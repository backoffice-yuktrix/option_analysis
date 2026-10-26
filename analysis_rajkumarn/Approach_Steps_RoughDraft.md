# Approach steps: rough draft for Phases 3-8 as a loop

Status: **draft for discussion**, fourth version (2026-10-25). Nothing here is decided until it is moved into `Approach_Steps.md`. Section 11 lists what the user still has to decide; where this draft needs a value it uses the suggested default from there, marked **[G#]**.

How this version was made:
1. Version 1 from `Approach_Steps.md` (Instructions, Phases 0-3), `Indicator.md`, and the user's notes `analysis_rajkumarn/Trading_llm_pattern_discovery_workflow.md`, `analysis_rajkumarn/Trading_llm_pattern_discovery_workflow2.md`, `analysis_rajkumarn/Trading_indicator_categories.md`, `analysis_rajkumarn/Trading_indicator_behaviours_catalogue.md`.
2. Version 2 after a cold review by a separate agent with no memory of the discussion.
3. Version 3 rebuilt Phases 4 and 5 on the user's flow (4.1 - 4.3, 5.1 - 5.8) and added one prompt file per subagent.
4. **Version 4 (this one)** after a second cold review of version 3 and the seven prompt files (`Approach_Steps_SubAgent_Reviewer.md`). Its findings were checked against the documents. The prompt files still have the version-3 wording; they are updated once section 11 is decided, because several of them depend on those answers.

---

## 1. The flow

```
Phase 0 Inputs
Phase 1 Candles                      candles.parquet
Phase 2 Events and zones             candles_events.parquet, events.parquet  (every zone gets a ZoneID)
   |
   +--> for each chosen indicator, in the order chosen at 0.3:
          Phase 3 Compute the indicator        (on a copy of candles_events.parquet; saved after Phase 4)
          Phase 4 Behaviours                   candles_events_<Indicator>.parquet, Current_ind_behav_catalogue_<Indicator>.md
          Phase 5 Discovery, once per side     sets of 10 zones -> conditions -> one final condition per side
          Phase 6 Validation (May-Jul)         the final condition per side, measured once per turn
          Phase 7 Existing condition           keep / merge / replace, the user accepts
          Phase 8 Report                       Indicator_Results.md
```

- Phase numbers 6-8 are a proposal **[G13]**. In this flow consolidation sits inside Phase 5, so the earlier separate "consolidation" phase goes away.
- "Validation" is the range the user gives at 0.2 (in the samples May-Jul). Because it is read in every turn, its numbers are a check that weakens with use, not an untouched test; the user's untouched test is the only independent one **[G12]**.

## 2. Columns per row

| | Columns |
|---|---|
| Candles, 8 timeframes x O/H/L/C/V | 40 |
| Tags and flags (range, session, trade window; `partial_Nm` x 8, `today_only_Nm` x 8) | 19 |
| Event and zone columns from Phase 2 (pivot, pivot price, pseudo, competent, ZoneID, entry minute) | about 6 |
| **One indicator output** on 8 timeframes: current 8; lag + seq on 1/2/3/5 minutes 63 (on 1 minute lag only: 9 + 18 x 3); on 8/13/21/34 minutes 24 (6 x 4) | **95 per output** |

Outputs per indicator: Range Filter 7, HalfTrend 4, CLV 1, wick ratio 2, candle sweep 6, zero-lag sweep 2, colour / flip / engulf / break 7. One turn's base table is about 160 columns for CLV and about 730 for the Range Filter, before the behaviour columns of Phase 4.

## 3. Phase 2 change: ZoneID

- Every zone gets a **ZoneID** in `candles_events.parquet` (column `zone_id` on every zone minute) and in `events.parquet`: `V0001`, `V0002`, ... for valley zones and `H0001`, ... for hill zones, numbered in time order.
- The Phase 2 sample's "Zone of: valley 10:00" column becomes `zone_id`. The Phase 2 log also states the share of pseudo zones per side.

## 4. Phase 3 in the loop

- A **copy** of `candles_events.parquet`; the turn's indicator computed on it as in `Approach_Steps.md` Phase 3.
- Saved once, at the end of Phase 4, as `candles_events_<Indicator>.parquet`.

## 5. Phase 4 in the loop: behaviours

### 4.1 Behaviour columns list (subagent: BehaviourColumns)
- **Input:** the indicator's entry in `Indicator.md`, `Trading_indicator_categories.md`, `columns_<Indicator>.md` (Python writes it: every column name of the Phase 3 table, no values).
- **Output:** `behaviour_columns_<Indicator>.json`: per column its name, output, family, formula, timeframes, empty handling, overlapping (yes / no), reason.
- **Formulas use a small fixed vocabulary** that Python computes along the chain on the full series (not only within the 9 lags stored): for example `diff_lag(x, k)`, `pct_dist(a, b)`, `run_up_lag(x)` (consecutive rises along the chain), `bars_since(cond)` (chain candles since a condition was last true), `cross_lag(a, b)` (a crossed b between lag 1 and now), `above(a, b)`, `between(x, lo, hi)`. The full vocabulary is written once in the prompt file and in `Approach_Steps.md`.
- **Rules:**
  - along lags only for indicators with memory (Range Filter, HalfTrend: N interleaved chains per timeframe); seq differences only for one-candle indicators, marked overlapping;
  - price = the row's 1-minute close `c_1m`;
  - a distance from a price line in points, in % of price, and, in the Range Filter turn only, in units of the Range Filter's own range (no other indicator exists inside a single-indicator turn); never the hill/valley ATR;
  - bounded values (CLV, wick ratios): absolute change, never % change;
  - empty stays empty;
  - no look-ahead: a behaviour needing later candles is "confirmed k candles later" and stamped on the confirming row;
  - no redundant copies (zero-lag sweep on 2 minutes equals the 1-minute candle sweep).
- **Family notes:** the Range Filter's `src` cannot leave its bands (the ratchet), but `c_1m` and the candle's high and low can, so band position uses `c_1m`; the band width is a volatility measure. The lower and upper wick ratios are not independent (lower + upper + body = 1). The Range Filter and HalfTrend lines are built from price, so price-indicator divergence does not apply to them.

### 4.2 Build the columns (Python)
- Every column of the 4.1 list computed on the Phase 3 table; the look-ahead check (Phase 3.6) repeated on them; `candles_events_<Indicator>.parquet` saved.
- **Output also:** `columns_<Indicator>_built.md`: every base and behaviour column that was built, with its formula; columns refused (invalid formula, look-ahead found) with the reason.

### 4.3 Current behaviour catalogue (subagent: BehaviourCatalogue)
- **Input:** `Trading_indicator_behaviours_catalogue.md`, `columns_<Indicator>_built.md` (the built list, base columns included), the indicator's entry in `Indicator.md`.
- **Output:** `Current_ind_behav_catalogue_<Indicator>.md`: the catalogue behaviours the built columns can express, each with an exact definition, **an example of how it might happen** (a few made-up rows), and its columns as a machine-readable list; behaviours that would need a missing column (with that column's formula, kept as candidates for the next run's 4.1); behaviours that do not apply, with the reason.

## 6. Phase 5 in the loop: discovery (5.2 - 5.8 once for valleys, once for hills)

### Definitions (Python writes them to `definitions.md`; every subagent and every count uses them)
- **Signal minute:** a condition is read on the completed candle of minute t; the trade is at t + 1. Signal minutes are 09:29 .. 14:44 on normal sessions.
- **Trigger:** happens at a minute (a flip, a sweep, a crossing). **Onset:** the first true minute after at least k false minutes, k = 5 **[G7]**.
- **Filter:** a state (direction up, CLV above 0.5). It becomes a trade only together with a trigger.
- **Hit:** a trigger onset at t whose t + 1 is an entry minute of a zone of the condition's side. **Filter match:** the filter is true at the signal minute just before at least one entry minute of the zone.
- **A condition matches a zone** when it has at least one hit (trigger) or one filter match (filter) in that zone.
- **Lead time:** the hit's t + 1 minus the pivot minute, in minutes (negative = entry before the turn).
- **False positive:** an onset that is not a hit; one landing in a zone of the other side is counted apart (it is the costlier kind).
- **Base rate:** the share of signal minutes whose t + 1 is an entry minute of the side, per 15-minute slot of the day, with 09:29 .. 09:35 as its own slot (the 09:30 pseudo pivots sit there). Lift = precision / base rate of the slots where the onsets fell.
- **Overlap of two conditions:** the Jaccard of their onset minutes (triggers) or of their true minutes (filters).
- **Allowed columns:** a condition may use only columns that can be computed live at the minute. Never `zone_id`, `is_zone`, `is_entry_minute`, `is_pivot`, `minute_in_window`, or any other label. Python rejects an expression that uses any other column.
- **Expression form:** a `pandas.eval` expression over the table's columns, using `&`, `|`, comparisons and arithmetic; any comparison with an empty value is false; `~` is not allowed (write the opposite comparison).

### 5.1 Counts and lists (Python)
- From `candles_events_<Indicator>.parquet`: the train zones per side, real and pseudo apart, with ZoneID, date, time of day; the columns with formulas.
- **Hold-out block [G1]:** the last part of the train range (by date, for example the last 25% of train sessions) is never put in a set. Its zones are the "rest of the zones" of the user's check 2, and every choice in 5.5 - 5.8 is made on them.
- **Output:** `zones_<side>.md`, `columns_<Indicator>_built.md`, the counts in the log.

### 5.2 Build the sets (Python, with an optional LLM step)
- **Python draws the zones**, with a fixed seed: each set gets 10 zones of the side from the discovery part of train (never the hold-out block), no two from the same date where possible, every zone appearing about equally often.
- **The catalogue subset per set:** an LLM (subagent SetBuilder) may group the catalogue's behaviours into themes once per indicator; Python then pairs themes with zone draws. If no LLM is used, Python cycles through the catalogue's groups.
- Number of sets: the user's plan is at least as many sets as zones; **[G2]** proposes a pilot of 20 sets per side, stopping when new sets stop adding new conditions.
- **Output:** `sets/<set_id>/set_plan.md` per set: its 10 ZoneIDs, its behaviours (definitions and examples from the current catalogue), its columns with formulas.

### 5.3 Write one table per set (Python)
- From `candles_events_<Indicator>.parquet`: the set's 10 zones, a window per zone **[G4]**, only the set's columns, at most about 150 rows x 100 columns.
- The **window** always includes non-zone minutes before and after the zone, and at least k minutes before the earliest signal minute, so the analyst sees the zone against its surroundings.
- **Decoy windows [G5]:** 2-3 windows of ordinary non-zone minutes from other train sessions, at similar times of day, mixed in without a label; only Python knows which they are, and scores conditions on them.
- **Price-level columns** (o/h/l/c of any timeframe, Range Filter line and bands, HalfTrend line) are shown as **% of the same row's `c_1m`**, in the set table and in the full table alike, so the instrument's price level is hidden and an expression means the same in both. Nothing is shown relative to the window's start (that would depend on where the zone is).
- Dates are replaced by ZoneIDs.
- **Output:** `sets/<set_id>/set_r1.csv` (CSV, so it can be put straight into the analyst's prompt).

### 5.4 Analyse one set (subagents: SetOwner calls and SetAnalyst pairs)
A subagent cannot start another subagent, so **the run** starts every call; each call starts fresh and gets everything earlier from files.
1. **Round 1 (always):** the run starts two analysts on `set_r1.csv`, independently. Each returns conditions in the shared record (section 6, end) with the zones it claims match, and may ask for **new columns**, each with a stated reason (the pattern it would show).
2. **Owner, merge call:** a fresh owner call reads both answers and `set_plan.md`. It picks and de-duplicates; it **never changes an expression**; each kept condition keeps its analyst's claim. It returns `{merged_conditions, new_columns}`; the run saves `sets/<set_id>/merge_r1.md`. A new column whose formula looks ahead or uses a column outside the set is dropped.
3. **New columns are computed on the full `candles_events_<Indicator>.parquet`** (never inside the 15-row window, which cannot hold earlier minutes), checked for look-ahead, then cut into `set_r2.csv`.
4. **Round 2 (only if new columns were made):** two fresh analysts on `set_r2.csv`, given `merge_r1.md`; owner merge call; `merge_r2.md`. **Round 3** only if round 2 made new columns: once more. No round 4.
5. **Owner, final call:** reads every merge file; writes the set's final conditions (at most 5).
6. **Translation check (Python):** each final condition's expression is run on the set table with the match definition. The analyst's claimed zones and Python's are compared, giving an **LLM accuracy** figure (Jaccard and the list of differences): the user's check 1. A wrong translation of the analyst's own wording into code is fixed once if it is a code error; otherwise the difference is recorded. From here on **Python's match list is the one used**; a condition is dropped only if Python finds it matching fewer than 3 of the 10 zones **[G6]**.
7. **Wider check (Python):** each kept condition on the whole train discovery part (the set's own 10 zones reported apart from the others) and on the decoys: precision, coverage, false positives per session, lift, lead time. Python's evaluator also reports, per zone, which clause of the expression passed or failed and the values used.
- This puts the Python checks before consolidation, a change from the user's order (consolidate first, then check): checking per set lets the consolidator see real numbers. **[G9]**
- Every new column made in any set is logged; Phase 4 can adopt the useful ones next run.

### 5.5 Consolidate all sets (Python, then subagent: Consolidator)
- **Python first:** conditions whose overlap is 0.8 or more form a cluster; one representative per cluster (the highest precision on the discovery part) goes forward, with its cluster listed.
- **Consolidator:** reads the representatives with their numbers, the current catalogue and the column list; removes redundancy by wording too (the user's rule) and may write generalised conditions; keeps 10-15.
- **Python measures** any generalised condition before 5.6.

### 5.6 Condition-by-zone table (Python)
- One row per zone of the side (discovery and hold-out apart), one column per kept condition: matched yes / no and lead time; plus each condition's false positives per session; plus, for every pair, how often both fire at the same signal minute (co-onset counts).

### 5.7 Combine (Python, optional subagent: Combiner)
- **Python enumerates** every combination of up to 3 of the kept conditions in a fixed grammar: AND of a trigger with filters (filters true at the trigger's onset), SEQ of two triggers (the second within w = 5 minutes after the first **[G7]**), OR of conditions. It scores them all on the **hold-out block**.
- The Combiner subagent, if used, only names pairs that complement each other (match different zones), from the 5.6 table and co-onset counts; it does not score.

### 5.8 Final condition and train report (Python)
- The final condition per side is chosen by a fixed rule on the **hold-out block** **[G8]**, for example: the highest hold-out precision among conditions and combinations with hold-out coverage of at least 20% and support of at least 10 distinct dates.
- Report: precision, coverage, false positives (same side / other side) per session, lift, lead time, support in events and dates, discovery against hold-out, first half against second half, real and pseudo zones apart, the number of conditions and combinations tried, and the trade check (section 8).

### The shared condition record
Used by the analysts, the owner, the consolidator, the combiner and Python alike:
`condition_id`, `side`, `kind` (trigger / filter), `feature_names`, `formal_expression`, `nan_rule` (always "empty compares false"), `claimed_zone_ids`, `claimed_non_match_ids`, `description`, `rationale`, `found_by` (set, round, analyst). Python adds `python_zone_ids`, `llm_accuracy`, the wider-check numbers, `cluster`, `decision`.

## 7. Phases 6-8 in the loop

- **Phase 6, validation:** the final condition per side measured once on the validation range, with the same measures and the change from train. Each read is counted, per indicator, side and run.
- **Phase 7, existing condition:** compared four ways with `existing_condition.md` (existing alone, new alone, both, either), on train first; the validation figures of the combination are one more counted read. The framework proposes keep / merge / replace; the user accepts. `existing_condition.md` holds each condition in plain words and its formal expression.
- **Phase 8, report:** `Indicator_Results.md`, under the run ID and indicator.
- Cross-indicator behaviours (catalogue group 10) only arise in Phase 7 comparisons and in a later cross-indicator round; group 11 (volume, directional movement) does not apply to the current seven.

## 8. The index trade check
- Entry at t + 1 at its worst price (buy at the high, sell at the low), target +0.3% from the entry price, out at 14:59 at the latest.
- The stop is known at entry **[G10]**: a fixed %, or the low (valley side) / high (hill side) of the last k minutes minus / plus x%, or a multiple of the Range Filter range.
- Run on **every** onset, inside zones and outside, reported apart. Inside a zone a trade can still lose: an entry on the before side sees price move against it until the pivot (further for minutes added by the 5-minute minimum), and the zone's 0.3% is measured from the zone's last close, not from this entry.

## 9. What each step may see

| Step | May read | Must never read |
|---|---|---|
| BehaviourColumns (4.1) | `Indicator.md` entry, categories file, column names | any values, results, validation |
| BehaviourCatalogue (4.3) | behaviours catalogue, the built column list, `Indicator.md` entry | any values, results |
| SetBuilder (5.2, optional) | the current catalogue | zones, values, results |
| SetAnalyst (5.4) | its set table only, its `set_plan.md`, `definitions.md`, the previous merge file | other sets, the full table, results, validation |
| SetOwner (5.4) | the analysts' answers, `set_plan.md`, `definitions.md`, earlier merge files | any table, results |
| Consolidator (5.5) | cluster representatives with their discovery numbers, the current catalogue, the column list, `definitions.md` | hold-out numbers, validation, `Indicator_Results.md` |
| Combiner (5.7, optional) | the 5.6 table (discovery part), co-onset counts, `definitions.md` | hold-out numbers, validation, `Indicator_Results.md` |

Every subagent starts with no memory of the discussion. Every prompt and answer is saved in the run folder with the model, time and settings; decisions are summarised in `LLMDecisions.md`. A rerun meant to reproduce a result replays the saved formal expressions instead of asking again.

## 10. Cost

Per indicator and side, with N sets: each set has 2-6 analyst calls and 2-4 owner calls, each carrying a 150 x 100 table (tens of thousands of tokens). With N = 100 that is about 400-1,000 calls per indicator and side, about 6,000-14,000 calls for 7 indicators x 2 sides. With the pilot of 20 sets, about 80-200 calls per indicator and side **[G2]**.

## 11. Gaps for the user to decide (suggested default in brackets)

- **G1 Hold-out block** inside train that never goes into a set, used for every choice in 5.5 - 5.8 (the user's "rest of the zones"). [yes: the last 25% of train sessions]
- **G2 Number of sets.** [a pilot of 20 per side, stopping when new sets stop adding new conditions; more only if they still do]
- **G3 Pseudo zones** (one per session at 09:30, a continuation rather than a turn, every larger candle partial). [out of the discovery sets; studied as a separate track later; always reported apart]
- **G4 Window per zone** in a set. [from 10 minutes before the zone start to 4 minutes after the zone end, cut to 15 rows around the first entry minute if longer]
- **G5 Decoy windows** in each set, unlabelled to the analyst. [2-3 per set]
- **G6 Minimum Python matches** for a set's condition to go on. [3 of 10]
- **G7 Values:** k (quiet minutes before an onset) [5]; w (minutes between two triggers in SEQ) [5].
- **G8 Final choice rule** in 5.8. [highest hold-out precision with coverage at least 20% and support at least 10 dates]
- **G9 Order of checks:** Python checks per set before consolidation (this draft), or after consolidation (the user's order). [per set]
- **G10 Stop for the trade check.** [the low / high of the last 5 minutes, minus / plus 0.05%]
- **G11 Analyst new-column requests:** at most 3 per analyst, each with a stated reason. [yes]
- **G12 Name of the May-Jul range:** keep "validation" as in `Approach_Steps.md`, noting it is read in every turn, or rename it "development". [keep "validation", with the note]
- **G13 Phase numbers:** 6 validation, 7 existing condition, 8 report. [yes; Instructions 3, 4 and 7 are updated to match]
- **G14 Loop unit:** per indicator, or per family. [per indicator]

## 12. Changes this would need (not made)

**`Approach_Steps.md`**
- New instruction: Phases 3-8 run once per indicator, in the order chosen at 0.3; inside Phase 5, steps 5.2 - 5.8 run once per side.
- Instruction 3: saved prompts and answers replayed for a reproducing rerun; `existing_condition.md` holds formal expressions; its Phase reference becomes Phase 7.
- Instruction 4: `LLMDecisions.md` covers every subagent of Phases 4 and 5.
- Instruction 7: validation read once per turn and counted; the untouched test the only independent check; phase references updated.
- Instruction 8: the same exception as Instruction 3.
- 0.3: the order of the indicators is asked.
- 2.7 and 2.8: ZoneID; the share of pseudo zones in the log.
- Phase 3: works on a copy; saved after Phase 4.
- Phases 4-8 as above, each with its Input and Output files (Instruction 11).

**`Indicator.md`:** per output, the family metadata of the categories file.

**Prompt files:** rewritten to this version once section 11 is decided: the analyst's allowed columns and exact hit wording; the owner split into a merge call and a final call that never change expressions; the shared condition record and the combination grammar; the 4.1 formula vocabulary and JSON output; the files each step reads, all produced by a named step.
