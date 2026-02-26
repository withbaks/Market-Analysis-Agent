"""
OHLC fetcher using yfinance only (no Binance).
Supports forex, gold, and crypto via Yahoo Finance.
"""

import logging
from typing import Dict, List, Optional

from core.models import OHLCV
from data.yfinance_client import YFinanceDataClient
from config.settings import OHLC_LOOKBACK_BARS, SYMBOL_SOURCE_MAP

logger = logging.getLogger(__name__)


class OHLCFetcher:
    """
    Fetches OHLCV from yfinance.
    SYMBOL_SOURCE_MAP maps display symbols (e.g. BTCUSD) to yfinance tickers (e.g. BTC-USD).
    """

    def __init__(self):
        self._yfinance = YFinanceDataClient()
        self._cache: Dict[str, List[OHLCV]] = {}

    def _get_api_symbol(self, symbol: str) -> str:
        """Resolve yfinance ticker for display symbol."""
        return SYMBOL_SOURCE_MAP.get(symbol, symbol)

    async def fetch(
        self,
        symbol: str,
        timeframe: str,
        limit: int = OHLC_LOOKBACK_BARS,
    ) -> List[OHLCV]:
        """
        Fetch OHLCV for symbol and timeframe.
        symbol: display symbol (e.g. GBPUSD, XAUUSD, BTCUSD)
        """
        api_symbol = self._get_api_symbol(symbol)
        cache_key = f"{symbol}_{timeframe}"
        if cache_key in self._cache and len(self._cache[cache_key]) >= limit:
            return self._cache[cache_key][-limit:]

        candles = await self._yfinance.fetch_klines(api_symbol, timeframe, limit=limit)

        # Ensure symbol on candles matches display symbol for downstream
        for c in candles:
            c.symbol = symbol
        self._cache[cache_key] = candles
        return candles

    async def fetch_multi_timeframe(
        self,
        symbol: str,
        timeframes: List[str],
        limit: int = OHLC_LOOKBACK_BARS,
    ) -> Dict[str, List[OHLCV]]:
        """Fetch same symbol across multiple timeframes."""
        result: Dict[str, List[OHLCV]] = {}
        for tf in timeframes:
            result[tf] = await self.fetch(symbol, tf, limit=limit)
        return result

    async def close(self) -> None:
        """Close underlying clients."""
        await self._yfinance.close()
