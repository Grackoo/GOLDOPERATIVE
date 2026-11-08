"""
AUREUS-SMC Institutional Timezone & Session Manager
Accurate DST-aware session scheduling using standard Python zoneinfo.
"""

from __future__ import annotations
from datetime import datetime, time, date
from zoneinfo import ZoneInfo
from typing import Tuple
from config import settings


class TimezoneManager:
    """
    Manages session boundaries in Eastern Time (EST/EDT) with dynamic Daylight Saving Time.
    All institutional SMC liquidity references are anchored to New York (America/New_York).
    """

    def __init__(self, tz_name: str = settings.TIMEZONE) -> None:
        self.tz = ZoneInfo(tz_name)
        # Parse session boundaries from settings
        l_start_h, l_start_m = map(int, settings.LONDON_SESSION_START.split(":"))
        l_end_h, l_end_m = map(int, settings.LONDON_SESSION_END.split(":"))
        ny_start_h, ny_start_m = map(int, settings.NY_EXECUTION_START.split(":"))
        ny_end_h, ny_end_m = map(int, settings.NY_EXECUTION_END.split(":"))

        self.london_start = time(l_start_h, l_start_m)
        self.london_end = time(l_end_h, l_end_m)
        self.ny_start = time(ny_start_h, ny_start_m)
        self.ny_end = time(ny_end_h, ny_end_m)

    def now(self) -> datetime:
        """Returns the current timezone-aware timestamp in New York time."""
        return datetime.now(self.tz)

    def to_ny_time(self, dt: datetime) -> datetime:
        """Converts any datetime to New York time with full DST alignment."""
        if dt.tzinfo is None:
            # Assume UTC if naive, or localize directly
            return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(self.tz)
        return dt.astimezone(self.tz)

    def is_in_london_session(self, dt: datetime | None = None) -> bool:
        """
        True if the given datetime (or now) falls in London Accumulation:
        03:00 AM to 08:00 AM EST/EDT.
        """
        target = self.to_ny_time(dt) if dt else self.now()
        t = target.time()
        return self.london_start <= t < self.london_end

    def is_in_ny_execution_window(self, dt: datetime | None = None) -> bool:
        """
        True if the given datetime (or now) falls in the NY Open liquidity sweep & entry window:
        08:00 AM to 10:30 AM EST/EDT.
        """
        target = self.to_ny_time(dt) if dt else self.now()
        t = target.time()
        return self.ny_start <= t <= self.ny_end

    def is_past_ny_window(self, dt: datetime | None = None) -> bool:
        """True if the trading window has concluded for the morning."""
        target = self.to_ny_time(dt) if dt else self.now()
        return target.time() > self.ny_end

    def get_session_date_str(self, dt: datetime | None = None) -> str:
        """Returns YYYY-MM-DD for the current trading day in New York."""
        target = self.to_ny_time(dt) if dt else self.now()
        return target.strftime("%Y-%m-%d")

    def get_london_range_datetimes(self, for_date: date | None = None) -> Tuple[datetime, datetime]:
        """Returns (start_dt, end_dt) for today's London session in NY timezone."""
        ref_date = for_date or self.now().date()
        start_dt = datetime.combine(ref_date, self.london_start, tzinfo=self.tz)
        end_dt = datetime.combine(ref_date, self.london_end, tzinfo=self.tz)
        return start_dt, end_dt

    def get_ny_window_datetimes(self, for_date: date | None = None) -> Tuple[datetime, datetime]:
        """Returns (start_dt, end_dt) for today's NY Execution window in NY timezone."""
        ref_date = for_date or self.now().date()
        start_dt = datetime.combine(ref_date, self.ny_start, tzinfo=self.tz)
        end_dt = datetime.combine(ref_date, self.ny_end, tzinfo=self.tz)
        return start_dt, end_dt


# Global singleton
time_manager = TimezoneManager()
