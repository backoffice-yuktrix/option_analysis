"""signals_trend.py - the six "trend" candidates of library.json, coded to the letter.

    orb15_close_break, pdhl_break_5m, first_hour_close_location,
    afternoon_new_extreme, ema20_pullback_5m, avgprice_cross_hold

Every function has the shape  fn(ctx: DayCtx, **params) -> None | (t, direction)
  t         = "HH:MM" stamp of the signal minute (the LAST 1-minute bar of the signal candle; fill bar is t+1)
  direction = "UP" (buy CE) or "DOWN" (buy PE)

Rules that come from protocol.md and override the library text:
  * P1.3 - signal minutes are 09:19 .. 14:13 (wherever the library says 14:29, read 14:13).
  * P1.4 - the rule is evaluated only on candles whose fill bar lies in 09:20..14:14; the day's signal is the
           FIRST such candle on which the rule is true.
  * P1.6 - no weekday, days-to-expiry or expiry calendar is used here; nothing is computed over the window as a whole.

Each function scans forward through ctx.bars and only ever reads bars stamped at or before the minute it is
evaluating, so the result is the same on a ctx truncated at the signal minute (ctx.check_no_lookahead).
No row is mutated.  Only index 1-minute candles are used (today's, and earlier sessions where the text says so).
"""
from __future__ import annotations

OPEN = 9 * 60 + 15            # 09:15, the first 1-minute candle of a session
FIRST_SIGNAL = 9 * 60 + 19    # protocol P1.3: "signal minutes are 09:19 .. 14:13"
LAST_SIGNAL = 14 * 60 + 13


# ---------------------------------------------------------------------------
# small helpers (private to this module)
# ---------------------------------------------------------------------------
def _mins(stamp: str) -> int:
    """ "09:15" -> 555 """
    return int(stamp[:2]) * 60 + int(stamp[3:5])


def _stamp(m: int) -> str:
    """ 555 -> "09:15" """
    return f"{m // 60:02d}:{m % 60:02d}"


def _candles(bars: list, n: int) -> list:
    """N-minute candles built from 1-minute bars, aligned to 09:15.
    Returns [[start_minute, open, high, low, close, last_minute_seen], ...] in time order, one per bucket that
    has at least one bar.  A candle is COMPLETE when last_minute_seen == start_minute + n - 1 (its last
    1-minute bar is present); the caller decides what to do with an incomplete one."""
    out: list = []
    for b in bars:
        m = _mins(b[0])
        if m < OPEN:
            continue
        start = OPEN + ((m - OPEN) // n) * n
        if out and out[-1][0] == start:
            c = out[-1]
            if b[2] > c[2]:
                c[2] = b[2]
            if b[3] < c[3]:
                c[3] = b[3]
            c[4] = b[4]
            c[5] = m
        else:
            out.append([start, b[1], b[2], b[3], b[4], m])     # a NEW list - the 1-minute row is not touched
    return out


# ---------------------------------------------------------------------------
# 1. orb15_close_break
# ---------------------------------------------------------------------------
def orb15_close_break(ctx, opening_range_minutes=15):
    n = int(opening_range_minutes)
    range_end = OPEN + n            # first minute AFTER the opening range (09:30 for N = 15)
    orh = orl = None
    seen = 0
    for b in ctx.bars:
        m = _mins(b[0])
        if m < OPEN:
            continue
        if m < range_end:
            # "ORH / ORL = highest high / lowest low of the first N 1-minute candles
            #  (N = 15: candles stamped 09:15..09:29)."
            orh = b[2] if orh is None or b[2] > orh else orh
            orl = b[3] if orl is None or b[3] < orl else orl
            seen += 1
            continue
        if seen != n:               # the opening range is not whole: the day cannot be evaluated
            return None
        if m > LAST_SIGNAL:
            return None
        if m < FIRST_SIGNAL:
            continue
        # "SIGNAL = the FIRST completed 1-minute candle stamped t, with 09:15+N <= t <= 14:29 [read 14:13],
        #  whose close > ORH (UP) or whose close < ORL (DOWN)."
        if b[4] > orh:
            return (b[0], "UP")
        if b[4] < orl:
            return (b[0], "DOWN")
    return None


# ---------------------------------------------------------------------------
# 2. pdhl_break_5m
# ---------------------------------------------------------------------------
def pdhl_break_5m(ctx, confirmation_candle_minutes=5):
    size = int(confirmation_candle_minutes)
    if not ctx.prev_sessions:
        return None
    # "PDH / PDL = highest high / lowest low of the previous session's index 1-minute candles (09:15..15:29)."
    # notes: "'Previous session' is the most recent earlier date in the index candle file."
    prev = [b for b in ctx.session(ctx.prev_sessions[-1]) if "09:15" <= b[0] <= "15:29"]
    if not prev:
        return None
    pdh = max(b[2] for b in prev)
    pdl = min(b[3] for b in prev)
    # "Build today's B-minute candles from 1-minute candles, aligned to 09:15 (B = 5: 09:15-09:19, ...)."
    for start, _o, _h, _l, close, last in _candles(ctx.bars, size):
        m = start + size - 1        # the candle's last 1-minute bar = its signal minute
        if last != m:               # not complete (its last 1-minute bar is not there): not examined
            continue
        # "Only candles whose last 1-minute bar m satisfies 09:19 <= m <= 14:29 [read 14:13] are examined."
        if m < FIRST_SIGNAL:
            continue
        if m > LAST_SIGNAL:
            return None
        # "SIGNAL = the FIRST such candle whose close > PDH (UP) or whose close < PDL (DOWN)"
        if close > pdh:
            return (_stamp(m), "UP")
        if close < pdl:
            return (_stamp(m), "DOWN")
    return None


# ---------------------------------------------------------------------------
# 3. first_hour_close_location
# ---------------------------------------------------------------------------
def first_hour_close_location(ctx, window_minutes=60, outer_fraction_of_range=0.25):
    w = int(window_minutes)
    f = float(outer_fraction_of_range)
    decision = OPEN + w - 1         # "the window's last candle" (10:14 for W = 60)
    if not FIRST_SIGNAL <= decision <= LAST_SIGNAL:
        return None
    # "Window = the first W 1-minute candles (W = 60: stamped 09:15..10:14)."
    window = [b for b in ctx.bars if OPEN <= _mins(b[0]) <= decision]
    if len(window) != w or _mins(window[-1][0]) != decision:
        return None                 # the window is not whole (or the day is cut before the decision minute)
    # "H1 = highest high, L1 = lowest low, C1 = close of the window's last candle (10:14)."
    h1 = max(b[2] for b in window)
    l1 = min(b[3] for b in window)
    c1 = window[-1][4]
    # "If H1 = L1, no trade."
    if h1 == l1:
        return None
    # "p = (C1 - L1) / (H1 - L1). ... p >= 1 - F is UP, p <= F is DOWN, with F = 0.25; otherwise no trade."
    p = (c1 - l1) / (h1 - l1)
    if p >= 1 - f:
        return (window[-1][0], "UP")
    if p <= f:
        return (window[-1][0], "DOWN")
    return None


# ---------------------------------------------------------------------------
# 4. afternoon_new_extreme
# ---------------------------------------------------------------------------
def afternoon_new_extreme(ctx, scan_start_time="12:00"):
    start = _mins(scan_start_time)
    sh = sl = None                  # session high / low of all candles stamped 09:15..t-1
    for b in ctx.bars:
        m = _mins(b[0])
        if m < OPEN:
            continue
        if m > LAST_SIGNAL:
            return None
        # "For each completed candle stamped t from S = 12:00 to 14:29 [read 14:13]: SH = highest high of all
        #  candles stamped 09:15..t-1, SL = lowest low of the same candles. SIGNAL = the FIRST such candle whose
        #  close > SH (UP) or whose close < SL (DOWN)."
        if m >= start and m >= FIRST_SIGNAL and sh is not None:
            if b[4] > sh:
                return (b[0], "UP")
            if b[4] < sl:
                return (b[0], "DOWN")
        sh = b[2] if sh is None or b[2] > sh else sh
        sl = b[3] if sl is None or b[3] < sl else sl
    return None


# ---------------------------------------------------------------------------
# 5. ema20_pullback_5m
# ---------------------------------------------------------------------------
_EMA_CANDLE = 5                     # "5-minute index candles, each session aligned to 09:15"
_EMA_BEFORE: dict = {}              # (index, day, period) -> EMA after the last candle of the previous session
#                                     (depends on EARLIER sessions only, so it is the same for any cutoff of today)


def _ema_before_today(ctx, period: int):
    """E after the last 5-minute candle of the session before ctx.day, over the continuous series that starts
    with the first session on disk (2025-11-24).  None if there is no earlier session."""
    key = (ctx.index, ctx.day, period)
    if key in _EMA_BEFORE:
        return _EMA_BEFORE[key]
    alpha = 2.0 / (period + 1)      # "alpha = 2/(P+1)"
    e = None
    for d in ctx.prev_sessions:     # "kept as one continuous series from 2025-11-24"
        for c in _candles(ctx.session(d), _EMA_CANDLE):
            # "seeded with the first close of the series"
            e = c[4] if e is None else alpha * c[4] + (1.0 - alpha) * e
    _EMA_BEFORE[key] = e
    return e


def ema20_pullback_5m(ctx, ema_period=20, clean_run_candles=6):
    period = int(ema_period)
    q = int(clean_run_candles)
    alpha = 2.0 / (period + 1)
    e = _ema_before_today(ctx, period)
    today = []                      # today's complete candles as (low, high, close, E including that candle)
    for start, _o, high, low, close, last in _candles(ctx.bars, _EMA_CANDLE):
        m = start + _EMA_CANDLE - 1
        if last != m:               # the candle's last 1-minute bar is not there yet: stop, nothing later is usable
            return None
        if m > LAST_SIGNAL:         # "with its last 1-minute bar m <= 14:29" [read 14:13]
            return None
        # "E(k) = exponential moving average of 5-minute closes ... value including candle k"
        e = close if e is None else alpha * close + (1.0 - alpha) * e
        today.append((low, high, close, e))
        k = len(today) - 1
        # "(a) each of the Q = 6 candles immediately before it (k-Q..k-1) belongs to TODAY"
        if k < q or m < FIRST_SIGNAL:
            continue
        run = today[k - q:k]
        # UP: "(a) ... and has low(j) > E(j); (b) low(k) <= E(k); (c) close(k) > E(k)."
        if all(lo > ej for lo, _hi, _c, ej in run) and low <= e and close > e:
            return (_stamp(m), "UP")
        # DOWN: "candles k-Q..k-1 are today's and each has high(j) < E(j); high(k) >= E(k); close(k) < E(k)."
        if all(hi < ej for _lo, hi, _c, ej in run) and high >= e and close < e:
            return (_stamp(m), "DOWN")
    return None


# ---------------------------------------------------------------------------
# 6. avgprice_cross_hold
# ---------------------------------------------------------------------------
def avgprice_cross_hold(ctx, hold_minutes=15, exclude_first_minutes=60):
    hold = int(hold_minutes)
    x = int(exclude_first_minutes)
    # "candle t-H is stamped at or after 09:15 + X - 1 minutes with X = 60 (10:14)"
    earliest_ref = OPEN + x - 1
    side: dict = {}                 # minute -> +1 / -1 / 0
    total = 0.0
    count = 0
    for b in ctx.bars:
        t = _mins(b[0])
        if t < OPEN:
            continue
        if t > LAST_SIGNAL:
            return None
        # "A(t) = arithmetic mean of (high+low+close)/3 over all of today's candles stamped 09:15..t."
        total += (b[2] + b[3] + b[4]) / 3.0
        count += 1
        a = total / count
        # "side(t) = +1 if close(t) > A(t), -1 if close(t) < A(t), 0 if equal."
        s = 1 if b[4] > a else (-1 if b[4] < a else 0)
        side[t] = s
        ref = t - hold              # the candle stamped t-H
        if t < FIRST_SIGNAL or ref < earliest_ref or s == 0:
            continue
        # "side(t-H) != s" - a missing candle t-H has no side, so that minute gives no signal
        if ref not in side or side[ref] == s:
            continue
        # "side(t-H+1), ..., side(t) (H = 15 consecutive candles) all equal the same s (+1 or -1)"
        if all(side.get(u) == s for u in range(ref + 1, t + 1)):
            return (b[0], "UP" if s == 1 else "DOWN")
    return None


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------
def _neighbours(centre: dict, moves: list) -> list:
    """moves = [(param, lower value, lower label text, upper value, upper label text), ...] in library order.
    One parameter moved at a time: for each param its lower neighbour, then its upper neighbour."""
    out = []
    for name, lo, lo_txt, hi, hi_txt in moves:
        for value, txt in ((lo, lo_txt), (hi, hi_txt)):
            params = dict(centre)
            params[name] = value
            out.append({"label": f"{name}={txt}", "params": params})
    return out


def _entry(fn, centre: dict, moves: list) -> dict:
    return {"fn": fn, "centre": dict(centre), "neighbours": _neighbours(centre, moves)}


# label values are the library's own strings ("0.20", "11:30"), not a re-formatted number
CANDIDATES = {
    "orb15_close_break": _entry(
        orb15_close_break, {"opening_range_minutes": 15},
        [("opening_range_minutes", 10, "10", 30, "30")]),
    "pdhl_break_5m": _entry(
        pdhl_break_5m, {"confirmation_candle_minutes": 5},
        [("confirmation_candle_minutes", 3, "3", 15, "15")]),
    "first_hour_close_location": _entry(
        first_hour_close_location, {"window_minutes": 60, "outer_fraction_of_range": 0.25},
        [("window_minutes", 45, "45", 90, "90"),
         ("outer_fraction_of_range", 0.20, "0.20", 0.33, "0.33")]),
    "afternoon_new_extreme": _entry(
        afternoon_new_extreme, {"scan_start_time": "12:00"},
        [("scan_start_time", "11:30", "11:30", "12:30", "12:30")]),
    "ema20_pullback_5m": _entry(
        ema20_pullback_5m, {"ema_period": 20, "clean_run_candles": 6},
        [("ema_period", 10, "10", 30, "30"),
         ("clean_run_candles", 4, "4", 8, "8")]),
    "avgprice_cross_hold": _entry(
        avgprice_cross_hold, {"hold_minutes": 15, "exclude_first_minutes": 60},
        [("hold_minutes", 10, "10", 30, "30"),
         ("exclude_first_minutes", 45, "45", 90, "90")]),
}


# Readings chosen where the text leaves room.  Every one is the most literal reading, fixed before any
# result was looked at (no profit, loss or forward price move was ever computed for this module).
AMBIGUITIES = {
    "_all": [
        "Signal minutes are 09:19..14:13 (protocol P1.3) wherever the library says 14:29. A candle outside that "
        "window is simply not examined; it does not consume the day (P1.4), no rule text here says it does.",
        "Neighbour labels use the library's own value strings, e.g. 'outer_fraction_of_range=0.20' and "
        "'scan_start_time=11:30'; the params hold the parsed value (int minutes, float fraction, 'HH:MM' string).",
        "Missing 1-minute bars (none exist on disk up to 2026-04-30; every session has 375 bars): a level or window "
        "that needs a whole block of bars (opening range, first-hour window) makes the day 'no signal' when a bar "
        "is missing; an N-minute candle is examined only when its last 1-minute bar is present.",
    ],
    "orb15_close_break": [
        "The breakout comparison is strict (close > ORH, close < ORL) exactly as written; a close equal to the "
        "level is not a signal.",
        "The scan starts at the candle stamped 09:15+N (09:25 / 09:30 / 09:45), which is always inside 09:19..14:13.",
    ],
    "pdhl_break_5m": [
        "PDH / PDL are the raw 1-minute high / low extremes of the previous session on disk (prev_sessions[-1], "
        "which for 2026-02-02 is Sunday 2026-02-01); the house daily close is not involved.",
        "The B-minute candle's close is the close of its last 1-minute bar. With B = 3 the 09:15-09:17 candle "
        "(m = 09:17) is before 09:19 and is not examined; the first examined candle is 09:18-09:20 (m = 09:20). "
        "With B = 15 the first is 09:15-09:29 and the last 13:45-13:59 (m = 13:59; the next one ends 14:14). "
        "With B = 5 the last examined candle is 14:05-14:09, with B = 3 it is 14:09-14:11.",
        "A candle that is not examined (B = 3: 09:15-09:17) does not consume the day even if it closed beyond "
        "the level; the first EXAMINED candle beyond the level is the signal.",
        "If one candle closed both above PDH and below PDL (impossible unless PDH < PDL) UP is tested first.",
    ],
    "first_hour_close_location": [
        "The threshold is computed as the Python expression 1 - F with no rounding tolerance: p >= 1 - F is UP, "
        "p <= F is DOWN (for F = 0.33 the UP threshold is 0.67, i.e. 0.6699999999999999 in floating point).",
        "Decision minute = 09:15 + W - 1 (09:59 / 10:14 / 10:44); it is the only minute evaluated.",
        "UP is tested before DOWN; both can hold only if F >= 0.5, which no library value reaches.",
    ],
    "afternoon_new_extreme": [
        "SH / SL at candle t cover every candle stamped 09:15..t-1, including the candles of the scan period "
        "itself that did not fire (the text says 'all candles stamped 09:15..t-1').",
        "Only the close is compared (strictly) with SH / SL; a candle whose high exceeds SH but closes below it "
        "is not a signal and just raises SH for the following candles.",
        "The scan runs from S to 14:13 (protocol), so the last fill bar is 14:14, not 14:30.",
        "The scan has no memory of the morning: a close beyond the session extreme before S is not a signal and "
        "does not consume the day (the text evaluates only candles stamped from S); the signal is the first "
        "candle from S that closes beyond the extreme of everything before it.",
    ],
    "ema20_pullback_5m": [
        "The continuous series starts with the first session on disk (ctx.prev_sessions[0] = 2025-11-24); the EMA "
        "is seeded with the close of that session's 09:15-09:19 candle and runs through every session, overnight "
        "gaps included, with no reset.",
        "'belongs to TODAY' is read as: the signal candle is at least the (Q+1)-th candle of today, so the earliest "
        "signal candle is 09:45-09:49 for Q = 6 (09:35-09:39 for Q = 4, 09:55-09:59 for Q = 8).",
        "Comparisons are exactly as written: run candles strict (low > E, high < E), touch non-strict "
        "(low(k) <= E(k), high(k) >= E(k)), close strict; E(j) is always the value including candle j itself.",
        "Last examined candle is 14:05-14:09 (m = 14:09), since the next one ends at 14:14 > 14:13.",
        "The EMA at the end of the previous session is cached per (index, day, period); it depends on earlier "
        "sessions only.",
    ],
    "avgprice_cross_hold": [
        "A(t) is a running sum of (h+l+c)/3 divided by the count of today's candles stamped 09:15..t; side(t) "
        "compares close(t) with A(t) of the SAME minute (A includes candle t).",
        "side(t-H) != s is satisfied by 0 as well as by the opposite side.",
        "'0 if equal' is an exact floating-point comparison of close(t) with A(t), no tolerance; a candle with "
        "side 0 inside the hold run breaks the run (the text needs all H sides equal to s = +1 or -1).",
        "Earliest signal candle = 09:15 + X - 1 + H (10:29 at the centre; 10:24 for H = 10, 10:44 for H = 30, "
        "10:14 for X = 45, 10:59 for X = 90). A flip whose reference candle t-H is before 09:15 + X - 1 is never "
        "a signal, and it does not consume the day: a later flip can still fire.",
        "Latest signal candle is 14:13 (protocol) instead of 14:29.",
    ],
}
