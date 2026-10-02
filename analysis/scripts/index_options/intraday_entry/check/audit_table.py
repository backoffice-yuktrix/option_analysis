"""check/audit_table.py - an INDEPENDENT audit of the DISCOVERY outcome table (protocol.md P2 / P3).

    python check/audit_table.py            the 150-row sample + the full sweep of every row + the hunts
    python check/audit_table.py --no-full  the 150-row sample only

It imports neither engine.py nor ctx.py nor py_funcs.py.  Everything is recomputed from the raw json
files in analysis/candle_datas with code written from the protocol text alone:
  strike (index close of bar t = fill bar - 1), expiry (first expiry dated after the day), lot (contract
  list), statuses, buy (HIGH of the fill bar), each exit's stamp and sell (LOW of the first traded bar),
  costs (own formula: NSE / BSE rates, STT 0.10% before 2026-04-01 and 0.15% from it), net, net % of
  premium, index points.

THE DATE WALL here is physical too: every candle file is read as a byte stream in small chunks, row by
row, and the reading STOPS at the first row stamped after 2026-04-30.  No later row is ever converted
to a number, kept or printed.  (Expiry and contract lists hold no candles.)

Readings this audit takes (literal, written before any comparison was run):
  * NO_DATA = index bar t missing, no expiry, contract not in the contract list, no candle file, no
    candles that day, or no bar stamped t+1.  NO_FILL = that bar exists with volume 0.
    The file's "fetched" ranges are NOT used to decide (the protocol does not mention them); the sweep
    counts how often they would change a row.
  * step = 50 (NIFTY) / 100 (SENSEX); atm = float(round(C / step) * step)  (Python banker's rounding,
    which is what py_funcs.atm_strike does - DATA_API gotcha 12).
  * index points = sign x (index close at the exit stamp - C).
It only reads individual rows and counts structural events; no outcome is aggregated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sys
import time
from datetime import date

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.normpath(os.path.join(HERE, ".."))
ANALYSIS = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
DATA = os.path.join(ANALYSIS, "candle_datas")
OUT = os.path.join(ANALYSIS, "working strategy reports", "intraday_entry")
PY_FUNCS = os.path.join(ANALYSIS, "templates", "py_funcs.py")

WALL = "2026-04-30"
WINDOW_START = "2026-01-01"
INDEXES = ("NIFTY", "SENSEX")
STEP = {"NIFTY": 50.0, "SENSEX": 100.0}
MONTHS = ("2026-01", "2026-02", "2026-03", "2026-04")
SEED = 20261002
N_SAMPLE = 150
BAR0, NBAR = 555, 375                     # 09:15 .. 15:29
FILL0, FILL1 = 560, 854                   # 09:20 .. 14:14
M_EOD, M_STOP_LAST, M_LAST = 914, 912, 929
OK, NO_DATA, NO_FILL, NO_EXIT = 0, 1, 2, 3
ST = {OK: "OK", NO_DATA: "NO_DATA", NO_FILL: "NO_FILL", NO_EXIT: "NO_EXIT", -1: "NOT_COMPUTED"}
EXITS = ("EOD", "H60", "STOP30")
DIRS = ("UP", "DOWN")
OTS = ("CE", "PE")

ROW = re.compile(rb'\["(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})\+05:30",([^\[\]]*)\]')
ROW_START = re.compile(rb'\["(\d{4}-\d{2}-\d{2})')
FETCHED = re.compile(rb'"fetched":\[(.*?)\]\]')
PAIR = re.compile(rb'\["(\d{4}-\d{2}-\d{2})","(\d{4}-\d{2}-\d{2})"')
WALL_B = WALL.encode()
READ_STATS = {"files": 0, "stopped_at_wall": 0, "bytes": 0}


def hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# raw readers (stream, stop at the wall)
# ---------------------------------------------------------------------------
def stream_candles(path: str, chunk: int):
    """(fetched ranges, rows) of one candle file; rows = (day, minute, o, h, l, c, volume), ascending.
    Reading stops at the first row dated after WALL; that row and everything after it is never converted."""
    rows, fetched = [], []
    with open(path, "rb") as f:
        buf, in_rows, stop, prev = b"", False, False, (b"", -1)
        while not stop:
            data = f.read(chunk)
            READ_STATS["bytes"] += len(data)
            buf += data
            if not in_rows:
                k = buf.find(b'"candles":[')
                if k < 0:
                    if not data:
                        raise ValueError(f"{os.path.basename(path)}: no candles key")
                    continue
                head = buf[:k]
                m = FETCHED.search(head)
                if m:
                    fetched = [(a.decode(), b.decode()) for a, b in PAIR.findall(m.group(0))]
                buf = buf[k + len(b'"candles":['):]
                in_rows = True
            pos = 0
            while True:
                s = ROW_START.match(buf, pos)
                if s is None:
                    break
                if s.group(1) > WALL_B:                    # the wall: stop before the row is even matched whole
                    stop = True
                    READ_STATS["stopped_at_wall"] += 1
                    break
                m = ROW.match(buf, pos)
                if m is None:                              # an incomplete row at the end of the buffer
                    break
                vals = m.group(5).split(b",")
                if len(vals) != 6 or m.group(4) != b"00":
                    raise ValueError(f"{os.path.basename(path)}: unexpected row {m.group(0)[:80]!r}")
                key = (m.group(1), int(m.group(2)) * 60 + int(m.group(3)))
                if key <= prev:
                    raise ValueError(f"{os.path.basename(path)}: rows not strictly ascending at {key}")
                prev = key
                rows.append((key[0].decode(), key[1], float(vals[0]), float(vals[1]), float(vals[2]),
                             float(vals[3]), float(vals[4])))
                pos = m.end()
                if buf[pos:pos + 1] == b",":
                    pos += 1
            buf = buf[pos:]
            if not data:
                if not stop and buf.strip() not in (b"]}", b""):
                    raise ValueError(f"{os.path.basename(path)}: unparsed tail {buf[:60]!r}")
                break
    READ_STATS["files"] += 1
    return fetched, rows


def load_index(index: str) -> dict:
    """{day: {minute: (o, h, l, c)}} of the index, days <= WALL."""
    _, rows = stream_candles(os.path.join(DATA, f"{index}_candles.json"), 2048)
    out: dict = {}
    for d, m, o, h, l, c, _v in rows:
        out.setdefault(d, {})[m] = (o, h, l, c)
    return out


class Grid:
    """One contract on one day on the 09:15..15:29 minute grid; nothing filled in."""
    __slots__ = ("present", "o", "h", "l", "c", "v")

    def __init__(self, rows):
        self.present = [False] * NBAR
        self.o, self.h, self.l, self.c = ([math.nan] * NBAR for _ in range(4))
        self.v = [0.0] * NBAR
        for _d, m, o, h, l, c, v in rows:
            b = m - BAR0
            if 0 <= b < NBAR:
                self.present[b] = True
                self.o[b], self.h[b], self.l[b], self.c[b], self.v[b] = o, h, l, c, v

    def traded(self, b: int) -> bool:
        return self.present[b] and self.v[b] > 0

    def first_traded(self, b0: int):
        for b in range(b0, NBAR):
            if self.present[b] and self.v[b] > 0:
                return b
        return None


class Raw:
    """All raw data of one index, read independently."""

    def __init__(self, index: str):
        self.index = index
        self.bars = load_index(index)
        with open(os.path.join(DATA, f"{index}_expiry.json"), encoding="utf-8") as f:
            self.expiries = sorted(set(json.load(f)["expiries"]))
        with open(os.path.join(DATA, f"{index}_contracts.json"), encoding="utf-8") as f:
            chain = json.load(f)
        self.lots = {}
        for exp, cs in chain.items():
            for c in cs:
                self.lots[(exp, c["type"], float(c["strike"]))] = int(c["lot_size"])
        self._files: dict = {}
        self.fetched_quirks = {"outside_fetched_but_has_rows": 0, "inside_fetched_no_rows": 0}

    def sessions(self) -> list:
        """P4.2: 09:15 and 15:14 bars present and at least 350 bars, WINDOW_START..WALL."""
        return [d for d in sorted(self.bars) if WINDOW_START <= d <= WALL
                and 555 in self.bars[d] and 914 in self.bars[d] and len(self.bars[d]) >= 350]

    def expiry(self, day: str):
        """P2.1: first expiry at least 1 calendar day after the day."""
        d0 = date.fromisoformat(day)
        for e in self.expiries:
            if (date.fromisoformat(e) - d0).days >= 1:
                return e
        return None

    def contract_day(self, ot: str, strike: float, expiry: str, day: str):
        """(Grid or None, reason)."""
        key = (ot, strike, expiry)
        if key not in self._files:
            path = os.path.join(DATA, f"{self.index}_{ot}_{strike:g}_{expiry}_candles.json")
            if not os.path.isfile(path):
                self._files[key] = None
            else:
                fetched, rows = stream_candles(path, 2048 if expiry > WALL else 1 << 20)
                days: dict = {}
                for r in rows:
                    days.setdefault(r[0], []).append(r)
                self._files[key] = (fetched, days, {})
        f = self._files[key]
        if f is None:
            return None, "no candle file"
        fetched, days, grids = f
        inside = any(a <= day <= b for a, b in fetched)
        if day not in days:
            if inside and day not in grids:
                self.fetched_quirks["inside_fetched_no_rows"] += 1
                grids[day] = None
            return None, "no candles that day" + ("" if inside else " (day outside the fetched ranges)")
        if day not in grids:
            if not inside:
                self.fetched_quirks["outside_fetched_but_has_rows"] += 1
            grids[day] = Grid(days[day])
        return grids[day], ""


# ---------------------------------------------------------------------------
# the protocol, written a third time
# ---------------------------------------------------------------------------
def stt_rate(day: str) -> float:
    return 0.0015 if day >= "2026-04-01" else 0.001


def costs_of(index: str, buy: float, sell: float, lot: int, day: str, force_exchange: str | None = None,
             force_stt: float | None = None) -> float:
    exchange = force_exchange or ("NSE" if index == "NIFTY" else "BSE")
    B, S = buy * lot, sell * lot
    brokerage = 30.0 * 2
    stt = (stt_rate(day) if force_stt is None else force_stt) * S
    if exchange == "NSE":
        exch = (0.0003503 + 0.5 / 1e5) * (B + S)
        sebi = (10.0 / 1e7) * (B + S)
    else:
        exch = 0.00005 * (B + S)
        sebi = 0.0
    stamp = 0.00003 * B
    gst = 0.18 * (brokerage + exch + sebi)
    return round(brokerage + stt + exch + sebi + stamp + gst, 2)


def audit_row(raw: Raw, day: str, fill: int, di: int, hunts: dict | None = None) -> dict:
    out = {"status_e": NO_DATA, "strike": math.nan, "lot": 0, "buy": math.nan, "open": math.nan, "why": "",
           "exits": [{"status": NO_DATA} for _ in EXITS]}
    ibars = raw.bars[day]
    t = fill - 1
    expiry = raw.expiry(day)
    out["expiry"] = expiry
    if t not in ibars:
        out["why"] = "index bar t missing"
        return out
    if expiry is None:
        out["why"] = "no expiry"
        return out
    C = ibars[t][3]
    step = STEP[raw.index]
    strike = float(round(C / step) * step)
    out["strike"] = strike
    ot = OTS[di]
    lot = raw.lots.get((expiry, ot, strike))
    if lot is None:
        out["why"] = f"{ot} {strike:g} {expiry} not in the contract list"
        return out
    g, why = raw.contract_day(ot, strike, expiry, day)
    if g is None:
        out["why"] = f"{ot} {strike:g} {expiry}: {why}"
        return out
    b = fill - BAR0
    if not g.present[b]:
        out["why"] = f"{ot} {strike:g} {expiry}: no bar stamped {hhmm(fill)}"
        return out
    if g.v[b] <= 0:
        out["status_e"] = NO_FILL
        out["exits"] = [{"status": NO_FILL} for _ in EXITS]
        out["why"] = f"{ot} {strike:g} {expiry}: bar {hhmm(fill)} has volume 0 (o=h=l=c={g.c[b]})"
        return out
    buy = g.h[b]
    out.update(status_e=OK, lot=lot, buy=buy, open=g.o[b])
    x_eod = g.first_traded(M_EOD - BAR0)
    x_h60 = g.first_traded(b + 60)
    level = 0.70 * buy
    trig = None
    for m in range(b, M_STOP_LAST - BAR0 + 1):
        if g.present[m] and g.v[m] > 0 and g.c[m] <= level:
            trig = m
            break
    x_stop = g.first_traded(trig + 1) if trig is not None else x_eod
    sign = 1.0 if di == 0 else -1.0
    for e, x in enumerate((x_eod, x_h60, x_stop)):
        if x is None:
            out["exits"][e] = {"status": NO_EXIT}
            continue
        sell = g.l[x]
        gross = round((sell - buy) * lot, 2)
        cst = costs_of(raw.index, buy, sell, lot, day)
        net = round(gross - cst, 2)
        xm = x + BAR0
        out["exits"][e] = {"status": OK, "exit_min": xm, "sell": sell, "gross": gross, "costs": cst, "net": net,
                           "pct": 100.0 * net / (buy * lot),
                           "pts": sign * (ibars[xm][3] - C) if xm in ibars else math.nan}
    if hunts is not None:
        hunts["ok_rows"] += 1
        # strike from the fill bar instead of the bar before it
        if fill in ibars and float(round(ibars[fill][3] / step) * step) != strike:
            hunts["strike_differs_if_taken_from_fill_bar"] += 1
        # EOD: the 15:14 bar itself not tradable
        if not g.traded(M_EOD - BAR0):
            hunts["eod_1514_bar_not_traded"] += 1
        if x_eod is not None and x_eod != M_EOD - BAR0:
            hunts["eod_filled_later_than_1514"] += 1
        # H60: the scheduled bar itself not tradable
        if not g.traded(b + 60):
            hunts["h60_scheduled_bar_not_traded"] += 1
        if x_h60 is not None and (g.l[x_h60] != g.l[min(x_h60 + 1, NBAR - 1)] or g.l[x_h60] != g.l[x_h60 - 1]):
            hunts["h60_low_differs_from_a_neighbour_minute"] += 1
        # STOP30 variants
        if trig is not None:
            hunts["stop_triggered"] += 1
            if trig == b:
                hunts["stop_trigger_is_the_entry_bar"] += 1
            if x_stop is not None:
                if g.l[x_stop] < level:
                    hunts["stop_sale_below_level_(a_cap_would_change_it)"] += 1
                elif g.l[x_stop] > level:
                    hunts["stop_sale_above_level"] += 1
                if x_stop != trig + 1:
                    hunts["stop_sale_bar_is_not_trigger_plus_1_(untraded_bar_skipped)"] += 1
        low_trig = None
        for m in range(b, M_STOP_LAST - BAR0 + 1):
            if g.present[m] and g.v[m] > 0 and g.l[m] <= level:
                low_trig = m
                break
        if low_trig != trig:
            hunts["stop_low_based_trigger_would_differ"] += 1
        if trig is None:
            for m in range(M_STOP_LAST - BAR0 + 1, NBAR):
                if g.present[m] and g.v[m] > 0 and g.c[m] <= level:
                    hunts["stop_would_trigger_only_after_1512"] += 1
                    break
        # zero-volume bars between the entry and 15:29 (the fills must have skipped them)
        if any(g.present[m] and g.v[m] <= 0 for m in range(b, NBAR)):
            hunts["rows_with_a_zero_volume_bar_after_entry"] += 1
        if any(not g.present[m] for m in range(b, NBAR)):
            hunts["rows_with_a_missing_minute_after_entry"] += 1
        # costs: the wrong exchange / the wrong STT rate would be visible
        if out["exits"][0]["status"] == OK:
            sell = out["exits"][0]["sell"]
            if raw.index == "SENSEX" and abs(costs_of("SENSEX", buy, sell, lot, day, force_exchange="NSE")
                                             - out["exits"][0]["costs"]) > 0.005:
                hunts["sensex_rows_where_nse_rates_would_change_costs"] += 1
            other = 0.001 if day >= "2026-04-01" else 0.0015
            if abs(costs_of(raw.index, buy, sell, lot, day, force_stt=other) - out["exits"][0]["costs"]) > 0.005:
                hunts["rows_where_the_other_stt_rate_would_change_costs"] += 1
    return out


# ---------------------------------------------------------------------------
# comparison with the saved table
# ---------------------------------------------------------------------------
class Saved:
    def __init__(self):
        self.side = json.load(open(os.path.join(OUT, "outcome_discovery.json"), encoding="utf-8"))
        self.z = np.load(os.path.join(OUT, "outcome_discovery.npz"))
        self.sessions = self.side["sessions"]
        self.expiry = self.side["expiry"]

    def a(self, index, name):
        return self.z[f"{index}__{name}"]


def same(a: float, b: float, tol: float = 0.0) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return abs(a - b) <= tol


def compare(saved: Saved, index: str, si: int, fill: int, di: int, ref: dict) -> list:
    """Field by field; returns the mismatches as text with both numbers."""
    fi = fill - FILL0
    tag = f"{index} {saved.sessions[index][si]} {hhmm(fill)} {DIRS[di]}"
    bad = []
    g = lambda name: saved.a(index, name)                              # noqa: E731
    se = int(g("status_e")[si, fi, di])
    if se != ref["status_e"]:
        bad.append(f"{tag}: entry status table {ST[se]} vs audit {ST[ref['status_e']]} ({ref['why']})")
    if saved.expiry[index][si] != ref["expiry"]:
        bad.append(f"{tag}: expiry table {saved.expiry[index][si]} vs audit {ref['expiry']}")
    day = saved.sessions[index][si]
    if ref["expiry"] is not None:
        dte = (date.fromisoformat(ref["expiry"]) - date.fromisoformat(day)).days
        if int(g("dte")[si]) != dte:
            bad.append(f"{tag}: DTE table {int(g('dte')[si])} vs audit {dte}")
    for name in ("strike", "buy", "open"):
        tv, av = float(g(name)[si, fi, di]), float(ref[name])
        if not same(tv, av):
            bad.append(f"{tag}: {name} table {tv!r} vs audit {av!r}")
    if int(g("lot")[si, fi, di]) != ref["lot"]:
        bad.append(f"{tag}: lot table {int(g('lot')[si, fi, di])} vs audit {ref['lot']}")
    for e, name in enumerate(EXITS):
        rx = ref["exits"][e]
        sx = int(g("status_x")[si, fi, di, e])
        if sx != rx["status"]:
            bad.append(f"{tag} {name}: status table {ST[sx]} vs audit {ST[rx['status']]}")
            continue
        if rx["status"] != OK:
            if int(g("exit_min")[si, fi, di, e]) != -1 or not all(
                    math.isnan(float(g(k)[si, fi, di, e])) for k in ("sell", "gross", "costs", "net", "pct", "pts")):
                bad.append(f"{tag} {name}: a non-OK row carries a result")
            continue
        xm = int(g("exit_min")[si, fi, di, e])
        if xm != rx["exit_min"]:
            bad.append(f"{tag} {name}: exit stamp table {hhmm(xm)} vs audit {hhmm(rx['exit_min'])}")
        for k, tol in (("sell", 0.0), ("gross", 1e-9), ("costs", 1e-9), ("net", 1e-9), ("pct", 1e-9), ("pts", 1e-9)):
            tv, av = float(g(k)[si, fi, di, e]), float(rx[k])
            if not same(tv, av, tol):
                bad.append(f"{tag} {name}: {k} table {tv!r} vs audit {av!r} (diff {tv - av:+.6f})")
    return bad


# ---------------------------------------------------------------------------
# the 150-row sample
# ---------------------------------------------------------------------------
def choose_sample(sessions: dict, raws: dict) -> list:
    rng = random.Random(SEED)
    rows, seen = [], set()

    def add(index, day, fill, di, tag):
        key = (index, day, fill, di)
        if key in seen:
            return False
        seen.add(key)
        rows.append((index, day, fill, di, tag))
        return True

    for index in INDEXES:
        sess = sessions[index]
        raw = raws[index]
        by_month = {m: [d for d in sess if d[:7] == m] for m in MONTHS}
        eve = [d for d in sess if (date.fromisoformat(raw.expiry(d)) - date.fromisoformat(d)).days == 1]
        expd = [d for d in sess if d in set(raw.expiries)]
        n0 = len(rows)
        # 8 rows at the earliest and the latest fill bar, both directions, two months each
        k = 0
        for fill in (FILL0, FILL1):
            for di in (0, 1):
                for _ in range(2):
                    m = MONTHS[k % 4]
                    k += 1
                    while not add(index, rng.choice(by_month[m]), fill, di, "edge fill bar"):
                        pass
        # 10 expiry-eve rows and 10 expiry-day rows (one each at 09:20 and at 14:14)
        for pool, tag in ((eve, "expiry eve (DTE 1)"), (expd, "expiry day")):
            for j in range(10):
                fill = FILL0 if j == 0 else FILL1 if j == 1 else rng.randint(FILL0, FILL1)
                while not add(index, rng.choice(pool), fill, j % 2, tag):
                    fill = rng.randint(FILL0, FILL1)
        # the rest: month x direction cells in turn, random day and minute
        cells = [(m, di) for m in MONTHS for di in (0, 1)]
        j = 0
        while len(rows) - n0 < N_SAMPLE // 2:
            m, di = cells[j % len(cells)]
            j += 1
            while not add(index, rng.choice(by_month[m]), rng.randint(FILL0, FILL1), di, "random"):
                pass
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-full", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="do not list the 150 sample rows")
    a = ap.parse_args()
    t0 = time.perf_counter()
    saved = Saved()
    report: dict = {"seed": SEED, "wall": WALL}
    problems: list = []

    # -- 0. is the saved table the current one, and is it intact?
    print("== 0. the saved table ==")
    side = saved.side
    cur = {"engine.py": sha256(os.path.join(STUDY, "engine.py")), "ctx.py": sha256(os.path.join(STUDY, "ctx.py")),
           "protocol.md": sha256(os.path.join(STUDY, "protocol.md"))}
    for k, v in cur.items():
        okk = side["hashes"].get(k) == v
        print(f"   {k}: sidecar hash {'matches' if okk else 'DIFFERS FROM'} the file on disk")
        if not okk:
            problems.append(f"sidecar hash of {k} differs from the file on disk")
    for label, path, want in (("py_funcs.py", PY_FUNCS, side["py_funcs_sha256"]),
                              ("outcome_discovery.npz", os.path.join(OUT, "outcome_discovery.npz"), side["npz_sha256"])):
        okk = sha256(path) == want
        print(f"   {label}: sidecar hash {'matches' if okk else 'DIFFERS FROM'} the file on disk")
        if not okk:
            problems.append(f"sidecar hash of {label} differs")
    sd = json.load(open(os.path.join(OUT, "sessions_discovery.json"), encoding="utf-8"))
    if sd["sessions"] != side["sessions"]:
        problems.append("sessions_discovery.json and outcome_discovery.json list different sessions")

    # -- 1. raw data, sessions (P4.2), expiry, DTE
    print("== 1. sessions, expiry, DTE from the raw files ==")
    raws = {idx: Raw(idx) for idx in INDEXES}
    for idx in INDEXES:
        raw = raws[idx]
        latest = max(raw.bars)
        own = raw.sessions()
        print(f"   {idx}: index days read {len(raw.bars)} ({min(raw.bars)} .. {latest}); own P4.2 session list {len(own)}; "
              f"table {len(saved.sessions[idx])}; identical: {own == saved.sessions[idx]}")
        if latest > WALL:
            problems.append(f"{idx}: the audit itself read past the wall ({latest})")
        if own != saved.sessions[idx]:
            problems.append(f"{idx}: session list differs: only audit {sorted(set(own) - set(saved.sessions[idx]))}, "
                            f"only table {sorted(set(saved.sessions[idx]) - set(own))}")
        if max(saved.sessions[idx]) > WALL:
            problems.append(f"{idx}: the table holds a session after the wall")
        exp_bad = [(d, saved.expiry[idx][i], raw.expiry(d)) for i, d in enumerate(saved.sessions[idx])
                   if saved.expiry[idx][i] != raw.expiry(d)]
        today = [d for i, d in enumerate(saved.sessions[idx]) if saved.expiry[idx][i] is not None and saved.expiry[idx][i] <= d]
        expd = [d for d in saved.sessions[idx] if d in set(raw.expiries)]
        dte = saved.a(idx, "dte")
        dte_bad = [d for i, d in enumerate(saved.sessions[idx]) if raw.expiry(d) is not None
                   and int(dte[i]) != (date.fromisoformat(raw.expiry(d)) - date.fromisoformat(d)).days]
        print(f"   {idx}: expiry mismatches {len(exp_bad)}; sessions whose table expiry is the day itself or earlier "
              f"{len(today)} (expiry-day sessions: {len(expd)}); DTE mismatches {len(dte_bad)}; "
              f"DTE-1 sessions {int((dte == 1).sum())}; min DTE {int(dte.min())}")
        for x in exp_bad:
            problems.append(f"{idx} {x[0]}: expiry table {x[1]} vs audit {x[2]}")
        for d in today:
            problems.append(f"{idx} {d}: today's (or a past) expiry used")
        for d in dte_bad:
            problems.append(f"{idx} {d}: DTE differs")
        shp = saved.a(idx, "status_e").shape
        if shp != (len(saved.sessions[idx]), FILL1 - FILL0 + 1, 2):
            problems.append(f"{idx}: table shape {shp}")
        report.setdefault("sessions", {})[idx] = {"n": len(own), "expiry_days": len(expd)}

    # -- 2. the 150-row sample
    print(f"== 2. {N_SAMPLE} pseudo-random rows (seed {SEED}), every field recomputed from the raw files ==")
    sample = choose_sample(saved.sessions, raws)
    cover = {idx: {"rows": 0, "UP": 0, "DOWN": 0, "09:20": 0, "14:14": 0, "expiry eve": 0, "expiry day": 0,
                   **{m: 0 for m in MONTHS}} for idx in INDEXES}
    sample_bad, fields = [], 0
    for index, day, fill, di, tag in sample:
        raw = raws[index]
        si = saved.sessions[index].index(day)
        ref = audit_row(raw, day, fill, di)
        bad = compare(saved, index, si, fill, di, ref)
        sample_bad += bad
        fields += 7 + 3 * 8
        c = cover[index]
        c["rows"] += 1
        c[DIRS[di]] += 1
        c[day[:7]] += 1
        c["09:20"] += fill == FILL0
        c["14:14"] += fill == FILL1
        dte = (date.fromisoformat(ref["expiry"]) - date.fromisoformat(day)).days
        c["expiry eve"] += dte == 1
        c["expiry day"] += day in set(raw.expiries)
        if not a.quiet:
            ex = " ".join(f"{n}:{hhmm(x['exit_min']) if x['status'] == OK else ST[x['status']]}"
                          for n, x in zip(EXITS, ref["exits"]))
            print(f"   {index:6s} {day} {hhmm(fill)} {DIRS[di]:4s} {OTS[di]} {ref['strike']:g} exp {ref['expiry']} dte {dte} "
                  f"lot {ref['lot']} {ST[ref['status_e']]:7s} buy {ref['buy']} | {ex} | "
                  f"{'match' if not bad else 'MISMATCH x' + str(len(bad))} [{tag}]")
    for idx in INDEXES:
        print(f"   coverage {idx}: {cover[idx]}")
    print(f"   sample: {len(sample)} rows, about {fields} fields compared, {len(sample_bad)} mismatches")
    for b in sample_bad:
        print("   MISMATCH " + b)
    report["sample"] = {"rows": len(sample), "fields": fields, "mismatches": sample_bad, "coverage": cover}

    # -- 3. every non-OK row of the table, with the raw evidence
    print("== 3. every non-OK row of the table against the raw file ==")
    nonok = []
    for idx in INDEXES:
        se, sx = saved.a(idx, "status_e"), saved.a(idx, "status_x")
        cells = np.argwhere((se != OK) | (sx != OK).any(axis=3))
        for si, fi, di in cells.tolist():
            day = saved.sessions[idx][si]
            ref = audit_row(raws[idx], day, FILL0 + fi, di)
            bad = compare(saved, idx, si, FILL0 + fi, di, ref)
            line = (f"{idx} {day} {hhmm(FILL0 + fi)} {DIRS[di]}: table entry {ST[int(se[si, fi, di])]}, exits "
                    f"{[ST[int(v)] for v in sx[si, fi, di]]}; audit {ST[ref['status_e']]} - {ref['why']}"
                    f"{'' if not bad else '  MISMATCH'}")
            print("   " + line)
            nonok.append(line)
            problems += bad
    report["non_ok_rows"] = nonok

    # -- 4. the full sweep
    if not a.no_full:
        print("== 4. full sweep: every row of the table recomputed (third coding) + the hunts ==")
        sweep_bad: list = []
        hunts_all = {}
        for idx in INDEXES:
            raw = raws[idx]
            hunts = {k: 0 for k in (
                "ok_rows", "strike_differs_if_taken_from_fill_bar", "eod_1514_bar_not_traded", "eod_filled_later_than_1514",
                "h60_scheduled_bar_not_traded", "h60_low_differs_from_a_neighbour_minute", "stop_triggered",
                "stop_trigger_is_the_entry_bar", "stop_sale_below_level_(a_cap_would_change_it)", "stop_sale_above_level",
                "stop_sale_bar_is_not_trigger_plus_1_(untraded_bar_skipped)", "stop_low_based_trigger_would_differ",
                "stop_would_trigger_only_after_1512", "rows_with_a_zero_volume_bar_after_entry",
                "rows_with_a_missing_minute_after_entry", "sensex_rows_where_nse_rates_would_change_costs",
                "rows_where_the_other_stt_rate_would_change_costs")}
            n = 0
            for si, day in enumerate(saved.sessions[idx]):
                for fill in range(FILL0, FILL1 + 1):
                    for di in (0, 1):
                        ref = audit_row(raw, day, fill, di, hunts)
                        sweep_bad += compare(saved, idx, si, fill, di, ref)
                        n += 1
            # table-side sanity: NaN handling, fills on traded bars only, exit windows
            se, sx = saved.a(idx, "status_e"), saved.a(idx, "status_x")
            okx = sx == OK
            nan_in_ok = sum(int(np.isnan(saved.a(idx, k)[okx]).sum()) for k in ("sell", "gross", "costs", "net", "pct", "pts"))
            val_in_bad = sum(int((~np.isnan(saved.a(idx, k)[~okx])).sum()) for k in ("sell", "gross", "costs", "net", "pct", "pts"))
            oke = se == OK
            nan_entry = int(np.isnan(saved.a(idx, "buy")[oke]).sum() + np.isnan(saved.a(idx, "strike")[oke]).sum()
                            + (saved.a(idx, "lot")[oke] <= 0).sum())
            xm = saved.a(idx, "exit_min")
            fillm = (FILL0 + np.arange(FILL1 - FILL0 + 1))[None, :, None]
            eod_bad = int(((xm[..., 0] < M_EOD) | (xm[..., 0] > M_LAST))[okx[..., 0]].sum())
            h60_bad = int(((xm[..., 1] < fillm + 60) | (xm[..., 1] > M_LAST))[okx[..., 1]].sum())
            stop_bad = int(((xm[..., 2] <= fillm) | (xm[..., 2] > M_LAST))[okx[..., 2]].sum())
            status_bad = int(((sx != se[..., None]) & (sx != NO_EXIT)).sum() + ((sx == NO_EXIT) & (se[..., None] != OK)).sum())
            not_computed = int((se == -1).sum() + (sx == -1).sum())
            lots = sorted(set(saved.a(idx, "lot")[oke].tolist()))
            print(f"   {idx}: {n} rows recomputed; table-side checks: NaN inside OK results {nan_in_ok}, values inside non-OK "
                  f"{val_in_bad}, OK entries without buy/strike/lot {nan_entry}, EOD stamp outside 15:14..15:29 {eod_bad}, "
                  f"H60 stamp before fill+60 {h60_bad}, STOP30 stamp at or before the fill bar {stop_bad}, inconsistent "
                  f"statuses {status_bad}, NOT_COMPUTED cells {not_computed}, lots {lots}")
            for name, v in (("NaN inside OK results", nan_in_ok), ("values inside non-OK rows", val_in_bad),
                            ("OK entries without buy/strike/lot", nan_entry), ("EOD stamp outside 15:14..15:29", eod_bad),
                            ("H60 stamp before fill+60", h60_bad), ("STOP30 stamp at or before the fill bar", stop_bad),
                            ("inconsistent statuses", status_bad), ("NOT_COMPUTED cells", not_computed)):
                if v:
                    problems.append(f"{idx}: {name}: {v}")
            print(f"   {idx} hunts (how many rows could expose each wrong coding):")
            for k, v in hunts.items():
                print(f"      {k}: {v}")
            print(f"   {idx} fetched-range quirks (contract-days): {raw.fetched_quirks}")
            hunts_all[idx] = {**hunts, "fetched_quirks": dict(raw.fetched_quirks), "rows": n}
        print(f"   full sweep: {len(sweep_bad)} mismatching fields")
        for b in sweep_bad[:60]:
            print("   MISMATCH " + b)
        report["sweep"] = {"mismatches": len(sweep_bad), "first": sweep_bad[:200], "hunts": hunts_all}
        problems += sweep_bad[:200]

    problems += sample_bad
    print(f"== files read: {READ_STATS['files']}, {READ_STATS['bytes'] / 1e6:.0f} MB, stopped at the wall in "
          f"{READ_STATS['stopped_at_wall']} files; {time.perf_counter() - t0:.0f} s ==")
    report["read_stats"] = dict(READ_STATS)
    report["problems"] = problems
    with open(os.path.join(OUT, "audit_table.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(f"AUDIT {'CLEAN' if not problems else 'FOUND ' + str(len(problems)) + ' PROBLEM(S)'}")
    for p in problems[:80]:
        print("   PROBLEM " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
