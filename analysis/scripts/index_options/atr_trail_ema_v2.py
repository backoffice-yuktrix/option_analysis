"""ATR Trailing Stop x EMA - v2: v1's midday crosses, with a stop and a target on the option.

THE PROMPT (the user, 2026-10-01): v1's prompt ("when the ema crosses above the ATR trailing stop indicator buy CE then
it crosses below exit and buy the PE ... try multiple time frames which make the edge"), then "where the stop and
target?" and, on the stop research, "[the -25% premium stop] is worth but i need target".

THE INDICATOR - Upstox's "ATR Trailing Stops" (the ChartIQ study), exactly as in v1: Wilder's average true range,
period 21, multiplier 3, HighLow off, the value on candle i computed from the candles before it:
    offset(i) = ATR(i-1) x 3
    Close(i-1) >  R(i-1) and Close(i-2) >  R(i-1):   R(i) = max(R(i-1), Close(i-1) - offset)
    Close(i-1) <= R(i-1) and Close(i-2) <= R(i-1):   R(i) = min(R(i-1), Close(i-1) + offset)
    Close(i-1) >  R(i-1):                            R(i) = Close(i-1) - offset
    otherwise:                                       R(i) = Close(i-1) + offset

THE RULE
  Step 1  On 5-minute NIFTY candles (aligned to 09:15) draw the ATR Trailing Stops line (21, 3) and the 5-candle EMA.
  Step 2  A candle closes with the EMA above the line after the candle before had it at or below: buy a CALL.  The
          EMA below the line after at or above: buy a PUT.
  Step 3  Only a cross whose candle finishes from 11:30 to 13:25 opens a trade.
  Step 4  Buy the 6-in-the-money option (strike from that candle's close, nearest expiry at least a day after today)
          in the first minute after the candle that the option trades (to 3 minutes), at that minute's HIGH = PAID.
  Step 5  STOP = 25% below PAID.  TARGET = 50% above PAID (twice the stop).  Read on the option's own completed
          1-minute candles from the next minute: its LOW at or under the stop, or its HIGH at or over the target
          (a minute that shows both = the stop).
  Step 6  Sell in the next minute the option trades, at its LOW, after the stop, the target or the next opposite
          cross - whichever comes first - or at 15:14.  Same day only; one position at a time.

CHECKLIST (RUN.md step 1)
  underlying NIFTY 50 (and SENSEX through run_instruments) | window: shared START_DATE..END_DATE | signal candles 5m
  (the panel: 5 / 10m), built from the 1-minute candles, completed candles only | index_options, bought, 1 lot, qty from
  the contract, 6 ITM (the ladder 6 ITM .. ATM) | exits step 5-6, stop and target in % of the premium paid | intraday |
  standard option costs | missing data -> no trade, logged.
  ASSUMED: everything v1 assumed (Upstox's default line, EMA 5, 5-minute candles, the 11:30-13:30 window, 15:14
  square-off, no new trade from 15:00, a zero-volume option minute is never a fill).  The stop and target are read on
  completed minutes and sold in the next one (RUN.md rule 3), not as resting orders filled at their own price.

WHERE THE STOP AND TARGET COME FROM (scratchpad research, 2026-10-01, v1's 64 NIFTY trades at 6 ITM; in-sample)
  - no stop, no target (v1): Rs 1,16,586, worst trade Rs -13,381.
  - A NIFTY stop of 1 or 1.5 ATR (28-42 points): hit on about half the trades; with a 1:1 or 1:2 target the result is
    a loss to Rs +16,000.  The trade needs room - the line sits about 70 points from the entry.
  - Premium stop -25%, no target: Rs 1,23,827, worst trade Rs -7,753, hit on 3 trades (SENSEX Rs 1,20,087).
  - With that stop, a premium target of +20% made Rs 60,389, +30% Rs 1,12,276, +37.5% Rs 1,13,712, +50% Rs 1,10,022,
    +75% Rs 1,25,731 (3 hits) - every target at or under +60% cost a little, because the profit is in the trades that
    run into the afternoon.  +50% is the rule: twice the stop, and about 6% under no target.
  - At the money the same % stop is hit 16 times and the targets cost far more: the stop and target are sized for
    the 6-ITM premium.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *          # noqa: F401,F403
from py_funcs import _admits, _ACTIVE
import argparse
import numpy as np

CATEGORY = "index_options"
SLUG = "atr_trail_ema_v2"
TFS = (5, 10)                   # signal candles, minutes, aligned to 09:15
TF_RULE = 5
EMAS = (1, 5, 9)                # EMA 1 = the close itself
EMA_RULE = 5
PERIOD, MULT = 21, 3.0          # ATR Trailing Stops at Upstox's defaults (v1 compares 10 / 21 and 2 / 3)
STOPS = (("none", None), ("25", 0.25))                      # share of the premium paid
STOP_RULE = "25"
TARGETS = (("none", None), ("37.5", 0.375), ("50", 0.50), ("75", 0.75))
TARGET_RULE = "50"
WINDOWS = (("11:30", "09:15-11:29"), ("13:30", "11:30-13:29"), ("15:00", "13:30-14:59"))   # (ends before, tag)
WINDOW_RULE = "11:30-13:29"
LAST_ENTRY = "15:00"            # no new trade from here
TIME_EXIT = "15:14"
FILL_WAIT = 2                   # entry: wait up to 2 more minutes for a traded option minute
WARMUP_DAYS = 40                # calendar days of candles before --from, read for the indicators, never traded
ROWS_PER_SESSION = 375
STEP = strike_step()            # 50 on NIFTY, 100 on SENSEX - read from the contract list
LOTS = 1
SPLIT = "2026-05-01"            # the research's halves: Jan-Apr and May-Jul
DEFAULT_LADDER = "6"
UP_DIR, DOWN_DIR = "EMA crossed above the line: buy CE", "EMA crossed below the line: buy PE"
REASON = {"stop": "stop", "target": "target", "cross": "opposite cross", "time": "time exit 15:14"}


def rung_label(v: int) -> str:
    return "at the money" if v == 0 else f"{abs(v)} strike{'s' if abs(v) > 1 else ''} {'in' if v > 0 else 'out of'} the money"


def mi(hhmm: str) -> int:
    """HH:MM -> minute index of the session (09:15 = 0)."""
    return hhmm_minutes(hhmm) - hhmm_minutes("09:15")


def hm_of(k: int) -> str:
    m = hhmm_minutes("09:15") + k
    return f"{m // 60:02d}:{m % 60:02d}"


# The control panel.  Defaults = the rule.  The candle and the EMA change which crosses exist; the stop and the target
# change every exit - each value is simulated on its own.  'Entries' only selects trades by the time of their cross:
# a trade's exit never depends on the trades before it.
SETTINGS = [
    setting("tf", "Candle", kind="entry", default=str(TF_RULE),
            help="the candles the line and the EMA are drawn on (built from the 1-minute candles, aligned to 09:15)",
            options=[{"value": str(v), "raw": v, "label": f"{v}-minute candles" + (" (the rule)" if v == TF_RULE else "")}
                     for v in TFS]),
    setting("ema", "EMA", kind="entry", default=str(EMA_RULE),
            help="the moving average that must cross the line; EMA 1 is the candle's close itself",
            options=[{"value": str(v), "raw": v,
                      "label": ("the close itself (EMA 1)" if v == 1 else f"EMA {v}") + (" (the rule)" if v == EMA_RULE else "")}
                     for v in EMAS]),
    setting("window", "Entries", kind="entry", mode="filter", default="midday",
            help="which crosses open a trade, by the time their candle finishes",
            options=[{"value": "midday", "label": "crosses 11:30 to 13:30 (the rule)", "tag": {"cross time": ["11:30-13:29"]}},
                     {"value": "all", "label": "every cross, all day (the prompt as written)", "tag": None},
                     {"value": "morning", "label": "crosses before 11:30", "tag": {"cross time": ["09:15-11:29"]}},
                     {"value": "afternoon", "label": "crosses 13:30 to 15:00", "tag": {"cross time": ["13:30-14:59"]}}]),
    setting("side_pick", "Which side", kind="entry", mode="filter", default="both",
            options=[{"value": "both", "label": "both (the rule)", "tag": None},
                     {"value": "CE", "label": "calls only (crossed above)", "tag": {"direction": [UP_DIR]}},
                     {"value": "PE", "label": "puts only (crossed below)", "tag": {"direction": [DOWN_DIR]}}]),
    setting("stop", "Stop", kind="exit", default=STOP_RULE,
            help="the option's 1-minute low this far under the price paid; sold in the next traded minute at its low",
            options=[{"value": "25", "raw": 0.25, "label": "25% under the price paid (the rule)"},
                     {"value": "none", "raw": None, "label": "no stop (v1: the opposite cross only)"}]),
    setting("target", "Target", kind="exit", default=TARGET_RULE,
            help="the option's 1-minute high this far over the price paid; sold in the next traded minute at its low",
            options=[{"value": "50", "raw": 0.50, "label": "50% over the price paid - twice the stop (the rule)"},
                     {"value": "37.5", "raw": 0.375, "label": "37.5% over - 1.5 times the stop"},
                     {"value": "75", "raw": 0.75, "label": "75% over - 3 times the stop"},
                     {"value": "none", "raw": None, "label": "no target"}]),
    setting("moneyness", "Strike depth", kind="strike", default=6, rerun=True,
            options=[{"value": v, "label": rung_label(v), "raw": v} for v in STRIKE_LADDER],
            help="--moneyness 6,0 prices the at-the-money rung on the same crosses"),
]


def options_of(settings: list[dict], key: str) -> list[tuple]:
    return [(o["value"], o["raw"]) for o in next(s for s in settings if s["key"] == key)["options"]]


# ---------------------------------------------------------------------------
# the indicator and the signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def tf_candles(sessions: dict[str, list[list]], tf: int) -> tuple:
    """Continuous tf-minute candles over every session, oldest first: high, low, close, and for each candle its day
    and the session minute at which it is complete (the minute the order goes in)."""
    H, L, C, D, K = [], [], [], [], []
    for d in sorted(sessions):
        buckets: dict[int, list] = {}
        for r in sessions[d]:
            k = mi(r[0])
            if 0 <= k < ROWS_PER_SESSION:
                b = buckets.setdefault(k // tf, [r[2], r[3], r[4]])
                b[0], b[1], b[2] = max(b[0], r[2]), min(b[1], r[3]), r[4]
        for q in sorted(buckets):
            h, l, c = buckets[q]
            H.append(h); L.append(l); C.append(c); D.append(d); K.append(min((q + 1) * tf, ROWS_PER_SESSION))
    return np.array(H), np.array(L), np.array(C), D, K


def wilder_atr(H, L, C, n: int):
    tr = np.empty(len(C))
    tr[0] = H[0] - L[0]
    tr[1:] = np.maximum(H[1:] - L[1:], np.maximum(abs(H[1:] - C[:-1]), abs(L[1:] - C[:-1])))
    out = np.full(len(C), np.nan)
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(C)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def trailing_stop(C, atr_, mult: float):
    """Upstox's ATR Trailing Stops line (the docstring's formula): the value on candle i uses candles up to i-1."""
    out = np.full(len(C), np.nan)
    i0 = int(np.argmax(np.isfinite(atr_))) + 1
    out[i0] = C[i0 - 1] - mult * atr_[i0 - 1]
    for i in range(i0 + 1, len(C)):
        p, c, pc, off = out[i - 1], C[i - 1], C[i - 2], mult * atr_[i - 1]
        if c > p and pc > p:
            out[i] = max(p, c - off)
        elif c <= p and pc <= p:
            out[i] = min(p, c + off)
        elif c > p:
            out[i] = c - off
        else:
            out[i] = c + off
    return out


def ema_line(C, n: int):
    if n == 1:
        return C.copy()
    out = np.full(len(C), np.nan)
    k = 2.0 / (n + 1)
    out[n - 1] = C[:n].mean()
    for i in range(n, len(C)):
        out[i] = C[i] * k + out[i - 1] * (1 - k)
    return out


def crosses(candles: tuple, em, stop, first_day: str) -> dict[str, list[tuple]]:
    """{day: [(minute the candle is complete, +1 above / -1 below, close, EMA, line)]} - every candle on which the
    EMA crossed the line, from `first_day`.  The last candle of a session (complete at 15:30) cannot be traded."""
    H, L, C, D, K = candles
    diff = em - stop
    out: dict[str, list[tuple]] = {}
    for i in range(1, len(C)):
        a, b = diff[i - 1], diff[i]
        if not (np.isfinite(a) and np.isfinite(b)) or D[i] < first_day or K[i] >= ROWS_PER_SESSION:
            continue
        s = 1 if (a <= 0 < b) else -1 if (a >= 0 > b) else 0
        if s:
            out.setdefault(D[i], []).append((K[i], s, float(C[i]), float(em[i]), float(stop[i])))
    return out


def window_of(k: int) -> str | None:
    return next((tag for until, tag in WINDOWS if k < mi(until)), None)


def next_traded(traded: np.ndarray, k: int, last: int = ROWS_PER_SESSION - 1) -> int | None:
    j = np.searchsorted(traded, k)
    return int(traded[j]) if j < len(traded) and traded[j] <= last else None


def find_exit(con: dict, ek: int, paid: float, nxt: int, tx: int, stop: float | None, target: float | None) -> tuple:
    """(minute the sell order goes in, why).  From the minute after the buy to the minute before `nxt` (the next
    opposite cross, or 15:14): the option's low at or under the stop, or its high at or over the target, on a
    completed minute - both in one minute = the stop (RUN.md rule 3).  Otherwise `nxt` itself."""
    hi, lo = con["hi"], con["lo"]
    s_px = None if stop is None else paid * (1 - stop)
    t_px = None if target is None else paid * (1 + target)
    for t in range(ek + 1, nxt):
        if s_px is not None and lo[t] <= s_px:
            return t + 1, "stop"
        if t_px is not None and hi[t] >= t_px:
            return t + 1, "target"
    return nxt, ("time" if nxt == tx else "cross")


# ---------------------------------------------------------------------------
# fetch + simulate
# ---------------------------------------------------------------------------
async def run(frm: date, to: date, settings: list[dict]):
    skips: list[str] = []
    log: list[dict] = []
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list[list]]] = {}
    rung = options_of(settings, "moneyness")[0][1]
    lines = [(tf, e) for _, tf in options_of(settings, "tf") for _, e in options_of(settings, "ema")]
    exits = [(sv, sr, tv, tr) for sv, sr in options_of(settings, "stop") for tv, tr in options_of(settings, "target")]
    rule = default_combo(settings)
    rule_line, rule_exit = (rule["tf"], rule["ema"]), (rule["stop"], rule["target"])
    broker_line = None
    now = datetime.now(IST)
    async with Upstox() as up:
        key = (await up.find_instrument(instrument()))["instrument_key"]
        info = await up.option_chain_info(key)
        if info["strike_step"] != STEP:
            raise SystemExit(f"strike step on disk is {info['strike_step']}, the script read {STEP}.")
        sessions = await up.minute_sessions(key, frm - timedelta(days=WARMUP_DAYS), to)
        cal = await up.expiry_calendar(key, frm, to)
        in_window = {d: r for d, r in sessions.items() if frm.isoformat() <= d <= to.isoformat()}
        full = {d: r for d, r in in_window.items() if len(r) >= ROWS_PER_SESSION}
        for d, r in in_window.items():
            if d not in full:
                skips.append(f"{d}: session incomplete ({len(r)} bars) - not traded")
                log.append(session_row(d, "no data", f"session incomplete: {len(r)} of {ROWS_PER_SESSION} candles"))
        days = sorted(full)
        print(f"{instrument()} sessions in window: {len(days)}; indicator warm-up from {min(sessions)}; "
              f"{len(lines) * len(exits)} setting(s) at {rung_label(rung)}")
        # every setting's crosses, from candles that run continuously through the warm-up
        sig: dict[tuple, dict] = {}
        cand = {tf: tf_candles(sessions, tf) for tf in {c[0] for c in lines}}
        for tf, e in lines:
            C = cand[tf][2]
            sig[(tf, e)] = crosses(cand[tf], ema_line(C, e), trailing_stop(C, wilder_atr(*cand[tf][:3], PERIOD), MULT),
                                   frm.isoformat())
        con_cache: dict[tuple, dict | None] = {}

        async def contract(d: str, expiry: date, typ: str, strike: float) -> dict | None:
            ck = (d, typ, strike)
            if ck not in con_cache:
                c = await up.resolve_option(key, expiry, strike, typ)
                got = None
                if c is None or int(c.get("lot_size") or 0) <= 0:
                    skips.append(f"{d}: contract {expiry} {strike:.0f} {typ} not found")
                else:
                    orows = await up.option_candles(c, date.fromisoformat(d), volume=True)
                    if not orows:
                        skips.append(f"{d}: no option candles ({c['trading_symbol']})")
                    else:
                        by = {mi(r[0]): r for r in orows}
                        hi = np.full(ROWS_PER_SESSION, np.nan); lo = np.full(ROWS_PER_SESSION, np.nan)
                        for k, r in by.items():
                            if 0 <= k < ROWS_PER_SESSION:
                                hi[k], lo[k] = r[2], r[3]
                        got = {"c": c, "qty": LOTS * c["lot_size"], "by": by, "rows5": [r[:5] for r in orows],
                               "hi": hi, "lo": lo,
                               "traded": np.array(sorted(k for k, r in by.items() if r[5] > 0))}
                con_cache[ck] = got
            return con_cache[ck]

        tx, last_entry = mi(TIME_EXIT), mi(LAST_ENTRY)
        for d in days:
            expiry = next_expiry(cal, date.fromisoformat(d), 1)
            if expiry is None:
                skips.append(f"{d}: no expiry at least a day after it")
                log.append(session_row(d, "no data", "no expiry at least a day after this day"))
                continue
            rule_day: list[dict] = []
            for ln in lines:
                evs = [e for e in sig[ln].get(d, []) if e[0] < tx]
                for j, (k, s, close, em, stop_line) in enumerate(evs):
                    if k >= last_entry:
                        continue
                    typ = "CE" if s > 0 else "PE"
                    con = await contract(d, expiry, typ, strike_offset(close, STEP, rung, typ, itm=True))
                    ek = None if con is None else next_traded(con["traded"], k, last=k + FILL_WAIT)
                    if ek is None or ek >= tx:
                        if con is not None:
                            skips.append(f"{d}: {con['c']['trading_symbol']} did not trade within {FILL_WAIT + 1} "
                                         f"minutes of the {hm_of(k)} cross - no trade")
                        continue
                    ebar = con["by"][ek]
                    paid = ebar[2]
                    nxt = evs[j + 1][0] if j + 1 < len(evs) else tx
                    for sv, sr, tv, tr in exits:
                        is_rule = ln == rule_line and (sr, tr) == rule_exit
                        trig, why = find_exit(con, ek, paid, nxt, tx, sr, tr)
                        xk = next_traded(con["traded"], trig)
                        if xk is None:
                            skips.append(f"{d}: {con['c']['trading_symbol']} bought {hm_of(ek)} could not be sold "
                                         f"(no traded minute from {hm_of(trig)}) - not a trade")
                            continue
                        xbar = con["by"][xk]
                        entry_px, exit_px = worst_fills("LONG", ebar, xbar)
                        mfe, mae = excursion(con["rows5"], "LONG", entry_px, ebar[0], xbar[0])
                        lv = ([{"name": "ATR Trailing Stops line at the cross", "price": stop_line},
                               {"name": f"EMA {ln[1]} at the cross", "price": em}] if is_rule else [])
                        t = make_trade(
                            day=d, side="LONG", symbol=con["c"]["trading_symbol"], entry_time=ebar[0],
                            entry_px=entry_px, exit_time=xbar[0], exit_px=exit_px, qty=con["qty"],
                            exit_reason=REASON[why], capital=entry_px * con["qty"],
                            stop=None if sr is None else paid * (1 - sr), target=None if tr is None else paid * (1 + tr),
                            mfe=mfe, mae=mae, expiry=con["c"]["expiry"], option_type=typ,
                            variant={"tf": ln[0], "ema": ln[1], "stop": sv, "target": tv, "moneyness": rung},
                            tags={"direction": UP_DIR if s > 0 else DOWN_DIR,
                                  "cross time": window_of(k),
                                  "the day's first cross": "yes" if j == 0 else "no"},
                            levels=lv,
                            note=f"cross on the {ln[0]}-minute candle finished {hm_of(k)}: close {close:.2f}, "
                                 f"EMA {em:.2f}, line {stop_line:.2f}")
                        trades.append(t)
                        # the option's own candles are kept for the rule's candle and EMA: every cross at the rule's strike, the
                        # midday crosses at every other strike (an exit setting changes the exit, not the contract)
                        if ln == rule_line and (int(rung) == int(DEFAULT_LADDER) or window_of(k) == WINDOW_RULE):
                            option_sessions.setdefault(con["c"]["trading_symbol"], {})[d] = con["rows5"]
                        if is_rule:
                            rule_day.append(t)
                            if broker_line is None and expiry >= now.date():
                                broker_line = await broker_check(up, CATEGORY, con["c"]["instrument_key"],
                                                                 con["qty"], ebar[2])
            # the session log records what the RULE's own setting saw
            evs = [e for e in sig[rule_line].get(d, []) if e[0] < last_entry]
            mid = [e for e in evs if window_of(e[0]) == WINDOW_RULE]
            facts = {"crosses before 15:00": len(evs), "crosses 11:30-13:29": len(mid),
                     "first cross": hm_of(evs[0][0]) if evs else None}
            won = [t for t in rule_day if t["tags"]["cross time"] == WINDOW_RULE]
            if won:
                log.append(session_row(d, "traded", f"{len(won)} trade(s): " + ", ".join(
                    f"{t['option_type']} {t['entry_time']} ({t['exit_reason']})" for t in won), **facts))
            elif mid:
                log.append(session_row(d, "no data", "a cross came 11:30-13:29 but the option's contract or candles "
                                                     "are missing, or it did not trade in time", **facts))
            elif evs:
                log.append(session_row(d, "declined", f"{len(evs)} cross(es), none between 11:30 and 13:29 - "
                                                      f"'Entries: every cross' counts them", **facts))
            else:
                log.append(session_row(d, "no signal", "the EMA did not cross the line before 15:00", **facts))
        print(broker_line or "broker check skipped: no live contract was traded in this window")
    return trades, skips, log, in_window, option_sessions


def report_skips(skips: list[str]) -> None:
    buckets: dict[str, list[str]] = {}
    for s in dict.fromkeys(skips):
        reason = s.split(": ", 1)[1] if ": " in s else s
        key = ("could not be sold" if "could not be sold" in reason else "did not trade within" if "did not trade within" in reason
               else reason.split(" (")[0].split(" 20")[0].strip())
        buckets.setdefault(key, []).append(s)
    print(f"\n{sum(len(v) for v in buckets.values())} day/contract items skipped, by reason:")
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
    """RUN.md rule 11: the days, the halves, the result without the best trades, and how the trades ended."""
    if not ts:
        return "day-level check: no trades under the rule"
    by: dict[str, float] = {}
    for t in ts:
        by[t["day"]] = by.get(t["day"], 0.0) + t["net"]
    v = sorted(by.values(), reverse=True)
    net = sorted((t["net"] for t in ts), reverse=True)
    h1 = [t for t in ts if t["day"] < SPLIT]; h2 = [t for t in ts if t["day"] >= SPLIT]
    wr = lambda a: sum(t["net"] > 0 for t in a) / len(a) * 100 if a else float("nan")
    ends = ", ".join(f"{r} {n} (Rs {sum(t['net'] for t in ts if t['exit_reason'] == r):,.0f})"
                     for r in REASON.values() if (n := sum(t["exit_reason"] == r for t in ts)))
    return (f"day-level check (the rule): {len(ts)} trades on {len(by)} days, {sum(x > 0 for x in v)} days made money, "
            f"median day Rs {sorted(v)[len(v) // 2]:,.0f}; net Rs {sum(net):,.0f}, without the best 5 trades "
            f"Rs {sum(net[5:]):,.0f}, worst trade Rs {net[-1]:,.0f}; before {SPLIT}: {len(h1)} trades, "
            f"{wr(h1):.1f}% won, Rs {sum(t['net'] for t in h1):,.0f}; from it: {len(h2)} trades, {wr(h2):.1f}% won, "
            f"Rs {sum(t['net'] for t in h2):,.0f}; exits: {ends}; average trades per week {len(ts) / (n_days / 5):.2f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat(),
                    help=f"first trade day; the shared START_DATE {START_DATE} - change it in py_funcs, not here")
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    if a.set_moneyness is None:
        a.set_moneyness = DEFAULT_LADDER
    settings = narrow(SETTINGS, a)
    # run_instruments keeps only the rule's own settings at every strike but the rule's: simulate only those there
    if _ACTIVE["collect"] is not None and _ACTIVE["ladder_rung"] not in (None, int(DEFAULT_LADDER)):
        settings = [s if s["mode"] != "sweep" or s["key"] == "moneyness" else
                    dict(s, options=[o for o in s["options"] if o["value"] == s["default"]]) for s in settings]
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    check_window(frm, to)
    trades, skips, log, sessions, option_sessions = asyncio.run(run(frm, to, settings))
    report_skips(skips)
    limits = [
        "WORST FILL ONLY: every buy at the minute's HIGH and every sell at the minute's LOW, on minutes the option "
        "TRADED (volume above zero); build_payload re-checks the rule's trades.",
        "THE STOP AND THE TARGET ARE NOT RESTING ORDERS HERE: each is read on the option's completed 1-minute candle "
        "(its low against the stop, its high against the target) and sold in the NEXT traded minute at that minute's "
        "low (RUN.md rule 3). So a target exit usually pays less than +50% and a stop exit can cost more than 25%. A "
        "live stop-loss order would fill near its own price; a live limit order at the target would fill at the target.",
        "THE STOP AND TARGET ARE SIZED FOR THE 6-ITM OPTION: they are a share of the premium paid. At the money the "
        "premium is smaller and moves more in %, so the same 25% is hit far more often - see 'The rule on every strike'.",
        "THE LINE is Upstox's 'ATR Trailing Stops' as its chart library (ChartIQ) documents it: Wilder's average true "
        f"range of {PERIOD} candles, {MULT:g} of them from the close (HighLow off), the value on a candle computed from "
        "the candles before it. Built from that documentation, not compared tick by tick with a live Upstox chart.",
        f"THE CANDLES run continuously across days, as on a chart. {WARMUP_DAYS} calendar days before the window are "
        f"read to settle the line and the EMA, never traded.",
        f"ASSUMED: the entry takes the first traded option minute within {FILL_WAIT + 1} minutes after the cross "
        f"candle, else no trade; a sale takes the first traded minute from its signal, to 15:29. No new trade from "
        f"{LAST_ENTRY}; whatever is open is sold at {TIME_EXIT}. The strike is counted from the cross candle's close; "
        f"the expiry is the nearest at least one day after the trade day.",
        "SELECTION - IN-SAMPLE: everything v1 chose (the 11:30-13:30 window, 5-minute candles, EMA 5 - about 7,000 "
        "settings looked at, on this same window), and on top of it the stop and the target: about 60 stop / target "
        "pairs were tried on v1's own trades. The 25% stop was the best of them and is hit on only a handful of trades, "
        "so its benefit rests on those few; no target at or under +60% beat having none. Expect less than the report "
        "shows.",
        f"HALVES: {SPLIT} is where the research split the window (Jan-Apr / May-Jul). NIFTY and SENSEX move together, "
        f"so SENSEX agreeing is the same market seen twice, not a second test.",
        f"WINDOW: the shared START_DATE {START_DATE} .. END_DATE; this report was run on {frm} .. {to}.",
        "Capital = premium x qty. 'Entries' and 'Which side' are exact filters: a trade's exit never depends on the "
        "trades before it. A cross that comes while flat (after a stop or a target) is traded like any other.",
        "A win is counted after charges (RUN.md rule 5).",
        "CHARTS: the option's own candles are in the file for the rule's candle and EMA - every cross of the day at the "
        "rule's strike (6 ITM), and the 11:30-13:30 crosses at every other strike - under every stop and target. A "
        "trade of another candle or EMA has its option chart only where it bought the same contract on the same day; "
        "otherwise the page says so and draws the index.",
        "NO OPTION CANDLES / NO TRADE: a cross is not traded when its option did not trade in the 3 minutes after it "
        "- mostly SENSEX on its expiry day, when the next week's deep in-the-money contract is thin - and on "
        "2026-07-31, where some contracts of the following week's expiry are not on local disk. Those days are listed "
        "under 'Every day' as bad data.",
    ]
    lot = trades[-1]["qty"] // LOTS if trades else None
    meta = {
        "title": "ATR Trailing Stop x EMA v2",
        "subtitle": f"On {TF_RULE}-minute NIFTY candles, when the {EMA_RULE}-candle EMA crosses above Upstox's ATR "
                    f"Trailing Stops line ({PERIOD}, {MULT:g}) buy a 6-ITM CALL, when it crosses below buy a 6-ITM PUT - "
                    f"only on crosses from 11:30 to 13:30. Stop 25% under the price paid, target 50% over it; else sell "
                    f"on the opposite cross or at 15:14.",
        "instrument": "NIFTY 50 weekly options",
        "category": CATEGORY,
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": lot,
        "break_date": SPLIT,
        "fill_rule": "WORST FILL ONLY: buy at the minute's HIGH, sell at the minute's LOW, on minutes the option traded",
        "params": {"the line": f"Upstox ATR Trailing Stops: period {PERIOD}, multiplier {MULT:g}, HighLow off",
                   "the average": f"EMA {EMA_RULE} of the candle closes",
                   "candles": f"{TF_RULE}-minute, built from the 1-minute candles, continuous across days",
                   "direction": "EMA crosses above the line -> buy CE, below -> buy PE",
                   "entries": "crosses whose candle finishes 11:30 to 13:25",
                   "stop": "option low 25% under the price paid", "target": "option high 50% over the price paid",
                   "other exits": f"the opposite cross, or {TIME_EXIT}",
                   "lots": LOTS, "expiry": "nearest >= 1 day after the trade day"},
        "rule_steps": [
            f"Draw Upstox's ATR Trailing Stops line (period {PERIOD}, multiplier {MULT:g}) and the {EMA_RULE}-candle "
            f"EMA on {TF_RULE}-minute NIFTY candles.",
            "A candle closes with the EMA above the line (it was at or below on the candle before): buy a CALL. The "
            "EMA below the line (it was at or above): buy a PUT.",
            "Only a cross whose candle finishes from 11:30 to 13:25 opens a trade.",
            "Buy the 6-in-the-money option (from the cross candle's close) in the next minute that trades (within 3 "
            "minutes), at its HIGH. That price is 'paid'.",
            "Stop = 25% under paid; target = 50% over paid. Example: paid Rs 360 -> stop Rs 270, target Rs 540 "
            "(1 lot of 65: about Rs 5,850 at risk for about Rs 11,700).",
            "From the next minute, read each finished 1-minute candle of the option: its low at or under the stop, or "
            "its high at or over the target (both in one minute = the stop) - sell in the next minute the option "
            "trades, at its LOW.",
            f"Neither touched: sell on the next opposite cross (same way), or at {TIME_EXIT}. A new cross between "
            f"11:30 and 13:30 buys the other option.",
        ],
        "limits": limits,
        "rejected": [
            ["A NIFTY-point stop of 1 or 1.5 ATR (about 28-42 points)", "research: hit on about half the trades; with "
             "a 1:1 to 1:3 target the 64 NIFTY trades made Rs -24,000 to Rs +67,000 against Rs 1,16,586 with no stop. "
             "The line sits about 70 points from the entry; the trade needs that room."],
            ["A stop at the ATR line touched inside the minute", "research: Rs 1,21,555 with no target, close to the "
             "25% premium stop, but it does not cap the worst trade (Rs -13,381); with EMA 1 the line is only about "
             "15 points away and it lost."],
            ["A premium stop of 15% or 35%", "research: 15% was hit 17 times and made Rs 98,016; 35% was hit once and "
             "made Rs 1,21,500. 25% is between them and capped the worst trade at Rs -7,753."],
            ["A target of 20%-30% of the premium", "research, with the 25% stop: +20% made Rs 60,389 and +30% "
             "Rs 1,12,276 on NIFTY but Rs 61,596 and Rs 92,515 on SENSEX - a target smaller than the stop gives the "
             "edge away."],
            ["10 and 21-candle ATR, multiplier 2, 15- and 30-minute candles, EMA 21", "compared in v1 "
             "(atr_trail_ema_v1.html); left out here to keep the file a size a browser can open."],
            ["Trailing the stop on the premium", "not tested: the opposite cross of the ATR line already is the trail."],
        ],
        "coverage": coverage(sessions, frm, to, ROWS_PER_SESSION),
        "rerun": rerun_command(SLUG, settings, frm.isoformat(), to.isoformat()),
    }
    groups = [{"name": "Direction", "keys": ["direction"]},
              {"name": "When the cross came", "keys": ["cross time"]},
              {"name": "The day's first cross", "keys": ["the day's first cross"]},
              {"name": "Cross time x direction", "keys": ["cross time", "direction"]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups,
                            settings=settings, chart="all", sessions_log=log, worst_only=True)
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
