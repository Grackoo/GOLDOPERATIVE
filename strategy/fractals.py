"""
AUREUS-SMC Fractals & Market Structure Swings
Identifies pivot highs and lows to detect Market Structure Shifts (MSS / CHOCH).
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple
from core.models import Bar


@dataclass(slots=True)
class SwingPoint:
    is_high: bool
    price: float
    bar_index: int
    bar: Bar


class FractalDetector:
    """
    Detects institutional swing points (Fractals) across completed candles.
    Uses configurable lookback (e.g. 2 bars on each side for a 5-bar fractal).
    """

    def __init__(self, lookback: int = 2) -> None:
        self.lookback = lookback  # 2 left, 1 center, 2 right = 5 bar pivot

    def find_swings(self, bars: List[Bar]) -> Tuple[List[SwingPoint], List[SwingPoint]]:
        """
        Scans a sequence of bars and returns (swing_highs, swing_lows).
        """
        swing_highs: List[SwingPoint] = []
        swing_lows: List[SwingPoint] = []

        n = len(bars)
        if n < (self.lookback * 2 + 1):
            return swing_highs, swing_lows

        for i in range(self.lookback, n - self.lookback):
            current = bars[i]

            # Check Swing High
            is_sh = True
            for left in range(i - self.lookback, i):
                if bars[left].high >= current.high:
                    is_sh = False
                    break
            if is_sh:
                for right in range(i + 1, i + self.lookback + 1):
                    if bars[right].high > current.high:
                        is_sh = False
                        break
            if is_sh:
                swing_highs.append(SwingPoint(is_high=True, price=current.high, bar_index=i, bar=current))

            # Check Swing Low
            is_sl = True
            for left in range(i - self.lookback, i):
                if bars[left].low <= current.low:
                    is_sl = False
                    break
            if is_sl:
                for right in range(i + 1, i + self.lookback + 1):
                    if bars[right].low < current.low:
                        is_sl = False
                        break
            if is_sl:
                swing_lows.append(SwingPoint(is_high=False, price=current.low, bar_index=i, bar=current))

        return swing_highs, swing_lows

    def get_latest_swing_high(self, bars: List[Bar]) -> Optional[SwingPoint]:
        shs, _ = self.find_swings(bars)
        return shs[-1] if shs else None

    def get_latest_swing_low(self, bars: List[Bar]) -> Optional[SwingPoint]:
        _, sls = self.find_swings(bars)
        return sls[-1] if sls else None
