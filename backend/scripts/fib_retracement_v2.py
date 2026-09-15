"""Fib retracement v3 - v1's report, run on the parameter set v2 selected.

This file contains NO strategy logic and NO report code.  It imports both from
fib_retracement_v1.py, changes the defaults to the configuration the v2
stability grid picked, and writes the result to its own report.  If v1 changes,
v3 changes with it; the two can never drift apart.


THE PARAMETER SET, AND WHERE IT CAME FROM
------------------------------------------
    timeframe        5-minute      (opens on this; 1 and 3 are still computed)
    swing pivot      7 bars either side   <- the only change from v1
    zone             0.618 - 0.786
    stop             5 points past the far edge
    target           1:2   (1:3 and 1:4 still computed)
    entry            retest   - touch the zone, get rejected out of it, buy the return
    trade count      flow     - one position at a time
    entry cut-off    none     (15:15 square-off)

v2 ran 85 configurations over 9 parameters and 12 cleared its acceptance
criteria (trades >= 75, mean premium % > 0, recovery factor >= 1.0).  Ranked by
trade count, which is the user's stated requirement:

  configuration                                   N   mean%  win%   rec  total%    h1     h2
  5m p7 0.618/0.786 s5 1:2 retest flow          117   0.964  41.0  1.57   112.8  0.40   1.43  <-
  5m p8 0.55 /0.82  s5 1:2 retest flow           99   0.958  36.4  1.28    94.9  0.71   1.15
  5m p8 0.618/0.786 s5 1:2 retest flow           97   0.646  41.2  1.00    62.6  0.44   0.81  (v1)
  5m p8 0.618/0.755 s5 1:2 retest flow           96   0.805  39.6  1.39    77.3  0.29   1.24
  5m p8 0.55 /0.855 s5 1:2 retest flow           96   1.490  37.5  1.68   143.0  1.39   1.57
  5m p8 0.618/0.786 s5 1:4 retest flow           90   1.220  30.0  1.10   109.8  2.42   0.22
  5m p8 0.618/0.786 s10 1:2.5 retest flow        86   1.072  37.2  1.02    92.2  0.29   1.72
  5m p8 0.618/0.786 s20 1:2 retest flow          85   1.306  44.7  1.07   111.0 -0.61   2.93  halves disagree
  5m p8 0.618/0.786 s10 1:3 retest flow          85   2.006  36.5  1.88   170.5  1.78   2.19
  5m p8 0.618/0.786 s15 1:2.5 retest flow        85   1.565  41.2  1.69   133.0  0.90   2.13
  5m p9 0.618/0.786 s5 1:2 retest flow           77   1.409  42.9  2.71   108.5  2.72   0.37
  5m p8 0.618/0.786 s5 1:2 retest session        75   1.390  42.7  2.03   104.3  1.97   0.91

WHY PIVOT 7 AND NOT ONE OF THE BIGGER MEANS.  Three reasons, in order.

  1  It is the MOST TRADES of any acceptable configuration - 117 against the
     next best 99 - which is what was asked for.
  2  It changes the ONE parameter v2 showed to be genuinely stable.  Pivots 7,
     8 and 9 are all acceptable, and their entry sets overlap the selected one
     by only 0.24-0.50, so they are substantially DIFFERENT trades reaching the
     same conclusion.  That is corroboration.  Every other dial in the grid was
     either an isolated peak (entry level, timeframe) or so highly overlapped
     with the baseline - 0.87 to 0.97 - that its stability was the same
     strategy measured twice.
  3  Both halves are positive (+0.40 / +1.43) and it is better than v1's
     setting on every measure at once: more trades, higher mean, higher
     recovery, and a win rate within noise.

The configurations with bigger means were NOT chosen.  s10/1:3 at +2.006% and
0.55/0.855 at +1.490% sit in parts of the grid v2 showed to be speckled rather
than connected - the stop x target surface has no connected acceptable region
at all, and 0.55 is a corner of the entry x far-edge grid whose own row is
otherwise negative.  Picking the largest number off a noisy surface is the
thing this whole exercise exists to avoid.


WHAT THIS REPORT IS NOT
------------------------
It is NOT an out-of-sample result.  Pivot 7 was chosen by looking at a grid
that included the second half of the sample, so its h1/h2 split is a
description of the data it was selected on, not a test.  Selecting the best of
12 acceptable configurations out of 85 is a selection decision, and the only
thing that can validate it is a window it was never fitted on.

The honest summary of v1 + v2 + v3 together: the rule is not demonstrated.  v2
showed the edge disappears when the entry level moves 0.032 of a leg or the
timeframe moves one step, and neither of those is a parameter you could claim
to know in advance.  This report exists because the user asked to see the best
parameter set run through the full strategy report - it shows what that
configuration did, not that it will do it again.

Run from backend/:
    python scripts/fib_retracement_v3.py --offline

Output: ../reports/fib_retracement_v3_report.html (self-contained, no CDN).
"""
from __future__ import annotations

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, SCRIPT_DIR)

import fib_retracement_v1 as V1  # noqa: E402

# ---------------------------------------------------------------------------
# The v2-selected parameter set, applied as v1's defaults.
# ---------------------------------------------------------------------------
# Everything not listed here is already v1's value and is deliberately left
# alone - this is one change to one parameter, not a re-tune.
V1.PIVOT_LEFT = 7
V1.PIVOT_RIGHT = 7
V1.DEFAULT_TF = 5
V1.DEFAULT_ENTRY = "retest"
V1.DEFAULT_MODE = "flow"
V1.DEFAULT_RR = 2.0
V1.REPORT_HTML = os.path.join(V1.REPORTS_DIR, "fib_retracement_v3_report.html")

# The report is v1's, with its own name on it so the two are never confused.
V1.HTML_TEMPLATE = (V1.HTML_TEMPLATE
    .replace("<title>NIFTY fib retracement __FROM__ to __TO__</title>",
             "<title>NIFTY fib retracement v3 (tuned) __FROM__ to __TO__</title>")
    .replace("<h1>NIFTY fib retracement &mdash; the 0.618&ndash;0.786 zone</h1>",
             "<h1>NIFTY fib retracement v3 &mdash; the 0.618&ndash;0.786 zone, "
             "<span class=\"dim\" style=\"font-size:14px\">pivot 7, the parameter set "
             "v2 selected</span></h1>"))

if __name__ == "__main__":
    V1.main()
