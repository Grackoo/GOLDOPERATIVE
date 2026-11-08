"""
AUREUS-SMC Quantitative Position Sizing Engine
Calculates institutional lot sizes mathematically aligned with capital risk rules.
"""

from __future__ import annotations
import math
import logging
from config import settings

logger = logging.getLogger("PositionSizer")


class PositionSizer:
    """
    Mathematical position sizer based on exact XAU/USD CFD contract specifications:
    Contract Size = 100 Troy Ounces per Standard Lot.
    Formula:
        Risk_Amount = Balance * (Risk_Percent / 100.0)
        Per_Lot_Risk = SL_Distance_Dollars * Contract_Size
        Lots = Risk_Amount / Per_Lot_Risk
    """

    def __init__(
        self,
        contract_size: float = settings.CONTRACT_SIZE,
        tick_size: float = settings.TICK_SIZE,
        min_lot: float = settings.MIN_LOT,
        max_lot: float = settings.MAX_LOT,
        lot_step: float = settings.LOT_STEP
    ) -> None:
        self.contract_size = contract_size
        self.tick_size = tick_size
        self.min_lot = min_lot
        self.max_lot = max_lot
        self.lot_step = lot_step

    def calculate_lot_size(
        self,
        balance: float,
        risk_percent: float,
        entry_price: float,
        stop_loss: float
    ) -> float:
        """
        Computes normalized lot volume based on account balance and stop loss distance.
        Clamps between min_lot and max_lot and rounds to nearest lot_step.
        """
        sl_distance_dollars = abs(entry_price - stop_loss)
        if sl_distance_dollars <= 0.0:
            logger.error("SL distance is 0 or negative. Cannot compute lot size.")
            return self.min_lot

        # Monetary risk budget
        risk_capital = balance * (risk_percent / 100.0)

        # Monetary loss per 1.0 standard lot
        # e.g. SL distance of $4.00 * 100 oz = $400 risk per standard lot
        per_lot_risk = sl_distance_dollars * self.contract_size

        raw_lots = risk_capital / per_lot_risk

        # Round down to nearest step
        steps = math.floor(raw_lots / self.lot_step)
        calculated_lots = round(steps * self.lot_step, 2)

        # Clamping
        final_lots = max(self.min_lot, min(self.max_lot, calculated_lots))

        logger.info(
            f"POSITION SIZING: Balance=${balance:,.2f} | Risk={risk_percent}% (${risk_capital:,.2f}) | "
            f"SL Dist=${sl_distance_dollars:.2f} | Computed Lots={final_lots:.2f}"
        )
        return final_lots

    def calculate_pnl(self, side: str, entry: float, current: float, volume: float) -> float:
        """Calculates exact gross floating PnL in USD for given volume."""
        if side.upper() == "BUY":
            price_diff = current - entry
        else:
            price_diff = entry - current
        return round(price_diff * self.contract_size * volume, 2)
