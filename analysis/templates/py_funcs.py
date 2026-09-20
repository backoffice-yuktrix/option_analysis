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
          5 pure helpers  6 costs  6b rules and indicators  7 trades  8 report
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
# 2  Upstox client
# ---------------------------------------------------------------------------
class Upstox:
    """One httpx client, a rate limit and retry.  Use as `async with Upstox() as up:`."""

    def __init__(self, token: str | None = None, min_interval: float = 0.25) -> None:
        self.token = token or read_access_token()
        self._min_interval = min_interval
        self._next_at = 0.0
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        self._instruments: dict[str, list[dict]] = {}          # exchange -> rows (this run only)
        self._expired_contracts: dict[tuple[str, str], list[dict]] = {}

    async def __aenter__(self) -> "Upstox":
        self._client = httpx.AsyncClient(timeout=60.0)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    async def get(self, url: str, params: dict | None = None, *, retries: int = 4) -> dict:
        """GET with the bearer token; retries 429 and 5xx with backoff."""
        assert self._client, "use `async with Upstox() as up:`"
        delay = 2.0
        for attempt in range(retries + 1):
            async with self._lock:                              # >= min_interval between calls
                loop = asyncio.get_running_loop()
                wait = self._next_at - loop.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._next_at = loop.time() + self._min_interval
            try:
                r = await self._client.get(url, params=params, headers={
                    "Accept": "application/json", "Authorization": f"Bearer {self.token}"})
            except httpx.RequestError as exc:
                if attempt == retries:
                    raise RuntimeError(f"network error for {url}: {exc}") from exc
                await asyncio.sleep(delay); delay *= 2
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                raise PermissionError("Upstox token expired or unauthorised. Run analysis/connect_upstox.py.")
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                await asyncio.sleep(delay); delay *= 2
                continue
            raise RuntimeError(f"Upstox HTTP {r.status_code} for {url}: {r.text[:200]}")
        raise RuntimeError(f"exhausted retries for {url}")

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
        `contract` is what `resolve_option` returned."""
        key = quote(contract["instrument_key"], safe="")
        d_ = day.isoformat()
        if contract["expired"]:
            url = f"{BASE_V2}/expired-instruments/historical-candle/{key}/{interval_minutes}minute/{d_}/{d_}"
        else:
            url = f"{BASE_V3}/historical-candle/{key}/minutes/{interval_minutes}/{d_}/{d_}"
            if day == datetime.now(IST).date():
                url = f"{BASE_V3}/historical-candle/intraday/{key}/minutes/{interval_minutes}"
        d = await self.get(url)
        raw = (d.get("data") or {}).get("candles") or []
        return sorted([c[0][11:16], float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                      for c in raw if len(c) >= 5)


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
# 8  report - every number is computed here; the browser only picks and formats
# ---------------------------------------------------------------------------
DATA_START, DATA_END = "/*DATA_START*/", "/*DATA_END*/"
ALL = "all"
MAX_VIEWS = 400                 # filter combinations; more than this means too many dimensions
ROLL_WINDOW = 20
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
STANDARD_GROUPS = ["weekday", "month", "entry hour", "exit reason"]
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


def _stability(trs: list[dict]) -> list[dict]:
    """Does the result survive being cut up?  Halves, thirds, quarters by trade order, each
    with its date range, then the book with the best 10% and the worst 10% of trades removed
    (10% rounded UP to a whole trade)."""
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
    return rows


def _filter_dims(trades: list[dict]) -> list[dict]:
    """side, then every variant key, each with its values in first-seen order."""
    dims: dict[str, list[str]] = {"side": []}
    for t in trades:
        for k, v in {"side": t["side"], **t["variant"]}.items():
            if v not in dims.setdefault(k, []):
                dims[k].append(v)
    dims["side"].sort()
    return [{"key": k, "values": v} for k, v in dims.items() if len(v) > 1 or k == "side"]


def view_key(dims: list[dict], chosen: dict) -> str:
    """'side=LONG|rr=1:2' - dimensions in order, 'all' left out.  The browser builds the same."""
    return "|".join(f"{d['key']}={chosen[d['key']]}" for d in dims if chosen.get(d["key"], ALL) != ALL)


def _filter_value(t: dict, key: str) -> str | None:
    return t["side"] if key == "side" else t["variant"].get(key)


def _views(trades: list[dict], dims: list[dict], custom: list[dict], standard: list[str]) -> dict:
    size = 1
    for d in dims:
        size *= len(d["values"]) + 1
    if size > MAX_VIEWS:
        raise ValueError(f"{size} filter combinations (> {MAX_VIEWS}); use fewer variant keys or values. "
                         f"Dimensions: {[(d['key'], len(d['values'])) for d in dims]}")
    views: dict[str, dict] = {}

    def rec(i: int, chosen: dict) -> None:
        if i == len(dims):
            ts = [t for t in trades if all(v == ALL or _filter_value(t, k) == v for k, v in chosen.items())]
            if ts:
                views[view_key(dims, chosen)] = {"overview": _book(ts), "series": _series(ts),
                                                 "groups": _groups(ts, custom, standard), "stability": _stability(ts)}
            return
        for v in [ALL] + dims[i]["values"]:
            rec(i + 1, {**chosen, dims[i]["key"]: v})
    rec(0, {})
    return views


def build_payload(meta: dict, trades: list[dict], index_sessions: dict[str, list[list]],
                  option_sessions: dict[str, dict[str, list[list]]] | None = None,
                  groups: list[dict] | None = None) -> dict:
    """Assemble what the HTML reads, computing every number.

    meta      title, subtitle, instrument, from, to, lot_size, fill_rule, cost_model,
              params {name: value}, rule_steps [str], limits [str], coverage (from `coverage()`).
    trades    from make_trade().
    index_sessions   {day: rows}, full sessions; only the days trades touch are embedded.
    option_sessions  {symbol: {day: rows}} for the option chart and the bar-by-bar table.
    groups    the user's custom group-bys: [{"name": "SMA10 at entry", "keys": ["sma10"]},
              {"name": "SMA10 x RSI", "keys": ["sma10", "rsi"]}]; keys are trade tag names.
    """
    groups = groups or []
    tag_keys = {k for t in trades for k in t["tags"]}
    for g in groups:
        miss = [k for k in g["keys"] if k not in tag_keys]
        if miss:
            raise ValueError(f"group {g['name']!r}: no trade carries the tag(s) {miss}")
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
    opt: dict[str, dict] = {}
    for sym, days in (option_sessions or {}).items():
        keep = {d: _round_rows(r) for d, r in days.items() if d in need and r}
        if keep:
            opt[sym] = keep
    trades = sorted(trades, key=lambda t: (t["day"], t["entry_time"], t["symbol"]))
    dims = _filter_dims(trades)
    for t in trades:
        t["filters"] = {"side": t["side"], **t["variant"]}
    meta = dict(meta)
    meta.setdefault("generated", datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"))
    meta["filters"] = dims
    standard = (STANDARD_GROUPS + ([OPTION_GROUP] if any(t.get("option_type") for t in trades) else [])
                + ([DTE_GROUP] if any(t.get("dte") is not None for t in trades) else []))
    meta["groups"] = standard + [g["name"] for g in groups]
    payload = {"meta": meta, "trades": trades, "views": _views(trades, dims, groups, standard),
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
    top = p["views"].get("")
    if p["trades"] and (top is None or top["overview"]["n"] != len(p["trades"])):
        bad.append("the all-trades view does not hold every trade")
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
    a, b = html.index(DATA_START), html.index(DATA_END)
    blob = json.dumps(_clean(payload), separators=(",", ":"), default=str).replace("</", "<\\/")
    html = html[:a] + DATA_START + blob + html[b:]
    title = payload["meta"].get("title")
    if title:
        html = re.sub(r"<title>.*?</title>", lambda _m: f"<title>{_esc(title)}</title>", html, count=1, flags=re.S)
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"{name}.html") if os.path.dirname(name) == "" else name
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
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
