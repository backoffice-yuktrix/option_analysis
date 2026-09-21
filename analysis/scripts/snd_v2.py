"""Supply and Demand - v2  (slug: snd_v2)

USER PROMPT (verbatim)
----------------------
v2 SnD - the same entry, two filters on top
* Filter one, an entry cut-off at 13:00.  Filter two, a minimum sweep depth of 0.1 zone widths.
* A rejected confirmation uses up the day - the machine does not go looking for a later one.
Step 1  A swing high is a candle whose high is higher than the 3 highs before it and the 3 highs after
        it, and a swing low is the opposite; a swing only counts once 3 candles have closed after it.
Step 2  The first candle of the day that CLOSES beyond the most recent confirmed swing sets the
        direction for the day: closing above a swing high = bullish, below a swing low = bearish.
Step 3  A wick is not a break, it has to be the close; only the first break of the day counts.
Step 4  The zone is the last opposite-coloured candle in the 3 candles before the break (last red before
        a bullish break, last green before a bearish one), full range low to high; bullish = demand
        zone, bearish = supply zone.
Step 5  No such candle -> no zone, the day is over.
Step 6  Wait for price to come back and touch the zone (candle low <= zone high and candle high >= zone
        low); a touch only arms the setup.
Step 7  Then in order: one candle trades below the most recent confirmed minor swing low (sweep), that
        same candle closes back above that low (recovery), then a later candle closes above the most
        recent confirmed minor swing high (micro break).
Step 8  Entry is the CLOSE of the micro break candle, buy there.  A short is the exact mirror.
Step 9  One candle cannot be both the sweep and the micro break (then it is a fresh sweep); a new sweep
        before the micro break replaces the old one.
Step 10 The sweep must pierce the swing level by at least 0.1 zone widths (zone width = zone high - zone
        low); a shallower poke is not a sweep and the setup stays armed.
Step 11 No new entry at or after 13:00 (micro break candle closing at 13:00 or later = not taken).
Step 12 If a confirmation completes and then fails either filter, the day is finished.
Step 13 Stop behind whichever is further away, the zone or the sweep; risk = entry to stop; below 1
        point there is no trade and the day's slot is used up anyway.
Step 14 Target = entry + 2 x risk (mirrored for a short); also score 1:1, 1:3 and 1:5.
Step 15 The setup dies if any candle CLOSES more than 4 zone widths past the far edge of the zone,
        checked before the touch test and the entry test on every candle.
Step 16 One trade a day at most; once in, the zone dying no longer matters.
Step 17 Watch stop and target on 1-minute prices from the candle after the entry; inside one minute the
        order is square-off, then stop, then target.  Square off at 15:15 and stop looking for setups at
        15:15.
Step 18 3-minute candles by default, 1-minute alongside.

RUN.md STEP 1 - CHECKLIST (non-interactive run: every gap closed by a default / simplest reading)
----------------------------------------------------------------------------------------------
 1 Underlying          clear    NIFTY 50 index, 1-minute candles from Upstox
 2 Window              assumed  default: last 6 months ending yesterday (--from / --to override)
 3 Signal timeframe    clear    3m (default) and 1m, both built from 1-minute candles, as variants
 4 Signal rule         clear*   Steps 1-16; see ASSUMED items for the numbers the prompt leaves out
 5 Decision time       clear    close of the micro break candle; the fill is the NEXT 1m bar (rule 2)
 6 Direction mapping   ASSUMED  bullish -> buy ATM CE, bearish -> buy ATM PE (index stop/target)
 7 Traded instrument   ASSUMED  ATM NIFTY option, bought (the prompt says "buy there" only)
 8 Option specifics    ASSUMED  ATM strike from the signal candle close, nearest expiry >= 1 day after
                                the trade day (rule 10), 1 lot, lot size from the contract
 9 Entry               clear    micro break confirmed, both v2 filters passed, risk >= 1 point
10 Exit                clear    index-level stop / target (evaluated on index 1m bars), time exit 15:15
11 Holding period      clear    intraday
12 Costs               assumed  standard option schedule (option_costs)
13 Position rules      assumed  one trade a day, one position at a time, no re-entry
14 Missing data        assumed  skip and list
15 Filters             clear    tf {3m, 1m} x target {1:1, 1:2, 1:3, 1:5}  (+ side)  = 30 views
16 Custom group-bys    assumed  none asked; added direction, sweep depth bucket, risk bucket
17 Script name         clear    snd_v2

ASSUMED (each is repeated in meta["limits"])
 A1 Traded instrument is a bought ATM option (CE on bullish, PE on bearish); the prompt names none.
    Stop/target are INDEX levels and are watched on index 1-minute bars; the fills are option bars.
 A2 Swings (Step 1) use same-day candles only; nothing from the previous day.  Same-day swings
    need 3 candles before, so the earliest break is candle 7 (09:15 + 6 candles).
 A3 "Minor swing" (Step 7) is not defined: taken as a swing with 2 candles before and 2 after,
    confirmed once 2 candles have closed after it; same-day only.
 A4 The touch candle may also be the sweep candle (Step 15 tests touch and entry on one candle).
 A5 Steps 10 and 12 contradict (shallow poke "stays armed" vs "confirmation fails filter -> day
    finished").  Followed Step 12 and the intro ("a rejected confirmation uses up the day"): the
    sweep is any wick beyond the level that closes back; the depth is checked on the sweep in force
    when the micro break completes, together with the 13:00 cut-off; failure ends the day.
 A6 "Behind the zone or the sweep" = exactly at the zone edge / sweep extreme, no buffer.
 A7 Stop/target levels are built from the index close of the micro break candle (the prompt's
    entry), although the real fill is the next 1m option bar's high (rule 1/2).  The stop is not
    checked inside the entry bar itself (scan starts with the next bar).
 A8 A candle that closes beyond both the swing high and swing low at once is ambiguous: day skipped.
 A9 "Stop looking for setups at 15:15": candles completing at 15:15 or later are not read.
 A10 Doji candles (close == open) are neither red nor green.
 A11 Lot count 1; ATM = nearest strike to the signal candle close.
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: F401,F403,E402

# ---------------------------------------------------------------------------
# parameters (numbers from the prompt unless marked ASSUMED)
# ---------------------------------------------------------------------------
SWING_N = 3               # Step 1
MINOR_N = 2               # ASSUMED (Step 7 "minor swing")
DEATH_WIDTHS = 4.0        # Step 15
MIN_SWEEP_WIDTHS = 0.1    # Step 10
ENTRY_CUTOFF = "13:00"    # Step 11
SQUARE_OFF = "15:15"      # Step 17
MIN_RISK = 1.0            # Step 13
RRS = [1.0, 2.0, 3.0, 5.0]   # Step 14
TFS = [3, 1]              # Step 18
LOTS = 1
SESSION_ROWS = 375
SLUG = "snd_v2"


def rr_label(rr: float) -> str:
    return f"1:{rr:g}"


# ---------------------------------------------------------------------------
# signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def swing_flags(c: list[list], n: int) -> tuple[list[bool], list[bool]]:
    """(high flags, low flags): candle j is a swing when strictly beyond the n candles either side.
    A flag at j is only READ once j + n candles have closed (see last_swing)."""
    hi, lo = [False] * len(c), [False] * len(c)
    for j in range(n, len(c) - n):
        around = list(range(j - n, j)) + list(range(j + 1, j + n + 1))
        hi[j] = all(c[j][2] > c[k][2] for k in around)
        lo[j] = all(c[j][3] < c[k][3] for k in around)
    return hi, lo


def last_swing(flags: list[bool], c: list[list], col: int, i: int, n: int):
    """Most recent swing confirmed at the close of candle i: (index, price) or None."""
    for j in range(i - n, -1, -1):
        if flags[j]:
            return j, c[j][col]
    return None


def done(c: list, tf: int) -> str:
    return candle_done_at(c[0], tf)


def find_setup(c: list[list], tf: int) -> dict:
    """Walk one day's tf-minute candles.  Returns {"skip": reason} or {"setup": {...}}."""
    hiS, loS = swing_flags(c, SWING_N)
    mhi, mlo = swing_flags(c, MINOR_N)
    # Steps 2-3: the first close beyond the most recent confirmed swing
    brk = None
    for i in range(len(c)):
        if done(c[i], tf) >= SQUARE_OFF:
            break
        sh, sl = last_swing(hiS, c, 2, i, SWING_N), last_swing(loS, c, 3, i, SWING_N)
        up = sh is not None and c[i][4] > sh[1]
        dn = sl is not None and c[i][4] < sl[1]
        if up and dn:
            return {"skip": f"ambiguous break at {c[i][0]} (closed beyond both swings)"}
        if up or dn:
            brk = (i, "bull" if up else "bear", sh if up else sl)
            break
    if brk is None:
        return {"skip": "no candle closed beyond a confirmed swing before 15:15"}
    bi, direction, swing = brk
    bull = direction == "bull"
    # Steps 4-5: last opposite-coloured candle in the 3 before the break
    zi = None
    for k in range(bi - 1, max(bi - 4, -1), -1):
        red, green = c[k][4] < c[k][1], c[k][4] > c[k][1]
        if (red and bull) or (green and not bull):
            zi = k
            break
    if zi is None:
        return {"skip": f"break at {c[bi][0]} ({direction}) but none of the 3 candles before it is "
                        f"{'red' if bull else 'green'} - no zone"}
    zlo, zhi = c[zi][3], c[zi][2]
    w = zhi - zlo
    if w <= 0:
        return {"skip": f"zone candle {c[zi][0]} has zero width"}
    armed, sweep = False, None
    for k in range(bi + 1, len(c)):
        if done(c[k], tf) >= SQUARE_OFF:
            return {"skip": f"{direction} zone {zlo:.2f}-{zhi:.2f}: no confirmation before 15:15"
                            + (" (armed)" if armed else " (never touched)")}
        o, h, l, cl = c[k][1:5]
        # Step 15 first: the zone dies
        if (bull and cl < zlo - DEATH_WIDTHS * w) or (not bull and cl > zhi + DEATH_WIDTHS * w):
            return {"skip": f"{direction} zone {zlo:.2f}-{zhi:.2f} died at {c[k][0]} "
                            f"(close {cl:.2f} beyond 4 widths)"}
        # Step 6: touch arms
        if not armed and l <= zhi and h >= zlo:
            armed = True
        if not armed:
            continue
        # Steps 7-9: sweep, recovery, micro break (minor swings confirmed at this candle's close)
        mh, ml = last_swing(mhi, c, 2, k, MINOR_N), last_swing(mlo, c, 3, k, MINOR_N)
        if bull:
            is_sweep = ml is not None and l < ml[1] and cl > ml[1]
            if is_sweep:
                sweep = {"i": k, "level": ml[1], "extreme": l, "depth": ml[1] - l}
                continue
            micro = sweep is not None and mh is not None and cl > mh[1]
        else:
            is_sweep = mh is not None and h > mh[1] and cl < mh[1]
            if is_sweep:
                sweep = {"i": k, "level": mh[1], "extreme": h, "depth": h - mh[1]}
                continue
            micro = sweep is not None and ml is not None and cl < ml[1]
        if not micro:
            continue
        # Step 8 entry candle found; Steps 10-12: filters apply to the whole confirmation
        why = []
        if sweep["depth"] < MIN_SWEEP_WIDTHS * w - 1e-9:
            why.append(f"sweep depth {sweep['depth']:.2f} < {MIN_SWEEP_WIDTHS * w:.2f} (0.1 zone widths)")
        if done(c[k], tf) >= ENTRY_CUTOFF:
            why.append(f"micro break candle closes {done(c[k], tf)} (cut-off {ENTRY_CUTOFF})")
        if why:
            return {"skip": f"{direction} confirmation at {c[k][0]} rejected, day used up: " + "; ".join(why)}
        stop = min(zlo, sweep["extreme"]) if bull else max(zhi, sweep["extreme"])   # Step 13
        risk = abs(cl - stop)
        if risk < MIN_RISK:
            return {"skip": f"{direction} confirmation at {c[k][0]}: risk {risk:.2f} < {MIN_RISK:g} point, "
                            f"day used up"}
        return {"setup": {"direction": direction, "bull": bull, "zone": (zlo, zhi), "zone_start": c[zi][0],
                          "break_start": c[bi][0], "swing": swing[1], "width": w,
                          "sweep": sweep, "sweep_start": c[sweep["i"]][0], "signal_start": c[k][0],
                          "signal_done": done(c[k], tf), "entry_index": cl, "stop": stop, "risk": risk}}
    return {"skip": f"{direction} zone {zlo:.2f}-{zhi:.2f}: session ended without a confirmation"}


# ---------------------------------------------------------------------------
# simulate (pure: bars -> exit)
# ---------------------------------------------------------------------------
def simulate(setup: dict, tf: int, rr: float, index_rows: list[list], opt_rows: list[list]):
    """Returns ({trade fields}) or a string (the reason the trade could not be taken)."""
    bull = setup["bull"]
    entry_bar_1m = bar_after_candle(index_rows, setup["signal_start"], tf)            # rule 2
    if entry_bar_1m is None:
        return "no 1-minute index bar right after the signal candle"
    ek = entry_bar_1m[0]
    if ek >= SQUARE_OFF:
        return f"entry bar {ek} is at/after {SQUARE_OFF}"
    e, risk = setup["entry_index"], setup["risk"]
    target = e + rr * risk if bull else e - rr * risk
    ex = scan_exit(index_rows, "LONG" if bull else "SHORT", ek, stop=setup["stop"], target=target,
                   force_key=SQUARE_OFF)                                              # rule 3
    if ex["bar"] is None:
        return f"exit not resolvable ({ex['reason']})"
    xk = ex["bar"][0]
    by = {r[0]: r for r in opt_rows}
    eb, xb = by.get(ek), by.get(xk)
    if eb is None:
        return f"option has no bar at the entry minute {ek}"
    if xb is None:
        return f"option has no bar at the exit minute {xk}"
    entry_px, exit_px = worst_fills("LONG", eb, xb)                                   # rule 1
    mfe, mae = excursion(opt_rows, "LONG", entry_px, ek, xk)
    return {"ek": ek, "xk": xk, "entry_px": entry_px, "exit_px": exit_px, "reason": ex["reason"],
            "target": target, "mfe": mfe, "mae": mae}


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
def clean_session(rows: list[list]) -> str | None:
    """None when the day is usable, else why not (rule 6/7)."""
    if len(rows) != SESSION_ROWS:
        return f"session has {len(rows)} bars, need {SESSION_ROWS}"
    times = [r[0] for r in rows]
    if len(set(times)) != len(times) or times[0] != "09:15" or times[-1] != "15:29":
        return "duplicate bars or wrong session bounds"
    for r in rows:
        if not (r[2] >= max(r[1], r[4], r[3]) and r[3] <= min(r[1], r[4], r[2]) and r[3] > 0):
            return f"invalid bar at {r[0]}"
    return None


async def main(frm: date, to: date) -> None:
    now = datetime.now(IST)
    if to >= now.date() and now.strftime("%H:%M") <= "15:45":
        to = now.date() - timedelta(days=1)                                           # rule 7
    print(f"window {frm} .. {to}")
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list]] = {}
    skips = 0
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        step = info["strike_step"]
        if not step:
            raise SystemExit("could not read the strike step from Upstox")
        cal = await up.expiry_calendar(key, frm, to)
        sessions = sessions_from(await up.candles(key, "1m", frm, to))
        cov = coverage(sessions, frm, to, SESSION_ROWS)
        print(f"strike step {step:g}; {cov['sessions']} sessions; weekday gaps {cov['weekday_gaps']}; "
              f"short {cov['short_sessions']}")
        contracts: dict[tuple, dict | None] = {}
        opt_cache: dict[tuple, list] = {}
        for day in sorted(sessions):
            d = date.fromisoformat(day)
            if not (frm <= d <= to):
                continue
            rows = sessions[day]
            bad = clean_session(rows)
            if bad:
                print(f"SKIP {day} (all): {bad}"); skips += 1
                continue
            for tf in TFS:
                res = find_setup(resample(rows, tf), tf)
                if "skip" in res:
                    print(f"SKIP {day} [{tf}m]: {res['skip']}"); skips += 1
                    continue
                s = res["setup"]
                ot = "CE" if s["bull"] else "PE"
                expiry = next_expiry(cal, d, 1)                                       # rule 10
                if expiry is None:
                    print(f"SKIP {day} [{tf}m]: no expiry at least 1 day after the trade day"); skips += 1
                    continue
                strike = atm_strike(s["entry_index"], step)
                ck = (expiry, strike, ot)
                if ck not in contracts:
                    contracts[ck] = await up.resolve_option(key, expiry, strike, ot)
                con = contracts[ck]
                if con is None:
                    print(f"SKIP {day} [{tf}m]: no contract {ot} {strike:g} exp {expiry}"); skips += 1
                    continue
                if (con["instrument_key"], day) not in opt_cache:
                    opt_cache[(con["instrument_key"], day)] = await up.option_candles(con, d)
                orows = opt_cache[(con["instrument_key"], day)]
                if not orows:
                    print(f"SKIP {day} [{tf}m]: no option bars for {con['trading_symbol']}"); skips += 1
                    continue
                option_sessions.setdefault(con["trading_symbol"], {})[day] = orows
                qty = LOTS * con["lot_size"]
                zlo, zhi = s["zone"]
                for rr in RRS:
                    r = simulate(s, tf, rr, rows, orows)
                    if isinstance(r, str):
                        print(f"SKIP {day} [{tf}m {rr_label(rr)}]: {r}"); skips += 1
                        continue
                    depth_w = s["sweep"]["depth"] / s["width"]
                    trades.append(make_trade(
                        day=day, side="LONG", symbol=con["trading_symbol"], entry_time=r["ek"],
                        entry_px=r["entry_px"], exit_time=r["xk"], exit_px=r["exit_px"], qty=qty,
                        exit_reason=r["reason"], kind="option", capital=r["entry_px"] * qty,
                        mfe=r["mfe"], mae=r["mae"], expiry=con["expiry"], option_type=ot,
                        variant={"tf": f"{tf}m", "rr": rr_label(rr)},
                        tags={"direction": "bullish (buy CE)" if s["bull"] else "bearish (buy PE)",
                              "sweep depth": bucket(depth_w, [0.25, 0.5, 1.0],
                                                    ["0.1-0.25 w", "0.25-0.5 w", "0.5-1 w", "over 1 w"]),
                              "risk pts": bucket(s["risk"], [30, 50, 80],
                                                 ["under 30", "30-50", "50-80", "over 80"])},
                        levels=[{"name": "zone", "price": zlo, "price2": zhi, "from": s["zone_start"], "to": r["xk"]},
                                {"name": "swing broken", "price": s["swing"], "from": s["break_start"], "to": s["signal_start"]},
                                {"name": "sweep level", "price": s["sweep"]["level"], "from": s["sweep_start"], "to": s["signal_start"]},
                                {"name": "index entry (signal close)", "price": s["entry_index"], "from": s["signal_start"], "to": r["xk"]},
                                {"name": "index stop", "price": s["stop"], "from": s["signal_start"], "to": r["xk"]},
                                {"name": "index target", "price": r["target"], "from": s["signal_start"], "to": r["xk"]}],
                        note=f"signal candle {s['signal_start']} ({tf}m), index risk {s['risk']:.2f} pts, "
                             f"zone width {s['width']:.2f}"))
    print(f"\n{len(trades)} trades, {skips} skips/rejections listed above")
    meta = {
        "title": "Supply and Demand v2 - NIFTY",
        "subtitle": "Zone touch, sweep, recovery, micro break; 13:00 cut-off and 0.1-width sweep filters",
        "instrument": "NIFTY 50 index signal; bought ATM option (assumed)",
        "from": frm.isoformat(), "to": to.isoformat(), "lot_size": info["lot_size"],
        "fill_rule": "Every BUY at the bar's high, every SELL at the bar's low; signal acted on in the next "
                     "1-minute bar; stop/target exits fill in the bar after the touch; 15:15 square-off fills in that bar",
        "cost_model": "Standard option schedule (option_costs), 1 lot",
        "params": {"swing": f"{SWING_N} each side", "minor swing (assumed)": f"{MINOR_N} each side",
                   "min sweep depth": f"{MIN_SWEEP_WIDTHS} zone widths", "entry cut-off": ENTRY_CUTOFF,
                   "zone death": f"{DEATH_WIDTHS:g} widths", "min risk": f"{MIN_RISK:g} pt",
                   "targets": ", ".join(rr_label(x) for x in RRS), "timeframes": "3m (default), 1m",
                   "square-off": SQUARE_OFF, "lots": LOTS},
        "rule_steps": [
            "Build 3-minute (and 1-minute) candles from 1-minute index data; use complete 375-bar sessions only.",
            f"A swing is a candle beyond the {SWING_N} candles before and after; it counts once {SWING_N} candles have closed after it (same day).",
            "The first candle whose CLOSE is beyond the latest confirmed swing sets the day's direction; later breaks are ignored.",
            "Zone = full range of the last opposite-coloured candle among the 3 before the break; none = day over.",
            f"The zone dies if a candle closes more than {DEATH_WIDTHS:g} zone widths past its far edge (tested first on every candle).",
            "A touch of the zone arms the setup.",
            f"Sweep: a candle trades through the latest confirmed minor swing ({MINOR_N} each side) and closes back inside; a new sweep replaces the old; a candle that is both sweep and break counts as a sweep.",
            "Micro break: a later candle closes beyond the opposite minor swing.  The confirmation completes here.",
            f"Filters on the confirmation: sweep depth at least {MIN_SWEEP_WIDTHS} zone widths and micro break candle closing before {ENTRY_CUTOFF}; failure ends the day.",
            f"Stop = further of zone edge / sweep extreme; risk below {MIN_RISK:g} point = no trade, day used up.",
            "Trade: buy the ATM CE (bullish) or PE (bearish) in the 1-minute bar after the signal candle, at that bar's high.",
            "Index stop / target (1:1, 1:2, 1:3, 1:5 of the index risk) watched on index 1-minute bars from the bar after entry; stop first if both; exit fills in the next bar at its low; square-off at 15:15.",
            "One trade per day per variant."],
        "limits": [
            "ASSUMED: the traded instrument is a bought ATM NIFTY option (CE bullish, PE bearish); the prompt only says 'buy'. Stop and target are INDEX levels, watched on index bars; fills are option bars.",
            "ASSUMED: swings use same-day candles only; the minor swing is 2 candles each side (the prompt does not define it).",
            "ASSUMED: the touch candle may also be the sweep candle.",
            "ASSUMED: Steps 10 and 12 conflict; followed Step 12 - a shallow sweep or a 13:00+ micro break ends the day.",
            "ASSUMED: stop sits exactly at the zone edge / sweep extreme; stop/target levels come from the index close of the signal candle while the real fill is the next bar's option high.",
            "ASSUMED: one lot; ATM strike from the signal candle close; expiry the nearest at least 1 day after the trade day.",
            "The four target multiples share one entry, so 1:1..1:5 views are the same signals, not independent samples; 3m and 1m views overlap in time.",
            "IN-SAMPLE: the two v2 filters were chosen on v1's trades in a study window; this window may overlap it, so v2 looks better than it will out of sample.",
            "Sold-option margin does not apply: capital is premium x quantity (bought option).",
            "Rule 1 fills at high/low are deliberately pessimistic, and stop checks use index prices not option prices."],
        "coverage": cov}
    payload = build_payload(meta, trades, sessions, option_sessions, [
        {"name": "Direction", "keys": ["direction"]},
        {"name": "Sweep depth (zone widths)", "keys": ["sweep depth"]},
        {"name": "Index risk (points)", "keys": ["risk pts"]}])
    path = write_report(payload, SLUG)
    print(console_summary(trades))
    print(path)


if __name__ == "__main__":
    yday = datetime.now(IST).date() - timedelta(days=1)
    ap = argparse.ArgumentParser(description="Supply and Demand v2 backtest")
    ap.add_argument("--from", dest="frm", type=date.fromisoformat, default=yday - timedelta(days=182))
    ap.add_argument("--to", dest="to", type=date.fromisoformat, default=yday)
    a = ap.parse_args()
    asyncio.run(main(a.frm, a.to))
