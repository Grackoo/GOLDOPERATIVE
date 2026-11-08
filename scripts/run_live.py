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
        await trading_system.shutdown()


def main():
    try:
        asyncio.run(start_server_and_engine())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Termination signal received. Exiting.")


if __name__ == "__main__":
    main()
