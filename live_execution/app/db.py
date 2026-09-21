from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from app.config import IST

ORDER_COLS = (
    "tag", "order_id", "strategy_id", "instrument", "side", "quantity", "order_type", "trigger_reason",
    "reference_price", "stop_loss", "target", "submitted_at", "acknowledged_at", "status",
    "filled_quantity", "average_price", "fill_time", "broker_message", "mode", "latency_ms",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    tag TEXT PRIMARY KEY, order_id TEXT, strategy_id TEXT, instrument TEXT, side TEXT, quantity INTEGER,
    order_type TEXT, trigger_reason TEXT, reference_price REAL, stop_loss REAL, target REAL,
    submitted_at TEXT, acknowledged_at TEXT, status TEXT, filled_quantity INTEGER, average_price REAL,
    fill_time TEXT, broker_message TEXT, mode TEXT, latency_ms INTEGER
);
CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_id TEXT, instrument TEXT, side TEXT, quantity INTEGER,
    entry_order_id TEXT, exit_order_id TEXT, entry_price REAL, exit_price REAL, stop_loss REAL, target REAL,
    pnl REAL, exit_reason TEXT, entry_time TEXT, exit_time TEXT
);
CREATE TABLE IF NOT EXISTS candle_diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_id TEXT, series TEXT, instrument TEXT, minute TEXT,
    local_json TEXT, official_json TEXT, difference_json TEXT, corrected INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS strategy_state (
    strategy_id TEXT PRIMARY KEY, state_json TEXT, updated_at TEXT
);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def _execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def upsert_order(self, order: dict) -> None:
        cols = ", ".join(ORDER_COLS)
        marks = ", ".join("?" for _ in ORDER_COLS)
        self._execute(
            f"INSERT OR REPLACE INTO orders ({cols}) VALUES ({marks})",
            tuple(order.get(c) for c in ORDER_COLS),
        )

    def orders_for(self, strategy_id: str, limit: int = 200) -> list[dict]:
        return self._query(
            "SELECT * FROM orders WHERE strategy_id = ? ORDER BY submitted_at DESC LIMIT ?",
            (strategy_id, limit),
        )

    def insert_trade(self, trade: dict) -> None:
        cols = [
            "strategy_id", "instrument", "side", "quantity", "entry_order_id", "exit_order_id", "entry_price",
            "exit_price", "stop_loss", "target", "pnl", "exit_reason", "entry_time", "exit_time",
        ]
        self._execute(
            f"INSERT INTO trades ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            tuple(trade.get(c) for c in cols),
        )

    def trades_for(self, strategy_id: str, limit: int = 200) -> list[dict]:
        return self._query(
            "SELECT * FROM trades WHERE strategy_id = ? ORDER BY trade_id DESC LIMIT ?", (strategy_id, limit)
        )

    def insert_diag(self, *, strategy_id, series, instrument, minute, local, official, difference, corrected) -> None:
        self._execute(
            "INSERT INTO candle_diagnostics (strategy_id, series, instrument, minute, local_json, official_json,"
            " difference_json, corrected, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                strategy_id, series, instrument, minute, json.dumps(local), json.dumps(official),
                json.dumps(difference), int(corrected), datetime.now(IST).isoformat(),
            ),
        )

    def save_state(self, strategy_id: str, state: dict) -> None:
        self._execute(
            "INSERT OR REPLACE INTO strategy_state (strategy_id, state_json, updated_at) VALUES (?, ?, ?)",
            (strategy_id, json.dumps(state), datetime.now(IST).isoformat()),
        )

    def load_state(self, strategy_id: str) -> dict | None:
        rows = self._query("SELECT state_json FROM strategy_state WHERE strategy_id = ?", (strategy_id,))
        return json.loads(rows[0]["state_json"]) if rows else None
