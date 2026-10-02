# Adjudication - context group (`signals_ctx.py` vs `check/alt_ctx.py`)

Date 2026-10-02. Candidates: `vol_vix_confirmed_or_break`, `gap_fail_through_pc`, `spx_cue_confirmed`,
`atm_oi_writer_skew`. Only signals were looked at (day, minute, direction, counts). No option price,
forward move, profit or loss was computed or read, and no candle after 2026-04-30 was loaded
(`Market(index)` with the default wall; the latest date held in any store was 2026-04-30).
The files in the output folder (`outcome_discovery.*`) were not opened.

## Result

- **The two codings agree on every session.** 14 variants (4 centres + 10 neighbours) x 80 discovery
  sessions x 2 indexes = 2,240 comparisons, 0 disagreements (`check/diff_ctx.py`).
- **Look-ahead check on the final primary:** 0 problems, 0 exceptions over the same 2,240 cells.
- **Structure check:** every signal minute is one the text allows for its variant, and lies in
  09:19..14:13.
- **One change was made to the primary**, in a branch that is never reached on disk (below). Signal
  counts are unchanged.
- The second coding is not wrong anywhere I could find; nothing in it was left wrong.

## What differed

Nothing on the data. Reading the two files side by side showed one latent difference in code:

| Where | Primary (before) | Second | Text | Decision |
|---|---|---|---|---|
| `vol_vix_confirmed_or_break`, `VIX_PREV` fallback when the previous session has no VIX candle 15:00..15:29 | the last VIX close of that session, whatever its stamp | the last VIX close of that session stamped 09:20 or later; none means no signal | Library: "the last VIX close of that session". Protocol P1.7: "No option price or India VIX value from bars stamped before 09:20", with no "today only" qualifier. The protocol overrides the library. | The second coding matches the protocol. **Primary changed** to the same rule and the choice recorded in its `AMBIGUITIES`. |

The branch is unreachable on disk: every VIX session from 2025-11-24 to 2026-04-30 has 375 candles
and all 30 candles 15:00..15:29, so the fallback never fires and no signal moved.

Other differences are cosmetic and cannot change an output: the primary also catches `KeyError` from
`house_close`; the order of two `return None` guards in `atm_oi_writer_skew`; how the half-way tie is
written (`<=` on distances vs `> step/2`).

## What changed in the primary (`signals_ctx.py`)

1. `vol_vix_confirmed_or_break`: the `VIX_PREV` fallback now ignores VIX candles stamped before 09:20
   and returns no signal if none is left.
2. `AMBIGUITIES` gained four entries: that fallback; strict comparisons in the VIX rule; that the
   P1.8 band uses P1's signal minute and its consequence on SENSEX; the listed-strike check.

No number, inequality, window or alignment in the four functions was altered.

## Line-by-line review of the primary against the frozen text

**`vol_vix_confirmed_or_break`** - correct.
- ORH / ORL from the candles stamped 09:15..09:15+R-1 (all R must exist).
- `VIX_PREV` = mean of (h+l+c)/3 over the previous session's VIX candles 15:00..15:29; "previous
  session" is the previous date in the index file.
- `VIX_OR` = VIX close at the last opening-range minute, else the latest earlier one, never before 09:20.
- Scan t = 09:15+R .. 14:13; `VIX_t` = close at t or the latest at or before t (from 09:20).
- Gate `VIX_t > VIX_PREV and VIX_t > VIX_OR`, then close(t) `> ORH` UP / `< ORL` DOWN, all strict;
  returns at the first such minute.
- Spot check on three days per index: the printed ORH, ORL, VIX_PREV, VIX_OR, VIX_t and close(t)
  satisfy the rule, and a brute-force scan found no earlier qualifying minute.

**`gap_fail_through_pc`** - correct.
- PC = `ctx.house_close(previous session)`; O = open of the 09:15 candle; G = O - PC, `G == 0` no trade.
- B-minute candles aligned to 09:15; a candle's close is the close of its last 1-minute bar, which is
  the signal minute.
- Candles examined: last minute in 09:19..14:13. B=5: 09:19..14:09. B=15: 09:29..13:59. B=30: 09:44..13:44.
- `G > 0 and close < PC` DOWN; `G < 0 and close > PC` UP; strict; first such candle.
- Protocol consequence, not a choice: for B=15 and B=30 the candle ending 14:14 misses the window by
  one minute.

**`spx_cue_confirmed`** - correct.
- Cue row = last GSPC row dated strictly before today; usable when its date >= the previous Indian
  session date.
- R = cue close / close of the row immediately before it - 1; `R == 0` or fewer than two rows: no trade.
- O = open of 09:15; C = close of the candle stamped 09:15+N-1 (09:24 / 09:29 / 09:44), which is the
  signal minute. `R > 0 and C > O` UP; `R < 0 and C < O` DOWN.
- The four unusable days are the same on both indexes: 2026-01-02, 2026-01-20, 2026-02-02, 2026-02-17
  (a US holiday, or the Sunday session, sits between the cue row and today). No GSPC row was dropped
  for a null price.

**`atm_oi_writer_skew`** - correct, with Addendum 2 applied.
- T = 09:15+V-1 (09:44 / 10:14 / 10:44) is the signal minute.
- K0 = nearest multiple of the step to the 09:15 close, tie to the lower strike; S = K0 +- j x step, j <= J.
- Baseline = the option candle stamped exactly 09:20; later reading = the latest candle stamped
  09:20..T-3; a missing reading or zero open interest in any contract skips the day.
- D = (PE change) - (CE change); `D > 0` UP, `D < 0` DOWN, `D == 0` no trade.
- P1.8: if any strike of S is more than 5 steps from `round(close(T)/step)*step`, no signal and no
  option file is read.
- A third plain reading written inside `diff_ctx.py` reproduces the primary on all 800 cells.

## Shared readings (both coders made the same choice) - checked against the text

| Reading | Verdict |
|---|---|
| "Listed strike" taken as a multiple of the step, because `DayCtx` does not expose the contract list | Checked against the contract list: on all 80 days of both indexes the nearest listed strike is the nearest multiple of the step, the listed strikes 1 and 2 away are K0 +- j x step, every strike of S is listed, and no 09:15 close is exactly half-way. The two readings are identical on this data. |
| P1.8 band checked once, at the signal minute T | "Minute t" is P1's signal minute throughout the protocol; this is the literal reading. Kept. |
| Baseline must be the 09:20 candle itself | Addendum 2: lookups "may not reach back before 09:20", so "latest at or before 09:20" can only be that candle. Literal. |
| P1.7 applied to every same-day VIX lookup | Protocol overrides the library's "latest VIX close earlier today". Literal. |
| No candle "consumes the day" in `gap_fail_through_pc` | The text has no such wording. Literal. |

## Things the scoring stage should know (none is a coding error)

- **`atm_oi_writer_skew` on SENSEX is thinned by the P1.8 band.** Days with no signal because the
  index moved more than (5 - J) steps from K0 by T: 5 at the centre, 3 at V=30, 8 at V=90, 20 at J=2
  (58 signals left). The J=2 neighbour is therefore scored on a subset of quieter mornings. NIFTY
  loses no day to the band.
- **Days skipped for data reasons** (centre): NIFTY 2026-02-03 and 2026-03-30, SENSEX 2026-03-19 and
  2026-04-02 (a strike of S has no 09:20 candle; the contract's first candle that day is 09:22..09:38);
  SENSEX 2026-03-12 (CE 75900 shows open interest 0 at 09:20).
- **Direction mix:** `vol_vix_confirmed_or_break` is about 78% DOWN on both indexes, as the library
  predicted; the other three are near balanced.
- **`spx_cue_confirmed` at N=10 gives 44 NIFTY signals against 39 at the centre** - a different
  confirmation minute, not a superset.

## Final signal counts of the primary (80 discovery sessions per index)

| Candidate | Variant | NIFTY n (UP / DOWN) | NIFTY minutes | SENSEX n (UP / DOWN) | SENSEX minutes |
|---|---|---|---|---|---|
| `vol_vix_confirmed_or_break` | centre (R=15) | 45 (10 / 35) | 09:30..14:09 | 44 (10 / 34) | 09:30..14:03 |
| | `R_opening_range_minutes=10` | 45 (6 / 39) | 09:25..13:57 | 46 (10 / 36) | 09:25..14:03 |
| | `R_opening_range_minutes=30` | 43 (10 / 33) | 09:45..14:08 | 41 (9 / 32) | 09:45..14:03 |
| `gap_fail_through_pc` | centre (B=15) | 29 (14 / 15) | 09:29..12:59 | 31 (16 / 15) | 09:29..13:29 |
| | `bar_minutes=5` | 31 (16 / 15) | 09:19..12:34 | 32 (16 / 16) | 09:19..13:29 |
| | `bar_minutes=30` | 28 (13 / 15) | 09:44..13:44 | 28 (14 / 14) | 09:44..13:44 |
| `spx_cue_confirmed` | centre (N=15) | 39 (19 / 20) | 09:29 | 37 (19 / 18) | 09:29 |
| | `confirm_minutes=10` | 44 (20 / 24) | 09:24 | 37 (18 / 19) | 09:24 |
| | `confirm_minutes=30` | 38 (18 / 20) | 09:44 | 36 (18 / 18) | 09:44 |
| `atm_oi_writer_skew` | centre (V=60, J=1) | 78 (42 / 36) | 10:14 | 72 (42 / 30) | 10:14 |
| | `eval_minutes=30` | 78 (35 / 43) | 09:44 | 74 (41 / 33) | 09:44 |
| | `eval_minutes=90` | 78 (41 / 37) | 10:44 | 69 (39 / 30) | 10:44 |
| | `strikes_each_side=0` | 80 (43 / 37) | 10:14 | 79 (43 / 36) | 10:14 |
| | `strikes_each_side=2` | 78 (40 / 38) | 10:14 | 58 (32 / 26) | 10:14 |

## Files

- `D:/YUKTRIX/option_analysis/analysis/scripts/index_options/intraday_entry/signals_ctx.py` - primary (changed as above)
- `D:/YUKTRIX/option_analysis/analysis/scripts/index_options/intraday_entry/check/alt_ctx.py` - second coding (unchanged)
- `D:/YUKTRIX/option_analysis/analysis/scripts/index_options/intraday_entry/check/diff_ctx.py` - the comparison, look-ahead, structure and listed-strike checks; exits 0 when all are clean
