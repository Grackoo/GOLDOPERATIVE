"""
AUREUS-SMC MetaTrader 5 (MT5) Institutional Gateway
Direct API connector for ECN/STP execution via MetaTrader 5 terminal.
"""

from __future__ import annotations
import logging
from typing import List, Optional
from datetime import datetime
from core.models import Order, Position, TradeRecord, AccountState, OrderSide, OrderType, OrderStatus, PositionStatus
from execution.base_broker import BaseBrokerClient
from config import settings

logger = logging.getLogger("MT5Broker")

try:
    import MetaTrader5 as mt5  # type: ignore
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


class MT5BrokerClient(BaseBrokerClient):
    """
    Production gateway interfacing directly with MetaTrader 5 via IPC.
    Handles order execution, SL/TP adjustments, and tick subscriptions.
    """

    def __init__(
        self,
        login: int = settings.MT5_LOGIN,
        password: str = settings.MT5_PASSWORD,
        server: str = settings.MT5_SERVER,
        path: str = settings.MT5_PATH
    ) -> None:
        self.login = login
        self.password = password
        self.server = server
        self.path = path
        self._connected = False

    async def connect(self) -> bool:
        if not MT5_AVAILABLE:
            logger.warning("MetaTrader5 package not installed. Running in simulation gateway mode.")
            return False

        init_kwargs = {}
        if self.path:
            init_kwargs["path"] = self.path
        if self.login and self.password and self.server:
            init_kwargs["login"] = self.login
            init_kwargs["password"] = self.password
            init_kwargs["server"] = self.server

        if not mt5.initialize(**init_kwargs):
            logger.error(f"MT5 Initialization failed: {mt5.last_error()}")
            return False

        self._connected = True
        logger.info(f"Connected to MT5 Terminal successfully. Version: {mt5.version()}")
        return True

    async def disconnect(self) -> None:
        if MT5_AVAILABLE and self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5 Terminal shutdown.")

    async def get_account_state(self) -> AccountState:
        if not MT5_AVAILABLE or not self._connected:
            return AccountState(
                balance=100000.0,
                equity=100000.0,
                free_margin=100000.0,
                margin_used=0.0,
                unrealized_pnl=0.0,
                realized_daily_pnl=0.0,
                daily_drawdown_percent=0.0,
                trades_executed_today=0,
                is_circuit_breaker_active=False,
                timestamp=datetime.utcnow()
            )

        account = mt5.account_info()
        if account is None:
            raise RuntimeError(f"Failed to fetch MT5 account info: {mt5.last_error()}")

        unrealized = account.profit
        equity = account.equity
        balance = account.balance
        free_margin = account.margin_free
        margin_used = account.margin

        dd_pct = max(0.0, (balance - equity) / balance * 100.0) if balance > 0 else 0.0

        return AccountState(
            balance=round(balance, 2),
            equity=round(equity, 2),
            free_margin=round(free_margin, 2),
            margin_used=round(margin_used, 2),
            unrealized_pnl=round(unrealized, 2),
            realized_daily_pnl=0.0,
            daily_drawdown_percent=round(dd_pct, 2),
            trades_executed_today=0,
            is_circuit_breaker_active=False,
            timestamp=datetime.utcnow()
        )

    async def place_order(self, order: Order) -> Order:
        if not MT5_AVAILABLE or not self._connected:
            logger.warning("MT5 not active. Order mocked.")
            order.status = OrderStatus.FILLED
            order.filled_price = order.entry_price
            return order

        order_type_mt5 = mt5.ORDER_TYPE_BUY if order.side == OrderSide.BUY else mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(order.symbol).ask if order.side == OrderSide.BUY else mt5.symbol_info_tick(order.symbol).bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": order.symbol,
            "volume": order.volume,
            "type": order_type_mt5,
            "price": price,
            "sl": order.stop_loss,
            "tp": order.take_profit,
            "deviation": int(settings.MAX_ALLOWED_SLIPPAGE_DOLLARS / settings.TICK_SIZE),
            "magic": 1088,
            "comment": "AUREUS-SMC",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"MT5 order_send failed: retcode={result.retcode}, comment={result.comment}")
            order.status = OrderStatus.REJECTED
            order.comment = result.comment
        else:
            order.status = OrderStatus.FILLED
            order.filled_price = result.price
            order.filled_at = datetime.utcnow()
            logger.info(f"MT5 Order executed successfully! Ticket: {result.order}")

        return order

    async def modify_order(
        self,
        position_id: str,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None
    ) -> bool:
        if not MT5_AVAILABLE or not self._connected:
            return True

        ticket = int(position_id)
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False

        p = pos[0]
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": p.symbol,
            "sl": new_sl if new_sl is not None else p.sl,
            "tp": new_tp if new_tp is not None else p.tp
        }
        res = mt5.order_send(request)
        return res.retcode == mt5.TRADE_RETCODE_DONE

    async def partial_close(
        self,
        position_id: str,
        volume: float,
        reason: str = "PARTIAL_TP"
    ) -> Optional[TradeRecord]:
        if not MT5_AVAILABLE or not self._connected:
            return None

        ticket = int(position_id)
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return None

        pos = positions[0]
        opp_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(pos.symbol).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(pos.symbol).ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": pos.symbol,
            "volume": volume,
            "type": opp_type,
            "price": price,
            "deviation": int(settings.MAX_ALLOWED_SLIPPAGE_DOLLARS / settings.TICK_SIZE),
            "magic": 1088,
            "comment": f"AUREUS-SMC {reason}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(request)
        if res.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"MT5 Partial close of {volume} lots executed for ticket #{ticket}")
            return None
        return None

    async def close_position(self, position_id: str, reason: str = "MANUAL") -> Optional[TradeRecord]:
        if not MT5_AVAILABLE or not self._connected:
            return None

        ticket = int(position_id)
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return None

        pos = positions[0]
        opp_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(pos.symbol).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(pos.symbol).ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": opp_type,
            "price": price,
            "deviation": int(settings.MAX_ALLOWED_SLIPPAGE_DOLLARS / settings.TICK_SIZE),
            "magic": 1088,
            "comment": f"AUREUS-SMC {reason}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        res = mt5.order_send(request)
        if res.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"MT5 Full position closed for ticket #{ticket}")
            return None
        return None

    async def get_open_positions(self) -> List[Position]:
        if not MT5_AVAILABLE or not self._connected:
            return []

        raw_positions = mt5.positions_get(symbol=settings.SYMBOL)
        if not raw_positions:
            return []

        positions = []
        for p in raw_positions:
            side = OrderSide.BUY if p.type == mt5.ORDER_TYPE_BUY else OrderSide.SELL
            pos = Position(
                position_id=str(p.ticket),
                ticket=p.ticket,
                symbol=p.symbol,
                side=side,
                volume=p.volume,
                original_volume=p.volume,
                entry_price=p.price_open,
                current_price=p.price_current,
                stop_loss=p.sl,
                take_profit=p.tp,
                original_sl=p.sl,
                original_tp=p.tp,
                opened_at=datetime.fromtimestamp(p.time),
                unrealized_pnl=p.profit
            )
            positions.append(pos)
        return positions
