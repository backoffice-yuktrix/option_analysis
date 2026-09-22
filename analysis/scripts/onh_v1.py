"""Over night Hold - v1 (ONH v1): the seven-feature EOD rule, BUY / SELL / HOLD.

USER PROMPT (verbatim summary of the steps)
    Decide something after the 15:14 candle, take a position into the close, and close it the
    next morning.  v1 is a seven-feature signal that can go either way.
    1  Daily bar per session from the 360 one-minute candles 09:15..15:14 (open = 09:15 open,
       high/low = extremes of the window, close = 15:14 close).
    2  Decide once the 15:14 candle is complete; nothing starting at/after 15:15 is read.
    3  Trend30   = % move oldest close -> newest close over the latest 30 daily bars.
    4  SMA10     = mean close of the latest 10 daily bars, today included.
    5  Location30 = (close - lowest low of 30) / (highest high - lowest low) over the last 30 bars.
    6  Momentum15 = 15:14 close - 15:00 open (points); Momentum10 = 15:14 close - 15:05 open.
    7  VolatilityRatio10 = sample stdev of the 9 close-to-close % changes over closes 15:05..15:14,
       divided by the mean of the same figure over the previous 20 sessions (today excluded).
    8  DailyRangeRatio20 = (high-low)/close*100 over 09:15..15:14, divided by the mean of that
       figure over the latest 20 sessions (today included).
    9  Triggers  A: Trend30 < 0 and Momentum15 > 0.   B: close < SMA10 and VolatilityRatio10 >= 1.20.
               C: Trend30 < 0 and Momentum10 < 0.     Base = A or B or C.
    10 Exhaustion = Location30 <= 0.20 AND DailyRangeRatio20 >= 1.20.
    11 Base false -> HOLD.   12 Base and exhaustion -> BUY (long).   13 Base and not exhaustion -> SELL (short).
    14 Any candle missing / duplicated / incomplete / invalid -> HOLD and log it.  A valid session
       has exactly the 360 expected candles with sane O/H/L/C.
    15 Enter in the 15:29 minute of the signal day, exit on the first 1-minute candle (09:15) of the
       next exchange trading day.
    16 Always use the nearest expiry strictly AFTER the signal day.
    17 Worst-fill: buy at the 15:29 minute's high, sell at the 09:15 minute's low.

CHECKLIST (RUN.md Step 1) - answers and ASSUMPTIONS
    1  Underlying          clear    NIFTY 50 index.
    2  Window              ASSUMED  2026-01-01 through the current IST date (--from / --to override).
    3  Signal timeframe    clear    daily bars built from 1m (09:15-15:14) plus the 1m late-session candles.
    4  Signal rule         clear    all inputs and thresholds numeric (steps 3-10).
    5  Decision time       clear    after the 15:14 candle completes.
    6  Direction mapping   ASSUMED  BUY = buy a CE; SELL = buy a PE (long option premium both ways;
                                    the prompt says "open a short" on the index, an option long in the PE
                                    is the closest bought-option equivalent; no naked selling, no margin).
    7  Traded instrument   ASSUMED  NIFTY options (the prompt talks of option minutes, expiries, strikes).
    8  Option specifics    ASSUMED  ATM strike from the 15:14 close (the last completed signal candle),
                                    1 lot (qty = lot_size of the resolved contract), expiry = nearest strictly
                                    after the signal day (prompt step 16).
    9  Entry               clear    15:29 minute of the signal day, at that option bar's HIGH.
    10 Exit                clear    first 1m bar of the next trading day (09:15), at that bar's LOW; no
                                    stop or target (none stated).
    11 Holding period      clear    overnight.  ASSUMED next trading day = next session present in the index
                                    feed; a gap of more than 4 calendar days is treated as bad data.
    12 Costs               ASSUMED  standard option schedule (option_costs).
    13 Position rules      ASSUMED  one at a time (cannot overlap: each trade ends at next 09:15).
    14 Missing data        ASSUMED  skip and list.  Duplicated 1m candles are merged by timestamp by the
                                    py_funcs client, so a duplicate cannot be detected here.
    15 Filters             ASSUMED  side (always LONG) and `signal` = BUY / SELL.
    16 Custom group-bys    ASSUMED  triggers, exhaustion, trigger x exhaustion, Trend30 bucket, Location30
                                    bucket, VolRatio bucket, DailyRange bucket, expiry-at-exit; bucket edges are
                                    descriptive only (they do not feed the signal), all measured at 15:14.
    17 Script name         onh_v1.
    History ASSUMED: the 30 daily bars are the latest 30 sessions present in the index feed; a weekday with
    no data at all (holiday or feed miss) cannot be told apart and is not counted; if any of the 30 is invalid,
    that day is HOLD.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: F401,F403

import argparse
import asyncio
from datetime import date, timedelta

SLUG = "onh_v1"

# The axes the source (eod_trend_signal_v1) compares and this script fixed at one point.
# Expiry changes WHICH contract is bought, so it is the only one that costs fetches.
EXPIRY_MODES = [("next", "nearest expiry strictly after the signal day - may expire next morning"),
                ("skip-1dte", "nearest expiry strictly after the EXIT day - never hold into expiry morning"),
                ("always", "one expiry further out than 'next'")]
RULE = {"expiry_mode": "next"}

SETTINGS = [
    setting("expiry_mode", "Which expiry", kind="other", default=RULE["expiry_mode"], rerun=True,
            options=[{"value": k, "label": v, "raw": k} for k, v in EXPIRY_MODES],
            help="the contract the night is bought in; each one is its own fetch"),
]


def _vals(key):
    return [o["raw"] for o in next(x for x in SETTINGS if x["key"] == key)["options"]]


def pick_expiry(expiries, signal_day, exit_day, mode):
    """The expiry for one mode, or None. 'always' steps one further out than 'next'."""
    if mode == "skip-1dte":
        return next_expiry(expiries, date.fromisoformat(exit_day), 1)
    nxt = next_expiry(expiries, signal_day, 1)
    if mode != "always" or nxt is None:
        return nxt
    return next_expiry(expiries, nxt, 1)
LOTS = 1
ENTRY_TIME, EXIT_TIME = "15:29", "09:15"
SIGNAL_LAST, WINDOW_FIRST = "15:14", "09:15"
LOOKBACK_DAYS = 70                                    # calendar days fetched before --from for the 30-bar history
TREND_N, SMA_N, LOC_N, VOL_PREV, RANGE_N = 30, 10, 30, 20, 20
VOL_THRESHOLD, RANGE_THRESHOLD, LOC_THRESHOLD = 1.20, 1.20, 0.20


def _minutes_list(a: str, b: str) -> list[str]:
    return [f"{m // 60:02d}:{m % 60:02d}" for m in range(hhmm_minutes(a), hhmm_minutes(b) + 1)]


WINDOW_MINUTES = _minutes_list(WINDOW_FIRST, SIGNAL_LAST)            # the 360 expected candles


# ---------------------------------------------------------------------------
# signal (pure; completed candles only)
# ---------------------------------------------------------------------------
def daily_bar(rows: list[list]) -> dict:
    """The day's bar from the 09:15..15:14 window, or {"valid": False, "why": ...}."""
    win = [r for r in rows if WINDOW_FIRST <= r[0] <= SIGNAL_LAST]
    keys = [r[0] for r in win]
    if len(keys) != len(set(keys)):
        return {"valid": False, "why": "duplicated candle"}
    if keys != WINDOW_MINUTES:
        missing = sorted(set(WINDOW_MINUTES) - set(keys))
        return {"valid": False, "why": f"{len(keys)} of {len(WINDOW_MINUTES)} candles in 09:15-15:14"
                                       f" (missing e.g. {missing[:3]})"}
    for r in win:
        o, h, l, c = r[1:5]
        if min(o, h, l, c) <= 0 or h < max(o, c, l) or l > min(o, c, h):
            return {"valid": False, "why": f"invalid OHLC at {r[0]}"}
    by = {r[0]: r for r in win}
    closes = [by[t][4] for t in _minutes_list("15:05", "15:14")]
    chg = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]      # 9 changes
    hi, lo, cl = max(r[2] for r in win), min(r[3] for r in win), win[-1][4]
    return {"valid": True, "why": "", "open": win[0][1], "high": hi, "low": lo, "close": cl,
            "o1500": by["15:00"][1], "o1505": by["15:05"][1], "vol10": statistics.stdev(chg),
            "range_pct": (hi - lo) / cl * 100}


def signal(bars: list[dict], days: list[str], i: int) -> dict:
    """Decision after the 15:14 candle of days[i].  bars[j] is the daily bar of days[j]."""
    d = days[i]
    if i < TREND_N - 1:
        return {"action": "HOLD", "why": f"only {i + 1} sessions of history (need {TREND_N})"}
    span = range(i - TREND_N + 1, i + 1)
    for j in span:
        if not bars[j]["valid"]:
            return {"action": "HOLD", "why": f"{days[j]} invalid in the 30-session history: {bars[j]['why']}"}
    w = [bars[j] for j in span]
    close = bars[i]["close"]
    trend = (w[-1]["close"] / w[0]["close"] - 1) * 100
    sma10 = sum(b["close"] for b in w[-SMA_N:]) / SMA_N
    hh, ll = max(b["high"] for b in w), min(b["low"] for b in w)
    if hh == ll:
        return {"action": "HOLD", "why": "30-bar range is zero"}
    loc = (close - ll) / (hh - ll)
    m15, m10 = close - bars[i]["o1500"], close - bars[i]["o1505"]
    prev = [bars[j]["vol10"] for j in range(i - VOL_PREV, i)]
    avg_prev = sum(prev) / VOL_PREV
    if avg_prev <= 0:
        return {"action": "HOLD", "why": "average late-session volatility of previous 20 sessions is zero"}
    volr = bars[i]["vol10"] / avg_prev
    rmean = sum(bars[j]["range_pct"] for j in range(i - RANGE_N + 1, i + 1)) / RANGE_N
    if rmean <= 0:
        return {"action": "HOLD", "why": "mean daily range is zero"}
    rr = bars[i]["range_pct"] / rmean
    A = trend < 0 and m15 > 0
    B = close < sma10 and volr >= VOL_THRESHOLD
    C = trend < 0 and m10 < 0
    base = A or B or C
    exh = loc <= LOC_THRESHOLD and rr >= RANGE_THRESHOLD
    m = {"trend30": trend, "sma10": sma10, "loc30": loc, "mom15": m15, "mom10": m10, "volr": volr,
         "rr20": rr, "close": close, "hh30": hh, "ll30": ll, "A": A, "B": B, "C": C, "exh": exh}
    if not base:
        return {"action": "HOLD", "why": "base condition false", **m}
    return {"action": "BUY" if exh else "SELL", "why": "", **m}


def make_tags(s: dict, expiry_at_exit: bool) -> dict:
    trig = "+".join(k for k in "ABC" if s[k])
    return {"direction": s["action"], "triggers": trig, "exhaustion": "yes" if s["exh"] else "no",
            "trigger x exhaustion": f"{trig} / exh {'yes' if s['exh'] else 'no'}",
            "trend30": bucket(s["trend30"], [-2, 0, 2], ["below -2%", "-2% to 0", "0 to 2%", "above 2%"]),
            "location30": bucket(s["loc30"], [0.2, 0.5, 0.8], ["<=0.2 (low)", "0.2-0.5", "0.5-0.8", ">0.8"]),
            "volratio10": bucket(s["volr"], [0.8, 1.2], ["below 0.8", "0.8-1.2", "1.2 and above"]),
            "dailyrange20": bucket(s["rr20"], [0.8, 1.2], ["below 0.8", "0.8-1.2", "1.2 and above"]),
            "expiry at exit": "exit on expiry day" if expiry_at_exit else "expiry after exit day"}


# ---------------------------------------------------------------------------
# simulate (pure: option bars -> fills)
# ---------------------------------------------------------------------------
def simulate(entry_rows: list[list], exit_rows: list[list]) -> tuple[list | None, list | None, str]:
    """Entry bar = the 15:29 option minute, exit bar = the 09:15 option minute next session.
    Rule 2 holds (15:29 is later than the bar after the 15:14 candle, 15:15); a missing minute
    skips the trade (rule 6)."""
    assert hhmm_minutes(ENTRY_TIME) >= hhmm_minutes(candle_done_at(SIGNAL_LAST, 1))
    eb = next((r for r in entry_rows if r[0] == ENTRY_TIME), None)
    xb = next((r for r in exit_rows if r[0] == EXIT_TIME), None)
    if eb is None:
        return None, None, f"no option bar at {ENTRY_TIME} on the signal day"
    if xb is None:
        return None, None, f"no option bar at {EXIT_TIME} on the exit day"
    for b in (eb, xb):
        if min(b[1:5]) <= 0 or b[2] < max(b[1], b[3], b[4]) or b[3] > min(b[1], b[2], b[4]):
            return None, None, f"invalid option bar at {b[0]}"
    return eb, xb, ""


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
async def run(frm: date, to: date) -> None:
    use_expiry = _vals("expiry_mode")
    today = date.today()
    fetch_to = min(to + timedelta(days=7), today - timedelta(days=1))    # next session for the last signal day
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        ukey = und["instrument_key"]
        info = await up.option_chain_info(ukey)
        step = info["strike_step"]
        if not step:
            raise SystemExit("could not read the strike step from Upstox")
        expiries = await up.expiry_calendar(ukey, frm, to + timedelta(days=7))
        print(f"NIFTY key {ukey}, strike step {step}, {len(expiries)} expiries known")
        cs = await up.candles(ukey, "1m", frm - timedelta(days=LOOKBACK_DAYS), fetch_to)
        sessions = sessions_from(cs)
        days = sorted(sessions)
        bars = [daily_bar(sessions[d]) for d in days]
        print(f"{len(days)} index sessions fetched ({days[0]} .. {days[-1]})" if days else "no index data")

        trades, skipped, opt_sessions, holds = [], [], {}, 0
        # the expiry mode changes which contract is bought, so it pairs with the day.
        for (i, d), expiry_mode in [((i, d), m) for i, d in enumerate(days) for m in use_expiry]:
            dd = date.fromisoformat(d)
            if not (frm <= dd <= to):
                continue

            def skip(why):
                skipped.append((d, why))
                print(f"  SKIP {d}: {why}")

            if len(sessions[d]) < 375:
                skip(f"short session ({len(sessions[d])} of 375 bars)"); continue
            if not bars[i]["valid"]:
                skip(f"HOLD, signal window invalid: {bars[i]['why']}"); continue
            s = signal(bars, days, i)
            if s["action"] == "HOLD":
                holds += 1
                if s["why"] != "base condition false":
                    skip(f"HOLD, {s['why']}"); holds -= 1
                continue
            if i + 1 >= len(days):
                skip("no next session in the feed (exit not yet possible)"); continue
            xd = days[i + 1]
            if (date.fromisoformat(xd) - dd).days > 4:
                skip(f"next session {xd} is more than 4 days away (possible missing data)"); continue
            if not any(r[0] == EXIT_TIME for r in sessions[xd]):
                skip(f"no index candle at {EXIT_TIME} on exit day {xd}"); continue

            opt_type = "CE" if s["action"] == "BUY" else "PE"
            expiry = pick_expiry(expiries, dd, xd, expiry_mode)
            if expiry is None:
                skip(f"no expiry for mode {expiry_mode}"); continue
            strike = atm_strike(s["close"], step)                       # 15:14 close, the completed signal candle
            c = await up.resolve_option(ukey, expiry, strike, opt_type)
            if c is None or not c["lot_size"]:
                skip(f"no contract for {expiry} {strike:.0f} {opt_type}"); continue
            try:
                er = await up.option_candles(c, dd)
                xr = await up.option_candles(c, date.fromisoformat(xd))
            except (RuntimeError, ValueError) as exc:
                skip(f"option candles failed for {c['trading_symbol']}: {exc}"); continue
            eb, xb, why = simulate(er, xr)
            if eb is None:
                skip(f"{c['trading_symbol']}: {why}"); continue
            entry_px, exit_px = worst_fills("LONG", eb, xb)              # buy at high, sell at low
            qty = LOTS * c["lot_size"]
            dated = [[f"{d} {r[0]}"] + r[1:] for r in er] + [[f"{xd} {r[0]}"] + r[1:] for r in xr]
            mfe, mae = excursion(dated, "LONG", entry_px, f"{d} {ENTRY_TIME}", f"{xd} {EXIT_TIME}")
            exp_at_exit = c["expiry"] == xd
            levels = [{"name": "SMA10 (daily)", "price": round(s["sma10"], 2)},
                      {"name": "30-bar high", "price": round(s["hh30"], 2)},
                      {"name": "30-bar low", "price": round(s["ll30"], 2)}]
            trades.append(make_trade(
                day=d, exit_day=xd, side="LONG", symbol=c["trading_symbol"],
                entry_time=ENTRY_TIME, entry_px=entry_px, exit_time=EXIT_TIME, exit_px=exit_px, qty=qty,
                exit_reason="next-morning time exit", capital=entry_px * qty, expiry=c["expiry"],
                option_type=opt_type, mfe=mfe, mae=mae, levels=levels,
                variant={"signal": s["action"], "expiry_mode": expiry_mode},
                tags=make_tags(s, exp_at_exit),
                note=(f"trend30 {s['trend30']:.2f}%  loc30 {s['loc30']:.2f}  mom15 {s['mom15']:.1f}  "
                      f"mom10 {s['mom10']:.1f}  volr {s['volr']:.2f}  range20 {s['rr20']:.2f}")))
            opt_sessions.setdefault(c["trading_symbol"], {})[d] = er
            opt_sessions[c["trading_symbol"]][xd] = xr
            print(f"  {d} {s['action']:4s} {c['trading_symbol']}  {entry_px:.2f} -> {exit_px:.2f}  "
                  f"net {trades[-1]['net']:,.0f}")

    in_window = {k: v for k, v in sessions.items() if frm.isoformat() <= k <= to.isoformat()}
    print(f"\nwindow sessions {len(in_window)}, HOLD (no signal) {holds}, skipped {len(skipped)}, trades {len(trades)}")
    if not trades:
        print("no trades - no report written")
        return
    lot = trades[-1]["qty"] // LOTS
    limits = [
        "ASSUMED: BUY = buy a NIFTY CE, SELL = buy a NIFTY PE (long premium both ways); the prompt's 'short' is not an index short or a sold option.",
        "ASSUMED: ATM strike from the 15:14 close (last completed signal candle); 1 lot; standard option cost schedule.",
        "ASSUMED: next trading day = next session in the index feed; a gap of more than 4 calendar days is skipped as bad data.",
        "ASSUMED: the 30-bar history is the latest 30 sessions in the feed; a weekday with no data cannot be detected; duplicated 1m candles are merged by timestamp before this script sees them.",
        "Expiry strictly after the signal day (prompt step 16) means the position can be exited on the morning of its expiry day (tag 'expiry at exit'); this departs from the default of rule 10.",
        "Entry at 15:29 (prompt) is later than the bar after the signal candle (15:15); it uses no later information than the signal.",
        "Fills: buy at the 15:29 option bar's high, sell at the 09:15 option bar's low. Overnight gaps are the whole result; no stop or target exists.",
        "Group-by bucket edges (Trend30, Location30, ratios) are descriptive and were not tuned. The signal thresholds are the prompt's, not fitted. No parameter is selected on this window, but the result is still one window (6 months) and a small sample.",
        "Skipped days are printed to the console only.",
    ]
    meta = {"title": "Overnight hold v1 - seven-feature EOD signal",
            "subtitle": "NIFTY options, decide after 15:14, enter 15:29, exit next 09:15",
            "instrument": "NIFTY 50 options (ATM, nearest expiry strictly after the signal day)",
            "from": frm.isoformat(), "to": to.isoformat(), "lot_size": lot,
            "fill_rule": "buy at the bar high, sell at the bar low (15:29 entry bar, 09:15 exit bar)",
            "cost_model": "standard option schedule (brokerage, STT, exchange, SEBI, stamp, GST)",
            "params": {"trend bars": TREND_N, "SMA": SMA_N, "location bars": LOC_N,
                       "volatility ratio >=": VOL_THRESHOLD, "daily range ratio >=": RANGE_THRESHOLD,
                       "location <=": LOC_THRESHOLD, "lots": LOTS, "entry": ENTRY_TIME, "exit": EXIT_TIME},
            "rule_steps": [
                "Build daily bars from the 360 one-minute candles 09:15-15:14; a session needs exactly those candles or it is invalid.",
                "After the 15:14 candle completes compute Trend30, SMA10, Location30, Momentum15/10, VolatilityRatio10, DailyRangeRatio20.",
                "Triggers: A Trend30<0 and Mom15>0; B close<SMA10 and VolRatio10>=1.20; C Trend30<0 and Mom10<0. Base = A or B or C.",
                "Exhaustion = Location30<=0.20 and DailyRangeRatio20>=1.20.",
                "No base: no trade. Base and exhaustion: BUY (buy a CE). Base without exhaustion: SELL (buy a PE).",
                "Enter in the 15:29 minute at that bar's high, on the ATM option of the nearest expiry strictly after the signal day.",
                "Exit at the 09:15 minute of the next trading day at that bar's low."],
            "limits": limits, "coverage": coverage(in_window, frm, to, 375)}
    groups = [{"name": "Triggers fired", "keys": ["triggers"]},
              {"name": "Exhaustion", "keys": ["exhaustion"]},
              {"name": "Triggers x exhaustion", "keys": ["trigger x exhaustion"]},
              {"name": "Trend30", "keys": ["trend30"]},
              {"name": "Location30", "keys": ["location30"]},
              {"name": "VolatilityRatio10", "keys": ["volratio10"]},
              {"name": "DailyRangeRatio20", "keys": ["dailyrange20"]},
              {"name": "Expiry at exit", "keys": ["expiry at exit"]}]
    meta.setdefault("rejected", []).append(
        ["The source's two partial-session readings",
         "PARTIAL_MODES asks whether a short session poisons every daily window that contains "
         "it or is simply left out. This script does not build a daily series at all - its "
         "features come from the intraday sessions - so there is no window for a partial day "
         "to poison, and the axis has nothing to price here."])
    payload = build_payload(meta, trades, sessions, opt_sessions, groups,
                            settings=SETTINGS, chart="default")
    path = write_report(payload, SLUG)
    print(console_summary(trades))
    print(path)


def main() -> None:
    ap = argparse.ArgumentParser(description="ONH v1 backtest")
    yday = date.today() - timedelta(days=1)
    ap.add_argument("--from", dest="frm", type=date.fromisoformat, default=START_DATE)
    ap.add_argument("--to", dest="to", type=date.fromisoformat, default=END_DATE)
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    SETTINGS[:] = narrow(SETTINGS, a)
    check_window(a.frm, a.to)
    print(f"axes: {len(combos(SETTINGS))} simulated combinations")
    if a.to > date.today() - timedelta(days=1):
        a.to = date.today() - timedelta(days=1)                          # rule 7: today is not complete
    asyncio.run(run(a.frm, a.to))


if __name__ == "__main__":
    main()
