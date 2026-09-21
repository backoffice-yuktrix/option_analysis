"""Over night Hold - v3 (ONH v3): v2 plus the time-value condition.

USER PROMPT (verbatim summary of the steps)
  Step 1  After the 15:14 candle, take the session's own bar: the 09:15 open and the 15:14 close.
  Step 2  Close above open -> BUY a call. Close below -> SELL, i.e. buy a put. Equal / candle missing -> no trade.
  Step 3  Strike six strikes ITM: BUY = call 300 points below, SELL = put 300 points above, reference =
          the 15:20 index rounded to the nearest 50. Expiry = nearest weekly after tomorrow.
  Step 4  At 15:19 read that contract's price; time value = 15:19 price - intrinsic (distance strike to
          index, ~300); share = time value / 15:19 price.
  Step 5  If the share is MORE than 15% of the premium, no trade tonight.
  Step 6  It is read at 15:19, one minute before the entry, from a price that has already printed.
  Step 7  Otherwise buy in the 15:20 minute; the line = what I paid + the round-trip costs.
  Step 8  From 09:30 tomorrow, after each one-minute candle: was the LOW of that minute above the line?
          Yes -> sell now, at that low. No -> wait.
  Step 9  If nothing qualifies by 15:14, sell in the 15:14 minute.
  Step 10 No stop.   Step 11 No profit target.
  Step 12 Buy at the entry minute's high, sell at the exit minute's low.
  Window: the whole period real option prices exist for, 2024-10-01 onward.

CHECKLIST (RUN.md Step 1)
  1 Underlying           clear    NIFTY 50 index (signal and strike reference).
  2 Window               clear    2024-10-01 .. yesterday (prompt names it); --from / --to override.
  3 Signal timeframe     clear    1-minute bars: 09:15 bar open vs 15:14 bar close.
  4 Signal rule          clear    close > open BUY CE; close < open BUY PE; equal / missing -> no trade.
                                  Time value share > 15% -> no trade (numbers given).
  5 Decision time        clear    signal candle 15:14 (complete 15:15); time-value read 15:19; entry 15:20.
  6 Direction mapping    clear    up -> buy CE, down -> buy PE (always LONG the option).
  7 Traded instrument    clear    NIFTY weekly option.
  8 Option specifics     clear    buy; 6 strikes ITM (300 pts at step 50); 1 lot (ASSUMED, default);
                                  expiry: nearest weekly after tomorrow (see conflicts / ASSUMED).
  9 Entry                clear    15:20 minute bar, at its HIGH.
 10 Exit                 clear    first 1m candle from 09:30 next session with LOW > line -> sell; else
                                  15:14 time exit; no stop, no target.
 11 Holding period       clear    overnight (entry day D, exit day = next session).
 12 Costs                assumed  standard option schedule (option_costs) - default.
 13 Position rules       assumed  one at a time (default; overnight trades cannot overlap anyway).
 14 Missing data         assumed  skip and list (default).
 15 Filters              clear    none asked; only `side` (always LONG).
 16 Custom group-bys     assumed  none asked; two added by me (direction, time-value share bucket at 15:19).
 17 Script name          assumed  onh_v3.

ASSUMED (also in meta["limits"])
  A1  "15:20 index" (strike reference) = close of the 15:19 index bar (the last completed price at 15:20).
  A2  The "15:19 price" of the option and the index used for intrinsic value = CLOSE of the 15:19 bar.
  A3  Intrinsic value = plain (spot - strike) for a CE, (strike - spot) for a PE, using the 15:19
      index close; time value may be negative (that passes the <=15% test).
  A4  Share exactly 15% passes (only MORE than 15% is rejected).
  A5  "From 09:30" = candles starting 09:30 are the first checked; the earliest exit is therefore the 09:31 bar.
  A6  The line = entry price + round-trip costs per unit, the costs computed with the sale at the line itself
      (fixed-point solve; STT depends on the sale price).
  A7  Expiry = nearest at least 1 day after the EXIT day (RUN.md rule 10); exit day = next available complete
      session in the index data (a feed gap would lengthen the hold; unknowable from the data).
  A8  1 lot; qty = lot_size of the resolved contract.
  A9  Strike step read from Upstox must equal 50, else the script aborts.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *          # noqa: F401,F403
import argparse

ENTRY_MIN = "15:20"
READ_MIN = "15:19"
SIGNAL_MIN = "15:14"
FIRST_EXIT_CANDLE = "09:30"
TIME_EXIT = "15:14"
TV_LIMIT = 0.15
STEPS_ITM = 6
STEP = 50.0
LOTS = 1
ROWS_PER_SESSION = 375
SLUG = "onh_v3"


def prev_minute(hhmm: str) -> str:
    m = hhmm_minutes(hhmm) - 1
    return f"{m // 60:02d}:{m % 60:02d}"


def next_minute(hhmm: str) -> str:
    return candle_done_at(hhmm, 1)


# ---------------------------------------------------------------------------
# signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def signal(rows: list[list]) -> tuple[str | None, str, float | None, float | None]:
    """(direction 'CE'|'PE'|None, reason, open 09:15, close 15:14)."""
    by = {r[0]: r for r in rows}
    if "09:15" not in by or SIGNAL_MIN not in by:
        return None, "09:15 or 15:14 candle missing", None, None
    o, c = by["09:15"][1], by[SIGNAL_MIN][4]
    if c > o:
        return "CE", "close above open", o, c
    if c < o:
        return "PE", "close below open", o, c
    return None, "close equals open", o, c


def breakeven_line(entry_px: float, qty: int) -> float:
    """Entry price + round-trip costs per unit, costs evaluated with the sale at the line (fixed point)."""
    line = entry_px
    for _ in range(60):
        new = entry_px + option_round_trip("LONG", entry_px, line, qty) / qty
        if abs(new - line) < 1e-6:
            return new
        line = new
    return line


# ---------------------------------------------------------------------------
# simulate (pure: bars -> exit)
# ---------------------------------------------------------------------------
def simulate_exit(exit_rows: list[list], line: float) -> dict:
    """First candle from 09:30 with LOW > line is the trigger (a completed-bar signal, rule 3);
    the sale fills in the very next 1-minute bar at that bar's LOW.  Nothing by 15:14 -> the 15:14
    bar itself (a scheduled time exit).  Missing next bar -> no trade (strict)."""
    by = {r[0]: r for r in exit_rows}
    for r in exit_rows:
        if r[0] < FIRST_EXIT_CANDLE or r[0] >= TIME_EXIT:
            continue
        if r[3] > line:
            nxt = by.get(next_minute(r[0]))
            if nxt is None:
                return {"bar": None, "reason": f"bar after trigger {r[0]} missing", "trigger": r}
            return {"bar": nxt, "reason": "low above line", "trigger": r}
    tb = by.get(TIME_EXIT)
    if tb is None:
        return {"bar": None, "reason": "15:14 exit bar missing", "trigger": None}
    return {"bar": tb, "reason": "time exit", "trigger": None}


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
async def run(frm: date, to: date):
    now = datetime.now(IST)
    skips: list[str] = []
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list[list]]] = {}
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        if info["strike_step"] != STEP:
            raise SystemExit(f"Upstox strike step is {info['strike_step']}, the prompt assumes {STEP}.")
        fetch_to = min(to + timedelta(days=7), now.date())
        cs = await up.candles(key, "1m", frm, fetch_to)
        sessions = sessions_from(cs)
        cal = await up.expiry_calendar(key, frm, to)
        # complete sessions only (rule 7); today's only after 15:45
        full = {d: r for d, r in sessions.items()
                if len(r) >= ROWS_PER_SESSION and not (d == now.date().isoformat() and now.strftime("%H:%M") < "15:45")}
        days = sorted(full)
        for d, r in sessions.items():
            if d not in full and frm.isoformat() <= d <= to.isoformat():
                skips.append(f"{d}: session incomplete ({len(r)} bars) - not used")
        print(f"index sessions fetched: {len(sessions)}, complete: {len(full)}")
        for d in days:
            if not (frm.isoformat() <= d <= to.isoformat()):
                continue
            rows = full[d]
            side_opt, why, o915, c1514 = signal(rows)
            if side_opt is None:
                skips.append(f"{d}: no trade - {why}")
                continue
            later = [x for x in days if x > d]
            if not later:
                skips.append(f"{d}: no later complete session (exit day unknown)")
                continue
            exit_day = later[0]
            if (date.fromisoformat(exit_day) - date.fromisoformat(d)).days > 5:
                skips.append(f"{d}: next complete session is {exit_day} (data gap) - skipped")
                continue
            by = {r[0]: r for r in rows}
            if READ_MIN not in by:
                skips.append(f"{d}: index 15:19 bar missing")
                continue
            spot = by[READ_MIN][4]                                   # A1 / A2
            strike = strike_offset(spot, STEP, STEPS_ITM, side_opt, itm=True)
            expiry = next_expiry(cal, date.fromisoformat(exit_day), 1)
            if expiry is None:
                skips.append(f"{d}: no expiry at least 1 day after exit day {exit_day}")
                continue
            c = await up.resolve_option(key, expiry, strike, side_opt)
            if c is None:
                skips.append(f"{d}: contract {expiry} {strike:.0f} {side_opt} not found")
                continue
            qty = LOTS * c["lot_size"]
            if qty <= 0:
                skips.append(f"{d}: contract lot size missing")
                continue
            orows = await up.option_candles(c, date.fromisoformat(d))
            ob = {r[0]: r for r in orows}
            if READ_MIN not in ob:
                skips.append(f"{d}: option 15:19 bar missing ({c['trading_symbol']})")
                continue
            entry_bar = bar_after_candle(orows, READ_MIN, 1)          # 15:20, strict
            if entry_bar is None:
                skips.append(f"{d}: option 15:20 entry bar missing ({c['trading_symbol']})")
                continue
            prem = ob[READ_MIN][4]
            intrinsic = (spot - strike) if side_opt == "CE" else (strike - spot)
            tv = prem - intrinsic
            share = tv / prem if prem > 0 else None
            if share is None:
                skips.append(f"{d}: option 15:19 price not positive")
                continue
            if share > TV_LIMIT:
                skips.append(f"{d}: no trade - time value {share * 100:.1f}% of premium > 15% "
                             f"({c['trading_symbol']}, prem {prem:.2f}, intrinsic {intrinsic:.2f})")
                continue
            xrows = await up.option_candles(c, date.fromisoformat(exit_day))
            if not xrows:
                skips.append(f"{d}: option bars for exit day {exit_day} missing ({c['trading_symbol']})")
                continue
            entry_px = entry_bar[2]                                   # BUY at the bar's HIGH
            line = breakeven_line(entry_px, qty)
            ex = simulate_exit(xrows, line)
            if ex["bar"] is None:
                skips.append(f"{d}: {ex['reason']} ({c['trading_symbol']}, exit day {exit_day})")
                continue
            exit_bar = ex["bar"]
            entry_px, exit_px = worst_fills("LONG", entry_bar, exit_bar)
            ixr = full[exit_day]
            xspot_bar = bar_at(ixr, prev_minute(exit_bar[0]), tolerance=3, direction=-1)
            dated = ([[f"{d} {r[0]}"] + r[1:] for r in orows] + [[f"{exit_day} {r[0]}"] + r[1:] for r in xrows])
            mfe, mae = excursion(dated, "LONG", entry_px, f"{d} {ENTRY_MIN}", f"{exit_day} {exit_bar[0]}")
            tv_tag = bucket(share * 100, [0, 5, 10, 15.0000001],
                            ["below intrinsic", "0-5%", "5-10%", "10-15%", "above 15%"])
            trades.append(make_trade(
                day=d, exit_day=exit_day, side="LONG", symbol=c["trading_symbol"],
                entry_time=entry_bar[0], entry_px=entry_px, exit_time=exit_bar[0], exit_px=exit_px,
                qty=qty, exit_reason=ex["reason"], capital=entry_px * qty,
                entry_spot=spot, exit_spot=xspot_bar[4] if xspot_bar else None,
                target=round(line, 2), mfe=mfe, mae=mae, expiry=c["expiry"], option_type=side_opt,
                tags={"direction": "up day: buy CE" if side_opt == "CE" else "down day: buy PE",
                      "time value": tv_tag},
                levels=[{"name": "09:15 open", "price": o915},
                        {"name": "15:14 close", "price": c1514},
                        {"name": "strike", "price": strike}],
                note=f"time value {share * 100:.1f}% of 15:19 premium {prem:.2f}; "
                     f"sell-line (paid + costs) {line:.2f} drawn as 'target'"))
            option_sessions.setdefault(c["trading_symbol"], {})[d] = orows
            option_sessions[c["trading_symbol"]][exit_day] = xrows
    return trades, skips, full, option_sessions, info


def main() -> None:
    ap = argparse.ArgumentParser()
    yesterday = datetime.now(IST).date() - timedelta(days=1)
    ap.add_argument("--from", dest="frm", default="2024-10-01")
    ap.add_argument("--to", dest="to", default=yesterday.isoformat())
    a = ap.parse_args()
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    trades, skips, sessions, option_sessions, info = asyncio.run(run(frm, to))
    print(f"\n{len(skips)} days skipped or not traded:")
    for s in skips:
        print("  " + s)
    limits = [
        "ASSUMED: '15:20 index' for the strike reference = close of the 15:19 index bar (15:20 has not completed).",
        "ASSUMED: the '15:19 price' and the index level for intrinsic value are the CLOSES of the 15:19 bars.",
        "ASSUMED: a time-value share of exactly 15% passes; negative time value passes.",
        "ASSUMED: 'from 09:30' = candles starting 09:30 are checked first, so the earliest exit fill is the 09:31 bar.",
        "ASSUMED: the line = entry price + round-trip costs per unit, costs evaluated with the sale at the line.",
        "ASSUMED: expiry = nearest at least 1 day after the exit day (rule 10); exit day = next complete index session.",
        "ASSUMED: 1 lot, qty from the resolved contract; standard option costs; one position at a time.",
        "RULES OVERRIDE the prompt: the low-above-line test is a completed-bar signal, so the sale fills at the NEXT "
        "minute's low (not the tested minute's low); that low can be below the line, so a 'line' exit can be a loss.",
        "The 'target' drawn on each trade is the sell-line (paid + costs), not a resting order.",
        "Selection: the 15% limit and 300-point strike come from the prompt, chosen on this same history (in-sample); "
        "no variants are compared.",
        "Capital = premium x qty. Only nights with real option bars for both sessions are traded; others are skipped.",
        "Underlying prices used at 15:19 come from the index candles; the option's own 15:19 close is what the "
        "time-value test reads.",
    ]
    meta = {
        "title": "Over night Hold v3",
        "subtitle": "Buy a 6-strike ITM NIFTY weekly option at 15:20 on the day's direction, skip when time value "
                    "exceeds 15% of premium, sell next session at the first candle low above paid + costs, else 15:14",
        "instrument": "NIFTY 50 weekly options",
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": trades[-1]["qty"] // LOTS if trades else info["lot_size"],
        "fill_rule": "Buy at the bar's high, sell at the bar's low; signals act in the next 1-minute bar",
        "cost_model": "Upstox option schedule (option_costs): brokerage 20/order, STT on sell, exchange, SEBI, stamp, GST",
        "params": {"signal": "09:15 open vs 15:14 close (1m)", "strike": f"{STEPS_ITM} strikes ITM (step {STEP:.0f})",
                   "time value limit": f"{TV_LIMIT * 100:.0f}% of 15:19 premium", "entry": ENTRY_MIN,
                   "first exit candle": FIRST_EXIT_CANDLE, "time exit": TIME_EXIT, "lots": LOTS,
                   "expiry": "nearest >= 1 day after exit day"},
        "rule_steps": [
            "Take the session's 09:15 open and the 15:14 close (1-minute bars); a missing one means no trade.",
            "Close above open: buy a call. Close below: buy a put. Equal: no trade.",
            "Reference = index at 15:19 (close), strike = 6 strikes in the money (300 points), nearest expiry at least a day after the exit day.",
            "At 15:19 read the option price; time value = price - intrinsic; share = time value / price.",
            "Share above 15%: no trade tonight.",
            "Otherwise buy in the 15:20 minute at that bar's high; line = paid + round-trip costs per unit.",
            "Next session, from the 09:30 candle: if a candle's low is above the line, sell in the next minute at its low.",
            "Nothing qualifying by then: sell in the 15:14 minute at its low.",
            "No stop, no target.",
        ],
        "limits": limits,
        "coverage": coverage(sessions, frm, to, ROWS_PER_SESSION),
    }
    groups = [{"name": "Direction", "keys": ["direction"]},
              {"name": "Time value share at 15:19", "keys": ["time value"]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups)
    path = write_report(payload, "onh_v3")
    print(console_summary(trades))
    print(path)


if __name__ == "__main__":
    main()
