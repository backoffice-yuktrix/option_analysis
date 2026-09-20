"""NIFTY "first hour favour" - the first hour's colour picks the side, a later
candle's CLOSE beyond the first hour's range is the trigger.  The user's rule
verbatim, run on FOUR breakout timeframes so the choice of chart is visible.

THE RULE                                    (LONG shown; SHORT is the mirror)
    1  The first hour, 09:15-10:14, closes GREEN (close > open) -> arm LONG.
       RED (close < open) -> arm SHORT.  A first hour that closes exactly at
       its open arms nothing and the day is skipped.
    2  cn = the first candle from 10:15 onward whose CLOSE is ABOVE the first
       hour's HIGH  (SHORT: whose CLOSE is BELOW the first hour's LOW).
    3  Entry = the OPEN of cn+1.
    4  SL = cn's LOW  (SHORT: cn's HIGH).
    5  Risk = |Entry - SL|,  Target = Entry + Risk x RR  (SHORT: Entry - Risk x RR).

THE TIMEFRAME AXIS - the point of this script
    The first hour is 09:15-10:14 on every timeframe; what changes is the
    candle that triggers and the candle that confirms the stop.  The report
    computes 1, 3, 5 and 15 minutes on IDENTICAL first-hour levels, with 15
    selected when it opens.  Buckets are anchored at 09:15, so the 15m grid is
    10:15 / 10:30 / ..., the 5m grid 10:15 / 10:20 / ..., and so on.  Settled
    with the user 2026-09-20: the stop is confirmed on the SAME timeframe as
    the breakout, so each timeframe is a complete standalone strategy and the
    four are a clean comparison rather than four entries into one exit rule.

    Also settled 2026-09-20: "the next 15 mins" means SCAN FORWARD from 10:15
    for the first candle that closes beyond the level, not only the single
    candle immediately after the first hour - step 3's "cn + n" already treats
    cn as an index.  --scan-to caps how late a breakout is still taken.

TWO READINGS OF THE STOP, both computed, because they are not the same trade
    close  the rule as written - "cn low > cn+n close" - the position is closed
           only when a later candle CLOSES beyond cn's level, and the fill is
           that candle's close.  THE DEFAULT, because it is the literal spec.
           A confirmed stop does NOT cap the loss at 1R: the fill lands wherever
           the candle closed.  The `slip` column is how far past the level it
           landed, and the day table shows fill, level and realised R together.
    touch  a resting order at cn's level, filled the moment price trades there.
           Every loss is exactly 1R, but a trade that only wicks through the
           level is stopped instead of surviving.

WHAT THE SIGNAL IS DECIDED ON, AND WHAT THE MONEY IS
    Two passes, and the order is the whole design.  Pass 1 runs the rule on
    SPOT alone - the first hour, the breakout, the stop and the target are all
    decided there.  Only then are the ATM contracts those signals imply
    resolved and fetched, so an option can never move a level or change which
    trades exist; it only puts a rupee figure on a result the underlying has
    already determined.  A green first hour buys the ATM CE, a red one the ATM PE.

    FILLS ARE THE WORST OF THE MINUTE (the user's standing rule, 2026-09-19):
    the option is BOUGHT at the entry minute's HIGH and SOLD at the exit
    minute's LOW.  Close fills are computed beside them and can be selected,
    but they are never the headline.  A contract-day cached close-only before
    2026-09-19 has no high/low to punish; those trades say so in the day table
    and the report counts them, so a timeframe cannot look good on missing data.

    Rupees are GROSS, then brokerage and statutory charges from
    services/trade_costs.py, then NET.  Win rate is judged on NET.

SAMPLE SIZE - state it, do not hide behind it
    The default window is the last 6 months.  A rule that fires roughly twice a
    week yields ~50 trades there, which resolves an edge of about +-0.37 R and
    nothing finer.  Per-timeframe cells are smaller still.  Treat the timeframe
    comparison as a description of this window, not as evidence that one chart
    beats another; the four timeframes trade the same days and are heavily
    correlated, so their differences are far less independent than four
    separate t-statistics would suggest.

WHAT THE FIRST RUN FOUND   (2026-03-21 -> 2026-09-20, 122 sessions, 87 traded)
    Headline, close stop / RR 1:2 / worst fills, both sides together:

        tf    n   tgt/stop/sq   win%    mean%     PF      net Rs   spot meanR
        1m   87    40/47/ 0     19.5    -8.86    0.06    -56,350      +0.23
        3m   85    31/51/ 3     22.4   -12.97    0.11    -75,853      -0.10
        5m   82    33/48/ 1     31.7   -12.70    0.22    -69,623      -0.06
       15m   80    26/41/13     31.2   -11.75    0.43    -66,620      -0.10

    Every timeframe, every side, every R:R from 1 to 5 and both stop rules
    lose money.  Nothing here is tradeable as written, and the interesting
    part is WHERE it dies:

    1  ON SPOT THE RULE IS A COIN FLIP, not a disaster.  Mean R at RR 1:2 runs
       -0.44 to +0.55 depending on the cell, and the 2R target is hit on 32-46%
       of trades against a ~33% break-even.  The LONG side is negative on all
       four timeframes (-0.13 to -0.44 R) and the SHORT side positive on all
       four (+0.13 to +0.55 R), but the per-month cells behind that are 1-11
       trades and the sign flips month to month, so it is not evidence of a
       side edge - and the window is a falling market, which would produce the
       same asymmetry with no edge at all.  See [[cas-structural-break]].

    2  THE OPTION LEG IS WHAT KILLS IT, and specifically the fill, not the
       costs.  Mean return on premium at RR 1:2, both sides, close stop:

        tf    close fills    worst fills    fill haircut    costs     net
        1m      -0.37%         -7.91%          -7.54%       0.95%    -8.86%
        3m      -5.29%        -11.98%          -6.69%       0.99%   -12.97%
        5m      -3.49%        -11.73%          -8.24%       0.97%   -12.70%
       15m      -3.14%        -10.81%          -7.67%       0.94%   -11.75%

       Brokerage and taxes are ~1% of premium.  Buying at the entry minute's
       HIGH and selling at the exit minute's LOW costs 5-10%.  The worst-fill
       rule is a deliberate stress test, not a quote, so read this as "the
       rule has no margin to pay a spread with" rather than "the spread is 8%".
       Even at neutral CLOSE fills only one cell is positive (1m SHORT, +3.77%
       on 46 trades) and everything else still loses.

    3  THE CLOSE-CONFIRMED STOP COSTS ROUGHLY HALF AN R PER STOP.  Mean risk
       and the mean overshoot past the stop LEVEL when it fires:

        tf     mean risk    slip per stop    overshoot as a fraction of R
        1m      11.0 pts       2.7 pts                 0.25 R
        3m      19.1 pts       7.2 pts                 0.38 R
        5m      23.3 pts       8.7 pts                 0.37 R
       15m      36.6 pts      17.4 pts                 0.48 R

       So "risk = entry - SL" understates the realised loss by a quarter to a
       half of an R on every timeframe.  The touch stop caps it at exactly 1R
       and turns out slightly LESS bad in rupees on 3m/5m/15m, but it also
       converts winners into stops (15m targets fall 26 -> 19), so the two
       rules are close to a wash and neither rescues the rule.

    4  FASTER IS NOT BETTER HERE.  1m produces the most trades (87) and the
       best spot R (+0.23) but the worst win rate (19.5%) and the worst profit
       factor (0.06), because an 11-point stop is inside the noise and the
       premium haircut is a fixed toll paid on every one of them.  15m - the
       user's own spec - is the least bad of the four on PF and win rate.

    These four timeframes trade the same days off the same first hour, so they
    are not four independent tests; the spread between them is far less
    meaningful than four separate t-statistics would suggest.

VERIFIED (2026-09-20)
    The spot rule was re-derived by a second, independent implementation
    reading the 1-minute cache directly - side, first-hour OHLC, breakout
    candle, entry, stop, risk, target, exit time, exit price, points and R,
    under both stop rules - and agreed on all 488 (session, timeframe) pairs.
    The report's in-page JavaScript aggregation was executed against the
    script's own Python summarise() over all 240 selector combinations and
    agreed on every field to display precision.

Run from backend/:
    python scripts/first_hour_favor_v1.py
    python scripts/first_hour_favor_v1.py --offline
    python scripts/first_hour_favor_v1.py --side LONG --tf 5
    python scripts/first_hour_favor_v1.py --from 2025-03-21 --to 2026-09-20

Output: first_hour_favor_v1_report.html (self-contained, no CDN).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..")
sys.path.insert(0, BACKEND_DIR)

from services.market_data import (  # noqa: E402
    load_minutes, read_access_token, print_coverage, option_file)
from services.option_pricing import (  # noqa: E402
    CachedPricer, OptionPricer, RateLimiter, ensure_cached, atm_strike,
    _candle_keys)
from services.trade_costs import capital_required, option_round_trip  # noqa: E402

REPORTS_DIR = os.path.join(BACKEND_DIR, "reports")
REPORT_HTML = os.path.join(REPORTS_DIR, "first_hour_favor_v1_report.html")

# NIFTY lot size verified against the Upstox contract master for this period.
LOT_SIZE = 65

OPEN_TIME = "09:15"
# The first hour is 09:15-10:14 inclusive - sixty one-minute candles.  The
# 10:15 candle is the first one that can trigger.
FH_END = "10:14"
SCAN_FROM = "10:15"
# How late a breakout is still taken.  A cut-off is a rule choice, not a data
# detail: without one the last bucket of the day can trigger an entry with
# minutes left to resolve it.  14:00 leaves ~85 minutes before square-off.
SCAN_TO = "14:00"
SQUARE_OFF = "15:25"
DAY_END = "15:29"

# The breakout/stop timeframes compared side by side.  15 is the user's spec
# and is what the report opens on.
TIMEFRAMES = [1, 3, 5, 15]
DEFAULT_TF = 15

RR_VALUES = [1.0, 2.0, 3.0, 4.0, 5.0]
DEFAULT_RR = 2.0

STOP_MODES = [("close", "a later candle CLOSES beyond cn's level, filled at that close (the literal rule)"),
              ("touch", "a resting order at cn's level, filled at the level - every loss exactly 1R")]
DEFAULT_STOP = "close"

FILL_MODES = [("worst", "buy the option at the entry minute's HIGH, sell at the exit minute's LOW"),
              ("close", "both legs at the minute's close - optimistic, for comparison only")]
DEFAULT_FILL = "worst"

SIDES = ["LONG", "SHORT"]
DEFAULT_SIDE = "BOTH"

PRICER = CachedPricer()


def rr_label(r: float) -> str:
    return f"1:{r:g}"


def tf_label(tf: int) -> str:
    return f"{tf}m"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _read_access_token() -> str | None:
    """The broker token (services/market_data reads the same file)."""
    return read_access_token()


async def load_nifty(offline: bool, from_date: date, to_date: date) -> list[dict]:
    """Index minute candles from data/nifty_1m.json (fetching only the days it
    does not already hold)."""
    return await load_minutes(offline, from_date, to_date)


def index_by_day(candles: list[dict]) -> dict[str, list[dict]]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for c in candles:
        ts = c.get("timestamp", "")
        if len(ts) < 16:
            continue
        by_day[ts[:10]].append(c)
    for day in by_day:
        by_day[day].sort(key=lambda c: c["timestamp"])
    return dict(by_day)


# ---------------------------------------------------------------------------
# Candle building
# ---------------------------------------------------------------------------

def bucket_start(hhmm: str, minutes: int) -> str:
    """09:15-anchored bucket label for a one-minute candle."""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    offset = (h * 60 + m) - (9 * 60 + 15)
    if offset < 0:
        return OPEN_TIME
    start = 9 * 60 + 15 + (offset // minutes) * minutes
    return f"{start // 60:02d}:{start % 60:02d}"


def build_buckets(minutes: list[dict], size: int) -> list[dict]:
    """Aggregate 1-minute candles into `size`-minute candles, in time order.

    Every bucket keeps its own minutes, because the target and the touch-stop
    are resolved minute by minute inside the bucket - a target reached at 11:03
    must be taken before the 11:15 close can decide anything.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in minutes:
        hhmm = c["timestamp"][11:16]
        if hhmm < OPEN_TIME or hhmm > DAY_END:
            continue
        groups[bucket_start(hhmm, size)].append(c)
    out = []
    for start in sorted(groups):
        g = groups[start]
        out.append({
            "start": start,
            "open": float(g[0]["open"]),
            "high": max(float(c["high"]) for c in g),
            "low": min(float(c["low"]) for c in g),
            "close": float(g[-1]["close"]),
            "minutes": g,
        })
    return out


def first_hour(minutes: list[dict]) -> dict | None:
    """The 09:15-10:14 candle, built from one-minute candles."""
    g = [c for c in minutes if OPEN_TIME <= c["timestamp"][11:16] <= FH_END]
    if not g:
        return None
    return {"open": float(g[0]["open"]),
            "high": max(float(c["high"]) for c in g),
            "low": min(float(c["low"]) for c in g),
            "close": float(g[-1]["close"]),
            "bars": len(g)}


# ---------------------------------------------------------------------------
# The walk to the exit
# ---------------------------------------------------------------------------

def walk(bars: list[dict], i_entry: int, side: str, sl: float, target: float,
         square_off: str, stop_mode: str) -> dict:
    """Forward walk from the entry candle until target, stop or square-off.

    The target and the touch-stop are checked on every MINUTE, so an intrabar
    target is taken before the bar's close can trigger a close-confirmed stop.
    Within a single minute the STOP is checked first, so a minute that spans
    both levels is scored as a loss - the pessimistic reading, because
    one-minute data cannot say which came first.
    """
    long_ = side == "LONG"
    for b in bars[i_entry:]:
        for m in b["minutes"]:
            hhmm = m["timestamp"][11:16]
            if hhmm >= square_off:
                return {"exit": float(m["open"]), "exit_time": hhmm, "reason": "SQUARE OFF"}
            if stop_mode == "touch":
                if (long_ and float(m["low"]) <= sl) or (not long_ and float(m["high"]) >= sl):
                    return {"exit": sl, "exit_time": hhmm, "reason": "STOP"}
            if (long_ and float(m["high"]) >= target) or (not long_ and float(m["low"]) <= target):
                return {"exit": target, "exit_time": hhmm, "reason": "TARGET"}
        if stop_mode == "close" and ((long_ and b["close"] < sl) or
                                     (not long_ and b["close"] > sl)):
            return {"exit": b["close"], "exit_time": b["minutes"][-1]["timestamp"][11:16],
                    "reason": "STOP"}
    last = bars[-1]
    return {"exit": last["close"], "exit_time": last["minutes"][-1]["timestamp"][11:16],
            "reason": "EOD"}


# ---------------------------------------------------------------------------
# The option leg - worst fills, then costs
# ---------------------------------------------------------------------------

def _day_option(pricer: CachedPricer, day: str, side: str, spot_entry: float,
                roll: str = "none") -> dict:
    """The contract a signal would buy, with BOTH its minute closes and its
    minute high/low.

    CachedPricer.day_prices() serves only the closes, and the worst-fill rule
    needs the high of the entry minute and the low of the exit minute.  Rather
    than widen the shared service for one strategy, this resolves the SAME
    contract through the pricer's own lookup and reads both views out of the
    shared store.  `ckey` comes back too, because the high/low backfill has to
    fetch under exactly the key this function reads - resolving the contract
    independently there can land on a different expiry and store the candles
    where nothing ever looks for them.

    `ohlc` is {} for a contract-day that was only ever cached close-only; such a
    trade falls back to the close fill and says so, rather than inventing a high
    or a low it does not have.
    """
    d = date.fromisoformat(day)
    strike = atm_strike(spot_entry)
    opt = "CE" if side == "LONG" else "PE"
    out = {"strike": strike, "option_type": opt, "symbol": None, "ckey": None,
           "candles": {}, "ohlc": {}, "reason": None}
    c = pricer._contract(d, strike, opt, roll)
    if not c:
        out["reason"] = "no contract"
        return out
    out["symbol"] = c["trading_symbol"]
    out["ckey"] = c.get("ckey")
    keys = _candle_keys(c, day)
    out["candles"] = next((pricer.candles[k] for k in keys if pricer.candles.get(k)), {})
    out["ohlc"] = next((pricer.ohlc[k] for k in keys if pricer.ohlc.get(k)), {})
    if not out["candles"]:
        out["reason"] = "no option candles"
    return out


def _leg(info: dict, entry_hhmm: str, exit_hhmm: str, fill: str) -> dict:
    """Premium, costs and net for one fill convention on the ATM option.

    `pnl_rs` is None with `opt_reason` set when the contract or its candles
    could not be had.  Such a trade STAYS in the table and is simply left out
    of the money totals - dropping it would quietly shrink the sample.

    fill "worst": bought at the entry minute's HIGH, sold at the exit minute's
    LOW.  When that minute has no high/low cached (a contract-day fetched
    close-only before 2026-09-19) the leg falls back to the close and sets
    `basis` to "close (no high/low)", which the report counts and shows.
    """
    blank = {"entry_px": None, "exit_px": None, "prem_pts": None, "pnl_rs": None,
             "cost_rs": None, "net_rs": None, "capital_rs": None, "ret_pct": None,
             "win": None, "basis": None, "opt_reason": info.get("reason")}
    if info.get("reason"):
        return blank

    closes, ohlc = info["candles"], info.get("ohlc") or {}
    basis = fill
    entry_px = exit_px = None
    if fill == "worst":
        eb, xb = ohlc.get(entry_hhmm), ohlc.get(exit_hhmm)
        if eb and xb:
            entry_px, exit_px = float(eb[1]), float(xb[2])      # high, low
        else:
            basis = "close (no high/low)"
    if entry_px is None:
        entry_px = closes.get(entry_hhmm)
        exit_px = closes.get(exit_hhmm)
    if entry_px is None:
        return dict(blank, basis=basis, opt_reason=f"no premium at entry {entry_hhmm}")
    if exit_px is None:
        return dict(blank, basis=basis, entry_px=round(float(entry_px), 2),
                    opt_reason=f"no premium at exit {exit_hhmm}")

    entry_px, exit_px = round(float(entry_px), 2), round(float(exit_px), 2)
    prem = round(exit_px - entry_px, 2)
    gross = round(prem * LOT_SIZE, 2)
    cost = option_round_trip("buy", entry_px, exit_px, LOT_SIZE)["total"]
    net = round(gross - cost, 2)
    cap = capital_required("buy", None, LOT_SIZE, entry_px)
    return {"entry_px": entry_px, "exit_px": exit_px, "prem_pts": prem,
            "pnl_rs": gross, "cost_rs": round(cost, 2), "net_rs": net,
            "capital_rs": cap, "ret_pct": round(net / cap * 100, 2) if cap else None,
            "win": net > 0, "basis": basis, "opt_reason": None}


# ---------------------------------------------------------------------------
# The strategy, one session
# ---------------------------------------------------------------------------

def simulate_day(day: str, minutes: list[dict], *, timeframes: list[int],
                 scan_from: str, scan_to: str, square_off: str,
                 rr_values: list[float], stop_modes: list[str],
                 fill_modes: list[str], option_of=None) -> dict:
    """Run the rule on one session, on every timeframe.  Always returns a
    diagnostic row, so a day that produced nothing says why.

    `option_of(day, side, entry) -> info | None` resolves the contract a signal
    would have bought.  It is None on the FIRST pass, which is what keeps the
    option out of the decision: pass 1 produces the signals on spot alone, and
    only the contracts those signals imply are then fetched.  Each timeframe
    gets its own lookup because each has its own entry, so a 1m entry and a 15m
    entry on the same day can land on different ATM strikes.
    """
    row: dict = {"date": day, "status": "", "side": None, "fh": None,
                 "tf": {tf_label(tf): {"status": "not reached"} for tf in timeframes}}

    fh = first_hour(minutes)
    if not fh or fh["bars"] < 30:
        row["status"] = "no data"
        return row
    row["fh"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in fh.items()}

    # ---- Step 1: the first hour's colour picks the side -------------------
    if fh["close"] > fh["open"]:
        side = "LONG"
    elif fh["close"] < fh["open"]:
        side = "SHORT"
    else:
        row["status"] = "first hour flat"
        return row
    row["side"] = side
    row["status"] = "armed"
    long_ = side == "LONG"
    level = fh["high"] if long_ else fh["low"]
    row["level"] = round(level, 2)

    any_trade = False
    for tf in timeframes:
        lab = tf_label(tf)
        sub: dict = {"status": "", "ex": {m: {} for m in stop_modes}}
        row["tf"][lab] = sub
        bars = build_buckets(minutes, tf)

        # ---- Step 2: the first close beyond the first hour's range --------
        idx = None
        for i, b in enumerate(bars):
            if b["start"] < scan_from or b["start"] > scan_to:
                continue
            if (long_ and b["close"] > level) or (not long_ and b["close"] < level):
                idx = i
                break
        if idx is None:
            sub["status"] = "no breakout"
            continue
        cn = bars[idx]
        if idx + 1 >= len(bars):
            sub["status"] = "no entry candle"
            continue
        nxt = bars[idx + 1]

        entry = nxt["open"]                                   # ---- Step 3
        sl = cn["low"] if long_ else cn["high"]               # ---- Step 4
        # Risk is signed on purpose.  Taking abs() here would hide an entry
        # that gapped to the WRONG SIDE of its own stop - a long whose next
        # candle opens below cn's low is already stopped before it starts, and
        # an abs() risk would silently turn it into a normal trade.
        risk = (entry - sl) if long_ else (sl - entry)
        sub.update({"breakout": cn["start"], "breakout_close": round(cn["close"], 2),
                    "cn_high": round(cn["high"], 2), "cn_low": round(cn["low"], 2),
                    "entry_time": nxt["start"], "entry": round(entry, 2),
                    "sl": round(sl, 2), "risk": round(risk, 2)})
        if risk <= 0:
            sub["status"] = "entry already beyond SL"
            continue

        sub["status"] = "trade"
        any_trade = True
        opt_info = option_of(day, side, entry) if option_of else None
        if opt_info is not None:
            sub["strike"] = opt_info.get("strike")
            sub["opt_type"] = opt_info.get("option_type")
            sub["opt_symbol"] = opt_info.get("symbol")

        # ---- Step 5: the same entry at every RR, under both stop rules ----
        for mode in stop_modes:
            for r in rr_values:
                target = entry + risk * r if long_ else entry - risk * r
                res = walk(bars, idx + 1, side, sl, target, square_off, mode)
                pts = (res["exit"] - entry) if long_ else (entry - res["exit"])
                cell = {
                    "target": round(target, 2), "exit": round(res["exit"], 2),
                    "exit_time": res["exit_time"], "reason": res["reason"],
                    "points": round(pts, 2), "r_multiple": round(pts / risk, 3),
                    # how far past the stop LEVEL the fill landed - 0 unless the
                    # close-confirmed stop overshot it
                    "slip": round(abs(sl - res["exit"]), 2) if res["reason"] == "STOP" else 0.0,
                    "fills": {},
                }
                if opt_info is not None:
                    for f in fill_modes:
                        cell["fills"][f] = _leg(opt_info, sub["entry_time"],
                                                res["exit_time"], f)
                sub["ex"][mode][rr_label(r)] = cell

    if any_trade:
        row["status"] = "trade"
    return row


# ---------------------------------------------------------------------------
# Aggregation - size-free metrics first, rupees for one lot beside them
# ---------------------------------------------------------------------------

def cells_of(rows: list[dict], tf: str, mode: str, key: str, fill: str,
             sides: list[str]) -> list[dict]:
    """Every scored trade under one (timeframe, stop rule, R:R, fill), flattened
    with the day-level fields the tables need."""
    out = []
    for r in rows:
        if r.get("side") not in sides:
            continue
        sub = r["tf"].get(tf) or {}
        if sub.get("status") != "trade":
            continue
        cell = (sub.get("ex", {}).get(mode) or {}).get(key)
        if not cell:
            continue
        out.append({"date": r["date"], "side": r["side"], "risk": sub["risk"],
                    "entry": sub["entry"], "sl": sub["sl"],
                    **{k: v for k, v in cell.items() if k != "fills"},
                    **(cell["fills"].get(fill) or {})})
    return out


def _stats(values: list[float]) -> dict:
    """n / mean / median / t on a list, or nulls when it is empty."""
    n = len(values)
    if not n:
        return {"n": 0, "mean": None, "median": None, "t": None}
    mean = statistics.fmean(values)
    sd = statistics.pstdev(values) if n > 1 else 0.0
    return {"n": n, "mean": round(mean, 4), "median": round(statistics.median(values), 4),
            "t": round(mean / (sd / (n ** 0.5)), 2) if sd else None}


def summarise(cells: list[dict]) -> dict:
    """The one scoring function every table in the report goes through.

    Win rate and profit factor are on the option's NET rupees, because that is
    what the account sees.  R-multiple stays on SPOT, because that is what the
    rule's risk is defined on.  `ret_pct` is net over the premium paid, so the
    number is comparable across strikes and across timeframes without a
    capital fraction or a lot count baked in.
    """
    n = len(cells)
    priced = [c for c in cells if c.get("net_rs") is not None]
    nets = [c["net_rs"] for c in priced]
    rets = [c["ret_pct"] for c in priced if c.get("ret_pct") is not None]
    rs_ = [c["r_multiple"] for c in cells]
    wins = [v for v in nets if v > 0]
    losses = [v for v in nets if v <= 0]
    gw, gl = sum(wins), -sum(losses)
    return {
        "trades": n, "priced": len(priced), "unpriced": n - len(priced),
        "days": len({c["date"] for c in cells}),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(nets) * 100, 1) if nets else None,
        "pf": round(gw / gl, 2) if gl else (None if not gw else float("inf")),
        "gross_rs": round(sum(c["pnl_rs"] for c in priced), 2) if priced else 0.0,
        "cost_rs": round(sum(c["cost_rs"] for c in priced), 2) if priced else 0.0,
        "net_rs": round(sum(nets), 2) if nets else 0.0,
        "worst_rs": round(min(nets), 2) if nets else None,
        "best_rs": round(max(nets), 2) if nets else None,
        "ret": _stats(rets),
        "r": _stats(rs_),
        "pts": round(sum(c["points"] for c in cells), 2),
        "targets": len([c for c in cells if c["reason"] == "TARGET"]),
        "stops": len([c for c in cells if c["reason"] == "STOP"]),
        "sqoff": len([c for c in cells if c["reason"] in ("SQUARE OFF", "EOD")]),
        "slip": round(sum(c["slip"] for c in cells), 2),
        "fallback": len([c for c in priced if (c.get("basis") or "").startswith("close (")]),
    }


def group_by(cells: list[dict], keyfn) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for c in cells:
        buckets[keyfn(c)].append(c)
    return [{"key": k, **summarise(v)} for k, v in sorted(buckets.items())]


def month_key(c: dict) -> str:
    return c["date"][:7]


def week_key(c: dict) -> str:
    d = date.fromisoformat(c["date"])
    return (d - timedelta(days=d.weekday())).isoformat()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

async def ensure_ohlc(needs, token: str | None, offline: bool) -> int:
    """Top up the option OHLC cache for the contract-days this run will price.

    ensure_cached() guarantees CLOSES.  A contract-day fetched before
    2026-09-19 was stored close-only, and the worst-fill rule has no high/low
    to punish on such a day.  Those days are refetched here; any that stay
    without high/low fall back to the close fill, are counted, and are shown as
    such in the report rather than quietly flattering the result.
    """
    def outstanding() -> list[tuple[str, str]]:
        """(day, contract key) for every contract-day the report will price that
        has no high/low yet.  The contract key comes from the SAME lookup the
        report reads through, which is the whole point: an earlier version
        resolved the contract independently here, landed on a different expiry
        for some days, and cheerfully stored the candles under a key the reader
        never looks at - 'fetched 58/58' while 58 stayed missing.  Resolving by
        the reader's own key makes that class of miss impossible.
        """
        p = CachedPricer()
        out = {}
        for d, side, spot in needs:
            info = _day_option(p, d, side, spot)
            if info.get("reason") or info.get("ohlc") or not info.get("ckey"):
                continue
            out[(d, info["ckey"])] = True
        return sorted(out)

    missing = outstanding()
    if not missing:
        return 0
    if offline or not token:
        print(f"  ! {len(missing)} contract-days have no high/low cached "
              f"(offline={offline}) - those trades fall back to close fills and say so")
        return 0
    print(f"  fetching high/low for {len(missing)} contract-days (worst-fill rule) ...")
    import httpx
    client = httpx.AsyncClient(timeout=30.0)
    op = OptionPricer(client, token, RateLimiter(), offline=False)
    await op.load_calendar(date.fromisoformat(missing[0][0]),
                           date.fromisoformat(missing[-1][0]))
    got = 0
    for i, (day, ckey) in enumerate(missing, 1):
        exp_s, strike_s, opt = ckey.split("|")
        # _resolve() keys on exactly this ckey, and re-resolves a contract that
        # was cached while live but has since expired, so the candles land under
        # the spelling day_prices() reads.
        c = await op._resolve(date.fromisoformat(exp_s), float(strike_s), opt)
        full = await op.ohlc_for(c, date.fromisoformat(day)) if c else None
        if full:
            # ohlc_for() writes the bars and THEN the closes, and that closes
            # write marks the contract-day close-only again - which makes the
            # high/low it just fetched invisible to every reader.  Re-assert
            # the bars here, under the key _day_option() reads, instead of
            # changing the shared service.
            option_file().put(_candle_keys(c, day)[0], full, close_only=False)
            got += 1
        if i % 25 == 0:
            op.save()
    op.save()
    await client.aclose()
    left = len(outstanding())
    print(f"  high/low fetched for {got}/{len(missing)} contract-days; "
          f"{left} still without it" if left else
          f"  high/low fetched for {got}/{len(missing)} contract-days; all covered")
    return got


def console_table(rows: list[dict], timeframes: list[int], stop: str, key: str,
                  fill: str) -> None:
    """The same numbers the report opens on, printed so a run can be checked
    without opening the HTML."""
    print(f"\n  {stop} stop, RR {key}, {fill} fills")
    head = ("tf", "side", "n", "win%", "mean%", "med%", "t", "PF",
            "gross", "costs", "net", "meanR")
    print("  " + "".join(h.rjust(w) for h, w in zip(
        head, (4, 6, 5, 7, 8, 8, 7, 7, 11, 10, 11, 8))))

    def f(v, d=2):
        return "-" if v is None else f"{v:,.{d}f}"

    for tf in timeframes:
        for sides, tag in ((SIDES, "both"), (["LONG"], "long"), (["SHORT"], "short")):
            s = summarise(cells_of(rows, tf_label(tf), stop, key, fill, sides))
            if not s["trades"]:
                continue
            vals = (tf_label(tf), tag, str(s["trades"]), f(s["win_rate"], 1),
                    f(s["ret"]["mean"]), f(s["ret"]["median"]), f(s["ret"]["t"]),
                    f(s["pf"]), f(s["gross_rs"], 0), f(s["cost_rs"], 0),
                    f(s["net_rs"], 0), f(s["r"]["mean"]))
            print("  " + "".join(v.rjust(w) for v, w in zip(
                vals, (4, 6, 5, 7, 8, 8, 7, 7, 11, 10, 11, 8))))


async def run(args) -> None:
    candles = await load_nifty(args.offline, args.from_date, args.to_date)
    print_coverage(args.from_date, args.to_date, "1m")
    by_day = index_by_day(candles)
    days = sorted(d for d in by_day
                  if args.from_date.isoformat() <= d <= args.to_date.isoformat())
    if not days:
        raise RuntimeError("No sessions in the requested window.")

    timeframes = args.timeframes
    rr_values = args.rr_values
    labels = [rr_label(r) for r in rr_values]
    stop_modes = [k for k, _ in STOP_MODES]
    fill_modes = [k for k, _ in FILL_MODES]

    def sim(day: str, option_of=None) -> dict:
        return simulate_day(
            day, by_day[day], timeframes=timeframes, scan_from=args.scan_from,
            scan_to=args.scan_to, square_off=args.square_off, rr_values=rr_values,
            stop_modes=stop_modes, fill_modes=fill_modes, option_of=option_of)

    # ---- pass 1: the rule on SPOT alone ----------------------------------
    # Nothing about an option exists yet, so nothing about an option can move a
    # level or decide which trades there are.
    signals = set()
    for d in days:
        r = sim(d)
        if not r.get("side"):
            continue
        for sub in r["tf"].values():
            if sub.get("status") == "trade":
                signals.add((r["date"], r["side"], sub["entry"]))
    print(f"\n  pass 1 (spot only): {len(signals)} distinct (day, side, entry) signals "
          f"over {len(days)} sessions")

    # ---- pass 2: price those signals, then re-run with the pricer --------
    global PRICER
    token = None if args.offline else _read_access_token()
    PRICER = await ensure_cached(signals, token, args.offline)
    await ensure_ohlc(signals, token, args.offline)
    PRICER.reload()

    info_cache: dict = {}

    def option_of(day: str, side: str, entry: float) -> dict:
        k = (day, side, atm_strike(entry))
        if k not in info_cache:
            info_cache[k] = _day_option(PRICER, day, side, entry)
        return info_cache[k]

    rows = [sim(d, option_of) for d in days]
    trade_days = [r for r in rows if r["status"] == "trade"]
    print(f"  pass 2: {len(trade_days)} sessions produced a trade on at least one timeframe")

    console_table(rows, timeframes, args.stop_mode, rr_label(args.default_rr), args.fill)

    # ---- the 1-minute chart, trade days only -----------------------------
    chart = {}
    for r in trade_days:
        chart[r["date"]] = [
            [c["timestamp"][11:16], round(float(c["open"]), 2), round(float(c["high"]), 2),
             round(float(c["low"]), 2), round(float(c["close"]), 2)]
            for c in by_day[r["date"]]
            if OPEN_TIME <= c["timestamp"][11:16] <= DAY_END]

    # How much of the priced book actually has high/low data.  A worst-fill
    # headline computed on trades that silently fell back to closes would not
    # be a worst-fill headline at all, so the report states the coverage.
    cov_have = cov_all = 0
    for r in trade_days:
        for sub in r["tf"].values():
            if sub.get("status") != "trade":
                continue
            leg = ((sub.get("ex", {}).get(args.stop_mode) or {})
                   .get(rr_label(args.default_rr)) or {}).get("fills", {}).get("worst") or {}
            if leg.get("net_rs") is None:
                continue
            cov_all += 1
            if leg.get("basis") == "worst":
                cov_have += 1

    payload = {
        "meta": {
            "from": args.from_date.isoformat(), "to": args.to_date.isoformat(),
            "sessions": len(days), "trade_days": len(trade_days),
            "lot": LOT_SIZE, "fh_start": OPEN_TIME, "fh_end": FH_END,
            "scan_from": args.scan_from, "scan_to": args.scan_to,
            "square_off": args.square_off,
            "timeframes": [tf_label(t) for t in timeframes],
            "default_tf": tf_label(args.tf),
            "rr": labels, "default_rr": rr_label(args.default_rr),
            "stop_modes": [{"key": k, "label": v} for k, v in STOP_MODES],
            "default_stop": args.stop_mode,
            "fill_modes": [{"key": k, "label": v} for k, v in FILL_MODES],
            "default_fill": args.fill,
            "default_side": args.side,
            "worst_coverage": [cov_have, cov_all],
            "generated": date.today().isoformat(),
        },
        "days": rows,
        "chart": chart,
    }
    write_report(payload, args.out)
    size = os.path.getsize(args.out) / 1e6
    print(f"\n  wrote {args.out}  ({size:.1f} MB)")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NIFTY First Hour Favour</title>
<style>
  :root {
    color-scheme: light;
    --surface:#fbfaf7; --page:#f4f2ed; --ink:#191917; --ink2:#43423d; --muted:#76746c;
    --grid:#e2dfd7; --border:rgba(0,0,0,.10);
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
  .tab.on { background:var(--chip-on); color:var(--chip-on-ink); border-color:transparent;
            font-weight:600; }
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
  .pill.tgt { background:rgba(var(--upN),.16); color:var(--up); }
  .pill.sl { background:rgba(var(--downN),.16); color:var(--down); }
  .pill.eod { background:rgba(127,127,127,.18); color:var(--ink2); }
  .pill.no { background:rgba(184,134,11,.18); color:var(--warn); }
  .pill.long { background:rgba(var(--upN),.16); color:var(--up); }
  .pill.short { background:rgba(var(--downN),.16); color:var(--down); }
  .scroll { overflow:auto; max-height:520px; }
  .scroll.short { max-height:340px; }
  .ctrl { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:10px;
          font-size:12.5px; color:var(--ink2); }
  select, button.btn { background:var(--surface); color:var(--ink); border:1px solid var(--border);
           border-radius:6px; padding:5px 8px; font-size:12.5px; }
  button.btn { cursor:pointer; }
  button.btn:hover { background:var(--chip); }
  .chart-wrap { position:relative; }
  svg { width:100%; height:auto; display:block; }
  #chart { cursor:crosshair; touch-action:none; }
  #chart.drag { cursor:grabbing; }
  .legend { display:flex; gap:16px; flex-wrap:wrap; font-size:11.5px; color:var(--ink2);
            margin-top:8px; }
  .legend i { display:inline-block; width:14px; height:3px; vertical-align:middle;
              margin-right:5px; border-radius:2px; }
  #tip { position:absolute; pointer-events:none; background:var(--surface);
         border:1px solid var(--border); border-radius:7px; padding:7px 9px; font-size:11.5px;
         line-height:1.5; display:none; box-shadow:0 6px 20px rgba(0,0,0,.18);
         font-variant-numeric:tabular-nums; z-index:5; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media (max-width:900px) { .grid2 { grid-template-columns:1fr; } }
  table.matrix td, table.matrix th { text-align:right; }
  table.matrix td.rh, table.matrix th.rh { text-align:left; font-weight:600; }
  table.matrix tr[data-tf] td { cursor:pointer; }
  table.matrix td.sel { outline:2px solid var(--accent); outline-offset:-2px; }
  .note { font-size:12px; color:var(--ink2); line-height:1.65; }
  .note b { color:var(--ink); }
  .note li { margin-bottom:7px; }
</style>
</head>
<body>

<h1>NIFTY First Hour Favour &middot; breakout on __TFS__ &middot; __FROM__ &rarr; __TO__</h1>
<div class="sub">
  <b>Step 1</b> &mdash; the first hour <b>__FHS__&ndash;__FHE__</b> closes GREEN &rarr; arm LONG,
  RED &rarr; arm SHORT (a flat close arms nothing).
  <b>Step 2</b> &mdash; <b>cn</b> is the first candle from <b>__SCANF__</b> to <b>__SCANT__</b>
  whose CLOSE is beyond the first hour's high (long) or low (short).
  <b>Step 3</b> &mdash; entry is the <b>OPEN of cn+1</b>.
  <b>Step 4</b> &mdash; SL is cn's low (long) or cn's high (short).
  <b>Step 5</b> &mdash; Risk = |Entry &minus; SL|, Target = Entry &plusmn; Risk &times; RR.<br>
  The first hour is the same on every timeframe; what the timeframe changes is the candle
  that triggers and the candle that confirms the stop. Squared off at <b>__SQO__</b> if still
  open. Targets and touch-stops are resolved on 1-minute data, so an intrabar target is taken
  before that bar's close can trigger a close-confirmed stop; within one minute the stop is
  taken first.<br>
  Money is the <b>ATM option</b> the signal implies (CE long, PE short), one lot of <b>__LOT__</b>,
  bought at the entry minute's HIGH and sold at the exit minute's LOW, then brokerage and
  statutory charges. <b>__NDAYS__</b> sessions, <b>__NTRADE__</b> of them produced a trade.
</div>

<div class="card">
  <div class="tabrow"><span class="cap">Side</span><span id="tabsSide" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow"><span class="cap">Timeframe</span><span id="tabsTF" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow"><span class="cap">Stop rule</span><span id="tabsStop" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow"><span class="cap">Risk : reward</span><span id="tabsRR" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow"><span class="cap">Fill</span><span id="tabsFill" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow" style="margin-bottom:0"><span class="cap">Selected</span>
    <span id="selDesc" style="font-size:12.5px;color:var(--ink2)"></span></div>
</div>

<div class="card">
  <h2>Overall &mdash; <span id="ovHead"></span></h2>
  <div class="stat-row" id="overall"></div>
  <div class="ctrl dim" style="margin:12px 0 0" id="ovNote"></div>
</div>

<div class="card">
  <h2>Timeframe &times; risk:reward &mdash; net &#8377; for 1 lot, after costs</h2>
  <div class="ctrl dim">Same first hour, same side, same day &mdash; only the trigger candle and
    the stop-confirming candle change. Click any cell to select that timeframe and R:R.</div>
  <div class="scroll"><table class="matrix" id="matrix"></table></div>
</div>

<div class="card">
  <h2>The four timeframes at the selected stop rule, R:R and fill</h2>
  <div class="scroll"><table id="tblTF"></table></div>
</div>

<div class="card">
  <h2>NIFTY 1-minute chart</h2>
  <div class="ctrl">
    <label for="daySel">Trade day</label>
    <select id="daySel"></select>
    <button class="btn" id="zoomIn">Zoom +</button>
    <button class="btn" id="zoomOut">Zoom &minus;</button>
    <button class="btn" id="zoomReset">Whole session</button>
    <span class="dim">wheel = zoom &middot; drag = pan &middot; double-click = reset</span>
    <span id="dayInfo" class="dim"></span>
  </div>
  <div class="chart-wrap"><svg id="chart" viewBox="0 0 1200 430"></svg><div id="tip"></div></div>
  <div class="legend">
    <span><i style="background:var(--muted)"></i>First hour high / low</span>
    <span><i style="background:var(--accent)"></i>Entry</span>
    <span><i style="background:var(--down)"></i>Stop &mdash; cn's low (long) / high (short)</span>
    <span><i style="background:var(--up)"></i>Target</span>
    <span>&#9670; Exit</span>
    <span class="dim">tinted band = the first hour 09:15&ndash;10:14</span>
  </div>
</div>

<div class="card">
  <h2>Day by day</h2>
  <div class="ctrl">
    <label><input type="checkbox" id="onlyTrades" checked> show only days that traded on this timeframe</label>
  </div>
  <div class="scroll"><table id="tblDays"></table></div>
</div>

<div class="grid2">
  <div class="card">
    <h2>Monthly</h2>
    <div class="scroll short"><table id="tblMonthly"></table></div>
  </div>
  <div class="card">
    <h2>Weekly</h2>
    <div class="scroll short"><table id="tblWeekly"></table></div>
  </div>
</div>

<div class="card">
  <h2>What these numbers can and cannot settle</h2>
  <ul class="note" id="caveats"></ul>
</div>

<script>
const DATA = __DATA_JSON__;
const M = DATA.meta;
let curSide = M.default_side, curTF = M.default_tf, curStop = M.default_stop,
    curRR = M.default_rr, curFill = M.default_fill;

const $ = id => document.getElementById(id);
const nf = (v, d) => v === null || v === undefined || !isFinite(v) ? '&mdash;'
  : Number(v).toLocaleString('en-IN', {minimumFractionDigits: d, maximumFractionDigits: d});
const plain = (v, d) => '<td class="num">' + nf(v, d) + '</td>';
const cell = (v, d) => '<td class="num">' + (v === null || v === undefined || !isFinite(v)
  ? '<span class="dim">&mdash;</span>'
  : '<span class="' + (v > 0 ? 'pos' : (v < 0 ? 'neg' : 'dim')) + '">' + nf(v, d) + '</span>') + '</td>';
const labelOf = (list, k) => (list.find(x => x.key === k) || {}).label || k;
// a win rate is only meaningful against the coin flip, so colour it against 50,
// not against zero the way a rupee figure is coloured
const winCell = v => '<td class="num">' + (v === null || v === undefined
  ? '<span class="dim">&mdash;</span>'
  : '<span class="' + (v > 50 ? 'pos' : (v < 50 ? 'neg' : 'dim')) + '">' + nf(v, 1) +
    '</span>') + '</td>';

// ---------------------------------------------------------------------------
// Selection -> trades.  Mirrors cells_of() / summarise() in the script, so the
// console table a run prints and the tables here are the same computation.
// ---------------------------------------------------------------------------
function cellsOf(tf, stop, rr, fill, side) {
  const out = [];
  for (const d of DATA.days) {
    if (!d.side) continue;
    if (side !== 'BOTH' && d.side !== side) continue;
    const sub = (d.tf || {})[tf];
    if (!sub || sub.status !== 'trade') continue;
    const c = ((sub.ex || {})[stop] || {})[rr];
    if (!c) continue;
    const f = (c.fills || {})[fill] || {};
    out.push(Object.assign({date: d.date, side: d.side, fh: d.fh, level: d.level,
      risk: sub.risk, entry: sub.entry, sl: sub.sl, entry_time: sub.entry_time,
      breakout: sub.breakout, breakout_close: sub.breakout_close, strike: sub.strike,
      opt_type: sub.opt_type, opt_symbol: sub.opt_symbol}, c, f));
  }
  return out;
}

function stats(v) {
  const n = v.length;
  if (!n) return {n: 0, mean: null, median: null, t: null};
  const mean = v.reduce((a, b) => a + b, 0) / n;
  const s = v.slice().sort((a, b) => a - b);
  const median = n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  const sd = Math.sqrt(v.reduce((a, b) => a + (b - mean) * (b - mean), 0) / n);
  return {n: n, mean: mean, median: median, t: sd ? mean / (sd / Math.sqrt(n)) : null};
}

function agg(cs) {
  const priced = cs.filter(c => c.net_rs !== null && c.net_rs !== undefined);
  const nets = priced.map(c => c.net_rs);
  const rets = priced.filter(c => c.ret_pct !== null && c.ret_pct !== undefined).map(c => c.ret_pct);
  const wins = nets.filter(v => v > 0), losses = nets.filter(v => v <= 0);
  const gw = wins.reduce((a, b) => a + b, 0), gl = -losses.reduce((a, b) => a + b, 0);
  return {
    trades: cs.length, priced: priced.length, unpriced: cs.length - priced.length,
    wins: wins.length, losses: losses.length,
    win_rate: nets.length ? wins.length / nets.length * 100 : null,
    pf: gl ? gw / gl : (gw ? Infinity : null),
    gross_rs: priced.reduce((a, c) => a + c.pnl_rs, 0),
    cost_rs: priced.reduce((a, c) => a + c.cost_rs, 0),
    net_rs: nets.reduce((a, b) => a + b, 0),
    worst_rs: nets.length ? Math.min.apply(null, nets) : null,
    best_rs: nets.length ? Math.max.apply(null, nets) : null,
    ret: stats(rets), r: stats(cs.map(c => c.r_multiple)),
    pts: cs.reduce((a, c) => a + c.points, 0),
    targets: cs.filter(c => c.reason === 'TARGET').length,
    stops: cs.filter(c => c.reason === 'STOP').length,
    sqoff: cs.filter(c => c.reason === 'SQUARE OFF' || c.reason === 'EOD').length,
    slip: cs.reduce((a, c) => a + c.slip, 0),
    fallback: priced.filter(c => (c.basis || '').indexOf('close (') === 0).length
  };
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
function tabs(host, items, get, set) {
  $(host).innerHTML = items.map(it =>
    '<button class="tab' + (get() === it.key ? ' on' : '') + '" data-k="' + it.key + '">' +
    it.text + (it.sub ? '<small>' + it.sub + '</small>' : '') + '</button>').join('');
  $(host).querySelectorAll('.tab').forEach(b =>
    b.onclick = () => { set(b.dataset.k); renderAll(); });
}

function renderTabs() {
  const sideCount = k => {
    const n = DATA.days.filter(d => d.side && (k === 'BOTH' || d.side === k)
      && ((d.tf || {})[curTF] || {}).status === 'trade').length;
    return n + ' trades';
  };
  tabs('tabsSide', [{key: 'BOTH', text: 'Both', sub: sideCount('BOTH')},
                    {key: 'LONG', text: 'Long', sub: sideCount('LONG')},
                    {key: 'SHORT', text: 'Short', sub: sideCount('SHORT')}],
       () => curSide, v => curSide = v);
  tabs('tabsTF', M.timeframes.map(t => ({key: t, text: t})), () => curTF, v => curTF = v);
  tabs('tabsStop', M.stop_modes.map(s => ({key: s.key, text: s.key})),
       () => curStop, v => curStop = v);
  tabs('tabsRR', M.rr.map(r => ({key: r, text: r})), () => curRR, v => curRR = v);
  tabs('tabsFill', M.fill_modes.map(f => ({key: f.key, text: f.key})),
       () => curFill, v => curFill = v);
  const cov = M.worst_coverage;
  $('selDesc').innerHTML =
    '<b>' + curSide.toLowerCase() + '</b> &middot; breakout and stop on the <b>' + curTF +
    '</b> candle &middot; stop: ' + labelOf(M.stop_modes, curStop) + ' &middot; target at <b>' +
    curRR + '</b> &middot; fill: ' + labelOf(M.fill_modes, curFill) +
    (curFill === 'worst' && cov[0] < cov[1]
      ? ' <span class="pill no">high/low on ' + cov[0] + ' of ' + cov[1] + ' priced trades</span>'
      : '');
}

// ---------------------------------------------------------------------------
// Overall
// ---------------------------------------------------------------------------
function renderOverall() {
  const s = agg(cellsOf(curTF, curStop, curRR, curFill, curSide));
  $('ovHead').textContent = curSide.toLowerCase() + ', ' + curTF + ', ' + curStop +
    ' stop, ' + curRR + ', ' + curFill + ' fills';
  const st = (v, l, cls) => '<div class="stat"><div class="v ' + (cls || '') + '">' + v +
    '</div><div class="l">' + l + '</div></div>';
  const col = v => v === null ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));
  $('overall').innerHTML =
    st(s.trades, 'trades') +
    st(s.wins + ' / ' + s.losses, 'win / loss (net)') +
    st(nf(s.win_rate, 1) + '%', 'win rate', col(s.win_rate === null ? null : s.win_rate - 50)) +
    st(nf(s.ret.mean, 2) + '%', 'mean return on premium', col(s.ret.mean)) +
    st(nf(s.ret.median, 2) + '%', 'median return', col(s.ret.median)) +
    st(nf(s.pf, 2), 'profit factor', col(s.pf === null ? null : s.pf - 1)) +
    st('&#8377; ' + nf(s.gross_rs, 0), 'gross', col(s.gross_rs)) +
    st('&#8377; ' + nf(s.cost_rs, 0), 'costs', 'neg') +
    st('&#8377; ' + nf(s.net_rs, 0), 'net, 1 lot', col(s.net_rs)) +
    st('&#8377; ' + nf(s.worst_rs, 0), 'worst trade', 'neg') +
    st(nf(s.r.mean, 2), 'mean R (spot)', col(s.r.mean)) +
    st(s.targets + ' / ' + s.stops + ' / ' + s.sqoff, 'target / stop / square-off');
  const bits = [];
  if (s.unpriced) bits.push('<b>' + s.unpriced + '</b> of ' + s.trades +
    ' trades had no option data and are shown but left out of every money total.');
  if (s.fallback) bits.push('<b>' + s.fallback + '</b> priced trades had no cached high/low ' +
    'and fell back to close fills &mdash; those are not worst fills.');
  if (curStop === 'close' && s.stops) bits.push('The close-confirmed stop overshot its level by ' +
    '<b>' + nf(s.slip, 1) + ' points</b> in total across ' + s.stops +
    ' stops, so those losses are bigger than 1R.');
  if (s.ret.t !== null) bits.push('t on the mean return is <b>' + nf(s.ret.t, 2) +
    '</b> over ' + s.ret.n + ' trades &mdash; see the caveats below before reading that as an edge.');
  $('ovNote').innerHTML = bits.join(' ');
}

// ---------------------------------------------------------------------------
// Matrix: timeframe x R:R
// ---------------------------------------------------------------------------
function renderMatrix() {
  let h = '<thead><tr><th class="rh">timeframe</th>' +
    M.rr.map(r => '<th>' + r + '</th>').join('') + '<th>trades</th></tr></thead><tbody>';
  for (const tf of M.timeframes) {
    h += '<tr data-tf="' + tf + '"><td class="rh">' + tf + '</td>';
    let n = 0;
    for (const rr of M.rr) {
      const s = agg(cellsOf(tf, curStop, rr, curFill, curSide));
      n = s.trades;
      const selCls = (tf === curTF && rr === curRR) ? ' sel' : '';
      h += '<td class="num' + selCls + '" data-rr="' + rr + '">' +
        (s.priced ? '<span class="' + (s.net_rs > 0 ? 'pos' : 'neg') + '">' +
          nf(s.net_rs, 0) + '</span><br><span class="dim" style="font-size:11px">' +
          nf(s.win_rate, 0) + '% win</span>' : '<span class="dim">&mdash;</span>') + '</td>';
    }
    h += '<td class="num dim">' + n + '</td></tr>';
  }
  $('matrix').innerHTML = h + '</tbody>';
  $('matrix').querySelectorAll('td[data-rr]').forEach(td => td.onclick = () => {
    curTF = td.parentElement.dataset.tf; curRR = td.dataset.rr; renderAll();
  });
}

// ---------------------------------------------------------------------------
// Timeframe comparison
// ---------------------------------------------------------------------------
function renderTF() {
  let h = '<thead><tr><th class="rh">timeframe</th><th>trades</th><th>W / L</th><th>win %</th>' +
    '<th>mean %</th><th>median %</th><th>t</th><th>PF</th><th>mean R</th>' +
    '<th>gross &#8377;</th><th>costs &#8377;</th><th>net &#8377;</th><th>worst &#8377;</th>' +
    '<th>target</th><th>stop</th><th>sq-off</th><th>slip pts</th><th>no px</th>' +
    '</tr></thead><tbody>';
  for (const tf of M.timeframes) {
    const s = agg(cellsOf(tf, curStop, curRR, curFill, curSide));
    h += '<tr' + (tf === curTF ? ' style="outline:2px solid var(--accent);outline-offset:-2px"' : '') +
      '><td class="rh">' + tf + '</td>' + plain(s.trades, 0) +
      '<td class="num">' + s.wins + ' / ' + s.losses + '</td>' + winCell(s.win_rate) +
      cell(s.ret.mean, 2) + cell(s.ret.median, 2) + plain(s.ret.t, 2) + plain(s.pf, 2) +
      cell(s.r.mean, 2) + cell(s.gross_rs, 0) + plain(s.cost_rs, 0) + cell(s.net_rs, 0) +
      cell(s.worst_rs, 0) + plain(s.targets, 0) + plain(s.stops, 0) + plain(s.sqoff, 0) +
      plain(s.slip, 1) + plain(s.unpriced, 0) + '</tr>';
  }
  $('tblTF').innerHTML = h + '</tbody>';
}

// ---------------------------------------------------------------------------
// Periodic tables
// ---------------------------------------------------------------------------
function groupTable(host, keyfn) {
  const cs = cellsOf(curTF, curStop, curRR, curFill, curSide);
  const b = {};
  cs.forEach(c => { (b[keyfn(c)] = b[keyfn(c)] || []).push(c); });
  let h = '<thead><tr><th class="rh">period</th><th>trades</th><th>W / L</th><th>win %</th>' +
    '<th>mean %</th><th>PF</th><th>net &#8377;</th></tr></thead><tbody>';
  Object.keys(b).sort().forEach(k => {
    const s = agg(b[k]);
    h += '<tr><td class="rh">' + k + '</td>' + plain(s.trades, 0) +
      '<td class="num">' + s.wins + ' / ' + s.losses + '</td>' + winCell(s.win_rate) +
      cell(s.ret.mean, 2) + plain(s.pf, 2) + cell(s.net_rs, 0) + '</tr>';
  });
  $(host).innerHTML = h + '</tbody>';
}

// ---------------------------------------------------------------------------
// Day by day
// ---------------------------------------------------------------------------
function renderDays() {
  const only = $('onlyTrades').checked;
  let h = '<thead><tr><th class="rh">date</th><th>side</th><th>FH open</th><th>FH close</th>' +
    '<th>FH high</th><th>FH low</th><th>cn</th><th>cn close</th><th>entry @</th><th>entry</th>' +
    '<th>SL</th><th>risk</th><th>target</th><th>exit @</th><th>exit</th><th>why</th>' +
    '<th>pts</th><th>R</th><th>slip</th><th>contract</th><th>buy px</th><th>sell px</th>' +
    '<th>prem</th><th>gross &#8377;</th><th>costs &#8377;</th><th>net &#8377;</th><th>ret %</th>' +
    '<th>fill</th></tr></thead><tbody>';
  for (const d of DATA.days) {
    const sub = (d.tf || {})[curTF] || {};
    const isTrade = sub.status === 'trade';
    const sideOk = !d.side || curSide === 'BOTH' || d.side === curSide;
    if (only && !(isTrade && sideOk)) continue;
    if (!sideOk && d.side) continue;
    const fh = d.fh || {};
    if (!isTrade) {
      const why = sub.status || d.status;
      h += '<tr><td class="rh">' + d.date + '</td><td>' +
        (d.side ? '<span class="pill ' + d.side.toLowerCase() + '">' + d.side + '</span>'
                : '<span class="dim">&mdash;</span>') + '</td>' +
        plain(fh.open, 2) + plain(fh.close, 2) + plain(fh.high, 2) + plain(fh.low, 2) +
        '<td colspan="22" class="dim">' + why + '</td></tr>';
      continue;
    }
    const c = ((sub.ex || {})[curStop] || {})[curRR] || {};
    const f = (c.fills || {})[curFill] || {};
    const why = c.reason === 'TARGET' ? '<span class="pill tgt">TARGET</span>'
      : c.reason === 'STOP' ? '<span class="pill sl">STOP</span>'
      : '<span class="pill eod">' + c.reason + '</span>';
    const contract = sub.opt_symbol
      ? '<span class="dim">' + sub.strike + ' ' + sub.opt_type + '</span>'
      : '<span class="dim">&mdash;</span>';
    const basis = f.opt_reason ? '<span class="pill no">' + f.opt_reason + '</span>'
      : (f.basis === 'worst' ? '<span class="dim">worst</span>'
         : '<span class="pill no">' + (f.basis || '') + '</span>');
    h += '<tr><td class="rh">' + d.date + '</td><td><span class="pill ' +
      d.side.toLowerCase() + '">' + d.side + '</span></td>' +
      plain(fh.open, 2) + plain(fh.close, 2) + plain(fh.high, 2) + plain(fh.low, 2) +
      '<td>' + sub.breakout + '</td>' + plain(sub.breakout_close, 2) +
      '<td>' + sub.entry_time + '</td>' + plain(sub.entry, 2) + plain(sub.sl, 2) +
      plain(sub.risk, 2) + plain(c.target, 2) + '<td>' + c.exit_time + '</td>' +
      plain(c.exit, 2) + '<td>' + why + '</td>' + cell(c.points, 2) + cell(c.r_multiple, 2) +
      plain(c.slip, 2) + '<td>' + contract + '</td>' + plain(f.entry_px, 2) +
      plain(f.exit_px, 2) + cell(f.prem_pts, 2) + cell(f.pnl_rs, 0) + plain(f.cost_rs, 0) +
      cell(f.net_rs, 0) + cell(f.ret_pct, 2) + '<td>' + basis + '</td></tr>';
  }
  $('tblDays').innerHTML = h + '</tbody>';
}

// ---------------------------------------------------------------------------
// Chart
// ---------------------------------------------------------------------------
let view = null, drag = null;

function chartDays() {
  return Object.keys(DATA.chart).filter(day => {
    const d = DATA.days.find(x => x.date === day);
    if (!d) return false;
    if (curSide !== 'BOTH' && d.side !== curSide) return false;
    return ((d.tf || {})[curTF] || {}).status === 'trade';
  }).sort();
}

function renderDaySel() {
  const days = chartDays();
  const prev = $('daySel').value;
  $('daySel').innerHTML = days.map(d => '<option>' + d + '</option>').join('');
  if (days.indexOf(prev) >= 0) $('daySel').value = prev;
  view = null;
  drawChart();
}

function drawChart() {
  const day = $('daySel').value;
  const bars = DATA.chart[day] || [];
  const svg = $('chart');
  if (!bars.length) { svg.innerHTML = ''; $('dayInfo').textContent = ''; return; }
  const d = DATA.days.find(x => x.date === day) || {};
  const sub = (d.tf || {})[curTF] || {};
  const c = ((sub.ex || {})[curStop] || {})[curRR] || {};
  if (!view) view = [0, bars.length - 1];
  const i0 = Math.max(0, Math.round(view[0])), i1 = Math.min(bars.length - 1, Math.round(view[1]));
  const vis = bars.slice(i0, i1 + 1);
  const W = 1200, H = 430, L = 58, R = 92, T = 14, B = 26;
  const lines = [];
  if (d.fh) { lines.push(['fhH', d.fh.high, 'var(--muted)']); lines.push(['fhL', d.fh.low, 'var(--muted)']); }
  if (sub.status === 'trade') {
    lines.push(['entry', sub.entry, 'var(--accent)']);
    lines.push(['SL', sub.sl, 'var(--down)']);
    if (c.target !== undefined) lines.push(['target', c.target, 'var(--up)']);
  }
  let lo = Math.min.apply(null, vis.map(b => b[3])), hi = Math.max.apply(null, vis.map(b => b[2]));
  lines.forEach(l => { lo = Math.min(lo, l[1]); hi = Math.max(hi, l[1]); });
  const pad = (hi - lo) * 0.06 || 1;
  lo -= pad; hi += pad;
  const x = i => L + (i + 0.5) * (W - L - R) / vis.length;
  const y = p => T + (hi - p) * (H - T - B) / (hi - lo);
  const bw = Math.max(1, Math.min(9, (W - L - R) / vis.length * 0.66));
  let s = '';

  // the first hour, tinted
  const fhEnd = vis.findIndex(b => b[0] > M.fh_end);
  if (fhEnd !== 0) {
    const x1 = fhEnd < 0 ? W - R : x(fhEnd) - bw;
    s += '<rect x="' + L + '" y="' + T + '" width="' + Math.max(0, x1 - L) + '" height="' +
      (H - T - B) + '" fill="rgba(127,127,127,.09)"/>';
  }
  // y grid
  for (let k = 0; k <= 4; k++) {
    const p = lo + (hi - lo) * k / 4, yy = y(p);
    s += '<line x1="' + L + '" y1="' + yy + '" x2="' + (W - R) + '" y2="' + yy +
      '" stroke="var(--grid)" stroke-width="1"/>' +
      '<text x="' + (L - 6) + '" y="' + (yy + 4) + '" text-anchor="end" font-size="11" ' +
      'fill="var(--muted)">' + p.toFixed(0) + '</text>';
  }
  // x labels
  const step = Math.max(1, Math.round(vis.length / 9));
  vis.forEach((b, i) => {
    if (i % step) return;
    s += '<text x="' + x(i) + '" y="' + (H - 8) + '" text-anchor="middle" font-size="11" ' +
      'fill="var(--muted)">' + b[0] + '</text>';
  });
  // candles
  vis.forEach((b, i) => {
    const up = b[4] >= b[1], col = up ? 'var(--up)' : 'var(--down)';
    const yo = y(b[1]), yc = y(b[4]);
    s += '<line x1="' + x(i) + '" y1="' + y(b[2]) + '" x2="' + x(i) + '" y2="' + y(b[3]) +
      '" stroke="' + col + '" stroke-width="1"/>' +
      '<rect x="' + (x(i) - bw / 2) + '" y="' + Math.min(yo, yc) + '" width="' + bw +
      '" height="' + Math.max(1, Math.abs(yc - yo)) + '" fill="' + col + '"/>';
  });
  // levels
  lines.forEach(l => {
    const yy = y(l[1]);
    s += '<line x1="' + L + '" y1="' + yy + '" x2="' + (W - R) + '" y2="' + yy +
      '" stroke="' + l[2] + '" stroke-width="1.2" stroke-dasharray="5 4" opacity=".9"/>' +
      '<text x="' + (W - R + 6) + '" y="' + (yy + 4) + '" font-size="11" fill="' + l[2] +
      '">' + l[0] + ' ' + l[1].toFixed(0) + '</text>';
  });
  // exit marker
  if (sub.status === 'trade' && c.exit_time) {
    const j = vis.findIndex(b => b[0] === c.exit_time);
    if (j >= 0) s += '<polygon points="' + [[x(j), y(c.exit) - 6], [x(j) + 6, y(c.exit)],
      [x(j), y(c.exit) + 6], [x(j) - 6, y(c.exit)]].map(p => p.join(',')).join(' ') +
      '" fill="var(--ink)"/>';
  }
  svg.innerHTML = s;
  $('dayInfo').innerHTML = sub.status === 'trade'
    ? d.side + ' &middot; cn ' + sub.breakout + ' &middot; entry ' + sub.entry_time + ' @ ' +
      nf(sub.entry, 2) + ' &middot; SL ' + nf(sub.sl, 2) + ' &middot; risk ' + nf(sub.risk, 2) +
      ' pts &middot; exit ' + c.exit_time + ' @ ' + nf(c.exit, 2) + ' (' + c.reason + ')'
    : '';

  svg.onmousemove = ev => {
    if (drag) {
      const dx = (ev.clientX - drag.x) / svg.getBoundingClientRect().width * W;
      const n = (i1 - i0 + 1), shift = -dx / ((W - L - R) / n);
      let a = drag.i0 + shift, b = drag.i1 + shift;
      if (a < 0) { b -= a; a = 0; }
      if (b > bars.length - 1) { a -= b - (bars.length - 1); b = bars.length - 1; }
      view = [Math.max(0, a), b]; drawChart(); return;
    }
    const r = svg.getBoundingClientRect();
    const i = Math.round(((ev.clientX - r.left) / r.width * W - L) / ((W - L - R) / vis.length) - 0.5);
    const b = vis[i];
    if (!b) { $('tip').style.display = 'none'; return; }
    $('tip').innerHTML = '<b>' + b[0] + '</b><br>O ' + b[1] + '<br>H ' + b[2] +
      '<br>L ' + b[3] + '<br>C ' + b[4];
    $('tip').style.display = 'block';
    $('tip').style.left = Math.min(r.width - 110, ev.clientX - r.left + 14) + 'px';
    $('tip').style.top = (ev.clientY - r.top + 12) + 'px';
  };
  svg.onmouseleave = () => { $('tip').style.display = 'none'; };
  svg.onmousedown = ev => { drag = {x: ev.clientX, i0: i0, i1: i1}; svg.classList.add('drag'); };
  window.onmouseup = () => { drag = null; svg.classList.remove('drag'); };
  svg.ondblclick = () => { view = null; drawChart(); };
  svg.onwheel = ev => {
    ev.preventDefault();
    const r = svg.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, ((ev.clientX - r.left) / r.width * W - L) / (W - L - R)));
    const anchor = i0 + frac * (i1 - i0);
    const k = ev.deltaY > 0 ? 1.18 : 1 / 1.18;
    let a = anchor - (anchor - i0) * k, b = anchor + (i1 - anchor) * k;
    a = Math.max(0, a); b = Math.min(bars.length - 1, b);
    if (b - a >= 8) { view = [a, b]; drawChart(); }
  };
}

function zoom(k) {
  const day = $('daySel').value, bars = DATA.chart[day] || [];
  if (!bars.length) return;
  if (!view) view = [0, bars.length - 1];
  const mid = (view[0] + view[1]) / 2, half = (view[1] - view[0]) / 2 * k;
  view = [Math.max(0, mid - half), Math.min(bars.length - 1, mid + half)];
  drawChart();
}

// ---------------------------------------------------------------------------
// Caveats - the honest reading, rendered from the actual numbers
// ---------------------------------------------------------------------------
function renderCaveats() {
  const s = agg(cellsOf(curTF, curStop, curRR, curFill, curSide));
  const li = [];
  li.push('<li><b>Sample.</b> ' + s.trades + ' trades over ' + M.sessions + ' sessions (' +
    M.from + ' to ' + M.to + '). A window this size resolves an edge of roughly &plusmn;0.37 R ' +
    'and nothing finer, so treat a t-statistic here as a description of this window rather ' +
    'than evidence the rule is stable. Splitting it further &mdash; by month, by side, by ' +
    'timeframe &mdash; makes each cell smaller still.</li>');
  li.push('<li><b>The four timeframes are not four independent tests.</b> They share the same ' +
    'first hour, the same side and largely the same days; they differ only in which candle ' +
    'triggers and which candle confirms the stop. Picking the best of the four on this window ' +
    'is selection on noise, not a finding about charts.</li>');
  li.push('<li><b>A close-confirmed stop does not cap the loss at 1R.</b> Under the ' +
    '<b>close</b> rule the fill is wherever the candle closed, which can be well past cn\'s ' +
    'level; the <b>slip</b> column and the total in the overall panel are how far past. The ' +
    '<b>touch</b> rule caps every loss at exactly 1R but stops trades that only wicked ' +
    'through. Both are computed on identical entries &mdash; compare them, do not pick one ' +
    'and forget the other.</li>');
  li.push('<li><b>Fills.</b> The headline buys the option at the entry minute\'s HIGH and ' +
    'sells at the exit minute\'s LOW. ' + (M.worst_coverage[0] < M.worst_coverage[1]
      ? 'High/low data covers ' + M.worst_coverage[0] + ' of ' + M.worst_coverage[1] +
        ' priced trades; the rest fall back to close fills and are flagged in the day table.'
      : 'Every priced trade has the high/low data the rule needs.') +
    ' The <b>close</b> fill mode is there for comparison and is optimistic by construction.</li>');
  li.push('<li><b>The option never decided anything.</b> The first hour, the breakout, the ' +
    'stop and the target are all computed on spot; the ATM contract is resolved afterwards ' +
    'only to put rupees on the result. Trades whose contract or candles could not be had stay ' +
    'in the table and are left out of the money totals &mdash; dropping them would quietly ' +
    'shrink the sample.</li>');
  li.push('<li><b>Rupees are for one lot of ' + M.lot + '</b> and are gross, then costs, then ' +
    'net; win rate is on net. The size-free figures &mdash; mean return on premium, win rate, ' +
    'profit factor &mdash; are the ones to compare variants on, because they carry no capital ' +
    'fraction or lot count.</li>');
  li.push('<li><b>Session structure.</b> From 2026-08-03 the closing auction damped the last ' +
    'half hour of the index session and F&amp;O trading was extended to 15:40, while the index ' +
    'feed still stops at 15:29. This rule enters mid-morning and squares off at ' + M.square_off +
    ', so it is not a late-session rule &mdash; but any trade that reaches square-off in the ' +
    'post-August window is being closed in a thinner tape than the same trade a year earlier.</li>');
  $('caveats').innerHTML = li.join('');
}

// ---------------------------------------------------------------------------
function renderAll() {
  renderTabs(); renderOverall(); renderMatrix(); renderTF();
  groupTable('tblMonthly', c => c.date.slice(0, 7));
  groupTable('tblWeekly', c => {
    const d = new Date(c.date + 'T00:00:00Z');
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    return d.toISOString().slice(0, 10);
  });
  renderDays(); renderDaySel(); renderCaveats();
}

$('onlyTrades').onchange = renderDays;
$('daySel').onchange = () => { view = null; drawChart(); };
$('zoomIn').onclick = () => zoom(1 / 1.4);
$('zoomOut').onclick = () => zoom(1.4);
$('zoomReset').onclick = () => { view = null; drawChart(); };
renderAll();
</script>
</body>
</html>
"""


def write_report(payload: dict, out_path: str) -> None:
    m = payload["meta"]
    html = (HTML_TEMPLATE
            .replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":")))
            .replace("__TFS__", ", ".join(m["timeframes"]))
            .replace("__FHS__", m["fh_start"])
            .replace("__FHE__", m["fh_end"])
            .replace("__SCANF__", m["scan_from"])
            .replace("__SCANT__", m["scan_to"])
            .replace("__SQO__", m["square_off"])
            .replace("__LOT__", str(m["lot"]))
            .replace("__NDAYS__", str(m["sessions"]))
            .replace("__NTRADE__", str(m["trade_days"]))
            .replace("__FROM__", m["from"])
            .replace("__TO__", m["to"]))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    today = date.today()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tf", type=int, default=DEFAULT_TF,
                    help="breakout timeframe selected when the report opens (default 15)")
    ap.add_argument("--timeframes", type=int, nargs="+", default=TIMEFRAMES, metavar="MIN",
                    help="breakout timeframes to compute (default 1 3 5 15)")
    ap.add_argument("--rr", dest="rr_values", type=float, nargs="+", default=RR_VALUES,
                    metavar="R", help="reward:risk multiples to compare (default 1 2 3 4 5)")
    ap.add_argument("--default-rr", type=float, default=DEFAULT_RR,
                    help="risk:reward selected when the report opens (default 2)")
    ap.add_argument("--stop-mode", choices=[k for k, _ in STOP_MODES], default=DEFAULT_STOP,
                    help="stop rule selected when the report opens; both are always computed")
    ap.add_argument("--fill", choices=[k for k, _ in FILL_MODES], default=DEFAULT_FILL,
                    help="fill convention selected when the report opens; both are computed")
    ap.add_argument("--side", choices=["BOTH", "LONG", "SHORT"], default=DEFAULT_SIDE,
                    help="side selected when the report opens; both are always computed")
    ap.add_argument("--scan-from", default=SCAN_FROM,
                    help="earliest breakout candle (default 10:15, the candle after the first hour)")
    ap.add_argument("--scan-to", default=SCAN_TO,
                    help="latest breakout candle still taken (default 14:00)")
    ap.add_argument("--square-off", default=SQUARE_OFF)
    ap.add_argument("--offline", action="store_true", help="use local caches only")
    ap.add_argument("--out", default=REPORT_HTML)
    ap.add_argument("--from", dest="from_date", type=date.fromisoformat,
                    default=today - timedelta(days=183), help="default: 6 months back")
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat, default=today)
    args = ap.parse_args()
    if args.default_rr not in args.rr_values:
        args.default_rr = args.rr_values[0]
    if args.tf not in args.timeframes:
        args.tf = args.timeframes[-1]
    os.makedirs(REPORTS_DIR, exist_ok=True)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
