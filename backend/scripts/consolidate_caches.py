"""Fold the window-named caches into the four single files, once.

    nifty_1m_*.json            -> data/nifty_1m.json
    nifty_1d_*.json            -> data/nifty_1d.json
    nifty_fut_volume_*.json    -> data/nifty_fut_volume.json
    nifty_option_cache.json    \\
    nifty_option_ohlc_cache.json> data/nifty_options.json
    nifty_contract_cache.json  /
    nifty_expiry_cache.json    /
    reversal_*_cache.json      /  (the older scripts' copies)

Nothing is fetched and nothing is deleted: the old files stay until `--remove`
is passed, and every candle is read back out of the new file and compared with
the source before that is allowed.

    python scripts/consolidate_caches.py            # build and verify
    python scripts/consolidate_caches.py --remove   # build, verify, delete the old files
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..")
sys.path.insert(0, BACKEND_DIR)

from services.market_data import (  # noqa: E402
    DATA_DIR, MINUTE_FILE, DAILY_FILE, FUTVOL_FILE, OPTIONS_FILE,
    CandleStore, OptionFile, _load_json, _save_json, merge_ranges)

MB = 1e6


def _window_of(name: str, prefix: str) -> tuple[str, str] | None:
    stem = name[len(prefix):-len(".json")]
    try:
        a, b = stem.split("_")
        date.fromisoformat(a), date.fromisoformat(b)
        return a, b
    except ValueError:
        return None


def build_candles(prefix: str, out_path: str, interval: str) -> tuple[CandleStore, list[str], dict]:
    """Merge every window-named file of one feed into a single store."""
    srcs = sorted(f for f in glob.glob(os.path.join(DATA_DIR, prefix + "*.json"))
                  if _window_of(os.path.basename(f), prefix))
    st = CandleStore(out_path, "NIFTY", interval)
    asked: list[list[str]] = []
    source_rows: dict[str, dict] = {}       # day -> {key: row} straight from the sources
    for f in srcs:
        win = _window_of(os.path.basename(f), prefix)
        raw = _load_json(f) or []
        if not isinstance(raw, list):
            print(f"  ! {os.path.basename(f)}: unexpected shape, skipped")
            continue
        st.put(raw, date.fromisoformat(win[0]), date.fromisoformat(win[1]), mark_covered=False)
        asked.append([win[0], win[1]])
        daily = interval == "1d"
        for c in raw:
            ts = c.get("timestamp", "")
            if len(ts) >= 16:
                row = CandleStore._candle_to_row(c, daily)
                source_rows.setdefault(ts[:10], {})[row[0]] = row
        print(f"  {os.path.basename(f):44s} {os.path.getsize(f)/MB:6.1f} MB  {len(raw):7d} rows")
    if not st.days:
        return st, srcs, source_rows
    # A range is only "covered" up to the last session it actually delivered:
    # the tail of a range fetched intraday may still be incomplete, and a daily
    # candle for the final day is published only after that day's close.
    last = max(st.days)
    st.covered = [[r[0], min(r[1], last)] for r in merge_ranges(asked)]
    st.covered = merge_ranges([r for r in st.covered if r[0] <= r[1]])
    st.save()
    return st, srcs, source_rows


def verify_candles(st: CandleStore, source_rows: dict, label: str) -> bool:
    """Every source row must come back out of the new file, unchanged."""
    fresh = CandleStore(st.path, "NIFTY", st.interval)
    bad = 0
    for day, rows in source_rows.items():
        have = {r[0]: r for r in fresh.days.get(day, [])}
        for k, row in rows.items():
            if have.get(k) != row:
                bad += 1
                if bad <= 3:
                    print(f"    ! {label} {day} {k}: {have.get(k)} != {row}")
    total = sum(len(v) for v in source_rows.values())
    print(f"  verify {label}: {total} source rows, {bad} mismatches, "
          f"{len(fresh.days)} sessions, {os.path.getsize(st.path)/MB:.1f} MB, "
          f"covered {fresh.covered}")
    return bad == 0


def build_futvol() -> list[str]:
    srcs = sorted(f for f in glob.glob(os.path.join(DATA_DIR, "nifty_fut_volume_*.json"))
                  if _window_of(os.path.basename(f), "nifty_fut_volume_"))
    if not srcs:
        return []
    minutes: dict[str, float] = {}
    for f in srcs:
        raw = _load_json(f) or {}
        minutes.update(raw.get("minutes", raw))
        print(f"  {os.path.basename(f):44s} {os.path.getsize(f)/MB:6.1f} MB  {len(raw):7d} minutes")
    _save_json(FUTVOL_FILE, {"instrument": "NIFTY front-month future",
                             "minutes": dict(sorted(minutes.items()))})
    back = _load_json(FUTVOL_FILE)["minutes"]
    print(f"  verify futures volume: {len(minutes)} minutes in, {len(back)} out, "
          f"{min(back)} -> {max(back)}")
    return srcs if len(back) == len(minutes) else []


def build_options() -> list[str]:
    """Contracts, expiries and candles from both spellings and both caches."""
    of = OptionFile(OPTIONS_FILE)
    srcs = []
    for name in ("nifty_expiry_cache.json", "reversal_expiry_cache.json"):
        p = os.path.join(DATA_DIR, name)
        if os.path.exists(p):
            of.expiries = sorted(set(of.expiries) | set(_load_json(p) or []))
            srcs.append(p)
    for name in ("nifty_contract_cache.json", "reversal_contract_cache.json"):
        p = os.path.join(DATA_DIR, name)
        if os.path.exists(p):
            for k, v in (_load_json(p) or {}).items():
                of.contracts.setdefault(k, v)
            srcs.append(p)
    # instrument_key (dated and undated) -> the stable EXPIRY|STRIKE|TYPE key
    by_ik: dict[str, str] = {}
    for ckey, c in of.contracts.items():
        if not c:
            continue
        ik = c.get("instrument_key") or ""
        by_ik[ik] = ckey
        parts = ik.split("|")
        if len(parts) == 3:
            by_ik[f"{parts[0]}|{parts[1]}"] = ckey

    def stable(key: str) -> str | None:
        """Normalise a candle key to EXPIRY|STRIKE|TYPE|DAY."""
        parts = key.split("|")
        day = parts[-1]
        head = "|".join(parts[:-1])
        if len(parts) == 4 and parts[2] in ("CE", "PE"):
            return key                                  # already stable
        return f"{by_ik[head]}|{day}" if head in by_ik else None

    unresolved = 0
    for name, is_ohlc in (("nifty_option_cache.json", False),
                          ("reversal_option_cache.json", False),
                          ("nifty_option_ohlc_cache.json", True)):
        p = os.path.join(DATA_DIR, name)
        if not os.path.exists(p):
            continue
        raw = _load_json(p) or {}
        n = 0
        for key, bars in raw.items():
            sk = stable(key)
            if sk is None:
                unresolved += 1
                continue
            if is_ohlc:
                of.put(sk, {m: [float(v[0]), float(v[1]), float(v[2]), float(v[3])]
                            for m, v in bars.items()}, close_only=False)
            elif sk not in of.candles or sk in of.close_only:
                of.put(sk, {m: float(v) for m, v in bars.items()}, close_only=True)
            else:
                of.fetched.add(sk)
            n += 1
        srcs.append(p)
        print(f"  {name:44s} {os.path.getsize(p)/MB:6.1f} MB  {len(raw):7d} keys, {n} folded in")
    if unresolved:
        print(f"  ! {unresolved} candle keys had no matching contract and were left out")
    of.save()
    back = OptionFile(OPTIONS_FILE)
    s = back.summary()
    print(f"  verify options: {s['contracts']} contracts, {s['contract_days']} contract-days "
          f"({s['close_only']} close-only), {s['from']} -> {s['to']}, "
          f"{os.path.getsize(OPTIONS_FILE)/MB:.1f} MB")
    return srcs


def main() -> None:
    remove = "--remove" in sys.argv
    print("minute candles"); m_st, m_src, m_rows = build_candles("nifty_1m_", MINUTE_FILE, "1m")
    ok_m = verify_candles(m_st, m_rows, "1m")
    print("daily candles"); d_st, d_src, d_rows = build_candles("nifty_1d_", DAILY_FILE, "1d")
    ok_d = verify_candles(d_st, d_rows, "1d")
    print("futures volume"); v_src = build_futvol()
    print("options"); o_src = build_options()
    before = sum(os.path.getsize(f) for f in m_src + d_src + v_src + o_src)
    after = sum(os.path.getsize(f) for f in (MINUTE_FILE, DAILY_FILE, FUTVOL_FILE, OPTIONS_FILE)
                if os.path.exists(f))
    print(f"\n{len(m_src + d_src + v_src + o_src)} source files, {before/MB:.1f} MB "
          f"-> 4 files, {after/MB:.1f} MB")
    if not (ok_m and ok_d):
        print("! verification failed - the old files are kept")
        return
    if remove:
        for f in m_src + d_src + v_src + o_src:
            os.remove(f)
            print(f"  removed {os.path.basename(f)}")
    else:
        print("re-run with --remove to delete the source files")


if __name__ == "__main__":
    main()
