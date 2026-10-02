"""check/alt_repo_a.py - INDEPENDENT SECOND CODING of five `existing_repo` library candidates.

Written only from library.json (the "signal" text), protocol.md and ctx.py.  No other signal module
was read.  Each function is fn(ctx, **params) -> None | (t, direction); t is the "HH:MM" stamp of the
signal minute (the fill bar is t+1), direction "UP" (buy CE) or "DOWN" (buy PE).

Every function reads only index candles: today's bars stamped at or before the minute it evaluates,
and whole EARLIER sessions.  No option, VIX, daily-file, weekday or expiry input is used.

Run this file to print the signal counts and the look-ahead check (discovery days only).
"""
from __future__ import annotations

import os
import sys

_STUDY = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _STUDY not in sys.path:
    sys.path.insert(0, _STUDY)

import ctx as ctxmod  # noqa: E402

SIGNAL_FIRST = "09:19"   # protocol P1.3: "signal minutes are 09:19 .. 14:13"
SIGNAL_LAST = "14:13"
OPEN_MIN = 555           # 09:15


# ---------------------------------------------------------------------------
# small helpers (private to this module)
# ---------------------------------------------------------------------------
def _mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _stamp(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _by_stamp(bars: list) -> dict:
    """{ "HH:MM": bar } of the bars handed in (today's bars are already cut at the ctx cutoff)."""
    return {b[0]: b for b in bars}


def _range_bars(bars: list, first: str, last: str) -> list:
    """Bars stamped first..last inclusive, in order."""
    return [b for b in bars if first <= b[0] <= last]


def _ols_slope(ys: list) -> float | None:
    """Slope of the ordinary least-squares line of ys against 0..n-1."""
    n = len(ys)
    if n < 2:
        return None
    xbar = (n - 1) / 2.0
    ybar = sum(ys) / n
    sxy = sum((i - xbar) * (y - ybar) for i, y in enumerate(ys))
    sxx = sum((i - xbar) ** 2 for i in range(n))
    return sxy / sxx


def _admissible(t: str) -> bool:
    return SIGNAL_FIRST <= t <= SIGNAL_LAST


# ---------------------------------------------------------------------------
# opening-range reversal: the part shared by the three ORR candidates
# ---------------------------------------------------------------------------
def _orr_setup(ctx, decision_time: str, opening_range_minutes: int):
    """None, or a dict with everything the ORR rules need at the decision minute T.

    "ORH = highest high, ORL = lowest low of the first OR 1-minute candles (OR = 5: candles stamped
     09:15..09:19).  One decision minute T = 11:30 (the candle stamped 11:30, complete).  Window W =
     all 1-minute candles stamped from 09:15+OR (09:20) to T inclusive; if W has fewer than 20 candles,
     no trade.  Fit an ordinary least-squares line through W's closes against the index 0..n-1.
     DOWN move = slope < 0 AND close(T) < close of W's first candle.  UP move = slope > 0 AND
     close(T) > close of W's first candle.  Otherwise no trade."
    """
    T = decision_time
    if not _admissible(T):
        return None
    bars = ctx.bars
    if not bars or bars[-1][0] < T:                 # the candle stamped T is not there (yet)
        return None
    by = _by_stamp(bars)
    bar_T = by.get(T)
    if bar_T is None:
        return None
    n_or = int(opening_range_minutes)
    or_first, or_last = _stamp(OPEN_MIN), _stamp(OPEN_MIN + n_or - 1)
    or_bars = _range_bars(bars, or_first, or_last)
    if len(or_bars) != n_or:                        # an incomplete opening range: no trade
        return None
    orh = max(b[2] for b in or_bars)
    orl = min(b[3] for b in or_bars)
    W = _range_bars(bars, _stamp(OPEN_MIN + n_or), T)
    if len(W) < 20:                                 # "if W has fewer than 20 candles, no trade"
        return None
    closes = [b[4] for b in W]
    slope = _ols_slope(closes)
    close_T = bar_T[4]
    first_close = closes[0]
    if slope is not None and slope < 0 and close_T < first_close:
        move = "DOWN"
    elif slope is not None and slope > 0 and close_T > first_close:
        move = "UP"
    else:
        move = None
    return {"T": T, "bar_T": bar_T, "close_T": close_T, "orh": orh, "orl": orl, "W": W, "closes": closes,
            "move": move, "w_high": max(b[2] for b in W), "w_low": min(b[3] for b in W)}


def repo_orr_outside_range(ctx, decision_time="11:30", opening_range_minutes=5):
    s = _orr_setup(ctx, decision_time, opening_range_minutes)
    if s is None or s["move"] is None:
        return None
    # "Buy-CE signal: close(T) < ORL AND highest high in W <= ORH AND move is DOWN."
    if s["close_T"] < s["orl"] and s["w_high"] <= s["orh"] and s["move"] == "DOWN":
        return (s["T"], "UP")
    # "Buy-PE signal: close(T) > ORH AND lowest low in W >= ORL AND move is UP."
    if s["close_T"] > s["orh"] and s["w_low"] >= s["orl"] and s["move"] == "UP":
        return (s["T"], "DOWN")
    return None


def _edge_survived_side(s):
    """'CE' / 'PE' / None for the surviving-edge rule on an _orr_setup dict.

    "Buy-CE signal: highest high in W <= ORH AND move is DOWN.  Otherwise buy-PE signal: lowest low in
     W >= ORL AND move is UP.  Where close(T) sits relative to the range does not matter."
    """
    if s is None or s["move"] is None:
        return None
    if s["w_high"] <= s["orh"] and s["move"] == "DOWN":
        return "CE"
    if s["w_low"] >= s["orl"] and s["move"] == "UP":
        return "PE"
    return None


def repo_orr_edge_survived(ctx, decision_time="11:30", opening_range_minutes=5):
    s = _orr_setup(ctx, decision_time, opening_range_minutes)
    side = _edge_survived_side(s)
    if side is None:
        return None
    return (s["T"], "UP" if side == "CE" else "DOWN")


def repo_orr_exhaustion(ctx, rsi_distance_from_50=10, sd_stretch_min=1.0):
    # "Start from repo_orr_edge_survived with OR = 5 (09:15..09:19) and T = 11:30 fixed"
    s = _orr_setup(ctx, "11:30", 5)
    side = _edge_survived_side(s)
    if side is None:
        return None
    closes = s["closes"]
    close_T = s["close_T"]

    # "(1) RSI by plain averages on the last 15 closes of W (14 changes): avgGain = sum of rises / 14,
    #  avgLoss = sum of falls / 14, RSI = 100 - 100/(1 + avgGain/avgLoss); RSI = 100 if there are no falls."
    if len(closes) < 15:
        return None
    last15 = closes[-15:]
    rises = falls = 0.0
    for a, b in zip(last15, last15[1:]):
        d = b - a
        if d > 0:
            rises += d
        elif d < 0:
            falls += -d
    avg_gain, avg_loss = rises / 14.0, falls / 14.0
    rsi = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    # "Need RSI <= 40 for CE, RSI >= 60 for PE"  (param: CE needs RSI <= 50 - x, PE needs RSI >= 50 + x)
    if side == "CE" and not rsi <= 50.0 - rsi_distance_from_50:
        return None
    if side == "PE" and not rsi >= 50.0 + rsi_distance_from_50:
        return None

    # "(2) Stretch: mean and population standard deviation (divide by n) of all closes in W; need
    #  (mean - close(T))/sd >= 1.0 for CE, (close(T) - mean)/sd >= 1.0 for PE; sd = 0 means no trade."
    n = len(closes)
    mean = sum(closes) / n
    sd = (sum((c - mean) ** 2 for c in closes) / n) ** 0.5
    if sd == 0:
        return None
    z = (mean - close_T) / sd if side == "CE" else (close_T - mean) / sd
    if not z >= sd_stretch_min:
        return None

    # "(3) The candle stamped T itself must still move with the move being faded: close < open for CE,
    #  close > open for PE."
    o, c = s["bar_T"][1], s["bar_T"][4]
    if side == "CE" and not c < o:
        return None
    if side == "PE" and not c > o:
        return None
    return (s["T"], "UP" if side == "CE" else "DOWN")


# ---------------------------------------------------------------------------
# daily values built from EARLIER sessions' 1-minute candles
# ---------------------------------------------------------------------------
def _session_high_low(ctx, d: str):
    """"high = highest high and low = lowest low of 09:15..15:29" of earlier session d."""
    rows = [b for b in ctx.session(d) if "09:15" <= b[0] <= "15:29"]
    if not rows:
        return None
    return max(b[2] for b in rows), min(b[3] for b in rows)


def _true_ranges(ctx, n: int):
    """True range of each of the n sessions before today (oldest first), or None if history is short.

    "True range of a session = max(high - low, |high - previous session's house close|,
     |low - previous session's house close|)."   Needs n + 1 earlier sessions.
    """
    prev = ctx.prev_sessions
    if len(prev) < n + 1:
        return None
    out = []
    for k in range(n, 0, -1):                       # the session k sessions before today
        d, d_before = prev[-k], prev[-k - 1]
        hl = _session_high_low(ctx, d)
        if hl is None:
            return None
        high, low = hl
        pc = ctx.house_close(d_before)
        out.append(max(high - low, abs(high - pc), abs(low - pc)))
    return out


def repo_stretch_fade_1100(ctx, stretch_threshold_adr=0.75, lookback_sessions=5):
    T = "11:00"                                     # "At the single decision minute 11:00"
    bars = ctx.bars
    if not bars or bars[-1][0] < T:
        return None
    bar_T = _by_stamp(bars).get(T)
    if bar_T is None:
        return None
    L = int(lookback_sessions)
    prev = ctx.prev_sessions
    if len(prev) < L:
        return None
    # "ADR = simple average of the true range of the 14 sessions before today."
    trs = _true_ranges(ctx, 14)
    if trs is None:
        return None
    adr = sum(trs) / len(trs)
    if adr <= 0:
        return None
    # "REF = house daily close of the session L = 5 sessions before today (yesterday is 1 session before)."
    ref = ctx.house_close(prev[-L])
    # "stretch = (close of the 11:00 candle - REF) / ADR.  stretch > +0.75: DOWN signal.
    #  stretch < -0.75: UP signal.  Otherwise no trade."
    stretch = (bar_T[4] - ref) / adr
    if stretch > stretch_threshold_adr:
        return (T, "DOWN")
    if stretch < -stretch_threshold_adr:
        return (T, "UP")
    return None


def repo_stretch_fade_line_reject(ctx, stretch_threshold=0.8, last_signal_time="12:30"):
    GATE = "11:00"                                  # "Step A, gate at the 11:00 candle (complete)"
    bars = ctx.bars
    if not bars or bars[-1][0] < GATE:
        return None
    by = _by_stamp(bars)
    gate_bar = by.get(GATE)
    if gate_bar is None:
        return None
    prev = ctx.prev_sessions
    if len(prev) < 11:
        return None

    # "R = simple average true range of the 10 sessions before today"
    trs = _true_ranges(ctx, 10)
    if trs is None:
        return None
    R = sum(trs) / len(trs)
    if R <= 0:
        return None
    C = gate_bar[4]                                 # "C = close of the 11:00 candle"
    # "s1 = (C - house close of the session 5 sessions before today) / R"
    s1 = (C - ctx.house_close(prev[-5])) / R
    # "s2 = (C - (highest high + lowest low of the 10 sessions before today) / 2) / R"
    highs, lows = [], []
    for d in prev[-10:]:
        hl = _session_high_low(ctx, d)
        if hl is None:
            return None
        highs.append(hl[0])
        lows.append(hl[1])
    s2 = (C - (max(highs) + min(lows)) / 2.0) / R
    # "PUT day if max(s1, s2) > 0.8 AND min(s1, s2) >= 0.  CALL day if min(s1, s2) < -0.8 AND
    #  max(s1, s2) <= 0.  Otherwise no trade today."
    hi_s, lo_s = max(s1, s2), min(s1, s2)
    if hi_s > stretch_threshold and lo_s >= 0:
        put_day = True
    elif lo_s < -stretch_threshold and hi_s <= 0:
        put_day = False
    else:
        return None

    # "Step B: LINE(t) = arithmetic mean of today's 1-minute closes from 09:15 through t."
    # Forward scan; at each minute only bars stamped at or before it have been added to the running sum.
    last_m = min(_mins(last_signal_time), _mins(SIGNAL_LAST))
    touch_from = _mins(GATE) + 1                    # "stamped 11:01 or later"
    run_sum, run_n = 0.0, 0
    touched = False
    for b in bars:
        m = _mins(b[0])
        if m > last_m:
            break
        run_sum += b[4]
        run_n += 1
        if m < touch_from:
            continue
        line = run_sum / run_n
        # "Touch minute u = the first 1-minute candle stamped 11:01 or later with high >= LINE(u) on a
        #  PUT day (low <= LINE(u) on a CALL day)."
        if not touched:
            if (put_day and b[2] >= line) or (not put_day and b[3] <= line):
                touched = True
            else:
                continue
        # "Step C: 10-minute candles aligned to 09:15 (last minutes 09:24, 09:34, ...).  Signal candle =
        #  the first 10-minute candle whose last minute m satisfies u <= m <= 12:30 and whose 1-minute
        #  close at m is < LINE(m) on a PUT day (> LINE(m) on a CALL day)."
        if (m - OPEN_MIN) % 10 != 9:
            continue
        close_m = b[4]
        if not ((put_day and close_m < line) or (not put_day and close_m > line)):
            continue
        if not _admissible(b[0]):
            return None
        # "Step D, confirmation at the same minute m: take the most recent 15-minute candle (aligned to
        #  09:15) whose last minute is <= m; on a PUT day close(m) must be < (its high + its low)/2, on a
        #  CALL day close(m) must be > that midpoint."
        k = (m - OPEN_MIN + 1) // 15                # number of 15-minute candles complete by the end of m
        if k < 1:
            return None
        c15 = _range_bars(bars, _stamp(OPEN_MIN + (k - 1) * 15), _stamp(OPEN_MIN + k * 15 - 1))
        if not c15:
            return None
        mid = (max(x[2] for x in c15) + min(x[3] for x in c15)) / 2.0
        # "Only the day's FIRST signal candle is examined: confirmed means SIGNAL at m (fill in bar m+1),
        #  not confirmed means no trade today."
        if put_day and close_m < mid:
            return (b[0], "DOWN")
        if (not put_day) and close_m > mid:
            return (b[0], "UP")
        return None
    return None


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------
def _neighbours(centre: dict, moves: list) -> list:
    """moves = [(param, lower value, lower text, upper value, upper text), ...] in library order."""
    out = []
    for name, lo, lo_txt, up, up_txt in moves:
        for val, txt in ((lo, lo_txt), (up, up_txt)):
            p = dict(centre)
            p[name] = val
            out.append({"label": f"{name}={txt}", "params": p})
    return out


_C_ORR = {"decision_time": "11:30", "opening_range_minutes": 5}
_M_ORR = [("decision_time", "11:15", "11:15", "11:45", "11:45"),
          ("opening_range_minutes", 3, "3", 15, "15")]
_C_EXH = {"rsi_distance_from_50": 10, "sd_stretch_min": 1.0}
_M_EXH = [("rsi_distance_from_50", 5, "5", 15, "15"),
          ("sd_stretch_min", 0.75, "0.75", 1.25, "1.25")]
_C_SF = {"stretch_threshold_adr": 0.75, "lookback_sessions": 5}
_M_SF = [("stretch_threshold_adr", 0.5, "0.5", 1.0, "1.0"),
         ("lookback_sessions", 3, "3", 7, "7")]
_C_LR = {"stretch_threshold": 0.8, "last_signal_time": "12:30"}
_M_LR = [("stretch_threshold", 0.6, "0.6", 1.0, "1.0"),
         ("last_signal_time", "12:00", "12:00", "13:00", "13:00")]

CANDIDATES = {
    "repo_orr_outside_range": {"fn": repo_orr_outside_range, "centre": dict(_C_ORR),
                               "neighbours": _neighbours(_C_ORR, _M_ORR)},
    "repo_orr_edge_survived": {"fn": repo_orr_edge_survived, "centre": dict(_C_ORR),
                               "neighbours": _neighbours(_C_ORR, _M_ORR)},
    "repo_orr_exhaustion": {"fn": repo_orr_exhaustion, "centre": dict(_C_EXH),
                            "neighbours": _neighbours(_C_EXH, _M_EXH)},
    "repo_stretch_fade_1100": {"fn": repo_stretch_fade_1100, "centre": dict(_C_SF),
                               "neighbours": _neighbours(_C_SF, _M_SF)},
    "repo_stretch_fade_line_reject": {"fn": repo_stretch_fade_line_reject, "centre": dict(_C_LR),
                                      "neighbours": _neighbours(_C_LR, _M_LR)},
}

AMBIGUITIES = {
    "repo_orr_outside_range": [
        "Neighbour labels use the library's own value text ('decision_time=11:15', 'opening_range_minutes=3').",
        "'the first OR 1-minute candles' is read as the candles stamped 09:15 .. 09:15+OR-1; if any of them "
        "is missing the day gives no signal (never happens on disk: every session has 375 bars).",
        "W is whatever candles are stamped 09:15+OR .. T; the OLS x is the position 0..n-1 in W, not the clock minute.",
        "A slope of exactly 0, or close(T) equal to W's first close, is 'no direction' (strict inequalities as written).",
        "Edge tests are non-strict as written: highest high in W <= ORH, lowest low in W >= ORL; "
        "close(T) < ORL / > ORH are strict.",
    ],
    "repo_orr_edge_survived": [
        "Same opening-range, W and OLS conventions as repo_orr_outside_range.",
        "'Otherwise buy-PE' is read as an if / else-if: the CE test is tried first. The two can never both be "
        "true because the move has one direction.",
    ],
    "repo_orr_exhaustion": [
        "The library parameter name 'rsi_distance_from_50 (CE needs RSI <= 50 - x, PE needs RSI >= 50 + x)' is "
        "coded as the argument rsi_distance_from_50; labels are 'rsi_distance_from_50=5' / '=15'.",
        "OR = 5 and T = 11:30 are constants inside the function ('fixed' in the text).",
        "'RSI = 100 if there are no falls' is applied literally, including when all 14 changes are zero.",
        "RSI uses the last 15 closes of W, which end with the close of the candle stamped T.",
        "Thresholds are inclusive as written (RSI <= 40 / >= 60, stretch >= 1.0); test (3) is strict "
        "(close < open / close > open), so a doji at T is no trade.",
    ],
    "repo_stretch_fade_1100": [
        "'the 14 sessions before today' needs 15 earlier sessions on disk (the oldest of the 14 needs its own "
        "previous house close); fewer means no signal. Warm-up sessions from 2025-11-24 count.",
        "Session high / low use every 1-minute candle stamped 09:15..15:29 of that session.",
        "REF for lookback L is prev_sessions[-L] (yesterday is L = 1). The ADR length stays 14 when L is moved.",
        "Strict inequalities as written: stretch exactly equal to the threshold is no trade.",
        "ADR <= 0 is treated as 'cannot evaluate' (no signal).",
    ],
    "repo_stretch_fade_line_reject": [
        "The REF lookback of 5 sessions, the 10-session R and the 10-session high/low are constants; only the "
        "threshold and the last signal time move.",
        "'(highest high + lowest low of the 10 sessions before today) / 2' is read as (the single highest high "
        "over the 10 sessions + the single lowest low over the 10 sessions) / 2.",
        "LINE(t) includes the close of the candle stamped t itself ('from 09:15 through t').",
        "The touch minute u may be the signal minute m itself (u <= m), and u itself must be <= last_signal_time "
        "because m <= last_signal_time.",
        "Step C tests only the 1-minute close at the 10-minute candle's last minute m (09:24, 09:34, ...); with "
        "last_signal_time 12:30 the last m that can qualify is 12:24 (12:00 -> 11:54, 13:00 -> 12:54).",
        "Step D: the most recent 15-minute candle whose last minute is <= m. When m is itself the last minute "
        "of a 15-minute candle (e.g. 11:14, 11:44) that candle - which contains m - is the one used.",
        "Step D is strict as written: close(m) equal to the midpoint is 'not confirmed' and the day is over.",
        "'Only the day's FIRST signal candle is examined': after the first Step-C candle the function returns, "
        "confirmed or not; no later candle is tried.",
        "last_signal_time is additionally capped at 14:13 (protocol P1.3); it never binds for 12:00/12:30/13:00.",
    ],
}


# ---------------------------------------------------------------------------
# self-run: counts and the look-ahead check on discovery days (no outcome of any signal is computed)
# ---------------------------------------------------------------------------
def _selfrun() -> int:
    import json

    with open(os.path.join(_STUDY, "library.json"), encoding="utf-8") as f:
        lib = {c["id"]: c for c in json.load(f)["candidates"]}
    problems: list[str] = []

    # the registry against the library text
    for cid, cand in CANDIDATES.items():
        lp = lib[cid]["params"]
        names = [p["name"].split(" ")[0] for p in lp]
        if list(cand["centre"]) != names:
            problems.append(f"{cid}: centre params {list(cand['centre'])} != library {names}")
        want = []
        for p, name in zip(lp, names):
            if str(cand["centre"][name]) != p["centre"] and float(cand["centre"][name]) != float(p["centre"]):
                problems.append(f"{cid}: centre {name} = {cand['centre'][name]!r}, library {p['centre']!r}")
            want += [f"{name}={p['lower_neighbour']}", f"{name}={p['upper_neighbour']}"]
        got = [n["label"] for n in cand["neighbours"]]
        if got != want:
            problems.append(f"{cid}: neighbour labels {got} != library {want}")
        for n in cand["neighbours"]:
            moved = [k for k in cand["centre"] if n["params"][k] != cand["centre"][k]]
            if len(moved) != 1 or set(n["params"]) != set(cand["centre"]):
                problems.append(f"{cid}: neighbour {n['label']} does not move exactly one value")

    for index in ctxmod.INDEXES:
        m = ctxmod.Market(index)
        days = [d for d in m.sessions if ctxmod.WINDOW_START <= d <= ctxmod.DISCOVERY_END]
        print(f"\n===== {index}: {len(days)} sessions {days[0]} .. {days[-1]} =====")
        ctxs = [m.day_ctx(d) for d in days]
        for cid, cand in CANDIDATES.items():
            cells = [("centre", cand["centre"])] + [(n["label"], n["params"]) for n in cand["neighbours"]]
            for label, params in cells:
                n_up = n_dn = n_bad = 0
                stamps = []
                for c in ctxs:
                    try:
                        r = cand["fn"](c, **params)
                        p = ctxmod.check_no_lookahead(cand["fn"], c, params)
                    except Exception as e:                     # noqa: BLE001
                        r, p = None, [f"{index} {c.day}: raised {type(e).__name__}: {e}"]
                    if p:
                        n_bad += 1
                        problems += [f"{cid} [{label}] {x}" for x in p]
                    if r is not None:
                        stamps.append(r[0])
                        n_up += r[1] == "UP"
                        n_dn += r[1] == "DOWN"
                n = n_up + n_dn
                rng = f"{min(stamps)}..{max(stamps)}" if stamps else "-"
                print(f"  {cid:32s} {label:28s} n={n:3d} UP={n_up:3d} DOWN={n_dn:3d} minutes {rng:13s} "
                      f"lookahead problems={n_bad}")
    print(f"\n{'ALL CLEAN' if not problems else 'PROBLEMS: ' + str(len(problems))}")
    for x in problems[:40]:
        print("  " + x)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(_selfrun())
