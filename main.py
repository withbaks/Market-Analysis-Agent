"""
Market Analysis Agent - Main Orchestrator.
Fetches data, runs strategies, scores, filters, and sends alerts.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config.settings import (
    DATA_DIR,
    LOGS_DIR,
    STORE_DIR,
    LOG_LEVEL,
    LOG_FORMAT,
    TRADING_SYMBOLS,
    EMERGENCY_EXIT_MAX_AGE_HOURS,
    USER_CONFIRMED_MAX_AGE_HOURS,
    DIAGNOSTIC_MODE,
)
from core.models import OHLCV, Signal, SignalType, MarketRegime
from data.ohlc_fetcher import OHLCFetcher
from services.scoring_engine import ScoringEngine
from services.signal_filter import SignalFilter
from services.telegram_service import TelegramService
from services.trade_journal import TradeJournal
from services.position_monitor import PositionMonitor
from services.telegram_callback_receiver import TelegramCallbackReceiver
from risk.engine import RiskEngine
from risk.position_sizer import PositionSizer

# Setup logging
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
STORE_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOGS_DIR / "agent.log"),
    ],
)
logger = logging.getLogger(__name__)


class MarketAnalysisAgent:
    """
    Production-ready trade signal engine.
    Modular, async, config-driven.
    """

    def __init__(
        self,
        symbols: list[str] | None = None,
        entry_timeframe: str = "15m",
    ):
        self.symbols = symbols or list(TRADING_SYMBOLS)
        self.entry_tf = entry_timeframe
        self.fetcher = OHLCFetcher()
        self.journal = TradeJournal()
        self.scoring = ScoringEngine(journal=self.journal, use_calibration=True, use_dynamic_weights=True)
        self.filter = SignalFilter()
        self.telegram = TelegramService()
        self.risk = RiskEngine()
        self.position_monitor = PositionMonitor()
        self._callback_receiver: TelegramCallbackReceiver | None = None

    def record_trade_outcome(
        self,
        signal_id: str,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
        outcome: str,
    ) -> None:
        """Record trade outcome (call when trade closes). Updates journal, calibration, and weights."""
        self.journal.update_outcome(signal_id, exit_price, pnl, pnl_pct, outcome)
        trade = self.journal.get_trade(signal_id)
        if trade:
            prob = trade.get("probability_score")
            regime = trade.get("regime")
            factors_str = trade.get("confluence_factors", "")
            factors = factors_str.split("|") if factors_str else []
            self.scoring.record_outcome(signal_id, float(prob or 0.5), regime, factors, outcome)

    async def process_symbol(self, symbol: str) -> list[Signal]:
        """Process one symbol and return valid signals."""
        timeframes = ["4h", "1h", "15m", "5m"]
        try:
            data = await self.fetcher.fetch_multi_timeframe(symbol, timeframes)
        except Exception as e:
            logger.exception("Data fetch failed for %s: %s", symbol, e)
            return []

        direction, probability, confluence, regime, valid = self.scoring.score(
            data, symbol, self.entry_tf
        )
        if DIAGNOSTIC_MODE:
            diag = self.scoring.score_diagnostics(data, symbol, self.entry_tf)
            fail = diag.get("fail", "none")
            logger.info("%s DIAG: regime=%s htf=%s ltf_ok=%s smc_ok=%s factors=%s prob=%.2f FAIL_AT=%s",
                symbol, diag.get("regime"), diag.get("htf_bias"), diag.get("ltf_aligned"),
                diag.get("smc_valid"), diag.get("smc_factors", [])[:3], diag.get("probability", 0), fail)

        if not valid or direction is None or probability < 0.0:
            logger.info("%s: no setup (regime/MTF/SMC not aligned)", symbol)
            return []

        ltf = data.get(self.entry_tf, [])
        if not ltf:
            return []

        entry = ltf[-1].close
        sl, tp, rr = self.risk.compute_sl_tp(ltf, entry, direction)

        signal = Signal(
            symbol=symbol,
            signal_type=direction,
            entry=entry,
            stop_loss=sl,
            take_profit=tp,
            risk_reward=rr,
            probability_score=probability,
            confluence_factors=confluence,
            timeframe=self.entry_tf,
            regime=regime,
        )

        passes, reason = self.filter.passes(signal)
        if not passes:
            logger.info("%s: filtered out (%s)", symbol, reason)
            return []

        risk_ok, risk_reason = self.risk.validate_signal(signal)
        if not risk_ok:
            logger.info("%s: risk rejected (%s)", symbol, risk_reason)
            return []

        return [signal]

    async def run_cycle(self) -> None:
        """Single analysis cycle."""
        logger.info("Starting analysis cycle")
        all_signals: list[Signal] = []
        for symbol in self.symbols:
            signals = await self.process_symbol(symbol)
            all_signals.extend(signals)

        logger.info("Cycle complete: %d signal(s) from %s", len(all_signals), self.symbols)
        for signal in all_signals:
            signal_id = self.journal.log_signal(signal)
            if self.telegram.is_enabled():
                await self.telegram.send_signal(signal, signal_id)
            logger.info("Signal sent: %s %s @ %s (id=%s)", signal.symbol, signal.signal_type.value, signal.entry, signal_id)

        # Human-like: monitor open positions and alert emergency exits
        await self._check_emergency_exits()

    def _on_button_click(self, signal_id: str, action: str) -> None:
        """
        Handle Telegram button clicks: in, skip, closed.
        Edge cases: duplicate clicks (idempotent), unknown signal_id (no-op), wrong chat (filtered by receiver).
        """
        if action == "in":
            if self.journal.set_user_in_position(signal_id, True):
                logger.info("User confirmed in position: %s", signal_id)
            else:
                logger.debug("Button 'I'm in' for unknown/old signal: %s", signal_id)
        elif action == "skip":
            self.journal.set_user_in_position(signal_id, False)
        elif action == "closed":
            if self.journal.set_user_closed(signal_id):
                logger.info("User closed position: %s", signal_id)

    async def _check_emergency_exits(self) -> None:
        """Check open positions (user clicked 'I'm in') and send emergency exit alerts when thesis invalidates."""
        open_trades = self.journal.get_open_trades(
            max_age_hours=USER_CONFIRMED_MAX_AGE_HOURS,
            exclude_alerted=True,
            user_in_position_only=True,
        )
        if not open_trades:
            return

        timeframes = ["4h", "1h", "15m", "5m"]
        for trade in open_trades:
            symbol = trade.get("symbol")
            signal_id = trade.get("signal_id")
            signal_type = trade.get("signal_type", "BUY")
            entry = float(trade.get("entry", 0))
            sl = float(trade.get("stop_loss", 0))
            tp = float(trade.get("take_profit", 0))
            if not symbol or not signal_id or entry <= 0:
                continue

            try:
                data = await self.fetcher.fetch_multi_timeframe(symbol, timeframes)
            except Exception as e:
                logger.debug("Skip emergency check for %s: %s", symbol, e)
                continue

            ltf = data.get("15m", [])
            current_price = ltf[-1].close if ltf else entry

            should_exit, reason = self.position_monitor.should_emergency_exit(
                data, symbol, signal_type, entry, sl, tp, "15m"
            )
            if should_exit and reason and self.telegram.is_enabled():
                sent = await self.telegram.send_emergency_exit(
                    signal_id, symbol, signal_type, entry, sl, tp, reason, current_price
                )
                if sent:
                    self.journal.mark_emergency_exit_alerted(signal_id)
                    logger.info("Emergency exit alerted: %s - %s", symbol, reason)

    async def run_live(self, interval_seconds: int = 300) -> None:
        """Run continuously with interval. Starts callback receiver for button clicks."""
        logger.info("Starting live mode, interval=%ds", interval_seconds)
        if self.telegram.is_enabled():
            self._callback_receiver = TelegramCallbackReceiver(handler=self._on_button_click)
            self._callback_receiver.start()
        try:
            while True:
                try:
                    await self.run_cycle()
                except Exception as e:
                    logger.exception("Cycle error: %s", e)
                await asyncio.sleep(interval_seconds)
        finally:
            if self._callback_receiver:
                self._callback_receiver.stop()

    async def run_once(self) -> None:
        """Run single cycle. Button clicks are processed when you run live mode (Telegram keeps updates ~24h)."""
        await self.run_cycle()

    async def shutdown(self) -> None:
        """Clean shutdown."""
        await self.fetcher.close()


async def main() -> None:
    """Entry point."""
    agent = MarketAnalysisAgent(symbols=list(TRADING_SYMBOLS))
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "live":
            await agent.run_live(interval_seconds=300)
        elif len(sys.argv) > 1 and sys.argv[1] == "test-signal":
            from core.models import Signal, SignalType
            from datetime import datetime
            test = Signal(
                symbol="BTCUSD",
                signal_type=SignalType.BUY,
                entry=100000.0,
                stop_loss=98000.0,
                take_profit=104000.0,
                risk_reward=2.0,
                probability_score=0.85,
                confluence_factors=["TEST_SIGNAL"],
                timeframe="15m",
                regime=None,
            )
            signal_id = agent.journal.log_signal(test)
            if agent.telegram.is_enabled():
                await agent.telegram.send_signal(test, signal_id)
                logger.info("Test signal sent to Telegram - check your chat")
            else:
                logger.warning("Telegram not configured - set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        else:
            await agent.run_once()
    finally:
        await agent.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
