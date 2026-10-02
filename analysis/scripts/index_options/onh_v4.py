"""Over night Hold - v4 (ONH v4): the overnight hold traded on six SCENARIOS (A-F), plus the
ASIA RESCUE (the user, 2026-09-30) for nights where no scenario fires.

THE RULE (scenarios A-F built 2026-09-29 from a one-year scenario study and stress-tested on the year before it;
the Asia rescue added 2026-09-30 from the global-factor study of the Jan-Jul 2026 window)
  Step 1  After the 15:14 candle, take the session's 09:15 open and 15:14 close.  Up day -> the trade is
          a CALL, down day -> a PUT; equal / candle missing -> no trade.  (Direction as in v2/v3.)
  Step 2  Trade tonight if ANY of these scenarios is true (all read from candles complete by 15:14,
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
  Step 2b THE ASIA RESCUE.  No scenario fired, but ALL of: at least 4 of the 5 Asian indices (Nikkei 225,
          Hang Seng, KOSPI, Shanghai Composite, ASX 200 - every close is in before 13:30 IST) traded today;
          at most HALF of those open moved the same way as NIFTY's day (the region went AGAINST the day);
          and the 15:14 close is in the day's strongest 20% (close location >= 0.8).  Then trade anyway.
          Fewer than 4 open (a regional holiday) = no read, and the night is a holiday night (Step 2d):
          no trade.  The Asia closes come from local disk (yahoo_<ticker>_daily.json).
  Step 2c THE REVERSE (the user, 2026-09-30, added to decide on later).  No scenario and no rescue, but the day
          moved at least 0.6% (15:14 close vs 09:15 open) and India VIX's 15:19 close is at least 17: buy the OPPOSITE side -
          a PUT on an up day, a CALL on a down day - six strikes ITM for that side, same entry and exit.  These
          are the nights the rule found the market takes the day's move back next morning.
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
  The scenarios' lead in the build year is largely that year's own fit; in the unseen year it is a
  modest improvement on every night.  Treat it as provisional.

WHERE THE ASIA RESCUE COMES FROM (scratchpad, 2026-09-30; NIFTY, 6 ITM, worst fill, Jan-Jul 2026)
  Every night was priced and 16 global factors known by 15:20 IST were split by whether they agreed with
  the option bought.  None "supported" the 73 nights scenarios A-F declined; the sign ran the other way:
  when Asia moved the same way as NIFTY the declined nights lost heavily, when Asia moved against them
  they were positive - and only with a strong close.
    scenarios A-F alone               69 nights 75% win PF 4.27 +3.04L  maxDD -19k
    declined, Asia against, strong    19 nights 79% win PF 4.86 +0.79L  (Jan-Apr 10 nights 90%, May-Jul 9 nights 67%)
    declined, Asia against, not strong 10 nights 60% win PF 0.35 -0.34L
    scenarios A-F + rescue            88 nights 76% win PF 4.38 +3.82L  maxDD -19k
  Every morning cut or stop tried (option gap, index gap, candle-close stops from 09:16 or 09:30) made
  every group worse - losses are gap-against nights the market claws back by 15:14 - so no stop.
  Holiday nights (fewer than 4 Asian closes, or the US shut that night) had normal-sized losses and tiny
  wins; the user first kept trading them on scenarios A-F, then made the holiday skip part of the rule.  The rescue was chosen on THIS window
  and has NOT been checked on the year before.

WHERE THE REVERSE COMES FROM (scratchpad, 2026-09-30; the 54 nights the rule still declined)
  With the day's direction nothing works on them: 170 one- and two-factor cuts, none positive in both halves.
  The next morning takes the day's move back (median next-day close -0.47% against the day; 17 of 54 gapped
  against by more than 0.3%).  The opposite side, same entry and exit, worst fill:
    all 53 declined nights            77% win PF 2.52 +1.46L   (Jan-Apr +1.68L, May-Jul -22k)
    declined AND day move >= 0.6%     27 nights 93% win PF 9.65 +1.62L (Jan-Apr +1.52L, May-Jul +9k)
    declined AND India VIX >= 17      23 nights 91% win PF 6.68 +1.53L (all in Mar-Apr-May)
    the rule's own 88 nights reversed 39% win PF 0.19 -4.97L   (the control: the rule's side is right)
  The money is March-April, a nervous tape (India VIX 17-25); outside it the reverse earns scraps.  It is in
  the rule at the user's request, to be decided on after the year-before check.

  Step 2d THE HOLIDAY SKIP (the user, 2026-09-30, first a panel option, then made part of the rule).  Whatever
          fired, no trade when fewer than 4 of the 5 Asian markets were open today or the US market is shut
          tonight: half of NIFTY's heavy losers fell on such nights, and they win almost nothing.

The panel: 'Direction check' offers the v4 rule (a scenario A-F, the Asia rescue or the reverse, never
on a holiday night), the same rule with holiday nights traded (the 103-trade book), and no check (every night) - the user, 2026-09-30; the earlier time-value check, the
strike ladder and the first-exit candle stay as in v3 for analysis.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *          # noqa: F401,F403
import argparse

ENTRY_MIN = "15:20"
READ_MIN = "15:19"
SIGNAL_MIN = "15:14"
TIME_EXIT = "15:14"
STEP = strike_step()             # 50 on NIFTY, 100 on SENSEX - read from the contract list
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
# The thresholds of scenarios A-F (see the docstring)
RANGE_N, RANGE_BAND = 20, (0.8, 1.2)   # normal range: today's range / average of the previous 20 full days
SMALL_MOVE = 0.3                        # a small day: 15:14 close within this % of the 09:15 open
STRONG_CLOSE = 0.8                      # close location (in the day's direction) at or above this = strong close
MIDDLE_CLOSE = (0.5, 0.8)               # scenario F: close location in this band
LATE_MIN = 15                           # the pull-back window: the last 15 minutes, 14:59 close -> 15:14 close
# THE ASIA RESCUE (the user, 2026-09-30): a night with no scenario is still traded when the region moved
# AGAINST the day and the close is strong.  Five closes, all in before 13:30 IST, read from local disk.
ASIA = {"^N225": "Nikkei 225", "^HSI": "Hang Seng", "^KS11": "KOSPI", "000001.SS": "Shanghai", "^AXJO": "ASX 200"}
ASIA_MIN_OPEN = 4            # fewer markets open today = no read: a holiday night, no trade
ASIA_MAX_AGREE = 0.5         # at most this share of the open markets moved the day's way = 'against the day'
TREND_TAG, RULE_TAG, WHY_TAG, SCEN_TAG = "5-day trend", "v4 rule", "why traded", "scenarios"
ASIA_TAG, CLOSE_TAG = "Asia today", "close location"
SCEN_LABEL = {"A": "A trend + normal range", "B": "B strong close + normal range", "C": "C small day + normal range",
              "D": "D small day + late pull-back", "E": "E late pull-back + time value <= 15%",
              "F": "F small day + middle close"}
AGREES, AGAINST, NO_HIST = "agrees with the day", "against the day", "no history yet"
ASIA_AGAINST, ASIA_WITH, ASIA_NO_READ = "against the day", "with the day", "no read (fewer than 4 open)"
# THE REVERSE (the user, 2026-09-30): no scenario, no rescue, a big day on a nervous tape -> the OPPOSITE side.
IVIX_NAME = "VIX"            # India VIX on local disk: VIX_candles.json (NSE_INDEX|India VIX), 1-minute bars
REVERSE_MOVE = 0.6           # the day's move (15:14 close vs 09:15 open), at least this %
REVERSE_IVIX = 17.0          # India VIX's 15:19 close (the same minute as the option price) at least this
SIDE_TAG, IVIX_TAG = "side vs day", "India VIX"
# THE HOLIDAY SKIP (the user, 2026-09-30, made part of THE RULE the same day): no trade on a night with fewer
# than ASIA_MIN_OPEN Asian markets open today or the US market shut that night.  Half the heavy losers (worse
# than -8k) on NIFTY fell on such nights; skipping them paid in both halves of the window.
US_TICKER = "^GSPC"          # a weekday with no S&P 500 bar = the US is closed that night
HOLIDAY_TAG = "holiday night"
WITH_DAY, AGAINST_DAY = "with the day", "against the day (reverse)"
WHY_SCEN, WHY_RESCUE, WHY_REVERSE, WHY_NO = ("entry 1-6 (scenario A-F)", "entry 7 only (Asia)",
                                             "entry 8 (opposite side)", "no entry")
# The window is START_DATE .. END_DATE from py_funcs - one place for every strategy.
# Do not shadow them here; a local copy is how one script silently ran a different period.
# Only the strike ladder costs requests, and Upstox meters per second, per minute and per half
# hour, so the whole ladder over the standing window is about an hour of pacing.  Three rungs
# around the rule is what a default run ships; --moneyness 0,2,4,6,8,10,12 buys the rest.
# The rungs: 6 in the money, through at the money, to 6 out of the money (the user, 2026-09-30: this
# strategy runs the OTM side too; the shared STRIKE_LADDER stops at ATM).  A positive value is strikes
# IN the money, a negative one OUT - strike_offset moves the other way for a negative value.
LADDER = list(STRIKE_LADDER) + [-1, -2, -3, -4, -5, -6]
DEFAULT_LADDER = ",".join(str(v) for v in LADDER)          # 6 ITM .. ATM .. 6 OTM
PASS_PTS, FAIL_PTS = f"<= {TV_MAX_POINTS:.0f} pts", f"above {TV_MAX_POINTS:.0f} pts"
PASS_SHARE, FAIL_SHARE = f"<= {TV_MAX_SHARE * 100:.0f}%", f"above {TV_MAX_SHARE * 100:.0f}%"
PASS_RANK, FAIL_RANK = f"cheapest {TV_RANK_KEEP} in 100", f"dearer than {TV_RANK_KEEP} in 100"
NO_RANK = "no history yet"


def rung_label(v: int) -> str:
    return "at the money" if v == 0 else f"{abs(v)} {'in' if v > 0 else 'out of'} the money"


# --entry N: ONE entry of the rule run alone as its own strategy (the user, 2026-10-01).  Read here, before SETTINGS.
ENTRY_MODE = sys.argv[sys.argv.index("--entry") + 1] if "--entry" in sys.argv[:-1] else None
if ENTRY_MODE is not None and ENTRY_MODE not in list("12345678"):
    raise SystemExit(f"--entry takes 1 to 8, got {ENTRY_MODE!r}")
ENTRY_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "onh_v4_entries"))


def entry_tag(n) -> str:
    return f"entry {n} true"


# The control panel.  Defaults = the rule as the prompt states it.
SETTINGS = [
    setting("confirm", "Direction check", kind="entry", mode="filter", default="rule",
            help="which nights the day's direction is traded on; 'off' trades every night",
            options=[
                {"value": "rule", "label": "the v4 rule: at least one of entries 1-8 TRUE, never on a holiday night "
                                           "(Asia thin or US shut)",
                 "tag": {RULE_TAG: ["yes"], HOLIDAY_TAG: ["no"]}},
                {"value": "rule_holidays", "label": "the v4 rule, holiday nights traded too (the 103-trade book)",
                 "tag": {RULE_TAG: ["yes"]}},
                {"value": "off", "label": "no check - every night", "tag": None}]
            if ENTRY_MODE is None else [
                {"value": "rule", "label": f"entry {ENTRY_MODE} alone: both its conditions TRUE, never on a holiday night",
                 "tag": {entry_tag(ENTRY_MODE): ["yes"], HOLIDAY_TAG: ["no"]}}]),
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
    """Everything scenarios A-F read, from candles complete by 15:14 only (rule 4).  Scenario E also needs
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
    rng_ratio = avg = None
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
            "day move %": move, "late pull-back": late_pull, "scen": scen,
            # the raw numbers behind each read - for the worked examples of the rule-only report
            "hi": hi, "lo": lo, "avg range": avg, "trend ref": ref,
            "trend ref day": days[i - TREND_N] if i >= TREND_N else None, "late close": c_late,
            "normal": normal, "small": small}


ENTRY_MINUTES = {f"{m // 60:02d}:{m % 60:02d}" for m in range(9 * 60 + 15, 15 * 60 + 20)}   # 09:15 .. 15:19
PRE_RATIOS: dict[str, float] = {}  # {index: its close ratio to NIFTY over the sessions BEFORE the window}


async def pre_window_ratio(up, name: str, frm: date) -> float:
    """The median close ratio of index `name` to NIFTY over the sessions BEFORE `frm` - known on the first day of the
    window, unlike py_funcs.price_scale(), which uses the whole window (audit fix 2026-10-01)."""
    def closes(key_sessions):
        return {d: r[-1][4] for d, r in key_sessions.items() if r and d < frm.isoformat()}
    a, b = [(await up.find_instrument(n))["instrument_key"] for n in (name, REFERENCE_INSTRUMENT)]
    span = (frm - timedelta(days=TREND_LOOKBACK_DAYS), frm - timedelta(days=1))
    mine, ref = [closes(sessions_from(await up.candles(k, "1m", *span))) for k in (a, b)]
    ratios = sorted(mine[d] / ref[d] for d in mine if d in ref)
    if not ratios:
        raise SystemExit(f"{name}: no sessions before {frm} to set the strike distance from")
    r = ratios[len(ratios) // 2] if len(ratios) % 2 else (ratios[len(ratios) // 2 - 1] + ratios[len(ratios) // 2]) / 2
    step = strike_step(name)
    print(f"{name} / {REFERENCE_INSTRUMENT} close ratio before {frm}: {r:.4f} over {len(ratios)} sessions "
          f"-> 6 NIFTY strikes = {round(6 * REFERENCE_STEP * r / step)} {name} strikes")
    return r


def depth_text(steps: int = 6) -> str:
    """The rule's strike distance on THIS index, in its own strikes and points - e.g. '6 strikes of 50 = 300 points'
    on NIFTY, '10 strikes of 100 = 1,000 points' on SENSEX.  No index name, so the NIFTY-to-SENSEX renaming of report
    text cannot turn it into a wrong number (audit round 3, 2026-10-01)."""
    n = abs(round((strike_at(100000.0, steps, "CE") - atm_strike(100000.0, STEP)) / STEP))
    return f"{n} strikes of {STEP:,.0f} = {n * STEP:,.0f} points"


def strike_at(spot: float, steps: int, option_type: str) -> float:
    """`steps` NIFTY strikes in the money (out when negative) from the at-the-money strike.  On another index the
    same share of the price, with the ratio known BEFORE the window (PRE_RATIOS), rounded to its own strikes."""
    atm = atm_strike(spot, STEP)
    if instrument() == REFERENCE_INSTRUMENT:
        n = steps
    elif instrument() in PRE_RATIOS:
        n = round(steps * REFERENCE_STEP * PRE_RATIOS[instrument()] / STEP)
    else:
        raise SystemExit(f"{instrument()}: no close ratio before the window, so no strike distance")
    return atm + (-1 if option_type == "CE" else 1) * n * STEP


def prev_n_minutes(hhmm: str, n: int) -> str:
    m = hhmm_minutes(hhmm) - n
    return f"{m // 60:02d}:{m % 60:02d}"


async def asia_reads(frm: date, to: date) -> dict[str, dict[str, float]]:
    """{ticker: {day: % change of that day's close vs the previous bar}} for the five Asian indices, from
    local disk (yahoo_daily).  A day absent from a market's file is a day that market did not trade (or is
    outside the fetched range - the run's notes say which); it is never filled."""
    out: dict[str, dict[str, float]] = {}
    for tk, name in ASIA.items():
        bars = await yahoo_daily(tk, frm, to) or []
        chg: dict[str, float] = {}
        for prev, cur in zip(bars, bars[1:]):
            if prev[4]:
                chg[cur[0]] = (cur[4] / prev[4] - 1) * 100
        if not chg:
            print(f"  ! {name} ({tk}): no daily bars on local disk ({yahoo_file(tk)}) - reads as not open every night")
        out[tk] = chg
    return out


def asia_check(asia: dict[str, dict[str, float]], d: str, side_opt: str) -> dict:
    """Did the region move WITH or AGAINST the day?  Counts the markets open today and how many of them
    moved the same way as the index's day; fewer than ASIA_MIN_OPEN open = no read."""
    sgn = 1 if side_opt == "CE" else -1
    moves = {ASIA[tk]: chg[d] for tk, chg in asia.items() if d in chg}
    n_open = len(moves)
    agree = sum(1 for v in moves.values() if v * sgn > 0)
    if n_open < ASIA_MIN_OPEN:
        tag = ASIA_NO_READ
    elif agree / n_open <= ASIA_MAX_AGREE:
        tag = ASIA_AGAINST
    else:
        tag = ASIA_WITH
    return {"tag": tag, "open": n_open, "agree": agree, "moves": moves}


def breakeven_line(entry_px: float, qty: int, day=None, exit_day=None) -> float:
    """Entry price + round-trip costs per unit, costs evaluated with the sale at the line (fixed point).  The sale
    tax is at the rate of the SALE's day, `exit_day` (audit fix 2026-10-01: a 30 Mar buy sold on 1 Apr pays 0.15%)."""
    line = entry_px
    for _ in range(60):
        new = entry_px + option_round_trip("LONG", entry_px, line, qty, day=day, exit_day=exit_day) / qty
        if abs(new - line) < 1e-6:
            return new
        line = new
    return line


# ---------------------------------------------------------------------------
# simulate (pure: bars -> exit)
# ---------------------------------------------------------------------------
def simulate_exit(exit_rows: list[list], line: float, first_exit: str, time_exit: str = TIME_EXIT) -> dict:
    """First candle from `first_exit` with LOW > line is the trigger (a completed-bar signal, rule 3);
    the sale fills in the very next 1-minute bar at that bar's LOW.  Nothing by `time_exit` -> that
    bar itself (a scheduled time exit; 15:14 is the rule, 14:00 the panel's early-quit view).
    Missing next bar -> no trade (strict)."""
    by = {r[0]: r for r in exit_rows}
    for r in exit_rows:
        if r[0] < first_exit or r[0] >= time_exit:
            continue
        if r[3] > line:
            nxt = by.get(next_minute(r[0]))
            if nxt is None:
                return {"bar": None, "reason": f"bar after trigger {r[0]} missing", "trigger": r}
            return {"bar": nxt, "reason": "low above line", "trigger": r}
    tb = by.get(time_exit)
    if tb is None:
        return {"bar": None, "reason": f"{time_exit} exit bar missing", "trigger": None}
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
    rule_first = default_combo(settings)["first_exit"]
    DETAILS.clear()
    async with Upstox() as up:
        und = await up.find_instrument(instrument())
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        if info["strike_step"] != STEP:
            raise SystemExit(f"Upstox strike step is {info['strike_step']}, the prompt assumes {STEP}.")
        fetch_to = min(to + timedelta(days=7), now.date())
        # TREND_LOOKBACK_DAYS before --from: read for the 5-day trend only, never traded
        cs = await up.candles(key, "1m", frm - timedelta(days=TREND_LOOKBACK_DAYS), fetch_to)
        sessions = sessions_from(cs)
        cal = await up.expiry_calendar(key, frm, to)
        asia = await asia_reads(frm - timedelta(days=TREND_LOOKBACK_DAYS), fetch_to)
        print("Asia closes on local disk: " + ", ".join(f"{ASIA[tk]} {len(c)} days" for tk, c in asia.items()))
        # India VIX at 15:19 - its own 1-minute bar, the same minute the option price is read (no look-ahead:
        # the 15:30 daily close was used until 2026-09-30 and flipped one night of the reverse).
        ivix: dict[str, float] = {}
        try:
            vix_key = (await up.find_instrument(IVIX_NAME))["instrument_key"]
            for day, vrows in (await up.minute_sessions(vix_key, frm - timedelta(days=TREND_LOOKBACK_DAYS), fetch_to)).items():
                vbar = bar_at(vrows, READ_MIN, tolerance=0)      # the 15:19 candle only (audit fix 2026-10-01)
                if vbar is not None:
                    ivix[day] = vbar[4]
        except LookupError as exc:
            print(f"  ! India VIX: {exc}")
        print(f"India VIX 15:19 reads on local disk: {len(ivix)} sessions" if ivix else
              f"  ! India VIX ({IVIX_NAME}_candles.json): no 1-minute bars on local disk - the reverse never fires")
        us_bars = await yahoo_daily(US_TICKER, frm - timedelta(days=TREND_LOOKBACK_DAYS), fetch_to) or []
        us_days = {b[0] for b in us_bars}
        us_span = (us_bars[0][0], us_bars[-1][0]) if us_bars else None
        print(f"US sessions (S&P 500) on local disk: {len(us_days)} days" if us_days else
              f"  ! S&P 500 ({US_TICKER}): no daily bars on local disk ({yahoo_file(US_TICKER)}) - US holidays unknown, never flagged")
        # A session is used when it has EVERY minute from 09:15 to 15:19 - all the rule reads on the entry day
        # (audit fix 2026-10-01: it used to need all 375 minutes, which judges today by candles after the entry).
        # Today's session only after 15:45.
        full = {d: r for d, r in sessions.items()
                if ENTRY_MINUTES <= {x[0] for x in r} and not (d == now.date().isoformat() and now.strftime("%H:%M") < "15:45")}
        days = sorted(full)
        for d, r in sessions.items():
            if d not in full and frm.isoformat() <= d <= to.isoformat():
                gap = sorted(ENTRY_MINUTES - {x[0] for x in r})
                skips.append(f"{d}: session incomplete ({len(gap)} minutes missing before 15:20) - not used")
                log.append(session_row(d, "no data", f"session incomplete: {len(gap)} minutes missing between 09:15 "
                                                     f"and 15:19 (first {gap[0] if gap else '-'})"))
        # SENSEX strike distance (audit fix 2026-10-01): N NIFTY strikes are converted with the SENSEX / NIFTY close
        # ratio of the sessions BEFORE the window, so no price after an entry day is used.
        for name in INDEX_INSTRUMENTS:
            if name != REFERENCE_INSTRUMENT and name not in PRE_RATIOS:
                try:
                    PRE_RATIOS[name] = await pre_window_ratio(up, name, frm)
                except (LookupError, SystemExit) as exc:
                    if name == instrument():
                        raise
                    print(f"  ! {name}: no close ratio before {frm} ({exc}) - its strike distance is not stated")
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
            asia_r = asia_check(asia, d, side_opt)
            loc_dir = checks["close location"]
            rescue_ok = asia_r["tag"] == ASIA_AGAINST and loc_dir >= STRONG_CLOSE
            close_tag = (f"strong (>= {STRONG_CLOSE})" if loc_dir >= STRONG_CLOSE
                         else f"middle ({MIDDLE_CLOSE[0]}-{MIDDLE_CLOSE[1]})" if loc_dir >= MIDDLE_CLOSE[0] else "weak (< 0.5)")
            asia_note = (f"{asia_r['agree']} of {asia_r['open']} Asian markets moved with the day"
                         if asia_r["open"] else "no Asian market open")
            iv = ivix.get(d)
            reverse_pre = checks["day move %"] >= REVERSE_MOVE and iv is not None and iv >= REVERSE_IVIX
            iv_tag = "unknown" if iv is None else bucket(iv, [12, 14, 17], ["below 12", "12-14", "14-17", "17 and above"])
            us_closed = us_span is not None and us_span[0] <= d <= us_span[1] and d not in us_days
            holiday = asia_r["open"] < ASIA_MIN_OPEN or us_closed
            holiday_why = ("Asia thin" if asia_r["open"] < ASIA_MIN_OPEN else "") + (" + " if asia_r["open"] < ASIA_MIN_OPEN and us_closed else "") + ("US shut tonight" if us_closed else "")
            base.update({ASIA_TAG: asia_r["tag"], "Asian markets open": asia_r["open"],
                         "Asian markets with the day": asia_r["agree"], IVIX_TAG: iv,
                         HOLIDAY_TAG: holiday_why if holiday else "no"})
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
                strike = strike_at(spot, steps, side_opt)
                # The DAY-SIDE option is read only for its 15:19 price (entry 5's time value).  Missing or not
                # positive: entry 5 is false and the night is judged on the other entries.  Whether a contract
                # exists and traded at 15:20 matters only for the option actually BOUGHT, checked after the
                # decision (audit fixes 2026-10-01).
                c_day = await up.resolve_option(key, expiry, strike, side_opt)
                orows_day = await up.option_candles(c_day, date.fromisoformat(d)) if c_day else []
                ob = {r[0]: r for r in orows_day}
                prem = ob[READ_MIN][4] if READ_MIN in ob and ob[READ_MIN][4] > 0 else None
                intrinsic = (spot - strike) if side_opt == "CE" else (strike - spot)
                share = (prem - intrinsic) / prem if prem else None   # A3, the DAY's side - scenario E reads it
                day_leg = {"symbol": c_day["trading_symbol"] if c_day else None, "strike": strike, "prem": prem,
                           "intrinsic": intrinsic, "share": share}
                c, orows = c_day, orows_day
                scen = dict(checks["scen"], E=checks["late pull-back"] and share is not None and share <= TV_MAX_SHARE)
                fired = [k for k in "ABCDEF" if scen[k]]
                scen_ok = bool(fired)
                reverse_ok = reverse_pre if ENTRY_MODE == "8" else (not scen_ok and not rescue_ok and reverse_pre)
                entry_true = {"1": scen["A"], "2": scen["B"], "3": scen["C"], "4": scen["D"], "5": scen["E"],
                              "6": scen["F"], "7": rescue_ok, "8": reverse_pre}
                rule_ok = scen_ok or rescue_ok or reverse_ok
                why = WHY_SCEN if scen_ok else (WHY_RESCUE if rescue_ok else (WHY_REVERSE if reverse_ok else WHY_NO))
                trade_side = side_opt
                if reverse_ok:
                    # THE REVERSE: the opposite side, the same depth ITM for THAT side, its own 15:19 / 15:20 bars.
                    # Only this contract is priced tonight, so 'every night' carries the reverse on these nights.
                    trade_side = "PE" if side_opt == "CE" else "CE"
                    strike = strike_at(spot, steps, trade_side)
                    c = await up.resolve_option(key, expiry, strike, trade_side)
                    orows = await up.option_candles(c, date.fromisoformat(d)) if c else []
                    obb = {r[0]: r for r in orows}
                    prem = obb[READ_MIN][4] if READ_MIN in obb and obb[READ_MIN][4] > 0 else None
                    intrinsic = (spot - strike) if trade_side == "CE" else (strike - spot)
                    share = (prem - intrinsic) / prem if prem else None   # the BOUGHT option's - display only
                # The option BOUGHT must exist, carry a lot size and have traded in the 15:20 minute (step 8).
                entry_bar, no_buy = None, None
                if c is None:
                    no_buy = f"the contract {expiry} {strike:.0f} {trade_side} does not exist"
                elif LOTS * c["lot_size"] <= 0:
                    no_buy = f"the contract {c['trading_symbol']} carries no lot size"
                else:
                    entry_bar = bar_after_candle(orows, READ_MIN, 1)  # 15:20, strict
                    if entry_bar is None:
                        no_buy = f"the option {c['trading_symbol']} did not trade in the 15:20 minute: nothing to buy at"
                if no_buy:
                    skips.append(f"{tag}: {no_buy}")
                    if steps == chart_rung:
                        wanted = rule_ok if ENTRY_MODE is None else bool(entry_true[ENTRY_MODE])
                        decided = holiday or not wanted
                        seen = {"status": "declined" if decided else "no data", "facts": dict(base),
                                "note": (f"holiday night ({holiday_why}) - no trade; also " if holiday and wanted else
                                         ("no entry is true" if ENTRY_MODE is None else f"entry {ENTRY_MODE} is FALSE")
                                         + " - no trade; also " if not wanted else "") + no_buy}
                    continue
                qty = LOTS * c["lot_size"]
                xrows = await up.option_candles(c, date.fromisoformat(exit_day))
                if not xrows:
                    skips.append(f"{tag}: option bars for exit day {exit_day} missing ({c['trading_symbol']})")
                    if steps == chart_rung:
                        seen = {"status": "no data", "facts": dict(base),
                                "note": f"the option has no bars on the exit day {exit_day}"}
                    continue
                line = breakeven_line(entry_bar[2], qty, d, exit_day)    # BUY at the bar's HIGH; A6
                tv_pts = None if prem is None else prem - intrinsic
                tv_tag = bucket(None if share is None else share * 100, [0, 5, 10, 15.0000001],
                                ["below intrinsic", "0-5%", "5-10%", "10-15%", "above 15%"])
                tvc = {"tv vs share": NO_RANK if share is None else PASS_SHARE if share <= TV_MAX_SHARE else FAIL_SHARE,
                       "tv vs points": NO_RANK if tv_pts is None else
                       PASS_PTS if tv_pts <= TV_MAX_POINTS * PRE_RATIOS.get(instrument(), 1.0) else FAIL_PTS}
                if share is not None:
                    tvc["tv share value"] = f"{share:.6f}"         # carrier for add_rank_tags
                if steps == chart_rung:
                    seen = {
                        "status": "traded" if rule_ok else "declined",
                        "note": (f"bought {c['trading_symbol']} in the 15:20 minute - scenario {'+'.join(fired)}"
                                 if scen_ok else
                                 f"bought {c['trading_symbol']} in the 15:20 minute - Asia rescue: {asia_note}, "
                                 f"close location {loc_dir:.2f}" if rescue_ok else
                                 f"bought {c['trading_symbol']} in the 15:20 minute - REVERSE, the opposite side: day "
                                 f"move {checks['day move %']:.2f}%, India VIX {iv:.1f}, no scenario, no rescue" if reverse_ok else
                                 f"no scenario A-F, no Asia rescue ({asia_r['tag']}: {asia_note}; close "
                                 f"location {loc_dir:.2f}), no reverse (day move {checks['day move %']:.2f}%, India VIX "
                                 f"{'unknown' if iv is None else f'{iv:.1f}'}) - the trade exists, set the direction check "
                                 f"to off to count it"),
                        "facts": dict(base, **{"direction": ("up day" if side_opt == "CE" else "down day")
                                                            + f": buy {trade_side}",
                                               "side": trade_side, "strike": strike, "premium 15:19": prem,
                                               "intrinsic": intrinsic,
                                               "time value": None if prem is None else prem - intrinsic,
                                               "tv % of premium (option bought)": None if share is None else share * 100,
                                               "tv % of the day-side option (entry 5 reads this)":
                                                   None if day_leg["share"] is None else day_leg["share"] * 100})}
                    if holiday and rule_ok:      # the rule never trades a holiday night; the trade exists for 'every night'
                        seen["status"] = "declined"
                        seen["note"] = (f"holiday night ({holiday_why}) - the rule does not trade it; would have "
                                        + seen["note"].replace("bought", "bought", 1))
                    if ENTRY_MODE is not None:   # this report is ONE entry alone
                        on = bool(entry_true[ENTRY_MODE])
                        seen["status"] = "traded" if on and not holiday else "declined"
                        seen["note"] = (f"entry {ENTRY_MODE} is FALSE - no trade" if not on else
                                        f"entry {ENTRY_MODE} is TRUE, but it is a holiday night ({holiday_why}) - no trade"
                                        if holiday else
                                        f"entry {ENTRY_MODE} is TRUE - bought {c['trading_symbol']} in the 15:20 minute")
                    DETAILS[d] = dict(day=d, exit_day=exit_day, side_day=side_opt, o915=o915, c1514=c1514, checks=checks,
                                      scen=scen, asia=asia_r, iv=iv, us_closed=us_closed, holiday=holiday,
                                      holiday_why=holiday_why, spot=spot, day_leg=day_leg, fired=fired, why=why,
                                      rule_ok=rule_ok, trade_side=trade_side, strike=strike, expiry=str(c["expiry"]),
                                      symbol=c["trading_symbol"], paid=entry_bar[2], qty=qty, line=line,
                                      tv_share=share, rescue_ok=rescue_ok, reverse_ok=reverse_ok)
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
                        target=round(line, 2), mfe=mfe, mae=mae, expiry=c["expiry"], option_type=trade_side,
                        variant={"moneyness": steps, "first_exit": first},
                        tags={"direction": ("up day" if side_opt == "CE" else "down day") + f": buy {trade_side}",
                              SIDE_TAG: AGAINST_DAY if reverse_ok else WITH_DAY, IVIX_TAG: iv_tag,
                              HOLIDAY_TAG: "yes" if holiday else "no",
                              **{entry_tag(k): "yes" if v else "no" for k, v in entry_true.items()},
                              TREND_TAG: checks[TREND_TAG], RULE_TAG: "yes" if rule_ok else "no", WHY_TAG: why,
                              ASIA_TAG: asia_r["tag"], CLOSE_TAG: close_tag,
                              SCEN_TAG: "+".join(fired) if fired else "none",
                              **{SCEN_LABEL[k]: "yes" if scen[k] else "no" for k in "ABCDEF"},
                              "time value": tv_tag, **tvc},
                        levels=[{"name": "09:15 open", "price": o915},
                                {"name": "15:14 close", "price": c1514},
                                {"name": "strike", "price": strike}],
                        note=f"{rung_label(steps)}; "
                             + (f"time value {share * 100:.1f}% of the 15:19 premium {prem:.2f} (intrinsic "
                                f"{intrinsic:.2f})" if share is not None else "no 15:19 option price, so no time value")
                             + (f"; the day-side option's time value (entry 5) {day_leg['share'] * 100:.1f}%"
                                if reverse_ok and day_leg["share"] is not None else "")
                             + f"; sell-line (paid + costs, sale tax at the {exit_day} rate) {line:.2f} drawn as "
                               f"'target'; exits scanned from {first}"))
                    if steps == chart_rung and first == rule_first and d in DETAILS:
                        lows = [r for r in xrows if first <= r[0] < TIME_EXIT]
                        best = max(lows, key=lambda r: r[3]) if lows else None
                        DETAILS[d].update(trigger=ex["trigger"], exit_bar=exit_bar, exit_reason=ex["reason"],
                                          gross=trades[-1]["gross"], costs=trades[-1]["costs"], net=trades[-1]["net"],
                                          best_low=best)
                if steps == chart_rung:      # only the charted rung is kept: holding all seven
                    sym = c["trading_symbol"]    # cost 365 MB of RAM for charts build_payload drops
                    option_sessions.setdefault(sym, {})[d] = orows
                    option_sessions[sym][exit_day] = xrows
            log.append(session_row(d, seen["status"], seen["note"], **seen["facts"]))
        add_rank_tags(trades)
        print(f"upstox calls: {up.calls}, paced {up.paced / 60:.1f} min to stay inside the rate limit"
              + (f", rate-limited {up.throttled} times (gap now {up._min_interval:.2f}s)" if up.throttled else ""))
    return trades, skips, log, full, option_sessions, info


DETAILS: dict[str, dict] = {}      # per night at the rule's own strike: every number the rule read (worked examples)


def _depth(name: str) -> tuple[float, int]:
    """(strike step, strikes in the money) of the rule's 6-NIFTY-strike depth on index `name`."""
    step = strike_step(name)
    if name == REFERENCE_INSTRUMENT:
        return step, 6
    if name not in PRE_RATIOS:
        raise LookupError(f"{name}: no close ratio before the window")
    return step, round(6 * REFERENCE_STEP * PRE_RATIOS[name] / step)


def _day(d: str) -> str:
    return date.fromisoformat(d).strftime("%a %d %b %Y")


def _n(x, d: int = 2) -> str:
    return "-" if x is None else f"{x:,.{d}f}"


def _tf(b: bool) -> str:
    return "TRUE" if b else "FALSE"


# THE 8 ENTRY POINTS (the user, 2026-10-01).  Each entry has TWO parts joined by AND; the night is entered if AT LEAST
# ONE entry is true (OR).  Entries 1-7: UP day buy CE, DOWN day buy PE.  Entry 8 is checked only when 1-7 are all
# false, and buys the other way: UP day buy PE, DOWN day buy CE.  1-6 are scenarios A-F, 7 the Asia read, 8 the
# opposite-side read.  `check_entry_points` proves on every night that these parts give exactly the code's trades.
#   (number, short name, part 1 words, part 2 words, part 1 key, part 2 key, buys with the day?)
ENTRY_POINTS = [
    ("1", "scenario A", "the 5-day trend agrees", "the range is normal", "trend", "normal", True),
    ("2", "scenario B", "a strong close", "the range is normal", "strong", "normal", True),
    ("3", "scenario C", "a small day", "the range is normal", "small", "normal", True),
    ("4", "scenario D", "a small day", "a late pull-back", "small", "pull", True),
    ("5", "scenario E", "a late pull-back", f"time value {TV_MAX_SHARE * 100:.0f}% or less", "pull", "tv", True),
    ("6", "scenario F", "a small day", "a middle close", "small", "middle", True),
    ("7", "Asia", "at most half of the Asian markets moved our day's way", "a strong close", "asia", "strong", True),
    ("8", "opposite side", f"the day moved {REVERSE_MOVE}% or more", f"India VIX at 15:19 is {REVERSE_IVIX:.0f} or more",
     "move", "vix", False),
]


def _parts(x: dict) -> dict[str, tuple[bool, str]]:
    """Every part an entry can use, for one night: (true or false, the numbers behind it)."""
    ck, c = x["checks"], x["c1514"]
    loc, a, dl = ck["close location"], x["asia"], x["day_leg"]
    rng = ck["hi"] - ck["lo"]
    return {
        "trend": (ck[TREND_TAG] == AGREES,
                  f"close {_n(c)} vs {_n(ck['trend ref'])} {TREND_N} sessions earlier" if ck["trend ref"] is not None
                  else "no history yet"),
        "normal": (bool(ck["normal"]), f"range {_n(rng)} / average {_n(ck['avg range'])} = {ck['range ratio']:.2f}"
                   if ck["avg range"] else "no 20-session average yet"),
        "strong": (loc >= STRONG_CLOSE, f"close location {loc:.2f}"),
        "middle": (MIDDLE_CLOSE[0] <= loc < MIDDLE_CLOSE[1], f"close location {loc:.2f}"),
        "small": (bool(ck["small"]), f"moved {ck['day move %']:.2f}%"),
        "pull": (bool(ck["late pull-back"]), f"14:59 {_n(ck['late close'])} -> 15:14 {_n(c)}"),
        "tv": (dl["share"] <= TV_MAX_SHARE, f"time value {dl['share'] * 100:.1f}%"),
        "asia": (a["open"] >= ASIA_MIN_OPEN and a["agree"] / a["open"] <= ASIA_MAX_AGREE,
                 f"{a['agree']} of {a['open']} Asian markets moved our way"),
        "move": (ck["day move %"] >= REVERSE_MOVE, f"moved {ck['day move %']:.2f}%"),
        "vix": (x["iv"] is not None and x["iv"] >= REVERSE_IVIX, f"India VIX {_n(x['iv'])}"),
    }


def _entry_true(x: dict, e: tuple) -> bool:
    p = _parts(x)
    return p[e[4]][0] and p[e[5]][0]


def _entries(x: dict) -> tuple[list[str], bool]:
    """(numbers of entries 1-7 that are true, is entry 8 true) - entry 8 counts only when 1-7 are all false."""
    ones = [e[0] for e in ENTRY_POINTS[:7] if _entry_true(x, e)]
    return ones, (not ones) and _entry_true(x, ENTRY_POINTS[7])


def _buy(up: bool, with_day: bool) -> str:
    return "CE" if up == with_day else "PE"


def check_entry_points() -> None:
    """The written entries must give EXACTLY the code's decision on every night - stop the run otherwise."""
    bad = []
    if ENTRY_MODE == "8":            # entry 8 run alone ignores 'only when 1-7 are false', so the rule's check does not apply
        return
    for d, x in DETAILS.items():
        if x["holiday"]:
            continue
        ones, eight = _entries(x)
        for e in ENTRY_POINTS[:6]:
            if _entry_true(x, e) != bool(x["scen"][e[1][-1]]):
                bad.append(f"{d} entry {e[0]}")
        if _entry_true(x, ENTRY_POINTS[6]) != bool(x["rescue_ok"]):
            bad.append(f"{d} entry 7")
        if eight != bool(x["reverse_ok"]) or bool(ones or eight) != bool(x["rule_ok"]):
            bad.append(f"{d} entry 8 / decision")
        if x["rule_ok"] and x["trade_side"] != _buy(x["side_day"] == "CE", bool(ones)):
            bad.append(f"{d} side")
    if bad:
        raise SystemExit(f"the written entry points disagree with the trades on {len(bad)} checks: {bad[:8]}")


def _long(d) -> str:
    """'2026-02-23' -> 'Monday 23 February 2026'."""
    return date.fromisoformat(str(d)[:10]).strftime("%A %d %B %Y")


def _entry_example(e: tuple, x: dict) -> str:
    """One entry on one real night, told in plain sentences: the day, why each part is true, then the trade."""
    num, name, w1, w2, k1, k2, with_day = e
    ck, up = x["checks"], x["side_day"] == "CE"
    o, c = x["o915"], x["c1514"]
    loc, a, dl = ck["close location"], x["asia"], x["day_leg"]
    rng = ck["hi"] - ck["lo"]
    day_word = "UP" if up else "DOWN"
    way = "up" if up else "down"

    def why(k: str) -> str:
        if k == "trend":
            return (f"The 15:14 close {TREND_N} sessions earlier ({_long(ck['trend ref day'])}) was {_n(ck['trend ref'])}; today's "
                    f"{_n(c)} is {'higher' if c > ck['trend ref'] else 'lower'}, so the 5-day trend agrees with the day.")
        if k == "normal":
            return (f"Today's range was {_n(ck['hi'])} - {_n(ck['lo'])} = {_n(rng)} points, and the average of the last "
                    f"{RANGE_N} sessions was {_n(ck['avg range'])}. {_n(rng)} / {_n(ck['avg range'])} = {ck['range ratio']:.2f}, "
                    f"which is between {RANGE_BAND[0]} and {RANGE_BAND[1]}, so the range is normal.")
        if k in ("strong", "middle"):
            pos = (f"({_n(c)} - {_n(ck['lo'])}) / {_n(rng)}" if up else f"({_n(ck['hi'])} - {_n(c)}) / {_n(rng)}")
            return (f"The close sat at {pos} = {loc:.2f} of today's range, counted for {'an' if up else 'a'} {way} day. "
                    + (f"That is {STRONG_CLOSE} or more, so it is a strong close." if k == "strong" else
                       f"That is from {MIDDLE_CLOSE[0]} up to {MIDDLE_CLOSE[1]}, so it is a middle close."))
        if k == "small":
            return (f"The close was {_n(abs(c - o))} points from the open: {_n(abs(c - o))} / {_n(o)} x 100 = "
                    f"{ck['day move %']:.2f}%, under {SMALL_MOVE}%, so it is a small day.")
        if k == "pull":
            lc = ck["late close"]
            moved = ("did not move" if c == lc else f"went {'up' if c > lc else 'down'} {_n(abs(c - lc))} points")
            return (f"From the 14:59 close ({_n(lc)}) to the 15:14 close ({_n(c)}) the index {moved}"
                    + (", against the day" if c != lc else "") + ", so there was a late pull-back.")
        if k == "tv":
            return (f"The {'CE' if up else 'PE'} for the day (strike {_n(dl['strike'], 0)}) cost {_n(dl['prem'])} at 15:19 and "
                    f"was worth {_n(dl['intrinsic'])} if used right then. Time value = ({_n(dl['prem'])} - "
                    f"{_n(dl['intrinsic'])}) / {_n(dl['prem'])} = {dl['share'] * 100:.1f}%, which is "
                    f"{TV_MAX_SHARE * 100:.0f}% or less."
                    + (" (Below zero means the option was trading a little under its worth-now value.)"
                       if dl["share"] < 0 else ""))
        if k == "asia":
            moves = ", ".join(f"{m} {v:+.2f}%" for m, v in a["moves"].items())
            return (f"Asia today (each market's close against its previous close): {moves}. {a['agree']} of the "
                    f"{a['open']} markets that traded moved {way} like our day, which is at most half.")
        if k == "move":
            return f"The day moved {ck['day move %']:.2f}%, which is {REVERSE_MOVE}% or more."
        if k == "vix":
            return f"India VIX at 15:19 was {_n(x['iv'])}, which is {REVERSE_IVIX:.0f} or more."
        return ""

    ones = _entries(x)[0]
    others = [o_ for o_ in ones if o_ != num]
    ts = x["trade_side"]
    atm = atm_strike(x["spot"], STEP)
    lines = [
        f"{date.fromisoformat(x['day']).strftime('%A %d %B %Y')}, {instrument()}.",
        f"The index opened at {_n(o)} at 09:15 and was at {_n(c)} at 15:14 - {'higher' if up else 'lower'}, so it was "
        f"{'an' if up else 'a'} {day_word} day. {a['open']} of the 5 Asian markets traded today and the US market was open "
        "tonight, so it was not a holiday night.",
    ]
    if num == "8":
        lines.append("Entries 1 to 7 were all false, so entry 8 was checked.")
    lines += [why(k1), why(k2), f"Both conditions are true, so entry {num} is true."
              + (f" Entr{'y' if len(others) == 1 else 'ies'} {', '.join(others)} {'was' if len(others) == 1 else 'were'} "
                 "also true that night; it is still one trade." if others else "")]
    lines.append(
        (f"{'An' if up else 'A'} {day_word} day, so we buy a {ts}. " if with_day else
         f"{'An' if up else 'A'} {day_word} day, but entry 8 buys the other way round, so we buy a {ts}. ")
        + f"The index's 15:19 close was {_n(x['spot'])}; rounded, the at-the-money strike is {_n(atm, 0)}; "
        f"{_n(abs(x['strike'] - atm), 0)} points {'below' if ts == 'CE' else 'above'} it is {_n(x['strike'], 0)}. "
        f"The next session was {_long(x['exit_day'])}, so the expiry is {_long(x['expiry'])}. We bought {x['symbol']} in the 15:20 "
        f"minute at {_n(x['paid'])} for {x['qty']} units (Rs {_n(x['paid'] * x['qty'], 0)}). With all costs the "
        f"sell-line was {_n(x['line'])}.")
    if "exit_bar" in x:
        eb, tg = x["exit_bar"], x.get("trigger")
        if tg:
            lines.append(f"On {_long(x['exit_day'])} the {tg[0]} candle's low ({_n(tg[3])}) was above the sell-line, so we sold "
                         f"in the {eb[0]} minute at {_n(eb[3])}.")
        else:
            bl = x.get("best_low")
            lines.append(f"On {_long(x['exit_day'])} no candle's low got above the sell-line"
                         + (f" (the best was {_n(bl[3])} at {bl[0]})" if bl else "")
                         + f", so we sold in the 15:14 minute at {_n(eb[3])}.")
        lines.append(f"Result after costs: Rs {x['net']:+,.0f} ({'a profit' if x['net'] > 0 else 'a loss'}).")
    return "\n".join(lines)


def rule_sections(with_examples: bool = True) -> list[dict]:
    """THE RULE for the rule-only report (the user, 2026-10-01: "remove everything, just explain the strategy in steps in
    plain English in detail, then give an example for each entry").  `check_entry_points` runs first, so the steps and
    entries below are proven to give exactly the report's trades."""
    check_entry_points()
    nstep, nn = _depth("NIFTY")
    try:
        sstep, sn = _depth("SENSEX")
        rnd, below = f"the nearest {nstep:.0f} (SENSEX: {sstep:.0f})", f"{nn * nstep:,.0f} points (SENSEX: {sn * sstep:,.0f})"
    except Exception:
        rnd, below = f"the nearest {nstep:.0f}", f"{nn * nstep:,.0f} points"
    steps = {"title": "The strategy, step by step", "items": [
        "Wait for the 15:14 candle to finish. Everything is decided from the index's 1-minute candles that have finished "
        "by 15:14, plus two prices read from the 15:19 candle: the option's price and India VIX.",
        "Find the day's direction. Compare the index's 15:14 close with its 09:15 open. If the close is higher, it is an "
        "UP day. If it is lower, it is a DOWN day. If they are exactly the same, there is no trade today.",
        "Check for a holiday night. There are two checks, and both come from the holiday calendars, so you know them "
        "days in advance.\n"
        "- Asia: look at the five Asian markets - Nikkei 225 (Japan), Hang Seng (Hong Kong), KOSPI (Korea), Shanghai "
        "(China) and ASX 200 (Australia). A market 'traded today' if it had a normal session today, not a local "
        f"holiday. If fewer than {ASIA_MIN_OPEN} of the 5 traded today, there is no trade today.\n"
        "- US: we hold the option overnight, and tonight's US session (New York 09:30 to 16:00, which is 19:00 to 01:30 "
        "India time in the US summer and 20:00 to 02:30 in the US winter) is the main thing that moves our index's "
        "opening price tomorrow. If the US market is closed tonight, there is no trade today. In this backtest that "
        "happened on 1 January (New Year), 19 January (Martin Luther King Day), 16 February (Presidents' Day), 25 May "
        "(Memorial Day), 19 June (Juneteenth) and 3 July (Independence Day), plus Sunday 1 February (India's Budget-day "
        "session, a weekend in the US).\n"
        "Why skip these nights: with the region or the US shut there is little to carry the index overnight, so the "
        "option rarely gets far above the sell-line by the next morning. The losses are normal size, the wins are tiny. "
        "(Each index's holiday-night results in this backtest are in the assumptions.)",
        "Work out these facts about today:\n"
        f"- Small day: the 15:14 close is less than {SMALL_MOVE}% away from the 09:15 open, up or down. (Open 25,000: a "
        "close between 24,925 and 25,075.)\n"
        f"- Normal range: today's high minus low, from 09:15 to 15:14, is at least {RANGE_BAND[0]} times and less than "
        f"{RANGE_BAND[1]} times the average high-minus-low of the last {RANGE_N} sessions.\n"
        "- Close location: where the 15:14 close sits inside today's range, from 0 to 1. On an UP day 0 is the day's low "
        "and 1 is its high; on a DOWN day 0 is the high and 1 is the low. A STRONG close is "
        f"{STRONG_CLOSE} or more; a MIDDLE close is from {MIDDLE_CLOSE[0]} up to {MIDDLE_CLOSE[1]}.\n"
        f"- The 5-day trend agrees: on an UP day, today's 15:14 close is higher than the 15:14 close {TREND_N} sessions "
        "ago; on a DOWN day, lower.\n"
        "- Late pull-back: from the 14:59 close to the 15:14 close the index moved against the day, or did not move.\n"
        "- Time value: take the option you would buy for the day (a CE on an UP day, a PE on a DOWN day, chosen as in "
        "step 7) and its 15:19 price. Subtract what it is worth if used right now (index minus strike for a CE, strike "
        "minus index for a PE), and divide by the price. (If that option did not trade at 15:19, there is no time "
        "value, so entry 5 cannot be true.)\n"
        "- Asia: for each of the five Asian markets that traded today, compare today's closing price with that "
        "market's previous closing price. Higher = it went UP today. Lower = it went DOWN. All five close by 13:30 India "
        "time, so this is known well before 15:14. A market 'moved our way' if it went up on our UP day, or down on our "
        "DOWN day (no change counts as not our way). Asia never decides our direction - only the index's own day does "
        "(step 2). Asia is used in only two places: step 3 (how many traded today) and entry 7 (how many moved our way).\n"
        "- India VIX: its value at 15:19.",
        "Check entries 1 to 7. Each entry needs BOTH of its two conditions to be true. If at least one of these seven "
        "entries is true, buy a CE on an UP day or a PE on a DOWN day. If two or more are true, it is still one trade.\n"
        "- Entry 1: the 5-day trend agrees, and the range is normal.\n"
        "- Entry 2: a strong close, and the range is normal.\n"
        "- Entry 3: a small day, and the range is normal.\n"
        "- Entry 4: a small day, and a late pull-back.\n"
        f"- Entry 5: a late pull-back, and time value of {TV_MAX_SHARE * 100:.0f}% or less.\n"
        "- Entry 6: a small day, and a middle close.\n"
        "- Entry 7: at most half of the Asian markets that traded today moved our way, and a strong close. 'At most half' "
        "means: with 5 traded, 0, 1 or 2 moved our way; with 4 traded, 0, 1 or 2 moved our way.\n"
        "  Example - 3 Asian markets went down and 2 went up. On a DOWN day, 3 of 5 moved our way: that is more than "
        "half, so entry 7 is false. On an UP day, 2 of 5 moved our way: that is at most half, so this part is true - and "
        "the index must also have a strong close for entry 7 to be true.\n"
        "  Why: when Asia went the other way and our index still closed near its best point, the index's own move "
        "tended to carry on overnight.",
        f"Only if entries 1 to 7 are all false, check entry 8: the day moved {REVERSE_MOVE}% or more, and India VIX at "
        f"15:19 is {REVERSE_IVIX:.0f} or more. If both are true, buy the other way round: a PE on an UP day, a CE on a "
        "DOWN day. If entry 8 is false too, there is no trade today.",
        f"Choose the contract. Round the index's 15:19 close to {rnd}: that is the at-the-money strike. For a CE go "
        f"{below} below it; for a PE go the same distance above it. Use the nearest expiry that is at least one day "
        "after tomorrow's session.",
        "Buy one lot in the 15:20 minute. (The backtest assumes you paid the highest price of that minute.) If the "
        "option did not trade at all in the 15:20 minute, the backtest has nothing to buy at, so there is no trade "
        "that night.",
        "Work out the sell-line: the price you paid plus all the costs of buying and selling (brokerage, taxes and "
        "exchange charges), per unit. The sale tax is charged at the rate in force on the day you sell: 0.10% of the "
        "premium until 31 March 2026, 0.15% from 1 April 2026. Above the sell-line the trade is in profit after costs.",
        "The next day, from the 09:30 candle onward, watch each 1-minute candle. As soon as a candle's lowest price is "
        "above the sell-line, sell in the next minute. (The backtest assumes you got the lowest price of that minute.)",
        f"If no candle gets above the sell-line by {TIME_EXIT}, sell in the {TIME_EXIT} minute. There is no stop-loss and "
        "no profit target."]}
    out = [steps]
    if not with_examples:
        return out
    nights = [x for d, x in sorted(DETAILS.items()) if not x["holiday"] and "exit_bar" in x]
    for e in ENTRY_POINTS:
        num, name, w1, w2 = e[:4]
        hits = [x for x in nights if (_entries(x)[1] if num == "8" else _entry_true(x, e))]
        if not hits:
            continue
        alone = [x for x in hits if len(_entries(x)[0]) <= 1]
        out.append({"title": f"Example - entry {num}: {w1} AND {w2}", "text": _entry_example(e, (alone or hits)[0])})
    return out


def holiday_note() -> str:
    """This index's holiday nights on which an entry was true, from its own trades (the rule's strike, first exit 09:30):
    what trading them would have made.  Written with this index's name, so each index shows its own line."""
    hol = [x for x in DETAILS.values() if x["holiday"] and x["rule_ok"] and x.get("net") is not None]
    book = [x for x in DETAILS.values() if x["rule_ok"] and x.get("net") is not None]
    if not hol:
        return f"HOLIDAY NIGHTS ({instrument()}): no entry was true on a holiday night in this window."
    w = [x["net"] for x in hol if x["net"] > 0]
    l = [x["net"] for x in hol if x["net"] <= 0]
    worst = sorted(book, key=lambda x: x["net"])[:6]
    return (f"HOLIDAY NIGHTS ({instrument()}): an entry was true on {len(hol)} holiday nights, which the rule skips. "
            f"Traded, they would have made {len(w)} wins"
            + (f" (Rs {sum(w) / len(w):,.0f} on average)" if w else "")
            + f" and {len(l)} losses" + (f" (Rs {-sum(l) / len(l):,.0f} on average)" if l else "")
            + f", Rs {sum(x['net'] for x in hol):+,.0f} in total; {sum(1 for x in worst if x['holiday'])} of the "
            f"{len(worst)} biggest losses among all nights with a true entry were holiday nights.")


def plain_steps() -> list[str]:
    """The rule-only report's steps (meta['rule_steps']): the 11 plain steps of `rule_sections`, line breaks kept, no
    examples (the user, 2026-10-01).  `rule_sections` runs `check_entry_points` first."""
    return rule_sections(with_examples=False)[0]["items"]


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
    ap.add_argument("--entry", dest="entry", default=None,
                    help="1 to 8: run that ONE entry alone as its own strategy; writes analysis/onh_v4_entries/")
    ap.add_argument("--rule-only", dest="rule_only", action="store_true",
                    help="write onh_v4_rule.html: the rule alone (6 ITM, direction check on, no time-value check, "
                         "first exit 09:30), with only its own steps and assumptions - no panel comparisons")
    a = ap.parse_args()
    if ENTRY_MODE is not None:
        a.rule_only = True               # one strike, one exit candle, the compact assumptions
    if a.rule_only:
        a.set_confirm, a.set_tv_check, a.set_first_exit = "rule", "off", "09:30"
        a.set_moneyness = a.set_moneyness or "6"
    if a.set_moneyness is None:
        a.set_moneyness = DEFAULT_LADDER
        print(f"strike ladder defaulting to {DEFAULT_LADDER} (6 ITM to 6 OTM)")
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
        "THE RULE is strike depth 6 ITM, the v4 rule (any of scenarios A-F, or the Asia rescue), time-value check "
        "OFF, first exit 09:30 - the panel's defaults. Every other setting is the SAME NIGHTS priced differently; "
        "'Direction check' offers only the rule and no check at all (the user, 2026-09-30: the v3 5-day-trend "
        "option was dropped from the panel; the trend still shows as a breakdown).",
        f"THE ASIA RESCUE (the user, 2026-09-30): a night with no scenario is traded when at least {ASIA_MIN_OPEN} of "
        f"the 5 Asian indices ({', '.join(ASIA.values())}) traded today, at most half of those open moved the same way "
        f"as the day (the region went AGAINST it), and the 15:14 close location is at least {STRONG_CLOSE} in the day's "
        f"direction. Fewer than {ASIA_MIN_OPEN} open (a regional holiday) is NO READ, never 'against', and it makes the "
        f"night a holiday night: no trade (see THE HOLIDAY SKIP). "
        f"Every one of the five closes is in before 13:30 IST, so the read is known at the 15:20 entry. On SENSEX the "
        f"same Asian closes are read against SENSEX's own day.",
        "ASIA DATA: daily bars from Yahoo Finance's chart API, placed on local disk as "
        "analysis/candle_datas/yahoo_<ticker>_daily.json (fetched 2026-09-30, 2025-11-03 to 2026-08-14; "
        "each file carries its source URL and fetch time), read by py_funcs.yahoo_daily - nothing is fetched by "
        "this run. The Yahoo NIFTY close was checked against the local Upstox candles on 152 sessions (median 1.4 "
        "points). A day missing from a market's file is a day that market did not trade.",
        f"THE REVERSE (the user, 2026-09-30, 'add it first, decide later'): a night with no scenario and no rescue, "
        f"a day move of at least {REVERSE_MOVE}% (15:14 close vs 09:15 open) and India VIX at least {REVERSE_IVIX:.0f} "
        f"buys the OPPOSITE side - a put on an up day, a call on a down day - the same strikes ITM for that side, "
        f"same 15:20 entry and the same exit. Only the reverse contract is priced on such a night, so 'no check - "
        f"every night' carries the reverse trade there, not the day's side. Where it comes from: the 54 nights the "
        f"rule declined took the day's move back next morning (17 of 54 gapped against by more than 0.3%); the "
        f"opposite side on them made 77% won, PF 2.52, +1.46L, and reversing the rule's own 88 nights lost 4.97L. "
        f"With the day move and India VIX cuts: 93% / 91% won. THE MONEY IS MARCH-APRIL 2026 (India VIX 17-25); "
        f"outside that stretch the reverse earns scraps. One window, one regime - NOT stress-tested.",
        f"THE HOLIDAY SKIP (the user, 2026-09-30) is part of THE RULE: no trade on a night with fewer than "
        f"{ASIA_MIN_OPEN} of the 5 Asian markets open today or the US market shut "
        f"that night (a weekday with no S&P 500 bar in analysis/candle_datas/yahoo_GSPC_daily.json). Why: on NIFTY 3 of "
        f"the 6 heavy losers (worse than -8k) and on SENSEX 2 of 10 fell on such nights; skipping them (8 nights each) "
        f"raised NIFTY from PF 5.66 to 8.68 (+35k, both halves) and SENSEX from 2.98 to 3.42 (+19k). The session log "
        f"marks such nights 'declined' with the holiday named; 'no check - every night' still trades them. Holiday nights "
        f"lose the usual amount and win almost nothing: with the region or the US shut there is no session to carry "
        f"the move. Known days ahead from the holiday calendars. Every exit, stop, hedge and morning confirmation tried "
        f"(stops of 10-40%, index stops, time cuts, the 15:20-15:29 window, the 09:15 minute, OI and volume at entry, "
        f"far-OTM hedges) cost more than it saved on both indices - the loss is made in the 09:15 candle.",
        "THE PANEL KEEPS ONE VIEW THE RULE REJECTED (the user, 2026-09-30): 'Direction check' also offers the rule "
        "WITH holiday nights (the 103-trade book on NIFTY: PF 5.66, +5.26L, against 95 trades, PF 8.68, +5.62L without "
        "them). There is ONE exit (the user): the first candle low above the line from 09:30, else 15:14. A 14:00 cut "
        "was tried and dropped (about +1% on both indices overall, negative on both in May-July); every stop, time "
        "cut, morning confirmation, hedge and recovery exit tried lost money on both indices.",
        "DATA COMPLETED 2026-09-30 (with the user's permission): the index candles now run from 2025-11-24, so every "
        "January night has its 20-session range, and to 2026-08-07, so the last night of the window (2026-07-31) exits "
        "on 2026-08-03; the 4-Aug (NIFTY) and 6-Aug (SENSEX) expiry contracts the OTM rungs needed in the last week of "
        "July were fetched too. What remains as 'no data' is real: a deep strike whose 15:19 minute did not trade "
        "(a handful of SENSEX nights on the far rungs), which rule 6 refuses to fill.",
        "INDIA VIX is read from its own 1-minute candles (analysis/candle_datas/VIX_candles.json, NSE_INDEX|India VIX, "
        "fetched 2026-09-30): the 15:19 bar's close, the same minute the option price is read, so the reverse's "
        "input is known at the 15:20 entry. Until 2026-09-30 the day's 15:30 close was used - ten minutes after "
        "entry - and the look-ahead audit found it flipped the read on two nights (2 March fired only on the close, "
        "6 May would have fired on the previous close); the 15:19 read settles both without a proxy. A session with "
        "no India VIX bar near 15:19 cannot fire the reverse.",
        "WHERE THE RESCUE COMES FROM (scratchpad, 2026-09-30, NIFTY 6 ITM, worst fill, Jan-Jul 2026): 16 global "
        "factors known by 15:20 IST were tested on every night; none supported the nights scenarios A-F declined, and "
        "Asia's same-day direction ran the OTHER way. Declined nights with Asia against the day and a strong close: 19 "
        "trades, 79% won, PF 4.86, +0.79L (Jan-Apr 10 nights 90% won; May-Jul 9 nights 67% won, PF 1.47); with a "
        "middle or weak close: 10 nights, -0.34L. The rescue was chosen on THIS window, is one factor of 16, and has "
        "NOT been checked on the year before. Every morning cut or stop tried made every group worse.",
        f"ASSUMED: every input of scenarios A-F is read from candles complete by 15:14 - the 5-day trend (15:14 close vs "
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
        "build year's numbers as in-sample. The Asia rescue was not part of that stress test.",
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
        f"SELECTION: the six scenarios, the strike ({depth_text()} in the money) and 09:30 were chosen on data that "
        "includes this window. "
        "The ladder and the other settings are an in-sample comparison - the best cell of a grid is mostly "
        "noise, and nothing here is out of sample.",
        f"WINDOW: {START_DATE} to {END_DATE}, defined in py_funcs and shared by every strategy. The start is "
        f"fixed and the end is the current IST date when the script starts. Existing HTML is a snapshot. A wider run "
        f"(--from 2024-10-01, the floor for real option prices) is only done on request.",
        "Capital = premium x qty, so it differs by rung and return on capital is comparable across the ladder.",
        "THE LADDER runs 6 ITM through ATM to 6 OTM for this strategy (the user, 2026-09-30); the shared ladder of the "
        "other index strategies stops at ATM. An OTM rung has little or no intrinsic value, so the time-value checks "
        "refuse nearly every night there, and the sell-line (paid + costs) is a larger share of a small premium.",
        "Only nights with real option bars for both sessions are traded, per rung; the console lists every skip.",
    ]
    lot = trades[-1]["qty"] // LOTS if trades else info["lot_size"]
    slug = SLUG
    if a.rule_only:
        # THE RULE ALONE (the user, 2026-09-30): one report with only the rule's steps and assumptions.
        slug = SLUG + "_rule"
        limits = [
            "READS. Direction = the session's 09:15 open against its 15:14 close (1-minute bars). Every input of scenarios A-F "
            f"comes from candles complete by 15:14: the {TREND_N}-day trend (15:14 close vs the 15:14 close {TREND_N} "
            f"sessions earlier), today's 09:15-15:14 range against the average full-day range of the previous {RANGE_N} "
            f"sessions, the day's move, the close's location in the day's range, and the last {LATE_MIN} minutes. "
            "Scenario E also reads the option's 15:19 price.",
            f"STRIKE. Reference = the 15:19 index close; the strike is {depth_text()} in the money for the side "
            "bought; expiry = the nearest at least one day after the exit day, so a position never crosses an expiry.",
            "FILLS - WORST ONLY. Buy in the 15:20 minute at its HIGH. Next session, from the 09:30 candle, the first "
            "candle whose LOW is above the line sells in the NEXT minute at that minute's LOW; nothing by 15:14 sells "
            "in the 15:14 minute at its LOW. The line = paid + round-trip costs per unit, so a 'line' exit can still "
            "lose a little when the next minute dips under it. No stop, no target: every stop, time cut, morning "
            "confirmation, hedge and recovery exit tried lost money on both indices.",
            f"ASIA RESCUE. The five closes (Nikkei 225, Hang Seng, KOSPI, Shanghai, ASX 200) are daily bars from Yahoo "
            f"Finance on local disk, each in before 13:30 IST. It needs at least {ASIA_MIN_OPEN} of them open today, at "
            f"most half of those open moving the day's way, and a 15:14 close location of at least {STRONG_CLOSE} in "
            "the day's direction.",
            f"REVERSE. A day move of at least {REVERSE_MOVE}% and India VIX of at least {REVERSE_IVIX:.0f} with no "
            "scenario and no rescue buys the OPPOSITE side at the same depth. India VIX is its 15:19 one-minute close, "
            "read in the same minute as the option price - known at entry.",
            f"HOLIDAY NIGHT. No trade when fewer than {ASIA_MIN_OPEN} Asian markets were open today or the US market "
            "is shut tonight (no S&P 500 bar for the day). Both are known from the holiday calendars in advance.",
            "SIZE AND COSTS. One lot (the contract's lot size), one position at a time; brokerage, STT, exchange, stamp "
            "and GST at the broker's rates for the trade's own date; capital = premium x quantity. A 6-ITM option moves "
            "about one for one with the index, so a 1% gap against costs about 17k a lot whatever the strike.",
            holiday_note(),
            "DATA. Local 1-minute candles, Nov 2025 to Aug 2026, nothing fetched by this run. A deep strike whose 15:19 "
            "minute did not trade is 'no data' and never filled (a few SENSEX nights).",
            f"WINDOW AND HONESTY. {START_DATE} to {END_DATE}, 143 sessions. Scenarios A-F were built on Sep 2025-Sep 2026 "
            "and stress-tested on the year before it (PF 1.28 there against 2.74 in the build year). The Asia rescue, "
            "the reverse and the holiday skip were chosen on THIS window and have NOT been checked on the year before; "
            "the reverse's profit is March-April 2026. Read every number here as in-sample.",
        ]
    meta = {
        "title": "Over night Hold v4" + (" - the rule" if a.rule_only else ""),
        "subtitle": "Buy an ITM NIFTY weekly option at 15:20 on the day's direction when any of six scenarios "
                    "(A-F) fires, or when Asia moved against the day and the close is strong (the Asia rescue); "
                    "on a big day with India VIX 17+ and neither, buy the opposite side (the reverse); "
                    "sell next session at the first candle low above paid + costs, else 15:14. "
                    "Worst fill only. The panel prices every other setting on the same nights.",
        "instrument": "NIFTY 50 weekly options",
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": lot,
        "fill_rule": "WORST FILL ONLY: buy at the minute's HIGH, sell at the minute's LOW, entry and exit; "
                     "signals act in the next 1-minute bar",
        "params": {"signal": "09:15 open vs 15:14 close (1m)",
                   "the rule": f"{rule['moneyness']} strikes ITM, scenarios A-F, the Asia rescue or the reverse, no holiday nights, first exit "
                               f"{rule['first_exit']}, time-value check off",
                   "scenarios A-F": " | ".join(SCEN_LABEL[k] for k in "ABCDEF"),
                   "Asia rescue": f"no scenario, but >= {ASIA_MIN_OPEN} of {', '.join(ASIA.values())} open, at most "
                                  f"{ASIA_MAX_AGREE:.0%} of them with the day, close location >= {STRONG_CLOSE}; "
                                  f"fewer than {ASIA_MIN_OPEN} open = a holiday night, no trade",
                   "thresholds": f"normal range {RANGE_BAND[0]}-{RANGE_BAND[1]} x {RANGE_N}-day average; small day "
                                 f"< {SMALL_MOVE}%; strong close >= {STRONG_CLOSE}; middle close "
                                 f"{MIDDLE_CLOSE[0]}-{MIDDLE_CLOSE[1]}; pull-back = last {LATE_MIN} min; "
                                 f"trend {TREND_N} sessions; time value <= {TV_MAX_SHARE * 100:.0f}%",
                   "the reverse": f"no scenario, no rescue, day move >= {REVERSE_MOVE}%, India VIX >= "
                                  f"{REVERSE_IVIX:.0f} -> the opposite side, same depth ITM",
                   "direction checks": "v4 rule (scenarios A-F, Asia rescue, or the reverse; never on a holiday night) | the same rule with holiday nights | none",
                   "holiday night": f"fewer than {ASIA_MIN_OPEN} of 5 Asian markets open today, or the US shut tonight",
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
            "Trade tonight if ANY of these six scenarios fires:",
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
            f"No scenario fired? Trade anyway (the Asia rescue) if at least {ASIA_MIN_OPEN} of the 5 Asian indices "
            f"({', '.join(ASIA.values())}) traded today, at most half of those open moved the same way as the day, "
            f"and the 15:14 close is in the day's strongest {100 - STRONG_CLOSE * 100:.0f}%.",
            f"Fewer than {ASIA_MIN_OPEN} Asian indices open: no Asia read, and the night is a HOLIDAY NIGHT (below) - "
            "no trade.",
            f"No scenario and no rescue, but the day moved at least {REVERSE_MOVE}% and India VIX is at least "
            f"{REVERSE_IVIX:.0f}: buy the OPPOSITE side (a put on an up day, a call on a down day), the same strikes "
            "in the money for that side - the reverse.",
            f"A HOLIDAY NIGHT is never traded, whatever fired: fewer than {ASIA_MIN_OPEN} of the 5 Asian markets open "
            "today, or the US market shut tonight.",
            "Otherwise no trade.",
            f"Reference = index at 15:19 (close), strike = {depth_text()} in the money for the rule, "
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
            ["Choosing the OPPOSITE side on EVERY night", "tested in the scratchpad study (2022-2026, 74 rules): no signal "
             "reliably picked the other side across all nights; on this window the reverse of every night loses 3.5L. "
             "The reverse is only taken on the nights the rule declines, a big day on a nervous tape (see limits)."],
            ["A stop or a profit target", "the prompt says neither, and adding one here would be a different rule "
             "chosen on the same history."],
            ["Holding more than one night", "the rule sells on the next session; a multi-night hold changes the "
             "expiry choice and is not comparable."],
            ["Selling the option instead of buying", "capital would be a margin estimate rather than the premium, "
             "so return on capital would not be comparable with the rungs shown."],
        ],
        "coverage": coverage(sessions, frm, to, ROWS_PER_SESSION),
        "rerun": rerun_command(SLUG, settings, frm.isoformat(), to.isoformat()) + (" --rule-only" if a.rule_only else ""),
    }
    meta["price_ratio"] = dict(PRE_RATIOS)
    meta["price_ratio_basis"] = (f"the median close ratio of the {TREND_LOOKBACK_DAYS} calendar days before {frm} "
                                 "(known before the first trade)")
    if a.rule_only:
        meta["rule_steps"] = plain_steps()     # the steps only, inside the settings-and-assumptions section
        meta["subtitle"] = ("The rule alone, 6 strikes in the money, bought at 15:20. Enter when at least one of entries 1-7 "
                            "is TRUE (UP day: buy CE, DOWN day: buy PE) or, when 1-7 are all FALSE, entry 8 is TRUE (UP day: "
                            "buy PE, DOWN day: buy CE). Never on a holiday night. Sell next session at the first candle low "
                            "above paid + costs, else at 15:14. Worst fill only.")
        meta["params"] = {"signal": "09:15 open vs 15:14 close (1m)", "strike": "6 in the money", "entry": ENTRY_MIN,
                          "first exit candle": "09:30", "time exit": TIME_EXIT, "lots": LOTS,
                          "expiry": "nearest >= 1 day after exit day", "scenarios A-F": meta["params"]["scenarios A-F"],
                          "thresholds": meta["params"]["thresholds"], "Asia rescue": meta["params"]["Asia rescue"],
                          "the reverse": meta["params"]["the reverse"], "holiday night": meta["params"]["holiday night"]}
        meta["rejected"] = [
            ["Every stop, time cut, morning confirmation, hedge and recovery exit", "about forty tried on both indices "
             "(2026-09-30); all lost money against holding to the line or 15:14. The loss is made in the 09:15 candle."],
            ["The opposite side on EVERY night", "loses 3.5L on this window; it pays only on the nights the rule declines "
             "(the reverse)."],
            ["A stop or a profit target", "not in the rule; tested and rejected."],
        ]
    groups = [{"name": "Direction", "keys": ["direction"]},
              {"name": "Which scenarios fired", "keys": [SCEN_TAG]},
              *[{"name": f"Scenario {SCEN_LABEL[k]}", "keys": [SCEN_LABEL[k]]} for k in "ABCDEF"],
              {"name": "Why the night was traded", "keys": [WHY_TAG]},
              {"name": "Side vs the day (reverse or not)", "keys": [SIDE_TAG]},
              {"name": "Holiday night (Asia thin or US shut)", "keys": [HOLIDAY_TAG]},
              {"name": "Why traded x holiday night", "keys": [WHY_TAG, HOLIDAY_TAG]},
              {"name": "India VIX level", "keys": [IVIX_TAG]},
              {"name": "Why traded x India VIX", "keys": [WHY_TAG, IVIX_TAG]},
              {"name": "Asia today (with or against the day)", "keys": [ASIA_TAG]},
              {"name": "Asia today x close location", "keys": [ASIA_TAG, CLOSE_TAG]},
              {"name": "Direction x why traded", "keys": ["direction", WHY_TAG]},
              {"name": f"{TREND_N}-day trend", "keys": [TREND_TAG]},
              {"name": "Time value share at 15:19", "keys": ["time value"]},
              {"name": "Do the three time-value checks agree?", "keys": ["tv vs share", "tv vs points", "tv vs recent"]},
              {"name": "Cheap or dear against recent nights", "keys": ["tv vs recent"]}]
    if ENTRY_MODE is not None:
        e = next(x for x in ENTRY_POINTS if x[0] == ENTRY_MODE)
        up_buy, dn_buy = _buy(True, e[6]), _buy(False, e[6])
        slug = f"{SLUG}_entry_{ENTRY_MODE}"
        meta["title"] = f"Over night Hold v4 - entry {ENTRY_MODE} alone"
        meta["subtitle"] = (f"ONE entry of the v4 rule run as its own strategy: trade only when {e[2]} AND {e[3]}. "
                            f"UP day: buy {up_buy}. DOWN day: buy {dn_buy}. Never on a holiday night. Same strike (6 in "
                            "the money), same 15:20 buy, same sell-line and exit as the rule. Worst fill only.")
        st = plain_steps()
        meta["rule_steps"] = st[:4] + [
            f"Check entry {ENTRY_MODE}: {e[2]}, AND {e[3]}. If both are true, buy a {up_buy} on an UP day or a {dn_buy} "
            "on a DOWN day. If either is false, there is no trade today."] + st[6:]
        meta["limits"] = [
            f"THIS REPORT IS ENTRY {ENTRY_MODE} ALONE. The full v4 rule trades when at least one of its 8 entries is true; "
            "here only this entry counts, so a night traded here may also be true on other entries, and the 8 single-"
            "entry reports overlap - their trades and profits must not be added together."
            + (" Entry 8 here is traded whenever its two conditions are true; in the full rule it is looked at only "
               "when entries 1 to 7 are all false, so the full rule takes fewer entry-8 trades." if ENTRY_MODE == "8" else "")
        ] + meta["limits"]
        meta["params"]["entry"] = f"entry {ENTRY_MODE}: {e[2]} AND {e[3]} -> UP day {up_buy}, DOWN day {dn_buy}; buy at {ENTRY_MIN}"
    if a.rule_only:
        groups = [{"name": "Why the night was traded", "keys": [WHY_TAG]},
                  {"name": "Direction", "keys": ["direction"]},
                  {"name": "Which scenarios fired", "keys": [SCEN_TAG]},
                  {"name": "Asia today (with or against the day)", "keys": [ASIA_TAG]},
                  {"name": "India VIX level", "keys": [IVIX_TAG]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups,
                            settings=settings, chart="default", sessions_log=log, worst_only=True)
    path = write_report(payload, slug)
    print(console_summary(trades))
    print(path)


if __name__ == "__main__":
    if (("--rule-only" in sys.argv or ENTRY_MODE is not None)
            and "--moneyness" not in sys.argv and "--rungs" not in sys.argv):
        sys.argv += ["--moneyness", "6"]                 # the rule's own strike only
    out = run_instruments(__file__, ladder=tuple(LADDER))  # 6 ITM .. 6 OTM for this strategy (the user, 2026-09-30)
    if ENTRY_MODE is not None and out and os.path.exists(out):   # single-entry reports live in their own folder
        import shutil
        os.makedirs(ENTRY_DIR, exist_ok=True)
        dest = os.path.join(ENTRY_DIR, os.path.basename(out))
        shutil.move(out, dest)
        print(f"moved to {dest}")
elif __name__ == "__instrument__":
    main()
