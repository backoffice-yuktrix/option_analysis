"""ATR Trailing Stop x EMA - v1: buy a CALL when the EMA crosses above Upstox's ATR Trailing Stops line, sell it and buy a
PUT when it crosses back below, and so on - traded only on the crosses that come in the middle of the day.

THE PROMPT (the user, 2026-10-01): "in the upstox has the ATR trailing stop indicator build that, now you have to add
the EMA on the candles chart, when the ema crosses above the ATR trailing stop indicator buy CE then it crosses below
exit and buy the PE then cross above buy/sell that, run in the loop, try multiple time frames which make the edge", then
"open the upstox in the browser and read how they build that, apply that on charts".

THE INDICATOR - Upstox's "ATR Trailing Stops" is the ChartIQ study; its documentation gives the line R drawn on candle i:
    ATR(i)    = (ATR(i-1) x (Period - 1) + true range(i)) / Period              (Wilder's average; Upstox default Period 21)
    offset(i) = ATR(i-1) x Multiplier                                           (Upstox default Multiplier 3)
    Close(i-1) >  R(i-1) and Close(i-2) >  R(i-1):   R(i) = max(R(i-1), Close(i-1) - offset)      the line trails up
    Close(i-1) <= R(i-1) and Close(i-2) <= R(i-1):   R(i) = min(R(i-1), Close(i-1) + offset)      the line trails down
    Close(i-1) >  R(i-1):                            R(i) = Close(i-1) - offset                   flips under the price
    otherwise:                                       R(i) = Close(i-1) + offset                   flips over the price
  (HighLow off, the default: the close, not the high / low.)  The line on candle i is known when candle i-1 closes.
  EMA(i) = Close(i) x 2 / (N + 1) + EMA(i-1) x (1 - 2 / (N + 1)).  Both run continuously across days, as on the chart.

THE RULE
  Step 1  On 5-minute NIFTY candles (aligned to 09:15) draw the ATR Trailing Stops line (21, 3) and the 5-candle EMA.
  Step 2  A candle closes with the EMA above the line after the candle before had it at or below: buy a CALL.  The
          EMA below the line after at or above: buy a PUT.  If the other option is held, sell it in the same minute.
  Step 3  Only a cross whose candle finishes from 11:30 to 13:25 opens a trade (the order goes in 11:30 .. 13:29).  A
          cross at any other time only closes what is open.
  Step 4  Buy the 6-in-the-money option (strike from that candle's close, nearest expiry at least a day after today)
          in the first minute after the candle that the option trades (to 3 minutes), at that minute's HIGH.
  Step 5  Sell on the next opposite cross - in the first minute after that candle the option trades, at its LOW - or
          at 15:14 if none came.  Same day only; one position at a time.

CHECKLIST (RUN.md step 1)
  underlying NIFTY 50 (and SENSEX through run_instruments) | window: shared START_DATE..END_DATE | signal candles 5m
  (the panel: 5 / 10 / 15 / 30m), built from the 1-minute candles, completed candles only | index_options, bought, 1 lot,
  qty from the contract, 6 ITM (the ladder 6 ITM .. ATM) | entry and exit: steps 2-5 | intraday | standard option costs
  | missing data -> no trade, logged.
  ASSUMED (the prompt gave no numbers): the indicator at Upstox's defaults (Period 21, Multiplier 3, HighLow off);
  EMA 5; 5-minute candles; same day only with a 15:14 square-off and no new trade from 15:00; a zero-volume option
  minute is never a fill.
  NOT IN THE PROMPT: step 3's 11:30-13:30 window.  As written (every cross, all day) the rule lost on every timeframe;
  the window is where the research found the crosses pay.  'Entries' in the panel switches it off.

WHERE IT COMES FROM (scratchpad research, 2026-10-01, real option candles, worst fills, charges; in-sample)
  - Every cross all day, 1 / 3 / 5 / 10 / 15 / 30 / 60-minute candles x EMA 1-50 x ATR 10 / 14 / 21 x multiplier 1-4
    x close / HighLow x ATM / 6 ITM (2,940 settings): 4% made money, none on 1- or 3-minute candles (1-minute at the
    Upstox defaults: 1,563 trades, 25.5% won, Rs -10.6 lakh).  The 25 best of Jan-Apr all lost in May-Jul.
  - The same crosses split by the half hour they came in: 11:15-12:45 made money in both halves of the window on
    nearly every setting; before 11:15 and after 13:45 lost on nearly every setting.
  - Entries 11:30-13:30 only (144 settings on 5 / 10 / 15-minute candles): 83 made money, 48 in both halves; SENSEX 95
    and 57.  A higher-timeframe filter (30m / 60m / day line on the same side) and re-entering at the open did not help.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *          # noqa: F401,F403
from py_funcs import _admits, _ACTIVE
import argparse
import numpy as np

CATEGORY = "index_options"
SLUG = "atr_trail_ema_v1"
TFS = (5, 10, 15, 30)           # signal candles, minutes, aligned to 09:15
TF_RULE = 5
EMAS = (1, 5, 9, 21)            # EMA 1 = the close itself
EMA_RULE = 5
PERIODS = (10, 21)              # ATR Trailing Stops period (Upstox default 21)
PERIOD_RULE = 21
MULTS = (2.0, 3.0)              # ATR Trailing Stops multiplier (Upstox default 3)
MULT_RULE = 3.0
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
CROSS_EXIT, TIME_REASON = "opposite cross", "time exit 15:14"


def rung_label(v: int) -> str:
    return "at the money" if v == 0 else f"{abs(v)} strike{'s' if abs(v) > 1 else ''} {'in' if v > 0 else 'out of'} the money"


def mi(hhmm: str) -> int:
    """HH:MM -> minute index of the session (09:15 = 0)."""
    return hhmm_minutes(hhmm) - hhmm_minutes("09:15")


def hm_of(k: int) -> str:
    m = hhmm_minutes("09:15") + k
    return f"{m // 60:02d}:{m % 60:02d}"


# The control panel.  Defaults = the rule.  The candle, the EMA and the two ATR Trailing Stops inputs each change which
# crosses exist, so each value is simulated on its own.  'Entries' only selects trades by the time of their cross: every
# cross flips the position, so a trade is the same trade whether or not the earlier crosses were traded.
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
    setting("period", "ATR Trailing Stops period", kind="entry", default=str(PERIOD_RULE),
            help="candles in the average true range of the line (Upstox default 21)",
            options=[{"value": str(v), "raw": v, "label": f"{v} candles" + (" (Upstox default, the rule)" if v == PERIOD_RULE else "")}
                     for v in PERIODS]),
    setting("mult", "ATR Trailing Stops multiplier", kind="entry", default=str(MULT_RULE),
            help="how many average true ranges the line sits from the close (Upstox default 3)",
            options=[{"value": str(v), "raw": v, "label": f"{v:g} x ATR" + (" (Upstox default, the rule)" if v == MULT_RULE else "")}
                     for v in MULTS]),
    setting("window", "Entries", kind="entry", mode="filter", default="midday",
            help="which crosses open a trade, by the time their candle finishes; a cross at any time still closes "
                 "the open trade",
            options=[{"value": "midday", "label": "crosses 11:30 to 13:30 (the rule)", "tag": {"cross time": ["11:30-13:29"]}},
                     {"value": "all", "label": "every cross, all day (the prompt as written)", "tag": None},
                     {"value": "morning", "label": "crosses before 11:30", "tag": {"cross time": ["09:15-11:29"]}},
                     {"value": "afternoon", "label": "crosses 13:30 to 15:00", "tag": {"cross time": ["13:30-14:59"]}}]),
    setting("side_pick", "Which side", kind="entry", mode="filter", default="both",
            options=[{"value": "both", "label": "both (the rule)", "tag": None},
                     {"value": "CE", "label": "calls only (crossed above)", "tag": {"direction": [UP_DIR]}},
                     {"value": "PE", "label": "puts only (crossed below)", "tag": {"direction": [DOWN_DIR]}}]),
    setting("moneyness", "Strike depth", kind="strike", default=6, rerun=True,
            options=[{"value": v, "label": rung_label(v), "raw": v} for v in STRIKE_LADDER],
            help="--moneyness 6,0 prices the at-the-money rung on the same crosses"),
]


def options_of(settings: list[dict], key: str) -> list:
    return [o["raw"] for o in next(s for s in settings if s["key"] == key)["options"]]


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


# ---------------------------------------------------------------------------
# fetch + simulate
# ---------------------------------------------------------------------------
async def run(frm: date, to: date, settings: list[dict]):
    skips: list[str] = []
    log: list[dict] = []
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list[list]]] = {}
    rung = options_of(settings, "moneyness")[0]
    combos_ = [(tf, e, n, m) for tf in options_of(settings, "tf") for e in options_of(settings, "ema")
               for n in options_of(settings, "period") for m in options_of(settings, "mult")]
    rule = default_combo(settings)
    rule_c = (rule["tf"], rule["ema"], rule["period"], rule["mult"])
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
              f"{len(combos_)} setting(s) at {rung_label(rung)}")
        # every setting's crosses, from candles that run continuously through the warm-up
        sig: dict[tuple, dict] = {}
        cand = {tf: tf_candles(sessions, tf) for tf in {c[0] for c in combos_}}
        atrs = {(tf, n): wilder_atr(*cand[tf][:3], n) for tf, _, n, _ in combos_}
        for tf, e, n, m in combos_:
            sig[(tf, e, n, m)] = crosses(cand[tf], ema_line(cand[tf][2], e),
                                         trailing_stop(cand[tf][2], atrs[(tf, n)], m), frm.isoformat())
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
                        got = {"c": c, "qty": LOTS * c["lot_size"], "by": by, "rows5": [r[:5] for r in orows],
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
            rule_missing = 0
            for cb in combos_:
                is_rule = cb == rule_c
                evs = [e for e in sig[cb].get(d, []) if e[0] < tx]
                pos = None                                   # the open trade: (contract, entry minute, the cross, first?)
                for n_ev, (k, s, close, em, stop) in enumerate(evs + [(tx, 0, 0.0, 0.0, 0.0)]):
                    if pos is not None:
                        con, ek, ev, first = pos
                        xk = next_traded(con["traded"], k)
                        pos = None
                        if xk is None:
                            skips.append(f"{d}: {con['c']['trading_symbol']} bought {hm_of(ek)} could not be sold "
                                         f"(no traded minute from {hm_of(k)}) - not a trade")
                            rule_missing += is_rule
                        else:
                            ebar, xbar = con["by"][ek], con["by"][xk]
                            entry_px, exit_px = worst_fills("LONG", ebar, xbar)
                            mfe, mae = excursion(con["rows5"], "LONG", entry_px, ebar[0], xbar[0])
                            side = ev[1]
                            lv = ([{"name": "ATR Trailing Stops line at the cross", "price": ev[4]},
                                   {"name": f"EMA {cb[1]} at the cross", "price": ev[3]}] if is_rule else [])
                            t = make_trade(
                                day=d, side="LONG", symbol=con["c"]["trading_symbol"], entry_time=ebar[0],
                                entry_px=entry_px, exit_time=xbar[0], exit_px=exit_px, qty=con["qty"],
                                exit_reason=TIME_REASON if s == 0 else CROSS_EXIT, capital=entry_px * con["qty"],
                                mfe=mfe, mae=mae, expiry=con["c"]["expiry"], option_type="CE" if side > 0 else "PE",
                                variant={"tf": cb[0], "ema": cb[1], "period": cb[2], "mult": cb[3], "moneyness": rung},
                                tags={"direction": UP_DIR if side > 0 else DOWN_DIR,
                                      "cross time": window_of(ev[0]),
                                      "the day's first cross": "yes" if first else "no"},
                                levels=lv,
                                note=f"cross on the {cb[0]}-minute candle finished {hm_of(ev[0])}: close {ev[2]:.2f}, "
                                     f"EMA {ev[3]:.2f}, line {ev[4]:.2f}")
                            trades.append(t)
                            if is_rule and (int(rung) == int(DEFAULT_LADDER) or window_of(ev[0]) == WINDOW_RULE):
                                option_sessions.setdefault(con["c"]["trading_symbol"], {})[d] = con["rows5"]
                            if is_rule:
                                rule_day.append(t)
                                if broker_line is None and expiry >= now.date():
                                    broker_line = await broker_check(up, CATEGORY, con["c"]["instrument_key"],
                                                                     con["qty"], ebar[2])
                    if s == 0 or k >= last_entry:
                        continue
                    typ = "CE" if s > 0 else "PE"
                    con = await contract(d, expiry, typ, strike_offset(close, STEP, rung, typ, itm=True))
                    ek = None if con is None else next_traded(con["traded"], k, last=k + FILL_WAIT)
                    if ek is None or ek >= tx:
                        rule_missing += is_rule
                        if con is not None:
                            skips.append(f"{d}: {con['c']['trading_symbol']} did not trade within {FILL_WAIT + 1} "
                                         f"minutes of the {hm_of(k)} cross - no trade")
                        continue
                    pos = (con, ek, (k, s, close, em, stop), n_ev == 0)
            # the session log records what the RULE's own setting saw
            evs = [e for e in sig[rule_c].get(d, []) if e[0] < last_entry]
            mid = [e for e in evs if window_of(e[0]) == WINDOW_RULE]
            facts = {"crosses before 15:00": len(evs), "crosses 11:30-13:29": len(mid),
                     "first cross": hm_of(evs[0][0]) if evs else None}
            won = [t for t in rule_day if t["tags"]["cross time"] == WINDOW_RULE]
            if won:
                log.append(session_row(d, "traded", f"{len(won)} trade(s): " + ", ".join(
                    f"{t['option_type']} {t['entry_time']}" for t in won), **facts))
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
    """RUN.md rule 11: the days, the halves, and the result without the best trades."""
    if not ts:
        return "day-level check: no trades under the rule"
    by: dict[str, float] = {}
    for t in ts:
        by[t["day"]] = by.get(t["day"], 0.0) + t["net"]
    v = sorted(by.values(), reverse=True)
    net = sorted((t["net"] for t in ts), reverse=True)
    h1 = [t for t in ts if t["day"] < SPLIT]; h2 = [t for t in ts if t["day"] >= SPLIT]
    wr = lambda a: sum(t["net"] > 0 for t in a) / len(a) * 100 if a else float("nan")
    return (f"day-level check (the rule): {len(ts)} trades on {len(by)} days, {sum(x > 0 for x in v)} days made money, "
            f"median day Rs {sorted(v)[len(v) // 2]:,.0f}; net Rs {sum(net):,.0f}, without the best 5 trades "
            f"Rs {sum(net[5:]):,.0f}, without the best 5 days Rs {sum(v[5:]):,.0f}; before {SPLIT}: {len(h1)} trades, "
            f"{wr(h1):.1f}% won, Rs {sum(t['net'] for t in h1):,.0f}; from it: {len(h2)} trades, {wr(h2):.1f}% won, "
            f"Rs {sum(t['net'] for t in h2):,.0f}; average trades per week {len(ts) / (n_days / 5):.2f}")


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
        "THE LINE is Upstox's 'ATR Trailing Stops' as its chart library (ChartIQ) documents it: Wilder's average true "
        "range, the close (HighLow off), and the value on a candle computed from the candles before it. It was built "
        "from that documentation, not compared tick by tick with a live Upstox chart; a chart that starts its history "
        "on another day can differ for the first few dozen candles after its start.",
        f"THE CANDLES run continuously across days, as on a chart: yesterday's last candle is the candle before "
        f"today's first. {WARMUP_DAYS} calendar days before the window are read to settle the line and the EMA, never "
        f"traded. A session's last candle of a size that does not divide 375 minutes (30-minute: 15:15-15:29) is short.",
        f"ASSUMED: the entry takes the first traded option minute within {FILL_WAIT + 1} minutes after the cross "
        f"candle, else no trade; a sale takes the first traded minute from its signal, to 15:29. No new trade from "
        f"{LAST_ENTRY}; whatever is open is sold at {TIME_EXIT}. The strike is counted from the cross candle's close; "
        f"the expiry is the nearest at least one day after the trade day.",
        "SELECTION - IN-SAMPLE: the prompt gave the idea, not the numbers. As written (every cross, all day) it lost "
        "on every timeframe: of 2,940 settings tried on 1- to 60-minute candles 4% made money, none on 1- or 3-minute "
        "candles, and the 25 best of Jan-Apr all lost in May-Jul. The 11:30-13:30 entry window was found by splitting "
        "those same trades by the half hour of their cross, on this same window - about 7,000 settings were looked at "
        "in all. The ATR Trailing Stops inputs are Upstox's defaults (21, 3), not picked; the 5-minute candle and "
        "EMA 5 were picked on the whole window. Expect less than the report shows.",
        f"HALVES: {SPLIT} is where the research split the window (Jan-Apr / May-Jul). NIFTY and SENSEX move together, "
        f"so SENSEX agreeing is the same market seen twice, not a second test.",
        f"WINDOW: the shared START_DATE {START_DATE} .. END_DATE; this report was run on {frm} .. {to}.",
        "Capital = premium x qty. 'Entries' and 'Which side' are exact filters: every cross flips the position, so a "
        "trade is the same trade whether or not the crosses before it were traded.",
        "A win is counted after charges (RUN.md rule 5).",
        "CHARTS: the option's own candles are in the file for the rule's candle / EMA / line settings - every cross "
        "of the day at the rule's strike (6 ITM), and the 11:30-13:30 crosses at every other strike. A trade of "
        "another setting has its option chart only where it bought the same contract on the same day; otherwise the "
        "page says so and draws the index.",
        "NO OPTION CANDLES / NO TRADE: a cross is not traded when its option did not trade in the 3 minutes after it "
        "- mostly SENSEX on its expiry day, when the next week's deep in-the-money contract is thin - and on "
        "2026-07-31, where some contracts of the following week's expiry are not on local disk.",
    ]
    lot = trades[-1]["qty"] // LOTS if trades else None
    meta = {
        "title": "ATR Trailing Stop x EMA v1",
        "subtitle": f"On {TF_RULE}-minute NIFTY candles, when the {EMA_RULE}-candle EMA crosses above Upstox's ATR "
                    f"Trailing Stops line ({PERIOD_RULE}, {MULT_RULE:g}) buy a 6-ITM CALL, when it crosses below buy a "
                    f"6-ITM PUT; sell on the opposite cross or at 15:14. Only crosses from 11:30 to 13:30 open a trade.",
        "instrument": "NIFTY 50 weekly options",
        "category": CATEGORY,
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": lot,
        "break_date": SPLIT,
        "fill_rule": "WORST FILL ONLY: buy at the minute's HIGH, sell at the minute's LOW, on minutes the option traded",
        "params": {"the line": f"Upstox ATR Trailing Stops: period {PERIOD_RULE}, multiplier {MULT_RULE:g}, HighLow off",
                   "the average": f"EMA {EMA_RULE} of the candle closes",
                   "candles": f"{TF_RULE}-minute, built from the 1-minute candles, continuous across days",
                   "direction": "EMA crosses above the line -> buy CE, below -> buy PE",
                   "entries": "crosses whose candle finishes 11:30 to 13:25", "exit": f"the opposite cross, or {TIME_EXIT}",
                   "lots": LOTS, "expiry": "nearest >= 1 day after the trade day"},
        "rule_steps": [
            f"Draw Upstox's ATR Trailing Stops line (period {PERIOD_RULE}, multiplier {MULT_RULE:g}) on {TF_RULE}-minute "
            f"NIFTY candles: in an up move it sits {MULT_RULE:g} average true ranges under the last close and only "
            f"rises; when a candle closes under it, it jumps to {MULT_RULE:g} average true ranges over the close and "
            f"only falls. Example: closes near 25,000 with a 5-minute average true range of 12 points put the line at "
            f"24,964.",
            f"Draw the {EMA_RULE}-candle EMA of the closes on the same chart.",
            "A candle closes with the EMA above the line (it was at or below on the candle before): buy a CALL. The "
            "EMA below the line (it was at or above): buy a PUT.",
            "Only a cross whose candle finishes from 11:30 to 13:25 opens a trade. A cross at any other time only "
            "closes the open trade.",
            "Buy the 6-in-the-money option (from the cross candle's close) in the next minute that trades (within 3 "
            "minutes), at its HIGH.",
            f"Sell on the next opposite cross, in the next minute the option trades, at its LOW - or at {TIME_EXIT} if "
            f"no cross came. If that cross is also between 11:30 and 13:30, the other option is bought in the same "
            f"minute.",
        ],
        "limits": limits,
        "rejected": [
            ["1-minute and 3-minute candles", "research: every setting lost. 1-minute at the Upstox defaults made "
             "1,563 trades, 25.5% won, Rs -10.6 lakh at 6 ITM; 3-minute 462 trades, Rs -2.9 lakh. The fills alone "
             "(buy the high, sell the low) cost more than the moves between crosses."],
            ["60-minute candles", "research: 39-63 trades in seven months at the defaults, all losing; too few crosses "
             "inside one day."],
            ["Multiplier 1 and 1.5", "research: the line sits inside the noise - 2 to 4 times the trades and the "
             "worst results of the sweep (1.5 on 10-minute candles did work inside the midday window: 87 trades, "
             "Rs +1.12 lakh, both halves positive - not shipped to keep the file small)."],
            ["HighLow on (the line from the candle's high / low)", "research: no better than the close on 5- to "
             "30-minute candles; the default is the close."],
            ["A longer EMA (50)", "research: crosses come late and the trade count rises from re-crossing; no setting "
             "with it was among the profitable ones."],
            ["Trade only with the higher timeframe (the 30-minute, 60-minute or daily line on the same side)",
             "research: 16-22% of settings profitable against 15% without it, and none stable across both halves - "
             "the time of day explained far more than the higher timeframe."],
            ["Re-enter at the open in the direction the EMA already sits", "research: worse than crosses only (15% of "
             "settings profitable against 22%)."],
            ["Holding overnight", "not tested: the prompt's loop is read as one session; an overnight hold needs the "
             "expiry roll and gap risk of a different strategy."],
            ["A stop or a target on the option", "the prompt exits on the opposite cross only; the line is the stop."],
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
