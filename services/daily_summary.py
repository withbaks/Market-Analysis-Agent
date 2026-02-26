"""
Daily Summary Service.
Sends end-of-day "If you had taken the trades I sent..." self-rating analysis.
"""

import logging
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


async def build_daily_summary(
    journal,
    fetcher,
    date_str: str,
) -> Optional[str]:
    """
    Build daily summary message.
    "If you had taken the trades I sent you today..."
    """
    trades = journal.get_trades_for_date(date_str)
    if not trades:
        return None

    lines: List[str] = []
    wins = 0
    losses = 0
    open_count = 0
    total_pnl_pct = 0.0

    for t in trades:
        symbol = t.get("symbol")
        signal_type = t.get("signal_type", "BUY")
        entry = float(t.get("entry", 0))
        sl = float(t.get("stop_loss", 0))
        tp = float(t.get("take_profit", 0))
        if not symbol or entry <= 0:
            continue

        try:
            data = await fetcher.fetch_multi_timeframe(symbol, ["15m"], limit=5)
            candles = data.get("15m", [])
            current = candles[-1].close if candles else entry
        except Exception:
            current = entry

        if signal_type == "BUY":
            if current >= tp:
                outcome = "WIN"
                pnl_pct = (tp - entry) / entry * 100
                wins += 1
            elif current <= sl:
                outcome = "LOSS"
                pnl_pct = (sl - entry) / entry * 100
                losses += 1
            else:
                outcome = "OPEN"
                pnl_pct = (current - entry) / entry * 100
                open_count += 1
        else:
            if current <= tp:
                outcome = "WIN"
                pnl_pct = (entry - tp) / entry * 100
                wins += 1
            elif current >= sl:
                outcome = "LOSS"
                pnl_pct = (entry - sl) / entry * 100
                losses += 1
            else:
                outcome = "OPEN"
                pnl_pct = (entry - current) / entry * 100
                open_count += 1

        total_pnl_pct += pnl_pct
        emoji = "✅" if outcome == "WIN" else "❌" if outcome == "LOSS" else "⏳"
        lines.append(f"{emoji} {symbol} {signal_type} @ {entry:,.2f} → {outcome} ({pnl_pct:+.2f}%)")

    if not lines:
        return None

    closed = wins + losses
    win_rate = (wins / closed * 100) if closed > 0 else 0

    summary = (
        f"📊 <b>Daily Summary</b> ({date_str})\n\n"
        f"<i>If you had taken the trades I sent you today...</i>\n\n"
        + "\n".join(lines)
        + f"\n\n<b>Result:</b> {wins} win(s), {losses} loss(es), {open_count} still open\n"
        f"<b>Win rate:</b> {win_rate:.0f}% ({wins}/{closed} closed)\n"
        f"<b>Total P&L:</b> {total_pnl_pct:+.2f}%\n\n"
    )

    if win_rate >= 70:
        summary += "🔥 <i>I did well today!</i>"
    elif win_rate >= 50:
        summary += "👍 <i>Not bad. Room to improve.</i>"
    else:
        summary += "😅 <i>Rough day. Tomorrow's another chance.</i>"

    return summary
