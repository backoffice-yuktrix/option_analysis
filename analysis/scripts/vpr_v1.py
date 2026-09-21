"""Volume Profile Range - v1 (value-area break and retest), NIFTY.

STRATEGY PROMPT (verbatim)
--------------------------
## 5. Value-area break and retest
Profile yesterday, extend the three lines into today, and trade the band break that holds when price comes back to it.
### v1 - the rule as specified
Step 1 - Build a fixed-range profile of the PREVIOUS session in full, on 5-minute candles, and take its point of
control, its value-area high and its value-area low. Value area is the middle 70% of the session, in 5-point rows.
Step 2 - Weight the profile by TIME, not volume: one unit per bar for every price row that bar spans. (Index has no
volume.)
Step 3 - Extend those three lines into the current day and leave them fixed.
Step 4 - Where the market opened / whether yesterday closed inside or outside the value area does not matter.
Step 5 - A candle that CLOSES above the value-area high arms a long. A candle that CLOSES below the value-area low
arms a short.
Step 6 - Between 4 and 7 candles after that breaking candle, price must come back and retest the band it broke.
Step 7 - The retest must be CONFIRMED: the retest candle has to reach the band AND still close beyond it.
Step 8 - The entry is the OPEN OF THE NEXT CANDLE after that confirming close.
Step 9 - For a long, the stop is 25 points below the value-area high. For a short it is 25 points above the
value-area low.
Step 10 - Risk = distance entry to stop, target = 2 x risk; 1:3 and 1:4 are scored off the same entries.
Step 11 - Walk the exits on 1-MINUTE candles whatever timeframe the signal came from.
Step 12 - Inside any one minute the order is square-off, then stop, then target (a minute spanning both = a loss).
Step 13 - One trade a day: the first placeable retest, then the day is done.
Step 14 - Square off at 15:15.
Step 15 - The signal runs on 3-minute and 5-minute candles, opening on 5-minute. (15-minute dropped.)
Note: the spec's short stop "above the VAH" is the far side of the value area; it is mirrored to VAL + 25. The
literal reading is kept behind a flag (--literal-short-stop).

CHECKLIST (RUN.md Step 1)
-------------------------
 1 Underlying          clear    NIFTY 50 index (signal levels read from it)
 2 Window              assumed  prompt names none -> last 6 months ending yesterday
 3 Signal timeframe    clear    3m and 5m (variant tf=); profile itself on 5m candles of the previous session
 4 Signal rule         assumed  see ASSUMPTIONS 3-9
 5 Decision time       clear    the close of the confirming retest candle
 6 Direction mapping   ASSUMED   long -> buy ATM CE ; short -> buy ATM PE (the prompt never names an instrument)
 7 Traded instrument   ASSUMED   NIFTY option (the index is not tradable; costs for other kinds need rates)
 8 Option specifics    assumed  buy, ATM, 1 lot, nearest expiry >= 1 day after the exit day
 9 Entry               clear    next 1-minute bar after the confirming candle completes (rule 2)
10 Exit                clear    index-level stop, target 2R/3R/4R (variant rr=), square-off 15:15; stop first on a tie
11 Holding             clear    intraday
12 Costs               assumed  standard option schedule
13 Position rules      clear    one trade a day per (tf) variant set; no re-entry
14 Missing data        assumed  skip and list
15 Filters             clear    side x tf (3m,5m) x rr (1:2,1:3,1:4)
16 Custom group-bys    assumed  retest lag (4..7), value-area width bucket, all measured at the entry signal
17 Script name         vpr_v1

ASSUMPTIONS
-----------
 1 ASSUMED  Traded instrument: long -> buy ATM CE, short -> buy ATM PE, 1 lot, ATM from the confirming candle's
            close, strike step from Upstox. Stop and target stay INDEX levels (prompt basis); the option exits in
            the 1-minute bar after the index bar that touched them.
 2 ASSUMED  Time exit 15:15 fills in the 15:15 bar itself. No entry at or after 15:15.
 3 ASSUMED  Profile rows: 5-point grid anchored at multiples of 5 (row = [5k, 5k+5)). A 5-minute bar adds one unit
            to every row from floor(low/5) up to the row holding its high (a high exactly on a row edge does not
            add the row above).
 4 ASSUMED  POC = centre of the row with the most units (ties: row nearest the session mid-range, then the lower).
 5 ASSUMED  Value area: standard two-row expansion from the POC row until >= 70% of all units; each step adds the
            side whose next two rows hold more units. VAH = top edge of the highest row, VAL = bottom edge of the
            lowest row.
 6 ASSUMED  "Previous session" = the previous session present in the data; it and the current session must both be
            full (375 one-minute bars, 09:15-15:29).
 7 ASSUMED  Break candle = a candle that closes beyond the level while the candle before it did not (the first
            candle of the day counts if it closes beyond). Later candles that stay beyond do not re-arm.
 8 ASSUMED  "Between 4 and 7 candles after" = the retest candle is 4, 5, 6 or 7 candles after the break candle
            (inclusive), on the signal timeframe. Reaching the band = low <= VAH (long) / high >= VAL (short) - the
            band is the level line. Confirming = close beyond the level (close > VAH / close < VAL).
 9 ASSUMED  "First placeable retest": retests are taken in time order; one that cannot be placed (entry at/after
            15:15, or risk <= 0 because the entry is already through the stop) is passed over. A missing option
            bar or contract skips the day (rule 6), it is not passed over.
10 ASSUMED  Entry index reference (for risk and target) = the worst index fill of the entry bar (high for a long
            signal, low for a short signal); risk = |that - stop|; target = entry +/- rr x risk.
11 ASSUMED  Step 11's exit scan runs on the INDEX 1-minute bars; the entry bar itself is not scanned.
12 ASSUMED  Costs: standard option schedule (option_costs).
13 ASSUMED  Capital = premium x qty (a bought option).
14 ASSUMED  "opening on 5-minute" is read as both tf values being shown; no variant is preselected.
15 ASSUMED  Literal short stop (VAH + 25) is only used with --literal-short-stop; default is the mirrored VAL + 25.

CONFLICTS WITH RULES TO LIVE BY (rules win)
-------------------------------------------
* Step 8 "entry at the OPEN of the next candle" -> rule 1/2: filled in the next 1-minute bar at its HIGH (buy).
* Step 12 "square-off, then stop, then target; a minute spanning both is a loss": kept as stop-before-target, but
  stops/targets are signals, so they exit in the next 1-minute bar (rule 3).
* Step 9/10 stop and target at exact levels -> filled at the next bar's worst price, not the level.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *

import argparse

TFS = [3, 5]
RRS = [2, 3, 4]
ROW = 5.0
VA_FRAC = 0.70
STOP_PTS = 25.0
RETEST_MIN, RETEST_MAX = 4, 7
SQUARE_OFF = "15:15"
LAST_ENTRY = "15:15"
LOOKBACK_DAYS = 14


# ------------------------------------------------------------------ signal (pure) -----------------
def build_profile(rows_5m: list[list]) -> dict | None:
    """Time-weighted profile of one session's 5-minute bars -> {poc, vah, val}."""
    counts: dict[int, int] = {}
    for _, o, h, l, c in rows_5m:
        lo = math.floor(l / ROW)
        hi = max(math.ceil(h / ROW) - 1, lo)
        for k in range(lo, hi + 1):
            counts[k] = counts.get(k, 0) + 1
    if not counts:
        return None
    total = sum(counts.values())
    mid = (max(r[2] for r in rows_5m) + min(r[3] for r in rows_5m)) / 2
    poc = min((k for k, v in counts.items() if v == max(counts.values())),
              key=lambda k: (abs((k + 0.5) * ROW - mid), k))
    lo_k = hi_k = poc
    acc = counts[poc]
    lo_edge, hi_edge = min(counts), max(counts)          # rows may be empty inside; count as zero
    while acc < VA_FRAC * total:
        up = [counts.get(hi_k + 1, 0), counts.get(hi_k + 2, 0)]
        dn = [counts.get(lo_k - 1, 0), counts.get(lo_k - 2, 0)]
        can_up, can_dn = hi_k < hi_edge, lo_k > lo_edge
        if not can_up and not can_dn:
            break
        go_up = can_up and (not can_dn or sum(up) >= sum(dn))
        if go_up:
            step = [k for k in (hi_k + 1, hi_k + 2) if k <= hi_edge]
            hi_k = step[-1]
            acc += sum(counts.get(k, 0) for k in step)
        else:
            step = [k for k in (lo_k - 1, lo_k - 2) if k >= lo_edge]
            lo_k = step[-1]
            acc += sum(counts.get(k, 0) for k in step)
    return {"poc": (poc + 0.5) * ROW, "vah": (hi_k + 1) * ROW, "val": lo_k * ROW, "units": total}


def find_retests(candles: list[list], vah: float, val: float) -> list[dict]:
    """Confirmed retests in time order.  candles = [[HH:MM,o,h,l,c]] of ONE session, completed candles only.
    A candle is read with information up to and including itself only."""
    breaks = {"LONG": [], "SHORT": []}
    for i, r in enumerate(candles):
        prev = candles[i - 1][4] if i else None
        if r[4] > vah and (prev is None or prev <= vah):
            breaks["LONG"].append(i)
        if r[4] < val and (prev is None or prev >= val):
            breaks["SHORT"].append(i)
    out = []
    for i, r in enumerate(candles):
        for side, lvl in (("LONG", vah), ("SHORT", val)):
            lag = [i - b for b in breaks[side] if RETEST_MIN <= i - b <= RETEST_MAX]
            if not lag:
                continue
            reach = r[3] <= lvl if side == "LONG" else r[2] >= lvl
            beyond = r[4] > lvl if side == "LONG" else r[4] < lvl
            if reach and beyond:
                out.append({"i": i, "start": r[0], "side": side, "lag": min(lag), "close": r[4]})
    return out


# ------------------------------------------------------------------ simulate (pure) ---------------
def index_stop_target(side: str, entry_ref: float, vah: float, val: float, rr: float, literal: bool):
    if side == "LONG":
        stop = vah - STOP_PTS
        risk = entry_ref - stop
        return stop, entry_ref + rr * risk, risk
    stop = (vah if literal else val) + STOP_PTS
    risk = stop - entry_ref
    return stop, entry_ref - rr * risk, risk


# ------------------------------------------------------------------ main --------------------------
async def run(frm: date, to: date, literal: bool):
    trades: list[dict] = []
    skips: list[str] = []
    opt_sessions: dict[str, dict[str, list]] = {}
    lot = None
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        step = info["strike_step"]
        lot = info["lot_size"]
        expiries = await up.expiry_calendar(key, frm, to)
        print(f"NIFTY key {key}, strike step {step}, {len(expiries)} expiries known")
        cs = await up.candles(key, "1m", frm - timedelta(days=LOOKBACK_DAYS), to)
        sess = sessions_from(cs)
        days = [d for d in sorted(sess) if frm.isoformat() <= d <= to.isoformat()]
        cov = coverage({d: r for d, r in sess.items() if frm.isoformat() <= d <= to.isoformat()}, frm, to, 375)
        for g in cov["weekday_gaps"]:
            print(f"SKIP {g}: no candles (holiday or feed miss)")

        def full(d):
            r = sess.get(d, [])
            return len(r) == 375 and r[0][0] == "09:15" and r[-1][0] == "15:29"

        all_days = sorted(sess)
        contracts: dict = {}
        for day in days:
            if not full(day):
                print(f"SKIP {day}: incomplete session ({len(sess[day])} bars)")
                continue
            prev = next((d for d in reversed(all_days) if d < day), None)
            if prev is None or not full(prev):
                print(f"SKIP {day}: previous session {prev} missing or incomplete")
                continue
            prof = build_profile(resample(sess[prev], 5))
            if not prof:
                print(f"SKIP {day}: empty profile")
                continue
            vah, val, poc = prof["vah"], prof["val"], prof["poc"]
            rows1 = sess[day]
            d_ = date.fromisoformat(day)
            for tf in TFS:
                cand = resample(rows1, tf)
                rets = find_retests(cand, vah, val)
                if not rets:
                    print(f"SKIP {day} tf={tf}m: no confirmed retest")
                    continue
                placed = None
                for rt in rets:
                    eb = bar_after_candle(rows1, rt["start"], tf)
                    if eb is None:
                        print(f"SKIP {day} tf={tf}m: entry bar after {rt['start']} missing")
                        placed = "bad"
                        break
                    if eb[0] >= LAST_ENTRY:
                        print(f"  {day} tf={tf}m: retest {rt['start']} entry {eb[0]} too late")
                        continue
                    ref = eb[2] if rt["side"] == "LONG" else eb[3]
                    _, _, risk = index_stop_target(rt["side"], ref, vah, val, 2, literal)
                    if risk <= 0:
                        print(f"  {day} tf={tf}m: retest {rt['start']} passed over (risk {risk:.1f} <= 0)")
                        continue
                    placed = (rt, eb, ref)
                    break
                if placed is None:
                    print(f"SKIP {day} tf={tf}m: no placeable retest")
                    continue
                if placed == "bad":
                    continue
                rt, eb, ref = placed
                side = rt["side"]
                otype = "CE" if side == "LONG" else "PE"
                exp = next_expiry(expiries, d_, 1)
                if exp is None:
                    print(f"SKIP {day} tf={tf}m: no expiry >= 1 day after")
                    continue
                strike = atm_strike(rt["close"], step)
                ck = (exp, strike, otype)
                if ck not in contracts:
                    contracts[ck] = await up.resolve_option(key, exp, strike, otype)
                c = contracts[ck]
                if not c:
                    print(f"SKIP {day} tf={tf}m: no contract {exp} {strike} {otype}")
                    continue
                lot = c["lot_size"] or lot
                opt_sessions.setdefault(c["trading_symbol"], {})
                orows = opt_sessions[c["trading_symbol"]].get(day)
                if orows is None:
                    orows = await up.option_candles(c, d_)
                    opt_sessions[c["trading_symbol"]][day] = orows
                if not orows:
                    print(f"SKIP {day} tf={tf}m: no option bars for {c['trading_symbol']}")
                    continue
                oby = {r[0]: r for r in orows}
                oe = oby.get(eb[0])
                if oe is None:
                    print(f"SKIP {day} tf={tf}m: option bar {eb[0]} missing for {c['trading_symbol']}")
                    continue
                qty = c["lot_size"]
                width = vah - val
                tags = {"direction": "long break (CE)" if side == "LONG" else "short break (PE)",
                        "retest lag": f"{rt['lag']} candles",
                        "va width": bucket(width, [60, 100], ["under 60", "60-100", "over 100"])}
                for rr in RRS:
                    stop, target, risk = index_stop_target(side, ref, vah, val, rr, literal)
                    res = scan_exit(rows1, "LONG" if side == "LONG" else "SHORT", eb[0], stop, target, SQUARE_OFF)
                    xb = res["bar"]
                    if xb is None:
                        print(f"SKIP {day} tf={tf}m rr={rr}: no exit bar ({res['reason']})")
                        continue
                    ox = oby.get(xb[0])
                    if ox is None:
                        print(f"SKIP {day} tf={tf}m rr={rr}: option exit bar {xb[0]} missing")
                        continue
                    epx, xpx = worst_fills("LONG", oe, ox)
                    mfe, mae = excursion(orows, "LONG", epx, eb[0], xb[0])
                    levels = [{"name": "VAH", "price": vah}, {"name": "POC", "price": poc},
                              {"name": "VAL", "price": val},
                              {"name": f"stop {stop:.1f}", "price": stop},
                              {"name": f"target {target:.1f}", "price": target}]
                    trades.append(make_trade(
                        day=day, side="LONG", symbol=c["trading_symbol"], entry_time=eb[0], entry_px=epx,
                        exit_time=xb[0], exit_px=xpx, qty=qty, exit_reason=res["reason"],
                        capital=epx * qty, expiry=c["expiry"], option_type=otype, mfe=mfe, mae=mae,
                        variant={"tf": f"{tf}m", "rr": f"1:{rr}"}, tags=tags, levels=levels,
                        note=f"{'long' if side == 'LONG' else 'short'} signal; retest candle {rt['start']} ({tf}m), "
                             f"lag {rt['lag']}; index stop {stop:.1f} target {target:.1f} risk {risk:.1f}"))
    return trades, sess, opt_sessions, lot, cov, skips


def main():
    ap = argparse.ArgumentParser()
    yest = datetime.now(IST).date() - timedelta(days=1)
    ap.add_argument("--from", dest="frm", default=(yest - timedelta(days=182)).isoformat())
    ap.add_argument("--to", dest="to", default=yest.isoformat())
    ap.add_argument("--literal-short-stop", action="store_true",
                    help="short stop at VAH+25 (the spec as literally written) instead of VAL+25")
    a = ap.parse_args()
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    now = datetime.now(IST)
    if to >= now.date() and now.strftime("%H:%M") < "15:45":
        to = now.date() - timedelta(days=1)
        print(f"today's session is not over: window ends {to}")
    trades, sess, opt, lot, cov, _ = asyncio.run(run(frm, to, a.literal_short_stop))
    meta = {
        "title": "Volume Profile Range v1 - value-area break and retest",
        "subtitle": "NIFTY 50: previous-session time profile (5-min, 5-pt rows, 70% value area); break, retest, "
                    "bought ATM option",
        "instrument": "NIFTY 50 index signal, ATM option traded", "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": lot,
        "fill_rule": "Buys fill at the bar's HIGH, sells at the bar's LOW; signal acted on in the next 1-minute bar; "
                     "stop/target touches exit in the next 1-minute bar.",
        "cost_model": "Standard option schedule (brokerage 20/order, STT, exchange, SEBI, stamp, GST)",
        "params": {"timeframes": "3m, 5m", "profile": "prev session, 5m, 5-pt rows, time-weighted, 70% VA",
                   "retest window": f"{RETEST_MIN}-{RETEST_MAX} candles after break", "stop": f"{STOP_PTS:.0f} pts from level",
                   "target": "1:2 / 1:3 / 1:4", "square off": SQUARE_OFF, "lots": 1,
                   "short stop": "literal VAH+25" if a.literal_short_stop else "mirrored VAL+25"},
        "rule_steps": [
            "Profile the previous full session on 5-minute candles: one unit per bar per 5-point row it spans; POC, VAH, VAL (70% value area).",
            "Fix those three lines for today.",
            "A candle that closes above VAH (below VAL) arms a long (short).",
            f"{RETEST_MIN} to {RETEST_MAX} candles later, a candle that reaches the level and closes beyond it confirms the retest.",
            "Enter in the next 1-minute bar after that candle completes: buy the ATM CE (long) or PE (short) at that bar's high.",
            "Index stop 25 points beyond the level (mirrored for shorts); target 2, 3 or 4 times the risk on the index.",
            "A stop or target touched in a completed 1-minute bar exits in the next bar (stop first if both); square off at 15:15.",
            "One trade a day per timeframe; missing data skips the day."],
        "limits": [
            "ASSUMED: the prompt names no traded instrument; long = buy ATM CE, short = buy ATM PE, 1 lot, nearest expiry >= 1 day after the day.",
            "ASSUMED: stop and target are index levels; the option exits in the bar after the index bar that touched them.",
            "ASSUMED: profile rows on a 5-pt grid anchored at multiples of 5, POC ties nearest mid-range, two-row value-area expansion; VAH = top edge, VAL = bottom edge.",
            "ASSUMED: break candle = first close beyond the level; retest lag 4-7 inclusive; reach = wick touches the level line; passed-over retests when risk <= 0 or entry >= 15:15.",
            "ASSUMED: index entry reference for risk/target = the entry bar's index high (long) / low (short); short stop mirrored to VAL+25 unless --literal-short-stop.",
            "ASSUMED: capital = premium x qty; costs = standard option schedule.",
            "Spec fills at the next candle's open and exits at exact stop/target prices; here fills are worst-case (high/low, next bar).",
            "In-sample: 15-minute was dropped and 3m/5m kept after looking at results; all rr and tf variants are shown as filters. Not an out-of-sample test.",
            "Sold-option margin not used (options are bought).",
            "Time weighting, not volume: NIFTY index has no volume."],
        "coverage": cov}
    groups = [{"name": "Retest lag", "keys": ["retest lag"]},
              {"name": "Value-area width", "keys": ["va width"]},
              {"name": "Direction x lag", "keys": ["direction", "retest lag"]}]
    if not trades:
        print("0 trades")
        return
    payload = build_payload(meta, trades, sess, opt, groups)
    path = write_report(payload, "vpr_v1")
    print(console_summary(trades))
    print(path)


if __name__ == "__main__":
    main()
