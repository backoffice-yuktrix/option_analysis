"""Opening Range Reversal - v2  (slug: orr_v2)

STRATEGY PROMPT (verbatim)
--------------------------
v2 ORR - the edge that survived, not where price sits
Step 1 - The opening range is the first five 1-minute candles, 09:15 to 09:19: the range high is the highest high of those five and the range low is the lowest low.
Step 2 - The decision time is 11:30. Take NIFTY's 1-minute close at exactly that minute and call it the spot.
Step 3 - Look at every 1-minute candle from 09:20 to 11:30 - I need at least 20 of them, otherwise skip the day.
Step 4 - That window must be a clean one-way move: fit a straight line through its closes, and the line must slope down with the last close below the first (a down move) or slope up with the last close above the first (an up move); a flat line is not a trend.
Step 5 - If every candle in that window stayed at or below the range high and the move is down, buy a CE - I am fading the fall and expecting the bounce.
Step 6 - Otherwise, if every candle stayed at or above the range low and the move is up, buy a PE - I am fading the rise.
Step 7 - Touching a level does not count as breaking it: a high exactly equal to the range high still counts as having stayed below it, and a low equal to the range low still counts as having stayed above.
Step 8 - Where the price sits at 11:30 does not matter at all - it can still be inside the opening range and I will still take the trade.
Step 9 - A day that never left the range passes both tests, so check the CE case first and let the direction of the move decide the side.
Step 10 - Skip the day only when price broke both edges, when the window has no clear direction, or when the edge that survived and the direction of the move point opposite ways.
Step 11 - The stop is 0.1% of the entry spot placed against the trade, and the target is that stop distance multiplied by 2; also score the same entries at 3, 3.5, 4, 4.5 and 5.
Step 12 - From the minute after 11:30, check each 1-minute index candle in turn and close the trade the moment either level is touched, filled exactly at that level; if one candle touches both, count it as the stop.
Step 13 - If neither level is touched by 15:00, close the trade there. One trade per day, no re-entry.
Step 14 - Run the whole thing separately at 11:00, 11:10, 11:15, 11:20, 11:40, 11:45 and 12:00 as well, each its own independent set of trades.

CHECKLIST (RUN.md Step 1)
-------------------------
 1 Underlying        clear    NIFTY 50 index, 1-minute candles.
 2 Window            ASSUMED  last 6 months ending yesterday (default); --from / --to override.
 3 Signal timeframe  clear    1m.
 4 Signal rule       clear    range = 09:15-09:19 high/low; window = 09:20..T; least-squares slope of closes;
                              touching is not breaking.  (Which candle is "the close at 11:30" -> ASSUMED below.)
 5 Decision time     clear    8 times: 11:00 11:10 11:15 11:20 11:30 11:40 11:45 12:00 (variant `time`).
 6 Direction         clear    down move -> buy CE, up move -> buy PE.
 7 Traded instrument ASSUMED  NIFTY option (prompt says "buy a CE/PE" but no instrument line).
 8 Option specifics  ASSUMED  buy; ATM strike from the spot at the signal candle (strike step read from
                              Upstox); 1 lot (qty = lot size of the resolved contract); expiry = nearest at
                              least 1 day after the exit day (RUN.md default; rule 10).
 9 Entry             clear    the signal only.
10 Exit              clear    index-level stop 0.1% of spot against the trade; target = rr x stop distance,
                              rr in {2, 3, 3.5, 4, 4.5, 5} (variant `rr`); time exit 15:00; stop first on a tie.
11 Holding           ASSUMED  intraday (time exit 15:00 is in the prompt).
12 Costs             ASSUMED  standard option schedule (option_costs).
13 Position rules    clear    one trade per day per (time, rr) set, no re-entry.  The 8 decision times and 6
                              rr values are independent sets, so on one day up to 48 trades exist - one per set.
14 Missing data      ASSUMED  skip the day / trade and print why (default).
15 Filters           clear    side, time (8), rr (6) -> 3*9*7 = 189 combinations (< MAX_VIEWS 400).
16 Group-bys         ASSUMED  two custom groups, not requested: direction and "edge that survived".
17 Script name       orr_v2.

ASSUMPTIONS (also in meta["limits"])
------------------------------------
A1 "NIFTY's 1-minute close at exactly that minute" = the candle STARTING at the decision time T (its close is
   known at T+1). It is the signal candle; the trade is placed in the 1m bar starting T+1 (rule 2).
A2 The window 09:20..T INCLUDES the candle starting at T.  Every 1m candle in it must be present; a missing
   candle skips the day.  ">= 20 candles" is satisfied by every decision time here (>= 101) but is still checked.
A3 Stop and target are INDEX levels (spot = close of the signal candle), not option premiums.
   CE (index long): stop = spot - 0.1% x spot, target = spot + rr x that distance.  PE: mirrored.
A4 The index scan starts with the 1m bar T+1 (the "minute after"), which is also the option entry bar; a touch
   there is a signal that completes at T+2 and is acted on in the T+2 bar.
A5 Instrument, ATM strike, 1 lot, expiry rule, intraday, costs: see checklist.  Capital = premium x qty.
A6 A session must have exactly 375 valid, unique 1m bars; otherwise the day is skipped.  The option bars for
   the entry bar and the exit bar must exist and be valid; otherwise that trade is skipped.
A7 Lines of the same day across decision times / rr are separate independent sets, not one position.

CONFLICTS with the Rules to Live By (rules win)
-----------------------------------------------
C1 Step 12 "filled exactly at that level": rule 3 makes a touched stop/target a signal, and rule 1 fills the
   option exit at the LOW of the bar after the touch (a bought option is sold at the bar low).
C2 Entry: the prompt does not price the entry; rule 1/2 -> option entry at the HIGH of the T+1 bar.
C3 Step 13 "close there at 15:00": kept, filled in the 15:00 option bar itself at its LOW (rule 1, rule 3).
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *

import argparse

DECISION_TIMES = ["11:00", "11:10", "11:15", "11:20", "11:30", "11:40", "11:45", "12:00"]
RR_LADDER = [2, 3, 3.5, 4, 4.5, 5]
STOP_PCT = 0.001
FORCE_EXIT = "15:00"
RANGE_END = "09:19"
LOTS = 1


def valid_bar(r: list) -> bool:
    o, h, l, c = r[1:5]
    return min(o, h, l, c) > 0 and h >= max(o, c, l) and l <= min(o, c, h)


def session_ok(rows: list[list]) -> str | None:
    """None when the session is complete and clean, else the reason."""
    if len(rows) != 375:
        return f"short/odd session ({len(rows)} bars, need 375)"
    if len({r[0] for r in rows}) != len(rows):
        return "duplicate candles"
    if rows[0][0] != "09:15" or rows[-1][0] != "15:29":
        return f"session runs {rows[0][0]}-{rows[-1][0]}"
    bad = [r[0] for r in rows if not valid_bar(r)]
    if bad:
        return f"invalid candle(s) e.g. {bad[0]}"
    return None


# ---------------------------------------------------------------------------
# signal - pure; reads candles up to and including the signal candle (starts at T)
# ---------------------------------------------------------------------------
def signal(rows: list[list], T: str) -> dict:
    """Returns {"skip": reason} or {"side": "CE"|"PE", "spot", "rh", "rl", "slope", "edge", "n"}."""
    by = {r[0]: r for r in rows}
    rng = [r for r in rows if "09:15" <= r[0] <= RANGE_END]
    if len(rng) != 5:
        return {"skip": "opening range candles missing"}
    rh, rl = max(r[2] for r in rng), min(r[3] for r in rng)
    t0, t1 = hhmm_minutes("09:20"), hhmm_minutes(T)
    win = []
    for m in range(t0, t1 + 1):
        k = f"{m // 60:02d}:{m % 60:02d}"
        if k not in by:
            return {"skip": f"window candle {k} missing"}
        win.append(by[k])
    if len(win) < 20:
        return {"skip": f"only {len(win)} window candles (< 20)"}
    closes = [r[4] for r in win]
    n = len(closes)
    xm, ym = (n - 1) / 2, sum(closes) / n
    slope = sum((i - xm) * (c - ym) for i, c in enumerate(closes)) / sum((i - xm) ** 2 for i in range(n))
    if slope < 0 and closes[-1] < closes[0]:
        direction = "down"
    elif slope > 0 and closes[-1] > closes[0]:
        direction = "up"
    else:
        return {"skip": f"no clear direction (slope {slope:.4f}, first {closes[0]}, last {closes[-1]})"}
    below = all(r[2] <= rh for r in win)          # never broke the range high (touch is fine)
    above = all(r[3] >= rl for r in win)          # never broke the range low
    if not below and not above:
        return {"skip": "price broke both edges"}
    edge = "never left range" if below and above else ("stayed below range high" if below else "stayed above range low")
    if below and direction == "down":
        side = "CE"
    elif above and direction == "up":
        side = "PE"
    else:
        return {"skip": f"surviving edge ({edge}) contradicts {direction} move"}
    return {"side": side, "spot": win[-1][4], "rh": rh, "rl": rl, "slope": slope, "edge": edge,
            "direction": direction, "n": n}


# ---------------------------------------------------------------------------
# simulate - pure: index bars + option bars -> one trade (or a skip reason)
# ---------------------------------------------------------------------------
def simulate(day: str, T: str, sig: dict, rr: float, idx_rows: list[list], opt_rows: list[list],
             contract: dict) -> tuple[dict | None, str]:
    spot = sig["spot"]
    dist = spot * STOP_PCT
    idx_side = "LONG" if sig["side"] == "CE" else "SHORT"           # index direction implied by the option
    sgn = 1 if idx_side == "LONG" else -1
    stop_lvl, tgt_lvl = spot - sgn * dist, spot + sgn * dist * rr
    res = scan_exit(idx_rows, idx_side, T, stop=stop_lvl, target=tgt_lvl, force_key=FORCE_EXIT)
    if res["bar"] is None:
        return None, f"exit not resolvable ({res['reason']})"
    ob = {r[0]: r for r in opt_rows}
    eb = bar_after_candle(opt_rows, T, 1)
    if eb is None or not valid_bar(eb):
        return None, "option entry bar missing/invalid"
    xb = ob.get(res["bar"][0])
    if xb is None or not valid_bar(xb):
        return None, f"option exit bar {res['bar'][0]} missing/invalid"
    entry_px, exit_px = worst_fills("LONG", eb, xb)
    qty = LOTS * contract["lot_size"]
    if qty <= 0:
        return None, "contract has no lot size"
    mfe, mae = excursion(opt_rows, "LONG", entry_px, eb[0], xb[0])
    up = sig["side"] == "CE"
    tags = {"direction": f"{sig['direction']} move -> buy {sig['side']}", "edge": sig["edge"]}
    levels = [{"name": "Range high", "price": sig["rh"], "from": "09:15", "to": T},
              {"name": "Range low", "price": sig["rl"], "from": "09:15", "to": T},
              {"name": "Index stop", "price": stop_lvl, "from": eb[0], "to": xb[0]},
              {"name": f"Index target {rr}R", "price": tgt_lvl, "from": eb[0], "to": xb[0]},
              {"name": "Spot at signal", "price": spot, "from": T, "to": eb[0]}]
    t = make_trade(day=day, side="LONG", symbol=contract["trading_symbol"], entry_time=eb[0], entry_px=entry_px,
                   exit_time=xb[0], exit_px=exit_px, qty=qty, exit_reason=res["reason"], kind="option",
                   capital=entry_px * qty, mfe=mfe, mae=mae, expiry=contract["expiry"],
                   option_type=sig["side"], variant={"time": T, "rr": f"{rr:g}"}, tags=tags, levels=levels,
                   note=f"signal candle {T}, spot {spot:.2f}, slope {sig['slope']:.4f}, "
                        f"stop/target are index levels ({'long' if up else 'short'} index)")
    return t, ""


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
async def run(frm: date, to: date):
    limits = [
        "ASSUMED: 'close at exactly T' = the 1m candle starting at T (signal candle); the trade fills in the T+1 bar.",
        "ASSUMED: window 09:20..T includes the candle starting at T; a missing candle skips the day.",
        "ASSUMED: buy an ATM NIFTY option (strike step read from Upstox), 1 lot, expiry = nearest at least 1 day "
        "after the exit day, intraday; standard option costs.",
        "Stop/target are index levels (0.1% of the signal-candle close; target = rr x that distance), not premium levels.",
        "A touched stop/target exits in the NEXT bar at the option's bar LOW (rules 1-3), not 'exactly at that level'; "
        "the entry fills at the T+1 option bar HIGH. Results are therefore worse than the prompt's idealised fills.",
        "The 8 decision times and 6 rr values are independent trade sets: the same day can appear in several of them. "
        "Trades in different sets overlap in time - do not add the sets together.",
        "Capital = premium x qty (bought option).",
        "Variants (8 times x 6 rr) are all shown as filters, none is selected; still, the window is a single "
        "6-month sample so any choice made from it is in-sample.",
    ]
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        step = info["strike_step"]
        if not step:
            raise SystemExit("could not read strike step from Upstox")
        expiries = await up.expiry_calendar(key, frm, to)
        cs = await up.candles(key, "1m", frm, to)
        sessions = sessions_from(cs)
        cov = coverage(sessions, frm, to, 375)
        print(f"NIFTY 1m: {len(sessions)} sessions between {frm} and {to}; strike step {step}; "
              f"{len(expiries)} expiries known")
        trades: list[dict] = []
        opt_sessions: dict[str, dict[str, list]] = {}
        contracts: dict = {}
        opt_cache: dict = {}
        skipped_days = 0
        for d in sorted(sessions):
            day = date.fromisoformat(d)
            if not (frm <= day <= to):
                continue
            rows = sessions[d]
            bad = session_ok(rows)
            if bad:
                print(f"SKIP {d}: {bad}")
                skipped_days += 1
                continue
            for T in DECISION_TIMES:
                sig = signal(rows, T)
                if "skip" in sig:
                    print(f"SKIP {d} {T}: {sig['skip']}")
                    continue
                exp = next_expiry(expiries, day, 1)
                if exp is None:
                    print(f"SKIP {d} {T}: no expiry at least 1 day after the day")
                    continue
                strike = atm_strike(sig["spot"], step)
                ck = (exp, strike, sig["side"])
                if ck not in contracts:
                    contracts[ck] = await up.resolve_option(key, exp, strike, sig["side"])
                c = contracts[ck]
                if c is None:
                    print(f"SKIP {d} {T}: no contract {exp} {strike:g} {sig['side']}")
                    continue
                ok = (c["instrument_key"], d)
                if ok not in opt_cache:
                    try:
                        opt_cache[ok] = await up.option_candles(c, day)
                    except RuntimeError as exc:
                        print(f"  ! option candles failed for {c['trading_symbol']} {d}: {exc}")
                        opt_cache[ok] = []
                orows = opt_cache[ok]
                if not orows:
                    print(f"SKIP {d} {T}: no option bars for {c['trading_symbol']}")
                    continue
                opt_sessions.setdefault(c["trading_symbol"], {})[d] = orows
                for rr in RR_LADDER:
                    t, why = simulate(d, T, sig, rr, rows, orows, c)
                    if t is None:
                        print(f"SKIP {d} {T} rr={rr:g}: {why}")
                    else:
                        trades.append(t)
    print(f"{len(trades)} trades; {skipped_days} sessions skipped for data quality")
    if cov["weekday_gaps"]:
        print(f"weekdays without candles (holidays/feed gaps): {cov['weekday_gaps']}")
    lot = trades[-1]["qty"] if trades else info["lot_size"]
    meta = {
        "title": "Opening Range Reversal v2",
        "subtitle": "Fade a clean one-way morning move that never broke the opposite edge of the 09:15-09:19 range",
        "instrument": "NIFTY 50 options (ATM), signal from 1m index candles",
        "from": frm.isoformat(), "to": to.isoformat(), "lot_size": lot,
        "fill_rule": "Every BUY fills at the bar's HIGH, every SELL at its LOW; signal candle -> next 1m bar; "
                     "stop/target touch -> exit in the next bar; 15:00 time exit fills in its own bar.",
        "cost_model": "Standard option schedule (Upstox flat F&O brokerage, STT, exchange, SEBI, stamp, GST).",
        "params": {"opening range": "09:15-09:19", "window": "09:20..decision time", "decision times": ", ".join(DECISION_TIMES),
                   "stop": "0.1% of spot (index)", "rr ladder": ", ".join(f"{r:g}" for r in RR_LADDER),
                   "time exit": FORCE_EXIT, "lots": LOTS},
        "rule_steps": [
            "Opening range = highest high / lowest low of the 1m candles 09:15-09:19.",
            "At decision time T take the close of the 1m candle starting at T as the spot (signal candle).",
            "Window = every 1m candle 09:20..T; need at least 20, none missing.",
            "Fit a least-squares line through the window closes: slope down and last close < first = down move; slope up and last > first = up move; otherwise skip.",
            "If no candle's high exceeded the range high (equal is fine) and the move is down: buy a CE (ATM).",
            "Otherwise, if no candle's low fell below the range low and the move is up: buy a PE (ATM).",
            "Skip when both edges broke, the direction is unclear, or the surviving edge contradicts the direction. Price position at T is irrelevant.",
            "Entry: the 1m option bar right after the signal candle, filled at that bar's high.",
            "Index stop = 0.1% of spot against the trade; index target = rr x stop distance (rr 2, 3, 3.5, 4, 4.5, 5).",
            "From the bar after T, a touch of the stop or target on a completed index bar exits in the next bar at the option bar's low; both in one bar = stop.",
            "If neither is touched, exit in the 15:00 bar at its low. One trade per day per (time, rr); no re-entry.",
            "Repeat independently at 11:00, 11:10, 11:15, 11:20, 11:30, 11:40, 11:45, 12:00.",
        ],
        "limits": limits, "coverage": cov,
    }
    groups = [{"name": "Direction", "keys": ["direction"]},
              {"name": "Range edge that survived", "keys": ["edge"]}]
    if not trades:
        print("no trades - no report written")
        return
    payload = build_payload(meta, trades, sessions, opt_sessions, groups)
    path = write_report(payload, "orr_v2")
    print(console_summary(trades))
    print(path)


def main():
    today = datetime.now(IST)
    last_done = today.date() if today.hour * 60 + today.minute > 15 * 60 + 45 else today.date() - timedelta(days=1)
    default_to = today.date() - timedelta(days=1)
    ap = argparse.ArgumentParser(description="Opening Range Reversal v2 backtest")
    ap.add_argument("--from", dest="frm", type=date.fromisoformat, default=None)
    ap.add_argument("--to", dest="to", type=date.fromisoformat, default=default_to)
    a = ap.parse_args()
    to = min(a.to, last_done)                       # rule 7: today only after 15:45
    frm = a.frm or (to - timedelta(days=182))
    if to != a.to:
        print(f"--to capped at {to}: today's session is not used until after 15:45")
    asyncio.run(run(frm, to))


if __name__ == "__main__":
    main()
