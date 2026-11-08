"""
AUREUS-SMC Institutional Persistence Repository
CRUD abstraction for trade audit trails, equity snapshots, and position rehydration.
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from core.models import TradeRecord, Position, Order, AccountState, OrderSide, PositionStatus
from storage.db import db_manager

logger = logging.getLogger("Repository")


class Repository:
    """
    Asynchronous data access layer for institutional auditability and crash recovery.
    """

    async def save_trade(self, trade: TradeRecord) -> None:
        """Persists a closed trade record to SQLite."""
        sql = """
        INSERT INTO trades (
            trade_id, position_id, symbol, side, volume, entry_price, exit_price,
            stop_loss, take_profit, r_multiple_realized, net_pnl, gross_pnl,
            commission, slippage, open_time, close_time, close_reason, smc_setup_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        async with db_manager.get_connection() as conn:
            await conn.execute(sql, (
                trade.trade_id,
                trade.position_id,
                trade.symbol,
                trade.side.value if hasattr(trade.side, "value") else str(trade.side),
                trade.volume,
                trade.entry_price,
                trade.exit_price,
                trade.stop_loss,
                trade.take_profit,
                trade.r_multiple_realized,
                trade.net_pnl,
                trade.gross_pnl,
                trade.commission,
                trade.slippage,
                trade.open_time.isoformat(),
                trade.close_time.isoformat(),
                trade.close_reason,
                trade.smc_setup_type
            ))
            await conn.commit()
            logger.info(f"Trade {trade.trade_id} persisted to SQLite.")

    async def get_all_trades(self, limit: int = 500) -> List[TradeRecord]:
        """Loads historical trades ordered by close time descending."""
        sql = "SELECT * FROM trades ORDER BY close_time DESC LIMIT ?;"
        trades: List[TradeRecord] = []
        async with db_manager.get_connection() as conn:
            async with conn.execute(sql, (limit,)) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    trades.append(TradeRecord(
                        trade_id=row["trade_id"],
                        position_id=row["position_id"],
                        symbol=row["symbol"],
                        side=OrderSide(row["side"]),
                        volume=row["volume"],
                        entry_price=row["entry_price"],
                        exit_price=row["exit_price"],
                        stop_loss=row["stop_loss"],
                        take_profit=row["take_profit"],
                        r_multiple_realized=row["r_multiple_realized"],
                        net_pnl=row["net_pnl"],
                        gross_pnl=row["gross_pnl"],
                        commission=row["commission"],
                        slippage=row["slippage"],
                        open_time=datetime.fromisoformat(row["open_time"]),
                        close_time=datetime.fromisoformat(row["close_time"]),
                        close_reason=row["close_reason"],
                        smc_setup_type=row["smc_setup_type"]
                    ))
        return trades

    async def save_active_position(self, pos: Position) -> None:
        """Stores or updates active position for crash rehydration."""
        sql = """
        INSERT OR REPLACE INTO active_positions (
            position_id, ticket, symbol, side, volume, original_volume,
            entry_price, current_price, stop_loss, take_profit,
            original_sl, original_tp, break_even_set, partial_closed,
            opened_at, commission_paid, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        async with db_manager.get_connection() as conn:
            await conn.execute(sql, (
                pos.position_id,
                pos.ticket,
                pos.symbol,
                pos.side.value if hasattr(pos.side, "value") else str(pos.side),
                pos.volume,
                pos.original_volume,
                pos.entry_price,
                pos.current_price,
                pos.stop_loss,
                pos.take_profit,
                pos.original_sl,
                pos.original_tp,
                1 if pos.break_even_set else 0,
                1 if pos.partial_closed else 0,
                pos.opened_at.isoformat(),
                pos.commission_paid,
                pos.status.value if hasattr(pos.status, "value") else str(pos.status)
            ))
            await conn.commit()

    async def remove_active_position(self, position_id: str) -> None:
        """Removes a position when liquidated."""
        sql = "DELETE FROM active_positions WHERE position_id = ?;"
        async with db_manager.get_connection() as conn:
            await conn.execute(sql, (position_id,))
            await conn.commit()

    async def rehydrate_positions(self) -> List[Position]:
        """Rehydrates active positions following system restart."""
        sql = "SELECT * FROM active_positions WHERE status != 'CLOSED';"
        positions: List[Position] = []
        async with db_manager.get_connection() as conn:
            async with conn.execute(sql) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    positions.append(Position(
                        position_id=row["position_id"],
                        ticket=row["ticket"],
                        symbol=row["symbol"],
                        side=OrderSide(row["side"]),
                        volume=row["volume"],
                        original_volume=row["original_volume"],
                        entry_price=row["entry_price"],
                        current_price=row["current_price"],
                        stop_loss=row["stop_loss"],
                        take_profit=row["take_profit"],
                        original_sl=row["original_sl"],
                        original_tp=row["original_tp"],
                        break_even_set=bool(row["break_even_set"]),
                        partial_closed=bool(row["partial_closed"]),
                        opened_at=datetime.fromisoformat(row["opened_at"]),
                        commission_paid=row["commission_paid"],
                        status=PositionStatus(row["status"])
                    ))
        if positions:
            logger.info(f"STATE REHYDRATION: Successfully restored {len(positions)} active positions from SQLite.")
        return positions

    async def save_snapshot(self, state: AccountState) -> None:
        """Stores equity curve snapshot."""
        sql = """
        INSERT INTO account_snapshots (
            balance, equity, free_margin, margin_used, unrealized_pnl,
            realized_daily_pnl, daily_drawdown_percent, trades_executed_today, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        async with db_manager.get_connection() as conn:
            await conn.execute(sql, (
                state.balance,
                state.equity,
                state.free_margin,
                state.margin_used,
                state.unrealized_pnl,
                state.realized_daily_pnl,
                state.daily_drawdown_percent,
                state.trades_executed_today,
                state.timestamp.isoformat()
            ))
            await conn.commit()

    async def get_snapshots(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Returns recent account equity snapshots for charts."""
        sql = "SELECT * FROM account_snapshots ORDER BY timestamp DESC LIMIT ?;"
        results = []
        async with db_manager.get_connection() as conn:
            async with conn.execute(sql, (limit,)) as cursor:
                rows = await cursor.fetchall()
                for row in reversed(rows):
                    results.append(dict(row))
        return results


# Global singleton
repository = Repository()
