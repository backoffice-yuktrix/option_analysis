"""Opening Range Reversal - v1 (report name: orr_v1)

STRATEGY PROMPT (verbatim)
--------------------------
v1 ORR
### v1 - price must be outside the range

Step 1 - The opening range is the first five 1-minute candles, 09:15 to 09:19: the range high is the highest high of those five and the range low is the lowest low.
Step 2 - The decision time is 11:30. Take NIFTY's 1-minute close at exactly that minute and call it the spot.
Step 3 - Look at every 1-minute candle from 09:20 to 11:30 - I need at least 20 of them, otherwise skip the day.
Step 4 - That window must be a clean one-way move: fit a straight line through its closes, and the line must slope down with the last close below the first (a down move) or slope up with the last close above the first (an up move). A flat line is not a trend.
Step 5 - The spot at 11:30 must be OUTSIDE the opening range. If it is still inside, there is no trade. This is the one condition that makes this v1.
Step 6 - If the spot is below the range low, no candle in the window may have traded above the range high, and the move must be down: buy a CE - I am fading the fall and expecting the bounce.
Step 7 - If the spot is above the range high, no candle in the window may have traded below the range low, and the move must be up: buy a PE - I am fading the rise.
Step 8 - Touching a level does not count as breaking it: a high exactly equal to the range high still counts as having stayed below it, and a low equal to the range low still counts as having stayed above.
Step 9 - Skip the day when price broke both edges, when the window has no clear direction, or when the edge that survived and the direction of the move point opposite ways.
Step 10 - The stop is 0.1% of the entry spot placed against the trade, and the target is that stop distance multiplied by 2; also score the same entries at 3, 3.5, 4, 4.5 and 5.
Step 11 - From the minute after 11:30, check each 1-minute index candle in turn and close the trade the moment either level is touched, filled exactly at that level; if one candle touches both, count it as the stop.
Step 12 - If neither level is touched by 15:00, close the trade there. One trade per day, no re-entry.
Step 13 - Run the whole thing separately at 11:00, 11:10, 11:15, 11:20, 11:40, 11:45 and 12:00 as well, each its own independent set of trades.
Two other readings of step 4 exist but are not the default: the loose one looks at the slope alone, and the strict one also requires the three thirds of the window to step down (or up) in order.

CHECKLIST (RUN.md Step 1) - no interactive gaps; assumptions marked ASSUMED
---------------------------------------------------------------------------
1  Underlying        clear     NIFTY 50 index 1-minute candles.
2  Window            ASSUMED   default: 2026-01-01 through the current IST date (--from / --to).
3  Signal timeframe  clear     1 minute.
4  Signal rule       clear     OR = 09:15-09:19 high/low; window = 1m candles 09:20..decision; OLS slope of closes;
                               strict comparisons (touch is not a break); >= 20 window candles.
5  Decision time     ASSUMED   "close at exactly 11:30" = the candle STAMPED 11:30 (it completes at 11:31); the window
                               includes that candle; the trade is placed in the 1-minute bar stamped 11:31 (rule 2).
6  Direction         clear     spot below OR low + down move -> buy CE; above OR high + up move -> buy PE.
7  Traded instrument ASSUMED   NIFTY weekly/monthly option bought (prompt says "buy a CE / PE"); stop/target are read on
                               the INDEX, the fills happen on the option's bars.
8  Option specifics  ASSUMED   ATM strike at the spot (strike step read from Upstox), expiry = nearest at least 1 day
                               after the trade day, 1 lot (qty = lot_size of the resolved contract).
9  Entry             clear     no condition beyond the signal.
10 Exit              ASSUMED   stop = 0.1% of spot against the trade, target = R x stop distance (index levels; R in
                               2, 3, 3.5, 4, 4.5, 5), both checked on 1m index candles from the candle after the
                               decision candle (11:31 onward); time exit at 15:00 (that bar). Tie -> stop first.
11 Holding period    clear     intraday.
12 Costs             ASSUMED   standard option schedule (option_costs).
13 Position rules    clear     one trade per day per (decision time, R) set; no re-entry.
14 Missing data      ASSUMED   skip and list (default).
15 Filters           clear     decision (8 times) x rr (6 values) [+ side].
16 Custom group-bys  ASSUMED   none requested; one group "direction" (CE fade-the-fall / PE fade-the-rise) is added.
17 Script name       ASSUMED   orr_v1.

ASSUMED / DEVIATIONS FROM THE PROMPT (also in meta["limits"])
- Rule 1: fills at the option bar's HIGH (buy) / LOW (sell), not "exactly at the level" (step 11).
- Rule 2/3: stop/target touched on the index is a signal; the option is sold in the NEXT 1-minute bar.
- Rule 2: entry is the bar after the decision candle completes (11:31 for a 11:30 decision).
- The 15:00 time exit fills in the 15:00 bar itself (low of the option bar).
- Stop/target checking starts with the 11:31 index bar (the prompt's "minute after 11:30"); the entry bar itself is
  therefore also scanned - a touch in it exits in the following bar.
- Rule 10: expiry-day contracts are never used (>= 1 day after the trade day).
- Strike step is read from the LIVE chain today and applied to the past.
- The chosen R values / decision times are all shown (variants); nothing is optimised - the result is not tuned but
  the eight decision times x six R values are looked at on the same window, so pick-the-best is in-sample.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *          # noqa: F401,F403
import argparse
from collections import Counter
from datetime import date, datetime, timedelta

SLUG = "orr_v1"
DECISIONS = ["11:00", "11:10", "11:15", "11:20", "11:30", "11:40", "11:45", "12:00"]
RRS = [2.0, 3.0, 3.5, 4.0, 4.5, 5.0]
OR_START, OR_END, WIN_START = "09:15", "09:19", "09:20"
MIN_WINDOW = 20
STOP_PCT = 0.001
TIME_EXIT = "15:00"
ROWS = 375
LOTS = 1


def add_min(t: str, m: int) -> str:
    x = hhmm_minutes(t) + m
    return f"{x // 60:02d}:{x % 60:02d}"


def rr_label(r: float) -> str:
    return f"1:{r:g}"


def valid_session(rows: list[list]) -> str | None:
    """None when the session is complete and sane, else the reason."""
    if len(rows) != ROWS:
        return f"session has {len(rows)} bars, not {ROWS}"
    keys = [r[0] for r in rows]
    if len(set(keys)) != len(keys) or keys[0] != "09:15" or keys[-1] != "15:29":
        return "duplicate or misplaced bars"
    for r in rows:
        if not (r[2] >= max(r[1], r[4], r[3]) and r[3] <= min(r[1], r[4], r[2]) and r[3] > 0):
            return f"invalid candle at {r[0]}"
    return None


def slope(y: list[float]) -> float:
    n = len(y)
    xm, ym = (n - 1) / 2, sum(y) / n
    den = sum((i - xm) ** 2 for i in range(n))
    return sum((i - xm) * (v - ym) for i, v in enumerate(y)) / den


# ---------------------------------------------------------------------------
# signal: pure, completed candles only (index rows up to and including the decision candle)
# ---------------------------------------------------------------------------
def signal(rows: list[list], decision: str) -> tuple[dict | None, str]:
    """Returns (signal, "") or (None, reason)."""
    by = {r[0]: r for r in rows}
    orb = [by.get(add_min(OR_START, k)) for k in range(5)]
    if None in orb:
        return None, "opening range bars missing"
    orh, orl = max(r[2] for r in orb), min(r[3] for r in orb)
    win = [r for r in rows if WIN_START <= r[0] <= decision]
    want = hhmm_minutes(decision) - hhmm_minutes(WIN_START) + 1
    if len(win) != want:
        return None, f"window has {len(win)} of {want} candles (gap)"
    if len(win) < MIN_WINDOW:
        return None, f"window has only {len(win)} candles (< {MIN_WINDOW})"
    spot = win[-1][4]
    if not (spot < orl or spot > orh):
        return None, f"spot {spot:.2f} still inside range {orl:.2f}-{orh:.2f}"
    broke_hi = any(r[2] > orh for r in win)
    broke_lo = any(r[3] < orl for r in win)
    if broke_hi and broke_lo:
        return None, "price broke both edges"
    closes = [r[4] for r in win]
    sl = slope(closes)
    if sl < 0 and closes[-1] < closes[0]:
        move = "down"
    elif sl > 0 and closes[-1] > closes[0]:
        move = "up"
    else:
        return None, "no clear direction (slope/last-vs-first disagree or flat)"
    if spot < orl:                                  # below the range: low edge broken, high edge must survive
        if broke_hi:
            return None, "below range but high edge also broken"
        if move != "down":
            return None, "below range but move is up (opposite ways)"
        return {"opt": "CE", "spot": spot, "orh": orh, "orl": orl, "slope": sl, "move": move,
                "direction": "fade fall (CE)"}, ""
    if broke_lo:
        return None, "above range but low edge also broken"
    if move != "up":
        return None, "above range but move is down (opposite ways)"
    return {"opt": "PE", "spot": spot, "orh": orh, "orl": orl, "slope": sl, "move": move,
            "direction": "fade rise (PE)"}, ""


# ---------------------------------------------------------------------------
# simulate: pure - index bars trigger, option bars fill
# ---------------------------------------------------------------------------
def simulate(idx_rows: list[list], opt_rows: list[list], sig: dict, decision: str, rr: float) -> tuple[dict | None, str]:
    """Entry: option bar after the decision candle.  Stop/target: index levels, scanned from the candle after
    the decision candle; exit: option bar after the trigger (rule 3) or the 15:00 bar itself."""
    entry_bar = bar_after_candle(opt_rows, decision, 1, strict=True)
    if entry_bar is None:
        return None, f"option bar {add_min(decision, 1)} missing"
    d = sig["spot"] * STOP_PCT
    if sig["opt"] == "CE":                         # index expected to bounce up
        idx_side, stop, target = "LONG", sig["spot"] - d, sig["spot"] + rr * d
    else:
        idx_side, stop, target = "SHORT", sig["spot"] + d, sig["spot"] - rr * d
    sc = scan_exit(idx_rows, idx_side, decision, stop=stop, target=target, force_key=TIME_EXIT)
    if sc["bar"] is None:
        return None, f"no exit bar ({sc['reason']})"
    ob = {r[0]: r for r in opt_rows}
    exit_bar = ob.get(sc["bar"][0])
    if exit_bar is None:
        return None, f"option exit bar {sc['bar'][0]} missing"
    if exit_bar[0] <= entry_bar[0]:
        return None, "exit not after entry"
    entry_px, exit_px = worst_fills("LONG", entry_bar, exit_bar)
    return {"entry_bar": entry_bar, "exit_bar": exit_bar, "entry_px": entry_px, "exit_px": exit_px,
            "reason": sc["reason"], "stop": stop, "target": target, "trigger": sc["trigger"]}, ""


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
async def main_async(frm: date, to: date) -> None:
    trades: list[dict] = []
    skips: list[str] = []
    skip_kinds: Counter = Counter()
    option_sessions: dict[str, dict[str, list]] = {}

    def skip(day, dec, why):
        skips.append(f"{day} {dec or '     '}: {why}")
        print(f"  skip {day} {dec or ''}: {why}")
        skip_kinds[why.split(" (")[0].split(" 0")[0][:40]] += 1

    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        step = info["strike_step"]
        cal = await up.expiry_calendar(key, frm, to)
        print(f"NIFTY {key}, strike step {step}, {len(cal)} expiries known, {frm} -> {to}")
        cs = await up.candles(key, "1m", frm, to)
        sessions = sessions_from(cs)
        now = datetime.now(IST)
        if now.date().isoformat() in sessions and (now.date() == to) and now.strftime("%H:%M") < "15:45":
            del sessions[now.date().isoformat()]
            print("  today's session dropped (not over yet)")
        cov = coverage(sessions, frm, to, ROWS)
        for g in cov["weekday_gaps"]:
            skip(g, "", "weekday with no candles (holiday or feed gap)")

        contracts: dict = {}
        obars: dict = {}
        for day_s, rows in sessions.items():
            day = date.fromisoformat(day_s)
            bad = valid_session(rows)
            if bad:
                skip(day_s, "", bad)
                continue
            for dec in DECISIONS:
                sig, why = signal(rows, dec)
                if sig is None:
                    skip(day_s, dec, why)
                    continue
                exp = next_expiry(cal, day, 1)
                if exp is None:
                    skip(day_s, dec, "no expiry at least 1 day after the trade day")
                    continue
                strike = atm_strike(sig["spot"], step)
                ck = (exp, strike, sig["opt"])
                if ck not in contracts:
                    contracts[ck] = await up.resolve_option(key, exp, strike, sig["opt"])
                c = contracts[ck]
                if not c or not c["lot_size"]:
                    skip(day_s, dec, f"contract {exp} {strike:g} {sig['opt']} not found")
                    continue
                bk = (c["trading_symbol"], day_s)
                if bk not in obars:
                    obars[bk] = await up.option_candles(c, day)
                orows = obars[bk]
                if not orows:
                    skip(day_s, dec, f"no option bars for {c['trading_symbol']}")
                    continue
                for rr in RRS:
                    sim, why = simulate(rows, orows, sig, dec, rr)
                    if sim is None:
                        skip(day_s, f"{dec} {rr_label(rr)}", why)
                        continue
                    qty = LOTS * c["lot_size"]
                    eb, xb = sim["entry_bar"], sim["exit_bar"]
                    mfe, mae = excursion(orows, "LONG", sim["entry_px"], eb[0], xb[0])
                    levels = [
                        {"name": "range high", "price": sig["orh"], "from": OR_START, "to": xb[0]},
                        {"name": "range low", "price": sig["orl"], "from": OR_START, "to": xb[0]},
                        {"name": f"index stop ({rr_label(rr)})", "price": sim["stop"], "from": eb[0], "to": xb[0]},
                        {"name": f"index target ({rr_label(rr)})", "price": sim["target"], "from": eb[0], "to": xb[0]},
                    ]
                    trades.append(make_trade(
                        day=day_s, side="LONG", symbol=c["trading_symbol"], entry_time=eb[0],
                        entry_px=sim["entry_px"], exit_time=xb[0], exit_px=sim["exit_px"], qty=qty,
                        exit_reason=sim["reason"], kind="option", capital=sim["entry_px"] * qty,
                        expiry=c["expiry"], option_type=sig["opt"], mfe=mfe, mae=mae, levels=levels,
                        variant={"decision": dec, "rr": rr_label(rr)},
                        tags={"direction": sig["direction"]},
                        note=f"spot {sig['spot']:.2f} at {dec}, range {sig['orl']:.2f}-{sig['orh']:.2f}, "
                             f"slope {sig['slope']:.4f}, {sig['move']} move"))
                    option_sessions.setdefault(c["trading_symbol"], {})[day_s] = orows

    print(f"\n{len(sessions)} sessions, {len(trades)} trades, {len(skips)} skips")
    for k, v in skip_kinds.most_common():
        print(f"  {v:5d} x {k}")
    limits = [
        "ASSUMED: window = 2026-01-01 through the current IST date unless --from/--to given.",
        "ASSUMED: 'close at 11:30' = the candle stamped 11:30 (complete at 11:31); trade placed in the 11:31 bar (rule 2).",
        "ASSUMED: an ATM NIFTY option is bought (strike step read from the live chain), expiry = nearest at least 1 day "
        "after the trade day, 1 lot; costs = standard option schedule.",
        "Rule 1: fills at the option bar's HIGH (buy) / LOW (sell) - the prompt's 'filled exactly at that level' is not used.",
        "Rules 2/3: stop/target are index levels (0.1% of spot, R x that); a touch is a signal, the option is sold in the "
        "next 1-minute bar; both touched in one bar -> stop; time exit fills in the 15:00 bar itself.",
        "Stop/target scanning starts with the 11:31 index bar, which is also the entry bar.",
        "Capital = option premium x quantity (bought option).",
        "In-sample: 8 decision times x 6 R values are compared on the same window; the best cell is mostly noise. "
        "The six R values reuse the same entries, so they are not independent samples.",
        "No custom indicator group-bys were requested; only 'direction' is added.",
        f"Skipped: {len(skips)} (day, decision, R) items; see console list.",
    ]
    meta = {
        "title": "Opening Range Reversal v1",
        "subtitle": "Fade a one-way move that ends outside the 09:15-09:19 range - buy CE after a fall, PE after a rise",
        "instrument": "NIFTY 50 index signal, ATM NIFTY option traded",
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": info["lot_size"],
        "fill_rule": "Buys fill at the bar's high, sells at the bar's low; signals act in the next 1-minute bar",
        "cost_model": "Upstox option schedule (brokerage, STT, exchange, SEBI, stamp, GST)",
        "params": {"decision times": ", ".join(DECISIONS), "R multiples": ", ".join(rr_label(r) for r in RRS),
                   "stop": "0.1% of spot (index)", "time exit": TIME_EXIT, "min window candles": MIN_WINDOW,
                   "lots": LOTS},
        "rule_steps": [
            "Opening range = high/low of the 1-minute candles 09:15-09:19.",
            "At the decision time take the close of that 1-minute candle as the spot; the trade goes in the next 1-minute bar.",
            "Window = 1-minute candles 09:20 to the decision candle; need at least 20, else skip.",
            "Fit a straight line through the window's closes: slope down and last close < first = down move; slope up and last > first = up move; otherwise skip.",
            "Spot must be outside the range (strictly). Touching an edge is not breaking it.",
            "Below the range low: the high edge must never have been exceeded and the move must be down -> buy ATM CE.",
            "Above the range high: the low edge must never have been undercut and the move must be up -> buy ATM PE.",
            "Skip if both edges broke, direction is unclear, or the surviving edge and the move disagree.",
            "Stop = 0.1% of spot against the trade; target = R x stop distance (R = 2, 3, 3.5, 4, 4.5, 5), on the index.",
            "From the candle after the decision candle, the first index touch of stop or target exits in the next 1-minute option bar; both in one bar = stop.",
            "Otherwise exit at 15:00. One trade per day per (decision time, R); no re-entry.",
            "Every decision time (11:00, 11:10, 11:15, 11:20, 11:30, 11:40, 11:45, 12:00) is an independent set of trades.",
        ],
        "limits": limits,
        "coverage": cov,
    }
    groups = [{"name": "Direction", "keys": ["direction"]}] if trades else []
    payload = build_payload(meta, trades, sessions, option_sessions, groups)
    path = write_report(payload, SLUG)
    print(console_summary(trades))
    print(path)


def main() -> None:
    today = datetime.now(IST).date()
    yday = today - timedelta(days=1)
    ap = argparse.ArgumentParser(description="Opening Range Reversal v1")
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat())
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    a = ap.parse_args()
    asyncio.run(main_async(date.fromisoformat(a.frm), date.fromisoformat(a.to)))


if __name__ == "__main__":
    main()
