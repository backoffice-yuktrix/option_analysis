"""check/alt_ctx.py - INDEPENDENT SECOND CODING of four library candidates (family "volatility" /
"context"):  vol_vix_confirmed_or_break, gap_fail_through_pc, spx_cue_confirmed, atm_oi_writer_skew.

Written only from library.json ("signal" text), protocol.md (v2 + Addendum 1 and 2) and ctx.py.
No other signal module was read.  Nothing here looks at what happens after a signal.

Every function is  fn(day_ctx, **params) -> None | ("HH:MM", "UP" | "DOWN")  and only uses candles
stamped at or before the minute it is evaluating (ctx.check_no_lookahead proves it mechanically).

Run this file to print the signal counts and the look-ahead check for the discovery sessions:
    D:/YUKTRIX/option_analysis/analysis/.venv/Scripts/python.exe check/alt_ctx.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the study folder
import ctx as ctx_mod  # noqa: E402

OPEN_MIN = 555          # 09:15, the first 1-minute candle of a session
SIG_FIRST = 559         # protocol P1.3: signal minutes 09:19 ..
SIG_LAST = 853          # .. 14:13 ("wherever library.json says 14:29, read 14:13")
P17_FIRST = 560         # protocol P1.7: "No option price or India VIX value from bars stamped before 09:20"


# ---------------------------------------------------------------------------
# small helpers (private to this module)
# ---------------------------------------------------------------------------
def _min(stamp: str) -> int:
    """ "09:15" -> 555 """
    return int(stamp[:2]) * 60 + int(stamp[3:])


def _stamp(minute: int) -> str:
    """ 555 -> "09:15" """
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _by_minute(rows: list) -> dict:
    """{minute of day: row} of a list of 1-minute rows (index, VIX or option)."""
    return {_min(r[0]): r for r in rows}


def _latest_at_or_before(rows: list, minute: int, not_before: int):
    """The latest row stamped in not_before..minute (both inclusive), or None.  Rows are ascending."""
    found = None
    for r in rows:
        m = _min(r[0])
        if m > minute:
            break
        if m >= not_before:
            found = r
    return found


# ---------------------------------------------------------------------------
# 1. vol_vix_confirmed_or_break
# ---------------------------------------------------------------------------
def vol_vix_confirmed_or_break(dc, R_opening_range_minutes=15):
    R = R_opening_range_minutes
    if not dc.prev_sessions:
        return None
    prev = dc.prev_sessions[-1]            # notes: "Previous session is the most recent earlier date in the index candle file"

    # "VIX_PREV = house daily close of VIX for the previous session (average of (h+l+c)/3 over its VIX
    #  candles 15:00..15:29; if that window is empty, the last VIX close of that session)."
    prev_vix = dc.vix_session(prev)
    window = [(r[2] + r[3] + r[4]) / 3.0 for r in prev_vix if "15:00" <= r[0] <= "15:29"]
    if window:
        vix_prev = sum(window) / len(window)
    else:
        usable = [r for r in prev_vix if _min(r[0]) >= P17_FIRST]      # P1.7 (see AMBIGUITIES)
        if not usable:
            return None
        vix_prev = usable[-1][4]

    # "ORH / ORL = highest high / lowest low of the index's first R 1-minute candles (R = 15: 09:15..09:29)."
    bars = dc.bars
    or_last = OPEN_MIN + R - 1
    opening = [b for b in bars if OPEN_MIN <= _min(b[0]) <= or_last]
    if len(opening) < R:                   # opening range not complete (or a candle is missing): no evaluation
        return None
    orh = max(b[2] for b in opening)
    orl = min(b[3] for b in opening)

    # today's VIX candles, P1.7: none stamped before 09:20
    vix = [(_min(r[0]), r[4]) for r in dc.vix() if _min(r[0]) >= P17_FIRST]

    # "VIX_OR = VIX close of the last opening-range minute (09:29), or the latest VIX close earlier
    #  today if that candle is missing."
    vix_or = None
    for m, close in vix:
        if m > or_last:
            break
        vix_or = close
    if vix_or is None:
        return None

    # "For each completed 1-minute candle stamped t from 09:15+R to 14:29 [protocol: 14:13]:
    #  VIX_t = VIX close at t (or the latest VIX close today at or before t; none means skip the minute).
    #  Gate: VIX_t > VIX_PREV AND VIX_t > VIX_OR.  SIGNAL = the FIRST minute t where the gate holds AND
    #  the index close(t) > ORH (UP) or < ORL (DOWN)."
    first_t = max(OPEN_MIN + R, SIG_FIRST)
    j = 0
    vix_t = None
    for b in bars:
        t = _min(b[0])
        if t < first_t:
            continue
        if t > SIG_LAST:
            break
        while j < len(vix) and vix[j][0] <= t:
            vix_t = vix[j][1]
            j += 1
        if vix_t is None:
            continue
        if not (vix_t > vix_prev and vix_t > vix_or):
            continue
        if b[4] > orh:
            return (b[0], "UP")
        if b[4] < orl:
            return (b[0], "DOWN")
    return None


# ---------------------------------------------------------------------------
# 2. gap_fail_through_pc
# ---------------------------------------------------------------------------
def gap_fail_through_pc(dc, bar_minutes=15):
    B = bar_minutes
    if not dc.prev_sessions:
        return None
    # "PC = house daily close of the previous session (average of (h+l+c)/3 over its 1-minute candles 15:00..15:29)."
    try:
        pc = dc.house_close(dc.prev_sessions[-1])
    except ValueError:                     # the previous session has no 15:00..15:29 candles
        return None

    by_min = _by_minute(dc.bars)
    # "O = open of today's 09:15 1-minute candle.  G = O - PC; G = 0 means no trade."
    first = by_min.get(OPEN_MIN)
    if first is None:
        return None
    gap = first[1] - pc
    if gap == 0:
        return None

    # "Build B-minute candles aligned to 09:15 (B = 15: 09:15-09:29, 09:30-09:44, ...).  Only candles
    #  whose last minute t satisfies 09:19 <= t <= 14:29 [protocol: 14:13] are examined.  SIGNAL = the
    #  FIRST such candle whose close is on the opposite side of PC from the open: G > 0 and close < PC
    #  (DOWN), or G < 0 and close > PC (UP)."
    start = OPEN_MIN
    while True:
        t = start + B - 1                  # the candle's last 1-minute bar = the signal minute (P1.2)
        if t > SIG_LAST:
            return None
        if t >= SIG_FIRST:
            last_bar = by_min.get(t)       # the candle's close is the close of its last 1-minute bar;
            if last_bar is not None:       # if that bar is not there the candle is not complete: not examined
                close = last_bar[4]
                if gap > 0 and close < pc:
                    return (last_bar[0], "DOWN")
                if gap < 0 and close > pc:
                    return (last_bar[0], "UP")
        start += B


# ---------------------------------------------------------------------------
# 3. spx_cue_confirmed
# ---------------------------------------------------------------------------
def spx_cue_confirmed(dc, confirm_minutes=15):
    N = confirm_minutes
    if not dc.prev_sessions:
        return None
    # "S&P 500 daily rows: take the most recent row dated strictly BEFORE today's Indian date (never a
    #  row dated today)."   DayCtx.daily() already holds only rows dated strictly before the ctx day.
    spx = dc.daily("GSPC")
    if len(spx) < 2:                       # "R = 0 or a missing row means no trade."
        return None
    last, before = spx[-1], spx[-2]
    # "It is usable only if its date is on or after the date of the previous Indian session (otherwise
    #  the cue was already traded on: no trade)."
    if last[0] < dc.prev_sessions[-1]:
        return None
    # "R = that row's close / the close of the S&P row before it - 1."
    if not before[4]:
        return None
    r = last[4] / before[4] - 1.0
    if r == 0:
        return None

    # "O = open of today's index 09:15 candle; C = close of the candle stamped 09:15 + N - 1 with
    #  N = 15 (09:29).  SIGNAL at t = 09:29 (fill in the 09:30 bar) if R > 0 and C > O (UP), or R < 0
    #  and C < O (DOWN).  Otherwise no trade.  One evaluation per day, so at most one signal."
    t = OPEN_MIN + N - 1
    if not SIG_FIRST <= t <= SIG_LAST:
        return None
    by_min = _by_minute(dc.bars)
    first, conf = by_min.get(OPEN_MIN), by_min.get(t)
    if first is None or conf is None:
        return None
    o, c = first[1], conf[4]
    if r > 0 and c > o:
        return (conf[0], "UP")
    if r < 0 and c < o:
        return (conf[0], "DOWN")
    return None


# ---------------------------------------------------------------------------
# 4. atm_oi_writer_skew   (rewritten by protocol Addendum 2)
# ---------------------------------------------------------------------------
OI_BASELINE = 560       # Addendum 2: "its baseline is the 09:20 candle (not 09:15)"
OI_LAG = 3              # Addendum 2: "the later reading is the candle stamped T-3 (3 completed minutes of lag)"
BAND_STEPS = 5          # P1.8: "strikes within +-5 strike steps of the at-the-money strike at minute t"


def atm_oi_writer_skew(dc, eval_minutes=60, strikes_each_side=1):
    V, J = eval_minutes, strikes_each_side
    # "T = 09:15 + V - 1 with V = 60 (10:14)."   One evaluation, at T.
    T = OPEN_MIN + V - 1
    if not SIG_FIRST <= T <= SIG_LAST:
        return None
    later = T - OI_LAG
    if later < OI_BASELINE:
        return None
    by_min = _by_minute(dc.bars)
    first, bar_T = by_min.get(OPEN_MIN), by_min.get(T)
    if first is None or bar_T is None:     # minute T is not complete yet (or missing): nothing to evaluate
        return None
    step = dc.step

    # "K0 = listed strike nearest the close of the index 09:15 candle (step 50 NIFTY, 100 SENSEX; tie
    #  goes to the lower strike)."   Addendum 2: "the strike K0 is still taken from the index 09:15 close".
    c0 = first[4]
    k0 = (c0 // step) * step
    if c0 - k0 > step / 2.0:
        k0 += step

    # "Strike set S = K0 plus the J = 1 listed strikes directly above and directly below it, fixed for the day."
    strikes = [k0 + k * step for k in range(-J, J + 1)]

    # P1.8: "may read only contracts of the P2 expiry at strikes within +-5 strike steps of the
    # at-the-money strike at minute t".  ATM at T as in P2.2: atm_strike(close of the candle stamped T).
    atm_T = float(round(bar_T[4] / step) * step)
    if any(abs(k - atm_T) > BAND_STEPS * step for k in strikes):
        return None

    # "OI_PE(m) / OI_CE(m) = sum over S of the open interest in each option's 1-minute candle at minute
    #  m (the latest candle of today at or before m)."   Addendum 2: these lookups "may not reach back
    #  before 09:20", so the baseline is exactly the 09:20 candle and the later reading is the latest
    #  candle stamped 09:20..T-3.
    # "Skip the day if any CE or PE in S has no candle today at or before 09:15 [09:20] or at or before
    #  T [T-3], or has zero open interest at either point."
    change = {"CE": 0, "PE": 0}
    for ot in ("CE", "PE"):
        for k in strikes:
            rows = dc.option(ot, k)
            if rows is None:
                return None
            base = _latest_at_or_before(rows, OI_BASELINE, OI_BASELINE)
            late = _latest_at_or_before(rows, later, OI_BASELINE)
            if base is None or late is None:
                return None
            if base[6] == 0 or late[6] == 0:
                return None
            change[ot] += late[6] - base[6]

    # "D = [OI_PE(T) - OI_PE(09:15)] - [OI_CE(T) - OI_CE(09:15)]. ... SIGNAL at T (fill in bar T+1):
    #  D > 0 is UP, D < 0 is DOWN, D = 0 is no trade."
    d = change["PE"] - change["CE"]
    if d > 0:
        return (bar_T[0], "UP")
    if d < 0:
        return (bar_T[0], "DOWN")
    return None


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
def _neighbours(centre: dict, moves: list) -> list:
    """moves = [(param, lower, upper), ...] in library order -> one-at-a-time neighbour dicts."""
    out = []
    for name, lower, upper in moves:
        for value in (lower, upper):
            params = dict(centre)
            params[name] = value
            out.append({"label": f"{name}={value}", "params": params})
    return out


_C_VIX = {"R_opening_range_minutes": 15}
_C_GAP = {"bar_minutes": 15}
_C_SPX = {"confirm_minutes": 15}
_C_OI = {"eval_minutes": 60, "strikes_each_side": 1}

CANDIDATES = {
    "vol_vix_confirmed_or_break": {
        "fn": vol_vix_confirmed_or_break,
        "centre": dict(_C_VIX),
        "neighbours": _neighbours(_C_VIX, [("R_opening_range_minutes", 10, 30)]),
    },
    "gap_fail_through_pc": {
        "fn": gap_fail_through_pc,
        "centre": dict(_C_GAP),
        "neighbours": _neighbours(_C_GAP, [("bar_minutes", 5, 30)]),
    },
    "spx_cue_confirmed": {
        "fn": spx_cue_confirmed,
        "centre": dict(_C_SPX),
        "neighbours": _neighbours(_C_SPX, [("confirm_minutes", 10, 30)]),
    },
    "atm_oi_writer_skew": {
        "fn": atm_oi_writer_skew,
        "centre": dict(_C_OI),
        "neighbours": _neighbours(_C_OI, [("eval_minutes", 30, 90), ("strikes_each_side", 0, 2)]),
    },
}

AMBIGUITIES = {
    "vol_vix_confirmed_or_break": [
        "Scan runs over minutes t = 09:15+R .. 14:13 (protocol P1.3 replaces the text's 14:29); for R = 10 it "
        "starts at 09:25, for 30 at 09:45.",
        "'First R 1-minute candles' is read as the candles stamped 09:15 .. 09:15+R-1; if fewer than R of them "
        "exist the day gives no signal.",
        "P1.7 (no VIX value from bars stamped before 09:20) is applied to every VIX read of today: VIX_OR's "
        "fallback ('the latest VIX close earlier today') and VIX_t only use VIX candles stamped 09:20 or later. "
        "If no VIX candle stamped 09:20 .. last opening-range minute exists, VIX_OR is undefined and the day "
        "gives no signal.",
        "VIX_PREV's fallback (previous session has no VIX candle 15:00..15:29) uses that session's last VIX "
        "close stamped 09:20 or later; a previous session with no usable VIX candle gives no signal.",
        "'Previous session' is the previous date in the INDEX candle file (registrar's note); its VIX candles "
        "are used for VIX_PREV.",
        "VIX_t falls back to the latest VIX close at or before t even when that is the same candle as VIX_OR "
        "(the gate VIX_t > VIX_OR is then simply false).",
        "Both comparisons of the gate and both break tests are strict (>, <), as written.",
    ],
    "gap_fail_through_pc": [
        "Candles examined are those whose last minute t lies in 09:19..14:13 (P1.3). For B = 15 the first is "
        "09:15-09:29 (t = 09:29) and the last ends 13:59; for B = 5 the first is 09:15-09:19; for B = 30 the "
        "first ends 09:44 and the last 13:44.",
        "A B-minute candle's close is the close of its last 1-minute bar; a candle whose last 1-minute bar is "
        "absent is not examined (never substituted by an earlier bar).",
        "No candle consumes the day: the first admissible candle that closes on the opposite side of PC is the "
        "signal, whatever earlier candles did.",
        "G = 0 is tested by exact float equality (O == PC).",
    ],
    "spx_cue_confirmed": [
        "'Most recent row dated strictly before today' is the last row of DayCtx.daily('GSPC'); usable when its "
        "date >= the previous session date in the index candle file (string dates, the row's own US calendar "
        "date).",
        "'Missing row' also covers the absence of the S&P row before it (fewer than two rows: no trade).",
        "The confirmation candle is the single 1-minute candle stamped 09:15+N-1 (09:24 / 09:29 / 09:44); if it "
        "or the 09:15 candle is absent: no trade.",
        "R = 0 and C = O are no trade (strict comparisons).",
    ],
    "atm_oi_writer_skew": [
        "Addendum 2 applied: baseline = the option candle stamped exactly 09:20 ('latest at or before 09:20' "
        "that may not reach back before 09:20); later reading = the latest candle stamped 09:20..T-3; the "
        "signal minute stays T = 09:15+V-1 (09:44 / 10:14 / 10:44).",
        "D = [OI_PE(T-3) - OI_PE(09:20)] - [OI_CE(T-3) - OI_CE(09:20)].",
        "'Listed strike nearest the 09:15 close' is computed as the nearest multiple of the strike step (tie to "
        "the lower strike) - the contract list is not reachable through DayCtx; a strike that is not listed has "
        "no file, so the day is skipped. 'The J listed strikes directly above and below' = K0 +- k*step.",
        "P1.8 band: if any strike of S is more than 5 steps away from atm_strike(index close of the candle "
        "stamped T) the day gives no signal (the contract may not be read). The band is checked at the signal "
        "minute T only, not at the 09:20 baseline.",
        "The index candle stamped T must exist (it is the signal candle) although the rule reads no price from "
        "it other than for the P1.8 band.",
        "Zero open interest in any of the 2*(2J+1) contracts at either reading skips the day; the later reading "
        "may be the 09:20 candle itself when a contract printed no candle after it (its change is then 0).",
    ],
}


# ---------------------------------------------------------------------------
# self-run: signal counts and the mechanical look-ahead check, discovery sessions only
# ---------------------------------------------------------------------------
def _run() -> int:
    problems_total = 0
    for index in ctx_mod.INDEXES:
        market = ctx_mod.Market(index)                       # date wall = 2026-04-30
        days = [d for d in market.sessions if ctx_mod.WINDOW_START <= d <= ctx_mod.DISCOVERY_END]
        print(f"\n===== {index}: {len(days)} sessions {days[0]} .. {days[-1]} =====")
        for cid, cand in CANDIDATES.items():
            cells = [("centre", cand["centre"])] + [(n["label"], n["params"]) for n in cand["neighbours"]]
            for label, params in cells:
                up = down = 0
                stamps = []
                problems = []
                for d in days:
                    dc = market.day_ctx(d)
                    try:
                        sig = cand["fn"](dc, **params)
                        problems += ctx_mod.check_no_lookahead(cand["fn"], dc, params)
                    except Exception as e:                   # noqa: BLE001 - reported, not hidden
                        problems.append(f"{index} {d}: raised {type(e).__name__}: {e}")
                        continue
                    if sig is None:
                        continue
                    stamps.append(sig[0])
                    up += sig[1] == "UP"
                    down += sig[1] == "DOWN"
                n = up + down
                span = f"{min(stamps)}..{max(stamps)}" if stamps else "-"
                print(f"{cid:28s} {label:28s} n={n:3d}  UP={up:3d} DOWN={down:3d}  minutes {span}  "
                      f"lookahead problems={len(problems)}")
                for p in problems[:5]:
                    print("    PROBLEM " + p)
                problems_total += len(problems)
    print(f"\nTOTAL look-ahead / exception problems: {problems_total}")
    return 1 if problems_total else 0


if __name__ == "__main__":
    sys.exit(_run())
