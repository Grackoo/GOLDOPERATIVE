"""
AUREUS-SMC Macroeconomic News Blackout Filter
Enforces strict 15-minute moratorium before and after High-Impact Red Folder releases.
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from core.models import EconomicNewsEvent, NewsImpact
from core.events import NewsBlackoutEvent
from core.event_bus import event_bus
from core.time_manager import time_manager
from macro.news_calendar import NewsCalendarManager
from config import settings

logger = logging.getLogger("NewsFilter")


class NewsFilter:
    """
    Evaluates current time against high-impact event schedules.
    Suspends algorithmic order placement within the [-15 min, +15 min] envelope.
    """

    def __init__(
        self,
        calendar_manager: Optional[NewsCalendarManager] = None,
        before_minutes: int = settings.NEWS_BLACKOUT_MINUTES_BEFORE,
        after_minutes: int = settings.NEWS_BLACKOUT_MINUTES_AFTER
    ) -> None:
        self.calendar = calendar_manager or NewsCalendarManager()
        self.before_delta = timedelta(minutes=before_minutes)
        self.after_delta = timedelta(minutes=after_minutes)
        self.is_blackout: bool = False
        self.active_event: Optional[EconomicNewsEvent] = None

    async def initialize(self) -> None:
        if settings.NEWS_FILTER_ENABLED:
            await self.calendar.fetch_events()

    def is_in_blackout(self, check_time: Optional[datetime] = None) -> bool:
        """
        Returns True if check_time (or current NY time) falls within a high-impact news blackout window.
        """
        if not settings.NEWS_FILTER_ENABLED:
            return False

        target = time_manager.to_ny_time(check_time) if check_time else time_manager.now()

        for event in self.calendar.events:
            if event.impact != NewsImpact.HIGH or event.currency != "USD":
                continue

            event_time = time_manager.to_ny_time(event.scheduled_time)
            window_start = event_time - self.before_delta
            window_end = event_time + self.after_delta

            if window_start <= target <= window_end:
                if not self.is_blackout or self.active_event != event:
                    self.is_blackout = True
                    self.active_event = event
                    logger.warning(
                        f"NEWS BLACKOUT ACTIVE: [{event.title}] scheduled at {event_time.strftime('%H:%M:%S')}. "
                        f"Trading frozen until {window_end.strftime('%H:%M:%S')}."
                    )
                    event_bus.publish_nowait(
                        NewsBlackoutEvent(
                            is_active=True,
                            event=event,
                            window_start=window_start,
                            window_end=window_end
                        )
                    )
                return True

        if self.is_blackout:
            # Exited blackout window
            logger.info("Exited News Blackout window. Normal strategy scanning resumes.")
            self.is_blackout = False
            self.active_event = None
            event_bus.publish_nowait(NewsBlackoutEvent(is_active=False))

        return False


# Global singleton
news_filter = NewsFilter()
