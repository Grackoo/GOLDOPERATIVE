"""
AUREUS-SMC Institutional Event System
Strongly typed event contracts for the asynchronous Event Bus.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from core.models import (
    Tick, Bar, LondonRange, LiquiditySweep, MarketStructureShift,
    FairValueGap, Order, Position, TradeRecord, AccountState, EconomicNewsEvent,
    SystemState
)


@dataclass(slots=True)
class BaseEvent:
    """Base class for all system events."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = field(default_factory=lambda: f"EVT_{datetime.now(timezone.utc).timestamp()}")


@dataclass(slots=True)
class TickEvent(BaseEvent):
    """Fired on every incoming tick from data feed."""
    tick: Tick = field(default=None) # type: ignore


@dataclass(slots=True)
class BarClosedEvent(BaseEvent):
    """Fired when an M1 or M5 candlestick completes and closes."""
    bar: Bar = field(default=None) # type: ignore


@dataclass(slots=True)
class BarUpdateEvent(BaseEvent):
    """Fired on real-time price updates within the currently forming bar."""
    bar: Bar = field(default=None) # type: ignore


@dataclass(slots=True)
class LondonRangeCalculatedEvent(BaseEvent):
    """Fired when London session completes (08:00 EST) and high/low are locked."""
    london_range: LondonRange = field(default=None) # type: ignore


@dataclass(slots=True)
class LiquiditySweepEvent(BaseEvent):
    """Fired when an institutional sweep of London range is detected & confirmed."""
    sweep: LiquiditySweep = field(default=None) # type: ignore


@dataclass(slots=True)
class DisplacementEvent(BaseEvent):
    """Fired when Market Structure Shift (MSS) with ATR displacement is confirmed."""
    mss: MarketStructureShift = field(default=None) # type: ignore


@dataclass(slots=True)
class FVGDetectedEvent(BaseEvent):
    """Fired when a valid Fair Value Gap is formed after displacement."""
    fvg: FairValueGap = field(default=None) # type: ignore


@dataclass(slots=True)
class SignalGeneratedEvent(BaseEvent):
    """Fired by SMC strategy when all confluences align for execution."""
    signal_id: str = ""
    symbol: str = "XAUUSD"
    direction: str = ""  # "BUY" or "SELL"
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward_ratio: float = 3.0
    fvg: Optional[FairValueGap] = None
    reason: str = ""


@dataclass(slots=True)
class OrderSubmittedEvent(BaseEvent):
    """Fired when an order is dispatched to the broker gateway."""
    order: Order = field(default=None) # type: ignore


@dataclass(slots=True)
class OrderFilledEvent(BaseEvent):
    """Fired when an order fill is confirmed by the broker gateway."""
    order: Order = field(default=None) # type: ignore
    position: Position = field(default=None) # type: ignore


@dataclass(slots=True)
class PositionModifiedEvent(BaseEvent):
    """Fired when SL is moved to Break-Even or trailing."""
    position: Position = field(default=None) # type: ignore
    modification_type: str = "BREAK_EVEN"
    new_sl: float = 0.0


@dataclass(slots=True)
class PositionPartialClosedEvent(BaseEvent):
    """Fired when 50% partial close at 1:2 RRR is executed."""
    position: Position = field(default=None) # type: ignore
    closed_volume: float = 0.0
    realized_pnl: float = 0.0


@dataclass(slots=True)
class PositionClosedEvent(BaseEvent):
    """Fired when a position is fully liquidated (TP, SL, BE, or Manual)."""
    position: Position = field(default=None) # type: ignore
    trade_record: TradeRecord = field(default=None) # type: ignore


@dataclass(slots=True)
class CircuitBreakerTriggeredEvent(BaseEvent):
    """Fired when risk limits (Max trades or Daily Drawdown 2%) are breached."""
    reason: str = ""
    current_drawdown: float = 0.0
    trades_count: int = 0


@dataclass(slots=True)
class SystemStateChangedEvent(BaseEvent):
    """Fired when the institutional state machine transitions."""
    previous_state: SystemState = SystemState.INIT
    new_state: SystemState = SystemState.IDLE
    reason: str = ""


@dataclass(slots=True)
class NewsBlackoutEvent(BaseEvent):
    """Fired when entering or leaving a high-impact news blackout window."""
    is_active: bool = False
    event: Optional[EconomicNewsEvent] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


@dataclass(slots=True)
class AccountUpdateEvent(BaseEvent):
    """Fired periodically or on equity updates."""
    account: AccountState = field(default=None) # type: ignore
