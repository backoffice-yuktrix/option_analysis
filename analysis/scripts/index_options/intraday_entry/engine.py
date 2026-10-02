"""engine.py - the measuring machine of protocol.md (v2, frozen 2026-10-02) for the intraday-entry study.

    python engine.py --step table                      build the DISCOVERY outcome table (P2 / P3)
    python engine.py --step signals                    run every candidate, mechanical look-ahead check, counts only
    python engine.py --step score --stamp <text>       run_log.json, P8.5 printout, S, gates, nulls, winner, freeze.json
    python engine.py --step holdout --stamp <text> --confirm OPEN-HOLDOUT      (one shot; refused without freeze.json)
    python engine.py --step selftest                   synthetic tests, PASS / FAIL lines

Every number comes from protocol.md / library.json.  Nothing here is tunable from the command line.

READINGS - where the protocol text left a choice, the most literal reading was taken BEFORE any result
existed; each one is listed in READINGS below and copied into every result file.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import sys
import time
from datetime import date

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ctx as C                                               # noqa: E402  the one data door

sys.path.insert(0, os.path.join(C.ANALYSIS_DIR, "templates"))
import py_funcs                                               # noqa: E402  atm_strike and the cost helpers only

PY_FUNCS_PATH = os.path.join(C.ANALYSIS_DIR, "templates", "py_funcs.py")
STUDY_DIR = HERE
OUT_DIR = C.OUTPUT_DIR

# ---------------------------------------------------------------------------
# protocol constants (nothing below is a parameter)
# ---------------------------------------------------------------------------
INDEXES = C.INDEXES
EXCHANGE = {"NIFTY": "NSE", "SENSEX": "BSE"}                  # P2.3
STRUCK = ("near_expiry_first_hour_drive",)                    # Addendum 1
SIGNAL_MODULES = ("signals_repo_a", "signals_repo_b", "signals_trend", "signals_revvol", "signals_ctx")
HOLDOUT_START = "2026-05-01"                                  # P4.1
DISCOVERY_MONTHS = ("2026-01", "2026-02", "2026-03", "2026-04")
EXITS = ("EOD", "H60", "STOP30")                              # P2.5; EOD is the headline (P2.6)
DIRS = ("UP", "DOWN")
OT = ("CE", "PE")                                             # UP buys CE, DOWN buys PE
BAR0 = 555                                                    # 09:15
NBAR = 375                                                    # 09:15 .. 15:29
FILL0, FILL1 = 560, 854                                       # fill bars 09:20 .. 14:14 (P1.3)
NF = FILL1 - FILL0 + 1                                        # 295
B_EOD = 914 - BAR0                                            # the 15:14 bar
B_STOP_LAST = 912 - BAR0                                      # the 15:12 bar, last possible STOP30 trigger
STOP_FRACTION = 0.70                                          # P2.5
SEED = 20261002                                               # P8.2 / P10.5
N_DRAWS = 2000
MIN_N_DISCOVERY, MIN_N_HOLDOUT = 20, 10                       # P6.1 / P10.1
GATE_MIN_TRADES, GATE_MAX_UNPRICED = 30, 0.05                 # P7(a)
GATE_MONTHS_POSITIVE, GATE_MAX_MONTH_SHARE = 3, 0.70          # P7(b)
GATE_P = 0.25                                                 # P7(e)
HOLDOUT_P = 0.20                                              # P10.3
ST_OK, ST_NO_DATA, ST_NO_FILL, ST_NO_EXIT, ST_NOT_COMPUTED = 0, 1, 2, 3, -1
ST_NAME = {ST_OK: "OK", ST_NO_DATA: "NO_DATA", ST_NO_FILL: "NO_FILL", ST_NO_EXIT: "NO_EXIT",
           ST_NOT_COMPUTED: "NOT_COMPUTED"}

READINGS = [
    "P3.1 status: one entry status per row (OK / NO_DATA / NO_FILL) and one status per exit (the entry status, or "
    "NO_EXIT). A trade exists under exit X when the row is OK under X; a NO_EXIT under H60 does not remove the EOD trade.",
    "P2.4 NO_DATA: the index bar stamped t is missing, there is no expiry, the contract is not in the contract list, "
    "the contract has no candles that day, or the option bar stamped t+1 is missing. NO_FILL: that bar exists with volume 0.",
    "P2.5 STOP30: level = 0.70 x buy; trigger = first bar from the entry bar to the 15:12 bar with volume > 0 and close <= "
    "level; the sale is the LOW of the first bar stamped after the trigger with volume > 0, up to 15:29 (else NO_EXIT). "
    "No trigger: the same fill as EOD (and NO_EXIT when EOD is NO_EXIT).",
    "P3.2 index points: direction sign x (index close of the 1-minute bar at the exit stamp - C), C = the index close of "
    "the signal bar t (the price that chose the strike). Descriptive only.",
    "P3.2 net % of premium is stored in percent: 100 x net / (buy x lot). gross and net are rounded to 2 decimals; costs "
    "come rounded from py_funcs.option_round_trip.",
    "P6.1 sd = 0: an sd at or below 1e-9 x (1 + |mean|) is treated as 0 (floating point), so t = 0.",
    "P7(a): 'OK trades' and 'unpriced' are counted on the headline exit (EOD): unpriced share = signals whose EOD row is "
    "not OK / signals, per index; both indices must be <= 5% and have >= 30 OK EOD trades. Counts under the other exits "
    "are reported beside it.",
    "P7(b): a month with no trade has combined net 0 (not > 0). The 70% rule is max(month net) / total combined net; a "
    "total <= 0 fails the gate.",
    "P7(c): a neighbour's S is P6 on the neighbour's own signals; a neighbour with fewer than 20 trades has S = 0, which "
    "passes 'S >= 0' but it still needs combined net > 0. Every neighbour written by the signal module counts.",
    "P7(d): best DATE = the trade date with the largest combined EOD net; gate = total - that > 0.",
    "P7(f): 'total net % of premium' = the SUM over EOD trades of the stored per-trade net % of premium (P3.2), per index. "
    "The pooled ratio (total net / total premium paid) is reported beside it and is not gated.",
    "P8.1: weeks = ISO (year, week) of the session dates of both indices together; weekday = ISO weekday 1..7 (Sunday "
    "2026-02-01 is weekday 7 of its ISO week and only ever maps onto itself). The same week map is used for every "
    "candidate and both indices; a target date that is not a session of that index drops the signal.",
    "P8.2: the 2,000 permutations are numpy.random.default_rng(20261002).permutation(W), drawn one after another. The "
    "identity is not excluded. P8.4 reference permutation: a separate default_rng(20261002), sessions permuted uniformly "
    "within each ISO weekday.",
    "P8.4 '>=': a null maximum within 1e-9 of the real S counts as >= (conservative on floating-point ties).",
    "P8.5: rupee edge for a 50-trade candidate = q75 x sd / sqrt(50), with sd = the sd of EOD net rupees over ALL OK rows "
    "of the outcome table of that index (candidate-free); the same with the median per-trade sd of the centre candidates "
    "is printed as a second line.",
    "P9 near-miss: every centre candidate that fails a gate is listed with the gates it failed, ordered by S.",
    "P10.5 bootstrap: holdout ISO weeks are resampled with replacement (as many as there are weeks); the statistic is "
    "the mean combined EOD net over the trade dates (dates with at least one OK EOD trade) of the drawn weeks; the "
    "interval is the 5th..95th percentile over 2,000 resamples, default_rng(20261002); a resample with no trade date is "
    "skipped and counted. 'The null mean' = the average over null draws of the mean EOD net per trade (per index and "
    "pooled) and of the mean combined net per trade date, reported for each null.",
    "P4.3: a scoring run made after results_holdout.json exists is labelled POST-HOLDOUT, EXPLORATORY, is written to its "
    "own file and never touches freeze.json.",
    "P3.3 hashes: protocol.md, library.json and every .py under the study folder (recursive, __pycache__ excluded), by "
    "relative path; py_funcs.py (outside the study folder) is hashed too and must also match.",
]


class Refusal(Exception):
    """The engine refuses to go on (missing freeze, changed hash, offenders ...)."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _j(o):
    """Make an object JSON-safe (numpy -> python, NaN / inf -> None)."""
    if isinstance(o, dict):
        return {str(k): _j(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_j(v) for v in o]
    if isinstance(o, np.ndarray):
        return _j(o.tolist())
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    return o


def write_json(path: str, obj, exclusive: bool = False) -> None:
    text = json.dumps(_j(obj), indent=1)
    if exclusive:
        with open(path, "x", encoding="utf-8") as f:           # never overwrites
            f.write(text)
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def study_hashes(study_dir: str) -> dict:
    """SHA-256 of protocol.md, library.json and every .py file of the study (P3.3)."""
    out = {}
    for name in ("protocol.md", "library.json"):
        p = os.path.join(study_dir, name)
        if not os.path.isfile(p):
            raise Refusal(f"{name} is missing from {study_dir}")
        out[name] = sha256_file(p)
    for root, dirs, files in os.walk(study_dir):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for f in sorted(files):
            if f.endswith(".py"):
                rel = os.path.relpath(os.path.join(root, f), study_dir).replace("\\", "/")
                out[rel] = sha256_file(os.path.join(root, f))
    return dict(sorted(out.items()))


def hash_diff(old: dict, new: dict) -> list[str]:
    out = []
    for k in sorted(set(old) | set(new)):
        if k not in new:
            out.append(f"{k}: file removed")
        elif k not in old:
            out.append(f"{k}: new file")
        elif old[k] != new[k]:
            out.append(f"{k}: content changed")
    return out


def load_library(study_dir: str) -> list[dict]:
    """The frozen candidates in library order, each flagged struck / previously seen."""
    lib = read_json(os.path.join(study_dir, "library.json"))
    out = []
    for pos, c in enumerate(lib["candidates"]):
        out.append({"id": c["id"], "order": pos, "family": c.get("family"), "name": c.get("name"),
                    "n_params": len(c.get("params", [])), "struck": c["id"] in STRUCK,
                    "previously_seen": c.get("family") == "existing_repo"})
    return out


# ---------------------------------------------------------------------------
# sessions (P4) and the week / weekday calendar (P8.1)
# ---------------------------------------------------------------------------
def included_sessions(market, lo: str, hi: str) -> tuple[list[str], list[str]]:
    """P4.2: bars at 09:15 and 15:14 and at least 350 bars.  (included, excluded)"""
    inc, exc = [], []
    for d in market.sessions:
        if d < lo or d > hi:
            continue
        bars = market.bars(d)
        stamps = {r[0] for r in bars}
        (inc if ("09:15" in stamps and "15:14" in stamps and len(bars) >= 350) else exc).append(d)
    return inc, exc


def print_sessions(index: str, sessions: list[str], excluded: list[str], label: str) -> None:
    print(f"{label} sessions {index}: {len(sessions)}"
          + (f" ({sessions[0]} .. {sessions[-1]})" if sessions else "")
          + f"; excluded by P4.2: {excluded if excluded else 'none'}")
    for i in range(0, len(sessions), 10):
        print("   " + " ".join(sessions[i:i + 10]))


class Calendar:
    """Slots (ISO week, ISO weekday) over the union of the session dates of all indices."""

    def __init__(self, sessions_by_index: dict):
        self.indexes = list(sessions_by_index)
        self.dates = sorted(set().union(*[set(v) for v in sessions_by_index.values()]))
        iso = [date.fromisoformat(d).isocalendar() for d in self.dates]
        self.weeks = sorted({(y, w) for y, w, _ in iso})
        self.W = len(self.weeks)
        wpos = {k: i for i, k in enumerate(self.weeks)}
        self.U = len(self.dates)
        self.week_of = np.array([wpos[(y, w)] for y, w, _ in iso], dtype=np.int64)
        self.wd = np.array([j for _, _, j in iso], dtype=np.int64)            # 1..7
        self.grid = np.full((self.W, 7), -1, dtype=np.int64)
        self.grid[self.week_of, self.wd - 1] = np.arange(self.U)
        upos = {d: i for i, d in enumerate(self.dates)}
        self.u_of_s, self.s_of_u = {}, {}
        for idx, sess in sessions_by_index.items():
            u = np.array([upos[d] for d in sess], dtype=np.int64)
            inv = np.full(self.U, -1, dtype=np.int64)
            inv[u] = np.arange(len(sess))
            self.u_of_s[idx], self.s_of_u[idx] = u, inv

    # -- maps: tgt_u[draw, u] = the union-date index the signal of date u is applied to, -1 = dropped
    def identity(self) -> np.ndarray:
        return np.arange(self.U, dtype=np.int64)[None, :]

    def from_week_perms(self, pis: np.ndarray) -> np.ndarray:
        """pis (D, W): week w -> week pis[d, w].  The weekday never changes."""
        return self.grid[pis[:, self.week_of], (self.wd - 1)[None, :]]

    def null_a(self, n_draws: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
        rng = np.random.default_rng(seed)
        pis = np.stack([rng.permutation(self.W) for _ in range(n_draws)]) if n_draws else np.zeros((0, self.W), np.int64)
        return self.from_week_perms(pis), pis

    def null_b(self) -> tuple[np.ndarray, np.ndarray]:
        k = np.arange(1, self.W, dtype=np.int64)
        pis = (np.arange(self.W, dtype=np.int64)[None, :] + k[:, None]) % self.W
        return self.from_week_perms(pis), pis

    def null_ref(self, n_draws: int, seed: int) -> np.ndarray:
        """Reference only: a uniform permutation of the sessions within each ISO weekday."""
        rng = np.random.default_rng(seed)
        out = np.tile(np.arange(self.U, dtype=np.int64), (n_draws, 1))
        groups = [np.flatnonzero(self.wd == j) for j in range(1, 8)]
        for d in range(n_draws):
            for g in groups:
                if len(g) > 1:
                    out[d, g] = g[rng.permutation(len(g))]
        return out

    def to_index(self, idx: str, tgt_u: np.ndarray) -> np.ndarray:
        """(D, U) union map -> (D, n_sessions of idx): target SESSION index of each source session, -1 = dropped."""
        tu = tgt_u[:, self.u_of_s[idx]]
        return np.where(tu >= 0, self.s_of_u[idx][np.maximum(tu, 0)], -1)


# ---------------------------------------------------------------------------
# outcome rows (P2 / P3) - one code path for the discovery table and the holdout rows
# ---------------------------------------------------------------------------
class Table:
    """Outcome rows of one index: [session, fill bar 09:20..14:14, direction UP/DOWN(, exit EOD/H60/STOP30)]."""
    E_FIELDS = (("status_e", np.int8), ("strike", np.float64), ("lot", np.int32), ("buy", np.float64),
                ("open", np.float64))
    X_FIELDS = (("status_x", np.int8), ("exit_min", np.int16), ("sell", np.float64), ("gross", np.float64),
                ("costs", np.float64), ("net", np.float64), ("pct", np.float64), ("pts", np.float64))

    def __init__(self, index: str, sessions: list[str]):
        self.index, self.sessions = index, list(sessions)
        n = len(sessions)
        self.expiry: list = [None] * n
        self.dte = np.full(n, -1, dtype=np.int16)
        for name, dt in self.E_FIELDS:
            fill = ST_NOT_COMPUTED if name == "status_e" else (0 if dt is np.int32 else np.nan)
            setattr(self, name, np.full((n, NF, 2), fill, dtype=dt))
        for name, dt in self.X_FIELDS:
            fill = ST_NOT_COMPUTED if name == "status_x" else (-1 if dt is np.int16 else np.nan)
            setattr(self, name, np.full((n, NF, 2, 3), fill, dtype=dt))

    def seal(self) -> "Table":
        """Only OK rows carry a result (P3.1)."""
        bad = self.status_x != ST_OK
        for name in ("sell", "gross", "costs", "net", "pct", "pts"):
            getattr(self, name)[bad] = np.nan
        self.exit_min[bad] = -1
        return self

    def arrays(self) -> dict:
        out = {"dte": self.dte}
        for name, _ in self.E_FIELDS + self.X_FIELDS:
            out[name] = getattr(self, name)
        return out


def save_tables(path_npz: str, tabs: dict) -> None:
    blob = {}
    for idx, t in tabs.items():
        for name, arr in t.arrays().items():
            blob[f"{idx}__{name}"] = arr
    tmp = path_npz + ".tmp.npz"
    np.savez_compressed(tmp, **blob)
    os.replace(tmp, path_npz)


def load_tables(path_npz: str, sidecar: dict) -> dict:
    tabs = {}
    with np.load(path_npz) as z:
        for idx in sidecar["indexes"]:
            t = Table(idx, sidecar["sessions"][idx])
            t.expiry = list(sidecar["expiry"][idx])
            for name in ["dte"] + [n for n, _ in Table.E_FIELDS + Table.X_FIELDS]:
                arr = z[f"{idx}__{name}"]
                if arr.shape != getattr(t, name).shape:
                    raise Refusal(f"outcome table {idx}.{name} has shape {arr.shape}, expected {getattr(t, name).shape}")
                setattr(t, name, arr)
            tabs[idx] = t.seal()
    return tabs


class ContractDay:
    """One option contract on one day, laid on the 09:15..15:29 minute grid (exact minutes, nothing filled)."""
    __slots__ = ("present", "o", "h", "l", "c", "vol", "c_traded", "nxt")

    def __init__(self, rows: list):
        present = [False] * NBAR
        o, h, l, c = [math.nan] * NBAR, [math.nan] * NBAR, [math.nan] * NBAR, [math.nan] * NBAR
        vol = [0] * NBAR
        for r in rows:
            b = int(r[0][:2]) * 60 + int(r[0][3:]) - BAR0
            if 0 <= b < NBAR:
                present[b] = True
                o[b], h[b], l[b], c[b], vol[b] = r[1], r[2], r[3], r[4], r[5]
        self.present, self.o, self.h, self.l, self.c, self.vol = present, o, h, l, c, vol
        traded = np.array([p and v > 0 for p, v in zip(present, vol)], dtype=bool)
        self.c_traded = np.where(traded, np.array(c, dtype=np.float64), np.inf)   # close of traded bars, +inf otherwise
        first = np.where(traded, np.arange(NBAR), NBAR)
        nxt = np.minimum.accumulate(first[::-1])[::-1]
        self.nxt = np.append(nxt, NBAR).tolist()              # nxt[m] = first traded bar >= m, NBAR = none (up to 15:29)


def _fill_row(T: Table, si: int, fi: int, di: int, cd: ContractDay, lot: int, day_obj: date, exch: str,
              idx_close: list, spot: float) -> None:
    b = fi + (FILL0 - BAR0)                                   # the fill bar on the minute grid
    if not cd.present[b]:
        T.status_e[si, fi, di] = ST_NO_DATA
        T.status_x[si, fi, di, :] = ST_NO_DATA
        return
    if cd.vol[b] <= 0:
        T.status_e[si, fi, di] = ST_NO_FILL
        T.status_x[si, fi, di, :] = ST_NO_FILL
        return
    buy = cd.h[b]                                             # entry at the HIGH of the fill bar
    T.status_e[si, fi, di] = ST_OK
    T.buy[si, fi, di] = buy
    T.open[si, fi, di] = cd.o[b]
    T.lot[si, fi, di] = lot
    x_eod = cd.nxt[B_EOD]
    x_h60 = cd.nxt[b + 60]
    level = STOP_FRACTION * buy
    hit = np.flatnonzero(cd.c_traded[b:B_STOP_LAST + 1] <= level)
    x_stop = cd.nxt[b + int(hit[0]) + 1] if hit.size else x_eod
    sign = 1.0 if di == 0 else -1.0
    prem = buy * lot
    for e, x in enumerate((x_eod, x_h60, x_stop)):
        if x >= NBAR:
            T.status_x[si, fi, di, e] = ST_NO_EXIT
            continue
        sell = cd.l[x]                                        # exit at the LOW of the exit bar
        gross = round((sell - buy) * lot, 2)
        costs = py_funcs.option_round_trip("LONG", buy, sell, lot, day=day_obj, exchange=exch)
        net = round(gross - costs, 2)
        T.status_x[si, fi, di, e] = ST_OK
        T.exit_min[si, fi, di, e] = x + BAR0
        T.sell[si, fi, di, e] = sell
        T.gross[si, fi, di, e] = gross
        T.costs[si, fi, di, e] = costs
        T.net[si, fi, di, e] = net
        T.pct[si, fi, di, e] = 100.0 * net / prem
        T.pts[si, fi, di, e] = sign * (idx_close[x] - spot)


def build_table(market, sessions: list[str], need: list | None = None, progress: bool = False) -> Table:
    """Outcome rows of one index.  need=None: every (fill bar, direction) of every session (discovery).
    need[si] = set of (fi, di): only those cells (holdout); every other cell stays NOT_COMPUTED."""
    T = Table(market.index, sessions)
    exch = EXCHANGE[market.index]
    step = market.step
    for si, day in enumerate(sessions):
        idx_close = [math.nan] * NBAR
        for r in market.bars(day):
            b = int(r[0][:2]) * 60 + int(r[0][3:]) - BAR0
            if 0 <= b < NBAR:
                idx_close[b] = r[4]
        expiry = market.expiry(day)
        day_obj = date.fromisoformat(day)
        T.expiry[si] = expiry
        if expiry is not None:
            T.dte[si] = (date.fromisoformat(expiry) - day_obj).days
        groups: dict = {}
        for fi in range(NF):
            dirs = (0, 1) if need is None else [di for di in (0, 1) if (fi, di) in need[si]]
            if not dirs:
                continue
            spot = idx_close[fi + (FILL0 - BAR0) - 1]         # index close of the bar before the fill bar (P2.2)
            if math.isnan(spot) or expiry is None:
                for di in dirs:
                    T.status_e[si, fi, di] = ST_NO_DATA
                    T.status_x[si, fi, di, :] = ST_NO_DATA
                continue
            strike = py_funcs.atm_strike(spot, step)
            for di in dirs:
                T.strike[si, fi, di] = strike
                groups.setdefault((di, strike), []).append((fi, spot))
        for (di, strike), cells in groups.items():
            lot = market.lot_size(expiry, OT[di], strike)
            rows = market.option_bars(day, OT[di], strike, expiry)
            if lot is None or rows is None:
                for fi, _ in cells:
                    T.status_e[si, fi, di] = ST_NO_DATA
                    T.status_x[si, fi, di, :] = ST_NO_DATA
                continue
            cd = ContractDay(rows)
            for fi, spot in cells:
                _fill_row(T, si, fi, di, cd, lot, day_obj, exch, idx_close, spot)
        if progress and (si + 1) % 20 == 0:
            print(f"   {market.index}: {si + 1}/{len(sessions)} sessions")
    return T.seal()


def slow_row(market, day: str, fill_hhmm: str, direction: str, _cache: dict | None = None) -> dict:
    """The same row, written a second time in plain Python straight from the candle lists (the cross-check)."""
    cache = _cache if _cache is not None else {}
    key = ("idx", day)
    if key not in cache:
        cache[key] = {r[0]: r for r in market.bars(day)}
    ibars = cache[key]
    t = C.hhmm(C.minutes(fill_hhmm) - 1)
    out = {"status_e": ST_NO_DATA, "exits": {e: {"status": ST_NO_DATA} for e in EXITS}}
    expiry = market.expiry(day)
    if t not in ibars or expiry is None:
        return out
    spot = ibars[t][4]
    ot = "CE" if direction == "UP" else "PE"
    strike = py_funcs.atm_strike(spot, market.step)
    out["strike"] = strike
    lot = market.lot_size(expiry, ot, strike)
    key = ("opt", day, ot, strike)
    if key not in cache:
        cache[key] = market.option_bars(day, ot, strike, expiry)
    rows = cache[key]
    if lot is None or rows is None:
        return out
    eb = next((r for r in rows if r[0] == fill_hhmm), None)
    if eb is None:
        return out
    if eb[5] <= 0:
        out["status_e"] = ST_NO_FILL
        out["exits"] = {e: {"status": ST_NO_FILL} for e in EXITS}
        return out
    buy = eb[2]
    out.update(status_e=ST_OK, buy=buy, lot=lot, open=eb[1])

    def first_traded(from_hhmm):
        for r in rows:
            if from_hhmm <= r[0] <= "15:29" and r[5] > 0:
                return r
        return None

    eod = first_traded("15:14")
    h60 = first_traded(C.hhmm(C.minutes(fill_hhmm) + 60))
    stop = eod
    level = 0.70 * buy
    for r in rows:
        if fill_hhmm <= r[0] <= "15:12" and r[5] > 0 and r[4] <= level:
            stop = first_traded(C.hhmm(C.minutes(r[0]) + 1))
            break
    sign = 1.0 if direction == "UP" else -1.0
    for name, xb in (("EOD", eod), ("H60", h60), ("STOP30", stop)):
        if xb is None:
            out["exits"][name] = {"status": ST_NO_EXIT}
            continue
        sell = xb[3]
        gross = round((sell - buy) * lot, 2)
        costs = py_funcs.option_round_trip("LONG", buy, sell, lot, day=date.fromisoformat(day),
                                           exchange=EXCHANGE[market.index])
        net = round(gross - costs, 2)
        out["exits"][name] = {"status": ST_OK, "exit": xb[0], "sell": sell, "gross": gross, "costs": costs,
                              "net": net, "pct": 100.0 * net / (buy * lot),
                              "pts": sign * (ibars[xb[0]][4] - spot) if xb[0] in ibars else math.nan}
    return out


def compare_rows(T: Table, market, cells=None) -> tuple[int, list[str]]:
    """Fast table against slow_row on the given cells (all computed cells when None).  (checked, mismatches)"""
    bad, n = [], 0
    cache: dict = {}

    def close(a, b):
        return (math.isnan(a) and math.isnan(b)) or abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))

    for si, day in enumerate(T.sessions):
        cache.clear()
        for fi in range(NF):
            for di in (0, 1):
                if T.status_e[si, fi, di] == ST_NOT_COMPUTED or (cells is not None and (si, fi, di) not in cells):
                    continue
                n += 1
                ref = slow_row(market, day, C.hhmm(FILL0 + fi), DIRS[di], cache)
                tag = f"{T.index} {day} {C.hhmm(FILL0 + fi)} {DIRS[di]}"
                if int(T.status_e[si, fi, di]) != ref["status_e"]:
                    bad.append(f"{tag}: entry status {ST_NAME[int(T.status_e[si, fi, di])]} vs {ST_NAME[ref['status_e']]}")
                    continue
                if ref["status_e"] == ST_OK and not (close(T.buy[si, fi, di], ref["buy"]) and int(T.lot[si, fi, di]) == ref["lot"]
                                                     and close(T.strike[si, fi, di], ref["strike"])
                                                     and close(T.open[si, fi, di], ref["open"])):
                    bad.append(f"{tag}: buy / lot / strike / open differ")
                for e, name in enumerate(EXITS):
                    rx = ref["exits"][name]
                    if int(T.status_x[si, fi, di, e]) != rx["status"]:
                        bad.append(f"{tag} {name}: status {ST_NAME[int(T.status_x[si, fi, di, e])]} vs {ST_NAME[rx['status']]}")
                    elif rx["status"] == ST_OK:
                        if C.hhmm(int(T.exit_min[si, fi, di, e])) != rx["exit"] or not all(
                                close(float(getattr(T, k)[si, fi, di, e]), rx[k])
                                for k in ("sell", "gross", "costs", "net", "pct", "pts")):
                            bad.append(f"{tag} {name}: values differ")
    return n, bad


def non_ok_shares(T: Table) -> dict:
    computed = T.status_e != ST_NOT_COMPUTED
    n = int(computed.sum())
    out = {"rows": n}
    if n == 0:
        return out
    se, sx = T.status_e[computed], T.status_x[computed]
    out["entry"] = {ST_NAME[k]: float((se == k).mean()) for k in (ST_OK, ST_NO_DATA, ST_NO_FILL)}
    out["per_exit_non_ok"] = {name: float((sx[:, e] != ST_OK).mean()) for e, name in enumerate(EXITS)}
    out["per_exit_no_exit"] = {name: float((sx[:, e] == ST_NO_EXIT).mean()) for e, name in enumerate(EXITS)}
    out["non_ok_headline_eod"] = out["per_exit_non_ok"]["EOD"]
    out["non_ok_any_exit"] = float((sx != ST_OK).any(axis=1).mean())
    return out


def print_non_ok(shares: dict) -> None:
    for idx, s in shares.items():
        e = s.get("entry", {})
        print(f"P3.4 non-OK share {idx}: {100 * s.get('non_ok_headline_eod', 0):.3f}% of {s['rows']} rows (EOD, headline)"
              f" | any exit {100 * s.get('non_ok_any_exit', 0):.3f}%"
              f" | entry NO_DATA {100 * e.get('NO_DATA', 0):.3f}% NO_FILL {100 * e.get('NO_FILL', 0):.3f}%"
              f" | NO_EXIT " + " ".join(f"{k} {100 * v:.3f}%" for k, v in s.get("per_exit_no_exit", {}).items()))


# ---------------------------------------------------------------------------
# step: table
# ---------------------------------------------------------------------------
def step_table(study_dir: str, out_dir: str, stamp: str | None) -> None:
    os.makedirs(out_dir, exist_ok=True)
    hashes = study_hashes(study_dir)
    markets = {idx: C.Market(idx, C.DISCOVERY_END) for idx in INDEXES}        # the wall is physical
    sess, exc = {}, {}
    for idx in INDEXES:
        sess[idx], exc[idx] = included_sessions(markets[idx], C.WINDOW_START, C.DISCOVERY_END)
        print_sessions(idx, sess[idx], exc[idx], "DISCOVERY")
    write_json(os.path.join(out_dir, "sessions_discovery.json"),               # P4.2: saved before any outcome
               {"split": "DISCOVERY", "window": [C.WINDOW_START, C.DISCOVERY_END], "sessions": sess,
                "excluded_by_P4.2": exc, "stamp": stamp})
    print("session list saved; building outcome rows ...")
    tabs, shares = {}, {}
    t0 = time.perf_counter()
    for idx in INDEXES:
        tabs[idx] = build_table(markets[idx], sess[idx], None, progress=True)
        shares[idx] = non_ok_shares(tabs[idx])
        md = markets[idx].max_dates()
        if any(v is not None and v > C.DISCOVERY_END for v in (md["index"], md["vix"], md["option_files"], md["option_days"])):
            raise Refusal(f"{idx}: a candle after {C.DISCOVERY_END} is held in memory: {md}")
        print(f"   {idx}: {shares[idx]['rows']} rows in {time.perf_counter() - t0:.1f} s; latest candle held: "
              f"index {md['index']}, option {md['option_files']}; wall fallbacks {markets[idx].wall_stats['fallbacks']}")
    print("cross-check: every row recomputed by the plain-Python second coding ...")
    total_bad = []
    for idx in INDEXES:
        n, bad = compare_rows(tabs[idx], markets[idx])
        print(f"   {idx}: {n} rows compared, {len(bad)} mismatches")
        total_bad += bad
    if total_bad:
        for b in total_bad[:50]:
            print("   MISMATCH " + b)
        raise Refusal(f"{len(total_bad)} rows differ between the two codings - the table was NOT saved")
    npz = os.path.join(out_dir, "outcome_discovery.npz")
    save_tables(npz, tabs)
    side = {"split": "DISCOVERY", "indexes": list(INDEXES), "sessions": sess,
            "expiry": {idx: tabs[idx].expiry for idx in INDEXES},
            "layout": {"fill_bars": [C.hhmm(FILL0), C.hhmm(FILL1)], "directions": list(DIRS), "exits": list(EXITS),
                       "status": {str(k): v for k, v in ST_NAME.items()},
                       "arrays": "<INDEX>__<field>[session, fill bar, direction(, exit)]; pct is in percent"},
            "non_ok": shares, "hashes": hashes, "py_funcs_sha256": sha256_file(PY_FUNCS_PATH),
            "npz_sha256": sha256_file(npz), "stamp": stamp, "readings": READINGS}
    write_json(os.path.join(out_dir, "outcome_discovery.json"), side)
    print_non_ok(shares)
    print(f"saved {npz}\nsaved {os.path.join(out_dir, 'outcome_discovery.json')}")


# ---------------------------------------------------------------------------
# step: signals
# ---------------------------------------------------------------------------
def load_candidates(modules, library: list[dict]) -> tuple[dict, list[str]]:
    """Import the signal modules and line their CANDIDATES up with the library.  (candidates, warnings)"""
    lib = {c["id"]: c for c in library}
    found, warnings, problems = {}, [], []
    for m in modules:
        mod = importlib.import_module(m) if isinstance(m, str) else m
        name = getattr(mod, "__name__", str(m))
        for cid, spec in getattr(mod, "CANDIDATES").items():
            if cid in found:
                problems.append(f"{cid}: defined in both {found[cid]['module']} and {name}")
                continue
            if cid not in lib:
                problems.append(f"{cid} ({name}): not in library.json")
                continue
            if lib[cid]["struck"]:
                warnings.append(f"{cid} ({name}): struck by Addendum 1 - not run")
                continue
            if not callable(spec.get("fn")) or not isinstance(spec.get("centre"), dict) \
                    or not isinstance(spec.get("neighbours"), list):
                problems.append(f"{cid} ({name}): needs fn, centre (dict) and neighbours (list)")
                continue
            nbs = spec["neighbours"]
            if len(nbs) != 2 * lib[cid]["n_params"] or len(nbs) > 4:
                problems.append(f"{cid} ({name}): {len(nbs)} neighbours, the library has {lib[cid]['n_params']} "
                                f"parameters (expected {2 * lib[cid]['n_params']}, at most 4)")
                continue
            labels = [nb.get("label") for nb in nbs]
            if len(set(labels)) != len(labels) or "centre" in labels or not all(isinstance(x, str) for x in labels):
                problems.append(f"{cid} ({name}): neighbour labels must be distinct strings")
                continue
            for nb in nbs:
                if not isinstance(nb.get("params"), dict) or set(nb["params"]) != set(spec["centre"]):
                    problems.append(f"{cid} ({name}) {nb.get('label')}: params must be the FULL parameter dict")
                    break
                moved = [k for k in spec["centre"] if nb["params"][k] != spec["centre"][k]]
                if len(moved) != 1:
                    warnings.append(f"{cid} {nb['label']}: {len(moved)} parsed values differ from the centre "
                                    f"({moved}) - check that only ONE library parameter moved (P5.2)")
            found[cid] = {"fn": spec["fn"], "centre": spec["centre"], "neighbours": nbs, "module": name}
    for c in library:
        if not c["struck"] and c["id"] not in found:
            problems.append(f"{c['id']}: no signal module provides it")
    if problems:
        raise Refusal("signal modules do not match library.json:\n   " + "\n   ".join(problems))
    ordered = {c["id"]: found[c["id"]] for c in library if not c["struck"]}
    return ordered, warnings


def run_signals(markets: dict, sessions: dict, cands: dict, verbose: bool = True) -> tuple[dict, list[str]]:
    """Every candidate variant on every session of both indices, each proven by ctx.check_no_lookahead.
    Returns ({id: [{"label", "params", "signals": {index: {day: [t, direction]}}}]}, offenders)."""
    out, offenders = {}, []
    for cid, spec in cands.items():
        variants = [("centre", spec["centre"])] + [(nb["label"], nb["params"]) for nb in spec["neighbours"]]
        rows = []
        t0 = time.perf_counter()
        for label, params in variants:
            sig = {}
            for idx, market in markets.items():
                sig[idx] = {}
                for day in sessions[idx]:
                    tag = f"{cid} [{label}] {idx} {day}"
                    try:
                        problems = C.check_no_lookahead(spec["fn"], market.day_ctx(day), params)
                        r = spec["fn"](market.day_ctx(day), **params)
                    except Exception as e:                    # noqa: BLE001 - a signal must return None, not raise
                        offenders.append(f"{tag}: raised {type(e).__name__}: {e}")
                        continue
                    offenders += [f"{cid} [{label}] {p}" for p in problems]
                    if r is None or problems:
                        continue
                    sig[idx][day] = [r[0], r[1]]
            rows.append({"label": label, "params": params, "signals": sig})
        out[cid] = rows
        if verbose:
            parts = []
            for v in rows:
                parts.append(f"{v['label']}: " + " ".join(
                    f"{idx} {len(v['signals'][idx])} (UP {sum(1 for s in v['signals'][idx].values() if s[1] == 'UP')}"
                    f"/DOWN {sum(1 for s in v['signals'][idx].values() if s[1] == 'DOWN')})" for idx in markets))
            print(f"{cid}  [{time.perf_counter() - t0:.1f} s]")
            for p in parts:
                print("     " + p)
    return out, offenders


def step_signals(study_dir: str, out_dir: str, stamp: str | None, modules=None, verbose: bool = True) -> None:
    os.makedirs(out_dir, exist_ok=True)
    hashes = study_hashes(study_dir)
    library = load_library(study_dir)
    cands, warnings = load_candidates(modules if modules is not None else SIGNAL_MODULES, library)
    markets = {idx: C.Market(idx, C.DISCOVERY_END) for idx in INDEXES}
    sessions = {}
    for idx in INDEXES:
        sessions[idx], exc = included_sessions(markets[idx], C.WINDOW_START, C.DISCOVERY_END)
        if verbose:
            print(f"DISCOVERY sessions {idx}: {len(sessions[idx])} ({sessions[idx][0]} .. {sessions[idx][-1]})")
    if verbose:
        print(f"candidates to run: {len(cands)} (struck: {[c['id'] for c in library if c['struck']]}) - signal COUNTS only")
        for w in warnings:
            print("   note: " + w)
    sigs, offenders = run_signals(markets, sessions, cands, verbose=verbose)
    for idx in INDEXES:
        md = markets[idx].max_dates()
        if any(v is not None and v > C.DISCOVERY_END for v in (md["index"], md["vix"], md["option_files"], md["option_days"])):
            raise Refusal(f"{idx}: a candle after {C.DISCOVERY_END} is held in memory: {md}")
    if offenders:
        if verbose:
            print(f"\nABORT: {len(offenders)} look-ahead / signal problems - signals_discovery.json was NOT written")
            for o in offenders[:300]:
                print("   " + o)
            if len(offenders) > 300:
                print(f"   ... and {len(offenders) - 300} more")
        bad_ids = sorted({o.split(" [")[0] for o in offenders})
        raise Refusal(f"offending candidates: {bad_ids}")
    write_json(os.path.join(out_dir, "signals_discovery.json"),
               {"split": "DISCOVERY", "sessions": sessions, "hashes": hashes, "stamp": stamp,
                "struck": [c["id"] for c in library if c["struck"]], "warnings": warnings,
                "lookahead_checks": "ctx.check_no_lookahead on every (variant, index, day): 0 problems",
                "candidates": {cid: {"module": cands[cid]["module"], "variants": rows} for cid, rows in sigs.items()}})
    if verbose:
        print(f"saved {os.path.join(out_dir, 'signals_discovery.json')}")


# ---------------------------------------------------------------------------
# the score S (P6) - ONE code path for the real score and every null draw
# ---------------------------------------------------------------------------
def tstat(x: np.ndarray, min_n: int, axis: int):
    """t = mean / (sample sd / sqrt(n)) over the non-NaN entries along `axis`; 0 if n < min_n or sd = 0.
    Returns (t, n, mean, sd)."""
    ok = ~np.isnan(x)
    n = ok.sum(axis=axis)
    s = np.where(ok, x, 0.0).sum(axis=axis)
    mean = s / np.maximum(n, 1)
    dev = np.where(ok, x - np.expand_dims(mean, axis), 0.0)
    sd = np.sqrt((dev * dev).sum(axis=axis) / np.maximum(n - 1, 1))
    good = (n >= min_n) & (n >= 2) & (sd > 1e-9 * (1.0 + np.abs(mean)))
    t = np.where(good, mean / np.where(good, sd / np.sqrt(np.maximum(n, 1)), 1.0), 0.0)
    return t, n, mean, sd


def gather(arr: np.ndarray, sig_f: np.ndarray, sig_d: np.ndarray, tgt: np.ndarray) -> np.ndarray:
    """arr [session, fill bar, direction, ...]; sig_f / sig_d (C, n_src): each source session's signal (fill-bar
    index, -1 = none; direction 0/1); tgt (D, n_src): the session the signal is applied to (-1 = dropped).
    Returns (D, C, n_src, ...) with NaN where there is no signal or no target."""
    valid = (sig_f >= 0)[None, :, :] & (tgt >= 0)[:, None, :]
    out = arr[np.maximum(tgt, 0)[:, None, :], np.maximum(sig_f, 0)[None, :, :], sig_d[None, :, :]].astype(np.float64, copy=False)
    out[~valid] = np.nan
    return out


def S_of(per_index: list, min_n: int) -> np.ndarray:
    """per_index: one (D, C, n_src, 3) array of per-trade results per index (NaN = no OK trade).
    P6.2: per index the median over the 3 exits of t; S = the smaller of the indices.  Returns (D, C)."""
    meds = [np.median(tstat(x, min_n, axis=2)[0], axis=-1) for x in per_index]
    return np.minimum.reduce(meds)


def S_under(arr_by_index: dict, sigs: dict, cal: Calendar, tgt_u: np.ndarray, min_n: int, chunk: int = 100) -> np.ndarray:
    """S of every signal row under every map of tgt_u (D, U).  The identity map gives the real score."""
    out = []
    for a in range(0, tgt_u.shape[0], chunk):
        per = [gather(arr_by_index[idx], sigs[idx]["f"], sigs[idx]["d"], cal.to_index(idx, tgt_u[a:a + chunk]))
               for idx in cal.indexes]
        out.append(S_of(per, min_n))
    n_rows = next(iter(sigs.values()))["f"].shape[0]
    return np.concatenate(out) if out else np.zeros((0, n_rows))


def adjusted_p(real_S: np.ndarray, null_max: np.ndarray) -> np.ndarray:
    """P8.4: (1 + draws whose maximum >= the real S) / (1 + draws)."""
    return (1.0 + (null_max[None, :] >= real_S[:, None] - 1e-9).sum(axis=1)) / (1.0 + len(null_max))


def quantiles(x: np.ndarray) -> dict:
    if len(x) == 0:
        return {}
    q = {f"q{p:02d}": float(np.percentile(x, p)) for p in (5, 25, 50, 75, 90, 95, 99)}
    q.update(min=float(x.min()), max=float(x.max()), mean=float(x.mean()), draws=int(len(x)))
    return q


def null_analysis(net_by_index: dict, sigs: dict, cal: Calendar, n_family: int, min_n: int, n_draws: int,
                  seed: int, with_ref: bool = True) -> dict:
    """Real S of every signal row, the null maxima over the first n_family rows (the centre candidates), and
    the adjusted p of the family rows under each null."""
    real = S_under(net_by_index, sigs, cal, cal.identity(), min_n)[0]
    tgt_a, pis_a = cal.null_a(n_draws, seed)
    tgt_b, pis_b = cal.null_b()
    fam = {idx: {"f": sigs[idx]["f"][:n_family], "d": sigs[idx]["d"][:n_family]} for idx in cal.indexes}
    out = {"S": real, "maps": {"A": tgt_a, "B": tgt_b}, "perms": {"A": pis_a, "B": pis_b}, "null_S": {}, "max": {}, "p": {}}
    todo = [("A", tgt_a), ("B", tgt_b)]
    if with_ref:
        tgt_r = cal.null_ref(n_draws, seed)
        out["maps"]["REF"] = tgt_r
        todo.append(("REF", tgt_r))
    for name, tgt in todo:
        s = S_under(net_by_index, fam, cal, tgt, min_n)
        out["null_S"][name] = s
        out["max"][name] = s.max(axis=1) if s.shape[0] else np.zeros(0)
        out["p"][name] = adjusted_p(real[:n_family], out["max"][name])
    out["p"]["used"] = np.maximum(out["p"]["A"], out["p"]["B"])               # the gate uses the LARGER
    return out


# ---------------------------------------------------------------------------
# per-candidate statistics and the gates (P6 / P7)
# ---------------------------------------------------------------------------
def signal_arrays(variant_signals: list, sessions: dict) -> dict:
    """[{index: {day: [t, direction]}}, ...] -> {index: {"f": (C, n) fill-bar index or -1, "d": (C, n) 0/1}}"""
    out = {}
    for idx, sess in sessions.items():
        pos = {d: i for i, d in enumerate(sess)}
        f = np.full((len(variant_signals), len(sess)), -1, dtype=np.int64)
        d = np.zeros((len(variant_signals), len(sess)), dtype=np.int64)
        for ci, sig in enumerate(variant_signals):
            for day, (t, direction) in sig.get(idx, {}).items():
                if day not in pos:
                    raise Refusal(f"a signal is dated {day}, which is not a {idx} session of the outcome table")
                fi = C.minutes(t) + 1 - FILL0                 # the fill bar is t + 1
                if not 0 <= fi < NF or direction not in DIRS:
                    raise Refusal(f"signal {idx} {day} {t} {direction} is outside the protocol window")
                f[ci, pos[day]] = fi
                d[ci, pos[day]] = DIRS.index(direction)
        out[idx] = {"f": f, "d": d}
    return out


def variant_book(tabs: dict, sigs: dict, cal: Calendar, ci: int, min_n: int, months, want_trades: bool) -> dict:
    """Everything reportable about one signal row (a centre candidate or a neighbour)."""
    per_index, trades = {}, []
    comb = np.zeros(cal.U)
    has = np.zeros(cal.U, dtype=bool)
    med_t, med_t_pct = [], []
    for idx in cal.indexes:
        T = tabs[idx]
        f, d = sigs[idx]["f"][ci], sigs[idx]["d"][ci]
        ss = np.flatnonzero(f >= 0)
        ff, dd = f[ss], d[ss]
        st = T.status_x[ss, ff, dd]
        if (st == ST_NOT_COMPUTED).any():
            raise Refusal(f"{idx}: a signal points at an outcome row that was never computed")
        net, pct = T.net[ss, ff, dd], T.pct[ss, ff, dd]
        prem = (T.buy[ss, ff, dd] * T.lot[ss, ff, dd])
        t_net, n_net, mean_net, sd_net = tstat(net, min_n, axis=0)
        t_pct, _, mean_pct, sd_pct = tstat(pct, min_n, axis=0)
        exits = {}
        for e, name in enumerate(EXITS):
            ok = st[:, e] == ST_OK
            x = net[ok, e]
            wins, losses = x[x > 0].sum(), -x[x < 0].sum()
            exits[name] = {
                "signals": int(len(ss)), "n": int(ok.sum()), "unpriced": int((~ok).sum()),
                "unpriced_share": float((~ok).mean()) if len(ss) else 0.0,
                "net": float(x.sum()), "mean": float(mean_net[e]) if ok.any() else None,
                "sd": float(sd_net[e]) if ok.sum() >= 2 else None, "t": float(t_net[e]),
                "win_share": float((x > 0).mean()) if ok.any() else None,
                "profit_factor": float(wins / losses) if losses > 0 else None,
                "net_pct_sum": float(pct[ok, e].sum()), "net_pct_mean": float(mean_pct[e]) if ok.any() else None,
                "net_pct_pooled": float(100.0 * x.sum() / prem[ok].sum()) if ok.any() else None,
                "premium_paid": float(prem[ok].sum()), "t_pct": float(t_pct[e])}
        ok_eod, ok_stop = st[:, 0] == ST_OK, st[:, 2] == ST_OK
        xm = T.exit_min[ss, ff, dd]
        identical = int((ok_eod & ok_stop & (xm[:, 0] == xm[:, 2]) & (net[:, 0] == net[:, 2])).sum())
        med_t.append(float(np.median(t_net)))
        med_t_pct.append(float(np.median(t_pct)))
        per_index[idx] = {"median_t": med_t[-1], "median_t_pct": med_t_pct[-1], "exits": exits,
                          "identical_eod_stop30": identical,
                          "directions": {DIRS[k]: int((dd == k).sum()) for k in (0, 1)}}
        u = cal.u_of_s[idx][ss[ok_eod]]
        np.add.at(comb, u, net[ok_eod, 0])
        has[u] = True
        if want_trades:
            for k, si in enumerate(ss.tolist()):
                fi, di = int(ff[k]), int(dd[k])
                se = int(T.status_e[si, fi, di])
                tr = {"index": idx, "day": T.sessions[si], "signal_minute": C.hhmm(FILL0 + fi - 1),
                      "fill_bar": C.hhmm(FILL0 + fi), "direction": DIRS[di], "option": OT[di],
                      "status": ST_NAME[se], "strike": float(T.strike[si, fi, di]), "expiry": T.expiry[si],
                      "dte": int(T.dte[si]),
                      "lot": int(T.lot[si, fi, di]) if se == ST_OK else None,
                      "buy": float(T.buy[si, fi, di]), "fill_bar_open": float(T.open[si, fi, di]), "exits": {}}
                for e, name in enumerate(EXITS):
                    sx = int(T.status_x[si, fi, di, e])
                    row = {"status": ST_NAME[sx]}
                    if sx == ST_OK:
                        row.update(exit=C.hhmm(int(T.exit_min[si, fi, di, e])), sell=float(T.sell[si, fi, di, e]),
                                   gross=float(T.gross[si, fi, di, e]), costs=float(T.costs[si, fi, di, e]),
                                   net=float(T.net[si, fi, di, e]), net_pct=float(T.pct[si, fi, di, e]),
                                   index_points=float(T.pts[si, fi, di, e]))
                    tr["exits"][name] = row
                trades.append(tr)
    vals = comb[has]
    dates = [cal.dates[i] for i in np.flatnonzero(has)]
    total = float(vals.sum())
    by_month = {m: float(sum(v for v, dt in zip(vals, dates) if dt[:7] == m)) for m in months}
    order = np.argsort(-vals, kind="stable")
    best = float(vals[order[0]]) if len(vals) else 0.0
    top3 = float(vals[order[:3]].sum()) if len(vals) else 0.0
    combined = {"trade_dates": int(len(vals)), "total": total, "mean_per_date": total / len(vals) if len(vals) else None,
                "by_month": by_month,
                "months_positive": int(sum(v > 0 for v in by_month.values())),
                "max_month_share": (max(by_month.values()) / total) if (total > 0 and by_month) else None,
                "best_date": dates[order[0]] if len(vals) else None, "best_date_net": best,
                "net_without_best_date": total - best,
                "best3_dates": [dates[i] for i in order[:3]], "best3_net": top3,
                "best3_share": (top3 / total) if total > 0 else None,
                "by_date": {dt: float(v) for dt, v in zip(dates, vals)}}
    out = {"S_check": min(med_t) if med_t else 0.0, "S_pct": min(med_t_pct) if med_t_pct else 0.0,
           "per_index": per_index, "combined": combined}
    if want_trades:
        out["trades"] = sorted(trades, key=lambda r: (r["day"], r["index"]))
    return out


def evaluate_gates(g: dict) -> dict:
    """P7 from plain numbers.  g: n_ok {index: n}, unpriced_share {index: share}, month_net {month: net},
    combined_total, best_date_net, neighbours [{label, combined_net, S}], p_used, pct_total {index: value}."""
    out = {}
    out["a"] = {"pass": bool(all(v >= GATE_MIN_TRADES for v in g["n_ok"].values())
                             and all(v <= GATE_MAX_UNPRICED for v in g["unpriced_share"].values())),
                "rule": "at least 30 OK trades per index and at most 5% of signals unpriced on either index (EOD)",
                "n_ok": g["n_ok"], "unpriced_share": g["unpriced_share"]}
    total = g["combined_total"]
    months = g["month_net"]
    pos = sum(1 for v in months.values() if v > 0)
    share = (max(months.values()) / total) if (total > 0 and months) else None
    out["b"] = {"pass": bool(pos >= GATE_MONTHS_POSITIVE and share is not None and share <= GATE_MAX_MONTH_SHARE),
                "rule": "combined net > 0 in at least 3 of the 4 months and no month above 70% of the total",
                "months_positive": pos, "max_month_share": share, "month_net": months, "combined_total": total}
    nb = g["neighbours"]
    out["c"] = {"pass": bool(all(x["combined_net"] > 0 and x["S"] >= 0 for x in nb)),
                "rule": "every neighbour has combined net > 0 and S >= 0",
                "neighbours": [{"label": x["label"], "combined_net": x["combined_net"], "S": x["S"],
                                "pass": bool(x["combined_net"] > 0 and x["S"] >= 0)} for x in nb]}
    rest = total - g["best_date_net"]
    out["d"] = {"pass": bool(rest > 0), "rule": "combined net > 0 after removing the single best date",
                "net_without_best_date": rest, "best_date_net": g["best_date_net"]}
    out["e"] = {"pass": bool(g["p_used"] <= GATE_P), "rule": "adjusted p (the larger of the two nulls) <= 0.25",
                "p_used": g["p_used"]}
    out["f"] = {"pass": bool(all(v > 0 for v in g["pct_total"].values())),
                "rule": "total net % of premium (EOD) > 0 on both indices", "pct_total": g["pct_total"]}
    return out


def pick_winner(order: list[str], S: dict, passed: dict) -> str | None:
    """P9: the highest S among candidates passing every gate; ties go to the earlier library entry."""
    best = None
    for cid in order:                                         # library order, strict > keeps the earlier one on ties
        if passed[cid] and (best is None or S[cid] > S[best]):
            best = cid
    return best


# ---------------------------------------------------------------------------
# run log, freeze, the holdout guard
# ---------------------------------------------------------------------------
def update_run_log(out_dir: str, hashes: dict, py_funcs_sha: str, stamp: str, reason: str | None, label: str) -> tuple[list, dict]:
    path = os.path.join(out_dir, "run_log.json")
    log = read_json(path) if os.path.isfile(path) else []
    if log:
        last = log[-1]
        diff = hash_diff(last["hashes"], hashes)
        if last.get("py_funcs_sha256") != py_funcs_sha:
            diff.append("py_funcs.py: content changed")
        if diff and not reason:
            raise Refusal("the study files changed since run " + str(last["run"]) + " and no --reason was given (P4.3):\n   "
                          + "\n   ".join(diff))
        why = reason or "re-run, no file changed"
    else:
        diff = []
        why = reason or "first scoring run"
    entry = {"run": len(log) + 1, "stamp": stamp, "reason": why, "changed_since_previous_run": diff, "label": label,
             "hashes": hashes, "py_funcs_sha256": py_funcs_sha, "status": "started"}
    log.append(entry)
    write_json(path, log)
    return log, entry


def freeze_path(study_dir: str, out_dir: str) -> str | None:
    for p in (os.path.join(out_dir, "freeze.json"), os.path.join(study_dir, "freeze.json")):
        if os.path.isfile(p):
            return p
    return None


def holdout_guard(study_dir: str, out_dir: str, py_funcs_path: str = PY_FUNCS_PATH) -> dict:
    """P3.3: refuse unless freeze.json exists and every hash still matches; never run twice."""
    p = freeze_path(study_dir, out_dir)
    if p is None:
        raise Refusal("no freeze.json - the holdout stays closed (P3.3 / P9)")
    fz = read_json(p)
    if not fz.get("winner") or "hashes" not in fz or "params" not in fz or not fz.get("stamp"):
        raise Refusal(f"{p} is not a complete freeze (winner, params, hashes, stamp)")
    diff = hash_diff(fz["hashes"], study_hashes(study_dir))
    if fz.get("py_funcs_sha256") != sha256_file(py_funcs_path):
        diff.append("py_funcs.py: content changed")
    if diff:
        raise Refusal("the study changed after the freeze - the holdout stays closed (P3.3):\n   " + "\n   ".join(diff))
    if os.path.exists(os.path.join(out_dir, "results_holdout.json")):
        raise Refusal("results_holdout.json already exists - the holdout is one shot and is never overwritten (P4.3)")
    return fz


# ---------------------------------------------------------------------------
# step: score
# ---------------------------------------------------------------------------
def step_score(study_dir: str, out_dir: str, stamp: str | None, reason: str | None, n_draws: int = N_DRAWS,
               quiet: bool = False) -> dict:
    say = (lambda *a, **k: None) if quiet else print
    if not stamp:
        raise Refusal("--step score needs --stamp <timestamp text> (the engine does not invent one)")
    for name in ("outcome_discovery.npz", "outcome_discovery.json", "signals_discovery.json"):
        if not os.path.isfile(os.path.join(out_dir, name)):
            raise Refusal(f"{name} is missing - run --step table and --step signals first")
    hashes = study_hashes(study_dir)
    py_sha = sha256_file(PY_FUNCS_PATH)
    post_holdout = os.path.exists(os.path.join(out_dir, "results_holdout.json"))
    label = "POST-HOLDOUT, EXPLORATORY" if post_holdout else "DISCOVERY"
    log, entry = update_run_log(out_dir, hashes, py_sha, stamp, reason, label)       # FIRST: the run log
    log_path = os.path.join(out_dir, "run_log.json")
    say(f"run {entry['run']} [{label}] stamp {stamp} - reason: {entry['reason']}")

    def fail(msg):
        entry["status"] = "refused: " + msg.splitlines()[0]
        write_json(log_path, log)
        raise Refusal(msg)

    if not post_holdout:                                      # a freeze from an earlier run is void now
        for p in (os.path.join(out_dir, "freeze.json"), os.path.join(study_dir, "freeze.json")):
            if os.path.isfile(p):
                os.remove(p)
                entry.setdefault("notes", []).append(f"removed the freeze.json of an earlier run ({p})")

    side = read_json(os.path.join(out_dir, "outcome_discovery.json"))
    sig_file = read_json(os.path.join(out_dir, "signals_discovery.json"))
    npz = os.path.join(out_dir, "outcome_discovery.npz")
    if sha256_file(npz) != side.get("npz_sha256"):
        fail("outcome_discovery.npz does not match its sidecar - rebuild with --step table")
    stale = [k for k in ("protocol.md", "engine.py", "ctx.py") if side["hashes"].get(k) != hashes.get(k)]
    if side.get("py_funcs_sha256") != py_sha:
        stale.append("py_funcs.py")
    if stale:
        fail(f"the outcome table was built with other versions of {stale} - full discovery re-run needed (P4.3): --step table")
    diff = hash_diff(sig_file["hashes"], hashes)
    if diff:
        fail("signals_discovery.json was made with other study files - full discovery re-run needed (P4.3): --step signals\n   "
             + "\n   ".join(diff))
    if sig_file["sessions"] != side["sessions"]:
        fail("the signal file and the outcome table do not have the same session list")
    entry["inputs"] = {"outcome_discovery.npz": side["npz_sha256"],
                       "signals_discovery.json": sha256_file(os.path.join(out_dir, "signals_discovery.json"))}

    library = load_library(study_dir)
    family = [c for c in library if not c["struck"]]
    ids = [c["id"] for c in family]
    if list(sig_file["candidates"]) != ids:
        fail("signals_discovery.json does not hold exactly the non-struck library candidates in library order")
    tabs = load_tables(npz, side)
    sessions = side["sessions"]
    cal = Calendar(sessions)

    # signal rows: the centre candidates first (the P8 family), then every neighbour
    rows, row_of, nb_rows = [], {}, {}
    for cid in ids:
        v = sig_file["candidates"][cid]["variants"]
        if v[0]["label"] != "centre":
            fail(f"{cid}: the first variant is not the centre")
        row_of[cid] = len(rows)
        rows.append(v[0]["signals"])
    for cid in ids:
        nb_rows[cid] = []
        for v in sig_file["candidates"][cid]["variants"][1:]:
            nb_rows[cid].append((v["label"], v["params"], len(rows)))
            rows.append(v["signals"])
    sigs = signal_arrays(rows, sessions)
    n_family = len(ids)
    net = {idx: tabs[idx].net for idx in cal.indexes}
    pct = {idx: tabs[idx].pct for idx in cal.indexes}

    say(f"family for the max-statistic: {n_family} centre candidates (struck: {[c['id'] for c in library if c['struck']]})")
    print_non_ok(side["non_ok"]) if not quiet else None       # P3.4, before any candidate is scored

    # ---- P8: the nulls, computed before any score is shown ----
    na = null_analysis(net, sigs, cal, n_family, MIN_N_DISCOVERY, n_draws, SEED, with_ref=True)
    S_all = na["S"]
    S_pct_all = S_under(pct, sigs, cal, cal.identity(), MIN_N_DISCOVERY)[0]
    books = {cid: variant_book(tabs, sigs, cal, row_of[cid], MIN_N_DISCOVERY, DISCOVERY_MONTHS, True) for cid in ids}
    table_sd = {idx: float(np.nanstd(tabs[idx].net[..., 0], ddof=1)) for idx in cal.indexes}
    cand_sd = {idx: float(np.median([b["per_index"][idx]["exits"]["EOD"]["sd"] for b in books.values()
                                     if b["per_index"][idx]["exits"]["EOD"]["sd"] is not None] or [math.nan]))
               for idx in cal.indexes}
    p85 = {}
    for name in ("A", "B"):
        q75 = float(np.percentile(na["max"][name], 75)) if len(na["max"][name]) else math.nan
        p85[name] = {"q75_of_null_maximum": q75,
                     "edge_per_trade_50_trades_table_sd": {idx: q75 * table_sd[idx] / math.sqrt(50) for idx in cal.indexes},
                     "edge_per_trade_50_trades_candidate_sd": {idx: q75 * cand_sd[idx] / math.sqrt(50) for idx in cal.indexes}}
    say("\nP8.5 - before any score: the bar a candidate has to clear")
    say(f"   weeks W = {cal.W}; null A = {len(na['max']['A'])} week permutations (seed {SEED}); "
        f"null B = {len(na['max']['B'])} circular shifts (smallest possible p {1 / (1 + len(na['max']['B'])):.4f})")
    for name in ("A", "B"):
        say(f"   null {name}: 75th percentile of the null maximum of S = {p85[name]['q75_of_null_maximum']:.3f}; a 50-trade "
            "candidate needs a mean net per trade of about "
            + ", ".join(f"Rs {p85[name]['edge_per_trade_50_trades_table_sd'][idx]:,.0f} ({idx})" for idx in cal.indexes)
            + " [sd of all table rows]; "
            + ", ".join(f"Rs {p85[name]['edge_per_trade_50_trades_candidate_sd'][idx]:,.0f} ({idx})" for idx in cal.indexes)
            + " [median candidate sd]")

    # ---- P6 / P7 per candidate ----
    cands_out, S, passed = {}, {}, {}
    for c in family:
        cid = c["id"]
        r = row_of[cid]
        b = books[cid]
        if abs(b["S_check"] - float(S_all[r])) > 1e-6:
            fail(f"{cid}: S from the report path ({b['S_check']}) differs from the null path ({float(S_all[r])})")
        nbs = []
        for lab, params, nr in nb_rows[cid]:
            nbk = variant_book(tabs, sigs, cal, nr, MIN_N_DISCOVERY, DISCOVERY_MONTHS, False)
            nbs.append({"label": lab, "params": params, "S": float(S_all[nr]), "S_pct": float(S_pct_all[nr]),
                        "combined_net": nbk["combined"]["total"], "per_index": nbk["per_index"],
                        "combined": {k: v for k, v in nbk["combined"].items() if k != "by_date"}})
        p = {k: float(na["p"][k][r]) for k in ("A", "B", "REF", "used")}
        eod = {idx: b["per_index"][idx]["exits"]["EOD"] for idx in cal.indexes}
        gates = evaluate_gates({
            "n_ok": {idx: eod[idx]["n"] for idx in cal.indexes},
            "unpriced_share": {idx: eod[idx]["unpriced_share"] for idx in cal.indexes},
            "month_net": b["combined"]["by_month"], "combined_total": b["combined"]["total"],
            "best_date_net": b["combined"]["best_date_net"],
            "neighbours": nbs, "p_used": p["used"],
            "pct_total": {idx: eod[idx]["net_pct_sum"] for idx in cal.indexes}})
        S[cid] = float(S_all[r])
        passed[cid] = all(gt["pass"] for gt in gates.values())
        cands_out[cid] = {
            "order": c["order"], "family": c["family"], "name": c["name"], "previously_seen_on_this_data": c["previously_seen"],
            "module": sig_file["candidates"][cid]["module"], "params": sig_file["candidates"][cid]["variants"][0]["params"],
            "S": S[cid], "S_pct": float(S_pct_all[r]), "per_index": b["per_index"], "combined": b["combined"],
            "p": p, "gates": gates, "all_gates_pass": passed[cid],
            "failed_gates": [k for k, gt in gates.items() if not gt["pass"]],
            "neighbours": nbs, "trades": b["trades"]}
    ranking = sorted(ids, key=lambda k: (-S[k], cands_out[k]["order"]))
    winner = pick_winner(ids, S, passed)

    say("\nScores (S = min over indices of the median over EOD / H60 / STOP30 of t; rupees are EOD, 1 lot)")
    say("   (nN nS = OK EOD trades NIFTY, SENSEX; same = trades whose EOD and STOP30 results are identical, NIFTY/SENSEX)")
    say(f"{'#':>2} {'candidate':34} {'S':>6} {'S_pct':>6} {'nN':>3} {'nS':>3} {'same':>7} {'combined':>10} {'pA':>6} {'pB':>6} {'pRef':>6}  gates failed")
    for k, cid in enumerate(ranking, 1):
        r = cands_out[cid]
        say(f"{k:>2} {cid:34} {r['S']:6.2f} {r['S_pct']:6.2f} "
            + " ".join(f"{r['per_index'][idx]['exits']['EOD']['n']:>3}" for idx in cal.indexes)
            + f" {'/'.join(str(r['per_index'][idx]['identical_eod_stop30']) for idx in cal.indexes):>7}"
            + f" {r['combined']['total']:10,.0f} {r['p']['A']:6.3f} {r['p']['B']:6.3f} {r['p']['REF']:6.3f}  "
            + ("PASSES ALL" if r["all_gates_pass"] else ",".join(r["failed_gates"]))
            + ("  [PREVIOUSLY SEEN ON THIS DATA]" if r["previously_seen_on_this_data"] else ""))
    if winner:
        say(f"\nWINNER (P9): {winner}  S = {S[winner]:.3f}"
            + ("  - PREVIOUSLY SEEN ON THIS DATA: a holdout verdict will be labelled NOT INDEPENDENT" if
               cands_out[winner]["previously_seen_on_this_data"] else ""))
    else:
        say("\nNO candidate passes every gate. The holdout is NOT opened. NOT VALIDATED - DO NOT TRADE:")
        for cid in ranking:
            say(f"   {cid}: S {S[cid]:.2f}, failed {','.join(cands_out[cid]['failed_gates'])}")
        say("   (reported as 'not detectable with about 80 sessions', not as 'no edge exists')")

    results = {
        "meta": {"label": label, "run": entry["run"], "stamp": stamp, "reason": entry["reason"],
                 "protocol": "protocol.md v2 with addenda 1 and 2", "hashes": hashes, "py_funcs_sha256": py_sha,
                 "family_size": n_family, "struck": [c["id"] for c in library if c["struck"]],
                 "sessions": sessions, "weeks": [f"{y}-W{w:02d}" for y, w in cal.weeks],
                 "exits": list(EXITS), "headline": "EOD exit, ATM contract, 1 lot per index",
                 "min_n": MIN_N_DISCOVERY, "seed": SEED, "draws_null_A": int(len(na["max"]["A"])),
                 "draws_null_B": int(len(na["max"]["B"])), "draws_reference": int(len(na["max"]["REF"])),
                 "readings": READINGS},
        "table_non_ok": side["non_ok"],
        "p85": p85,
        "nulls": {name: {"what": {"A": "week-block permutation", "B": "circular week shift, enumerated",
                                  "REF": "within-weekday uniform day permutation (reference only)"}[name],
                         "maximum_quantiles": quantiles(na["max"][name]),
                         "sessions_dropped_per_draw_mean": float((na["maps"][name] < 0).sum(axis=1).mean())
                         if len(na["maps"][name]) else None}
                  for name in ("A", "B", "REF")},
        "ranking": ranking, "winner": winner,
        "not_validated": [] if winner else [{"id": cid, "S": S[cid], "failed_gates": cands_out[cid]["failed_gates"]}
                                            for cid in ranking],
        "candidates": cands_out}
    name = "results_discovery.json" if not post_holdout else f"results_discovery_exploratory_run{entry['run']}.json"
    write_json(os.path.join(out_dir, name), results)
    if winner and not post_holdout:                           # P3.3 - only ever written when there is a winner
        write_json(os.path.join(out_dir, "freeze.json"),
                   {"winner": winner, "params": cands_out[winner]["params"], "module": cands_out[winner]["module"],
                    "S_discovery": S[winner], "previously_seen_on_this_data": cands_out[winner]["previously_seen_on_this_data"],
                    "hashes": hashes, "py_funcs_sha256": py_sha, "stamp": stamp, "run": entry["run"],
                    "results_discovery_sha256": sha256_file(os.path.join(out_dir, name))})
        say(f"freeze.json written: {os.path.join(out_dir, 'freeze.json')}")
    entry.update(status="completed", winner=winner, results_file=name,
                 results_sha256=sha256_file(os.path.join(out_dir, name)))
    write_json(log_path, log)
    say(f"saved {os.path.join(out_dir, name)}")
    return results


# ---------------------------------------------------------------------------
# step: holdout (P10) - one shot
# ---------------------------------------------------------------------------
def holdout_compute(markets: dict, sessions: dict, fn, params: dict, n_draws: int = N_DRAWS, seed: int = SEED,
                    min_n: int = MIN_N_HOLDOUT, months=None) -> dict:
    """The frozen entry on the given sessions: its signals, only the rows it and its null need, S, the two nulls,
    the verdict and the P10.5 figures.  Takes markets and sessions as arguments so the selftest can dry-run it
    on discovery data."""
    indexes = list(markets)
    signals, offenders = {}, []
    for idx in indexes:
        signals[idx] = {}
        for day in sessions[idx]:
            try:
                problems = C.check_no_lookahead(fn, markets[idx].day_ctx(day), params)
                r = fn(markets[idx].day_ctx(day), **params)
            except Exception as e:                            # noqa: BLE001
                offenders.append(f"{idx} {day}: raised {type(e).__name__}: {e}")
                continue
            offenders += problems
            if r is not None and not problems:
                signals[idx][day] = [r[0], r[1]]
    cal = Calendar(sessions)
    sigs = signal_arrays([signals], sessions)
    # rows: the entry's own signals, and each signal on every other session of the same weekday (the null)
    tabs = {}
    for idx in indexes:
        f, d = sigs[idx]["f"][0], sigs[idx]["d"][0]
        wd = cal.wd[cal.u_of_s[idx]]
        by_wd = {j: {(int(f[s]), int(d[s])) for s in np.flatnonzero((wd == j) & (f >= 0))} for j in range(1, 8)}
        need = [by_wd[int(wd[s])] for s in range(len(sessions[idx]))]
        tabs[idx] = build_table(markets[idx], sessions[idx], need)
    net = {idx: tabs[idx].net for idx in indexes}
    na = null_analysis(net, sigs, cal, 1, min_n, n_draws, seed, with_ref=True)
    # no null draw may have read a row that was never computed
    for idx in indexes:
        f, d = sigs[idx]["f"][0], sigs[idx]["d"][0]
        for name in ("A", "B", "REF"):
            ts = cal.to_index(idx, na["maps"][name])
            ok = (ts >= 0) & (f >= 0)[None, :]
            st = tabs[idx].status_e[np.maximum(ts, 0), np.maximum(f, 0)[None, :], d[None, :]]
            if (st[ok] == ST_NOT_COMPUTED).any():
                raise Refusal(f"{idx} null {name}: a draw points at an outcome row that was never computed")
    if months is None:
        months = sorted({d[:7] for d in cal.dates})
    book = variant_book(tabs, sigs, cal, 0, min_n, months, True)
    S_real = float(na["S"][0])
    S_pct = float(S_under({idx: tabs[idx].pct for idx in indexes}, sigs, cal, cal.identity(), min_n)[0][0])
    p = {k: float(na["p"][k][0]) for k in ("A", "B", "REF", "used")}
    combined = book["combined"]["total"]
    if offenders:
        verdict = "NOT CONFIRMED (the look-ahead check failed on holdout days - the result is void)"
    elif p["used"] <= HOLDOUT_P and combined > 0:
        verdict = "CONFIRMED"
    elif combined > 0:
        verdict = "WEAK"
    else:
        verdict = "NOT CONFIRMED"

    # P10.5: null means (EOD net per trade, per index and pooled; combined net per trade date)
    null_means = {}
    for name in ("A", "B"):
        tgt = na["maps"][name]
        D = tgt.shape[0]
        per_trade = {idx: [] for idx in indexes}
        pooled, per_date = [], []
        g = {idx: gather(net[idx], sigs[idx]["f"], sigs[idx]["d"], cal.to_index(idx, tgt))[:, 0, :, 0] for idx in indexes}
        for k in range(D):
            comb = np.zeros(cal.U)
            has = np.zeros(cal.U, dtype=bool)
            tot, cnt = 0.0, 0
            for idx in indexes:
                x = g[idx][k]
                ok = ~np.isnan(x)
                if ok.any():
                    per_trade[idx].append(float(x[ok].mean()))
                    tot += float(x[ok].sum())
                    cnt += int(ok.sum())
                    u = tgt[k, cal.u_of_s[idx][ok]]
                    np.add.at(comb, u, x[ok])
                    has[u] = True
            if cnt:
                pooled.append(tot / cnt)
                per_date.append(float(comb[has].mean()))
        null_means[name] = {"draws": int(D),
                            "mean_net_per_trade": {idx: float(np.mean(v)) if v else None for idx, v in per_trade.items()},
                            "mean_net_per_trade_pooled": float(np.mean(pooled)) if pooled else None,
                            "mean_combined_net_per_date": float(np.mean(per_date)) if per_date else None,
                            "mean_S": float(na["null_S"][name][:, 0].mean()) if D else None,
                            "S_quantiles": quantiles(na["null_S"][name][:, 0])}
    # P10.5: 90% week-block bootstrap of the mean combined net per trade date
    by_date = book["combined"]["by_date"]
    wk_vals = [[] for _ in range(cal.W)]
    for u, dt in enumerate(cal.dates):
        if dt in by_date:
            wk_vals[int(cal.week_of[u])].append(by_date[dt])
    rng = np.random.default_rng(seed)
    boots, skipped = [], 0
    for _ in range(n_draws):
        pick = rng.integers(0, cal.W, size=cal.W)
        vals = [v for w in pick for v in wk_vals[int(w)]]
        if vals:
            boots.append(sum(vals) / len(vals))
        else:
            skipped += 1
    eod = {idx: book["per_index"][idx]["exits"]["EOD"] for idx in indexes}
    n_tr = sum(eod[idx]["n"] for idx in indexes)
    return {
        "S": S_real, "S_pct": S_pct, "min_n": min_n, "p": p, "verdict": verdict,
        "combined_eod_net": combined, "lookahead_offenders": offenders,
        "holdout_trades": {idx: eod[idx]["n"] for idx in indexes},
        "signals": {idx: len(signals[idx]) for idx in indexes},
        "mean_net_per_trade": {**{idx: eod[idx]["mean"] for idx in indexes},
                               "pooled": (sum(eod[idx]["net"] for idx in indexes) / n_tr) if n_tr else None},
        "mean_combined_net_per_date": book["combined"]["mean_per_date"],
        "bootstrap_90_mean_combined_net_per_date": {
            "low": float(np.percentile(boots, 5)) if boots else None,
            "high": float(np.percentile(boots, 95)) if boots else None,
            "resamples": n_draws, "skipped_empty": skipped, "seed": seed, "weeks": cal.W},
        "null_mean": null_means,
        "rupees_per_index": {idx: eod[idx]["net"] for idx in indexes},
        "pct_of_premium_per_index": {idx: {"sum_of_trade_pct": eod[idx]["net_pct_sum"], "mean_trade_pct": eod[idx]["net_pct_mean"],
                                           "pooled_pct": eod[idx]["net_pct_pooled"]} for idx in indexes},
        "null_draws": {"A": int(len(na["max"]["A"])), "B": int(len(na["max"]["B"])), "REF": int(len(na["max"]["REF"]))},
        "weeks": [f"{y}-W{w:02d}" for y, w in cal.weeks],
        "per_index": book["per_index"], "combined": book["combined"], "trades": book["trades"],
        "table_non_ok": {idx: non_ok_shares(tabs[idx]) for idx in indexes},
        "_tabs": tabs,
    }


def print_holdout(out: dict) -> None:
    """The P10 printout, from the result dict that is saved."""
    res = out
    chk = out["meta"]["second_coding_check"]
    print(f"\nHOLDOUT VERDICT: {res['verdict']}" + ("" if out["independence"] == "INDEPENDENT" else "  [NOT INDEPENDENT]"))
    print(f"   S (min n {MIN_N_HOLDOUT}) = {res['S']:.3f}; p null A {res['p']['A']:.4f}, null B {res['p']['B']:.4f}, "
          f"used {res['p']['used']:.4f} (threshold {HOLDOUT_P}); combined EOD net Rs {res['combined_eod_net']:,.0f}")
    print(f"   trades {res['holdout_trades']}; mean net per trade {res['mean_net_per_trade']}")
    bt = res["bootstrap_90_mean_combined_net_per_date"]
    print(f"   mean combined net per trade date {res['mean_combined_net_per_date']}; 90% week-block bootstrap "
          f"[{bt['low']}, {bt['high']}]")
    for name in ("A", "B"):
        print(f"   null {name} mean: per trade pooled {res['null_mean'][name]['mean_net_per_trade_pooled']}, "
              f"per date {res['null_mean'][name]['mean_combined_net_per_date']}")
    print(f"   rupees per index {res['rupees_per_index']}; % of premium {res['pct_of_premium_per_index']}")
    print(f"   second coding: {chk['rows_compared']} rows compared, {len(chk['mismatches'])} mismatches; "
          f"look-ahead problems {len(res['lookahead_offenders'])}")
    print("   " + out["error_budget"])
    print("   " + out["sentence"])


def step_holdout(study_dir: str, out_dir: str, stamp: str | None, confirm: str | None, modules=None) -> None:
    fz = holdout_guard(study_dir, out_dir)                    # refuses: no freeze, changed hash, already run
    if confirm != "OPEN-HOLDOUT":
        raise Refusal("the holdout is one shot: pass --confirm OPEN-HOLDOUT to open it")
    if not stamp:
        raise Refusal("--step holdout needs --stamp <timestamp text>")
    disc_path = os.path.join(out_dir, "results_discovery.json")
    if not os.path.isfile(disc_path):
        raise Refusal("results_discovery.json is missing")
    if fz.get("results_discovery_sha256") != sha256_file(disc_path):
        raise Refusal("results_discovery.json changed after the freeze")
    disc = read_json(disc_path)
    if disc.get("winner") != fz["winner"]:
        raise Refusal("freeze.json and results_discovery.json do not name the same winner")
    library = load_library(study_dir)
    cands, _ = load_candidates(modules if modules is not None else SIGNAL_MODULES, library)
    if fz["winner"] not in cands:
        raise Refusal(f"the frozen winner {fz['winner']} is not provided by the signal modules")
    spec = cands[fz["winner"]]
    if _j(spec["centre"]) != fz["params"]:
        raise Refusal("the signal module's centre parameters differ from the frozen ones")
    print(f"freeze verified: winner {fz['winner']} params {fz['params']} (frozen at {fz['stamp']}); every hash matches.")
    print("OPENING THE HOLDOUT - this happens once.")
    markets = {idx: C.Market(idx, C.WINDOW_END) for idx in INDEXES}           # only now
    sessions, exc = {}, {}
    for idx in INDEXES:
        sessions[idx], exc[idx] = included_sessions(markets[idx], HOLDOUT_START, C.WINDOW_END)
        print_sessions(idx, sessions[idx], exc[idx], "HOLDOUT")
    write_json(os.path.join(out_dir, "sessions_holdout.json"),                 # P4.2: before any outcome
               {"split": "HOLDOUT", "window": [HOLDOUT_START, C.WINDOW_END], "sessions": sessions,
                "excluded_by_P4.2": exc, "stamp": stamp})
    res = holdout_compute(markets, sessions, spec["fn"], spec["centre"])
    tabs = res.pop("_tabs")
    n_cmp, bad = 0, []
    for idx in INDEXES:                                       # the second coding, on the winner's own rows only
        cells = set()
        pos = {dd: i for i, dd in enumerate(sessions[idx])}
        for tr in res["trades"]:
            if tr["index"] == idx:
                cells.add((pos[tr["day"]], C.minutes(tr["fill_bar"]) - FILL0, DIRS.index(tr["direction"])))
        n, b = compare_rows(tabs[idx], markets[idx], cells)
        n_cmp += n
        bad += b
    independent = not next(c for c in library if c["id"] == fz["winner"])["previously_seen"]
    out = {
        "meta": {"label": "HOLDOUT - single hypothesis, one shot", "stamp": stamp, "freeze": fz,
                 "window": [HOLDOUT_START, C.WINDOW_END], "sessions": sessions, "seed": SEED,
                 "readings": READINGS, "second_coding_check": {"rows_compared": n_cmp, "mismatches": bad}},
        "winner": fz["winner"], "params": fz["params"],
        "independence": "INDEPENDENT" if independent else "NOT INDEPENDENT (family existing_repo: PREVIOUSLY SEEN ON THIS DATA, P5.3)",
        "S_discovery": fz.get("S_discovery"),
        "error_budget": "discovery 0.25 x holdout 0.20 = about 5% chance that a worthless library produces a CONFIRMED entry",
        "sentence": "the holdout mean is the only unbiased estimate of the edge; the discovery figure is inflated by selection",
        **res}
    write_json(os.path.join(out_dir, "results_holdout.json"), out, exclusive=True)      # once; never overwritten
    log_path = os.path.join(out_dir, "run_log.json")
    log = read_json(log_path) if os.path.isfile(log_path) else []
    log.append({"run": len(log) + 1, "stamp": stamp, "reason": "the one holdout run (P10)", "label": "HOLDOUT",
                "changed_since_previous_run": [], "hashes": fz["hashes"], "py_funcs_sha256": fz.get("py_funcs_sha256"),
                "status": "completed", "winner": fz["winner"], "verdict": res["verdict"],
                "results_file": "results_holdout.json",
                "results_sha256": sha256_file(os.path.join(out_dir, "results_holdout.json"))})
    write_json(log_path, log)
    print_holdout(out)
    print(f"saved {os.path.join(out_dir, 'results_holdout.json')}")


# ---------------------------------------------------------------------------
# step: selftest (synthetic; no real candidate is touched)
# ---------------------------------------------------------------------------
def _selftest() -> int:
    import statistics
    import shutil
    import tempfile
    import types

    fails: list[str] = []

    def check(cond, what):
        print(("PASS  " if cond else "FAIL  ") + what)
        if not cond:
            fails.append(what)

    def refuses(fn, what, needle=""):
        try:
            fn()
        except Refusal as e:
            check(needle in str(e), f"{what} -> refused ({str(e).splitlines()[0][:90]})")
        except Exception as e:                                # noqa: BLE001
            check(False, f"{what} -> wrong exception {type(e).__name__}: {e}")
        else:
            check(False, f"{what} -> did NOT refuse")

    t_start = time.perf_counter()
    markets = {idx: C.Market(idx, C.DISCOVERY_END) for idx in INDEXES}
    sessions = {idx: included_sessions(markets[idx], C.WINDOW_START, C.DISCOVERY_END)[0] for idx in INDEXES}
    cal = Calendar(sessions)

    # ------------------------------------------------------------------ (i)
    print("== (i) the t / S arithmetic on a hand-made example ==")
    a = [120.0, -80.0, 45.5, 300.0, -150.25, 60.0, -20.0, 10.0, 95.0, -40.0,
         210.0, -75.0, 33.0, -12.5, 88.0, 140.0, -200.0, 15.0, 70.0, -5.0, 51.0, 9.0]
    t_ref = statistics.mean(a) / (statistics.stdev(a) / math.sqrt(len(a)))
    t_got, n_got, m_got, sd_got = tstat(np.array(a + [math.nan, math.nan]), 20, axis=0)
    check(abs(float(t_got) - t_ref) < 1e-12 and int(n_got) == 22 and abs(float(sd_got) - statistics.stdev(a)) < 1e-9,
          f"t = mean / (sd / sqrt(n)): engine {float(t_got):.6f}, statistics module {t_ref:.6f}, n {int(n_got)} (NaN ignored)")
    check(float(tstat(np.array(a[:19]), 20, axis=0)[0]) == 0.0 and float(tstat(np.array(a[:19]), 10, axis=0)[0]) != 0.0,
          "n = 19: t = 0 with minimum 20 (discovery), not 0 with minimum 10 (holdout)")
    check(float(tstat(np.full(25, 37.3), 20, axis=0)[0]) == 0.0 and float(tstat(np.full(25, 0.1 + 0.2), 20, axis=0)[0]) == 0.0,
          "sd = 0 (25 identical results): t = 0")
    # S through the real code path: a tiny hand-made table, identity map
    hand = {idx: np.full((len(sessions[idx]), NF, 2, 3), np.nan) for idx in INDEXES}
    hs = {idx: {"f": np.full((1, len(sessions[idx])), -1, dtype=np.int64),
                "d": np.zeros((1, len(sessions[idx])), dtype=np.int64)} for idx in INDEXES}
    rs = np.random.default_rng(1)
    want = {}
    for idx, shift in (("NIFTY", 60.0), ("SENSEX", 20.0)):
        ts = []
        for e in range(3):
            vals = [round(float(v), 2) for v in rs.normal(shift * (e + 1), 400.0, 22)]
            for k, v in enumerate(vals):
                hand[idx][k * 3, 7 + k, k % 2, e] = v
            ts.append(statistics.mean(vals) / (statistics.stdev(vals) / math.sqrt(22)))
        want[idx] = statistics.median(ts)
    for idx in INDEXES:
        for k in range(22):
            hs[idx]["f"][0, k * 3], hs[idx]["d"][0, k * 3] = 7 + k, k % 2
    S_hand = float(S_under(hand, hs, cal, cal.identity(), 20)[0][0])
    check(abs(S_hand - min(want.values())) < 1e-9,
          f"S = min over indices of the median of 3 exit t: engine {S_hand:.6f}, by hand min({want['NIFTY']:.6f}, {want['SENSEX']:.6f})")
    hand2 = {idx: v.copy() for idx, v in hand.items()}
    hand2["NIFTY"][0, 7, 0, :] = np.nan
    hand2["NIFTY"][3, 8, 1, :] = np.nan
    hand2["NIFTY"][6, 9, 0, :] = np.nan
    check(float(S_under(hand2, hs, cal, cal.identity(), 20)[0][0]) == 0.0,
          "three non-OK rows leave NIFTY with 19 trades -> its t is 0 on every exit -> S = min(0, SENSEX) = 0")
    check(np.allclose(adjusted_p(np.array([1.0, 5.0, -1.0]), np.array([0.5, 1.0, 2.0, 3.0])), [(1 + 3) / 5, 1 / 5, 1.0]),
          "adjusted p = (1 + draws with maximum >= S) / (1 + draws) on a 4-draw example (a tie counts)")

    # ------------------------------------------------------------------ synthetic world
    same_sessions = sessions["NIFTY"] == sessions["SENSEX"]

    def synth_net(rng, drift=0.0, k=None):
        """Noise outcome arrays on calendar k: a shared day move (the two indices are one bet), CE and PE mirror it."""
        k = k or cal
        z = rng.normal(drift, 1.0, k.U)
        out = {}
        for idx in k.indexes:
            n = len(k.u_of_s[idx])
            zs = z[k.u_of_s[idx]][:, None, None, None]
            sign = np.array([1.0, -1.0])[None, None, :, None]
            base = 1500.0 * (0.8 * sign * zs + rng.normal(0.0, 0.6, (n, NF, 2, 1)))
            x = base + rng.normal(0.0, 450.0, (n, NF, 2, 3)) - 150.0
            x[rng.random((n, NF, 2)) < 0.02] = np.nan         # some non-OK rows
            out[idx] = x
        return out

    def synth_sigs(rng, n_cand, k=None):
        k = k or cal
        f = np.full((n_cand, k.U), -1, dtype=np.int64)
        d = np.zeros((n_cand, k.U), dtype=np.int64)
        for c in range(n_cand):
            on = rng.random(k.U) < rng.uniform(0.45, 1.0)
            habit = rng.integers(0, NF)
            f[c] = np.where(on, np.clip(habit + rng.integers(-20, 21, k.U), 0, NF - 1), -1)
            d[c] = (rng.random(k.U) < rng.uniform(0.2, 0.8)).astype(np.int64)
        return {idx: {"f": f[:, k.u_of_s[idx]], "d": d[:, k.u_of_s[idx]]} for idx in k.indexes}

    # ------------------------------------------------------------------ (ii)
    print("== (ii) pure noise: the adjusted p must not reject too often ==")
    reps, draws = 400, 300
    rng = np.random.default_rng(777)
    min_p, min_pa, min_pb, all_p = [], [], [], []
    for _ in range(reps):
        netx = synth_net(rng)
        sg = synth_sigs(rng, 27)
        na = null_analysis(netx, sg, cal, 27, MIN_N_DISCOVERY, draws, int(rng.integers(1, 1 << 30)), with_ref=False)
        min_p.append(float(na["p"]["used"].min()))
        min_pa.append(float(na["p"]["A"].min()))
        min_pb.append(float(na["p"]["B"].min()))
        all_p += na["p"]["used"].tolist()
    fw = float(np.mean(np.array(min_p) <= GATE_P))
    fwa, fwb = float(np.mean(np.array(min_pa) <= GATE_P)), float(np.mean(np.array(min_pb) <= GATE_P))
    per_c = float(np.mean(np.array(all_p) <= GATE_P))
    tol = 3 * math.sqrt(0.25 * 0.75 / reps)
    print(f"      {reps} noise worlds x 27 fake candidates, {draws} week permutations + {cal.W - 1} shifts each")
    print(f"      share of worlds whose BEST candidate has p <= 0.25: gate p (larger of A, B) {fw:.3f}; null A alone {fwa:.3f}; "
          f"null B alone {fwb:.3f}")
    print(f"      share of all candidate p values <= 0.25: {per_c:.4f}; deciles of the best-candidate p: "
          + " ".join(f"{np.percentile(min_p, q):.2f}" for q in range(10, 100, 10)))
    check(fw <= 0.25 + tol, f"a worthless library passes gate (e) in {fw:.3f} of worlds (allowed 0.25 + 3 se = {0.25 + tol:.3f})")
    check(fwa <= 0.25 + 2 * tol, f"null A alone: {fwa:.3f} (not far above 0.25; the limit printed is {0.25 + 2 * tol:.3f})")
    check(per_c <= 0.25, f"per candidate, p <= 0.25 happens in {per_c:.4f} of cases (max-statistic: far below 0.25)")

    # ------------------------------------------------------------------ (iii)
    print("== (iii) a planted real edge gets a small p ==")
    rng = np.random.default_rng(4242)
    ps, ss = [], []
    for _ in range(10):
        netx = synth_net(rng)
        sg = synth_sigs(rng, 27)
        for idx in INDEXES:                                   # candidate 5 really earns 0.8 sd per trade on its own rows
            f5, d5 = sg[idx]["f"][5], sg[idx]["d"][5]
            s5 = np.flatnonzero(f5 >= 0)
            netx[idx][s5, f5[s5], d5[s5], :] += 1500.0
        na = null_analysis(netx, sg, cal, 27, MIN_N_DISCOVERY, 500, SEED, with_ref=False)
        ps.append(float(na["p"]["used"][5]))
        ss.append(float(na["S"][5]))
    print(f"      planted candidate: S {min(ss):.2f}..{max(ss):.2f}; p used {min(ps):.4f}..{max(ps):.4f} "
          f"(the smallest possible p under null B is {1 / cal.W:.4f})")
    check(max(ps) <= 0.10, f"planted edge: p <= 0.10 in 10 of 10 worlds (worst {max(ps):.4f})")

    # ------------------------------------------------------------------ (iv)
    print("== (iv) always-PE in a falling market does NOT get a small p ==")
    from datetime import timedelta
    full_days = [(date(2030, 1, 7) + timedelta(days=7 * w + j)).isoformat() for w in range(cal.W) for j in range(5)]
    cal_full = Calendar({idx: full_days for idx in INDEXES})  # a synthetic calendar with no holiday: no signal is ever dropped

    def falling(k, worlds, drift, seed):
        """Candidate 0 buys a PE every session while the market falls `drift` sd a day.  Returns its raw S, its
        protocol p, and p_equal: the same p when its real score is thinned to the sessions each draw keeps."""
        rng_ = np.random.default_rng(seed)
        raw, p_prot, p_equal, n_null = [], [], [], []
        for _ in range(worlds):
            netx = synth_net(rng_, drift=drift, k=k)
            sg = synth_sigs(rng_, 27, k)
            for idx in k.indexes:
                sg[idx]["d"][0] = 1
                sg[idx]["f"][0] = 100 + (k.u_of_s[idx] % 7)
            na = null_analysis(netx, sg, k, 27, MIN_N_DISCOVERY, 300, int(rng_.integers(1, 1 << 30)), with_ref=False)
            raw.append(float(na["S"][0]))
            p_prot.append(float(na["p"]["used"][0]))
            one = {idx: {"f": sg[idx]["f"][:1], "d": sg[idx]["d"][:1]} for idx in k.indexes}
            pe = []
            for name in ("A", "B"):
                tgt = na["maps"][name]
                thin = np.where(tgt >= 0, np.arange(k.U)[None, :], -1)      # the REAL trades, minus the days the draw drops
                s_thin = S_under(netx, one, k, thin, MIN_N_DISCOVERY)[:, 0]
                pe.append((1.0 + float((na["max"][name] >= s_thin - 1e-9).sum())) / (1.0 + len(s_thin)))
                if name == "A":
                    n_null.append(float((tgt >= 0).sum(axis=1).mean()))
            p_equal.append(max(pe))
        return np.array(raw), np.array(p_prot), np.array(p_equal), float(np.mean(n_null))

    worlds = 120
    lim = 0.25 + 3 * math.sqrt(0.25 * 0.75 / worlds)
    raw_f, p_f, _, _ = falling(cal_full, worlds, -1.0, 99)
    sh_f = float(np.mean(p_f <= GATE_P))
    print(f"      holiday-free synthetic calendar ({cal_full.U} sessions, nothing dropped), market falling 1 sd a day: raw S "
          f"{raw_f.min():.1f}..{raw_f.max():.1f}; adjusted p median {np.median(p_f):.3f}, share <= 0.25: {sh_f:.3f}")
    check(raw_f.min() > 3.0, f"always-PE in the falling market: its raw S is large in every world (min {raw_f.min():.2f}; "
          "a naive t-test would call it significant)")
    check(sh_f <= lim, f"it does NOT get a small p: p <= 0.25 in {sh_f:.3f} of {worlds} worlds (limit 0.25 + 3 se = {lim:.3f})")
    raw_r, p_r, pe_r, n_null = falling(cal, worlds, -1.0, 99)
    sh_r, sh_e = float(np.mean(p_r <= GATE_P)), float(np.mean(pe_r <= GATE_P))
    check(sh_e <= lim, f"real discovery calendar, real score thinned to the sessions each draw keeps: p <= 0.25 in {sh_e:.3f} of "
          f"{worlds} worlds (limit {lim:.3f}) - with equal trade counts the null absorbs the drift")
    raw_m, p_m, _, _ = falling(cal, worlds, -0.3, 199)
    sh_m = float(np.mean(p_m <= GATE_P))
    print(f"NOTE  real discovery calendar, protocol as written (P8.2): the real score keeps all {cal.U} sessions while a null "
          f"draw keeps {n_null:.1f} on average (holiday slots drop the signal), and t grows with sqrt(n).")
    print(f"NOTE  so a pure-drift entry leaks through: market falling 1 sd a day (raw S {raw_r.min():.1f}..{raw_r.max():.1f}): "
          f"always-PE gets p <= 0.25 in {sh_r:.3f} of worlds (median p {np.median(p_r):.3f}); falling 0.3 sd a day (raw S "
          f"{raw_m.min():.1f}..{raw_m.max():.1f}): {sh_m:.3f} (median p {np.median(p_m):.3f}). Not tuned away - disclosed.")

    # ------------------------------------------------------------------ (v)
    print("== (v) every gate flips on hand-made inputs ==")
    base = {"n_ok": {"NIFTY": 30, "SENSEX": 31}, "unpriced_share": {"NIFTY": 0.05, "SENSEX": 0.0},
            "month_net": {"2026-01": 700.0, "2026-02": 200.0, "2026-03": -50.0, "2026-04": 150.0},
            "combined_total": 1000.0, "best_date_net": 999.0,
            "neighbours": [{"label": "x=1", "combined_net": 1.0, "S": 0.0}, {"label": "x=3", "combined_net": 50.0, "S": 1.2}],
            "p_used": 0.25, "pct_total": {"NIFTY": 0.01, "SENSEX": 3.0}}
    g0 = evaluate_gates(base)
    check(all(v["pass"] for v in g0.values()), "a candidate sitting exactly on every limit passes all six gates "
          "(30 trades, 5% unpriced, 3 months, 70% month share, neighbour S = 0, p = 0.25)")

    def flipped(gate, **change):
        g = json.loads(json.dumps(base))
        for k, v in change.items():
            if isinstance(v, dict) and isinstance(g.get(k), dict):
                g[k].update(v)
            else:
                g[k] = v
        r = evaluate_gates(g)
        return (not r[gate]["pass"]) and all(r[k]["pass"] for k in r if k != gate)

    check(flipped("a", n_ok={"NIFTY": 29}), "(a) 29 OK trades on one index -> only gate a fails")
    check(flipped("a", unpriced_share={"SENSEX": 0.051}), "(a) 5.1% unpriced on one index -> only gate a fails")
    check(flipped("b", month_net={"2026-01": 700.0, "2026-02": 350.0, "2026-03": -50.0, "2026-04": 0.0}),
          "(b) only 2 months above zero (a month at exactly 0 does not count) -> only gate b fails")
    check(flipped("b", month_net={"2026-01": 701.0, "2026-02": 199.0, "2026-03": -50.0, "2026-04": 150.0}),
          "(b) one month supplies 70.1% of the total -> only gate b fails")
    check(flipped("c", neighbours=[{"label": "x=1", "combined_net": 0.0, "S": 0.5}]),
          "(c) a neighbour with combined net 0 -> only gate c fails")
    check(flipped("c", neighbours=[{"label": "x=1", "combined_net": 10.0, "S": -0.01}]),
          "(c) a neighbour with S = -0.01 -> only gate c fails")
    check(flipped("d", best_date_net=1000.0), "(d) the best date supplies the whole net -> only gate d fails")
    check(flipped("e", p_used=0.2501), "(e) p = 0.2501 -> only gate e fails")
    check(flipped("f", pct_total={"NIFTY": 0.0}), "(f) net % of premium = 0 on one index -> only gate f fails")
    r = evaluate_gates({**base, "combined_total": -10.0, "month_net": {"2026-01": 5.0, "2026-02": 5.0, "2026-03": 5.0, "2026-04": -25.0}})
    check(not r["b"]["pass"] and not r["d"]["pass"], "a negative total fails (b) (share undefined) and (d)")
    check(pick_winner(["x", "y", "z"], {"x": 1.0, "y": 2.0, "z": 2.0}, {"x": True, "y": True, "z": True}) == "y"
          and pick_winner(["x", "y"], {"x": 1.0, "y": 2.0}, {"x": True, "y": False}) == "x"
          and pick_winner(["x"], {"x": 9.0}, {"x": False}) is None,
          "winner: highest S among those passing; a tie goes to the earlier library entry; none passing -> no winner")

    # ------------------------------------------------------------------ (vi)
    print("== (vi) the week / weekday mapping of both nulls on the real discovery session list ==")
    wk = [f"{y}-W{w:02d}" for y, w in cal.weeks]
    print(f"      {cal.U} session dates, {cal.W} ISO weeks {wk[0]}..{wk[-1]}; sessions per weekday (Mon..Sun): "
          f"{[int((cal.wd == j).sum()) for j in range(1, 8)]}; both indices share one list: {same_sessions}")
    tgt_a, pis_a = cal.null_a(N_DRAWS, SEED)
    tgt_b, pis_b = cal.null_b()
    tgt_r = cal.null_ref(200, SEED)
    print(f"      example, null A draw 1 (seed {SEED}): week permutation {pis_a[0].tolist()}")
    shown = 0
    for u in range(cal.U):
        if shown < 6 and (u % 13 == 2 or tgt_a[0, u] < 0):
            tu = int(tgt_a[0, u])
            src = f"{cal.dates[u]} ({wk[cal.week_of[u]]}, weekday {cal.wd[u]})"
            print(f"         signal of {src} -> " + (f"{cal.dates[tu]} ({wk[cal.week_of[tu]]}, weekday {cal.wd[tu]})"
                                                    if tu >= 0 else f"week {wk[pis_a[0][cal.week_of[u]]]} has no session on that weekday: DROPPED"))
            shown += 1
    print(f"         {int((tgt_a[0] < 0).sum())} of {cal.U} signals-days dropped in this draw; "
          f"mean over 2,000 draws {float((tgt_a < 0).sum(axis=1).mean()):.2f}")

    def weekday_kept(tgt):
        ok = tgt >= 0
        return bool((cal.wd[np.maximum(tgt, 0)][ok] == np.broadcast_to(cal.wd, tgt.shape)[ok]).all())

    def injective(tgt):
        for row in tgt:
            v = row[row >= 0]
            if len(np.unique(v)) != len(v):
                return False
        return True

    check(all(sorted(p.tolist()) == list(range(cal.W)) for p in pis_a) and len(pis_a) == N_DRAWS,
          f"null A: {N_DRAWS} draws, each a permutation of the {cal.W} weeks")
    check(weekday_kept(tgt_a) and weekday_kept(tgt_b) and weekday_kept(tgt_r),
          "a signal never changes weekday (null A, null B, reference permutation)")
    check(injective(tgt_a) and injective(tgt_b) and injective(tgt_r), "no session ever receives two signals in one draw")
    exp_ok = True
    for tgt, pis in ((tgt_a[:50], pis_a[:50]), (tgt_b, pis_b)):
        for k in range(len(pis)):
            for u in range(cal.U):
                target_week = int(pis[k][cal.week_of[u]])
                want_u = [v for v in range(cal.U) if cal.week_of[v] == target_week and cal.wd[v] == cal.wd[u]]
                exp_ok &= (int(tgt[k, u]) == (want_u[0] if want_u else -1))
    check(exp_ok, "target = the session at (permuted week, same weekday); no such session -> the signal is dropped "
                  "(brute force on 50 draws of A and every shift of B)")
    check(len(pis_b) == cal.W - 1 and all((pis_b[k - 1] == (np.arange(cal.W) + k) % cal.W).all() for k in range(1, cal.W)),
          f"null B: exactly the {cal.W - 1} circular shifts k = 1..W-1, week w -> (w + k) mod W")
    sun = [u for u in range(cal.U) if cal.wd[u] == 7]
    check(all(((tgt_a[:, u] == u) | (tgt_a[:, u] == -1)).all() for u in sun) and (tgt_r[:, sun] == np.array(sun)).all()
          if sun else True, f"the Sunday session {[cal.dates[u] for u in sun]} only ever maps onto itself or is dropped")
    check((tgt_r >= 0).all() and all(sorted(r.tolist()) == list(range(cal.U)) for r in tgt_r),
          "reference permutation: a bijection of the sessions within each weekday, nothing dropped")
    # a dropped target and a non-OK target row both remove the trade
    n_s = {idx: len(sessions[idx]) for idx in INDEXES}
    tiny = {idx: np.zeros((n_s[idx], NF, 2, 3)) + 100.0 for idx in INDEXES}
    f1 = np.full((1, cal.U), 10, dtype=np.int64)
    d1 = np.zeros((1, cal.U), dtype=np.int64)
    sg1 = {idx: {"f": f1[:, cal.u_of_s[idx]], "d": d1[:, cal.u_of_s[idx]]} for idx in INDEXES}
    k0 = 0
    kept = gather(tiny["NIFTY"], sg1["NIFTY"]["f"], sg1["NIFTY"]["d"], cal.to_index("NIFTY", tgt_a[k0:k0 + 1]))
    n_kept = int((~np.isnan(kept[0, 0, :, 0])).sum())
    n_expected = int((cal.to_index("NIFTY", tgt_a[k0:k0 + 1]) >= 0).sum())
    tiny["NIFTY"][5, 10, 0, :] = np.nan
    kept2 = gather(tiny["NIFTY"], sg1["NIFTY"]["f"], sg1["NIFTY"]["d"], cal.to_index("NIFTY", tgt_a[k0:k0 + 1]))
    n_kept2 = int((~np.isnan(kept2[0, 0, :, 0])).sum())
    hit = int((cal.to_index("NIFTY", tgt_a[k0:k0 + 1]) == 5).sum())
    check(n_kept == n_expected < n_s["NIFTY"] and n_kept2 == n_kept - hit and hit == 1,
          f"draw 1: {n_s['NIFTY']} signals -> {n_kept} trades (missing target sessions dropped); making one target row "
          f"non-OK drops one more ({n_kept2})")

    # ------------------------------------------------------------------ (vii)
    print("== (vii) the holdout refuses without freeze.json and after a hash change ==")
    tmp = tempfile.mkdtemp(prefix="engine_selftest_", dir=os.environ.get("ENGINE_SELFTEST_TMP") or None)
    try:
        sdir, odir = os.path.join(tmp, "study"), os.path.join(tmp, "out")
        os.makedirs(os.path.join(sdir, "check"))
        os.makedirs(odir)
        files = {"protocol.md": "rules v2\n", "library.json": "{}", "engine.py": "# engine\n", "ctx.py": "# ctx\n",
                 "signals_x.py": "# signals\n", "check/alt_x.py": "# second coding\n"}
        for k, v in files.items():
            with open(os.path.join(sdir, k), "w", encoding="utf-8") as fh:
                fh.write(v)
        hs = study_hashes(sdir)
        check(sorted(hs) == sorted(files), f"hashes cover protocol.md, library.json and every .py, recursively ({len(hs)} files)")
        refuses(lambda: holdout_guard(sdir, odir), "holdout guard, no freeze.json", "no freeze.json")
        write_json(os.path.join(odir, "freeze.json"), {"winner": "x", "params": {"a": 1}, "hashes": hs,
                                                         "py_funcs_sha256": sha256_file(PY_FUNCS_PATH), "stamp": "T"})
        check(holdout_guard(sdir, odir)["winner"] == "x", "holdout guard passes with a freeze whose hashes all match (temp folder)")
        for k, change in (("signals_x.py", "# signals, edited\n"), ("protocol.md", "rules v3\n"), ("library.json", "{ }"),
                          ("check/alt_x.py", "# edited\n")):
            with open(os.path.join(sdir, k), "w", encoding="utf-8") as fh:
                fh.write(change)
            refuses(lambda: holdout_guard(sdir, odir), f"holdout guard after {k} changed", "changed after the freeze")
            with open(os.path.join(sdir, k), "w", encoding="utf-8") as fh:
                fh.write(files[k])
        with open(os.path.join(sdir, "report.py"), "w", encoding="utf-8") as fh:
            fh.write("# new\n")
        refuses(lambda: holdout_guard(sdir, odir), "holdout guard after a NEW .py file appeared", "new file")
        os.remove(os.path.join(sdir, "report.py"))
        os.remove(os.path.join(sdir, "check", "alt_x.py"))
        refuses(lambda: holdout_guard(sdir, odir), "holdout guard after a .py file was removed", "file removed")
        with open(os.path.join(sdir, "check", "alt_x.py"), "w", encoding="utf-8") as fh:
            fh.write(files["check/alt_x.py"])
        fz_bad = read_json(os.path.join(odir, "freeze.json"))
        fz_bad["py_funcs_sha256"] = "0" * 64
        write_json(os.path.join(odir, "freeze.json"), fz_bad)
        refuses(lambda: holdout_guard(sdir, odir), "holdout guard when py_funcs.py differs from the frozen hash", "py_funcs.py")
        fz_bad["py_funcs_sha256"] = sha256_file(PY_FUNCS_PATH)
        write_json(os.path.join(odir, "freeze.json"), fz_bad)
        refuses(lambda: step_holdout(sdir, odir, "T", None), "step holdout with a valid freeze but no --confirm", "one shot")
        write_json(os.path.join(odir, "results_holdout.json"), {"done": True})
        refuses(lambda: holdout_guard(sdir, odir), "holdout guard when results_holdout.json exists", "never overwritten")
        if freeze_path(STUDY_DIR, OUT_DIR) is None:
            refuses(lambda: step_holdout(STUDY_DIR, OUT_DIR, "selftest", "OPEN-HOLDOUT"),
                    "the REAL --step holdout (real folders, no freeze.json)", "no freeze.json")
            try:
                C.Market("NIFTY", C.WINDOW_END)
                check(False, "ctx.Market beyond the discovery wall without freeze.json -> did not refuse")
            except PermissionError:
                check(True, "ctx.Market('NIFTY', '2026-07-31') without freeze.json -> PermissionError (the wall itself refuses)")
        else:
            print("      skip: a real freeze.json exists - the real holdout step is not touched by the selftest")

        # -------------------------------------------------------------- (viii)
        print("== (viii) signals -> score end to end with a 3-candidate DUMMY module (synthetic outcome table) ==")

        def at_minute(ctx_, minute="09:44", direction="UP", even_only=False):
            if even_only and int(ctx_.day[8:]) % 2:
                return None
            return (minute, direction) if (ctx_.bars and ctx_.bars[-1][0] >= minute) else None

        def cheat(ctx_, minute="10:00"):                     # reads the day's last bar: must be caught
            if len(ctx_.bars) < 60:
                return None
            return (minute, "UP" if ctx_.bars[-1][4] > ctx_.bars[0][1] else "DOWN")

        def nbs(key, lo, hi, centre):
            return [{"label": f"{key}={lo}", "params": {**centre, key: lo}}, {"label": f"{key}={hi}", "params": {**centre, key: hi}}]

        c1 = {"minute": "09:44", "direction": "UP", "even_only": False}
        c2 = {"minute": "11:00", "direction": "DOWN", "even_only": False}
        c3 = {"minute": "10:00", "direction": "UP", "even_only": True}
        dummy = types.SimpleNamespace(__name__="dummy_signals", CANDIDATES={
            "dummy_up_0944": {"fn": at_minute, "centre": c1, "neighbours": nbs("minute", "09:39", "09:49", c1)},
            "dummy_down_1100": {"fn": at_minute, "centre": c2, "neighbours": nbs("minute", "10:45", "11:15", c2)},
            "dummy_up_1000_even_days": {"fn": at_minute, "centre": c3, "neighbours": nbs("minute", "09:50", "10:10", c3)},
            "near_expiry_first_hour_drive": {"fn": at_minute, "centre": c1, "neighbours": nbs("minute", "09:39", "09:49", c1)}})
        cheater = types.SimpleNamespace(__name__="dummy_cheat", CANDIDATES={
            "dummy_up_0944": {"fn": cheat, "centre": {"minute": "10:00"}, "neighbours": nbs("minute", "09:50", "10:10", {"minute": "10:00"})}})
        lib = {"candidates": [{"id": k, "family": fam, "name": k, "params": [{"name": "minute"}]} for k, fam in
                              (("dummy_up_0944", "existing_repo"), ("dummy_down_1100", "trend"),
                               ("near_expiry_first_hour_drive", "context"), ("dummy_up_1000_even_days", "trend"))]}
        s2, o2 = os.path.join(tmp, "study2"), os.path.join(tmp, "out2")
        os.makedirs(s2)
        os.makedirs(o2)
        for k, v in (("protocol.md", "rules\n"), ("engine.py", "# e\n"), ("ctx.py", "# c\n")):
            with open(os.path.join(s2, k), "w", encoding="utf-8") as fh:
                fh.write(v)
        write_json(os.path.join(s2, "library.json"), lib)
        refuses(lambda: step_signals(s2, o2, None, modules=[cheater], verbose=False),
                "signals step with a look-ahead dummy and two candidates missing", "do not match library.json")
        lib1 = {"candidates": lib["candidates"][:1]}
        write_json(os.path.join(s2, "library.json"), lib1)
        refuses(lambda: step_signals(s2, o2, None, modules=[cheater], verbose=False),
                "signals step with a dummy that reads the day's last bar", "offending candidates")
        check(not os.path.exists(os.path.join(o2, "signals_discovery.json")), "no signals file is written when the check fails")
        write_json(os.path.join(s2, "library.json"), lib)
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            step_signals(s2, o2, "T0", modules=[dummy], verbose=True)
        txt = buf.getvalue()
        check("signal COUNTS only" in txt and "dummy_down_1100" in txt and "Rs" not in txt and "saved" in txt,
              "signals step printout (captured): candidates and signal counts, no rupee figure")
        sf = read_json(os.path.join(o2, "signals_discovery.json"))
        n_days = len(sessions["NIFTY"])
        even = sum(1 for dd in sessions["NIFTY"] if int(dd[8:]) % 2 == 0)
        v0 = sf["candidates"]["dummy_up_0944"]["variants"]
        check(list(sf["candidates"]) == ["dummy_up_0944", "dummy_down_1100", "dummy_up_1000_even_days"]
              and "near_expiry_first_hour_drive" not in sf["candidates"],
              "signals file: the 3 dummies in library order; the struck candidate was not run")
        check(len(v0) == 3 and [v["label"] for v in v0] == ["centre", "minute=09:39", "minute=09:49"]
              and len(v0[0]["signals"]["NIFTY"]) == n_days and v0[1]["signals"]["SENSEX"][sessions["SENSEX"][0]] == ["09:39", "UP"]
              and len(sf["candidates"]["dummy_up_1000_even_days"]["variants"][0]["signals"]["NIFTY"]) == even,
              f"signal counts: always-UP {n_days} days, even-day dummy {even} days, centre + 2 neighbours each")
        # a synthetic outcome table in the real file format
        def save_synth_table(odir, sdir, netx):
            tabs_ = {}
            for idx in INDEXES:
                T = Table(idx, sessions[idx])
                ok = ~np.isnan(netx[idx])
                T.status_e[:] = np.where(ok.any(axis=-1), ST_OK, ST_NO_FILL)
                T.status_x[:] = np.where(ok, ST_OK, np.where(ok.any(axis=-1)[..., None], ST_NO_EXIT, ST_NO_FILL))
                T.buy[:] = 200.0
                T.open[:] = 199.0
                T.lot[:] = 65 if idx == "NIFTY" else 20
                T.strike[:] = 25000.0
                T.net[:] = np.round(netx[idx], 2)
                T.costs[:] = 100.0
                T.gross[:] = T.net + 100.0
                T.sell[:] = 200.0 + T.gross / T.lot[..., None]
                T.pct[:] = 100.0 * T.net / (T.buy * T.lot)[..., None]
                T.pts[:] = 1.0
                T.exit_min[:] = 914
                T.dte[:] = 3
                T.expiry = [markets[idx].expiry(dd) for dd in sessions[idx]]
                tabs_[idx] = T.seal()
            npz_ = os.path.join(odir, "outcome_discovery.npz")
            save_tables(npz_, tabs_)
            write_json(os.path.join(odir, "outcome_discovery.json"),
                       {"split": "DISCOVERY", "indexes": list(INDEXES), "sessions": sessions,
                        "expiry": {idx: tabs_[idx].expiry for idx in INDEXES},
                        "non_ok": {idx: non_ok_shares(tabs_[idx]) for idx in INDEXES}, "hashes": study_hashes(sdir),
                        "py_funcs_sha256": sha256_file(PY_FUNCS_PATH), "npz_sha256": sha256_file(npz_)})
            return tabs_, npz_

        tabs, npz = save_synth_table(o2, s2, synth_net(np.random.default_rng(5)))
        back = load_tables(npz, read_json(os.path.join(o2, "outcome_discovery.json")))
        check(all(np.array_equal(getattr(back[idx], k), getattr(tabs[idx], k), equal_nan=True)
                  for idx in INDEXES for k in ("status_e", "status_x", "net", "pct", "buy", "lot", "exit_min", "dte")),
              "outcome table: save -> load round trip is exact")
        refuses(lambda: step_score(s2, o2, None, None, quiet=True), "score step without --stamp", "--stamp")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = step_score(s2, o2, "T1", None, n_draws=200, quiet=False)
        txt = buf.getvalue()
        i_nonok, i_p85, i_scores = txt.find("P3.4 non-OK share"), txt.find("P8.5 - before any score"), txt.find("Scores (S =")
        check(0 <= i_nonok < i_p85 < i_scores and txt.find("dummy_up_0944") > i_scores
              and ("WINNER (P9)" in txt or "NOT VALIDATED - DO NOT TRADE" in txt),
              "score step printout (captured, synthetic table): non-OK share, then the P8.5 bar, and only then any candidate's score")
        log = read_json(os.path.join(o2, "run_log.json"))
        check(len(log) == 1 and log[0]["run"] == 1 and log[0]["stamp"] == "T1" and log[0]["status"] == "completed"
              and log[0]["hashes"] == study_hashes(s2), "run_log.json: run 1 with the stamp given and every hash")
        cr = res["candidates"]
        ok_arith = True
        for cid, r in cr.items():
            meds = []
            for idx in INDEXES:
                ts_ = []
                for e in EXITS:
                    xs = [t["exits"][e]["net"] for t in r["trades"] if t["index"] == idx and t["exits"][e]["status"] == "OK"]
                    t_ = (statistics.mean(xs) / (statistics.stdev(xs) / math.sqrt(len(xs)))) if len(xs) >= 20 and statistics.stdev(xs) > 0 else 0.0
                    ok_arith &= abs(t_ - r["per_index"][idx]["exits"][e]["t"]) < 1e-6 and len(xs) == r["per_index"][idx]["exits"][e]["n"]
                    ok_arith &= abs(sum(xs) - r["per_index"][idx]["exits"][e]["net"]) < 1e-4
                    ts_.append(t_)
                meds.append(statistics.median(ts_))
            ok_arith &= abs(min(meds) - r["S"]) < 1e-6
            comb = {}
            for t in r["trades"]:
                if t["exits"]["EOD"]["status"] == "OK":
                    comb[t["day"]] = comb.get(t["day"], 0.0) + t["exits"]["EOD"]["net"]
            ok_arith &= abs(sum(comb.values()) - r["combined"]["total"]) < 1e-4
            ok_arith &= abs(max(comb.values()) - r["combined"]["best_date_net"]) < 1e-6
            ok_arith &= all(abs(sum(v for dd, v in comb.items() if dd[:7] == m) - r["combined"]["by_month"][m]) < 1e-4
                            for m in DISCOVERY_MONTHS)
            ok_arith &= r["gates"]["d"]["pass"] == (sum(comb.values()) - max(comb.values()) > 0)
            ok_arith &= all(0.0 < r["p"][k] <= 1.0 for k in ("A", "B", "REF")) and r["p"]["used"] == max(r["p"]["A"], r["p"]["B"])
            ok_arith &= len(r["neighbours"]) == 2 and set(r["gates"]) == set("abcdef")
            ok_arith &= r["all_gates_pass"] == all(g["pass"] for g in r["gates"].values())
        check(ok_arith, "results: per-exit n / net / t, S, combined net, months, best date, gate (d) and the p range all "
                        "agree with a recomputation from the stored trade list (statistics module)")
        check(res["meta"]["family_size"] == 3 and res["nulls"]["A"]["maximum_quantiles"]["draws"] == 200
              and res["nulls"]["B"]["maximum_quantiles"]["draws"] == cal.W - 1 and len(res["ranking"]) == 3
              and cr["dummy_up_0944"]["previously_seen_on_this_data"] is True and "q75_of_null_maximum" in res["p85"]["A"],
              "results: family of 3, null A / B / reference draws, ranking, P8.5 block, the PREVIOUSLY SEEN flag")
        fz_there = os.path.isfile(os.path.join(o2, "freeze.json"))
        check(fz_there == (res["winner"] is not None), f"freeze.json exists exactly when there is a winner (winner: "
              f"{'yes' if res['winner'] else 'none'}, freeze.json: {'written' if fz_there else 'absent'})")
        if not fz_there:
            refuses(lambda: holdout_guard(s2, o2), "holdout guard after a score with no winner", "no freeze.json")
        res_b = step_score(s2, o2, "T2", None, n_draws=200, quiet=True)
        log = read_json(os.path.join(o2, "run_log.json"))
        check(len(log) == 2 and log[1]["reason"] == "re-run, no file changed"
              and [res_b["candidates"][k]["S"] for k in res_b["ranking"]] == [res["candidates"][k]["S"] for k in res["ranking"]]
              and [res_b["candidates"][k]["p"] for k in res_b["ranking"]] == [res["candidates"][k]["p"] for k in res["ranking"]],
              "a second score run with unchanged files needs no reason, is logged as run 2 and reproduces S and p exactly")
        with open(os.path.join(s2, "signals_new.py"), "w", encoding="utf-8") as fh:
            fh.write("# a change after the first scoring run\n")
        refuses(lambda: step_score(s2, o2, "T3", None, quiet=True), "score after a code change without --reason", "no --reason")
        check(len(read_json(os.path.join(o2, "run_log.json"))) == 2, "the refused run added nothing to run_log.json")
        refuses(lambda: step_score(s2, o2, "T3", "testing the log", n_draws=200, quiet=True),
                "score after a code change WITH --reason but stale signals", "full discovery re-run needed")
        log = read_json(os.path.join(o2, "run_log.json"))
        check(len(log) == 3 and log[2]["reason"] == "testing the log" and log[2]["changed_since_previous_run"] == ["signals_new.py: new file"]
              and log[2]["status"].startswith("refused") and not os.path.isfile(os.path.join(o2, "freeze.json")),
              "run 3 is logged with its reason and the changed file, refuses until signals are re-run, and leaves no freeze.json")

        # the winner path: the even-day dummy really earns on ITS days (centre and both neighbours); nobody else does
        o3 = os.path.join(tmp, "out3")
        os.makedirs(o3)
        step_signals(s2, o3, "T4", modules=[dummy], verbose=False)
        netw = synth_net(np.random.default_rng(6))
        for idx in INDEXES:
            even_days = np.array([int(dd[8:]) % 2 == 0 for dd in sessions[idx]])
            for t_sig in ("09:50", "10:00", "10:10"):
                fi = C.minutes(t_sig) + 1 - FILL0
                cell = netw[idx][even_days, fi, 0, :]
                netw[idx][even_days, fi, 0, :] = np.where(np.isnan(cell), 0.0, cell) + 3000.0
        save_synth_table(o3, s2, netw)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res_w = step_score(s2, o3, "T5", None, n_draws=200, quiet=False)
        fzp = os.path.join(o3, "freeze.json")
        fzw = read_json(fzp) if os.path.isfile(fzp) else {}
        win = "dummy_up_1000_even_days"
        check(res_w["winner"] == win and res_w["candidates"][win]["all_gates_pass"] and f"WINNER (P9): {win}" in buf.getvalue()
              and [k for k in res_w["candidates"] if res_w["candidates"][k]["all_gates_pass"]] == [win],
              f"a dummy with a planted day-specific edge passes all six gates and wins (S {res_w['candidates'][win]['S']:.1f}, "
              f"p {res_w['candidates'][win]['p']['used']:.4f}); the two fixed-minute dummies do not")
        check(fzw.get("winner") == win and fzw.get("params") == c3 and fzw.get("hashes") == study_hashes(s2)
              and fzw.get("stamp") == "T5" and fzw.get("py_funcs_sha256") == sha256_file(PY_FUNCS_PATH)
              and fzw.get("results_discovery_sha256") == sha256_file(os.path.join(o3, "results_discovery.json")),
              "freeze.json: winner id, its parameters, the SHA-256 of protocol.md / library.json / every .py, the stamp")
        check(holdout_guard(s2, o3)["winner"] == win, "the holdout guard accepts that freeze while nothing has changed (temp folder)")
        with open(os.path.join(s2, "signals_new.py"), "a", encoding="utf-8") as fh:
            fh.write("# one more line\n")
        refuses(lambda: holdout_guard(s2, o3), "the holdout guard after one .py gained a line", "changed after the freeze")
        with open(os.path.join(s2, "signals_new.py"), "w", encoding="utf-8") as fh:
            fh.write("# a change after the first scoring run\n")
        save_synth_table(o3, s2, synth_net(np.random.default_rng(5)))
        res_n = step_score(s2, o3, "T6", None, n_draws=200, quiet=True)
        last = read_json(os.path.join(o3, "run_log.json"))[-1]
        check(res_n["winner"] is None and not os.path.isfile(fzp) and "removed the freeze.json" in json.dumps(last),
              "a later scoring run with no winner removes the earlier freeze.json and says so in run_log.json")

        # -------------------------------------------------------------- (ix)
        print("== (ix) the outcome-row code on real discovery candles: fast path == plain-Python second coding ==")
        rng = np.random.default_rng(11)
        days = {idx: [sessions[idx][i] for i in sorted(rng.choice(len(sessions[idx]), 3, replace=False).tolist())] for idx in INDEXES}
        n_all, bad_all = 0, []
        for idx in INDEXES:
            T = build_table(markets[idx], days[idx])
            n, bad = compare_rows(T, markets[idx])
            n_all += n
            bad_all += bad
        check(n_all == 2 * 3 * NF * 2 and not bad_all,
              f"{n_all} rows on 3 random discovery days per index: status, strike, lot, buy, and per exit stamp / sell / gross / "
              f"costs / net / % / index points identical ({len(bad_all)} mismatches)")
        cd = ContractDay([["09:20", 100.0, 110.0, 95.0, 100.0, 50, 1], ["09:21", 100.0, 101.0, 60.0, 65.0, 50, 1],
                          ["09:22", 65.0, 65.0, 65.0, 65.0, 0, 1], ["09:23", 64.0, 66.0, 61.0, 62.0, 50, 1],
                          ["10:20", 80.0, 80.0, 80.0, 80.0, 0, 1], ["10:22", 90.0, 91.0, 88.0, 90.0, 50, 1],
                          ["15:14", 120.0, 120.0, 120.0, 120.0, 0, 1], ["15:20", 130.0, 131.0, 128.0, 130.0, 50, 1]])
        Th = Table("NIFTY", ["2026-01-05"])
        _fill_row(Th, 0, 0, 0, cd, 65, date(2026, 1, 5), "NSE", [25000.0 + i for i in range(NBAR)], 25004.0)
        cost = py_funcs.option_round_trip("LONG", 110.0, 128.0, 65, day=date(2026, 1, 5), exchange="NSE")
        check(Th.buy[0, 0, 0] == 110.0 and C.hhmm(int(Th.exit_min[0, 0, 0, 0])) == "15:20" and Th.sell[0, 0, 0, 0] == 128.0
              and C.hhmm(int(Th.exit_min[0, 0, 0, 1])) == "10:22" and Th.sell[0, 0, 0, 1] == 88.0
              and C.hhmm(int(Th.exit_min[0, 0, 0, 2])) == "09:23" and Th.sell[0, 0, 0, 2] == 61.0
              and abs(Th.net[0, 0, 0, 0] - round((128.0 - 110.0) * 65 - cost, 2)) < 1e-9
              and abs(Th.pct[0, 0, 0, 0] - 100.0 * Th.net[0, 0, 0, 0] / (110.0 * 65)) < 1e-9
              and Th.pts[0, 0, 0, 0] == (25000.0 + (920 - BAR0)) - 25004.0,
              "hand-made contract: buy at the 09:20 HIGH 110; EOD skips the zero-volume 15:14 bar and sells at the 15:20 LOW 128; "
              "H60 skips 10:20 (no volume) and 10:21 (missing) -> 10:22 LOW 88; STOP30 (level 77) triggers on the 09:21 close 65, "
              "skips the zero-volume 09:22 bar and sells at the 09:23 LOW 61 (below the level, not capped)")
        _fill_row(Th, 0, 2, 0, cd, 65, date(2026, 1, 5), "NSE", [25000.0] * NBAR, 25000.0)      # 09:22: volume 0
        _fill_row(Th, 0, 4, 0, cd, 65, date(2026, 1, 5), "NSE", [25000.0] * NBAR, 25000.0)      # 09:24: no bar
        cd2 = ContractDay([["09:20", 100.0, 110.0, 95.0, 100.0, 50, 1], ["15:13", 100.0, 100.0, 100.0, 100.0, 50, 1],
                           ["15:14", 100.0, 100.0, 100.0, 100.0, 0, 1]])
        _fill_row(Th, 0, 0, 1, cd2, 65, date(2026, 1, 5), "NSE", [25000.0] * NBAR, 25000.0)
        check(Th.status_e[0, 2, 0] == ST_NO_FILL and Th.status_e[0, 4, 0] == ST_NO_DATA and Th.status_e[0, 0, 1] == ST_OK
              and Th.status_x[0, 0, 1].tolist() == [ST_NO_EXIT, ST_OK, ST_NO_EXIT]
              and C.hhmm(int(Th.exit_min[0, 0, 1, 1])) == "15:13",
              "statuses: zero-volume fill bar -> NO_FILL; missing fill bar -> NO_DATA; no traded bar from 15:14 -> EOD and "
              "STOP30 (no trigger, sold as EOD) are NO_EXIT, while H60 fills at the first traded bar at or after 10:20 "
              "(the 15:13 bar)")

        # -------------------------------------------------------------- (x)
        print("== (x) the holdout machinery, dry run on DISCOVERY days with a dummy (nothing printed about its result) ==")
        pretend = {idx: [dd for dd in sessions[idx] if dd >= "2026-03-01"] for idx in INDEXES}

        def dummy_fn(ctx_, base="10:30"):
            m = C.minutes(base) + (int(ctx_.day[8:]) % 5) * 7
            t = C.hhmm(m)
            return (t, "UP" if int(ctx_.day[8:]) % 3 else "DOWN") if (ctx_.bars and ctx_.bars[-1][0] >= t) else None

        hr = holdout_compute(markets, pretend, dummy_fn, {"base": "10:30"}, n_draws=200)
        tabs_h = hr.pop("_tabs")
        computed = {idx: int((tabs_h[idx].status_e != ST_NOT_COMPUTED).sum()) for idx in INDEXES}
        full = {idx: len(pretend[idx]) * NF * 2 for idx in INDEXES}
        cmp_h = [compare_rows(tabs_h[idx], markets[idx]) for idx in INDEXES]
        n_cmp, n_bad = sum(c[0] for c in cmp_h), sum(len(c[1]) for c in cmp_h)
        check(all(0 < computed[idx] < 0.05 * full[idx] for idx in INDEXES) and n_bad == 0 and n_cmp == sum(computed.values()),
              f"only the rows the entry and its null need are computed ({computed} of {full}); all {n_cmp} agree with the second coding")
        check(hr["verdict"] in ("CONFIRMED", "WEAK", "NOT CONFIRMED") and hr["min_n"] == 10 and not hr["lookahead_offenders"]
              and 0 < hr["p"]["A"] <= 1 and 0 < hr["p"]["B"] <= 1 and hr["p"]["used"] == max(hr["p"]["A"], hr["p"]["B"])
              and hr["null_draws"]["B"] == len(hr["weeks"]) - 1 and hr["null_draws"]["A"] == 200
              and hr["signals"]["NIFTY"] == len(pretend["NIFTY"])
              and (hr["verdict"] == "CONFIRMED") == (hr["p"]["used"] <= HOLDOUT_P and hr["combined_eod_net"] > 0)
              and (hr["verdict"] == "WEAK") == (hr["p"]["used"] > HOLDOUT_P and hr["combined_eod_net"] > 0),
              "holdout result block is complete and the verdict follows P10.3 from its own p and combined net")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_holdout({**hr, "meta": {"second_coding_check": {"rows_compared": n_cmp, "mismatches": []}},
                           "independence": "INDEPENDENT", "error_budget": "budget", "sentence": "sentence"})
        check("HOLDOUT VERDICT" in buf.getvalue() and "bootstrap" in buf.getvalue(),
              "the holdout printout runs on the dry-run result (captured, not shown)")
        bt = hr["bootstrap_90_mean_combined_net_per_date"]
        check(bt["low"] is not None and bt["low"] <= bt["high"] and bt["resamples"] == 200
              and set(hr["null_mean"]) == {"A", "B"} and hr["null_mean"]["A"]["mean_net_per_trade_pooled"] is not None
              and all(k in hr for k in ("holdout_trades", "mean_net_per_trade", "rupees_per_index", "pct_of_premium_per_index", "trades")),
              "P10.5 block: trades, mean net per trade, week-block bootstrap interval, null means, rupees and % of premium per index")
        md = {idx: markets[idx].max_dates() for idx in INDEXES}
        check(all(v is None or v <= C.DISCOVERY_END for idx in INDEXES for v in
                  (md[idx]["index"], md[idx]["vix"], md[idx]["option_files"], md[idx]["option_days"])),
              f"after the whole selftest the latest candle held in memory is {max(md[i]['index'] for i in INDEXES)} "
              f"(index) / {max(md[i]['option_files'] for i in INDEXES)} (options): the holdout was never opened")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nselftest: {'ALL PASS' if not fails else str(len(fails)) + ' FAILED'}  ({time.perf_counter() - t_start:.0f} s)")
    for x in fails:
        print("   FAILED: " + x)
    return 1 if fails else 0


# ---------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="intraday-entry study: the measuring machine of protocol.md")
    ap.add_argument("--step", required=True, choices=("table", "signals", "score", "holdout", "selftest"))
    ap.add_argument("--stamp", default=None, help="timestamp text recorded in the outputs (required for score / holdout)")
    ap.add_argument("--reason", default=None, help="why the study files changed since the previous scoring run (P4.3)")
    ap.add_argument("--confirm", default=None, help="holdout only: OPEN-HOLDOUT")
    a = ap.parse_args()
    try:
        if a.step == "table":
            step_table(STUDY_DIR, OUT_DIR, a.stamp)
        elif a.step == "signals":
            step_signals(STUDY_DIR, OUT_DIR, a.stamp)
        elif a.step == "score":
            step_score(STUDY_DIR, OUT_DIR, a.stamp, a.reason)
        elif a.step == "holdout":
            step_holdout(STUDY_DIR, OUT_DIR, a.stamp, a.confirm)
        else:
            return _selftest()
    except Refusal as e:
        print(f"\nREFUSED: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
