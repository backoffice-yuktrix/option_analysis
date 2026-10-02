"""5-Day Stretch Fade - v1: a same-day NIFTY option trade against a stretched 5-day move.

THE IDEA
  When NIFTY has run far from where it closed five sessions ago, the rest of the day tends to give some of
  that run back.  At 11:00 the rule buys an in-the-money option against the run and closes it the same day.
  A losing trade is not held to the close: it waits for the first chance to get out at cost (the recovery
  exit).  A winning trade rides to 15:14 above a profit floor.

THE RULE
  Step 1  At 11:00 (the 11:00 one-minute candle complete), stretch = (NIFTY's 11:00 close - the official close
          5 sessions ago) / the average daily range of the last 14 sessions (true range, simple average).
  Step 2  Stretch above +0.75: the 5-day move is up - buy a PUT.  Below -0.75: buy a CALL.  Otherwise no trade.
  Step 3  Strike 6 in the money (300 points) from the 11:00 close rounded to 50; expiry the nearest at least a
          day after today (never the expiry day itself, RUN.md rule 10).  1 lot, qty from the contract.
  Step 4  Buy in the 11:01 minute at its HIGH.  Line = paid + round-trip charges per unit.
  Step 5  The 13:00 check, on the option's 13:00 candle:
            LOW at or below the line (losing) -> recovery exit: sell at the first later minute whose LOW is
                                                  above the line, in the next minute at its LOW;
            LOW above the line (winning)      -> hold, but sell if a minute's LOW falls to line + 16 points,
                                                  in the next minute at its LOW.
  Step 6  Nothing by then: sell in the 15:14 minute at its LOW.  One trade a day, never overnight.

CHECKLIST (RUN.md step 1) - every item clear or assumed
  underlying NIFTY 50 index (1m) | window: shared START_DATE..END_DATE, run on the one-year study window
  2025-09-29..2026-09-25 | signal 1m 11:00 candle + daily candles | decision 11:00 | stretch up -> PE,
  down -> CE | index_options, buy, 6 ITM, nearest expiry >= 1 day after today, 1 lot | exits as steps 5-6 |
  intraday | standard option costs | one trade a day | missing data -> no trade, logged.
  ASSUMED: a minute in which nothing traded (volume 0) is not a fill - the order fills in the next minute
  that traded, at most 2 minutes later, else no trade (entry) or the scan goes on (exit).  The check and
  the triggers READ a candle (volume 0 included); only fills need a trade.  The 15:14 exit likewise takes
  the first traded minute of 15:14-15:16.

HOW THE VALUES WERE FOUND (scratchpad, 2026-09-29; real option candles with volume, worst fills, charges)
  About 25 same-day direction signals (VWAP, banks lead, breadth, futures OI, gap, VIX, range and close
  location) at 10 decision times; only the 5-day stretch fade kept its sign in both halves of the year.  It
  also works with 3/7/10-session lookbacks and the 10-day average, not with 2 sessions.  Every quick-profit
  exit (10-80 index points) removed the edge; the 13:00 check kept it and lifted the win rate.  All values
  were chosen looking at the whole year (in-sample).
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *          # noqa: F401,F403
from py_funcs import _admits    # the panel's own filter test, reused for the day-level check
import argparse

CATEGORY = "index_options"
SLUG = "stretch_fade_v1"
SIGNAL_MIN = "11:00"            # the decision candle
TIME_EXIT = "15:14"
STEP = strike_step()             # 50 on NIFTY, 100 on SENSEX - read from the contract list
LOTS = 1
LOOKBACK = 5                    # sessions back for the stretch reference close
RANGE_N = 14                    # sessions in the average daily range
STRETCH_RULE = 0.75             # the rule: trade when |stretch| is above this
FILL_WAIT = 2                   # a zero-volume minute is not a fill: wait up to this many minutes more
DAILY_LOOKBACK_DAYS = 45        # calendar days of daily candles before --from (5 + 14 + 1 sessions and holidays)
ROWS_PER_SESSION = 375
SPLIT = "2026-04-01"            # option STT rose from 0.10% to 0.15% of the sale; also the study's halves
DEFAULT_LADDER = ",".join(str(v) for v in STRIKE_LADDER)   # 6 ITM .. ATM (the user, 2026-09-30)
UP_DIR, DOWN_DIR = "5-day move up: buy PE", "5-day move down: buy CE"
AT_LOSING, AT_WINNING, AT_NONE = "losing at the check", "winning at the check", "no check"
SIZE_EDGES = [0.5, 0.75, 1.0, 1.25]
SIZE_LABELS = ["0.5 or less", "0.5-0.75", "0.75-1.0", "1.0-1.25", "above 1.25"]
REASON = {"time": "time exit 15:14", "rescue": "rescue: back above paid + charges",
          "floor": "floor: winner fell back", "loser": "time exit, losing at the check",
          "winner": "time exit, winning at the check"}


def rung_label(v: int) -> str:
    return "at the money" if v == 0 else f"{abs(v)} strikes {'in' if v > 0 else 'out of'} the money"


def size_label(x: float) -> str:
    """|stretch| bucket, each bucket (low, high] so 'above 0.75' is exactly the rule's test."""
    a = abs(x)
    for e, lab in zip(SIZE_EDGES, SIZE_LABELS):
        if a <= e:
            return lab
    return SIZE_LABELS[-1]


def above(th: float) -> list[str]:
    return [lab for e, lab in zip([0.0] + SIZE_EDGES, SIZE_LABELS) if e >= th]


# The control panel.  Defaults = the rule.
SETTINGS = [
    setting("stretch", "Stretch needed", kind="entry", mode="filter", default=str(STRETCH_RULE),
            help="how far NIFTY at 11:00 must be from the close 5 sessions ago, in average daily ranges",
            options=[{"value": "any", "label": "any stretch - every day", "tag": None},
                     *[{"value": str(t), "label": f"above {t} x the average range" + (" (the rule)" if t == STRETCH_RULE else ""),
                        "tag": {"stretch size": above(t)}} for t in (0.5, 0.75, 1.0, 1.25)]]),
    setting("side_pick", "Which side", kind="entry", mode="filter", default="both",
            help="each day is one side only, so 'both' is the whole book",
            options=[{"value": "both", "label": "both (the rule)", "tag": None},
                     {"value": "CE", "label": "calls only (5-day move down)", "tag": {"direction": [DOWN_DIR]}},
                     {"value": "PE", "label": "puts only (5-day move up)", "tag": {"direction": [UP_DIR]}}]),
    setting("check", "Check time", kind="exit", default="13:00",
            help="when a losing trade switches to the recovery exit and a winning one gets its floor",
            options=[{"value": "12:30", "raw": "12:30"}, {"value": "13:00", "label": "13:00 (the rule)", "raw": "13:00"},
                     {"value": "13:30", "raw": "13:30"},
                     {"value": "none", "label": "no check - hold to 15:14", "raw": None}]),
    setting("floor", "After the check, a winner", kind="exit", default="16",
            help="option points above paid + charges; with no check time it has nothing to act on",
            options=[{"value": "8", "label": "sells if it falls to 8 points above paid + charges", "raw": 8.0},
                     {"value": "16", "label": "sells if it falls to 16 points above paid + charges (the rule)", "raw": 16.0},
                     {"value": "24", "label": "sells if it falls to 24 points above paid + charges", "raw": 24.0},
                     {"value": "hold", "label": "is held to 15:14 with no floor", "raw": "hold"}]),
    setting("moneyness", "Strike depth", kind="strike", default=6, rerun=True,
            options=[{"value": v, "label": rung_label(v), "raw": v} for v in STRIKE_LADDER],
            help="every rung is priced on the same days; --moneyness narrows the ladder"),
]


def values_of(settings: list[dict], key: str) -> list:
    return [o["raw"] for o in next(s for s in settings if s["key"] == key)["options"]]


def add_min(hhmm: str, n: int) -> str:
    m = hhmm_minutes(hhmm) + n
    return f"{m // 60:02d}:{m % 60:02d}"


# ---------------------------------------------------------------------------
# signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def day_facts(daily: list[list], d: str) -> dict | None:
    """The reference close 5 sessions back and the average daily range of the 14 sessions before `d`,
    from DAILY candles [[day, o, h, l, c], ...] (official closes).  None when the history is too short."""
    days = [r[0] for r in daily]
    if d not in days:
        return None
    j = days.index(d)
    if j < RANGE_N + 1 or j < LOOKBACK:
        return None
    tr = [max(daily[k][2] - daily[k][3], abs(daily[k][2] - daily[k - 1][4]), abs(daily[k][3] - daily[k - 1][4]))
          for k in range(j - RANGE_N, j)]
    return {"ref": daily[j - LOOKBACK][4], "ref_day": daily[j - LOOKBACK][0], "range": sum(tr) / RANGE_N}


def signal(rows: list[list], facts: dict) -> tuple[str | None, str, float | None, float | None]:
    """(option type 'CE'|'PE'|None, reason, stretch, 11:00 close)."""
    bar = next((r for r in rows if r[0] == SIGNAL_MIN), None)
    if bar is None:
        return None, "the 11:00 candle is missing", None, None
    if facts["range"] <= 0:
        return None, "the average daily range is zero", None, bar[4]
    x = (bar[4] - facts["ref"]) / facts["range"]
    if x > 0:
        return "PE", "11:00 above the close 5 sessions ago", x, bar[4]
    if x < 0:
        return "CE", "11:00 below the close 5 sessions ago", x, bar[4]
    return None, "11:00 exactly at the close 5 sessions ago", x, bar[4]


def breakeven_line(entry_px: float, qty: int, day=None) -> float:
    """Entry price + round-trip costs per unit, costs evaluated with the sale at the line (fixed point)."""
    line = entry_px
    for _ in range(60):
        new = entry_px + option_round_trip("LONG", entry_px, line, qty, day=day) / qty
        if abs(new - line) < 1e-6:
            return new
        line = new
    return line


# ---------------------------------------------------------------------------
# simulate (pure: option bars -> exit)
# ---------------------------------------------------------------------------
def traded(bar: list | None) -> bool:
    return bar is not None and bar[5] > 0


def fill_from(by: dict, hhmm: str) -> list | None:
    """The first minute at or after `hhmm` (up to FILL_WAIT minutes later) in which the option traded."""
    for k in range(FILL_WAIT + 1):
        b = by.get(add_min(hhmm, k))
        if traded(b):
            return b
    return None


def simulate_exit(rows: list[list], entry_bar: list, line: float, check: str | None, floor) -> dict:
    """Walk the option's own minutes after the entry.  A trigger is read on a COMPLETED minute's LOW
    and sells in the next traded minute at its LOW (rules 1-3); the 15:14 exit sells in 15:14 itself.
    Returns {"bar", "reason", "at_check"}; bar None = the day could not be exited (no data)."""
    by = {r[0]: r for r in rows}
    later = [r[0] for r in rows if entry_bar[0] < r[0] < TIME_EXIT]

    def time_exit(reason: str, state: str) -> dict:
        return {"bar": fill_from(by, TIME_EXIT), "reason": reason, "at_check": state}

    def first_sale(times: list[str], hit, reason: str, state: str) -> dict | None:
        for t in times:
            if hit(by[t][3]):
                b = fill_from(by, add_min(t, 1))
                if b is not None:
                    return {"bar": b, "reason": reason, "at_check": state}
        return None

    if check is None:
        return time_exit(REASON["time"], AT_NONE)
    cb = by.get(check)
    if cb is None:
        return {"bar": None, "reason": f"the option's {check} candle is missing", "at_check": None}
    state = AT_LOSING if cb[3] <= line else AT_WINNING
    after = [t for t in later if t > check]
    if state == AT_LOSING:                                   # the recovery exit
        got = first_sale(after, lambda lo: lo > line, REASON["rescue"], state)
        return got or time_exit(REASON["loser"], state)
    if floor != "hold":                                      # a winner keeps its floor
        got = first_sale(after, lambda lo: lo <= line + floor * price_scale(), REASON["floor"], state)
        if got:
            return got
    return time_exit(REASON["winner"], state)


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
    checks = values_of(settings, "check")
    floors = values_of(settings, "floor")
    rule = default_combo(settings)
    chart_rung = rule["moneyness"]
    broker_line = None
    async with Upstox() as up:
        und = await up.find_instrument(instrument())
        key = und["instrument_key"]
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
        traded_days = [d for d in sorted(full) if frm.isoformat() <= d <= to.isoformat()]
        print(f"index sessions: {len(sessions)}, complete: {len(full)}, in window: {len(traded_days)}; "
              f"daily candles: {len(daily)} from {daily[0][0] if daily else '-'}")
        print(f"strike ladder {[rung_label(v) for v in rungs]}: {fetch_estimate(len(traded_days) * len(rungs))} "
              f"(fewer with the candle cache). Check times {checks} and floors {floors} re-scan the same candles.")
        for d in traded_days:
            rows = full[d]
            facts = day_facts(daily, d)
            if facts is None:
                skips.append(f"{d}: fewer than {RANGE_N + 1} daily candles before it")
                log.append(session_row(d, "no data", f"not enough daily candles before this day for the "
                                                     f"{RANGE_N}-session range"))
                continue
            opt_type, why, x, c1100 = signal(rows, facts)
            base = {"11:00 NIFTY": c1100, f"close {LOOKBACK} sessions ago": facts["ref"],
                    f"average daily range ({RANGE_N} sessions)": facts["range"], "stretch (x range)": x}
            if opt_type is None:
                skips.append(f"{d}: no trade - {why}")
                log.append(session_row(d, "no data" if c1100 is None else "no signal", why, **base))
                continue
            direction = UP_DIR if opt_type == "PE" else DOWN_DIR
            size = size_label(x)
            base.update({"direction": direction, "stretch size": size})
            open915 = rows[0][1]
            so_far = "already moving the trade's way" if (c1100 - open915) * (1 if opt_type == "CE" else -1) > 0 \
                else "still against the trade"
            expiry = next_expiry(cal, date.fromisoformat(d), 1)
            if expiry is None:
                skips.append(f"{d}: no expiry at least a day after it")
                log.append(session_row(d, "no data", "no expiry at least a day after this day", **base))
                continue
            rule_ok = abs(x) > STRETCH_RULE
            seen = {"status": "no data", "facts": dict(base),
                    "note": f"the rule's own rung ({rung_label(chart_rung)}) could not be priced"}
            for steps in rungs:
                tag = f"{d} [{steps} ITM]"
                strike = strike_offset(c1100, STEP, steps, opt_type, itm=True)
                c = await up.resolve_option(key, expiry, strike, opt_type)
                if c is None:
                    skips.append(f"{tag}: contract {expiry} {strike:.0f} {opt_type} not found")
                    if steps == chart_rung:
                        seen["note"] = f"the contract {expiry} {strike:.0f} {opt_type} does not exist"
                    continue
                qty = LOTS * c["lot_size"]
                if qty <= 0:
                    skips.append(f"{tag}: contract lot size missing")
                    if steps == chart_rung:
                        seen["note"] = "the contract carries no lot size"
                    continue
                orows = await up.option_candles(c, date.fromisoformat(d), volume=True)
                ob = {r[0]: r for r in orows}
                entry_bar = fill_from(ob, add_min(SIGNAL_MIN, 1))
                if entry_bar is None:
                    skips.append(f"{tag}: nothing traded in the option 11:01-11:03 ({c['trading_symbol']})")
                    if steps == chart_rung:
                        seen["note"] = "nothing traded in the option between 11:01 and 11:03"
                    continue
                line = breakeven_line(entry_bar[2], qty, d)                 # BUY at the minute's HIGH
                if steps == chart_rung:
                    seen = {"status": "traded" if rule_ok else "declined",
                            "note": (f"bought {c['trading_symbol']} at {entry_bar[0]}" if rule_ok else
                                     f"stretch {x:+.2f} x the average range is not beyond {STRETCH_RULE} - set "
                                     f"'Stretch needed' to count it"),
                            "facts": dict(base, **{"strike": strike, "premium paid": entry_bar[2],
                                                   "line (paid + charges)": line})}
                bars5 = [r[:5] for r in orows]
                rule_exit = None                 # why the rule's own exit failed, on the charted rung
                for chk in checks:
                    for fl in floors:
                        ex = simulate_exit(orows, entry_bar, line, chk, fl)
                        if ex["bar"] is None:
                            why_x = ex["reason"] if ex["at_check"] is None else "nothing traded 15:14-15:16"
                            skips.append(f"{tag} check {chk or 'none'} floor {fl}: {why_x} ({c['trading_symbol']})")
                            if steps == chart_rung and chk == rule["check"] and fl == rule["floor"]:
                                rule_exit = why_x
                            continue
                        exit_bar = ex["bar"]
                        entry_px, exit_px = worst_fills("LONG", entry_bar, exit_bar)
                        # WORST FILL ONLY on every rung - the report keeps only the rule rung's candles
                        if entry_px != entry_bar[2] or exit_px != exit_bar[3]:
                            raise SystemExit(f"{tag}: fill is not the worst price")
                        mfe, mae = excursion(bars5, "LONG", entry_px, entry_bar[0], exit_bar[0])
                        if steps == chart_rung and chk == rule["check"] and fl == rule["floor"]:
                            seen["facts"]["at the check"] = ex["at_check"]
                        trades.append(make_trade(
                            day=d, side="LONG", symbol=c["trading_symbol"], entry_time=entry_bar[0],
                            entry_px=entry_px, exit_time=exit_bar[0], exit_px=exit_px, qty=qty,
                            exit_reason=ex["reason"], capital=entry_px * qty,
                            target=round(line, 2), mfe=mfe, mae=mae, expiry=c["expiry"], option_type=opt_type,
                            variant={"moneyness": steps, "check": chk or "none",
                                     "floor": fl if isinstance(fl, str) else f"{fl:g}"},
                            tags={"direction": direction, "stretch size": size, "at the check": ex["at_check"],
                                  "index 09:15 to 11:00": so_far},
                            levels=[{"name": f"close {LOOKBACK} sessions ago ({facts['ref_day']})", "price": facts["ref"]},
                                    {"name": "11:00 close", "price": c1100},
                                    {"name": "strike", "price": strike}],
                            note=(f"{rung_label(steps)}; stretch {x:+.2f} x the {RANGE_N}-session average range "
                                  f"({facts['range']:.0f} pts); line (paid + charges) {line:.2f} drawn as 'target'; "
                                  f"check {chk or 'none'}, winner floor "
                                  f"{fl if isinstance(fl, str) else f'line + {fl:g}'}")))
                if steps == chart_rung and rule_exit is not None:
                    seen["status"] = "no data"
                    seen["note"] = (f"bought {c['trading_symbol']} at {entry_bar[0]}, but the rule could not sell it: "
                                    f"{rule_exit} - no trade is counted for this day")
                if steps == chart_rung:
                    option_sessions.setdefault(c["trading_symbol"], {})[d] = orows
                    if broker_line is None and expiry >= now.date():
                        broker_line = await broker_check(up, CATEGORY, c["instrument_key"], qty, entry_bar[2])
            log.append(session_row(d, seen["status"], seen["note"], **seen["facts"]))
        print(broker_line or "broker check skipped: no live contract was traded in this window")
        print(f"upstox calls: {up.calls}, paced {up.paced / 60:.1f} min"
              + (f", rate-limited {up.throttled} times" if up.throttled else ""))
    return trades, skips, log, full, option_sessions


def report_skips(skips: list[str]) -> None:
    buckets: dict[str, list[str]] = {}
    for s in skips:
        reason = s.split(": ", 1)[1] if ": " in s else s
        reason = reason.split(" (")[0]
        buckets.setdefault(reason.strip(), []).append(s)
    print(f"\n{len(skips)} day/rung/exit combinations skipped or not traded, by reason:")
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


def day_level_check(ts: list[dict]) -> str:
    """RUN.md rule 11: days that made money, the median day, the book without its best days - for the rule."""
    if not ts:
        return "day-level check: no trades under the rule"
    by: dict[str, float] = {}
    for t in ts:
        by[t["day"]] = by.get(t["day"], 0.0) + t["net"]
    v = sorted(by.values(), reverse=True)
    med = sorted(v)[len(v) // 2]
    h1 = [t["net"] for t in ts if t["day"] < SPLIT]; h2 = [t["net"] for t in ts if t["day"] >= SPLIT]
    return (f"day-level check (the rule): {len(v)} days, {sum(x > 0 for x in v)} made money "
            f"({sum(x > 0 for x in v) / len(v) * 100:.1f}%), median day Rs {med:,.0f}, total Rs {sum(v):,.0f}, "
            f"without the best 5 days Rs {sum(v[5:]):,.0f}, without the best 10 Rs {sum(v[10:]):,.0f}; "
            f"before {SPLIT} Rs {sum(h1):,.0f} over {len(h1)}, from it Rs {sum(h2):,.0f} over {len(h2)}")


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
    rule = default_combo(settings)
    limits = [
        "WORST FILL ONLY: every buy at the minute's HIGH and every sell at the minute's LOW. The script stops if any "
        "trade on any rung is filled otherwise, and build_payload re-checks the rule rung's trades.",
        f"ASSUMED: a minute in which the option did not trade (volume 0) is not a fill. The order fills in the next "
        f"minute that traded, at most {FILL_WAIT} minutes later; an entry with nothing traded 11:01-11:03 is no "
        f"trade (the day is 'no data'), and an exit trigger with no trade in the next {FILL_WAIT + 1} minutes lets the "
        f"scan go on. The check and every trigger READ a candle, traded or not.",
        f"ASSUMED: the stretch reference is the OFFICIAL daily close {LOOKBACK} sessions before the trade day, and "
        f"the average daily range is the simple average of the true range (high-low, or the gap from the previous "
        f"close when bigger) of the {RANGE_N} sessions before it, both from Upstox daily candles.",
        "ASSUMED: the strike reference is the close of the 11:00 index candle, rounded to 50; the expiry is the "
        "nearest at least one day after the trade day, so a trade is never in an expiry-day contract.",
        "ASSUMED: the line = paid + round-trip charges per unit, charges worked out with the sale at the line. The "
        "floor is in the option's own points above that line (16 = about 20 index points at a 0.8 delta).",
        "With 'no check - hold to 15:14', the winner setting has nothing to act on, so all its values give the "
        "same trades.",
        "SELECTION: the signal, 11:00, the 0.75 stretch, the 13:00 check and the 16-point floor were chosen on "
        "29 Sep 2025 - 25 Sep 2026, the same year this report shows. About 25 signals at 10 decision times, and "
        "many exits, were tried first. It is in-sample; nothing here is out of sample.",
        f"HALVES: before {SPLIT} the rule was weak (study: 58.8% won, +Rs 23k); from it strong (72.0%, +Rs 1.43L). "
        f"{SPLIT} is also when STT on an option sale rose from 0.10% to 0.15%, which the costs follow.",
        "BIG DAYS CARRY IT: the trades still winning at the check and held to 15:14 make the profit; without the "
        "best 10 trades the study book was about -Rs 18k. Expect flat or losing months.",
        f"WINDOW: the shared START_DATE {START_DATE} .. END_DATE; this report was run on {frm} .. {to}."
        f" Daily candles from {DAILY_LOOKBACK_DAYS} calendar days "
        f"before the window are read for the stretch and the range, never traded.",
        "Capital = premium x qty, so it differs by rung and return on capital is comparable across the ladder.",
    ]
    lot = trades[-1]["qty"] // LOTS if trades else None
    meta = {
        "title": "5-Day Stretch Fade v1",
        "subtitle": "At 11:00, when NIFTY has run far from its close 5 sessions ago, buy a 6-ITM option against "
                    "that run. At 13:00 a losing trade sells once back above paid + charges (the recovery exit); a "
                    "winning one rides to 15:14 above a floor. Same-day only. Worst fill only.",
        "instrument": "NIFTY 50 weekly options",
        "category": CATEGORY,
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": lot,
        "break_date": SPLIT,
        "fill_rule": "WORST FILL ONLY: buy at the minute's HIGH, sell at the minute's LOW; signals act in the next "
                     "1-minute candle that traded",
        "params": {"signal": f"(11:00 close - close {LOOKBACK} sessions ago) / average daily range of {RANGE_N} sessions",
                   "the rule": f"stretch above {STRETCH_RULE}, {rung_label(rule['moneyness'])}, check {rule['check']}, "
                               f"winner floor line + {rule['floor']:g} points",
                   "direction": "stretch up -> buy PE, stretch down -> buy CE",
                   "strike step": f"{STEP:.0f}", "entry": "11:01 (first traded minute to 11:03)",
                   "time exit": TIME_EXIT, "lots": LOTS, "expiry": "nearest >= 1 day after the trade day",
                   "strike ladder": ", ".join(rung_label(v) for v in values_of(settings, "moneyness"))},
        "rule_steps": [
            f"At 11:00, take NIFTY's 11:00 close and the official close {LOOKBACK} sessions ago.",
            f"Stretch = the difference / the average daily range of the last {RANGE_N} sessions. Example: 25,000 at "
            f"11:00, 24,700 five sessions ago, average range 250 -> stretch 300 / 250 = 1.2.",
            f"Stretch above +{STRETCH_RULE}: buy a PUT. Below -{STRETCH_RULE}: buy a CALL. Otherwise no trade today.",
            "Strike 6 in the money from the 11:00 close (the example: the 25,300 PE); expiry the nearest at least a "
            "day after today; 1 lot.",
            "Buy in the 11:01 minute at its HIGH. Line = what you paid + the round-trip charges per unit.",
            "At 13:00, read the option's 13:00 candle. Its LOW at or below the line (losing): sell at the first "
            "later minute whose LOW is above the line, in the next minute at its LOW.",
            "Its LOW above the line (winning): hold, but if a minute's LOW falls to line + 16 points, sell in the "
            "next minute at its LOW.",
            "Nothing by then: sell in the 15:14 minute at its LOW. One trade a day, never overnight.",
        ],
        "limits": limits,
        "rejected": [
            ["Selling a winner as soon as it is above paid + charges", "tested in the study: the win rate rises "
             "(67.5%) but the profit drops to about +Rs 1.08L, because the edge is paid by the winners that run to "
             "15:14."],
            ["A fixed profit target (10-80 index points) or a quick first exit", "tested in the study: every one "
             "turned the book flat or negative. The same-day edge is in the trend afternoons."],
            ["Another decision time", "11:30 was about as good (study 64.8%, +Rs 1.34L) and 10:30 weaker; the strike "
             "and side are read at 11:00, so another time needs new option data - not offered."],
            ["Other lookbacks (3, 7, 10 sessions, the 10- or 20-day average)", "tested at the index: 3/7/10 and the "
             "10-day average also work, 2 sessions does not; kept to one lookback so the rule stays one number."],
            ["A second signal on the days this one does not fire", "banks lead, breadth and VWAP at 12:00-13:00 all "
             "lost on those days in the study."],
            ["Filters on VWAP, futures OI, the gap, the day's range, the close location", "none lifted the win rate "
             "in both halves; 'index 09:15 to 11:00' is kept as a group-by to read."],
            ["A stop loss", "a hard stop of 80-120 index points gave about the same result with a lower win rate; "
             "the recovery exit does the loss control instead."],
        ],
        "coverage": coverage(sessions, frm, to, ROWS_PER_SESSION),
        "rerun": rerun_command(SLUG, settings, frm.isoformat(), to.isoformat()),
    }
    groups = [{"name": "Direction", "keys": ["direction"]},
              {"name": "How big the stretch was", "keys": ["stretch size"]},
              {"name": "Direction x stretch", "keys": ["direction", "stretch size"]},
              {"name": "At the check", "keys": ["at the check"]},
              {"name": "NIFTY 09:15 to 11:00", "keys": ["index 09:15 to 11:00"]},
              {"name": "Direction x at the check", "keys": ["direction", "at the check"]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups,
                            settings=settings, chart="default", sessions_log=log, worst_only=True)
    path = write_report(payload, SLUG)
    ruled = rule_trades(trades, settings)
    print(day_level_check(ruled))
    print("THE RULE: " + console_summary(ruled))
    print(f"every setting pooled ({len(trades)} trades across {len(combos(settings))} exit x strike combinations; "
          f"not a book): " + console_summary(trades))
    print(path)


if __name__ == "__main__":
    run_instruments(__file__)
elif __name__ == "__instrument__":
    main()
