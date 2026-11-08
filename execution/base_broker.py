"""
AUREUS-SMC Institutional Broker Gateway Specification
Abstract base interface for execution venues (Paper Simulator, MT5, OANDA).
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional, Callable, Awaitable
from core.models import Order, Position, TradeRecord, AccountState, Tick


class BaseBrokerClient(ABC):
    """
    Standardized asynchronous broker gateway interface.
    Decouples algorithmic strategy logic from low-level broker execution protocols.
    """

    @abstractmethod
    async def connect(self) -> bool:
        """Establishes connection and authenticates with broker infrastructure."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully terminates connection and closes active streams."""
        pass

    @abstractmethod
    async def get_account_state(self) -> AccountState:
        """Retrieves real-time balance, equity, margin, and floating PnL."""
        pass

    @abstractmethod
    async def place_order(self, order: Order) -> Order:
        """Transmits order for execution."""
        pass

    @abstractmethod
    async def modify_order(
        self,
        position_id: str,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None
    ) -> bool:
        """Updates Stop Loss and/or Take Profit on an open position."""
        pass

    @abstractmethod
    async def close_position(self, position_id: str, reason: str = "MANUAL") -> Optional[TradeRecord]:
        """Liquidates entire open position at current market price."""
        pass

    @abstractmethod
    async def partial_close(
        self,
        position_id: str,
        volume: float,
        reason: str = "PARTIAL_TP"
    ) -> Optional[TradeRecord]:
        """Liquidates a portion of open volume, maintaining the remaining ticket."""
        pass

    @abstractmethod
    async def get_open_positions(self) -> List[Position]:
        """Returns all currently active positions held at the broker."""
        pass
