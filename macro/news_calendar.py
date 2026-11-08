"""
AUREUS-SMC Macroeconomic News Calendar Feeder
Fetches and structures high-impact institutional releases (NFP, CPI, FOMC) affecting Gold.
"""

from __future__ import annotations
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo
from core.models import EconomicNewsEvent, NewsImpact
from config import settings

logger = logging.getLogger("NewsCalendar")

HIGH_IMPACT_USD_KEYWORDS = [
    "non-farm", "nfp", "cpi", "fomc", "interest rate",
    "fed chair", "powell", "ppi", "unemployment rate", "gdp"
]


class NewsCalendarManager:
    """
    Retrieves economic calendar releases from institutional feeds (ForexFactory JSON / Investing).
    Maintains an active schedule of high-impact events for trading window filtering.
    """

    def __init__(self, provider: str = settings.NEWS_API_PROVIDER) -> None:
        self.provider = provider
        self.events: List[EconomicNewsEvent] = []
        self._last_fetch: Optional[datetime] = None

    async def fetch_events(self) -> List[EconomicNewsEvent]:
        """Fetches calendar events asynchronously."""
        if self.provider == "FOREXFACTORY":
            events = await self._fetch_forexfactory()
        else:
            events = self._generate_simulated_events()

        self.events = events
        self._last_fetch = datetime.utcnow()
        logger.info(f"Loaded {len(self.events)} high-impact calendar events.")
        return self.events

    async def _fetch_forexfactory(self) -> List[EconomicNewsEvent]:
        """Fetches weekly calendar from ForexFactory public JSON feed."""
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        events: List[EconomicNewsEvent] = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data:
                            currency = item.get("country", "").upper()
                            impact_str = item.get("impact", "").upper()
                            title = item.get("title", "")

                            # We only care about USD High-Impact releases for Gold
                            if currency == "USD" and impact_str == "HIGH":
                                # Parse ISO timestamp
                                date_str = item.get("date", "")
                                try:
                                    dt = datetime.fromisoformat(date_str)
                                    events.append(EconomicNewsEvent(
                                        title=title,
                                        currency=currency,
                                        impact=NewsImpact.HIGH,
                                        scheduled_time=dt,
                                        forecast=item.get("forecast"),
                                        previous=item.get("previous"),
                                        actual=item.get("actual")
                                    ))
                                except ValueError:
                                    continue
                        return events
        except Exception as e:
            logger.warning(f"Could not reach external news feed ({e}). Using simulated high-impact schedule.")
            return self._generate_simulated_events()

        return self._generate_simulated_events()

    def _generate_simulated_events(self) -> List[EconomicNewsEvent]:
        """Provides institutional benchmark events for sandbox / testing environments."""
        tz = ZoneInfo(settings.TIMEZONE)
        now = datetime.now(tz)
        today = now.date()

        # Generate realistic 08:30 AM EST high-impact releases (CPI / NFP)
        event_830 = datetime(today.year, today.month, today.day, 8, 30, tzinfo=tz)
        event_1400 = datetime(today.year, today.month, today.day, 14, 0, tzinfo=tz)

        return [
            EconomicNewsEvent(
                title="US Core CPI (Consumer Price Index) m/m",
                currency="USD",
                impact=NewsImpact.HIGH,
                scheduled_time=event_830,
                forecast="0.3%",
                previous="0.2%"
            ),
            EconomicNewsEvent(
                title="FOMC Interest Rate Decision & Monetary Policy Statement",
                currency="USD",
                impact=NewsImpact.HIGH,
                scheduled_time=event_1400,
                forecast="5.25%",
                previous="5.25%"
            )
        ]
