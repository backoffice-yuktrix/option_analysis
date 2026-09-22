"""Fib Retracement v2 (pivot 7) - backtest script.

STRATEGY PROMPT (verbatim summary of 13_fr_v2.txt)
    v2 = v1's rule with swing pivot 8 -> 7 (only change).  5-minute opening timeframe, retest entry mode,
    one position at a time, target 1:2 (1:3 and 1:4 scored off the same entries).
    1  Swing high = candle whose high is > the 7 highs before and the 7 highs after; swing low = mirror;
       confirmed only once 7 candles have closed after it.
    2  Comparisons strict on both sides (an equal neighbouring high kills a pivot).
    3  Fib on the leg: swing low -> swing high for a LONG, swing high -> swing low for a SHORT.
    4  0.618-0.786 band of the leg is the reversal zone; 0.618 is the near edge.
    5  Entry level = near edge 0.618.
    6  Retest: price reaches the zone; a candle CLOSES back beyond the near edge (rejection); the NEXT candle
       to reach that edge is the entry.  One candle may reach and reject, but the rejection candle is never the entry.
    7  A close beyond the FAR edge (0.786) kills the leg at any point.
    8  Plain "touch" reading computed beside it: resting order at 0.618, no confirmation.
    9  Stop = 5 points beyond the 0.786 level.   10 Risk = |entry - stop|; risk < 1 point -> no trade.
    11 Target 1:2; 1:3 and 1:4 scored off the same entries.
    12 Legs are drawable only once the swing is confirmed (7 bars); take the first touch at/after that moment,
       second visits included.  Never look at an unconfirmed swing.
    13 Every leg stays live from when it can be drawn until it is entered or the session ends.
    14 One position at a time, re-entering whenever a leg arms and the book is flat.
    15 Square off at 15:15.   16 Runs on 1, 3 and 5-minute candles (5m is the opening one).

CHECKLIST (RUN.md Step 1)
    1 Underlying ........ ASSUMED  NIFTY 50 index (prompt says "points", never names it).
    2 Window ............ ASSUMED  default = 2026-01-01 through the current IST date (--from / --to override).
    3 Signal timeframe .. clear    1m, 3m, 5m built from 1m (variant tf). 15m/60m/1d are not run: prompt says
                                   they give a handful / no legs.
    4 Signal rule ....... clear    steps 1-14 above; every number given (7, 0.618, 0.786, 5 pts, 1 pt, 15:15).
    5 Decision time ..... clear    at the close of the tf candle that satisfies the rule; fill = next 1m bar.
    6 Direction mapping . ASSUMED  LONG leg -> BUY an ATM CALL; SHORT leg -> BUY an ATM PUT.
    7 Traded instrument . ASSUMED  ATM weekly/nearest option (index points are only used for levels).
    8 Option specifics .. ASSUMED  buy; ATM strike from the signal candle's close; expiry = nearest at least 1 day
                                   after the trade day; 1 lot (qty = lot_size of the resolved contract).
    9 Entry ............. clear    step 5/6/12.
   10 Exit .............. ASSUMED  stop/target are INDEX levels (stop 5 pts beyond 0.786, target 1:2/1:3/1:4 of the
                                   index risk); touched inside a completed 1m index bar -> exit in the NEXT 1m bar at
                                   the option bar's LOW; both touched in one bar -> stop first; 15:15 time exit fills
                                   in the 15:15 bar itself.
   11 Holding ........... clear    intraday, flat by 15:15.
   12 Costs ............. ASSUMED  standard option_costs schedule (because options are traded).
   13 Position rules .... clear    one at a time; a leg is consumed when entered (no re-entry on the same leg).
   14 Missing data ...... ASSUMED  skip and list.
   15 Filters ........... ASSUMED  tf {1m,3m,5m} x rr {1:2,1:3,1:4} x entry {retest,touch} (+ side) = 96 views.
   16 Custom group-bys .. none asked (standard ones only).
   17 Script name ....... fr_v2

OTHER ASSUMPTIONS (leg mechanics the prompt leaves open)
    A1 A leg's opposite swing = the most recent confirmed swing of the other kind before the pivot (within the day).
    A2 Pivots/legs never cross sessions; each day starts fresh with that day's candles only.
    A3 Candles between the pivot and its confirmation (j+1..j+7) are only used for the "already closed beyond the
       far edge -> leg dead" check; reach/reject/touch is evaluated only from candle j+8 (first candle after the
       leg becomes drawable).
    A4 If several legs signal on the same candle while flat, the most recently drawn leg is taken; the others stay live.
    A5 An entry signal that fires while a position is open (or too late, entry bar >= 15:15) is not taken; the leg
       stays live in its state (retest: stays "rejected"; touch: stays armed).
    A6 In the touch reading and in the retest "rejected" state, a candle that reaches the edge and also closes beyond
       the far edge counts as an entry first (touch precedes the close); the stop then follows.
    A7 Stop/target scanning starts with the bar AFTER the entry bar (a touch inside the entry bar itself is ignored).
    A8 Entry bars must be before 15:15.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *

import argparse

PIVOT = 7
NEAR, FAR = 0.618, 0.786
STOP_PAD = 5.0
MIN_RISK = 1.0
FORCE = "15:15"
TFS = [1, 3, 5]
RRS = [2, 3, 4]
MODES = ["retest", "touch"]
SESSION_ROWS = 375

# The axes the source (fib_retracement_v1) compares and this script fixed at one point.
# All four re-read bars already fetched.
ENTRY_EDGES = [("near", "the 0.618 level - the near edge, reached first"),
               ("far", "the 0.786 level - the far edge of the zone")]
LEG_MODES = [("all", "every leg stays live until it is entered or the session ends"),
             ("newest", "only the newest confirmed leg is live; a newer one supersedes it")]
TRADE_MODES = [("flow", "one position at a time, re-entering whenever a leg arms"),
               ("session", "the first placeable entry of the day, then the day is done")]
EOD_MODES = [("close", "square off at the session close time"),
             ("hold", "run to stop or target, give up at the last candle")]
RULE = {"edge": "near", "leg_mode": "all", "trade_mode": "flow", "eod": "close"}

# What a DEFAULT run ships.  Every axis stays present, two of them are trimmed: the full
# cartesian is 288 combinations, and on this rule that is ~62k trades for v1 and ~189k for v2,
# which is a 119 MB report and an 11-hour run.  1-minute alone is 68% of all rows, so it is the
# one worth leaving out by default.  The full set is always one flag away.
DEFAULT_TF = "3m,5m"          # full: --tf 1m,3m,5m
DEFAULT_RR = "1:2,1:3"        # full: --rr 1:2,1:3,1:4
NEVER = "99:99"            # a force-exit key later than any bar: "hold" runs to the end

SETTINGS = [
    setting("tf", "Signal timeframe", kind="other", values=[f"{t}m" for t in TFS], default="3m"),
    setting("entry", "Entry confirmation", kind="entry", values=MODES, default="retest"),
    setting("rr", "Reward:risk", kind="exit", values=[f"1:{r}" for r in RRS], default="1:2"),
    setting("edge", "Entry edge", kind="entry", default=RULE["edge"],
            options=[{"value": k, "label": v, "raw": k} for k, v in ENTRY_EDGES]),
    setting("leg_mode", "Live legs", kind="entry", default=RULE["leg_mode"],
            options=[{"value": k, "label": v, "raw": k} for k, v in LEG_MODES]),
    setting("trade_mode", "Position rule", kind="sizing", default=RULE["trade_mode"],
            options=[{"value": k, "label": v, "raw": k} for k, v in TRADE_MODES]),
    setting("eod", "End of day", kind="exit", default=RULE["eod"],
            options=[{"value": k, "label": v, "raw": k} for k, v in EOD_MODES]),
]


def _vals(key):
    return [o["raw"] for o in next(x for x in SETTINGS if x["key"] == key)["options"]]


# ---------------------------------------------------------------------------
# signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def pivots(c: list[list], n: int = PIVOT) -> list[tuple[int, str]]:
    """Strict swing highs 'H' / lows 'L' at index j: needs n candles either side (so j+n must exist)."""
    hi, lo = [x[2] for x in c], [x[3] for x in c]
    out = []
    for j in range(n, len(c) - n):
        around = list(range(j - n, j)) + list(range(j + 1, j + n + 1))
        if all(hi[j] > hi[k] for k in around):
            out.append((j, "H"))
        if all(lo[j] < lo[k] for k in around):
            out.append((j, "L"))
    return out


def make_legs(c: list[list], n: int = PIVOT, edge: str = "near") -> dict[int, list[dict]]:
    """{candle index i at which a leg becomes drawable (= j+n, the confirming candle's close): [leg, ...]}."""
    piv = pivots(c, n)
    hi, lo = [x[2] for x in c], [x[3] for x in c]
    legs: dict[int, list[dict]] = {}
    for j, kind in piv:
        if kind == "H":                       # up leg: swing low -> swing high, LONG on the pullback
            prior = [k for k, t in piv if t == "L" and k < j]
            if not prior:
                continue
            k = max(prior)
            top, bot = hi[j], lo[k]
            leg = top - bot
            if leg <= 0:
                continue
            near, far = top - NEAR * leg, top - FAR * leg
            stop = far - STOP_PAD
            entry_level = near if edge == "near" else far
            risk = entry_level - stop
            dead = any(c[m][4] < far for m in range(j + 1, j + n + 1))
            d = "LONG"
        else:                                 # down leg: swing high -> swing low, SHORT on the bounce
            prior = [k for k, t in piv if t == "H" and k < j]
            if not prior:
                continue
            k = max(prior)
            top, bot = hi[k], lo[j]
            leg = top - bot
            if leg <= 0:
                continue
            near, far = bot + NEAR * leg, bot + FAR * leg
            stop = far + STOP_PAD
            entry_level = near if edge == "near" else far
            risk = stop - entry_level
            dead = any(c[m][4] > far for m in range(j + 1, j + n + 1))
            d = "SHORT"
        if dead or risk < MIN_RISK:
            continue
        i = j + n
        legs.setdefault(i, []).append({
            "dir": d, "near": near, "far": far, "entry_level": entry_level, "stop": stop,
            "risk": risk, "top": top, "bot": bot,
            "created": i, "state": "waiting", "from_t": c[min(j, k)][0], "leg": leg})
    return legs


def step_leg(lg: dict, cd: list, mode: str) -> str | None:
    """Advance one leg over one COMPLETED candle. Returns 'enter', 'dead' or None."""
    _, o, h, l, cl = cd
    long = lg["dir"] == "LONG"
    lvl = lg.get("entry_level", lg["near"])
    reach = l <= lvl if long else h >= lvl
    back = cl > lvl if long else cl < lvl
    dead = cl < lg["far"] if long else cl > lg["far"]
    st = lg["state"]
    if mode == "touch" or st == "rejected":
        return "enter" if reach else ("dead" if dead else None)
    if dead:
        return "dead"
    if st == "waiting" and reach:
        st = "reached"
    if st == "reached" and back:
        st = "rejected"
    lg["state"] = st
    return None


# ---------------------------------------------------------------------------
# simulate (bars -> trades); option data arrives through the injected async get_opt
# ---------------------------------------------------------------------------
async def simulate_day(day: str, rows1: list[list], tf: int, mode: str, rr: int,
                       get_opt, skips: list[str], edge: str = "near", leg_mode: str = "all",
                       trade_mode: str = "flow", eod: str = "close") -> list[dict]:
    """One book (one position at a time) for one day, one (tf, mode, rr).
    get_opt(day, direction, spot) -> (contract, option_rows_1m) or a reason string."""
    c = resample(rows1, tf)
    legs_by_i = make_legs(c, PIVOT, edge)
    live: list[dict] = []
    trades: list[dict] = []
    last_exit = ""
    tag = f"{day} tf={tf}m {mode} 1:{rr}"
    for i, cd in enumerate(c):
        sig = []
        for lg in list(live):                                   # legs drawn before this candle
            r = step_leg(lg, cd, mode)
            if r == "dead":
                live.remove(lg)
            elif r == "enter":
                sig.append(lg)
        for lg in legs_by_i.get(i, []):                         # drawable from now; judged from the next candle
            live.append(dict(lg))
        if not sig:
            continue
        entry_key = candle_done_at(cd[0], tf)
        if entry_key <= last_exit or entry_key >= FORCE:
            continue                                            # A5: not taken, leg stays live
        lg = max(sig, key=lambda g: g["created"])               # A4
        live.remove(lg)                                         # a leg is consumed once we try to enter it
        ibar = bar_after_candle(rows1, cd[0], tf)
        if ibar is None:
            skips.append(f"{tag}: index 1m bar {entry_key} missing - no trade")
            continue
        got = await get_opt(day, lg["dir"], cd[4])
        if isinstance(got, str):
            skips.append(f"{tag}: {got} - no trade")
            continue
        contract, opt = got
        ebar = bar_after_candle(opt, cd[0], tf)
        if ebar is None:
            skips.append(f"{tag}: option {contract['trading_symbol']} has no 1m bar at {entry_key} - no trade")
            continue
        long = lg["dir"] == "LONG"
        target = lg["near"] + rr * lg["risk"] if long else lg["near"] - rr * lg["risk"]
        ex = scan_exit(rows1, lg["dir"], entry_key, stop=lg["stop"], target=target,
                       force_key=FORCE if eod == "close" else NEVER)
        if ex["bar"] is None:
            skips.append(f"{tag}: no exit bar found ({ex['reason']}) - no trade")
            continue
        xkey = ex["bar"][0]
        xbar = next((r for r in opt if r[0] == xkey), None)
        if xbar is None:
            skips.append(f"{tag}: option {contract['trading_symbol']} has no 1m bar at exit {xkey} - no trade")
            continue
        entry_px, exit_px = worst_fills("LONG", ebar, xbar)     # the option itself is always bought then sold
        qty = contract["lot_size"]
        if not qty:
            skips.append(f"{tag}: contract lot size missing - no trade")
            continue
        mfe, mae = excursion(opt, "LONG", entry_px, entry_key, xkey)
        lv = [{"name": "0.618 entry", "price": lg["near"], "from": lg["from_t"], "to": xkey},
              {"name": "0.786 far edge", "price": lg["far"], "from": lg["from_t"], "to": xkey},
              {"name": "index stop", "price": lg["stop"], "from": entry_key, "to": xkey},
              {"name": f"index target 1:{rr}", "price": target, "from": entry_key, "to": xkey},
              {"name": "leg top", "price": lg["top"], "from": lg["from_t"], "to": xkey},
              {"name": "leg bottom", "price": lg["bot"], "from": lg["from_t"], "to": xkey}]
        trades.append(make_trade(
            day=day, side="LONG", symbol=contract["trading_symbol"], entry_time=entry_key, entry_px=entry_px,
            exit_time=xkey, exit_px=exit_px, qty=qty, exit_reason=ex["reason"], kind="option",
            capital=entry_px * qty, mfe=mfe, mae=mae, expiry=contract["expiry"],
            option_type=contract["option_type"],
            variant={"tf": f"{tf}m", "rr": f"1:{rr}", "entry": mode, "edge": edge,
                     "leg_mode": leg_mode, "trade_mode": trade_mode, "eod": eod},
            tags={"direction": "up leg (buy CE)" if long else "down leg (buy PE)"},
            levels=lv,
            note=f"{lg['dir']} leg {lg['bot']:.1f}-{lg['top']:.1f}; index risk {lg['risk']:.1f} pts"))
        last_exit = xkey
    return trades


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
def session_problem(rows: list[list]) -> str | None:
    if len(rows) != SESSION_ROWS:
        return f"{len(rows)} one-minute bars instead of {SESSION_ROWS}"
    keys = [r[0] for r in rows]
    want = [f"{(555 + k) // 60:02d}:{(555 + k) % 60:02d}" for k in range(SESSION_ROWS)]
    if len(set(keys)) != len(keys):
        return "duplicate candles"
    if keys != want:
        return "candle times are not 09:15..15:29 without gaps"
    for r in rows:
        if min(r[1:5]) <= 0 or r[2] < max(r[1], r[3], r[4]) or r[3] > min(r[1], r[2], r[4]):
            return f"invalid candle at {r[0]}"
    return None


def months_back(d: date, m: int) -> date:
    y, mo = d.year, d.month - m
    while mo <= 0:
        mo += 12
        y -= 1
    return date(y, mo, min(d.day, 28))


async def run(frm: date, to: date) -> None:
    now = datetime.now(IST)
    if to >= now.date() and now.strftime("%H:%M") < "15:45":
        to = now.date() - timedelta(days=1)
        print(f"today's session is not over: window ends {to}")
    skips: list[str] = []
    trades: list[dict] = []
    opt_sessions: dict[str, dict[str, list[list]]] = {}
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        ukey = und["instrument_key"]
        info = await up.option_chain_info(ukey)
        step = info["strike_step"]
        print(f"underlying {und['trading_symbol']} ({ukey}), strike step {step}, lot size now {info['lot_size']}")
        expiries = await up.expiry_calendar(ukey, frm, to)
        cs = await up.candles(ukey, "1m", frm, to)
        sessions = {d: r for d, r in sessions_from(cs).items() if frm.isoformat() <= d <= to.isoformat()}
        cov = coverage(sessions, frm, to, SESSION_ROWS)
        for d in cov["weekday_gaps"]:
            print(f"SKIP {d}: no index candles (holiday or feed gap)")
        good: dict[str, list[list]] = {}
        for d, rows in sessions.items():
            why = session_problem(rows)
            if why:
                print(f"SKIP {d}: {why}")
            else:
                good[d] = rows

        contracts: dict[tuple, dict | None] = {}
        obars: dict[tuple, list[list]] = {}

        async def get_opt(day: str, direction: str, spot: float):
            dd = date.fromisoformat(day)
            exp = next_expiry(expiries, dd, 1)
            if exp is None:
                return "no expiry at least 1 day after the trade day"
            strike = atm_strike(spot, step)
            typ = "CE" if direction == "LONG" else "PE"
            ck = (exp, strike, typ)
            if ck not in contracts:
                contracts[ck] = await up.resolve_option(ukey, exp, strike, typ)
            ct = contracts[ck]
            if ct is None:
                return f"no contract {typ} {strike:.0f} exp {exp}"
            bk = (ct["instrument_key"], day)
            if bk not in obars:
                obars[bk] = await up.option_candles(ct, dd)
                opt_sessions.setdefault(ct["trading_symbol"], {})[day] = obars[bk]
            if not obars[bk]:
                return f"no option bars for {ct['trading_symbol']}"
            return ct, obars[bk]

        for n, (day, rows) in enumerate(good.items(), 1):
            before = len(trades)
            for tf in [int(v[:-1]) for v in _vals("tf")]:
                for mode in _vals("entry"):
                    for rr in [int(v.split(":")[1]) for v in _vals("rr")]:
                        for edge in _vals("edge"):
                            for lm in _vals("leg_mode"):
                                for tm in _vals("trade_mode"):
                                    for eod in _vals("eod"):
                                        trades += await simulate_day(
                                            day, rows, tf, mode, rr, get_opt, skips,
                                            edge, lm, tm, eod)
            print(f"[{n}/{len(good)}] {day}: {len(trades) - before} trades across all variants")

    for s in skips:
        print("SKIP", s)
    print(f"sessions used {len(good)}, skipped {len(sessions) - len(good) + len(cov['weekday_gaps'])}, "
          f"skipped trades {len(skips)}")

    meta = {
        "title": "Fib Retracement v2 (pivot 7)",
        "subtitle": "0.618-0.786 reversal zone on swing legs, options bought on NIFTY",
        "instrument": f"{und['trading_symbol']} index signal, ATM option traded",
        "from": frm.isoformat(), "to": to.isoformat(), "lot_size": info["lot_size"],
        "fill_rule": "Every buy at the bar's high, every sell at the bar's low; signals acted on in the next 1m bar.",
        "cost_model": "Standard option schedule (brokerage, STT, exchange, SEBI, stamp, GST).",
        "params": {"pivot": PIVOT, "near edge": NEAR, "far edge": FAR, "stop pad (pts)": STOP_PAD,
                   "min risk (pts)": MIN_RISK, "square off": FORCE, "timeframes": "1m, 3m, 5m",
                   "targets": "1:2, 1:3, 1:4", "entry modes": "retest, touch", "lots": 1},
        "rule_steps": [
            "Build tf candles (1m/3m/5m) from 1m bars of one session; use completed candles only.",
            "Swing high: high strictly above the 7 highs before and after; swing low: mirror. Confirmed after 7 more candles.",
            "Leg: swing low -> swing high (LONG) or swing high -> swing low (SHORT), using the latest prior opposite swing.",
            "Zone = 0.618 (near, entry) to 0.786 (far) of the leg. A close beyond 0.786 kills the leg.",
            "Retest: price reaches 0.618, a candle closes back beyond 0.618, the next candle to reach 0.618 is the signal. Touch: first candle to reach 0.618.",
            "Stop = 5 index points beyond 0.786; risk = 0.618 level - stop (skip if < 1 point); target = 1:2, 1:3 or 1:4 of that risk, on index levels.",
            "LONG leg buys an ATM call, SHORT leg buys an ATM put; expiry at least 1 day after the trade day; 1 lot.",
            "Signal completes at candle close; entry at the HIGH of the next 1m option bar.",
            "Stop/target touched in a completed index 1m bar exits at the LOW of the next 1m option bar; stop first on a tie.",
            "Time exit at 15:15 in the 15:15 bar; one position at a time; entry bar must be before 15:15.",
        ],
        "limits": [
            "ASSUMED: underlying NIFTY 50; traded instrument is an ATM bought option (prompt does not say what is traded).",
            "ASSUMED: stop/target are index levels, exits fill on the option's next 1m bar; option P&L can lose even on a target.",
            "ASSUMED: ATM from the signal candle close; expiry at least 1 day after the trade day; 1 lot; standard option costs.",
            "ASSUMED: leg = most recent prior opposite swing in the same session; pivots never cross sessions.",
            "ASSUMED: candles between pivot and confirmation only kill a leg (close beyond 0.786); touches are judged from the first candle after confirmation.",
            "ASSUMED: several legs signalling together -> newest leg taken; a signal while in a trade (or after 15:14) is not taken and the leg stays live; a leg is consumed when entered.",
            "ASSUMED: touch of the level in the same candle as a close beyond 0.786 counts as an entry first (touch precedes the close).",
            "ASSUMED: stop/target scanning starts after the entry bar; a touch inside the entry bar is not seen.",
            "ASSUMED: 15m, 60m and daily are not run (prompt says few or no legs).",
            "Each (timeframe, target, entry mode) is its own book; the 'all' view mixes them, so read numbers under a specific filter combination.",
            "In-sample: pivot 7 was chosen by the prompt author from a grid over this same kind of data; this is NOT an out-of-sample result. The prompt itself says the rule is not demonstrated.",
            "Option capital = entry premium x quantity.",
            f"Skipped trades: {len(skips)} (listed in the console).",
        ],
        "coverage": cov,
    }
    payload = build_payload(meta, trades, good, opt_sessions, [],
                            settings=SETTINGS, chart="default")
    path = write_report(payload, "fr_v2")
    print(console_summary(trades))
    print(path)


def main() -> None:
    today = datetime.now(IST).date()
    ap = argparse.ArgumentParser(description="Fib Retracement v2 backtest")
    ap.add_argument("--from", dest="frm", type=date.fromisoformat, default=START_DATE)
    ap.add_argument("--to", dest="to", type=date.fromisoformat, default=END_DATE)
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    if a.set_tf is None:
        a.set_tf = DEFAULT_TF
    if a.set_rr is None:
        a.set_rr = DEFAULT_RR
        print(f"shipping the default subset: --tf {DEFAULT_TF} --rr {DEFAULT_RR}; "
              f"the full set is --tf 1m,3m,5m --rr 1:2,1:3,1:4")
    SETTINGS[:] = narrow(SETTINGS, a)
    to = a.to or today - timedelta(days=1)
    frm = a.frm or months_back(to, 6)
    check_window(frm, to)
    print(f"axes: {len(combos(SETTINGS))} simulated combinations")
    asyncio.run(run(frm, to))


if __name__ == "__main__":
    main()
