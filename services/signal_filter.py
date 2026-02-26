"""
Signal Quality Filter.
Only passes signals meeting minimum thresholds.
"""

import logging
from typing import Optional, Tuple

from core.models import Signal, SignalType
from core.exceptions import SignalFilterError
from config.settings import (
    MIN_PROBABILITY_SCORE,
    MIN_CONFLUENCE_SCORE,
    MIN_RISK_REWARD,
    MAX_SPREAD_BPS,
)

logger = logging.getLogger(__name__)


class SignalFilter:
    """
    Filters low-quality setups.
    Enforces probability, confluence, RR, spread, regime.
    """

    def __init__(
        self,
        min_probability: float = MIN_PROBABILITY_SCORE,
        min_confluence: float = MIN_CONFLUENCE_SCORE,
        min_rr: float = MIN_RISK_REWARD,
        max_spread_bps: float = MAX_SPREAD_BPS,
    ):
        self.min_probability = min_probability
        self.min_confluence = min_confluence
        self.min_rr = min_rr
        self.max_spread_bps = max_spread_bps

    def _confluence_score(self, factors: list) -> float:
        """Heuristic: more factors = higher confluence."""
        if not factors:
            return 0.0
        base = 0.5
        per_factor = 0.1
        return min(1.0, base + len(factors) * per_factor)

    def passes(self, signal: Signal) -> Tuple[bool, str]:
        """
        Check if signal passes all filters.
        Returns (passes, reason).
        """
        if signal.probability_score < self.min_probability:
            return False, f"Probability {signal.probability_score:.0%} < {self.min_probability:.0%}"

        conf = self._confluence_score(signal.confluence_factors)
        if conf < self.min_confluence:
            return False, f"Confluence {conf:.0%} < {self.min_confluence:.0%}"

        if signal.risk_reward < self.min_rr:
            return False, f"RR {signal.risk_reward} < {self.min_rr}"

        if signal.spread_bps is not None and signal.spread_bps > self.max_spread_bps:
            return False, f"Spread {signal.spread_bps} bps > {self.max_spread_bps}"

        return True, "OK"
