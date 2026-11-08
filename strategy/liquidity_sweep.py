"""
AUREUS-SMC Liquidity Sweep Detector
Detects institutional false breakouts (Turtle Soups / Liquidity Grabs) outside London boundaries.
"""

from __future__ import annotations
import logging
from typing import Optional
from core.models import Bar, LondonRange, LiquiditySweep, OrderSide
from core.events import LiquiditySweepEvent
from core.event_bus import event_bus
from core.time_manager import time_manager
from config import settings

logger = logging.getLogger("LiquiditySweep")


class LiquiditySweepDetector:
    """
    Evaluates completed bars in the NY Open window (08:00 - 10:30 AM EST).
    Validates institutional sweeps where price reaches beyond London High/Low
    and closes back inside the boundary, confirming trap liquidity.
    """

    def __init__(self) -> None:
        self.last_sweep: Optional[LiquiditySweep] = None

    def check_sweep(self, bar: Bar, london_range: Optional[LondonRange]) -> Optional[LiquiditySweep]:
        """
        Scans a completed bar (M1 or M5) for liquidity sweep conditions.
        Returns a LiquiditySweep if confirmed, otherwise None.
        """
        if not london_range or not london_range.is_finalized:
            return None

        # Must occur inside NY Open Execution Window
        if not time_manager.is_in_ny_execution_window(bar.timestamp):
            return None

        # 1. Bearish Sweep of London High (Buy-Side Liquidity Grab -> Potential SELL)
        if bar.high > london_range.high and bar.close <= london_range.high:
            penetration = round(bar.high - london_range.high, 2)
            if penetration >= (settings.SWEEP_MIN_TICKS * settings.TICK_SIZE):
                sweep = LiquiditySweep(
                    direction=OrderSide.SELL,
                    level_swept=london_range.high,
                    wick_extreme=bar.high,
                    close_price=bar.close,
                    timestamp=bar.timestamp,
                    penetration_pips=round(penetration / settings.PIP_SIZE, 1)
                )
                self.last_sweep = sweep
                logger.info(
                    f"BEARISH SWEEP DETECTED: Swept London High {london_range.high} by ${penetration:.2f} "
                    f"({sweep.penetration_pips} pips). Extreme={bar.high}, Close={bar.close}"
                )
                event_bus.publish_nowait(LiquiditySweepEvent(sweep=sweep))
                return sweep

        # 2. Bullish Sweep of London Low (Sell-Side Liquidity Grab -> Potential BUY)
        if bar.low < london_range.low and bar.close >= london_range.low:
            penetration = round(london_range.low - bar.low, 2)
            if penetration >= (settings.SWEEP_MIN_TICKS * settings.TICK_SIZE):
                sweep = LiquiditySweep(
                    direction=OrderSide.BUY,
                    level_swept=london_range.low,
                    wick_extreme=bar.low,
                    close_price=bar.close,
                    timestamp=bar.timestamp,
                    penetration_pips=round(penetration / settings.PIP_SIZE, 1)
                )
                self.last_sweep = sweep
                logger.info(
                    f"BULLISH SWEEP DETECTED: Swept London Low {london_range.low} by ${penetration:.2f} "
                    f"({sweep.penetration_pips} pips). Extreme={bar.low}, Close={bar.close}"
                )
                event_bus.publish_nowait(LiquiditySweepEvent(sweep=sweep))
                return sweep

        return None
