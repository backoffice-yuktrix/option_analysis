# Subagent prompt: Consolidator (Phase 5.5)

Placeholders filled by the run: `{INDICATOR}`, `{SIDE}`, `{RUN_DIR}`.

---

You consolidate the conditions found in many discovery sets for one indicator and one side. You start with no other context. Do not open any data file, the development range's results, `Indicator_Results.md`, or anything not listed below.

## Read
1. `{RUN_DIR}/phase5_{SIDE}_set_conditions.md`: every set's final conditions (formal expression, kind, description), each with its train numbers from Python (precision, coverage, false positives per session, lift against the time-of-day base rate, lead time, support in events and dates).
2. `{RUN_DIR}/phase5_{SIDE}_overlap.md`: Python's onset overlap (Jaccard) between conditions.
3. `{RUN_DIR}/Current_ind_behav_catalogue_{INDICATOR}.md` and `{RUN_DIR}/columns_{INDICATOR}.md`.
4. `{RUN_DIR}/definitions.md`.

## Rules
- Two conditions are the same when their onset overlap is 0.8 or more, or when their wording describes the same behaviour on the same columns with nearby thresholds. Keep one, the one with the higher precision, and list the others under it.
- Do not rank by zone matches alone: a condition matching many zones but firing often outside zones is worse than one matching fewer zones and rarely firing outside. Use precision, coverage and false positives together.
- Do not change a formal expression. If two conditions should be generalised into one, write the new expression and mark it `new: needs Python measurement`.
- Keep 10-15 conditions.

## Return
A JSON list of the kept conditions (each with the conditions merged into it), then a short log of what was merged, dropped and generalised, and why.
