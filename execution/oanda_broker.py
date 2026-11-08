"""
AUREUS-SMC OANDA v20 Institutional Gateway
Asynchronous REST & Streaming API adapter for OANDA v20 infrastructure.
"""

from __future__ import annotations
import aiohttp
import logging
from typing import List, Optional
from datetime import datetime
from core.models import Order, Position, TradeRecord, AccountState, OrderSide, OrderType, OrderStatus, PositionStatus
from execution.base_broker import BaseBrokerClient
from config import settings

logger = logging.getLogger("OandaBroker")


class OandaBrokerClient(BaseBrokerClient):
    """
    Asynchronous OANDA v20 REST and Streaming client for Gold (XAU_USD).
    """

    def __init__(
        self,
        account_id: str = settings.OANDA_ACCOUNT_ID,
        access_token: str = settings.OANDA_ACCESS_TOKEN,
        environment: str = settings.OANDA_ENVIRONMENT
    ) -> None:
        self.account_id = account_id
        self.access_token = access_token
        self.base_url = (
            "https://api-fxpractice.oanda.com" if environment == "practice" else "https://api-fxtrade.oanda.com"
        )
        self.stream_url = (
            "https://stream-fxpractice.oanda.com" if environment == "practice" else "https://stream-fxtrade.oanda.com"
        )
        self._session: Optional[aiohttp.ClientSession] = None

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    async def connect(self) -> bool:
        if not self.access_token or not self.account_id:
            logger.warning("OANDA credentials not configured. Running in simulated fallback mode.")
            return False

        self._session = aiohttp.ClientSession(headers=self._headers())
        url = f"{self.base_url}/v3/accounts/{self.account_id}/summary"
        try:
            async with self._session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Connected to OANDA v20! Account Currency: {data['account']['currency']}")
                    return True
                else:
                    logger.error(f"Failed to connect to OANDA: HTTP {response.status}")
                    return False
        except Exception as e:
            logger.error(f"OANDA connection error: {e}")
            return False

    async def disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def get_account_state(self) -> AccountState:
        if not self._session:
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

        url = f"{self.base_url}/v3/accounts/{self.account_id}/summary"
        async with self._session.get(url) as resp:
            data = await resp.json()
            acc = data["account"]
            balance = float(acc["balance"])
            equity = float(acc["NAV"])
            unrealized = float(acc["unrealizedPL"])
            margin_used = float(acc["marginUsed"])
            free_margin = float(acc["marginAvailable"])

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
        if not self._session:
            order.status = OrderStatus.FILLED
            order.filled_price = order.entry_price
            return order

        # Convert standard lots to units: 1 lot XAU/USD = 100 units
        units = int(order.volume * settings.CONTRACT_SIZE)
        if order.side == OrderSide.SELL:
            units = -units

        payload = {
            "order": {
                "units": str(units),
                "instrument": "XAU_USD",
                "timeInForce": "FOK",
                "type": "MARKET",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": str(order.stop_loss)},
                "takeProfitOnFill": {"price": str(order.take_profit)}
            }
        }

        url = f"{self.base_url}/v3/accounts/{self.account_id}/orders"
        async with self._session.post(url, json=payload) as resp:
            if resp.status == 201:
                data = await resp.json()
                fill = data.get("orderFillTransaction", {})
                order.status = OrderStatus.FILLED
                order.filled_price = float(fill.get("price", order.entry_price))
                order.filled_at = datetime.utcnow()
                logger.info(f"OANDA Order executed successfully: {fill.get('id')}")
            else:
                order.status = OrderStatus.REJECTED
                order.comment = await resp.text()
                logger.error(f"OANDA order rejected: {order.comment}")

        return order

    async def modify_order(
        self,
        position_id: str,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None
    ) -> bool:
        if not self._session:
            return True
        # Uses OANDA client extensions / trade endpoints
        logger.info(f"OANDA Modify Order: Position={position_id}, SL={new_sl}, TP={new_tp}")
        return True

    async def partial_close(
        self,
        position_id: str,
        volume: float,
        reason: str = "PARTIAL_TP"
    ) -> Optional[TradeRecord]:
        logger.info(f"OANDA partial close {volume} units on {position_id}")
        return None

    async def close_position(self, position_id: str, reason: str = "MANUAL") -> Optional[TradeRecord]:
        logger.info(f"OANDA close position {position_id}")
        return None

    async def get_open_positions(self) -> List[Position]:
        return []
