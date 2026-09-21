"""Fib Retracement - v1 (FR v1)

STRATEGY PROMPT (verbatim summary of 12_fr_v1.txt)
    Step 1  swing high = candle whose high is higher than the 8 highs before and the 8 after; swing
            low is the mirror.  Not confirmed until 8 candles have closed after it.
    Step 2  comparisons strict on both sides (an equal neighbouring high kills a pivot).
    Step 3  fib on the leg: swing low -> swing high for a LONG, swing high -> swing low for a SHORT.
    Step 4  0.618-0.786 band of the leg is the reversal zone (both directions); 0.618 = near edge.
    Step 5  entry = the near edge, 0.618.
    Step 6  retest reading (default): price reaches the zone; then a candle CLOSES back beyond the
            near edge (rejection); then the NEXT candle to reach that edge is the entry.  One candle
            can reach and reject; the rejection candle is never the entry.
    Step 7  a close beyond the FAR edge kills the leg at any point.
    Step 8  computed beside it: plain touch (resting order at 0.618, no confirmation).
    Step 9  stop = 5 points beyond the 0.786 level.
    Step 10 risk = entry - stop (long); below 1 point of risk there is no trade.
    Step 11 target 1:2; 1:3 and 1:4 are scored off the same entries.
    Step 12 first touch at or after the moment the zone becomes drawable; second visits included;
            never look at an unconfirmed swing.
    Step 13 every leg stays live from the moment it can be drawn until entered or the session ends.
    Step 14 one position at a time, re-entering whenever a leg arms and the book is flat.
    Step 15 square off at 15:15.
    Step 16 1, 3 and 5-minute candles (opening on 5-minute).

RUN.md STEP 1 CHECKLIST
    1 Underlying ........ ASSUMED  NIFTY 50 (the prompt names none; RUN.md rule 7 uses 375-bar NIFTY sessions)
    2 Window ............ ASSUMED  default: last 6 months ending yesterday (--from / --to override)
    3 Signal timeframe .. clear    1m, 3m, 5m (built from 1m) -> variant "tf"
    4 Signal rule ....... clear    pivot 8/8 strict, fib 0.618 / 0.786, stop 5 pts, min risk 1 pt
    5 Decision time ..... clear    any candle after the zone is drawable; fill per rules 1-2
    6 Direction mapping . ASSUMED  up-leg (swing low -> swing high) = LONG signal; down-leg = SHORT signal
    7 Traded instrument . ASSUMED  ATM NIFTY option, bought: LONG signal -> buy CE, SHORT signal -> buy PE
                                   (the prompt is in index points; an index cannot be traded and RUN.md rule 5
                                   forbids guessing non-option costs, so the option schedule is used)
    8 Option specifics .. ASSUMED  buy; ATM strike from the signal candle's close; expiry = nearest at least
                                   1 day after the trade day (RUN.md default); 1 lot (qty from the contract)
    9 Entry ............. clear    steps 6 / 8; fills per rules 1-2 (see conflicts)
   10 Exit .............. clear    stop, target (1:2 / 1:3 / 1:4) measured on the INDEX levels (ASSUMED basis: the
                                   fib levels are index prices), time exit 15:15 (ASSUMED: the bar starting 15:15
                                   fills in itself)
   11 Holding period .... clear    intraday
   12 Costs ............. ASSUMED  standard option schedule (option_costs)
   13 Position rules .... clear    one at a time, re-entry when flat
   14 Missing data ...... ASSUMED  skip and list (default)
   15 Filters ........... clear    tf (1m/3m/5m) x entry (retest/touch) x rr (1:2/1:3/1:4), plus side
   16 Custom group-bys .. ASSUMED  none asked; added "direction" and "leg size" (leg range in index points,
                                   known at the signal)
   17 Script name ....... fr_v1

OTHER ASSUMPTIONS
    A1 Leg pairing: when a pivot confirms, the leg is drawn from the most recent confirmed OPPOSITE pivot that
       is earlier in the session.  Older pivots keep their own legs live (step 13).
    A2 Swings are found inside one session only (a pivot needs 8 candles of the same day on each side).
    A3 Legs are evaluated only from the candle after the confirming candle.  Candles during the 8 blind bars are
       ignored for reach / rejection (step 12) but a close beyond the far edge during them kills the leg at birth.
    A4 When several legs trigger on the same candle, the earliest-drawn one is taken; the rest stay live.
       A leg that triggers while a position is open is not entered; it stays live and can trigger later.
    A5 Each (tf, entry, rr) is simulated independently, so with one-position-at-a-time the 1:3 and 1:4 books can
       differ from the 1:2 book after the first exit (same leg detection, different exit times).
    A6 Stop/target triggers are checked on the INDEX 1-minute bars from the entry bar itself (the bar touching a
       level is the signal; the exit fills in the next 1m bar on the OPTION, high/low rule).
    A7 A leg whose signal candle already went through the stop (or the target) before entry could fill is
       dropped (dead) and listed.
    A8 No new entry when the entry bar would start later than 15:14.
    A9 Tie between stop and target in one bar: stop first.
    A10 Strike step and live lot size come from Upstox (rule 8); the strike step is read from today's chain.

The Rules to Live By override the prompt (see meta.limits): fills are at the option bar's high (buy) / low (sell)
in the 1-minute bar AFTER the signal candle, not "exactly at 0.618".
"""
import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: F401,F403,E402
from py_funcs import (IST, Upstox, atm_strike, bar_after_candle, bucket, build_payload,  # noqa: E402
                      candle_done_at, console_summary, coverage, excursion, hhmm_minutes,
                      make_trade, next_expiry, resample, scan_exit, sessions_from,
                      worst_fills, write_report)

NAME = "fr_v1"
PIVOT = 8
NEAR, FAR = 0.618, 0.786
STOP_PTS = 5.0
MIN_RISK = 1.0
FORCE_KEY = "15:15"
LAST_ENTRY = "15:14"
TFS = [1, 3, 5]
MODES = ["retest", "touch"]
RRS = [2, 3, 4]
SESSION_ROWS = 375


# ---------------------------------------------------------------------------
# data checks
# ---------------------------------------------------------------------------
def _expected_minutes() -> list[str]:
    return [f"{m // 60:02d}:{m % 60:02d}" for m in range(9 * 60 + 15, 15 * 60 + 30)]


EXPECTED = _expected_minutes()


def check_session(rows: list[list]) -> str | None:
    """None if the session is complete and valid, else the reason it is not used (rules 6, 7)."""
    if len(rows) != SESSION_ROWS:
        return f"short/odd session: {len(rows)} bars, need {SESSION_ROWS}"
    if [r[0] for r in rows] != EXPECTED:
        miss = sorted(set(EXPECTED) - {r[0] for r in rows})
        return f"missing/duplicate minutes, e.g. {miss[:3]}"
    for r in rows:
        _, o, h, l, c = r
        if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c) or h < l:
            return f"invalid candle at {r[0]}: {r[1:]}"
    return None


def valid_bar(b: list | None) -> bool:
    return bool(b) and min(b[1:5]) > 0 and b[2] >= max(b[1], b[4]) and b[3] <= min(b[1], b[4])


def prev_key(hhmm: str) -> str:
    m = hhmm_minutes(hhmm) - 1
    return f"{m // 60:02d}:{m % 60:02d}"


# ---------------------------------------------------------------------------
# signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def pivot_at(cs: list[list], p: int, k: int = PIVOT) -> tuple[bool, bool]:
    """(swing high, swing low) for candle p, strict on both sides.  Needs candles p-k .. p+k, so
    it is only called when candle p+k is complete (rule 4)."""
    if p < k or p + k >= len(cs):
        return False, False
    hi, lo = cs[p][2], cs[p][3]
    win = [q for q in range(p - k, p + k + 1) if q != p]
    return all(hi > cs[q][2] for q in win), all(lo < cs[q][3] for q in win)


def make_leg(direction: int, a: int, b: int, cs: list[list], j: int) -> dict | None:
    """direction +1 LONG: a = swing low idx, b = swing high idx.  -1 SHORT: a = swing high, b = swing low.
    j = candle just completed (the confirming candle of the later pivot)."""
    if direction == 1:
        lo, hi = cs[a][3], cs[b][2]
    else:
        hi, lo = cs[a][2], cs[b][3]
    rng = hi - lo
    if rng <= 0:
        return None
    if direction == 1:
        near, far = hi - NEAR * rng, hi - FAR * rng
        stop = far - STOP_PTS
        risk = near - stop
    else:
        near, far = lo + NEAR * rng, lo + FAR * rng
        stop = far + STOP_PTS
        risk = stop - near
    # a close beyond the far edge during the blind bars kills the leg at birth (assumption A3)
    for q in range(b + 1, j + 1):
        if (direction == 1 and cs[q][4] < far) or (direction == -1 and cs[q][4] > far):
            return None
    return {"dir": direction, "a": a, "b": b, "hi": hi, "lo": lo, "range": rng, "near": near, "far": far,
            "stop": stop, "risk": risk, "state": "fresh", "key": (direction, a, b)}


def step_leg(leg: dict, c: list, mode: str) -> str:
    """Feed one COMPLETED candle to a leg.  Returns 'dead', 'trigger' or 'live'.
    retest: fresh -> reached -> rejected (close back beyond near) -> the next candle reaching near triggers.
    touch : any candle reaching near triggers."""
    d = leg["dir"]
    reach = c[3] <= leg["near"] if d == 1 else c[2] >= leg["near"]
    reject = c[4] > leg["near"] if d == 1 else c[4] < leg["near"]
    killed = c[4] < leg["far"] if d == 1 else c[4] > leg["far"]
    if killed:
        return "dead"
    if mode == "touch":
        return "trigger" if reach else "live"
    if leg["state"] == "rejected":
        return "trigger" if reach else "live"
    if reach:
        leg["state"] = "reached"
    if leg["state"] == "reached" and reject:
        leg["state"] = "rejected"      # this candle is the rejection; it can never be the entry
    return "live"


# ---------------------------------------------------------------------------
# simulate (bars -> trades).  `provider` is an injected async callable that gives the option bars.
# ---------------------------------------------------------------------------
async def simulate_day(day: str, idx_rows: list[list], tf: int, mode: str, rr: int, provider, log) -> list[dict]:
    cs = resample(idx_rows, tf)
    trades: list[dict] = []
    legs: list[dict] = []
    hi_piv: list[int] = []
    lo_piv: list[int] = []
    last_exit = ""
    late_logged = False
    variant = {"tf": f"{tf}m", "entry": mode, "rr": f"1:{rr}"}

    for j, c in enumerate(cs):
        done = candle_done_at(c[0], tf)
        # 1. legs already live see this completed candle
        triggered = []
        for leg in list(legs):
            s = step_leg(leg, c, mode)
            if s == "dead":
                legs.remove(leg)
            elif s == "trigger":
                triggered.append(leg)
        # 2. act on triggers (entry = the 1m bar right after this candle)
        for leg in triggered:
            if done <= last_exit:
                continue                                   # book busy: leg stays live (A4)
            if done > LAST_ENTRY:
                if not late_logged:
                    log(day, variant, "entry would fall at/after 15:15, no new trades", None)
                    late_logged = True
                continue
            legs.remove(leg)
            t = await _enter(day, idx_rows, c, tf, leg, rr, variant, cs, provider, log)
            if t is None:
                continue
            trades.append(t["trade"])
            last_exit = t["exit_time"]
        # 3. pivots that this candle confirms (candle j-8), legs live from the next candle
        p = j - PIVOT
        if p >= PIVOT:
            is_hi, is_lo = pivot_at(cs, p)
            new = []
            if is_hi and lo_piv:
                new.append(make_leg(1, lo_piv[-1], p, cs, j))
            if is_lo and hi_piv:
                new.append(make_leg(-1, hi_piv[-1], p, cs, j))
            legs.extend(x for x in new if x)
            if is_hi:
                hi_piv.append(p)
            if is_lo:
                lo_piv.append(p)
    return trades


async def _enter(day, idx_rows, c, tf, leg, rr, variant, cs, provider, log):
    d = leg["dir"]
    done = candle_done_at(c[0], tf)
    otype = "CE" if d == 1 else "PE"
    idx_side = "LONG" if d == 1 else "SHORT"
    near, stop, risk = leg["near"], leg["stop"], leg["risk"]
    if risk < MIN_RISK:
        log(day, variant, f"risk {risk:.2f} < {MIN_RISK} point", leg["key"])
        return None
    target = near + d * rr * risk
    # RULE 4/3: the signal candle itself already went through the stop or the target before entry could fill
    if (d == 1 and c[3] <= stop) or (d == -1 and c[2] >= stop):
        log(day, variant, "signal candle already crossed the stop (band crossed inside one candle)", leg["key"])
        return None
    if (d == 1 and c[2] >= target) or (d == -1 and c[3] <= target):
        log(day, variant, "signal candle already reached the target", leg["key"])
        return None
    contract, orows = await provider(day, otype, c[4])
    if contract is None:
        log(day, variant, f"option unavailable: {orows}", leg["key"])
        return None
    ebar = bar_after_candle(orows, c[0], tf)                       # RULE 2, strict
    if not valid_bar(ebar):
        log(day, variant, f"option entry bar {done} missing/invalid for {contract['trading_symbol']}", leg["key"])
        return None
    sc = scan_exit(idx_rows, idx_side, prev_key(done), stop=stop, target=target, force_key=FORCE_KEY)  # RULE 3
    if sc["bar"] is None:
        log(day, variant, f"no exit bar ({sc['reason']})", leg["key"])
        return None
    xkey = sc["bar"][0]
    xbar = next((r for r in orows if r[0] == xkey), None)
    if not valid_bar(xbar):
        log(day, variant, f"option exit bar {xkey} missing/invalid for {contract['trading_symbol']}", leg["key"])
        return None
    entry_px, exit_px = worst_fills("LONG", ebar, xbar)              # RULE 1: bought option
    qty = contract["lot_size"]                                        # RULE 8, 1 lot
    mfe, mae = excursion(orows, "LONG", entry_px, ebar[0], xkey)
    t_a, t_b = cs[leg["a"]][0], cs[leg["b"]][0]
    levels = [
        {"name": "leg high", "price": leg["hi"], "from": min(t_a, t_b), "to": xkey},
        {"name": "leg low", "price": leg["lo"], "from": min(t_a, t_b), "to": xkey},
        {"name": "0.618 near edge", "price": near, "from": done, "to": xkey},
        {"name": "0.786 far edge", "price": leg["far"], "from": done, "to": xkey},
        {"name": "index stop", "price": stop, "from": done, "to": xkey},
        {"name": f"index target 1:{rr}", "price": target, "from": done, "to": xkey},
    ]
    trade = make_trade(
        day=day, side="LONG", symbol=contract["trading_symbol"], entry_time=ebar[0], entry_px=entry_px,
        exit_time=xkey, exit_px=exit_px, qty=qty, exit_reason=sc["reason"], kind="option",
        capital=entry_px * qty, mfe=mfe, mae=mae, variant=variant, expiry=contract["expiry"],
        option_type=otype, levels=levels,
        tags={"direction": "up-leg (buy CE)" if d == 1 else "down-leg (buy PE)",
              "leg size": bucket(leg["range"], [50, 100, 200], ["<50 pts", "50-100 pts", "100-200 pts", ">200 pts"])},
        note=(f"{'LONG' if d == 1 else 'SHORT'} leg {leg['lo']:.2f}-{leg['hi']:.2f}, signal candle {c[0]} "
              f"({tf}m), near {near:.2f}, stop {stop:.2f}, target {target:.2f} (index levels)"))
    return {"trade": trade, "exit_time": xkey}


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
async def run(frm: date, to: date) -> None:
    now = datetime.now(IST)
    if to >= now.date() and now.strftime("%H:%M") < "15:45":        # RULE 7: today is not over
        to = now.date() - timedelta(days=1)
        print(f"  today's session is not complete; window ends {to}")
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        ukey = und["instrument_key"]
        info = await up.option_chain_info(ukey)
        step = info["strike_step"]
        if not step:
            raise SystemExit("could not read the strike step from Upstox")
        cal = await up.expiry_calendar(ukey, frm, to)
        print(f"{und['trading_symbol']}  strike step {step:g}  expiries known: {len(cal)}")
        cs = await up.candles(ukey, "1m", frm, to)
        sessions = {d: r for d, r in sessions_from(cs).items() if frm.isoformat() <= d <= to.isoformat()}
        cov = coverage(sessions, frm, to, SESSION_ROWS)

        contracts: dict = {}
        bars: dict = {}
        opt_sessions: dict = {}

        async def provider(day: str, otype: str, spot: float):
            dd = date.fromisoformat(day)
            exp = next_expiry(cal, dd, 1)                             # RULE 10
            if exp is None:
                return None, "no expiry at least 1 day after the trade day"
            strike = atm_strike(spot, step)
            ck = (exp, strike, otype)
            if ck not in contracts:
                contracts[ck] = await up.resolve_option(ukey, exp, strike, otype)
            con = contracts[ck]
            if con is None:
                return None, f"no contract {exp} {strike:g} {otype}"
            bk = (con["instrument_key"], day)
            if bk not in bars:
                bars[bk] = await up.option_candles(con, dd)
            rows = bars[bk]
            if not rows:
                return None, f"no option bars for {con['trading_symbol']}"
            opt_sessions.setdefault(con["trading_symbol"], {})[day] = rows
            return con, rows

        skips: dict = defaultdict(set)

        def log(day, variant, why, legkey):
            skips[day].add((variant["tf"], variant["entry"], why, legkey))

        all_trades: list[dict] = []
        good_days: dict = {}
        for gap in cov["weekday_gaps"]:
            print(f"  SKIP {gap}: no index candles (holiday or feed miss)")
        for day, rows in sessions.items():
            bad = check_session(rows)
            if bad:
                print(f"  SKIP {day}: {bad}")
                continue
            good_days[day] = rows
            for tf in TFS:
                for mode in MODES:
                    for rr in RRS:
                        all_trades += await simulate_day(day, rows, tf, mode, rr, provider, log)
            for tf, mode, why, key in sorted(skips.get(day, ()), key=str):
                print(f"  skipped leg {day} tf={tf} {mode}: {why}")
            print(f"  {day}: {sum(1 for t in all_trades if t['day'] == day)} trades so far {len(all_trades)}")

    if not all_trades:
        print("no trades in the window")
        return

    meta = {
        "title": "Fib Retracement v1",
        "subtitle": "Return into the 0.618-0.786 band of a confirmed 8/8 swing leg, ATM NIFTY option bought",
        "instrument": f"NIFTY 50 signal, ATM option bought (strike step {step:g})",
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": "from the resolved contract, per trade (1 lot)",
        "fill_rule": "buy at the bar's HIGH, sell at the bar's LOW; signal candle -> next 1-minute bar; "
                     "stop/target touch -> next 1-minute bar; 15:15 time exit fills in the 15:15 bar",
        "cost_model": "standard option schedule (option_costs)",
        "params": {"pivot": f"{PIVOT} before / {PIVOT} after, strict", "zone": f"{NEAR}-{FAR}",
                   "stop": f"{STOP_PTS:g} pts beyond 0.786", "min risk": f"{MIN_RISK:g} pt",
                   "targets": "1:2, 1:3, 1:4", "timeframes": "1m, 3m, 5m", "square off": FORCE_KEY,
                   "expiry": "nearest at least 1 day after the trade day", "lots": 1},
        "rule_steps": [
            "Build 1/3/5-minute candles from the 1-minute session; read only completed candles.",
            f"A swing high has a high strictly above the {PIVOT} highs before and {PIVOT} after it; a swing low is the "
            f"mirror. It is confirmed {PIVOT} candles later.",
            "When a pivot confirms, draw a leg from the latest earlier opposite pivot (low to high = LONG leg, "
            "high to low = SHORT leg).",
            f"Near edge = {NEAR} retracement, far edge = {FAR}; stop = {STOP_PTS:g} pts beyond the far edge; "
            f"risk = near - stop (long); no trade under {MIN_RISK:g} pt; target = 1:2, 1:3 or 1:4 of risk (index levels).",
            "A close beyond the far edge kills the leg.",
            "Retest: price reaches the near edge, a candle closes back beyond it (rejection), the next candle that "
            "reaches the edge is the signal. Touch: the first candle that reaches the edge is the signal.",
            "Enter in the 1-minute bar after the signal candle completes: LONG leg buys the ATM CE, SHORT leg buys "
            "the ATM PE, at that option bar's high.",
            "Stop/target are watched on the index 1-minute bars from the entry bar; the exit sells the option at the "
            "next 1-minute bar's low. Stop first if one bar touches both. Otherwise sell in the 15:15 bar.",
            "One position at a time; a leg stays live until entered, killed or the session ends.",
        ],
        "limits": [
            "ASSUMED: underlying = NIFTY 50 (prompt names none).",
            "ASSUMED: the traded instrument is the ATM option bought (CE on a long leg, PE on a short leg); the prompt "
            "is in index points. Stops and targets are index levels; P&L is option premium.",
            "ASSUMED: leg pairing = the latest earlier confirmed opposite pivot; swings inside one session only.",
            "ASSUMED: legs are evaluated from the candle after confirmation; a close beyond the far edge during the "
            "8 blind bars kills the leg at birth.",
            "ASSUMED: several legs triggering on one candle -> earliest-drawn first; a leg triggering while a position "
            "is open stays live.",
            "ASSUMED: ATM strike from the signal candle's close; expiry nearest >= 1 day after the trade day; 1 lot; "
            "costs = standard option schedule; 15:15 = the bar starting 15:15; no new entry after 15:14.",
            "Rules override the prompt: entries/exits are NOT 'at exactly 0.618'; they fill at the option bar's "
            "high/low in the 1-minute bar after the signal candle, so real entries are later and worse than the fib "
            "level assumes. Index-level stops that were already crossed inside the signal candle are dropped.",
            "Each (tf, entry, rr) is a separate one-position-at-a-time simulation; 1:3 and 1:4 are not the same trade "
            "sequence as 1:2 after the first exit.",
            "Nothing is optimised; all tf x entry x rr variants are shown as filters. Any pick from them is in-sample.",
            "Option premium is not the index: theta and IV are inside the result; the strike step is read from "
            "today's chain.",
            "Skipped days/legs are printed on the console only.",
        ],
        "coverage": cov,
    }
    groups = [{"name": "direction", "keys": ["direction"]}, {"name": "leg size", "keys": ["leg size"]}]
    payload = build_payload(meta, all_trades, good_days, opt_sessions, groups)
    path = write_report(payload, NAME)
    print(console_summary(all_trades))
    print(path)


def main() -> None:
    yest = datetime.now(IST).date() - timedelta(days=1)
    ap = argparse.ArgumentParser(description="Fib Retracement v1 backtest")
    ap.add_argument("--from", dest="frm", type=date.fromisoformat, default=yest - timedelta(days=182))
    ap.add_argument("--to", dest="to", type=date.fromisoformat, default=yest)
    a = ap.parse_args()
    asyncio.run(run(a.frm, a.to))


if __name__ == "__main__":
    main()
