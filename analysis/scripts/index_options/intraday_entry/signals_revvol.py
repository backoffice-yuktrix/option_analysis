"""signals_revvol.py - mean-reversion and volatility candidates of library.json, coded to the letter.

Candidates: mr_session_mean_band_fade, mr_opening_range_failed_breakout, mr_prev_day_extreme_sweep,
mr_rsi14_exhaustion_recross, vol_narrow_ib_extension, vol_wide_range_bar_follow, vol_lunch_lull_break.

Every function is fn(ctx, **params) -> None | (t, direction):
  t = "HH:MM" stamp of the signal minute (the LAST 1-minute bar of the signal candle), direction "UP" / "DOWN".
All of them read index candles only (today's, and earlier sessions where the rule says so).
Protocol P1.3 overrides the library's "14:29": signal minutes are 09:19 .. 14:13.

A candle is only used when it is complete inside ctx.bars, so a ctx truncated at t gives the same
answer as the full day (checked mechanically by ctx.check_no_lookahead; run this file to see it).

Run:  python signals_revvol.py      -> signal counts per index / candidate / neighbour, look-ahead check.
It prints signal days, minutes and directions only - never anything that happened after a signal.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ctx import hhmm, minutes  # noqa: E402

OPEN = 555            # 09:15, the stamp of the first 1-minute candle
SIG_FIRST = 559       # 09:19  protocol P1.3
SIG_LAST = 853        # 14:13  protocol P1.3 ("wherever library.json says 14:29, read 14:13")


# ---------------------------------------------------------------------------
# helpers (private to this module)
# ---------------------------------------------------------------------------
def _by_minute(bars):
    """{minute of day: bar} of one session's 1-minute bars."""
    return {minutes(b[0]): b for b in bars}


def _five(bars):
    """COMPLETE 5-minute candles aligned to 09:15, ascending: (start, last, o, h, l, c) with start/last
    as minutes of the day.  A candle is built only when all five of its 1-minute bars are present."""
    by = _by_minute(bars)
    out = []
    for s in range(OPEN, OPEN + 375, 5):
        grp = [by.get(s + j) for j in range(5)]
        if any(g is None for g in grp):
            continue
        out.append((s, s + 4, grp[0][1], max(g[2] for g in grp), min(g[3] for g in grp), grp[4][4]))
    return out


def _first_n(bars, n):
    """The 1-minute bars stamped 09:15 .. 09:15+n-1, or None unless all n are present."""
    by = _by_minute(bars)
    grp = [by.get(OPEN + j) for j in range(n)]
    return None if any(g is None for g in grp) else grp


# ---------------------------------------------------------------------------
# 1. mr_session_mean_band_fade
# ---------------------------------------------------------------------------
def mr_session_mean_band_fade(ctx, K_band_width_sd=2.0, WARM_minutes=30):
    K, WARM = K_band_width_sd, WARM_minutes
    bars = ctx.bars
    by = _by_minute(bars)
    # "Evaluate only at the minutes t = 09:19, 09:24, 09:29, ... (every 5 minutes) with
    #  09:15 + WARM - 1 <= t <= 14:29"   (14:29 -> 14:13 by protocol P1.3)
    for t in range(SIG_FIRST, SIG_LAST + 1, 5):
        if t < OPEN + WARM - 1:
            continue
        bar = by.get(t)
        if bar is None:
            continue
        # "M = arithmetic mean of all 1-minute closes stamped 09:15..t; SD = population standard
        #  deviation (divide by n) of the same closes; C = close of the candle stamped t."
        closes = [b[4] for b in bars if OPEN <= minutes(b[0]) <= t]
        n = len(closes)
        m = sum(closes) / n
        sd = (sum((c - m) ** 2 for c in closes) / n) ** 0.5
        # "SD = 0: skip that minute."
        if sd == 0:
            continue
        c = bar[4]
        # "DOWN condition: C >= M + K x SD. UP condition: C <= M - K x SD."
        if c >= m + K * sd:
            return (hhmm(t), "DOWN")
        if c <= m - K * sd:
            return (hhmm(t), "UP")
    return None


# ---------------------------------------------------------------------------
# 2. mr_opening_range_failed_breakout
# ---------------------------------------------------------------------------
def _orfb_sides(ctx, N, W):
    """(t_up_failure, t_down_failure) as minutes or None each - before the 14:13 limit is applied."""
    # "ORH / ORL = highest high / lowest low of the first N 1-minute candles (N = 15: 09:15..09:29)."
    first = _first_n(ctx.bars, N)
    if first is None:
        return None
    orh = max(b[2] for b in first)
    orl = min(b[3] for b in first)
    # "Then use 5-minute candles aligned to 09:15 that START at or after 09:15+N"
    cs = [c for c in _five(ctx.bars) if c[0] >= OPEN + N]
    t_up = t_dn = None
    # "Up-breakout candle = the first such candle of the day whose close > ORH; its last minute is b_up.
    #  Up-failure = the first later 5-minute candle with last minute t, b_up < t <= b_up + W minutes
    #  (W = 30), whose close < ORH."
    b_up = next((c[1] for c in cs if c[5] > orh), None)
    if b_up is not None:
        t_up = next((c[1] for c in cs if b_up < c[1] <= b_up + W and c[5] < orh), None)
    # "Down-breakout candle = the first 5-minute candle whose close < ORL, last minute b_dn;
    #  down-failure = the first later candle with b_dn < t <= b_dn + W whose close > ORL."
    b_dn = next((c[1] for c in cs if c[5] < orl), None)
    if b_dn is not None:
        t_dn = next((c[1] for c in cs if b_dn < c[1] <= b_dn + W and c[5] > orl), None)
    # "Only the first breakout on each side is eligible; if it does not fail within W that side is
    #  finished for the day."  (b_up / b_dn are the first breakouts; nothing later is looked for.)
    return t_up, t_dn


def mr_opening_range_failed_breakout(ctx, N_opening_range_minutes=15, W_failure_window_minutes=30):
    sides = _orfb_sides(ctx, N_opening_range_minutes, W_failure_window_minutes)
    if sides is None:
        return None
    t_up, t_dn = sides
    # "SIGNAL = the earliest failure candle across both sides with t <= 14:29" (-> 14:13)
    # direction: "Broke above the range, then closed back below ORH: buy PE. Broke below, then closed
    #  back above ORL: buy CE."
    cands = []
    if t_up is not None:
        cands.append((t_up, 0, "DOWN"))
    if t_dn is not None:
        cands.append((t_dn, 1, "UP"))
    if not cands:
        return None
    t, _, direction = min(cands)        # a tie cannot happen (see AMBIGUITIES); text order would decide
    if not SIG_FIRST <= t <= SIG_LAST:
        return None
    return (hhmm(t), direction)


# ---------------------------------------------------------------------------
# 3. mr_prev_day_extreme_sweep
# ---------------------------------------------------------------------------
def _sweep_sides(ctx, W):
    """(t_up_sweep, t_down_sweep) as minutes or None each - before the 09:19..14:13 limit is applied."""
    if not ctx.prev_sessions:
        return None
    # "PDH / PDL = highest high / lowest low of the previous session's index 1-minute candles
    #  (09:15..15:29)."
    prev = [b for b in ctx.session(ctx.prev_sessions[-1]) if "09:15" <= b[0] <= "15:29"]
    if not prev:
        return None
    pdh = max(b[2] for b in prev)
    pdl = min(b[3] for b in prev)
    bars = ctx.bars
    cs = _five(bars)
    t_up = t_dn = None
    # "b_up = stamp of the first 1-minute candle (from 09:15, so a gap open counts) whose high > PDH.
    #  Up-sweep = the first 5-minute candle (aligned to 09:15) with last minute t,
    #  b_up <= t <= b_up + W minutes (W = 60), whose close < PDH."
    b_up = next((minutes(b[0]) for b in bars if b[2] > pdh), None)
    if b_up is not None:
        t_up = next((c[1] for c in cs if b_up <= c[1] <= b_up + W and c[5] < pdh), None)
    # "b_dn = stamp of the first 1-minute candle whose low < PDL; down-sweep = the first 5-minute
    #  candle with b_dn <= t <= b_dn + W whose close > PDL."
    b_dn = next((minutes(b[0]) for b in bars if b[3] < pdl), None)
    if b_dn is not None:
        t_dn = next((c[1] for c in cs if b_dn <= c[1] <= b_dn + W and c[5] > pdl), None)
    # "Only the first breach on each side is eligible."
    return t_up, t_dn


def mr_prev_day_extreme_sweep(ctx, W_reclaim_window_minutes=60):
    sides = _sweep_sides(ctx, W_reclaim_window_minutes)
    if sides is None:
        return None
    t_up, t_dn = sides
    # "SIGNAL = the earliest such t across both sides with 09:19 <= t <= 14:29" (-> 14:13)
    # direction: "Breach above PDH then a 5-minute close back below it: buy PE. Breach below PDL then
    #  a 5-minute close back above it: buy CE."
    cands = []
    if t_up is not None and SIG_FIRST <= t_up <= SIG_LAST:
        cands.append((t_up, 0, "DOWN"))
    if t_dn is not None and SIG_FIRST <= t_dn <= SIG_LAST:
        cands.append((t_dn, 1, "UP"))
    if not cands:
        return None
    t, _, direction = min(cands)        # same t on both sides: the side the text names first (see AMBIGUITIES)
    return (hhmm(t), direction)


# ---------------------------------------------------------------------------
# 4. mr_rsi14_exhaustion_recross
# ---------------------------------------------------------------------------
def mr_rsi14_exhaustion_recross(ctx, P_rsi_period=14, D_level_distance_from_50=20):
    P, D = P_rsi_period, D_level_distance_from_50
    # "5-minute index candles of TODAY only, aligned to 09:15 (no carry-over from yesterday)."
    cs = _five(ctx.bars)
    # "Levels: upper = 50 + D, lower = 50 - D"
    upper, lower = 50 + D, 50 - D
    gains, losses = [], []
    avg_g = avg_l = None
    prev_rsi = None
    for i in range(1, len(cs)):
        # "changes d(i) = close(i) - close(i-1) from today's 2nd candle"
        d = cs[i][5] - cs[i - 1][5]
        g, l = (d, 0.0) if d > 0 else (0.0, -d)
        if avg_g is None:
            gains.append(g)
            losses.append(l)
            if len(gains) < P:
                continue
            # "the first average gain and average loss are the simple means of the first P gains /
            #  losses (first RSI at today's candle number P+1 ...)"
            avg_g, avg_l = sum(gains) / P, sum(losses) / P
        else:
            # "afterwards Wilder smoothing avg = (previous avg x (P-1) + current) / P"
            avg_g = (avg_g * (P - 1) + g) / P
            avg_l = (avg_l * (P - 1) + l) / P
        # "RSI = 100 - 100/(1 + avgGain/avgLoss), RSI = 100 if avgLoss = 0."
        rsi = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
        t = cs[i][1]
        if t > SIG_LAST:
            return None
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
IB_AVG_SESSIONS = 20      # "AVG = simple mean of WIDTH (same M) over the 20 sessions before today"


def _ib(bars, M):
    """(IBH, IBL) of the first M 1-minute candles, or None unless all M are present."""
    first = _first_n(bars, M)
    if first is None:
        return None
    return max(b[2] for b in first), min(b[3] for b in first)


def vol_narrow_ib_extension(ctx, M_initial_balance_minutes=60, K_width_vs_20_session_average=1.0):
    M, K = M_initial_balance_minutes, K_width_vs_20_session_average
    # "Initial balance (IB) = highest high (IBH) and lowest low (IBL) of the first M 1-minute candles
    #  (M = 60: 09:15..10:14). WIDTH = IBH - IBL."
    ib = _ib(ctx.bars, M)
    if ib is None:
        return None
    ibh, ibl = ib
    width = ibh - ibl
    # "AVG = simple mean of WIDTH (same M) over the 20 sessions before today."
    if len(ctx.prev_sessions) < IB_AVG_SESSIONS:
        return None
    widths = []
    for d in ctx.prev_sessions[-IB_AVG_SESSIONS:]:
        p = _ib(ctx.session(d), M)
        if p is None:
            return None
        widths.append(p[0] - p[1])
    avg = sum(widths) / IB_AVG_SESSIONS
    # "The day is eligible only if WIDTH < K x AVG with K = 1.0."
    if not width < K * avg:
        return None
    # "use 5-minute candles aligned to 09:15 that START at or after 09:15+M (10:15-10:19 onward for
    #  M = 60) and whose last minute m <= 14:29" (-> 14:13)
    for c in _five(ctx.bars):
        if c[0] < OPEN + M or c[1] < SIG_FIRST:
            continue
        if c[1] > SIG_LAST:
            break
        # "SIGNAL = the FIRST such candle whose close > IBH (UP) or whose close < IBL (DOWN)"
        if c[5] > ibh:
            return (hhmm(c[1]), "UP")
        if c[5] < ibl:
            return (hhmm(c[1]), "DOWN")
    return None


# ---------------------------------------------------------------------------
# 6. vol_wide_range_bar_follow
# ---------------------------------------------------------------------------
WRB_FIRST_LAST_MINUTE = 574   # 09:34  "last minute m satisfies 09:34 <= m <= 14:29 (the first three
#                                       candles 09:15-09:29 are skipped)"


def vol_wide_range_bar_follow(ctx, X_range_multiple=2.0, N_average_candles=20):
    X, N = X_range_multiple, N_average_candles
    today = _five(ctx.bars)
    if not today:
        return None
    # "5-minute index candles, each session aligned to 09:15, kept as one continuous series across
    #  sessions. Range of a candle = high - low."
    prior = []                                   # ranges of earlier sessions' candles, ascending
    for d in reversed(ctx.prev_sessions):
        if len(prior) >= N:
            break
        prior = [c[3] - c[4] for c in _five(ctx.session(d))] + prior
    ranges = prior + [c[3] - c[4] for c in today]
    off = len(prior)
    for i, c in enumerate(today):
        m = c[1]
        if m < WRB_FIRST_LAST_MINUTE or m < SIG_FIRST:
            continue
        if m > SIG_LAST:
            break
        j = off + i
        if j < N:
            continue
        # "AVG = simple mean of the ranges of the N = 20 five-minute candles immediately before k
        #  (running back into the previous session when needed)."
        avg = sum(ranges[j - N:j]) / N
        rng, o, h, l, cl = ranges[j], c[2], c[3], c[4], c[5]
        if not rng >= X * avg:
            continue
        # "UP condition: range(k) >= X x AVG with X = 2.0, AND close(k) > open(k), AND
        #  close(k) > (high(k) + low(k)) / 2."
        if cl > o and cl > (h + l) / 2:
            return (hhmm(m), "UP")
        # "DOWN condition: range(k) >= X x AVG, AND close(k) < open(k), AND close(k) < (high(k) + low(k)) / 2."
        if cl < o and cl < (h + l) / 2:
            return (hhmm(m), "DOWN")
    return None


# ---------------------------------------------------------------------------
# 7. vol_lunch_lull_break
# ---------------------------------------------------------------------------
def vol_lunch_lull_break(ctx, T1_lull_start="11:30", T2_lull_end="13:30"):
    t1, t2 = minutes(T1_lull_start), minutes(T2_lull_end)
    by = _by_minute(ctx.bars)
    # "Lull window = 1-minute candles stamped from T1 = 11:30 up to but excluding T2 = 13:30
    #  (11:30..13:29). LH / LL = highest high / lowest low of that window."
    lull = [by.get(m) for m in range(t1, t2)]
    if not lull or any(b is None for b in lull):
        return None
    lh = max(b[2] for b in lull)
    ll = min(b[3] for b in lull)
    # "Use 5-minute candles aligned to 09:15 that START at or after T2 and whose last minute m <= 14:29"
    for c in _five(ctx.bars):
        if c[0] < t2 or c[1] < SIG_FIRST:
            continue
        if c[1] > SIG_LAST:
            break
        # "SIGNAL = the FIRST such candle whose close > LH (UP) or whose close < LL (DOWN)"
        if c[5] > lh:
            return (hhmm(c[1]), "UP")
        if c[5] < ll:
            return (hhmm(c[1]), "DOWN")
    return None


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------
def _entry(fn, spec):
    """spec = [(param, centre, lower, upper, label_lower, label_upper), ...] in library order."""
    centre = {p: c for p, c, *_ in spec}
    neighbours = []
    for p, _c, lo, up, lab_lo, lab_up in spec:
        for v, lab in ((lo, lab_lo), (up, lab_up)):
            params = dict(centre)
            params[p] = v
            neighbours.append({"label": f"{p}={lab}", "params": params})
    return {"fn": fn, "centre": centre, "neighbours": neighbours}


CANDIDATES = {
    "mr_session_mean_band_fade": _entry(mr_session_mean_band_fade, [
        ("K_band_width_sd", 2.0, 1.5, 2.5, "1.5", "2.5"),
        ("WARM_minutes", 30, 15, 60, "15", "60")]),
    "mr_opening_range_failed_breakout": _entry(mr_opening_range_failed_breakout, [
        ("N_opening_range_minutes", 15, 5, 30, "5", "30"),
        ("W_failure_window_minutes", 30, 15, 60, "15", "60")]),
    "mr_prev_day_extreme_sweep": _entry(mr_prev_day_extreme_sweep, [
        ("W_reclaim_window_minutes", 60, 30, 120, "30", "120")]),
    "mr_rsi14_exhaustion_recross": _entry(mr_rsi14_exhaustion_recross, [
        ("P_rsi_period", 14, 10, 20, "10", "20"),
        ("D_level_distance_from_50", 20, 15, 25, "15", "25")]),
    "vol_narrow_ib_extension": _entry(vol_narrow_ib_extension, [
        ("M_initial_balance_minutes", 60, 45, 75, "45", "75"),
        ("K_width_vs_20_session_average", 1.0, 0.9, 1.1, "0.9", "1.1")]),
    "vol_wide_range_bar_follow": _entry(vol_wide_range_bar_follow, [
        ("X_range_multiple", 2.0, 1.5, 2.5, "1.5", "2.5"),
        ("N_average_candles", 20, 14, 30, "14", "30")]),
    "vol_lunch_lull_break": _entry(vol_lunch_lull_break, [
        ("T1_lull_start", "11:30", "11:00", "12:00", "11:00", "12:00"),
        ("T2_lull_end", "13:30", "13:00", "14:00", "13:00", "14:00")]),
}

_COMMON = ("Signal minutes are limited to 09:19..14:13 (protocol P1.3) wherever the text says 14:29; the "
           "limit is a constant, not a parameter.")
_FIVE = ("A 5-minute candle is used only when all five of its 1-minute bars are present (every session on "
         "disk has 375 bars, so this never bites); the text does not say what to do with a hole.")

AMBIGUITIES = {
    "mr_session_mean_band_fade": [
        _COMMON,
        "Evaluation grid 09:19, 09:24, ... capped at 14:13 means the last evaluation minute is 14:09.",
        "Both conditions use the same M and SD and cannot hold together when SD > 0; DOWN is tested first.",
        "M and SD are recomputed from the closes at every evaluation minute (plain sum / n, population sd).",
        "The lower bound is taken as written, 09:15 + WARM - 1 <= t: first evaluation 09:29 for WARM = 15, "
        "09:44 for 30, 10:14 for 60.",
    ],
    "mr_opening_range_failed_breakout": [
        _COMMON, _FIVE,
        "The 14:13 limit is applied to the failure candle only; the breakout candle may be any earlier "
        "5-minute candle starting at or after 09:15+N.",
        "'The earliest failure candle across both sides' is found first and then tested against 14:13; "
        "since a later candle is later still this equals 'the earliest failure with t <= 14:13'.",
        "A same-candle failure on both sides is impossible when ORH > ORL (the second side's breakout "
        "candle is itself the first side's failure or lies outside its window); the code would take the "
        "up side (DOWN), the one the text names first.",
        "The window b_up < t <= b_up + W is in minutes on last-minute stamps: W = 30 admits the 6 candles "
        "after the breakout candle, W = 15 admits 3, W = 60 admits 12.",
    ],
    "mr_prev_day_extreme_sweep": [
        _COMMON, _FIVE,
        "The 5-minute candle that contains the breach minute is eligible (b_up <= t), as written.",
        "The up-sweep / down-sweep is THE first 5-minute candle in its window that closes back; if that "
        "candle's t is outside 09:19..14:13 the side gives nothing (no later candle is looked for).",
        "If both sides give the same t (one 5-minute candle that is the first reclaim of both a PDH and "
        "a PDL breach) the text gives no direction; the code takes the side the text names first "
        "(up-sweep, DOWN). Count of such days in discovery is reported by the self-run. "
        "ADJUDICATED (check/adjudication_revvol.md): the second coding reads this tie as 'no signal'; the "
        "text says 'SIGNAL = the earliest such t across both sides', so a signal exists at that t and "
        "dropping it is the less literal reading - the primary keeps the signal. The tie occurred on 0 of "
        "80 discovery sessions on either index for W = 30, 60 and 120, so no signal depends on the choice.",
        "The breach minute is searched over all of today's 1-minute candles from 09:15, including those "
        "before 09:19, as the text says ('from 09:15, so a gap open counts').",
        "No previous session on disk -> no signal.",
    ],
    "mr_rsi14_exhaustion_recross": [
        _COMMON, _FIVE,
        "avgLoss = 0 gives RSI = 100 even when avgGain is also 0, as written.",
        "A signal needs the previous candle's RSI, so the earliest signal candle is today's candle P+2 "
        "(10:34 for P = 14, 10:14 for P = 10, 11:04 for P = 20); last possible signal minute 14:09.",
        "The two conditions cannot hold together (upper > lower); DOWN is tested first.",
        "D is used as a number of RSI points: upper = 50 + D, lower = 50 - D.",
    ],
    "vol_narrow_ib_extension": [
        _COMMON, _FIVE,
        "'The 20 sessions before today' = the 20 most recent earlier session dates on disk (warm-up days "
        "included); fewer than 20, or any of them lacking one of its first M bars, -> no signal.",
        "20 is a constant of the rule (the parameter note says 'the 20-session average is held fixed').",
        "Eligibility is strict: WIDTH < K x AVG.",
        "Close above IBH is tested before close below IBL; both cannot hold when IBH >= IBL.",
    ],
    "vol_wide_range_bar_follow": [
        _COMMON, _FIVE,
        "The N candles before k run back through as many earlier sessions as needed (one is enough for "
        "N <= 30); the series is the complete 5-minute candles of each session, 09:15..15:29, in order.",
        "Fewer than N earlier candles on disk -> that candle is skipped.",
        "A candle with close = open, or close exactly at its midpoint, meets neither condition.",
        "The lower bound 09:34 on the last minute is a constant of the rule; last possible signal 14:09.",
    ],
    "vol_lunch_lull_break": [
        _COMMON, _FIVE,
        "All 1-minute bars of the lull window T1..T2-1 must be present, else no signal that day.",
        "With T2 = 14:00 only two candles are admissible (last minutes 14:04 and 14:09) because of the "
        "14:13 limit; with T2 = 13:30 the last minutes are 13:34..14:09, with 13:00 they are 13:04..14:09.",
        "T1 and T2 are passed as 'HH:MM' strings.",
        "Close above LH is tested before close below LL; both cannot hold.",
    ],
}


# ---------------------------------------------------------------------------
# self-run: signal counts and the mechanical look-ahead check (discovery days only, no outcomes)
# ---------------------------------------------------------------------------
def _selfrun() -> int:
    from ctx import INDEXES, WINDOW_START, DISCOVERY_END, Market, check_no_lookahead

    problems_total = 0
    for index in INDEXES:
        m = Market(index)
        days = [d for d in m.sessions if WINDOW_START <= d <= DISCOVERY_END]
        print(f"\n=== {index}: {len(days)} sessions {days[0]} .. {days[-1]} ===")
        ctxs = [m.day_ctx(d) for d in days]
        for cid, cand in CANDIDATES.items():
            runs = [("centre", cand["centre"])] + [(n["label"], n["params"]) for n in cand["neighbours"]]
            for label, params in runs:
                sigs, problems = [], []
                for cx in ctxs:
                    problems += check_no_lookahead(cand["fn"], cx, params)
                    r = cand["fn"](cx, **params)
                    if r is not None:
                        sigs.append((cx.day, r[0], r[1]))
                up = sum(1 for s in sigs if s[2] == "UP")
                ts = sorted(s[1] for s in sigs)
                print(f"{cid:34s} {label:36s} n={len(sigs):3d} UP={up:3d} DOWN={len(sigs) - up:3d} "
                      f"first={ts[0] if ts else '-'} last={ts[-1] if ts else '-'} lookahead_problems={len(problems)}")
                for p in problems[:5]:
                    print("    PROBLEM " + p)
                problems_total += len(problems)
        # ties the text does not resolve (mr_prev_day_extreme_sweep), counted for the record
        for label, params in [("centre", CANDIDATES["mr_prev_day_extreme_sweep"]["centre"])] + \
                [(n["label"], n["params"]) for n in CANDIDATES["mr_prev_day_extreme_sweep"]["neighbours"]]:
            ties = 0
            for cx in ctxs:
                s = _sweep_sides(cx, params["W_reclaim_window_minutes"])
                ties += s is not None and s[0] is not None and s[0] == s[1]
            print(f"mr_prev_day_extreme_sweep {label}: days with the same t on both sides = {ties}")
        for label, params in [("centre", CANDIDATES["mr_opening_range_failed_breakout"]["centre"])] + \
                [(n["label"], n["params"]) for n in CANDIDATES["mr_opening_range_failed_breakout"]["neighbours"]]:
            ties = 0
            for cx in ctxs:
                s = _orfb_sides(cx, params["N_opening_range_minutes"], params["W_failure_window_minutes"])
                ties += s is not None and s[0] is not None and s[0] == s[1]
            print(f"mr_opening_range_failed_breakout {label}: days with the same t on both sides = {ties}")
    print(f"\nTOTAL look-ahead problems: {problems_total}")
    return 1 if problems_total else 0


if __name__ == "__main__":
    sys.exit(_selfrun())
