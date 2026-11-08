"""
AUREUS-SMC Institutional Domain Models & Type Specifications
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


class SystemState(str, Enum):
    INIT = "INIT"
    IDLE = "IDLE"
    LONDON_ACCUMULATION = "LONDON_ACCUMULATION"
    NY_SCANNING_SWEEP = "NY_SCANNING_SWEEP"
    NY_SCANNING_DISPLACEMENT = "NY_SCANNING_DISPLACEMENT"
    NY_SCANNING_FVG = "NY_SCANNING_FVG"
    PENDING_ORDER = "PENDING_ORDER"
    IN_POSITION = "IN_POSITION"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    COOLDOWN = "COOLDOWN"


class NewsImpact(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(slots=True, frozen=True)
class Tick:
    """Microsecond-precision price tick for XAU/USD."""
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    volume: float = 1.0

    @property
    def mid(self) -> float:
        return round((self.bid + self.ask) / 2.0, 3)

    @property
    def spread(self) -> float:
        return round(self.ask - self.bid, 3)


@dataclass(slots=True)
class Bar:
    """Completed or updating candlestick bar."""
    symbol: str
    timeframe: str  # e.g., 'M1', 'M5'
    timestamp: datetime  # Opening time
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    is_closed: bool = False

    @property
    def body_size(self) -> float:
        return round(abs(self.close - self.open), 3)

    @property
    def full_range(self) -> float:
        return round(self.high - self.low, 3)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def upper_wick(self) -> float:
        return round(self.high - max(self.open, self.close), 3)

    @property
    def lower_wick(self) -> float:
        return round(min(self.open, self.close) - self.low, 3)


@dataclass(slots=True)
class LondonRange:
    """London Session High & Low liquidity boundaries (03:00 - 08:00 EST)."""
    date_str: str
    high: float
    low: float
    high_time: Optional[datetime] = None
    low_time: Optional[datetime] = None
    range_size: float = 0.0
    is_finalized: bool = False

    def update(self, high: float, low: float, high_time: datetime, low_time: datetime):
        if high > self.high:
            self.high = high
            self.high_time = high_time
        if low < self.low:
            self.low = low
            self.low_time = low_time
        self.range_size = round(self.high - self.low, 2)


@dataclass(slots=True)
class LiquiditySweep:
    """Validated Institutional Liquidity Sweep."""
    direction: OrderSide  # BUY = swept low (liquidity grab for buy); SELL = swept high
    level_swept: float    # London High or Low
    wick_extreme: float   # Max price reached during sweep
    close_price: float    # Returned inside price
    timestamp: datetime
    penetration_pips: float


@dataclass(slots=True)
class MarketStructureShift:
    """Institutional Displacement & Market Structure Shift (MSS/CHOCH)."""
    direction: OrderSide  # BUY (shift to bullish) or SELL (shift to bearish)
    broken_swing_level: float
    displacement_candle: Bar
    displacement_atr: float
    body_to_atr_ratio: float
    timestamp: datetime


@dataclass(slots=True)
class FairValueGap:
    """3-candle imbalance (Fair Value Gap)."""
    direction: OrderSide  # BUY: candle 3 low > candle 1 high; SELL: candle 3 high < candle 1 low
    top: float
    bottom: float
    consequent_encroachment: float  # 50% midpoint
    candle_1: Bar
    candle_2: Bar  # The displacement candle
    candle_3: Bar
    timestamp: datetime
    is_mitigated: bool = False
    mitigated_at: Optional[datetime] = None

    @classmethod
    def create(cls, direction: OrderSide, c1: Bar, c2: Bar, c3: Bar, timestamp: datetime) -> FairValueGap:
        if direction == OrderSide.BUY:
            top = c3.low
            bottom = c1.high
        else:
            top = c1.low
            bottom = c3.high
        ce = round((top + bottom) / 2.0, 2)
        return cls(
            direction=direction,
            top=round(top, 2),
            bottom=round(bottom, 2),
            consequent_encroachment=ce,
            candle_1=c1,
            candle_2=c2,
            candle_3=c3,
            timestamp=timestamp
        )


@dataclass(slots=True)
class Order:
    """Internal institutional order descriptor."""
    order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    status: OrderStatus
    created_at: datetime
    filled_at: Optional[datetime] = None
    filled_price: Optional[float] = None
    slippage: float = 0.0
    commission: float = 0.0
    comment: str = ""


@dataclass(slots=True)
class Position:
    """Live open market position with institutional tracking."""
    position_id: str
    ticket: int
    symbol: str
    side: OrderSide
    volume: float
    original_volume: float
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    original_sl: float
    original_tp: float
    break_even_set: bool = False
    partial_closed: bool = False
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    commission_paid: float = 0.0
    swap_paid: float = 0.0
    status: PositionStatus = PositionStatus.OPEN

    @property
    def r_risk_distance(self) -> float:
        return abs(self.entry_price - self.original_sl)

    def current_r_multiple(self) -> float:
        if self.r_risk_distance == 0.0:
            return 0.0
        if self.side == OrderSide.BUY:
            return round((self.current_price - self.entry_price) / self.r_risk_distance, 2)
        else:
            return round((self.entry_price - self.current_price) / self.r_risk_distance, 2)


@dataclass(slots=True)
class TradeRecord:
    """Completed trade record for SQLite persistence and quantitative analytics."""
    trade_id: str
    position_id: str
    symbol: str
    side: OrderSide
    volume: float
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    r_multiple_realized: float
    net_pnl: float
    gross_pnl: float
    commission: float
    slippage: float
    open_time: datetime
    close_time: datetime
    close_reason: str  # TP, SL, BE, PARTIAL_TP, MANUAL, CIRCUIT_BREAKER
    smc_setup_type: str = "LONDON_SWEEP_NY_DISPLACEMENT"


@dataclass(slots=True)
class AccountState:
    """Live account balance, equity and risk exposure snapshot."""
    balance: float
    equity: float
    free_margin: float
    margin_used: float
    unrealized_pnl: float
    realized_daily_pnl: float
    daily_drawdown_percent: float
    trades_executed_today: int
    is_circuit_breaker_active: bool
    timestamp: datetime


@dataclass(slots=True)
class EconomicNewsEvent:
    """Macroeconomic news calendar event."""
    title: str
    currency: str
    impact: NewsImpact
    scheduled_time: datetime
    forecast: Optional[str] = None
    previous: Optional[str] = None
    actual: Optional[str] = None
