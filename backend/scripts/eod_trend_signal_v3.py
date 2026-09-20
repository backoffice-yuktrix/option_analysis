"""EOD trend signal, v3 - the live rule.  One signal, one strike, one exit, one
extra condition: never pay for too much time value.

v2 is the research bench: five strikes, six exits, two fill models, ten optional
filters, a matrix to compare them.  v3 is what that search settled on, written
out as the single rule to trade, with nothing to select and nothing to tune.

WHY v3 IS A NEW VERSION AND NOT A v2 REVISION
    The 2026-09-19 change (6 strikes in, entry 15:20, scan from 09:30) was
    execution only, so it was folded back into v2.  This one is not: the
    time-value condition decides WHETHER A NIGHT IS TRADED AT ALL.  It removes
    44% of the nights v2 takes (209 of 476).  That is a change to the rule, so
    it is v3.  (The 37% often quoted is the older 60-point limit, which removed
    176; the ratio in force removes more.)

THE RULE
--------
    Feed        NSE_INDEX|Nifty 50, one-minute candles, Asia/Kolkata.
    Daily bar   09:15 open .. 15:14 close, from the 360 one-minute candles.
    Decision    after the 15:14 candle; nothing from 15:15 on is read for the
                DIRECTION.  The time-value check reads the option at 15:19.

    1. 15:14 close ABOVE the 09:15 open  -> BUY   (buy a CALL)
    2. 15:14 close BELOW the 09:15 open  -> SELL  (buy a PUT)
    3. equal, or any candle missing, duplicated or invalid -> HOLD

    Strike      SIX strikes in the money: the call at ATM-6 on a BUY, the put
                at ATM+6 on a SELL.  ATM is the 15:20 index rounded to 50.
                The report prices the WHOLE LADDER on the same nights - ATM and
                six rungs either side, thirteen in all - so every rung can be
                compared against the one the rule trades.  Only this rung is
                the rule.
    Expiry      the nearest weekly expiry strictly AFTER the exit day.

    4. THE TIME-VALUE CONDITION (new in v3).  At 15:19 read that contract's
       price and work out how much of it is NOT intrinsic value, as a SHARE of
       what you would pay:

           intrinsic  = | 15:20 index  -  strike |      (about 300 points)
           time value = 15:19 option price  -  intrinsic
           share      = time value / 15:19 option price

       If the share is MORE THAN 15%, do not trade tonight.  It is read at
       15:19, one minute before the entry, so the decision is made from a price
       that has already printed.

       IT IS A RATIO, NOT A NUMBER OF POINTS, and that matters.  Sixty points of
       time value on a 360 premium is 17% of what you pay; the same sixty points
       on a 150 premium is 40%.  An absolute limit therefore means a different
       thing at every strike and in every volatility regime.  Measured over all
       476 nights at this strike, the ratio is a STRICT SUBSET of the old
       60-point limit - 267 nights in both, 33 taken only by the point limit,
       none taken only by the ratio - and those 33 extra nights won 75.8% but
       lost Rs 16,345 net.  The ratio removes exactly the nights that dragged:

                            nights  win rate      net    PF   max drawdown
           no check            476     75.8%  257,433  1.25        -92,289
           60 points           300     79.7%  217,832  1.43       -103,621
           15% of premium      267     80.1%  234,178  1.54        -69,017
           10% of premium      203     80.8%  215,622  1.76        -66,116

       The point limit made the drawdown WORSE than trading every night; the
       ratio makes it better.  By year the ratio wins throughout - 2024 89.2%
       (PF 2.77), 2025 78.3% (PF 1.20), 2026 79.3% (PF 1.86) - against 87.8 /
       77.9 / 79.2 for the point limit, and it lifts the flat year of 2025 from
       PF 1.03 unchecked and 1.09 at 60 points to 1.20.  Win rate falls smoothly
       as the limit loosens (5% -> 81.2%, 10% -> 80.8%, 15% -> 80.1%, 20% ->
       78.4%, 30% -> 76.7%), so 15% is not a knife edge.  10% reads better
       still on the whole sample but is thinner (203 nights), less even between
       halves (78.6% then 83.0% against 79.6% then 80.8%) and weaker in 2025.

       A ratio also makes the ladder coherent.  Out of the money there is no
       intrinsic value, so time value is 100% of the premium and no rung at or
       beyond the money can ever pass.  The old point limit let deep
       out-of-the-money contracts through merely because they were cheap - a
       50-point option is 100% air but passed a 60-point test.

    Entry       buy in the 15:20 minute.
    Exit        from 09:30 of the next session, the FIRST minute whose LOW is
                above the entry by more than the round-trip costs, sold at that
                minute's low; if no minute gets there by 15:14, sold in the
                15:14 minute.
    Fills       WORST OF THE MINUTE: bought at the entry minute's HIGH, sold at
                the exit minute's LOW.

WHY THE TIME-VALUE CONDITION
    Measured over the broker's whole option archive, 2024-10-01 -> 2026-09-17,
    476 nights, 6 strikes in, worst fills, net of costs.  THE REPORT ITSELF NOW
    RUNS FROM A FIXED 2026-03-01 TO TODAY (see START_DATE); the figures below
    are the wider evidence the rule was chosen on, kept here because a six-month
    window cannot settle them.

    The losing nights are not trades that turned.  All 115 of them exited at the
    15:14 fallback, 91% never traded above the line at any minute of the day,
    and 82% had already gapped against at the open (34% of winners did).  A
    median loser is -10.8% of premium before the first candle of the exit day
    closes.  Nothing observable at 15:20 forecasts that gap: every feature
    tested - the day's move, its range, the close location, 5/10/30-day trend,
    the previous day, realised volatility, weekday, side, days to expiry -
    separates winners from losers at 0.45..0.55, where 0.50 is no information
    at all, and the best of them failed out of sample.

    Time value is the exception, and it is not a forecast.  It is how much of
    the premium is exposed to something other than the index moving your way.
    Pay less of it and fewer nights lose:

        time value paid     nights   loss rate
        under 0.6 pts           95      20.0%
        0.6 .. 33               95      20.0%
        33 .. 59                95      18.9%
        59 .. 99                95      28.4%
        99 .. 353               96      33.3%

    Taking 60 points as the line, decided at 15:19 with no look-ahead:

                            nights  loss rate      net  profit factor
        every night            476      24.2%  257,433           1.25
        time value <= 60       300      20.3%  217,832           1.43
          first half           160      21.2%   63,981           1.24
          second half          140      19.3%  153,852           1.63
          2024 (part)           41      12.2%   46,449           2.59
          2025                 163      22.1%   27,559           1.09
          2026                  96      20.8%  143,825           1.83

    It holds in both halves and in every year, and the threshold is flat from
    40 to 80 points, so it is not a knife edge.  It is also not a liquidity
    artefact: the EXPENSIVE contracts are the illiquid ones (16.1% of exit-day
    minutes never trade, against 7.4% for the cheap ones), so the condition
    improves liquidity as well as the loss rate.

WHAT WAS REJECTED, AND WHY IT IS NOT IN HERE
    * Stop-losses.  Every level on the premium (-5%..-70%) and on NIFTY
      (25..500 points) lowered win rate, net AND profit factor, and none
      reduced the worst night: on 2026-03-30 every stop filled below the 15:14
      low.  The premium paid is the stop.
    * Profit targets.  v2's exit already is one (entry + costs).  Because it
      waits for a whole minute to clear that line, its winners come in at a
      median +6.5% of premium and 28% of them above +20%, and those carry 77%
      of all winning rupees.  A resting limit caps exactly those: +10% reads
      PF 0.60, +20% 0.78, +30% 0.93, +50% 1.13, all below doing nothing.
    * Deeper strikes.  4 -> 8 strikes in moves the loss rate only 26.3% ->
      23.9% while untraded minutes go 3.3% -> 24.1%.  Six is the last strike
      where the worst-fill test still has prices to punish.
    * Signal filters (21 of them: trend agreement, day size, close location,
      range, weekday, previous day).  None survived an out-of-sample split.
    * Carrying a losing night into a second session.  Win rate rises to 81%
      but the average loss grows from 9,540 to 13,121 and profit factor falls
      from 1.23 to 1.08 over five years of spot.

THE LADDER AND THE TIME-VALUE CHECK INTERACT
    The check is a limit on time value, and time value is largest at the money,
    so the check is in effect a requirement that the contract be deep enough in
    the money.  Measured on the nights already priced:

        strike        median time value   nights passing the 60-point check
        6 in the money            45.7                          63.1%
        4 in the money            77.3                          38.0%
        1 in the money           125.6                           8.0%
        at the money             147.1                           2.8%
        1 out of the money       125.0                           5.6%

    So an at-the-money column with the check applied is nearly empty, and that
    is not a bug.  The ladder table therefore shows every rung twice, once with
    the check and once without it, with the share of nights that pass beside
    them.  Read the two together: the "without" column is what that strike does
    as a strategy of its own, the "with" column is what survives this rule's
    condition.

WHAT THIS IS NOT
    * A forecast of the overnight gap.  Nothing here predicts direction; the
      condition only limits what a bad gap can cost.
    * A long history.  The report runs from a fixed 2026-03-01, about seven
      months.  The broker's archive reaches 2024-10 and `--from 2024-10-01`
      still runs it, but even that is two years of real premiums, not five.  On spot alone
      the direction signal goes back to 2022 and wins 74.7% of nights under the
      same exit, but no option P&L exists before 2024-10 and none is estimated
      here.
    * Free of a losing year.  2025 returned PF 1.03 unfiltered and 1.09
      filtered over 245 nights.  A flat year is inside this rule's range.
    * Sized.  One lot risks its whole premium every night, a median Rs 22,787.
      The p99 drawdown per lot is about Rs 155,000, which is what capital must
      be set against, not the premium.

Shares its data layer with eod_trend_signal_v1.py, its pricing helpers with
eod_trend_signal_v2.py and its capital and cost arithmetic with
services/trade_costs.py.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..")
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, SCRIPT_DIR)

import httpx  # noqa: E402
from services.option_pricing import (  # noqa: E402
    CachedPricer, OptionPricer, RateLimiter, atm_strike, _candle_keys)
from services.trade_costs import capital_required, option_round_trip, live_margin  # noqa: E402
from eod_trend_signal_v1 import (  # noqa: E402
    IST, LOT_SIZE, SESSION_START, FEATURE_END, CAS_DATE, PARTIAL_MODES,
    CHART_FULL_DAYS, PX_TOLERANCE_MIN, REPORTS_DIR, RESULTS_DIR,
    _read_access_token, load_nifty, load_daily_ohlc, to_rows, build_sessions,
    daily_series, stats, _px_at, _day_closes)
import eod_trend_signal_v2 as v2  # noqa: E402

REPORT_HTML = os.path.join(REPORTS_DIR, "eod_trend_signal_v3_report.html")
SIGNALS_CSV = os.path.join(RESULTS_DIR, "eod_trend_signal_v3_signals.csv")
TRADES_CSV = os.path.join(RESULTS_DIR, "eod_trend_signal_v3_trades.csv")

# ---- the rule's constants.  None of these is a selector. ----
TV_MINUTE = "15:19"          # the minute the time value is read from
ENTRY_HHMM = "15:20"         # the minute the option is bought in
# The check is a RATIO, not a number of points.  Time value is what you pay ON
# TOP of the option's real value, so the question is what SHARE of the price is
# air - 60 points on a 360 premium is 17% of what you pay, the same 60 points on
# a 150 premium is 40%.  A fixed point limit therefore means something different
# at every strike and on every volatility regime; a share means one thing.
TV_MAX_SHARE = 0.15          # do not trade if time value is more than this share of the premium
TV_MAX_POINTS_OLD = 60.0     # the earlier absolute limit, kept only so the report can show both side by side
# The third way of asking the question, and the one that keeps the trade count
# up: not "is this option dear" but "is it dear COMPARED WITH RECENT NIGHTS".
# A fixed limit is an absolute bar, so in an expensive stretch it rejects nearly
# every night and in a cheap one it rejects none, which is why the trade count
# swings.  Ranking tonight against the recent past holds the traded share
# roughly steady.  It reads only backwards, so it is knowable at 15:19.
TV_RANK_LOOKBACK = 60        # how many past nights tonight is ranked against
TV_RANK_KEEP = 75            # trade when tonight is among the cheapest this many in 100
# Why 75 and not 70.  Over the standing window the level barely matters between
# 60 and 70 - all three read 80.0% - but they trade 85, 90 and 95 nights, and the
# floor asked for is 100.  75 is the first level that clears it:
#   cheapest 60 ->  85 trades, 80.0%, PF 2.08      cheapest 80 -> 109, 76.1%, PF 1.59
#   cheapest 65 ->  90 trades, 80.0%, PF 2.03      cheapest 85 -> 117, 76.1%, PF 1.84
#   cheapest 70 ->  95 trades, 80.0%, PF 1.97      cheapest 90 -> 123, 74.0%, PF 1.58
#   cheapest 75 -> 102 trades, 77.5%, PF 1.80  <- the floor, and the default
# Change this one number to move along that line; nothing else needs touching.
TV_WARMUP_DAYS = 150         # calendar days loaded before the window so the ranking has history
STRIKE_OFFSET = 300          # THE RULE's strike: six in the money, 50 points apart
# The whole ladder is priced every night so the report can show what each strike
# would have done.  Offset is in points from the at-the-money strike, positive =
# INTO the money.  On a BUY (a call) offset +n*50 is the strike the trader calls
# ATM-n; on a SELL (a put) the same offset is ATM+n.  The naming below is by
# moneyness so one label means one thing on both sides.
STRIKES = [(300, "itm6", "6 in the money"), (250, "itm5", "5 in the money"),
           (200, "itm4", "4 in the money"), (150, "itm3", "3 in the money"),
           (100, "itm2", "2 in the money"), (50, "itm1", "1 in the money"),
           (0, "atm", "at the money"),
           (-50, "otm1", "1 out of the money"), (-100, "otm2", "2 out of the money"),
           (-150, "otm3", "3 out of the money"), (-200, "otm4", "4 out of the money"),
           (-250, "otm5", "5 out of the money"), (-300, "otm6", "6 out of the money")]
RULE_STRIKE = "itm6"         # the one the rule trades
EXIT_START = "09:30"         # nothing may fire before this
EXIT_LIMIT = "15:14"         # the fallback minute
CHART_OPT_ENTRY_FROM = "14:00"
STRIKE_STEP = 50

# THE FIXED START (user, 2026-09-20).  The run always begins on this date and
# always ends today, so the window grows by one session a day and never moves
# at the front.  Yesterday's report is therefore a prefix of today's, and two
# runs a week apart can be compared without the start sliding underneath them -
# which is what a rolling "last 6 months" does, and it is why this book's
# headline moved when a big night dropped off the front earlier.
# The broker's option archive itself reaches back to 2024-10-03; running from
# there is still possible with --from, it is simply not the default.
START_DATE = date(2026, 3, 1)
ARCHIVE_START = date(2024, 10, 1)      # the earliest the broker serves, for reference

WIDE_SPOT = ("On spot alone the direction signal runs back to 2022-01: under the same "
             "'first minute whose low clears costs from 09:30' exit it wins 74.7% of 1,156 "
             "nights (76.4 / 72.1 / 77.8 / 73.3 / 73.3% by year) with a mean of +0.044% and "
             "profit factor 1.23. No option P&L exists before 2024-10 and none is estimated.")


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

def compute_signal(s: dict) -> dict:
    """Direction for one session from its own daily bar.  The time-value
    condition is applied later, once the contract has a price."""
    out = {"day": s["day"], "decision": "HOLD", "data_ok": True, "hold_reason": "",
           "day_open": None, "close": None, "day_high": None, "day_low": None,
           "move_pct": None, "loc_day": None, "direction": "HOLD"}
    if not s["valid"]:
        out["data_ok"] = False
        out["hold_reason"] = f"session invalid: {s['invalid_reason']}"
        return out
    out.update(day_open=s["o"], close=s["c"], day_high=s["h"], day_low=s["l"],
               move_pct=(s["c"] / s["o"] - 1.0) * 100.0,
               loc_day=(s["c"] - s["l"]) / (s["h"] - s["l"]) if s["h"] > s["l"] else None)
    if s["c"] > s["o"]:
        out["decision"] = out["direction"] = "BUY"
    elif s["c"] < s["o"]:
        out["decision"] = out["direction"] = "SELL"
    else:
        out["hold_reason"] = "15:14 close equals the 09:15 open"
    return out


def rel_strike(decision: str, off: int) -> str:
    """The strike the way a trader says it: ATM-4 on a BUY is four strikes below
    the money, which for a call is four strikes IN the money."""
    n = abs(off) // STRIKE_STEP
    if n == 0:
        return "ATM"
    into = off > 0                      # into the money for this side
    up = (decision == "SELL") == into   # does the strike sit above the ATM?
    return f"ATM{'+' if up else '-'}{n}"


def build_trades(signals: list[dict], sessions: dict, all_days: list[str]) -> list[dict]:
    """One row per session with a direction, filled or not.  The time-value
    condition has not been applied yet - it needs the option price."""
    pos = {d: k for k, d in enumerate(all_days)}
    out = []
    for sig in signals:
        if sig["direction"] == "HOLD":
            continue
        s = sessions[sig["day"]]
        t = {"day": sig["day"], "decision": sig["direction"], "move_pct": sig["move_pct"],
             "entry_time": ENTRY_HHMM, "entry_spot": None, "exit_day": None,
             "exit_day_assumed": None, "exit_time": None, "exit_spot": None,
             "spot_pts": None, "spot_pct": None, "status": "closed", "legs": {},
             "skipped": False, "skip_reason": ""}
        if s["entry"] is None:
            t["status"] = f"no {ENTRY_HHMM} candle - not filled"
            out.append(t)
            continue
        t["entry_spot"] = s["entry"]["c"]
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
        pts = ((t["exit_spot"] - t["entry_spot"]) if t["decision"] == "BUY"
               else (t["entry_spot"] - t["exit_spot"]))
        t["spot_pts"], t["spot_pct"] = round(pts, 2), pts / t["entry_spot"] * 100.0
        out.append(t)
    return out


# ---------------------------------------------------------------------------
# Pricing - one contract, one exit, worst fills
# ---------------------------------------------------------------------------

def contract_spec(t: dict, off: int = STRIKE_OFFSET) -> tuple[str, float]:
    """(option type, strike) for one night at one rung of the ladder."""
    a = atm_strike(t["entry_spot"])
    return ("CE", a - off) if t["decision"] == "BUY" else ("PE", a + off)


def _exit_day_of(t: dict) -> str:
    return t["exit_day"] or t["exit_day_assumed"]


def _cached(pricer: CachedPricer, t: dict, opt: str, strike: float):
    """The contract and its two days of one-minute OHLC, straight from the cache."""
    for e in v2._expiries_after(pricer.expiries, _exit_day_of(t)):
        key = f"{e.isoformat()}|{strike:.0f}|{opt}"
        c = pricer.contracts.get(key)
        if c:
            c = dict(c, ckey=key)
            eo = next((pricer.ohlc[k] for k in _candle_keys(c, t["day"])
                       if pricer.ohlc.get(k)), {})
            xo = next((pricer.ohlc[k] for k in _candle_keys(c, t["exit_day"])
                       if pricer.ohlc.get(k)), {}) if t["exit_day"] else {}
            return c, eo, xo
    return None, {}, {}


def price_leg(t: dict, off: int, c, eo: dict, xo: dict) -> dict:
    """One rung of the ladder on one night: the time-value check, the entry and
    the exit.  `gated` is True when the contract is too dear to trade."""
    opt, strike = contract_spec(t, off)
    leg = {"offset": off, "symbol": None, "expiry": None, "dte": None, "strike": strike,
           "option_type": opt, "rel_strike": rel_strike(t["decision"], off),
           "instrument_key": None, "tv_price": None, "tv_minute": None, "intrinsic": None,
           "time_value": None, "tv_share": None, "gated": None,
           "tv_cut": None, "tv_rank": None, "tv_n": None,
           "tv_cheapest": None, "tv_dearest": None,
           "entry_px": None, "entry_minute": None,
           "line": None, "exit_px": None, "exit_minute": None, "prem_pts": None,
           "prem_pct": None, "pnl_rs": None, "costs_rs": None, "net_rs": None,
           "capital_rs": None, "qualified": None, "reason": None, "flat_pct": None,
           "entry_px_close": None, "exit_px_close": None, "net_rs_close": None}
    if not c:
        leg["reason"] = "no contract"
        return leg
    leg.update(symbol=c["trading_symbol"], expiry=c["ckey"].split("|")[0],
               instrument_key=c.get("instrument_key"))
    leg["dte"] = (date.fromisoformat(leg["expiry"]) - date.fromisoformat(t["day"])).days
    intrinsic = (t["entry_spot"] - strike) if opt == "CE" else (strike - t["entry_spot"])
    leg["intrinsic"] = round(max(0.0, intrinsic), 2)
    bar, tvm = v2._ohlc_at(eo or {}, TV_MINUTE, -1)
    if not bar:
        leg["reason"] = f"no option print within {PX_TOLERANCE_MIN} min of {TV_MINUTE}"
        return leg
    leg["tv_price"], leg["tv_minute"] = round(bar[3], 2), tvm
    leg["time_value"] = round(bar[3] - leg["intrinsic"], 2)
    leg["tv_share"] = round(leg["time_value"] / bar[3], 4) if bar[3] > 0 else None
    leg["gated"] = leg["tv_share"] is None or leg["tv_share"] > TV_MAX_SHARE
    # the entry and the exit are priced even when the gate blocks the night, so
    # the report can show what a skipped night would have done
    ebar, emin = v2._ohlc_at(eo, ENTRY_HHMM, -1)
    if not ebar:
        leg["reason"] = f"no option print within {PX_TOLERANCE_MIN} min of {ENTRY_HHMM}"
        return leg
    e = ebar[1]
    if e <= 0:
        leg["reason"] = "entry price is not positive"
        return leg
    leg.update(entry_px=round(e, 2), entry_minute=emin, entry_px_close=round(ebar[3], 2),
               capital_rs=capital_required("buy", t["entry_spot"], LOT_SIZE, e))
    leg["line"] = round(e + option_round_trip("buy", e, e, LOT_SIZE)["total"] / LOT_SIZE, 2)
    if not t["exit_day"]:
        leg["reason"] = "open - no exit yet"
        return leg
    if not xo:
        leg["reason"] = "no option candles on the exit day"
        return leg
    ms = [m for m in xo if SESSION_START <= m <= EXIT_LIMIT]
    if ms:
        leg["flat_pct"] = round(sum(1 for m in ms if xo[m][1] == xo[m][2]) / len(ms) * 100, 1)
    x_px = x_min = None
    for m in sorted(xo):
        if m < EXIT_START or m > EXIT_LIMIT:
            continue
        if xo[m][2] > leg["line"]:
            x_px, x_min, leg["qualified"] = xo[m][2], m, True
            break
    if x_px is None:
        bar2, m2 = v2._ohlc_at(xo, EXIT_LIMIT, -1)
        if not bar2:
            leg["reason"] = f"no option print within {PX_TOLERANCE_MIN} min of {EXIT_LIMIT}"
            return leg
        x_px, x_min, leg["qualified"] = bar2[2], m2, False
    pnl = x_px - e
    costs = option_round_trip("buy", e, x_px, LOT_SIZE)["total"]
    leg.update(exit_px=round(x_px, 2), exit_minute=x_min, prem_pts=round(pnl, 2),
               prem_pct=pnl / e * 100.0, pnl_rs=round(pnl * LOT_SIZE, 2),
               costs_rs=costs, net_rs=round(pnl * LOT_SIZE - costs, 2))
    cbar, _ = v2._ohlc_at(xo, x_min, -1)
    if cbar:
        pc = cbar[3] - ebar[3]
        leg["exit_px_close"] = round(cbar[3], 2)
        leg["net_rs_close"] = round(pc * LOT_SIZE - option_round_trip(
            "buy", ebar[3], cbar[3], LOT_SIZE)["total"], 2)
    return leg


async def _fetch(op: OptionPricer, t: dict, opt: str, strike: float) -> bool:
    """Pull one contract's two days into the shared cache."""
    for e in v2._expiries_after(op.expiries, _exit_day_of(t)):
        c = await op._resolve(e, strike, opt)
        if c:
            a = await op.ohlc_for(c, date.fromisoformat(t["day"]))
            if not a:
                a = await _day_closes(op, c, date.fromisoformat(t["day"]))
            b = (await op.ohlc_for(c, date.fromisoformat(t["exit_day"]))
                 if t["exit_day"] else True)
            return bool(a and b)
    return False


async def price_trades(trades: list[dict], offline: bool, token: str | None,
                       chart_from: str | None, ladder_from: str | None = None) -> tuple[int, dict, dict]:
    """Price every night at every rung of the ladder.  The rule's own strike is
    RULE_STRIKE; the rest are carried so the report can show the ladder."""
    priceable = [t for t in trades if t["entry_spot"] is not None]
    if not priceable:
        return 0, {}, []
    pricer = CachedPricer()
    need = []
    for t in priceable:
        for off, key, _lab in STRIKES:
            opt, strike = contract_spec(t, off)
            c, eo, xo = _cached(pricer, t, opt, strike)
            if not (c and eo and (xo or not t["exit_day"])):
                need.append((t, opt, strike))
    if need and not offline and token:
        print(f"  fetching {len(need)} night/strike legs ...")
        client = httpx.AsyncClient(timeout=30.0)
        op = OptionPricer(client, token, RateLimiter(0.42), offline=False)
        await op.load_calendar(date.fromisoformat(min(t["day"] for t, *_ in need)),
                               date.fromisoformat(max(_exit_day_of(t) for t, *_ in need)))
        got = 0
        for i, (t, opt, strike) in enumerate(need, 1):
            got += await _fetch(op, t, opt, strike)
            if i % 50 == 0:
                try:
                    op.save()
                except OSError as exc:
                    print(f"    ! cache save skipped: {exc}")
                print(f"    {i}/{len(need)}")
        try:
            op.save()
        except OSError as exc:
            print(f"    ! cache save skipped: {exc}")
        await client.aclose()
        print(f"  fetched {got}/{len(need)}")
        pricer.reload()
    elif need:
        print(f"  ! {len(need)} legs without option data and no token (offline={offline})")

    option_chart, priced = {}, 0
    for t in priceable:
        t["legs"] = {}
        for off, key, _lab in STRIKES:
            opt, strike = contract_spec(t, off)
            c, eo, xo = _cached(pricer, t, opt, strike)
            t["legs"][key] = price_leg(t, off, c, eo, xo)
            if chart_from and t["day"] >= chart_from and (eo or xo):
                option_chart.setdefault(t["day"], {})[key] = {
                    "e": {m: [round(x, 2) for x in v] for m, v in (eo or {}).items()
                          if m >= CHART_OPT_ENTRY_FROM},
                    "x": {m: [round(x, 2) for x in v] for m, v in (xo or {}).items()}}
        rule = t["legs"][RULE_STRIKE]
        t["skipped"] = bool(rule.get("gated"))
        t["skip_reason"] = (f"time value {rule['time_value']:.1f} pts is "
                            f"{rule['tv_share'] * 100:.0f}% of the {rule['tv_price']:.0f} premium, "
                            f"above the {TV_MAX_SHARE * 100:.0f}% limit"
                            ) if (t["skipped"] and rule.get("tv_share") is not None) else ""
        priced += rule["net_rs"] is not None
    open_now = [t for t in priceable if t["status"].startswith("open")]
    if open_now and not offline and token:
        async with httpx.AsyncClient() as client:
            for t in open_now:
                ik = (t["legs"].get(RULE_STRIKE) or {}).get("instrument_key")
                if ik:
                    m = await live_margin(client, token, ik, "buy", LOT_SIZE)
                    if m is not None:
                        t["legs"][RULE_STRIKE]["capital_rs"] = m
    # the ladder summary, computed once here so the report never has to
    lad_lo = ladder_from or "0000-00-00"   # also keeps the run-up out of the ladder
    ladder = []
    for off, key, lab in STRIKES:
        legs = [t["legs"][key] for t in priceable
                if t["status"] == "closed" and t["day"] >= lad_lo and t["legs"].get(key)]
        ok = [l for l in legs if l["net_rs"] is not None]
        gated = [l for l in ok if l["gated"]]
        taken = [l for l in ok if not l["gated"]]
        old = [l for l in ok if l["time_value"] is not None and l["time_value"] <= TV_MAX_POINTS_OLD]
        tv = [l["time_value"] for l in ok if l["time_value"] is not None]
        tvs = [l["tv_share"] for l in ok if l.get("tv_share") is not None]
        flat = [l["flat_pct"] for l in ok if l["flat_pct"] is not None]
        ladder.append({
            "key": key, "offset": off, "label": lab, "n": len(ok),
            "median_tv": round(statistics.median(tv), 1) if tv else None,
            "median_tv_share": round(statistics.median(tvs) * 100, 1) if tvs else None,
            "median_premium": round(statistics.median([l["entry_px"] for l in ok]), 1) if ok else None,
            "flat_pct": round(statistics.fmean(flat), 1) if flat else None,
            "pass_pct": round(len(taken) / len(ok) * 100, 1) if ok else None,
            "all": _agg([l["net_rs"] for l in ok]),
            "gated_off": _agg([l["net_rs"] for l in ok]),
            "gated_on": _agg([l["net_rs"] for l in taken]),
            "old_on": _agg([l["net_rs"] for l in old]),
            "old_pass_pct": round(len(old) / len(ok) * 100, 1) if ok else None,
            "removed": _agg([l["net_rs"] for l in gated])})
    lad_days = sorted({t["day"] for t in priceable
                       if t["status"] == "closed" and t["day"] >= lad_lo})
    return priced, option_chart, {"rows": ladder, "from": lad_lo,
                                  "to": lad_days[-1] if lad_days else None,
                                  "sessions": len(lad_days)}


def add_rolling_rank(trades: list[dict]) -> None:
    """For every night and every rung, where tonight's time-value share sits
    among the previous TV_RANK_LOOKBACK nights at that same rung.

    `tv_cut` is the level that TV_RANK_KEEP nights in 100 sat below; tonight
    trades when its own share is at or under that level.  `tv_rank` is where
    tonight actually fell, as a percentile, purely so the report can say it.
    """
    hist: dict[str, list[float]] = defaultdict(list)
    for t in sorted(trades, key=lambda x: x["day"]):
        for key, leg in (t.get("legs") or {}).items():
            share = leg.get("tv_share")
            if share is None:
                continue
            past = hist[key]
            if len(past) >= 20:                       # enough to rank against
                window = past[-TV_RANK_LOOKBACK:]
                ordered = sorted(window)
                idx = min(len(ordered) - 1, int(len(ordered) * TV_RANK_KEEP / 100))
                leg["tv_cut"] = round(ordered[idx], 4)
                leg["tv_n"] = len(window)
                below = sum(1 for x in window if x < share)
                leg["tv_rank"] = round(below / len(window) * 100, 1)
                leg["tv_cheapest"] = round(ordered[0], 4)
                leg["tv_dearest"] = round(ordered[-1], 4)
            past.append(share)


def _agg(nets: list[float]) -> dict:
    if not nets:
        return {"n": 0}
    w = [x for x in nets if x > 0]
    l = [x for x in nets if x < 0]
    gw, gl = sum(w), -sum(l)
    cum = peak = dd = 0.0
    for v in nets:
        cum += v
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    return {"n": len(nets), "wins": len(w), "losses": len(l),
            "win": len(w) / len(nets) * 100, "total": sum(nets),
            "pf": (gw / gl) if gl else None, "dd": dd, "worst": min(nets)}


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------

def book(trades: list[dict], key: str = RULE_STRIKE) -> dict:
    taken = [t for t in trades if t["status"] == "closed"
             and (t.get("legs") or {}).get(key)
             and not t["legs"][key]["gated"] and t["legs"][key]["net_rs"] is not None]
    nets = [t["legs"][key]["net_rs"] for t in taken]
    s = stats(nets)
    gross = sum(t["legs"][key]["pnl_rs"] for t in taken) if taken else None
    costs = sum(t["legs"][key]["costs_rs"] for t in taken) if taken else None
    cum = peak = dd = 0.0
    for v in nets:
        cum += v
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    wins = [v for v in nets if v > 0]
    losses = [v for v in nets if v < 0]
    streak = best = cur = 0
    for v in nets:
        if v < 0:
            cur += 1
            streak = max(streak, cur)
        else:
            cur = 0
    cur = 0
    for v in nets:
        if v > 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    caps = [t["legs"][key]["capital_rs"] for t in taken if t["legs"][key]["capital_rs"]]
    return {"signals": len(trades), "taken": len(taken),
            "skipped": sum(1 for t in trades if t["skipped"]),
            "rs": s, "gross": gross, "costs": costs, "maxdd": dd,
            "avg_win": statistics.fmean(wins) if wins else None,
            "avg_loss": statistics.fmean(losses) if losses else None,
            "loss_streak": streak, "win_streak": best,
            "cap_avg": statistics.fmean(caps) if caps else None,
            "spot": stats([t["spot_pct"] for t in trades
                           if t["status"] == "closed" and t["spot_pct"] is not None]),
            "tv_avg": statistics.fmean([t["legs"][key]["time_value"] for t in taken
                                        if t["legs"][key]["time_value"] is not None]) if taken else None}


def grouped(trades: list[dict], key) -> list[dict]:
    g: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        g[key(t)].append(t)
    return [{"key": k, **book(g[k])} for k in sorted(g)]


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _r(v, d=4):
    return "" if v is None else f"{v:.{d}f}"


def write_signals_csv(signals, trades, path):
    tby = {t["day"]: t for t in trades}
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "direction", "day_open", "close_1514", "move_pct",
                    "traded", "time_value", "tv_share_pct", "tv_limit_pct", "hold_reason"])
        for x in signals:
            t = tby.get(x["day"])
            lg = ((t or {}).get("legs") or {}).get(RULE_STRIKE) or {}
            traded = "yes" if (t and not t["skipped"] and lg.get("entry_px")) else "no"
            reason = x["hold_reason"] or (t["skip_reason"] if t and t["skipped"] else
                                          (lg.get("reason") or "") if t else "")
            w.writerow([x["day"], x["direction"], _r(x["day_open"], 2), _r(x["close"], 2),
                        _r(x["move_pct"]), traded, _r(lg.get("time_value"), 2),
                        _r(None if lg.get("tv_share") is None else lg["tv_share"] * 100, 1),
                        TV_MAX_SHARE * 100, reason])
    print(f"  signals -> {path}")


def write_trades_csv(trades, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "decision", "move_pct", "entry_spot", "strike", "option_type",
                    "symbol", "expiry", "dte", "tv_minute", "tv_price", "intrinsic",
                    "time_value", "tv_share_pct", "traded", "skip_reason", "entry_minute", "entry_px",
                    "line", "exit_day", "exit_minute", "exit_px", "qualified", "prem_pts",
                    "prem_pct", "pnl_rs", "costs_rs", "net_rs", "capital_rs",
                    "entry_px_close", "exit_px_close", "net_rs_close", "spot_pct", "status"])
        for t in trades:
            l = (t.get("legs") or {}).get(RULE_STRIKE) or {}
            w.writerow([t["day"], t["decision"], _r(t["move_pct"]), _r(t["entry_spot"], 2),
                        _r(l.get("strike"), 0), l.get("option_type", ""), l.get("symbol", ""),
                        l.get("expiry", ""), l.get("dte", ""), l.get("tv_minute", ""),
                        _r(l.get("tv_price"), 2), _r(l.get("intrinsic"), 2),
                        _r(l.get("time_value"), 2),
                        _r(None if l.get("tv_share") is None else l["tv_share"] * 100, 1),
                        "no" if t["skipped"] else "yes",
                        t["skip_reason"] or (l.get("reason") or ""),
                        l.get("entry_minute", ""), _r(l.get("entry_px"), 2),
                        _r(l.get("line"), 2), t["exit_day"] or "", l.get("exit_minute", ""),
                        _r(l.get("exit_px"), 2), l.get("qualified", ""),
                        _r(l.get("prem_pts"), 2), _r(l.get("prem_pct")),
                        _r(l.get("pnl_rs"), 2), _r(l.get("costs_rs"), 2),
                        _r(l.get("net_rs"), 2), _r(l.get("capital_rs"), 2),
                        _r(l.get("entry_px_close"), 2), _r(l.get("exit_px_close"), 2),
                        _r(l.get("net_rs_close"), 2), _r(t["spot_pct"]), t["status"]])
    print(f"  trades  -> {path}")


def verdict(trades, label):
    b = book(trades)
    if not b["rs"]["n"]:
        return f"{label}: no priced night."
    r = b["rs"]
    return (f"<b>{label}.</b> {b['signals']} sessions with a direction, {b['skipped']} skipped by the "
            f"time-value condition, <b>{r['n']} traded</b>. "
            f"{r['wins']} wins / {r['losses']} losses = <b>{r['win_rate']:.1f}%</b> net of costs; "
            f"gross Rs {b['gross']:,.0f} less brokerage and taxes Rs {b['costs']:,.0f} = "
            f"<b>net Rs {r['total']:,.0f}</b> on one lot, profit factor <b>{r['pf']:.2f}</b>, "
            f"worst night Rs {r['worst']:,.0f}, deepest drawdown Rs {b['maxdd']:,.0f}, "
            f"longest losing run {b['loss_streak']} nights.")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EOD trend signal v3 - the live rule</title>
<style>
  :root{--bg:#0f1115;--surface:#171a21;--surface2:#1d212a;--ink:#e8eaf0;--ink2:#aeb4c2;--muted:#79808f;
        --grid:#262b36;--up:#3fb950;--down:#f85149;--accent:#58a6ff;--warn:#d29922;--line:#2a2f3a}
  @media (prefers-color-scheme: light){:root{--bg:#f6f7f9;--surface:#fff;--surface2:#f0f2f5;--ink:#11151c;
        --ink2:#39404e;--muted:#6b7280;--grid:#e3e6ec;--up:#1a7f37;--down:#cf222e;--accent:#0969da;
        --warn:#9a6700;--line:#d8dce3}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
  .wrap{max-width:1280px;margin:0 auto;padding:22px 16px 80px}
  h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:30px 0 8px;color:var(--ink)}
  h3{font-size:14px;margin:18px 0 6px;color:var(--ink2)}
  .sub{color:var(--muted);font-size:12.5px;margin-bottom:10px}
  .panel{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
  .live{border-left:4px solid var(--accent)}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:10px 0}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:9px;padding:10px 12px}
  .card .k{color:var(--muted);font-size:11.5px;margin-bottom:3px}
  .card .v{font-size:19px;font-weight:600}
  table{border-collapse:collapse;width:100%;font-size:12.5px}
  th,td{padding:5px 8px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
  th{color:var(--muted);font-weight:600;text-align:right;position:sticky;top:0;background:var(--surface)}
  th.l,td.l{text-align:left}
  tbody tr:hover{background:var(--surface2)}
  .scroll{overflow:auto;border:1px solid var(--line);border-radius:9px;background:var(--surface);max-height:560px}
  .pos{color:var(--up)} .neg{color:var(--down)} .dimc{color:var(--muted)}
  .pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;font-weight:600}
  .pill.BUY{background:rgba(63,185,80,.16);color:var(--up)} .pill.SELL{background:rgba(248,81,73,.16);color:var(--down)}
  .pill.HOLD{background:rgba(121,128,143,.18);color:var(--muted)}
  .pill.skip{background:rgba(210,153,34,.18);color:var(--warn)}
  .setup{border-radius:9px;padding:10px 12px;font-size:13px;border:1px solid var(--line);background:var(--surface)}
  .setup.pos{border-left:4px solid var(--up)} .setup.neg{border-left:4px solid var(--down)}
  .setup.dim{border-left:4px solid var(--muted)}
  .r{display:inline-block;min-width:78px;color:var(--muted);font-size:11.5px}
  .chartbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0}
  .chartbar label{color:var(--muted);font-size:12px;display:flex;gap:5px;align-items:center}
  select,button{background:var(--surface2);color:var(--ink);border:1px solid var(--line);border-radius:7px;
        padding:5px 9px;font-size:12.5px;font-family:inherit}
  button{cursor:pointer} button:hover{border-color:var(--accent)}
  svg{width:100%;height:auto;background:var(--surface);border:1px solid var(--line);border-radius:9px;touch-action:none}
  svg.drag{cursor:grabbing}
  #tip{position:fixed;pointer-events:none;display:none;background:var(--surface2);border:1px solid var(--line);
       border-radius:7px;padding:6px 9px;font-size:11.5px;z-index:9;white-space:pre}
  ol.steps{padding-left:18px;margin:6px 0} ol.steps li{margin:5px 0}
  .warn{border-left:4px solid var(--warn)}
</style></head><body><div class="wrap">
<h1>EOD trend signal &mdash; v3, the live rule</h1>
<div class="sub" id="sub"></div>

<div class="panel live" id="livePanel"></div>

<h2>The rule, in six steps</h2>
<div class="panel"><ol class="steps" id="steps"></ol></div>

<h2>The check, worked through</h2>
<div class="sub">The rule buys only when the time value is a small enough <b>share</b> of what you pay. Here is the arithmetic, first as a plain illustration and then on real nights out of this book.</div>
<div class="panel" id="howBox"></div>
<h3>The same 60 points is a different bet at a different premium</h3>
<div class="sub">This is why the check is a share and not a number of points. Every row below pays exactly the same 60, 50 or 60 points of time value, but it is a very different fraction of the money at risk.</div>
<div class="scroll"><table id="tblIllo"></table></div>
<h3>Three real nights</h3>
<div class="scroll"><table id="tblEx"></table></div>
<div class="panel" id="disagreeBox" style="margin-top:10px"></div>

<h2>The strike ladder &mdash; every rung, priced on the same nights</h2>
<div class="sub" id="ladderSub">The rule buys <b>six strikes in the money</b>. Every other rung is priced on exactly the same nights so you can see what it would have done. <b>With the check</b> applies the 60-point time-value limit; <b>without</b> trades every night regardless. Near the money almost the whole premium IS time value, so the check removes nearly every night there &mdash; the "nights passing" column shows it.</div>
<div class="scroll"><table id="tblLadder"></table></div>

<h2>Result</h2>
<div class="chartbar"><select id="winSel"></select><select id="strikeSel"></select><select id="checkSel"></select><span class="dimc" id="winNote"></span></div>
<div class="setup" id="verdict"></div>
<div class="cards" id="cards"></div>

<h2>Equity, one lot, net of costs</h2>
<svg id="eq" viewBox="0 0 1200 300" preserveAspectRatio="xMidYMid meet"></svg>

<h2>Chart &mdash; the index above, the contract you bought below</h2>
<div class="chartbar">
  <select id="daySel"></select>
  <label><input type="checkbox" id="showQual" checked> mark every qualifying minute</label>
  <button id="zoomFocus">14:30 &rarr; 10:00</button><button id="zoomIn">+</button><button id="zoomOut">&minus;</button><button id="zoomReset">both sessions</button>
  <span class="dimc" id="dayTag"></span>
</div>
<div class="setup dim" id="setupBanner"></div>
<svg id="chart" viewBox="0 0 1200 320" preserveAspectRatio="xMidYMid meet"></svg>
<div class="setup dim" id="optHead" style="margin:10px 0 4px"></div>
<svg id="ochart" viewBox="0 0 1200 380" preserveAspectRatio="xMidYMid meet"></svg>
<div id="tip"></div>

<h2>Cross-check &mdash; the exit day minute by minute</h2>
<div class="sub" id="verifySub"></div>
<div class="chartbar"><label><input type="checkbox" id="verifyAll"> every minute (otherwise 09:30 to the sale)</label>
  <span class="dimc" id="verifyTag"></span></div>
<div class="scroll" style="max-height:420px"><table id="tblVerify"></table></div>

<h2>By month</h2><div class="scroll"><table id="tblMonth"></table></div>
<h2>By year, by half, and across the closing-auction change</h2><div class="scroll"><table id="tblStab"></table></div>

<h2>What the time-value condition removed</h2>
<div class="sub">Every night the direction fired but the option was too expensive. These were not traded. The column on the right is what they would have done if they had been.</div>
<div class="scroll" style="max-height:420px"><table id="tblSkip"></table></div>

<h2>Trades</h2><div class="scroll"><table id="tblTrades"></table></div>
<h2>Every session</h2><div class="scroll"><table id="tblLog"></table></div>

<h2>What was tested and left out</h2>
<div class="panel" id="rejected"></div>
<h2>What this is not</h2>
<div class="panel warn" id="caveats"></div>

<script>
const DATA = __DATA_JSON__;
const M = DATA.meta;
const $ = id => document.getElementById(id);
const fmt = (v, d = 2) => (v === null || v === undefined) ? '&mdash;'
  : (typeof v === 'number' ? v.toLocaleString('en-IN', {minimumFractionDigits: d, maximumFractionDigits: d}) : v);
const sign = v => (v === null || v === undefined) ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));
const cell = (v, d = 2, s = '') => '<td class="' + sign(v) + '">' + fmt(v, d) + (v === null || v === undefined ? '' : s) + '</td>';
const plain = (v, d = 2, s = '') => '<td>' + fmt(v, d) + (v === null || v === undefined ? '' : s) + '</td>';
const pill = d => '<span class="pill ' + d + '">' + d + '</span>';
function fill(sel, opts, cur) { sel.innerHTML = opts.map(o => '<option value="' + o.k + '"' + (o.k === cur ? ' selected' : '') + '>' + o.v + '</option>').join(''); }

/* The check is selectable so the two versions can be compared on the same
   nights.  'share15' is the rule; the others are here for comparison only. */
const CHECKS = [
  {k: 'share15', v: 'check: time value ≤ ' + M.tv_max_share + '% of the premium  ← the rule',
   fn: l => l && l.tv_share !== null && l.tv_share !== undefined && l.tv_share <= M.tv_max_share / 100},
  {k: 'pts60', v: 'check: time value ≤ ' + M.tv_max_points_old + ' points (the earlier version)',
   fn: l => l && l.time_value !== null && l.time_value !== undefined && l.time_value <= M.tv_max_points_old},
  {k: 'rank', v: 'check: cheaper than ' + M.tv_rank_keep + ' nights in 100 recently  ← the most trades',
   fn: l => l && l.tv_cut !== null && l.tv_cut !== undefined && l.tv_share !== null
        && l.tv_share !== undefined && l.tv_share <= l.tv_cut},
  {k: 'none', v: 'no check — trade every night', fn: l => true},
];
let curWin = DATA.default_view, curStrike = M.rule_strike, curCheck = 'share15';
const checkFn = () => (CHECKS.find(c => c.k === curCheck) || CHECKS[0]).fn;
const readable = l => !!l && l.tv_share !== null && l.tv_share !== undefined
  && l.time_value !== null && l.time_value !== undefined;
const blocked = l => readable(l) && !checkFn()(l);
function whyBlocked(l) {
  if (!l) return '';
  if (curCheck === 'rank') {
    if (l.tv_cut === null || l.tv_cut === undefined) return 'not enough earlier nights yet to rank this one';
    return 'dearer than ' + fmt(l.tv_rank, 0) + ' nights in 100 recently, and only the cheapest '
      + M.tv_rank_keep + ' are taken';
  }
  if (curCheck === 'pts60') return 'time value ' + fmt(l.time_value, 1) + ' pts > ' + M.tv_max_points_old + ' pts';
  return 'time value ' + fmt(l.time_value, 1) + ' pts = ' + fmt(l.tv_share * 100, 0) + '% of the ' + fmt(l.tv_price, 0) + ' premium, over ' + M.tv_max_share + '%';
}
let V = DATA.views[curWin];
const VT = () => DATA.trades.filter(t => t.day >= V.from);
const VS = () => DATA.signals.filter(x => x.day >= V.from);
const leg = t => (t && t.legs) ? (t.legs[curStrike] || null) : null;
const isTaken = t => { const l = leg(t); return t.status === 'closed' && l && !blocked(l) && l.net_rs !== null && l.net_rs !== undefined; };
fill($('winSel'), Object.keys(DATA.views).map(k => ({k, v: DATA.views[k].label})), curWin);
fill($('strikeSel'), M.strikes.map(x => ({k: x.key, v: x.label + (x.key === M.rule_strike ? '  ← the rule' : '')})), curStrike);
$('winSel').onchange = () => { curWin = $('winSel').value; V = DATA.views[curWin]; renderAll(); };
$('strikeSel').onchange = () => { curStrike = $('strikeSel').value; renderAll(); };
fill($('checkSel'), CHECKS.map(c => ({k: c.k, v: c.v})), curCheck);
$('checkSel').onchange = () => { curCheck = $('checkSel').value; renderAll(); };

function stat(vals) {
  const v = vals.filter(x => x !== null && x !== undefined);
  if (!v.length) return {n: 0};
  const w = v.filter(x => x > 0), l = v.filter(x => x < 0);
  const gw = w.reduce((a, b) => a + b, 0), gl = -l.reduce((a, b) => a + b, 0);
  let cum = 0, peak = 0, dd = 0;
  v.forEach(x => { cum += x; peak = Math.max(peak, cum); dd = Math.min(dd, cum - peak); });
  return {n: v.length, wins: w.length, losses: l.length, win: w.length / v.length * 100,
          total: v.reduce((a, b) => a + b, 0), pf: gl ? gw / gl : null, dd,
          avgW: w.length ? gw / w.length : null, avgL: l.length ? -gl / l.length : null,
          worst: Math.min(...v), best: Math.max(...v)};
}
const taken = ts => ts.filter(isTaken);
function bookOf(ts) {
  const tk = taken(ts), s = stat(tk.map(t => leg(t).net_rs));
  s.gross = tk.reduce((a, t) => a + leg(t).pnl_rs, 0);
  s.costs = tk.reduce((a, t) => a + leg(t).costs_rs, 0);
  s.skipped = ts.filter(t => { const l = leg(t); return l && blocked(l); }).length;
  s.signals = ts.length;
  /* nights with a direction that this strike could not be priced on at all.
     Only the rule's own strike is fetched over the whole history; the rest of
     the ladder is fetched over the report's 6-month window, so outside it this
     number is large and the figures beside it cover fewer nights. */
  s.nodata = ts.filter(t => { const l = leg(t); return t.status === 'closed' && (!l || l.net_rs === null || l.net_rs === undefined) && !(l && blocked(l)); }).length;
  const tv = tk.map(t => leg(t).time_value).filter(x => x !== null && x !== undefined);
  s.tv = tv.length ? tv.reduce((a, b) => a + b, 0) / tv.length : null;
  let cur = 0, ls = 0, ws = 0, cw = 0;
  tk.forEach(t => { if (leg(t).net_rs < 0) { cur++; ls = Math.max(ls, cur); cw = 0; } else { cur = 0; cw++; ws = Math.max(ws, cw); } });
  s.lossStreak = ls; s.winStreak = ws;
  const caps = tk.map(t => leg(t).capital_rs).filter(x => x);
  s.cap = caps.length ? caps.reduce((a, b) => a + b, 0) / caps.length : null;
  return s;
}
function yn(ok) { return ok ? '<span class="pos">pass</span>' : '<span class="neg">no trade</span>'; }
function renderHow() {
  const X = M.examples;
  $('howBox').innerHTML =
    '<div style="font-weight:600;margin-bottom:6px">Three numbers, read at ' + M.tv_minute + '</div>' +
    '<ol class="steps">' +
    '<li><b>Intrinsic value</b> = how far the strike sits from the index = <b>| index &minus; strike |</b>. It is the part of the premium that is real: if the option expired now, this is what it would be worth. At six strikes in the money it is about 300 points.</li>' +
    '<li><b>Time value</b> = <b>premium &minus; intrinsic</b>. This is the part you pay for time and for the market&rsquo;s expectation of movement. It is the part that can evaporate on its own, without the index going against you.</li>' +
    '<li><b>The check</b> = time value &divide; premium. Trade only when that share is <b>' + M.tv_max_share + '% or less</b>.</li>' +
    '</ol>' +
    '<div style="margin-top:12px;font-weight:600">The third way of asking it, and the one that trades most nights</div>' +
    '<div style="line-height:1.7">A fixed limit, whether ' + M.tv_max_points_old + ' points or ' + M.tv_max_share + '%, is an <b>absolute</b> bar. Options are dear when the market expects movement and cheap when it does not, so in a nervous stretch an absolute bar rejects almost every night, and in a quiet one it rejects almost none. That is why the number of trades swings so much.<br><br>' +
    'The ranking asks a different question: <b>not &ldquo;is this option dear&rdquo; but &ldquo;is it dear compared with the nights just gone&rdquo;.</b> In practice:' +
    '<ol class="steps">' +
    '<li>Take the time-value share of each recent night and <b>line them up cheapest to dearest</b>.</li>' +
    '<li>Find the level that <b>' + M.tv_rank_keep + ' nights out of every 100 sit below</b>. That is tonight&rsquo;s bar, and it moves as the market does.</li>' +
    '<li>If tonight&rsquo;s share is <b>at or under</b> that level, trade. If tonight is among the <b>dearest ' + (100 - M.tv_rank_keep) + ' in 100</b>, stand aside.</li>' +
    '</ol>' +
    'So it always skips roughly the dearest ' + (100 - M.tv_rank_keep) + ' nights in every 100, whatever the market is charging. The bar rises by itself when options get expensive across the board, and falls back when they cheapen, which is what keeps the trade count steady instead of collapsing in a nervous month.<br><br>' +
    '<b>Where ' + M.tv_rank_keep + ' came from.</b> The level is a dial, not a discovery. Taking only the cheapest 60, 65 or 70 nights in 100 all win the same 80.0% on this window, but they trade 85, 90 and 95 nights; taking the cheapest 75 trades 102 at 77.5%, and 85 trades 117 at 76.1%. ' + M.tv_rank_keep + ' is set where it is because a hundred trades was the floor asked for. Tightening it buys win rate and gives up trades, one for the other, smoothly.</div>' +
    '<div class="dimc" style="line-height:1.6;margin-top:10px">The earlier version of this rule used a flat <b>' + M.tv_max_points_old + ' points</b> of time value instead of a share. ' +
    'That is the same test only when the premium happens to be about ' + fmt(M.tv_max_points_old / (M.tv_max_share / 100), 0) + '. Below that premium, ' + M.tv_max_points_old + ' points is a bigger fraction of your money than ' + M.tv_max_share + '% allows, and the flat limit lets the night through anyway.</div>';
  $('tblIllo').innerHTML = '<thead><tr><th>premium you pay</th><th>intrinsic value</th><th>time value</th>' +
    '<th>time value as % of premium</th><th class="l">' + M.tv_max_points_old + '-point check</th><th class="l">' + M.tv_max_share + '% check</th><th class="l">do they agree?</th></tr></thead><tbody>' +
    X.illustration.map(r => '<tr' + (r.pass60 !== r.pass15 ? ' style="background:var(--surface2)"' : '') + '>' +
      plain(r.premium, 0) + plain(r.intrinsic, 0) + plain(r.tv, 0) +
      '<td class="' + (r.pass15 ? 'pos' : 'neg') + '">' + fmt(r.share, 1) + '%</td>' +
      '<td class="l">' + yn(r.pass60) + '</td><td class="l">' + yn(r.pass15) + '</td>' +
      '<td class="l">' + (r.pass60 === r.pass15 ? '<span class="dimc">yes</span>' : '<b class="neg">no &mdash; the points test is too loose here</b>') + '</td></tr>').join('') +
    '</tbody>';
  $('tblEx').innerHTML = '<thead><tr><th class="l">night</th><th class="l">side</th><th>index at ' + M.entry_hhmm + '</th>' +
    '<th class="l">contract</th><th>premium at ' + M.tv_minute + '</th><th>&minus; intrinsic</th><th>= time value</th>' +
    '<th>as % of premium</th><th class="l">' + M.tv_max_points_old + ' pts</th><th class="l">' + M.tv_max_share + '%</th><th class="l">what happened</th></tr></thead><tbody>' +
    X.nights.map(r => {
      const outcome = r.pass15
        ? 'bought ' + fmt(r.entry_px, 2) + ', line ' + fmt(r.line, 2) + ', sold ' + fmt(r.exit_px, 2) + ' at ' + r.exit_minute +
          (r.qualified ? '' : ' (fallback)') + ' &rarr; <b class="' + sign(r.net_rs) + '">&#8377;' + fmt(r.net_rs, 0) + '</b>'
        : '<span class="dimc">not traded. Had it been: &#8377;' + fmt(r.net_rs, 0) + '</span>';
      return '<tr><td class="l">' + r.day + '<div class="dimc" style="font-size:11px">' + r.title + '</div></td>' +
        '<td class="l">' + pill(r.decision) + '</td>' + plain(r.spot, 2) +
        '<td class="l">' + r.symbol + '<div class="dimc" style="font-size:11px">' + r.rel + '</div></td>' +
        plain(r.premium, 2) + plain(r.intrinsic, 2) + plain(r.time_value, 2) +
        '<td class="' + (r.pass15 ? 'pos' : 'neg') + '">' + fmt(r.share, 1) + '%</td>' +
        '<td class="l">' + yn(r.pass60) + '</td><td class="l">' + yn(r.pass15) + '</td>' +
        '<td class="l">' + outcome + '</td></tr>'; }).join('') + '</tbody>';
  $('disagreeBox').innerHTML = '<b>How often do the two disagree?</b> On the rule&rsquo;s own strike over this whole book: ' +
    '<b>' + X.both + '</b> nights pass both, <b>' + X.only60 + '</b> pass the ' + M.tv_max_points_old + '-point test but fail the ' + M.tv_max_share + '% one, and <b>' + X.only15 + '</b> the other way round. ' +
    'So the share test is a strict subset of the points test. Those <b>' + X.only60 + '</b> extra nights the points test would have taken won ' +
    '<b>' + fmt(X.only60_win, 1) + '%</b> and made <b class="' + sign(X.only60_net) + '">&#8377;' + fmt(X.only60_net, 0) + '</b> between them &mdash; which is why they are left out.';
}
function renderLadder() {
  const cur = M.rule_strike, L = M.ladder;
  $('ladderSub').innerHTML = 'Every rung priced on the same <b>' + L.sessions + ' nights</b>, ' + L.from + ' &rarr; ' + L.to +
    '. The rule buys <b>six strikes in the money</b>; its own figures elsewhere on this page cover the full history. ' +
    '<b>With the check</b> applies the ' + M.tv_max_share + '% time-value limit, <b>without</b> trades every night. ' +
    'Near the money almost the whole premium IS time value, so the check removes nearly every night there &mdash; read the "nights passing" column beside it. ' +
    '<b>Read the two halves of this table as different questions.</b> Without the check, the ladder is monotone: the further in the money, the higher the win rate and the better the profit factor, while the drawdown shrinks going out of the money only because the bets get smaller. ' +
    '<b>And the check does not mean the same thing at every rung.</b> On an in-the-money strike, time value is what you pay ON TOP of real value, so the check says "do not overpay for time". Out of the money there is no intrinsic value at all, so time value IS the whole premium and the same 60-point test becomes "only buy if the option costs under 60 points" &mdash; a cheapness rule, not the rule this strategy was built on. That is why the passing share falls to 5% at the money and then climbs again further out. ' +
    '"Untraded minutes" is the share of the exit day in which the contract never traded: where that is high the worst-fill test has no price to punish and the row flatters itself. Rows with only a handful of trades settle nothing.';
  $('tblLadder').innerHTML = '<thead><tr><th class="l">strike</th><th>median premium</th><th>median time value</th><th>as % of premium</th>' +
    '<th>untraded minutes</th><th>nights passing the check</th>' +
    '<th>' + M.tv_max_share + '%: traded</th><th>win %</th><th>net &#8377;</th><th>PF</th>' +
    '<th>' + M.tv_max_points_old + ' pts: traded</th><th>win %</th><th>net &#8377;</th><th>PF</th>' +
    '<th>no check: traded</th><th>win %</th><th>net &#8377;</th><th>PF</th></tr></thead><tbody>' +
    L.rows.map(r => { const on = r.gated_on, old = r.old_on || {}, off = r.all;
      return '<tr' + (r.key === cur ? ' style="font-weight:700;background:var(--surface2)"' : '') + '>' +
        '<td class="l">' + r.label + (r.key === cur ? ' &#9664; the rule' : '') + '</td>' +
        plain(r.median_premium, 1) + plain(r.median_tv, 1) + plain(r.median_tv_share, 1, '%') + plain(r.flat_pct, 1, '%') + plain(r.pass_pct, 1, '%') +
        '<td>' + (on.n || 0) + '</td>' + plain(on.n ? on.win : null, 1, '%') + cell(on.n ? on.total : null, 0) + plain(on.pf, 2) +
        '<td>' + (old.n || 0) + '</td>' + plain(old.n ? old.win : null, 1, '%') + cell(old.n ? old.total : null, 0) + plain(old.pf, 2) +
        '<td>' + (off.n || 0) + '</td>' + plain(off.n ? off.win : null, 1, '%') + cell(off.n ? off.total : null, 0) + plain(off.pf, 2) + '</tr>'; }).join('') + '</tbody>';
}

/* ---------- live panel ---------- */
function renderLive() {
  const p = $('livePanel'), L = DATA.live;
  if (!L) { p.innerHTML = '<b>No open signal.</b>'; return; }
  const rows = [];
  rows.push('<div style="font-weight:600;font-size:15px;margin-bottom:6px">' + L.headline + '</div>');
  L.lines.forEach(x => rows.push('<div style="margin:3px 0">' + x + '</div>'));
  p.innerHTML = rows.join('');
}

/* ---------- steps ---------- */
function renderSteps() {
  const steps = M.steps.slice();
  if (curCheck === 'rank')
    steps[3] = 'At <b>' + M.tv_minute + '</b>, work out the <b>time value</b> as before: the contract&rsquo;s price minus its intrinsic value, divided by the price. Then line up the same figure for the recent nights, cheapest to dearest, and find the level that <b>' + M.tv_rank_keep + ' nights in 100 sit below</b>. If tonight is at or under that level, trade. If tonight is among the <b>dearest ' + (100 - M.tv_rank_keep) + ' in 100</b>, do not trade. The bar moves with the market instead of being a fixed number, so a nervous month does not stop you trading altogether.';
  else if (curCheck === 'pts60')
    steps[3] = 'At <b>' + M.tv_minute + '</b>, read the contract&rsquo;s price and subtract its intrinsic value. If what is left &mdash; the <b>time value</b> &mdash; is more than <b>' + M.tv_max_points_old + ' points</b>, do not trade tonight. This is the earlier version of the check and it is kept only for comparison: the same 60 points is a sixth of a 360 premium but a third of a 180 one.';
  else if (curCheck === 'none')
    steps[3] = '<span class="dimc">No check is selected, so every night with a direction is traded. This is the baseline the checks are measured against.</span>';
  $('steps').innerHTML = steps.map(x => '<li>' + x + '</li>').join('');
}
renderSteps();
$('rejected').innerHTML = M.rejected.map(r => '<div style="margin:6px 0"><b>' + r[0] + '</b> &mdash; ' + r[1] + '</div>').join('');
$('caveats').innerHTML = M.caveats.map(r => '<div style="margin:6px 0">' + r + '</div>').join('');

/* ---------- tables ---------- */
const HEAD = '<th>sessions</th><th>skipped</th><th>traded</th><th>W / L</th><th>win %</th><th>gross &#8377;</th><th>costs &#8377;</th><th>net &#8377;</th><th>PF</th><th>avg win</th><th>avg loss</th><th>worst</th><th>max DD</th>';
function rowOf(b) {
  return '<td>' + b.signals + '</td><td>' + b.skipped + '</td><td>' + (b.n || 0) + '</td>' +
    '<td><span class="pos">' + (b.wins || 0) + '</span> / <span class="neg">' + (b.losses || 0) + '</span></td>' +
    plain(b.n ? b.win : null, 1, '%') + cell(b.n ? b.gross : null, 0) + cell(b.n ? -b.costs : null, 0) +
    cell(b.n ? b.total : null, 0) + plain(b.pf, 2) + cell(b.avgW, 0) + cell(b.avgL, 0) + cell(b.worst, 0) + cell(b.dd, 0);
}
function groupTable(id, label, groups) {
  $(id).innerHTML = '<thead><tr><th class="l">' + label + '</th>' + HEAD + '</tr></thead><tbody>' +
    groups.map(g => '<tr><td class="l">' + g.key + '</td>' + rowOf(bookOf(g.rows)) + '</tr>').join('') + '</tbody>';
}
function groupBy(ts, fn) {
  const m = {}; ts.forEach(t => { const k = fn(t); (m[k] = m[k] || []).push(t); });
  return Object.keys(m).sort().map(k => ({key: k, rows: m[k]}));
}

function renderAll() {
  const b = bookOf(VT());
  $('sub').innerHTML = V.label + ' &nbsp;&middot;&nbsp; ' + V.sessions + ' sessions ' + V.from + ' &rarr; ' + V.to +
    ' &nbsp;&middot;&nbsp; <b>' + M.strikes.find(x => x.key === curStrike).label + '</b>' +
    (curStrike === M.rule_strike ? ' (the rule)' : ' <span class="dimc">&mdash; not the rule, shown for comparison</span>') +
    ', bought at ' + M.entry_hhmm + ', time value limit ' + M.tv_max_share +
    '% of the premium, read at ' + M.tv_minute + ', exit from ' + M.exit_start + ' &nbsp;&middot;&nbsp; worst-of-minute fills, net of brokerage and taxes' +
    ' &nbsp;&middot;&nbsp; one lot = ' + M.lot_size + ' &nbsp;&middot;&nbsp; generated ' + M.generated;
  $('winNote').innerHTML = (V.note || '') + (b.nodata > 0.05 * b.signals && curStrike !== M.rule_strike
    ? ' <b class="neg">' + b.nodata + ' of these nights have no option data at this strike</b> &mdash; only the rule’s own strike is priced over the whole history; the rest of the ladder is priced over the last 6 months, which is the window the ladder table uses.'
    : '');
  const ck = CHECKS.find(c => c.k === curCheck);
  $('verdict').innerHTML =
    '<b>' + V.label + '.</b> ' + b.signals + ' sessions with a direction, ' + b.skipped + ' not traded by the ' +
    (curCheck === 'none' ? 'check (none selected)' : (curCheck === 'pts60' ? M.tv_max_points_old + '-point check' : M.tv_max_share + '% check')) +
    (b.nodata ? ', ' + b.nodata + ' with no option data' : '') + ', <b>' + (b.n || 0) + ' traded</b>' +
    (curStrike === M.rule_strike ? '' : ' at <b>' + M.strikes.find(x => x.key === curStrike).label + '</b>, not the rule&rsquo;s strike') + '. ' +
    (b.n ? b.wins + ' wins / ' + b.losses + ' losses = <b>' + fmt(b.win, 1) + '%</b> net of costs; gross &#8377;' + fmt(b.gross, 0) +
      ' less brokerage and taxes &#8377;' + fmt(b.costs, 0) + ' = <b>net &#8377;' + fmt(b.total, 0) + '</b> on one lot, profit factor <b>' +
      fmt(b.pf, 2) + '</b>, worst night &#8377;' + fmt(b.worst, 0) + ', deepest drawdown &#8377;' + fmt(b.dd, 0) +
      ', longest losing run ' + b.lossStreak + ' nights.' : 'No priced night.') +
    '<br><br><span class="dimc">' + M.wide_spot + '</span>';
  const cards = [
    ['sessions with a direction', b.signals, ''],
    ['skipped, option too dear', b.skipped, 'dimc'],
    ['no option data', b.nodata, b.nodata ? 'dimc' : ''],
    ['traded', b.n || 0, ''],
    ['win rate', b.n ? fmt(b.win, 1) + '%' : null, sign(b.n ? b.win - 50 : null)],
    ['wins / losses', b.n ? '<span class="pos">' + b.wins + '</span> / <span class="neg">' + b.losses + '</span>' : null, ''],
    ['net, after costs', b.n ? '&#8377;' + fmt(b.total, 0) : null, sign(b.total)],
    ['profit factor', b.pf === null ? null : fmt(b.pf, 2), sign(b.pf === null ? null : b.pf - 1)],
    ['worst night', b.n ? '&#8377;' + fmt(b.worst, 0) : null, 'neg'],
    ['deepest drawdown', b.n ? '&#8377;' + fmt(b.dd, 0) : null, 'neg'],
    ['longest losing run', b.n ? b.lossStreak + ' nights' : null, 'neg'],
    ['average time value paid', b.tv === null ? null : fmt(b.tv, 1) + ' pts', ''],
    ['average capital per lot', b.cap === null ? null : '&#8377;' + fmt(b.cap, 0), ''],
  ];
  $('cards').innerHTML = cards.map(c => '<div class="card"><div class="k">' + c[0] + '</div><div class="v ' + c[2] + '">' +
    (c[1] === null || c[1] === undefined ? '&mdash;' : c[1]) + '</div></div>').join('');
  renderSteps();
  renderHow();
  renderLadder();
  groupTable('tblMonth', 'month', groupBy(VT(), t => t.day.slice(0, 7)));
  const tk = VT(), h = Math.floor(tk.length / 2);
  const stab = [];
  if (tk.length >= 8) stab.push({key: 'first half', rows: tk.slice(0, h)}, {key: 'second half', rows: tk.slice(h)});
  groupBy(tk, t => t.day < M.cas_date ? 'before ' + M.cas_date : 'from ' + M.cas_date).forEach(g => stab.push(g));
  groupBy(tk, t => t.day.slice(0, 4)).forEach(g => stab.push(g));
  groupTable('tblStab', 'slice', stab);
  renderSkipped(); renderTrades(); renderLog(); drawEquity(); fillDays();
}

function renderSkipped() {
  const sk = VT().filter(t => { const l = leg(t); return l && blocked(l); });
  $('tblSkip').innerHTML = '<thead><tr><th class="l">date</th><th class="l">direction</th><th>day move</th>' +
    '<th class="l">contract</th><th>price at ' + M.tv_minute + '</th><th>intrinsic</th><th>time value</th><th>as % of premium</th><th class="l">limit</th></tr></thead><tbody>' +
    (sk.length ? sk.map(t => { const l = leg(t) || {};
      return '<tr><td class="l">' + t.day + '</td><td class="l">' + pill(t.decision) + '</td>' + cell(t.move_pct, 2, '%') +
        '<td class="l">' + (l.symbol || '') + '</td>' + plain(l.tv_price, 2) + plain(l.intrinsic, 2) +
        plain(l.time_value, 1) + '<td class="neg">' + fmt(l.tv_share * 100, 0) + '%</td><td class="l dimc">above ' + M.tv_max_share + '% &rarr; no trade</td></tr>'; }).join('')
      : '<tr><td class="l dimc" colspan="9">none in this window</td></tr>') + '</tbody>';
}
function renderTrades() {
  const ts = taken(VT()).slice().reverse();
  $('tblTrades').innerHTML = '<thead><tr><th class="l">date</th><th class="l">side</th><th>day move</th><th class="l">contract</th>' +
    '<th>time value</th><th>entry</th><th>line</th><th class="l">exit day</th><th>exit min</th><th>exit</th><th>pts</th><th>net &#8377;</th><th>capital</th></tr></thead><tbody>' +
    ts.map(t => { const l = leg(t);
      return '<tr><td class="l">' + t.day + '</td><td class="l">' + pill(t.decision) + '</td>' + cell(t.move_pct, 2, '%') +
        '<td class="l">' + l.symbol + '</td>' + plain(l.time_value, 1) + plain(l.entry_px, 2) + plain(l.line, 2) +
        '<td class="l">' + t.exit_day + '</td><td>' + l.exit_minute + (l.qualified ? '' : ' <span class="dimc">fb</span>') + '</td>' +
        plain(l.exit_px, 2) + cell(l.prem_pts, 2) + cell(l.net_rs, 0) + plain(l.capital_rs, 0) + '</tr>'; }).join('') + '</tbody>';
}
function renderLog() {
  const tby = {}; DATA.trades.forEach(t => tby[t.day] = t);
  $('tblLog').innerHTML = '<thead><tr><th class="l">date</th><th>09:15 open</th><th>15:14 close</th><th>move</th>' +
    '<th class="l">direction</th><th>time value</th><th class="l">outcome</th></tr></thead><tbody>' +
    VS().slice().reverse().map(x => { const t = tby[x.day], l = leg(t) || {};
      let out;
      if (x.direction === 'HOLD') out = '<span class="pill HOLD">HOLD</span> <span class="dimc">' + (x.hold_reason || 'flat day') + '</span>';
      else if (blocked(l)) out = '<span class="pill skip">SKIP</span> <span class="dimc">' + whyBlocked(l) + '</span>';
      else if (l.net_rs !== null && l.net_rs !== undefined) out = '<span class="' + sign(l.net_rs) + '">traded &rarr; &#8377;' + fmt(l.net_rs, 0) + '</span>';
      else out = '<span class="dimc">' + (l.reason || (t ? t.status : 'not priced')) + '</span>';
      return '<tr><td class="l">' + x.day + '</td>' + plain(x.day_open, 2) + plain(x.close, 2) + cell(x.move_pct, 2, '%') +
        '<td class="l">' + (x.direction === 'HOLD' ? '<span class="dimc">&mdash;</span>' : pill(x.direction)) + '</td>' +
        plain(l.time_value, 1) + '<td class="l">' + out + '</td></tr>'; }).join('') + '</tbody>';
}

/* ---------- equity ---------- */
function drawEquity() {
  const tk = taken(VT()), svg = $('eq'), W = 1200, H = 300, PL = 70, PR = 16, PT = 16, PB = 26;
  if (!tk.length) { svg.innerHTML = ''; return; }
  let cum = 0; const pts = tk.map(t => ({d: t.day, v: (cum += leg(t).net_rs)}));
  const lo = Math.min(0, ...pts.map(p => p.v)), hi = Math.max(0, ...pts.map(p => p.v)), pad = (hi - lo) * .08 || 1;
  const Y = v => PT + (hi + pad - v) / (hi - lo + 2 * pad) * (H - PT - PB);
  const X = i => PL + i / Math.max(1, pts.length - 1) * (W - PL - PR);
  let g = '';
  for (let k = 0; k <= 4; k++) { const v = lo - pad + (hi - lo + 2 * pad) * k / 4;
    g += '<line x1="' + PL + '" y1="' + Y(v) + '" x2="' + (W - PR) + '" y2="' + Y(v) + '" stroke="var(--grid)"/>' +
      '<text x="' + (PL - 6) + '" y="' + (Y(v) + 3) + '" fill="var(--muted)" font-size="10" text-anchor="end">' + fmt(v, 0) + '</text>'; }
  g += '<line x1="' + PL + '" y1="' + Y(0) + '" x2="' + (W - PR) + '" y2="' + Y(0) + '" stroke="var(--muted)" stroke-dasharray="4 4"/>';
  g += '<polyline fill="none" stroke="var(--accent)" stroke-width="1.8" points="' + pts.map((p, i) => X(i) + ',' + Y(p.v)).join(' ') + '"/>';
  const step = Math.max(1, Math.round(pts.length / 10));
  for (let i = 0; i < pts.length; i += step) g += '<text x="' + X(i) + '" y="' + (H - 8) + '" fill="var(--muted)" font-size="10" text-anchor="middle">' + pts[i].d.slice(2) + '</text>';
  svg.innerHTML = g;
}

__CHART_JS__

renderLive();
renderAll();
</script></div></body></html>
"""


def build_chart_js() -> str:
    """The two-panel chart, shared with v2 but cut down to the single contract."""
    return r"""
/* ---------- chart: index above, the bought contract below ---------- */
const CW = 1200, CH = 320, PADL = 66, PADR = 16, PADT = 18, PADB = 26;
const OCH = 380, OPADT = 18, OPADB = 26;
const csvg = $('chart'), osvg = $('ochart'), ctip = $('tip');
let chartState = null;
function txt(x, y, t, col, size, anchor) { return '<text x="' + x + '" y="' + y + '" fill="' + (col || 'var(--muted)') + '" font-size="' + (size || 10) + '"' + (anchor ? ' text-anchor="' + anchor + '"' : '') + '>' + t + '</text>'; }
function fillDays() {
  const sel = $('daySel'), keep = sel.value;
  const days = VT().filter(t => (DATA.option_chart[t.day] || {})[curStrike]);
  sel.innerHTML = days.map(t => { const l = leg(t);
    return '<option value="' + t.day + '">' + t.day + ' · ' + t.decision + (blocked(l) ? ' · not traded' : '') + '</option>'; }).join('');
  const ks = days.map(t => t.day);
  if (ks.includes(keep)) sel.value = keep;
  else {
    /* open on the most recent night that actually traded and closed, not on
       tonight's open position, which has no exit day to show yet */
    const done = days.filter(t => isTaken(t) && t.exit_day);
    sel.value = done.length ? done[done.length - 1].day : (ks.length ? ks[ks.length - 1] : '');
  }
  renderChart();
}
function renderChart() {
  const day = $('daySel').value;
  const trade = DATA.trades.find(t => t.day === day) || null, sig = DATA.signals.find(x => x.day === day) || null;
  banner(sig, trade);
  if (!day) { chartState = null; csvg.innerHTML = ''; osvg.innerHTML = ''; return; }
  const nd = trade ? trade.exit_day : null;
  const c1 = DATA.chart_days[day] || [], c2 = nd ? (DATA.chart_days[nd] || []) : [];
  const oc = (DATA.option_chart[day] || {})[curStrike] || null;
  const keys = new Set();
  c1.forEach(r => keys.add(day + ' ' + r[0]));
  c2.forEach(r => keys.add(nd + ' ' + r[0]));
  if (oc) { Object.keys(oc.e || {}).forEach(m => keys.add(day + ' ' + m)); if (nd) Object.keys(oc.x || {}).forEach(m => keys.add(nd + ' ' + m)); }
  if (!keys.size) { chartState = null; csvg.innerHTML = txt(CW / 2, CH / 2, 'no candles carried for this night', null, 12, 'middle'); osvg.innerHTML = ''; return; }
  const tl = Array.from(keys).sort().map(s => ({d: s.slice(0, 10), t: s.slice(11)}));
  const pos = {}; tl.forEach((p, i) => pos[p.d + ' ' + p.t] = i);
  const ix = new Array(tl.length).fill(null), op = new Array(tl.length).fill(null);
  c1.forEach(r => { ix[pos[day + ' ' + r[0]]] = [r[1], r[2], r[3], r[4]]; });
  c2.forEach(r => { ix[pos[nd + ' ' + r[0]]] = [r[1], r[2], r[3], r[4]]; });
  if (oc) { Object.entries(oc.e || {}).forEach(([m, v]) => { const i = pos[day + ' ' + m]; if (i !== undefined) op[i] = v; });
    if (nd) Object.entries(oc.x || {}).forEach(([m, v]) => { const i = pos[nd + ' ' + m]; if (i !== undefined) op[i] = v; }); }
  let split = tl.findIndex(p => p.d === nd); if (split < 0) split = tl.length;
  chartState = {day, nd, tl, pos, ix, op, split, sig, trade, oc, i0: 0, i1: tl.length};
  $('dayTag').textContent = day + (nd ? '  →  ' + nd : '  (no next session yet)');
  focusZoom();
}
function banner(sig, trade) {
  const b = $('setupBanner'); if (!sig) { b.className = 'setup dim'; b.textContent = ''; return; }
  const l = leg(trade) || {}, lines = [];
  lines.push('<span class="r">Day</span> 09:15 open <b>' + fmt(sig.day_open, 2) + '</b> &rarr; 15:14 close <b>' + fmt(sig.close, 2) +
    '</b> = <b class="' + sign(sig.move_pct) + '">' + (sig.move_pct >= 0 ? '+' : '') + fmt(sig.move_pct, 3) + '%</b> &rarr; ' + pill(sig.direction));
  if (l.symbol) lines.push('<span class="r">Contract</span> <b>' + l.symbol + '</b> (' + l.rel_strike + ')  ' +
    '<span class="dimc">price at ' + M.tv_minute + ' ' + fmt(l.tv_price, 2) + ' &minus; intrinsic ' + fmt(l.intrinsic, 2) + ' = </span> time value <b class="' +
    (blocked(l) ? 'neg' : 'pos') + '">' + fmt(l.time_value, 1) + '</b> <span class="dimc">= ' + fmt(l.tv_share * 100, 0) + '% of the premium (limit ' + M.tv_max_share + '%)</span>');
  if (blocked(l)) lines.push('<span class="r">Result</span> <span class="pill skip">NOT TRADED</span> <span class="dimc">time value ' + fmt(l.time_value, 1) + ' pts is above the ' + M.tv_max + '-point limit</span>');
  else if (l.net_rs !== null && l.net_rs !== undefined) lines.push('<span class="r">Result</span> bought ' + fmt(l.entry_px, 2) + ' at ' + l.entry_minute +
    ', sold ' + fmt(l.exit_px, 2) + ' at ' + l.exit_minute + (l.qualified ? '' : ' <span class="dimc">(fallback)</span>') +
    ' = <b class="' + sign(l.net_rs) + '">' + (l.prem_pts >= 0 ? '+' : '') + fmt(l.prem_pts, 2) + ' pts, net &#8377;' + fmt(l.net_rs, 0) + '</b>');
  b.className = 'setup ' + (blocked(l) ? 'dim' : (l.net_rs >= 0 ? 'pos' : (l.net_rs < 0 ? 'neg' : 'dim')));
  b.innerHTML = lines.join('<br>');
}
function clampWindow(n, a, b) { let i0 = Math.max(0, Math.floor(a)), i1 = Math.min(n, Math.ceil(b)); if (i1 - i0 < 8) { const m = (i0 + i1) / 2; i0 = Math.max(0, Math.floor(m - 4)); i1 = Math.min(n, i0 + 8); } return [i0, i1]; }
function drawAll() { drawChart(); drawOption(); renderVerify(); }
function focusZoom() { const st = chartState; if (!st) return;
  const a = st.tl.findIndex(p => p.d === st.day && p.t >= '14:30');
  let b = st.tl.findIndex(p => p.d === st.nd && p.t > '10:00'); if (b < 0) b = st.tl.length;
  const w = clampWindow(st.tl.length, a < 0 ? 0 : a, b); st.i0 = w[0]; st.i1 = w[1]; drawAll(); }
function resetZoom() { if (!chartState) return; chartState.i0 = 0; chartState.i1 = chartState.tl.length; drawAll(); }
function zoomAt(f, anchor) { const st = chartState; if (!st) return; const a = anchor === undefined ? (st.i0 + st.i1) / 2 : anchor;
  const w = clampWindow(st.tl.length, a - (a - st.i0) * f, a + (st.i1 - a) * f); st.i0 = w[0]; st.i1 = w[1]; drawAll(); }
function idxAt(cx, box) { const px = (cx - box.left) / box.width * CW; return chartState.i0 + (px - PADL) / (CW - PADL - PADR) * (chartState.i1 - chartState.i0); }
function xOf(i) { const st = chartState, n = st.i1 - st.i0; return PADL + (i - st.i0 + 0.5) / n * (CW - PADL - PADR); }
function halfW() { const st = chartState; return (CW - PADL - PADR) / (st.i1 - st.i0) / 2; }
function seriesRange(arr) { const st = chartState; let lo = Infinity, hi = -Infinity;
  for (let i = st.i0; i < st.i1; i++) { const k = arr[i]; if (!k) continue; lo = Math.min(lo, k[2]); hi = Math.max(hi, k[1]); } return [lo, hi]; }
function candles(arr, Y, i0, i1) { let g = ''; const bw = Math.max(1, halfW() * 1.4);
  for (let i = i0; i < i1; i++) { const k = arr[i]; if (!k) continue;
    const up = k[3] >= k[0], col = up ? 'var(--up)' : 'var(--down)', x = xOf(i), y1 = Y(Math.max(k[0], k[3])), y2 = Y(Math.min(k[0], k[3]));
    g += '<line x1="' + x + '" y1="' + Y(k[1]) + '" x2="' + x + '" y2="' + Y(k[2]) + '" stroke="' + col + '" stroke-width="1"/><rect x="' + (x - bw / 2) + '" y="' + y1 + '" width="' + bw + '" height="' + Math.max(1, y2 - y1) + '" fill="' + col + '"/>'; }
  return g; }
function drawChart() {
  const st = chartState; if (!st) return;
  const {ix, i0, i1, sig, trade, split, day, nd} = st;
  let [lo, hi] = seriesRange(ix);
  if (!isFinite(lo)) { csvg.innerHTML = txt(CW / 2, CH / 2, 'no index candles here', null, 12, 'middle'); return; }
  const pad = (hi - lo) * 0.07 || 1; lo -= pad; hi += pad;
  const Y = v => PADT + (hi - v) / (hi - lo) * (CH - PADT - PADB);
  const at = (d, t) => { const i = st.pos[d + ' ' + t]; return i === undefined ? -1 : i; };
  const half = halfW(), vis = i => i >= i0 && i < i1;
  let g = '';
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4; g += '<line x1="' + PADL + '" y1="' + Y(v) + '" x2="' + (CW - PADR) + '" y2="' + Y(v) + '" stroke="var(--grid)"/>' + txt(PADL - 6, Y(v) + 3, fmt(v, 0), null, 10, 'end'); }
  const step = Math.max(1, Math.round((i1 - i0) / 12));
  for (let i = i0; i < i1; i += step) g += txt(xOf(i), CH - 8, st.tl[i].t, null, 10, 'middle');
  g += txt(PADL, 12, 'NIFTY index', 'var(--ink2)', 11);
  if (split > i0 && split < i1) { const xs = xOf(split) - half;
    g += '<line x1="' + xs + '" y1="' + PADT + '" x2="' + xs + '" y2="' + (CH - PADB) + '" stroke="var(--ink2)" stroke-width="1.2" stroke-dasharray="6 4"/>' +
      txt(xs - 6, PADT + 10, day, 'var(--ink2)', 11, 'end') + txt(xs + 6, PADT + 10, nd + ' (next session)', 'var(--ink2)', 11); }
  if (sig && sig.data_ok) {
    const io = at(day, '09:15'), ic = at(day, '15:14');
    const col = sig.move_pct >= 0 ? 'var(--up)' : 'var(--down)';
    if (ic >= 0 && (vis(ic) || vis(io))) { const yo = Y(sig.day_open), xo = io >= 0 ? xOf(Math.max(io, i0)) : PADL;
      g += '<line x1="' + xo + '" y1="' + yo + '" x2="' + xOf(ic) + '" y2="' + Y(sig.close) + '" stroke="' + col + '" stroke-width="1.6" stroke-dasharray="4 3"/>' +
        txt(PADL + 4, yo - 4, '09:15 open ' + fmt(sig.day_open, 2) + ' · day ' + (sig.move_pct >= 0 ? '+' : '') + fmt(sig.move_pct, 3) + '% → ' + sig.direction, col, 10.5); }
    if (ic >= 0 && vis(ic)) { const x = xOf(ic) + half;
      g += '<line x1="' + x + '" y1="' + PADT + '" x2="' + x + '" y2="' + (CH - PADB) + '" stroke="var(--warn)" stroke-width="1.3"/>' + txt(x - 4, PADT + 24, 'decision 15:14', 'var(--warn)', 10.5, 'end'); }
  }
  g += candles(ix, Y, i0, i1);
  if (trade && trade.entry_spot) { const ie = at(day, M.entry_hhmm);
    if (ie >= 0 && vis(ie)) g += '<circle cx="' + xOf(ie) + '" cy="' + Y(trade.entry_spot) + '" r="4" fill="var(--accent)" stroke="var(--surface)" stroke-width="1.5"/>'; }
  csvg.innerHTML = g;
}
function drawOption() {
  const st = chartState; if (!st) return;
  const {op, i0, i1, trade, split, day, nd} = st, head = $('optHead');
  const l = leg(trade) || {};
  if (!st.oc) { osvg.innerHTML = txt(CW / 2, OCH / 2, 'no option candles carried for this night', null, 12, 'middle'); head.innerHTML = ''; return; }
  let [lo, hi] = seriesRange(op);
  if (!isFinite(lo)) { osvg.innerHTML = txt(CW / 2, OCH / 2, 'no option candles in this window', null, 12, 'middle'); head.innerHTML = ''; return; }
  [l.entry_px, l.line, l.exit_px, l.tv_price].forEach(v => { if (v) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
  const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
  const Y = v => OPADT + (hi - v) / (hi - lo) * (OCH - OPADT - OPADB);
  const at = (d, t) => { const i = st.pos[d + ' ' + t]; return i === undefined ? -1 : i; };
  const half = halfW(), vis = i => i >= i0 && i < i1;
  let g = '';
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4; g += '<line x1="' + PADL + '" y1="' + Y(v) + '" x2="' + (CW - PADR) + '" y2="' + Y(v) + '" stroke="var(--grid)"/>' + txt(PADL - 6, Y(v) + 3, fmt(v, 1), null, 10, 'end'); }
  const step = Math.max(1, Math.round((i1 - i0) / 12));
  for (let i = i0; i < i1; i += step) g += txt(xOf(i), OCH - 8, st.tl[i].t, null, 10, 'middle');
  g += txt(PADL, 12, (l.symbol || 'option') + ' · premium per share', 'var(--ink2)', 11);
  if (split > i0 && split < i1) { const xs = xOf(split) - half; g += '<line x1="' + xs + '" y1="' + OPADT + '" x2="' + xs + '" y2="' + (OCH - OPADB) + '" stroke="var(--ink2)" stroke-width="1.2" stroke-dasharray="6 4"/>'; }
  /* the intrinsic floor and the time-value band on the entry day */
  if (l.intrinsic) { const y = Y(l.intrinsic);
    g += '<line x1="' + PADL + '" y1="' + y + '" x2="' + (CW - PADR) + '" y2="' + y + '" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 5"/>' +
      txt(PADL + 4, y - 4, 'intrinsic ' + fmt(l.intrinsic, 1) + ' — everything above this line is time value', 'var(--muted)', 10); }
  if (nd) { const a = at(nd, M.exit_start); let b = at(nd, M.exit_limit); if (b < 0) b = i1 - 1;
    if (a >= 0 && (vis(a) || vis(b))) { const x0 = Math.max(PADL, xOf(a) - half), x1 = Math.min(CW - PADR, xOf(b) + half);
      g += '<rect x="' + x0 + '" y="' + OPADT + '" width="' + Math.max(0, x1 - x0) + '" height="' + (OCH - OPADT - OPADB) + '" fill="var(--accent)" opacity="0.06"/>' +
        txt((x0 + x1) / 2, OCH - OPADB - 6, 'the rule may sell only here: ' + M.exit_start + ' → ' + M.exit_limit, 'var(--accent)', 10, 'middle'); } }
  if (l.line) { g += '<line x1="' + PADL + '" y1="' + Y(l.line) + '" x2="' + (CW - PADR) + '" y2="' + Y(l.line) + '" stroke="var(--warn)" stroke-width="1.3" stroke-dasharray="7 4"/>' +
    txt(CW - PADR - 4, Y(l.line) - 5, 'line to clear ' + fmt(l.line, 2) + ' = entry + costs', 'var(--warn)', 10.5, 'end'); }
  if ($('showQual').checked && l.line && nd) {
    for (let i = Math.max(i0, split); i < i1; i++) { const k = op[i]; if (!k) continue;
      const t = st.tl[i].t; if (t < M.exit_start || t > M.exit_limit) continue;
      if (k[2] > l.line) g += '<rect x="' + (xOf(i) - half) + '" y="' + OPADT + '" width="' + Math.max(1, half * 2) + '" height="' + (OCH - OPADT - OPADB) + '" fill="var(--up)" opacity="0.13"/>'; } }
  g += candles(op, Y, i0, i1);
  const itv = at(day, l.tv_minute || M.tv_minute);
  if (itv >= 0 && vis(itv) && l.tv_price) g += '<circle cx="' + xOf(itv) + '" cy="' + Y(l.tv_price) + '" r="3.5" fill="var(--warn)" stroke="var(--surface)" stroke-width="1.2"/>' +
    txt(xOf(itv) - 8, Y(l.tv_price) - 7, 'check at ' + (l.tv_minute || M.tv_minute) + ': time value ' + fmt(l.time_value, 1), 'var(--warn)', 10.5, 'end');
  const ie = at(day, l.entry_minute || M.entry_hhmm);
  const col = (l.net_rs !== null && l.net_rs !== undefined) ? (l.net_rs >= 0 ? 'var(--up)' : 'var(--down)') : 'var(--accent)';
  if (ie >= 0 && vis(ie) && l.entry_px) g += '<circle cx="' + xOf(ie) + '" cy="' + Y(l.entry_px) + '" r="5" fill="var(--accent)" stroke="var(--surface)" stroke-width="1.5"/>' +
    txt(xOf(ie) - 9, Y(l.entry_px) + 4, 'BOUGHT ' + (l.entry_minute || M.entry_hhmm) + ' @ ' + fmt(l.entry_px, 2) + ' (minute high)', 'var(--accent)', 11, 'end');
  if (l.exit_minute && l.exit_px !== null && l.exit_px !== undefined && nd) { const ixm = at(nd, l.exit_minute);
    if (ixm >= 0 && vis(ixm)) g += '<circle cx="' + xOf(ixm) + '" cy="' + Y(l.exit_px) + '" r="5" fill="' + col + '" stroke="var(--surface)" stroke-width="1.5"/>' +
      (ie >= 0 ? '<line x1="' + xOf(ie) + '" y1="' + Y(l.entry_px) + '" x2="' + xOf(ixm) + '" y2="' + Y(l.exit_px) + '" stroke="' + col + '" stroke-width="1.6" stroke-dasharray="5 3"/>' : '') +
      txt(xOf(ixm) + 9, Y(l.exit_px) + 4, (l.qualified ? 'SOLD ' : 'FALLBACK SOLD ') + l.exit_minute + ' @ ' + fmt(l.exit_px, 2) + ' (minute low) = ' +
        (l.prem_pts >= 0 ? '+' : '') + fmt(l.prem_pts, 2) + ' pts, net ₹' + fmt(l.net_rs, 0), col, 11); }
  osvg.innerHTML = g;
  const parts = [];
  if (l.symbol) parts.push('<span class="r">Contract</span> <b>' + l.symbol + '</b> <span class="dimc">(' + l.rel_strike + ', strike ' + fmt(l.strike, 0) + ' ' + l.option_type + ', expiry ' + l.expiry + ')</span>');
  if (l.tv_cut !== null && l.tv_cut !== undefined) parts.push('<span class="r">Ranking</span> recent nights ran from <b>'
    + fmt(l.tv_cheapest * 100, 1) + '%</b> to <b>' + fmt(l.tv_dearest * 100, 1) + '%</b> of premium; the cheapest '
    + M.tv_rank_keep + ' in 100 sat under <b>' + fmt(l.tv_cut * 100, 1) + '%</b>. Tonight was <b>' + fmt(l.tv_share * 100, 1)
    + '%</b>, dearer than <b>' + fmt(l.tv_rank, 0) + '</b> nights in 100 &rarr; <b class="' + (l.tv_share <= l.tv_cut ? 'pos' : 'neg') + '">'
    + (l.tv_share <= l.tv_cut ? 'inside the cheapest ' + M.tv_rank_keep : 'among the dearest ' + (100 - M.tv_rank_keep)) + '</b>');
  if (l.tv_price) parts.push('<span class="r">Check</span> at ' + l.tv_minute + ' price <b>' + fmt(l.tv_price, 2) + '</b> &minus; intrinsic <b>' + fmt(l.intrinsic, 2) +
    '</b> = time value <b class="' + (blocked(l) ? 'neg' : 'pos') + '">' + fmt(l.time_value, 1) + '</b> = <b>' + fmt(l.tv_share * 100, 0) + '%</b> of the premium against the ' + M.tv_max_share + '% limit &rarr; ' +
    (blocked(l) ? '<b class="neg">no trade</b>' : '<b class="pos">trade</b>'));
  if (l.entry_px) parts.push('<span class="r">Line</span> entry <b>' + fmt(l.entry_px, 2) + '</b> (the ' + M.entry_hhmm + ' minute&rsquo;s HIGH) + costs = <b>' + fmt(l.line, 2) + '</b>; a minute qualifies only when its LOW is above it');
  head.className = 'setup ' + (blocked(l) ? 'dim' : (l.net_rs >= 0 ? 'pos' : (l.net_rs < 0 ? 'neg' : 'dim')));
  head.innerHTML = parts.join('<br>') || 'No contract for this night.';
}
function renderVerify() {
  const st = chartState, tb = $('tblVerify');
  if (!st || !st.oc || !st.nd) {
    tb.innerHTML = ''; $('verifyTag').textContent = '';
    $('verifySub').innerHTML = st && st.trade && st.trade.status && st.trade.status.indexOf('open') === 0
      ? 'This position is still <b>open</b>: the exit runs on the next session, so there is nothing to cross-check yet.'
      : 'No exit-day candles for this night.';
    return; }
  const l = leg(st.trade) || {}, x = st.oc.x || {}, mins = Object.keys(x).sort();
  if (blocked(l)) { tb.innerHTML = ''; $('verifySub').innerHTML = 'This night was <b>not traded</b> at this strike: ' + whyBlocked(l) + '. The candles below the chart show what it would have done.'; $('verifyTag').textContent = ''; return; }
  const all = $('verifyAll').checked;
  const rows = mins.filter(m => all || (m >= M.exit_start && (!l.exit_minute || m <= l.exit_minute) && m <= M.exit_limit));
  $('verifySub').innerHTML = 'Exit day <b>' + st.nd + '</b>, contract <b>' + (l.symbol || '-') + '</b>. ' +
    (l.line ? 'A minute qualifies when its LOW is above <b>' + fmt(l.line, 2) + '</b>. ' : '') + 'These are the raw one-minute candles the backtest read.';
  $('verifyTag').textContent = rows.length + ' of ' + mins.length + ' minutes';
  tb.innerHTML = '<thead><tr><th class="l">minute</th><th>open</th><th>high</th><th>low</th><th>close</th><th>low &minus; line</th><th class="l">qualifies?</th><th class="l">what the rule did</th></tr></thead><tbody>' +
    rows.map(m => { const k = x[m], q = l.line && k[2] > l.line, isExit = l.exit_minute === m, before = m < M.exit_start, after = l.exit_minute && m > l.exit_minute;
      let note;
      if (isExit) note = '<b class="' + sign(l.net_rs) + '">' + (q ? 'SOLD here' : 'nothing qualified — sold at the ' + M.exit_limit + ' fallback') + ' at ' + fmt(l.exit_px, 2) + ' → net &#8377;' + fmt(l.net_rs, 0) + '</b>';
      else if (before) note = '<span class="dimc">before ' + M.exit_start + ', the rule is not looking yet</span>';
      else if (after) note = '<span class="dimc">after the sale</span>';
      else if (q) note = '<span class="pos">first qualifying minute</span>';
      else note = '<span class="dimc">low is not above the line → wait</span>';
      return '<tr' + (isExit ? ' style="font-weight:600;background:var(--grid)"' : '') + '><td class="l">' + m + '</td>' +
        plain(k[0], 2) + plain(k[1], 2) + plain(k[2], 2) + plain(k[3], 2) + (l.line ? cell(k[2] - l.line, 2) : '<td>&mdash;</td>') +
        '<td class="l">' + (before ? '<span class="dimc">n/a</span>' : (q ? '<span class="pos">yes</span>' : '<span class="neg">no</span>')) + '</td><td class="l">' + note + '</td></tr>'; }).join('') + '</tbody>';
}
[csvg, osvg].forEach(el => {
  el.addEventListener('wheel', e => { if (!chartState) return; e.preventDefault(); zoomAt(e.deltaY < 0 ? 0.82 : 1.22, idxAt(e.clientX, el.getBoundingClientRect())); }, {passive: false});
  el.addEventListener('pointerdown', e => { if (!chartState) return; el._drag = {x: e.clientX, i0: chartState.i0, i1: chartState.i1}; el.classList.add('drag'); try { el.setPointerCapture(e.pointerId); } catch (_) {} });
  el.addEventListener('pointermove', e => { if (!chartState) return; const box = el.getBoundingClientRect();
    if (el._drag) { const dx = (e.clientX - el._drag.x) / box.width * CW, per = (el._drag.i1 - el._drag.i0) / (CW - PADL - PADR);
      const w = clampWindow(chartState.tl.length, el._drag.i0 - dx * per, el._drag.i1 - dx * per); chartState.i0 = w[0]; chartState.i1 = w[1]; drawAll(); ctip.style.display = 'none'; return; }
    const i = Math.round(idxAt(e.clientX, box) - 0.5); if (i < 0 || i >= chartState.tl.length) { ctip.style.display = 'none'; return; }
    const p = chartState.tl[i], a = chartState.ix[i], b = chartState.op[i];
    ctip.innerHTML = '<b>' + p.t + '</b> ' + p.d + (a ? '\nindex  O ' + a[0].toFixed(2) + '  H ' + a[1].toFixed(2) + '  L ' + a[2].toFixed(2) + '  C ' + a[3].toFixed(2) : '') +
      (b ? '\noption O ' + b[0].toFixed(2) + '  H ' + b[1].toFixed(2) + '  L ' + b[2].toFixed(2) + '  C ' + b[3].toFixed(2) : '');
    ctip.style.display = 'block'; ctip.style.left = Math.min(e.clientX + 14, window.innerWidth - 230) + 'px'; ctip.style.top = Math.max(4, e.clientY - 60) + 'px'; });
  el.addEventListener('pointerup', e => { el._drag = null; el.classList.remove('drag'); try { el.releasePointerCapture(e.pointerId); } catch (_) {} });
  el.addEventListener('pointerleave', () => { ctip.style.display = 'none'; });
});
$('daySel').onchange = renderChart; $('showQual').onchange = drawOption; $('verifyAll').onchange = renderVerify;
$('zoomFocus').onclick = focusZoom; $('zoomIn').onclick = () => zoomAt(0.7); $('zoomOut').onclick = () => zoomAt(1.4); $('zoomReset').onclick = resetZoom;
"""


def worked_examples(trades: list[dict]) -> dict:
    """Three real nights that show the arithmetic, plus a plain illustration of
    why the same number of points is a different bet at a different premium."""
    cands = [(t, t["legs"][RULE_STRIKE]) for t in trades
             if t["status"] == "closed" and (t.get("legs") or {}).get(RULE_STRIKE)
             and t["legs"][RULE_STRIKE].get("tv_share") is not None
             and t["legs"][RULE_STRIKE].get("net_rs") is not None]
    def pick(fn, mode):
        """The most illustrative night of its group, not the newest.  'median'
        gives a typical night; 'max' the clearest case of too much time value.
        A typical night matters for the passing example, because the extremes
        there are contracts that printed BELOW intrinsic when the index moved
        inside the minute, which would only confuse a worked example."""
        sel = [c for c in cands if fn(c[1])]
        if not sel:
            return None
        sel.sort(key=lambda c: c[1]["tv_share"])
        return sel[len(sel) // 2] if mode == "median" else sel[-1]
    out = []
    picks = [
        ("comfortably passes both checks",
         lambda l: l["tv_share"] <= TV_MAX_SHARE and l["time_value"] <= TV_MAX_POINTS_OLD,
         "median"),
        (f"passes {TV_MAX_POINTS_OLD:.0f} points but FAILS {TV_MAX_SHARE:.0%} - this is where the two disagree",
         lambda l: l["tv_share"] > TV_MAX_SHARE and l["time_value"] <= TV_MAX_POINTS_OLD,
         "max"),
        ("fails both checks - far too much time value",
         lambda l: l["tv_share"] > TV_MAX_SHARE and l["time_value"] > TV_MAX_POINTS_OLD,
         "max"),
    ]
    for title, fn, mode in picks:
        c = pick(fn, mode)
        if not c:
            continue
        t, l = c
        out.append({"title": title, "day": t["day"], "decision": t["decision"],
                    "spot": round(t["entry_spot"], 2), "symbol": l["symbol"],
                    "strike": l["strike"], "opt": l["option_type"], "rel": l["rel_strike"],
                    "tv_minute": l["tv_minute"], "premium": l["tv_price"],
                    "intrinsic": l["intrinsic"], "time_value": l["time_value"],
                    "share": round(l["tv_share"] * 100, 1),
                    "pass15": l["tv_share"] <= TV_MAX_SHARE,
                    "pass60": l["time_value"] <= TV_MAX_POINTS_OLD,
                    "entry_px": l["entry_px"], "line": l["line"],
                    "exit_minute": l["exit_minute"], "exit_px": l["exit_px"],
                    "net_rs": l["net_rs"], "qualified": l["qualified"]})
    # the same 60 points at different premiums
    illo = []
    for prem, intr in ((340.0, 300.0), (360.0, 300.0), (400.0, 300.0),
                       (250.0, 200.0), (150.0, 100.0), (110.0, 50.0)):
        tv = prem - intr
        illo.append({"premium": prem, "intrinsic": intr, "tv": round(tv, 1),
                     "share": round(tv / prem * 100, 1),
                     "pass60": tv <= TV_MAX_POINTS_OLD,
                     "pass15": tv / prem <= TV_MAX_SHARE})
    # how often the two checks disagree, on the rule's strike
    both = sum(1 for _t, l in cands if l["tv_share"] <= TV_MAX_SHARE and l["time_value"] <= TV_MAX_POINTS_OLD)
    only60 = [l for _t, l in cands if l["tv_share"] > TV_MAX_SHARE and l["time_value"] <= TV_MAX_POINTS_OLD]
    only15 = sum(1 for _t, l in cands if l["tv_share"] <= TV_MAX_SHARE and l["time_value"] > TV_MAX_POINTS_OLD)
    nets = [l["net_rs"] for l in only60]
    return {"nights": out, "illustration": illo,
            "both": both, "only60": len(only60), "only15": only15,
            "only60_win": round(sum(1 for x in nets if x > 0) / len(nets) * 100, 1) if nets else None,
            "only60_net": round(sum(nets), 0) if nets else None,
            "tv_max_share": round(TV_MAX_SHARE * 100, 1), "tv_max_points": TV_MAX_POINTS_OLD}


def live_panel(trades: list[dict], signals: list[dict]) -> dict | None:
    """What to do right now, from the most recent session."""
    if not signals:
        return None
    last = signals[-1]
    t = next((x for x in trades if x["day"] == last["day"]), None)
    lines = []
    if last["direction"] == "HOLD":
        return {"headline": f"{last['day']}: no trade. {last['hold_reason'] or 'the 15:14 close equals the 09:15 open'}",
                "lines": ["The rule takes a position only when the 15:14 close differs from the 09:15 open."]}
    l = ((t or {}).get("legs") or {}).get(RULE_STRIKE) or {}
    lines.append(f'<span class="r">Day</span> 09:15 open <b>{last["day_open"]:.2f}</b> &rarr; 15:14 close '
                 f'<b>{last["close"]:.2f}</b> = <b>{last["move_pct"]:+.3f}%</b> &rarr; <b>{last["direction"]}</b>')
    if l.get("symbol"):
        lines.append(f'<span class="r">Contract</span> <b>{l["symbol"]}</b> ({l["rel_strike"]}, expiry {l["expiry"]})')
    if l.get("time_value") is not None:
        ok = not l["gated"]
        share = (l.get("tv_share") or 0) * 100
        lines.append(f'<span class="r">Check</span> price at {l["tv_minute"]} <b>{l["tv_price"]:.2f}</b> '
                     f'&minus; intrinsic <b>{l["intrinsic"]:.2f}</b> = time value '
                     f'<b>{l["time_value"]:.1f}</b>, which is '
                     f'<b class="{"pos" if ok else "neg"}">{share:.0f}%</b> of the premium against the '
                     f'{TV_MAX_SHARE * 100:.0f}% limit &rarr; '
                     f'<b class="{"pos" if ok else "neg"}">{"TRADE" if ok else "NO TRADE"}</b>')
    if t and t["skipped"]:
        head = f"{last['day']}: NO TRADE - the option is too expensive"
        lines.append('<span class="r">Action</span> stand aside tonight.')
    elif l.get("entry_px"):
        head = f"{last['day']}: {last['direction']} - buy {l['symbol']}"
        lines.append(f'<span class="r">Entry</span> bought in the {l["entry_minute"]} minute at '
                     f'<b>{l["entry_px"]:.2f}</b> (that minute&rsquo;s high), capital '
                     f'&#8377;{l["capital_rs"]:,.0f} for one lot')
        lines.append(f'<span class="r">Tomorrow</span> from {EXIT_START}, sell in the first minute whose '
                     f'<b>LOW is above {l["line"]:.2f}</b>. If no minute gets there by {EXIT_LIMIT}, '
                     f'sell in the {EXIT_LIMIT} minute.')
        if l.get("net_rs") is not None:
            lines.append(f'<span class="r">Closed</span> sold {l["exit_px"]:.2f} at {l["exit_minute"]}'
                         f'{"" if l["qualified"] else " (fallback)"} = net &#8377;{l["net_rs"]:,.0f}')
    else:
        head = f"{last['day']}: {last['direction']}, not priced"
        lines.append(f'<span class="r">Note</span> {l.get("reason") or (t or {}).get("status", "")}')
    return {"headline": head, "lines": lines}


STEPS = [
    "After the <b>15:14</b> candle, take the session&rsquo;s own bar: the <b>09:15 open</b> and the <b>15:14 close</b>.",
    "Close <b>above</b> the open &rarr; <b>BUY</b> a call. Close <b>below</b> &rarr; <b>SELL</b>, meaning buy a put. Equal, or any candle missing &rarr; no trade.",
    "Take the strike <b>six strikes in the money</b>: on a BUY the call at ATM&minus;6, on a SELL the put at ATM+6, where ATM is the 15:20 index rounded to the nearest 50. Expiry: the nearest weekly <b>after</b> tomorrow.",
    "At <b>15:19</b>, read that contract&rsquo;s price and subtract its intrinsic value (the distance from the strike to the index, about 300 points). That difference is the <b>time value</b>. Divide it by the price you would pay. If the time value is <b>more than 15% of the premium, do not trade tonight</b>. On a 340 premium that limit is about 51 points; on a 400 premium it is 60. The limit moves with the price, because the same number of points is a very different bet at a different premium.",
    "Otherwise buy one lot in the <b>15:20</b> minute. Work out your line: <b>what you paid plus the round-trip costs</b> (about 1.2 points).",
    "From <b>09:30</b> tomorrow, after each one-minute candle ask: <b>was the LOW of that minute above the line?</b> Yes &rarr; sell now. No &rarr; wait. If nothing qualifies by <b>15:14</b>, sell in the 15:14 minute. There is no stop and no target.",
]

REJECTED = [
    ["Stop-losses", "every level on the premium (&minus;5% to &minus;70%) and on NIFTY (25 to 500 points) lowered win rate, net and profit factor, and none reduced the worst night. The premium paid is the stop."],
    ["Profit targets", "the exit already is one. Its winners come in at a median +6.5% of premium and 28% of them above +20%, and those carry 77% of all winning rupees; a resting limit caps exactly those (+10% reads PF 0.60, +50% 1.13, both below doing nothing)."],
    ["Deeper strikes", "4 &rarr; 8 strikes in moves the loss rate only 26.3% &rarr; 23.9% while untraded minutes go 3.3% &rarr; 24.1%. Six is the last strike where the worst-fill test still has prices to punish."],
    ["Signal filters", "21 of them (trend agreement, day size, close location, range, weekday, previous day). None survived an out-of-sample split; the best in-sample one read 16.8% loss rate in the first half and 25.2% in the second, worse than doing nothing."],
    ["Holding a loser a second day", "win rate rises to 81% but the average loss grows from 9,540 to 13,121 and profit factor falls from 1.23 to 1.08 over five years of spot."],
    ["Cutting at the open", "35 of 37 losers gapped against, but cutting at 09:16&ndash;09:20 fills at the low of the widest minute of the day and also cuts winners; every variant read PF 1.01&ndash;1.13 against 1.14 for holding."],
]

CAVEATS = [
    "<b>A short window, by choice.</b> This report runs from a fixed 2026-03-01 to today, so it grows by a session a day and never loses one off the front. That is a few hundred nights, not a few thousand. The rule was chosen on the broker&rsquo;s whole archive, 2024-10 onward, 476 nights, which <code>--from 2024-10-01</code> still reproduces; even that is two years of real premiums, not five. The direction signal alone goes back to 2022 on spot, but no option P&L before 2024-10 exists to be had.",
    "<b>A flat year is inside the range.</b> 2025 returned profit factor 1.03 before the time-value condition and 1.09 after it, over 245 nights. The second half of 2025 lost money outright.",
    "<b>The loss is the overnight gap and nothing prevents it.</b> 82% of losing nights had already gapped against at the open and 91% never traded above the line at any minute. The time-value condition limits how much such a night costs; it does not forecast one.",
    "<b>Size from the drawdown, not the premium.</b> One lot risks its whole premium every night, a median &#8377;22,787. The p99 drawdown per lot is about &#8377;155,000, and that is what capital must be set against.",
    "<b>Worst-of-minute fills.</b> Every night is bought at the entry minute&rsquo;s high and sold at the exit minute&rsquo;s low, so no fill here is better than a real one could have been. Close fills are carried in the CSV for comparison only.",
]


def write_report(payload: dict, out_path: str) -> None:
    html = HTML_TEMPLATE.replace("__CHART_JS__", build_chart_js())
    html = html.replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":")))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  report  -> {out_path} ({os.path.getsize(out_path)/1e6:.1f} MB)")


async def run(args) -> None:
    # The ranking check needs the nights BEFORE the window to rank the first of
    # them against, so the run-up is loaded and priced and then dropped from
    # every table.  Without it the first three months of any report would have
    # nothing to compare tonight with.
    warm_from = args.from_date - timedelta(days=TV_WARMUP_DAYS)
    candles = await load_nifty(args.offline, warm_from - timedelta(days=10), args.to_date)
    rows, _ = to_rows(candles)
    sessions, all_days = build_sessions(rows)
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["day"]].append(r)
    for d, sess in sessions.items():
        ent = [r for r in by_day[d] if r["t"] == ENTRY_HHMM and r["ok"]]
        sess["entry"] = ent[0] if len(ent) == 1 else None
    series = daily_series(sessions, all_days, args.partial)
    from_iso, to_iso = args.from_date.isoformat(), args.to_date.isoformat()
    warm_iso = warm_from.isoformat()
    all_signals = [compute_signal(s) for s in series if warm_iso <= s["day"] <= to_iso]
    signals = [x for x in all_signals if x["day"] >= from_iso]
    if not signals:
        raise RuntimeError(f"no session inside {from_iso} -> {to_iso}")
    print(f"  {len(signals)} sessions, {sum(1 for x in signals if x['direction'] != 'HOLD')} with a direction"
          f"  (+{len(all_signals) - len(signals)} run-up sessions for the ranking)")
    all_trades = build_trades(all_signals, sessions, all_days)
    # The window is fixed and short now, so the chart covers ALL of it rather
    # than a rolling 183-day slice - otherwise the first nights of every report
    # have tables but no candles to check them against.
    chart_full_from = from_iso
    # with a fixed short window the ladder can cover the whole run, so every
    # rung is compared on exactly the nights the report is about
    ladder_from = from_iso
    priced, option_chart, ladder = await price_trades(
        all_trades, args.offline, None if args.offline else _read_access_token(),
        chart_full_from, ladder_from)
    add_rolling_rank(all_trades)                 # needs every leg priced first
    trades = [t for t in all_trades if t["day"] >= from_iso]
    skipped = sum(1 for t in trades if t["skipped"])
    print(f"  {len(trades)} directions, {skipped} skipped by the time-value condition, {priced} priced")

    six = (args.to_date - timedelta(days=183)).isoformat()
    windows = [("all", f"the run: {from_iso} -> {to_iso}", from_iso,
                f"The window is fixed at the front ({from_iso}) and grows to today, so this report is "
                f"always a superset of yesterday's and the headline cannot move because an old night fell off."),
               ("cas", f"from {CAS_DATE} (closing auction)", max(from_iso, CAS_DATE),
                "After the closing-auction change and the move of F&O hours to 15:40.")]
    if six > from_iso:                       # only when it is genuinely a narrower view
        windows.insert(1, ("6m", "last 6 months", six,
                           "The house default window, shown when it is narrower than the run."))
    views = {}
    for key, label, lo, note in windows:
        tr_w = [t for t in trades if t["day"] >= lo]
        sg_w = [x for x in signals if x["day"] >= lo]
        if not sg_w:
            continue
        views[key] = {"label": label, "from": lo, "to": to_iso, "sessions": len(sg_w),
                      "note": note, "verdict": verdict(tr_w, label)}

    chart_rows: dict[str, list] = defaultdict(list)
    trade_days = {t["day"] for t in trades} | {t["exit_day"] for t in trades if t["exit_day"]}
    for r in rows:
        d = r["day"]
        if d < chart_full_from or not r["ok"] or d not in trade_days:
            continue
        if not (SESSION_START <= r["t"] <= "15:29"):
            continue
        chart_rows[d].append([r["t"], round(r["o"], 2), round(r["h"], 2), round(r["l"], 2), round(r["c"], 2)])

    meta = {"generated": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"), "lot_size": LOT_SIZE,
            "cas_date": CAS_DATE, "entry_hhmm": ENTRY_HHMM, "tv_minute": TV_MINUTE,
            "tv_max_share": round(TV_MAX_SHARE * 100, 1), "exit_start": EXIT_START, "exit_limit": EXIT_LIMIT,
            "tv_rank_keep": TV_RANK_KEEP, "tv_rank_lookback": TV_RANK_LOOKBACK,
            "steps": STEPS, "rejected": REJECTED, "caveats": CAVEATS, "wide_spot": WIDE_SPOT,
            "tv_max_points_old": TV_MAX_POINTS_OLD,
            "examples": worked_examples(trades),
            "strikes": [{"key": k, "offset": o, "label": lab} for o, k, lab in STRIKES],
            "rule_strike": RULE_STRIKE, "ladder": ladder}
    payload = {"meta": meta, "views": views, "default_view": "all" if "all" in views else "6m",
               "signals": signals, "trades": trades,
               "live": live_panel(trades, signals),
               "chart_days": {d: sorted(v) for d, v in chart_rows.items()},
               "option_chart": option_chart}
    write_signals_csv(signals, trades, args.signals_csv)
    write_trades_csv(trades, args.trades_csv)
    write_report(payload, args.out)
    for key in ("all", "6m", "cas"):
        if key in views:
            import re as _re
            print("\n  " + _re.sub("<[^>]+>", "", views[key]["verdict"]))
    print()


def main() -> None:
    today = date.today()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--partial-sessions", dest="partial", default="strict",
                    choices=[k for k, _ in PARTIAL_MODES])
    ap.add_argument("--offline", action="store_true", help="use local caches only")
    ap.add_argument("--out", default=REPORT_HTML)
    ap.add_argument("--signals-csv", default=SIGNALS_CSV)
    ap.add_argument("--trades-csv", default=TRADES_CSV)
    ap.add_argument("--from", dest="from_date", type=date.fromisoformat, default=START_DATE,
                    help=f"first signal day; fixed at {START_DATE} so the window only ever grows "
                         f"at the far end (the broker's archive reaches {ARCHIVE_START} if wanted)")
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat, default=today)
    args = ap.parse_args()
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
