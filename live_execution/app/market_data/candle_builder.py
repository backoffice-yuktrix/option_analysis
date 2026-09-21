from __future__ import annotations

from app.models import Tick
from app.timeutil import floor_minute

CANDLE_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")


class CandleBuilder:
    def __init__(self, key: str):
        self.key = key
        self.live: dict | None = None
        self.version = 0
        self.ignored_out_of_order = 0
        self.ignored_duplicates = 0
        self._last_vtt: float | None = None
        self._last_sig: tuple | None = None

    def on_tick(self, tick: Tick) -> list[dict]:
        sig = (tick.ts, tick.price, tick.volume_total)
        if sig == self._last_sig:
            self.ignored_duplicates += 1
            return []
        minute = floor_minute(tick.ts)
        if self.live is not None and minute < self.live["timestamp"]:
            self.ignored_out_of_order += 1
            return []

        delta = 0.0
        if tick.volume_total is not None:
            if self._last_vtt is not None and tick.volume_total >= self._last_vtt:
                delta = tick.volume_total - self._last_vtt
            self._last_vtt = tick.volume_total

        finalized: list[dict] = []
        if self.live is None or minute > self.live["timestamp"]:
            if self.live is not None:
                finalized.append(self._close_live())
            self.live = {
                "timestamp": minute,
                "open": tick.price,
                "high": tick.price,
                "low": tick.price,
                "close": tick.price,
                "volume": delta,
            }
        else:
            self.live["high"] = max(self.live["high"], tick.price)
            self.live["low"] = min(self.live["low"], tick.price)
            self.live["close"] = tick.price
            self.live["volume"] += delta

        self._last_sig = sig
        self.version += 1
        self.live["last_tick_price"] = tick.price
        self.live["last_tick_timestamp"] = tick.ts.isoformat()
        self.live["market_version"] = self.version
        return finalized

    def roll_to(self, minute) -> list[dict]:
        if self.live is not None and self.live["timestamp"] < minute:
            closed = self._close_live()
            self.live = None
            return [closed]
        return []

    def _close_live(self) -> dict:
        return {k: self.live[k] for k in CANDLE_FIELDS}
