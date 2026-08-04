"""Fetch NIFTY 1-minute OHLCV candles for Jan 1 - Jul 31, 2026 and cache locally.

Saves the full series to nifty_jan1_july31.json and a small
nifty_jan1_july31_sample.json (first + last 10 candles) so
analyse_overnight_jump.py (and anyone else) can see the JSON shape without
opening the full file.

Reuses services/upstox_client.get_candles exactly as module1/module2 do,
and the same upstox_config.txt credentials. Run from backend/:
    python scripts/fetch_nifty_jan1_july31.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.upstox_client import get_candles, INSTRUMENT_KEYS  # noqa: E402

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "upstox_config.txt")
OUT_FULL = os.path.join(os.path.dirname(__file__), "nifty_jan1_july31.json")
OUT_SAMPLE = os.path.join(os.path.dirname(__file__), "nifty_jan1_july31_sample.json")

RANGE_FROM = date(2026, 1, 1)
RANGE_TO = date(2026, 7, 31)
UNDERLYING = "NIFTY"


def _read_access_token() -> str:
    with open(CONFIG_FILE) as f:
        lines = [l.strip() for l in f.readlines()]
    if len(lines) < 4 or not lines[3]:
        raise RuntimeError(f"No access_token found in {CONFIG_FILE}. Connect to Upstox first.")
    return lines[3]


async def main() -> None:
    token = _read_access_token()

    print(f"Fetching NIFTY 1-minute candles {RANGE_FROM.isoformat()} -> {RANGE_TO.isoformat()} ...")
    candles = await get_candles(token, INSTRUMENT_KEYS[UNDERLYING], "1m", RANGE_FROM, RANGE_TO)
    print(f"Fetched {len(candles)} candles.")

    if not candles:
        print("No candles returned - nothing to save.")
        return

    with open(OUT_FULL, "w") as f:
        json.dump(candles, f)
    print(f"Saved full data to {OUT_FULL}")

    sample = candles[:10] + candles[-10:] if len(candles) > 20 else candles
    with open(OUT_SAMPLE, "w") as f:
        json.dump(sample, f, indent=2)
    print(f"Saved sample (first/last 10) to {OUT_SAMPLE}")


if __name__ == "__main__":
    asyncio.run(main())
