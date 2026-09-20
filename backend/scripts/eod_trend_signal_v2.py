"""EOD trend signal, v2 - the sign of the day, every session, one bought option six
strikes in the money, bought before the last minute, sold on the first calm
minute that is profitable through its whole range.

v1 is the user's seven-feature rule.  v2 keeps option BUYING (the user's goal:
a higher win rate than v1 inside buying, never selling) and replaces the
signal with the sign of the day.  Its execution settings were revised on
2026-09-19 after a 1,620-cell grid over the six months under the worst-fill
rule (buy at the entry minute's HIGH, sell at the exit minute's LOW):

    setting        first version (2026-09-18)   current (2026-09-19)
    strike         4 strikes in the money       6 strikes in the money
    entry minute   15:29                        15:20
    exit scan      from 09:16                   from 09:30

Each change has a mechanical reason, checked before and after the closing-
auction change and across every other setting of the grid; the first-version
settings stay in the report's selectors for comparison.  Nothing in the rule
has a threshold.

THE RULE
--------
    Feed        NSE_INDEX|Nifty 50, one-minute candles, Asia/Kolkata.
    Daily bar   09:15 open .. 15:14 close, from the 360 one-minute candles.
    Decision    after the 15:14 candle completes; nothing from 15:15 on is read.

    1. 15:14 close ABOVE the 09:15 open  -> BUY   (buy a CALL)
    2. 15:14 close BELOW the 09:15 open  -> SELL  (buy a PUT)
    3. equal, or any candle missing, duplicated or invalid -> HOLD

    Strike      SIX strikes in the money: the call at ATM-6, the put at ATM+6
                (300 points in).  Deeper is better in the data but not tradeable:
                flat (no-trade) minutes are 2% of the exit day at 4 strikes in,
                7% at 6, 18% at 8, 35% at 10 - past 6 the worst-fill test has
                nothing to punish.  8 strikes in is carried, labelled thin.
    Entry       the 15:20 minute (any minute 15:15-15:25 tests the same).  The
                15:29 minute has the widest range of the afternoon, so its HIGH
                - the worst-fill entry - sat a mean 7.8 points above the 15:20
                high before the auction change; buying earlier removes that.
    Expiry      the nearest weekly expiry strictly AFTER the exit day.
    Exit        from 09:30 of the next session, the FIRST minute whose LOW is
                above the entry by more than the round-trip costs, sold at that
                minute's low; if no minute gets there by 15:14, sold in the
                15:14 minute.  Minute ranges run 45 points at 09:15, 19 at
                09:16, ~10 by 09:20 and settle after 09:30; a low-trigger that
                fires before 09:30 is filled far below the close.
    Fills       WORST OF THE MINUTE (user's rule of 2026-09-19).  Close fills
                are carried beside them for comparison.

    Every night is also priced at ATM, 2, 4 and 8 strikes in and under five
    other exits; the report carries the matrix and the selectors read any cell.

WHY THESE SETTINGS (six months 2026-03-20 -> 2026-09-19, 122 nights, net of
brokerage and taxes, worst fills)
    first  4 ITM, entry 15:29, low-trigger from 09:16  69.7% win   net Rs  44,379  PF 1.14
    now    6 ITM, entry 15:20, low-trigger from 09:30  73.8% win   net Rs 130,494  PF 1.43
        (90 W / 32 L, gross 141,794 less costs 11,300, worst night -21,214;
         post-auction window 26 W / 7 L, 78.8%, net Rs 22,294, PF 1.40)
    (the grid marginals: strike ATM->10 ITM lifts PF 1.08->1.37 monotonically;
    entry 15:20 beats 15:29 at every strike pre-CAS, equal post-CAS; start 09:30
    beats 09:16 in both regimes; trailing costs win rate; a 14:00 fallback that
    scans to 15:14 is look-ahead and was dropped.)

WHAT IT IS NOT
--------------
* Six months of option data; the signal's five-year record is spot only.
* A bought option's loss is capped at the premium, about Rs 23,000 a lot here.
* At 6 strikes in, 7% of exit-day minutes have no trade; in those minutes the
  worst-fill rule cannot bite.  The liquidity table in the report shows this
  for every strike offered.

Shares its data layer with eod_trend_signal_v1.py and its capital and cost
arithmetic with services/trade_costs.py.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..")
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, SCRIPT_DIR)

import httpx  # noqa: E402
from services.option_pricing import (  # noqa: E402
    CachedPricer, OptionPricer, RateLimiter, atm_strike, _candle_keys)
from services.market_data import (  # noqa: E402
    load_minutes, load_daily, load_daily_ohlc, load_fut_volume,
    read_access_token, print_coverage)
from services.trade_costs import (  # noqa: E402
    capital_required, option_round_trip, live_margin)
from eod_trend_signal_v1 import (  # noqa: E402
    IST, LOT_SIZE, SESSION_START, FEATURE_END, ENTRY_HHMM, CAS_DATE, PARTIAL_MODES,
    PRICED_START, CHART_FULL_DAYS, PX_TOLERANCE_MIN, REPORTS_DIR, RESULTS_DIR,
    _read_access_token, load_nifty, load_daily_ohlc, to_rows, build_sessions,
    daily_series, stats, _px_at, _day_closes)

REPORT_HTML = os.path.join(REPORTS_DIR, "eod_trend_signal_v2_report.html")
SIGNALS_CSV = os.path.join(RESULTS_DIR, "eod_trend_signal_v2_signals.csv")
TRADES_CSV = os.path.join(RESULTS_DIR, "eod_trend_signal_v2_trades.csv")

EXIT_HHMM = "09:15"
# The option panel carries the whole exit day and this much of the entry day.
CHART_OPT_ENTRY_FROM = "14:00"
# Since 2026-09-19 the option is bought in the 15:20 minute, not the last one (the 15:29 minute has the widest
# afternoon range, and the worst-fill entry is that minute's HIGH).  Shadows the
# constant imported from v1; the spot reference entry moves to the same minute.
ENTRY_HHMM = "15:20"
CHART_END = "15:29"

# (key, kind, offset, label).  kind 'sell' sells the OPPOSITE option `offset`
# points out of the money; 'buy' buys the signal's side `offset` points in.
# Strikes are 50 points apart, so the offsets are 0 / 2 / 4 / 6 strikes.  A BUY
# takes the strike BELOW the ATM (ATM-n), a SELL the strike ABOVE it (ATM+n):
# bought that is in the money, sold on the opposite side it is out of the money.
# BOUGHT options only - the user's goal for v2 is a higher win rate than v1
# within option buying.  Selling was tested in the study and set aside.
INSTRUMENTS = [
    ("buy-ATM", "buy", 0, "Buy - ATM"),
    ("buy-ITM100", "buy", 100, "Buy - 2 strikes ITM"),
    ("buy-ITM200", "buy", 200, "Buy - 4 strikes ITM (earlier default)"),
    ("buy-ITM300", "buy", 300, "Buy - 6 strikes ITM"),
    ("buy-ITM400", "buy", 400, "Buy - 8 strikes ITM (thin: ~18% of minutes untraded)"),
]
STRIKE_STEP = 50


def rel_strike(t: dict, off: int) -> str:
    """The strike named the way a trader says it: ATM, ATM-2, ATM+4."""
    n = off // STRIKE_STEP
    if n == 0:
        return "ATM"
    return f"ATM{'-' if t['decision'] == 'BUY' else '+'}{n}"
# (key, label, limit_hhmm, threshold or None).  None = fixed close at `limit`;
# a threshold = the first one-minute close in profit by more than that fraction
# of the entry premium, else the close at `limit`.
# thr None = fixed close at `limit`; "costs" = the first one-minute close that
# is above the entry by at least the round-trip brokerage and taxes (about 1.2
# premium points on one lot), so every win is a win AFTER costs; a number = the
# first close that fraction of the entry premium above it.
# (key, label, limit, threshold, trigger, start).  trigger 'close' fires when the
# minute's CLOSE clears the threshold; 'low' fires only when the minute's LOW
# clears it, so under worst fills the sale is a profit by construction.  `start`
# is the first minute the exit may fire: the 09:15 minute's option range is a
# median 45 points against 19 at 09:16 and about 10 by 09:20 (measured
# 2026-09-19), so any exit allowed to fire at 09:15 is filled at the low of the
# widest minute of the day and loses under the worst-fill rule.
EXITS = [
    ("low-0930-15:14", "first minute whose LOW clears costs, from 09:30, by 15:14", "15:14", "costs", "low", "09:30"),
    ("low-0916-15:14", "first minute whose LOW clears costs, from 09:16, by 15:14 (earlier default)", "15:14", "costs", "low", "09:16"),
    ("low1-0930-15:14", "first minute whose LOW clears costs +1%, from 09:30, by 15:14", "15:14", 0.01, "low", "09:30"),
    ("cover-15:14", "first CLOSE above costs, from 09:15, by 15:14", "15:14", "costs", "close", "09:15"),
    ("09:30", "09:30 fixed", "09:30", None, "close", "09:30"),
    ("15:14", "15:14 fixed (hold the full session)", "15:14", None, "close", "15:14"),
]
# Capital and transaction costs come from services/trade_costs.py, the one
# place every strategy computes them.
# How each minute is filled.  "worst" is the user's stress test (2026-09-19): pay
# the HIGH of the entry minute, receive the LOW of the exit minute, so no fill
# in the backtest is better than a real one could have been.
FILLS = [
    ("worst", "worst - buy at the entry minute's HIGH, sell at the exit minute's LOW"),
    ("close", "close - the minute's closing price, as the data prints"),
]
DEFAULT_FILL = "worst"
DEFAULT_INSTRUMENT = "buy-ITM300"
DEFAULT_EXIT = "low-0930-15:14"
INSTRUMENT_BY_KEY = {k: (kind, off, lab) for k, kind, off, lab in INSTRUMENTS}
EXIT_BY_KEY = {k: (lab, lim, thr) for k, lab, lim, thr, _trig, _start in EXITS}


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

def add_context(series: list[dict], signals: list[dict]) -> None:
    """Attach the familiar filter inputs to each signal so the report can show
    what a filter would COST.  None of these is read by the rule itself."""
    by_day = {x["day"]: x for x in signals}
    for i, s in enumerate(series):
        x = by_day.get(s["day"])
        if x is None:
            continue
        prev = series[i - 1] if i >= 1 else None
        x["prev_move_pct"] = ((prev["c"] / prev["o"] - 1) * 100 if prev and prev["valid"] else None)
        x["gap_pct"] = ((s["o"] / prev["c"] - 1) * 100 if prev and prev["valid"] and s["valid"] else None)
        x["ret5_pct"] = ((s["c"] / series[i - 5]["c"] - 1) * 100 if i >= 5 and s["valid"] and series[i - 5]["valid"] else None)
        x["trend30_pct"] = ((s["c"] / series[i - 29]["c"] - 1) * 100 if i >= 29 and s["valid"] and series[i - 29]["valid"] else None)
        w = [z for z in series[max(0, i - 5):i] if z["valid"]]
        atr5 = statistics.fmean((z["h"] - z["l"]) / z["c"] * 100 for z in w) if len(w) == 5 else None
        x["range_ratio5"] = (((s["h"] - s["l"]) / s["c"] * 100) / atr5 if atr5 and s["valid"] else None)
        x["weekday"] = date.fromisoformat(s["day"]).weekday()


def compute_signal(s: dict) -> dict:
    """BUY / SELL / HOLD for one session from its own daily bar."""
    out = {"day": s["day"], "decision": "HOLD", "data_ok": True, "hold_reason": "",
           "day_open": None, "close": None, "day_high": None, "day_low": None,
           "move_pct": None, "loc_day": None}
    if not s["valid"]:
        out["data_ok"] = False
        out["hold_reason"] = f"session invalid: {s['invalid_reason']}"
        return out
    out.update(day_open=s["o"], close=s["c"], day_high=s["h"], day_low=s["l"],
               move_pct=(s["c"] / s["o"] - 1.0) * 100.0,
               loc_day=(s["c"] - s["l"]) / (s["h"] - s["l"]) if s["h"] > s["l"] else None)
    if s["c"] > s["o"]:
        out["decision"] = "BUY"
    elif s["c"] < s["o"]:
        out["decision"] = "SELL"
    else:
        out["hold_reason"] = "15:14 close equals the 09:15 open"
    return out


def build_trades(signals: list[dict], sessions: dict, all_days: list[str]) -> list[dict]:
    pos = {d: k for k, d in enumerate(all_days)}
    out = []
    for sig in signals:
        if sig["decision"] == "HOLD":
            continue
        s = sessions[sig["day"]]
        side = "LONG" if sig["decision"] == "BUY" else "SHORT"
        t = {"day": sig["day"], "decision": sig["decision"], "side": side,
             "move_pct": sig["move_pct"], "entry_time": ENTRY_HHMM, "entry_spot": None,
             "entry_open_1529": None, "exit_day": None, "exit_day_assumed": None,
             "exit_time": None, "exit_spot": None, "spot_pts": None, "spot_pct": None,
             "status": "closed", "legs": {}}
        if s["entry"] is None:
            t["status"] = f"no {ENTRY_HHMM} candle - not filled"
            out.append(t)
            continue
        t["entry_spot"], t["entry_open_1529"] = s["entry"]["c"], s["entry"]["o"]
        k = pos[sig["day"]]
        if k + 1 >= len(all_days):
            t["status"] = "open - next session not in the data"
            nd = date.fromisoformat(sig["day"]) + timedelta(days=1)
            while nd.weekday() >= 5:
                nd += timedelta(days=1)
            t["exit_day_assumed"] = nd.isoformat()
            out.append(t)
            continue
        nxt = sessions[all_days[k + 1]]
        t["exit_day"] = nxt["day"]
        if nxt["first"] is None:
            t["status"] = "next session has no usable candle"
            out.append(t)
            continue
        t["exit_time"], t["exit_spot"] = nxt["first"]["t"], nxt["first"]["c"]
        pts = (t["exit_spot"] - t["entry_spot"]) if side == "LONG" else (t["entry_spot"] - t["exit_spot"])
        t["spot_pts"], t["spot_pct"] = round(pts, 2), pts / t["entry_spot"] * 100.0
        out.append(t)
    return out


# ---------------------------------------------------------------------------
# Pricing - after the signal, and it can change nothing above
# ---------------------------------------------------------------------------

def contract_spec(t: dict, kind: str, off: int) -> tuple[str, float]:
    """(option type, strike) for one instrument on one trade."""
    a = atm_strike(t["entry_spot"])
    if kind == "buy":
        return ("CE", a - off) if t["decision"] == "BUY" else ("PE", a + off)
    return ("PE", a - off) if t["decision"] == "BUY" else ("CE", a + off)


def _exit_day_of(t: dict) -> str:
    return t["exit_day"] or t["exit_day_assumed"]


def _expiries_after(expiries, exit_day: str):
    return [e for e in expiries if e > date.fromisoformat(exit_day)][:3]


def _cached(pricer: CachedPricer, t: dict, opt: str, strike: float):
    for e in _expiries_after(pricer.expiries, _exit_day_of(t)):
        key = f"{e.isoformat()}|{strike:.0f}|{opt}"
        c = pricer.contracts.get(key)
        if c:
            c = dict(c, ckey=key)
            ec = next((pricer.candles[k] for k in _candle_keys(c, t["day"])
                       if pricer.candles.get(k)), {})
            xc = next((pricer.candles[k] for k in _candle_keys(c, t["exit_day"])
                       if pricer.candles.get(k)), {}) if t["exit_day"] else {}
            eo = next((pricer.ohlc[k] for k in _candle_keys(c, t["day"])
                       if pricer.ohlc.get(k)), {})
            xo = next((pricer.ohlc[k] for k in _candle_keys(c, t["exit_day"])
                       if pricer.ohlc.get(k)), {}) if t["exit_day"] else {}
            return c, ec, xc, eo, xo
    return None, {}, {}, {}, {}


def _complete(t: dict, c, ec, xc, eo, xo) -> bool:
    return bool(c and ec and eo and ((xc and xo) or not t["exit_day"]))


async def _fetch(op: OptionPricer, t: dict, opt: str, strike: float) -> bool:
    for e in _expiries_after(op.expiries, _exit_day_of(t)):
        c = await op._resolve(e, strike, opt)
        if c:
            a = await op.ohlc_for(c, date.fromisoformat(t["day"]))
            if not a:                                   # today: closes only via intraday
                a = await _day_closes(op, c, date.fromisoformat(t["day"]))
            b = (await op.ohlc_for(c, date.fromisoformat(t["exit_day"]))
                 if t["exit_day"] else True)
            return bool(a and b)
    return False


def _ohlc_at(xo: dict, hhmm: str, direction: int):
    """The [o,h,l,c] of the minute `hhmm`, else the nearest within tolerance."""
    if hhmm in xo:
        return xo[hhmm], hhmm
    m0 = int(hhmm[:2]) * 60 + int(hhmm[3:])
    for k in range(1, PX_TOLERANCE_MIN + 1):
        m = m0 + k * direction
        key = f"{m // 60:02d}:{m % 60:02d}"
        if key in xo:
            return xo[key], key
    return None, None


def _exit_worst(xo: dict, sgn: int, e_px: float, lim: str, thr, kind: str = "buy",
                trigger: str = "close", start: str = EXIT_HHMM):
    """(exit premium, minute) under one exit rule with WORST fills: the fill is
    the minute's LOW (bought option); the trigger is its close or, for
    trigger='low', its low - which makes the sale a profit by construction."""
    if thr is None:
        bar, m = _ohlc_at(xo, lim, +1)
        return (bar[2], m) if bar else (None, None)
    need = (option_round_trip(kind, e_px, e_px, LOT_SIZE)["total"] / LOT_SIZE
            if thr == "costs" else thr * e_px)
    ref = 2 if trigger == "low" else 3
    for m in sorted(xo):
        if m < start:
            continue
        if m > lim:
            break
        if sgn * (xo[m][ref] - e_px) > need:
            return xo[m][2], m
    bar, m = _ohlc_at(xo, lim, -1)
    return (bar[2], m) if bar else (None, None)


def _exit_px(xc: dict, sgn: int, e_px: float, lim: str, thr, kind: str = "buy",
             trigger: str = "close", start: str = EXIT_HHMM, xo: dict | None = None):
    """(exit premium, minute) under one exit rule with CLOSE fills.  A 'low'
    trigger needs the minute bars; without them it degrades to the close."""
    if thr is None:
        return _px_at(xc, lim, +1)
    need = (option_round_trip(kind, e_px, e_px, LOT_SIZE)["total"] / LOT_SIZE
            if thr == "costs" else thr * e_px)
    for m in sorted(xc):
        if m < start:
            continue
        if m > lim:
            break
        ref = xo[m][2] if (trigger == "low" and xo and m in xo) else xc[m]
        if sgn * (ref - e_px) > need:
            return xc[m], m
    return _px_at(xc, lim, -1)


def _legs_for(t: dict, kind: str, off: int, c, ec, xc, eo=None, xo=None) -> dict:
    """One instrument's result under every exit rule."""
    base = {"symbol": None, "expiry": None, "dte": None, "strike": None, "option_type": None,
            "entry_px": None, "entry_minute": None, "reason": None,
            "capital_rs": None, "capital_source": None, "instrument_key": None, "rel_strike": None}
    opt, strike = contract_spec(t, kind, off)
    base.update(strike=strike, option_type=opt, rel_strike=rel_strike(t, off))
    if not c:
        base["reason"] = "no contract"
        return {"info": base, "exits": {k: {"reason": base["reason"]} for k, *_ in EXITS}}
    base.update(symbol=c["trading_symbol"], expiry=c["ckey"].split("|")[0],
                instrument_key=c.get("instrument_key"))
    base["dte"] = (date.fromisoformat(base["expiry"]) - date.fromisoformat(t["day"])).days
    e_px, e_min = _px_at(ec, ENTRY_HHMM, -1)
    if e_px is None or e_px <= 0:
        base["reason"] = f"no premium within {PX_TOLERANCE_MIN} min of {ENTRY_HHMM}"
        return {"info": base, "exits": {k: {"reason": base["reason"]} for k, *_ in EXITS}}
    base.update(entry_px=round(e_px, 2), entry_minute=e_min,
                capital_rs=capital_required(kind, t["entry_spot"], LOT_SIZE, e_px, off),
                capital_source="estimate")
    # worst fill: the HIGH of the entry minute
    ebar, _em = _ohlc_at(eo or {}, ENTRY_HHMM, -1)
    e_w = ebar[1] if ebar else None
    base.update(entry_px_w=None if e_w is None else round(e_w, 2),
                capital_rs_w=capital_required(kind, t["entry_spot"], LOT_SIZE, e_w, off) if e_w else None)
    sgn = 1 if kind == "buy" else -1
    exits = {}
    for key, _lab, lim, thr, trig, start in EXITS:
        leg = {"exit_px": None, "exit_minute": None, "prem_pts": None, "prem_pct": None,
               "pnl_rs": None, "costs_rs": None, "net_rs": None, "reason": None,
               "exit_px_w": None, "exit_minute_w": None, "prem_pts_w": None, "prem_pct_w": None,
               "pnl_rs_w": None, "costs_rs_w": None, "net_rs_w": None,
               "line": None, "line_w": None}
        # The price the rule is actually watching for, under each fill.  The
        # chart draws it, so what you see is the number the exit compares to.
        if thr is not None:
            need_c = (option_round_trip(kind, e_px, e_px, LOT_SIZE)["total"] / LOT_SIZE
                      if thr == "costs" else thr * e_px)
            leg["line"] = round(e_px + sgn * need_c, 2)
            if e_w:
                need_w = (option_round_trip(kind, e_w, e_w, LOT_SIZE)["total"] / LOT_SIZE
                          if thr == "costs" else thr * e_w)
                leg["line_w"] = round(e_w + sgn * need_w, 2)
        if not t["exit_day"]:
            leg["reason"] = "open - no exit yet"
        else:
            x_px, x_min = _exit_px(xc, sgn, e_px, lim, thr, kind, trig, start, xo)
            if x_px is None:
                leg["reason"] = f"no premium within {PX_TOLERANCE_MIN} min of {lim}"
            else:
                pnl = sgn * (x_px - e_px)
                costs = option_round_trip(kind, e_px, x_px, LOT_SIZE)["total"]
                leg.update(exit_px=round(x_px, 2), exit_minute=x_min, prem_pts=round(pnl, 2),
                           prem_pct=pnl / e_px * 100.0, pnl_rs=round(pnl * LOT_SIZE, 2),
                           costs_rs=costs, net_rs=round(pnl * LOT_SIZE - costs, 2))
            if e_w and xo:
                xw, xm = _exit_worst(xo, sgn, e_w, lim, thr, kind, trig, start)
                if xw is not None:
                    pnl = sgn * (xw - e_w)
                    costs = option_round_trip(kind, e_w, xw, LOT_SIZE)["total"]
                    leg.update(exit_px_w=round(xw, 2), exit_minute_w=xm, prem_pts_w=round(pnl, 2),
                               prem_pct_w=pnl / e_w * 100.0, pnl_rs_w=round(pnl * LOT_SIZE, 2),
                               costs_rs_w=costs, net_rs_w=round(pnl * LOT_SIZE - costs, 2))
        exits[key] = leg
        # the minute-by-minute walk the report shows for the default exit
        if key == DEFAULT_EXIT and xo and e_w and thr == "costs":
            line = e_w + option_round_trip(kind, e_w, e_w, LOT_SIZE)["total"] / LOT_SIZE
            last = leg.get("exit_minute_w") or lim
            ms = [m for m in sorted(xo) if start <= m <= last]
            shown = ms[:12] + ([ms[-1]] if len(ms) > 13 else ms[12:13])
            leg["walk"] = {"line": round(line, 2), "n": len(ms), "start": start, "limit": lim,
                           "rows": [[m, xo[m][2], xo[m][1], xo[m][2] > line] for m in shown]}
    return {"info": base, "exits": exits}


async def price_trades(trades: list[dict], offline: bool, token: str | None,
                       chart_from: str | None = None) -> tuple[int, int, dict]:
    priceable = [t for t in trades if t["entry_spot"] is not None
                 and (t["status"] == "closed" or t["status"].startswith("open"))]
    if not priceable:
        return 0, 0
    pricer = CachedPricer()
    need = []
    for t in priceable:
        for key, kind, off, _ in INSTRUMENTS:
            opt, strike = contract_spec(t, kind, off)
            if not _complete(t, *_cached(pricer, t, opt, strike)):
                need.append((t, opt, strike))
    if need and not offline and token:
        print(f"  fetching option series (with open/high/low) for {len(need)} night/instrument legs ...")
        client = httpx.AsyncClient(timeout=30.0)
        op = OptionPricer(client, token, RateLimiter(), offline=False)
        await op.load_calendar(date.fromisoformat(min(t["day"] for t, *_ in need)),
                               date.fromisoformat(max(_exit_day_of(t) for t, *_ in need)))
        got = 0
        for i, (t, opt, strike) in enumerate(need, 1):
            got += await _fetch(op, t, opt, strike)
            if i % 25 == 0:
                op.save()
        op.save()
        await client.aclose()
        print(f"  fetched {got}/{len(need)} (contracts {op.fetched_contracts}, days {op.fetched_days})")
        pricer.reload()
    elif need:
        print(f"  ! {len(need)} legs without option data and no token (offline={offline})")
    priced = 0
    option_chart: dict[str, dict] = {}
    for t in priceable:
        for key, kind, off, _ in INSTRUMENTS:
            opt, strike = contract_spec(t, kind, off)
            got = _cached(pricer, t, opt, strike)
            t["legs"][key] = _legs_for(t, kind, off, *got)
            # the contract's own candles, for the option panel of the chart
            if chart_from and t["day"] >= chart_from:
                _c, _ec, _xc, eo, xo = got
                if eo or xo:
                    option_chart.setdefault(t["day"], {})[key] = {
                        "e": {m: [round(x, 2) for x in v] for m, v in (eo or {}).items()
                              if m >= CHART_OPT_ENTRY_FROM},
                        "x": {m: [round(x, 2) for x in v] for m, v in (xo or {}).items()}}
        h = t["legs"][DEFAULT_INSTRUMENT]["exits"][DEFAULT_EXIT]
        priced += h.get("prem_pct") is not None
    # The capital figure for the CURRENT signal comes from the broker itself.
    open_now = [t for t in priceable if t["status"].startswith("open")]
    if open_now and not offline and token:
        async with httpx.AsyncClient() as client:
            for t in open_now:
                for key, kind, off, _ in INSTRUMENTS:
                    info = t["legs"][key]["info"]
                    if info.get("instrument_key"):
                        m = await live_margin(client, token, info["instrument_key"], kind, LOT_SIZE)
                        if m is not None:
                            info["capital_rs"], info["capital_source"] = m, "broker"
        print(f"  live margin fetched for {len(open_now)} open signal(s)")
    return priced, sum(1 for t in trades if t["status"] == "closed"), option_chart


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _r(v, d=4):
    return "" if v is None else f"{v:.{d}f}"


def write_signals_csv(signals, official, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "decision", "day_open", "close_1514", "move_pct", "day_high",
                    "day_low", "close_location", "official_close", "hold_reason"])
        for x in signals:
            w.writerow([x["day"], x["decision"], _r(x["day_open"], 2), _r(x["close"], 2),
                        _r(x["move_pct"]), _r(x["day_high"], 2), _r(x["day_low"], 2),
                        _r(x["loc_day"]), _r(official.get(x["day"], {}).get("c"), 2),
                        x["hold_reason"]])
    print(f"  signals -> {path}")


def write_trades_csv(trades, path):
    inst_cols = [f"net_rs_{k}_{DEFAULT_EXIT}" for k, *_ in INSTRUMENTS]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "decision", "move_pct", "entry_spot", "exit_day", "exit_time",
                    "exit_spot", "spot_pts", "spot_pct", "status", "instrument", "exit_rule",
                    "strike", "symbol", "expiry", "dte", "entry_px", "entry_minute", "exit_px",
                    "exit_minute", "prem_pts", "prem_pct", "pnl_rs", "costs_rs", "net_rs",
                    "capital_rs", "capital_source", "entry_px_worst", "exit_px_worst",
                    "exit_minute_worst", "pnl_rs_worst", "net_rs_worst", "note"] + inst_cols)
        for t in trades:
            lg = t["legs"].get(DEFAULT_INSTRUMENT) or {}
            h = {**lg.get("info", {}), **lg.get("exits", {}).get(DEFAULT_EXIT, {})}
            w.writerow([t["day"], t["decision"], _r(t["move_pct"]), _r(t["entry_spot"], 2),
                        t["exit_day"] or "", t["exit_time"] or "", _r(t["exit_spot"], 2),
                        _r(t["spot_pts"], 2), _r(t["spot_pct"]), t["status"],
                        DEFAULT_INSTRUMENT if h else "", DEFAULT_EXIT if h else "",
                        h.get("rel_strike") or "", h.get("symbol") or "", h.get("expiry") or "",
                        "" if h.get("dte") is None else h["dte"], _r(h.get("entry_px"), 2),
                        h.get("entry_minute") or "", _r(h.get("exit_px"), 2),
                        h.get("exit_minute") or "", _r(h.get("prem_pts"), 2),
                        _r(h.get("prem_pct")), _r(h.get("pnl_rs"), 2), _r(h.get("costs_rs"), 2),
                        _r(h.get("net_rs"), 2), _r(h.get("capital_rs"), 0),
                        h.get("capital_source") or "", _r(h.get("entry_px_w"), 2),
                        _r(h.get("exit_px_w"), 2), h.get("exit_minute_w") or "",
                        _r(h.get("pnl_rs_w"), 2), _r(h.get("net_rs_w"), 2), h.get("reason") or ""]
                       + [_r(((t["legs"].get(k) or {}).get("exits", {}).get(DEFAULT_EXIT, {}) or {}).get("net_rs"), 2)
                          for k, *_ in INSTRUMENTS])
    print(f"  trades  -> {path}")


def leg_book(trades, inst, ex, fill=DEFAULT_FILL):
    sfx = "" if fill == "close" else "_w"
    legs = [t["legs"][inst]["exits"][ex] for t in trades if t["status"] == "closed" and t.get("legs")]
    rs = [l["net_rs" + sfx] for l in legs if l.get("net_rs" + sfx) is not None]          # NET of costs
    gross = [l["pnl_rs" + sfx] for l in legs if l.get("pnl_rs" + sfx) is not None]
    costs = [l["costs_rs" + sfx] for l in legs if l.get("costs_rs" + sfx) is not None]
    pct = [l["prem_pct" + sfx] for l in legs if l.get("prem_pct" + sfx) is not None]
    gw, gl = sum(x for x in rs if x > 0), -sum(x for x in rs if x < 0)
    return {"n": len(rs), "wins": sum(1 for x in rs if x > 0), "losses": sum(1 for x in rs if x < 0),
            "win_rate": (sum(1 for x in rs if x > 0) / len(rs) * 100) if rs else None,
            "rs": sum(rs) if rs else None, "gross": sum(gross) if gross else None,
            "costs": sum(costs) if costs else None, "pf": (gw / gl) if gl else None,
            "mean_pct": statistics.fmean(pct) if pct else None,
            "worst_rs": min(rs) if rs else None, "best_rs": max(rs) if rs else None}


def verdict_text(trades, signals, label, fill=DEFAULT_FILL) -> str:
    counts = Counter(x["decision"] for x in signals)
    closed = [t for t in trades if t["status"] == "closed"]
    h = leg_book(trades, DEFAULT_INSTRUMENT, DEFAULT_EXIT, fill)
    sp = stats([t["spot_pct"] for t in closed])
    parts = [f"{label}: {len(signals)} sessions, {counts.get('BUY', 0)} BUY, "
             f"{counts.get('SELL', 0)} SELL, {counts.get('HOLD', 0)} HOLD."]
    if sp["n"]:
        parts.append(f"Spot, {sp['n']} closed nights: mean {sp['mean']:+.3f}%, win {sp['win_rate']:.1f}%, "
                     f"t {sp['t']:+.2f}." if sp["t"] is not None else "")
    if h["n"]:
        parts.append(f"{INSTRUMENT_BY_KEY[DEFAULT_INSTRUMENT][2]}, exit {EXIT_BY_KEY[DEFAULT_EXIT][0]}, "
                     f"{fill} fills: "
                     f"{h['wins']} wins / {h['losses']} losses ({h['win_rate']:.1f}%) net of costs, "
                     f"gross Rs {h['gross']:,.0f} less brokerage and taxes Rs {h['costs']:,.0f} = "
                     f"net Rs {h['rs']:,.0f} on one lot, profit factor {h['pf']:.2f} on net, "
                     f"worst night Rs {h['worst_rs']:,.0f}.")
    return " ".join(p for p in parts if p)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EOD trend signal v2</title>
<style>
  :root{color-scheme:light;--surface:#fcfcfb;--page:#f4f4f1;--ink:#0b0b0b;--ink2:#52514e;--muted:#8b8983;
    --grid:#e3e2db;--border:rgba(11,11,11,.10);--up:#128a5a;--down:#d0453f;--accent:#2a78d6;--warn:#b8860b;--zone:#7a5cd0;--chip:#eceae3}
  @media (prefers-color-scheme: dark){:root:not([data-theme="light"]){color-scheme:dark;--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
    --grid:#2c2c2a;--border:rgba(255,255,255,.10);--up:#3ecf8e;--down:#e66767;--accent:#5b9df0;--warn:#e0b341;--zone:#a68bf0;--chip:#262624}}
  :root[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;
    --grid:#2c2c2a;--border:rgba(255,255,255,.10);--up:#3ecf8e;--down:#e66767;--accent:#5b9df0;--warn:#e0b341;--zone:#a68bf0;--chip:#262624}
  *{box-sizing:border-box}
  body{margin:0;background:var(--page);color:var(--ink);font:13px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
  .wrap{max-width:1500px;margin:0 auto;padding:20px 16px 80px}
  h1{font-size:20px;margin:0 0 4px}
  h2{font-size:15px;margin:28px 0 10px;border-bottom:1px solid var(--border);padding-bottom:6px}
  .sub{color:var(--muted);font-size:12px;margin-bottom:14px}
  .note{background:var(--chip);border-left:3px solid var(--accent);border-radius:0 6px 6px 0;padding:10px 14px;margin:10px 0;color:var(--muted);font-size:12px}
  .note b{color:var(--ink)} .warn{border-left-color:var(--warn)}
  .controls{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;margin-bottom:14px}
  .ctl{display:flex;flex-direction:column;gap:4px}
  .ctl label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
  select,button{background:var(--chip);color:var(--ink);border:1px solid var(--border);border-radius:6px;padding:6px 10px;font:inherit}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
  .card{background:var(--chip);border:1px solid var(--border);border-radius:8px;padding:12px 14px}
  .card .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
  .card .v{font-size:20px;font-weight:600;margin-top:3px}
  table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
  th,td{padding:6px 9px;text-align:right;border-bottom:1px solid var(--border);white-space:nowrap}
  th{color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.03em;position:sticky;top:0;background:var(--surface)}
  td.l,th.l{text-align:left} tr:hover td{background:var(--chip)}
  .pos{color:var(--up)} .neg{color:var(--down)} .dimc{color:var(--muted)}
  .scroll{max-height:560px;overflow:auto;border:1px solid var(--border);border-radius:8px}
  svg{display:block;width:100%;height:auto;background:var(--surface);border:1px solid var(--border);border-radius:8px}
  svg.drag{cursor:grabbing}
  .chartbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0}
  .chartbar label{color:var(--muted);font-size:12px;display:flex;gap:5px;align-items:center}
  .pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:10.5px;font-weight:600;white-space:nowrap}
  .pill.buy{background:rgba(18,138,90,.15);color:var(--up)} .pill.sell{background:rgba(208,69,63,.15);color:var(--down)}
  .pill.hold{background:var(--chip);color:var(--muted)} .pill.data{background:rgba(184,134,11,.15);color:var(--warn)}
  #tip{position:fixed;pointer-events:none;display:none;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 9px;font-size:11px;z-index:9;box-shadow:0 4px 16px rgba(0,0,0,.18)}
  .setup{padding:8px 12px;border-radius:6px;margin:0 0 8px;font-size:12.5px;border:1px solid var(--border);background:var(--chip);color:var(--ink2);line-height:1.7}
  .setup.neg{border-left:4px solid var(--down)} .setup.pos{border-left:4px solid var(--up)} .setup.dim{border-left:4px solid var(--muted)}
  .setup b{color:var(--ink)} .setup .r{display:inline-block;min-width:110px;color:var(--muted)}
  td.sel{outline:2px solid var(--accent);outline-offset:-2px;font-weight:600}
  td.cell{cursor:pointer}
  .rule{display:grid;grid-template-columns:150px 1fr;gap:4px 14px;font-size:12.5px} .rule .k{color:var(--muted)} .rule b{color:var(--ink)}
  details{margin-top:28px;border:1px solid var(--border);border-radius:8px;background:var(--surface);padding:0 14px}
  details[open]{padding-bottom:12px} summary{cursor:pointer;padding:12px 0;color:var(--ink2);font-weight:500}
  code{background:var(--chip);padding:0 4px;border-radius:3px;font-size:11.5px}
  ol.steps{margin:0;padding-left:22px;line-height:1.7} ol.steps li{margin-bottom:5px} ol.steps b{color:var(--ink)}
  .exitbox{border-left:3px solid var(--up);background:var(--chip);border-radius:0 6px 6px 0;padding:10px 14px;line-height:1.7;margin-bottom:8px}
  .exitbox.red{border-left-color:var(--down)}
  @media (max-width:900px){.panel[style*="grid"]{grid-template-columns:1fr !important}}
</style>
</head>
<body>
<div class="wrap">
  <h1>EOD trend signal v2 &mdash; the sign of the day, one option six strikes in, bought at 15:20, out on the first calm minute in profit</h1>
  <div class="sub" id="sub"></div>
  <div class="controls">
    <div class="ctl"><label>Window</label><select id="winSel"></select></div>
    <div class="ctl"><label>Instrument</label><select id="instSel"></select></div>
    <div class="ctl"><label>Exit</label><select id="exitSel"></select></div>
    <div class="ctl"><label>Fill</label><select id="fillSel"></select></div>
    <div class="ctl"><label>Extra HOLD filter</label><select id="filtSel"></select></div>
    <div class="sub" id="winNote" style="margin:0;align-self:center"></div>
  </div>
  <div class="note" id="instNote"></div>
  <div class="note warn" id="verdict"></div>

  <h2>Overall</h2>
  <div class="cards" id="cards"></div>
  <div class="chartbar" style="margin-top:12px"><label>Equity curve:
    <select id="eqSel"><option value="pnl_rs">rupees on one lot</option><option value="prem_pct">premium, cumulative %</option><option value="spot_pct">spot, cumulative %</option></select></label></div>
  <svg id="equity" viewBox="0 0 1200 210" preserveAspectRatio="xMidYMid meet"></svg>

  <h2>The matrix &mdash; every instrument against every exit</h2>
  <div class="sub">Each cell, NET of brokerage and taxes: win rate &middot; net rupees on one lot &middot; profit factor &middot; return on the average capital a lot needed. Click a cell to make it the headline above.</div>
  <div class="scroll"><table id="tblMatrix"></table></div>

  <h2>What each extra filter would cost</h2>
  <div class="sub">Each row applies one familiar condition as an additional HOLD rule to the selected window, strike and exit. Read the trade count and the win rate side by side; the selected filter is marked.</div>
  <div class="scroll"><table id="tblFilters"></table></div>

  <h2>Liquidity by strike &mdash; why the default stops at six strikes in</h2>
  <div class="sub">Share of the exit day&rsquo;s one-minute bars in which the contract did not trade at all (high equals low). In such a minute the worst-fill rule has no low to punish, so a deeper strike&rsquo;s better numbers are partly untradeable.</div>
  <div class="scroll"><table id="tblLiq"></table></div>

  <h2>Chart &mdash; the day, the entry, the exit</h2>
  <div class="chartbar">
    <select id="daySel"></select>
    <label><input type="checkbox" id="showRules" checked> day open &rarr; 15:14 close</label>
    <label><input type="checkbox" id="showTrade" checked> entry / exit</label>
    <label><input type="checkbox" id="showQual" checked> mark every qualifying minute</label>
    <button id="zoomFocus">14:30 &rarr; 10:00</button><button id="zoomIn">+</button><button id="zoomOut">&minus;</button><button id="zoomReset">both sessions</button>
    <span class="tag" id="dayTag"></span>
  </div>
  <div id="setupBanner" class="setup dim"></div>
  <svg id="chart" viewBox="0 0 1200 330" preserveAspectRatio="xMidYMid meet"></svg>
  <div id="optHead" class="setup dim" style="margin:10px 0 4px"></div>
  <svg id="ochart" viewBox="0 0 1200 400" preserveAspectRatio="xMidYMid meet"></svg>
  <div id="tip"></div>

  <h3 style="margin:18px 0 4px">Cross-check &mdash; the exit day minute by minute</h3>
  <div class="sub" id="verifySub"></div>
  <div class="chartbar">
    <label><input type="checkbox" id="verifyAll"> every minute of the exit day (otherwise the scan window up to the exit)</label>
    <span class="tag" id="verifyTag"></span>
  </div>
  <div class="scroll" style="max-height:420px"><table id="tblVerify"></table></div>

  <h2>By side</h2><div class="scroll"><table id="tblSide"></table></div>
  <h2>Monthly</h2><div class="scroll"><table id="tblMonth"></table></div>
  <h2>Stability &mdash; halves, the closing-auction split, years</h2><div class="scroll"><table id="tblStab"></table></div>
  <h2>Trades</h2><div class="scroll"><table id="tblTrades"></table></div>
  <h2>Signal log &mdash; every session</h2>
  <div class="chartbar"><label><input type="checkbox" id="onlyFired"> only BUY / SELL</label></div>
  <div class="scroll"><table id="tblLog"></table></div>

  <h2>The rule in plain English</h2>
  <div class="panel" style="display:grid;grid-template-columns:1fr 1fr;gap:18px">
    <div>
      <div style="font-weight:600;margin-bottom:6px">Up to the entry, every trading day</div>
      <ol class="steps" id="steps"></ol>
      <div style="font-weight:600;margin:14px 0 6px">The optional filters, and exactly how each one is calculated</div>
      <ul class="steps" id="filterDefs" style="padding-left:18px"></ul>
    </div>
    <div>
      <div style="font-weight:600;margin-bottom:6px">The exit, next session</div>
      <div id="exitPlain"></div>
      <div style="font-weight:600;margin:14px 0 6px">What this rule does <u>not</u> calculate, and why</div>
      <div class="dimc" style="line-height:1.6;margin-bottom:8px">No volatility, no trend, no moving average, no range ratio, no momentum, no filter on the size of the day&rsquo;s move, no lookback of any length. The only time frame is the one-minute candle, used to build the daily bar and to price the exit minute by minute. Each of v1&rsquo;s seven features and fourteen other filters were measured on this data before v2 was fixed: none raised the win rate on both the six months and the five years, and a minimum move size lowered it. The exit rule and the strike depth are the two things that moved the result, so they are the two things this rule sets.</div>
      <div style="font-weight:600;margin:14px 0 6px">The latest signal, worked through</div>
      <div id="worked" class="setup dim"></div>
    </div>
  </div>

  <details open>
    <summary>Notes &mdash; the rule, the fills, what limits these numbers</summary>
    <div class="panel"><div class="rule" id="rule"></div></div>
    <div class="note" id="fills"></div>
    <div class="note warn" id="limits"></div>
  </details>
</div>

<script>
const DATA = __DATA_JSON__;
const M = DATA.meta;
const $ = id => document.getElementById(id);
const fmt = (v, d = 2) => (v === null || v === undefined) ? '&mdash;'
  : Number(v).toLocaleString('en-IN', {minimumFractionDigits: d, maximumFractionDigits: d});
const sign = v => (v === null || v === undefined) ? 'dimc' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : 'dimc'));
const cell = (v, d = 2, suf = '') => '<td class="' + sign(v) + '">' + fmt(v, d) + (v === null || v === undefined ? '' : suf) + '</td>';
const plain = (v, d = 2, suf = '') => '<td>' + fmt(v, d) + (v === null || v === undefined ? '' : suf) + '</td>';
const pill = dec => '<span class="pill ' + dec.toLowerCase() + '">' + dec + '</span>';
function fill(sel, opts, def) {
  sel.innerHTML = opts.map(o => '<option value="' + o.k + '"' + (o.k === def ? ' selected' : '') + '>' + o.v + '</option>').join('');
}
const FILTER_HOW = {
  none: 'No extra test. No trend, average, volatility or move-size condition is applied; the two prices in step 2 decide alone.',
  move15: 'Day move % = (15:14 close &minus; 09:15 open) &divide; 09:15 open &times; 100. If it is between &minus;0.15% and +0.15%, HOLD.',
  move30: 'Day move % = (15:14 close &minus; 09:15 open) &divide; 09:15 open &times; 100. If it is between &minus;0.30% and +0.30%, HOLD.',
  prev: 'Yesterday&rsquo;s day move = its 15:14 close &minus; its 09:15 open. If its sign is not the same as today&rsquo;s day move, HOLD.',
  ret5: '5-day trend = today&rsquo;s 15:14 close &divide; the 15:14 close 5 sessions ago &minus; 1. If its sign is not the same as today&rsquo;s day move, HOLD.',
  trend30: '30-day trend = today&rsquo;s 15:14 close &divide; the 15:14 close 29 sessions ago &minus; 1 (30 daily bars, today included). If its sign is not the same as today&rsquo;s day move, HOLD.',
  gap: 'Gap = today&rsquo;s 09:15 open &divide; yesterday&rsquo;s 15:14 close &minus; 1. If its sign is not the same as today&rsquo;s day move, HOLD.',
  range: 'Day range % = (day high &minus; day low) &divide; 15:14 close &times; 100, over 09:15&ndash;15:14. 5-day average = the mean of that figure over the previous 5 sessions, today excluded. Ratio = today &divide; average. If the ratio is below 0.69, HOLD.',
  quiet: 'Same day range % and 5-day average as above. If today&rsquo;s ratio is 1.0 or more, HOLD (only quieter-than-average days trade).',
  nofri: 'If today is a Friday, HOLD (no position is held over a weekend).',
};
const FILTERS = [
  {k: 'none', v: 'none - the rule as it is', f: x => true},
  {k: 'move15', v: 'day move at least 0.15%', f: x => Math.abs(x.move_pct) >= 0.15},
  {k: 'move30', v: 'day move at least 0.30%', f: x => Math.abs(x.move_pct) >= 0.30},
  {k: 'prev', v: 'previous day moved the same way', f: x => x.prev_move_pct !== null && x.prev_move_pct * x.move_pct > 0},
  {k: 'ret5', v: '5-day trend agrees with the day', f: x => x.ret5_pct !== null && x.ret5_pct * x.move_pct > 0},
  {k: 'trend30', v: '30-day trend agrees with the day', f: x => x.trend30_pct !== null && x.trend30_pct * x.move_pct > 0},
  {k: 'gap', v: 'opening gap agrees with the day', f: x => x.gap_pct !== null && x.gap_pct * x.move_pct > 0},
  {k: 'range', v: 'day range at least 0.69 x 5-day average', f: x => x.range_ratio5 !== null && x.range_ratio5 >= 0.69},
  {k: 'quiet', v: 'day range below the 5-day average', f: x => x.range_ratio5 !== null && x.range_ratio5 < 1.0},
  {k: 'nofri', v: 'no Friday entries (no weekend hold)', f: x => x.weekday !== 4},
];
let curWin = DATA.default_view, curInst = M.default_instrument, curExit = M.default_exit, curFilt = 'none', curFill = M.default_fill;
const passes = x => x.decision === 'HOLD' || FILTERS.find(f => f.k === curFilt).f(x);
const sigByDay = {}; DATA.signals.forEach(x => sigByDay[x.day] = x);
let V = DATA.views[curWin];
const VS = () => DATA.signals.filter(x => x.day >= V.from).map(x => passes(x) ? x : Object.assign({}, x, {decision: 'HOLD', hold_reason: 'filter: ' + FILTERS.find(f => f.k === curFilt).v, filtered: true}));
const VT = () => DATA.trades.filter(t => t.day >= V.from && passes(sigByDay[t.day]));
fill($('winSel'), Object.keys(DATA.views).map(k => ({k, v: DATA.views[k].label})), curWin);
const shortLab = i => i.label;
fill($('instSel'), M.instruments.map(i => ({k: i.key, v: i.label})), curInst);
fill($('exitSel'), M.exits.map(e => ({k: e.key, v: e.label})), curExit);
fill($('filtSel'), FILTERS.map(f => ({k: f.k, v: f.v})), curFilt);
fill($('fillSel'), M.fills.map(f => ({k: f.key, v: f.label})), curFill);
$('fillSel').onchange = () => { curFill = $('fillSel').value; renderAll(); };
if (M.worst_coverage && M.worst_coverage[0] < M.worst_coverage[1]) {
  const o = $('fillSel').querySelector ? null : null;
  M.fills.forEach(f => { if (f.key === 'worst') f.label += ' (high/low data on ' + M.worst_coverage[0] + ' of ' + M.worst_coverage[1] + ' nights)'; });
  fill($('fillSel'), M.fills.map(f => ({k: f.key, v: f.label})), curFill);
}
const W = ['entry_px', 'exit_px', 'exit_minute', 'prem_pts', 'prem_pct', 'pnl_rs', 'costs_rs', 'net_rs', 'capital_rs', 'line'];
function withFill(l) {
  if (!l || curFill === 'close') return l;
  const o = Object.assign({}, l);
  for (const k of W) o[k] = l[k + '_w'];
  if (l.reason === null && l.net_rs_w === null && l.net_rs !== null) o.reason = 'no open/high/low data for this minute';
  return o;
}
const netOf = (t, i, e) => t.legs[i].exits[e][curFill === 'close' ? 'net_rs' : 'net_rs_w'];
$('filtSel').onchange = () => { curFilt = $('filtSel').value; renderAll(); };
function renderFilters() {
  const base = DATA.trades.filter(t => t.day >= V.from);
  const rows = FILTERS.map(f => {
    const tr = base.filter(t => f.f(sigByDay[t.day]));
    return {f, b: book(tr)};
  });
  const b0 = rows[0].b;
  $('tblFilters').innerHTML = '<thead><tr><th class="l">extra HOLD filter</th><th>trades</th><th>trades removed</th><th>W / L net</th><th>win % net</th><th>vs none</th><th>net &#8377;</th><th>vs none</th><th>PF net</th><th>worst &#8377;</th></tr></thead><tbody>' +
    rows.map(r => '<tr' + (r.f.k === curFilt ? ' style="font-weight:600"' : '') + '><td class="l">' + r.f.v + (r.f.k === curFilt ? ' &#9664;' : '') + '</td><td>' + r.b.rs.n + '</td><td>' + (b0.rs.n - r.b.rs.n) + '</td>' +
      '<td><span class="pos">' + r.b.rs.wins + '</span> / <span class="neg">' + r.b.rs.losses + '</span></td>' + plain(r.b.rs.win, 1, '%') + cell(r.b.rs.win === null ? null : r.b.rs.win - b0.rs.win, 1, ' pts') +
      cell(r.b.rs.total, 0) + cell(r.b.rs.total === null ? null : r.b.rs.total - b0.rs.total, 0) + plain(r.b.rs.pf, 2) + cell(r.b.rs.worst, 0) + '</tr>').join('') + '</tbody>';
}
$('winSel').onchange = () => { curWin = $('winSel').value; V = DATA.views[curWin]; renderAll(); };
$('instSel').onchange = () => { curInst = $('instSel').value; renderAll(); };
$('exitSel').onchange = () => { curExit = $('exitSel').value; renderAll(); };

/* ---------- statistics in the page: every table reads the selected cell ---------- */
const leg = t => (t.legs && t.legs[curInst]) ? withFill(Object.assign({}, t.legs[curInst].info, t.legs[curInst].exits[curExit])) : null;
function stats(v) {
  const n = v.length;
  if (!n) return {n: 0, wins: 0, losses: 0, win: null, mean: null, med: null, pf: null, t: null, worst: null, best: null, total: null};
  const wins = v.filter(x => x > 0).length, losses = v.filter(x => x < 0).length;
  const mean = v.reduce((a, b) => a + b, 0) / n;
  const sd = n > 1 ? Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / (n - 1)) : null;
  const gw = v.filter(x => x > 0).reduce((a, b) => a + b, 0), gl = -v.filter(x => x < 0).reduce((a, b) => a + b, 0);
  const s = [...v].sort((a, b) => a - b);
  return {n, wins, losses, win: wins / n * 100, mean, med: n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2,
          pf: gl ? gw / gl : null, t: sd ? mean / (sd / Math.sqrt(n)) : null, worst: s[0], best: s[n - 1], total: v.reduce((a, b) => a + b, 0)};
}
function book(trades) {
  const closed = trades.filter(t => t.status === 'closed');
  const legs = closed.map(leg).filter(l => l && l.net_rs !== null && l.net_rs !== undefined);
  const capKey = curFill === 'close' ? 'capital_rs' : 'capital_rs_w';
  const caps = closed.map(t => (t.legs && t.legs[curInst]) ? t.legs[curInst].info[capKey] : null).filter(x => x !== null && x !== undefined);
  const capAvg = caps.length ? caps.reduce((a, b) => a + b, 0) / caps.length : null;
  const total = legs.length ? legs.map(l => l.net_rs).reduce((a, b) => a + b, 0) : null;
  const costs = legs.length ? legs.map(l => l.costs_rs).reduce((a, b) => a + b, 0) : null;
  let ws = 0, ls = 0, maxW = 0, maxL = 0;
  for (const l of legs) { if (l.net_rs > 0) { ws++; ls = 0; } else { ls++; ws = 0; } maxW = Math.max(maxW, ws); maxL = Math.max(maxL, ls); }
  const wins = legs.map(l => l.net_rs).filter(v => v > 0), losses = legs.map(l => l.net_rs).filter(v => v <= 0);
  return {signals: trades.length, closed: closed.length, priced: legs.length, maxWinStreak: maxW, maxLossStreak: maxL,
          avgWin: wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : null, avgLoss: losses.length ? losses.reduce((a, b) => a + b, 0) / losses.length : null,
          spot: stats(closed.map(t => t.spot_pct)), rs: stats(legs.map(l => l.net_rs)), gross: stats(legs.map(l => l.pnl_rs)),
          costs, pct: stats(legs.map(l => l.prem_pct)),
          capAvg, capMax: caps.length ? Math.max(...caps) : null, capMin: caps.length ? Math.min(...caps) : null,
          roc: (capAvg && total !== null) ? total / capAvg * 100 : null};
}
function grouped(trades, keyFn) {
  const g = {};
  for (const t of trades) (g[keyFn(t)] = g[keyFn(t)] || []).push(t);
  return Object.keys(g).sort().map(k => ({key: k, ...book(g[k])}));
}

function latestCap() {
  const tr = VT().filter(t => t.legs && t.legs[curInst]);
  if (!tr.length) return null;
  const l = leg(tr[tr.length - 1]);
  if (!l || l.capital_rs === null || l.capital_rs === undefined) return null;
  return '&#8377;' + fmt(l.capital_rs, 0) + ' <span class="dimc" style="font-size:12px">' + tr[tr.length - 1].day + ', ' + (l.capital_source === 'broker' ? 'broker SPAN+exposure' : 'estimate') + '</span>';
}
function instNote() {
  const i = M.instruments.find(x => x.key === curInst), n = i.key.match(/\d+/) ? Number(i.key.match(/\d+/)[0]) / 50 : 0;
  const buyDay = 'buy the CALL at ' + (n ? 'ATM&minus;' + n : 'ATM');
  const sellDay = 'buy the PUT at ' + (n ? 'ATM+' + n : 'ATM');
  const lq = (M.liquidity || []).find(x => x.key === i.key);
  $('instNote').innerHTML = '<b>' + i.label + ':</b> on a <b class="pos">BUY</b> day ' + buyDay + '; on a <b class="neg">SELL</b> day ' + sellDay +
    '. One strike = 50 points. The trades table shows each night&rsquo;s exact strike and contract.' +
    (lq && lq.flat_day !== null ? ' Untraded minutes on the exit day at this strike: <b>' + fmt(lq.flat_day, 1) + '%</b>.' : '');
}
function renderSteps() {
  const inst = M.instruments.find(i => i.key === curInst), ex = M.exits.find(e => e.key === curExit);
  const n = inst.key.match(/\d+/) ? Number(inst.key.match(/\d+/)[0]) / 50 : 0;
  const strikeTxt = n ? 'the strike <b>' + n + ' steps in the money</b>: on a BUY the call ' + n + ' strikes below the ATM (ATM&minus;' + n + '), on a SELL the put ' + n + ' strikes above it (ATM+' + n + '). Strikes are 50 points apart, so that is ' + (n * 50) + ' points in.'
                       : 'the <b>ATM strike</b>: on a BUY the call at the ATM, on a SELL the put at the ATM.';
  $('steps').innerHTML = [
    '<b>Wait for the 15:14 candle to finish.</b> Nothing from 15:15 onward is used for any decision.',
    '<b>Take two prices from today:</b> the open of the 09:15 candle and the close of the 15:14 candle. These two numbers are the only inputs to the decision.',
    '<b>Check the data.</b> All 360 one-minute candles from 09:15 to 15:14 must be there, none repeated, none with impossible prices. If anything is missing or broken: <span class="pill hold">HOLD</span>, no trade today.',
    '<b>Compare the two prices.</b> 15:14 close <i>above</i> the 09:15 open = up day = <span class="pill buy">BUY</span> (you will buy a CALL). Below = down day = <span class="pill sell">SELL</span> (you will buy a PUT). Exactly equal: HOLD. There is no minimum size: one rupee up is a BUY.',
    (curFilt === 'none' ? '<b>Extra filter: none.</b> ' + FILTER_HOW.none + ' The selector at the top can add one; the cost table shows what each does.'
                        : '<b>Extra filter, ' + FILTERS.find(f => f.k === curFilt).v + ':</b> ' + FILTER_HOW[curFilt] + ' Otherwise carry on.'),
    '<b>Find the ATM strike.</b> Round the 15:14 close to the nearest 50. A close of 23,341 gives an ATM of 23,350.',
    '<b>Pick the contract:</b> ' + strikeTxt,
    '<b>Pick the expiry:</b> the nearest weekly expiry that falls <i>after tomorrow</i>. If tomorrow is an expiry day, take the following week, so the position is never held into an expiry morning.',
    '<b>Buy one lot in the ' + M.entry_hhmm + ' minute</b> (any minute from 15:15 to 15:25 tests the same; the last minute is avoided because its range is the widest of the afternoon)' + (curFill === 'worst' ? ', and assume you paid the <b>highest price of that minute</b>.' : ', at its closing price.') + ' The capital needed is that premium &times; ' + M.lot_size + ', shown per trade below.',
    '<b>Tomorrow, run the exit on the right</b> &mdash; starting at 09:30, never in the first fifteen minutes, whose candles are three to nine times wider than the rest of the day. One trade a session, a call or a put, never both, never a sold option.',
  ].map(x => '<li>' + x + '</li>').join('');
  $('filterDefs').innerHTML = FILTERS.filter(f => f.k !== 'none').map(f => '<li' + (f.k === curFilt ? ' style="font-weight:600"' : '') + '><b>' + f.v + ':</b> ' + FILTER_HOW[f.k] + '</li>').join('');
  const lims = ex.label.match(/\d\d:\d\d/g); const lim = lims[lims.length - 1];
  let txt;
  if (ex.trigger === 'low' && ex.key.startsWith('low')) {
    const extra = ex.label.includes('+1%') ? ' plus 1% of the premium' : '';
    txt =
    '<ol class="steps" style="margin-bottom:8px">' +
    '<li><b>Work out your line.</b> Entry price + brokerage and taxes' + extra + '. Costs are about 1.2 points on one lot, so the line sits just above what you paid. Selling above the line is a real profit; below it is not.</li>' +
    '<li><b>Do nothing until ' + ex.start + '.</b> The early candles are wild: about 45 points of range at 09:15, 19 at 09:16, 10 until 09:30. Selling inside them means selling near the bottom of a big swing.</li>' +
    '<li><b>From ' + ex.start + ', after each one-minute candle finishes, ask one question:</b> was the <b>lowest</b> price of that minute above the line?</li>' +
    '<li><b>Yes &rarr; sell now.</b> Even the worst price traded in that minute was above your line, so the sale is a profit whatever fill you get. The trade is over.</li>' +
    '<li><b>No &rarr; wait one more minute</b> and ask again.</li>' +
    '<li><b>Nothing by ' + lim + ' &rarr; sell in the ' + lim + ' minute</b> at whatever the price is. That is the losing night. There is no stop-loss before it; every stop tested cut nights that were about to recover.</li>' +
    '</ol>' +
    '<div class="dimc" style="line-height:1.6">Why the low and not the close: a minute can close above your line and still have traded below it. Asking the <i>low</i> to clear the line makes the sale profitable under your own worst-fill rule, by construction.</div>';
  }
  else if (ex.thr === undefined && !ex.label.includes('first')) txt = '<div class="exitbox">Sell in the <b>next session&rsquo;s ' + lim + ' candle</b>' + (curFill === 'worst' ? ', assumed filled at that minute&rsquo;s <b>low</b>' : ', at its close') + ', whatever the price. Win or lose, the trade is over.</div>';
  else if (ex.key === '09:15') txt = '<div class="exitbox">Sell in the <b>next session&rsquo;s 09:15 candle</b>' + (curFill === 'worst' ? ', assumed filled at that minute&rsquo;s <b>low</b>' : ', at its close') + ', whatever the price. One minute after the open, win or lose, the trade is over.</div>';
  else {
    const thr = ex.label.includes('+') ? ex.label.match(/\+(\d+)%/)[1] : null;
    txt = '<div class="exitbox">From <b>' + ex.start + '</b> tomorrow, look at the option&rsquo;s price <b>one minute at a time</b>. The first minute whose close is ' +
      (thr ? '<b>at least ' + thr + '% above</b> what you paid' : '<b>above what you paid by more than the round-trip costs</b> (about 1.2 points of premium, so the sale is a profit after brokerage and taxes, not just a green tick)') + ', <b>sell there</b>' +
      (curFill === 'worst' ? ' &mdash; and assume you received the <b>lowest price of that minute</b>. When that low is below your entry, the night counts as a loss even though the close triggered the exit.' : '') + '. That is a win, and the trade is over.</div>' +
      '<div class="exitbox red">If that never happens by <b>' + lim + '</b>, sell at the <b>' + lim + ' close</b> for whatever it is. That is the losing case.</div>' +
      '<div class="dimc" style="line-height:1.6">There is no target and no stop. Wins are taken at the first sign of profit, so they are small and frequent; losses are the sessions that never turned, so they are fewer and larger. That is why the win rate is high and the profit factor is what it is.</div>';
  }
  $('exitPlain').innerHTML = txt;
  const tr = VT().filter(t => t.legs && t.legs[curInst]);
  if (!tr.length) { $('worked').textContent = 'no trade in this window'; return; }
  const t = tr[tr.length - 1], sig = DATA.signals.find(x => x.day === t.day), l = leg(t) || {};
  const atm = Math.round(sig.close / 50) * 50;
  let w = '<b>' + t.day + '.</b> 09:15 open <b>' + fmt(sig.day_open, 2) + '</b>, 15:14 close <b>' + fmt(sig.close, 2) + '</b> &rarr; the close is ' + (t.decision === 'BUY' ? 'above' : 'below') + ' the open &rarr; ' + pill(t.decision) +
    '.<br>ATM = ' + fmt(atm, 0) + (n ? ' &rarr; ' + (t.decision === 'BUY' ? 'call ' + n + ' strikes below = <b>' + fmt(atm - n * 50, 0) + ' CE</b>' : 'put ' + n + ' strikes above = <b>' + fmt(atm + n * 50, 0) + ' PE</b>') : ' &rarr; <b>' + fmt(atm, 0) + (t.decision === 'BUY' ? ' CE' : ' PE') + '</b>') +
    (l.symbol ? ', expiry ' + l.expiry + ' (' + l.dte + ' days away).<br>Bought at ' + M.entry_hhmm + ' for <b>' + fmt(l.entry_px, 2) + '</b>, capital &#8377;' + fmt(l.capital_rs, 0) + ' for one lot.' : '.');
  if (t.status === 'closed' && l.exit_px !== null && l.exit_px !== undefined)
    w += '<br>Next session: ' + (l.exit_minute === lim && ex.key !== '09:15' && l.net_rs <= 0 ? 'never traded far enough above ' + fmt(l.entry_px, 2) + ' to cover costs, so sold at the ' + lim + ' close' : 'sold at <b>' + l.exit_minute + '</b>') + ' for <b>' + fmt(l.exit_px, 2) + '</b> = <b class="' + sign(l.net_rs) + '">' + (l.prem_pts >= 0 ? '+' : '') + fmt(l.prem_pts, 2) + ' points, &#8377;' + fmt(l.pnl_rs, 0) + ' gross, &#8377;' + fmt(l.net_rs, 0) + ' net of costs</b>.';
  else w += '<br>Still open: the exit runs on the next session.';
  function walkTable(lg, label) {
    const wk = lg.walk;
    if (!wk || !wk.rows || !wk.rows.length) return '';
    return '<div style="margin-top:10px;font-weight:600">' + label + ' (your line: ' + fmt(wk.line, 2) + ' = entry ' + fmt(lg.entry_px, 2) + ' + costs)</div>' +
      '<table style="width:auto;margin-top:4px"><thead><tr><th class="l">minute</th><th>lowest price</th><th>highest price</th><th class="l">low above ' + fmt(wk.line, 2) + '?</th></tr></thead><tbody>' +
      wk.rows.map((r, i) => '<tr' + (r[3] ? ' style="font-weight:600"' : '') + '><td class="l">' + r[0] + '</td>' + plain(r[1], 2) + plain(r[2], 2) +
        '<td class="l">' + (r[3] ? '<span class="pos">yes &rarr; sell here at ' + fmt(r[1], 2) + '</span>' : '<span class="dimc">no, wait</span>') + '</td></tr>' +
        (i === 11 && wk.n > 13 ? '<tr><td class="l dimc" colspan="4">&hellip; ' + (wk.n - 13) + ' more minutes, none qualified &hellip;</td></tr>' : '')).join('') +
      '</tbody></table>' +
      (wk.rows[wk.rows.length - 1][3] ? '' : '<div class="dimc" style="margin-top:4px">No minute qualified by ' + wk.limit + ', so the position was sold in the ' + wk.limit + ' minute: the losing case.</div>');
  }
  if (t.status === 'closed') w += walkTable(l, 'The same night, minute by minute');
  else {
    const closedTr = tr.filter(x => x.status === 'closed');
    if (closedTr.length) { const tc = closedTr[closedTr.length - 1], lc = leg(tc) || {}; w += walkTable(lc, 'Latest closed night, ' + tc.day + ' &rarr; ' + tc.exit_day + ', minute by minute'); }
  }
  $('worked').className = 'setup ' + (t.decision === 'BUY' ? 'pos' : 'neg');
  $('worked').innerHTML = w;
}
function renderAll() {
  instNote(); renderSteps(); renderFilters();
  const instLab = M.instruments.find(i => i.key === curInst).label, exitLab = M.exits.find(e => e.key === curExit).label;
  $('sub').innerHTML = V.sessions + ' sessions &nbsp;' + V.from + ' &rarr; ' + V.to +
    ' &nbsp;&middot;&nbsp; decision at 15:14, entry ' + M.entry_hhmm + ', exit next session from 09:30 on the first minute in profit after costs' +
    ' &nbsp;&middot;&nbsp; headline: <b>' + instLab + '</b>, exit <b>' + exitLab + '</b>, fills <b>' + curFill + '</b>' + (curFilt !== 'none' ? ', extra HOLD filter <b>' + FILTERS.find(f => f.k === curFilt).v + '</b>' : '') +
    ' &nbsp;&middot;&nbsp; expiry: nearest after the exit day &nbsp;&middot;&nbsp; generated ' + M.generated;
  $('winNote').innerHTML = curWin === 'cas'
    ? 'The rule is meant for the market after the closing auction, so this is the default view. ' + V.sessions + ' sessions is a very small sample.'
    : (curWin === '6m' ? 'The house default window, the last 6 months: ' + V.sessions + ' sessions from ' + V.from + '.'
       : 'Everything loaded: ' + V.sessions + ' sessions from ' + V.from + '.');
  const b = book(VT());
  const counts = {BUY: 0, SELL: 0, HOLD: 0};
  VS().forEach(x => counts[x.decision]++);
  $('verdict').innerHTML = '<b>' + V.label + '.</b> ' + counts.BUY + ' BUY, ' + counts.SELL + ' SELL, ' + counts.HOLD + ' HOLD over ' + V.sessions + ' sessions. ' +
    (b.rs.n ? '<b>' + instLab + ', exit ' + exitLab + ':</b> ' + b.rs.wins + ' wins / ' + b.rs.losses + ' losses (' + fmt(b.rs.win, 1) + '%) net of costs; gross Rs ' + fmt(b.gross.total, 0) +
      ' less brokerage and taxes Rs ' + fmt(b.costs, 0) + ' = <b>net Rs ' + fmt(b.rs.total, 0) + '</b> on one lot, profit factor ' + fmt(b.rs.pf, 2) + ' on net, mean ' + fmt(b.pct.mean, 2) + '% of premium gross, worst night Rs ' + fmt(b.rs.worst, 0) + ' net. ' : '') +
    (b.spot.n ? 'On spot the same nights: ' + fmt(b.spot.win, 1) + '% win, mean ' + fmt(b.spot.mean, 3) + '%, t ' + fmt(b.spot.t, 2) + '.' : '') +
    '<br><br><b>The signal over 2022-01 &rarr; 2026-09 (spot, recorded from the study):</b> ' + M.wide_signal;
  const rowHtml = (title, note, cards) => '<div style="grid-column:1/-1;margin-top:6px"><span style="font-weight:600">' + title + '</span> <span class="dimc">' + note + '</span></div>' +
    cards.map(c => '<div class="card"><div class="k">' + c[0] + '</div><div class="v ' + c[2] + '">' + (c[1] === null ? '&mdash;' : c[1]) + '</div></div>').join('');
  const signalsRow = [
    ['sessions', V.sessions, ''],
    ['BUY / SELL / HOLD', counts.BUY + ' / ' + counts.SELL + ' / ' + counts.HOLD, ''],
    ['closed nights', b.closed + (b.priced < b.closed ? ' <span class="dimc">(' + b.priced + ' priced)</span>' : ''), ''],
    ['open now', VT().filter(t => t.status.startsWith('open')).length, ''],
  ];
  const resultRow = [
    ['wins / losses', b.rs.n ? '<span class="pos">' + b.rs.wins + '</span> / <span class="neg">' + b.rs.losses + '</span>' : null, ''],
    ['win rate', b.rs.win === null ? null : fmt(b.rs.win, 1) + '%', sign(b.rs.win === null ? null : b.rs.win - 50)],
    ['gross', b.gross.total === null ? null : '&#8377;' + fmt(b.gross.total, 0), sign(b.gross.total)],
    ['brokerage &amp; taxes', b.costs === null ? null : '&#8377;' + fmt(b.costs, 0), 'neg'],
    ['net, after costs', b.rs.total === null ? null : '&#8377;' + fmt(b.rs.total, 0), sign(b.rs.total)],
    ['profit factor', b.rs.pf === null ? null : fmt(b.rs.pf, 2), sign(b.rs.pf === null ? null : b.rs.pf - 1)],
    ['biggest loss, one night', b.rs.worst === null ? null : '&#8377;' + fmt(b.rs.worst, 0), 'neg'],
    ['biggest win, one night', b.rs.best === null ? null : '&#8377;' + fmt(b.rs.best, 0), 'pos'],
    ['average win per trade', b.avgWin === null ? null : '&#8377;' + fmt(b.avgWin, 0), 'pos'],
    ['average loss per trade', b.avgLoss === null ? null : '&#8377;' + fmt(b.avgLoss, 0), 'neg'],
    ['longest winning streak', b.rs.n ? b.maxWinStreak + ' nights' : null, 'pos'],
    ['longest losing streak', b.rs.n ? b.maxLossStreak + ' nights' : null, 'neg'],
    ['net earned per &#8377; of capital', b.roc === null ? null : fmt(b.roc, 1) + '%', sign(b.roc)],
  ];
  const capitalRow = [
    ['average capital per lot', b.capAvg === null ? null : '&#8377;' + fmt(b.capAvg, 0), ''],
    ['latest 1 lot cost', latestCap(), ''],
  ];
  $('cards').innerHTML =
    rowHtml('Signals', 'the same for every strike and exit', signalsRow) +
    rowHtml('Result', 'for the selected strike, exit and fill; all figures net of brokerage and taxes', resultRow) +
    rowHtml('Capital', 'the premium you pay &times; ' + M.lot_size + '. It depends only on the strike you buy and the price at entry; changing the exit cannot change it. A bought option cannot lose more than this.', capitalRow);
  drawEquity();
  renderMatrix();
  bookTable('tblSide', 'side', ['ALL', 'BUY', 'SELL'].map(k => ({key: k, ...book(k === 'ALL' ? VT() : VT().filter(t => t.decision === k))})), k => k === 'ALL' ? 'all' : pill(k));
  bookTable('tblMonth', 'month', grouped(VT(), t => t.day.slice(0, 7)));
  const closed = VT().filter(t => t.status === 'closed'), h = Math.floor(closed.length / 2);
  const stab = closed.length >= 4 ? [{key: 'first half (' + closed[0].day + ' ...)', ...book(closed.slice(0, h))}, {key: 'second half (... ' + closed[closed.length - 1].day + ')', ...book(closed.slice(h))}] : [];
  const cas = grouped(VT(), t => t.day < M.cas_date ? 'before ' + M.cas_date + ' (continuous close)' : 'from ' + M.cas_date + ' (closing auction)');
  bookTable('tblStab', 'slice', stab.concat(cas.length > 1 ? cas : []).concat(grouped(VT(), t => t.day.slice(0, 4))));
  renderTrades(); renderLog(); fillDays(); renderLiq();
}
function renderLiq() {
  $('tblLiq').innerHTML = '<thead><tr><th class="l">strike</th><th>trades</th><th>untraded minutes, whole day</th><th>untraded minutes, 09:30-15:14</th></tr></thead><tbody>' +
    M.liquidity.map(r => '<tr' + (r.key === curInst ? ' style="font-weight:600"' : '') + '><td class="l">' + r.label + (r.key === curInst ? ' &#9664;' : '') + '</td><td>' + r.n + '</td>' +
      plain(r.flat_day, 1, '%') + plain(r.flat_scan, 1, '%') + '</tr>').join('') + '</tbody>';
}

const BOOK_HEAD = '<th>signals</th><th>closed</th><th>W / L net</th><th>win % net</th><th>gross &#8377;</th><th>costs &#8377;</th><th>net &#8377;</th><th>PF net</th><th>mean % prem</th><th>median %</th><th>worst &#8377;</th><th>best &#8377;</th><th>spot win %</th><th>spot mean %</th><th>spot t</th>';
function bookRow(b) {
  return '<td>' + b.signals + '</td><td>' + b.closed + '</td><td><span class="pos">' + b.rs.wins + '</span> / <span class="neg">' + b.rs.losses + '</span></td>' +
    plain(b.rs.win, 1, '%') + cell(b.gross.total, 0) + cell(b.costs === null ? null : -b.costs, 0) + cell(b.rs.total, 0) + plain(b.rs.pf, 2) + cell(b.pct.mean, 2, '%') + cell(b.pct.med, 2, '%') + cell(b.rs.worst, 0) + cell(b.rs.best, 0) +
    plain(b.spot.win, 1, '%') + cell(b.spot.mean, 3, '%') + cell(b.spot.t, 2);
}
function bookTable(id, label, rows, keyFmt) {
  $(id).innerHTML = '<thead><tr><th class="l">' + label + '</th>' + BOOK_HEAD + '</tr></thead><tbody>' +
    rows.map(r => '<tr><td class="l">' + (keyFmt ? keyFmt(r.key) : r.key) + '</td>' + bookRow(r) + '</tr>').join('') + '</tbody>';
}

function renderMatrix() {
  const closed = VT().filter(t => t.status === 'closed' && t.legs);
  let h = '<thead><tr><th class="l">instrument</th>' + M.exits.map(e => '<th>' + e.label + '</th>').join('') + '</tr></thead><tbody>';
  for (const i of M.instruments) {
    h += '<tr><td class="l" title="' + i.label + '">' + shortLab(i) + '</td>';
    for (const e of M.exits) {
      const rs = closed.map(t => netOf(t, i.key, e.key)).filter(x => x !== null && x !== undefined);
      const caps = closed.map(t => t.legs[i.key].info[curFill === 'close' ? 'capital_rs' : 'capital_rs_w']).filter(x => x !== null && x !== undefined);
      const capAvg = caps.length ? caps.reduce((a, b) => a + b, 0) / caps.length : null;
      const s = stats(rs);
      const selected = i.key === curInst && e.key === curExit;
      h += '<td class="cell' + (selected ? ' sel' : '') + '" data-i="' + i.key + '" data-e="' + e.key + '">' +
        (s.n ? '<span class="' + sign(s.win - 50) + '">' + fmt(s.win, 1) + '%</span> &middot; <span class="' + sign(s.total) + '">&#8377;' + fmt(s.total, 0) + '</span> &middot; ' + fmt(s.pf, 2) +
          (capAvg ? ' &middot; <span class="dimc">' + fmt(s.total / capAvg * 100, 1) + '% on &#8377;' + fmt(capAvg / 1000, 0) + 'k</span>' : '') : '&mdash;') + '</td>';
    }
    h += '</tr>';
  }
  $('tblMatrix').innerHTML = h + '</tbody>';
  $('tblMatrix').querySelectorAll('td.cell').forEach(td => td.onclick = () => {
    curInst = td.dataset.i; curExit = td.dataset.e; $('instSel').value = curInst; $('exitSel').value = curExit; renderAll();
  });
}

function drawEquity() {
  const key = $('eqSel').value, el = $('equity');
  const rows = VT().filter(t => t.status === 'closed').map(t => ({d: t.day, v: key === 'spot_pct' ? t.spot_pct : (leg(t) ? leg(t)[key] : null)})).filter(r => r.v !== null && r.v !== undefined);
  if (rows.length < 2) { el.innerHTML = '<text x="20" y="30" fill="var(--muted)" font-size="12">fewer than two data points</text>'; return; }
  let cum = 0; const pts = rows.map(r => { cum += r.v; return {d: r.d, v: cum}; });
  const W2 = 1200, H2 = 210, L = 74, R = 16, T = 14, B = 26;
  const lo = Math.min(0, ...pts.map(p => p.v)), hi = Math.max(0, ...pts.map(p => p.v)), pad = (hi - lo) * 0.08 || 1;
  const X = i => L + i / (pts.length - 1) * (W2 - L - R), Y = v => T + (hi + pad - v) / (hi - lo + 2 * pad) * (H2 - T - B);
  const dec = key === 'pnl_rs' ? 0 : 2;
  let g = '';
  for (let k = 0; k <= 4; k++) { const v = lo - pad + (hi - lo + 2 * pad) * k / 4;
    g += '<line x1="' + L + '" y1="' + Y(v) + '" x2="' + (W2 - R) + '" y2="' + Y(v) + '" stroke="var(--grid)"/><text x="' + (L - 6) + '" y="' + (Y(v) + 3) + '" fill="var(--muted)" font-size="10" text-anchor="end">' + fmt(v, dec) + '</text>'; }
  g += '<line x1="' + L + '" y1="' + Y(0) + '" x2="' + (W2 - R) + '" y2="' + Y(0) + '" stroke="var(--ink2)" stroke-width="1.2" stroke-dasharray="4 3"/>';
  const d = pts.map((p, i) => (i ? 'L' : 'M') + X(i) + ' ' + Y(p.v)).join(' '), last = pts[pts.length - 1].v, col = last >= 0 ? 'var(--up)' : 'var(--down)';
  g += '<path d="' + d + ' L' + X(pts.length - 1) + ' ' + Y(0) + ' L' + X(0) + ' ' + Y(0) + ' Z" fill="' + col + '" opacity="0.10"/><path d="' + d + '" fill="none" stroke="' + col + '" stroke-width="1.8"/>';
  const step = Math.max(1, Math.round(pts.length / 8));
  for (let i = 0; i < pts.length; i += step) g += '<text x="' + X(i) + '" y="' + (H2 - 8) + '" fill="var(--muted)" font-size="10" text-anchor="middle">' + pts[i].d.slice(2) + '</text>';
  g += '<text x="' + (W2 - R) + '" y="' + (Y(last) - 6) + '" fill="' + col + '" font-size="11" text-anchor="end">cumulative ' + fmt(last, dec) + '</text>';
  el.innerHTML = g;
}
$('eqSel').onchange = drawEquity;

function renderTrades() {
  const head = '<tr><th class="l">date</th><th class="l">signal</th><th>day move %</th><th>entry ' + M.entry_hhmm + '</th><th class="l">exit</th><th>exit spot</th><th>spot pts</th><th>spot %</th>' +
    '<th class="l">strike</th><th class="l">contract</th><th>DTE</th><th>entry prem</th><th>exit prem</th><th class="l">exit min</th><th>prem pts</th><th>prem %</th><th>gross &#8377;</th><th>costs &#8377;</th><th>net &#8377;</th><th>capital / lot</th><th class="l">note</th></tr>';
  $('tblTrades').innerHTML = '<thead>' + head + '</thead><tbody>' + VT().map(t => { const l = leg(t) || {};
    return '<tr><td class="l">' + t.day + '</td><td class="l">' + pill(t.decision) + '</td>' + cell(t.move_pct, 3) + plain(t.entry_spot, 2) +
      '<td class="l">' + (t.exit_day ? t.exit_day + ' ' + t.exit_time : '&mdash;') + '</td>' + plain(t.exit_spot, 2) + cell(t.spot_pts, 2) + cell(t.spot_pct, 3, '%') +
      '<td class="l">' + (l.rel_strike || '&mdash;') + '</td><td class="l">' + (l.symbol || '&mdash;') + '</td><td>' + (l.dte === null || l.dte === undefined ? '&mdash;' : l.dte) + '</td>' + plain(l.entry_px, 2) + plain(l.exit_px, 2) +
      '<td class="l dimc">' + (l.exit_minute || '') + '</td>' + cell(l.prem_pts, 2) + cell(l.prem_pct, 2, '%') + cell(l.pnl_rs, 0) + cell(l.costs_rs === null || l.costs_rs === undefined ? null : -l.costs_rs, 0) + cell(l.net_rs, 0) +
      '<td>' + (l.capital_rs === null || l.capital_rs === undefined ? '&mdash;' : fmt(l.capital_rs, 0) + (l.capital_source === 'broker' ? ' <span class="dimc">live</span>' : '')) + '</td>' +
      '<td class="l dimc">' + (t.status !== 'closed' ? t.status : (l.reason || '')) + '</td></tr>'; }).join('') + '</tbody>';
}
function renderLog() {
  const rows = VS().filter(x => !$('onlyFired').checked || x.decision !== 'HOLD');
  $('tblLog').innerHTML = '<thead><tr><th class="l">date</th><th class="l">decision</th><th>09:15 open</th><th>15:14 close</th><th>move %</th><th>day high</th><th>day low</th><th>close location</th><th class="l">reason</th></tr></thead><tbody>' +
    rows.map(x => '<tr><td class="l">' + x.day + '</td><td class="l">' + pill(x.decision) + (x.data_ok ? '' : ' <span class="pill data">data</span>') + (x.filtered ? ' <span class="pill data">filter</span>' : '') + '</td>' +
      plain(x.day_open, 2) + plain(x.close, 2) + cell(x.move_pct, 3, '%') + plain(x.day_high, 2) + plain(x.day_low, 2) + plain(x.loc_day, 3) + '<td class="l dimc">' + (x.hold_reason || '') + '</td></tr>').join('') + '</tbody>';
}
$('onlyFired').onchange = renderLog;

/* ---------- chart ---------- */
/* Two panels over ONE timeline: the index above, the option contract below.
   The timeline is the union of index minutes and option minutes across the
   signal day and the exit day, so the post-auction 15:30-15:39 option minutes
   (the index prints nothing there) still line up.  Both panels share the same
   zoom, pan and tooltip. */
const CW = 1200, CH = 330, PADL = 66, PADR = 16, PADT = 18, PADB = 26;
const OCH = 400, OPADT = 18, OPADB = 26;
const csvg = $('chart'), osvg = $('ochart'), ctip = $('tip');
let chartState = null;
function txt(x, y, t, col, size, anchor) { return '<text x="' + x + '" y="' + y + '" fill="' + (col || 'var(--muted)') + '" font-size="' + (size || 10) + '"' + (anchor ? ' text-anchor="' + anchor + '"' : '') + '>' + t + '</text>'; }
function fillDays() {
  const sel = $('daySel'), keep = sel.value, days = VS().map(x => x.day);
  sel.innerHTML = VS().map(x => '<option value="' + x.day + '">' + x.day + ' · ' + x.decision + '</option>').join('');
  if (days.includes(keep)) sel.value = keep; else { const tr = VT().filter(t => t.status === 'closed'); sel.value = tr.length ? tr[tr.length - 1].day : days[days.length - 1]; }
  renderChart();
}
function curExitMeta() { return M.exits.find(e => e.key === curExit); }
function renderChart() {
  const day = $('daySel').value, sig = DATA.signals.find(x => x.day === day) || null, trade = DATA.trades.find(t => t.day === day) || null;
  banner(sig, trade);
  const nd = DATA.next_of[day] || null;
  const c1 = DATA.chart_days[day] || [], c2 = nd ? (DATA.chart_days[nd] || []) : [];
  const oc = ((DATA.option_chart || {})[day] || {})[curInst] || null;
  if (!c1.length && !oc) {
    chartState = null; $('dayTag').textContent = day;
    csvg.innerHTML = txt(CW / 2, CH / 2, 'Candles are carried only from ' + M.chart_full_from + ' on, and for trade days before that.', null, 12, 'middle');
    osvg.innerHTML = ''; $('optHead').innerHTML = ''; $('tblVerify').innerHTML = ''; $('verifySub').textContent = ''; $('verifyTag').textContent = '';
    return;
  }
  /* one timeline for both panels */
  const keys = new Set();
  c1.forEach(r => keys.add(day + ' ' + r[0]));
  c2.forEach(r => keys.add(nd + ' ' + r[0]));
  if (oc) { Object.keys(oc.e || {}).forEach(m => keys.add(day + ' ' + m)); if (nd) Object.keys(oc.x || {}).forEach(m => keys.add(nd + ' ' + m)); }
  const tl = Array.from(keys).sort().map(s => ({d: s.slice(0, 10), t: s.slice(11)}));
  const pos = {}; tl.forEach((p, i) => pos[p.d + ' ' + p.t] = i);
  const ix = new Array(tl.length).fill(null), op = new Array(tl.length).fill(null);
  c1.forEach(r => { ix[pos[day + ' ' + r[0]]] = [r[1], r[2], r[3], r[4]]; });
  c2.forEach(r => { ix[pos[nd + ' ' + r[0]]] = [r[1], r[2], r[3], r[4]]; });
  if (oc) {
    Object.entries(oc.e || {}).forEach(([m, v]) => { const i = pos[day + ' ' + m]; if (i !== undefined) op[i] = v; });
    if (nd) Object.entries(oc.x || {}).forEach(([m, v]) => { const i = pos[nd + ' ' + m]; if (i !== undefined) op[i] = v; });
  }
  let split = tl.findIndex(p => p.d === nd); if (split < 0) split = tl.length;
  chartState = {day, nd, tl, pos, ix, op, split, sig, trade, oc, i0: 0, i1: tl.length};
  $('dayTag').textContent = day + (nd ? '  →  ' + nd : '  (no next session yet)');
  focusZoom();
}
function banner(sig, trade) {
  const b = $('setupBanner');
  if (!sig) { b.className = 'setup dim'; b.textContent = 'Outside the signal window.'; return; }
  const lines = [];
  if (sig.data_ok) lines.push('<span class="r">Day</span> 09:15 open <b>' + fmt(sig.day_open, 2) + '</b> &rarr; 15:14 close <b>' + fmt(sig.close, 2) + '</b> = <b class="' + sign(sig.move_pct) + '">' + (sig.move_pct >= 0 ? '+' : '') + fmt(sig.move_pct, 3) + '%</b>' +
    ' &nbsp;<span class="dimc">(high ' + fmt(sig.day_high, 2) + ', low ' + fmt(sig.day_low, 2) + ', close at ' + fmt(sig.loc_day * 100, 0) + '% of the range)</span>');
  lines.push('<span class="r">Decision</span> ' + pill(sig.decision) + (sig.data_ok ? (sig.decision === 'BUY' ? ' <span class="dimc">close above open &rarr; long the index overnight</span>' : sig.decision === 'SELL' ? ' <span class="dimc">close below open &rarr; short the index overnight</span>' : ' <span class="dimc">' + sig.hold_reason + '</span>') : ' <span class="pill data">data</span> <span class="dimc">' + sig.hold_reason + '</span>'));
  if (trade) {
    const l = leg(trade) || {};
    let t = '<span class="r">Position</span> ' + (l.symbol ? ('BOUGHT ') + '<b>' + l.symbol + '</b> (' + l.rel_strike + ') at ' + M.entry_hhmm + ' for <b>' + fmt(l.entry_px, 2) + '</b>' + (l.capital_rs ? ', capital &#8377;' + fmt(l.capital_rs, 0) + ' per lot' + (l.capital_source === 'broker' ? ' (broker)' : '') : '') : 'no contract priced');
    if (trade.status === 'closed' && l.exit_px !== null && l.exit_px !== undefined)
      t += ' &rarr; closed ' + trade.exit_day + ' ' + l.exit_minute + ' at <b>' + fmt(l.exit_px, 2) + '</b> = <b class="' + sign(l.pnl_rs) + '">' + (l.prem_pts >= 0 ? '+' : '') + fmt(l.prem_pts, 2) + ' pts &times; ' + M.lot_size + ' = &#8377;' + fmt(l.pnl_rs, 0) + '</b> gross, costs &#8377;' + fmt(l.costs_rs, 0) + ', <b class="' + sign(l.net_rs) + '">net &#8377;' + fmt(l.net_rs, 0) + '</b>';
    else if (trade.status !== 'closed') t += ' &nbsp;&middot;&nbsp; ' + trade.status;
    lines.push(t);
    if (trade.status === 'closed') lines.push('<span class="r">Spot</span> ' + fmt(trade.entry_spot, 2) + ' &rarr; ' + fmt(trade.exit_spot, 2) + ' at ' + trade.exit_time + ' = <b class="' + sign(trade.spot_pts) + '">' + (trade.spot_pts >= 0 ? '+' : '') + fmt(trade.spot_pts, 2) + ' pts (' + (trade.spot_pct >= 0 ? '+' : '') + fmt(trade.spot_pct, 3) + '%)</b>');
  }
  b.className = 'setup ' + (sig.decision === 'BUY' ? 'pos' : (sig.decision === 'SELL' ? 'neg' : 'dim'));
  b.innerHTML = lines.join('<br>');
}
function clampWindow(n, a, b) { let i0 = Math.max(0, Math.floor(a)), i1 = Math.min(n, Math.ceil(b)); if (i1 - i0 < 8) { const m = (i0 + i1) / 2; i0 = Math.max(0, Math.floor(m - 4)); i1 = Math.min(n, i0 + 8); } return [i0, i1]; }
function drawAll() { drawChart(); drawOption(); renderVerify(); }
function focusZoom() {
  const st = chartState; if (!st) return;
  const a = st.tl.findIndex(p => p.d === st.day && p.t >= '14:30');
  let b = st.tl.findIndex(p => p.d === st.nd && p.t > '10:00'); if (b < 0) b = st.tl.length;
  const w = clampWindow(st.tl.length, a < 0 ? 0 : a, b); st.i0 = w[0]; st.i1 = w[1]; drawAll();
}
function resetZoom() { if (!chartState) return; chartState.i0 = 0; chartState.i1 = chartState.tl.length; drawAll(); }
function zoomAt(f, anchor) { const st = chartState; if (!st) return; const a = anchor === undefined ? (st.i0 + st.i1) / 2 : anchor; const w = clampWindow(st.tl.length, a - (a - st.i0) * f, a + (st.i1 - a) * f); st.i0 = w[0]; st.i1 = w[1]; drawAll(); }
function idxAt(cx, box) { const px = (cx - box.left) / box.width * CW; return chartState.i0 + (px - PADL) / (CW - PADL - PADR) * (chartState.i1 - chartState.i0); }
/* shared X helpers */
function xOf(i) { const st = chartState, n = st.i1 - st.i0; return PADL + (i - st.i0 + 0.5) / n * (CW - PADL - PADR); }
function halfW() { const st = chartState; return (CW - PADL - PADR) / (st.i1 - st.i0) / 2; }
function seriesRange(arr) {
  const st = chartState; let lo = Infinity, hi = -Infinity;
  for (let i = st.i0; i < st.i1; i++) { const k = arr[i]; if (!k) continue; lo = Math.min(lo, k[2]); hi = Math.max(hi, k[1]); }
  return [lo, hi];
}
function candles(arr, Y, i0, i1) {
  let g = '', bw = Math.max(1, halfW() * 1.4);
  for (let i = i0; i < i1; i++) {
    const k = arr[i]; if (!k) continue;
    const up = k[3] >= k[0], col = up ? 'var(--up)' : 'var(--down)', x = xOf(i), y1 = Y(Math.max(k[0], k[3])), y2 = Y(Math.min(k[0], k[3]));
    g += '<line x1="' + x + '" y1="' + Y(k[1]) + '" x2="' + x + '" y2="' + Y(k[2]) + '" stroke="' + col + '" stroke-width="1"/><rect x="' + (x - bw / 2) + '" y="' + y1 + '" width="' + bw + '" height="' + Math.max(1, y2 - y1) + '" fill="' + col + '"/>';
  }
  return g;
}
function drawChart() {
  const st = chartState; if (!st) return;
  const {ix, i0, i1, sig, trade, split, day, nd} = st;
  const showRules = $('showRules').checked && sig && sig.data_ok, showTr = $('showTrade').checked && trade && trade.entry_spot !== null;
  let [lo, hi] = seriesRange(ix);
  if (!isFinite(lo)) { csvg.innerHTML = txt(CW / 2, CH / 2, 'no index candles in this window', null, 12, 'middle'); return; }
  if (showTr && trade.exit_spot !== null) { lo = Math.min(lo, trade.entry_spot, trade.exit_spot); hi = Math.max(hi, trade.entry_spot, trade.exit_spot); }
  const pad = (hi - lo) * 0.07 || 1; lo -= pad; hi += pad;
  const Y = v => PADT + (hi - v) / (hi - lo) * (CH - PADT - PADB);
  const at = (d, t) => { const i = st.pos[d + ' ' + t]; return i === undefined ? -1 : i; };
  const half = halfW(), vis = i => i >= i0 && i < i1;
  let g = '';
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4; g += '<line x1="' + PADL + '" y1="' + Y(v) + '" x2="' + (CW - PADR) + '" y2="' + Y(v) + '" stroke="var(--grid)"/>' + txt(PADL - 6, Y(v) + 3, fmt(v, 0), null, 10, 'end'); }
  const step = Math.max(1, Math.round((i1 - i0) / 12));
  for (let i = i0; i < i1; i += step) g += txt(xOf(i), CH - 8, st.tl[i].t, null, 10, 'middle');
  g += txt(PADL, 12, 'NIFTY index', 'var(--ink2)', 11);
  if (split > i0 && split < i1) { const xs = xOf(split) - half; g += '<line x1="' + xs + '" y1="' + PADT + '" x2="' + xs + '" y2="' + (CH - PADB) + '" stroke="var(--ink2)" stroke-width="1.2" stroke-dasharray="6 4"/>' + txt(xs - 6, PADT + 10, day, 'var(--ink2)', 11, 'end') + txt(xs + 6, PADT + 10, nd + ' (next session)', 'var(--ink2)', 11); }
  else if (i0 < split) g += txt(PADL + 6, PADT + 10, day, 'var(--ink2)', 11); else g += txt(PADL + 6, PADT + 10, nd + ' (next session)', 'var(--ink2)', 11);
  if (showRules) {
    const io = at(day, '09:15'), ic = at(day, '15:14'), icut = at(day, '15:15'), iend = at(day, '15:29');
    if (icut >= 0 && iend >= 0 && (vis(icut) || vis(iend))) { const x0 = Math.max(PADL, xOf(icut) - half), x1 = Math.min(CW - PADR, xOf(iend) + half);
      g += '<rect x="' + x0 + '" y="' + PADT + '" width="' + Math.max(0, x1 - x0) + '" height="' + (CH - PADT - PADB) + '" fill="var(--muted)" opacity="0.10"/>' + txt((x0 + x1) / 2, CH - PADB - 6, 'not read (15:15+)', null, 10, 'middle'); }
    if (ic >= 0 && vis(ic)) { const x = xOf(ic) + half; g += '<line x1="' + x + '" y1="' + PADT + '" x2="' + x + '" y2="' + (CH - PADB) + '" stroke="var(--warn)" stroke-width="1.4"/>' + txt(x - 4, PADT + 24, 'decision at 15:14 close ' + fmt(sig.close, 2), 'var(--warn)', 10.5, 'end'); }
    const col = sig.move_pct >= 0 ? 'var(--up)' : 'var(--down)';
    const xo = io >= 0 ? xOf(Math.max(io, i0)) : PADL, yo = Y(sig.day_open);
    if (ic >= 0 && (vis(ic) || vis(io))) { g += '<line x1="' + xo + '" y1="' + yo + '" x2="' + xOf(ic) + '" y2="' + Y(sig.close) + '" stroke="' + col + '" stroke-width="1.6" stroke-dasharray="4 3"/>' +
      '<line x1="' + PADL + '" y1="' + yo + '" x2="' + (xOf(Math.min(split, i1) - 1) + half) + '" y2="' + yo + '" stroke="' + col + '" stroke-width="0.8" stroke-dasharray="2 4"/>' +
      txt(PADL + 4, yo - 4, '09:15 open ' + fmt(sig.day_open, 2) + '  ·  day ' + (sig.move_pct >= 0 ? '+' : '') + fmt(sig.move_pct, 3) + '% → ' + sig.decision, col, 10.5); }
  }
  g += candles(ix, Y, i0, i1);
  if (showTr) {
    const l = leg(trade) || {}, ie = at(day, M.entry_hhmm), col = trade.status === 'closed' ? ((l.pnl_rs !== null && l.pnl_rs !== undefined ? l.pnl_rs : trade.spot_pts) >= 0 ? 'var(--up)' : 'var(--down)') : 'var(--accent)';
    if (ie >= 0 && vis(ie)) g += '<circle cx="' + xOf(ie) + '" cy="' + Y(trade.entry_spot) + '" r="4.5" fill="' + col + '" stroke="var(--surface)" stroke-width="1.5"/>' + txt(xOf(ie) - 8, Y(trade.entry_spot) + 4, trade.decision + ' ' + M.entry_hhmm + ' ' + fmt(trade.entry_spot, 2), col, 11, 'end');
    if (trade.status === 'closed') { const xm = l.exit_minute || trade.exit_time, ixm = at(nd, xm); const sAt = ixm >= 0 && ix[ixm] ? ix[ixm][3] : trade.exit_spot;
      if (ixm >= 0 && ie >= 0 && (vis(ixm) || vis(ie))) g += '<line x1="' + xOf(ie) + '" y1="' + Y(trade.entry_spot) + '" x2="' + xOf(ixm) + '" y2="' + Y(sAt) + '" stroke="' + col + '" stroke-width="1.8" stroke-dasharray="5 3"/><circle cx="' + xOf(ixm) + '" cy="' + Y(sAt) + '" r="4.5" fill="' + col + '" stroke="var(--surface)" stroke-width="1.5"/>' +
        txt(xOf(ixm) + 8, Y(sAt) + 4, 'exit ' + xm + '  ·  spot ' + (trade.spot_pts >= 0 ? '+' : '') + fmt(trade.spot_pts, 2), col, 11); }
  }
  csvg.innerHTML = g;
}
/* the option panel: the contract you actually bought */
function drawOption() {
  const st = chartState; if (!st) return;
  const {op, i0, i1, trade, split, day, nd} = st;
  const head = $('optHead');
  if (!st.oc) {
    osvg.innerHTML = txt(CW / 2, OCH / 2, 'No option candles carried for this night and strike.', null, 12, 'middle');
    head.className = 'setup dim'; head.innerHTML = 'Option candles are carried for the last ' + M.chart_opt_days + ' days of the run.';
    return;
  }
  const l = (trade ? leg(trade) : null) || {}, ex = curExitMeta();
  const line = (l.line !== null && l.line !== undefined) ? l.line : null;
  let [lo, hi] = seriesRange(op);
  if (!isFinite(lo)) { osvg.innerHTML = txt(CW / 2, OCH / 2, 'no option candles in this window', null, 12, 'middle'); head.innerHTML = ''; return; }
  if (l.entry_px) { lo = Math.min(lo, l.entry_px); hi = Math.max(hi, l.entry_px); }
  if (line) { lo = Math.min(lo, line); hi = Math.max(hi, line); }
  if (l.exit_px) { lo = Math.min(lo, l.exit_px); hi = Math.max(hi, l.exit_px); }
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const Y = v => OPADT + (hi - v) / (hi - lo) * (OCH - OPADT - OPADB);
  const at = (d, t) => { const i = st.pos[d + ' ' + t]; return i === undefined ? -1 : i; };
  const half = halfW(), vis = i => i >= i0 && i < i1;
  let g = '';
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4; g += '<line x1="' + PADL + '" y1="' + Y(v) + '" x2="' + (CW - PADR) + '" y2="' + Y(v) + '" stroke="var(--grid)"/>' + txt(PADL - 6, Y(v) + 3, fmt(v, 1), null, 10, 'end'); }
  const step = Math.max(1, Math.round((i1 - i0) / 12));
  for (let i = i0; i < i1; i += step) g += txt(xOf(i), OCH - 8, st.tl[i].t, null, 10, 'middle');
  g += txt(PADL, 12, (l.symbol || 'option') + '  ·  premium per share', 'var(--ink2)', 11);
  if (split > i0 && split < i1) { const xs = xOf(split) - half; g += '<line x1="' + xs + '" y1="' + OPADT + '" x2="' + xs + '" y2="' + (OCH - OPADB) + '" stroke="var(--ink2)" stroke-width="1.2" stroke-dasharray="6 4"/>'; }
  /* the scan window: nothing may fire before it */
  if (nd && ex) {
    const a = at(nd, ex.start); let b = at(nd, ex.limit);
    if (b < 0) b = i1 - 1;
    if (a >= 0 && (vis(a) || vis(b))) { const x0 = Math.max(PADL, xOf(a) - half), x1 = Math.min(CW - PADR, xOf(b) + half);
      g += '<rect x="' + x0 + '" y="' + OPADT + '" width="' + Math.max(0, x1 - x0) + '" height="' + (OCH - OPADT - OPADB) + '" fill="var(--accent)" opacity="0.06"/>' +
        txt((x0 + x1) / 2, OCH - OPADB - 6, 'the rule may sell only here: ' + ex.start + ' → ' + ex.limit, 'var(--accent)', 10, 'middle'); }
  }
  /* the line the rule watches */
  if (line) {
    g += '<line x1="' + PADL + '" y1="' + Y(line) + '" x2="' + (CW - PADR) + '" y2="' + Y(line) + '" stroke="var(--warn)" stroke-width="1.3" stroke-dasharray="7 4"/>' +
      txt(CW - PADR - 4, Y(line) - 5, 'line to clear ' + fmt(line, 2) + (ex && ex.thr === 'costs' ? '  =  entry + costs' : ''), 'var(--warn)', 10.5, 'end');
  }
  /* every minute whose LOW cleared the line */
  if ($('showQual').checked && line && nd && ex && ex.trigger === 'low') {
    for (let i = Math.max(i0, split); i < i1; i++) {
      const k = op[i]; if (!k || st.tl[i].t < ex.start || st.tl[i].t > ex.limit) continue;
      if (k[2] > line) g += '<rect x="' + (xOf(i) - half) + '" y="' + OPADT + '" width="' + Math.max(1, half * 2) + '" height="' + (OCH - OPADT - OPADB) + '" fill="var(--up)" opacity="0.13"/>';
    }
  }
  g += candles(op, Y, i0, i1);
  /* entry and exit, at the prices actually filled */
  const ie = at(day, l.entry_minute || M.entry_hhmm);
  const col = (l.net_rs !== null && l.net_rs !== undefined) ? (l.net_rs >= 0 ? 'var(--up)' : 'var(--down)') : 'var(--accent)';
  if (ie >= 0 && vis(ie) && l.entry_px) {
    g += '<circle cx="' + xOf(ie) + '" cy="' + Y(l.entry_px) + '" r="5" fill="var(--accent)" stroke="var(--surface)" stroke-width="1.5"/>' +
      txt(xOf(ie) - 9, Y(l.entry_px) + 4, 'BOUGHT ' + (l.entry_minute || M.entry_hhmm) + ' @ ' + fmt(l.entry_px, 2) + (curFill === 'worst' ? ' (minute high)' : ' (close)'), 'var(--accent)', 11, 'end');
  }
  if (l.exit_minute && l.exit_px !== null && l.exit_px !== undefined && nd) {
    const ixm = at(nd, l.exit_minute);
    if (ixm >= 0 && vis(ixm)) {
      const xb = (st.oc.x || {})[l.exit_minute];
      const fallback = !!(line && xb && xb[2] <= line);
      g += '<circle cx="' + xOf(ixm) + '" cy="' + Y(l.exit_px) + '" r="5" fill="' + col + '" stroke="var(--surface)" stroke-width="1.5"/>' +
        (ie >= 0 ? '<line x1="' + xOf(ie) + '" y1="' + Y(l.entry_px) + '" x2="' + xOf(ixm) + '" y2="' + Y(l.exit_px) + '" stroke="' + col + '" stroke-width="1.6" stroke-dasharray="5 3"/>' : '') +
        txt(xOf(ixm) + 9, Y(l.exit_px) + 4, (fallback ? 'FALLBACK SOLD ' : 'SOLD ') + l.exit_minute + ' @ ' + fmt(l.exit_px, 2) + (curFill === 'worst' ? ' (minute low)' : '') +
          '  =  ' + (l.prem_pts >= 0 ? '+' : '') + fmt(l.prem_pts, 2) + ' pts, net ₹' + fmt(l.net_rs, 0), col, 11);
    }
  }
  osvg.innerHTML = g;
  /* the header: which strike, and the arithmetic behind the line */
  const parts = [];
  if (l.symbol) parts.push('<span class="r">Contract</span> <b>' + l.symbol + '</b> <span class="dimc">(' + l.rel_strike + ', strike ' + fmt(l.strike, 0) + ' ' + l.option_type + ', expiry ' + l.expiry + ', ' + l.dte + ' days from the signal day)</span>');
  if (l.entry_px) parts.push('<span class="r">Line</span> entry <b>' + fmt(l.entry_px, 2) + '</b>' + (curFill === 'worst' ? ' (the 15:20 minute&rsquo;s HIGH, the worst you could have paid)' : ' (the 15:20 close)') +
    (line ? ' + costs <b>' + fmt(line - l.entry_px, 2) + '</b> = <b>' + fmt(line, 2) + '</b> &mdash; a minute qualifies only when its LOW is above this' : ''));
  head.className = 'setup ' + (l.net_rs >= 0 ? 'pos' : (l.net_rs < 0 ? 'neg' : 'dim'));
  head.innerHTML = parts.join('<br>') || 'No contract priced for this night and strike.';
}
/* the cross-check table: every minute, the numbers the rule compared */
function renderVerify() {
  const st = chartState, tb = $('tblVerify');
  if (!st || !st.oc || !st.nd) { tb.innerHTML = ''; $('verifySub').textContent = 'No option candles for this night and strike.'; $('verifyTag').textContent = ''; return; }
  const trade = st.trade, l = (trade ? leg(trade) : null) || {}, ex = curExitMeta();
  const line = (l.line !== null && l.line !== undefined) ? l.line : null;
  const x = st.oc.x || {}, mins = Object.keys(x).sort();
  const all = $('verifyAll').checked;
  const rows = mins.filter(m => all || ((!ex || m >= ex.start) && (!l.exit_minute || m <= l.exit_minute) && (!ex || m <= ex.limit)));
  $('verifySub').innerHTML = 'Exit day <b>' + st.nd + '</b>, contract <b>' + (l.symbol || '-') + '</b>, fills <b>' + curFill + '</b>. ' +
    (line ? 'A minute qualifies when its LOW is above <b>' + fmt(line, 2) + '</b>. ' : '') +
    'These are the raw one-minute candles the backtest read; the marked row is the minute it sold in.';
  $('verifyTag').textContent = rows.length + ' of ' + mins.length + ' minutes shown';
  tb.innerHTML = '<thead><tr><th class="l">minute</th><th>open</th><th>high</th><th>low</th><th>close</th>' +
    (line ? '<th>low &minus; line</th><th class="l">qualifies?</th>' : '') + '<th class="l">what the rule did</th></tr></thead><tbody>' +
    rows.map(m => {
      const k = x[m], q = line !== null && k[2] > line, isExit = l.exit_minute === m;
      const before = ex && m < ex.start;
      const after = l.exit_minute && m > l.exit_minute;
      let note = '';
      if (isExit) note = '<b class="' + sign(l.net_rs) + '">' + (q ? 'SOLD here' : 'NOTHING QUALIFIED &mdash; sold at the ' + ex.limit + ' fallback') +
        ' at ' + fmt(l.exit_px, 2) + ' &rarr; net &#8377;' + fmt(l.net_rs, 0) + '</b>';
      else if (before) note = '<span class="dimc">before ' + ex.start + ', the rule is not looking yet</span>';
      else if (after) note = '<span class="dimc">after the sale &mdash; the position was already closed</span>';
      else if (q) note = '<span class="pos">first qualifying minute</span>';
      else note = '<span class="dimc">low is not above the line &rarr; wait</span>';
      return '<tr' + (isExit ? ' style="font-weight:600;background:var(--grid)"' : '') + '><td class="l">' + m + '</td>' +
        plain(k[0], 2) + plain(k[1], 2) + plain(k[2], 2) + plain(k[3], 2) +
        (line ? cell(k[2] - line, 2) + '<td class="l">' + (before ? '<span class="dimc">n/a</span>' : (q ? '<span class="pos">yes</span>' : '<span class="neg">no</span>')) + '</td>' : '') +
        '<td class="l">' + note + '</td></tr>';
    }).join('') + '</tbody>';
}
csvg.addEventListener('wheel', e => { if (!chartState) return; e.preventDefault(); zoomAt(e.deltaY < 0 ? 0.82 : 1.22, idxAt(e.clientX, csvg.getBoundingClientRect())); }, {passive: false});
osvg.addEventListener('wheel', e => { if (!chartState) return; e.preventDefault(); zoomAt(e.deltaY < 0 ? 0.82 : 1.22, idxAt(e.clientX, osvg.getBoundingClientRect())); }, {passive: false});
let drag = null;
function startDrag(el, e) { if (!chartState) return; drag = {x: e.clientX, i0: chartState.i0, i1: chartState.i1}; el.classList.add('drag'); try { el.setPointerCapture(e.pointerId); } catch (_) {} }
function moveDrag(el, e) {
  if (!chartState) return; const box = el.getBoundingClientRect();
  if (drag) { const dx = (e.clientX - drag.x) / box.width * CW, perPx = (drag.i1 - drag.i0) / (CW - PADL - PADR); const w = clampWindow(chartState.tl.length, drag.i0 - dx * perPx, drag.i1 - dx * perPx); chartState.i0 = w[0]; chartState.i1 = w[1]; drawAll(); ctip.style.display = 'none'; return; }
  const i = Math.round(idxAt(e.clientX, box) - 0.5); if (i < 0 || i >= chartState.tl.length) { ctip.style.display = 'none'; return; }
  const p = chartState.tl[i], a = chartState.ix[i], b = chartState.op[i];
  ctip.innerHTML = '<b>' + p.t + '</b> <span style="opacity:.65">' + p.d + '</span>' +
    (a ? '<br><span style="opacity:.65">index</span> O ' + a[0].toFixed(2) + ' H ' + a[1].toFixed(2) + ' L ' + a[2].toFixed(2) + ' C ' + a[3].toFixed(2) : '') +
    (b ? '<br><span style="opacity:.65">option</span> O ' + b[0].toFixed(2) + ' H ' + b[1].toFixed(2) + ' L ' + b[2].toFixed(2) + ' C ' + b[3].toFixed(2) : '');
  ctip.style.display = 'block'; ctip.style.left = Math.min(e.clientX + 14, window.innerWidth - 220) + 'px'; ctip.style.top = Math.max(4, e.clientY - 60) + 'px';
}
function endDrag(el, e) { drag = null; el.classList.remove('drag'); try { el.releasePointerCapture(e.pointerId); } catch (_) {} }
[csvg, osvg].forEach(el => {
  el.addEventListener('pointerdown', e => startDrag(el, e));
  el.addEventListener('pointermove', e => moveDrag(el, e));
  el.addEventListener('pointerup', e => endDrag(el, e));
  el.addEventListener('pointerleave', () => { ctip.style.display = 'none'; });
});
$('daySel').onchange = renderChart; $('showRules').onchange = drawChart; $('showTrade').onchange = drawAll;
$('showQual').onchange = drawOption; $('verifyAll').onchange = renderVerify;
$('zoomFocus').onclick = focusZoom; $('zoomIn').onclick = () => zoomAt(0.7); $('zoomOut').onclick = () => zoomAt(1.4); $('zoomReset').onclick = resetZoom;

/* ---------- notes ---------- */
$('rule').innerHTML = [
  ['Daily bar', '360 one-minute candles 09:15..15:14; open = 09:15 open, close = 15:14 close. Any candle missing, duplicated or invalid &rarr; <b>HOLD</b>.'],
  ['Decision', '15:14 close <b>above</b> the 09:15 open &rarr; <b>BUY</b>; <b>below</b> &rarr; <b>SELL</b>; equal &rarr; HOLD. Nothing from 15:15 on is read.'],
  ['Position', 'BUY <b>buys the CALL 6 strikes in the money (ATM&minus;6)</b>; SELL <b>buys the PUT 6 strikes in the money (ATM+6)</b>. Opened in the 15:20 minute. Four other strikes are priced beside it; 8 strikes in is thin (see the liquidity table). One strike = 50 points.' +
    '<table style="margin-top:8px;width:auto"><thead><tr><th class="l">instrument</th><th class="l">on a BUY day</th><th class="l">on a SELL day</th></tr></thead><tbody>' +
    [['Buy - ATM', 'buy CALL at ATM', 'buy PUT at ATM'], ['Buy - 2 strikes ITM', 'buy CALL at ATM&minus;2', 'buy PUT at ATM+2'], ['Buy - 4 strikes ITM', 'buy CALL at ATM&minus;4', 'buy PUT at ATM+4'], ['Buy - 6 strikes ITM', 'buy CALL at ATM&minus;6', 'buy PUT at ATM+6'], ['Buy - 8 strikes ITM', 'buy CALL at ATM&minus;8', 'buy PUT at ATM+8']]
      .map(r => '<tr><td class="l">' + r[0] + '</td><td class="l">' + r[1] + '</td><td class="l">' + r[2] + '</td></tr>').join('') + '</tbody></table>'],
  ['Expiry', 'nearest weekly expiry strictly <b>after the exit day</b> &mdash; never carried into an expiry morning.'],
  ['Exit', 'from <b>09:30</b> of the next session, the <b>first minute whose LOW is above the entry price by more than the round-trip costs</b>, sold at that minute&rsquo;s low; if no minute gets there by 15:14, sold in the 15:14 minute. The first fifteen minutes are never used: the option&rsquo;s minute range is 45 points at 09:15, 19 at 09:16 and about 10 until 09:30, so a low-trigger there is filled far below the close. The other exits in the selector are kept for comparison, including the earlier 09:16 start.'],
  ['Trade count', 'every valid session, so about 250 a year.'],
].map(r => '<div class="k">' + r[0] + '</div><div>' + r[1] + '</div>').join('');
$('fills').innerHTML = '<b>Fills.</b> Spot entry is the 15:29 candle close and spot exit the next session&rsquo;s first-candle close; both are references only. The option is priced at its own one-minute closes at the same minutes. A strike with no print at the nominal minute takes the nearest print within 5 minutes (last before for the entry, first after for the exit) and the minute used is in the trades table. &#8377; is one lot of ' + M.lot_size + '. Derived 09:15 opens matched the daily feed on ' + M.open_match + ' of ' + M.open_checked + ' sessions checked.';
$('fills').innerHTML += ' <b>Capital per lot.</b> A bought option ties up its premium. A sold option ties up SPAN + exposure margin, ' +
  'which the exchange sets from volatility and which no archive serves for past dates; past nights use a model calibrated on the broker&rsquo;s margin API on 2026-09-18 ' +
  '(exposure 2.0% of notional plus SPAN of 9.0% at the money, falling about 0.38% per 100 points out of the money: about &#8377;1.67 lakh for a sold ATM at index 23,350), ' +
  'and the current signal&rsquo;s figure is read live from the broker (marked &ldquo;live&rdquo;). SPAN rises when volatility rises, so the estimate runs LOW on panic nights.';
$('fills').innerHTML += ' <b>Fills.</b> Two fill assumptions are carried for every night: <i>close</i>, the minute&rsquo;s closing price as the data prints it, and <i>worst</i>, paying the entry minute&rsquo;s high and receiving the exit minute&rsquo;s low, so that no backtest fill is better than a real one could have been. The exit trigger is always the minute&rsquo;s close; under worst fills the sale is booked at that minute&rsquo;s low, which can turn a triggered exit into a small loss. The selector at the top switches every figure between the two.';
$('fills').innerHTML += ' <b>Brokerage and taxes.</b> Every round trip is charged as two orders: brokerage &#8377;20 per order, STT 0.1% of the sell-side premium, exchange charge 0.03503% of the premium turnover, SEBI fee &#8377;10 per crore, stamp duty 0.003% of the buy-side premium, GST 18% on brokerage and exchange and SEBI charges (rates in force from 2024-10-01, held in <code>services/trade_costs.py</code>). Every position is closed before expiry, so there is no exercise STT. Wins, losses, win rate, profit factor and the matrix are all NET of these costs; the gross figure is shown beside them.';
$('limits').innerHTML = '<b>What limits these numbers.</b> A bought option&rsquo;s loss is capped at the premium paid, which is also the capital per lot. Because the exit can wait until the next 15:14, the capital is committed for a full session. The option pricing is six months of history; the signal&rsquo;s five-year record and the exit&rsquo;s five-year lift are on spot. Six months and ~120 nights cannot separate 72% from 66%. From ' + M.cas_date + ' the 15:29 index candle carries the closing-auction print, and F&amp;O trading runs to 15:40 (the option feed shows contracts trading to 15:39 from that date) while the index prints nothing after 15:29. The rule therefore decides on the 15:14 candle, may enter any time up to 15:39, and is measured with the 15:29 entry it was specified with; entries at 15:15, 15:20 and 15:25 give the same win rate inside noise. The exit fallback stays at the next 15:14 so that pre- and post-auction nights are measured the same way.';

renderAll();
</script>
</body>
</html>
"""


def liquidity_table(trades: list[dict]) -> list[dict]:
    """Share of exit-day minutes with no trade (high == low) per strike offered,
    over the closed trades - the reason the default stops at 6 strikes in."""
    pricer = CachedPricer()
    out = []
    for key, kind, off, lab in INSTRUMENTS:
        flat_day, flat_scan, n = [], [], 0
        for t in trades:
            if t["status"] != "closed" or t["entry_spot"] is None:
                continue
            opt, strike = contract_spec(t, kind, off)
            c, ec, xc, eo, xo = _cached(pricer, t, opt, strike)
            if not xo:
                continue
            bars = [xo[m] for m in xo if "09:16" <= m <= "15:14"]
            scan = [xo[m] for m in xo if "09:30" <= m <= "15:14"]
            if not bars or not scan:
                continue
            flat_day.append(sum(1 for b in bars if b[1] == b[2]) / len(bars))
            flat_scan.append(sum(1 for b in scan if b[1] == b[2]) / len(scan))
            n += 1
        out.append({"key": key, "label": lab, "n": n,
                    "flat_day": statistics.fmean(flat_day) * 100 if flat_day else None,
                    "flat_scan": statistics.fmean(flat_scan) * 100 if flat_scan else None})
    return out


def write_report(payload: dict, out_path: str) -> None:
    html = HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":")))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  report  -> {out_path} ({len(html) / 1e6:.1f} MB)")


# Recorded from the scratch study of 2026-09-18 (research_overnight.py):
# the signal on spot, 15:29 close -> next first-candle close.
WIDE_SIGNAL = ("1,127 sessions, 54.5% win, mean +0.069% a night, t +4.40; by year (win %, mean %) "
               "2022 62 / +0.11, 2023 52 / +0.01, 2024 52 / +0.05, 2025 53 / +0.07, 2026 55 / +0.12. "
               "BUY side 62.0% over 540 nights, SELL side 47.5% over 587: the calls carry the long run, "
               "the puts carried 2026. Sold-option pricing exists for the last six months only.")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

async def run(args) -> None:
    candles = await load_nifty(args.offline, args.from_date, args.to_date)
    rows, bad_ts = to_rows(candles)
    print_coverage(args.from_date, args.to_date)
    sessions, all_days = build_sessions(rows)
    # the spot reference entry is the same minute the option is bought in
    by_day_rows = defaultdict(list)
    for r in rows:
        by_day_rows[r["day"]].append(r)
    for d, sess in sessions.items():
        ent = [r for r in by_day_rows[d] if r["t"] == ENTRY_HHMM and r["ok"]]
        sess["entry"] = ent[0] if len(ent) == 1 else None
    series = daily_series(sessions, all_days, args.partial)
    from_iso, to_iso = args.from_date.isoformat(), args.to_date.isoformat()
    signals = [compute_signal(s) for s in series if from_iso <= s["day"] <= to_iso]
    if not signals:
        raise RuntimeError(f"no session inside {from_iso} -> {to_iso}")
    add_context(series, signals)
    print(f"  {len(signals)} sessions in the window, {sum(1 for x in signals if not x['data_ok'])} invalid")
    official = await load_daily_ohlc(args.offline, args.from_date, args.to_date)
    checked = [x for x in signals if x["day_open"] is not None and x["day"] in official]
    open_match = sum(1 for x in checked if abs(x["day_open"] - official[x["day"]]["o"]) < 0.005)

    trades = build_trades(signals, sessions, all_days)
    chart_full_from = (args.to_date - timedelta(days=CHART_FULL_DAYS)).isoformat()
    priced, closed, option_chart = await price_trades(
        trades, args.offline, None if args.offline else _read_access_token(), chart_full_from)
    liquidity = liquidity_table(trades)
    print(f"  {len(trades)} signals, {closed} closed nights, {priced} priced ({DEFAULT_INSTRUMENT}, {DEFAULT_EXIT})")

    # The worst-fill view needs open/high/low for every contract-day.  When the
    # caches do not have them yet (a refetch needs a live token), open the report
    # on close fills and say so, rather than show a headline built on a handful.
    closed_all = [t for t in trades if t["status"] == "closed" and t.get("legs")]
    have_w = sum(1 for t in closed_all
                 if t["legs"][DEFAULT_INSTRUMENT]["exits"][DEFAULT_EXIT].get("net_rs_w") is not None)
    fill = DEFAULT_FILL
    if DEFAULT_FILL == "worst" and closed_all and have_w < 0.9 * len(closed_all):
        fill = "close"
        print(f"  ! open/high/low present for {have_w} of {len(closed_all)} closed nights - "
              f"report opens on CLOSE fills; rerun online with a fresh token to complete the worst-fill view")
    six = (args.to_date - timedelta(days=183)).isoformat()
    six_lo = max(from_iso, six)
    windows = [("cas", f"from {CAS_DATE} (closing auction)", max(from_iso, CAS_DATE)),
               ("6m", f"6-month backtest {six_lo} -> {to_iso}", six_lo)]
    if from_iso < six:
        windows.append(("all", f"all data {from_iso} -> {to_iso}", from_iso))
    views = {}
    for key, label, lo in windows:
        sig_w = [x for x in signals if x["day"] >= lo]
        tr_w = [t for t in trades if t["day"] >= lo]
        views[key] = {"label": label, "from": lo, "to": to_iso, "sessions": len(sig_w),
                      "verdict": verdict_text(tr_w, sig_w, label, fill)}

    chart_rows: dict[str, list] = defaultdict(list)
    trade_days = {t["day"] for t in trades} | {t["exit_day"] for t in trades if t["exit_day"]}
    for r in rows:
        d = r["day"]
        if d < from_iso or not r["ok"] or not (SESSION_START <= r["t"] <= CHART_END):
            continue
        if d < chart_full_from and (d not in trade_days or not (r["t"] >= "14:30" or r["t"] <= "10:00")):
            continue
        chart_rows[d].append([r["t"], round(r["o"], 2), round(r["h"], 2), round(r["l"], 2), round(r["c"], 2)])
    meta = {"from": from_iso, "to": to_iso, "generated": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
            "lot_size": LOT_SIZE, "cas_date": CAS_DATE, "chart_full_from": chart_full_from,
            "chart_opt_days": CHART_FULL_DAYS,
            "default_instrument": DEFAULT_INSTRUMENT, "default_exit": DEFAULT_EXIT,
            "default_fill": fill, "worst_coverage": [have_w, len(closed_all)],
            "entry_hhmm": ENTRY_HHMM, "liquidity": liquidity,
            "fills": [{"key": k, "label": lab} for k, lab in FILLS],
            "instruments": [{"key": k, "label": lab} for k, _, _, lab in INSTRUMENTS],
            "exits": [{"key": k, "label": lab, "trigger": trig, "start": start, "limit": _l,
                         "thr": (_t if isinstance(_t, (str, float, int)) else None)}
                        for k, lab, _l, _t, trig, start in EXITS],
            "open_checked": len(checked), "open_match": open_match, "wide_signal": WIDE_SIGNAL}
    payload = {"meta": meta, "views": views, "signals": signals, "trades": trades,
               "default_view": "cas" if views["cas"]["sessions"] else "6m",
               "chart_days": {d: sorted(v) for d, v in chart_rows.items()},
               "option_chart": option_chart,
               "next_of": {d: all_days[k + 1] for k, d in enumerate(all_days) if k + 1 < len(all_days)}}
    for key in ("cas", "6m", "all"):
        if key in views:
            print(f"\n  {views[key]['verdict']}")
    print()
    write_signals_csv(signals, official, args.signals_csv)
    write_trades_csv(trades, args.trades_csv)
    write_report(payload, args.out)


def main() -> None:
    today = date.today()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--partial-sessions", dest="partial", default="strict",
                    choices=[k for k, _ in PARTIAL_MODES], help="; ".join(f"{k}: {v}" for k, v in PARTIAL_MODES))
    ap.add_argument("--offline", action="store_true", help="use local caches only")
    ap.add_argument("--out", default=REPORT_HTML)
    ap.add_argument("--signals-csv", default=SIGNALS_CSV)
    ap.add_argument("--trades-csv", default=TRADES_CSV)
    ap.add_argument("--from", dest="from_date", type=date.fromisoformat, default=today - timedelta(days=183),
                    help="first signal day (default 6 months back). The report always carries the "
                         "post-auction window and the 6-month window; a wider --from adds a third.")
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat, default=today)
    ap.add_argument("--full-history", action="store_true",
                    help=f"run from the start of the broker's option archive ({PRICED_START})")
    args = ap.parse_args()
    if args.full_history:
        args.from_date = PRICED_START
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
