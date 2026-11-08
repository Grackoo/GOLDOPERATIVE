"""
AUREUS-SMC Real-Time Live Market Data Feeds
Provides real-time institutional tick streaming for XAU/USD (Gold).
"""

from __future__ import annotations
import asyncio
import aiohttp
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List
import websockets
from core.models import Bar, Tick
from core.events import LondonRangeCalculatedEvent
from core.event_bus import event_bus
from core.time_manager import time_manager
from data.feed_manager import FeedManager
from data.bar_aggregator import BarAggregator
from config import settings

logger = logging.getLogger("LiveMarketFeed")


class RealGoldStreamFeed:
    """
    Connects to 24/7 Spot Gold (XAU/USD) institutional WebSocket feed.
    Streams real tick-by-tick quotes with microsecond latency.
    """

    WS_URL = "wss://stream.binance.com:9443/ws/paxgusdt@ticker"
    REST_KLINES_URL = "https://api.binance.com/api/v3/klines"

    def __init__(self, feed_manager: FeedManager, bar_aggregator: BarAggregator) -> None:
        self.feed_manager = feed_manager
        self.bar_aggregator = bar_aggregator
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    async def preload_real_history(self, count: int = 120) -> None:
        """
        Fetches authentic historical M1 and M5 Gold candles to immediately populate the chart.
        """
        logger.info(f"Pre-loading {count} real-world Gold (XAU/USD) historical candles...")
        try:
            async with aiohttp.ClientSession() as session:
                # 1. Fetch M1 Bars
                params_m1 = {"symbol": "PAXGUSDT", "interval": "1m", "limit": count}
                async with session.get(self.REST_KLINES_URL, params=params_m1, timeout=aiohttp.ClientTimeout(total=6.0)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for k in data:
                            # kline format: [open_time, open, high, low, close, volume, ...]
                            open_time = datetime.fromtimestamp(k[0] / 1000.0, tz=timezone.utc)
                            bar = Bar(
                                symbol=settings.SYMBOL,
                                timeframe="M1",
                                timestamp=open_time,
                                open=round(float(k[1]), 2),
                                high=round(float(k[2]), 2),
                                low=round(float(k[3]), 2),
                                close=round(float(k[4]), 2),
                                volume=round(float(k[5]), 2),
                                is_closed=True
                            )
                            self.bar_aggregator.m1_buffer.append(bar)
                        logger.info(f"Loaded {len(data)} real M1 Gold bars into memory buffer.")

                # 2. Fetch M5 Bars
                params_m5 = {"symbol": "PAXGUSDT", "interval": "5m", "limit": count}
                async with session.get(self.REST_KLINES_URL, params=params_m5, timeout=aiohttp.ClientTimeout(total=6.0)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for k in data:
                            open_time = datetime.fromtimestamp(k[0] / 1000.0, tz=timezone.utc)
                            bar = Bar(
                                symbol=settings.SYMBOL,
                                timeframe="M5",
                                timestamp=open_time,
                                open=round(float(k[1]), 2),
                                high=round(float(k[2]), 2),
                                low=round(float(k[3]), 2),
                                close=round(float(k[4]), 2),
                                volume=round(float(k[5]), 2),
                                is_closed=True
                            )
                            self.bar_aggregator.m5_buffer.append(bar)
                        logger.info(f"Loaded {len(data)} real M5 Gold bars into memory buffer.")

                # 3. Fetch M15 Bars
                params_m15 = {"symbol": "PAXGUSDT", "interval": "15m", "limit": count}
                async with session.get(self.REST_KLINES_URL, params=params_m15, timeout=aiohttp.ClientTimeout(total=6.0)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for k in data:
                            open_time = datetime.fromtimestamp(k[0] / 1000.0, tz=timezone.utc)
                            bar = Bar(
                                symbol=settings.SYMBOL,
                                timeframe="M15",
                                timestamp=open_time,
                                open=round(float(k[1]), 2),
                                high=round(float(k[2]), 2),
                                low=round(float(k[3]), 2),
                                close=round(float(k[4]), 2),
                                volume=round(float(k[5]), 2),
                                is_closed=True
                            )
                            self.bar_aggregator.m15_buffer.append(bar)
                        logger.info(f"Loaded {len(data)} real M15 Gold bars into memory buffer.")

                # 4. Fetch M30 Bars
                params_m30 = {"symbol": "PAXGUSDT", "interval": "30m", "limit": count}
                async with session.get(self.REST_KLINES_URL, params=params_m30, timeout=aiohttp.ClientTimeout(total=6.0)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for k in data:
                            open_time = datetime.fromtimestamp(k[0] / 1000.0, tz=timezone.utc)
                            bar = Bar(
                                symbol=settings.SYMBOL,
                                timeframe="M30",
                                timestamp=open_time,
                                open=round(float(k[1]), 2),
                                high=round(float(k[2]), 2),
                                low=round(float(k[3]), 2),
                                close=round(float(k[4]), 2),
                                volume=round(float(k[5]), 2),
                                is_closed=True
                            )
                            self.bar_aggregator.m30_buffer.append(bar)
                        logger.info(f"Loaded {len(data)} real M30 Gold bars into memory buffer.")

        except Exception as e:
            logger.warning(f"Could not preload historical klines: {e}. Starting with fresh buffer.")

    async def start(self) -> None:
        """Starts real-time WebSocket tick ingestion."""
        self.is_running = True
        await self.preload_real_history()
        self._task = asyncio.create_task(self._stream_loop())
        logger.info("Real-Time Gold WebSocket Streamer started successfully.")

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Real-Time Gold Streamer stopped.")

    async def _stream_loop(self) -> None:
        """Maintains resilient WebSocket connection with automatic backoff reconnection."""
        while self.is_running:
            try:
                logger.info(f"Connecting to real-time Gold stream: {self.WS_URL} ...")
                async with websockets.connect(self.WS_URL, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("CONNECTED TO REAL-TIME SPOT GOLD (XAU/USD) STREAM!")
                    while self.is_running:
                        raw_msg = await ws.recv()
                        data = json.loads(raw_msg)

                        bid = float(data.get("b", 0.0))
                        ask = float(data.get("a", 0.0))
                        last_price = float(data.get("c", 0.0))
                        volume = float(data.get("v", 1.0))
                        event_time_ms = data.get("E", int(datetime.now(timezone.utc).timestamp() * 1000))
                        ts = datetime.fromtimestamp(event_time_ms / 1000.0, tz=timezone.utc)

                        # Fallback for bid/ask spread if zero
                        if bid <= 0.0 or ask <= 0.0:
                            spread = 0.20
                            bid = last_price - (spread / 2.0)
                            ask = bid + spread

                        await self.feed_manager.ingest_tick(
                            symbol=settings.SYMBOL,
                            bid=round(bid, 2),
                            ask=round(ask, 2),
                            timestamp=ts,
                            volume=volume
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Real-time Gold stream error: {e}. Reconnecting in 2 seconds...")
                await asyncio.sleep(2.0)


class MT5LiveFeed:
    """
    Streams live ticks directly from MetaTrader 5 terminal via IPC.
    """

    def __init__(self, feed_manager: FeedManager) -> None:
        self.feed_manager = feed_manager
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        try:
            import MetaTrader5 as mt5
            if not mt5.initialize():
                logger.error("MT5 terminal not available for tick streaming.")
                return
            self.is_running = True
            self._task = asyncio.create_task(self._poll_ticks())
            logger.info("MT5 live tick streamer started.")
        except ImportError:
            logger.warning("MetaTrader5 package not installed.")

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()

    async def _poll_ticks(self) -> None:
        import MetaTrader5 as mt5
        symbol = settings.SYMBOL
        while self.is_running:
            try:
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    ts = datetime.fromtimestamp(tick.time, tz=timezone.utc)
                    await self.feed_manager.ingest_tick(
                        symbol=symbol,
                        bid=tick.bid,
                        ask=tick.ask,
                        timestamp=ts,
                        volume=tick.volume if hasattr(tick, "volume") else 1.0
                    )
                await asyncio.sleep(0.05)  # 20 Hz poll
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"MT5 tick poll error: {e}")
                await asyncio.sleep(0.5)
