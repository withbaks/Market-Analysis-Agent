"""
Backtest runner - tests strategy on historical data.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config.settings import TRADING_SYMBOLS
from data.ohlc_fetcher import OHLCFetcher
from services.scoring_engine import ScoringEngine
from services.signal_filter import SignalFilter
from risk.engine import RiskEngine
from core.models import Signal, SignalType
from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import BacktestMetrics


async def generate_signals(data: dict, symbol: str = "BTCUSDT") -> list:
    """Generate signals from historical data using scoring engine."""
    scoring = ScoringEngine()
    filter_svc = SignalFilter()
    risk = RiskEngine()
    signals: list[Signal] = []
    sym_data = {k: v for k, v in data.items() if v}
    if not sym_data:
        return signals
    direction, prob, confluence, regime, valid = scoring.score(
        sym_data, symbol, "15m"
    )
    if not valid or direction is None:
        return signals
    ltf = sym_data.get("15m", [])
    if len(ltf) < 50:
        return signals
    entry = ltf[-1].close
    sl, tp, rr = risk.compute_sl_tp(ltf, entry, direction)
    sig = Signal(
        symbol=symbol,
        signal_type=direction,
        entry=entry,
        stop_loss=sl,
        take_profit=tp,
        risk_reward=rr,
        probability_score=prob,
        confluence_factors=confluence,
        timeframe="15m",
        regime=regime,
    )
    if filter_svc.passes(sig)[0]:
        signals.append(sig)
    return signals


async def main() -> None:
    fetcher = OHLCFetcher()
    symbol = TRADING_SYMBOLS[0] if TRADING_SYMBOLS else "BTCUSD"
    data = await fetcher.fetch_multi_timeframe(symbol, ["4h", "1h", "15m", "5m"])
    await fetcher.close()

    signals = await generate_signals(data, symbol)
    print(f"Generated {len(signals)} signals")

    engine = BacktestEngine(BacktestConfig(initial_capital=100_000))
    result = engine.run(data, signals=signals)

    metrics = BacktestMetrics.summary(result.trades, result.equity_curve)
    print("\n--- Backtest Results ---")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print(f"  Final capital: {result.final_capital:,.2f}")
    print(f"  Total return: {result.total_return_pct:.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
