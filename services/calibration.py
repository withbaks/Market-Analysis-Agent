"""
Bayesian probability calibration.
Maps raw model scores to calibrated win probabilities using Beta posterior.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config.settings import STORE_DIR

logger = logging.getLogger(__name__)

# Probability bins for calibration: (min, max) -> Beta(alpha, beta)
BIN_EDGES = [0.50, 0.60, 0.70, 0.80, 0.90, 1.01]
DEFAULT_PRIOR_ALPHA = 1.0
DEFAULT_PRIOR_BETA = 1.0
CALIBRATION_STATE_FILE = "calibration_state.json"


class BayesianCalibrator:
    """
    Calibrates raw probability scores using Bayesian Beta posterior.
    Tracks wins/losses per probability bin; outputs posterior mean as calibrated prob.
    """

    def __init__(
        self,
        bin_edges: Optional[List[float]] = None,
        prior_alpha: float = DEFAULT_PRIOR_ALPHA,
        prior_beta: float = DEFAULT_PRIOR_BETA,
        state_path: Optional[Path] = None,
    ):
        self.bin_edges = bin_edges or BIN_EDGES
        self.prior_alpha = prior_alpha
        self.prior_beta = prior_beta
        self.state_path = state_path or (STORE_DIR / CALIBRATION_STATE_FILE)
        self._bins: Dict[str, Tuple[float, float]] = {}  # bin_key -> (alpha, beta)
        self._init_bins()
        self._load_state()

    def _bin_key(self, raw_score: float) -> str:
        """Get bin key for raw score."""
        for i in range(len(self.bin_edges) - 1):
            if self.bin_edges[i] <= raw_score < self.bin_edges[i + 1]:
                return f"{self.bin_edges[i]:.2f}_{self.bin_edges[i+1]:.2f}"
        return f"{self.bin_edges[-2]:.2f}_{self.bin_edges[-1]:.2f}"

    def _init_bins(self) -> None:
        """Initialize all bins with prior."""
        for i in range(len(self.bin_edges) - 1):
            key = f"{self.bin_edges[i]:.2f}_{self.bin_edges[i+1]:.2f}"
            self._bins[key] = (self.prior_alpha, self.prior_beta)

    def _beta_mean(self, alpha: float, beta: float) -> float:
        """Posterior mean of Beta(alpha, beta)."""
        if alpha + beta <= 0:
            return 0.5
        return alpha / (alpha + beta)

    def calibrate(self, raw_score: float) -> float:
        """
        Map raw model score to calibrated win probability.
        Uses Beta posterior mean for the bin containing raw_score.
        When bin has no observations (prior only), returns raw_score to avoid over-dampening.
        """
        key = self._bin_key(raw_score)
        alpha, beta = self._bins.get(key, (self.prior_alpha, self.prior_beta))
        observations = alpha + beta - self.prior_alpha - self.prior_beta
        if observations < 1:
            return raw_score  # No evidence yet: trust raw score
        return self._beta_mean(alpha, beta)

    def update(self, raw_score: float, outcome: str) -> None:
        """
        Bayesian update: observe outcome (WIN/LOSS) for a trade with raw_score.
        """
        key = self._bin_key(raw_score)
        alpha, beta = self._bins.get(key, (self.prior_alpha, self.prior_beta))
        if outcome == "WIN":
            alpha += 1.0
        elif outcome == "LOSS":
            beta += 1.0
        else:
            return
        self._bins[key] = (alpha, beta)
        self._save_state()
        logger.debug("Calibration updated: bin=%s outcome=%s -> Beta(%.1f, %.1f)", key, outcome, alpha, beta)

    def update_from_trades(self, trades: List[dict]) -> None:
        """Bulk update from trade records with probability_score, outcome."""
        for t in trades:
            prob = t.get("probability_score")
            outcome = t.get("outcome")
            if prob is not None and outcome in ("WIN", "LOSS"):
                self.update(float(prob), outcome)

    def rebuild_from_trades(self, trades: List[dict]) -> None:
        """Clear state and rebuild from trade history (avoids double-counting on sync)."""
        self._init_bins()
        self.update_from_trades(trades)

    def _save_state(self) -> None:
        """Persist calibration state to JSON."""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_path, "w") as f:
                json.dump(self._bins, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save calibration state: %s", e)

    def _load_state(self) -> None:
        """Load calibration state from JSON."""
        try:
            if self.state_path.exists():
                with open(self.state_path) as f:
                    data = json.load(f)
                for k, v in data.items():
                    if isinstance(v, (list, tuple)) and len(v) >= 2:
                        self._bins[k] = (float(v[0]), float(v[1]))
                    elif isinstance(v, dict):
                        self._bins[k] = (float(v.get("alpha", self.prior_alpha)), float(v.get("beta", self.prior_beta)))
                logger.info("Loaded calibration state: %d bins", len(self._bins))
        except Exception as e:
            logger.warning("Failed to load calibration state: %s", e)

    def get_bin_stats(self) -> Dict[str, dict]:
        """Return stats per bin for inspection."""
        return {
            key: {
                "alpha": a,
                "beta": b,
                "mean": self._beta_mean(a, b),
                "count": int(a + b - self.prior_alpha - self.prior_beta),
            }
            for key, (a, b) in self._bins.items()
        }
