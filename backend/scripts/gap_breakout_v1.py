"""NIFTY gap breakout - ONE strategy, both directions, exactly as specified.

The long and the short are mirror images.  Nothing else differs: same session,
same 15-minute candles, same scan window, same square-off, same R:R ladder.

                     LONG (gap up)                  SHORT (gap down)
  ------------------------------------------------------------------------
  1  gap        GapUp%   = (Open-PDC)/PDC*100   GapDown% = (Open-PDC)/PDC*100
                PDC = previous session's last traded print (--pdc, see below)
                >= +0.30                        <= -0.30
  2  level      FirstCandleHIGH (09:15-09:29)   FirstCandleLOW (09:15-09:29)
     trigger    first cn in 09:30..11:00        first cn in 09:30..11:00
                with CLOSE ABOVE the level      with CLOSE BELOW the level
     entry      BUY at the OPEN of cn+1         SELL at the OPEN of cn+1
  3  stop       SL = cn LOW                     SL = cn HIGH
  4  risk       Risk = Entry - SL               Risk = SL - Entry
  5  target     Entry + Risk x RR               Entry - Risk x RR

A session can only be one of the two - the open is either above or below PDC -
so the two sides never overlap and "both" is simply every signal the rule
produces.  The report shows Long, Short and Both as three views of the same
run.

STOP RULE - two readings of step 3, selectable, applied to both sides:

  close  the rule as written - the position is closed only when a later
         candle CLOSES beyond cn's low (long) / high (short), and the fill is
         that candle's close.  A confirmed stop, but the fill is wherever the
         candle happened to close, so the loss is NOT capped at 1R.
  touch  a resting SL order at that level, filled the moment price trades
         there.  Every loss is exactly 1R, but trades that only wick through
         the level are stopped out instead of surviving.

Targets are a touch and are checked on 1-minute data, so a target reached
inside a candle is taken before that candle's close can trigger the stop.
When one minute both touches the target and breaks the stop, the stop is taken
first.  Anything still open is squared off at 15:15.


KNOWN PITFALLS IN THIS DATA - both of these were shipped wrong once
-------------------------------------------------------------------
1. THE PDC BASIS IS A RULE CHOICE, AND IT IS NOT FREE.  --pdc selects it:

     last1m  the previous session's last traded print (its 15:29 candle).
             THE DEFAULT, chosen deliberately 2026-09-09 - it is the previous
             close a chart shows, and it is the number the gap is judged
             against in practice.
     daily   the previous session's OFFICIAL close, from the daily candles.

   They are not the same number: the 1-minute feed stops at 15:29 and carries
   the last print, while the official close comes from the closing session.
   Over 2026-03-09..2026-09-07 they differ on 98 of 124 sessions, by up to
   85.70 points (2026-03-19), which moves GapUp% across the 0.30% line on 8
   days and changes 4 actual trades: last1m gains 2026-03-18, 2026-06-03 and
   2026-07-02, and loses 2026-06-22.  The other 4 flips never broke out on
   either basis.  Every day row carries pdc_alt / gap_pct_alt - the reading
   NOT in use - so a day sitting on the threshold stays visible instead of
   silently vanishing, which is how 2026-03-18 was missed for a whole session.

2. A CLOSE-CONFIRMED STOP DOES NOT CAP THE LOSS AT 1R.  Reporting "risk =
   |entry - SL|" and then filling at a candle close silently understates the
   loss.  Hence --stop-mode, and hence the day table shows the fill, the level
   and the realised R side by side.

Run from backend/:
    python scripts/gap_breakout_v1.py
    python scripts/gap_breakout_v1.py --offline
    python scripts/gap_breakout_v1.py --gap 0.5 --side short

Output: gap_breakout_v1_report.html (self-contained, no CDN).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..")
sys.path.insert(0, BACKEND_DIR)

from services.upstox_client import INSTRUMENT_KEYS, get_candles  # noqa: E402
from services.option_pricing import CachedPricer, ensure_cached  # noqa: E402

# backend/scripts holds only strategy code; the candle caches live in
# backend/data and the generated reports in backend/reports.
DATA_DIR = os.path.join(BACKEND_DIR, "data")
REPORTS_DIR = os.path.join(BACKEND_DIR, "reports")
CONFIG_FILE = os.path.join(BACKEND_DIR, "upstox_config.txt")
REPORT_HTML = os.path.join(REPORTS_DIR, "gap_breakout_v1_report.html")

UNDERLYING = "NIFTY"
UNDERLYING_KEY = INSTRUMENT_KEYS[UNDERLYING]

# NIFTY lot size verified against the Upstox contract master for this period.
LOT_SIZE = 65
# The rule is decided on SPOT, but the money is the option that would actually
# have been bought.  `points x LOT_SIZE` is a NIFTY FUTURES payoff: premium
# moves at delta and bleeds theta, so that figure overstates a bought option.
PRICER = CachedPricer()

GAP_PCT = 0.30                 # step 1 threshold, % of PDC
RR_VALUES = [2.0, 3.0, 4.0, 5.0]
DEFAULT_RR = 2.0
# Two readings of step 3.  See KNOWN PITFALLS above.
STOP_MODES = [("close", "Candle CLOSE below cn low, filled at that close"),
              ("touch", "SL order at cn low, filled on touch")]
DEFAULT_STOP = "close"
# Report views.  A day is either a gap up or a gap down, never both, so "both"
# is the union - the strategy as actually traded.
SIDES = [("both", "Long + short, every signal the rule produces"),
         ("long", "Gap up, breakout above the first 15m high"),
         ("short", "Gap down, breakdown below the first 15m low")]
DEFAULT_SIDE = "both"
# Which previous close the gap is measured against.  These are NOT the same
# number: the 1-minute feed's last candle is 15:29 and carries the last traded
# print, while the official close is derived from the closing session, and the
# two differ on 98 of 124 sessions here (up to 85.70 points).  That moves
# GapUp% across the 0.30% line on 8 days, so the basis is a rule choice, not a
# data detail - hence a flag rather than a fixed answer.
PDC_MODES = [("daily", "Previous session's OFFICIAL close (daily candles)"),
             ("last1m", "Previous session's last traded print (15:29 candle)")]
DEFAULT_PDC = "last1m"

SCAN_FROM = "09:30"            # first candle that may break out
SCAN_TO = "11:00"              # last candle that may break out
SQUARE_OFF = "15:15"           # anything still open is closed here (3:15 PM)

OPEN_TIME = "09:15"
DAY_END = "15:29"
BUCKET = 15                    # minutes per candle


def rr_label(r: float) -> str:
    return f"1:{r:g}"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _read_access_token() -> str | None:
    try:
        with open(CONFIG_FILE) as f:
            lines = [l.strip() for l in f.readlines()]
    except OSError:
        return None
    return lines[3] if len(lines) >= 4 and lines[3] else None


def nifty_cache_path(from_date: date, to_date: date) -> str:
    return os.path.join(
        DATA_DIR, f"nifty_1m_{from_date.isoformat()}_{to_date.isoformat()}.json")


def _slice_existing_cache(from_date: date, to_date: date) -> list[dict] | None:
    """Reuse a wider cache file that already covers the requested window."""
    best: tuple[int, list[dict], str] | None = None
    for name in os.listdir(DATA_DIR):
        if not (name.startswith("nifty_1m_") and name.endswith(".json")):
            continue
        stem = name[len("nifty_1m_"):-len(".json")]
        try:
            a, b = stem.split("_")
            c_from, c_to = date.fromisoformat(a), date.fromisoformat(b)
        except ValueError:
            continue
        if c_from > from_date or c_to < from_date:
            continue
        with open(os.path.join(DATA_DIR, name)) as f:
            candles = json.load(f)
        kept = [c for c in candles
                if from_date.isoformat() <= c.get("timestamp", "")[:10] <= to_date.isoformat()]
        if kept and (best is None or len(kept) > best[0]):
            best = (len(kept), kept, name)
    if best is None:
        return None
    print(f"Reusing {best[2]}: {best[0]} candles inside {from_date} -> {to_date}")
    return best[1]


async def load_nifty(offline: bool, from_date: date, to_date: date) -> list[dict]:
    cache = nifty_cache_path(from_date, to_date)
    if os.path.exists(cache):
        with open(cache) as f:
            candles = json.load(f)
        print(f"Loaded {len(candles)} cached NIFTY 1m candles from {os.path.basename(cache)}")
        return candles
    token = None if offline else _read_access_token()
    if token:
        try:
            print(f"Fetching NIFTY 1m candles {from_date} -> {to_date} ...")
            candles = await get_candles(token, UNDERLYING_KEY, "1m", from_date, to_date)
            if candles:
                print(f"Fetched {len(candles)} candles.")
                with open(cache, "w") as f:
                    json.dump(candles, f)
                return candles
            print("  ! Upstox returned no candles; falling back to the local caches.")
        except Exception as exc:                                  # noqa: BLE001
            print(f"  ! fetch failed ({exc}); falling back to the local caches.")
    reused = _slice_existing_cache(from_date, to_date)
    if reused is None:
        raise RuntimeError(f"No data for {from_date} -> {to_date} and no usable cache.")
    return reused


def daily_cache_path(from_date: date, to_date: date) -> str:
    return os.path.join(
        DATA_DIR, f"nifty_1d_{from_date.isoformat()}_{to_date.isoformat()}.json")


async def load_daily(offline: bool, from_date: date, to_date: date) -> dict[str, float]:
    """{'YYYY-MM-DD': official session close} from the daily candle feed.

    This is the `--pdc daily` basis.  It is loaded even when --pdc is last1m,
    because the report shows both readings side by side (pdc / pdc_alt) and
    the difference is what decides 8 days on the 0.30% line - see KNOWN
    PITFALLS 1 for which days and what it costs.
    """
    lookback = from_date - timedelta(days=15)       # enough to have a PDC for day 1
    cache = daily_cache_path(lookback, to_date)
    raw = None
    if os.path.exists(cache):
        with open(cache) as f:
            raw = json.load(f)
        print(f"Loaded {len(raw)} cached NIFTY daily candles from {os.path.basename(cache)}")
    else:
        token = None if offline else _read_access_token()
        if token:
            try:
                print(f"Fetching NIFTY daily candles {lookback} -> {to_date} ...")
                raw = await get_candles(token, UNDERLYING_KEY, "1d", lookback, to_date)
                if raw:
                    with open(cache, "w") as f:
                        json.dump(raw, f)
                    print(f"Fetched {len(raw)} daily candles.")
                else:
                    raw = None
            except Exception as exc:                              # noqa: BLE001
                print(f"  ! daily fetch failed ({exc})")
                raw = None
    if not raw:
        raise RuntimeError(
            "Daily candles are required for the previous-day close (PDC). "
            "Run once online, or supply " + os.path.basename(cache))
    return {c["timestamp"][:10]: float(c["close"]) for c in raw}


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

def bucket_start(hhmm: str, minutes: int = BUCKET) -> str:
    """09:15-anchored bucket label: 09:15, 09:30, 09:45, ..., 15:15."""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    offset = (h * 60 + m) - (9 * 60 + 15)
    if offset < 0:
        return OPEN_TIME
    start = 9 * 60 + 15 + (offset // minutes) * minutes
    return f"{start // 60:02d}:{start % 60:02d}"


def build_buckets(minutes: list[dict], size: int = BUCKET) -> list[dict]:
    """Aggregate 1-minute candles into `size`-minute candles, in time order."""
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


# ---------------------------------------------------------------------------
# The strategy
# ---------------------------------------------------------------------------

def walk(bars: list[dict], i_entry: int, entry: float, sl: float,
         target: float, square_off: str, stop_mode: str, side: str) -> dict:
    """Forward walk from the entry candle until target, stop or square-off.

    Long and short are exact mirrors:
      long   stop is below (close < sl / low <= sl),  target above (high >= target)
      short  stop is above (close > sl / high >= sl), target below (low <= target)

    stop_mode "close": the stop can only fire at a 15-minute bar close, and the
    fill is that close.  stop_mode "touch": a resting order at the level,
    checked every minute and filled at the level.  The stop is checked BEFORE
    the target, so a minute that spans both is scored as a loss.
    """
    long = side == "LONG"
    for b in bars[i_entry:]:
        for m in b["minutes"]:
            hhmm = m["timestamp"][11:16]
            if hhmm >= square_off:
                return {"exit": float(m["open"]), "exit_time": hhmm, "reason": "SQUARE OFF"}
            hi, lo = float(m["high"]), float(m["low"])
            if stop_mode == "touch" and (lo <= sl if long else hi >= sl):
                return {"exit": sl, "exit_time": hhmm, "reason": "STOP"}
            if (hi >= target) if long else (lo <= target):
                return {"exit": target, "exit_time": hhmm, "reason": "TARGET"}
        if stop_mode == "close" and (b["close"] < sl if long else b["close"] > sl):
            return {"exit": b["close"], "exit_time": b["minutes"][-1]["timestamp"][11:16],
                    "reason": "STOP"}
    last = bars[-1]
    return {"exit": last["close"], "exit_time": last["minutes"][-1]["timestamp"][11:16],
            "reason": "EOD"}


def _option_leg(info: dict, entry_hhmm: str, exit_hhmm: str | None) -> dict:
    """Premium fields for one exit variant.

    pnl_rs is None with opt_reason set when the contract or its candles could
    not be had.  Such a trade STAYS in the table and is simply left out of the
    money totals - dropping it would quietly shrink the sample.
    """
    if info["reason"]:
        return {"entry_px": None, "exit_px": None, "prem_pts": None,
                "pnl_rs": None, "win": None, "opt_reason": info["reason"]}
    o = CachedPricer.price_from(info, entry_hhmm, exit_hhmm)
    prem = o["prem_pts"]
    return {"entry_px": o["entry_px"], "exit_px": o["exit_px"], "prem_pts": prem,
            "pnl_rs": None if prem is None else round(prem * LOT_SIZE, 2),
            "win": None if prem is None else prem > 0,
            "opt_reason": o["reason"]}


def simulate_day(day: str, minutes: list[dict], pdc: float, *,
                 gap_pct: float, scan_from: str, scan_to: str,
                 square_off: str, rr_values: list[float],
                 stop_modes: list[str]) -> dict:
    """Run the 5-step rule on one session, long or short.  Always returns a row."""
    row: dict = {"date": day, "pdc": round(pdc, 2), "status": "", "gap_pct": None,
                 "met": False, "side": None, "ex": {k: {} for k in stop_modes}}

    bars = build_buckets(minutes)
    if not bars or bars[0]["start"] != OPEN_TIME:
        row["status"] = "no data"
        return row

    # ---- Step 1: which side, if any -------------------------------------
    day_open = bars[0]["open"]
    gap = (day_open - pdc) / pdc * 100.0          # signed: + gap up, - gap down
    row["open"] = round(day_open, 2)
    row["gap_pct"] = round(gap, 3)
    if gap >= gap_pct:
        side = "LONG"
    elif gap <= -gap_pct:
        side = "SHORT"
    else:
        row["status"] = "no gap"
        return row
    row["side"] = side

    # ---- Step 2: the level and the trigger candle -----------------------
    or_high, or_low = bars[0]["high"], bars[0]["low"]
    row["or_high"], row["or_low"] = round(or_high, 2), round(or_low, 2)
    level = or_high if side == "LONG" else or_low
    row["level"] = round(level, 2)

    idx = None
    for i, b in enumerate(bars):
        if b["start"] < scan_from or b["start"] > scan_to:
            continue
        if (b["close"] > level) if side == "LONG" else (b["close"] < level):
            idx = i
            break
    if idx is None:
        row["status"] = "no breakout" if side == "LONG" else "no breakdown"
        return row
    cn = bars[idx]
    if idx + 1 >= len(bars):
        row["status"] = "no entry candle"
        return row
    nxt = bars[idx + 1]

    # ---- Steps 3 and 4: stop and risk -----------------------------------
    entry = nxt["open"]
    sl = cn["low"] if side == "LONG" else cn["high"]
    risk = (entry - sl) if side == "LONG" else (sl - entry)
    row.update({
        "breakout": cn["start"], "breakout_close": round(cn["close"], 2),
        "entry_time": nxt["start"], "entry": round(entry, 2),
        "sl": round(sl, 2), "risk": round(risk, 2),
    })
    if risk <= 0:
        row["status"] = "entry at/through SL"
        return row

    # ---- Step 5: the same trade at every RR, under both stop rules ------
    row["status"] = "trade"
    row["met"] = True
    opt_info = PRICER.day_prices(day, side, entry)
    row["strike"] = opt_info["strike"]
    row["opt_type"] = opt_info["option_type"]
    row["opt_symbol"] = opt_info["symbol"]
    for mode in stop_modes:
        for r in rr_values:
            target = entry + risk * r if side == "LONG" else entry - risk * r
            res = walk(bars, idx + 1, entry, sl, target, square_off, mode, side)
            pts = (res["exit"] - entry) if side == "LONG" else (entry - res["exit"])
            row["ex"][mode][rr_label(r)] = {
                "target": round(target, 2), "exit": round(res["exit"], 2),
                "exit_time": res["exit_time"], "reason": res["reason"],
                "points": round(pts, 2), "r_multiple": round(pts / risk, 3),
                # how far the fill landed beyond the stop level - 0 unless the
                # close-confirmed stop overshot it
                "slip": (round(abs(res["exit"] - sl), 2)
                         if res["reason"] == "STOP" else 0.0),
                **_option_leg(opt_info, row["entry_time"], res["exit_time"]),
            }

    return row


# ---------------------------------------------------------------------------
# Aggregation — the same numbers the reversal reports carry, nothing extra
# ---------------------------------------------------------------------------

def summarise(trades: list[dict], mode: str, key: str) -> dict:
    """`trades` are day rows; score them under stop rule `mode` at R:R `key`."""
    rows = [t["ex"][mode][key] for t in trades]
    n = len(rows)
    if not n:
        return {"days": 0, "trades": 0, "priced": 0, "unpriced": 0, "wins": 0,
                "losses": 0, "win_rate": 0.0, "pnl_prem": 0.0,
                "pnl_pts": 0.0, "pnl_rs": 0.0, "stops": 0, "slip": 0.0}
    # Wins and rupees follow the PREMIUM - that is what the account sees.
    # pnl_pts stays the spot move, which is what R is measured on.
    priced = [x for x in rows if x.get("prem_pts") is not None]
    wins = [x for x in priced if x["prem_pts"] > 0]
    pts = sum(x["points"] for x in rows)
    prem = sum(x["prem_pts"] for x in priced)
    np_ = len(priced)
    return {
        "days": len({t["date"] for t in trades}), "trades": n,
        "priced": np_, "unpriced": n - np_,
        "wins": len(wins), "losses": np_ - len(wins),
        "win_rate": round(len(wins) / np_ * 100, 1) if np_ else 0.0,
        "pnl_prem": round(prem, 2),
        "pnl_pts": round(pts, 2), "pnl_rs": round(prem * LOT_SIZE, 2),
        "stops": len([x for x in rows if x["reason"] == "STOP"]),
        "slip": round(sum(x["slip"] for x in rows), 2),
    }


def group_by(trades: list[dict], mode: str, key: str, keyfn) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        buckets[keyfn(t)].append(t)
    return [{"key": k, **summarise(v, mode, key)} for k, v in sorted(buckets.items())]


def week_key(t: dict) -> str:
    d = date.fromisoformat(t["date"])
    return (d - timedelta(days=d.weekday())).isoformat()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

async def run(args) -> None:
    candles = await load_nifty(args.offline, args.from_date, args.to_date)
    by_day = index_by_day(candles)
    days = sorted(d for d in by_day
                  if args.from_date.isoformat() <= d <= args.to_date.isoformat())
    if not days:
        raise RuntimeError("No sessions in the requested window.")

    # PDC basis - see PDC_MODES.  The daily feed is loaded either way so the
    # report can show both numbers side by side and the choice stays visible.
    daily_close = await load_daily(args.offline, args.from_date, args.to_date)
    dd = sorted(daily_close)
    official_prev = {d: daily_close[dd[i - 1]] for i, d in enumerate(dd) if i}
    sess = sorted(by_day)
    last1m_prev = {d: float(by_day[sess[i - 1]][-1]["close"])
                   for i, d in enumerate(sess) if i}
    prev_close = official_prev if args.pdc == "daily" else last1m_prev

    rr_values = args.rr_values
    labels = [rr_label(r) for r in rr_values]
    stop_modes = [k for k, _ in STOP_MODES]

    # ---- two passes, and the order is the whole point --------------------
    # Pass 1 runs the rule on SPOT alone: the gap, the opening range, the
    # breakout candle, the stop and the target are all decided there.  Only
    # then are the ATM contracts those signals imply resolved and fetched, so
    # the option can never move a level or change which trades exist - it only
    # puts a rupee figure on a result the underlying already determined.
    global PRICER

    def _spot_only(d):
        return simulate_day(
            d, by_day[d], prev_close[d], gap_pct=args.gap, scan_from=args.scan_from,
            scan_to=args.scan_to, square_off=args.square_off, rr_values=rr_values,
            stop_modes=stop_modes)

    needs = {(r["date"], r.get("side", "LONG"), r["entry"])
             for r in (_spot_only(d) for d in days if d in prev_close)
             if r.get("status") == "trade"}
    PRICER = await ensure_cached(
        needs, None if args.offline else _read_access_token(), args.offline)

    rows = []
    for d in days:
        if d not in prev_close:
            rows.append({"date": d, "status": "no PDC", "gap_pct": None,
                         "met": False, "ex": {k: {} for k in stop_modes}})
            continue
        row = simulate_day(
            d, by_day[d], prev_close[d], gap_pct=args.gap, scan_from=args.scan_from,
            scan_to=args.scan_to, square_off=args.square_off, rr_values=rr_values,
            stop_modes=stop_modes)
        # the reading NOT used, so a day sitting on the threshold is visible
        alt = last1m_prev if args.pdc == "daily" else official_prev
        if d in alt and row.get("open") is not None:
            row["pdc_alt"] = round(alt[d], 2)
            row["gap_pct_alt"] = round((row["open"] - alt[d]) / alt[d] * 100.0, 3)
        rows.append(row)

    trades = sorted([r for r in rows if r["status"] == "trade"], key=lambda r: r["date"])

    by_view = {
        "both": trades,
        "long": [t for t in trades if t["side"] == "LONG"],
        "short": [t for t in trades if t["side"] == "SHORT"],
    }
    summaries = {view: {mode: {lab: {
        "overall": summarise(rows_v, mode, lab),
        "daily": group_by(rows_v, mode, lab, lambda t: t["date"]),
        "weekly": group_by(rows_v, mode, lab, week_key),
        "monthly": group_by(rows_v, mode, lab, lambda t: t["date"][:7]),
    } for lab in labels} for mode in stop_modes}
        for view, rows_v in by_view.items()}

    # 1-minute candles for the chart: the previous session AND the trade day, so
    # the gap itself is visible.  Each candle carries a session flag,
    # 0 = previous day, 1 = trade day.
    sessions = sorted(by_day)

    def minute_rows(day: str, flag: int) -> list:
        return [[c["timestamp"][11:16], float(c["open"]), float(c["high"]),
                 float(c["low"]), float(c["close"]), flag]
                for c in by_day[day]
                if OPEN_TIME <= c["timestamp"][11:16] <= DAY_END]

    chart_days = {}
    for t in trades:
        i = sessions.index(t["date"])
        prev_day = sessions[i - 1] if i else None
        chart_days[t["date"]] = {
            "prev_date": prev_day,
            "pdc": t["pdc"],
            "candles": (minute_rows(prev_day, 0) if prev_day else []) +
                       minute_rows(t["date"], 1),
        }

    payload = {
        "meta": {
            "from": days[0], "to": days[-1], "sessions": len(days),
            "gap": args.gap, "rr_values": labels, "default_rr": rr_label(args.default_rr),
            "pdc_mode": args.pdc, "pdc_label": dict(PDC_MODES)[args.pdc],
            "stop_modes": [{"key": k, "label": v} for k, v in STOP_MODES],
            "default_stop": args.stop_mode,
            "sides": [{"key": k, "label": v} for k, v in SIDES],
            "default_side": args.side,
            "long_days": len(by_view["long"]), "short_days": len(by_view["short"]),
            "scan_from": args.scan_from, "scan_to": args.scan_to,
            "square_off": args.square_off, "lot": LOT_SIZE, "bucket": BUCKET,
            "generated": date.today().isoformat(),
        },
        "summaries": summaries,
        "days": rows,
        "chart_days": chart_days,
    }

    write_report(payload, args.out)
    print(f"\n{len(days)} sessions | trades {len(trades)} "
          f"(long {len(by_view['long'])}, short {len(by_view['short'])})")
    for view in ("both", "long", "short"):
        print(f"  {view}")
        for mode in stop_modes:
            for lab in labels:
                o = summaries[view][mode][lab]["overall"]
                print(f"    stop {mode:<5} {lab}: {o['wins']}W/{o['losses']}L  "
                      f"win {o['win_rate']:>5}%  {o['pnl_pts']:>8} pts  "
                      f"Rs {o['pnl_rs']:>9,.0f}  stops {o['stops']}  slip {o['slip']}")
    print(f"Report: {args.out}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NIFTY Gap Breakout long + short __FROM__ to __TO__</title>
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
  table.matrix tr[data-rr] { cursor:pointer; }
  table.matrix td.sel { outline:2px solid var(--accent); outline-offset:-2px; }
</style>
</head>
<body>

<h1>NIFTY Gap Breakout &mdash; long <span class="dim">and</span> short
  <span class="dim" style="font-size:14px">&middot; gap &ge; __GAP__% &middot; cn __SCANF__&ndash;__SCANT__</span></h1>
<div class="sub">
  One rule, two mirrored directions. <b>Step 1</b> &mdash;
  Gap% = (Open &minus; PDC) / PDC &times; 100: <b>&ge; +__GAP__%</b> makes the day a
  <b class="pos">LONG</b> day, <b>&le; &minus;__GAP__%</b> a <b class="neg">SHORT</b> day,
  anything between is skipped. <b>Step 2</b> &mdash; the first 15-minute candle
  (09:15&ndash;09:29) sets the level: its <b>high</b> for longs, its <b>low</b> for shorts;
  the first candle <b>cn</b> between <b>__SCANF__</b> and <b>__SCANT__</b> that <b>closes
  beyond</b> that level is the trigger, and the trade is taken at the <b>open of cn+1</b>.
  <b>Step 3</b> &mdash; stop is <b>cn's low</b> for longs, <b>cn's high</b> for shorts.
  <b>Step 4</b> &mdash; Risk = |Entry &minus; SL|. <b>Step 5</b> &mdash;
  Target = Entry + Risk &times; RR for longs, Entry &minus; Risk &times; RR for shorts.<br>
  A session is either a gap up or a gap down, never both, so the two sides never overlap and
  <b>Both</b> is simply every signal the rule produces. Squared off at __SQO__ if still open.
  PnL is in NIFTY points and in &#8377; for 1 lot (__LOT__); shorts are scored as
  Entry &minus; Exit.<br>
  <b>PDC is the previous session's official close</b> (daily candle), not the last 1-minute
  candle &mdash; the 1-minute feed ends at 15:29 and misses the closing print.
  A <b>close</b>-confirmed stop fills at the candle's close, so the loss is not capped at 1R;
  the <b>slip</b> column is how far past the stop level the fill landed. When one minute both
  touches the target and breaks the stop, the stop is taken first.<br>
  Range __FROM__ &rarr; __TO__ &middot; __NDAYS__ trading days.
</div>

<div class="card">
  <div class="tabrow"><span class="cap">Side</span><span id="tabsV" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow"><span class="cap">Stop rule</span><span id="tabsS" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow"><span class="cap">Risk : reward</span><span id="tabsR" style="display:flex;gap:6px;flex-wrap:wrap"></span></div>
  <div class="tabrow" style="margin-bottom:0"><span class="cap">Selected</span><span id="rrDesc" style="font-size:12.5px;color:var(--ink2)"></span></div>
</div>

<div class="card">
  <h2>Every side &times; stop rule &times; risk:reward</h2>
  <div class="ctrl dim" id="matrixNote"></div>
  <div class="scroll"><table class="matrix" id="matrix"></table></div>
</div>

<div class="card">
  <h2>Overall &mdash; <span id="ovV"></span>, <span id="ovS"></span>, RR = <span id="ovR"></span></h2>
  <div class="stat-row" id="overall"></div>
</div>

<div class="card">
  <h2>NIFTY 1-minute chart &mdash; previous session and trade day</h2>
  <div class="ctrl">
    <label for="daySel">Trade day</label>
    <select id="daySel"></select>
    <button class="btn" id="zoomIn">Zoom +</button>
    <button class="btn" id="zoomOut">Zoom &minus;</button>
    <button class="btn" id="zoomDay">Trade day only</button>
    <button class="btn" id="zoomReset">Both sessions</button>
    <span class="dim">wheel = zoom &middot; drag = pan &middot; double-click = reset</span>
    <span id="dayInfo" class="dim"></span>
  </div>
  <div class="chart-wrap"><svg id="chart" viewBox="0 0 1200 430"></svg><div id="tip"></div></div>
  <div class="legend">
    <span><i style="background:var(--warn)"></i>PDC &mdash; previous session close</span>
    <span><i style="background:var(--muted)"></i>First 15-minute high / low (the level)</span>
    <span><i style="background:var(--up)"></i>Target</span>
    <span><i style="background:var(--down)"></i>Stop &mdash; low of cn</span>
    <span><i style="background:var(--accent)"></i>Entry</span>
    <span>&#9670; Exit</span>
    <span class="dim">dimmed candles on the tinted band = previous session</span>
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
let curR = M.default_rr, curS = M.default_stop, curV = M.default_side;
const stopLabel = k => (M.stop_modes.find(m => m.key === k) || {}).label || k;
const stopShort = k => k === 'touch' ? 'Touch the SL level' : 'Close beyond the SL level';
const sideShort = k => k === 'long' ? 'Long only' : (k === 'short' ? 'Short only' : 'Both');
const sidePill = sd => sd === 'LONG'
  ? '<span class="pill long">BUY</span>' : '<span class="pill short">SELL</span>';

const n2 = v => (v===null||v===undefined||isNaN(v)) ? '&ndash;' : Number(v).toFixed(2);
const n0 = v => (v===null||v===undefined||isNaN(v)) ? '&ndash;' : Math.round(v).toLocaleString('en-IN');
const sgn = (v,d=2) => (v===null||v===undefined||isNaN(v)) ? '&ndash;'
      : `<span class="${v>0?'pos':(v<0?'neg':'dim')}">${v>0?'+':''}${Number(v).toFixed(d)}</span>`;
const sgnRs = v => (v===null||v===undefined||isNaN(v)) ? '&ndash;'
      : `<span class="${v>0?'pos':(v<0?'neg':'dim')}">${v>0?'+':''}${Math.round(v).toLocaleString('en-IN')}</span>`;

/* the day rows, flattened onto the selected stop rule + risk:reward */
function rowsFor(r, sm) {
  const m = sm || curS;
  return DATA.days.map(d => d.met ? Object.assign({}, d, d.ex[m][r]) : d)
                  .filter(d => inView(d));
}
/* A Long or Short view is a standalone strategy: every section of the report -
   stats, matrix, chart, day table, summaries - shows that side only.  Days the
   other side owns, and days that gapped neither way, are dropped entirely. */
function inView(d) {
  if (curV === 'both') return true;
  return d.side === (curV === 'long' ? 'LONG' : 'SHORT');
}
function tradesFor(r, sm) { return rowsFor(r, sm).filter(d => d.met); }
function S() { return DATA.summaries[curV][curS][curR]; }

/* ---------- tabs ---------- */
const tabsR = document.getElementById('tabsR'), tabsS = document.getElementById('tabsS'),
      tabsV = document.getElementById('tabsV');
M.sides.forEach(v => {
  const b = document.createElement('button');
  const n = DATA.summaries[v.key][M.default_stop][M.default_rr].overall.trades;
  b.className = 'tab' + (v.key === curV ? ' on' : '');
  b.dataset.vw = v.key;
  b.innerHTML = sideShort(v.key) + `<small>${n} trades</small>`;
  b.onclick = () => { curV = v.key; syncTabs(); renderAll(); };
  tabsV.appendChild(b);
});
M.stop_modes.forEach(m => {
  const b = document.createElement('button');
  b.className = 'tab' + (m.key === curS ? ' on' : '');
  b.dataset.sm = m.key;
  b.innerHTML = stopShort(m.key);
  b.onclick = () => { curS = m.key; syncTabs(); renderAll(); };
  tabsS.appendChild(b);
});
M.rr_values.forEach(v => {
  const b = document.createElement('button');
  b.className = 'tab' + (v === curR ? ' on' : '');
  b.dataset.rr = v;
  b.innerHTML = v;
  b.onclick = () => { curR = v; syncTabs(); renderAll(); };
  tabsR.appendChild(b);
});
function syncTabs() {
  [...tabsR.children].forEach(c => c.classList.toggle('on', c.dataset.rr === curR));
  [...tabsS.children].forEach(c => c.classList.toggle('on', c.dataset.sm === curS));
  [...tabsV.children].forEach(c => c.classList.toggle('on', c.dataset.vw === curV));
}

function table(el, head, rows, empty) {
  document.getElementById(el).innerHTML =
    '<thead><tr>' + head + '</tr></thead><tbody>' +
    (rows.join('') || `<tr><td class="dim" colspan="20">${empty||'no rows'}</td></tr>`) +
    '</tbody>';
}

/* ---------- matrix ---------- */
function renderMatrix() {
  let max = 1;
  const scope = curV === 'both' ? M.sides : M.sides.filter(v => v.key === curV);
  scope.forEach(v => M.stop_modes.forEach(m => M.rr_values.forEach(rr =>
    max = Math.max(max, Math.abs(DATA.summaries[v.key][m.key][rr].overall.pnl_rs)))));
  const head = '<th class="rh">Side</th><th class="rh">Stop rule</th>'
    + '<th class="rh">Risk : reward</th><th>Trade days</th><th>Trades</th><th>Success</th>'
    + '<th>Fail</th><th>Win rate</th><th>Stops</th><th>Slip past SL (pts)</th>'
    + '<th>Net PnL (&#8377;/lot)</th><th>Net PnL (NIFTY pts)</th>';
  const rows = [];
  /* Long -> the 8 long rows, Short -> the 8 short rows, Both -> everything,
     so "Both" literally shows the combined book next to long and short. */
  const shown = curV === 'both' ? M.sides : M.sides.filter(v => v.key === curV);
  shown.forEach(v => M.stop_modes.forEach(m => M.rr_values.forEach(rr => {
    const st = DATA.summaries[v.key][m.key][rr].overall;
    const a = (Math.abs(st.pnl_rs) / max * 0.5).toFixed(3);
    const bg = st.pnl_rs >= 0 ? `rgba(var(--upN),${a})` : `rgba(var(--downN),${a})`;
    const sel = (rr === curR && m.key === curS && v.key === curV) ? ' sel' : '';
    rows.push(`<tr data-rr="${rr}" data-sm="${m.key}" data-vw="${v.key}">`
      + `<td class="rh${sel}">${sideShort(v.key)}</td>`
      + `<td class="rh${sel}">${stopShort(m.key)}</td><td class="rh${sel}">${rr}</td>`
      + `<td>${st.days}</td><td>${st.trades}</td>`
      + `<td class="pos">${st.wins}</td><td class="neg">${st.losses}</td>`
      + `<td>${st.win_rate.toFixed(1)}%</td><td>${st.stops}</td>`
      + `<td class="${st.slip > 0 ? 'neg' : 'dim'}">${st.slip.toFixed(2)}</td>`
      + `<td class="${sel}" style="background:${bg}">${sgnRs(st.pnl_rs)}</td>`
      + `<td>${sgn(st.pnl_pts)}</td></tr>`);
  })));
  table('matrix', head, rows);
  document.querySelectorAll('#matrix tr[data-rr]').forEach(tr => {
    tr.onclick = () => {
      curR = tr.dataset.rr; curS = tr.dataset.sm; curV = tr.dataset.vw;
      syncTabs(); renderAll();
    };
  });
}

/* ---------- summaries ---------- */
function statBlock(s) {
  return [
    [s.days, 'trade days'], [s.trades, 'total trades'],
    [s.wins, 'success'], [s.losses, 'fail'],
    [s.win_rate.toFixed(1)+'%', 'win rate'],
    [(s.pnl_pts>0?'+':'')+s.pnl_pts.toFixed(2), 'NIFTY move (pts)'],
    [(s.pnl_prem>0?'+':'')+s.pnl_prem.toFixed(2), 'option premium (pts)'],
    [(s.pnl_rs>0?'+':'')+Math.round(s.pnl_rs).toLocaleString('en-IN'), 'net PnL (1 lot ₹, premium)'],
    [s.stops, 'stopped out'], [s.slip.toFixed(2), 'slip past SL (pts)'],
  ].map(([v,l]) => `<div class="stat"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
}

function summaryTable(el, rows, label) {
  const head = `<th>${label}</th><th class="num">Trade days</th><th class="num">Trades</th>
    <th class="num">Success</th><th class="num">Fail</th><th class="num">Win %</th>
    <th class="num">Net PnL (pts)</th><th class="num">Net PnL (₹)</th>`;
  table(el, head, rows.map(r => `<tr><td>${r.key}</td><td class="num">${r.days}</td>
    <td class="num">${r.trades}</td><td class="num pos">${r.wins}</td>
    <td class="num neg">${r.losses}</td><td class="num">${r.win_rate.toFixed(1)}%</td>
    <td class="num">${sgn(r.pnl_pts)}</td><td class="num">${sgnRs(r.pnl_rs)}</td></tr>`),
    'no trades');
}

/* ---------- day table ---------- */
function closePill(ct) {
  if (ct === 'TARGET') return '<span class="pill tgt">TARGET</span>';
  if (ct === 'STOP') return '<span class="pill sl">STOP</span>';
  if (ct === 'SQUARE OFF') return `<span class="pill eod">SQUARE OFF</span>`;
  return `<span class="pill no">${ct || '&ndash;'}</span>`;
}

function renderDays() {
  const only = document.getElementById('onlyTrades').checked;
  const rows = rowsFor(curR).filter(r => !only || r.met);
  const head = `<th>Date</th><th>Met</th><th>Trade</th><th class="num">PDC</th>
    <th class="num">Open</th><th class="num">Gap %</th><th class="num">Level</th>
    <th>Trigger cn</th><th class="num">cn close</th><th>Entry time</th>
    <th class="num">Entry</th><th class="num">Target</th><th class="num">Stop</th>
    <th class="num">Exit</th><th>Close type</th><th class="num">PnL (pts)</th>
    <th class="num">R</th><th>Contract</th><th class="num">Prem in</th>
    <th class="num">Prem out</th><th class="num">Prem pts</th>
    <th class="num">PnL (₹)</th><th>Exit time</th><th>Note</th>`;
  const body = rows.map(r => {
    if (!r.met) {
      return `<tr><td>${r.date}</td><td class="dim">no</td><td colspan="3" class="dim">&mdash;</td>
        <td class="num dim">${n2(r.gap_pct)}</td><td class="num dim">${n2(r.level)}</td>
        <td colspan="12" class="dim">&mdash;</td><td class="dim">${r.status}</td></tr>`;
    }
    return `<tr><td>${r.date}</td><td class="pos">yes</td>
      <td>${sidePill(r.side)}</td>
      <td class="num dim">${n2(r.pdc)}</td><td class="num dim">${n2(r.open)}</td>
      <td class="num ${r.side === 'LONG' ? 'pos' : 'neg'}">${n2(r.gap_pct)}</td>
      <td class="num dim">${n2(r.level)}</td>
      <td>${r.breakout}</td><td class="num dim">${n2(r.breakout_close)}</td>
      <td>${r.entry_time}</td><td class="num">${n2(r.entry)}</td>
      <td class="num dim">${n2(r.target)}</td><td class="num dim">${n2(r.sl)}</td>
      <td class="num">${n2(r.exit)}</td><td>${closePill(r.reason)}</td>
      <td class="num">${sgn(r.points)}</td><td class="num">${sgn(r.r_multiple,2)}</td>
      <td class="dim">${r.opt_symbol || '<span class="pill no">'+(r.opt_reason||'not priced')+'</span>'}</td>
      <td class="num dim">${n2(r.entry_px)}</td><td class="num dim">${n2(r.exit_px)}</td>
      <td class="num">${sgn(r.prem_pts)}</td>
      <td class="num">${r.pnl_rs===null||r.pnl_rs===undefined?'<span class="pill no">no option data</span>':sgnRs(r.pnl_rs)}</td>
      <td>${r.exit_time}</td>
      <td class="dim">risk ${n2(r.risk)} pts${r.slip > 0
        ? ` &middot; <span class="neg">filled ${n2(r.slip)} below SL</span>` : ''}</td></tr>`;
  });
  table('tblDays', head, body);
}

/* ---------- chart (zoom + pan) ---------- */
const W = 1200, H = 430, PADL = 8, PADR = 62, PADT = 14, PADB = 26;
const svg = document.getElementById('chart');
const tip = document.getElementById('tip');
let chartState = null;          // { c, r, i0, i1 }  i0..i1 = visible candle window

function viewFor(day) { return DATA.chart_days[day] || null; }

function clampWindow(n, i0, i1) {
  const MIN = 12;
  if (i1 - i0 < MIN) { const mid = (i0 + i1) / 2; i0 = mid - MIN/2; i1 = mid + MIN/2; }
  if (i1 - i0 > n)   { i0 = 0; i1 = n; }
  if (i0 < 0) { i1 -= i0; i0 = 0; }
  if (i1 > n) { i0 -= (i1 - n); i1 = n; }
  return [Math.max(0, i0), Math.min(n, i1)];
}

function drawChart() {
  if (!chartState) { svg.innerHTML = ''; return; }
  const { c, r, cd, split } = chartState;
  let [i0, i1] = [chartState.i0, chartState.i1];
  const view = c.slice(Math.floor(i0), Math.ceil(i1));
  if (!view.length) return;
  const lvls = [r.or_high, r.or_low, r.target, r.sl, cd.pdc].filter(v => v != null);
  let lo = Math.min(...view.map(x => x[3]), ...lvls);
  let hi = Math.max(...view.map(x => x[2]), ...lvls);
  const pad = (hi - lo) * 0.06 || 10; lo -= pad; hi += pad;

  const iw = W - PADL - PADR, ih = H - PADT - PADB;
  const span = i1 - i0;
  const x = i => PADL + (i - i0 + 0.5) * iw / span;
  const y = v => PADT + (hi - v) * ih / (hi - lo);
  const bw = Math.max(1.2, iw / span * 0.62);

  let s = '';
  /* the previous session sits on a tinted band so the two days never blur together */
  if (split > i0) {
    const x1 = PADL;
    const x2 = Math.min(PADL + iw, x(Math.min(split, i1)) - bw / 2);
    if (x2 > x1) s += `<rect x="${x1.toFixed(1)}" y="${PADT}" width="${(x2-x1).toFixed(1)}" `
                    + `height="${ih}" fill="rgba(127,127,127,.07)"/>`;
  }
  for (let k = 0; k <= 6; k++) {
    const v = lo + (hi - lo) * k / 6, yy = y(v);
    s += `<line x1="${PADL}" y1="${yy}" x2="${PADL+iw}" y2="${yy}" stroke="var(--grid)"/>`
       + `<text x="${PADL+iw+6}" y="${yy+3.5}" font-size="10" fill="var(--muted)">${v.toFixed(0)}</text>`;
  }
  const step = Math.max(1, Math.round(span / 10));
  for (let i = Math.ceil(i0); i < i1; i++) {
    if ((i - Math.ceil(i0)) % step) continue;
    s += `<text x="${x(i)}" y="${H-8}" font-size="10" fill="var(--muted)" text-anchor="middle">${c[i][0]}</text>`
       + `<line x1="${x(i)}" y1="${PADT}" x2="${x(i)}" y2="${PADT+ih}" stroke="var(--grid)" opacity=".55"/>`;
  }
  for (let i = Math.floor(i0); i < Math.ceil(i1) && i < c.length; i++) {
    const [tm, o, h, l, cl, flag] = c[i];
    const col = cl >= o ? 'var(--up)' : 'var(--down)';
    const yo = y(o), yc = y(cl);
    const op = flag ? 1 : 0.45;                 /* previous session is dimmed */
    s += `<line x1="${x(i).toFixed(2)}" y1="${y(h).toFixed(2)}" x2="${x(i).toFixed(2)}" y2="${y(l).toFixed(2)}" stroke="${col}" opacity="${op}"/>`
       + `<rect x="${(x(i)-bw/2).toFixed(2)}" y="${Math.min(yo,yc).toFixed(2)}" width="${bw.toFixed(2)}" height="${Math.max(1,Math.abs(yc-yo)).toFixed(2)}" fill="${col}" opacity="${op}"/>`;
  }
  /* session divider + both session labels */
  if (split > i0 && split < i1) {
    const sx = x(split) - bw / 2;
    s += `<line x1="${sx}" y1="${PADT}" x2="${sx}" y2="${PADT+ih}" stroke="var(--ink2)" stroke-width="1.2"/>`
       + `<text x="${sx-5}" y="${PADT+12}" font-size="10" fill="var(--muted)" text-anchor="end">${cd.prev_date} &middot; previous</text>`
       + `<text x="${sx+5}" y="${PADT+12}" font-size="10" font-weight="600" fill="var(--ink2)">${chartState.day} &middot; trade day</text>`;
  }
  const hline = (v, col, dash, label, atEnd) => v == null ? '' :
    `<line x1="${PADL}" y1="${y(v)}" x2="${PADL+iw}" y2="${y(v)}" stroke="${col}" stroke-width="1.4" stroke-dasharray="${dash}" opacity=".9"/>`
    + `<text x="${atEnd ? PADL+iw-4 : PADL+4}" y="${y(v)-4}" font-size="10" fill="${col}"`
    + `${atEnd ? ' text-anchor="end"' : ''}>${label} ${v.toFixed(2)}</text>`;
  s += hline(cd.pdc,    'var(--warn)',  '2 4', 'PDC', true);
  s += hline(r.or_high, 'var(--muted)', '4 3',
             r.side === 'LONG' ? '15m high (level)' : '15m high');
  s += hline(r.or_low,  'var(--muted)', '4 3',
             r.side === 'SHORT' ? '15m low (level)' : '15m low');
  s += hline(r.target,  'var(--up)',    '6 3', 'Target');
  s += hline(r.sl,      'var(--down)',  '6 3', 'Stop');

  const ei = c.findIndex(q => q[5] === 1 && q[0] === r.entry_time);
  if (ei >= 0 && ei >= i0 - 1 && ei <= i1) {
    const ex = x(ei), ey = y(r.entry);
    s += `<line x1="${ex}" y1="${PADT}" x2="${ex}" y2="${PADT+ih}" stroke="var(--accent)" stroke-width="1.2" stroke-dasharray="3 3"/>`
       + (r.side === 'LONG'
          ? `<polygon points="${ex},${ey} ${ex-6},${ey+12} ${ex+6},${ey+12}" fill="var(--accent)"/>`
          : `<polygon points="${ex},${ey} ${ex-6},${ey-12} ${ex+6},${ey-12}" fill="var(--accent)"/>`)
       + `<text x="${ex+9}" y="${ey + (r.side === 'LONG' ? 16 : -16)}" font-size="11" font-weight="600" fill="var(--accent)">${r.side === 'LONG' ? 'BUY' : 'SELL'} @ ${r.entry.toFixed(2)}</text>`;
  }
  const xi = c.findIndex(q => q[5] === 1 && q[0] === r.exit_time);
  if (xi >= 0 && xi >= i0 - 1 && xi <= i1) {
    const xx = x(xi), xy = y(r.exit), col = r.points > 0 ? 'var(--up)' : 'var(--down)';
    s += `<polygon points="${xx},${xy-7} ${xx+7},${xy} ${xx},${xy+7} ${xx-7},${xy}" fill="${col}" stroke="var(--surface)" stroke-width="1.2"/>`
       + `<text x="${xx+11}" y="${xy+4}" font-size="11" font-weight="600" fill="${col}">${r.reason} @ ${r.exit.toFixed(2)}</text>`;
  }
  const a = c[Math.floor(i0)], b = c[Math.min(c.length-1, Math.ceil(i1)-1)];
  s += `<text x="${PADL+iw-2}" y="${H-8}" font-size="10" fill="var(--muted)" text-anchor="end">`
     + `${a[5]?'':'prev '}${a[0]} &ndash; ${b[5]?'':'prev '}${b[0]} &middot; ${Math.round(i1-i0)} min</text>`;
  svg.innerHTML = s;
}

function renderChart() {
  const day = document.getElementById('daySel').value;
  const info = document.getElementById('dayInfo');
  const cd = viewFor(day);
  const r = tradesFor(curR).find(x => x.date === day);
  if (!cd || !r) { chartState = null; svg.innerHTML = ''; info.textContent = ''; return; }
  const c = cd.candles;
  const sp = c.findIndex(q => q[5] === 1);
  const keep = chartState && chartState.day === day
    ? [chartState.i0, chartState.i1] : [0, c.length];
  chartState = { day, c, r, cd, split: sp < 0 ? 0 : sp, i0: keep[0], i1: keep[1] };
  [chartState.i0, chartState.i1] = clampWindow(c.length, keep[0], keep[1]);
  drawChart();
  info.innerHTML = `${sidePill(r.side)} &middot; PDC ${n2(cd.pdc)} &rarr; open ${n2(r.open)}`
    + ` = gap ${n2(r.gap_pct)}% &middot; cn ${r.breakout} &middot; entry ${r.entry_time} @ ${n2(r.entry)}`
    + ` &rarr; exit ${r.exit_time} @ ${n2(r.exit)} &middot; ${sgn(r.points)} pts (${sgnRs(r.pnl_rs)})`;
}

function zoomAt(factor, anchor) {
  if (!chartState) return;
  const { c } = chartState;
  let { i0, i1 } = chartState;
  const a = anchor === undefined ? (i0 + i1) / 2 : anchor;
  [chartState.i0, chartState.i1] =
    clampWindow(c.length, a - (a - i0) * factor, a + (i1 - a) * factor);
  drawChart();
}

svg.addEventListener('wheel', e => {
  if (!chartState) return;
  e.preventDefault();
  const box = svg.getBoundingClientRect();
  const px = (e.clientX - box.left) / box.width * W;
  const { i0, i1 } = chartState;
  const anchor = i0 + (px - PADL) / (W - PADL - PADR) * (i1 - i0);
  zoomAt(e.deltaY < 0 ? 0.82 : 1.22, anchor);
}, { passive: false });

let drag = null;
svg.addEventListener('pointerdown', e => {
  if (!chartState) return;
  drag = { x: e.clientX, i0: chartState.i0, i1: chartState.i1 };
  svg.classList.add('drag'); svg.setPointerCapture(e.pointerId);
});
svg.addEventListener('pointerup', e => {
  drag = null; svg.classList.remove('drag');
  try { svg.releasePointerCapture(e.pointerId); } catch (_) {}
});
svg.addEventListener('dblclick', () => resetZoom());
function resetZoom() {
  if (!chartState) return;
  chartState.i0 = 0; chartState.i1 = chartState.c.length; drawChart();
}
function zoomTradeDay() {
  if (!chartState) return;
  [chartState.i0, chartState.i1] =
    clampWindow(chartState.c.length, chartState.split, chartState.c.length);
  drawChart();
}
document.getElementById('zoomIn').onclick = () => zoomAt(0.7);
document.getElementById('zoomOut').onclick = () => zoomAt(1.4);
document.getElementById('zoomReset').onclick = resetZoom;
document.getElementById('zoomDay').onclick = zoomTradeDay;

svg.addEventListener('pointermove', e => {
  if (!chartState) return;
  const box = svg.getBoundingClientRect();
  const { c } = chartState;
  if (drag) {
    const dx = (e.clientX - drag.x) / box.width * W;
    const perPx = (drag.i1 - drag.i0) / (W - PADL - PADR);
    [chartState.i0, chartState.i1] =
      clampWindow(c.length, drag.i0 - dx * perPx, drag.i1 - dx * perPx);
    drawChart();
    tip.style.display = 'none';
    return;
  }
  const px = (e.clientX - box.left) / box.width * W;
  const { i0, i1 } = chartState;
  const i = Math.round(i0 + (px - PADL) / (W - PADL - PADR) * (i1 - i0) - 0.5);
  if (i < 0 || i >= c.length) { tip.style.display = 'none'; return; }
  const [tm, o, h, l, cl, flag] = c[i];
  const dlab = flag ? chartState.day : (chartState.cd.prev_date + ' \u00b7 prev');
  tip.innerHTML = `<b>${tm}</b> <span style="opacity:.6">${dlab}</span><br>O ${o.toFixed(2)}<br>H ${h.toFixed(2)}<br>L ${l.toFixed(2)}<br>C ${cl.toFixed(2)}`;
  tip.style.display = 'block';
  tip.style.left = Math.min(e.clientX - box.left + 14, box.width - 110) + 'px';
  tip.style.top = Math.max(0, e.clientY - box.top - 60) + 'px';
});
svg.addEventListener('pointerleave', () => { tip.style.display = 'none'; });

/* ---------- orchestration ---------- */
function renderAll() {
  const sm = S();
  document.getElementById('ovR').textContent = curR;
  document.getElementById('ovS').textContent = stopShort(curS);
  document.getElementById('ovV').textContent = sideShort(curV);
  document.getElementById('rrDesc').innerHTML =
    `${(M.sides.find(v => v.key === curV) || {}).label}. Stop: ${stopLabel(curS)}. `
    + `Target = Entry ${curV === 'short' ? '&minus;' : '&plusmn;'} Risk &times; `
    + `${curR.split(':')[1]}, taken on touch.`;
  document.getElementById('overall').innerHTML = statBlock(sm.overall);
  document.getElementById('matrixNote').innerHTML = curV === 'both'
    ? 'Both sides together, then each side on its own &mdash; long and short are disjoint sets '
      + 'of days, so Both is their union. Click any row to select it.'
    : `${sideShort(curV)}: the same ${sm.overall.trades} entries in all eight rows, only the `
      + 'exit changes. Click any row to select it.';
  renderMatrix();

  const sel = document.getElementById('daySel');
  const prev = sel.value;
  const days = tradesFor(curR).map(r => r.date);
  sel.innerHTML = days.map(d => `<option value="${d}">${d}</option>`).join('');
  if (days.includes(prev)) sel.value = prev;
  renderChart();

  renderDays();
  summaryTable('tblDaily', sm.daily, 'Date');
  summaryTable('tblWeekly', sm.weekly, 'Week of');
  summaryTable('tblMonthly', sm.monthly, 'Month');
}
document.getElementById('daySel').addEventListener('change', () => {
  if (chartState) chartState.day = null;   // new day -> full view
  renderChart();
});
document.getElementById('onlyTrades').addEventListener('change', renderDays);
renderAll();
</script>
</body>
</html>
"""


def write_report(payload: dict, out_path: str) -> None:
    m = payload["meta"]
    html = (HTML_TEMPLATE
            .replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":")))
            .replace("__GAP__", f"{m['gap']:g}")
            .replace("__SCANF__", m["scan_from"])
            .replace("__SCANT__", m["scan_to"])
            .replace("__SQO__", m["square_off"])
            .replace("__BUCKET__", str(m["bucket"]))
            .replace("__LOT__", str(m["lot"]))
            .replace("__NDAYS__", str(m["sessions"]))
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
    ap.add_argument("--gap", type=float, default=GAP_PCT, help="step 1 threshold in %%")
    ap.add_argument("--rr", dest="rr_values", type=float, nargs="+", default=RR_VALUES,
                    metavar="R", help="reward:risk multiples to compare (default 2 3 4 5)")
    ap.add_argument("--default-rr", type=float, default=DEFAULT_RR,
                    help="risk:reward selected when the report opens")
    ap.add_argument("--side", choices=[k for k, _ in SIDES], default=DEFAULT_SIDE,
                    help="view selected when the report opens; all three are always computed")
    ap.add_argument("--stop-mode", choices=[k for k, _ in STOP_MODES], default=DEFAULT_STOP,
                    help="stop rule selected when the report opens; both are always computed")
    ap.add_argument("--scan-from", default=SCAN_FROM)
    ap.add_argument("--scan-to", default=SCAN_TO)
    ap.add_argument("--square-off", default=SQUARE_OFF)
    ap.add_argument("--offline", action="store_true", help="use local caches only")
    ap.add_argument("--pdc", choices=[k for k, _ in PDC_MODES], default=DEFAULT_PDC,
                    help="which previous close the gap is measured against "
                         "(default: the official daily close)")
    ap.add_argument("--out", default=REPORT_HTML)
    ap.add_argument("--from", dest="from_date", type=date.fromisoformat,
                    default=today - timedelta(days=183), help="default: 6 months back")
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat, default=today)
    args = ap.parse_args()
    if args.default_rr not in args.rr_values:
        args.default_rr = args.rr_values[0]
    os.makedirs(REPORTS_DIR, exist_ok=True)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
