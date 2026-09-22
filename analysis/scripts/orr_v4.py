"""Opening Range Reversal - v4  (report name: orr_v4)

STRATEGY PROMPT (verbatim)
--------------------------
v4 ORR
### v4 - v2's entry, a completely new exit
Step 1 - The opening range is the first five 1-minute candles, 09:15 to 09:19: the range high is the
  highest high of those five and the range low is the lowest low.
Step 2 - The decision time is 11:30. Take NIFTY's 1-minute close at exactly that minute and call it the spot.
Step 3 - Look at every 1-minute candle from 09:20 to 11:30 - I need at least 20 of them, otherwise skip the day.
Step 4 - That window must be a clean one-way move: fit a straight line through its closes, and the line must
  slope down with the last close below the first (a down move) or slope up with the last close above the first
  (an up move); a flat line is not a trend.
Step 5 - If every candle stayed at or below the range high and the move is down, buy a CE; otherwise, if every
  candle stayed at or above the range low and the move is up, buy a PE. Touching a level is not breaking it,
  and where price sits at 11:30 does not matter.
Step 6 - Work out the average true range of the last 14 one-minute candles before the entry. That is the unit
  the disaster stop is measured in.
Step 7 - From the minute after 11:30 there are four ways out, checked on every candle in the order below.
Step 8 - The disaster stop comes first: if spot has travelled 15 of those average true ranges against the
  trade, get out at that level.
Step 9 - The premium stop comes second: if the option's 1-minute close is 65% or less of what I paid - down
  35% - get out at that price.
Step 10 - The trail comes third. Once the option's 1-minute close reaches 1.15 times what I paid, the trail is
  armed. From then on, track the highest 1-minute close the option has made and get out on the first close
  that is 10% or more below that running high. Before it is armed the trail does nothing.
Step 11 - On expiry day, square off at 13:30 instead.
Step 12 - On any other day, square off whatever is still open at 15:00. One trade per day, no re-entry.
Step 13 - Run the whole thing separately at 11:00, 11:10, 11:15, 11:20, 11:40, 11:45 and 12:00 as well, each
  its own independent set of trades.

RUN.md STEP 1 CHECKLIST (no user available; gaps filled with defaults / simplest reading = ASSUMED)
  1 Underlying         clear    NIFTY 50 index, 1-minute candles.
  2 Window             ASSUMED  2026-01-01 through the current IST date (--from / --to override).
  3 Signal timeframe   clear    1m.
  4 Signal rule        clear*   ASSUMED details: "every candle stayed at or below the range high" is tested on
                                candle HIGHS, "at or above the range low" on candle LOWS. Trend line = ordinary
                                least squares of the closes against 0,1,2,... The window is 09:20..decision
                                candle inclusive.
  5 Decision time      clear    11:30 plus 11:00, 11:10, 11:15, 11:20, 11:40, 11:45, 12:00 (variant "decision").
                                The decision candle is the 1-minute candle STARTING at that time.
  6 Direction          clear    down move -> buy CE, up move -> buy PE (a reversal). Always LONG the option.
  7 Traded instrument  clear    NIFTY weekly option, bought.
  8 Option specifics   ASSUMED  strike = ATM at the decision-candle close (step read from Upstox); 1 lot;
                                expiry = nearest at least 1 day after the trade day (RUN.md default).
                                "Expiry day" (Step 11) = a day on which a NIFTY expiry falls (from Upstox's
                                expiry calendar); the option held is then the NEXT expiry, so rule 10 holds.
  9 Entry              clear    signal candle -> next 1-minute option bar, at that bar's HIGH (rules 1, 2).
 10 Exit               clear*   ASSUMED: "paid" = the entry fill price; disaster level = spot at the decision
                                candle close -/+ 15 x ATR (CE: below, PE: above); ATR = simple mean of the true
                                range of the 14 one-minute candles ending at the decision candle. Checks start
                                with the entry bar's own (completed) candle. Trail: the arming candle's close
                                becomes the first running high. Order per candle: disaster, premium, trail.
 11 Holding period     clear    intraday; time exit 15:00 (13:30 on expiry day), filled in that bar.
 12 Costs              ASSUMED  standard option schedule (option_costs).
 13 Position rules     clear    one trade per day per variant, no re-entry.
 14 Missing data       ASSUMED  skip and list: incomplete session, missing decision candle, missing contract,
                                any missing option 1m bar between entry and the exit.
 15 Filters            clear    decision time (8 values) x side (LONG only) = 18 combinations.
 16 Custom group-bys   ASSUMED  "direction" (down move -> CE / up move -> PE) and "day type" (expiry day or not),
                                both known at the decision candle.
 17 Script name        orr_v4

RULES TO LIVE BY that override the prompt: see meta["limits"] and the run notes.
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: F401,F403,E402

REPORT_NAME = "orr_v4"
DECISIONS = ["11:00", "11:10", "11:15", "11:20", "11:30", "11:40", "11:45", "12:00"]
OR_START, OR_END = "09:15", "09:19"         # opening range candles (start times)
WINDOW_START = "09:20"
MIN_WINDOW = 20
ATR_N = 14
ATR_MULT = 15.0
PREM_STOP = 0.65
TRAIL_ARM = 1.15
TRAIL_GIVE = 0.10
SQUARE_OFF = "15:00"
SQUARE_OFF_EXPIRY = "13:30"
FULL_SESSION_ROWS = 375
LOTS = 1
SESSION_TIMES = [f"{m // 60:02d}:{m % 60:02d}" for m in range(9 * 60 + 15, 15 * 60 + 30)]


def add_minutes(hhmm: str, n: int) -> str:
    m = hhmm_minutes(hhmm) + n
    return f"{m // 60:02d}:{m % 60:02d}"


# ---------------------------------------------------------------------------
# signal - pure, completed candles only (index = the decision candle)
# ---------------------------------------------------------------------------
def signal(rows: list[list], decision: str) -> tuple[dict | None, str]:
    """(signal | None, reason).  `rows` is one full 1-minute spot session."""
    idx = {r[0]: i for i, r in enumerate(rows)}
    if decision not in idx:
        return None, f"no decision candle {decision}"
    orr = [r for r in rows if OR_START <= r[0] <= OR_END]
    if len(orr) < 5:
        return None, "opening range incomplete"
    or_hi, or_lo = max(r[2] for r in orr), min(r[3] for r in orr)
    win = [r for r in rows if WINDOW_START <= r[0] <= decision]
    if len(win) < MIN_WINDOW:
        return None, f"only {len(win)} candles 09:20-{decision} (< {MIN_WINDOW})"
    closes = [r[4] for r in win]
    n = len(closes)
    xm, ym = (n - 1) / 2.0, sum(closes) / n
    sxx = sum((i - xm) ** 2 for i in range(n))
    slope = sum((i - xm) * (c - ym) for i, c in enumerate(closes)) / sxx
    if slope < 0 and closes[-1] < closes[0]:
        move = "down"
    elif slope > 0 and closes[-1] > closes[0]:
        move = "up"
    else:
        return None, f"no clean trend (slope {slope:.4f}, first {closes[0]}, last {closes[-1]})"
    if move == "down" and max(r[2] for r in win) <= or_hi:
        opt_type = "CE"
    elif move == "up" and min(r[3] for r in win) >= or_lo:
        opt_type = "PE"
    else:
        return None, f"{move} move but the opening range was broken"
    i = idx[decision]
    if i < ATR_N:
        return None, "not enough candles for ATR"
    tr = [max(rows[j][2] - rows[j][3], abs(rows[j][2] - rows[j - 1][4]), abs(rows[j][3] - rows[j - 1][4]))
          for j in range(i - ATR_N + 1, i + 1)]
    return {"option_type": opt_type, "move": move, "spot": rows[i][4], "atr": sum(tr) / ATR_N,
            "or_hi": or_hi, "or_lo": or_lo, "slope": slope}, ""


# ---------------------------------------------------------------------------
# simulate - pure: bars -> exit
# ---------------------------------------------------------------------------
def simulate(opt: list[list], spot: list[list], decision: str, opt_type: str, spot_ref: float,
             atr_v: float, force_key: str) -> dict:
    """Entry: next 1m option bar after the decision candle, at its HIGH (rules 1-2).  Then, on every
    completed 1m candle from the entry bar on: disaster stop (spot), premium stop, trail.  A trigger is
    a signal: the exit is the NEXT 1m option bar at its LOW (rules 1-3).  The scheduled time exit fills
    in its own bar.  Returns {"skip": reason} or the pieces of the trade."""
    by_o = {r[0]: r for r in opt}
    by_s = {r[0]: r for r in spot}
    entry = bar_after_candle(opt, decision, 1, strict=True)
    if entry is None:
        return {"skip": f"no option bar at {candle_done_at(decision, 1)} (entry)"}
    paid = worst_fills("LONG", entry, entry)[0]                       # buy at the bar's high
    if paid <= 0:
        return {"skip": "invalid entry price"}
    d_level = spot_ref - ATR_MULT * atr_v if opt_type == "CE" else spot_ref + ATR_MULT * atr_v
    armed, run_high = False, None
    k = entry[0]
    while k <= force_key:
        ob, sb = by_o.get(k), by_s.get(k)
        if ob is None:
            return {"skip": f"missing option bar {k} between entry and exit"}
        if k == force_key:
            return {"entry": entry, "paid": paid, "exit": ob, "reason": "time exit", "trigger": None,
                    "d_level": d_level}
        why = None
        if sb is not None and ((opt_type == "CE" and sb[3] <= d_level) or (opt_type == "PE" and sb[2] >= d_level)):
            why = "disaster stop"
        elif ob[4] <= PREM_STOP * paid:
            why = "premium stop"
        else:
            if not armed and ob[4] >= TRAIL_ARM * paid:
                armed = True
            if armed:
                run_high = ob[4] if run_high is None else max(run_high, ob[4])
                if ob[4] <= (1 - TRAIL_GIVE) * run_high:
                    why = "trail"
        if why:
            nk = add_minutes(k, 1)
            nb = by_o.get(nk)
            if nb is None:
                return {"skip": f"{why} at {k} but no option bar at {nk} to exit in"}
            return {"entry": entry, "paid": paid, "exit": nb, "reason": why, "trigger": ob, "d_level": d_level}
        k = add_minutes(k, 1)
    return {"skip": "no exit found"}


# ---------------------------------------------------------------------------
# fetch + orchestrate
# ---------------------------------------------------------------------------
async def run(frm: date, to: date):
    trades: list[dict] = []
    skips: list[str] = []
    opt_sessions: dict[str, dict[str, list]] = {}
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        step = info["strike_step"]
        cal = await up.expiry_calendar(key, frm, to)
        cs = await up.candles(key, "1m", frm, to)
        sessions = sessions_from(cs)
        cov = coverage(sessions, frm, to, FULL_SESSION_ROWS)
        for g in cov["weekday_gaps"]:
            print(f"SKIP {g}: no NIFTY candles (holiday or feed gap)")
        contracts: dict = {}
        opt_cache: dict = {}
        good_days: dict[str, list] = {}
        for day, rows in sessions.items():
            if [r[0] for r in rows] != SESSION_TIMES:
                msg = f"SKIP {day}: incomplete/irregular session ({len(rows)} bars, need {FULL_SESSION_ROWS})"
                print(msg); skips.append(msg)
                continue
            good_days[day] = rows
        expiry_days = {e.isoformat() for e in cal}
        for day, rows in good_days.items():
            d = date.fromisoformat(day)
            is_exp = day in expiry_days
            force = SQUARE_OFF_EXPIRY if is_exp else SQUARE_OFF
            for dec in DECISIONS:
                tag = f"{day} @{dec}"
                sig, why = signal(rows, dec)
                if sig is None:
                    print(f"SKIP {tag}: {why}"); skips.append(f"{tag}: {why}")
                    continue
                exp = next_expiry(cal, d, 1)
                if exp is None:
                    print(f"SKIP {tag}: no expiry at least 1 day after"); continue
                strike = atm_strike(sig["spot"], step)
                ck = (exp, strike, sig["option_type"])
                if ck not in contracts:
                    contracts[ck] = await up.resolve_option(key, exp, strike, sig["option_type"])
                c = contracts[ck]
                if c is None:
                    print(f"SKIP {tag}: no contract {exp} {strike} {sig['option_type']}"); continue
                ok = (c["instrument_key"], day)
                if ok not in opt_cache:
                    opt_cache[ok] = await up.option_candles(c, d)
                orows = opt_cache[ok]
                if not orows:
                    print(f"SKIP {tag}: no option bars for {c['trading_symbol']}"); continue
                res = simulate(orows, rows, dec, sig["option_type"], sig["spot"], sig["atr"], force)
                if "skip" in res:
                    print(f"SKIP {tag}: {res['skip']} ({c['trading_symbol']})"); skips.append(f"{tag}: {res['skip']}")
                    continue
                en, ex, paid = res["entry"], res["exit"], res["paid"]
                epx, xpx = worst_fills("LONG", en, ex)
                qty = LOTS * c["lot_size"]
                mfe, mae = excursion(orows, "LONG", epx, en[0], ex[0])
                levels = [{"name": "range high", "price": sig["or_hi"], "from": OR_START, "to": dec},
                          {"name": "range low", "price": sig["or_lo"], "from": OR_START, "to": dec},
                          {"name": "disaster stop (spot)", "price": res["d_level"], "from": en[0], "to": ex[0]}]
                trades.append(make_trade(
                    day=day, side="LONG", symbol=c["trading_symbol"], entry_time=en[0], entry_px=epx,
                    exit_time=ex[0], exit_px=xpx, qty=qty, exit_reason=res["reason"], kind="option",
                    capital=epx * qty, stop=PREM_STOP * paid, target=None, mfe=mfe, mae=mae,
                    levels=levels, expiry=c["expiry"], option_type=sig["option_type"],
                    variant={"decision": dec},
                    tags={"direction": f"{sig['move']} move -> {sig['option_type']}",
                          "day type": "expiry day" if is_exp else "normal day"},
                    note=f"signal candle {dec}, ATR14 {sig['atr']:.2f}, spot {sig['spot']}"))
                opt_sessions.setdefault(c["trading_symbol"], {})[day] = orows
        return trades, skips, sessions, opt_sessions, cov, info


def main() -> None:
    today = datetime.now(IST)
    yesterday = today.date() - timedelta(days=1)
    ap = argparse.ArgumentParser(description="Opening Range Reversal v4")
    ap.add_argument("--from", dest="frm", type=date.fromisoformat, default=START_DATE)
    ap.add_argument("--to", dest="to", type=date.fromisoformat, default=END_DATE)
    a = ap.parse_args()
    to = a.to or yesterday
    if to >= today.date() and (today.hour, today.minute) < (15, 45):      # rule 7: today only when over
        to = yesterday
    frm = a.frm or (to - timedelta(days=182))
    print(f"ORR v4  {frm} -> {to}")

    trades, skips, sessions, opt_sessions, cov, info = asyncio.run(run(frm, to))

    meta = {
        "title": "Opening Range Reversal v4",
        "subtitle": f"NIFTY, buy ATM CE/PE on a clean one-way morning move that never broke the opening range; "
                    f"premium stop, spot disaster stop, trailing stop; {frm} to {to}",
        "instrument": "NIFTY 50 weekly options (bought, ATM)", "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": info["lot_size"],
        "fill_rule": "Every buy at the bar's high, every sell at the bar's low; a signal candle is acted on in the "
                     "next 1-minute bar; stop/trail triggers exit in the next 1-minute bar.",
        "cost_model": "Standard option schedule (Upstox flat Rs 20/order, STT, exchange, SEBI, stamp, GST).",
        "params": {"decision times": ", ".join(DECISIONS), "opening range": "09:15-09:19", "min window candles": MIN_WINDOW,
                   "ATR": f"{ATR_N} x 1m", "disaster stop": f"{ATR_MULT:g} ATR on spot",
                   "premium stop": f"close <= {PREM_STOP:.0%} of paid", "trail arm": f"close >= {TRAIL_ARM}x paid",
                   "trail give-back": f"{TRAIL_GIVE:.0%} of running high close", "square-off": SQUARE_OFF,
                   "square-off expiry day": SQUARE_OFF_EXPIRY, "lots": LOTS, "strike": "ATM"},
        "rule_steps": [
            "Opening range = highest high / lowest low of the 1-minute candles 09:15-09:19.",
            "For each decision time (11:00, 11:10, 11:15, 11:20, 11:30, 11:40, 11:45, 12:00) take the 1-minute candles 09:20 to the decision candle; fewer than 20 -> skip the day.",
            "Fit a least-squares line to their closes; slope down and last close below first = down move, slope up and last close above first = up move, else skip.",
            "Down move and no candle high above the range high -> buy ATM CE; up move and no candle low below the range low -> buy ATM PE; otherwise skip.",
            "Entry: the 1-minute option bar right after the decision candle, filled at its high.",
            "ATR = mean true range of the 14 one-minute candles ending at the decision candle.",
            "On every completed candle from the entry bar: (1) disaster stop - spot has moved 15 ATR against the trade from the decision close; (2) premium stop - option close <= 65% of the price paid; (3) trail - once an option close >= 1.15x paid, exit on the first close 10% or more below the highest close since; the exit is the next 1-minute option bar, filled at its low.",
            "Time exit: 15:00 (13:30 on an expiry day), filled in that bar at its low. One trade per day per decision time, no re-entry.",
        ],
        "limits": [
            "ASSUMED: window = 2026-01-01 through the current IST date (no window in the prompt).",
            "ASSUMED: strike = ATM at the decision-candle close; 1 lot; expiry = nearest at least 1 day after the trade day; on an expiry day the next expiry is held (rule 10).",
            "ASSUMED: range tests use candle highs/lows; trend line = OLS on closes; ATR = simple mean of 14 true ranges ending at the decision candle; 'paid' = the entry fill price (bar high); disaster level measured from the decision-candle close.",
            "ASSUMED: stop/trail checks begin with the entry bar's own completed candle; the trail's first running high is the arming candle's close.",
            "ASSUMED: a missing option minute between entry and exit skips the trade (no gap filling); trades are always intraday.",
            "Rules override the prompt: entry is the next 1-minute bar's high (not the signal close); stops/trail exit in the next bar's low, not 'at that level/price'.",
            "The eight decision times are compared side by side and the prompt's parameters came from studying this same kind of data: results are in-sample.",
            "Costs use the option schedule in force from 2024-10-01; capital = premium x qty. Options are bought, so no margin estimate is used.",
            f"Skipped day/decision pairs: {len(skips)} (listed in the console).",
        ],
        "coverage": cov,
    }
    groups = [{"name": "Direction", "keys": ["direction"]}, {"name": "Day type", "keys": ["day type"]}]
    payload = build_payload(meta, trades, sessions, opt_sessions, groups)
    path = write_report(payload, REPORT_NAME)
    print(console_summary(trades))
    print(path)


if __name__ == "__main__":
    main()
