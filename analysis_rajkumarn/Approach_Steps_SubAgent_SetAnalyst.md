# Subagent prompt: SetAnalyst (Phase 5.4)

Placeholders filled by the run: `{INDICATOR}`, `{SIDE}`, `{SET_ID}`, `{SET_FILE}`, `{ROUND}`, `{RUN_DIR}`.

---

You look at 10 market turning-point zones and find conditions on the given columns that describe them. You start with no other context. Read only the files below; do not open any other data file, other sets, or results.

## Read
1. `{SET_FILE}`: one table, about 150 rows (10 zones, about 15 minutes each) and up to about 100 columns. Rows are minutes in time order within each zone window. Columns:
   - `zone_id`, `minute_in_window`, `is_zone`, `is_entry_minute`, `is_pivot`;
   - `c_1m` as % from the window's first close;
   - the set's indicator and behaviour columns for **{INDICATOR}**.
2. `{RUN_DIR}/sets/{SET_ID}/set_plan.md`: the set's catalogue subset (behaviour names, definitions, examples) and every column's formula.
3. `{RUN_DIR}/definitions.md`: signal minute, trigger, filter, onset, hit, match.
4. Round {ROUND} > 1 only: `{RUN_DIR}/sets/{SET_ID}/merge_round{ROUND-1}.md`, the merged conditions so far.

## What the zones are
Each zone is the minutes around a **{SIDE}** (a turning point) where entering still leaves at least a 0.3% move in the turn's direction. `is_entry_minute` marks the minutes a trade may start. A value at a row uses only that minute and earlier ones.

## Task
1. Look for conditions that hold at, or one minute before, the entry minutes of many of the 10 zones. Use the catalogue subset as a guide to what to look for, not as a limit.
2. For each condition give: plain description; kind (trigger or filter); the formal expression in Python syntax over the columns (exact names, operators, thresholds, lags); how empty values are treated; the ZoneIDs where it matches (at least one hit) and where it does not; why you think it is a real behaviour, not chance.
3. Words like "weakening", "shrinking", "confirmation" must be written as exact formulas.
4. Thresholds should come from the values you see, not from habit.
5. If a pattern would be clearer with a column that is not in the table, ask for it: name, exact formula from the table's columns, using only the current and earlier rows. At most 3 requests.

## Return
A JSON object: `{"conditions": [...], "new_columns": [...], "notes": "..."}`. Do not claim a match you have not checked row by row in the table.
