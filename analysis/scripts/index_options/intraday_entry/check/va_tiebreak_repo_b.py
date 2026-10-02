"""check/va_tiebreak_repo_b.py - does the one reading both codings SHARE in the value-area profile bind?

Text: "POC = the row with the most units (tie: the row nearest the session's (high+low)/2, then the lower row)".
Both codings measure "nearest" from the row's centre (r + 0.5).  Two other literal readings exist:
  interval : distance from the row as the interval [r, r+1) to the midpoint (0 when the midpoint is inside)
  edge     : distance from the row's lower edge r (its label) to the midpoint
This script rebuilds the previous-session profile of every discovery day under all three and counts the
sessions on which VAH / VAL differ.  Earlier-session index candles only; no signal outcome is touched.
"""
from __future__ import annotations

import os
import sys
from math import floor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import ctx as C  # noqa: E402


def five(bars):
    out = []
    for k in range(len(bars) // 5):
        g = bars[5 * k:5 * k + 5]
        assert [b[0] for b in g] == [C.hhmm(555 + 5 * k + j) for j in range(5)]
        out.append((g[0][1], max(b[2] for b in g), min(b[3] for b in g), g[-1][4]))
    return out


def profile(cs):
    units = {}
    for o, h, l, c in cs:
        for r in range(floor(l), floor(h) + 1):
            units[r] = units.get(r, 0) + 1
    return units


def dist(kind, r, mid):
    if kind == "centre":
        return abs(r + 0.5 - mid)
    if kind == "interval":
        return 0.0 if r <= mid < r + 1 else min(abs(r - mid), abs(r + 1 - mid))
    return abs(r - mid)


def value_area(units, mid, share, kind):
    lowest, highest, total = min(units), max(units), sum(units.values())
    best = max(units.values())
    poc = min((r for r in units if units[r] == best), key=lambda r: (dist(kind, r, mid), r))
    top = bottom = poc
    held = units[poc]
    while held * 100 < share * total:
        up = units.get(top + 1, 0) if top + 1 <= highest else None
        down = units.get(bottom - 1, 0) if bottom - 1 >= lowest else None
        if up is None and down is None:
            break
        if down is None or (up is not None and up > down):
            top += 1
            held += up
        elif up is None or down > up:
            bottom -= 1
            held += down
        else:
            top += 1
            bottom -= 1
            held += up + down
    return poc, float(top + 1), float(bottom), held, total


def main():
    for index in C.INDEXES:
        m = C.Market(index)
        days = [d for d in m.sessions if C.WINDOW_START <= d <= C.DISCOVERY_END]
        n_tie = n_zero_rows = n_not75 = 0
        diff = {(k, s): 0 for k in ("interval", "edge") for s in (65, 70, 75)}
        poc_diff = {"interval": 0, "edge": 0}
        bad_share = 0
        for d in days:
            prev = m.sessions[m.sessions.index(d) - 1]
            cs = five(m.bars(prev))
            n_not75 += len(cs) != 75
            units = profile(cs)
            mid = (max(c[1] for c in cs) + min(c[2] for c in cs)) / 2.0
            best = max(units.values())
            n_tie += sum(1 for v in units.values() if v == best) > 1
            n_zero_rows += any(r not in units for r in range(min(units), max(units) + 1))
            for s in (65, 70, 75):
                base = value_area(units, mid, s, "centre")
                bad_share += not base[3] * 100 >= s * base[4]
                for k in ("interval", "edge"):
                    alt = value_area(units, mid, s, k)
                    diff[(k, s)] += alt[1:3] != base[1:3]
                    if s == 70:
                        poc_diff[k] += alt[0] != base[0]
        print(f"{index}: {len(days)} previous-session profiles; not 75 candles {n_not75}; "
              f"POC tied on units {n_tie}; profiles with an empty row inside the range {n_zero_rows}; "
              f"area below the share at exit {bad_share}")
        print(f"   POC row differs from the centre reading: {poc_diff}")
        print(f"   (VAH, VAL) differs from the centre reading: "
              + ", ".join(f"{k} @{s}%: {v}" for (k, s), v in diff.items()))


if __name__ == "__main__":
    main()
