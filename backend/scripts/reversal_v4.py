"""NIFTY opening-range reversal — v4: same entry as v2, a new exit engine.

THE CORE STRATEGY IS UNCHANGED.  detect_signal_v2() below is byte-identical to
v2: opening range = 09:15-09:19, and at the entry minute `t`

    2A. every candle 09:20 -> t stayed BELOW OR high + down-trend -> BUY ATM CE
    2B. every candle 09:20 -> t stayed ABOVE OR low  + up-trend   -> BUY ATM PE

v4 takes EVERY v2 signal.  There is no confirmation filter, no extra entry
condition, no dropped day.  That is the difference from v3, which raised the win
rate by throwing away 80% of the trades.

WHY THE EXIT, NOT THE ENTRY
---------------------------
Research on the 702 v2 signals (Jan-Sep 2026, 8 entry times) showed:

  * No entry-minute indicator, mean-reversion statistic or market-structure
    state separates winners from losers out of sample.  RSI, MACD, ADX,
    Bollinger, stochastic, EMA distance, swing structure, gap state and a
    fitted 2-3 variable score all fail on the second half of the period.
  * The FIXED 0.1% SPOT STOP is what destroys the win rate.  It is touched in
    62 of 89 trades at t=11:30, and 16 of those 62 are profitable by 15:00.
    Win rate rises monotonically with stop width: 0.10% -> 29%, 0.20% -> 33%,
    0.30% -> 37%, 0.40% -> 43%, no stop -> 45%.
  * Winners are slow.  Their best price arrives late in the session, median
    MAE is only 0.09%, and any time-based or break-even exit kills them.
  * To beat the ~45% ceiling of "hold with a wide stop" the target has to be
    capped.  A trailing stop measured on the OPTION PREMIUM does that without
    capping the big winners, because it also adapts to implied volatility.

THE v4 EXIT ENGINE
------------------
Every level below is a command-line switch:

    premium stop   exit if the option's 1-minute close <= 65% of entry premium
    disaster stop  exit if NIFTY spot travels 15 x ATR14(1m) against the trade
                   (median 0.48% of spot - a genuine disaster stop, not a
                   working stop)
    trail          once the premium closes >= 1.15 x entry, track the running
                   maximum premium and exit at the first close <= 90% of it
    expiry day     square off at 13:30 (premium decay makes a held expiry-day
                   position negative at every t)
    otherwise      square off at 15:00

Measured at t=11:30 on 89 trades, 1 lot:  v2 1:5 -> 27.0% win rate, +33,761.
v4 ptrail -> 56.2% win rate, +55,011, max drawdown -13,384, longest losing run
4.  Win rate is 54-61% at all 8 entry times and PnL is positive in all 16
(t x half-period) cells.

The report shows v4 and nothing else - no baseline columns, no alternative
schemes.  The only dimension left is the decision time t, so the summary table
is "the v4 rule at each entry time".

Run from backend/:
    python scripts/reversal_v4.py --offline
    python scripts/reversal_v4.py --offline --trail-act 1.20 --trail-off 0.15
    python scripts/reversal_v4.py --offline --no-expiry-exit --side ce

Output: reversal_v4_report.html (self-contained, no CDN).
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


REPORT_HTML = os.path.join(REPORTS_DIR, "reversal_v4_report.html")

# ---------------------------------------------------------------------------
# v4 exit schemes
# ---------------------------------------------------------------------------
# Each scheme is a set of exit levels applied to the SAME v2 entries, so the
# report compares them on identical trades.  Keys:
#   spot_stop_pct  spot stop as % of entry spot
#   atr_k          spot stop at k x ATR14(1m) instead (overrides spot_stop_pct)
#   spot_tgt_R     spot target at R x the spot stop distance
#   prem_stop      exit when option close <= this fraction of entry premium
#   prem_tgt       exit when option close >= this fraction of entry premium
#   trail_act      arm the premium trail once the close reaches this multiple
#   trail_off      once armed, exit at this fraction below the running maximum
#   or_mid_target  target = opening-range midpoint
EXPIRY_CUTOFF = "13:30"
DEFAULT_SCHEME = "v4"

PREM_STOP = 0.65        # -35% of premium
TRAIL_ACT = 1.15        # arm at +15%
TRAIL_OFF = 0.10        # give back 10% of the running high
ATR_K = 15.0            # disaster stop, in ATR14(1m) units


def build_schemes(prem_stop, trail_act, trail_off, atr_k):
    """The v4 exit, and nothing else.  This report is not a comparison."""
    return [
        {"label": "v4",
         "desc": (f"premium stop -{(1 - prem_stop) * 100:.0f}%, "
                  f"trail {trail_off * 100:.0f}% after +{(trail_act - 1) * 100:.0f}%, "
                  f"{atr_k:g} x ATR14 disaster stop"),
         "prem_stop": prem_stop, "atr_k": atr_k,
         "trail_act": trail_act, "trail_off": trail_off},
    ]


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


def atr14(candles: list[dict], n: int = 14) -> float:
    """Wilder true range, simple mean of the last n bars. 0.0 if too short."""
    if not candles:
        return 0.0
    tr = []
    for i, c in enumerate(candles):
        if i == 0:
            tr.append(c["high"] - c["low"])
        else:
            p = candles[i - 1]["close"]
            tr.append(max(c["high"] - c["low"], abs(c["high"] - p), abs(c["low"] - p)))
    return sum(tr[-n:]) / min(n, len(tr))


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


def make_detector(base: str, side: str = "both"):
    """v4 wraps the v2 rule with nothing but the optional one-sided report.

    There are deliberately NO confirmation filters here.  v4 trades every
    signal the core rule produces; all of the improvement lives in the exit.
    """
    base_fn = BASE_RULES[base]

    def detect(day_map: dict[str, dict], t: str, trend_mode: str) -> dict:
        sig = base_fn(day_map, t, trend_mode)
        if not sig.get("met"):
            return sig
        if side != "both" and sig["option_type"] != side.upper():
            other = "above OR high + up-trend" if side == "ce" else "below OR low + down-trend"
            return {**_keep(sig), "met": False,
                    "reason": f"{sig['option_type']} side ({other}) - excluded, "
                              f"{side.upper()}-only report"}
        return sig

    return detect


# ---------------------------------------------------------------------------
# Trade simulation on NIFTY spot
# ---------------------------------------------------------------------------

def simulate_exit_v4(day_map: dict[str, dict], opt: dict[str, float], t: str,
                     side: str, entry_spot: float, entry_px: float | None,
                     scheme: dict, atr: float, or_mid: float,
                     cutoff: str) -> dict:
    """Walk 1m candles after `t` and apply the scheme's exit levels.

    Both the NIFTY candles and the option's 1-minute closes are walked together,
    so premium-based levels are evaluated on the same minute as spot levels.
    Priority inside one minute: spot stop, premium stop, premium target, spot
    target, premium trail.  The stop is therefore assumed hit first whenever a
    single candle spans both, exactly as v2 assumed.
    """
    d = 1 if side == "BULLISH" else -1

    stop = None
    if scheme.get("atr_k") is not None and atr > 0:
        stop = entry_spot - d * scheme["atr_k"] * atr
    elif scheme.get("spot_stop_pct") is not None:
        stop = entry_spot * (1 - d * scheme["spot_stop_pct"] / 100)

    target = None
    if scheme.get("spot_tgt_R") is not None and stop is not None:
        target = entry_spot + d * abs(entry_spot - stop) * scheme["spot_tgt_R"]
    if scheme.get("or_mid_target"):
        target = or_mid if (or_mid - entry_spot) * d > 0 else None

    base = {"target": target, "stop": stop}
    times = [k for k in sorted(day_map) if t < k <= cutoff]
    if not times:
        return {**base, "exit_time": None, "exit_spot": None,
                "exit_px": None, "close_type": "NO DATA"}

    prem_stop = scheme.get("prem_stop")
    prem_tgt = scheme.get("prem_tgt")
    trail_act = scheme.get("trail_act")
    trail_off = scheme.get("trail_off")

    px_last = entry_px
    running_max = entry_px or 0.0
    armed = False

    def done(hhmm, spot, px, ct):
        return {**base, "exit_time": hhmm, "exit_spot": spot,
                "exit_px": px, "close_type": ct}

    for hhmm in times:
        c = day_map[hhmm]
        px = opt.get(hhmm)
        if px is not None:
            px_last = px
        adverse = c["low"] if d > 0 else c["high"]
        favour = c["high"] if d > 0 else c["low"]

        if stop is not None and (adverse - stop) * d <= 0:
            return done(hhmm, stop, opt.get(hhmm, px_last), "SPOT SL")
        if prem_stop is not None and entry_px and px_last <= entry_px * prem_stop:
            return done(hhmm, c["close"], px_last, "PREM SL")
        if prem_tgt is not None and entry_px and px_last >= entry_px * prem_tgt:
            return done(hhmm, c["close"], px_last, "PREM TGT")
        if target is not None and (favour - target) * d >= 0:
            return done(hhmm, target, opt.get(hhmm, px_last), "SPOT TGT")
        if trail_act is not None and entry_px:
            if px_last > running_max:
                running_max = px_last
            if not armed and px_last >= entry_px * trail_act:
                armed = True
            if armed and px_last <= running_max * (1 - trail_off):
                return done(hhmm, c["close"], px_last, "TRAIL")

    last = times[-1]
    ct = "EXPIRY" if cutoff != SQUARE_OFF else "3PM"
    return done(last, day_map[last]["close"], opt.get(last, px_last), ct)


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
              schemes: list[dict], expiry_exit: bool) -> None:
    token = None if offline else _read_access_token()

    nifty = await load_nifty(token, offline, from_date, to_date)
    by_day = index_by_day(nifty)
    trading_days = sorted(
        d for d in by_day if from_date.isoformat() <= d <= to_date.isoformat())
    print(f"{len(trading_days)} trading days in range, trend mode = {trend_mode}")
    print("exit schemes: " + ", ".join(f"{x['label']} ({x['desc']})" for x in schemes))
    if expiry_exit:
        print(f"expiry-day trades squared off at {EXPIRY_CUTOFF}")

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
                    contract = {**contract, "expiry": expiry.isoformat()}
                    break
            if not contract:
                missing.append(f"{day_str} {strike:.0f}{opt_type}")
                print(f"  [{i}/{len(needed)}] {day_str} {strike:.0f}{opt_type}: no contract")
                continue
            candles = await store.get(contract, d)
            option_prices[(day_str, strike, opt_type)] = {
                "symbol": contract["trading_symbol"], "candles": candles,
                "expiry": contract.get("expiry")}
            if i % 50 == 0 or i == len(needed):
                print(f"  [{i}/{len(needed)}] {day_str} {contract['trading_symbol']}: "
                      f"{len(candles)} candles")
                resolver.save()
                store.save()
        resolver.save()
        store.save()

    # ---- pass 3: per-t base rows, then per-scheme exits on top of them ----
    base_rows: dict[str, list[dict]] = {}
    trades: dict[str, dict[str, dict[str, dict]]] = {t: {} for t in T_VALUES}
    summaries: dict[str, dict[str, dict]] = {t: {} for t in T_VALUES}

    # expiry dates are needed only to flag expiry-day trades for the early exit
    expiry_of = {k: v.get("expiry") for k, v in option_prices.items()}

    for t in T_VALUES:
        rows = []
        for day_str in trading_days:
            sig = signals[t][day_str]
            d = date.fromisoformat(day_str)
            row = {
                "date": day_str, "week": week_key(d), "month": month_key(d),
                "met": bool(sig.get("met")), "reason": sig.get("reason", ""),
                "or_high": sig.get("or_high"), "or_low": sig.get("or_low"),
                "nifty_t": sig.get("nifty_t"),
            }
            if sig.get("met"):
                key = (day_str, sig["atm"], sig["option_type"])
                info = option_prices.get(key, {})
                window = [by_day[day_str][k] for k in sorted(by_day[day_str])
                          if OPEN_TIME <= k <= t]
                row.update({
                    "side": sig["side"], "option_type": sig["option_type"],
                    "strike": sig["atm"], "symbol": info.get("symbol", ""),
                    "entry_time": t, "entry_px": info.get("candles", {}).get(t),
                    "atr": atr14(window),
                    "expiry_day": expiry_of.get(key) == day_str,
                })
            rows.append(row)
        base_rows[t] = rows

        for scheme in schemes:
            label = scheme["label"]
            per_day: dict[str, dict] = {}
            merged: list[dict] = []          # for the summaries only
            for row in rows:
                out = {"traded": False}
                if row["met"]:
                    sig = signals[t][row["date"]]
                    key = (row["date"], sig["atm"], sig["option_type"])
                    opt = option_prices.get(key, {}).get("candles", {})
                    cutoff = (EXPIRY_CUTOFF
                              if (expiry_exit and row.get("expiry_day")
                                  and not scheme.get("pure"))
                              else SQUARE_OFF)
                    ex = simulate_exit_v4(
                        by_day[row["date"]], opt, t, sig["side"], sig["nifty_t"],
                        row["entry_px"], scheme, row.get("atr") or 0.0,
                        (row["or_high"] + row["or_low"]) / 2, cutoff)
                    out.update({
                        "exit_time": ex["exit_time"], "close_type": ex["close_type"],
                        "target": ex["target"], "stop": ex["stop"],
                        "nifty_exit": ex["exit_spot"], "exit_px": ex["exit_px"],
                    })
                    if row["entry_px"] is not None and ex["exit_px"] is not None \
                            and ex["exit_spot"] is not None:
                        npts = (ex["exit_spot"] - sig["nifty_t"]) if sig["side"] == "BULLISH" \
                            else (sig["nifty_t"] - ex["exit_spot"])
                        out.update({
                            "traded": True, "pnl": ex["exit_px"] - row["entry_px"],
                            "pnl_rs": (ex["exit_px"] - row["entry_px"]) * LOT_SIZE,
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

    rr_labels = [x["label"] for x in schemes]
    payload = {
        "meta": {
            "from": from_date.isoformat(), "to": to_date.isoformat(),
            "trend_mode": trend_mode, "lot": LOT_SIZE,
            "square_off": SQUARE_OFF, "t_values": T_VALUES, "default_t": DEFAULT_T,
            "rr_values": rr_labels,
            "rr_targets": {x["label"]: x["desc"] for x in schemes},
            "default_rr": (DEFAULT_SCHEME if DEFAULT_SCHEME in rr_labels
                           else rr_labels[0]),
            "total_days": len(trading_days),
            "rule": rule_html, "variant": variant,
            "expiry_note": ("expiry-day trades squared off at " + EXPIRY_CUTOFF
                            if expiry_exit else "no expiry-day exception"),
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

    lbl = rr_labels[0]
    hdr = (f"  {'t':<7}{'trades':>8}{'wins':>7}{'losses':>8}"
           f"{'win rate':>10}{'net PnL (Rs/lot)':>19}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for t in T_VALUES:
        o = summaries[t][lbl]["overall"]
        print(f"  {t:<7}{o['trades']:>8}{o['wins']:>7}{o['losses']:>8}"
              f"{o['win_rate']:>9.1f}%{o['pnl_rs']:>+19,.0f}")


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NIFTY Reversal v4 __FROM__ to __TO__</title>
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

<h1>NIFTY Opening-Range Reversal — v4 exit engine__VARIANT__</h1>
<div class="sub">
  __RULE__<br>
  <b>The entry rule is identical to v2 and every v2 signal is traded.</b>
  Squared off at __SQO__ if still open
  (__EXP__). Stop is assumed hit first when one candle spans both levels. Option prices are
  1-minute closes; PnL is in option points and in &#8377; for 1 lot (__LOT__).<br>
  Range __FROM__ &rarr; __TO__ &middot; __NDAYS__ trading days.
</div>

<div class="card">
  <div class="tabrow"><span class="cap">Decision time t</span><span id="tabsT" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow" style="margin-bottom:0"><span class="cap">Exit rule</span><span id="exitDesc" style="font-size:12.5px;color:var(--ink2)"></span></div>
</div>

<div class="card">
  <h2>v4 by entry time — the same rule at every decision time t</h2>
  <div class="ctrl dim">Rows = decision time, columns = risk:reward. Click any cell to jump to it. Small number = win rate.</div>
  <div class="scroll"><table class="matrix" id="matrix"></table></div>
</div>

<div class="card">
  <h2>Overall — t = <span id="ovT"></span></h2>
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

/* merge the per-t signal row with the per-scheme exit for that day */
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
document.getElementById('exitDesc').textContent = M.rr_targets[curR];

function syncTabs() {
  [...document.getElementById('tabsT').children].forEach(
    c => c.classList.toggle('on', c.textContent.trim() === curT));
}

/* ---------- matrix ---------- */
function renderMatrix() {
  const r = curR;
  let max = 1;
  M.t_values.forEach(t => max = Math.max(max, Math.abs(DATA.summaries[t][r].overall.pnl_rs)));
  let h = '<thead><tr><th class="rh">Entry time t</th><th>Trades</th><th>Wins</th>'
        + '<th>Losses</th><th>Win rate</th><th>Net PnL (&#8377;/lot)</th>'
        + '<th>Net PnL (opt pts)</th><th>NIFTY pts</th></tr></thead><tbody>';
  M.t_values.forEach(t => {
    const s = DATA.summaries[t][r].overall;
    const a = (Math.abs(s.pnl_rs) / max * 0.5).toFixed(3);
    const bg = s.pnl_rs >= 0 ? `rgba(var(--upN),${a})` : `rgba(var(--downN),${a})`;
    const sel = (t === curT) ? ' sel' : '';
    h += `<tr data-t="${t}"><td class="rh${sel}">${t}</td>`
       + `<td>${s.trades}</td><td class="pos">${s.wins}</td><td class="neg">${s.losses}</td>`
       + `<td>${s.win_rate.toFixed(1)}%</td>`
       + `<td class="${sel}" style="background:${bg}">${sgnRs(s.pnl_rs)}</td>`
       + `<td>${sgn(s.pnl_pts)}</td><td>${sgn(s.nifty_pts,1)}</td></tr>`;
  });
  const el = document.getElementById('matrix');
  el.innerHTML = h + '</tbody>';
  el.querySelectorAll('tr[data-t]').forEach(tr => {
    tr.style.cursor = 'pointer';
    tr.onclick = () => { curT = tr.dataset.t; syncTabs(); renderAll(); };
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
  if (ct === 'SPOT TGT' || ct === 'PREM TGT') return `<span class="pill tgt">${ct}</span>`;
  if (ct === 'TRAIL') return '<span class="pill tgt">TRAIL</span>';
  if (ct === 'SPOT SL' || ct === 'PREM SL') return `<span class="pill sl">${ct}</span>`;
  if (ct === '3PM') return '<span class="pill eod">3 PM</span>';
  if (ct === 'EXPIRY') return '<span class="pill eod">EXPIRY 1:30</span>';
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
    svg.innerHTML = `<text x="20" y="40" fill="currentColor" font-size="13" opacity=".6">No trade days for t = ${curT}</text>`;
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
    if (r.target != null) s += hline(r.target, 'var(--up)',   '6 3', 'Target');
    if (r.stop   != null) s += hline(r.stop,   'var(--down)', '6 3', 'Stop');
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
        .replace("__SQO__", m["square_off"])
        .replace("__EXP__", m["expiry_note"])
        .replace("__LOT__", str(m["lot"]))
        .replace("__NDAYS__", str(m["total_days"]))
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

RULE_HTML = (
    "<b>v4 &mdash; v2 entry, new exit.</b> Opening range = first 5-min candle "
    "(09:15&ndash;09:20). <b>2A</b> &mdash; every candle 09:20&rarr;<b>t</b> stayed "
    "<b>below OR high</b> + down-trend &rarr; <b>BUY ATM CE</b>. <b>2B</b> &mdash; every "
    "candle stayed <b>above OR low</b> + up-trend &rarr; <b>BUY ATM PE</b>. Where NIFTY "
    "sits at <b>t</b> does not matter. <b>No confirmation filter &mdash; every v2 signal "
    "is traded.</b> Trend mode: <b>__TREND__</b>; nearest expiry."
)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trend", choices=["loose", "moderate", "strict"], default="moderate")
    ap.add_argument("--side", choices=["both", "ce", "pe"], default="both",
                    help="trade only one leg; the other is dropped at detection time "
                         "so every number in the report is genuinely one-sided")
    g = ap.add_argument_group("v4 exit parameters")
    g.add_argument("--prem-stop", type=float, default=PREM_STOP, metavar="F",
                   help=f"premium stop as a fraction of entry premium "
                        f"(default {PREM_STOP:g} = -35%%)")
    g.add_argument("--trail-act", type=float, default=TRAIL_ACT, metavar="F",
                   help=f"arm the premium trail at this multiple of entry premium "
                        f"(default {TRAIL_ACT:g})")
    g.add_argument("--trail-off", type=float, default=TRAIL_OFF, metavar="F",
                   help=f"once armed, exit this far below the running high "
                        f"(default {TRAIL_OFF:g} = 10%%)")
    g.add_argument("--atr-k", type=float, default=ATR_K, metavar="K",
                   help=f"disaster spot stop at K x ATR14(1m) (default {ATR_K:g})")
    g.add_argument("--no-expiry-exit", dest="expiry_exit", action="store_false",
                   help=f"do not square off expiry-day trades at {EXPIRY_CUTOFF}")
    ap.set_defaults(expiry_exit=True)
    ap.add_argument("--offline", action="store_true",
                    help="use only the local caches, make no Upstox calls")
    ap.add_argument("--out", default=REPORT_HTML)
    ap.add_argument("--from", dest="from_date", type=date.fromisoformat, default=RANGE_FROM,
                    help="start date, YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat, default=RANGE_TO,
                    help="end date, YYYY-MM-DD")
    args = ap.parse_args()

    schemes = build_schemes(args.prem_stop, args.trail_act, args.trail_off, args.atr_k)
    tag = []
    if args.side != "both":
        tag.append(f"{args.side.upper()} only")
    tag.append(f"prem&le;{args.prem_stop:g}")
    tag.append(f"trail {args.trail_act:g}/{args.trail_off:g}")
    tag.append(f"{args.atr_k:g}xATR")
    if args.expiry_exit:
        tag.append(f"expiry {EXPIRY_CUTOFF}")

    os.makedirs(REPORTS_DIR, exist_ok=True)
    asyncio.run(run(
        args.trend, args.offline, args.out,
        detect_fn=make_detector("v2", side=args.side),
        rule_html=RULE_HTML,
        variant=" &middot; " + " &middot; ".join(tag),
        from_date=args.from_date, to_date=args.to_date,
        schemes=schemes, expiry_exit=args.expiry_exit))


if __name__ == "__main__":
    main()
