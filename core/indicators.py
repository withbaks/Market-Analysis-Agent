"""
Technical indicator calculations.
Pure functions - no side effects, fully typed.
"""

from typing import List, Tuple
import math


def ema(values: List[float], period: int) -> List[float]:
    """Exponential Moving Average."""
    if not values or period < 1 or len(values) < period:
        return []
    result: List[float] = []
    multiplier = 2.0 / (period + 1)
    # First EMA = SMA of first period
    sma = sum(values[:period]) / period
    result.extend([float("nan")] * (period - 1))
    result.append(sma)
    for i in range(period, len(values)):
        ema_val = (values[i] - result[-1]) * multiplier + result[-1]
        result.append(ema_val)
    return result


def sma(values: List[float], period: int) -> List[float]:
    """Simple Moving Average."""
    if not values or period < 1 or len(values) < period:
        return []
    result: List[float] = [float("nan")] * (period - 1)
    for i in range(period - 1, len(values)):
        result.append(sum(values[i - period + 1 : i + 1]) / period)
    return result


def rsi(closes: List[float], period: int = 14) -> List[float]:
    """Relative Strength Index."""
    if not closes or period < 1 or len(closes) < period + 1:
        return []
    result: List[float] = [float("nan")] * period
    for i in range(period, len(closes)):
        gains: List[float] = []
        losses: List[float] = []
        for j in range(i - period + 1, i + 1):
            diff = closes[j] - closes[j - 1]
            if diff > 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            rs = 100.0
        else:
            rs = avg_gain / avg_loss
        rsi_val = 100 - (100 / (1 + rs))
        result.append(rsi_val)
    return result


def macd(
    closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[List[float], List[float], List[float]]:
    """MACD line, signal line, histogram."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line: List[float] = []
    for i in range(len(closes)):
        if math.isnan(ema_fast[i]) or math.isnan(ema_slow[i]):
            macd_line.append(float("nan"))
        else:
            macd_line.append(ema_fast[i] - ema_slow[i])
    signal_line = ema([v for v in macd_line if not math.isnan(v)], signal)
    # Align signal line length
    nan_count = sum(1 for v in macd_line if math.isnan(v))
    signal_line = [float("nan")] * nan_count + signal_line
    histogram = [
        macd_line[i] - signal_line[i]
        if not math.isnan(macd_line[i]) and not math.isnan(signal_line[i])
        else float("nan")
        for i in range(len(closes))
    ]
    return macd_line, signal_line, histogram


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """Average True Range."""
    if not highs or len(highs) < period + 1:
        return []
    tr_list: List[float] = [float("nan")]
    for i in range(1, len(highs)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(hl, hc, lc))
    return ema(tr_list, period)


def adx(
    highs: List[float], lows: List[float], closes: List[float], period: int = 14
) -> Tuple[List[float], List[float], List[float]]:
    """ADX, +DI, -DI."""
    if len(highs) < period + 2:
        return ([], [], [])
    tr_list: List[float] = [0.0]
    plus_dm: List[float] = [0.0]
    minus_dm: List[float] = [0.0]
    for i in range(1, len(highs)):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
            minus_dm.append(0.0)
        elif down_move > up_move and down_move > 0:
            plus_dm.append(0.0)
            minus_dm.append(down_move)
        else:
            plus_dm.append(0.0)
            minus_dm.append(0.0)
    atr_vals = atr(highs, lows, closes, period)
    plus_di: List[float] = []
    minus_di: List[float] = []
    adx_vals: List[float] = []
    for i in range(len(tr_list)):
        if i < period or math.isnan(atr_vals[i]) or atr_vals[i] == 0:
            plus_di.append(float("nan"))
            minus_di.append(float("nan"))
            adx_vals.append(float("nan"))
        else:
            pdi = 100 * sum(plus_dm[i - period + 1 : i + 1]) / (period * atr_vals[i])
            mdi = 100 * sum(minus_dm[i - period + 1 : i + 1]) / (period * atr_vals[i])
            plus_di.append(pdi)
            minus_di.append(mdi)
            if pdi + mdi == 0:
                adx_vals.append(float("nan"))
            else:
                dx = 100 * abs(pdi - mdi) / (pdi + mdi)
                if i >= period * 2:
                    prev_adx = adx_vals[-1] if not math.isnan(adx_vals[-1]) else dx
                    adx_vals.append((prev_adx * (period - 1) + dx) / period)
                else:
                    adx_vals.append(dx)
    return adx_vals, plus_di, minus_di


def bollinger_bands(
    closes: List[float], period: int = 20, std_dev: float = 2.0
) -> Tuple[List[float], List[float], List[float]]:
    """Upper, middle, lower Bollinger Bands."""
    mid = sma(closes, period)
    std_list: List[float] = []
    for i in range(len(closes)):
        if i < period - 1:
            std_list.append(float("nan"))
        else:
            slice_vals = closes[i - period + 1 : i + 1]
            mean = sum(slice_vals) / period
            variance = sum((x - mean) ** 2 for x in slice_vals) / period
            std_list.append(math.sqrt(variance) if variance > 0 else 0)
    upper = [
        mid[i] + std_dev * std_list[i] if not math.isnan(mid[i]) and not math.isnan(std_list[i]) else float("nan")
        for i in range(len(closes))
    ]
    lower = [
        mid[i] - std_dev * std_list[i] if not math.isnan(mid[i]) and not math.isnan(std_list[i]) else float("nan")
        for i in range(len(closes))
    ]
    return upper, mid, lower


def vwap_from_ohlcv(
    opens: List[float], highs: List[float], lows: List[float], closes: List[float], volumes: List[float]
) -> List[float]:
    """VWAP for each bar (typical price * volume cumulative)."""
    if not closes or not volumes:
        return []
    typical = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    cum_tpv = 0.0
    cum_vol = 0.0
    result: List[float] = []
    for i in range(len(closes)):
        tpv = typical[i] * volumes[i]
        cum_tpv += tpv
        cum_vol += volumes[i]
        result.append(cum_tpv / cum_vol if cum_vol > 0 else typical[i])
    return result


def ma_slope(ma_values: List[float], lookback: int) -> float:
    """Slope of MA over lookback (positive = uptrend)."""
    valid = [v for v in ma_values[-lookback:] if not (math.isnan(v) if isinstance(v, float) else False)]
    if len(valid) < 2:
        return 0.0
    return (valid[-1] - valid[0]) / len(valid) if len(valid) > 0 else 0.0
