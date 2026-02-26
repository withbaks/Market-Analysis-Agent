"""
Risk Management Engine.
Dynamic SL/TP, position sizing, kill switch, max trades.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from core.models import OHLCV, Signal, SignalType, TradeRecord
from core.indicators import atr
from config.settings import (
    ATR_SL_MULTIPLIER,
    ATR_TP_MULTIPLIER,
    MIN_RISK_REWARD,
    MAX_TRADES_PER_DAY,
    KILL_SWITCH_LOSSES,
)

logger = logging.getLogger(__name__)


class RiskEngine:
    """
    Enforces risk rules: min RR, dynamic SL/TP, kill switch, daily limit.
    """

    def __init__(
        self,
        atr_sl_mult: float = ATR_SL_MULTIPLIER,
        atr_tp_mult: float = ATR_TP_MULTIPLIER,
        min_rr: float = MIN_RISK_REWARD,
        max_trades_per_day: int = MAX_TRADES_PER_DAY,
        kill_switch: int = KILL_SWITCH_LOSSES,
    ):
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult
        self.min_rr = min_rr
        self.max_trades_per_day = max_trades_per_day
        self.kill_switch = kill_switch
        self._trades_today: List[datetime] = []
        self._consecutive_losses = 0
        self._last_reset = datetime.utcnow().date()

    def _reset_daily_if_needed(self) -> None:
        today = datetime.utcnow().date()
        if today != self._last_reset:
            self._trades_today = []
            self._last_reset = today

    def compute_sl_tp(
        self,
        candles: List[OHLCV],
        entry: float,
        direction: SignalType,
        atr_period: int = 14,
    ) -> Tuple[float, float, float]:
        """
        Compute SL and TP from ATR. Ensures minimum RR.
        Returns (stop_loss, take_profit, risk_reward).
        """
        if len(candles) < atr_period + 1:
            return entry * 0.99, entry * 1.02, 2.0
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        atr_vals = atr(highs, lows, closes, atr_period)
        atr_last = next((v for v in reversed(atr_vals) if v == v), entry * 0.01)
        sl_distance = atr_last * self.atr_sl_mult
        tp_distance = sl_distance * self.min_rr
        if direction == SignalType.BUY:
            sl = entry - sl_distance
            tp = entry + tp_distance
        else:
            sl = entry + sl_distance
            tp = entry - tp_distance
        rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else self.min_rr
        if rr < self.min_rr:
            tp_distance = sl_distance * self.min_rr
            if direction == SignalType.BUY:
                tp = entry + tp_distance
            else:
                tp = entry - tp_distance
            rr = self.min_rr
        return sl, tp, rr

    def can_trade(self) -> Tuple[bool, str]:
        """
        Check if trading is allowed (kill switch, daily limit).
        Returns (allowed, reason).
        """
        self._reset_daily_if_needed()
        if self._consecutive_losses >= self.kill_switch:
            return False, f"Kill switch: {self._consecutive_losses} consecutive losses"
        if len(self._trades_today) >= self.max_trades_per_day:
            return False, f"Max trades per day ({self.max_trades_per_day}) reached"
        return True, "OK"

    def record_trade(self, outcome: str) -> None:
        """Record trade outcome for kill switch."""
        self._trades_today.append(datetime.utcnow())
        if outcome == "LOSS":
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    def validate_signal(self, signal: Signal) -> Tuple[bool, str]:
        """
        Validate signal against risk rules.
        Returns (valid, reason).
        """
        if signal.risk_reward < self.min_rr:
            return False, f"RR {signal.risk_reward} below minimum {self.min_rr}"
        allowed, reason = self.can_trade()
        if not allowed:
            return False, reason
        return True, "OK"
