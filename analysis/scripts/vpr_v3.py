"""Volume Profile Range - v3 (value-area re-entry), backtest script.

STRATEGY PROMPT (verbatim)
--------------------------
v3 VPR
## 6. Value-area re-entry
The mirror of the break and retest: price tries to leave value, fails, and comes back in.
Step 1 - Build the previous session's profile on 5-minute candles, time-weighted, and extend the point of control,
  the value-area high and the value-area low into today. It does not matter where the previous session closed.
Step 2 - A re-entry is a CROSSING inward. The candle before must have CLOSED OUTSIDE the band; without that, every
  candle drifting around inside value arms the rule and the "re-entry" is not an entry at all.
Step 3 - Price is ABOVE the value-area high and a candle closes back BELOW it. That arms a short.
Step 4 - Price is BELOW the value-area low and a candle closes back ABOVE it. That arms a long.
Step 5 - Between 4 and 7 candles later, price must retest that band from the inside and it must HOLD: the retest
  candle reaches the level and still closes back inside value. On the short side that is the value-area high holding
  as resistance; on the long side the value-area low holding as support.
Step 6 - The entry is the OPEN of the candle after that confirming close, taken back INTO the value area.
Step 7 - For the short, the stop is 25 points above the value-area high. For the long, 25 points below the value-area low.
Step 8 - Risk is the distance from the entry to the stop, and the target is 2 times the risk; 1:3 and 1:4 are scored
  off the same entries.
Step 9 - Walk the exits on 1-minute candles; inside any one minute the order is square-off, then stop, then target.
Step 10 - One trade a day, and square off at 15:15.
Step 11 - The signal runs on 3-minute and 5-minute candles, opening on 5-minute.
(Commentary in the prompt: does not beat break-and-retest; short half is 21 trades; compare each side against a
 same-side control, never against zero.)

RUN.md STEP 1 CHECKLIST (non-interactive: gaps closed with defaults / simplest reading; ASSUMED = not in prompt)
 1 Underlying          clear    NIFTY 50 index (profile and signals read from it)
 2 Window              ASSUMED  2026-01-01 through the current IST date (RUN.md default)
 3 Signal timeframe    clear    3m and 5m (variant tf); profile always on 5m of the previous session
 4 Signal rule         partly   ASSUMED profile details: 1-point price bins; time-weighted = each 5m candle adds 1 to
                                every bin its low..high spans (TPO style); value area = 70% of the total, grown from
                                the POC bin by repeatedly adding the heavier of the next two bins above / below
                                (standard method); POC tie -> bin nearest the previous session's mid-range;
                                VAL = lower edge of the lowest VA bin, VAH = upper edge of the highest, POC = bin centre.
                                ASSUMED "back below/above" = strict close < VAH / > VAL. "4 to 7 candles later" =
                                retest candle index arm+4 .. arm+7 inclusive; "reaches the level" = high >= VAH
                                (short) / low <= VAL (long); holds = close < VAH / close > VAL. No invalidation of an
                                armed setup between arm and retest. The first candle of the day has no "candle
                                before" inside the day (no carry-over of yesterday's close). Earliest confirmed retest
                                wins the day.
 5 Decision time       clear    close of the retest (confirming) candle; fill per Rules 1-2
 6 Direction mapping   ASSUMED  short setup -> BUY a PE; long setup -> BUY a CE (prompt gives no instrument)
 7 Traded instrument   ASSUMED  NIFTY options (Rule 5 forbids guessing costs for index/futures)
 8 Option specifics    ASSUMED  buy, ATM (spot = close of the confirming candle, step read from Upstox), expiry = nearest
                                at least 1 day after the trade day, 1 lot (qty from the resolved contract)
 9 Entry               clear    confirming close -> next 1-minute bar (Rules 1-2), no extra condition
10 Exit                clear    stop = VAH+25 / VAL-25 (index level), target = entry +/- rr x risk (index level),
                                square-off 15:15 (fills in the 15:15 bar); order in one bar: square-off, stop, target.
                                Stop/target are watched on the INDEX 1-minute bars, the option exits in the next
                                1-minute bar (Rule 3). ASSUMED risk/target measured from the index worst-fill reference
                                of the entry bar (long: bar high, short: bar low).
11 Holding             clear    intraday
12 Costs               ASSUMED  standard option schedule (option_costs)
13 Position rules      clear    one trade a day (per variant), no overlap
14 Missing data        ASSUMED  skip and print
15 Filters             clear    tf (3m,5m) x rr (1:2,1:3,1:4) x signal (short/long) x side
16 Group-bys           ASSUMED  direction; retest delay (candles after arming); entry vs POC; combined direction x delay
17 Script name         vpr_v3

Rule conflicts (Rules to Live By override the prompt): "entry is the OPEN of the candle after the confirming close"
-> Rule 1: fill at the next 1-minute bar's high (buy option); "candle after" on the signal timeframe -> Rule 2:
next 1-minute bar after the confirming candle completes; stop/target "walk exits on 1m" filled at the level -> Rule 3:
exit in the bar after the touch, worst fills.
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: F401,F403,E402

SLUG = "vpr_v3"
TFS = (3, 5)
RRS = (2, 3, 4)
STOP_BUFFER = 25.0
RETEST_MIN, RETEST_MAX = 4, 7
SQUARE_OFF = "15:15"
VA_SHARE = 0.70
BIN = 1.0
SESSION_ROWS = 375

# The axes the source (va_reentry_v1) compares and this script used to fix at one point each.
# All four re-read bars already fetched, so the sweep costs no new data beyond the contracts a
# different confirmation lands on.
CONFIRMS = [
    ("close", "reaches the band and closes back inside"),
    ("touch", "reaches the band; no close test"),
    ("two-candle", "a later candle closes inside after the touch"),
    ("reclaim", "closes back outside, then fails and closes inside again"),
]
STOP_MODES = [("band", "inside the broken band - the spec"),
              ("entry", "a fixed distance from the entry price")]
EOD_MODES = [("close", "square off at the session close time"),
             ("hold", "run to stop or target, give up at the last candle")]
BOOKS = [("session", "the first placeable entry of the day, then done"),
         ("flow", "one position at a time, re-entering whenever it re-arms")]
# The RULE is the prompt as written: close-confirmed retest, stop inside the broken band,
# square off at 15:15, one trade a day. Everything else is the same sessions priced another way.
RULE = {"confirm": "close", "stop_mode": "band", "eod": "close", "book": "session"}

SETTINGS = [
    setting("confirm", "Retest confirmation", kind="entry", default=RULE["confirm"],
            options=[{"value": k, "label": v, "raw": k} for k, v in CONFIRMS],
            help="what counts as the retest holding"),
    setting("tf", "Signal timeframe", kind="other", values=[f"{t}m" for t in TFS], default="3m"),
    setting("rr", "Reward:risk", kind="exit", values=[f"1:{r}" for r in RRS], default="1:2"),
    setting("stop_mode", "Stop anchor", kind="exit", default=RULE["stop_mode"],
            options=[{"value": k, "label": v, "raw": k} for k, v in STOP_MODES]),
    setting("eod", "End of day", kind="exit", default=RULE["eod"],
            options=[{"value": k, "label": v, "raw": k} for k, v in EOD_MODES]),
    setting("book", "Position rule", kind="sizing", default=RULE["book"],
            options=[{"value": k, "label": v, "raw": k} for k, v in BOOKS]),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def session_problem(rows: list[list]) -> str | None:
    """None when the session is a complete, clean 375-bar session."""
    times = [r[0] for r in rows]
    if len(times) != SESSION_ROWS:
        return f"{len(times)} one-minute bars instead of {SESSION_ROWS}"
    if len(set(times)) != len(times):
        return "duplicate bars"
    if times[0] != "09:15" or times[-1] != "15:29":
        return f"session runs {times[0]}-{times[-1]}"
    for r in rows:
        if not (r[3] <= min(r[1], r[4]) and r[2] >= max(r[1], r[4]) and r[3] > 0):
            return f"invalid bar at {r[0]}"
    return None


def value_area(rows_5m: list[list]) -> dict:
    """Time-weighted (TPO style) profile on 5m candles: POC, VAH, VAL (see docstring)."""
    tpo: dict[int, int] = {}
    for r in rows_5m:
        for b in range(int(r[3] // BIN), int(r[2] // BIN) + 1):
            tpo[b] = tpo.get(b, 0) + 1
    lo, hi = min(tpo), max(tpo)
    mid = (min(r[3] for r in rows_5m) + max(r[2] for r in rows_5m)) / 2 / BIN
    best = max(tpo.values())
    poc = min((b for b, v in tpo.items() if v == best), key=lambda b: abs(b + 0.5 - mid))
    total, acc = sum(tpo.values()), tpo[poc]
    up = dn = poc
    while acc < VA_SHARE * total and (up < hi or dn > lo):
        a = [tpo.get(up + 1, 0), tpo.get(up + 2, 0)] if up < hi else None
        d = [tpo.get(dn - 1, 0), tpo.get(dn - 2, 0)] if dn > lo else None
        if a is not None and (d is None or sum(a) >= sum(d)):
            for _ in a:
                if up < hi:
                    up += 1
                    acc += tpo.get(up, 0)
        else:
            for _ in d:
                if dn > lo:
                    dn -= 1
                    acc += tpo.get(dn, 0)
    return {"poc": (poc + 0.5) * BIN, "vah": (up + 1) * BIN, "val": dn * BIN}


def find_signals(cs: list[list], vah: float, val: float, confirm: str) -> list[dict]:
    """Every confirming retest in the session, earliest first, under one confirmation rule.

    Completed candles only (rule 4).  `j` is the candle whose completion confirms the setup;
    the entry is the 1-minute bar after it (rule 2).  The four rules differ only in what counts
    as the retest holding:
      close       the retest candle reaches the band AND closes back inside   (the rule)
      touch       it reaches the band; no close test
      two-candle  it reaches the band, and a LATER candle closes back inside
      reclaim     it CLOSES back outside the band, and a later candle closes inside again
    """
    out, n = [], len(cs)
    for j in range(RETEST_MIN + 1, n):
        for k in range(RETEST_MIN, RETEST_MAX + 1):
            a = j - k
            if a < 1:
                continue
            armed_s = cs[a - 1][4] > vah and cs[a][4] < vah      # was above, crossed back in
            armed_l = cs[a - 1][4] < val and cs[a][4] > val      # was below, crossed back in
            if not (armed_s or armed_l):
                continue
            side = "short" if armed_s else "long"
            reach = cs[j][2] >= vah if armed_s else cs[j][3] <= val
            inside = cs[j][4] < vah if armed_s else cs[j][4] > val
            outside = cs[j][4] > vah if armed_s else cs[j][4] < val
            conf = None
            if confirm == "close" and reach and inside:
                conf = j
            elif confirm == "touch" and reach:
                conf = j
            elif confirm == "two-candle" and reach:
                for mm in range(j + 1, n):                        # the first later close back inside
                    if (cs[mm][4] < vah) if armed_s else (cs[mm][4] > val):
                        conf = mm
                        break
            elif confirm == "reclaim" and outside:
                for mm in range(j + 1, n):
                    if (cs[mm][4] < vah) if armed_s else (cs[mm][4] > val):
                        conf = mm
                        break
            if conf is not None:
                out.append({"j": conf, "k": k, "arm": a, "dir": side})
                break                                             # one setup per arming candle
    out.sort(key=lambda x: x["j"])
    seen, uniq = set(), []
    for x in out:
        if x["j"] not in seen:
            seen.add(x["j"])
            uniq.append(x)
    return uniq


def simulate_index(rows: list[list], direction: str, entry_bar: list, vah: float, val: float,
                   rr: int, stop_mode: str = "band", eod: str = "close") -> dict | None:
    """Index-level stop/target walk on 1-minute bars.

    stop_mode  "band"  the stop sits STOP_BUFFER outside the broken band (the spec)
               "entry" STOP_BUFFER from the entry price, so every loss is the same size
    eod        "close" square off at SQUARE_OFF; "hold" run on and give up at the last candle
    """
    if direction == "short":
        side, ref = "SHORT", entry_bar[3]
        stop = (vah + STOP_BUFFER) if stop_mode == "band" else (ref + STOP_BUFFER)
        risk = stop - ref
        target = ref - rr * risk
    else:
        side, ref = "LONG", entry_bar[2]
        stop = (val - STOP_BUFFER) if stop_mode == "band" else (ref - STOP_BUFFER)
        risk = ref - stop
        target = ref + rr * risk
    if risk <= 0:
        return None
    ex = scan_exit(rows, side, entry_bar[0], stop, target, SQUARE_OFF if eod == "close" else None)
    return {"exit": ex, "stop": stop, "target": target, "ref": ref, "risk": risk}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def _vals(key):
    return [o["raw"] for o in next(x for x in SETTINGS if x["key"] == key)["options"]]


async def main(frm: date, to: date) -> None:
    use_confirms = _vals("confirm")
    use_stops = _vals("stop_mode")
    use_eods = _vals("eod")
    use_books = _vals("book")
    use_tfs = [int(v[:-1]) for v in _vals("tf")]          # "3m" -> 3
    use_rrs = [int(v.split(":")[1]) for v in _vals("rr")]  # "1:2" -> 2
    skips: list[str] = []
    trades: list[dict] = []
    opt_sessions: dict[str, dict[str, list]] = {}
    opt_cache: dict[tuple, list] = {}

    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        step = info["strike_step"]
        expiries = await up.expiry_calendar(key, frm, to)
        cs1 = await up.candles(key, "1m", frm - timedelta(days=10), to)
        sessions = sessions_from(cs1)
        days = [d for d in sorted(sessions) if frm.isoformat() <= d <= to.isoformat()]
        allkeys = sorted(sessions)
        now = datetime.now(IST)
        today = now.date().isoformat()
        print(f"NIFTY key {key}, strike step {step}, {len(days)} sessions in window")

        for d in days:
            if d == today and now.strftime("%H:%M") <= "15:45":
                skips.append(f"{d}: today's session is not over")
                print("skip", skips[-1]); continue
            rows = sessions[d]
            prob = session_problem(rows)
            if prob:
                skips.append(f"{d}: {prob}")
                print("skip", skips[-1]); continue
            idx = allkeys.index(d)
            if idx == 0:
                skips.append(f"{d}: no previous session in the data")
                print("skip", skips[-1]); continue
            pd_ = allkeys[idx - 1]
            if (date.fromisoformat(d) - date.fromisoformat(pd_)).days > 5:
                skips.append(f"{d}: previous session {pd_} is more than 5 days back")
                print("skip", skips[-1]); continue
            prob = session_problem(sessions[pd_])
            if prob:
                skips.append(f"{d}: previous session {pd_} unusable ({prob})")
                print("skip", skips[-1]); continue
            va = value_area(resample(sessions[pd_], 5))
            vah, val, poc = va["vah"], va["val"], va["poc"]

            expiry = next_expiry(expiries, date.fromisoformat(d), 1)
            if expiry is None:
                skips.append(f"{d}: no expiry >= 1 day after")
                print("skip", skips[-1]); continue

            async def contract_for(close_px, opt_type):
                """The ATM contract for this setup, with its bars.  Cached per (strike, type)
                within the day, and py_funcs caches the bars across runs."""
                strike = atm_strike(close_px, step)
                ckey = (strike, opt_type)
                if ckey in day_contracts:
                    return day_contracts[ckey]
                con = await up.resolve_option(key, expiry, strike, opt_type)
                rws = []
                if con is not None:
                    try:
                        rws = await up.option_candles(con, date.fromisoformat(d))
                    except RuntimeError as exc:
                        print(f"  ! option fetch failed {con['trading_symbol']} {d}: {exc}")
                day_contracts[ckey] = (con, rws)
                return day_contracts[ckey]

            day_contracts: dict = {}
            for tf in use_tfs:
                cs = resample(rows, tf)
                for confirm in use_confirms:
                    sigs = find_signals(cs, vah, val, confirm)
                    if not sigs:
                        skips.append(f"{d} {tf}m {confirm}: no value-area re-entry setup")
                        continue
                    for book in use_books:
                        # "session" takes the first placeable setup and is done; "flow" re-arms
                        # after each trade closes, one position at a time, first come first served.
                        for stop_mode in use_stops:
                            for eod in use_eods:
                                for rr in use_rrs:
                                    busy_until = ""
                                    for sig in sigs:
                                        c = cs[sig["j"]]
                                        if c[0] < busy_until:
                                            continue
                                        ebar = bar_after_candle(rows, c[0], tf)
                                        if ebar is None or ebar[0] >= SQUARE_OFF:
                                            continue
                                        opt_type = "PE" if sig["dir"] == "short" else "CE"
                                        contract, orows = await contract_for(c[4], opt_type)
                                        if contract is None:
                                            continue
                                        obar_in = next((r for r in orows if r[0] == ebar[0]), None)
                                        if obar_in is None:
                                            continue
                                        sim = simulate_index(rows, sig["dir"], ebar, vah, val, rr,
                                                             stop_mode, eod)
                                        if sim is None or sim["exit"]["bar"] is None:
                                            continue
                                        ex = sim["exit"]
                                        obar_out = next((r for r in orows if r[0] == ex["bar"][0]), None)
                                        if obar_out is None:
                                            continue
                                        epx, xpx = worst_fills("LONG", obar_in, obar_out)
                                        mfe, mae = excursion(orows, "LONG", epx, obar_in[0], obar_out[0])
                                        qty = contract["lot_size"]
                                        trades.append(make_trade(
                                            day=d, side="LONG", symbol=contract["trading_symbol"],
                                            entry_time=obar_in[0], entry_px=epx,
                                            exit_time=obar_out[0], exit_px=xpx, qty=qty,
                                            exit_reason=ex["reason"], capital=epx * qty,
                                            expiry=contract["expiry"], option_type=opt_type,
                                            mfe=mfe, mae=mae,
                                            variant={"tf": f"{tf}m", "rr": f"1:{rr}", "confirm": confirm,
                                                     "stop_mode": stop_mode, "eod": eod, "book": book},
                                            tags={"direction": "short (buy PE)" if sig["dir"] == "short" else "long (buy CE)",
                                                  "delay": f"{sig['k']} candles",
                                                  "poc": ("below POC" if c[4] < poc else "above POC")},
                                            levels=[{"name": "VAH", "price": vah}, {"name": "VAL", "price": val},
                                                    {"name": "POC", "price": poc},
                                                    {"name": "index stop", "price": sim["stop"]},
                                                    {"name": "index target", "price": sim["target"]}],
                                            note=f"{tf}m {confirm}: arm {cs[sig['arm']][0]}, retest {c[0]} "
                                                 f"({sig['k']} candles later); stop {stop_mode}, eod {eod}; "
                                                 f"index ref {sim['ref']:.2f}, risk {sim['risk']:.2f}"))
                                        if (tf == 3 and confirm == RULE["confirm"]
                                                and stop_mode == RULE["stop_mode"]
                                                and eod == RULE["eod"] and book == RULE["book"]):
                                            opt_sessions.setdefault(contract["trading_symbol"], {})[d] = orows
                                        if book == "session":
                                            break
                                        busy_until = ex["bar"][0]

    print(f"\n{len(skips)} skips:")
    for s in skips:
        print("  ", s)

    meta = {
        "rejected": [
            ["Entering at the confirming candle's own close",
             "the source offers it, but a signal read from a candle can only be acted on in the "
             "next bar (rule 2); taking the close of the candle that produced the signal is a "
             "price you could not have had. Only 'open of the next candle' is simulated."],
            ["Which previous close defines the level",
             "the source sweeps the 15:29 print against the official settlement close; this rule "
             "builds the band from the previous session's profile and never reads its close, so "
             "the axis does not apply."],
        ],
        "title": "Volume Profile Range v3 - value-area re-entry",
        "subtitle": "NIFTY previous-session value area; re-entry then held retest; buy ATM PE (short) / CE (long)",
        "instrument": "NIFTY 50 options (signal on the index)",
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": trades[0]["qty"] if trades else None,
        "fill_rule": "Every buy at the bar's high, every sell at the bar's low; signals acted on in the next "
                     "1-minute bar; stop/target touches exit in the next 1-minute bar; 15:15 exit in its own bar.",
        "cost_model": "Standard option schedule (Upstox flat brokerage, STT, exchange, SEBI, stamp, GST).",
        "params": {"timeframes": "3m, 5m", "profile": "previous session, 5m, TPO, 1-pt bins, 70% value area",
                   "retest window": f"{RETEST_MIN}-{RETEST_MAX} candles after arming",
                   "stop": f"{STOP_BUFFER:g} pts beyond VAH/VAL", "targets": "1:2, 1:3, 1:4",
                   "square-off": SQUARE_OFF, "strike": "ATM", "lots": 1},
        "rule_steps": [
            "1. Previous session's 5-minute time-weighted profile gives POC, VAH, VAL for today.",
            "2. Re-entry = the candle before closed outside the band and the arming candle closes back inside.",
            "3. Close above VAH then a close back below it arms a short (buy PE).",
            "4. Close below VAL then a close back above it arms a long (buy CE).",
            "5. 4 to 7 candles later a candle must touch the band from inside and close back inside value.",
            "6. Entry in the next 1-minute bar after that confirming candle completes (option bought at its high).",
            "7. Index stop 25 points beyond VAH (short) / VAL (long).",
            "8. Risk = index entry reference to stop; target 2x (also 1:3, 1:4) risk on the index.",
            "9. Exits walked on 1-minute index bars: square-off, then stop, then target; option sold in the next bar's low.",
            "10. One trade a day per timeframe; square off at 15:15.",
            "11. Signals on 3-minute and 5-minute candles."],
        "limits": [
            "ASSUMED: traded instrument is ATM NIFTY options (short setup -> buy PE, long -> buy CE), 1 lot, "
            "nearest expiry at least 1 day after the trade day; the prompt names no instrument.",
            "ASSUMED: profile details - 1-point bins, TPO time-weighting, 70% value area, POC tie by mid-range, "
            "VAL/VAH as bin edges.",
            "ASSUMED: 'back inside' / 'holds' use strict closes; no invalidation between arm and retest; "
            "first candle of a day has no candle before; earliest retest wins.",
            "ASSUMED: risk and target measured from the entry bar's index worst-fill reference "
            "(long: bar high, short: bar low); stop/target tested on index levels, option exits next bar.",
            "ASSUMED: 'opening on 5-minute' read as 5m being the primary timeframe; both are shown as the tf filter.",
            "Prompt conflicts overridden by the Rules: entry at the open of the next candle -> option bought at the "
            "next 1-minute bar's high; stop/target at the level -> exit in the next bar at the worst price.",
            "Capital is premium x qty (bought option).",
            "In-sample: tf x rr x signal are all shown, none chosen; the window is short and the short-side "
            "sample is small - the prompt itself warns about ~21 trades and same-side control comparison, "
            "which this report does not include.",
            f"Skipped setups/days: {len(skips)} (listed on the console)."],
        "coverage": coverage(sessions_from_window(sessions, days), frm, to, SESSION_ROWS),
    }
    groups = [{"name": "Direction", "keys": ["direction"]},
              {"name": "Retest delay", "keys": ["delay"]},
              {"name": "Direction x delay", "keys": ["direction", "delay"]},
              {"name": "Entry vs POC", "keys": ["poc"]}]
    if not trades:
        print("0 trades - no report written")
        return
    payload = build_payload(meta, trades, sessions, opt_sessions, groups,
                            settings=SETTINGS, chart="default")
    path = write_report(payload, "vpr_v3")
    print(console_summary(trades))
    print(path)


def sessions_from_window(sessions: dict, days: list[str]) -> dict:
    return {d: sessions[d] for d in days}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="VPR v3 value-area re-entry backtest")
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat())
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    SETTINGS[:] = narrow(SETTINGS, a)
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    check_window(frm, to)
    print(f"axes: {len(combos(SETTINGS))} simulated combinations "
          f"(confirmation x timeframe x R:R x stop anchor x end-of-day x position rule)")
    asyncio.run(main(frm, to))
