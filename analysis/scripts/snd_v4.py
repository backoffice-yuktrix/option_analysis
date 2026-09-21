"""Supply and Demand - v4  (snd_v4)

STRATEGY PROMPT (verbatim)
--------------------------
v4 SnD
### v4 - v3's entry, a flat 100-point stop and a trail

WHAT CHANGED FROM v3
* The entry is v3's, unchanged: the close of the candle that touches the zone, no new entry from 13:00.
* The stop is no longer the zone edge. It is a flat 100 points from the entry, sent as a market order,
  so the fill is the print at the minute the level trades and not the level itself - a loss is not capped
  at the level.
* Because the stop is the same distance every time, risk is the same number on every trade.
* There is no fixed target any more. A trail replaces it.
* The trail arms at +40 points and sits 30 points behind the best price.
* The report also shows that trail capped at the opposing liquidity, and R-multiple caps can be switched
  on, but neither is the rule.
* A re-entry after a stop was built and is switched OFF.

Step 1 - A swing high is a candle whose high is higher than the 3 highs before it and the 3 highs after it,
and a swing low is the opposite; a swing only counts once 3 candles have closed after it.
Step 2 - The first candle of the day that CLOSES beyond the most recent confirmed swing sets the direction:
closing above a swing high makes it bullish, closing below a swing low makes it bearish. A wick through is
not a break; only the first break of the day counts.
Step 3 - The zone is the last opposite-coloured candle in the 3 candles before the break (last red before a
bullish break, last green before a bearish break), its full range low to high. Bullish break = demand zone,
bearish break = supply zone. If none of those 3 candles is the opposite colour there is no zone and the day
is over.
Step 4 - Wait for price to come back and touch the zone: the candle's low is at or below the zone high and
its high is at or above the zone low.
Step 5 - The touch is the entry: buy at that candle's close in a demand zone, sell at its close in a supply
zone. No new entry at or after 13:00.
Step 6 - The stop is 100 points below the entry for a long and 100 points above it for a short. Market order.
Step 7 - Risk is 100 points on every trade, by construction.
Step 8 - No fixed target. Once the trade is 40 points in my favour, start trailing a stop 30 points behind
the best price the trade has seen, and move it only in my favour.
Step 9 - Update that trail on completed 1-minute candles, not on ticks.
Step 10 - The setup dies if any candle CLOSES more than 4 zone widths past the far edge of the zone; check
that before the touch test on every candle.
Step 11 - One trade a day at most; once I am in, the zone dying no longer matters.
Step 12 - Square off anything still open at 15:15.
Step 13 - 3-minute candles by default, 1-minute alongside.

RUN.md STEP 1 CHECKLIST  (non-interactive run: every gap closed with a default / simplest reading = ASSUMED)
--------------------------------------------------------------------------------------------------------
 1 Underlying        ASSUMED  NIFTY 50 index (prompt names none). Signals are read from the index.
 2 Window            ASSUMED  last 6 months ending yesterday (--from / --to).
 3 Signal timeframe  clear    3-minute (default) and 1-minute, built from 1-minute data. Variant filter tf.
 4 Signal rule       clear    swing = 3 left / 3 right strict highs/lows; break = close beyond latest swing.
                     ASSUMED  - swings are computed on the same day's candles only (no carry-over from prior day)
                                so the first possible break is candle index 7.
                     ASSUMED  - "confirmed" = the swing candle s is usable for candle i only if s+3 <= i-1 (the 3
                                confirming candles have all closed before the breaking candle i).
                     ASSUMED  - "most recent swing" is taken separately per side: latest confirmed swing high for a
                                bullish break, latest confirmed swing low for a bearish break.
                     ASSUMED  - red = close < open, green = close > open (a doji is neither).
                     ASSUMED  - "far edge" (step 10) = the edge on the breakout side: zone high for demand, zone
                                low for supply; the setup dies if a close is > 4 x zone width beyond it.
                     ASSUMED  - after the break, the touch/death tests start with the candle after the break candle.
 5 Decision time     clear    the close of the candle that touches the zone; no entry when that candle completes
                              at or after 13:00 (ASSUMED reading of "no new entry at or after 13:00").
 6 Direction         ASSUMED  demand zone = bullish = buy a CE; supply zone = bearish = buy a PE. The trade is
                              always LONG the option (tag `direction` = demand / supply).
 7 Traded instrument ASSUMED  NIFTY option (the index itself cannot be traded and no cost schedule is given).
 8 Option specifics  ASSUMED  buy ATM (nearest strike to the signal candle's close, strike step read from Upstox),
                              nearest expiry at least 1 day after the trade day, 1 lot (qty = lot_size of the
                              resolved contract).
 9 Entry             clear    the touch candle's signal; filled per rules 1-2 (see conflicts).
10 Exit              clear    initial stop = 100 index points from the reference entry price; trail arms at +40
                              and sits 30 behind the best price; 15:15 time exit; no target. ASSUMED: all of these
                              are measured on the NIFTY INDEX level (1-minute candles), while the fills are on the
                              option's bars. The reference "entry" price for stop/trail is the signal candle's close.
                              The trail is updated from completed 1-minute candles AFTER the entry bar; a stop check
                              on a bar uses the stop in force before that bar's own update (conservative).
                              Stop check starts with the entry bar itself (conservative).
11 Holding period    clear    intraday (15:15 square-off).
12 Costs             ASSUMED  standard option schedule (py_funcs.option_costs).
13 Position rules    clear    one trade a day per timeframe variant; no re-entry (switched OFF in the prompt).
14 Missing data      ASSUMED  skip the day / trade and print it (default).
15 Filters           clear    tf = 3m / 1m (variant) and side (always LONG on the option).
                     Not built (the prompt says they are not the rule): opposing-liquidity trail cap, R caps,
                     re-entry. Slippage number is not recorded separately: fills already use the worst-fill rule.
16 Custom group-bys  ASSUMED  none requested; one added: direction at entry (demand / supply).
17 Script name       snd_v4

Capital = premium x qty (bought option). Selection: no parameter was searched by this script (the prompt's
numbers 100/40/30 were chosen by its author on the same history, so results are in-sample).
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: F401,F403,E402

REPORT_NAME = "snd_v4"
SESSION_ROWS = 375
SWING_N = 3
STOP_PTS = 100.0
ARM_PTS = 40.0
TRAIL_PTS = 30.0
DEATH_WIDTHS = 4.0
NO_ENTRY_FROM = "13:00"
SQUARE_OFF = "15:15"
TIMEFRAMES = [3, 1]                  # minutes; 3m is the default, 1m alongside

_EXPECTED = None


def expected_minutes() -> list[str]:
    return [f"{m // 60:02d}:{m % 60:02d}" for m in range(9 * 60 + 15, 15 * 60 + 30)]


# ---------------------------------------------------------------------------
# signal: pure, completed candles only
# ---------------------------------------------------------------------------
def is_swing_high(c: list[list], s: int) -> bool:
    if s < SWING_N or s + SWING_N >= len(c):
        return False
    h = c[s][2]
    return all(h > c[k][2] for k in list(range(s - SWING_N, s)) + list(range(s + 1, s + SWING_N + 1)))


def is_swing_low(c: list[list], s: int) -> bool:
    if s < SWING_N or s + SWING_N >= len(c):
        return False
    lo = c[s][3]
    return all(lo < c[k][3] for k in list(range(s - SWING_N, s)) + list(range(s + 1, s + SWING_N + 1)))


def latest_confirmed(c: list[list], i: int, side: str) -> int | None:
    """Index of the latest swing usable at candle i (its 3 confirming candles closed before i)."""
    test = is_swing_high if side == "high" else is_swing_low
    for s in range(i - SWING_N - 1, SWING_N - 1, -1):
        if test(c, s):
            return s
    return None


def find_setup(c: list[list], tf: int) -> tuple[dict | None, str]:
    """Steps 1-5 and 10-11 on the tf-minute candles of ONE day.  Returns (setup, reason).
    setup: direction, signal candle index/start, break index, zone_lo, zone_hi, level."""
    brk = None
    for i in range(len(c)):
        sh, sl = latest_confirmed(c, i, "high"), latest_confirmed(c, i, "low")
        if sh is not None and c[i][4] > c[sh][2]:
            brk = (i, "demand", c[sh][2], c[sh][0])
            break
        if sl is not None and c[i][4] < c[sl][3]:
            brk = (i, "supply", c[sl][3], c[sl][0])
            break
    if brk is None:
        return None, "no candle closed beyond a confirmed swing"
    i, direction, level, level_t = brk
    zone = None
    for k in range(i - 1, max(i - 4, -1), -1):                  # last opposite candle of the 3 before
        red, green = c[k][4] < c[k][1], c[k][4] > c[k][1]
        if (direction == "demand" and red) or (direction == "supply" and green):
            zone = c[k]
            break
    if zone is None:
        return None, f"{direction} break at {c[i][0]} but no opposite-coloured candle in the 3 before it: no zone"
    zlo, zhi = zone[3], zone[2]
    width = zhi - zlo
    for j in range(i + 1, len(c)):
        cl = c[j][4]
        if (direction == "demand" and cl > zhi + DEATH_WIDTHS * width) or \
           (direction == "supply" and cl < zlo - DEATH_WIDTHS * width):
            return None, f"{direction} zone {zlo:.2f}-{zhi:.2f} died at {c[j][0]} (close {DEATH_WIDTHS:g} widths past the far edge)"
        if c[j][3] <= zhi and c[j][2] >= zlo:                   # touch
            done = candle_done_at(c[j][0], tf)
            if done >= NO_ENTRY_FROM:
                return None, f"{direction} zone first touched at {c[j][0]} (completes {done}): no entry from {NO_ENTRY_FROM}"
            return {"direction": direction, "zone_lo": zlo, "zone_hi": zhi, "zone_t": zone[0],
                    "break_t": c[i][0], "level": level, "level_t": level_t,
                    "signal_start": c[j][0], "signal_close": c[j][4], "tf": tf}, ""
        if candle_done_at(c[j][0], tf) >= NO_ENTRY_FROM:
            return None, f"{direction} zone {zlo:.2f}-{zhi:.2f} not touched before {NO_ENTRY_FROM}"
    return None, f"{direction} zone {zlo:.2f}-{zhi:.2f} never touched"


# ---------------------------------------------------------------------------
# simulate: pure - index 1-minute bars -> exit trigger; option bars -> fills
# ---------------------------------------------------------------------------
def scan_index(rows_1m: list[list], long_: bool, entry_t: str, ref: float) -> dict | None:
    """Walk the INDEX 1-minute bars from the entry bar on.  Stop = ref -/+ 100; once the best price is
    40 in favour the stop trails 30 behind it (only in favour).  A touch inside a completed bar is a
    signal, acted on in the NEXT bar; a bar's own high/low updates the trail only after that bar's stop
    check (conservative); the entry bar checks the stop but does not feed the trail.  15:15 = time exit
    in that bar.  Returns {exit_t, reason, trigger_t, stop0, stop, armed_at} or None."""
    stop = stop0 = ref - STOP_PTS if long_ else ref + STOP_PTS
    best, armed, armed_at, pending, trig = ref, False, None, None, None
    for r in rows_1m:
        t = r[0]
        if t < entry_t:
            continue
        if pending:
            return {"exit_t": t, "reason": pending, "trigger_t": trig, "stop0": stop0, "stop": stop, "armed_at": armed_at}
        if t >= SQUARE_OFF:
            return {"exit_t": t, "reason": "time exit", "trigger_t": None, "stop0": stop0, "stop": stop, "armed_at": armed_at}
        if (r[3] <= stop) if long_ else (r[2] >= stop):
            pending, trig = ("trail" if armed else "stop"), t
            continue
        if t > entry_t:
            best = max(best, r[2]) if long_ else min(best, r[3])
            if abs(best - ref) >= ARM_PTS and (best > ref if long_ else best < ref):
                if not armed:
                    armed, armed_at = True, t
                new = best - TRAIL_PTS if long_ else best + TRAIL_PTS
                stop = max(stop, new) if long_ else min(stop, new)
    return None


def clean_rows(rows: list[list]) -> bool:
    ts = [r[0] for r in rows]
    return len(ts) == len(set(ts)) and all(r[2] >= max(r[1], r[4]) and r[3] <= min(r[1], r[4]) for r in rows)


# ---------------------------------------------------------------------------
async def main(frm: date, to: date) -> None:
    today = datetime.now(IST)
    if to >= today.date() and today.strftime("%H:%M") < "15:45":
        to = today.date() - timedelta(days=1)
        print(f"Today's session is not over: window ends {to}")
    skipped: list[str] = []
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list]] = {}
    opt_cache: dict[tuple, list] = {}
    contract_cache: dict[tuple, dict | None] = {}
    exp_ok = set(expected_minutes())

    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        step = info["strike_step"]
        expiries = await up.expiry_calendar(key, frm, to)
        print(f"{und['trading_symbol']} {key}: strike step {step}, {len(expiries)} expiries known")
        sessions_all = sessions_from(await up.candles(key, "1m", frm, to))
        sessions = {d: r for d, r in sessions_all.items() if frm.isoformat() <= d <= to.isoformat()}
        cov = coverage(sessions, frm, to, SESSION_ROWS)
        for d in cov["weekday_gaps"]:
            print(f"SKIP {d}: no index candles (holiday or feed gap)")
            skipped.append(f"{d}: no index candles")

        for day, rows in sessions.items():
            times = [r[0] for r in rows]
            if len(rows) != SESSION_ROWS or set(times) != exp_ok or len(set(times)) != len(times) or not clean_rows(rows):
                msg = f"{day}: invalid/short session ({len(rows)} bars)"
                print("SKIP " + msg); skipped.append(msg)
                continue
            d_ = date.fromisoformat(day)
            for tf in TIMEFRAMES:
                candles = rows if tf == 1 else resample(rows, tf)
                setup, why = find_setup(candles, tf)
                tag = f"{day} [{tf}m]"
                if setup is None:
                    print(f"SKIP {tag}: {why}"); skipped.append(f"{tag}: {why}")
                    continue
                long_ = setup["direction"] == "demand"
                otype = "CE" if long_ else "PE"
                ebar = bar_after_candle(rows, setup["signal_start"], tf)
                if ebar is None:
                    msg = f"{tag}: entry bar after {setup['signal_start']} missing"
                    print("SKIP " + msg); skipped.append(msg)
                    continue
                sc = scan_index(rows, long_, ebar[0], setup["signal_close"])
                if sc is None:
                    msg = f"{tag}: no exit found in the index bars"
                    print("SKIP " + msg); skipped.append(msg)
                    continue
                exp = next_expiry(expiries, d_, 1)
                if exp is None:
                    msg = f"{tag}: no expiry at least 1 day after {day}"
                    print("SKIP " + msg); skipped.append(msg)
                    continue
                strike = atm_strike(setup["signal_close"], step)
                ck = (exp, strike, otype)
                if ck not in contract_cache:
                    contract_cache[ck] = await up.resolve_option(key, exp, strike, otype)
                con = contract_cache[ck]
                if con is None or not con["lot_size"]:
                    msg = f"{tag}: contract {exp} {strike:g} {otype} not found"
                    print("SKIP " + msg); skipped.append(msg)
                    continue
                ok = (con["trading_symbol"], day)
                if ok not in opt_cache:
                    opt_cache[ok] = await up.option_candles(con, d_)
                orows = opt_cache[ok]
                if not orows or not clean_rows(orows):
                    msg = f"{tag}: option bars missing/invalid for {con['trading_symbol']}"
                    print("SKIP " + msg); skipped.append(msg)
                    continue
                ob = {r[0]: r for r in orows}
                oe, ox = ob.get(ebar[0]), ob.get(sc["exit_t"])
                if oe is None or ox is None:
                    msg = f"{tag}: option bar missing at entry {ebar[0]} or exit {sc['exit_t']} ({con['trading_symbol']})"
                    print("SKIP " + msg); skipped.append(msg)
                    continue
                epx, xpx = worst_fills("LONG", oe, ox)
                qty = con["lot_size"]
                mfe, mae = excursion(orows, "LONG", epx, ebar[0], sc["exit_t"])
                ref = setup["signal_close"]
                lv = [{"name": f"{setup['direction']} zone", "price": setup["zone_lo"], "price2": setup["zone_hi"],
                       "from": setup["zone_t"], "to": ebar[0]},
                      {"name": "swing broken", "price": setup["level"], "from": setup["level_t"], "to": setup["break_t"]},
                      {"name": "entry ref (signal close)", "price": ref, "from": ebar[0], "to": sc["exit_t"]},
                      {"name": "initial stop (index)", "price": sc["stop0"], "from": ebar[0], "to": sc["exit_t"]}]
                if sc["armed_at"]:
                    lv.append({"name": "trail stop at exit (index)", "price": sc["stop"], "from": sc["armed_at"], "to": sc["exit_t"]})
                trades.append(make_trade(
                    day=day, side="LONG", symbol=con["trading_symbol"], entry_time=ebar[0], entry_px=epx,
                    exit_time=sc["exit_t"], exit_px=xpx, qty=qty, exit_reason=sc["reason"], kind="option",
                    capital=epx * qty, entry_spot=ref, stop=None, target=None, mfe=mfe, mae=mae,
                    variant={"tf": f"{tf}m"}, tags={"direction": setup["direction"]}, levels=lv,
                    option_type=otype, expiry=con["expiry"],
                    note=(f"signal candle {setup['signal_start']} ({tf}m), touch of zone "
                          f"{setup['zone_lo']:.2f}-{setup['zone_hi']:.2f}; index stop/trail; trigger {sc['trigger_t']}")))
                option_sessions.setdefault(con["trading_symbol"], {})[day] = orows

    limits = [
        "ASSUMED: underlying NIFTY 50; the index is not tradable, so the trade is a bought ATM NIFTY option "
        "(demand = CE, supply = PE), nearest expiry at least 1 day after the trade day, 1 lot (lot size from the resolved contract).",
        "ASSUMED: swings use the same day's candles only; a swing is usable for candle i when s+3 <= i-1; latest swing per side; red = close<open, green = close>open.",
        "ASSUMED: step 10 'far edge' = the breakout-side edge of the zone (high for demand, low for supply).",
        "ASSUMED: stop (100), trail arm (+40) and trail distance (30) are index points on 1-minute index candles; reference entry = signal candle close; "
        "the fill is on the option bars (buy at the bar high, sell at the bar low), so the option P&L is not 100 index points of risk.",
        "The stop / trail are checked on completed 1-minute index bars and exit in the next 1-minute bar; the entry bar checks the stop but does not feed the trail; "
        "a bar's high/low updates the trail only after its own stop check.",
        "ASSUMED: no new entry when the touch candle completes at or after 13:00; time exit at 15:15 fills in that bar.",
        "Not built (the prompt says they are not the rule): opposing-liquidity trail cap, R-multiple caps, re-entry. Slippage is not recorded separately; every fill is already worst-case.",
        "Capital = premium x qty (bought option). Costs: standard option schedule.",
        "In-sample: 100 / 40 / 30 / 3m-vs-1m come from the prompt's author looking at the same history; nothing is tuned here.",
        "3m and 1m variants are separate alternative books (one trade a day each), not one combined portfolio; their trades overlap in time.",
        f"Skipped ({len(skipped)}): see console output.",
    ]
    meta = {
        "title": "Supply and Demand v4 - 100-point stop with trail",
        "subtitle": "NIFTY swing-break zone retest, bought ATM option, index-point stop 100, trail arms +40 / 30 behind",
        "instrument": "NIFTY 50 index signal; ATM NIFTY option traded",
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": info["lot_size"],
        "fill_rule": "Signal in a completed candle, filled in the next 1-minute bar: every buy at that bar's high, every sell at its low.",
        "cost_model": "Upstox F&O option schedule (brokerage, STT, exchange, SEBI, stamp, GST) on every trade",
        "params": {"timeframes": "3m, 1m", "swing": "3 left / 3 right", "zone candles": 3, "death": f"{DEATH_WIDTHS:g} zone widths",
                   "no entry from": NO_ENTRY_FROM, "stop": f"{STOP_PTS:g} index pts", "trail arm": f"+{ARM_PTS:g}",
                   "trail distance": f"{TRAIL_PTS:g}", "square off": SQUARE_OFF, "strike": "ATM", "lots": 1},
        "rule_steps": [
            "Swing high/low: a candle whose high (low) is above (below) the 3 highs (lows) before and the 3 after; usable only after 3 candles have closed after it.",
            "The first candle of the day that CLOSES above the latest confirmed swing high (bullish) or below the latest swing low (bearish) sets the direction.",
            "Zone = full range of the last opposite-coloured candle among the 3 before the break; none = no trade that day.",
            f"Setup dies if a candle closes more than {DEATH_WIDTHS:g} zone widths past the breakout-side edge (checked before the touch test).",
            "First candle after the break that touches the zone (low <= zone high and high >= zone low) is the signal; not acted on if it completes at or after 13:00.",
            "Demand: buy a CE; supply: buy a PE, filled in the next 1-minute bar at its high.",
            f"Initial stop {STOP_PTS:g} index points from the signal close; trail arms at +{ARM_PTS:g} and follows {TRAIL_PTS:g} behind the best price, in favour only, on completed 1-minute candles.",
            "A stop touch exits in the next 1-minute bar (option sold at that bar's low); if untouched, square off in the 15:15 bar.",
            "One trade a day per timeframe; no re-entry.",
        ],
        "limits": limits,
        "coverage": cov,
    }
    groups = [{"name": "Direction at entry", "keys": ["direction"]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups)
    path = write_report(payload, REPORT_NAME)
    print(f"\nSkipped {len(skipped)} day/timeframe combinations (listed above).")
    print(console_summary(trades))
    print(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Supply and Demand v4 backtest")
    yday = date.today() - timedelta(days=1)
    ap.add_argument("--from", dest="frm", type=date.fromisoformat, default=yday - timedelta(days=182))
    ap.add_argument("--to", dest="to", type=date.fromisoformat, default=yday)
    a = ap.parse_args()
    asyncio.run(main(a.frm, a.to))
