"""Volume Profile Range - v2 (vpr_v2)

STRATEGY PROMPT (verbatim summary of 15_vpr_v2.txt)
  v2: a break is a CROSSING (previous candle closed inside the band, this one closes beyond it);
  retest window 4 to 15 candles (was 4 to 7); 3-minute and 5-minute signals run TOGETHER as one book,
  one position at a time. Everything else is v1: previous session profiled on 5-minute candles,
  time-weighted; entry on the open after the confirming close; stop 25 points inside the broken band;
  2R target (1:3 and 1:4 scored off the same entries); exits walked on 1-minute candles; square-off 15:15.
  1 Build the previous session's profile on 5m candles, time-weighted; extend POC, VAH, VAL into today.
  2 A break is a CROSSING: previous candle CLOSED INSIDE the band, this one CLOSES BEYOND it.
  3 Close above VAH arms a long; close below VAL arms a short.
  4 4 to 15 candles after the crossing candle, price must come back and retest the band it broke.
  5 The retest candle must reach the band and still CLOSE beyond it (the level held).
  6 Entry is the OPEN of the candle after that confirming close.
  7 Stop is 25 points inside the band that broke (below VAH for a long, above VAL for a short).
  8 Risk = entry to stop; target = 2 x risk; 1:3 and 1:4 scored off the same entries.
  9 Run 3m and 5m signals together as one book, one position at a time, first come first served.
  10 Walk exits on 1-minute candles; inside one minute the order is square-off, then stop, then target.
  11 One trade a day by default; the "flow" reading (re-arms after each trade closes) is computed alongside.
  12 Square off at 15:15.

RUN.md STEP 1 CHECKLIST (non-interactive: gaps closed by ASSUMPTIONS)
  Underlying ...... ASSUMED  NIFTY 50 (prompt only says "points").
  Window .......... default  2026-01-01 through the current IST date (--from/--to).
  Timeframe ....... clear    signals on 3m and 5m (built from 1m); profile on 5m.
  Signal rule ..... partly ASSUMED (below): bin size, value-area %, band edges, retest touch.
  Decision time ... clear    close of the confirming (retest) candle; fill fixed by rules 1-2.
  Direction ....... clear    close above VAH = long, below VAL = short (index direction).
  Traded instr. ... ASSUMED  ATM NIFTY option BOUGHT: CE for a long signal, PE for a short signal.
  Option specifics  ASSUMED  ATM strike from the retest candle's close, nearest expiry >= 1 day after
                             the trade day, 1 lot (qty = lot_size of the resolved contract).
  Entry ........... clear    next 1-minute bar after the confirming candle completes (rules 1-2).
  Exit ............ clear    stop 25 pts inside band, target rr x risk (rr 2/3/4), square-off 15:15.
                             Stop/target are INDEX levels (points), checked on 1m index bars.
  Holding ......... clear    intraday.
  Costs ........... default  option_costs.
  Positions ....... clear    one at a time, first come first served; one trade a day by default.
  Missing data .... default  skip and list.
  Filters ......... clear    rr (1:2, 1:3, 1:4) and book (one per day / flow) + side.
  Group-bys ....... ASSUMED  timeframe, direction, retest gap (candles), timeframe x direction.

ASSUMPTIONS
  A1 Underlying NIFTY 50. A2 Traded instrument = bought ATM option (CE for long, PE for short), 1 lot,
  expiry rule = nearest >= 1 day after the day; stop/target measured on the INDEX (1m high/low).
  A3 Profile: price bins of 1 point; each 5m candle's time is spread equally over the bins between its
  low and high (time-weighted); value area = 70% of total weight grown out from the POC bin, adding the
  heavier neighbouring bin each step (tie: upper). VAH = upper edge of the top bin, VAL = lower edge of
  the bottom bin. "The band" = [VAL, VAH].
  A4 Previous session = the preceding session present in the feed (a holiday cannot be told apart from
  a feed miss); it must be complete or the day is skipped.
  A5 Crossing needs a previous candle in today's session (the day's first candle cannot arm).
  "Closed inside" is inclusive of the edges (VAL <= close <= VAH).
  A6 Retest touch: long low <= VAH (short high >= VAL) and close beyond the level (> VAH / < VAL).
  Candles k = 4..15 after the crossing candle; the first qualifying one is used; a candle that closes
  back inside does NOT cancel the setup. A retest shared by two crossings is one setup (earliest crossing).
  A7 Risk and target are measured from the index's worst-fill price of the entry 1m bar (long: bar high,
  short: bar low) rather than from the candle open. Risk must be > 0.
  A8 No entry at or after 15:15. A candidate whose entry falls while a position is open, or on a day that
  already has a trade (book = one per day), is dropped. Entering at the same minute as an exit is not
  allowed (entry must be after the exit bar). Same-minute tie between 3m and 5m: 3m first.
  A9 If a candidate is skipped for data reasons the next candidate of the day may still be taken.
  A10 Strike step is read from the LIVE chain (may differ from the historical step).
  A11 In-sample: the retest window (4-15) was tuned on this kind of data by the prompt's author.
"""
import argparse
import asyncio
import math
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: F401,F403,E402

REPORT = "vpr_v2"
BIN = 1.0
VA_PCT = 0.70
RETEST_MIN, RETEST_MAX = 4, 15
STOP_PTS = 25.0
FORCE = "15:15"
LAST_ENTRY = "15:15"
RRS = [2, 3, 4]
BOOKS = ["one per day", "flow"]
TFS = [3, 5]
SESSION_KEYS = [f"{m // 60:02d}:{m % 60:02d}" for m in range(9 * 60 + 15, 15 * 60 + 30)]

# The axes the source (va_retest_v2) compares. All are re-simulations of bars already fetched.
# The timeframe is NOT swept here: this rule runs 3m and 5m TOGETHER as one book (its Step 9),
# so it stays a tag and "any" is the strategy as it trades.
CONFIRMS = [("close", "reaches the band and closes beyond it"),
            ("touch", "reaches the band; no close test"),
            ("two-candle", "a later candle closes beyond it after the touch")]
STOP_MODES = [("band", "inside the broken band - the spec"),
              ("entry", "a fixed distance from the entry price")]
EOD_MODES = [("close", "square off at the session close time"),
             ("hold", "run to stop or target, give up at the last candle")]
READINGS = [("mirror", "the short stop mirrored to VAL + 25"),
            ("literal", "the spec word for word - the short stop at VAH + 25")]
REENTRIES = [("on", "keep taking setups after a stop"),
             ("off", "take the stop and stand down for the day")]
RULE = {"confirm": "close", "stop_mode": "band", "eod": "close", "book": "one per day",
        "reading": "mirror", "reentry": "on"}

SETTINGS = [
    setting("confirm", "Retest confirmation", kind="entry", default=RULE["confirm"],
            options=[{"value": k, "label": v, "raw": k} for k, v in CONFIRMS]),
    setting("rr", "Reward:risk", kind="exit", values=[f"1:{r}" for r in RRS], default="1:2"),
    setting("stop_mode", "Stop anchor", kind="exit", default=RULE["stop_mode"],
            options=[{"value": k, "label": v, "raw": k} for k, v in STOP_MODES]),
    setting("eod", "End of day", kind="exit", default=RULE["eod"],
            options=[{"value": k, "label": v, "raw": k} for k, v in EOD_MODES]),
    setting("book", "Position rule", kind="sizing", default=RULE["book"],
            options=[{"value": k, "label": k, "raw": k} for k in BOOKS]),
    setting("reading", "Short-stop reading", kind="exit", default=RULE["reading"],
            options=[{"value": k, "label": v, "raw": k} for k, v in READINGS]),
    setting("reentry", "After a stop", kind="entry", default=RULE["reentry"],
            options=[{"value": k, "label": v, "raw": k} for k, v in REENTRIES]),
]


def _vals(key):
    return [o["raw"] for o in next(x for x in SETTINGS if x["key"] == key)["options"]]


# ---------------------------------------------------------------------------
# signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def session_problem(rows: list[list]) -> str | None:
    if [r[0] for r in rows] != SESSION_KEYS:
        return f"incomplete/duplicated session ({len(rows)} bars, expected 375)"
    for r in rows:
        if not (r[2] >= r[3] and r[3] <= r[1] <= r[2] and r[3] <= r[4] <= r[2]):
            return f"invalid candle at {r[0]}"
    return None


def volume_profile(rows5: list[list]) -> dict:
    """Time-weighted profile: each 5m candle's time is spread equally over the bins between its low and high."""
    w: dict[int, float] = {}
    for r in rows5:
        lo, hi = math.floor(r[3] / BIN), math.floor(r[2] / BIN)
        for k in range(lo, hi + 1):
            w[k] = w.get(k, 0.0) + 1.0 / (hi - lo + 1)
    keys = sorted(w)
    mid = (min(r[3] for r in rows5) + max(r[2] for r in rows5)) / 2 / BIN
    poc_k = max(keys, key=lambda k: (w[k], -abs(k - mid)))
    total = sum(w.values())
    lo_i = hi_i = keys.index(poc_k)
    acc = w[poc_k]
    while acc < VA_PCT * total and (lo_i > 0 or hi_i < len(keys) - 1):
        up = w[keys[hi_i + 1]] if hi_i < len(keys) - 1 else -1.0
        dn = w[keys[lo_i - 1]] if lo_i > 0 else -1.0
        if up >= dn:
            hi_i += 1; acc += w[keys[hi_i]]
        else:
            lo_i -= 1; acc += w[keys[lo_i]]
    return {"poc": (poc_k + 0.5) * BIN, "vah": (keys[hi_i] + 1) * BIN, "val": keys[lo_i] * BIN}


def find_setups(rows_1m: list[list], prof: dict, confirm: str = "close") -> list[dict]:
    """Crossings, then the first retest 4..15 candles later that reaches the band and closes beyond it.
    Uses only candles up to and including the confirming (retest) candle."""
    vah, val = prof["vah"], prof["val"]
    out: dict[tuple, dict] = {}
    for tf in TFS:
        c = resample(rows_1m, tf)
        for i in range(1, len(c)):
            prev_in = val <= c[i - 1][4] <= vah
            if not prev_in:
                continue
            if c[i][4] > vah:
                side = "LONG"
            elif c[i][4] < val:
                side = "SHORT"
            else:
                continue
            for j in range(i + RETEST_MIN, min(i + RETEST_MAX, len(c) - 1) + 1):
                lvl = vah if side == "LONG" else val
                reach = (c[j][3] <= lvl) if side == "LONG" else (c[j][2] >= lvl)
                beyond = (c[j][4] > lvl) if side == "LONG" else (c[j][4] < lvl)
                if not reach:
                    continue
                jj = None
                if confirm == "close" and beyond:
                    jj = j
                elif confirm == "touch":
                    jj = j
                elif confirm == "two-candle":
                    for mm in range(j + 1, len(c)):        # the first LATER close beyond the band
                        if (c[mm][4] > lvl) if side == "LONG" else (c[mm][4] < lvl):
                            jj = mm
                            break
                if jj is None:
                    continue
                j = jj
                eb = bar_after_candle(rows_1m, c[j][0], tf)          # strict: next 1m bar
                if eb is None or eb[0] >= LAST_ENTRY:
                    break
                key = (tf, j, side)
                if key not in out:
                    out[key] = {"tf": tf, "side": side, "cross_start": c[i][0], "retest_start": c[j][0],
                                "gap": j - i, "spot": c[j][4], "entry_bar": eb, "cstart": c[j][0],
                                "vah": vah, "val": val, "poc": prof["poc"]}
                break
    return sorted(out.values(), key=lambda s: (s["entry_bar"][0], s["tf"]))


# ---------------------------------------------------------------------------
# simulate (pure: setups + bars -> trades)
# ---------------------------------------------------------------------------
def simulate_book(day: str, setups: list[dict], idx_rows: list[list], rr: int, book: str,
                  skips: set, stop_mode: str = "band", eod: str = "close",
                  reading: str = "mirror", reentry: str = "on", confirm: str = "close") -> list[dict]:
    trades: list[dict] = []
    free = ""
    stopped = False
    for s in setups:
        if book == "one per day" and trades:
            break
        if stopped and reentry == "off":
            break                                    # took the stop and stood down
        et = s["entry_bar"][0]
        if et <= free:
            continue
        if s["opt"] is None:
            skips.add(f"{day} {s['tf']}m {s['side']} retest {s['retest_start']}: {s['opt_why']}")
            continue
        contract, orows = s["opt"]
        side = s["side"]                                              # index direction
        eb = s["entry_bar"]
        ref = eb[2] if side == "LONG" else eb[3]                      # worst fill on the index (A7)
        if stop_mode == "entry":
            stop = ref - STOP_PTS if side == "LONG" else ref + STOP_PTS
        elif side == "LONG":
            stop = s["vah"] - STOP_PTS
        else:                                        # the spec's short stop is ambiguous
            stop = (s["vah"] if reading == "literal" else s["val"]) + STOP_PTS
        risk = (ref - stop) if side == "LONG" else (stop - ref)
        if risk <= 0:
            skips.add(f"{day} {s['tf']}m {side} retest {s['retest_start']}: risk<=0 (entry {ref} vs stop {stop})")
            continue
        target = ref + rr * risk if side == "LONG" else ref - rr * risk
        res = scan_exit(idx_rows, side, et, stop, target, FORCE if eod == "close" else None)
        if res["bar"] is None:
            skips.add(f"{day} {s['tf']}m {side} retest {s['retest_start']}: exit not found ({res['reason']})")
            continue
        oe = bar_after_candle(orows, s["cstart"], s["tf"])
        xk = res["bar"][0]
        ox = next((r for r in orows if r[0] == xk), None)
        if oe is None or ox is None:
            skips.add(f"{day} {s['tf']}m {side} retest {s['retest_start']}: option bar missing "
                      f"({contract['trading_symbol']}, entry {'ok' if oe else 'missing'}, exit {xk} {'ok' if ox else 'missing'})")
            continue
        epx, xpx = worst_fills("LONG", oe, ox)                       # option is always bought
        mfe, mae = excursion(orows, "LONG", epx, oe[0], ox[0])
        qty = contract["lot_size"]
        levels = [{"name": "VAH", "price": s["vah"], "from": "09:15", "to": "15:29"},
                  {"name": "VAL", "price": s["val"], "from": "09:15", "to": "15:29"},
                  {"name": "POC", "price": s["poc"], "from": "09:15", "to": "15:29"},
                  {"name": f"stop ({STOP_PTS:g} pts inside band)", "price": stop, "from": et, "to": xk},
                  {"name": f"target 1:{rr}", "price": target, "from": et, "to": xk}]
        trades.append(make_trade(
            day=day, side="LONG", symbol=contract["trading_symbol"], entry_time=oe[0], entry_px=epx,
            exit_time=ox[0], exit_px=xpx, qty=qty, exit_reason=res["reason"], kind="option",
            capital=epx * qty, stop=None, target=None, mfe=mfe, mae=mae,
            variant={"rr": f"1:{rr}", "book": book, "confirm": confirm, "stop_mode": stop_mode,
                     "eod": eod, "reading": reading, "reentry": reentry},
            tags={"timeframe": f"{s['tf']}m", "direction": "long (buy CE)" if side == "LONG" else "short (buy PE)",
                  "retest gap": bucket(s["gap"], [7, 11], ["4-6 candles", "7-10 candles", "11-15 candles"])},
            levels=levels, expiry=contract["expiry"], option_type=contract["option_type"],
            note=f"{s['tf']}m crossing {s['cross_start']}, retest {s['retest_start']} (+{s['gap']}); index entry ref {ref:.2f}, "
                 f"stop {stop:.2f}, target {target:.2f}"))
        free = xk
        stopped = "stop" in (res["reason"] or "").lower()
    return trades


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
async def run(frm: date, to: date) -> None:
    skips: set[str] = set()
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        ukey = und["instrument_key"]
        info = await up.option_chain_info(ukey)
        step = info["strike_step"]
        cal = await up.expiry_calendar(ukey, frm, to)
        cs = await up.candles(ukey, "1m", frm - timedelta(days=10), to)
        sessions = sessions_from(cs)
        now = datetime.now(IST)
        if now.date().isoformat() in sessions and now.strftime("%H:%M") < "15:45":
            sessions.pop(now.date().isoformat())                     # rule 7: today not over
        all_days = sorted(sessions)
        window = [d for d in all_days if frm.isoformat() <= d <= to.isoformat()]
        cov = coverage({d: sessions[d] for d in window}, frm, to, 375)
        print(f"{len(window)} sessions in window; weekday gaps: {cov['weekday_gaps']}")

        contracts: dict = {}
        rows_cache: dict = {}
        setups_by_day: dict[str, list[dict]] = {}
        for d in window:
            why = session_problem(sessions[d])
            k = all_days.index(d)
            prev = all_days[k - 1] if k > 0 else None
            if why:
                print(f"SKIP {d}: {why}"); continue
            if prev is None:
                print(f"SKIP {d}: no previous session in the data"); continue
            pw = session_problem(sessions[prev])
            if pw:
                print(f"SKIP {d}: previous session {prev} {pw}"); continue
            prof = volume_profile(resample(sessions[prev], 5))
            setups = []
            for _cf in _vals("confirm"):
                for _s in find_setups(sessions[d], prof, _cf):
                    _s["confirm"] = _cf
                    setups.append(_s)
            expiry = next_expiry(cal, date.fromisoformat(d), 1)
            for s in setups:
                s["opt"], s["opt_why"] = None, ""
                if expiry is None:
                    s["opt_why"] = "no expiry >= 1 day after"; continue
                otype = "CE" if s["side"] == "LONG" else "PE"
                strike = atm_strike(s["spot"], step)
                ck = (expiry, strike, otype)
                if ck not in contracts:
                    try:
                        contracts[ck] = await up.resolve_option(ukey, expiry, strike, otype)
                    except (RuntimeError, LookupError) as exc:
                        print(f"  ! contract lookup failed {ck}: {exc}"); contracts[ck] = None
                c = contracts[ck]
                if not c or not c["lot_size"]:
                    s["opt_why"] = f"no contract {otype} {strike:g} exp {expiry}"; continue
                rk = (c["instrument_key"], d)
                if rk not in rows_cache:
                    try:
                        rows_cache[rk] = await up.option_candles(c, date.fromisoformat(d))
                    except (RuntimeError, LookupError) as exc:
                        print(f"  ! option bars failed {c['trading_symbol']} {d}: {exc}"); rows_cache[rk] = []
                if not rows_cache[rk]:
                    s["opt_why"] = f"no option bars for {c['trading_symbol']}"; continue
                s["opt"] = (c, rows_cache[rk])
            setups_by_day[d] = setups
            if not setups:
                print(f"no setup {d} (VAL {prof['val']:.0f} POC {prof['poc']:.0f} VAH {prof['vah']:.0f})")

        trades: list[dict] = []
        for d, setups in setups_by_day.items():
            if not setups:
                continue
            for cf in _vals("confirm"):
                mine = [s for s in setups if s["confirm"] == cf]
                if not mine:
                    continue
                for rr in _vals("rr"):
                    rr_n = int(str(rr).split(":")[1]) if ":" in str(rr) else int(rr)
                    for book in _vals("book"):
                        for stop_mode in _vals("stop_mode"):
                            for eod in _vals("eod"):
                                for reading in _vals("reading"):
                                    for reentry in _vals("reentry"):
                                        trades += simulate_book(
                                            d, mine, sessions[d], rr_n, book, skips,
                                            stop_mode, eod, reading, reentry, cf)
        for m in sorted(skips):
            print("SKIP", m)
        if not trades:
            print("0 trades; no report written"); return

    option_sessions: dict[str, dict] = {}
    sym_by_key = {c["instrument_key"]: c["trading_symbol"] for c in contracts.values() if c}
    for (ik, d), rows in rows_cache.items():
        option_sessions.setdefault(sym_by_key[ik], {})[d] = rows

    meta = {
        "title": "Volume Profile Range v2", "subtitle": "Previous-session value area, crossing + retest, 3m and 5m as one book",
        "instrument": "NIFTY 50 signal; bought ATM option (CE long / PE short)", "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": "from each resolved contract",
        "fill_rule": "Every buy at its bar's HIGH, every sell at its bar's LOW; signals acted on in the next 1-minute bar",
        "cost_model": "option_costs (brokerage, STT, exchange, SEBI, stamp, GST)",
        "params": {"profile candles": "5m, time-weighted, 1-pt bins", "value area": "70%", "retest window": "4-15 candles",
                   "stop": "25 pts inside band", "target": "1:2 / 1:3 / 1:4", "square-off": FORCE, "signal timeframes": "3m + 5m"},
        "rule_steps": [
            "Profile the previous session on 5m candles, time-weighted; VAH/VAL/POC extended into today.",
            "A crossing: previous candle closed inside [VAL, VAH], this candle closes above VAH (long) or below VAL (short).",
            "4 to 15 candles later a candle must reach the band and still close beyond it.",
            "Entry: the 1-minute bar after that candle completes; buy the ATM CE (long) / PE (short) at that bar's high.",
            "Stop 25 index points inside the broken band; target rr x risk from the index entry reference; rr 2, 3, 4.",
            "Stop/target touched in a completed 1m index bar exits in the next 1m option bar at its low; both in one bar = stop first.",
            "Square off at 15:15 in that bar (sell at its low). 3m and 5m signals share one book, one position at a time.",
            "Book 'one per day' takes the first trade only; 'flow' re-arms after each trade closes."],
        "limits": [
            "ASSUMED: underlying NIFTY 50; traded instrument is a bought ATM option (prompt only says points).",
            "ASSUMED: 1-point bins, 70% value area from POC (heavier neighbour first), VAH/VAL = bin edges; band = [VAL, VAH].",
            "ASSUMED: crossing needs a previous candle today; 'inside' is inclusive; retest = low<=VAH / high>=VAL and close beyond; first such candle, no cancel on a close back inside.",
            "ASSUMED: risk/target measured from the index worst-fill of the entry 1m bar, not the candle open; stop/target on index, exits in the option.",
            "ASSUMED: ATM strike from the retest close, live strike step, expiry >= 1 day after the day, 1 lot; no entry at/after 15:15; 3m before 5m on a tie.",
            "Prompt's 'open of the next candle' fill replaced by the rule-1 worst fill (next 1m bar high) - results are worse than the prompt's.",
            "Prompt's stop/target 'exact level' style exits replaced by exit in the next 1m bar at its low (rules 1 and 3).",
            "The 'day-clustered' significance the prompt asks for is NOT computed: the report's t-stat is pooled and overstates the case (3m and 5m fire on the same sessions).",
            "In-sample: the 4-15 retest window and rr ladder were chosen by looking at data of this kind; all variants are shown as filters.",
            "Capital = premium x qty. Previous session = preceding session in the feed (holiday vs feed miss not distinguished).",
        ],
        "coverage": cov,
    }
    groups = [{"name": "Timeframe", "keys": ["timeframe"]}, {"name": "Direction", "keys": ["direction"]},
              {"name": "Retest gap", "keys": ["retest gap"]}, {"name": "Timeframe x direction", "keys": ["timeframe", "direction"]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups,
                            settings=SETTINGS, chart="default")
    path = write_report(payload, REPORT)
    print(console_summary(trades))
    print(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat())
    ap.add_argument("--to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    SETTINGS[:] = narrow(SETTINGS, a)
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    check_window(frm, to)
    print(f"axes: {len(combos(SETTINGS))} simulated combinations "
          f"(3m and 5m run TOGETHER as one book, so the timeframe is a tag, not an axis)")
    asyncio.run(run(frm, to))


if __name__ == "__main__":
    main()
