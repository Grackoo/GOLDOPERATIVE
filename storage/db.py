"""
AUREUS-SMC Asynchronous SQLite Database Manager
High-concurrency storage using aiosqlite configured with Write-Ahead Logging (WAL).
"""

from __future__ import annotations
import aiosqlite
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from config import settings

logger = logging.getLogger("Database")

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    volume REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    r_multiple_realized REAL NOT NULL,
    net_pnl REAL NOT NULL,
    gross_pnl REAL NOT NULL,
    commission REAL NOT NULL,
    slippage REAL NOT NULL,
    open_time TEXT NOT NULL,
    close_time TEXT NOT NULL,
    close_reason TEXT NOT NULL,
    smc_setup_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    client_order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    volume REAL NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    filled_at TEXT,
    filled_price REAL,
    slippage REAL,
    commission REAL,
    comment TEXT
);

CREATE TABLE IF NOT EXISTS active_positions (
    position_id TEXT PRIMARY KEY,
    ticket INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    volume REAL NOT NULL,
    original_volume REAL NOT NULL,
    entry_price REAL NOT NULL,
    current_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    original_sl REAL NOT NULL,
    original_tp REAL NOT NULL,
    break_even_set INTEGER NOT NULL,
    partial_closed INTEGER NOT NULL,
    opened_at TEXT NOT NULL,
    commission_paid REAL NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    balance REAL NOT NULL,
    equity REAL NOT NULL,
    free_margin REAL NOT NULL,
    margin_used REAL NOT NULL,
    unrealized_pnl REAL NOT NULL,
    realized_daily_pnl REAL NOT NULL,
    daily_drawdown_percent REAL NOT NULL,
    trades_executed_today INTEGER NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_close_time ON trades(close_time);
CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON account_snapshots(timestamp);
"""


class DatabaseManager:
    """
    Manages SQLite database lifecycle with asynchronous connection pooling and WAL mode.
    """

    def __init__(self, db_path: str = settings.DATABASE_PATH) -> None:
        self.db_path = db_path
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    async def init_db(self) -> None:
        """Initializes tables, indexes and configures PRAGMA journal_mode=WAL."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()
            # Verify WAL mode
            async with db.execute("PRAGMA journal_mode;") as cursor:
                row = await cursor.fetchone()
                mode = row[0] if row else "unknown"
                logger.info(f"SQLite initialized at {self.db_path} with journal_mode={mode.upper()}")

    @asynccontextmanager
    async def get_connection(self):
        """Yields an active aiosqlite connection with row_factory enabled."""
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            yield conn


# Global singleton
db_manager = DatabaseManager()
