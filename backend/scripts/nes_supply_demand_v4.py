"""NES supply/demand v4 - v3's zone-touch entry, a clean 100-point market
stop, and R-multiple targets off it.

The whole day is one state machine.  It is written out here in the order it
runs, because every decision below depends on the one above it.

  09:15   WAIT_FIRST_BOS
          The FIRST candle to CLOSE beyond a confirmed swing sets the day's
          direction.  Close above a confirmed swing high -> BULLISH; close
          below a confirmed swing low -> BEARISH.  A wick through is not a BOS.
          Only the first one counts; later BOS candles never replace the zone.

          The zone is the last opposite-colour candle before the displacement
          that caused the BOS - the last bearish candle for a bullish BOS, the
          last bullish candle for a bearish BOS - taken as its FULL range,
          low to high.  Bullish BOS -> DEMAND zone.  Bearish BOS -> SUPPLY.

  ->      WAIT_PRIMARY_RETEST
          Price has to come back and touch the zone (high >= zoneLow and
          low <= zoneHigh).  A touch is not an entry.

  ->      WAIT_*_CONFIRMATION            three steps, in this order
          1  SWEEP     a candle takes out the last confirmed minor swing
                       (low < previous swing low for a long)
          2  RECOVER   that SAME candle closes back the right side of it
                       (close > that swing low)
          3  MICRO-BOS a LATER candle closes beyond the latest confirmed minor
                       swing the other way (close > latest swing high)
          Entry is the CLOSE of the micro-BOS candle.
          Stop is min(zoneLow, sweepLow) - buffer for a long, and the mirror
          for a short.

  ->      TRADE_ACTIVE                   one position at a time

  Any time the zone gives way - a candle CLOSING below zoneLow for demand, or
  above zoneHigh for supply - the setup is dead and the DAY IS OVER.  ONE trade
  per day, at most.

  THE FLIP WAS REMOVED (2026-09-10, at the user's request), along with the
  reversal slot, the direction lock and the frozen unlock level.

Long and short are exact mirrors; nothing in the code branches on direction
except by sign.


WHY V3 THREW THE CONFIRMATION AWAY
----------------------------------
v1 and v2 both wait, after the zone is touched, for a three-part confirmation:
a sweep of the last minor swing, a recovery close on that same candle, then a
micro-BOS on a later one.  Measured against simply buying the touch, that
confirmation is not a filter - it is the thing that was breaking the strategy.

                        v2 (confirmed)   v3 (zone only)
    trades                     29              92
    win rate                 58.6%           66.3%
    net points                +882           +1332
    average R                 0.491           0.987
    median risk            41 points       15 points

The mechanism is the one this work has been circling since the first day.  The
stop is anchored to the zone, but the micro-BOS does not print until price has
already left it, so the entry drifts away from the stop while the stop stays
put.  Median risk goes from 15 points to 41 - the SAME trade, taken 2.7x
larger, with a 1:2 target 2.7x further away.  The confirmation does not buy
accuracy; it buys a worse price for the same idea.

Entering at the touch is shaken out more often - 55% of v3's stopped trades
later reach the target, against 8% of v2's - and that is fine.  A stop at the
zone edge is wrong cheaply: ~15 points, 31 times in 92 trades, against 61
winners at ~30 points.  Widening it to avoid the shakeouts was tested and is
strictly worse, because a 1:2 target is measured on the NEW risk, so a wider
stop pushes the target out in proportion and gains nothing:

    stop pad (zone widths)   0.0     0.25    0.5     1.0     2.0
    win rate               66.3%   60.9%   53.3%   47.8%   50.0%
    average R              0.987   0.821   0.591   0.438   0.517

And unlike everything else tried on this data, it does not decay out of sample
- the second half is BETTER than the first, on both timeframes:

    3-minute   H1  48 trades  60.4%  +729 pts  avgR 0.81
               H2  44 trades  72.7%  +603 pts  avgR 1.18
    1-minute   H1  48 trades  62.5%  +512 pts  avgR 0.88
               H2  50 trades  64.0%  +400 pts  avgR 0.92

WHAT V2 ADDED TO V1 (kept here only where it still applies)
----------------------------------------------------------
v1 takes every confirmation the rule produces: 78 trades, 42.3% win at 1:2 on
3-minute, and a win rate that falls from 47.4% in the first half of the sample
to 37.5% in the second.  v2 keeps the entry rule byte-identical and adds two
filters, both of which were measured on those 78 trades and then re-checked on
each half separately.  Four other candidates - how late the entry was, the
size of the risk, the width of the zone, the wait between touch and entry -
all reversed sign between the halves and were thrown away.

1. ENTRY CUT-OFF (--entry-until, default 13:00).
   A 1:2 target on a median 41-point risk needs an 82-point move.  Enter at
   10:30 and the session has 4h45m left to deliver it; enter at 14:00 and it
   has 75 minutes before the square-off.  Late trades do not lose so much as
   run out of clock - they get squared off mid-move.  The win rate falls
   monotonically as the cut-off is pushed later (50.0% before 12:00, 48.2%
   before 13:00, 44.4% before 14:00, 42.3% all day) and it falls in BOTH
   halves, which is what a mechanical effect looks like.

2. MINIMUM SWEEP DEPTH (--min-sweep-depth, default 0.1 zone widths).
   A sweep that pokes one tick past the swing is noise brushing a level, not a
   stop-hunt.  One that drives a tenth of a zone width through it actually
   triggered resting orders and then failed, which is the event the strategy
   exists to trade.  Depth >= 0.1 lifts the win rate 42.3% -> 47.2%, again in
   both halves.

Together: 38 trades, 52.6% win at 1:2, +762 points - MORE profit than v1's 78
trades made, because the 40 removed trades lost 86 points between them.  The
win rate is 52.9% in the first half and 52.4% in the second, the first time in
this work that a win rate has not decayed across the sample.

A REJECTED CONFIRMATION USES UP THE DAY.  When a confirmation completes but
fails a filter, the day is finished - the state machine does not go looking for
a later one.  That is deliberate: it reproduces exactly the 38 trades the
filters were validated on.  Letting it re-look would produce a larger, and
therefore unvalidated, set of trades.

THE SPEC LEAVES THINGS OPEN.  WHAT THIS SCRIPT CHOSE, AND WHY
-------------------------------------------------------------
Every one of these is a flag, so none of them is baked in.

1. TIMEFRAME.  "1-minute or 3-minute" - so both are run and the report has a
   timeframe switch.  It changes which swings exist, so it changes the trades
   themselves, not just the exits.  --tf picks the one the report opens on.

2. MINOR vs MAJOR SWINGS.  Section 3 defines exactly one detector
   (PIVOT_LENGTH = 2), sections 6/7 then say "minor" and section 11 says
   "major".  Read literally they are all the same set, and that is the default
   (--pivot 2 --minor-pivot 2 --major-pivot 2).  The two extra flags exist so
   the confirmation can run on a finer pivot, and the opposing-liquidity
   target aim at a coarser one, without touching anything else.

3. REPAINTING.  A pivot needs PIVOT_LENGTH candles AFTER it before it is
   confirmed, so at candle i the newest usable swing is the one at i-pivot.
   Every BOS, sweep and micro-BOS test in this file uses only swings whose
   right-hand side had already closed - `usable_swing()` enforces it.  Get
   this wrong and the backtest reads the future and the results are fiction.

4. THE ZONE CANDLE.  "the last bearish candle before the bullish displacement"
   - the search walks back from the BOS candle to the first opposite-colour
   candle, at most --zone-lookback bars.  If nothing opposite is found in that
   window the day is recorded as "no zone candle" and no trade is taken.
   v2 sets that window to 3 (v1 used 30) which turns it from a formality into
   a filter - see ZONE_LOOKBACK below.  58.6% win at 1:2 and +882 points from
   29 trades, against 52.6% and +762 from 38 at the wider setting, and it
   stays positive in both halves.

5. FAILURE BEATS TOUCH ON THE SAME CANDLE.  A candle can both dip into the
   zone and close beyond it.  Section 6 makes the zone valid while
   close >= zoneLow and section 8 fails it when close < zoneLow, so the close
   is what decides: such a candle is a FAILURE, not a touch.  It flips.

6. AFTER A TRADE CLOSES the state machine keeps running - the spec's
   TRADE_ACTIVE has no exit transition, but the zone can still fail after the
   primary is done, and that is exactly the demand-fails-then-reverses case.

7. STOP AND REVERSE.  If the reversal fires while the primary is somehow still
   open, the primary is closed at the reversal's entry price (exit reason
   REVERSED) and the short is opened there.  One position at a time, kept.
   Because the exit differs per variant, so does this: the same reversal can
   cut a primary short under one target and not under another.

7b. THERE IS NO SECOND FLIP.  The spec flips a zone once and says nothing
   about the flipped zone failing in turn.  If it does - a flipped supply that
   a candle then closes above - the day is simply over; the zone does not flip
   back.  Those sessions show up as "flipped zone failed" in the timeline.

8. stopBuffer has no value in the spec.  --buffer, default 0.

9. TARGET_MODE.  All three are computed and switchable in the report:
     rr        Entry +/- Risk x RR, over the whole --rr ladder.
     liq       opposing liquidity - the session extreme at entry, or the
               latest confirmed swing beyond it, whichever is further away.
               If there is no liquidity on the far side (entry is itself the
               session extreme) the trade has NO target and is managed by the
               stop and the square-off alone.  Those rows say "no target".
   Section 11's third mode - half off at 1R with the rest trailed - is
   deliberately NOT implemented.  It was built, and then taken out: trailing
   turns every trade into a stop-out, which buries the thing this backtest is
   trying to measure.

10. SESSION END.  Section 12's input is --eod: `close` squares off at
    --square-off (default 15:15), `hold` lets the position run to its stop or
    target and only gives up at the last candle of the day.


KNOWN PITFALLS IN THIS DATA - both of these were shipped wrong once before
--------------------------------------------------------------------------
1. DAILY VALUES MUST COME FROM THE DAILY CANDLES.  The 1-minute feed's last
   candle is 15:29 and misses the closing print; it differs from the official
   close on 94 of 124 sessions, by up to 85 NIFTY points.  This strategy is
   intraday and never uses a previous close, so nothing here depends on it -
   but the daily feed is still loaded and the report shows the official close
   next to the 15:29 print so the difference stays visible.

2. A CLOSE-CONFIRMED STOP DOES NOT CAP THE LOSS AT 1R.  Reporting
   "risk = |entry - SL|" and then filling at a candle close silently
   understates the loss.  Hence --stop-mode with both readings computed:
     touch  a resting order at the level, filled there (or at the open, if a
            minute opens already through it - which is the honest fill).
     close  the position is only closed once a candle CLOSES beyond the level
            and the fill is that close, wherever it landed.
   The day table shows fill, level and realised R side by side, and the
   `slip` column is how far past the level the fill actually happened.

Targets are a touch and are checked on 1-minute data, so a target reached
inside a candle is taken before that candle's close can trigger the stop.
When one minute both touches the target and breaks the stop, the stop is
taken first.

Run from backend/:
    python scripts/nes_supply_demand_v4.py --offline
    python scripts/nes_supply_demand_v4.py --tf 1 --target liq
    python scripts/nes_supply_demand_v4.py --eod hold --buffer 2

Output: ../reports/nes_supply_demand_v4_report.html (self-contained, no CDN).
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
from services.option_pricing import CachedPricer, ensure_cached  # noqa: E402

# backend/scripts holds only strategy code; the candle caches live in
# backend/data and the generated reports in backend/reports.
DATA_DIR = os.path.join(BACKEND_DIR, "data")
REPORTS_DIR = os.path.join(BACKEND_DIR, "reports")
CONFIG_FILE = os.path.join(BACKEND_DIR, "upstox_config.txt")
REPORT_HTML = os.path.join(REPORTS_DIR, "nes_supply_demand_v4_report.html")

UNDERLYING = "NIFTY"
UNDERLYING_KEY = INSTRUMENT_KEYS[UNDERLYING]

# NIFTY lot size verified against the Upstox contract master for this period.
LOT_SIZE = 65

TIMEFRAMES = [1, 3]            # section 1: "1-minute or 3-minute"
DEFAULT_TF = 3  # 1:2 holds up on 3-minute; on 1-minute it does not
# Section 1 says PIVOT_LENGTH = 2.  On a 1-minute chart that makes a "swing"
# any 5-minute wiggle - one qualified by 0.55 of a point in the sample - and it
# was the worst setting in every split-half on both timeframes.  3 is the
# smallest step that filters the chop while costing only ~13% of the trades.
PIVOT = 3
MINOR_PIVOT = 3                # the confirmation module's swings; see note 2
# NOT a safety cap any more - it is v2's third filter.  The search back from
# the BOS candle terminates at the first opposite-colour candle, and it never
# needed more than 6 bars in the whole sample, so anything >= 6 is inert (30,
# 60 and 200 give byte-identical results).  Below 6 it starts REJECTING days:
# at 3, the 32 sessions whose zone candle sits further back than 3 bars are
# dropped entirely.  Those are the slow, grinding displacements where the zone
# is already stale by the time price returns; what is left is the sharp
# one-candle reversal the setup is meant to be about.
ZONE_LOOKBACK = 3              # bars searched back for the zone candle
STOP_BUFFER = 0.0              # section 11 stopBuffer, never given a value
# Section 8 says a zone fails the moment one candle closes past its edge.  That
# is a one-candle kill racing a three-condition entry, and it wins 3 times in 4
# - which is why the literal rule only trades 26 of 124 sessions.  These two
# dials make the break prove itself; both default to the spec as written.
# One trade per session, as section 1 says.  The volume comes from converting
# MORE DAYS rather than stacking entries inside a day: at the settings below,
# 97 of 124 sessions produce a trade instead of 26.
# The two v2 filters.  Both were measured on v1's 78 trades and confirmed to
# point the same way in each half of the sample.  Set --entry-until 15:15 and
# --min-sweep-depth 0 to get v1's behaviour back out of this file.
ENTRY_UNTIL = "13:00"          # no new entry at or after this time
# The stop sits this many zone widths BEYOND the far edge.  0.0 - flush with
# the edge - was the best setting on every measure that matters; see the
# table in the docstring.  It is a flag only so the choice stays visible.
STOP_PAD = 0.0

# ---------------------------------------------------------------------------
# v4's two changes, and the measurements behind them
# ---------------------------------------------------------------------------
#
# THE STOP, THE RISK, AND THE TARGET
# ----------------------------------
#   stop    a MARKET order STOP_PTS below the entry for a long, above it for a
#           short.  The user exits it as a market order, so the fill is the
#           print at the minute the level trades, not the level - a loss is
#           not capped at the level, and the `slip` column says by how much.
#   risk    STOP_PTS, the same for every trade.
#   target  entry +/- risk x R over the ladder below, PLUS `liq`, the opposing
#           liquidity (the session extreme at entry or the latest confirmed
#           major swing beyond it, whichever is further).
#
# WHY 100.  Three stops were tried and measured on the real option first.
#   zone edge (v3)      killed 39 of 70 eventual 1-minute winners on a dip
#   confirmed swing     63% of trades stopped, 62% of those then hit target
#   fixed points        the only level outside the pullback winners make:
#                       on a no-stop book the winners' worst adverse move
#                       maxed at 98.3 pts and the losers' started at 59.6
# Then stop distance x R multiple, premium PnL, first / second half (1-min):
#
#   stop     1:0.5            1:1              1:2              1:3
#    60   -1,180*         2,860*           7,341*          13,861
#    80   19,412         8,258*          11,521          10,173*
#   100   18,521        17,800          18,093          12,672
#           (* = the two halves disagree in sign)
#
# That grid was run on the 82 trades the previous (swing-stop) rule let
# through.  A fixed stop is placeable on EVERY touch, including the 4 entries
# at or through the zone edge that the old risk guard rejected, so the report
# below runs on 86.  On that book, at the engine's session split (2026-06-11):
#
#   1:0.5  Rs 20,699  h1  7,690 / h2 13,009   holds
#   1:1    Rs 19,444  h1  9,018 / h2 10,426   holds       <- default tab
#   1:2    Rs 11,801  h1 -6,139 / h2 17,940   knife-edge: +4,124/+7,676 if the
#   1:3    Rs  6,380  h1 -9,002 / h2 15,382   split moves 5 sessions either way
#   liq    Rs 21,014  h1  4,267 / h2 16,747   holds
#
# So 100 is demonstrated at 1:0.5, 1:1 and liq.  1:2 and 1:3 are positive over
# the full sample and sit on a split-date knife-edge - shown, not claimed.
# Two of the four newly-placeable trades (2026-04-30, 2026-06-09) are the
# h1 losses that tip 1:2; they are legitimate under this rule and stay in.
#
# 3-MINUTE at 100 holds only at 1:0.5 (Rs 9,714, h2 barely +192); every R >= 1
# has a negative second half.  Nothing on 3-minute is demonstrated at these
# ratios - read its tabs as what they are.
STOP_PTS = 100.0

# THE TRAIL - how the big moves get captured without a fixed target
# ------------------------------------------------------------------
# Measured first (real option, split-half).  Favourable moves after entry on
# 1-minute run median 68 pts, p75 143, p90 233, max 520 - but only 13 of 86
# trades reach +200, so every FIXED target above 100 makes less than a target
# of 50 or 100 (the other ~70 trades give back their +68 waiting).  A trailing
# stop keeps the runners and cuts the give-back:
#
#   act \ trail        20        25        30        40        50
#        30        27,319    29,494    36,143    22,112    16,539*
#        40        40,043    42,549    43,544    29,145    18,054*
#        50        32,298    28,415    30,999    19,399    10,758*
#        60        20,858    12,864*   20,017*   11,901*    7,852*
#                                    (* = halves disagree)
#
# The whole block activate 30-50 x trail 20-40 is positive in BOTH halves -
# 12 of 12 cells - and the best cell (+40 / 30: 53W/28L, Rs 43,544) holds at
# every split date tried (h1 13.1k-19.6k / h2 24.0k-30.5k).  It degrades
# predictably as the trail loosens to 50 or activation rises to 60+.
# Baselines on the same book: fixed target 50 = Rs 20,699, fixed 100 =
# Rs 19,444, hold to 15:15 = Rs 10,585.
#
# 3-MINUTE: the activate-50 row holds, but its second halves are Rs 39-5,249.
# Not demonstrated to the same standard.
#
# Live, this is a resting SL order placed with the entry and MODIFIED (never
# cancelled) each completed 1-minute candle the best price improves.  Update
# on completed candles, not ticks - that is what was measured.
TRAIL_ACT = 40.0                 # trail switches on once this far in favour
TRAIL_DIST = 30.0                # ...and then sits this far behind the best price
# The rule has no fixed target.  The report shows the trail, and next to it
# the same trail capped at the OPPOSING LIQUIDITY (the session extreme at
# entry or the latest confirmed major swing beyond it) - the user wants that
# level visible.  --rr adds R-multiple caps as well; off by default.
RR_VALUES: list[float] = []

# RE-ENTRY.  In v3, 98% of stopped 1-minute trades (46 of 47) and 80% on
# 3-minute traded back through their entry before the square-off, and 39 and 34
# of them reached the original target afterwards.  Simply widening the stop
# does NOT capture that: the target is derived from the risk, so it moves out
# with the stop, and re-simulating the pad ladder shows no systematic gain.
# What the data supports is taking the 1R loss and going again once the zone
# proves itself: price trades BEYOND the stop edge and then a candle CLOSES
# back inside the zone.  Losses stay at 1R instead of being inflated.
# 0 disables it, which reproduces v3 exactly.
#
# TESTED AND REJECTED.  Both v4 ideas were run over 2026-03-09..2026-09-07 and
# neither beat the v3 baseline, so both default to OFF.  1-minute, premium PnL
# at touch/1:2:
#     reentries 0, basis risk   Rs 10,540   <- baseline, and the best
#     reentries 1, basis risk   Rs  7,917
#     reentries 0, basis zone   Rs  8,421
#     reentries 1, basis zone   Rs  6,419
# The re-entry lifts the trade count from 78 to 120 and dilutes: it converts
# some stop-outs, but the extra entries are worse than the ones it saves.  The
# zone basis fixes the arbitrary-target problem it was built for and still
# loses money, so that problem was not what was costing the strategy.
# On 3-minute every combination is negative, and the two that look least bad
# have halves that DISAGREE in sign - see the split-half block in the report.
# The flags stay so the test is reproducible, not because they are recommended.
MAX_REENTRIES = 0


STOP_ANCHORS = [("zone", "Far side of the zone, or the sweep - the spec"),
                ("sweep", "The sweep candle's extreme"),
                ("bos", "The micro-BOS candle's extreme"),
                ("tight", "The nearer of the sweep and the micro-BOS candle")]
DEFAULT_ANCHOR = "zone"

# A stop closer than this is not a trade, it is noise: NIFTY ticks in 0.05, and
# every sub-1-point stop in the sample was taken out for exactly -1.00R.  They
# also wreck avg R, since a 15-point move on a 0.2-point stop scores +75R.
# 1.0 is the smallest floor that removes only the physically unplaceable ones -
# raising it further keeps "improving" the numbers, which is curve-fitting, not
# a fix.  0 restores the old behaviour.
MIN_RISK = 1.0                 # NIFTY points

MAX_PER_DAY = 1
REENTRY_GAP = 5                # bars of separation between entries

# The zone only dies once a close is 4 zone widths past its edge.  As written
# (0.0) a single candle a tick through killed the setup, and since the kill
# needs one candle while the entry needs three across two, it won 3 times in 4
# and only 26 of 124 sessions ever traded.  At 4.0 the count is 78 and, unlike
# every wider or narrower setting tried, the win rate holds across both halves
# of the sample rather than collapsing.  --fail-buffer 0 restores the spec.
FAIL_BUFFER = 4.0              # in zone widths; 0.0 is the literal spec
FAIL_CLOSES = 1                # consecutive closes beyond the edge

TARGET_MODES = [("trail", "No fixed target - the trailing stop is the exit"),
                ("rr", "Fixed R:R off the 100-point stop, with the trail still active"),
                ("liq", "Opposing liquidity")]
DEFAULT_TARGET = "trail"

# THE STOP HUNT, AND WHAT ACTUALLY STOPS IT
# -----------------------------------------
# The stop at the zone edge is a good classifier - across v3's book NOT ONE
# winning trade ever traded through it (0 of 31 on 1-minute, 0 of 17 on
# 3-minute).  The problem is what happens to the losers: they break the edge,
# and then 98% of them (1-minute) trade back through the entry before the
# square-off, 39 of 47 going on to reach the original target.
#
# Widening the stop does NOT capture that.  Measured on the real option, the
# premium capture collapses as the stop widens - 0.47 of the spot move at
# pad 0, 0.30 at pad 1.0, 0.17 at pad 1.5 - because the position sits open
# through the adverse excursion and theta eats it.  Every pad from 0.5 to 3.0
# raises the win rate (48.7% -> 64.2%) and loses money.
#
# What works is removing the spot stop altogether.  This strategy is always
# LONG PREMIUM, so the position already has defined risk: the premium paid.
# The spot stop is a second, self-imposed exit, and it is the one being hunted
# - with it, the MEDIAN 1-minute trade is closed 2 minutes after entry.
#
#   1-minute, target 1:2, priced on the real ATM contract
#     spot stop at the zone edge   40W/38L  51.3%  Rs 10,540   median hold  2 min
#     NO SPOT STOP                 60W/18L  76.9%  Rs 20,790   median hold  8 min
#         and both halves agree:   h1 Rs 16,946   h2 Rs 3,845
#
# The risk is real but bounded, because the position is squared off the same
# session: worst single loss 49% of that trade's premium (Rs 3,666), median
# loss Rs 426, and NO 1-minute trade lost more than 90% of its premium.
#
# On 3-MINUTE the same change shows Rs 19,538 - but h1 Rs 19,945 against
# h2 Rs -407.  That is one good half, not a demonstrated edge.  Do not read
# the 3-minute no-stop number as a result.
# `touch` (SL order at the level) and `close` (candle closes beyond it) were
# both removed on 2026-09-10: they are the stop that was being hunted, and the
# comparison above is kept in this comment rather than as live tabs nobody
# should trade.  The zone edge still sets `risk`, and therefore the target -
# it is just no longer an exit.
# One stop rule: a MARKET order STOP_PTS from the entry.
STOP_MODES = [("pts", "Market stop 100 pts from entry; once +40 in favour it "
                     "trails 30 behind the best price")]
DEFAULT_STOP = "pts"

EOD_MODES = [("close", "square off at the session close time"),
             ("hold", "run to stop or target, give up at the last candle")]
DEFAULT_EOD = "close"

# Which of the day's two slots is actually traded.  The primary is the better
# half of the rule - it is positive in both halves of the sample where the
# combined book is not - so it is the default.  The reversal machinery still
# runs regardless: the zone has to be able to fail and flip for the report to
# show what happened.
# The flip-and-reverse half of the rule was removed on 2026-09-10, so a day has
# exactly one slot: the primary, in the first BOS direction.
TAKE_LABEL = "Primary only - the first BOS direction"

VIEWS = [("both", "Long and short together"),
         ("long", "Long trades only"),
         ("short", "Short trades only")]
DEFAULT_VIEW = "both"

SESSION_START = "09:15"        # nothing is looked at before this
SQUARE_OFF = "15:15"           # --eod close exits here
OPEN_TIME = "09:15"
DAY_END = "15:29"


def rr_label(r: float) -> str:
    return f"1:{r:g}"


def target_keys(rr_values: list[float], with_liq: bool = False) -> list[str]:
    """The rule first; capped comparisons only when asked for."""
    return (["trail"] + [f"rr:{rr_label(r)}" for r in rr_values]
            + (["liq"] if with_liq else []))


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
    """{'YYYY-MM-DD': official session close} from the daily candle feed.

    This strategy is purely intraday and never uses a previous close, so no
    signal depends on this.  It is loaded anyway because the 1-minute feed's
    15:29 print is NOT the official close - it differs on 94 of 124 sessions,
    by up to ~85 NIFTY points - and the report shows both so that gap stays
    visible rather than being quietly assumed away.  Missing daily data is a
    warning here, not a failure.
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
        for name in sorted(os.listdir(DATA_DIR)):
            if name.startswith("nifty_1d_") and name.endswith(".json"):
                with open(os.path.join(DATA_DIR, name)) as f:
                    raw = json.load(f)
                print(f"Reusing {name} for the official daily closes.")
                break
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
# Candle building
# ---------------------------------------------------------------------------

def bucket_start(hhmm: str, minutes: int) -> str:
    """09:15-anchored bucket label: for 3m, 09:15, 09:18, 09:21, ..."""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    offset = (h * 60 + m) - (9 * 60 + 15)
    if offset < 0:
        return OPEN_TIME
    start = 9 * 60 + 15 + (offset // minutes) * minutes
    return f"{start // 60:02d}:{start % 60:02d}"


def build_buckets(minutes: list[dict], size: int) -> list[dict]:
    """Aggregate 1-minute candles into `size`-minute candles, in time order.

    size == 1 is the identity aggregation, so the 1-minute timeframe runs
    through exactly the same code path as the 3-minute one.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in minutes:
        hhmm = c["timestamp"][11:16]
        if hhmm < OPEN_TIME or hhmm > DAY_END:
            continue
        groups[bucket_start(hhmm, size)].append(c)
    out = []
    for start in sorted(groups):
        g = groups[start]
        out.append({
            "start": start,
            "open": float(g[0]["open"]),
            "high": max(float(c["high"]) for c in g),
            "low": min(float(c["low"]) for c in g),
            "close": float(g[-1]["close"]),
            "minutes": g,
        })
    return out


# ---------------------------------------------------------------------------
# Swings - section 3
# ---------------------------------------------------------------------------

def confirmed_swings(bars: list[dict], pivot: int) -> tuple[list[dict], list[dict]]:
    """Confirmed swing highs and lows.

    A swing high at i is strictly higher than the `pivot` highs before it and
    the `pivot` highs after it.  It is only CONFIRMED once bar i+pivot has
    closed, and `confirm` carries that index: nothing in this file may look at
    a swing before its confirm bar, or the backtest is reading the future.
    Precomputing the pivots for the whole day and then using the "latest" one
    without that gate is the single biggest look-ahead trap in this strategy.
    """
    highs: list[dict] = []
    lows: list[dict] = []
    n = len(bars)
    for i in range(pivot, n - pivot):
        h = bars[i]["high"]
        if (all(bars[j]["high"] < h for j in range(i - pivot, i)) and
                all(bars[j]["high"] < h for j in range(i + 1, i + pivot + 1))):
            highs.append({"i": i, "price": h, "confirm": i + pivot,
                          "time": bars[i]["start"]})
        lo = bars[i]["low"]
        if (all(bars[j]["low"] > lo for j in range(i - pivot, i)) and
                all(bars[j]["low"] > lo for j in range(i + 1, i + pivot + 1))):
            lows.append({"i": i, "price": lo, "confirm": i + pivot,
                         "time": bars[i]["start"]})
    return highs, lows


def usable_swing(swings: list[dict], at: int) -> dict | None:
    """The latest swing whose right-hand side had closed by bar `at`."""
    out = None
    for s in swings:
        if s["confirm"] <= at:
            out = s
        else:
            break
    return out


# ---------------------------------------------------------------------------
# The state machine - sections 4 to 10 and 13
# ---------------------------------------------------------------------------

def touches(bar: dict, lo: float, hi: float) -> bool:
    """Section 5 - the candle's range overlaps the zone."""
    return bar["low"] <= hi and bar["high"] >= lo


def find_zone_candle(bars: list[dict], bos_i: int, bullish: bool,
                     lookback: int) -> int | None:
    """Section 4 - the last opposite-colour candle before the displacement.

    Walks back from the candle before the BOS candle.  A bullish BOS wants the
    last BEARISH candle (close < open); a bearish BOS the last BULLISH one.
    The spec puts no bound on that search and gives no miss case, so the walk
    is capped at `lookback` bars and a miss kills the day.
    """
    stop = max(0, bos_i - lookback)
    for j in range(bos_i - 1, stop - 1, -1):
        b = bars[j]
        if bullish and b["close"] < b["open"]:
            return j
        if not bullish and b["close"] > b["open"]:
            return j
    return None


def run_state_machine(bars: list[dict], *, pivot: int, minor_pivot: int,
                      major_pivot: int, zone_lookback: int, buffer: float,
                      session_start: str, signal_until: str,
                      allow_same_bar_bos: bool,
                      fail_buffer: float = 0.0, fail_closes: int = 1,
                      max_per_day: int = 1, reentry_gap: int = 5,
                      max_reentries: int = 0, stop_pts: float = 100.0,
                      stop_anchor: str = "zone",
                      entry_until: str = "15:15", stop_pad: float = 0.0,
                      take_primary: bool = True) -> dict:
    """One session, one pass, left to right.  Returns the day's structure and
    up to two signals (one primary, one reversal).

    Nothing here knows about targets, stops-in-flight or PnL - this is purely
    the rule that decides WHEN and WHERE a position is opened.  Everything the
    exit engine needs afterwards is handed over inside the signal dict.

    take_primary suppresses the ENTRY without disabling any
    of the structure behind it: the zone still fails, still flips, still gets
    retested, and the timeline still records all of it.  That matters because
    the flip is what draws the zone in the report, and because a suppressed
    reversal must not silently change the primary - see the REVERSED exit in
    price_trades(), which only exists when both slots are live.
    """
    sw_hi, sw_lo = confirmed_swings(bars, pivot)
    if minor_pivot == pivot:
        mn_hi, mn_lo = sw_hi, sw_lo
    else:
        mn_hi, mn_lo = confirmed_swings(bars, minor_pivot)
    if major_pivot == pivot:
        mj_hi, mj_lo = sw_hi, sw_lo
    else:
        mj_hi, mj_lo = confirmed_swings(bars, major_pivot)

    out: dict = {"status": "no BOS", "bos": None, "zone": None, "dead": None,
                 "events": [], "signals": [], "swings": None,
                 "original_dir": None}
    ev = out["events"]

    state = "WAIT_FIRST_BOS"
    zone_lo = zone_hi = None
    zone_type = None            # DEMAND | SUPPLY
    primary_taken = False
    reentries_left = max_reentries
    breached = False
    primary_count = 0
    last_entry_i = None
    touch_i = None
    sweep = None                # {"i", "level", "px", "time"}
    sess_hi = sess_lo = None    # running extremes, EXCLUDING the current bar

    def add(t: str, kind: str, text: str, price=None) -> None:
        ev.append({"t": t, "kind": kind, "text": text,
                   "price": None if price is None else round(price, 2)})

    fail_streak = 0

    def zone_failed(b: dict) -> bool:
        """Section 8's failure test, with two dials the spec does not have.

        As written, ONE candle closing a single tick past an 11-point zone
        kills the setup.  That is the same noise problem as a pivot of 2, one
        level down: the kill needs one candle, the entry needs three across at
        least two candles, so the kill wins about three times out of four.

        fail_buffer widens the edge by a fraction of the zone's own width, so
        the break has to mean something on the zone's own scale.  fail_closes
        demands that many CONSECUTIVE closes beyond it.  Both default to the
        literal spec (0.0 and 1).
        """
        nonlocal fail_streak
        width = zone_hi - zone_lo
        pad = fail_buffer * width
        if zone_type == "DEMAND":
            beyond = b["close"] < zone_lo - pad
        else:
            beyond = b["close"] > zone_hi + pad
        fail_streak = fail_streak + 1 if beyond else 0
        return fail_streak >= fail_closes

    def zone_dies(i: int, b: dict) -> None:
        """The zone gives way, so the setup is dead and the day is over.

        The spec joined two ideas in one sentence - "the setup is dead AND the
        zone flips in place".  The flip half is deliberately gone: no reversal
        slot, no direction lock, no frozen unlock level, no second zone.
        """
        nonlocal state
        was_demand = zone_type == "DEMAND"
        state = "DONE"
        if out["status"] in ("no touch", "no confirmation"):
            out["status"] = "zone failed"
        out["dead"] = {"time": b["start"], "close": round(b["close"], 2),
                       "zone": zone_type}
        add(b["start"], "DEAD",
            f"{'Demand' if was_demand else 'Supply'} failed - close "
            f"{b['close']:.2f} {'below' if was_demand else 'above'} the zone. "
            f"The setup is dead; there is no reversal.", b["close"])

    def liq_target(side: str, i: int, b: dict) -> float | None:
        """Section 11 OPPOSING_LIQUIDITY - the session extreme at entry, or the
        latest confirmed MAJOR swing beyond it, whichever is further away.

        Returns None when there is no liquidity left on the far side, i.e. the
        entry is itself the session extreme.  Those trades are managed by the
        stop and the square-off alone; they are not silently given an RR
        target instead.

        The session extreme used here is the one standing BEFORE the entry
        candle.  Including the entry candle's own high would hand a breakout
        entry a "target" a fraction of a point above its own close, which
        prints a flattering win rate for trades that never went anywhere.
        """
        entry = b["close"]
        if side == "LONG":
            cands = [] if sess_hi is None else [sess_hi]
            s = usable_swing(mj_hi, i)
            if s is not None:
                cands.append(s["price"])
            cands = [c for c in cands if c > entry]
            return max(cands) if cands else None
        cands = [] if sess_lo is None else [sess_lo]
        s = usable_swing(mj_lo, i)
        if s is not None:
            cands.append(s["price"])
        cands = [c for c in cands if c < entry]
        return min(cands) if cands else None

    def make_signal(i: int, b: dict, kind: str, side: str) -> dict:
        """Entry is the close of the candle that TOUCHED the zone.  The stop
        is STOP_PTS from that entry (a market order), so risk is the same
        number for every trade and the R ladder means the same thing on
        every row."""
        entry = b["close"]
        width = zone_hi - zone_lo
        long = side == "LONG"
        sl = entry - stop_pts if long else entry + stop_pts
        stop_src, stop_time = "fixed", None
        lt = liq_target(side, i, b)
        return {
            "kind": kind, "side": side, "i": i,
            "entry_time": b["start"], "entry": round(entry, 2),
            "sl": round(sl, 2), "zone_width": round(width, 2),
            # SIGNED, deliberately.  abs() here reported the DISTANCE to the
            # stop and threw away which side of it the entry landed on, which
            # made the `risk <= 0` guard in price_trades() unreachable: it
            # could only ever catch entry == sl, never a long entered BELOW
            # its own stop.  Those trades are impossible to place and were
            # being scored anyway - some of them as wins.  Keeping the sign
            # lets that guard reject them.  (A wide --fail-buffer is what
            # lets the confirmation fire that far past the zone; see below.)
            "risk": round((entry - sl) if side == "LONG" else (sl - entry), 2),
            "zone_low": round(zone_lo, 2), "zone_high": round(zone_hi, 2),
            "zone_type": zone_type,
            "touch_time": b["start"],
            "zone_width": round(width, 2),
            "stop_src": stop_src, "stop_time": stop_time,
            "liq": None if lt is None else round(lt, 2),
        }

    def filter_reason(b: dict, sig: dict) -> str | None:
        """v3 keeps only the time cut-off.  The sweep-depth filter went with the
        confirmation module it belonged to.  Evaluated on the entry candle's
        close, so it cannot look forward."""
        if b["start"] >= entry_until:
            return (f"touch at {b['start']} is at or after the {entry_until} "
                    f"cut-off - not enough session left for a 2R move")
        return None

    def try_confirmation(i: int, b: dict, side: str, kind: str) -> dict | None:
        """The three-step module of sections 6 and 7, run in `side`'s direction.

        Steps 1 and 2 are the SAME candle: it takes out the last confirmed
        minor swing and closes back the right side of it.  Step 3 is a LATER
        candle closing beyond the latest confirmed minor swing the other way.
        A candle that does both at once only re-arms the sweep unless
        --allow-same-bar-bos is on.
        """
        nonlocal sweep
        long = side == "LONG"
        ref = usable_swing(mn_lo if long else mn_hi, i)
        new_sweep = None
        if ref is not None:
            swept = b["low"] < ref["price"] if long else b["high"] > ref["price"]
            recovered = b["close"] > ref["price"] if long else b["close"] < ref["price"]
            if swept and recovered:
                new_sweep = {"i": i, "level": ref["price"],
                             "px": b["low"] if long else b["high"],
                             "time": b["start"]}

        if last_entry_i is not None and i - last_entry_i < reentry_gap:
            return None
        armed = sweep if (sweep is not None and i > sweep["i"]) else None
        if armed is None and allow_same_bar_bos and new_sweep is not None:
            armed = new_sweep

        if armed is not None:
            bos_ref = usable_swing(mn_hi if long else mn_lo, i)
            if bos_ref is not None:
                broke = (b["close"] > bos_ref["price"] if long
                         else b["close"] < bos_ref["price"])
                if broke:
                    sweep = armed
                    add(b["start"], "MICRO-BOS",
                        f"Close {b['close']:.2f} {'above' if long else 'below'} "
                        f"the latest minor swing {'high' if long else 'low'} "
                        f"{bos_ref['price']:.2f} - {kind} {side} entry",
                        b["close"])
                    sig = make_signal(i, b, kind, side)
                    sig["bos_level"] = round(bos_ref["price"], 2)
                    return sig

        if new_sweep is not None:
            sweep = new_sweep
            add(b["start"], "SWEEP",
                f"Swept the minor swing {'low' if long else 'high'} "
                f"{ref['price']:.2f} to {new_sweep['px']:.2f} and closed back "
                f"{'above' if long else 'below'} it at {b['close']:.2f}",
                new_sweep["px"])
        return None

    # -----------------------------------------------------------------------
    for i, b in enumerate(bars):
        t = b["start"]
        if t < session_start:
            sess_hi = b["high"] if sess_hi is None else max(sess_hi, b["high"])
            sess_lo = b["low"] if sess_lo is None else min(sess_lo, b["low"])
            continue
        if t >= signal_until or state == "DONE":
            break

        if state == "WAIT_FIRST_BOS":
            sh = usable_swing(sw_hi, i)
            sl_ = usable_swing(sw_lo, i)
            bullish = sh is not None and b["close"] > sh["price"]
            bearish = sl_ is not None and b["close"] < sl_["price"]
            if bullish or bearish:
                # a close cannot be above a swing high and below a swing low at
                # the same time unless the data is broken; bullish wins.
                zc = find_zone_candle(bars, i, bullish, zone_lookback)
                lvl = sh["price"] if bullish else sl_["price"]
                add(t, "BOS",
                    f"First {'bullish' if bullish else 'bearish'} BOS - close "
                    f"{b['close']:.2f} {'above' if bullish else 'below'} the "
                    f"confirmed swing {'high' if bullish else 'low'} {lvl:.2f}",
                    b["close"])
                out["bos"] = {"time": t, "dir": "BULLISH" if bullish else "BEARISH",
                              "level": round(lvl, 2),
                              "swing_time": (sh if bullish else sl_)["time"]}
                out["original_dir"] = "BULLISH" if bullish else "BEARISH"
                if zc is None:
                    out["status"] = "no zone candle"
                    add(t, "DEAD", f"No {'bearish' if bullish else 'bullish'} "
                        f"candle within {zone_lookback} bars before the "
                        f"displacement - no zone, no trade")
                    state = "DONE"
                else:
                    zone_lo, zone_hi = bars[zc]["low"], bars[zc]["high"]
                    zone_type = "DEMAND" if bullish else "SUPPLY"
                    out["zone"] = {"low": round(zone_lo, 2), "high": round(zone_hi, 2),
                                   "time": bars[zc]["start"], "type": zone_type}
                    out["status"] = "no touch"
                    add(bars[zc]["start"], "ZONE",
                        f"{zone_type.title()} zone from the last "
                        f"{'bearish' if bullish else 'bullish'} candle before "
                        f"the displacement: {zone_lo:.2f} - {zone_hi:.2f}")
                    state = "WAIT_PRIMARY_RETEST"

        elif state == "WAIT_PRIMARY_RETEST":
            # the close decides: a candle that dips in AND closes beyond the far
            # boundary is a failure, not a touch
            if zone_failed(b):
                zone_dies(i, b)
            elif not primary_taken and touches(b, zone_lo, zone_hi):
                touch_i = i
                side = "LONG" if zone_type == "DEMAND" else "SHORT"
                sig = make_signal(i, b, "primary", side)
                add(t, "TOUCH", f"Price touched the {zone_type.lower()} zone "
                    f"({zone_lo:.2f} - {zone_hi:.2f})")
                if (why := filter_reason(b, sig)) is not None:
                    add(t, "FILTERED", f"{side} touch - {why}")
                    out["status"] = "filtered out"
                    primary_taken = True
                    state = "WAIT_ZONE_FAIL"
                else:
                    out["signals"].append(sig)
                    out["status"] = "trade"
                    add(t, "ENTRY", f"{side} at the touch, {sig['entry']:.2f}; "
                        f"stop {sig['sl']:.2f}, risk {sig['risk']:.2f}")
                    primary_count += 1
                    last_entry_i = i
                    primary_taken = primary_count >= max_per_day
                    if primary_taken and reentries_left > 0:
                        breached = False
                        state = "WAIT_REENTRY"
                    else:
                        state = ("WAIT_ZONE_FAIL" if primary_taken
                                 else "WAIT_PRIMARY_RETEST")

        elif state == "WAIT_ZONE_FAIL":
            # the primary is done; the zone giving way now simply ends the day
            if zone_failed(b):
                zone_dies(i, b)

        elif state == "WAIT_REENTRY":
            # A position is open as far as this state machine knows - whether it
            # was stopped is decided per exit variant, downstream.  So the
            # re-entry is defined on PRICE alone: the zone edge has to be broken
            # and then reclaimed.  price_trades() enforces one position at a
            # time per variant, so a re-entry is automatically skipped for any
            # variant whose first trade is still running, and taken for the ones
            # where it was stopped.  Nothing here needs to know which.
            if zone_failed(b):
                zone_dies(i, b)
            else:
                edge = zone_lo if zone_type == "DEMAND" else zone_hi
                broke = (b["low"] < edge) if zone_type == "DEMAND" else (b["high"] > edge)
                if broke and not breached:
                    breached = True
                    add(t, "BREAK", f"Price broke the {zone_type.lower()} zone edge "
                        f"{edge:.2f} - watching for a close back inside", edge)
                reclaimed = (zone_lo <= b["close"] <= zone_hi)
                if breached and reclaimed and i - last_entry_i >= reentry_gap:
                    side = "LONG" if zone_type == "DEMAND" else "SHORT"
                    sig = make_signal(i, b, "reentry", side)
                    if (why := filter_reason(b, sig)) is not None:
                        add(t, "FILTERED", f"Re-entry {side} - {why}")
                    else:
                        out["signals"].append(sig)
                        out["status"] = "trade"
                        add(t, "REENTRY", f"{side} re-entry at {sig['entry']:.2f} - "
                            f"the zone was broken and closed back inside; "
                            f"stop {sig['sl']:.2f}, risk {sig['risk']:.2f}")
                        reentries_left -= 1
                        last_entry_i = i
                        breached = False
                    if reentries_left <= 0:
                        state = "WAIT_ZONE_FAIL"

        if state == "WAIT_CONF":
            if zone_failed(b):
                add(t, "CANCEL", "Zone failed while waiting for the "
                    "confirmation - the pending setup is cancelled")
                zone_dies(i, b)
            else:
                side = "LONG" if zone_type == "DEMAND" else "SHORT"
                sig = try_confirmation(i, b, side, "primary")
                if sig is not None:
                    if not take_primary:
                        add(t, "SKIPPED", f"{side} primary confirmation "
                            "completed - not taken, primary is switched off")
                        primary_taken = True
                        state = "WAIT_ZONE_FAIL"
                    elif primary_taken:
                        add(t, "BLOCKED", f"{side} confirmation completed but "
                            "the primary trade is already used")
                    elif (why := filter_reason(b, sig)) is not None:
                        # a rejected confirmation uses up the day; see the
                        # docstring for why it does not go looking for another
                        add(t, "FILTERED", f"{side} confirmation completed - {why}")
                        out["status"] = "filtered out"
                        primary_taken = True
                        state = "WAIT_ZONE_FAIL"
                    else:
                        out["signals"].append(sig)
                        out["status"] = "trade"
                        primary_count += 1
                        last_entry_i = i
                        primary_taken = primary_count >= max_per_day
                        # re-arm on the same zone: while it holds, each fresh
                        # sweep + micro-BOS is another entry.  The spec caps the
                        # day at one, which traded 26 of 124 sessions.
                        sweep = None
                        state = "WAIT_ZONE_FAIL" if primary_taken else "WAIT_CONF"

        sess_hi = b["high"] if sess_hi is None else max(sess_hi, b["high"])
        sess_lo = b["low"] if sess_lo is None else min(sess_lo, b["low"])

    out["swings"] = {
        "highs": [{"t": s["time"], "p": round(s["price"], 2)} for s in sw_hi],
        "lows": [{"t": s["time"], "p": round(s["price"], 2)} for s in sw_lo],
    }
    return out


# ---------------------------------------------------------------------------
# Exits - section 11 and 12
# ---------------------------------------------------------------------------
#
# The signal layer above decided WHERE a position opens.  Everything below
# decides where it closes, and it is deliberately the only place in the file
# that touches 1-minute data: the structure is read on the strategy timeframe,
# but a stop or a target is a price that can be traded at any moment inside a
# candle, so pretending it can only happen at a 3-minute close would flatter
# the results.
#
# Fill assumptions, stated once and used everywhere:
#   stop, touch mode   a resting order at the level.  Filled AT the level,
#                      unless the minute already opened through it, in which
#                      case the open is the honest fill and the loss is worse
#                      than 1R.
#   stop, close mode   only a candle CLOSE beyond the level closes the trade,
#                      and the fill is that close, wherever it landed.  This
#                      does NOT cap the loss at 1R.
#   target             a resting limit at the level, same treatment: filled at
#                      the level, or at the open if the minute gapped past it.
#   square-off         the OPEN of the first minute at or after the cut-off.
#   reversed           the reversal's own entry price, at the close of the
#                      candle that triggered it.
# Within one minute the STOP is always checked before the target, so a minute
# that spans both is scored as a loss.

def walk(bars: list[dict], i_entry: int, side: str, sl: float,
         target: float | None, *, stop_mode: str, eod: str, square_off: str,
         entry: float | None = None, trail_act: float = 0.0,
         trail_dist: float = 0.0,
         reverse_bar: int | None = None, reverse_px: float | None = None) -> dict:
    """Forward walk from the candle AFTER the entry candle - entry is that
    candle's close, so nothing can happen to the position inside it.

    The trail is a ratchet on `sl`: once price has been `trail_act` in favour,
    each minute the best price improves the stop is moved to best -/+
    `trail_dist`, and it never moves back.  The order inside a minute matters
    and matches the measurement that justified it: square-off, then the stop
    at its CURRENT level, then the target, then the best price is updated and
    the stop ratcheted for the NEXT minute.
    """
    long = side == "LONG"
    last = bars[-1]
    best = entry if entry is not None else None
    armed_at = None
    for bi in range(i_entry + 1, len(bars)):
        b = bars[bi]
        for m in b["minutes"]:
            hhmm = m["timestamp"][11:16]
            mo, mh, ml = float(m["open"]), float(m["high"]), float(m["low"])
            if eod == "close" and hhmm >= square_off:
                return {"exit": mo, "exit_time": hhmm, "exit_i": bi,
                        "reason": "SQUARE OFF", "final_stop": sl,
                        "trail_on": armed_at}
            # A MARKET stop: once the level trades, the position is out at
            # this minute's print, not at the level - the honest reading of a
            # market order.  The option leg is priced at this same minute.
            if stop_mode == "pts" and (ml <= sl if long else mh >= sl):
                return {"exit": (ml if long else mh), "exit_time": hhmm,
                        "exit_i": bi,
                        "reason": "TRAIL STOP" if armed_at else "STOP",
                        "final_stop": sl, "trail_on": armed_at}
            if target is not None and (mh >= target if long else ml <= target):
                fill = max(target, mo) if long else min(target, mo)
                return {"exit": fill, "exit_time": hhmm, "exit_i": bi,
                        "reason": "TARGET", "final_stop": sl,
                        "trail_on": armed_at}
            if best is not None and trail_act > 0:
                best = max(best, mh) if long else min(best, ml)
                if (best - entry if long else entry - best) >= trail_act:
                    if armed_at is None:
                        armed_at = hhmm
                    sl = (max(sl, best - trail_dist) if long
                          else min(sl, best + trail_dist))
        if reverse_bar is not None and bi >= reverse_bar:
            return {"exit": reverse_px, "exit_time": b["start"], "exit_i": bi,
                    "reason": "REVERSED", "final_stop": sl, "trail_on": armed_at}
    return {"exit": last["close"], "exit_time": last["minutes"][-1]["timestamp"][11:16],
            "exit_i": len(bars) - 1, "reason": "EOD", "final_stop": sl,
            "trail_on": armed_at}


PRICER = CachedPricer()


def _option_leg(pricer, info, t, res) -> dict:
    """The premium fields for one exit variant.

    Returns pnl_rs=None and opt_reason set when the contract or its candles
    could not be had.  Such a trade STAYS in the book and stays visible - it is
    simply left out of the money totals.  Dropping it would quietly shrink the
    sample, which is the failure mode this whole exercise exists to remove.
    """
    if pricer is None or info is None:
        return {"pnl_rs": None, "win": None, "opt_reason": "not priced"}
    if info["reason"]:
        return {"strike": info["strike"], "opt_type": info["option_type"],
                "opt_symbol": info["symbol"], "entry_px": None, "exit_px": None,
                "prem_pts": None, "pnl_rs": None, "win": None,
                "opt_reason": info["reason"]}
    o = CachedPricer.price_from(info, t["entry_time"], res["exit_time"])
    prem = o["prem_pts"]
    return {"strike": o["strike"], "opt_type": o["option_type"],
            "opt_symbol": o["symbol"], "entry_px": o["entry_px"],
            "exit_px": o["exit_px"], "prem_pts": prem,
            "pnl_rs": None if prem is None else round(prem * LOT_SIZE, 2),
            "win": None if prem is None else prem > 0,
            "opt_reason": o["reason"]}


def price_trades(bars: list[dict], signals: list[dict], *, rr_values: list[float],
                 stop_modes: list[str], eod: str, square_off: str,
                 min_risk: float = 0.0, pricer=None, day: str = "",
                 trail_act: float = 0.0, trail_dist: float = 0.0,
                 with_liq: bool = False) -> list[dict]:
    """Turn each signal into a trade carrying every exit variant.

    ONE POSITION AT A TIME, and it has to be enforced per variant, because the
    exit differs per variant: the same second signal can be legal under a 1:1
    target (the first trade was already closed) and illegal under 1:5 (it was
    still running).  So the walk is driven per stop-rule / target pair, in
    signal order, carrying the bar the previous trade actually closed on:

      - a later signal in the SAME direction while one is open is SKIPPED for
        that variant; it would be pyramiding, which this strategy never does.
      - a later signal in the OPPOSITE direction closes the open one at the new
        entry price (reason REVERSED) and takes the new side.

    A skipped signal carries `skipped: True` for that variant and is dropped by
    summarise(), so trade counts legitimately differ between columns.
    """
    tkeys = target_keys(rr_values, with_liq)
    trades: list[dict] = []
    for sig in signals:
        t = dict(sig)
        t["ex"] = {}
        if sig["risk"] <= 0:
            t["dead"] = "entry at or through the stop"
        elif sig["risk"] < min_risk:
            t["dead"] = f"risk {sig['risk']} below the {min_risk:g}-point floor"
        trades.append(t)

    day_info = {}
    if pricer is not None:
        for t in trades:
            day_info[id(t)] = pricer.day_prices(day, t["side"], t["entry"])

    live = [t for t in trades if "dead" not in t]
    for mode in stop_modes:
        for tk in tkeys:
            open_until = -1          # bar the running trade closes on
            open_side = None
            for t in live:
                entry, risk = t["entry"], t["risk"]
                long = t["side"] == "LONG"
                # The stop is the fixed level set at signal time.
                sl = t["sl"]
                t["stop_level"] = round(sl, 2)
                opt_info = day_info.get(id(t))
                t["ex"].setdefault(mode, {})
                if t["i"] <= open_until and t["side"] == open_side:
                    t["ex"][mode][tk] = {"skipped": True,
                                         "why": "a position was already open"}
                    continue
                if tk == "trail":
                    tgt = None          # the trailing stop is the only exit
                elif tk == "liq":
                    tgt = t["liq"]
                else:
                    r = float(tk[3:].split(":")[1])
                    tgt = entry + risk * r if long else entry - risk * r
                res = walk(bars, t["i"], t["side"], sl, tgt, stop_mode=mode,
                           eod=eod, square_off=square_off, entry=entry,
                           trail_act=trail_act, trail_dist=trail_dist)
                pts = (res["exit"] - entry) if long else (entry - res["exit"])
                t["ex"][mode][tk] = {
                    "target": None if tgt is None else round(tgt, 2),
                    # the level the stop actually sat at under THIS mode, so
                    # the table and the chart can show where it was placed
                    "stop_level": round(sl, 2),
                    # where the trail switched on and where the stop ended up
                    "trail_on": res.get("trail_on"),
                    "final_stop": round(res.get("final_stop", sl), 2),
                    "exit": round(res["exit"], 2), "exit_time": res["exit_time"],
                    "reason": res["reason"],
                    "points": round(pts, 2), "r_multiple": round(pts / risk, 3),
                    # how far past the WORKING stop the market fill landed
                    "slip": (round(abs(res["exit"] - res.get("final_stop", sl)), 2)
                             if "STOP" in res["reason"] else 0.0),
                    # The rule is decided on SPOT, but the money is made on the
                    # option that would actually have been bought.  `points` is
                    # the spot move and drives R; the rupee figure and the
                    # win/loss flag come from the PREMIUM, because that is what
                    # the account sees.  spot points x LOT_SIZE is a NIFTY
                    # FUTURES payoff and was what this reported before.
                    **_option_leg(pricer, opt_info, t, res),
                    "skipped": False,
                }
                open_until = res["exit_i"]
                open_side = t["side"]
    return trades


# ---------------------------------------------------------------------------
# Aggregation - the same numbers the other reports carry, nothing extra
# ---------------------------------------------------------------------------

def summarise(trades: list[dict], mode: str, tkey: str) -> dict:
    rows = [t["ex"][mode][tkey] for t in trades
            if t.get("ex") and not t["ex"][mode][tkey].get("skipped")]
    n = len(rows)
    if not n:
        return {"days": 0, "trades": 0, "priced": 0, "unpriced": 0,
                "wins": 0, "losses": 0, "win_rate": 0.0, "pnl_prem": 0.0,
                "pnl_pts": 0.0, "pnl_rs": 0.0, "stops": 0, "slip": 0.0,
                "avg_r": 0.0, "no_target": 0, "capital": 0.0,
                "trail_stops": 0, "sqo": 0, "targets": 0,
                "avg_win_rs": 0.0, "avg_loss_rs": 0.0, "rr_real": 0.0,
                "worst_rs": 0.0, "roi": 0.0}
    # Money and win/loss come from the PREMIUM, because that is what the
    # account actually sees.  pnl_pts stays the SPOT move, for reference and
    # because R is measured on the spot geometry the rule defines.
    priced = [x for x in rows if x.get("prem_pts") is not None]
    wins = [x for x in priced if x["prem_pts"] > 0]
    losses_ = [x for x in priced if x["prem_pts"] <= 0]
    pts = sum(x["points"] for x in rows)
    prem = sum(x["prem_pts"] for x in priced)
    np_ = len(priced)
    # THE RISK IS THE PREMIUM PAID.  The old avg_r divided by (entry - zone
    # edge), which under `none` never fires at all and under `zone`/`prem` is
    # not where the trade actually exits either.  What is genuinely at risk on
    # a bought option is what it cost, so that is what gets reported.
    paid = [x["entry_px"] for x in priced if x.get("entry_px")]
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
        "avg_win_rs": round(avg_w * LOT_SIZE, 2),
        "avg_loss_rs": round(avg_l * LOT_SIZE, 2),
        "rr_real": round(abs(avg_w / avg_l), 2) if avg_l else 0.0,
        "worst_rs": round(worst * LOT_SIZE, 2),
        "roi": round(prem / sum(paid) * 100, 2) if paid else 0.0,
        "stops": len([x for x in rows if x["reason"] == "STOP"]),
        "trail_stops": len([x for x in rows if x["reason"] == "TRAIL STOP"]),
        "sqo": len([x for x in rows if x["reason"].startswith("SQUARE")]),
        "targets": len([x for x in rows if x["reason"] == "TARGET"]),
        "slip": round(sum(x["slip"] for x in rows), 2),
        "avg_r": round(sum(x["r_multiple"] for x in rows) / n, 3),
        "no_target": len([x for x in rows if x["target"] is None]),
    }


def in_view(t: dict, view: str) -> bool:
    if view == "both":
        return True
    return t["side"] == ("LONG" if view == "long" else "SHORT")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def simulate_day(day: str, minutes: list[dict], tf: int, args) -> dict:
    """One session on one timeframe: structure, signals, priced trades."""
    bars = build_buckets(minutes, tf)
    row: dict = {"date": day, "status": "no data", "bos": None, "zone": None,
                 "dead": None, "events": [], "trades": [], "swings": None,
                 "day_open": None, "day_high": None, "day_low": None,
                 "day_close": None}
    if not bars or bars[0]["start"] != OPEN_TIME:
        return row
    row["day_open"] = round(bars[0]["open"], 2)
    row["day_high"] = round(max(b["high"] for b in bars), 2)
    row["day_low"] = round(min(b["low"] for b in bars), 2)
    row["day_close"] = round(bars[-1]["close"], 2)

    st = run_state_machine(
        bars, pivot=args.pivot, minor_pivot=args.minor_pivot,
        major_pivot=args.major_pivot, zone_lookback=args.zone_lookback,
        buffer=args.buffer, session_start=args.session_start,
        signal_until=args.signal_until,
        allow_same_bar_bos=args.allow_same_bar_bos,
        fail_buffer=args.fail_buffer, fail_closes=args.fail_closes,
        max_per_day=args.max_per_day, reentry_gap=args.reentry_gap,
        max_reentries=args.max_reentries, stop_pts=args.stop_pts,
        stop_anchor=args.stop_anchor,
        entry_until=args.entry_until, stop_pad=args.stop_pad,
        take_primary=True)
    row.update({k: st[k] for k in ("status", "bos", "zone", "dead", "events",
                                   "swings")})
    row["original_dir"] = st["original_dir"]

    if st["signals"]:
        trades = price_trades(
            bars, st["signals"], rr_values=args.rr_values,
            stop_modes=[k for k, _ in STOP_MODES], eod=args.eod,
            square_off=args.square_off, min_risk=args.min_risk,
            pricer=PRICER, day=day,
            trail_act=args.trail_act, trail_dist=args.trail_dist,
            with_liq=args.with_liq)
        for t in trades:
            t["date"] = day
            t.pop("i", None)
        row["trades"] = trades
        # If every signal was rejected as unplaceable, the day must not keep
        # claiming "trade": the table has no row to show for it and it would
        # read as a rendering bug rather than as the rule refusing the entry.
        if not any(t.get("ex") for t in trades):
            why = [t.get("dead", "") for t in trades]
            row["status"] = ("entry through the stop"
                             if any("through the stop" in w for w in why)
                             else "risk below the floor")
    return row


async def run(args) -> None:
    candles = await load_nifty(args.offline, args.from_date, args.to_date)
    by_day = index_by_day(candles)
    days = sorted(d for d in by_day
                  if args.from_date.isoformat() <= d <= args.to_date.isoformat())
    if not days:
        raise RuntimeError("No sessions in the requested window.")
    daily_close = await load_daily(args.offline, args.from_date, args.to_date)

    tkeys = target_keys(args.rr_values, args.with_liq)
    stop_modes = [k for k, _ in STOP_MODES]
    views = [k for k, _ in VIEWS]

    # ---- two passes, and the order is the whole point --------------------
    # Pass 1 runs the rule on SPOT alone.  Entry, stop and target are decided
    # there and nowhere else; the option cannot move a level or change which
    # trades exist.  Only once the signals are known do we resolve the ATM
    # contracts they imply and fetch whatever the requested date range is
    # missing.  Pass 2 then re-runs the identical simulation with those prices
    # available, purely so each trade carries a rupee figure.
    global PRICER
    needs = {(t["date"], t["side"], t["entry"])
             for tf in TIMEFRAMES for d in days
             for t in simulate_day(d, by_day[d], tf, args)["trades"] if t.get("ex")}
    PRICER = await ensure_cached(
        needs, None if args.offline else _read_access_token(), args.offline)

    tf_rows: dict[str, list[dict]] = {}
    tf_trades: dict[str, list[dict]] = {}
    for tf in TIMEFRAMES:
        rows = [simulate_day(d, by_day[d], tf, args) for d in days]
        for r in rows:
            r["official_close"] = (round(daily_close[r["date"]], 2)
                                   if r["date"] in daily_close else None)
        tf_rows[str(tf)] = rows
        tf_trades[str(tf)] = [t for r in rows for t in r["trades"] if t.get("ex")]

    # ---- split-half ------------------------------------------------------
    # 146 trades is a small sample and every parameter here was chosen by
    # looking at it.  Reporting each combination over the first and second half
    # of the sessions separately is the cheapest guard against shipping a
    # number that only exists in one half.  A setting that flips sign between
    # halves has not been demonstrated, whatever the full-sample figure says.
    mid = days[len(days) // 2]

    def half(trades, which):
        if which == "h1":
            return [t for t in trades if t["date"] < mid]
        return [t for t in trades if t["date"] >= mid]

    summaries = {
        str(tf): {
            v: {m: {tk: summarise([t for t in tf_trades[str(tf)] if in_view(t, v)],
                                  m, tk)
                    for tk in tkeys}
                for m in stop_modes}
            for v in views}
        for tf in TIMEFRAMES}

    # 1-minute candles for the chart, shared by both timeframes - the report
    # aggregates them to 3 minutes itself, so a day is never stored twice.
    trade_days = sorted({t["date"] for tf in TIMEFRAMES
                         for t in tf_trades[str(tf)]})
    chart_days = {
        d: [[c["timestamp"][11:16], round(float(c["open"]), 2),
             round(float(c["high"]), 2), round(float(c["low"]), 2),
             round(float(c["close"]), 2)]
            for c in by_day[d]
            if OPEN_TIME <= c["timestamp"][11:16] <= DAY_END]
        for d in trade_days}

    halves = {
        str(tf): {h: {m: {tk: summarise(half(tf_trades[str(tf)], h), m, tk)
                          for tk in tkeys}
                      for m in stop_modes}
                  for h in ("h1", "h2")}
        for tf in TIMEFRAMES}

    payload = {
        "meta": {
            "from": days[0], "to": days[-1], "sessions": len(days),
            "timeframes": [str(tf) for tf in TIMEFRAMES], "default_tf": str(args.tf),
            "pivot": args.pivot, "minor_pivot": args.minor_pivot,
            "major_pivot": args.major_pivot, "buffer": args.buffer,
            "zone_lookback": args.zone_lookback,
            "rr_values": [rr_label(r) for r in args.rr_values],
            "stop_pts": args.stop_pts,
            "trail_act": args.trail_act, "trail_dist": args.trail_dist,
            "target_keys": tkeys, "default_target": args.default_target,
            "target_modes": [{"key": k, "label": v} for k, v in TARGET_MODES],
            "stop_modes": [{"key": k, "label": v} for k, v in STOP_MODES],
            "default_stop": args.stop_mode,
            "views": [{"key": k, "label": v} for k, v in VIEWS],
            "default_view": args.view,
            "fail_buffer": args.fail_buffer, "fail_closes": args.fail_closes,
            "max_per_day": args.max_per_day, "reentry_gap": args.reentry_gap,
            "max_reentries": args.max_reentries,

            "min_risk": args.min_risk,
            "stop_anchor": args.stop_anchor,
            "entry_until": args.entry_until,
            "stop_pad": args.stop_pad,
            "take": "primary",
            "take_label": TAKE_LABEL,
            "eod": args.eod,
            "eod_label": dict(EOD_MODES)[args.eod],
            "square_off": args.square_off, "signal_until": args.signal_until,
            "session_start": args.session_start,
            "same_bar_bos": bool(args.allow_same_bar_bos),
            "lot": LOT_SIZE, "generated": date.today().isoformat(),
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
        trades = tf_trades[str(tf)]
        status = defaultdict(int)
        for r in rows:
            status[r["status"]] += 1
        print(f"\n  {tf}-minute: {len(trades)} trades on "
              f"{len({t['date'] for t in trades})} days "
              f"(primary {len([t for t in trades if t['kind'] == 'primary'])}, "
              f"reversal {len([t for t in trades if t['kind'] == 'reversal'])})")
        print("    days by outcome: "
              + ", ".join(f"{k} {v}" for k, v in sorted(status.items(),
                                                        key=lambda kv: -kv[1])))
        for m in stop_modes:
            for tk in tkeys:
                o = summaries[str(tf)]["both"][m][tk]
                if not o["trades"]:
                    continue
                nt = (f"  no-target {o['no_target']}"
                      if o["no_target"] and tk not in ("trail",) else "")
                print(f"    stop {m:<5} target {tk:<8}: {o['wins']}W/{o['losses']}L "
                      f" win {o['win_rate']:>5}%  {o['pnl_pts']:>9} pts  "
                      f"Rs {o['pnl_rs']:>10,.0f}  R:R {o['rr_real']:>5}:1  "
                      f"stops {o['stops']}  slip {o['slip']}{nt}")
    print(f"\n  SPLIT-HALF at {mid} - a setting that flips sign here is not "
          f"demonstrated, whatever the full-sample number says")
    for tf in TIMEFRAMES:
        for m in stop_modes:
            tk = args.default_target
            f_ = summaries[str(tf)]["both"][m][tk]
            a = halves[str(tf)]["h1"][m][tk]
            b = halves[str(tf)]["h2"][m][tk]
            agree = "" if (a["pnl_rs"] >= 0) == (b["pnl_rs"] >= 0) else "   <-- HALVES DISAGREE"
            print(f"    {tf}m {m:<5} {tk:<8} full Rs {f_['pnl_rs']:>9,.0f} "
                  f"({f_['win_rate']:>5}%)   h1 Rs {a['pnl_rs']:>9,.0f} "
                  f"({a['win_rate']:>5}%)   h2 Rs {b['pnl_rs']:>9,.0f} "
                  f"({b['win_rate']:>5}%){agree}")
    print(f"\nReport: {args.out}")

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NIFTY NES supply/demand __FROM__ to __TO__</title>
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
</style>
</head>
<body>

<h1>NIFTY NES supply / demand
  <span class="dim" style="font-size:14px">&middot; first BOS builds the zone &middot;
  sweep + micro-BOS enters it</span></h1>
<div class="sub">
  The whole day is one state machine. <b>1</b> &mdash; after __SSTART__ the first candle to
  <b>CLOSE</b> beyond a confirmed swing (pivot __PIVOT__) sets the day's direction; a wick
  through is not a BOS. <b>2</b> &mdash; the <b>zone</b> is the last opposite-colour candle
  before that displacement, taken as its full high&ndash;low range: a bullish BOS builds
  <b class="pos">demand</b>, a bearish BOS builds <b class="neg">supply</b>. <b>3</b> &mdash;
  price comes back and <b>touches</b> the zone; the entry is the <b>close of that touching
  candle</b> &mdash; long in demand, short in supply. One trade per day.<br>
  <b>Stop</b> &mdash; a <b>market order __STOPPTS__ points from the entry</b>, below it for a
  long and above it for a short, placed with the entry. <b>Risk</b> = __STOPPTS__ points on
  every trade. <b>Trail</b> &mdash; once the trade is <b>__TRAILACT__ points in favour</b>, the
  stop moves to <b>__TRAILDIST__ behind the best price</b> and is re-set each completed
  1-minute candle the best price improves; it only ever tightens. A stop that fires after the
  trail switched on is a <b>TRAIL STOP</b>; before that it is a plain STOP at &minus;__STOPPTS__.
  Exits are market orders, so the fill is the print at the minute the level trades, not the
  level itself &mdash; the <b>slip</b> column shows by how much.
  <b>Target</b> &mdash; the rule has <b>no fixed target</b>: the trailing stop is the exit
  (the <b>trail</b> tab). The 1:0.5 / 1:1 / 1:2 / 1:3 and <b>liq</b> tabs are shown for
  comparison and mean &ldquo;the same trail, but also take profit at that level&rdquo;. Every
  fixed target above 100 was measured to make <i>less</i> than the trail, because only 13 of
  86 trades ever reach +200 and the rest give back their move waiting. The split-half block
  below flags any tab whose two halves disagree.<br>
  If the zone gives way &mdash; a candle closing beyond its far edge by more than the fail
  buffer &mdash; the setup is dead and the day is over. There is no flip and no reversal.<br>
  Swings never repaint: a pivot needs __PIVOT__ candles after it to confirm, so at candle
  <i>i</i> the newest usable swing is the one at <i>i</i>&minus;__PIVOT__.
  Signals stop at <b>__SIGUNTIL__</b>; open positions are __EODLABEL__.
  The rule is decided on NIFTY <b>spot</b>, but the money is the <b>option that would
  actually have been bought</b>: ATM strike at entry, nearest expiry on/after the day,
  long &rarr; CE and short &rarr; PE, filled at that contract's 1-minute closes. The
  &#8377; column is premium &times; __LOT__, not NIFTY points &times; __LOT__ &mdash; the
  latter is a <b>futures</b> payoff and overstates a bought option. <b>Reward : risk</b> is
  the real one &mdash; average winning premium against average losing premium &mdash; and
  <b>return on premium</b> is net premium over premium deployed. Rows with no option data
  stay in the table and are left out of the money totals. Shorts are scored as
  Entry &minus; Exit.<br>
  A target reached inside a candle beats that candle's close; when one minute both touches
  the target and trades the stop, the stop is taken first.<br>
  Range __FROM__ &rarr; __TO__ &middot; __NDAYS__ trading days.
</div>

<div class="card">
  <div class="tabrow"><span class="cap">Timeframe</span><span id="tabsF" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow"><span class="cap">View</span><span id="tabsV" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow" style="display:none"><span class="cap">Stop rule</span><span id="tabsS" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow" id="tabrowT"><span class="cap">Exit</span><span id="tabsT" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow" style="margin-bottom:0"><span class="cap">Selected</span><span id="selDesc" style="font-size:12.5px;color:var(--ink2)"></span></div>
</div>

<div class="card">
  <h2>The rule on each timeframe</h2>
  <div class="ctrl dim" id="matrixNote"></div>
  <div class="scroll"><table class="matrix" id="matrix"></table></div>
</div>

<div class="card">
  <h2>Overall &mdash; <span id="ovF"></span>, <span id="ovV"></span>, <span id="ovS"></span>, target <span id="ovT"></span></h2>
  <div class="stat-row" id="overall"></div>
</div>

<div class="card">
  <h2>1-minute vs 3-minute &mdash; <span id="cmpWhat"></span></h2>
  <div class="ctrl dim">The same rule read on two timeframes. Different swings means different
    trades, not just different exits, so these are two separate strategies rather than two
    views of one.</div>
  <div class="scroll short"><table id="tblTf"></table></div>
</div>

<div class="card">
  <h2>How the __NDAYS__ sessions ended</h2>
  <div class="scroll short"><table id="tblStatus"></table></div>
</div>

<div class="card">
  <h2>NIFTY chart &mdash; the zone, the swings and the trade</h2>
  <div class="ctrl">
    <label for="daySel">Trade day</label>
    <select id="daySel"></select>
    <button class="btn" id="zoomIn">Zoom +</button>
    <button class="btn" id="zoomOut">Zoom &minus;</button>
    <button class="btn" id="zoomReset">Whole session</button>
    <label><input type="checkbox" id="showSwings" checked> swings</label>
    <span class="dim">wheel = zoom &middot; drag = pan &middot; double-click = reset</span>
  </div>
  <div class="chart-wrap"><svg id="chart" viewBox="0 0 1200 430"></svg><div id="tip"></div></div>
  <div class="legend">
    <span><i style="background:var(--zone)"></i>The zone (flips in place if it fails)</span>
    <span><i style="background:var(--warn)"></i>BOS level &mdash; the swing that was broken</span>
    <span><i style="background:var(--up)"></i>Target</span>
    <span><i style="background:var(--down)"></i>Stop</span>
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
  <div class="scroll"><table id="tblDays"></table></div>
</div>

<div class="card">
  <h2>Daily summary</h2>
  <div class="scroll short"><table id="tblDaily"></table></div>
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
let curF = M.default_tf, curV = M.default_view, curS = M.default_stop, curT = M.default_target;

const stopLabel = k => (M.stop_modes.find(m => m.key === k) || {}).label || k;
// the column, the tabs and the headers all read the rule's own label from
// M.stop_modes - never a hard-coded string, which is how a stale label once
// outlived the rule it described
const stopShort = k => (M.stop_modes.find(m => m.key === k) || {}).label || k;
const viewLabel = k => (M.views.find(v => v.key === k) || {}).label || k;
const viewShort = k => ({both:'Both', long:'Long', short:'Short'})[k] || k;
const tgtShort = k => k === 'trail' ? 'Trail only'
                    : k.startsWith('rr:') ? k.slice(3) : 'Opposing liquidity';
const tgtLabel = k => k === 'trail'
  ? 'No fixed target - the trailing stop is the exit'
  : k.startsWith('rr:')
  ? `Entry &plusmn; Risk &times; ${k.slice(3).split(':')[1]}, risk = the stop distance`
  : 'Opposing liquidity - the session extreme or the latest confirmed major swing beyond it';
const sidePill = s => s === 'LONG'
  ? '<span class="pill long">BUY</span>' : '<span class="pill short">SELL</span>';


const n2 = v => (v===null||v===undefined||isNaN(v)) ? '&ndash;' : Number(v).toFixed(2);
const sgn = (v,d=2) => (v===null||v===undefined||isNaN(v)) ? '&ndash;'
      : `<span class="${v>0?'pos':(v<0?'neg':'dim')}">${v>0?'+':''}${Number(v).toFixed(d)}</span>`;
const sgnRs = v => (v===null||v===undefined||isNaN(v)) ? '&ndash;'
      : `<span class="${v>0?'pos':(v<0?'neg':'dim')}">${v>0?'+':''}${Math.round(v).toLocaleString('en-IN')}</span>`;

function inView(t, v) {
  if (v === 'both') return true;
  return t.side === (v === 'long' ? 'LONG' : 'SHORT');
}
/* every trade of the selected timeframe and view, flattened onto the selected
   stop rule + target so the tables can read one object */
function tradesFor(tf, v, s, t) {
  const sm = s || curS, tk = t || curT;
  return DATA.tf_trades[tf || curF]
    .filter(x => inView(x, v || curV))
    // a signal can be legal under one target and skipped under another - it
    // was still in a position when the next confirmation fired - so the row
    // set genuinely differs between columns
    .filter(x => x.ex && x.ex[sm] && x.ex[sm][tk] && !x.ex[sm][tk].skipped)
    .map(x => Object.assign({}, x, x.ex[sm][tk]));
}
function daysFor() { return DATA.tf_days[curF]; }
function S() { return DATA.summaries[curF][curV][curS][curT]; }

/* the same arithmetic summarise() does in Python, so the grouped tables and the
   headline stats can never drift apart */
function summarise(rows) {
  const n = rows.length;
  if (!n) return {days:0, trades:0, priced:0, unpriced:0, wins:0, losses:0,
                  win_rate:0, pnl_prem:0, pnl_pts:0, pnl_rs:0, stops:0,
                  slip:0, avg_r:0};
  const priced = rows.filter(r => r.prem_pts !== null && r.prem_pts !== undefined);
  const wins = priced.filter(r => r.prem_pts > 0).length;
  const wRows = priced.filter(r => r.prem_pts > 0);
  const lRows = priced.filter(r => r.prem_pts <= 0);
  const paid = priced.reduce((a,r) => a + (r.entry_px||0), 0);
  const aW = wRows.length ? wRows.reduce((a,r)=>a+r.prem_pts,0)/wRows.length : 0;
  const aL = lRows.length ? lRows.reduce((a,r)=>a+r.prem_pts,0)/lRows.length : 0;
  const pts = rows.reduce((a,r) => a + r.points, 0);
  const prem = priced.reduce((a,r) => a + r.prem_pts, 0);
  const np = priced.length;
  return {
    days: new Set(rows.map(r => r.date)).size, trades: n,
    priced: np, unpriced: n - np,
    wins, losses: np - wins, win_rate: np ? wins / np * 100 : 0,
    pnl_prem: prem, pnl_pts: pts, pnl_rs: prem * LOT,
    capital: paid * LOT, avg_win_rs: aW * LOT, avg_loss_rs: aL * LOT,
    rr_real: aL ? Math.abs(aW/aL) : 0,
    worst_rs: priced.length ? Math.min(...priced.map(r=>r.prem_pts)) * LOT : 0,
    roi: paid ? prem / paid * 100 : 0,
    stops: rows.filter(r => r.reason === 'STOP').length,
    trail_stops: rows.filter(r => r.reason === 'TRAIL STOP').length,
    sqo: rows.filter(r => (r.reason||'').startsWith('SQUARE')).length,
    targets: rows.filter(r => r.reason === 'TARGET').length,
    slip: rows.reduce((a,r) => a + r.slip, 0),
    avg_r: rows.reduce((a,r) => a + r.r_multiple, 0) / n,
  };
}
function groupBy(rows, keyfn) {
  const m = new Map();
  rows.forEach(r => { const k = keyfn(r); if (!m.has(k)) m.set(k, []); m.get(k).push(r); });
  return [...m.keys()].sort().map(k => Object.assign({key:k}, summarise(m.get(k))));
}
function weekKey(r) {
  const d = new Date(r.date + 'T00:00:00');
  const off = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - off);
  return d.toISOString().slice(0,10);
}

/* ---------- tabs ---------- */
function mkTabs(el, items, cur, onPick) {
  const host = document.getElementById(el);
  host.innerHTML = '';
  items.forEach(it => {
    const b = document.createElement('button');
    b.className = 'tab' + (it.key === cur() ? ' on' : '');
    b.dataset.k = it.key;
    b.innerHTML = it.html;
    b.onclick = () => { onPick(it.key); syncTabs(); renderAll(); };
    host.appendChild(b);
  });
}
function buildTabs() {
  mkTabs('tabsF', M.timeframes.map(f => ({
    key: f, html: f + '-minute' +
      `<small>${DATA.tf_trades[f].length} trades</small>`})),
    () => curF, k => { curF = k; });
  mkTabs('tabsV', M.views.map(v => ({
    key: v.key, html: viewShort(v.key) +
      `<small>${DATA.summaries[curF][v.key][curS][curT].trades}</small>`})),
    () => curV, k => { curV = k; });
  mkTabs('tabsS', M.stop_modes.map(s => ({key: s.key, html: stopShort(s.key)})),
    () => curS, k => { curS = k; });
  mkTabs('tabsT', M.target_keys.map(t => ({key: t, html: tgtShort(t)})),
    () => curT, k => { curT = k; });
}
function syncTabs() { buildTabs();
  // with a single exit there is nothing to choose - hide the selector row
  document.getElementById('tabrowT').style.display = M.target_keys.length > 1 ? '' : 'none'; }

function table(el, head, rows, empty) {
  document.getElementById(el).innerHTML =
    '<thead><tr>' + head + '</tr></thead><tbody>' +
    (rows.join('') || `<tr><td class="dim" colspan="22">${empty||'no rows'}</td></tr>`) +
    '</tbody>';
}

/* ---------- matrix ---------- */
function renderMatrix() {
  let max = 1;
  M.timeframes.forEach(f => M.stop_modes.forEach(m => M.target_keys.forEach(t =>
    max = Math.max(max, Math.abs(DATA.summaries[f][curV][m.key][t].pnl_rs)))));
  const multiT = M.target_keys.length > 1;
  const head = '<th class="rh">Timeframe</th>' + (multiT ? '<th class="rh">Exit</th>' : '')
    + '<th>Trades</th><th class="pos">Won</th><th class="neg">Lost</th><th>Win rate</th>'
    + '<th>Exit: trail stop</th><th>Exit: stop &minus;100</th><th>Exit: square-off</th>'
    + (multiT ? '<th>Target cap</th>' : '')
    + '<th>Avg win (&#8377;)</th><th>Avg loss (&#8377;)</th><th>Reward : risk</th>'
    + '<th>Worst loss (&#8377;)</th><th>Net (&#8377;/lot)</th><th>Return on premium</th>';
  const rows = [];
  M.timeframes.forEach(f => M.stop_modes.forEach(m => M.target_keys.forEach(t => {
    const st = DATA.summaries[f][curV][m.key][t];
    const a = (Math.abs(st.pnl_rs) / max * 0.5).toFixed(3);
    const bg = st.pnl_rs >= 0 ? `rgba(var(--upN),${a})` : `rgba(var(--downN),${a})`;
    const sel = (f === curF && m.key === curS && t === curT) ? ' sel' : '';
    rows.push(`<tr data-tf="${f}" data-sm="${m.key}" data-tg="${t}">`
      + `<td class="rh${sel}">${f}-minute</td>`
      + (multiT ? `<td class="rh${sel}">${tgtShort(t)}</td>` : '')
      + `<td>${st.trades}</td>`
      + `<td class="pos">${st.wins}</td><td class="neg">${st.losses}</td>`
      + `<td>${st.win_rate.toFixed(1)}%</td>`
      + `<td class="pos">${st.trail_stops}</td><td class="neg">${st.stops}</td><td>${st.sqo}</td>`
      + (multiT ? `<td>${st.targets}</td>` : '')
      + `<td>${sgnRs(st.avg_win_rs)}</td><td>${sgnRs(st.avg_loss_rs)}</td>`
      + `<td>${st.rr_real.toFixed(2)} : 1</td><td>${sgnRs(st.worst_rs)}</td>`
      + `<td class="${sel}" style="background:${bg}">${sgnRs(st.pnl_rs)}</td>`
      + `<td>${st.roi.toFixed(2)}%</td></tr>`);
  })));
  table('matrix', head, rows);
  document.querySelectorAll('#matrix tr[data-tf]').forEach(tr => {
    tr.onclick = () => {
      curF = tr.dataset.tf; curS = tr.dataset.sm; curT = tr.dataset.tg;
      syncTabs(); renderAll();
    };
  });
}

/* ---------- summaries ---------- */
function statBlock(s) {
  return [
    [s.days, 'trade days'], [s.trades, 'trades'],
    [s.wins, 'success'], [s.losses, 'fail'],
    [s.win_rate.toFixed(1)+'%', 'win rate'],
    [s.rr_real.toFixed(2)+' : 1', 'reward : risk (real)'],
    [(s.pnl_pts>0?'+':'')+s.pnl_pts.toFixed(2), 'NIFTY move (pts)'],
    [(s.pnl_prem>0?'+':'')+s.pnl_prem.toFixed(2), 'option premium (pts)'],
    [(s.pnl_rs>0?'+':'')+Math.round(s.pnl_rs).toLocaleString('en-IN'), 'net PnL (1 lot ₹, premium)'],
    [sgnRs(s.avg_win_rs), 'avg win (₹)'],
    [sgnRs(s.avg_loss_rs), 'avg loss (₹)'],
    [sgnRs(s.worst_rs), 'worst single loss (₹)'],
    [Math.round(s.capital).toLocaleString('en-IN'), 'premium deployed (₹)'],
    [s.roi.toFixed(2)+'%', 'return on premium'],
  ].map(([v,l]) => `<div class="stat"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
}
function summaryTable(el, rows, label) {
  const head = `<th>${label}</th><th class="num">Trade days</th><th class="num">Trades</th>
    <th class="num">Success</th><th class="num">Fail</th><th class="num">Win %</th>
    <th class="num">Avg R</th><th class="num">Net PnL (pts)</th><th class="num">Net PnL (₹)</th>`;
  table(el, head, rows.map(r => `<tr><td>${r.key}</td><td class="num">${r.days}</td>
    <td class="num">${r.trades}</td><td class="num pos">${r.wins}</td>
    <td class="num neg">${r.losses}</td><td class="num">${r.win_rate.toFixed(1)}%</td>
    <td class="num">${sgn(r.avg_r,2)}</td>
    <td class="num">${sgn(r.pnl_pts)}</td><td class="num">${sgnRs(r.pnl_rs)}</td></tr>`),
    'no trades');
}

/* ---------- 1-minute vs 3-minute, side by side ---------- */
function renderTfCompare() {
  document.getElementById('cmpWhat').textContent =
    `${viewShort(curV)}, ${stopShort(curS)}, target ${tgtShort(curT)}`;
  const head = '<th>Timeframe</th><th class="num">Trade days</th><th class="num">Trades</th>'
    + '<th class="num">Success</th><th class="num">Fail</th><th class="num">Win %</th>'
    + '<th class="num">Avg R</th><th class="num">Stops</th><th class="num">Slip (pts)</th>'
    + '<th class="num">Net PnL (pts)</th><th class="num">Net PnL (₹)</th>';
  const rows = M.timeframes.map(f => {
    const st = DATA.summaries[f][curV][curS][curT];
    const on = f === curF ? ' style="font-weight:600"' : '';
    return `<tr${on}><td>${f}-minute${f===curF?' <span class="dim">(selected)</span>':''}</td>`
      + `<td class="num">${st.days}</td><td class="num">${st.trades}</td>`
      + `<td class="num pos">${st.wins}</td><td class="num neg">${st.losses}</td>`
      + `<td class="num">${st.win_rate.toFixed(1)}%</td><td class="num">${sgn(st.avg_r,2)}</td>`
      + `<td class="num">${st.stops}</td>`
      + `<td class="num ${st.slip>0?'neg':'dim'}">${st.slip.toFixed(2)}</td>`
      + `<td class="num">${sgn(st.pnl_pts)}</td><td class="num">${sgnRs(st.pnl_rs)}</td></tr>`;
  });
  table('tblTf', head, rows);
}

/* ---------- how the sessions ended ---------- */
function renderStatus() {
  const counts = new Map();
  daysFor().forEach(d => counts.set(d.status, (counts.get(d.status)||0) + 1));
  const explain = {
    'trade': 'the rule completed and a position was opened',
    'no BOS': 'no candle ever closed beyond a confirmed swing',
    'no zone candle': 'the BOS had no opposite-colour candle behind it',
    'entry through the stop': 'the confirmation fired with the entry already past its own stop - unplaceable, so no trade',
    'risk below the floor': 'the stop was closer than --min-risk points - noise-width, so no trade',
    'no touch': 'the zone was built but price never came back to it',
    'no confirmation': 'the zone was touched but the sweep + micro-BOS never completed',
    'zone failed': 'the zone gave way before the confirmation completed - day over',
    'filtered out': 'the rule fired but the trade failed a v2 entry filter',
    'no data': 'the session is missing candles',
  };
  const rows = [...counts.entries()].sort((a,b) => b[1]-a[1]).map(([k,v]) =>
    `<tr><td>${k}</td><td class="num">${v}</td>
     <td class="num">${(v/daysFor().length*100).toFixed(1)}%</td>
     <td class="dim">${explain[k]||''}</td></tr>`);
  table('tblStatus', '<th>Outcome</th><th class="num">Sessions</th><th class="num">Share</th><th>What it means</th>', rows);
}

/* ---------- trade table ---------- */
function closePill(ct) {
  const base = (ct||'').split(' ')[0];
  if (base === 'TARGET') return '<span class="pill tgt">TARGET</span>';
  if (base === 'TRAIL') return '<span class="pill tgt">TRAIL STOP</span>';
  if (base === 'STOP') return '<span class="pill sl">STOP</span>';
  if (base === 'SQUARE') return '<span class="pill eod">SQUARE OFF</span>';
  return `<span class="pill eod">${base||'&ndash;'}</span>`;
}
function renderDays() {
  const only = document.getElementById('onlyTrades').checked;
  const trades = tradesFor();
  const byDay = new Map();
  trades.forEach(t => { if (!byDay.has(t.date)) byDay.set(t.date, []); byDay.get(t.date).push(t); });
  const head = `<th>Date</th><th>Dir</th><th>Zone</th><th>BOS</th>
    <th>Touch</th><th class="num">Zone width</th><th>Entry time</th>
    <th class="num">Entry</th><th class="num">Stop</th><th class="num">Risk</th>
    <th class="num">Stop</th><th class="num">Target</th><th class="num">Exit</th><th>Close type</th>
    <th class="num">NIFTY pts</th><th class="num">R</th>
    <th>Contract</th><th class="num">Prem in</th><th class="num">Prem out</th>
    <th class="num">Prem pts</th><th class="num">PnL (₹)</th>
    <th>Exit time</th><th>Note</th>`;
  const body = [];
  daysFor().forEach(d => {
    const ts = byDay.get(d.date) || [];
    if (!ts.length) {
      if (only) return;
      body.push(`<tr><td>${d.date}</td>
        <td colspan="2" class="dim">${d.zone ? n2(d.zone.low)+' &ndash; '+n2(d.zone.high) : '&mdash;'}</td>
        <td class="dim">${d.bos ? d.bos.dir[0]+d.bos.dir.slice(1).toLowerCase()+' '+d.bos.time : '&mdash;'}</td>
        <td colspan="14" class="dim">&mdash;</td><td class="dim">${d.status}</td></tr>`);
      return;
    }
    ts.forEach(r => {
      body.push(`<tr><td>${r.date}</td><td>${sidePill(r.side)}</td>
        <td class="dim">${n2(r.zone_low)} &ndash; ${n2(r.zone_high)}</td>
        <td class="dim">${d.bos ? d.bos.time+' @ '+n2(d.bos.level) : '&mdash;'}</td>
        <td class="dim">${r.touch_time||'&mdash;'}</td>
        <td class="num dim">${n2(r.zone_width)}</td>
        <td>${r.entry_time}</td><td class="num">${n2(r.entry)}</td>
        <td class="num dim">${n2(r.sl)}</td><td class="num dim">${n2(r.risk)}</td>
        <td class="num dim">${n2(r.stop_level)}${r.trail_on
            ? ` <small>&rarr; ${n2(r.final_stop)} (trail on ${r.trail_on})</small>`
            : ' <small>market</small>'}</td>
        <td class="num dim">${r.target===null?'<span class="pill no">none</span>':n2(r.target)}</td>
        <td class="num">${n2(r.exit)}</td><td>${closePill(r.reason)}</td>
        <td class="num">${sgn(r.points)}</td><td class="num">${sgn(r.r_multiple,2)}</td>
        <td class="dim">${r.opt_symbol || '<span class="pill no">'+(r.opt_reason||'not priced')+'</span>'}</td>
        <td class="num dim">${n2(r.entry_px)}</td><td class="num dim">${n2(r.exit_px)}</td>
        <td class="num">${sgn(r.prem_pts)}</td>
        <td class="num">${r.pnl_rs===null||r.pnl_rs===undefined?'<span class="pill no">no option data</span>':sgnRs(r.pnl_rs)}</td>
        <td>${r.exit_time}</td>
        <td class="dim">${r.opt_reason ? `<span class="neg">${r.opt_reason}</span>` : 'priced'}</td></tr>`);
    });
  });
  table('tblDays', head, body, 'no trades in this view');
}

/* ---------- chart ---------- */
const W = 1200, H = 430, PADL = 8, PADR = 62, PADT = 14, PADB = 26;
const svg = document.getElementById('chart');
const tip = document.getElementById('tip');
let chartState = null;

function tmin(t) { return (+t.slice(0,2)) * 60 + (+t.slice(3,5)); }
function tlabel(m) { return String(Math.floor(m/60)).padStart(2,'0') + ':' + String(m%60).padStart(2,'0'); }
/* the payload only ever carries 1-minute candles; the 3-minute view is built
   here so a session is never stored twice */
function bucketize(rows, tf) {
  if (+tf === 1) return rows.map(r => r.slice());
  const out = []; let cur = null, ck = null;
  rows.forEach(r => {
    const k = Math.floor((tmin(r[0]) - tmin('09:15')) / tf);
    if (k !== ck) { if (cur) out.push(cur); ck = k; cur = [tlabel(tmin('09:15') + k*tf), r[1], r[2], r[3], r[4]]; }
    else { cur[2] = Math.max(cur[2], r[2]); cur[3] = Math.min(cur[3], r[3]); cur[4] = r[4]; }
  });
  if (cur) out.push(cur);
  return out;
}
function clampWindow(n, i0, i1) {
  const MIN = 12;
  if (i1 - i0 < MIN) { const mid = (i0 + i1) / 2; i0 = mid - MIN/2; i1 = mid + MIN/2; }
  if (i1 - i0 > n)   { i0 = 0; i1 = n; }
  if (i0 < 0) { i1 -= i0; i0 = 0; }
  if (i1 > n) { i0 -= (i1 - n); i1 = n; }
  return [Math.max(0, i0), Math.min(n, i1)];
}

function drawChart() {
  if (!chartState) { svg.innerHTML = ''; return; }
  const { c, day, drow, trades } = chartState;
  let [i0, i1] = [chartState.i0, chartState.i1];
  const view = c.slice(Math.floor(i0), Math.ceil(i1));
  if (!view.length) return;
  const lvls = [];
  if (drow.zone) lvls.push(drow.zone.low, drow.zone.high);
  if (drow.bos) lvls.push(drow.bos.level);
  trades.forEach(t => { lvls.push(t.sl); if (t.target !== null) lvls.push(t.target); });
  let lo = Math.min(...view.map(x => x[3]), ...lvls);
  let hi = Math.max(...view.map(x => x[2]), ...lvls);
  const pad = (hi - lo) * 0.06 || 10; lo -= pad; hi += pad;

  const iw = W - PADL - PADR, ih = H - PADT - PADB;
  const span = i1 - i0;
  const x = i => PADL + (i - i0 + 0.5) * iw / span;
  const y = v => PADT + (hi - v) * ih / (hi - lo);
  const bw = Math.max(1.2, iw / span * 0.62);
  /* exit times come off the 1-minute feed, so on the 3-minute view they are
     usually NOT a bucket label - map any time to the bucket containing it */
  const at = t => {
    if (!t) return -1;
    const k = Math.floor((tmin(t) - tmin('09:15')) / (+curF));
    return (k >= 0 && k < c.length) ? k : -1;
  };

  let s = '';
  /* the zone, drawn from the candle it was built on to the right edge */
  if (drow.zone) {
    const zi = Math.max(0, at(drow.zone.time));
    const zx = Math.max(PADL, x(zi) - bw/2);
    const yt = y(drow.zone.high), yb = y(drow.zone.low);
    s += `<rect x="${zx.toFixed(1)}" y="${yt.toFixed(1)}" width="${(PADL+iw-zx).toFixed(1)}" `
       + `height="${Math.max(1,yb-yt).toFixed(1)}" fill="rgba(var(--zoneN),.13)" `
       + `stroke="var(--zone)" stroke-width="1" stroke-dasharray="3 3"/>`
       + `<text x="${(zx+4).toFixed(1)}" y="${(yt-4).toFixed(1)}" font-size="10" fill="var(--zone)">`
       + `${drow.zone.type} ${drow.zone.low.toFixed(2)}&ndash;${drow.zone.high.toFixed(2)}`
       + `${drow.flip ? ' &rarr; flipped ' + drow.flip.to + ' at ' + drow.flip.time : ''}</text>`;
  }
  for (let k = 0; k <= 6; k++) {
    const v = lo + (hi - lo) * k / 6, yy = y(v);
    s += `<line x1="${PADL}" y1="${yy}" x2="${PADL+iw}" y2="${yy}" stroke="var(--grid)"/>`
       + `<text x="${PADL+iw+6}" y="${yy+3.5}" font-size="10" fill="var(--muted)">${v.toFixed(0)}</text>`;
  }
  const step = Math.max(1, Math.round(span / 10));
  for (let i = Math.ceil(i0); i < i1; i++) {
    if ((i - Math.ceil(i0)) % step) continue;
    s += `<text x="${x(i)}" y="${H-8}" font-size="10" fill="var(--muted)" text-anchor="middle">${c[i][0]}</text>`
       + `<line x1="${x(i)}" y1="${PADT}" x2="${x(i)}" y2="${PADT+ih}" stroke="var(--grid)" opacity=".55"/>`;
  }
  for (let i = Math.floor(i0); i < Math.ceil(i1) && i < c.length; i++) {
    const [tm, o, h, l, cl] = c[i];
    const col = cl >= o ? 'var(--up)' : 'var(--down)';
    const yo = y(o), yc = y(cl);
    s += `<line x1="${x(i).toFixed(2)}" y1="${y(h).toFixed(2)}" x2="${x(i).toFixed(2)}" y2="${y(l).toFixed(2)}" stroke="${col}"/>`
       + `<rect x="${(x(i)-bw/2).toFixed(2)}" y="${Math.min(yo,yc).toFixed(2)}" width="${bw.toFixed(2)}" height="${Math.max(1,Math.abs(yc-yo)).toFixed(2)}" fill="${col}"/>`;
  }
  /* confirmed swings - the raw material every decision is made from */
  if (document.getElementById('showSwings').checked && drow.swings) {
    drow.swings.highs.forEach(sw => {
      const i = at(sw.t); if (i < i0 - 1 || i > i1) return;
      s += `<polygon points="${x(i)},${y(sw.p)-9} ${x(i)-4},${y(sw.p)-3} ${x(i)+4},${y(sw.p)-3}" fill="var(--muted)" opacity=".8"/>`;
    });
    drow.swings.lows.forEach(sw => {
      const i = at(sw.t); if (i < i0 - 1 || i > i1) return;
      s += `<polygon points="${x(i)},${y(sw.p)+9} ${x(i)-4},${y(sw.p)+3} ${x(i)+4},${y(sw.p)+3}" fill="var(--muted)" opacity=".8"/>`;
    });
  }
  const hline = (v, col, dash, label, atEnd) => v == null ? '' :
    `<line x1="${PADL}" y1="${y(v)}" x2="${PADL+iw}" y2="${y(v)}" stroke="${col}" stroke-width="1.4" stroke-dasharray="${dash}" opacity=".9"/>`
    + `<text x="${atEnd ? PADL+iw-4 : PADL+4}" y="${y(v)-4}" font-size="10" fill="${col}"`
    + `${atEnd ? ' text-anchor="end"' : ''}>${label} ${v.toFixed(2)}</text>`;
  if (drow.bos) s += hline(drow.bos.level, 'var(--warn)', '2 4',
    (drow.bos.dir === 'BULLISH' ? 'BOS swing high' : 'BOS swing low'), true);

  trades.forEach(t => {
    // The zone edge still sets `risk`, and the target is entry +/- risk x R,
    // so it is worth seeing - but it is NOT an exit any more and must not be
    // drawn as one.  Muted, dotted, and labelled for what it actually is.
    // the level the stop is actually working at under the selected rule
    if (t.stop_level != null)
      s += hline(t.stop_level, 'var(--down)', '6 3',
                 'Stop at entry (' + n2(t.risk) + ' pts)');
    if (t.trail_on && t.final_stop != null && t.final_stop !== t.stop_level)
      s += hline(t.final_stop, 'var(--up)', '2 3',
                 'Trailed stop (on ' + t.trail_on + ')', true);
    if (t.target !== null) s += hline(t.target, 'var(--up)', '6 3', 'Target');
    const ei = at(t.entry_time);
    if (ei >= 0) {
      const ex = x(ei), ey = y(t.entry);
      s += `<line x1="${ex}" y1="${PADT}" x2="${ex}" y2="${PADT+ih}" stroke="var(--accent)" stroke-width="1.2" stroke-dasharray="3 3"/>`
         + (t.side === 'LONG'
            ? `<polygon points="${ex},${ey} ${ex-6},${ey+12} ${ex+6},${ey+12}" fill="var(--accent)"/>`
            : `<polygon points="${ex},${ey} ${ex-6},${ey-12} ${ex+6},${ey-12}" fill="var(--accent)"/>`)
         + `<text x="${ex+9}" y="${ey + (t.side === 'LONG' ? 16 : -16)}" font-size="11" font-weight="600" fill="var(--accent)">${t.side === 'LONG' ? 'BUY' : 'SELL'} @ ${t.entry.toFixed(2)}</text>`;
    }
    const xi = at(t.exit_time);
    if (xi >= 0) {
      const xx = x(xi), xy = y(t.exit), col = t.points > 0 ? 'var(--up)' : 'var(--down)';
      s += `<polygon points="${xx},${xy-7} ${xx+7},${xy} ${xx},${xy+7} ${xx-7},${xy}" fill="${col}" stroke="var(--surface)" stroke-width="1.2"/>`
         + `<text x="${xx+11}" y="${xy+4}" font-size="11" font-weight="600" fill="${col}">${(t.reason||'').split(' ')[0]} @ ${t.exit.toFixed(2)}</text>`;
    }
  });
  const a = c[Math.floor(i0)], b = c[Math.min(c.length-1, Math.ceil(i1)-1)];
  s += `<text x="${PADL+iw-2}" y="${H-8}" font-size="10" fill="var(--muted)" text-anchor="end">`
     + `${day} &middot; ${a[0]} &ndash; ${b[0]} &middot; ${curF}-minute</text>`;
  svg.innerHTML = s;
}

function renderChart() {
  const day = document.getElementById('daySel').value;
  const info = document.getElementById('dayInfo');
  const raw = DATA.chart_days[day];
  const drow = daysFor().find(d => d.date === day);
  if (!raw || !drow) { chartState = null; svg.innerHTML = ''; info.textContent = '';
                       renderTimeline(null); return; }
  const c = bucketize(raw, +curF);
  const trades = tradesFor().filter(t => t.date === day);
  const keep = chartState && chartState.day === day && chartState.tf === curF
    ? [chartState.i0, chartState.i1] : [0, c.length];
  chartState = { day, tf: curF, c, drow, trades, i0: keep[0], i1: keep[1] };
  [chartState.i0, chartState.i1] = clampWindow(c.length, keep[0], keep[1]);
  drawChart();
  info.innerHTML = trades.length
    ? trades.map(t => `${sidePill(t.side)} entry ${t.entry_time} @ ${n2(t.entry)}`
        + ` &middot; stop ${n2(t.sl)} (risk ${n2(t.risk)}) &middot; target `
        + `${t.target===null?'none':n2(t.target)} &rarr; ${(t.reason||'').split(' ')[0]} `
        + `${t.exit_time} @ ${n2(t.exit)} &middot; ${sgn(t.points)} pts (${sgnRs(t.pnl_rs)})`).join('<br>')
    : '<span class="dim">no trade in this view on this day</span>';
  renderTimeline(drow);
}

function renderTimeline(drow) {
  const el = document.getElementById('timeline');
  if (!drow || !drow.events.length) { el.innerHTML = '<li class="dim">nothing to show</li>'; return; }
  /* the zone is created from a candle EARLIER than the BOS that revealed it,
     so the events are emitted out of order - show them chronologically */
  el.innerHTML = drow.events.slice().sort((a,b) => a.t < b.t ? -1 : (a.t > b.t ? 1 : 0)).map(e =>
    `<li><span class="tm">${e.t}</span>`
    + `<span class="k ${e.kind.replace('-','')}">${e.kind}</span>`
    + `<span>${e.text}</span></li>`).join('');
}

function zoomAt(factor, anchor) {
  if (!chartState) return;
  const { c } = chartState;
  let { i0, i1 } = chartState;
  const a = anchor === undefined ? (i0 + i1) / 2 : anchor;
  [chartState.i0, chartState.i1] =
    clampWindow(c.length, a - (a - i0) * factor, a + (i1 - a) * factor);
  drawChart();
}
svg.addEventListener('wheel', e => {
  if (!chartState) return;
  e.preventDefault();
  const box = svg.getBoundingClientRect();
  const px = (e.clientX - box.left) / box.width * W;
  const { i0, i1 } = chartState;
  const anchor = i0 + (px - PADL) / (W - PADL - PADR) * (i1 - i0);
  zoomAt(e.deltaY < 0 ? 0.82 : 1.22, anchor);
}, { passive: false });
let drag = null;
svg.addEventListener('pointerdown', e => {
  if (!chartState) return;
  drag = { x: e.clientX, i0: chartState.i0, i1: chartState.i1 };
  svg.classList.add('drag'); svg.setPointerCapture(e.pointerId);
});
svg.addEventListener('pointerup', e => {
  drag = null; svg.classList.remove('drag');
  try { svg.releasePointerCapture(e.pointerId); } catch (_) {}
});
svg.addEventListener('dblclick', () => resetZoom());
function resetZoom() {
  if (!chartState) return;
  chartState.i0 = 0; chartState.i1 = chartState.c.length; drawChart();
}
document.getElementById('zoomIn').onclick = () => zoomAt(0.7);
document.getElementById('zoomOut').onclick = () => zoomAt(1.4);
document.getElementById('zoomReset').onclick = resetZoom;
document.getElementById('showSwings').onchange = drawChart;

svg.addEventListener('pointermove', e => {
  if (!chartState) return;
  const box = svg.getBoundingClientRect();
  const { c } = chartState;
  if (drag) {
    const dx = (e.clientX - drag.x) / box.width * W;
    const perPx = (drag.i1 - drag.i0) / (W - PADL - PADR);
    [chartState.i0, chartState.i1] =
      clampWindow(c.length, drag.i0 - dx * perPx, drag.i1 - dx * perPx);
    drawChart();
    tip.style.display = 'none';
    return;
  }
  const px = (e.clientX - box.left) / box.width * W;
  const { i0, i1 } = chartState;
  const i = Math.round(i0 + (px - PADL) / (W - PADL - PADR) * (i1 - i0) - 0.5);
  if (i < 0 || i >= c.length) { tip.style.display = 'none'; return; }
  const [tm, o, h, l, cl] = c[i];
  tip.innerHTML = `<b>${tm}</b> <span style="opacity:.6">${chartState.day}</span><br>O ${o.toFixed(2)}<br>H ${h.toFixed(2)}<br>L ${l.toFixed(2)}<br>C ${cl.toFixed(2)}`;
  tip.style.display = 'block';
  tip.style.left = Math.min(e.clientX - box.left + 14, box.width - 110) + 'px';
  tip.style.top = Math.max(0, e.clientY - box.top - 60) + 'px';
});
svg.addEventListener('pointerleave', () => { tip.style.display = 'none'; });

/* ---------- orchestration ---------- */
function renderAll() {
  const sm = S();
  document.getElementById('ovF').textContent = curF + '-minute';
  document.getElementById('ovV').textContent = viewShort(curV);
  document.getElementById('ovS').textContent = stopShort(curS);
  document.getElementById('ovT').textContent = tgtShort(curT);
  document.getElementById('selDesc').innerHTML =
    `${viewLabel(curV)}. Stop: ${stopLabel(curS)}. Target: ${tgtLabel(curT)}.`
    + (curT === 'liq' && sm.no_target
       ? ` <span class="neg">${sm.no_target} of these trades had no liquidity on the far `
         + `side and ran on the stop and the square-off alone.</span>` : '');
  document.getElementById('overall').innerHTML = statBlock(sm);
  document.getElementById('matrixNote').innerHTML =
    `${viewShort(curV)} trades. One stop (market, 100 pts, trailing 30 behind the best price once +40) and one exit (that trail); `
    + 'The timeframe changes which swings exist, so it changes the trades themselves, '
    + 'not just the exits &mdash; the trade counts differ down the table. Click any row to select it.';
  renderMatrix();
  renderStatus();
  renderTfCompare();

  const sel = document.getElementById('daySel');
  const prev = sel.value;
  const days = [...new Set(tradesFor().map(t => t.date))].sort();
  sel.innerHTML = days.map(d => `<option value="${d}">${d}</option>`).join('');
  if (days.includes(prev)) sel.value = prev;
  renderChart();

  renderDays();
  const rows = tradesFor();
  summaryTable('tblDaily', groupBy(rows, r => r.date), 'Date');
  summaryTable('tblWeekly', groupBy(rows, weekKey), 'Week of');
  summaryTable('tblMonthly', groupBy(rows, r => r.date.slice(0,7)), 'Month');
}
document.getElementById('daySel').addEventListener('change', () => {
  if (chartState) chartState.day = null;
  renderChart();
});
document.getElementById('onlyTrades').addEventListener('change', renderDays);
buildTabs();
renderAll();
</script>
</body>
</html>
"""


def write_report(payload: dict, out_path: str) -> None:
    m = payload["meta"]
    html = (HTML_TEMPLATE
            .replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":")))
            .replace("__PIVOT__", str(m["pivot"]))
            .replace("__SSTART__", m["session_start"])
            .replace("__SIGUNTIL__", m["signal_until"])
            .replace("__EODLABEL__", m["eod_label"])
            .replace("__TAKE__", m["take_label"].split(" - ")[0].lower())
            .replace("__SQO__", m["square_off"])
            .replace("__STOPPTS__", f"{m['stop_pts']:g}")
            .replace("__TRAILACT__", f"{m['trail_act']:g}")
            .replace("__TRAILDIST__", f"{m['trail_dist']:g}")

            .replace("__LOT__", str(m["lot"]))
            .replace("__NDAYS__", str(m["sessions"]))
            .replace("__FROM__", m["from"])
            .replace("__TO__", m["to"]))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)



# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    today = date.today()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tf", type=int, choices=TIMEFRAMES, default=DEFAULT_TF,
                    help="timeframe selected when the report opens; both are "
                         "always computed")
    ap.add_argument("--pivot", type=int, default=PIVOT,
                    help="PIVOT_LENGTH for the swings the first BOS uses")
    ap.add_argument("--minor-pivot", type=int, default=MINOR_PIVOT,
                    help="pivot length for the sweep / micro-BOS swings")
    ap.add_argument("--major-pivot", type=int, default=PIVOT,
                    help="pivot length for the swings the opposing-liquidity "
                         "target aims at")
    ap.add_argument("--zone-lookback", type=int, default=ZONE_LOOKBACK,
                    help="how many bars back to search for the zone candle")
    ap.add_argument("--buffer", type=float, default=STOP_BUFFER,
                    help="stopBuffer in NIFTY points (the spec never gives it "
                         "a value)")
    ap.add_argument("--rr", dest="rr_values", type=float, nargs="+",
                    default=RR_VALUES, metavar="R",
                    help="OPTIONAL comparison tabs: the same trail, but also take "
                         "profit at entry +/- stop x R (e.g. --rr 1 2). Off by default")
    ap.add_argument("--no-liq", dest="with_liq", action="store_false", default=True,
                    help="drop the opposing-liquidity tab (shown by default: the same "
                         "trail, but also take profit at the opposing liquidity)")
    ap.add_argument("--stop-pts", type=float, default=STOP_PTS,
                    help="market stop this many NIFTY points from the entry")
    ap.add_argument("--trail-act", type=float, default=TRAIL_ACT,
                    help="the trail switches on once the trade is this many "
                         "points in favour (0 disables the trail)")
    ap.add_argument("--trail-dist", type=float, default=TRAIL_DIST,
                    help="once on, the stop sits this many points behind the "
                         "best price and only ever tightens")
    ap.add_argument("--target", dest="default_target", default=None,
                    help="target variant selected when the report opens: "
                         "an R:R like 1:2, or liq")
    ap.add_argument("--stop-mode", choices=[k for k, _ in STOP_MODES],
                    default=DEFAULT_STOP,
                    help="stop rule selected when the report opens; both are "
                         "always computed")
    ap.add_argument("--entry-until", default=ENTRY_UNTIL,
                    help="no new entry at or after this time (v2 filter 1)")
    ap.add_argument("--max-reentries", type=int, default=MAX_REENTRIES,
                    help="re-entries allowed after the zone edge is broken and "
                         "then closed back inside (0 = v3 behaviour)")
    ap.add_argument("--stop-pad", type=float, default=STOP_PAD,
                    help="stop sits this many zone widths beyond the far edge")
    ap.add_argument("--stop-anchor", choices=[k for k, _ in STOP_ANCHORS],
                    default=DEFAULT_ANCHOR,
                    help="what the stop is placed behind")
    ap.add_argument("--min-risk", type=float, default=MIN_RISK,
                    help="reject a signal whose risk is under this many NIFTY "
                         "points - such a stop is noise-width and always fills "
                         "at -1R (0 disables the floor)")
    ap.add_argument("--max-per-day", type=int, default=MAX_PER_DAY,
                    help="entries allowed per session while the zone holds "
                         "(the spec says 1)")
    ap.add_argument("--reentry-gap", type=int, default=REENTRY_GAP,
                    help="bars that must pass after an entry before another "
                         "confirmation can fire")
    ap.add_argument("--fail-buffer", type=float, default=FAIL_BUFFER,
                    help="the zone only fails once a close is this many ZONE "
                         "WIDTHS past its edge (0 = the literal spec)")
    ap.add_argument("--fail-closes", type=int, default=FAIL_CLOSES,
                    help="consecutive closes beyond the edge needed to fail "
                         "the zone (1 = the literal spec)")
    ap.add_argument("--view", choices=[k for k, _ in VIEWS], default=DEFAULT_VIEW,
                    help="view selected when the report opens; all are always "
                         "computed")
    ap.add_argument("--eod", choices=[k for k, _ in EOD_MODES], default=DEFAULT_EOD,
                    help="section 12: square off at the close time, or hold to "
                         "stop/target")
    ap.add_argument("--square-off", default=SQUARE_OFF)
    ap.add_argument("--session-start", default=SESSION_START,
                    help="nothing is looked at before this")
    ap.add_argument("--signal-until", default=None,
                    help="stop searching for new signals at this time "
                         "(default: the square-off time)")
    ap.add_argument("--allow-same-bar-bos", action="store_true",
                    help="let one candle be both the sweep and the micro-BOS; "
                         "off by default, which is the literal reading")
    ap.add_argument("--offline", action="store_true", help="use local caches only")
    ap.add_argument("--out", default=REPORT_HTML)
    ap.add_argument("--from", dest="from_date", type=date.fromisoformat,
                    default=today - timedelta(days=183), help="default: 6 months back")
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat, default=today)
    args = ap.parse_args()

    if args.signal_until is None:
        args.signal_until = args.square_off
    keys = target_keys(args.rr_values, args.with_liq)
    if args.default_target is None:
        # the report opens on the RULE - the trail - not on an R rung
        args.default_target = DEFAULT_TARGET if DEFAULT_TARGET in keys else keys[0]
    elif args.default_target not in keys:
        cand = f"rr:{args.default_target}"
        args.default_target = cand if cand in keys else keys[0]
    os.makedirs(REPORTS_DIR, exist_ok=True)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
