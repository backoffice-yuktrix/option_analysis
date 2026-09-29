"""Candles on disk (candle_datas/) and from Upstox.

    fetch(instrument, ce_pe_strikeprice_expiry, frm, to)          candles from candle_datas/*.json - no API call
    await fetch_broker(instrument, ce_pe_strikeprice_expiry, frm, to)   candles from Upstox, merged into candle_datas/*.json
    await fetch_expiries(instrument, frm, to)                     expiry list -> candle_datas/<INSTRUMENT>_expiry.json

instrument                 "NIFTY" (the underlying index)
ce_pe_strikeprice_expiry   None                   -> the index itself      candle_datas/NIFTY_candles.json
                           "CE_23000_2026-01-27"  -> that option contract  candle_datas/NIFTY_CE_23000_2026-01-27_candles.json
                           (a tuple ("CE", 23000, date(2026, 1, 27)) works too)

fetch_broker splits the range into batches the API accepts (MAX_RANGE per request): one calendar
month for 1-minute candles (Jan 1..Jan 31, Feb 1..Feb 28, ...), or N days (from..from+N-1, ...).  After every batch the file is saved and the fetched range recorded, so an
interrupted run resumes where it stopped and a range already fetched is not asked for again.

CLI
    python fetch_candles.py candles NIFTY --from 2026-01-01 --to 2026-07-31
    python fetch_candles.py candles NIFTY --opt CE_23000_2026-01-27 --from 2026-01-07 --to 2026-01-27
    python fetch_candles.py expiries NIFTY --from 2026-01-01 --to 2026-07-31
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
from datetime import date, datetime, timedelta
from urllib.parse import quote

from upstox_funcs import BASE_V2, BASE_V3, IST, Upstox

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "candle_datas")

# Range per request: a number of days, or "month" = one calendar month (from .. from+1 month-1 day).
# v3 historical, 1-15 minute intervals: probed 2026-09-29 - to_date may be at most the same day of the
# next month (Feb 15..Mar 15 ok, Feb 15..Mar 16 -> UDAPI1148 Invalid date range), so a fixed 30 days
# fails whenever it crosses February.  The expired-contract endpoint publishes no cap; "month" is
# assumed until a probe says otherwise.
MAX_RANGE = {"index": "month", "expired": "month", "live": "month"}

# Index keys, so the instrument master (a large download) is not needed for the common ones.
UNDERLYING_KEYS = {"NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank",
                   "FINNIFTY": "NSE_INDEX|Nifty Fin Service", "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT"}

# interval -> (v3 unit, v3 n, expired-endpoint name)
INTERVALS = {"1m": ("minutes", 1, "1minute"), "3m": ("minutes", 3, "3minute"),
             "5m": ("minutes", 5, "5minute"), "15m": ("minutes", 15, "15minute"),
             "30m": ("minutes", 30, "30minute"), "1d": ("days", 1, "day")}


# ---------------------------------------------------------------------------
# names and files
# ---------------------------------------------------------------------------
def parse_option(ce_pe_strikeprice_expiry) -> tuple[str, float, date] | None:
    """"CE_23000_2026-01-27" or ("CE", 23000, date) -> ("CE", 23000.0, date).  None stays None."""
    if ce_pe_strikeprice_expiry is None:
        return None
    if isinstance(ce_pe_strikeprice_expiry, str):
        parts = ce_pe_strikeprice_expiry.split("_")
        if len(parts) != 3:
            raise ValueError(f"{ce_pe_strikeprice_expiry!r}: use CE_23000_2026-01-27")
        ot, strike, expiry = parts
    else:
        ot, strike, expiry = ce_pe_strikeprice_expiry
    ot = ot.upper()
    if ot not in ("CE", "PE"):
        raise ValueError(f"option type {ot!r}: use CE or PE")
    if isinstance(expiry, str):
        expiry = date.fromisoformat(expiry)
    return ot, float(strike), expiry


def option_name(ot: str, strike: float, expiry: date) -> str:
    return f"{ot}_{strike:g}_{expiry.isoformat()}"


def candle_file(instrument: str, ce_pe_strikeprice_expiry=None, interval: str = "1m") -> str:
    opt = parse_option(ce_pe_strikeprice_expiry)
    sfx = "" if interval == "1m" else f"_{interval}"
    mid = "" if opt is None else "_" + option_name(*opt)
    return os.path.join(DATA_DIR, f"{instrument.upper()}{mid}{sfx}_candles.json")


def _load(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path: str, blob: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(blob, f, separators=(",", ":"))
    os.replace(tmp, path)                                   # atomic: never a half-written file


# ---------------------------------------------------------------------------
# date ranges
# ---------------------------------------------------------------------------
def add_month(d: date) -> date:
    """Same day next month, clamped to that month's last day (Jan 31 -> Feb 28)."""
    y, m = d.year + (d.month == 12), d.month % 12 + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def batches(frm: date, to: date, limit: int | str) -> list[tuple[date, date]]:
    """Split [frm, to] into request-sized pieces, both ends inclusive.
    limit=30      -> frm..frm+29, frm+30..frm+59, ...
    limit="month" -> Jan 1..Jan 31, Feb 1..Feb 28, ... (from frm, one calendar month each)"""
    out, cur = [], frm
    while cur <= to:
        nxt = add_month(cur) if limit == "month" else cur + timedelta(days=limit)
        end = min(nxt - timedelta(days=1), to)
        out.append((cur, end))
        cur = end + timedelta(days=1)
    return out


def _merge_ranges(ranges: list[list[str]]) -> list[list[str]]:
    """Merge overlapping or touching [from, to] date ranges."""
    out: list[list[date]] = []
    for a, b in sorted((date.fromisoformat(a), date.fromisoformat(b)) for a, b in ranges):
        if out and a <= out[-1][1] + timedelta(days=1):
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [[a.isoformat(), b.isoformat()] for a, b in out]


def gaps(frm: date, to: date, fetched: list[list[str]]) -> list[tuple[date, date]]:
    """The parts of [frm, to] not inside any fetched range."""
    out, cur = [], frm
    for a, b in _merge_ranges(fetched):
        a, b = date.fromisoformat(a), date.fromisoformat(b)
        if b < cur:
            continue
        if a > to:
            break
        if a > cur:
            out.append((cur, a - timedelta(days=1)))
        cur = max(cur, b + timedelta(days=1))
    if cur <= to:
        out.append((cur, to))
    return out


def _as_dicts(rows: list[list]) -> list[dict]:
    return [{"timestamp": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4],
             "volume": r[5] if len(r) > 5 else 0, "oi": r[6] if len(r) > 6 else 0} for r in rows]


# ---------------------------------------------------------------------------
# fetch - from disk
# ---------------------------------------------------------------------------
def fetch(instrument: str, ce_pe_strikeprice_expiry=None, frm: date | None = None, to: date | None = None,
          interval: str = "1m", warn: bool = True) -> list[dict]:
    """Candles from candle_datas/ for [frm, to] (all when omitted), oldest first.
    Each: {timestamp, open, high, low, close, volume, oi}.  No API call."""
    path = candle_file(instrument, ce_pe_strikeprice_expiry, interval)
    blob = _load(path)
    if blob is None:
        raise FileNotFoundError(f"{path} not found - run fetch_broker first")
    rows = blob["candles"]
    if frm or to:
        lo, hi = (frm or date.min).isoformat(), (to or date.max).isoformat()
        rows = [r for r in rows if lo <= r[0][:10] <= hi]
        missing = gaps(frm or date.fromisoformat(blob["fetched"][0][0]),
                       to or date.fromisoformat(blob["fetched"][-1][1]), blob["fetched"]) if blob["fetched"] else [(frm, to)]
        if missing and warn:
            print(f"  ! {os.path.basename(path)}: not fetched yet for "
                  + ", ".join(f"{a}..{b}" for a, b in missing))
    return _as_dicts(rows)


# ---------------------------------------------------------------------------
# contracts and expiries
# ---------------------------------------------------------------------------
async def underlying_key(up: Upstox, instrument: str) -> str:
    key = UNDERLYING_KEYS.get(instrument.upper())
    return key or (await up.find_instrument(instrument))["instrument_key"]


def _contracts_file(instrument: str) -> str:
    return os.path.join(DATA_DIR, f"{instrument.upper()}_contracts.json")


async def contracts(up: Upstox, instrument: str, expiry: date) -> list[dict]:
    """Every option contract of one expiry, kept in candle_datas/<INSTRUMENT>_contracts.json.
    Past expiries: 1 API call the first time, then from disk."""
    path = _contracts_file(instrument)
    blob = _load(path) or {}
    ek = expiry.isoformat()
    if ek not in blob:
        ukey = await underlying_key(up, instrument)
        if expiry < datetime.now(IST).date():
            raw, expired = await up.expired_option_contracts(ukey, expiry), True
        else:
            raw = [c for c in await up.option_contracts(ukey) if str(c["expiry"])[:10] == ek]
            expired = False
        rows = [{"instrument_key": c["instrument_key"], "trading_symbol": c.get("trading_symbol"),
                 "strike": float(c["strike_price"]), "type": c["instrument_type"],
                 "lot_size": int(c.get("lot_size") or 0), "expired": expired} for c in raw]
        if expiry < datetime.now(IST).date():           # a live expiry's strike list can still grow
            blob[ek] = sorted(rows, key=lambda r: (r["strike"], r["type"]))
            _save(path, blob)
        return rows
    return blob[ek]


async def fetch_expiries(instrument: str, frm: date, to: date, up: Upstox | None = None) -> list[date]:
    """Every expiry (expired + live) in [frm, to] -> candle_datas/<INSTRUMENT>_expiry.json."""
    if up is None:
        async with Upstox() as up_:
            return await fetch_expiries(instrument, frm, to, up_)
    ukey = await underlying_key(up, instrument)
    exps = [e for e in await up.expiries(ukey) if frm <= e <= to]
    _save(os.path.join(DATA_DIR, f"{instrument.upper()}_expiry.json"),
          {"instrument": instrument.upper(), "instrument_key": ukey, "from": frm.isoformat(),
           "to": to.isoformat(), "expiries": [e.isoformat() for e in exps]})
    return exps


def load_expiries(instrument: str) -> list[date]:
    blob = _load(os.path.join(DATA_DIR, f"{instrument.upper()}_expiry.json"))
    if blob is None:
        raise FileNotFoundError(f"no expiry list for {instrument} - run fetch_expiries first")
    return [date.fromisoformat(e) for e in blob["expiries"]]


# ---------------------------------------------------------------------------
# fetch_broker - from Upstox, into candle_datas/
# ---------------------------------------------------------------------------
async def _get_candles(up: Upstox, key: str, kind: str, interval: str, a: date, b: date) -> list[list]:
    unit, n, name = INTERVALS[interval]
    k = quote(key, safe="")
    if kind == "expired":
        url = f"{BASE_V2}/expired-instruments/historical-candle/{k}/{name}/{b.isoformat()}/{a.isoformat()}"
    else:
        url = f"{BASE_V3}/historical-candle/{k}/{unit}/{n}/{b.isoformat()}/{a.isoformat()}"
    d = await up.get(url)
    return (d.get("data") or {}).get("candles") or []


async def fetch_broker(instrument: str, ce_pe_strikeprice_expiry=None, frm: date | None = None,
                       to: date | None = None, *, up: Upstox | None = None, interval: str = "1m",
                       force: bool = False, quiet: bool = False) -> list[dict]:
    """Fetch [frm, to] from Upstox in API-sized batches, merge into candle_datas/, return the candles.
    Only the parts not fetched before are requested (force=True re-fetches everything).
    Historical only: `to` is cut to yesterday, since today's session is still forming."""
    if up is None:
        async with Upstox() as up_:
            return await fetch_broker(instrument, ce_pe_strikeprice_expiry, frm, to, up=up_,
                                      interval=interval, force=force, quiet=quiet)
    opt = parse_option(ce_pe_strikeprice_expiry)
    yesterday = datetime.now(IST).date() - timedelta(days=1)
    if opt:
        to = min(to, opt[2])                              # no bars after the contract expires
    if to > yesterday:
        to = yesterday
        if not quiet:
            print(f"  'to' cut to {to}: only closed sessions are fetched")
    if frm > to:
        return []

    path = candle_file(instrument, ce_pe_strikeprice_expiry, interval)
    blob = _load(path)
    if opt is None:
        key, kind, symbol = await underlying_key(up, instrument), "index", instrument.upper()
    else:
        ot, strike, expiry = opt
        match = [c for c in await contracts(up, instrument, expiry) if c["strike"] == strike and c["type"] == ot]
        if not match:
            raise LookupError(f"no {instrument} contract {option_name(*opt)}")
        c = match[0]
        key, kind, symbol = c["instrument_key"], ("expired" if c["expired"] else "live"), c["trading_symbol"]
    if blob is None:
        blob = {"instrument": instrument.upper(), "option": option_name(*opt) if opt else None,
                "instrument_key": key, "trading_symbol": symbol, "interval": interval,
                "fetched": [], "candles": []}

    todo = [(frm, to)] if force else gaps(frm, to, blob["fetched"])
    by_ts = {r[0]: r for r in blob["candles"]}
    for ga, gb in todo:
        for a, b in batches(ga, gb, MAX_RANGE[kind]):
            raw = await _get_candles(up, key, kind, interval, a, b)
            for r in raw:
                if len(r) >= 5:
                    by_ts[r[0]] = [r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                                   int(r[5]) if len(r) > 5 else 0, int(r[6]) if len(r) > 6 else 0]
            blob["candles"] = [by_ts[t] for t in sorted(by_ts)]
            blob["fetched"] = _merge_ranges(blob["fetched"] + [[a.isoformat(), b.isoformat()]])
            _save(path, blob)                               # after every batch: resumable
            if not quiet:
                print(f"  {os.path.basename(path)}  {a}..{b}: {len(raw)} candles")
    return fetch(instrument, ce_pe_strikeprice_expiry, frm, to, interval, warn=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _stats(up: Upstox) -> str:
    lat = up.latencies
    avg = f", avg {statistics.mean(lat) * 1000:.0f} ms/call" if lat else ""
    return f"api calls: {up.calls}{avg}, throttled {up.throttled}, paced {up.paced:.0f}s"


async def _main() -> None:
    ap = argparse.ArgumentParser(description="Fetch candles / expiries from Upstox into candle_datas/")
    ap.add_argument("what", choices=["candles", "expiries"])
    ap.add_argument("instrument")
    ap.add_argument("--opt", help="CE_23000_2026-01-27 (omit for the index)")
    ap.add_argument("--from", dest="frm", required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--interval", default="1m", choices=list(INTERVALS))
    ap.add_argument("--force", action="store_true", help="re-fetch ranges already on disk")
    a = ap.parse_args()
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    async with Upstox() as up:
        if a.what == "expiries":
            exps = await fetch_expiries(a.instrument, frm, to, up)
            print(f"{len(exps)} expiries: " + ", ".join(e.isoformat() for e in exps))
        else:
            cs = await fetch_broker(a.instrument, a.opt, frm, to, up=up, interval=a.interval, force=a.force)
            days = sorted({c["timestamp"][:10] for c in cs})
            print(f"{len(cs)} candles over {len(days)} sessions"
                  + (f" ({days[0]} .. {days[-1]})" if days else "")
                  + f" -> {candle_file(a.instrument, a.opt, a.interval)}")
        print(_stats(up))


if __name__ == "__main__":
    asyncio.run(_main())
