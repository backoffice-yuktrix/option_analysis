# Subagent prompt: BehaviourCatalogue (Phase 4.3)

Placeholders filled by the run: `{INDICATOR}`, `{VERSION}`, `{RUN_DIR}`.

---

You turn a general catalogue of indicator behaviours into a catalogue for one indicator. You start with no other context. Do not open any data file, results file, or anything not listed below.

## Read
1. `D:\Yuktrix\Trading_indicator_behaviours_catalogue.md`: 180 candidate behaviours in 12 groups.
2. `{RUN_DIR}/behaviour_columns_{INDICATOR}.md`: the behaviour columns built for **{INDICATOR}** ({VERSION}), each with its formula.
3. `analysis_rajkumarn/Indicator.md`: the definition of {INDICATOR}.

## Task
For each catalogue behaviour, decide whether the columns of {INDICATOR} can express it.

## Rules
- A behaviour is included only if it can be written exactly with the listed columns (or a simple combination of them), using only the current and earlier rows.
- Each included behaviour gets a mathematical definition in those columns, with every word such as "weakening", "shrinking", "confirmation" made exact.
- Each included behaviour gets **an example of how it might happen**: 3-6 rows of made-up values for the columns involved, with the row where the behaviour is true marked.
- Do not invent columns. If a behaviour needs a column that does not exist, list it under "would need" with the column it would need.

## Return
`Current_ind_behav_catalogue_{INDICATOR}.md` content:
1. Included behaviours, grouped as in the catalogue: number, name, columns, exact definition, example rows.
2. "Would need": behaviours that fit the indicator but need a column that does not exist, with that column's formula.
3. Not applicable: the rest, one line each with the reason.
