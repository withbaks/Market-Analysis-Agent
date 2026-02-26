"""
Market Regime Detection.
Identifies trending vs ranging markets using ADX, MA slope, and volatility.
"""

import logging
from typing import List, Tuple

from core.models import MarketRegime, OHLCV
from core.indicators import adx, ema, atr, ma_slope
from config.settings import (
    ADX_TREND_THRESHOLD,
    ADX_RANGE_THRESHOLD,
    VOLATILITY_COMPRESSION_LOOKBACK,
    MA_SLOPE_LOOKBACK,
    RELAXED_MODE,
)

logger = logging.getLogger(__name__)


class RegimeDetector:
    """
    Detects market regime: trending up/down, ranging, or low volatility.
    Disables trend strategies in ranging markets and breakout in low vol.
    """

    def __init__(
        self,
        adx_trend: float = ADX_TREND_THRESHOLD,
        adx_range: float = ADX_RANGE_THRESHOLD,
        vol_lookback: int = VOLATILITY_COMPRESSION_LOOKBACK,
        ma_lookback: int = MA_SLOPE_LOOKBACK,
    ):
        self.adx_trend = adx_trend
        self.adx_range = adx_range
        self.vol_lookback = vol_lookback
        self.ma_lookback = ma_lookback

    def detect(self, candles: List[OHLCV]) -> Tuple[MarketRegime, dict]:
        """
        Detect current market regime.
        Returns (regime, metadata dict with scores).
        """
        if len(candles) < 50:
            return MarketRegime.UNKNOWN, {"reason": "insufficient_data"}

        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]

        adx_vals, plus_di, minus_di = adx(highs, lows, closes, 14)
        atr_vals = atr(highs, lows, closes, 14)
        ema_50 = ema(closes, 50)

        # Get latest valid values
        adx_last = next((v for v in reversed(adx_vals) if v and v == v), 0.0)
        plus_di_last = next((v for v in reversed(plus_di) if v and v == v), 0.0)
        minus_di_last = next((v for v in reversed(minus_di) if v and v == v), 0.0)
        slope = ma_slope(ema_50, self.ma_lookback)

        # Volatility compression: compare recent ATR to older ATR
        valid_atr = [v for v in atr_vals if v and v == v]
        if len(valid_atr) >= self.vol_lookback * 2:
            recent_atr = sum(valid_atr[-self.vol_lookback :]) / self.vol_lookback
            older_atr = sum(valid_atr[-self.vol_lookback * 2 : -self.vol_lookback]) / self.vol_lookback
            vol_ratio = recent_atr / older_atr if older_atr > 0 else 1.0
        else:
            vol_ratio = 1.0

        metadata = {
            "adx": adx_last,
            "plus_di": plus_di_last,
            "minus_di": minus_di_last,
            "ma_slope": slope,
            "vol_ratio": vol_ratio,
        }

        # Low volatility: ATR compressed
        if vol_ratio < 0.7:
            return MarketRegime.LOW_VOLATILITY, metadata

        # Ranging: ADX below threshold
        if adx_last < self.adx_range:
            return MarketRegime.RANGING, metadata

        # Trending
        if adx_last >= self.adx_trend:
            if plus_di_last > minus_di_last and slope > 0:
                return MarketRegime.TRENDING_UP, metadata
            if minus_di_last > plus_di_last and slope < 0:
                return MarketRegime.TRENDING_DOWN, metadata

        # Weak trend
        if slope > 0:
            return MarketRegime.TRENDING_UP, metadata
        if slope < 0:
            return MarketRegime.TRENDING_DOWN, metadata

        return MarketRegime.RANGING, metadata

    def is_trend_friendly(self, regime: MarketRegime) -> bool:
        """True if trend strategies should run."""
        if RELAXED_MODE:
            return regime in (MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN, MarketRegime.RANGING)
        return regime in (MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN)

    def is_breakout_friendly(self, regime: MarketRegime) -> bool:
        """True if breakout strategies should run (need volatility)."""
        return regime != MarketRegime.LOW_VOLATILITY
