# Market Analysis Agent

Production-ready, modular trade signal engine with multi-layer confluence scoring, Smart Money Concepts (SMC), risk management, and Telegram alerts. No single indicator drives decisions—signals require alignment across regime, multi-timeframe, structure, and technical confluence.

---

## Features

- **Multi-layer strategy**: Market regime, MTF, SMC, technical confluence
- **Weighted probability scoring**: Bayesian calibration, dynamic regime-based weights
- **Risk management**: Dynamic SL/TP (ATR), min RR 1:2, kill switch, daily limit
- **Signal quality filter**: Probability + confluence thresholds, spread check
- **Telegram alerts**: Formatted signals with **I'm in / Skipped** buttons
- **Emergency exit alerts**: Human-like—tells you to close when thesis invalidates
- **Trade journal**: SQLite + CSV export
- **Backtesting**: Win rate, Sharpe, max drawdown, profit factor

---

## Architecture

```
/core          - Models (OHLCV, Signal, MarketRegime), indicators, exceptions
/strategies    - Regime, MTF, SMC, Technical confluence
/risk          - Risk engine, position sizer
/data          - yfinance client, OHLC fetcher
/services      - Scoring, filter, Telegram, journal, position monitor
/backtest      - Backtest engine, metrics
/config        - Settings (config-driven)
```

---

## Trading Algorithm & Thought Process

### Philosophy

The agent does **not** trade on a single indicator. It requires **confluence**—multiple independent layers agreeing on direction. This mimics institutional flow: regime sets context, higher timeframes set bias, structure (SMC) confirms entry, and technicals add conviction. A signal is only sent when all layers align.

### Signal Generation Pipeline

```
Data (4h, 1h, 15m, 5m) → Regime → MTF → SMC → Technical → Probability → Filter → Risk → Telegram
```

Each step can **reject** the signal. If any layer fails, no signal is sent.

---

### Layer 1: Market Regime

**Purpose**: Determine if the market is tradeable and in what mode.

**Logic** (on 15m candles):
- **ADX** (14): Trend strength. ADX ≥ 25 = trending; ADX < 15–20 = ranging.
- **+DI / -DI**: Direction. +DI > -DI with positive EMA slope = bullish; opposite = bearish.
- **EMA 50 slope**: Confirms trend direction.
- **ATR volatility ratio**: Recent ATR vs older ATR. Ratio < 0.7 = low volatility (avoid).

**Regimes**:
- `TRENDING_UP` / `TRENDING_DOWN`: Trend strategies allowed.
- `RANGING`: Allowed in relaxed mode; otherwise skipped.
- `LOW_VOLATILITY`: No breakout strategies.

**Output**: Regime type. If not trend- or breakout-friendly → **reject**.

---

### Layer 2: Multi-Timeframe (MTF)

**Purpose**: Higher timeframes set bias; lower timeframes confirm entry.

**HTF (4h, 1h)**:
- EMA 20, 50, 200 alignment.
- Price > EMA20 > EMA50 > EMA200 → **BUY** (0.9 confidence).
- Price < EMA20 < EMA50 < EMA200 → **SELL** (0.9 confidence).
- Partial alignment → lower confidence.
- In strict mode: both 4h and 1h must agree. In relaxed: majority wins.

**LTF (15m, 5m)**:
- Price vs EMA 20. For BUY: price > EMA20; for SELL: price < EMA20.
- Average alignment score ≥ 0.5–0.6 (configurable) → LTF aligned.

**Output**: Direction (BUY/SELL) and confidence. If HTF neutral or LTF not aligned → **reject**.

---

### Layer 3: Smart Money Concepts (SMC)

**Purpose**: Confirm structure and institutional-style setups before entry.

**Concepts used**:

| Concept | Description |
|---------|-------------|
| **BOS** (Break of Structure) | Price breaks above recent swing high (bullish) or below swing low (bearish). |
| **CHOCH** (Change of Character) | Structure shifts from bearish to bullish (or vice versa)—e.g. higher lows forming. |
| **Liquidity Sweep** | Price wicks beyond a recent high/low (stops) then reverses. Classic trap. |
| **FVG** (Fair Value Gap) | Gap between candle 1 high and candle 3 low (bullish) or vice versa (bearish). Price often fills these. |
| **Order Block** | Last opposite candle before a strong move. Acts as support/resistance. |

**SMC validation** (strict mode):
- **Liquidity sweep** must be present.
- **BOS or CHOCH** must be present.
- At least **2 confluence factors** (BOS, CHOCH, Liquidity Sweep, FVG, Order Block).

**Relaxed mode**: BOS or CHOCH or Liquidity Sweep + 2 factors.

**Output**: Valid/invalid + list of factors. If invalid (and not ultra-relaxed) → **reject**.

---

### Layer 4: Technical Confluence

**Purpose**: Add conviction from classic indicators.

**Indicators** (weighted, regime-adjusted):
- RSI divergence (oversold/overbought + reversal)
- MACD momentum
- EMA alignment (20/50/200)
- VWAP position
- ATR expansion (volatility breakout)
- Volume spike
- Bollinger squeeze
- SMC confluence (count of SMC factors)

Each contributes 0–1; weighted sum → technical score. Weights can be adjusted by regime based on historical performance.

**Output**: Technical score (0–1) and confluence factor labels.

---

### Layer 5: Probability Scoring

**Formula**:
```
raw_probability = regime_weight×0.2 + mtf_weight×0.25 + smc_weight×0.25 + tech_weight×0.3
```

- Regime: 0.9 if trending, 0.5 if ranging.
- MTF: HTF confidence × LTF alignment.
- SMC: 0.9 if valid, 0.5 otherwise.
- Tech: weighted technical score.

**Bayesian calibration**: Raw score is mapped to a calibrated win probability using historical trade outcomes. Improves accuracy over time.

**Output**: Calibrated probability (0–1).

---

### Layer 6: Signal Filter

**Checks**:
- Probability ≥ MIN_PROBABILITY_SCORE (65% relaxed, 80% strict)
- Confluence score ≥ MIN_CONFLUENCE_SCORE (55% relaxed, 70% strict)
- Risk/reward ≥ MIN_RISK_REWARD (2.0)
- Spread (if available) ≤ MAX_SPREAD_BPS

**Output**: Pass/fail. If fail → **reject**.

---

### Layer 7: Risk Engine

**SL/TP**:
- ATR-based: SL distance = ATR × 2.0, TP = SL × 2 (min 1:2 RR).
- Direction: BUY → SL below entry, TP above; SELL → opposite.

**Rules**:
- Kill switch: Stop after 3 consecutive losses.
- Daily limit: Max 5 trades per day (configurable).

**Output**: Valid/invalid. If invalid → **reject**.

---

### Final Output

If all layers pass: **Signal sent to Telegram** with entry, SL, TP, RR, probability, confluence factors, and **I'm in / Skipped** buttons.

---

## Emergency Exit (Human-like Trading)

After you click **I'm in**, the agent monitors that position. If the thesis invalidates **before** SL or TP, it sends an emergency exit alert.

**Triggers**:
- **Regime flip**: Long but regime turns bearish (or opposite).
- **MTF flip**: Higher timeframe bias flips against your position.
- **Structure break**: Price breaks key support (long) or resistance (short).

Emergency messages include a **🔒 Closed** button to stop monitoring once you exit.

---

## Setup

```bash
cd market-analysis-agent
python -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
# Edit .env with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
```

---

## Usage

| Command | Description |
|---------|--------------|
| `python main.py` | Single analysis cycle |
| `python main.py live` | Continuous (every 5 min) + callback receiver for buttons |
| `python main.py test-signal` | Send a test signal to Telegram |
| `python run_backtest.py` | Backtest on historical data |

---

## Configuration

All parameters in `config/settings.py`:

| Setting | Description |
|---------|-------------|
| `TRADING_SYMBOLS` | Pairs to analyze (e.g. GBPUSD, XAUUSD, BTCUSD) |
| `SYMBOL_SOURCE_MAP` | Display symbol → yfinance ticker |
| `RELAXED_MODE` | Allow ranging, softer MTF/SMC, lower thresholds |
| `ULTRA_RELAXED_MODE` | If True, skip SMC requirement (not recommended) |
| `DIAGNOSTIC_MODE` | Log each step (regime, MTF, SMC, prob, fail reason) |
| `MIN_PROBABILITY_SCORE` | Min probability to pass filter |
| `MIN_CONFLUENCE_SCORE` | Min confluence to pass filter |
| `ADX_TREND_THRESHOLD` | ADX ≥ this = trending |
| `ADX_RANGE_THRESHOLD` | ADX < this = ranging |
| `KILL_SWITCH_LOSSES` | Stop after N consecutive losses |
| `MAX_TRADES_PER_DAY` | Daily trade limit |

---

## Trading Pairs & Data

**Symbols**: GBPUSD, XAUUSD, BTCUSD (configurable)

**Data source**: yfinance only (no API keys):
- BTCUSD → BTC-USD
- XAUUSD → GC=F (gold futures)
- GBPUSD → GBPUSD=X (forex)

---

## Position Tracking (Buttons)

Every signal includes:
- **✅ I'm in** – You took the trade; agent monitors for emergency exit
- **❌ Skipped** – You didn't take it; no monitoring

The bot **replies** when you click any button:
- "✅ Got it! I'll monitor this position for emergency exits."
- "❌ Skipped. I won't monitor this one."
- "🔒 Closed. I'll stop monitoring."

Only positions where you clicked **I'm in** are monitored. Run `python main.py live` so the bot can receive button clicks.

## Daily Summary (11:59pm)

At the end of each day (11:59pm UTC), the bot sends a **self-rating summary**:

> *"If you had taken the trades I sent you today..."*

It lists each signal with simulated outcome (WIN/LOSS/OPEN based on current price vs SL/TP), win rate, total P&L, and a short self-assessment. Configure `DAILY_SUMMARY_HOUR` and `DAILY_SUMMARY_MINUTE` in `config/settings.py`.

---

## Signal Format (Telegram)

Each signal includes **CURRENT** (market price at signal time) and **ENTRY**:

```
PAIR: BTCUSD
TYPE: BUY
CURRENT: 62,450
ENTRY: 62,450
STOP LOSS: 61,980
TAKE PROFIT: 63,900
RISK REWARD: 1:3
PROBABILITY SCORE: 84%
CONFLUENCE: Liquidity Sweep + BOS + FVG + RSI Divergence
TIMEFRAME: 15m
[✅ I'm in] [❌ Skipped]
```

---

## Emergency Exit Format (Telegram)

```
⚠️ EMERGENCY EXIT - CLOSE TRADE NOW

PAIR: BTCUSD
POSITION: LONG
ENTRY: 62,450
CURRENT: 62,100
P&L: -0.56%

REASON: Regime flipped to bearish - thesis invalidated

The setup is no longer valid. Close your position before the original SL/TP.
Original SL: 61,980 | TP: 63,900
[🔒 Closed]
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Chat ID for alerts |

---

## Error Handling

- Retry on transient network errors (3 attempts)
- Duplicate signal prevention (5 min cooldown per pair)
- Graceful degradation when Telegram unavailable

---

## License

MIT
# Market-Analysis-Agent
