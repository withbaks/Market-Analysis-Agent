"""
Telegram callback receiver - processes button clicks (I'm in, Skipped, Closed).
Runs as background task during live mode.
Sends a reply message after each button click.
"""

import asyncio
import logging
from typing import Callable, Optional

import aiohttp

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CALLBACK_POLL_INTERVAL

logger = logging.getLogger(__name__)


class TelegramCallbackReceiver:
    """
    Polls Telegram for updates and processes callback_query from inline buttons.
    Calls handler(signal_id, action) -> Optional[str]; if handler returns a string,
    sends it as a reply message via reply_sender.
    """

    def __init__(
        self,
        handler: Callable[[str, str], Optional[str]],
        reply_sender: Optional[Callable[[str], object]] = None,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self._enabled = bool(self.bot_token and self.chat_id)
        self._handler = handler
        self._reply_sender = reply_sender
        self._offset = 0
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def is_enabled(self) -> bool:
        return self._enabled

    async def _poll_once(self) -> None:
        """Fetch updates and process callback_queries."""
        if not self._enabled:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        params = {"offset": self._offset, "timeout": 30}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=35)) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json()
        except Exception as e:
            logger.debug("Telegram poll error: %s", e)
            return

        if not data.get("ok"):
            return

        for upd in data.get("result", []):
            self._offset = upd["update_id"] + 1
            cb = upd.get("callback_query")
            if not cb:
                continue

            callback_id = cb.get("id")
            data_str = cb.get("data", "")
            msg = cb.get("message") or {}
            from_chat = msg.get("chat", {}).get("id")

            # Only process from our configured chat (ignore other groups/users)
            if from_chat is None or str(from_chat) != str(self.chat_id):
                continue

            if ":" not in data_str:
                await self._answer_callback(callback_id)
                continue

            action, signal_id = data_str.split(":", 1)
            if action not in ("in", "skip", "closed"):
                await self._answer_callback(callback_id)
                continue

            try:
                reply_msg = self._handler(signal_id, action)
                if reply_msg and self._reply_sender:
                    try:
                        coro = self._reply_sender(reply_msg)
                        if asyncio.iscoroutine(coro):
                            await coro
                    except Exception as e:
                        logger.debug("Reply send failed: %s", e)
            except Exception as e:
                logger.exception("Callback handler error: %s", e)

            await self._answer_callback(callback_id)

    async def _answer_callback(self, callback_id: str) -> None:
        """Answer callback to remove loading state."""
        url = f"https://api.telegram.org/bot{self.bot_token}/answerCallbackQuery"
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, json={"callback_query_id": callback_id})
        except Exception:
            pass

    async def _poll_loop(self) -> None:
        """Background poll loop."""
        while self._running:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Poll loop error: %s", e)
            await asyncio.sleep(CALLBACK_POLL_INTERVAL)

    def start(self) -> None:
        """Start background polling."""
        if not self._enabled:
            logger.warning("Telegram not configured - callback receiver disabled")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Telegram callback receiver started")

    def stop(self) -> None:
        """Stop background polling."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Telegram callback receiver stopped")
