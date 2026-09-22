"""Overnight Hold v2 - the sign of the day, bought six strikes in the money.

STRATEGY PROMPT (verbatim summary of 10_onh_v2.txt)
  Step 1  Build the session's own bar from the 1m candles: the 09:15 open and the 15:14 close.
  Step 2  Decide after the 15:14 candle completes; nothing from 15:15 onward is read for direction.
  Step 3  15:14 close ABOVE 09:15 open -> BUY, buy a call. BELOW -> SELL, buy a put. Exactly equal, or
          any candle missing/duplicated/invalid -> no trade.
  Step 4  Strike six strikes in the money (300 points): BUY = call 300 below, SELL = put 300 above, where
          the index is the 15:20 price rounded to the nearest 50.
  Step 5  Deeper is better in the data but not tradeable; 6 is the last honest rung.
  Step 6  Nearest weekly expiry strictly after the exit day.
  Step 7  Buy in the 15:20 minute.
  Step 8  Line to beat = what I paid + round-trip costs.
  Step 9  From 09:30 next morning, look at each completed 1m candle: is its LOW above the line? The first
          one that is, sell there, at that minute's low.
  Step 10 Do not start that scan before 09:30.
  Step 11 If no minute qualifies by 15:14, sell in the 15:14 minute.
  Step 12 No stop, no target. The premium paid is the stop.
  Step 13 Buy at the entry minute's high and sell at the exit minute's low.

RUN.md STEP 1 CHECKLIST (no user was available; every non-clear item is marked)
  1  Underlying          clear    NIFTY 50 index (signal + strike reference)
  2  Window              ASSUMED  2026-01-01 through the current IST date (--from/--to = SIGNAL/entry days)
  3  Signal timeframe    clear    1m candles; the signal compares the 09:15 open with the 15:14 close
  4  Signal rule         clear    close(15:14 bar) > open(09:15 bar) -> BUY; < -> SELL; == -> no trade
  5  Decision time       clear    after the 15:14 candle completes (15:15); entry 15:20 (Step 7)
  6  Direction mapping   clear    BUY -> buy CE, SELL -> buy PE (always LONG the option)
  7  Traded instrument   clear    NIFTY weekly option
  8  Option specifics    ASSUMED  buy; strike = ATM(15:20 index price) -/+ 6 strikes ITM, strike step read from
                                   Upstox; expiry = nearest at least 1 day after the exit day; 1 lot
  9  Entry               clear    15:20 minute, at that minute's HIGH (rule 1)
  10 Exit                clear    first completed minute >= 09:30 whose LOW > (entry + costs per unit) is the
                                   signal; sell in the NEXT minute at its low (rule 2/3); else 15:14 minute
                                   (fill in that bar); no stop/target
  11 Holding period      clear    overnight, exit on the next trading session
  12 Costs               ASSUMED  standard option_costs schedule
  13 Position rules      ASSUMED  one at a time (cannot overlap anyway)
  14 Missing data        ASSUMED  skip the trade, print the reason
  15 Filters             ASSUMED  none beyond side (single variant); direction (BUY/SELL) is a tag+group
  16 Custom group-bys    ASSUMED  one: "direction" (BUY/SELL, from the 09:15 open vs 15:14 close)
  17 Script name         clear    onh_v2

ASSUMPTIONS
  A1 "the index is the 15:20 price": the OPEN of the 15:20 one-minute index bar (the price when 15:20
     starts; nothing from inside the 15:20 candle is used), rounded to the nearest strike step.
  A2 Strike step is read from Upstox's live option chain (NIFTY: 50) and applied to the whole window.
  A3 "line to beat": entry price + round-trip costs per unit, where the costs are the standard option
     schedule evaluated at an exit price equal to the line itself (fixed point; STT depends on the exit).
     The actual trade then carries the real costs at the actual exit fill.
  A4 "Exit day" = the next session present in the NIFTY 1m data after the entry day; a gap of more than
     5 calendar days is treated as suspect data and the day is skipped.
  A5 Duplicated candles cannot be seen (the API layer keys candles by timestamp); a missing 09:15/15:14
     bar, an entry-session with != 375 bars, or an invalid OHLC (high < low, open/close outside the range,
     non-positive) skips the day. The exit-day index session must also be complete (375 bars).
  A6 Session data for today is used only after 15:45 (rule 7).
  A7 Trades that have entered but whose exit day is not yet available/complete are skipped (the last
     final signal day is normally skipped when its next session is not available for this reason).
  A8 15:14 forced exit: if the 15:14 option bar is missing the trade is skipped.

CONFLICTS WITH THE RULES TO LIVE BY (rules win)
  C1 Step 9 sells "at that minute's low" in the very minute whose low cleared the line. The rules make that
     a signal from a completed candle: the sell happens in the NEXT one-minute bar, at that bar's low.
  C2 Step 11's 15:14 time exit is a scheduled exit, so it fills in the 15:14 bar itself (rule 3).
  (Step 7 buys at 15:20, later than the next-bar minimum of 15:15: acceptable, nothing is read late.)
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: E402,F401,F403
from py_funcs import IST  # noqa: E402  (explicit: star import skips nothing here, kept for clarity)

NAME = "onh_v2"
SESSION_ROWS = 375
SIGNAL_OPEN, SIGNAL_CLOSE = "09:15", "15:14"
ENTRY_MIN = "15:20"
SCAN_START, FORCE_EXIT = "09:30", "15:14"
ITM_STEPS = 6
LOTS = 1
TREND_LOOKBACK_DAYS = 70          # calendar days of daily candles behind --from, for the 30-day trend

# The three axes the source compares and this script used to fix at one point each.
# EXIT RULES - all six re-read bars already fetched, so the sweep is free.
#   (key, label, start minute, limit minute, trigger price, threshold)
#   threshold None = a scheduled time exit in the start bar itself (rule 3)
EXIT_RULES = [
    ("low-0930", "first minute whose LOW clears costs, from 09:30", "09:30", "15:14", "low", 1.0),
    ("low-0916", "first minute whose LOW clears costs, from 09:16", "09:16", "15:14", "low", 1.0),
    ("low1-0930", "first minute whose LOW clears costs +1%, from 09:30", "09:30", "15:14", "low", 1.01),
    ("close-0915", "first CLOSE above costs, from 09:15", "09:15", "15:14", "close", 1.0),
    ("fixed-0930", "09:30 fixed", "09:30", "09:30", "low", None),
    ("fixed-1514", "15:14 fixed - hold the full session", "15:14", "15:14", "low", None),
]
EXIT_BY_KEY = {k: (st, lim, trig, thr) for k, _l, st, lim, trig, thr in EXIT_RULES}
RULE_EXIT = "low-0930"
# THE STRIKE LADDER - each rung is its own fetch, which is the only part that costs anything.
RUNGS = [0, 2, 4, 6, 8]
RULE_RUNG = 6
# THE EXTRA HOLD CONDITIONS - a filter over trades that already exist, so every night is
# traded and tagged and any condition can be switched off. (tag name, label)
HOLD_TAGS = [
    ("move >= 0.15%", "day move at least 0.15%"),
    ("move >= 0.30%", "day move at least 0.30%"),
    ("previous day agrees", "previous day moved the same way"),
    ("5-day trend agrees", "5-day trend agrees with the day"),
    ("30-day trend agrees", "30-day trend agrees with the day"),
    ("gap agrees", "opening gap agrees with the day"),
    ("range >= 0.69x", "day range at least 0.69 x the 5-day average"),
    ("range below average", "day range below the 5-day average"),
    ("not Friday", "no Friday entries - no weekend hold"),
]
YES, NO, NA = "yes", "no", "n/a"

SETTINGS = [
    setting("hold_filter", "Extra hold condition", kind="entry", mode="filter", default="none",
            help="one extra condition on top of the rule; 'none' is the rule as it is",
            options=[{"value": "none", "label": "none - the rule as it is", "tag": None}]
                    + [{"value": t, "label": lab, "tag": {t: [YES]}} for t, lab in HOLD_TAGS]),
    setting("exit_rule", "Exit rule", kind="exit", default=RULE_EXIT,
            options=[{"value": k, "label": lab, "raw": k} for k, lab, *_ in EXIT_RULES],
            help="how the next morning is exited; all six re-read the same bars"),
    setting("moneyness", "Strike depth", kind="strike", default=RULE_RUNG, rerun=True,
            options=[{"value": v, "label": ("at the money" if v == 0 else f"{v} strikes in the money"),
                      "raw": v} for v in RUNGS],
            help="each rung is fetched and priced on the same nights"),
]
MAX_GAP_DAYS = 5


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def session_ready(day: str) -> bool:
    """Rule 7: today's session is used only after 15:45."""
    now = datetime.now(IST)
    if day > now.date().isoformat():
        return False
    return not (day == now.date().isoformat() and now.strftime("%H:%M") < "15:45")


def valid_bars(rows: list[list]) -> bool:
    for r in rows:
        _, o, h, l, c = r[:5]
        if min(o, h, l, c) <= 0 or h < l or not (l <= o <= h) or not (l <= c <= h):
            return False
    return True


def line_to_beat(entry_px: float, qty: int) -> float:
    """Entry + round-trip costs per unit (A3): solve L = entry + costs(entry, L)/qty."""
    line = entry_px
    for _ in range(50):
        nxt = entry_px + option_round_trip("LONG", entry_px, line, qty) / qty
        if abs(nxt - line) < 1e-9:
            return nxt
        line = nxt
    return line


# ---------------------------------------------------------------------------
# signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def signal(rows: list[list]) -> tuple[str | None, str, dict]:
    """(direction BUY/SELL/None, reason, facts) from one full index session.
    Only the 09:15 bar and the 15:14 bar are read (the 15:14 candle is complete at 15:15)."""
    if len(rows) != SESSION_ROWS:
        return None, f"index session has {len(rows)} bars, not {SESSION_ROWS}", {}
    if not valid_bars(rows):
        return None, "invalid index candle (OHLC inconsistent or non-positive)", {}
    by = {r[0]: r for r in rows}
    if len(by) != len(rows):
        return None, "duplicated index candle", {}
    if SIGNAL_OPEN not in by or SIGNAL_CLOSE not in by or ENTRY_MIN not in by:
        return None, "09:15, 15:14 or 15:20 index candle missing", {}
    o, c = by[SIGNAL_OPEN][1], by[SIGNAL_CLOSE][4]
    facts = {"open": o, "close": c, "spot_1520": by[ENTRY_MIN][1]}
    if c > o:
        return "BUY", "close above open", facts
    if c < o:
        return "SELL", "close below open", facts
    return None, "15:14 close equals 09:15 open", facts


# ---------------------------------------------------------------------------
# simulate (pure): entry-day option bars + exit-day option bars -> entry / exit
# ---------------------------------------------------------------------------
def simulate(entry_rows: list[list], exit_rows: list[list], qty: int, exit_key: str = RULE_EXIT) -> dict:
    """Returns {"skip": reason} or {entry_bar, exit_bar, trigger, reason, line}.
    Entry: the 15:20 bar (buy at its HIGH). Exit: first completed bar >= 09:30 (and before 15:14)
    whose LOW > line -> sell in the NEXT bar at its LOW (rule 2/3); else the 15:14 bar itself."""
    eb = next((r for r in entry_rows if r[0] == ENTRY_MIN), None)
    if eb is None:
        return {"skip": "option bar 15:20 missing on entry day"}
    if not valid_bars([eb]):
        return {"skip": "invalid option bar at 15:20"}
    line = line_to_beat(eb[2], qty)                                   # entry fills at the bar high
    by = {r[0]: r for r in exit_rows}
    if not exit_rows:
        return {"skip": "no option bars on exit day"}
    if not valid_bars(exit_rows):
        return {"skip": "invalid option bar on exit day"}
    start, limit, trig, thr = EXIT_BY_KEY[exit_key]
    if thr is None:                                   # a scheduled time exit fills in that bar (rule 3)
        fb = by.get(start)
        if fb is None:
            return {"skip": f"option bar {start} missing on exit day (fixed exit)"}
        return {"entry_bar": eb, "exit_bar": fb, "trigger": None, "reason": f"fixed exit {start}", "line": line}
    want_px = line * thr
    ordered = sorted(exit_rows)
    for r in ordered:
        if r[0] < start:
            continue
        if r[0] >= limit:
            break
        px = r[3] if trig == "low" else r[4]          # the completed minute's LOW, or its CLOSE
        if px > want_px:
            m = hhmm_minutes(r[0]) + 1
            nxt = by.get(f"{m // 60:02d}:{m % 60:02d}")
            if nxt is None:
                return {"skip": f"option bar after {r[0]} missing (needed to act on the signal)"}
            return {"entry_bar": eb, "exit_bar": nxt, "trigger": r, "line": line,
                    "reason": "cleared costs" + ("" if thr == 1.0 else f" +{(thr - 1) * 100:.0f}%")}
    fb = by.get(FORCE_EXIT)
    if fb is None:
        return {"skip": "option bar 15:14 missing on exit day (time exit)"}
    return {"entry_bar": eb, "exit_bar": fb, "trigger": None, "reason": "time exit 15:14", "line": line}


def day_features(daily: list[dict], day: str, move_pct: float, open_915: float) -> dict:
    """The facts the extra hold conditions test, from DAILY candles up to and including the
    session BEFORE `day` (rule 4: nothing from the future, nothing from the day itself except
    its own 09:15 open and 15:14 close, which the signal already used).

    Returns tag values, not booleans, so the report can group by them as well as filter."""
    past = [c for c in daily if c["timestamp"][:10] < day]
    prev = past[-1] if past else None
    closes = [c["close"] for c in past]
    ranges = [c["high"] - c["low"] for c in past]
    today = next((c for c in daily if c["timestamp"][:10] == day), None)
    agree = lambda x: NA if x is None else (YES if x * move_pct > 0 else NO)

    prev_move = None
    if len(past) >= 2 and past[-2]["close"]:
        prev_move = (past[-1]["close"] - past[-2]["close"]) / past[-2]["close"] * 100
    ret5 = None
    if len(closes) >= 6 and closes[-6]:
        ret5 = (closes[-1] - closes[-6]) / closes[-6] * 100
    trend30 = None
    if len(closes) >= 31 and closes[-31]:
        trend30 = (closes[-1] - closes[-31]) / closes[-31] * 100
    gap = None
    if prev and prev["close"]:
        gap = (open_915 - prev["close"]) / prev["close"] * 100
    ratio = None
    if today and len(ranges) >= 5:
        avg5 = sum(ranges[-5:]) / 5
        if avg5:
            ratio = (today["high"] - today["low"]) / avg5

    wd = date.fromisoformat(day).weekday()
    return {
        "move >= 0.15%": YES if abs(move_pct) >= 0.15 else NO,
        "move >= 0.30%": YES if abs(move_pct) >= 0.30 else NO,
        "previous day agrees": agree(prev_move),
        "5-day trend agrees": agree(ret5),
        "30-day trend agrees": agree(trend30),
        "gap agrees": agree(gap),
        "range >= 0.69x": NA if ratio is None else (YES if ratio >= 0.69 else NO),
        "range below average": NA if ratio is None else (YES if ratio < 1.0 else NO),
        "not Friday": YES if wd != 4 else NO,
    }


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
async def run(frm: date, to: date, settings: list[dict]) -> None:
    rungs = [o["raw"] for o in next(x for x in settings if x["key"] == "moneyness")["options"]]
    exit_keys = [o["raw"] for o in next(x for x in settings if x["key"] == "exit_rule")["options"]]
    skips: list[tuple[str, str]] = []
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list[list]]] = {}
    today = datetime.now(IST).date()

    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        step = info["strike_step"]
        if not step:
            raise SystemExit("could not read the strike step from Upstox")
        end = min(to + timedelta(days=10), today)
        print(f"NIFTY key {key}; strike step {step}; fetching 1m index {frm} .. {end}")
        cs = await up.candles(key, "1m", frm, end)
        sessions = sessions_from(cs)
        # daily candles behind the window, for the 5- and 30-day trend conditions only.
        # No trade is taken outside the window; these are read, never traded.
        daily = await up.candles(key, "1d", frm - timedelta(days=TREND_LOOKBACK_DAYS), end)
        print(f"daily candles for the trend conditions: {len(daily)} "
              f"({frm - timedelta(days=TREND_LOOKBACK_DAYS)} .. {end}, read only)")
        expiries = await up.expiry_calendar(key, frm, end)
        days = [d for d in sessions if frm.isoformat() <= d <= to.isoformat()]
        all_days = list(sessions)

        for day in days:
            rows = sessions[day]
            if not session_ready(day):
                skips.append((day, "session not complete yet")); continue
            direction, why, f = signal(rows)
            if direction is None:
                skips.append((day, f"no signal: {why}")); continue
            later = [d for d in all_days if d > day]
            if not later:
                skips.append((day, "no exit session available yet")); continue
            xday = later[0]
            if (date.fromisoformat(xday) - date.fromisoformat(day)).days > MAX_GAP_DAYS:
                skips.append((day, f"next session {xday} is more than {MAX_GAP_DAYS} days away (suspect data)")); continue
            if not session_ready(xday):
                skips.append((day, f"exit session {xday} not complete yet")); continue
            if len(sessions[xday]) != SESSION_ROWS or not valid_bars(sessions[xday]):
                skips.append((day, f"exit-day index session {xday} incomplete or invalid ({len(sessions[xday])} bars)")); continue

            opt_type = "CE" if direction == "BUY" else "PE"
            spot = f["spot_1520"]
            exp = next_expiry(expiries, date.fromisoformat(xday), 1)
            if exp is None:
                skips.append((day, "no expiry at least 1 day after the exit day")); continue
            move_pct = (f["close"] - f["open"]) / f["open"] * 100 if f["open"] else 0.0
            holds = day_features(daily, day, move_pct, f["open"])

            for rung in rungs:
                tag = f"{day} [{rung} ITM]"
                strike = strike_offset(spot, step, rung, opt_type, itm=True)
                c = await up.resolve_option(key, exp, strike, opt_type)
                if c is None:
                    skips.append((tag, f"contract not found: {exp} {strike:.0f} {opt_type}")); continue
                erows = await up.option_candles(c, date.fromisoformat(day))
                xrows = await up.option_candles(c, date.fromisoformat(xday))
                qty = LOTS * c["lot_size"]
                if qty <= 0:
                    skips.append((tag, "contract carries no lot size")); continue
                for ex_key in exit_keys:
                    sim = simulate(erows, xrows, qty, ex_key)
                    if "skip" in sim:
                        skips.append((f"{tag} {ex_key}", f"{c['trading_symbol']}: {sim['skip']}")); continue
                    eb, xb = sim["entry_bar"], sim["exit_bar"]
                    entry_px, exit_px = worst_fills("LONG", eb, xb)   # rule 1: buy high, sell low
                    m1, a1 = excursion(erows, "LONG", entry_px, ENTRY_MIN, "15:29")
                    m2, a2 = excursion(xrows, "LONG", entry_px, "09:15", xb[0])
                    trades.append(make_trade(
                        day=day, exit_day=xday, side="LONG", symbol=c["trading_symbol"],
                        entry_time=eb[0], entry_px=entry_px, exit_time=xb[0], exit_px=exit_px, qty=qty,
                        exit_reason=sim["reason"], kind="option", capital=entry_px * qty,
                        entry_spot=spot, mfe=max(m1, m2), mae=min(a1, a2),
                        option_type=opt_type, expiry=c["expiry"],
                        variant={"moneyness": rung, "exit_rule": ex_key},
                        tags={"direction": direction, **holds},
                        levels=[{"name": "09:15 open", "price": f["open"], "from": SIGNAL_OPEN, "to": SIGNAL_CLOSE},
                                {"name": "15:14 close", "price": f["close"], "from": SIGNAL_CLOSE, "to": ENTRY_MIN}],
                        note=(f"{direction}: 15:14 close {f['close']:.2f} vs 09:15 open {f['open']:.2f} "
                              f"({move_pct:+.2f}%); strike {strike:.0f} ({rung} in) from 15:20 price {spot:.2f}; "
                              f"line to beat {sim['line']:.2f}; exit rule {ex_key}"
                              + (f"; trigger {sim['trigger'][0]}" if sim["trigger"] else ""))))
                if rung == RULE_RUNG:                 # only the rule's rung keeps candles for the chart
                    osess = option_sessions.setdefault(c["trading_symbol"], {})
                    osess[day], osess[xday] = erows, xrows
            print(f"{day} {direction:4s} {spot:.0f}  {len(rungs)}x{len(exit_keys)} priced")

    print(f"\nSkipped {len(skips)} day(s):")
    for d, why in skips:
        print(f"  {d}: {why}")

    window = {d: r for d, r in sessions.items() if frm.isoformat() <= d <= to.isoformat()}
    meta = {
        "title": "Overnight Hold v2 - sign of the day, 6 strikes ITM",
        "subtitle": "Buy a NIFTY call (15:14 close above 09:15 open) or put (below) at 15:20; sell next morning the "
                    "first minute after 09:30 that clears costs, else 15:14",
        "instrument": "NIFTY 50 weekly options (bought only)",
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": info["lot_size"],
        "fill_rule": "Every buy at the bar's high, every sell at the bar's low; a signal from a completed "
                     "minute is acted on in the next minute; the 15:14 time exit fills in its own bar.",
        "cost_model": "Standard option schedule (Upstox flat brokerage, STT on sell side, exchange, SEBI, stamp, GST)",
        "params": {"signal": "15:14 close vs 09:15 open", "strike": f"{ITM_STEPS} steps ITM (step {step:g})",
                   "entry": f"{ENTRY_MIN} bar high", "scan from": SCAN_START, "time exit": FORCE_EXIT,
                   "expiry": "nearest >= 1 day after exit day", "lots": LOTS},
        "rule_steps": [
            "Take the 09:15 open and the 15:14 close of the NIFTY session (complete 1m candles only).",
            "Decide after the 15:14 candle completes: close above open = BUY (buy a call), below = SELL (buy a put); equal or bad data = no trade.",
            f"Strike = the index price at 15:20, rounded to the nearest {step:g}, moved {ITM_STEPS} strikes in the money.",
            "Expiry = the nearest weekly expiry at least one day after the exit day.",
            "Buy in the 15:20 minute at that minute's high.",
            "Line to beat = price paid + round-trip costs per unit.",
            "From 09:30 next morning, when a completed minute's low is above the line, sell in the next minute at its low.",
            "If nothing qualifies before 15:14, sell in the 15:14 minute at its low.",
            "No stop and no target; the premium paid is the maximum loss."],
        "limits": [
            "ASSUMED: window = 2026-01-01 through the current IST date unless --from/--to given (dates are entry days).",
            "ASSUMED: '15:20 index price' = open of the 15:20 index bar; strike step read from Upstox and applied to the whole window.",
            "ASSUMED: line to beat uses the standard option costs evaluated at an exit price equal to the line; the trade carries the real costs.",
            "ASSUMED: 1 lot; qty from each contract's own lot size; one position at a time; standard option costs.",
            "ASSUMED: exit day = next session in the data; a >5 day gap, missing/invalid candles or missing option bars skip the trade (listed on the console).",
            "ASSUMED: duplicated candles cannot be detected (the API layer keys candles by time).",
            "RULE OVERRIDE: the prompt sells in the very minute whose low cleared the line; per the rules the sell is in the NEXT minute at its low.",
            "IN-SAMPLE: the 6-strike depth, 15:20 entry and 09:30 scan start were chosen by looking at data of this kind; results are in-sample and not a forecast.",
            "Capital = premium paid x qty (bought options). Sessions skipped are printed on the console, not in the report.",
            f"Skipped in this run: {len(skips)} day(s)."],
        "coverage": coverage(window, frm, to, SESSION_ROWS),
    }
    groups = ([{"name": "direction (BUY call / SELL put)", "keys": ["direction"]}]
              + [{"name": lab, "keys": [t]} for t, lab in HOLD_TAGS]
              + [{"name": "direction x day move", "keys": ["direction", "move >= 0.30%"]}])
    payload = build_payload(meta, trades, sessions, option_sessions, groups,
                            settings=settings, chart="default")
    path = write_report(payload, NAME)
    print(console_summary(trades))
    print(path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Overnight Hold v2 backtest")
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat())
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    settings = narrow(SETTINGS, a)
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    check_window(frm, to)
    rungs = [o["raw"] for o in next(x for x in settings if x["key"] == "moneyness")["options"]]
    print(f"strike ladder {rungs}; exit rules "
          f"{[o['raw'] for o in next(x for x in settings if x['key'] == 'exit_rule')['options']]} are free")
    asyncio.run(run(frm, to, settings))


if __name__ == "__main__":
    main()
