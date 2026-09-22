"""Everything a generated strategy script needs from Upstox, plus the report writer.

A strategy script in analysis/scripts/ imports this file and contains ONLY the
strategy: decide, simulate, build trades.  Nothing is cached - every run fetches
what it needs.

    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
    from py_funcs import *

FLOW OF A SCRIPT
    async with Upstox() as up:
        und   = await up.find_instrument("Nifty 50")                 # instrument key
        info  = await up.option_chain_info(und["instrument_key"])    # expiries, strike step, lot
        cal   = await up.expiry_calendar(und["instrument_key"], frm, to)
        cs    = await up.candles(und["instrument_key"], "1m", frm, to)
        days  = sessions_from(cs)                                    # {day: [[HH:MM,o,h,l,c], ...]}
        c     = await up.resolve_option(und["instrument_key"], expiry, strike, "CE")
        rows  = await up.option_candles(c, day)                      # [[HH:MM,o,h,l,c], ...]
    trade = make_trade(...)
    payload = build_payload(meta, trades, days, {symbol: {day: rows}}, groups)
    write_report(payload, "my_strategy")                             # -> analysis/report/my_strategy.html

Sections: 1 paths  2 Upstox client (3 instruments and options, 4 candles inside it)
          5 pure helpers  6 costs  6b rules and indicators  7 trades  7b settings  7c session log  8 report
"""
from __future__ import annotations

import asyncio
import gzip
import json
import math
import os
import re
import statistics
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import httpx

# ---------------------------------------------------------------------------
# 1  paths
# ---------------------------------------------------------------------------
TEMPLATES_DIR = os.path.dirname(os.path.abspath(__file__))
ANALYSIS_DIR = os.path.abspath(os.path.join(TEMPLATES_DIR, ".."))
CONFIG_FILE = os.path.join(ANALYSIS_DIR, "upstox_config.txt")     # line 4 = access token
REPORT_DIR = os.path.join(ANALYSIS_DIR, "report")
SAMPLE_HTML = os.path.join(TEMPLATES_DIR, "sample.html")

IST = timezone(timedelta(hours=5, minutes=30), "IST")
BASE_V2 = "https://api.upstox.com/v2"
BASE_V3 = "https://api.upstox.com/v3"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"

# Short names people type -> the Upstox index name.
INDEX_ALIASES = {"NIFTY": "Nifty 50", "NIFTY50": "Nifty 50", "BANKNIFTY": "Nifty Bank",
                 "FINNIFTY": "Nifty Fin Service", "MIDCPNIFTY": "NIFTY MID SELECT",
                 "VIX": "India VIX", "SENSEX": "SENSEX"}


def read_access_token() -> str:
    """Line 4 of analysis/upstox_config.txt.  Run connect_upstox.py to refresh it."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            lines = [l.strip() for l in f.read().splitlines()]
    except OSError:
        raise SystemExit(f"Missing {CONFIG_FILE}. Run analysis/connect_upstox.py first.")
    if len(lines) < 4 or not lines[3]:
        raise SystemExit("No access token in upstox_config.txt (line 4). Run analysis/connect_upstox.py.")
    return lines[3]


# ---------------------------------------------------------------------------
# 1b  the candle cache - CLOSED SESSIONS ONLY, and never a guess
# ---------------------------------------------------------------------------
# The window starts at a fixed date and grows through the current IST date.  Bars from sessions
# that have already closed can never change, so caching them turns a re-run from an hour into
# seconds.
#
# Everything here exists to make the cache impossible to trust wrongly:
#
#   * ONLY past sessions.  Nothing for today or later is ever written or read - a session
#     still forming is partial, and a partial bar is not the day's bar (rule 7).
#   * NEVER an empty result.  "No bars" can mean the contract did not trade, or it can mean a
#     transient failure; the two are indistinguishable from outside, so an empty answer is
#     re-fetched every time rather than remembered as fact.
#   * EVERY read is validated: timestamps unique and ascending, OHLC consistent, all positive.
#     A row that fails is not repaired - the whole entry is dropped and re-fetched.
#   * Only what the API returned is stored.  Nothing is interpolated, filled forward, or
#     reconstructed.  A gap in the data stays a gap.
#
# `CACHE_OFF = True` (or --no-cache on a script) bypasses it entirely, and
# `verify_cache(up, n)` re-fetches a random sample and compares, so the claim is testable.

CACHE_DIR = os.path.join(ANALYSIS_DIR, "cache")
CACHE_VERSION = 1
CACHE_OFF = os.environ.get("PYFUNCS_NO_CACHE") == "1"
_CACHE_STATS = {"hit": 0, "miss": 0, "write": 0, "rejected": 0}


def _cache_path(kind: str, day: str) -> str:
    return os.path.join(CACHE_DIR, f"v{CACHE_VERSION}", kind, f"{day}.json")


def _cache_is_past(day: str) -> bool:
    """Only sessions strictly before today may be cached."""
    return day < datetime.now(IST).date().isoformat()


def _rows_ok(rows) -> bool:
    """A cached session must look exactly like what the API gives, or it is not used."""
    if not isinstance(rows, list) or not rows:
        return False
    last = ""
    for r in rows:
        if not isinstance(r, list) or len(r) != 5:
            return False
        t, o, h, l, c = r
        if not isinstance(t, str) or len(t) != 5 or t[2] != ":" or t <= last:
            return False                                  # unique and ascending
        last = t
        try:
            o, h, l, c = float(o), float(h), float(l), float(c)
        except (TypeError, ValueError):
            return False
        if min(o, h, l, c) <= 0 or l > min(o, c) or h < max(o, c) or l > h:
            return False                                  # OHLC must be consistent
    return True


def _cache_read(kind: str, day: str, key: str):
    if CACHE_OFF or not _cache_is_past(day):
        return None
    path = _cache_path(kind, day)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            blob = json.load(f)
    except (OSError, ValueError):
        return None
    rows = blob.get(key)
    if rows is None:
        return None
    if not _rows_ok(rows):
        _CACHE_STATS["rejected"] += 1
        return None
    _CACHE_STATS["hit"] += 1
    return [[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in rows]


def _cache_write(kind: str, day: str, key: str, rows: list) -> None:
    if CACHE_OFF or not _cache_is_past(day) or not rows or not _rows_ok(rows):
        return                                            # never cache empty, never cache today
    path = _cache_path(kind, day)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    blob = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                blob = json.load(f)
        except (OSError, ValueError):
            blob = {}
    blob[key] = rows
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(blob, f, separators=(",", ":"))
    os.replace(tmp, path)                                 # atomic: no half-written file
    _CACHE_STATS["write"] += 1


def cache_stats() -> str:
    t = _CACHE_STATS
    return (f"cache: {t['hit']} hits, {t['miss']} misses, {t['write']} written"
            + (f", {t['rejected']} REJECTED as invalid" if t["rejected"] else ""))


async def verify_cache(up: "Upstox", sample: int = 12) -> str:
    """Re-fetch a random sample of cached sessions and compare, bar for bar.  The cache is only
    worth having if this passes, so run it whenever the cache is doubted."""
    import random
    root = os.path.join(CACHE_DIR, f"v{CACHE_VERSION}", "opt1m")
    if not os.path.isdir(root):
        return "no cache to verify"
    files = [f for f in os.listdir(root) if f.endswith(".json")]
    random.shuffle(files)
    checked = bad = 0
    for fn in files:
        if checked >= sample:
            break
        day = fn[:-5]
        with open(os.path.join(root, fn), encoding="utf-8") as f:
            blob = json.load(f)
        for ikey, rows in list(blob.items())[:2]:
            if checked >= sample:
                break
            live = await up.option_candles({"instrument_key": ikey, "expired": True},
                                           date.fromisoformat(day))
            checked += 1
            if live != rows:
                bad += 1
                print(f"  MISMATCH {day} {ikey}: cached {len(rows)} rows, live {len(live)} rows")
    return f"verified {checked} cached sessions against a live fetch: {checked - bad} identical, {bad} MISMATCHED"


# ---------------------------------------------------------------------------
# 2  Upstox client
# ---------------------------------------------------------------------------
class Upstox:
    """One httpx client, a rate limit and retry.  Use as `async with Upstox() as up:`."""

    # Upstox meters per second, per minute AND per half hour, and a breach of the long window
    # puts the whole account in a penalty box for minutes - no amount of retrying gets through.
    # A ladder is thousands of calls, so the client PACES ITSELF to stay inside every window
    # rather than sprinting and then failing.  Set a little under the published caps.
    RATE_LIMITS = ((1.0, 20), (60.0, 220), (1800.0, 880))      # (window seconds, max calls)
    MAX_INTERVAL = 4.0          # the slowest the adaptive gap will go
    COOLDOWN = 75.0             # a 429 means a window is spent; wait it out, do not hammer
    MAX_COOLDOWN = 240.0        # ... but never trust a server-supplied Retry-After blindly

    def __init__(self, token: str | None = None, min_interval: float = 0.25) -> None:
        self.token = token or read_access_token()
        self._min_interval = min_interval
        self._next_at = 0.0
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        self._instruments: dict[str, list[dict]] = {}          # exchange -> rows (this run only)
        self._expired_contracts: dict[tuple[str, str], list[dict]] = {}
        self._bars: dict[tuple[str, str, int], list[list]] = {}   # (key, day, interval) -> rows
        self._times: list[float] = []      # when recent calls went out, for the rolling windows
        self._said_pacing = False
        self.calls = 0
        self.throttled = 0
        self.paced = 0.0                   # seconds spent waiting for a window to clear

    async def __aenter__(self) -> "Upstox":
        self._client = httpx.AsyncClient(timeout=60.0)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    async def get(self, url: str, params: dict | None = None, *, retries: int = 8) -> dict:
        """GET with the bearer token; retries 429 and 5xx with backoff.

Pacing happens in `_slot` before the
        call goes out; this handles the case where it was not enough.  A 429 means a whole
        window is spent, so the run waits `Retry-After` (or COOLDOWN) rather than retrying into
        the same wall, and permanently widens its own gap.  A ladder of a few thousand calls
        used to die on `UDAPI10005 Too Many Request Sent`; the point of a backtest is to finish
        slowly, not to fail fast."""
        assert self._client, "use `async with Upstox() as up:`"
        delay = 2.0
        for attempt in range(retries + 1):
            await self._slot()
            try:
                r = await self._client.get(url, params=params, headers={
                    "Accept": "application/json", "Authorization": f"Bearer {self.token}"})
            except httpx.RequestError as exc:
                if attempt == retries:
                    raise RuntimeError(f"network error for {url}: {exc}") from exc
                await asyncio.sleep(delay); delay *= 2
                continue
            self.calls += 1
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                raise PermissionError("Upstox token expired or unauthorised. Run analysis/connect_upstox.py.")
            if r.status_code == 429:
                self.throttled += 1
                self._min_interval = min(self.MAX_INTERVAL, self._min_interval * 1.5)
                after = r.headers.get("Retry-After")
                pause = float(after) if (after or "").replace(".", "", 1).isdigit() else self.COOLDOWN
                pause = min(pause, self.MAX_COOLDOWN)
                if attempt < retries:
                    print(f"  rate limited ({self.throttled}), try {attempt + 1}/{retries} - cooling down "
                          f"{pause:.0f}s, then {self._min_interval:.2f}s between calls", flush=True)
                    self._times = []            # the window is spent; start counting again after the wait
                    await asyncio.sleep(pause)
                    continue
            if r.status_code in (500, 502, 503, 504) and attempt < retries:
                await asyncio.sleep(delay); delay = min(delay * 2, 60.0)
                continue
            raise RuntimeError(f"Upstox HTTP {r.status_code} for {url}: {r.text[:200]}")
        raise RuntimeError(f"exhausted retries for {url}")

    async def _slot(self) -> None:
        """Block until a call may go out under every rolling window, then book the slot."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            longest = self.RATE_LIMITS[-1][0]
            while True:
                now = loop.time()
                self._times = [t for t in self._times if now - t <= longest]
                wait = self._next_at - now
                for win, cap in self.RATE_LIMITS:
                    inwin = [t for t in self._times if now - t <= win]
                    if len(inwin) >= cap:
                        wait = max(wait, inwin[-cap] + win - now)
                if wait <= 0:
                    self._times.append(now)
                    self._next_at = now + self._min_interval
                    return
                if wait > 20 and not self._said_pacing:
                    self._said_pacing = True
                    print(f"  pacing: waiting {wait:.0f}s for a rate-limit window to clear", flush=True)
                self.paced += min(wait, 10.0)
                await asyncio.sleep(min(wait, 10.0))

    # -----------------------------------------------------------------------
    # 3  instruments and options
    # -----------------------------------------------------------------------
    async def instruments(self, exchange: str = "NSE") -> list[dict]:
        """The public instrument master for one exchange (NSE, BSE, MCX ...).
        Live instruments only; fetched once per run.  Rows carry segment, name,
        trading_symbol, instrument_key, instrument_type, lot_size, strike_price,
        expiry (epoch ms), underlying_symbol, underlying_key."""
        if exchange not in self._instruments:
            assert self._client
            r = await self._client.get(INSTRUMENTS_URL.format(exchange=exchange))
            r.raise_for_status()
            self._instruments[exchange] = json.loads(gzip.decompress(r.content))
        return self._instruments[exchange]

    async def find_instrument(self, query: str, segment: str | None = None,
                              exchange: str = "NSE") -> dict:
        """The instrument whose trading symbol or name equals `query` (case-blind).

        `find_instrument("NIFTY")`                    -> the Nifty 50 index (NSE_INDEX)
        `find_instrument("RELIANCE", "NSE_EQ")`       -> the equity
        `segment` is one of NSE_INDEX, NSE_EQ, NSE_FO ...; without it indices win, then
        equities.  Raises with the closest candidates when nothing matches, so a typo is
        obvious instead of silently picking something else."""
        q = INDEX_ALIASES.get(query.upper().replace(" ", ""), query).lower()
        rows = await self.instruments(exchange)
        order = [segment] if segment else ["NSE_INDEX", "NSE_EQ"]
        for seg in order:
            for r in rows:
                if r.get("segment") == seg and q in (str(r.get("trading_symbol", "")).lower(),
                                                     str(r.get("name", "")).lower()):
                    return {k: r.get(k) for k in ("instrument_key", "trading_symbol", "name", "segment",
                                                  "instrument_type", "lot_size", "exchange")}
        near = sorted({f"{r['segment']}|{r.get('trading_symbol')}" for r in rows
                       if q.split()[0] in str(r.get("trading_symbol", "")).lower()
                       and r.get("segment") in ("NSE_INDEX", "NSE_EQ")})[:8]
        raise LookupError(f"No instrument matching {query!r}. Closest: {near or 'none'}")

    async def option_chain_info(self, underlying_key: str) -> dict:
        """What the LIVE option chain of an underlying looks like:
        {expiries: [date...], strike_step, lot_size, strikes, contracts}.
        strike_step is the most common gap between adjacent strikes near the money's
        expiry (NIFTY 50, BANKNIFTY 100, ...), so it is read, never assumed."""
        data = await self.get(f"{BASE_V2}/option/contract", {"instrument_key": underlying_key})
        cs = data.get("data") or []
        if not cs:
            raise LookupError(f"No live option contracts for {underlying_key}")
        expiries = sorted({date.fromisoformat(str(c["expiry"])[:10]) for c in cs})
        near = [c for c in cs if str(c["expiry"])[:10] == expiries[0].isoformat()]
        strikes = sorted({float(c["strike_price"]) for c in near})
        gaps = [b - a for a, b in zip(strikes, strikes[1:])]
        step = max(set(gaps), key=gaps.count) if gaps else None
        return {"expiries": expiries, "strike_step": step, "lot_size": int(cs[0].get("lot_size") or 0),
                "strikes": strikes, "contracts": cs}

    async def expiry_calendar(self, underlying_key: str, frm: date, to: date) -> list[date]:
        """Every option expiry from a week before `frm` to a month after `to`:
        the expired ones (expired-instruments API) plus the live ones."""
        out: set[date] = set()
        try:
            d = await self.get(f"{BASE_V2}/expired-instruments/expiries", {"instrument_key": underlying_key})
            out |= {date.fromisoformat(s) for s in d.get("data") or []}
        except RuntimeError as exc:
            print(f"  ! expired expiries unavailable ({exc})")
        try:
            out |= set((await self.option_chain_info(underlying_key))["expiries"])
        except (RuntimeError, LookupError) as exc:
            print(f"  ! live expiries unavailable ({exc})")
        return sorted(e for e in out if frm - timedelta(days=7) <= e <= to + timedelta(days=30))

    async def resolve_option(self, underlying_key: str, expiry: date, strike: float,
                             option_type: str) -> dict | None:
        """The contract for (expiry, strike, CE|PE) or None.  Live contracts come from
        /option/contract, past ones from /expired-instruments/option/contract; the
        instrument key differs (an expired one carries a date suffix), which is why
        `expired` is returned and must be passed on to `option_candles`."""
        ek = expiry.isoformat()
        if expiry >= datetime.now(IST).date():
            ck = (underlying_key, "live")
            if ck not in self._expired_contracts:
                d = await self.get(f"{BASE_V2}/option/contract", {"instrument_key": underlying_key})
                self._expired_contracts[ck] = d.get("data") or []
            pool, expired = [c for c in self._expired_contracts[ck] if str(c["expiry"])[:10] == ek], False
        else:
            ck = (underlying_key, ek)
            if ck not in self._expired_contracts:
                d = await self.get(f"{BASE_V2}/expired-instruments/option/contract",
                                   {"instrument_key": underlying_key, "expiry_date": ek})
                self._expired_contracts[ck] = d.get("data") or []
            pool, expired = self._expired_contracts[ck], True
        for c in pool:
            if float(c.get("strike_price", 0)) == float(strike) and c.get("instrument_type") == option_type:
                return {"trading_symbol": c["trading_symbol"], "instrument_key": c["instrument_key"],
                        "expired": expired, "lot_size": int(c.get("lot_size") or 0),
                        "expiry": ek, "strike": float(strike), "option_type": option_type}
        return None

    # -----------------------------------------------------------------------
    # 4  candles
    # -----------------------------------------------------------------------
    async def candles(self, instrument_key: str, interval: str, frm: date, to: date) -> list[dict]:
        """OHLCV candles for any interval ('1m','3m','5m','15m','30m','1h','1d'), oldest
        first.  Upstox caps one request at a month (<=15m) or a quarter (30m, 1h), so the
        range is chunked.  Today's candles are added from the intraday endpoint for
        minute intervals, because the historical endpoint does not serve the current day.
        Each item: {timestamp, open, high, low, close, volume, oi}."""
        unit, n = _interval_unit(interval)
        key = quote(instrument_key, safe="")
        out: dict[str, dict] = {}
        today = datetime.now(IST).date()
        cur = frm
        while cur <= min(to, today - timedelta(days=1) if unit == "minutes" else to):
            end = min(_chunk_end(interval, cur), to, today - timedelta(days=1) if unit == "minutes" else to)
            d = await self.get(f"{BASE_V3}/historical-candle/{key}/{unit}/{n}/{end.isoformat()}/{cur.isoformat()}")
            for raw in (d.get("data") or {}).get("candles") or []:
                c = _candle(raw)
                if c:
                    out[c["timestamp"]] = c
            cur = end + timedelta(days=1)
        if unit == "minutes" and frm <= today <= to:
            d = await self.get(f"{BASE_V3}/historical-candle/intraday/{key}/{unit}/{n}")
            for raw in (d.get("data") or {}).get("candles") or []:
                c = _candle(raw)
                if c and frm.isoformat() <= c["timestamp"][:10] <= to.isoformat():
                    out[c["timestamp"]] = c
        return [out[k] for k in sorted(out)]

    async def option_candles(self, contract: dict, day: date, interval_minutes: int = 1) -> list[list]:
        """One session of an option contract as [[HH:MM, o, h, l, c], ...] ([] if it did not trade).
        `contract` is what `resolve_option` returned.

        Memoised for THIS RUN only (nothing on disk, so rule 15 holds): a strike ladder asks for
        the same contract-day over and over, because one night's exit day is the next night's
        entry day and neighbouring nights often land on the same strike.  The same URL returns
        the same bytes, so the memo cannot go stale the way a disk cache could - and it roughly
        halves the number of calls, which is what keeps the run under the rate limit."""
        key = quote(contract["instrument_key"], safe="")
        d_ = day.isoformat()
        memo = (contract["instrument_key"], d_, interval_minutes)
        if memo in self._bars and day != datetime.now(IST).date():
            return self._bars[memo]
        if interval_minutes == 1:
            hit = _cache_read("opt1m", d_, contract["instrument_key"])
            if hit is not None:
                self._bars[memo] = hit
                return hit
            _CACHE_STATS["miss"] += 1
        if contract["expired"]:
            url = f"{BASE_V2}/expired-instruments/historical-candle/{key}/{interval_minutes}minute/{d_}/{d_}"
        else:
            url = f"{BASE_V3}/historical-candle/{key}/minutes/{interval_minutes}/{d_}/{d_}"
            if day == datetime.now(IST).date():
                url = f"{BASE_V3}/historical-candle/intraday/{key}/minutes/{interval_minutes}"
        d = await self.get(url)
        raw = (d.get("data") or {}).get("candles") or []
        rows = sorted([c[0][11:16], float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                      for c in raw if len(c) >= 5)
        self._bars[memo] = rows
        if interval_minutes == 1:
            _cache_write("opt1m", d_, contract["instrument_key"], rows)
        return rows


def _interval_unit(interval: str) -> tuple[str, int]:
    m = re.fullmatch(r"(\d+)([mhdw])", interval)
    if not m:
        raise ValueError(f"interval {interval!r}: use e.g. 1m 5m 15m 30m 1h 1d")
    return {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[m.group(2)], int(m.group(1))


def _chunk_end(interval: str, cur: date) -> date:
    unit, n = _interval_unit(interval)
    if unit == "minutes" and n <= 15:                            # one calendar month
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        return nxt - timedelta(days=1)
    if unit in ("minutes", "hours"):                             # one calendar quarter
        qm = ((cur.month - 1) // 3 + 1) * 3
        nxt = date(cur.year + (qm == 12), qm % 12 + 1, 1)
        return nxt - timedelta(days=1)
    return cur + timedelta(days=3650)


def _candle(raw: list) -> dict | None:
    if len(raw) < 5:
        return None
    return {"timestamp": raw[0], "open": float(raw[1]), "high": float(raw[2]), "low": float(raw[3]),
            "close": float(raw[4]), "volume": int(raw[5]) if len(raw) > 5 else 0,
            "oi": int(raw[6]) if len(raw) > 6 else 0}


# ---------------------------------------------------------------------------
# 5  pure helpers
# ---------------------------------------------------------------------------
def sessions_from(candles: list[dict]) -> dict[str, list[list]]:
    """{day: [[HH:MM, o, h, l, c], ...]} - the shape everything else in this file uses."""
    out: dict[str, list[list]] = {}
    for c in candles:
        out.setdefault(c["timestamp"][:10], []).append(
            [c["timestamp"][11:16], c["open"], c["high"], c["low"], c["close"]])
    return {d: sorted(r) for d, r in sorted(out.items())}


def resample(rows: list[list], minutes: int, start: str = "09:15") -> list[list]:
    """Group 1-minute rows into `minutes`-minute bars anchored at `start`."""
    s0 = int(start[:2]) * 60 + int(start[3:])
    buckets: dict[int, list[list]] = {}
    for r in rows:
        m = int(r[0][:2]) * 60 + int(r[0][3:])
        buckets.setdefault((m - s0) // minutes, []).append(r)
    out = []
    for k in sorted(buckets):
        b = buckets[k]
        t = s0 + k * minutes
        out.append([f"{t // 60:02d}:{t % 60:02d}", b[0][1], max(x[2] for x in b),
                    min(x[3] for x in b), b[-1][4]])
    return out


def atm_strike(spot: float, step: float) -> float:
    return float(round(spot / step) * step)


def strike_offset(spot: float, step: float, steps: int, option_type: str, itm: bool = True) -> float:
    """ATM moved `steps` strikes: in the money for a CE is BELOW spot, for a PE ABOVE."""
    atm = atm_strike(spot, step)
    sign = -1 if option_type == "CE" else 1
    return atm + (sign if itm else -sign) * steps * step


def next_expiry(expiries: list[date], day: date, min_days_after: int = 0) -> date | None:
    """First expiry at least `min_days_after` days after `day` (0 = may be today)."""
    return next((e for e in sorted(expiries) if (e - day).days >= min_days_after), None)


def hhmm_minutes(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:])


def bar_at(rows: list[list], hhmm: str, tolerance: int = 3, direction: int = -1) -> list | None:
    """The bar for `hhmm`, else the nearest one within `tolerance` minutes
    (direction -1 looks earlier, +1 later)."""
    by = {r[0]: r for r in rows}
    m0 = hhmm_minutes(hhmm)
    for k in range(0, tolerance + 1):
        m = m0 + k * direction
        key = f"{m // 60:02d}:{m % 60:02d}"
        if key in by:
            return by[key]
    return None


def fill_price(bar: list, action: str, mode: str = "worst") -> float:
    """Price of a fill inside one bar [t,o,h,l,c].  action is 'buy' or 'sell'.
    'worst' = buy at the HIGH, sell at the LOW (no fill better than reality could be);
    'close' = the bar's close; 'open' = its open."""
    if mode == "close":
        return bar[4]
    if mode == "open":
        return bar[1]
    return bar[2] if action == "buy" else bar[3]


def excursion(rows: list[list], side: str, entry_px: float, t0: str, t1: str) -> tuple[float, float]:
    """(MFE, MAE) in price points between t0 and t1 inclusive: the best and worst the
    position was, versus its entry, at any bar extreme."""
    span = [r for r in rows if t0 <= r[0] <= t1]
    if not span:
        return 0.0, 0.0
    hi, lo = max(r[2] for r in span), min(r[3] for r in span)
    if side == "LONG":
        return max(hi - entry_px, 0.0), min(lo - entry_px, 0.0)
    return max(entry_px - lo, 0.0), min(entry_px - hi, 0.0)


# ---------------------------------------------------------------------------
# THE WINDOW.  Defined in one place for every strategy.
# The start is fixed; the end is the current date in exchange time (IST), evaluated whenever a
# report script starts.  No individual strategy script should define its own defaults.
# Existing HTML reports are snapshots and must be re-run to include newly available sessions.
START_DATE = date(2026, 1, 1)
END_DATE = datetime.now(IST).date()

# Keep the historical one-year guard, but never reject the shared growing default window once
# it becomes older than a year.
MAX_WINDOW_DAYS = max(366, (END_DATE - START_DATE).days)


def fetch_estimate(calls: int, limits=None) -> str:
    """How long `calls` requests will take under the rolling windows - printed before a ladder
    starts, so a run that is going to take an hour says so at the top instead of at the end."""
    limits = limits or Upstox.RATE_LIMITS
    secs = max(calls * win / cap for win, cap in limits)
    return (f"{calls} requests, about {secs / 60:.0f} min at the rate limit"
            if secs >= 90 else f"{calls} requests, under two minutes")


def check_window(frm: date, to: date, max_days: int = MAX_WINDOW_DAYS) -> None:
    """Refuse a window longer than the shared default/cap.  Fetching is the expensive part of a run - a strike
    ladder over two years is thousands of option-candle calls and gigabytes held in memory for
    charts nobody opens.  A wider run is a deliberate act: pass max_days= to allow it and say
    in meta["limits"] why."""
    if to < frm:
        raise SystemExit(f"--to {to} is before --from {frm}")
    span = (to - frm).days
    if span > max_days:
        raise SystemExit(
            f"window {frm} .. {to} is {span} days; the cap is {max_days} days. "
            f"Narrow it, or pass max_days= to check_window() and say in meta['limits'] why "
            f"this run needs more.")


def coverage(sessions: dict[str, list], frm: date, to: date, rows_per_session: int | None = None) -> dict:
    """Data-quality summary for the meta block: sessions present, weekdays with no candles
    (holidays or feed misses) and, if `rows_per_session` is given, short sessions."""
    have = set(sessions)
    gaps, d = [], frm
    while d <= to:
        if d.weekday() < 5 and d.isoformat() not in have:
            gaps.append(d.isoformat())
        d += timedelta(days=1)
    short = {k: len(v) for k, v in sessions.items() if rows_per_session and len(v) < rows_per_session}
    return {"sessions": len(have), "weekday_gaps": gaps, "short_sessions": short}


# ---------------------------------------------------------------------------
# 6  costs - options, rates in force from 2024-10-01 (change here when the schedule changes)
# ---------------------------------------------------------------------------
BROKERAGE_PER_ORDER = 20.0          # Upstox flat F&O
STT_SELL_RATE = 0.001               # on the sell-side premium turnover
EXCHANGE_RATE = 0.0003503           # NSE options, on total premium turnover
SEBI_RATE = 10.0 / 1e7              # Rs 10 per crore
STAMP_BUY_RATE = 0.00003            # on the buy-side turnover
GST_RATE = 0.18                     # on brokerage + exchange + SEBI


def option_costs(buy_turnover: float, sell_turnover: float, orders: int = 2) -> dict:
    """Charges on one completed option trade from the rupee turnover of each leg."""
    brokerage = BROKERAGE_PER_ORDER * orders
    stt = STT_SELL_RATE * sell_turnover
    exch = EXCHANGE_RATE * (buy_turnover + sell_turnover)
    sebi = SEBI_RATE * (buy_turnover + sell_turnover)
    stamp = STAMP_BUY_RATE * buy_turnover
    gst = GST_RATE * (brokerage + exch + sebi)
    return {"brokerage": brokerage, "stt": stt, "exchange": exch, "sebi": sebi, "stamp": stamp,
            "gst": gst, "total": round(brokerage + stt + exch + sebi + stamp + gst, 2)}


def option_round_trip(side: str, entry_px: float, exit_px: float, qty: int) -> float:
    """Total costs of one option trade.  side LONG = bought then sold, SHORT = sold then bought."""
    e, x = entry_px * qty, exit_px * qty
    return option_costs(e, x)["total"] if side == "LONG" else option_costs(x, e)["total"]


# ---------------------------------------------------------------------------
# 6b  Rules to Live By - enforced here so a strategy cannot drift from them
#     (the full list, with the reasons, is in RUN.md)
# ---------------------------------------------------------------------------
def candle_done_at(candle_start: str, tf: int) -> str:
    """HH:MM at which a `tf`-minute candle that started at `candle_start` is complete."""
    m = hhmm_minutes(candle_start) + tf
    return f"{m // 60:02d}:{m % 60:02d}"


def bar_after_candle(rows_1m: list[list], candle_start: str, tf: int, strict: bool = True) -> list | None:
    """RULE 2.  A signal read from a candle is acted on in the NEXT ONE-MINUTE bar after that
    candle has completed - whatever the signal timeframe (a 1m signal candle -> the next 1m
    bar; a 5m signal candle starting 09:15 -> the 1m bar starting 09:20).
    `strict` (default) returns None when that exact minute is missing, so a gap in the data
    skips the trade instead of silently filling at a later price."""
    want = candle_done_at(candle_start, tf)
    for r in rows_1m:
        if r[0] == want:
            return r
        if r[0] > want:
            return None if strict else r
    return None


def worst_fills(side: str, entry_bar: list, exit_bar: list) -> tuple[float, float]:
    """RULE 1.  Every BUY fills at its bar's HIGH, every SELL at its bar's LOW.
    LONG:  entry is a buy (entry bar high), exit is a sell (exit bar low).
    SHORT: entry is a sell (entry bar low),  exit is a buy  (exit bar high)."""
    if side == "LONG":
        return entry_bar[2], exit_bar[3]
    return entry_bar[3], exit_bar[2]


def scan_exit(bars: list[list], side: str, entry_key: str, stop: float | None = None,
              target: float | None = None, force_key: str | None = None) -> dict:
    """Walk the traded instrument's bars after entry and find the exit, obeying the rules.

    bars       [[key, o, h, l, c], ...] in time order; key is HH:MM (one day) or
               "YYYY-MM-DD HH:MM" (a trade that crosses days) - the same form as entry_key.
    entry_key  the ENTRY bar.  Checking starts with the bar after it.
    stop/target  PRICES of the traded instrument (LONG: stop below, target above; SHORT: reverse).
    force_key  a scheduled exit (e.g. 15:14): filled in that bar itself.

    A stop or target touched inside a COMPLETED bar is a signal, so RULE 2 applies: the exit
    fills in the NEXT bar.  If one bar touches both, the stop is assumed to have come first.
    Returns {"bar": fill bar | None, "reason": str, "trigger": trigger bar | None}.  bar is
    None when the trigger is the last bar available (the exit has not happened yet).
    """
    for i, r in enumerate(bars):
        if r[0] <= entry_key:
            continue
        if force_key is not None and r[0] == force_key:
            return {"bar": r, "reason": "time exit", "trigger": None}
        hit_stop = stop is not None and (r[3] <= stop if side == "LONG" else r[2] >= stop)
        hit_tgt = target is not None and (r[2] >= target if side == "LONG" else r[3] <= target)
        if hit_stop or hit_tgt:
            why = "stop" if hit_stop else "target"
            nxt = bars[i + 1] if i + 1 < len(bars) else None
            if force_key is not None and nxt is not None and nxt[0] > force_key:
                nxt = None
            return {"bar": nxt, "reason": why, "trigger": r}
    return {"bar": None, "reason": "no exit found", "trigger": None}


# ---- indicators: computed on COMPLETED candles only; index i is the signal candle ----------
def sma(v: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(v)
    s = 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n:
            s -= v[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(v: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(v)
    if len(v) < n:
        return out
    k = 2.0 / (n + 1)
    out[n - 1] = sum(v[:n]) / n
    for i in range(n, len(v)):
        out[i] = v[i] * k + out[i - 1] * (1 - k)
    return out


def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, n + 1)]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, n + 1)]
    ag, al = sum(gains) / n, sum(losses) / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag, al = (ag * (n - 1) + max(d, 0.0)) / n, (al * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def atr(rows: list[list], n: int = 14) -> list[float | None]:
    """Wilder's ATR over [t,o,h,l,c] rows."""
    out: list[float | None] = [None] * len(rows)
    if len(rows) < n:
        return out
    tr = [rows[0][2] - rows[0][3]] + [max(rows[i][2] - rows[i][3], abs(rows[i][2] - rows[i - 1][4]),
                                          abs(rows[i][3] - rows[i - 1][4])) for i in range(1, len(rows))]
    out[n - 1] = sum(tr[:n]) / n
    for i in range(n, len(rows)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def crossed_above(a: list, b: list, i: int) -> bool:
    """`a` crossed above `b` on candle i: at or below on i-1, strictly above on i."""
    return i >= 1 and None not in (a[i], b[i], a[i - 1], b[i - 1]) and a[i - 1] <= b[i - 1] and a[i] > b[i]


def crossed_below(a: list, b: list, i: int) -> bool:
    return i >= 1 and None not in (a[i], b[i], a[i - 1], b[i - 1]) and a[i - 1] >= b[i - 1] and a[i] < b[i]


def bucket(x: float | None, edges: list[float], labels: list[str]) -> str:
    """Label of the bucket x falls in.  `edges` ascending; len(labels) == len(edges) + 1.
    bucket(rsi, [30, 70], ["below 30", "30-70", "above 70"]).  None -> "n/a"."""
    if x is None:
        return "n/a"
    for e, lab in zip(edges, labels):
        if x < e:
            return lab
    return labels[-1]


# ---------------------------------------------------------------------------
# 7  trades
# ---------------------------------------------------------------------------
def make_trade(*, day: str, side: str, symbol: str, entry_time: str, entry_px: float,
               exit_time: str, exit_px: float, qty: int, exit_day: str | None = None,
               exit_reason: str = "", kind: str = "option", costs: float | None = None,
               capital: float | None = None, entry_spot: float | None = None,
               exit_spot: float | None = None, stop: float | None = None,
               target: float | None = None, mfe: float | None = None, mae: float | None = None,
               variant: dict | None = None, tags: dict | None = None,
               levels: list[dict] | None = None, note: str = "",
               option_type: str | None = None, expiry: str | None = None) -> dict:
    """One completed trade in the report's format; P&L is computed here so every strategy
    does it the same way.

    side      LONG or SHORT on the instrument actually traded (a bought PUT is LONG).
    qty       units = lots x lot size.  Take the lot size from the resolved contract
              (`contract["lot_size"]`), per trade: NIFTY was 25, then 75, now 65, and the contract
              Upstox returns for a past expiry carries the size that was in force.  Never a constant.
    expiry    the option's expiry date "YYYY-MM-DD" (`contract["expiry"]`); REQUIRED for options.
              The report derives DTE (calendar days from the trade day to expiry) from it and
              adds a DTE breakdown.
    costs     rupees; None + kind 'option' -> the standard option schedule; otherwise pass
              it (0.0 is allowed, deliberately).
    capital   rupees tied up (bought option: premium x qty; sold: margin).
    stop/target  PRICES of the traded instrument, drawn on the chart.
    entry_spot/exit_spot  the underlying index/stock price at entry and exit (the report shows
              the move); if left None, build_payload fills them from the index candles.
    variant   the parameter set that produced this trade, e.g. {"rr": "1:2", "exit": "trail"}.
              Each key becomes a FILTER in the report (with 'side'); every combination is
              computed.  Keep it to the few dimensions the user actually asked to compare.
    tags      facts about the entry/exit CONDITIONS, e.g. {"sma10": "crossed above",
              "rsi": "30-70"}.  They feed the report's custom group-bys (`groups`) and
              must be computed only from candles completed at that moment.
    levels    [{"name","price","price2"?,"from"?,"to"?}] drawn on the index chart; times are
              HH:MM on `day` or "YYYY-MM-DD HH:MM".
    option_type  'CE' or 'PE'; when kind is 'option' and this is left None it is read from the
              symbol ("NIFTY 23400 CE 15 SEP 26").  Feeds the 'option type' group-by.
    """
    if side not in ("LONG", "SHORT"):
        raise ValueError(f"side must be LONG or SHORT, got {side!r}")
    sgn = 1 if side == "LONG" else -1
    gross = round(sgn * (exit_px - entry_px) * qty, 2)
    if kind == "option" and option_type is None:
        m = re.search(r"\b(CE|PE)\b", symbol)
        option_type = m.group(1) if m else None
    if kind == "option" and not expiry:
        raise ValueError("an option trade needs expiry='YYYY-MM-DD' (from the resolved contract)")
    dte = (date.fromisoformat(expiry) - date.fromisoformat(day)).days if expiry else None
    prem_pts = round(exit_px, 2) - round(entry_px, 2)   # the traded price's own move, signed, from the prices shown
    if costs is None:
        if kind != "option":
            raise ValueError("pass costs= for a non-option trade (0.0 if you really mean none)")
        costs = option_round_trip(side, entry_px, exit_px, qty)
    return {"day": day, "exit_day": exit_day or day, "side": side, "symbol": symbol, "kind": kind,
            "entry_time": entry_time, "entry_px": round(entry_px, 2),
            "exit_time": exit_time, "exit_px": round(exit_px, 2), "qty": qty,
            "exit_reason": exit_reason, "gross": gross, "costs": round(costs, 2),
            "net": round(gross - costs, 2),
            "capital": None if capital is None else round(capital, 2),
            "option_type": option_type, "expiry": expiry, "dte": dte,
            "prem_pts": round(prem_pts, 2), "prem_pct": prem_pts / round(entry_px, 2) * 100 if entry_px else None,
            "entry_spot": entry_spot, "exit_spot": exit_spot, "stop": stop, "target": target,
            "mfe": mfe, "mae": mae, "variant": {k: str(v) for k, v in (variant or {}).items()},
            "tags": {k: str(v) for k, v in (tags or {}).items()}, "levels": levels or [], "note": note}


# ---------------------------------------------------------------------------
# 7b  settings - the strategy's own knobs, rendered as the report's control panel
# ---------------------------------------------------------------------------
# A strategy declares what a reader is allowed to change.  The template renders the
# declaration as a panel of dropdowns grouped by KIND, and the browser recomputes every
# number for the chosen combination, so "what if six strikes ITM became four" is a click
# instead of an edit and a re-run.
#
# Two MODES, because there are two different kinds of knob:
#
#   mode="sweep"   changing it changes the SIMULATION, so each value needs its own trades.
#                  The script loops `combos(SETTINGS)` and stamps every trade with
#                  `variant=combo`.  Costs one simulation (and sometimes one fetch) per value.
#                  Use for: strike depth, stop distance, the first candle an exit may fire.
#
#   mode="filter"  changing it only SELECTS among trades that already exist, by a tag.
#                  The script simulates once, tags every trade, and the browser subsets.
#                  Costs nothing.  Use for: an entry condition to switch on and off, a regime,
#                  a threshold that only ever removes trades.
#
# A filter that is "on" in the rule must still be simulated OFF: the script has to trade every
# candidate night and tag it, otherwise the only trades that exist are the ones the filter
# admits and turning it off changes nothing.
#
# The date range is built into the template - never declare it as a setting.
#
# An axis a source declares is not automatically one this rule HAS.  Check the rule, not the
# list: a family of scripts often shares one set of choices and some of them name things a
# given rule never produces.  Refuse those in meta["rejected"] with the reason - never fake
# one, never drop one in silence.

KINDS = ("entry", "exit", "strike", "sizing", "other")
KIND_LABELS = {"entry": "Entry filters", "exit": "Exit settings", "strike": "Strike / moneyness",
               "sizing": "Sizing", "other": "Other settings"}
MAX_COMBOS = 400                # sweep combinations one run may simulate.  Raised from 240 on
                                # 2026-09-21: with the candle cache a sweep of re-simulations
                                # costs compute, not fetching, and a faithful strategy needs
                                # every axis its source compares (confirm x tf x rr x stop x
                                # end-of-day x position rule x reading is already 288).
PYTHON_HINT = "analysis/.venv/Scripts/python.exe"


def setting(key: str, label: str, *, kind: str = "other", mode: str = "sweep",
            values: list | None = None, options: list[dict] | None = None,
            default=None, unit: str = "", help: str = "", rerun: bool = False) -> dict:
    """One knob in the report's control panel.

    key      short identifier; also the variant key (sweep) and the CLI flag (--<key>).
    label    what the panel shows, e.g. "Strike depth".
    kind     entry | exit | strike | sizing | other - the band it is grouped under.  The user's
             "entry filters" and "exit settings" are kind="entry" and kind="exit".
    mode     "sweep" (own simulation per value) or "filter" (selects existing trades by a tag).
    values   sweep: the values to simulate, e.g. [2, 4, 6, 8, 10].  Each becomes an option whose
             report value is str(v) - exactly what make_trade(variant=) stores, so the panel and
             the trades match without the script doing anything.
    options  filter: [{"value","label","tag":{tag_key: [allowed, ...]} | None}], one per choice.
             tag=None admits every trade (the "off" choice).  Also usable for a sweep when the
             labels should read differently from the values.
    default  the value the RULE itself uses; the panel marks it and the combination table points
             at it.  Defaults to the first option.
    unit     appended to a generated label, e.g. " strikes ITM".
    help     one line under the dropdown.
    rerun    True when a value outside the ones shipped needs new DATA (a deeper strike, a wider
             window).  The panel then offers the re-run command instead of pretending.
    """
    if kind not in KINDS:
        raise ValueError(f"setting {key!r}: kind must be one of {KINDS}, got {kind!r}")
    if mode not in ("sweep", "filter"):
        raise ValueError(f"setting {key!r}: mode must be 'sweep' or 'filter', got {mode!r}")
    if (values is None) == (options is None):
        raise ValueError(f"setting {key!r}: pass exactly one of values= or options=")
    if values is not None:
        opts = [{"value": str(v), "label": f"{v}{unit}", "raw": v, "tag": None, "var": None} for v in values]
    else:
        opts = []
        for o in options:
            o = dict(o)
            o["value"] = str(o["value"])
            o.setdefault("label", o["value"])
            o.setdefault("raw", o["value"])
            o.setdefault("tag", None)
            o.setdefault("var", None)
            opts.append(o)
    if not opts:
        raise ValueError(f"setting {key!r}: no values")
    seen = [o["value"] for o in opts]
    if len(set(seen)) != len(seen):
        raise ValueError(f"setting {key!r}: duplicate values {seen}")
    if mode == "filter" and all(o["tag"] is None and o.get("var") is None for o in opts):
        raise ValueError(f"setting {key!r}: a filter needs at least one option with a tag= or var=")
    if mode == "sweep":
        for o in opts:
            o["tag"] = None
    dflt = str(default) if default is not None else opts[0]["value"]
    if dflt not in seen:
        raise ValueError(f"setting {key!r}: default {dflt!r} is not one of {seen}")
    return {"key": key, "label": label, "kind": kind, "mode": mode, "default": dflt,
            "unit": unit, "help": help, "rerun": bool(rerun), "options": opts}


def _sweeps(settings: list[dict] | None) -> list[dict]:
    return [s for s in (settings or []) if s["mode"] == "sweep"]


def combos(settings: list[dict] | None) -> list[dict]:
    """Every combination of the SWEEP settings, as {key: raw value} - what the strategy loops.

        for c in combos(SETTINGS):
            ... simulate using c["moneyness"], c["first_exit"] ...
            trades.append(make_trade(..., variant=c))

    Filter settings are not in here: they cost nothing and are applied in the browser.
    """
    sw = _sweeps(settings)
    out: list[dict] = [{}]
    for s in sw:
        out = [{**c, s["key"]: o["raw"]} for c in out for o in s["options"]]
    if len(out) > MAX_COMBOS:
        raise ValueError(f"{len(out)} sweep combinations (> {MAX_COMBOS}): "
                         f"{[(s['key'], len(s['options'])) for s in sw]}. Narrow one with its --flag.")
    return out


def default_combo(settings: list[dict] | None) -> dict:
    """{key: raw value} for the sweep settings at their defaults - the rule's own setting."""
    return {s["key"]: next(o["raw"] for o in s["options"] if o["value"] == s["default"])
            for s in _sweeps(settings)}


def _flag(key: str) -> str:
    return "--" + key.replace("_", "-")


def settings_cli(ap, settings: list[dict] | None) -> None:
    """Add one --<key> flag per setting: a comma-separated list that NARROWS what is shipped.
    `--moneyness 4,6,8` simulates three rungs instead of the whole declared ladder."""
    for s in settings or []:
        vals = ",".join(o["value"] for o in s["options"])
        # argparse runs help through %-formatting, and a label like "move >= 0.15%" blows it up
        txt = f"{s['label']} - comma separated, from: {vals} (rule: {s['default']})".replace("%", "%%")
        ap.add_argument(_flag(s["key"]), dest=f"set_{s['key']}", default=None, help=txt)


def narrow(settings: list[dict] | None, args) -> list[dict]:
    """Apply the --<key> flags and return a new spec.  If the declared default was dropped the
    default moves to the first value kept, so 'the rule' always points at something shipped."""
    out = []
    for s in settings or []:
        want = getattr(args, f"set_{s['key']}", None)
        if not want:
            out.append(s)
            continue
        keep = [w.strip() for w in str(want).split(",") if w.strip()]
        known = {o["value"]: o for o in s["options"]}
        bad = [w for w in keep if w not in known]
        if bad:
            raise SystemExit(f"{_flag(s['key'])}: {bad} not one of {list(known)}")
        s = dict(s, options=[known[w] for w in keep])
        if s["default"] not in keep:
            s["default"] = keep[0]
        out.append(s)
    return out


def rerun_command(slug: str, settings: list[dict] | None, frm, to) -> str:
    """The exact command that reproduces this report - shown in the panel, so a setting that
    needs new data is one paste away instead of a guess."""
    parts = [PYTHON_HINT, f"analysis/scripts/{slug}.py", f"--from {frm}", f"--to {to}"]
    for s in settings or []:
        if s.get("derived"):        # inferred from variants, so the script has no such flag
            continue
        parts.append(f"{_flag(s['key'])} " + ",".join(o["value"] for o in s["options"]))
    return " ".join(parts)


def _admits(t: dict, opt: dict) -> bool:
    """Does this trade pass one filter option?  Neither tag nor var set admits everything.
    `tag` selects on what the trade was tagged with, `var` on which variant produced it - the
    second is what a PARTITION axis needs (see `_axis_shape`)."""
    if not opt:
        return True
    tag, var = opt.get("tag"), opt.get("var")
    if tag and not all(str(t["tags"].get(k)) in [str(x) for x in vals] for k, vals in tag.items()):
        return False
    if var and not all(str(t["variant"].get(k)) in [str(x) for x in vals] for k, vals in var.items()):
        return False
    return True


def check_settings(settings: list[dict] | None, trades: list[dict]) -> list[str]:
    """Warnings a strategy author wants before the report is written, not after."""
    out = []
    if not settings:
        out.append("no SETTINGS declared, so the panel was DERIVED from the variants and tags this "
                   "script already emits: the knobs work, but they carry raw keys for labels, none "
                   "is marked as the rule, and none has a CLI flag. Declare them (RUN.md rule 18, "
                   "Step 1b) next time this script is touched.")
    elif len({s["kind"] for s in settings}) < 2:
        out.append(f"every setting is kind={settings[0]['kind']!r}: RUN.md Step 1b lists five axes "
                   f"(what is traded, when it enters, when it exits, timeframe, direction) - "
                   f"say in meta['rejected'] which ones this strategy has nothing on.")
    for s in settings or []:
        if s["mode"] == "sweep":
            have = {t["variant"].get(s["key"]) for t in trades}
            missing = [o["value"] for o in s["options"] if o["value"] not in have]
            if missing:
                out.append(f"setting {s['key']!r}: no trade carries variant {missing} - "
                           f"is the script looping combos(SETTINGS) and passing variant=combo?")
        else:
            for o in s["options"]:
                for k in (o.get("var") or {}):
                    if not any(k in t["variant"] for t in trades):
                        out.append(f"setting {s['key']!r} option {o['value']!r}: no trade carries "
                                   f"the variant {k!r}")
                for k in (o.get("tag") or {}):
                    if not any(k in t["tags"] for t in trades):
                        out.append(f"setting {s['key']!r} option {o['value']!r}: no trade carries "
                                   f"the tag {k!r}")
                if (o.get("tag") or o.get("var")) and not any(_admits(t, o) for t in trades):
                    out.append(f"setting {s['key']!r} option {o['value']!r}: admits no trade at all")
    return out


# ---------------------------------------------------------------------------
# 7c  the session log - what happened on every session, traded or not
# ---------------------------------------------------------------------------
# The trades table only shows sessions that produced a trade, so a report built from trades
# alone cannot answer "what about the other days?".  A strategy therefore emits one row per
# session in the window - signal or no signal, traded, declined or skipped for bad data - and
# the report renders it as "Every session", with the skips and the declines each on their own
# tab.  The console list is for the person running the script; this is for the person reading
# the report.

STATUSES = ("traded", "declined", "no signal", "no data")


def session_row(day: str, status: str, note: str = "", **facts) -> dict:
    """One session in the log.

    day     "YYYY-MM-DD".
    status  traded    - the rule fired and at least one trade exists for this day
            declined  - the rule fired but a condition of the rule said no (a filter setting
                        turns this into a trade you can switch back on; say which in `note`)
            no signal - the rule did not fire
            no data   - a missing candle, a missing contract, a short session: the day is
                        unusable, and the report must SAY so rather than swallow it
    note    the reason, in the words the rule uses.
    facts   any extra columns - the day's move, the direction, the premium read, the share.
            They become columns of the table in first-seen order; keep them scalar.
    """
    if status not in STATUSES:
        raise ValueError(f"session {day}: status must be one of {STATUSES}, got {status!r}")
    return {"day": day, "status": status, "note": note, "facts": facts}


# ---------------------------------------------------------------------------
# 8  report - every number is computed here; the browser only picks and formats
# ---------------------------------------------------------------------------
DATA_START, DATA_END = "/*DATA_START*/", "/*DATA_END*/"
ALL = "all"
ROLL_WINDOW = 20
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
STANDARD_GROUPS = ["weekday", "week", "month", "entry hour", "exit reason"]
OPTION_GROUP = "option type"       # CE / PE - added only when the trades are options
DTE_GROUP = "DTE"                  # days to expiry at entry - added only when the trades are options
_REQUIRED_TRADE = ("day", "exit_day", "side", "symbol", "entry_time", "entry_px", "exit_time",
                   "exit_px", "qty", "gross", "costs", "net")


def _order(trs: list[dict]) -> list[dict]:
    return sorted(trs, key=lambda t: (t["exit_day"], t["exit_time"], t["day"], t["entry_time"]))


def _row(trs: list[dict]) -> dict:
    """The compact statistics block used by every table."""
    net = [t["net"] for t in trs]
    n = len(net)
    wins = sum(1 for x in net if x > 0)
    gw, gl = sum(x for x in net if x > 0), -sum(x for x in net if x < 0)
    return {"n": n, "wins": wins, "losses": n - wins, "win": wins / n * 100 if n else None,
            "net": sum(net), "gross": sum(t["gross"] for t in trs), "costs": sum(t["costs"] for t in trs),
            "mean": sum(net) / n if n else None, "pf": gw / gl if gl else None,
            "best": max(net) if n else None, "worst": min(net) if n else None}


def _book(trs: list[dict]) -> dict:
    """The full overview block for one set of trades."""
    o = _order(trs)
    r = _row(o)
    net = [t["net"] for t in o]
    n = len(net)
    sd = statistics.stdev(net) if n > 1 else None
    cum = peak = mdd = 0.0
    peak_day = mdd_from = mdd_to = None
    w = l = mw = ml = 0
    for t in o:
        cum += t["net"]
        if cum > peak:
            peak, peak_day = cum, t["exit_day"]
        if cum - peak < mdd:
            mdd, mdd_from, mdd_to = cum - peak, peak_day, t["exit_day"]
        w, l = (w + 1, 0) if t["net"] > 0 else (0, l + 1)
        mw, ml = max(mw, w), max(ml, l)
    W = [x for x in net if x > 0]
    L = [x for x in net if x <= 0]
    avg_win = sum(W) / len(W) if W else None
    avg_loss = sum(L) / len(L) if L else None
    caps = [t["capital"] for t in o if t.get("capital") is not None]
    cap_avg = sum(caps) / len(caps) if caps else None
    hold = [(datetime.fromisoformat(f"{t['exit_day']}T{t['exit_time']}")
             - datetime.fromisoformat(f"{t['day']}T{t['entry_time']}")).total_seconds() / 60 for t in o]
    r.update({"avg_win": avg_win, "avg_loss": avg_loss,
              "payoff": avg_win / abs(avg_loss) if avg_win is not None and avg_loss else None,
              "max_dd": mdd, "dd_from": mdd_from, "dd_to": mdd_to, "win_streak": mw, "loss_streak": ml,
              "t": statistics.fmean(net) / (sd / math.sqrt(n)) if sd else None,
              "cap_avg": cap_avg, "roc": r["net"] / cap_avg * 100 if cap_avg else None,
              "hold_min": sum(hold) / n if n else None, "sessions": len({t["day"] for t in o})})
    return r


def _series(trs: list[dict]) -> dict:
    """Trade 1 .. last: cumulative net, drawdown from the running peak, rolling win rate."""
    o = _order(trs)
    eq, dd, cum, peak = [], [], 0.0, 0.0
    for t in o:
        cum += t["net"]
        peak = max(peak, cum)
        eq.append(cum)
        dd.append(cum - peak)
    roll = [sum(1 for t in o[i - ROLL_WINDOW + 1:i + 1] if t["net"] > 0) / ROLL_WINDOW * 100
            for i in range(ROLL_WINDOW - 1, len(o))]
    return {"x": [t["exit_day"] for t in o], "equity": eq, "drawdown": dd, "rolling": roll,
            "roll_window": ROLL_WINDOW}


def _group_label(t: dict, kind: str) -> str:
    if kind == "weekday":
        return WEEKDAYS[date.fromisoformat(t["day"]).weekday()]
    if kind == "week":
        y, w, _ = date.fromisoformat(t["day"]).isocalendar()
        return f"{y}-W{w:02d}"
    if kind == "month":
        return t["day"][:7]
    if kind == "entry hour":
        return t["entry_time"][:2] + ":00"
    if kind == "exit reason":
        return t.get("exit_reason") or "-"
    if kind == OPTION_GROUP:
        return t.get("option_type") or "-"
    if kind == DTE_GROUP:
        return "-" if t.get("dte") is None else f"{t['dte']} DTE"
    raise KeyError(kind)


def _groups(trs: list[dict], custom: list[dict], standard: list[str]) -> dict:
    """{group name: [{key, ...row}]}.  Standard groups first, then the user's own: each custom
    group is a list of tag keys; its bucket is the combination of those tags' values, so one
    key gives a single-indicator bucket and several give a multi-indicator bucket."""
    out: dict[str, list] = {}
    for kind in standard:
        g: dict[str, list] = {}
        for t in trs:
            g.setdefault(_group_label(t, kind), []).append(t)
        if kind == "weekday":
            keys = sorted(g, key=WEEKDAYS.index)
        elif kind == DTE_GROUP:
            keys = sorted(g, key=lambda k: int(k.split()[0]) if k[0].isdigit() else 10 ** 6)
        else:
            keys = sorted(g)
        out[kind] = [{"key": k, **_row(g[k])} for k in keys]
    for c in custom:
        g = {}
        for t in trs:
            g.setdefault(" | ".join(t["tags"].get(k, "n/a") for k in c["keys"]), []).append(t)
        out[c["name"]] = [{"key": k, **_row(g[k])} for k in sorted(g)]
    return out


def _stability(trs: list[dict], break_date: str | None = None) -> list[dict]:
    """Does the result survive being cut up?  Halves, thirds, quarters by trade ORDER, each
    with its date range, then the book with the best 10% and the worst 10% of trades removed
    (10% rounded UP to a whole trade), then the same by the CALENDAR - year and calendar half.
    Order slices answer "did it decay"; calendar slices answer "which period paid", and they
    are not the same cut when trades are unevenly spread."""
    o = _order(trs)
    n = len(o)
    rows: list[dict] = []

    def add(label, ts, note=""):
        a = min((t["day"] for t in ts), default=None)
        b = max((t["exit_day"] for t in ts), default=None)
        rows.append({"label": label, "from": a, "to": b, "note": note, **_row(ts)})

    def cut(parts, names):
        for k, name in enumerate(names):
            add(name, o[k * n // parts:(k + 1) * n // parts])

    add("all trades", o)
    if n >= 4:
        cut(2, ["first half", "second half"])
    if n >= 6:
        cut(3, ["first third", "second third", "last third"])
    if n >= 8:
        cut(4, ["first quarter", "second quarter", "third quarter", "last quarter"])
    if n >= 10:
        k = math.ceil(n * 0.10)
        s = sorted(range(n), key=lambda i: o[i]["net"])
        worst, best = set(s[:k]), set(s[-k:])
        add("without best 10%", [t for i, t in enumerate(o) if i not in best], f"{k} best trades removed")
        add("without worst 10%", [t for i, t in enumerate(o) if i not in worst], f"{k} worst trades removed")
    if break_date:
        for lab, keep in ((f"before {break_date}", lambda t: t["day"] < break_date),
                          (f"from {break_date}", lambda t: t["day"] >= break_date)):
            sel = [t for t in o if keep(t)]
            if sel:
                add(lab, sel, "across the named break")
    for label, keyf in (("year", lambda t: t["day"][:4]),
                        ("half", lambda t: f"{t['day'][:4]} H{1 if t['day'][5:7] <= '06' else 2}")):
        g: dict[str, list] = {}
        for t in o:
            g.setdefault(keyf(t), []).append(t)
        if len(g) > 1:
            for k2 in sorted(g):
                add(k2, g[k2], f"by {label}")
    return rows


FILL_MODES = [
    ("worst", "worst - buy the bar's HIGH, sell its LOW"),
    ("mid", "midpoint of the bar"),
    ("close", "the bar's close - NOT achievable, for comparison only"),
]


def _bar_at(rows: list[list], hhmm: str) -> list | None:
    for r in rows or []:
        if r[0] == hhmm:
            return r
    return None


def _price_fills(trades: list[dict], index: dict, option_sessions: dict | None) -> int:
    """Re-price every trade at the midpoint and at the close of the SAME bars it already used.

    The fill convention is the single biggest lever on an option backtest and it is usually
    invisible: a rule can read as -Rs 89k at the worst fill and +Rs 91k at the close, on
    identical trades, because the exit bar is the opening minute and 57 points wide.  The
    source reports made it a dropdown, so the template does too - for every strategy, with no
    extra fetching, because both prices are already in the bar.

    `worst` stays the default and the rule (RUN.md rule 1).  The others are labelled as what
    they are: a sensitivity check, not a result you could have traded."""
    opt = option_sessions or {}
    done = 0
    for t in trades:
        src = opt.get(t["symbol"]) if t.get("kind") == "option" else None
        if src is None:
            src = index
        e = _bar_at((src or {}).get(t["day"]), t["entry_time"])
        x = _bar_at((src or {}).get(t["exit_day"]), t["exit_time"])
        if not e or not x:
            continue
        sgn = 1 if t["side"] == "LONG" else -1
        out = {"worst": {"entry_px": t["entry_px"], "exit_px": t["exit_px"], "gross": t["gross"],
                         "costs": t["costs"], "net": t["net"]}}
        for mode, ep, xp in (("mid", (e[2] + e[3]) / 2, (x[2] + x[3]) / 2), ("close", e[4], x[4])):
            ep, xp = round(ep, 2), round(xp, 2)
            gross = round(sgn * (xp - ep) * t["qty"], 2)
            costs = (round(option_round_trip(t["side"], ep, xp, t["qty"]), 2)
                     if t.get("kind") == "option" else t["costs"])
            out[mode] = {"entry_px": ep, "exit_px": xp, "gross": gross, "costs": costs,
                         "net": round(gross - costs, 2),
                         "prem_pts": round(xp - ep, 2),
                         "prem_pct": (xp - ep) / ep * 100 if ep else None}
        out["worst"]["prem_pts"] = t["prem_pts"]
        out["worst"]["prem_pct"] = t["prem_pct"]
        t["fills"] = out
        done += 1
    return done


def _sides(trades: list[dict]) -> list[str]:
    return sorted({t["side"] for t in trades})


# Guessing a band from a variant key, for scripts that predate SETTINGS.  Crude on purpose:
# a wrong band is cosmetic, and declaring the setting properly (Step 1b) overrides it.
_KIND_HINTS = (
    ("strike", ("moneyness", "strike", "itm", "otm", "depth")),
    ("exit", ("rr", "r:r", "target", "stop", "exit", "trail", "tp", "sl", "hold")),
    ("entry", ("entry", "decision", "signal", "trigger", "time", "delay", "filter")),
    ("sizing", ("lot", "size", "qty", "book", "capital")),
)
DERIVE_MAX_FILTER_VALUES = 6      # a tag with more values than this is a group-by, not a knob
DERIVE_MAX_COMBOS = 600           # stop adding derived filters before the panel becomes a maze


def _guess_kind(key: str) -> str:
    k = key.lower()
    for kind, words in _KIND_HINTS:
        if any(w in k for w in words):
            return kind
    return "other"


def _axis_shape(trades: list[dict], key: str) -> str:
    """Is a variant key a SWEEP or a PARTITION?

    A sweep re-prices THE SAME SESSION under a different parameter, so a day shows up under
    every value (R:R, stop rule, strike depth, timeframe).  A partition splits the sessions
    themselves - a day is a gap-up or a gap-down, a long or a short, never both - so the
    values are disjoint and together they are ONE book.

    It matters because the panel treats them differently.  A sweep must not offer "all",
    because pooling a night's 1:2 and 1:3 versions is not a book.  A partition MUST offer
    "any", because refusing to means the report can never show the strategy as it actually
    trades - which is what happened when a two-direction rule opened showing one direction
    and a third of its trades.  The test is the trades themselves, so no script has to declare
    it and no strategy's nature is changed by the report."""
    byval: dict[str, set] = {}
    for t in trades:
        byval.setdefault(t["variant"][key], set()).add(t["day"])
    if len(byval) < 2:
        return "sweep"
    shared = set.intersection(*byval.values())
    union = set().union(*byval.values())
    return "sweep" if len(shared) > 0.2 * len(union) else "partition"


def _one_to_one(trades: list[dict], vkey: str, tkey: str) -> bool:
    """Do a variant key and a tag key carry the same fact?  Two dropdowns for one thing is
    worse than none: set them to disagreeing values and the report shows nothing."""
    fwd: dict[str, set] = {}
    rev: dict[str, set] = {}
    for t in trades:
        x, y = t["variant"].get(vkey), t["tags"].get(tkey)
        fwd.setdefault(x, set()).add(y)
        rev.setdefault(y, set()).add(x)
    return len(fwd) > 1 and all(len(v) == 1 for v in fwd.values()) and all(len(v) == 1 for v in rev.values())


def _derive_settings(trades: list[dict]) -> list[dict]:
    """Build a panel for a script that declares no SETTINGS, from what it already emits.

    Every `variant` key becomes a SWEEP (it already is one - the script simulated each value).
    Every `tag` with a handful of values becomes a FILTER with an "any" option, because a tag
    describes the condition at entry (rule 12) and "what if I only took the trades where this
    was true" is the question a reader asks next.  Filters are added cheapest-first and stop
    before the combination count gets silly; the rest stay as group-bys, where they already are.

    This is a floor, not a substitute for Step 1b: labels are the raw keys, nothing is marked
    as the rule, and the CLI has no flags for them.  `check_settings` says so."""
    vals_of: dict[str, list[str]] = {}
    for t in trades:
        for k, v in t["variant"].items():
            if v not in vals_of.setdefault(k, []):
                vals_of[k].append(v)
    vals_of = {k: v for k, v in vals_of.items() if len(v) > 1}
    shape = {k: _axis_shape(trades, k) for k in vals_of}

    tags: dict[str, list[str]] = {}
    for t in trades:
        for k, v in t["tags"].items():
            if v not in tags.setdefault(k, []):
                tags[k].append(v)
    # a tag that repeats a variant is dropped, and lends the variant its nicer name
    twin = {}
    for vk in vals_of:
        for tk in list(tags):
            if _one_to_one(trades, vk, tk):
                twin.setdefault(vk, tk)
                tags.pop(tk, None)

    out = []
    combos_so_far = 1
    for k, vals in vals_of.items():
        label = twin.get(k, k)
        if shape[k] == "sweep":
            out.append(dict(setting(k, label, kind=_guess_kind(k), mode="sweep", values=vals), derived=True))
        else:
            out.append(dict(setting(
                k, label, kind=_guess_kind(twin.get(k, k)), mode="filter", default="any",
                help="these are disjoint sets of sessions, not alternative runs, so they are one "
                     "book and 'any' is the strategy as it trades",
                options=[{"value": "any", "label": "any", "tag": None, "var": None}]
                        + [{"value": v, "label": v, "var": {k: [v]}} for v in vals]), derived=True))
        combos_so_far *= len(out[-1]["options"])

    usable = [(len(v), k, v) for k, v in tags.items() if 2 <= len(v) <= DERIVE_MAX_FILTER_VALUES]
    for _, k, vals in sorted(usable):                      # fewest values first
        if combos_so_far * (len(vals) + 1) > DERIVE_MAX_COMBOS:
            continue
        out.append(dict(setting(
            k, k, kind="entry", mode="filter", default="any",
            help="derived from the trade tag; declare it in SETTINGS to give it a proper name",
            options=[{"value": "any", "label": "any", "tag": None}]
                    + [{"value": v, "label": v, "tag": {k: [v]}} for v in sorted(vals)]), derived=True))
        combos_so_far *= len(vals) + 1
    return out


def build_payload(meta: dict, trades: list[dict], index_sessions: dict[str, list[list]],
                  option_sessions: dict[str, dict[str, list[list]]] | None = None,
                  groups: list[dict] | None = None, settings: list[dict] | None = None,
                  chart: str = "default", sessions_log: list[dict] | None = None) -> dict:
    """Assemble what the HTML reads.

    meta      title, subtitle, instrument, from, to, lot_size, fill_rule, cost_model,
              params {name: value}, rule_steps [str], limits [str], coverage (from `coverage()`).
    trades    from make_trade().
    index_sessions   {day: rows}, full sessions; only the days trades touch are embedded.
    option_sessions  {symbol: {day: rows}} for the option chart and the bar-by-bar table.
    groups    the user's custom group-bys: [{"name": "SMA10 at entry", "keys": ["sma10"]},
              {"name": "SMA10 x RSI", "keys": ["sma10", "rsi"]}]; keys are trade tag names.
    settings  the control panel, from `setting()`.  Omit it and every variant key becomes an
              untyped knob, which is what older scripts get.
    meta["break_date"]  optional "YYYY-MM-DD": a date the market itself changed (a session-time
              change, a lot-size change).  Stability then also cuts before/from it.
    sessions_log  one `session_row()` per session in the window, traded or not.  Without it the
              report can only show the days that produced a trade, and a reader cannot tell a
              day the rule declined from a day the data was missing.
    chart     "default" embeds option candles only for the trades the RULE's own settings
              produce - a 6-rung ladder would otherwise carry six times the option data for
              charts nobody opens.  It trims by SYMBOL, so a sweep that only changes the exit
              loses nothing, and it does nothing at all unless `settings` was passed: a script
              that never declared a panel keeps every chart it always had.  "all" embeds every
              symbol; say so in meta["limits"].

    The payload carries the TRADES, not a precomputed answer per filter combination: the page
    recomputes the book for whatever settings and date range are chosen.  `baseline` is the
    same book computed here, over every trade, and the page checks itself against it on load.
    """
    groups = groups or []
    tag_keys = {k for t in trades for k in t["tags"]}
    for g in groups:
        miss = [k for k in g["keys"] if k not in tag_keys]
        if miss:
            raise ValueError(f"group {g['name']!r}: no trade carries the tag(s) {miss}")
    declared = settings is not None
    spec = list(settings) if declared else _derive_settings(trades)
    for w in check_settings(settings, trades):
        print("WARNING  " + w)
    # every session a trade lives through: entry day, exit day, and any session between them
    need = {d for t in trades for d in index_sessions if t["day"] <= d <= t["exit_day"]}
    need |= {d for t in trades for d in (t["day"], t["exit_day"])}      # validate_payload reports a missing one
    index = {d: _round_rows(r) for d, r in index_sessions.items() if d in need}
    for t in trades:                                  # the index move during the trade
        for k, day, hhmm in (("entry_spot", t["day"], t["entry_time"]), ("exit_spot", t["exit_day"], t["exit_time"])):
            if t.get(k) is None:
                b = bar_at(index.get(day, []), hhmm, tolerance=3, direction=-1)
                t[k] = b[4] if b else None
        es, xs = t["entry_spot"], t["exit_spot"]
        t["spot_pts"] = None if es is None or xs is None else xs - es
        t["spot_pct"] = None if not es or xs is None else (xs - es) / es * 100
    # option candles: by default only for the trades the rule's own settings produce
    chart_syms = None
    if chart == "default" and declared and spec:
        dflt = {s["key"]: s["default"] for s in spec}
        fopt = {s["key"]: next(o for o in s["options"] if o["value"] == s["default"])
                for s in spec if s["mode"] == "filter"}
        chart_syms = {t["symbol"] for t in trades
                      if all(t["variant"].get(k) == v for k, v in dflt.items() if k not in fopt)
                      and all(_admits(t, o) for o in fopt.values())}
    elif chart not in ("default", "all"):
        raise ValueError(f"chart must be 'default' or 'all', got {chart!r}")
    opt: dict[str, dict] = {}
    for sym, days in (option_sessions or {}).items():
        if chart_syms is not None and sym not in chart_syms:
            continue
        keep = {d: _round_rows(r) for d, r in days.items() if d in need and r}
        if keep:
            opt[sym] = keep
    trades = sorted(trades, key=lambda t: (t["day"], t["entry_time"], t["symbol"]))
    priced = _price_fills(trades, index, option_sessions)
    for t in trades:
        t["filters"] = {"side": t["side"], **t["variant"]}      # kept for older readers
    standard = (STANDARD_GROUPS + ([OPTION_GROUP] if any(t.get("option_type") for t in trades) else [])
                + ([DTE_GROUP] if any(t.get("dte") is not None for t in trades) else []))
    meta = dict(meta)
    meta.setdefault("generated", datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"))
    meta["settings"] = spec
    meta["sides"] = _sides(trades)
    meta["fill_modes"] = [{"value": k, "label": v} for k, v in FILL_MODES] if priced == len(trades) and trades else []
    if trades and priced != len(trades):
        print(f"WARNING  fill comparison off: only {priced} of {len(trades)} trades had both bars "
              f"in the embedded candles")
    meta["group_defs"] = {"standard": standard, "custom": groups}
    meta["groups"] = standard + [g["name"] for g in groups]
    meta["chart_scope"] = ("every setting" if chart_syms is None else
                           "the rule's own settings only - other settings show metrics but no option chart")
    log = sorted(sessions_log or [], key=lambda r: r["day"])
    counts: dict[str, int] = {k: 0 for k in STATUSES}
    for r in log:
        counts[r["status"]] += 1
    meta["session_counts"] = dict(counts, total=len(log))
    meta["log_columns"] = list(dict.fromkeys(k for r in log for k in r["facts"]))
    payload = {"meta": meta, "trades": trades, "sessions": log,
               "baseline": {"overview": _book(trades), "series": _series(trades),
                            "groups": _groups(trades, groups, standard),
                            "stability": _stability(trades, meta.get("break_date"))},
               "candles": {"index": index, "option": opt}}
    validate_payload(payload)
    return payload


def _round_rows(rows: list[list]) -> list[list]:
    return [[r[0]] + [round(float(x), 2) for x in r[1:5]] for r in rows]


def validate_payload(p: dict) -> None:
    """Fail loudly on anything the HTML would silently mis-draw or mis-count."""
    bad: list[str] = []
    for i, t in enumerate(p["trades"]):
        for k in _REQUIRED_TRADE:
            if t.get(k) is None:
                bad.append(f"trade {i} ({t.get('day')}): missing {k}")
        if None not in (t.get("net"), t.get("gross"), t.get("costs")) and abs(t["gross"] - t["costs"] - t["net"]) > 0.05:
            bad.append(f"trade {i} ({t['day']}): net != gross - costs")
        for d in {t.get("day"), t.get("exit_day")}:
            if d not in p["candles"]["index"]:
                bad.append(f"trade {i}: no index candles for {d}")
    log = p.get("sessions") or []
    if log:
        days = {r["day"] for r in log}
        tdays = {t["day"] for t in p["trades"]}
        miss = sorted(tdays - days)
        if miss:
            bad.append(f"{len(miss)} trade day(s) are not in the session log, e.g. {miss[:3]}")
        orphan = sorted({r["day"] for r in log if r["status"] == "traded"} - tdays)
        if orphan:
            bad.append(f"{len(orphan)} session(s) logged 'traded' but produced no trade, e.g. {orphan[:3]}")
        dupes = sorted({d for d in days if sum(1 for r in log if r["day"] == d) > 1})
        if dupes:
            bad.append(f"{len(dupes)} day(s) appear twice in the session log, e.g. {dupes[:3]}")
    base = (p.get("baseline") or {}).get("overview")
    if p["trades"] and (base is None or base["n"] != len(p["trades"])):
        bad.append("the baseline book does not hold every trade")
    if bad:
        raise ValueError("report payload invalid:\n  " + "\n  ".join(bad[:25]))


def _clean(o):
    """Floats to 6 places (file size only - display rounding is the browser's job); NaN -> None."""
    if isinstance(o, float):
        return None if o != o or o in (float("inf"), float("-inf")) else round(o, 6)
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def write_report(payload: dict, name: str, template: str = SAMPLE_HTML) -> str:
    """Put `payload` into the template and write analysis/report/<name>.html.  Returns the path.
    The template is a normal HTML file whose data sits between /*DATA_START*/ and /*DATA_END*/;
    the same function rewrites sample.html itself when asked to."""
    with open(template, encoding="utf-8") as f:
        html = f.read()
    m = payload.get("meta", {})
    slug = os.path.splitext(os.path.basename(name))[0]
    m.setdefault("rerun", rerun_command(slug, m.get("settings"), m.get("from"), m.get("to")))
    a, b = html.index(DATA_START), html.index(DATA_END)
    blob = json.dumps(_clean(payload), separators=(",", ":"), default=str).replace("</", "<\\/")
    html = html[:a] + DATA_START + blob + html[b:]
    title = payload["meta"].get("title")
    if title:
        html = re.sub(r"<title>.*?</title>", lambda _m: f"<title>{_esc(title)}</title>", html, count=1, flags=re.S)
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"{name}.html") if os.path.dirname(name) == "" else name
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    mb = len(blob) / 1e6
    cand = len(json.dumps(_clean(payload.get("candles", {})), separators=(",", ":"), default=str)) / 1e6
    print(cache_stats())
    print(f"report data {mb:.1f} MB ({cand:.1f} MB of it candles)"
          + ("  - consider a shorter window or chart='default'" if mb > 40 else ""))
    return path


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def console_summary(trades: list[dict]) -> str:
    """One line printed at the end of a run, so the terminal shows the run did something
    sensible.  The report is the authority."""
    if not trades:
        return "0 trades"
    b = _book(trades)
    pf = f"{b['pf']:.2f}" if b["pf"] is not None else "n/a"
    return (f"{b['n']} trades, {b['wins']} wins ({b['win']:.1f}%), net Rs {b['net']:,.0f}, "
            f"costs Rs {b['costs']:,.0f}, profit factor {pf}, max drawdown Rs {b['max_dd']:,.0f}")
