"""Opening Range Reversal - v3   (report name: orr_v3)

STRATEGY PROMPT (verbatim)
--------------------------
v3 ORR - the same entry as v2, plus three exhaustion tests (RSI, standard-deviation stretch, candle run);
all three must pass. Target ladder 2,3,4,5,6,8,10. Two more filters exist but are OFF (max opening-range
width; required % beyond the faded edge). Thresholds are hypotheses, not settings.

Step 1  Opening range = first five 1-minute candles 09:15-09:19: range high = highest high, range low = lowest low.
Step 2  Decision time 11:30. NIFTY's 1-minute close at exactly that minute is the spot.
Step 3  Look at every 1-minute candle 09:20..11:30; need at least 20, else skip the day.
Step 4  Fit a straight line through the closes: slope down and last close < first = down move; slope up and
        last close > first = up move; flat is not a trend.
Step 5  If every candle stayed at or below the range high and the move is down -> possible CE; otherwise, if
        every candle stayed at or above the range low and the move is up -> possible PE. Touching is not
        breaking; where price sits at 11:30 does not matter.
Step 6  Exhaustion test: RSI, standard-deviation stretch, candle run; all three must pass, else skip.
Step 7-9  RSI(14) at 11:30 from the last 15 closes of the 09:20..11:30 window only: 14 changes, total gain,
        total loss, each /14, RSI = 100 - 100/(1 + avg gain/avg loss). Plain averages (not Wilder). No falls -> 100.
        Fewer than 15 closes -> 50.
Step 10 RSI <= 40 to buy a CE, >= 60 to buy a PE.
Step 11-12 Mean of every close 09:20..11:30 and population standard deviation (divide by n). The 11:30 close must
        be >= 1.0 SD away from the mean - below for a CE, above for a PE. SD exactly zero -> tiny number.
Step 13 Candle run: at least 1 candle counting back from 11:30 still moving with the move being faded: red
        (close < open) for a CE, green (close > open) for a PE; a flat candle ends the count.
Step 14 Check in order RSI, stretch, run; the first failure is the skip reason.
Step 15 Stop = 0.1% of the entry spot against the trade; target = stop distance x 2; also score 3,4,5,6,8,10.
Step 16 From the minute after 11:30, check each 1-minute index candle; close the moment either level is touched,
        filled exactly at that level; both in one candle -> stop.
Step 17 Neither touched by 15:00 -> close there. One trade per day, no re-entry.
Step 18 Run the whole thing separately at 11:00, 11:10, 11:15, 11:20, 11:40, 11:45 and 12:00 as well; each its
        own independent set of trades.

CHECKLIST (RUN.md Step 1) - ASSUMED items are marked
----------------------------------------------------
 1 Underlying         clear    NIFTY 50 index.
 2 Window             ASSUMED  not stated: 2026-01-01 through the current IST date (--from / --to override).
 3 Signal timeframe   clear    1-minute candles.
 4 Signal rule        clear    all thresholds numeric (RSI 40/60, 1.0 SD, run >= 1, >= 20 candles, 0.1% stop).
 5 Decision time      clear    candle labelled D (09:20..D window). ASSUMED reading: "1-minute close at exactly
                               D" = the candle that STARTS at D, which completes at D+1 (Rule 2/4), so the
                               trade is in the 1-minute bar starting D+1.
 6 Direction mapping  ASSUMED  down move faded -> BUY CE; up move faded -> BUY PE (the prompt says "possible CE /
                               PE" and "buy a CE / a PE" in step 10, so options are bought).
 7 Traded instrument  ASSUMED  NIFTY weekly/monthly option, bought.
 8 Option specifics   ASSUMED  ATM strike (spot at the decision candle's close rounded to the strike step read
                               from Upstox), 1 lot, nearest expiry at least 1 day after the trade day.
 9 Entry              clear    signal only; fill = the option bar's HIGH in the next 1-minute bar.
10 Exit               clear    stop 0.1% and target 0.1% x R:R of the ENTRY SPOT, both measured on the INDEX
                               1-minute candles (ASSUMED: "entry spot" = the decision-candle close, the spot
                               named in step 2); time exit 15:00. Exit fills in the next option 1-minute bar at
                               its LOW (Rules 1 & 3); the 15:00 time exit fills in the 15:00 bar itself.
11 Holding period     clear    intraday.
12 Costs              ASSUMED  standard option schedule (option_costs).
13 Position rules     clear    one trade per day per (decision time, R:R) set; no re-entry.
14 Missing data       ASSUMED  skip and list.
15 Filters            clear    decision = 8 times; rr = 2,3,4,5,6,8,10. (144 filter views < MAX_VIEWS.)
16 Custom group-bys   ASSUMED  none requested; added: RSI bucket, stretch bucket, candle-run bucket, RSI x stretch
                               (all measured on the decision candle, Rule 12).
17 Script name        orr_v3.
Other ASSUMED: the two OFF filters (max range width, % beyond the edge) are off (0) and not implemented; the
option strike step is read once from the live chain and held for the whole window; stop/target are index levels,
so they are shown as chart `levels`, not as option-price stop/target.
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: E402,F401,F403

SLUG = "orr_v3"
DECISIONS = ["11:00", "11:10", "11:15", "11:20", "11:30", "11:40", "11:45", "12:00"]
RR_LADDER = [2, 3, 4, 5, 6, 8, 10]
OR_START, OR_END, WIN_START = "09:15", "09:19", "09:20"
MIN_CANDLES = 20
RSI_N, RSI_CE_MAX, RSI_PE_MIN = 14, 40.0, 60.0
SD_MIN = 1.0
RUN_MIN = 1
STOP_PCT = 0.001
FORCE_EXIT = "15:00"
LOTS = 1


def _minutes(a: str, b: str) -> list:
    out, m = [], hhmm_minutes(a)
    while m <= hhmm_minutes(b):
        out.append(f"{m // 60:02d}:{m % 60:02d}")
        m += 1
    return out


FULL_SESSION = _minutes("09:15", "15:29")          # 375 one-minute bars


# --------------------------------------------------------------------------- signal (pure)
def signal(rows: list, decision: str):
    """rows = one complete 1m session. Returns (dict, None) for a signal or (None, reason)."""
    by = {r[0]: r for r in rows}
    orb = [by.get(t) for t in _minutes(OR_START, OR_END)]
    if None in orb:
        return None, "opening-range candle missing"
    rng_hi, rng_lo = max(r[2] for r in orb), min(r[3] for r in orb)
    win = [by.get(t) for t in _minutes(WIN_START, decision)]
    if None in win:
        return None, "candle missing in the 09:20-decision window"
    if len(win) < MIN_CANDLES:
        return None, f"only {len(win)} candles in window (<{MIN_CANDLES})"
    closes = [r[4] for r in win]
    n = len(closes)
    xm, ym = (n - 1) / 2, sum(closes) / n
    slope = sum((i - xm) * (c - ym) for i, c in enumerate(closes)) / sum((i - xm) ** 2 for i in range(n))
    if slope < 0 and closes[-1] < closes[0]:
        move = "down"
    elif slope > 0 and closes[-1] > closes[0]:
        move = "up"
    else:
        return None, "no clean trend (slope/first-last disagree or flat)"
    if move == "down" and all(r[2] <= rng_hi for r in win):
        opt = "CE"
    elif move == "up" and all(r[3] >= rng_lo for r in win):
        opt = "PE"
    else:
        return None, f"{move} move but the window broke the opposite range edge"
    # exhaustion tests, in the prompt's order
    last15 = closes[-15:]
    if len(last15) < 15:
        rsi_v = 50.0
    else:
        ch = [last15[i] - last15[i - 1] for i in range(1, 15)]
        ag, al = sum(x for x in ch if x > 0) / 14, sum(-x for x in ch if x < 0) / 14
        rsi_v = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    if opt == "CE" and not rsi_v <= RSI_CE_MAX:
        return None, f"RSI {rsi_v:.1f} not <= {RSI_CE_MAX:g} (CE)"
    if opt == "PE" and not rsi_v >= RSI_PE_MIN:
        return None, f"RSI {rsi_v:.1f} not >= {RSI_PE_MIN:g} (PE)"
    mean = sum(closes) / n
    sd = (sum((c - mean) ** 2 for c in closes) / n) ** 0.5 or 1e-9
    z = (closes[-1] - mean) / sd
    if opt == "CE" and not z <= -SD_MIN:
        return None, f"stretch {z:.2f} SD not <= -{SD_MIN:g} (CE)"
    if opt == "PE" and not z >= SD_MIN:
        return None, f"stretch {z:.2f} SD not >= {SD_MIN:g} (PE)"
    run = 0
    for r in reversed(win):
        if (opt == "CE" and r[4] < r[1]) or (opt == "PE" and r[4] > r[1]):
            run += 1
        else:
            break
    if run < RUN_MIN:
        return None, f"candle run {run} < {RUN_MIN}"
    return {"opt": opt, "spot": closes[-1], "rsi": rsi_v, "z": z, "run": run,
            "rng_hi": rng_hi, "rng_lo": rng_lo, "move": move}, None


# --------------------------------------------------------------------------- simulate (pure)
def simulate(idx_rows: list, opt_rows: list, sig: dict, decision: str, rr: int):
    """Returns (dict with entry/exit bars and prices, None) or (None, reason)."""
    entry_i = bar_after_candle(idx_rows, decision, 1)
    entry_o = bar_after_candle(opt_rows, decision, 1)
    if entry_i is None or entry_o is None:
        return None, "entry minute missing in index or option bars"
    d = sig["spot"] * STOP_PCT
    if sig["opt"] == "CE":          # long the index view
        side, stop, target = "LONG", sig["spot"] - d, sig["spot"] + rr * d
    else:
        side, stop, target = "SHORT", sig["spot"] + d, sig["spot"] - rr * d
    ex = scan_exit(idx_rows, side, entry_i[0], stop, target, FORCE_EXIT)
    if ex["bar"] is None:
        return None, f"exit not available ({ex['reason']})"
    exit_o = next((r for r in opt_rows if r[0] == ex["bar"][0]), None)
    if exit_o is None:
        return None, f"option bar missing at exit minute {ex['bar'][0]}"
    epx, xpx = worst_fills("LONG", entry_o, exit_o)
    return {"entry_o": entry_o, "exit_o": exit_o, "epx": epx, "xpx": xpx, "reason": ex["reason"],
            "stop": stop, "target": target}, None


# --------------------------------------------------------------------------- fetch + main
async def main_async(frm: date, to: date) -> None:
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        step = info["strike_step"]
        cal = await up.expiry_calendar(key, frm, to)
        print(f"NIFTY key {key}; strike step {step}; {len(cal)} expiries; window {frm} to {to}")
        cs = await up.candles(key, "1m", frm, to)
        sessions = sessions_from(cs)
        cov = coverage(sessions, frm, to, 375)

        contracts: dict = {}
        obars: dict = {}
        trades, opt_sessions, skips = [], {}, []

        def skip(day, dec, why):
            skips.append((day, dec, why))
            print(f"  skip {day} {dec}: {why}")

        for day in sorted(sessions):
            rows = sessions[day]
            times = [r[0] for r in rows]
            if len(rows) != 375 or len(set(times)) != 375 or times != FULL_SESSION:
                print(f"  skip {day} (all decisions): incomplete/invalid session ({len(rows)} bars)")
                continue
            d = date.fromisoformat(day)
            for dec in DECISIONS:
                sig, why = signal(rows, dec)
                if sig is None:
                    skip(day, dec, why)
                    continue
                exp = next_expiry(cal, d, 1)
                if exp is None:
                    skip(day, dec, "no expiry at least 1 day after the trade day")
                    continue
                strike = atm_strike(sig["spot"], step)
                ck = (exp, strike, sig["opt"])
                if ck not in contracts:
                    contracts[ck] = await up.resolve_option(key, exp, strike, sig["opt"])
                c = contracts[ck]
                if c is None:
                    skip(day, dec, f"no contract {sig['opt']} {strike:g} exp {exp}")
                    continue
                bk = (c["instrument_key"], day)
                if bk not in obars:
                    obars[bk] = await up.option_candles(c, d)
                orows = obars[bk]
                if not orows:
                    skip(day, dec, f"no option bars for {c['trading_symbol']}")
                    continue
                for rr in RR_LADDER:
                    res, why = simulate(rows, orows, sig, dec, rr)
                    if res is None:
                        skip(day, f"{dec} rr{rr}", why)
                        continue
                    qty = LOTS * c["lot_size"]
                    e, x = res["entry_o"], res["exit_o"]
                    mfe, mae = excursion(orows, "LONG", res["epx"], e[0], x[0])
                    levels = [
                        {"name": "opening range high", "price": sig["rng_hi"], "from": OR_START, "to": FORCE_EXIT},
                        {"name": "opening range low", "price": sig["rng_lo"], "from": OR_START, "to": FORCE_EXIT},
                        {"name": f"index stop (0.1%)", "price": res["stop"], "from": e[0], "to": x[0]},
                        {"name": f"index target (1:{rr})", "price": res["target"], "from": e[0], "to": x[0]},
                    ]
                    tags = {
                        "direction": f"BUY {sig['opt']} ({sig['move']} move faded)",
                        "rsi": bucket(sig["rsi"], [20, 30, 40, 60, 70, 80],
                                      ["<20", "20-30", "30-40", "40-60", "60-70", "70-80", ">80"]),
                        "stretch": bucket(abs(sig["z"]), [1.5, 2.0, 2.5],
                                          ["1.0-1.5 SD", "1.5-2.0 SD", "2.0-2.5 SD", "2.5+ SD"]),
                        "run": bucket(sig["run"], [2, 3, 5], ["1 candle", "2 candles", "3-4 candles", "5+ candles"]),
                    }
                    trades.append(make_trade(
                        day=day, side="LONG", symbol=c["trading_symbol"], entry_time=e[0], entry_px=res["epx"],
                        exit_time=x[0], exit_px=res["xpx"], qty=qty, exit_reason=res["reason"],
                        capital=res["epx"] * qty, mfe=mfe, mae=mae, levels=levels, tags=tags,
                        variant={"decision": dec, "rr": f"1:{rr}"}, option_type=sig["opt"],
                        expiry=c["expiry"],
                        note=f"spot {sig['spot']:.2f}, RSI {sig['rsi']:.1f}, {sig['z']:.2f} SD, run {sig['run']}"))
                    opt_sessions.setdefault(c["trading_symbol"], {})[day] = orows

    lot = trades[0]["qty"] if trades else None
    meta = {
        "title": "Opening Range Reversal v3",
        "subtitle": "Fade a clean one-way drift that never broke the opening range, gated by RSI, SD-stretch and candle-run",
        "instrument": "NIFTY 50 index signal, bought ATM NIFTY option",
        "from": frm.isoformat(), "to": to.isoformat(), "lot_size": lot,
        "fill_rule": "Every buy at the bar HIGH, every sell at the bar LOW; signals acted on in the next 1-minute bar; "
                     "stop/target touches exit in the next bar; stop first if both touch.",
        "cost_model": "Upstox option schedule (brokerage, STT, exchange, SEBI, stamp, GST)",
        "params": {"decision times": ", ".join(DECISIONS), "R:R ladder": ", ".join(map(str, RR_LADDER)),
                   "stop": "0.1% of entry spot (index)", "RSI": f"14 plain, <= {RSI_CE_MAX:g} CE / >= {RSI_PE_MIN:g} PE",
                   "stretch": f">= {SD_MIN} SD (population)", "run": f">= {RUN_MIN} candle", "time exit": FORCE_EXIT,
                   "lots": LOTS},
        "rule_steps": [
            "Opening range = 09:15-09:19 one-minute candles; high = highest high, low = lowest low.",
            "For each decision time D, window = 1-minute candles 09:20..D (at least 20); the spot is the close of the D candle.",
            "Least-squares line through the window closes: down (slope<0 and last<first) or up (slope>0 and last>first); else skip.",
            "Down and every candle high <= range high -> possible CE; up and every candle low >= range low -> possible PE.",
            "RSI(14), plain averages, from the last 15 window closes: CE needs <= 40, PE needs >= 60.",
            "Close of D must be >= 1.0 population SD from the window mean (below for CE, above for PE).",
            "At least 1 candle counting back from D moving with the fade (red for CE, green for PE).",
            "Buy the ATM option (CE/PE) at the HIGH of the 1-minute bar after the D candle completes.",
            "Stop = 0.1% of the spot against the trade, target = stop x R (2,3,4,5,6,8,10), read on index 1-minute candles; "
            "exit in the next option bar at its LOW; stop first if one candle touches both; time exit at 15:00.",
            "One trade per day per decision time and R:R; each (decision time, R:R) is an independent set.",
        ],
        "limits": [
            "ASSUMED: window = 2026-01-01 through the current IST date unless --from/--to given.",
            "ASSUMED: decision candle = the candle starting at D (complete at D+1); entry in the bar starting D+1.",
            "ASSUMED: BUY CE for a faded down move, BUY PE for a faded up move; ATM strike, 1 lot, nearest expiry >= 1 day after the trade day.",
            "ASSUMED: entry spot for stop/target = the decision-candle close; stop/target are INDEX levels (shown as chart levels).",
            "ASSUMED: strike step read once from the live chain, held constant over the window.",
            "ASSUMED: the two OFF filters (max range width, % beyond the edge) are off and not implemented.",
            "CONFLICT resolved by Rules: prompt's 'filled exactly at that level' replaced by next-bar option-LOW fill; "
            "stop/target scan starts after the entry bar, not in it.",
            "Capital = premium x qty (bought option).",
            "In-sample: thresholds were fitted by the prompt's author on the same kind of data; 8 decision times x 7 R:R shown "
            "side by side as filters, the best cell is mostly noise. Trades across R:R share the same entries, so they are not independent.",
            "The prompt itself says the v3 filter discards ~80% of v2's trades; the sample is small.",
            f"Skipped (day, decision, reason) entries: {len(skips)} (printed to the console).",
        ],
        "coverage": cov,
    }
    groups = [
        {"name": "Direction", "keys": ["direction"]},
        {"name": "RSI at decision", "keys": ["rsi"]},
        {"name": "Stretch at decision", "keys": ["stretch"]},
        {"name": "Candle run at decision", "keys": ["run"]},
        {"name": "RSI x stretch", "keys": ["rsi", "stretch"]},
    ]
    payload = build_payload(meta, trades, sessions, opt_sessions, groups)
    path = write_report(payload, SLUG)
    print(console_summary(trades))
    print(path)


def main() -> None:
    now = datetime.now(IST)
    yesterday = now.date() - timedelta(days=1)
    ap = argparse.ArgumentParser(description="Opening Range Reversal v3 backtest")
    ap.add_argument("--from", dest="frm", type=date.fromisoformat, default=START_DATE)
    ap.add_argument("--to", dest="to", type=date.fromisoformat, default=END_DATE)
    a = ap.parse_args()
    to = a.to
    if to >= now.date() and (now.hour, now.minute) < (15, 45):   # Rule 7: today not used until over
        to = yesterday
    frm = a.frm or (to - timedelta(days=182))
    asyncio.run(main_async(frm, to))


if __name__ == "__main__":
    main()
