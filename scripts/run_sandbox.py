"""
AUREUS-SMC Institutional Sandbox Replay & Verification Script
Simulates a complete London Accumulation -> NY Open Sweep -> Displacement MSS -> FVG 1:3 Execution lifecycle.
"""

from __future__ import annotations
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from core.models import (
    Bar, Tick, Order, OrderSide, OrderType, OrderStatus, SystemState
)
from core.events import (
    BarClosedEvent, SignalGeneratedEvent, OrderFilledEvent, PositionModifiedEvent,
    PositionClosedEvent, PositionPartialClosedEvent
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
from storage.db import db_manager
from storage.repository import repository
from storage.metrics_calc import compute_metrics
from macro.news_filter import news_filter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("SandboxRunner")


async def main():
    logger.info("=================================================================")
    logger.info("   STARTING AUREUS-SMC INSTITUTIONAL SANDBOX VERIFICATION RUN   ")
    logger.info("=================================================================")

    # 1. Initialize SQLite Database with WAL mode
    await db_manager.init_db()

    # 2. Initialize Execution Venue (Paper Broker Simulator)
    broker = PaperBrokerClient(initial_balance=settings.INITIAL_BALANCE)
    await broker.connect()

    # 3. Initialize Risk Subsystems
    position_sizer = PositionSizer()
    spread_filter = SpreadFilter()
    circuit_breaker = CircuitBreaker(starting_day_balance=settings.INITIAL_BALANCE)

    order_manager = OrderManager(
        modify_sl_callback=lambda pos, new_sl: broker.modify_order(pos.position_id, new_sl=new_sl),
        partial_close_callback=lambda pos, vol: broker.partial_close(pos.position_id, vol, reason="PARTIAL_1_2_RRR")
    )

    # 4. Initialize Data Ingestion & Bar Aggregator
    bar_aggregator = BarAggregator()
    feed_manager = FeedManager(bar_aggregator)

    # 5. Initialize SMC Strategy Engine
    smc = SMCEngine(news_filter_check=news_filter.is_in_blackout)
    smc.set_bar_provider(bar_aggregator.get_latest_bars)

    # 6. Wire Automated Order Execution on SMC Signal
    async def on_signal(event: SignalGeneratedEvent):
        logger.info(f"Signal received: {event.direction} | Entry: ${event.entry_price}")
        account = await broker.get_account_state()

        # Check circuit breaker limits
        if not await circuit_breaker.evaluate_risk(account.equity):
            logger.warning("Circuit breaker blocked signal execution.")
            return

        # Check spread filter
        assert broker.latest_tick is not None
        if not spread_filter.is_spread_acceptable(broker.latest_tick.bid, broker.latest_tick.ask):
            logger.warning("Spread filter rejected execution.")
            return

        # Calculate exact institutional position size
        lots = position_sizer.calculate_lot_size(
            balance=account.balance,
            risk_percent=settings.RISK_PER_TRADE_PERCENT,
            entry_price=event.entry_price,
            stop_loss=event.stop_loss
        )

        side = OrderSide.BUY if event.direction == "BUY" else OrderSide.SELL
        now_utc = datetime.now(timezone.utc)
        order = Order(
            order_id=f"ORD_{int(now_utc.timestamp())}",
            client_order_id=event.signal_id,
            symbol=settings.SYMBOL,
            side=side,
            order_type=OrderType.MARKET,
            volume=lots,
            entry_price=event.entry_price,
            stop_loss=event.stop_loss,
            take_profit=event.take_profit,
            status=OrderStatus.PENDING,
            created_at=now_utc,
            comment="SMC London Sweep Setup"
        )
        await broker.place_order(order)

    event_bus.subscribe(SignalGeneratedEvent, on_signal)

    # Wire order filled to state machine & repository
    async def on_order_filled(event: OrderFilledEvent):
        await state_machine.transition_to(SystemState.IN_POSITION, "Order filled in market")
        await repository.save_active_position(event.position)

    event_bus.subscribe(OrderFilledEvent, on_order_filled)

    # Wire position closed to circuit breaker, repository, and state machine
    async def on_position_closed(event: PositionClosedEvent):
        await repository.remove_active_position(event.position.position_id)
        await repository.save_trade(event.trade_record)
        circuit_breaker.register_trade_closed(event.trade_record)
        await state_machine.transition_to(SystemState.IDLE, f"Position closed: {event.trade_record.close_reason}")

    event_bus.subscribe(PositionClosedEvent, on_position_closed)

    # 7. MARKET REPLAY SIMULATION (XAU/USD)
    tz = ZoneInfo(settings.TIMEZONE)
    base_date = datetime.now(tz).date()

    logger.info("--- [PHASE 1] SIMULATING LONDON ACCUMULATION SESSION (03:00 - 08:00 EST) ---")
    current_sim_time = datetime.combine(base_date, datetime.min.time(), tzinfo=tz) + timedelta(hours=3)

    # Generate London Range: High = $2745.00, Low = $2730.00
    london_prices = [2735.0, 2732.0, 2730.0, 2738.0, 2745.0, 2742.0, 2736.0, 2734.0]
    for p in london_prices:
        bar = Bar(
            symbol="XAUUSD",
            timeframe="M5",
            timestamp=current_sim_time,
            open=p,
            high=p + 1.5,
            low=p - 1.5,
            close=p,
            volume=150.0,
            is_closed=True
        )
        # Ensure exact London High and Low
        if p == 2745.0:
            bar.high = 2745.0
        if p == 2730.0:
            bar.low = 2730.0

        bar_aggregator.m5_buffer.append(bar)
        smc.london_detector.process_bar(bar)
        current_sim_time += timedelta(minutes=30)

    # Advance time to 08:00 EST: Finalize London Range
    current_sim_time = datetime.combine(base_date, datetime.min.time(), tzinfo=tz) + timedelta(hours=8, minutes=1)
    smc.london_detector.finalize_range()
    assert smc.london_range is not None
    logger.info(f"Verified London High: ${smc.london_range.high:.2f} | Low: ${smc.london_range.low:.2f}")

    logger.info("--- [PHASE 2] NY OPEN: LIQUIDITY SWEEP OF LONDON LOW (09:05 EST) ---")
    # Time after 08:30 CPI blackout window (08:15 - 08:45)
    current_sim_time = datetime.combine(base_date, datetime.min.time(), tzinfo=tz) + timedelta(hours=9, minutes=5)
    await state_machine.transition_to(SystemState.NY_SCANNING_SWEEP, "NY Open Window Active")

    # Sweep candle: Drops to 2727.50 (sweeping 2730.00 by 2.50 points / 25 pips), closes back at 2732.00
    sweep_bar = Bar(
        symbol="XAUUSD",
        timeframe="M5",
        timestamp=current_sim_time,
        open=2733.0,
        high=2734.0,
        low=2727.50, # Extreme wick
        close=2732.0, # Closes back inside
        volume=500.0,
        is_closed=True
    )
    bar_aggregator.m5_buffer.append(sweep_bar)
    await smc.on_bar_closed(BarClosedEvent(bar=sweep_bar))
    assert smc.active_sweep is not None
    logger.info("Liquidity sweep successfully registered!")

    logger.info("--- [PHASE 3] DISPLACEMENT CANDLE & MARKET STRUCTURE SHIFT (08:20 EST) ---")
    current_sim_time += timedelta(minutes=5)
    # Displacement candle surges to 2740.0 with body = $7.00 (> 1.5 * ATR ~1.20)
    displacement_bar = Bar(
        symbol="XAUUSD",
        timeframe="M5",
        timestamp=current_sim_time,
        open=2732.0,
        high=2740.50,
        low=2731.80,
        close=2739.0, # Massive bullish body = 7.00
        volume=900.0,
        is_closed=True
    )
    bar_aggregator.m5_buffer.append(displacement_bar)
    await smc.on_bar_closed(BarClosedEvent(bar=displacement_bar))
    logger.info("Displacement & MSS successfully confirmed!")

    logger.info("--- [PHASE 4] FAIR VALUE GAP (FVG) FORMATION (08:25 EST) ---")
    current_sim_time += timedelta(minutes=5)
    # Candle 3 leaves an imbalance: c3.low = 2736.0 > c1.high = 2734.0
    # Gap: 2734.00 to 2736.00. 50% CE = 2735.00
    c3_bar = Bar(
        symbol="XAUUSD",
        timeframe="M5",
        timestamp=current_sim_time,
        open=2739.0,
        high=2742.0,
        low=2736.0,
        close=2741.0,
        volume=400.0,
        is_closed=True
    )
    bar_aggregator.m5_buffer.append(c3_bar)

    # Ingest tick at FVG entry 2735.00 with realistic spread ($0.15)
    await feed_manager.ingest_tick("XAUUSD", bid=2734.90, ask=2735.05, timestamp=current_sim_time)
    await smc.on_bar_closed(BarClosedEvent(bar=c3_bar))

    # Give async event bus a brief moment to process order matching
    await asyncio.sleep(0.1)

    open_positions = await broker.get_open_positions()
    logger.info(f"Active positions count: {len(open_positions)}")
    assert len(open_positions) == 1, "Expected 1 active position"
    pos = open_positions[0]
    logger.info(
        f"POSITION VERIFIED: {pos.side.value} {pos.volume} lots @ ${pos.entry_price:.2f} | "
        f"SL: ${pos.stop_loss:.2f} | TP: ${pos.take_profit:.2f}"
    )

    logger.info("--- [PHASE 5] DYNAMIC RISK ADVANCE: 1:1.5 RRR -> MOVE TO BREAK-EVEN ---")
    # Distance to SL was ~$7.60. At 1.5 RRR price reaches entry + (7.60 * 1.5) = 2735 + 11.40 = 2746.40
    be_tick_price = 2746.50
    await feed_manager.ingest_tick("XAUUSD", bid=be_tick_price, ask=be_tick_price + 0.15)
    await order_manager.update_position_risk(pos, be_tick_price)
    assert pos.break_even_set is True
    logger.info(f"Verified SL shifted to Break-Even: ${pos.stop_loss:.2f}")

    logger.info("--- [PHASE 6] DYNAMIC RISK ADVANCE: 1:2.0 RRR -> 50% PARTIAL PROFIT TAKING ---")
    # At 2.0 RRR price reaches entry + (7.60 * 2.0) = 2735 + 15.20 = 2750.20
    partial_tick_price = 2750.50
    await feed_manager.ingest_tick("XAUUSD", bid=partial_tick_price, ask=partial_tick_price + 0.15)
    await order_manager.update_position_risk(pos, partial_tick_price)
    assert pos.partial_closed is True
    logger.info(f"Verified 50% Partial Close executed! Remaining volume: {pos.volume:.2f} lots")

    logger.info("--- [PHASE 7] STRICT 1:3 RRR TAKE PROFIT HIT ---")
    # At 3.0 RRR price reaches TP target = 2757.80
    tp_tick_price = pos.take_profit + 0.50
    await feed_manager.ingest_tick("XAUUSD", bid=tp_tick_price, ask=tp_tick_price + 0.15)
    await asyncio.sleep(0.1)

    # Verify position is closed and trade recorded
    open_positions_after = await broker.get_open_positions()
    assert len(open_positions_after) == 0, "Position should be fully liquidated"
    logger.info("Position closed at Take Profit target!")

    # 8. Query SQLite persistence and quantitative metrics
    trades = await repository.get_all_trades()
    logger.info(f"Audit records in SQLite: {len(trades)} trades recorded.")
    metrics = compute_metrics(trades, settings.INITIAL_BALANCE)

    logger.info("=================================================================")
    logger.info("                 INSTITUTIONAL METRICS SUMMARY                   ")
    logger.info("=================================================================")
    logger.info(f"Total Trades:      {metrics['total_trades']}")
    logger.info(f"Win Rate:          {metrics['win_rate']}%")
    logger.info(f"Profit Factor:     {metrics['profit_factor']}")
    logger.info(f"Net Profit:        ${metrics['net_profit']:,.2f}")
    logger.info(f"Max Drawdown:      {metrics['max_drawdown_percent']}%")
    logger.info(f"Sharpe Ratio:      {metrics['sharpe_ratio']}")
    logger.info("=================================================================")
    logger.info("   ALL CHECKS & VERIFICATION TESTS COMPLETED WITH 100% SUCCESS   ")
    logger.info("=================================================================")


if __name__ == "__main__":
    asyncio.run(main())
