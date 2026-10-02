"""signals_repo_b.py - five `existing_repo` candidates of library.json, coded from the rule text only.

    repo_snd_sweep_microbreak   repo_snd_zone_touch
    repo_vpr_break_retest       repo_vpr_reentry
    repo_atr_trail_ema_cross

Every function is fn(ctx: DayCtx, **params) -> None | (t, direction):
  t = "HH:MM" stamp of the LAST 1-minute bar of the signal candle (the fill bar is t+1),
  direction = "UP" (buy CE) or "DOWN" (buy PE).

Protocol P1.3 / P1.4 override the library's "09:19 <= m <= 14:29": a signal minute is 09:19 .. 14:13,
and a candle whose last minute is outside that window is never a signal candle.

No look-ahead by construction: N-minute candles are built only from 1-minute bars present in ctx.bars
and only when all N bars of the candle are there, and every scan walks forward and returns at the
first qualifying candle.  Earlier sessions are read whole (they are complete before today opens).

No option data, no VIX, no daily file, no weekday / expiry input is used by any of the five.
Nothing here looks at what happens after a signal.
"""
from __future__ import annotations

from math import floor

from ctx import hhmm, minutes

OPEN_MIN = 555            # 09:15, the alignment of every N-minute candle
SIG_FIRST = 559           # 09:19  (protocol P1.3)
SIG_LAST = 853            # 14:13  (protocol P1.3; replaces the library's 14:29)

O, H, L, C = 0, 1, 2, 3   # columns of an N-minute candle built here


# ---------------------------------------------------------------------------
# shared helpers (private to this module)
# ---------------------------------------------------------------------------
def _candles(bars: list, n: int) -> list:
    """Complete n-minute candles [(o, h, l, c), ...] aligned to 09:15 from 1-minute bars [[hhmm,o,h,l,c]].
    Candle k covers the minutes 555 + n*k .. 555 + n*k + n - 1.  A candle is built only when all its n
    bars are present with exactly the expected stamps; building stops at the first gap."""
    out = []
    k = 0
    while (k + 1) * n <= len(bars):
        chunk = bars[k * n:(k + 1) * n]
        if any(chunk[j][0] != hhmm(OPEN_MIN + k * n + j) for j in range(n)):
            break
        out.append((chunk[0][1], max(r[2] for r in chunk), min(r[3] for r in chunk), chunk[-1][4]))
        k += 1
    return out


def _last_minute(k: int, n: int) -> int:
    """Minute of day of the last 1-minute bar of n-minute candle k."""
    return OPEN_MIN + k * n + n - 1


def _is_swing_high(cs: list, j: int, n: int) -> bool:
    """Candle j's high is strictly above the highs of the n candles before and the n candles after it.
    Needs all 2n neighbours to exist (today's candles only)."""
    if j < n or j + n >= len(cs):
        return False
    h = cs[j][H]
    return all(h > cs[k][H] for k in range(j - n, j + n + 1) if k != j)


def _is_swing_low(cs: list, j: int, n: int) -> bool:
    if j < n or j + n >= len(cs):
        return False
    lo = cs[j][L]
    return all(lo < cs[k][L] for k in range(j - n, j + n + 1) if k != j)


# ---------------------------------------------------------------------------
# supply / demand: the first break of structure and its zone (shared by the two snd candidates)
# ---------------------------------------------------------------------------
ZONE_LOOKBACK = 3     # "among candles i-3, i-2, i-1"
DEATH_WIDTHS = 4.0    # "close < zone low - 4 x width ... close > zone high + 4 x width"


def _first_break_and_zone(cs: list, n: int):
    """(i, bullish, zone_low, zone_high) of the day's first break of structure, or None when there is
    no break among the candles given or the break has no usable zone (= no trade today)."""
    last_sh = None        # high of the most recent major swing high confirmed BEFORE the candle tested
    last_sl = None        # low of the most recent major swing low confirmed before it
    for i in range(len(cs)):
        # "confirmed once candle j+3 has completed" and "confirmed before candle i":
        # candle j+n must be candle i-1 or earlier, so the swing newly usable at candle i is j = i-1-n.
        j = i - 1 - n
        if j >= 0:
            if _is_swing_high(cs[:i], j, n):
                last_sh = cs[j][H]
            if _is_swing_low(cs[:i], j, n):
                last_sl = cs[j][L]
        close = cs[i][C]
        # "(a) Break candle i = the first candle of the day whose close is above the high of the most
        #  recent major swing high confirmed before candle i (bullish) or below the low of the most
        #  recent confirmed major swing low (bearish). Only this first break counts."
        if last_sh is not None and close > last_sh:
            bullish = True
        elif last_sl is not None and close < last_sl:
            bullish = False
        else:
            continue
        # "(b) Zone = the latest opposite-coloured candle among candles i-3, i-2, i-1 (close < open for
        #  a bullish break, close > open for a bearish one); zone low / zone high = that candle's low /
        #  high; width = high - low. No such candle or width = 0: no trade today."
        for k in range(i - 1, i - 1 - ZONE_LOOKBACK, -1):
            if k < 0:
                break
            opposite = cs[k][C] < cs[k][O] if bullish else cs[k][C] > cs[k][O]
            if opposite:
                zone_low, zone_high = cs[k][L], cs[k][H]
                if zone_high - zone_low == 0:
                    return None
                return i, bullish, zone_low, zone_high
        return None
    return None


def _dead(candle, bullish: bool, zone_low: float, zone_high: float) -> bool:
    """"death test: bullish case close < zone low - 4 x width, bearish case close > zone high + 4 x width,
    ends the day with no trade."""
    width = zone_high - zone_low
    if bullish:
        return candle[C] < zone_low - DEATH_WIDTHS * width
    return candle[C] > zone_high + DEATH_WIDTHS * width


def _touches(candle, zone_low: float, zone_high: float) -> bool:
    """"low <= zone high AND high >= zone low"."""
    return candle[L] <= zone_high and candle[H] >= zone_low


def snd_sweep_microbreak(ctx, major_swing_n=3, minor_swing_n=2):
    """repo_snd_sweep_microbreak - 3-minute candles of today only."""
    cs = _candles(ctx.bars, 3)                      # "3-minute index candles ... aligned to 09:15"
    found = _first_break_and_zone(cs, major_swing_n)
    if found is None:
        return None
    i, bullish, zone_low, zone_high = found
    n = minor_swing_n

    # MINOR swings are found on all of today's candles (registrar's note: "swings are found on today's
    # candles only", "the touch candle may itself be the sweep candle").  A minor swing at candle j is
    # "confirmed once N candles after it have completed", i.e. when candle j+n is complete.
    # "the most recent confirmed minor swing" of a candle c = the latest one confirmed BEFORE candle c
    # (candle j+n is candle c-1 or earlier) - the same meaning the text gives the phrase for the major
    # swing ("confirmed before candle i").  The swing that candle c itself completes (j = c-n) is not a
    # level for candle c; it becomes one from candle c+1.   [adjudication 2026-10-02, see AMBIGUITIES]
    last_minor_high = None      # high of the most recent minor swing high confirmed before the candle tested
    last_minor_low = None       # low of the most recent minor swing low confirmed before the candle tested
    for j in range(0, i - n):                       # everything confirmed before candle i (j+n <= i-1)
        if _is_swing_high(cs[:i], j, n):
            last_minor_high = cs[j][H]
        if _is_swing_low(cs[:i], j, n):
            last_minor_low = cs[j][L]

    touched = False
    have_sweep = False
    for c in range(i + 1, len(cs)):                 # "On every candle after i, in this order"
        m = _last_minute(c, 3)
        if m > SIG_LAST:                            # nothing after 14:13 can be a signal candle
            return None
        j = c - 1 - n                               # the minor swing confirmed by candle c-1 completing
        if j >= 0:
            if _is_swing_high(cs[:c], j, n):
                last_minor_high = cs[j][H]
            if _is_swing_low(cs[:c], j, n):
                last_minor_low = cs[j][L]
        candle = cs[c]
        if _dead(candle, bullish, zone_low, zone_high):      # (c) death test first
            return None
        if not touched:                                      # (d) "Touch = the first candle after i with ..."
            if not _touches(candle, zone_low, zone_high):
                continue
            touched = True
        # (e) "From the touch candle onward" (the touch candle itself included)
        if bullish:
            # "A candle that trades below the low of the most recent confirmed minor swing low and closes
            #  back above that low is a sweep (a newer sweep replaces an older one; a candle that is both a
            #  sweep and a micro break counts only as a sweep)."
            if last_minor_low is not None and candle[L] < last_minor_low and candle[C] > last_minor_low:
                have_sweep = True
                continue
            # "After a sweep exists, the first LATER candle that closes above the high of the most recent
            #  confirmed minor swing high is the SIGNAL candle."
            if have_sweep and last_minor_high is not None and candle[C] > last_minor_high:
                return (hhmm(m), "UP") if m >= SIG_FIRST else None
        else:                                                # "mirror for bearish"
            if last_minor_high is not None and candle[H] > last_minor_high and candle[C] < last_minor_high:
                have_sweep = True
                continue
            if have_sweep and last_minor_low is not None and candle[C] < last_minor_low:
                return (hhmm(m), "DOWN") if m >= SIG_FIRST else None
    return None


def snd_zone_touch(ctx, swing_n=3, entry_cutoff="13:00"):
    """repo_snd_zone_touch - 3-minute candles of today only; the first touch of the zone is the entry."""
    cs = _candles(ctx.bars, 3)
    found = _first_break_and_zone(cs, swing_n)
    if found is None:
        return None
    i, bullish, zone_low, zone_high = found
    cutoff = minutes(entry_cutoff)
    for c in range(i + 1, len(cs)):
        m = _last_minute(c, 3)
        if m > SIG_LAST:
            return None
        candle = cs[c]
        # "On each candle after i, first the death test"
        if _dead(candle, bullish, zone_low, zone_high):
            return None
        # "SIGNAL = the first later candle with low <= zone high AND high >= zone low, provided that candle
        #  STARTS before 13:00; a first touch by a candle starting at or after 13:00 ends the day with no trade."
        if _touches(candle, zone_low, zone_high):
            if OPEN_MIN + 3 * c >= cutoff or m < SIG_FIRST:
                return None
            return (hhmm(m), "UP" if bullish else "DOWN")
    return None


# ---------------------------------------------------------------------------
# previous-session value area (shared by the two vpr candidates)
# ---------------------------------------------------------------------------
_VA_CACHE: dict = {}      # (index, previous session, share) -> (VAH, VAL) | None; earlier sessions never change


def _value_area(ctx, share_pct):
    """(VAH, VAL) of the PREVIOUS session's time-weighted profile, or None when it cannot be built."""
    if not ctx.prev_sessions:
        return None
    prev = ctx.prev_sessions[-1]              # "Previous session" = the most recent earlier date on disk
    key = (ctx.index, prev, share_pct)
    if key in _VA_CACHE:
        return _VA_CACHE[key]
    # "build that session's 5-minute candles (aligned to 09:15, 75 candles from its 1-minute candles 09:15..15:29)"
    cs = _candles(ctx.session(prev), 5)
    if len(cs) != 75:
        _VA_CACHE[key] = None
        return None
    # "Price rows are 1 index point wide (row r covers r to r+1). Each 5-minute candle adds one unit to
    #  every row from floor(low) to floor(high) inclusive."
    units: dict = {}
    for c in cs:
        for r in range(floor(c[L]), floor(c[H]) + 1):
            units[r] = units.get(r, 0) + 1
    lowest, highest = min(units), max(units)
    total = sum(units.values())
    # "POC = the row with the most units (tie: the row nearest the session's (high+low)/2, then the lower row)."
    mid = (max(c[H] for c in cs) + min(c[L] for c in cs)) / 2.0
    top_units = max(units.values())
    poc = min((r for r in units if units[r] == top_units), key=lambda r: (abs(r + 0.5 - mid), r))
    # "Value area: start with the POC row; repeatedly compare the next row above the area with the next row
    #  below it and add the one with more units (tie: add both; one side exhausted: add the other) until the
    #  area holds at least 70% of all units."
    top = bottom = poc
    held = units[poc]
    while held * 100 < share_pct * total:
        up_ok, down_ok = top + 1 <= highest, bottom - 1 >= lowest
        if not up_ok and not down_ok:
            break
        up = units.get(top + 1, 0) if up_ok else None
        down = units.get(bottom - 1, 0) if down_ok else None
        if up is None:
            bottom -= 1
            held += down
        elif down is None:
            top += 1
            held += up
        elif up > down:
            top += 1
            held += up
        elif down > up:
            bottom -= 1
            held += down
        else:
            top += 1
            bottom -= 1
            held += up + down
    # "VAH = upper edge of the top row, VAL = lower edge of the bottom row, fixed all day."
    _VA_CACHE[key] = (float(top + 1), float(bottom))
    return _VA_CACHE[key]


def vpr_break_retest(ctx, retest_window_candles=(4, 7), value_area_share_pct=70):
    """repo_vpr_break_retest - break out of the previous session's value area, then a held retest."""
    va = _value_area(ctx, value_area_share_pct)
    if va is None:
        return None
    vah, val = va
    k_from, k_to = retest_window_candles
    cs = _candles(ctx.bars, 5)                      # "Today: 5-minute candles aligned to 09:15."
    arms = []                                       # (candle index of B, "UP" | "DOWN"), in time order
    for c in range(len(cs)):
        m = _last_minute(c, 5)
        if m > SIG_LAST:
            return None
        candle = cs[c]
        # "Retest candle R for an UP arm = the first candle that is k candles after B, k from 4 to 7
        #  inclusive, with low <= VAH AND close > VAH; for a DOWN arm, high >= VAL AND close < VAL.
        #  A close back inside between B and R does not cancel.
        #  SIGNAL = the earliest retest candle R of the day across all arming candles"
        if m >= SIG_FIRST:
            for b, direction in arms:
                if not k_from <= c - b <= k_to:
                    continue
                if direction == "UP" and candle[L] <= vah and candle[C] > vah:
                    return (hhmm(m), "UP")
                if direction == "DOWN" and candle[H] >= val and candle[C] < val:
                    return (hhmm(m), "DOWN")
        # "Arming candle B: closes > VAH (arms UP) and is either today's first candle or the previous candle
        #  of today closed <= VAH; or closes < VAL (arms DOWN) and is either today's first candle or the
        #  previous candle of today closed >= VAL. Every such crossing arms."
        if candle[C] > vah and (c == 0 or cs[c - 1][C] <= vah):
            arms.append((c, "UP"))
        if candle[C] < val and (c == 0 or cs[c - 1][C] >= val):
            arms.append((c, "DOWN"))
    return None


def vpr_reentry(ctx, retest_window_candles=(4, 7), value_area_share_pct=70):
    """repo_vpr_reentry - a failed break of the previous session's value area, re-entered and retested."""
    va = _value_area(ctx, value_area_share_pct)
    if va is None:
        return None
    vah, val = va
    k_from, k_to = retest_window_candles
    cs = _candles(ctx.bars, 5)
    arms = []                                       # (candle index of A, "UP" | "DOWN"), in time order
    for c in range(len(cs)):
        m = _last_minute(c, 5)
        if m > SIG_LAST:
            return None
        candle = cs[c]
        # "Retest candle R for a DOWN arm = the first candle that is k candles after A, k from 4 to 7
        #  inclusive, with high >= VAH AND close < VAH; for an UP arm, low <= VAL AND close > VAL.
        #  Nothing between A and R cancels. SIGNAL = the earliest retest candle R of the day across all
        #  arming candles"
        if m >= SIG_FIRST:
            for a, direction in arms:               # earliest arming candle first
                if not k_from <= c - a <= k_to:
                    continue
                if direction == "DOWN" and candle[H] >= vah and candle[C] < vah:
                    return (hhmm(m), "DOWN")
                if direction == "UP" and candle[L] <= val and candle[C] > val:
                    return (hhmm(m), "UP")
        # "Arming candle A (cannot be today's first candle): the previous candle of today closed > VAH and
        #  this candle closes < VAH (arms DOWN); or the previous candle closed < VAL and this candle closes
        #  > VAL (arms UP). Every such inward crossing arms."
        if c >= 1:
            if cs[c - 1][C] > vah and candle[C] < vah:
                arms.append((c, "DOWN"))
            if cs[c - 1][C] < val and candle[C] > val:
                arms.append((c, "UP"))
    return None


# ---------------------------------------------------------------------------
# ATR Trailing Stops line crossed by the EMA, on one continuous 5-minute series
# ---------------------------------------------------------------------------
ATR_PERIOD = 21           # "ATR = Wilder average, period 21"
# EMA: "EMA(i) = close(i) x 2/6 + EMA(i-1) x 4/6 (length 5), seeded with the first close of the series."

_ATR_START = (0, 0.0, None, None, None, None, None)
# indicator state after candle i of the continuous series:
#   (candles seen, sum of the first true ranges, ATR(i), close(i), close(i-1), R(i), EMA(i))
_ATR_CACHE: dict = {}     # (index, first session of the series, multiplier) -> {session: state at its end}


def _atr_step(state, candle, mult):
    """Advance the indicators by one 5-minute candle; returns the new state."""
    count, tr_sum, atr, c1, c2, line, ema = state
    h, lo, close = candle[H], candle[L], candle[C]
    # "True range of candle i = max(high - low, |high - close(i-1)|, |low - close(i-1)|) (first candle: high - low)."
    if count == 0:
        tr = h - lo
        new_ema = close
    else:
        tr = max(h - lo, abs(h - c1), abs(lo - c1))
        new_ema = close * 2 / 6 + ema * 4 / 6
    # "Trailing line R (close-based, one candle lagged): offset(i) = ATR(i-1) x 3.0. Seed at the first candle
    #  where ATR(i-1) exists: R(i) = close(i-1) - offset(i). Afterwards: if close(i-1) > R(i-1) and close(i-2) >
    #  R(i-1): R(i) = max(R(i-1), close(i-1) - offset(i)); else if close(i-1) <= R(i-1) and close(i-2) <= R(i-1):
    #  R(i) = min(R(i-1), close(i-1) + offset(i)); else if close(i-1) > R(i-1): R(i) = close(i-1) - offset(i);
    #  else R(i) = close(i-1) + offset(i)."
    if atr is None:
        new_line = None
    else:
        offset = atr * mult
        if line is None:
            new_line = c1 - offset
        elif c1 > line and c2 > line:
            new_line = max(line, c1 - offset)
        elif c1 <= line and c2 <= line:
            new_line = min(line, c1 + offset)
        elif c1 > line:
            new_line = c1 - offset
        else:
            new_line = c1 + offset
    # "first value = simple mean of the first 21 true ranges, then ATR(i) = (ATR(i-1) x 20 + TR(i)) / 21."
    if count < ATR_PERIOD - 1:
        tr_sum += tr
        new_atr = None
    elif count == ATR_PERIOD - 1:
        tr_sum += tr
        new_atr = tr_sum / ATR_PERIOD
    else:
        new_atr = (atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
    return (count + 1, tr_sum, new_atr, close, c1, new_line, new_ema)


def _atr_state_before_today(ctx, mult):
    """State of the continuous series at the end of the previous session ("kept as ONE continuous series
    across sessions from the first warm-up day"): every earlier session on disk, each as its complete
    5-minute candles.  The end-of-session states are cached; earlier sessions never change."""
    prev = ctx.prev_sessions
    if not prev:
        return _ATR_START
    cache = _ATR_CACHE.setdefault((ctx.index, prev[0], mult), {})
    start = len(prev)
    while start > 0 and prev[start - 1] not in cache:
        start -= 1
    state = cache[prev[start - 1]] if start > 0 else _ATR_START
    for d in prev[start:]:
        for candle in _candles(ctx.session(d), 5):
            state = _atr_step(state, candle, mult)
        cache[d] = state
    return state


def atr_trail_ema_cross(ctx, atr_multiplier=3.0, entry_window=("11:29", "13:24")):
    """repo_atr_trail_ema_cross - first cross of the day inside the entry window."""
    first = max(minutes(entry_window[0]), SIG_FIRST)
    last = min(minutes(entry_window[1]), SIG_LAST)
    state = _atr_state_before_today(ctx, atr_multiplier)
    for k, candle in enumerate(_candles(ctx.bars, 5)):
        m = _last_minute(k, 5)
        if m > last:
            return None
        prev_line, prev_ema = state[5], state[6]
        state = _atr_step(state, candle, atr_multiplier)
        line, ema = state[5], state[6]
        # "Crosses outside that window neither fire nor cancel."
        if m < first or line is None or prev_line is None:
            continue
        # "UP cross at candle i: EMA(i) > R(i) AND EMA(i-1) <= R(i-1). DOWN cross: EMA(i) < R(i) AND
        #  EMA(i-1) >= R(i-1). SIGNAL = the FIRST cross of the day on a 5-minute candle whose last 1-minute
        #  bar m satisfies 11:29 <= m <= 13:24"
        if ema > line and prev_ema <= prev_line:
            return (hhmm(m), "UP")
        if ema < line and prev_ema >= prev_line:
            return (hhmm(m), "DOWN")
    return None


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------
def _neighbours(centre: dict, moves: list) -> list:
    """moves = [(param, label value, value), ...] in library order (lower then upper per param);
    each neighbour is the FULL centre dict with ONE value moved."""
    out = []
    for param, text, value in moves:
        params = dict(centre)
        params[param] = value
        out.append({"label": f"{param}={text}", "params": params})
    return out


_C_SWEEP = {"major_swing_n": 3, "minor_swing_n": 2}
_C_TOUCH = {"swing_n": 3, "entry_cutoff": "13:00"}
_C_RETEST = {"retest_window_candles": (4, 7), "value_area_share_pct": 70}
_C_REENTRY = {"retest_window_candles": (4, 7), "value_area_share_pct": 70}
_C_ATR = {"atr_multiplier": 3.0, "entry_window": ("11:29", "13:24")}

CANDIDATES = {
    "repo_snd_sweep_microbreak": {
        "fn": snd_sweep_microbreak,
        "centre": _C_SWEEP,
        "neighbours": _neighbours(_C_SWEEP, [
            ("major_swing_n", "2", 2), ("major_swing_n", "5", 5),
            ("minor_swing_n", "1", 1), ("minor_swing_n", "3", 3)]),
    },
    "repo_snd_zone_touch": {
        "fn": snd_zone_touch,
        "centre": _C_TOUCH,
        "neighbours": _neighbours(_C_TOUCH, [
            ("swing_n", "2", 2), ("swing_n", "5", 5),
            ("entry_cutoff", "12:30", "12:30"), ("entry_cutoff", "13:30", "13:30")]),
    },
    "repo_vpr_break_retest": {
        "fn": vpr_break_retest,
        "centre": _C_RETEST,
        "neighbours": _neighbours(_C_RETEST, [
            ("retest_window_candles", "3..6", (3, 6)), ("retest_window_candles", "4..15", (4, 15)),
            ("value_area_share_pct", "65", 65), ("value_area_share_pct", "75", 75)]),
    },
    "repo_vpr_reentry": {
        "fn": vpr_reentry,
        "centre": _C_REENTRY,
        "neighbours": _neighbours(_C_REENTRY, [
            ("retest_window_candles", "3..6", (3, 6)), ("retest_window_candles", "4..10", (4, 10)),
            ("value_area_share_pct", "65", 65), ("value_area_share_pct", "75", 75)]),
    },
    "repo_atr_trail_ema_cross": {
        "fn": atr_trail_ema_cross,
        "centre": _C_ATR,
        "neighbours": _neighbours(_C_ATR, [
            ("atr_multiplier", "2.0", 2.0), ("atr_multiplier", "4.0", 4.0),
            ("entry_window", "10:59..12:54", ("10:59", "12:54")),
            ("entry_window", "11:59..13:54", ("11:59", "13:54"))]),
    },
}

AMBIGUITIES = {
    "repo_snd_sweep_microbreak": [
        "Signal minute bound: the text's 14:29 is read as 14:13 (protocol P1.3). A signal candle whose last "
        "minute is after 14:13 is no signal, so the scan stops there; the last usable 3-minute candle is "
        "14:09-14:11.",
        "A swing needs all of its N candles on BOTH sides to exist among today's candles, so the first N "
        "candles of the day can never be a swing (no candle from the previous session is used).",
        "MAJOR swing 'confirmed before candle i' is read as: candle j+n is candle i-1 or earlier.",
        "MINOR swing 'the most recent confirmed minor swing low / high' of a candle c is read as the latest one "
        "confirmed BEFORE candle c: candle j+N is candle c-1 or earlier (j <= c-1-N). The swing that candle c "
        "itself completes (j = c-N) is not a level for candle c; it is one from candle c+1. Reasons, all from "
        "the text: (1) step (a) defines the phrase for the major swing as 'confirmed before candle i' and "
        "uses the bare 'most recent confirmed ... swing low' as its shorthand in the same sentence; step (e) "
        "uses that same bare phrase; (2) a swing is 'confirmed once N candles after it have completed', and "
        "while candle c 'trades below' a level candle c has not completed. The other reading (confirmed by "
        "the time candle c has completed, j <= c-N; the first version of this file) is possible because (e) "
        "does not repeat the word 'before'; it was dropped in the adjudication of 2026-10-02 "
        "(check/adjudication_repo_b.md). It gave a different answer on 32 of 800 session-cells of this "
        "candidate (centre: NIFTY 1 day, SENSEX 2 days); no result of any signal was looked at.",
        "Minor swings are found on all of today's candles, also those before the touch (registrar's note: the "
        "touch candle may itself be the sweep candle); 'from the touch candle onward' limits which candles can "
        "be a sweep or the signal candle, not which candles can be swings.",
        "The death test runs on every candle after i, before and after the touch, and is checked first on each "
        "candle (also on the touch candle and on a would-be signal candle).",
        "'Trades below the low' = candle low < that low (strict); 'closes back above' = close > that low (strict).",
        "A candle that qualifies as a sweep is never the signal candle, also when an older sweep already "
        "exists ('counts only as a sweep'); the signal candle is the first later non-sweep candle closing "
        "beyond the most recent confirmed minor swing on the other side, that level being the one in force at "
        "that candle (it may be a swing from before the touch or before the sweep).",
        "If one candle closes both above the last major swing high and below the last major swing low, it is "
        "taken as a bullish break (the order of the text). Believed impossible in practice.",
        "The zone search always uses candles i-3, i-2, i-1 (the text's fixed 3), whatever major_swing_n is.",
        "The break, the zone, the touch and the sweep may occur at any time from 09:15; only the signal candle "
        "is bound to 09:19..14:13.",
    ],
    "repo_snd_zone_touch": [
        "Signal minute bound 14:29 read as 14:13 (protocol P1.3); it never binds because the touch candle must "
        "start before the entry cutoff (13:30 at most).",
        "Swings need N candles on both sides among today's candles; 'confirmed before i' = candle j+n is "
        "candle i-1 or earlier (same as in repo_snd_sweep_microbreak).",
        "The death test is checked before the touch test on the same candle: a candle that both touches the "
        "zone and fails the death test (a long candle that passes through the zone and closes more than 4 "
        "widths beyond it) ends the day with no trade.",
        "The zone search always uses candles i-3, i-2, i-1, whatever swing_n is.",
        "entry_cutoff compares the START minute of the touch candle (09:15 + 3k) strictly: start < cutoff.",
    ],
    "repo_vpr_break_retest": [
        "Signal minute bound 14:29 read as 14:13 (protocol P1.3): the last usable 5-minute candle is "
        "14:05-14:09. Arming candles may be any candle of the day from 09:15 (the first candle's last minute, "
        "09:19, is itself admissible).",
        "POC tie-break 'the row nearest the session's (high+low)/2': the distance is measured from the row's "
        "centre (r + 0.5); remaining ties go to the lower row. Session high / low are those of the previous "
        "session's 09:15..15:29 candles.",
        "Value area growth: the test 'holds at least X% of all units' is made after each step (a tie step adds "
        "both rows before the test). 'One side exhausted' = the next row lies outside the previous session's "
        "floor(low)..floor(high) rows. The comparison is exact in integers: held x 100 >= share x total.",
        "floor() is the mathematical floor of the price (rows are integer index points).",
        "'The first candle that is k candles after B': candle index of R minus candle index of B = k, counted "
        "in today's 5-minute candles.",
        "If the previous session does not give 75 complete 5-minute candles there is no profile and no signal "
        "(does not occur on disk).",
    ],
    "repo_vpr_reentry": [
        "Same profile, POC tie-break, value-area growth and 14:13 bound as repo_vpr_break_retest.",
        "A close exactly equal to VAH / VAL neither arms nor is 'outside': the text's strict > and < are used "
        "on both the previous and the arming candle.",
        "If one candle is the retest of a DOWN arm and of an UP arm at once (only possible when it spans the "
        "whole value area), the direction of the earlier arming candle is taken.",
    ],
    "repo_atr_trail_ema_cross": [
        "The continuous series is every session on disk before today (from 2025-11-24, including the Sunday "
        "session 2026-02-01), 75 five-minute candles each, followed by today's completed candles; candle "
        "indexes i-1, i-2 run across the session boundary.",
        "ATR(i) first exists at the 21st candle of the series (index 20), so R is seeded at index 21 and a "
        "cross needs R(i-1), i.e. index >= 22; all of that lies in the first warm-up morning.",
        "EMA is computed as close*2/6 + previous*4/6 in that order of operations.",
        "The entry window bounds are also clipped to 09:19..14:13 (no effect at the centre or the neighbours).",
        "A cross is tested with the values of consecutive series candles, so the candle before today's first "
        "candle is the last candle of the previous session (irrelevant inside the 11:29..13:24 window).",
    ],
}
