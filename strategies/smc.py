"""
Smart Money Concepts (SMC).
BOS, CHOCH, Liquidity Sweeps, FVG, Order Blocks.
Trades only after liquidity sweep + structure confirmation.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from core.models import OHLCV, SignalType
from config.settings import FVG_MIN_PIPS, OB_LOOKBACK, LIQUIDITY_SWEEP_CONFIRMATION_BARS, RELAXED_MODE

logger = logging.getLogger(__name__)


@dataclass
class StructureLevel:
    """Swing high/low for structure."""

    price: float
    index: int
    is_high: bool


@dataclass
class FVG:
    """Fair Value Gap."""

    top: float
    bottom: float
    index: int
    bullish: bool


@dataclass
class OrderBlock:
    """Order block zone."""

    high: float
    low: float
    index: int
    bullish: bool


class SMCAnalyzer:
    """
    Smart Money Concepts analyzer.
    Detects BOS, CHOCH, liquidity sweeps, FVGs, order blocks.
    """

    def __init__(
        self,
        fvg_min_pips: float = FVG_MIN_PIPS,
        ob_lookback: int = OB_LOOKBACK,
        sweep_confirmation: int = LIQUIDITY_SWEEP_CONFIRMATION_BARS,
    ):
        self.fvg_min_pips = fvg_min_pips
        self.ob_lookback = ob_lookback
        self.sweep_confirmation = sweep_confirmation

    def _get_swing_points(self, candles: List[OHLCV], lookback: int = 5) -> List[StructureLevel]:
        """Identify swing highs and lows."""
        levels: List[StructureLevel] = []
        for i in range(lookback, len(candles) - lookback):
            c = candles[i]
            # Swing high
            if all(candles[j].high <= c.high for j in range(i - lookback, i + lookback + 1) if j != i):
                levels.append(StructureLevel(c.high, i, True))
            # Swing low
            if all(candles[j].low >= c.low for j in range(i - lookback, i + lookback + 1) if j != i):
                levels.append(StructureLevel(c.low, i, False))
        return levels

    def detect_bos_choch(
        self,
        candles: List[OHLCV],
        direction: SignalType,
    ) -> Tuple[bool, bool]:
        """
        Detect Break of Structure (BOS) and Change of Character (CHOCH).
        Returns (bos_detected, choch_detected).
        """
        levels = self._get_swing_points(candles)
        if len(levels) < 4:
            return False, False
        recent = [l for l in levels if l.index >= len(candles) - 30]
        if not recent:
            return False, False
        highs = sorted([l for l in recent if l.is_high], key=lambda x: x.price, reverse=True)
        lows = sorted([l for l in recent if not l.is_high], key=lambda x: x.price)
        current = candles[-1].close
        if direction == SignalType.BUY:
            bos = len(highs) >= 1 and current > highs[0].price
            choch = len(lows) >= 2 and current > lows[-1].price and lows[-1].price > lows[-2].price
        else:
            bos = len(lows) >= 1 and current < lows[0].price
            choch = len(highs) >= 2 and current < highs[-1].price and highs[-1].price < highs[-2].price
        return bos, choch

    def detect_liquidity_sweep(
        self,
        candles: List[OHLCV],
        direction: SignalType,
    ) -> bool:
        """
        Detect liquidity sweep (price wicks beyond recent high/low then reverses).
        """
        if len(candles) < self.sweep_confirmation + 10:
            return False
        recent = candles[-self.sweep_confirmation - 10 : -self.sweep_confirmation]
        if not recent:
            return False
        if direction == SignalType.BUY:
            recent_low = min(c.low for c in recent)
            sweep_candles = candles[-self.sweep_confirmation :]
            for c in sweep_candles:
                if c.low < recent_low and c.close > recent_low and c.is_bullish:
                    return True
        else:
            recent_high = max(c.high for c in recent)
            sweep_candles = candles[-self.sweep_confirmation :]
            for c in sweep_candles:
                if c.high > recent_high and c.close < recent_high and not c.is_bullish:
                    return True
        return False

    def detect_fvg(self, candles: List[OHLCV]) -> List[FVG]:
        """Detect Fair Value Gaps."""
        fvgs: List[FVG] = []
        min_gap = self.fvg_min_pips * 0.0001 if "BTC" in candles[0].symbol or "ETH" in candles[0].symbol else self.fvg_min_pips * 0.00001
        for i in range(2, len(candles)):
            c1, c2, c3 = candles[i - 2], candles[i - 1], candles[i]
            # Bullish FVG: gap between c1 high and c3 low
            if c3.low > c1.high:
                gap = c3.low - c1.high
                if gap >= min_gap * candles[-1].close:
                    fvgs.append(FVG(c3.low, c1.high, i, True))
            # Bearish FVG: gap between c1 low and c3 high
            if c3.high < c1.low:
                gap = c1.low - c3.high
                if gap >= min_gap * candles[-1].close:
                    fvgs.append(FVG(c1.low, c3.high, i, False))
        return fvgs[-10:]  # Last 10 FVGs

    def detect_order_blocks(self, candles: List[OHLCV]) -> List[OrderBlock]:
        """Detect order blocks (last opposite candle before strong move)."""
        obs: List[OrderBlock] = []
        lookback = min(self.ob_lookback, len(candles) - 5)
        for i in range(3, len(candles) - 2):
            if i < lookback:
                continue
            c = candles[i]
            next_c = candles[i + 1]
            body_next = next_c.body
            body_avg = sum(candles[j].body for j in range(max(0, i - 10), i)) / 10 if i >= 10 else body_next
            if body_next > body_avg * 1.5:
                if next_c.is_bullish:
                    obs.append(OrderBlock(c.open, c.low, i, False))
                else:
                    obs.append(OrderBlock(c.high, c.open, i, True))
        return obs[-5:]

    def price_in_fvg(self, price: float, fvgs: List[FVG], bullish: bool) -> bool:
        """Check if price is inside a relevant FVG."""
        for fvg in fvgs:
            if fvg.bullish == bullish and fvg.bottom <= price <= fvg.top:
                return True
        return False

    def analyze(
        self,
        candles: List[OHLCV],
        direction: SignalType,
    ) -> Tuple[bool, List[str]]:
        """
        Full SMC analysis.
        Returns (valid_setup, confluence_factors).
        """
        factors: List[str] = []
        bos, choch = self.detect_bos_choch(candles, direction)
        if bos:
            factors.append("BOS")
        if choch:
            factors.append("CHOCH")
        sweep = self.detect_liquidity_sweep(candles, direction)
        if sweep:
            factors.append("Liquidity Sweep")
        fvgs = self.detect_fvg(candles)
        price = candles[-1].close
        in_fvg = self.price_in_fvg(price, fvgs, direction == SignalType.BUY)
        if in_fvg:
            factors.append("FVG")
        obs = self.detect_order_blocks(candles)
        in_ob = any(
            ob.low <= price <= ob.high and ob.bullish == (direction == SignalType.BUY)
            for ob in obs
        )
        if in_ob:
            factors.append("Order Block")
        if RELAXED_MODE:
            valid = (bos or choch or sweep) and len(factors) >= 2
        else:
            valid = sweep and (bos or choch) and len(factors) >= 2
        return valid, factors
