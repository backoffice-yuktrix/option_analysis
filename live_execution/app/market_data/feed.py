from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Callable

from app.config import IST
from app.models import Tick


def parse_ticks(message: dict) -> list[Tick]:
    ticks: list[Tick] = []
    for key, feed in (message.get("feeds") or {}).items():
        full = feed.get("fullFeed") or feed.get("ff") or {}
        inner = next((v for v in full.values() if isinstance(v, dict)), {})
        ltpc = feed.get("ltpc") or inner.get("ltpc")
        if not ltpc or not ltpc.get("ltp"):
            continue
        ltt = ltpc.get("ltt")
        ts = datetime.fromtimestamp(int(ltt) / 1000, tz=IST) if ltt else datetime.now(IST)
        vtt = inner.get("vtt")
        ticks.append(Tick(key=key, price=float(ltpc["ltp"]), ts=ts, volume_total=float(vtt) if vtt else None))
    return ticks


class MarketFeed:
    def __init__(
        self,
        token: str,
        keys: list[str],
        loop: asyncio.AbstractEventLoop,
        on_ticks: Callable[[list[Tick]], None],
        on_status: Callable[[bool], None],
    ):
        self._token = token
        self._keys = keys
        self._loop = loop
        self._on_ticks = on_ticks
        self._on_status = on_status
        self._streamer = None
        self.connected = False

    def start(self) -> None:
        import upstox_client

        config = upstox_client.Configuration()
        config.access_token = self._token
        self._streamer = upstox_client.MarketDataStreamerV3(
            upstox_client.ApiClient(config), self._keys, "full"
        )
        self._streamer.on("open", self._handle_open)
        self._streamer.on("message", self._handle_message)
        self._streamer.on("close", self._handle_close)
        self._streamer.on("error", self._handle_close)
        try:
            self._streamer.auto_reconnect(True, 5, 100)
        except Exception:
            pass
        threading.Thread(target=self._streamer.connect, name="upstox-feed", daemon=True).start()

    def stop(self) -> None:
        if self._streamer is not None:
            try:
                self._streamer.disconnect()
            except Exception:
                pass

    def _handle_open(self, *_) -> None:
        self.connected = True
        self._loop.call_soon_threadsafe(self._on_status, True)

    def _handle_close(self, *_) -> None:
        if self.connected:
            self.connected = False
            self._loop.call_soon_threadsafe(self._on_status, False)

    def _handle_message(self, message: dict) -> None:
        ticks = parse_ticks(message)
        if ticks:
            self._loop.call_soon_threadsafe(self._on_ticks, ticks)
