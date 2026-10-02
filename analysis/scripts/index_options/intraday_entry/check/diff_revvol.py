"""check/diff_revvol.py - adjudication of the seven mean-reversion / volatility candidates.

Three things, on discovery sessions only (2026-01-01 .. 2026-04-30), both indexes, the centre and every
neighbour (matched by position):

  1. DIFF      primary signals_revvol.py  vs  second coding check/alt_revvol.py  (None or (t, direction)).
  2. WITNESS   a third, brute-force reading of each rule written here from library.json: every level and
               every candle of the whole day is computed first, then the rule's "first" is picked.  It is
               compared with the primary.  (Two codings can share a misreading; this one is written in a
               different shape - array positions instead of scans.)
  3. LOOKAHEAD ctx.check_no_lookahead on the primary, every variant, every session.

Only signals are looked at (day, minute, direction, counts).  Nothing that happened after a signal is
computed: no price after t is read for any purpose other than deciding whether a LATER candle would have
been the signal, and no P&L, forward move or option price exists anywhere in this file.

Run:  python check/diff_revvol.py
"""
from __future__ import annotations

import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
for p in (STUDY, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import ctx as ctxmod                       # noqa: E402
from ctx import hhmm                       # noqa: E402
import signals_revvol as primary           # noqa: E402
import alt_revvol as second                # noqa: E402

IDS = ["mr_session_mean_band_fade", "mr_opening_range_failed_breakout", "mr_prev_day_extreme_sweep",
       "mr_rsi14_exhaustion_recross", "vol_narrow_ib_extension", "vol_wide_range_bar_follow",
       "vol_lunch_lull_break"]

O = 555          # 09:15
LAST = 853       # 14:13 (protocol P1.3)


# ---------------------------------------------------------------------------
# the witness: brute force on a full 375-bar day; bar i is the minute 09:15 + i
# ---------------------------------------------------------------------------
def _c5(bars):
    """75 five-minute candles: (last minute, o, h, l, c); candle k covers bars 5k..5k+4."""
    assert len(bars) == 375 and bars[0][0] == "09:15" and bars[-1][0] == "15:29"
    return [(O + 5 * k + 4, bars[5 * k][1], max(b[2] for b in bars[5 * k:5 * k + 5]),
             min(b[3] for b in bars[5 * k:5 * k + 5]), bars[5 * k + 4][4]) for k in range(75)]


def w_band(m, day, K_band_width_sd, WARM_minutes):
    bars = m.bars(day)
    hits = []
    for t in range(O + 4, 24 * 60, 5):                      # 09:19, 09:24, ...
        if not (O + WARM_minutes - 1 <= t <= LAST):
            continue
        cl = [b[4] for b in bars[:t - O + 1]]
        mean, sd = statistics.fmean(cl), statistics.pstdev(cl)
        if sd == 0:
            continue
        if cl[-1] >= mean + K_band_width_sd * sd:
            hits.append((t, "DOWN"))
        elif cl[-1] <= mean - K_band_width_sd * sd:
            hits.append((t, "UP"))
    return min(hits) if hits else None


def w_orfb(m, day, N_opening_range_minutes, W_failure_window_minutes):
    N, W = N_opening_range_minutes, W_failure_window_minutes
    bars = m.bars(day)
    orh, orl = max(b[2] for b in bars[:N]), min(b[3] for b in bars[:N])
    cs = [c for c in _c5(bars) if c[0] - 4 >= O + N]
    out = []
    ups = [c[0] for c in cs if c[4] > orh]
    if ups:
        f = [c[0] for c in cs if ups[0] < c[0] <= ups[0] + W and c[4] < orh]
        if f:
            out.append((f[0], "DOWN"))
    dns = [c[0] for c in cs if c[4] < orl]
    if dns:
        f = [c[0] for c in cs if dns[0] < c[0] <= dns[0] + W and c[4] > orl]
        if f:
            out.append((f[0], "UP"))
    out = [x for x in out if x[0] <= LAST]
    if len(out) == 2 and out[0][0] == out[1][0]:
        return ("TIE", out[0][0])
    return min(out) if out else None


def w_sweep(m, day, W_reclaim_window_minutes):
    W = W_reclaim_window_minutes
    i = m.sessions.index(day)
    if i == 0:
        return None
    prev = m.bars(m.sessions[i - 1])
    pdh, pdl = max(b[2] for b in prev), min(b[3] for b in prev)
    bars = m.bars(day)
    cs = _c5(bars)
    out = []
    br = [O + k for k, b in enumerate(bars) if b[2] > pdh]
    if br:
        s = [c[0] for c in cs if br[0] <= c[0] <= br[0] + W and c[4] < pdh]
        if s:
            out.append((s[0], "DOWN"))
    br = [O + k for k, b in enumerate(bars) if b[3] < pdl]
    if br:
        s = [c[0] for c in cs if br[0] <= c[0] <= br[0] + W and c[4] > pdl]
        if s:
            out.append((s[0], "UP"))
    out = [x for x in out if O + 4 <= x[0] <= LAST]
    if len(out) == 2 and out[0][0] == out[1][0]:
        return ("TIE", out[0][0])
    return min(out) if out else None


def w_rsi(m, day, P_rsi_period, D_level_distance_from_50):
    P, D = P_rsi_period, D_level_distance_from_50
    cs = _c5(m.bars(day))
    d = [cs[k][4] - cs[k - 1][4] for k in range(1, 75)]            # d[j] belongs to candle j+1 (0-based)
    gain = [max(x, 0.0) for x in d]
    loss = [max(-x, 0.0) for x in d]
    rsi = {}                                                        # 0-based candle -> RSI
    ag, al = sum(gain[:P]) / P, sum(loss[:P]) / P                   # at candle P (0-based) = number P+1
    rsi[P] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for k in range(P + 1, 75):
        ag = (ag * (P - 1) + gain[k - 1]) / P
        al = (al * (P - 1) + loss[k - 1]) / P
        rsi[k] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    hits = []
    for k in range(P + 1, 75):
        t = cs[k][0]
        if t > LAST:
            continue
        if rsi[k] < 50 + D and rsi[k - 1] >= 50 + D:
            hits.append((t, "DOWN"))
        elif rsi[k] > 50 - D and rsi[k - 1] <= 50 - D:
            hits.append((t, "UP"))
    return min(hits) if hits else None


def w_ib(m, day, M_initial_balance_minutes, K_width_vs_20_session_average):
    M, K = M_initial_balance_minutes, K_width_vs_20_session_average
    i = m.sessions.index(day)
    if i < 20:
        return None

    def width(d):
        b = m.bars(d)[:M]
        return max(x[2] for x in b) - min(x[3] for x in b)

    avg = statistics.fmean(width(d) for d in m.sessions[i - 20:i])
    bars = m.bars(day)
    ibh, ibl = max(b[2] for b in bars[:M]), min(b[3] for b in bars[:M])
    if not (ibh - ibl) < K * avg:
        return None
    hits = [(c[0], "UP" if c[4] > ibh else "DOWN") for c in _c5(bars)
            if c[0] - 4 >= O + M and c[0] <= LAST and (c[4] > ibh or c[4] < ibl)]
    return min(hits) if hits else None


def w_wrb(m, day, X_range_multiple, N_average_candles):
    X, N = X_range_multiple, N_average_candles
    i = m.sessions.index(day)
    series = []                                                     # (day, candle) continuous
    for d in m.sessions[max(0, i - 2):i + 1]:
        series += [(d, c) for c in _c5(m.bars(d))]
    hits = []
    for j, (d, c) in enumerate(series):
        if d != day or not (O + 19 <= c[0] <= LAST) or j < N:
            continue
        avg = statistics.fmean(x[2] - x[3] for _, x in series[j - N:j])
        t, o, h, l, cl = c
        if h - l >= X * avg:
            if cl > o and cl > (h + l) / 2:
                hits.append((t, "UP"))
            elif cl < o and cl < (h + l) / 2:
                hits.append((t, "DOWN"))
    return min(hits) if hits else None


def w_lull(m, day, T1_lull_start, T2_lull_end):
    t1, t2 = ctxmod.minutes(T1_lull_start), ctxmod.minutes(T2_lull_end)
    bars = m.bars(day)
    win = bars[t1 - O:t2 - O]
    assert win[0][0] == T1_lull_start and len(win) == t2 - t1
    lh, ll = max(b[2] for b in win), min(b[3] for b in win)
    hits = [(c[0], "UP" if c[4] > lh else "DOWN") for c in _c5(bars)
            if c[0] - 4 >= t2 and c[0] <= LAST and (c[4] > lh or c[4] < ll)]
    return min(hits) if hits else None


WITNESS = dict(zip(IDS, [w_band, w_orfb, w_sweep, w_rsi, w_ib, w_wrb, w_lull]))


def _norm(r):
    return None if r is None else (r[0], r[1])


def _wnorm(r):
    if r is None:
        return None
    if r[0] == "TIE":
        return ("TIE", hhmm(r[1]))
    return (hhmm(r[0]), r[1])


def main() -> int:
    markets = {ix: ctxmod.Market(ix) for ix in ctxmod.INDEXES}        # default wall: 2026-04-30
    days = {ix: [d for d in m.sessions if ctxmod.WINDOW_START <= d <= ctxmod.DISCOVERY_END]
            for ix, m in markets.items()}
    ctxs = {ix: [markets[ix].day_ctx(d) for d in days[ix]] for ix in markets}
    for ix in markets:
        assert max(days[ix]) <= ctxmod.DISCOVERY_END
        print(f"{ix}: {len(days[ix])} sessions {days[ix][0]} .. {days[ix][-1]}")

    # the registries must describe the same variants
    reg_problems = []
    for cid in IDS:
        a, b = primary.CANDIDATES[cid], second.CANDIDATES[cid]
        if a["centre"] != b["centre"]:
            reg_problems.append(f"{cid}: centre differs {a['centre']} vs {b['centre']}")
        if len(a["neighbours"]) != len(b["neighbours"]):
            reg_problems.append(f"{cid}: neighbour count {len(a['neighbours'])} vs {len(b['neighbours'])}")
        for na, nb in zip(a["neighbours"], b["neighbours"]):
            if na["label"] != nb["label"] or na["params"] != nb["params"]:
                reg_problems.append(f"{cid}: neighbour {na} vs {nb}")
            moved = [k for k in a["centre"] if na["params"][k] != a["centre"][k]]
            if len(moved) != 1 or set(na["params"]) != set(a["centre"]):
                reg_problems.append(f"{cid}: neighbour {na['label']} does not move exactly one value")
    print(f"registry problems: {len(reg_problems)}")
    for x in reg_problems:
        print("  " + x)

    tot_dis = tot_wit = tot_look = tot_ties = 0
    counts = {}
    for cid in IDS:
        a, b = primary.CANDIDATES[cid], second.CANDIDATES[cid]
        cells = [("centre", a["centre"], b["centre"])] + \
                [(na["label"], na["params"], nb["params"]) for na, nb in zip(a["neighbours"], b["neighbours"])]
        print(f"\n{cid}")
        for label, pa, pb in cells:
            for ix in markets:
                m = markets[ix]
                agree, dis, wit, look, ties = 0, [], [], [], 0
                sig = []
                for cx in ctxs[ix]:
                    ra = _norm(a["fn"](cx, **pa))
                    try:
                        rb = _norm(b["fn"](cx, **pb))
                    except Exception as e:                           # noqa: BLE001
                        rb = ("raised", f"{type(e).__name__}: {e}")
                    if ra == rb:
                        agree += 1
                    else:
                        dis.append((cx.day, ra, rb))
                    rw = _wnorm(WITNESS[cid](m, cx.day, **pa))
                    if rw is not None and rw[0] == "TIE":
                        ties += 1
                        wit.append((cx.day, ra, rw))                 # always shown: the text gives no direction
                    elif rw != ra:
                        wit.append((cx.day, ra, rw))
                    look += ctxmod.check_no_lookahead(a["fn"], cx, pa)
                    if ra is not None:
                        sig.append(ra)
                up = sum(1 for s in sig if s[1] == "UP")
                ts = sorted(s[0] for s in sig)
                counts[(cid, label, ix)] = (len(sig), up, len(sig) - up, ts[0] if ts else "-", ts[-1] if ts else "-")
                print(f"  {label:<36} {ix:<6} compared={len(ctxs[ix])} agree={agree} disagree={len(dis)} "
                      f"| witness_diff={len(wit)} ties={ties} lookahead={len(look)} "
                      f"| n={len(sig)} UP={up} DOWN={len(sig) - up} first={ts[0] if ts else '-'} last={ts[-1] if ts else '-'}")
                for d, ra, rb in dis:
                    print(f"      DISAGREE {d}: primary={ra} second={rb}")
                for d, ra, rw in wit:
                    print(f"      WITNESS  {d}: primary={ra} witness={rw}")
                for x in look[:5]:
                    print(f"      LOOKAHEAD {x}")
                tot_dis += len(dis)
                tot_wit += len(wit)
                tot_look += len(look)
                tot_ties += ties
    print(f"\nTOTAL primary-vs-second disagreements: {tot_dis}")
    print(f"TOTAL primary-vs-witness differences:  {tot_wit} (of which same-candle ties: {tot_ties})")
    print(f"TOTAL look-ahead problems (primary):   {tot_look}")
    print(f"wall: " + ", ".join(f"{ix} latest index day {markets[ix].max_dates()['index']}" for ix in markets))
    return 1 if (tot_dis or tot_wit or tot_look or reg_problems) else 0


if __name__ == "__main__":
    sys.exit(main())
