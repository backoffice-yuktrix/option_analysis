"""One file per feed, extended in place - the single source of market data.

WHY THIS EXISTS
    Every strategy used to keep its own window-named cache
    (nifty_1m_2022-01-01_2026-09-16.json, nifty_1m_2022-01-01_2026-09-17.json,
    ...), so the same candles were stored several times, a new end date meant a
    fresh multi-year download, and a day that simply has no data (a holiday, or
    a session the feed never served) looked exactly like a day nobody had
    fetched yet.  This module replaces all of that with ONE file per feed:

        data/nifty_1m.json           index minute candles
        data/nifty_1d.json           index daily candles
        data/nifty_fut_volume.json   front-month futures volume, by minute
        data/nifty_options.json      option expiries, contracts and candles

    Each file carries its own COVERAGE, so the loader knows the difference
    between "not fetched" and "nothing to fetch":

        covered   list of [from, to] CALENDAR date ranges that have been asked
                  of the broker.  A date inside a covered range with no candles
                  is a non-trading day and is never re-requested.
        days      the candles themselves, keyed by session date.

    Asking for a window fetches only the calendar days outside `covered`, in
    one request per gap, and merges the result in.  Re-running the same window
    costs nothing; extending it by a day fetches one day.

FORMAT
    Minute and daily candles are stored per session as compact rows
    [HH:MM, open, high, low, close] (daily: [date, open, high, low, close]),
    which is about a third of the size of the broker's own row shape.  The
    loaders hand callers the ORIGINAL shape
    ({"timestamp": "...+05:30", "open": ..., ...}), so no strategy has to know.

MISSING DATA
    `coverage_report()` returns, for any window: the sessions present, the
    calendar days never fetched, the trading days that are absent although
    their range was fetched (feed gaps), and any session whose candle count is
    short of the 375 a full NIFTY session has.  Strategies decide what to do;
    the two EOD scripts already treat a short session as HOLD.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import httpx

SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SERVICES_DIR, "..")
DATA_DIR = os.path.join(BACKEND_DIR, "data")
CONFIG_FILE = os.path.join(BACKEND_DIR, "upstox_config.txt")

IST = timezone(timedelta(hours=5, minutes=30), "IST")
SESSION_ROWS = 375                      # 09:15..15:29 inclusive
FULL_SESSION_END = "15:45"              # a session is complete once this has passed

MINUTE_FILE = os.path.join(DATA_DIR, "nifty_1m.json")
DAILY_FILE = os.path.join(DATA_DIR, "nifty_1d.json")
FUTVOL_FILE = os.path.join(DATA_DIR, "nifty_fut_volume.json")
OPTIONS_FILE = os.path.join(DATA_DIR, "nifty_options.json")

UPSTOX_V3 = "https://api.upstox.com/v3"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def read_access_token() -> str | None:
    """The broker token, line 4 of upstox_config.txt.  None when absent."""
    try:
        with open(CONFIG_FILE) as f:
            lines = [l.strip() for l in f.readlines()]
    except OSError:
        return None
    return lines[3] if len(lines) >= 4 and lines[3] else None


def _load_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, path)               # never leave a half-written cache


def _d(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def session_closed_now() -> bool:
    """True once today's session (and its closing auction) is over, so today
    may be marked covered rather than re-requested on the next run."""
    return datetime.now(IST).strftime("%H:%M") >= FULL_SESSION_END


def merge_ranges(ranges: Iterable[Iterable[str]]) -> list[list[str]]:
    """Normalise [from, to] date ranges: sorted, merged, adjacent ones joined."""
    rs = sorted(([str(a), str(b)] for a, b in ranges), key=lambda r: r[0])
    out: list[list[str]] = []
    for r in rs:
        if out and _d(r[0]) <= _d(out[-1][1]) + timedelta(days=1):
            if r[1] > out[-1][1]:
                out[-1][1] = r[1]
        else:
            out.append(list(r))
    return out


def missing_ranges(covered: list[list[str]], frm: date, to: date) -> list[tuple[date, date]]:
    """The calendar sub-ranges of [frm, to] that `covered` does not include."""
    gaps: list[tuple[date, date]] = []
    cur = frm
    for a, b in sorted(covered, key=lambda r: r[0]):
        ca, cb = _d(a), _d(b)
        if cb < cur:
            continue
        if ca > to:
            break
        if ca > cur:
            gaps.append((cur, min(ca - timedelta(days=1), to)))
        cur = max(cur, cb + timedelta(days=1))
        if cur > to:
            return gaps
    if cur <= to:
        gaps.append((cur, to))
    return gaps


# ---------------------------------------------------------------------------
# candle store (index minute + daily)
# ---------------------------------------------------------------------------

class CandleStore:
    """One JSON file of candles for one instrument and interval, extended in
    place.  Rows are [key, open, high, low, close]; `key` is HH:MM for intraday
    intervals and the date for daily ones."""

    def __init__(self, path: str, instrument: str, interval: str) -> None:
        self.path, self.instrument, self.interval = path, instrument, interval
        raw = _load_json(path) or {}
        self.days: dict[str, list] = raw.get("days", {})
        self.covered: list[list[str]] = merge_ranges(raw.get("covered", []))
        self.fetched_days = 0

    # -- shape -----------------------------------------------------------
    def _rows_to_candles(self, day: str, rows: list) -> list[dict]:
        if self.interval == "1d":
            return [{"timestamp": f"{r[0]}T00:00:00+05:30", "open": r[1], "high": r[2],
                     "low": r[3], "close": r[4], "volume": 0, "oi": 0} for r in rows]
        return [{"timestamp": f"{day}T{r[0]}:00+05:30", "open": r[1], "high": r[2],
                 "low": r[3], "close": r[4], "volume": 0, "oi": 0} for r in rows]

    @staticmethod
    def _candle_to_row(c: dict, daily: bool) -> list:
        ts = c["timestamp"]
        return [ts[:10] if daily else ts[11:16], float(c["open"]), float(c["high"]),
                float(c["low"]), float(c["close"])]

    # -- reading ---------------------------------------------------------
    def candles(self, frm: date, to: date) -> list[dict]:
        """Broker-shaped candles for the window, in time order."""
        out: list[dict] = []
        for day in sorted(self.days):
            if frm.isoformat() <= day <= to.isoformat():
                out.extend(self._rows_to_candles(day, self.days[day]))
        return out

    def sessions(self, frm: date, to: date) -> list[str]:
        return [d for d in sorted(self.days) if frm.isoformat() <= d <= to.isoformat()]

    # -- writing ---------------------------------------------------------
    def put(self, candles: list[dict], frm: date, to: date, mark_covered: bool = True) -> int:
        """Merge broker candles in and (optionally) record the range as fetched."""
        daily = self.interval == "1d"
        by_day: dict[str, dict[str, list]] = {}
        for c in candles:
            ts = c.get("timestamp", "")
            if len(ts) < 16:
                continue
            row = self._candle_to_row(c, daily)
            by_day.setdefault(ts[:10], {})[row[0]] = row
        added = 0
        for day, rows in by_day.items():
            have = {r[0]: r for r in self.days.get(day, [])}
            before = len(have)
            have.update(rows)
            self.days[day] = [have[k] for k in sorted(have)]
            added += len(have) - before
        if mark_covered:
            self.mark(frm, to)
        return added

    def mark(self, frm: date, to: date) -> None:
        self.covered = merge_ranges(self.covered + [[frm.isoformat(), to.isoformat()]])

    def save(self) -> None:
        _save_json(self.path, {"instrument": self.instrument, "interval": self.interval,
                               "updated": datetime.now(IST).isoformat(timespec="seconds"),
                               "covered": self.covered, "days": self.days})

    # -- fetching --------------------------------------------------------
    async def ensure(self, frm: date, to: date, token: str | None,
                     offline: bool = False, quiet: bool = False) -> None:
        """Fetch only the calendar days of [frm, to] not already covered."""
        today = datetime.now(IST).date()
        to = min(to, today)
        gaps = missing_ranges(self.covered, frm, to)
        if not gaps:
            return
        if offline or not token:
            if not quiet:
                span = ", ".join(f"{a}..{b}" for a, b in gaps)
                print(f"  ! {os.path.basename(self.path)}: {span} not cached and "
                      f"no fetch (offline={offline}, token={'yes' if token else 'no'})")
            return
        from services.upstox_client import get_candles, INSTRUMENT_KEYS  # noqa: E402
        key = INSTRUMENT_KEYS.get(self.instrument, self.instrument)
        for a, b in gaps:
            hist_to = min(b, today - timedelta(days=1))
            got: list[dict] = []
            if a <= hist_to:
                if not quiet:
                    print(f"  fetching {self.interval} {a} -> {hist_to} ...")
                try:
                    got += await get_candles(token, key, self.interval, a, hist_to)
                except Exception as exc:                          # noqa: BLE001
                    print(f"  ! fetch failed ({exc})")
                    continue
            if a <= today <= b and self.interval == "1m":
                got += await self._intraday(token, key, quiet)
            # today is only marked covered once its session is over, so a
            # partial day is completed on the next run instead of sticking
            mark_to = b if (b < today or session_closed_now()) else b - timedelta(days=1)
            n = self.put(got, a, mark_to) if mark_to >= a else self.put(got, a, a, False)
            self.fetched_days += len({c["timestamp"][:10] for c in got})
            if not quiet and got:
                print(f"    +{n} candles over {len({c['timestamp'][:10] for c in got})} sessions")
        self.save()

    async def _intraday(self, token: str, key: str, quiet: bool) -> list[dict]:
        """Today's candles: the historical endpoint does not serve the current
        day, the intraday one does."""
        from urllib.parse import quote
        from services.upstox_client import _get, _candle_to_dict  # noqa: E402
        url = f"{UPSTOX_V3}/historical-candle/intraday/{quote(key, safe='')}/minutes/1"
        try:
            data = await _get(url, token)
        except Exception as exc:                                  # noqa: BLE001
            if not quiet:
                print(f"  ! intraday fetch failed ({exc})")
            return []
        raw = (data.get("data", {}) or {}).get("candles", []) or []
        got = [_candle_to_dict(c) for c in raw if c]
        if got and not quiet:
            print(f"  fetched {len(got)} intraday candles for today")
        return got


# ---------------------------------------------------------------------------
# public loaders - what the strategies call
# ---------------------------------------------------------------------------

_minute_store: CandleStore | None = None
_daily_store: CandleStore | None = None


def minute_store() -> CandleStore:
    global _minute_store
    if _minute_store is None:
        _minute_store = CandleStore(MINUTE_FILE, "NIFTY", "1m")
    return _minute_store


def daily_store() -> CandleStore:
    global _daily_store
    if _daily_store is None:
        _daily_store = CandleStore(DAILY_FILE, "NIFTY", "1d")
    return _daily_store


def reload_stores() -> None:
    global _minute_store, _daily_store
    _minute_store = _daily_store = None


async def load_minutes(offline: bool, from_date, to_date, token: str | None = None,
                       quiet: bool = False) -> list[dict]:
    """Index minute candles for the window, fetching only what is missing."""
    frm, to = _d(from_date), _d(to_date)
    st = minute_store()
    await st.ensure(frm, to, token if token is not None else (None if offline else read_access_token()),
                    offline, quiet)
    out = st.candles(frm, to)
    if not out:
        raise RuntimeError(f"No minute data for {frm} -> {to}; run online once to fetch it.")
    if not quiet:
        print(f"Loaded {len(out)} NIFTY 1m candles ({len(st.sessions(frm, to))} sessions) "
              f"from {os.path.basename(MINUTE_FILE)}")
    return out


async def load_daily_ohlc(offline: bool, from_date, to_date, token: str | None = None,
                          quiet: bool = False) -> dict[str, dict]:
    """Session date -> official daily OHLC."""
    frm, to = _d(from_date), _d(to_date)
    st = daily_store()
    await st.ensure(frm - timedelta(days=15), to,
                    token if token is not None else (None if offline else read_access_token()),
                    offline, quiet)
    out = {}
    for day in st.sessions(frm - timedelta(days=15), to):
        r = st.days[day][0]
        out[day] = {"o": r[1], "h": r[2], "l": r[3], "c": r[4]}
    if not quiet:
        print(f"Loaded {len(out)} NIFTY daily candles from {os.path.basename(DAILY_FILE)}")
    return out


async def load_daily(offline: bool, from_date, to_date, token: str | None = None,
                     quiet: bool = False) -> dict[str, float]:
    """Session date -> official daily CLOSE (what most strategies want)."""
    return {d: v["c"] for d, v in
            (await load_daily_ohlc(offline, from_date, to_date, token, quiet)).items()}


async def load_fut_volume(offline: bool, from_date, to_date) -> dict:
    """Front-month futures volume by minute ("YYYY-MM-DDTHH:MM" -> volume)."""
    raw = _load_json(FUTVOL_FILE) or {}
    vol = raw.get("minutes", raw)       # tolerate the pre-consolidation shape
    if not vol:
        raise RuntimeError(f"{os.path.basename(FUTVOL_FILE)} is empty; fetch the "
                           f"futures volume before using --weight volume.")
    print(f"Loaded {len(vol)} minutes of NIFTY futures volume from "
          f"{os.path.basename(FUTVOL_FILE)}")
    return vol


# ---------------------------------------------------------------------------
# missing-data report
# ---------------------------------------------------------------------------

def coverage_report(from_date, to_date, interval: str = "1m") -> dict:
    """What the store does and does not have for a window.

    sessions        session dates present
    never_fetched   calendar days outside every covered range
    feed_gaps       weekdays inside a covered range with no candles at all
                    (holidays land here too - the store cannot tell them apart,
                    which is why they are reported rather than re-fetched)
    short_sessions  {date: rows} for sessions with fewer than 375 minute rows
    """
    frm, to = _d(from_date), _d(to_date)
    st = minute_store() if interval == "1m" else daily_store()
    sessions = st.sessions(frm, to)
    have = set(sessions)
    never = []
    for a, b in missing_ranges(st.covered, frm, to):
        d = a
        while d <= b:
            never.append(d.isoformat())
            d += timedelta(days=1)
    never_set = set(never)
    gaps, d = [], frm
    while d <= to:
        iso = d.isoformat()
        if d.weekday() < 5 and iso not in have and iso not in never_set:
            gaps.append(iso)
        d += timedelta(days=1)
    short = {}
    if interval == "1m":
        short = {s: len(st.days[s]) for s in sessions if len(st.days[s]) < SESSION_ROWS}
    return {"sessions": sessions, "never_fetched": never, "feed_gaps": gaps,
            "short_sessions": short, "covered": st.covered}


def print_coverage(from_date, to_date, interval: str = "1m") -> dict:
    r = coverage_report(from_date, to_date, interval)
    print(f"  coverage {from_date} -> {to_date}: {len(r['sessions'])} sessions"
          + (f", {len(r['never_fetched'])} calendar days never fetched" if r["never_fetched"] else "")
          + (f", {len(r['feed_gaps'])} weekday gaps (holidays or feed misses)" if r["feed_gaps"] else "")
          + (f", {len(r['short_sessions'])} short sessions" if r["short_sessions"] else ""))
    if r["short_sessions"]:
        head = ", ".join(f"{d} ({n} rows)" for d, n in list(r["short_sessions"].items())[:5])
        print(f"    short: {head}{' ...' if len(r['short_sessions']) > 5 else ''}")
    return r


# ---------------------------------------------------------------------------
# options - one file for expiries, contracts and candles
# ---------------------------------------------------------------------------

class OptionFile:
    """data/nifty_options.json, the single option store.

        expiries   ["2024-10-03", ...]
        contracts  "EXPIRY|STRIKE|CE" -> {trading_symbol, instrument_key, expired,
                   lot_size} or null when the broker has no such contract (a
                   cached miss, so it is asked for once and never again)
        candles    "EXPIRY|STRIKE|CE|DAY" -> {"HH:MM": [open, high, low, close]},
                   or -> {"HH:MM": close} for the days only ever fetched as
                   closes by the older scripts (listed in `close_only`)
        fetched    the candle keys that have been requested, including the ones
                   that came back empty - this is what stops a contract-day with
                   no trades from being fetched on every run

    A close-only day is stored as a bare number per minute, not a padded
    four-value row: it is half the size and it cannot be mistaken for a real
    high and low by a worst-fill backtest.
    """

    def __init__(self, path: str = OPTIONS_FILE) -> None:
        self.path = path
        raw = _load_json(path) or {}
        self.expiries: list[str] = raw.get("expiries", [])
        self.contracts: dict = raw.get("contracts", {})
        self.candles: dict = raw.get("candles", {})
        self.fetched: set = set(raw.get("fetched", []))
        self.close_only: set = set(raw.get("close_only", []))

    def has(self, key: str) -> bool:
        """True when this contract-day has been asked for (even if it was empty)."""
        return key in self.fetched or key in self.candles

    def closes(self, key: str) -> dict:
        """{"HH:MM": close} for a contract-day - what the older scripts expect."""
        bars = self.candles.get(key) or {}
        return {m: (v if isinstance(v, (int, float)) else v[3]) for m, v in bars.items()}

    def ohlc(self, key: str) -> dict:
        """{"HH:MM": [o, h, l, c]}; empty when only closes were ever stored, so
        a worst-fill backtest never invents a high or a low it does not have."""
        if key in self.close_only:
            return {}
        return self.candles.get(key) or {}

    def put(self, key: str, bars: dict, close_only: bool = False) -> None:
        self.fetched.add(key)
        if bars:
            self.candles[key] = bars
            if close_only:
                self.close_only.add(key)
            else:
                self.close_only.discard(key)

    def save(self) -> None:
        _save_json(self.path, {
            "updated": datetime.now(IST).isoformat(timespec="seconds"),
            "expiries": sorted(set(self.expiries)),
            "contracts": self.contracts,
            "candles": self.candles,
            "fetched": sorted(self.fetched),
            "close_only": sorted(self.close_only),
        })

    # -- reporting -------------------------------------------------------
    def summary(self) -> dict:
        days = {k.split("|")[-1] for k in self.candles}
        return {"expiries": len(self.expiries), "contracts": len(self.contracts),
                "contract_days": len(self.candles), "asked": len(self.fetched),
                "empty": len(self.fetched) - len(self.candles),
                "close_only": len(self.close_only),
                "from": min(days) if days else None, "to": max(days) if days else None}

    # -- dict-like views -------------------------------------------------
    # The pricers used to hold two whole dictionaries of candles in memory (a
    # close-only one and an OHLC one).  These views read straight out of the
    # single store instead, so the file is parsed once and nothing is copied.

    def closes_view(self) -> "_ClosesView":
        return _ClosesView(self)

    def ohlc_view(self) -> "_OhlcView":
        return _OhlcView(self)


class _ClosesView:
    """`{contract-day: {"HH:MM": close}}`, backed by the option file."""

    def __init__(self, of: OptionFile) -> None:
        self._of = of

    def get(self, key, default=None):
        bars = self._of.candles.get(key)
        return self._of.closes(key) if bars else default

    def __getitem__(self, key):
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __setitem__(self, key, closes):
        # only used when the caller has nothing but closes; an OHLC write for
        # the same contract-day afterwards replaces this and clears the marker
        self._of.put(key, {m: float(c) for m, c in (closes or {}).items()}, close_only=True)

    def __contains__(self, key):
        return key in self._of.candles

    def __len__(self):
        return len(self._of.candles)


class _OhlcView:
    """`{contract-day: {"HH:MM": [o, h, l, c]}}`, backed by the option file."""

    def __init__(self, of: OptionFile) -> None:
        self._of = of

    def get(self, key, default=None):
        return self._of.ohlc(key) or default

    def __getitem__(self, key):
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __setitem__(self, key, bars):
        self._of.put(key, {m: [float(v[0]), float(v[1]), float(v[2]), float(v[3])]
                           for m, v in (bars or {}).items()}, close_only=False)

    def __contains__(self, key):
        return key in self._of.candles and key not in self._of.close_only

    def __len__(self):
        return len(self._of.candles) - len(self._of.close_only)


_option_file: OptionFile | None = None


def option_file(reload: bool = False) -> OptionFile:
    """The process-wide option store (parsed once)."""
    global _option_file
    if _option_file is None or reload:
        _option_file = OptionFile()
    return _option_file
