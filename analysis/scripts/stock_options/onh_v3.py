"""Overnight Hold v3 on STOCK options - v2 plus the time-value condition.

v3 = v2 exactly, plus ONE condition that decides whether a night is traded: at 15:19 read the chosen
contract's price; time value = price - intrinsic (distance from strike to the stock's 15:19 close);
if time value is MORE than 15% of the price, do not trade tonight.  It is a filter in the panel
(off / 15% / 10% / 5%; the rule is 15%) so the declined nights stay visible.  A night whose 15:19
option minute has no trade cannot be read and is declined by the rule (tagged n/a).

The v2 rule, carried over:

THE RULE (index onh_v2, carried to stock options unchanged except where a stock option differs)
  Step 1  Build the stock's own session bar from its 1m candles: the 09:15 open and the 15:14 close.
  Step 2  Decide after the 15:14 candle completes; nothing from 15:15 onward is read for direction.
  Step 3  15:14 close ABOVE 09:15 open -> BUY, buy a call.  BELOW -> SELL, buy a put.  Equal, or any
          candle missing / invalid -> no trade.
  Step 4  Strike: six LISTED strikes in the money from the at-the-money strike, where at the money is
          the listed strike nearest the stock's 15:20 price.
  Step 5  Expiry: the nearest expiry at least one day after the exit day (stock options: monthly).
  Step 6  Buy in the 15:20 minute at that minute's high.
  Step 7  Line to beat = price paid + round-trip costs per share.
  Step 8  From 09:30 next morning, when a completed minute's LOW is above the line, sell in the next
          minute at its low.  Nothing by 15:14 -> sell in the 15:14 minute at its low.
  Step 9  No stop and no target.

WHAT IS DIFFERENT ON A STOCK OPTION (checked against Upstox on 2026-09-24)
  * Expiries are MONTHLY only (last Tuesday); NIFTY has weekly ones.  "Nearest weekly" becomes the
    nearest monthly at least a day after the exit day.
  * Strikes are NOT evenly spaced (RELIANCE 10 near the money and 20 further out, INFY 20 and 40), so
    "6 strikes ITM" steps through the LISTED strikes (Upstox.listed_strikes), never 6 x one step.
  * Lots are large and differ per stock (RELIANCE 500, HDFCBANK 650, ICICIBANK 700, INFY 400,
    SBIN 750) and are revised by NSE - qty comes from each resolved contract.
  * Charges are the same schedule as index options (the Upstox charges API returns identical
    numbers) - category stock_options -> option_round_trip, dated (STT 0.15% from 2026-04-01).
  * Physical settlement: an ITM stock option held into expiry is delivered.  The expiry rule above
    guarantees the trade is always closed at least a day before it.
  * Deep ITM stock options are THIN: a night whose 15:20 minute (or needed exit minute) has no trade
    is skipped and listed - never filled from another minute (rule 6).

CHECKLIST (RUN.md Step 1)
  1 Underlying        clear    RELIANCE, HDFCBANK, ICICIBANK, INFY, SBIN (each its own signal)
  2 Window            clear    shared START_DATE .. END_DATE
  3 Timeframe         clear    1m
  4 Signal            clear    15:14 close vs 09:15 open of the stock
  5 Decision time     clear    after 15:14; entry 15:20
  6 Direction         clear    up -> buy CE, down -> buy PE
  7 Category          clear    stock_options
  8 Option specifics  clear    buy, 6 listed strikes ITM, monthly expiry >= 1 day after exit, 1 lot
  9 Entry             clear    15:20 bar high
 10 Exit              clear    as index v2 (scan from 09:30, else 15:14); exit alternatives in the panel
 11 Holding           clear    overnight, next session
 12 Costs             clear    category stock_options (broker-read, dated)
 13 Positions         assumed  one per stock per night; the five stocks are separate positions
 14 Missing data      assumed  skip and list
 15 Settings          clear    exit rule sweep (free - the same bars re-read); one report per stock
 16 Groups            assumed  direction
 17 Script name       clear    onh_v3 (stock_options)
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *  # noqa: E402,F401,F403
from py_funcs import IST  # noqa: E402

CATEGORY = "stock_options"
NAME = "onh_v3"
STOCKS = ["HDFCBANK", "ICICIBANK", "INFY", "SBIN"]   # the stocks this version ranked best on - see meta['limits']
SESSION_ROWS = 375
SIGNAL_OPEN, SIGNAL_CLOSE, ENTRY_MIN = "09:15", "15:14", "15:20"
FORCE_EXIT = "15:14"
ITM_STEPS = 6
LOTS = 1
MAX_GAP_DAYS = 5
EXIT_RULES = [
    ("low-0930", "first minute whose LOW clears costs, from 09:30", "09:30", "15:14", "low", 1.0),
    ("low-0916", "first minute whose LOW clears costs, from 09:16", "09:16", "15:14", "low", 1.0),
    ("close-0915", "first CLOSE above costs, from 09:15", "09:15", "15:14", "close", 1.0),
    ("fixed-0930", "09:30 fixed", "09:30", "09:30", "low", None),
    ("fixed-1514", "15:14 fixed - hold the full session", "15:14", "15:14", "low", None),
]
EXIT_BY_KEY = {k: (st, lim, trig, thr) for k, _l, st, lim, trig, thr in EXIT_RULES}
RULE_EXIT = "low-0930"
TV_LIMITS = [0.15, 0.10, 0.05]
RULE_TV = 0.15
YES, NO, NA = "yes", "no", "n/a"
SETTINGS = [
    setting("tv_check", "Time-value check at 15:19", kind="entry", mode="filter", default="15%",
            help="decline the night when time value is more than this share of the 15:19 price; 'off' shows every night",
            options=[{"value": "off", "label": "off - trade every night", "tag": None}]
                    + [{"value": f"{int(v * 100)}%", "label": f"time value at most {int(v * 100)}% of the price"
                        + (" (the rule)" if v == RULE_TV else ""), "tag": {f"tv <= {int(v * 100)}%": [YES]}}
                       for v in TV_LIMITS]),
    setting("exit_rule", "Exit rule", kind="exit", default=RULE_EXIT,
            options=[{"value": k, "label": lab, "raw": k} for k, lab, *_ in EXIT_RULES],
            help="how the next morning is exited; every option re-reads the same bars"),
]


def session_ready(day: str) -> bool:
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


def line_to_beat(entry_px: float, qty: int, day=None) -> float:
    """Entry + round-trip costs per share: solve L = entry + costs(entry, L) / qty."""
    line = entry_px
    for _ in range(50):
        nxt = entry_px + trade_costs(CATEGORY, "LONG", entry_px, line, qty, day) / qty
        if abs(nxt - line) < 1e-9:
            return nxt
        line = nxt
    return line


def signal(rows: list[list]) -> tuple[str | None, str, dict]:
    """(BUY/SELL/None, reason, facts) from one full stock session: the 09:15 bar and the 15:14 bar."""
    if len(rows) != SESSION_ROWS:
        return None, f"stock session has {len(rows)} bars, not {SESSION_ROWS}", {}
    if not valid_bars(rows):
        return None, "invalid stock candle", {}
    by = {r[0]: r for r in rows}
    if SIGNAL_OPEN not in by or SIGNAL_CLOSE not in by or ENTRY_MIN not in by:
        return None, "09:15, 15:14 or 15:20 stock candle missing", {}
    o, c = by[SIGNAL_OPEN][1], by[SIGNAL_CLOSE][4]
    facts = {"open": o, "close": c, "spot_1520": by[ENTRY_MIN][1]}
    if c > o:
        return "BUY", "close above open", facts
    if c < o:
        return "SELL", "close below open", facts
    return None, "15:14 close equals 09:15 open", facts


def simulate(entry_rows: list[list], exit_rows: list[list], qty: int, exit_key: str, day=None) -> dict:
    """Entry: the 15:20 bar (buy at its HIGH).  Exit per `exit_key`: a completed bar that clears the
    line triggers a sale in the NEXT bar at its LOW (rules 2/3); a scheduled exit fills in its own bar."""
    eb = next((r for r in entry_rows if r[0] == ENTRY_MIN), None)
    if eb is None:
        return {"skip": "no trade in the 15:20 option minute (thin deep-ITM contract)"}
    if not valid_bars([eb]):
        return {"skip": "invalid option bar at 15:20"}
    if not exit_rows:
        return {"skip": "no option bars on the exit day"}
    if not valid_bars(exit_rows):
        return {"skip": "invalid option bar on the exit day"}
    line = line_to_beat(eb[2], qty, day)
    by = {r[0]: r for r in exit_rows}
    start, limit, trig, thr = EXIT_BY_KEY[exit_key]
    if thr is None:
        fb = by.get(start)
        if fb is None:
            return {"skip": f"no trade in the {start} option minute (fixed exit)"}
        return {"entry_bar": eb, "exit_bar": fb, "trigger": None, "reason": f"fixed exit {start}", "line": line}
    for r in sorted(exit_rows):
        if r[0] < start:
            continue
        if r[0] >= limit:
            break
        if (r[3] if trig == "low" else r[4]) > line * thr:
            m = hhmm_minutes(r[0]) + 1
            nxt = by.get(f"{m // 60:02d}:{m % 60:02d}")
            if nxt is None:
                return {"skip": f"no trade in the option minute after {r[0]} (needed to act on the signal)"}
            return {"entry_bar": eb, "exit_bar": nxt, "trigger": r, "line": line, "reason": "cleared costs"}
    fb = by.get(FORCE_EXIT)
    if fb is None:
        return {"skip": "no trade in the 15:14 option minute (time exit)"}
    return {"entry_bar": eb, "exit_bar": fb, "trigger": None, "reason": "time exit 15:14", "line": line}


async def run(sym: str, frm: date, to: date, settings: list[dict]) -> None:
    exit_keys = [o["raw"] for o in next(x for x in settings if x["key"] == "exit_rule")["options"]]
    skips: list[tuple[str, str]] = []
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list[list]]] = {}
    lots_seen: dict[str, set] = {}
    today = datetime.now(IST).date()
    async with Upstox() as up:
        for sym in [sym]:
            und = await up.find_instrument(sym, "NSE_EQ")
            key = und["instrument_key"]
            end = min(to + timedelta(days=10), today)
            sessions = sessions_from(await up.candles(key, "1m", frm, end))
            expiries = await up.expiry_calendar(key, frm, end)
            all_days = list(sessions)
            days = [d for d in all_days if frm.isoformat() <= d <= to.isoformat()]
            print(f"{sym}: {key}, {len(days)} sessions, expiries {[e.isoformat() for e in expiries]}")
            checked = False
            for day in days:
                tag0 = f"{sym} {day}"
                if not session_ready(day):
                    skips.append((tag0, "session not complete yet")); continue
                direction, why, f = signal(sessions[day])
                if direction is None:
                    skips.append((tag0, f"no signal: {why}")); continue
                later = [d for d in all_days if d > day]
                if not later:
                    skips.append((tag0, "no exit session available yet")); continue
                xday = later[0]
                if (date.fromisoformat(xday) - date.fromisoformat(day)).days > MAX_GAP_DAYS:
                    skips.append((tag0, f"next session {xday} more than {MAX_GAP_DAYS} days away")); continue
                if not session_ready(xday):
                    skips.append((tag0, f"exit session {xday} not complete yet")); continue
                opt_type = "CE" if direction == "BUY" else "PE"
                exp = next_expiry(expiries, date.fromisoformat(xday), 1)
                if exp is None:
                    skips.append((tag0, "no expiry at least 1 day after the exit day")); continue
                ks = await up.listed_strikes(key, exp, opt_type)
                if not ks:
                    skips.append((tag0, f"no listed strikes for {exp} {opt_type}")); continue
                spot = f["spot_1520"]
                atm = min(range(len(ks)), key=lambda j: abs(ks[j] - spot))
                j = atm - ITM_STEPS if opt_type == "CE" else atm + ITM_STEPS
                if not 0 <= j < len(ks):
                    skips.append((tag0, f"{ITM_STEPS} strikes ITM is not listed for {exp}")); continue
                strike = ks[j]
                c = await up.resolve_option(key, exp, strike, opt_type)
                if c is None:
                    skips.append((tag0, f"contract not found: {exp} {strike:g} {opt_type}")); continue
                qty = LOTS * c["lot_size"]
                if qty <= 0:
                    skips.append((tag0, "contract carries no lot size")); continue
                lots_seen.setdefault(sym, set()).add(c["lot_size"])
                erows = await up.option_candles(c, date.fromisoformat(day))
                xrows = await up.option_candles(c, date.fromisoformat(xday))
                if not checked and erows and not c["expired"]:     # the charges API takes live contracts only
                    print("  " + await broker_check(up, CATEGORY, c["instrument_key"], qty, erows[-1][4]))
                    checked = True
                move_pct = (f["close"] - f["open"]) / f["open"] * 100
                b19 = next((r for r in erows if r[0] == "15:19"), None)
                spot19 = next((r[4] for r in sessions[day] if r[0] == "15:19"), None)
                share = None
                if b19 and spot19 and b19[4] > 0:
                    intr = max(0.0, (spot19 - strike) if opt_type == "CE" else (strike - spot19))
                    share = (b19[4] - intr) / b19[4]
                tv_tags = {f"tv <= {int(v * 100)}%": (NA if share is None else YES if share <= v else NO) for v in TV_LIMITS}
                tv_tags["time value share"] = ("n/a" if share is None else "<=5%" if share <= .05 else "5-10%" if share <= .10
                                               else "10-15%" if share <= .15 else "15-30%" if share <= .30 else ">30%")
                for ex_key in exit_keys:
                    sim = simulate(erows, xrows, qty, ex_key, day=day)
                    if "skip" in sim:
                        skips.append((f"{tag0} {ex_key}", f"{c['trading_symbol']}: {sim['skip']}")); continue
                    eb, xb = sim["entry_bar"], sim["exit_bar"]
                    entry_px, exit_px = worst_fills("LONG", eb, xb)
                    m1, a1 = excursion(erows, "LONG", entry_px, ENTRY_MIN, "15:29")
                    m2, a2 = excursion(xrows, "LONG", entry_px, "09:15", xb[0])
                    trades.append(make_trade(
                        day=day, exit_day=xday, side="LONG", symbol=c["trading_symbol"],
                        entry_time=eb[0], entry_px=entry_px, exit_time=xb[0], exit_px=exit_px, qty=qty,
                        exit_reason=sim["reason"], kind="option", capital=entry_px * qty,
                        entry_spot=spot, mfe=max(m1, m2), mae=min(a1, a2),
                        option_type=opt_type, expiry=c["expiry"],
                        variant={"exit_rule": ex_key},
                        tags={"direction": direction, **tv_tags},
                        note=(f"{sym} {direction}: 15:14 close {f['close']:.2f} vs 09:15 open {f['open']:.2f} "
                              f"({move_pct:+.2f}%); strike {strike:g} = {ITM_STEPS} listed strikes ITM from "
                              f"{ks[atm]:g} (15:20 price {spot:.2f}); line {sim['line']:.2f}; exit {ex_key}")))
                osess = option_sessions.setdefault(c["trading_symbol"], {})
                osess[day], osess[xday] = erows, xrows
            print(f"  {sym}: {sum(1 for t in trades if t['variant']['exit_rule'] == RULE_EXIT)} rule trades; "
                  f"lot sizes {sorted(lots_seen.get(sym, []))}")

    print(f"\nSkipped {len(skips)}:")
    for d, why in skips:
        print(f"  {d}: {why}")
    rule_skips = [s for s in skips if not any(k in s[0] for k, *_ in EXIT_RULES) or RULE_EXIT in s[0]]
    meta = {
        "title": f"Overnight Hold v3 - {sym} options (v2 + time-value check)",
        "subtitle": f"{sym}: only when time value <= 15% of the 15:19 price - buy a call (15:14 close above the 09:15 open) or a put (below) at 15:20, six listed "
                    "strikes in the money; sell next morning the first minute after 09:30 that clears costs, else 15:14",
        "instrument": f"{sym} (stock; its monthly options are what is bought)",
        "category": CATEGORY,
        "from": frm.isoformat(), "to": to.isoformat(),
        "lot_size": sorted(lots_seen.get(sym, [])),
        "fill_rule": "Every buy at the bar's high, every sell at the bar's low; a signal from a completed minute is "
                     "acted on in the next minute; the 15:14 time exit fills in its own bar.",
        "params": {"signal": "stock 15:14 close vs 09:15 open", "strike": f"{ITM_STEPS} LISTED strikes ITM",
                   "entry": f"{ENTRY_MIN} bar high", "exit": RULE_EXIT, "time-value check": "<= 15% at 15:19", "expiry": "nearest monthly >= 1 day after exit day",
                   "lots": LOTS, "stock": sym},
        "rule_steps": [
            f"Take {sym}'s 09:15 open and 15:14 close (complete 1m candles only).",
            "Close above open = BUY (buy a call); below = SELL (buy a put); equal or bad data = no trade.",
            f"At the money = the listed strike nearest the stock's 15:20 price; move {ITM_STEPS} LISTED strikes in the money.",
            "Expiry = the nearest (monthly) expiry at least one day after the exit day - never held into expiry (physical settlement).",
            "At 15:19 read the contract's price; time value = price - intrinsic (strike vs the stock's 15:19 close). More than 15% of the price -> no trade tonight.",
            "Otherwise buy in the 15:20 minute at that minute's high.",
            "Line to beat = price paid + round-trip costs per share.",
            "From 09:30 next morning, when a completed minute's low is above the line, sell in the next minute at its low.",
            "If nothing qualifies before 15:14, sell in the 15:14 minute at its low.",
            "No stop and no target."],
        "limits": [
            "Rule carried over from the NIFTY onh_v3 unchanged (time-value limit 15%, set on NIFTY); its 6-strike depth, 15:20 entry and 09:30 scan were chosen on NIFTY data, not on these stocks.",
            "Stock options are monthly, unevenly strike-spaced and thin in the money: a night with no trade in a needed minute is skipped (listed on the console).",
            f"Skipped nights for the rule's exit: {len(rule_skips)} (all exits: {len(skips)}).",
            "HDFCBANK, ICICIBANK, INFY and SBIN: of v1/v2/v3 on Jan-Sep 2026, v3 ranked best for each (win rate, then trades, then profit factor); RELIANCE runs v2 (onh_v2.py).",
            f"One report per stock; the same script writes onh_v3_<stock>.html for {', '.join(STOCKS)}.",
            "Capital = premium paid x qty (bought options).",
        ],
        "rejected": [
            ["Strike depth ladder (0..8 ITM)", "each rung is a separate fetch of thin monthly contracts; the rule's "
             "6 listed strikes is the only rung priced.  Deeper rungs skip even more nights for lack of trades."],
            ["Entry minute", "fixed at 15:20 by the rule; 15:29 (v1's minute) is the widest of the afternoon."],
            ["Timeframe", "the rule reads two 1-minute bars (09:15 open, 15:14 close); there is no other timeframe."],
            ["Direction filter", "both sides are always traded; direction is a group-by, not a filter."],
        ],
    }
    meta["coverage"] = coverage({d: r for d, r in sessions.items() if frm.isoformat() <= d <= to.isoformat()}, frm, to, SESSION_ROWS)
    groups = [{"name": "direction (BUY call / SELL put)", "keys": ["direction"]},
              {"name": "time-value share at 15:19", "keys": ["time value share"]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups, settings=settings, chart="all")
    path = write_report(payload, f"{NAME}_{sym.lower().replace('-', '_').replace('&', '')}")
    print(console_summary([t for t in trades if t["variant"]["exit_rule"] == RULE_EXIT]))
    print(path)


def main() -> None:
    ap = argparse.ArgumentParser(description="Overnight Hold v3 on stock options")
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat())
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    ap.add_argument("--stock", default="all", help=f"one of {STOCKS}, or all (default): one report per stock")
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    settings = narrow(SETTINGS, a)
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    check_window(frm, to)
    for sym in (STOCKS if a.stock == "all" else [a.stock.upper()]):
        asyncio.run(run(sym, frm, to, settings))


if __name__ == "__main__":
    main()
