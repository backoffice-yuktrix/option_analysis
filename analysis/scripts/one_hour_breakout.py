"""One hour breakout (first hour favour) - NIFTY spot signals, ATM option bought.

STRATEGY PROMPT (verbatim summary of steps)
  Step 1  First hour = 09:15-10:14. Closes above its open (green) -> arm LONG; below (red) -> arm SHORT;
          exactly at its open -> nothing, day skipped.
  Step 2  Take the first hour's HIGH and LOW.
  Step 3  Scan forward from 10:15 for the first candle whose CLOSE is above the first-hour high (long) or
          below its low (short). That is the trigger candle (a scan, not just the next candle).
  Step 4  Stop scanning at 14:00. A later breakout is not taken.
  Step 5  Entry is the OPEN of the candle after the trigger candle.
  Step 6  Stop = trigger candle's LOW (long) / HIGH (short).
  Step 7  Stop is close-confirmed: closed only when a later candle CLOSES beyond that level, filled at that
          candle's close; slippage past the level is recorded. A resting order at the level is computed beside it.
  Step 8  Risk = entry-to-stop distance; target = entry +/- risk x 2; also score 1, 3, 4 and 5.
  Step 9  Run the whole rule on 1, 3, 5 and 15-minute candles, opening on 15-minute. First hour is 09:15-10:14
          on all; trigger and stop-confirm use the SAME timeframe; each timeframe is a standalone strategy.
          Buckets anchored at 09:15.
  Step 10 Square off anything still open at 15:25.
  Step 11 Decide everything on spot first (first hour, breakout, stop, target), then resolve the option those
          signals imply. Green first hour buys the CE, red the PE.

RUN.md STEP 1 CHECKLIST
  1 Underlying         clear    NIFTY 50 index (spot signals)
  2 Window             assumed  prompt gives none -> last 6 months ending yesterday (--from/--to)
  3 Signal timeframe   clear    1m, 3m, 5m, 15m (each a standalone strategy; built from 1m, anchored 09:15)
  4 Signal rule        clear    numbers/definitions given (first hour 09:15-10:14, close beyond hi/lo, 10:15-14:00)
  5 Decision time      clear    the trigger candle's completion; act in the next 1m bar (rule 2)
  6 Direction          clear    green -> buy CE, red -> buy PE
  7 Traded instrument  clear    NIFTY weekly/monthly option (bought)
  8 Option specifics   assumed  buy; strike ATM at the trigger candle's close (prompt gives no strike);
                               expiry nearest >= 1 day after the day; 1 lot
  9 Entry              clear    next 1m bar after the trigger candle (rule 2), worst fill
  10 Exit              clear    target (R x 1..5 on spot), stop (close-confirmed or resting, on spot), 15:25 time exit
  11 Holding           clear    intraday
  12 Costs             assumed  standard option schedule (py_funcs.option_costs)
  13 Position rules    assumed  one trade per day per (timeframe, R, stop-reading) variant; no re-entry after a stop
  14 Missing data      assumed  skip and list
  15 Filters           clear    timeframe (1/3/5/15m) x R:R (1..5) x stop reading (close-confirmed / resting) x side
  16 Custom group-bys  assumed  prompt names none; added: direction, breakout delay, first-hour range, stop slippage
  17 Script name       one_hour_breakout

ASSUMED (also in meta["limits"])
  A1  Window: last 6 months ending yesterday.
  A2  Strike = ATM (nearest strike step, step read from the live Upstox chain) at the TRIGGER candle's close.
  A3  Expiry = nearest at least 1 day after the trade day (rule 10); lots = 1; qty from the contract lot size.
  A4  "Stop scanning at 14:00": the trigger candle must be COMPLETE by 14:00 (its entry bar is then <= 14:00).
  A5  The option is always LONG (bought): the spot direction only picks CE/PE. Stop/target/first-hour levels are
      SPOT levels (drawn on the index chart); they are not option prices.
  A6  Target and resting-stop touches are detected on 1-minute spot bars (any 1m bar touching the level),
      whatever the signal timeframe; the close-confirmed stop is tested on the signal timeframe's candles.
  A7  A stop/target touched inside the entry bar itself is treated like any other bar (exit in the next bar).
  A8  Close-confirmed stop: a "later candle" is a signal-timeframe candle starting at/after the trigger candle's
      end (so the entry candle is the first one that can confirm). "Beyond" = strictly beyond the level.
  A9  If a target touch and a close-confirmed stop complete in the same minute, the stop is assumed first.
  A10 Group-by buckets (breakout delay 30/90 min; first-hour range 0.4%/0.7% of open; slippage 0.25/0.5/1 R)
      are my own edges, chosen without looking at results.
  A11 The report opens with all variants; the prompt's "opening on 15-minute" is not preselectable, use the tf filter.
  A12 Only days with a complete 375-bar spot session AND a complete 60-bar first hour are used.

CONFLICTS WITH THE RULES TO LIVE BY (rules win)
  * Step 5 "entry is the OPEN of the candle after the trigger": entry is the next 1m bar after the trigger candle
    completes, and the OPTION is bought at that bar's HIGH (rule 1/2). The spot open still defines risk/target.
  * Step 7 "fill is that candle's close": the confirming candle is complete at its end, the exit is the option's
    SELL at the LOW of the next 1m bar (rules 1, 2, 3). Slippage is still measured on spot vs the level.
  * Resting stop "at the level" / target "at the level": touched inside a bar -> exit in the NEXT 1m bar, option sold
    at that bar's low (rule 3); stop first on ties.
  * Step 10 15:25 square-off fills in the 15:25 bar itself (scheduled exit), at the bar's low.
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: E402,F401,F403

SLUG = "one_hour_breakout"
TIMEFRAMES = [1, 3, 5, 15]
RRS = [1, 2, 3, 4, 5]
STOP_MODES = ["close-confirmed", "resting"]
FIRST_HOUR_START, FIRST_HOUR_END = "09:15", "10:14"
SCAN_FROM, SCAN_TO = "10:15", "14:00"
SQUARE_OFF = "15:25"
SESSION_BARS = 375


def add_min(hhmm: str, m: int) -> str:
    t = hhmm_minutes(hhmm) + m
    return f"{t // 60:02d}:{t % 60:02d}"


# ---------------------------------------------------------------------------
# fetch (spot)
# ---------------------------------------------------------------------------
async def fetch_spot(up: Upstox, frm: date, to: date):
    und = await up.find_instrument("NIFTY")
    info = await up.option_chain_info(und["instrument_key"])
    expiries = await up.expiry_calendar(und["instrument_key"], frm, to)
    cs = await up.candles(und["instrument_key"], "1m", frm, to)
    return und, info, expiries, sessions_from(cs)


# ---------------------------------------------------------------------------
# signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def day_ok(rows: list[list]) -> str | None:
    """None when the session is usable, else the reason."""
    keys = [r[0] for r in rows]
    if len(rows) != SESSION_BARS or len(set(keys)) != len(keys):
        return f"session has {len(rows)} bars / {len(set(keys))} unique (need {SESSION_BARS})"
    fh = [r for r in rows if FIRST_HOUR_START <= r[0] <= FIRST_HOUR_END]
    if len(fh) != 60:
        return f"first hour has {len(fh)} bars (need 60)"
    return None


def first_hour(rows: list[list]) -> dict | str:
    fh = [r for r in rows if FIRST_HOUR_START <= r[0] <= FIRST_HOUR_END]
    o, c = fh[0][1], fh[-1][4]
    if c == o:
        return "first hour closed exactly at its open"
    return {"open": o, "close": c, "high": max(r[2] for r in fh), "low": min(r[3] for r in fh),
            "side": "LONG" if c > o else "SHORT"}


def find_trigger(rows: list[list], tf: int, fh: dict) -> dict | str:
    """First tf-candle (start >= 10:15, complete by 14:00) whose CLOSE is beyond the first-hour range."""
    for c in resample(rows, tf):
        if c[0] < SCAN_FROM:
            continue
        if candle_done_at(c[0], tf) > SCAN_TO:
            break
        beyond = c[4] > fh["high"] if fh["side"] == "LONG" else c[4] < fh["low"]
        if beyond:
            stop = c[3] if fh["side"] == "LONG" else c[2]
            return {"candle": c, "start": c[0], "done": candle_done_at(c[0], tf), "stop": stop}
    return f"no {'upside' if fh['side'] == 'LONG' else 'downside'} breakout close before {SCAN_TO}"


# ---------------------------------------------------------------------------
# simulate (pure): spot levels -> exit minute
# ---------------------------------------------------------------------------
def prev_min(hhmm: str) -> str:
    return add_min(hhmm, -1)


def spot_exit(rows: list[list], tf: int, side: str, entry_key: str, stop: float, target: float,
              mode: str) -> dict:
    """Which 1m bar the option must be sold in.  side = SPOT direction (LONG/SHORT).
    Returns {"key", "reason", "slip"(spot pts beyond the stop level, close-confirmed only)}."""
    ek = prev_min(entry_key)                       # include the entry bar itself (A7)
    if mode == "resting":
        r = scan_exit(rows, side, ek, stop=stop, target=target, force_key=SQUARE_OFF)
        if r["bar"] is None:
            return {"key": None, "reason": r["reason"]}
        return {"key": r["bar"][0], "reason": r["reason"], "slip": None}
    # close-confirmed stop: target through scan_exit, stop from completed tf candles' closes
    tg = scan_exit(rows, side, ek, stop=None, target=target, force_key=SQUARE_OFF)
    if tg["bar"] is None:
        return {"key": None, "reason": tg["reason"]}
    best = {"key": tg["bar"][0], "reason": tg["reason"], "slip": None}
    for c in resample(rows, tf):
        if c[0] < entry_key:             # only candles starting at/after the trigger's end
            continue
        done = candle_done_at(c[0], tf)
        if done > best["key"]:
            break
        beyond = c[4] < stop if side == "LONG" else c[4] > stop
        if beyond:                                   # tie with target/time exit -> stop first
            slip = (stop - c[4]) if side == "LONG" else (c[4] - stop)
            best = {"key": done, "reason": "stop", "slip": slip}
            break
    return best


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def default_window() -> tuple[date, date]:
    now = datetime.now(IST)
    to = now.date() - timedelta(days=1)
    return to - timedelta(days=182), to


async def run(frm: date, to: date) -> None:
    now = datetime.now(IST)
    if to >= now.date() and now.strftime("%H:%M") < "15:45":      # rule 7: today is not complete yet
        to = now.date() - timedelta(days=1)
        print(f"  today's session is not complete; window ends {to}")
    skipped: list[str] = []
    trades: list[dict] = []
    opt_sessions: dict[str, dict[str, list]] = {}
    async with Upstox() as up:
        und, info, expiries, spot = await fetch_spot(up, frm, to)
        step = info["strike_step"]
        if not step:
            raise SystemExit("could not read the strike step from Upstox")
        print(f"NIFTY key {und['instrument_key']}, strike step {step}, {len(spot)} sessions {frm}..{to}")
        cov = coverage(spot, frm, to, SESSION_BARS)
        for d in cov["weekday_gaps"]:
            print(f"SKIP {d}: no spot candles (holiday or feed gap)")
        opt_bars: dict[tuple[str, str], list] = {}
        contracts: dict[tuple, dict | None] = {}

        for day, rows in spot.items():
            bad = day_ok(rows)
            if bad:
                print(f"SKIP {day}: {bad}")
                skipped.append(day)
                continue
            fh = first_hour(rows)
            if isinstance(fh, str):
                print(f"SKIP {day}: {fh}")
                skipped.append(day)
                continue
            d0 = date.fromisoformat(day)
            opt_type = "CE" if fh["side"] == "LONG" else "PE"
            expiry = next_expiry(expiries, d0, 1)
            if expiry is None:
                print(f"SKIP {day}: no expiry at least 1 day after the day")
                continue
            rng_pct = (fh["high"] - fh["low"]) / fh["open"] * 100
            for tf in TIMEFRAMES:
                trig = find_trigger(rows, tf, fh)
                if isinstance(trig, str):
                    print(f"SKIP {day} {tf}m: {trig}")
                    continue
                ebar = bar_after_candle(rows, trig["start"], tf)
                if ebar is None:
                    print(f"SKIP {day} {tf}m: no 1m bar at {trig['done']} for the entry")
                    continue
                entry_spot, stop = ebar[1], trig["stop"]        # spot open of the candle after the trigger
                risk = abs(entry_spot - stop)
                if risk <= 0:
                    print(f"SKIP {day} {tf}m: entry {entry_spot} not beyond stop {stop}")
                    continue
                strike = atm_strike(trig["candle"][4], step)
                ck = (expiry, strike, opt_type)
                if ck not in contracts:
                    contracts[ck] = await up.resolve_option(und["instrument_key"], expiry, strike, opt_type)
                con = contracts[ck]
                if not con or not con["lot_size"]:
                    print(f"SKIP {day} {tf}m: no option contract {expiry} {strike} {opt_type}")
                    continue
                bk = (con["instrument_key"], day)
                if bk not in opt_bars:
                    opt_bars[bk] = await up.option_candles(con, d0)
                obars = opt_bars[bk]
                oby = {r[0]: r for r in obars}
                if len(oby) != len(obars):
                    print(f"SKIP {day} {tf}m: duplicated option bars for {con['trading_symbol']}")
                    continue
                oe = oby.get(ebar[0])
                if oe is None:
                    print(f"SKIP {day} {tf}m: no option bar at {ebar[0]} for {con['trading_symbol']}")
                    continue
                opt_sessions.setdefault(con["trading_symbol"], {})[day] = obars
                qty = con["lot_size"]                                   # 1 lot
                delay = hhmm_minutes(trig["done"]) - hhmm_minutes(SCAN_FROM)
                sgn = 1 if fh["side"] == "LONG" else -1
                for rr in RRS:
                    target = entry_spot + sgn * risk * rr
                    for mode in STOP_MODES:
                        ex = spot_exit(rows, tf, fh["side"], ebar[0], stop, target, mode)
                        tag = f"{day} {tf}m {rr}R {mode}"
                        if ex["key"] is None:
                            print(f"SKIP {tag}: {ex['reason']}")
                            continue
                        ox = oby.get(ex["key"])
                        if ox is None:
                            print(f"SKIP {tag}: no option bar at exit {ex['key']}")
                            continue
                        epx, xpx = worst_fills("LONG", oe, ox)
                        if not epx or not xpx:
                            print(f"SKIP {tag}: zero option price")
                            continue
                        slip_r = None if ex.get("slip") is None else ex["slip"] / risk
                        xs = next((r for r in rows if r[0] == ex["key"]), None)
                        mfe, mae = excursion(obars, "LONG", epx, ebar[0], ex["key"])
                        lv_to = SQUARE_OFF
                        levels = [
                            {"name": "first-hour high", "price": fh["high"], "from": "09:15", "to": lv_to},
                            {"name": "first-hour low", "price": fh["low"], "from": "09:15", "to": lv_to},
                            {"name": "stop (spot)", "price": stop, "from": ebar[0], "to": lv_to},
                            {"name": f"target {rr}R (spot)", "price": target, "from": ebar[0], "to": lv_to},
                        ]
                        trades.append(make_trade(
                            day=day, side="LONG", symbol=con["trading_symbol"], entry_time=ebar[0], entry_px=epx,
                            exit_time=ex["key"], exit_px=xpx, qty=qty, exit_reason=ex["reason"],
                            capital=epx * qty, entry_spot=ebar[1], exit_spot=xs[1] if xs else None,
                            mfe=mfe, mae=mae, expiry=con["expiry"], option_type=opt_type,
                            variant={"tf": f"{tf}m", "rr": f"{rr}R", "stop": mode},
                            tags={"direction": "green -> CE" if opt_type == "CE" else "red -> PE",
                                  "breakout delay": bucket(delay, [30, 90], ["under 30 min", "30-90 min", "over 90 min"]),
                                  "first-hour range": bucket(rng_pct, [0.4, 0.7], ["under 0.4%", "0.4-0.7%", "over 0.7%"]),
                                  "stop slippage": "n/a" if slip_r is None else
                                  bucket(slip_r, [0.25, 0.5, 1.0], ["under 0.25R", "0.25-0.5R", "0.5-1R", "over 1R"])},
                            levels=levels,
                            note=(f"{fh['side']} first hour {fh['open']:.2f}->{fh['close']:.2f}; trigger {tf}m candle "
                                  f"{trig['start']} close {trig['candle'][4]:.2f}; spot entry {entry_spot:.2f}, stop "
                                  f"{stop:.2f}, target {target:.2f}"
                                  + ("" if slip_r is None else f"; stop slippage {ex['slip']:.2f} pts = {slip_r:.2f}R"))))

    meta = {
        "title": "One hour breakout - first hour favour",
        "subtitle": "NIFTY spot first-hour colour + range breakout, ATM option bought; 1/3/5/15m x R 1-5 x two stop readings",
        "instrument": "NIFTY 50 (spot signals), ATM NIFTY option bought",
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": "from each contract (1 lot)",
        "fill_rule": "Every buy at the 1m bar's HIGH, every sell at its LOW; signals act in the next 1m bar",
        "cost_model": "Upstox option schedule (brokerage, STT, exchange, SEBI, stamp, GST)",
        "params": {"timeframes": "1m, 3m, 5m, 15m", "first hour": "09:15-10:14", "scan": f"{SCAN_FROM}-{SCAN_TO}",
                   "R:R": "1, 2, 3, 4, 5", "stop": "close-confirmed / resting (spot)", "square off": SQUARE_OFF,
                   "strike": "ATM at trigger close", "expiry": ">= 1 day after trade day", "lots": 1},
        "rule_steps": [
            "First hour 09:15-10:14: green arms LONG (buy CE), red arms SHORT (buy PE), flat skips the day.",
            "Take the first hour's high and low.",
            f"From {SCAN_FROM}, on the chosen timeframe, the first candle whose close is beyond the range is the trigger; candle must complete by {SCAN_TO}.",
            "Act in the next 1m bar after the trigger candle completes: buy the ATM option at that bar's HIGH.",
            "Spot stop = trigger candle low (long) / high (short); risk = spot entry (open of that bar) to stop; target = entry +/- R x risk, R in 1..5.",
            "Close-confirmed stop: exit when a later same-timeframe candle closes beyond the level; resting stop: exit when any 1m bar touches it. Both exit in the NEXT 1m bar at its LOW (option sold).",
            "Target touched in a 1m bar exits in the next 1m bar; stop first if both in one bar.",
            f"Square off at {SQUARE_OFF} (fills in that bar).",
            "One trade per day per variant (timeframe x R x stop reading); each timeframe is a standalone strategy.",
        ],
        "limits": [
            "ASSUMED: window = last 6 months ending yesterday.",
            "ASSUMED: strike = ATM at the trigger candle's close (strike step from the live Upstox chain); expiry >= 1 day after the trade day; 1 lot.",
            "ASSUMED: 'stop scanning at 14:00' = trigger candle complete by 14:00.",
            "ASSUMED: stop/target/first-hour levels are SPOT levels; the option is always bought (LONG); they are not option prices.",
            "ASSUMED: target and resting-stop touches are read from 1m spot bars for every timeframe; close-confirmed stop from signal-timeframe candle closes.",
            "ASSUMED: a later candle for the close-confirmed stop = a candle starting at/after the trigger candle's end; ties -> stop first.",
            "ASSUMED: group-by bucket edges (delay 30/90 min, first-hour range 0.4/0.7%, slippage 0.25/0.5/1R) are mine.",
            "Prompt fills (entry at open, stop fill at the candle close, fills at the level) are replaced by the worst-fill, next-bar rules; results are therefore worse than the prompt's own numbers.",
            "The 10 variants (R x stop reading) per timeframe are the SAME day's signal scored different ways, not independent samples; compare them, do not add them.",
            "No parameter was selected on this window, but all variants are shown; the report is still a single in-sample window in one market regime.",
            "Every run refetches everything; days with missing/duplicate bars, short sessions or missing option bars are skipped and printed.",
        ],
        "coverage": cov,
    }
    groups = [{"name": "Direction", "keys": ["direction"]},
              {"name": "Breakout delay", "keys": ["breakout delay"]},
              {"name": "First-hour range", "keys": ["first-hour range"]},
              {"name": "Stop slippage (close-confirmed stops)", "keys": ["stop slippage"]}]
    if not trades:
        print("no trades")
        print(console_summary(trades))
        return
    payload = build_payload(meta, trades, spot, opt_sessions, groups)
    path = write_report(payload, SLUG)
    print(f"{len(skipped)} whole days skipped (listed above)")
    print(console_summary(trades))
    print(path)


def main() -> None:
    d_from, d_to = default_window()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="frm", default=d_from.isoformat(), help="YYYY-MM-DD (default: 6 months ago)")
    ap.add_argument("--to", dest="to", default=d_to.isoformat(), help="YYYY-MM-DD (default: yesterday)")
    a = ap.parse_args()
    asyncio.run(run(date.fromisoformat(a.frm), date.fromisoformat(a.to)))


if __name__ == "__main__":
    main()
