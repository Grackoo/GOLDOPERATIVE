"""
AUREUS-SMC Displacement & Market Structure Shift (MSS) Validator
Validates structural shifts characterized by wide-range displacement bodies (> 1.5 * ATR).
"""

from __future__ import annotations
import logging
from typing import Optional, List
from core.models import Bar, MarketStructureShift, OrderSide
from core.events import DisplacementEvent
from core.event_bus import event_bus
from strategy.fractals import SwingPoint
from config import settings

logger = logging.getLogger("Displacement")


class DisplacementDetector:
    """
    Detects aggressive institutional displacement breaking local structure (MSS / CHOCH).
    Requires the displacement bar body to exceed 1.5 * ATR(14) to eliminate retail noise.
    """

    def __init__(self, atr_multiplier: float = settings.DISPLACEMENT_ATR_MULTIPLIER) -> None:
        self.atr_multiplier = atr_multiplier

    def check_mss(
        self,
        current_bar: Bar,
        atr: float,
        recent_swing_high: Optional[SwingPoint] = None,
        recent_swing_low: Optional[SwingPoint] = None,
        fallback_level: Optional[float] = None,
        expected_direction: Optional[OrderSide] = None
    ) -> Optional[MarketStructureShift]:
        """
        Evaluates whether current_bar creates an institutional Market Structure Shift (MSS).
        """
        required_body = self.atr_multiplier * atr
        if current_bar.body_size < required_body:
            return None

        body_ratio = round(current_bar.body_size / atr, 2) if atr > 0 else 1.0

        # Determine reference break levels
        break_high = recent_swing_high.price if recent_swing_high else fallback_level
        break_low = recent_swing_low.price if recent_swing_low else fallback_level

        # 1. Bullish MSS (Break above recent swing high with wide bullish body)
        if expected_direction in {None, OrderSide.BUY} and current_bar.is_bullish:
            if break_high is not None and current_bar.close > break_high:
                mss = MarketStructureShift(
                    direction=OrderSide.BUY,
                    broken_swing_level=break_high,
                    displacement_candle=current_bar,
                    displacement_atr=atr,
                    body_to_atr_ratio=body_ratio,
                    timestamp=current_bar.timestamp
                )
                logger.info(
                    f"BULLISH MSS CONFIRMED: Broken Swing High {break_high} | "
                    f"Body=${current_bar.body_size:.2f} ({body_ratio}x ATR) | Close={current_bar.close}"
                )
                event_bus.publish_nowait(DisplacementEvent(mss=mss))
                return mss

        # 2. Bearish MSS (Break below recent swing low with wide bearish body)
        if expected_direction in {None, OrderSide.SELL} and not current_bar.is_bullish:
            if break_low is not None and current_bar.close < break_low:
                mss = MarketStructureShift(
                    direction=OrderSide.SELL,
                    broken_swing_level=break_low,
                    displacement_candle=current_bar,
                    displacement_atr=atr,
                    body_to_atr_ratio=body_ratio,
                    timestamp=current_bar.timestamp
                )
                logger.info(
                    f"BEARISH MSS CONFIRMED: Broken Swing Low {break_low} | "
                    f"Body=${current_bar.body_size:.2f} ({body_ratio}x ATR) | Close={current_bar.close}"
                )
                event_bus.publish_nowait(DisplacementEvent(mss=mss))
                return mss

        return None
