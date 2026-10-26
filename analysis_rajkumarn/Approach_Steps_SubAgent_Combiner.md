# Subagent prompt: Combiner (Phase 5.7)

Placeholders filled by the run: `{INDICATOR}`, `{SIDE}`, `{RUN_DIR}`, `{W}` (minutes allowed between two triggers).

---

You look for combinations of conditions that describe the zones of one side better together than alone. You start with no other context. Do not open any data file, the development range's results, `Indicator_Results.md`, or anything not listed below.

## Read
1. `{RUN_DIR}/phase5_{SIDE}_conditions.md`: the 10-15 consolidated conditions (formal expression, kind, description).
2. `{RUN_DIR}/phase5_{SIDE}_zone_table.md`: one row per train zone of the side, one column per condition: matched (yes/no) and lead time; plus, per condition, its onsets outside zones per session.
3. `{RUN_DIR}/definitions.md`.

## Task
Propose combinations:
- **AND** of a trigger with one or more filters (the filters true at the trigger's onset minute);
- **AND** of two triggers (the second onset within w minutes after the first, w = {W});
- **OR** of conditions that match different zones.

For each: the formal expression, the ZoneIDs you expect it to match (from the table), the reason you expect fewer firings outside zones (for AND) or more zones covered without many more firings (for OR). At most 3 conditions in one combination.

## Return
A JSON list of combinations, then one paragraph on which conditions complement each other (match different zones) and which only repeat each other.
