"""check/diff_repo_a.py - adjudication of the five `existing_repo` candidates of group repo_a.

    PRIMARY  signals_repo_a.py          (the coding the study uses)
    SECOND   check/alt_repo_a.py        (blind second coding)
    THIRD    the oracle in this file    (written by the adjudicator from library.json + protocol.md only,
                                         deliberately in another style: numpy, exact-minute dict lookups,
                                         every quantity recomputed from scratch per call)

What it prints (discovery sessions 2026-01-01 .. 2026-04-30, both indexes, centre + every neighbour):
  1. the registry of the PRIMARY against library.json (ids, parameter names, centre values, the neighbour
     values and labels, one value moved at a time) and against the SECOND, position by position;
  2. per candidate variant: sessions compared, agreements, and every disagreement with the day and the answers
     (PRIMARY vs SECOND, and PRIMARY vs THIRD);
  3. ctx.check_no_lookahead of the PRIMARY on every variant / session / index;
  4. a stronger sweep on the PRIMARY: the function is called on the day cut at EVERY minute 09:14 .. 14:14 and
     must answer None before the signal minute and the same signal from that minute on;
  5. structural facts of the signals (window 09:19..14:13, decision minutes, 10-minute alignment);
  6. the final signal counts.

Signals only: (day, minute, direction).  Nothing that happened after a signal is read or computed here.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.normpath(os.path.join(HERE, ".."))
if STUDY not in sys.path:
    sys.path.insert(0, STUDY)

import ctx as C  # noqa: E402

IDS = ("repo_orr_outside_range", "repo_orr_edge_survived", "repo_orr_exhaustion",
       "repo_stretch_fade_1100", "repo_stretch_fade_line_reject")


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# THIRD coding (oracle).  It takes the Market and the day, reads the whole day into a {stamp: bar} dict and
# then only ever asks that dict for stamps at or before the minute it is deciding.
# ---------------------------------------------------------------------------
def _daily(m, d):
    """(high, low, house close) of a completed session d from its 1-minute candles."""
    a = [b for b in m.bars(d) if 555 <= C.minutes(b[0]) <= 929]
    hi = max(b[2] for b in a)
    lo = min(b[3] for b in a)
    last30 = [b for b in a if 900 <= C.minutes(b[0]) <= 929]
    hc = float(np.mean([(b[2] + b[3] + b[4]) / 3.0 for b in last30]))
    return hi, lo, hc


def _tr_list(m, before: list, n: int):
    """True ranges of the n sessions before today, or None when a previous close is missing."""
    if len(before) < n + 1:
        return None
    out = []
    for j in range(1, n + 1):                           # j sessions before today
        hi, lo, _ = _daily(m, before[-j])
        pc = _daily(m, before[-j - 1])[2]
        out.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    return out


def _orr_parts(by, T: str, n_or: int):
    tm = C.minutes(T)
    or_bars = [by.get(C.hhmm(555 + i)) for i in range(n_or)]
    w = [by.get(C.hhmm(x)) for x in range(555 + n_or, tm + 1)]
    if any(b is None for b in or_bars) or by.get(T) is None:
        return None
    w = [b for b in w if b is not None]
    if len(w) < 20:
        return None
    cl = np.array([b[4] for b in w], dtype=float)
    x = np.arange(len(cl), dtype=float)
    slope = float(((x - x.mean()) * (cl - cl.mean())).sum() / ((x - x.mean()) ** 2).sum())
    ct, c0 = cl[-1], cl[0]
    move = "DOWN" if (slope < 0 and ct < c0) else "UP" if (slope > 0 and ct > c0) else None
    return {"orh": max(b[2] for b in or_bars), "orl": min(b[3] for b in or_bars), "cl": cl, "move": move,
            "wh": max(b[2] for b in w), "wl": min(b[3] for b in w), "bt": by[T]}


def third(m, day: str, cid: str, p: dict):
    by = {b[0]: b for b in m.bars(day)}
    before = [d for d in m.sessions if d < day]

    if cid in ("repo_orr_outside_range", "repo_orr_edge_survived", "repo_orr_exhaustion"):
        T = p.get("decision_time", "11:30")
        s = _orr_parts(by, T, int(p.get("opening_range_minutes", 5)))
        if s is None or s["move"] is None or not "09:19" <= T <= "14:13":
            return None
        ct = s["bt"][4]
        if cid == "repo_orr_outside_range":
            if ct < s["orl"] and s["wh"] <= s["orh"] and s["move"] == "DOWN":
                return (T, "UP")
            if ct > s["orh"] and s["wl"] >= s["orl"] and s["move"] == "UP":
                return (T, "DOWN")
            return None
        side = "CE" if (s["wh"] <= s["orh"] and s["move"] == "DOWN") else \
               "PE" if (s["wl"] >= s["orl"] and s["move"] == "UP") else None
        if side is None:
            return None
        if cid == "repo_orr_edge_survived":
            return (T, "UP" if side == "CE" else "DOWN")
        cl = s["cl"]
        ch = np.diff(cl[-15:])
        gain, loss = ch[ch > 0].sum() / 14.0, -ch[ch < 0].sum() / 14.0
        rsi = 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)
        x = p["rsi_distance_from_50"]
        sd = float(np.std(cl))                              # population sd (ddof = 0)
        if sd == 0:
            return None
        if side == "CE":
            good = rsi <= 50 - x and (cl.mean() - ct) / sd >= p["sd_stretch_min"] and s["bt"][4] < s["bt"][1]
        else:
            good = rsi >= 50 + x and (ct - cl.mean()) / sd >= p["sd_stretch_min"] and s["bt"][4] > s["bt"][1]
        return (T, "UP" if side == "CE" else "DOWN") if good else None

    if cid == "repo_stretch_fade_1100":
        L = int(p["lookback_sessions"])
        trs = _tr_list(m, before, 14)
        if trs is None or len(before) < L or by.get("11:00") is None:
            return None
        adr = float(np.mean(trs))
        if adr == 0:
            return None
        st = (by["11:00"][4] - _daily(m, before[-L])[2]) / adr
        thr = p["stretch_threshold_adr"]
        return ("11:00", "DOWN") if st > thr else ("11:00", "UP") if st < -thr else None

    if cid == "repo_stretch_fade_line_reject":
        thr, last = p["stretch_threshold"], min(C.minutes(p["last_signal_time"]), C.minutes("14:13"))
        trs = _tr_list(m, before, 10)
        if trs is None or by.get("11:00") is None:
            return None
        R = float(np.mean(trs))
        if R == 0:
            return None
        c = by["11:00"][4]
        d10 = [_daily(m, d) for d in before[-10:]]
        s1 = (c - _daily(m, before[-5])[2]) / R
        s2 = (c - (max(x[0] for x in d10) + min(x[1] for x in d10)) / 2.0) / R
        if max(s1, s2) > thr and min(s1, s2) >= 0:
            put = True
        elif min(s1, s2) < -thr and max(s1, s2) <= 0:
            put = False
        else:
            return None

        def line(t_min):                                    # mean of the closes stamped 09:15 .. t
            return float(np.mean([by[C.hhmm(x)][4] for x in range(555, t_min + 1) if C.hhmm(x) in by]))

        u = None
        for t_min in range(C.minutes("11:01"), last + 1):
            b = by.get(C.hhmm(t_min))
            if b is not None and ((put and b[2] >= line(t_min)) or (not put and b[3] <= line(t_min))):
                u = t_min
                break
        if u is None:
            return None
        k = 0
        while True:                                         # 10-minute candles: last minutes 09:24, 09:34, ...
            mm = 555 + 10 * k + 9
            k += 1
            if mm < u:
                continue
            if mm > last:
                return None
            b = by.get(C.hhmm(mm))
            if b is None:
                continue
            ln = line(mm)
            if (put and b[4] < ln) or (not put and b[4] > ln):
                break
        # the most recent 15-minute candle (starts 09:15 + 15j) whose last minute is <= mm
        j = 0
        while 555 + 15 * (j + 1) + 14 <= mm:
            j += 1
        if 555 + 15 * j + 14 > mm:
            return None
        c15 = [by[C.hhmm(x)] for x in range(555 + 15 * j, 555 + 15 * j + 15) if C.hhmm(x) in by]
        mid = (max(x[2] for x in c15) + min(x[3] for x in c15)) / 2.0
        ok = b[4] < mid if put else b[4] > mid
        return (C.hhmm(mm), "DOWN" if put else "UP") if ok else None
    raise KeyError(cid)


# ---------------------------------------------------------------------------
def _parse(text: str):
    if ":" in text:
        return text
    return float(text) if "." in text else int(text)


def registry_check(P, S, lib) -> list:
    bad = []
    for cid in IDS:
        if cid not in P.CANDIDATES:
            bad.append(f"{cid}: missing from the primary")
            continue
        cp, cs, lp = P.CANDIDATES[cid], S.CANDIDATES[cid], lib[cid]["params"]
        names = [x["name"].split(" ")[0] for x in lp]
        if list(cp["centre"]) != names:
            bad.append(f"{cid}: primary centre keys {list(cp['centre'])} != library {names}")
        want = []
        for x, name in zip(lp, names):
            cv = _parse(x["centre"])
            if cp["centre"].get(name) != cv or type(cp["centre"].get(name)) is not type(cv):
                bad.append(f"{cid}: centre {name} = {cp['centre'].get(name)!r}, library {x['centre']!r}")
            for side in ("lower_neighbour", "upper_neighbour"):
                q = dict((n, _parse(y["centre"])) for y, n in zip(lp, names))
                q[name] = _parse(x[side])
                want.append((f"{name}={x[side]}", q))
        got = [(n["label"], n["params"]) for n in cp["neighbours"]]
        if got != want:
            bad.append(f"{cid}: primary neighbours {got} != library {want}")
        if cp["centre"] != cs["centre"]:
            bad.append(f"{cid}: centre differs primary {cp['centre']} / second {cs['centre']}")
        if [n["params"] for n in cp["neighbours"]] != [n["params"] for n in cs["neighbours"]]:
            bad.append(f"{cid}: neighbour params differ between primary and second (by position)")
    return bad


def main() -> int:
    P = _load(os.path.join(STUDY, "signals_repo_a.py"), "signals_repo_a")
    S = _load(os.path.join(HERE, "alt_repo_a.py"), "alt_repo_a")
    with open(os.path.join(STUDY, "library.json"), encoding="utf-8") as f:
        lib = {c["id"]: c for c in json.load(f)["candidates"]}

    print("== 1. registry ==")
    reg = registry_check(P, S, lib)
    print("  primary == library.json == second (ids, names, centres, neighbour values/labels/order): "
          + ("OK" if not reg else "PROBLEMS"))
    for x in reg:
        print("   ! " + x)

    n_dis2 = n_dis3 = 0
    la_problems, sweep_problems, struct_problems = [], [], []
    counts: dict = {}
    for index in C.INDEXES:
        m = C.Market(index)
        assert m.last_day == C.DISCOVERY_END and max(m.sessions) <= C.DISCOVERY_END
        days = [d for d in m.sessions if C.WINDOW_START <= d <= C.DISCOVERY_END]
        ctxs = {d: m.day_ctx(d) for d in days}
        cuts = [C.hhmm(x) for x in range(C.minutes("09:14"), C.minutes("14:14") + 1)]
        print(f"\n== 2. {index}: {len(days)} sessions {days[0]} .. {days[-1]} ==")
        for cid in IDS:
            cp, cs = P.CANDIDATES[cid], S.CANDIDATES[cid]
            cells_p = [("centre", cp["centre"])] + [(n["label"], n["params"]) for n in cp["neighbours"]]
            cells_s = [("centre", cs["centre"])] + [(n["label"], n["params"]) for n in cs["neighbours"]]
            for (label, pp), (_, ps) in zip(cells_p, cells_s):
                agree2 = agree3 = 0
                dis2, dis3, sig = [], [], []
                for d in days:
                    dc = ctxs[d]
                    rp = cp["fn"](dc, **pp)
                    rs = cs["fn"](dc, **ps)
                    rt = third(m, d, cid, pp)
                    rp_t = None if rp is None else tuple(rp)
                    if rp_t == (None if rs is None else tuple(rs)):
                        agree2 += 1
                    else:
                        dis2.append((d, rp, rs))
                    if rp_t == rt:
                        agree3 += 1
                    else:
                        dis3.append((d, rp, rt))
                    la_problems += [f"{cid} [{label}] {x}" for x in C.check_no_lookahead(cp["fn"], dc, pp)]
                    # every-minute sweep on the primary
                    seen = None
                    for cut in cuts:
                        r = cp["fn"](dc.truncated(cut), **pp)
                        if seen is None and r is not None:
                            seen = (cut, tuple(r))
                            if r[0] != cut:
                                sweep_problems.append(f"{index} {d} {cid} [{label}]: first answer {r} appears at cut {cut}")
                        elif seen is not None and (r is None or tuple(r) != seen[1]):
                            sweep_problems.append(f"{index} {d} {cid} [{label}]: answer changes from {seen[1]} to {r} at cut {cut}")
                    if (seen[1] if seen else None) != rp_t:
                        sweep_problems.append(f"{index} {d} {cid} [{label}]: sweep {seen} vs full day {rp}")
                    if rp is not None:
                        sig.append(rp)
                        t = rp[0]
                        if not "09:19" <= t <= "14:13" or rp[1] not in ("UP", "DOWN"):
                            struct_problems.append(f"{index} {d} {cid} [{label}]: {rp} outside the window / bad direction")
                        if cid.startswith("repo_orr") and t != pp.get("decision_time", "11:30"):
                            struct_problems.append(f"{index} {d} {cid} [{label}]: {rp} not at the decision minute")
                        if cid == "repo_stretch_fade_1100" and t != "11:00":
                            struct_problems.append(f"{index} {d} {cid} [{label}]: {rp} not at 11:00")
                        if cid == "repo_stretch_fade_line_reject" and not (
                                (C.minutes(t) - 555) % 10 == 9 and "11:04" <= t <= pp["last_signal_time"]):
                            struct_problems.append(f"{index} {d} {cid} [{label}]: {rp} not a 10-minute last minute in 11:04..last")
                n_dis2 += len(dis2)
                n_dis3 += len(dis3)
                ups = sum(1 for r in sig if r[1] == "UP")
                stamps = sorted(r[0] for r in sig)
                counts.setdefault(cid, {}).setdefault(label, {})[index] = {
                    "n": len(sig), "UP": ups, "DOWN": len(sig) - ups,
                    "first": stamps[0] if stamps else None, "last": stamps[-1] if stamps else None}
                print(f"  {cid:30s} {label:28s} compared {len(days)}  primary=second {agree2:3d} differ {len(dis2):2d}"
                      f"  | primary=third {agree3:3d} differ {len(dis3):2d}")
                for d, a, b in dis2:
                    print(f"      SECOND differs {d}: primary {a}  second {b}")
                for d, a, b in dis3:
                    print(f"      THIRD  differs {d}: primary {a}  third {b}")

    print("\n== 3. ctx.check_no_lookahead on the primary ==")
    print(f"  problems: {len(la_problems)}")
    for x in la_problems[:40]:
        print("   ! " + x)
    print("== 4. every-minute truncation sweep on the primary (09:14 .. 14:14) ==")
    print(f"  problems: {len(sweep_problems)}")
    for x in sweep_problems[:40]:
        print("   ! " + x)
    print("== 5. structure of the signals ==")
    print(f"  problems: {len(struct_problems)}")
    for x in struct_problems[:40]:
        print("   ! " + x)

    print("\n== 6. final signal counts of the primary: n (UP/DOWN) first..last signal minute ==")
    for cid in IDS:
        for label, per in counts[cid].items():
            cells = []
            for index in C.INDEXES:
                c = per[index]
                cells.append(f"{index} {c['n']:2d} ({c['UP']}/{c['DOWN']}) {c['first']}..{c['last']}")
            print(f"  {cid:30s} {label:28s} " + "   ".join(cells))

    total = len(reg) + n_dis2 + n_dis3 + len(la_problems) + len(sweep_problems) + len(struct_problems)
    print(f"\nSUMMARY: registry problems {len(reg)}, primary/second disagreements {n_dis2}, primary/third "
          f"disagreements {n_dis3}, look-ahead problems {len(la_problems)}, sweep problems {len(sweep_problems)}, "
          f"structure problems {len(struct_problems)}")
    print("ALL CLEAN" if total == 0 else "NOT CLEAN")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
