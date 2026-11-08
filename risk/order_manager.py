"""
AUREUS-SMC Dynamic Order Manager
Manages real-time position lifecycle: Break-Even relocation (1:1.5 RRR) and 50% partial taking (1:2.0 RRR).
"""

from __future__ import annotations
import logging
from typing import Dict, Optional, Callable, Awaitable
from core.models import Position, OrderSide, PositionStatus
from core.events import PositionModifiedEvent, PositionPartialClosedEvent
from core.event_bus import event_bus
from config import settings

logger = logging.getLogger("OrderManager")


class OrderManager:
    """
    Supervises active open positions on every tick.
    Executes automated risk transitions:
    - 1:1.5 RRR achieved -> Move SL to Break-Even + buffer
    - 1:2.0 RRR achieved -> Take 50% partial profit
    """

    def __init__(
        self,
        be_rrr: float = settings.BREAK_EVEN_RRR,
        be_offset: float = settings.BE_OFFSET_DOLLARS,
        partial_tp_rrr: float = settings.PARTIAL_TP_RRR,
        partial_percent: float = settings.PARTIAL_TP_PERCENT,
        modify_sl_callback: Optional[Callable[[Position, float], Awaitable[bool]]] = None,
        partial_close_callback: Optional[Callable[[Position, float], Awaitable[bool]]] = None
    ) -> None:
        self.be_rrr = be_rrr
        self.be_offset = be_offset
        self.partial_tp_rrr = partial_tp_rrr
        self.partial_percent = partial_percent

        self.modify_sl_callback = modify_sl_callback
        self.partial_close_callback = partial_close_callback

    async def update_position_risk(self, position: Position, current_price: float) -> None:
        """
        Evaluates position against real-time price updates and triggers dynamic risk actions.
        """
        if position.status != PositionStatus.OPEN and position.status != PositionStatus.PARTIALLY_CLOSED:
            return

        position.current_price = current_price
        r_multiple = position.current_r_multiple()

        # 1. Break-Even Relocation (Trigger: 1:1.5 RRR)
        if not position.break_even_set and r_multiple >= self.be_rrr:
            await self._execute_break_even(position)

        # 2. Partial Profit Taking 50% (Trigger: 1:2.0 RRR)
        if not position.partial_closed and r_multiple >= self.partial_tp_rrr:
            await self._execute_partial_close(position)

    async def _execute_break_even(self, position: Position) -> None:
        """Calculates and applies Break-Even Stop Loss."""
        if position.side == OrderSide.BUY:
            new_sl = round(position.entry_price + self.be_offset, 2)
            # Only advance SL forward
            if new_sl <= position.stop_loss:
                return
        else:
            new_sl = round(position.entry_price - self.be_offset, 2)
            if new_sl >= position.stop_loss:
                return

        logger.info(
            f"DYNAMIC RISK: Moving SL to Break-Even + ${self.be_offset:.2f} for {position.position_id} "
            f"(Old SL: {position.stop_loss} -> New SL: {new_sl})"
        )

        success = True
        if self.modify_sl_callback:
            success = await self.modify_sl_callback(position, new_sl)

        if success:
            position.stop_loss = new_sl
            position.break_even_set = True
            await event_bus.publish(
                PositionModifiedEvent(
                    position=position,
                    modification_type="BREAK_EVEN",
                    new_sl=new_sl
                )
            )

    async def _execute_partial_close(self, position: Position) -> None:
        """Executes 50% partial liquidation of position volume."""
        close_volume = round(position.volume * (self.partial_percent / 100.0), 2)
        # Ensure residual is valid
        if close_volume < settings.MIN_LOT:
            logger.warning(f"Calculated partial volume {close_volume} below min_lot. Skipping partial.")
            return

        logger.info(
            f"DYNAMIC RISK: Executing {self.partial_percent}% Partial Close on {position.position_id} | "
            f"Closing {close_volume} lots of {position.volume} lots at 1:{self.partial_tp_rrr} RRR"
        )

        success = True
        if self.partial_close_callback:
            success = await self.partial_close_callback(position, close_volume)

        if success:
            position.partial_closed = True
            position.status = PositionStatus.PARTIALLY_CLOSED
            await event_bus.publish(
                PositionPartialClosedEvent(
                    position=position,
                    closed_volume=close_volume,
                    realized_pnl=0.0
                )
            )
