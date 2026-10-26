# Approach steps

What the framework does on every run, phase by phase. Indicators and their settings are in `Indicator.md`; what a run finds goes to `Indicator_Results.md`.

---

## Instructions

These hold for every run and every phase.

1. **Run the phases in order** and the steps inside each phase in order. Do not skip a step or start the next phase before the current one has produced its output.
2. **Ask, do not assume.** Every item marked *asked* is put to the user at the start of the run, all in one message, each with its default or recommended value so the user can answer "default". Nothing is calculated until the answers are in.
3. **Calculations start from raw candles; learning carries over.**
   - Every calculation (rolling candles, indicator values, hills, valleys, zones, pattern measurements) is rebuilt from the raw candle files in `candle_datas/` on every run. No calculated value from an earlier run is reused.
   - What earlier runs *learned* is used: `Indicator_Results.md` (what worked better, what did not) and `existing_condition.md` (the best condition so far, in plain words). A run reads both before it starts.
   - `existing_condition.md` lives in `analysis_rajkumarn/`, outside the run folders. A run proposes to keep, merge or replace it (Phase 8); it changes only when the user accepts.
4. **Each run has its own folder**, `backtests/<run ID>/`, holding all its outputs and these two logs:
   - `WorkLog.md`: what the run did, step by step.
   - `LLMDecisions.md`: every decision Claude makes in the LLM step (Phase 6), with the reason, for the user to review.
5. **Log after each step.** Every step below ends with a **Log** line saying what to record. After finishing the step, append it to the run's `WorkLog.md`:
   - the timestamp in IST with milliseconds, read from the system clock and never estimated (for example `2026-10-19 21:30:05.123`), and the step number;
   - what was done, with the numbers that came out of it;
   - anything skipped, dropped, flagged or failed, with the reason;
   - every answer the user gave and every value used.

   Entries are only appended, never edited. A step whose Log line says "nothing" writes nothing.
6. **Stop on a failed check.** When a check fails (missing data, too little history, a test that does not pass), stop, log it, and tell the user what failed. Do not work around it. Once the cause is fixed, start a **new run**; the stopped run's folder stays as the record.
7. **Train before validation.** Train and validation are always continuous: validation starts with the session right after the last train session. Indicators are computed in one pass from the warm-up start to the validation end. Phases 1-3 prepare the validation range like the train range (candles, events, zones, indicators), but no pattern is measured on it until Phase 7; before then, only counts are logged for it. Patterns are found and frozen on train; validation is measured once, after freezing. Data after the validation end is never read; the user's untouched test stays with the user.
8. **Same inputs, same result.** A run with the same inputs, `Approach_Steps.md` and `Indicator.md` gives the same result (any random choice uses a fixed seed). A different result is expected only when one of those two files has changed.
9. **Results.** At the end of the run, its findings go to `Indicator_Results.md` under a heading with the run ID.
10. **Method changes happen here, between runs.** A change to a fixed value (0.6) or to how a phase works is made in this file before a run, never during one.
11. **Each phase feeds the next.** Every phase states its **Input** and its **Output**, and a phase's output is exactly the next phase's input. Phase 0 has no input; its output is the input of Phase 1.
12. **A candle is named by its last minute.** Every candle of more than one minute is written with the time of its last minute: the 5-minute candle 11:23 .. 11:27 is the 11:27 candle; the 13-minute block 09:15 .. 09:27 is the 09:27 candle. TradingView names a candle by its first minute, so the same candle shows there at 11:23 or 09:15.
13. **Code has no comments.** The documents carry the explanation.

---

## Phase 0: Inputs

**Goal:** settle everything a run needs before any calculation, so that the run can be repeated exactly.

**Input:** none.

**Output:** `backtests/<run ID>/run_inputs.md` (every answer, in plain words) and the run summary of 0.8. This is the input of Phase 1.

### Sample input
None: Phase 0 starts from the user's answers to the questions of 0.1-0.5.

### 0.0 Ask, then start the run
- Read `Indicator.md`, `Indicator_Results.md` and `existing_condition.md` (Instruction 3).
- Put every *asked* item of 0.1-0.5 to the user in one message, each with its default or recommended value.
- When the answers are in, create the run ID: date-time and instrument, for example `2026-10-19_2130_NIFTY`.
- Create `backtests/<run ID>/` with an empty `WorkLog.md`.
- **Log:** run ID, start time, the existing condition read (or "none").

### 0.1 Instrument (asked)
- The user names the instrument, for example `NIFTY`.
- Candles come from `candle_datas/<INSTRUMENT>_candles.json` (1-minute OHLCV).
- If the file is missing or does not cover the dates asked for, the run stops and says what is missing. More data is fetched only with the user's approval, following `fetch.md`.
- On disk on 2026-10-19: NIFTY 2025-10-01 .. 2026-07-31, SENSEX 2025-12-12 .. 2026-07-31.
- Whether the file has volume: if every minute's volume is 0, the instrument has **no volume** (0.3 and 1.2 use this).
- **Log:** instrument, candle file, first and last date in it, number of 1-minute candles, volume or no volume.

### 0.2 Train and validation ranges (asked)
- The user gives `train from`, `train to` and `validation to`.
- Validation starts with the session right after `train to` (Instruction 7), so there is never a gap or an overlap.
- **Log:** the three dates as given; the first validation session.

### 0.3 Indicators and their versions (asked)
- The run reads the list in `Indicator.md` (section 1, Summary), shows it with each indicator's versions (for example Range Filter v1), and asks which indicators to run and which version of each: all of them or a chosen subset.
- Each indicator is computed with the parameter values of the chosen version, as written in `Indicator.md`.
- An indicator that needs volume is offered only when the instrument has volume; for an instrument without it (every minute 0), it is shown as not available. `Indicator.md` says for each indicator whether it needs volume.
- **Log:** each indicator chosen, its version and its parameter values.

### 0.4 Hill and valley detection settings (asked)
Hills and valleys are found in Phase 2 by a zigzag on fixed blocks of N minutes: a valley is confirmed when price rises from the swing's lowest low by `ATR multiplier x ATR`, and a hill is the mirror; each pivot is then pinned to its 1-minute low or high. The settings are run inputs:

| Input | Meaning | Default | Allowed |
|---|---|---|---|
| ATR length | how many blocks the ATR averages over | 14 | any whole number |
| ATR timeframe | the block size N, in minutes | 13 minutes | one of the 8 timeframes (1, 2, 3, 5, 8, 13, 21, 34); if the user names another, suggest the nearest of the 8 |
| ATR multiplier | how many ATRs price must reverse to confirm a turn | 2.0 | any positive number |

- The blocks restart at each session's first minute, as on a TradingView chart of that timeframe. For 13 minutes: 09:27 (09:15 .. 09:27), 09:40, ..., 15:18, and a short last block 15:29 (15:19 .. 15:29, 11 minutes). They are not a second kind of candle: Phase 2 takes them from the rolling candles of Phase 1 (2.1).
- The ATR and the zigzag start at the warm-up start (0.5). The ATR needs `ATR length` blocks before it has a value (14 blocks of 13 minutes is about half a session), so the warm-up must hold at least that many; with the default 5 sessions it always does. No separate question.
- This ATR is for finding hills and valleys only; it is never one of the indicators.
- The zone values are fixed, not inputs; they are set in Phase 2 (2.7): band 0.08% of the pivot price; each side looks at most 15 minutes from the pivot and holds when 80% of its O/H/L/C values and 75% of its 2 farthest minutes' values are inside the band; a zone is at least 5 minutes; a move of at least 0.3% must follow by 14:59.
- **Log:** the three values used; the number of blocks the warm-up gives the ATR.

### 0.5 Warm-up for the indicators (asked)
- Indicators with memory need candles before the train start; nothing is analysed in the warm-up.
- **Default: 5 sessions** before the train start.
- For the indicators chosen in 0.3, the run shows what each one needs on each timeframe and recommends a warm-up; **the user decides**:
  - **minimum**: sessions until the indicator gives its first value;
  - **recommended**: sessions until its starting point has faded out, so its values match a long-running TradingView chart.
- An indicator works on chains of N-minute candles, and a session holds only about 375 / N candles of each chain, so the large timeframes need the most sessions. The candles each indicator needs are written in `Indicator.md` under each indicator's **Warm-up**, per version.
- What that means in sessions with the current indicators:

  | Timeframe | 1 | 2 | 3 | 5 | 8 | 13 | 21 | 34 |
  |---|---|---|---|---|---|---|---|---|
  | candles per session per chain | 375 | 187 | 124 | 74 | 46 | 28 | 17 | 10 |
  | Range Filter v1, minimum | 0.4 | 0.8 | 1.2 | 2.0 | 3.2 | 5.3 | 8.8 | 14.8 |
  | Range Filter v1, recommended | 1.2 | 2.4 | 3.6 | 6.0 | 9.7 | 16 | 26 | 44 |
  | HalfTrend v1, minimum | 0.3 | 0.5 | 0.8 | 1.4 | 2.2 | 3.6 | 5.9 | 9.9 |

  So for all 8 timeframes the run would show: minimum 15 sessions (Range Filter on 34m), recommended 44.
- With a warm-up shorter than an indicator's minimum on some timeframe, that indicator is left empty on that timeframe until it has its first value, and the run says from which date it is filled.
- **Log:** minimum and recommended shown, sessions chosen, warm-up date range; every indicator and timeframe left empty at the train start, with the date it is filled from.

### 0.6 Fixed for the market (not asked)
| Item | Value |
|---|---|
| Session | 09:15 .. 15:29, 375 one-minute candles |
| Trade window | first entry 09:30, last new entry 14:45, forced exit 14:59 |
| Timeframes | 1, 2, 3, 5, 8, 13, 21, 34 minutes |
| A minute with invalid OHLC (high below open or close, low above open or close, a price of 0 or less), a negative volume, or a duplicate timestamp | flagged and skipped: the minute is removed |
| A session that is not a normal 09:15 .. 15:29 session of 375 minutes: a special session (for example the Diwali Muhurat session, 13:45 .. 14:44 on 2025-10-21; other years' Muhurat sessions are often in the evening), minutes outside 09:15 .. 15:29, a data gap, or minutes removed by the row above | **kept**: every minute it has is used for the candles, the indicators and the hill/valley zigzag, starting from its own first minute (not 09:15); flagged; **no event, zone or trade comes from that day** |

Changing any row here is a change of method, made in this file between runs (Instruction 10).

- **Log:** nothing (the values are in this file).

### 0.7 Save the inputs
- Write every answer from 0.1-0.5, in plain words, to `backtests/<run ID>/run_inputs.md`, so the run can be repeated exactly.
- **Log:** the file written.

### 0.8 Run summary (the output of Phase 0)
- Instrument; train range; validation range; warm-up range (where the indicators, the hill/valley ATR and the zigzag start).
- Sessions in each range; every flagged minute (invalid OHLC, duplicate) and every session that is not a normal session, with the date and what is different (used for indicators, skipped for events).
- Indicators chosen, with their versions and parameter values; the hill/valley ATR settings.
- The run stops here if a check fails: data missing for a range, or too little history for the warm-up.
- The summary is added at the end of `run_inputs.md`.
- **Log:** the summary; passed, or the check that failed.

### Sample output
`run_inputs.md` for a NIFTY run with the default answers:

```markdown
# Run inputs: 2026-10-20_2130_NIFTY

Existing condition read at the start: none.

## Answers
- Instrument: NIFTY, candles from candle_datas/NIFTY_candles.json.
- Train: 2026-01-01 to 2026-04-30.
- Validation: to 2026-07-31, starting 2026-05-04 (the session right after the train end; 2026-05-01 was a market holiday).
- Indicators: all seven.
  - Range Filter v1: source (O+H+L+C)/4, sampling period 50, multiplier 3.
  - HalfTrend v1: amplitude 2, channel deviation 2, ATR length 100.
  - CLV, Wick ratio, Candle sweep, Zero-lag sweep, Colour / flip / engulf / range break.
- Hill and valley detection: ATR length 14 on 13-minute candles, multiplier 2.0.
- Warm-up: 5 sessions (shown: minimum 15, recommended 44).

## Run summary
- Warm-up: 5 sessions, 2025-12-24 to 2025-12-31 (2025-12-25 was a holiday).
- Train: 80 sessions. Validation: 63 sessions.
- Indicators, hill/valley ATR and zigzag start on 2025-12-24 (145 ATR blocks in the warm-up).
- Volume: none (every minute 0).
- Flagged minutes: none. Sessions that are not normal: none.
- Empty at the train start because the warm-up is shorter than their minimum
  (dates from the warm-up table in 0.5):
  - Range Filter 13m: filled during 2026-01-01.
  - Range Filter 21m: filled during 2026-01-06.
  - Range Filter 34m: filled during 2026-01-14.
  - HalfTrend 21m: filled during 2026-01-01.
  - HalfTrend 34m: filled during 2026-01-07.
- Checks: passed.
```

`WorkLog.md` lines for this phase (format only; the values are what the default answers give):
```
2026-10-20 21:30:05.123  0.0  run 2026-10-20_2130_NIFTY started; read Indicator.md, Indicator_Results.md; existing condition: none
2026-10-20 21:30:05.130  0.1  instrument NIFTY; candle_datas/NIFTY_candles.json 2025-10-01..2026-07-31, 76,560 one-minute candles; no volume
2026-10-20 21:30:05.131  0.2  train 2026-01-01..2026-04-30; validation to 2026-07-31; first validation session 2026-05-04
2026-10-20 21:30:05.133  0.3  indicators: Range Filter v1 (ohlc4, 50, 3), HalfTrend v1 (2, 2, 100), CLV, Wick ratio, Candle sweep, Zero-lag sweep, Colour/flip/engulf/break
2026-10-20 21:30:05.134  0.4  hill/valley ATR: length 14, 13 minutes, multiplier 2.0; warm-up gives 145 blocks (14 needed)
2026-10-20 21:30:05.140  0.5  warm-up shown: minimum 15, recommended 44; chosen 5 sessions, 2025-12-24..2025-12-31; empty at train start: RF 13m/21m/34m, HT 21m/34m (filled by 2026-01-14)
2026-10-20 21:30:05.152  0.7  wrote run_inputs.md
2026-10-20 21:30:05.160  0.8  summary: warm-up 5, train 80, validation 63 sessions; no flagged minutes, no special sessions; checks passed
```

---

## Phase 1: Prepare candles

**Goal:** turn the raw 1-minute candles into one table with a row per minute, holding the rolling candle of every timeframe, ready for the events (Phase 2) and the indicators (Phase 3).

**Input:** the output of Phase 0 (`run_inputs.md`, with its run summary) and the raw candle file it names.

**Output:** `backtests/<run ID>/candles.parquet`: one row per minute from the earliest date needed to the validation end, with the tags of 1.5 and the rolling candles of 1.4. This is the input of Phase 2 (and, through Phase 2's output, of Phase 3).

### Sample input
The raw file, `candle_datas/NIFTY_candles.json`: one row per minute, `[timestamp, open, high, low, close, volume, oi]` (the index has no volume or open interest; both are always 0).
```
["2026-01-05T09:15:00+05:30", 26333.7,  26358.25, 26317.3,  26328.25, 0, 0]
["2026-01-05T09:16:00+05:30", 26327.6,  26327.6,  26306.15, 26319.15, 0, 0]
["2026-01-05T09:17:00+05:30", 26317.85, 26331.0,  26316.35, 26329.8,  0, 0]
["2026-01-05T09:18:00+05:30", 26329.2,  26345.0,  26318.85, 26339.95, 0, 0]
["2026-01-05T09:19:00+05:30", 26339.2,  26348.75, 26330.1,  26340.25, 0, 0]
```

### 1.1 Load
- Read the raw 1-minute candles from the warm-up start to the validation end.
- **Log:** file, date range read, number of candles read.

### 1.2 Check minutes
- Each minute: OHLC valid (high at or above open and close, low at or below them, every price above 0); volume 0 or more; timestamp not a duplicate; timestamps ascending.
- Whether the instrument has volume at all: if every minute's volume is 0 (an index such as NIFTY has none), the run records "no volume", and indicators that need volume are not run (0.3 says which ones need it).
- An invalid or duplicate minute is flagged and removed (0.6).
- A minute outside 09:15 .. 15:29 is flagged and **kept**: its session is a special session (1.3).
- **Log:** each flagged minute with its reason; the number removed.

### 1.3 Check sessions
- Each session is **normal** (09:15 .. 15:29, 375 minutes) or **special** (anything else: other hours, missing minutes, minutes removed in 1.2).
- A special session is kept for candles, indicators and the hill/valley zigzag, from its own first minute, and marked so that no event, zone or trade comes from it (0.6).
- **Log:** each special session: date, first and last minute, number of minutes, what is different.

### 1.4 Rolling candles
- For each minute and each of the 8 timeframes (1, 2, 3, 5, 8, 13, 21, 34): the N-minute candle that ends at that minute. Open = open of its first minute, high = highest high, low = lowest low, close = close of its last minute, **volume = the sum of its minutes' volumes**. Columns `o_5m`, `h_5m`, `l_5m`, `c_5m`, `v_5m` and so on.
- **A candle never spans two days.** In the first minutes of a session it holds only the session's minutes so far, so every timeframe has a value from the session's first minute: at 09:15 all 8 candles equal the 09:15 minute; at 09:17 the 5-minute candle is 09:15 .. 09:17; from 09:19 it is a full 5 minutes. The 34-minute candle is full from 09:48.
- A window with a missing minute is built from the minutes that exist.
- No value is left empty.
- **Log:** candles per timeframe; per timeframe, how many were partial (start of a session or missing minutes).

### 1.5 Mark rows
- Each minute gets three tags:
  - **range**: warm-up, train or validation;
  - **session**: normal or special;
  - **trade window**: whether the minute is inside 09:30 .. 14:59.
- **Log:** rows per range, per session type, and inside the trade window.

### 1.6 Check
- Compare a random sample of minutes (fixed seed) with a direct calculation from the raw minutes, on every timeframe, including minutes at the start of a session.
- If any value differs, the run stops (Instruction 6).
- **Log:** sample size; passed, or the first difference found.

### 1.7 Save
- Write the table to `backtests/<run ID>/candles.parquet` (Parquet: compact, keeps column types, opens with `pandas.read_parquet`).
- **Log:** file written, rows, columns.

### Sample output
`candles.parquet` (NIFTY 2026-01-05; the 8, 13, 21 and 34-minute columns follow the same pattern; every volume column is 0 for NIFTY and is left out here):

| minute | range | session | trade window | 1m O / H / L / C | 2m O / H / L / C | 3m O / H / L / C | 5m O / H / L / C |
|---|---|---|---|---|---|---|---|
| 09:15 | train | normal | no | 26333.70 / 26358.25 / 26317.30 / 26328.25 | same as 1m (09:15 only) | same as 1m (09:15 only) | same as 1m (09:15 only) |
| 09:16 | train | normal | no | 26327.60 / 26327.60 / 26306.15 / 26319.15 | 26333.70 / 26358.25 / 26306.15 / 26319.15 | same as 2m (09:15 .. 09:16) | same as 2m (09:15 .. 09:16) |
| 09:17 | train | normal | no | 26317.85 / 26331.00 / 26316.35 / 26329.80 | 26327.60 / 26331.00 / 26306.15 / 26329.80 | 26333.70 / 26358.25 / 26306.15 / 26329.80 | same as 3m (09:15 .. 09:17) |
| 09:19 | train | normal | no | 26339.20 / 26348.75 / 26330.10 / 26340.25 | 26329.20 / 26348.75 / 26318.85 / 26340.25 | 26317.85 / 26348.75 / 26316.35 / 26340.25 | 26333.70 / 26358.25 / 26306.15 / 26340.25 (first full 5m) |
| 11:27 | train | normal | yes | 26317.65 / 26324.35 / 26313.85 / 26324.10 | 26326.35 / 26327.05 / 26313.85 / 26324.10 | 26320.30 / 26327.30 / 26313.85 / 26324.10 | 26337.85 / 26337.85 / 26313.85 / 26324.10 |

Run summary for the sample inputs:

| | Sessions | Dates |
|---|---|---|
| Warm-up | 5 | 2025-12-24 .. 2025-12-31 (2025-12-25 was a holiday) |
| Train | 80 | 2026-01-01 .. 2026-04-30 |
| Validation | 63 | 2026-05-04 .. 2026-07-31 |
| Rows | 55,500 | all normal sessions; nothing flagged |

`WorkLog.md` lines for this phase (format only; the counts are what the sample inputs give):
```
2026-10-20 21:30:07.412  1.1  read candle_datas/NIFTY_candles.json 2025-12-24..2026-07-31: 55,500 one-minute candles
2026-10-20 21:30:07.598  1.2  minutes checked: 0 invalid OHLC, 0 negative volume, 0 duplicates, 0 outside 09:15..15:29; no volume (every minute 0)
2026-10-20 21:30:07.611  1.3  sessions: 148 normal, 0 special
2026-10-20 21:30:08.204  1.4  rolling candles: 55,500 per timeframe; partial at session start: 2m 148, 3m 296, 5m 592, 8m 1,036, 13m 1,776, 21m 2,960, 34m 4,884
2026-10-20 21:30:08.390  1.5  rows: warm-up 1,875, train 30,000, validation 23,625; inside the trade window 48,840
2026-10-20 21:30:09.015  1.6  check: 500 random minutes x 8 timeframes match a direct calculation: passed
2026-10-20 21:30:09.420  1.7  wrote candles.parquet: 55,500 rows, 44 columns (minute, 3 tags, 8 timeframes x O/H/L/C/V)
```

---

## Phase 2: Find events and zones

**Goal:** find the hills and valleys of the train and validation ranges, pin each one to its 1-minute high or low, and mark the zone around it: the minutes where entering still leaves at least a 0.3% move ahead. This is the answer key every pattern is judged against.

**Input:** the output of Phase 1 (`candles.parquet`) and the hill/valley settings in `run_inputs.md` (0.4).

**Output:** `backtests/<run ID>/events.parquet` (one row per event) and `backtests/<run ID>/candles_events.parquet` (the Phase 1 table with the pivot, zone and entry-minute columns added). This is the input of Phase 3.

### Sample input
The Phase 1 table (`candles.parquet`); see the sample output of Phase 1.

### 2.1 Build the ATR blocks
- Go through the minutes of the Phase 1 table in time order, from the warm-up start to the validation end, over **every** session: normal and special (a special session's blocks start from its own first minute; a session with removed or missing minutes builds its blocks from the minutes it has).
- At every minute that ends a full block (09:15 + k x N - 1; for 13 minutes 09:27, 09:40, ..., 15:18), take that row's rolling N-minute candle (`o_13m`, `h_13m`, `l_13m`, `c_13m`): at those minutes it is exactly the block.
- At the session's last minute, if minutes remain after the last full block, build the short block from those 1-minute rows: open of the first, highest high, lowest low, close of the last (for 13 minutes: 15:19 .. 15:29, named 15:29). The rolling candle at 15:29 cannot be used, because it is a full 15:17 .. 15:29 and overlaps the 15:18 block.
- The block times are the same every day; no block spans two days.

  | Timeframe | Full blocks per day | Short last block |
  |---|---|---|
  | 1, 3, 5 | 375, 125, 75 | none |
  | 2 | 187 | 1 minute |
  | 8 | 46 | 7 minutes |
  | 13 | 28 | 11 minutes |
  | 21 | 17 | 18 minutes |
  | 34 | 11 | 1 minute |

- **Log:** blocks built per range; short blocks; special sessions and the blocks they gave.

### 2.2 ATR on the blocks
- **Formula** (as TradingView's `ta.atr`):
  - true range of a block = the largest of: high - low; |high - previous block's close|; |low - previous block's close|;
  - ATR = Wilder's average of the true range over the last `ATR length` blocks: it starts as the simple average of the first `ATR length` true ranges, then each new block gives `ATR = (previous ATR x (length - 1) + true range) / length`.
- The blocks form one sequence across sessions: yesterday's 15:29 block is followed by today's 09:27 block. The ATR's average carries across days though no block does; the overnight gap enters through the true range of the day's first block, against yesterday's last close.
- **Log:** the first block with an ATR value; the median ATR as % of price in train and in validation.

### 2.3 Zigzag on the blocks
- The zigzag runs **continuously** over the whole block sequence, across sessions and through special sessions; it starts at the first block with an ATR value, in the warm-up. A leg may therefore run overnight.
- **Start:** before the first pivot, track the highest high and the lowest low since the start; the first pivot is whichever of them is reversed by the threshold first.
- A **valley** is confirmed at the first block, **after** the block holding the lowest low since the last hill, whose high is at least `ATR multiplier x ATR` above that lowest low; the valley is the block holding the lowest low (the earliest such block on a tie). A **hill** is the mirror. A block never confirms an extreme it holds itself: the confirmation always comes from a later block.
- The ATR only sets **how far** price must reverse. **Where** the pivot is comes from 2.4, on 1-minute candles.
- **Which ATR:** when a block is checked, the threshold uses the ATR as it stood **before** that block, so a large block does not raise the bar it has to clear itself. Example (price near 100): blocks of about 0.25 range, ATR 0.25; the 11:24 block has a range of 0.60 and would lift the ATR to 0.275; the 11:24 block is checked against 2 x 0.25 = 0.50, not 2 x 0.275 = 0.55.
- **Log:** hills and valleys found per range; the median minutes between a pivot and the block that confirmed it.

### 2.4 Pin each pivot to 1 minute
- Inside the pivot's block, the pivot is the minute with the lowest 1-minute low (valley) or the highest 1-minute high (hill); on a tie, the earliest such minute. The block's low or high is that minute's, so the pin is exact.
- **Competent tag** (informative only): a pivot at or after 11:30, the first minute from which every lag window (34 minutes x 4 positions = 136 minutes) lies inside the same session.
- **Log:** pivots pinned; competent pivots.

### 2.5 Pseudo pivots at 09:30
- At 09:30 every session is inside some leg, and that leg's pivot lies earlier: on the previous day, or 09:15 .. 09:29 of the same day. It cannot be traded from 09:30, so **09:30 becomes a pseudo pivot** of the same kind: a pseudo valley inside an up leg, a pseudo hill inside a down leg. Its price is the 09:30 low (pseudo valley) or high (pseudo hill). It is tagged `pseudo`. So every normal session has one pseudo pivot, unless a real pivot falls exactly on 09:30.
- A pivot of the **same day before 09:30** gets **no zone and no event**, even when price is still near it at 09:30: only the pseudo pivot counts. Example: a valley at 09:22 whose band still holds at 09:34 is ignored; 09:30 becomes the pseudo valley.
- A pivot of the **previous day** keeps its own zone and event on its own day; the pseudo pivot is an extra event for the new day.
- The pseudo pivot's zone (2.7) is built like any other: a before side (minutes before 09:30, which are never entry minutes) and an after side. It is an event only if it reaches the 0.3% move like any other pivot.
- **Log:** pseudo pivots made; same-day pivots before 09:30 set aside for them.

### 2.6 Apply to the original table
- Mark each pinned pivot and each pseudo pivot on its minute in the Phase 1 table: hill or valley, pivot price, pseudo, competent, range (warm-up, train or validation).
- **Log:** pivots written per range.

### 2.7 Zones and events
- Zones are built for the pivots of **train and validation** on **normal sessions** only. A pivot on a special session gets no zone and no event, the same way a leg under 0.3% gets none.
- **Band:** within **0.08%** of the pivot price: valley `low .. low x 1.0008`, hill `high x 0.9992 .. high`.
- **Values counted:** each 1-minute candle gives its open, high, low and close (4 values); 10 minutes give 40 values.
- **Two sides, each on its own:**
  - **before side:** the pivot minute and the minutes before it;
  - **after side:** the pivot minute and the minutes after it.
  - **Each side looks at most 15 minutes away from the pivot.** For a pivot at 10:00, the before side starts as 09:45 .. 10:00 and the after side as 10:00 .. 10:15 (16 minutes each, pivot minute included).
  - **A side holds when both are true:**
    - at least **80%** of all its values are inside the band;
    - at least **75%** of the values of its **2 farthest minutes** are inside the band (6 of 8). The 2 farthest minutes are the last two of the after side, the first two of the before side; for a side of 2 minutes they are the pivot minute and the one beside it.
  - **Shrink from the far end until the side holds:** check the side; if it does not hold, drop its farthest minute and check again (before side: 09:45 .. 10:00, then 09:46 .. 10:00, then 09:47 .. 10:00, ...; after side: 10:00 .. 10:15, then 10:00 .. 10:14, ...). The side is the first, longest window that holds. This keeps the zone's edge near the pivot: a side cannot end on minutes that have left the band.
  - If no window holds, the side is the pivot minute alone; the minimum zone below then fills it in.
  - A side never reaches past the previous or next pivot, nor the session's start or end: the 15 minutes are cut there first.
  - Example (valley at 100.00, band 100.00 .. 100.08, after side of a pivot at 10:00): the pivot minute has 3 of its 4 values inside (its high is outside); 10:01 .. 10:08 are fully inside; 10:09 has 2 of 4 inside; 10:10 .. 10:15 are fully outside.

    | Window | All values inside (80%) | 2 farthest minutes inside (75%) | |
    |---|---|---|---|
    | 10:00 .. 10:15 | 37 of 64, 58% | 10:14, 10:15: 0 of 8 | drop 10:15 |
    | 10:00 .. 10:14 | 37 of 60, 62% | 10:13, 10:14: 0 of 8 | drop 10:14 |
    | 10:00 .. 10:13 | 37 of 56, 66% | 10:12, 10:13: 0 of 8 | drop 10:13 |
    | 10:00 .. 10:12 | 37 of 52, 71% | 10:11, 10:12: 0 of 8 | drop 10:12 |
    | 10:00 .. 10:11 | 37 of 48, 77% | 10:10, 10:11: 0 of 8 | drop 10:11 |
    | 10:00 .. 10:10 | 37 of 44, 84% | 10:09, 10:10: 2 of 8, 25% | drop 10:10 |
    | 10:00 .. 10:09 | 37 of 40, 92% | 10:08, 10:09: 6 of 8, 75% | **holds: the after side is 10:00 .. 10:09** |
- **The zone** = the before side + the after side (the pivot minute is in both and counted once).
- **Minimum zone: 5 minutes** (the pivot minute and 4 more). When the two sides give fewer, minutes are added on the **before** side until the zone has 5:
  - neither side holds: the zone is the pivot minute and the 4 minutes before it (pivot at 10:00: 09:56 .. 10:00);
  - before side 09:58 .. 10:00 (2 minutes before), after side 10:00 .. 10:01 (1 minute after): 4 minutes, so 1 more is added before: 09:57 .. 10:01.
  - Minutes are **never** added on the after side: after the pivot, price may already have left the zone, and a zone stretched there would start the 0.3% move from too late. A pseudo pivot is filled the same way (pseudo pivot at 09:30: 09:26 .. 09:30 at minimum).
  - When the previous pivot or the session start is in the way, the before side fills only up to it, and the zone stays shorter than 5 minutes.
  - Minutes added this way may lie outside the band; the minimum takes priority over the 80% / 75% rule.
- **The 0.3% move:** from the **close of the zone's last minute**, price must reach at least **0.3%** in the leg's direction, measured on the whole of a later 1-minute candle so the turn is definite:
  - after a valley: a later 1-minute **low** at least 0.3% above that close;
  - after a hill: a later 1-minute **high** at least 0.3% below that close;
  - by **14:59** (the forced exit), and before the next pivot.
- **Event:** a pivot whose zone reaches the 0.3% move and has at least one minute between 09:30 and 14:45. Those minutes are the event's **entry minutes**.
- A pivot that is not an event is kept in the log with the reason: special session, 0.3% not reached, zone outside 09:30 .. 14:45.
- **Log:** events per range and type (hill / valley); pivots without an event, by reason; zone length, entry minutes and the best move reached per event (median and range).

### 2.8 Save
- Write `events.parquet` (one row per event: date, type, pivot minute and price, pseudo, competent, range, zone start and end, entry minutes, best move reached from the zone's last close to the leg's end) and `candles_events.parquet`.
- **Log:** files written, rows.

### Sample output
An illustrative session of an instrument trading near 100, with the default settings (ATR 14 on 13-minute blocks, multiplier 2.0). The day before, the last pivot was a hill at 14:10 (100.80); the down leg from it is still running at the open.

**Blocks and pivots (2.1 - 2.4)**

| Block | O | H | L | C | ATR before the block | What happens |
|---|---|---|---|---|---|---|
| 09:27 | 100.25 | 100.32 | 100.05 | 100.20 | 0.24 | down leg from yesterday's hill continues |
| 09:40 | 100.20 | 100.30 | 99.90 | 99.95 | 0.24 | |
| 09:53 | 99.95 | 100.00 | 99.70 | 99.75 | 0.24 | |
| 10:06 | 99.75 | 99.85 | **99.55** | 99.60 | 0.24 | lowest low so far: the valley block (low at the 10:00 minute) |
| 10:19 | 99.60 | 99.98 | 99.66 | 99.95 | 0.24 | needs a high of 99.55 + 2 x 0.24 = 100.03: not yet |
| 10:32 | 99.95 | 100.05 | 99.90 | 100.02 | 0.24 | high 100.05 >= 100.03: **valley confirmed** |
| ... | | | | | | up leg |
| 11:11 | 100.40 | **100.62** | 100.36 | 100.50 | 0.25 | highest high: the hill block (high at the 11:03 minute) |
| ... | | | | | | |
| 11:37 | 100.30 | 100.34 | 100.12 | 100.15 | 0.25 | needs a low of 100.62 - 2 x 0.25 = 100.12: **hill confirmed** |
| ... | | | | | | down leg; a valley later at 14:50 (100.05) |

**Pivots after 2.4 - 2.5**

| Pivot | Minute | Price | Note |
|---|---|---|---|
| hill (previous day) | 14:10 | 100.80 | its zone and event belong to the previous day; 09:30 falls inside its down leg, so 09:30 becomes a pseudo hill |
| pseudo hill | 09:30 | 100.30 | the 09:30 high |
| valley | 10:00 | 99.55 | lowest 1-minute low of the 10:06 block |
| hill | 11:03 | 100.62 | highest 1-minute high of the 11:11 block |
| valley | 14:50 | 100.05 | |

**Zones and events (2.7)**

| Pivot | Band | Before side | After side | Zone | 0.3% target (from the zone's last close) | Reached | Event? |
|---|---|---|---|---|---|---|---|
| pseudo hill 09:30 | 100.22 .. 100.30 | does not hold: 09:30 alone | 09:30 .. 09:33 | 4 minutes, so 1 added before: 09:29 .. 09:33 | 09:33 close 100.20: a high at or below 99.90 | 09:47 (high 99.86) | **yes**, 4 entry minutes (09:29 is before 09:30) |
| valley 10:00 | 99.55 .. 99.63 | 09:57 .. 10:00 (14 of 16 inside; 09:57 - 09:58: 6 of 8) | 10:00 .. 10:06 (26 of 28; 10:05 - 10:06: 7 of 8) | 09:57 .. 10:06, 10 minutes | 10:06 close 99.60: a low at or above 99.90 | 10:29 (low 99.91) | **yes**, 10 entry minutes |
| hill 11:03 | 100.54 .. 100.62 | 10:59 .. 11:03 | 11:03 .. 11:07 | 10:59 .. 11:07, 9 minutes | 11:07 close 100.55: a high at or below 100.25 | 11:36 (high 100.24) | **yes**, 9 entry minutes |
| valley 14:50 | 100.05 .. 100.13 | 14:46 .. 14:50 | 14:50 .. 14:55 | 14:46 .. 14:55 | | | **no**: no zone minute between 09:30 and 14:45 |

**`events.parquet`** (one row per event)

| Date | Type | Pivot minute | Price | Pseudo | Competent | Range | Zone | Entry minutes | Best move reached |
|---|---|---|---|---|---|---|---|---|---|
| D | hill | 09:30 | 100.30 | yes | no | train | 09:29 .. 09:33 | 4 | -0.65% (to 99.55 at 10:00) |
| D | valley | 10:00 | 99.55 | no | no | train | 09:57 .. 10:06 | 10 | +1.02% (to 100.62 at 11:03) |
| D | hill | 11:03 | 100.62 | no | no | train | 10:59 .. 11:07 | 9 | -0.50% (to 100.05 at 14:50) |

**`candles_events.parquet`** (the Phase 1 table plus these columns; a few minutes around the valley)

| Minute | Pivot | Pivot price | Pseudo | Zone of | Entry minute |
|---|---|---|---|---|---|
| 09:56 | | | | | |
| 09:57 | | | | valley 10:00 | yes |
| 10:00 | valley | 99.55 | no | valley 10:00 | yes |
| 10:06 | | | | valley 10:00 | yes |
| 10:07 | | | | | |

**`WorkLog.md` lines for this phase** (format only; the counts are illustrative, for 5 warm-up, 80 train and 63 validation sessions)
```
2026-10-22 21:30:10.105  2.1  blocks: warm-up 145, train 2,320, validation 1,827 (29 a day: 28 of 13 minutes + 1 of 11); special sessions 0
2026-10-22 21:30:10.212  2.2  first ATR value at block 14 of the warm-up; median ATR 0.24% of price (train), 0.22% (validation)
2026-10-22 21:30:10.640  2.3  pivots: train 168 hills / 167 valleys, validation 131 / 132; median 26 minutes from pivot to confirming block
2026-10-22 21:30:10.702  2.4  pinned 598 train and validation pivots to 1 minute; competent 371
2026-10-22 21:30:10.715  2.5  pseudo pivots 143 (one per normal session); same-day pivots before 09:30 set aside 31
2026-10-22 21:30:10.730  2.6  pivots written: train 335, validation 263, pseudo 143 (31 set aside)
2026-10-22 21:30:11.380  2.7  pivots with a zone 710; events: train 152 (78 valleys, 74 hills), validation 118 (60, 58); not events: 0.3% not reached 347, zone outside 09:30..14:45 93, special session 0; zone length per event: middle value 9 minutes, shortest 5, longest 26; entry minutes per event: middle value 9
2026-10-22 21:30:11.501  2.8  wrote events.parquet (270 rows), candles_events.parquet (55,500 rows)
```

---

## Phase 3: Compute indicators

**Goal:** compute every chosen indicator on every timeframe for every minute, with its past values (lag and seq) in the same row, and mark whether each value rests on today's candles alone.

**Input:** the output of Phase 2 (`candles_events.parquet`) and the indicators and versions in `run_inputs.md` (0.3).

**Output:** `backtests/<run ID>/indicators.parquet`: the Phase 2 table plus, for each indicator output and timeframe, its current value, its lag and seq values, and the day flags of 3.4. This is the input of Phase 4.

### Sample input
The Phase 2 table (`candles_events.parquet`); see the sample outputs of Phases 1 and 2.

### 3.1 Read the indicators
- Take the indicators and versions chosen in 0.3, with their parameter values from `Indicator.md`.
- An indicator that needs volume is not run for an instrument without volume (0.1).
- **Log:** indicators run, their versions and parameter values; indicators not run, with the reason.

### 3.2 The previous candle
For the N-minute candle at row t:
- if row t - N is in the same session, the previous candle is the candle at row t - N;
- otherwise, the previous candle is the **previous session's last minute (15:29)**: on 5 minutes the full candle 15:25 .. 15:29.

Every step further back applies the same rule again.

| 5-minute candle at | Previous (lag 1) | lag 2 | lag 3 |
|---|---|---|---|
| 09:17 (09:15 .. 09:17, partial) | previous session 15:29 | previous session 15:24 | previous session 15:19 |
| 09:20 (09:16 .. 09:20) | 09:15 (09:15 only, partial) | previous session 15:29 | previous session 15:24 |
| 09:24 (09:20 .. 09:24) | 09:19 | previous session 15:29 | previous session 15:24 |
| 11:27 (11:23 .. 11:27) | 11:22 | 11:17 | 11:12 |

- **Log:** nothing (the rule is fixed).

### 3.3 Compute each indicator
- **Indicators with memory** (Range Filter, HalfTrend): every reference to "one candle back" in the formula (`[1]` in the Pine script) is the previous candle of 3.2. So the Range Filter at 11:27 on 5 minutes continues from its own value at 11:22, 11:17, ..., back through earlier sessions. Partial candles at the open are used like any other candle.
- **One-candle indicators** (candle sweep, colour, flip, engulf, range break) compare the candle with its previous candle of 3.2.
- **Zero-lag sweep** uses the 1-minute rows inside the current candle.
- On 1, 3 and 5 minutes, which divide the 375-minute session, the rows ending at the session's own block ends (on 5 minutes: 09:19, 09:24, ..., 15:29) form exactly the candles of a TradingView chart of that timeframe, so their values match the chart. On 2, 8, 13, 21 and 34 minutes the values near the open differ from a chart.
- Before an indicator has the candles its warm-up needs (0.5), its value is left empty.
- **Log:** columns computed per indicator and timeframe; for each indicator and timeframe, the first date with a value.

### 3.4 Day flags
Two flags per timeframe, so a reader can tell whether a value rests on today's candles alone:
- **`partial_Nm`**: the row's own N-minute candle has fewer than N minutes (the first N - 1 minutes of a session, or missing minutes).
- **`today_only_Nm`**: the row's candle and every lag candle up to the depth (3.5) are full candles of today's session. It turns on at `09:15 + (depth + 1) x N - 1`:

  | Timeframe | 1 | 2 | 3 | 5 | 8 | 13 | 21 | 34 |
  |---|---|---|---|---|---|---|---|---|
  | `today_only` from | 09:24 | 09:34 | 09:44 | 10:04 | 09:46 | 10:06 | 10:38 | 11:30 |

- These flags describe the candles and their lags. An indicator with memory (Range Filter, HalfTrend) always carries some of the previous sessions by design, whatever the flag says.
- **Log:** rows with each flag per timeframe.

### 3.5 Lag and seq columns
- **Lag k** (`<output>_<N>m_<k>lag`): the value at the k-th previous candle of 3.2 (non-overlapping candles).
- **Seq k** (`<output>_<N>m_<k>seq`): the value at row t - k, the rolling candle k minutes earlier (overlapping candles); near the open it reaches into the previous session (09:16's seq 2 is the previous session's 15:29 row).
- **Depth:** 9 for 1, 2, 3 and 5 minutes; 3 for 8, 13, 21 and 34 minutes. On 1 minute lag and seq are the same, so only lag is kept.
- Every output of every chosen indicator gets them. With the 7 current indicators this is about 2,750 columns:

  | | Outputs per timeframe | Copies per output | Columns |
  |---|---|---|---|
  | 1 minute | 28 (no zero-lag sweep) | current + 9 lag = 10 | 280 |
  | 2, 3, 5 minutes | 29 each | current + 9 lag + 9 seq = 19 | 1,653 |
  | 8, 13, 21, 34 minutes | 29 each | current + 3 lag + 3 seq = 7 | 812 |
  | **Total** | | | **2,745** (plus 16 day flags) |

  Values are stored as 4-byte numbers: about 600 MB in memory for 55,500 rows; the Parquet file is smaller (true/false columns compress well).
- **Log:** lag and seq columns built; total columns.

### 3.6 Check
- **Look-ahead:** scramble every candle after a cut-off minute, recompute, and confirm that no value at or before the cut-off changed, current, lag or seq (several cut-offs, including the session start).
- **Reference:** the 5-minute rows ending at 09:19, 09:24, ... reproduce the Range Filter and HalfTrend samples of `Indicator.md` 2.1 and 2.2.
- If a check fails, the run stops (Instruction 6).
- **Log:** cut-offs tested; passed, or the first difference.

### 3.7 Save
- Write `backtests/<run ID>/indicators.parquet`.
- **Log:** file written, rows, columns.

### Sample output
NIFTY, 2026-01-05, 5-minute timeframe, Range Filter v1 and CLV (real values). The previous session was 2026-01-02.

| Row | 5m candle | Range Filter line | direction | signal | CLV | `partial_5m` | `today_only_5m` |
|---|---|---|---|---|---|---|---|
| 2026-01-02 15:29 | 15:25 .. 15:29 | 26318.03 | +1 | | +0.18 | no | yes |
| 09:19 | 09:15 .. 09:19 | 26318.29 | +1 | | +0.31 | no | no |
| 09:24 | 09:20 .. 09:24 | 26318.29 | +1 | | -0.82 | no | no |
| 09:29 | 09:25 .. 09:29 | 26318.29 | +1 | | -0.22 | no | no |
| **09:34** | 09:30 .. 09:34 | **26302.58** | **-1** | **Sell** | -0.82 | no | no |
| 11:24 | 11:20 .. 11:24 | 26344.39 | +1 | | -0.97 | no | yes |

The same row 09:34 with its lag columns:

| Column | Value | Taken from |
|---|---|---|
| `rf_filt_5m` | 26302.58 | 09:34 |
| `rf_filt_5m_1lag` | 26318.29 | 09:29 |
| `rf_filt_5m_2lag` | 26318.29 | 09:24 |
| `rf_filt_5m_3lag` | 26318.29 | 09:19 |
| `rf_filt_5m_4lag` | 26318.03 | previous session 15:29 |
| `clv_5m` | -0.82 | 09:34 |
| `clv_5m_1lag` | -0.22 | 09:29 |
| `clv_5m_2lag` | -0.82 | 09:24 |
| `clv_5m_1seq` | (the rolling candle 09:29 .. 09:33) | 09:33 |

`WorkLog.md` lines for this phase (format only; the counts are what the sample inputs give):
```
2026-10-20 21:30:12.010  3.1  indicators run: Range Filter v1 (ohlc4, 50, 3), HalfTrend v1 (2, 2, 100), CLV, Wick ratio, Candle sweep, Zero-lag sweep, Colour/flip/engulf/break; none skipped (none needs volume)
2026-10-20 21:30:19.480  3.3  computed 231 indicator columns (8 timeframes); first value: Range Filter 13m 2026-01-01, 21m 2026-01-06, 34m 2026-01-14; HalfTrend 21m 2026-01-01, 34m 2026-01-07; all others within the warm-up
2026-10-20 21:30:19.655  3.4  day flags: partial_5m 592 rows, today_only_5m 48,248 rows (10:04..15:29 x 148 sessions), ...
2026-10-20 21:30:24.902  3.5  lag and seq columns: 2,514 built; table 2,761 indicator and flag columns
2026-10-20 21:30:31.233  3.6  look-ahead check at 4 cut-offs: passed; Indicator.md 2.1 / 2.2 samples reproduced
2026-10-20 21:30:38.770  3.7  wrote indicators.parquet: 55,500 rows
```
