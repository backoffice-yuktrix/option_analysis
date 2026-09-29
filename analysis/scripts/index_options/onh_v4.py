"""Over night Hold - v4 (ONH v4): the overnight hold traded on a PLAYBOOK of six scenarios.

THE RULE (built 2026-09-29 from a one-year scenario study, then stress-tested on the year before it)
  Step 1  After the 15:14 candle, take the session's 09:15 open and 15:14 close.  Up day -> the trade is
          a CALL, down day -> a PUT; equal / candle missing -> no trade.  (Direction as in v2/v3.)
  Step 2  Trade tonight only if ANY of these scenarios is true (all read from candles complete by 15:14,
          plus the option's 15:19 price for E):
            A  the 5-day trend agrees with the day, and today's range is NORMAL
            B  the 15:14 close is in the day's strongest 20% (top 20% on an up day, bottom 20% on a
               down day), and the range is normal
            C  a SMALL day (15:14 close within 0.3% of the 09:15 open), and the range is normal
            D  a small day, and the LAST 15 MINUTES (14:59 close -> 15:14 close) pulled back against the day
            E  the last 15 minutes pulled back against the day, and time value is at most 15% of the
               option's 15:19 price
            F  a small day whose 15:14 close sits in the MIDDLE of the day's range (location 0.5 to 0.8
               in the day's direction)
          NORMAL range = today's 09:15-15:14 high-low between 0.8 and 1.2 x the average full-day range of
          the previous 20 complete sessions.  5-day trend = today's 15:14 close vs the 15:14 close five
          complete sessions earlier.
  Step 3  Strike six strikes ITM (300 points; reference = the 15:19 index close rounded to 50); expiry =
          nearest at least one day after the exit day.
  Step 4  Buy in the 15:20 minute at that minute's HIGH; line = paid + round-trip costs per unit.
  Step 5  From 09:30 next session: when a completed minute's LOW is above the line, sell in the NEXT
          minute at its LOW.  Nothing by 15:14 -> sell in the 15:14 minute at its LOW.  No stop, no target.
  WORST FILL ONLY: every buy at the minute's high, every sell at its low; the report carries no
  middle/close comparison and refuses a better fill.

WHERE IT COMES FROM AND HOW HARD IT WAS PUSHED (scratchpad, 2026-09-29; real premiums, 6 ITM, worst fill)
  Built on 29 Sep 2025 - 25 Sep 2026 from 556 one- and two-factor scenarios, keeping only those that held
  when chosen on Oct-Mar and checked on Apr-Sep.  Stress-tested on the year BEFORE (Oct 2024 - Sep 2025),
  which the choice never saw.  Two changes came out of the stress test, both allowed only because they
  did not cut the trade count: the pull-back is read over 15 minutes (it was 30), and scenario F added.
                         build year (Sep25-Sep26)            year before, unseen (Oct24-Sep25)
    every night          245 trades 67% win PF 1.20 +1.36L   234 trades 66% win PF 1.07 +0.34L
    v3 (5-day trend)     143 trades 72% win PF 1.46 +1.56L   142 trades 68% win PF 1.09 +0.28L
    v4 (this rule)       140 trades 76% win PF 2.74 +3.69L   149 trades 68% win PF 1.28 +0.73L
  Resampled 10,000 times: the build year never loses; the unseen year loses in 16% of resamples (its 5-95%
  range is -0.49L .. +1.96L).  Worst drawdown at 95%: about -0.8L; worst losing streak at 95%: 6; worst
  single night about -17k.  Two points of extra slippage per side erase the unseen year's profit.
  The playbook's lead in the build year is largely that year's own fit; in the unseen year it is a
  modest improvement on every night.  Treat it as provisional.

The panel: 'Direction check' offers the v4 playbook (the rule), v3's 5-day trend, and no check; the
earlier time-value check, the strike ladder and the first-exit candle stay as in v3.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
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
SLUG = "onh_v4"
# THE RULE's direction check: the day must agree with the 5-day trend.
TREND_N = 5                  # complete sessions back for the trend (15:14 close vs 15:14 close)
TREND_LOOKBACK_DAYS = 40     # calendar days fetched before --from: 20 sessions for the range, 5 for the trend
# THE PLAYBOOK's thresholds (see the docstring)
RANGE_N, RANGE_BAND = 20, (0.8, 1.2)   # normal range: today's range / average of the previous 20 full days
SMALL_MOVE = 0.3                        # a small day: 15:14 close within this % of the 09:15 open
STRONG_CLOSE = 0.8                      # close location (in the day's direction) at or above this = strong close
MIDDLE_CLOSE = (0.5, 0.8)               # scenario F: close location in this band
LATE_MIN = 15                           # the pull-back window: the last 15 minutes, 14:59 close -> 15:14 close
TREND_TAG, PLAYBOOK_TAG, SCEN_TAG = "5-day trend", "v4 playbook", "scenarios"
SCEN_LABEL = {"A": "A trend + normal range", "B": "B strong close + normal range", "C": "C small day + normal range",
              "D": "D small day + late pull-back", "E": "E late pull-back + time value <= 15%",
              "F": "F small day + middle close"}
AGREES, AGAINST, NO_HIST = "agrees with the day", "against the day", "no history yet"
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
    setting("confirm", "Direction check", kind="entry", mode="filter", default="playbook",
            help="which nights the day's direction is traded on; 'off' trades every night",
            options=[
                {"value": "playbook", "label": "the v4 playbook: any of scenarios A-F (the rule)",
                 "tag": {PLAYBOOK_TAG: ["yes"]}},
                {"value": "trend", "label": f"v3: the {TREND_N}-day trend agrees with the day",
                 "tag": {TREND_TAG: [AGREES]}},
                {"value": "off", "label": "no check - every night", "tag": None}]),
    setting("tv_check", "Time-value check (the earlier rule)", kind="entry", mode="filter", default="off",
            help="the earlier v3 check, kept for comparison: is the option too dear tonight?",
            options=[
                {"value": "share", "label": f"time value <= {TV_MAX_SHARE * 100:.0f}% of premium",
                 "tag": {"tv vs share": [PASS_SHARE]}},
                {"value": "pts", "label": f"time value <= {TV_MAX_POINTS:.0f} points",
                 "tag": {"tv vs points": [PASS_PTS]}},
                {"value": "rank", "label": f"cheaper than {TV_RANK_KEEP} nights in 100",
                 "tag": {"tv vs recent": [PASS_RANK]}},
                {"value": "off", "label": "no time-value check (the rule)", "tag": None}]),
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


def direction_checks(full: dict[str, list[list]], days: list[str], d: str, side_opt: str, c1514: float) -> dict:
    """Everything the playbook reads, from candles complete by 15:14 only (rule 4).  Scenario E also needs
    the option's 15:19 time value, so it is decided per contract in the loop."""
    sgn = 1 if side_opt == "CE" else -1
    i = days.index(d)
    ref = None
    if i >= TREND_N:
        ref = next((r[4] for r in full[days[i - TREND_N]] if r[0] == SIGNAL_MIN), None)
    if ref is None:
        trend, trend_pct = NO_HIST, None
    else:
        trend_pct = (c1514 - ref) / ref * 100
        trend = AGREES if trend_pct * sgn > 0 else AGAINST
    win = [r for r in full[d] if "09:15" <= r[0] <= SIGNAL_MIN]
    hi, lo = max(r[2] for r in win), min(r[3] for r in win)
    loc = (c1514 - lo) / (hi - lo) if hi > lo else 0.5
    loc_dir = loc if sgn > 0 else 1 - loc
    past = days[max(0, i - RANGE_N):i]
    rng_ratio = None
    if len(past) == RANGE_N:
        avg = sum(max(r[2] for r in full[x]) - min(r[3] for r in full[x]) for x in past) / RANGE_N
        rng_ratio = (hi - lo) / avg if avg > 0 else None
    o915 = win[0][1]
    move = abs(c1514 - o915) / o915 * 100
    c_late = next((r[4] for r in full[d] if r[0] == prev_n_minutes(SIGNAL_MIN, LATE_MIN)), None)
    late_pull = c_late is not None and (c1514 - c_late) * sgn <= 0
    normal = rng_ratio is not None and RANGE_BAND[0] <= rng_ratio < RANGE_BAND[1]
    small = move < SMALL_MOVE
    scen = {"A": trend == AGREES and normal, "B": loc_dir >= STRONG_CLOSE and normal, "C": small and normal,
            "D": small and late_pull, "F": small and MIDDLE_CLOSE[0] <= loc_dir < MIDDLE_CLOSE[1]}
    return {TREND_TAG: trend, "trend5 %": trend_pct, "close location": loc_dir, "range ratio": rng_ratio,
            "day move %": move, "late pull-back": late_pull, "scen": scen}


def prev_n_minutes(hhmm: str, n: int) -> str:
    m = hhmm_minutes(hhmm) - n
    return f"{m // 60:02d}:{m % 60:02d}"


def breakeven_line(entry_px: float, qty: int, day=None) -> float:
    """Entry price + round-trip costs per unit, costs evaluated with the sale at the line (fixed point)."""
    line = entry_px
    for _ in range(60):
        new = entry_px + option_round_trip("LONG", entry_px, line, qty, day=day) / qty
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
        # TREND_LOOKBACK_DAYS before --from: read for the 5-day trend only, never traded
        cs = await up.candles(key, "1m", frm - timedelta(days=TREND_LOOKBACK_DAYS), fetch_to)
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
            checks = direction_checks(full, days, d, side_opt, c1514)
            base.update({"5-day trend": checks[TREND_TAG], "5-day trend %": checks["trend5 %"],
                         "close location (day's direction)": checks["close location"],
                         "range vs 20-day average": checks["range ratio"],
                         f"last {LATE_MIN} min pulled back": "yes" if checks["late pull-back"] else "no"})
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
                line = breakeven_line(entry_bar[2], qty, d)              # BUY at the bar's HIGH; A6
                tv_pts = prem - intrinsic
                tv_tag = bucket(share * 100, [0, 5, 10, 15.0000001],
                                ["below intrinsic", "0-5%", "5-10%", "10-15%", "above 15%"])
                tvc = {"tv vs share": PASS_SHARE if share <= TV_MAX_SHARE else FAIL_SHARE,
                          "tv vs points": PASS_PTS if tv_pts <= TV_MAX_POINTS else FAIL_PTS,
                          "tv share value": f"{share:.6f}"}      # carrier for add_rank_tags
                scen = dict(checks["scen"], E=checks["late pull-back"] and share <= TV_MAX_SHARE)
                fired = [k for k in "ABCDEF" if scen[k]]
                rule_ok = bool(fired)
                if steps == chart_rung:
                    seen = {
                        "status": "traded" if rule_ok else "declined",
                        "note": (f"bought {c['trading_symbol']} in the 15:20 minute - scenario {'+'.join(fired)}"
                                 if rule_ok else "no playbook scenario fired - the trade exists, set the "
                                 "direction check to off to count it"),
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
                    # WORST FILL ONLY (the user, 2026-09-29): bought at the entry minute's HIGH, sold at the
                    # exit minute's LOW - checked here for every rung, since the report keeps only one rung's bars
                    if entry_px != entry_bar[2] or exit_px != exit_bar[3]:
                        raise SystemExit(f"{tag}: fill is not the worst price (in {entry_px} vs high {entry_bar[2]}, "
                                         f"out {exit_px} vs low {exit_bar[3]})")
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
                              TREND_TAG: checks[TREND_TAG], PLAYBOOK_TAG: "yes" if rule_ok else "no",
                              SCEN_TAG: "+".join(fired) if fired else "none",
                              **{SCEN_LABEL[k]: "yes" if scen[k] else "no" for k in "ABCDEF"},
                              "time value": tv_tag, **tvc},
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
        "THE RULE is strike depth 6 ITM, the v4 playbook (any of scenarios A-F), time-value check OFF, first exit "
        "09:30 - the panel's defaults. Every other setting is the SAME NIGHTS priced differently; 'Direction check' "
        "also offers v3's 5-day trend and no check at all, so the playbook can be judged against both.",
        f"ASSUMED: every playbook input is read from candles complete by 15:14 - the 5-day trend (15:14 close vs "
        f"the 15:14 close {TREND_N} complete sessions earlier; flat counts as against), the day's range against the "
        f"average full-day range of the previous {RANGE_N} complete sessions, the day's move (15:14 close vs 09:15 "
        f"open), the close location in the 09:15-15:14 range, and the last {LATE_MIN} minutes (14:59 close to 15:14 "
        f"close; no change counts as a pull-back). Scenario E alone also reads the option's 15:19 price.",
        f"The index is fetched from {TREND_LOOKBACK_DAYS} calendar days before the window so its first nights have "
        f"{RANGE_N} sessions behind them; those days are read, never traded. A night without them cannot fire "
        f"scenarios A-C and is judged on D, E and F only.",
        "WORST FILL ONLY (the user, 2026-09-29): every buy at the minute's HIGH and every sell at the minute's LOW, "
        "entry and exit alike. The script stops if any trade on any rung is filled otherwise, and the report carries "
        "no middle or close comparison.",
        "STRESS TEST (scratchpad, real premiums, 6 ITM, worst fill; not in this report): built on Sep 2025-Sep 2026 "
        "(140 trades, 76% won, PF 2.74, +3.69L) and checked on the year before, which the choice never saw (149 "
        "trades, 68% won, PF 1.28, +0.73L; every night that year: PF 1.07, +0.34L). Resampled 10,000 times the "
        "unseen year loses 16% of the time; two extra points of slippage per side erase its profit. Treat the "
        "build year's numbers as in-sample.",
        "CHANGES MADE BY THE STRESS TEST, allowed only because neither cut the trade count: the pull-back window is "
        "15 minutes (30 was the first design; 15 improved both years), and scenario F (small day, middle close) was "
        "added - it paid in both years.",
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
        "SELECTION: the playbook, the 300-point strike and 09:30 were chosen on data that includes this window. "
        "The ladder and the other settings are an in-sample comparison - the best cell of a grid is mostly "
        "noise, and nothing here is out of sample.",
        f"WINDOW: {START_DATE} to {END_DATE}, defined in py_funcs and shared by every strategy. The start is "
        f"fixed and the end is the current IST date when the script starts. Existing HTML is a snapshot. A wider run "
        f"(--from 2024-10-01, the floor for real option prices) is only done on request.",
        "Capital = premium x qty, so it differs by rung and return on capital is comparable across the ladder.",
        "Only nights with real option bars for both sessions are traded, per rung; the console lists every skip.",
    ]
    lot = trades[-1]["qty"] // LOTS if trades else info["lot_size"]
    meta = {
        "title": "Over night Hold v4",
        "subtitle": "Buy an ITM NIFTY weekly option at 15:20 on the day's direction when any of six playbook "
                    "scenarios fires, sell next session at the first candle low above paid + costs, else 15:14. "
                    "Worst fill only. The panel prices every other setting on the same nights.",
        "instrument": "NIFTY 50 weekly options",
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": lot,
        "fill_rule": "WORST FILL ONLY: buy at the minute's HIGH, sell at the minute's LOW, entry and exit; "
                     "signals act in the next 1-minute bar",
        "params": {"signal": "09:15 open vs 15:14 close (1m)",
                   "the rule": f"{rule['moneyness']} strikes ITM, v4 playbook (A-F), first exit "
                               f"{rule['first_exit']}, time-value check off",
                   "playbook": " | ".join(SCEN_LABEL[k] for k in "ABCDEF"),
                   "thresholds": f"normal range {RANGE_BAND[0]}-{RANGE_BAND[1]} x {RANGE_N}-day average; small day "
                                 f"< {SMALL_MOVE}%; strong close >= {STRONG_CLOSE}; middle close "
                                 f"{MIDDLE_CLOSE[0]}-{MIDDLE_CLOSE[1]}; pull-back = last {LATE_MIN} min; "
                                 f"trend {TREND_N} sessions; time value <= {TV_MAX_SHARE * 100:.0f}%",
                   "direction checks": "v4 playbook (the rule) | v3 5-day trend | none",
                   "strike ladder": ", ".join(rung_label(v) for v in values_of(settings, "moneyness")),
                   "first exit candles": ", ".join(values_of(settings, "first_exit")),
                   "time-value checks (earlier rule)": f"<= {TV_MAX_SHARE * 100:.0f}% of premium | "
                                        f"<= {TV_MAX_POINTS:.0f} points | cheapest {TV_RANK_KEEP} in 100 "
                                        f"over {TV_RANK_LOOKBACK} nights | none (the rule)",
                   "strike step": f"{STEP:.0f}", "entry": ENTRY_MIN, "time exit": TIME_EXIT, "lots": LOTS,
                   "expiry": "nearest >= 1 day after exit day"},
        "rule_steps": [
            "Take the session's 09:15 open and the 15:14 close (1-minute bars); a missing one means no trade.",
            "Close above open: buy a call. Close below: buy a put. Equal: no trade.",
            "Trade tonight only if ANY playbook scenario fires; otherwise no trade:",
            f"  A - the {TREND_N}-day trend agrees with the day, and today's range is normal "
            f"({RANGE_BAND[0]}-{RANGE_BAND[1]} x the {RANGE_N}-day average).",
            f"  B - the 15:14 close is in the day's strongest {100 - STRONG_CLOSE * 100:.0f}% (near the high on an up "
            "day, the low on a down day), and the range is normal.",
            f"  C - a small day (15:14 close within {SMALL_MOVE}% of the open), and the range is normal.",
            f"  D - a small day, and the last {LATE_MIN} minutes (14:59 to 15:14) pulled back against the day.",
            f"  E - the last {LATE_MIN} minutes pulled back, and time value is at most "
            f"{TV_MAX_SHARE * 100:.0f}% of the option's 15:19 price.",
            f"  F - a small day whose close sits in the middle of the day's range ({MIDDLE_CLOSE[0]}-"
            f"{MIDDLE_CLOSE[1]} in its direction).",
            "Reference = index at 15:19 (close), strike = 6 strikes in the money (300 points) for the rule, "
            "nearest expiry at least a day after the exit day.",
            "Buy in the 15:20 minute at that minute's HIGH (worst fill); line = paid + round-trip costs per unit.",
            "Next session, from the 09:30 candle: if a candle's low is above the line, sell in the next minute "
            "at its LOW (worst fill). (The panel's first-exit candle moves 09:30.)",
            "Nothing qualifying by then: sell in the 15:14 minute at its LOW.",
            "No stop, no target.",
            "The earlier rule's time-value check (skip the night when time value is above 15% of the premium) "
            "is in the panel, off by default.",
        ],
        "limits": limits,
        "rejected": [
            ["Choosing the OPPOSITE side to the day", "tested in the scratchpad study (2022-2026, 74 rules): no signal "
             "reliably picked the other side; the edge is in which nights to trade, not in flipping the direction."],
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
              {"name": "Which scenarios fired", "keys": [SCEN_TAG]},
              *[{"name": f"Scenario {SCEN_LABEL[k]}", "keys": [SCEN_LABEL[k]]} for k in "ABCDEF"],
              {"name": f"{TREND_N}-day trend", "keys": [TREND_TAG]},
              {"name": "Direction x playbook", "keys": ["direction", PLAYBOOK_TAG]},
              {"name": "Time value share at 15:19", "keys": ["time value"]},
              {"name": "Do the three time-value checks agree?", "keys": ["tv vs share", "tv vs points", "tv vs recent"]},
              {"name": "Cheap or dear against recent nights", "keys": ["tv vs recent"]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups,
                            settings=settings, chart="default", sessions_log=log, worst_only=True)
    path = write_report(payload, SLUG)
    print(console_summary(trades))
    print(path)


if __name__ == "__main__":
    main()
