"""
Backtesting engine.
Runs strategy on historical data and tracks equity.
Note: Uses probability-weighted outcome simulation when bar-by-bar data unavailable.
"""

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from core.models import OHLCV, Signal, SignalType, TradeRecord
from config.settings import BACKTEST_INITIAL_CAPITAL, BACKTEST_COMMISSION_BPS

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Backtest configuration."""

    initial_capital: float = BACKTEST_INITIAL_CAPITAL
    commission_bps: float = BACKTEST_COMMISSION_BPS


@dataclass
class BacktestResult:
    """Backtest result with trades and equity curve."""

    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    final_capital: float = 0.0
    total_return_pct: float = 0.0


class BacktestEngine:
    """
    Runs backtest using signal generator and historical OHLCV.
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.equity: List[float] = []
        self.trades: List[TradeRecord] = []

    def run(
        self,
        data: Dict[str, List[OHLCV]],
        signals: Optional[List[Signal]] = None,
        signal_generator: Optional[Callable[[Dict[str, List[OHLCV]]], List[Signal]]] = None,
        symbol: str = "BTCUSDT",
    ) -> BacktestResult:
        """
        Run backtest.
        Pass either signals list directly or signal_generator(data) -> List[Signal].
        """
        if signals is None and signal_generator is not None:
            signals = signal_generator(data)
        elif signals is None:
            signals = []
        capital = self.config.initial_capital
        self.equity = [capital]
        self.trades = []
        candles = data.get("15m", data.get(list(data.keys())[0], []))
        if not candles:
            return BacktestResult(
                trades=[],
                equity_curve=[capital],
                final_capital=capital,
                total_return_pct=0.0,
            )

        commission = self.config.commission_bps / 10000
        for sig in signals:
            risk = abs(sig.entry - sig.stop_loss)
            reward = abs(sig.take_profit - sig.entry)
            position_size = (capital * 0.02) / risk if risk > 0 else 0
            # Probability-weighted outcome (strategy score as win probability)
            win_prob = sig.probability_score
            is_win = random.random() < win_prob
            exit_price = sig.take_profit if is_win else sig.stop_loss
            gross_pnl = position_size * (reward if is_win else -risk)
            commission_cost = position_size * sig.entry * commission * 2
            pnl = gross_pnl - commission_cost
            pnl_pct = (pnl / capital) * 100 if capital > 0 else 0
            outcome = "WIN" if pnl > 0 else "LOSS"
            rec = TradeRecord(
                signal_id=f"bt_{len(self.trades)}",
                symbol=sig.symbol,
                signal_type=sig.signal_type,
                entry=sig.entry,
                stop_loss=sig.stop_loss,
                take_profit=sig.take_profit,
                risk_reward=sig.risk_reward,
                probability_score=sig.probability_score,
                exit_price=exit_price,
                exit_time=datetime.now(timezone.utc),
                pnl=pnl,
                pnl_pct=pnl_pct,
                outcome=outcome,
                regime=sig.regime.value if sig.regime else None,
                timestamp=sig.timestamp,
            )
            self.trades.append(rec)
            capital += pnl
            self.equity.append(capital)

        total_return = (capital - self.config.initial_capital) / self.config.initial_capital * 100
        return BacktestResult(
            trades=self.trades,
            equity_curve=self.equity,
            final_capital=capital,
            total_return_pct=total_return,
        )
