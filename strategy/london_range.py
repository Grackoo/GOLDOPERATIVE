"""
AUREUS-SMC London Session Range Detector
Identifies and finalizes the institutional London High & Low liquidity boundaries (03:00 - 08:00 EST).
"""

from __future__ import annotations
import logging
from typing import Optional
from datetime import datetime
from core.models import Bar, LondonRange
from core.events import LondonRangeCalculatedEvent
from core.event_bus import event_bus
from core.time_manager import time_manager

logger = logging.getLogger("LondonRange")


class LondonRangeDetector:
    """
    Monitors incoming M1/M5 bars during London Accumulation (03:00 - 08:00 AM New York).
    Extracts the highest high and lowest low as benchmark liquidity pools for the NY Open session.
    """

    def __init__(self) -> None:
        self.current_range: Optional[LondonRange] = None
        self._current_date_str: str = ""

    def process_bar(self, bar: Bar) -> Optional[LondonRange]:
        """
        Processes a newly closed or forming candlestick. Updates London High/Low
        if bar timestamp is within 03:00 - 08:00 AM New York time.
        """
        ny_bar_time = time_manager.to_ny_time(bar.timestamp)
        date_str = ny_bar_time.strftime("%Y-%m-%d")

        # New day reset
        if date_str != self._current_date_str:
            self._current_date_str = date_str
            self.current_range = LondonRange(
                date_str=date_str,
                high=bar.high,
                low=bar.low,
                high_time=bar.timestamp,
                low_time=bar.timestamp,
                range_size=round(bar.high - bar.low, 2),
                is_finalized=False
            )

        if not self.current_range:
            return None

        # Check if bar is within London Session
        if time_manager.is_in_london_session(bar.timestamp):
            self.current_range.update(bar.high, bar.low, bar.timestamp, bar.timestamp)

        # Check if session has transitioned to NY Open (08:00 AM EST) and needs finalization
        elif time_manager.is_in_ny_execution_window(bar.timestamp) and not self.current_range.is_finalized:
            self.finalize_range()

        return self.current_range

    def finalize_range(self) -> None:
        """Locks the London range for the day and dispatches event."""
        if self.current_range and not self.current_range.is_finalized:
            self.current_range.is_finalized = True
            logger.info(
                f"LONDON RANGE LOCKED: High={self.current_range.high} | Low={self.current_range.low} | "
                f"Range=${self.current_range.range_size:.2f} (Points: {int(self.current_range.range_size * 100)})"
            )
            event_bus.publish_nowait(LondonRangeCalculatedEvent(london_range=self.current_range))

    def reset(self) -> None:
        self.current_range = None
        self._current_date_str = ""
