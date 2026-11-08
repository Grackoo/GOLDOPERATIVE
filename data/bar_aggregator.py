"""
AUREUS-SMC Real-Time Bar Aggregator
Constructs synchronized M1 and M5 institutional candlesticks from continuous tick streams.
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple
from core.models import Tick, Bar
from core.events import TickEvent, BarClosedEvent, BarUpdateEvent
from core.event_bus import event_bus
from data.ring_buffer import RingBuffer
from config import settings

logger = logging.getLogger("BarAggregator")


class BarAggregator:
    """
    Subscribes to incoming price ticks and aggregates them into multi-timeframe
    candlestick bars (M1 and M5) with sub-millisecond precision.
    """

    def __init__(self) -> None:
        self.m1_buffer: RingBuffer[Bar] = RingBuffer[Bar](settings.CANDLE_BUFFER_SIZE_M1)
        self.m5_buffer: RingBuffer[Bar] = RingBuffer[Bar](settings.CANDLE_BUFFER_SIZE_M5)
        self.tick_buffer: RingBuffer[Tick] = RingBuffer[Tick](settings.TICK_BUFFER_SIZE)

        self._current_m1_bar: Optional[Bar] = None
        self._current_m5_bar: Optional[Bar] = None

    def _get_m1_open_time(self, ts: datetime) -> datetime:
        return ts.replace(second=0, microsecond=0)

    def _get_m5_open_time(self, ts: datetime) -> datetime:
        minute = ts.minute - (ts.minute % 5)
        return ts.replace(minute=minute, second=0, microsecond=0)

    async def on_tick(self, event: TickEvent) -> None:
        """Processes incoming tick and drives candlestick aggregation."""
        tick = event.tick
        self.tick_buffer.append(tick)
        price = tick.mid

        # 1. Process M1 Bar
        m1_open_time = self._get_m1_open_time(tick.timestamp)
        if self._current_m1_bar is None:
            self._current_m1_bar = Bar(
                symbol=tick.symbol,
                timeframe="M1",
                timestamp=m1_open_time,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=tick.volume,
                is_closed=False
            )
        elif self._current_m1_bar.timestamp != m1_open_time:
            # Finalize previous M1 bar
            self._current_m1_bar.is_closed = True
            self.m1_buffer.append(self._current_m1_bar)
            closed_event = BarClosedEvent(bar=self._current_m1_bar)
            await event_bus.publish(closed_event)

            # Start new M1 bar
            self._current_m1_bar = Bar(
                symbol=tick.symbol,
                timeframe="M1",
                timestamp=m1_open_time,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=tick.volume,
                is_closed=False
            )
        else:
            # Update existing M1 bar
            self._current_m1_bar.high = max(self._current_m1_bar.high, price)
            self._current_m1_bar.low = min(self._current_m1_bar.low, price)
            self._current_m1_bar.close = price
            self._current_m1_bar.volume += tick.volume

        # Emit current forming M1 update for WebSockets
        await event_bus.publish(BarUpdateEvent(bar=self._current_m1_bar))

        # 2. Process M5 Bar
        m5_open_time = self._get_m5_open_time(tick.timestamp)
        if self._current_m5_bar is None:
            self._current_m5_bar = Bar(
                symbol=tick.symbol,
                timeframe="M5",
                timestamp=m5_open_time,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=tick.volume,
                is_closed=False
            )
        elif self._current_m5_bar.timestamp != m5_open_time:
            # Finalize previous M5 bar
            self._current_m5_bar.is_closed = True
            self.m5_buffer.append(self._current_m5_bar)
            closed_m5_event = BarClosedEvent(bar=self._current_m5_bar)
            await event_bus.publish(closed_m5_event)

            # Start new M5 bar
            self._current_m5_bar = Bar(
                symbol=tick.symbol,
                timeframe="M5",
                timestamp=m5_open_time,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=tick.volume,
                is_closed=False
            )
        else:
            # Update existing M5 bar
            self._current_m5_bar.high = max(self._current_m5_bar.high, price)
            self._current_m5_bar.low = min(self._current_m5_bar.low, price)
            self._current_m5_bar.close = price
            self._current_m5_bar.volume += tick.volume

    def get_latest_bars(self, timeframe: str = "M1", count: int = 100, include_forming: bool = False) -> list[Bar]:
        """Returns the latest finalized bars for requested timeframe."""
        if timeframe.upper() == "M5":
            bars = self.m5_buffer.latest(count)
            if include_forming and self._current_m5_bar:
                bars.append(self._current_m5_bar)
            return bars
        else:
            bars = self.m1_buffer.latest(count)
            if include_forming and self._current_m1_bar:
                bars.append(self._current_m1_bar)
            return bars
