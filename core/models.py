"""
Core data models for the Market Analysis Agent.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class SignalType(str, Enum):
    """Trade direction."""

    BUY = "BUY"
    SELL = "SELL"


class MarketRegime(str, Enum):
    """Market regime classification."""

    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNKNOWN = "UNKNOWN"


class Timeframe(str, Enum):
    """Supported timeframes."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


@dataclass
class OHLCV:
    """OHLCV candle data."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str = ""
    timeframe: str = ""

    @property
    def body(self) -> float:
        """Candle body size."""
        return abs(self.close - self.open)

    @property
    def is_bullish(self) -> bool:
        """True if close > open."""
        return self.close > self.open

    @property
    def range_size(self) -> float:
        """High-low range."""
        return self.high - self.low


@dataclass
class Signal:
    """Trade signal with full metadata."""

    symbol: str
    signal_type: SignalType
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    probability_score: float
    confluence_factors: List[str]
    timeframe: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    regime: Optional[MarketRegime] = None
    spread_bps: Optional[float] = None

    def to_telegram_message(self, current_price: Optional[float] = None) -> str:
        """Format signal for Telegram. current_price: market price at signal time."""
        confluences = " + ".join(self.confluence_factors) if self.confluence_factors else "N/A"
        rr_str = f"1:{int(self.risk_reward)}"
        price_line = f"CURRENT: {current_price:,.2f}\n" if current_price is not None else ""
        return (
            f"PAIR: {self.symbol}\n"
            f"TYPE: {self.signal_type.value}\n"
            f"{price_line}"
            f"ENTRY: {self.entry:,.2f}\n"
            f"STOP LOSS: {self.stop_loss:,.2f}\n"
            f"TAKE PROFIT: {self.take_profit:,.2f}\n"
            f"RISK REWARD: {rr_str}\n"
            f"PROBABILITY SCORE: {self.probability_score:.0%}\n"
            f"CONFLUENCE: {confluences}\n"
            f"TIMEFRAME: {self.timeframe}"
        )


@dataclass
class TradeRecord:
    """Record of an executed or simulated trade."""

    signal_id: str
    symbol: str
    signal_type: SignalType
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    probability_score: float
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    outcome: Optional[str] = None  # "WIN" | "LOSS" | "BE"
    regime: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
