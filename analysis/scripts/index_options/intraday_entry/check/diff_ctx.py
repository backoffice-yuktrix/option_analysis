"""check/diff_ctx.py - compare the PRIMARY coding (signals_ctx.py) with the blind SECOND coding
(check/alt_ctx.py) of: vol_vix_confirmed_or_break, gap_fail_through_pc, spx_cue_confirmed,
atm_oi_writer_skew.

For both indexes, every discovery session 2026-01-01..2026-04-30, the centre and every neighbour
(matched by position): the two outputs (None or (t, direction)) are compared.

It also runs, on the PRIMARY only:
  * ctx.check_no_lookahead for every variant on every session,
  * structural checks of the outputs (signal minute where the text puts it, window 09:19..14:13),
  * signal-side facts that back the recorded ambiguities (is every strike of the atm_oi strike set a
    LISTED strike, does the "nearest listed strike" equal the nearest multiple of the step, are the
    index / VIX sessions complete, why did a day give no atm_oi signal).

Only signals are looked at (day, minute, direction, counts).  Nothing after a signal is computed:
no option price, no forward index move, no profit or loss.  The date wall is Market's default
(2026-04-30).

    D:/YUKTRIX/option_analysis/analysis/.venv/Scripts/python.exe check/diff_ctx.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
sys.path.insert(0, STUDY)
sys.path.insert(0, HERE)

import ctx as C            # noqa: E402
import signals_ctx as P    # noqa: E402  the primary
import alt_ctx as A        # noqa: E402  the blind second coding

IDS = ("vol_vix_confirmed_or_break", "gap_fail_through_pc", "spx_cue_confirmed", "atm_oi_writer_skew")


def cells(cand: dict) -> list:
    return [("centre", cand["centre"])] + [(n["label"], n["params"]) for n in cand["neighbours"]]


def norm(sig):
    return None if sig is None else (sig[0], sig[1])


def expected_minutes(cid: str, params: dict):
    """The set of signal minutes the frozen text allows for this variant (None = any minute in a range)."""
    if cid == "vol_vix_confirmed_or_break":
        lo = max(555 + params["R_opening_range_minutes"], 559)
        return {C.hhmm(m) for m in range(lo, 853 + 1)}
    if cid == "gap_fail_through_pc":
        b = params["bar_minutes"]
        return {C.hhmm(m) for m in range(555 + b - 1, 853 + 1, b) if m >= 559}
    if cid == "spx_cue_confirmed":
        return {C.hhmm(555 + params["confirm_minutes"] - 1)}
    if cid == "atm_oi_writer_skew":
        return {C.hhmm(555 + params["eval_minutes"] - 1)}
    raise KeyError(cid)


def oi_reason(market, dc, V: int, J: int) -> str:
    """Why atm_oi_writer_skew gives / does not give a signal on this day - a plain third reading of the
    text + Addendum 2 + P1.8, used only to tally reasons and to cross-check the primary."""
    step = market.step
    T = 555 + V - 1
    by = {r[0]: r for r in dc.bars}
    c0 = by["09:15"][4]
    lower = (c0 // step) * step
    k0 = lower if c0 - lower <= lower + step - c0 else lower + step
    strikes = [k0 + j * step for j in range(-J, J + 1)]
    atm_t = float(round(by[C.hhmm(T)][4] / step) * step)
    if any(abs(k - atm_t) > 5 * step for k in strikes):
        return "P1.8 band (a strike of S is more than 5 steps from ATM at T)"
    d = 0
    for sign, ot in ((+1, "PE"), (-1, "CE")):
        for k in strikes:
            rows = market.option_bars(dc.day, ot, k)
            if rows is None:
                return "no option file / no rows that day"
            m = {r[0]: r for r in rows}
            base = m.get("09:20")
            if base is None:
                return "no 09:20 option candle"
            late = None
            for mm in range(T - 3, 560 - 1, -1):
                late = m.get(C.hhmm(mm))
                if late is not None:
                    break
            if late is None:
                return "no option candle in 09:20..T-3"
            if base[6] == 0 or late[6] == 0:
                return "zero open interest at a reading"
            d += sign * (late[6] - base[6])
    return "UP" if d > 0 else "DOWN" if d < 0 else "D = 0"


def main() -> int:
    assert tuple(P.CANDIDATES) == IDS and tuple(A.CANDIDATES) == IDS, "candidate ids / order differ"
    total_diff = 0
    total_la = 0
    total_struct = 0
    counts: dict = {}
    for index in C.INDEXES:
        market = C.Market(index)                       # the date wall = 2026-04-30
        assert market.last_day == C.DISCOVERY_END
        days = [d for d in market.sessions if C.WINDOW_START <= d <= C.DISCOVERY_END]
        assert days and max(days) <= C.DISCOVERY_END
        print(f"\n================ {index}: {len(days)} sessions {days[0]} .. {days[-1]} ================")

        # ---- data facts behind the "never happens on disk" notes ----
        short_idx = [d for d in market.sessions if len(market.bars(d)) != 375]
        vix_short = [d for d in market.sessions if len(market.vix_bars(d)) != 375]
        vix_no_close_window = [d for d in market.sessions
                               if not any("15:00" <= r[0] <= "15:29" for r in market.vix_bars(d))]
        vix_no_0920 = [d for d in days if not any(r[0] == "09:20" for r in market.vix_bars(d))]
        print(f"  index sessions not 375 bars: {short_idx or 'none'};  VIX sessions not 375 bars: {vix_short or 'none'};  "
              f"VIX sessions with no 15:00..15:29 candle: {vix_no_close_window or 'none'};  "
              f"discovery days with no 09:20 VIX candle: {vix_no_0920 or 'none'}")

        for cid in IDS:
            pc, ac = P.CANDIDATES[cid], A.CANDIDATES[cid]
            pcells, acells = cells(pc), cells(ac)
            assert len(pcells) == len(acells), f"{cid}: different number of variants"
            for (plabel, pparams), (alabel, aparams) in zip(pcells, acells):
                if plabel != alabel or pparams != aparams:
                    print(f"  NOTE {cid}: variant mismatch primary {plabel} {pparams} vs second {alabel} {aparams}")
                allowed = expected_minutes(cid, pparams)
                agree = 0
                diffs = []
                la = []
                struct = []
                up = down = 0
                stamps = []
                for d in days:
                    dc = market.day_ctx(d)
                    ps = norm(pc["fn"](dc, **pparams))
                    as_ = norm(ac["fn"](market.day_ctx(d), **aparams))
                    if ps == as_:
                        agree += 1
                    else:
                        diffs.append((d, ps, as_))
                    la += C.check_no_lookahead(pc["fn"], market.day_ctx(d), pparams)
                    if ps is not None:
                        t, direction = ps
                        stamps.append(t)
                        up += direction == "UP"
                        down += direction == "DOWN"
                        if t not in allowed or not "09:19" <= t <= "14:13" or direction not in ("UP", "DOWN"):
                            struct.append(f"{d}: {ps} is not a minute the text allows")
                n = up + down
                span = (min(stamps) if len(set(stamps)) == 1 else f"{min(stamps)}..{max(stamps)}") if stamps else "-"
                counts[(cid, plabel, index)] = (n, up, down, span)
                print(f"  {cid:27s} {plabel:27s} compared {len(days)}  agree {agree}  disagree {len(diffs)}  | "
                      f"primary n={n} UP {up} DOWN {down} minutes {span} | look-ahead problems {len(la)}  "
                      f"structure problems {len(struct)}")
                for d, ps, as_ in diffs:
                    print(f"      DIFF {d}: primary {ps}   second {as_}")
                for p in la[:10]:
                    print(f"      LOOKAHEAD {p}")
                for p in struct[:10]:
                    print(f"      STRUCTURE {p}")
                total_diff += len(diffs)
                total_la += len(la)
                total_struct += len(struct)

        # ---- atm_oi_writer_skew: "listed strike" against the contract list, and the reasons ----
        listed_by_exp: dict = {}
        for (exp, ot, strike) in market._lots:           # the contract list (no candle is read here)
            listed_by_exp.setdefault((exp, ot), set()).add(strike)
        not_listed = 0
        k0_differs = 0
        neighbours_differ = 0
        ties = 0
        for d in days:
            dc = market.day_ctx(d)
            c0 = dc.bars[0][4]
            assert dc.bars[0][0] == "09:15"
            step = market.step
            lower = (c0 // step) * step
            k0 = lower if c0 - lower <= lower + step - c0 else lower + step
            ties += (c0 - lower) == (lower + step - c0)
            for ot in ("CE", "PE"):
                listed = sorted(listed_by_exp.get((dc.expiry, ot), ()))
                best = min(listed, key=lambda s: (abs(s - c0), s)) if listed else None   # nearest, tie -> lower
                k0_differs += best != k0
                if best is not None:
                    i = listed.index(best)
                    for j in (1, 2):                       # the J listed strikes directly above / below
                        want = [k0 - j * step, k0 + j * step]
                        got = [listed[i - j] if i - j >= 0 else None, listed[i + j] if i + j < len(listed) else None]
                        neighbours_differ += want != got
                for j in range(-2, 3):
                    not_listed += market.lot_size(dc.expiry, ot, k0 + j * step) is None
        print(f"  atm_oi strike set vs the contract list ({len(days)} days x CE/PE): nearest LISTED strike != nearest "
              f"multiple of the step on {k0_differs}; listed neighbours (1 and 2 away) != K0 +- j*step on "
              f"{neighbours_differ}; strikes of S (J<=2) not listed {not_listed}; exact half-way 09:15 closes {ties}")
        oi = P.CANDIDATES["atm_oi_writer_skew"]
        for label, params in cells(oi):
            reasons: Counter = Counter()
            mism = 0
            for d in days:
                dc = market.day_ctx(d)
                r = oi_reason(market, dc, params["eval_minutes"], params["strikes_each_side"])
                reasons[r] += 1
                ps = norm(oi["fn"](dc, **params))
                want = (C.hhmm(555 + params["eval_minutes"] - 1), r) if r in ("UP", "DOWN") else None
                mism += ps != want
            total_diff += mism
            print(f"  atm_oi {label:22s} third reading vs primary: {mism} mismatches; days by outcome: "
                  + "; ".join(f"{k}: {v}" for k, v in sorted(reasons.items())))

        md = market.max_dates()
        latest = max(v for v in (md["index"], md["vix"], md["option_files"], md["option_days"],
                                 *md["daily"].values()) if v)
        assert latest <= C.DISCOVERY_END, f"a row after the wall was held: {latest}"
        print(f"  latest date held in any store: {latest} (wall {market.last_day})")

    print("\n================ final signal counts of the PRIMARY (n, UP / DOWN, minutes) ================")
    for cid in IDS:
        for label, _ in cells(P.CANDIDATES[cid]):
            row = "  ".join(f"{ix} n={counts[(cid, label, ix)][0]} UP {counts[(cid, label, ix)][1]} "
                            f"DOWN {counts[(cid, label, ix)][2]} [{counts[(cid, label, ix)][3]}]" for ix in C.INDEXES)
            print(f"  {cid:27s} {label:27s} {row}")
    print(f"\nTOTAL disagreements {total_diff}   look-ahead problems {total_la}   structure problems {total_struct}")
    return 1 if (total_diff or total_la or total_struct) else 0


if __name__ == "__main__":
    sys.exit(main())
