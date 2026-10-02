"""ctx.py - the one data door of the intraday-entry study (protocol.md, frozen 2026-10-02).

Everything a signal, the outcome builder or the scorer reads comes through `Market` / `DayCtx`.

THE DATE WALL.  `Market(index, last_day)` never keeps a row dated after `last_day`:
  * every candle file (index, India VIX, yahoo dailies, each option file) is CUT AS TEXT before it is
    parsed - the rows are ascending on disk, the first row dated after `last_day` is found by a binary
    search on the raw text, and only the text before it is handed to the JSON parser.  Later candles
    are therefore never turned into Python objects.  What was parsed is filtered once more by date.
  * every method that takes a day refuses (ValueError) a day after `last_day`.
  * `last_day` after DISCOVERY_END is refused (PermissionError) unless freeze.json exists (protocol P3.3;
    the full hash check is the runner's job), and anything after WINDOW_END is always refused.

`DayCtx` is what a signal function sees for one index on one day.  `truncated(hhmm)` gives a copy that
only holds candles stamped <= hhmm; `check_no_lookahead` uses it to prove a signal mechanically.

Time strings are "HH:MM" exactly as stamped on disk (IST, candle START); nothing is converted.
"Previous session" is the previous entry of `sessions` (Sunday 2026-02-01 is a real session).

Rows handed out are shared with the cache: NEVER mutate a row (the outer lists are fresh copies).
"""
from __future__ import annotations

import json
import os
import re
import sys
from bisect import bisect_left, bisect_right
from collections import Counter
from operator import itemgetter

import numpy as np

DISCOVERY_END = "2026-04-30"
WINDOW_START = "2026-01-01"
WINDOW_END = "2026-07-31"
WARMUP_START = "2025-11-24"
INDEXES = ("NIFTY", "SENSEX")
DAILY_TICKERS = ("N225", "HSI", "KS11", "000001_SS", "AXJO", "GSPC", "INDIAVIX")

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS_DIR = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
DATA_DIR = os.path.join(ANALYSIS_DIR, "candle_datas")
OUTPUT_DIR = os.path.join(ANALYSIS_DIR, "working strategy reports", "intraday_entry")
FREEZE_PATHS = (os.path.join(HERE, "freeze.json"), os.path.join(OUTPUT_DIR, "freeze.json"))

_HHMM = tuple(f"{m // 60:02d}:{m % 60:02d}" for m in range(1440))
_HHMM_SET = frozenset(_HHMM)
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_ROW = re.compile(r'\[\s*"(\d{4}-\d{2}-\d{2})[T"]')       # the start of one candle row, minute or daily
_T = itemgetter(0)


def minutes(hhmm: str) -> int:
    """ "09:15" -> 555 """
    if hhmm not in _HHMM_SET:
        raise ValueError(f"not an HH:MM time: {hhmm!r}")
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def hhmm(minutes: int) -> str:
    """ 555 -> "09:15" """
    if not 0 <= minutes < 1440:
        raise ValueError(f"minute of day out of range: {minutes!r}")
    return _HHMM[minutes]


def _is_day(d) -> bool:
    return isinstance(d, str) and _DAY.match(d) is not None


# ---------------------------------------------------------------------------
# the wall, at text level
# ---------------------------------------------------------------------------
def wall_cut(text: str, last_day: str) -> tuple[str, bool]:
    """(text to parse, was it cut).  `text` is one candle file whose LAST key is "candles" with rows in
    ascending date order.  Everything from the first row dated after `last_day` is removed and the JSON
    is closed again, so the parser never sees a later candle."""
    k = text.find('"candles"')
    if k < 0:
        return text, False
    first = _ROW.search(text, k)
    if first is None:                                   # no rows at all
        return text, False
    if first.group(1) > last_day:
        cut = first.start()
    else:
        cut, lo, hi = None, first.end(), len(text)      # rows starting before lo are inside the wall
        while lo < hi:
            mid = (lo + hi) // 2
            m = _ROW.search(text, mid)                  # the first row starting at or after mid
            if m is None or m.start() >= hi:            # (no end limit: it would hide a row straddling hi)
                hi = mid
            elif m.group(1) > last_day:
                cut = hi = m.start()
            else:
                lo = m.end()
        if cut is None:
            return text, False
    head = text[:cut].rstrip()
    if head.endswith(","):
        head = head[:-1]
    return head + "]}", True


def read_walled(path: str, last_day: str, stats: dict | None = None) -> dict | None:
    """One candle file as a dict whose "candles" hold no row dated after `last_day`; None if no file."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return None
    cut_text, was_cut = wall_cut(text, last_day)
    blob = None
    if was_cut:
        try:
            blob = json.loads(cut_text)
        except ValueError:
            blob = None
        if not (isinstance(blob, dict) and isinstance(blob.get("candles"), list)):
            blob = None
            if stats is not None:
                stats["fallbacks"] = stats.get("fallbacks", 0) + 1
        elif stats is not None:
            stats["cuts"] = stats.get("cuts", 0) + 1
    del text
    if blob is None:                                    # nothing to cut, or an unexpected layout
        with open(path, encoding="utf-8") as f:
            blob = json.load(f)
    blob["candles"] = [r for r in blob.get("candles", []) if r[0][:10] <= last_day]
    return blob


def freeze_exists() -> bool:
    return any(os.path.isfile(p) for p in FREEZE_PATHS)


class _OptFile:
    """One option contract file, compact: day -> (start, end) into numpy columns."""
    __slots__ = ("fetched", "spans", "mins", "px", "vi")

    def __init__(self, fetched, spans, mins, px, vi):
        self.fetched, self.spans, self.mins, self.px, self.vi = fetched, spans, mins, px, vi


# ---------------------------------------------------------------------------
# Market
# ---------------------------------------------------------------------------
class Market:
    """All local data of one index up to and including `last_day` (the date wall)."""

    def __init__(self, index: str, last_day: str = DISCOVERY_END):
        if index not in INDEXES:
            raise ValueError(f"index must be one of {INDEXES}, got {index!r}")
        if not _is_day(last_day):
            raise ValueError(f"last_day must be 'YYYY-MM-DD', got {last_day!r}")
        if last_day > WINDOW_END:
            raise ValueError(f"last_day {last_day} is after the trading window ({WINDOW_END})")
        if last_day > DISCOVERY_END and not freeze_exists():
            raise PermissionError(
                f"last_day {last_day} opens the holdout (> {DISCOVERY_END}) and there is no freeze.json "
                f"(looked for {FREEZE_PATHS[0]} and {FREEZE_PATHS[1]}) - protocol P3.3")
        self.index = index
        self.last_day = last_day
        self.wall_stats: dict = {"cuts": 0, "fallbacks": 0}

        self._bars = self._load_minute(f"{index}_candles.json")
        self.sessions: list[str] = sorted(self._bars)
        self._pos = {d: i for i, d in enumerate(self.sessions)}
        self._vix = self._load_minute("VIX_candles.json")

        with open(os.path.join(DATA_DIR, f"{index}_expiry.json"), encoding="utf-8") as f:
            self.expiries: list[str] = sorted(set(json.load(f)["expiries"]))
        with open(os.path.join(DATA_DIR, f"{index}_contracts.json"), encoding="utf-8") as f:
            chain = json.load(f)
        self._lots: dict = {}
        gaps: Counter = Counter()
        for exp, cs in chain.items():
            for c in cs:
                self._lots[(exp, c["type"], float(c["strike"]))] = int(c["lot_size"])
            strikes = sorted({float(c["strike"]) for c in cs})
            gaps.update(b - a for a, b in zip(strikes, strikes[1:]))
        if not gaps:
            raise LookupError(f"no option contracts of {index} on disk")
        self.step: float = float(gaps.most_common(1)[0][0])

        self._daily: dict = {}
        self._daily_dates: dict = {}
        self.daily_dropped: dict = {}                    # ticker -> rows dropped for a null price
        for t in DAILY_TICKERS:
            blob = read_walled(os.path.join(DATA_DIR, f"yahoo_{t}_daily.json"), last_day, self.wall_stats)
            if blob is None:
                raise FileNotFoundError(f"yahoo_{t}_daily.json")
            rows, dropped = [], 0
            for r in blob["candles"]:
                if any(v is None for v in r[1:5]):
                    dropped += 1
                    continue
                rows.append([r[0][:10], float(r[1]), float(r[2]), float(r[3]), float(r[4])])
            dates = [r[0] for r in rows]
            if any(a >= b for a, b in zip(dates, dates[1:])):
                raise ValueError(f"yahoo_{t}_daily.json is not in strictly ascending date order")
            self._daily[t], self._daily_dates[t], self.daily_dropped[t] = rows, dates, dropped

        self._opt: dict = {}          # (index, ot, strike, expiry) -> _OptFile | None   (unbounded)
        self._opt_days: dict = {}     # (index, ot, strike, expiry, day) -> rows | None  (unbounded)
        self._house: dict = {}

    # -- loading ----------------------------------------------------------
    def _load_minute(self, fname: str) -> dict:
        blob = read_walled(os.path.join(DATA_DIR, fname), self.last_day, self.wall_stats)
        if blob is None:
            raise FileNotFoundError(os.path.join(DATA_DIR, fname))
        out: dict = {}
        prev = ""
        for r in blob["candles"]:
            ts = r[0]
            if ts <= prev:
                raise ValueError(f"{fname}: rows not in strictly ascending time order at {ts}")
            prev = ts
            d = ts[:10]
            if d < WARMUP_START:
                continue
            out.setdefault(d, []).append([_HHMM[int(ts[11:13]) * 60 + int(ts[14:16])],
                                          float(r[1]), float(r[2]), float(r[3]), float(r[4])])
        return out

    def _opt_file(self, ot: str, strike: float, expiry: str):
        key = (self.index, ot, strike, expiry)
        try:
            return self._opt[key]
        except KeyError:
            pass
        path = os.path.join(DATA_DIR, f"{self.index}_{ot}_{strike:g}_{expiry}_candles.json")
        blob = read_walled(path, self.last_day, self.wall_stats)
        if blob is None:
            self._opt[key] = None
            return None
        rows = blob["candles"]
        n = len(rows)
        fetched = [(a[:10], b[:10]) for a, b in blob.get("fetched", [])]
        spans: dict = {}
        if n:
            prev, start, cur = "", 0, rows[0][0][:10]
            for i, r in enumerate(rows):
                ts = r[0]
                if ts <= prev:
                    raise ValueError(f"{os.path.basename(path)}: rows not strictly ascending at {ts}")
                prev = ts
                if ts[:10] != cur:
                    spans[cur] = (start, i)
                    start, cur = i, ts[:10]
            spans[cur] = (start, n)
            mins = np.fromiter((int(r[0][11:13]) * 60 + int(r[0][14:16]) for r in rows), dtype=np.int16, count=n)
            px = np.array([r[1:5] for r in rows], dtype=np.float64)
            vi = np.array([r[5:7] for r in rows], dtype=np.int64)
            if px.shape != (n, 4) or vi.shape != (n, 2):
                raise ValueError(f"{os.path.basename(path)}: rows are not [ts,o,h,l,c,volume,oi]")
        else:
            mins = px = vi = None
        f = _OptFile(fetched, spans, mins, px, vi)
        self._opt[key] = f
        return f

    def _opt_day(self, ot: str, strike, expiry: str, day: str):
        """The cached rows of one contract on one day (shared - callers copy the outer list), or None."""
        if ot != "CE" and ot != "PE":
            raise ValueError(f"ot must be 'CE' or 'PE', got {ot!r}")
        strike = float(strike)
        key = (self.index, ot, strike, expiry, day)
        try:
            return self._opt_days[key]
        except KeyError:
            pass
        rows = None
        f = self._opt_file(ot, strike, expiry)
        if f is not None and any(a <= day <= b for a, b in f.fetched):
            span = f.spans.get(day)
            if span is not None:
                s, e = span
                rows = [[_HHMM[m], *p, *v] for m, p, v in
                        zip(f.mins[s:e].tolist(), f.px[s:e].tolist(), f.vi[s:e].tolist())]
        self._opt_days[key] = rows
        return rows

    def _wall(self, day: str) -> None:
        if not _is_day(day):
            raise ValueError(f"a day must be 'YYYY-MM-DD', got {day!r}")
        if day > self.last_day:
            raise ValueError(f"{day} is beyond the date wall ({self.last_day})")

    def _house_close(self, d: str) -> float:
        try:
            return self._house[d]
        except KeyError:
            pass
        tp = [(r[2] + r[3] + r[4]) / 3.0 for r in self._bars[d] if "15:00" <= r[0] <= "15:29"]
        if not tp:
            raise ValueError(f"{self.index} {d}: no bars stamped 15:00..15:29")
        self._house[d] = v = sum(tp) / len(tp)
        return v

    # -- public -----------------------------------------------------------
    def bars(self, day: str) -> list:
        """[[ "HH:MM", o, h, l, c ], ...] index bars of that session.  KeyError if it is not a session."""
        self._wall(day)
        return self._bars[day][:]

    def vix_bars(self, day: str) -> list:
        """India VIX 1-minute bars of that day, [] if it has none."""
        self._wall(day)
        return self._vix.get(day, [])[:]

    def expiry(self, day: str) -> str | None:
        """Protocol P2.1: the first expiry at least 1 calendar day after `day` (never today's)."""
        if not _is_day(day):
            raise ValueError(f"a day must be 'YYYY-MM-DD', got {day!r}")
        i = bisect_right(self.expiries, day)
        return self.expiries[i] if i < len(self.expiries) else None

    def lot_size(self, expiry: str, ot: str, strike) -> int | None:
        """Lot size of the listed contract, None if it is not in the contract list."""
        return self._lots.get((expiry, ot, float(strike)))

    def option_bars(self, day: str, ot: str, strike, expiry: str | None = None) -> list | None:
        """[[ "HH:MM", o, h, l, c, volume, oi ], ...] of that day; expiry defaults to self.expiry(day).
        None if there is no file, the day is outside the file's fetched ranges, or it has no rows that day."""
        self._wall(day)
        if expiry is None:
            expiry = self.expiry(day)
            if expiry is None:
                return None
        rows = self._opt_day(ot, strike, expiry, day)
        return None if rows is None else rows[:]

    def daily(self, ticker: str) -> list:
        """[[ "YYYY-MM-DD", o, h, l, c ], ...] of a yahoo daily file, rows dated <= last_day."""
        if ticker not in self._daily:
            raise ValueError(f"ticker must be one of {DAILY_TICKERS}, got {ticker!r}")
        return self._daily[ticker][:]

    def day_ctx(self, day: str) -> "DayCtx":
        self._wall(day)
        if day not in self._pos:
            raise KeyError(f"{day} is not a {self.index} session on disk")
        return DayCtx(self, day, None)

    # -- extras (not in the minimal spec) ---------------------------------
    def max_dates(self) -> dict:
        """The latest date held in every store - the wall, as data."""
        opt = [max(f.spans) for f in self._opt.values() if f is not None and f.spans]
        return {"index": max(self._bars) if self._bars else None,
                "vix": max(self._vix) if self._vix else None,
                "daily": {t: (d[-1] if d else None) for t, d in self._daily_dates.items()},
                "option_files": max(opt) if opt else None,
                "option_days": max((k[4] for k, v in self._opt_days.items() if v is not None), default=None)}

    def drop_option_cache(self) -> None:
        """Free the option caches (they are unbounded by design)."""
        self._opt.clear()
        self._opt_days.clear()


# ---------------------------------------------------------------------------
# DayCtx
# ---------------------------------------------------------------------------
class DayCtx:
    """Everything a signal function may see for one index on one day."""
    __slots__ = ("_m", "index", "day", "step", "expiry", "bars", "prev_sessions", "cutoff")

    def __init__(self, market: Market, day: str, cutoff: str | None = None):
        self._m = market
        self.index = market.index
        self.day = day
        self.step = market.step
        self.expiry = market.expiry(day)
        self.cutoff = cutoff
        full = market._bars[day]
        self.bars = full[:] if cutoff is None else full[:bisect_right(full, cutoff, key=_T)]
        self.prev_sessions = market.sessions[:market._pos[day]]

    def _earlier(self, d: str) -> None:
        if not _is_day(d):
            raise ValueError(f"a day must be 'YYYY-MM-DD', got {d!r}")
        if d >= self.day:
            raise ValueError(f"{d} is not earlier than the ctx day {self.day}")

    def session(self, d: str) -> list:
        """Index bars of an EARLIER session d.  ValueError if d >= self.day, KeyError if d is no session."""
        self._earlier(d)
        return self._m._bars[d][:]

    def house_close(self, d: str) -> float:
        """Average of (h+l+c)/3 over the bars stamped 15:00..15:29 of earlier session d."""
        self._earlier(d)
        return self._m._house_close(d)

    def vix(self) -> list:
        """Today's India VIX bars stamped <= the cutoff."""
        rows = self._m._vix.get(self.day, [])
        return rows[:] if self.cutoff is None else rows[:bisect_right(rows, self.cutoff, key=_T)]

    def vix_session(self, d: str) -> list:
        """India VIX bars of an earlier session ([] if it has none).  ValueError if d >= self.day."""
        self._earlier(d)
        return self._m._vix.get(d, [])[:]

    def daily(self, ticker: str) -> list:
        """Daily rows dated strictly BEFORE self.day."""
        m = self._m
        if ticker not in m._daily:
            raise ValueError(f"ticker must be one of {DAILY_TICKERS}, got {ticker!r}")
        return m._daily[ticker][:bisect_left(m._daily_dates[ticker], self.day)]

    def option(self, ot: str, strike) -> list | None:
        """Today's bars [[hhmm,o,h,l,c,volume,oi]] of the P2-expiry contract stamped <= the cutoff.
        None if unavailable - and also while the contract has no bar stamped <= the cutoff yet, so a
        truncated ctx cannot tell that a contract will print later in the day."""
        if self.expiry is None:
            return None
        rows = self._m._opt_day(ot, strike, self.expiry, self.day)
        if rows is None:
            return None
        if self.cutoff is None:
            return rows[:]
        i = bisect_right(rows, self.cutoff, key=_T)
        return rows[:i] if i else None

    def truncated(self, hhmm: str) -> "DayCtx":
        """A copy whose bars / vix() / option() only contain candles stamped <= hhmm (never widens)."""
        if hhmm not in _HHMM_SET:
            raise ValueError(f"not an HH:MM time: {hhmm!r}")
        c = hhmm if self.cutoff is None or hhmm < self.cutoff else self.cutoff
        return DayCtx(self._m, self.day, c)


# ---------------------------------------------------------------------------
# the mechanical look-ahead check
# ---------------------------------------------------------------------------
SIGNAL_FIRST, SIGNAL_LAST = "09:19", "14:13"          # protocol P1.3


def check_no_lookahead(fn, ctx: DayCtx, params: dict) -> list[str]:
    """Run fn on the full-day ctx.  A signal (t, direction) must be reproduced exactly by
    fn(ctx.truncated(t)) and must NOT exist on fn(ctx.truncated(<minute before t>)).
    Returns the problems found (empty = clean)."""
    tag = f"{ctx.index} {ctx.day}"
    out: list[str] = []
    if ctx.cutoff is not None:
        out.append(f"{tag}: check_no_lookahead was given a ctx already truncated at {ctx.cutoff}")
    r = fn(ctx, **params)
    if r is None:
        return out
    if not (isinstance(r, (tuple, list)) and len(r) == 2):
        return out + [f"{tag}: signal is not (t, direction): {r!r}"]
    t, direction = r
    if t not in _HHMM_SET:
        return out + [f"{tag}: signal minute is not HH:MM: {t!r}"]
    if not SIGNAL_FIRST <= t <= SIGNAL_LAST:
        out.append(f"{tag}: signal minute {t} outside {SIGNAL_FIRST}..{SIGNAL_LAST}")
    if direction not in ("UP", "DOWN"):
        out.append(f"{tag}: direction is not UP/DOWN: {direction!r}")
    try:
        r_at = fn(ctx.truncated(t), **params)
    except Exception as e:                                   # noqa: BLE001 - reported, not hidden
        r_at = ("raised", f"{type(e).__name__}: {e}")
    if r_at is None or tuple(r_at) != tuple(r):
        out.append(f"{tag}: full day gives {tuple(r)!r} but the day cut at {t} gives {r_at!r} "
                   f"(the signal needs candles after {t})")
    if t == "00:00":
        return out
    before = _HHMM[minutes(t) - 1]
    try:
        r_before = fn(ctx.truncated(before), **params)
    except Exception as e:                                   # noqa: BLE001
        r_before = ("raised", f"{type(e).__name__}: {e}")
    if r_before is not None:
        out.append(f"{tag}: full day gives {tuple(r)!r} but the day cut at {before} gives {r_before!r} "
                   f"(not the first qualifying minute, or it raises on a short day)")
    return out


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------
def _selftest() -> int:
    import time
    sys.path.insert(0, os.path.join(ANALYSIS_DIR, "templates"))
    import py_funcs
    from datetime import date

    fails: list[str] = []

    def ok(cond, what):
        if not cond:
            fails.append(what)
        print(("  ok   " if cond else "  FAIL ") + what)

    def raises(exc, fn, what):
        try:
            fn()
        except exc as e:
            ok(True, f"{what} -> {type(e).__name__}")
        except Exception as e:                               # noqa: BLE001
            ok(False, f"{what} -> wrong exception {type(e).__name__}: {e}")
        else:
            ok(False, f"{what} -> did not raise")

    # ---- 0. the text cut on synthetic files (no real data) ----
    print("== wall_cut on synthetic text ==")
    days = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-02-01", "2026-04-30", "2026-05-04", "2026-07-01"]
    minute_rows = [[f"{d}T{h}:00+05:30", 1.0, 2.0, 0.5, 1.5, 10, 20] for d in days for h in ("09:15", "09:16", "15:29")]
    daily_rows = [[d, 1.0, 2.0, 0.5, 1.5] for d in days]
    n_cases = 0
    synth_ok = True
    for rows in (minute_rows, daily_rows, []):
        blob = {"instrument": "X", "fetched": [["2025-11-01", "2026-08-14"]], "candles": rows}
        for text in (json.dumps(blob, separators=(",", ":")), json.dumps(blob), json.dumps(blob, indent=1)):
            for wall in ("2025-12-31", "2026-01-02", "2026-01-04", "2026-01-05", "2026-02-01", "2026-03-15",
                         "2026-04-30", "2026-05-03", "2026-05-04", "2026-06-30", "2026-07-01", "2026-07-31"):
                cut, was = wall_cut(text, wall)
                want = [r for r in rows if r[0][:10] <= wall]
                got = json.loads(cut)
                later = [d for d in days if d > wall and rows]
                n_cases += 1
                if got["candles"] != want or got["fetched"] != blob["fetched"] or was != bool(later) \
                        or any(d in cut[cut.find('"candles"'):] for d in later):
                    synth_ok = False
    ok(synth_ok, f"wall_cut == parse-then-filter, and the cut text holds no later date ({n_cases} cases)")

    # ---- refusals that must happen before any file is read ----
    print("== Market refusals ==")
    raises(ValueError, lambda: Market("NIFTY", "2026-08-07"), "Market(last_day after WINDOW_END)")
    raises(ValueError, lambda: Market("BANKNIFTY"), "Market(unknown index)")
    raises(ValueError, lambda: Market("NIFTY", date(2026, 4, 30)), "Market(last_day as a date object)")
    if freeze_exists():
        print("  skip holdout refusal: a freeze.json exists")
    else:
        raises(PermissionError, lambda: Market("NIFTY", "2026-05-29"), "Market(holdout day, no freeze.json)")

    timings: dict = {}
    for index in INDEXES:
        print(f"\n================ {index} ================")
        t0 = time.perf_counter()
        m = Market(index)
        timings[f"{index} Market() load"] = time.perf_counter() - t0
        t0 = time.perf_counter()
        m2 = Market(index, "2026-02-27")
        timings[f"{index} Market(last_day=2026-02-27) load"] = time.perf_counter() - t0
        win = [d for d in m.sessions if d >= WINDOW_START]
        print(f"  sessions {len(m.sessions)} ({m.sessions[0]} .. {m.sessions[-1]}), in window {len(win)}, "
              f"warm-up {len(m.sessions) - len(win)}, step {m.step}, expiries {len(m.expiries)}, "
              f"text cuts {m.wall_stats}")

        # ---- 1. the wall ----
        print("-- wall --")
        for mk in (m, m2):
            w = mk.last_day
            md = mk.max_dates()
            ok(md["index"] <= w and md["vix"] <= w and all(v <= w for v in md["daily"].values()),
               f"wall {w}: latest index {md['index']}, vix {md['vix']}, daily {max(md['daily'].values())}")
            ok(all(d <= w for d in mk.sessions) and mk.sessions == sorted(mk.sessions)
               and mk.sessions[0] == WARMUP_START, f"wall {w}: sessions ascending from {WARMUP_START}, none later")
            ok(all(r[0] <= w for t in DAILY_TICKERS for r in mk.daily(t)), f"wall {w}: Market.daily rows all <= wall")
            ok(mk.wall_stats["fallbacks"] == 0 and mk.wall_stats["cuts"] >= 2,
               f"wall {w}: files cut as text {mk.wall_stats['cuts']}, fallbacks {mk.wall_stats['fallbacks']}")
            # the raw text handed to the parser holds no later date (index, VIX and every daily file)
            clean = True
            for fn_ in [f"{index}_candles.json", "VIX_candles.json"] + [f"yahoo_{t}_daily.json" for t in DAILY_TICKERS]:
                with open(os.path.join(DATA_DIR, fn_), encoding="utf-8") as f:
                    cut, _ = wall_cut(f.read(), w)
                k = cut.find('"candles"')
                clean &= all(mm.group(1) <= w for mm in _ROW.finditer(cut, k))
                del cut
            ok(clean, f"wall {w}: the text given to the JSON parser has no row dated after the wall (9 files)")
        raises(ValueError, lambda: m.bars("2026-05-04"), "Market.bars(day after the wall)")
        raises(ValueError, lambda: m.vix_bars("2026-05-04"), "Market.vix_bars(day after the wall)")
        raises(ValueError, lambda: m.day_ctx("2026-05-04"), "Market.day_ctx(day after the wall)")
        raises(ValueError, lambda: m.option_bars("2026-05-04", "CE", 24000), "Market.option_bars(day after the wall)")
        raises(ValueError, lambda: m2.bars("2026-03-02"), "Market(2026-02-27).bars('2026-03-02')")
        raises(ValueError, lambda: m2.day_ctx("2026-03-02"), "Market(2026-02-27).day_ctx('2026-03-02')")
        raises(ValueError, lambda: m2.option_bars("2026-03-02", "CE", 24000), "Market(2026-02-27).option_bars('2026-03-02')")
        raises(KeyError, lambda: m.day_ctx("2026-01-03"), "Market.day_ctx(a Saturday)")
        # the two walls agree on everything they share
        same = (m2.sessions == [d for d in m.sessions if d <= "2026-02-27"]
                and all(m2.bars(d) == m.bars(d) and m2.vix_bars(d) == m.vix_bars(d) for d in m2.sessions)
                and all(m2.daily(t) == [r for r in m.daily(t) if r[0] <= "2026-02-27"] for t in DAILY_TICKERS))
        ok(same, "Market(2026-02-27) == Market(2026-04-30) filtered to <= 2026-02-27 (index, vix, dailies)")
        ok(all(len(m.bars(d)) == 375 and m.bars(d)[0][0] == "09:15" and m.bars(d)[-1][0] == "15:29" for d in m.sessions),
           "every session has 375 bars 09:15..15:29")
        ok("2026-02-01" in m.sessions and m.sessions[m.sessions.index("2026-02-01") + 1] == "2026-02-02",
           "Sunday 2026-02-01 is a session; the next one is 2026-02-02")
        if index == "NIFTY":
            ok(m.bars(WARMUP_START)[0] == ["09:15", 26122.8, 26137.55, 26090.4, 26102.35],
               "first NIFTY bar matches the head of the raw file")
            ob = m.option_bars("2026-02-03", "CE", 25000, "2026-02-03")
            ok(ob is not None and ob[-1] == ["15:29", 726.0, 728.1, 725.55, 726.9, 15275, 1956695],
               "option row (NIFTY CE 25000 2026-02-03, last bar) matches the tail of the raw file")
            ob = m.option_bars("2026-01-14", "CE", 25000, "2026-02-03")
            ok(ob is not None and ob[0] == ["09:17", 889.9, 889.9, 889.9, 889.9, 65, 33995],
               "option row (same contract, first bar 2026-01-14 09:17) matches the head of the raw file")
            ok(m.option_bars("2026-01-13", "CE", 25000, "2026-02-03") is None,
               "a day outside the file's fetched range -> None")
            ok(m.option_bars("2026-02-03", "CE", 25025, "2026-02-03") is None, "no file -> None")
        # option files that straddle each wall
        for mk, d in ((m2, "2026-02-27"), (m, "2026-04-30")):
            ctx = mk.day_ctx(d)
            atm = py_funcs.atm_strike(ctx.bars[105][4], mk.step)          # the 11:00 close
            n_files = 0
            for k in range(-5, 6):
                for ot in ("CE", "PE"):
                    if mk.option_bars(d, ot, atm + k * mk.step) is not None:
                        n_files += 1
            md = mk.max_dates()
            ok(n_files >= 10 and ctx.expiry > mk.last_day and md["option_files"] <= mk.last_day
               and all(max(f.spans) <= mk.last_day for f in mk._opt.values() if f and f.spans),
               f"wall {mk.last_day}: {n_files} option files of expiry {ctx.expiry} (it lies after the wall) "
               f"hold nothing after {md['option_files']}")
        # the same contract through both walls: m sees days after 02-27, m2 does not
        d = "2026-02-27"
        e2 = m2.expiry(d)
        atm = py_funcs.atm_strike(m2.bars(d)[105][4], m2.step)
        f_small, f_big = m2._opt_file("CE", float(atm), e2), m._opt_file("CE", float(atm), e2)
        ok(f_small is not None and f_big is not None and max(f_big.spans) > d and max(f_small.spans) == d
           and m2.option_bars(d, "CE", atm) == m.option_bars(d, "CE", atm),
           f"{index} CE {atm:g} {e2}: wall 04-30 holds days to {max(f_big.spans) if f_big else None}, "
           f"wall 02-27 stops at {max(f_small.spans) if f_small else None}; the shared day is identical")
        txt_ok = True
        for mk, dd in ((m2, "2026-02-27"), (m, "2026-04-30")):       # the option text itself, cut at each wall
            a_ = py_funcs.atm_strike(mk.bars(dd)[105][4], mk.step)
            for ot in ("CE", "PE"):
                with open(os.path.join(DATA_DIR, f"{index}_{ot}_{a_:g}_{mk.expiry(dd)}_candles.json"), encoding="utf-8") as f:
                    cut, was = wall_cut(f.read(), mk.last_day)
                got = [mm.group(1) for mm in _ROW.finditer(cut, cut.find('"candles"'))]
                txt_ok &= was and bool(got) and max(got) == dd and got == sorted(got)
                del cut
        ok(txt_ok, "option files straddling a wall: the text given to the parser ends on the wall day (4 files)")

        # ---- 2. expiry / step / lot against py_funcs (dates only) ----
        print("-- expiry, step, lot --")
        cal = [date.fromisoformat(e) for e in m.expiries]
        exp_ok = all((py_funcs.next_expiry(cal, date.fromisoformat(d), 1) or date.min).isoformat() == m.expiry(d)
                     for d in m.sessions)
        ok(exp_ok, "expiry(day) == py_funcs.next_expiry(cal, day, 1) on every session")
        ok(all(m.expiry(d) > d for d in m.sessions), "expiry is never the day itself")
        ok(m.step == py_funcs.strike_step(index) == {"NIFTY": 50.0, "SENSEX": 100.0}[index],
           f"step {m.step} == py_funcs.strike_step")
        e = m.expiry("2026-02-01")
        atm = py_funcs.atm_strike(m.bars("2026-02-01")[105][4], m.step)
        ok(m.lot_size(e, "CE", atm) == {"NIFTY": 65, "SENSEX": 20}[index] and m.lot_size(e, "CE", atm + 1) is None,
           f"lot_size({e}, CE, {atm:g}) = {m.lot_size(e, 'CE', atm)}; unlisted strike -> None")

        # ---- 3. truncation ----
        print("-- truncation --")
        day = "2026-02-01"
        ctx = m.day_ctx(day)
        atm = py_funcs.atm_strike(ctx.bars[105][4], m.step)
        full_opt = ctx.option("CE", atm)
        ok(len(ctx.bars) == 375 and len(ctx.vix()) > 300 and full_opt is not None and ctx.cutoff is None,
           f"full ctx {day}: {len(ctx.bars)} bars, {len(ctx.vix())} vix, {len(full_opt or [])} option bars")
        tr_ok = True
        for cut in ("09:14", "09:15", "09:19", "09:20", "11:00", "14:13", "15:29", "23:59"):
            c = ctx.truncated(cut)
            o = c.option("CE", atm)
            tr_ok &= all(r[0] <= cut for r in c.bars) and all(r[0] <= cut for r in c.vix())
            tr_ok &= o is None or all(r[0] <= cut for r in o)
            tr_ok &= c.bars == [r for r in ctx.bars if r[0] <= cut]
            tr_ok &= c.vix() == [r for r in ctx.vix() if r[0] <= cut]
            tr_ok &= (o or []) == [r for r in full_opt if r[0] <= cut]
            tr_ok &= (c.day, c.expiry, c.step, c.prev_sessions, c.index) == (ctx.day, ctx.expiry, ctx.step, ctx.prev_sessions, ctx.index)
            tr_ok &= c.session(c.prev_sessions[-1]) == ctx.session(ctx.prev_sessions[-1])       # earlier days stay whole
        ok(tr_ok, "truncated(): bars, vix() and option() all cut at the cutoff; earlier sessions untouched")
        ok(ctx.truncated("09:14").bars == [] and ctx.truncated("09:14").option("CE", atm) is None,
           "truncated before the open: no bars, option() None")
        c = ctx.truncated("10:00").truncated("12:00")
        ok(c.cutoff == "10:00" and c.bars[-1][0] == "10:00" and c.truncated("09:30").bars[-1][0] == "09:30",
           "truncated() never widens an earlier cutoff")
        raises(ValueError, lambda: ctx.truncated("9:30"), "truncated('9:30')")
        raises(ValueError, lambda: ctx.truncated("10:00:00"), "truncated('10:00:00')")
        ctx.bars.pop()
        ok(len(m.day_ctx(day).bars) == 375 and len(m.bars(day)) == 375, "popping from ctx.bars does not touch the cache")

        # ---- 4. refusals of session() / daily() ----
        print("-- session() / daily() --")
        ctx = m.day_ctx(day)
        prev = ctx.prev_sessions[-1]
        ok(prev == "2026-01-30" and ctx.prev_sessions == [d for d in m.sessions if d < day],
           f"prev_sessions of Sunday {day} ends with {prev}")
        ok(m.day_ctx("2026-02-02").prev_sessions[-1] == "2026-02-01", "previous session of 2026-02-02 is Sunday 2026-02-01")
        ok(len(ctx.session(prev)) == 375 and ctx.session(prev) == m.bars(prev), "session(previous) is the whole earlier day")
        raises(ValueError, lambda: ctx.session(day), "session(today)")
        raises(ValueError, lambda: ctx.session("2026-02-02"), "session(tomorrow)")
        raises(ValueError, lambda: ctx.truncated("10:00").session(day), "truncated ctx .session(today)")
        raises(KeyError, lambda: ctx.session("2026-01-31"), "session(a Saturday)")
        raises(ValueError, lambda: ctx.vix_session(day), "vix_session(today)")
        raises(ValueError, lambda: ctx.vix_session("2026-03-05"), "vix_session(later day)")
        raises(ValueError, lambda: ctx.house_close(day), "house_close(today)")
        raises(ValueError, lambda: ctx.house_close("2026-02-02"), "house_close(tomorrow)")
        raises(ValueError, lambda: ctx.daily("DJI"), "daily(unknown ticker)")
        d_ok = True
        for dd in ("2026-01-01", day, "2026-03-04", "2026-04-30"):
            cx = m.day_ctx(dd)
            for t in DAILY_TICKERS:
                rows = cx.daily(t)
                d_ok &= bool(rows) and all(r[0] < dd for r in rows) and rows == [r for r in m.daily(t) if r[0] < dd]
                d_ok &= cx.truncated("10:00").daily(t) == rows
        ok(d_ok, "daily(ticker): every row dated strictly before the ctx day, on 4 days x 7 tickers")
        last = {t: m.day_ctx("2026-04-30").daily(t)[-1][0] for t in DAILY_TICKERS}
        print(f"  last daily row seen on 2026-04-30: {last}")
        print(f"  daily rows dropped for a null price: {m.daily_dropped}")
        ok(len(ctx.vix_session(prev)) > 300 and all(len(r) == 5 for r in ctx.vix_session(prev)), "vix_session(previous) has bars")

        # ---- 5. house_close two (three) ways ----
        print("-- house_close --")
        hc = ctx.house_close(prev)
        rows = m.bars(prev)
        a = np.array([r[1:] for r in rows if 900 <= minutes(r[0]) <= 929], dtype=float)       # way 2: numpy
        hc2 = float(((a[:, 1] + a[:, 2] + a[:, 3]) / 3.0).mean())
        raw = [[f"{prev}T{r[0]}:00+05:30", r[1], r[2], r[3], r[4], 0, 0] for r in rows]       # way 3: py_funcs' daily candle
        hc3 = py_funcs._aggregate(raw, "1d")[0][4]
        ok(len(a) == 30 and abs(hc - hc2) < 1e-6 and abs(hc - hc3) < 0.011,
           f"house_close({prev}) = {hc:.4f}; numpy {hc2:.4f}; py_funcs 1d close {hc3}; 15:29 close {rows[-1][4]}")

        # ---- 6. option() for an ATM strike on three discovery days ----
        print("-- option() --")
        for dd in ("2026-01-05", "2026-02-01", "2026-04-22"):
            cx = m.day_ctx(dd)
            atm = py_funcs.atm_strike(cx.bars[105][4], m.step)
            for ot in ("CE", "PE"):
                rows = cx.option(ot, atm)
                good = rows is not None and len(rows) > 300 and all(len(r) == 7 for r in rows) \
                    and rows == m.option_bars(dd, ot, atm) and rows == m.option_bars(dd, ot, atm, cx.expiry) \
                    and all(isinstance(r[5], int) and isinstance(r[6], int) and isinstance(r[1], float) for r in rows) \
                    and [r[0] for r in rows] == sorted({r[0] for r in rows})
                indep = "not re-read (expiry after the wall)"
                if good and cx.expiry <= DISCOVERY_END:          # this file holds no holdout candle: read it raw
                    with open(os.path.join(DATA_DIR, f"{index}_{ot}_{atm:g}_{cx.expiry}_candles.json"), encoding="utf-8") as f:
                        rawf = json.load(f)
                    want = [[r[0][11:16], float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[5]), int(r[6])]
                            for r in rawf["candles"] if r[0][:10] == dd]
                    good &= rows == want
                    indep = "== raw file"
                ok(good, f"{dd} {ot} {atm:g} exp {cx.expiry} lot {m.lot_size(cx.expiry, ot, atm)}: "
                         f"{len(rows or [])} bars {rows[0][0] if rows else '-'}..{rows[-1][0] if rows else '-'}, "
                         f"zero-volume {sum(1 for r in rows or [] if r[5] == 0)}, {indep}")
            ok(cx.option("CE", atm + 0.5) is None, f"{dd}: a strike with no file -> None")
        raises(ValueError, lambda: ctx.option("XX", 25000), "option('XX', ...)")

        # ---- 7. check_no_lookahead on toy signals ----
        print("-- check_no_lookahead --")

        def honest(c, n=30):                 # first bar from 09:19 whose close is above the high of the n bars before it
            b = c.bars
            for i in range(max(n, 4), len(b)):
                if b[i][0] > SIGNAL_LAST:
                    return None
                if b[i][4] > max(r[2] for r in b[i - n:i]):
                    return (b[i][0], "UP")
            return None

        def cheat(c, n=30):                  # uses the day's last bar
            b = c.bars
            if len(b) < 60:
                return None
            return ("10:00", "UP" if b[-1][4] > b[0][1] else "DOWN")

        def late(c, n=30):                   # not the first qualifying minute
            return ("10:00", "UP") if len(c.bars) >= 10 else None

        n_sig = bad_honest = cheat_caught = late_caught = n_cheat = 0
        for dd in win:
            cx = m.day_ctx(dd)
            p = check_no_lookahead(honest, cx, {"n": 30})
            n_sig += honest(cx, 30) is not None
            bad_honest += bool(p)
            pc = check_no_lookahead(cheat, cx, {"n": 30})
            cheat_caught += bool(pc)
            late_caught += bool(check_no_lookahead(late, cx, {"n": 30}))
        ok(bad_honest == 0 and n_sig > 0, f"honest toy signal: {n_sig} signals on {len(win)} days, 0 problems")
        ok(cheat_caught == len(win) and late_caught == len(win),
           f"toy signal that reads the day's last bar flagged on {cheat_caught}/{len(win)} days, "
           f"'not first minute' toy flagged on {late_caught}/{len(win)} days")
        ok(check_no_lookahead(lambda c: ("14:20", "UP"), m.day_ctx(day), {}) != [], "a signal after 14:13 is reported")

        # ---- 8. timings ----
        cx = m.day_ctx(day)
        t0 = time.perf_counter()
        for dd in m.sessions:
            m.day_ctx(dd)
        timings[f"{index} day_ctx() per call"] = (time.perf_counter() - t0) / len(m.sessions)
        t0 = time.perf_counter()
        for i in range(20000):
            cx.truncated("11:00")
        timings[f"{index} truncated() per call"] = (time.perf_counter() - t0) / 20000
        c11 = cx.truncated("11:00")
        atm = py_funcs.atm_strike(cx.bars[105][4], m.step)
        t0 = time.perf_counter()
        for i in range(20000):
            c11.option("CE", atm)
        timings[f"{index} truncated ctx .option() per call (cached)"] = (time.perf_counter() - t0) / 20000
        t0 = time.perf_counter()
        for i in range(20000):
            cx.vix()
        timings[f"{index} .vix() per call"] = (time.perf_counter() - t0) / 20000
        t0 = time.perf_counter()
        for i in range(2000):
            check_no_lookahead(honest, cx, {"n": 30})
        timings[f"{index} check_no_lookahead(toy signal) per call"] = (time.perf_counter() - t0) / 2000
        # a cold sweep: ATM +-5 strikes, CE and PE, every discovery session
        m.drop_option_cache()
        t0 = time.perf_counter()
        n_req = n_none = 0
        for dd in win:
            cx = m.day_ctx(dd)
            atm = py_funcs.atm_strike(cx.bars[105][4], m.step)
            for k in range(-5, 6):
                for ot in ("CE", "PE"):
                    n_req += 1
                    n_none += cx.option(ot, atm + k * m.step) is None
        cold = time.perf_counter() - t0
        n_files = sum(1 for f in m._opt.values() if f is not None)
        timings[f"{index} cold sweep: {len(win)} days x 22 contracts ({n_files} files parsed)"] = cold
        timings[f"{index}   -> per file"] = cold / max(n_files, 1)
        t0 = time.perf_counter()
        for dd in win:
            cx = m.day_ctx(dd)
            atm = py_funcs.atm_strike(cx.bars[105][4], m.step)
            for k in range(-5, 6):
                for ot in ("CE", "PE"):
                    cx.option(ot, atm + k * m.step)
        timings[f"{index} the same sweep again (all cached)"] = time.perf_counter() - t0
        md = m.max_dates()
        ok(md["option_files"] <= m.last_day and md["option_days"] <= m.last_day and m.wall_stats["fallbacks"] == 0,
           f"after the sweep: {n_req} requests, {n_none} unavailable, {n_files} files, latest option day held "
           f"{md['option_files']}, text cuts {m.wall_stats['cuts']}, fallbacks {m.wall_stats['fallbacks']}")
        nbytes = sum(f.px.nbytes + f.vi.nbytes + f.mins.nbytes for f in m._opt.values() if f is not None and f.px is not None)
        print(f"  compact option store: {nbytes / 1e6:.1f} MB for {n_files} files; "
              f"{sum(1 for v in m._opt_days.values() if v is not None)} contract-days materialised")

    print("\n== timings ==")
    for k, v in timings.items():
        print(f"  {k}: " + (f"{v * 1e6:.1f} us" if v < 1e-3 else f"{v * 1e3:.1f} ms" if v < 1 else f"{v:.2f} s"))
    print(f"\n{'ALL CLEAN' if not fails else 'FAILURES: ' + str(len(fails))}")
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_selftest())
