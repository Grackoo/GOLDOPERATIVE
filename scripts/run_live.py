"""
AUREUS-SMC Production Live Engine & Web Dashboard Launcher
Coordinates the event bus, broker gateway, SMC algorithmic engine, and FastAPI server.
"""

from __future__ import annotations
import asyncio
import logging
import signal
import sys
from pathlib import Path
import uvicorn

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from core.models import (
    Bar, Tick, Order, OrderSide, OrderType, OrderStatus, SystemState
)
from core.events import (
    SignalGeneratedEvent, OrderFilledEvent, PositionClosedEvent
)
from core.event_bus import event_bus
from core.state_machine import state_machine
from core.time_manager import time_manager
from data.bar_aggregator import BarAggregator
from data.feed_manager import FeedManager
from strategy.smc_engine import SMCEngine
from risk.position_sizer import PositionSizer
from risk.spread_filter import SpreadFilter
from risk.circuit_breaker import CircuitBreaker
from risk.order_manager import OrderManager
from execution.paper_broker import PaperBrokerClient
from execution.mt5_broker import MT5BrokerClient
from execution.oanda_broker import OandaBrokerClient
from storage.db import db_manager
from storage.repository import repository
from macro.news_filter import news_filter
from web.server import app

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("LiveLauncher")


class AureusTradingSystem:
    """
    Main orchestration wrapper for live institutional execution.
    """

    def __init__(self) -> None:
        self.running = False
        self.bar_aggregator = BarAggregator()
        self.feed_manager = FeedManager(self.bar_aggregator)

        # Select Broker Gateway
        if settings.BROKER_TYPE == "MT5":
            self.broker = MT5BrokerClient()
        elif settings.BROKER_TYPE == "OANDA":
            self.broker = OandaBrokerClient()
        else:
            self.broker = PaperBrokerClient(initial_balance=settings.INITIAL_BALANCE)

        self.position_sizer = PositionSizer()
        self.spread_filter = SpreadFilter()
        self.circuit_breaker = CircuitBreaker(starting_day_balance=settings.INITIAL_BALANCE)

        self.order_manager = OrderManager(
            modify_sl_callback=lambda pos, new_sl: self.broker.modify_order(pos.position_id, new_sl=new_sl),
            partial_close_callback=lambda pos, vol: self.broker.partial_close(pos.position_id, vol, reason="PARTIAL_1_2_RRR")
        )

        self.smc_engine = SMCEngine(news_filter_check=news_filter.is_in_blackout)
        self.smc_engine.set_bar_provider(self.bar_aggregator.get_latest_bars)

    async def initialize(self) -> None:
        """Initializes database, connects broker, and rehydrates state."""
        logger.info(f"Initializing {settings.SYSTEM_NAME} in [{settings.ENVIRONMENT}] mode...")
        await db_manager.init_db()

        # Connect Broker
        connected = await self.broker.connect()
        if not connected:
            logger.warning("Broker connection failed or running in fallback. Check credentials.")

        # Initialize Macro Calendar
        await news_filter.initialize()

        # State Rehydration: Restore active positions from SQLite
        rehydrated = await repository.rehydrate_positions()
        if rehydrated:
            logger.info(f"State Rehydrated: Loaded {len(rehydrated)} active positions into order manager.")
            await state_machine.transition_to(SystemState.IN_POSITION, "Rehydrated active market positions")
        else:
            await state_machine.transition_to(SystemState.IDLE, "Engine initialized cleanly. Standby.")

        # Wire event subscriptions
        event_bus.subscribe(SignalGeneratedEvent, self.on_signal)
        event_bus.subscribe(OrderFilledEvent, self.on_order_filled)
        event_bus.subscribe(PositionClosedEvent, self.on_position_closed)

        self.running = True

    async def on_signal(self, event: SignalGeneratedEvent) -> None:
        """Processes automated order placement upon verified SMC signal."""
        logger.info(f"Signal received: {event.direction} | Entry: ${event.entry_price}")
        account = await self.broker.get_account_state()

        # Check circuit breaker
        if not await self.circuit_breaker.evaluate_risk(account.equity):
            logger.warning("Signal blocked: Circuit breaker limits reached.")
            return

        # Check spread filter
        if self.feed_manager.latest_tick:
            if not self.spread_filter.is_spread_acceptable(
                self.feed_manager.latest_tick.bid, self.feed_manager.latest_tick.ask
            ):
                logger.warning("Signal aborted: Microstructure spread exceeded threshold.")
                return

        lots = self.position_sizer.calculate_lot_size(
            balance=account.balance,
            risk_percent=settings.RISK_PER_TRADE_PERCENT,
            entry_price=event.entry_price,
            stop_loss=event.stop_loss
        )

        side = OrderSide.BUY if event.direction == "BUY" else OrderSide.SELL
        order = Order(
            order_id=f"ORD_{int(datetime.utcnow().timestamp())}",
            client_order_id=event.signal_id,
            symbol=settings.SYMBOL,
            side=side,
            order_type=OrderType.MARKET,
            volume=lots,
            entry_price=event.entry_price,
            stop_loss=event.stop_loss,
            take_profit=event.take_profit,
            status=OrderStatus.PENDING,
            created_at=datetime.utcnow(),
            comment=f"SMC {event.reason[:25]}"
        )
        await self.broker.place_order(order)

    async def on_order_filled(self, event: OrderFilledEvent) -> None:
        await state_machine.transition_to(SystemState.IN_POSITION, "Order filled in market")
        await repository.save_active_position(event.position)

    async def on_position_closed(self, event: PositionClosedEvent) -> None:
        await repository.remove_active_position(event.position.position_id)
        await repository.save_trade(event.trade_record)
        self.circuit_breaker.register_trade_closed(event.trade_record)
        await state_machine.transition_to(SystemState.IDLE, f"Closed: {event.trade_record.close_reason}")

    async def shutdown(self) -> None:
        """Graceful shutdown protocol."""
        logger.info("Executing graceful system shutdown...")
        self.running = False
        await self.broker.disconnect()
        await event_bus.stop()
        logger.info("System halted cleanly.")


async def start_server_and_engine():
    trading_system = AureusTradingSystem()
    await trading_system.initialize()

    # Share bar aggregator and feed manager reference with FastAPI
    app.state.bar_aggregator = trading_system.bar_aggregator
    app.state.feed_manager = trading_system.feed_manager

    feed_task = None
    real_stream = None

    # 1. Connect Real-Time Live Gold (XAU/USD) Data Stream
    if settings.DATA_FEED_SOURCE == "REAL_GOLD":
        from data.live_feed import RealGoldStreamFeed
        real_stream = RealGoldStreamFeed(trading_system.feed_manager, trading_system.bar_aggregator)
        await real_stream.start()

        # Compute actual London Range from loaded history
        for b in trading_system.bar_aggregator.m5_buffer:
            trading_system.smc_engine.london_detector.process_bar(b)
        if trading_system.smc_engine.london_range:
            trading_system.smc_engine.london_detector.finalize_range()

    elif settings.DATA_FEED_SOURCE == "MT5":
        from data.live_feed import MT5LiveFeed
        mt5_feed = MT5LiveFeed(trading_system.feed_manager)
        await mt5_feed.start()

    else:
        # Fallback synthetic simulator
        import random
        from datetime import datetime, timedelta, timezone
        from core.models import Bar, LondonRange
        from core.events import LondonRangeCalculatedEvent

        now_utc = datetime.now(timezone.utc)
        base_p = 2736.0

        for i in range(120, 0, -1):
            t = now_utc - timedelta(minutes=i)
            base_p += random.uniform(-0.4, 0.4)
            h = round(base_p + random.uniform(0.1, 0.5), 2)
            l = round(base_p - random.uniform(0.1, 0.5), 2)
            c = round(base_p, 2)
            o = round(c + random.uniform(-0.2, 0.2), 2)
            b = Bar(settings.SYMBOL, "M1", t, o, h, l, c, random.randint(30, 150), is_closed=True)
            trading_system.bar_aggregator.m1_buffer.append(b)

        async def _market_feed_loop():
            curr = 2736.0
            while trading_system.running:
                try:
                    curr += random.uniform(-0.15, 0.15)
                    curr = round(curr, 2)
                    spread = round(random.uniform(0.14, 0.24), 2)
                    bid = round(curr - (spread / 2.0), 2)
                    ask = round(bid + spread, 2)
                    ts = datetime.now(timezone.utc)
                    await trading_system.feed_manager.ingest_tick(settings.SYMBOL, bid, ask, timestamp=ts)
                    await asyncio.sleep(1.0)
                except asyncio.CancelledError:
                    break
                except Exception as ex:
                    logger.error(f"Feed simulator error: {ex}")
                    await asyncio.sleep(1.0)

        feed_task = asyncio.create_task(_market_feed_loop())
        logger.info("Live market tick simulator active (1 Hz tick updates).")

    # Configure Uvicorn Web Server
    config = uvicorn.Config(
        app=app,
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        log_level="warning",
        access_log=False
    )
    server = uvicorn.Server(config)

    logger.info(f"Dashboard Web Server active at http://{settings.WEB_HOST}:{settings.WEB_PORT}")
    try:
        await server.serve()
    finally:
        if real_stream:
            await real_stream.stop()
        if feed_task:
            feed_task.cancel()
        await trading_system.shutdown()


def main():
    try:
        asyncio.run(start_server_and_engine())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Termination signal received. Exiting.")


if __name__ == "__main__":
    main()
