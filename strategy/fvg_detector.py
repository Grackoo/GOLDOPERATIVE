"""
AUREUS-SMC Fair Value Gap (FVG) Detector & Consequent Encroachment Engine
Identifies 3-bar institutional imbalances and computes precise entry levels.
"""

from __future__ import annotations
import logging
from typing import Optional, List
from datetime import datetime
from core.models import Bar, FairValueGap, OrderSide
from core.events import FVGDetectedEvent
from core.event_bus import event_bus
from config import settings

logger = logging.getLogger("FVGDetector")


class FVGDetector:
    """
    Scans the 3 most recent completed candlesticks for institutional Fair Value Gaps.
    Calculates Consequent Encroachment (50% midpoint) and tracks mitigation.
    """

    def __init__(self, min_size_points: float = settings.MIN_FVG_SIZE_POINTS) -> None:
        self.min_size_points = min_size_points
        self.active_fvgs: List[FairValueGap] = []

    def check_fvg(self, c1: Bar, c2: Bar, c3: Bar) -> Optional[FairValueGap]:
        """
        Inspects 3 sequential candles:
        c1: Prior candle
        c2: Displacement candle
        c3: Post-displacement candle
        """
        # 1. Bullish FVG (c3.low > c1.high)
        if c3.low > c1.high:
            gap_size = round(c3.low - c1.high, 2)
            if gap_size >= self.min_size_points:
                fvg = FairValueGap.create(
                    direction=OrderSide.BUY,
                    c1=c1,
                    c2=c2,
                    c3=c3,
                    timestamp=c3.timestamp
                )
                self.active_fvgs.append(fvg)
                logger.info(
                    f"BULLISH FVG DETECTED: Imbalance [${fvg.bottom:.2f} - ${fvg.top:.2f}] | "
                    f"Size=${gap_size:.2f} | 50% CE=${fvg.consequent_encroachment:.2f}"
                )
                event_bus.publish_nowait(FVGDetectedEvent(fvg=fvg))
                return fvg

        # 2. Bearish FVG (c3.high < c1.low)
        if c3.high < c1.low:
            gap_size = round(c1.low - c3.high, 2)
            if gap_size >= self.min_size_points:
                fvg = FairValueGap.create(
                    direction=OrderSide.SELL,
                    c1=c1,
                    c2=c2,
                    c3=c3,
                    timestamp=c3.timestamp
                )
                self.active_fvgs.append(fvg)
                logger.info(
                    f"BEARISH FVG DETECTED: Imbalance [${fvg.bottom:.2f} - ${fvg.top:.2f}] | "
                    f"Size=${gap_size:.2f} | 50% CE=${fvg.consequent_encroachment:.2f}"
                )
                event_bus.publish_nowait(FVGDetectedEvent(fvg=fvg))
                return fvg

        return None

    def check_mitigation(self, fvg: FairValueGap, current_price: float, current_time: datetime) -> bool:
        """
        Evaluates whether price has tapped the entry target of the FVG.
        """
        target_price = fvg.consequent_encroachment if settings.FVG_ENTRY_MODE == "50_PERCENT" else (
            fvg.top if fvg.direction == OrderSide.BUY else fvg.bottom
        )

        if fvg.direction == OrderSide.BUY and current_price <= target_price:
            fvg.is_mitigated = True
            fvg.mitigated_at = current_time
            return True
        elif fvg.direction == OrderSide.SELL and current_price >= target_price:
            fvg.is_mitigated = True
            fvg.mitigated_at = current_time
            return True

        return False
