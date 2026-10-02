"""check/diff_trend.py - adjudication of the six "trend" candidates.

Compares, for both indexes, every discovery session (2026-01-01 .. 2026-04-30), the centre and every
neighbour (matched by position):
    PRIMARY   signals_trend.py          (the coding the study uses)
    SECOND    check/alt_trend.py        (the blind second coding)
    BYDEF     a third reading written here straight from the library text, in a different style
              (one from-scratch predicate per minute, no running state), used only as a tie-breaker /
              shared-misreading probe.

It also checks the primary's parameter cells against library.json, a few structural invariants of the
signal minutes, and runs ctx.check_no_lookahead on the primary for every cell.

ONLY signals are looked at (day, minute, direction, counts).  Nothing after a signal is read or computed:
no option candle is opened, no P&L, no forward move.  The date wall is ctx.Market's default (2026-04-30).
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
for p in (STUDY, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import ctx as C                      # noqa: E402
import signals_trend as PRI          # noqa: E402
import alt_trend as ALT              # noqa: E402

IDS = ("orb15_close_break", "pdhl_break_5m", "first_hour_close_location",
       "afternoon_new_extreme", "ema20_pullback_5m", "avgprice_cross_hold")
OPEN, FIRST, LAST = 555, 559, 853            # 09:15, 09:19, 14:13 (protocol P1.3)


# ---------------------------------------------------------------------------
# BYDEF: the text, minute by minute, from scratch (no running state)
# ---------------------------------------------------------------------------
def _by_minute(bars):
    return {C.minutes(b[0]): b for b in bars}


def def_orb(market, day, opening_range_minutes):
    n = opening_range_minutes
    bm = _by_minute(market.bars(day))
    rng = [bm[m] for m in range(OPEN, OPEN + n)]                 # "the first N 1-minute candles"
    orh, orl = max(b[2] for b in rng), min(b[3] for b in rng)
    for t in range(max(OPEN + n, FIRST), LAST + 1):              # "09:15+N <= t <= 14:29" -> 14:13
        c = bm[t][4]
        if c > orh:
            return (C.hhmm(t), "UP")
        if c < orl:
            return (C.hhmm(t), "DOWN")
    return None


def def_pdhl(market, day, confirmation_candle_minutes):
    b = confirmation_candle_minutes
    i = market.sessions.index(day)
    if i == 0:
        return None
    prev = [r for r in market.bars(market.sessions[i - 1]) if "09:15" <= r[0] <= "15:29"]
    pdh, pdl = max(r[2] for r in prev), min(r[3] for r in prev)
    bm = _by_minute(market.bars(day))
    k = 0
    while True:
        m = OPEN + k * b + b - 1                                 # last 1-minute bar of the k-th B-minute candle
        k += 1
        if m > LAST:
            return None
        if m < FIRST:
            continue
        c = bm[m][4]                                             # the candle's close = close of its last bar
        if c > pdh:
            return (C.hhmm(m), "UP")
        if c < pdl:
            return (C.hhmm(m), "DOWN")


def def_fhcl(market, day, window_minutes, outer_fraction_of_range):
    w, f = window_minutes, outer_fraction_of_range
    bm = _by_minute(market.bars(day))
    t = OPEN + w - 1
    if not FIRST <= t <= LAST:
        return None
    win = [bm[m] for m in range(OPEN, t + 1)]
    h1, l1, c1 = max(r[2] for r in win), min(r[3] for r in win), bm[t][4]
    if h1 == l1:
        return None
    p = (c1 - l1) / (h1 - l1)
    if p >= 1 - f:
        return (C.hhmm(t), "UP")
    if p <= f:
        return (C.hhmm(t), "DOWN")
    return None


def def_ane(market, day, scan_start_time):
    bars = market.bars(day)
    s = C.minutes(scan_start_time)
    for t in range(max(s, FIRST), LAST + 1):
        before = [r for r in bars if OPEN <= C.minutes(r[0]) <= t - 1]   # "all candles stamped 09:15..t-1"
        cur = [r for r in bars if C.minutes(r[0]) == t][0]
        if cur[4] > max(r[2] for r in before):
            return (C.hhmm(t), "UP")
        if cur[4] < min(r[3] for r in before):
            return (C.hhmm(t), "DOWN")
    return None


_SERIES: dict = {}        # (index, period) -> flat list of (day, last minute, high, low, close, E) over ALL sessions <= wall


def _series(market, period):
    key = (market.index, period)
    if key not in _SERIES:
        alpha = 2.0 / (period + 1)
        out, e = [], None
        for d in market.sessions:                               # "one continuous series from 2025-11-24"
            bars = market.bars(d)
            for g in range(len(bars) // 5):
                grp = bars[g * 5:(g + 1) * 5]
                assert C.minutes(grp[0][0]) == OPEN + g * 5 and C.minutes(grp[-1][0]) == OPEN + g * 5 + 4
                close = grp[-1][4]
                e = close if e is None else alpha * close + (1 - alpha) * e     # causal: E(k) never sees later candles
                out.append((d, OPEN + g * 5 + 4, max(r[2] for r in grp), min(r[3] for r in grp), close, e))
        _SERIES[key] = out
    return _SERIES[key]


def def_ema(market, day, ema_period, clean_run_candles):
    q = clean_run_candles
    ser = _series(market, ema_period)
    for k, (d, m, high, low, close, e) in enumerate(ser):
        if d != day or m > LAST or m < FIRST:
            continue
        if k < q:
            continue
        run = ser[k - q:k]
        if any(r[0] != day for r in run):                       # "(k-Q..k-1) belongs to TODAY"
            continue
        if all(r[3] > r[5] for r in run) and low <= e and close > e:
            return (C.hhmm(m), "UP")
        if all(r[2] < r[5] for r in run) and high >= e and close < e:
            return (C.hhmm(m), "DOWN")
    return None


def def_apch(market, day, hold_minutes, exclude_first_minutes):
    h, x = hold_minutes, exclude_first_minutes
    bars = market.bars(day)
    tp = [(r[2] + r[3] + r[4]) / 3.0 for r in bars]
    assert all(C.minutes(r[0]) == OPEN + i for i, r in enumerate(bars))

    def side(t):                                                # from scratch for every t
        i = t - OPEN
        a = sum(tp[:i + 1]) / (i + 1)
        c = bars[i][4]
        return 1 if c > a else (-1 if c < a else 0)

    for t in range(FIRST, LAST + 1):
        if t - h < OPEN + x - 1:                                # "candle t-H is stamped at or after 09:15 + X - 1"
            continue
        s = side(t)
        if s == 0:
            continue
        if all(side(u) == s for u in range(t - h + 1, t + 1)) and side(t - h) != s:
            return (C.hhmm(t), "UP" if s == 1 else "DOWN")
    return None


BYDEF = {"orb15_close_break": def_orb, "pdhl_break_5m": def_pdhl, "first_hour_close_location": def_fhcl,
         "afternoon_new_extreme": def_ane, "ema20_pullback_5m": def_ema, "avgprice_cross_hold": def_apch}


# ---------------------------------------------------------------------------
# library cells, parsed here independently of both modules
# ---------------------------------------------------------------------------
def _parse(text):
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def library_cells():
    with open(os.path.join(STUDY, "library.json"), encoding="utf-8") as f:
        lib = {c["id"]: c for c in json.load(f)["candidates"]}
    out = {}
    for cid in IDS:
        params = lib[cid]["params"]
        centre = {p["name"]: _parse(p["centre"]) for p in params}
        cells = [("centre", centre)]
        for p in params:
            for side in ("lower_neighbour", "upper_neighbour"):
                moved = dict(centre)
                moved[p["name"]] = _parse(p[side])
                cells.append((f"{p['name']}={p[side]}", moved))
        out[cid] = cells
    return out


def structural_problem(cid, params, r):
    """Alignment / window invariants a signal minute must satisfy whatever the day."""
    if r is None:
        return None
    t, direction = r
    m = C.minutes(t)
    if direction not in ("UP", "DOWN"):
        return f"direction {direction!r}"
    if not FIRST <= m <= LAST:
        return f"{t} outside 09:19..14:13"
    if cid == "orb15_close_break" and m < OPEN + params["opening_range_minutes"]:
        return f"{t} inside the opening range"
    if cid == "pdhl_break_5m" and (m - OPEN) % params["confirmation_candle_minutes"] != params["confirmation_candle_minutes"] - 1:
        return f"{t} is not the last bar of a 09:15-aligned candle"
    if cid == "first_hour_close_location" and m != OPEN + params["window_minutes"] - 1:
        return f"{t} is not the window's last candle"
    if cid == "afternoon_new_extreme" and m < C.minutes(params["scan_start_time"]):
        return f"{t} before the scan start"
    if cid == "ema20_pullback_5m" and ((m - OPEN) % 5 != 4 or m < OPEN + 5 * params["clean_run_candles"] + 4):
        return f"{t} is not a 5-minute candle end with Q earlier candles of today"
    if cid == "avgprice_cross_hold" and m < OPEN + params["exclude_first_minutes"] - 1 + params["hold_minutes"]:
        return f"{t} earlier than 09:15 + X - 1 + H"
    return None


def main():
    lib = library_cells()
    markets = {ix: C.Market(ix) for ix in C.INDEXES}            # default wall = 2026-04-30
    for ix, m in markets.items():
        assert m.last_day == C.DISCOVERY_END and max(m.sessions) <= C.DISCOVERY_END
        assert m.sessions[0] == C.WARMUP_START
    days = {ix: [d for d in m.sessions if C.WINDOW_START <= d <= C.DISCOVERY_END] for ix, m in markets.items()}

    # ---- 0. parameter cells of both modules against library.json ----
    print("== parameter cells against library.json ==")
    cell_problems = []
    for cid in IDS:
        for name, mod in (("PRIMARY", PRI), ("SECOND", ALT)):
            cand = mod.CANDIDATES[cid]
            got = [("centre", cand["centre"])] + [(nb["label"], nb["params"]) for nb in cand["neighbours"]]
            if got != lib[cid]:
                cell_problems.append(f"{name} {cid}: cells {got} != library {lib[cid]}")
    extra = sorted(set(PRI.CANDIDATES) ^ set(IDS))
    if extra:
        cell_problems.append(f"PRIMARY ids differ from the six: {extra}")
    print(f"  problems: {len(cell_problems)}")
    for p in cell_problems:
        print("   " + p)

    # ---- 1. the diff ----
    print("\n== PRIMARY vs SECOND (and BYDEF), per cell and index ==")
    total_dis = total_def_dis = total_struct = 0
    lookahead = []
    counts = {}
    for cid in IDS:
        print(f"\n-- {cid} --")
        for pos, (label, params) in enumerate(lib[cid]):
            pc, ac = PRI.CANDIDATES[cid], ALT.CANDIDATES[cid]
            p_params = pc["centre"] if pos == 0 else pc["neighbours"][pos - 1]["params"]
            a_params = ac["centre"] if pos == 0 else ac["neighbours"][pos - 1]["params"]
            for ix, m in markets.items():
                agree = 0
                dis, def_dis, struct = [], [], []
                sig = []
                for d in days[ix]:
                    dc = m.day_ctx(d)
                    rp = pc["fn"](dc, **p_params)
                    ra = ac["fn"](m.day_ctx(d), **a_params)
                    rd = BYDEF[cid](m, d, **params)
                    rp_t = None if rp is None else tuple(rp)
                    ra_t = None if ra is None else tuple(ra)
                    if rp_t == ra_t:
                        agree += 1
                    else:
                        dis.append((d, rp_t, ra_t, rd))
                    if rp_t != rd:
                        def_dis.append((d, rp_t, rd))
                    sp = structural_problem(cid, params, rp_t)
                    if sp:
                        struct.append((d, sp))
                    if rp_t is not None:
                        sig.append(rp_t)
                    # ---- 4. the mechanical look-ahead check on the primary ----
                    try:
                        lookahead += [f"{cid} [{label}] {x}" for x in C.check_no_lookahead(pc["fn"], dc, p_params)]
                    except Exception as e:                       # noqa: BLE001 - reported, not hidden
                        lookahead.append(f"{cid} [{label}] {ix} {d}: raised {type(e).__name__}: {e}")
                total_dis += len(dis)
                total_def_dis += len(def_dis)
                total_struct += len(struct)
                up = sum(1 for _t, s in sig if s == "UP")
                ts = sorted(t for t, _s in sig)
                counts[(cid, label, ix)] = {"sessions": len(days[ix]), "signals": len(sig), "up": up,
                                            "down": len(sig) - up, "earliest": ts[0] if ts else None,
                                            "latest": ts[-1] if ts else None}
                print(f"  {label:<34} {ix:<6} compared {len(days[ix])}  agree {agree}  disagree {len(dis)}"
                      f"  | vs by-definition: differ {len(def_dis)}  structural {len(struct)}"
                      f"  | signals {len(sig)} (UP {up} / DOWN {len(sig) - up}) {ts[0] if ts else '-'}..{ts[-1] if ts else '-'}")
                for d, rp_t, ra_t, rd in dis:
                    print(f"      DISAGREE {d}: primary {rp_t}  second {ra_t}  by-definition {rd}")
                for d, rp_t, rd in def_dis:
                    print(f"      BYDEF    {d}: primary {rp_t}  by-definition {rd}")
                for d, sp in struct:
                    print(f"      STRUCT   {d}: {sp}")

    # ---- 5. robustness of the primary: any cutoff, and days it cannot evaluate ----
    # A day cut at ANY minute c must give None when c is before the full-day signal minute and the same
    # signal when c is at or after it (check_no_lookahead only tries t and t-1).  Cutoffs every 7 minutes
    # from 09:14 to 14:20, plus the day's edges.  Only the function's own output is compared.
    print("\n== primary on a day cut at any minute, and on days it cannot evaluate ==")
    prefix_bad, raised = [], []
    cuts = sorted({C.hhmm(x) for x in range(OPEN - 1, 14 * 60 + 21, 7)} | {"09:15", "09:19", "14:13", "14:14", "15:29"})
    n_calls = 0
    for cid in IDS:
        pc = PRI.CANDIDATES[cid]
        for pos, (label, _params) in enumerate(lib[cid]):
            p_params = pc["centre"] if pos == 0 else pc["neighbours"][pos - 1]["params"]
            for ix, m in markets.items():
                for d in days[ix]:
                    dc = m.day_ctx(d)
                    full = pc["fn"](dc, **p_params)
                    for c in cuts:
                        n_calls += 1
                        try:
                            got = pc["fn"](dc.truncated(c), **p_params)
                        except Exception as e:                   # noqa: BLE001
                            raised.append(f"{cid} [{label}] {ix} {d} cut {c}: {type(e).__name__}: {e}")
                            continue
                        want = full if (full is not None and c >= full[0]) else None
                        if got != want:
                            prefix_bad.append(f"{cid} [{label}] {ix} {d} cut {c}: {got} != {want}")
                # warm-up sessions, including the very first one on disk (no previous session)
                for d in m.sessions[:3]:
                    try:
                        r = pc["fn"](m.day_ctx(d), **p_params)
                        if r is not None and structural_problem(cid, _params, tuple(r)):
                            raised.append(f"{cid} [{label}] {ix} {d}: structural problem on a warm-up day")
                    except Exception as e:                       # noqa: BLE001
                        raised.append(f"{cid} [{label}] {ix} {d}: {type(e).__name__}: {e}")
    print(f"  calls on cut days: {n_calls} ({len(cuts)} cutoffs)  inconsistent: {len(prefix_bad)}  raised: {len(raised)}")
    for p in (prefix_bad + raised)[:40]:
        print("   " + p)
    lookahead += prefix_bad + raised

    print("\n== totals ==")
    print(f"  cells x indexes x sessions compared: {sum(c['sessions'] for c in counts.values())}")
    print(f"  PRIMARY vs SECOND disagreements: {total_dis}")
    print(f"  PRIMARY vs by-definition differences: {total_def_dis}")
    print(f"  structural problems: {total_struct}")
    print(f"  parameter-cell problems: {len(cell_problems)}")
    print(f"  check_no_lookahead problems on the primary: {len(lookahead)}")
    for p in lookahead[:40]:
        print("   " + p)
    for ix, m in markets.items():
        print(f"  {ix}: sessions {days[ix][0]}..{days[ix][-1]} ({len(days[ix])}), latest index candle held {max(m.sessions)}")

    os.makedirs(C.OUTPUT_DIR, exist_ok=True)
    out = os.path.join(C.OUTPUT_DIR, "check_diff_trend.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"disagreements": total_dis, "by_definition_differences": total_def_dis,
                   "structural_problems": total_struct, "cell_problems": cell_problems,
                   "lookahead_problems": lookahead,
                   "counts": [{"candidate": k[0], "cell": k[1], "index": k[2], **v} for k, v in counts.items()]},
                  f, indent=1)
    print(f"  written {out}")
    return 1 if (total_dis or total_def_dis or total_struct or cell_problems or lookahead) else 0


if __name__ == "__main__":
    sys.exit(main())
