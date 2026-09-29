"""Panic Buy - v1 (panic_buy_v1).  Cash equity, intraday MIS, the 50 NIFTY-50 stocks.  BUY side only.

THE USER'S PROMPTS (2026-09-29): "think in the out of the box, a simple way can give the best strategy?
thinking is yours now" - then, after the study below: "now make a panic buy strategy as separate version".
Late Gap Fill v4 stays as it is; this is a separate strategy.

WHERE IT COMES FROM (scratchpad study s36-s39, the user's one year 2025-09-29..2026-09-25, worst prices)
  * One share at the worst price costs about 0.35-0.4% of the price a round trip (0.27% charges + candle
    width), so only trades that catch BIG moves can win.  The big, repeatable intraday move is the market-wide
    shock that snaps back - the idea behind Late Gap Fill.
  * Measuring the stretch AT THE SIGNAL (gap + morning fall together, not the gap alone) and splitting by side:
    the edge is almost all on the BUY side.  Panic selling overshoots and is bought back the same day; a
    market-wide rally does not reverse the same way (the sell mirror lost 0.19% a trade after 1-share costs;
    even v4's own sell trades were about break-even after costs).
  * Values: the stock's stretch of 0.8x its daily range held for every market level from 0.6% to 1.0% (all
    positive in both halves).  The market level was picked on the FIRST half only - the lowest that still gives
    120+ trades - which is 0.7%; the second half then confirmed it.
  Study result: 131 trades, 67.9% winners, +0.54% of the price a trade before costs, +0.263% after the costs of
  one share (first half +0.28%, second half +0.25%).

THE HONEST WEAK POINT (day-level check, study): 27 trading days, only 12 made money, the median day lost 0.88%.
9 Mar 2026 alone (29 trades) made +26% of the +34.5% total; without the best 5 days it loses 0.32% a trade.
No trades before Feb 2026.  It is a bet on a few crash-rebound days a year - and the user keeps every study to
one year, which holds only one or two of them.  Treat it as promising, not proven.

HIGHER-TIMEFRAME ENTRY (the user, 2026-09-29: "use the higher time frames for the directions ... to increase the
win rates and profit points and avoid the high losing trades" - for the ENTRY only; every fill stays on the
1-minute candle at its worst price).  Scratchpad s42-s44, the same year:
  * Signal candle: a 5-minute candle closing back above VWAP beats a single 1-minute candle (111 trades, 68.5%
    winners, +0.34% a trade after 1-share costs, vs 131 / 67.9% / +0.26%); 15-minute was no better than 5.
  * Daily chart: buys in stocks ALREADY BELOW their 20-day average (the daily chart already weak) won 70.5%,
    +0.43% after costs, both halves; stocks above it made nothing (61%, +0.00%).  The panic finishes a move the
    daily chart had started - the snap-back is strongest at the extreme.
  * The first hourly candle (09:15-10:15) closing in its LOWER half (the panic still on at 10:15) helps too.
  * Both together: 54 trades, 74.1% winners, +0.87% of the price a trade before costs, +0.60% after
    the costs of one share (first half +0.45%, second +0.83%); losers of 1% or more 9 -> 5; days that made money
    14 of 20 (was 11 of 24); without the best 5 days -0.16% a trade (was -0.28%).
  * BUT the user's minimum is 120 trades a year ("min of 120 trades in a year", 2026-09-29), and 54 is far below it.
    A search over every setting with 120+ trades (market fall 0.4-0.7%, stock fall 0.5-0.8x, 1m / 5m candle,
    signals to 11:30 / 12:00 / 12:30, each check; s45) found none that beats the plain rule when picked on the
    first half: the best first-half pick fell to +0.14% a trade in the second half.  Panic Buy is already
    selective - the checks mostly cut good trades.  So the RULE stays plain (131 trades) and the checks are
    settings, to show the trade-off.
  * Not used: 5-minute RSI, 15-minute higher lows, NIFTY's own 15-minute low, NIFTY's daily trend, daily RSI - no
    clean split in both halves.

USER DECISIONS (all standing)
  - Worst price only, entry and exit (2026-09-28, permanent for intraday stocks).  No pre-open price, no
    candle-close comparison (build_payload refuses anything else).
  - One share a trade, no lots, no leverage.  Points per share, never bps; plain words.
  - Window: the user's one year, from 2025-09-29; studies stay inside it.

THE RULE
  1 Every minute from 10:30 to 11:30, NIFTY at least 0.7% below yesterday's official close.
  2 The stock at least 0.8 x its average daily range of the last 14 days (ATR14) below yesterday's close,
    and it has NOT touched yesterday's close since 09:15.
  3 Skip results days 1-2 and ex-dividend days.
  4 Signal: the first completed minute, with 1-2 true, that closes ABOVE the day's VWAP.
  5 Buy 1 share in the next 1-minute candle at its HIGH.
  6 Target 0.25 x ATR14 above yesterday's close; stop 0.75 x ATR14 below the day's low up to the signal.  A
    minute touching either exits in the next minute at its LOW (the stop first if both).  Else sell in the
    15:14 minute at its LOW.
  7 Never sell short.  Each stock is its own trade (several can be open on the same day).

CHECKLIST (RUN.md Step 1)
  1 Underlying clear   the 50 NIFTY-50 stocks (NSE list read 2026-09-28)     9 Entry clear  see 4-5
  2 Window     clear   2025-09-29..END_DATE, the user's one year             10 Exit clear  see 6
  3 Timeframe  clear   daily facts + 1-minute candles (VWAP from 1-min)       11 Holding clear intraday
  4 Signal     clear   see 1-4                                                12 Costs clear category
  5 Decision   clear   the close of the signal minute                         13 Positions clear one per stock/day
  6 Direction  clear   buy only                                              14 Missing data assumed skip+log
  7 Instrument clear   cash equity, MIS                                      14b declined = a signal the rule's
  8 Options    n/a                                                               filters refuse; no signal = the
                                                                                 market or no stock was down enough
ASSUMED
  A1 VWAP = cumulative (typical price x volume) / cumulative volume from 09:15, using completed minutes.
  A2 NIFTY's level at a minute = that minute's close (the index is not traded; it only gates the day).
  A3 The universe is the index as listed on 2026-09-28, read back over the year (survivorship).
  A4 TMPV is skipped 2025-10-14..2025-11-04 (the Tata Motors demerger makes its prices jump).
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *          # noqa: F401,F403
import argparse

CATEGORY = "stock_intraday"
SLUG = "panic_buy_v1"
STUDY_FROM = date(2025, 9, 29)
SPLIT = "2026-04-01"
ROWS = 375
ATR_N = 14
WARMUP_DAYS = 45
SCAN_FROM, SCAN_TO = "10:29", "11:59"         # signal minutes scanned (the rule uses 10:29..11:29, entry 10:30..11:30)
SKIP = {"TMPV": ("2025-10-14", "2025-11-04")}  # corporate action (A4)
QTY = 1                                        # one share a trade - no lots, no leverage (the user, 2026-09-28)

UNIVERSE = {s: sec for sec, ss in {
    "Auto": ["BAJAJ-AUTO", "EICHERMOT", "M&M", "MARUTI", "TMPV"],
    "Capital Goods": ["BEL"], "Cement": ["GRASIM", "ULTRACEMCO"], "Construction": ["LT"],
    "Consumer Durables": ["ASIANPAINT", "TITAN"], "Consumer Services": ["ETERNAL", "TRENT"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "TATACONSUM"],
    "Financial Services": ["AXISBANK", "BAJFINANCE", "BAJAJFINSV", "HDFCBANK", "HDFCLIFE", "ICICIBANK", "JIOFIN",
                           "KOTAKBANK", "SBILIFE", "SHRIRAMFIN", "SBIN"],
    "Healthcare": ["APOLLOHOSP", "CIPLA", "DRREDDY", "MAXHEALTH", "SUNPHARMA"],
    "IT": ["HCLTECH", "INFY", "TCS", "TECHM", "WIPRO"],
    "Metals & Mining": ["ADANIENT", "HINDALCO", "JSWSTEEL", "TATASTEEL"],
    "Oil & Gas": ["COALINDIA", "ONGC", "RELIANCE"], "Power": ["NTPC", "POWERGRID"],
    "Services": ["ADANIPORTS", "INDIGO"], "Telecom": ["BHARTIARTL"],
}.items() for s in ss}

BUY, SELL = "buy the market-wide fall back up", "sell the market-wide rise back down (the mirror)"
T_TIME, T_EVENT = "signal time", "results & dividend days"
T_STRETCH, T_NIFTY, T_HOW = ("stock's distance from yesterday's close at the signal", "NIFTY's move at the signal",
                             "how the stock got there")
TIME_LABELS = ["10:30-11:00", "11:00-11:30", "11:30-12:00"]
STRETCH_LABELS = ["0.6 to 0.8x", "0.8 to 1x", "1 to 1.5x", "1.5x or more"]
NIFTY_LABELS = ["0.5 to 0.7%", "0.7 to 1%", "1 to 1.5%", "1.5% or more"]
HOW_LABELS = ["mostly the opening gap", "mostly the move after the open"]
T_DAILY, T_HOUR, T_HTF = "daily chart before today", "first hour (09:15-10:15)", "bigger-timeframe check"
DAILY_LABELS = ["already stretched (buy: below its 20-day average)", "not stretched (buy: above its 20-day average)",
                "unknown (under 20 days of history)"]
HOUR_LABELS = ["closed in its worse half (buy: the panic still on)", "closed in its better half (buy: already bouncing)"]
HTF_LABELS = ["both", "daily chart only", "first hour only", "neither"]
NO_EVENT = "normal day"
SMA_N = 20
# exit key: (label, target above yesterday's close in x ATR14 or None, time exit, stop below the day's low in x ATR14 or None)
EXITS = {"ext075": ("stop 0.75x below the day's low, target 0.25x above yesterday's close, else 15:14", 0.25, "15:14", 0.75),
         "hold1514": ("no target, no stop, sell at 15:14", None, "15:14", None)}

SETTINGS = [
    setting("market", "Market fall (NIFTY)", kind="entry", default="0.7",
            help="how far NIFTY must be below yesterday's close at the signal (above it, for the mirror)",
            options=[{"value": "0.5", "raw": 0.5, "label": "0.5% or more"},
                     {"value": "0.7", "raw": 0.7, "label": "0.7% or more"}]),
    setting("stretch", "Stock's fall", kind="entry", default="0.8",
            help="how far the stock must be below yesterday's close at the signal, in x its average daily range",
            options=[{"value": "0.6", "raw": 0.6, "label": "0.6x its daily range or more"},
                     {"value": "0.8", "raw": 0.8, "label": "0.8x its daily range or more"}]),
    setting("trigger", "Signal candle", kind="entry", default="1",
            help="the candle whose close must be back above VWAP; the buy is always filled on the NEXT 1-minute candle "
                 "at its high",
            options=[{"value": "1", "raw": 1, "label": "1-minute candle"},
                     {"value": "5", "raw": 5, "label": "5-minute candle"}]),
    setting("htf", "Bigger-timeframe check", kind="entry", mode="filter", default="off",
            help="daily chart = yesterday's close below the stock's 20-day average (above, for the mirror); first hour = "
                 "the 09:15-10:15 candle closed in its lower half (upper half, for the mirror)",
            options=[{"value": "and", "label": "both: weak daily chart AND first-hour panic (74% winners, ~55 trades)", "tag": {T_HTF: HTF_LABELS[:1]}},
                     {"value": "daily", "label": "the daily chart only", "tag": {T_HTF: HTF_LABELS[:2]}},
                     {"value": "hour", "label": "the first hour only", "tag": {T_HTF: [HTF_LABELS[0], HTF_LABELS[2]]}},
                     {"value": "or", "label": "either one", "tag": {T_HTF: HTF_LABELS[:3]}},
                     {"value": "off", "label": "off (the rule - keeps 120+ trades)", "tag": None}]),
    setting("side", "Which side", kind="entry", mode="filter", default="buy",
            help="the mirror sells a stock that ran up with a market-wide rally - it lost in the study",
            options=[{"value": "buy", "label": "buy the fall only (the rule)", "tag": {"direction": [BUY]}},
                     {"value": "both", "label": "both - also sell the rally", "tag": None}]),
    setting("window", "Signal between", kind="entry", mode="filter", default="1130",
            help="the first minute that turns back above VWAP must close in this window",
            options=[{"value": "1130", "label": "10:30 and 11:30", "tag": {T_TIME: TIME_LABELS[:2]}},
                     {"value": "1200", "label": "10:30 and 12:00", "tag": {T_TIME: TIME_LABELS}}]),
    setting("events", "Results & dividend days", kind="entry", mode="filter", default="skip",
            help="the first two days after quarterly results, and ex-dividend days (from NSE)",
            options=[{"value": "skip", "label": "skip them", "tag": {T_EVENT: [NO_EVENT, "unknown (NSE not reachable)"]}},
                     {"value": "trade", "label": "trade them too", "tag": None}]),
    setting("exit", "Stop-loss and target", kind="exit", default="ext075",
            options=[{"value": k, "label": v[0]} for k, v in EXITS.items()],
            help="the day's low = the lowest price from 09:15 to the signal (the high, for the mirror); every exit is at "
                 "the worst price of its minute; a stop or target touched in one minute exits in the next (the stop first)"),
]


# ---------------------------------------------------------------------------
# signal (pure, completed candles only)
# ---------------------------------------------------------------------------
def atr14(daily: dict, ddays: list[str], k: int) -> float:
    trs = []
    for j in range(k - ATR_N, k):
        h, l, pc = daily[ddays[j]]["high"], daily[ddays[j]]["low"], daily[ddays[j - 1]]["close"]
        trs.append(max(h, pc) - min(l, pc))
    return sum(trs) / ATR_N


def find_signal(rows: list[list], side: int, pc: float, atr: float, nclose: dict, npc: float,
                market: float, stretch: float, tf: int = 1) -> dict:
    """Walk the day's minutes.  side +1 = buy a fall, -1 = the mirror.  Stop at the first touch of yesterday's
    close; else return the first tf-minute candle close (candles aligned to 09:15) in SCAN_FROM..SCAN_TO where
    NIFTY is `market`% and the stock `stretch` x ATR14 away from yesterday's close (the side's way) and the close
    is back across VWAP.  rows must be the full 375-minute session (index = minutes since 09:15)."""
    cum_pv = cum_v = 0.0
    for i, r in enumerate(rows):
        t, o, h, l, c, v = r
        cum_pv += (h + l + c) / 3 * v
        cum_v += v
        if (side > 0 and h >= pc) or (side < 0 and l <= pc):
            return {"why": f"it touched yesterday's close at {t}"}
        if t > SCAN_TO:
            break
        if t < SCAN_FROM or cum_v <= 0 or t not in nclose or (i + 1) % tf:
            continue
        mkt = (1 - nclose[t] / npc) * 100 * side      # % NIFTY is away from yesterday's close, the side's way
        st = (pc - c) * side / atr
        if mkt < market or st < stretch:
            continue
        vw = cum_pv / cum_v
        if (c - vw) * side > 0:
            return {"k": i, "time": t, "close": c, "vwap": vw, "stretch": st, "market": mkt}
    return {"why": f"no minute qualified and turned across VWAP by {SCAN_TO}"}


def signal_bucket(t: str) -> str:
    return TIME_LABELS[0] if t <= "10:59" else (TIME_LABELS[1] if t <= "11:29" else TIME_LABELS[2])


def daily_stretched(daily: dict, ddays: list[str], k: int, side: int) -> str:
    """Yesterday's close against the average of the last 20 closes up to yesterday: below it = stretched for a buy."""
    if k < SMA_N:
        return DAILY_LABELS[2]
    closes = [daily[x]["close"] for x in ddays[k - SMA_N:k]]
    return DAILY_LABELS[0] if (closes[-1] - sum(closes) / SMA_N) * side < 0 else DAILY_LABELS[1]


def first_hour(rows: list[list], side: int) -> str:
    """Where the 09:15-10:15 candle closed in its own range: the lower half = worse for a buy."""
    h1 = rows[:60]
    hi, lo, cl = max(r[2] for r in h1), min(r[3] for r in h1), h1[-1][4]
    pos = 0.5 if hi <= lo else ((cl - lo) / (hi - lo) if side > 0 else (hi - cl) / (hi - lo))
    return HOUR_LABELS[0] if pos < 0.5 else HOUR_LABELS[1]


def htf_tag(daily_tag: str, hour_tag: str) -> str:
    dly, hr = daily_tag == DAILY_LABELS[0], hour_tag == HOUR_LABELS[0]
    return HTF_LABELS[0] if dly and hr else HTF_LABELS[1] if dly else HTF_LABELS[2] if hr else HTF_LABELS[3]


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
async def run(frm: date, to: date, settings: list[dict]):
    warm = frm - timedelta(days=WARMUP_DAYS)
    trades, log, skips = [], [], []
    rule = default_combo(settings)
    rule_f = {s["key"]: next(o for o in s["options"] if o["value"] == s["default"]) for s in settings if s["mode"] == "filter"}
    now = datetime.now(IST)
    all_c = combos(settings)
    async with Upstox() as up:
        keys = {s: (await up.find_instrument(s, "NSE_EQ"))["instrument_key"] for s in UNIVERSE}
        nkey = (await up.find_instrument("NIFTY"))["instrument_key"]
        print(fetch_estimate(14 * len(keys) + 2 * len(keys)) + " before the cache fills")
        nd = {c["timestamp"][:10]: c for c in await up.candles(nkey, "1d", warm, to)}
        nmin = await up.minute_sessions(nkey, frm, to)
        daily, mins, events, ev_state = {}, {}, {}, {}
        for s, k in keys.items():
            daily[s] = {c["timestamp"][:10]: c for c in await up.candles(k, "1d", warm, to)}
            mins[s] = await up.minute_sessions(k, frm, to, volume=True)
            stamps = await nse_results_stamps(s, warm, to)
            exdiv = await nse_exdividend_days(s, warm, to)
            ev = results_reaction_days(stamps, sorted(daily[s])) if stamps is not None else {}
            for x in (exdiv or set()):
                ev.setdefault(x, "ex-dividend day")
            events[s], ev_state[s] = ev, (stamps is not None and exdiv is not None)
        last = max(daily["RELIANCE"])
        check = await broker_check(up, CATEGORY, keys["RELIANCE"], QTY, daily["RELIANCE"][last]["close"])
        print(check)
        idays = sorted(nd)
        window = [d for d in idays if frm.isoformat() <= d <= to.isoformat()
                  and not (d == now.date().isoformat() and now.strftime("%H:%M") < "15:45")]
        dsorted = {s: sorted(daily[s]) for s in UNIVERSE}
        for d in window:
            nrows = nmin.get(d)
            i = idays.index(d)
            npc = nd[idays[i - 1]]["close"] if i > 0 else None
            facts = {"NIFTY gap %": None if not nrows or npc is None else (nrows[0][1] / npc - 1) * 100}
            if not nrows or len(nrows) != ROWS or npc is None:
                log.append(session_row(d, "no data", "NIFTY's candles for the day are incomplete (a special or short "
                                                     "session) - not traded", **facts))
                skips.append(f"{d}: NIFTY session incomplete")
                continue
            nclose = {r[0]: r[4] for r in nrows}
            upto = [r for r in nrows if r[0] <= "11:29"]
            facts["NIFTY lowest by 11:30 %"] = (min(r[3] for r in upto) / npc - 1) * 100
            facts["NIFTY highest by 11:30 %"] = (max(r[2] for r in upto) / npc - 1) * 100
            day_trades, refused, bad = [], [], []
            for s, sector in UNIVERSE.items():
                if s in SKIP and SKIP[s][0] <= d <= SKIP[s][1]:
                    continue
                rows = mins[s].get(d)
                dd, ddays = daily[s], dsorted[s]
                if not rows or len(rows) != ROWS or d not in dd:
                    bad.append(s)
                    skips.append(f"{d} {s}: {0 if not rows else len(rows)} of {ROWS} one-minute candles")
                    continue
                k = ddays.index(d)
                if k < ATR_N + 1 or ddays[k - 1] != idays[i - 1]:
                    bad.append(s)
                    skips.append(f"{d} {s}: not enough earlier days, or a gap in its daily data")
                    continue
                prev = dd[ddays[k - 1]]
                pc = prev["close"]
                o = rows[0][1]
                atr = atr14(dd, ddays, k)
                ev = events[s].get(d, NO_EVENT) if ev_state[s] else "unknown (NSE not reachable)"
                for side in (1, -1):
                    side_s = "LONG" if side > 0 else "SHORT"
                    d_tag, h_tag = daily_stretched(dd, ddays, k, side), first_hour(rows, side)
                    sigs, seen = {}, None
                    for c in all_c:
                        key = (c["market"], c["stretch"], c["trigger"])
                        if key not in sigs:
                            sigs[key] = find_signal(rows, side, pc, atr, nclose, npc, c["market"], c["stretch"], c["trigger"])
                        sig = sigs[key]
                        if "k" not in sig:
                            continue
                        if sig["k"] + 1 >= len(rows):
                            skips.append(f"{d} {s}: no candle after the signal")
                            continue
                        upto_s = rows[:sig["k"] + 1]                        # completed minutes up to the signal
                        extreme = min(r[3] for r in upto_s) if side > 0 else max(r[2] for r in upto_s)
                        gap_part = (pc - o) * side / atr
                        tags = {"direction": BUY if side > 0 else SELL, "stock": s, "sector": sector,
                                T_TIME: signal_bucket(sig["time"]), T_EVENT: ev,
                                T_STRETCH: bucket(sig["stretch"], [0.8, 1.0, 1.5], STRETCH_LABELS),
                                T_NIFTY: bucket(sig["market"], [0.7, 1.0, 1.5], NIFTY_LABELS),
                                T_HOW: HOW_LABELS[0] if gap_part >= 0.5 * sig["stretch"] else HOW_LABELS[1],
                                T_DAILY: d_tag, T_HOUR: h_tag, T_HTF: htf_tag(d_tag, h_tag),
                                "period": "Sep 2025 - Mar 2026 (rule picked here)" if d < SPLIT else "Apr - Sep 2026 (new data)"}
                        entry = rows[sig["k"] + 1]
                        e_px = entry[2] if side > 0 else entry[3]             # worst price of the next minute
                        label, past, x_time, stop_x = EXITS[c["exit"]]
                        tgt = None if past is None else pc + side * past * atr
                        stop = None if stop_x is None else extreme - side * stop_x * atr
                        ex = scan_exit(rows, side_s, entry[0], stop=stop, target=tgt, force_key=x_time)
                        if ex["bar"] is None:
                            skips.append(f"{d} {s} {c}: {ex['reason']}")
                            continue
                        xb = ex["bar"]
                        x_px = xb[3] if side > 0 else xb[2]
                        reason = {"target": "target reached", "stop": "stop-loss",
                                  "time exit": f"{x_time} time exit"}.get(ex["reason"], ex["reason"])
                        mfe, mae = excursion(rows, side_s, e_px, rows[min(sig["k"] + 2, len(rows) - 1)][0], xb[0])
                        t = make_trade(
                            day=d, side=side_s, symbol=s, kind="equity", entry_time=entry[0], entry_px=e_px,
                            exit_time=xb[0], exit_px=x_px, qty=QTY, exit_reason=reason,
                            target=None if tgt is None else round(tgt, 2), stop=None if stop is None else round(stop, 2),
                            mfe=mfe, mae=mae, variant=c, tags=tags,
                            levels=[{"name": "yesterday's close", "price": pc},
                                    {"name": "the day's low so far" if side > 0 else "the day's high so far",
                                     "price": round(extreme, 2)},
                                    {"name": "today's open", "price": o},
                                    {"name": "VWAP at the signal", "price": round(sig["vwap"], 2)}],
                            note=f"at the close of the {c['trigger']}-minute candle whose last minute is {sig['time']}, NIFTY was "
                                 f"{sig['market']:.2f}% {'below' if side > 0 else 'above'} yesterday's close and the stock "
                                 f"{sig['stretch']:.2f}x its average daily range ({atr / pc * 100:.2f}%) "
                                 f"{'below' if side > 0 else 'above'} its own; it closed {sig['close']:.2f}, back across "
                                 f"VWAP {sig['vwap']:.2f}; daily chart: {d_tag}; first hour: {h_tag}; 1 share")
                        trades.append(t)
                        if c == rule:
                            seen = t
                    if seen is None:
                        continue
                    no = [f"{st['label'].lower()}: {', '.join(str(seen['tags'].get(k2)) for k2 in o_['tag'])}"
                          for st in settings if st["mode"] == "filter"
                          for o_ in [rule_f[st["key"]]] if o_.get("tag")
                          and not all(str(seen["tags"].get(k2)) in [str(v) for v in vals] for k2, vals in o_["tag"].items())]
                    (refused if no else day_trades).append((s, no))
            facts.update({"trades (rule)": len(day_trades), "stocks traded (rule)": ", ".join(s for s, _ in day_trades) or "-"})
            tail = f"; no usable data for {', '.join(bad)}" if bad else ""
            if day_trades:
                log.append(session_row(d, "traded", f"{len(day_trades)} trade(s) under the rule" + tail, **facts))
            elif refused:
                why = "; ".join(f"{s} ({', '.join(n)})" for s, n in refused[:6])
                log.append(session_row(d, "declined", f"a stock qualified and turned, but the rule's filters said no - "
                                       f"{why}. Switch the filter off in the settings to count it" + tail, **facts))
            else:
                low = facts["NIFTY lowest by 11:30 %"]
                log.append(session_row(d, "no signal", (f"NIFTY was never 0.7% below yesterday's close by 11:30 (lowest "
                                                        f"{low:+.2f}%)" if low > -0.7 else
                                                        "NIFTY fell 0.7%+, but no stock was 0.8x its range down, "
                                                        "untouched, and turned above VWAP by 11:30")
                                       + tail, **facts))
        calls = up.calls
    return trades, log, skips, nmin, mins, check, ev_state, calls


def day_check(ts: list[dict]) -> str:
    """The day-level check: how many days made money, the median day, and the result without the best 5 days."""
    if not ts:
        return "no trades"
    days: dict[str, float] = {}
    for t in ts:
        days[t["day"]] = days.get(t["day"], 0.0) + t["pts"] / t["entry_px"] * 100
    v = sorted(days.values())
    best = sorted(days, key=lambda x: -days[x])[:5]
    rest = [t["pts"] / t["entry_px"] * 100 for t in ts if t["day"] not in best]
    top = max(days, key=lambda x: days[x])
    return (f"{len(v)} days, {sum(x > 0 for x in v)} made money, median day {v[len(v) // 2]:+.2f}% of the price summed; "
            f"best day {top} {days[top]:+.1f}% of {sum(v):+.1f}% total; without the best 5 days "
            f"{(sum(rest) / len(rest)) if rest else float('nan'):+.3f}% a trade (before costs)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default=STUDY_FROM.isoformat(),
                    help=f"first day; the user's one-year window starts {STUDY_FROM}")
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    settings = narrow(SETTINGS, a)
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to)
    check_window(frm, to, max_days=max(366, (END_DATE - STUDY_FROM).days))
    trades, log, skips, nmin, mins, check, ev_state, calls = asyncio.run(run(frm, to, settings))
    print(f"\n{len(skips)} skips:")
    for s in skips[:60]:
        print("  " + s)
    if len(skips) > 60:
        print(f"  ... {len(skips) - 60} more")
    ev_bad = [s for s, ok_ in ev_state.items() if not ok_]
    rule = default_combo(settings)
    fopts = [next(o for o in s["options"] if o["value"] == s["default"]) for s in settings if s["mode"] == "filter"]
    ruled = [t for t in trades if all(t["variant"].get(k) == str(v) for k, v in rule.items())
             and all(not o.get("tag") or all(t["tags"].get(k) in v for k, v in o["tag"].items()) for o in fopts)]
    dcheck = day_check(ruled)
    meta = {
        "title": "Panic Buy v1",
        "subtitle": "When the whole market is sold hard in the morning, buy the NIFTY-50 stocks that were sold the most as "
                    "soon as each turns back above its VWAP; exact stop below the day's low, target a little above "
                    "yesterday's close, else sell at 15:14. Buy side only, cash equity, intraday (MIS), worst prices, "
                    "one share, in points per share.",
        "instrument": f"{len(UNIVERSE)} NIFTY-50 stocks - cash equity (NSE), intraday MIS",
        "index_label": "NIFTY 50",
        "from": frm.isoformat(), "to": to.isoformat(), "category": CATEGORY,
        "fill_rule": "Worst price only: a buy fills at the HIGH of the minute after the signal minute; it is sold at the "
                     "LOW of the minute after the target or stop is touched; the time exit fills in its own minute at its LOW",
        "params": {"the rule": "between 10:30 and 11:30, NIFTY at least 0.7% below yesterday's close and the stock at least "
                               "0.8x its average daily range below its own, not yet back at yesterday's close; the first "
                               "such minute that closes above VWAP; buy 1 share the next 1-minute candle at its high; target 0.25x "
                               "the range above yesterday's close; stop 0.75x the range below the day's low; else 15:14; "
                               "skip results and dividend days; never sell short",
                   "average daily range (ATR14)": "the average of the last 14 days' high-to-low range, counting the gap "
                                                  "from the day before",
                   "VWAP": "cumulative (typical price x volume) / cumulative volume from 09:15, completed minutes",
                   "NIFTY's level": "the close of the same minute, against NIFTY's official close yesterday",
                   "size": "1 share per trade, at the stock's full price - no lots, no leverage",
                   "day": "09:15-15:29 in 375 one-minute candles",
                   "window": f"{frm} .. {to} (the user's one-year window)"},
        "rule_steps": [
            "Watch NIFTY every minute from 10:30 to 11:30. The day qualifies only while NIFTY is at least 0.7% BELOW "
            "yesterday's close - the whole market is being sold.",
            "On such a day, look at every NIFTY-50 stock. It qualifies while it is at least 0.8 times its average daily "
            "range (ATR14) below its own close of yesterday, and has not been back up to that close since 09:15. "
            "Example: closed at Rs 1,000 yesterday, moves about Rs 20 a day - it qualifies at Rs 984 or lower.",
            "Skip the first two days after the company's quarterly results, and its ex-dividend day.",
            "The signal is the first minute, while both qualify, that closes ABOVE the day's VWAP - buyers have taken "
            "over from the panic.",
            "Buy ONE share in the next 1-MINUTE candle at its HIGH (the worst price). Every fill in this strategy is on the "
            "1-minute candle.",
            "Target = 0.25 times the daily range ABOVE yesterday's close. In the example: Rs 1,005. A minute that touches "
            "it: sell in the next minute at its LOW.",
            "Stop-loss = the day's lowest price up to the signal, minus 0.75 times the daily range. Example: today's low "
            "Rs 975 - stop Rs 960. A minute that touches it: sell in the next minute at its LOW.",
            "Neither touched: sell in the 15:14 minute at its LOW.",
            "Never sell short: the mirror (selling stocks in a market-wide rally) lost money - it is kept in the "
            "settings only to show that.",
            "Each stock is its own trade, so several can be open on the same day.",
        ],
        "limits": [
            f"THE DAY-LEVEL CHECK (read this first): {dcheck}. The profit comes from a few crash-rebound days; on most "
            "trading days the rule loses a little. In the study, 9 Mar 2026 alone made +26% of the +34.5% total, and "
            "without the best 5 days the rule lost 0.32% of the price a trade after costs.",
            "ONE YEAR ONLY: the user keeps every study to one year, which holds only one or two real crash-rebound days. "
            "That cannot prove a strategy that lives on them - treat this as promising, not proven, and paper-trade it.",
            "QUIET MONTHS: from Sep 2025 to Jan 2026 NIFTY hardly ever fell 0.7% by mid-morning, so the rule did nothing. "
            "'Before April' is therefore really Feb-Mar 2026.",
            "ONE BET, MANY TRADES: on a crash day many stocks qualify together (29 on 9 Mar 2026). Those trades win or "
            "lose together - read 'Every day' and the day-level check, not only the trade count.",
            "WORST PRICE ONLY - the user's permanent rule for intraday stocks: entries and exits are at the worst price "
            "of the 1-minute candle after the signal. The 5-minute, hourly and daily candles only decide WHETHER and "
            "WHEN to enter (the user, 2026-09-29). There is no better-price comparison in this report.",
            "THE BIGGER-TIMEFRAME CHECK IS A SETTING, NOT THE RULE: stocks whose daily chart was already weak (below the "
            "20-day average) and whose 09:15-10:15 candle closed near its low, entered on a 5-minute close above VWAP, "
            "won 74.5% for +0.60% a trade after costs, with 15 of 21 days making money - but only about 55 trades a year. "
            "The user's minimum is 120, and no setting with 120+ trades beat the plain rule when picked on the first half "
            "(the best such pick fell to +0.14% a trade in the second half). Pick 'Bigger-timeframe check: both' and "
            "'Signal candle: 5-minute' to see it.",
            "ONE SHARE, NO LEVERAGE: every trade is 1 share at the stock's full price. Every figure is rupees for that 1 "
            "share, and a win is a trade that gained points.",
            "COSTS ARE NOT TAKEN OFF in this report. For 1 share they are about 0.27% of the price a round trip (brokerage "
            "is Rs 30 or 0.1% of each order, whichever is lower, plus STT and the rest - Rs 2.71 on a Rs 1,000 share). "
            f"The console line 'after costs' takes them off. {check}.",
            "SEVERAL STOCKS: points are added up across stocks priced from about Rs 250 to about Rs 12,000, so read "
            "'average move per trade' (%) and the 'Stock' breakdown beside the total.",
            "HOW THE RULE WAS CHOSEN: the idea (buy side of a market-wide stretch) came from the whole year; the stock's "
            "0.8x held for every market level from 0.6% to 1.0%; the market level 0.7% was picked on the days before "
            f"{SPLIT} as the lowest that still gives 120+ trades, and the days after it confirmed it.",
            "OVERLAP WITH LATE GAP FILL: both buy the same crash days. Its buy trades and these are largely the same "
            "bet - running both is not diversification.",
            "RESULTS AND DIVIDEND DAYS come from NSE announcements. " + (
                f"NSE could not be reached for {', '.join(ev_bad)} - their days say 'unknown' and the rule trades them."
                if ev_bad else "NSE answered for every stock."),
            "THE STOCK LIST is the index as listed on 2026-09-28, used for the whole year. TMPV is skipped from "
            "2025-10-14 to 2025-11-04 (the Tata Motors demerger).",
            f"WINDOW: {frm} to {to}, the one year the user asked for. Daily candles before it are read only for the "
            "average daily range and 'yesterday'.",
        ],
        "rejected": [
            ["Selling the market-wide rally (the mirror)", "lost 0.19% of the price a trade after 1-share costs in the "
             "study; kept under 'Which side: both' to show it."],
            ["Any stretch, entered at 10:30 sharp (no VWAP turn)", "358 trades, 50% winners, -0.27% a trade after costs - "
             "waiting for the turn is what makes it work."],
            ["A smaller stock fall (0.5-0.7x the range)", "more trades, but the first half lost; kept as 0.6x in the settings."],
            ["Signals up to 12:30 or 13:30", "weaker the later the signal; 12:00 is kept in the settings."],
            ["Stretches measured on the open gap alone", "that is Late Gap Fill, which stays as its own strategy."],
            ["More years of data to prove it", "not done - the user keeps every study to one year (2026-09-29)."],
            ["A 15-minute signal candle", "no better than 5 minutes and fewer trades (94, +0.36% after costs)."],
            ["Buying only stocks in a daily UPTREND (above the 20-day average)", "the opposite worked: those made nothing "
             "(61% winners, +0.00% after costs)."],
            ["5-minute RSI, 15-minute higher lows, NIFTY's own 15-minute low, NIFTY's daily trend, daily RSI",
             "no clean split in both halves, or too few trades."],
            ["The bigger-timeframe check as the rule", "74.5% winners and +0.60% a trade after costs, but about 55 trades a "
             "year - under the user's 120 minimum; kept as a setting."],
            ["Loosening the market or stock fall to get back to 120 trades", "with the bigger-timeframe check on, every "
             "looser setting lost in the first half."],
        ],
        "coverage": coverage({d: r for d, r in nmin.items() if frm.isoformat() <= d <= to.isoformat()}, frm, to, ROWS),
        "rerun": rerun_command(SLUG, settings, frm.isoformat(), to.isoformat()),
        "break_date": SPLIT,
    }
    groups = [{"name": "Stock", "keys": ["stock"]},
              {"name": "Sector", "keys": ["sector"]},
              {"name": "Buy or sell", "keys": ["direction"]},
              {"name": "Stock's distance at the signal (x daily range)", "keys": [T_STRETCH]},
              {"name": "NIFTY's move at the signal", "keys": [T_NIFTY]},
              {"name": "How the stock got there", "keys": [T_HOW]},
              {"name": "Signal time", "keys": [T_TIME]},
              {"name": "Bigger-timeframe check", "keys": [T_HTF]},
              {"name": "Daily chart before today", "keys": [T_DAILY]},
              {"name": "First hour (09:15-10:15)", "keys": [T_HOUR]},
              {"name": "Results & dividend days", "keys": [T_EVENT]},
              {"name": "Period (rule picked / new data)", "keys": ["period"]}]
    payload = build_payload(meta, trades, nmin, mins, groups, settings=settings, chart="default", sessions_log=log)
    path = write_report(payload, SLUG)
    for lab, ts in (("THE RULE", ruled), (f"  before {SPLIT}", [t for t in ruled if t["day"] < SPLIT]),
                    (f"  from {SPLIT}", [t for t in ruled if t["day"] >= SPLIT])):
        net = [t["pts"] - t["costs"] / t["qty"] for t in ts]
        extra = (f" | after costs: {sum(1 for x in net if x > 0)} wins ({sum(1 for x in net if x > 0) / len(ts) * 100:.1f}%), "
                 f"{sum(x / t['entry_px'] * 100 for x, t in zip(net, ts)) / len(ts):+.3f}% of the price a trade") if ts else ""
        print(f"{lab}: {console_summary(ts)}{extra}")
    print("day-level check: " + dcheck)
    print("exits (rule): " + ", ".join(f"{r} {sum(t['exit_reason'] == r for t in ruled)}" for r in sorted({t['exit_reason'] for t in ruled})))
    print("every trade, every setting: " + console_summary(trades))
    print(f"upstox calls: {calls}")
    print(path)


if __name__ == "__main__":
    main()
