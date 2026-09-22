"""Over night Hold - v3 (ONH v3): v2 plus the time-value condition, as an explorable report.

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
  Window: the prompt says "the whole period real option prices exist for, 2024-10-01 onward";
          the run window is START_DATE..END_DATE in py_funcs, shared by every
          strategy. A wider run is --from 2024-10-01, opted into and labelled as outside it.

WHAT THE RULE IS, AND WHAT THE REPORT LETS YOU MOVE
  The rule is exactly the prompt: 6 strikes ITM, the 15% time-value check ON, the first exit candle
  09:30.  Those three are the DEFAULTS of the report's control panel and are marked "the rule".
  Everything else in the panel is the same nights priced a different way, so the question
  "which setting gives the best win rate" is a click instead of an edit and a re-run:

    Strike depth   (sweep)   0 .. 12 strikes ITM - every rung is fetched and priced on the same
                             nights.  --moneyness narrows the ladder.
    First exit     (sweep)   09:16 / 09:30 / 10:00 - the earliest candle whose LOW may trigger
                             the sale.  Free: the same next-session bars are re-scanned.
    Time-value chk (filter)  off / 15% / 10% / 5% - a filter over the trades, not a re-simulation.
                             Every night is now TRADED and TAGGED with its time-value bucket, so
                             turning the check off shows the nights the rule declines.

CHECKLIST (RUN.md Step 1)
  1 Underlying           clear    NIFTY 50 index (signal and strike reference).
  2 Window               clear    THE WINDOW: START_DATE .. END_DATE in py_funcs, shared by
                                  every strategy; fixed start, current-date end. The prompt's "2024-10-01 onward" is wider
                                  and is run only on request (real option prices start 2024-10-03).
  3 Signal timeframe     clear    1-minute bars: 09:15 bar open vs 15:14 bar close.
  4 Signal rule          clear    close > open BUY CE; close < open BUY PE; equal / missing -> no trade.
                                  Time value share > 15% -> the rule's own setting declines the night.
  5 Decision time        clear    signal candle 15:14 (complete 15:15); time-value read 15:19; entry 15:20.
  6 Direction mapping    clear    up -> buy CE, down -> buy PE (always LONG the option).
  7 Traded instrument    clear    NIFTY weekly option.
  8 Option specifics     clear    buy; the rule is 6 strikes ITM (300 pts at step 50); 1 lot (ASSUMED,
                                  default); expiry: nearest weekly after tomorrow (see ASSUMED A7).
  9 Entry                clear    15:20 minute bar, at its HIGH.
 10 Exit                 clear    first 1m candle from the chosen first-exit candle with LOW > line ->
                                  sell; else 15:14 time exit; no stop, no target.
 11 Holding period       clear    overnight (entry day D, exit day = next session).
 12 Costs                assumed  standard option schedule (option_costs) - default.
 13 Position rules       assumed  one at a time (default; overnight trades cannot overlap anyway).
 14 Missing data         assumed  skip and list (default).
 15 Settings             clear    strike depth, first exit candle, time-value check (see above).
 16 Custom group-bys     assumed  none asked; two added by me (direction, time-value share bucket at 15:19).
 17 Script name          assumed  onh_v3.

ASSUMED (also in meta["limits"])
  A1  "15:20 index" (strike reference) = close of the 15:19 index bar (the last completed price at 15:20).
  A2  The "15:19 price" of the option and the index used for intrinsic value = CLOSE of the 15:19 bar.
  A3  Intrinsic value = plain (spot - strike) for a CE, (strike - spot) for a PE, using the 15:19
      index close; time value may be negative (that passes every check).
  A4  Share exactly 15% passes (only MORE than 15% is rejected); the same for the 10% and 5% settings.
  A5  "From 09:30" = candles starting 09:30 are the first checked; the earliest exit is therefore the
      09:31 bar.  The first-exit setting moves that candle, nothing else.
  A6  The line = entry price + round-trip costs per unit, the costs computed with the sale at the line itself
      (fixed-point solve; STT depends on the sale price).  It does not depend on the first-exit setting.
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
TIME_EXIT = "15:14"
STEP = 50.0
LOTS = 1
# The three entry checks, side by side.  One time-value limit is three different questions, and
# they do not agree; see the aspect catalogue in RUN.md.  All three are FILTERS: every night is
# traded and tagged, so any of them can be switched off and the nights it refused are still there.
TV_MAX_SHARE = 0.15          # the rule: time value at most this share of the premium
TV_MAX_POINTS = 60.0         # the earlier version: a flat points limit, kept for comparison
TV_RANK_KEEP = 75            # trade when tonight is among the cheapest this many in 100
TV_RANK_LOOKBACK = 60        # how many past nights at the SAME rung tonight is ranked against
TV_RANK_MIN = 20             # fewer past nights than this and the rank is not meaningful
ROWS_PER_SESSION = 375
SLUG = "onh_v3"
# The window is START_DATE .. END_DATE from py_funcs - one place for every strategy.
# Do not shadow them here; a local copy is how one script silently ran a different period.
# Only the strike ladder costs requests, and Upstox meters per second, per minute and per half
# hour, so the whole ladder over the standing window is about an hour of pacing.  Three rungs
# around the rule is what a default run ships; --moneyness 0,2,4,6,8,10,12 buys the rest.
DEFAULT_LADDER = "6,4,2,0,-2,-4,-6"

# The rungs: 6 in the money, through at the money, to 6 out of the money.  A positive value is
# strikes IN the money, a negative one OUT.
PASS_PTS, FAIL_PTS = f"<= {TV_MAX_POINTS:.0f} pts", f"above {TV_MAX_POINTS:.0f} pts"
PASS_SHARE, FAIL_SHARE = f"<= {TV_MAX_SHARE * 100:.0f}%", f"above {TV_MAX_SHARE * 100:.0f}%"
PASS_RANK, FAIL_RANK = f"cheapest {TV_RANK_KEEP} in 100", f"dearer than {TV_RANK_KEEP} in 100"
NO_RANK = "no history yet"


def rung_label(v: int) -> str:
    return "at the money" if v == 0 else f"{abs(v)} {'in' if v > 0 else 'out of'} the money"


LADDER = [6, 5, 4, 3, 2, 1, 0, -1, -2, -3, -4, -5, -6]

# The control panel.  Defaults = the rule as the prompt states it.
SETTINGS = [
    setting("tv_check", "Time-value check", kind="entry", mode="filter", default="share",
            help="the three ways of asking whether the option is too dear tonight, side by side",
            options=[
                {"value": "share", "label": f"time value <= {TV_MAX_SHARE * 100:.0f}% of premium",
                 "tag": {"tv vs share": [PASS_SHARE]}},
                {"value": "pts", "label": f"time value <= {TV_MAX_POINTS:.0f} points",
                 "tag": {"tv vs points": [PASS_PTS]}},
                {"value": "rank", "label": f"cheaper than {TV_RANK_KEEP} nights in 100",
                 "tag": {"tv vs recent": [PASS_RANK]}},
                {"value": "off", "label": "no check - every night", "tag": None}]),
    setting("first_exit", "First exit candle", kind="exit", values=["09:16", "09:30", "10:00"],
            default="09:30", help="earliest candle whose LOW may trigger the sale next morning"),
    setting("moneyness", "Strike depth", kind="strike", default=6, rerun=True,
            options=[{"value": v, "label": rung_label(v), "raw": v} for v in LADDER],
            help="every rung is priced on the same nights; --moneyness narrows the ladder"),
]


def prev_minute(hhmm: str) -> str:
    m = hhmm_minutes(hhmm) - 1
    return f"{m // 60:02d}:{m % 60:02d}"


def next_minute(hhmm: str) -> str:
    return candle_done_at(hhmm, 1)


def add_rank_tags(trades: list[dict]) -> None:
    """Tag each trade with whether tonight was cheap RELATIVE TO RECENT NIGHTS AT THE SAME RUNG.

    A flat limit, in points or as a share, is an absolute bar: options are dear when the market
    expects movement and cheap when it does not, so in a nervous stretch an absolute bar refuses
    almost every night and in a quiet one almost none.  Ranking tonight against the last
    TV_RANK_LOOKBACK nights at the same rung moves the bar with the market instead.  It needs at
    least TV_RANK_MIN past nights, so the first few weeks of every rung are tagged "no history
    yet" and the rank filter leaves them out - said here and in meta["limits"]."""
    by_rung: dict[str, list[tuple[str, float]]] = {}
    for t in trades:
        share = t["tags"].get("tv share value")
        if share is None:
            continue
        by_rung.setdefault(t["variant"]["moneyness"], []).append((t["day"], float(share)))
    cut: dict[tuple[str, str], str] = {}
    for rung, rows in by_rung.items():
        seen: dict[str, float] = {}                     # one share per night, not per exit setting
        for day, share in sorted(rows):
            seen.setdefault(day, share)
        past: list[float] = []
        for day in sorted(seen):
            share = seen[day]
            if len(past) >= TV_RANK_MIN:
                window = sorted(past[-TV_RANK_LOOKBACK:])
                idx = min(len(window) - 1, int(len(window) * TV_RANK_KEEP / 100))
                cut[(rung, day)] = PASS_RANK if share <= window[idx] else FAIL_RANK
            else:
                cut[(rung, day)] = NO_RANK
            past.append(share)
    for t in trades:
        t["tags"]["tv vs recent"] = cut.get((t["variant"]["moneyness"], t["day"]), NO_RANK)
        t["tags"].pop("tv share value", None)           # a carrier, not a group-by


def values_of(settings: list[dict], key: str) -> list:
    return [o["raw"] for o in next(s for s in settings if s["key"] == key)["options"]]


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
def simulate_exit(exit_rows: list[list], line: float, first_exit: str) -> dict:
    """First candle from `first_exit` with LOW > line is the trigger (a completed-bar signal, rule 3);
    the sale fills in the very next 1-minute bar at that bar's LOW.  Nothing by 15:14 -> the 15:14
    bar itself (a scheduled time exit).  Missing next bar -> no trade (strict)."""
    by = {r[0]: r for r in exit_rows}
    for r in exit_rows:
        if r[0] < first_exit or r[0] >= TIME_EXIT:
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
async def run(frm: date, to: date, settings: list[dict]):
    now = datetime.now(IST)
    skips: list[str] = []
    log: list[dict] = []                 # one row per session in the window, traded or not
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list[list]]] = {}
    rungs = values_of(settings, "moneyness")
    firsts = values_of(settings, "first_exit")
    chart_rung = default_combo(settings)["moneyness"]      # the only rung whose candles we keep
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
                log.append(session_row(d, "no data", f"session incomplete: {len(r)} of {ROWS_PER_SESSION} bars"))
        traded = [d for d in days if frm.isoformat() <= d <= to.isoformat()]
        print(f"index sessions fetched: {len(sessions)}, complete: {len(full)}, in window: {len(traded)}")
        print(f"strike ladder {[rung_label(v) for v in rungs]}: "
              f"{fetch_estimate(len(traded) * len(rungs) * 2)} "
              f"(fewer in practice - one night's exit day is the next night's entry day). "
              f"First-exit candles {firsts} are free: the same bars, re-scanned.")
        for d in traded:
            rows = full[d]
            side_opt, why, o915, c1514 = signal(rows)
            move = None if not o915 else (c1514 - o915) / o915 * 100
            base = {"direction": side_opt or "-", "day move %": move}
            if side_opt is None:
                skips.append(f"{d}: no trade - {why}")
                log.append(session_row(d, "no signal", why, **base))
                continue
            base["direction"] = "up day: buy CE" if side_opt == "CE" else "down day: buy PE"
            later = [x for x in days if x > d]
            if not later:
                skips.append(f"{d}: no later complete session (exit day unknown)")
                log.append(session_row(d, "no data", "no later complete session, so no exit day", **base))
                continue
            exit_day = later[0]
            if (date.fromisoformat(exit_day) - date.fromisoformat(d)).days > 5:
                skips.append(f"{d}: next complete session is {exit_day} (data gap) - skipped")
                log.append(session_row(d, "no data",
                                       f"the next complete session is {exit_day}: a feed gap, not one night", **base))
                continue
            by = {r[0]: r for r in rows}
            if READ_MIN not in by:
                skips.append(f"{d}: index 15:19 bar missing")
                log.append(session_row(d, "no data", "the index 15:19 bar is missing", **base))
                continue
            spot = by[READ_MIN][4]                                   # A1 / A2
            expiry = next_expiry(cal, date.fromisoformat(exit_day), 1)
            if expiry is None:
                skips.append(f"{d}: no expiry at least 1 day after exit day {exit_day}")
                log.append(session_row(d, "no data", f"no expiry at least a day after {exit_day}", **base))
                continue
            ixr = full[exit_day]
            # The session log records what THE RULE's own rung saw; the other rungs are the
            # panel's business.  It starts pessimistic and is overwritten when that rung prices.
            seen = {"status": "no data", "facts": dict(base),
                    "note": f"the rule's own rung ({chart_rung} strikes ITM) could not be priced"}
            for steps in rungs:
                tag = f"{d} [{steps} ITM]"
                strike = strike_offset(spot, STEP, steps, side_opt, itm=True)
                c = await up.resolve_option(key, expiry, strike, side_opt)
                if c is None:
                    skips.append(f"{tag}: contract {expiry} {strike:.0f} {side_opt} not found")
                    if steps == chart_rung:
                        seen = {"status": "no data", "facts": dict(base),
                                "note": f"the contract {expiry} {strike:.0f} {side_opt} does not exist"}
                    continue
                qty = LOTS * c["lot_size"]
                if qty <= 0:
                    skips.append(f"{tag}: contract lot size missing")
                    if steps == chart_rung:
                        seen = {"status": "no data", "facts": dict(base),
                                "note": f"the contract carries no lot size"}
                    continue
                orows = await up.option_candles(c, date.fromisoformat(d))
                ob = {r[0]: r for r in orows}
                if READ_MIN not in ob:
                    skips.append(f"{tag}: option 15:19 bar missing ({c['trading_symbol']})")
                    if steps == chart_rung:
                        seen = {"status": "no data", "facts": dict(base),
                                "note": f"the option 15:19 bar is missing"}
                    continue
                entry_bar = bar_after_candle(orows, READ_MIN, 1)      # 15:20, strict
                if entry_bar is None:
                    skips.append(f"{tag}: option 15:20 entry bar missing ({c['trading_symbol']})")
                    if steps == chart_rung:
                        seen = {"status": "no data", "facts": dict(base),
                                "note": f"the option 15:20 entry bar is missing"}
                    continue
                prem = ob[READ_MIN][4]
                if prem <= 0:
                    skips.append(f"{tag}: option 15:19 price not positive ({c['trading_symbol']})")
                    if steps == chart_rung:
                        seen = {"status": "no data", "facts": dict(base),
                                "note": f"the option 15:19 price is not positive"}
                    continue
                intrinsic = (spot - strike) if side_opt == "CE" else (strike - spot)
                share = (prem - intrinsic) / prem                     # A3
                xrows = await up.option_candles(c, date.fromisoformat(exit_day))
                if not xrows:
                    skips.append(f"{tag}: option bars for exit day {exit_day} missing ({c['trading_symbol']})")
                    if steps == chart_rung:
                        seen = {"status": "no data", "facts": dict(base),
                                "note": f"the option has no bars on the exit day {exit_day}"}
                    continue
                line = breakeven_line(entry_bar[2], qty)              # BUY at the bar's HIGH; A6
                tv_pts = prem - intrinsic
                tv_tag = bucket(share * 100, [0, 5, 10, 15.0000001],
                                ["below intrinsic", "0-5%", "5-10%", "10-15%", "above 15%"])
                checks = {"tv vs share": PASS_SHARE if share <= TV_MAX_SHARE else FAIL_SHARE,
                          "tv vs points": PASS_PTS if tv_pts <= TV_MAX_POINTS else FAIL_PTS,
                          "tv share value": f"{share:.6f}"}      # carrier for add_rank_tags
                if steps == chart_rung:
                    over = share > TV_MAX_SHARE
                    seen = {
                        "status": "declined" if over else "traded",
                        "note": (f"time value is {share * 100:.1f}% of the premium, above the rule's "
                                 f"{TV_MAX_SHARE * 100:.0f}% limit - the trade exists, set the time-value "
                                 f"check to off to count it" if over
                                 else f"bought {c['trading_symbol']} in the 15:20 minute"),
                        "facts": dict(base, **{"strike": strike, "premium 15:19": prem,
                                               "intrinsic": intrinsic, "time value": prem - intrinsic,
                                               "tv % of premium": share * 100})}
                for first in firsts:
                    ex = simulate_exit(xrows, line, first)
                    if ex["bar"] is None:
                        skips.append(f"{tag} exit>={first}: {ex['reason']} ({c['trading_symbol']}, {exit_day})")
                        continue
                    exit_bar = ex["bar"]
                    entry_px, exit_px = worst_fills("LONG", entry_bar, exit_bar)
                    xspot_bar = bar_at(ixr, prev_minute(exit_bar[0]), tolerance=3, direction=-1)
                    dated = ([[f"{d} {r[0]}"] + r[1:] for r in orows]
                             + [[f"{exit_day} {r[0]}"] + r[1:] for r in xrows])
                    mfe, mae = excursion(dated, "LONG", entry_px, f"{d} {ENTRY_MIN}", f"{exit_day} {exit_bar[0]}")
                    trades.append(make_trade(
                        day=d, exit_day=exit_day, side="LONG", symbol=c["trading_symbol"],
                        entry_time=entry_bar[0], entry_px=entry_px, exit_time=exit_bar[0], exit_px=exit_px,
                        qty=qty, exit_reason=ex["reason"], capital=entry_px * qty,
                        entry_spot=spot, exit_spot=xspot_bar[4] if xspot_bar else None,
                        target=round(line, 2), mfe=mfe, mae=mae, expiry=c["expiry"], option_type=side_opt,
                        variant={"moneyness": steps, "first_exit": first},
                        tags={"direction": "up day: buy CE" if side_opt == "CE" else "down day: buy PE",
                              "time value": tv_tag, **checks},
                        levels=[{"name": "09:15 open", "price": o915},
                                {"name": "15:14 close", "price": c1514},
                                {"name": "strike", "price": strike}],
                        note=f"{rung_label(steps)}; time value {share * 100:.1f}% of the 15:19 premium "
                             f"{prem:.2f} (intrinsic {intrinsic:.2f}); sell-line (paid + costs) {line:.2f} "
                             f"drawn as 'target'; exits scanned from {first}"))
                if steps == chart_rung:      # only the charted rung is kept: holding all seven
                    sym = c["trading_symbol"]    # cost 365 MB of RAM for charts build_payload drops
                    option_sessions.setdefault(sym, {})[d] = orows
                    option_sessions[sym][exit_day] = xrows
            log.append(session_row(d, seen["status"], seen["note"], **seen["facts"]))
        add_rank_tags(trades)
        print(f"upstox calls: {up.calls}, paced {up.paced / 60:.1f} min to stay inside the rate limit"
              + (f", rate-limited {up.throttled} times (gap now {up._min_interval:.2f}s)" if up.throttled else ""))
    return trades, skips, log, full, option_sessions, info


def report_skips(skips: list[str]) -> None:
    """One line per reason with a count and two examples: a 7-rung ladder makes the raw list
    unreadable, and the counts are what tells you whether a rung is missing data."""
    buckets: dict[str, list[str]] = {}
    for s in skips:
        reason = s.split(": ", 1)[1] if ": " in s else s
        for cut in (" (", " - "):
            if cut in reason:
                reason = reason.split(cut)[0]
        buckets.setdefault(reason.strip(), []).append(s)
    print(f"\n{len(skips)} day/rung combinations skipped or not traded, by reason:")
    for reason, rows in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(rows):5d}  {reason}")
        for r in rows[:2]:
            print(f"         e.g. {r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    today = datetime.now(IST).date()
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat(),
                    help=f"first signal day; fixed at {START_DATE} for every strategy - change it in "
                         f"py_funcs, not here, and only when asked")
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    if a.set_moneyness is None:
        a.set_moneyness = DEFAULT_LADDER
        print(f"strike ladder defaulting to {DEFAULT_LADDER} (6 ITM to 6 OTM, every other rung); "
              f"the full 13-rung ladder is --moneyness " + ",".join(str(v) for v in LADDER))
    settings = narrow(SETTINGS, a)
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    check_window(frm, to)
    trades, skips, log, sessions, option_sessions, info = asyncio.run(run(frm, to, settings))
    report_skips(skips)
    rule = default_combo(settings)
    limits = [
        "ASSUMED: '15:20 index' for the strike reference = close of the 15:19 index bar (15:20 has not completed).",
        "ASSUMED: the '15:19 price' and the index level for intrinsic value are the CLOSES of the 15:19 bars.",
        "ASSUMED: a time-value share of exactly the limit passes; negative time value passes every check.",
        "ASSUMED: the first-exit candle is the first one CHECKED, so the earliest fill is the minute after it.",
        "ASSUMED: the line = entry price + round-trip costs per unit, costs evaluated with the sale at the line. "
        "It does not depend on the first-exit setting, so the three exit settings share one line per night.",
        "ASSUMED: expiry = nearest at least 1 day after the exit day (rule 10); exit day = next complete index session.",
        "ASSUMED: 1 lot, qty from the resolved contract; standard option costs; one position at a time.",
        "RULES OVERRIDE the prompt: the low-above-line test is a completed-bar signal, so the sale fills at the NEXT "
        "minute's low (not the tested minute's low); that low can be below the line, so a 'line' exit can be a loss.",
        "The 'target' drawn on each trade is the sell-line (paid + costs), not a resting order.",
        "THE RULE is strike depth 6 ITM, the 15% time-value check, first exit 09:30 - the panel's defaults. "
        "Every other setting is the SAME NIGHTS priced differently, shown so the rule can be judged against them.",
        f"THE THREE CHECKS. A flat bar ({TV_MAX_POINTS:.0f} points, or {TV_MAX_SHARE * 100:.0f}% of premium) is "
        f"absolute: options are dear when the market expects movement, so a nervous stretch refuses almost every "
        f"night and a quiet one almost none. The rank check ('cheapest {TV_RANK_KEEP} in 100 over the last "
        f"{TV_RANK_LOOKBACK} nights at the same rung') moves with the market instead. The first {TV_RANK_MIN} "
        f"nights of every rung have no history to rank against and the rank check leaves them out.",
        f"A flat {TV_MAX_POINTS:.0f} points and {TV_MAX_SHARE * 100:.0f}% of premium are the same test only when "
        f"the premium happens to be about {TV_MAX_POINTS / TV_MAX_SHARE:.0f}. Below that, the flat limit is the "
        f"looser one. The 'Do the three checks agree?' breakdown shows where they part company.",
        "The time-value check is a FILTER over trades, not a re-simulation: every night is traded and tagged, and "
        "the check selects. Near the money almost the whole premium IS time value, so at 0-2 strikes ITM the 15% "
        "setting removes nearly every night - compare those rungs with the check off.",
        "SELECTION: the 15% limit, the 300-point strike and 09:30 come from the prompt and are measured on this same "
        "history. The ladder and the other settings are an in-sample comparison - the best cell of a grid is mostly "
        "noise, and nothing here is out of sample.",
        f"WINDOW: {START_DATE} to {END_DATE}, defined in py_funcs and shared by every strategy. The start is "
        f"fixed and the end is the current IST date when the script starts. Existing HTML is a snapshot. A wider run "
        f"(--from 2024-10-01, the floor for real option prices) is only done on request.",
        "Capital = premium x qty, so it differs by rung and return on capital is comparable across the ladder.",
        "Only nights with real option bars for both sessions are traded, per rung; the console lists every skip.",
    ]
    lot = trades[-1]["qty"] // LOTS if trades else info["lot_size"]
    meta = {
        "title": "Over night Hold v3",
        "subtitle": "Buy an ITM NIFTY weekly option at 15:20 on the day's direction, sell next session at the first "
                    "candle low above paid + costs, else 15:14. The rule is 6 strikes ITM with the 15% time-value "
                    "check; the panel prices every other setting on the same nights.",
        "instrument": "NIFTY 50 weekly options",
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": lot,
        "fill_rule": "Buy at the bar's high, sell at the bar's low; signals act in the next 1-minute bar",
        "cost_model": "Upstox option schedule (option_costs): brokerage 20/order, STT on sell, exchange, SEBI, stamp, GST",
        "params": {"signal": "09:15 open vs 15:14 close (1m)",
                   "the rule": f"{rule['moneyness']} strikes ITM, first exit {rule['first_exit']}, "
                               f"time-value check 15%",
                   "strike ladder": ", ".join(rung_label(v) for v in values_of(settings, "moneyness")),
                   "first exit candles": ", ".join(values_of(settings, "first_exit")),
                   "time-value checks": f"<= {TV_MAX_SHARE * 100:.0f}% of premium (the rule) | "
                                        f"<= {TV_MAX_POINTS:.0f} points | cheapest {TV_RANK_KEEP} in 100 "
                                        f"over {TV_RANK_LOOKBACK} nights | none",
                   "strike step": f"{STEP:.0f}", "entry": ENTRY_MIN, "time exit": TIME_EXIT, "lots": LOTS,
                   "expiry": "nearest >= 1 day after exit day"},
        "rule_steps": [
            "Take the session's 09:15 open and the 15:14 close (1-minute bars); a missing one means no trade.",
            "Close above open: buy a call. Close below: buy a put. Equal: no trade.",
            "Reference = index at 15:19 (close), strike = 6 strikes in the money (300 points) for the rule, "
            "nearest expiry at least a day after the exit day.",
            "At 15:19 read the option price; time value = price - intrinsic; share = time value / price.",
            "Share above 15%: no trade tonight. The panel compares that against two other ways of "
            "asking the same question - a flat 60 points, and 'cheaper than 75 nights in 100 recently' - "
            "and against no check at all, on the same nights.",
            "Otherwise buy in the 15:20 minute at that bar's high; line = paid + round-trip costs per unit.",
            "Next session, from the 09:30 candle: if a candle's low is above the line, sell in the next minute "
            "at its low. (The panel's first-exit candle moves 09:30.)",
            "Nothing qualifying by then: sell in the 15:14 minute at its low.",
            "No stop, no target.",
        ],
        "limits": limits,
        "rejected": [
            ["Strikes further out than the money", "not in the ladder at all: out of the money there is no "
             "intrinsic value, so the time-value share is 100% and the rule declines every night by construction."],
            ["A stop or a profit target", "the prompt says neither, and adding one here would be a different rule "
             "chosen on the same history."],
            ["Holding more than one night", "the rule sells on the next session; a multi-night hold changes the "
             "expiry choice and is not comparable."],
            ["Selling the option instead of buying", "capital would be a margin estimate rather than the premium, "
             "so return on capital would not be comparable with the rungs shown."],
        ],
        "coverage": coverage(sessions, frm, to, ROWS_PER_SESSION),
        "rerun": rerun_command(SLUG, settings, frm.isoformat(), to.isoformat()),
    }
    groups = [{"name": "Direction", "keys": ["direction"]},
              {"name": "Time value share at 15:19", "keys": ["time value"]},
              {"name": "Do the three checks agree?", "keys": ["tv vs share", "tv vs points", "tv vs recent"]},
              {"name": "Cheap or dear against recent nights", "keys": ["tv vs recent"]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups,
                            settings=settings, chart="default", sessions_log=log)
    path = write_report(payload, SLUG)
    print(console_summary(trades))
    print(path)


if __name__ == "__main__":
    main()
