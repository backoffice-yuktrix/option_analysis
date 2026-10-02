"""signals_ctx.py - the "context" group of library candidates, coded to the letter of library.json
("signal" field) as overridden by protocol.md (P1 and both addenda).

Candidates here:
    vol_vix_confirmed_or_break   opening-range break confirmed by India VIX
    gap_fail_through_pc          failed gap: B-minute close through the previous house close
    spx_cue_confirmed            overnight S&P 500 cue confirmed by the first N minutes
    atm_oi_writer_skew           first-hour at-the-money open-interest skew (Addendum 2 applied)

Every function is fn(ctx: DayCtx, **params) -> None | (t, direction):
    t = "HH:MM" stamp of the signal minute (the last 1-minute bar of the signal candle; fill bar = t+1),
    "09:19" <= t <= "14:13" (protocol P1.3 - wherever the library says 14:29, read 14:13),
    direction = "UP" (buy CE) or "DOWN" (buy PE).
A function scans forward and returns at the FIRST qualifying minute; it only ever reads candles stamped
at or before the minute it is evaluating, and returns None (never raises) on a day it cannot evaluate.

Run this file to print the signal counts and the look-ahead check on the discovery sessions
(no profit or loss, no forward price is ever computed here).
"""
from __future__ import annotations

OPEN_MIN = 555            # 09:15
FIRST_SIGNAL_MIN = 559    # 09:19  (protocol P1.3)
LAST_SIGNAL_MIN = 853     # 14:13  (protocol P1.3)
FIRST_OPT_VIX_MIN = 560   # 09:20  (protocol P1.7: "No option price or India VIX value from bars stamped before 09:20")


# ---------------------------------------------------------------------------
# small helpers (private to this module)
# ---------------------------------------------------------------------------
def _hm(m: int) -> str:
    """555 -> "09:15" """
    return f"{m // 60:02d}:{m % 60:02d}"


def _mins(s: str) -> int:
    """ "09:15" -> 555 """
    return int(s[:2]) * 60 + int(s[3:5])


def _by_stamp(rows) -> dict:
    """{ "HH:MM": row } for exact-minute lookups."""
    return {r[0]: r for r in rows}


def _latest_at_or_before(rows, lo_min: int, hi_min: int):
    """The latest row stamped within lo_min..hi_min (inclusive), or None.  Rows are ascending."""
    lo, hi = _hm(lo_min), _hm(hi_min)
    found = None
    for r in rows:
        if r[0] > hi:
            break
        if r[0] >= lo:
            found = r
    return found


# ---------------------------------------------------------------------------
# vol_vix_confirmed_or_break
# ---------------------------------------------------------------------------
def vol_vix_confirmed_or_break(ctx, R_opening_range_minutes=15):
    R = int(R_opening_range_minutes)
    by = _by_stamp(ctx.bars)

    # "ORH / ORL = highest high / lowest low of the index's first R 1-minute candles (R = 15: 09:15..09:29)."
    or_rows = [by.get(_hm(OPEN_MIN + i)) for i in range(R)]
    if any(r is None for r in or_rows):
        return None                                   # opening range not complete (yet)
    orh = max(r[2] for r in or_rows)
    orl = min(r[3] for r in or_rows)

    # "VIX_PREV = house daily close of VIX for the previous session (average of (h+l+c)/3 over its VIX
    #  candles 15:00..15:29; if that window is empty, the last VIX close of that session)."
    # notes: "Previous session" is the most recent earlier date in the index candle file.
    if not ctx.prev_sessions:
        return None
    prev_vix = ctx.vix_session(ctx.prev_sessions[-1])
    if not prev_vix:
        return None
    tp = [(r[2] + r[3] + r[4]) / 3.0 for r in prev_vix if "15:00" <= r[0] <= "15:29"]
    if tp:
        vix_prev = sum(tp) / len(tp)
    else:
        # protocol P1.7 ("No ... India VIX value from bars stamped before 09:20") has no "today only"
        # qualifier, so the fallback close may not come from a bar stamped before 09:20 either.
        usable = [r for r in prev_vix if r[0] >= _hm(FIRST_OPT_VIX_MIN)]
        if not usable:
            return None
        vix_prev = usable[-1][4]

    # protocol P1.7: no India VIX value from bars stamped before 09:20.
    vix_rows = [r for r in ctx.vix() if r[0] >= _hm(FIRST_OPT_VIX_MIN)]

    # "VIX_OR = VIX close of the last opening-range minute (09:29), or the latest VIX close earlier today
    #  if that candle is missing."
    last_or_min = OPEN_MIN + R - 1
    row = _latest_at_or_before(vix_rows, FIRST_OPT_VIX_MIN, last_or_min)
    if row is None:
        return None
    vix_or = row[4]

    # "For each completed 1-minute candle stamped t from 09:15+R to 14:29" (protocol: 14:13)
    k = 0                                             # vix_rows[:k] are stamped <= t
    vix_t = None
    for m in range(max(OPEN_MIN + R, FIRST_SIGNAL_MIN), LAST_SIGNAL_MIN + 1):
        t = _hm(m)
        # "VIX_t = VIX close at t (or the latest VIX close today at or before t; none means skip the minute)."
        while k < len(vix_rows) and vix_rows[k][0] <= t:
            vix_t = vix_rows[k][4]
            k += 1
        bar = by.get(t)
        if bar is None:
            if ctx.bars and ctx.bars[-1][0] < t:
                return None                           # the day (as visible) ends here
            continue
        if vix_t is None:
            continue
        # "Gate: VIX_t > VIX_PREV AND VIX_t > VIX_OR."
        if not (vix_t > vix_prev and vix_t > vix_or):
            continue
        # "SIGNAL = the FIRST minute t where the gate holds AND the index close(t) > ORH (UP) or < ORL (DOWN)."
        if bar[4] > orh:
            return (t, "UP")
        if bar[4] < orl:
            return (t, "DOWN")
    return None


# ---------------------------------------------------------------------------
# gap_fail_through_pc
# ---------------------------------------------------------------------------
def gap_fail_through_pc(ctx, bar_minutes=15):
    B = int(bar_minutes)
    by = _by_stamp(ctx.bars)

    # "PC = house daily close of the previous session (average of (h+l+c)/3 over its 1-minute candles 15:00..15:29)."
    if not ctx.prev_sessions:
        return None
    try:
        pc = ctx.house_close(ctx.prev_sessions[-1])
    except (ValueError, KeyError):
        return None

    # "O = open of today's 09:15 1-minute candle. G = O - PC; G = 0 means no trade."
    first = by.get("09:15")
    if first is None:
        return None
    g = first[1] - pc
    if g == 0:
        return None

    # "Build B-minute candles aligned to 09:15 (B = 15: 09:15-09:29, 09:30-09:44, ...). Only candles whose
    #  last minute t satisfies 09:19 <= t <= 14:29 are examined."  (protocol: 14:13)
    start = OPEN_MIN
    while True:
        m = start + B - 1                             # the candle's last 1-minute bar = the signal minute
        if m > LAST_SIGNAL_MIN:
            return None
        if m >= FIRST_SIGNAL_MIN:
            t = _hm(m)
            last = by.get(t)                          # the candle's close = the close of its last 1-minute bar
            if last is None:
                if ctx.bars and ctx.bars[-1][0] < t:
                    return None                       # candle not complete (yet)
            else:
                close = last[4]
                # "SIGNAL = the FIRST such candle whose close is on the opposite side of PC from the open:
                #  G > 0 and close < PC (DOWN), or G < 0 and close > PC (UP)."
                if g > 0 and close < pc:
                    return (t, "DOWN")
                if g < 0 and close > pc:
                    return (t, "UP")
        start += B


# ---------------------------------------------------------------------------
# spx_cue_confirmed
# ---------------------------------------------------------------------------
def spx_cue_confirmed(ctx, confirm_minutes=15):
    N = int(confirm_minutes)

    # "S&P 500 daily rows: take the most recent row dated strictly BEFORE today's Indian date (never a row
    #  dated today)."   ctx.daily() already holds only rows dated strictly before ctx.day.
    rows = ctx.daily("GSPC")
    if len(rows) < 2 or not ctx.prev_sessions:
        return None                                   # "a missing row means no trade"
    cue, before = rows[-1], rows[-2]

    # "It is usable only if its date is on or after the date of the previous Indian session (otherwise the
    #  cue was already traded on: no trade)."
    if cue[0] < ctx.prev_sessions[-1]:
        return None

    # "R = that row's close / the close of the S&P row before it - 1. R = 0 or a missing row means no trade."
    if not before[4]:
        return None
    r = cue[4] / before[4] - 1.0
    if r == 0:
        return None

    # "O = open of today's index 09:15 candle; C = close of the candle stamped 09:15 + N - 1 with N = 15 (09:29)."
    m = OPEN_MIN + N - 1
    if not FIRST_SIGNAL_MIN <= m <= LAST_SIGNAL_MIN:
        return None
    t = _hm(m)
    by = _by_stamp(ctx.bars)
    first, last = by.get("09:15"), by.get(t)
    if first is None or last is None:
        return None
    o, c = first[1], last[4]

    # "SIGNAL at t = 09:29 (fill in the 09:30 bar) if R > 0 and C > O (UP), or R < 0 and C < O (DOWN).
    #  Otherwise no trade."
    if r > 0 and c > o:
        return (t, "UP")
    if r < 0 and c < o:
        return (t, "DOWN")
    return None


# ---------------------------------------------------------------------------
# atm_oi_writer_skew   (protocol Addendum 2 applied)
# ---------------------------------------------------------------------------
def atm_oi_writer_skew(ctx, eval_minutes=60, strikes_each_side=1):
    V = int(eval_minutes)
    J = int(strikes_each_side)
    step = ctx.step

    # "T = 09:15 + V - 1 with V = 60 (10:14)."  One evaluation per day, the signal is at T.
    T = OPEN_MIN + V - 1
    if not FIRST_SIGNAL_MIN <= T <= LAST_SIGNAL_MIN:
        return None
    t = _hm(T)
    by = _by_stamp(ctx.bars)
    first, bar_t = by.get("09:15"), by.get(t)
    if first is None or bar_t is None:
        return None                                   # the candle stamped T is not complete (yet)

    # "Contract = the expiry the house rule would trade today."  ctx.option() resolves the P2 expiry.
    if ctx.expiry is None:
        return None

    # "K0 = listed strike nearest the close of the index 09:15 candle (step 50 NIFTY, 100 SENSEX; tie goes
    #  to the lower strike)."   Addendum 2: "the strike K0 is still taken from the index 09:15 close".
    c0 = first[4]
    lower = (c0 // step) * step
    upper = lower + step
    k0 = lower if (c0 - lower) <= (upper - c0) else upper

    # "Strike set S = K0 plus the J = 1 listed strikes directly above and directly below it, fixed for the day."
    strikes = [k0 + j * step for j in range(-J, J + 1)]

    # protocol P1.8: "may read only contracts of the P2 expiry at strikes within +-5 strike steps of the
    #  at-the-money strike at minute t ... A needed strike with no file or no bar makes that minute 'no signal'."
    atm_t = float(round(bar_t[4] / step) * step)
    if any(abs(k - atm_t) > 5 * step for k in strikes):
        return None

    # Addendum 2: "its baseline is the 09:20 candle (not 09:15) ... the later reading is the candle stamped
    #  T-3 (3 completed minutes of lag) with the signal still at T. 'Latest candle at or before m' lookups
    #  stay as written but may not reach back before 09:20."
    base_min = FIRST_OPT_VIX_MIN
    late_min = T - 3
    if late_min < base_min:
        return None

    # "OI_PE(m) / OI_CE(m) = sum over S of the open interest in each option's 1-minute candle at minute m
    #  (the latest candle of today at or before m)."
    sums = {"PE": [0, 0], "CE": [0, 0]}               # [OI at the baseline, OI at the later reading]
    for ot in ("PE", "CE"):
        for k in strikes:
            rows = ctx.option(ot, k)
            if rows is None:
                return None
            base = _latest_at_or_before(rows, base_min, base_min)
            late = _latest_at_or_before(rows, base_min, late_min)
            # "Skip the day if any CE or PE in S has no candle today at or before 09:15 or at or before T,
            #  or has zero open interest at either point."   (09:15 -> 09:20, T -> T-3 by Addendum 2)
            if base is None or late is None:
                return None
            if base[6] == 0 or late[6] == 0:
                return None
            sums[ot][0] += base[6]
            sums[ot][1] += late[6]

    # "D = [OI_PE(T) - OI_PE(09:15)] - [OI_CE(T) - OI_CE(09:15)]."
    d = (sums["PE"][1] - sums["PE"][0]) - (sums["CE"][1] - sums["CE"][0])

    # "SIGNAL at T (fill in bar T+1, 10:15): D > 0 is UP, D < 0 is DOWN, D = 0 is no trade."
    if d > 0:
        return (t, "UP")
    if d < 0:
        return (t, "DOWN")
    return None


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------
def _neighbours(centre: dict, moves: list) -> list:
    """moves = [(param, lower, upper), ...] in library order -> one-at-a-time neighbours, lower then upper."""
    out = []
    for name, lower, upper in moves:
        for value in (lower, upper):
            params = dict(centre)
            params[name] = value
            out.append({"label": f"{name}={value}", "params": params})
    return out


CANDIDATES = {
    "vol_vix_confirmed_or_break": {
        "fn": vol_vix_confirmed_or_break,
        "centre": {"R_opening_range_minutes": 15},
        "neighbours": _neighbours({"R_opening_range_minutes": 15}, [("R_opening_range_minutes", 10, 30)]),
    },
    "gap_fail_through_pc": {
        "fn": gap_fail_through_pc,
        "centre": {"bar_minutes": 15},
        "neighbours": _neighbours({"bar_minutes": 15}, [("bar_minutes", 5, 30)]),
    },
    "spx_cue_confirmed": {
        "fn": spx_cue_confirmed,
        "centre": {"confirm_minutes": 15},
        "neighbours": _neighbours({"confirm_minutes": 15}, [("confirm_minutes", 10, 30)]),
    },
    "atm_oi_writer_skew": {
        "fn": atm_oi_writer_skew,
        "centre": {"eval_minutes": 60, "strikes_each_side": 1},
        "neighbours": _neighbours({"eval_minutes": 60, "strikes_each_side": 1},
                                  [("eval_minutes", 30, 90), ("strikes_each_side", 0, 2)]),
    },
}


AMBIGUITIES = {
    "vol_vix_confirmed_or_break": [
        "Scan window: t runs from 09:15+R to 14:13 (protocol P1.3 replaces the text's 14:29).",
        "Protocol P1.7 forbids VIX values from bars stamped before 09:20, so every VIX lookup of today "
        "('VIX close at 09:29 or the latest earlier today', 'latest VIX close today at or before t') only "
        "reaches back to the 09:20 VIX candle. If no VIX candle exists in 09:20..last opening-range minute, "
        "VIX_OR is undefined and the day has no signal.",
        "The 'latest VIX close today at or before t' fallback for VIX_t may be a candle inside the opening "
        "range (even the VIX_OR candle itself, in which case the gate VIX_t > VIX_OR is simply false).",
        "'Previous session' for VIX_PREV is the previous date of the INDEX candle file (registrar's notes); "
        "if VIX has no candle at all on that date the day has no signal (no reach-back to an older VIX day).",
        "VIX_PREV fallback ('if that window is empty, the last VIX close of that session'): protocol P1.7 is "
        "applied to it as well, so it is the last VIX close of that session stamped 09:20 or later; none means "
        "no signal. Added at adjudication (check/adjudication_ctx.md); the branch is never reached on disk - "
        "every VIX session has all 30 candles 15:00..15:29.",
        "Gate and break tests are strict (>, <) as written; a close equal to ORH / ORL or a VIX equal to "
        "VIX_PREV / VIX_OR is not a signal.",
        "The opening range needs all R index candles 09:15..09:15+R-1; a missing one means no signal that day "
        "(never happens on disk: every session has 375 bars).",
        "A minute whose index candle is missing is skipped (never happens on disk).",
    ],
    "gap_fail_through_pc": [
        "Candles examined: last minute t in 09:19..14:13 (protocol P1.3 replaces 14:29). With B=15 the last "
        "candle examined is 13:45-13:59 (the 14:00-14:14 candle ends after 14:13); with B=5 it is 14:05-14:09; "
        "with B=30 it is 13:15-13:44.",
        "A B-minute candle's close is the close of the 1-minute bar stamped at its last minute t; if that "
        "exact bar were missing the candle is skipped (never happens on disk).",
        "'The open' in 'opposite side of PC from the open' is O, the open of today's 09:15 candle (the day's "
        "open, via the sign of G), not the open of the B-minute candle being examined.",
        "No 'consumes the day' wording: a close exactly equal to PC is not a signal and the scan continues.",
    ],
    "spx_cue_confirmed": [
        "'The S&P row before it' is the row immediately before the cue row in the GSPC daily file, whatever "
        "its date.",
        "'On or after the date of the previous Indian session' compares the S&P row's own (US calendar) date "
        "with the previous date of the index candle file as plain dates (>=).",
        "C = O is no trade (text: 'Otherwise no trade').",
        "R is computed in floating point; 'R = 0' is tested as exact equality of the ratio to 1.",
    ],
    "atm_oi_writer_skew": [
        "Addendum 2 applied: baseline = the option candle stamped exactly 09:20 ('latest at or before 09:20' "
        "may not reach before 09:20, so it must be the 09:20 candle itself; missing -> skip the day); later "
        "reading = the latest candle stamped in 09:20..T-3; signal minute stays T = 09:15+V-1.",
        "'Listed strike' is taken as a multiple of the index strike step (ctx.step); the contract list is not "
        "visible through DayCtx. A strike with no file gives option() = None and the day is skipped, which is "
        "also what the text's skip rule says.",
        "K0 tie-break: an index 09:15 close exactly half-way between two strikes goes to the lower strike "
        "(as written; this is NOT py_funcs.atm_strike's banker's rounding).",
        "Protocol P1.8 (+-5 strike steps of the at-the-money strike at minute t): checked once, at the signal "
        "minute T, with ATM = round(close(T)/step)*step (the atm_strike formula). If any strike of S is more "
        "than 5 steps from it, the day has no signal and no option file is read. ('minute t' is P1's signal "
        "minute; the band is not re-checked at the 09:20 or T-3 reading minutes.) Consequence, not a choice: "
        "the rule is silent on days when the index has moved more than (5 - J) steps away from K0 by T - on "
        "SENSEX 5 discovery days at the centre and 20 at strikes_each_side=2.",
        "'Listed strike' check (check/diff_ctx.py, contract list only): on all 80 discovery days of both "
        "indexes the nearest listed strike equals the nearest multiple of the step, the listed strikes 1 and "
        "2 away are K0 +- j*step, and no 09:15 close sits exactly half-way between two strikes.",
        "The zero-open-interest skip is applied per contract (any CE or PE of S with OI = 0 at either reading "
        "skips the day), not to the sums.",
        "Volume is not used; a zero-volume candle still carries an open-interest value and is read as is.",
    ],
}


# ---------------------------------------------------------------------------
# debug run: counts and the mechanical look-ahead check (never any result of a signal)
# ---------------------------------------------------------------------------
def _debug_run() -> int:
    import ctx as C

    problems: list[str] = []
    for index in C.INDEXES:
        market = C.Market(index)
        days = [d for d in market.sessions if C.WINDOW_START <= d <= C.DISCOVERY_END]
        print(f"\n================ {index}: {len(days)} sessions {days[0]} .. {days[-1]} ================")
        for cid, cand in CANDIDATES.items():
            cells = [("centre", cand["centre"])] + [(n["label"], n["params"]) for n in cand["neighbours"]]
            for label, params in cells:
                up = down = 0
                times = []
                for d in days:
                    dc = market.day_ctx(d)
                    try:
                        problems += C.check_no_lookahead(cand["fn"], dc, params)
                        sig = cand["fn"](dc, **params)
                    except Exception as e:                       # noqa: BLE001 - reported, not hidden
                        problems.append(f"{index} {d} {cid} {label}: raised {type(e).__name__}: {e}")
                        continue
                    if sig is None:
                        continue
                    times.append(sig[0])
                    if sig[1] == "UP":
                        up += 1
                    else:
                        down += 1
                n = up + down
                share = f"UP {up} ({up / n:.0%}) DOWN {down} ({down / n:.0%})" if n else "UP 0 DOWN 0"
                span = f"{min(times)}..{max(times)}" if times else "-"
                print(f"  {cid:28s} {label:28s} n={n:3d}  {share:28s} minutes {span}")
    print(f"\nlook-ahead / exception problems: {len(problems)}")
    for p in problems[:50]:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    import sys
    sys.exit(_debug_run())
