"""
Position sizing based on risk parameters.
"""

import logging
from typing import Optional

from core.models import Signal, SignalType
from config.settings import MAX_POSITION_PCT

logger = logging.getLogger(__name__)


class PositionSizer:
    """
    Calculates position size from risk % and SL distance.
    """

    def __init__(self, max_risk_pct: float = MAX_POSITION_PCT):
        self.max_risk_pct = max_risk_pct

    def calculate(
        self,
        capital: float,
        entry: float,
        stop_loss: float,
        risk_pct: Optional[float] = None,
    ) -> float:
        """
        Calculate position size in units.
        risk_pct: fraction of capital to risk (e.g. 0.02 = 2%)
        """
        risk_pct = risk_pct or self.max_risk_pct
        risk_amount = capital * risk_pct
        sl_distance = abs(entry - stop_loss)
        if sl_distance <= 0:
            return 0.0
        units = risk_amount / sl_distance
        return units
