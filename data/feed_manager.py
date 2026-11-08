"""
AUREUS-SMC Institutional Feed Manager
Handles primary Gold feed normalization and optional secondary correlation feeds (DXY, US10Y).
"""

from __future__ import annotations
import logging
from typing import Optional, Dict
from datetime import datetime
from core.models import Tick, Bar
from core.events import TickEvent
from core.event_bus import event_bus
from data.ring_buffer import RingBuffer
from data.bar_aggregator import BarAggregator
from config import settings

logger = logging.getLogger("FeedManager")


class FeedManager:
    """
    Coordinates multi-asset feeds, applies asset-specific normalization,
    and feeds the bar aggregator and event bus.
    """

    def __init__(self, bar_aggregator: Optional[BarAggregator] = None) -> None:
        self.bar_aggregator = bar_aggregator or BarAggregator()
        self.dxy_buffer: RingBuffer[Bar] = RingBuffer[Bar](600)    # DXY M1 correlation buffer
        self.us10y_buffer: RingBuffer[Bar] = RingBuffer[Bar](600)  # US10Y M1 correlation buffer
        self.latest_tick: Optional[Tick] = None

        # Wire bar aggregator to event bus for ticks
        event_bus.subscribe(TickEvent, self.bar_aggregator.on_tick)

    def normalize_gold_price(self, price: float) -> float:
        """Enforces 2-decimal precision (0.01 cent tick size)."""
        return round(price, 2)

    async def ingest_tick(self, symbol: str, bid: float, ask: float, timestamp: Optional[datetime] = None, volume: float = 1.0) -> Tick:
        """
        Normalizes and injects an incoming raw tick into the trading engine.
        Calculates spread and dispatches TickEvent.
        """
        ts = timestamp or datetime.utcnow()
        norm_bid = self.normalize_gold_price(bid)
        norm_ask = self.normalize_gold_price(ask)

        tick = Tick(
            symbol=symbol,
            timestamp=ts,
            bid=norm_bid,
            ask=norm_ask,
            volume=volume
        )
        self.latest_tick = tick

        # Fast path publish
        await event_bus.publish(TickEvent(tick=tick))
        return tick

    def ingest_macro_bar(self, asset: str, bar: Bar) -> None:
        """Stores secondary macro correlation bar (DXY or US10Y)."""
        if asset.upper() == "DXY":
            self.dxy_buffer.append(bar)
        elif asset.upper() in {"US10Y", "TNX"}:
            self.us10y_buffer.append(bar)

    def get_macro_confluence(self) -> Dict[str, str]:
        """
        Analyzes short-term correlation between Gold, DXY, and US10Y.
        Institutional Gold is typically inversely correlated with DXY and Yields.
        """
        result = {"DXY_bias": "NEUTRAL", "US10Y_bias": "NEUTRAL"}
        latest_dxy = self.dxy_buffer.latest(3)
        if len(latest_dxy) >= 2:
            if latest_dxy[-1].close < latest_dxy[0].open:
                result["DXY_bias"] = "BULLISH_FOR_GOLD"  # DXY weakening = Gold strength
            elif latest_dxy[-1].close > latest_dxy[0].open:
                result["DXY_bias"] = "BEARISH_FOR_GOLD"

        latest_yield = self.us10y_buffer.latest(3)
        if len(latest_yield) >= 2:
            if latest_yield[-1].close < latest_yield[0].open:
                result["US10Y_bias"] = "BULLISH_FOR_GOLD"
            elif latest_yield[-1].close > latest_yield[0].open:
                result["US10Y_bias"] = "BEARISH_FOR_GOLD"

        return result
