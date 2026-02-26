"""
Telegram notification service.
Sends trade alerts with inline buttons for position tracking.
"""

import asyncio
import logging
import time
from typing import Optional

import aiohttp

from core.models import Signal
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def _signal_id(signal: Signal) -> str:
    """Compute signal_id (must match trade_journal format)."""
    return f"{signal.symbol}_{signal.signal_type.value}_{signal.timestamp.strftime('%Y%m%d%H%M%S')}"


class TelegramService:
    """
    Sends formatted trade signals to Telegram with inline buttons.
    Buttons: "I'm in" (user in trade) | "Skipped" (not monitoring).
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self._enabled = bool(self.bot_token and self.chat_id)
        self._last_signal_key: Optional[str] = None
        self._last_signal_time: Optional[float] = None
        self._cooldown_seconds = 300  # 5 min between same-pair signals

    def is_enabled(self) -> bool:
        return self._enabled

    def _signal_key(self, signal: Signal) -> str:
        return f"{signal.symbol}_{signal.signal_type.value}_{signal.timeframe}"

    def _is_duplicate(self, signal: Signal) -> bool:
        key = self._signal_key(signal)
        now = time.time()
        if self._last_signal_key == key and self._last_signal_time:
            if now - self._last_signal_time < self._cooldown_seconds:
                return True
        return False

    def _inline_keyboard(self, signal_id: str) -> dict:
        """Inline keyboard: I'm in | Skipped. callback_data max 64 bytes."""
        return {
            "inline_keyboard": [
                [
                    {"text": "✅ I'm in", "callback_data": f"in:{signal_id}"},
                    {"text": "❌ Skipped", "callback_data": f"skip:{signal_id}"},
                ],
            ],
        }

    async def send_signal(self, signal: Signal, signal_id: str) -> bool:
        """
        Send signal to Telegram with buttons.
        signal_id: from journal.log_signal (for callback_data).
        """
        if not self._enabled:
            logger.warning("Telegram not configured - skipping send")
            return False
        if self._is_duplicate(signal):
            logger.info("Skipping duplicate signal: %s", self._signal_key(signal))
            return False

        message = signal.to_telegram_message()
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": self._inline_keyboard(signal_id),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        self._last_signal_key = self._signal_key(signal)
                        self._last_signal_time = time.time()
                        logger.info("Telegram signal sent: %s %s (id=%s)", signal.symbol, signal.signal_type.value, signal_id)
                        return True
                    else:
                        text = await resp.text()
                        logger.error("Telegram API error %s: %s", resp.status, text)
                        return False
        except Exception as e:
            logger.exception("Telegram send failed: %s", e)
            return False

    async def send_emergency_exit(
        self,
        signal_id: str,
        symbol: str,
        signal_type: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        reason: str,
        current_price: float,
    ) -> bool:
        """
        Send emergency exit alert - tells user to close trade NOW before SL/TP.
        Human-like: actionable, urgent, with clear reason.
        """
        if not self._enabled:
            logger.warning("Telegram not configured - skipping emergency exit alert")
            return False

        direction = "LONG" if signal_type == "BUY" else "SHORT"
        pnl_pct = ((current_price - entry) / entry * 100) if signal_type == "BUY" else ((entry - current_price) / entry * 100)

        message = (
            f"⚠️ <b>EMERGENCY EXIT - CLOSE TRADE NOW</b>\n\n"
            f"PAIR: {symbol}\n"
            f"POSITION: {direction}\n"
            f"ENTRY: {entry:,.2f}\n"
            f"CURRENT: {current_price:,.2f}\n"
            f"P&L: {pnl_pct:+.2f}%\n\n"
            f"<b>REASON:</b> {reason}\n\n"
            f"The setup is no longer valid. Close your position before the original SL/TP.\n"
            f"Original SL: {stop_loss:,.2f} | TP: {take_profit:,.2f}"
        )

        # Button: Closed - user confirms they closed, stop monitoring
        reply_markup = {
            "inline_keyboard": [[{"text": "🔒 Closed", "callback_data": f"closed:{signal_id}"}]],
        }

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": reply_markup,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info("Emergency exit alert sent: %s %s - %s", symbol, signal_type, reason)
                        return True
                    else:
                        text = await resp.text()
                        logger.error("Telegram API error %s: %s", resp.status, text)
                        return False
        except Exception as e:
            logger.exception("Telegram emergency exit send failed: %s", e)
            return False
