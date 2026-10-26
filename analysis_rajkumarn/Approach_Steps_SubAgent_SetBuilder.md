# Subagent prompt: SetBuilder (Phase 5.2)

Placeholders filled by the run: `{INDICATOR}`, `{SIDE}` (valley or hill), `{RUN_DIR}`, `{N_SETS}`, `{SEED}`, `{PSEUDO_RULE}` (how pseudo zones are used, as decided for the run).

---

You plan the discovery sets for one indicator and one side. You start with no other context. Do not open any data file with prices or indicator values, any results file, or anything not listed below.

## Read
1. `{RUN_DIR}/zones_{SIDE}.md`: the {SIDE} zones of the train range: ZoneID, date, time of day of the pivot, pseudo (yes/no), competent (yes/no), and whether the zone is held out (never to be put in a set).
2. `{RUN_DIR}/Current_ind_behav_catalogue_{INDICATOR}.md`: the behaviours that {INDICATOR}'s columns can express, with the columns of each.
3. `{RUN_DIR}/columns_{INDICATOR}.md`: every column name, base and behaviour.

## Task
Make {N_SETS} sets. Each set has:
- exactly 10 ZoneIDs of the {SIDE} side, never a held-out zone;
- a subset of the catalogue: 2-5 related behaviours;
- the columns those behaviours need, plus `c_1m` and the zone markers, at most 100 columns.

## Rules
- Spread the zones of each set over different dates and times of day; do not put two zones of the same date in one set unless there are not enough dates.
- Follow the run's pseudo setting: {PSEUDO_RULE}.
- Over all sets, every catalogue behaviour should appear in several sets, and every non-held-out zone in several sets, as evenly as possible.
- Use the seed {SEED} for any random choice and say how you used it, so the sets can be rebuilt.

## Return
A JSON list, one object per set:
`{"set_id": "...", "zone_ids": [...10...], "behaviours": [catalogue numbers and names], "columns": [...], "why": "one line"}`
followed by a short table: how many sets each zone and each behaviour appears in.
