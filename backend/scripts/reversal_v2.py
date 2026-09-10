"""NIFTY opening-range reversal — v2, the relaxed entry rule.

Self-contained: this file is the whole v2 strategy.  It imports nothing from
the other version files.

WHAT CHANGED FROM v1
--------------------
v1 required NIFTY to be outside the opening range at `t`.  v2 drops that
entirely.  Qualification now rests only on WHICH EDGE was never breached plus
the direction of the 09:20->t trend; where NIFTY happens to sit at `t` is
irrelevant.

    2A. every candle 09:20 -> t stayed BELOW OR high + down-trend -> BUY ATM CE
    2B. every candle 09:20 -> t stayed ABOVE OR low  + up-trend   -> BUY ATM PE

The two clauses overlap: on a day that never left the opening range both hold,
and the trend alone decides.  classify_trend() returns a single direction, so
that is never ambiguous.  A day that breached one edge can still qualify on the
other clause, but only if the trend agrees with it.

Expect materially more signals than v1, since every "still inside the range at
t" day is now tradable.

TRADE MANAGEMENT (all levels measured on NIFTY spot, not on the option)
  entry   NIFTY close at `t`; ATM strike = that value rounded to nearest 50,
          nearest expiry on/after the trade date.
  stop    --stop percent of spot against the trade (default 0.1%)
  target  stop x R, swept over the --rr ladder
  exit    first 1-minute candle after `t` whose high/low touches either level
          (stop is checked first when one candle spans both), else squared off
          at the 15:00 close.
  prices  the ATM option's 1-minute closes at the entry and exit minutes.

Run from backend/:
    python scripts/reversal_v2.py --offline
    python scripts/reversal_v2.py --trend strict

Output: reversal_v2_report.html (self-contained, no CDN).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import date, timedelta
from urllib.parse import quote

import httpx

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..")
sys.path.insert(0, BACKEND_DIR)

# backend/scripts holds only strategy code; the candle caches live in
# backend/data and the generated reports in backend/reports.
DATA_DIR = os.path.join(BACKEND_DIR, "data")
REPORTS_DIR = os.path.join(BACKEND_DIR, "reports")

from services.upstox_client import (  # noqa: E402
    INSTRUMENT_KEYS, get_candles, get_option_contracts)
from services.option_pricing import (  # noqa: E402
    RateLimiter, api_get, ContractResolver, OptionCandleStore,
    get_expired_expiries, get_expired_option_contracts,
    get_option_day_candles)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CONFIG_FILE = os.path.join(BACKEND_DIR, "upstox_config.txt")
# The contract / option-candle / expiry caches now live in
# backend/services/option_pricing.py and are SHARED with every other
# strategy, so a contract fetched once is never fetched again.
EXPIRY_CACHE = os.path.join(DATA_DIR, "nifty_expiry_cache.json")

BASE_V2 = "https://api.upstox.com/v2"
UNDERLYING = "NIFTY"
UNDERLYING_KEY = INSTRUMENT_KEYS[UNDERLYING]

RANGE_FROM = date(2026, 1, 1)
RANGE_TO = date(2026, 9, 3)

STRIKE_STEP = 50
# NIFTY option lot size.  Verified against the Upstox contract master (both the
# live /option/contract feed and the expired-instruments contracts for Jan/Apr/
# Aug 2026): every NIFTY contract in this date range carries lot_size 65.
# ContractResolver.resolve() re-checks each contract it touches and warns loudly
# if a different lot size ever shows up.
LOT_SIZE = 65

T_VALUES = ["11:00", "11:10", "11:15", "11:20", "11:30", "11:40", "11:45", "12:00"]
DEFAULT_T = "11:30"

OPEN_TIME = "09:15"
FIRST5_TIMES = ["09:15", "09:16", "09:17", "09:18", "09:19"]
TREND_START = "09:20"
SQUARE_OFF = "15:00"
DAY_END = "15:30"

MIN_TREND_POINTS = 20            # need at least this many 1m closes in 09:20..t

STOP_PCT = 0.1                                   # % of NIFTY spot, fixed
PREFERRED_RR_LABEL = "1:2"

# Weekly NIFTY expiries used only to fill gaps the Upstox expiry endpoints miss.
FALLBACK_EXPIRIES_2026: list[date] = [
    date(2026, 1, 6), date(2026, 1, 13), date(2026, 1, 20), date(2026, 1, 27),
    date(2026, 2, 3), date(2026, 2, 10), date(2026, 2, 17), date(2026, 2, 24),
    date(2026, 3, 3), date(2026, 3, 10), date(2026, 3, 17), date(2026, 3, 24), date(2026, 3, 31),
    date(2026, 4, 7), date(2026, 4, 14), date(2026, 4, 21), date(2026, 4, 28),
    date(2026, 5, 5), date(2026, 5, 12), date(2026, 5, 19), date(2026, 5, 26),
    date(2026, 6, 2), date(2026, 6, 9), date(2026, 6, 16), date(2026, 6, 23), date(2026, 6, 30),
    date(2026, 7, 7), date(2026, 7, 14), date(2026, 7, 21), date(2026, 7, 28),
    date(2026, 8, 4), date(2026, 8, 11), date(2026, 8, 18), date(2026, 8, 25),
]


REPORT_HTML = os.path.join(REPORTS_DIR, "reversal_v2_report.html")
DEFAULT_RR = [2.0, 3.0, 3.5, 4.0, 4.5, 5.0]


def nifty_cache_path(from_date: date, to_date: date) -> str:
    """One cache file per date range, so widening the range never reuses stale data."""
    return os.path.join(
        DATA_DIR, f"nifty_1m_{from_date.isoformat()}_{to_date.isoformat()}.json")


def rr_label(r: float) -> str:
    return f"1:{r:g}"


# ---------------------------------------------------------------------------
# Auth / HTTP helpers
# ---------------------------------------------------------------------------

def _read_access_token() -> str:
    with open(CONFIG_FILE) as f:
        lines = [l.strip() for l in f.readlines()]
    if len(lines) < 4 or not lines[3]:
        raise RuntimeError(f"No access_token found in {CONFIG_FILE}. Connect to Upstox first.")
    return lines[3]


# ---------------------------------------------------------------------------
# Upstox endpoints (expired-instruments variants)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# NIFTY spot data
# ---------------------------------------------------------------------------

async def load_nifty(token: str | None, offline: bool,
                     from_date: date, to_date: date) -> list[dict]:
    cache = nifty_cache_path(from_date, to_date)
    if os.path.exists(cache):
        with open(cache) as f:
            candles = json.load(f)
        print(f"Loaded {len(candles)} cached NIFTY 1m candles from {os.path.basename(cache)}")
        return candles
    if offline or not token:
        raise RuntimeError(f"{cache} missing and --offline was requested.")
    print(f"Fetching NIFTY 1m candles {from_date} -> {to_date} ...")
    candles = await get_candles(token, UNDERLYING_KEY, "1m", from_date, to_date)
    print(f"Fetched {len(candles)} candles.")
    with open(cache, "w") as f:
        json.dump(candles, f)
    return candles


def index_by_day(candles: list[dict]) -> dict[str, dict[str, dict]]:
    by_day: dict[str, dict[str, dict]] = defaultdict(dict)
    for c in candles:
        ts = c.get("timestamp", "")
        if len(ts) < 16:
            continue
        day, hhmm = ts[:10], ts[11:16]
        if OPEN_TIME <= hhmm <= DAY_END:
            by_day[day][hhmm] = c
    return by_day


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def _slope(v: list[float]) -> float:
    """Least-squares slope of v against its own index."""
    n = len(v)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2.0
    my = sum(v) / n
    den = sum((i - mx) ** 2 for i in range(n))
    return sum((i - mx) * (y - my) for i, y in enumerate(v)) / den if den else 0.0


def _bucket_means(values: list[float], k: int = 3) -> list[float]:
    n = len(values)
    out = []
    for i in range(k):
        chunk = values[n * i // k: n * (i + 1) // k]
        out.append(sum(chunk) / len(chunk) if chunk else 0.0)
    return out


def classify_trend(closes: list[float], mode: str) -> str | None:
    """Return 'down' | 'up' | None for the 09:20..t close series."""
    if len(closes) < MIN_TREND_POINTS:
        return None
    slope = _slope(closes)
    net = closes[-1] - closes[0]
    if mode == "loose":
        return "down" if slope < 0 else ("up" if slope > 0 else None)
    down = slope < 0 and net < 0
    up = slope > 0 and net > 0
    if mode == "moderate":
        return "down" if down else ("up" if up else None)
    b = _bucket_means(closes, 3)          # strict
    if down and b[0] > b[1] > b[2]:
        return "down"
    if up and b[0] < b[1] < b[2]:
        return "up"
    return None


# ---------------------------------------------------------------------------
# Entry rule
# ---------------------------------------------------------------------------

def detect_signal_v2(day_map: dict[str, dict], t: str, trend_mode: str) -> dict:
    """Relaxed rule: only the un-breached edge plus the trend direction matter."""
    first5 = [day_map[x] for x in FIRST5_TIMES if x in day_map]
    if len(first5) < 3:
        return {"met": False, "reason": "no opening-range candles"}
    or_high = max(c["high"] for c in first5)
    or_low = min(c["low"] for c in first5)
    base = {"or_high": or_high, "or_low": or_low}

    t_candle = day_map.get(t)
    if t_candle is None:
        return {**base, "met": False, "reason": f"no {t} candle"}
    base["nifty_t"] = t_candle["close"]

    window = [day_map[k] for k in sorted(day_map) if TREND_START <= k <= t]
    if len(window) < MIN_TREND_POINTS:
        return {**base, "met": False, "reason": "not enough candles 09:20-t"}

    stayed_below_high = all(c["high"] <= or_high for c in window)
    stayed_above_low = all(c["low"] >= or_low for c in window)
    trend = classify_trend([c["close"] for c in window], trend_mode)

    # 2A - never touched the top edge, and falling -> fade the fall, buy CE
    if stayed_below_high and trend == "down":
        return {**base, "met": True, "side": "BULLISH", "option_type": "CE",
                "reason": "2A: held below OR high + down-trend -> expect reversal up"}

    # 2B - never touched the bottom edge, and rising -> fade the rise, buy PE
    if stayed_above_low and trend == "up":
        return {**base, "met": True, "side": "BEARISH", "option_type": "PE",
                "reason": "2B: held above OR low + up-trend -> expect reversal down"}

    if not stayed_below_high and not stayed_above_low:
        reason = "breached both opening-range edges"
    elif trend is None:
        reason = "09:20-t has no clear trend"
    else:
        edge = "below OR high" if stayed_below_high else "above OR low"
        reason = f"held {edge} but 09:20-t trends {trend} (wrong way)"
    return {**base, "met": False, "reason": reason}


BASE_RULES = {"v2": detect_signal_v2}


def _keep(sig: dict) -> dict:
    """Strip trade-side keys so a filtered-out day reads cleanly as 'not met'."""
    return {k: v for k, v in sig.items()
            if k not in ("side", "option_type", "met", "reason")}


def make_detector(base: str, max_or_width: float | None = None, min_dist: float = 0.0,
                  rsi_max: float | None = None, ext_z_min: float | None = None,
                  consec_min: int | None = None, wick_min: float | None = None,
                  since_ext_min: int | None = None, side: str = "both"):
    """Wrap a base entry rule with the optimisation + confirmation filters."""
    base_fn = BASE_RULES[base]

    def detect(day_map: dict[str, dict], t: str, trend_mode: str) -> dict:
        sig = base_fn(day_map, t, trend_mode)
        if not sig.get("met"):
            return sig

        # Dropping a leg at DETECTION time (rather than filtering the results
        # afterwards) keeps the day table, chart, summaries and t x R:R matrix
        # all genuinely one-sided.  Excluded days stay listed, with the reason.
        if side != "both" and sig["option_type"] != side.upper():
            other = "above OR high + up-trend" if side == "ce" else "below OR low + down-trend"
            return {**_keep(sig), "met": False,
                    "reason": f"{sig['option_type']} side ({other}) - excluded, "
                              f"{side.upper()}-only report"}

        cur, hi, lo = sig["nifty_t"], sig["or_high"], sig["or_low"]

        # ---- confirmation filters, all measured at the entry minute ----
        if any(v is not None for v in
               (rsi_max, ext_z_min, consec_min, wick_min, since_ext_min)):
            d = 1 if sig["side"] == "BULLISH" else -1
            win = [day_map[k] for k in sorted(day_map) if TREND_START <= k <= t]
            f = features(win, d)
            if rsi_max is not None and f["rsi_ext"] > rsi_max:
                return {**_keep(sig), "met": False,
                        "reason": f"RSI {f['rsi_ext']:.0f} not stretched enough "
                                  f"(needs <= {rsi_max:g})"}
            if ext_z_min is not None and f["ext_z"] < ext_z_min:
                return {**_keep(sig), "met": False,
                        "reason": f"only {f['ext_z']:.2f} sd from the mean "
                                  f"(needs >= {ext_z_min:g})"}
            if consec_min is not None and f["consec"] < consec_min:
                return {**_keep(sig), "met": False,
                        "reason": f"{f['consec']} candle(s) still in the move "
                                  f"(needs >= {consec_min})"}
            if wick_min is not None and f["wick"] < wick_min:
                return {**_keep(sig), "met": False,
                        "reason": f"rejection wick {f['wick']:.2f} of range "
                                  f"(needs >= {wick_min:g})"}
            if since_ext_min is not None and f["since_ext"] < since_ext_min:
                return {**_keep(sig), "met": False,
                        "reason": f"extreme only {f['since_ext']}m ago "
                                  f"(needs >= {since_ext_min}m)"}

        if max_or_width is not None:
            width = (hi - lo) / cur * 100
            if width > max_or_width:
                return {**_keep(sig), "met": False,
                        "reason": f"opening range {width:.2f}% exceeds the "
                                  f"{max_or_width:g}% limit - too volatile"}

        if min_dist > 0:
            # how far beyond the edge being faded, as % of spot
            dist = ((lo - cur) / cur * 100 if sig["option_type"] == "CE"
                    else (cur - hi) / cur * 100)
            if dist < min_dist:
                return {**_keep(sig), "met": False,
                        "reason": f"only {dist:+.2f}% beyond the OR edge, "
                                  f"needs {min_dist:g}%"}
        return sig

    return detect


# ---------------------------------------------------------------------------
# Trade simulation on NIFTY spot
# ---------------------------------------------------------------------------

def simulate_exit(day_map: dict[str, dict], t: str, side: str, entry_spot: float,
                  target_pct: float, stop_pct: float) -> dict:
    """Walk 1m NIFTY candles after `t` until target/stop/15:00. Stop wins ties.

    target_pct / stop_pct are fractions (0.002 == 0.2%).
    """
    if side == "BULLISH":
        target = entry_spot * (1 + target_pct)
        stop = entry_spot * (1 - stop_pct)
    else:
        target = entry_spot * (1 - target_pct)
        stop = entry_spot * (1 + stop_pct)

    times = [k for k in sorted(day_map) if t < k <= SQUARE_OFF]
    for hhmm in times:
        c = day_map[hhmm]
        if side == "BULLISH":
            hit_stop = c["low"] <= stop
            hit_target = c["high"] >= target
        else:
            hit_stop = c["high"] >= stop
            hit_target = c["low"] <= target
        if hit_stop:
            return {"exit_time": hhmm, "exit_spot": stop, "close_type": "STOPLOSS",
                    "target": target, "stop": stop}
        if hit_target:
            return {"exit_time": hhmm, "exit_spot": target, "close_type": "TARGET",
                    "target": target, "stop": stop}

    if times:
        last = times[-1]
        return {"exit_time": last, "exit_spot": day_map[last]["close"], "close_type": "3PM",
                "target": target, "stop": stop}
    return {"exit_time": None, "exit_spot": None, "close_type": "NO DATA",
            "target": target, "stop": stop}


# ---------------------------------------------------------------------------
# Contract resolution / option candles
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Grouping / summaries
# ---------------------------------------------------------------------------

def week_key(d: date) -> str:
    monday = d - timedelta(days=d.weekday())
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d} ({monday.isoformat()})"


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def summarise(rows: list[dict]) -> dict:
    traded = [r for r in rows if r.get("traded")]
    wins = [r for r in traded if r["pnl"] > 0]
    losses = [r for r in traded if r["pnl"] <= 0]
    return {
        "days": len({r["date"] for r in traded}),
        "trades": len(traded),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(traded) * 100) if traded else 0.0,
        "pnl_pts": sum(r["pnl"] for r in traded),
        "pnl_rs": sum(r["pnl"] for r in traded) * LOT_SIZE,
        "nifty_pts": sum(r["nifty_pts"] for r in traded),
    }


def _grouped(rows: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    return [{"key": k, **summarise(v)} for k, v in sorted(groups.items())]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

async def run(trend_mode: str, offline: bool, out_path: str, detect_fn,
              rule_html: str, variant: str, from_date: date, to_date: date,
              rr_ratios: list[float], stop_pct: float) -> None:
    token = None if offline else _read_access_token()

    nifty = await load_nifty(token, offline, from_date, to_date)
    by_day = index_by_day(nifty)
    trading_days = sorted(
        d for d in by_day if from_date.isoformat() <= d <= to_date.isoformat())
    print(f"{len(trading_days)} trading days in range, trend mode = {trend_mode}")
    print(f"stop fixed at {stop_pct}%, targets: "
          + ", ".join(f"{rr_label(r)}={stop_pct * r:g}%" for r in rr_ratios))

    # ---- pass 1: signals (independent of the exit levels) ----
    signals: dict[str, dict[str, dict]] = {t: {} for t in T_VALUES}
    for day_str in trading_days:
        day_map = by_day[day_str]
        for t in T_VALUES:
            sig = detect_fn(day_map, t, trend_mode)
            if sig.get("met"):
                sig["atm"] = float(round(sig["nifty_t"] / STRIKE_STEP) * STRIKE_STEP)
            signals[t][day_str] = sig

    needed = {
        (day_str, s["atm"], s["option_type"])
        for t in T_VALUES for day_str, s in signals[t].items() if s.get("met")
    }
    print("Signals: " + ", ".join(
        f"{t}={sum(1 for s in signals[t].values() if s.get('met'))}" for t in T_VALUES))
    print(f"Unique option series needed: {len(needed)}")

    # ---- pass 2: contracts + option candles (cache-served when warm) ----
    option_prices: dict[tuple[str, float, str], dict] = {}
    missing: list[str] = []
    async with httpx.AsyncClient(timeout=40.0) as client:
        limiter = RateLimiter(0.3)

        # The real expiry calendar comes from Upstox; it is cached so that
        # --offline reruns resolve the same contracts as the online run did.
        all_expiries = sorted(set(FALLBACK_EXPIRIES_2026))
        if os.path.exists(EXPIRY_CACHE):
            with open(EXPIRY_CACHE) as f:
                all_expiries = sorted({date.fromisoformat(s) for s in json.load(f)})
        live_by_key: dict = {}
        live_expiries: list[date] = []
        if not offline:
            try:
                expired = [e for e in await get_expired_expiries(client, token, limiter)
                           if from_date <= e <= to_date + timedelta(days=30)]
                all_expiries = sorted(set(all_expiries) | set(expired))
            except RuntimeError as exc:
                print(f"! expired-expiries lookup failed ({exc}); using cached calendar")
            try:
                live = await get_option_contracts(token, UNDERLYING)
                live_expiries = sorted({date.fromisoformat(c["expiry"][:10]) for c in live})
                live_by_key = {(c["expiry"][:10], c["strike"], c["option_type"]): c for c in live}
                all_expiries = sorted(set(all_expiries) | set(live_expiries))
            except Exception as exc:
                print(f"! live option contracts lookup failed ({exc})")
            with open(EXPIRY_CACHE, "w") as f:
                json.dump([e.isoformat() for e in all_expiries], f, indent=0)

        resolver = ContractResolver(client, token, limiter, all_expiries,
                                    live_expiries, live_by_key, offline)
        store = OptionCandleStore(client, token, limiter, offline)

        for i, (day_str, strike, opt_type) in enumerate(sorted(needed), 1):
            d = date.fromisoformat(day_str)
            contract = None
            for expiry in resolver.expiries_for(d):
                contract = await resolver.resolve(expiry, strike, opt_type)
                if contract:
                    break
            if not contract:
                missing.append(f"{day_str} {strike:.0f}{opt_type}")
                print(f"  [{i}/{len(needed)}] {day_str} {strike:.0f}{opt_type}: no contract")
                continue
            candles = await store.get(contract, d)
            option_prices[(day_str, strike, opt_type)] = {
                "symbol": contract["trading_symbol"], "candles": candles}
            if i % 50 == 0 or i == len(needed):
                print(f"  [{i}/{len(needed)}] {day_str} {contract['trading_symbol']}: "
                      f"{len(candles)} candles")
                resolver.save()
                store.save()
        resolver.save()
        store.save()

    # ---- pass 3: per-t base rows, then per-R:R exits on top of them ----
    base_rows: dict[str, list[dict]] = {}
    trades: dict[str, dict[str, dict[str, dict]]] = {t: {} for t in T_VALUES}
    summaries: dict[str, dict[str, dict]] = {t: {} for t in T_VALUES}

    for t in T_VALUES:
        rows = []
        for day_str in trading_days:
            s = signals[t][day_str]
            d = date.fromisoformat(day_str)
            row = {
                "date": day_str, "week": week_key(d), "month": month_key(d),
                "met": bool(s.get("met")), "reason": s.get("reason", ""),
                "or_high": s.get("or_high"), "or_low": s.get("or_low"),
                "nifty_t": s.get("nifty_t"),
            }
            if s.get("met"):
                key = (day_str, s["atm"], s["option_type"])
                info = option_prices.get(key, {})
                row.update({
                    "side": s["side"], "option_type": s["option_type"],
                    "strike": s["atm"], "symbol": info.get("symbol", ""),
                    "entry_time": t, "entry_px": info.get("candles", {}).get(t),
                })
            rows.append(row)
        base_rows[t] = rows

        for r in rr_ratios:
            label = rr_label(r)
            target_pct = stop_pct * r / 100
            stop_frac = stop_pct / 100
            per_day: dict[str, dict] = {}
            merged: list[dict] = []          # for the summaries only
            for row in rows:
                out = {"traded": False}
                if row["met"]:
                    s = signals[t][row["date"]]
                    ex = simulate_exit(by_day[row["date"]], t, s["side"], s["nifty_t"],
                                       target_pct, stop_frac)
                    candles = option_prices.get(
                        (row["date"], s["atm"], s["option_type"]), {}).get("candles", {})
                    exit_px = candles.get(ex["exit_time"]) if ex["exit_time"] else None
                    out.update({
                        "exit_time": ex["exit_time"], "close_type": ex["close_type"],
                        "target": ex["target"], "stop": ex["stop"],
                        "nifty_exit": ex["exit_spot"], "exit_px": exit_px,
                    })
                    if row["entry_px"] is not None and exit_px is not None \
                            and ex["exit_spot"] is not None:
                        npts = (ex["exit_spot"] - s["nifty_t"]) if s["side"] == "BULLISH" \
                            else (s["nifty_t"] - ex["exit_spot"])
                        out.update({
                            "traded": True, "pnl": exit_px - row["entry_px"],
                            "pnl_rs": (exit_px - row["entry_px"]) * LOT_SIZE,
                            "nifty_pts": npts,
                        })
                    else:
                        out["close_type"] = "NO OPT DATA"
                    per_day[row["date"]] = out
                merged.append({**row, **out})
            trades[t][label] = per_day
            summaries[t][label] = {
                "overall": summarise(merged),
                "daily": [{"key": m["date"], **summarise([m])} for m in merged if m["traded"]],
                "weekly": _grouped(merged, "week"),
                "monthly": _grouped(merged, "month"),
            }

    # ---- pass 4: chart candles for every day that traded anywhere ----
    chart_days = sorted({
        d for t in T_VALUES for lbl in trades[t] for d, o in trades[t][lbl].items()
        if o.get("traded")
    })
    days_payload: dict[str, list] = {}
    idx_maps: dict[str, dict[str, int]] = {}
    for day_str in chart_days:
        day_map = by_day[day_str]
        arr, idx_of = [], {}
        for k in [x for x in sorted(day_map) if OPEN_TIME <= x <= DAY_END]:
            c = day_map[k]
            idx_of[k] = len(arr)
            arr.append([k, round(c["open"], 2), round(c["high"], 2),
                        round(c["low"], 2), round(c["close"], 2)])
        days_payload[day_str] = arr
        idx_maps[day_str] = idx_of

    for t in T_VALUES:
        for row in base_rows[t]:
            if row["date"] in idx_maps and row.get("entry_time"):
                row["ei"] = idx_maps[row["date"]].get(row["entry_time"])
        for lbl in trades[t]:
            for day_str, o in trades[t][lbl].items():
                if o.get("traded") and day_str in idx_maps:
                    o["xi"] = idx_maps[day_str].get(o["exit_time"])

    rr_labels = [rr_label(r) for r in rr_ratios]
    payload = {
        "meta": {
            "from": from_date.isoformat(), "to": to_date.isoformat(),
            "trend_mode": trend_mode, "lot": LOT_SIZE, "stop_pct": stop_pct,
            "square_off": SQUARE_OFF, "t_values": T_VALUES, "default_t": DEFAULT_T,
            "rr_values": rr_labels,
            "rr_targets": {rr_label(r): round(stop_pct * r, 3) for r in rr_ratios},
            "default_rr": (PREFERRED_RR_LABEL if PREFERRED_RR_LABEL in rr_labels
                           else rr_labels[0]),
            "total_days": len(trading_days),
            "rule": rule_html, "variant": variant,
        },
        "signals": base_rows,
        "trades": trades,
        "days": days_payload,
        "summaries": summaries,
    }

    write_report(payload, out_path)
    print(f"\nReport written to {out_path}\n")

    # ---- data-completeness report: every signal must have a price ----
    nodata = sorted({
        d for t in T_VALUES for lbl in trades[t] for d, o in trades[t][lbl].items()
        if o.get("close_type") == "NO OPT DATA"
    })
    if missing:
        print(f"! {len(missing)} signal(s) had no resolvable contract: "
              + ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else ""))
    if nodata:
        print(f"! {len(nodata)} signal day(s) had no option price data: "
              + ", ".join(nodata[:10]) + (" ..." if len(nodata) > 10 else ""))
    if not missing and not nodata:
        print("All signals priced - no missing option data.")
    print()

    hdr = "  t     " + "".join(f"{lbl:>13}" for lbl in rr_labels)
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for t in T_VALUES:
        cells = "".join(
            f"{summaries[t][lbl]['overall']['pnl_rs']:>+13,.0f}" for lbl in rr_labels)
        print(f"  {t:<6}{cells}")


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NIFTY Reversal — Risk:Reward Sweep __FROM__ to __TO__</title>
<style>
  :root {
    color-scheme: light;
    --surface:#fcfcfb; --page:#f4f4f1; --ink:#0b0b0b; --ink2:#52514e; --muted:#8b8983;
    --grid:#e3e2db; --border:rgba(11,11,11,.10);
    --up:#128a5a; --down:#d0453f; --accent:#2a78d6; --warn:#b8860b;
    --chip:#eceae3; --chip-on:#0b0b0b; --chip-on-ink:#fff;
    --upN:18,138,90; --downN:208,69,63;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --border:rgba(255,255,255,.10);
      --up:#3ecf8e; --down:#e66767; --accent:#5b9df0; --warn:#e0b341;
      --chip:#262624; --chip-on:#fff; --chip-on-ink:#0d0d0d;
      --upN:62,207,142; --downN:230,103,103;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --border:rgba(255,255,255,.10);
    --up:#3ecf8e; --down:#e66767; --accent:#5b9df0; --warn:#e0b341;
    --chip:#262624; --chip-on:#fff; --chip-on-ink:#0d0d0d;
    --upN:62,207,142; --downN:230,103,103;
  }
  * { box-sizing:border-box; }
  body { background:var(--page); color:var(--ink); margin:0; padding:22px;
         font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }
  h1 { font-size:20px; margin:0 0 4px; }
  h2 { font-size:14px; margin:0 0 10px; }
  .sub { color:var(--ink2); font-size:12.5px; margin-bottom:16px; line-height:1.6; }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:10px;
          padding:14px 16px; margin-bottom:16px; }
  .tabrow { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:8px; }
  .tabrow .cap { font-size:10.5px; text-transform:uppercase; letter-spacing:.05em;
                 color:var(--muted); width:104px; flex-shrink:0; }
  .tab { padding:6px 14px; border-radius:999px; border:1px solid var(--border);
         background:var(--chip); color:var(--ink2); font-size:13px; cursor:pointer;
         font-variant-numeric:tabular-nums; }
  .tab.on { background:var(--chip-on); color:var(--chip-on-ink); border-color:transparent; font-weight:600; }
  .tab small { opacity:.62; margin-left:5px; font-size:11px; }
  .stat-row { display:flex; gap:22px; flex-wrap:wrap; }
  .stat { min-width:108px; }
  .stat .v { font-size:21px; font-weight:600; font-variant-numeric:tabular-nums; }
  .stat .l { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
  table { border-collapse:collapse; width:100%; font-size:12.5px; }
  th { text-align:left; color:var(--muted); font-weight:500; font-size:10.5px;
       text-transform:uppercase; letter-spacing:.04em; padding:6px 8px;
       border-bottom:1px solid var(--grid); position:sticky; top:0; background:var(--surface); }
  td { padding:5px 8px; border-bottom:1px solid var(--grid); white-space:nowrap;
       font-variant-numeric:tabular-nums; }
  tbody tr:hover { background:rgba(127,127,127,.07); }
  .num { text-align:right; }
  .pos { color:var(--up); font-weight:600; }
  .neg { color:var(--down); font-weight:600; }
  .dim { color:var(--muted); }
  .pill { display:inline-block; padding:1px 7px; border-radius:5px; font-size:11px; font-weight:600; }
  .pill.ce { background:rgba(var(--upN),.16); color:var(--up); }
  .pill.pe { background:rgba(var(--downN),.16); color:var(--down); }
  .pill.tgt { background:rgba(var(--upN),.16); color:var(--up); }
  .pill.sl { background:rgba(var(--downN),.16); color:var(--down); }
  .pill.eod { background:rgba(127,127,127,.18); color:var(--ink2); }
  .pill.no { background:rgba(184,134,11,.18); color:var(--warn); }
  .scroll { overflow:auto; max-height:520px; }
  .scroll.short { max-height:340px; }
  .ctrl { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:10px;
          font-size:12.5px; color:var(--ink2); }
  select { background:var(--surface); color:var(--ink); border:1px solid var(--border);
           border-radius:6px; padding:5px 8px; font-size:12.5px; }
  .chart-wrap { position:relative; }
  svg { width:100%; height:auto; display:block; }
  .legend { display:flex; gap:16px; flex-wrap:wrap; font-size:11.5px; color:var(--ink2); margin-top:8px; }
  .legend i { display:inline-block; width:14px; height:3px; vertical-align:middle; margin-right:5px; border-radius:2px; }
  #tip { position:absolute; pointer-events:none; background:var(--surface); border:1px solid var(--border);
         border-radius:7px; padding:7px 9px; font-size:11.5px; line-height:1.5; display:none;
         box-shadow:0 6px 20px rgba(0,0,0,.18); font-variant-numeric:tabular-nums; z-index:5; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media (max-width:900px) { .grid2 { grid-template-columns:1fr; } }
  table.matrix td, table.matrix th { text-align:right; }
  table.matrix td.rh, table.matrix th.rh { text-align:left; font-weight:600; }
  table.matrix td { cursor:pointer; border-radius:4px; }
  table.matrix td.sel { outline:2px solid var(--accent); outline-offset:-2px; }
  table.matrix .wr { font-size:10.5px; opacity:.62; display:block; }
</style>
</head>
<body>

<h1>NIFTY Opening-Range Reversal — risk:reward sweep__VARIANT__</h1>
<div class="sub">
  __RULE__<br>
  Stop-loss fixed at <b>__STP__%</b> of NIFTY spot; target = stop &times; R. Squared off at __SQO__ if still open.
  Stop is assumed hit first when one candle spans both levels. Option prices are 1-minute closes;
  PnL is in option points and in &#8377; for 1 lot (__LOT__).<br>
  Range __FROM__ &rarr; __TO__ &middot; __NDAYS__ trading days.
</div>

<div class="card">
  <div class="tabrow"><span class="cap">Decision time t</span><span id="tabsT" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow" style="margin-bottom:0"><span class="cap">Risk : Reward</span><span id="tabsR" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
</div>

<div class="card">
  <h2>Net PnL matrix — &#8377; per lot, all 48 combinations</h2>
  <div class="ctrl dim">Rows = decision time, columns = risk:reward. Click any cell to jump to it. Small number = win rate.</div>
  <div class="scroll"><table class="matrix" id="matrix"></table></div>
</div>

<div class="card">
  <h2>Overall — t = <span id="ovT"></span>, R:R = <span id="ovR"></span> (target <span id="ovTgt"></span>%)</h2>
  <div class="stat-row" id="overall"></div>
</div>

<div class="card">
  <h2>NIFTY 1-minute chart with entry / exit</h2>
  <div class="ctrl">
    <label for="daySel">Trade day</label>
    <select id="daySel"></select>
    <span id="dayInfo" class="dim"></span>
  </div>
  <div class="chart-wrap"><svg id="chart" viewBox="0 0 1200 430"></svg><div id="tip"></div></div>
  <div class="legend">
    <span><i style="background:var(--muted)"></i>Opening-range high / low</span>
    <span><i style="background:var(--up)"></i>Target</span>
    <span><i style="background:var(--down)"></i>Stop-loss</span>
    <span><i style="background:var(--accent)"></i>Entry</span>
    <span>&#9670; Exit</span>
  </div>
</div>

<div class="card">
  <h2>Day-by-day</h2>
  <div class="ctrl">
    <label><input type="checkbox" id="onlyTrades" checked> show only days where the condition was met</label>
  </div>
  <div class="scroll"><table id="tblDays"></table></div>
</div>

<div class="card">
  <h2>Daily summary</h2>
  <div class="scroll short"><table id="tblDaily"></table></div>
</div>

<div class="grid2">
  <div class="card">
    <h2>Weekly summary</h2>
    <div class="scroll short"><table id="tblWeekly"></table></div>
  </div>
  <div class="card">
    <h2>Monthly summary</h2>
    <div class="scroll short"><table id="tblMonthly"></table></div>
  </div>
</div>

<script>
const DATA = __DATA_JSON__;
const M = DATA.meta;
let curT = M.default_t, curR = M.default_rr;

const n2 = v => (v===null||v===undefined||isNaN(v)) ? '&ndash;' : Number(v).toFixed(2);
const n0 = v => (v===null||v===undefined||isNaN(v)) ? '&ndash;' : Math.round(v).toLocaleString('en-IN');
const sgn = (v,d=2) => (v===null||v===undefined||isNaN(v)) ? '&ndash;'
      : `<span class="${v>0?'pos':(v<0?'neg':'dim')}">${v>0?'+':''}${Number(v).toFixed(d)}</span>`;
const sgnRs = v => (v===null||v===undefined||isNaN(v)) ? '&ndash;'
      : `<span class="${v>0?'pos':(v<0?'neg':'dim')}">${v>0?'+':''}${Math.round(v).toLocaleString('en-IN')}</span>`;

/* merge the per-t signal row with the per-R:R exit for that day */
function rowsFor(t, r) {
  const tr = DATA.trades[t][r];
  return DATA.signals[t].map(b => Object.assign({}, b, tr[b.date] || {}));
}

/* ---------- tabs ---------- */
function buildTabs(el, values, get, set, sub) {
  el.innerHTML = '';
  values.forEach(v => {
    const b = document.createElement('button');
    b.className = 'tab' + (v === get() ? ' on' : '');
    b.innerHTML = v + (sub ? `<small>${sub(v)}</small>` : '');
    b.onclick = () => { set(v); [...el.children].forEach(c => c.classList.remove('on'));
                        b.classList.add('on'); renderAll(); };
    el.appendChild(b);
  });
}
buildTabs(document.getElementById('tabsT'), M.t_values, () => curT, v => curT = v, null);
buildTabs(document.getElementById('tabsR'), M.rr_values, () => curR, v => curR = v,
          v => `${M.rr_targets[v]}%`);

function syncTabs() {
  [...document.getElementById('tabsT').children].forEach(
    c => c.classList.toggle('on', c.textContent.trim() === curT));
  [...document.getElementById('tabsR').children].forEach(
    c => c.classList.toggle('on', c.firstChild.textContent.trim() === curR));
}

/* ---------- matrix ---------- */
function renderMatrix() {
  let max = 1;
  M.t_values.forEach(t => M.rr_values.forEach(r =>
    max = Math.max(max, Math.abs(DATA.summaries[t][r].overall.pnl_rs))));
  let h = `<thead><tr><th class="rh">t \\ R:R</th>` +
    M.rr_values.map(r => `<th>${r}<br><span class="dim" style="font-weight:400">${M.rr_targets[r]}%</span></th>`).join('') +
    `</tr></thead><tbody>`;
  M.t_values.forEach(t => {
    h += `<tr><td class="rh">${t}</td>`;
    M.rr_values.forEach(r => {
      const s = DATA.summaries[t][r].overall;
      const a = (Math.abs(s.pnl_rs) / max * 0.5).toFixed(3);
      const bg = s.pnl_rs >= 0 ? `rgba(var(--upN),${a})` : `rgba(var(--downN),${a})`;
      const sel = (t === curT && r === curR) ? ' sel' : '';
      h += `<td class="${sel}" style="background:${bg}" data-t="${t}" data-r="${r}">` +
           `${sgnRs(s.pnl_rs)}<span class="wr">${s.win_rate.toFixed(0)}% · ${s.trades}t</span></td>`;
    });
    h += `</tr>`;
  });
  const el = document.getElementById('matrix');
  el.innerHTML = h + `</tbody>`;
  el.querySelectorAll('td[data-t]').forEach(td => {
    td.onclick = () => { curT = td.dataset.t; curR = td.dataset.r; syncTabs(); renderAll(); };
  });
}

/* ---------- summaries ---------- */
function statBlock(s) {
  return [
    [s.days, 'trade days'], [s.trades, 'total trades'],
    [s.wins, 'success'], [s.losses, 'fail'],
    [s.win_rate.toFixed(1)+'%', 'win rate'],
    [(s.pnl_pts>0?'+':'')+s.pnl_pts.toFixed(2), 'net PnL (opt pts)'],
    [(s.pnl_rs>0?'+':'')+Math.round(s.pnl_rs).toLocaleString('en-IN'), 'net PnL (1 lot ₹)'],
    [(s.nifty_pts>0?'+':'')+s.nifty_pts.toFixed(1), 'NIFTY pts'],
  ].map(([v,l]) => `<div class="stat"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
}

function summaryTable(el, rows, label) {
  const head = `<thead><tr><th>${label}</th><th class="num">Trade days</th><th class="num">Trades</th>
    <th class="num">Success</th><th class="num">Fail</th><th class="num">Win %</th>
    <th class="num">Net PnL (pts)</th><th class="num">Net PnL (₹)</th><th class="num">NIFTY pts</th></tr></thead>`;
  const body = rows.map(r => `<tr><td>${r.key}</td><td class="num">${r.days}</td>
    <td class="num">${r.trades}</td><td class="num pos">${r.wins}</td><td class="num neg">${r.losses}</td>
    <td class="num">${r.win_rate.toFixed(1)}%</td><td class="num">${sgn(r.pnl_pts)}</td>
    <td class="num">${sgnRs(r.pnl_rs)}</td><td class="num">${sgn(r.nifty_pts,1)}</td></tr>`).join('');
  el.innerHTML = head + `<tbody>${body || '<tr><td colspan="9" class="dim">no trades</td></tr>'}</tbody>`;
}

/* ---------- day table ---------- */
function closePill(ct) {
  if (ct === 'TARGET') return '<span class="pill tgt">TARGET</span>';
  if (ct === 'STOPLOSS') return '<span class="pill sl">STOPLOSS</span>';
  if (ct === '3PM') return '<span class="pill eod">3 PM</span>';
  return `<span class="pill no">${ct || '&ndash;'}</span>`;
}

function renderDays() {
  const only = document.getElementById('onlyTrades').checked;
  const rows = rowsFor(curT, curR).filter(r => !only || r.met);
  const head = `<thead><tr><th>Date</th><th>Met</th><th>Trade</th><th>Strike</th><th>Symbol</th>
    <th class="num">Opt entry</th><th class="num">Opt exit</th><th>Close type</th>
    <th class="num">PnL (pts)</th><th class="num">PnL (₹)</th>
    <th class="num">NIFTY @ t</th><th class="num">Target</th><th class="num">Stop</th>
    <th class="num">NIFTY @ exit</th><th class="num">NIFTY pts</th>
    <th>Exit time</th><th>Note</th></tr></thead>`;
  const body = rows.map(r => {
    if (!r.met) {
      return `<tr><td>${r.date}</td><td class="dim">no</td>
        <td colspan="14" class="dim">&mdash;</td><td class="dim">${r.reason}</td></tr>`;
    }
    const side = r.option_type === 'CE'
      ? '<span class="pill ce">BUY CE</span>' : '<span class="pill pe">BUY PE</span>';
    if (!r.traded) {
      return `<tr><td>${r.date}</td><td class="pos">yes</td><td>${side}</td>
        <td class="num">${n0(r.strike)}</td><td class="dim">${r.symbol||''}</td>
        <td colspan="11" class="dim">&mdash;</td>
        <td class="dim">${r.close_type === 'NO OPT DATA' ? 'option price data unavailable' : r.reason}</td></tr>`;
    }
    return `<tr><td>${r.date}</td><td class="pos">yes</td><td>${side}</td>
      <td class="num">${n0(r.strike)}</td><td class="dim">${r.symbol}</td>
      <td class="num">${n2(r.entry_px)}</td><td class="num">${n2(r.exit_px)}</td>
      <td>${closePill(r.close_type)}</td>
      <td class="num">${sgn(r.pnl)}</td><td class="num">${sgnRs(r.pnl_rs)}</td>
      <td class="num">${n2(r.nifty_t)}</td><td class="num dim">${n2(r.target)}</td>
      <td class="num dim">${n2(r.stop)}</td>
      <td class="num">${n2(r.nifty_exit)}</td><td class="num">${sgn(r.nifty_pts,1)}</td>
      <td>${r.exit_time||''}</td><td class="dim">${r.reason}</td></tr>`;
  }).join('');
  document.getElementById('tblDays').innerHTML =
    head + `<tbody>${body || '<tr><td class="dim">no rows</td></tr>'}</tbody>`;
}

/* ---------- chart ---------- */
const W = 1200, H = 430, PADL = 8, PADR = 62, PADT = 14, PADB = 26;
const svg = document.getElementById('chart');
const tip = document.getElementById('tip');
let chartState = null;

function renderChart() {
  const sel = document.getElementById('daySel');
  const day = sel.value;
  const info = document.getElementById('dayInfo');
  if (!day || !DATA.days[day]) {
    svg.innerHTML = `<text x="20" y="40" fill="currentColor" font-size="13" opacity=".6">No trade days for t = ${curT}, R:R = ${curR}</text>`;
    info.textContent = ''; chartState = null; return;
  }
  const c = DATA.days[day];
  const r = rowsFor(curT, curR).find(x => x.date === day && x.traded);
  const lvls = r ? [r.or_high, r.or_low, r.target, r.stop].filter(v => v != null) : [];
  let lo = Math.min(...c.map(x=>x[3]).concat(lvls));
  let hi = Math.max(...c.map(x=>x[2]).concat(lvls));
  const pad = (hi - lo) * 0.06 || 10; lo -= pad; hi += pad;

  const iw = W - PADL - PADR, ih = H - PADT - PADB;
  const x = i => PADL + (i + 0.5) * iw / c.length;
  const y = v => PADT + (hi - v) * ih / (hi - lo);
  const bw = Math.max(1.2, iw / c.length * 0.62);

  let s = '';
  for (let k = 0; k <= 6; k++) {
    const v = lo + (hi - lo) * k / 6, yy = y(v);
    s += `<line x1="${PADL}" y1="${yy}" x2="${PADL+iw}" y2="${yy}" stroke="var(--grid)" stroke-width="1"/>`;
    s += `<text x="${PADL+iw+6}" y="${yy+3.5}" font-size="10" fill="var(--muted)">${v.toFixed(0)}</text>`;
  }
  for (let i = 0; i < c.length; i += 30) {
    s += `<text x="${x(i)}" y="${H-8}" font-size="10" fill="var(--muted)" text-anchor="middle">${c[i][0]}</text>`;
    s += `<line x1="${x(i)}" y1="${PADT}" x2="${x(i)}" y2="${PADT+ih}" stroke="var(--grid)" stroke-width="1" opacity=".55"/>`;
  }
  for (let i = 0; i < c.length; i++) {
    const [tm,o,h,l,cl] = c[i];
    const col = cl >= o ? 'var(--up)' : 'var(--down)';
    const yo = y(o), yc = y(cl);
    s += `<line x1="${x(i).toFixed(2)}" y1="${y(h).toFixed(2)}" x2="${x(i).toFixed(2)}" y2="${y(l).toFixed(2)}" stroke="${col}" stroke-width="1"/>`;
    s += `<rect x="${(x(i)-bw/2).toFixed(2)}" y="${Math.min(yo,yc).toFixed(2)}" width="${bw.toFixed(2)}" height="${Math.max(1, Math.abs(yc-yo)).toFixed(2)}" fill="${col}"/>`;
  }
  const hline = (v, col, dash, label) => v == null ? '' :
    `<line x1="${PADL}" y1="${y(v)}" x2="${PADL+iw}" y2="${y(v)}" stroke="${col}" stroke-width="1.4" stroke-dasharray="${dash}" opacity=".9"/>`
    + `<text x="${PADL+4}" y="${y(v)-4}" font-size="10" fill="${col}">${label} ${v.toFixed(2)}</text>`;
  if (r) {
    s += hline(r.or_high, 'var(--muted)', '4 3', 'OR high');
    s += hline(r.or_low,  'var(--muted)', '4 3', 'OR low');
    s += hline(r.target,  'var(--up)',    '6 3', 'Target');
    s += hline(r.stop,    'var(--down)',  '6 3', 'Stop');
    if (r.ei != null) {
      const ex = x(r.ei), ey = y(r.nifty_t);
      s += `<line x1="${ex}" y1="${PADT}" x2="${ex}" y2="${PADT+ih}" stroke="var(--accent)" stroke-width="1.2" stroke-dasharray="3 3"/>`;
      const up = r.side === 'BULLISH';
      const ty = up ? ey + 12 : ey - 12, dir = up ? 1 : -1;
      s += `<polygon points="${ex},${ey} ${ex-6},${ty} ${ex+6},${ty}" fill="var(--accent)"/>`;
      s += `<text x="${ex+9}" y="${ey + dir*16}" font-size="11" font-weight="600" fill="var(--accent)">${up?'BUY CE':'BUY PE'} @ ${r.nifty_t.toFixed(2)}</text>`;
    }
    if (r.xi != null && r.nifty_exit != null) {
      const xx = x(r.xi), xy = y(r.nifty_exit);
      const col = r.pnl > 0 ? 'var(--up)' : 'var(--down)';
      s += `<polygon points="${xx},${xy-7} ${xx+7},${xy} ${xx},${xy+7} ${xx-7},${xy}" fill="${col}" stroke="var(--surface)" stroke-width="1.2"/>`;
      s += `<text x="${xx+11}" y="${xy+4}" font-size="11" font-weight="600" fill="${col}">${r.close_type} @ ${r.nifty_exit.toFixed(2)}</text>`;
    }
  }
  s += `<rect x="${PADL}" y="${PADT}" width="${iw}" height="${ih}" fill="transparent"/>`;
  svg.innerHTML = s;
  chartState = { c, iw };

  info.innerHTML = r
    ? `${r.symbol} &middot; entry ${r.entry_time} @ ${n2(r.entry_px)} &rarr; exit ${r.exit_time} @ ${n2(r.exit_px)}` +
      ` &middot; PnL ${sgn(r.pnl)} pts (${sgnRs(r.pnl_rs)})`
    : '';
}

svg.addEventListener('mousemove', e => {
  if (!chartState) return;
  const box = svg.getBoundingClientRect();
  const px = (e.clientX - box.left) / box.width * W;
  const { c, iw } = chartState;
  const i = Math.round((px - PADL) / iw * c.length - 0.5);
  if (i < 0 || i >= c.length) { tip.style.display = 'none'; return; }
  const [tm,o,h,l,cl] = c[i];
  tip.innerHTML = `<b>${tm}</b><br>O ${o.toFixed(2)}<br>H ${h.toFixed(2)}<br>L ${l.toFixed(2)}<br>C ${cl.toFixed(2)}`;
  tip.style.display = 'block';
  tip.style.left = Math.min(e.clientX - box.left + 14, box.width - 110) + 'px';
  tip.style.top = Math.max(0, e.clientY - box.top - 60) + 'px';
});
svg.addEventListener('mouseleave', () => { tip.style.display = 'none'; });

/* ---------- orchestration ---------- */
function renderAll() {
  const sm = DATA.summaries[curT][curR];
  document.getElementById('ovT').textContent = curT;
  document.getElementById('ovR').textContent = curR;
  document.getElementById('ovTgt').textContent = M.rr_targets[curR];
  document.getElementById('overall').innerHTML = statBlock(sm.overall);
  renderMatrix();

  const sel = document.getElementById('daySel');
  const prev = sel.value;
  const days = rowsFor(curT, curR).filter(r => r.traded).map(r => r.date);
  sel.innerHTML = days.map(d => `<option value="${d}">${d}</option>`).join('');
  if (days.includes(prev)) sel.value = prev;
  renderChart();

  renderDays();
  summaryTable(document.getElementById('tblDaily'), sm.daily, 'Date');
  summaryTable(document.getElementById('tblWeekly'), sm.weekly, 'Week');
  summaryTable(document.getElementById('tblMonthly'), sm.monthly, 'Month');
}

document.getElementById('daySel').addEventListener('change', renderChart);
document.getElementById('onlyTrades').addEventListener('change', renderDays);
renderAll();
</script>
</body>
</html>
"""


def write_report(payload: dict, out_path: str) -> None:
    m = payload["meta"]
    html = (
        HTML_TEMPLATE
        .replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":")))
        .replace("__RULE__", m.get("rule", ""))
        .replace("__VARIANT__", m.get("variant", ""))
        .replace("__FROM__", m["from"])
        .replace("__TO__", m["to"])
        .replace("__TREND__", m["trend_mode"])
        .replace("__STP__", f"{m['stop_pct']:g}")
        .replace("__SQO__", m["square_off"])
        .replace("__LOT__", str(m["lot"]))
        .replace("__NDAYS__", str(m["total_days"]))
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

RULE_HTML = (
    "<b>v2 &mdash; relaxed rule.</b> Opening range = first 5-min candle "
    "(09:15&ndash;09:20). <b>2A</b> &mdash; every candle 09:20&rarr;<b>t</b> stayed "
    "<b>below OR high</b> + down-trend &rarr; <b>BUY ATM CE</b>. <b>2B</b> &mdash; every "
    "candle stayed <b>above OR low</b> + up-trend &rarr; <b>BUY ATM PE</b>. Where NIFTY "
    "sits at <b>t</b> does not matter. No confirmation filters. "
    "Trend mode: <b>__TREND__</b>; nearest expiry; stop <b>__STOPPCT__%</b> of spot."
)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    ap.add_argument("--trend", choices=["loose", "moderate", "strict"], default="moderate")
    ap.add_argument("--side", choices=["both", "ce", "pe"], default="both",
                    help="trade only one leg; the other is dropped at detection time "
                         "so every number in the report is genuinely one-sided")
    ap.add_argument("--rr", type=float, nargs="+", default=DEFAULT_RR, metavar="R",
                    help="risk:reward ladder, e.g. --rr 2 3 5 8 10")
    ap.add_argument("--stop", type=float, default=STOP_PCT, metavar="PCT",
                    help=f"base stop as percent of NIFTY spot (default {STOP_PCT})")
    ap.add_argument("--offline", action="store_true",
                    help="use only the local caches, make no Upstox calls")
    ap.add_argument("--out", default=REPORT_HTML)
    ap.add_argument("--from", dest="from_date", type=date.fromisoformat, default=RANGE_FROM,
                    help="start date, YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat, default=RANGE_TO,
                    help="end date, YYYY-MM-DD")
    args = ap.parse_args()

    tag = ["v2"]
    if args.side != "both":
        tag.append(f"{args.side.upper()} only")

    os.makedirs(REPORTS_DIR, exist_ok=True)
    asyncio.run(run(
        args.trend, args.offline, args.out,
        detect_fn=make_detector("v2", side=args.side),
        rule_html=RULE_HTML.replace("__STOPPCT__", f"{args.stop:g}"),
        variant=" &middot; " + " &middot; ".join(tag),
        from_date=args.from_date, to_date=args.to_date,
        rr_ratios=args.rr, stop_pct=args.stop))


if __name__ == "__main__":
    main()
