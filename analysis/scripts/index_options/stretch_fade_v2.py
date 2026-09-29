"""5-Day Stretch Fade - v2: fade a stretched NIFTY, entered on a VWAP rejection, with a price stop and target.

THE PROMPT (the user, 2026-09-29): "replace the fade v2 strategy accurately without missing anything and cross validate"
- the rule found in the entry / variation / trade-count research of that day (scratchpad; summarised below).

THE RULE   (range = the average daily range of the last 10 sessions, true range - high to low, or the gap from the
            previous close when bigger - simple average; about 224 NIFTY points this year)
  Step 1  At 11:00 (the 11:00 one-minute candle complete), measure NIFTY's 11:00 close against two references:
            the official close 5 sessions ago, and the middle of the last 10 sessions' range ((highest high + lowest
            low) / 2).  Stretch = (11:00 close - reference) / range.
  Step 2  If either stretch is beyond 0.8 (and they do not point opposite ways): stretched UP -> buy a PUT,
          stretched DOWN -> buy a CALL.  Otherwise no trade today.
  Step 3  Wait for the VWAP rejection, 11:01 to 13:30.  VWAP = NIFTY's volume-weighted average price, built from the
          50 NIFTY stocks' own trades (NIFTY x the index-weighted average of each stock's VWAP / its price).  For a PUT:
          NIFTY first trades at or above VWAP (a minute's HIGH), then a 15-minute candle (aligned to 09:15) CLOSES back
          below VWAP.  A CALL mirrors it (a minute's LOW at or below, then a 15-minute close above).
  Step 4  Skip a quiet day: at that candle, today's range so far must be at least 0.35 x the average range.  If it
          is not, the next VWAP rejection before 13:30 is checked the same way.
  Step 5  Buy the 6-in-the-money option (strike from the 11:00 close, nearest expiry at least a day after today) in
          the first minute after the signal that traded (to 3 minutes), at that minute's HIGH.  NIFTY's close in that
          minute is the entry level.
  Step 6  STOP: NIFTY 0.4 x range against the entry level.  TARGET: NIFTY 0.22 x range in favour.  Read on NIFTY's
          completed minute (a PUT's stop on NIFTY's HIGH, its target on NIFTY's LOW; a CALL the other way; a minute
          that touches both = the stop).  Sell in the next minute the option traded, at its LOW.  Neither by 15:13:
          sell from 15:14 at the minute's LOW.
  Step 7  A SECOND trade the same day: after the first is closed, a NEW VWAP touch and 15-minute rejection before
          13:30 on the same side is traded the same way.  At most 2 trades a day, one at a time.

CHECKLIST (RUN.md step 1) - all clear from the research rule, nothing assumed beyond these fill details:
  underlying NIFTY 50 (1m) + its 50 stocks (1m with volume, for VWAP) | window: shared START_DATE..END_DATE, run
  on 2025-09-29..2026-09-25 | signal 11:00 + 15-minute candles | index_options, buy, 6 ITM, 1 lot, qty from the
  contract, expiry nearest >= 1 day after the trade day | exits steps 6-7 | intraday | standard option costs |
  missing data -> no trade, logged.  A zero-volume option minute is never a fill: the entry takes the first traded
  minute within 3 minutes of the signal, a sale the first traded minute after its signal (to 15:29).

WHERE IT COMES FROM (scratchpad research, 2026-09-29, real option candles, worst fills; all in-sample on one year)
  - Direction: fading a 1-3 week stretch works; 7-20 session ranges all worked (10 best), true range > high-low;
    references 5-15 sessions back worked, 1-3 sessions and today's open did not.  ~90% of 1,566 variants made money
    in both halves.
  - Entry: the VWAP rejection cuts the losing days - signal days that never came back through VWAP lost with an 11:01
    entry (39% won); the same VWAP entry without the stretch lost too.  Pullback, reversal-candle, RSI, breakout and
    tight structure-stop entries all failed.
  - Trade count: every simple loosening added losing trades (lower threshold, later cut-off, earlier 'arming'); the
    10-day middle as a second reference, a second trade a day, a 0.35 quiet filter and a 0.22 target reached 120+
    trades at ~79% won.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *          # noqa: F401,F403
from py_funcs import _admits    # the panel's own filter test, reused for the day-level check
import argparse
import numpy as np

CATEGORY = "index_options"
SLUG = "stretch_fade_v2"
SIGNAL_MIN = "11:00"            # the decision candle
CUT_MIN = "13:30"               # the last minute a VWAP signal candle may end
TIME_EXIT = "15:14"
LAST_MIN = "15:29"              # a working sell order waits at most until the last minute
TF = 15                         # the VWAP signal candle, minutes, aligned to 09:15
STEP = 50.0
LOTS = 1
RANGE_N = 10                    # sessions in the average daily range (true range)
CLOSE_BACK = 5                  # reference 1: the official close this many sessions ago
MID_N = 10                      # reference 2: the middle of this many sessions' high-low range
STRETCH_RULE = 0.8
USED_RULE = 0.35                # the day's range so far, x the average range, at the signal
STOP_RULE = 0.4
TARGET_RULE = 0.22
MAX_PER_DAY = 2
FILL_WAIT = 2                   # entry: wait up to 2 more minutes for a traded option minute
DAILY_LOOKBACK_DAYS = 45        # calendar days of daily candles before --from (10 + 1 sessions and holidays)
ROWS_PER_SESSION = 375
SPLIT = "2026-04-01"            # option STT 0.10% -> 0.15% of the sale; also the research's halves
DEFAULT_LADDER = "6"
UP_DIR, DOWN_DIR = "stretched up: buy PE", "stretched down: buy CE"
REF_LABEL = {"close5": f"close {CLOSE_BACK} sessions ago", "mid10": f"middle of the {MID_N}-day range"}
REFSETS = {"both": ("close5", "mid10"), "close5": ("close5",)}
REASON = {"stop": "stop", "target": "target", "time": "time exit 15:14"}
# The NIFTY 50 stocks and their index weights (%), from niftyindices.com 'Nifty 50' weights, Annexure II, August 2026
# (the constituents in force for the whole study year).  Used ONLY to build NIFTY's VWAP from the stocks' own trades;
# a missing stock-minute is left out of that minute and the weights re-scaled.  The instrument keys come from Upstox.
NIFTY50_WEIGHTS = {
    "ADANIENT": 0.75, "ADANIPORTS": 1.07, "APOLLOHOSP": 0.83, "ASIANPAINT": 1.09, "AXISBANK": 3.39, "BAJAJ-AUTO": 1.22,
    "BAJAJFINSV": 1.06, "BAJFINANCE": 2.57, "BEL": 1.35, "BHARTIARTL": 5.0, "CIPLA": 0.72, "COALINDIA": 0.87,
    "DRREDDY": 0.64, "EICHERMOT": 0.99, "ETERNAL": 2.15, "GRASIM": 1.15, "HCLTECH": 1.26, "HDFCBANK": 9.85,
    "HDFCLIFE": 0.53, "HINDALCO": 1.33, "HINDUNILVR": 1.58, "ICICIBANK": 9.45, "INDIGO": 1.08, "INFY": 3.61,
    "ITC": 2.24, "JIOFIN": 0.72, "JSWSTEEL": 1.11, "KOTAKBANK": 2.8, "LT": 4.3, "M&M": 2.66, "MARUTI": 1.6,
    "MAXHEALTH": 0.7, "NESTLEIND": 0.97, "NTPC": 1.41, "ONGC": 0.82, "POWERGRID": 1.08, "RELIANCE": 7.83,
    "SBILIFE": 0.71, "SBIN": 3.98, "SHRIRAMFIN": 1.41, "SUNPHARMA": 1.91, "TATACONSUM": 0.61, "TATASTEEL": 1.38,
    "TCS": 2.22, "TECHM": 0.94, "TITAN": 1.91, "TMPV": 0.59, "TRENT": 0.87, "ULTRACEMCO": 1.23, "WIPRO": 0.45,
}


def rung_label(v: int) -> str:
    return "at the money" if v == 0 else f"{abs(v)} strikes {'in' if v > 0 else 'out of'} the money"


def mi(hhmm: str) -> int:
    """HH:MM -> minute index of the session (09:15 = 0)."""
    return hhmm_minutes(hhmm) - hhmm_minutes("09:15")


def hm_of(k: int) -> str:
    m = hhmm_minutes("09:15") + k
    return f"{m // 60:02d}:{m % 60:02d}"


# The control panel.  Defaults = the rule.  Every sweep value is simulated on its own (they are not subsets of each
# other: a stricter quiet filter can move a day to a LATER signal, and one reference can flip a day's side).
SETTINGS = [
    setting("stretch", "Stretch needed", kind="entry", default=str(STRETCH_RULE),
            help="how far NIFTY at 11:00 must be from the reference, in average daily ranges",
            options=[{"value": str(v), "raw": v, "label": f"beyond {v} x the range" + (" (the rule)" if v == STRETCH_RULE else "")}
                     for v in (0.7, 0.8, 0.9)]),
    setting("refs", "Stretch measured from", kind="entry", default="both",
            help="the rule takes either reference; one reference alone trades fewer days",
            options=[{"value": "both", "raw": "both", "label": f"{REF_LABEL['close5']} OR {REF_LABEL['mid10']} (the rule)"},
                     {"value": "close5", "raw": "close5", "label": f"only the {REF_LABEL['close5']}"}]),
    setting("quiet", "Skip quiet days", kind="entry", default=str(USED_RULE),
            help="today's range at the VWAP signal must be at least this x the average range",
            options=[{"value": str(v), "raw": v, "label": f"range so far at least {v} x average" + (" (the rule)" if v == USED_RULE else "")}
                     for v in (0.35, 0.4)]),
    setting("per_day", "Trades a day", kind="entry", mode="filter", default="2",
            help="the first trade of a day never depends on the second, so this is an exact filter",
            options=[{"value": "2", "label": "up to 2 (the rule)", "tag": None},
                     {"value": "1", "label": "first trade only", "tag": {"trade of the day": ["first"]}}]),
    setting("side_pick", "Which side", kind="entry", mode="filter", default="both",
            help="each day is one side only, so 'both' is the whole book",
            options=[{"value": "both", "label": "both (the rule)", "tag": None},
                     {"value": "CE", "label": "calls only (stretched down)", "tag": {"direction": [DOWN_DIR]}},
                     {"value": "PE", "label": "puts only (stretched up)", "tag": {"direction": [UP_DIR]}}]),
    setting("stop", "Stop", kind="exit", default=str(STOP_RULE),
            help="NIFTY this many average ranges against the entry level",
            options=[{"value": str(v), "raw": v, "label": f"{v} x range against" + (" (the rule)" if v == STOP_RULE else "")}
                     for v in (0.35, 0.4, 0.5)]),
    setting("target", "Target", kind="exit", default=str(TARGET_RULE),
            help="NIFTY this many average ranges in the trade's favour from the entry level",
            options=[{"value": str(v), "raw": v, "label": f"{v} x range in favour" + (" (the rule)" if v == TARGET_RULE else "")}
                     for v in (0.2, 0.22, 0.25)]),
    setting("moneyness", "Strike depth", kind="strike", default=6, rerun=True,
            options=[{"value": v, "label": rung_label(v), "raw": v} for v in (6, 4)],
            help="--moneyness 6,4 prices the 4-ITM rung on the same days"),
]


def values_of(settings: list[dict], key: str) -> list:
    return [o["raw"] for o in next(s for s in settings if s["key"] == key)["options"]]


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


def side_of(c1100: float, facts: dict, th: float, refs: tuple) -> tuple[int, dict]:
    """(+1 CALL / -1 PUT / 0 no trade, {ref: stretch}).  A stretched-up reference asks for a PUT; references that
    are beyond the threshold must agree."""
    xs = {r: (c1100 - facts[r]) / facts["range"] for r in refs}
    sides = {(-1 if x > 0 else 1) for x in xs.values() if abs(x) > th}
    return (sides.pop() if len(sides) == 1 else 0), xs


def nifty_arrays(rows: list[list]) -> tuple:
    """(high, low, close) arrays over the 375 session minutes; NaN where a minute is missing."""
    A = np.full((ROWS_PER_SESSION, 3), np.nan)
    for r in rows:
        k = mi(r[0])
        if 0 <= k < ROWS_PER_SESSION:
            A[k] = (r[2], r[3], r[4])
    return A[:, 0], A[:, 1], A[:, 2]


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


# ---------------------------------------------------------------------------
# simulate one day for one setting (pure)
# ---------------------------------------------------------------------------
def simulate_day(H, L, C, V, side, rng, used_min, stop, target, opt) -> list[dict]:
    """The VWAP-rejection entries and their exits (steps 3-7) for one side, as minute indices and prices."""
    arr, traded = opt
    t0, cut, tx = mi(SIGNAL_MIN), mi(CUT_MIN), mi(TIME_EXIT)
    touched = False; busy = -1; out = []
    for t in range(t0 + 1, cut + 1):
        if t <= busy:
            continue
        v = V[t]
        if not np.isfinite(v):
            continue
        if (H[t] >= v) if side < 0 else (L[t] <= v):
            touched = True
        if not touched or (t + 1) % TF or not ((C[t] < v) if side < 0 else (C[t] > v)):
            continue
        used = (np.nanmax(H[:t + 1]) - np.nanmin(L[:t + 1])) / rng
        if used < used_min:
            continue
        ke = next_traded(traded, t + 1, last=t + 1 + FILL_WAIT)
        if ke is None or ke >= tx:
            continue
        lvl = C[ke]
        s_lvl, t_lvl = lvl - side * stop * rng, lvl + side * target * rng
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
            continue                                   # could not be sold: not a trade (logged by the caller)
        out.append({"signal": t, "ek": ke, "xk": xk, "why": why, "lvl": lvl, "stop_lvl": s_lvl, "tgt_lvl": t_lvl,
                    "used": used, "entry_px": arr[ke, 0], "exit_px": arr[xk, 1]})
        if len(out) >= MAX_PER_DAY:
            break
        busy = xk; touched = False                     # flat again after the exit; a NEW touch is needed
    return out


def vwap_ratio_add(num: np.ndarray, den: np.ndarray, rows: list[list], w: float) -> None:
    """Add one stock-day to NIFTY's VWAP: that stock's VWAP (typical price x volume, cumulated from 09:15) divided by
    its price, weighted.  Minutes the stock has no candle are left out of that minute (and its weight with them)."""
    A = np.full((ROWS_PER_SESSION, 4), np.nan)                 # high, low, close, volume
    for r in rows:
        k = mi(r[0])
        if 0 <= k < ROWS_PER_SESSION:
            A[k] = (r[2], r[3], r[4], r[5])
    tp = (A[:, 0] + A[:, 1] + A[:, 2]) / 3
    with np.errstate(invalid="ignore", divide="ignore"):
        vwap = np.nancumsum(tp * A[:, 3]) / np.nancumsum(A[:, 3])
        ratio = vwap / A[:, 2]
    ok = np.isfinite(ratio)
    num[ok] += w * ratio[ok]
    den[ok] += w


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
async def run(frm: date, to: date, settings: list[dict]):
    now = datetime.now(IST)
    skips: list[str] = []
    log: list[dict] = []
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list[list]]] = {}
    rungs = values_of(settings, "moneyness")
    ths, refsets, quiets = values_of(settings, "stretch"), values_of(settings, "refs"), values_of(settings, "quiet")
    stops, targets = values_of(settings, "stop"), values_of(settings, "target")
    rule = default_combo(settings)
    chart_rung = rule["moneyness"]
    broker_line = None
    async with Upstox() as up:
        key = (await up.find_instrument("NIFTY"))["instrument_key"]
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
        # NIFTY's VWAP from its 50 stocks, one stock at a time (cached closed months; only the running month is fetched)
        num = {d: np.zeros(ROWS_PER_SESSION) for d in days}; den = {d: np.zeros(ROWS_PER_SESSION) for d in days}
        stock_days = {}
        for sym, w in NIFTY50_WEIGHTS.items():
            inst = await up.find_instrument(sym, "NSE_EQ")
            ss = await up.minute_sessions(inst["instrument_key"], frm, to, volume=True)
            stock_days[sym] = sum(1 for d in days if ss.get(d))
            for d in days:
                if ss.get(d):
                    vwap_ratio_add(num[d], den[d], ss[d], w)
        thin = {s: n for s, n in stock_days.items() if n < len(days)}
        print(f"NIFTY sessions in window: {len(days)}; daily candles from {daily[0][0] if daily else '-'}; VWAP built from "
              f"{len(NIFTY50_WEIGHTS)} stocks" + (f"; stocks missing some days: {thin}" if thin else ""))
        print(f"strike ladder {[rung_label(v) for v in rungs]}: {fetch_estimate(len(days) * len(rungs))} "
              f"(fewer with the candle cache).")
        for d in days:
            rows = full[d]
            facts = day_facts(daily, d)
            if facts is None:
                skips.append(f"{d}: not enough daily candles before it")
                log.append(session_row(d, "no data", f"not enough daily candles before this day for the {RANGE_N}-session range"))
                continue
            H, L, C = nifty_arrays(rows)
            k11 = mi(SIGNAL_MIN)
            if not np.isfinite(C[k11]):
                skips.append(f"{d}: the 11:00 candle is missing")
                log.append(session_row(d, "no data", "the 11:00 candle is missing"))
                continue
            c1100 = float(C[k11]); rng = facts["range"]
            with np.errstate(invalid="ignore", divide="ignore"):
                V = C * np.where(den[d] > 0, num[d] / den[d], np.nan)
            base = {"11:00 NIFTY": c1100, REF_LABEL["close5"]: facts["close5"], REF_LABEL["mid10"]: facts["mid10"],
                    f"average range ({RANGE_N} sessions)": rng,
                    "stretch vs close 5 back": (c1100 - facts["close5"]) / rng,
                    "stretch vs 10-day middle": (c1100 - facts["mid10"]) / rng}
            # which side each (threshold, references) setting asks for today
            want = {(th, rs): side_of(c1100, facts, th, REFSETS[rs])[0] for th in ths for rs in refsets}
            sides = {s for s in want.values() if s}
            rule_side = want[(rule["stretch"], rule["refs"])]
            if not sides:
                log.append(session_row(d, "no signal", f"not stretched beyond {min(ths)} x the range on either reference", **base))
                continue
            expiry = next_expiry(cal, date.fromisoformat(d), 1)
            if expiry is None:
                skips.append(f"{d}: no expiry at least a day after it")
                log.append(session_row(d, "no data", "no expiry at least a day after this day", **base))
                continue
            contracts = {}                                          # (side, rung) -> (contract, qty, arrays, rows)
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
            rule_trades_today, rule_note, any_trade_today = 0, None, False
            direction_fact = None
            for th in ths:
                for rs in refsets:
                    side = want[(th, rs)]
                    if not side:
                        continue
                    sgn_x = side_of(c1100, facts, th, REFSETS[rs])[1]
                    fired = [r for r, x in sgn_x.items() if abs(x) > th and (-1 if x > 0 else 1) == side]
                    which = "both" if len(fired) == 2 else REF_LABEL[fired[0]]
                    size = max(abs(sgn_x[r]) for r in fired)
                    direction = UP_DIR if side < 0 else DOWN_DIR
                    for steps in rungs:
                        got = contracts.get((side, steps))
                        if got is None:
                            continue
                        c, qty, opt, orows, rows5 = got
                        for um in quiets:
                            for st in stops:
                                for tg in targets:
                                    is_rule = (th == rule["stretch"] and rs == rule["refs"] and um == rule["quiet"]
                                               and st == rule["stop"] and tg == rule["target"] and steps == chart_rung)
                                    sims = simulate_day(H, L, C, V, side, rng, um, st, tg, opt)
                                    for n_, sm in enumerate(sims):
                                        ebar, xbar = orows_at(orows, sm["ek"]), orows_at(orows, sm["xk"])
                                        entry_px, exit_px = worst_fills("LONG", ebar, xbar)
                                        # WORST FILL ONLY on every rung and setting - the report keeps one rung's candles
                                        if entry_px != ebar[2] or exit_px != xbar[3] or ebar[5] <= 0 or xbar[5] <= 0:
                                            raise SystemExit(f"{d} {c['trading_symbol']}: fill is not the worst traded price")
                                        mfe, mae = excursion(rows5, "LONG", entry_px, ebar[0], xbar[0])
                                        sig_hm = hm_of(sm["signal"])
                                        trades.append(make_trade(
                                            day=d, side="LONG", symbol=c["trading_symbol"], entry_time=ebar[0],
                                            entry_px=entry_px, exit_time=xbar[0], exit_px=exit_px, qty=qty,
                                            exit_reason=REASON[sm["why"]], capital=entry_px * qty, entry_spot=sm["lvl"],
                                            mfe=mfe, mae=mae, expiry=c["expiry"], option_type="CE" if side > 0 else "PE",
                                            variant={"stretch": str(th), "refs": rs, "quiet": str(um), "stop": str(st),
                                                     "target": str(tg), "moneyness": str(steps)},
                                            tags={"direction": direction, "trade of the day": "first" if n_ == 0 else "second",
                                                  "which reference": which,
                                                  "stretch size": bucket(size, [0.8, 0.9, 1.2, 1.6],
                                                                         ["0.7-0.8", "0.8-0.9", "0.9-1.2", "1.2-1.6", "above 1.6"]),
                                                  "range used at the signal": bucket(sm["used"], [0.5, 0.75, 1.0],
                                                                                     ["under 0.5", "0.5-0.75", "0.75-1.0", "1.0 or more"]),
                                                  "signal time": sig_hm[:2] + ":00-" + sig_hm[:2] + ":59",
                                                  "NIFTY 09:15 to 11:00": ("already moving the trade's way"
                                                                           if (c1100 - rows[0][1]) * side > 0 else "still against the trade")},
                                            levels=[{"name": REF_LABEL["close5"] + f" ({facts['close5_day']})", "price": facts["close5"]},
                                                    {"name": REF_LABEL["mid10"], "price": facts["mid10"]},
                                                    {"name": "entry level", "price": sm["lvl"]},
                                                    {"name": f"stop {st} x range", "price": sm["stop_lvl"]},
                                                    {"name": f"target {tg} x range", "price": sm["tgt_lvl"]}],
                                            note=(f"{rung_label(steps)}; stretch {size:.2f} x the {RANGE_N}-session average range "
                                                  f"({rng:.0f} pts) from the {which}; VWAP signal candle ended {sig_hm}; range "
                                                  f"used {sm['used']:.2f}; trade {n_ + 1} of the day")))
                                        any_trade_today = True
                                        if is_rule:
                                            rule_trades_today += 1
                                            direction_fact = direction
                                    if is_rule and not sims:
                                        rule_note = "no VWAP rejection passed the quiet-day check by 13:30"
            # the session log records what the RULE's own setting saw
            if rule_side == 0:
                log.append(session_row(d, "declined" if any_trade_today else "no signal",
                                       (f"stretched only on a looser setting (beyond {min(ths)}, not beyond "
                                        f"{rule['stretch']} on the rule's references) - 'Stretch needed' counts it")
                                       if any_trade_today else
                                       f"not stretched beyond {rule['stretch']} on the rule's references, and no looser "
                                       f"setting found a VWAP rejection", **base))
            elif (rule_side, chart_rung) not in contracts:
                log.append(session_row(d, "no data", "the rule's option contract or its candles are missing", **base))
            elif rule_trades_today:
                typ = "CE" if rule_side > 0 else "PE"
                log.append(session_row(d, "traded", f"{rule_trades_today} trade(s), {direction_fact}",
                                       **dict(base, direction=direction_fact)))
            else:
                # was there a VWAP rejection at all?  (quiet 0 = no quiet filter)
                c, qty, opt, orows, rows5 = contracts[(rule_side, chart_rung)]
                any_rej = simulate_day(H, L, C, V, rule_side, rng, 0.0, rule["stop"], rule["target"], opt)
                if any_rej:
                    log.append(session_row(d, "declined", "a VWAP rejection came only on a quiet day (range so far under "
                                                          f"{rule['quiet']} x average)", **base))
                else:
                    log.append(session_row(d, "no signal", "stretched, but NIFTY gave no VWAP rejection by 13:30", **base))
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
    """RUN.md rule 11, before and after charges."""
    if not ts:
        return "day-level check: no trades under the rule"
    g = sorted((t["gross"] for t in ts), reverse=True)
    by = {}
    for t in ts:
        by[t["day"]] = by.get(t["day"], 0.0) + t["net"]
    v = sorted(by.values(), reverse=True)
    h1 = [t for t in ts if t["day"] < SPLIT]; h2 = [t for t in ts if t["day"] >= SPLIT]
    wr = lambda a: sum(t["net"] > 0 for t in a) / len(a) * 100 if a else float("nan")
    return (f"day-level check (the rule): {len(ts)} trades on {len(by)} days, {sum(x > 0 for x in v)} days made money, "
            f"median day Rs {sorted(v)[len(v) // 2]:,.0f}; gross Rs {sum(g):,.0f} (without the best 10 trades "
            f"Rs {sum(g[10:]):,.0f}); net Rs {sum(t['net'] for t in ts):,.0f}; before {SPLIT}: {len(h1)} trades, "
            f"{wr(h1):.1f}% won, Rs {sum(t['net'] for t in h1):,.0f}; from it: {len(h2)} trades, {wr(h2):.1f}% won, "
            f"Rs {sum(t['net'] for t in h2):,.0f}; average trades per week {len(ts) / (n_days / 5):.2f} "
            f"({n_days} trading days / 5)")


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
        f"candle (else no entry on that signal); a sale takes the first traded minute after its signal, however late, "
        f"up to {LAST_MIN}. Every trigger READS a candle.",
        "VWAP: NIFTY has no volume of its own, so its VWAP is built from the 50 stocks: NIFTY's price x the "
        "index-weighted average of each stock's VWAP / its price (typical price = (high + low + close) / 3, cumulated "
        "from 09:15). The weights are the August 2026 official index weights for the whole year; a stock-minute with no "
        "candle is left out of that minute. The futures-chart VWAP gives a weaker result (research: ~71% won against "
        "~79%), so a live copy of this rule needs the same stock-built VWAP.",
        f"ASSUMED: the average range is the simple average true range of the {RANGE_N} sessions before the trade day; "
        f"the references are the official close {CLOSE_BACK} sessions back and the middle of the last {MID_N} "
        f"sessions' high-low range (Upstox daily candles, which count the 21 Oct 2025 Muhurat hour as a session).",
        "ASSUMED: the strike reference is the close of the 11:00 index candle, rounded to 50; the expiry is the nearest "
        "at least one day after the trade day. A second trade on the same day uses the same contract.",
        "SELECTION: the lookback, references, threshold, VWAP entry, quiet filter, stop, target and the second trade "
        "were chosen on 29 Sep 2025 - 25 Sep 2026, the same year this report shows, after about 1,700 variants. It is "
        "in-sample; the cross-validation (settings chosen on one half, tested on the other) is reported with it.",
        f"HALVES: {SPLIT} is where the research split the year; it is also when STT on an option sale rose from 0.10% "
        f"to 0.15%, which the costs follow.",
        f"WINDOW: the shared START_DATE {START_DATE} .. END_DATE; this report was run on the one-year study window "
        f"2025-09-29 .. 2026-09-25. Daily candles from {DAILY_LOOKBACK_DAYS} calendar days before it are read for the "
        f"range and the references, never traded.",
        "Capital = premium x qty. The 'Trades a day' and 'Which side' settings are exact filters; every other setting "
        "is simulated on its own.",
    ]
    lot = trades[-1]["qty"] // LOTS if trades else None
    meta = {
        "title": "5-Day Stretch Fade v2",
        "subtitle": "At 11:00, when NIFTY is stretched 0.8 x its 10-day average range from its close 5 sessions ago or "
                    "the middle of its 10-day range, wait for a VWAP rejection and buy a 6-ITM option against the "
                    "stretch. Stop 0.4 x range, target 0.22 x range, up to 2 trades a day, same day only.",
        "instrument": "NIFTY 50 weekly options",
        "category": CATEGORY,
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": lot,
        "break_date": SPLIT,
        "fill_rule": "WORST FILL ONLY: buy at the minute's HIGH, sell at the minute's LOW, on minutes the option traded",
        "params": {"range": f"{RANGE_N}-session average true range",
                   "references": f"{REF_LABEL['close5']} | {REF_LABEL['mid10']}",
                   "the rule": f"stretch beyond {STRETCH_RULE}, VWAP rejection ({TF}-minute close) 11:01-{CUT_MIN}, range "
                               f"so far >= {USED_RULE} x average, stop {STOP_RULE}, target {TARGET_RULE}, up to "
                               f"{MAX_PER_DAY} trades a day, 6 strikes ITM",
                   "direction": "stretched up -> buy PE, stretched down -> buy CE",
                   "VWAP": "built from the 50 NIFTY stocks (Aug 2026 weights)",
                   "time exit": TIME_EXIT, "lots": LOTS, "expiry": "nearest >= 1 day after the trade day"},
        "rule_steps": [
            f"Average range = the average daily range of the last {RANGE_N} sessions (true range). Typically about 224 "
            f"NIFTY points this year.",
            f"At 11:00, stretch = (NIFTY's 11:00 close - the reference) / the average range, for two references: the "
            f"close {CLOSE_BACK} sessions ago, and the middle of the last {MID_N} sessions' high-low range.",
            f"Either stretch beyond +{STRETCH_RULE}: buy a PUT; beyond -{STRETCH_RULE}: buy a CALL (if the two point "
            f"opposite ways, no trade). Example: 25,000 at 11:00, 24,800 five sessions ago, range 224 -> 200/224 = 0.89 "
            f"-> a PUT day.",
            f"Wait (11:01-{CUT_MIN}) for NIFTY to trade at or above its VWAP (a PUT day), then for a {TF}-minute "
            f"candle to close back below VWAP. A CALL day mirrors it. VWAP is built from the 50 NIFTY stocks.",
            f"At that candle, today's range so far must be at least {USED_RULE} x the average range (about 78 points); "
            f"if not, wait for the next VWAP rejection.",
            "Buy the 6-in-the-money option (from the 11:00 close) in the next minute that trades, at its HIGH. NIFTY's "
            "close in that minute is the entry level.",
            f"STOP: NIFTY {STOP_RULE} x range against the entry level (about 90 points). TARGET: {TARGET_RULE} x range in "
            f"favour (about 49 points). Sell in the next minute that trades, at its LOW. Neither: sell at 15:14.",
            f"After a trade closes, a NEW VWAP touch and rejection before {CUT_MIN} gives one more trade the same day "
            f"(at most {MAX_PER_DAY} a day).",
        ],
        "limits": limits,
        "rejected": [
            ["A lower stretch threshold, a later cut-off, or counting a stretch reached before 11:00",
             "research: the trades each added won 0-50% and lost money."],
            ["Entering at 11:01 without the VWAP rejection", "research: the signal days that never came back through "
             "VWAP won 39% and lost money; the VWAP step is what cuts them."],
            ["The futures-chart VWAP", "research: the same rule won about 71% instead of about 79%."],
            ["A target from the 'room left' in the day's average range", "research: bigger targets made more money but "
             "won 65-68%; the room is almost never small after a VWAP rejection."],
            ["Trading WITH the stretch on the days the fade skips", "research: worked Oct-Mar only, not Apr-Sep."],
            ["Faster VWAP candles (5 or 10 minutes)", "research: they only move entries in time and win less."],
            ["More than 2 trades a day, or a later deadline for the second trade", "research: added trades won 50-58%."],
        ],
        "coverage": coverage(sessions, frm, to, ROWS_PER_SESSION),
        "rerun": rerun_command(SLUG, settings, frm.isoformat(), to.isoformat()),
    }
    groups = [{"name": "Direction", "keys": ["direction"]},
              {"name": "Trade of the day", "keys": ["trade of the day"]},
              {"name": "Which reference fired", "keys": ["which reference"]},
              {"name": "How big the stretch was", "keys": ["stretch size"]},
              {"name": "Range used at the signal", "keys": ["range used at the signal"]},
              {"name": "Signal time", "keys": ["signal time"]},
              {"name": "NIFTY 09:15 to 11:00", "keys": ["NIFTY 09:15 to 11:00"]}]
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
    main()
