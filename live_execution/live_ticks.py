"""Stream live NIFTY 50 and RELIANCE ticks from Upstox and print them.  Run from anywhere:

    python live_ticks.py

Uses the Upstox WebSocket market data feed (V3) through the official SDK, which handles
the protobuf decoding.  Reads the access token from line 4 of upstox_config.txt.
Press Ctrl+C to stop.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from datetime import datetime, timezone, timedelta

import upstox_client

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upstox_config.txt")
INSTRUMENTS = {
    "NSE_INDEX|Nifty 50": "NIFTY 50",
    "NSE_EQ|INE002A01018": "RELIANCE",
}
MODE = "ltpc"
IST = timezone(timedelta(hours=5, minutes=30))


def read_token() -> str:
    if not os.path.exists(CONFIG_FILE):
        sys.exit(f"Missing {CONFIG_FILE}. Run connect_upstox.py first.")
    with open(CONFIG_FILE, encoding="utf-8") as f:
        lines = [l.strip() for l in f.read().splitlines()]
    if len(lines) < 4 or not lines[3]:
        sys.exit("No access token on line 4 of upstox_config.txt. Run connect_upstox.py first.")
    return lines[3]


def find_ltpc(feed: dict) -> dict | None:
    if "ltpc" in feed:
        return feed["ltpc"]
    for full in feed.get("fullFeed", feed.get("ff", {})).values():
        if isinstance(full, dict) and "ltpc" in full:
            return full["ltpc"]
    return None


def on_open() -> None:
    print(f"Connected. Subscribed to {', '.join(INSTRUMENTS.values())}. Waiting for ticks...")


def on_message(message: dict) -> None:
    feeds = message.get("feeds")
    if not feeds:
        return
    for key, feed in feeds.items():
        ltpc = find_ltpc(feed)
        if not ltpc or "ltp" not in ltpc:
            continue
        ltt = ltpc.get("ltt")
        tick_time = (
            datetime.fromtimestamp(int(ltt) / 1000, tz=IST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            if ltt else "n/a"
        )
        print(f"{INSTRUMENTS.get(key, key):<10} ltp={ltpc['ltp']:<10} tick_time={tick_time} IST"
              f"  prev_close={ltpc.get('cp')}", flush=True)


def on_error(error: object) -> None:
    print(f"Stream error: {error}", file=sys.stderr, flush=True)


def on_close(*_: object) -> None:
    print("Connection closed.")


def main() -> None:
    config = upstox_client.Configuration()
    config.access_token = read_token()
    streamer = upstox_client.MarketDataStreamerV3(
        upstox_client.ApiClient(config), list(INSTRUMENTS), MODE
    )
    streamer.on("open", on_open)
    streamer.on("message", on_message)
    streamer.on("error", on_error)
    streamer.on("close", on_close)
    def stop(*_: object) -> None:
        print("\nStopping...", flush=True)
        os._exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop)
    streamer.connect()
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
