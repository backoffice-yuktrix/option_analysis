"""Fib retracement v1 - the 0.618-0.786 zone of a confirmed swing leg, entered
on the first touch, stopped 5 points past 0.786, targeted at 1:2 / 1:3 / 1:4.

THE RULE, AS SPECIFIED
----------------------
  1  Find every swing high and swing low.  A swing high is a candle whose high
     is higher than the 8 highs before it and the 8 highs after it; a swing low
     is the mirror.  Loop over the session and mark them all.
  2  Draw the fib on the leg: swing low -> swing high for a LONG, swing high ->
     swing low for a SHORT.
  3  The 0.618-0.786 band is the reversal zone, for both directions.
  4  Enter when price reaches that zone.
  5  Stop 5 points beyond the 0.786 level.
  6  Target at Risk:Reward of 1:2, 1:3 and 1:4.

Everything below is either that rule, or a choice the rule did not make and
this file had to.  Every one of those choices is a flag.


TWO CORRECTIONS TO STEP 1, AND WHY
-----------------------------------
1. STEP 1A'S INEQUALITY IS FLIPPED.  The prose says "Cn's high is higher than
   the past 8 and next 8 highs".  The formula next to it says

       High (cn+9) < High (cn to cn+8)  and  Hight < (cn+10 to cn+17)

   - the SAME "<" that step 1B uses for a swing LOW, whose prose says "lower".
   Taken literally, 1A is not a swing-high detector, it is a LOWEST-HIGH
   detector, and it fails silently: it returns a similar NUMBER of pivots, just
   the wrong bars.  Measured on this sample, 47.6% of the bars it accepts as
   "swing highs" are the same bars 1B accepts as swing lows, and 24.0% of the
   legs built from them have the "high" at or below the leg's own low - a zero
   or negative fib range, from which steps 3-6 cannot be computed at all.

   Worked, on a real swing high: highs cn..cn+8 rising 25000->25040, cn+9 =
   25050, cn+10..cn+17 falling 25045->25010.  The prose accepts it.  The
   formula asks 25050 < 25000, which is false, and REJECTS it.

   So both "<" in 1A are read as ">".  1B is internally consistent (prose
   "lower", operator "<") and is implemented exactly as written.

2. "THE PAST 8 AND NEXT 8" IS TAKEN OVER THE INDEX RANGES.  With the pivot at
   cn+9, "cn to cn+8" is NINE candles (cn+0 ... cn+8) and "cn+10 to cn+17" is
   EIGHT.  The indices spell an asymmetric 9-left / 8-right window; the prose
   says 8 and 8.  This file uses 8 and 8 - symmetric, because long and short
   are exact mirrors here and an asymmetric pivot would confirm swing highs and
   swing lows on different amounts of evidence.  It moves about 6% of the
   pivots, by deletion only, and --pivot-left / --pivot-right put the literal
   9/8 one flag away.

   Comparisons are STRICT (>, <) on both sides, so an equal neighbouring high
   kills a pivot.  The spec does not mention ties; strict is the conservative
   reading and is what this repo's existing detector does.


THE SIX THINGS THE SPEC LEFT OPEN, AND WHAT WAS CHOSEN
-------------------------------------------------------
1. TIMEFRAME.  The spec never names one, and it decides whether the strategy
   exists at all.  Measured over the 123 sessions in this window, pivot 8:

       1-minute    375 bars/session   2733 legs    ~22 legs/session
       3-minute    125 bars/session    757 legs
       5-minute     75 bars/session    351 legs
      15-minute     25 bars/session      8 legs    3 traded sessions in 123
      60-minute      7 bars/session      0 legs    structurally impossible
       daily       132 bars TOTAL        7 legs    every one multi-day

   A pivot of 8 needs 17 bars to exist.  A 15-minute session holds 25 and a
   60-minute session holds 7, so 15-minute is a rounding error and 60-minute
   cannot produce a single swing.  Daily produces 7 legs in six months and
   every one spans sessions, which this repo cannot price (PITFALL 3).  1, 3
   and 5 minute are the timeframes that produce a book, so all three are
   computed and the report switches between them.

2. HOLDING PERIOD.  Intraday, squared off at --square-off (default 15:15).
   Chosen by the user.  It is also the only reading the shared option-pricing
   layer can price - see PITFALL 3.

3. WHICH LEG IS LIVE.  "go in the loop to find every swing high and swing low"
   marks them all but never says which fib is the one being traded.  Both
   readings ship, --legs picks:
     all      every leg stays live from the moment it can be drawn until it is
              entered or the session ends.  This is the literal loop.
     latest   only the most recent confirmed leg is live; a newer leg
              supersedes it.  This is what dragging a fib tool onto the newest
              swing does, and it is the only reading under which a long zone
              and a short zone can never be live at once.

4. WHERE IN THE ZONE THE ENTRY IS.  0.618 is the near edge - price coming back
   off the swing reaches it before 0.786 - so "when the price reaches that
   zone" is a resting order at the 0.618 level.  --entry-at 786 moves it to the
   far edge, which roughly triples the risk; kept as a comparison only.

4b. HOW THE ZONE IS ENTERED.  Step 4 says only "enter when the price reaches
   that zone", which read literally is a resting limit and no confirmation of
   any kind.  That is `touch`.  The other thing a trader usually means by the
   same words is `retest`: let price into the zone, wait for it to be REJECTED
   back out of it, and buy the SECOND visit.  Both are computed and the report
   switches between them; --entry-mode picks which one it opens on.

     touch    the first minute whose low reaches the 0.618 level (mirrored for
              a short) is the fill.
     retest   a three-state machine on 1-minute candles:
                WAIT_TOUCH    price has to reach the zone at all
                WAIT_REJECT   a candle has to CLOSE back beyond the near edge.
                              One candle can do both - dip in and close back
                              out is the classic rejection and counts as
                              touch-then-reject in a single bar.
                WAIT_RETEST   the NEXT candle to reach the edge is the entry.
              At any point a close beyond the FAR edge kills the leg: price has
              retraced more than 78.6% and the fib no longer holds.
              The rejection candle itself can never be the entry.

   THE RETEST FIXES THE PLACEABILITY PROBLEM COMPLETELY.  Under `touch`, a
   retracement fast enough to cross the whole zone does it inside one minute,
   so the fill lands at or beyond its own stop and the trade is rejected -
   17.6% of 1-minute candidates, 21.8% on 3-minute, 30.5% on 5-minute.  Under
   `retest` that number is ZERO on all three, because the rejection close puts
   price back OUTSIDE the zone before the return, so the entry is always on the
   correct side of the stop:

       1m touch   2293 found   1889 placeable   404 rejected (17.6%)
       1m retest  1035 found   1035 placeable     0 rejected ( 0.0%)
       3m touch    564 found    441 placeable   123 rejected (21.8%)
       3m retest   264 found    264 placeable     0 rejected ( 0.0%)
       5m touch    246 found    171 placeable    75 rejected (30.5%)
       5m retest   108 found    108 placeable     0 rejected ( 0.0%)

   It costs roughly half to two-thirds of the entries to get that.

5. HOW MANY TRADES A SESSION.  The rule generates ~19 post-confirmation zone
   touches a session on 1-minute, and every other report in this repo is
   one-trade-per-session.  Both are computed and the report switches:
     flow     one position at a time, re-entering whenever a leg arms and the
              book is flat
     session  the first placeable entry of the day, then the day is done
   Neither is a filter on the other - they are different strategies, and the
   matrix shows them side by side.

6. THE BLIND WINDOW.  A swing is not confirmed until 8 bars after it prints, so
   the fib cannot be drawn until then - and on 60.8% of legs price has ALREADY
   reached the 0.618 level during those 8 blind bars.  Chosen by the user: take
   the FIRST TOUCH AT OR AFTER the zone becomes drawable, second visits
   included.  --virgin-only ships the other reading (kill any leg whose zone
   was reached while it was still blind), which is about a third of the book.
   Neither reading ever looks at an unconfirmed swing; see PITFALL 1.


WHAT THIS SCRIPT MEASURES, ON THE REAL ATM OPTION
-------------------------------------------------
123 sessions, 2026-03-16 to 2026-09-11.  Every trade priced on the contract that
would actually have been bought; 0 trades went unpriced.  The columns are the
ones every other report in this repo carries: win rate and rupees come from the
PREMIUM, avg prem % is the simple mean of each trade's return on the premium
paid, R:R is the real average win over the real average loss.  h1/h2 split at
2026-06-17; X marks the halves disagreeing in sign.

  combo                     N   win%    R:R   avgPrem%     h1      h2
  1m touch  flow    1:2  1242   32.9   1.92     -0.24    0.25   -0.73  X
  1m touch  flow    1:3  1057   28.1   2.38     -0.30    0.20   -0.82  X
  1m touch  flow    1:4   939   24.3   2.69     -0.60   -0.12   -1.07
  1m touch  session 1:2   123   25.2   2.71     -0.58   -0.10   -1.05
  1m touch  session 1:3   123   21.1   3.48     -0.57    0.00   -1.14  X
  1m touch  session 1:4   123   17.9   3.82     -0.76   -1.03   -0.50
  1m retest flow    1:2   741   36.2   1.62     -0.40    0.04   -0.81  X
  1m retest flow    1:3   660   29.4   2.12     -0.60   -0.09   -1.09
  1m retest flow    1:4   591   24.9   2.76     -0.60    0.13   -1.26  X
  1m retest session 1:2   123   31.7   1.81     -0.80    0.43   -2.00  X
  1m retest session 1:3   123   26.8   2.46     -0.47    0.82   -1.75  X
  1m retest session 1:4   123   20.3   3.01     -1.09   -0.24   -1.92
  3m touch  flow    1:2   362   33.1   2.12     +0.11    0.22    0.02
  3m touch  flow    1:3   320   28.4   2.78     +0.16    0.95   -0.57  X
  3m touch  flow    1:4   303   24.4   3.63     +0.58    1.12    0.08
  3m touch  session 1:2   120   33.3   2.36     +0.32    1.10   -0.41  X
  3m touch  session 1:3   120   28.3   3.15     +0.83    1.64    0.07
  3m touch  session 1:4   120   25.0   4.74     +2.14    2.85    1.48
  3m retest flow    1:2   218   35.3   1.70     -0.50   -0.11   -0.83
  3m retest flow    1:3   200   27.5   2.57     -0.53    0.91   -1.78  X
  3m retest flow    1:4   192   25.0   3.37     +0.21    2.40   -1.69  X
  3m retest session 1:2   111   35.1   1.96     -0.10    0.79   -0.94  X
  3m retest session 1:3   111   27.9   3.24     +0.87    2.66   -0.82  X
  3m retest session 1:4   111   25.2   4.22     +1.82    4.45   -0.67  X
  5m touch  flow    1:2   152   36.2   1.86     -0.09   -0.14   -0.04
  5m touch  flow    1:3   140   33.6   2.31     +0.21    0.16    0.25
  5m touch  flow    1:4   134   28.4   3.05     +0.34    0.72    0.03
  5m touch  session 1:2    88   39.8   1.96     +0.39    0.97   -0.14  X
  5m touch  session 1:3    88   33.0   2.51     +0.19    0.98   -0.54  X
  5m touch  session 1:4    88   27.3   3.35     +0.27    1.48   -0.83  X
  5m retest flow    1:2    97   41.2   1.78     +0.65    0.44    0.81
  5m retest flow    1:3    92   34.8   2.28     +0.49    0.36    0.60
  5m retest flow    1:4    90   30.0   3.35     +1.22    2.42    0.22
  5m retest session 1:2    75   42.7   2.02     +1.39    1.97    0.91
  5m retest session 1:3    75   33.3   2.74     +1.11    1.61    0.70
  5m retest session 1:4    75   30.7   3.77     +2.25    4.14    0.68

READ THIS BEFORE READING THAT TABLE.

  1  THE RETEST IS NOT UNIFORMLY BETTER.  On 1-minute it is WORSE than touch on
     every rung, and on 3-minute it is worse on four of six and turns five of
     six split-halves into disagreements.  It helps on exactly one timeframe.
  2  5-MINUTE RETEST IS THE ONLY BLOCK IN THE WHOLE 36-CELL MATRIX where all
     six rungs are positive AND all six agree across the halves.  Every other
     block has either a negative rung or a sign flip in it.  It is also the
     block with the fewest trades (75-97), which is the trade-off.
  3  1-MINUTE IS NEGATIVE EVERYWHERE, under both entry readings.  It is not a
     smaller version of the other results, it is the opposite sign.
  4  THE MEANS ARE STILL SMALL.  Costs are not modelled anywhere in this repo,
     and a realistic round trip on a NIFTY ATM option - spread plus brokerage
     plus STT - is a large fraction of a 1% mean.  Read every positive cell as
     smaller than it looks once it is paid for.
  5  THIS IS 36 CELLS ON ONE WINDOW.  The 5-minute retest block is the best
     block, and it was found by looking at all 36.  What earns it more
     attention than a lucky cell is that the mechanism is understood - see the
     placeability table under choice 4b - and that it holds across all six of
     its own rungs rather than in one.  It is still not validated out of
     sample, and it needs a window it was never fitted on before it is
     believed.

WHY THE RETEST CHANGES THE SHAPE.  The zone is 0.786 - 0.618 = 0.168 of the leg
wide and the stop sits 5 points past its far edge, so risk is 0.168 x L + 5 - a
100-point leg gives a 21.8-point stop.  Under `touch` a fast retracement crosses
that whole zone inside one minute and the fill lands beyond its own stop; under
`retest` the rejection close proves price left the zone first, so the entry is
always on the correct side of it.  That is the entire mechanism, and it shows up
as the 17.6 / 21.8 / 30.5 percent of `touch` candidates that are unplaceable
against zero for `retest`.

It does NOT fix the other half of the problem: a 1R stop still costs roughly 20%
of the premium paid, so the rule still needs a strike rate on a target it
reaches less than half the time.

This file implements the rule as specified, with both readings of step 4 shown
side by side.  Reporting where it does and does not clear its costs is the
deliverable; quietly keeping only the block that works would not be.


KNOWN PITFALLS IN THIS DATA - every one of these has been shipped wrong before
------------------------------------------------------------------------------
1. A SWING DOES NOT EXIST UNTIL ITS RIGHT-HAND SIDE HAS CLOSED.  A pivot at bar
   i needs bars i+1 .. i+8 to close before it is a swing, so at bar i the newest
   usable swing is the one at i-8.  Every leg here carries `ready`, the bar by
   which BOTH its swings had confirmed, and the entry scan starts strictly after
   it.  Precomputing the pivots for a whole session and then using the "latest"
   one without that gate is the single biggest look-ahead trap in this strategy
   - it reads the future and the results become fiction.  build_legs() carries a
   runtime assertion on it.

2. RISK IS SIGNED, NEVER abs().  The entry is a level and the stop is only
   0.168 x L + 5 beyond it, so a minute that opens deep inside the zone can fill
   the entry BEYOND its own stop.  Reporting abs(entry - sl) there invents a
   positive risk for a trade that was never placeable and hides an entry on the
   wrong side of the stop.  risk = (entry - sl) for a long, (sl - entry) for a
   short, and risk <= 0 is rejected as "entry through the stop" with its own row
   in the report.  On this rule that is 18% of candidates on 1-minute,
   22% on 3-minute and 31% on 5-minute - a headline property of the rule,
   not a footnote.

3. THE OPTION LAYER IS SINGLE-SESSION AND FAILS SILENTLY WRONG.  CachedPricer
   resolves one date and reads both the entry and the exit premium out of that
   one day's minute dict.  Hand it a position that opened yesterday and it
   returns a plausible WRONG number with no error.  This strategy is intraday
   and squares off at 15:15, so it never happens here - but it is why a
   multi-day reading of this spec is a pricing-layer project, not a flag.

4. DAILY VALUES MUST COME FROM THE DAILY CANDLES.  The 1-minute feed's last
   candle is 15:29 and misses the closing print.  Nothing in this strategy uses
   a previous close, but the daily feed is loaded anyway and the report shows
   the official close beside the 15:29 print so the gap stays visible.

5. THE STOP CAN BE HIT ON THE ENTRY MINUTE.  The entry is a level touched inside
   a minute and the stop is ~20 points away, so the same minute often trades
   both.  The exit walk therefore INCLUDES the entry minute, and within any
   minute the stop is checked before the target.  Excluding it would quietly
   delete this rule's most common loss.

6. COSTS ARE NOT MODELLED, AND HERE THAT MATTERS MORE THAN USUAL.  Like every
   other report in this repo the numbers are GROSS.  1R on this rule is a small
   fraction of the premium paid, so a realistic round trip is a large share of
   it - the report prints the break-even round-trip cost next to the headline
   so the size of that hole is visible rather than assumed away.


FILL ASSUMPTIONS, STATED ONCE AND TRUE OF THE CODE
---------------------------------------------------
  entry      a resting limit at the 0.618 level.  Filled AT the level, unless
             the minute already opened past it, in which case the open is the
             honest fill.
  stop       a resting stop at 0.786 -/+ 5.  Same treatment: filled at the
             level, or at the open when the minute opened through it.  It is
             not close-confirmed, so the loss is capped at 1R except when a
             minute opens past the level - and `slip` is how far that went.
  target     a resting limit, same treatment.
  square-off the OPEN of the first minute at or after --square-off.
  order      within one minute: square-off, then stop, then target.

Levels are prices and can trade at any moment, so every exit is checked on
1-MINUTE candles even when the structure is read on 3- or 5-minute bars.

Run from backend/:
    python scripts/fib_retracement_v1.py                 # first run online, fetches option data
    python scripts/fib_retracement_v1.py --offline       # afterwards
    python scripts/fib_retracement_v1.py --legs latest --virgin-only

Output: ../reports/fib_retracement_v1_report.html (self-contained, no CDN).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..")
sys.path.insert(0, BACKEND_DIR)

from services.upstox_client import INSTRUMENT_KEYS, get_candles  # noqa: E402
from services.option_pricing import (  # noqa: E402
    CachedPricer, ensure_cached, ROLL_MODES)

DATA_DIR = os.path.join(BACKEND_DIR, "data")
REPORTS_DIR = os.path.join(BACKEND_DIR, "reports")
CONFIG_FILE = os.path.join(BACKEND_DIR, "upstox_config.txt")
REPORT_HTML = os.path.join(REPORTS_DIR, "fib_retracement_v1_report.html")

UNDERLYING = "NIFTY"
UNDERLYING_KEY = INSTRUMENT_KEYS[UNDERLYING]

# NIFTY lot size verified against the Upstox contract master for this period.
# It scales the rupee columns and NOTHING else: every headline number here is a
# percentage of the premium paid, which is lot-size independent.
LOT_SIZE = 65

# 15-minute gives 8 legs in 123 sessions and 60-minute gives zero, because a
# pivot of 8 needs 17 bars and those sessions hold 25 and 7.  See choice 1.
TIMEFRAMES = [1, 3, 5]
# The report opens on 5-minute because that is the only timeframe on which the
# retest block is positive on every rung with both halves agreeing.  It is the
# best block of 36 and it was chosen by looking at all 36 - see note 5 above.
DEFAULT_TF = 5

# Step 1, read from the PROSE ("the past 8 and next 8"), not from the index
# ranges, which spell an asymmetric 9-left / 8-right window.  See correction 2.
PIVOT_LEFT = 8
PIVOT_RIGHT = 8

# Step 3.  The zone is the band between these two retracements of the leg.
FIB_NEAR = 0.618               # the edge price reaches first - the entry
FIB_FAR = 0.786                # the far edge - the stop sits beyond this
# Step 5: "below the 0.786 (78.60%) ( 5 points)", mirrored for a short.  The
# spec gives the number, so it is not tuned.
STOP_OFFSET = 5.0

# Step 6.  All three are computed and the report switches between them.
RR_VALUES = [2.0, 3.0, 4.0]
DEFAULT_RR = 2.0

# A stop closer than this is not a trade, it is noise: NIFTY ticks in 0.05 and
# a sub-point stop is taken out for exactly -1R by the spread alone.  Because
# risk is 0.168 x L + 5, this floor only ever catches entries that filled deep
# inside the zone; it is not a leg-size filter.  0 disables it.
MIN_RISK = 1.0

LEG_MODES = [("all", "Every leg stays live until it is entered or the session ends"),
             ("latest", "Only the newest confirmed leg is live; a newer one supersedes it")]
DEFAULT_LEGS = "all"

TRADE_MODES = [("flow", "One position at a time, re-entering whenever a leg arms"),
               ("session", "The first placeable entry of the day, then the day is done")]
DEFAULT_MODE = "flow"

ENTRY_EDGES = [("618", "The 0.618 level - the near edge, reached first"),
               ("786", "The 0.786 level - the far edge of the zone")]
DEFAULT_EDGE = "618"

# HOW THE ZONE IS ENTERED.  Step 4 says only "enter when the price reaches that
# zone", which is a resting limit at the near edge and nothing else - no
# confirmation of any kind.  `retest` is the other reading a trader usually
# means by the same words: let price into the zone, wait for it to be REJECTED
# back out (a close beyond the near edge), and buy the SECOND visit.
ENTRY_MODES = [("touch", "Resting limit at the near edge - fills on the first touch"),
               ("retest", "Touch, rejection close back out, then buy the return")]
DEFAULT_ENTRY = "retest"
ENTRY_KEYS = [k for k, _ in ENTRY_MODES]

VIEWS = [("both", "Long and short together"),
         ("long", "Long trades only"),
         ("short", "Short trades only")]
DEFAULT_VIEW = "both"

EOD_MODES = [("close", "square off at the session close time"),
             ("hold", "run to stop or target, give up at the last candle")]
DEFAULT_EOD = "close"

# 0-DTE is where every catastrophic percentage loss in this repo's other books
# came from: an expiry-day ATM option is nearly all gamma, so an adverse move
# takes most of a thin contract.  Rolling off it costs premium and buys a far
# smaller worst case.
DEFAULT_ROLL = "zero-dte"

SESSION_START = "09:15"
SQUARE_OFF = "15:15"
OPEN_TIME = "09:15"
DAY_END = "15:29"


def rr_label(r: float) -> str:
    return f"1:{r:g}"


def rr_keys(rr_values: list[float]) -> list[str]:
    return [rr_label(r) for r in rr_values]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _read_access_token() -> str | None:
    try:
        with open(CONFIG_FILE) as f:
            lines = [l.strip() for l in f.readlines()]
    except OSError:
        return None
    return lines[3] if len(lines) >= 4 and lines[3] else None


def nifty_cache_path(from_date: date, to_date: date) -> str:
    return os.path.join(
        DATA_DIR, f"nifty_1m_{from_date.isoformat()}_{to_date.isoformat()}.json")


def _slice_existing_cache(from_date: date, to_date: date) -> list[dict] | None:
    """Reuse a wider cache file in backend/data that already covers the window."""
    best: tuple[int, list[dict], str] | None = None
    for name in os.listdir(DATA_DIR):
        if not (name.startswith("nifty_1m_") and name.endswith(".json")):
            continue
        stem = name[len("nifty_1m_"):-len(".json")]
        try:
            a, b = stem.split("_")
            c_from, c_to = date.fromisoformat(a), date.fromisoformat(b)
        except ValueError:
            continue
        if c_from > from_date or c_to < from_date:
            continue
        with open(os.path.join(DATA_DIR, name)) as f:
            candles = json.load(f)
        kept = [c for c in candles
                if from_date.isoformat() <= c.get("timestamp", "")[:10] <= to_date.isoformat()]
        if kept and (best is None or len(kept) > best[0]):
            best = (len(kept), kept, name)
    if best is None:
        return None
    print(f"Reusing {best[2]}: {best[0]} candles inside {from_date} -> {to_date}")
    return best[1]


async def load_nifty(offline: bool, from_date: date, to_date: date) -> list[dict]:
    cache = nifty_cache_path(from_date, to_date)
    if os.path.exists(cache):
        with open(cache) as f:
            candles = json.load(f)
        print(f"Loaded {len(candles)} cached NIFTY 1m candles from {os.path.basename(cache)}")
        return candles
    token = None if offline else _read_access_token()
    if token:
        try:
            print(f"Fetching NIFTY 1m candles {from_date} -> {to_date} ...")
            candles = await get_candles(token, UNDERLYING_KEY, "1m", from_date, to_date)
            if candles:
                print(f"Fetched {len(candles)} candles.")
                with open(cache, "w") as f:
                    json.dump(candles, f)
                return candles
            print("  ! Upstox returned no candles; falling back to the local caches.")
        except Exception as exc:                                  # noqa: BLE001
            print(f"  ! fetch failed ({exc}); falling back to the local caches.")
    reused = _slice_existing_cache(from_date, to_date)
    if reused is None:
        raise RuntimeError(f"No data for {from_date} -> {to_date} and no usable cache.")
    return reused


def daily_cache_path(from_date: date, to_date: date) -> str:
    return os.path.join(
        DATA_DIR, f"nifty_1d_{from_date.isoformat()}_{to_date.isoformat()}.json")


async def load_daily(offline: bool, from_date: date, to_date: date) -> dict[str, float]:
    """Map of session date to the OFFICIAL close, from the daily candle feed.

    This strategy is purely intraday and never uses a previous close, so no
    signal depends on this.  It is loaded anyway because the 1-minute feed's
    15:29 print is NOT the official close, and the report shows both so that
    gap stays visible rather than being quietly assumed away.  See PITFALL 4.
    """
    lookback = from_date - timedelta(days=15)
    cache = daily_cache_path(lookback, to_date)
    raw = None
    if os.path.exists(cache):
        with open(cache) as f:
            raw = json.load(f)
        print(f"Loaded {len(raw)} cached NIFTY daily candles from {os.path.basename(cache)}")
    else:
        token = None if offline else _read_access_token()
        if token:
            try:
                print(f"Fetching NIFTY daily candles {lookback} -> {to_date} ...")
                raw = await get_candles(token, UNDERLYING_KEY, "1d", lookback, to_date)
                if raw:
                    with open(cache, "w") as f:
                        json.dump(raw, f)
                    print(f"Fetched {len(raw)} daily candles.")
                else:
                    raw = None
            except Exception as exc:                              # noqa: BLE001
                print(f"  ! daily fetch failed ({exc})")
                raw = None
    if not raw:
        # Only a file that actually COVERS the window is any use.  Taking the
        # first name alphabetically once silently loaded a December-March file
        # for a March-September run and left official_close blank on every row
        # without ever erroring.
        best = None
        for name in sorted(os.listdir(DATA_DIR)):
            if not (name.startswith("nifty_1d_") and name.endswith(".json")):
                continue
            try:
                a, b = name[len("nifty_1d_"):-len(".json")].split("_")
                c_from, c_to = date.fromisoformat(a), date.fromisoformat(b)
            except ValueError:
                continue
            if c_from <= from_date and c_to >= to_date:
                span = (c_to - c_from).days
                if best is None or span < best[0]:
                    best = (span, name)
        if best is not None:
            with open(os.path.join(DATA_DIR, best[1])) as f:
                raw = json.load(f)
            print(f"Reusing {best[1]} for the official daily closes.")
    if not raw:
        print("  ! no daily candles; the report will show the 15:29 print only.")
        return {}
    return {c["timestamp"][:10]: float(c["close"]) for c in raw}


def index_by_day(candles: list[dict]) -> dict[str, list[dict]]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for c in candles:
        ts = c.get("timestamp", "")
        if len(ts) < 16:
            continue
        by_day[ts[:10]].append(c)
    for day in by_day:
        by_day[day].sort(key=lambda c: c["timestamp"])
    return dict(by_day)


# ---------------------------------------------------------------------------
# Candles
# ---------------------------------------------------------------------------

def session_minutes(minutes: list[dict]) -> list[dict]:
    """The session 1-minute candles, in order, normalised to floats."""
    out = []
    for c in minutes:
        hhmm = c["timestamp"][11:16]
        if hhmm < OPEN_TIME or hhmm > DAY_END:
            continue
        out.append({"t": hhmm, "o": float(c["open"]), "h": float(c["high"]),
                    "l": float(c["low"]), "c": float(c["close"])})
    out.sort(key=lambda c: c["t"])
    return out


def bucket_start(hhmm: str, minutes: int) -> str:
    """09:15-anchored bucket label: for 3m, 09:15, 09:18, 09:21, ..."""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    offset = (h * 60 + m) - (9 * 60 + 15)
    if offset < 0:
        return OPEN_TIME
    start = 9 * 60 + 15 + (offset // minutes) * minutes
    return f"{start // 60:02d}:{start % 60:02d}"


def build_buckets(mins: list[dict], size: int) -> list[dict]:
    """Aggregate the session 1-minute candles into size-minute bars.

    Each bar carries m0 and m1, the index range of the 1-minute candles it is
    built from.  That mapping is what lets the structure be read on 3- or
    5-minute bars while every entry and exit is still checked minute by minute
    - a level can trade at any moment inside a bar, and pretending otherwise
    would flatter the fills.  size == 1 is the identity aggregation, so the
    1-minute timeframe runs through exactly the same code path.
    """
    groups: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(mins):
        groups[bucket_start(c["t"], size)].append(i)
    out = []
    for start in sorted(groups):
        g = groups[start]
        out.append({
            "start": start,
            "open": mins[g[0]]["o"],
            "high": max(mins[i]["h"] for i in g),
            "low": min(mins[i]["l"] for i in g),
            "close": mins[g[-1]]["c"],
            "m0": g[0], "m1": g[-1],
        })
    return out


# ---------------------------------------------------------------------------
# Step 1 - swings
# ---------------------------------------------------------------------------

def confirmed_swings(bars: list[dict], left: int, right: int
                     ) -> tuple[list[dict], list[dict]]:
    """Every swing high and swing low, each carrying the bar that confirms it.

    A swing high at i is STRICTLY higher than the left highs before it and the
    right highs after it, which is step 1A read through its prose rather than
    through its inequality (see correction 1 in the docstring).  A swing low is
    step 1B exactly as written.

    confirm is i + right: the bar by which the right-hand side has closed and
    the swing is knowable.  Nothing in this file may look at a swing before its
    confirm bar - see PITFALL 1.
    """
    highs: list[dict] = []
    lows: list[dict] = []
    n = len(bars)
    for i in range(left, n - right):
        h = bars[i]["high"]
        if (all(bars[j]["high"] < h for j in range(i - left, i)) and
                all(bars[j]["high"] < h for j in range(i + 1, i + right + 1))):
            highs.append({"i": i, "price": h, "confirm": i + right,
                          "time": bars[i]["start"]})
        lo = bars[i]["low"]
        if (all(bars[j]["low"] > lo for j in range(i - left, i)) and
                all(bars[j]["low"] > lo for j in range(i + 1, i + right + 1))):
            lows.append({"i": i, "price": lo, "confirm": i + right,
                         "time": bars[i]["start"]})
    return highs, lows


# ---------------------------------------------------------------------------
# Steps 2 and 3 - legs and the 0.618-0.786 zone
# ---------------------------------------------------------------------------

def build_legs(bars: list[dict], highs: list[dict], lows: list[dict], *,
               fib_near: float, fib_far: float, stop_offset: float) -> list[dict]:
    """Alternating swing pairs, each with its fib zone and its stop.

    The spec says to mark every swing and then draw the fib "swing low to high"
    or "high to low", which only has a meaning once the swings alternate.  Two
    consecutive swings of the SAME type are collapsed to the more extreme of
    the two - the standard reading, and what a charting platform does when it
    auto-draws a fib.  A leg of zero height is dropped: steps 3 to 6 cannot be
    computed from it.

    Each leg carries ready, the bar by which BOTH its swings had confirmed, and
    superseded, the bar at which the NEXT leg becomes drawable.
    """
    ev = sorted([dict(s, k="H") for s in highs] + [dict(s, k="L") for s in lows],
                key=lambda s: (s["i"], s["k"]))
    seq: list[dict] = []
    for s in ev:
        if seq and seq[-1]["k"] == s["k"]:
            better = (s["price"] > seq[-1]["price"] if s["k"] == "H"
                      else s["price"] < seq[-1]["price"])
            if better:
                seq[-1] = s
            continue
        seq.append(s)

    legs: list[dict] = []
    for a, b in zip(seq, seq[1:]):
        size = abs(b["price"] - a["price"])
        if size <= 0:
            continue
        long_ = b["k"] == "H"                 # up-leg: buy the retracement down
        ready = max(a["confirm"], b["confirm"])
        # b always prints after a, so b's confirmation is always the binding
        # one.  Asserted rather than assumed - if this ever failed, the leg
        # would be drawable before one of its own swings existed.
        assert ready == b["confirm"], "leg ready must be the terminus confirm"
        if ready >= len(bars):
            continue
        near = b["price"] - fib_near * size if long_ else b["price"] + fib_near * size
        far = b["price"] - fib_far * size if long_ else b["price"] + fib_far * size
        sl = far - stop_offset if long_ else far + stop_offset
        legs.append({
            "side": "LONG" if long_ else "SHORT",
            "from_price": round(a["price"], 2), "from_time": a["time"], "from_i": a["i"],
            "to_price": round(b["price"], 2), "to_time": b["time"], "to_i": b["i"],
            "size": round(size, 2),
            "near": round(near, 2), "far": round(far, 2), "sl": round(sl, 2),
            "ready": ready, "ready_time": bars[ready]["start"],
            "superseded": None, "outcome": "pending",
        })
    for k in range(len(legs) - 1):
        legs[k]["superseded"] = legs[k + 1]["ready"]
    return legs


# ---------------------------------------------------------------------------
# Step 4 - the entry
# ---------------------------------------------------------------------------

def _retest_hit(mins, legs_long: bool, level: float, far: float,
                start: int, end: int) -> tuple[int | None, str]:
    """The zone retest, as a three-state machine over 1-minute candles.

      WAIT_TOUCH    price has to reach the zone at all (low <= near for a long)
      WAIT_REJECT   it then has to be pushed back OUT of the zone - a candle
                    CLOSING beyond the near edge.  A single candle can do both:
                    dip in and close back out is the classic rejection, and it
                    counts as touch-then-reject in one bar.
      WAIT_RETEST   the next candle to reach the near edge again is the ENTRY.

    At any point a close BEYOND THE FAR EDGE kills the leg: price has retraced
    more than 78.6%, so the fib that defined the trade no longer holds.

    The rejection candle itself can never be the entry - the retest has to be a
    LATER minute - which is the whole difference from `touch`.
    """
    state = 'WAIT_TOUCH'
    for i in range(start, end + 1):
        c = mins[i]
        touched = (c["l"] <= level) if legs_long else (c["h"] >= level)
        broke = (c["c"] < far) if legs_long else (c["c"] > far)
        rejected = (c["c"] > level) if legs_long else (c["c"] < level)
        if broke:
            return None, {"WAIT_TOUCH": "zone broken before it was reached",
                          "WAIT_REJECT": "zone broken while price sat in it",
                          "WAIT_RETEST": "zone broken before the retest"}[state]
        if state == 'WAIT_RETEST':
            if touched:
                return i, ""
            continue
        if state == 'WAIT_TOUCH' and touched:
            state = 'WAIT_REJECT'
        if state == 'WAIT_REJECT' and rejected:
            state = 'WAIT_RETEST'
    return None, {"WAIT_TOUCH": "zone never reached",
                  "WAIT_REJECT": "reached the zone, never rejected out of it",
                  "WAIT_RETEST": "rejected, but never retested"}[state]


def find_signals(bars: list[dict], mins: list[dict], legs: list[dict], *,
                 leg_mode: str, entry_edge: str, virgin_only: bool,
                 entry_until: str, entry_mode: str) -> list[dict]:
    """Where each leg is entered, under whichever reading of step 4 is selected.

    `touch`   a resting limit at the near edge; the first minute that reaches
              it, at or after the leg becomes drawable, is the fill.
    `retest`  the zone has to be reached, REJECTED out of (a close beyond the
              near edge), and only the RETURN to the edge is the entry.

    Either way the scan starts at the minute AFTER the leg's `ready` bar has
    closed, which is what keeps the fib off unconfirmed swings (PITFALL 1), and
    either way the fill is a resting limit: at the level, or at the minute open
    when the minute had already opened past it.

    `virgin_only` additionally drops any leg whose entry level was already
    reached during the blind window - the bars between the terminus swing and
    its confirmation, when the zone existed but could not yet be drawn.
    """
    out: list[dict] = []
    last_min = len(mins) - 1
    for leg in legs:
        long_ = leg["side"] == "LONG"
        level = leg["near"] if entry_edge == "618" else leg["far"]
        sl = leg["sl"]
        start = bars[leg["ready"]]["m1"] + 1
        if leg_mode == "latest" and leg["superseded"] is not None:
            end = bars[leg["superseded"]]["m1"]
        else:
            end = last_min
        end = min(end, last_min)
        if start > end:
            leg["outcome"] = "never drawable in time"
            continue

        if virgin_only:
            blind_from = max(0, bars[leg["to_i"]]["m1"] + 1)
            blind_to = min(bars[leg["ready"]]["m1"], last_min)
            if any((mins[i]["l"] <= level) if long_ else (mins[i]["h"] >= level)
                   for i in range(blind_from, blind_to + 1)):
                leg["outcome"] = "zone reached while blind"
                continue

        if entry_mode == "retest":
            hit, why = _retest_hit(mins, long_, level, leg["far"], start, end)
        else:
            hit, why = None, "zone never reached"
            for i in range(start, end + 1):
                c = mins[i]
                if (c["l"] <= level) if long_ else (c["h"] >= level):
                    hit, why = i, ""
                    break
        if hit is None:
            leg["outcome"] = why
            continue
        c = mins[hit]
        if c["t"] >= entry_until:
            leg["outcome"] = "past the entry cut-off"
            leg["touched_at"] = c["t"]
            continue
        # A resting limit fills at the level, or at the open when the minute
        # opened past it - the honest reading, and the one that exposes the
        # entries that land beyond their own stop.
        entry = min(level, c["o"]) if long_ else max(level, c["o"])
        risk = (entry - sl) if long_ else (sl - entry)     # SIGNED - PITFALL 2
        leg["outcome"] = "zone entered" if risk > 0 else "entry through the stop"
        out.append({
            "leg": leg, "side": leg["side"], "mi": hit, "entry_time": c["t"],
            "entry": round(entry, 2), "level": round(level, 2),
            "sl": round(sl, 2), "risk": round(risk, 2),
        })
    out.sort(key=lambda s: s["mi"])
    return out


# ---------------------------------------------------------------------------
# Steps 5 and 6 - the exits
# ---------------------------------------------------------------------------
#
# The signal layer above decided WHERE a position opens.  Everything below
# decides where it closes, and it runs entirely on 1-MINUTE candles even when
# the structure was read on 3- or 5-minute bars: a stop or a target is a price
# that can be traded at any moment inside a bar, and pretending it can only
# happen at a 5-minute close would flatter the results.
#
# The walk INCLUDES the entry minute.  The entry is a level touched inside that
# minute and the stop is only 0.168 x L + 5 away, so the same minute very often
# trades both - excluding it would quietly delete this rule's most common loss
# (PITFALL 5).  Within any minute the order is square-off, then stop, then
# target, so a minute that spans both the stop and the target is a loss.

def walk(mins: list[dict], mi_entry: int, side: str, sl: float,
         target: float | None, *, eod: str, square_off: str) -> dict:
    long_ = side == "LONG"
    for i in range(mi_entry, len(mins)):
        m = mins[i]
        if eod == "close" and m["t"] >= square_off:
            return {"exit": m["o"], "exit_time": m["t"], "exit_i": i,
                    "reason": "SQUARE OFF"}
        if (m["l"] <= sl) if long_ else (m["h"] >= sl):
            # A resting stop: filled AT the level, unless the minute opened
            # through it, in which case the open is the honest fill and the
            # loss is worse than 1R.  `slip` is exactly that overshoot.
            fill = min(sl, m["o"]) if long_ else max(sl, m["o"])
            return {"exit": fill, "exit_time": m["t"], "exit_i": i,
                    "reason": "STOP"}
        if target is not None and ((m["h"] >= target) if long_ else (m["l"] <= target)):
            fill = max(target, m["o"]) if long_ else min(target, m["o"])
            return {"exit": fill, "exit_time": m["t"], "exit_i": i,
                    "reason": "TARGET"}
    last = mins[-1]
    return {"exit": last["c"], "exit_time": last["t"], "exit_i": len(mins) - 1,
            "reason": "EOD"}


PRICER = CachedPricer()


def _option_leg(pricer, info, t, res) -> dict:
    """The premium fields for one exit variant.

    Returns pnl_rs=None and opt_reason set when the contract or its candles
    could not be had.  Such a trade STAYS in the book and stays visible - it is
    simply left out of the money totals.  Dropping it would quietly shrink the
    sample, which is the failure mode this whole exercise exists to remove.
    """
    if pricer is None or info is None:
        return {"pnl_rs": None, "win": None, "opt_reason": "not priced",
                "prem_pts": None, "prem_perc": None, "entry_px": None,
                "exit_px": None}
    if info["reason"]:
        return {"strike": info["strike"], "opt_type": info["option_type"],
                "opt_symbol": info["symbol"], "entry_px": None, "exit_px": None,
                "prem_pts": None, "prem_perc": None, "pnl_rs": None, "win": None,
                "opt_reason": info["reason"]}
    o = CachedPricer.price_from(info, t["entry_time"], res["exit_time"])
    prem = o["prem_pts"]
    px = o["entry_px"]
    # THE HEADLINE NUMBER.  What the account risks on a bought option is what
    # the contract cost, so the return is measured against exactly that.  It is
    # independent of lot size and of how much capital was committed, which is
    # what makes it comparable across timeframes and across variants.
    perc = None if (prem is None or not px) else round(prem / px * 100, 2)
    return {"strike": o["strike"], "opt_type": o["option_type"],
            "opt_symbol": o["symbol"], "entry_px": px,
            "exit_px": o["exit_px"], "prem_pts": prem, "prem_perc": perc,
            "pnl_rs": None if prem is None else round(prem * LOT_SIZE, 2),
            "win": None if prem is None else prem > 0,
            "opt_reason": o["reason"]}


def price_trades(mins: list[dict], signals: list[dict], *, rr_values: list[float],
                 modes: list[str], eod: str, square_off: str,
                 min_risk: float = 0.0, pricer=None, day: str = "",
                 roll: str = "none") -> list[dict]:
    """Turn each signal into a trade carrying every (trade-mode, R) variant.

    ONE POSITION AT A TIME, enforced PER VARIANT, because the exit differs per
    variant: the same later signal can be legal under 1:2 (the first trade was
    already closed) and illegal under 1:4 (it was still running).  So the walk
    is driven per trade-mode / R pair, in signal order, carrying the minute the
    previous trade actually closed on.

    `session` additionally stops after the first placeable entry of the day.
    A skipped signal carries skipped=True for that variant and is dropped by
    summarise(), so trade counts legitimately differ between columns.
    """
    keys = rr_keys(rr_values)
    trades: list[dict] = []
    for sig in signals:
        t = dict(sig)
        t["ex"] = {}
        # PITFALL 2 - signed risk.  A zero or negative risk is not a small
        # trade, it is an entry that filled on the wrong side of its own stop.
        if sig["risk"] <= 0:
            t["dead"] = "entry at or through the stop"
        elif sig["risk"] < min_risk:
            t["dead"] = f"risk {sig['risk']} below the {min_risk:g}-point floor"
        trades.append(t)

    day_info = {}
    if pricer is not None:
        for t in trades:
            day_info[id(t)] = pricer.day_prices(day, t["side"], t["entry"], roll)

    live = [t for t in trades if "dead" not in t]
    for mode in modes:
        for rk in keys:
            open_until = -1
            done_for_day = False
            r = float(rk.split(":")[1])
            for t in live:
                t["ex"].setdefault(mode, {})
                if mode == "session" and done_for_day:
                    t["ex"][mode][rk] = {"skipped": True,
                                         "why": "one trade per session"}
                    continue
                if t["mi"] <= open_until:
                    t["ex"][mode][rk] = {"skipped": True,
                                         "why": "a position was already open"}
                    continue
                entry, sl, risk = t["entry"], t["sl"], t["risk"]
                long_ = t["side"] == "LONG"
                tgt = entry + risk * r if long_ else entry - risk * r
                res = walk(mins, t["mi"], t["side"], sl, tgt,
                           eod=eod, square_off=square_off)
                pts = (res["exit"] - entry) if long_ else (entry - res["exit"])
                t["ex"][mode][rk] = {
                    "target": round(tgt, 2),
                    "stop_level": round(sl, 2),
                    "exit": round(res["exit"], 2), "exit_time": res["exit_time"],
                    "reason": res["reason"],
                    "points": round(pts, 2), "r_multiple": round(pts / risk, 3),
                    # how far past the stop the fill actually landed
                    "slip": (round(abs(res["exit"] - sl), 2)
                             if res["reason"] == "STOP" else 0.0),
                    # The rule is decided on SPOT, but the money is made on the
                    # option that would actually have been bought.  `points` is
                    # the spot move and drives R; the percentage and the
                    # win/loss flag come from the PREMIUM, because that is what
                    # the account sees.  spot points x LOT_SIZE would be a
                    # NIFTY FUTURES payoff, which is not what this trades.
                    **_option_leg(pricer, day_info.get(id(t)), t, res),
                    "skipped": False,
                }
                open_until = res["exit_i"]
                done_for_day = True
    return trades


# ---------------------------------------------------------------------------
# Aggregation - percentages first, rupees second
# ---------------------------------------------------------------------------
#
# Every headline here is a percentage of the premium paid.  That is deliberate:
# a mean %, a win rate and a profit factor do not depend on lot size or on how
# much capital was committed, so two timeframes or two trade modes can be
# compared directly.  The rupee columns are kept because they are legible, but
# nothing is decided on them.

EMPTY_SUMMARY = {
    "days": 0, "trades": 0, "priced": 0, "unpriced": 0, "wins": 0, "losses": 0,
    "win_rate": 0.0, "pnl_prem": 0.0, "pnl_pts": 0.0, "pnl_rs": 0.0,
    "capital": 0.0, "avg_prem_perc": 0.0, "avg_win_rs": 0.0, "avg_loss_rs": 0.0,
    "rr_real": 0.0, "worst_rs": 0.0, "roi": 0.0, "stops": 0, "sqo": 0,
    "targets": 0, "slip": 0.0, "avg_r": 0.0,
}


def summarise(trades: list[dict], mode: str, rk: str) -> dict:
    rows = [t["ex"][mode][rk] for t in trades
            if t.get("ex") and t["ex"].get(mode, {}).get(rk)
            and not t["ex"][mode][rk].get("skipped")]
    n = len(rows)
    if not n:
        return dict(EMPTY_SUMMARY)
    # Money and win/loss come from the PREMIUM, because that is what the
    # account actually sees.  pnl_pts stays the SPOT move, for reference and
    # because R is measured on the spot geometry the rule defines.
    priced = [x for x in rows if x.get("prem_pts") is not None]
    wins = [x for x in priced if x["prem_pts"] > 0]
    losses_ = [x for x in priced if x["prem_pts"] <= 0]
    pts = sum(x["points"] for x in rows)
    prem = sum(x["prem_pts"] for x in priced)
    np_ = len(priced)
    # THE RISK IS THE PREMIUM PAID.  What is genuinely at risk on a bought
    # option is what it cost, so that is what the return is measured against.
    paid = [x["entry_px"] for x in priced if x.get("entry_px")]
    with_px = [x for x in priced if x.get("entry_px")]
    avg_w = (sum(x["prem_pts"] for x in wins) / len(wins)) if wins else 0.0
    avg_l = (sum(x["prem_pts"] for x in losses_) / len(losses_)) if losses_ else 0.0
    worst = min((x["prem_pts"] for x in priced), default=0.0)
    return {
        "days": len({t["date"] for t in trades}), "trades": n,
        "priced": np_, "unpriced": n - np_,
        "wins": len(wins), "losses": np_ - len(wins),
        "win_rate": round(len(wins) / np_ * 100, 1) if np_ else 0.0,
        "pnl_prem": round(prem, 2),
        "pnl_pts": round(pts, 2), "pnl_rs": round(prem * LOT_SIZE, 2),
        "capital": round(sum(paid) * LOT_SIZE, 2),
        # simple mean of each trade's premium return; unpriced rows excluded
        "avg_prem_perc": (round(sum(x["prem_pts"] / x["entry_px"] * 100
                                    for x in with_px) / len(with_px), 2)
                          if with_px else 0.0),
        "avg_win_rs": round(avg_w * LOT_SIZE, 2),
        "avg_loss_rs": round(avg_l * LOT_SIZE, 2),
        "rr_real": round(abs(avg_w / avg_l), 2) if avg_l else 0.0,
        "worst_rs": round(worst * LOT_SIZE, 2),
        "roi": round(prem / sum(paid) * 100, 2) if paid else 0.0,
        "stops": len([x for x in rows if x["reason"] == "STOP"]),
        "sqo": len([x for x in rows if x["reason"].startswith("SQUARE")]),
        "targets": len([x for x in rows if x["reason"] == "TARGET"]),
        "slip": round(sum(x["slip"] for x in rows), 2),
        "avg_r": round(sum(x["r_multiple"] for x in rows) / n, 3),
    }


def in_view(t: dict, view: str) -> bool:
    if view == "both":
        return True
    return t["side"] == ("LONG" if view == "long" else "SHORT")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def simulate_day(day: str, minutes: list[dict], tf: int, args) -> dict:
    """One session on one timeframe, run once per entry mode.

    The swings and the legs are identical between the two modes - only WHERE
    the leg is entered differs - so the structure is computed once and the legs
    are rebuilt per mode purely because find_signals stamps each one with its
    own outcome.
    """
    mins = session_minutes(minutes)
    blank = {"status": "no data", "legs": [], "trades": [], "signals": 0}
    row: dict = {"date": day, "swings": None, "day_open": None, "day_high": None,
                 "day_low": None, "day_close": None,
                 "by_entry": {em: dict(blank) for em in ENTRY_KEYS}}
    if not mins:
        return row
    bars = build_buckets(mins, tf)
    if not bars or bars[0]["start"] != OPEN_TIME:
        return row
    row["day_open"] = round(bars[0]["open"], 2)
    row["day_high"] = round(max(b["high"] for b in bars), 2)
    row["day_low"] = round(min(b["low"] for b in bars), 2)
    row["day_close"] = round(bars[-1]["close"], 2)

    highs, lows = confirmed_swings(bars, args.pivot_left, args.pivot_right)
    row["swings"] = {
        "highs": [{"t": x["time"], "p": round(x["price"], 2)} for x in highs],
        "lows": [{"t": x["time"], "p": round(x["price"], 2)} for x in lows],
    }

    for em in ENTRY_KEYS:
        sub = {"status": "no leg", "legs": [], "trades": [], "signals": 0}
        legs = build_legs(bars, highs, lows, fib_near=args.fib_near,
                          fib_far=args.fib_far, stop_offset=args.stop_offset)
        if legs:
            signals = find_signals(bars, mins, legs, leg_mode=args.legs,
                                   entry_edge=args.entry_at,
                                   virgin_only=args.virgin_only,
                                   entry_until=args.entry_until, entry_mode=em)
            sub["signals"] = len(signals)
            sub["legs"] = [{k: v for k, v in leg.items() if k != "superseded"}
                           for leg in legs]
            if not signals:
                sub["status"] = "zone never reached"
            else:
                trades = price_trades(mins, signals, rr_values=args.rr_values,
                                      modes=args.modes, eod=args.eod,
                                      square_off=args.square_off,
                                      min_risk=args.min_risk, pricer=PRICER,
                                      day=day, roll=args.expiry_roll)
                for t in trades:
                    t["date"] = day
                    leg = t.pop("leg")
                    t["leg"] = {"from_price": leg["from_price"],
                                "from_time": leg["from_time"],
                                "to_price": leg["to_price"], "to_time": leg["to_time"],
                                "size": leg["size"], "near": leg["near"],
                                "far": leg["far"], "ready_time": leg["ready_time"]}
                sub["trades"] = trades
                if any(t.get("ex") for t in trades):
                    sub["status"] = "trade"
                else:
                    why = [t.get("dead", "") for t in trades]
                    sub["status"] = ("entry through the stop"
                                     if any("through the stop" in w for w in why)
                                     else "risk below the floor")
        row["by_entry"][em] = sub
    return row


async def run(args) -> None:
    candles = await load_nifty(args.offline, args.from_date, args.to_date)
    by_day = index_by_day(candles)
    days = sorted(d for d in by_day
                  if args.from_date.isoformat() <= d <= args.to_date.isoformat())
    if not days:
        raise RuntimeError("No sessions in the requested window.")
    daily_close = await load_daily(args.offline, args.from_date, args.to_date)

    keys = rr_keys(args.rr_values)
    views = [k for k, _ in VIEWS]

    # ---- two passes, and the order is the whole point --------------------
    # Pass 1 runs the rule on SPOT alone.  Entry, stop and target are decided
    # there and nowhere else; the option cannot move a level or change which
    # trades exist.  Only once the signals are known do we resolve the ATM
    # contracts they imply and fetch whatever is missing.  Pass 2 then re-runs
    # the identical simulation with those prices available, purely so each
    # trade carries a premium figure.
    global PRICER
    needs = set()
    for tf in TIMEFRAMES:
        for d in days:
            row = simulate_day(d, by_day[d], tf, args)
            for em in ENTRY_KEYS:
                for t in row["by_entry"][em]["trades"]:
                    if t.get("ex"):
                        needs.add((t["date"], t["side"], t["entry"]))
    print(f"  {len(needs)} distinct (day, side, entry) signals to price")
    PRICER = await ensure_cached(
        needs, None if args.offline else _read_access_token(), args.offline,
        roll=args.expiry_roll)

    tf_rows: dict[str, list[dict]] = {}
    tf_trades: dict[str, dict[str, list[dict]]] = {}
    for tf in TIMEFRAMES:
        rows = [simulate_day(d, by_day[d], tf, args) for d in days]
        for r in rows:
            r["official_close"] = (round(daily_close[r["date"]], 2)
                                   if r["date"] in daily_close else None)
        tf_rows[str(tf)] = rows
        tf_trades[str(tf)] = {
            em: [t for r in rows for t in r["by_entry"][em]["trades"] if t.get("ex")]
            for em in ENTRY_KEYS}

    summaries = {
        str(tf): {v: {em: {m: {rk: summarise(
                            [t for t in tf_trades[str(tf)][em] if in_view(t, v)], m, rk)
                           for rk in keys}
                       for m in args.modes}
                      for em in ENTRY_KEYS}
                  for v in views}
        for tf in TIMEFRAMES}

    # ---- split-half ------------------------------------------------------
    # Every parameter here was either given by the spec or chosen by looking at
    # this sample.  Reporting each combination over the first and second half
    # of the sessions separately is the cheapest guard against shipping a
    # number that only exists in one half.  A setting that flips sign between
    # halves has not been demonstrated, whatever the full-sample figure says.
    mid = days[len(days) // 2]

    def half(trades, which):
        return ([t for t in trades if t["date"] < mid] if which == "h1"
                else [t for t in trades if t["date"] >= mid])

    halves = {
        str(tf): {h: {em: {m: {rk: summarise(half(tf_trades[str(tf)][em], h), m, rk)
                               for rk in keys}
                           for m in args.modes}
                      for em in ENTRY_KEYS}
                  for h in ("h1", "h2")}
        for tf in TIMEFRAMES}

    trade_days = sorted({t["date"] for tf in TIMEFRAMES
                         for em in ENTRY_KEYS for t in tf_trades[str(tf)][em]})
    chart_days = {
        d: [[c["timestamp"][11:16], round(float(c["open"]), 2),
             round(float(c["high"]), 2), round(float(c["low"]), 2),
             round(float(c["close"]), 2)]
            for c in by_day[d]
            if OPEN_TIME <= c["timestamp"][11:16] <= DAY_END]
        for d in trade_days}

    unpriced = sum(1 for tf in TIMEFRAMES for em in ENTRY_KEYS
                   for t in tf_trades[str(tf)][em]
                   for m in args.modes for rk in keys
                   if t["ex"].get(m, {}).get(rk, {}).get("opt_reason"))

    payload = {
        "meta": {
            "from": days[0], "to": days[-1], "sessions": len(days),
            "timeframes": [str(tf) for tf in TIMEFRAMES],
            "default_tf": str(args.tf),
            "pivot_left": args.pivot_left, "pivot_right": args.pivot_right,
            "fib_near": args.fib_near, "fib_far": args.fib_far,
            "stop_offset": args.stop_offset,
            "rr_keys": keys, "default_rr": rr_label(args.default_rr),
            "modes": [{"key": k, "label": v} for k, v in TRADE_MODES
                      if k in args.modes],
            "default_mode": args.mode,
            "entries": [{"key": k, "label": v} for k, v in ENTRY_MODES],
            "default_entry": args.entry_mode,
            "views": [{"key": k, "label": v} for k, v in VIEWS],
            "default_view": args.view,
            "legs": args.legs,
            "legs_label": dict(LEG_MODES)[args.legs],
            "entry_at": args.entry_at,
            "entry_at_label": dict(ENTRY_EDGES)[args.entry_at],
            "virgin_only": bool(args.virgin_only),
            "entry_until": args.entry_until,
            "min_risk": args.min_risk,
            "eod": args.eod, "eod_label": dict(EOD_MODES)[args.eod],
            "square_off": args.square_off, "session_start": args.session_start,
            "expiry_roll": args.expiry_roll,
            "expiry_roll_label": dict(ROLL_MODES)[args.expiry_roll],
            "lot": LOT_SIZE, "unpriced": unpriced,
            "generated": date.today().isoformat(),
        },
        "summaries": summaries,
        "halves": halves,
        "split_at": mid,
        "tf_days": tf_rows,
        "tf_trades": tf_trades,
        "chart_days": chart_days,
    }

    write_report(payload, args.out)

    print(f"\n{len(days)} sessions {days[0]} -> {days[-1]}")
    for tf in TIMEFRAMES:
        rows = tf_rows[str(tf)]
        for em in ENTRY_KEYS:
            status = defaultdict(int)
            for r in rows:
                status[r["by_entry"][em]["status"]] += 1
            legs = sum(len(r["by_entry"][em]["legs"]) for r in rows)
            sigs = sum(r["by_entry"][em]["signals"] for r in rows)
            print(f"\n  {tf}-minute / {em}: {legs} legs, {sigs} entries found, "
                  f"{len(tf_trades[str(tf)][em])} placeable")
            print("    sessions by outcome: "
                  + ", ".join(f"{k} {v}" for k, v in sorted(status.items(),
                                                            key=lambda kv: -kv[1])))
            for m in args.modes:
                for rk in keys:
                    o = summaries[str(tf)]["both"][em][m][rk]
                    if not o["trades"]:
                        continue
                    print(f"    {m:<7} {rk:<5}: {o['trades']:>4} tr "
                          f"{o['wins']}W/{o['losses']}L  win {o['win_rate']:>5}%  "
                          f"avg prem {o['avg_prem_perc']:>6}%  R:R {o['rr_real']:>5}:1  "
                          f"Rs {o['pnl_rs']:>10,.0f}")
    print(f"\n  SPLIT-HALF at {mid} - a setting that flips sign here is not "
          f"demonstrated, whatever the full-sample number says")
    for tf in TIMEFRAMES:
        for em in ENTRY_KEYS:
            for m in args.modes:
                rk = rr_label(args.default_rr)
                f_ = summaries[str(tf)]["both"][em][m][rk]
                a = halves[str(tf)]["h1"][em][m][rk]
                b = halves[str(tf)]["h2"][em][m][rk]
                if not f_["trades"]:
                    continue
                agree = ("" if (a["avg_prem_perc"] >= 0) == (b["avg_prem_perc"] >= 0)
                         else "   <-- HALVES DISAGREE")
                print(f"    {tf}m {em:<6} {m:<7} {rk:<5} full {f_['avg_prem_perc']:>7}% "
                      f"({f_['trades']:>4} tr)   h1 {a['avg_prem_perc']:>7}%   "
                      f"h2 {b['avg_prem_perc']:>7}%{agree}")
    if unpriced:
        print(f"\n  ! {unpriced} trade-variants had no option data and are "
              f"excluded from every percentage")
    print(f"\nReport: {args.out}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NIFTY fib retracement __FROM__ to __TO__</title>
<style>
  :root {
    color-scheme: light;
    --surface:#fcfcfb; --page:#f4f4f1; --ink:#0b0b0b; --ink2:#52514e; --muted:#8b8983;
    --grid:#e3e2db; --border:rgba(11,11,11,.10);
    --up:#128a5a; --down:#d0453f; --accent:#2a78d6; --warn:#b8860b; --zone:#7a5cd0;
    --chip:#eceae3; --chip-on:#0b0b0b; --chip-on-ink:#fff;
    --upN:18,138,90; --downN:208,69,63; --zoneN:122,92,208;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --border:rgba(255,255,255,.10);
      --up:#3ecf8e; --down:#e66767; --accent:#5b9df0; --warn:#e0b341; --zone:#a68bf0;
      --chip:#262624; --chip-on:#fff; --chip-on-ink:#0d0d0d;
      --upN:62,207,142; --downN:230,103,103; --zoneN:166,139,240;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --border:rgba(255,255,255,.10);
    --up:#3ecf8e; --down:#e66767; --accent:#5b9df0; --warn:#e0b341; --zone:#a68bf0;
    --chip:#262624; --chip-on:#fff; --chip-on-ink:#0d0d0d;
    --upN:62,207,142; --downN:230,103,103; --zoneN:166,139,240;
  }
  * { box-sizing:border-box; }
  body { background:var(--page); color:var(--ink); margin:0; padding:22px;
         font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }
  h1 { font-size:20px; margin:0 0 4px; }
  h2 { font-size:14px; margin:0 0 10px; }
  .sub { color:var(--ink2); font-size:12.5px; margin-bottom:16px; line-height:1.6; }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:10px;
          padding:14px 16px; margin-bottom:16px; }
  .tabrow { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:8px; }
  .tabrow .cap { font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
                 color:var(--muted); width:104px; flex-shrink:0; }
  .tab { padding:6px 14px; border-radius:999px; border:1px solid var(--border);
         background:var(--chip); color:var(--ink2); font-size:13px; cursor:pointer;
         font-variant-numeric:tabular-nums; }
  .tab.on { background:var(--chip-on); color:var(--chip-on-ink); border-color:transparent;
            font-weight:600; }
  .tab small { opacity:.62; margin-left:5px; font-size:11px; }
  .stat-row { display:flex; gap:22px; flex-wrap:wrap; }
  .stat { min-width:104px; }
  .stat .v { font-size:21px; font-weight:600; font-variant-numeric:tabular-nums; }
  .stat .l { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
  table { border-collapse:collapse; width:100%; font-size:12.5px; }
  th { text-align:left; color:var(--muted); font-weight:500; font-size:10.5px;
       text-transform:uppercase; letter-spacing:.04em; padding:6px 8px;
       border-bottom:1px solid var(--grid); position:sticky; top:0; background:var(--surface); }
  td { padding:5px 8px; border-bottom:1px solid var(--grid); white-space:nowrap;
       font-variant-numeric:tabular-nums; }
  tbody tr:hover { background:rgba(127,127,127,.07); }
  .num { text-align:right; }
  .pos { color:var(--up); font-weight:600; }
  .neg { color:var(--down); font-weight:600; }
  .dim { color:var(--muted); }
  .pill { display:inline-block; padding:1px 7px; border-radius:5px; font-size:11px; font-weight:600; }
  .pill.tgt { background:rgba(var(--upN),.16); color:var(--up); }
  .pill.sl { background:rgba(var(--downN),.16); color:var(--down); }
  .pill.eod { background:rgba(127,127,127,.18); color:var(--ink2); }
  .pill.no { background:rgba(184,134,11,.18); color:var(--warn); }
  .pill.long { background:rgba(var(--upN),.16); color:var(--up); }
  .pill.short { background:rgba(var(--downN),.16); color:var(--down); }
  .scroll { overflow:auto; max-height:520px; }
  .scroll.short { max-height:340px; }
  .ctrl { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:10px;
          font-size:12.5px; color:var(--ink2); }
  select, button.btn { background:var(--surface); color:var(--ink); border:1px solid var(--border);
           border-radius:6px; padding:5px 8px; font-size:12.5px; }
  button.btn { cursor:pointer; }
  button.btn:hover { background:var(--chip); }
  .chart-wrap { position:relative; }
  svg { width:100%; height:auto; display:block; }
  #chart { cursor:crosshair; touch-action:none; }
  #chart.drag { cursor:grabbing; }
  .legend { display:flex; gap:16px; flex-wrap:wrap; font-size:11.5px; color:var(--ink2);
            margin-top:8px; }
  .legend i { display:inline-block; width:14px; height:3px; vertical-align:middle;
              margin-right:5px; border-radius:2px; }
  #tip { position:absolute; pointer-events:none; background:var(--surface);
         border:1px solid var(--border); border-radius:7px; padding:7px 9px; font-size:11.5px;
         line-height:1.5; display:none; box-shadow:0 6px 20px rgba(0,0,0,.18);
         font-variant-numeric:tabular-nums; z-index:5; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media (max-width:900px) { .grid2 { grid-template-columns:1fr; } }
  table.matrix td, table.matrix th { text-align:right; }
  table.matrix td.rh, table.matrix th.rh { text-align:left; font-weight:600; }
  table.matrix tr[data-tf] { cursor:pointer; }
  table.matrix td.sel { outline:2px solid var(--accent); outline-offset:-2px; }
  .tl { list-style:none; margin:0; padding:0; font-size:12.5px; }
  .tl li { display:flex; gap:10px; padding:4px 0; border-bottom:1px solid var(--grid);
           align-items:baseline; }
  .tl .k { font-size:10px; font-weight:600; letter-spacing:.04em; padding:1px 6px;
           border-radius:4px; flex-shrink:0; width:78px; text-align:center; }
  .tl .tm { color:var(--muted); font-variant-numeric:tabular-nums; flex-shrink:0; width:44px; }
  .k.BOS { background:rgba(var(--zoneN),.18); color:var(--zone); }
  .k.ZONE { background:rgba(var(--zoneN),.12); color:var(--zone); }
  .k.TOUCH, .k.RETEST { background:rgba(42,120,214,.16); color:var(--accent); }
  .k.SWEEP { background:rgba(184,134,11,.18); color:var(--warn); }
  .k.MICROBOS { background:rgba(var(--upN),.18); color:var(--up); }
  .k.DEAD, .k.CANCEL { background:rgba(var(--downN),.16); color:var(--down); }
  .k.FILTERED { background:rgba(184,134,11,.18); color:var(--warn); }
  .k.DEAD, .k.BLOCKED, .k.SKIPPED { background:rgba(127,127,127,.18); color:var(--ink2); }
  .k.UNLOCK { background:rgba(127,127,127,.18); color:var(--ink2); }

  /* ---- used by the fib reports, absent from the NES template ---- */
  .rh { text-align:left; font-weight:600; }
  code { background:var(--chip); padding:1px 5px; border-radius:4px; font-size:11.5px; }
  .k.LEG { background:rgba(var(--zoneN),.18); color:var(--zone); }
  .k.ENTRY { background:rgba(42,120,214,.16); color:var(--accent); }
</style>
</head>
<body>
<h1>NIFTY fib retracement &mdash; the 0.618&ndash;0.786 zone</h1>
<div class="sub" id="hdr"></div>

<div class="card">
  <div class="tabrow"><span class="cap">Timeframe</span><span id="tabsF" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow"><span class="cap">Entry</span><span id="tabsE" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow"><span class="cap">Mode</span><span id="tabsM" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow"><span class="cap">Exit</span><span id="tabsT" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow"><span class="cap">View</span><span id="tabsV" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow" style="margin-bottom:0"><span class="cap">Selected</span><span id="selDesc" style="font-size:12.5px;color:var(--ink2)"></span></div>
</div>

<div class="card">
  <h2>Every timeframe &times; trade mode &times; target</h2>
  <div class="ctrl dim" id="matrixNote"></div>
  <div class="scroll"><table class="matrix" id="matrix"></table></div>
</div>

<div class="card">
  <h2>Overall &mdash; <span id="ovF"></span>, <span id="ovE"></span> entry, <span id="ovM"></span>, <span id="ovV"></span>, target <span id="ovT"></span></h2>
  <div class="stat-row" id="overall"></div>
  <div class="dim" style="font-size:12px;margin-top:10px" id="ovNote"></div>
</div>

<div class="card">
  <h2>1 vs 3 vs 5-minute &mdash; <span id="cmpWhat"></span></h2>
  <div class="ctrl dim">The timeframe changes which swings exist, so it changes the legs and
    therefore the trades themselves &mdash; not just the exits. The trade counts differ down
    the table for that reason.</div>
  <div class="scroll short"><table id="tblTf"></table></div>
</div>

<div class="card">
  <h2>How the __NDAYS__ sessions ended</h2>
  <div class="scroll short"><table id="tblStatus"></table></div>
</div>

<div class="card">
  <h2>NIFTY chart &mdash; the swing leg, the 0.618&ndash;0.786 zone and the trade</h2>
  <div class="ctrl">
    <label for="daySel">Trade day</label>
    <select id="daySel"></select>
    <button class="btn" id="zoomIn">Zoom +</button>
    <button class="btn" id="zoomOut">Zoom &minus;</button>
    <button class="btn" id="zoomReset">Whole session</button>
    <label><input type="checkbox" id="showSwings" checked> swings</label>
    <label><input type="checkbox" id="showLegs" checked> leg + zone</label>
    <span class="dim">wheel = zoom &middot; drag = pan &middot; double-click = reset</span>
  </div>
  <div class="chart-wrap"><svg id="chart" viewBox="0 0 1200 460"></svg><div id="tip"></div></div>
  <div class="legend">
    <span><i style="background:var(--zone)"></i>Swing leg and its 0.618&ndash;0.786 zone</span>
    <span class="dim">solid = the leg that was entered &middot; dashed and faint = a leg that was not</span>
    <span><i style="background:var(--down)"></i>Stop</span>
    <span><i style="background:var(--up)"></i>Target</span>
    <span><i style="background:var(--accent)"></i>Entry</span>
    <span>&#9670; Exit &middot; &#9662;&#9652; confirmed swings</span>
  </div>
  <div id="dayInfo" class="dim" style="font-size:12.5px;margin-top:8px"></div>
</div>

<div class="card">
  <h2>What happened that day</h2>
  <ul class="tl" id="timeline"></ul>
</div>

<div class="card">
  <h2>Trade by trade</h2>
  <div class="ctrl">
    <label><input type="checkbox" id="onlyTrades" checked> show only sessions that produced a trade</label>
  </div>
  <div class="scroll"><table id="tblTrades"></table></div>
</div>

<div class="grid2">
  <div class="card">
    <h2>Weekly summary</h2>
    <div class="scroll short"><table id="tblWeekly"></table></div>
  </div>
  <div class="card">
    <h2>Monthly summary</h2>
    <div class="scroll short"><table id="tblMonthly"></table></div>
  </div>
</div>
<script>
const DATA = __DATA_JSON__;
const M = DATA.meta;
const LOT = M.lot;
let curF = M.default_tf, curV = M.default_view, curM = M.default_mode,
    curT = M.default_rr, curE = M.default_entry;

const n2 = v => (v === null || v === undefined) ? '&ndash;' : (+v).toFixed(2);
const n0 = v => (v === null || v === undefined) ? '&ndash;' : (+v).toFixed(0);
const sgn = (v, d) => {
  if (v === null || v === undefined) return '&ndash;';
  const s = (+v).toFixed(d === undefined ? 2 : d);
  return '<span class="' + (v > 0 ? 'pos' : v < 0 ? 'neg' : 'dim') + '">' + (v > 0 ? '+' : '') + s + '</span>';
};
const rs = v => v === null || v === undefined ? '&ndash;'
  : '<span class="' + (v > 0 ? 'pos' : v < 0 ? 'neg' : 'dim') + '">' + (v > 0 ? '+' : '')
    + Math.round(v).toLocaleString('en-IN') + '</span>';

function inView(t, v) {
  if (v === 'both') return true;
  return t.side === (v === 'long' ? 'LONG' : 'SHORT');
}
function tradesFor(tf, v, e, m, rk) {
  return DATA.tf_trades[tf][e].filter(t => inView(t, v))
    .map(t => {
      const e = t.ex && t.ex[m] && t.ex[m][rk];
      return (!e || e.skipped) ? null : Object.assign({}, t, e);
    }).filter(Boolean);
}
function daysFor() { return DATA.tf_days[curF]; }
function S() { return DATA.summaries[curF][curV][curE][curM][curT]; }
/* the per-session record for the selected entry reading */
function dayRow(d) { return d.by_entry[curE]; }

/* A line-for-line mirror of the Python summarise(). The grouped tables below
   recompute client-side so every row uses the same arithmetic as the headline;
   if one of these changes, the other has to change with it. */
function summarise(rows) {
  const priced = rows.filter(r => r.prem_pts !== null && r.prem_pts !== undefined);
  const wins = priced.filter(r => r.prem_pts > 0);
  const losses = priced.filter(r => r.prem_pts <= 0);
  const sum = a => a.reduce((x, y) => x + y, 0);
  const withPx = priced.filter(r => r.entry_px);
  const paid = withPx.map(r => r.entry_px);
  const prem = sum(priced.map(r => r.prem_pts));
  const aW = wins.length ? sum(wins.map(r => r.prem_pts)) / wins.length : 0;
  const aL = losses.length ? sum(losses.map(r => r.prem_pts)) / losses.length : 0;
  return {
    days: Object.keys(groupBy(rows, r => r.date)).length,
    trades: rows.length, priced: priced.length, unpriced: rows.length - priced.length,
    wins: wins.length, losses: losses.length,
    win_rate: priced.length ? wins.length / priced.length * 100 : 0,
    pnl_prem: prem, pnl_pts: sum(rows.map(r => r.points)), pnl_rs: prem * LOT,
    capital: sum(paid) * LOT,
    avg_prem_perc: withPx.length
      ? sum(withPx.map(r => r.prem_pts / r.entry_px * 100)) / withPx.length : 0,
    avg_win_rs: aW * LOT, avg_loss_rs: aL * LOT,
    rr_real: aL ? Math.abs(aW / aL) : 0,
    worst_rs: priced.length ? Math.min.apply(null, priced.map(r => r.prem_pts)) * LOT : 0,
    roi: sum(paid) ? prem / sum(paid) * 100 : 0,
    stops: rows.filter(r => r.reason === 'STOP').length,
    sqo: rows.filter(r => r.reason.indexOf('SQUARE') === 0).length,
    targets: rows.filter(r => r.reason === 'TARGET').length,
    slip: sum(rows.map(r => r.slip)),
    avg_r: rows.length ? sum(rows.map(r => r.r_multiple)) / rows.length : 0,
  };
}

function groupBy(rows, keyfn) {
  const g = {};
  rows.forEach(r => { const k = keyfn(r); (g[k] = g[k] || []).push(r); });
  return g;
}
function weekKey(r) {
  const d = new Date(r.date + 'T00:00:00Z');
  const day = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - day);
  return d.toISOString().slice(0, 10);
}

function mkTabs(el, items, cur, onPick) {
  el.innerHTML = '';
  items.forEach(it => {
    const b = document.createElement('span');
    b.className = 'tab' + (it.key === cur ? ' on' : '');
    b.textContent = it.label;
    b.onclick = () => { onPick(it.key); renderAll(); };
    el.appendChild(b);
  });
}
function buildTabs() {
  mkTabs(document.getElementById('tabsF'),
    M.timeframes.map(f => ({ key: f, label: f + '-minute' })), curF, k => curF = k);
  mkTabs(document.getElementById('tabsE'),
    M.entries.map(e => ({ key: e.key, label: e.key })), curE, k => curE = k);
  mkTabs(document.getElementById('tabsM'),
    M.modes.map(m => ({ key: m.key, label: m.key })), curM, k => curM = k);
  mkTabs(document.getElementById('tabsT'),
    M.rr_keys.map(k => ({ key: k, label: k })), curT, k => curT = k);
  mkTabs(document.getElementById('tabsV'),
    M.views.map(v => ({ key: v.key, label: v.key })), curV, k => curV = k);
}

const sidePill = s => '<span class="pill ' + (s === 'LONG' ? 'long' : 'short')
  + '">' + s + '</span>';
function closePill(r) {
  const c = r === 'TARGET' ? 'tgt' : r === 'STOP' ? 'sl'
          : (r || '').indexOf('SQUARE') === 0 ? 'eod' : 'no';
  return '<span class="pill ' + c + '">' + r + '</span>';
}
function table(el, head, rows, empty) {
  if (!rows.length) { el.innerHTML = '<tr><td class="dim">' + (empty || 'nothing') + '</td></tr>'; return; }
  el.innerHTML = '<thead><tr>' + head.map(h =>
    '<th' + (h.rh ? ' class="rh"' : h.n ? ' class="num"' : '') + '>' + h.t + '</th>').join('') + '</tr></thead><tbody>'
    + rows.join('') + '</tbody>';
}

function renderHeader() {
  document.getElementById('hdr').innerHTML =
    '<b>' + M.sessions + ' sessions</b>, ' + M.from + ' &rarr; ' + M.to
    + ' &middot; swings at ' + M.pivot_left + ' left / ' + M.pivot_right + ' right'
    + ' &middot; zone ' + M.fib_near + '&ndash;' + M.fib_far
    + ' &middot; stop ' + M.stop_offset + ' pts past ' + M.fib_far
    + ' &middot; entry at the ' + (M.entry_at === '618' ? M.fib_near : M.fib_far) + ' level'
    + ' &middot; <code>' + curE + '</code>'
    + ' &middot; legs: <code>' + M.legs + '</code>'
    + (M.virgin_only ? ' &middot; <code>virgin zones only</code>' : '')
    + ' &middot; ' + M.eod_label + ' ' + M.square_off
    + ' &middot; ATM option, ' + M.expiry_roll_label.toLowerCase()
    + ' &middot; lot ' + M.lot
    + '<br>Generated ' + M.generated + '. Every percentage is of the premium paid for that '
    + 'trade. Rupee columns are that percentage times the lot, shown for legibility only.';
}

function renderMatrixNote() {
  document.getElementById('matrixNote').innerHTML =
    'The timeframe changes which swings exist, so it changes the legs and therefore the '
    + 'trades themselves &mdash; not just the exits. <b>Entry</b> is how the zone is taken: '
    + '<code>touch</code> is a resting limit that fills the first time price reaches the '
    + '0.618 edge, <code>retest</code> waits for price to be rejected back out of the zone '
    + '(a close beyond that edge) and buys the return. <b>Mode</b> is the trade-count rule: '
    + '<code>flow</code> re-enters whenever a leg arms and the book is flat, '
    + '<code>session</code> takes the first entry of the day and then stops. '
    + 'Win / loss and every rupee figure come from the ATM option premium, not from spot. '
    + 'Click any row to select it.';
}

function statBlock(s) {
  return [
    [s.days, 'trade days'], [s.trades, 'trades'],
    [s.wins, 'success'], [s.losses, 'fail'],
    [s.win_rate.toFixed(1) + '%', 'win rate'],
    [s.rr_real.toFixed(2) + ' : 1', 'reward : risk (real)'],
    [sgn(s.pnl_pts, 2), 'NIFTY move (pts)'],
    [sgn(s.pnl_prem, 2), 'option premium (pts)'],
    [rs(s.pnl_rs), 'net PnL (1 lot Rs, premium)'],
    [sgn(s.avg_prem_perc, 2) + '%', 'avg premium % / trade'],
    [rs(s.avg_win_rs), 'avg win (Rs)'],
    [rs(s.avg_loss_rs), 'avg loss (Rs)'],
    [rs(s.worst_rs), 'worst single loss (Rs)'],
    [Math.round(s.capital).toLocaleString('en-IN'), 'premium deployed (Rs)'],
    [s.roi.toFixed(2) + '%', 'return on premium'],
  ].map(c => '<div class="stat"><div class="v">' + c[0] + '</div><div class="l">'
             + c[1] + '</div></div>').join('');
}

function renderOverall() {
  const s = S();
  document.getElementById('ovF').textContent = curF + '-minute';
  document.getElementById('ovE').textContent = curE;
  document.getElementById('ovM').textContent = curM;
  document.getElementById('ovT').textContent = curT;
  document.getElementById('ovV').textContent = curV;
  document.getElementById('overall').innerHTML = statBlock(s);
  document.getElementById('ovNote').innerHTML =
    s.priced + ' of ' + s.trades + ' trades priced on a real ATM contract'
    + (s.unpriced ? '; <b>' + s.unpriced + ' had no option data and are excluded from the '
                    + 'money totals</b>' : '')
    + '. Exits: ' + s.stops + ' stopped, ' + s.targets + ' target, ' + s.sqo + ' squared off.';
  document.getElementById('selDesc').innerHTML =
    (M.entries.filter(e => e.key === curE)[0] || {}).label + ' &middot; '
    + (M.modes.filter(m => m.key === curM)[0] || {}).label
    + ' &middot; target ' + curT + ' off the signed risk'
    + ' &middot; ' + (M.views.filter(v => v.key === curV)[0] || {}).label.toLowerCase();
}

function renderMatrix() {
  let max = 1;
  M.timeframes.forEach(f => M.entries.forEach(e => M.modes.forEach(m => M.rr_keys.forEach(rk =>
    max = Math.max(max, Math.abs(DATA.summaries[f][curV][e.key][m.key][rk].pnl_rs))))));
  const rows = [];
  M.timeframes.forEach(f => M.entries.forEach(e => M.modes.forEach(m => M.rr_keys.forEach(rk => {
    const st = DATA.summaries[f][curV][e.key][m.key][rk];
    const a = (Math.abs(st.pnl_rs) / max * 0.5).toFixed(3);
    const bg = st.pnl_rs >= 0 ? 'rgba(var(--upN),' + a + ')' : 'rgba(var(--downN),' + a + ')';
    const sel = (f === curF && e.key === curE && m.key === curM && rk === curT) ? ' sel' : '';
    rows.push('<tr data-tf="' + f + '" data-en="' + e.key + '" data-md="' + m.key
      + '" data-rk="' + rk + '">'
      + '<td class="rh' + sel + '">' + f + '-minute</td>'
      + '<td class="rh' + sel + '">' + e.key + '</td>'
      + '<td class="rh' + sel + '">' + m.key + '</td>'
      + '<td class="rh' + sel + '">' + rk + '</td>'
      + '<td>' + st.trades + '</td>'
      + '<td class="pos">' + st.wins + '</td><td class="neg">' + st.losses + '</td>'
      + '<td>' + st.win_rate.toFixed(1) + '%</td>'
      + '<td class="neg">' + st.stops + '</td><td class="pos">' + st.targets + '</td>'
      + '<td>' + st.sqo + '</td>'
      + '<td>' + rs(st.avg_win_rs) + '</td><td>' + rs(st.avg_loss_rs) + '</td>'
      + '<td>' + st.rr_real.toFixed(2) + ' : 1</td><td>' + rs(st.worst_rs) + '</td>'
      + '<td>' + sgn(st.avg_prem_perc, 2) + '%</td>'
      + '<td class="' + sel + '" style="background:' + bg + '">' + rs(st.pnl_rs) + '</td>'
      + '<td>' + st.roi.toFixed(2) + '%</td></tr>');
  }))));
  table(document.getElementById('matrix'), [
    { t: 'Timeframe', rh: 1 }, { t: 'Entry', rh: 1 }, { t: 'Mode', rh: 1 },
    { t: 'Exit', rh: 1 },
    { t: 'Trades', n: 1 }, { t: 'Won', n: 1 }, { t: 'Lost', n: 1 },
    { t: 'Win rate', n: 1 }, { t: 'Exit: stop', n: 1 }, { t: 'Exit: target', n: 1 },
    { t: 'Exit: square-off', n: 1 }, { t: 'Avg win (Rs)', n: 1 },
    { t: 'Avg loss (Rs)', n: 1 }, { t: 'Reward : risk', n: 1 },
    { t: 'Worst loss (Rs)', n: 1 }, { t: 'Avg Prem %', n: 1 },
    { t: 'Net (Rs/lot)', n: 1 }, { t: 'Return on premium', n: 1 }], rows);
  const host = document.getElementById('matrix');
  const trs = host.querySelectorAll ? host.querySelectorAll('tr[data-tf]') : [];
  Array.prototype.forEach.call(trs, tr => {
    tr.onclick = () => {
      curF = tr.getAttribute('data-tf'); curE = tr.getAttribute('data-en');
      curM = tr.getAttribute('data-md'); curT = tr.getAttribute('data-rk');
      renderAll();
    };
  });
}

function renderTfCompare() {
  document.getElementById('cmpWhat').textContent =
    curE + ' entry, ' + curM + ', target ' + curT + ', ' + curV;
  const rows = M.timeframes.map(f => {
    const o = DATA.summaries[f][curV][curE][curM][curT];
    const sel = f === curF;
    return '<tr style="' + (sel ? 'background:rgba(var(--zoneN),.10)' : '') + '">'
      + '<td>' + f + '-minute</td>'
      + '<td class="num">' + o.days + '</td><td class="num">' + o.trades + '</td>'
      + '<td class="num pos">' + o.wins + '</td><td class="num neg">' + o.losses + '</td>'
      + '<td class="num">' + o.win_rate.toFixed(1) + '%</td>'
      + '<td class="num">' + o.avg_r.toFixed(2) + '</td>'
      + '<td class="num">' + o.stops + '</td>'
      + '<td class="num">' + n2(o.slip) + '</td>'
      + '<td class="num">' + sgn(o.pnl_pts, 2) + '</td>'
      + '<td class="num">' + rs(o.pnl_rs) + '</td>'
      + '<td class="num">' + sgn(o.avg_prem_perc, 2) + '%</td></tr>';
  });
  table(document.getElementById('tblTf'), [
    { t: 'Timeframe' }, { t: 'Trade days', n: 1 }, { t: 'Trades', n: 1 },
    { t: 'Success', n: 1 }, { t: 'Fail', n: 1 }, { t: 'Win %', n: 1 },
    { t: 'Avg R', n: 1 }, { t: 'Stops', n: 1 }, { t: 'Slip (pts)', n: 1 },
    { t: 'Net PnL (pts)', n: 1 }, { t: 'Net PnL (Rs)', n: 1 },
    { t: 'Avg Prem %', n: 1 }], rows);
}

function renderStatus() {
  const c = {};
  daysFor().forEach(d => { const r = dayRow(d); c[r.status] = (c[r.status] || 0) + 1; });
  const legOut = {};
  daysFor().forEach(d => (dayRow(d).legs || []).forEach(l => {
    legOut[l.outcome] = (legOut[l.outcome] || 0) + 1;
  }));
  const rows = Object.keys(c).sort((a, b) => c[b] - c[a]).map(k =>
    '<tr><td>session</td><td>' + k + '</td><td class="num">' + c[k] + '</td>'
    + '<td class="num dim">' + n2(c[k] / M.sessions * 100) + '%</td></tr>');
  const tot = Object.keys(legOut).reduce((a, k) => a + legOut[k], 0);
  Object.keys(legOut).sort((a, b) => legOut[b] - legOut[a]).forEach(k =>
    rows.push('<tr><td class="dim">leg</td><td>' + k + '</td><td class="num">' + legOut[k]
      + '</td><td class="num dim">' + n2(legOut[k] / tot * 100) + '%</td></tr>'));
  table(document.getElementById('tblStatus'),
    [{ t: 'Level' }, { t: 'Outcome' }, { t: 'Count', n: 1 }, { t: 'Share', n: 1 }], rows);
}

/* ---------------- chart ---------------- */
const W = 1200, H = 460, PADL = 46, PADR = 62, PADT = 16, PADB = 26;
const svg = document.getElementById('chart');
const tip = document.getElementById('tip');
let chartState = null;

function tmin(t) { return (+t.slice(0, 2)) * 60 + (+t.slice(3, 5)); }
function bucketize(rows, tf) {
  if (+tf === 1) return rows;
  const out = [], n = +tf;
  for (let i = 0; i < rows.length; i += n) {
    const g = rows.slice(i, i + n);
    out.push([g[0][0], g[0][1], Math.max.apply(null, g.map(x => x[2])),
              Math.min.apply(null, g.map(x => x[3])), g[g.length - 1][4]]);
  }
  return out;
}
function clampWindow(n, i0, i1) {
  let span = Math.max(8, Math.min(n, i1 - i0));
  if (i0 < 0) i0 = 0;
  if (i0 + span > n) i0 = n - span;
  return [i0, i0 + span];
}

function drawChart() {
  if (!chartState) { svg.innerHTML = ''; return; }
  const { c, day, drow, trades, legs, taken } = chartState;
  let [i0, i1] = [chartState.i0, chartState.i1];
  const view = c.slice(Math.floor(i0), Math.ceil(i1));
  if (!view.length) return;
  const showLegs = document.getElementById('showLegs').checked;
  const lvls = [];
  trades.forEach(t => {
    lvls.push(t.stop_level, t.entry);
    if (t.target !== null && t.target !== undefined) lvls.push(t.target);
  });
  if (showLegs) (legs || []).forEach(l => {
    lvls.push(l.near, l.far, l.from_price, l.to_price);
  });
  let lo = Math.min.apply(null, view.map(x => x[3]).concat(lvls));
  let hi = Math.max.apply(null, view.map(x => x[2]).concat(lvls));
  const pad = (hi - lo) * 0.06 || 10; lo -= pad; hi += pad;

  const iw = W - PADL - PADR, ih = H - PADT - PADB;
  const span = i1 - i0;
  const x = i => PADL + (i - i0 + 0.5) * iw / span;
  const y = v => PADT + (hi - v) * ih / (hi - lo);
  const bw = Math.max(1.2, iw / span * 0.62);
  const at = t => {
    if (!t) return -1;
    const k = Math.floor((tmin(t) - tmin('09:15')) / (+curF));
    return (k >= 0 && k < c.length) ? k : -1;
  };

  let s = '';
  /* Every leg the session produced.  A leg that was entered is drawn solid and
     labelled; one that was never entered is drawn faintly with its outcome,
     because the fib structure is what the rule reacted to whether or not it
     ended in a trade. */
  if (showLegs) (legs || []).forEach(l => {
    const hit = !!taken[l.from_time + '|' + l.to_time];
    const zi = at(l.ready_time);
    if (zi < 0) return;
    const zx = Math.max(PADL, x(zi) - bw / 2);
    const yt = y(Math.max(l.near, l.far));
    const yb = y(Math.min(l.near, l.far));
    const fill = hit ? '.13' : '.05';
    const op = hit ? '1' : '.5';
    s += '<rect x="' + zx.toFixed(1) + '" y="' + yt.toFixed(1) + '" width="'
       + (PADL + iw - zx).toFixed(1) + '" height="' + Math.max(1, yb - yt).toFixed(1)
       + '" fill="rgba(var(--zoneN),' + fill + ')" stroke="var(--zone)" stroke-width="1"'
       + ' stroke-dasharray="3 3" opacity="' + op + '"/>';
    const ai = at(l.from_time), bi = at(l.to_time);
    if (ai >= 0 && bi >= 0) {
      const dash = hit ? '' : ' stroke-dasharray="4 3"';
      s += '<line x1="' + x(ai) + '" y1="' + y(l.from_price) + '" x2="' + x(bi)
         + '" y2="' + y(l.to_price) + '" stroke="var(--zone)" stroke-width="'
         + (hit ? '1.8' : '1') + '" opacity="' + (hit ? '.9' : '.45') + '"' + dash + '/>'
         + '<circle cx="' + x(ai) + '" cy="' + y(l.from_price) + '" r="' + (hit ? 3 : 2)
         + '" fill="var(--zone)" opacity="' + op + '"/>'
         + '<circle cx="' + x(bi) + '" cy="' + y(l.to_price) + '" r="' + (hit ? 3 : 2)
         + '" fill="var(--zone)" opacity="' + op + '"/>';
    }
    s += '<text x="' + (zx + 4).toFixed(1) + '" y="' + (yt - 4).toFixed(1)
       + '" font-size="10" fill="var(--zone)" opacity="' + op + '">'
       + l.side + ' ' + l.size.toFixed(0) + 'pt &middot; ' + l.near.toFixed(2)
       + ' &ndash; ' + l.far.toFixed(2)
       + (hit ? '' : ' &middot; ' + l.outcome) + '</text>';
  });
  for (let k = 0; k <= 6; k++) {
    const v = lo + (hi - lo) * k / 6, yy = y(v);
    s += '<line x1="' + PADL + '" y1="' + yy + '" x2="' + (PADL + iw) + '" y2="' + yy
       + '" stroke="var(--grid)"/><text x="' + (PADL + iw + 6) + '" y="' + (yy + 3.5)
       + '" font-size="10" fill="var(--muted)">' + v.toFixed(0) + '</text>';
  }
  const step = Math.max(1, Math.round(span / 10));
  for (let i = Math.ceil(i0); i < i1; i++) {
    if ((i - Math.ceil(i0)) % step) continue;
    s += '<text x="' + x(i) + '" y="' + (H - 8) + '" font-size="10" fill="var(--muted)" '
       + 'text-anchor="middle">' + c[i][0] + '</text>'
       + '<line x1="' + x(i) + '" y1="' + PADT + '" x2="' + x(i) + '" y2="' + (PADT + ih)
       + '" stroke="var(--grid)" opacity=".55"/>';
  }
  for (let i = Math.floor(i0); i < Math.ceil(i1) && i < c.length; i++) {
    const o = c[i][1], h = c[i][2], l = c[i][3], cl = c[i][4];
    const col = cl >= o ? 'var(--up)' : 'var(--down)';
    const yo = y(o), yc = y(cl);
    s += '<line x1="' + x(i).toFixed(2) + '" y1="' + y(h).toFixed(2) + '" x2="' + x(i).toFixed(2)
       + '" y2="' + y(l).toFixed(2) + '" stroke="' + col + '"/>'
       + '<rect x="' + (x(i) - bw / 2).toFixed(2) + '" y="' + Math.min(yo, yc).toFixed(2)
       + '" width="' + bw.toFixed(2) + '" height="' + Math.max(1, Math.abs(yc - yo)).toFixed(2)
       + '" fill="' + col + '"/>';
  }
  if (document.getElementById('showSwings').checked && drow && drow.swings) {
    drow.swings.highs.forEach(sw => {
      const i = at(sw.t); if (i < i0 - 1 || i > i1) return;
      s += '<polygon points="' + x(i) + ',' + (y(sw.p) - 9) + ' ' + (x(i) - 4) + ','
         + (y(sw.p) - 3) + ' ' + (x(i) + 4) + ',' + (y(sw.p) - 3)
         + '" fill="var(--muted)" opacity=".8"/>';
    });
    drow.swings.lows.forEach(sw => {
      const i = at(sw.t); if (i < i0 - 1 || i > i1) return;
      s += '<polygon points="' + x(i) + ',' + (y(sw.p) + 9) + ' ' + (x(i) - 4) + ','
         + (y(sw.p) + 3) + ' ' + (x(i) + 4) + ',' + (y(sw.p) + 3)
         + '" fill="var(--muted)" opacity=".8"/>';
    });
  }
  const hline = (v, col, dash, label, atEnd) => v === null || v === undefined ? '' :
    '<line x1="' + PADL + '" y1="' + y(v) + '" x2="' + (PADL + iw) + '" y2="' + y(v)
    + '" stroke="' + col + '" stroke-width="1.3" stroke-dasharray="' + dash + '" opacity=".9"/>'
    + '<text x="' + (atEnd ? PADL + iw - 4 : PADL + 4) + '" y="' + (y(v) - 4)
    + '" font-size="10" fill="' + col + '"' + (atEnd ? ' text-anchor="end"' : '') + '>'
    + label + ' ' + v.toFixed(2) + '</text>';

  trades.forEach(t => {
    s += hline(t.stop_level, 'var(--down)', '6 3', 'Stop (' + n2(t.risk) + ' pts)');
    if (t.target !== null && t.target !== undefined)
      s += hline(t.target, 'var(--up)', '6 3', 'Target ' + curT, true);
    const ei = at(t.entry_time);
    if (ei >= 0) {
      const ex = x(ei), ey = y(t.entry);
      s += '<line x1="' + ex + '" y1="' + PADT + '" x2="' + ex + '" y2="' + (PADT + ih)
         + '" stroke="var(--accent)" stroke-width="1.1" stroke-dasharray="3 3"/>'
         + (t.side === 'LONG'
            ? '<polygon points="' + ex + ',' + ey + ' ' + (ex - 6) + ',' + (ey + 12) + ' ' + (ex + 6) + ',' + (ey + 12) + '" fill="var(--accent)"/>'
            : '<polygon points="' + ex + ',' + ey + ' ' + (ex - 6) + ',' + (ey - 12) + ' ' + (ex + 6) + ',' + (ey - 12) + '" fill="var(--accent)"/>')
         + '<text x="' + (ex + 9) + '" y="' + (ey + (t.side === 'LONG' ? 16 : -16))
         + '" font-size="11" font-weight="600" fill="var(--accent)">'
         + (t.side === 'LONG' ? 'BUY' : 'SELL') + ' @ ' + t.entry.toFixed(2) + '</text>';
    }
    const xi = at(t.exit_time);
    if (xi >= 0) {
      const xx = x(xi), xy = y(t.exit);
      const col = (t.prem_perc !== null && t.prem_perc !== undefined ? t.prem_perc : t.points) > 0
        ? 'var(--up)' : 'var(--down)';
      s += '<polygon points="' + xx + ',' + (xy - 7) + ' ' + (xx + 7) + ',' + xy + ' ' + xx + ','
         + (xy + 7) + ' ' + (xx - 7) + ',' + xy + '" fill="' + col
         + '" stroke="var(--surface)" stroke-width="1.2"/>'
         + '<text x="' + (xx + 11) + '" y="' + (xy + 4) + '" font-size="11" font-weight="600" '
         + 'fill="' + col + '">' + (t.reason || '').split(' ')[0] + ' @ ' + t.exit.toFixed(2)
         + '</text>';
    }
  });
  const a = c[Math.floor(i0)], b = c[Math.min(c.length - 1, Math.ceil(i1) - 1)];
  s += '<text x="' + (PADL + iw - 2) + '" y="' + (H - 8) + '" font-size="10" fill="var(--muted)" '
     + 'text-anchor="end">' + day + ' &middot; ' + a[0] + ' &ndash; ' + b[0] + ' &middot; '
     + curF + '-minute</text>';
  svg.innerHTML = s;
}

function renderChart() {
  const day = document.getElementById('daySel').value;
  const info = document.getElementById('dayInfo');
  if (!day || !DATA.chart_days[day]) { chartState = null; svg.innerHTML = ''; info.textContent = ''; return; }
  const c = bucketize(DATA.chart_days[day], curF);
  const drow = daysFor().filter(d => d.date === day)[0];
  const trades = tradesFor(curF, curV, curE, curM, curT).filter(t => t.date === day);
  // EVERY leg the session produced, not only the ones that became a trade.
  // 44 of the 123 selectable sessions have legs but no trade in the variant the
  // report opens on, and drawing the structure only when a trade fired left
  // those sessions looking empty.
  const legs = (drow && dayRow(drow).legs) || [];
  const taken = {};
  trades.forEach(t => { taken[t.leg.from_time + '|' + t.leg.to_time] = t; });
  // keep the window the user is looking at when only the tab changed
  const keep = (chartState && chartState.day === day && chartState.tf === curF)
    ? [chartState.i0, chartState.i1] : [0, c.length];
  chartState = { c: c, day: day, tf: curF, drow: drow, trades: trades,
                 legs: legs, taken: taken, i0: keep[0], i1: keep[1] };
  const w = clampWindow(c.length, chartState.i0, chartState.i1);
  chartState.i0 = w[0]; chartState.i1 = w[1];
  drawChart();
  if (drow) {
    info.innerHTML = 'Open ' + n2(drow.day_open) + ' &middot; high ' + n2(drow.day_high)
      + ' &middot; low ' + n2(drow.day_low) + ' &middot; 15:29 print ' + n2(drow.day_close)
      + (drow.official_close !== null && drow.official_close !== undefined
         ? ' &middot; <b>official close ' + n2(drow.official_close) + '</b> (differs by '
           + n2(Math.abs(drow.official_close - drow.day_close)) + ')' : '')
      + ' &middot; ' + (dayRow(drow).legs || []).length + ' legs, '
      + dayRow(drow).signals + ' entries found, '
      + trades.length + ' trades in this variant';
  }
}

/* Outcome -> the house event-kind badge, so the fib timeline reads like the
   NES one: a time column, a coloured kind, then the sentence. */
function legKind(o) {
  if (o === 'zone entered') return 'RETEST';
  if (o === 'entry through the stop') return 'BLOCKED';
  if (o.indexOf('broken') >= 0) return 'CANCEL';
  if (o.indexOf('cut-off') >= 0) return 'FILTERED';
  if (o.indexOf('drawable') >= 0) return 'SKIPPED';
  return 'DEAD';
}
function legLine(l, t) {
  const out = [];
  out.push('<li><span class="tm">' + l.ready_time + '</span>'
    + '<span class="k LEG">LEG</span><span>' + sidePill(l.side) + ' '
    + n2(l.from_price) + ' &rarr; ' + n2(l.to_price) + ' (' + n2(l.size)
    + ' pts) &middot; zone <b>' + n2(l.near) + '</b>&ndash;' + n2(l.far)
    + ', stop ' + n2(l.sl) + '</span></li>');
  out.push('<li><span class="tm">' + (l.touched_at || l.ready_time) + '</span>'
    + '<span class="k ' + legKind(l.outcome) + '">' + legKind(l.outcome) + '</span>'
    + '<span>' + l.outcome + '</span></li>');
  if (t) out.push('<li><span class="tm">' + t.entry_time + '</span>'
    + '<span class="k ENTRY">ENTRY</span><span>' + sidePill(t.side) + ' @ ' + n2(t.entry)
    + ' &middot; stop ' + (t.stop_level === null ? 'none' : n2(t.stop_level))
    + ', target ' + n2(t.target) + ' &rarr; ' + closePill(t.reason) + ' '
    + t.exit_time + ' @ ' + n2(t.exit) + ' &middot; ' + sgn(t.prem_perc, 2)
    + '% of premium</span></li>');
  return out.join('');
}
function renderTimeline() {
  const day = document.getElementById('daySel').value;
  const drow = daysFor().filter(d => d.date === day)[0];
  const el = document.getElementById('timeline');
  const legs = (drow && dayRow(drow).legs) || [];
  if (!legs.length) { el.innerHTML = '<li class="dim">nothing to show</li>'; return; }
  const taken = {};
  tradesFor(curF, curV, curE, curM, curT).filter(t => t.date === day)
    .forEach(t => { taken[t.leg.from_time + '|' + t.leg.to_time] = t; });
  el.innerHTML = legs.map(l => legLine(l, taken[l.from_time + '|' + l.to_time])).join('');
}

function closePill(r) {
  const c = r === 'TARGET' ? 'up' : r === 'STOP' ? 'down' : 'zone';
  return '<span class="pill ' + c + '">' + r + '</span>';
}
function renderTrades() {
  const only = document.getElementById('onlyTrades').checked;
  const byDay = groupBy(tradesFor(curF, curV, curE, curM, curT), r => r.date);
  const out = [];
  daysFor().forEach(d => {
    const ts = byDay[d.date] || [];
    const drow = dayRow(d);
    if (!ts.length) {
      if (only) return;
      out.push('<tr><td>' + d.date + '</td>'
        + '<td colspan="20" class="dim">&mdash;</td>'
        + '<td class="dim">' + drow.status + '</td></tr>');
      return;
    }
    ts.forEach(r => out.push(
      '<tr><td>' + r.date + '</td>'
      + '<td><span class="pill ' + (r.side === 'LONG' ? 'up' : 'down') + '">' + r.side + '</span></td>'
      + '<td class="dim">' + n2(r.leg.from_price) + ' &rarr; ' + n2(r.leg.to_price) + '</td>'
      + '<td class="num dim">' + n2(r.leg.size) + '</td>'
      + '<td class="dim">' + n2(r.leg.near) + ' &ndash; ' + n2(r.leg.far) + '</td>'
      + '<td>' + r.entry_time + '</td><td class="num">' + n2(r.entry) + '</td>'
      + '<td class="num dim">' + n2(r.stop_level) + '</td>'
      + '<td class="num dim">' + n2(r.risk) + '</td>'
      + '<td class="num dim">' + n2(r.target) + '</td>'
      + '<td class="num">' + n2(r.exit) + '</td><td>' + closePill(r.reason) + '</td>'
      + '<td class="num">' + sgn(r.points) + '</td><td class="num">' + sgn(r.r_multiple, 2) + '</td>'
      + '<td class="dim">' + (r.opt_symbol || '&mdash;') + '</td>'
      + '<td class="num dim">' + n2(r.entry_px) + '</td>'
      + '<td class="num dim">' + n2(r.exit_px) + '</td>'
      + '<td class="num">' + sgn(r.prem_pts) + '</td>'
      + '<td class="num">' + sgn(r.prem_perc, 2) + '%</td>'
      + '<td class="num">' + rs(r.pnl_rs) + '</td>'
      + '<td>' + r.exit_time + '</td>'
      + '<td class="dim">' + (r.opt_reason || '') + '</td></tr>'));
  });
  table(document.getElementById('tblTrades'), [
    { t: 'Date' }, { t: 'Dir' }, { t: 'Leg' }, { t: 'Leg pts', n: 1 },
    { t: 'Zone 0.618-0.786' }, { t: 'Entry time' }, { t: 'Entry', n: 1 },
    { t: 'Stop', n: 1 }, { t: 'Risk', n: 1 }, { t: 'Target', n: 1 },
    { t: 'Exit', n: 1 }, { t: 'Close type' }, { t: 'NIFTY pts', n: 1 },
    { t: 'R', n: 1 }, { t: 'Contract' }, { t: 'Prem in', n: 1 },
    { t: 'Prem out', n: 1 }, { t: 'Prem pts', n: 1 }, { t: 'Prem %', n: 1 },
    { t: 'PnL (Rs)', n: 1 }, { t: 'Exit time' }, { t: 'Note' }],
    out, 'no trades in this variant');
}

function summaryTable(el, rows, label) {
  const g = groupBy(rows, label === 'Month' ? (r => r.date.slice(0, 7)) : weekKey);
  const out = Object.keys(g).sort().map(k => {
    const s = summarise(g[k]);
    return '<tr><td>' + k + '</td><td class="num">' + s.days + '</td>'
      + '<td class="num">' + s.trades + '</td>'
      + '<td class="num pos">' + s.wins + '</td><td class="num neg">' + s.losses + '</td>'
      + '<td class="num">' + s.win_rate.toFixed(1) + '%</td>'
      + '<td class="num">' + sgn(s.avg_r, 2) + '</td>'
      + '<td class="num">' + sgn(s.pnl_pts, 2) + '</td>'
      + '<td class="num">' + rs(s.pnl_rs) + '</td>'
      + '<td class="num">' + sgn(s.avg_prem_perc, 1) + '%</td></tr>';
  });
  table(el, [{ t: label }, { t: 'Trade days', n: 1 }, { t: 'Trades', n: 1 },
             { t: 'Success', n: 1 }, { t: 'Fail', n: 1 }, { t: 'Win %', n: 1 },
             { t: 'Avg R', n: 1 }, { t: 'Net PnL (pts)', n: 1 },
             { t: 'Net PnL (Rs)', n: 1 }, { t: 'Avg Prem %', n: 1 }], out);
}

function zoomAt(factor, anchor) {
  if (!chartState) return;
  const c = chartState.c;
  const i0 = chartState.i0, i1 = chartState.i1;
  const a = anchor === undefined ? (i0 + i1) / 2 : anchor;
  const w = clampWindow(c.length, a - (a - i0) * factor, a + (i1 - a) * factor);
  chartState.i0 = w[0]; chartState.i1 = w[1];
  drawChart();
}
function resetZoom() {
  if (!chartState) return;
  chartState.i0 = 0; chartState.i1 = chartState.c.length; drawChart();
}
/* index under the cursor, in bar coordinates */
function idxAt(clientX, box) {
  const px = (clientX - box.left) / box.width * W;
  return chartState.i0 + (px - PADL) / (W - PADL - PADR)
         * (chartState.i1 - chartState.i0);
}
svg.addEventListener('wheel', e => {
  if (!chartState) return;
  e.preventDefault();
  zoomAt(e.deltaY < 0 ? 0.82 : 1.22, idxAt(e.clientX, svg.getBoundingClientRect()));
}, { passive: false });
let drag = null;
svg.addEventListener('pointerdown', e => {
  if (!chartState) return;
  drag = { x: e.clientX, i0: chartState.i0, i1: chartState.i1 };
  svg.classList.add('drag');
  try { svg.setPointerCapture(e.pointerId); } catch (_) {}
});
svg.addEventListener('pointerup', e => {
  drag = null; svg.classList.remove('drag');
  try { svg.releasePointerCapture(e.pointerId); } catch (_) {}
});
svg.addEventListener('dblclick', resetZoom);
svg.addEventListener('pointermove', e => {
  if (!chartState) return;
  const box = svg.getBoundingClientRect();
  if (drag) {
    const dx = (e.clientX - drag.x) / box.width * W;
    const perPx = (drag.i1 - drag.i0) / (W - PADL - PADR);
    const w = clampWindow(chartState.c.length, drag.i0 - dx * perPx,
                          drag.i1 - dx * perPx);
    chartState.i0 = w[0]; chartState.i1 = w[1];
    drawChart();
    tip.style.display = 'none';
    return;
  }
  const i = Math.round(idxAt(e.clientX, box) - 0.5);
  const c = chartState.c;
  if (i < 0 || i >= c.length) { tip.style.display = 'none'; return; }
  tip.innerHTML = '<b>' + c[i][0] + '</b> <span style="opacity:.6">' + chartState.day
    + '</span><br>O ' + c[i][1].toFixed(2) + '<br>H ' + c[i][2].toFixed(2)
    + '<br>L ' + c[i][3].toFixed(2) + '<br>C ' + c[i][4].toFixed(2);
  tip.style.display = 'block';
  tip.style.left = Math.min(e.clientX - box.left + 14, box.width - 110) + 'px';
  tip.style.top = Math.max(0, e.clientY - box.top - 60) + 'px';
});
svg.addEventListener('pointerleave', () => { tip.style.display = 'none'; });

function renderAll() {
  buildTabs();
  renderHeader();
  renderMatrixNote();
  renderMatrix();
  renderOverall();
  renderTfCompare();
  renderStatus();
  const sel = document.getElementById('daySel');
  const days = Object.keys(DATA.chart_days).sort();
  const keep = sel.value;
  sel.innerHTML = days.map(d => '<option' + (d === keep ? ' selected' : '') + '>' + d + '</option>').join('');
  if (!keep && days.length) sel.value = days[0];
  renderChart();
  renderTimeline();
  renderTrades();
  const rows = tradesFor(curF, curV, curE, curM, curT);
  summaryTable(document.getElementById('tblWeekly'), rows, 'Week');
  summaryTable(document.getElementById('tblMonthly'), rows, 'Month');
}

document.getElementById('daySel').onchange = () => { renderChart(); renderTimeline(); };
document.getElementById('onlyTrades').onchange = renderTrades;
document.getElementById('showSwings').onchange = drawChart;
document.getElementById('showLegs').onchange = drawChart;
document.getElementById('zoomIn').onclick = () => zoomAt(0.7);
document.getElementById('zoomOut').onclick = () => zoomAt(1.4);
document.getElementById('zoomReset').onclick = resetZoom;
renderAll();
</script>
</body>
</html>
"""


def write_report(payload: dict, out_path: str) -> None:
    html = (HTML_TEMPLATE
            .replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":")))
            .replace("__FROM__", payload["meta"]["from"])
            .replace("__TO__", payload["meta"]["to"])
            .replace("__NDAYS__", str(payload["meta"]["sessions"])))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  report {len(html) / 1e6:.1f} MB")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    today = date.today()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tf", type=int, choices=TIMEFRAMES, default=DEFAULT_TF,
                    help="timeframe selected when the report opens; all are "
                         "always computed")
    ap.add_argument("--pivot-left", type=int, default=PIVOT_LEFT,
                    help="candles before a pivot that it must beat (the spec's "
                         "prose says 8; its index ranges say 9)")
    ap.add_argument("--pivot-right", type=int, default=PIVOT_RIGHT,
                    help="candles after a pivot that it must beat, and therefore "
                         "the bars of confirmation lag")
    ap.add_argument("--fib-near", type=float, default=FIB_NEAR,
                    help="the near edge of the reversal zone (step 3)")
    ap.add_argument("--fib-far", type=float, default=FIB_FAR,
                    help="the far edge of the reversal zone (step 3)")
    ap.add_argument("--stop-offset", type=float, default=STOP_OFFSET,
                    help="points beyond the far edge for the stop (step 5)")
    ap.add_argument("--rr", dest="rr_values", type=float, nargs="+",
                    default=RR_VALUES, metavar="R",
                    help="the R:R ladder (step 6)")
    ap.add_argument("--target", dest="default_rr", type=float, default=DEFAULT_RR,
                    help="which rung the report opens on")
    ap.add_argument("--legs", choices=[k for k, _ in LEG_MODES], default=DEFAULT_LEGS,
                    help="all: every leg stays live until entered or the session "
                         "ends. latest: only the newest confirmed leg is live")
    ap.add_argument("--mode", choices=[k for k, _ in TRADE_MODES], default=DEFAULT_MODE,
                    help="trade-count policy selected when the report opens; "
                         "both are always computed")
    ap.add_argument("--entry-mode", choices=ENTRY_KEYS, default=DEFAULT_ENTRY,
                    help="entry reading selected when the report opens; both "
                         "are always computed. touch = resting limit on the "
                         "first touch; retest = touch, rejection close back "
                         "out, then buy the return")
    ap.add_argument("--entry-at", choices=[k for k, _ in ENTRY_EDGES], default=DEFAULT_EDGE,
                    help="which edge of the zone the resting order sits at")
    ap.add_argument("--virgin-only", action="store_true", default=False,
                    help="drop any leg whose zone was already reached during the "
                         "confirmation blind window")
    ap.add_argument("--entry-until", default=None,
                    help="no new entry at or after this time (default: the "
                         "square-off time)")
    ap.add_argument("--min-risk", type=float, default=MIN_RISK,
                    help="reject a signal whose SIGNED risk is under this many "
                         "NIFTY points (0 disables the floor)")
    ap.add_argument("--expiry-roll", choices=[k for k, _ in ROLL_MODES],
                    default=DEFAULT_ROLL,
                    help="which expiry to buy: none (nearest, 0-DTE included), "
                         "zero-dte (roll off it on expiry day), always (next out)")
    ap.add_argument("--view", choices=[k for k, _ in VIEWS], default=DEFAULT_VIEW,
                    help="view selected when the report opens")
    ap.add_argument("--eod", choices=[k for k, _ in EOD_MODES], default=DEFAULT_EOD,
                    help="square off at the close time, or hold to stop/target")
    ap.add_argument("--square-off", default=SQUARE_OFF)
    ap.add_argument("--session-start", default=SESSION_START)
    ap.add_argument("--offline", action="store_true", help="use local caches only")
    ap.add_argument("--out", default=REPORT_HTML)
    ap.add_argument("--from", dest="from_date", type=date.fromisoformat,
                    default=today - timedelta(days=183), help="default: 6 months back")
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat, default=today)
    args = ap.parse_args()

    if args.entry_until is None:
        args.entry_until = args.square_off
    args.modes = [k for k, _ in TRADE_MODES]
    if args.default_rr not in args.rr_values:
        args.default_rr = args.rr_values[0]
    os.makedirs(REPORTS_DIR, exist_ok=True)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
