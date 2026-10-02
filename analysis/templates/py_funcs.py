"""Everything a generated strategy script needs from the local candle store, plus the report writer.

A strategy script in analysis/scripts/<category>/ imports this file and contains ONLY the
strategy: decide, simulate, build trades.  Every candle, expiry and contract comes from
analysis/candle_datas (section 1b); nothing is fetched from Upstox without the user's
permission, and a run ends by listing whatever it needed that was not on disk.

    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
    from py_funcs import *
    CATEGORY = "index_options"        # or "stock_options" / "stock_intraday" - see CATEGORIES

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
    write_report(payload, "my_strategy")                             # -> analysis/report/<category>/my_strategy.html

Sections: 1 paths  2 Upstox client (3 instruments and options, 4 candles inside it)
          5 pure helpers  6 costs  6b rules and indicators  7 trades  7b settings  7c session log  8 report
"""
from __future__ import annotations

import asyncio
import functools
import gzip
import json
import math
import os
import re
import statistics
import sys
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
SCRIPTS_DIR = os.path.join(ANALYSIS_DIR, "scripts")
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
# 1b  LOCAL DATA ONLY - analysis/candle_datas (the user, 2026-09-29)
# ---------------------------------------------------------------------------
# Every candle, expiry list and contract list a strategy reads comes from the files that
# analysis/templates/fetch_data.py keeps in analysis/candle_datas (moved from analysis_rajkumarn/ on
# 2026-09-30, the user; fetch_data drives the unedited analysis_rajkumarn/fetch_candles.py; layout and
# format: analysis_rajkumarn/fetch.md, section 3).  A strategy run never fetches from Upstox.
#
#   * What is not on disk is NOT fetched.  It is noted, the run carries on with it as 'no data'
#     (rule 6), the report says so in meta.limits, and the end of the run prints the exact
#     fetch_candles.py commands that would fill the gap.  Those are run only with the user's
#     permission, and only for what was missing.
#   * A day inside a file's `fetched` ranges with no candles is a real no-trade day; a day outside
#     them is missing data.  The two are never confused.
#   * Nothing here writes to disk.  Nothing is interpolated or filled forward: a gap stays a gap.
#   * The broker's charges and margin calculators, NSE and Yahoo are live calls too: they run only
#     with PYFUNCS_ALLOW_FETCH=1, set when the user has allowed it for that run.

LOCAL_DATA_DIR = os.path.abspath(os.path.join(ANALYSIS_DIR, "candle_datas"))
# Stocks and their options live apart in analysis/stock_datas (git-ignored, the user, 2026-09-30);
# fetch_data.data_dir puts every non-index instrument there.  Both folders are read, candle_datas first.
STOCK_DATA_DIR = os.path.abspath(os.path.join(ANALYSIS_DIR, "stock_datas"))
LOCAL_DATA_DIRS = (LOCAL_DATA_DIR, STOCK_DATA_DIR)
ALLOW_FETCH = os.environ.get("PYFUNCS_ALLOW_FETCH") == "1"
NO_FETCH = ("live fetches are off - nothing is fetched without the user's permission "
            "(PYFUNCS_ALLOW_FETCH=1 once they allow it)")

_OPT_FILE = re.compile(r"^(?P<name>.+?)_(?P<ot>CE|PE)_(?P<strike>[\d.]+)_(?P<expiry>\d{4}-\d{2}-\d{2})(_\w+)?_candles\.json$")
_INST_FILE = re.compile(r"^(?P<name>.+?)(?:_(?P<iv>\d+[md]))?_candles\.json$")
_EXPIRY_FILE = re.compile(r"^(?P<name>.+)_expiry\.json$")
_BLOBS: dict[str, dict | None] = {}              # index candles, expiry and contract lists - this run only
_KEYS: dict[str, str] | None = None               # instrument_key -> NAME of every index / stock on disk
_CONTRACTS: dict[str, dict] = {}                  # option instrument_key -> its contract row
_INDEXED: set[str] = set()                        # NAMEs whose contract list is in _CONTRACTS
_MISSING: dict[str, list[tuple[date, date]]] = {}  # fetch_candles.py arguments -> date ranges not on disk
_NOTES: set[str] = set()                          # a gap no single fetch_candles.py command fills
_BUILT: set[tuple[str, str]] = set()              # (NAME, interval) built from 1-minute candles this run


class LiveFetchBlocked(RuntimeError):
    """A live call (Upstox, NSE, Yahoo) was asked for while PYFUNCS_ALLOW_FETCH is not set."""


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _local_path(fname: str) -> str:
    """Where a data file is: the first of LOCAL_DATA_DIRS that holds it (else where an index file would be)."""
    for d in LOCAL_DATA_DIRS:
        p = os.path.join(d, fname)
        if os.path.exists(p):
            return p
    return os.path.join(LOCAL_DATA_DIR, fname)


def _local(fname: str) -> dict | None:
    """One file of LOCAL_DATA_DIRS, parsed once per run."""
    if fname not in _BLOBS:
        _BLOBS[fname] = _read_json(_local_path(fname))
    return _BLOBS[fname]


def _local_keys() -> dict[str, str]:
    """{instrument_key: NAME} for every index or stock with a candle or expiry file on disk.  The key
    is read from the head of each file (fetch_candles writes it before the candles), so no big
    file is parsed to find it."""
    global _KEYS
    if _KEYS is None:
        _KEYS = {}
        names = [(d, fn) for d in LOCAL_DATA_DIRS if os.path.isdir(d) for fn in sorted(os.listdir(d))]
        for d, fn in names:
            m = None if _OPT_FILE.match(fn) else (_INST_FILE.match(fn) or _EXPIRY_FILE.match(fn))
            if not m:
                continue
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                k = re.search(r'"instrument_key":\s*"([^"]+)"', f.read(1024))
            if k:
                _KEYS.setdefault(k.group(1), m.group("name"))
    return _KEYS


def _local_contracts(name: str) -> dict[str, list[dict]]:
    """{expiry: [contract, ...]} from NAME_contracts.json - every past expiry fetch_candles has seen.
    Each: {instrument_key, trading_symbol, strike, type, lot_size, expired}."""
    chain = _local(f"{name}_contracts.json") or {}
    if name not in _INDEXED:
        _INDEXED.add(name)
        for e, cs in chain.items():
            for c in cs:
                _CONTRACTS[c["instrument_key"]] = dict(c, underlying=name, expiry=e)
    return chain


def _contract_by_key(key: str) -> dict | None:
    for name in sorted(set(_local_keys().values())):
        _local_contracts(name)
    return _CONTRACTS.get(key)


def _option_name(option_type: str, strike: float, expiry: str) -> str:
    """CE_25000_2026-01-27 - the contract part of a file name, as fetch_candles.option_name writes it."""
    return f"{option_type}_{float(strike):g}_{expiry}"


@functools.lru_cache(maxsize=32)
def _option_file(fname: str) -> tuple[list, dict] | None:
    """(fetched ranges, {day: [[HH:MM, o, h, l, c, volume], ...]}) of one contract file, or None.
    Kept for the last 32 contracts: a trade reads its contract on the entry day and the exit day."""
    blob = _read_json(_local_path(fname))
    if blob is None:
        return None
    days: dict[str, list[list]] = {}
    for r in blob["candles"]:
        days.setdefault(r[0][:10], []).append(
            [r[0][11:16], float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[5]) if len(r) > 5 else 0])
    return blob["fetched"], days


def _gaps(frm: date, to: date, fetched: list[list[str]]) -> list[tuple[date, date]]:
    """The parts of [frm, to] not inside any fetched [from, to] range."""
    out, cur = [], frm
    for a, b in sorted((date.fromisoformat(a), date.fromisoformat(b)) for a, b in fetched):
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


def _aggregate(rows: list[list], interval: str) -> list[list]:
    """Bigger candles built from 1-minute rows [timestamp, o, h, l, c, volume, oi], oldest first.
    Minute and hour candles start at 09:15 like the exchange's own (5m: 09:15, 09:20 ...); a day is
    its whole session.  open = the first minute's open, high / low = the extremes of the minutes,
    close = the last minute's close, volume = the sum, oi = the last.  Only minutes that exist are
    used - nothing is filled.

    A DAY's close is not the last minute's: the exchange sets the official close from the last half
    hour's average price, so it is the average typical price (h + l + c) / 3 of the 15:00-15:29
    minutes, weighted by volume when the minutes carry it (a stock; an index has none).  Checked on
    153 NIFTY sessions against Upstox's official daily closes: median 1.4 points off, 90% within
    4.3 - the 15:29 minute's close was a median 11 points off, up to 86 (`built_note` says so)."""
    unit, n = _interval_unit(interval)
    if unit == "weeks" or (unit == "days" and n != 1):
        raise ValueError(f"interval {interval!r}: only minutes, hours and 1d are built from 1-minute candles")
    size = n * 60 if unit == "hours" else n
    out: list[list] = []
    last_half_hour: dict[str, list[list]] = {}
    for r in rows:
        day = r[0][:10]
        if unit == "days":
            key = f"{day}T00:00:00+05:30"
            if "15:00" <= r[0][11:16] <= "15:29":
                last_half_hour.setdefault(day, []).append(r)
        else:
            m = int(r[0][11:13]) * 60 + int(r[0][14:16])
            s = 555 + (m - 555) // size * size                    # 555 = 09:15
            key = f"{day}T{s // 60:02d}:{s % 60:02d}:00+05:30"
        vol, oi = (r[5] if len(r) > 5 else 0), (r[6] if len(r) > 6 else 0)
        if out and out[-1][0] == key:
            c = out[-1]
            c[2], c[3], c[4], c[5], c[6] = max(c[2], r[2]), min(c[3], r[3]), r[4], c[5] + vol, oi
        else:
            out.append([key, r[1], r[2], r[3], r[4], vol, oi])
    for c in out:
        tail = last_half_hour.get(c[0][:10])
        if tail:
            w = [x[5] if len(x) > 5 else 0 for x in tail]
            w = w if any(w) else [1] * len(tail)
            c[4] = round(sum((x[2] + x[3] + x[4]) / 3 * k for x, k in zip(tail, w)) / sum(w), 2)
    return out


def built_note() -> str | None:
    """One plain line for meta.limits naming the candles this run built from 1-minute candles."""
    if not _BUILT:
        return None
    what = ", ".join(f"{name} {'daily' if iv == '1d' else iv}" for name, iv in sorted(_BUILT))
    return (f"Candles built from the 1-minute candles on disk, not fetched: {what}.  Open, high and low are "
            "exact.  A daily close is the average price of the last half hour (15:00-15:29), the way the exchange "
            "sets its official close: on 153 NIFTY days it was a median 1.4 points from the official close, "
            "90% of days within 4.3 points.")


def _missing(args: str, a: date, b: date) -> None:
    _MISSING.setdefault(args, []).append((a, b))


def missing_local() -> dict[str, list[tuple[date, date]]]:
    """What this run asked for and the disk did not have: {fetch_candles.py arguments: [(from, to), ...]}."""
    out = {}
    for args, rs in sorted(_MISSING.items()):
        merged: list[tuple[date, date]] = []
        for a, b in sorted(rs):
            if merged and a <= merged[-1][1] + timedelta(days=1):
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        out[args] = merged
    return out


def missing_report(limit: int = 40) -> str:
    """The console block a run ends with when data was missing: every gap as the fetch_candles.py
    command that fills exactly it.  Run them only with the user's permission."""
    miss = missing_local()
    if not miss and not _NOTES:
        return ""
    lines = [f"NOT ON LOCAL DISK ({' + '.join(LOCAL_DATA_DIRS)}) - treated as no data, nothing was fetched.",
             "With the user's permission, fetch only this (from the repository root; see analysis/templates/fetch_data.py):"]
    for i, (args, rs) in enumerate(miss.items()):
        if i == limit:
            lines.append(f"  ... and {len(miss) - limit} more")
            break
        lines.append(f"  analysis/.venv/Scripts/python.exe analysis/templates/fetch_data.py {args} --from {rs[0][0]} --to {rs[-1][1]}"
                     + (f"   ({len(rs)} separate gaps)" if len(rs) > 1 else ""))
    lines += [f"  - {n}" for n in sorted(_NOTES)]
    return "\n".join(lines)


def missing_note() -> str | None:
    """One plain line for meta.limits saying what the local data lacked, or None."""
    miss = missing_local()
    if not miss and not _NOTES:
        return None
    def plain(args: str) -> str:              # "candles NIFTY --interval 1d" -> "NIFTY daily candles"
        what, name, *rest = args.split()
        if what == "expiries":
            return f"{name} expiry list"
        return f"{name} {'daily' if rest[-1:] == ['1d'] else rest[-1] if rest else '1-minute'} candles"

    n_opt = sum(" --opt " in k for k in miss)
    parts = [f"{plain(k)} {rs[0][0]} to {rs[-1][1]}" for k, rs in miss.items() if " --opt " not in k]
    parts += [f"{n_opt} option contract(s)"] if n_opt else []
    parts += sorted(_NOTES)
    return ("Local data only (analysis/candle_datas, nothing fetched): not on disk, so treated as "
            "no data - " + "; ".join(parts) + ".")


# ---------------------------------------------------------------------------
# 1c  INSTRUMENTS - every index strategy runs on each index on disk (the user, 2026-09-30)
# ---------------------------------------------------------------------------
# A script written for NIFTY runs unchanged on SENSEX through `run_instruments` (section 8): the
# script file is executed once per index with `instrument()` set, and ONE report comes out with an
# Instrument selector (all = the books added together).  What differs between the indices is read,
# never assumed:
#   * the strike step and lot size come from the index's own contract list (NIFTY 50 / 65,
#     SENSEX 100 / 20);
#   * a rule number written in NIFTY points means the same SHARE OF THE PRICE on another index
#     (the user, 2026-09-30): multiply it by `price_scale()`, the median SENSEX/NIFTY close ratio over
#     the window (about 3.22), and `strike_offset` counts its steps in NIFTY strikes;
#   * costs follow the exchange the contract trades on: SENSEX options are BSE's (`exchange_of`).
INDEX_INSTRUMENTS = ("NIFTY", "SENSEX")
REFERENCE_INSTRUMENT = "NIFTY"          # the index every rule was written on
REFERENCE_STEP = 50.0                   # its strike step: `strike_offset` counts in these
BSE_UNDERLYINGS = {"SENSEX", "BANKEX", "SENSEX50"}
# Every index strategy is priced on these strikes, in NIFTY strikes in the money (the user,
# 2026-09-30: "every strategy has to run on ITM 6 to ATM"): 6 ITM ... 1 ITM, ATM.
STRIKE_LADDER = (6, 5, 4, 3, 2, 1, 0)
_ACTIVE: dict = {"instrument": REFERENCE_INSTRUMENT, "collect": None, "rung": 0, "ladder_rung": None}


def rung_label(n) -> str:
    """'6 ITM' ... '1 ITM', 'ATM' - a strike depth in NIFTY strikes in the money."""
    n = int(n)
    return "ATM" if n == 0 else f"{n} ITM" if n > 0 else f"{-n} OTM"


def instrument() -> str:
    """The index this run trades - NIFTY unless `run_instruments` is running the script for another."""
    return _ACTIVE["instrument"]


def exchange_of(symbol: str | None = None) -> str:
    """'BSE' for a SENSEX / BANKEX contract, else 'NSE' - from the trading symbol, or the active index."""
    return "BSE" if (symbol or instrument()).split()[0].upper() in BSE_UNDERLYINGS else "NSE"


def price_scale(name: str | None = None) -> float:
    """How many points of `name` make one NIFTY point, as a share of the price: the median of its daily
    close / NIFTY's daily close over START_DATE .. END_DATE (15:29 minutes, from local disk).  1.0 for
    NIFTY.  A rule number in NIFTY points (a stop of 25 points, a floor of 16 option points) is that
    number x price_scale() on another index - the same rule, the same share of the price.  With no
    name it is the ACTIVE index's (the cache is keyed on the resolved name, never on the call)."""
    return _price_scale(name or instrument())


@functools.lru_cache(maxsize=None)
def _price_scale(name: str) -> float:
    if name == REFERENCE_INSTRUMENT:
        return 1.0
    closes = {}
    for n in (name, REFERENCE_INSTRUMENT):
        blob = _local(f"{n}_candles.json")
        if blob is None:
            raise LookupError(f"no {n}_candles.json on local disk to scale {name} against {REFERENCE_INSTRUMENT}")
        closes[n] = {r[0][:10]: r[4] for r in blob["candles"]
                     if START_DATE.isoformat() <= r[0][:10] <= END_DATE.isoformat()}
    days = sorted(set(closes[name]) & set(closes[REFERENCE_INSTRUMENT]))
    return round(statistics.median(closes[name][d] / closes[REFERENCE_INSTRUMENT][d] for d in days), 4)


def strike_step(name: str | None = None) -> float:
    """The index's strike step, read from its latest expiry on disk: the most common gap between
    adjacent listed strikes (NIFTY 50, SENSEX 100)."""
    name = name or instrument()
    chain = _local_contracts(name)
    if not chain:
        raise LookupError(f"no option contracts of {name} on local disk ({name}_contracts.json)")
    strikes = sorted({float(c["strike"]) for c in chain[max(chain)]})
    gaps = [b - a for a, b in zip(strikes, strikes[1:])]
    return max(set(gaps), key=gaps.count)


# ---------------------------------------------------------------------------
# 2  Upstox client
# ---------------------------------------------------------------------------
class Upstox:
    """The data client every script uses: `async with Upstox() as up:`.  Candles, expiries,
    contracts and instruments come from local disk (section 1b) and never from the API.  The
    httpx client, rate limit and retry below serve only the live calls (the broker's charges and
    margin, the instrument master for a futures lot), and those refuse to go out unless
    PYFUNCS_ALLOW_FETCH=1.  Leaving the block prints what the run needed that was not on disk."""

    # Upstox meters per second, per minute AND per half hour, and a breach of the long window
    # puts the whole account in a penalty box for minutes - no amount of retrying gets through.
    # A ladder is thousands of calls, so the client PACES ITSELF to stay inside every window
    # rather than sprinting and then failing.  Set a little under the published caps.
    RATE_LIMITS = ((1.0, 20), (60.0, 220), (1800.0, 880))      # (window seconds, max calls)
    MAX_INTERVAL = 4.0          # the slowest the adaptive gap will go
    COOLDOWN = 75.0             # a 429 means a window is spent; wait it out, do not hammer
    MAX_COOLDOWN = 240.0        # ... but never trust a server-supplied Retry-After blindly

    def __init__(self, token: str | None = None, min_interval: float = 0.25) -> None:
        self.token = token or (read_access_token() if ALLOW_FETCH else None)
        self._min_interval = min_interval
        self._next_at = 0.0
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        self._instruments: dict[str, list[dict]] = {}          # exchange -> rows (this run only)
        self._expired_contracts: dict[tuple[str, str], list[dict]] = {}
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
        report = missing_report()
        if report:
            print(report, flush=True)

    async def get(self, url: str, params: dict | None = None, *, retries: int = 8) -> dict:
        """GET with the bearer token; retries 429 and 5xx with backoff (see `_request`)."""
        return await self._request("GET", url, params=params, retries=retries)

    async def post(self, url: str, body: dict, *, retries: int = 8) -> dict:
        """POST a JSON body with the bearer token - the margin calculator is a POST."""
        return await self._request("POST", url, body=body, retries=retries)

    async def _request(self, method: str, url: str, params: dict | None = None, body: dict | None = None,
                       *, retries: int = 8) -> dict:
        """One Upstox call; retries 429 and 5xx with backoff.

Pacing happens in `_slot` before the
        call goes out; this handles the case where it was not enough.  A 429 means a whole
        window is spent, so the run waits `Retry-After` (or COOLDOWN) rather than retrying into
        the same wall, and permanently widens its own gap.  A ladder of a few thousand calls
        used to die on `UDAPI10005 Too Many Request Sent`; the point of a backtest is to finish
        slowly, not to fail fast."""
        if not ALLOW_FETCH:
            raise LiveFetchBlocked(f"{method} {url} not sent: {NO_FETCH}")
        assert self._client, "use `async with Upstox() as up:`"
        delay = 2.0
        for attempt in range(retries + 1):
            await self._slot()
            try:
                r = await self._client.request(method, url, params=params, json=body, headers={
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
    # 3  instruments and options - from local disk
    # -----------------------------------------------------------------------
    async def instruments(self, exchange: str = "NSE") -> list[dict]:
        """The public instrument master for one exchange (NSE, BSE, MCX ...) - a LIVE download, so
        it refuses unless PYFUNCS_ALLOW_FETCH=1.  Only `future_contract` still needs it."""
        if not ALLOW_FETCH:
            raise LiveFetchBlocked(f"the {exchange} instrument master not downloaded: {NO_FETCH}")
        if exchange not in self._instruments:
            assert self._client
            r = await self._client.get(INSTRUMENTS_URL.format(exchange=exchange))
            r.raise_for_status()
            self._instruments[exchange] = json.loads(gzip.decompress(r.content))
        return self._instruments[exchange]

    def _name(self, instrument_key: str) -> str:
        """The NAME the local files use for an index or stock key (NSE_INDEX|Nifty 50 -> NIFTY)."""
        name = _local_keys().get(instrument_key)
        if name is None:
            raise LookupError(f"{instrument_key} has no files in {' or '.join(LOCAL_DATA_DIRS)}")
        return name

    async def find_instrument(self, query: str, segment: str | None = None,
                              exchange: str = "NSE") -> dict:
        """The index or stock whose name is `query` (case-blind), among those on local disk.

        `find_instrument("NIFTY")`                    -> the Nifty 50 index (NIFTY_candles.json)
        `find_instrument("SENSEX")`                   -> BSE SENSEX (SENSEX_candles.json)
        `find_instrument("RELIANCE", "NSE_EQ")`       -> the equity, once RELIANCE_candles.json exists
        `segment` (NSE_INDEX, NSE_EQ, BSE_INDEX ...) narrows the match.  Raises with what IS on
        disk when nothing matches, and notes the fetch that would add it."""
        q = query.upper().replace(" ", "")
        alias = INDEX_ALIASES.get(q, query).lower()
        for key, name in _local_keys().items():
            seg, _, label = key.partition("|")
            if segment and seg != segment:
                continue
            if q == name.upper().replace(" ", "") or label.lower() in (alias, query.lower()):
                return {"instrument_key": key, "trading_symbol": name, "name": label, "segment": seg,
                        "instrument_type": "INDEX" if seg.endswith("INDEX") else seg.split("_")[-1],
                        "lot_size": None, "exchange": seg.split("_")[0]}
        _missing(f"candles {q}", START_DATE, END_DATE - timedelta(days=1))
        raise LookupError(f"{query!r} is not on local disk ({' or '.join(LOCAL_DATA_DIRS)}); on disk: "
                          f"{sorted(set(_local_keys().values())) or 'nothing'}")

    async def option_chain_info(self, underlying_key: str) -> dict:
        """What the option chain of an underlying looks like, from its local contract list:
        {expiries: [date...], strike_step, lot_size, strikes, contracts}.  expiries are every
        expiry on disk; strikes, lot_size and contracts are the LATEST one's.  strike_step is the
        most common gap between adjacent strikes (NIFTY 50, SENSEX 100), so it is read, never
        assumed."""
        name = self._name(underlying_key)
        chain = _local_contracts(name)
        if not chain:
            raise LookupError(f"no option contracts of {name} on local disk ({name}_contracts.json)")
        expiries = sorted(date.fromisoformat(e) for e in chain)
        last = chain[expiries[-1].isoformat()]
        strikes = sorted({float(c["strike"]) for c in last})
        gaps = [b - a for a, b in zip(strikes, strikes[1:])]
        step = max(set(gaps), key=gaps.count) if gaps else None
        return {"expiries": expiries, "strike_step": step, "lot_size": int(last[0]["lot_size"]),
                "strikes": strikes,
                "contracts": [{"instrument_key": c["instrument_key"], "trading_symbol": c["trading_symbol"],
                               "strike_price": c["strike"], "instrument_type": c["type"],
                               "lot_size": c["lot_size"], "expiry": expiries[-1].isoformat()} for c in last]}

    async def expiry_calendar(self, underlying_key: str, frm: date, to: date) -> list[date]:
        """Every option expiry from a week before `frm` to a month after `to`, from the local
        NAME_expiry.json.  A window that runs past the list's own end is noted as missing."""
        name = self._name(underlying_key)
        blob = _local(f"{name}_expiry.json")
        if blob is None:
            _missing(f"expiries {name}", frm, to)
            return []
        if to > date.fromisoformat(blob["to"]):
            _missing(f"expiries {name}", date.fromisoformat(blob["from"]), to)
        return sorted(e for e in map(date.fromisoformat, blob["expiries"])
                      if frm - timedelta(days=7) <= e <= to + timedelta(days=30))

    async def resolve_option(self, underlying_key: str, expiry: date, strike: float,
                             option_type: str) -> dict | None:
        """The contract for (expiry, strike, CE|PE) from the local contract list, or None.  The
        lot_size is the one in force for that expiry.  An expiry whose list is not on disk is
        noted as missing (fetching any contract of it brings the list).

        The strike ladder (`run_instruments`): while a strategy that trades one strike is run at
        rung N, the strike it asks for is moved N NIFTY strikes in the money here - below the
        spot for a CE, above it for a PE, the same % distance on another index - so the rest of
        the script (candles, fills, costs, lot) follows the contract actually traded."""
        name = self._name(underlying_key)
        if _ACTIVE["rung"] and strike > 0:
            step = strike_step(name)
            n = (_ACTIVE["rung"] if name == REFERENCE_INSTRUMENT
                 else round(_ACTIVE["rung"] * REFERENCE_STEP * price_scale(name) / step))
            strike = float(strike) + (-n if option_type == "CE" else n) * step
        ek = expiry.isoformat()
        pool = _local_contracts(name).get(ek)
        if pool is None:
            if strike > 0:
                _missing(f"candles {name} --opt {_option_name(option_type, strike, ek)}",
                         expiry - timedelta(days=20), expiry)
            return None
        for c in pool:
            if float(c["strike"]) == float(strike) and c["type"] == option_type:
                return {"trading_symbol": c["trading_symbol"], "instrument_key": c["instrument_key"],
                        "expired": c["expired"], "lot_size": int(c["lot_size"]), "expiry": ek,
                        "strike": float(strike), "option_type": option_type, "underlying": name}
        return None

    async def listed_strikes(self, underlying_key: str, expiry: date, option_type: str) -> list[float]:
        """Every strike listed for (expiry, CE|PE), ascending, from the local contract list.  Stock
        options are NOT evenly spaced (RELIANCE: 10 near the money, 20 further out; INFY 20 and 40),
        so 'N strikes in the money' on a stock must step through THIS list, never ATM +/- N x one
        step (RULE 8)."""
        name = self._name(underlying_key)
        pool = _local_contracts(name).get(expiry.isoformat())
        if pool is None:
            _NOTES.add(f"{name} contract list for expiry {expiry} (fetching any {name} option of that expiry brings it)")
            return []
        return sorted({float(c["strike"]) for c in pool if c["type"] == option_type})

    async def future_contract(self, underlying_key: str, day: date) -> dict | None:
        """The near-month FUTURES contract in force on `day`: the one with the nearest expiry on
        or after it.  Returns {trading_symbol, instrument_key, lot_size, expiry} or None.

        This is where a stock's F&O LOT SIZE comes from (RULE 8) - NSE revises it every few
        months (HDFCBANK was 550 through the Jun-2026 series and 650 from Jul-2026), so a trade
        sized "one lot" must read it per day, never from a constant.  LIVE calls (the local store
        keeps no futures): past contracts come from /expired-instruments/future/contract, live ones
        from the instrument master - so it refuses unless PYFUNCS_ALLOW_FETCH=1."""
        exps = self._expired_contracts.setdefault((underlying_key, "fut-expiries"), [])
        if not exps:
            try:
                d = await self.get(f"{BASE_V2}/expired-instruments/expiries", {"instrument_key": underlying_key})
                exps.extend(sorted(date.fromisoformat(s) for s in d.get("data") or []))
            except LiveFetchBlocked:
                raise
            except RuntimeError as exc:
                print(f"  ! expired expiries unavailable ({exc})")
        live = [r for r in await self.instruments("NSE")
                if r.get("segment") == "NSE_FO" and r.get("instrument_type") == "FUT"
                and r.get("underlying_key") == underlying_key]
        for r in live:                                     # expiry is epoch ms in the master
            r["_exp"] = datetime.fromtimestamp(r["expiry"] / 1000, IST).date()
        cands = sorted({e for e in exps if e >= day} | {r["_exp"] for r in live if r["_exp"] >= day})
        if not cands:
            return None
        e = cands[0]
        for r in live:
            if r["_exp"] == e:
                return {"trading_symbol": r["trading_symbol"], "instrument_key": r["instrument_key"],
                        "lot_size": int(r.get("lot_size") or 0), "expiry": e.isoformat()}
        ck = (underlying_key, "fut", e.isoformat())
        if ck not in self._expired_contracts:
            d = await self.get(f"{BASE_V2}/expired-instruments/future/contract",
                               {"instrument_key": underlying_key, "expiry_date": e.isoformat()})
            self._expired_contracts[ck] = [{"trading_symbol": c.get("trading_symbol"),
                                            "instrument_key": c.get("instrument_key"),
                                            "lot_size": int(c.get("lot_size") or 0)} for c in d.get("data") or []]
        for c in self._expired_contracts[ck]:
            return {"trading_symbol": c["trading_symbol"], "instrument_key": c["instrument_key"],
                    "lot_size": int(c.get("lot_size") or 0), "expiry": e.isoformat()}
        return None

    # -----------------------------------------------------------------------
    # 4  candles - from local disk
    # -----------------------------------------------------------------------
    async def candles(self, instrument_key: str, interval: str, frm: date, to: date) -> list[dict]:
        """OHLCV candles of an index or stock, oldest first, from NAME_candles.json ('1m') or
        NAME_<interval>_candles.json ('5m', '1d' ...).  An interval with no file of its own is BUILT
        from the 1-minute file (`_aggregate`, the user, 2026-09-29: never fetched), and the report
        says so.  Closed sessions only - `to` stops at yesterday.  Any part of frm..to the file was
        never fetched for is noted as missing.  Each item: {timestamp, open, high, low, close, volume, oi}."""
        name = self._name(instrument_key)
        to = min(to, datetime.now(IST).date() - timedelta(days=1))
        if frm > to:
            return []
        blob = _local(f"{name}{'' if interval == '1m' else '_' + interval}_candles.json")
        built = blob is None and interval != "1m"
        if built:
            blob = _local(f"{name}_candles.json")
            _BUILT.add((name, interval))
        args = f"candles {name}" + ("" if interval == "1m" or built else f" --interval {interval}")
        for a, b in _gaps(frm, to, blob["fetched"] if blob else []):
            _missing(args, a, b)
        if blob is None:
            return []
        lo, hi = frm.isoformat(), to.isoformat()
        rows = [r for r in blob["candles"] if lo <= r[0][:10] <= hi]
        return [_candle(r) for r in (_aggregate(rows, interval) if built else rows)]

    async def minute_sessions(self, instrument_key: str, frm: date, to: date,
                              volume: bool = False) -> dict[str, list[list]]:
        """1-minute bars of a stock or an index by session, {day: [[HH:MM, o, h, l, c], ...]}, frm..to,
        from `candles`.  volume=True adds the minute's traded volume as a sixth column, for anything
        that needs it - a VWAP, relative volume (an index has none: Upstox reports 0)."""
        out: dict[str, list[list]] = {}
        for c in await self.candles(instrument_key, "1m", frm, to):
            out.setdefault(c["timestamp"][:10], []).append(
                [c["timestamp"][11:16], c["open"], c["high"], c["low"], c["close"]] + ([c["volume"]] if volume else []))
        return out

    async def option_candles(self, contract: dict, day: date, interval_minutes: int = 1,
                             volume: bool = False) -> list[list]:
        """One session of an option contract as [[HH:MM, o, h, l, c], ...] ([] if it did not trade),
        from NAME_<CE|PE>_<strike>_<expiry>_candles.json.  `contract` is what `resolve_option`
        returned.  1-minute only: build bigger candles with `resample`.

        volume=True adds the minute's traded volume as a sixth column.  Upstox returns a candle for a
        minute in which nothing traded (volume 0, usually open = high = low = close); its "price"
        is the last trade, not one anybody could have filled at, so a rule that wants real fills
        reads the volume and treats such a minute as no trade (RUN.md rule 6).  build_payload keeps
        only the first five columns for the charts.

        A contract with no file, or a day outside the file's fetched ranges, is noted as missing
        and returns [] - the caller logs it as no data."""
        if interval_minutes != 1:
            raise ValueError("local option candles are 1-minute; build bigger ones with resample()")
        c = contract if contract.get("underlying") else _contract_by_key(contract["instrument_key"])
        if c is None:
            _NOTES.add(f"option {contract['instrument_key']}: in no local contract list")
            return []
        name = c["underlying"]
        opt = _option_name(c.get("option_type") or c["type"], c["strike"], c["expiry"])
        got = _option_file(f"{name}_{opt}_candles.json")
        d_ = day.isoformat()
        if got is None or not any(a <= d_ <= b for a, b in got[0]):
            _missing(f"candles {name} --opt {opt}", day, day)
            return []
        return [r[:6] if volume else r[:5] for r in got[1].get(d_, [])]


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
    """ATM moved `steps` strikes: in the money for a CE is BELOW spot, for a PE ABOVE.

    `steps` are NIFTY strikes (50 points).  On another index the distance is the same share of the
    price - steps x 50 x price_scale() - rounded to that index's own `step` (the user, 2026-09-30):
    6 NIFTY strikes (300 points, about 1.2%) are 10 SENSEX strikes (1,000 points).  NIFTY is unchanged."""
    atm = atm_strike(spot, step)
    sign = -1 if option_type == "CE" else 1
    n = steps if instrument() == REFERENCE_INSTRUMENT else round(steps * REFERENCE_STEP * price_scale() / step)
    return atm + (sign if itm else -sign) * n * step


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
# The user, 2026-09-29: backtest STRICTLY the 143 sessions on local disk, 2026-01-01 .. 2026-07-31,
# nothing before or after (candles before the start are read only as an indicator's warm-up, never
# traded).  Both ends are fixed; move them here, and nowhere else, only when the user asks.
# No individual strategy script should define its own defaults.
START_DATE = date(2026, 1, 1)
END_DATE = date(2026, 7, 31)

# Keep the historical one-year guard, but never reject the shared growing default window once
# it becomes older than a year.
MAX_WINDOW_DAYS = max(366, (END_DATE - START_DATE).days)


def fetch_estimate(calls: int, limits=None) -> str:
    """How long `calls` requests will take under the rolling windows - printed before a ladder
    starts, so a run that is going to take an hour says so at the top instead of at the end."""
    if not ALLOW_FETCH:
        return f"{calls} reads from local disk, no Upstox calls"
    limits = limits or Upstox.RATE_LIMITS
    secs = max(calls * win / cap for win, cap in limits)
    return (f"{calls} requests, about {secs / 60:.0f} min at the rate limit"
            if secs >= 90 else f"{calls} requests, under two minutes")


def check_window(frm: date, to: date, max_days: int = MAX_WINDOW_DAYS) -> None:
    """Refuse a window longer than the shared default/cap.  Fetching is the expensive part of a run - a strike
    ladder over two years is thousands of option-candle calls and gigabytes held in memory for
    charts nobody opens.  A wider run is a deliberate act: pass max_days= to allow it and say
    in meta["limits"] why.  A window outside START_DATE .. END_DATE is refused outright: the user
    backtests those sessions only."""
    if to < frm:
        raise SystemExit(f"--to {to} is before --from {frm}")
    if frm < START_DATE or to > END_DATE:
        raise SystemExit(f"window {frm} .. {to} leaves {START_DATE} .. {END_DATE}, the only sessions the user "
                         f"backtests (py_funcs START_DATE / END_DATE)")
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
# 6  costs and categories - READ FROM THE BROKER
#
# Every strategy belongs to one CATEGORY (intraday stocks, index options, stock options).  The
# category fixes where its script and report live, how many units a trade is, how it is charged
# and what capital it ties up.  The rates below were read from Upstox's own charges API
# (/v2/charges/brokerage, this account) on 2026-09-24 and are re-checked against it by
# `broker_check()` on a run the user allows to call Upstox; regulatory rates carry the date they took effect, so a trade is charged
# what was in force on ITS day.  Change a rate here, with its date and source, never in a script.
# ---------------------------------------------------------------------------
BROKER_READ_ON = "2026-09-24"
# Brokerage is the ACCOUNT's plan, not a market fact, so it is applied to every date: Upstox
# Plus charges Rs 30 per executed order (the standard plan is Rs 20).  Read from the broker API.
BROKERAGE_PER_ORDER = 30.0
EQ_INTRADAY_BROKERAGE_CAP = 0.001   # intraday equity: Rs 30 or 0.1% of the order, whichever is lower
SEBI_RATE = 10.0 / 1e7              # Rs 10 per crore, every segment
GST_RATE = 0.18                     # on brokerage + exchange transaction + IPFT + SEBI
STAMP_BUY_RATE = 0.00003            # 0.003% of the buy leg: options and intraday equity alike
# Exchange transaction charges as the broker bills them INCLUDE the NSE IPFT levy.
OPT_EXCHANGE_RATE = 0.0003503       # NSE options, on premium turnover (from 2024-10-01)
OPT_IPFT_RATE = 0.5 / 1e5           # Rs 0.50 per lakh of premium
EQ_EXCHANGE_RATE = 0.0000297        # NSE cash market (from 2024-10-01)
EQ_IPFT_RATE = 10.0 / 1e7           # Rs 10 per crore
EQ_INTRADAY_STT = 0.00025           # 0.025% of the sell leg
# STT on the SALE of an option, on the premium: 0.1% from 2024-10-01, 0.15% from 2026-04-01
# (Union Budget 2026).  (effective date, rate), oldest first.
OPT_STT_SCHEDULE = ((date(2024, 10, 1), 0.001), (date(2026, 4, 1), 0.0015))
EXCHANGE_RATE = OPT_EXCHANGE_RATE   # older name, kept for scripts that read it
# BSE options (SENSEX, BANKEX), read from the Upstox charges API on 2026-09-30: a live SENSEX option,
# Rs 10 lakh of premium bought -> brokerage Rs 30, transaction Rs 50 (0.005%), IPFT 0, SEBI 0, stamp
# Rs 30, GST 18% of brokerage + transaction.  STT is the same statutory schedule on either exchange.
BSE_READ_ON = "2026-09-30"
BSE_OPT_EXCHANGE_RATE = 0.00005     # of premium turnover, both legs
BSE_OPT_IPFT_RATE = 0.0
BSE_SEBI_RATE = 0.0                 # the broker's calculator charges none on BSE options


def _on(day) -> date:
    if day is None:
        return datetime.now(IST).date()
    return day if isinstance(day, date) else date.fromisoformat(str(day)[:10])


def option_stt_rate(day=None) -> float:
    """STT on an option sale in force on `day` (today when None).  Before the first entry the
    first rate is used - the schedule is only kept from 2024-10-01, where option data starts."""
    d, rate = _on(day), OPT_STT_SCHEDULE[0][1]
    for since, r in OPT_STT_SCHEDULE:
        if d >= since:
            rate = r
    return rate


def option_costs(buy_turnover: float, sell_turnover: float, orders: int = 2, day=None,
                 exchange: str | None = None, sell_day=None) -> dict:
    """Charges on one completed option trade (index or stock options - NSE charges them alike)
    from the rupee premium turnover of each leg, at the rates in force on `day`.  `exchange` 'BSE'
    (SENSEX) uses BSE's transaction rate; None = the exchange of the active index (`exchange_of`).
    `sell_day` = the day of the SALE leg: STT is charged at the rate in force that day (audit fix,
    2026-10-01 - an overnight trade sold after a rate change pays the new rate); None = `day`."""
    bse = (exchange or exchange_of()) == "BSE"
    brokerage = BROKERAGE_PER_ORDER * orders
    stt = option_stt_rate(sell_day if sell_day is not None else day) * sell_turnover
    exch = ((BSE_OPT_EXCHANGE_RATE + BSE_OPT_IPFT_RATE) if bse else (OPT_EXCHANGE_RATE + OPT_IPFT_RATE)) \
        * (buy_turnover + sell_turnover)
    sebi = (BSE_SEBI_RATE if bse else SEBI_RATE) * (buy_turnover + sell_turnover)
    stamp = STAMP_BUY_RATE * buy_turnover
    gst = GST_RATE * (brokerage + exch + sebi)
    return {"brokerage": brokerage, "stt": stt, "exchange": exch, "sebi": sebi, "stamp": stamp,
            "gst": gst, "total": round(brokerage + stt + exch + sebi + stamp + gst, 2)}


def option_round_trip(side: str, entry_px: float, exit_px: float, qty: int, day=None,
                      exchange: str | None = None, exit_day=None) -> float:
    """Total costs of one option trade.  side LONG = bought then sold, SHORT = sold then bought.
    `day` = the entry day, `exit_day` = the exit day (None = the same day).  The sale tax uses the
    day of the sale: the exit day for LONG, the entry day for SHORT."""
    e, x = entry_px * qty, exit_px * qty
    return (option_costs(e, x, day=day, exchange=exchange, sell_day=exit_day)["total"] if side == "LONG"
            else option_costs(x, e, day=day, exchange=exchange, sell_day=day)["total"])


def equity_intraday_costs(buy_turnover: float, sell_turnover: float, orders: int = 2, day=None) -> dict:
    """Charges on one completed intraday (MIS) cash-equity trade from the rupee turnover of each
    leg.  Brokerage is per order: Rs 30 or 0.1% of that order, whichever is lower."""
    per_leg = [min(BROKERAGE_PER_ORDER, EQ_INTRADAY_BROKERAGE_CAP * v) for v in (buy_turnover, sell_turnover)]
    brokerage = sum(per_leg) * orders / 2
    stt = EQ_INTRADAY_STT * sell_turnover
    exch = (EQ_EXCHANGE_RATE + EQ_IPFT_RATE) * (buy_turnover + sell_turnover)
    sebi = SEBI_RATE * (buy_turnover + sell_turnover)
    stamp = STAMP_BUY_RATE * buy_turnover
    gst = GST_RATE * (brokerage + exch + sebi)
    return {"brokerage": brokerage, "stt": stt, "exchange": exch, "sebi": sebi, "stamp": stamp,
            "gst": gst, "total": round(brokerage + stt + exch + sebi + stamp + gst, 2)}


def equity_round_trip(side: str, entry_px: float, exit_px: float, qty: int, day=None) -> float:
    """Total costs of one intraday equity trade.  side LONG = bought then sold, SHORT = sold then
    bought back (the sell leg, which carries STT, is then the entry)."""
    e, x = entry_px * qty, exit_px * qty
    return (equity_intraday_costs(e, x, day=day)["total"] if side == "LONG"
            else equity_intraday_costs(x, e, day=day)["total"])


# The three categories.  `folder` is the sub-folder of analysis/scripts/ AND analysis/report/;
# a script declares CATEGORY = "<key>" and puts it in meta["category"].
CATEGORIES = {
    "stock_intraday": {
        "label": "Intraday stocks - cash equity, MIS",
        "kind": "equity", "segment": "NSE_EQ", "product": "I",
        "units": "ONE SHARE per trade at the stock's full price - no lots, no leverage (the user, 2026-09-28)",
        "costs": "equity_round_trip: brokerage Rs 30 or 0.1% per order (lower), STT 0.025% on the sell leg, "
                 "NSE 0.00297% + IPFT Rs 10/cr, stamp 0.003% on the buy leg, SEBI Rs 10/cr, GST 18%",
        "capital": "not reported: the broker gives no historical MIS margin, so the report is in POINTS "
                   "per share (no rupee P&L, costs, margin or leverage).  broker_margin_ratio still gives "
                   "today's margin for sizing a live trade",
        "holding": "same session only: MIS is squared off by the broker before the close",
        "report_unit": "points",
    },
    "index_options": {
        "label": "Index options - NIFTY, SENSEX ...",
        "kind": "option", "segment": "NSE_FO", "product": "D",
        "units": "lots x the resolved contract's lot_size (the size in force for that expiry)",
        "costs": "option_round_trip: brokerage Rs 30 per order, STT on the sale 0.1% of premium "
                 "(0.15% from 2026-04-01, at the rate of the day of the sale), NSE 0.03503% + IPFT Rs 0.50/lakh, stamp 0.003% on the buy leg, "
                 "SEBI Rs 10/cr, GST 18%.  SENSEX (BSE): BSE 0.005% of premium, no IPFT or SEBI fee "
                 "(read from the Upstox charges API on 2026-09-30), the rest the same",
        "capital": "bought: premium x qty.  Sold: the broker's SPAN + exposure margin for the lot "
                   "(broker_margin), an estimate at today's margin",
        "holding": "intraday or overnight (NRML); a bought option is not held through its expiry day",
        "report_unit": "rupees",
    },
    "stock_options": {
        "label": "Stock options - RELIANCE, HDFCBANK ...",
        "kind": "option", "segment": "NSE_FO", "product": "D",
        "units": "lots x the resolved contract's lot_size (stock lots are revised by NSE; read per contract)",
        "costs": "option_round_trip - NSE charges stock options exactly as index options (same schedule). "
                 "Physical settlement: an ITM stock option held into expiry is DELIVERED - exit before it",
        "capital": "bought: premium x qty.  Sold: the broker's SPAN + exposure margin (broker_margin)",
        "holding": "intraday or overnight (NRML); never into expiry (physical settlement)",
        "report_unit": "rupees",
    },
}


def category_of(key: str) -> dict:
    if key not in CATEGORIES:
        raise ValueError(f"category must be one of {list(CATEGORIES)}, got {key!r}")
    return CATEGORIES[key]


def trade_costs(category: str, side: str, entry_px: float, exit_px: float, qty: int, day=None,
                exit_day=None) -> float:
    """Round-trip costs of one trade in `category`, at the rates in force on `day` (the sale tax of an
    option at the rate of the sale's own day - see option_round_trip)."""
    c = category_of(category)
    if c["kind"] == "equity":
        return equity_round_trip(side, entry_px, exit_px, qty, day=day)
    return option_round_trip(side, entry_px, exit_px, qty, day=day, exit_day=exit_day)


async def broker_charges(up: "Upstox", instrument_key: str, qty: int, price: float, side: str,
                         product: str) -> float:
    """What the BROKER says one order costs (Upstox /v2/charges/brokerage), in rupees."""
    d = await up.get(f"{BASE_V2}/charges/brokerage", {"instrument_token": instrument_key, "quantity": qty,
                                                      "product": product, "transaction_type": side,
                                                      "price": price})
    return float(((d.get("data") or {}).get("charges") or {}).get("total") or 0.0)


async def broker_check(up: "Upstox", category: str, instrument_key: str, qty: int, price: float) -> str:
    """Price one round trip (buy and sell at `price`) with the model AND with the broker's own
    calculator, today, and say whether they agree.  Every script calls it once and prints the
    line; a disagreement means a rate in section 6 is stale - fix it there, with its date.
    A live call: without PYFUNCS_ALLOW_FETCH=1 the line says SKIPPED."""
    c = category_of(category)
    try:
        broker = (await broker_charges(up, instrument_key, qty, price, "BUY", c["product"])
                  + await broker_charges(up, instrument_key, qty, price, "SELL", c["product"]))
    except (RuntimeError, PermissionError) as exc:
        return f"broker check SKIPPED for {category}: {exc}"
    model = trade_costs(category, "LONG", price, price, qty)
    ok = abs(model - broker) <= max(0.5, 0.01 * broker)
    return (f"broker check {category}: {qty} @ {price:g} round trip - model Rs {model:.2f}, "
            f"Upstox Rs {broker:.2f} - {'AGREE' if ok else 'DISAGREE: update the rates in py_funcs section 6'}")


async def broker_margin(up: "Upstox", instrument_key: str, qty: int, price: float, side: str,
                        product: str) -> float:
    """The broker's required margin for one order today (Upstox /v2/charges/margin), rupees."""
    d = await up.post(f"{BASE_V2}/charges/margin", {"instruments": [
        {"instrument_key": instrument_key, "quantity": qty, "transaction_type": side, "product": product,
         "price": price}]})
    return float((d.get("data") or {}).get("required_margin") or 0.0)


async def broker_margin_ratio(up: "Upstox", instrument_key: str, qty: int, price: float,
                              product: str = "I") -> float:
    """Margin / position value for a cash-equity order today (MIS: product 'I').  Capital for an
    intraday-stock trade is its position x this ratio; say in meta['limits'] it is today's ratio."""
    m = await broker_margin(up, instrument_key, qty, price, "BUY", product)
    return m / (qty * price)


# ---------------------------------------------------------------------------
# 6c  corporate events from NSE (not an Upstox fact: Upstox has no results calendar)
# ---------------------------------------------------------------------------
NSE_HOME = "https://www.nseindia.com/"
NSE_API = "https://www.nseindia.com/api/"
NSE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124 Safari/537.36")


async def nse_results_stamps(symbol: str, frm: date, to: date) -> list[datetime] | None:
    """When a company's quarterly RESULTS became public, as IST datetimes (naive), oldest first.

    Source: NSE corporate announcements ('Outcome of Board Meeting' / 'Financial Result Updates'
    that mention financial results), plus the financial-results feed's broadcast times, plus
    scheduled results board meetings with no disclosure found (assumed 18:00, after the close).
    Several filings of one quarter (standalone, then consolidated a day later) collapse to the
    first.  Returns None when NSE cannot be reached - a caller must then say the event tag is
    unknown rather than treat every day as event-free (RULE 6).  Nothing is written to disk.
    A live call: None unless PYFUNCS_ALLOW_FETCH=1."""
    if not ALLOW_FETCH:
        print(f"  ! NSE results calendar for {symbol} not fetched: {NO_FETCH}")
        return None
    f, t = frm.strftime("%d-%m-%Y"), to.strftime("%d-%m-%Y")
    hdr = {"User-Agent": NSE_UA, "Referer": NSE_HOME, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": NSE_UA}, follow_redirects=True) as c:
            await c.get(NSE_HOME)                                        # sets the session cookies
            q = f"index=equities&symbol={quote(symbol)}"
            ann = (await c.get(f"{NSE_API}corporate-announcements?{q}&from_date={f}&to_date={t}", headers=hdr)).json()
            fr = (await c.get(f"{NSE_API}corporates-financial-results?{q}&period=Quarterly", headers=hdr)).json()
            bm = (await c.get(f"{NSE_API}corporate-board-meetings?{q}&from_date={f}&to_date={t}", headers=hdr)).json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"  ! NSE results calendar unavailable for {symbol} ({exc})")
        return None
    stamps: list[datetime] = []
    for r in ann if isinstance(ann, list) else []:
        text = f"{r.get('desc') or ''} {r.get('attchmntText') or ''}".lower()
        if r.get("desc") in ("Outcome of Board Meeting", "Financial Result Updates") and "financial result" in text:
            stamps.append(datetime.strptime(r["an_dt"], "%d-%b-%Y %H:%M:%S"))
    for r in fr if isinstance(fr, list) else []:
        if r.get("broadCastDate"):
            stamps.append(datetime.strptime(r["broadCastDate"], "%d-%b-%Y %H:%M:%S"))
    out: list[datetime] = []
    for s in sorted(stamps):
        if not out or (s - out[-1]).days > 4:
            out.append(s)
    known = {s.date() for s in out}
    for r in bm if isinstance(bm, list) else []:
        if "result" in f"{r.get('bm_purpose', '')} {r.get('bm_desc', '')}".lower():
            d = datetime.strptime(r["bm_date"], "%d-%b-%Y")
            if d.date() not in known and not any(abs((d.date() - k).days) <= 4 for k in known):
                out.append(d.replace(hour=18))
                known.add(d.date())
    return sorted(s for s in out if frm <= s.date() <= to)


async def nse_exdividend_days(symbol: str, frm: date, to: date) -> set[str] | None:
    """Ex-dividend dates ("YYYY-MM-DD") from NSE corporate actions.  On an ex-date the open gaps
    down by the dividend mechanically - not a market move - so a gap rule should know about it.
    None when NSE cannot be reached (say so; never treat it as 'no dividends').
    A live call: None unless PYFUNCS_ALLOW_FETCH=1."""
    if not ALLOW_FETCH:
        print(f"  ! NSE corporate actions for {symbol} not fetched: {NO_FETCH}")
        return None
    f, t = frm.strftime("%d-%m-%Y"), to.strftime("%d-%m-%Y")
    hdr = {"User-Agent": NSE_UA, "Referer": NSE_HOME, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": NSE_UA}, follow_redirects=True) as c:
            await c.get(NSE_HOME)
            rows = (await c.get(f"{NSE_API}corporates-corporateActions?index=equities&symbol={quote(symbol)}"
                                f"&from_date={f}&to_date={t}", headers=hdr)).json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"  ! NSE corporate actions unavailable for {symbol} ({exc})")
        return None
    out = set()
    for r in rows if isinstance(rows, list) else []:
        if "dividend" in str(r.get("subject", "")).lower() and r.get("exDate") not in (None, "", "-"):
            out.add(datetime.strptime(r["exDate"], "%d-%b-%Y").date().isoformat())
    return out


YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


def yahoo_file(ticker: str) -> str:
    """The local file of a Yahoo daily series: yahoo_<ticker>_daily.json in LOCAL_DATA_DIR, the ticker
    with ^ dropped and = . - turned into _ (^N225 -> yahoo_N225_daily.json, 000001.SS -> yahoo_000001_SS_daily.json).
    Format: {ticker, name, source, fetched_utc, timezone, fetched: [[from, to]], candles: [[day, o, h, l, c], ...]}."""
    safe = ticker.replace("^", "").replace("=", "_").replace(".", "_").replace("-", "_")
    return f"yahoo_{safe}_daily.json"


async def yahoo_daily(ticker: str, frm: date, to: date) -> list[list] | None:
    """Daily bars of a market Upstox does not carry (Asian and US indices, commodities, FX):
    [[YYYY-MM-DD, open, high, low, close], ...] oldest first.

    LOCAL FIRST (the user, 2026-09-30): if `yahoo_file(ticker)` is on local disk it is the only source,
    and a part of frm..to outside its fetched ranges is noted as missing (never filled).  Without the
    file, Yahoo Finance's chart API is a live call: None unless PYFUNCS_ALLOW_FETCH=1, and None when
    Yahoo cannot be reached - the caller must then say the factor is unknown (RULE 6), never treat it
    as flat.  Nothing is written to disk by this function.

    The date is the EXCHANGE's own calendar day (Tokyo's session of 2026-03-02 is '2026-03-02',
    and it opens at 05:30 IST - before NSE's pre-open), so a caller pairing it with an NSE session
    must decide which of its prices were known at that minute.  Bars without a close are dropped."""
    fname = yahoo_file(ticker)
    blob = _local(fname)
    if blob is not None:
        lo, hi = frm.isoformat(), to.isoformat()
        for a, b in _gaps(frm, to, blob.get("fetched") or []):
            _NOTES.add(f"yahoo {ticker}: {a}..{b} not inside {fname}'s fetched ranges - unknown on those days")
        return [[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4])]
                for r in blob.get("candles") or [] if lo <= r[0] <= hi and r[4] is not None]
    if not ALLOW_FETCH:
        print(f"  ! Yahoo daily bars for {ticker} not fetched: {NO_FETCH}")
        return None
    p1 =int(datetime(frm.year, frm.month, frm.day, tzinfo=timezone.utc).timestamp())
    p2 = int((datetime(to.year, to.month, to.day, tzinfo=timezone.utc) + timedelta(days=1)).timestamp())
    try:
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": NSE_UA}, follow_redirects=True) as c:
            r = await c.get(YAHOO_CHART.format(ticker=quote(ticker, safe="")),
                            params={"period1": p1, "period2": p2, "interval": "1d", "includePrePost": "false"})
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        print(f"  ! Yahoo daily bars unavailable for {ticker} ({exc})")
        return None
    off = int(res.get("meta", {}).get("gmtoffset") or 0)
    q = (res.get("indicators", {}).get("quote") or [{}])[0]
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        o, h, l, c_ = ((q.get(k) or [])[i] if i < len(q.get(k) or []) else None
                       for k in ("open", "high", "low", "close"))
        if None in (o, h, l, c_):
            continue
        day = datetime.fromtimestamp(ts + off, timezone.utc).date().isoformat()
        if frm.isoformat() <= day <= to.isoformat():
            out.append([day, float(o), float(h), float(l), float(c_)])
    return out


def results_reaction_days(stamps: list[datetime], sessions: list[str]) -> dict[str, str]:
    """{session: 'results day 1' | 'results day 2'} - the first session that trades with the
    results known, and the one after it.  A disclosure during market hours makes the NEXT
    session day 1 (the rest of that afternoon is not an opening-auction question)."""
    days = sorted(sessions)
    out: dict[str, str] = {}
    for s in stamps:
        d, hm = s.date().isoformat(), s.hour * 60 + s.minute
        first = next((x for x in days if x >= d), None) if hm < 9 * 60 + 15 else next((x for x in days if x > d), None)
        if first is None:
            continue
        out[first] = "results day 1"
        i = days.index(first)
        if i + 1 < len(days):
            out.setdefault(days[i + 1], "results day 2")
    return out


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


def worst_fill_breaches(trades: list[dict], index_sessions: dict, own: dict | None = None) -> list[str]:
    """RULE 1 FOR INTRADAY STOCKS, made permanent by the user on 2026-09-28: every trade is filled at
    the WORST price of its candle - a buy (long entry, short exit) at the candle's HIGH, a sell (short
    entry, long exit) at its LOW - with no exception (no pre-open auction price) and no comparison.
    The entry candle is the one after the signal candle, the exit candle the one after the exit
    signal (rules 2-3); a scheduled time exit fills in its own candle.  Returns one line per trade
    that breaks it; build_payload refuses a stock_intraday report that has any."""
    bad = []
    for t in trades:
        src = (own or {}).get(t["symbol"]) or index_sessions
        e = _bar_at(src.get(t["day"]), t["entry_time"])
        x = _bar_at(src.get(t["exit_day"]), t["exit_time"])
        if not e or not x:
            bad.append(f"{t['day']} {t['symbol']}: no {t['entry_time'] if not e else t['exit_time']} candle to check the fill")
            continue
        want_in, want_out = worst_fills(t["side"], e, x)
        if abs(t["entry_px"] - round(want_in, 2)) > 0.006 or abs(t["exit_px"] - round(want_out, 2)) > 0.006:
            bad.append(f"{t['day']} {t['symbol']} {t['side']}: in {t['entry_px']} at {t['entry_time']} (worst "
                       f"{want_in:.2f}), out {t['exit_px']} at {t['exit_time']} (worst {want_out:.2f})")
    return bad


def preopen_fill(rows_1m: list[list]) -> float | None:
    """RULE 1 - THE NAMED EXCEPTION (agreed 2026-09-24) - NOT FOR INTRADAY STOCKS: on 2026-09-28 the user
    made the worst price the only fill for stock_intraday (entry and exit), and build_payload refuses a
    stock report filled at this price.  An order placed in the NSE pre-open session (09:00-09:08,
    equities) is matched in the call auction and fills at the EQUILIBRIUM price, which is the
    session's official open - the OPEN of the 09:15 bar.  Returns None when the 09:15 bar is missing
    (rule 6: no bar, no trade)."""
    for r in rows_1m:
        if r[0] == "09:15":
            return r[1]
        if r[0] > "09:15":
            return None
    return None


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
def trade_economics(side: str, entry_px: float, exit_px: float, qty: int, net: float,
                    capital: float | None) -> dict:
    """What one trade did in the units a trader reads it in.

    pts       price points per unit IN THE TRADE'S FAVOUR (a short that falls 5 is +5).  For a stock
              these are the stock's own points; for an option, premium points.
    move_pct  pts / entry, %.
    notional  entry x qty: the position's value (for a bought option, the premium paid).
    leverage  notional / capital - for an MIS stock trade, position / margin (5x at 20% margin).
    rom       net / capital, %: return on the margin (or premium) the trade tied up."""
    sgn = 1 if side == "LONG" else -1
    pts = round(sgn * (exit_px - entry_px), 2)
    notional = round(entry_px * qty, 2)
    return {"pts": pts, "move_pct": pts / entry_px * 100 if entry_px else None, "notional": notional,
            "leverage": notional / capital if capital else None,
            "rom": net / capital * 100 if capital else None}


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
    costs     rupees; None -> the broker-read schedule (section 6) in force on `day`:
              kind 'option' -> option_round_trip, kind 'equity' -> equity_round_trip (intraday
              MIS).  Any other kind must pass it (0.0 is allowed, deliberately).
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
        if kind == "option":
            costs = option_round_trip(side, entry_px, exit_px, qty, day=day, exchange=exchange_of(symbol),
                                      exit_day=exit_day)
        elif kind == "equity":
            costs = equity_round_trip(side, entry_px, exit_px, qty, day=day)
        else:
            raise ValueError(f"pass costs= for a {kind!r} trade (0.0 if you really mean none)")
    return {"day": day, "exit_day": exit_day or day, "side": side, "symbol": symbol, "kind": kind,
            "entry_time": entry_time, "entry_px": round(entry_px, 2),
            "exit_time": exit_time, "exit_px": round(exit_px, 2), "qty": qty,
            "exit_reason": exit_reason, "gross": gross, "costs": round(costs, 2),
            "net": round(gross - costs, 2),
            "capital": None if capital is None else round(capital, 2),
            "option_type": option_type, "expiry": expiry, "dte": dte,
            "prem_pts": round(prem_pts, 2), "prem_pct": prem_pts / round(entry_px, 2) * 100 if entry_px else None,
            **trade_economics(side, entry_px, exit_px, qty, gross - costs, capital),
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


def script_category() -> str | None:
    """The category of the running script, from its folder: analysis/scripts/<category>/<slug>.py."""
    here = os.path.basename(os.path.dirname(os.path.abspath(sys.argv[0] or "")))
    return here if here in CATEGORIES else None


def rerun_command(slug: str, settings: list[dict] | None, frm, to) -> str:
    """The exact command that reproduces this report - shown in the panel, so a setting that
    needs new data is one paste away instead of a guess."""
    cat = script_category()
    where = f"analysis/scripts/{cat}/{slug}.py" if cat else f"analysis/scripts/{slug}.py"
    parts = [PYTHON_HINT, where, f"--from {frm}", f"--to {to}"]
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
INSTRUMENT_GROUP = "instrument"    # NIFTY / SENSEX - added only when a report holds more than one index
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
    mfes = [t["mfe"] for t in o if t.get("mfe") is not None]
    maes = [t["mae"] for t in o if t.get("mae") is not None]
    moves = [t["move_pct"] for t in o if t.get("move_pct") is not None]
    hold = [(datetime.fromisoformat(f"{t['exit_day']}T{t['exit_time']}")
             - datetime.fromisoformat(f"{t['day']}T{t['entry_time']}")).total_seconds() / 60 for t in o]
    r.update({"avg_win": avg_win, "avg_loss": avg_loss,
              "payoff": avg_win / abs(avg_loss) if avg_win is not None and avg_loss else None,
              "max_dd": mdd, "dd_from": mdd_from, "dd_to": mdd_to, "win_streak": mw, "loss_streak": ml,
              "t": statistics.fmean(net) / (sd / math.sqrt(n)) if sd else None,
              "cap_avg": cap_avg, "roc": r["net"] / cap_avg * 100 if cap_avg else None,
              "mfe_avg": sum(mfes) / len(mfes) if mfes else None,
              "mae_avg": sum(maes) / len(maes) if maes else None,
              "move_avg": sum(moves) / len(moves) if moves else None,
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
    if kind == INSTRUMENT_GROUP:
        return t.get("instrument") or "-"
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


# Two scenarios only: the rule, and the bar close as the one comparison.
FILL_MODES = [
    ("worst", "worst case - buy at the next candle's high, sell at the next candle's low"),
    ("signal", "signal candle - buy at the signal candle's high, sell at the exit candle's low"),
]
# Exits at a set time keep their own minute in every view (the user, 2026-09-30); only an exit a
# price triggered (stop, target, trail, floor ...) moves to the candle that triggered it.
_SCHEDULED_EXIT = re.compile(r"time exit|fixed exit|next-morning|square[- ]?off|expiry|end of day", re.I)


def _bar_at(rows: list[list], hhmm: str) -> list | None:
    for r in rows or []:
        if r[0] == hhmm:
            return r
    return None


def _minute_before(hhmm: str) -> str:
    m = int(hhmm[:2]) * 60 + int(hhmm[3:5]) - 1
    return f"{m // 60:02d}:{m % 60:02d}"


def _price_fills(trades: list[dict], index: dict, option_sessions: dict | None) -> tuple[int, dict]:
    """The SECOND VIEW of every trade (the user, 2026-09-30): the same signals and the same exit minutes,
    re-priced one candle earlier - in at the SIGNAL candle, out at the candle that TRIGGERED the exit.

        worst   (the rule)  a buy fills at the NEXT candle's high, a sell at the NEXT candle's low
        signal              a buy fills at the signal candle's high, a sell at the exit candle's low;
                            a short (stocks) mirrors it: in at the signal candle's low, out at the
                            exit candle's high

    The signal candle is the 1-minute candle just before the entry minute - also when the signal came
    from a bigger candle (the user's choice: its last minute).  The exit candle is the minute before
    the exit fill for an exit a price triggered; an exit at a set time (15:14, 09:30, next morning)
    keeps its own minute.  Never a price nobody could have had: if the signal minute or the trigger
    minute has no candle in the traded instrument (nothing traded, or the entry is the day's first
    minute - a signal known before the open), that leg keeps its worst-case price.  Returns (trades
    re-priced, counts of the legs that kept the worst price)."""
    opt = option_sessions or {}
    done, kept = 0, {"entry": 0, "exit": 0, "scheduled": 0}
    for t in trades:
        src = opt.get(t["symbol"])          # the traded instrument's own bars: an option, or one stock of a book
        if src is None:
            src = index
        e = _bar_at((src or {}).get(t["day"]), t["entry_time"])
        x = _bar_at((src or {}).get(t["exit_day"]), t["exit_time"])
        if not e or not x:
            continue
        long_ = t["side"] == "LONG"
        sgn = 1 if long_ else -1
        s_bar = _bar_at(src.get(t["day"]), _minute_before(t["entry_time"]))
        scheduled = bool(_SCHEDULED_EXIT.search(t.get("exit_reason") or ""))
        x_bar = None if scheduled else _bar_at(src.get(t["exit_day"]), _minute_before(t["exit_time"]))
        kept["entry"] += s_bar is None
        kept["scheduled"] += scheduled
        kept["exit"] += (not scheduled) and x_bar is None
        ep = (s_bar[2] if long_ else s_bar[3]) if s_bar else t["entry_px"]
        xp = (x_bar[3] if long_ else x_bar[2]) if x_bar else t["exit_px"]
        ep, xp = round(ep, 2), round(xp, 2)
        gross = round(sgn * (xp - ep) * t["qty"], 2)
        costs = (round(option_round_trip(t["side"], ep, xp, t["qty"], day=t["day"],
                                         exchange=exchange_of(t["symbol"]), exit_day=t.get("exit_day")), 2)
                 if t.get("kind") == "option" else
                 round(equity_round_trip(t["side"], ep, xp, t["qty"], day=t["day"]), 2)
                 if t.get("kind") == "equity" else t["costs"])
        out = {"worst": {"entry_px": t["entry_px"], "exit_px": t["exit_px"], "gross": t["gross"],
                         "costs": t["costs"], "net": t["net"], "entry_time": t["entry_time"],
                         "exit_time": t["exit_time"], "prem_pts": t.get("prem_pts"), "prem_pct": t.get("prem_pct"),
                         **{k: t.get(k) for k in ("pts", "move_pct", "notional", "leverage", "rom")}},
               "signal": {"entry_px": ep, "exit_px": xp, "gross": gross, "costs": costs,
                          "net": round(gross - costs, 2), "prem_pts": round(xp - ep, 2),
                          "prem_pct": (xp - ep) / ep * 100 if ep else None,
                          "entry_time": s_bar[0] if s_bar else t["entry_time"],
                          "exit_time": x_bar[0] if x_bar else t["exit_time"],
                          **trade_economics(t["side"], ep, xp, t["qty"], round(gross - costs, 2), t.get("capital"))}}
        t["fills"] = out
        done += 1
    return done, kept


def fill_note(priced: int, n: int, kept: dict) -> str:
    """One plain line for meta.limits: what the signal-candle view could and could not re-price."""
    return (f"SECOND VIEW - signal candle: {priced} of {n} trades re-priced in at the signal candle's high and out at "
            f"the exit candle's low (a short mirrored). Kept the worst-case price because nothing traded in that minute "
            f"or the signal came before the open: {kept['entry']} entries, {kept['exit']} exits. Exits at a set time "
            f"({kept['scheduled']}) keep their own minute in both views."
            + (f" {n - priced} trades have no candles kept to re-price and read the same in both views." if priced < n else "")
            + " The worst case stays the rule; this view is a comparison, never a result.")


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


def points_view(t: dict) -> dict:
    """The same trade read in POINTS PER SHARE, for a report whose category has report_unit
    'points' (intraday stocks: the broker gives no historical MIS margin, so rupees, costs,
    margin and leverage are left out).  gross = net = the points in the trade's favour and
    costs = 0, so every statistic of the book - win rate, profit factor, drawdown, t-stat - is
    computed in points by the same code.  A win is a trade that gained points; the costs are
    not in it.  The fill-sensitivity prices are converted the same way."""
    v = dict(t)
    for k in ("capital", "notional", "leverage", "rom", "prem_pts", "prem_pct"):
        v[k] = None
    v.update({"gross": t["pts"], "net": t["pts"], "costs": 0.0, "qty": 1})
    if t.get("fills"):
        v["fills"] = {m: {"entry_px": f["entry_px"], "exit_px": f["exit_px"], "gross": f["pts"], "net": f["pts"],
                          "costs": 0.0, "pts": f["pts"], "move_pct": f.get("move_pct"),
                          **{k: f[k] for k in ("entry_time", "exit_time") if k in f}}
                      for m, f in t["fills"].items()}
    return v


def build_payload(meta: dict, trades: list[dict], index_sessions: dict[str, list[list]],
                  option_sessions: dict[str, dict[str, list[list]]] | None = None,
                  groups: list[dict] | None = None, settings: list[dict] | None = None,
                  chart: str = "default", sessions_log: list[dict] | None = None,
                  worst_only: bool = False, index_by: dict[str, dict[str, list[list]]] | None = None) -> dict:
    """Assemble what the HTML reads.

    index_by  {instrument: {day: rows}} for a report that holds SEVERAL indices (built by
              `run_instruments`, never by a script): every trade then carries `instrument`, is
              charted on its own index, and the page gets an Instrument selector.  index_sessions
              is ignored.  While `run_instruments` is collecting, a script's own call is also
              recorded, so the combined report can be built from the same inputs.

    worst_only  True = the report is the WORST price only (buy at the candle's HIGH, sell at its
              LOW), with no middle / close comparison - what stock_intraday always is.  Every
              trade whose candles are embedded is re-checked and the report is refused if one
              was filled better; trades of settings whose candles are not embedded (chart
              'default' keeps only the rule's own) must be checked by the script itself.

    meta      title, subtitle, instrument, from, to, lot_size, fill_rule, cost_model,
              params {name: value}, rule_steps [str], limits [str], coverage (from `coverage()`).
    trades    from make_trade().
    index_sessions   {day: rows}, full sessions; only the days trades touch are embedded.
    option_sessions  {symbol: {day: rows}} - the TRADED instrument's own bars, for its chart, the
              bar-by-bar table and the fill comparison: an option contract, or, for a book that
              trades several stocks, each stock (index_sessions is then the market index, drawn
              under the stock for context, and each trade's 'underlying move' is its own stock's).
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
    multi = index_by is not None
    if _ACTIVE["collect"] is not None and not multi:          # run_instruments: keep this index's inputs
        _ACTIVE["collect"].append({
            "instrument": instrument(), "rung": _ACTIVE["ladder_rung"], "meta": dict(meta),
            "index_sessions": index_sessions,
            "trades": [dict(t, tags=dict(t["tags"]), variant=dict(t["variant"])) for t in trades],
            "option_sessions": dict(option_sessions or {}), "groups": groups, "settings": settings,
            "chart": chart, "worst_only": worst_only,
            "sessions_log": [dict(r, facts=dict(r.get("facts") or {})) for r in sessions_log or []]})
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
    by = index_by if multi else {None: index_sessions}          # the index sessions, per instrument
    if multi and (odd := sorted({str(t.get("instrument")) for t in trades} - set(index_by))):
        raise ValueError(f"trades on {odd} but index_by holds {list(index_by)}")
    inst_of = (lambda t: t["instrument"]) if multi else (lambda t: None)
    # every session a trade lives through: entry day, exit day, and any session between them
    def lives(t: dict) -> set:
        if t["day"] == t["exit_day"]:
            return {t["day"]}
        return {d for d in by[inst_of(t)] if t["day"] <= d <= t["exit_day"]} | {t["day"], t["exit_day"]}
    need_by: dict = {k: set() for k in by}
    for t in trades:
        need_by[inst_of(t)] |= lives(t)
    need = set().union(*need_by.values())                     # validate_payload reports a missing one
    embedded = {k: {d: _round_rows(r) for d, r in s.items() if d in need_by[k]} for k, s in by.items()}
    index = next(iter(embedded.values()))
    own = option_sessions or {}
    for t in trades:
        # the underlying's move during the trade: the index - or, for one stock of a book of several,
        # that stock itself (its own bars came in option_sessions; the index is then only context)
        src = own.get(t["symbol"]) if t.get("kind") != "option" else None
        for k, day, hhmm in (("entry_spot", t["day"], t["entry_time"]), ("exit_spot", t["exit_day"], t["exit_time"])):
            if t.get(k) is None:
                b = bar_at((src if src is not None else embedded[inst_of(t)]).get(day, []), hhmm,
                           tolerance=3, direction=-1)
                t[k] = b[4] if b else None
        es, xs = t["entry_spot"], t["exit_spot"]
        t["spot_pts"] = None if es is None or xs is None else xs - es
        t["spot_pct"] = None if not es or xs is None else (xs - es) / es * 100
    # the traded instrument's candles: by default only for the trades the rule's own settings produce
    chart_syms = rule_keys = None
    if chart == "default" and declared and spec:
        dflt = {s["key"]: s["default"] for s in spec}
        fopt = {s["key"]: next(o for o in s["options"] if o["value"] == s["default"])
                for s in spec if s["mode"] == "filter"}
        ruled = [t for t in trades if all(t["variant"].get(k) == v for k, v in dflt.items() if k not in fopt)
                 and all(_admits(t, o) for o in fopt.values())]
        chart_syms = {t["symbol"] for t in ruled}
        rule_keys = {(t["symbol"], d) for t in ruled for d in lives(t)}
    elif chart not in ("default", "all"):
        raise ValueError(f"chart must be 'default' or 'all', got {chart!r}")
    opt_syms = {t["symbol"] for t in trades if t.get("kind") == "option"}
    all_keys = {(t["symbol"], d) for t in trades for d in lives(t)}
    opt: dict[str, dict] = {}
    for sym, days in own.items():
        if chart_syms is not None and sym not in chart_syms:
            continue
        if sym in opt_syms:
            want = need
        else:       # one stock of a book: only the sessions its own trades live through
            want = {d for s, d in (rule_keys if rule_keys is not None else all_keys) if s == sym}
        keep = {d: _round_rows(r) for d, r in days.items() if d in want and r}
        if keep:
            opt[sym] = keep
    trades = sorted(trades, key=lambda t: (t["day"], t["entry_time"], t["symbol"]))
    meta = dict(meta)
    # the category decides the folder, the units, the costs and the capital - and the cost model
    # the report prints is the category's broker-read one, never a line a script wrote by hand
    cat = meta.get("category") or script_category()
    if cat is None:
        raise ValueError("meta['category'] is missing and the script is not in analysis/scripts/<category>/ - "
                         f"set CATEGORY to one of {list(CATEGORIES)}")
    if cat == "stock_intraday" or worst_only:
        # RULE 1 for intraday stocks (the user, 2026-09-28), and for any report built with
        # worst_only=True: the WORST price only, both legs, no exception and no comparison - a
        # report is refused if any trade was filled better
        # an option contract can be the rule's rung one night and another rung the next; only the
        # nights whose candles are embedded can be re-checked here - the script checks the rest
        chk = trades if cat == "stock_intraday" else [
            t for t in trades if t["day"] in (own.get(t["symbol"]) or {}) and t["exit_day"] in (own.get(t["symbol"]) or {})]
        bad = worst_fill_breaches(chk, {} if multi else index_sessions, own)
        if bad:
            raise ValueError(f"{len(bad)} trade(s) not filled at the worst price of their candle "
                             "(buy = the candle's HIGH, sell = its LOW):\n  " + "\n  ".join(bad[:15]))
        if worst_only and cat != "stock_intraday":
            print(f"worst fill checked on {len(chk)} of {len(trades)} trades here (the rest by the script)")
    # the second view, for every category (the user, 2026-09-30): the same trades at the signal candle
    priced, kept = _price_fills(trades, {} if multi else index, option_sessions)
    for t in trades:
        t["filters"] = {"side": t["side"], **t["variant"]}      # kept for older readers
    standard = (STANDARD_GROUPS + ([OPTION_GROUP] if any(t.get("option_type") for t in trades) else [])
                + ([DTE_GROUP] if any(t.get("dte") is not None for t in trades) else [])
                + ([INSTRUMENT_GROUP] if multi else []))
    spec_c = category_of(cat)
    here = script_category()
    if here is not None and here != cat:
        raise ValueError(f"meta['category'] is {cat!r} but the script lives in scripts/{here}/")
    meta["category"] = cat
    meta["category_label"] = spec_c["label"]
    meta["cost_model"] = f"{spec_c['costs']}. Rates read from the Upstox charges API on {BROKER_READ_ON}."
    if spec_c.get("report_unit") == "points":
        trades = [points_view(t) for t in trades]
        meta["cost_model"] = None           # nothing in a points report is charged
        meta["lot_size"] = None
    meta["unit"] = spec_c.get("report_unit", "rupees")
    local = [n for n in (built_note(), missing_note()) if n]
    if local:
        meta["limits"] = list(meta.get("limits") or []) + local
    meta.setdefault("generated", datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"))
    meta["settings"] = spec
    meta["sides"] = _sides(trades)
    meta["fill_modes"] = [{"value": k, "label": v} for k, v in FILL_MODES] if priced else []
    if priced:
        meta["limits"] = list(meta.get("limits") or []) + [fill_note(priced, len(trades), kept)]
    if trades and priced != len(trades):
        print(f"NOTE  signal-candle view: {priced} of {len(trades)} trades had their candles to re-price; "
              f"the rest read the same in both views")
    meta["group_defs"] = {"standard": standard, "custom": groups}
    meta["groups"] = standard + [g["name"] for g in groups]
    meta["chart_scope"] = ("every setting" if chart_syms is None else
                           "the rule's own settings only - other settings show metrics but no chart of the "
                           "instrument traded")
    log = sorted(sessions_log or [], key=lambda r: (r["day"], r.get("instrument") or ""))
    counts: dict[str, int] = {k: 0 for k in STATUSES}
    for r in log:
        counts[r["status"]] += 1
    meta["session_counts"] = dict(counts, total=len(log))
    meta["log_columns"] = list(dict.fromkeys(k for r in log for k in r["facts"]))
    # every trading day of the window (market open, traded or not), for the 'average trades per week' card: the page
    # counts the days inside whatever date range the reader picks, so holiday weeks and part-weeks come out exact
    meta["trading_days"] = sorted(set().union(*(trading_days_in(s, meta.get("from"), meta.get("to")) for s in by.values())))
    if multi:
        meta["instruments"] = list(index_by)
    overview = _book(trades)
    overview.update(_per_week(len(trades), len(meta["trading_days"])))
    payload = {"meta": meta, "trades": trades, "sessions": log,
               "baseline": {"overview": overview, "series": _series(trades),
                            "groups": _groups(trades, groups, standard),
                            "stability": _stability(trades, meta.get("break_date"))},
               "candles": {"index": index, "option": opt, **({"index_by": embedded} if multi else {})}}
    validate_payload(payload)
    return payload


def trading_days_in(index_sessions: dict, frm: str | None, to: str | None) -> list[str]:
    """The sessions of the window, oldest first: every day the index has candles, from `frm` to `to` inclusive.
    A script that fetches look-back days before its window (for an average range, a trend) passes them in
    index_sessions too, so the window bounds are applied here rather than trusted."""
    return sorted(d for d in index_sessions if (not frm or d >= frm) and (not to or d <= to))


def _per_week(n_trades: int, n_days: int) -> dict:
    """Average trades per week, measured on TRADING days: weeks = trading days / 5.  A calendar count would call a
    holiday week (4 sessions) a full week and a window that starts on a Thursday one week too; the trading-day count
    gets both right.  The page uses the same formula for any date range and checks itself against this one."""
    weeks = n_days / 5 if n_days else None
    return {"trading_days": n_days, "weeks": weeks, "per_week": n_trades / weeks if weeks else None}


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
        by = p["candles"].get("index_by")
        idx = by.get(t.get("instrument"), {}) if by else p["candles"]["index"]
        for d in {t.get("day"), t.get("exit_day")}:
            if d not in idx:
                bad.append(f"trade {i}: no {t.get('instrument') or 'index'} candles for {d}")
    log = p.get("sessions") or []
    if log:                                   # a session is (instrument, day) - one index per row
        key = lambda r: (r.get("instrument") or "", r["day"])
        days = {key(r) for r in log}
        tdays = {key(t) for t in p["trades"]}
        miss = sorted(tdays - days)
        if miss:
            bad.append(f"{len(miss)} trade day(s) are not in the session log, e.g. {miss[:3]}")
        orphan = sorted({key(r) for r in log if r["status"] == "traded"} - tdays)
        if orphan:
            bad.append(f"{len(orphan)} session(s) logged 'traded' but produced no trade, e.g. {orphan[:3]}")
        seen: dict = {}
        for r in log:
            seen[key(r)] = seen.get(key(r), 0) + 1
        dupes = sorted(k for k, n in seen.items() if n > 1)
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
    """Put `payload` into the template and write analysis/report/<category>/<name>.html.  Returns the path.
    The template is a normal HTML file whose data sits between /*DATA_START*/ and /*DATA_END*/;
    the same function rewrites sample.html itself when asked to.  While `run_instruments` is
    collecting, nothing is written: the one combined report is written when every index has run."""
    if _ACTIVE["collect"] is not None:
        _ACTIVE["collect_name"] = name
        cat = payload.get("meta", {}).get("category")
        return os.path.join(REPORT_DIR, cat, f"{name}.html") if os.path.dirname(name) == "" and cat else name
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
    if os.path.dirname(name) == "":
        cat = m.get("category")
        if cat not in CATEGORIES:
            raise ValueError(f"payload meta['category'] must be one of {list(CATEGORIES)} (build_payload sets it)")
        folder = os.path.join(REPORT_DIR, cat)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{name}.html")
    else:
        path = name
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    mb = len(blob) / 1e6
    cand = len(json.dumps(_clean(payload.get("candles", {})), separators=(",", ":"), default=str)) / 1e6
    n_miss = len(missing_local()) + len(_NOTES)
    print("local data: everything this run asked for was on disk" if not n_miss else
          f"local data: {n_miss} item(s) not on disk, treated as no data - see the NOT ON LOCAL DISK list")
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
    if all(t.get("kind") == "equity" for t in trades):
        b = _book([points_view(t) for t in trades])
        pf = f"{b['pf']:.2f}" if b["pf"] is not None else "n/a"
        return (f"{b['n']} trades, {b['wins']} wins ({b['win']:.1f}%), {b['net']:+,.2f} points per share, "
                f"{b['mean']:+.2f} a trade, profit factor {pf}, max drawdown {b['max_dd']:,.2f} points")
    b = _book(trades)
    pf = f"{b['pf']:.2f}" if b["pf"] is not None else "n/a"
    return (f"{b['n']} trades, {b['wins']} wins ({b['win']:.1f}%), net Rs {b['net']:,.0f}, "
            f"costs Rs {b['costs']:,.0f}, profit factor {pf}, max drawdown Rs {b['max_dd']:,.0f}")


# ---------------------------------------------------------------------------
# 8b  one report, several indices (the user, 2026-09-30)
# ---------------------------------------------------------------------------
_INDEX_WORD = re.compile(r"\bNIFTY(?: 50)?\b|\bNifty 50\b")
_COLUMN_WORD = re.compile(r"\b(?:NIFTY(?: 50)?|Nifty 50|SENSEX)\b")


def _renamed(v, name: str):
    """Free text a NIFTY-born script wrote, read for another index: 'NIFTY' / 'NIFTY 50' -> `name`."""
    if isinstance(v, str):
        return _INDEX_WORD.sub(name, v)
    if isinstance(v, (list, tuple)):
        return [_renamed(x, name) for x in v]
    if isinstance(v, dict):
        return {k: _renamed(x, name) for k, x in v.items()}
    return v


def _merge_lines(lists: list[list], insts: list[str]) -> list:
    """One list of text lines from several indices: a line they all share appears once, a line that
    differs appears once per index, prefixed with the index's name."""
    key = lambda x: json.dumps(x, sort_keys=True, default=str)
    tag = lambda x, i: (f"[{i}] {x}" if isinstance(x, str)
                        else [f"[{i}] {x[0]}", *x[1:]] if isinstance(x, (list, tuple)) and x
                        else dict(x, title=f"[{i}] {x.get('title', '')}") if isinstance(x, dict) else x)
    out: list = []
    if len({len(l) for l in lists}) == 1:                      # the same script: compare line by line
        for items in zip(*lists):
            out += [items[0]] if len({key(x) for x in items}) == 1 else [tag(x, i) for x, i in zip(items, insts)]
        return out
    shared = set.intersection(*({key(x) for x in l} for l in lists))
    done: set = set()
    for l, i in zip(lists, insts):
        for x in l:
            if key(x) not in shared:
                out.append(tag(x, i))
            elif key(x) not in done:
                out.append(x)
                done.add(key(x))
    return out


def _rule_combo(settings: list[dict] | None, trades: list[dict]) -> dict[str, str]:
    """{sweep key: the rule's value} for every sweep but the strike depth - what a trade at another
    strike must match to be kept.  With no declared panel, the derived panel's defaults."""
    spec = settings if settings is not None else _derive_settings(trades)
    return {s["key"]: s["default"] for s in spec if s["mode"] == "sweep" and s["key"] != "moneyness"}


def _combine(parts: list[dict], failed: dict[str, str], own_ladder: bool, rule_rung: int,
             ladder_opts: list[dict], combo: dict[str, str]) -> dict:
    """The one payload of a report that holds several indices and the strike ladder, built from what
    each (index, strike) run passed to build_payload.  The rule's strike keeps every setting; the
    other strikes were already cut to the rule's own settings by `run_instruments`.  Trades,
    sessions and candles are kept per index; the meta text is merged (shared lines once,
    differing ones per index)."""
    rule_parts = [p for p in parts if p["rung"] == rule_rung]
    insts = list(dict.fromkeys(p["instrument"] for p in rule_parts))
    both = " & ".join(insts)
    metas = [p["meta"] if p["instrument"] == REFERENCE_INSTRUMENT else _renamed(p["meta"], p["instrument"])
             for p in rule_parts]
    m = dict(metas[0])
    m.pop("rerun", None)             # a run's own command names one strike; write_report writes the whole ladder's
    for k in ("title", "subtitle"):
        v = rule_parts[0]["meta"].get(k) or ""
        m[k] = (_INDEX_WORD.sub(both, v, count=1) if _INDEX_WORD.search(v)
                else f"{v} - {both}" if k == "title" else v)
    m["instrument"] = both
    m["lot_size"] = " · ".join(f"{i} {x.get('lot_size')}" for i, x in zip(insts, metas))
    for k in ("rule_steps", "limits", "rejected"):
        m[k] = _merge_lines([x.get(k) or [] for x in metas], insts)
    if any(x.get("rule_sections") for x in metas):           # a part that differs by index appears once per index
        m["rule_sections"] = _merge_lines([x.get("rule_sections") or [] for x in metas], insts)
    params: dict = {}
    for k in dict.fromkeys(k for x in metas for k in (x.get("params") or {})):
        vals = [(x.get("params") or {}).get(k) for x in metas]
        same = len({json.dumps(v, sort_keys=True, default=str) for v in vals}) == 1
        params[k] = vals[0] if same else " · ".join(f"{i}: {v}" for i, v in zip(insts, vals))
    m["params"] = dict(params, **{"strike ladder": " · ".join(o["label"] for o in ladder_opts)
                                  + f" (the rule: {rung_label(rule_rung)})"})
    covs = [x.get("coverage") or {} for x in metas]
    m["coverage"] = {"sessions": " · ".join(f"{i} {c.get('sessions')}" for i, c in zip(insts, covs)),
                     "weekday_gaps": sorted(set().union(*(c.get("weekday_gaps") or [] for c in covs))),
                     "short_sessions": {f"{i} {d}": n for i, c in zip(insts, covs)
                                        for d, n in (c.get("short_sessions") or {}).items()}}
    # A strategy that converts NIFTY numbers with its OWN ratio (e.g. one known before the window, onh_v4) passes
    # meta["price_ratio"] = {index: ratio} and meta["price_ratio_basis"]; the note then quotes those (2026-10-01).
    own_ratio = metas[0].get("price_ratio") or {}
    ratio_basis = metas[0].get("price_ratio_basis") or "the median close ratio over the window"
    scaled = "; ".join(
        f"{i}: strike step {strike_step(i):g}, lot {x.get('lot_size')}, "
        + ("the reference" if i == REFERENCE_INSTRUMENT else f"NIFTY points x {own_ratio.get(i, price_scale(i)):.4g}")
        for i, x in zip(insts, metas))
    rungs = sorted({p["rung"] for p in parts}, reverse=True)
    m["limits"] = [
        f"ONE RULE, {len(insts)} INDICES ({scaled}). Each index trades its own candles and options. A number "
        "the rule states in NIFTY points (a stop, a floor, a profile row, a strike depth of N strikes) is the "
        f"same share of the price on the other index: NIFTY points x {ratio_basis}, and "
        "N NIFTY strikes (N x 50 points) the same distance rounded to that index's own strikes. SENSEX options "
        "are charged BSE's rates. 'All (combined)' adds the books together - a day can hold a trade on each "
        "index at once.",
        f"STRIKE LADDER (the user, 2026-09-30): the rule is priced on {len(rungs)} strikes, "
        f"{', '.join(rung_label(r) for r in rungs)}, counted in NIFTY strikes in the money (on SENSEX the same % "
        f"distance: 6 ITM = 10 SENSEX strikes). The rule's own strike ({rung_label(rule_rung)}) carries every "
        "setting in the panel; every other strike is priced on the rule's own settings only, so another setting "
        "at another strike has no trades."
        + ("" if own_ladder else " The strategy itself picks the ATM strike; at another rung the contract is "
                                 "moved that many strikes in the money and everything after (candles, fills, "
                                 "costs, lot) follows it.")] + m["limits"]
    m["limits"] += [f"{i}: NOT IN THIS REPORT - its run failed: {e}" for i, e in failed.items()]
    trades, log, option_sessions, index_by = [], [], {}, {}
    for p in parts:
        i = p["instrument"]
        index_by.setdefault(i, p["index_sessions"])
        for sym, days in p["option_sessions"].items():      # one contract can trade at two rungs on different days
            option_sessions.setdefault(sym, {}).update(days)
        for t in p["trades"]:
            t = dict(t, instrument=i)
            if not own_ladder:
                t["variant"] = dict(t["variant"], moneyness=str(p["rung"]))
            if i != REFERENCE_INSTRUMENT:
                t["note"] = _renamed(t.get("note") or "", i)
                t["levels"] = [dict(l, name=_renamed(l.get("name", ""), i)) for l in t.get("levels") or []]
            trades.append(t)
        for r in p["sessions_log"]:                          # the day log is the rule strike's
            log.append(dict(r, instrument=i, note=_renamed(r.get("note") or "", i) if i != REFERENCE_INSTRUMENT
                            else r.get("note") or "",
                            facts={_COLUMN_WORD.sub("index", k): v for k, v in (r.get("facts") or {}).items()}))
    base = rule_parts[0]
    settings = base["settings"]
    if settings is None:                                     # no declared panel: derive it at the rule's strike
        rule_trades = [t for t in trades if t["variant"].get("moneyness") == str(rule_rung)]
        settings = [dict(s, default=combo.get(s["key"], s["default"])) for s in _derive_settings(rule_trades)
                    if s["key"] != "moneyness"]
    ladder = setting("moneyness", "Strike depth", kind="strike", default=str(rule_rung), options=ladder_opts,
                     help="NIFTY strikes in the money (the same % distance on SENSEX); the rule's own strike "
                          "carries every setting, the others the rule's settings only")
    settings = [ladder if s["key"] == "moneyness" else s for s in settings]
    if not own_ladder:
        settings = settings + [ladder]
    groups = [dict(g, name=_COLUMN_WORD.sub("index", g["name"])) for g in base["groups"] or []]
    return build_payload(m, trades, None, option_sessions, groups, settings=settings,
                         chart=base["chart"], sessions_log=log, worst_only=base["worst_only"], index_by=index_by)


def run_instruments(script: str, instruments=INDEX_INSTRUMENTS, ladder=STRIKE_LADDER) -> str:
    """Run an index strategy on every index on local disk and every strike of the ladder (6 ITM ..
    ATM), and write ONE report: an Instrument selector ('all' adds the books together) and a Strike
    depth setting (the user, 2026-09-30).

    The script is unchanged but for its last lines:
        if __name__ == "__main__":
            run_instruments(__file__)
        elif __name__ == "__instrument__":
            main()
    Its file is executed afresh for each (index, strike) with `instrument()` set, so a constant that
    depends on the index (STEP = strike_step(), a point amount x price_scale()) is right for it.  A
    script with its own "moneyness" setting is run once per strike with --moneyness N; one that
    trades a single strike (ATM) has the contract moved N strikes in the money by `resolve_option`.
    The rule's own strike runs first and keeps every setting; at every other strike only the trades
    of the rule's own settings are kept (the user's choice: the report stays a size a browser can
    open).  Build_payload() inputs are collected, write_report() is held back, and the combined
    report is written at the end.  --instruments NIFTY and --rungs 6,0 narrow the runs.  An index
    whose rule run fails is left out and the report says so."""
    import runpy
    import traceback
    argv = list(sys.argv)
    for flag in ("--instruments", "--rungs"):
        if flag in argv:
            k = argv.index(flag)
            vals = [x.strip().upper() for x in argv[k + 1].split(",") if x.strip()]
            if flag == "--instruments":
                instruments = vals
            else:
                ladder = tuple(int(v) for v in vals)
            del argv[k:k + 2]
    own = 'setting("moneyness"' in open(script, encoding="utf-8").read()
    if "--moneyness" in argv:                        # the report's re-run command names the ladder this way
        k = argv.index("--moneyness")
        ladder = tuple(int(v) for v in argv[k + 1].split(",") if v.strip())
        del argv[k:k + 2]
    ladder_opts = [{"value": str(r), "label": rung_label(r)} for r in ladder]
    rule_rung = 0                                            # a one-strike strategy trades ATM
    if own:                                                  # its own ladder: the rule's rung, and its labels
        g = runpy.run_path(script, run_name="__settings__")
        mset = next(s for s in g["SETTINGS"] if s["key"] == "moneyness")
        rule_rung = int(mset["default"])
        known = {o["value"]: o for o in mset["options"]}
        missing = [r for r in ladder if str(r) not in known]
        if missing:
            raise SystemExit(f"{script}: its moneyness setting has no rung {missing} - widen its options")
        ladder_opts = [{"value": str(r), "label": known[str(r)]["label"]} for r in ladder]
    order = [rule_rung] + [r for r in ladder if r != rule_rung]
    combo: dict | None = None                                # the rule's settings, from the first index
    parts: list[dict] = []
    failed: dict[str, str] = {}
    _ACTIVE.update(collect=parts, collect_name=None)
    try:
        for inst in instruments:
            for r in order:
                _ACTIVE.update(instrument=inst, rung=0 if own else r, ladder_rung=r)
                sys.argv = argv + (["--moneyness", str(r)] if own else [])
                n0 = len(parts)
                print(f"\n{'=' * 18} {inst}  {rung_label(r)} {'=' * 18}", flush=True)
                try:
                    runpy.run_path(script, run_name="__instrument__")
                except (Exception, SystemExit) as exc:
                    traceback.print_exc()
                    del parts[n0:]
                    if r == rule_rung:                       # no rule run: leave the index out
                        failed[inst] = f"{type(exc).__name__}: {exc}"[:300]
                        break
                    failed[f"{inst} {rung_label(r)}"] = f"{type(exc).__name__}: {exc}"[:300]
                    continue
                if len(parts) == n0:
                    failed[inst if r == rule_rung else f"{inst} {rung_label(r)}"] = "the script built no report"
                    if r == rule_rung:
                        break
                    continue
                p = parts[-1]
                if r == rule_rung:
                    if combo is None:
                        combo = _rule_combo(p["settings"], p["trades"])
                    continue
                # another strike: the rule's own settings only
                p["trades"] = [t for t in p["trades"] if all(t["variant"].get(k) == v for k, v in combo.items())]
                syms = {t["symbol"] for t in p["trades"]}
                p["option_sessions"] = {s: d for s, d in p["option_sessions"].items() if s in syms}
                p["sessions_log"] = []
    finally:
        name = _ACTIVE.get("collect_name")
        sys.argv = argv
        _ACTIVE.update(instrument=REFERENCE_INSTRUMENT, collect=None, collect_name=None, rung=0, ladder_rung=None)
    if not any(p["rung"] == rule_rung for p in parts) or not name:
        raise SystemExit(f"no report was built for any index: {failed or 'nothing ran'}")
    payload = _combine(parts, failed, own, rule_rung, ladder_opts, combo or {})
    path = write_report(payload, name)
    print(f"\n{'=' * 18} {payload['meta']['instrument']}: the rule's settings on each strike {'=' * 18}")
    spec = payload["meta"]["settings"]
    dflt = {s["key"]: s["default"] for s in spec if s["mode"] == "sweep" and s["key"] != "moneyness"}
    fopt = [next(o for o in s["options"] if o["value"] == s["default"]) for s in spec if s["mode"] == "filter"]
    ruled = [t for t in payload["trades"] if all(t["variant"].get(k) == v for k, v in dflt.items())
             and all(_admits(t, o) for o in fopt)]
    for r in [x for x in order if any(t["variant"].get("moneyness") == str(x) for t in ruled)]:
        for inst in payload["meta"]["instruments"] + ["all"]:
            mine = [t for t in ruled if t["variant"].get("moneyness") == str(r) and inst in ("all", t["instrument"])]
            print(f"{rung_label(r):<6} {inst:<7} {console_summary(mine)}")
    for what, err in failed.items():
        print(f"FAILED   {what}: {err}")
    print(path)
    return path


def refresh_report(path: str) -> str:
    """Re-wrap a written report in the current template and give it the second (signal-candle) view,
    re-priced from the candles the report already embeds - for a report whose script cannot be
    re-run here (its data is not on local disk).  A trade whose candles were not kept reads the same
    in both views, and the report's limits say how many."""
    with open(path, encoding="utf-8") as f:
        html = f.read()
    p = json.loads(html[html.rindex(DATA_START) + len(DATA_START):html.rindex(DATA_END)])
    trades, c = p["trades"], p.get("candles") or {}
    for t in trades:
        t.pop("fills", None)
    priced, kept = _price_fills(trades, {} if c.get("index_by") else c.get("index") or {}, c.get("option") or {})
    if p["meta"].get("unit") == "points":                       # a points report: the view in points too
        for t in trades:
            for f in (t.get("fills") or {}).values():
                f.update(gross=f["pts"], net=f["pts"], costs=0.0)
    m = p["meta"]
    m["fill_modes"] = [{"value": k, "label": v} for k, v in FILL_MODES] if priced else []
    m["limits"] = [l for l in m.get("limits") or [] if not str(l).startswith("SECOND VIEW")]
    if priced:
        m["limits"].append(fill_note(priced, len(trades), kept))
    return write_report(p, path)
