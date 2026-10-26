# Subagent prompt: BehaviourColumns (Phase 4.1)

Placeholders filled by the run: `{INDICATOR}`, `{VERSION}`, `{RUN_DIR}`.

---

You design behaviour columns for one indicator, for a research framework that looks for indicator behaviour around market turning points. You start with no other context. Do not open any data file (no `.parquet`, no `.json` with prices), any results file, or anything not listed below.

## Read
1. `analysis_rajkumarn/Indicator.md`: section 1 (Summary) and the definition of **{INDICATOR}** ({VERSION}): formula, outputs, how to read it.
2. `analysis_rajkumarn/Trading_indicator_categories.md`: the 8 indicator families and the metadata each needs.
3. `{RUN_DIR}/columns_{INDICATOR}.md`: the names of the columns that already exist for this indicator (current value, lag and seq copies, on timeframes 1, 2, 3, 5, 8, 13, 21, 34), and the candle columns `o_Nm, h_Nm, l_Nm, c_Nm, v_Nm`.

## Facts about the existing columns
- Each row is one minute. `x_Nm` is the value for the N-minute rolling candle ending at that minute.
- `x_Nm_klag` is the value k non-overlapping N-minute candles back. `x_Nm_kseq` is the value at the row k minutes back (an overlapping rolling candle).
- Depth: 9 for 1, 2, 3, 5 minutes; 3 for 8, 13, 21, 34. On 1 minute only lag exists.
- An indicator with memory (Range Filter, HalfTrend) on N minutes is N interleaved chains: the value at 11:27 continues from 11:22, 11:17, ... So a seq value belongs to a different chain.

## Rules
1. Classify each output of {INDICATOR} into a family of the categories file, and write its metadata: value type, whether zero is meaningful, whether thresholds are meaningful, whether price comparison applies, whether % change is valid, normalisation.
2. Propose only behaviour columns valid for that family.
3. **Indicators with memory:** differences, slopes, runs (consecutive rises) and durations (candles since a flip) along **lags only**, counted in that chain's candles. Seq-based differences only for one-candle indicators, and mark them `overlapping`.
4. **Price** is the row's 1-minute close `c_1m`.
5. A distance from a price line: in points, in % of price, and in units of the Range Filter's own range on the same timeframe if the Range Filter is available. Never use any ATR built for hills and valleys.
6. Bounded values: absolute change over a stated lag; never % change.
7. An empty input gives an empty output; never treat empty as 0.
8. **No look-ahead.** A column at a row may use only that row and earlier rows. A behaviour that needs later candles (a local peak) is defined as confirmed k candles later and stamped on the confirming row.
9. No redundant copies of the same information (for example the zero-lag sweep on 2 minutes equals the 1-minute candle sweep).
10. Keep the list useful, not exhaustive: about 10-25 behaviour formulas per output, each applied on chosen timeframes.

## Return
A markdown file content with:
1. A table of the outputs with their family and metadata.
2. A table of behaviour columns: `name` (pattern `{output}_{behaviour}_{N}m`), output, family, formula (exact, using existing column names), timeframes, empty handling, overlapping (yes/no), one-line reason it is valid.
3. A short list of behaviours you rejected and why.
