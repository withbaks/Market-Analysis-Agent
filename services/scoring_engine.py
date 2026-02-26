"""
Scoring Engine.
Aggregates regime, MTF, SMC, and technical confluence into probability score.
Includes Bayesian calibration and dynamic regime-based weight adjustment.
"""

import logging
from typing import Dict, List, Optional, Tuple

from core.models import OHLCV, MarketRegime, SignalType
from config.settings import ULTRA_RELAXED_MODE
from strategies.regime import RegimeDetector
from strategies.mtf import MTFAnalyzer
from strategies.smc import SMCAnalyzer
from strategies.technical import TechnicalConfluence
from services.calibration import BayesianCalibrator
from services.weight_adjuster import RegimeWeightAdjuster

logger = logging.getLogger(__name__)


class ScoringEngine:
    """
    Multi-factor probability scoring with:
    - Bayesian calibration (maps raw scores to calibrated win probability)
    - Dynamic regime-based weight adjustment (performs better factors get higher weight)
    """

    def __init__(
        self,
        use_calibration: bool = True,
        use_dynamic_weights: bool = True,
        journal: Optional[object] = None,
    ):
        self.regime = RegimeDetector()
        self.mtf = MTFAnalyzer()
        self.smc = SMCAnalyzer()
        self.technical = TechnicalConfluence()
        self.use_calibration = use_calibration
        self.use_dynamic_weights = use_dynamic_weights
        self.journal = journal
        self._calibrator = BayesianCalibrator() if use_calibration else None
        self._weight_adjuster = RegimeWeightAdjuster() if use_dynamic_weights else None
        self._synced = False

    def _sync_from_journal(self) -> None:
        """Rebuild calibration and weight state from journal trades with outcomes."""
        if not self.journal or self._synced:
            return
        try:
            trades = self.journal.get_trades(limit=500, with_outcomes_only=True)
            if trades:
                if self._calibrator:
                    self._calibrator.rebuild_from_trades(trades)
                if self._weight_adjuster:
                    self._weight_adjuster.rebuild_from_trades(trades)
                logger.debug("Synced calibration/weights from %d trades", len(trades))
        except Exception as e:
            logger.warning("Failed to sync from journal: %s", e)
        self._synced = True

    def force_resync(self) -> None:
        """Force re-sync from journal (e.g. after adding historical trades)."""
        self._synced = False
        self._sync_from_journal()

    def record_outcome(
        self,
        signal_id: str,
        raw_probability: float,
        regime: Optional[str],
        confluence_factors: List[str],
        outcome: str,
    ) -> None:
        """
        Record trade outcome for calibration and weight adjustment.
        Call this when a trade is closed (e.g. after journal.update_outcome).
        """
        if self._calibrator and outcome in ("WIN", "LOSS"):
            self._calibrator.update(raw_probability, outcome)
        if self._weight_adjuster and outcome in ("WIN", "LOSS"):
            self._weight_adjuster.record_outcome(regime, confluence_factors, outcome)

    def score(
        self,
        data: Dict[str, List[OHLCV]],
        symbol: str,
        entry_tf: str = "15m",
    ) -> Tuple[
        Optional[SignalType],
        float,
        List[str],
        MarketRegime,
        bool,
    ]:
        """
        Full confluence scoring.
        Returns (direction, probability, confluence_factors, regime, valid).
        Probability is calibrated when use_calibration=True.
        """
        self._sync_from_journal()

        ltf_candles = data.get(entry_tf, [])
        if len(ltf_candles) < 50:
            return None, 0.0, [], MarketRegime.UNKNOWN, False

        regime, regime_meta = self.regime.detect(ltf_candles)
        if not self.regime.is_trend_friendly(regime) and not self.regime.is_breakout_friendly(regime):
            return None, 0.0, [], regime, False

        htf_bias, mtf_conf, ltf_aligned = self.mtf.analyze(data)
        if htf_bias is None or not ltf_aligned:
            return None, 0.0, [], regime, False

        smc_valid, smc_factors = self.smc.analyze(ltf_candles, htf_bias)
        if not smc_valid and not ULTRA_RELAXED_MODE:
            return None, 0.0, [], regime, False
        if ULTRA_RELAXED_MODE and not smc_valid:
            smc_factors = ["MTF_Only"]

        # Apply regime-based dynamic weights
        regime_str = regime.value if regime else None
        if self._weight_adjuster:
            adjusted = self._weight_adjuster.get_adjusted_weights(regime_str)
            self.technical.set_weights(adjusted)

        tech_score, tech_factors = self.technical.score(
            ltf_candles, htf_bias, smc_factors
        )

        confluence = list(dict.fromkeys(smc_factors + tech_factors))
        regime_weight = 0.9 if regime in (MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN) else 0.5
        mtf_weight = mtf_conf
        smc_weight = 0.9 if smc_valid else 0.5
        tech_weight = tech_score
        raw_probability = (regime_weight * 0.2 + mtf_weight * 0.25 + smc_weight * 0.25 + tech_weight * 0.3)
        raw_probability = min(1.0, raw_probability)

        # Bayesian calibration
        if self._calibrator:
            probability = self._calibrator.calibrate(raw_probability)
        else:
            probability = raw_probability

        return htf_bias, probability, confluence, regime, True

    def score_diagnostics(
        self,
        data: Dict[str, List[OHLCV]],
        symbol: str,
        entry_tf: str = "15m",
    ) -> dict:
        """Run scoring steps and return intermediate values for debugging."""
        result = {"regime": None, "htf_bias": None, "ltf_aligned": False, "smc_valid": False, "smc_factors": [], "probability": 0.0}
        ltf_candles = data.get(entry_tf, [])
        if len(ltf_candles) < 50:
            result["fail"] = "insufficient_data"
            return result

        regime, _ = self.regime.detect(ltf_candles)
        result["regime"] = regime.value if regime else None
        if not self.regime.is_trend_friendly(regime) and not self.regime.is_breakout_friendly(regime):
            result["fail"] = "regime"
            return result

        htf_bias, mtf_conf, ltf_aligned = self.mtf.analyze(data)
        result["htf_bias"] = htf_bias.value if htf_bias else None
        result["ltf_aligned"] = ltf_aligned
        if htf_bias is None or not ltf_aligned:
            result["fail"] = "mtf"
            return result

        smc_valid, smc_factors = self.smc.analyze(ltf_candles, htf_bias)
        result["smc_valid"] = smc_valid
        result["smc_factors"] = smc_factors
        if not smc_valid and not ULTRA_RELAXED_MODE:
            result["fail"] = "smc"
            return result
        if not smc_valid and ULTRA_RELAXED_MODE:
            smc_factors = ["MTF_Only"]

        regime_str = regime.value if regime else None
        if self._weight_adjuster:
            self.technical.set_weights(self._weight_adjuster.get_adjusted_weights(regime_str))
        tech_score, tech_factors = self.technical.score(ltf_candles, htf_bias, smc_factors)
        confluence = list(dict.fromkeys(smc_factors + tech_factors))
        regime_weight = 0.9 if regime in (MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN) else 0.5
        raw_prob = (regime_weight * 0.2 + mtf_conf * 0.25 + 0.9 * 0.25 + tech_score * 0.3)
        raw_prob = min(1.0, raw_prob)
        probability = self._calibrator.calibrate(raw_prob) if self._calibrator else raw_prob
        result["probability"] = probability
        result["fail"] = None
        return result
