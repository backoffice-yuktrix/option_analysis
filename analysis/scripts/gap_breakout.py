"""Gap breakout, both sides.

STRATEGY PROMPT (verbatim)
--------------------------
Step 1 - Work out the gap: today's open minus the previous session's close, divided by that close, as a
percentage. The previous close is the previous session's last traded print, its 15:29 candle, with the
official daily close carried beside it on every row.
Step 2 - A gap of +0.30% or more arms the LONG side. A gap of -0.30% or more arms the SHORT side.
Anything in between is not traded.
Step 3 - The opening range is the first 15-minute candle, 09:15 to 09:29. The long side works off its HIGH,
the short side off its LOW.
Step 4 - Scan the 15-minute candles from 09:30 to 11:00. On the long side, the first candle to CLOSE ABOVE
the level is the trigger; on the short side, the first to CLOSE BELOW it.
Step 5 - The entry is the OPEN of the next 15-minute candle: buy on the long side, sell on the short side.
Step 6 - The stop is the trigger candle's LOW on the long side and its HIGH on the short side.
Step 7 - The stop as written is close-confirmed - the position is closed only when a later candle CLOSES
beyond that level and the fill is that close, so the loss is not capped at 1R. A resting order at the level
is computed beside it, where every loss is exactly 1R but a trade that only wicks through is stopped
instead of surviving.
Step 8 - Risk is the distance from the entry to the stop, and the target is the entry plus (long) or minus
(short) the risk times 2; also score 3, 4 and 5.
Step 9 - Targets are a touch, checked on 1-minute candles, so a target reached inside a candle is taken
before that candle's close can trigger the stop. When one minute both touches the target and breaks the
stop, the stop is taken first.
Step 10 - Square off anything still open at 15:15.

RUN.md STEP 1 CHECKLIST (no user available; ASSUMED = default or simplest reading)
-----------------------------------------------------------------------------------
 1 Underlying        ASSUMED  NIFTY 50 index (prompt names none).
 2 Window            ASSUMED  2026-01-01 through the current IST date (default).
 3 Signal timeframe  clear    15m candles built from 1m; opening range = 09:15 candle.
 4 Signal rule       clear    gap >= +/-0.30%; first 15m close beyond OR high/low. ASSUMED: the scan covers
                              15m candles that START 09:30 .. 10:45 (i.e. complete by 11:00). ASSUMED: the
                              "previous session" is the previous session present in the feed (a missing
                              trading day cannot be told from a holiday); the official daily close is not
                              used, only the 15:29 1m close. Gap uses the 09:15 1m open.
 5 Decision time     clear    close of the trigger 15m candle (entry: the 1m bar after it, rule 2).
 6 Direction         ASSUMED  prompt says buy / sell. Traded instrument is not stated, so: long signal ->
                              BUY an ATM CE, short signal -> BUY an ATM PE (a sell of the index is a
                              bought put). Stops/targets are measured on the INDEX; fills are option bars.
 7 Traded instrument ASSUMED  NIFTY option (no futures/index cost schedule may be guessed, rule 5).
 8 Option specifics  ASSUMED  buy, ATM strike from the trigger candle's close (strike step read from
                              Upstox), nearest expiry at least 1 day after the trade day, 1 lot.
 9 Entry             clear    trigger only; one entry per session.
10 Exit              clear    target (R x risk, R in 2,3,4,5), stop (trigger candle low/high, two modes),
                              time exit 15:15 (fills in the 15:15 bar). Exits may fire from the bar after
                              entry. ASSUMED: risk is measured from the index entry price = worst fill of
                              the entry 1m bar (rule 1) to the trigger candle's stop.
11 Holding           clear    intraday.
12 Costs             ASSUMED  standard option schedule (option_costs).
13 Position rules    clear    one at a time; at most one signal per session; no re-entry.
14 Missing data      ASSUMED  skip and list (default). A session needs all 375 valid 1m bars, as does the
                              previous one.
15 Filters           clear    variant `stop` (close-confirmed / resting), `rr` (1:2..1:5), `gap` (up/down),
                              plus side. 2 x 4 x 2 x 1 side -> 90 views.
16 Group-bys         ASSUMED  gap size, trigger candle, risk size (all measured by the entry signal).
17 Script name       gap_breakout.

STOP MODES (variant `stop`)
    close-confirmed: a 15m candle completes with its close beyond the stop level -> exit in the next 1m bar.
    resting: any 1m bar touching the stop level -> exit in the next 1m bar (rule 3).
    Both: target touch on 1m bars -> exit next 1m bar; same-minute stop and target -> stop first.
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: E402,F401,F403

SLUG = "gap_breakout"
GAP_PCT = 0.30
RRS = [2, 3, 4, 5]
STOP_MODES = ["close-confirmed", "resting"]
FIRST_SCAN, LAST_SCAN_START = "09:30", "10:45"     # 15m candles starting 09:30..10:45 complete by 11:00
FORCE = "15:15"
TF = 15
ROWS_PER_SESSION = 375
EXPECTED = [f"{m // 60:02d}:{m % 60:02d}" for m in range(9 * 60 + 15, 15 * 60 + 30)]

# The axis the source (gap_breakout_v1) compares and this script fixed at one point.
# It matters more than it looks: the gap decides WHICH days qualify, so the two bases do not
# merely reprice the same trades, they choose different ones.
PDC_MODES = [("last", "the 15:29 print - the close the chart actually shows"),
             ("daily", "the official settlement close from the daily feed")]
RULE = {"pdc": "last"}

SETTINGS = [
    setting("pdc", "Previous close", kind="entry", default=RULE["pdc"],
            options=[{"value": k, "label": v, "raw": k} for k, v in PDC_MODES],
            help="what the gap is measured from"),
    setting("stop", "Stop trigger", kind="exit", values=STOP_MODES, default="close-confirmed"),
    setting("rr", "Reward:risk", kind="exit", values=[f"1:{r}" for r in RRS], default="1:2"),
]


def _vals(key):
    return [o["raw"] for o in next(x for x in SETTINGS if x["key"] == key)["options"]]


def valid_session(rows: list[list]) -> str | None:
    """None if the 1m session is complete and sane, else the reason."""
    if len(rows) != ROWS_PER_SESSION:
        return f"{len(rows)} bars, need {ROWS_PER_SESSION}"
    if [r[0] for r in rows] != EXPECTED:
        return "1m bar times are not 09:15..15:29"
    for r in rows:
        if min(r[1:5]) <= 0 or r[2] < max(r[1], r[4], r[3]) or r[3] > min(r[1], r[4]):
            return f"invalid bar at {r[0]}"
    return None


# ---------------------------------------------------------------- signal (pure) ------------------
def signal(prev_rows: list[list], rows: list[list], prev_daily_close: float | None = None,
           pdc: str = "last") -> dict:
    """Completed candles only.  Returns {"skip": reason} or the signal dict.

    pdc "last"  the previous session's 15:29 one-minute close - what the chart shows
        "daily" the official settlement close from the daily feed; they differ, and the gap
                threshold decides which days qualify, so this picks different trades."""
    prev_close = prev_rows[-1][4]                                   # 15:29 close
    if pdc == "daily":
        if prev_daily_close is None:
            return {"skip": "no official daily close for the previous session"}
        prev_close = prev_daily_close
    gap = (rows[0][1] - prev_close) / prev_close * 100
    gap = round(gap, 9)
    if gap >= GAP_PCT:
        direction = "LONG"
    elif gap <= -GAP_PCT:
        direction = "SHORT"
    else:
        return {"skip": f"gap {gap:+.2f}% inside +/-{GAP_PCT:.2f}%"}
    c15 = resample(rows, TF)
    orc = c15[0]                                                    # 09:15 candle
    level = orc[2] if direction == "LONG" else orc[3]
    for c in c15[1:]:
        if c[0] < FIRST_SCAN or c[0] > LAST_SCAN_START:
            continue
        if (direction == "LONG" and c[4] > level) or (direction == "SHORT" and c[4] < level):
            return {"direction": direction, "gap": gap, "prev_close": prev_close, "level": level,
                    "or_high": orc[2], "or_low": orc[3], "trigger": c,
                    "stop": c[3] if direction == "LONG" else c[2]}
    return {"skip": f"gap {gap:+.2f}% ({direction}) but no 15m close beyond the opening range "
                    f"{'high' if direction == 'LONG' else 'low'} {level:.2f} by 11:00"}


# ---------------------------------------------------------------- simulate (pure) ----------------
def _is_candle_end(hhmm: str) -> bool:
    return (hhmm_minutes(hhmm) - 555 + 1) % TF == 0


def scan_close_confirmed(bars: list[list], direction: str, entry_key: str, stop: float,
                         target: float, force_key: str) -> dict:
    """Index 1m bars.  Target touch -> exit in the next bar; a 15m candle that completes with its close
    beyond the stop -> exit in the next bar; same step: stop first; FORCE bar fills itself."""
    pending = None
    for r in bars:
        if r[0] <= entry_key:
            continue
        if pending:
            return {"bar": r, "reason": pending[0], "trigger": pending[1]}
        if r[0] == force_key:
            return {"bar": r, "reason": "time exit", "trigger": None}
        hit_tgt = r[2] >= target if direction == "LONG" else r[3] <= target
        stop_sig = _is_candle_end(r[0]) and (r[4] < stop if direction == "LONG" else r[4] > stop)
        if stop_sig:
            pending = ("stop (close-confirmed)", r)
        elif hit_tgt:
            pending = ("target", r)
    return {"bar": None, "reason": "no exit found", "trigger": None}


def simulate(mode: str, bars: list[list], direction: str, entry_key: str, stop: float, target: float) -> dict:
    if mode == "close-confirmed":
        return scan_close_confirmed(bars, direction, entry_key, stop, target, FORCE)
    out = scan_exit(bars, direction, entry_key, stop=stop, target=target, force_key=FORCE)
    if out["reason"] == "stop":
        out["reason"] = "stop (resting)"
    return out


# ---------------------------------------------------------------- main ---------------------------
async def run(frm: date, to: date) -> None:
    use_pdc = _vals("pdc")
    use_stops = _vals("stop")
    use_rrs = [int(v.split(":")[1]) for v in _vals("rr")]
    now = datetime.now(IST)
    last_ok = now.date() if (now.hour, now.minute) >= (15, 45) else now.date() - timedelta(days=1)
    to = min(to, last_ok)
    skips: dict[str, str] = {}
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list]] = {}
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        ukey = und["instrument_key"]
        info = await up.option_chain_info(ukey)
        step = info["strike_step"]
        cal = await up.expiry_calendar(ukey, frm, to)
        cs = await up.candles(ukey, "1m", frm - timedelta(days=10), to)
        # the official daily closes, for the alternative gap base (read only, no trades outside)
        dl = await up.candles(ukey, "1d", frm - timedelta(days=20), to)
        daily_close = {c["timestamp"][:10]: c["close"] for c in dl}
        print(f"daily closes for the alternative gap base: {len(daily_close)}")
        sessions = sessions_from(cs)
        alldays = sorted(sessions)
        days = [d for d in alldays if frm.isoformat() <= d <= to.isoformat()]
        # the previous-close base changes WHICH days qualify, so it belongs in the day loop.
        # Pairing it into the header keeps the body at one indent level.
        for day, pdc in [(d, p) for d in days for p in use_pdc]:
            i = alldays.index(day)
            if i == 0:
                skips[day] = "no previous session in the fetched data"
                continue
            prev = alldays[i - 1]
            bad = valid_session(sessions[day])
            if bad:
                skips[day] = f"today's session unusable: {bad}"
                continue
            bad = valid_session(sessions[prev])
            if bad:
                skips[day] = f"previous session {prev} unusable: {bad}"
                continue
            sig = signal(sessions[prev], sessions[day], daily_close.get(prev), pdc)
            if "skip" in sig:
                skips[day] = sig["skip"]
                continue
            rows = sessions[day]
            d_ = date.fromisoformat(day)
            direction, trig = sig["direction"], sig["trigger"]
            entry_bar = bar_after_candle(rows, trig[0], TF)
            if entry_bar is None:
                skips[day] = f"entry bar after {trig[0]} candle missing"
                continue
            idx_entry = entry_bar[2] if direction == "LONG" else entry_bar[3]     # rule 1 on the index
            stop = sig["stop"]
            risk = idx_entry - stop if direction == "LONG" else stop - idx_entry
            if risk <= 0:
                skips[day] = (f"{direction} trigger {trig[0]}: entry {idx_entry:.2f} is not beyond the stop "
                              f"{stop:.2f} (risk <= 0)")
                continue
            opt_type = "CE" if direction == "LONG" else "PE"
            expiry = next_expiry(cal, d_, 1)
            if expiry is None:
                skips[day] = "no expiry at least 1 day after the trade day"
                continue
            contract = await up.resolve_option(ukey, expiry, atm_strike(trig[4], step), opt_type)
            if contract is None:
                skips[day] = f"no {opt_type} contract for {expiry} strike {atm_strike(trig[4], step):.0f}"
                continue
            orows = await up.option_candles(contract, d_)
            if not orows:
                skips[day] = f"no option bars for {contract['trading_symbol']}"
                continue
            obars = {r[0]: r for r in orows}
            ob_in = obars.get(entry_bar[0])
            if ob_in is None:
                skips[day] = f"option bar {entry_bar[0]} missing for {contract['trading_symbol']}"
                continue
            option_sessions.setdefault(contract["trading_symbol"], {})[day] = orows
            qty = contract["lot_size"]
            rsk_pct = risk / idx_entry * 100
            tags = {"gap size": bucket(abs(sig["gap"]), [0.5, 1.0], ["0.30-0.50%", "0.50-1.00%", "1.00%+"]),
                    "trigger candle": trig[0],
                    "risk size": bucket(rsk_pct, [0.15, 0.30], ["<0.15%", "0.15-0.30%", "0.30%+"]),
                    "direction": f"{direction} ({opt_type})"}
            for mode in use_stops:
                for rr in use_rrs:
                    tgt = idx_entry + rr * risk if direction == "LONG" else idx_entry - rr * risk
                    ex = simulate(mode, rows, direction, entry_bar[0], stop, tgt)
                    if ex["bar"] is None:
                        print(f"  ! {day} {mode} 1:{rr}: no exit bar ({ex['reason']}) - trade skipped")
                        continue
                    ob_out = obars.get(ex["bar"][0])
                    if ob_out is None:
                        print(f"  ! {day} {mode} 1:{rr}: option bar {ex['bar'][0]} missing - trade skipped")
                        continue
                    epx, xpx = worst_fills("LONG", ob_in, ob_out)                   # bought option
                    mfe, mae = excursion(orows, "LONG", epx, entry_bar[0], ex["bar"][0])
                    levels = [{"name": "OR high", "price": sig["or_high"], "from": "09:15", "to": "09:30"},
                              {"name": "OR low", "price": sig["or_low"], "from": "09:15", "to": "09:30"},
                              {"name": "index stop", "price": stop, "from": entry_bar[0], "to": ex["bar"][0]},
                              {"name": f"index target 1:{rr}", "price": tgt, "from": entry_bar[0],
                               "to": ex["bar"][0]},
                              {"name": "prev close", "price": sig["prev_close"]}]
                    trades.append(make_trade(
                        day=day, side="LONG", symbol=contract["trading_symbol"], entry_time=entry_bar[0],
                        entry_px=epx, exit_time=ex["bar"][0], exit_px=xpx, qty=qty,
                        exit_reason=ex["reason"], capital=epx * qty, mfe=mfe, mae=mae,
                        expiry=contract["expiry"], option_type=opt_type,
                        variant={"gap": "up" if direction == "LONG" else "down", "stop": mode,
                                 "rr": f"1:{rr}", "pdc": pdc},
                        tags=tags, levels=levels,
                        note=(f"gap {sig['gap']:+.2f}% | level {sig['level']:.2f} | trigger candle {trig[0]} "
                              f"close {trig[4]:.2f} | index entry {idx_entry:.2f} stop {stop:.2f} "
                              f"target {tgt:.2f} risk {risk:.2f} pts")))
    print(f"\nSessions in window: {len(days)}; without a trade: {len(skips)}; "
          f"trades (all variants): {len(trades)}")
    print("Skipped days:")
    for d in sorted(skips):
        print(f"  {d}: {skips[d]}")
    if not trades:
        print("No trades - no report written.")
        return
    win_sessions = {d: sessions[d] for d in days}
    cov = coverage(win_sessions, frm, to, ROWS_PER_SESSION)
    meta = {
        "title": "Gap breakout (NIFTY, both sides)", "subtitle": f"{frm} to {to}", "instrument": "NIFTY 50",
        "from": frm.isoformat(), "to": to.isoformat(), "lot_size": trades[0]["qty"],
        "fill_rule": "Every buy at the bar's HIGH, every sell at the bar's LOW; signals acted on in the next 1m bar.",
        "cost_model": "Standard option schedule (brokerage, STT, exchange, SEBI, stamp, GST).",
        "params": {"gap threshold": f"+/-{GAP_PCT}%", "opening range": "09:15 15m candle",
                   "scan": "15m candles 09:30-11:00", "R multiples": ", ".join(f"1:{r}" for r in RRS),
                   "stop modes": ", ".join(STOP_MODES), "square-off": FORCE, "strike": "ATM, 1 lot"},
        "rule_steps": [
            "1. Gap % = (today's 09:15 open - previous session's 15:29 close) / that close.",
            f"2. Gap >= +{GAP_PCT}% arms LONG, <= -{GAP_PCT}% arms SHORT; otherwise no trade.",
            "3. Opening range = the 09:15 15-minute candle: LONG uses its high, SHORT its low.",
            "4. The first 15m candle from 09:30 (completing by 11:00) closing above/below the level is the trigger.",
            "5. Entry in the 1m bar right after the trigger candle completes: buy ATM CE (LONG) or ATM PE (SHORT), at that bar's high.",
            "6. Stop level on the index = trigger candle low (LONG) / high (SHORT).",
            "7. Stop mode close-confirmed: a completed 15m candle closes beyond the level, exit next 1m bar. "
            "Stop mode resting: any 1m bar touching the level, exit next 1m bar.",
            "8. Risk = index entry (entry bar high/low) to the stop; target = entry +/- R x risk, R = 2, 3, 4, 5.",
            "9. Target touch on 1m bars, exit next 1m bar; if one minute touches both, the stop is taken first.",
            f"10. Anything open is closed in the {FORCE} bar. Option exit sells at the exit bar's low."],
        "limits": [
            "ASSUMED: underlying NIFTY 50; traded instrument is a bought ATM option (CE for LONG, PE for SHORT), "
            "1 lot, expiry at least 1 day after the trade day; the prompt only says buy/sell.",
            "ASSUMED: stop/target/risk are index levels; P&L and R are in option rupees, so 1R on the index is not "
            "1R of premium.",
            "ASSUMED: index entry for risk/target = high (LONG) / low (SHORT) of the entry 1m bar (rule 1), not the "
            "15m open the prompt names.",
            "ASSUMED: scan covers 15m candles starting 09:30-10:45; previous session = previous one present in "
            "the feed; official daily close unused.",
            "ASSUMED: costs = standard option schedule; capital = premium x qty (bought option).",
            "Rules override the prompt: fills at bar high/low not the 15m open/close; the resting stop exits in the "
            "next 1m bar, so losses are not exactly 1R; the close-confirmed stop exits in the 1m bar after the "
            "candle completes at that bar's low, not at the candle close.",
            "Stop modes and R values are compared side by side on the same window: any pick is in-sample. "
            "One signal per session, so the sample is small; the 8 variants share the same signals.",
            "Skipped sessions are listed in the console only."],
        "coverage": cov}
    groups = [{"name": "gap size", "keys": ["gap size"]},
              {"name": "trigger candle", "keys": ["trigger candle"]},
              {"name": "risk size", "keys": ["risk size"]},
              {"name": "gap size x risk size", "keys": ["gap size", "risk size"]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups,
                            settings=SETTINGS, chart="default")
    path = write_report(payload, SLUG)
    print(console_summary(trades))
    print(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    y = date.today() - timedelta(days=1)
    ap.add_argument("--from", dest="frm", type=date.fromisoformat, default=START_DATE)
    ap.add_argument("--to", dest="to", type=date.fromisoformat, default=END_DATE)
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    asyncio.run(run(a.frm, a.to))


if __name__ == "__main__":
    main()
