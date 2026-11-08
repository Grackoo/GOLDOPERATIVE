"""
AUREUS-SMC Institutional Circuit Breakers & Kill Switches
Enforces mandatory capital preservation barriers (Max Trades & 2% Max Daily Drawdown).
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional
from core.models import SystemState, TradeRecord
from core.events import CircuitBreakerTriggeredEvent
from core.event_bus import event_bus
from core.state_machine import state_machine
from config import settings

logger = logging.getLogger("CircuitBreaker")


class CircuitBreaker:
    """
    Continuous risk sentinel monitoring daily metrics.
    Triggers hard stop if drawdown exceeds 2.0% or 2 trades are executed in the session.
    """

    def __init__(
        self,
        max_daily_drawdown_percent: float = settings.MAX_DAILY_DRAWDOWN_PERCENT,
        max_trades_per_session: int = settings.MAX_TRADES_PER_SESSION,
        starting_day_balance: float = settings.INITIAL_BALANCE
    ) -> None:
        self.max_daily_drawdown_percent = max_daily_drawdown_percent
        self.max_trades_per_session = max_trades_per_session

        self.starting_day_balance = starting_day_balance
        self.daily_trades_count: int = 0
        self.daily_realized_pnl: float = 0.0
        self.is_tripped: bool = False
        self.trip_reason: str = ""

    def register_trade_closed(self, trade: TradeRecord) -> None:
        """Updates internal daily accounting when a trade concludes."""
        self.daily_trades_count += 1
        self.daily_realized_pnl += trade.net_pnl
        logger.info(
            f"CIRCUIT BREAKER ACCRUAL: Trades Today={self.daily_trades_count}/{self.max_trades_per_session} | "
            f"Daily Net PnL=${self.daily_realized_pnl:,.2f}"
        )

    async def evaluate_risk(self, current_equity: float) -> bool:
        """
        Evaluates equity and trade count against institutional risk guardrails.
        Returns True if safe to continue, False if a circuit breaker tripped.
        """
        if self.is_tripped:
            return False

        # 1. Hard Stop Daily Drawdown Check
        # Drawdown = (Starting Balance - Current Equity) / Starting Balance
        if self.starting_day_balance > 0:
            current_drawdown_dollars = self.starting_day_balance - current_equity
            current_drawdown_pct = (current_drawdown_dollars / self.starting_day_balance) * 100.0

            if current_drawdown_pct >= self.max_daily_drawdown_percent:
                self.is_tripped = True
                self.trip_reason = (
                    f"Daily Drawdown Hard Stop reached: {current_drawdown_pct:.2f}% "
                    f"(Threshold: {self.max_daily_drawdown_percent}%) | Lost ${current_drawdown_dollars:,.2f}"
                )
                await self._trigger_trip(current_drawdown_pct)
                return False

        # 2. Max Trades Per Session Check
        if self.daily_trades_count >= self.max_trades_per_session:
            self.is_tripped = True
            self.trip_reason = (
                f"Maximum session trades limit reached: {self.daily_trades_count}/{self.max_trades_per_session}"
            )
            await self._trigger_trip(0.0)
            return False

        return True

    async def _trigger_trip(self, drawdown: float) -> None:
        """Dispatches circuit breaker event and forces state machine lock."""
        logger.critical(f"CIRCUIT BREAKER TRIPPED! Reason: {self.trip_reason}")
        await state_machine.transition_to(
            SystemState.CIRCUIT_BREAKER,
            self.trip_reason
        )
        event = CircuitBreakerTriggeredEvent(
            reason=self.trip_reason,
            current_drawdown=round(drawdown, 2),
            trades_count=self.daily_trades_count
        )
        await event_bus.publish(event)

    def reset_day(self, new_starting_balance: float) -> None:
        """Resets the circuit breaker metrics for a new trading day."""
        self.starting_day_balance = new_starting_balance
        self.daily_trades_count = 0
        self.daily_realized_pnl = 0.0
        self.is_tripped = False
        self.trip_reason = ""
        logger.info(f"Circuit Breaker reset for new day. Baseline balance: ${new_starting_balance:,.2f}")
