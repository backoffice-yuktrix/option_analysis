from __future__ import annotations

import pandas as pd

from app.timeutil import to_ts

COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "source"]


class CandleStore:
    def __init__(self, max_rows: int = 500):
        self._max_rows = max_rows
        self._rows: dict[int, dict] = {}

    def upsert(self, candle: dict, source: str) -> None:
        ts = to_ts(candle["timestamp"])
        self._rows[int(ts.timestamp())] = {
            "timestamp": ts,
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle["volume"]),
            "source": source,
        }
        while len(self._rows) > self._max_rows:
            del self._rows[min(self._rows)]

    def get(self, ts) -> dict | None:
        return self._rows.get(int(to_ts(ts).timestamp()))

    def frame(self) -> pd.DataFrame:
        if not self._rows:
            return pd.DataFrame(columns=COLUMNS)
        return pd.DataFrame([self._rows[k] for k in sorted(self._rows)], columns=COLUMNS)

    def tail(self, n: int) -> list[dict]:
        return [self._rows[k] for k in sorted(self._rows)[-n:]]
