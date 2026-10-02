# Adjudication: mean-reversion and volatility candidates (revvol)

Candidates: `mr_session_mean_band_fade`, `mr_opening_range_failed_breakout`, `mr_prev_day_extreme_sweep`,
`mr_rsi14_exhaustion_recross`, `vol_narrow_ib_extension`, `vol_wide_range_bar_follow`, `vol_lunch_lull_break`.

- Primary: `signals_revvol.py`
- Second coding: `check/alt_revvol.py`
- Comparison tool: `check/diff_revvol.py` (run with `python check/diff_revvol.py`)

Only signals were looked at (day, minute, direction, counts). No P&L, forward move or option price was
computed. Every `Market` was built with the default wall, and the latest index day held was 2026-04-30.

## Result

The two codings agree on every session. No behaviour of the primary was changed.

| Check | Scope | Result |
|---|---|---|
| Registry (centre values, neighbour order, labels, one value moved per neighbour) | 7 candidates, 26 neighbours | 0 problems |
| Primary vs second coding | 33 variants x 2 indexes x 80 sessions = 5,280 comparisons | 5,280 agree, 0 disagree |
| Primary vs a third brute-force reading (the "witness" in `diff_revvol.py`) | the same 5,280 | 0 differences |
| `ctx.check_no_lookahead` on the primary | the same 5,280 | 0 problems |
| Primary on short and early days (first sessions on disk, cuts at 09:14 .. 14:13) | 3,168 calls | 0 exceptions, 0 signals outside 09:19..14:13 or after the cut |

Sessions: 80 per index, 2026-01-01 .. 2026-04-30.

## What differed

Nothing differed on the data. One difference exists in the code and was never exercised.

### `mr_prev_day_extreme_sweep`: both sides sweeping on the same 5-minute candle

- **Primary:** returns the signal with direction DOWN (the up-sweep, the side the text names first).
- **Second coding:** returns no signal for the day.
- **Cause:** the text says "SIGNAL = the earliest such t across both sides" and gives a direction per
  side, so one candle that is the first reclaim of both a PDH breach and a PDL breach has a signal minute
  but two opposite directions. The text has no tie rule.
- **Decision:** keep the primary. The text states that a signal exists at that t, so dropping it is the
  less literal reading. Choosing the direction by the order of the text is a convention, and it is
  recorded as an ambiguity. The choice was made without looking at any outcome.
- **Effect on discovery data:** none. The tie occurred on 0 of 80 sessions on either index for W = 30, 60
  and 120.
- **Second coding:** left as it is (it is the less literal one on this point).

### Differences that cannot bite on this data

Every session on disk has all 375 bars and 27 warm-up sessions precede 2026-01-01, so none of these
changes a signal.

| Situation | Primary | Second coding |
|---|---|---|
| A hole in the first N or M bars | no signal unless all are present | no signal unless the last one is present |
| A hole in the lull window | no signal unless all bars are present | no signal unless the bar at T2-1 is present |
| `vol_wide_range_bar_follow` with fewer than N earlier candles on disk | that candle is skipped | no signal for the day |
| Square root in the band fade | `** 0.5` | `math.sqrt` |

## What changed in the primary

One documentation change, no change of behaviour: the tie entry of `mr_prev_day_extreme_sweep` in
`AMBIGUITIES` now records this adjudication (the second coding's reading, why the primary's is kept, and
that the tie occurred on 0 discovery sessions). Signal counts before and after are identical.

## Line-by-line reading of the primary against the frozen text

All seven read index 1-minute candles only. None uses the weekday, days to expiry, the expiry calendar,
a daily file, the house daily close, India VIX or an option candle, so P1.6, P1.7, P1.8 and both addenda
have nothing to bite on (addendum 1 strikes a candidate outside this group; addendum 2 concerns
`atm_oi_writer_skew`). Common points checked for each: 5-minute candles aligned to 09:15, signal minute =
the candle's last 1-minute bar, signal minutes limited to 09:19..14:13, first signal only.

| Candidate | Checked against the text | Verdict |
|---|---|---|
| `mr_session_mean_band_fade` | Grid 09:19 + 5j; `09:15 + WARM - 1 <= t` (first 09:44 / 09:29 / 10:14 for WARM 30 / 15 / 60); mean and population SD of closes 09:15..t including t; SD = 0 skipped; `C >= M + K SD` gives DOWN, `C <= M - K SD` gives UP | matches |
| `mr_opening_range_failed_breakout` | ORH / ORL from the first N bars; candles starting at or after 09:15+N; breakout strict (`> ORH`, `< ORL`); failure strict and `b < t <= b + W`; only the first breakout per side; up-failure gives DOWN, down-failure gives UP; earliest across sides, then `t <= 14:13` | matches |
| `mr_prev_day_extreme_sweep` | PDH / PDL from all 1-minute bars of the previous session on disk (Sunday 2026-02-01 included); breach strict, searched from 09:15; `b <= t <= b + W`; reclaim strict; up-sweep gives DOWN, down-sweep gives UP; `09:19 <= t <= 14:13` | matches; tie rule is a recorded ambiguity |
| `mr_rsi14_exhaustion_recross` | Today's candles only; changes from the 2nd candle; first averages = simple means of the first P; Wilder smoothing after; RSI = 100 when avgLoss = 0; levels 50 +/- D; DOWN on `RSI < upper` with previous `>= upper`; UP on `RSI > lower` with previous `<= lower`; first RSI at candle P+1 (10:29 for P 14), earliest signal 10:34 | matches |
| `vol_narrow_ib_extension` | IBH / IBL from the first M bars; AVG over the 20 earlier sessions with the same M, today excluded; strict `WIDTH < K x AVG`; candles starting at or after 09:15+M; `close > IBH` gives UP, `close < IBL` gives DOWN | matches |
| `vol_wide_range_bar_follow` | Range = high - low; AVG of the N candles immediately before k, running back into the previous session, k excluded; `09:34 <= m <= 14:13`; `range >= X x AVG`; UP needs close > open and close > midpoint; DOWN the mirror | matches |
| `vol_lunch_lull_break` | Window T1 .. T2-1; LH / LL from highs and lows; candles starting at or after T2 with `m <= 14:13`; `close > LH` gives UP, `close < LL` gives DOWN | matches |

Registry: the centre and neighbour values equal `library.json` for all seven, in library order, lower
neighbour then upper, one value moved per neighbour.

Two ties were proved or counted rather than assumed:
- **Opening-range failed breakout, both sides failing on one candle:** impossible. If the down-breakout
  came after the up-breakout and before t, its close below ORL is already an up-failure earlier than t.
  Counted: 0 days.
- **Previous-day sweep, both sides on one candle:** possible in principle, 0 days in discovery.

## Final signal counts (primary, 80 discovery sessions per index)

Each cell is `signals (UP/DOWN) earliest..latest signal minute`.

| Candidate | Variant | NIFTY | SENSEX |
|---|---|---|---|
| mr_session_mean_band_fade | centre (K 2.0, WARM 30) | 69 (38/31) 09:44..13:34 | 70 (40/30) 09:44..14:09 |
| | K_band_width_sd=1.5 | 80 (46/34) 09:44..12:29 | 80 (45/35) 09:44..13:14 |
| | K_band_width_sd=2.5 | 40 (24/16) 09:44..14:04 | 47 (28/19) 09:44..14:04 |
| | WARM_minutes=15 | 72 (40/32) 09:29..13:34 | 73 (42/31) 09:29..14:09 |
| | WARM_minutes=60 | 58 (33/25) 10:14..14:09 | 60 (37/23) 10:14..14:09 |
| mr_opening_range_failed_breakout | centre (N 15, W 30) | 47 (25/22) 09:39..14:09 | 51 (24/27) 09:39..14:04 |
| | N_opening_range_minutes=5 | 55 (31/24) 09:29..14:09 | 55 (27/28) 09:29..13:19 |
| | N_opening_range_minutes=30 | 52 (31/21) 09:54..14:09 | 50 (27/23) 09:54..14:04 |
| | W_failure_window_minutes=15 | 39 (25/14) 09:39..14:09 | 37 (19/18) 09:39..14:04 |
| | W_failure_window_minutes=60 | 57 (31/26) 09:39..14:09 | 57 (25/32) 09:39..13:54 |
| mr_prev_day_extreme_sweep | centre (W 60) | 40 (19/21) 09:19..13:59 | 39 (19/20) 09:19..14:04 |
| | W_reclaim_window_minutes=30 | 39 (20/19) 09:19..13:59 | 37 (19/18) 09:19..14:04 |
| | W_reclaim_window_minutes=120 | 44 (19/25) 09:19..13:59 | 41 (19/22) 09:19..14:04 |
| mr_rsi14_exhaustion_recross | centre (P 14, D 20) | 46 (26/20) 10:34..14:09 | 45 (26/19) 10:34..14:04 |
| | P_rsi_period=10 | 69 (42/27) 10:14..14:04 | 71 (43/28) 10:14..14:04 |
| | P_rsi_period=20 | 26 (16/10) 11:04..14:04 | 26 (17/9) 11:04..14:04 |
| | D_level_distance_from_50=15 | 69 (41/28) 10:34..14:09 | 68 (38/30) 10:34..14:09 |
| | D_level_distance_from_50=25 | 27 (16/11) 10:34..14:04 | 29 (18/11) 10:34..14:04 |
| vol_narrow_ib_extension | centre (M 60, K 1.0) | 35 (21/14) 10:19..14:09 | 37 (21/16) 10:19..13:54 |
| | M_initial_balance_minutes=45 | 45 (25/20) 10:04..14:09 | 43 (26/17) 10:04..13:54 |
| | M_initial_balance_minutes=75 | 29 (14/15) 10:34..14:09 | 33 (17/16) 10:34..13:59 |
| | K_width_vs_20_session_average=0.9 | 25 (13/12) 10:19..14:04 | 31 (17/14) 10:19..13:54 |
| | K_width_vs_20_session_average=1.1 | 41 (25/16) 10:19..14:09 | 47 (26/21) 10:19..13:54 |
| vol_wide_range_bar_follow | centre (X 2.0, N 20) | 55 (35/20) 09:34..14:09 | 52 (29/23) 09:34..14:09 |
| | X_range_multiple=1.5 | 80 (37/43) 09:34..13:39 | 80 (37/43) 09:34..13:14 |
| | X_range_multiple=2.5 | 24 (11/13) 09:34..14:04 | 23 (11/12) 09:34..14:04 |
| | N_average_candles=14 | 55 (29/26) 09:34..14:09 | 60 (30/30) 09:34..14:09 |
| | N_average_candles=30 | 57 (33/24) 09:34..14:09 | 56 (33/23) 09:34..14:09 |
| vol_lunch_lull_break | centre (T1 11:30, T2 13:30) | 45 (21/24) 13:34..14:09 | 43 (19/24) 13:34..14:09 |
| | T1_lull_start=11:00 | 43 (20/23) 13:34..14:09 | 40 (18/22) 13:34..14:09 |
| | T1_lull_start=12:00 | 48 (23/25) 13:34..14:09 | 48 (23/25) 13:34..14:09 |
| | T2_lull_end=13:00 | 59 (26/33) 13:04..14:09 | 59 (24/35) 13:04..14:09 |
| | T2_lull_end=14:00 | 17 (6/11) 14:04..14:09 | 18 (6/12) 14:04..14:09 |

These are signal counts before any fill is checked. Variants already under gate P7(a)'s 30 trades on at
least one index: `T2_lull_end=14:00` (17 / 18), `X_range_multiple=2.5` (24 / 23), `P_rsi_period=20`
(26 / 26), `D_level_distance_from_50=25` (27 / 29), `K_width_vs_20_session_average=0.9` (NIFTY 25) and
`M_initial_balance_minutes=75` (NIFTY 29). All seven centres have at least 35 signals per index.
