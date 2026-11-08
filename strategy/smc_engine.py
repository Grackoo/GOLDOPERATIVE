"""
AUREUS-SMC Institutional Gold Strategy Engine
Synthesizes London Range, Liquidity Sweep, Displacement (MSS), and FVG mitigation into high-probability execution signals.
"""

from __future__ import annotations
import logging
from typing import Optional, List, Callable
from datetime import datetime
from core.models import (
    Bar, Tick, LondonRange, LiquiditySweep, MarketStructureShift,
    FairValueGap, OrderSide, SystemState
)
from core.events import (
    BarClosedEvent, LondonRangeCalculatedEvent, LiquiditySweepEvent,
    DisplacementEvent, FVGDetectedEvent, SignalGeneratedEvent, TickEvent
)
from core.event_bus import event_bus
from core.time_manager import time_manager
from core.state_machine import state_machine
from strategy.indicators import calculate_atr
from strategy.fractals import FractalDetector, SwingPoint
from strategy.london_range import LondonRangeDetector
from strategy.liquidity_sweep import LiquiditySweepDetector
from strategy.displacement import DisplacementDetector
from strategy.fvg_detector import FVGDetector
from config import settings

logger = logging.getLogger("SMCEngine")


class SMCEngine:
    """
    Complete SMC (Smart Money Concepts) algorithmic engine executing the London Sweep & NY Open strategy.
    """

    def __init__(
        self,
        news_filter_check: Optional[Callable[[datetime], bool]] = None
    ) -> None:
        self.news_filter_check = news_filter_check

        # Sub-detectors
        self.london_detector = LondonRangeDetector()
        self.sweep_detector = LiquiditySweepDetector()
        self.fractal_detector = FractalDetector(lookback=settings.SWING_LOOKBACK)
        self.displacement_detector = DisplacementDetector(settings.DISPLACEMENT_ATR_MULTIPLIER)
        self.fvg_detector = FVGDetector(settings.MIN_FVG_SIZE_POINTS)

        # Context State for Current Session
        self.active_sweep: Optional[LiquiditySweep] = None
        self.active_mss: Optional[MarketStructureShift] = None
        self.active_fvg: Optional[FairValueGap] = None
        self.active_signal: Optional[SignalGeneratedEvent] = None
        self.current_atr: float = 1.0

        # Wire event subscriptions
        event_bus.subscribe(BarClosedEvent, self.on_bar_closed)
        event_bus.subscribe(TickEvent, self.on_tick)

    @property
    def london_range(self) -> Optional[LondonRange]:
        return self.london_detector.current_range

    async def on_bar_closed(self, event: BarClosedEvent) -> None:
        """Core state-machine evaluation invoked upon every candle close."""
        bar = event.bar

        # We primarily analyze M1 and M5 bars
        if bar.timeframe not in {"M1", "M5"}:
            return

        ny_time = time_manager.to_ny_time(bar.timestamp)

        # 1. Update London Accumulation Range (03:00 - 08:00 EST)
        l_range = self.london_detector.process_bar(bar)

        # Session State Transition
        if time_manager.is_in_london_session(bar.timestamp):
            if state_machine.state != SystemState.LONDON_ACCUMULATION:
                await state_machine.transition_to(
                    SystemState.LONDON_ACCUMULATION,
                    f"London session active (03:00 - 08:00 EST)"
                )
            return

        # 2. Check if we entered NY Execution Window (08:00 - 10:30 EST)
        if time_manager.is_in_ny_execution_window(bar.timestamp):
            if state_machine.state in {SystemState.IDLE, SystemState.LONDON_ACCUMULATION}:
                await state_machine.transition_to(
                    SystemState.NY_SCANNING_SWEEP,
                    "NY Open window active (08:00 - 10:30 EST)"
                )
        else:
            # Outside execution window
            if state_machine.state in {
                SystemState.NY_SCANNING_SWEEP,
                SystemState.NY_SCANNING_DISPLACEMENT,
                SystemState.NY_SCANNING_FVG
            }:
                await state_machine.transition_to(
                    SystemState.IDLE,
                    "NY Open window closed. Stand down."
                )
                self.reset_session_context()
            return

        # Check macro news blackout
        if self.news_filter_check and self.news_filter_check(bar.timestamp):
            logger.info("News blackout window active. Strategy entries suspended.")
            return

        # Need finalized London Range to proceed
        if not l_range or not l_range.is_finalized:
            return

        # 3. Step A: Scanning for Liquidity Sweep
        if state_machine.state == SystemState.NY_SCANNING_SWEEP:
            sweep = self.sweep_detector.check_sweep(bar, l_range)
            if sweep:
                self.active_sweep = sweep
                await state_machine.transition_to(
                    SystemState.NY_SCANNING_DISPLACEMENT,
                    f"Confirmed {sweep.direction.value} sweep of {sweep.level_swept} (Wick: {sweep.wick_extreme})"
                )

        # 4. Step B: Scanning for Market Structure Shift (MSS / CHOCH) with Displacement
        elif state_machine.state == SystemState.NY_SCANNING_DISPLACEMENT:
            if not self.active_sweep:
                return

            expected_direction = self.active_sweep.direction
            # Calculate ATR over recent bars
            from data.bar_aggregator import BarAggregator
            # We fetch recent bars from caller or buffer
            bars = self._get_recent_bars(bar.timeframe)
            if len(bars) >= 15:
                self.current_atr = calculate_atr(bars, settings.ATR_PERIOD)

            sh = self.fractal_detector.get_latest_swing_high(bars)
            sl = self.fractal_detector.get_latest_swing_low(bars)

            fallback_level = None
            if expected_direction == OrderSide.BUY:
                if len(bars) >= 2:
                    fallback_level = max(b.high for b in bars[-3:-1])
            else:
                if len(bars) >= 2:
                    fallback_level = min(b.low for b in bars[-3:-1])

            mss = self.displacement_detector.check_mss(
                current_bar=bar,
                atr=self.current_atr,
                recent_swing_high=sh,
                recent_swing_low=sl,
                fallback_level=fallback_level,
                expected_direction=expected_direction
            )

            if mss:
                self.active_mss = mss
                await state_machine.transition_to(
                    SystemState.NY_SCANNING_FVG,
                    f"Confirmed {mss.direction.value} displacement MSS across {mss.broken_swing_level}"
                )

        # 5. Step C: Scanning for Fair Value Gap (FVG)
        elif state_machine.state == SystemState.NY_SCANNING_FVG:
            bars = self._get_recent_bars(bar.timeframe)
            if len(bars) >= 3:
                c1, c2, c3 = bars[-3], bars[-2], bars[-1]
                fvg = self.fvg_detector.check_fvg(c1, c2, c3)
                if fvg and self.active_sweep and fvg.direction == self.active_sweep.direction:
                    self.active_fvg = fvg
                    await self._generate_setup_signal(fvg)

    async def on_tick(self, event: TickEvent) -> None:
        """Evaluates intra-candle FVG mitigation and limit entry touch."""
        tick = event.tick
        if state_machine.state == SystemState.PENDING_ORDER and self.active_fvg:
            # Check if price taps Consequent Encroachment (50%)
            if self.fvg_detector.check_mitigation(self.active_fvg, tick.mid, tick.timestamp):
                logger.info(
                    f"FVG MITIGATED: Price {tick.mid} touched target {self.active_fvg.consequent_encroachment}"
                )

    async def _generate_setup_signal(self, fvg: FairValueGap) -> None:
        """
        Synthesizes the SMC entry order parameters with strict 1:3 RRR.
        """
        assert self.active_sweep is not None

        direction = fvg.direction.value
        entry_price = fvg.consequent_encroachment if settings.FVG_ENTRY_MODE == "50_PERCENT" else (
            fvg.bottom if fvg.direction == OrderSide.BUY else fvg.top
        )

        # Buffer of 1 pip ($0.10) beyond extreme wick for Stop Loss
        sl_buffer = 0.10
        if fvg.direction == OrderSide.BUY:
            stop_loss = round(self.active_sweep.wick_extreme - sl_buffer, 2)
            risk_distance = round(entry_price - stop_loss, 2)
            if risk_distance <= 0:
                logger.warning("Invalid risk distance for BUY setup. Aborting signal.")
                return
            take_profit = round(entry_price + (risk_distance * settings.TARGET_RRR), 2)
        else:
            stop_loss = round(self.active_sweep.wick_extreme + sl_buffer, 2)
            risk_distance = round(stop_loss - entry_price, 2)
            if risk_distance <= 0:
                logger.warning("Invalid risk distance for SELL setup. Aborting signal.")
                return
            take_profit = round(entry_price - (risk_distance * settings.TARGET_RRR), 2)

        signal = SignalGeneratedEvent(
            signal_id=f"SIG_{int(datetime.utcnow().timestamp())}",
            symbol=settings.SYMBOL,
            direction=direction,
            entry_price=round(entry_price, 2),
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            risk_reward_ratio=settings.TARGET_RRR,
            fvg=fvg,
            reason=(
                f"SMC Setup: Swept {self.active_sweep.level_swept} -> MSS with "
                f"{self.active_mss.body_to_atr_ratio if self.active_mss else 1.5}x ATR -> FVG CE Tap"
            )
        )
        self.active_signal = signal

        await state_machine.transition_to(
            SystemState.PENDING_ORDER,
            f"Signal generated: {direction} @ {entry_price} | SL: {stop_loss} | TP: {take_profit} (1:{settings.TARGET_RRR})"
        )

        logger.info(
            f"=== INSTITUTIONAL SMC SIGNAL FIRED ==="
            f"\nDirection: {signal.direction}"
            f"\nEntry:     ${signal.entry_price:.2f}"
            f"\nStop Loss: ${signal.stop_loss:.2f} (Risk: ${risk_distance:.2f})"
            f"\nTarget TP: ${signal.take_profit:.2f} (Reward: ${risk_distance * settings.TARGET_RRR:.2f})"
            f"\nRRR:       1:{signal.risk_reward_ratio}"
        )
        await event_bus.publish(signal)

    def _get_recent_bars(self, timeframe: str) -> List[Bar]:
        """Helper to get recent bars from global aggregator."""
        if hasattr(self, "_bar_provider"):
            try:
                return self._bar_provider(timeframe, include_forming=False)
            except TypeError:
                return self._bar_provider(timeframe)
        return []

    def set_bar_provider(self, provider: Callable[[str], List[Bar]]) -> None:
        self._bar_provider = provider

    def reset_session_context(self) -> None:
        self.active_sweep = None
        self.active_mss = None
        self.active_fvg = None
        self.active_signal = None
