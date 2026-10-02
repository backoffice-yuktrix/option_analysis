"""check/alt_trend.py - INDEPENDENT SECOND CODING of the six "trend" candidates of library.json.

Written only from library.json, protocol.md and ctx.py (no other signal module was read).
Each function is fn(ctx, **params) -> None | (t, direction):
  t = "HH:MM" stamp of the signal minute (the LAST 1-minute bar of the signal candle; the fill bar is t+1),
  direction = "UP" (buy CE) or "DOWN" (buy PE).

Protocol P1.3 overrides the library's "14:29": signal minutes are 09:19 .. 14:13.
Every function scans forward through ctx.bars and returns at the FIRST qualifying candle, using only
bars stamped at or before the candle it is evaluating, so a ctx truncated at t gives the same answer.

Run this file to print signal counts and the look-ahead check (no price outcome is computed anywhere).
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
if STUDY not in sys.path:
    sys.path.insert(0, STUDY)

import ctx as C  # noqa: E402

OPEN_MIN = 555            # 09:15, the first candle of a session
FIRST_SIGNAL = "09:19"    # protocol P1.3: "signal minutes are 09:19 .. 14:13"
LAST_SIGNAL = "14:13"     # protocol P1.3: "Wherever library.json says a signal may fall up to 14:29, read 14:13"

AMBIGUITIES = {
    "_all": [
        "A session is evaluated only if its 1-minute bars are contiguous from 09:15 (bar i is stamped "
        "09:15 + i minutes); otherwise the function returns None. 'Candle t-1', 't-H' etc. are then both "
        "the previous bar and the previous minute. All sessions on disk are complete, so this never bites.",
        "An N-minute candle exists only when all N of its 1-minute bars are present; a trailing partial "
        "group is not a candle.",
        "The library's upper bound 14:29 is read as 14:13 (protocol P1.3). The lower bounds written in each "
        "rule are kept; none of them is earlier than 09:19 except where noted below.",
    ],
    "orb15_close_break": [
        "Scan window is 09:15+N .. 14:13 exactly as written (09:25 for N=10, 09:30 for N=15, 09:45 for N=30).",
        "A close equal to ORH or ORL is not a break (strict > and <, as written).",
    ],
    "pdhl_break_5m": [
        "For B=3 the 09:15-09:17 candle ends at 09:17 < 09:19, so it is not examined (the text: 'Only candles "
        "whose last 1-minute bar m satisfies 09:19 <= m ... are examined'); it does not consume the day, the "
        "scan starts at the 09:18-09:20 candle.",
        "With the 14:13 bound the last examined candle ends at 14:09 (B=5), 14:11 (B=3), 13:59 (B=15).",
        "Previous session = ctx.prev_sessions[-1] (warm-up days and Sunday 2026-02-01 count). PDH / PDL use "
        "every 1-minute bar of that session.",
    ],
    "first_hour_close_location": [
        "UP is tested before DOWN; with F < 0.5 the two cannot both hold.",
        "p is compared with the floating-point values 1 - F and F as computed, no tolerance.",
    ],
    "afternoon_new_extreme": [
        "The scan starts at S with no memory: a close beyond the session extreme before S does not consume "
        "the day (the text only evaluates candles stamped from S).",
        "SH / SL at candle t use every candle 09:15..t-1, including candles stamped at or after S.",
    ],
    "ema20_pullback_5m": [
        "The continuous series is every complete 5-minute candle of every session on disk from 2025-11-24 "
        "(ctx.prev_sessions) followed by today's; the EMA is seeded with the first close of that series and "
        "is NOT reset at a session boundary.",
        "The two sides are mutually exclusive (the Q prior candles cannot be both wholly above and wholly "
        "below the average), so no tie rule is needed.",
        "Candle k itself needs Q earlier candles of TODAY, so k is at least today's candle number Q (0-based): "
        "last bar 09:49 for Q=6, 09:39 for Q=4, 09:59 for Q=8. With the 14:13 bound the last candle ends 14:09.",
    ],
    "avgprice_cross_hold": [
        "side(t-H) != s is true when side(t-H) is 0 (close exactly on the average) as well as when it is -s.",
        "Candle t-H must be stamped at or after 09:15 + X - 1 minutes, as written: 10:14 for X=60, 09:59 for "
        "X=45, 10:44 for X=90; the earliest signal minute is that stamp + H.",
        "A(t) includes candle t itself and every candle from 09:15, also those inside the excluded first X "
        "minutes.",
    ],
}


# ---------------------------------------------------------------------------
# small helpers (private to this module)
# ---------------------------------------------------------------------------
def _contiguous(bars) -> bool:
    """True when bar i is stamped 09:15 + i minutes (an unbroken prefix of a session)."""
    for i, r in enumerate(bars):
        if r[0] != C.hhmm(OPEN_MIN + i):
            return False
    return True


def _candles(bars, n):
    """Complete n-minute candles of one session's contiguous 1-minute bars, aligned to 09:15.
    Each is (stamp of its last 1-minute bar, open, high, low, close)."""
    out = []
    for g in range(len(bars) // n):
        grp = bars[g * n:(g + 1) * n]
        out.append((grp[-1][0], grp[0][1], max(r[2] for r in grp), min(r[3] for r in grp), grp[-1][4]))
    return out


# ---------------------------------------------------------------------------
# 1. orb15_close_break
# ---------------------------------------------------------------------------
def orb15_close_break(ctx, opening_range_minutes=15):
    n = opening_range_minutes
    bars = ctx.bars
    if len(bars) <= n or not _contiguous(bars):
        return None
    # "ORH / ORL = highest high / lowest low of the first N 1-minute candles (N = 15: candles stamped 09:15..09:29)"
    orh = max(r[2] for r in bars[:n])
    orl = min(r[3] for r in bars[:n])
    # "SIGNAL = the FIRST completed 1-minute candle stamped t, with 09:15+N <= t <= 14:29 ... whose close > ORH (UP)
    #  or whose close < ORL (DOWN)"   (14:29 -> 14:13 by protocol P1.3)
    for i in range(n, len(bars)):
        t, close = bars[i][0], bars[i][4]
        if t > LAST_SIGNAL:
            return None
        if t < FIRST_SIGNAL:
            continue
        if close > orh:
            return (t, "UP")
        if close < orl:
            return (t, "DOWN")
    return None


# ---------------------------------------------------------------------------
# 2. pdhl_break_5m
# ---------------------------------------------------------------------------
def pdhl_break_5m(ctx, confirmation_candle_minutes=5):
    b = confirmation_candle_minutes
    if not ctx.prev_sessions:
        return None
    bars = ctx.bars
    if not bars or not _contiguous(bars):
        return None
    # "PDH / PDL = highest high / lowest low of the previous session's index 1-minute candles (09:15..15:29)"
    prev = ctx.session(ctx.prev_sessions[-1])
    if not prev:
        return None
    pdh = max(r[2] for r in prev)
    pdl = min(r[3] for r in prev)
    # "Build today's B-minute candles from 1-minute candles, aligned to 09:15 ... Only candles whose last 1-minute
    #  bar m satisfies 09:19 <= m <= 14:29 are examined. SIGNAL = the FIRST such candle whose close > PDH (UP) or
    #  whose close < PDL (DOWN)"   (14:29 -> 14:13)
    for m, _o, _h, _l, close in _candles(bars, b):
        if m > LAST_SIGNAL:
            return None
        if m < FIRST_SIGNAL:
            continue
        if close > pdh:
            return (m, "UP")
        if close < pdl:
            return (m, "DOWN")
    return None


# ---------------------------------------------------------------------------
# 3. first_hour_close_location
# ---------------------------------------------------------------------------
def first_hour_close_location(ctx, window_minutes=60, outer_fraction_of_range=0.25):
    w, f = window_minutes, outer_fraction_of_range
    bars = ctx.bars
    if len(bars) < w or not _contiguous(bars):
        return None
    # "Window = the first W 1-minute candles (W = 60: stamped 09:15..10:14). H1 = highest high, L1 = lowest low,
    #  C1 = close of the window's last candle"
    win = bars[:w]
    t = win[-1][0]
    if not FIRST_SIGNAL <= t <= LAST_SIGNAL:
        return None
    h1 = max(r[2] for r in win)
    l1 = min(r[3] for r in win)
    c1 = win[-1][4]
    # "If H1 = L1, no trade."
    if h1 == l1:
        return None
    # "p = (C1 - L1) / (H1 - L1). At the single decision minute ...: p >= 1 - F is UP, p <= F is DOWN ...;
    #  otherwise no trade."
    p = (c1 - l1) / (h1 - l1)
    if p >= 1 - f:
        return (t, "UP")
    if p <= f:
        return (t, "DOWN")
    return None


# ---------------------------------------------------------------------------
# 4. afternoon_new_extreme
# ---------------------------------------------------------------------------
def afternoon_new_extreme(ctx, scan_start_time="12:00"):
    bars = ctx.bars
    if len(bars) < 2 or not _contiguous(bars):
        return None
    # "For each completed candle stamped t from S = 12:00 to 14:29: SH = highest high of all candles stamped
    #  09:15..t-1, SL = lowest low of the same candles. SIGNAL = the FIRST such candle whose close > SH (UP) or
    #  whose close < SL (DOWN)."   (14:29 -> 14:13)
    sh, sl = bars[0][2], bars[0][3]          # extremes of the candles BEFORE bar i
    for i in range(1, len(bars)):
        t, close = bars[i][0], bars[i][4]
        if t > LAST_SIGNAL:
            return None
        if t >= scan_start_time and t >= FIRST_SIGNAL:
            if close > sh:
                return (t, "UP")
            if close < sl:
                return (t, "DOWN")
        if bars[i][2] > sh:
            sh = bars[i][2]
        if bars[i][3] < sl:
            sl = bars[i][3]
    return None


# ---------------------------------------------------------------------------
# 5. ema20_pullback_5m
# ---------------------------------------------------------------------------
EMA_CANDLE_MINUTES = 5     # "5-minute index candles, each session aligned to 09:15"
_EMA_AT_CLOSE: dict = {}   # (index, period, session) -> EMA after that EARLIER session's last 5-minute candle


def _ema_before_today(ctx, period):
    """EMA of the continuous 5-minute close series after the last candle of the previous session
    (None when today is the first session of the series).  Only earlier, complete sessions are read."""
    alpha = 2.0 / (period + 1)               # "alpha = 2/(P+1)"
    sessions = ctx.prev_sessions
    start, e = 0, None
    for j in range(len(sessions) - 1, -1, -1):          # resume from the latest session already done
        got = _EMA_AT_CLOSE.get((ctx.index, period, sessions[j]))
        if got is not None:
            start, e = j + 1, got
            break
    for d in sessions[start:]:
        for cndl in _candles(ctx.session(d), EMA_CANDLE_MINUTES):
            # "seeded with the first close of the series"
            e = cndl[4] if e is None else alpha * cndl[4] + (1 - alpha) * e
        if e is not None:
            _EMA_AT_CLOSE[(ctx.index, period, d)] = e
    return e


def ema20_pullback_5m(ctx, ema_period=20, clean_run_candles=6):
    p, q = ema_period, clean_run_candles
    bars = ctx.bars
    if not bars or not _contiguous(bars):
        return None
    alpha = 2.0 / (p + 1)
    e = _ema_before_today(ctx, p)
    today = _candles(bars, EMA_CANDLE_MINUTES)
    ema = []                                  # E(k) "value including candle k", for today's candles
    for k, (m, _o, high, low, close) in enumerate(today):
        e = close if e is None else alpha * close + (1 - alpha) * e
        ema.append(e)
        if m > LAST_SIGNAL:                   # "with its last 1-minute bar m <= 14:29"  (-> 14:13)
            return None
        if k < q or m < FIRST_SIGNAL:         # "(a) each of the Q = 6 candles immediately before it ... belongs to TODAY"
            continue
        before = range(k - q, k)
        # UP: "(a) ... has low(j) > E(j); (b) low(k) <= E(k); (c) close(k) > E(k)"
        if low <= e and close > e and all(today[j][3] > ema[j] for j in before):
            return (m, "UP")
        # DOWN: "the mirror: ... each has high(j) < E(j); high(k) >= E(k); close(k) < E(k)"
        if high >= e and close < e and all(today[j][2] < ema[j] for j in before):
            return (m, "DOWN")
    return None


# ---------------------------------------------------------------------------
# 6. avgprice_cross_hold
# ---------------------------------------------------------------------------
def avgprice_cross_hold(ctx, hold_minutes=15, exclude_first_minutes=60):
    h, x = hold_minutes, exclude_first_minutes
    bars = ctx.bars
    if not bars or not _contiguous(bars):
        return None
    # "candle t-H is stamped at or after 09:15 + X - 1 minutes with X = 60 (10:14)"
    first_base = x - 1                        # bar position of the earliest allowed candle t-H
    side = []
    total = 0.0
    for i, r in enumerate(bars):
        t = r[0]
        if t > LAST_SIGNAL:                   # "the FIRST candle stamped t <= 14:29"  (-> 14:13)
            return None
        # "A(t) = arithmetic mean of (high+low+close)/3 over all of today's candles stamped 09:15..t"
        total += (r[2] + r[3] + r[4]) / 3.0
        a = total / (i + 1)
        # "side(t) = +1 if close(t) > A(t), -1 if close(t) < A(t), 0 if equal"
        s = 1 if r[4] > a else (-1 if r[4] < a else 0)
        side.append(s)
        if s == 0 or i - h < first_base or i - h < 0 or t < FIRST_SIGNAL:
            continue
        # "side(t-H+1), ..., side(t) (H = 15 consecutive candles) all equal the same s (+1 or -1), side(t-H) != s"
        if side[i - h] != s and all(v == s for v in side[i - h + 1:i + 1]):
            return (t, "UP" if s > 0 else "DOWN")      # "Direction = s."
    return None


# ---------------------------------------------------------------------------
# CANDIDATES - centres and neighbours are parsed from library.json (never typed by hand)
# ---------------------------------------------------------------------------
_FUNCS = {
    "orb15_close_break": orb15_close_break,
    "pdhl_break_5m": pdhl_break_5m,
    "first_hour_close_location": first_hour_close_location,
    "afternoon_new_extreme": afternoon_new_extreme,
    "ema20_pullback_5m": ema20_pullback_5m,
    "avgprice_cross_hold": avgprice_cross_hold,
}


def _parse(text):
    """'15' -> 15, '0.25' -> 0.25, '12:00' -> '12:00'."""
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _build_candidates():
    with open(os.path.join(STUDY, "library.json"), encoding="utf-8") as f:
        lib = {c["id"]: c for c in json.load(f)["candidates"]}
    out = {}
    for cid, fn in _FUNCS.items():
        params = lib[cid]["params"]
        centre = {p["name"]: _parse(p["centre"]) for p in params}
        neighbours = []
        for p in params:                                   # library order: lower neighbour, then upper
            for side in ("lower_neighbour", "upper_neighbour"):
                moved = dict(centre)
                moved[p["name"]] = _parse(p[side])
                neighbours.append({"label": f"{p['name']}={p[side]}", "params": moved})
        out[cid] = {"fn": fn, "centre": centre, "neighbours": neighbours}
    return out


CANDIDATES = _build_candidates()


# ---------------------------------------------------------------------------
# self-run: signal counts and the mechanical look-ahead check (no outcome of any signal is computed)
# ---------------------------------------------------------------------------
def _main():
    problems = []
    markets = {ix: C.Market(ix) for ix in C.INDEXES}
    for cid, cand in CANDIDATES.items():
        print(f"\n== {cid} ==")
        cells = [("centre", cand["centre"])] + [(nb["label"], nb["params"]) for nb in cand["neighbours"]]
        for label, params in cells:
            for ix, m in markets.items():
                days = [d for d in m.sessions if C.WINDOW_START <= d <= C.DISCOVERY_END]
                sig = []
                for d in days:
                    dc = m.day_ctx(d)
                    try:
                        problems += [f"{cid} [{label}] {p}" for p in C.check_no_lookahead(cand["fn"], dc, params)]
                        r = cand["fn"](dc, **params)
                    except Exception as e:                  # noqa: BLE001 - reported, not hidden
                        problems.append(f"{cid} [{label}] {ix} {d}: raised {type(e).__name__}: {e}")
                        continue
                    if r is not None:
                        sig.append(r)
                up = sum(1 for _t, s in sig if s == "UP")
                ts = sorted(t for t, _s in sig)
                print(f"  {label:<34} {ix:<6} days {len(days)}  signals {len(sig):>3}  UP {up:>3}  DOWN {len(sig) - up:>3}"
                      f"  first {ts[0] if ts else '-'}  last {ts[-1] if ts else '-'}")
    print(f"\nlook-ahead / exception problems: {len(problems)}")
    for p in problems[:40]:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(_main())
