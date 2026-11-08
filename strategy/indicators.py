"""
AUREUS-SMC Quantitative Technical Indicators
High-performance ATR, True Range, and volatility calculations.
"""

from __future__ import annotations
from typing import List, Sequence
import numpy as np
from core.models import Bar


def calculate_true_range(current: Bar, previous: Bar) -> float:
    """Calculates True Range between two consecutive candlestick bars."""
    hl = current.high - current.low
    h_pc = abs(current.high - previous.close)
    l_pc = abs(current.low - previous.close)
    return round(max(hl, h_pc, l_pc), 3)


def calculate_atr(bars: Sequence[Bar], period: int = 14) -> float:
    """
    Computes Average True Range (Wilder's Smoothing) over the provided bar sequence.
    Returns the latest ATR value. If insufficient bars, returns fallback spread/range estimate.
    """
    if len(bars) < 2:
        return 1.0  # Safe default for Gold

    tr_list: List[float] = []
    for i in range(1, len(bars)):
        tr = calculate_true_range(bars[i], bars[i - 1])
        tr_list.append(tr)

    if not tr_list:
        return 1.0

    if len(tr_list) < period:
        return round(float(np.mean(tr_list)), 3)

    # Wilder's RMA calculation
    atr = float(np.mean(tr_list[:period]))
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period

    return round(atr, 3)
