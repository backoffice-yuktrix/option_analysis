"""check/alt_repo_b.py - INDEPENDENT SECOND CODING of five library candidates (blind to signals_*.py).

    repo_snd_sweep_microbreak, repo_snd_zone_touch, repo_vpr_break_retest, repo_vpr_reentry,
    repo_atr_trail_ema_cross

Written only from library.json ("signal" text), protocol.md and ctx.py.  Index candles only: no option,
VIX, daily file, weekday or expiry input is read by any function here.

Every function scans forward through COMPLETED N-minute candles and returns at the first qualifying
one; at candle c it only ever reads candles 0..c (and earlier sessions).  Signal minute t = the last
1-minute bar of the signal candle, and must lie in 09:19..14:13 (protocol P1.3 overrides the
library's 14:29).

Run this file to print the signal counts and the look-ahead check:  python check/alt_repo_b.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ctx as C  # noqa: E402

OPEN_MIN = 555            # 09:15
SIG_FIRST = 559           # 09:19  protocol P1.3
SIG_LAST = 853            # 14:13  protocol P1.3 ("Wherever library.json says ... up to 14:29, read 14:13")

AMBIGUITIES = {
    "repo_snd_sweep_microbreak": [
        "A swing (major or minor) needs its full N candles on BOTH sides inside today's candles: the first N "
        "candles of the day can never be a swing ('today's candles only').",
        "'Most recent' swing = the one with the latest candle index among those confirmed before the candle "
        "being evaluated (confirmed = candle j+N completed, i.e. j+N <= c-1).",
        "MINOR swings are found on all of today's candles (also before the break and the touch); only the "
        "sweep / micro-break tests start at the touch candle (registrar note: 'the touch candle may itself be "
        "the sweep candle', which needs a minor swing confirmed before the touch).",
        "For the sweep and micro-break tests on candle c the 'most recent confirmed minor swing' is the one "
        "confirmed BEFORE candle c started (j+N <= c-1), the same wording the text uses for the major swing "
        "('confirmed before candle i'); the swing that candle c itself completes is not used on candle c.",
        "If one candle closes both above the last major swing high and below the last major swing low, it is "
        "read as a bullish break (the text lists bullish first). Not expected to occur.",
        "The zone search always looks at candles i-3, i-2, i-1 (the text's constant 3), also when "
        "major_swing_n is 2 or 5.",
        "The death test runs on every candle after i, before and after the touch, and is evaluated before the "
        "touch / sweep / micro-break tests of the same candle.",
        "A candle that is a sweep never signals, even when an older sweep already exists ('counts only as a "
        "sweep').",
        "If the first micro-break candle after a sweep ends after 14:13 the day has no signal (3-minute "
        "candles end on 09:17, 09:20, ..., 14:11, 14:14, so the last usable signal minute is 14:11).",
        "The break, zone and touch may happen at any time of day; only the signal candle is bound to "
        "09:19..14:13.",
    ],
    "repo_snd_zone_touch": [
        "Swing, 'most recent', bullish-first and zone conventions exactly as in repo_snd_sweep_microbreak.",
        "The death test of a candle is evaluated before its touch test: a candle that both fails the death "
        "test and touches the zone ends the day with no trade.",
        "entry_cutoff compares the START stamp of the 3-minute touch candle as a string 'HH:MM' < cutoff.",
        "The zone search always looks at candles i-3, i-2, i-1, also when swing_n is 2 or 5.",
    ],
    "repo_vpr_break_retest": [
        "Previous session = ctx.prev_sessions[-1] (the most recent earlier date in the index file; Sunday "
        "2026-02-01 counts).",
        "POC tie-break 'row nearest the session's (high+low)/2': distance is measured from the row's CENTRE "
        "(r + 0.5) to the midpoint; a remaining tie goes to the lower row.",
        "Value area: rows outside floor(session low)..floor(session high) do not exist ('side exhausted'); a "
        "row inside that range with 0 units is a normal row. The share test is area_units * 100 >= pct * "
        "total_units, checked after every addition (and once for the POC row alone); on a tie both rows are "
        "added before the test.",
        "Each arming candle B has at most one retest candle R (its first qualifying candle with k in the "
        "window). The day's signal is the earliest R over all arms. 5-minute candles end on 09:19, 09:24, "
        "..., 14:09, 14:14, so an R ending after 14:13 can only be followed by later R's: whether 'the "
        "earliest R must be in the window' or 'the earliest R that is in the window' is meant, the result "
        "is the same (last usable signal minute 14:09).",
        "Several arming candles may be open at once; an UP arm and a DOWN arm cannot both retest on the same "
        "candle (close > VAH and close < VAL exclude each other).",
        "The neighbour windows '3..6' and '4..15' are read as k_from..k_to inclusive, like the centre '4..7'.",
    ],
    "repo_vpr_reentry": [
        "Profile conventions exactly as in repo_vpr_break_retest.",
        "If a DOWN arm and an UP arm both retest on the same candle (a wide candle with high >= VAH, low <= "
        "VAL and close inside), the direction of the EARLIER arming candle is taken.",
        "The neighbour windows '3..6' and '4..10' are read as k_from..k_to inclusive.",
    ],
    "repo_atr_trail_ema_cross": [
        "The continuous series starts at the first session on disk at or after 2025-11-24 "
        "(ctx.prev_sessions[0]) and ends with today's last COMPLETED 5-minute candle.",
        "The first candle at which a cross can be tested is the one after the seed candle (both R(i) and "
        "R(i-1) must exist).",
        "In the seed-following candle the recursion needs close(i-2); it exists (the seed is at series index "
        "21), so no special case is needed.",
        "entry_window bounds are inclusive on the candle's last 1-minute bar, as written "
        "('11:29 <= m <= 13:24'); all three windows lie inside 09:19..14:13.",
    ],
}


# ---------------------------------------------------------------------------
# helpers (this module's own; nothing shared with other modules)
# ---------------------------------------------------------------------------
def n_minute_candles(bars, n):
    """Completed n-minute candles [start_minute, o, h, l, c] aligned to 09:15, from 1-minute bars
    [[hhmm, o, h, l, c], ...].  A candle is kept only if all n of its 1-minute bars are present."""
    slots = {}
    for b in bars:
        k = (C.minutes(b[0]) - OPEN_MIN) // n
        slots.setdefault(k, []).append(b)
    out = []
    k = 0
    while k in slots and len(slots[k]) == n:      # stop at the first missing / incomplete candle
        g = slots[k]
        out.append([OPEN_MIN + k * n, g[0][1], max(b[2] for b in g), min(b[3] for b in g), g[-1][4]])
        k += 1
    return out


def is_swing_high(cs, j, n):
    """Candle j's high strictly above the highs of the n candles before and the n after it."""
    if j < n or j + n >= len(cs):
        return False
    h = cs[j][2]
    return all(cs[x][2] < h for x in range(j - n, j + n + 1) if x != j)


def is_swing_low(cs, j, n):
    if j < n or j + n >= len(cs):
        return False
    lo = cs[j][3]
    return all(cs[x][3] > lo for x in range(j - n, j + n + 1) if x != j)


# ---------------------------------------------------------------------------
# supply / demand: the day's first break of structure and its zone
# ---------------------------------------------------------------------------
def snd_first_break(cs, swing_n):
    """(i, direction, zone_low, zone_high) of the day's first break of structure, or None.
    Uses candles 0..i only."""
    last_high = None      # high of the most recent swing high confirmed before the current candle
    last_low = None
    for i in range(len(cs)):
        # "confirmed once candle j+3 has completed" and "confirmed before candle i": j + n <= i - 1.
        j = i - 1 - swing_n
        if j >= 0:
            if is_swing_high(cs[:i], j, swing_n):
                last_high = cs[j][2]
            if is_swing_low(cs[:i], j, swing_n):
                last_low = cs[j][3]
        close = cs[i][4]
        # "(a) Break candle i = the first candle of the day whose close is above the high of the most recent
        #  major swing high confirmed before candle i (bullish) or below the low of the most recent confirmed
        #  major swing low (bearish). Only this first break counts."
        if last_high is not None and close > last_high:
            direction = "UP"
        elif last_low is not None and close < last_low:
            direction = "DOWN"
        else:
            continue
        # "(b) Zone = the latest opposite-coloured candle among candles i-3, i-2, i-1 (close < open for a
        #  bullish break, close > open for a bearish one) ... No such candle or width = 0: no trade today."
        for z in (i - 1, i - 2, i - 3):
            if z < 0:
                continue
            o, c = cs[z][1], cs[z][4]
            if (direction == "UP" and c < o) or (direction == "DOWN" and c > o):
                zone_low, zone_high = cs[z][3], cs[z][2]
                if zone_high - zone_low == 0:
                    return None
                return i, direction, zone_low, zone_high
        return None
    return None


def snd_dead(candle, direction, zone_low, zone_high):
    """"death test: bullish case close < zone low - 4 x width, bearish case close > zone high + 4 x width"."""
    width = zone_high - zone_low
    if direction == "UP":
        return candle[4] < zone_low - 4 * width
    return candle[4] > zone_high + 4 * width


def snd_touches(candle, zone_low, zone_high):
    """"low <= zone high AND high >= zone low"."""
    return candle[3] <= zone_high and candle[2] >= zone_low


def repo_snd_sweep_microbreak(ctx, major_swing_n=3, minor_swing_n=2):
    cs = n_minute_candles(ctx.bars, 3)           # "3-minute index candles ... aligned to 09:15 ... today's candles only"
    brk = snd_first_break(cs, major_swing_n)
    if brk is None:
        return None
    i, direction, zone_low, zone_high = brk

    minor_low = None      # low of the most recent minor swing low confirmed before the current candle
    minor_high = None
    touched = False
    sweep_exists = False
    for c in range(len(cs)):
        # "MINOR swing low / high = a candle whose low / high is strictly beyond those of the N candles each
        #  side (N = 2), confirmed once N candles after it have completed."
        j = c - 1 - minor_swing_n
        if j >= 0:
            if is_swing_low(cs[:c], j, minor_swing_n):
                minor_low = cs[j][3]
            if is_swing_high(cs[:c], j, minor_swing_n):
                minor_high = cs[j][2]
        if c <= i:
            continue
        candle = cs[c]
        # "(c) On every candle after i, in this order - death test ... ends the day with no trade."
        if snd_dead(candle, direction, zone_low, zone_high):
            return None
        # "(d) Touch = the first candle after i with low <= zone high AND high >= zone low."
        if not touched:
            if not snd_touches(candle, zone_low, zone_high):
                continue
            touched = True
        # "(e) From the touch candle onward (bullish case; mirror for bearish)"
        high, low, close = candle[2], candle[3], candle[4]
        if direction == "UP":
            # "A candle that trades below the low of the most recent confirmed minor swing low and closes back
            #  above that low is a sweep"
            is_sweep = minor_low is not None and low < minor_low and close > minor_low
            # "closes above the high of the most recent confirmed minor swing high"
            is_break = minor_high is not None and close > minor_high
        else:
            is_sweep = minor_high is not None and high > minor_high and close < minor_high
            is_break = minor_low is not None and close < minor_low
        if is_sweep:
            # "a newer sweep replaces an older one; a candle that is both a sweep and a micro break counts
            #  only as a sweep"
            sweep_exists = True
            continue
        # "After a sweep exists, the first LATER candle that closes above the high of the most recent confirmed
        #  minor swing high is the SIGNAL candle."
        if sweep_exists and is_break:
            m = candle[0] + 2                    # last 1-minute bar of the 3-minute candle
            if SIG_FIRST <= m <= SIG_LAST:
                return (C.hhmm(m), direction)
            return None                          # "First signal of the day only" - it fell outside the window
    return None


def repo_snd_zone_touch(ctx, swing_n=3, entry_cutoff="13:00"):
    cs = n_minute_candles(ctx.bars, 3)
    brk = snd_first_break(cs, swing_n)
    if brk is None:
        return None
    i, direction, zone_low, zone_high = brk
    for c in range(i + 1, len(cs)):
        candle = cs[c]
        # "On each candle after i, first the death test ... ends the day with no trade."
        if snd_dead(candle, direction, zone_low, zone_high):
            return None
        # "SIGNAL = the first later candle with low <= zone high AND high >= zone low, provided that candle
        #  STARTS before 13:00; a first touch by a candle starting at or after 13:00 ends the day with no trade."
        if snd_touches(candle, zone_low, zone_high):
            if not C.hhmm(candle[0]) < entry_cutoff:
                return None
            m = candle[0] + 2
            if SIG_FIRST <= m <= SIG_LAST:
                return (C.hhmm(m), direction)
            return None
    return None


# ---------------------------------------------------------------------------
# previous-session value area
# ---------------------------------------------------------------------------
_VA_CACHE: dict = {}      # (index, previous session, share pct) -> (VAL, VAH); earlier sessions only


def prev_value_area(ctx, share_pct):
    """(VAL, VAH) from the PREVIOUS session's time-weighted profile, or None."""
    if not ctx.prev_sessions:
        return None
    prev = ctx.prev_sessions[-1]
    key = (ctx.index, prev, share_pct)
    if key in _VA_CACHE:
        return _VA_CACHE[key]
    # "build that session's 5-minute candles (aligned to 09:15, 75 candles from its 1-minute candles)"
    cs = n_minute_candles(ctx.session(prev), 5)
    result = None
    if cs:
        # "Price rows are 1 index point wide (row r covers r to r+1). Each 5-minute candle adds one unit to
        #  every row from floor(low) to floor(high) inclusive."
        units = {}
        for c in cs:
            for r in range(int(c[3] // 1), int(c[2] // 1) + 1):
                units[r] = units.get(r, 0) + 1
        ses_high = max(c[2] for c in cs)
        ses_low = min(c[3] for c in cs)
        bottom, top = int(ses_low // 1), int(ses_high // 1)
        mid = (ses_high + ses_low) / 2.0
        # "POC = the row with the most units (tie: the row nearest the session's (high+low)/2, then the lower row)"
        best = max(units.values())
        poc = min((r for r in units if units[r] == best), key=lambda r: (abs(r + 0.5 - mid), r))
        total = sum(units.values())
        lo = hi = poc
        area = units[poc]
        # "start with the POC row; repeatedly compare the next row above the area with the next row below it
        #  and add the one with more units (tie: add both; one side exhausted: add the other) until the area
        #  holds at least 70% of all units."
        while area * 100 < share_pct * total:
            can_up, can_down = hi + 1 <= top, lo - 1 >= bottom
            if not can_up and not can_down:
                break
            up = units.get(hi + 1, 0) if can_up else None
            down = units.get(lo - 1, 0) if can_down else None
            if not can_down or (can_up and up > down):
                hi += 1
                area += up
            elif not can_up or down > up:
                lo -= 1
                area += down
            else:
                hi += 1
                lo -= 1
                area += up + down
        # "VAH = upper edge of the top row, VAL = lower edge of the bottom row, fixed all day."
        result = (float(lo), float(hi + 1))
    _VA_CACHE[key] = result
    return result


def repo_vpr_break_retest(ctx, retest_window_candles=(4, 7), value_area_share_pct=70):
    va = prev_value_area(ctx, value_area_share_pct)
    if va is None:
        return None
    val, vah = va
    k_from, k_to = retest_window_candles
    cs = n_minute_candles(ctx.bars, 5)           # "Today: 5-minute candles aligned to 09:15."
    arms = []                                    # (candle index of B, direction)
    for c in range(len(cs)):
        high, low, close = cs[c][2], cs[c][3], cs[c][4]
        # "Retest candle R for an UP arm = the first candle that is k candles after B, k from 4 to 7 inclusive,
        #  with low <= VAH AND close > VAH; for a DOWN arm, high >= VAL AND close < VAL. A close back inside
        #  between B and R does not cancel."
        for b, direction in arms:
            if not k_from <= c - b <= k_to:
                continue
            if direction == "UP":
                hit = low <= vah and close > vah
            else:
                hit = high >= val and close < val
            if hit:
                # "SIGNAL = the earliest retest candle R of the day across all arming candles"
                m = cs[c][0] + 4
                if SIG_FIRST <= m <= SIG_LAST:
                    return (C.hhmm(m), direction)
                return None
        # "Arming candle B: closes > VAH (arms UP) and is either today's first candle or the previous candle of
        #  today closed <= VAH; or closes < VAL (arms DOWN) and is either today's first candle or the previous
        #  candle of today closed >= VAL. Every such crossing arms."
        if close > vah and (c == 0 or cs[c - 1][4] <= vah):
            arms.append((c, "UP"))
        elif close < val and (c == 0 or cs[c - 1][4] >= val):
            arms.append((c, "DOWN"))
    return None


def repo_vpr_reentry(ctx, retest_window_candles=(4, 7), value_area_share_pct=70):
    va = prev_value_area(ctx, value_area_share_pct)
    if va is None:
        return None
    val, vah = va
    k_from, k_to = retest_window_candles
    cs = n_minute_candles(ctx.bars, 5)
    arms = []                                    # (candle index of A, direction), in arming order
    for c in range(len(cs)):
        high, low, close = cs[c][2], cs[c][3], cs[c][4]
        # "Retest candle R for a DOWN arm = the first candle that is k candles after A, k from 4 to 7 inclusive,
        #  with high >= VAH AND close < VAH; for an UP arm, low <= VAL AND close > VAL. Nothing between A and R
        #  cancels."
        for a, direction in arms:
            if not k_from <= c - a <= k_to:
                continue
            if direction == "DOWN":
                hit = high >= vah and close < vah
            else:
                hit = low <= val and close > val
            if hit:
                m = cs[c][0] + 4
                if SIG_FIRST <= m <= SIG_LAST:
                    return (C.hhmm(m), direction)
                return None
        # "Arming candle A (cannot be today's first candle): the previous candle of today closed > VAH and this
        #  candle closes < VAH (arms DOWN); or the previous candle closed < VAL and this candle closes > VAL
        #  (arms UP). Every such inward crossing arms."
        if c >= 1:
            prev_close = cs[c - 1][4]
            if prev_close > vah and close < vah:
                arms.append((c, "DOWN"))
            if prev_close < val and close > val:
                arms.append((c, "UP"))
    return None


# ---------------------------------------------------------------------------
# ATR trailing stop line crossed by EMA(5)
# ---------------------------------------------------------------------------
_C5_CACHE: dict = {}      # (index, earlier session) -> its 5-minute candles


def repo_atr_trail_ema_cross(ctx, atr_multiplier=3.0, entry_window=("11:29", "13:24")):
    ATR_PERIOD = 21       # "ATR = Wilder average, period 21"
    # "5-minute index candles, each session aligned to 09:15 (75 per session), kept as ONE continuous series
    #  across sessions from the first warm-up day 2025-11-24."
    series = []
    for d in ctx.prev_sessions:
        key = (ctx.index, d)
        if key not in _C5_CACHE:
            _C5_CACHE[key] = n_minute_candles(ctx.session(d), 5)
        series.extend(_C5_CACHE[key])
    today_from = len(series)
    series.extend(n_minute_candles(ctx.bars, 5))
    n = len(series)
    if n == today_from:
        return None
    w_from, w_to = C.minutes(entry_window[0]), C.minutes(entry_window[1])

    close = [c[4] for c in series]
    atr = [None] * n
    line = [None] * n     # the trailing line R
    ema = [None] * n
    tr_sum = 0.0
    for i in range(n):
        high, low = series[i][2], series[i][3]
        # "True range of candle i = max(high - low, |high - close(i-1)|, |low - close(i-1)|) (first candle:
        #  high - low)."
        if i == 0:
            tr = high - low
        else:
            tr = max(high - low, abs(high - close[i - 1]), abs(low - close[i - 1]))
        # "first value = simple mean of the first 21 true ranges, then ATR(i) = (ATR(i-1) x 20 + TR(i)) / 21."
        if i < ATR_PERIOD:
            tr_sum += tr
            if i == ATR_PERIOD - 1:
                atr[i] = tr_sum / ATR_PERIOD
        else:
            atr[i] = (atr[i - 1] * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
        # "Trailing line R (close-based, one candle lagged): offset(i) = ATR(i-1) x 3.0."
        if i >= 1 and atr[i - 1] is not None:
            offset = atr[i - 1] * atr_multiplier
            if line[i - 1] is None:
                # "Seed at the first candle where ATR(i-1) exists: R(i) = close(i-1) - offset(i)."
                line[i] = close[i - 1] - offset
            else:
                r1, c1, c2 = line[i - 1], close[i - 1], close[i - 2]
                # "if close(i-1) > R(i-1) and close(i-2) > R(i-1): R(i) = max(R(i-1), close(i-1) - offset(i));
                #  else if close(i-1) <= R(i-1) and close(i-2) <= R(i-1): R(i) = min(R(i-1), close(i-1) + offset(i));
                #  else if close(i-1) > R(i-1): R(i) = close(i-1) - offset(i); else R(i) = close(i-1) + offset(i)."
                if c1 > r1 and c2 > r1:
                    line[i] = max(r1, c1 - offset)
                elif c1 <= r1 and c2 <= r1:
                    line[i] = min(r1, c1 + offset)
                elif c1 > r1:
                    line[i] = c1 - offset
                else:
                    line[i] = c1 + offset
        # "EMA(i) = close(i) x 2/6 + EMA(i-1) x 4/6 (length 5), seeded with the first close of the series."
        ema[i] = close[i] if i == 0 else close[i] * 2.0 / 6.0 + ema[i - 1] * 4.0 / 6.0

    for i in range(max(today_from, 1), n):
        m = series[i][0] + 4                     # last 1-minute bar of the 5-minute candle
        # "the FIRST cross of the day on a 5-minute candle whose last 1-minute bar m satisfies
        #  11:29 <= m <= 13:24 ... Crosses outside that window neither fire nor cancel."
        if m < w_from or m < SIG_FIRST:
            continue
        if m > w_to or m > SIG_LAST:
            break
        if line[i] is None or line[i - 1] is None:
            continue
        # "UP cross at candle i: EMA(i) > R(i) AND EMA(i-1) <= R(i-1). DOWN cross: EMA(i) < R(i) AND
        #  EMA(i-1) >= R(i-1)."
        if ema[i] > line[i] and ema[i - 1] <= line[i - 1]:
            return (C.hhmm(m), "UP")
        if ema[i] < line[i] and ema[i - 1] >= line[i - 1]:
            return (C.hhmm(m), "DOWN")
    return None


# ---------------------------------------------------------------------------
# the candidate table
# ---------------------------------------------------------------------------
def _candidate(fn, centre, moves):
    """moves: [(param, label value, python value), ...] in the order lower, upper for each param."""
    return {"fn": fn, "centre": dict(centre),
            "neighbours": [{"label": f"{p}={shown}", "params": {**centre, p: v}} for p, shown, v in moves]}


CANDIDATES = {
    "repo_snd_sweep_microbreak": _candidate(
        repo_snd_sweep_microbreak, {"major_swing_n": 3, "minor_swing_n": 2},
        [("major_swing_n", "2", 2), ("major_swing_n", "5", 5),
         ("minor_swing_n", "1", 1), ("minor_swing_n", "3", 3)]),
    "repo_snd_zone_touch": _candidate(
        repo_snd_zone_touch, {"swing_n": 3, "entry_cutoff": "13:00"},
        [("swing_n", "2", 2), ("swing_n", "5", 5),
         ("entry_cutoff", "12:30", "12:30"), ("entry_cutoff", "13:30", "13:30")]),
    "repo_vpr_break_retest": _candidate(
        repo_vpr_break_retest, {"retest_window_candles": (4, 7), "value_area_share_pct": 70},
        [("retest_window_candles", "3..6", (3, 6)), ("retest_window_candles", "4..15", (4, 15)),
         ("value_area_share_pct", "65", 65), ("value_area_share_pct", "75", 75)]),
    "repo_vpr_reentry": _candidate(
        repo_vpr_reentry, {"retest_window_candles": (4, 7), "value_area_share_pct": 70},
        [("retest_window_candles", "3..6", (3, 6)), ("retest_window_candles", "4..10", (4, 10)),
         ("value_area_share_pct", "65", 65), ("value_area_share_pct", "75", 75)]),
    "repo_atr_trail_ema_cross": _candidate(
        repo_atr_trail_ema_cross, {"atr_multiplier": 3.0, "entry_window": ("11:29", "13:24")},
        [("atr_multiplier", "2.0", 2.0), ("atr_multiplier", "4.0", 4.0),
         ("entry_window", "10:59..12:54", ("10:59", "12:54")),
         ("entry_window", "11:59..13:54", ("11:59", "13:54"))]),
}


# ---------------------------------------------------------------------------
# self-run: signal counts and the mechanical look-ahead check (no outcome of any signal is looked at)
# ---------------------------------------------------------------------------
def _main() -> int:
    problems = []
    for index in C.INDEXES:
        market = C.Market(index)
        days = [d for d in market.sessions if C.WINDOW_START <= d <= C.DISCOVERY_END]
        print(f"\n===== {index}: {len(days)} sessions {days[0]} .. {days[-1]} =====")
        for cid, cand in CANDIDATES.items():
            cells = [("centre", cand["centre"])] + [(nb["label"], nb["params"]) for nb in cand["neighbours"]]
            for label, params in cells:
                sigs = []
                for d in days:
                    dc = market.day_ctx(d)
                    try:
                        problems.extend(f"{cid} [{label}] {p}" for p in C.check_no_lookahead(cand["fn"], dc, params))
                        r = cand["fn"](dc, **params)
                    except Exception as e:                   # noqa: BLE001 - reported, not hidden
                        problems.append(f"{cid} [{label}] {index} {d}: raised {type(e).__name__}: {e}")
                        continue
                    if r is not None:
                        sigs.append((d, r[0], r[1]))
                up = sum(1 for s in sigs if s[2] == "UP")
                ts = sorted(s[1] for s in sigs)
                print(f"  {cid:28s} {label:28s} n={len(sigs):3d}  UP={up:3d} DOWN={len(sigs) - up:3d}  "
                      f"earliest={ts[0] if ts else '-'} latest={ts[-1] if ts else '-'}")
    print(f"\nlook-ahead / exception problems: {len(problems)}")
    for p in problems[:40]:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(_main())
