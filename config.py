"""
AUREUS-SMC Institutional Trading System
Core Configuration and Environment Settings
"""

from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SystemSettings(BaseSettings):
    """
    Centralized configuration with validation for institutional execution on XAU/USD.
    Supports dynamic overriding via environment variables or .env file.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # --- System & Environment ---
    SYSTEM_NAME: str = "AUREUS-SMC Institutional Gold Engine"
    ENVIRONMENT: Literal["PRODUCTION", "SANDBOX", "PAPER"] = "SANDBOX"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    TIMEZONE: str = "America/New_York"  # Canonical institutional EST/EDT zone

    # --- Asset Specification (XAU/USD Gold CFD) ---
    SYMBOL: str = "XAUUSD"
    CONTRACT_SIZE: float = 100.0        # 1 Standard Lot = 100 Troy Ounces
    TICK_SIZE: float = 0.01             # Price increments in 1 cent ($0.01)
    PIP_SIZE: float = 0.10              # Standard gold pip = 10 cents ($0.10)
    MIN_LOT: float = 0.01
    MAX_LOT: float = 50.0
    LOT_STEP: float = 0.01

    # --- SMC Strategy Session Schedules (New York Time) ---
    # London Session (Accumulation / Liquidity Pool Formation)
    LONDON_SESSION_START: str = "03:00"  # 03:00 AM EST/EDT
    LONDON_SESSION_END: str = "08:00"    # 08:00 AM EST/EDT

    # New York Open Execution Window (Sweep & Displacement)
    NY_EXECUTION_START: str = "08:00"    # 08:00 AM EST/EDT
    NY_EXECUTION_END: str = "10:30"      # 10:30 AM EST/EDT

    # Hard Session Cut-off / Flattening (optional protection)
    SESSION_HARD_CLOSE: str = "16:00"    # 16:00 PM EST

    # --- SMC Algorithm Parameters ---
    ATR_PERIOD: int = 14
    DISPLACEMENT_ATR_MULTIPLIER: float = 1.5  # Candle body > 1.5 * ATR qualifies MSS
    SWING_LOOKBACK: int = 5                   # Fractals swing lookback
    FVG_ENTRY_MODE: Literal["50_PERCENT", "EDGE"] = "50_PERCENT" # Consequent Encroachment (50%)
    MIN_FVG_SIZE_POINTS: float = 0.30         # Minimum FVG imbalance in dollars ($0.30)
    SWEEP_MIN_TICKS: int = 2                  # Minimum penetration beyond London High/Low

    # --- Risk Management & Math Engine ---
    INITIAL_BALANCE: float = 100_000.0        # Baseline institutional capital ($100k)
    RISK_PER_TRADE_PERCENT: float = 1.0       # 1.0% per setup (0.01)
    TARGET_RRR: float = 3.0                   # Strict 1:3 minimum risk/reward ratio
    BREAK_EVEN_RRR: float = 1.5               # Move to BE at 1:1.5 RRR
    BE_OFFSET_DOLLARS: float = 0.10           # Additional buffer for BE to cover commission & spread ($0.10)
    PARTIAL_TP_RRR: float = 2.0               # Partial close trigger at 1:2.0 RRR
    PARTIAL_TP_PERCENT: float = 50.0          # 50% partial close of volume

    # --- Microstructure & Spread Filters ---
    MAX_ALLOWED_SPREAD_DOLLARS: float = 0.30  # Max spread $0.30 (3 pips / 30 cents)
    MAX_ALLOWED_SLIPPAGE_DOLLARS: float = 0.20 # Max slippage tolerance
    COMMISSION_PER_LOT_ROUNDTRIP: float = 6.0 # $6 per roundtrip lot ECN commission

    # --- Circuit Breakers & Kill Switches ---
    MAX_TRADES_PER_SESSION: int = 2           # Hard cap: Max 2 trades per morning
    MAX_DAILY_DRAWDOWN_PERCENT: float = 2.0   # Hard stop: 2.0% daily max loss
    COOLDOWN_AFTER_LOSS_SECONDS: int = 300    # 5 minutes pause after a loss

    # --- Macroeconomic Calendar Filter ---
    NEWS_FILTER_ENABLED: bool = True
    NEWS_BLACKOUT_MINUTES_BEFORE: int = 15    # Freeze entries 15m before High Impact
    NEWS_BLACKOUT_MINUTES_AFTER: int = 15     # Freeze entries 15m after High Impact
    NEWS_API_PROVIDER: Literal["MOCK", "FOREXFACTORY", "INVESTING"] = "FOREXFACTORY"

    # --- Broker Gateway Selection ---
    BROKER_TYPE: Literal["PAPER", "MT5", "OANDA"] = "PAPER"

    # --- Live Real-Time Market Data Feed ---
    # REAL_GOLD: 24/7 Real Spot Gold (XAU/USD) live WebSocket feed with real tick-by-tick prices
    # MT5: Live ticks directly from MetaTrader 5 terminal
    # OANDA: Live ticks from OANDA v20 pricing stream
    # SIMULATED: Synthetic tick generator for off-market simulation
    DATA_FEED_SOURCE: Literal["REAL_GOLD", "MT5", "OANDA", "SIMULATED"] = "REAL_GOLD"

    # MT5 Configuration (Optional / If Active)
    MT5_LOGIN: int = 0
    MT5_PASSWORD: str = ""
    MT5_SERVER: str = ""
    MT5_PATH: str = ""

    # OANDA v20 Configuration (Optional / If Active)
    OANDA_ACCOUNT_ID: str = ""
    OANDA_ACCESS_TOKEN: str = ""
    OANDA_ENVIRONMENT: Literal["practice", "live"] = "practice"

    # Paper Simulator Parameters
    SIMULATED_LATENCY_MIN_MS: float = 10.0
    SIMULATED_LATENCY_MAX_MS: float = 35.0
    SIMULATED_SLIPPAGE_PROBABILITY: float = 0.15

    # --- Database & Persistence ---
    DATABASE_PATH: str = "storage/aureus_trades.db"
    SQLITE_WAL_MODE: bool = True

    # --- Web Dashboard & High-Speed WebSockets ---
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8000
    WS_HEARTBEAT_INTERVAL: float = 5.0
    CANDLE_BUFFER_SIZE_M1: int = 1440         # 24 hours of 1-minute bars
    CANDLE_BUFFER_SIZE_M5: int = 576          # 48 hours of 5-minute bars
    CANDLE_BUFFER_SIZE_M15: int = 384         # 4 days of 15-minute bars
    CANDLE_BUFFER_SIZE_M30: int = 192         # 4 days of 30-minute bars
    TICK_BUFFER_SIZE: int = 50_000            # Circular tick cache


# Global settings singleton
settings = SystemSettings()
