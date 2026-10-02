"""5-Day Stretch Fade - v3: fade a stretched NIFTY on a confirmed rejection of the day's average line, with a real 1:2
in rupees - a stop that follows volatility and a target of twice the stop plus the cost of the fills.

THE PROMPT (the user, 2026-09-29): "if we do not enter at the right entry point the risk is higher than the reward - so
find the exact thing ... if you risk 25 points in the nifty the target is only 50, think like that and then for premium
too; you can place the stop based on the volatility too but your reward is to be 2x ... use multiple time frame
analysis - use only the 1 min candle for the backtest but the open/high/low/close of multiple time frames", then
"make this as v3" - the rule found in that day's precise-entry research (scratchpad; summarised below).

THE RULE   (range = the average daily range of the last 10 sessions, true range - high to low, or the gap from the
            previous close when bigger - simple average; about 224 NIFTY points this year)
  Step 1  At 11:00 (the 11:00 one-minute candle complete), measure NIFTY's 11:00 close against two references:
            the official close 5 sessions ago, and the middle of the last 10 sessions' range ((highest high + lowest
            low) / 2).  Stretch = (11:00 close - reference) / range.
  Step 2  If either stretch is beyond 0.8 (and they do not point opposite ways): stretched UP -> buy a PUT,
          stretched DOWN -> buy a CALL.  Otherwise no trade today.
  Step 3  THE LINE = the average of today's NIFTY 1-minute closes since 09:15 (every minute counts once; no volume).
          From 11:01, once a minute trades at or above the line (a PUT day; at or below on a CALL day) the line is
          'touched'; the SIGNAL is a 10-minute candle (aligned to 09:15) that then closes back below the line (above it
          on a CALL day), its last minute's close read against the line at that minute.
  Step 4  CONFIRMATION (15-minute candles): at the signal, NIFTY's close must be below the middle ((high + low) / 2) of
          the last finished 15-minute candle (above it on a CALL day).  The day's FIRST signal decides: not confirmed
          -> no trade today.  If it is confirmed but the option cannot be bought (step 5), the next confirmed signal is
          taken.  Signals are read until 12:30.
  Step 5  Buy the 6-in-the-money option (strike from the 11:00 close, nearest expiry at least a day after today) in
          the first minute after the signal that traded (to 3 minutes), at that minute's HIGH.
  Step 6  Levels, set when that minute is complete, from NIFTY's LOW in it (a PUT; its HIGH on a CALL) - the NIFTY
          price that matches the worst fill:
            STOP   = 1 x the 15-minute ATR (average true range of the last 8 finished 15-minute candles) against;
            TARGET = 2 x the stop + 1.5 x the 1-minute range (average high-low of the last 30 one-minute candles) in
                     favour - the extra pays for the worst-price fills, so a target pays about twice a stop in rupees.
  Step 7  Read on NIFTY's completed minutes from the next minute to 15:13 (a PUT's stop on NIFTY's HIGH, its target on
          NIFTY's LOW; a CALL the other way; a minute that touches both = the stop).  Sell in the next minute the option
          traded, at its LOW (to 15:29).  Neither by 15:13: sell from 15:14 at the minute's LOW.  One trade a day.

CHECKLIST (RUN.md step 1) - all clear from the research rule, nothing assumed beyond these fill details:
  underlying NIFTY 50 (1m) | window: shared START_DATE..END_DATE, run on 2025-09-29..2026-09-25 | decision 11:00;
  entry on 10-minute candles, confirmed on 15-minute candles, stop from 15-minute candles, target allowance from
  1-minute candles, all built from the 1-minute candles, completed candles only | index_options, buy, 6 ITM, 1 lot,
  qty from the contract, expiry nearest >= 1 day after the trade day | exits steps 6-7 | intraday | standard option
  costs | missing data -> no trade, logged.  A zero-volume option minute is never a fill: the entry takes the first
  traded minute within 3 minutes of the signal, a sale the first traded minute after its signal (to 15:29).

WHERE IT COMES FROM (scratchpad research, 2026-09-29, real option candles, worst fills; all in-sample on one year)
  - From the older entry (a 10-minute close back through the line, no confirmation) 76% of trades were right by 15:14,
    but the winners first went a median 23 NIFTY points against the entry (1 in 4 went 39+): a 25-point stop killed
    about half of them.  The 15-minute confirmation is what makes the entry precise enough for a real stop.
  - Friction: a traded option minute's high-low is a median 5.2 premium points and the 6-ITM option moves about 0.8 x
    NIFTY; with a plain 2 x stop target a target paid 1.83 x a stop in rupees, with 1.5 x the 1-minute range added it
    paid 2.03 x.
  - About 39,000 settings were searched (entry families, confirmations on 5 to 60-minute candles, stop shapes); out of
    sample (settings chosen on three quarters, traded on the fourth) the family made 84-87 trades a year at 58-61% won.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *          # noqa: F401,F403
from py_funcs import _admits    # the panel's own filter test, reused for the rule's trades
import argparse
import numpy as np

CATEGORY = "index_options"
SLUG = "stretch_fade_v3"
SIGNAL_MIN = "11:00"            # the decision candle
CUT_RULE = "12:30"              # the last minute a signal candle may end, in the rule
CUT_MAX = "13:30"               # signals are simulated to here; 'Entries until' selects among them
BANDS = (("12:30", "by 12:30"), ("13:00", "12:30-13:00"), ("13:30", "13:00-13:30"))
TIME_EXIT = "15:14"
LAST_MIN = "15:29"              # a working sell order waits at most until the last minute
SETUP_TF = 10                   # the signal candle, minutes, aligned to 09:15
CONFIRM_TFS = (5, 15, 30)       # candles whose middle may confirm the signal (15 = the rule)
CONFIRM_RULE = 15
STEP = strike_step()             # 50 on NIFTY, 100 on SENSEX - read from the contract list
LOTS = 1
RANGE_N = 10                    # sessions in the average daily range (true range)
CLOSE_BACK = 5                  # reference 1: the official close this many sessions ago
MID_N = 10                      # reference 2: the middle of this many sessions' high-low range
STRETCH_RULE = 0.8
ATR_TF, ATR_N = 15, 8           # the stop's volatility: average true range of the last 8 finished 15-minute candles
FILL_N = 30                     # the fill allowance's unit: average high-low of the last 30 one-minute candles
STOP_RULE = "atr1"
ALLOW_RULE = 1.5
QUIET = 0.35                    # 'Skip quiet days' (off in the rule): today's range so far x the average range
FILL_WAIT = 2                   # entry: wait up to 2 more minutes for a traded option minute
DAILY_LOOKBACK_DAYS = 45        # calendar days of daily candles before --from (10 + 1 sessions and holidays)
ROWS_PER_SESSION = 375
SPLIT = "2026-04-01"            # option STT 0.10% -> 0.15% of the sale; also the research's halves
DEFAULT_LADDER = "6"
UP_DIR, DOWN_DIR = "stretched up: buy PE", "stretched down: buy CE"
REF_LABEL = {"close5": f"close {CLOSE_BACK} sessions ago", "mid10": f"middle of the {MID_N}-day range"}
REASON = {"stop": "stop", "target": "target", "time": "time exit 15:14"}
STOPS = {"atr0.75": ("atr", 0.75), "atr1": ("atr", 1.0), "atr1.25": ("atr", 1.25),
         "pts25": ("pts", 25.0), "pts30": ("pts", 30.0), "pts40": ("pts", 40.0)}


def rung_label(v: int) -> str:
    return "at the money" if v == 0 else f"{abs(v)} strikes {'in' if v > 0 else 'out of'} the money"


def stop_label(k: str) -> str:
    kind, x = STOPS[k]
    s = (f"{x:g} x the 15-minute ATR" if kind == "atr" else f"fixed {x:g} NIFTY points")
    return s + (" (the rule)" if k == STOP_RULE else "")


def mi(hhmm: str) -> int:
    """HH:MM -> minute index of the session (09:15 = 0)."""
    return hhmm_minutes(hhmm) - hhmm_minutes("09:15")


def hm_of(k: int) -> str:
    m = hhmm_minutes("09:15") + k
    return f"{m // 60:02d}:{m % 60:02d}"


# The control panel.  Defaults = the rule.  Every sweep value is simulated on its own: the confirmation decides WHICH
# signal is traded (a day whose first signal fails one check can pass another), the stretch can move a day's side,
# and the stop and target change every exit.  'Entries until', 'Skip quiet days' and 'Which side' only remove trades.
SETTINGS = [
    setting("stretch", "Stretch needed", kind="entry", default=str(STRETCH_RULE),
            help="how far NIFTY at 11:00 must be from the reference, in average daily ranges",
            options=[{"value": str(v), "raw": v, "label": f"beyond {v} x the range" + (" (the rule)" if v == STRETCH_RULE else "")}
                     for v in (0.7, 0.8, 0.9)]),
    setting("confirm", "Confirmation candle", kind="entry", default=str(CONFIRM_RULE),
            help="at the signal, NIFTY must be past the middle of the last finished candle of this size "
                 "(below it on a PUT day); the day's first signal decides",
            options=[{"value": "15", "raw": 15, "label": "past the middle of the last 15-minute candle (the rule)"},
                     {"value": "5", "raw": 5, "label": "past the middle of the last 5-minute candle"},
                     {"value": "30", "raw": 30, "label": "past the middle of the last 30-minute candle"},
                     {"value": "none", "raw": None, "label": "no confirmation"}]),
    setting("until", "Entries until", kind="entry", mode="filter", default=CUT_RULE,
            help="the last time a signal candle may end; later signals of the same rule are simulated and tagged",
            options=[{"value": "12:30", "label": "12:30 (the rule)", "tag": {"entry window": ["by 12:30"]}},
                     {"value": "13:00", "label": "13:00", "tag": {"entry window": ["by 12:30", "12:30-13:00"]}},
                     {"value": "13:30", "label": "13:30", "tag": None}]),
    setting("quiet", "Skip quiet days", kind="entry", mode="filter", default="off",
            help=f"drop the trade when today's range at the signal is under {QUIET} x the average range",
            options=[{"value": "off", "label": "no (the rule)", "tag": None},
                     {"value": str(QUIET), "label": f"skip when today's range so far is under {QUIET} x the average",
                      "tag": {"quiet day": ["no"]}}]),
    setting("side_pick", "Which side", kind="entry", mode="filter", default="both",
            help="each day is one side only, so 'both' is the whole book",
            options=[{"value": "both", "label": "both (the rule)", "tag": None},
                     {"value": "CE", "label": "calls only (stretched down)", "tag": {"direction": [DOWN_DIR]}},
                     {"value": "PE", "label": "puts only (stretched up)", "tag": {"direction": [UP_DIR]}}]),
    setting("stop", "Stop", kind="exit", default=STOP_RULE,
            help="NIFTY this far against the entry level; the 15-minute ATR is the average true range of the last "
                 "8 finished 15-minute candles (about 40 points on a normal day)",
            options=[{"value": k, "raw": k, "label": stop_label(k)} for k in STOPS]),
    setting("allow", "Target", kind="exit", default=str(ALLOW_RULE),
            help="2 x the stop in the trade's favour, plus this many 1-minute ranges (average high-low of the last 30 "
                 "minutes, about 7 points) to pay for the worst-price fills",
            options=[{"value": "0", "raw": 0.0, "label": "2 x the stop"},
                     {"value": "1.5", "raw": 1.5, "label": "2 x the stop + 1.5 x the 1-minute range (the rule)"},
                     {"value": "2", "raw": 2.0, "label": "2 x the stop + 2 x the 1-minute range"}]),
    setting("moneyness", "Strike depth", kind="strike", default=6, rerun=True,
            options=[{"value": v, "label": rung_label(v), "raw": v} for v in STRIKE_LADDER],
            help="--moneyness 6,4 prices the 4-ITM rung on the same days"),
]


def options_of(settings: list[dict], key: str) -> list[tuple[str, object]]:
    return [(o["value"], o["raw"]) for o in next(s for s in settings if s["key"] == key)["options"]]


# ---------------------------------------------------------------------------
# signal pieces (pure, completed candles only)
# ---------------------------------------------------------------------------
def day_facts(daily: list[list], d: str) -> dict | None:
    """From DAILY candles [[day, o, h, l, c], ...] (official): the 10-session average true range, the close 5
    sessions back and the middle of the last 10 sessions' range - all from sessions BEFORE `d`."""
    days = [r[0] for r in daily]
    if d not in days:
        return None
    j = days.index(d)
    if j < max(RANGE_N + 1, CLOSE_BACK, MID_N):
        return None
    tr = [max(daily[k][2] - daily[k][3], abs(daily[k][2] - daily[k - 1][4]), abs(daily[k][3] - daily[k - 1][4]))
          for k in range(j - RANGE_N, j)]
    hi = max(r[2] for r in daily[j - MID_N:j]); lo = min(r[3] for r in daily[j - MID_N:j])
    return {"range": sum(tr) / RANGE_N, "close5": daily[j - CLOSE_BACK][4], "close5_day": daily[j - CLOSE_BACK][0],
            "mid10": (hi + lo) / 2}


def side_of(c1100: float, facts: dict, th: float) -> tuple[int, dict]:
    """(+1 CALL / -1 PUT / 0 no trade, {ref: stretch}).  A stretched-up reference asks for a PUT; references that
    are beyond the threshold must agree."""
    xs = {r: (c1100 - facts[r]) / facts["range"] for r in ("close5", "mid10")}
    sides = {(-1 if x > 0 else 1) for x in xs.values() if abs(x) > th}
    return (sides.pop() if len(sides) == 1 else 0), xs


def day_arrays(rows: list[list]) -> dict:
    """NIFTY's high, low and close by session minute, and what the rule reads at every minute t - each from candles
    finished by t: the day's average line, the 15-minute ATR, the 1-minute range, and the last finished 5 / 15 /
    30-minute candle's middle."""
    A = np.full((ROWS_PER_SESSION, 3), np.nan)
    for r in rows:
        k = mi(r[0])
        if 0 <= k < ROWS_PER_SESSION:
            A[k] = (r[2], r[3], r[4])
    H, L, C = A[:, 0], A[:, 1], A[:, 2]
    n = np.cumsum(np.isfinite(C))
    with np.errstate(invalid="ignore", divide="ignore"):
        line = np.where(n > 0, np.nancumsum(C) / n, np.nan)
    t_ = np.arange(ROWS_PER_SESSION)
    # the 15-minute ATR: true range of each finished 15-minute candle (the gap from the previous candle's close counts)
    nb = ROWS_PER_SESSION // ATR_TF
    bh = np.array([np.nanmax(H[q * ATR_TF:(q + 1) * ATR_TF]) for q in range(nb)])
    bl = np.array([np.nanmin(L[q * ATR_TF:(q + 1) * ATR_TF]) for q in range(nb)])
    bc = C[ATR_TF - 1::ATR_TF][:nb]
    pc = np.r_[np.nan, bc[:-1]]
    tr = np.maximum(bh - bl, np.nan_to_num(np.maximum(abs(bh - pc), abs(bl - pc)), nan=0))
    atr = np.full(ROWS_PER_SESSION, np.nan)
    for t in t_:
        b = (t + 1) // ATR_TF - 1
        if b >= 0:
            atr[t] = tr[max(0, b - ATR_N + 1):b + 1].mean()
    # the 1-minute range: average high-low of the last 30 one-minute candles
    cs = np.r_[0, np.nancumsum(H - L)]
    lo_k = np.maximum(0, t_ - FILL_N + 1)
    rng1 = (cs[t_ + 1] - cs[lo_k]) / (t_ + 1 - lo_k)
    mids = {}
    for tf in CONFIRM_TFS:
        b = (t_ + 1) // tf - 1
        m = np.full(ROWS_PER_SESSION, np.nan)
        for t in t_[b >= 0]:
            q = b[t]
            m[t] = (np.nanmax(H[q * tf:(q + 1) * tf]) + np.nanmin(L[q * tf:(q + 1) * tf])) / 2
        mids[tf] = m
    return {"H": H, "L": L, "C": C, "line": line, "atr": atr, "rng1": rng1, "mid": mids}


def confirmed(D: dict, t: int, side: int, tf: int | None) -> bool:
    """NIFTY's close at t past the middle of the last finished tf-minute candle, on the trade's side."""
    if tf is None:
        return True
    m = D["mid"][tf][t]
    return bool(np.isfinite(m) and ((D["C"][t] < m) if side < 0 else (D["C"][t] > m)))


def option_arrays(rows: list[list]) -> tuple:
    """(high, low, volume) by session minute, and the sorted minutes that TRADED (volume > 0)."""
    A = np.full((ROWS_PER_SESSION, 3), np.nan)
    for r in rows:
        k = mi(r[0])
        if 0 <= k < ROWS_PER_SESSION:
            A[k] = (r[2], r[3], r[5])
    return A, np.where(np.nan_to_num(A[:, 2]) > 0)[0]


def next_traded(traded: np.ndarray, k: int, last: int = ROWS_PER_SESSION - 1) -> int | None:
    j = np.searchsorted(traded, k)
    return int(traded[j]) if j < len(traded) and traded[j] <= last else None


def band_of(t: int) -> str:
    return next(lab for until, lab in BANDS if t <= mi(until))


# ---------------------------------------------------------------------------
# simulate one day for one setting (pure)
# ---------------------------------------------------------------------------
def simulate_day(D: dict, side: int, conf: int | None, stop: str, allow: float, opt) -> tuple[dict | None, dict]:
    """Steps 3-7 for one side: (the trade or None, what the day's first signal was).  The first signal decides; if it
    is confirmed but cannot be bought or sold, the next confirmed signal is taken."""
    H, L, C, line = D["H"], D["L"], D["C"], D["line"]
    arr, traded = opt
    t0, cut, tx = mi(SIGNAL_MIN), mi(CUT_MAX), mi(TIME_EXIT)
    touched = False
    first = {"t": None, "ok": None, "unfilled": 0}
    for t in range(t0 + 1, cut + 1):
        v = line[t]
        if not np.isfinite(v):
            continue
        if (H[t] >= v) if side < 0 else (L[t] <= v):
            touched = True
        if not touched or (t + 1) % SETUP_TF or not ((C[t] < v) if side < 0 else (C[t] > v)):
            continue
        ok = confirmed(D, t, side, conf)
        if first["t"] is None:
            first.update(t=t, ok=ok)
            if not ok:
                return None, first                     # the day's first signal is not confirmed: no trade today
        if not ok:
            continue
        ke = next_traded(traded, t + 1, last=t + 1 + FILL_WAIT)
        if ke is None or ke >= tx:
            first["unfilled"] += 1
            continue
        e = L[ke] if side < 0 else H[ke]               # NIFTY at our worst fill
        kind, x = STOPS[stop]
        R = x * D["atr"][ke] if kind == "atr" else x
        extra = allow * D["rng1"][ke]
        s_lvl, t_lvl = e - side * R, e + side * (2 * R + extra)
        worst = L[ke + 1:tx] if side > 0 else H[ke + 1:tx]
        best = H[ke + 1:tx] if side > 0 else L[ke + 1:tx]
        hs = np.nonzero((worst - s_lvl) * side <= 0)[0]; ht = np.nonzero((best - t_lvl) * side >= 0)[0]
        ks = hs[0] if len(hs) else None; kt = ht[0] if len(ht) else None
        if ks is not None and (kt is None or ks <= kt):
            why, trig = "stop", ke + 1 + ks
        elif kt is not None:
            why, trig = "target", ke + 1 + kt
        else:
            why, trig = "time", None
        xk = next_traded(traded, trig + 1) if trig is not None else next_traded(traded, tx)
        if xk is None:
            first["unfilled"] += 1
            continue                                   # could not be sold: not a trade; the next signal is read
        used = (np.nanmax(H[:t + 1]) - np.nanmin(L[:t + 1]))
        return ({"signal": t, "ek": ke, "xk": xk, "why": why, "lvl": e, "R": R, "extra": extra, "stop_lvl": s_lvl,
                 "tgt_lvl": t_lvl, "line": v, "used_pts": used, "first": t == first["t"],
                 "checks": {tf: confirmed(D, t, side, tf) for tf in CONFIRM_TFS},
                 "mid": {tf: D["mid"][tf][t] for tf in CONFIRM_TFS},
                 "entry_px": arr[ke, 0], "exit_px": arr[xk, 1]}, first)
    return None, first


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
async def run(frm: date, to: date, settings: list[dict]):
    now = datetime.now(IST)
    skips: list[str] = []
    log: list[dict] = []
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list[list]]] = {}
    rungs = [r for _, r in options_of(settings, "moneyness")]
    ths = [r for _, r in options_of(settings, "stretch")]
    confs, stops, allows = options_of(settings, "confirm"), options_of(settings, "stop"), options_of(settings, "allow")
    rule = default_combo(settings)
    chart_rung = rule["moneyness"]
    broker_line = None
    async with Upstox() as up:
        key = (await up.find_instrument(instrument()))["instrument_key"]
        info = await up.option_chain_info(key)
        if info["strike_step"] != STEP:
            raise SystemExit(f"Upstox strike step is {info['strike_step']}, the rule assumes {STEP}.")
        sessions = await up.minute_sessions(key, frm, to)
        dc = await up.candles(key, "1d", frm - timedelta(days=DAILY_LOOKBACK_DAYS), to)
        daily = [[c["timestamp"][:10], c["open"], c["high"], c["low"], c["close"]] for c in dc]
        cal = await up.expiry_calendar(key, frm, to)
        full = {d: r for d, r in sessions.items()
                if len(r) >= ROWS_PER_SESSION and not (d == now.date().isoformat() and now.strftime("%H:%M") < "15:45")}
        for d, r in sessions.items():
            if d not in full and frm.isoformat() <= d <= to.isoformat():
                skips.append(f"{d}: session incomplete ({len(r)} bars) - not used")
                log.append(session_row(d, "no data", f"session incomplete: {len(r)} of {ROWS_PER_SESSION} candles"))
        days = [d for d in sorted(full) if frm.isoformat() <= d <= to.isoformat()]
        print(f"NIFTY sessions in window: {len(days)}; daily candles from {daily[0][0] if daily else '-'}")
        print(f"strike ladder {[rung_label(v) for v in rungs]}: {fetch_estimate(len(days) * len(rungs))} "
              f"(fewer with the candle cache).")
        for d in days:
            rows = full[d]
            facts = day_facts(daily, d)
            if facts is None:
                skips.append(f"{d}: not enough daily candles before it")
                log.append(session_row(d, "no data", f"not enough daily candles before this day for the {RANGE_N}-session range"))
                continue
            D = day_arrays(rows)
            k11 = mi(SIGNAL_MIN)
            if not np.isfinite(D["C"][k11]):
                skips.append(f"{d}: the 11:00 candle is missing")
                log.append(session_row(d, "no data", "the 11:00 candle is missing"))
                continue
            c1100 = float(D["C"][k11]); rng = facts["range"]
            base = {"11:00 NIFTY": c1100, REF_LABEL["close5"]: facts["close5"], REF_LABEL["mid10"]: facts["mid10"],
                    f"average range ({RANGE_N} sessions)": rng,
                    "stretch vs close 5 back": (c1100 - facts["close5"]) / rng,
                    "stretch vs 10-day middle": (c1100 - facts["mid10"]) / rng}
            want = {th: side_of(c1100, facts, th)[0] for th in ths}
            sides = {s for s in want.values() if s}
            rule_side = want[rule["stretch"]]
            if not sides:
                log.append(session_row(d, "no signal", f"not stretched beyond {min(ths)} x the range on either reference", **base))
                continue
            expiry = next_expiry(cal, date.fromisoformat(d), 1)
            if expiry is None:
                skips.append(f"{d}: no expiry at least a day after it")
                log.append(session_row(d, "no data", "no expiry at least a day after this day", **base))
                continue
            contracts = {}                                          # (side, rung) -> (contract, qty, arrays, rows, rows5)
            for s in sorted(sides):
                typ = "CE" if s > 0 else "PE"
                for steps in rungs:
                    strike = strike_offset(c1100, STEP, steps, typ, itm=True)
                    c = await up.resolve_option(key, expiry, strike, typ)
                    if c is None or int(c.get("lot_size") or 0) <= 0:
                        skips.append(f"{d} [{steps} ITM {typ}]: contract {expiry} {strike:.0f} {typ} not found")
                        continue
                    orows = await up.option_candles(c, date.fromisoformat(d), volume=True)
                    if not orows:
                        skips.append(f"{d} [{steps} ITM {typ}]: no option candles ({c['trading_symbol']})")
                        continue
                    contracts[(s, steps)] = (c, LOTS * c["lot_size"], option_arrays(orows), orows, [r[:5] for r in orows])
            rule_trade, rule_sig, rule_first, any_trade_today = None, None, None, False
            for th in ths:
                side = want[th]
                if not side:
                    continue
                xs = side_of(c1100, facts, th)[1]
                fired = [r for r, x in xs.items() if abs(x) > th and (-1 if x > 0 else 1) == side]
                which = "both" if len(fired) == 2 else REF_LABEL[fired[0]]
                size = max(abs(xs[r]) for r in fired)
                direction = UP_DIR if side < 0 else DOWN_DIR
                for steps in rungs:
                    got = contracts.get((side, steps))
                    if got is None:
                        continue
                    c, qty, opt, orows, rows5 = got
                    for cv, cf in confs:
                        for sv, sk in stops:
                            for av, al in allows:
                                is_rule = (th == rule["stretch"] and cf == rule["confirm"] and sk == rule["stop"]
                                           and al == rule["allow"] and steps == chart_rung)
                                sm, first = simulate_day(D, side, cf, sk, al, opt)
                                if is_rule:
                                    rule_first = first
                                if sm is None:
                                    continue
                                ebar, xbar = orows_at(orows, sm["ek"]), orows_at(orows, sm["xk"])
                                entry_px, exit_px = worst_fills("LONG", ebar, xbar)
                                # WORST FILL ONLY on every rung and setting - the report keeps one rung's candles
                                if entry_px != ebar[2] or exit_px != xbar[3] or ebar[5] <= 0 or xbar[5] <= 0:
                                    raise SystemExit(f"{d} {c['trading_symbol']}: fill is not the worst traded price")
                                mfe, mae = excursion(rows5, "LONG", entry_px, ebar[0], xbar[0])
                                sig_hm = hm_of(sm["signal"])
                                tgt_pts = 2 * sm["R"] + sm["extra"]
                                # every level on the rule's own sweep; entry / stop / target elsewhere (file size)
                                lv = [{"name": "entry level (NIFTY at the worst fill)", "price": sm["lvl"]},
                                      {"name": f"stop ({sm['R']:.0f} pts)", "price": sm["stop_lvl"]},
                                      {"name": f"target ({tgt_pts:.0f} pts)", "price": sm["tgt_lvl"]}]
                                full_detail = (th == rule["stretch"] and cf == rule["confirm"] and sk == rule["stop"]
                                               and al == rule["allow"])
                                if full_detail:
                                    lv = [{"name": REF_LABEL["close5"] + f" ({facts['close5_day']})", "price": facts["close5"]},
                                          {"name": REF_LABEL["mid10"], "price": facts["mid10"]},
                                          {"name": "day-average line at the signal", "price": sm["line"]},
                                          {"name": "last 15-minute candle's middle at the signal", "price": sm["mid"][15]}] + lv
                                t = make_trade(
                                    day=d, side="LONG", symbol=c["trading_symbol"], entry_time=ebar[0],
                                    entry_px=entry_px, exit_time=xbar[0], exit_px=exit_px, qty=qty,
                                    exit_reason=REASON[sm["why"]], capital=entry_px * qty, entry_spot=sm["lvl"],
                                    mfe=mfe, mae=mae, expiry=c["expiry"], option_type="CE" if side > 0 else "PE",
                                    variant={"stretch": str(th), "confirm": cv, "stop": sv, "allow": av,
                                             "moneyness": str(steps)},
                                    tags={"direction": direction,
                                          "entry window": band_of(sm["signal"]),
                                          "quiet day": "yes" if sm["used_pts"] < QUIET * rng else "no",
                                          "which reference": which,
                                          "stretch size": bucket(size, [0.8, 0.9, 1.2, 1.6],
                                                                 ["0.7-0.8", "0.8-0.9", "0.9-1.2", "1.2-1.6", "above 1.6"]),
                                          "signal time": sig_hm[:2] + ":00-" + sig_hm[:2] + ":59",
                                          "stop size": bucket(sm["R"], [30, 40, 50],
                                                              ["under 30 points", "30-40 points", "40-50 points",
                                                               "50 points or more"]),
                                          "5-minute candle": "confirms" if sm["checks"][5] else "does not confirm",
                                          "15-minute candle": "confirms" if sm["checks"][15] else "does not confirm",
                                          "30-minute candle": "confirms" if sm["checks"][30] else "does not confirm",
                                          "the day's first signal": ("yes" if sm["first"] else
                                                                     "no - the first could not be bought or sold")},
                                    levels=lv,
                                    note=((f"stretch {size:.2f} x the {RANGE_N}-session average range ({rng:.0f} pts) "
                                           f"from the {which}; " if full_detail else "")
                                          + f"signal {sig_hm}; stop {sm['R']:.0f} pts, target {tgt_pts:.0f} pts"))
                                trades.append(t)
                                any_trade_today = True
                                if is_rule:
                                    rule_trade, rule_sig = t, sig_hm
            # the session log records what the RULE's own setting saw
            if rule_side == 0:
                log.append(session_row(d, "declined" if any_trade_today else "no signal",
                                       (f"stretched only on a looser setting (beyond {min(ths)}, not beyond "
                                        f"{rule['stretch']}) - 'Stretch needed' counts it")
                                       if any_trade_today else
                                       f"not stretched beyond {rule['stretch']} on either reference, and no looser "
                                       f"setting traded", **base))
            elif (rule_side, chart_rung) not in contracts:
                log.append(session_row(d, "no data", "the rule's option contract or its candles are missing", **base))
            elif rule_trade is not None and rule_trade["tags"]["entry window"] == "by 12:30":
                log.append(session_row(d, "traded", f"1 trade, {rule_trade['tags']['direction']}",
                                       **dict(base, direction=rule_trade["tags"]["direction"])))
            elif rule_trade is not None:
                log.append(session_row(d, "declined", f"the signal candle ended {rule_sig}, after {CUT_RULE} - 'Entries "
                                                      f"until' 13:00 / 13:30 counts it", **base))
            elif rule_first is None or rule_first["t"] is None:
                log.append(session_row(d, "no signal", f"stretched, but NIFTY gave no close back through the line by "
                                                       f"{CUT_MAX}", **base))
            elif not rule_first["ok"]:
                log.append(session_row(d, "declined", f"the day's first signal ({hm_of(rule_first['t'])}) was not "
                                                      f"confirmed by the 15-minute candle - 'Confirmation candle' "
                                                      f"counts it", **base))
            else:
                log.append(session_row(d, "declined", "confirmed, but the option did not trade within 3 minutes of the "
                                                      "signal (or could not be sold), and no later confirmed signal came",
                                       **base))
            got = contracts.get((rule_side, chart_rung))
            if got is not None:
                c, qty, opt, orows, rows5 = got
                option_sessions.setdefault(c["trading_symbol"], {})[d] = orows
                if broker_line is None and expiry >= now.date():
                    broker_line = await broker_check(up, CATEGORY, c["instrument_key"], qty, orows[0][2])
        print(broker_line or "broker check skipped: no live contract was traded in this window")
        print(f"upstox calls: {up.calls}, paced {up.paced / 60:.1f} min"
              + (f", rate-limited {up.throttled} times" if up.throttled else ""))
    return trades, skips, log, full, option_sessions


def orows_at(orows: list[list], k: int) -> list:
    hhmm = hm_of(k)
    return next(r for r in orows if r[0] == hhmm)


def report_skips(skips: list[str]) -> None:
    buckets: dict[str, list[str]] = {}
    for s in skips:
        reason = s.split(": ", 1)[1] if ": " in s else s
        buckets.setdefault(reason.split(" (")[0].strip(), []).append(s)
    print(f"\n{len(skips)} day/contract items skipped, by reason:")
    for reason, rows in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(rows):5d}  {reason}")
        for r in rows[:2]:
            print(f"         e.g. {r}")


def rule_trades(trades: list[dict], settings: list[dict]) -> list[dict]:
    """The trades the panel shows on load: every setting at the rule's own value."""
    sweep = {s["key"]: s["default"] for s in settings if s["mode"] == "sweep"}
    fopt = [next(o for o in s["options"] if o["value"] == s["default"]) for s in settings if s["mode"] == "filter"]
    return [t for t in trades if all(t["variant"].get(k) == v for k, v in sweep.items())
            and all(_admits(t, o) for o in fopt)]


def day_level_check(ts: list[dict], n_days: int) -> str:
    """RUN.md rule 11, before and after charges, plus what a target pays against what a stop costs."""
    if not ts:
        return "day-level check: no trades under the rule"
    g = sorted((t["gross"] for t in ts), reverse=True)
    by = {}
    for t in ts:
        by[t["day"]] = by.get(t["day"], 0.0) + t["net"]
    v = sorted(by.values(), reverse=True)
    h1 = [t for t in ts if t["day"] < SPLIT]; h2 = [t for t in ts if t["day"] >= SPLIT]
    wr = lambda a: sum(t["net"] > 0 for t in a) / len(a) * 100 if a else float("nan")
    st = [t["gross"] for t in ts if t["exit_reason"] == "stop"]; tg = [t["gross"] for t in ts if t["exit_reason"] == "target"]
    pay = (sum(tg) / len(tg)) / -(sum(st) / len(st)) if st and tg else float("nan")
    return (f"day-level check (the rule): {len(ts)} trades on {len(by)} days, {sum(x > 0 for x in v)} days made money, "
            f"median day Rs {sorted(v)[len(v) // 2]:,.0f}; gross Rs {sum(g):,.0f} (without the best 10 trades "
            f"Rs {sum(g[10:]):,.0f}; {sum(x > 0 for x in g)} trades above zero before charges); net Rs "
            f"{sum(t['net'] for t in ts):,.0f}; before {SPLIT}: {len(h1)} trades, {wr(h1):.1f}% won, "
            f"Rs {sum(t['net'] for t in h1):,.0f}; from it: {len(h2)} trades, {wr(h2):.1f}% won, "
            f"Rs {sum(t['net'] for t in h2):,.0f}; a target exit paid {pay:.2f} x a stop exit (gross, average); "
            f"average trades per week {len(ts) / (n_days / 5):.2f} ({n_days} trading days / 5)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat(),
                    help=f"first signal day; the shared START_DATE {START_DATE} - change it in py_funcs, not here")
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    if a.set_moneyness is None:
        a.set_moneyness = DEFAULT_LADDER
    settings = narrow(SETTINGS, a)
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    check_window(frm, to)
    trades, skips, log, sessions, option_sessions = asyncio.run(run(frm, to, settings))
    report_skips(skips)
    limits = [
        "WORST FILL ONLY: every buy at the minute's HIGH and every sell at the minute's LOW, on minutes the option "
        "TRADED (volume above zero). The script stops if any trade on any setting is filled otherwise, and "
        "build_payload re-checks the rule's trades.",
        f"ASSUMED: the entry takes the first traded option minute within {FILL_WAIT + 1} minutes after the signal "
        f"candle; if there is none (or the trade could not be sold), the next confirmed signal is read. A sale takes the "
        f"first traded minute after its signal, however late, up to {LAST_MIN}. Every trigger READS a candle.",
        "THE LEVELS are measured from NIFTY's low in the buy minute (a PUT; its high on a CALL): the NIFTY price that "
        "matches paying the option's high. They are set when that minute is complete and read from the next minute.",
        f"THE LINE needs no volume: the plain average of today's 1-minute closes. The 15-minute ATR is the average "
        f"true range of the last {ATR_N} finished 15-minute candles of the day (the first candle's gap from yesterday "
        f"is not counted); the 1-minute range is the average high-low of the last {FILL_N} one-minute candles.",
        f"ASSUMED: the average range is the simple average true range of the {RANGE_N} sessions before the trade day; "
        f"the references are the official close {CLOSE_BACK} sessions back and the middle of the last {MID_N} "
        f"sessions' high-low range (Upstox daily candles, which count the 21 Oct 2025 Muhurat hour as a session).",
        "ASSUMED: the strike reference is the close of the 11:00 index candle, rounded to 50; the expiry is the nearest "
        "at least one day after the trade day.",
        "SELECTION: the confirmation, the stop, the target allowance and the cut-off were chosen on 29 Sep 2025 - 25 "
        "Sep 2026, the same year this report shows, after about 39,000 settings. It is in-sample. Chosen on three "
        "quarters and traded on the fourth, the rule family made 84-87 trades a year at 58-61% won: expect about 60%, "
        "not the 64% shown.",
        f"HALVES: {SPLIT} is where the research split the year; it is also when STT on an option sale rose from 0.10% "
        f"to 0.15%, which the costs follow.",
        f"WINDOW: the shared START_DATE {START_DATE} .. END_DATE; this report was run on "
        f"{frm} .. {to}. Daily candles from {DAILY_LOOKBACK_DAYS} calendar days before it are read for the "
        f"range and the references, never traded.",
        "Capital = premium x qty. 'Entries until', 'Skip quiet days' and 'Which side' are exact filters (signals are "
        f"simulated to {CUT_MAX} and tagged); every other setting is simulated on its own.",
        "A win is counted after charges (RUN.md rule 5); a 15:14 exit that only covered part of its charges counts as a "
        "loss here.",
        "CHARTS: the rule's own stretch / confirmation / stop / target draw every level (the references, the line, the "
        "15-minute middle, entry, stop, target); other settings draw entry, stop and target only, to keep the file small.",
    ]
    lot = trades[-1]["qty"] // LOTS if trades else None
    meta = {
        "title": "5-Day Stretch Fade v3",
        "subtitle": "At 11:00, when NIFTY is stretched 0.8 x its 10-day average range from its close 5 sessions ago or "
                    "the middle of its 10-day range, wait for a 10-minute close back through the day's average line "
                    "that the last 15-minute candle confirms, and buy a 6-ITM option against the stretch. Stop 1 x the "
                    "15-minute ATR, target 2 x the stop plus the fill cost, one trade a day, same day only.",
        "instrument": "NIFTY 50 weekly options",
        "category": CATEGORY,
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": lot,
        "break_date": SPLIT,
        "fill_rule": "WORST FILL ONLY: buy at the minute's HIGH, sell at the minute's LOW, on minutes the option traded",
        "params": {"range": f"{RANGE_N}-session average true range",
                   "references": f"{REF_LABEL['close5']} | {REF_LABEL['mid10']}",
                   "the rule": f"stretch beyond {STRETCH_RULE}; a {SETUP_TF}-minute close back through the day's "
                               f"average line 11:01-{CUT_RULE}; the first signal confirmed by the last "
                               f"{CONFIRM_RULE}-minute candle's middle; stop 1 x the {ATR_TF}-minute ATR; target 2 x "
                               f"the stop + {ALLOW_RULE} x the 1-minute range; one trade a day; 6 strikes ITM",
                   "direction": "stretched up -> buy PE, stretched down -> buy CE",
                   "the line": "average of today's 1-minute closes since 09:15 (no volume)",
                   "time exit": TIME_EXIT, "lots": LOTS, "expiry": "nearest >= 1 day after the trade day"},
        "rule_steps": [
            f"Average range = the average daily range of the last {RANGE_N} sessions (true range). Typically about 224 "
            f"NIFTY points this year.",
            f"At 11:00, stretch = (NIFTY's 11:00 close - the reference) / the average range, for two references: the "
            f"close {CLOSE_BACK} sessions ago, and the middle of the last {MID_N} sessions' high-low range.",
            f"Either stretch beyond +{STRETCH_RULE}: buy a PUT; beyond -{STRETCH_RULE}: buy a CALL (if the two point "
            f"opposite ways, no trade). Example: 25,000 at 11:00, 24,800 five sessions ago, range 224 -> 200/224 = 0.89 "
            f"-> a PUT day.",
            f"The line = the average of today's 1-minute closes since 09:15. From 11:01, once NIFTY trades at or above "
            f"the line (a PUT day), wait for a {SETUP_TF}-minute candle (09:15, 09:25, ...) to close back below it, by "
            f"{CUT_RULE}. A CALL day mirrors it.",
            f"Confirm: at that close NIFTY must be below the middle of the last finished {CONFIRM_RULE}-minute candle "
            f"(above it on a CALL day). Only the day's first signal decides - not confirmed, no trade today.",
            "Buy the 6-in-the-money option (from the 11:00 close) in the next minute that trades (within 3 minutes), at "
            "its HIGH.",
            f"Stop = 1 x the {ATR_TF}-minute ATR (the average range of the last {ATR_N} finished {ATR_TF}-minute "
            f"candles, about 40 points); target = 2 x the stop + {ALLOW_RULE} x the 1-minute range (average high-low "
            f"of the last {FILL_N} minutes, about 7 points), both from NIFTY's low in the buy minute (its high on a "
            f"CALL). Example: ATR 40, 1-minute range 7, a PUT bought when NIFTY's low was 25,000 -> stop 25,040, "
            f"target 24,909.",
            "Sell in the next minute the option trades, at its LOW, after NIFTY touches the stop or the target (a minute "
            "that touches both = the stop); neither by 15:13 -> sell at 15:14. One trade a day. The extra 1.5 "
            "1-minute ranges on the target pay for the worst-price fills, so a target pays about twice what a stop "
            "costs.",
        ],
        "limits": limits,
        "rejected": [
            ["A stop just beyond the signal candle (a structure stop)", "research: 52-54% won with the same entry; the "
             "stop sat inside normal 5-minute noise."],
            ["Waiting for a pullback after the signal and entering on a 1- or 3-minute turn",
             "research: a real 1:2.3 with 19-27-point stops, but only 47-55 trades a year and weak in Oct-Mar."],
            ["Entering on a failed new high / low after 11:00", "research: 30-45% won."],
            ["A resting order back at the line after the signal", "research: 37-47% won."],
            ["A 60-minute candle check", "research: 62-67 trades a year at 61-63% won - fewer trades, no gain."],
            ["The 100-minute EMA as the line", "research: 55% won at 1:2."],
            ["5- or 15-minute signal candles instead of 10", "research: 60% and 57% won."],
            ["A second trade the same day", "research (entries to 13:30): 122 trades at 52.5% won with two a day, "
             "against 107 at 57.9% with one."],
            ["A VWAP built from the 50 stocks' volumes", "it cannot be computed live, and this rule does not need one."],
        ],
        "coverage": coverage(sessions, frm, to, ROWS_PER_SESSION),
        "rerun": rerun_command(SLUG, settings, frm.isoformat(), to.isoformat()),
    }
    groups = [{"name": "Direction", "keys": ["direction"]},
              {"name": "Entry window", "keys": ["entry window"]},
              {"name": "Stop size in NIFTY points", "keys": ["stop size"]},
              {"name": "15-minute candle check", "keys": ["15-minute candle"]},
              {"name": "Do the 5, 15 and 30-minute checks agree?",
               "keys": ["5-minute candle", "15-minute candle", "30-minute candle"]},
              {"name": "Which reference fired", "keys": ["which reference"]},
              {"name": "How big the stretch was", "keys": ["stretch size"]},
              {"name": "Signal time", "keys": ["signal time"]},
              {"name": "Quiet day", "keys": ["quiet day"]},
              {"name": "The day's first signal", "keys": ["the day's first signal"]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups,
                            settings=settings, chart="default", sessions_log=log, worst_only=True)
    path = write_report(payload, SLUG)
    ruled = rule_trades(trades, settings)
    print(day_level_check(ruled, len(payload["meta"]["trading_days"])))
    print("THE RULE: " + console_summary(ruled))
    print(f"every setting pooled ({len(trades)} trades across {len(combos(settings))} combinations; not a book): "
          + console_summary(trades))
    print(path)


if __name__ == "__main__":
    run_instruments(__file__)
elif __name__ == "__instrument__":
    main()
