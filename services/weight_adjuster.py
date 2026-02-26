"""
Dynamic regime-based weight adjustment.
Adjusts indicator weights based on rolling performance per (regime, factor).
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.settings import STORE_DIR, INDICATOR_WEIGHTS

logger = logging.getLogger(__name__)

# Map confluence factor names (from signals) to weight keys
FACTOR_TO_WEIGHT_KEY: Dict[str, str] = {
    "RSI Divergence": "rsi_divergence",
    "MACD Momentum": "macd_momentum",
    "EMA Alignment": "ema_alignment",
    "VWAP": "vwap_position",
    "ATR Expansion": "atr_expansion",
    "Volume Spike": "volume_spike",
    "Bollinger Squeeze": "bollinger_squeeze",
    "BOS": "smc_confluence",
    "CHOCH": "smc_confluence",
    "Liquidity Sweep": "smc_confluence",
    "FVG": "smc_confluence",
    "Order Block": "smc_confluence",
}

WEIGHT_STATE_FILE = "weight_adjuster_state.json"
ROLLING_WINDOW = 200  # Max trades to consider for performance
MIN_OBSERVATIONS = 5  # Min (regime, factor) observations before adjusting
BLEND_BASE = 0.6  # 60% base weight, 40% performance-adjusted


class RegimeWeightAdjuster:
    """
    Adjusts indicator weights based on rolling (regime, factor) performance.
    Factors that perform well in a regime get higher weight; poor performers get lower.
    """

    def __init__(
        self,
        base_weights: Optional[Dict[str, float]] = None,
        rolling_window: int = ROLLING_WINDOW,
        min_observations: int = MIN_OBSERVATIONS,
        blend_base: float = BLEND_BASE,
        state_path: Optional[Path] = None,
    ):
        self.base_weights = base_weights or dict(INDICATOR_WEIGHTS)
        self.rolling_window = rolling_window
        self.min_observations = min_observations
        self.blend_base = blend_base
        self.state_path = state_path or (STORE_DIR / WEIGHT_STATE_FILE)
        # (regime, weight_key) -> (wins, losses)
        self._performance: Dict[str, Tuple[int, int]] = {}
        self._load_state()

    def _perf_key(self, regime: str, weight_key: str) -> str:
        return f"{regime or 'UNKNOWN'}|{weight_key}"

    def record_outcome(
        self,
        regime: Optional[str],
        confluence_factors: List[str],
        outcome: str,
    ) -> None:
        """
        Record trade outcome. For each factor present, update (regime, factor) stats.
        """
        regime_str = regime or "UNKNOWN"
        weight_keys = set()
        for f in confluence_factors or []:
            wk = FACTOR_TO_WEIGHT_KEY.get(f, None)
            if wk:
                weight_keys.add(wk)
        if not weight_keys:
            weight_keys.add("smc_confluence")
        is_win = outcome == "WIN"
        for wk in weight_keys:
            key = self._perf_key(regime_str, wk)
            w, l = self._performance.get(key, (0, 0))
            if is_win:
                w += 1
            elif outcome == "LOSS":
                l += 1
            self._performance[key] = (w, l)
        self._prune_and_save()

    def record_from_trades(self, trades: List[dict]) -> None:
        """Bulk record from trade history."""
        for t in trades[: self.rolling_window]:
            regime = t.get("regime")
            factors_str = t.get("confluence_factors", "")
            outcome = t.get("outcome")
            if outcome not in ("WIN", "LOSS"):
                continue
            factors = factors_str.split("|") if isinstance(factors_str, str) else (factors_str or [])
            self.record_outcome(regime, factors, outcome)

    def rebuild_from_trades(self, trades: List[dict]) -> None:
        """Clear state and rebuild from trade history (avoids double-counting on sync)."""
        self._performance.clear()
        self.record_from_trades(trades)

    def get_adjusted_weights(self, regime: Optional[str]) -> Dict[str, float]:
        """
        Get weights adjusted for current regime based on rolling performance.
        Blends base weights with performance factor: weight_i = base_i * (blend_base + (1-blend_base) * perf_factor)
        """
        regime_str = regime or "UNKNOWN"
        adjusted = {}
        for wk, base_w in self.base_weights.items():
            key = self._perf_key(regime_str, wk)
            wins, losses = self._performance.get(key, (0, 0))
            total = wins + losses
            if total >= self.min_observations:
                win_rate = wins / total
                perf_factor = win_rate
                blended = self.blend_base + (1 - self.blend_base) * perf_factor
                adjusted[wk] = base_w * blended
            else:
                adjusted[wk] = base_w
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: v / total for k, v in adjusted.items()}
        return adjusted

    def _prune_and_save(self) -> None:
        """Keep only recent data (approximate) and persist."""
        if len(self._performance) > 500:
            sorted_keys = sorted(self._performance.keys(), key=lambda k: sum(self._performance[k]))
            for k in sorted_keys[:-300]:
                del self._performance[k]
        self._save_state()

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            data = {k: {"wins": v[0], "losses": v[1]} for k, v in self._performance.items()}
            with open(self.state_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save weight adjuster state: %s", e)

    def _load_state(self) -> None:
        try:
            if self.state_path.exists():
                with open(self.state_path) as f:
                    data = json.load(f)
                for k, v in data.items():
                    if isinstance(v, dict):
                        self._performance[k] = (int(v.get("wins", 0)), int(v.get("losses", 0)))
                logger.info("Loaded weight adjuster state: %d regime-factor pairs", len(self._performance))
        except Exception as e:
            logger.warning("Failed to load weight adjuster state: %s", e)

    def get_performance_summary(self, regime: Optional[str] = None) -> Dict[str, dict]:
        """Return performance stats per weight key for inspection."""
        summary = {}
        for k, (wins, losses) in self._performance.items():
            reg, wk = k.split("|", 1) if "|" in k else ("UNKNOWN", k)
            if regime and reg != regime:
                continue
            total = wins + losses
            summary[k] = {"wins": wins, "losses": losses, "win_rate": wins / total if total > 0 else 0}
        return summary
