"""Over night Hold v5 - the final rule (the user, 2026-10-03).

The user's requests, in order:
  "make this a detailed report as v5, only the rules like onh_v4_rule.html, but I have to choose the moneyness; add
   entries 1 to 7, the watchlist and the three confirmations"
  "I need all the entries ... check ALL at a time, then see the confirmation, then the entry; fit the best thing now"
  "remove entry 10, it is not worth it - 10C is the most dangerous - and make entry 11 entry 10"
  "why did you add the 9th entry separately? I need the best rule only in v5 - when I add the 9th the trade count and the
   win rate also increase.  In v5 make only the final version of this strategy; in the rules explain each entry in detail
   and break down in simple English how to calculate it; add the exit tab at 09:16 as per the rule"

THE v5 RULE - one rule, ten entries
  Step 1  At 15:14: 15:14 close above the 09:15 open = UP day, below = DOWN day, equal = no trade.
  Step 2  Check ALL the entries at the same time.
            Day-side entries (they say: buy the day's side)       1-7 and 10   (never on a holiday night)
            Opposite-side entries (they say: buy the other side)  8            (never on a holiday night)
                                                                  9            (also on a holiday night)
  Step 3  Count the confirmations, 0 to 3:
            a  US futures are WITH the day (S&P 500 futures at 14:30 against 21:00 UTC the evening before)
            b  option writers SUPPORT the day (09:30 -> 15:19, the at-the-money option of the OTHER side added at least
               as much open interest as the day's side)
            c  crude oil is AGAINST the day (crude futures at 14:30 against 21:00 UTC the evening before)
          A reading that is missing is not a confirmation.
  Step 4  Decide, in this order.
            A day-side entry is true AND at least 1 confirmation   -> buy the DAY's side (CE on UP, PE on DOWN).
            A day-side entry is true but no confirmation            -> no trade.
            No day-side entry; entry 8 is true                      -> buy the OPPOSITE side (PE on UP, CE on DOWN).
            No day-side entry, no entry 8; entry 9 is true AND at most 2 confirmations -> buy the OPPOSITE side.
            Nothing true                                            -> no trade.
  Step 5  Strike = the chosen depth in the money from the 15:19 index close (the rule: 6 ITM); expiry = nearest at least
          one day after the exit day; buy 1 lot in the 15:20 minute at its HIGH; sell-line = paid + costs.  THE EXIT
          (the user, 2026-10-04): two exits in the 'Exit' box, onh_v4.py's sell_by_rule - from 09:20 the first candle
          whose LOW is above the sell-line sells in the next minute, else the 14:00 minute (SELECTED: V4 RULE_EXIT); or
          in profit at 09:20 -> sell at 09:20, else at 14:00.  No stop, no target.  WORST FILL ONLY.
          A strike that did not trade in the 15:20 minute: one strike nearer the money, bought in the next minute at its
          HIGH (NEARER_STRIKE) - the user, 2026-10-03, on the SENSEX nights the report showed as bad data.

HOW IT WAS FITTED (scratchpad final_fit*.py, Jan-Jul 2026, both indices, 6 ITM): every state of (a day-side entry true?,
an opposite-side entry true?, confirmations 0-3) was tabulated.  With a day-side entry true the day's side beat the
opposite side in every state with one or more confirmations; with none it was clearly weaker (this script counts a
missing reading as not confirmed; those nights made NIFTY 5 trades +26k, SENSEX 7 trades -4k at 6 ITM under the old
exit).  With no day-side entry true, entry 8 paid on the opposite side whatever the confirmations; entry 9 paid there
except with all three confirmations agreeing with the day.  All of this is in-sample.
The report's rule section (the user, 2026-10-04: "remove ... unwanted things, it makes it noisy"): the rule in short,
the steps, the exit on real nights, the decision table, the ten entries, the confirmations, what is and is not proven.

THE ENTRIES are onh_v4.py's own definitions - this script loads that file and uses its functions:
   1 trend agrees + normal range      2 strong close + normal range     3 small day + normal range
   4 small day + late pull-back       5 late pull-back + time value <= 15%
   6 small day + middle close         7 Asia against the day + strong close
   8 India VIX >= 17, range NOT normal, day moved 0.3%+, most of Asia WITH the day            -> opposite side
   9 balance (value overlaps yesterday's, or the close is inside the 5-session value area)    -> opposite side
  10 day moved 0.3%+, Asia against the day, crude oil against the day                          -> the day's side
(Entry 10 was first a pair of opposite-side models, 10A and 10C; the user removed them and the crude entry, first
numbered 11, took the number.)

The report holds ONLY the final rule's trades: every strike depth and the two exits of the 'Exit' box.  'Which entries' shows
the rule's own trades entry by entry; it is not a choice between rules.

It does not touch onh_v5.py (a different v5 candidate written on 2026-10-02) or onh_v4.py's rule (entries 1-7).
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *          # noqa: F401,F403
import argparse
import asyncio
import bisect
import json
import runpy
from datetime import date, datetime, timedelta, timezone

CATEGORY = "index_options"
SLUG = "onh_v5_rule"
# onh_v4.py as a library: its entry definitions, strike and exit.  Loaded afresh for each index, so its
# index-dependent constants (the strike step) are this index's.
V4 = runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "onh_v4.py"), run_name="__onh_v4_lib__")
(ENTRY_MIN, READ_MIN, SIGNAL_MIN, TIME_EXIT, FIRST_EXIT, LOTS) = (
    V4[k] for k in ("ENTRY_MIN", "READ_MIN", "SIGNAL_MIN", "TIME_EXIT", "RULE_EXIT", "LOTS"))
EXIT_LABEL, EXIT_START, EXIT_END = V4["EXIT_LABEL"], V4["EXIT_START"], V4["EXIT_END"]
(TV_MAX_SHARE, STRONG_CLOSE, MIDDLE_CLOSE, SMALL_MOVE, RANGE_BAND, RANGE_N, TREND_N, LATE_MIN, REVERSE_IVIX,
 ASIA_MIN_OPEN) = (V4[k] for k in ("TV_MAX_SHARE", "STRONG_CLOSE", "MIDDLE_CLOSE", "SMALL_MOVE", "RANGE_BAND", "RANGE_N",
                                   "TREND_N", "LATE_MIN", "REVERSE_IVIX", "ASIA_MIN_OPEN"))
LADDER = V4["LADDER"]
RULE_DEPTH = 6
# THE STRIKE PLAN (the user, 2026-10-05; sleeve exit chosen the same day).  'stable' - the v5 rule, the SELECTED
# plan: the chosen depth every night.  'best': only a DAY-SIDE weekend hold changes - 2 strikes out of the money with
# the same rupees, and that leg books profit at 09:20 (else 14:00).  Opposite-side (entry 8/9) weekends stay at the
# chosen depth: the opposite side PAYS the weekend premium instead of collecting it (the 19 Jun 2026 drawdown trade
# was exactly such a night).  Original note:
# 'best': a weeknight is bought exactly as 'stable', but a WEEKEND HOLD (exit day 3+ calendar days away) is bought
# 2 strikes OUT of the money.  Why: weekend overnight gaps are 2-4x weeknight gaps (a 2022-2025 fact, see the
# shut-time study), and a cheap strike is convex - on the real Jan-Jul 2026 trades the same weekend nights earned
# ~+50% per rupee of premium at 2 OTM vs ~+33% at 6 ITM, at about the same win rate (85% vs 88%).  The per-rupee
# numbers are 2026-only; a losing 2 OTM night burns nearly the whole premium where 6 ITM usually keeps about half.
BEST_WEEKEND_RUNG = -2
PLAN_STABLE, PLAN_BEST = "stable", "best"
PLAN_LABEL = {PLAN_STABLE: "stable: the chosen strike depth every night (the v5 rule)",
              PLAN_BEST: "best: a DAY-SIDE weekend hold 2 strikes OUT of the money (same rupees), profit booked "
                         "at 09:20; everything else as stable"}
# THE EXIT is onh_v4.py's: FIRST_EXIT = its RULE_EXIT (the selected one), FIRST_EXITS = both exits of the 'Exit' box
FIRST_EXITS = [FIRST_EXIT] + [k for k in (V4["EXIT_LINE"], V4["EXIT_TWO"]) if k != FIRST_EXIT]
ROWS_PER_SESSION = 375
ES_FILE = os.path.join(LOCAL_DATA_DIR, "yahoo_ES_F_hourly.json")
CRUDE_FILE = V4["CRUDE_FILE"]
HOURLY_STALE = 4 * 3600
DAY_NEEDS = 1                # a day-side trade needs at least this many confirmations
NINE_MAX = 2                 # entry 9 trades only with at most this many confirmations (not when all three back the day)
# A thin strike (a deep SENSEX strike on a few nights) that did not trade in the 15:20 minute cannot be bought.  Then the
# rule moves ONE strike of the ladder nearer the money and buys it in the NEXT minute (15:21) at that minute's HIGH; if
# that one did not trade either, one more strike nearer in the minute after, as far as the at-the-money strike.  Each
# step uses only what is known when it is taken (the minute before has finished), so nothing is filled from a later
# price of the SAME contract and the fill is still the worst one.  False = the earlier behaviour: no trade that night.
NEARER_STRIKE = True
STRIKE_TAG = "strike bought"
AT_RULE_STRIKE = "the chosen strike"
DAY_ENTRIES = ("1", "2", "3", "4", "5", "6", "7", "10")
ALL_ENTRIES = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10")
CONF_TAG, HOLIDAY_TAG, KIND_TAG, WHY_TAG = "confirmations", "holiday night", "what is bought", "decided by"
K_DAY, K_OPP = "the day's side", "the opposite side"
KIND = {"day": K_DAY, "opp": K_OPP}
WHY_DAY, WHY_8, WHY_9 = "a day-side entry (1-7, 10) + a confirmation", "entry 8", "entry 9"
ES_TAG, OI_TAG, CRUDE_TAG = "US futures", "option writers", "crude oil"
CONF = lambda n: f"{n} of 3"
entry_flag = lambda n: f"entry {n} true"
# the rule's trades at the rule's strike and selected exit, with each one's exit told in words - 'The exit on real nights'
EX: list[dict] = []

SETTINGS = [
    setting("entries", "Which entries", kind="entry", mode="filter", default="all",
            help="one rule - all ten entries. The other choices show the rule's own trades entry by entry.",
            options=[{"value": "all", "label": "THE v5 RULE: all entries, 1 to 10", "tag": None}]
                    + [{"value": f"e{n}", "tag": {entry_flag(n): ["yes"], KIND_TAG: [K_DAY]} if n in DAY_ENTRIES
                        else {WHY_TAG: [WHY_8 if n == "8" else WHY_9]},
                        "label": f"only the rule's trades where entry {n} is true (the day's side)" if n in DAY_ENTRIES
                        else f"only the rule's trades from entry {n} (the opposite side)"} for n in ALL_ENTRIES]),
    setting("first_exit", "Exit", kind="exit", default=FIRST_EXIT,
            options=[{"value": k, "label": EXIT_LABEL[k], "raw": k} for k in FIRST_EXITS],
            help="how the option is sold the next session; 'paid + costs' is the sell-line"),
    setting("moneyness", "Strike depth", kind="strike", default=RULE_DEPTH, rerun=True,
            options=[{"value": v, "label": V4["rung_label"](v), "raw": v} for v in LADDER],
            help="every strike is priced on the same nights; the rule is 6 strikes in the money"),
]


def values_of(settings: list[dict], key: str) -> list:
    return [o["raw"] for o in next(s for s in settings if s["key"] == key)["options"]]


def prev_minute(hhmm: str) -> str:
    m = hhmm_minutes(hhmm) - 1
    return f"{m // 60:02d}:{m % 60:02d}"


def hourly_reads(path: str, days: list[str]) -> dict[str, float]:
    """{day: % move from 21:00 UTC the evening before to 14:30 IST today} from one-hour bars, FINISHED bars only: the
    bar that starts at 08:00 UTC ends at 09:00 UTC = 14:30 IST, before the 15:14 decision.  A stale bar is no read."""
    import py_funcs as _pf                        # the joining loader: with PYFUNCS_TEST_DATA=1 the
    blob = _pf._local(os.path.basename(path))     # test_data copy's rows are joined on (holdout run, 2026-10-05)
    if not blob or not blob.get("rows"):
        print(f"  ! hourly bars not on local disk ({path}) - no read on any night")
        return {}
    rows = blob["rows"]
    starts = [r[0] for r in rows]

    def last_done(ts):
        i = bisect.bisect_right(starts, ts - 3600) - 1
        return rows[i][4] if i >= 0 and ts - starts[i] <= HOURLY_STALE else None
    out = {}
    for d in days:
        y, m, dd = (int(x) for x in d.split("-"))
        px = last_done(datetime(y, m, dd, 9, 0, tzinfo=timezone.utc).timestamp())
        ref = next((q for q in (last_done((datetime(y, m, dd, 21, 0, tzinfo=timezone.utc) - timedelta(days=b)).timestamp())
                                for b in range(1, 6)) if q is not None), None)
        if px is not None and ref:
            out[d] = (px / ref - 1) * 100
    return out


def last_at(by: dict, hhmm: str):
    ks = [k for k in by if k <= hhmm]
    return by[max(ks)] if ks else None


# A SESSION IS USED (the owner, 2026-10-11, "still the bad data exist"): when every minute the rule READS is there -
# the 09:15 open, the 14:59 close of the late pull-back, the 15:14 signal close and the 15:19 price - and at most
# MAX_MISSING other minutes of 09:15-15:19 are absent.  Three 2025 sessions lack one minute at the source (Upstox) in
# NIFTY, SENSEX and India VIX at once (25 Mar 10:42, 4 Apr 11:57, 23 Apr 10:36; re-fetched, still absent).  Nothing
# is filled in: the day's high, low and value area are read from the minutes that exist.  A session of fewer than
# SPECIAL_SESSION_MAX minutes is a special short session (the one-hour Muhurat), not a trading night at all.
MAX_MISSING = 1
SPECIAL_SESSION_MAX = 120


def complete_session(rows: list[list]) -> bool:
    have = {x[0] for x in rows}
    must = {"09:15", V4["prev_n_minutes"](SIGNAL_MIN, LATE_MIN), SIGNAL_MIN, READ_MIN}
    return must <= have and len(V4["ENTRY_MINUTES"] - have) <= MAX_MISSING


def pick(dayside: bool, e8: bool, e9: bool, conf: int) -> tuple:
    """THE v5 RULE: (what is bought: 'day' | 'opp' | None, why).  All entries are looked at together, then the
    confirmations.  `dayside` (any of entries 1-7, 10) and `e8` are already false on a holiday night."""
    if dayside:
        if conf >= DAY_NEEDS:
            return "day", WHY_DAY
        return None, "a day-side entry is true but no confirmation agrees"
    if e8:
        return "opp", WHY_8
    if e9:
        if conf <= NINE_MAX:
            return "opp", WHY_9
        return None, "entry 9 is true but all three confirmations agree with the day"
    return None, "no entry is true"


# ---------------------------------------------------------------------------
# fetch + run
# ---------------------------------------------------------------------------
async def run(frm: date, to: date, settings: list[dict]):
    now = datetime.now(IST)
    skips, log, trades = [], [], []
    option_sessions: dict[str, dict[str, list[list]]] = {}
    rungs = values_of(settings, "moneyness")
    firsts = values_of(settings, "first_exit")
    plans = [PLAN_STABLE]      # the 'best' weekend 2-OTM plan was REMOVED by the owner on 2026-10-06: on the test
    #                            period it did worse than 'stable' (its weekend-premium premise did not show up there)
    rule = default_combo(settings)
    chart_rung, chart_first, chart_plan = rule["moneyness"], rule["first_exit"], PLAN_STABLE
    STEP = V4["STEP"]
    async with Upstox() as up:
        und = await up.find_instrument(instrument())
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        if info["strike_step"] != STEP:
            raise SystemExit(f"Upstox strike step is {info['strike_step']}, the script read {STEP}.")
        back = timedelta(days=V4["TREND_LOOKBACK_DAYS"])
        fetch_to = min(to + timedelta(days=7), now.date())
        sessions = sessions_from(await up.candles(key, "1m", frm - back, fetch_to))
        cal = await up.expiry_calendar(key, frm, to)
        asia = await V4["asia_reads"](frm - back, fetch_to)
        ivix: dict[str, float] = {}
        try:
            vix_key = (await up.find_instrument(V4["IVIX_NAME"]))["instrument_key"]
            for day, vrows in (await up.minute_sessions(vix_key, frm - back, fetch_to)).items():
                vbar = bar_at(vrows, READ_MIN, tolerance=0)
                if vbar is not None:
                    ivix[day] = vbar[4]
        except LookupError as exc:
            print(f"  ! India VIX: {exc}")
        us_bars = await yahoo_daily(V4["US_TICKER"], frm - back, fetch_to) or []
        us_days = {b[0] for b in us_bars}
        us_span = (us_bars[0][0], us_bars[-1][0]) if us_bars else None
        full = {d: r for d, r in sessions.items()
                if complete_session(r) and not (d == now.date().isoformat() and now.strftime("%H:%M") < "15:45")}
        days = sorted(full)
        es, crude = hourly_reads(ES_FILE, days), hourly_reads(CRUDE_FILE, days)
        print(f"hourly reads: US futures {len(es)} sessions, crude oil {len(crude)} sessions; India VIX {len(ivix)}")
        for name in INDEX_INSTRUMENTS:
            if name != REFERENCE_INSTRUMENT and name not in V4["PRE_RATIOS"]:
                try:
                    V4["PRE_RATIOS"][name] = await V4["pre_window_ratio"](up, name, frm)
                except (LookupError, SystemExit) as exc:
                    if name == instrument():
                        raise
                    print(f"  ! {name}: no close ratio before {frm} ({exc})")
        for d, r in sessions.items():
            if d not in full and frm.isoformat() <= d <= to.isoformat():
                if len(r) < SPECIAL_SESSION_MAX:          # e.g. the one-hour Muhurat session: not a normal trading day
                    skips.append(f"{d}: special short session ({r[0][0]}-{r[-1][0]}) - not a trading night")
                    log.append(session_row(d, "no signal", f"a special short session ({r[0][0]}-{r[-1][0]}, e.g. the "
                                                           "Muhurat hour) - not a normal trading day"))
                    continue
                gap = sorted(V4["ENTRY_MINUTES"] - {x[0] for x in r})
                skips.append(f"{d}: session incomplete ({len(gap)} minutes missing) - not used")
                log.append(session_row(d, "no data", f"session incomplete: {len(gap)} minutes missing between 09:15 "
                                                     f"and 15:19 ({', '.join(gap[:4])}{' ...' if len(gap) > 4 else ''})"))
        traded = [d for d in days if frm.isoformat() <= d <= to.isoformat()]
        print(f"index sessions on disk: {len(sessions)}, complete: {len(full)}, in window: {len(traded)}")

        async def next_trade(c, after: str):
            """(day, rows) of the first session after `after`, up to the contract's expiry, in which it traded."""
            for nd in days:
                if after < nd <= c["expiry"]:
                    nrows = await up.option_candles(c, date.fromisoformat(nd))
                    if nrows:
                        return nd, nrows
            return None, None
        for d in traded:
            rows = full[d]
            side_opt, why, o915, c1514 = V4["signal"](rows)
            if side_opt is None:
                skips.append(f"{d}: no trade - {why}")
                log.append(session_row(d, "no signal", why))
                continue
            up_day = side_opt == "CE"
            sgn = 1 if up_day else -1
            other = "PE" if up_day else "CE"
            checks = V4["direction_checks"](full, days, d, side_opt, c1514)
            asia_r = V4["asia_check"](asia, d, side_opt)
            iv = ivix.get(d)
            us_closed = us_span is not None and us_span[0] <= d <= us_span[1] and d not in us_days
            holiday = asia_r["open"] < ASIA_MIN_OPEN or us_closed
            holiday_why = " + ".join(x for x in ("Asia thin" if asia_r["open"] < ASIA_MIN_OPEN else "",
                                                 "US shut tonight" if us_closed else "") if x)
            bal = V4["balance_read"](full, days, d, c1514)
            later = [x for x in days if x > d]
            if not later:                                 # the data ends here: nothing is missing, there is no next day yet
                skips.append(f"{d}: the last session in the data - no next session to sell in")
                log.append(session_row(d, "no signal", "the last session in this data: there is no next session to sell "
                                                       "in (a later run will trade it)"))
                continue
            if (date.fromisoformat(later[0]) - date.fromisoformat(d)).days > 5:
                skips.append(f"{d}: no next complete session within 5 days")
                log.append(session_row(d, "no data", "no next complete session, so no exit day"))
                continue
            exit_day = later[0]
            by = {r[0]: r for r in rows}
            spot = by[READ_MIN][4]
            expiry = next_expiry(cal, date.fromisoformat(exit_day), 1)
            if expiry is None:
                skips.append(f"{d}: no expiry at least 1 day after exit day {exit_day}")
                log.append(session_row(d, "no data", f"no expiry at least a day after {exit_day}"))
                continue
            # ---- the entries that do not depend on the strike ----
            asia_against, asia_with = asia_r["tag"] == V4["ASIA_AGAINST"], asia_r["tag"] == V4["ASIA_WITH"]
            cr, us = crude.get(d), es.get(d)
            e7 = asia_against and checks["close location"] >= STRONG_CLOSE
            e8 = (iv is not None and iv >= REVERSE_IVIX and checks["range ratio"] is not None and not checks["normal"]
                  and not checks["small"] and asia_with and not holiday)                  # never on a holiday night
            e9 = bool(bal["ok"])
            e10 = cr is not None and cr * sgn < 0 and not checks["small"] and asia_against and not holiday
            # ---- the three confirmations (for the day's side); a missing reading is not a confirmation ----
            atm = atm_strike(spot, STEP)
            oi_diff = ch = None
            c_ce, c_pe = [await up.resolve_option(key, expiry, atm, t) for t in ("CE", "PE")]
            if c_ce and c_pe:
                o_ce, o_pe = option_open_interest(c_ce, date.fromisoformat(d)), option_open_interest(c_pe, date.fromisoformat(d))
                ends = [max((k for k in o if k <= READ_MIN), default="") for o in (o_ce, o_pe)]
                if all(e_ >= "15:10" for e_ in ends) and last_at(o_ce, "09:30") is not None and last_at(o_pe, "09:30") is not None:
                    ch = {"CE": last_at(o_ce, READ_MIN) - last_at(o_ce, "09:30"), "PE": last_at(o_pe, READ_MIN) - last_at(o_pe, "09:30")}
                    oi_diff = ch[side_opt] - ch[other]            # the day's side minus the other side
            w = {ES_TAG: None if us is None else us * sgn > 0, OI_TAG: None if oi_diff is None else oi_diff <= 0,
                 CRUDE_TAG: None if cr is None else cr * sgn < 0}
            conf = sum(1 for v in w.values() if v)
            words = lambda v, yes, no: "no reading" if v is None else yes if v else no
            w_tags = {ES_TAG: words(w[ES_TAG], "with the day", "against the day"),
                      OI_TAG: words(w[OI_TAG], "support the day", "do not support"),
                      CRUDE_TAG: words(w[CRUDE_TAG], "against the day (supports it)", "with the day")}
            direction = "up day" if up_day else "down day"
            base = {"direction": f"{direction}: day's side {side_opt}", "day move %": (c1514 - o915) / o915 * 100,
                    HOLIDAY_TAG: holiday_why if holiday else "no", "India VIX": iv,
                    "Asia today": asia_r["tag"],
                    ES_TAG: w_tags[ES_TAG], OI_TAG: w_tags[OI_TAG], CRUDE_TAG: w_tags[CRUDE_TAG], CONF_TAG: CONF(conf)}
            seen = None
            for steps in rungs:
                tag = f"{d} [{steps} ITM]"
                # the day-side option's 15:19 price: entry 5 reads its time value
                k_day = V4["strike_at"](spot, steps, side_opt)
                c_day = await up.resolve_option(key, expiry, k_day, side_opt)
                orows_day = await up.option_candles(c_day, date.fromisoformat(d)) if c_day else []
                ob = {r[0]: r for r in orows_day}
                prem = ob[READ_MIN][4] if READ_MIN in ob and ob[READ_MIN][4] > 0 else None
                intrinsic = (spot - k_day) if up_day else (k_day - spot)
                share = (prem - intrinsic) / prem if prem else None
                scen = dict(checks["scen"], E=bool(checks["late pull-back"]) and share is not None and share <= TV_MAX_SHARE)
                # a day-side entry is never true on a holiday night
                ent = {n: bool(v) and not holiday for n, v in (("1", scen["A"]), ("2", scen["B"]), ("3", scen["C"]), ("4", scen["D"]),
                                                               ("5", scen["E"]), ("6", scen["F"]), ("7", e7), ("10", e10))}
                true_day = [n for n in DAY_ENTRIES if ent[n]]
                dayside = bool(true_day)
                opp_now = [n for n, v in (("8", e8), ("9", e9)) if v]
                rk, rwhy = pick(dayside, e8, e9, conf)
                flags = {entry_flag(n): "yes" if (ent[n] if n in ent else (e8 if n == "8" else e9)) else "no" for n in ALL_ENTRIES}
                built, built_how, built_no_fill = None, "", False
                wkhold = (date.fromisoformat(exit_day) - date.fromisoformat(d)).days >= 3    # a weekend / long-weekend hold
                for kind in ([rk] if rk else []):
                  typ = side_opt if kind == "day" else other
                  stable_paid = None                     # the stable strike's 15:20 worst price, set on the stable pass
                  for plan in plans:
                    # 'best' changes ONLY a day-side weekend hold: 2 OTM, same rupees, profit booked at 09:20
                    steps_p = BEST_WEEKEND_RUNG if plan == PLAN_BEST and wkhold and kind == "day" else steps
                    strike = V4["strike_at"](spot, steps_p, typ)
                    c = c_day if kind == "day" and steps_p == steps else await up.resolve_option(key, expiry, strike, typ)
                    orows = (orows_day if kind == "day" and steps_p == steps
                             else (await up.option_candles(c, date.fromisoformat(d)) if c else []))
                    entry_bar = bar_after_candle(orows, READ_MIN, 1) if c and LOTS * c["lot_size"] > 0 else None
                    nearer, c0, strike0 = 0, c, strike
                    while NEARER_STRIKE and entry_bar is None and nearer < abs(steps_p):
                        nearer += 1                 # one strike nearer the money, tried in the next minute
                        strike = V4["strike_at"](spot, steps_p - nearer if steps_p > 0 else steps_p + nearer, typ)
                        c = await up.resolve_option(key, expiry, strike, typ)
                        orows = await up.option_candles(c, date.fromisoformat(d)) if c else []
                        entry_bar = bar_after_candle(orows, READ_MIN, 1 + nearer) if c and LOTS * c["lot_size"] > 0 else None
                    if entry_bar is None:           # nothing traded all the way to the money: say it about the chosen strike
                        c, strike, nearer = c0, strike0, 0
                    bought_at = AT_RULE_STRIKE if not nearer else f"{nearer} strike{'s' if nearer > 1 else ''} nearer the money"
                    xrows = await up.option_candles(c, date.fromisoformat(exit_day)) if entry_bar else []
                    problem = (f"the contract {expiry} {strike:.0f} {typ} does not exist" if c is None else
                               f"the option {c['trading_symbol']} did not trade in the 15:20 minute"
                               + (", and no strike nearer the money traded in the minutes after" if NEARER_STRIKE and steps_p else "")
                               + ": nothing to buy at" if entry_bar is None else None)
                    no_fill = c is not None and entry_bar is None      # the market did not trade it: not missing data
                    # 'best' on a weekend: the SAME RUPEES as the stable strike, not the same lots - the cheaper
                    # strike earns more per rupee, less per lot, so the premium is matched (1 to 6 lots, rounded)
                    mult = 1
                    if plan == PLAN_BEST and steps_p != steps and not problem:
                        if stable_paid and entry_bar[2] > 0:
                            mult = min(6, max(1, round(stable_paid / entry_bar[2])))
                        else:
                            problem = "the stable strike did not trade at 15:20, so there is no premium to match"
                    if plan == PLAN_STABLE and not problem:
                        stable_paid = entry_bar[2]
                    qty = mult * LOTS * c["lot_size"] if not problem else 0
                    line = V4["breakeven_line"](entry_bar[2], qty, d, exit_day) if not problem else None
                    for first in firsts:
                        # the OTM weekend leg books profit at 09:20 (else 14:00), whatever the Exit box says: an
                        # out-of-the-money option is richest at the open - the gap has arrived, the decay has not
                        first_used = V4["EXIT_TWO"] if steps_p != steps else first
                        ex = V4["sell_by_rule"](xrows, line, first_used) if not problem else None
                        sale_day, srows = exit_day, xrows
                        if ex is not None and ex["bar"] is None:
                            # NO SALE POSSIBLE ON THE EXIT DAY (the owner, 2026-10-11): the option did not trade when
                            # the exit needs it (or at all that day).  As the exit rule already does within a day, it is
                            # sold in the first minute it trades after that - on the next session(s), up to expiry, at
                            # that minute's LOW.  Only if it never trades again before expiry is the night left out.
                            nd, nrows = await next_trade(c, exit_day)
                            if nd:
                                sale_day, srows = nd, nrows
                                ex = {"bar": nrows[0], "trigger": None,
                                      "reason": f"no trade when needed on the exit day ({exit_day}) - sold in the first "
                                                f"traded minute of {nd}"}
                            else:
                                problem = (f"{ex['reason']} ({c['trading_symbol']}, {exit_day}), and it did not trade "
                                           "again before expiry")
                        if problem:
                            if plan == PLAN_STABLE or steps_p != steps:        # a weeknight 'best' trade is the same contract
                                skips.append(f"{tag}: {problem}")
                            if plan == PLAN_STABLE:
                                built, built_no_fill = problem, no_fill
                            break
                        exit_bar = ex["bar"]
                        entry_px, exit_px = worst_fills("LONG", entry_bar, exit_bar)
                        if entry_px != entry_bar[2] or exit_px != exit_bar[3]:
                            raise SystemExit(f"{tag}: fill is not the worst price")
                        xspot = bar_at(full[sale_day], prev_minute(exit_bar[0]), tolerance=3, direction=-1)
                        dated = ([[f"{d} {r[0]}"] + r[1:] for r in orows] + [[f"{exit_day} {r[0]}"] + r[1:] for r in xrows]
                                 + ([[f"{sale_day} {r[0]}"] + r[1:] for r in srows] if sale_day != exit_day else []))
                        mfe, mae = excursion(dated, "LONG", entry_px, f"{d} {entry_bar[0]}", f"{sale_day} {exit_bar[0]}")
                        t = make_trade(
                            day=d, exit_day=sale_day, side="LONG", symbol=c["trading_symbol"],
                            entry_time=entry_bar[0], entry_px=entry_px, exit_time=exit_bar[0], exit_px=exit_px,
                            qty=qty, exit_reason=ex["reason"], capital=entry_px * qty,
                            entry_spot=spot, exit_spot=xspot[4] if xspot else None,
                            target=round(line, 2), mfe=mfe, mae=mae, expiry=c["expiry"], option_type=typ,
                            variant={"moneyness": steps, "first_exit": first, "strike_plan": plan},
                            tags={"direction": f"{direction}: buy {typ}", KIND_TAG: KIND[kind], WHY_TAG: rwhy,
                                  CONF_TAG: CONF(conf), **w_tags, HOLIDAY_TAG: "yes" if holiday else "no",
                                  STRIKE_TAG: bought_at, "night": "weekend hold" if wkhold else "weeknight",
                                  **({"lots bought": f"{mult} (premium matched to the stable strike)"} if mult > 1 else {}),
                                  **flags},
                            levels=[{"name": "09:15 open", "price": o915}, {"name": "15:14 close", "price": c1514},
                                    {"name": "strike", "price": strike}],
                            note=f"the v5 rule: {rwhy}; {V4['rung_label'](steps)}"
                                 + (f"; the 'best' strike plan: a day-side weekend hold, so {mult} lot{'s' if mult > 1 else ''} of "
                                    f"{V4['rung_label'](steps_p)} bought for about the stable strike's premium, profit "
                                    "booked at 09:20 (else 14:00)"
                                    if steps_p != steps else "")
                                 + (f"; the chosen strike {strike0:.0f} did not trade in the 15:20 minute, so {bought_at} "
                                    f"was bought in the {entry_bar[0]} minute" if nearer else "")
                                 + f"; day-side entries true: {', '.join(true_day) or 'none'}; opposite-side entries true: {', '.join(opp_now) or 'none'}"
                                 + f"; confirmations {CONF(conf)}; sell-line (paid + costs) {line:.2f} drawn as 'target'"
                                 + f"; sold in the {exit_bar[0]} minute ({ex['reason']})")
                        trades.append(t)
                        if plan == PLAN_STABLE:
                            built = "traded"
                            built_how = (f", {bought_at} in the {entry_bar[0]} minute (the chosen strike {strike0:.0f} did not "
                                         "trade in the 15:20 minute)" if nearer else "")
                        if steps == chart_rung and first == chart_first and plan == chart_plan:
                            option_sessions.setdefault(c["trading_symbol"], {})[d] = orows
                            option_sessions[c["trading_symbol"]][exit_day] = xrows
                            if sale_day != exit_day:
                                option_sessions[c["trading_symbol"]][sale_day] = srows
                        if steps == RULE_DEPTH and first == FIRST_EXIT and plan == PLAN_STABLE and sale_day == exit_day:
                            EX.append({"day": d, "reason": ex["reason"], "net": t["net"], "trigger": ex["trigger"],
                                       "story": V4["exit_story"](c["trading_symbol"], entry_px, qty, line, d, exit_day,
                                                                 xrows, ex, t, first)})
                if steps == chart_rung:
                    facts = dict(base, **{"day-side entries true": ", ".join(true_day) or "none",
                                          "opposite-side entries true": ", ".join(opp_now) or "none"})
                    if rk and built == "traded":
                        seen = ("traded", f"{rwhy} - bought {KIND[rk]} ({side_opt if rk == 'day' else other}){built_how}", facts)
                    elif rk and built_no_fill:       # a real no-trade in the market, not missing data: nothing to buy
                        seen = ("declined", f"{rwhy}, but {built} - the market did not trade it, so there was nothing "
                                            "to buy; no trade", facts)
                    elif rk:
                        seen = ("no data", f"{rwhy}, but {built}", facts)
                    else:
                        seen = ("declined", rwhy + (f" (holiday night: {holiday_why})" if holiday else "") + " - no trade", facts)
            log.append(session_row(d, seen[0], seen[1], **seen[2]))
    return trades, skips, log, full, option_sessions, info


# ---------------------------------------------------------------------------
# the exit on real nights (per index)
# ---------------------------------------------------------------------------
def exit_nights() -> dict:
    """The selected exit worked through on real nights of this index, in plain English, one for each way it can end
    (the user, 2026-10-04: "for above paid, work with a real example in plain English")."""
    m = lambda t: int(t[:2]) * 60 + int(t[3:])                               # noqa: E731
    if FIRST_EXIT == V4["EXIT_LINE"]:
        cases = [("Sold as soon as the day's watch began", lambda x: x["reason"].startswith("low above") and x["trigger"][0] == EXIT_START),
                 ("Sold later, when the price came back above the sell-line", lambda x: x["reason"].startswith("low above") and m(x["trigger"][0]) >= m("09:45")),
                 (f"Never above the sell-line - sold at {EXIT_END}", lambda x: x["reason"].startswith(EXIT_END))]
    else:
        cases = [(f"In profit at {EXIT_START} - sold at {EXIT_START}", lambda x: x["reason"].startswith("in profit")),
                 (f"Not in profit at {EXIT_START} - held, sold at {EXIT_END} at a profit", lambda x: x["reason"].startswith(EXIT_END) and x["net"] > 0),
                 (f"Not in profit at {EXIT_START} - held, sold at {EXIT_END} at a loss", lambda x: x["reason"].startswith(EXIT_END) and x["net"] <= 0)]
    items = []
    for lab, f in cases:
        hit = next((x for x in EX if f(x)), None)
        if hit:
            items.append(f"{lab}.\n{hit['story']}")
    return {"title": "The exit on real nights", "items": items,
            "note": f"{instrument()}, {V4['rung_label'](RULE_DEPTH)}, the selected exit: {EXIT_LABEL[FIRST_EXIT]}. Each night's own "
                    "numbers: how its sell-line is worked out, what the candles did the next morning, where it was sold."}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat())
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    settings = narrow(SETTINGS, a)
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    check_window(frm, to)
    trades, skips, log, sessions, option_sessions, info = asyncio.run(run(frm, to, settings))
    V4["report_skips"](skips)
    lot = trades[-1]["qty"] // LOTS if trades else info["lot_size"]
    nstep, nn = V4["_depth"]("NIFTY")            # the depth in points, written without an index name the combined
    try:                                         # report would rename: '300 points (SENSEX: 1,000)'
        sstep, sn = V4["_depth"]("SENSEX")
        rnd, depth = f"the nearest {nstep:.0f} (SENSEX: {sstep:.0f})", f"{nn * nstep:,.0f} points (SENSEX: {sn * sstep:,.0f})"
    except Exception:
        rnd, depth = f"the nearest {nstep:.0f}", f"{nn * nstep:,.0f} points"
    tv_pct, lo_band, hi_band, vix = f"{TV_MAX_SHARE * 100:.0f}%", RANGE_BAND[0], RANGE_BAND[1], f"{REVERSE_IVIX:.0f}"
    lead = {
        "title": "The v5 rule in short",
        "lead": "At 15:14 find the day's direction, check all ten entries together and count the three confirmations. "
                f"If a day-side entry (1 to 7, or 10) is true and at least {DAY_NEEDS} confirmation agrees, buy the day's side: "
                "a CE on an UP day, a PE on a DOWN day. If no day-side entry is true, and entry 8 is true - or entry 9 is true "
                f"with at most {NINE_MAX} confirmations - buy the opposite side: a PE on an UP day, a CE on a DOWN day. Buy in the "
                f"15:20 minute. Exit: {EXIT_LABEL[FIRST_EXIT]} - the selected exit (the other one is in the 'Exit' box). "
                "'Paid + costs' is the sell-line: the price paid plus every cost of buying and selling, per unit."}
    steps = [
        "Wait for the 15:14 candle to finish. Compare the index's 15:14 close with its 09:15 open. Higher = an UP day. "
        "Lower = a DOWN day. Exactly the same = no trade today.",
        "Check whether it is a holiday night. On a normal night both of these markets are open; it is a holiday night "
        "when either one is shut:\n"
        f"- Asia: the 5 Asian markets (Nikkei 225, Hang Seng, KOSPI, Shanghai, ASX 200) trade during our day and close by "
        f"13:30 India time. If fewer than {ASIA_MIN_OPEN} of them traded today (a holiday in those countries), it is a holiday "
        "night.\n"
        "- US: on a normal night the US market trades WHILE we hold the option. The New York session runs from 19:00 to "
        "01:30 India time in the US summer (20:00 to 02:30 in the US winter), so it starts after our 15:20 buy and ends "
        "before our sale the next morning - it is the main thing that moves our index's opening. If the US market is "
        "closed on today's date (a US holiday), there is no US session in the night we hold, and it is a holiday night. "
        "In January-July 2026 that happened on 7 nights: 1 Jan (New Year), 19 Jan (Martin Luther King Day), 1 Feb (India's "
        "Sunday Budget session - a weekend in the US), 16 Feb (Presidents' Day), 25 May (Memorial Day), 19 Jun (Juneteenth) "
        "and 3 Jul (Independence Day). A normal Friday is NOT a holiday night: the US trades on Friday night.\n"
        "Both are known days in advance from the holiday calendars. On a holiday night entries 1 to 8 and 10 are not "
        "used; only entry 9 can trade.",
        "Work out today's facts from the candles that have finished by 15:14 (and three prices read at 15:19: the index, the "
        "option and India VIX). Each fact is explained, with a worked illustration, in the entry or confirmation below "
        "that uses it.",
        "Check ALL ten entries at the same time and note which are true. Each is explained in its own part below.\n"
        "DAY-SIDE entries (each says: buy the day's side):\n"
        "- Entry 1: the 5-day trend agrees, and the range is normal.\n"
        "- Entry 2: a strong close, and the range is normal.\n"
        "- Entry 3: a small day, and the range is normal.\n"
        "- Entry 4: a small day, and a late pull-back.\n"
        f"- Entry 5: a late pull-back, and time value of {tv_pct} or less.\n"
        "- Entry 6: a small day, and a middle close.\n"
        "- Entry 7: Asia against the day, and a strong close.\n"
        f"- Entry 10: the day moved {SMALL_MOVE}% or more, Asia against the day, and crude oil against the day.\n"
        "OPPOSITE-SIDE entries (each says: buy the other side):\n"
        f"- Entry 8: India VIX is {vix} or more, the range is NOT normal, the day moved {SMALL_MOVE}% or more, and Asia with "
        "the day.\n"
        "- Entry 9: the market is in balance - today's value area overlaps yesterday's, or the 15:14 close is inside the "
        "value area of the previous five sessions.",
        "Count the confirmations, 0 to 3. A reading you cannot get counts as not confirmed.\n"
        "- Confirmation 1: US futures are WITH our day (up on an UP day, down on a DOWN day).\n"
        "- Confirmation 2: option writers SUPPORT our day (the at-the-money option of the OTHER side added more open "
        "interest today than the option of our side).\n"
        "- Confirmation 3: crude oil is AGAINST our day (down on an UP day, up on a DOWN day).",
        "Decide - in this order:\n"
        f"- A day-side entry is true AND at least {DAY_NEEDS} confirmation agrees: buy the DAY's side - a CE on an UP day, a "
        "PE on a DOWN day. Two or more true entries are still one trade.\n"
        "- A day-side entry is true but NO confirmation agrees: no trade today.\n"
        "- No day-side entry is true, and entry 8 is true: buy the OPPOSITE side - a PE on an UP day, a CE on a DOWN day.\n"
        f"- No day-side entry and no entry 8, and entry 9 is true with at most {NINE_MAX} confirmations: buy the OPPOSITE "
        "side - a PE on an UP day, a CE on a DOWN day. (If all three confirmations agree with the day, entry 9 does not "
        "trade.)\n"
        "- Nothing is true: no trade today.",
        f"Choose the contract. Round the index's 15:19 close to {rnd}: that is the at-the-money strike. Go "
        f"{depth} in the money every night: below the at-the-money strike for a CE, above it for a PE. Use the "
        "nearest expiry that is at least one day after the next session. The 'Strike depth' setting prices every "
        "other depth on the same nights. (A 'best' plan that bought weekend holds 2 strikes out of the money was "
        "tried here and removed on 6 October 2026: on the unseen test period it did worse than this plain plan.)",
        "Buy one lot in the 15:20 minute. (The backtest assumes you paid the highest price of that minute.)\n"
        "If the option did not trade at all in the 15:20 minute - a deep strike can be that thin - do not wait for it: move "
        "one strike of the ladder nearer the money and buy that one in the 15:21 minute, again at that minute's highest "
        "price. If that one did not trade either, go one more strike nearer in the 15:22 minute, and so on as far as the "
        "at-the-money strike. If nothing traded all the way, there is no trade that night.",
        *V4["exit_steps"](),
    ]
    day_buy = "It says: buy the DAY's side - a CE on an UP day, a PE on a DOWN day. Never on a holiday night."
    entries = [
        {"title": "Entry 1 - the 5-day trend agrees AND the range is normal",
         "note": "It looks for a day that went the same way as the last five sessions, on an ordinary-sized range. " + day_buy,
         "items": [f"Trend: find the index's 15:14 close {TREND_N} trading sessions ago. On an UP day today's 15:14 close must be "
                   "HIGHER than it; on a DOWN day, LOWER.",
                   f"Range: today's high minus low (09:15 to 15:14), divided by the average high-minus-low of the previous {RANGE_N} "
                   f"sessions. The answer must be {lo_band} or more and under {hi_band}.",
                   "Both true = entry 1 is true.",
                   "Illustration (UP day): today's close 25,090, five sessions ago 24,900 - higher, the trend agrees. Today's range "
                   "190, usual range 200: 190 / 200 = 0.95 - normal. Entry 1 is true."]},
        {"title": "Entry 2 - a strong close AND the range is normal",
         "note": "It looks for a day that finished near its best point, on an ordinary-sized range. " + day_buy,
         "items": ["Close location: on an UP day (15:14 close - day's low) / (day's high - day's low); on a DOWN day (day's high - "
                   f"15:14 close) / (high - low). It must be {STRONG_CLOSE} or more.",
                   f"Range: today's range / the usual range must be {lo_band} or more and under {hi_band}.",
                   "Both true = entry 2 is true.",
                   "Illustration (UP day): low 24,950, high 25,150, close 25,120: 170 / 200 = 0.85 - a strong close. Range 200, "
                   "usual range 210: 0.95 - normal. Entry 2 is true."]},
        {"title": "Entry 3 - a small day AND the range is normal",
         "note": "It looks for a day that ended close to where it opened but still had an ordinary-sized range. " + day_buy,
         "items": [f"Small day: (15:14 close - 09:15 open) / 09:15 open x 100, ignoring the sign, must be under {SMALL_MOVE}%.",
                   f"Range: today's range / the usual range must be {lo_band} or more and under {hi_band}.",
                   "Both true = entry 3 is true.",
                   "Illustration: open 25,000, close 25,050: 50 / 25,000 x 100 = 0.20% - a small day. Range 180, usual range 200: "
                   "0.90 - normal. Entry 3 is true."]},
        {"title": "Entry 4 - a small day AND a late pull-back",
         "note": f"It looks for a small day that slipped back, or stood still, in the last {LATE_MIN} minutes. " + day_buy,
         "items": [f"Small day: the day's move must be under {SMALL_MOVE}%.",
                   "Late pull-back: compare the 15:14 close with the 14:59 close. On an UP day the 15:14 close must be the same or "
                   "LOWER; on a DOWN day the same or HIGHER.",
                   "Both true = entry 4 is true.",
                   "Illustration (UP day): open 25,000, close 25,050 = 0.20%, a small day. 14:59 close 25,062, 15:14 close 25,050 - "
                   "lower, a late pull-back. Entry 4 is true."]},
        {"title": f"Entry 5 - a late pull-back AND time value of {tv_pct} or less",
         "note": "It looks for a late pull-back on a night when the option is cheap - almost all of its price is real value. " + day_buy,
         "items": ["Late pull-back: on an UP day the 15:14 close is the same or lower than the 14:59 close; on a DOWN day the same "
                   "or higher.",
                   "Time value: take the option you would buy for the day's side and its 15:19 price. Worth right now = index's "
                   "15:19 close minus strike (CE), or strike minus index's 15:19 close (PE). Time value % = (price - worth right "
                   f"now) / price x 100. It must be {tv_pct} or less. If the option did not trade at 15:19, entry 5 is false.",
                   "Both true = entry 5 is true. Because the time value depends on the strike, entry 5 can be true at one strike "
                   "depth and false at another.",
                   "Illustration (UP day): index 25,010 at 15:19, CE strike 24,700, price 340. Worth now 310. (340 - 310) / 340 = "
                   f"8.8% - {tv_pct} or less. With a late pull-back, entry 5 is true."]},
        {"title": "Entry 6 - a small day AND a middle close",
         "note": "It looks for a small day that closed in the better half of its range, but not at the extreme. " + day_buy,
         "items": [f"Small day: the day's move must be under {SMALL_MOVE}%.",
                   f"Middle close: the close location (as in entry 2) must be {MIDDLE_CLOSE[0]} or more and under {MIDDLE_CLOSE[1]}.",
                   "Both true = entry 6 is true.",
                   "Illustration (UP day): open 25,000, close 25,060 = 0.24%, a small day. Low 24,940, high 25,140: (25,060 - "
                   "24,940) / 200 = 0.60 - a middle close. Entry 6 is true."]},
        {"title": "Entry 7 - Asia against the day AND a strong close",
         "note": "It looks for a day on which Asia went the other way and our index still finished near its best point. " + day_buy,
         "items": ["Asia against the day: of the Asian markets that traded today, count how many closed in the same direction as "
                   "our day (up on our UP day, down on our DOWN day). It must be at most half: 0, 1 or 2 of 5, or 0, 1 or 2 of 4.",
                   f"Strong close: the close location must be {STRONG_CLOSE} or more.",
                   "Both true = entry 7 is true.",
                   "Illustration (UP day): Nikkei +0.4%, Hang Seng -0.6%, KOSPI -0.2%, Shanghai -0.1%, ASX +0.1%: 2 of 5 went up "
                   "like our day - at most half. Close location 0.85 - strong. Entry 7 is true."]},
        {"title": "Entry 8 - a nervous market, an unusual range, a real move, and Asia with the day",
         "note": "It looks for a nervous market on an unusual-sized day when Asia had already gone the same way - a move that "
                 "tends to be given back overnight. It says: buy the OPPOSITE side - a PE on an UP day, a CE on a DOWN day. It is "
                 "used only when no day-side entry is true. Never on a holiday night.",
         "items": [f"India VIX: the close of India VIX's 15:19 candle must be {vix} or more.",
                   f"Range NOT normal: today's range / the usual range is under {lo_band}, or {hi_band} or more.",
                   f"The day moved: the day's move is {SMALL_MOVE}% or more.",
                   "Asia with the day: MORE than half of the Asian markets that traded today closed in the same direction as our "
                   "day (3, 4 or 5 of 5; 3 or 4 of 4).",
                   "All four true = entry 8 is true.",
                   "Illustration (UP day): India VIX 19.40. Range 290, usual range 200: 1.45 - not normal. Open 25,000, close "
                   "25,200: 0.80%. 4 of 5 Asian markets went up. Entry 8 is true: if no day-side entry is true, buy a PE."]},
        {"title": "Entry 9 - the market is in balance",
         "note": "It looks for a market trading around the same prices as before, where the day's move tends to be given back. It "
                 "says: buy the OPPOSITE side - a PE on an UP day, a CE on a DOWN day. It is used only when no day-side entry is "
                 f"true and entry 8 is not true, and only with at most {NINE_MAX} confirmations. It is the only entry that can also "
                 "trade on a holiday night.",
         "items": ["Today's value area: cut today's 1-minute candles from 09:15 to 15:14 into 30-minute blocks and note each "
                   "block's low and high.",
                   "Divide the price into small steps of 0.02% of the price (5 points when the index is at 25,000; 16 points at "
                   "80,000). For each step "
                   "count how many blocks traded there.",
                   "Start at the busiest step. Add the next step above or below, whichever is busier, and keep going until the band "
                   "holds 70% of all the counts. That band is today's value area.",
                   "Do the same with yesterday's candles. BALANCE A = today's value area and yesterday's overlap (they share at "
                   "least one price).",
                   "Put the blocks of the previous five sessions together (not today) and do the same. BALANCE B = today's 15:14 "
                   "close is inside that five-session value area.",
                   "A or B true = entry 9 is true.",
                   "Illustration: today's value area 25,040 to 25,110, yesterday's 25,090 to 25,180. They share 25,090 to 25,110, "
                   "so balance A is true and entry 9 is true."]},
        {"title": "Entry 10 - the day moved, Asia against the day, AND crude oil against the day",
         "note": "It looks for a day that moved clearly even though both Asia and crude oil went the other way. " + day_buy,
         "items": [f"The day moved: the day's move is {SMALL_MOVE}% or more.",
                   "Asia against the day: at most half of the Asian markets that traded today closed in the same direction as our "
                   "day.",
                   "Crude oil against the day: crude futures at 14:30 India time against 02:30 this morning (finished one-hour "
                   "candles). Crude must be DOWN on an UP day, or UP on a DOWN day. No reading = entry 10 is false.",
                   "All three true = entry 10 is true.",
                   "Illustration (UP day): open 25,000, close 25,113: 0.45%. 2 of 5 Asian markets went up. Crude 80.00 at 02:30, "
                   "79.40 at 14:30: -0.75%, down on an UP day. Entry 10 is true."]},
    ]
    confirm = {
        "title": "The three confirmations",
        "note": "They are always measured against the DAY's direction, whichever side is bought. Count how many are confirmed: "
                "0, 1, 2 or 3. A reading you cannot get is not confirmed.",
        "items": [
            "Confirmation 1 - US futures are WITH the day. Take S&P 500 futures on one-hour candles: the close of the last hour "
            "candle finished by 14:30 India time, against the close of the last one finished by 02:30 this morning. Confirmed "
            "when the change is UP on an UP day, or DOWN on a DOWN day.\nIllustration: 5,800.00 at 02:30 and 5,817.40 at 14:30 "
            "= +0.30%. On an UP day it is confirmed.",
            "Confirmation 2 - option writers SUPPORT the day. Take the at-the-money CE and PE of the expiry you will trade. For "
            "each: open interest at 15:19 minus open interest at 09:30 = open interest added today. Confirmed when the option of "
            "the OTHER side added at least as much as the option of our side - on an UP day the PE added more (writers are "
            "selling puts under the market), on a DOWN day the CE added more.\nIllustration (UP day): the PE added 12,00,000, "
            "the CE added 7,00,000. Confirmed.",
            "Confirmation 3 - crude oil is AGAINST the day. The same crude reading as entry 10: 14:30 against 02:30. Confirmed "
            "when crude is DOWN on an UP day, or UP on a DOWN day.\nIllustration: crude -0.75% on an UP day. Confirmed."]}
    decide = {
        "title": "Putting it together: what to do",
        "note": "Read from the top; the first row that fits decides.",
        "head": ["What is true at 15:14", "Confirmations", "What you do"],
        "rows": [
            ["A day-side entry is true (any of 1-7, 10); not a holiday night", f"{DAY_NEEDS}, 2 or 3 of 3",
             "BUY THE DAY'S SIDE: a CE on an UP day, a PE on a DOWN day"],
            ["A day-side entry is true; not a holiday night", "0 of 3", "NO TRADE"],
            ["No day-side entry is true; entry 8 is true", "any", "BUY THE OPPOSITE SIDE: a PE on an UP day, a CE on a DOWN day"],
            ["No day-side entry, no entry 8; entry 9 is true (a holiday night too)", f"0, 1 or {NINE_MAX} of 3",
             "BUY THE OPPOSITE SIDE: a PE on an UP day, a CE on a DOWN day"],
            ["No day-side entry, no entry 8; entry 9 is true", "3 of 3", "NO TRADE"],
            ["No entry is true", "-", "NO TRADE"]]}
    proven = [
        "Everything here is January to July 2026, and the entries, the confirmations, the way they are combined and the "
        "exit were all chosen on these same sessions. It is a fitted rule: expect weaker results on new data.",
        "Earlier years (index only, no option prices): entries 1-7 lost on May 2024 to December 2025; entry 10 held "
        "(53 trades, profit factor 2.53). Entry 8 and the open-interest confirmation cannot be checked there.",
        "Weak spots: entry 9 (it pays only on nights no other entry trades; on SENSEX only its holiday nights pay), the "
        "open-interest confirmation (it says 'support' on about three nights in four), and entry 8 (all its trades are "
        "in March to May 2026).",
        "A 'best' strike plan (day-side weekend holds bought 2 strikes out of the money with the same rupees, "
        "profit booked at 09:20) was added on 5 October and REMOVED on 6 October 2026: its premise - the weekend "
        "overnight premium - is a 2022-2025 fact, but on this report's unseen test period it earned less than the "
        "plain plan. The removal is recorded here so the attempt is not forgotten and not retried on the same data.",
        "The clean test still to run is the locked August-September data, which nothing here has seen.",
    ]
    rule_sections = None
    if str(RULE_DEPTH) in {str(t["variant"]["moneyness"]) for t in trades}:
        rule_sections = [lead, {"title": "The rule, step by step", "items": steps}, exit_nights(), decide, *entries,
                         confirm, {"title": "What is and is not proven", "items": proven}]
    meta = {
        "title": "Over night Hold v5 - the final rule",
        "subtitle": "Ten entries checked together at 15:14, then three confirmations; bought in the 15:20 minute; exit: "
                    f"{EXIT_LABEL[FIRST_EXIT]}. Worst fill only.",
        "instrument": "NIFTY 50 weekly options",
        "category": CATEGORY,
        "from": frm.isoformat(), "to": to.isoformat(),
        # the window box offers exactly these two (the user, 2026-10-05); dates outside them show as 'custom'
        "windows": ([{"l": "Jan-Jul: pattern mining (everything was chosen here)", "a": frm.isoformat(), "b": "2026-07-31"},
                     {"l": "Aug onwards: unseen data (the test period)", "a": HOLDOUT_SPLIT, "b": to.isoformat()}]
                    if to.isoformat() > HOLDOUT_SPLIT else None),
        "lot_size": lot,
        "fill_rule": "WORST FILL ONLY: buy at the minute's HIGH, sell at the minute's LOW, entry and exit; "
                     "signals act in the next 1-minute bar",
        "params": {"signal": "09:15 open vs 15:14 close (1m)",
                   "the rule": f"day-side entry (1-7, 10) + at least {DAY_NEEDS} confirmation -> the day's side; else entry 8 -> "
                               f"the opposite side; else entry 9 with at most {NINE_MAX} confirmations -> the opposite side",
                   "strike": f"{RULE_DEPTH} in the money (the panel offers 6 ITM to 6 OTM)",
                   "entry": ENTRY_MIN,
                   "if the strike did not trade at 15:20": "one strike nearer the money in the next minute, as far as the at-the-money strike",
                   "exit": EXIT_LABEL[FIRST_EXIT] + " (the selected exit)",
                   "the other exit (panel)": EXIT_LABEL[FIRST_EXITS[1]],
                   "lots": LOTS, "expiry": "nearest >= 1 day after exit day",
                   "holiday night": f"fewer than {ASIA_MIN_OPEN} of 5 Asian markets open today, or the US shut tonight: only entry 9 can trade",
                   "confirmations": "US futures with the day | option writers support the day | crude oil against the day"},
        "rule_steps": steps,
        "limits": [
            "ONE RULE. The report holds only the final rule's trades. 'Which entries' does not switch between rules: it shows "
            "the rule's own trades entry by entry. A night with two true day-side entries is one trade and appears under both.",
            "FILLS - WORST ONLY. Bought in the 15:20 minute at its HIGH; sold at the exit minute's LOW. The script stops if "
            "any trade is filled otherwise. Option buying only. One lot; costs at the broker-read rates, sale tax at the "
            "rate of the SALE's day; capital = premium x quantity.",
            V4["exit_limit"](),
            "Entry 5 reads the time value of the option at the chosen strike, so the number of trades can differ a little "
            "from strike to strike.",
            "CONFIRMATIONS count readings that are confirmed; a missing reading (a US holiday, an option that did not "
            "trade) is not a confirmation. They are measured against the day's direction on every night.",
            "US FUTURES AND CRUDE OIL: one-hour bars from Yahoo Finance (ES=F and CL=F, continuous front-month series) on "
            "local disk; nothing is fetched by this run. A bar's time is its START; the reading uses the last bar FINISHED "
            "by 14:30 IST against the last bar finished by 21:00 UTC the evening before, so nothing after the 15:14 "
            "decision is used. Checked against separate daily files (correlation 0.97 for both); not checked against a "
            "second vendor. A contract-roll day can distort a crude reading.",
            "OPEN INTEREST is the seventh column of the local option candle files: the at-the-money call and put of the "
            "traded expiry, 09:30 to 15:19, needing a candle of each at or after 15:10. There is no second source for it.",
            "VALUE AREA (entry 9): 30-minute blocks of the index's 1-minute candles up to 15:14, price steps of 0.02%, 70% of "
            "the counts. Recomputed separately from the raw candles: the same answer on all 143 sessions of both indices.",
            "ASIA AND HOLIDAY NIGHTS: daily closes from Yahoo Finance on local disk. The US check reads the S&P 500's daily "
            "candles, which are dated in New York time: a date on which India traded and the S&P 500 has no candle is a night "
            "the US was shut. India VIX = its 15:19 one-minute close.",
            f"WINDOW: {frm} to {to}, {sum(1 for x in sessions if frm.isoformat() <= x <= to.isoformat())} complete sessions.",
            "THIN CONTRACTS: a strike that did not trade in the 15:20 minute is never filled from a later price of the same "
            "contract; the rule moves one strike nearer the money and buys in the next minute at that minute's HIGH (the "
            "trade's note says so). At the rule's depth it happened on "
            f"{sum(1 for t in trades if str(t['variant']['moneyness']) == str(RULE_DEPTH) and t['variant']['first_exit'] == FIRST_EXIT and t['tags'].get(STRIKE_TAG) != AT_RULE_STRIKE)}"
            " trades. When nothing traded all the way to the money, the market did not trade the option: the night is "
            "shown as skipped (nothing to buy), not as bad data.",
            "SALE WHEN THE OPTION DOES NOT TRADE ON THE EXIT DAY (the owner, 2026-10-11): it is sold in the first minute it "
            "trades after that - on the next session, up to expiry - at that minute's LOW. The trade's exit reason says so.",
            f"SESSIONS USED: every minute the rule reads must be there (09:15, 14:59, 15:14, 15:19) and at most "
            f"{MAX_MISSING} other minute of 09:15-15:19 may be missing (the source - Upstox - lacks one minute on a few "
            "days, in every index at once); nothing is filled in. A special short session (the one-hour Muhurat) is not a "
            "trading night. The last session in the data has no next session to sell in and waits for a later run.",
        ],
        "rejected": [
            ["Entry 9 on every balance night", "buying the opposite side whenever the market is in balance loses heavily; "
             "entry 9 is used only when no other entry trades and not all three confirmations back the day."],
            ["Needing 2 or 3 confirmations for a day-side trade", "it removes many winning trades; one confirmation was the "
             "best trade-off. The breakdown by confirmations shows each count."],
            ["Selling every trade in the 09:16 minute (the exit for one day, 2026-10-04)", "it cost about a fifth of the "
             "profit: 09:16 is one of the widest minutes of the day, and a trade that opens at a loss tends to recover in "
             "the afternoon."],
            ["A stop or a profit target", "not in the rule."],
        ],
        "coverage": coverage(sessions, frm, to, ROWS_PER_SESSION),
        "rerun": rerun_command(SLUG, settings, frm.isoformat(), to.isoformat()),
        "price_ratio": dict(V4["PRE_RATIOS"]),
        "price_ratio_basis": f"the median close ratio of the {V4['TREND_LOOKBACK_DAYS']} calendar days before {frm} (known before the first trade)",
    }
    meta["sources"] = V4["data_sources"](
        with_es=True, with_crude=True,
        options_used="every fill - the 15:20 buy and the next session's sale; entry 5's time value (15:19 price); and "
                     "confirmation 2 (open interest of the at-the-money call and put, 09:30 to 15:19)")
    if rule_sections:
        meta["rule_sections"] = rule_sections
    groups = [{"name": "Decided by", "keys": [WHY_TAG]},
              {"name": "Confirmations", "keys": [CONF_TAG]},
              {"name": "US futures", "keys": [ES_TAG]}, {"name": "Option writers", "keys": [OI_TAG]},
              {"name": "Crude oil", "keys": [CRUDE_TAG]},
              {"name": "Direction", "keys": ["direction"]},
              {"name": "Holiday night", "keys": [HOLIDAY_TAG]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups,
                            settings=settings, chart="default", sessions_log=log, worst_only=True)
    path = write_report(payload, SLUG)
    for first in values_of(settings, "first_exit"):
        print(f"   exit {first}: " + console_summary([t for t in trades if str(t["variant"]["first_exit"]) == first]))
    print(path)


HOLDOUT_SPLIT = "2026-08-01"      # Part 2 begins here: the locked test data, first opened on 2026-10-05


def _two_part_rows(trades: list[dict], insts: list[str]) -> list[list[str]]:
    """The holdout table's rows, computed from the run's own trades: per index and strike plan, at the
    rule's strike depth and the selected exit, Part 1 (entry day before HOLDOUT_SPLIT) then Part 2."""
    import py_funcs as _pf
    rows = []
    for inst in insts:
        for plan in (PLAN_STABLE, PLAN_BEST):
            mine = [t for t in trades
                    if (t.get("instrument") or inst) == inst
                    and str(t["variant"].get("moneyness")) == str(RULE_DEPTH)
                    and str(t["variant"].get("first_exit")) == FIRST_EXIT
                    and str(t["variant"].get("strike_plan")) == plan]
            for label, part in (("Part 1: Jan-Jul (in sample)", [t for t in mine if t["day"] < HOLDOUT_SPLIT]),
                                ("Part 2: from 1 Aug (THE TEST PERIOD)", [t for t in mine if t["day"] >= HOLDOUT_SPLIT])):
                if not part:
                    rows.append([inst, plan, label, "0", "-", "-", "-", "-"])
                    continue
                b = _pf._book(part)
                rows.append([inst, plan, label, str(b["n"]), f"{b['win']:.0f}%",
                             f"{b['pf']:.2f}" if b["pf"] is not None else "n/a",
                             f"{b['net']:+,.0f}", f"{abs(b['max_dd']):,.0f}"])
    return rows


def add_two_parts(path: str) -> None:
    """Insert 'The two parts' section into the written combined report, right after the lead section,
    computed from the payload's own trades (nothing hard-coded).  The user opened the held-out
    August-September data for the first time on 2026-10-05, for this run."""
    import py_funcs as _pf
    with open(path, encoding="utf-8") as f:
        html = f.read()
    p = json.loads(html[html.rindex(_pf.DATA_START) + len(_pf.DATA_START):html.rindex(_pf.DATA_END)])
    m = p["meta"]
    insts = m.get("instruments") or sorted({t.get("instrument") for t in p["trades"] if t.get("instrument")})
    section = {
        "title": "The two parts: built on Jan-Jul, tested from 1 Aug to the current date",
        "note": "The window of this report is January to September 2026, shown here in two parts, split at 1 August. "
                "Part 1 is the window every rule, entry, exit and strike plan was chosen on. Part 2 was locked away "
                "and first opened on 5 October 2026 - nothing here was chosen on it. Part 2 is the only out-of-sample "
                "evidence in this report. Both parts are the same rule at the rule's strike depth "
                f"({V4['rung_label'](RULE_DEPTH)}) and the selected exit; 'stable' and 'best' are the two choices of "
                "the Strike plan box. Worst fills only, as everywhere in this report.",
        "head": ["Index", "Strike plan", "Part", "Trades", "Wins", "Profit factor", "Net (Rs)", "Worst drawdown (Rs)"],
        "rows": _two_part_rows(p["trades"], insts)}
    secs = m.get("rule_sections") or []
    secs = [s for s in secs if s.get("title") != section["title"]]      # a re-run replaces it
    m["rule_sections"] = secs[:1] + [section] + secs[1:]
    _pf.write_report(p, path)
    print("two-part section (Part 1 = Jan-Jul, Part 2 = Aug-Sep holdout):")
    for r in section["rows"]:
        print("  " + " | ".join(r))


if __name__ == "__main__":
    _path = run_instruments(__file__, ladder=tuple(LADDER), keep=("first_exit",))   # both exits at every strike
    add_two_parts(_path)
elif __name__ == "__instrument__":
    main()
