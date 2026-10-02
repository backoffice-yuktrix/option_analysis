# Intraday entry search - the rules of the test (protocol v2, frozen 2026-10-02)

Written and frozen BEFORE any candidate was scored. Version 1 was attacked by two independent
reviewers (statistics, execution); every accepted fix is folded in below. Nothing here may be
changed after the first scoring run. Where this file and `library.json` disagree, this file wins.

Goal: find ONE entry model (a rule saying, on a given day, at which minute to buy a CE or a PE)
for same-day trades in NIFTY / SENSEX options, without overfitting. "No entry survives" is an
allowed answer and is reported as "not detectable with about 80 sessions", not as "no edge exists".

## P1. What an entry is
1. An entry is a function of candles COMPLETED at or before minute t (and of earlier days). It gives
   at most ONE signal per day per index: (signal minute t, direction UP = buy CE / DOWN = buy PE).
2. Candle stamps are candle STARTS. A 1-minute candle stamped t is complete at t+1 and is acted on
   in the 1-minute bar stamped t+1 (the fill bar). An N-minute candle starting at s (aligned to
   09:15) is complete at s+N; its signal minute t is its last 1-minute bar (s+N-1).
3. Fill bars allowed: 09:20 .. 14:14, so signal minutes are 09:19 .. 14:13. These bounds are fixed
   and are not candidate parameters. Wherever `library.json` says a signal may fall up to 14:29,
   read 14:13.
4. The rule is evaluated only on candles whose fill bar lies in that window. The day's signal is the
   FIRST such candle on which the rule is true. If that signal's outcome row is not OK (P3) there is
   no trade that day for that index; later signals of the same day are ignored.
5. NIFTY and SENSEX are two separate books of 1 lot each, each read from its own index candles.
6. Inputs a candidate may NOT use: the weekday, days-to-expiry or the expiry calendar; any
   statistic computed over the trading window as a whole (every average, percentile or scale uses
   only bars completed at or before t; warm-up from 2025-11-24 is allowed).
7. Daily files (Asian indices, S&P 500, India VIX daily): only rows dated strictly before today
   (S&P 500: the row of the previous US session, which is dated before today). Today's high, low and
   close of any daily series are forbidden. Intraday India VIX only from completed 1-minute VIX
   candles stamped at or before t. No option price or India VIX value from bars stamped before 09:20.
8. A candidate that uses option candles may read only contracts of the P2 expiry at strikes within
   +-5 strike steps of the at-the-money strike at minute t; it may never iterate over the files that
   happen to exist. Volume of a bar is usable once the bar is complete; open interest with a lag of
   3 completed minutes. A needed strike with no file or no bar makes that minute "no signal".

## P2. The trade - identical for every candidate
1. Expiry = the first date in the index's own expiry file at least 1 calendar day after the trade
   day (`next_expiry(expiries, day, 1)`), weekly or monthly; never today's expiry.
2. Strike = `atm_strike(C, step)`, C = the index CLOSE of the 1-minute candle stamped t (the bar
   immediately before the fill bar). It is not re-chosen from the fill bar.
3. Quantity = 1 lot = `lot_size` of the resolved contract. Costs = `option_round_trip("LONG", buy,
   sell, lot, day=<trade day>, exchange="NSE" for NIFTY / "BSE" for SENSEX)`, both passed explicitly.
4. Option candles are read with volume. A bar with volume 0 is NOT a tradable bar.
   ENTRY: the option bar stamped t+1 must exist and have volume > 0; the buy fills at its HIGH.
   Otherwise the row is NO_FILL (or NO_DATA when the contract, its candles for the day, or the bar is
   missing). No retry at a later minute.
   EXIT: a scheduled or stop exit fills at the LOW of the first bar at or after the scheduled minute
   that has volume > 0, up to and including 15:29; if none, the row is NO_EXIT.
5. Three exits, none tuned:
   - EOD: scheduled minute 15:14.
   - H60: scheduled minute = the bar stamped exactly 60 minutes after the entry bar.
   - STOP30: stop level = 0.70 x the buy fill price. Starting with the entry bar itself and ending
     with the 15:12 bar, the first bar with volume > 0 whose CLOSE is at or below the level is the
     trigger; the sale fills at the LOW of the next bar with volume > 0, whatever that low is (never
     capped at the level). No trigger by 15:12: sell as EOD. Close-based only; `scan_exit`'s
     touch-based stop is not used.
6. THE HEADLINE: exit EOD, contract ATM. These are what the final model trades and what every rupee
   figure in a summary refers to. H60 and STOP30 exist only to make the score robust to the exit.
7. Known tilt, accepted and disclosed: buying at the next bar's HIGH costs trend entries more than
   fade entries.

## P3. Outcome tables
1. A row is keyed (index, day, fill-bar stamp, direction) and has a status: OK, NO_DATA, NO_FILL,
   NO_EXIT (per exit). Only OK rows carry a result. Nothing is imputed, interpolated or taken from a
   neighbouring minute, strike or expiry. Exact-minute lookups only (`bar_at` with a tolerance is
   forbidden here).
2. Each OK row stores: lot, DTE, strike, expiry, buy price, and per exit: exit stamp, sell price,
   gross, costs, net rupees, net as % of premium paid (net / (buy x lot)), index points move in the
   trade's direction.
3. Two tables, two steps. Step A builds the DISCOVERY table only and never opens a candle dated
   after 2026-04-30; candidate signals are generated for discovery days only. Step B (holdout) is
   refused by the code unless `freeze.json` exists (winner id, its parameters, SHA-256 of
   `protocol.md`, `library.json` and every .py file of the study, timestamp) and the hashes still
   match; it computes rows only for the winner's own signals and for the holdout null (P10).
4. The share of non-OK rows is printed per index before any candidate is scored.

## P4. Sessions and the split
1. Trading window 2026-01-01 .. 2026-07-31. DISCOVERY = sessions dated <= 2026-04-30;
   HOLDOUT = sessions dated >= 2026-05-01.
2. A session is included only if the index has 1-minute bars at 09:15 and 15:14 and at least 350
   bars. The session list is printed and saved before any outcome is computed. No day is removed
   afterwards for any reason.
3. Everything is chosen on DISCOVERY. One shot: no second pick after a failed holdout. Any code
   change after the first scoring run is logged with its reason in `run_log.json` and triggers a
   full discovery re-run; no change at all once the holdout has been opened. Any later run is
   labelled POST-HOLDOUT, EXPLORATORY.

## P5. The candidate library
1. `library.json` is the exact list: 28 centre candidates, written by proposers who were not allowed
   to see any price, result or report. Each has at most 2 varied parameters; the centre and one
   neighbour on each side are written in the file.
2. Neighbours are moved ONE AT A TIME (at most 4 per candidate). They can never be selected and are
   not part of the P8 family; they exist only for gate P7(c).
3. The 10 candidates with family `existing_repo` were built earlier on this same window (their
   centres were partly fitted on it, including on the holdout months). They are flagged PREVIOUSLY
   SEEN ON THIS DATA; if one wins, its holdout verdict is labelled NOT INDEPENDENT.

## P6. The score S (computed on DISCOVERY)
1. t = mean / (sample sd / sqrt(n)) of per-trade net rupees over OK trades; t = 0 if n < 20 or sd = 0.
2. For each index: t under each of the 3 exits, then the MEDIAN of the three.
   S = the SMALLER of the NIFTY and SENSEX medians.
3. Beside S the same statistic on net % of premium (S_pct) is printed; it is not used to rank.
4. The report prints how many trades had identical EOD and STOP30 results.

## P7. Gates on DISCOVERY - all must pass
"Combined" = per session date, NIFTY net + SENSEX net (EOD exit, ATM). The unit of evidence is the
session date: NIFTY and SENSEX are one bet taken twice and their agreement is never cited as
confirmation.
- (a) at least 30 OK trades per index, and at most 5% of its signals unpriced on either index.
- (b) combined net > 0 in at least 3 of the 4 discovery months (Jan, Feb, Mar, Apr), and no single
  month supplies more than 70% of the total combined net.
- (c) every neighbour has combined net > 0 and S >= 0.
- (d) combined net stays > 0 after removing the single best DATE. (The share of net from the best 3
  dates is reported, not gated.)
- (e) adjusted p <= 0.25 (P8).
- (f) total net % of premium (EOD) > 0 on both indices.

## P8. The shuffle test (max-statistic, for having tried 28 entries)
1. Weeks are ISO weeks; a session's slot is (week, weekday). Signals keep their weekday in every
   null so each candidate keeps its days-to-expiry mix, its trade count, its time-of-day habit and
   its CE/PE mix. An entry that only profits because the market fell while it mostly bought PEs does
   not beat this null.
2. Null A, week-block permutation, 2,000 draws, seed 20261002: the discovery weeks are permuted; the
   signal (minute, direction) of the session at (week w, weekday j) is applied to the session at
   (week pi(w), weekday j) - the same permutation for every candidate and both indices. If that
   session does not exist or the row is not OK, the signal is dropped for that draw.
3. Null B, circular week shift, enumerated exactly: for k = 1 .. W-1, week w -> week (w + k) mod W.
4. In each draw S is recomputed for every one of the 28 centre candidates (including those failing
   other gates) exactly as in P6, and the MAXIMUM over candidates is recorded.
   Adjusted p of a candidate = (1 + number of draws whose maximum >= its real S) / (1 + draws).
   The gate uses the LARGER of the two p values. A within-weekday uniform day permutation (2,000
   draws) is reported for reference only.
5. Before any candidate's score is printed, the run prints the 75th percentile of the null maximum
   and what rupee edge per trade a 50-trade candidate would need to reach it.

## P9. The winner
Winner = the highest S among candidates passing every gate; ties go to the earlier library entry.
If none passes: the holdout is NOT opened; near-misses are listed under NOT VALIDATED - DO NOT
TRADE with the gate each failed; no gate is loosened. Any later protocol on the same discovery data
must keep all 28 candidates in its family.

## P10. Holdout verdict (single hypothesis, fixed now)
1. On HOLDOUT the frozen entry's S is computed as in P6 with a minimum n of 10 (instead of 20).
2. Its one-sided p comes from the same two nulls applied to holdout weeks only (single candidate;
   p = (1 + draws with null S >= real S) / (1 + draws); the larger p is used).
3. CONFIRMED if p <= 0.20 and combined EOD net > 0. WEAK if combined net > 0 but p > 0.20.
   NOT CONFIRMED otherwise.
4. Error budget, printed in the report: discovery 0.25 x holdout 0.20 = about 5% chance that a
   worthless library produces a CONFIRMED entry.
5. Reported beside the verdict: holdout trades, mean net per trade, a 90% week-block bootstrap
   interval for the mean combined net per date (2,000 resamples, seed 20261002), the null mean, rupees
   and % of premium per index, and the sentence "the holdout mean is the only unbiased estimate of the
   edge; the discovery figure is inflated by selection".

## P11. Shown for the winner only - DESCRIPTIVE, NOT SELECTED, NOT VALIDATED
Other strike depths (2 / 4 / 6 NIFTY strikes in the money), entry at the next bar's OPEN, index
points, by month, weekday, DTE (1, 2, 3, 4+) and without 1-DTE trades, CE vs PE, entry hour, without
the best and worst 5 dates. No exit, depth, weekday, hour or CE/PE filter from these tables may be
added to the model without a new pre-registration on new data.

## Addendum 1 (2026-10-02, before any code was written or any candidate scored)
Checking `library.json` against P1: `near_expiry_first_hour_drive` conditions on days-to-expiry,
which P1.6 forbids. It is struck from the library. The family for P8 is therefore 27 centre
candidates; read "27" wherever this file says "28".

## Addendum 2 (2026-10-02, before any code was written or any candidate scored)
`atm_oi_writer_skew` as written reads option open interest at the 09:15 candle and at minute T
with no lag. To meet P1.7 and P1.8: its baseline is the 09:20 candle (not 09:15), the strike K0 is
still taken from the index 09:15 close, and the later reading is the candle stamped T-3 (3 completed
minutes of lag) with the signal still at T. "Latest candle at or before m" lookups stay as written
but may not reach back before 09:20.
