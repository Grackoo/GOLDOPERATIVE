"""
AUREUS-SMC Real-Time Bar Aggregator
Constructs synchronized M1, M5, M15, and M30 institutional candlesticks from continuous tick streams.
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple, List
from core.models import Tick, Bar
from core.events import TickEvent, BarClosedEvent, BarUpdateEvent
from core.event_bus import event_bus
from data.ring_buffer import RingBuffer
from config import settings

logger = logging.getLogger("BarAggregator")


class BarAggregator:
    """
    Subscribes to incoming price ticks and aggregates them into multi-timeframe
    candlestick bars (M1, M5, M15, and M30) with sub-millisecond precision.
    """

    def __init__(self) -> None:
        self.m1_buffer: RingBuffer[Bar] = RingBuffer[Bar](settings.CANDLE_BUFFER_SIZE_M1)
        self.m5_buffer: RingBuffer[Bar] = RingBuffer[Bar](settings.CANDLE_BUFFER_SIZE_M5)
        self.m15_buffer: RingBuffer[Bar] = RingBuffer[Bar](settings.CANDLE_BUFFER_SIZE_M15)
        self.m30_buffer: RingBuffer[Bar] = RingBuffer[Bar](settings.CANDLE_BUFFER_SIZE_M30)
        self.tick_buffer: RingBuffer[Tick] = RingBuffer[Tick](settings.TICK_BUFFER_SIZE)

        self._current_m1_bar: Optional[Bar] = None
        self._current_m5_bar: Optional[Bar] = None
        self._current_m15_bar: Optional[Bar] = None
        self._current_m30_bar: Optional[Bar] = None

    def _get_m1_open_time(self, ts: datetime) -> datetime:
        return ts.replace(second=0, microsecond=0)

    def _get_m5_open_time(self, ts: datetime) -> datetime:
        minute = ts.minute - (ts.minute % 5)
        return ts.replace(minute=minute, second=0, microsecond=0)

    def _get_m15_open_time(self, ts: datetime) -> datetime:
        minute = ts.minute - (ts.minute % 15)
        return ts.replace(minute=minute, second=0, microsecond=0)

    def _get_m30_open_time(self, ts: datetime) -> datetime:
        minute = ts.minute - (ts.minute % 30)
        return ts.replace(minute=minute, second=0, microsecond=0)

    async def _update_timeframe_bar(
        self,
        timeframe: str,
        open_time: datetime,
        current_bar: Optional[Bar],
        buffer: RingBuffer[Bar],
        price: float,
        volume: float,
        symbol: str
    ) -> Bar:
        if current_bar is None:
            return Bar(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=open_time,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                is_closed=False
            )
        elif current_bar.timestamp != open_time:
            # Finalize previous bar
            current_bar.is_closed = True
            buffer.append(current_bar)
            await event_bus.publish(BarClosedEvent(bar=current_bar))

            # Start new bar
            return Bar(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=open_time,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                is_closed=False
            )
        else:
            # Update existing bar
            current_bar.high = max(current_bar.high, price)
            current_bar.low = min(current_bar.low, price)
            current_bar.close = price
            current_bar.volume += volume
            return current_bar

    async def on_tick(self, event: TickEvent) -> None:
        """Processes incoming tick across M1, M5, M15, and M30 timeframes."""
        tick = event.tick
        self.tick_buffer.append(tick)
        price = tick.mid

        # 1. Process M1
        m1_time = self._get_m1_open_time(tick.timestamp)
        self._current_m1_bar = await self._update_timeframe_bar(
            "M1", m1_time, self._current_m1_bar, self.m1_buffer, price, tick.volume, tick.symbol
        )
        await event_bus.publish(BarUpdateEvent(bar=self._current_m1_bar))

        # 2. Process M5
        m5_time = self._get_m5_open_time(tick.timestamp)
        self._current_m5_bar = await self._update_timeframe_bar(
            "M5", m5_time, self._current_m5_bar, self.m5_buffer, price, tick.volume, tick.symbol
        )
        await event_bus.publish(BarUpdateEvent(bar=self._current_m5_bar))

        # 3. Process M15
        m15_time = self._get_m15_open_time(tick.timestamp)
        self._current_m15_bar = await self._update_timeframe_bar(
            "M15", m15_time, self._current_m15_bar, self.m15_buffer, price, tick.volume, tick.symbol
        )
        await event_bus.publish(BarUpdateEvent(bar=self._current_m15_bar))

        # 4. Process M30
        m30_time = self._get_m30_open_time(tick.timestamp)
        self._current_m30_bar = await self._update_timeframe_bar(
            "M30", m30_time, self._current_m30_bar, self.m30_buffer, price, tick.volume, tick.symbol
        )
        await event_bus.publish(BarUpdateEvent(bar=self._current_m30_bar))

    def get_latest_bars(self, timeframe: str = "M1", count: int = 100, include_forming: bool = False) -> List[Bar]:
        """Returns the latest finalized bars for requested timeframe."""
        tf = timeframe.upper()
        if tf == "M5":
            bars = self.m5_buffer.latest(count)
            if include_forming and self._current_m5_bar:
                bars.append(self._current_m5_bar)
            return bars
        elif tf == "M15":
            bars = self.m15_buffer.latest(count)
            if include_forming and self._current_m15_bar:
                bars.append(self._current_m15_bar)
            return bars
        elif tf == "M30":
            bars = self.m30_buffer.latest(count)
            if include_forming and self._current_m30_bar:
                bars.append(self._current_m30_bar)
            return bars
        else:
            bars = self.m1_buffer.latest(count)
            if include_forming and self._current_m1_bar:
                bars.append(self._current_m1_bar)
            return bars
