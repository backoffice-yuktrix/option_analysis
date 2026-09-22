"""Supply and Demand - v1  (slug: snd_v1)

STRATEGY PROMPT (verbatim):
    v1 SnD
    ### v1 - the zone, the sweep and the micro break
    Step 1 - A swing high is a candle whose high is higher than the 3 highs before it and the 3 highs
    after it, and a swing low is the opposite; a swing only counts once 3 candles have closed after it,
    so I can never use one that has not been confirmed yet.
    Step 2 - The first candle of the day that CLOSES beyond the most recent confirmed swing sets the
    direction for the day: closing above a swing high makes it bullish, closing below a swing low makes
    it bearish.
    Step 3 - A wick through the swing is not a break, it has to be the close, and only the first break
    of the day counts - later breaks never change the direction and never build a new zone.
    Step 4 - The zone is the last opposite-coloured candle in the 3 candles before the break - the last
    red candle before a bullish break, the last green one before a bearish break - taken as its full
    range, low to high; a bullish break gives a demand zone and a bearish one gives a supply zone.
    Step 5 - If none of those 3 candles is the opposite colour, there is no zone and the day is over.
    Step 6 - Now wait for price to come back and touch the zone, meaning the candle's low is at or below
    the zone high and its high is at or above the zone low; a touch on its own is not an entry, it only
    arms the setup.
    Step 7 - After that, three things have to happen in order: one candle must trade below the most
    recent confirmed minor swing low (the sweep), that same candle must close back above that low (the
    recovery), and then a later candle must close above the most recent confirmed minor swing high (the
    micro break).
    Step 8 - The entry is the CLOSE of that micro break candle, and I buy there. A short is the exact
    mirror - sweep above a swing high, close back below it, then a later candle closes below a swing low.
    Step 9 - One candle cannot be both the sweep and the micro break; if it does both it just counts as
    a fresh sweep, and if a new sweep prints before the micro break arrives it replaces the old one.
    Step 10 - The stop goes behind whichever is further away, the zone or the sweep: for a long, the
    lower of the zone low and that sweep candle's low, and the mirror for a short.
    Step 11 - Risk is the entry minus the stop for a long, and the stop minus the entry for a short; if
    the risk works out at less than 1 point there is no trade, and the day's single slot is used up
    either way.
    Step 12 - The target is the entry plus 2 times the risk for a long, and the mirror for a short; also
    score 1:1, 1:3 and 1:5 off the same entries.
    Step 13 - The setup dies if any candle CLOSES more than 4 zone widths past the far edge of the zone -
    below a demand zone's low or above a supply zone's high - and when that happens the day is over, with
    no flipping the zone and no trade the other way.
    Step 14 - Check that death test first on every candle, before the touch test and before the entry
    test, so a candle that dips into the zone and also closes that far past it counts as the death, not
    as a touch.
    Step 15 - One trade a day at most, and once I am in, the zone dying no longer matters - the position
    runs to its stop, its target or the square-off.
    Step 16 - Watch the stop and target on 1-minute prices starting from the candle after the entry
    candle; the stop is a resting order filled at its level, or at the minute's open if a minute opens
    already through it, and inside any one minute the order is square-off first, then the stop, then the
    target.
    Step 17 - Square off anything still open at 15:15, and stop looking for new setups at 15:15 as well.
    Step 18 - The whole rule runs on 3-minute candles by default and on 1-minute alongside it. The
    timeframe changes which swings exist, so it changes the trades themselves, not just the exits.
    The other reading of the stop - close-confirmed, where the position is only closed once a candle
    CLOSES beyond the level and the fill is that close - is computed beside it, because a close-confirmed
    stop does not cap the loss at 1R and the difference has to stay visible.

CHECKLIST (RUN.md Step 1) - non-interactive, so gaps were closed by ASSUMPTION
    1 Underlying        ASSUMED  NIFTY 50 index (the prompt names none).
    2 Window            ASSUMED  default: 2026-01-01 through the current IST date (--from / --to override).
    3 Signal timeframe  clear    3m and 1m, both built from 1-minute candles, shown as variant tf.
    4 Signal rule       clear except: "minor swing" has no number -> ASSUMED 1 candle each side
                        (higher/lower than the 1 candle before and the 1 after, confirmed once 1 candle
                        has closed after it); swings are taken from the SAME DAY's candles only (no
                        carry-over from the previous day); a doji (close = open) is neither red nor
                        green; the break candle itself cannot touch/arm the zone (touch is tested from
                        the next candle on); the touch candle cannot also be the sweep (sweep is tested
                        on candles after the touch); a swing is "confirmed" for candle k only if the
                        n candles after it had all closed before candle k opened.
    5 Decision time     clear    signal candle = the micro break candle; no new setup once the entry
                        bar would start at or after 15:15 (setups looked for while the candle
                        completes by 15:14).
    6 Direction         ASSUMED  bullish -> buy ATM CE, bearish -> buy ATM PE (prompt says "buy" and
                        "short" on the index only).  The index levels (zone, stop, target) drive the
                        exits; the option is what is bought and sold.
    7 Traded instrument ASSUMED  NIFTY weekly/monthly option (see 6): only the option cost schedule is
                        available, and RUN.md forbids guessing rates for index/futures.
    8 Option specifics  ASSUMED  buy; ATM strike from the signal candle's close; expiry = nearest at
                        least 1 day after the exit day; 1 lot (qty from the resolved contract).
    9 Entry             clear    micro break; fill by the Rules (next 1m bar, option bar HIGH).
    10 Exit             clear    index-level stop / target (RR 1:1, 1:2, 1:3, 1:5) evaluated on 1m
                        index bars from the bar after the entry bar; time exit 15:15 (fills in that
                        bar); stop first if a bar touches both; square-off first inside a bar.
    11 Holding          clear    intraday.
    12 Costs            ASSUMED  standard option schedule (option_costs).
    13 Position rules   clear    one trade a day per variant; no re-entry; the day's slot is used even
                        when risk < 1 point.
    14 Missing data     ASSUMED  skip and list (default); a session must be the full 375 contiguous 1m bars.
    15 Filters          clear    side x tf (3m, 1m) x rr (1:1, 1:2, 1:3, 1:5) x stop (touch, close).
    16 Group-bys        ASSUMED  only "direction" (long CE / short PE); none requested.
    17 Script name      snd_v1

RULES TO LIVE BY OVERRIDE THE PROMPT (see meta["limits"]): entry is not the signal candle's close but the
next 1m option bar's HIGH; a stop is not a resting order filled at its level/open but a signal that exits
in the next 1m bar at that bar's LOW; a close-confirmed stop does not fill at the close but in the next 1m
bar; a target does the same.  The risk and the target are still measured from the signal candle's close
on the index (that is the strategy's reference level).

Run:  analysis\\.venv\\Scripts\\python.exe analysis\\scripts\\snd_v1.py [--from YYYY-MM-DD] [--to YYYY-MM-DD]
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *

import argparse

SLUG = "snd_v1"
SWING_N = 3                 # major swing: 3 candles each side (prompt)
MINOR_N = 1                 # ASSUMED minor swing: 1 candle each side
DEATH_WIDTHS = 4.0          # prompt
MIN_RISK = 1.0              # index points (prompt)
RRS = [1.0, 2.0, 3.0, 5.0]  # 2 is the base, 1/3/5 alongside (prompt)
TFS = [3, 1]
STOP_MODES = ["touch", "close"]

# The axes the source (nes_supply_demand_v1) compares. All are re-simulations of fetched bars.
STOP_ANCHORS = [("zone", "far side of the zone, or the sweep - the spec"),
                ("sweep", "the sweep candle's extreme"),
                ("bos", "the micro-BOS candle's extreme"),
                ("tight", "the nearer of the sweep and the micro-BOS candle")]
TARGET_MODES = [("rr", "fixed R:R"),
                ("liq", "opposing liquidity")]
EOD_MODES = [("close", "square off at the session close time"),
             ("hold", "run to stop or target, give up at the last candle")]
NEVER = "99:99"                 # a force-exit key later than any bar: "hold" runs to the end
RULE = {"anchor": "zone", "target_mode": "rr", "eod": "close", "stop": "touch"}

SETTINGS = [
    setting("tf", "Signal timeframe", kind="other", values=[f"{t}m" for t in TFS], default="3m"),
    setting("rr", "Reward:risk", kind="exit", values=[f"1:{r:g}" for r in RRS], default="1:2"),
    setting("stop", "Stop trigger", kind="exit", values=STOP_MODES, default=RULE["stop"],
            help="an order resting at the level, or a candle CLOSE beyond it"),
    setting("anchor", "Stop anchor", kind="exit", default=RULE["anchor"],
            options=[{"value": k, "label": v, "raw": k} for k, v in STOP_ANCHORS]),
    setting("target_mode", "Target", kind="exit", default=RULE["target_mode"],
            options=[{"value": k, "label": v, "raw": k} for k, v in TARGET_MODES]),
    setting("eod", "End of day", kind="exit", default=RULE["eod"],
            options=[{"value": k, "label": v, "raw": k} for k, v in EOD_MODES]),
]


def _vals(key):
    return [o["raw"] for o in next(x for x in SETTINGS if x["key"] == key)["options"]]


def anchored_stop(setup: dict, anchor: str) -> float:
    """The stop for one anchor.  'zone' is the spec: the far side of the zone, or the sweep,
    whichever is further away.  The others are the source's alternatives."""
    short = setup["direction"] != "long"
    sweep, bos = setup["sweep_extreme"], setup["bos_extreme"]
    far = setup["zone_high"] if short else setup["zone_low"]
    if anchor == "sweep":
        return sweep
    if anchor == "bos":
        return bos
    if anchor == "tight":
        return min(sweep, bos) if short else max(sweep, bos)
    return max(far, sweep) if short else min(far, sweep)
LAST_SIGNAL_DONE = "15:14"  # the entry bar must start before 15:15
SQUARE_OFF = "15:15"
FULL_TIMES = [f"{m // 60:02d}:{m % 60:02d}" for m in range(9 * 60 + 15, 15 * 60 + 30)]   # 375 minutes


# ---------------------------------------------------------------------------
# signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def swing_flags(rows: list[list], n: int) -> tuple[list[bool], list[bool]]:
    """Swing high / low flags at each candle j (needs n candles either side, strict).  A flag at j is
    only ever READ once candle j+n has closed (see last_swing)."""
    hi, lo = [r[2] for r in rows], [r[3] for r in rows]
    sh, sl = [False] * len(rows), [False] * len(rows)
    for j in range(n, len(rows) - n):
        sh[j] = hi[j] > max(hi[j - n:j]) and hi[j] > max(hi[j + 1:j + n + 1])
        sl[j] = lo[j] < min(lo[j - n:j]) and lo[j] < min(lo[j + 1:j + n + 1])
    return sh, sl


def last_swing(flags: list[bool], n: int, i: int) -> int | None:
    """Most recent swing confirmed BEFORE candle i opened: j + n <= i - 1."""
    for j in range(i - 1 - n, n - 1, -1):
        if flags[j]:
            return j
    return None


def find_setup(rows: list[list], tf: int) -> dict:
    """One day of `tf`-minute candles -> {"status": ..., ...}.  status 'signal' carries the setup."""
    o = [r[1] for r in rows]; h = [r[2] for r in rows]; l = [r[3] for r in rows]; c = [r[4] for r in rows]
    sh, sl = swing_flags(rows, SWING_N)
    msh, msl = swing_flags(rows, MINOR_N)
    ok = lambda k: candle_done_at(rows[k][0], tf) <= LAST_SIGNAL_DONE

    # steps 2-3: the day's first candle that closes beyond the most recent confirmed swing
    brk = direction = None
    for i in range(len(rows)):
        if not ok(i):
            break
        a, b = last_swing(sh, SWING_N, i), last_swing(sl, SWING_N, i)
        if a is not None and c[i] > h[a]:
            brk, direction = i, "long"; break
        if b is not None and c[i] < l[b]:
            brk, direction = i, "short"; break
    if brk is None:
        return {"status": "no break of a confirmed swing before 15:15"}

    # steps 4-5: zone = last opposite-coloured candle among the 3 before the break
    zi = None
    for k in range(brk - 1, max(brk - 1 - 3, -1), -1):
        if (direction == "long" and c[k] < o[k]) or (direction == "short" and c[k] > o[k]):
            zi = k; break
    if zi is None:
        return {"status": f"{direction} break at {rows[brk][0]} but no opposite-coloured candle in the 3 before it (no zone)"}
    zl, zh = l[zi], h[zi]
    width = zh - zl

    found = False
    armed, sweep = False, None          # sweep = (candle index, its extreme, swept level)
    for k in range(brk + 1, len(rows)):
        if not ok(k):
            break
        # step 13/14: death first
        if direction == "long" and c[k] < zl - DEATH_WIDTHS * width:
            return {"status": f"zone died at {rows[k][0]} (close {c[k]:.2f} beyond 4 widths below the demand zone)"}
        if direction == "short" and c[k] > zh + DEATH_WIDTHS * width:
            return {"status": f"zone died at {rows[k][0]} (close {c[k]:.2f} beyond 4 widths above the supply zone)"}
        if not armed:                    # step 6
            if l[k] <= zh and h[k] >= zl:
                armed = True
            continue
        a, b = last_swing(msh, MINOR_N, k), last_swing(msl, MINOR_N, k)   # minor high / low index
        if direction == "long":
            if b is not None and l[k] < l[b] and c[k] > l[b]:               # sweep + recovery (also wins over a micro break, step 9)
                sweep = (k, l[k], l[b]); continue
            if sweep is not None and a is not None and c[k] > h[a]:         # micro break
                entry_ref = c[k]
                stop = min(zl, sweep[1])
                risk = entry_ref - stop
                break_k = k
                found = True
                break
        else:
            if a is not None and h[k] > h[a] and c[k] < h[a]:
                sweep = (k, h[k], h[a]); continue
            if sweep is not None and b is not None and c[k] < l[b]:
                entry_ref = c[k]
                stop = max(zh, sweep[1])
                risk = stop - entry_ref
                break_k = k
                found = True
                break
    if not found:
        return {"status": ("sweep seen but no micro break before 15:15" if sweep is not None else
                           "zone touched but no sweep before 15:15" if armed else
                           "zone never touched before 15:15")}
    if risk < MIN_RISK:
        return {"status": f"risk {risk:.2f} pts < {MIN_RISK:g}: no trade, the day's slot is used"}
    # the alternatives the source compares need the micro-BOS extreme and the opposing
    # liquidity, both read from candles complete at the signal (rule 4)
    bos_extreme = h[break_k] if direction != "long" else l[break_k]
    before = rows[:break_k]
    if direction == "long":
        cands = [max((r[2] for r in before), default=None),
                 max((h[k] for k in range(break_k) if sh[k]), default=None)]
        cands = [x for x in cands if x is not None and x > entry_ref]
        liq = max(cands) if cands else None
    else:
        cands = [min((r[3] for r in before), default=None),
                 min((l[k] for k in range(break_k) if sl[k]), default=None)]
        cands = [x for x in cands if x is not None and x < entry_ref]
        liq = min(cands) if cands else None
    return {"status": "signal", "direction": direction, "tf": tf, "signal_start": rows[break_k][0],
            "signal_close": entry_ref, "stop": stop, "risk": risk, "zone_low": zl, "zone_high": zh,
            "zone_time": rows[zi][0], "break_time": rows[brk][0], "sweep_time": rows[sweep[0]][0],
            "sweep_level": sweep[2], "sweep_extreme": sweep[1],
            "bos_extreme": bos_extreme, "liq": liq}


# ---------------------------------------------------------------------------
# simulate (pure: bars -> exit)
# ---------------------------------------------------------------------------
def scan_close_stop(bars: list[list], side: str, entry_key: str, stop: float, target: float,
                    force_key: str) -> dict:
    """Close-confirmed stop: the 1m bar must CLOSE beyond the stop; that is a signal, so the exit is
    the next 1m bar (rule 3).  The target is a touch (as everywhere).  Stop first if both in one
    bar; the square-off bar exits in itself.  Same return shape as scan_exit."""
    for i, r in enumerate(bars):
        if r[0] <= entry_key:
            continue
        if r[0] == force_key:
            return {"bar": r, "reason": "time exit", "trigger": None}
        hit_stop = r[4] < stop if side == "LONG" else r[4] > stop
        hit_tgt = r[2] >= target if side == "LONG" else r[3] <= target
        if hit_stop or hit_tgt:
            nxt = bars[i + 1] if i + 1 < len(bars) else None
            if nxt is not None and nxt[0] > force_key:
                nxt = None
            return {"bar": nxt, "reason": "stop (close-confirmed)" if hit_stop else "target", "trigger": r}
    return {"bar": None, "reason": "no exit found", "trigger": None}


def simulate(setup: dict, rr: float, mode: str, idx1: list[list], opt: list[list],
             anchor: str = "zone", target_mode: str = "rr", eod: str = "close") -> dict:
    """Index-level exit scan, then the fills on the OPTION's bars (bought option = LONG)."""
    d = setup["direction"]
    iside = "LONG" if d == "long" else "SHORT"
    entry_bar = bar_after_candle(idx1, setup["signal_start"], setup["tf"])
    if entry_bar is None:
        return {"skip": "entry bar (1m after the signal candle) missing in the index data"}
    if entry_bar[0] >= SQUARE_OFF:
        return {"skip": f"entry bar {entry_bar[0]} is not before {SQUARE_OFF}"}
    sgn = 1 if d == "long" else -1
    stop = anchored_stop(setup, anchor)
    risk = (setup["signal_close"] - stop) if d == "long" else (stop - setup["signal_close"])
    if risk < MIN_RISK:
        return {"skip": f"{anchor} stop gives risk {risk:.2f} pts < {MIN_RISK:g}"}
    if target_mode == "liq":
        target = setup.get("liq")
        if target is None:
            return {"skip": "no opposing liquidity beyond the entry"}
    else:
        target = setup["signal_close"] + sgn * rr * risk
    force = SQUARE_OFF if eod == "close" else NEVER
    if mode == "touch":
        ex = scan_exit(idx1, iside, entry_bar[0], stop, target, force)
    else:
        ex = scan_close_stop(idx1, iside, entry_bar[0], stop, target, force)
    if ex["bar"] is None:
        return {"skip": f"no exit bar ({ex['reason']}"
                        f"{', trigger ' + ex['trigger'][0] if ex['trigger'] else ''})"}
    by = {r[0]: r for r in opt}
    ob_in, ob_out = by.get(entry_bar[0]), by.get(ex["bar"][0])
    if ob_in is None:
        return {"skip": f"option bar missing at entry {entry_bar[0]}"}
    if ob_out is None:
        return {"skip": f"option bar missing at exit {ex['bar'][0]}"}
    epx, xpx = worst_fills("LONG", ob_in, ob_out)
    return {"entry_bar": entry_bar, "exit_bar": ex["bar"], "reason": ex["reason"], "trigger": ex["trigger"],
            "entry_px": epx, "exit_px": xpx, "target": target, "stop": stop, "risk": risk}


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
def default_window() -> tuple[date, date]:
    to = datetime.now(IST).date() - timedelta(days=1)
    return to - timedelta(days=182), to


async def fetch_index(up: Upstox, key: str, frm: date, to: date) -> dict[str, list[list]]:
    return sessions_from(await up.candles(key, "1m", frm, to))


def session_problem(day: str, rows: list[list]) -> str | None:
    times = [r[0] for r in rows]
    if len(times) != len(set(times)):
        return "duplicate 1m candles"
    if times != FULL_TIMES:
        missing = sorted(set(FULL_TIMES) - set(times))
        return f"incomplete session: {len(times)} of 375 bars" + (f", first missing {missing[0]}" if missing else "")
    if any(not (r[3] <= min(r[1], r[4]) and r[2] >= max(r[1], r[4])) or r[3] <= 0 for r in rows):
        return "invalid candle (high/low do not contain open/close)"
    return None


async def main() -> None:
    ap = argparse.ArgumentParser(description="Supply and Demand v1 backtest")
    d0, d1 = default_window()
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat())
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    SETTINGS[:] = narrow(SETTINGS, a)
    use_tfs = [int(v[:-1]) for v in _vals("tf")]
    use_rrs = [float(v.split(":")[1]) for v in _vals("rr")]
    use_stops = _vals("stop")
    use_anchors = _vals("anchor")
    use_targets = _vals("target_mode")
    use_eods = _vals("eod")
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    check_window(frm, to)
    print(f"axes: {len(combos(SETTINGS))} simulated combinations")
    now = datetime.now(IST)
    if to >= now.date() and now.strftime("%H:%M") <= "15:45":
        to = now.date() - timedelta(days=1)          # rule 7: today's session is not over
        print(f"today's session is not over; --to cut to {to}")

    trades: list[dict] = []
    opt_sessions: dict[str, dict[str, list[list]]] = {}
    skipped: list[str] = []

    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        ukey = und["instrument_key"]
        info = await up.option_chain_info(ukey)
        step = info["strike_step"]
        expiries = await up.expiry_calendar(ukey, frm, to)
        print(f"{und['trading_symbol']}  strike step {step}  live lot size {info['lot_size']}  {frm} -> {to}")
        sessions = await fetch_index(up, ukey, frm, to)
        cov = coverage(sessions, frm, to, rows_per_session=375)
        contracts: dict[tuple, dict | None] = {}

        for day, rows1 in sessions.items():
            dd = date.fromisoformat(day)
            if not (frm <= dd <= to):
                continue
            prob = session_problem(day, rows1)
            if prob:
                skipped.append(f"{day}: {prob}"); print(f"SKIP {day}: {prob}"); continue
            exp = next_expiry(expiries, dd, 1)
            for tf in use_tfs:
                rows_tf = rows1 if tf == 1 else resample(rows1, tf)
                st = find_setup(rows_tf, tf)
                if st["status"] != "signal":
                    msg = f"{day} [{tf}m]: {st['status']}"
                    skipped.append(msg); print(f"SKIP {msg}"); continue
                if exp is None:
                    msg = f"{day} [{tf}m]: no expiry at least 1 day after the day"
                    skipped.append(msg); print(f"SKIP {msg}"); continue
                otype = "CE" if st["direction"] == "long" else "PE"
                strike = atm_strike(st["signal_close"], step)
                ck = (exp, strike, otype)
                if ck not in contracts:
                    contracts[ck] = await up.resolve_option(ukey, exp, strike, otype)
                con = contracts[ck]
                if con is None or not con["lot_size"]:
                    msg = f"{day} [{tf}m]: no contract {exp} {strike:g} {otype}"
                    skipped.append(msg); print(f"SKIP {msg}"); continue
                sym = con["trading_symbol"]
                if day not in opt_sessions.get(sym, {}):
                    opt_sessions.setdefault(sym, {})[day] = await up.option_candles(con, dd)
                orows = opt_sessions[sym][day]
                if not orows:
                    msg = f"{day} [{tf}m]: option {sym} has no bars"
                    skipped.append(msg); print(f"SKIP {msg}"); continue
                qty = con["lot_size"]               # 1 lot
                for rr in use_rrs:
                  for mode in use_stops:
                   for anchor in use_anchors:
                    for tmode in use_targets:
                     for eod in use_eods:
                        sim = simulate(st, rr, mode, rows1, orows, anchor, tmode, eod)
                        if "skip" in sim:
                            skipped.append(f"{day} [{tf}m 1:{rr:g} {mode} {anchor} {tmode} {eod}]: {sim['skip']}")
                            continue
                        ent, ext = sim["entry_bar"][0], sim["exit_bar"][0]
                        mfe, mae = excursion(orows, "LONG", sim["entry_px"], ent, ext)
                        end = ext
                        levels = [
                            {"name": f"{'demand' if st['direction'] == 'long' else 'supply'} zone",
                             "price": st["zone_low"], "price2": st["zone_high"], "from": st["zone_time"], "to": end},
                            {"name": f"stop ({anchor}, index)", "price": sim["stop"], "from": ent, "to": end},
                            {"name": "target (index)", "price": sim["target"], "from": ent, "to": end},
                            {"name": "signal close", "price": st["signal_close"], "from": st["signal_start"], "to": end},
                            {"name": "sweep level", "price": st["sweep_level"], "from": st["sweep_time"], "to": end},
                        ]
                        trades.append(make_trade(
                            day=day, side="LONG", symbol=sym, entry_time=ent, entry_px=sim["entry_px"],
                            exit_time=ext, exit_px=sim["exit_px"], qty=qty, exit_reason=sim["reason"],
                            capital=sim["entry_px"] * qty, expiry=con["expiry"], option_type=otype,
                            mfe=mfe, mae=mae, levels=levels,
                            variant={"tf": f"{tf}m", "rr": f"1:{rr:g}", "stop": mode,
                                     "anchor": anchor, "target_mode": tmode, "eod": eod},
                            tags={"direction": "long (buy CE)" if st["direction"] == "long" else "short (buy PE)"},
                            note=(f"{st['direction']} setup: break {st['break_time']}, zone candle {st['zone_time']}, "
                                  f"sweep {st['sweep_time']}, micro break candle {st['signal_start']} closed "
                                  f"{st['signal_close']:.2f}; {anchor} stop {sim['stop']:.2f}, risk "
                                  f"{sim['risk']:.2f} pts, target {tmode}, end of day {eod}")))

    print(f"\n{len(skipped)} skips / no-setup lines listed above; trades built: {len(trades)}")
    meta = {
        "title": "Supply and Demand v1: zone, sweep, micro break",
        "subtitle": f"NIFTY 50 signals; ATM option bought; {frm} to {to}",
        "instrument": "NIFTY 50 (signal) / ATM CE-PE option (traded)", "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": info["lot_size"],
        "fill_rule": "Every buy at the 1m option bar's HIGH, every sell at its LOW; a signal is acted on in the next 1m bar.",
        "cost_model": "Standard option schedule (brokerage, STT, exchange, SEBI, stamp, GST)",
        "params": {"swing": f"{SWING_N} candles each side", "minor swing (assumed)": f"{MINOR_N} candle each side",
                   "death": f"close > {DEATH_WIDTHS:g} zone widths past the far edge", "min risk": f"{MIN_RISK:g} pt",
                   "timeframes": "3m, 1m", "RR": "1:1, 1:2, 1:3, 1:5", "stop modes": "touch, close-confirmed",
                   "square-off": SQUARE_OFF, "lots": 1},
        "rule_steps": [
            "Each day, build candles (3m and 1m) from the 1-minute NIFTY index; swings need 3 candles each side and count once 3 candles have closed.",
            "The first candle to close beyond the latest confirmed swing sets the day's direction (above a swing high: bullish; below a swing low: bearish).",
            "Zone = full range of the last opposite-coloured candle among the 3 before the break; none means no trade that day.",
            "Death test on every candle first: a close more than 4 zone widths beyond the far edge ends the day.",
            "A candle after the break that touches the zone arms the setup.",
            "Then: a sweep (trade through the latest minor swing low/high and close back), replaced by any later fresh sweep, then a later candle closing beyond the latest minor swing high/low (micro break).",
            "Stop = lower of zone low and sweep low (mirror for shorts), measured from the micro-break candle's close; risk under 1 point uses up the day's slot with no trade.",
            "Target = signal close + RR x risk (1:1, 1:2, 1:3, 1:5).  Bullish buys an ATM CE, bearish an ATM PE, in the next 1m bar.",
            "Stop and target are watched on 1m index bars from the bar after entry; a hit exits in the next 1m bar; square-off 15:15; stop first, then target.",
            "Stop is shown two ways: touch (any trade through the level) and close-confirmed (a 1m close beyond the level).",
        ],
        "limits": [
            "ASSUMED: underlying NIFTY 50; the traded instrument is the ATM option (bullish buys CE, bearish buys PE) because only the option cost schedule is available; the stop/target are on the index level.",
            "ASSUMED: minor swing = 1 candle each side; swings come from the same day's candles only; a doji is neither colour; the break candle cannot arm the zone; the touch candle cannot also be the sweep.",
            "ASSUMED: no new setup once the entry bar would start at or after 15:15; window default 2026-01-01 through the current IST date; 1 lot; expiry nearest at least 1 day after the exit day; close-confirmed stop uses 1-minute closes.",
            "OVERRIDDEN by the fill rules: the prompt's entry at the micro-break candle's close is replaced by the next 1m option bar's HIGH; a stop 'resting order filled at its level/open' is replaced by a stop signal exiting in the next 1m option bar at its LOW; close-confirmed exits fill in the next 1m bar, not at the close.  Risk and target are still measured from the signal candle's index close, so realised R differs from planned R.",
            "Capital = option premium x quantity (bought option).",
            "Variants (tf, rr, stop mode) are all shown; nothing is selected, but the whole window is in-sample and the 3m/1m and RR variants share the same days, so they are not independent evidence.",
            "Option data comes from Upstox; a missing option bar skips that trade and is listed on the console.",
        ],
        "coverage": cov,
    }
    payload = build_payload(meta, trades, sessions, opt_sessions,
                            [{"name": "Direction", "keys": ["direction"]}],
                            settings=SETTINGS, chart="default")
    path = write_report(payload, SLUG)
    print(console_summary(trades))
    print(path)


if __name__ == "__main__":
    asyncio.run(main())
