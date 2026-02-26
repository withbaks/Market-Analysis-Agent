"""
yfinance data client for forex, commodities, and crypto.
Single data source - no Binance required.
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from core.models import OHLCV
from core.exceptions import DataFetchError

logger = logging.getLogger(__name__)

# Retry config for transient yfinance/Yahoo API failures
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2.0  # seconds

# yfinance interval mapping (Binance-style -> yfinance)
YF_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "1h",  # Fetch 1h, aggregate to 4h
    "1d": "1d",
}


class YFinanceDataClient:
    """
    Fetches OHLCV from yfinance (forex, commodities).
    Runs sync yfinance in executor for async compatibility.
    """

    def __init__(self):
        pass

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[OHLCV]:
        """
        Fetch OHLCV from yfinance.
        symbol: e.g. GBPUSD=X, XAUUSD=X
        interval: 5m, 15m, 1h, 1d
        """
        try:
            import yfinance as yf
        except ImportError:
            raise DataFetchError(
                "yfinance not installed. Run: pip install yfinance"
            ) from None

        yf_interval = YF_INTERVAL_MAP.get(interval, interval)
        if interval == "4h":
            # Fetch 4x limit of 1h bars, then resample
            fetch_limit = min(limit * 4, 1000)
        else:
            fetch_limit = limit

        end = datetime.now(timezone.utc)
        if end_time:
            end = datetime.fromtimestamp(end_time / 1000, tz=timezone.utc)
        start = end - timedelta(days=30)  # yfinance needs days
        if start_time:
            start = datetime.fromtimestamp(start_time / 1000, tz=timezone.utc)

        def _fetch():
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, interval=yf_interval)
            if df is None or df.empty:
                return []
            candles = []
            for ts, row in df.iterrows():
                ts_utc = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                candles.append(
                    OHLCV(
                        timestamp=ts_utc,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row.get("Volume", 0)),
                        symbol=symbol,
                        timeframe=interval,
                    )
                )
            return candles

        loop = asyncio.get_event_loop()
        for attempt in range(MAX_RETRIES):
            try:
                candles = await loop.run_in_executor(None, _fetch)
                break
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_BASE * (2**attempt) + random.uniform(0, 1)
                    logger.warning(
                        "yfinance fetch failed for %s (attempt %d/%d), retrying in %.1fs: %s",
                        symbol,
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                        str(e),
                    )
                    await asyncio.sleep(delay)
                else:
                    raise DataFetchError(f"yfinance error: {e}") from e

        if not candles:
            raise DataFetchError(f"No data from yfinance for {symbol} {interval}")

        if interval == "4h":
            # Resample 1h -> 4h
            candles = self._resample_4h(candles)

        return candles[-limit:] if len(candles) > limit else candles

    async def get_live_price(self, symbol: str) -> Optional[float]:
        """
        Fetch live market price via quote API (regularMarketPrice/currentPrice).
        Uses Yahoo's quote endpoint, not history() which omits incomplete candles.
        """
        try:
            import yfinance as yf
        except ImportError:
            return None

        def _fetch() -> Optional[float]:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            if not info:
                return None
            price = info.get("regularMarketPrice") or info.get("currentPrice")
            if price is not None:
                return float(price)
            return None

        loop = asyncio.get_event_loop()
        for attempt in range(MAX_RETRIES):
            try:
                price = await loop.run_in_executor(None, _fetch)
                if price is not None:
                    return price
            except Exception as e:
                pass
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY_BASE * (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    "get_live_price failed for %s (attempt %d/%d), retrying in %.1fs",
                    symbol,
                    attempt + 1,
                    MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.debug("get_live_price failed for %s after %d attempts", symbol, MAX_RETRIES)
        return None

    def _resample_4h(self, candles: List[OHLCV]) -> List[OHLCV]:
        """Aggregate 1h candles into 4h."""
        if len(candles) < 4:
            return candles
        result = []
        for i in range(0, len(candles), 4):
            chunk = candles[i : i + 4]
            if not chunk:
                break
            result.append(
                OHLCV(
                    timestamp=chunk[-1].timestamp,
                    open=chunk[0].open,
                    high=max(c.high for c in chunk),
                    low=min(c.low for c in chunk),
                    close=chunk[-1].close,
                    volume=sum(c.volume for c in chunk),
                    symbol=chunk[0].symbol,
                    timeframe="4h",
                )
            )
        return result

    async def close(self) -> None:
        pass
