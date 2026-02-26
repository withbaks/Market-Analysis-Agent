"""
Technical Confluence Layer.
Weighted scoring: RSI divergence, MACD, EMA, VWAP, ATR, Volume, Bollinger.
"""

import logging
from typing import Dict, List, Optional, Tuple

from core.models import OHLCV, SignalType
from core.indicators import (
    rsi,
    macd,
    ema,
    atr,
    bollinger_bands,
    vwap_from_ohlcv,
)
from config.settings import INDICATOR_WEIGHTS

logger = logging.getLogger(__name__)


class TechnicalConfluence:
    """
    Multi-indicator confluence with weighted probability scoring.
    Each indicator contributes to overall score.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or dict(INDICATOR_WEIGHTS)

    def set_weights(self, weights: Dict[str, float]) -> None:
        """Update weights (e.g. for regime-based dynamic adjustment)."""
        self.weights = dict(weights)

    def _rsi_divergence_score(self, candles: List[OHLCV], direction: SignalType) -> float:
        """RSI divergence detection (simplified: RSI extreme + reversal)."""
        if len(candles) < 30:
            return 0.5
        closes = [c.close for c in candles]
        rsi_vals = rsi(closes, 14)
        recent_rsi = [r for r in rsi_vals[-10:] if r == r]
        if not recent_rsi:
            return 0.5
        last_rsi = recent_rsi[-1]
        if direction == SignalType.BUY:
            if last_rsi < 30:
                return 0.9
            if last_rsi < 40 and closes[-1] > closes[-5]:
                return 0.75
        else:
            if last_rsi > 70:
                return 0.9
            if last_rsi > 60 and closes[-1] < closes[-5]:
                return 0.75
        return 0.5

    def _macd_momentum_score(self, candles: List[OHLCV], direction: SignalType) -> float:
        """MACD momentum shift."""
        if len(candles) < 35:
            return 0.5
        closes = [c.close for c in candles]
        macd_line, signal_line, hist = macd(closes, 12, 26, 9)
        valid_hist = [(i, h) for i, h in enumerate(hist) if h == h]
        if len(valid_hist) < 5:
            return 0.5
        recent = valid_hist[-5:]
        if direction == SignalType.BUY:
            if all(h > 0 for _, h in recent):
                return 0.85
            if recent[-1][1] > recent[-2][1]:
                return 0.7
        else:
            if all(h < 0 for _, h in recent):
                return 0.85
            if recent[-1][1] < recent[-2][1]:
                return 0.7
        return 0.5

    def _ema_alignment_score(self, candles: List[OHLCV], direction: SignalType) -> float:
        """EMA 20/50/200 alignment."""
        if len(candles) < 200:
            return 0.5
        closes = [c.close for c in candles]
        e20 = ema(closes, 20)
        e50 = ema(closes, 50)
        e200 = ema(closes, 200)
        p, a, b, c = closes[-1], e20[-1], e50[-1], e200[-1]
        if any(x != x for x in [a, b, c]):
            return 0.5
        if direction == SignalType.BUY and p > a > b > c:
            return 0.95
        if direction == SignalType.SELL and p < a < b < c:
            return 0.95
        if direction == SignalType.BUY and p > a > b:
            return 0.75
        if direction == SignalType.SELL and p < a < b:
            return 0.75
        return 0.5

    def _vwap_score(self, candles: List[OHLCV], direction: SignalType) -> float:
        """VWAP positioning."""
        if len(candles) < 5:
            return 0.5
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        volumes = [c.volume for c in candles]
        vwap_vals = vwap_from_ohlcv(
            [c.open for c in candles], highs, lows, closes, volumes
        )
        vwap_last = vwap_vals[-1]
        price = closes[-1]
        if direction == SignalType.BUY and price > vwap_last:
            return 0.8
        if direction == SignalType.SELL and price < vwap_last:
            return 0.8
        return 0.5

    def _atr_expansion_score(self, candles: List[OHLCV]) -> float:
        """ATR volatility expansion (breakout confirmation)."""
        if len(candles) < 30:
            return 0.5
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        atr_vals = atr(highs, lows, closes, 14)
        valid = [a for a in atr_vals if a == a]
        if len(valid) < 15:
            return 0.5
        recent = valid[-5:]
        older = valid[-15:-5]
        if not older:
            return 0.5
        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)
        if recent_avg > older_avg * 1.1:
            return 0.85
        return 0.5

    def _volume_spike_score(self, candles: List[OHLCV]) -> float:
        """Volume spike detection."""
        if len(candles) < 20:
            return 0.5
        volumes = [c.volume for c in candles]
        recent_vol = volumes[-1]
        avg_vol = sum(volumes[-20:-1]) / 19 if len(volumes) >= 20 else recent_vol
        if avg_vol <= 0:
            return 0.5
        ratio = recent_vol / avg_vol
        if ratio > 2.0:
            return 0.9
        if ratio > 1.5:
            return 0.75
        return 0.5

    def _bollinger_squeeze_score(self, candles: List[OHLCV], direction: SignalType) -> float:
        """Bollinger squeeze breakout."""
        if len(candles) < 25:
            return 0.5
        closes = [c.close for c in candles]
        upper, mid, lower = bollinger_bands(closes, 20, 2.0)
        price = closes[-1]
        u, m, l = upper[-1], mid[-1], lower[-1]
        if any(x != x for x in [u, m, l]):
            return 0.5
        band_width = (u - l) / m if m > 0 else 0
        prev_bw = (upper[-5] - lower[-5]) / mid[-5] if len(mid) >= 5 and mid[-5] > 0 else band_width
        squeeze = band_width < prev_bw * 0.9
        if not squeeze:
            return 0.5
        if direction == SignalType.BUY and price > m:
            return 0.8
        if direction == SignalType.SELL and price < m:
            return 0.8
        return 0.5

    def score(
        self,
        candles: List[OHLCV],
        direction: SignalType,
        smc_factors: List[str],
    ) -> Tuple[float, List[str]]:
        """
        Compute weighted probability score and confluence factors.
        """
        scores: Dict[str, float] = {}
        factors: List[str] = []

        scores["rsi_divergence"] = self._rsi_divergence_score(candles, direction)
        if scores["rsi_divergence"] >= 0.7:
            factors.append("RSI Divergence")

        scores["macd_momentum"] = self._macd_momentum_score(candles, direction)
        if scores["macd_momentum"] >= 0.7:
            factors.append("MACD Momentum")

        scores["ema_alignment"] = self._ema_alignment_score(candles, direction)
        if scores["ema_alignment"] >= 0.7:
            factors.append("EMA Alignment")

        scores["vwap_position"] = self._vwap_score(candles, direction)
        if scores["vwap_position"] >= 0.7:
            factors.append("VWAP")

        scores["atr_expansion"] = self._atr_expansion_score(candles)
        if scores["atr_expansion"] >= 0.7:
            factors.append("ATR Expansion")

        scores["volume_spike"] = self._volume_spike_score(candles)
        if scores["volume_spike"] >= 0.7:
            factors.append("Volume Spike")

        scores["bollinger_squeeze"] = self._bollinger_squeeze_score(candles, direction)
        if scores["bollinger_squeeze"] >= 0.7:
            factors.append("Bollinger Squeeze")

        scores["smc_confluence"] = min(1.0, 0.5 + len(smc_factors) * 0.15)
        if smc_factors:
            factors.extend(smc_factors)

        weighted = sum(
            scores.get(k, 0.5) * self.weights.get(k, 0.1)
            for k in self.weights
        )
        total_weight = sum(self.weights.values())
        if total_weight > 0:
            weighted /= total_weight
        return min(1.0, weighted), list(dict.fromkeys(factors))
