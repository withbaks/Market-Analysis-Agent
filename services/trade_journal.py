"""
Trade journal - logs trades to SQLite and CSV.
"""

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.models import Signal, SignalType, TradeRecord
from config.settings import DATA_DIR, DB_PATH

logger = logging.getLogger(__name__)


class TradeJournal:
    """
    Persists trade records to SQLite and CSV.
    """

    def __init__(self, db_path: Optional[Path] = None, csv_dir: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.csv_dir = csv_dir or DATA_DIR
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create SQLite schema."""
        import sqlite3
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT,
                symbol TEXT,
                signal_type TEXT,
                entry REAL,
                stop_loss REAL,
                take_profit REAL,
                risk_reward REAL,
                probability_score REAL,
                exit_price REAL,
                exit_time TEXT,
                pnl REAL,
                pnl_pct REAL,
                outcome TEXT,
                regime TEXT,
                confluence_factors TEXT,
                timestamp TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN confluence_factors TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN emergency_exit_alerted_at TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN user_in_position INTEGER DEFAULT 0")
        except Exception:
            pass
        conn.commit()
        conn.close()

    def log_signal(self, signal: Signal) -> str:
        """Log signal, return signal_id. Uses seconds for uniqueness (collision-safe)."""
        import sqlite3
        signal_id = f"{signal.symbol}_{signal.signal_type.value}_{signal.timestamp.strftime('%Y%m%d%H%M%S')}"
        confluence_str = "|".join(signal.confluence_factors) if signal.confluence_factors else ""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """
            INSERT INTO trades (signal_id, symbol, signal_type, entry, stop_loss, take_profit,
                risk_reward, probability_score, regime, confluence_factors, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_id,
                signal.symbol,
                signal.signal_type.value,
                signal.entry,
                signal.stop_loss,
                signal.take_profit,
                signal.risk_reward,
                signal.probability_score,
                signal.regime.value if signal.regime else None,
                confluence_str,
                signal.timestamp.isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        self._append_csv(signal, signal_id)
        logger.info("Logged signal %s", signal_id)
        return signal_id

    def update_outcome(
        self,
        signal_id: str,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
        outcome: str,
    ) -> None:
        """Update trade with outcome."""
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """
            UPDATE trades SET exit_price=?, exit_time=?, pnl=?, pnl_pct=?, outcome=?
            WHERE signal_id=?
            """,
            (exit_price, datetime.utcnow().isoformat(), pnl, pnl_pct, outcome, signal_id),
        )
        conn.commit()
        conn.close()

    def _append_csv(self, signal: Signal, signal_id: str) -> None:
        """Append to CSV export."""
        csv_path = self.csv_dir / "trades.csv"
        file_exists = csv_path.exists()
        with open(csv_path, "a", newline="") as f:
            w = csv.writer(f)
            if not file_exists:
                w.writerow([
                    "signal_id", "symbol", "type", "entry", "sl", "tp", "rr",
                    "prob", "regime", "timestamp"
                ])
            w.writerow([
                signal_id, signal.symbol, signal.signal_type.value,
                signal.entry, signal.stop_loss, signal.take_profit,
                signal.risk_reward, signal.probability_score,
                signal.regime.value if signal.regime else "",
                signal.timestamp.isoformat(),
            ])

    def get_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 100,
        with_outcomes_only: bool = False,
    ) -> List[dict]:
        """Fetch trades from DB."""
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conditions = []
        params: list = []
        if with_outcomes_only:
            conditions.append("outcome IS NOT NULL")
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        params.append(limit)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        cur = conn.execute(
            f"SELECT * FROM trades{where} ORDER BY timestamp DESC LIMIT ?",
            params,
        )
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_trade(self, signal_id: str) -> Optional[dict]:
        """Fetch single trade by signal_id."""
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM trades WHERE signal_id = ?", (signal_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_open_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        max_age_hours: Optional[float] = None,
        exclude_alerted: bool = True,
        user_in_position_only: bool = True,
    ) -> List[dict]:
        """
        Fetch open trades (no outcome yet) for position monitoring.
        user_in_position_only: if True, only return trades where user clicked "I'm in".
        """
        import sqlite3
        from datetime import datetime, timedelta
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conditions = ["outcome IS NULL"]
        params: list = []
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if max_age_hours is not None:
            cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
            conditions.append("timestamp >= ?")
            params.append(cutoff)
        if exclude_alerted:
            conditions.append("(emergency_exit_alerted_at IS NULL OR emergency_exit_alerted_at = '')")
        if user_in_position_only:
            conditions.append("user_in_position = 1")
        params.append(limit)
        where = " WHERE " + " AND ".join(conditions)
        cur = conn.execute(
            f"SELECT * FROM trades{where} ORDER BY timestamp DESC LIMIT ?",
            params,
        )
        rows = cur.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def set_user_in_position(self, signal_id: str, in_position: bool) -> bool:
        """Mark trade as user-confirmed in position (clicked 'I'm in'). Returns True if updated."""
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.execute(
            "UPDATE trades SET user_in_position = ? WHERE signal_id = ?",
            (1 if in_position else 0, signal_id),
        )
        updated = cur.rowcount > 0
        conn.commit()
        conn.close()
        return updated

    def set_user_closed(self, signal_id: str) -> bool:
        """Mark that user closed position (clicked 'Closed'). Stops monitoring."""
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        cur = conn.execute(
            "UPDATE trades SET user_in_position = 0 WHERE signal_id = ?",
            (signal_id,),
        )
        updated = cur.rowcount > 0
        conn.commit()
        conn.close()
        return updated

    def mark_emergency_exit_alerted(self, signal_id: str) -> None:
        """Mark that we sent an emergency exit alert for this trade."""
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "UPDATE trades SET emergency_exit_alerted_at = ? WHERE signal_id = ?",
            (datetime.utcnow().isoformat(), signal_id),
        )
        conn.commit()
        conn.close()
