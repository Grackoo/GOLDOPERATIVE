"""
AUREUS-SMC Institutional Paper Trading Simulator
Realistic matching engine with sub-millisecond tick matching, latency simulation, and stochastic slippage.
"""

from __future__ import annotations
import asyncio
import logging
import random
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from core.models import (
    Order, Position, TradeRecord, AccountState, Tick,
    OrderSide, OrderType, OrderStatus, PositionStatus
)
from core.events import (
    OrderSubmittedEvent, OrderFilledEvent, PositionModifiedEvent,
    PositionPartialClosedEvent, PositionClosedEvent, AccountUpdateEvent, TickEvent
)
from core.event_bus import event_bus
from execution.base_broker import BaseBrokerClient
from config import settings

logger = logging.getLogger("PaperBroker")


class PaperBrokerClient(BaseBrokerClient):
    """
    High-fidelity simulation matching engine for XAU/USD.
    Emulates ECN liquidity conditions:
    - Network latency jitter (10ms - 35ms)
    - Stochastic tick slippage
    - Exact Gold CFD contract specifications (100 oz per lot, $0.01 tick size)
    - Full trade accounting with roundtrip commissions ($6/lot)
    """

    def __init__(
        self,
        initial_balance: float = settings.INITIAL_BALANCE,
        latency_min_ms: float = settings.SIMULATED_LATENCY_MIN_MS,
        latency_max_ms: float = settings.SIMULATED_LATENCY_MAX_MS,
        slippage_prob: float = settings.SIMULATED_SLIPPAGE_PROBABILITY
    ) -> None:
        self.balance: float = initial_balance
        self.initial_balance: float = initial_balance
        self.latency_min_ms = latency_min_ms
        self.latency_max_ms = latency_max_ms
        self.slippage_prob = slippage_prob

        self.positions: Dict[str, Position] = {}
        self.pending_orders: Dict[str, Order] = {}
        self.trade_history: List[TradeRecord] = []
        self.latest_tick: Optional[Tick] = None
        self._ticket_counter: int = 100_000

        # Subscribe to incoming ticks for position evaluation
        event_bus.subscribe(TickEvent, self.on_tick)

    async def connect(self) -> bool:
        logger.info(f"Connected to Paper Trading Simulator. Initial Capital: ${self.balance:,.2f}")
        return True

    async def disconnect(self) -> None:
        logger.info("Disconnected from Paper Trading Simulator.")

    async def _simulate_latency(self) -> None:
        """Injects realistic network transmission delay."""
        delay = random.uniform(self.latency_min_ms, self.latency_max_ms) / 1000.0
        await asyncio.sleep(delay)

    def _calculate_slippage(self, side: OrderSide) -> float:
        """Simulates microsecond queue positioning and execution slippage."""
        if random.random() < self.slippage_prob:
            # Random slippage 1 to 4 ticks against the order
            ticks_slip = random.randint(1, 4)
            slip = ticks_slip * settings.TICK_SIZE
            return round(slip, 2)
        return 0.0

    async def place_order(self, order: Order) -> Order:
        """Processes order entry with latency and matching."""
        await self._simulate_latency()

        if not self.latest_tick:
            order.status = OrderStatus.REJECTED
            order.comment = "No market price available"
            return order

        # Handle Market Execution
        if order.order_type == OrderType.MARKET:
            return await self._fill_market_order(order)
        elif order.order_type == OrderType.LIMIT:
            # Store pending limit order
            order.status = OrderStatus.PENDING
            self.pending_orders[order.order_id] = order
            logger.info(f"Pending Limit Order stored: {order.order_id} @ {order.entry_price}")
            return order

        return order

    async def _fill_market_order(self, order: Order, fill_price_override: Optional[float] = None) -> Order:
        assert self.latest_tick is not None
        slippage = self._calculate_slippage(order.side)

        if fill_price_override is not None:
            raw_fill = fill_price_override
        else:
            raw_fill = self.latest_tick.ask if order.side == OrderSide.BUY else self.latest_tick.bid

        # Slippage is against trader
        if order.side == OrderSide.BUY:
            final_fill_price = round(raw_fill + slippage, 2)
        else:
            final_fill_price = round(raw_fill - slippage, 2)

        self._ticket_counter += 1
        ticket = self._ticket_counter
        commission = round(order.volume * settings.COMMISSION_PER_LOT_ROUNDTRIP, 2)

        order.status = OrderStatus.FILLED
        order.filled_at = datetime.utcnow()
        order.filled_price = final_fill_price
        order.slippage = slippage
        order.commission = commission

        # Create live open position
        position = Position(
            position_id=str(uuid.uuid4())[:8],
            ticket=ticket,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
            original_volume=order.volume,
            entry_price=final_fill_price,
            current_price=final_fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            original_sl=order.stop_loss,
            original_tp=order.take_profit,
            opened_at=order.filled_at,
            commission_paid=commission
        )
        self.positions[position.position_id] = position

        logger.info(
            f"ORDER FILLED: Ticket #{ticket} | {order.side.value} {order.volume} lots {order.symbol} @ "
            f"${final_fill_price:.2f} (Slip: ${slippage:.2f}) | SL: {order.stop_loss} | TP: {order.take_profit}"
        )

        # Notify via event bus
        await event_bus.publish(OrderFilledEvent(order=order, position=position))
        return order

    async def modify_order(
        self,
        position_id: str,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None
    ) -> bool:
        """Modifies SL/TP parameters of an open position."""
        await self._simulate_latency()
        if position_id not in self.positions:
            return False

        pos = self.positions[position_id]
        if new_sl is not None:
            pos.stop_loss = round(new_sl, 2)
        if new_tp is not None:
            pos.take_profit = round(new_tp, 2)

        logger.info(f"Position {position_id} modified: SL={pos.stop_loss}, TP={pos.take_profit}")
        return True

    async def partial_close(
        self,
        position_id: str,
        volume: float,
        reason: str = "PARTIAL_TP"
    ) -> Optional[TradeRecord]:
        """Liquidates a portion of open volume and realizes PnL."""
        await self._simulate_latency()
        if position_id not in self.positions or not self.latest_tick:
            return None

        pos = self.positions[position_id]
        if volume >= pos.volume:
            return await self.close_position(position_id, reason=reason)

        exit_price = self.latest_tick.bid if pos.side == OrderSide.BUY else self.latest_tick.ask
        gross_pnl = self._calculate_realized_pnl(pos.side, pos.entry_price, exit_price, volume)
        comm = round(volume * settings.COMMISSION_PER_LOT_ROUNDTRIP, 2)
        net_pnl = round(gross_pnl - comm, 2)

        self.balance += net_pnl
        pos.volume = round(pos.volume - volume, 2)
        pos.partial_closed = True
        pos.status = PositionStatus.PARTIALLY_CLOSED

        trade_record = TradeRecord(
            trade_id=f"TRD_{uuid.uuid4().hex[:8]}",
            position_id=pos.position_id,
            symbol=pos.symbol,
            side=pos.side,
            volume=volume,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            r_multiple_realized=pos.current_r_multiple(),
            net_pnl=net_pnl,
            gross_pnl=gross_pnl,
            commission=comm,
            slippage=0.0,
            open_time=pos.opened_at,
            close_time=datetime.utcnow(),
            close_reason=reason
        )
        self.trade_history.append(trade_record)

        logger.info(
            f"PARTIAL CLOSE: {pos.position_id} liquidated {volume} lots @ ${exit_price:.2f}. "
            f"Realized PnL: ${net_pnl:,.2f} | Remaining volume: {pos.volume} lots"
        )
        await event_bus.publish(PositionClosedEvent(position=pos, trade_record=trade_record))
        return trade_record

    async def close_position(self, position_id: str, reason: str = "MANUAL") -> Optional[TradeRecord]:
        """Liquidates entire remaining position."""
        await self._simulate_latency()
        if position_id not in self.positions or not self.latest_tick:
            return None

        pos = self.positions.pop(position_id)
        exit_price = self.latest_tick.bid if pos.side == OrderSide.BUY else self.latest_tick.ask
        gross_pnl = self._calculate_realized_pnl(pos.side, pos.entry_price, exit_price, pos.volume)
        comm = round(pos.volume * settings.COMMISSION_PER_LOT_ROUNDTRIP, 2)
        net_pnl = round(gross_pnl - comm, 2)

        self.balance += net_pnl
        pos.status = PositionStatus.CLOSED

        trade_record = TradeRecord(
            trade_id=f"TRD_{uuid.uuid4().hex[:8]}",
            position_id=pos.position_id,
            symbol=pos.symbol,
            side=pos.side,
            volume=pos.volume,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            r_multiple_realized=pos.current_r_multiple(),
            net_pnl=net_pnl,
            gross_pnl=gross_pnl,
            commission=comm,
            slippage=0.0,
            open_time=pos.opened_at,
            close_time=datetime.utcnow(),
            close_reason=reason
        )
        self.trade_history.append(trade_record)

        logger.info(
            f"POSITION CLOSED: {pos.position_id} liquidated {pos.volume} lots @ ${exit_price:.2f} [{reason}]. "
            f"Net PnL: ${net_pnl:,.2f} | New Balance: ${self.balance:,.2f}"
        )

        await event_bus.publish(PositionClosedEvent(position=pos, trade_record=trade_record))
        return trade_record

    def _calculate_realized_pnl(self, side: OrderSide, entry: float, exit_p: float, volume: float) -> float:
        """Exact CFD contract PnL calculation: (exit - entry) * 100 oz * volume."""
        if side == OrderSide.BUY:
            diff = exit_p - entry
        else:
            diff = entry - exit_p
        return round(diff * settings.CONTRACT_SIZE * volume, 2)

    async def on_tick(self, event: TickEvent) -> None:
        """Processes incoming tick against active positions and pending limit orders."""
        self.latest_tick = event.tick
        tick = event.tick

        # 1. Match Pending Limit Orders
        for order_id, order in list(self.pending_orders.items()):
            if order.side == OrderSide.BUY and tick.ask <= order.entry_price:
                del self.pending_orders[order_id]
                await self._fill_market_order(order, fill_price_override=order.entry_price)
            elif order.side == OrderSide.SELL and tick.bid >= order.entry_price:
                del self.pending_orders[order_id]
                await self._fill_market_order(order, fill_price_override=order.entry_price)

        # 2. Check Open Positions for SL or TP breach
        for pos_id, pos in list(self.positions.items()):
            pos.current_price = tick.bid if pos.side == OrderSide.BUY else tick.ask
            pos.unrealized_pnl = self._calculate_realized_pnl(
                pos.side, pos.entry_price, pos.current_price, pos.volume
            )

            # Check SL Trigger
            if pos.side == OrderSide.BUY and tick.bid <= pos.stop_loss:
                logger.info(f"STOP LOSS HIT for BUY {pos.position_id} at {tick.bid} (SL: {pos.stop_loss})")
                await self.close_position(pos.position_id, reason="SL")
            elif pos.side == OrderSide.SELL and tick.ask >= pos.stop_loss:
                logger.info(f"STOP LOSS HIT for SELL {pos.position_id} at {tick.ask} (SL: {pos.stop_loss})")
                await self.close_position(pos.position_id, reason="SL")

            # Check TP Trigger
            elif pos.side == OrderSide.BUY and tick.bid >= pos.take_profit:
                logger.info(f"TAKE PROFIT HIT for BUY {pos.position_id} at {tick.bid} (TP: {pos.take_profit})")
                await self.close_position(pos.position_id, reason="TP")
            elif pos.side == OrderSide.SELL and tick.ask <= pos.take_profit:
                logger.info(f"TAKE PROFIT HIT for SELL {pos.position_id} at {tick.ask} (TP: {pos.take_profit})")
                await self.close_position(pos.position_id, reason="TP")

    async def get_open_positions(self) -> List[Position]:
        return list(self.positions.values())

    async def get_account_state(self) -> AccountState:
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        equity = round(self.balance + unrealized, 2)
        # Margin: 1 lot Gold = 100 oz * price / leverage (e.g. 1:100 leverage = 1% margin)
        margin_used = sum(
            round((p.volume * settings.CONTRACT_SIZE * p.current_price) / 100.0, 2)
            for p in self.positions.values()
        )
        free_margin = round(equity - margin_used, 2)
        realized_today = sum(t.net_pnl for t in self.trade_history)

        dd_pct = 0.0
        if self.initial_balance > 0:
            dd_dollars = max(0.0, self.initial_balance - equity)
            dd_pct = round((dd_dollars / self.initial_balance) * 100.0, 2)

        state = AccountState(
            balance=round(self.balance, 2),
            equity=equity,
            free_margin=free_margin,
            margin_used=margin_used,
            unrealized_pnl=round(unrealized, 2),
            realized_daily_pnl=round(realized_today, 2),
            daily_drawdown_percent=dd_pct,
            trades_executed_today=len(self.trade_history),
            is_circuit_breaker_active=(dd_pct >= settings.MAX_DAILY_DRAWDOWN_PERCENT),
            timestamp=datetime.utcnow()
        )
        return state
