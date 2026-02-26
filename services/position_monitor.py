"""
Position Monitor - Human-like trading.
Monitors open positions and sends emergency exit alerts when thesis invalidates.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from core.models import OHLCV, SignalType, MarketRegime
from strategies.regime import RegimeDetector
from strategies.mtf import MTFAnalyzer
from config.settings import (
    EMERGENCY_EXIT_COOLDOWN_MINUTES,
    EMERGENCY_EXIT_MAX_AGE_HOURS,
    EMERGENCY_EXIT_REGIME_FLIP,
    EMERGENCY_EXIT_MTF_FLIP,
    EMERGENCY_EXIT_STRUCTURE_BREAK,
)

logger = logging.getLogger(__name__)


class PositionMonitor:
    """
    Monitors open positions and alerts when to close early (emergency exit).
    Mimics human trader behavior: exit when setup invalidates, not just at SL/TP.
    """

    def __init__(
        self,
        regime_detector: Optional[RegimeDetector] = None,
        mtf_analyzer: Optional[MTFAnalyzer] = None,
    ):
        self.regime = regime_detector or RegimeDetector()
        self.mtf = mtf_analyzer or MTFAnalyzer()

    def _check_regime_flip(
        self,
        regime: MarketRegime,
        signal_type: str,
    ) -> Tuple[bool, str]:
        """Check if regime flipped against our position."""
        if not EMERGENCY_EXIT_REGIME_FLIP:
            return False, ""
        if signal_type == "BUY" and regime == MarketRegime.TRENDING_DOWN:
            return True, "Regime flipped to bearish - thesis invalidated"
        if signal_type == "SELL" and regime == MarketRegime.TRENDING_UP:
            return True, "Regime flipped to bullish - thesis invalidated"
        if signal_type == "BUY" and regime == MarketRegime.LOW_VOLATILITY:
            return True, "Market went low volatility - momentum gone"
        if signal_type == "SELL" and regime == MarketRegime.LOW_VOLATILITY:
            return True, "Market went low volatility - momentum gone"
        return False, ""

    def _check_mtf_flip(
        self,
        htf_bias: Optional[SignalType],
        signal_type: str,
    ) -> Tuple[bool, str]:
        """Check if HTF bias flipped against our position."""
        if not EMERGENCY_EXIT_MTF_FLIP or htf_bias is None:
            return False, ""
        if signal_type == "BUY" and htf_bias == SignalType.SELL:
            return True, "Higher timeframe flipped bearish"
        if signal_type == "SELL" and htf_bias == SignalType.BUY:
            return True, "Higher timeframe flipped bullish"
        return False, ""

    def _check_structure_break(
        self,
        candles: List[OHLCV],
        entry: float,
        stop_loss: float,
        signal_type: str,
    ) -> Tuple[bool, str]:
        """
        Check if price broke key structure (e.g. support for long).
        For long: price broke below recent swing low (structure broken).
        For short: price broke above recent swing high.
        """
        if not EMERGENCY_EXIT_STRUCTURE_BREAK or len(candles) < 20:
            return False, ""

        recent = candles[-20:]
        if signal_type == "BUY":
            # Long: structure breaks if we take out a key low
            lows = [c.low for c in recent]
            swing_low = min(lows[:-3])  # Exclude last 3 bars (current formation)
            current_low = min(lows[-3:])
            # If we broke below swing low, structure is broken
            if current_low < swing_low and current_low < entry:
                return True, "Price broke key support - structure invalidated"
        else:
            # Short
            highs = [c.high for c in recent]
            swing_high = max(highs[:-3])
            current_high = max(highs[-3:])
            if current_high > swing_high and current_high > entry:
                return True, "Price broke key resistance - structure invalidated"

        return False, ""

    def should_emergency_exit(
        self,
        data: Dict[str, List[OHLCV]],
        symbol: str,
        signal_type: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        entry_tf: str = "15m",
    ) -> Tuple[bool, str]:
        """
        Check if we should recommend emergency exit for this open position.
        Returns (should_exit, reason).
        """
        ltf = data.get(entry_tf, [])
        if len(ltf) < 50:
            return False, ""

        regime, _ = self.regime.detect(ltf)
        triggered, reason = self._check_regime_flip(regime, signal_type)
        if triggered:
            return True, reason

        htf_bias, _, ltf_aligned = self.mtf.analyze(data)
        triggered, reason = self._check_mtf_flip(htf_bias, signal_type)
        if triggered:
            return True, reason

        triggered, reason = self._check_structure_break(
            ltf, entry, stop_loss, signal_type
        )
        if triggered:
            return True, reason

        return False, ""
