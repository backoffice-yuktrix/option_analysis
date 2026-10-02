"""signals_repo_a.py - five `existing_repo` candidates of library.json as signal functions.

    repo_orr_outside_range, repo_orr_edge_survived, repo_orr_exhaustion,
    repo_stretch_fade_1100, repo_stretch_fade_line_reject

Each function is fn(ctx: DayCtx, **params) -> None | (t, direction):
    t = "HH:MM" stamp of the signal minute (the fill bar is t+1), direction "UP" (buy CE) / "DOWN" (buy PE).
The rule text is the "signal" field of the candidate in library.json; protocol.md overrides it.
Every number that is not a varied parameter is a constant with the sentence it comes from quoted beside it.
Only index candles are used (today's, cut at the minute being evaluated, and whole EARLIER sessions).
Nothing here looks at an option price, the weekday, the expiry calendar or anything after the signal minute.
"""
from __future__ import annotations

SESSION_OPEN = 555                    # 09:15 in minutes of the day
SIGNAL_FIRST, SIGNAL_LAST = "09:19", "14:13"      # protocol P1.3

AMBIGUITIES = {
    "repo_orr_outside_range": [
        "Opening range needs ALL of its OR 1-minute candles (09:15 .. 09:15+OR-1) to be on disk; if one is "
        "missing the day is 'cannot evaluate' -> None. (Every session on disk has 375 bars, so this never bites.)",
        "'One decision minute T (the candle stamped T, complete)': the candle stamped T must exist; no "
        "neighbouring minute is substituted. Signal minute t = T, fill bar T+1.",
        "W = the candles that exist with 09:15+OR <= stamp <= T; the OLS x is the position 0..n-1 in W "
        "(not the clock minute), as written: 'against the index 0..n-1'.",
        "slope == 0 exactly, or close(T) == first close of W, is 'otherwise no trade' (strict inequalities as written).",
        "Direction mapping: 'Buy-CE signal' -> UP, 'Buy-PE signal' -> DOWN.",
        "Edge tests are non-strict as written (highest high in W <= ORH, lowest low in W >= ORL); "
        "close(T) < ORL / close(T) > ORH are strict as written.   [added at adjudication, text only]",
    ],
    "repo_orr_edge_survived": [
        "Same opening-range, W, OLS and decision-minute readings as repo_orr_outside_range.",
        "'Buy-CE ... Otherwise buy-PE': CE is tested first; the two cannot both be true (the move is DOWN or UP, not both).",
    ],
    "repo_orr_exhaustion": [
        "Parameter name in the library is 'rsi_distance_from_50 (CE needs RSI <= 50 - x, PE needs RSI >= 50 + x)'; "
        "the function argument and the neighbour labels use the identifier 'rsi_distance_from_50'.",
        "RSI: 'RSI = 100 if there are no falls' is applied whenever the sum of falls is 0, including a flat run "
        "with no rises either.",
        "Fewer than 15 closes in W -> no trade (cannot happen with OR = 5, T = 11:30 on a full session).",
        "Stretch test compares with >= as written ('>= 1.0'); RSI tests are <= / >= as written.",
        "OR = 5 and T = 11:30 are constants here ('with OR = 5 (09:15..09:19) and T = 11:30 fixed').",
    ],
    "repo_stretch_fade_1100": [
        "ADR needs the true range of each of the 14 sessions before today, and each true range needs the house "
        "close of the session before it: so 15 earlier sessions are required (and at least L); fewer -> None. "
        "No true range is ever computed as plain high - low for want of a previous close.",
        "'the 14 sessions before today' / 'L sessions before today' are counted on the index's own session list "
        "(ctx.prev_sessions; Sunday 2026-02-01 counts as a session).",
        "Strict inequalities as written: stretch > +thr -> DOWN, stretch < -thr -> UP; ADR == 0 -> None.",
        "Signal minute t = 11:00 (the candle stamped 11:00 must exist), fill bar 11:01.",
        "REF for lookback L is the house close of ctx.prev_sessions[-L] (yesterday is L = 1). The ADR length stays "
        "14 when lookback_sessions is moved to a neighbour; only REF moves.   [added at adjudication, text only]",
    ],
    "repo_stretch_fade_line_reject": [
        "R and the 10-session high/low use 'the 10 sessions before today'; the true ranges need an 11th earlier "
        "session for the first previous close: fewer than 11 earlier sessions -> None. R == 0 -> None.",
        "The '5 sessions before today' in s1 is a constant of the text (not a varied parameter).",
        "Step B touch test uses the same candle's own high (PUT day) / low (CALL day) against LINE(u), where "
        "LINE(u) already includes the close of candle u, as written ('from 09:15 through t').",
        "No upper clock limit is written for the touch minute u itself; it is bounded only through "
        "u <= m <= last_signal_time. A day with no touch by last_signal_time has no signal.",
        "Step C: the 10-minute candle is identified by its last minute m (09:24 + 10k); only the 1-minute candle "
        "stamped m is required to exist (its close is 'the 1-minute close at m'). A missing m candle means that "
        "10-minute candle cannot satisfy the test, so it is not the signal candle and the scan moves on to the "
        "next 10-minute candle (never a neighbour minute). No session on disk has a missing minute.",
        "Step D: 'the most recent 15-minute candle (aligned to 09:15) whose last minute is <= m' = the candle "
        "ending 09:29 + 15j with the largest j such that its last minute <= m; its high / low are taken over the "
        "1-minute candles on disk inside its 15 minutes. When m is itself such a last minute (e.g. 11:44) that "
        "candle includes minute m.",
        "Strict inequalities in steps C and D as written (close < LINE, close < midpoint; mirrored for CALL).",
        "Direction mapping: PUT day -> DOWN (buy PE), CALL day -> UP (buy CE).",
        "LINE(t) is the mean of the closes of the candles on disk stamped 09:15..t.",
        "s2: '(highest high + lowest low of the 10 sessions before today) / 2' is read as (the single highest high "
        "over those 10 sessions + the single lowest low over them) / 2.   [added at adjudication, text only]",
        "'Only the day's FIRST signal candle is examined': at the first Step-C candle the function returns, "
        "confirmed (signal) or not (None); no later 10-minute candle is tried.   [added at adjudication, text only]",
        "last_signal_time is additionally capped at 14:13 (protocol P1.3); the cap never binds for 12:00 / 12:30 / "
        "13:00. Because m is a 10-minute candle's last minute (09:24 + 10k), the last m that can qualify is 12:24 "
        "with 12:30 (11:54 with 12:00, 12:54 with 13:00).   [added at adjudication, text only]",
    ],
}


# ---------------------------------------------------------------------------
# small helpers (local to this module on purpose)
# ---------------------------------------------------------------------------
def _min(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _admissible(t: str) -> bool:
    """Protocol P1.3/P1.4: the signal minute must lie in 09:19..14:13."""
    return SIGNAL_FIRST <= t <= SIGNAL_LAST


def _ols_slope(ys: list) -> float:
    """Ordinary least-squares slope of ys against 0..n-1."""
    n = len(ys)
    xm = (n - 1) / 2.0
    ym = sum(ys) / n
    num = sum((i - xm) * (y - ym) for i, y in enumerate(ys))
    den = sum((i - xm) ** 2 for i in range(n))
    return num / den


# ---------------------------------------------------------------------------
# opening-range reversal: the part shared by the three orr candidates
# ---------------------------------------------------------------------------
ORR_MIN_WINDOW = 20        # "if W has fewer than 20 candles, no trade"


def _orr_setup(ctx, decision_time: str, opening_range_minutes: int):
    """None, or a dict with ORH, ORL, the window W (rows), the candle T and the OLS move ("DOWN"/"UP"/None)."""
    if not _admissible(decision_time):
        return None
    t_min = _min(decision_time)
    or_end = SESSION_OPEN + opening_range_minutes          # first minute AFTER the opening range (09:20 for OR = 5)
    # "ORH = highest high, ORL = lowest low of the first OR 1-minute candles (OR = 5: candles stamped 09:15..09:19)"
    or_rows, w = [], []
    for r in ctx.bars:
        m = _min(r[0])
        if SESSION_OPEN <= m < or_end:
            or_rows.append(r)
        elif or_end <= m <= t_min:
            # "Window W = all 1-minute candles stamped from 09:15+OR (09:20) to T inclusive"
            w.append(r)
    if len(or_rows) != opening_range_minutes:
        return None
    # "One decision minute T = 11:30 (the candle stamped 11:30, complete)"
    if not w or w[-1][0] != decision_time:
        return None
    if len(w) < ORR_MIN_WINDOW:
        return None
    closes = [r[4] for r in w]
    # "Fit an ordinary least-squares line through W's closes against the index 0..n-1."
    slope = _ols_slope(closes)
    close_t, first_close = closes[-1], closes[0]
    move = None
    if slope < 0 and close_t < first_close:      # "DOWN move = slope < 0 AND close(T) < close of W's first candle"
        move = "DOWN"
    elif slope > 0 and close_t > first_close:    # "UP move = slope > 0 AND close(T) > close of W's first candle"
        move = "UP"
    return {
        "orh": max(r[2] for r in or_rows),
        "orl": min(r[3] for r in or_rows),
        "w": w,
        "w_high": max(r[2] for r in w),
        "w_low": min(r[3] for r in w),
        "close_t": close_t,
        "bar_t": w[-1],
        "move": move,
    }


def repo_orr_outside_range(ctx, decision_time="11:30", opening_range_minutes=5):
    s = _orr_setup(ctx, decision_time, opening_range_minutes)
    if s is None or s["move"] is None:           # "Otherwise no trade."
        return None
    # "Buy-CE signal: close(T) < ORL AND highest high in W <= ORH AND move is DOWN."
    if s["close_t"] < s["orl"] and s["w_high"] <= s["orh"] and s["move"] == "DOWN":
        return (decision_time, "UP")
    # "Buy-PE signal: close(T) > ORH AND lowest low in W >= ORL AND move is UP."
    if s["close_t"] > s["orh"] and s["w_low"] >= s["orl"] and s["move"] == "UP":
        return (decision_time, "DOWN")
    return None


def _edge_survived_side(s):
    """"CE" / "PE" / None for the surviving-edge rule on an _orr_setup result."""
    if s is None or s["move"] is None:
        return None
    # "Buy-CE signal: highest high in W <= ORH AND move is DOWN."
    if s["w_high"] <= s["orh"] and s["move"] == "DOWN":
        return "CE"
    # "Otherwise buy-PE signal: lowest low in W >= ORL AND move is UP."
    if s["w_low"] >= s["orl"] and s["move"] == "UP":
        return "PE"
    # "No trade when both edges were broken, the move has no direction, or the surviving edge and the move disagree."
    return None


def repo_orr_edge_survived(ctx, decision_time="11:30", opening_range_minutes=5):
    s = _orr_setup(ctx, decision_time, opening_range_minutes)
    side = _edge_survived_side(s)
    if side is None:
        return None
    return (decision_time, "UP" if side == "CE" else "DOWN")


EXH_DECISION_TIME = "11:30"   # "with OR = 5 (09:15..09:19) and T = 11:30 fixed"
EXH_OR_MINUTES = 5
EXH_RSI_CLOSES = 15           # "RSI by plain averages on the last 15 closes of W (14 changes)"


def repo_orr_exhaustion(ctx, rsi_distance_from_50=10, sd_stretch_min=1.0):
    s = _orr_setup(ctx, EXH_DECISION_TIME, EXH_OR_MINUTES)
    side = _edge_survived_side(s)                # "Start from repo_orr_edge_survived ..."
    if side is None:
        return None
    closes = [r[4] for r in s["w"]]
    close_t = closes[-1]

    # (1) "avgGain = sum of rises / 14, avgLoss = sum of falls / 14, RSI = 100 - 100/(1 + avgGain/avgLoss);
    #      RSI = 100 if there are no falls."
    if len(closes) < EXH_RSI_CLOSES:
        return None
    last = closes[-EXH_RSI_CLOSES:]
    changes = [b - a for a, b in zip(last, last[1:])]
    n_ch = EXH_RSI_CLOSES - 1
    avg_gain = sum(c for c in changes if c > 0) / n_ch
    avg_loss = sum(-c for c in changes if c < 0) / n_ch
    rsi = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    # "Need RSI <= 40 for CE, RSI >= 60 for PE."  (40 = 50 - x, 60 = 50 + x, x = rsi_distance_from_50)
    if side == "CE" and not rsi <= 50 - rsi_distance_from_50:
        return None
    if side == "PE" and not rsi >= 50 + rsi_distance_from_50:
        return None

    # (2) "mean and population standard deviation (divide by n) of all closes in W; need (mean - close(T))/sd >= 1.0
    #      for CE, (close(T) - mean)/sd >= 1.0 for PE; sd = 0 means no trade."
    n = len(closes)
    mean = sum(closes) / n
    sd = (sum((c - mean) ** 2 for c in closes) / n) ** 0.5
    if sd == 0:
        return None
    stretch = (mean - close_t) / sd if side == "CE" else (close_t - mean) / sd
    if not stretch >= sd_stretch_min:
        return None

    # (3) "The candle stamped T itself must still move with the move being faded: close < open for CE,
    #      close > open for PE."
    bar_t = s["bar_t"]
    if side == "CE" and not bar_t[4] < bar_t[1]:
        return None
    if side == "PE" and not bar_t[4] > bar_t[1]:
        return None
    return (EXH_DECISION_TIME, "UP" if side == "CE" else "DOWN")


# ---------------------------------------------------------------------------
# stretch fade: daily values from earlier sessions
# ---------------------------------------------------------------------------
_HL_CACHE: dict = {}       # (index, session date) -> (high, low) of a COMPLETED earlier session (never today)


def _session_high_low(ctx, d: str):
    """"high = highest high and low = lowest low of 09:15..15:29" of earlier session d."""
    key = (ctx.index, d)
    hl = _HL_CACHE.get(key)
    if hl is None:
        rows = [r for r in ctx.session(d) if "09:15" <= r[0] <= "15:29"]
        hl = _HL_CACHE[key] = (max(r[2] for r in rows), min(r[3] for r in rows))
    return hl


def _daily_stats(ctx, n: int):
    """For the n sessions before today (oldest first): list of (high, low, true range).
    None when there are fewer than n + 1 earlier sessions (each true range needs the close before it).
    "True range of a session = max(high - low, |high - previous session's house close|,
     |low - previous session's house close|)"; close = house daily close."""
    prev = ctx.prev_sessions
    if len(prev) < n + 1:
        return None
    out = []
    for i in range(len(prev) - n, len(prev)):
        try:
            high, low = _session_high_low(ctx, prev[i])
            pc = ctx.house_close(prev[i - 1])
        except (ValueError, KeyError):
            return None
        out.append((high, low, max(high - low, abs(high - pc), abs(low - pc))))
    return out


def _close_at(ctx, hhmm_: str):
    """Close of today's candle stamped exactly hhmm_, None if it is not (yet) there."""
    for r in ctx.bars:
        if r[0] == hhmm_:
            return r[4]
        if r[0] > hhmm_:
            return None
    return None


SF_DECISION_TIME = "11:00"    # "At the single decision minute 11:00 (candle stamped 11:00, complete)"
SF_ADR_SESSIONS = 14          # "ADR = simple average of the true range of the 14 sessions before today"


def repo_stretch_fade_1100(ctx, stretch_threshold_adr=0.75, lookback_sessions=5):
    c = _close_at(ctx, SF_DECISION_TIME)
    if c is None:
        return None
    stats = _daily_stats(ctx, SF_ADR_SESSIONS)
    if stats is None or len(ctx.prev_sessions) < lookback_sessions:
        return None
    adr = sum(s[2] for s in stats) / SF_ADR_SESSIONS
    if adr == 0:
        return None
    # "REF = house daily close of the session L = 5 sessions before today (yesterday is 1 session before)"
    try:
        ref = ctx.house_close(ctx.prev_sessions[-lookback_sessions])
    except (ValueError, KeyError):
        return None
    # "stretch = (close of the 11:00 candle - REF) / ADR. stretch > +0.75: DOWN signal. stretch < -0.75: UP signal."
    stretch = (c - ref) / adr
    if stretch > stretch_threshold_adr:
        return (SF_DECISION_TIME, "DOWN")
    if stretch < -stretch_threshold_adr:
        return (SF_DECISION_TIME, "UP")
    return None


LR_GATE_TIME = "11:00"        # "Step A, gate at the 11:00 candle (complete)"
LR_RANGE_SESSIONS = 10        # "R = simple average true range of the 10 sessions before today"
LR_REF_SESSIONS = 5           # "house close of the session 5 sessions before today"
LR_TOUCH_FROM = "11:01"       # "the first 1-minute candle stamped 11:01 or later"
LR_SIGNAL_TF = 10             # "10-minute candles aligned to 09:15 (last minutes 09:24, 09:34, ...)"
LR_CONFIRM_TF = 15            # "the most recent 15-minute candle (aligned to 09:15) whose last minute is <= m"


def repo_stretch_fade_line_reject(ctx, stretch_threshold=0.8, last_signal_time="12:30"):
    # ---- Step A: the gate at 11:00 ----
    c = _close_at(ctx, LR_GATE_TIME)
    if c is None:
        return None
    stats = _daily_stats(ctx, LR_RANGE_SESSIONS)
    if stats is None or len(ctx.prev_sessions) < LR_REF_SESSIONS:
        return None
    r_avg = sum(s[2] for s in stats) / LR_RANGE_SESSIONS
    if r_avg == 0:
        return None
    try:
        ref = ctx.house_close(ctx.prev_sessions[-LR_REF_SESSIONS])
    except (ValueError, KeyError):
        return None
    hh = max(s[0] for s in stats)
    ll = min(s[1] for s in stats)
    s1 = (c - ref) / r_avg                       # "s1 = (C - house close of the session 5 sessions before today) / R"
    s2 = (c - (hh + ll) / 2.0) / r_avg           # "s2 = (C - (highest high + lowest low of the 10 sessions ...) / 2) / R"
    if max(s1, s2) > stretch_threshold and min(s1, s2) >= 0:
        put_day = True                           # "PUT day if max(s1, s2) > 0.8 AND min(s1, s2) >= 0."
    elif min(s1, s2) < -stretch_threshold and max(s1, s2) <= 0:
        put_day = False                          # "CALL day if min(s1, s2) < -0.8 AND max(s1, s2) <= 0."
    else:
        return None                              # "Otherwise no trade today."

    # ---- Steps B, C, D: one forward pass over today's candles ----
    last_min = min(_min(last_signal_time), _min(SIGNAL_LAST))
    touch_from = _min(LR_TOUCH_FROM)
    by_min = {}                                  # minute -> row, filled as the scan advances
    total, count = 0.0, 0                        # running sum of closes: LINE(t) = total / count
    touched = False
    for r in ctx.bars:
        m = _min(r[0])
        if m < SESSION_OPEN:
            continue
        if m > last_min:
            return None
        by_min[m] = r
        total += r[4]
        count += 1
        line = total / count                     # "LINE(t) = arithmetic mean of today's 1-minute closes from 09:15 through t"
        if m < touch_from:
            continue
        if not touched:
            # "Touch minute u = the first 1-minute candle stamped 11:01 or later with high >= LINE(u) on a PUT day
            #  (low <= LINE(u) on a CALL day)."
            touched = (r[2] >= line) if put_day else (r[3] <= line)
        if not touched:
            continue
        # "Signal candle = the first 10-minute candle whose last minute m satisfies u <= m <= 12:30 and whose
        #  1-minute close at m is < LINE(m) on a PUT day (> LINE(m) on a CALL day)."
        if (m - SESSION_OPEN) % LR_SIGNAL_TF != LR_SIGNAL_TF - 1:
            continue
        rejected = (r[4] < line) if put_day else (r[4] > line)
        if not rejected:
            continue
        # ---- Step D: "Only the day's FIRST signal candle is examined" ----
        k = (m - SESSION_OPEN + 1) // LR_CONFIRM_TF          # number of 15-minute candles complete by the end of m
        if k < 1:
            return None
        start = SESSION_OPEN + (k - 1) * LR_CONFIRM_TF
        rows15 = [by_min[x] for x in range(start, start + LR_CONFIRM_TF) if x in by_min]
        if not rows15:
            return None
        mid = (max(x[2] for x in rows15) + min(x[3] for x in rows15)) / 2.0
        # "on a PUT day close(m) must be < (its high + its low)/2, on a CALL day close(m) must be > that midpoint"
        confirmed = (r[4] < mid) if put_day else (r[4] > mid)
        if not confirmed:
            return None                          # "not confirmed means no trade today"
        t = _hhmm(m)
        if not _admissible(t):
            return None
        return (t, "DOWN" if put_day else "UP")
    return None


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------
def _neighbours(centre: dict, moves: list) -> list:
    """moves = [(param, value, text of the value as written in library.json), ...] in library order."""
    out = []
    for param, value, text in moves:
        p = dict(centre)
        p[param] = value
        out.append({"label": f"{param}={text}", "params": p})
    return out


_ORR_CENTRE = {"decision_time": "11:30", "opening_range_minutes": 5}
_ORR_MOVES = [("decision_time", "11:15", "11:15"), ("decision_time", "11:45", "11:45"),
              ("opening_range_minutes", 3, "3"), ("opening_range_minutes", 15, "15")]
_EXH_CENTRE = {"rsi_distance_from_50": 10, "sd_stretch_min": 1.0}
_SF_CENTRE = {"stretch_threshold_adr": 0.75, "lookback_sessions": 5}
_LR_CENTRE = {"stretch_threshold": 0.8, "last_signal_time": "12:30"}

CANDIDATES = {
    "repo_orr_outside_range": {
        "fn": repo_orr_outside_range,
        "centre": dict(_ORR_CENTRE),
        "neighbours": _neighbours(_ORR_CENTRE, _ORR_MOVES),
    },
    "repo_orr_edge_survived": {
        "fn": repo_orr_edge_survived,
        "centre": dict(_ORR_CENTRE),
        "neighbours": _neighbours(_ORR_CENTRE, _ORR_MOVES),
    },
    "repo_orr_exhaustion": {
        "fn": repo_orr_exhaustion,
        "centre": dict(_EXH_CENTRE),
        "neighbours": _neighbours(_EXH_CENTRE, [
            ("rsi_distance_from_50", 5, "5"), ("rsi_distance_from_50", 15, "15"),
            ("sd_stretch_min", 0.75, "0.75"), ("sd_stretch_min", 1.25, "1.25")]),
    },
    "repo_stretch_fade_1100": {
        "fn": repo_stretch_fade_1100,
        "centre": dict(_SF_CENTRE),
        "neighbours": _neighbours(_SF_CENTRE, [
            ("stretch_threshold_adr", 0.5, "0.5"), ("stretch_threshold_adr", 1.0, "1.0"),
            ("lookback_sessions", 3, "3"), ("lookback_sessions", 7, "7")]),
    },
    "repo_stretch_fade_line_reject": {
        "fn": repo_stretch_fade_line_reject,
        "centre": dict(_LR_CENTRE),
        "neighbours": _neighbours(_LR_CENTRE, [
            ("stretch_threshold", 0.6, "0.6"), ("stretch_threshold", 1.0, "1.0"),
            ("last_signal_time", "12:00", "12:00"), ("last_signal_time", "13:00", "13:00")]),
    },
}


# ---------------------------------------------------------------------------
# self-check: signals only (day, minute, direction) - never what happened after a signal
# ---------------------------------------------------------------------------
def _selfcheck() -> int:
    import json
    import ctx as C

    problems, summary = [], {}
    for index in C.INDEXES:
        m = C.Market(index)
        days = [d for d in m.sessions if C.WINDOW_START <= d <= C.DISCOVERY_END]
        for cid, cand in CANDIDATES.items():
            cells = [("centre", cand["centre"])] + [(nb["label"], nb["params"]) for nb in cand["neighbours"]]
            for label, params in cells:
                n = up = 0
                tmin = tmax = None
                for d in days:
                    dc = m.day_ctx(d)
                    try:
                        problems += C.check_no_lookahead(cand["fn"], dc, params)
                        r = cand["fn"](dc, **params)
                    except Exception as e:                    # noqa: BLE001 - reported, not hidden
                        problems.append(f"{index} {d} {cid} {label}: raised {type(e).__name__}: {e}")
                        continue
                    if r is None:
                        continue
                    n += 1
                    up += r[1] == "UP"
                    tmin = r[0] if tmin is None or r[0] < tmin else tmin
                    tmax = r[0] if tmax is None or r[0] > tmax else tmax
                summary.setdefault(cid, {}).setdefault(label, {})[index] = {
                    "days": len(days), "signals": n, "UP": up, "DOWN": n - up, "earliest": tmin, "latest": tmax}
    print(json.dumps(summary, indent=1))
    print(f"look-ahead / exception problems: {len(problems)}")
    for p in problems[:40]:
        print("  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    import sys
    sys.exit(_selfcheck())
