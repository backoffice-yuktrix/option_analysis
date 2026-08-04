"""Upstox REST API client for the standalone option_analysis app.

No DB / instrument master. Instrument keys for NIFTY/BANKNIFTY are hardcoded.
Option contract keys are resolved live via the /option/contract endpoint.

Reused patterns from:
  app/broker/plugins/upstox/auth.py   — OAuth URL + token exchange
  app/broker/plugins/upstox/data.py   — _get(), get_history(), get_option_contracts()
  app/market_data/history_client.py   — calendar-month chunking for 1m Upstox data
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from urllib.parse import urlencode, quote

import httpx

UPSTOX_BASE_V2 = "https://api.upstox.com/v2"
UPSTOX_BASE_V3 = "https://api.upstox.com/v3"

# Hardcoded Upstox instrument keys for supported underlyings
INSTRUMENT_KEYS: dict[str, str] = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "VIX": "NSE_INDEX|India VIX",
}

# Upstox 1m data cap is one calendar month per call
_MONTHLY_INTERVALS = frozenset({"1m", "3m", "5m", "10m", "15m"})
_QUARTERLY_INTERVALS = frozenset({"30m", "1h"})

_INTERVAL_TO_UNIT: dict[str, tuple[str, str]] = {
    "1m": ("minutes", "1"),
    "3m": ("minutes", "3"),
    "5m": ("minutes", "5"),
    "10m": ("minutes", "10"),
    "15m": ("minutes", "15"),
    "30m": ("minutes", "30"),
    "1h": ("hours", "1"),
    "1d": ("days", "1"),
}


def _headers(auth_token: str | None) -> dict[str, str]:
    h = {"Accept": "application/json"}
    if auth_token:
        h["Authorization"] = f"Bearer {auth_token}"
    return h


async def _get(url: str, auth_token: str | None, params: dict | None = None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=_headers(auth_token), params=params)
    except httpx.RequestError as exc:
        raise RuntimeError(f"Upstox network error: {exc}") from exc

    if resp.status_code == 200:
        try:
            return resp.json()
        except Exception as exc:
            raise RuntimeError(f"Upstox malformed response: {exc}") from exc

    if resp.status_code in (401, 403):
        raise PermissionError("Upstox token expired or unauthorized. Re-connect.")
    raise RuntimeError(f"Upstox HTTP {resp.status_code}: {resp.text[:300]}")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_auth_url(api_key: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": api_key,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{UPSTOX_BASE_V2}/login/authorization/dialog?{urlencode(params)}"


async def exchange_code(
    api_key: str, api_secret: str, code: str, redirect_uri: str
) -> str:
    """Exchange OAuth code for access token. Returns the access_token string."""
    url = f"{UPSTOX_BASE_V2}/login/authorization/token"
    form_data = {
        "code": code,
        "client_id": api_key,
        "client_secret": api_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, data=form_data)
    except httpx.RequestError as exc:
        raise RuntimeError(f"Upstox auth network error: {exc}") from exc

    if resp.status_code == 200:
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError("Upstox returned no access_token")
        return token

    try:
        err = resp.json()
        errors = err.get("errors", [])
        msg = "; ".join(e.get("message", "") for e in errors) if errors else err.get("message", resp.text)
    except Exception:
        msg = resp.text
    raise RuntimeError(f"Upstox auth failed (HTTP {resp.status_code}): {msg}")


# ---------------------------------------------------------------------------
# Historical candles — calendar-month chunking for 1m data
# ---------------------------------------------------------------------------

def _end_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1) - timedelta(days=1)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _end_of_quarter(d: date) -> date:
    end_month = ((d.month - 1) // 3 + 1) * 3
    if end_month == 12:
        return date(d.year + 1, 1, 1) - timedelta(days=1)
    return date(d.year, end_month + 1, 1) - timedelta(days=1)


def _chunk_end(interval: str, cur_from: date, to_date: date) -> date:
    if interval in _MONTHLY_INTERVALS:
        return min(_end_of_month(cur_from), to_date)
    if interval in _QUARTERLY_INTERVALS:
        return min(_end_of_quarter(cur_from), to_date)
    return min(cur_from + timedelta(days=365 * 10), to_date)


def _candle_to_dict(raw: list) -> dict:
    """Upstox v3 candle: [timestamp, open, high, low, close, volume, oi]"""
    if len(raw) < 6:
        return {}
    return {
        "timestamp": raw[0],
        "open": float(raw[1]),
        "high": float(raw[2]),
        "low": float(raw[3]),
        "close": float(raw[4]),
        "volume": int(raw[5]),
        "oi": int(raw[6]) if len(raw) > 6 else 0,
    }


async def _fetch_candles_one_window(
    auth_token: str,
    instrument_key: str,
    interval: str,
    win_from: date,
    win_to: date,
) -> list[dict]:
    unit, value = _INTERVAL_TO_UNIT.get(interval, ("days", "1"))
    key_enc = quote(instrument_key, safe="")
    url = (
        f"{UPSTOX_BASE_V3}/historical-candle/{key_enc}"
        f"/{unit}/{value}/{win_to.isoformat()}/{win_from.isoformat()}"
    )
    data = await _get(url, auth_token)
    raw_candles = (data.get("data", {}) or {}).get("candles", [])
    return [_candle_to_dict(c) for c in raw_candles if c]


async def get_candles(
    auth_token: str,
    instrument_key: str,
    interval: str,
    from_date: date,
    to_date: date,
    *,
    concurrency: int = 4,
) -> list[dict]:
    """Fetch OHLCV candles for any interval, chunking for Upstox monthly cap."""
    windows: list[tuple[date, date]] = []
    cur = from_date
    while cur <= to_date:
        end = _chunk_end(interval, cur, to_date)
        windows.append((cur, end))
        cur = end + timedelta(days=1)

    sem = asyncio.Semaphore(concurrency)

    async def _fetch(win: tuple[date, date]) -> list[dict]:
        async with sem:
            return await _fetch_candles_one_window(auth_token, instrument_key, interval, win[0], win[1])

    results = await asyncio.gather(*(_fetch(w) for w in windows))
    seen: set[str] = set()
    out: list[dict] = []
    for chunk in results:
        for c in chunk:
            ts = c.get("timestamp", "")
            if ts and ts not in seen:
                seen.add(ts)
                out.append(c)
    out.sort(key=lambda c: c.get("timestamp", ""))
    return out


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

async def get_option_contracts(
    auth_token: str, underlying: str
) -> list[dict]:
    """Return all option contracts for the underlying (NIFTY or BANKNIFTY).
    Each item: {trading_symbol, instrument_key, strike, expiry, option_type, lot_size}
    """
    key = INSTRUMENT_KEYS[underlying]
    data = await _get(
        f"{UPSTOX_BASE_V2}/option/contract",
        auth_token,
        params={"instrument_key": key},
    )
    contracts = data.get("data", []) or []
    out = []
    for c in contracts:
        out.append({
            "trading_symbol": c.get("trading_symbol", ""),
            "instrument_key": c.get("instrument_key", ""),
            "strike": float(c.get("strike_price", 0)),
            "expiry": c.get("expiry", ""),
            "option_type": c.get("instrument_type", ""),   # CE | PE
            "lot_size": int(c.get("lot_size", 0) or 0),
        })
    return out


async def get_vix_daily(
    auth_token: str, from_date: date, to_date: date
) -> dict[str, float]:
    """Return {date_str: vix_close} for the date range."""
    candles = await get_candles(
        auth_token,
        INSTRUMENT_KEYS["VIX"],
        "1d",
        from_date,
        to_date,
    )
    return {c["timestamp"][:10]: c["close"] for c in candles if c.get("close")}
