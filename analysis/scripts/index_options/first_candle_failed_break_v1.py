"""First-Candle Failed Break - v1: fade a break of the first 5-minute candle once it has failed.

THE USER'S IDEA (2026-10-02)
  "Mark the first 5 min candle high.  For short: from that high a certain percentage like 0.25, 0.30, 0.50
  has given a reversal of at least 80 to 100 points.  For long: mark the first 5 min candle low, from that
  low a certain percentage ... reversal of at least 80 to 100 points.  Find the exact rule."

WHAT THE CANDLES SAID (mined fresh on NIFTY and SENSEX 1-minute candles, 2026-01-01..2026-07-31)
  Selling the first touch of the level is a coin flip: after a 0.25% touch, 80 points in favour came before
  80 against on 52% of shorts and 29% of longs, and with real option prices it lost at every percentage.
  A pullback from the peak, a level scaled by the candle's own range and one scaled by VIX did no better.
  What does fit: the break has to FAIL first.  Price makes a new day high at least 0.25% above the first
  candle's high and then a 1-minute candle closes back below that high (mirror for the low).  From there the
  index gave 80 points in the trade's favour on about two days in three, on both sides and in both halves,
  and the result grew with the size of the break.  It pays from late morning on: failures before 11:00-11:30
  do not cover the option's costs.

THE RULE
  Step 1  First candle: the HIGH and LOW of 09:15-09:19 (five 1-minute candles).
  Step 2  Up-break: a 1-minute candle makes a new day high at least 0.25% above the first candle's high.
          Down-break: a new day low at least 0.25% below the first candle's low.
  Step 3  Failure (the signal): after an up-break, the first 1-minute candle that CLOSES below the first
          candle's high; after a down-break, the first that closes above the first candle's low.  A side
          signals again only after a new, further day high (low).
  Step 4  Only signals whose entry minute is 11:30 to 14:30 are taken.
  Step 5  Failed up-break: buy the at-the-money PUT.  Failed down-break: buy the at-the-money CALL.  Strike
          from the signal candle's close; expiry the nearest at least a day after today; 1 lot.  Buy in the
          next minute at its HIGH.
  Step 6  Reference = the signal candle's close on the index.  Target: the index 80 points in the trade's
          favour.  Stop: 80 points against.  Read on completed index minutes; sell in the next minute at its
          LOW.  Both in one minute: the stop counts.
  Step 7  Nothing by then: sell in the 15:14 minute at its LOW.  One position at a time, never overnight.

CHECKLIST (RUN.md step 1) - every item clear or assumed
  underlying the index (1m) | window: shared START_DATE..END_DATE | signal 1m candles, first candle = 5 x 1m |
  decision at the close of the signal candle | failed up-break -> PE, failed down-break -> CE |
  index_options, buy, ATM (the runner adds the strike ladder), nearest expiry >= 1 day after today, 1 lot |
  exits as steps 6-7, on index points scaled by price_scale() | intraday | standard option costs |
  one position at a time | missing data -> no trade, logged.
  ASSUMED: a minute in which the option did not trade (volume 0) is not a fill - the order takes the next
  minute that traded, at most 2 minutes later, else no trade (entry) or the 15:14 exit (exit).
  ASSUMED: the index trigger is read from the entry minute on (a completed candle), and sells one minute later.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *          # noqa: F401,F403
from py_funcs import _admits    # the panel's own filter test, reused for the rule's trades
import argparse

CATEGORY = "index_options"
SLUG = "first_candle_failed_break_v1"
FIRST_N = 5                     # 1-minute candles in the first candle (09:15-09:19)
LAST_ENTRY = "14:30"
TIME_EXIT = "15:14"
FILL_WAIT = 2                   # a zero-volume minute is not a fill: wait up to this many minutes more
ROWS_PER_SESSION = 375
STEP = strike_step()            # 50 on NIFTY, 100 on SENSEX - read from the contract list
SC = price_scale()              # NIFTY points -> this index's points (the same share of the price)
LOTS = 1
SPLIT = "2026-04-01"            # option STT rose from 0.10% to 0.15% of the sale
BREAK_RULE, START_RULE, EXIT_RULE = "0.25", "11:30", "80/80"
UP_DIR, DOWN_DIR = "failed up-break: buy PE", "failed down-break: buy CE"
EXITS = {"80/80": (80, 80), "100/100": (100, 100), "100/60": (100, 60), "hold/80": (None, 80), "hold": (None, None)}
EXIT_LABEL = {"80/80": "target 80, stop 80 index points", "100/100": "target 100, stop 100",
              "100/60": "target 100, stop 60", "hold/80": "no target, stop 80, sell 15:14",
              "hold": "no target, no stop, sell 15:14"}

# The control panel.  Defaults = the rule.
SETTINGS = [
    setting("brk", "Break needed before it fails", kind="entry", default=BREAK_RULE,
            help="how far beyond the first candle's high (low) the day's new high (low) must go, in % of the price",
            options=[{"value": v, "label": f"{v}% beyond the first candle" + (" (the rule)" if v == BREAK_RULE else ""),
                      "raw": float(v)} for v in ("0.15", "0.20", "0.25", "0.30", "0.35")]),
    setting("start", "Earliest entry", kind="entry", default=START_RULE,
            help="a failure before this time is not traded; the last entry is 14:30 at every value",
            options=[{"value": "09:21", "label": "any time from 09:21", "raw": "09:21"},
                     {"value": "10:30", "raw": "10:30"}, {"value": "11:00", "raw": "11:00"},
                     {"value": "11:30", "label": "11:30 (the rule)", "raw": "11:30"},
                     {"value": "12:00", "raw": "12:00"}]),
    setting("side_pick", "Which side", kind="entry", mode="filter", default="both",
            help="one position at a time was simulated with both sides on",
            options=[{"value": "both", "label": "both (the rule)", "tag": None},
                     {"value": "PE", "label": "puts only (failed up-breaks)", "tag": {"direction": [UP_DIR]}},
                     {"value": "CE", "label": "calls only (failed down-breaks)", "tag": {"direction": [DOWN_DIR]}}]),
    setting("exit", "Exit", kind="exit", default=EXIT_RULE,
            help="index points from the signal candle's close, the same share of the price on SENSEX",
            options=[{"value": k, "label": EXIT_LABEL[k] + (" (the rule)" if k == EXIT_RULE else ""), "raw": k}
                     for k in EXITS]),
]


def values_of(settings: list[dict], key: str) -> list:
    return [o["raw"] for o in next(s for s in settings if s["key"] == key)["options"]]


def add_min(hhmm: str, n: int) -> str:
    m = hhmm_minutes(hhmm) + n
    return f"{m // 60:02d}:{m % 60:02d}"


# ---------------------------------------------------------------------------
# signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def failed_breaks(rows: list[list], pct: float) -> list[dict]:
    """Every failed break of the day, in time order.  `i` is the SIGNAL candle: the first 1-minute candle
    that closes back inside the first candle after a new day high (low) at least `pct` % beyond it."""
    hi5 = max(r[2] for r in rows[:FIRST_N]); lo5 = min(r[3] for r in rows[:FIRST_N])
    up_lvl, dn_lvl = hi5 * (1 + pct / 100), lo5 * (1 - pct / 100)
    top, bot = (hi5, None), (lo5, None)            # the day's running high / low and the candle that set it
    up = dn = False
    out = []
    for i in range(FIRST_N, len(rows)):
        _, _, h, l, c = rows[i][:5]
        if h > top[0]:
            top = (h, i)
            up = up or h >= up_lvl
        if l < bot[0]:
            bot = (l, i)
            dn = dn or l <= dn_lvl
        if up and c < hi5:
            out.append({"i": i, "dir": "up", "peak": top[0], "peak_i": top[1], "ref": hi5,
                        "ext": (top[0] / hi5 - 1) * 100})
            up = False
        if dn and c > lo5:
            out.append({"i": i, "dir": "dn", "peak": bot[0], "peak_i": bot[1], "ref": lo5,
                        "ext": (1 - bot[0] / lo5) * 100})
            dn = False
    return out


def index_trigger(rows: list[list], j0: int, sign: int, anchor: float, target, stop) -> tuple[str, str] | None:
    """(minute, 'target'|'stop') of the first completed index candle from rows[j0] that reaches the stop
    (checked first) or the target, measured from `anchor`; None = neither before 15:13.
    sign +1 = the trade wants the index UP (a call), -1 = DOWN (a put)."""
    for r in rows[j0:]:
        if r[0] >= add_min(TIME_EXIT, -1):
            return None
        fav = (r[2] - anchor) if sign == 1 else (anchor - r[3])
        adv = (anchor - r[3]) if sign == 1 else (r[2] - anchor)
        if stop is not None and adv >= stop * SC:
            return r[0], "stop"
        if target is not None and fav >= target * SC:
            return r[0], "target"
    return None


def traded(bar: list | None) -> bool:
    return bar is not None and bar[5] > 0


def fill_from(by: dict, hhmm: str) -> list | None:
    """The first minute at or after `hhmm` (up to FILL_WAIT minutes later) in which the option traded."""
    for k in range(FILL_WAIT + 1):
        b = by.get(add_min(hhmm, k))
        if traded(b):
            return b
    return None


def size_label(ext: float) -> str:
    return bucket(ext, [0.20, 0.25, 0.30, 0.40, 0.60],
                  ["under 0.20%", "0.20-0.25%", "0.25-0.30%", "0.30-0.40%", "0.40-0.60%", "0.60% and more"])


def time_label(t: str) -> str:
    for a, lab in (("10:30", "before 10:30"), ("11:30", "10:30-11:29"), ("12:30", "11:30-12:29"), ("13:30", "12:30-13:29")):
        if t < a:
            return lab
    return "13:30-14:30"


def wait_label(n: int) -> str:
    return "peak 15 min ago or less" if n <= 15 else "peak 16-45 min ago" if n <= 45 else \
        "peak 46-120 min ago" if n <= 120 else "peak over 2 hours ago"


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
async def run(frm: date, to: date, settings: list[dict]):
    skips: list[str] = []
    log: list[dict] = []
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list[list]]] = {}
    rule = default_combo(settings)
    priced: dict = {}                               # (day, signal index) -> contract, candles, entry bar
    async with Upstox() as up:
        und = await up.find_instrument(instrument())
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        if info["strike_step"] != STEP:
            raise SystemExit(f"strike step on disk is {info['strike_step']}, the script read {STEP}.")
        sessions = await up.minute_sessions(key, frm, to)
        cal = await up.expiry_calendar(key, frm, to)
        full = {d: r for d, r in sessions.items() if len(r) >= ROWS_PER_SESSION}
        days = [d for d in sorted(full) if frm.isoformat() <= d <= to.isoformat()]
        print(f"{instrument()}: index sessions {len(sessions)}, complete {len(full)}, in window {len(days)}; "
              f"{len(combos(settings))} setting combinations re-scan the same local candles")
        for d, r in sessions.items():
            if d not in full and frm.isoformat() <= d <= to.isoformat():
                skips.append(f"{d}: session incomplete ({len(r)} bars) - not used")
                log.append(session_row(d, "no data", f"session incomplete: {len(r)} of {ROWS_PER_SESSION} candles"))

        async def price(d: str, rows: list[list], s: dict):
            """The contract, its candles and the entry bar for one signal - read once, reused by every setting."""
            k = (d, s["i"], s["dir"])
            if k in priced:
                return priced[k]
            day = date.fromisoformat(d)
            opt_type = "PE" if s["dir"] == "up" else "CE"
            anchor = rows[s["i"]][4]
            expiry = next_expiry(cal, day, 1)
            got = None
            if expiry is None:
                why = "no expiry at least a day after this day"
            else:
                c = await up.resolve_option(key, expiry, atm_strike(anchor, STEP), opt_type)
                if c is None:
                    why = f"contract {expiry} {atm_strike(anchor, STEP):.0f} {opt_type} not on disk"
                elif c["lot_size"] <= 0:
                    why = "the contract carries no lot size"
                else:
                    orows = await up.option_candles(c, day, volume=True)
                    by = {r[0]: r for r in orows}
                    eb = fill_from(by, rows[s["i"] + 1][0])
                    why = None if eb is not None else \
                        f"nothing traded in {c['trading_symbol']} in the {FILL_WAIT + 1} minutes after the signal"
                    if eb is not None:
                        got = (c, orows, by, eb)
            priced[k] = (got, why)
            return priced[k]

        for d in days:
            rows = full[d]
            hi5 = max(r[2] for r in rows[:FIRST_N]); lo5 = min(r[3] for r in rows[:FIRST_N])
            day_hi = max(r[2] for r in rows[FIRST_N:]); day_lo = min(r[3] for r in rows[FIRST_N:])
            facts = {"first candle high": hi5, "first candle low": lo5,
                     "furthest above the high %": round(max(day_hi / hi5 - 1, 0) * 100, 2),
                     "furthest below the low %": round(max(1 - day_lo / lo5, 0) * 100, 2)}
            seen = {"status": "no signal", "note": f"no break of {rule['brk']}% failed back inside the first candle"}
            for brk in values_of(settings, "brk"):
                sigs = [s for s in failed_breaks(rows, brk) if s["i"] + 1 < len(rows)]
                for start in values_of(settings, "start"):
                    is_rule_entry = brk == rule["brk"] and start == rule["start"]
                    if is_rule_entry and sigs:
                        first = rows[sigs[0]["i"]][0]
                        seen = {"status": "declined", "note": f"{len(sigs)} failed break(s), the first at {first}, none "
                                                              f"with an entry between {start} and {LAST_ENTRY} - "
                                                              f"set 'Earliest entry' to count them"}
                    for ex in values_of(settings, "exit"):
                        is_rule = is_rule_entry and ex == rule["exit"]
                        target, stop = EXITS[ex]
                        busy = ""                            # exit minute of the open trade
                        for s in sigs:
                            t_in = rows[s["i"] + 1][0]
                            if not (start <= t_in <= LAST_ENTRY) or t_in <= busy:
                                continue
                            got, why = await price(d, rows, s)
                            tag = f"{d} {rows[s['i']][0]} [{brk}% from {start}, {ex}]"
                            if got is None:
                                if is_rule:
                                    skips.append(f"{tag}: {why}")
                                    if seen["status"] != "traded":
                                        seen = {"status": "no data", "note": why}
                                continue
                            c, orows, by, eb = got
                            sign = -1 if s["dir"] == "up" else 1
                            anchor = rows[s["i"]][4]
                            j0 = next(j for j, r in enumerate(rows) if r[0] >= eb[0])
                            trig = index_trigger(rows, j0, sign, anchor, target, stop)
                            xb, reason = None, "time exit 15:14"
                            if trig is not None:
                                xb = fill_from(by, add_min(trig[0], 1))
                                reason = f"{trig[1]}: index {EXITS[ex][0 if trig[1] == 'target' else 1]} points " \
                                         f"{'in favour' if trig[1] == 'target' else 'against'}"
                            if xb is None:
                                xb = fill_from(by, TIME_EXIT)
                                if trig is not None:
                                    reason += ", filled at 15:14 (no trade in the option before)"
                            if xb is None:
                                if is_rule:
                                    skips.append(f"{tag}: bought {c['trading_symbol']} but nothing traded 15:14-15:16")
                                    if seen["status"] != "traded":
                                        seen = {"status": "no data", "note": "the option did not trade at the exit"}
                                continue
                            busy = xb[0]
                            qty = LOTS * c["lot_size"]
                            entry_px, exit_px = worst_fills("LONG", eb, xb)
                            if entry_px != eb[2] or exit_px != xb[3]:
                                raise SystemExit(f"{tag}: fill is not the worst price")
                            mfe, mae = excursion([r[:5] for r in orows], "LONG", entry_px, eb[0], xb[0])
                            direction = UP_DIR if s["dir"] == "up" else DOWN_DIR
                            lv = [{"name": "first candle high", "price": hi5}, {"name": "first candle low", "price": lo5},
                                  {"name": f"break level ({brk}%)", "price": s["ref"] * (1 + brk / 100 * (1 if s["dir"] == "up" else -1))},
                                  {"name": "the break's extreme", "price": s["peak"]}]
                            if target is not None:
                                lv.append({"name": f"index target ({target})", "price": anchor + sign * target * SC, "from": eb[0]})
                            if stop is not None:
                                lv.append({"name": f"index stop ({stop})", "price": anchor - sign * stop * SC, "from": eb[0]})
                            trades.append(make_trade(
                                day=d, side="LONG", symbol=c["trading_symbol"], entry_time=eb[0], entry_px=entry_px,
                                exit_time=xb[0], exit_px=exit_px, qty=qty, exit_reason=reason, capital=entry_px * qty,
                                mfe=mfe, mae=mae, expiry=c["expiry"], option_type=c["option_type"],
                                variant={"brk": f"{brk:.2f}", "start": start, "exit": ex},
                                tags={"direction": direction, "break size": size_label(s["ext"]),
                                      "entry time": time_label(eb[0]),
                                      "since the peak": wait_label(s["i"] - s["peak_i"])},
                                levels=lv,
                                note=(f"new day {'high' if s['dir'] == 'up' else 'low'} {s['peak']:.2f} at "
                                      f"{rows[s['peak_i']][0]}, {s['ext']:.2f}% beyond the first candle's "
                                      f"{'high' if s['dir'] == 'up' else 'low'} {s['ref']:.2f}; the {rows[s['i']][0]} candle "
                                      f"closed back inside at {anchor:.2f}; {EXIT_LABEL[ex]}")))
                            if is_rule:
                                option_sessions.setdefault(c["trading_symbol"], {})[d] = orows
                                seen = {"status": "traded", "note": f"bought {c['trading_symbol']} at {eb[0]}"}
            log.append(session_row(d, seen["status"], seen["note"], **facts))
        print(f"upstox calls: {up.calls} (local data only)")
    return trades, skips, log, full, option_sessions


def rule_trades(trades: list[dict], settings: list[dict]) -> list[dict]:
    """The trades the panel shows under the rule: every setting at its own default."""
    sweep = {s["key"]: s["default"] for s in settings if s["mode"] == "sweep"}
    fopt = [next(o for o in s["options"] if o["value"] == s["default"]) for s in settings if s["mode"] == "filter"]
    return [t for t in trades if all(t["variant"].get(k) == v for k, v in sweep.items())
            and all(_admits(t, o) for o in fopt)]


def day_level_check(ts: list[dict]) -> str:
    if not ts:
        return "day-level check: no trades under the rule"
    by: dict[str, float] = {}
    for t in ts:
        by[t["day"]] = by.get(t["day"], 0.0) + t["net"]
    v = sorted(by.values(), reverse=True)
    h1 = [t["net"] for t in ts if t["day"] < SPLIT]; h2 = [t["net"] for t in ts if t["day"] >= SPLIT]
    return (f"day-level check (the rule): {len(v)} days, {sum(x > 0 for x in v)} made money, median day "
            f"Rs {sorted(v)[len(v) // 2]:,.0f}, total Rs {sum(v):,.0f}, without the best 3 days Rs {sum(v[3:]):,.0f}, "
            f"without the best 5 Rs {sum(v[5:]):,.0f}; before {SPLIT} Rs {sum(h1):,.0f} over {len(h1)}, "
            f"from it Rs {sum(h2):,.0f} over {len(h2)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat())
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    settings = narrow(SETTINGS, a)
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    check_window(frm, to)
    trades, skips, log, sessions, option_sessions = asyncio.run(run(frm, to, settings))
    if skips:
        print(f"\n{len(skips)} skipped under the rule:")
        for s in skips:
            print("  " + s)
    limits = [
        "WORST FILL ONLY: every buy at the minute's HIGH and every sell at the minute's LOW; the script stops if "
        "any trade is filled otherwise.",
        "SMALL SAMPLE: the rule makes about one trade a week - around 30 trades per index in seven months. Thirty "
        "trades cannot settle a win rate; read it as a lead to follow, not a proven edge.",
        "SELECTION, IN-SAMPLE: the pattern was mined on 1 Jan - 31 Jul 2026, the same window this report shows. "
        "Tried first and dropped: selling the first touch of the level, a pullback from the peak, a level scaled "
        "by the first candle's range and one scaled by VIX. The 0.25% break and the 11:30 start were both chosen "
        "with hindsight; 11:00 and 12:00, and 0.20% and 0.30%, are in the panel to show it is not one lucky cell.",
        "THE TWO INDICES ARE NOT TWO TESTS: NIFTY and SENSEX move together, so SENSEX agreeing is the same days "
        "seen twice, not independent confirmation.",
        "OUTSIDE THE WINDOW: on the 32 NIFTY sessions on disk outside it (24 Nov - 31 Dec 2025, 3-7 Aug 2026) the "
        "index gave 4 such signals from 11:30 and they lost on balance. Too few to judge, but not a confirmation.",
        "BEFORE 11:30 IT LOSES: the same failed break taken in the morning did not cover the option's costs "
        "(set 'Earliest entry' to see it). The rule's time filter is the part most likely to be fitted.",
        f"ASSUMED: a minute in which the option did not trade (volume 0) is not a fill. The order takes the next "
        f"minute that traded, at most {FILL_WAIT} minutes later; no entry fill means no trade (the day is bad data).",
        "ASSUMED: target and stop are index points measured from the signal candle's close, read on completed "
        "1-minute index candles from the entry minute on, and sold one minute later; a minute that reaches both "
        "counts as the stop. On SENSEX the points are the same share of the price (80 NIFTY points = about 258).",
        "ASSUMED: a side signals again only after a new, further day high (low); one position at a time, so a "
        "signal while a trade is open is not taken.",
        "The strike is at the money from the signal candle's close; the expiry is the nearest at least one day "
        "after the trade day, so no trade is in an expiry-day contract.",
        f"WINDOW: the shared START_DATE {START_DATE} .. END_DATE; this report was run on {frm} .. {to}.",
        "Capital = premium x qty.",
    ]
    ruled = rule_trades(trades, settings)
    meta = {
        "title": "First-Candle Failed Break v1",
        "subtitle": "When the index makes a new day high at least 0.25% above the first 5-minute candle's high and "
                    "then closes back below that high (or the mirror below the low), from 11:30 buy the "
                    "at-the-money option against the failed break. Target 80 index points, stop 80, out by 15:14. "
                    "Worst fill only.",
        "instrument": "NIFTY 50 weekly options",
        "category": CATEGORY,
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": ruled[-1]["qty"] // LOTS if ruled else None,
        "break_date": SPLIT,
        "fill_rule": "WORST FILL ONLY: buy at the minute's HIGH, sell at the minute's LOW; a signal acts in the "
                     "next 1-minute candle that traded",
        "params": {"first candle": "09:15-09:19 (five 1-minute candles)",
                   "the rule": f"break {BREAK_RULE}%, entry {START_RULE}-{LAST_ENTRY}, {EXIT_LABEL[EXIT_RULE]}",
                   "direction": "failed up-break -> buy PE, failed down-break -> buy CE",
                   "strike": "at the money from the signal candle's close", "strike step": f"{STEP:.0f}",
                   "expiry": "nearest >= 1 day after the trade day", "lots": LOTS, "time exit": TIME_EXIT},
        "rule_steps": [
            "Mark the HIGH and LOW of the first 5-minute candle (09:15-09:19).",
            f"Up-break: a new day high at least {BREAK_RULE}% above that high. Example: first candle high 25,000 -> "
            f"the day's high must reach 25,062.5 or more. Down-break: a new day low at least {BREAK_RULE}% below the low.",
            "The signal is the failure: after an up-break, the first 1-minute candle that CLOSES below the first "
            "candle's high (below 25,000 in the example). After a down-break, the first that closes above the low.",
            f"Take it only if the next minute is between {START_RULE} and {LAST_ENTRY}.",
            "Failed up-break: buy the at-the-money PUT. Failed down-break: buy the at-the-money CALL. Nearest expiry "
            "at least a day away, 1 lot, in the next minute at its HIGH.",
            "From the signal candle's close on the index: target 80 points in your favour, stop 80 points against. "
            "Example: signal close 24,990 on a failed up-break -> target 24,910, stop 25,070. Sell in the minute "
            "after the index gets there, at its LOW.",
            "Neither by 15:14: sell in the 15:14 minute at its LOW. One position at a time; a side trades again "
            "only after a new, further day high (low).",
        ],
        "limits": limits,
        "rejected": [
            ["Selling the first touch of the level (the idea as first worded)", "tested: 80 points in favour before "
             "80 against on 52% of shorts and 29% of longs at 0.25%; with options it lost at 0.15%-0.50%."],
            ["A pullback from the peak as the trigger (15-40 points)", "tested: the target was hit exactly as often as "
             "chance in every zone beyond the candle."],
            ["The level as a multiple of the first candle's range, or of the VIX-implied day move", "tested: no "
             "better than the fixed percentage."],
            ["Break sizes of 0.50% and more", "the result was strongest there but with about a dozen signals in "
             "seven months - too few to be a setting."],
            ["A 5-minute close as the failure signal", "not tested; the 1-minute close is the earliest completed "
             "candle and the fills are 1-minute either way."],
            ["Strike depth", "the runner prices the rule on every strike from 6 in the money to at the money."],
        ],
        "coverage": coverage(sessions, frm, to, ROWS_PER_SESSION),
        "rerun": rerun_command(SLUG, settings, frm.isoformat(), to.isoformat()),
    }
    groups = [{"name": "Direction", "keys": ["direction"]},
              {"name": "How far the break went", "keys": ["break size"]},
              {"name": "Entry time", "keys": ["entry time"]},
              {"name": "Time since the break's peak", "keys": ["since the peak"]},
              {"name": "Direction x entry time", "keys": ["direction", "entry time"]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups,
                            settings=settings, chart="default", sessions_log=log)
    path = write_report(payload, SLUG)
    print(day_level_check(ruled))
    print("THE RULE: " + console_summary(ruled))
    print(f"every setting pooled ({len(trades)} trades across {len(combos(settings))} combinations; not a book)")
    print(path)


if __name__ == "__main__":
    run_instruments(__file__)
elif __name__ == "__instrument__":
    main()
