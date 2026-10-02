"""check/alt_revvol.py - INDEPENDENT SECOND CODING of seven library candidates
(4 mean-reversion, 3 volatility).  Written only from library.json, protocol.md and ctx.py.

Conventions used by every function here
  * A signal is (t, direction): t = "HH:MM" stamp of the LAST 1-minute bar of the signal candle,
    direction "UP" (buy CE) or "DOWN" (buy PE).  Protocol P1.3: "09:19" <= t <= "14:13"
    (wherever the library says 14:29, read 14:13).
  * Times are handled as minutes of the day (09:15 = 555).
  * A 5-minute candle is aligned to 09:15 and exists only when all five of its 1-minute bars are
    present in ctx.bars, so a candle that is not complete yet is never seen (no look-ahead).
  * Every function scans forward and returns at the first qualifying candle; None when there is
    no signal or the day cannot be evaluated.
"""
from __future__ import annotations

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
if STUDY not in sys.path:
    sys.path.insert(0, STUDY)

import ctx as ctxmod                      # noqa: E402
from ctx import hhmm, minutes             # noqa: E402

OPEN = 555            # 09:15
SIG_FIRST = 559       # 09:19  protocol P1.3
SIG_LAST = 853        # 14:13  protocol P1.3 ("Wherever library.json says ... 14:29, read 14:13")
SESSION_LAST = 929    # 15:29


# ---------------------------------------------------------------------------
# helpers (private to this module)
# ---------------------------------------------------------------------------
def _five(bars):
    """5-minute candles aligned to 09:15, as tuples (last_minute, o, h, l, c), ascending.
    Only candles whose five 1-minute bars are all present."""
    by = {minutes(b[0]): b for b in bars}
    out = []
    s = OPEN
    while s + 4 <= SESSION_LAST:
        chunk = [by.get(s + i) for i in range(5)]
        if all(b is not None for b in chunk):
            out.append((s + 4,
                        chunk[0][1],
                        max(b[2] for b in chunk),
                        min(b[3] for b in chunk),
                        chunk[4][4]))
        s += 5
    return out


def _first_bars(bars, n):
    """The 1-minute bars stamped 09:15 .. 09:15+n-1 that are present."""
    return [b for b in bars if OPEN <= minutes(b[0]) < OPEN + n]


def _complete_first(bars, n):
    """True when the bar stamped 09:15+n-1 (the last of 'the first n candles') is present."""
    want = hhmm(OPEN + n - 1)
    return any(b[0] == want for b in bars)


# ---------------------------------------------------------------------------
# 1. mr_session_mean_band_fade
# ---------------------------------------------------------------------------
def mr_session_mean_band_fade(ctx, K_band_width_sd=2.0, WARM_minutes=30):
    K, WARM = K_band_width_sd, WARM_minutes
    # "Evaluate only at the minutes t = 09:19, 09:24, 09:29, ... (every 5 minutes) with
    #  09:15 + WARM - 1 <= t <= 14:29"   (14:29 -> 14:13 by protocol P1.3)
    first_t = max(SIG_FIRST, OPEN + WARM - 1)
    closes = []                                   # running list of closes stamped 09:15..t
    for b in ctx.bars:
        t = minutes(b[0])
        if t > SIG_LAST:
            break
        closes.append(b[4])
        if t < first_t or (t - SIG_FIRST) % 5 != 0:
            continue
        # "M = arithmetic mean of all 1-minute closes stamped 09:15..t; SD = population standard
        #  deviation (divide by n) of the same closes; C = close of the candle stamped t."
        n = len(closes)
        m = sum(closes) / n
        sd = math.sqrt(sum((c - m) ** 2 for c in closes) / n)
        if sd == 0:                               # "SD = 0: skip that minute."
            continue
        c = b[4]
        if c >= m + K * sd:                       # "DOWN condition: C >= M + K x SD."
            return (b[0], "DOWN")
        if c <= m - K * sd:                       # "UP condition: C <= M - K x SD."
            return (b[0], "UP")
    return None


# ---------------------------------------------------------------------------
# 2. mr_opening_range_failed_breakout
# ---------------------------------------------------------------------------
def mr_opening_range_failed_breakout(ctx, N_opening_range_minutes=15, W_failure_window_minutes=30):
    N, W = N_opening_range_minutes, W_failure_window_minutes
    bars = ctx.bars
    # "ORH / ORL = highest high / lowest low of the first N 1-minute candles (N = 15: 09:15..09:29)."
    if not _complete_first(bars, N):
        return None
    rng = _first_bars(bars, N)
    orh = max(b[2] for b in rng)
    orl = min(b[3] for b in rng)
    b_up = b_dn = None            # last minute of the first breakout candle on each side
    up_done = dn_done = False     # that side is finished for the day
    for (t, _o, _h, _l, c) in _five(bars):
        # "5-minute candles aligned to 09:15 that START at or after 09:15+N"
        if t - 4 < OPEN + N:
            continue
        if t > SIG_LAST:          # "SIGNAL = the earliest failure candle ... with t <= 14:29" (-> 14:13)
            break
        # failures first: a failure candle must be LATER than its breakout candle (b < t)
        # "Up-failure = the first later 5-minute candle with last minute t, b_up < t <= b_up + W
        #  minutes (W = 30), whose close < ORH."
        up_fail = dn_fail = False
        if b_up is not None and not up_done:
            if t > b_up + W:
                up_done = True    # "if it does not fail within W that side is finished for the day"
            elif c < orh:
                up_fail = True
        if b_dn is not None and not dn_done:
            if t > b_dn + W:
                dn_done = True
            elif c > orl:
                dn_fail = True
        # (both failing on the same candle cannot happen: a down-breakout close < ORL is itself an
        #  up-failure close < ORH, and the reverse; up is tested first only for definiteness.)
        if up_fail:
            return (hhmm(t), "DOWN")   # "Broke above the range, then closed back below ORH: buy PE."
        if dn_fail:
            return (hhmm(t), "UP")     # "Broke below, then closed back above ORL: buy CE."
        # "Up-breakout candle = the first such candle of the day whose close > ORH"
        # "Only the first breakout on each side is eligible"
        if b_up is None and c > orh:
            b_up = t
        if b_dn is None and c < orl:
            b_dn = t
    return None


# ---------------------------------------------------------------------------
# 3. mr_prev_day_extreme_sweep
# ---------------------------------------------------------------------------
def mr_prev_day_extreme_sweep(ctx, W_reclaim_window_minutes=60):
    W = W_reclaim_window_minutes
    if not ctx.prev_sessions:
        return None
    # "PDH / PDL = highest high / lowest low of the previous session's index 1-minute candles"
    prev = ctx.session(ctx.prev_sessions[-1])
    if not prev:
        return None
    pdh = max(b[2] for b in prev)
    pdl = min(b[3] for b in prev)
    bars = ctx.bars
    # "b_up = stamp of the first 1-minute candle (from 09:15, so a gap open counts) whose high > PDH"
    # "b_dn = stamp of the first 1-minute candle whose low < PDL"   ("Only the first breach on each
    #  side is eligible.")
    b_up = next((minutes(b[0]) for b in bars if b[2] > pdh), None)
    b_dn = next((minutes(b[0]) for b in bars if b[3] < pdl), None)
    if b_up is None and b_dn is None:
        return None
    up_t = dn_t = None
    for (t, _o, _h, _l, c) in _five(bars):
        # "Up-sweep = the first 5-minute candle (aligned to 09:15) with last minute t,
        #  b_up <= t <= b_up + W minutes (W = 60), whose close < PDH."
        if up_t is None and b_up is not None and b_up <= t <= b_up + W and c < pdh:
            up_t = t
        # "down-sweep = the first 5-minute candle with b_dn <= t <= b_dn + W whose close > PDL"
        if dn_t is None and b_dn is not None and b_dn <= t <= b_dn + W and c > pdl:
            dn_t = t
        if up_t is not None or dn_t is not None:
            break                 # the earliest sweep across both sides is known at this candle
    if up_t is None and dn_t is None:
        return None
    if up_t is not None and dn_t is not None:
        return None               # both sides swept on the same candle: see AMBIGUITIES
    t = up_t if up_t is not None else dn_t
    # "SIGNAL = the earliest such t across both sides with 09:19 <= t <= 14:29" (-> 14:13)
    if not SIG_FIRST <= t <= SIG_LAST:
        return None
    return (hhmm(t), "DOWN" if up_t is not None else "UP")


# ---------------------------------------------------------------------------
# 4. mr_rsi14_exhaustion_recross
# ---------------------------------------------------------------------------
def mr_rsi14_exhaustion_recross(ctx, P_rsi_period=14, D_level_distance_from_50=20):
    P, D = P_rsi_period, D_level_distance_from_50
    upper, lower = 50 + D, 50 - D            # "Levels: upper = 50 + D, lower = 50 - D, D = 20."
    # "5-minute index candles of TODAY only, aligned to 09:15 (no carry-over from yesterday)."
    candles = _five(ctx.bars)
    gains, losses = [], []
    avg_gain = avg_loss = None
    prev_rsi = None
    for i in range(1, len(candles)):
        t = candles[i][0]
        if t > SIG_LAST:
            break
        # "changes d(i) = close(i) - close(i-1) from today's 2nd candle"
        d = candles[i][4] - candles[i - 1][4]
        g, l = (d, 0.0) if d > 0 else (0.0, -d)
        if avg_gain is None:
            gains.append(g)
            losses.append(l)
            if len(gains) < P:
                continue
            # "the first average gain and average loss are the simple means of the first P gains /
            #  losses (first RSI at today's candle number P+1 ...)"
            avg_gain = sum(gains) / P
            avg_loss = sum(losses) / P
        else:
            # "afterwards Wilder smoothing avg = (previous avg x (P-1) + current) / P"
            avg_gain = (avg_gain * (P - 1) + g) / P
            avg_loss = (avg_loss * (P - 1) + l) / P
        # "RSI = 100 - 100/(1 + avgGain/avgLoss), RSI = 100 if avgLoss = 0."
        rsi = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
        if prev_rsi is not None and t >= SIG_FIRST:
            # "DOWN signal at a candle whose RSI < upper while the previous candle's RSI >= upper."
            if rsi < upper and prev_rsi >= upper:
                return (hhmm(t), "DOWN")
            # "UP signal at a candle whose RSI > lower while the previous candle's RSI <= lower."
            if rsi > lower and prev_rsi <= lower:
                return (hhmm(t), "UP")
        prev_rsi = rsi
    return None


# ---------------------------------------------------------------------------
# 5. vol_narrow_ib_extension
# ---------------------------------------------------------------------------
IB_SESSIONS = 20      # "AVG = simple mean of WIDTH (same M) over the 20 sessions before today."


def _ib(bars, m):
    """(IBH, IBL) of the first m 1-minute candles, or None if the window is not complete."""
    if not _complete_first(bars, m):
        return None
    rng = _first_bars(bars, m)
    return max(b[2] for b in rng), min(b[3] for b in rng)


def vol_narrow_ib_extension(ctx, M_initial_balance_minutes=60, K_width_vs_20_session_average=1.0):
    M, K = M_initial_balance_minutes, K_width_vs_20_session_average
    # "Initial balance (IB) = highest high (IBH) and lowest low (IBL) of the first M 1-minute
    #  candles (M = 60: 09:15..10:14). WIDTH = IBH - IBL."
    ib = _ib(ctx.bars, M)
    if ib is None:
        return None
    ibh, ibl = ib
    width = ibh - ibl
    if len(ctx.prev_sessions) < IB_SESSIONS:
        return None
    widths = []
    for d in ctx.prev_sessions[-IB_SESSIONS:]:
        p = _ib(ctx.session(d), M)
        if p is None:
            return None
        widths.append(p[0] - p[1])
    avg = sum(widths) / IB_SESSIONS
    # "The day is eligible only if WIDTH < K x AVG with K = 1.0."
    if not width < K * avg:
        return None
    for (t, _o, _h, _l, c) in _five(ctx.bars):
        # "5-minute candles aligned to 09:15 that START at or after 09:15+M ... and whose last
        #  minute m <= 14:29" (-> 14:13)
        if t - 4 < OPEN + M or t < SIG_FIRST:
            continue
        if t > SIG_LAST:
            break
        # "SIGNAL = the FIRST such candle whose close > IBH (UP) or whose close < IBL (DOWN)"
        if c > ibh:
            return (hhmm(t), "UP")
        if c < ibl:
            return (hhmm(t), "DOWN")
    return None


# ---------------------------------------------------------------------------
# 6. vol_wide_range_bar_follow
# ---------------------------------------------------------------------------
WRB_FIRST = 574       # 09:34  "whose last minute m satisfies 09:34 <= m <= 14:29 (the first three
#                              candles 09:15-09:29 are skipped)"


def vol_wide_range_bar_follow(ctx, X_range_multiple=2.0, N_average_candles=20):
    X, N = X_range_multiple, N_average_candles
    today = _five(ctx.bars)
    earlier = None                # ranges of the candles before today, oldest first (built lazily)
    for k, (t, o, h, l, c) in enumerate(today):
        if t < WRB_FIRST:
            continue
        if t > SIG_LAST:
            break
        # "AVG = simple mean of the ranges of the N = 20 five-minute candles immediately before k
        #  (running back into the previous session when needed)."
        before = [x[2] - x[3] for x in today[max(0, k - N):k]]
        if len(before) < N:
            if earlier is None:
                earlier = []
                for d in reversed(ctx.prev_sessions):      # one continuous series across sessions
                    earlier = [x[2] - x[3] for x in _five(ctx.session(d))] + earlier
                    if len(earlier) >= N:
                        break
            need = N - len(before)
            if len(earlier) < need:
                return None
            before = earlier[-need:] + before
        avg = sum(before) / N
        rng = h - l                                        # "Range of a candle = high - low."
        if rng >= X * avg:
            mid = (h + l) / 2
            # "UP condition: range(k) >= X x AVG ..., AND close(k) > open(k), AND close(k) >
            #  (high(k) + low(k)) / 2."
            if c > o and c > mid:
                return (hhmm(t), "UP")
            # "DOWN condition: range(k) >= X x AVG, AND close(k) < open(k), AND close(k) <
            #  (high(k) + low(k)) / 2."
            if c < o and c < mid:
                return (hhmm(t), "DOWN")
    return None


# ---------------------------------------------------------------------------
# 7. vol_lunch_lull_break
# ---------------------------------------------------------------------------
def vol_lunch_lull_break(ctx, T1_lull_start="11:30", T2_lull_end="13:30"):
    t1, t2 = minutes(T1_lull_start), minutes(T2_lull_end)
    bars = ctx.bars
    # "Lull window = 1-minute candles stamped from T1 = 11:30 up to but excluding T2 = 13:30"
    if not any(minutes(b[0]) == t2 - 1 for b in bars):     # the window is not complete yet
        return None
    lull = [b for b in bars if t1 <= minutes(b[0]) < t2]
    lh = max(b[2] for b in lull)                           # "LH / LL = highest high / lowest low"
    ll = min(b[3] for b in lull)
    for (t, _o, _h, _l, c) in _five(bars):
        # "5-minute candles aligned to 09:15 that START at or after T2 and whose last minute
        #  m <= 14:29" (-> 14:13)
        if t - 4 < t2 or t < SIG_FIRST:
            continue
        if t > SIG_LAST:
            break
        # "SIGNAL = the FIRST such candle whose close > LH (UP) or whose close < LL (DOWN)"
        if c > lh:
            return (hhmm(t), "UP")
        if c < ll:
            return (hhmm(t), "DOWN")
    return None


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------
def _candidate(fn, spec):
    """spec = [(param, centre, lower, upper, label_lower, label_upper), ...] in library order."""
    centre = {p: c for p, c, _lo, _up, _a, _b in spec}
    neighbours = []
    for p, _c, lo, up, lab_lo, lab_up in spec:
        for value, lab in ((lo, lab_lo), (up, lab_up)):
            params = dict(centre)
            params[p] = value
            neighbours.append({"label": f"{p}={lab}", "params": params})
    return {"fn": fn, "centre": centre, "neighbours": neighbours}


CANDIDATES = {
    "mr_session_mean_band_fade": _candidate(mr_session_mean_band_fade, [
        ("K_band_width_sd", 2.0, 1.5, 2.5, "1.5", "2.5"),
        ("WARM_minutes", 30, 15, 60, "15", "60"),
    ]),
    "mr_opening_range_failed_breakout": _candidate(mr_opening_range_failed_breakout, [
        ("N_opening_range_minutes", 15, 5, 30, "5", "30"),
        ("W_failure_window_minutes", 30, 15, 60, "15", "60"),
    ]),
    "mr_prev_day_extreme_sweep": _candidate(mr_prev_day_extreme_sweep, [
        ("W_reclaim_window_minutes", 60, 30, 120, "30", "120"),
    ]),
    "mr_rsi14_exhaustion_recross": _candidate(mr_rsi14_exhaustion_recross, [
        ("P_rsi_period", 14, 10, 20, "10", "20"),
        ("D_level_distance_from_50", 20, 15, 25, "15", "25"),
    ]),
    "vol_narrow_ib_extension": _candidate(vol_narrow_ib_extension, [
        ("M_initial_balance_minutes", 60, 45, 75, "45", "75"),
        ("K_width_vs_20_session_average", 1.0, 0.9, 1.1, "0.9", "1.1"),
    ]),
    "vol_wide_range_bar_follow": _candidate(vol_wide_range_bar_follow, [
        ("X_range_multiple", 2.0, 1.5, 2.5, "1.5", "2.5"),
        ("N_average_candles", 20, 14, 30, "14", "30"),
    ]),
    "vol_lunch_lull_break": _candidate(vol_lunch_lull_break, [
        ("T1_lull_start", "11:30", "11:00", "12:00", "11:00", "12:00"),
        ("T2_lull_end", "13:30", "13:00", "14:00", "13:00", "14:00"),
    ]),
}

_COMMON = [
    "Signal window: the library's '<= 14:29' is read as '<= 14:13' (protocol P1.3). For 5-minute "
    "candles the last admissible candle is therefore 14:05-14:09 (t = 14:09); for the 5-minute "
    "evaluation grid of the band fade the last minute is 14:09 too.",
    "A 5-minute candle exists only when all five of its 1-minute bars are present (every session "
    "on disk has all 375 bars, so this never bites; it is what keeps an unfinished candle unseen).",
    "Parameter names are the library's 'name' fields verbatim; neighbour labels use the library's "
    "own value strings.",
]

AMBIGUITIES = {
    "mr_session_mean_band_fade": _COMMON + [
        "The mean and SD use every close stamped 09:15..t including the candle t itself (the text "
        "says 'closes stamped 09:15..t'), so C is part of its own band.",
        "First evaluation minute = the first grid minute (09:19 + 5j) with t >= 09:15 + WARM - 1: "
        "09:44 for WARM 30, 09:29 for WARM 15, 10:14 for WARM 60.",
        "An evaluation minute that does not qualify does not consume the day; the scan goes on to "
        "the next grid minute.",
    ],
    "mr_opening_range_failed_breakout": _COMMON + [
        "The failure window is counted in minutes between LAST minutes: b < t <= b + W, so W = 30 "
        "admits the 6 five-minute candles after the breakout candle (W = 15: 3, W = 60: 12).",
        "A breakout close must be strictly beyond the range (close > ORH / close < ORL) and a "
        "failure close strictly back inside (close < ORH / close > ORL); a close exactly on the "
        "level is neither.",
        "A side whose first breakout did not fail within W is finished for the day; a later second "
        "breakout of that side is ignored ('Only the first breakout on each side is eligible').",
        "The candle that fails one side can be the breakout candle of the other side (close < ORL "
        "after an up-breakout): it is returned as the up-failure signal (DOWN), and the day ends "
        "there because only the first signal counts.",
        "A breakout candle may be any candle starting at or after 09:15+N, including one after "
        "14:13; only the FAILURE candle has to lie in 09:19..14:13. A failure after 14:13 is no signal.",
        "Both sides failing on the same candle is logically impossible (a close below ORL is "
        "already a close below ORH), so no tie rule was needed.",
    ],
    "mr_prev_day_extreme_sweep": _COMMON + [
        "The 5-minute candle that contains the breach minute is eligible (b <= t), as the text says.",
        "Each side has exactly one sweep candle: the first 5-minute candle in [b, b + W] closing "
        "back inside. The day's signal is the earlier of the two sides' sweep candles; if that "
        "candle's t is after 14:13 there is no signal (the other side cannot be earlier).",
        "TIE: if the up-sweep and the down-sweep fall on the same 5-minute candle (PDH and PDL both "
        "breached and the candle closes between them) the text gives two opposite directions for "
        "one t. Read as NO SIGNAL for the day (each side's only sweep candle is spent). The self-run "
        "prints how many days this happens on.",
        "Breach is strict (high > PDH, low < PDL) and the reclaim close is strict (close < PDH, "
        "close > PDL).",
        "PDH / PDL use every 1-minute bar of the previous session on disk (prev_sessions[-1], "
        "Sunday 2026-02-01 included).",
    ],
    "mr_rsi14_exhaustion_recross": _COMMON + [
        "RSI = 100 whenever avgLoss = 0, also when avgGain = 0 too (the text's rule, taken literally).",
        "The first candle that can signal is candle P+2 (it needs the previous candle's RSI): "
        "10:34 for P 14, 10:14 for P 10, 11:04 for P 20.",
        "Comparisons exactly as written: DOWN when RSI < upper and previous RSI >= upper; UP when "
        "RSI > lower and previous RSI <= lower. Both cannot be true on one candle.",
    ],
    "vol_narrow_ib_extension": _COMMON + [
        "AVG uses the 20 sessions immediately before today in the index file (warm-up sessions "
        "included); a day with fewer than 20 earlier sessions gives no signal (never happens from "
        "2026-01-01: 27 warm-up sessions).",
        "Today's WIDTH is not part of AVG.",
        "Eligibility is strict: WIDTH < K x AVG.",
        "M = 45 / 60 / 75 all end on the 5-minute grid, so the first candle used starts exactly at "
        "09:15 + M (10:00 / 10:15 / 10:30).",
        "A close above IBH is tested before a close below IBL; both cannot be true unless IBH < IBL.",
    ],
    "vol_wide_range_bar_follow": _COMMON + [
        "AVG excludes candle k itself ('the N candles immediately before k').",
        "The series runs back through as many earlier sessions as needed (one is always enough: a "
        "session has 75 five-minute candles); the overnight gap is not a candle and adds no range.",
        "The first three candles of today (09:15-09:29) are never signal candles but DO count in "
        "the average of later candles.",
        "AVG = 0 is not special-cased (range >= 0 would then hold); it does not occur.",
    ],
    "vol_lunch_lull_break": _COMMON + [
        "The lull window is the 1-minute bars stamped T1 .. T2-1; LH / LL use their highs and lows.",
        "T2 = 13:00 / 13:30 / 14:00 are on the 5-minute grid, so the first candle used starts at T2. "
        "With T2 = 14:00 only two candles are admissible (t = 14:04 and 14:09).",
        "Breaks are strict (close > LH, close < LL).",
    ],
}


# ---------------------------------------------------------------------------
# self-run: signals only (day, minute, direction).  NO outcome of any signal is computed.
# ---------------------------------------------------------------------------
def _selfrun() -> int:
    problems = []
    markets = {ix: ctxmod.Market(ix) for ix in ctxmod.INDEXES}
    for cid, cand in CANDIDATES.items():
        cells = [("centre", cand["centre"])] + [(n["label"], n["params"]) for n in cand["neighbours"]]
        print(f"\n{cid}")
        for label, params in cells:
            for ix, m in markets.items():
                days = [d for d in m.sessions if ctxmod.WINDOW_START <= d <= ctxmod.DISCOVERY_END]
                sig = []
                for d in days:
                    c = m.day_ctx(d)
                    try:
                        p = ctxmod.check_no_lookahead(cand["fn"], c, params)
                        r = cand["fn"](c, **params)
                    except Exception as e:                       # noqa: BLE001
                        p, r = [f"{ix} {d}: raised {type(e).__name__}: {e}"], None
                    problems += [f"{cid} [{label}] {x}" for x in p]
                    if r is not None:
                        sig.append(r)
                up = sum(1 for r in sig if r[1] == "UP")
                ts = sorted(r[0] for r in sig)
                print(f"  {label:<40} {ix:<6} n={len(sig):>3}/{len(days)}  UP={up:>3} DOWN={len(sig) - up:>3}"
                      f"  first={ts[0] if ts else '-'} last={ts[-1] if ts else '-'}")
    # how often the sweep tie (both sides on one candle) happens
    for ix, m in markets.items():
        ties = 0
        for d in [d for d in m.sessions if ctxmod.WINDOW_START <= d <= ctxmod.DISCOVERY_END]:
            c = m.day_ctx(d)
            prev = c.session(c.prev_sessions[-1])
            pdh, pdl = max(b[2] for b in prev), min(b[3] for b in prev)
            b_up = next((minutes(b[0]) for b in c.bars if b[2] > pdh), None)
            b_dn = next((minutes(b[0]) for b in c.bars if b[3] < pdl), None)
            if b_up is None or b_dn is None:
                continue
            for W in (30, 60, 120):
                for (t, _o, _h, _l, cl) in _five(c.bars):
                    a = b_up <= t <= b_up + W and cl < pdh
                    b = b_dn <= t <= b_dn + W and cl > pdl
                    if a or b:
                        ties += a and b
                        break
        print(f"\nmr_prev_day_extreme_sweep tie candles (both sides, any W) on {ix}: {ties}")
    print(f"\nlook-ahead problems / exceptions: {len(problems)}")
    for x in problems[:40]:
        print("  " + x)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(_selfrun())
