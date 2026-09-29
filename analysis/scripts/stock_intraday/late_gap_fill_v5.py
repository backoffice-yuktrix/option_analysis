"""Late Gap Fill - v5 (late_gap_fill_v5).  Cash equity, intraday MIS, the 50 NIFTY-50 stocks.

v5 (2026-09-29) - the user: "in both strategies you have used the 1 min candles for everything; use the higher
time frames for the directions to increase the win rates and profit points and avoid the high losing trades" -
"the worst case rule checks in the 1 min only, okay; what I said is only for the entry models".
The study (scratchpad s42-s44, the same year, same exits, every fill on the next 1-minute candle's worst price):
  * The daily chart: trades where the stock was ALREADY stretched the trade's way before today (a buy: yesterday's
    close below its 20-day average; a sell: above it) won 69.8%, +0.28% a trade after 1-share costs, both halves
    (+0.26% / +0.35%); the rest made nothing in both halves (-0.08% / +0.02%).  The gap finishes a move the daily
    chart had started - the snap-back is strongest at the extreme.
  * The first hourly candle (09:15-10:15) closing in its WORSE half for the trade (a buy: the lower half - the
    panic still on at 10:15) won 73.4%, +0.38% a trade, with 1 loss of 1% or more in 64 trades.
  * v5 rule = either one: 124 trades (v4 200), 69.4% winners (65.5%), +0.52% of the price a trade before costs
    (+0.40%), +0.25% after the costs of one share (+0.12%), both halves (+0.21% / +0.32%); losers of 1% or more
    14 -> 5; without the best 5 days -0.14% a trade (-0.18%).  The 76 trades it drops lost in BOTH halves
    (-0.07% / -0.09% after costs).  Both together: 36 trades, 77.8% winners, +0.58% (a setting).
  * A 5-minute signal candle changed little here (117 trades, +0.26%) - a setting; 1 minute stays the rule.
  * Not used: 5-minute RSI, 15-minute higher lows, NIFTY's own 15-minute low, NIFTY's daily trend, daily RSI -
    no clean split in both halves.

v4 (2026-09-29) - the user: "I need the exact stop loss and target with the maximum of trades ... we have the
global feeds, other indicators and other concepts too - make a strategy better than this" (NIFTY-50 only).
The research (scratchpad, the same year, worst prices; choices read on the first half, checked on the second):
  * A research set of 871 big-gap VWAP turns (gaps from 0.5x, 10:30-12:30) with ~25 facts each - global
    (Asian open, US overnight, VIX, rupee, crude, US yields), indicators (daily RSI14, distance from the 20-day
    average, 20-day trend, beta), market (NIFTY's gap, how many stocks gapped together) and intraday state.
  * Facts that held in BOTH halves: how many NIFTY stocks gapped together (the strongest), the stock's gap size,
    NIFTY's own gap, yesterday's move (a gap after a move the other way fills better), the stretch from the
    20-day average and RSI14 (a stretched stock fills better).  The global feeds did NOT hold - they explain the
    gap but not whether it fills.
  * A combined score of those facts did not beat v3's simple cut-offs (it crowds onto fewer days).  An afternoon
    trend setup lost in every variant.  What DID add trades: on a BROAD SHOCK day (10+ NIFTY stocks gapping 1x
    their range or more the same way) medium gaps (0.6-1x) fill too - 53 more trades, 66% winners, positive in
    both halves.
  * Exact stop-loss: 0.75x the daily range beyond the gap's own extreme (the day's low for a buy, high for a
    sell, up to the signal) - where the reversal is plainly wrong.  It was hit once in 201 trades and cost
    nothing (tighter stops cost 0.03-0.05% a trade).  Exact target: 0.25x the daily range past yesterday's close.
  v4 = v3's trades + medium gaps on broad shock days, with the exact stop.  201 trades (v3: 148), 65.7% winners,
  +0.40% of the price a trade (v3 +0.45%), total +81% (v3 +67%), before April +0.40% / from April +0.41%.

v3 (2026-09-29) - the user: "somewhere we miss something; if the overall strategy rules should change to
get a real edge, check where the things will boom."  Where v2 made its money (same 175 trades):
  * By DAY: the best 5 of 50 days made 81% of the total, the best 10 made 102% - the other 40 days about
    lost.  9 Mar 2026 alone (17 trades, NIFTY opened -2.4% and came back) made +21.7% of the price summed.
  * By the MARKET: when NIFTY itself gapped the same way (0.3% or more) the gap fills - 148 trades, 65.5%
    winners, +0.45% of the price a trade, before April +0.44% / from April +0.46% (the most even split of
    anything tried).  A stock gapping ALONE (NIFTY flat or the other way) did not fill: 27 trades that lost
    as a group.  This is a market-shock reversal: big gaps shared by the whole market come back.
  * By TIME: the profit comes late - the average open trade is still slightly down an hour after entry
    and +0.26% after four hours - so the 15:14 exit stays.
  * Tried and not used: waiting 5-60 minutes after the signal (higher win rate, but 95-108 trades and
    uneven halves); allowing smaller gaps on market-gap days to keep 175+ trades (lower quality:
    0.9x -> +0.34% a trade, 0.8x -> +0.26%); weekday, buy-vs-sell and 'NIFTY already turning' splits
    (they flip between the halves).
  v3 rule = v2 + 'NIFTY gapped the same way by at least 0.3%'.  148 trades instead of 175, every
  measure better: win 62.3% -> 65.5%, +0.378% -> +0.450% of the price a trade, after the costs of one
  share +0.106% -> +0.179%, profit factor 2.35 -> 2.80, biggest drawdown 4.0% -> 3.7%.

v2 (2026-09-29) - the user: "analyze the losing trades and find a key to avoid the loss trades - manage
the proper risk here like the stop loss, then analyze and optimize this strategy for the next level;
don't reduce the trade counts."  What the losing-trade study found (same 175 trades as v1):
  * Losers do not lose fast; they DRIFT: all 64 losers were closed by the time exit, none by a jump.
    They go a median 0.46x the average daily range against, then never come back.
  * A stop-loss makes it WORSE at every distance tried (0.3x..2x the daily range, the day's extreme,
    trailing, time stops, break-even): winners dip too (48% go 0.2x against), and every stop-out pays the
    worst price.  A wide 'disaster' stop does not even cut the worst trade (the worst losses are sudden
    jumps) and raises the biggest drawdown from 4.0% to 6-7%.
  * The key to the losers: how far the stock had ALREADY swung that day by the signal.  Calm and medium
    days (under 1.26x the daily range) win 71-72%; wild days (1.26x or more) win 47-50% and make about
    nothing.  Stock-specific gaps (NIFTY did not gap the same way) are weak too (13 trades, 38% winners).
  * The target capped the winners.  Aiming 0.25x the daily range PAST yesterday's close, and holding to
    15:14 if it is not reached, lifted BOTH halves with the same 175 trades: before April +0.268% ->
    +0.324% a trade, from April +0.363% -> +0.450%; profit factor 2.24 -> 2.35; biggest drawdown 4.1% ->
    4.0%; after the costs of ONE share +0.04% -> +0.11% of the price a trade.  Win rate 63.4% -> 62.3%.
  * Filtering the wild days (and widening the net to keep 175+ trades) looked better before April and
    WORSE after it - so the trade count stays, and the swing is a setting and a breakdown, not the rule.
  v1 was removed; the v1 exit is kept in the settings for comparison.

THE USER'S PROMPT (2026-09-28): after every earlier strategy turned negative under the permanent
worst-price rule - "now make a better strategy using all the analysis you have did, if find means keep
that one strategy as best, remove all other strategies, think out of the box, then increase the win
rate and profits too."

WHERE IT COMES FROM (scratchpad study, 2025-09-29..2026-09-25, all 50 stocks, worst prices, costs in)
  * A stock's opening gap tends to come back toward yesterday's close - but most of that happens INSIDE
    the first minute, whose candle is ~0.67% of the price from high to low, so a worst-price entry at
    09:15 gives it all away.  From ~10:30 the 1-minute candles are only ~0.08% wide.
  * So wait: take only BIG gaps (at least 1x the stock's average daily range) that have NOT been filled
    by 10:30, and enter when the price turns back through the day's VWAP toward yesterday's close - the
    sign that the gap's buyers (or sellers) have given up.  Yesterday's close is the target.
  * Out of ~1,200 variants of 9 idea families tried under the worst price, this family was the one that
    held in both halves of the year.  The rule's values were picked on the sessions before 2026-04-01
    and read on the sessions after it: 173 trades, 61.8% winners, +0.25% of the price a trade after
    costs (before April 59.4% / +0.22%, from April 65.3% / +0.30%).  It survives 0.10% of extra slippage
    a trade.  Its weak points: trades cluster on ~50 days (big-gap days, mostly Feb-Apr 2026); without
    the best 10% of trades it is about break-even; exits before 14:45 are weaker.

USER DECISIONS (all standing)
  - Worst price only, entry and exit (2026-09-28, permanent for intraday stocks): a buy fills at the
    HIGH of the candle after the signal, a sell at its LOW; exits the same way.  No pre-open price, no
    candle-close comparison (build_payload refuses anything else).
  - Points per share, never bps; plain words (2026-09-28).
  - Window: the user's one year, from 2025-09-29 (fixed, so the split at 2026-04-01 stays put).

THE RULE
  1 The gap: today's 09:15 open against yesterday's official close.  It must be at least 1 x the
    stock's average daily range of the last 14 days (ATR14).
  2 Skip results days 1-2 and ex-dividend days.
  3 If any minute has already touched yesterday's close, the gap is filled: no trade that day.
  4 From 10:30 to 11:30: the first completed minute that closes on yesterday's-close side of the day's
    VWAP is the signal (gap down: closes ABOVE VWAP -> buy; gap up: closes BELOW VWAP -> sell).
  5 Enter in the next minute at its worst price (buy at its HIGH, sell at its LOW).  ONE SHARE - no
    lots, no leverage (the user, 2026-09-28).
  6 Target 0.25 x the average daily range PAST yesterday's close: the first minute that touches it exits in
    the NEXT minute at its worst price.  Not touched: exit in the 15:14 minute at its worst price.  No
    stop-loss (v2 - see above).
  7 Every stock is its own trade (several can be open on the same day).

CHECKLIST (RUN.md Step 1)
  1 Underlying clear   the 50 NIFTY-50 stocks (NSE list read 2026-09-28)     9 Entry clear  see 4-5
  2 Window     clear   2025-09-29..END_DATE, the user's one year             10 Exit clear  see 6
  3 Timeframe  clear   daily facts + 1-minute candles (VWAP from 1-min)       11 Holding clear intraday
  4 Signal     clear   see 1-4                                                12 Costs clear category
  5 Decision   clear   the close of the signal minute                         13 Positions clear one per stock/day
  6 Direction  clear   toward yesterday's close                               14 Missing data assumed skip+log
  7 Instrument clear   cash equity, MIS                                      14b declined = a gap the rule's
  8 Options    n/a                                                               filters refuse; no signal = no
                                                                                 big unfilled gap turned in time
ASSUMED
  A1 VWAP = cumulative (typical price x volume) / cumulative volume from 09:15, using completed minutes.
  A2 The universe is the index as listed on 2026-09-28, read back over the year (survivorship).
  A3 TMPV is skipped 2025-10-14..2025-11-04: the Tata Motors demerger makes its prices jump, which is not
     a gap, and inflates its average daily range for the next 14 days.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *          # noqa: F401,F403
import argparse

CATEGORY = "stock_intraday"
SLUG = "late_gap_fill_v5"
STUDY_FROM = date(2025, 9, 29)
SPLIT = "2026-04-01"
ROWS = 375
ATR_N = 14
WARMUP_DAYS = 45
SCAN_FROM, SCAN_TO = "10:29", "12:29"         # signal minutes scanned (the rule uses 10:29..11:29, entry 10:30..11:30)
MIN_GAP = 0.6                                  # smallest gap simulated (medium gaps count on broad shock days)
BROAD = 10                                     # a broad shock day: this many NIFTY stocks gapped 1x+ with NIFTY
SKIP = {"TMPV": ("2025-10-14", "2025-11-04")}  # corporate action (A3)
QTY = 1                                        # one share a trade - no lots, no leverage (the user, 2026-09-28)
ASIA = {"^N225": "Nikkei 225", "^KS11": "KOSPI", "^TWII": "Taiwan Weighted"}

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

T_SWING = "day's swing before the signal"
T_MKT = "market gap (NIFTY)"
T_SETUP, T_BREADTH = "setup", "stocks gapping 1x+ with NIFTY"
MKT_MIN = 0.003                                # NIFTY must gap the same way by at least 0.3% (the v3 rule)
MKT_LABELS = ["same way, 0.3% or more", "same way, under 0.3%", "the other way", "unknown"]
SWING_LABELS = ["calm (under 0.87x)", "medium (0.87 to 1.26x)", "wild (1.26x or more)"]
SETUP_LABELS = ["big gap (1x or more)", "medium gap (0.6-1x) on a broad shock day", "medium gap on a normal day"]
BREADTH_LABELS = ["0-4 stocks", "5-9 stocks", "10-19 stocks", "20 or more stocks"]
T_GAP, T_TIME, T_EVENT, T_RANGE, T_ASIA = ("gap size (x average daily range)", "signal time",
                                           "results & dividend days", "open vs yesterday's high-low",
                                           "Asian markets this morning")
GAP_LABELS = ["0.6 to 0.8x", "0.8 to 1x", "1 to 1.2x", "1.2 to 1.5x", "1.5x or more"]
TIME_LABELS = ["10:30-11:00", "11:00-11:30", "11:30-12:30"]
NO_EVENT = "normal day"
TARGET_PAST = 0.25                             # the target: this x the daily range PAST yesterday's close
T_DAILY, T_HOUR, T_HTF = "daily chart before today", "first hour (09:15-10:15)", "bigger-timeframe check"
DAILY_LABELS = ["already stretched the trade's way (buy: below its 20-day average)",
                "not stretched (buy: above its 20-day average)", "unknown (under 20 days of history)"]
HOUR_LABELS = ["closed in its worse half (buy: still falling at 10:15)", "closed in its better half (buy: already bouncing)"]
HTF_LABELS = ["both", "daily chart only", "first hour only", "neither"]
SMA_N = 20
# exit key: (label, target past yesterday's close in x ATR14 or None, time exit, stop beyond the gap's extreme in x ATR14 or None)
EXITS = {"ext075": ("stop 0.75x beyond the gap's extreme, target 0.25x past yesterday's close, else 15:14", TARGET_PAST, "15:14", 0.75),
         "ext050": ("stop 0.5x beyond the gap's extreme, same target", TARGET_PAST, "15:14", 0.5),
         "nostop": ("no stop, same target (v3)", TARGET_PAST, "15:14", None),
         "hold1514": ("no target, no stop, close at 15:14", None, "15:14", None)}

SETTINGS = [
    setting("market", "Market gap (NIFTY)", kind="entry", mode="filter", default="with",
            help="NIFTY itself must have gapped the same way as the stock by at least 0.3% - the whole market's gap "
                 "comes back, a stock gapping alone does not",
            options=[{"value": "with", "label": "NIFTY gapped the same way, 0.3% or more", "tag": {T_MKT: MKT_LABELS[:1]}},
                     {"value": "any", "label": "any (the stock's gap alone)", "tag": None}]),
    setting("setup", "Which gaps", kind="entry", mode="filter", default="broad",
            help="a broad shock day = 10 or more NIFTY stocks gapped at least 1x their average daily range the same "
                 "way as NIFTY; on those days medium gaps fill too",
            options=[{"value": "broad", "label": "big gaps + medium gaps on broad shock days (v4)",
                      "tag": {T_SETUP: SETUP_LABELS[:2]}},
                     {"value": "big", "label": "big gaps only, 1x or more (v3)", "tag": {T_SETUP: SETUP_LABELS[:1]}},
                     {"value": "all", "label": "every gap from 0.6x", "tag": None}]),
    setting("window", "Signal between", kind="entry", mode="filter", default="1130",
            help="the first minute that turns back across VWAP must close in this window",
            options=[{"value": "1130", "label": "10:30 and 11:30", "tag": {T_TIME: TIME_LABELS[:2]}},
                     {"value": "1230", "label": "10:30 and 12:30", "tag": {T_TIME: TIME_LABELS}}]),
    setting("events", "Results & dividend days", kind="entry", mode="filter", default="skip",
            help="the first two days after quarterly results, and ex-dividend days (from NSE)",
            options=[{"value": "skip", "label": "skip them", "tag": {T_EVENT: [NO_EVENT, "unknown (NSE not reachable)"]}},
                     {"value": "trade", "label": "trade them too", "tag": None}]),
    setting("trigger", "Signal candle", kind="entry", default="1",
            help="the candle whose close must be back across VWAP; the trade is always filled on the NEXT 1-minute "
                 "candle at its worst price",
            options=[{"value": "1", "raw": 1, "label": "1-minute candle"},
                     {"value": "5", "raw": 5, "label": "5-minute candle"}]),
    setting("htf", "Bigger-timeframe check", kind="entry", mode="filter", default="or",
            help="daily chart = yesterday's close already beyond the stock's 20-day average the trade's way (below it for "
                 "a buy); first hour = the 09:15-10:15 candle closed in its worse half for the trade",
            options=[{"value": "or", "label": "either one (the rule)", "tag": {T_HTF: HTF_LABELS[:3]}},
                     {"value": "and", "label": "both", "tag": {T_HTF: HTF_LABELS[:1]}},
                     {"value": "daily", "label": "the daily chart only", "tag": {T_HTF: HTF_LABELS[:2]}},
                     {"value": "hour", "label": "the first hour only", "tag": {T_HTF: [HTF_LABELS[0], HTF_LABELS[2]]}},
                     {"value": "off", "label": "off (v4)", "tag": None}]),
    setting("exit", "Stop-loss and target", kind="exit", default="ext075",
            options=[{"value": k, "label": v[0]} for k, v in EXITS.items()],
            help="the gap's extreme = the day's low (buy) or high (sell) up to the signal; every exit is at the worst "
                 "price of its minute; a stop or target touched in one minute exits in the next (the stop first if both)"),
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


def find_signal(rows: list[list], side: int, pc: float, tf: int = 1) -> dict:
    """Walk the day's minutes: stop at the first touch of yesterday's close (gap filled), else return the
    first tf-minute candle close (candles aligned to 09:15) in SCAN_FROM..SCAN_TO on the fill side of VWAP.
    VWAP uses completed minutes.  rows must be the full 375-minute session (index = minutes since 09:15)."""
    cum_pv = cum_v = 0.0
    for i, r in enumerate(rows):
        t, o, h, l, c, v = r
        cum_pv += (h + l + c) / 3 * v
        cum_v += v
        if (side > 0 and h >= pc) or (side < 0 and l <= pc):
            return {"why": f"the gap was filled at {t}, before any signal"}
        if t > SCAN_TO:
            break
        if t < SCAN_FROM or cum_v <= 0 or (i + 1) % tf:
            continue
        vw = cum_pv / cum_v
        if (c - vw) * side > 0:
            return {"k": i, "time": t, "close": c, "vwap": vw}
    return {"why": f"no minute turned back across VWAP by {SCAN_TO}"}


def signal_bucket(t: str) -> str:
    return TIME_LABELS[0] if t <= "10:59" else (TIME_LABELS[1] if t <= "11:29" else TIME_LABELS[2])


def daily_stretched(daily: dict, ddays: list[str], k: int, side: int) -> str:
    """Yesterday's close against the average of the last 20 closes up to yesterday: below it = stretched for a buy."""
    if k < SMA_N:
        return DAILY_LABELS[2]
    closes = [daily[x]["close"] for x in ddays[k - SMA_N:k]]
    return DAILY_LABELS[0] if (closes[-1] - sum(closes) / SMA_N) * side < 0 else DAILY_LABELS[1]


def first_hour(rows: list[list], side: int) -> str:
    """Where the 09:15-10:15 candle closed in its own range: the lower half = worse for a buy (upper, for a sell)."""
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
        asia = {}
        for tk in ASIA:
            rows = await yahoo_daily(tk, warm, to)
            asia[tk] = None if rows is None else {b[0]: b[1] / a[4] - 1 for a, b in zip(rows, rows[1:]) if a[4] > 0}
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
            ngap = (nrows[0][1] / nd[idays[i - 1]]["close"] - 1) if nrows and i > 0 else None
            av = [g[d] for g in asia.values() if g and d in g]
            ag = sum(av) / len(av) if av else None
            facts = {"NIFTY gap %": None if ngap is None else ngap * 100,
                     "Asian markets gap %": None if ag is None else ag * 100}
            if not nrows or len(nrows) != ROWS:
                log.append(session_row(d, "no data", "NIFTY's candles for the day are incomplete (a special or short "
                                                     "session) - not traded", **facts))
                skips.append(f"{d}: NIFTY session incomplete")
                continue
            brd = 0                                        # stocks gapping 1x+ their range the same way as NIFTY
            for s2 in UNIVERSE:
                r2, dd2, dl2 = mins[s2].get(d), daily[s2], dsorted[s2]
                if not r2 or d not in dd2 or ngap is None or (s2 in SKIP and SKIP[s2][0] <= d <= SKIP[s2][1]):
                    continue
                k2 = dl2.index(d)
                if k2 < ATR_N + 1:
                    continue
                pc2 = dd2[dl2[k2 - 1]]["close"]
                g2 = r2[0][1] / pc2 - 1
                if g2 * ngap > 0 and abs(g2) / (atr14(dd2, dl2, k2) / pc2) >= 1.0:
                    brd += 1
            facts["stocks gapping 1x+ with NIFTY"] = brd
            big, day_trades, refused, bad = 0, [], [], []
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
                pc, ph, pl = prev["close"], prev["high"], prev["low"]
                o = rows[0][1]
                gap = o / pc - 1
                atr = atr14(dd, ddays, k)
                g_atr = abs(gap) / (atr / pc)
                if g_atr < MIN_GAP:
                    continue
                big += 1
                side = 1 if gap < 0 else -1                   # gap down -> buy back toward yesterday's close
                ev = events[s].get(d, NO_EVENT) if ev_state[s] else "unknown (NSE not reachable)"
                d_tag, h_tag = daily_stretched(dd, ddays, k, side), first_hour(rows, side)
                if ag is None:
                    atag = "unknown"
                else:
                    atag = "flat (under 0.1%)" if abs(ag) < 0.001 else ("same way as the gap" if (ag > 0) == (gap > 0)
                                                                      else "the other way")
                side_s = "LONG" if side > 0 else "SHORT"
                per_tf = {}
                for tf in sorted({c["trigger"] for c in all_c}):
                    sig = find_signal(rows, side, pc, tf)
                    per_tf[tf] = None
                    if "k" not in sig:
                        continue
                    if sig["k"] + 1 >= len(rows):
                        skips.append(f"{d} {s}: no candle after the signal")
                        continue
                    upto = rows[:sig["k"] + 1]                     # completed minutes up to the signal
                    swing = (max(r[2] for r in upto) - min(r[3] for r in upto)) / atr
                    extreme = min(r[3] for r in upto) if side > 0 else max(r[2] for r in upto)   # the gap's extreme so far
                    tags = {"direction": "buy the gap-down back up" if side > 0 else "sell the gap-up back down",
                            "stock": s, "sector": sector,
                            T_GAP: bucket(g_atr, [0.8, 1.0, 1.2, 1.5], GAP_LABELS),
                            T_SETUP: (SETUP_LABELS[0] if g_atr >= 1.0 else SETUP_LABELS[1] if brd >= BROAD else SETUP_LABELS[2]),
                            T_BREADTH: bucket(brd, [5, 10, 20], BREADTH_LABELS),
                            T_TIME: signal_bucket(sig["time"]),
                            T_EVENT: ev,
                            T_RANGE: "beyond it" if (o > ph or o < pl) else "inside it",
                            T_SWING: bucket(swing, [0.87, 1.26], SWING_LABELS),
                            T_MKT: (MKT_LABELS[3] if ngap is None else MKT_LABELS[2] if (ngap > 0) != (gap > 0) or ngap == 0
                                    else MKT_LABELS[0] if abs(ngap) >= MKT_MIN else MKT_LABELS[1]),
                            T_ASIA: atag,
                            T_DAILY: d_tag, T_HOUR: h_tag, T_HTF: htf_tag(d_tag, h_tag),
                            "NIFTY's own gap": ("unknown" if ngap is None else "flat (under 0.05%)" if abs(ngap) < 0.0005
                                                else "same way as the stock" if (ngap > 0) == (gap > 0) else "the other way"),
                            "period": "Sep 2025 - Mar 2026 (rule picked here)" if d < SPLIT else "Apr - Sep 2026 (new data)"}
                    entry = rows[sig["k"] + 1]
                    per_tf[tf] = (sig, swing, extreme, tags, entry, entry[2] if side > 0 else entry[3])   # worst price
                seen = None
                for c in all_c:
                    bundle = per_tf.get(c["trigger"])
                    if bundle is None:
                        continue
                    sig, swing, extreme, tags, entry, e_px = bundle
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
                                {"name": "the gap's extreme", "price": round(extreme, 2)},
                                {"name": "today's open", "price": o},
                                {"name": "VWAP at the signal", "price": round(sig["vwap"], 2)}],
                        note=f"gap {gap * 100:+.2f}% = {g_atr:.2f} x its average daily range ({atr / pc * 100:.2f}%); the "
                             f"{c['trigger']}-minute candle whose last minute is {sig['time']} closed {sig['close']:.2f}, back "
                             f"across VWAP {sig['vwap']:.2f}; the day had swung {swing:.2f}x its daily range by then; daily "
                             f"chart: {d_tag}; first hour: {h_tag}; 1 share")
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
            facts.update({"gaps 0.6x+": big, "trades (rule)": len(day_trades),
                          "stocks traded (rule)": ", ".join(s for s, _ in day_trades) or "-"})
            tail = f"; no usable data for {', '.join(bad)}" if bad else ""
            if day_trades:
                log.append(session_row(d, "traded", f"{len(day_trades)} trade(s) under the rule" + tail, **facts))
            elif refused:
                why = "; ".join(f"{s} ({', '.join(n)})" for s, n in refused[:6])
                log.append(session_row(d, "declined", f"a big gap turned back, but the rule's filters said no - {why}. "
                                       "Switch the filter off in the settings to count it" + tail, **facts))
            else:
                log.append(session_row(d, "no signal", ("no big gap turned back across VWAP in time" if big else
                                                        "no stock gapped by 0.8x its average daily range") + tail, **facts))
        calls = up.calls
    return trades, log, skips, nmin, mins, check, ev_state, asia, calls


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
    trades, log, skips, nmin, mins, check, ev_state, asia, calls = asyncio.run(run(frm, to, settings))
    print(f"\n{len(skips)} skips:")
    for s in skips[:60]:
        print("  " + s)
    if len(skips) > 60:
        print(f"  ... {len(skips) - 60} more")
    ev_bad = [s for s, ok_ in ev_state.items() if not ok_]
    meta = {
        "title": "Late Gap Fill v5",
        "subtitle": "On a day the whole market gaps, a stock's gap that is still unfilled at 10:30 (big, or medium on a broad shock day): when the price turns back across the day's VWAP, "
                    "trade toward yesterday's close - only when a bigger timeframe agrees (the daily chart already stretched the same way, or the first hour closed at its worst) - with an exact stop beyond the gap's extreme and a target a little past the close, else close at 15:14. All 50 NIFTY-50 stocks, "
                    "cash equity, intraday (MIS), worst prices, in points per share.",
        "instrument": f"{len(UNIVERSE)} NIFTY-50 stocks - cash equity (NSE), intraday MIS",
        "index_label": "NIFTY 50",
        "from": frm.isoformat(), "to": to.isoformat(), "category": CATEGORY,
        "fill_rule": "Worst price only: entry in the minute after the signal minute - a buy at its HIGH, a sell at its LOW; "
                     "exit in the minute after the target is touched - a buy sold at its LOW, a sell bought back at its "
                     "HIGH; the time exit fills in its own minute",
        "params": {"the rule": "NIFTY gapped the same way by 0.3% or more; the stock's gap at least 1x its average daily range (0.6x on a broad shock day with 10+ stocks gapping 1x+), not filled; first minute from 10:30 to 11:30 that "
                               "closes back across VWAP; the daily chart already stretched the trade's way OR the 09:15-10:15 candle closed in its worse half; enter the next minute at the worst price; target 0.25x the daily "
                               "range past yesterday's close; stop 0.75x the range beyond the gap's extreme; else 15:14; skip results and dividend days",
                   "gap": "today's 09:15 open against yesterday's official close",
                   "average daily range (ATR14)": "the average of the last 14 days' high-to-low range, counting the gap "
                                                  "from the day before",
                   "VWAP": "cumulative (typical price x volume) / cumulative volume from 09:15, completed minutes",
                   "size": "1 share per trade, at the stock's full price - no lots, no leverage",
                   "day": "09:15-15:29 in 375 one-minute candles",
                   "window": f"{frm} .. {to} (the user's one-year window)"},
        "rule_steps": [
            "Each morning, measure every NIFTY-50 stock's gap: today's 09:15 open against yesterday's close.",
            "Keep only BIG gaps - at least 1 times the stock's average daily range of the last 14 days (ATR14). "
            "Example: a stock that moves about Rs 20 a day must open at least Rs 20 away from yesterday's close.",
            "On a BROAD SHOCK day - 10 or more NIFTY stocks gapped at least 1x their range the same way as NIFTY - "
            "medium gaps count too: at least 0.6 times the average daily range.",
            "The MARKET must gap too: NIFTY's open must be at least 0.3% away from its own close, the same way as the "
            "stock's gap. A stock gapping alone is not traded.",
            "Skip the first two days after the company's quarterly results, and its ex-dividend day.",
            "If the price has already touched yesterday's close, the gap is filled - no trade that day.",
            "BIGGER TIMEFRAMES - at least ONE must agree: (a) DAILY CHART: yesterday's close was already beyond the "
            "stock's 20-day average the trade's way (below it for a buy, above it for a sell); (b) HOURLY CANDLE: the "
            "09:15-10:15 candle closed in its worse half for the trade (the lower half for a buy - still falling at "
            "10:15; the upper half for a sell).",
            "From 10:30 to 11:30, watch for the first minute that closes back across the day's VWAP toward "
            "yesterday's close (a gap-down stock closing ABOVE VWAP, a gap-up stock closing BELOW it).",
            "Enter in the next minute at its worst price: BUY a gap-down stock at the minute's HIGH, SELL a gap-up "
            "stock at its LOW. One share.",
            "Target = a little PAST yesterday's close: 0.25 times the average daily range beyond it. Example: closed "
            "yesterday at Rs 1,000, moves about Rs 20 a day, gapped down - the target is Rs 1,005. As soon as a minute "
            "touches it, close in the next minute at that minute's worst price (a buy is sold at the LOW, a sell is "
            "bought back at the HIGH).",
            "STOP-LOSS = the gap's extreme (the day's lowest price so far for a buy, highest for a sell) plus 0.75 times "
            "the average daily range beyond it. Example: a buy whose low today was Rs 980, range Rs 20 - stop Rs 965. A "
            "minute touching it closes the trade in the next minute at its worst price.",
            "If neither is touched, close in the 15:14 minute at its worst price.",
            "Each stock is its own trade, so several can be open on the same day.",
        ],
        "limits": [
            "WORST PRICE ONLY - the user's permanent rule for intraday stocks: entries and exits are at the worst price "
            "of the 1-minute candle after the signal. The daily and hourly candles (and the 5-minute signal candle in "
            "the settings) only decide WHETHER and WHEN to enter (the user, 2026-09-29). There is no better-price "
            "comparison in this report.",
            "v5 - THE BIGGER-TIMEFRAME CHECK (study, same year): trades where the daily chart was already stretched the "
            "trade's way won 69.8%, +0.28% a trade after 1-share costs, in both halves; a first hour that closed at its "
            "worst for the trade won 73.4%, +0.38%, with 1 loss of 1% or more in 64 trades. The rule takes either: 124 "
            "trades, 69.4% winners, +0.25% a trade after costs (v4 +0.12%), losers of 1% or more 14 -> 5. The 76 trades "
            "it drops lost money in BOTH halves. It was one of 9 bigger-timeframe checks tried on the whole year - one "
            "year only, so paper-trade it.",
            "WHY 10:30: the 09:15 candle is typically 0.67% of the price from high to low, the 10:30 candles about 0.09%, "
            "so waiting costs far less than it gives up. Most of a gap's move back happens in the first minute; this "
            "rule only takes the part that is left on big gaps that have not given up yet.",
            "ONE SHARE, NO LEVERAGE: every trade is 1 share at the stock's full price - no lots, no margin (the user, "
            "2026-09-28). Every figure is rupees for that 1 share, in the trade's favour (a short that falls Rs 5 is +5), "
            "and a win is a trade that gained points.",
            "COSTS ARE NOT TAKEN OFF in this report. For 1 share they are large: brokerage is Rs 30 or 0.1% of each order, "
            "whichever is lower, so a small order pays 0.1% on the way in and again on the way out - about 0.27% of the "
            "price per round trip with STT and the rest (Rs 2.71 on a Rs 1,000 share). That takes most of this rule's "
            f"average move (about 0.31% before costs). {check}.",
            "SEVERAL STOCKS: points are added up across stocks priced from about Rs 250 to about Rs 12,000, so read "
            "'average move per trade' (%) and the 'Stock' breakdown beside the total.",
            "HOW THE RULE WAS CHOSEN: about 1,200 variants of 9 ideas were tried on the whole year in a study; this "
            f"family was the only one that held in both halves. The rule's own values were ranked on the days before "
            f"{SPLIT} - so 'Stability' before {SPLIT} is where it was picked and from {SPLIT} is new data. The idea "
            "itself was found on the whole year: treat the result as promising, not proven.",
            "CLUSTERED: big gap days come in bunches (market-wide shocks), so the trades fall on about 50 days, most in "
            "Feb-Apr 2026. In the study, without the best 10% of trades the result was about break-even - a few big "
            "fills carry it. It survived 0.10% of the price of extra slippage per trade.",
            "EXIT TIME MATTERS: in the study, closing at 14:15 or 14:30 made much less than 14:45 or 15:14 - the fill "
            "often completes in the afternoon.",
            "THE LOSING TRADES (v2 study, the same 175 trades): losers do not lose fast, they drift - every one was closed "
            "by the time exit, after going a median 0.46x the daily range against. Their key is the day's swing before "
            "the signal: under 1.26x the daily range the trades won 71-72%, at 1.26x or more about half, for almost "
            "nothing. Gaps the market did not share (NIFTY gapped the other way) were weak too. See 'Day's swing before "
            "the signal' and 'NIFTY's own gap' in the breakdowns.",
            "RISK - WHY NO STOP-LOSS: every stop tried (0.3x to 2x the daily range, the day's extreme, trailing, "
            "time-based, break-even) lowered the result, because winners dip too and each stop-out pays the worst price. "
            "A wide 'disaster' stop did not even cut the worst trade - the worst losses are sudden jumps - and it raised "
            "the biggest drawdown from 4.0% to 6-7%. The risk here is held by the design instead: one share, a fixed "
            "exit time, and only big gaps that have already turned. 'Exit and stop-loss' in the settings shows the "
            "stops' cost on these trades.",
            "WHERE IT MAKES ITS MONEY (v3 study): on MARKET-WIDE gap days. With v2's rules the best 5 of 50 days made 81% "
            "of the profit and the best 10 all of it; 9 Mar 2026 alone (17 trades, NIFTY opened -2.4%) made the most. The "
            "v3 rule keeps only days when NIFTY itself gapped 0.3%+ the same way - 148 trades on about 32 days - and "
            "every measure improved, with before and after April almost equal (+0.44% / +0.46% of the price a trade). "
            "It is still a few-big-days strategy: most of the year it does nothing, and a few shock days carry it.",
            "v4 RESEARCH: ~25 facts per trade were tested (global feeds, daily RSI14, 20-day average, trend, beta, "
            "market breadth, intraday state). Held in both halves: how many stocks gapped together, the gap size, "
            "NIFTY's gap, yesterday's move, the stretch from the 20-day average. The global feeds did not (they explain "
            "the gap, not the fill). On broad shock days medium gaps fill too - that is v4's extra 53 trades.",
            "EXACT STOP: 0.75x the daily range beyond the gap's extreme - hit once in 201 trades in the study and cost "
            "nothing; tighter stops (0.25x / 0.5x) cost 0.05% / 0.03% of the price a trade. Most trades still end at "
            "15:14: the target (0.25x past yesterday's close) was reached 11 times.",
            "HOW v3 WAS CHOSEN: the market-gap rule came from dissecting v2's trades on the whole year; the 0.3% level "
            "was compared with 0.2-1.0% (all similar). Treat it as a strong lead, not proof - paper-trade it.",
            "HOW v2 WAS CHOSEN: the new exit was picked on the days before 2026-04-01 among exits and stops that keep "
            "every trade, and it improved the days after too (+0.363% -> +0.450% of the price a trade). Skipping the wild "
            "days looked better before April and worse after, so the rule keeps them.",
            "RESULTS AND DIVIDEND DAYS come from NSE announcements. " + (
                f"NSE could not be reached for {', '.join(ev_bad)} - their days say 'unknown' and the rule trades them."
                if ev_bad else "NSE answered for every stock."),
            "ASIAN MARKETS come from Yahoo Finance: the average opening gap of the Nikkei 225, KOSPI and Taiwan that "
            "morning (a breakdown only). " + ("Not available on this run for: " + ", ".join(
                ASIA[k] for k, v in asia.items() if v is None) + "." if any(v is None for v in asia.values()) else ""),
            "THE STOCK LIST is the index as listed on 2026-09-28, used for the whole year. TMPV is skipped from "
            "2025-10-14 to 2025-11-04 (the Tata Motors demerger).",
            f"WINDOW: {frm} to {to}, the one year the user asked for - longer than the shared window (from "
            f"{START_DATE}). Daily candles before it are read only for the average daily range and 'yesterday'.",
        ],
        "rejected": [
            ["Every earlier strategy", "the seven opening-gap fades and the HDFC open fade lose at the worst price "
             "(for example the base gap fade: 935 trades, 37.9% winners); they were removed on 2026-09-28."],
            ["Trading at the open", "the 09:15 candle is ~0.67% wide - a worst-price entry there gives the move away."],
            ["A stop-loss as the rule", "every stop lowered the result on these trades (see the notes); two are kept "
             "in 'Exit and stop-loss' to show their cost."],
            ["Skipping wild days / widening the net", "skipping days that had already swung 1.26x+ (and widening the "
             "gap or time window to keep 175+ trades) looked better before April and worse after it; widening alone "
             "added weaker trades (win rate 56-58%)."],
            ["v1", "replaced by v2 on 2026-09-29; its exit is 'v1: target yesterday's close, else 14:45' in the settings."],
            ["v2", "replaced by v3 on 2026-09-29; 'Market gap (NIFTY): any' in the settings is v2."],
            ["v3", "replaced by v4 on 2026-09-29; 'Which gaps: big gaps only' with 'no stop' is v3."],
            ["v4", "replaced by v5 on 2026-09-29; 'Bigger-timeframe check: off (v4)' is v4. The v1 exit was dropped from "
             "the settings to keep the page's combination list under 1,000."],
            ["Buying only stocks in a daily UPTREND", "the opposite worked: gaps in stocks NOT already stretched the same "
             "way made nothing in both halves."],
            ["5-minute RSI, 15-minute higher lows, NIFTY's own 15-minute low, NIFTY's daily trend, daily RSI",
             "no clean split in both halves, or too few trades."],
            ["A 15-minute signal candle", "no better than 1 or 5 minutes (183 trades, +0.13% a trade after costs)."],
            ["A combined score of the good facts", "did not beat the simple cut-offs at the same trade count and crowded "
             "the trades onto fewer days."],
            ["Global feeds as filters", "Asian open, US overnight, VIX, rupee, crude, US yields - none held in both halves."],
            ["Afternoon trend continuation", "a separate setup for more trades: lost in every variant (36-45% winners)."],
            ["NIFTY Next 50 stocks", "not tested - the user keeps this to the NIFTY-50 stocks."],
            ["Waiting after the signal", "entering 5-60 minutes later won more often but left only 95-108 trades, and "
             "the two halves disagreed."],
            ["Smaller gaps to keep 175+ trades", "on market-gap days, 0.9x gaps gave +0.34% and 0.8x +0.26% of the price a "
             "trade (both below v3) - the count is not worth the quality."],
            ["Weekday / buy vs sell / 'NIFTY already turning'", "each looked strong in one half and weak in the other."],
            ["Watching from 10:00 or 10:15", "earlier signals were weaker in the study: wider candles and more false "
             "turns."],
            ["Other ideas tried under the worst price", "opening-range breakouts on heavy-volume days, results-day "
             "follow-through, stock-specific gaps, late-day momentum, yesterday's big move reversing, sector "
             "spreads and VWAP pullbacks on trend days - all lost or were too few to trust."],
        ],
        "coverage": coverage({d: r for d, r in nmin.items() if frm.isoformat() <= d <= to.isoformat()}, frm, to, ROWS),
        "rerun": rerun_command(SLUG, settings, frm.isoformat(), to.isoformat()),
        "break_date": SPLIT,
    }
    groups = [{"name": "Stock", "keys": ["stock"]},
              {"name": "Sector", "keys": ["sector"]},
              {"name": "Buy or sell", "keys": ["direction"]},
              {"name": "Gap size (x average daily range)", "keys": [T_GAP]},
              {"name": "Signal time", "keys": [T_TIME]},
              {"name": "Day's swing before the signal", "keys": [T_SWING]},
              {"name": "Market gap (NIFTY)", "keys": [T_MKT]},
              {"name": "Setup", "keys": [T_SETUP]},
              {"name": "Bigger-timeframe check", "keys": [T_HTF]},
              {"name": "Daily chart before today", "keys": [T_DAILY]},
              {"name": "First hour (09:15-10:15)", "keys": [T_HOUR]},
              {"name": "Stocks gapping together", "keys": [T_BREADTH]},
              {"name": "Day's swing x market gap", "keys": [T_SWING, T_MKT]},
              {"name": "Open vs yesterday's high-low", "keys": [T_RANGE]},
              {"name": "Results & dividend days", "keys": [T_EVENT]},
              {"name": "Asian markets this morning", "keys": [T_ASIA]},
              {"name": "NIFTY's own gap", "keys": ["NIFTY's own gap"]},
              {"name": "Period (rule picked / new data)", "keys": ["period"]}]
    payload = build_payload(meta, trades, nmin, mins, groups, settings=settings, chart="default", sessions_log=log)
    path = write_report(payload, SLUG)
    rule = default_combo(settings)
    fopts = [next(o for o in s["options"] if o["value"] == s["default"]) for s in settings if s["mode"] == "filter"]
    ruled = [t for t in trades if all(t["variant"].get(k) == str(v) for k, v in rule.items())
             and all(not o.get("tag") or all(t["tags"].get(k) in v for k, v in o["tag"].items()) for o in fopts)]
    for lab, ts in (("THE RULE", ruled), (f"  before {SPLIT}", [t for t in ruled if t["day"] < SPLIT]),
                    (f"  from {SPLIT}", [t for t in ruled if t["day"] >= SPLIT])):
        net = [t["pts"] - t["costs"] / t["qty"] for t in ts]
        extra = (f" | after costs: {sum(1 for x in net if x > 0)} wins ({sum(1 for x in net if x > 0) / len(ts) * 100:.1f}%), "
                 f"{sum(x / t['entry_px'] * 100 for x, t in zip(net, ts)) / len(ts):+.3f}% of the price a trade") if ts else ""
        print(f"{lab}: {console_summary(ts)}{extra}")
    days = {}
    for t in ruled:
        days[t["day"]] = days.get(t["day"], 0.0) + t["pts"] / t["entry_px"] * 100
    best5 = sorted(days, key=lambda x: -days[x])[:5]
    rest = [t["pts"] / t["entry_px"] * 100 for t in ruled if t["day"] not in best5]
    if days:
        v = sorted(days.values())
        print(f"day-level check: {len(v)} days, {sum(x > 0 for x in v)} made money, median day {v[len(v) // 2]:+.2f}%; "
              f"without the best 5 days {sum(rest) / max(len(rest), 1):+.3f}% a trade (before costs)")
    print("every trade, every setting: " + console_summary(trades))
    print(f"upstox calls: {calls}")
    print(path)


if __name__ == "__main__":
    main()
