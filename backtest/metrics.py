"""
Backtest performance metrics.
Win rate, RR average, Sharpe, max drawdown, profit factor.
"""

import logging
import math
from typing import List

from core.models import TradeRecord

logger = logging.getLogger(__name__)


class BacktestMetrics:
    """
    Computes standard backtest metrics.
    """

    @staticmethod
    def win_rate(trades: List[TradeRecord]) -> float:
        """Win rate as fraction."""
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.outcome == "WIN")
        return wins / len(trades)

    @staticmethod
    def avg_rr(trades: List[TradeRecord]) -> float:
        """Average risk-reward of trades."""
        if not trades:
            return 0.0
        return sum(t.risk_reward for t in trades) / len(trades)

    @staticmethod
    def sharpe_ratio(
        equity_curve: List[float],
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252 * 24,
    ) -> float:
        """Annualized Sharpe ratio from equity curve."""
        if len(equity_curve) < 2:
            return 0.0
        returns = [
            (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
            for i in range(1, len(equity_curve))
            if equity_curve[i - 1] > 0
        ]
        if not returns:
            return 0.0
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std = math.sqrt(variance) if variance > 0 else 0.0001
        excess = mean_ret - risk_free_rate / periods_per_year
        return (excess / std) * math.sqrt(periods_per_year) if std > 0 else 0.0

    @staticmethod
    def max_drawdown(equity_curve: List[float]) -> float:
        """Max drawdown as fraction (e.g. 0.15 = 15%)."""
        if len(equity_curve) < 2:
            return 0.0
        peak = equity_curve[0]
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd

    @staticmethod
    def profit_factor(trades: List[TradeRecord]) -> float:
        """Gross profit / gross loss."""
        gross_profit = sum(t.pnl or 0 for t in trades if (t.pnl or 0) > 0)
        gross_loss = abs(sum(t.pnl or 0 for t in trades if (t.pnl or 0) < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float("inf")

    @staticmethod
    def summary(
        trades: List[TradeRecord],
        equity_curve: List[float],
    ) -> dict:
        """Full metrics summary."""
        return {
            "total_trades": len(trades),
            "win_rate": BacktestMetrics.win_rate(trades),
            "avg_rr": BacktestMetrics.avg_rr(trades),
            "sharpe_ratio": BacktestMetrics.sharpe_ratio(equity_curve),
            "max_drawdown": BacktestMetrics.max_drawdown(equity_curve),
            "profit_factor": BacktestMetrics.profit_factor(trades),
            "total_pnl": sum(t.pnl or 0 for t in trades),
        }
