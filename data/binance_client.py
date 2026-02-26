"""
Binance API client for fetching OHLCV data.
Supports REST and WebSocket for real-time streams.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import AsyncGenerator, List, Optional

import aiohttp

from core.models import OHLCV
from core.exceptions import DataFetchError, RateLimitError, WebSocketError
from config.settings import BINANCE_BASE_URL, BINANCE_WS_URL, RATE_LIMIT_DELAY

logger = logging.getLogger(__name__)

FETCH_RETRIES = 3
FETCH_RETRY_DELAY = 2.0


class BinanceDataClient:
    """
    Async Binance data client.
    Fetches historical OHLCV and streams real-time klines.
    """

    def __init__(
        self,
        base_url: str = BINANCE_BASE_URL,
        ws_url: str = BINANCE_WS_URL,
    ):
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[OHLCV]:
        """
        Fetch OHLCV klines from Binance.
        """
        session = await self._get_session()
        url = f"{self.base_url}/api/v3/klines"
        params: dict = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000),
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        last_error = None
        for attempt in range(FETCH_RETRIES):
            try:
                await asyncio.sleep(RATE_LIMIT_DELAY)
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 429:
                        raise RateLimitError("Binance rate limit exceeded")
                    resp.raise_for_status()
                    data = await resp.json()
                    last_error = None
                    break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt < FETCH_RETRIES - 1:
                    logger.warning("Binance fetch attempt %d failed, retrying in %.1fs: %s", attempt + 1, FETCH_RETRY_DELAY, e)
                    await asyncio.sleep(FETCH_RETRY_DELAY)
                else:
                    raise DataFetchError(f"Binance API error: {e}") from e

        candles: List[OHLCV] = []
        for k in data:
            candles.append(
                OHLCV(
                    timestamp=datetime.utcfromtimestamp(k[0] / 1000),
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    symbol=symbol,
                    timeframe=interval,
                )
            )
        logger.debug("Fetched %d klines for %s %s", len(candles), symbol, interval)
        return candles

    async def stream_klines(
        self,
        symbol: str,
        interval: str,
    ) -> AsyncGenerator[OHLCV, None]:
        """
        Stream real-time klines via WebSocket.
        """
        stream = f"{symbol.lower()}@kline_{interval}"
        url = f"{self.ws_url}/{stream}"

        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url) as ws:
                        logger.info("WebSocket connected: %s", stream)
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                k = data.get("k", {})
                                if k.get("x"):  # Candle closed
                                    candle = OHLCV(
                                        timestamp=datetime.utcfromtimestamp(int(k["t"]) / 1000),
                                        open=float(k["o"]),
                                        high=float(k["h"]),
                                        low=float(k["l"]),
                                        close=float(k["c"]),
                                        volume=float(k["v"]),
                                        symbol=symbol,
                                        timeframe=interval,
                                    )
                                    yield candle
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                raise WebSocketError("WebSocket error")
            except Exception as e:
                logger.warning("WebSocket disconnected: %s. Reconnecting in 5s...", e)
                await asyncio.sleep(5)

    async def get_ticker_price(self, symbol: str) -> float:
        """Get current price for symbol."""
        session = await self._get_session()
        url = f"{self.base_url}/api/v3/ticker/price"
        async with session.get(url, params={"symbol": symbol}) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return float(data["price"])

    async def get_spread_bps(self, symbol: str) -> float:
        """Get bid-ask spread in basis points (placeholder - uses 24h high/low proxy)."""
        session = await self._get_session()
        url = f"{self.base_url}/api/v3/ticker/24hr"
        async with session.get(url, params={"symbol": symbol}) as resp:
            resp.raise_for_status()
            data = await resp.json()
        price = float(data["lastPrice"])
        high = float(data["highPrice"])
        low = float(data["lowPrice"])
        range_pct = ((high - low) / price * 10000) if price > 0 else 0
        return min(range_pct * 0.1, 100)  # Proxy: ~1% of range as spread estimate
