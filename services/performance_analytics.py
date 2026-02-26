"""
Performance analytics - strategy self-evaluation.
Tracks accuracy per regime, adaptive weighting ideas.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Optional

from core.models import TradeRecord

logger = logging.getLogger(__name__)


class PerformanceAnalytics:
    """
    Tracks strategy performance per market regime.
    Supports adaptive weighting and strategy accuracy review.
    """

    def __init__(self):
        self._trades_by_regime: Dict[str, List[TradeRecord]] = defaultdict(list)
        self._all_trades: List[TradeRecord] = []

    def record(self, trade: TradeRecord) -> None:
        """Record completed trade."""
        self._all_trades.append(trade)
        if trade.regime:
            self._trades_by_regime[trade.regime].append(trade)

    def win_rate_by_regime(self) -> Dict[str, float]:
        """Win rate per regime."""
        result: Dict[str, float] = {}
        for regime, trades in self._trades_by_regime.items():
            if trades:
                wins = sum(1 for t in trades if t.outcome == "WIN")
                result[regime] = wins / len(trades)
        return result

    def accuracy_summary(self) -> dict:
        """Overall and per-regime accuracy."""
        total = len(self._all_trades)
        wins = sum(1 for t in self._all_trades if t.outcome == "WIN")
        return {
            "total_trades": total,
            "win_rate": wins / total if total > 0 else 0,
            "by_regime": self.win_rate_by_regime(),
        }
