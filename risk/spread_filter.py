"""
AUREUS-SMC Institutional Spread & Slippage Filter
Guards against toxic liquidity, high volatility widening, and execution slippage.
"""

from __future__ import annotations
import logging
from config import settings

logger = logging.getLogger("SpreadFilter")


class SpreadFilter:
    """
    Validates execution conditions against microstructure spread widening.
    Rejects or voids orders if spread exceeds maximum acceptable institutional thresholds.
    """

    def __init__(
        self,
        max_allowed_spread: float = settings.MAX_ALLOWED_SPREAD_DOLLARS,
        max_allowed_slippage: float = settings.MAX_ALLOWED_SLIPPAGE_DOLLARS
    ) -> None:
        self.max_allowed_spread = max_allowed_spread
        self.max_allowed_slippage = max_allowed_slippage

    def is_spread_acceptable(self, bid: float, ask: float) -> bool:
        """
        Returns True if current spread is strictly within acceptable limits.
        """
        spread = round(ask - bid, 2)
        if spread > self.max_allowed_spread:
            logger.warning(
                f"SPREAD FILTER REJECTION: Current Spread ${spread:.2f} > Max Allowed ${self.max_allowed_spread:.2f}. "
                f"Entry blocked."
            )
            return False
        return True

    def is_slippage_acceptable(self, requested_price: float, filled_price: float) -> bool:
        """
        Verifies that actual fill price does not exceed maximum allowable slippage.
        """
        slippage = round(abs(filled_price - requested_price), 2)
        if slippage > self.max_allowed_slippage:
            logger.warning(
                f"EXCESSIVE SLIPPAGE: Slippage ${slippage:.2f} exceeded max ${self.max_allowed_slippage:.2f}"
            )
            return False
        return True
