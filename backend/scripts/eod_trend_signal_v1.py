"""EOD trend / exhaustion signal, v1 - BUY, SELL or HOLD after the 15:14 candle.

The user's rule of 2026-09-18, implemented as written.  Nothing in it is tuned
here: the three thresholds are module constants with no command-line flag, and
the script has no sweep.

    Feed        NSE_INDEX|Nifty 50, one-minute candles, Asia/Kolkata.
    Decision    computed once the 15:14 candle has completed; no candle that
                starts at or after 15:15 is read for any feature.
    Daily bar   built from the 360 one-minute candles 09:15..15:14 of each
                session: open = 09:15 open, high/low = extremes, close = the
                15:14 close.

    Trend30            % move, oldest close -> newest close, latest 30 daily bars
    SMA10              mean close of the latest 10 daily bars (current included)
    Location30         (close - low30) / (high30 - low30) over the latest 30 bars
    Momentum15         15:14 close - 15:00 open            (points)
    Momentum10         15:14 close - 15:05 open            (points)
    VolatilityRatio10  sample std-dev of the 9 close-to-close % changes over the
                       closes 15:05..15:14, divided by the mean of that same
                       figure over the PREVIOUS 20 sessions (current excluded)
    DailyRangeRatio20  today's (high - low) / close in %, over the 09:15..15:14
                       window, divided by the mean of the latest 20 sessions
                       (current INCLUDED)

    Trigger A   Trend30 < 0  and  Momentum15 > 0
    Trigger B   close < SMA10  and  VolatilityRatio10 >= 1.20
    Trigger C   Trend30 < 0  and  Momentum10 < 0
    Base        A or B or C
    Exhaustion  Location30 <= 0.20  and  DailyRangeRatio20 >= 1.20

    1. Base false                 -> HOLD
    2. Base true, exhaustion true -> BUY   (open a long)
    3. Base true, exhaustion false-> SELL  (open a short)
    Any required candle or feature missing, duplicated, incomplete or invalid
    -> HOLD, with the reason logged.

    Entry   15:29 of the signal day.  Exit  the close of the next exchange
    trading day's first one-minute candle.


SETTLED ASSUMPTIONS (each one is a judgment call the spec leaves open)
----------------------------------------------------------------------
* FILL.  The spot entry is the 15:29 candle's CLOSE, the last print of the
  session, and the exit is the 09:15 candle's close of the next session.  The
  15:29 open is logged beside it (`entry_open_1529`) so the difference is
  visible; it is not used.  The option is priced at the same two minutes from
  the contract's own one-minute closes.
* RANGE DENOMINATOR.  "Daily high-low percentage range" is (high - low) / the
  15:14 close x 100.  Numerator and denominator of the ratio use the same
  definition, so the choice moves the ratio very little.
* SESSION VALIDITY.  A session is valid when the 09:15..15:14 window holds
  exactly the 360 expected candles, none duplicated, every one with finite
  OHLC where low <= min(open, close) <= max(open, close) <= high.  Candles
  outside the window (the 09:07 and 15:30/15:31 prints of 2022, 15:39/15:59 of
  2025-04/05) are ignored, not treated as errors.
* PARTIAL SESSIONS.  The spec's HOLD-on-invalid clause is read literally
  (`--partial-sessions strict`, the default): a session with a missing or bad
  candle produces an invalid daily bar, and every feature whose window contains
  it is invalid, so the 29 sessions that follow it are HOLD for Trend30 and
  Location30 and the 19 that follow it for the two ratios.  In the cached feed
  that hits 2022-03-07 (3 candles missing), 2024-12-12, 2025-03-25, 2025-04-04
  and 2025-04-23 (1 each), the Saturday drill sessions 2024-03-02 and
  2024-05-18, and the in-hours Muhurat session 2025-10-21.  Evening Muhurat
  sessions (2022-10-24, 2023-11-12, 2024-11-01) have NO candle in the window,
  so no daily bar can be built from them: they are not part of the daily
  series, but they ARE exchange trading days, so a position opened the day
  before exits on their first candle.  `--partial-sessions skip` drops the
  partial sessions from the daily series instead.  The default 6-month window
  contains none of these, so the choice does not touch the headline run.
* EXPIRY.  A 15:29 entry on an expiry day cannot hold that expiry's contract
  overnight, so the option is always the nearest expiry strictly AFTER the
  signal day (`--expiry-roll zero-dte`).  `always` takes one further out.
* OFFICIAL CLOSE.  The daily feed's official close is logged for reference
  (`official_close`) and used nowhere; every rule reads the 15:14 close.
* MISSING PRINTS.  A strike can go a few minutes without a trade (a far expiry
  at the open, a strike listed that afternoon).  Within 5 minutes the nearest
  print stands in - the last one before an entry, the first one after an exit
  - and the minute used is logged (`entry_px_minute`, `exit_px_minute`).
* WINDOWS.  The rule is built for the post-auction market (user, 2026-09-18),
  so the report opens on the window from 2026-08-03 and offers the others in a
  selector: the last 6 months, and with `--full-history` the whole period the
  broker's option archive covers (2024-10-01 onward) - the user wants the wide
  window to show a REAL premium P&L, so it stops where the premiums stop.
  Every table and the chart follow the selection.
* DATA NOT YET CACHED is fetched from the broker: past days from the historical
  endpoint, today from the intraday endpoint (the historical one returns
  nothing for the current day), and saved as a small per-day cache once the
  session is over.  A trade whose next session has not happened yet is priced
  at entry and shown open.


RESULTS (generated 2026-09-18 - re-derive before quoting)
----------------------------------------------------------
WORST-FILL RULE (user, 2026-09-19): the headline now buys at the 15:29 minute's
HIGH and sells at the 09:15 minute's LOW.  On that basis the 6-month book is
57 nights, 43.9% win, net Rs -54,714 (close fills: 56.1%, net +72,811).  The
09:15 option minute has a median range of 45 points, so an exit inside it is
filled ~27 points below its close under the rule; that single minute is the
whole difference.  The figures below are the CLOSE-FILL numbers of 2026-09-18.

Default window 2026-03-19 -> 2026-09-18, 124 sessions, none partial (the
2026-09-18 candles were pulled from the broker's intraday endpoint after the
close; that day's SELL is open until Monday's first candle):

    decisions     50 SELL   9 BUY   65 HOLD (0 of them for data validity)
    spot          58 closed nights  mean +0.184%  median +0.166%  win 60.3%
                  PF 1.87  t +1.67      (filled at the 15:29 OPEN instead:
                                          +0.154%, 58.6% win, t +1.44)
      SELL        49 nights  +0.165%  59.2% win
      BUY          9 nights  +0.288%  66.7% win
      before CAS  40 nights  +0.131%  50.0% win  t +0.84
      from CAS    18 nights  +0.301%  83.3% win  t +3.77
    premium       skip-1dte (default) 58/58  +14.53% mean  +11.33% median
                                             56.9% win  PF 2.06  Rs +78,994
                  next                58/58  +17.63%  +11.33%  55.2%  PF 2.07
                                             (9 nights exit on expiry morning)
                  always              58/58   +9.82%   +6.45%  56.9%  PF 2.08
      SELL        49 nights  +18.27%  57.1% win     BUY  9 nights  -5.85%  55.6%
      before CAS  40 nights   +4.77%  47.5% win     from CAS  18 nights  +36.21%  77.8%

Full history 2022-01-03 -> 2026-09-17 (`--from 2022-01-01 --offline`, strict):
    418 closed nights  mean -0.018%  median -0.061%  win 45.7%  PF 0.92  t -0.58
    by year  2022 -0.049% 41.9%    2023 -0.094% 37.6% (t -2.51)
             2024 -0.119% 37.5% (t -2.55)    2025 -0.036% 45.9%
             2026 +0.149% 60.8% (t +1.84)
    `--partial-sessions skip`: 467 nights  -0.028%  45.4% win  t -0.97, same
    shape by year.  Both wide runs are spot only (option archive from 2024-10).

READ IT THIS WAY.  The 6-month book is positive because 2026 is a falling
market and this is a short-in-a-downtrend rule: the 18 post-CAS nights at 83%
win carry both the spot and the premium result, while the 40 nights before
CAS are a coin flip on spot (50.0%) and +4.8% of premium.  Over 4.7 years the
same rule loses in four of five years, two of them significantly.  Nothing
here was tuned, so nothing here is curve-fit; it is a rule whose sign happens
to match one regime.  The BUY side is 9 nights and cannot be read at all.


WHAT THIS IS AND IS NOT
------------------------
Both BUY and SELL are implemented as BOUGHT options - ATM CE for BUY, ATM PE
for SELL - because that is how every spot rule in this repository is priced.
The spot columns (points, %) are the rule itself and are lot-size free; the
premium columns say what a bought ATM option made of it over one night, which
is a different thing (theta, skew, a delta near one half).  Read the spot
columns first.

KNOWN PITFALLS - see nifty-backtest-data-and-fill-pitfalls
* The rule runs on SPOT and decides the side; the option is resolved
  afterwards purely to price the result.  Nothing in the pricing pass can
  change which trades exist.
* The features are verified against an independent numpy re-implementation
  (scratch check, 2026-09-18) on every session of the 2022-01 -> 2026-09
  cache: all feature values, trigger states and decisions agree.
* Post-2026-08-03 (closing-auction session) the last 30 minutes barely move,
  so Momentum15 / Momentum10 are small in magnitude.  The triggers read only
  their SIGN, so they still fire; but a sign on a 2-point move is noise.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone, time as dt_time

import httpx

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..")
sys.path.insert(0, BACKEND_DIR)

from services.upstox_client import (  # noqa: E402
    INSTRUMENT_KEYS, UPSTOX_BASE_V3, get_candles, _get, _candle_to_dict)
from services.option_pricing import (  # noqa: E402
    CachedPricer, OptionPricer, RateLimiter, atm_strike, _candle_keys, api_get)
from services.trade_costs import capital_required, option_round_trip  # noqa: E402
from urllib.parse import quote  # noqa: E402

DATA_DIR = os.path.join(BACKEND_DIR, "data")
REPORTS_DIR = os.path.join(BACKEND_DIR, "reports")
RESULTS_DIR = os.path.join(BACKEND_DIR, "results")
CONFIG_FILE = os.path.join(BACKEND_DIR, "upstox_config.txt")
REPORT_HTML = os.path.join(REPORTS_DIR, "eod_trend_signal_v1_report.html")
SIGNALS_CSV = os.path.join(RESULTS_DIR, "eod_trend_signal_v1_signals.csv")
TRADES_CSV = os.path.join(RESULTS_DIR, "eod_trend_signal_v1_trades.csv")

UNDERLYING = "NIFTY"
UNDERLYING_KEY = INSTRUMENT_KEYS[UNDERLYING]
IST = timezone(timedelta(hours=5, minutes=30), "IST")   # no DST, a fixed offset is exact

# Scales the rupee column and nothing else; every headline figure is a % of
# spot or a % of premium and is lot-size free.
LOT_SIZE = 65


def _hhmm_range(start: str, end: str) -> list[str]:
    out, h, m = [], int(start[:2]), int(start[3:])
    while f"{h:02d}:{m:02d}" <= end:
        out.append(f"{h:02d}:{m:02d}")
        m += 1
        if m == 60:
            h, m = h + 1, 0
    return out


# ---- the rule's constants.  FIXED.  There is deliberately no flag for any ----
SESSION_START = "09:15"
FEATURE_END = "15:14"           # last candle any feature may read
CUTOFF = "15:15"                # nothing starting here or later is read
ENTRY_HHMM = "15:29"
WINDOW_TIMES = _hhmm_range(SESSION_START, FEATURE_END)      # 360 candles
WINDOW_SET = set(WINDOW_TIMES)
MOM15_OPEN = "15:00"
MOM10_OPEN = "15:05"
VOL_TIMES = _hhmm_range("15:05", FEATURE_END)               # 10 closes -> 9 changes
TREND_N = 30
SMA_N = 10
LOCATION_N = 30
VOL_PREV_N = 20                 # previous sessions, current excluded
RANGE_N = 20                    # latest sessions, current included
VOL_RATIO_THRESHOLD = 1.20
LOCATION_THRESHOLD = 0.20
RANGE_RATIO_THRESHOLD = 1.20

# The one-minute feed starts 2022-01-03, but the broker's expired-option archive
# starts 2024-10, and a window without premiums shows no real P&L (user,
# 2026-09-18).  `--full-history` therefore runs from the archive start; pass
# `--from 2022-01-01` explicitly for the spot-only years before it.
PRICED_START = date(2024, 10, 1)
# Full one-minute candles are carried in the report for sessions this many days
# back; older sessions keep only trade days, and only 14:30-15:29 of the signal
# day and 09:15-10:00 of the exit day, or a full-history report would be 30 MB.
CHART_FULL_DAYS = 183

# Calendar days loaded before --from so the first in-window session already
# has its 29 earlier daily bars and 20 earlier volatility readings.
WARMUP_DAYS = 75

PARTIAL_MODES = [
    ("strict", "a partial session is an invalid daily bar and poisons every "
               "window that contains it (the spec, literally)"),
    ("skip", "partial sessions are left out of the daily series"),
]
# Which contract prices the night.  All three are priced for every trade and
# tabulated side by side; the default fills the headline premium columns.
EXPIRY_MODES = [
    ("next", "nearest expiry strictly after the signal day - may expire the next morning"),
    ("skip-1dte", "nearest expiry strictly after the EXIT day - never hold into expiry morning"),
    ("always", "one expiry further out than 'next'"),
]
DEFAULT_EXPIRY = "skip-1dte"
# The closing auction session.  From this date the 15:29 one-minute candle
# carries the auction print, so its close can sit far from its open.
CAS_DATE = "2026-08-03"

# Recorded from `--from 2022-01-01 --offline` on 2026-09-18 (1,165 sessions,
# strict partial-session handling; spot only, the option archive starts
# 2024-10).  Cite this; re-run wide only on request.
WIDE_RUN = {
    "window": "2022-01-03 -> 2026-09-17",
    "text": ("355 SELL, 64 BUY, 746 HOLD (189 of the HOLDs are windows poisoned by a "
             "partial session). 418 closed nights on spot: mean -0.018%, median -0.061%, "
             "win 45.7%, profit factor 0.92, t = -0.58. By year (mean %, win %): "
             "2022 -0.049 / 41.9; 2023 -0.094 / 37.6 (t -2.51); 2024 -0.119 / 37.5 "
             "(t -2.55); 2025 -0.036 / 45.9; 2026 +0.149 / 60.8 (t +1.84). The SELL "
             "side, 85% of the book, lost in every year before 2026; no trigger "
             "combination is positive with t above 0.7. With --partial-sessions skip "
             "(467 nights) it reads -0.028%, 45.4% win, t = -0.97, same shape by year. "
             "The 6-month figure above is one regime - a falling market - not a "
             "property of the rule."),
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _read_access_token() -> str | None:
    try:
        with open(CONFIG_FILE) as f:
            lines = [l.strip() for l in f.readlines()]
    except OSError:
        return None
    return lines[3] if len(lines) >= 4 and lines[3] else None


def nifty_cache_path(from_date: date, to_date: date) -> str:
    return os.path.join(
        DATA_DIR, f"nifty_1m_{from_date.isoformat()}_{to_date.isoformat()}.json")


def _merge_existing_caches(from_date: date, to_date: date) -> list[dict]:
    """Every cache in backend/data that overlaps the window, merged by
    timestamp.  Merging (rather than picking one file) is what lets a
    per-day tail file sit beside the multi-year one."""
    merged: dict[str, dict] = {}
    used = []
    for name in sorted(os.listdir(DATA_DIR)):
        if not (name.startswith("nifty_1m_") and name.endswith(".json")):
            continue
        stem = name[len("nifty_1m_"):-len(".json")]
        try:
            a, b = stem.split("_")
            c_from, c_to = date.fromisoformat(a), date.fromisoformat(b)
        except ValueError:
            continue
        if c_from > to_date or c_to < from_date:
            continue
        with open(os.path.join(DATA_DIR, name)) as f:
            candles = json.load(f)
        n = 0
        for c in candles:
            ts = c.get("timestamp", "")
            if from_date.isoformat() <= ts[:10] <= to_date.isoformat() and ts not in merged:
                merged[ts] = c
                n += 1
        if n:
            used.append(f"{name} (+{n})")
    if merged:
        print(f"Reusing {', '.join(used)}: {len(merged)} candles inside {from_date} -> {to_date}")
    return [merged[k] for k in sorted(merged)]


def _session_closed_now() -> bool:
    """True once today's regular session (and its closing auction) is over, so
    a fetched 'today' can be cached as a complete day."""
    return datetime.now(IST).time() >= dt_time(15, 45)


async def _intraday_index_candles(token: str) -> list[dict]:
    """Today's one-minute candles.  The historical endpoint returns nothing for
    the current day; the intraday endpoint returns all of it."""
    url = (f"{UPSTOX_BASE_V3}/historical-candle/intraday/"
           f"{quote(UNDERLYING_KEY, safe='')}/minutes/1")
    data = await _get(url, token)
    raw = (data.get("data", {}) or {}).get("candles", []) or []
    return [_candle_to_dict(c) for c in raw if c]


async def fetch_tail(token: str, from_date: date, to_date: date) -> list[dict]:
    """The candles the caches do not have yet: past days from the historical
    endpoint, today from the intraday one.  Saved as its own small cache file
    once the day is complete, so the next run needs no network."""
    today = datetime.now(IST).date()
    out: list[dict] = []
    hist_to = min(to_date, today - timedelta(days=1))
    if from_date <= hist_to:
        print(f"Fetching NIFTY 1m candles {from_date} -> {hist_to} from the broker ...")
        try:
            out += await get_candles(token, UNDERLYING_KEY, "1m", from_date, hist_to)
        except Exception as exc:                                  # noqa: BLE001
            print(f"  ! historical fetch failed ({exc})")
    if from_date <= today <= to_date:
        try:
            got = await _intraday_index_candles(token)
            print(f"Fetched {len(got)} intraday candles for {today} from the broker")
            out += got
        except Exception as exc:                                  # noqa: BLE001
            print(f"  ! intraday fetch failed ({exc})")
    out.sort(key=lambda c: c.get("timestamp", ""))
    if out:
        days = sorted({c["timestamp"][:10] for c in out})
        if days[-1] < today.isoformat() or _session_closed_now():
            path = nifty_cache_path(date.fromisoformat(days[0]), date.fromisoformat(days[-1]))
            with open(path, "w") as f:
                json.dump(out, f)
            print(f"  saved {len(out)} candles -> {os.path.basename(path)}")
        else:
            print("  today's session is still open: its candles are used, not cached")
    return out


async def load_nifty(offline: bool, from_date: date, to_date: date) -> list[dict]:
    candles = _merge_existing_caches(from_date, to_date)
    have_to = max((c["timestamp"][:10] for c in candles), default=None)
    need_from = from_date if have_to is None else date.fromisoformat(have_to) + timedelta(days=1)
    token = None if offline else _read_access_token()
    if need_from <= to_date:
        if token:
            tail = await fetch_tail(token, need_from, to_date)
            have = {c["timestamp"] for c in candles}
            candles += [c for c in tail if c["timestamp"] not in have]
            candles.sort(key=lambda c: c["timestamp"])
        else:
            print(f"  ! caches end {have_to}; {need_from} -> {to_date} not fetched "
                  f"(offline={offline}, token={'yes' if token else 'no'})")
    if not candles:
        raise RuntimeError(f"No data for {from_date} -> {to_date} and no usable cache.")
    return candles


def load_daily_ohlc(from_date: date, to_date: date) -> dict[str, dict]:
    """Session date -> official daily OHLC, from the widest cached daily file
    that covers the window.  Used only to cross-check the derived bars and to
    log the official close; no rule reads it."""
    best = None
    for name in sorted(os.listdir(DATA_DIR)):
        if not (name.startswith("nifty_1d_") and name.endswith(".json")):
            continue
        try:
            a, b = name[len("nifty_1d_"):-len(".json")].split("_")
            c_from, c_to = date.fromisoformat(a), date.fromisoformat(b)
        except ValueError:
            continue
        if c_from <= from_date and c_to >= min(to_date, date.today() - timedelta(days=1)):
            span = (c_to - c_from).days
            if best is None or span > best[0]:
                best = (span, name)
    if best is None:
        print("  ! no daily cache covers the window; official closes not logged")
        return {}
    with open(os.path.join(DATA_DIR, best[1])) as f:
        raw = json.load(f)
    print(f"Loaded {len(raw)} NIFTY daily candles from {best[1]} (reference only)")
    return {c["timestamp"][:10]: {"o": float(c["open"]), "h": float(c["high"]),
                                  "l": float(c["low"]), "c": float(c["close"])}
            for c in raw}


def to_rows(candles: list[dict]) -> tuple[list[dict], int]:
    """Compact rows in IST.  `ok` is the per-candle OHLC sanity flag."""
    rows, bad_ts = [], 0
    for c in candles:
        try:
            dt = datetime.fromisoformat(c.get("timestamp"))
        except (TypeError, ValueError):
            bad_ts += 1
            continue
        if dt.tzinfo is None:                     # Upstox stamps IST; be explicit
            dt = dt.replace(tzinfo=IST)
        dt = dt.astimezone(IST)
        o = h = l = cl = None
        ok = False
        try:
            o, h, l, cl = (float(c["open"]), float(c["high"]),
                           float(c["low"]), float(c["close"]))
            ok = (all(math.isfinite(x) for x in (o, h, l, cl)) and l > 0
                  and h >= max(o, cl) and l <= min(o, cl))
        except (KeyError, TypeError, ValueError):
            ok = False
        rows.append({"day": dt.strftime("%Y-%m-%d"), "t": dt.strftime("%H:%M"),
                     "o": o, "h": h, "l": l, "c": cl, "ok": bool(ok)})
    return rows, bad_ts


def build_session(day: str, rows: list[dict]) -> dict:
    """One exchange session: its daily bar, its intraday features, its validity
    and the two candles the trade needs (15:29 entry, first-candle exit)."""
    rows = sorted(rows, key=lambda r: r["t"])
    win = [r for r in rows if SESSION_START <= r["t"] <= FEATURE_END]
    cnt = Counter(r["t"] for r in win)
    dups = sorted(t for t, n in cnt.items() if n > 1)
    missing = [t for t in WINDOW_TIMES if t not in cnt]
    bad = sorted({r["t"] for r in win if not r["ok"]})
    reasons = []
    if missing:
        head = ", ".join(missing[:4]) + (" ..." if len(missing) > 4 else "")
        reasons.append(f"{len(missing)} candle(s) missing ({head})")
    if dups:
        reasons.append(f"duplicated candle(s) {', '.join(dups[:4])}")
    if bad:
        reasons.append(f"invalid OHLC at {', '.join(bad[:4])}")
    s = {"day": day, "n_all": len(rows), "n_window": len(win),
         "valid": not reasons and len(win) > 0,
         "invalid_reason": "; ".join(reasons) if reasons else
         ("no candle inside 09:15..15:14" if not win else ""),
         "o": None, "h": None, "l": None, "c": None,
         "momentum15": None, "momentum10": None, "vol10": None, "range_pct": None}
    if s["valid"]:
        by_t = {r["t"]: r for r in win}
        s["o"] = by_t[SESSION_START]["o"]
        s["h"] = max(r["h"] for r in win)
        s["l"] = min(r["l"] for r in win)
        s["c"] = by_t[FEATURE_END]["c"]
        s["momentum15"] = s["c"] - by_t[MOM15_OPEN]["o"]
        s["momentum10"] = s["c"] - by_t[MOM10_OPEN]["o"]
        closes = [by_t[t]["c"] for t in VOL_TIMES]
        rets = [(closes[i] / closes[i - 1] - 1.0) * 100.0 for i in range(1, len(closes))]
        s["vol10"] = statistics.stdev(rets)                # sample std, n - 1
        s["range_pct"] = (s["h"] - s["l"]) / s["c"] * 100.0
    # The entry candle.  Not a feature, so it does not affect validity - but a
    # duplicated 15:29 is not a fill either.
    ent = [r for r in rows if r["t"] == ENTRY_HHMM and r["ok"]]
    s["entry"] = ent[0] if len(ent) == 1 else None
    # The exit candle for a position opened the previous session: the first
    # candle of the regular session or, on a special session, its first print.
    first = [r for r in rows if r["t"] >= SESSION_START and r["ok"]]
    s["first"] = first[0] if first else None
    return s


def build_sessions(rows: list[dict]) -> tuple[dict[str, dict], list[str]]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_day[r["day"]].append(r)
    all_days = sorted(by_day)
    return {d: build_session(d, by_day[d]) for d in all_days}, all_days


# ---------------------------------------------------------------------------
# Features and the decision
# ---------------------------------------------------------------------------

FEATURE_KEYS = ["close", "day_open", "day_high", "day_low", "trend30", "sma10",
                "high30", "low30", "location30", "momentum10", "momentum15",
                "vol10", "vol10_avg20", "volatility_ratio10", "daily_range_pct",
                "range_avg20", "daily_range_ratio20"]


def _window_bad(w: list[dict], today: str) -> list[str]:
    return [x["day"] for x in w if not x["valid"] and x["day"] != today]


def compute_signal(series: list[dict], i: int) -> dict:
    """Features, triggers and the decision for series[i], reading nothing
    later than its own 15:14 candle."""
    s = series[i]
    f: dict = {k: None for k in FEATURE_KEYS}
    reasons: list[str] = []
    if s["valid"]:
        f.update(close=s["c"], day_open=s["o"], day_high=s["h"], day_low=s["l"],
                 momentum15=s["momentum15"], momentum10=s["momentum10"],
                 vol10=s["vol10"], daily_range_pct=s["range_pct"])
    else:
        reasons.append(f"session invalid: {s['invalid_reason']}")

    # Trend30 and Location30 share the 30-bar window.
    if i + 1 < TREND_N:
        reasons.append(f"only {i + 1} daily bars, Trend30/Location30 need {TREND_N}")
    else:
        w = series[i - TREND_N + 1:i + 1]
        bad = _window_bad(w, s["day"])
        if bad:
            reasons.append(f"invalid daily bar inside the {TREND_N}-session window: "
                           + ", ".join(bad))
        elif s["valid"]:
            f["trend30"] = (w[-1]["c"] / w[0]["c"] - 1.0) * 100.0
            f["high30"] = max(x["h"] for x in w)
            f["low30"] = min(x["l"] for x in w)
            if f["high30"] > f["low30"]:
                f["location30"] = (s["c"] - f["low30"]) / (f["high30"] - f["low30"])
            else:
                reasons.append("30-session high equals the low")

    if i + 1 < SMA_N:
        reasons.append(f"only {i + 1} daily bars, SMA10 needs {SMA_N}")
    else:
        w = series[i - SMA_N + 1:i + 1]
        bad = _window_bad(w, s["day"])
        if bad:
            reasons.append(f"invalid daily bar inside the {SMA_N}-session window: "
                           + ", ".join(bad))
        elif s["valid"]:
            f["sma10"] = statistics.fmean(x["c"] for x in w)

    # VolatilityRatio10: the previous 20 sessions, current excluded.
    if i < VOL_PREV_N:
        reasons.append(f"only {i} previous sessions, VolatilityRatio10 needs {VOL_PREV_N}")
    else:
        w = series[i - VOL_PREV_N:i]
        bad = [x["day"] for x in w if not x["valid"] or x["vol10"] is None]
        if bad:
            reasons.append(f"invalid volatility reading inside the previous "
                           f"{VOL_PREV_N} sessions: " + ", ".join(bad))
        else:
            avg = statistics.fmean(x["vol10"] for x in w)
            f["vol10_avg20"] = avg
            if avg <= 0:
                reasons.append("previous-20-session volatility average is zero")
            elif s["valid"]:
                f["volatility_ratio10"] = s["vol10"] / avg

    # DailyRangeRatio20: the latest 20 sessions, current included.
    if i + 1 < RANGE_N:
        reasons.append(f"only {i + 1} daily bars, DailyRangeRatio20 needs {RANGE_N}")
    else:
        w = series[i - RANGE_N + 1:i + 1]
        bad = _window_bad(w, s["day"])
        if bad:
            reasons.append(f"invalid daily bar inside the {RANGE_N}-session window: "
                           + ", ".join(bad))
        elif s["valid"]:
            avg = statistics.fmean(x["range_pct"] for x in w)
            f["range_avg20"] = avg
            if avg <= 0:
                reasons.append("20-session range average is zero")
            else:
                f["daily_range_ratio20"] = s["range_pct"] / avg

    def have(*keys):
        return all(f[k] is not None for k in keys)

    trig_a = (f["trend30"] < 0 and f["momentum15"] > 0) if have("trend30", "momentum15") else None
    trig_b = ((f["close"] < f["sma10"] and f["volatility_ratio10"] >= VOL_RATIO_THRESHOLD)
              if have("close", "sma10", "volatility_ratio10") else None)
    trig_c = (f["trend30"] < 0 and f["momentum10"] < 0) if have("trend30", "momentum10") else None
    base = (trig_a or trig_b or trig_c) if None not in (trig_a, trig_b, trig_c) else None
    exhaustion = ((f["location30"] <= LOCATION_THRESHOLD
                   and f["daily_range_ratio20"] >= RANGE_RATIO_THRESHOLD)
                  if have("location30", "daily_range_ratio20") else None)

    # The order the spec gives, with the data check in front of it.
    if reasons or base is None or exhaustion is None:
        if not reasons:                      # cannot happen, but never trade on it
            reasons.append("a trigger could not be evaluated")
        decision, hold_reason, data_ok = "HOLD", "; ".join(reasons), False
    elif not base:
        decision, hold_reason, data_ok = "HOLD", "base signal false", True
    elif exhaustion:
        decision, hold_reason, data_ok = "BUY", "", True
    else:
        decision, hold_reason, data_ok = "SELL", "", True

    pattern = "".join(k for k, v in (("A", trig_a), ("B", trig_b), ("C", trig_c)) if v)
    return {"day": s["day"], "decision": decision, "trigger_a": trig_a,
            "trigger_b": trig_b, "trigger_c": trig_c, "base_signal": base,
            "exhaustion": exhaustion, "pattern": pattern or "-",
            "data_ok": data_ok, "hold_reason": hold_reason, **f}


def daily_series(sessions: dict[str, dict], all_days: list[str], partial: str) -> list[dict]:
    """The daily bars, in order.  A session with no candle in the window has no
    daily bar at all; a partial one is kept (strict) or dropped (skip)."""
    out = []
    for d in all_days:
        s = sessions[d]
        if s["n_window"] == 0:
            continue
        if partial == "skip" and not s["valid"]:
            continue
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

def build_trades(signals: list[dict], sessions: dict[str, dict],
                 all_days: list[str]) -> list[dict]:
    """Spot only.  Entry 15:29 close, exit the next session's first-candle
    close.  Every non-HOLD signal yields a row, filled or not."""
    pos = {d: k for k, d in enumerate(all_days)}
    out = []
    for sig in signals:
        if sig["decision"] == "HOLD":
            continue
        s = sessions[sig["day"]]
        side = "LONG" if sig["decision"] == "BUY" else "SHORT"
        t = {"day": sig["day"], "decision": sig["decision"], "side": side,
             "pattern": sig["pattern"], "exhaustion": sig["exhaustion"],
             "entry_time": ENTRY_HHMM, "entry_spot": None, "entry_open_1529": None,
             "exit_day": None, "exit_time": None, "exit_spot": None, "next_open": None,
             "spot_pts": None, "spot_pct": None, "spot_pct_open": None, "status": "closed",
             "strike": None, "option_type": "CE" if side == "LONG" else "PE",
             "symbol": None, "expiry": None, "dte": None, "entry_px": None,
             "exit_px": None, "entry_minute": None, "exit_minute": None,
             "prem_pts": None, "prem_pct": None, "pnl_rs": None, "capital_rs": None,
             "costs_rs": None, "net_rs": None, "entry_px_close": None, "exit_px_close": None,
             "pnl_rs_close": None, "net_rs_close": None, "fill": None,
             "price_reason": None, "exit_day_assumed": None}
        if s["entry"] is None:
            t["status"] = "no 15:29 candle - not filled"
            out.append(t)
            continue
        t["entry_spot"] = s["entry"]["c"]
        t["entry_open_1529"] = s["entry"]["o"]
        k = pos[sig["day"]]
        if k + 1 >= len(all_days):
            t["status"] = "open - next session not in the data"
            # The expiry choice needs an exit day; assume the next weekday.
            nd = date.fromisoformat(sig["day"]) + timedelta(days=1)
            while nd.weekday() >= 5:
                nd += timedelta(days=1)
            t["exit_day_assumed"] = nd.isoformat()
            out.append(t)
            continue
        nxt = sessions[all_days[k + 1]]
        t["exit_day"] = nxt["day"]
        if nxt["first"] is None:
            t["status"] = "next session has no usable candle"
            out.append(t)
            continue
        t["exit_time"] = nxt["first"]["t"]
        t["exit_spot"] = nxt["first"]["c"]
        t["next_open"] = nxt["first"]["o"]
        pts = (t["exit_spot"] - t["entry_spot"] if side == "LONG"
               else t["entry_spot"] - t["exit_spot"])
        t["spot_pts"] = round(pts, 2)
        t["spot_pct"] = pts / t["entry_spot"] * 100.0
        # The same night filled at the 15:29 OPEN instead - the sensitivity row.
        alt = (t["exit_spot"] - t["entry_open_1529"] if side == "LONG"
               else t["entry_open_1529"] - t["exit_spot"])
        t["spot_pct_open"] = alt / t["entry_open_1529"] * 100.0
        out.append(t)
    return out


# ---------------------------------------------------------------------------
# Option pricing - AFTER the spot pass, and it can change nothing above
# ---------------------------------------------------------------------------

def pick_expiries(expiries: list[date], day: date, exit_day: date, mode: str) -> list[date]:
    """Candidate expiries for one night, nearest first.  A 15:29 entry can never
    hold a contract that expires the same day, so every mode starts strictly
    after the signal day."""
    after = [e for e in expiries if e > day]
    if mode == "skip-1dte":
        after = [e for e in after if e > exit_day]
    elif mode == "always":
        after = after[1:]
    return after[:3]


def _exit_day_of(t: dict) -> str:
    return t["exit_day"] or t["exit_day_assumed"]


def _cached_contract(pricer: CachedPricer, t: dict, mode: str):
    """(strike, contract, entry-day candles, exit-day candles) from the caches."""
    d, xd = date.fromisoformat(t["day"]), date.fromisoformat(_exit_day_of(t))
    strike = atm_strike(t["entry_spot"])
    for e in pick_expiries(pricer.expiries, d, xd, mode):
        key = f"{e.isoformat()}|{strike:.0f}|{t['option_type']}"
        c = pricer.contracts.get(key)
        if c:
            c = dict(c, ckey=key)
            ec = next((pricer.candles[k] for k in _candle_keys(c, t["day"])
                       if pricer.candles.get(k)), {})
            xc = next((pricer.candles[k] for k in _candle_keys(c, t["exit_day"])
                       if pricer.candles.get(k)), {}) if t["exit_day"] else {}
            eo = next((pricer.ohlc[k] for k in _candle_keys(c, t["day"])
                       if pricer.ohlc.get(k)), {})
            xo = next((pricer.ohlc[k] for k in _candle_keys(c, t["exit_day"])
                       if pricer.ohlc.get(k)), {}) if t["exit_day"] else {}
            return strike, c, ec, xc, eo, xo
    return strike, None, {}, {}, {}, {}


def _leg_complete(t: dict, c, ec, xc, eo, xo) -> bool:
    """Everything the caches must hold for this night, including the minute
    highs and lows the worst-fill rule needs; an open trade only needs its
    entry day."""
    return bool(c and ec and eo and ((xc and xo) or not t["exit_day"]))


async def _intraday_option_closes(op: OptionPricer, contract: dict, day: date) -> dict:
    """Today's premiums, which the historical endpoint does not serve yet.
    Cached under the contract's stable key only once the session is over."""
    url = (f"{UPSTOX_BASE_V3}/historical-candle/intraday/"
           f"{quote(contract['instrument_key'], safe='')}/minutes/1")
    try:
        data = await api_get(op.client, url, op.token, op.limiter)
    except RuntimeError as exc:
        print(f"  ! intraday {contract['trading_symbol']}: {exc}")
        return {}
    raw = (data.get("data", {}) or {}).get("candles", []) or []
    got = {c[0][11:16]: float(c[4]) for c in raw if len(c) >= 5}
    if got and _session_closed_now():
        op.candles[_candle_keys(contract, day.isoformat())[0]] = got
    return got


async def _day_closes(op: OptionPricer, contract: dict, day: date) -> dict:
    got = await op.candles_for(contract, day)
    if not got and day == datetime.now(IST).date():
        got = await _intraday_option_closes(op, contract, day)
    return got


async def _fetch_night(op: OptionPricer, t: dict, mode: str) -> bool:
    d, xd = date.fromisoformat(t["day"]), date.fromisoformat(_exit_day_of(t))
    strike = atm_strike(t["entry_spot"])
    for e in pick_expiries(op.expiries, d, xd, mode):
        c = await op._resolve(e, strike, t["option_type"])
        if c:
            a = await op.ohlc_for(c, d) or await _day_closes(op, c, d)
            b = await op.ohlc_for(c, xd) if t["exit_day"] else True
            return bool(a and b)
    return False


# A strike can go a few minutes without a print, most often a far expiry at the
# open.  Within this many minutes the nearest print stands in: for an entry the
# LAST one before (the price on the screen when the order goes in), for an exit
# the FIRST one after (the first price the exit can get).  The minute used is
# logged whenever it is not the nominal one.
PX_TOLERANCE_MIN = 5


def _px_at(candles: dict, hhmm: str, direction: int):
    if hhmm in candles:
        return candles[hhmm], hhmm
    m0 = int(hhmm[:2]) * 60 + int(hhmm[3:])
    for k in range(1, PX_TOLERANCE_MIN + 1):
        m = m0 + k * direction
        key = f"{m // 60:02d}:{m % 60:02d}"
        if key in candles:
            return candles[key], key
    return None, None


def _bar_at(xo: dict, hhmm: str, direction: int):
    """[o,h,l,c] of the minute, else the nearest within tolerance."""
    if hhmm in xo:
        return xo[hhmm], hhmm
    m0 = int(hhmm[:2]) * 60 + int(hhmm[3:])
    for k in range(1, PX_TOLERANCE_MIN + 1):
        m = m0 + k * direction
        key = f"{m // 60:02d}:{m % 60:02d}"
        if key in xo:
            return xo[key], key
    return None, None


def _leg(strike, c, ec, xc, eo, xo, t: dict) -> dict:
    """One contract's result.  HEADLINE FILLS ARE THE WORST OF THE MINUTE (the
    user's rule of 2026-09-19): bought at the entry minute's HIGH, sold at the
    exit minute's LOW.  The close-fill figures are kept beside them
    (`*_close`) for comparison; `fill` says which the headline used."""
    leg = {"strike": strike, "symbol": None, "expiry": None, "dte": None,
           "entry_px": None, "exit_px": None, "entry_minute": None, "exit_minute": None,
           "prem_pts": None, "prem_pct": None, "pnl_rs": None, "capital_rs": None,
           "costs_rs": None, "net_rs": None, "entry_px_close": None, "exit_px_close": None,
           "pnl_rs_close": None, "net_rs_close": None, "fill": None, "reason": None, "note": None}
    if not c:
        leg["reason"] = "no contract"
        return leg
    leg["symbol"] = c["trading_symbol"]
    leg["expiry"] = c["ckey"].split("|")[0]
    leg["dte"] = (date.fromisoformat(leg["expiry"]) - date.fromisoformat(t["day"])).days
    e_px, e_min = _px_at(ec, t["entry_time"], -1)
    if e_px is None:
        leg["reason"] = f"no premium within {PX_TOLERANCE_MIN} min of entry {t['entry_time']}"
        return leg
    # worst entry: the minute's HIGH when the minute bar is known, else the close
    ebar, _ = _bar_at(eo or {}, t["entry_time"], -1)
    e_w = ebar[1] if ebar else None
    leg["fill"] = "worst" if e_w is not None else "close"
    e_use = e_w if e_w is not None else e_px
    leg["entry_px"], leg["entry_minute"], leg["entry_px_close"] = round(e_use, 2), e_min, round(e_px, 2)
    leg["capital_rs"] = capital_required("buy", t["entry_spot"], LOT_SIZE, e_use)
    notes = []
    if e_min != t["entry_time"]:
        notes.append(f"entry priced at {e_min} (no {t['entry_time']} print)")
    if leg["fill"] == "close":
        notes.append("no minute high/low - filled at closes")
    if not t["exit_day"]:
        leg["reason"] = "open - no exit yet"
        leg["note"] = "; ".join(notes) or None
        return leg
    x_px, x_min = _px_at(xc, t["exit_time"], +1)
    if x_px is None:
        leg["reason"] = (f"no premium within {PX_TOLERANCE_MIN} min of exit "
                         f"{t['exit_day']} {t['exit_time']}")
        return leg
    if x_min != t["exit_time"]:
        notes.append(f"exit priced at {x_min} (no {t['exit_time']} print)")
    # worst exit: the LOW of the exit minute
    xbar, _ = _bar_at(xo or {}, t["exit_time"], +1)
    x_use = xbar[2] if (xbar and leg["fill"] == "worst") else x_px
    if xbar is None and leg["fill"] == "worst":
        leg["fill"] = "close"; x_use = x_px
        notes.append("no exit-minute high/low - exit filled at close")
    costs_c = option_round_trip("buy", e_px, x_px, LOT_SIZE)["total"]
    costs = option_round_trip("buy", e_use, x_use, LOT_SIZE)["total"]
    leg.update(exit_px=round(x_use, 2), exit_minute=x_min, exit_px_close=round(x_px, 2),
               prem_pts=round(x_use - e_use, 2),             # a BOUGHT option, both sides
               prem_pct=(x_use - e_use) / e_use * 100.0,
               pnl_rs=round((x_use - e_use) * LOT_SIZE, 2),
               costs_rs=costs, net_rs=round((x_use - e_use) * LOT_SIZE - costs, 2),
               pnl_rs_close=round((x_px - e_px) * LOT_SIZE, 2),
               net_rs_close=round((x_px - e_px) * LOT_SIZE - costs_c, 2),
               note="; ".join(notes) or None)
    return leg


LEG_KEYS = ("strike", "symbol", "expiry", "dte", "entry_px", "exit_px",
            "entry_minute", "exit_minute", "prem_pts", "prem_pct", "pnl_rs",
            "capital_rs", "costs_rs", "net_rs", "entry_px_close", "exit_px_close",
            "pnl_rs_close", "net_rs_close", "fill")


async def price_trades(trades: list[dict], offline: bool, token: str | None,
                       default_mode: str) -> tuple[int, int]:
    """Puts a premium on every closed trade it can, under every expiry mode.
    One night = two contract days (entry day, exit day), which is why
    ensure_cached() is not reused: it fetches the entry day only."""
    closed = [t for t in trades if t["status"] == "closed"]
    # Open trades (no next session yet) still get their contract and entry
    # premium, so today's signal shows what it bought.
    priceable = [t for t in trades if t["entry_spot"] is not None
                 and (t["status"] == "closed" or t["status"].startswith("open"))]
    if not priceable:
        return 0, 0
    modes = [k for k, _ in EXPIRY_MODES]
    pricer = CachedPricer()
    need = [(t, m) for t in priceable for m in modes
            if not _leg_complete(t, *_cached_contract(pricer, t, m)[1:])]
    print(f"  {len(need)} night/expiry legs lack a contract, closes or minute highs/lows")
    if need and not offline and token:
        print(f"  fetching option series for {len(need)} night/expiry combinations ...")
        client = httpx.AsyncClient(timeout=30.0)
        op = OptionPricer(client, token, RateLimiter(), offline=False)
        await op.load_calendar(date.fromisoformat(min(t["day"] for t, _ in need)),
                               date.fromisoformat(max(_exit_day_of(t) for t, _ in need)))
        got = 0
        for i, (t, m) in enumerate(need, 1):
            got += await _fetch_night(op, t, m)
            if i % 25 == 0:
                op.save()
        op.save()
        await client.aclose()
        print(f"  fetched {got}/{len(need)} (contracts {op.fetched_contracts}, "
              f"days {op.fetched_days})")
        pricer.reload()
    elif need:
        print(f"  ! {len(need)} night/expiry combinations without option data and no "
              f"token (offline={offline}) - shown as 'no option data'")

    priced = 0
    for t in priceable:
        t["legs"] = {m: _leg(*_cached_contract(pricer, t, m), t) for m in modes}
        leg = t["legs"][default_mode]
        t.update({k: leg[k] for k in LEG_KEYS})
        t["price_reason"] = leg["reason"] or leg["note"]
        priced += leg["prem_pct"] is not None
    return priced, len(closed)


# ---------------------------------------------------------------------------
# Statistics - all size-free
# ---------------------------------------------------------------------------

def stats(vals: list[float | None]) -> dict:
    v = [x for x in vals if x is not None]
    n = len(v)
    if n == 0:
        return {"n": 0, "wins": 0, "losses": 0, "flat": 0, "win_rate": None,
                "mean": None, "median": None, "std": None, "t": None, "pf": None,
                "best": None, "worst": None, "total": None}
    wins = sum(1 for x in v if x > 0)
    losses = sum(1 for x in v if x < 0)
    mean = statistics.fmean(v)
    std = statistics.stdev(v) if n > 1 else None
    gw = sum(x for x in v if x > 0)
    gl = -sum(x for x in v if x < 0)
    return {"n": n, "wins": wins, "losses": losses, "flat": n - wins - losses,
            "win_rate": wins / n * 100.0, "mean": mean,
            "median": statistics.median(v), "std": std,
            "t": (mean / (std / math.sqrt(n))) if std else None,
            "pf": (gw / gl) if gl > 0 else None, "best": max(v), "worst": min(v),
            "total": sum(v)}


def book(trades: list[dict]) -> dict:
    closed = [t for t in trades if t["status"] == "closed"]
    priced = [t for t in closed if t["prem_pct"] is not None]
    legs = {}
    for m, _ in EXPIRY_MODES:
        v = [t["legs"][m] for t in closed
             if t.get("legs") and t["legs"][m]["prem_pct"] is not None]
        legs[m] = {**stats([l["prem_pct"] for l in v]),
                   "rs": sum(l["pnl_rs"] for l in v) if v else None,
                   "costs": sum(l["costs_rs"] for l in v) if v else None,
                   "rs_net": sum(l["net_rs"] for l in v) if v else None,
                   "net_wins": sum(1 for l in v if l["net_rs"] > 0),
                   "net_losses": sum(1 for l in v if l["net_rs"] < 0),
                   "dte1": sum(1 for l in v if l["dte"] == 1),
                   "avg_entry_px": statistics.fmean(l["entry_px"] for l in v) if v else None}
    return {"signals": len(trades), "closed": len(closed), "priced": len(priced),
            "spot_pct": stats([t["spot_pct"] for t in closed]),
            "spot_pct_open": stats([t["spot_pct_open"] for t in closed]),
            "spot_pts": stats([t["spot_pts"] for t in closed]),
            "prem_pct": stats([t["prem_pct"] for t in priced]),
            "rs": sum(t["pnl_rs"] for t in priced) if priced else None,
            "costs": sum(t["costs_rs"] for t in priced) if priced else None,
            "rs_net": sum(t["net_rs"] for t in priced) if priced else None,
            "net_stats": stats([t["net_rs"] for t in priced]),
            "rs_net_close": sum(t["net_rs_close"] for t in priced if t["net_rs_close"] is not None) if priced else None,
            "worst_filled": sum(1 for t in priced if t["fill"] == "worst"),
            "capital_avg": statistics.fmean(t["capital_rs"] for t in priced) if priced else None,
            "rs_worst": min(t["pnl_rs"] for t in priced) if priced else None,
            "worst_spot_day": min(closed, key=lambda t: t["spot_pct"])["day"] if closed else None,
            "worst_prem_day": min(priced, key=lambda t: t["prem_pct"])["day"] if priced else None,
            "legs": legs}


def grouped(trades: list[dict], key) -> list[dict]:
    g: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        g[key(t)].append(t)
    return [{"key": k, **book(g[k])} for k in sorted(g)]


def benchmark(series: list[dict], sessions: dict[str, dict], all_days: list[str],
              signals: list[dict], from_iso: str) -> dict:
    """The unconditional overnight move, 15:29 close -> next first-candle close,
    LONG sign, on the same sessions - so a SELL book can be read against
    'always short' and a HOLD against what it left alone."""
    pos = {d: k for k, d in enumerate(all_days)}
    dec = {x["day"]: x for x in signals}
    groups: dict[str, list[float]] = defaultdict(list)
    for s in series:
        if s["day"] < from_iso or s["entry"] is None:
            continue
        k = pos[s["day"]]
        if k + 1 >= len(all_days):
            continue
        nxt = sessions[all_days[k + 1]]
        if nxt["first"] is None:
            continue
        mv = (nxt["first"]["c"] / s["entry"]["c"] - 1.0) * 100.0
        groups["every session"].append(mv)
        x = dec.get(s["day"])
        if x is None:
            continue
        if x["decision"] == "HOLD":
            groups["HOLD sessions" + (" (base false)" if x["data_ok"] else " (data)")].append(mv)
        else:
            groups[x["decision"] + " sessions"].append(mv)
    return {k: stats(v) for k, v in groups.items()}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

SIGNAL_COLS = ["date", "decision", "trigger_a", "trigger_b", "trigger_c", "base_signal",
               "exhaustion", "trend30", "sma10", "location30", "momentum10",
               "momentum15", "volatility_ratio10", "daily_range_ratio20",
               "close_1514", "day_open", "day_high", "day_low", "high30", "low30",
               "vol10", "vol10_avg20", "daily_range_pct", "range_avg20",
               "official_close", "hold_reason"]
TRADE_COLS = ["date", "decision", "side", "triggers", "exhaustion", "entry_time",
              "entry_spot", "entry_open_1529", "exit_day", "exit_time", "exit_spot",
              "next_open", "spot_pts", "spot_pct", "spot_pct_at_1529_open", "status",
              "expiry_mode", "strike", "option_type", "symbol", "expiry", "dte",
              "entry_px", "entry_px_minute", "exit_px", "exit_px_minute", "prem_pts",
              "prem_pct", "pnl_rs", "costs_rs", "net_rs", "capital_rs", "fill",
              "entry_px_close", "exit_px_close", "net_rs_close", "price_reason",
              "prem_pct_next", "prem_pct_skip1dte", "prem_pct_always"]


def _yn(v):
    return "" if v is None else ("true" if v else "false")


def _r(v, d=4):
    return "" if v is None else f"{v:.{d}f}"


def write_signals_csv(signals: list[dict], official: dict, path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SIGNAL_COLS)
        for x in signals:
            oc = official.get(x["day"], {}).get("c")
            w.writerow([x["day"], x["decision"], _yn(x["trigger_a"]), _yn(x["trigger_b"]),
                        _yn(x["trigger_c"]), _yn(x["base_signal"]), _yn(x["exhaustion"]),
                        _r(x["trend30"]), _r(x["sma10"], 2), _r(x["location30"]),
                        _r(x["momentum10"], 2), _r(x["momentum15"], 2),
                        _r(x["volatility_ratio10"]), _r(x["daily_range_ratio20"]),
                        _r(x["close"], 2), _r(x["day_open"], 2), _r(x["day_high"], 2),
                        _r(x["day_low"], 2), _r(x["high30"], 2), _r(x["low30"], 2),
                        _r(x["vol10"], 5), _r(x["vol10_avg20"], 5),
                        _r(x["daily_range_pct"]), _r(x["range_avg20"]),
                        _r(oc, 2), x["hold_reason"]])
    print(f"  signals -> {path}")


def write_trades_csv(trades: list[dict], mode: str, path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(TRADE_COLS)
        for t in trades:
            legs = t.get("legs") or {}
            w.writerow([t["day"], t["decision"], t["side"], t["pattern"], _yn(t["exhaustion"]),
                        t["entry_time"], _r(t["entry_spot"], 2), _r(t["entry_open_1529"], 2),
                        t["exit_day"] or "", t["exit_time"] or "", _r(t["exit_spot"], 2),
                        _r(t["next_open"], 2), _r(t["spot_pts"], 2), _r(t["spot_pct"]),
                        _r(t["spot_pct_open"]), t["status"], mode if legs else "",
                        _r(t["strike"], 0), t["option_type"],
                        t["symbol"] or "", t["expiry"] or "",
                        "" if t["dte"] is None else t["dte"], _r(t["entry_px"], 2),
                        t["entry_minute"] or "", _r(t["exit_px"], 2), t["exit_minute"] or "",
                        _r(t["prem_pts"], 2), _r(t["prem_pct"]),
                        _r(t["pnl_rs"], 2), _r(t["costs_rs"], 2), _r(t["net_rs"], 2),
                        _r(t["capital_rs"], 0), t["fill"] or "", _r(t["entry_px_close"], 2),
                        _r(t["exit_px_close"], 2), _r(t["net_rs_close"], 2), t["price_reason"] or "",
                        _r(legs.get("next", {}).get("prem_pct")),
                        _r(legs.get("skip-1dte", {}).get("prem_pct")),
                        _r(legs.get("always", {}).get("prem_pct"))])
    print(f"  trades  -> {path}")


def _fmt(v, d=2, suffix=""):
    return "n/a" if v is None else f"{v:+.{d}f}{suffix}" if d else f"{v}{suffix}"


def verdict_text(books: dict, meta: dict, cas: list[dict]) -> str:
    a, b, s = books["ALL"], books["BUY"], books["SELL"]
    sp, pp = a["spot_pct"], a["prem_pct"]
    parts = [f"Over {meta['sessions']} sessions the rule gave {meta['counts']['SELL']} SELL, "
             f"{meta['counts']['BUY']} BUY and {meta['counts']['HOLD']} HOLD "
             f"({meta['counts']['HOLD_data']} of the HOLDs for data validity)."]
    if sp["n"]:
        pf = "n/a" if sp["pf"] is None else f"{sp['pf']:.2f}"
        parts.append(f"On spot, {sp['n']} closed nights: mean {_fmt(sp['mean'], 3, '%')}, "
                     f"median {_fmt(sp['median'], 3, '%')}, win rate {sp['win_rate']:.1f}%, "
                     f"profit factor {pf}, t = {_fmt(sp['t'], 2)}.")
        if s["spot_pct"]["n"] and b["spot_pct"]["n"]:
            parts.append(f"SELL {s['spot_pct']['n']} nights at {_fmt(s['spot_pct']['mean'], 3, '%')} "
                         f"({s['spot_pct']['win_rate']:.1f}% win); BUY {b['spot_pct']['n']} at "
                         f"{_fmt(b['spot_pct']['mean'], 3, '%')} ({b['spot_pct']['win_rate']:.1f}% win).")
        if len(cas) == 2 and all(c["spot_pct"]["n"] >= 2 for c in cas):
            pre, post = cas[0], cas[1]
            parts.append(f"Split at the closing-auction date {CAS_DATE}: before it "
                         f"{pre['spot_pct']['n']} nights at {_fmt(pre['spot_pct']['mean'], 3, '%')} "
                         f"({pre['spot_pct']['win_rate']:.1f}% win, t {_fmt(pre['spot_pct']['t'], 2)}); "
                         f"from it {post['spot_pct']['n']} nights at "
                         f"{_fmt(post['spot_pct']['mean'], 3, '%')} "
                         f"({post['spot_pct']['win_rate']:.1f}% win, t {_fmt(post['spot_pct']['t'], 2)}).")
    if pp["n"]:
        parts.append(f"Priced as bought ATM options, {meta['expiry_mode']} expiry "
                     f"({pp['n']} of {a['closed']} nights): mean {_fmt(pp['mean'], 2, '%')} of "
                     f"premium, median {_fmt(pp['median'], 2, '%')}, win rate {pp['win_rate']:.1f}%, "
                     f"gross Rs {a['rs']:,.0f} less brokerage and taxes Rs {a['costs']:,.0f} = "
                     f"net Rs {a['rs_net']:,.0f} on one lot of {LOT_SIZE} "
                     f"({a['net_stats']['wins']} W / {a['net_stats']['losses']} L net).")
    return " ".join(parts)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EOD trend signal v1</title>
<style>
  :root {
    color-scheme: light;
    --surface:#fcfcfb; --page:#f4f4f1; --ink:#0b0b0b; --ink2:#52514e; --muted:#8b8983;
    --grid:#e3e2db; --border:rgba(11,11,11,.10);
    --up:#128a5a; --down:#d0453f; --accent:#2a78d6; --warn:#b8860b; --zone:#7a5cd0;
    --chip:#eceae3;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --border:rgba(255,255,255,.10);
      --up:#3ecf8e; --down:#e66767; --accent:#5b9df0; --warn:#e0b341; --zone:#a68bf0;
      --chip:#262624;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --border:rgba(255,255,255,.10);
    --up:#3ecf8e; --down:#e66767; --accent:#5b9df0; --warn:#e0b341; --zone:#a68bf0;
    --chip:#262624;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--page);color:var(--ink);
       font:13px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
  .wrap{max-width:1500px;margin:0 auto;padding:20px 16px 80px}
  h1{font-size:20px;margin:0 0 4px}
  h2{font-size:15px;margin:28px 0 10px;color:var(--ink);
     border-bottom:1px solid var(--border);padding-bottom:6px}
  .sub{color:var(--muted);font-size:12px;margin-bottom:14px}
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:8px;
         padding:14px 16px;margin-bottom:14px}
  .note{background:var(--chip);border-left:3px solid var(--accent);
        border-radius:0 6px 6px 0;padding:10px 14px;margin:10px 0;
        color:var(--muted);font-size:12px}
  .note b{color:var(--ink)}
  .warn{border-left-color:var(--warn)}
  .controls{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;margin-bottom:14px}
  .ctl{display:flex;flex-direction:column;gap:4px}
  .ctl label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
  select,button{background:var(--chip);color:var(--ink);border:1px solid var(--border);
         border-radius:6px;padding:6px 10px;font:inherit}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
  .card{background:var(--chip);border:1px solid var(--border);border-radius:8px;padding:12px 14px}
  .card .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
  .card .v{font-size:20px;font-weight:600;margin-top:3px}
  table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
  th,td{padding:6px 9px;text-align:right;border-bottom:1px solid var(--border);white-space:nowrap}
  th{color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase;
     letter-spacing:.03em;position:sticky;top:0;background:var(--surface)}
  td.l,th.l{text-align:left}
  tr:hover td{background:var(--chip)}
  .pos{color:var(--up)} .neg{color:var(--down)} .dimc{color:var(--muted)}
  .scroll{max-height:560px;overflow:auto;border:1px solid var(--border);border-radius:8px}
  svg{display:block;width:100%;height:auto;background:var(--surface);
      border:1px solid var(--border);border-radius:8px}
  .chartbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0}
  .chartbar label{color:var(--muted);font-size:12px;display:flex;gap:5px;align-items:center}
  .pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:10.5px;
        font-weight:600;letter-spacing:.02em;white-space:nowrap}
  .pill.buy{background:rgba(18,138,90,.15);color:var(--up)}
  .pill.sell{background:rgba(208,69,63,.15);color:var(--down)}
  .pill.hold{background:var(--chip);color:var(--muted)}
  .pill.data{background:rgba(184,134,11,.15);color:var(--warn)}
  .tick{color:var(--up);font-weight:600} .cross{color:var(--muted)}
  .rule{display:grid;grid-template-columns:150px 1fr;gap:4px 14px;font-size:12.5px}
  .rule b{color:var(--ink)}
  .rule .k{color:var(--muted)}
  details{margin-top:28px;border:1px solid var(--border);border-radius:8px;
          background:var(--surface);padding:0 14px}
  details[open]{padding-bottom:12px}
  summary{cursor:pointer;padding:12px 0;color:var(--ink2);font-size:13px;font-weight:500}
  code{background:var(--chip);padding:0 4px;border-radius:3px;font-size:11.5px}
  svg.drag{cursor:grabbing}
  #tip{position:fixed;pointer-events:none;display:none;background:var(--surface);
       border:1px solid var(--border);border-radius:6px;padding:6px 9px;
       font-size:11px;z-index:9;box-shadow:0 4px 16px rgba(0,0,0,.18)}
  .setup{padding:8px 12px;border-radius:6px;margin:0 0 8px;font-size:12.5px;
         border:1px solid var(--border);background:var(--chip);color:var(--ink2);line-height:1.7}
  .setup.neg{border-left:4px solid var(--down)}
  .setup.pos{border-left:4px solid var(--up)}
  .setup.dim{border-left:4px solid var(--muted)}
  .setup b{color:var(--ink)}
  .setup .r{display:inline-block;min-width:110px;color:var(--muted)}
</style>
</head>
<body>
<div class="wrap">
  <h1>EOD trend signal v1 &mdash; BUY / SELL / HOLD after the 15:14 candle, held overnight</h1>
  <div class="sub" id="sub"></div>
  <div class="controls">
    <div class="ctl"><label>Window</label><select id="winSel"></select></div>
    <div class="sub" id="winNote" style="margin:0;align-self:center"></div>
  </div>
  <div class="note warn" id="verdict"></div>

  <h2>Overall</h2>
  <div class="cards" id="cards"></div>
  <div class="chartbar" style="margin-top:12px">
    <label>Equity curve:
      <select id="eqSel">
        <option value="spot_pct">spot, cumulative %</option>
        <option value="spot_pts">spot, cumulative points</option>
        <option value="prem_pct">premium, cumulative % (priced nights only)</option>
        <option value="pnl_rs">rupees on one lot (priced nights only)</option>
      </select>
    </label>
  </div>
  <svg id="equity" viewBox="0 0 1200 210" preserveAspectRatio="xMidYMid meet"></svg>

  <h2>Chart &mdash; the signal day, the exit, and the rule</h2>
  <div class="chartbar">
    <select id="daySel"></select>
    <label><input type="checkbox" id="showRules" checked> rule windows &amp; momentum</label>
    <label><input type="checkbox" id="showLevels" checked> SMA10 / 30-session levels</label>
    <label><input type="checkbox" id="showTrade" checked> entry / exit</label>
    <button id="zoomFocus">14:30 &rarr; 10:00</button>
    <button id="zoomIn">+</button><button id="zoomOut">&minus;</button>
    <button id="zoomReset">both sessions</button>
    <span class="tag" id="dayTag"></span>
  </div>
  <div id="setupBanner" class="setup dim"></div>
  <svg id="chart" viewBox="0 0 1200 520" preserveAspectRatio="xMidYMid meet"></svg>
  <div id="tip"></div>

  <h2>By side</h2>
  <div class="scroll"><table id="tblSide"></table></div>

  <h2>By trigger combination</h2>
  <div class="sub">Which of A, B, C were true on the signal day. The exhaustion trigger decides BUY against SELL, so each pattern can hold both.</div>
  <div class="scroll"><table id="tblTrig"></table></div>

  <h2>What the same nights did unconditionally</h2>
  <div class="sub">15:29 close &rarr; next first-candle close, LONG sign, on every session of the window and on each decision class. A SELL book is read against the row it fired on.</div>
  <div class="scroll"><table id="tblBench"></table></div>

  <h2>Monthly</h2>
  <div class="scroll"><table id="tblMonth"></table></div>

  <h2>Stability &mdash; halves, the closing-auction split, years</h2>
  <div class="sub">One window cannot carry a stability claim; these rows are here so a regime shows up as one. The full-history figures in the header note are the reference.</div>
  <div class="scroll"><table id="tblStab"></table></div>

  <h2>Entry fill &mdash; 15:29 close against 15:29 open</h2>
  <div class="sub" id="fillSub"></div>
  <div class="scroll"><table id="tblFill"></table></div>

  <h2>Which expiry prices the night</h2>
  <div class="sub">Every closed night priced under all three choices; the marked row fills the premium columns above. DTE&nbsp;1 counts nights that exit on the contract&rsquo;s own expiry morning.</div>
  <div class="scroll"><table id="tblExpiry"></table></div>

  <h2>Trades</h2>
  <div class="scroll"><table id="tblTrades"></table></div>

  <h2>Signal log &mdash; every session</h2>
  <div class="chartbar">
    <label><input type="checkbox" id="onlyFired"> only BUY / SELL</label>
    <label><input type="checkbox" id="onlyData"> only data HOLDs</label>
  </div>
  <div class="scroll"><table id="tblLog"></table></div>

  <h2>Why sessions were HOLD</h2>
  <div class="scroll"><table id="tblHold"></table></div>

  <details open id="notes">
    <summary>Notes &mdash; the rule, the fill conventions and what limits these numbers</summary>
    <div class="panel"><div class="rule" id="rule"></div></div>
    <div class="note" id="fills"></div>
    <div class="note warn" id="limits"></div>
  </details>
</div>

<script>
const DATA = __DATA_JSON__;
const M = DATA.meta;
const $ = id => document.getElementById(id);
const fmt = (v, d = 2) => (v === null || v === undefined) ? '&mdash;'
  : Number(v).toLocaleString('en-IN', {minimumFractionDigits: d, maximumFractionDigits: d});
const sign = v => (v === null || v === undefined) ? 'dimc' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : 'dimc'));
const cell = (v, d = 2, suf = '') => '<td class="' + sign(v) + '">' + fmt(v, d) + (v === null || v === undefined ? '' : suf) + '</td>';
const plain = (v, d = 2, suf = '') => '<td>' + fmt(v, d) + (v === null || v === undefined ? '' : suf) + '</td>';
const pill = dec => '<span class="pill ' + dec.toLowerCase() + '">' + dec + '</span>';
function fill(sel, opts, def) {
  sel.innerHTML = opts.map(o => '<option value="' + o.k + '"' + (o.k === def ? ' selected' : '') + '>' + o.v + '</option>').join('');
}
const tick = v => v === null || v === undefined ? '<td class="cross">&mdash;</td>'
  : (v ? '<td class="tick">&#10003;</td>' : '<td class="cross">&#10007;</td>');

let curWin = DATA.default_view, V = DATA.views[curWin], BOOK_HEAD;
fill($('winSel'), Object.keys(DATA.views).map(k => ({k, v: DATA.views[k].label})), curWin);
$('winSel').onchange = () => { curWin = $('winSel').value; V = DATA.views[curWin]; renderAll(); };

function renderAll() {
$('sub').innerHTML =
  V.sessions + ' sessions &nbsp;' + V.from + ' &rarr; ' + V.to +
  ' &nbsp;&middot;&nbsp; decision at 15:14, entry 15:29, exit next session 09:15; fills: bought at the entry minute HIGH, sold at the exit minute LOW' +
  ' &nbsp;&middot;&nbsp; partial sessions: ' + M.partial +
  ' &nbsp;&middot;&nbsp; option expiry: ' + M.expiry_mode +
  ' &nbsp;&middot;&nbsp; thresholds fixed: vol ' + M.thresholds.vol + ', location ' +
  M.thresholds.loc + ', range ' + M.thresholds.range +
  ' &nbsp;&middot;&nbsp; generated ' + M.generated;
$('winNote').innerHTML = curWin === 'cas'
  ? 'The rule is built for the market after the closing auction, so this is the default view. ' +
    V.sessions + ' sessions is a very small sample: every ratio here moves about ' +
    (V.books.ALL.closed ? (100 / V.books.ALL.closed).toFixed(1) : '?') + ' points of win rate per night.'
  : curWin === '6m'
  ? 'The house default window, the last 6 months: ' + V.sessions + ' sessions from ' + V.from + '.'
  : 'The whole period a real premium P&amp;L exists for: ' + V.sessions + ' sessions from ' + V.from + ', the start of the broker&rsquo;s option archive. Earlier years are spot only and are summarised in the note above. A partial session makes every window that contains it HOLD (see the HOLD reasons table).';
$('verdict').innerHTML = '<b>This window.</b> ' + V.verdict +
  '<br><br><b>Full history, ' + M.wide.window + ' (recorded from the wide run, spot only).</b> ' + M.wide.text;

/* ---------- cards ---------- */
(function () {
  const a = V.books.ALL, sp = a.spot_pct, pp = a.prem_pct;
  const cards = [
    ['SELL / BUY / HOLD', V.counts.SELL + ' / ' + V.counts.BUY + ' / ' + V.counts.HOLD, ''],
    ['closed nights', a.closed, ''],
    ['spot wins / losses', '<span class="pos">' + sp.wins + '</span> / <span class="neg">' + sp.losses + '</span>' + (sp.flat ? ' <span class="dimc">(' + sp.flat + ' flat)</span>' : ''), ''],
    ['spot max loss', sp.worst === null ? null : fmt(sp.worst, 3) + '% <span class="dimc" style="font-size:12px">' + fmt(a.spot_pts.worst, 1) + ' pts, ' + a.worst_spot_day + '</span>', 'neg'],
    ['spot win rate', sp.win_rate === null ? null : fmt(sp.win_rate, 1) + '%', sign(sp.win_rate === null ? null : sp.win_rate - 50)],
    ['spot mean', sp.mean === null ? null : fmt(sp.mean, 3) + '%', sign(sp.mean)],
    ['spot median', sp.median === null ? null : fmt(sp.median, 3) + '%', sign(sp.median)],
    ['spot profit factor', sp.pf === null ? null : fmt(sp.pf, 2), sign(sp.pf === null ? null : sp.pf - 1)],
    ['spot t', sp.t === null ? null : fmt(sp.t, 2), sign(sp.t)],
    ['spot total', a.spot_pts.total === null ? null : fmt(a.spot_pts.total, 1) + ' pts', sign(a.spot_pts.total)],
    ['priced nights', a.priced + ' / ' + a.closed, ''],
    ['premium wins / losses (net of costs)', a.net_stats.n ? '<span class="pos">' + a.net_stats.wins + '</span> / <span class="neg">' + a.net_stats.losses + '</span>' : null, ''],
    ['premium max loss', pp.worst === null ? null : fmt(pp.worst, 1) + '% <span class="dimc" style="font-size:12px">&#8377;' + fmt(a.rs_worst, 0) + ', ' + a.worst_prem_day + '</span>', 'neg'],
    ['premium mean', pp.mean === null ? null : fmt(pp.mean, 2) + '%', sign(pp.mean)],
    ['premium win rate (net of costs)', a.net_stats.win_rate === null ? null : fmt(a.net_stats.win_rate, 1) + '%', sign(a.net_stats.win_rate === null ? null : a.net_stats.win_rate - 50)],
    ['gross &#8377; one lot', a.rs === null ? null : fmt(a.rs, 0), sign(a.rs)],
    ['brokerage &amp; taxes', a.costs === null ? null : fmt(a.costs, 0) + ' <span class="dimc" style="font-size:12px">' + fmt(a.costs / a.priced, 0) + ' / night</span>', 'neg'],
    ['net &#8377; one lot (worst fills)', a.rs_net === null ? null : fmt(a.rs_net, 0) + (a.worst_filled < a.priced ? ' <span class="dimc" style="font-size:12px">high/low on ' + a.worst_filled + ' of ' + a.priced + '</span>' : ''), sign(a.rs_net)],
    ['net &#8377; if filled at closes', a.rs_net_close === null ? null : fmt(a.rs_net_close, 0), sign(a.rs_net_close)],
    ['net wins / losses', a.net_stats.n ? '<span class="pos">' + a.net_stats.wins + '</span> / <span class="neg">' + a.net_stats.losses + '</span>' : null, ''],
    ['avg capital / lot', a.capital_avg === null ? null : '&#8377;' + fmt(a.capital_avg, 0) + ' <span class="dimc" style="font-size:12px">premium paid</span>', ''],
    ['return on capital (net)', a.capital_avg ? fmt(a.rs_net / a.capital_avg * 100, 1) + '%' : null, sign(a.rs_net)],
  ];
  $('cards').innerHTML = cards.map(c =>
    '<div class="card"><div class="k">' + c[0] + '</div><div class="v ' + c[2] + '">' +
    (c[1] === null ? '&mdash;' : c[1]) + '</div></div>').join('');
})();

/* ---------- equity ---------- */
function drawEquity() {
  const key = $('eqSel').value, el = $('equity');
  const rows = V.trades.filter(t => t.status === 'closed' && t[key] !== null && t[key] !== undefined);
  if (rows.length < 2) { el.innerHTML = '<text x="20" y="30" fill="var(--muted)" font-size="12">fewer than two data points</text>'; return; }
  let cum = 0;
  const pts = rows.map(t => { cum += t[key]; return {d: t.day, v: cum}; });
  const W2 = 1200, H2 = 210, L = 74, R = 16, T = 14, B = 26;
  const lo = Math.min(0, ...pts.map(p => p.v)), hi = Math.max(0, ...pts.map(p => p.v));
  const pad = (hi - lo) * 0.08 || 1;
  const X = i => L + i / (pts.length - 1) * (W2 - L - R);
  const Y = v => T + (hi + pad - v) / (hi - lo + 2 * pad) * (H2 - T - B);
  const dec = key === 'pnl_rs' ? 0 : (key === 'spot_pts' ? 0 : 2);
  let g = '';
  for (let k = 0; k <= 4; k++) {
    const v = lo - pad + (hi - lo + 2 * pad) * k / 4;
    g += '<line x1="' + L + '" y1="' + Y(v) + '" x2="' + (W2 - R) + '" y2="' + Y(v) +
      '" stroke="var(--grid)"/><text x="' + (L - 6) + '" y="' + (Y(v) + 3) +
      '" fill="var(--muted)" font-size="10" text-anchor="end">' + fmt(v, dec) + '</text>';
  }
  g += '<line x1="' + L + '" y1="' + Y(0) + '" x2="' + (W2 - R) + '" y2="' + Y(0) +
    '" stroke="var(--ink2)" stroke-width="1.2" stroke-dasharray="4 3"/>';
  const d = pts.map((p, i) => (i ? 'L' : 'M') + X(i) + ' ' + Y(p.v)).join(' ');
  const last = pts[pts.length - 1].v;
  const col = last >= 0 ? 'var(--up)' : 'var(--down)';
  g += '<path d="' + d + ' L' + X(pts.length - 1) + ' ' + Y(0) + ' L' + X(0) + ' ' + Y(0) +
    ' Z" fill="' + col + '" opacity="0.10"/>' +
    '<path d="' + d + '" fill="none" stroke="' + col + '" stroke-width="1.8"/>';
  const step = Math.max(1, Math.round(pts.length / 8));
  for (let i = 0; i < pts.length; i += step)
    g += '<text x="' + X(i) + '" y="' + (H2 - 8) + '" fill="var(--muted)" font-size="10" text-anchor="middle">' + pts[i].d.slice(2) + '</text>';
  g += '<text x="' + (W2 - R) + '" y="' + (Y(last) - 6) + '" fill="' + col +
    '" font-size="11" text-anchor="end">cumulative ' + fmt(last, dec) + '</text>';
  el.innerHTML = g;
}
$('eqSel').onchange = drawEquity;
drawEquity();

/* ---------- book tables ---------- */
BOOK_HEAD = '<th>signals</th><th>closed</th><th>W / L</th><th>spot win %</th><th>spot mean %</th>' +
  '<th>median %</th><th>PF</th><th>t</th><th>best %</th><th>worst %</th><th>total pts</th>' +
  '<th>priced</th><th>prem mean %</th><th>prem win %</th><th>prem PF</th><th>gross &#8377;</th><th>costs &#8377;</th><th>net &#8377;</th>';
function bookRow(b) {
  const s = b.spot_pct, p = b.prem_pct;
  return '<td>' + b.signals + '</td><td>' + b.closed + '</td><td><span class="pos">' + s.wins +
    '</span> / <span class="neg">' + s.losses + '</span></td>' + plain(s.win_rate, 1, '%') + cell(s.mean, 3, '%') + cell(s.median, 3, '%') +
    plain(s.pf, 2) + cell(s.t, 2) + cell(s.best, 2, '%') + cell(s.worst, 2, '%') +
    cell(b.spot_pts.total, 1) + '<td>' + b.priced + '</td>' + cell(p.mean, 2, '%') +
    plain(p.win_rate, 1, '%') + plain(p.pf, 2) + cell(b.rs, 0) + cell(b.costs === null ? null : -b.costs, 0) + cell(b.rs_net, 0);
}
function bookTable(id, label, rows, keyFmt) {
  $(id).innerHTML = '<thead><tr><th class="l">' + label + '</th>' + BOOK_HEAD + '</tr></thead><tbody>' +
    rows.map(r => '<tr><td class="l">' + (keyFmt ? keyFmt(r.key) : r.key) + '</td>' + bookRow(r) + '</tr>').join('') +
    '</tbody>';
}
bookTable('tblSide', 'side', ['ALL', 'SELL', 'BUY'].map(k => ({key: k, ...V.books[k]})),
  k => k === 'ALL' ? 'all' : pill(k));
bookTable('tblTrig', 'triggers', V.by_trigger);
bookTable('tblMonth', 'month', V.monthly);
bookTable('tblStab', 'slice', V.stability);

/* ---------- entry fill ---------- */
(function () {
  const cc = M.cas_candle, bits = [];
  if (cc.pre) bits.push('before ' + M.cas_date + ' the 15:29 candle moved a median ' + fmt(cc.pre.median, 2) + ' points open to close (max ' + fmt(cc.pre.max, 2) + ', ' + cc.pre.n + ' sessions)');
  if (cc.post) bits.push('from ' + M.cas_date + ' a median ' + fmt(cc.post.median, 2) + ' points (max ' + fmt(cc.post.max, 2) + ', ' + cc.post.n + ' sessions), because that candle now carries the closing-auction print');
  $('fillSub').innerHTML = 'The spot columns use the 15:29 close. ' + bits.join('; ') + '. This table re-fills every night at the 15:29 open instead.';
  $('tblFill').innerHTML = '<thead><tr><th class="l">book</th><th>n</th><th>win %</th><th>mean %</th><th>median %</th><th>PF</th><th>t</th><th>worst %</th></tr></thead><tbody>' +
    V.fills.map(r => '<tr><td class="l">' + r.key + '</td><td>' + r.s.n + '</td>' + plain(r.s.win_rate, 1, '%') +
      cell(r.s.mean, 3, '%') + cell(r.s.median, 3, '%') + plain(r.s.pf, 2) + cell(r.s.t, 2) + cell(r.s.worst, 2, '%') + '</tr>').join('') + '</tbody>';
})();

/* ---------- expiry choice ---------- */
$('tblExpiry').innerHTML = '<thead><tr><th class="l">expiry</th><th class="l">meaning</th><th>priced</th><th>DTE 1</th>' +
  '<th>avg entry prem</th><th>mean %</th><th>median %</th><th>win %</th><th>PF</th><th>t</th><th>worst %</th><th>gross &#8377;</th><th>costs &#8377;</th><th>net &#8377;</th><th>net W / L</th></tr></thead><tbody>' +
  V.expiry.map(r => '<tr' + (r.default ? ' style="font-weight:600"' : '') + '><td class="l">' + r.key + (r.default ? ' &#9664;' : '') + '</td>' +
    '<td class="l dimc">' + r.desc + '</td><td>' + r.n + '</td><td>' + r.dte1 + '</td>' + plain(r.avg_entry_px, 1) +
    cell(r.mean, 2, '%') + cell(r.median, 2, '%') + plain(r.win_rate, 1, '%') + plain(r.pf, 2) + cell(r.t, 2) +
    cell(r.worst, 2, '%') + cell(r.rs, 0) + cell(r.costs === null || r.costs === undefined ? null : -r.costs, 0) + cell(r.rs_net, 0) + '<td><span class="pos">' + r.net_wins + '</span> / <span class="neg">' + r.net_losses + '</span></td></tr>').join('') + '</tbody>';

/* ---------- benchmark ---------- */
(function () {
  const order = ['every session', 'SELL sessions', 'BUY sessions', 'HOLD sessions (base false)', 'HOLD sessions (data)'];
  const rows = order.filter(k => V.benchmark[k]).map(k => [k, V.benchmark[k]]);
  $('tblBench').innerHTML = '<thead><tr><th class="l">sessions</th><th>n</th><th>up %</th>' +
    '<th>mean % (long)</th><th>median %</th><th>t</th><th>best %</th><th>worst %</th></tr></thead><tbody>' +
    rows.map(([k, s]) => '<tr><td class="l">' + k + '</td><td>' + s.n + '</td>' + plain(s.win_rate, 1, '%') +
      cell(s.mean, 3, '%') + cell(s.median, 3, '%') + cell(s.t, 2) + cell(s.best, 2, '%') + cell(s.worst, 2, '%') + '</tr>').join('') +
    '</tbody>';
})();

/* ---------- trades ---------- */
(function () {
  const head = '<tr><th class="l">date</th><th class="l">signal</th><th class="l">triggers</th>' +
    '<th>entry 15:29</th><th class="l">exit</th><th>exit px</th><th>spot pts</th><th>spot %</th>' +
    '<th class="l">contract</th><th>DTE</th><th>entry prem</th><th>exit prem</th><th>prem pts</th>' +
    '<th>prem %</th><th>gross &#8377;</th><th>costs &#8377;</th><th>net &#8377;</th><th>capital</th><th class="l">note</th></tr>';
  $('tblTrades').innerHTML = '<thead>' + head + '</thead><tbody>' + V.trades.map(t =>
    '<tr><td class="l">' + t.day + '</td><td class="l">' + pill(t.decision) + '</td><td class="l">' + t.pattern + '</td>' +
    plain(t.entry_spot, 2) + '<td class="l">' + (t.exit_day ? t.exit_day + ' ' + t.exit_time : '&mdash;') + '</td>' +
    plain(t.exit_spot, 2) + cell(t.spot_pts, 2) + cell(t.spot_pct, 3, '%') +
    '<td class="l">' + (t.symbol || '&mdash;') + '</td><td>' + (t.dte === null ? '&mdash;' : t.dte) + '</td>' +
    plain(t.entry_px, 2) + plain(t.exit_px, 2) + cell(t.prem_pts, 2) + cell(t.prem_pct, 2, '%') + cell(t.pnl_rs, 0) +
    cell(t.costs_rs === null || t.costs_rs === undefined ? null : -t.costs_rs, 0) + cell(t.net_rs, 0) + plain(t.capital_rs, 0) +
    '<td class="l dimc">' + (t.status !== 'closed' ? t.status : (t.price_reason || '')) + '</td></tr>').join('') + '</tbody>';
})();

/* ---------- signal log ---------- */
function renderLog() {
  const onlyFired = $('onlyFired').checked, onlyData = $('onlyData').checked;
  const rows = V.signals.filter(x => (!onlyFired || x.decision !== 'HOLD') && (!onlyData || !x.data_ok));
  const head = '<tr><th class="l">date</th><th class="l">decision</th><th>A</th><th>B</th><th>C</th>' +
    '<th>base</th><th>exh.</th><th>Trend30 %</th><th>SMA10</th><th>close 15:14</th><th>Loc30</th>' +
    '<th>Mom10</th><th>Mom15</th><th>VolRatio10</th><th>RangeRatio20</th><th class="l">hold reason</th></tr>';
  $('tblLog').innerHTML = '<thead>' + head + '</thead><tbody>' + rows.map(x =>
    '<tr><td class="l">' + x.day + '</td><td class="l">' + pill(x.decision) +
    (x.data_ok ? '' : ' <span class="pill data">data</span>') + '</td>' +
    tick(x.trigger_a) + tick(x.trigger_b) + tick(x.trigger_c) + tick(x.base_signal) + tick(x.exhaustion) +
    cell(x.trend30, 2) + plain(x.sma10, 2) + plain(x.close, 2) + plain(x.location30, 3) +
    cell(x.momentum10, 2) + cell(x.momentum15, 2) + plain(x.volatility_ratio10, 3) + plain(x.daily_range_ratio20, 3) +
    '<td class="l dimc">' + (x.hold_reason || '') + '</td></tr>').join('') + '</tbody>';
}
$('onlyFired').onchange = renderLog; $('onlyData').onchange = renderLog;
renderLog();

$('tblHold').innerHTML = '<thead><tr><th class="l">reason</th><th>sessions</th></tr></thead><tbody>' +
  V.hold_reasons.map(r => '<tr><td class="l">' + r[0] + '</td><td>' + r[1] + '</td></tr>').join('') + '</tbody>';

  fillDays();
}

/* ---------- chart ---------- */
const CW = 1200, CH = 520, PADL = 66, PADR = 16, PADT = 18, PADB = 30;
const csvg = $('chart'), ctip = $('tip');
let chartState = null;
const chk = ok => (ok === null || ok === undefined) ? '<span class="dimc">?</span>'
  : (ok ? '<span class="tick">&#10003;</span>' : '<span class="cross">&#10007;</span>');
const num = (v, d) => (v === null || v === undefined) ? 'n/a' : fmt(v, d);
const locLine = sig => (sig && sig.low30 !== null && sig.high30 !== null)
  ? sig.low30 + M.thresholds.loc * (sig.high30 - sig.low30) : null;

function renderChart() {
  const day = $('daySel').value;
  const c1 = DATA.chart_days[day];
  if (!c1) {
    chartState = null;
    banner(DATA.views.all.signals.find(x => x.day === day) || null, DATA.views.all.trades.find(t => t.day === day) || null);
    $('dayTag').textContent = day;
    csvg.innerHTML = txt(CW / 2, CH / 2, 'Candles are carried only from ' + M.chart_full_from + ' on, and for trade days before that. ' + day + ' had no trade.', null, 12, 'middle');
    return;
  }
  const nd = DATA.next_of[day], c2 = nd ? (DATA.chart_days[nd] || []) : [];
  const all = c1.map(x => x.concat([day])).concat(c2.map(x => x.concat([nd])));
  const sig = DATA.views.all.signals.find(x => x.day === day) || null;
  const trade = DATA.views.all.trades.find(t => t.day === day) || null;
  chartState = {day, nd, c: all, split: c1.length, sig, trade, i0: 0, i1: all.length};
  $('dayTag').textContent = day + (nd ? '  →  ' + nd : '  (no next session yet)');
  banner(sig, trade);
  focusZoom();
}

function banner(sig, trade) {
  const b = $('setupBanner');
  if (!sig) { b.className = 'setup dim'; b.textContent = 'This session is outside the signal window.'; return; }
  const T = M.thresholds;
  const A = sig.trigger_a, B = sig.trigger_b, C = sig.trigger_c;
  const lines = [];
  lines.push('<span class="r">Trigger A ' + chk(A) + '</span> Trend30 <b>' + num(sig.trend30, 2) + '%</b> &lt; 0 ' +
    chk(sig.trend30 === null ? null : sig.trend30 < 0) + ' &nbsp;and&nbsp; Momentum15 <b>' + num(sig.momentum15, 2) + '</b> &gt; 0 ' +
    chk(sig.momentum15 === null ? null : sig.momentum15 > 0));
  lines.push('<span class="r">Trigger B ' + chk(B) + '</span> close <b>' + num(sig.close, 2) + '</b> &lt; SMA10 <b>' + num(sig.sma10, 2) + '</b> ' +
    chk(sig.sma10 === null ? null : sig.close < sig.sma10) + ' &nbsp;and&nbsp; VolatilityRatio10 <b>' + num(sig.volatility_ratio10, 3) +
    '</b> &ge; ' + T.vol + ' ' + chk(sig.volatility_ratio10 === null ? null : sig.volatility_ratio10 >= T.vol));
  lines.push('<span class="r">Trigger C ' + chk(C) + '</span> Trend30 &lt; 0 ' + chk(sig.trend30 === null ? null : sig.trend30 < 0) +
    ' &nbsp;and&nbsp; Momentum10 <b>' + num(sig.momentum10, 2) + '</b> &lt; 0 ' + chk(sig.momentum10 === null ? null : sig.momentum10 < 0));
  lines.push('<span class="r">Exhaustion ' + chk(sig.exhaustion) + '</span> Location30 <b>' + num(sig.location30, 3) + '</b> &le; ' + T.loc + ' ' +
    chk(sig.location30 === null ? null : sig.location30 <= T.loc) + ' &nbsp;and&nbsp; DailyRangeRatio20 <b>' + num(sig.daily_range_ratio20, 3) +
    '</b> &ge; ' + T.range + ' ' + chk(sig.daily_range_ratio20 === null ? null : sig.daily_range_ratio20 >= T.range) +
    ' &nbsp;<span class="dimc">(30-session low ' + num(sig.low30, 2) + ', high ' + num(sig.high30, 2) + '; day range ' + num(sig.daily_range_pct, 3) + '% vs 20-day mean ' + num(sig.range_avg20, 3) + '%)</span>');
  let dec = '<span class="r">Decision</span> base ' + chk(sig.base_signal) + ' &rarr; ' + pill(sig.decision);
  if (!sig.data_ok) dec += ' <span class="pill data">data</span> <span class="dimc">' + sig.hold_reason + '</span>';
  else if (sig.decision === 'HOLD') dec += ' <span class="dimc">no base trigger</span>';
  else dec += ' <span class="dimc">base true, exhaustion ' + (sig.exhaustion ? 'true &rarr; long' : 'false &rarr; short') + '</span>';
  lines.push(dec);
  if (trade) {
    let t = '<span class="r">Trade</span> ' + trade.side + ' at 15:29 <b>' + num(trade.entry_spot, 2) + '</b>';
    if (trade.status === 'closed') {
      t += ' &rarr; exit ' + trade.exit_day + ' ' + trade.exit_time + ' <b>' + num(trade.exit_spot, 2) + '</b> = <b class="' + sign(trade.spot_pts) + '">' +
        (trade.spot_pts >= 0 ? '+' : '') + fmt(trade.spot_pts, 2) + ' pts (' + (trade.spot_pct >= 0 ? '+' : '') + fmt(trade.spot_pct, 3) + '%)</b>';
      if (trade.prem_pct !== null && trade.prem_pct !== undefined)
        t += ' &nbsp;&middot;&nbsp; ' + trade.symbol + ' ' + fmt(trade.entry_px, 2) + ' &rarr; ' + fmt(trade.exit_px, 2) + ' = <b class="' + sign(trade.prem_pct) + '">' +
          (trade.prem_pct >= 0 ? '+' : '') + fmt(trade.prem_pct, 1) + '% of premium, &#8377;' + fmt(trade.pnl_rs, 0) + '</b>';
    } else {
      t += ' &nbsp;&middot;&nbsp; ' + trade.status + (trade.symbol ? ' &nbsp;&middot;&nbsp; ' + trade.symbol + ' bought at ' + fmt(trade.entry_px, 2) : '');
    }
    lines.push(t);
  }
  b.className = 'setup ' + (sig.decision === 'BUY' ? 'pos' : (sig.decision === 'SELL' ? 'neg' : 'dim'));
  b.innerHTML = lines.join('<br>');
}

function clampWindow(n, a, b) {
  let i0 = Math.max(0, Math.floor(a)), i1 = Math.min(n, Math.ceil(b));
  if (i1 - i0 < 8) { const m = (i0 + i1) / 2; i0 = Math.max(0, Math.floor(m - 4)); i1 = Math.min(n, i0 + 8); }
  return [i0, i1];
}
function focusZoom() {
  const st = chartState; if (!st) return;
  const a = st.c.findIndex(x => x[5] === st.day && x[0] >= '14:30');
  let b = st.c.findIndex(x => x[5] === st.nd && x[0] > '10:00');
  if (b < 0) b = st.c.length;
  const w = clampWindow(st.c.length, a < 0 ? 0 : a, b);
  st.i0 = w[0]; st.i1 = w[1]; drawChart();
}
function resetZoom() { if (!chartState) return; chartState.i0 = 0; chartState.i1 = chartState.c.length; drawChart(); }
function zoomAt(factor, anchor) {
  const st = chartState; if (!st) return;
  const a = anchor === undefined ? (st.i0 + st.i1) / 2 : anchor;
  const w = clampWindow(st.c.length, a - (a - st.i0) * factor, a + (st.i1 - a) * factor);
  st.i0 = w[0]; st.i1 = w[1]; drawChart();
}
function idxAt(clientX, box) {
  const px = (clientX - box.left) / box.width * CW;
  return chartState.i0 + (px - PADL) / (CW - PADL - PADR) * (chartState.i1 - chartState.i0);
}
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
function txt(x, y, t, col, size, anchor) {
  return '<text x="' + x + '" y="' + y + '" fill="' + (col || 'var(--muted)') + '" font-size="' + (size || 10) +
    '"' + (anchor ? ' text-anchor="' + anchor + '"' : '') + '>' + t + '</text>';
}

function drawChart() {
  const st = chartState; if (!st) return;
  const {c, i0, i1, sig, trade, split, day, nd} = st;
  const view = c.slice(i0, i1); if (!view.length) return;
  const showRules = $('showRules').checked && sig && sig.close !== null;
  const showLv = $('showLevels').checked && sig;
  const showTr = $('showTrade').checked && trade && trade.entry_spot !== null;
  let lo = Math.min(...view.map(x => x[3])), hi = Math.max(...view.map(x => x[2]));
  const span0 = hi - lo || 1;
  const near = v => v !== null && v !== undefined && v > lo - span0 * 0.8 && v < hi + span0 * 0.8;
  if (showLv) for (const v of [sig.sma10, locLine(sig), sig.low30, sig.high30]) if (near(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  if (showTr && trade.exit_spot !== null) { lo = Math.min(lo, trade.entry_spot, trade.exit_spot); hi = Math.max(hi, trade.entry_spot, trade.exit_spot); }
  const pad = (hi - lo) * 0.07 || 1; lo -= pad; hi += pad;
  const n = i1 - i0;
  const X = i => PADL + (i - i0 + 0.5) / n * (CW - PADL - PADR);
  const Y = v => PADT + (hi - v) / (hi - lo) * (CH - PADT - PADB);
  const at = (d, t) => c.findIndex(x => x[5] === d && x[0] === t);
  const half = (CW - PADL - PADR) / n / 2;
  const bw = Math.max(1, half * 1.4);
  let g = '';
  // grid
  for (let k = 0; k <= 5; k++) {
    const v = lo + (hi - lo) * k / 5;
    g += '<line x1="' + PADL + '" y1="' + Y(v) + '" x2="' + (CW - PADR) + '" y2="' + Y(v) + '" stroke="var(--grid)"/>' +
      txt(PADL - 6, Y(v) + 3, fmt(v, 0), null, 10, 'end');
  }
  const step = Math.max(1, Math.round(n / 12));
  for (let i = i0; i < i1; i += step) g += txt(X(i), CH - 10, c[i][0], null, 10, 'middle');
  // session boundary
  if (split > i0 && split < i1) {
    const xs = X(split) - half;
    g += '<line x1="' + xs + '" y1="' + PADT + '" x2="' + xs + '" y2="' + (CH - PADB) + '" stroke="var(--ink2)" stroke-width="1.2" stroke-dasharray="6 4"/>' +
      txt(xs - 6, PADT + 10, day, 'var(--ink2)', 11, 'end') + txt(xs + 6, PADT + 10, nd + ' (next session)', 'var(--ink2)', 11);
  } else if (i0 < split) g += txt(PADL + 6, PADT + 10, day, 'var(--ink2)', 11);
  else g += txt(PADL + 6, PADT + 10, nd + ' (next session)', 'var(--ink2)', 11);
  // rule windows on the signal day
  if (showRules) {
    const iv0 = at(day, '15:05'), iv1 = at(day, '15:14'), icut = at(day, '15:15'), iend = at(day, '15:29'), i1500 = at(day, '15:00');
    const vis = i => i >= i0 && i < i1;
    if (iv0 >= 0 && iv1 >= 0 && (vis(iv0) || vis(iv1))) {
      const x0 = Math.max(PADL, X(iv0) - half), x1 = Math.min(CW - PADR, X(iv1) + half);
      g += '<rect x="' + x0 + '" y="' + PADT + '" width="' + Math.max(0, x1 - x0) + '" height="' + (CH - PADT - PADB) + '" fill="var(--accent)" opacity="0.10"/>' +
        txt((x0 + x1) / 2, CH - PADB - 6, 'VolatilityRatio10 window 15:05–15:14 = ' + num(sig.volatility_ratio10, 3) + '×', 'var(--accent)', 10, 'middle');
    }
    if (icut >= 0 && iend >= 0 && (vis(icut) || vis(iend))) {
      const x0 = Math.max(PADL, X(icut) - half), x1 = Math.min(CW - PADR, X(iend) + half);
      g += '<rect x="' + x0 + '" y="' + PADT + '" width="' + Math.max(0, x1 - x0) + '" height="' + (CH - PADT - PADB) + '" fill="var(--muted)" opacity="0.10"/>' +
        txt((x0 + x1) / 2, CH - PADB - 18, 'not read (15:15+)', null, 10, 'middle');
    }
    if (iv1 >= 0 && vis(iv1)) {
      const x = X(iv1) + half;
      g += '<line x1="' + x + '" y1="' + PADT + '" x2="' + x + '" y2="' + (CH - PADB) + '" stroke="var(--warn)" stroke-width="1.4"/>' +
        txt(x - 4, PADT + 24, 'decision at 15:14 close ' + fmt(sig.close, 2), 'var(--warn)', 10.5, 'end');
    }
    // momentum lines: 15:00 open -> 15:14 close, 15:05 open -> 15:14 close
    if (i1500 >= 0 && iv1 >= 0 && vis(i1500)) {
      const yc = Y(sig.close), xo = X(i1500), xc = X(iv1);
      g += '<line x1="' + xo + '" y1="' + Y(c[i1500][1]) + '" x2="' + xc + '" y2="' + yc + '" stroke="var(--warn)" stroke-width="1.6" stroke-dasharray="3 3"/>' +
        txt(xo, Y(c[i1500][1]) - 8, 'Momentum15 ' + (sig.momentum15 >= 0 ? '+' : '') + fmt(sig.momentum15, 2) + ' (15:00 open ' + fmt(c[i1500][1], 2) + ')', 'var(--warn)', 10, 'middle');
    }
    if (iv0 >= 0 && iv1 >= 0 && vis(iv0)) {
      const yc = Y(sig.close), xo = X(iv0), xc = X(iv1);
      g += '<line x1="' + xo + '" y1="' + Y(c[iv0][1]) + '" x2="' + xc + '" y2="' + yc + '" stroke="var(--zone)" stroke-width="1.6" stroke-dasharray="3 3"/>' +
        txt(xo, Y(c[iv0][1]) + 14, 'Momentum10 ' + (sig.momentum10 >= 0 ? '+' : '') + fmt(sig.momentum10, 2) + ' (15:05 open ' + fmt(c[iv0][1], 2) + ')', 'var(--zone)', 10, 'middle');
    }
    // day range of the signal day (09:15..15:14)
    if (sig.day_high !== null && i0 < split) {
      const x0 = PADL, x1 = X(Math.min(split, i1) - 1) + half;
      for (const [v, lab] of [[sig.day_high, 'day high'], [sig.day_low, 'day low']]) if (v >= lo && v <= hi)
        g += '<line x1="' + x0 + '" y1="' + Y(v) + '" x2="' + x1 + '" y2="' + Y(v) + '" stroke="var(--ink2)" stroke-width="0.8" stroke-dasharray="2 4"/>' +
          txt(x0 + 4, Y(v) + (lab === 'day high' ? -4 : 12), lab + ' ' + fmt(v, 2) + '  ·  range ' + num(sig.daily_range_pct, 2) + '% = ' + num(sig.daily_range_ratio20, 2) + '× 20-day', 'var(--ink2)', 10);
    }
  }
  // candles
  for (let i = i0; i < i1; i++) {
    const k = c[i], up = k[4] >= k[1], col = up ? 'var(--up)' : 'var(--down)', x = X(i);
    const y1 = Y(Math.max(k[1], k[4])), y2 = Y(Math.min(k[1], k[4]));
    g += '<line x1="' + x + '" y1="' + Y(k[2]) + '" x2="' + x + '" y2="' + Y(k[3]) + '" stroke="' + col + '" stroke-width="1"/>' +
      '<rect x="' + (x - bw / 2) + '" y="' + y1 + '" width="' + bw + '" height="' + Math.max(1, y2 - y1) + '" fill="' + col + '"/>';
  }
  // levels
  if (showLv) {
    const lv = [[sig.sma10, 'SMA10 ' + num(sig.sma10, 2) + (sig.close !== null ? (sig.close < sig.sma10 ? '  ·  close below (B needs VolRatio ≥ ' + M.thresholds.vol + ')' : '  ·  close above, B off') : ''), 'var(--accent)', '6 3'],
                [locLine(sig), 'Location30 ' + M.thresholds.loc + ' line ' + num(locLine(sig), 2) + '  ·  Location30 = ' + num(sig.location30, 3), 'var(--zone)', '2 3'],
                [sig.low30, '30-session low ' + num(sig.low30, 2), 'var(--zone)', ''],
                [sig.high30, '30-session high ' + num(sig.high30, 2), 'var(--zone)', '']];
    let off = 0;
    for (const [v, lab, col, dash] of lv) {
      if (v === null || v === undefined) continue;
      if (v >= lo && v <= hi) {
        g += '<line x1="' + PADL + '" y1="' + Y(v) + '" x2="' + (CW - PADR) + '" y2="' + Y(v) + '" stroke="' + col + '" stroke-width="1.2"' + (dash ? ' stroke-dasharray="' + dash + '"' : '') + '/>' +
          txt(CW - PADR - 4, Y(v) - 4, lab, col, 10, 'end');
      } else {
        g += txt(CW - PADR - 4, PADT + 24 + 13 * off, lab + (v > hi ? '  ↑ above the chart' : '  ↓ below the chart'), col, 10, 'end');
        off++;
      }
    }
  }
  // trade
  if (showTr) {
    const ie = at(day, '15:29');
    const col = trade.status === 'closed' ? (trade.spot_pts >= 0 ? 'var(--up)' : 'var(--down)') : 'var(--accent)';
    if (ie >= 0 && ie >= i0 && ie < i1) {
      g += '<circle cx="' + X(ie) + '" cy="' + Y(trade.entry_spot) + '" r="4.5" fill="' + col + '" stroke="var(--surface)" stroke-width="1.5"/>' +
        txt(X(ie) - 8, Y(trade.entry_spot) + 4, trade.decision + ' entry 15:29 ' + fmt(trade.entry_spot, 2), col, 11, 'end');
    }
    if (trade.status === 'closed') {
      const ix = at(nd, trade.exit_time);
      if (ix >= 0 && ie >= 0 && (ix >= i0 && ix < i1 || ie >= i0 && ie < i1)) {
        g += '<line x1="' + X(ie) + '" y1="' + Y(trade.entry_spot) + '" x2="' + X(ix) + '" y2="' + Y(trade.exit_spot) + '" stroke="' + col + '" stroke-width="1.8" stroke-dasharray="5 3"/>' +
          '<circle cx="' + X(ix) + '" cy="' + Y(trade.exit_spot) + '" r="4.5" fill="' + col + '" stroke="var(--surface)" stroke-width="1.5"/>' +
          txt(X(ix) + 8, Y(trade.exit_spot) + 4, 'exit ' + trade.exit_time + ' ' + fmt(trade.exit_spot, 2) + '  =  ' + (trade.spot_pts >= 0 ? '+' : '') + fmt(trade.spot_pts, 2) + ' pts (' + (trade.spot_pct >= 0 ? '+' : '') + fmt(trade.spot_pct, 3) + '%)', col, 11);
      }
    } else if (ie >= 0 && ie >= i0 && ie < i1) {
      g += txt(X(ie) + 8, Y(trade.entry_spot) + 4, 'open · ' + esc(trade.status), col, 11);
    }
  }
  csvg.innerHTML = g;
}

csvg.addEventListener('wheel', e => {
  if (!chartState) return; e.preventDefault();
  zoomAt(e.deltaY < 0 ? 0.82 : 1.22, idxAt(e.clientX, csvg.getBoundingClientRect()));
}, {passive: false});
let drag = null;
csvg.addEventListener('pointerdown', e => {
  if (!chartState) return;
  drag = {x: e.clientX, i0: chartState.i0, i1: chartState.i1}; csvg.classList.add('drag');
  try { csvg.setPointerCapture(e.pointerId); } catch (_) {}
});
csvg.addEventListener('pointerup', e => { drag = null; csvg.classList.remove('drag'); try { csvg.releasePointerCapture(e.pointerId); } catch (_) {} });
csvg.addEventListener('dblclick', resetZoom);
csvg.addEventListener('pointermove', e => {
  if (!chartState) return;
  const box = csvg.getBoundingClientRect();
  if (drag) {
    const dx = (e.clientX - drag.x) / box.width * CW;
    const perPx = (drag.i1 - drag.i0) / (CW - PADL - PADR);
    const w = clampWindow(chartState.c.length, drag.i0 - dx * perPx, drag.i1 - dx * perPx);
    chartState.i0 = w[0]; chartState.i1 = w[1]; drawChart(); ctip.style.display = 'none'; return;
  }
  const i = Math.round(idxAt(e.clientX, box) - 0.5), c = chartState.c;
  if (i < 0 || i >= c.length) { ctip.style.display = 'none'; return; }
  ctip.innerHTML = '<b>' + c[i][0] + '</b> <span style="opacity:.65">' + c[i][5] + '</span><br>O ' + c[i][1].toFixed(2) +
    '<br>H ' + c[i][2].toFixed(2) + '<br>L ' + c[i][3].toFixed(2) + '<br>C ' + c[i][4].toFixed(2);
  ctip.style.display = 'block';
  ctip.style.left = Math.min(e.clientX + 14, window.innerWidth - 120) + 'px';
  ctip.style.top = Math.max(4, e.clientY - 60) + 'px';
});
csvg.addEventListener('pointerleave', () => { ctip.style.display = 'none'; });
$('daySel').onchange = renderChart;
$('showRules').onchange = drawChart; $('showLevels').onchange = drawChart; $('showTrade').onchange = drawChart;
$('zoomFocus').onclick = focusZoom; $('zoomIn').onclick = () => zoomAt(0.7); $('zoomOut').onclick = () => zoomAt(1.4); $('zoomReset').onclick = resetZoom;

function fillDays() {
  const sel = $('daySel'), keep = sel.value;
  const days = V.signals.map(x => x.day);
  sel.innerHTML = V.signals.map(x => '<option value="' + x.day + '">' + x.day + ' · ' + x.decision + '</option>').join('');
  if (days.includes(keep)) sel.value = keep;
  else { const tr = V.trades.filter(t => t.status === 'closed'); sel.value = tr.length ? tr[tr.length - 1].day : days[days.length - 1]; }
  renderChart();
}

renderAll();

/* ---------- notes ---------- */
$('rule').innerHTML = [
  ['Daily bar', '360 one-minute candles 09:15..15:14; open = 09:15 open, close = 15:14 close'],
  ['Trend30', '% from the oldest close to the newest close of the latest 30 daily bars; <b>&lt; 0</b> is the down-trend condition'],
  ['SMA10', 'mean close of the latest 10 daily bars, current included'],
  ['Location30', '(close &minus; low30) / (high30 &minus; low30); 0 = the 30-session low, 1 = the high'],
  ['Momentum15', '15:14 close &minus; 15:00 open, points'],
  ['Momentum10', '15:14 close &minus; 15:05 open, points'],
  ['VolatilityRatio10', 'sample std-dev of the 9 close-to-close % changes 15:05..15:14, over the mean of the previous 20 sessions (current excluded)'],
  ['DailyRangeRatio20', '(high &minus; low) / close of the 09:15..15:14 window, over the mean of the latest 20 sessions (current included)'],
  ['Trigger A', 'Trend30 &lt; 0 <b>and</b> Momentum15 &gt; 0'],
  ['Trigger B', 'close &lt; SMA10 <b>and</b> VolatilityRatio10 &ge; ' + M.thresholds.vol],
  ['Trigger C', 'Trend30 &lt; 0 <b>and</b> Momentum10 &lt; 0'],
  ['Exhaustion', 'Location30 &le; ' + M.thresholds.loc + ' <b>and</b> DailyRangeRatio20 &ge; ' + M.thresholds.range],
  ['Decision', 'no base trigger &rarr; <b>HOLD</b>; base and exhaustion &rarr; <b>BUY</b>; base without exhaustion &rarr; <b>SELL</b>; any missing, duplicated, incomplete or invalid candle or feature &rarr; <b>HOLD</b>'],
].map(r => '<div class="k">' + r[0] + '</div><div>' + r[1] + '</div>').join('');

$('fills').innerHTML =
  '<b>Fills and conventions.</b> The direction is frozen at 15:14 and nothing starting at or after 15:15 is read. ' +
  'Spot entry is the <b>15:29 candle close</b> (its open is in the CSV as <code>entry_open_1529</code>); ' +
  'spot exit is the <b>close of the next session&rsquo;s first one-minute candle</b>, 09:15 on a regular day, ' +
  'the first print on a special session. Both BUY and SELL are priced as <b>bought</b> ATM options ' +
  '(CE for BUY, PE for SELL) from the contract&rsquo;s own one-minute closes at the same two minutes; ' +
  'the headline contract is <code>' + M.expiry_mode + '</code> (see the expiry table) and &#8377; is one lot of ' + M.lot_size + '. ' +
  '<b>Fills follow the worst-fill rule (2026-09-19):</b> the option is bought at the <b>high</b> of the 15:29 minute and sold at the <b>low</b> of the exit minute, so no backtest fill is better than a real one could have been; the same night filled at the minutes&rsquo; closes is kept beside it (<code>net_rs_close</code>, and the card &ldquo;net if filled at closes&rdquo;). ' +
  '<b>Capital</b> per lot is the premium paid. <b>Brokerage and taxes</b> are charged on every round trip as two orders: &#8377;20 per order, STT 0.1% of the sell-side premium, exchange charge 0.03503% of premium turnover, SEBI fee &#8377;10 per crore, stamp duty 0.003% of the buy-side premium, GST 18% on brokerage, exchange and SEBI charges (rates from 2024-10-01, in <code>services/trade_costs.py</code>); net columns are after these. ' +
  'The range denominator is the 15:14 close. Official daily closes are logged for reference and used by no rule. ' +
  'Derived 09:15 opens matched the daily feed on ' + M.open_match + ' of ' + M.open_checked + ' sessions checked.';

$('limits').innerHTML =
  '<b>What limits these numbers.</b> ' + M.sessions + ' sessions is ' + M.months + ' months; ' +
  'at this trade count a nightly edge of a few basis points cannot be told from zero, and no half of this window ' +
  'is out of sample. The thresholds are the user&rsquo;s, untouched. ' +
  'From 2026-08-03 the closing auction has flattened the last 30 minutes, so Momentum15 / Momentum10 are read ' +
  'as signs on very small moves. The option archive starts 2024-10, so a wider run prices fewer nights. ' +
  (M.partial === 'strict'
    ? 'Partial sessions poison the windows that contain them (the spec, read literally); the default window has none.'
    : 'Partial sessions are dropped from the daily series (<code>--partial-sessions skip</code>).');
</script>
</body>
</html>
"""


def write_report(payload: dict, out_path: str) -> None:
    html = HTML_TEMPLATE.replace("__DATA_JSON__",
                                 json.dumps(payload, separators=(",", ":")))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  report  -> {out_path} ({len(html) / 1e6:.1f} MB)")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def build_view(label: str, from_iso: str, to_iso: str, signals: list[dict],
               trades: list[dict], series, sessions, all_days, expiry_mode: str) -> dict:
    """Every table of the report for one window of sessions."""
    counts = Counter(x["decision"] for x in signals)
    hold_data = sum(1 for x in signals if x["decision"] == "HOLD" and not x["data_ok"])
    books = {"ALL": book(trades),
             "BUY": book([t for t in trades if t["decision"] == "BUY"]),
             "SELL": book([t for t in trades if t["decision"] == "SELL"])}
    closed_trades = [t for t in trades if t["status"] == "closed"]
    half = len(closed_trades) // 2
    halves = [{"key": f"first half ({closed_trades[0]['day']} ...)",
               **book(closed_trades[:half])},
              {"key": f"second half (... {closed_trades[-1]['day']})",
               **book(closed_trades[half:])}] if len(closed_trades) >= 4 else []
    cas = grouped(trades, lambda t: (f"before {CAS_DATE} (continuous close)"
                                     if t["day"] < CAS_DATE else
                                     f"from {CAS_DATE} (closing auction)"))
    yearly = grouped(trades, lambda t: t["day"][:4])
    hold_reasons = Counter(x["hold_reason"] for x in signals if x["decision"] == "HOLD")
    fills = []
    for side in ("ALL", "SELL", "BUY"):
        fills.append({"key": f"{side} - entry 15:29 close (used)", "s": books[side]["spot_pct"]})
        fills.append({"key": f"{side} - entry 15:29 open", "s": books[side]["spot_pct_open"]})
    expiry_rows = [{"key": m, "desc": desc, "default": m == expiry_mode,
                    **books["ALL"]["legs"][m]} for m, desc in EXPIRY_MODES]
    view = {"label": label, "from": from_iso, "to": to_iso, "sessions": len(signals),
            "counts": {"BUY": counts.get("BUY", 0), "SELL": counts.get("SELL", 0),
                       "HOLD": counts.get("HOLD", 0), "HOLD_data": hold_data},
            "expiry_mode": expiry_mode, "books": books,
            "by_trigger": grouped(trades, lambda t: t["pattern"]),
            "monthly": grouped(trades, lambda t: t["day"][:7]),
            "stability": halves + (cas if len(cas) > 1 else []) + yearly,
            "fills": fills, "expiry": expiry_rows,
            "benchmark": benchmark(series, sessions, all_days, signals, from_iso),
            "signals": signals, "trades": trades,
            "hold_reasons": sorted(hold_reasons.items(), key=lambda kv: -kv[1])}
    view["verdict"] = verdict_text(books, view, cas)
    return view


async def run(args) -> None:
    load_from = args.from_date - timedelta(days=WARMUP_DAYS)
    candles = await load_nifty(args.offline, load_from, args.to_date)
    rows, bad_ts = to_rows(candles)
    if bad_ts:
        print(f"  ! {bad_ts} candle(s) with an unreadable timestamp dropped")
    sessions, all_days = build_sessions(rows)
    series = daily_series(sessions, all_days, args.partial)
    print(f"  {len(all_days)} sessions loaded ({len(series)} with a daily bar), "
          f"{sum(1 for s in series if not s['valid'])} of them partial")

    from_iso, to_iso = args.from_date.isoformat(), args.to_date.isoformat()
    signals = [compute_signal(series, i) for i, s in enumerate(series)
               if from_iso <= s["day"] <= to_iso]
    if not signals:
        raise RuntimeError(f"no session inside {from_iso} -> {to_iso}")

    official = load_daily_ohlc(args.from_date, args.to_date)
    checked = [x for x in signals if x["day_open"] is not None and x["day"] in official]
    open_match = sum(1 for x in checked
                     if abs(x["day_open"] - official[x["day"]]["o"]) < 0.005)
    if checked:
        print(f"  derived 09:15 open matches the daily feed on {open_match}/{len(checked)} sessions")

    trades = build_trades(signals, sessions, all_days)
    priced, closed = await price_trades(
        trades, args.offline, None if args.offline else _read_access_token(), args.expiry)
    print(f"  {len(trades)} signals, {closed} closed nights, {priced} priced ({args.expiry})")

    # |close - open| of the 15:29 candle, before and from the closing auction:
    # the size of the fill question the entry-fill table answers.
    gaps: dict[str, list[float]] = defaultdict(list)
    for x in signals:
        s = sessions[x["day"]]
        if s["entry"]:
            gaps["post" if x["day"] >= CAS_DATE else "pre"].append(
                abs(s["entry"]["c"] - s["entry"]["o"]))
    cas_candle = {k: {"n": len(v), "median": statistics.median(v), "max": max(v)}
                  for k, v in gaps.items()}
    months = (args.to_date - args.from_date).days / 30.44
    meta = {"from": from_iso, "to": to_iso, "generated": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
            "sessions": len(signals), "months": f"{months:.1f}",
            "partial": args.partial, "expiry_mode": args.expiry, "lot_size": LOT_SIZE,
            "thresholds": {"vol": VOL_RATIO_THRESHOLD, "loc": LOCATION_THRESHOLD,
                           "range": RANGE_RATIO_THRESHOLD},
            "open_checked": len(checked), "open_match": open_match,
            "cas_date": CAS_DATE, "cas_candle": cas_candle, "wide": WIDE_RUN}
    # THE RULE IS BUILT FOR THE POST-AUCTION MARKET (user, 2026-09-18), so the
    # report opens on the window from CAS_DATE and keeps the full run beside it.
    # Every table is computed per window from the same signal and trade lists.
    views = {}
    six = (args.to_date - timedelta(days=183)).isoformat()
    first_day = series[0]["day"] if series else from_iso
    windows = [("cas", f"from {CAS_DATE} (closing auction)", max(from_iso, CAS_DATE)),
               ("6m", f"last 6 months (from {six})", six),
               ("all", (f"priced history {max(from_iso, first_day)} -> {to_iso}"
                        if from_iso >= PRICED_START.isoformat() else
                        f"all data {max(from_iso, first_day)} -> {to_iso}"), from_iso)]
    for key, label, lo in windows:
        if key == "6m" and six <= from_iso:
            continue                     # the run IS the 6-month window
        views[key] = build_view(label, lo, to_iso,
                                [x for x in signals if x["day"] >= lo],
                                [t for t in trades if t["day"] >= lo],
                                series, sessions, all_days, args.expiry)
    # The chart: every in-window session's 09:15..15:29 candles, and which
    # session follows which, so the exit can be drawn on the next day.
    chart_rows: dict[str, list] = defaultdict(list)
    chart_full_from = (args.to_date - timedelta(days=CHART_FULL_DAYS)).isoformat()
    trade_days = ({t["day"] for t in trades}
                  | {t["exit_day"] for t in trades if t["exit_day"]})
    for r in rows:
        d = r["day"]
        if d < from_iso or not r["ok"] or not (SESSION_START <= r["t"] <= ENTRY_HHMM):
            continue
        if d < chart_full_from and (d not in trade_days
                                    or not (r["t"] >= "14:30" or r["t"] <= "10:00")):
            continue
        chart_rows[d].append([r["t"], round(r["o"], 2), round(r["h"], 2),
                              round(r["l"], 2), round(r["c"], 2)])
    chart_days = {d: sorted(v) for d, v in chart_rows.items()}
    meta["chart_full_from"] = chart_full_from
    next_of = {d: all_days[k + 1] for k, d in enumerate(all_days) if k + 1 < len(all_days)}
    payload = {"meta": meta, "views": views, "chart_days": chart_days, "next_of": next_of,
               "default_view": "cas" if views["cas"]["sessions"] else "all"}
    payload["verdict"] = views[payload["default_view"]]["verdict"]

    print(f"\n  {payload['verdict']}\n")
    write_signals_csv(signals, official, args.signals_csv)
    write_trades_csv(trades, args.expiry, args.trades_csv)
    write_report(payload, args.out)


def main() -> None:
    today = date.today()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--partial-sessions", dest="partial", default="strict",
                    choices=[k for k, _ in PARTIAL_MODES],
                    help="; ".join(f"{k}: {v}" for k, v in PARTIAL_MODES))
    ap.add_argument("--expiry", default=DEFAULT_EXPIRY,
                    choices=[k for k, _ in EXPIRY_MODES],
                    help="which contract fills the headline premium columns (all "
                         "three are always priced and tabulated): "
                         + "; ".join(f"{k}: {v}" for k, v in EXPIRY_MODES))
    ap.add_argument("--offline", action="store_true", help="use local caches only")
    ap.add_argument("--out", default=REPORT_HTML)
    ap.add_argument("--signals-csv", default=SIGNALS_CSV)
    ap.add_argument("--trades-csv", default=TRADES_CSV)
    # The default window is 6 months, per the house rule of 2026-09-18.  The
    # 75-day warm-up before it is loaded automatically so the first session
    # already has its 30 daily bars; it is not reported.
    ap.add_argument("--from", dest="from_date", type=date.fromisoformat,
                    default=today - timedelta(days=183),
                    help="first SIGNAL day (default 6 months back); the warm-up "
                         "before it is loaded automatically")
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat, default=today)
    ap.add_argument("--full-history", action="store_true",
                    help=f"run from the start of the broker's option archive ({PRICED_START}), "
                         "the whole period a real premium P&L exists for; the report then "
                         "carries three windows: post-CAS, last 6 months, priced history")
    args = ap.parse_args()
    if args.full_history:
        args.from_date = PRICED_START
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
