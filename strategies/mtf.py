"""
Multi-Timeframe Analysis.
HTF bias + LTF entry confirmation.
"""

import logging
from typing import Dict, List, Optional, Tuple

from core.models import OHLCV, SignalType
from core.indicators import ema
from config.settings import HTF_TIMEFRAMES, LTF_TIMEFRAMES, RELAXED_MODE

logger = logging.getLogger(__name__)


class MTFAnalyzer:
    """
    Confirms directional alignment across HTF and LTF.
    HTF (4H/1H) sets bias, LTF (15m/5m) confirms entry.
    """

    def __init__(
        self,
        htf_tfs: List[str] = None,
        ltf_tfs: List[str] = None,
    ):
        self.htf_tfs = htf_tfs or HTF_TIMEFRAMES
        self.ltf_tfs = ltf_tfs or LTF_TIMEFRAMES

    def get_htf_bias(
        self,
        data: Dict[str, List[OHLCV]],
    ) -> Tuple[Optional[SignalType], float]:
        """
        Determine HTF bias from 4H and 1H.
        Returns (SignalType or None if neutral, confidence 0-1).
        """
        biases: List[Tuple[SignalType, float]] = []
        for tf in self.htf_tfs:
            candles = data.get(tf, [])
            if len(candles) < 60:
                continue
            closes = [c.close for c in candles]
            ema_20 = ema(closes, 20)
            ema_50 = ema(closes, 50)
            ema_200 = ema(closes, 200)
            price = closes[-1]
            # Get last valid EMAs
            e20 = next((v for v in reversed(ema_20) if v == v), price)
            e50 = next((v for v in reversed(ema_50) if v == v), price)
            e200 = next((v for v in reversed(ema_200) if v == v), price)
            if price > e20 > e50 > e200:
                biases.append((SignalType.BUY, 0.9))
            elif price < e20 < e50 < e200:
                biases.append((SignalType.SELL, 0.9))
            elif price > e20 and e20 > e50:
                biases.append((SignalType.BUY, 0.6))
            elif price < e20 and e20 < e50:
                biases.append((SignalType.SELL, 0.6))
            else:
                biases.append((SignalType.BUY, 0.5))  # Neutral

        if not biases:
            return None, 0.0
        buys = sum(1 for b, _ in biases if b == SignalType.BUY)
        sells = sum(1 for b, _ in biases if b == SignalType.SELL)
        avg_conf = sum(c for _, c in biases) / len(biases)
        if buys == len(biases):
            return SignalType.BUY, avg_conf
        if sells == len(biases):
            return SignalType.SELL, avg_conf
        if RELAXED_MODE and buys > sells:
            return SignalType.BUY, avg_conf * 0.8
        if RELAXED_MODE and sells > buys:
            return SignalType.SELL, avg_conf * 0.8
        return None, 0.5

    def get_ltf_alignment(
        self,
        data: Dict[str, List[OHLCV]],
        htf_bias: Optional[SignalType],
    ) -> Tuple[bool, float]:
        """
        Check if LTF aligns with HTF bias.
        Returns (aligned, alignment_score).
        """
        if htf_bias is None:
            return False, 0.0
        scores: List[float] = []
        for tf in self.ltf_tfs:
            candles = data.get(tf, [])
            if len(candles) < 30:
                continue
            closes = [c.close for c in candles]
            ema_20 = ema(closes, 20)
            e20 = next((v for v in reversed(ema_20) if v == v), closes[-1])
            price = closes[-1]
            if htf_bias == SignalType.BUY and price > e20:
                scores.append(0.8)
            elif htf_bias == SignalType.SELL and price < e20:
                scores.append(0.8)
            else:
                scores.append(0.3)
        if not scores:
            return False, 0.0
        avg = sum(scores) / len(scores)
        threshold = 0.5 if RELAXED_MODE else 0.6
        return avg >= threshold, avg

    def analyze(
        self,
        data: Dict[str, List[OHLCV]],
    ) -> Tuple[Optional[SignalType], float, bool]:
        """
        Full MTF analysis.
        Returns (bias, confidence, ltf_aligned).
        """
        htf_bias, htf_conf = self.get_htf_bias(data)
        ltf_aligned, ltf_score = self.get_ltf_alignment(data, htf_bias)
        combined_conf = htf_conf * (0.7 + 0.3 * ltf_score) if ltf_aligned else 0.0
        return htf_bias, combined_conf, ltf_aligned
