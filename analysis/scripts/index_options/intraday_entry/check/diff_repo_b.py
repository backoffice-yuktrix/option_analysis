"""check/diff_repo_b.py - compare the PRIMARY coding (signals_repo_b.py) with the blind SECOND coding
(check/alt_repo_b.py) of five library candidates, and run the mechanical look-ahead check on the primary.

For both indexes, every discovery session 2026-01-01 .. 2026-04-30, the centre and every neighbour
(matched by POSITION, labels and parameter dicts are compared too), the two outputs (None or
(t, direction)) are compared.  Only signals are looked at: day, minute, direction, counts.  Nothing
that happens after a signal is computed or read.

    python check/diff_repo_b.py            # diff + look-ahead check + final counts
    python check/diff_repo_b.py --json     # also write the result to the output folder
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, STUDY)
sys.path.insert(0, HERE)

import ctx as C                    # noqa: E402
import signals_repo_b as PRI       # noqa: E402
import alt_repo_b as ALT           # noqa: E402

IDS = ("repo_snd_sweep_microbreak", "repo_snd_zone_touch", "repo_vpr_break_retest", "repo_vpr_reentry",
       "repo_atr_trail_ema_cross")


def _cells(cand):
    return [("centre", cand["centre"])] + [(nb["label"], nb["params"]) for nb in cand["neighbours"]]


def main() -> int:
    structure = []
    for cid in IDS:
        if cid not in PRI.CANDIDATES:
            structure.append(f"{cid}: missing in the primary")
            continue
        if cid not in ALT.CANDIDATES:
            structure.append(f"{cid}: missing in the second coding")
            continue
        p, a = _cells(PRI.CANDIDATES[cid]), _cells(ALT.CANDIDATES[cid])
        if len(p) != len(a):
            structure.append(f"{cid}: {len(p)} cells in the primary, {len(a)} in the second coding")
        for (pl, pp), (al, ap) in zip(p, a):
            if pl != al:
                structure.append(f"{cid}: label {pl!r} (primary) vs {al!r} (second)")
            if pp != ap:
                structure.append(f"{cid} [{pl}]: params {pp!r} (primary) vs {ap!r} (second)")
    print("== structure (ids, labels, parameter dicts, matched by position) ==")
    print("  identical" if not structure else "\n".join("  " + s for s in structure))

    total_cmp = total_dis = 0
    lookahead: list[str] = []
    crashes: list[str] = []
    counts: dict = {}
    disagreements: list = []
    for index in C.INDEXES:
        market = C.Market(index)
        days = [d for d in market.sessions if C.WINDOW_START <= d <= C.DISCOVERY_END]
        if days[-1] > C.DISCOVERY_END:
            raise SystemExit("a day after the discovery wall was listed")
        print(f"\n===== {index}: {len(days)} sessions {days[0]} .. {days[-1]} =====")
        for cid in IDS:
            pc, ac = PRI.CANDIDATES[cid], ALT.CANDIDATES[cid]
            for (label, pparams), (_, aparams) in zip(_cells(pc), _cells(ac)):
                agree = 0
                diffs = []
                sigs = []
                for d in days:
                    dc = market.day_ctx(d)
                    try:
                        rp = pc["fn"](dc, **pparams)
                    except Exception as e:                       # noqa: BLE001 - reported, not hidden
                        crashes.append(f"PRIMARY {cid} [{label}] {index} {d}: {type(e).__name__}: {e}")
                        rp = ("raised", type(e).__name__)
                    try:
                        ra = ac["fn"](dc, **aparams)
                    except Exception as e:                       # noqa: BLE001
                        crashes.append(f"SECOND {cid} [{label}] {index} {d}: {type(e).__name__}: {e}")
                        ra = ("raised", type(e).__name__)
                    rp = None if rp is None else tuple(rp)
                    ra = None if ra is None else tuple(ra)
                    if rp == ra:
                        agree += 1
                    else:
                        diffs.append((d, rp, ra))
                    if rp is not None and rp[0] != "raised":
                        sigs.append((d, rp[0], rp[1]))
                    try:
                        lookahead.extend(f"{cid} [{label}] {p}" for p in C.check_no_lookahead(pc["fn"], dc, pparams))
                    except Exception as e:                       # noqa: BLE001
                        crashes.append(f"LOOKAHEAD {cid} [{label}] {index} {d}: {type(e).__name__}: {e}")
                total_cmp += len(days)
                total_dis += len(diffs)
                up = sum(1 for s in sigs if s[2] == "UP")
                ts = sorted(s[1] for s in sigs)
                counts[(cid, label, index)] = (len(sigs), up, len(sigs) - up, ts[0] if ts else "-", ts[-1] if ts else "-")
                print(f"  {cid:27s} {label:30s} compared {len(days)}  agree {agree}  disagree {len(diffs)}"
                      f"   | primary n={len(sigs)} UP={up} DOWN={len(sigs) - up} {ts[0] if ts else '-'}..{ts[-1] if ts else '-'}")
                for d, rp, ra in diffs:
                    print(f"        {d}: primary {rp}   second {ra}")
                    disagreements.append({"id": cid, "cell": label, "index": index, "day": d,
                                          "primary": rp, "second": ra})

    print(f"\n== totals ==\n  session-cells compared {total_cmp}, disagreements {total_dis}")
    print(f"  look-ahead problems on the primary: {len(lookahead)}")
    for p in lookahead[:60]:
        print("    " + p)
    print(f"  exceptions: {len(crashes)}")
    for p in crashes[:60]:
        print("    " + p)

    print("\n== final primary signal counts: n (UP/DOWN) earliest..latest ==")
    for cid in IDS:
        for label, _ in _cells(PRI.CANDIDATES[cid]):
            row = []
            for index in C.INDEXES:
                n, up, dn, a, b = counts[(cid, label, index)]
                row.append(f"{index} {n} ({up}/{dn}) {a}..{b}")
            print(f"  {cid:27s} {label:30s} " + "   ".join(row))

    if "--json" in sys.argv:
        os.makedirs(C.OUTPUT_DIR, exist_ok=True)
        path = os.path.join(C.OUTPUT_DIR, "diff_repo_b.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"compared": total_cmp, "disagreements": disagreements, "lookahead_problems": lookahead,
                       "exceptions": crashes, "structure": structure,
                       "counts": [{"id": k[0], "cell": k[1], "index": k[2], "n": v[0], "up": v[1], "down": v[2],
                                   "earliest": v[3], "latest": v[4]} for k, v in counts.items()]}, f, indent=1)
        print(f"\nwritten {path}")
    return 1 if (lookahead or crashes or structure) else 0


if __name__ == "__main__":
    sys.exit(main())
