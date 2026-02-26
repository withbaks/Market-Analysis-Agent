"""
Configuration settings for the Market Analysis Agent.
All thresholds and parameters are config-driven for easy calibration.
"""

from pathlib import Path
from typing import Optional
import os

# ─── Paths ───────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"      # DB, CSV (trades.db, trades.csv)
LOGS_DIR = PROJECT_ROOT / "logs"
STORE_DIR = PROJECT_ROOT / "store"     # Calibration, weight state
DB_PATH = DATA_DIR / "trades.db"

# ─── Environment Variables ───────────────────────────────────────────────
BINANCE_API_KEY: Optional[str] = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET: Optional[str] = os.getenv("BINANCE_API_SECRET")
TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")

# ─── Signal Quality Thresholds ───────────────────────────────────────────
RELAXED_MODE = True           # More signals: allow ranging, softer MTF/SMC, lower thresholds
ULTRA_RELAXED_MODE = True    # Require SMC (liquidity sweep, BOS/CHOCH, FVG, order blocks)
DIAGNOSTIC_MODE = True        # Log each step to find where signals are blocked
MIN_PROBABILITY_SCORE = 0.50 if RELAXED_MODE else 0.80  # Relaxed: 50% (calibrator can be conservative)
MIN_CONFLUENCE_SCORE = 0.50 if RELAXED_MODE else 0.70   # Relaxed: 50%
MIN_RISK_REWARD = 2.0         # Minimum 1:2 RR
MAX_SPREAD_BPS = 50           # Max spread in basis points
MAX_TRADES_PER_DAY = 5
KILL_SWITCH_LOSSES = 3        # Stop after X consecutive losses

# ─── Market Regime ───────────────────────────────────────────────────────
ADX_TREND_THRESHOLD = 25      # ADX > 25 = trending
ADX_RANGE_THRESHOLD = 15 if RELAXED_MODE else 20   # Relaxed: ADX < 15 = ranging
VOLATILITY_COMPRESSION_LOOKBACK = 20
MA_SLOPE_LOOKBACK = 10

# ─── Multi-Timeframe ─────────────────────────────────────────────────────
HTF_TIMEFRAMES = ["4h", "1h"]
LTF_TIMEFRAMES = ["15m", "5m"]
MTF_ALIGNMENT_REQUIRED = True

# ─── Technical Indicator Weights (sum to 1.0) ────────────────────────────
INDICATOR_WEIGHTS = {
    "rsi_divergence": 0.15,
    "macd_momentum": 0.15,
    "ema_alignment": 0.15,
    "vwap_position": 0.10,
    "atr_expansion": 0.10,
    "volume_spike": 0.15,
    "bollinger_squeeze": 0.10,
    "smc_confluence": 0.10,
}

# ─── Risk Management ────────────────────────────────────────────────────
ATR_SL_MULTIPLIER = 2.0       # SL = ATR * multiplier
ATR_TP_MULTIPLIER = 4.0      # TP = ATR * multiplier (for 1:2)
MAX_POSITION_PCT = 0.02      # 2% max risk per trade
DEFAULT_RISK_REWARD = 2.0

# ─── Emergency Exit (Human-like Trading) ──────────────────────────────────
EMERGENCY_EXIT_COOLDOWN_MINUTES = 60   # Don't re-alert same position
EMERGENCY_EXIT_MAX_AGE_HOURS = 48      # Only monitor trades from last 48h
EMERGENCY_EXIT_REGIME_FLIP = True      # Exit when regime flips against position
EMERGENCY_EXIT_MTF_FLIP = True         # Exit when HTF bias flips
EMERGENCY_EXIT_STRUCTURE_BREAK = True  # Exit when price breaks key structure

# ─── SMC Parameters ──────────────────────────────────────────────────────
FVG_MIN_PIPS = 5
OB_LOOKBACK = 20
LIQUIDITY_SWEEP_CONFIRMATION_BARS = 3

# ─── Trading Symbols & Data Sources ───────────────────────────────────────
# Symbols to trade (display names)
TRADING_SYMBOLS = ["GBPUSD", "XAUUSD", "BTCUSD"]

# Map display symbol -> yfinance ticker (no Binance - yfinance only)
SYMBOL_SOURCE_MAP = {
    "BTCUSD": "BTC-USD",    # Bitcoin
    "XAUUSD": "GC=F",       # Gold futures (XAUUSD=X deprecated on Yahoo)
    "GBPUSD": "GBPUSD=X",   # Forex
}

# ─── Position Tracking (Button-based) ─────────────────────────────────────
# Only monitor trades where user clicked "I'm in"
USER_CONFIRMED_MAX_AGE_HOURS = 168  # 7 days - user-confirmed positions
CALLBACK_POLL_INTERVAL = 2.0        # Seconds between Telegram update polls

# ─── Data & API ──────────────────────────────────────────────────────────
BINANCE_BASE_URL = "https://api.binance.com"
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"
RATE_LIMIT_DELAY = 0.1       # Seconds between API calls
OHLC_LOOKBACK_BARS = 500

# ─── Bayesian Calibration ────────────────────────────────────────────────
USE_CALIBRATION = True
CALIBRATION_BIN_EDGES = [0.50, 0.60, 0.70, 0.80, 0.90, 1.01]
CALIBRATION_PRIOR_ALPHA = 1.0
CALIBRATION_PRIOR_BETA = 1.0

# ─── Dynamic Weight Adjustment ───────────────────────────────────────────
USE_DYNAMIC_WEIGHTS = True
WEIGHT_ROLLING_WINDOW = 200
WEIGHT_MIN_OBSERVATIONS = 5
WEIGHT_BLEND_BASE = 0.6  # 60% base, 40% performance-adjusted

# ─── Backtesting ─────────────────────────────────────────────────────────
BACKTEST_INITIAL_CAPITAL = 100_000
BACKTEST_COMMISSION_BPS = 10  # 0.1%

# ─── Logging ─────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
