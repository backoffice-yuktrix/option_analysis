from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import date
from urllib.parse import quote

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.upstox_client import get_candles, get_option_contracts, INSTRUMENT_KEYS  # noqa: E402

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "upstox_config.txt")

BASE_V2 = "https://api.upstox.com/v2"
BASE_V3 = "https://api.upstox.com/v3"
UNDERLYING = "NIFTY"
UNDERLYING_KEY = INSTRUMENT_KEYS[UNDERLYING]
STRIKE_STEP = 50

RANGE_FROM = date(2025, 1, 1)
RANGE_TO = date.today()

NA = "N/A"

# Target 3-minute time slots between 3:00 PM and 3:30 PM (10 candles)
TARGET_TIMES = [
    "15:00:00", "15:03:00", "15:06:00", "15:09:00", "15:12:00",
    "15:15:00", "15:18:00", "15:21:00", "15:24:00", "15:27:00"
]

FALLBACK_EXPIRIES: list[date] = [
    # --- 2025 Expiries ---
    date(2025, 1, 2), date(2025, 1, 9), date(2025, 1, 16), date(2025, 1, 23), date(2025, 1, 30),
    date(2025, 2, 6), date(2025, 2, 13), date(2025, 2, 20), date(2025, 2, 27),
    date(2025, 3, 6), date(2025, 3, 13), date(2025, 3, 20), date(2025, 3, 27),
    date(2025, 4, 3), date(2025, 4, 10), date(2025, 4, 17), date(2025, 4, 24),
    date(2025, 4, 30), # Shifted from May 1 (Maharashtra Day)
    date(2025, 5, 8), date(2025, 5, 15), date(2025, 5, 22), date(2025, 5, 29),
    date(2025, 6, 5), date(2025, 6, 12), date(2025, 6, 19), date(2025, 6, 26),
    date(2025, 7, 3), date(2025, 7, 10), date(2025, 7, 17), date(2025, 7, 24), date(2025, 7, 31),
    date(2025, 8, 7), date(2025, 8, 14), date(2025, 8, 21), date(2025, 8, 28),
    date(2025, 9, 2), date(2025, 9, 9), date(2025, 9, 16), date(2025, 9, 23), date(2025, 9, 30),
    date(2025, 10, 7), date(2025, 10, 14), date(2025, 10, 21), date(2025, 10, 28),
    date(2025, 11, 4), date(2025, 11, 11), date(2025, 11, 18), date(2025, 11, 25),
    date(2025, 12, 2), date(2025, 12, 9), date(2025, 12, 16), date(2025, 12, 23), date(2025, 12, 30),
    
    # --- 2026 Expiries ---
    date(2026, 1, 6), date(2026, 1, 13), date(2026, 1, 20), date(2026, 1, 27),
    date(2026, 2, 3), date(2026, 2, 10), date(2026, 2, 17), date(2026, 2, 24),
    date(2026, 3, 2), date(2026, 3, 10), date(2026, 3, 17), date(2026, 3, 24), date(2026, 3, 30),
    date(2026, 4, 7), date(2026, 4, 13), date(2026, 4, 21), date(2026, 4, 28),
    date(2026, 5, 5), date(2026, 5, 12), date(2026, 5, 19), date(2026, 5, 26),
    date(2026, 6, 2), date(2026, 6, 9), date(2026, 6, 16), date(2026, 6, 23), date(2026, 6, 30),
    date(2026, 7, 7), date(2026, 7, 14), date(2026, 7, 21), date(2026, 7, 28)
]


def _read_access_token() -> str:
    with open(CONFIG_FILE) as f:
        lines = [l.strip() for l in f.readlines()]
    if len(lines) < 4 or not lines[3]:
        raise RuntimeError(f"No access_token found in {CONFIG_FILE}. Connect to Upstox first.")
    return lines[3]


async def _get(client: httpx.AsyncClient, url: str, token: str, params: dict | None = None) -> dict:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    resp = await client.get(url, headers=headers, params=params)
    if resp.status_code == 429:
        print(f"[Rate Limit Hit] HTTP 429 for URL: {url}")
    if resp.status_code == 200:
        return resp.json()
    raise RuntimeError(f"Upstox HTTP {resp.status_code} for {url}: {resp.text[:300]}")


async def get_expired_expiries(client: httpx.AsyncClient, token: str, instrument_key: str) -> list[date]:
    data = await _get(client, f"{BASE_V2}/expired-instruments/expiries", token, {"instrument_key": instrument_key})
    return sorted(date.fromisoformat(s) for s in data.get("data", []) or [])


async def get_expired_option_contracts(client: httpx.AsyncClient, token: str, instrument_key: str, expiry: date) -> list[dict]:
    data = await _get(
        client,
        f"{BASE_V2}/expired-instruments/option/contract",
        token,
        {"instrument_key": instrument_key, "expiry_date": expiry.isoformat()},
    )
    return data.get("data", []) or []


async def get_3min_candles(
    client: httpx.AsyncClient, token: str, instrument_key: str, is_expired: bool, d: date
) -> list[dict]:
    """Fetch 3-minute candles for a specific day."""
    key_enc = quote(instrument_key, safe="")
    if is_expired:
        url = f"{BASE_V2}/expired-instruments/historical-candle/{key_enc}/3minute/{d.isoformat()}/{d.isoformat()}"
    else:
        url = f"{BASE_V3}/historical-candle/{key_enc}/minutes/3/{d.isoformat()}/{d.isoformat()}"
    
    try:
        data = await _get(client, url, token)
        raw = (data.get("data", {}) or {}).get("candles", [])
        return [{"timestamp": c[0], "close": float(c[4])} for c in raw if len(c) >= 5]
    except RuntimeError:
        return []


async def process_day(
    d: date,
    nifty_close: float,
    expiry: date | None,
    token: str,
    live_expiries: list[date],
    live_by_key: dict,
    expired_contracts_cache: dict,
    client: httpx.AsyncClient,
) -> tuple[str, str, str, str]:
    if expiry is None:
        return NA, "[]", NA, "[]"

    atm_strike = float(round(nifty_close / STRIKE_STEP) * STRIKE_STEP)

    async def _resolve_contract(option_type: str) -> dict | None:
        if expiry in live_expiries:
            return live_by_key.get((expiry.isoformat(), atm_strike, option_type))
        if expiry not in expired_contracts_cache:
            try:
                expired_contracts_cache[expiry] = await get_expired_option_contracts(client, token, UNDERLYING_KEY, expiry)
            except RuntimeError:
                expired_contracts_cache[expiry] = []
        for c in expired_contracts_cache[expiry]:
            if float(c.get("strike_price", 0)) == atm_strike and c.get("instrument_type") == option_type:
                return {
                    "trading_symbol": c.get("trading_symbol", ""),
                    "instrument_key": c.get("instrument_key", ""),
                    "expired": True,
                }
        return None

    async def _option_3pm_closes(contract: dict) -> list[float | str]:
        instrument_key = contract["instrument_key"]
        is_expired = contract.get("expired", False)
        candles = await get_3min_candles(client, token, instrument_key, is_expired, d)
        
        # Map candles by HH:MM:SS time string
        candles_by_time = {}
        for c in candles:
            # timestamp format: "YYYY-MM-DDTHH:MM:SS+05:30"
            if len(c["timestamp"]) >= 19:
                time_str = c["timestamp"][11:19]
                candles_by_time[time_str] = c["close"]

        # Extract 10 values corresponding to 3:00 PM - 3:30 PM slots
        closes = [candles_by_time.get(t, "-") for t in TARGET_TIMES]
        return closes

    ce_contract, pe_contract = await asyncio.gather(_resolve_contract("CE"), _resolve_contract("PE"))

    call_name = ce_contract["trading_symbol"] if ce_contract else NA
    put_name = pe_contract["trading_symbol"] if pe_contract else NA

    ce_vals, pe_vals = await asyncio.gather(
        _option_3pm_closes(ce_contract) if ce_contract else asyncio.sleep(0, result=["-"] * 10),
        _option_3pm_closes(pe_contract) if pe_contract else asyncio.sleep(0, result=["-"] * 10),
    )

    format_vals = lambda vals: "[" + ", ".join(f"{v:.2f}" if isinstance(v, float) else str(v) for v in vals) + "]"

    return call_name, format_vals(ce_vals), put_name, format_vals(pe_vals)


async def main() -> None:
    token = _read_access_token()
    counter = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        nifty_candles = await get_candles(token, UNDERLYING_KEY, "1d", RANGE_FROM, RANGE_TO)
        if not nifty_candles:
            print("No NIFTY candles returned for the range.")
            return

        expired_expiries = [e for e in await get_expired_expiries(client, token, UNDERLYING_KEY) if RANGE_FROM <= e <= RANGE_TO]
        live_contracts = await get_option_contracts(token, UNDERLYING)
        live_expiries = sorted({date.fromisoformat(c["expiry"][:10]) for c in live_contracts})
        fallback_expiries = [e for e in FALLBACK_EXPIRIES if RANGE_FROM <= e <= RANGE_TO]
        all_expiries = sorted(set(expired_expiries) | set(live_expiries) | set(fallback_expiries))

        def _nearest_expiry(d: date) -> date | None:
            for e in all_expiries:
                if e >= d:
                    return e
            return None

        live_by_key = {(c["expiry"][:10], c["strike"], c["option_type"]): c for c in live_contracts}
        expired_contracts_cache: dict[date, list[dict]] = {}

        header = f"{'Date':<12}{'NIFTY Close':<14}{'ATM Call':<25}{'Call 3PM-3:30PM (10 Closes)':<65}{'ATM Put':<25}{'Put 3PM-3:30PM (10 Closes)':<65}"
        print(header)
        print("-" * len(header))

        for candle in nifty_candles:
            d = date.fromisoformat(candle["timestamp"][:10])
            nifty_close = candle["close"]
            expiry = _nearest_expiry(d)

            call_name, call_closes, put_name, put_closes = await process_day(
                d, nifty_close, expiry, token, live_expiries, live_by_key,
                expired_contracts_cache, client
            )

            print(
                f"{d.isoformat():<12}{nifty_close:<14.2f}"
                f"{call_name:<25}{call_closes:<65}"
                f"{put_name:<25}{put_closes:<65}"
            )

            counter = counter + 1
            if counter % 20 == 0:
                time.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())