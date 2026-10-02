# Adjudication: trend group (2026-10-02)

Candidates: `orb15_close_break`, `pdhl_break_5m`, `first_hour_close_location`, `afternoon_new_extreme`,
`ema20_pullback_5m`, `avgprice_cross_hold`.

- PRIMARY: `signals_trend.py`
- SECOND: `check/alt_trend.py`
- Diff script: `check/diff_trend.py` (machine-readable result: `working strategy reports/intraday_entry/check_diff_trend.json`)

## Verdict

**The two codings agree on every session. No signal logic in the primary was changed.**

| Check | Result |
|---|---|
| Sessions compared (24 cells x 2 indexes x 80 sessions, 2026-01-01..2026-04-30) | 3,840 |
| PRIMARY vs SECOND disagreements | 0 |
| PRIMARY vs a third from-the-text coding (in `diff_trend.py`) | 0 differences |
| Parameter cells of both modules vs `library.json` (names, values, labels, order) | 0 problems |
| Structural checks on signal minutes (window, candle alignment, earliest minute) | 0 problems |
| `ctx.check_no_lookahead`, every cell, session and index, final primary | 0 problems |
| Primary on a day cut at 49 different minutes (188,160 calls) | 0 inconsistent, 0 raised |
| Primary on the first three warm-up sessions (incl. 2025-11-24, no previous session) | 0 raised |

The primary author's report said "22 parameter sets"; the real number is 24 (3 + 3 + 5 + 3 + 5 + 5). All 24 were checked.

## What differed

Nothing in the outputs. The two modules differ only in style:

- **Bar addressing.** The primary works by minute stamp and tolerates gaps; the second requires bars contiguous from 09:15 and returns None otherwise. Every session on disk has 375 bars, so this never changes an answer.
- **Incomplete N-minute candles.** The primary skips a candle whose last bar is missing (pdhl) or stops the day (ema); the second only builds whole groups. Same reason, no effect.
- **EMA cache.** The primary recomputes from 2025-11-24 per day; the second resumes from the previous session. Same values.

## Line-by-line reading of the primary against the text

Each function was read against its `signal` text, the library's conventions note and protocol P1.

| Candidate | Points checked | Finding |
|---|---|---|
| `orb15_close_break` | ORH/ORL over 09:15..09:15+N-1; scan from 09:15+N to 14:13; strict `>` / `<` on the 1-minute close; first candle only | matches |
| `pdhl_break_5m` | PDH/PDL from the previous session's 1-minute highs/lows 09:15..15:29 (`prev_sessions[-1]`, not the house close); B-minute candles aligned to 09:15; signal minute = candle's last bar; 09:19 <= m <= 14:13; strict close comparison | matches |
| `first_hour_close_location` | window = first W bars; decision minute 09:15+W-1; `H1 = L1` gives no trade; `p >= 1 - F` UP, `p <= F` DOWN; one evaluation | matches |
| `afternoon_new_extreme` | SH/SL over 09:15..t-1 (candle t excluded, checked before the update); scan S..14:13; strict close comparison | matches |
| `ema20_pullback_5m` | 5-minute candles aligned to 09:15; one series from 2025-11-24, seeded with the first close, no reset; alpha = 2/(P+1); E(k) includes candle k; run strict, touch non-strict, close strict; Q run candles all today's; m <= 14:13 | matches |
| `avgprice_cross_hold` | A(t) includes candle t and all bars from 09:15; side by strict comparison; H sides equal s; side(t-H) != s; t-H >= 09:15+X-1; t <= 14:13 | matches |

Protocol points:

- **P1.2 / P1.3 / P1.4:** signal minute is the last 1-minute bar of the candle; all signals fall in 09:19..14:13; every "14:29" in the text is read as 14:13; first qualifying candle only.
- **P1.6:** no weekday, days-to-expiry, expiry calendar or whole-window statistic is used. The EMA warm-up from 2025-11-24 is allowed.
- **P1.7 / P1.8:** none of the six reads a daily file, VIX or an option candle.
- **House daily close:** none of the six uses a previous close, so it does not apply. PDH/PDL come from 1-minute candles, as the library's conventions say.
- **Addenda 1 and 2:** concern `near_expiry_first_hour_drive` and `atm_oi_writer_skew`; neither touches this group.

No shared misreading was found. The third coding in `diff_trend.py` evaluates each rule minute by minute from scratch, with no running state, and gives the same signals. For `avgprice_cross_hold` it uses Python's compensated `sum()` where the primary uses a plain running total, and the signals are still identical, so the result does not hinge on float rounding of the average.

## What changed in the primary

Documentation only: three readings that the code already applied were added to `AMBIGUITIES`. No function body, parameter or label changed.

- **`pdhl_break_5m`:** with B = 3 the last examined candle is 14:09-14:11; a candle that is not examined (B = 3: 09:15-09:17) does not consume the day.
- **`afternoon_new_extreme`:** the scan has no memory of the morning; a close beyond the session extreme before S is not a signal and does not consume the day.
- **`avgprice_cross_hold`:** "0 if equal" is an exact float comparison; a side of 0 inside the hold run breaks the run.

The second coding was left as it was; it is not wrong anywhere.

## Things a reader should know (not changed, not tuned)

- Signal rates are far above the library's "expected trades per week" for `pdhl_break_5m` (about 66 of 80 sessions against an expected 2.5-3 a week) and `afternoon_new_extreme` (about 60 of 80 against 2.5-3.5). `orb15_close_break` fires on 79 of 80. This is the literal rule; the expectation was the proposer's guess.
- `first_hour_close_location` with F = 0.33 uses the float `1 - 0.33` = 0.6699999999999999 as the UP threshold, with no tolerance.
- No P&L, option candle or forward move was read or computed. The outcome files already in the output folder were not opened.

## Final signal counts (80 sessions per index)

Cells are `signals (UP/DOWN) earliest..latest`.

| Candidate / cell | NIFTY | SENSEX |
|---|---|---|
| **orb15_close_break** centre (15) | 79 (38/41) 09:30..14:08 | 79 (40/39) 09:30..14:03 |
| opening_range_minutes=10 | 80 (36/44) 09:25..13:42 | 80 (40/40) 09:25..14:03 |
| opening_range_minutes=30 | 76 (36/40) 09:45..14:08 | 75 (35/40) 09:45..14:03 |
| **pdhl_break_5m** centre (5) | 67 (32/35) 09:19..13:34 | 66 (30/36) 09:19..13:34 |
| confirmation_candle_minutes=3 | 67 (32/35) 09:20..13:32 | 67 (31/36) 09:20..13:32 |
| confirmation_candle_minutes=15 | 64 (28/36) 09:29..13:44 | 65 (28/37) 09:29..13:44 |
| **first_hour_close_location** centre (60, 0.25) | 50 (24/26) 10:14 | 51 (27/24) 10:14 |
| window_minutes=45 | 53 (24/29) 09:59 | 51 (24/27) 09:59 |
| window_minutes=90 | 47 (22/25) 10:44 | 46 (21/25) 10:44 |
| outer_fraction_of_range=0.20 | 44 (20/24) 10:14 | 42 (22/20) 10:14 |
| outer_fraction_of_range=0.33 | 63 (30/33) 10:14 | 63 (32/31) 10:14 |
| **afternoon_new_extreme** centre (12:00) | 62 (28/34) 12:00..14:11 | 60 (27/33) 12:00..14:09 |
| scan_start_time=11:30 | 65 (29/36) 11:30..14:11 | 64 (29/35) 11:30..14:09 |
| scan_start_time=12:30 | 56 (25/31) 12:30..14:11 | 52 (24/28) 12:30..14:09 |
| **ema20_pullback_5m** centre (20, 6) | 61 (27/34) 09:54..14:04 | 57 (26/31) 10:14..14:04 |
| ema_period=10 | 65 (35/30) 09:49..14:04 | 59 (28/31) 09:49..14:09 |
| ema_period=30 | 55 (24/31) 09:54..14:04 | 50 (21/29) 09:54..14:09 |
| clean_run_candles=4 | 65 (28/37) 09:44..14:04 | 65 (30/35) 09:39..14:04 |
| clean_run_candles=8 | 55 (26/29) 09:59..14:04 | 51 (22/29) 10:14..14:04 |
| **avgprice_cross_hold** centre (15, 60) | 72 (37/35) 10:30..14:13 | 70 (35/35) 10:31..13:58 |
| hold_minutes=10 | 72 (40/32) 10:25..14:08 | 71 (37/34) 10:24..14:11 |
| hold_minutes=30 | 69 (35/34) 10:45..14:13 | 70 (35/35) 10:46..14:13 |
| exclude_first_minutes=45 | 74 (38/36) 10:14..14:13 | 73 (34/39) 10:14..13:58 |
| exclude_first_minutes=90 | 67 (35/32) 11:00..14:13 | 66 (32/34) 10:59..13:58 |
