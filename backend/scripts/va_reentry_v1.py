"""Value-area RE-ENTRY - price fails outside value, falls back in, and goes on.

THE RULE
--------
  1  Build the fixed-range volume profile (POC, VAH, VAL).
  2  On 5-minute candles, profile the PREVIOUS day in full.  Extend the three
     lines into the current day.
  3  Do not care where the previous session closed.
  3A Price is ABOVE the VAH.  A candle closes back BELOW it.  After 4-7 candles
     price retests the VAH from underneath and it HOLDS as resistance ->
     enter SHORT, back into the value area.
     SL 25 points above the VAH.  Target = risk x 2.
  3B Price is BELOW the VAL.  A candle closes back ABOVE it.  After 4-7 candles
     price retests the VAL from above and it HOLDS as support -> enter LONG,
     back into the value area.
     SL 25 points below the VAL.  Target = risk x 2.

This is the MIRROR of va_retest_v1, which trades price LEAVING value.  In
market-profile terms this is the failed auction: price tried to leave, could
not, and is returning - and the classical claim is that a re-entry tends to
traverse value toward the far side.  The two files are opposite bets on the same
three lines, run on the same profile, the same exits and the same pricing, so
the difference between them is the rule and nothing else.

A BREAK IS A CROSSING, NOT A POSITION.  The candle before the break must have
CLOSED outside the band.  Without that, every candle drifting around inside
value arms the rule and the "re-entry" is not an entry at all.


WHAT IT MEASURED - 245 sessions, and it does NOT beat va_retest_v1
------------------------------------------------------------------
    rule                        tf     n   /wk     avgR       t
    va_retest_v1 (leave value)   5   109   2.2   +0.239   +1.76
    THIS FILE    (re-enter)      5    55   1.1   -0.092   -0.53
    va_retest_v1 (leave value)   3   123   2.5   +0.152   +1.21
    THIS FILE    (re-enter)      3    73   1.5   +0.186   +1.13

Worse on 5-minute, marginally better on 3-minute, and it fires half as often.
Leaving value beats re-entering it, which is the same direction as the earlier
break-and-reclaim versus break-and-retest result.

THE TWO SIDES ARE NOT THE SAME RULE.  Against a SAME-SIDE random control over
the same window - which matters, because NIFTY fell 2135 points here and 300
random books give short-only +0.039 against long-only -0.115 - the split is:

    SHORT (VAH re-entry)   +0.490 - (+0.039) = +0.451   on 21 trades
    LONG  (VAL re-entry)   -0.451 - (-0.115) = -0.336   worse than a random long

The short half is the best drift-adjusted cell in this whole study and the long
half is genuinely bad.  Twenty-one trades is roughly 0.4 a week, far too thin to
act on and one cell among many that were examined, so --view short is available
but nothing here recommends it.

ALWAYS COMPARE A SIDE AGAINST A SAME-SIDE CONTROL, never against zero, on a
window with a directional tilt.  Comparing against zero is what made this
rule's short half - and va_retest_v1's - look better than it is.


EVERYTHING ELSE MATCHES va_retest_v1
-------------------------------------
Entry is the OPEN of the candle after the confirming close, because the
confirmation is a close and that candle cannot be traded at its own open.
Exits walk on 1-MINUTE candles whatever the signal timeframe; within a minute
the order is square-off, then stop, then target, so a minute spanning both is a
loss.  One trade per session by default.  The profile is TIME-weighted because
the NIFTY index reports no volume on any endpoint - see services/market_profile.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SCRIPT_DIR, "..")
sys.path.insert(0, BACKEND_DIR)

from services.upstox_client import INSTRUMENT_KEYS, get_candles  # noqa: E402
from services.option_pricing import (  # noqa: E402
    CachedPricer, ensure_cached, ROLL_MODES)
from services.market_profile import (  # noqa: E402
    build_profile, ProfileDataError, WEIGHTS, WEIGHT_KEYS,
    DEFAULT_ROW_SIZE, DEFAULT_VALUE_AREA)

DATA_DIR = os.path.join(BACKEND_DIR, "data")
REPORTS_DIR = os.path.join(BACKEND_DIR, "reports")
RESULTS_DIR = os.path.join(BACKEND_DIR, "results")
CONFIG_FILE = os.path.join(BACKEND_DIR, "upstox_config.txt")
REPORT_HTML = os.path.join(REPORTS_DIR, "va_reentry_v1_report.html")
TRADES_CSV = os.path.join(RESULTS_DIR, "va_reentry_v1_trades.csv")

UNDERLYING = "NIFTY"
UNDERLYING_KEY = INSTRUMENT_KEYS[UNDERLYING]

# Scales the rupee columns and NOTHING else.  Every headline number in this
# report is a percentage of the premium paid or an R-multiple, both of which
# are lot-size independent and therefore comparable across variants.
LOT_SIZE = 65

# Step 2 says 5-minute.  3 is carried alongside it because a level rule that
# works on exactly one timeframe has not been demonstrated.  15-minute was
# dropped on 2026-09-17 at the user's request: it held 29-35 trades a year, its
# stop was pre-traded on 40-69% of them and its split-halves never agreed.
TIMEFRAMES = [3, 5]
DEFAULT_TF = 5
PROFILE_TF = 5                      # step 2, literally

# Step 3B/3C say 25 points inside the broken band, and that IS the spec here -
# unlike strategy 1, nothing about this stop was tuned on the sample.
SPEC_STOP_OFFSET = 25.0
SPEC_STOP_AT = "band"
STOP_OFFSET = 25.0
# The sweep still brackets the default on both sides so it is never read alone.
ENTRY_STOP_SWEEP = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0]
# Re-run at each of these so "just widen the stop" is answered with a book.
STOP_SWEEP = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0]
# 1:2 IS THE MINIMUM.  The user set the floor on 2026-09-18, so the 1:1 rung is
# gone: with a flat 25-point stop the smallest target this rule takes is 50
# points.  3 and 4 stay because a rule that only works at its own floor has not
# been shown to work.
RR_VALUES = [2.0, 3.0, 4.0]
MIN_RR = 2.0
DEFAULT_RR = 2.0                    # step 3 says 1:2, and it is now the floor

# A stop closer than this is noise: NIFTY ticks in 0.05 and a sub-point stop is
# taken out by the spread alone.  0 disables it.
MIN_RISK = 1.0

STOP_MODES = [("band", "Inside the broken band - the spec"),
              ("entry", "A fixed distance from the ENTRY price")]
DEFAULT_STOP = "band"
STOP_KEYS = [k for k, _ in STOP_MODES]
CONFIRMS = [("close", "The retest candle reaches the band and closes back inside"),
            ("touch", "The retest candle reaches the band; no close test"),
            ("two-candle", "A later candle closes inside after the touch"),
            ("reclaim", "Price CLOSES back outside the band, then fails and "
                        "closes inside again")]
# ACCEPTANCE: how many candles price must have CLOSED outside the band before
# the break counts.  1 is the loosest reading - a single candle outside - and is
# what "price traded above the VAH" means at its weakest.  Higher values demand
# that price was genuinely accepted out there before losing the level, which is
# what a trader usually means by the phrase.
DEFAULT_ACCEPTANCE = 1
DEFAULT_CONFIRM = "close"
WAIT_MIN, WAIT_MAX = 4, 7

ENTRY_MODES = [("next", "Open of the candle after the confirming close"),
               ("close", "The confirming candle's own close")]
DEFAULT_ENTRY = "next"
ENTRY_KEYS = [k for k, _ in ENTRY_MODES]

# This rule has no 3B/3C stop defect to reproduce - the spec it came from is the
# user's own sentence, not a written step - so there is one reading only.
LONG_READINGS = [("mirror", "SHORT stops above the VAH, LONG below the VAL")]
DEFAULT_LONG = "mirror"

# WHICH "PREVIOUS CLOSE" STEP 3 COMPARES AGAINST VALUE.
# `last` is the default, and the reason is consistency with the chart and with
# the profile.  VAL/POC/VAH are built from INTRADAY candles; comparing them to
# the official settlement close mixes two different sources, and the settlement
# close is not drawn anywhere on the chart the rule is read from.  Step 2 says
# to mark the previous day on 5-minute candles, so the close that step 3 means
# is the one the last of those candles prints.
#
# It is not a cosmetic choice.  The two disagree about the SETUP on 10.2% of
# sessions (median gap 8.5 points, max 85.7), and on 2025-10-01 the settlement
# close was 24611.10 - 3.9 points under a VAL of 24615 - while the 15:29 print
# was 24633.60, comfortably INSIDE value.  The rule fired on a number that was
# nowhere on the chart.  Spotted by the user on 2026-09-17.
PDC_BASES = [("last", "The 15:29 print - the close the chart actually shows"),
             ("daily", "The official settlement close from the daily feed")]
DEFAULT_PDC = "last"

# ONE TRADE PER SESSION.  `flow` re-entered whenever the setup re-armed, which
# put up to five trades on a single day and let one session dominate a month.
# The user asked for one day, one trade on 2026-09-17, so `session` is the only
# mode computed by default; --modes flow session brings the comparison back.
TRADE_MODES = [("session", "The first placeable entry of the day, then done"),
               ("flow", "One position at a time, re-entering whenever it re-arms")]
DEFAULT_MODE = "session"
DEFAULT_MODES = ["session"]

VIEWS = [("both", "Long and short together"),
         ("long", "Long trades only"),
         ("short", "Short trades only")]
DEFAULT_VIEW = "both"

EOD_MODES = [("close", "Square off at the session close time"),
             ("hold", "Run to stop or target, give up at the last candle")]
DEFAULT_EOD = "close"

# 0-DTE is where every catastrophic percentage loss in this repo's other books
# came from: an expiry-day ATM option is nearly all gamma.
DEFAULT_ROLL = "zero-dte"

SESSION_START = "09:15"
SQUARE_OFF = "15:15"
DAY_END = "15:29"


def rr_label(r: float) -> str:
    return f"1:{r:g}"


def rr_keys(rr_values: list[float]) -> list[str]:
    return [rr_label(r) for r in rr_values]


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
    """Reuse a wider cache in backend/data that already covers the window."""
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
    reused = _slice_existing_cache(from_date, to_date)
    if reused is not None:
        return reused
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
        except Exception as exc:                                  # noqa: BLE001
            print(f"  ! fetch failed ({exc}); falling back to the local caches.")
    raise RuntimeError(f"No data for {from_date} -> {to_date} and no usable cache.")


async def load_daily(offline: bool, from_date: date, to_date: date) -> dict[str, float]:
    """Session date -> OFFICIAL close, from the daily feed.

    Step 3 compares the previous close against VAL/VAH, so this decides which
    days have a setup at all.  The 1-minute feed's 15:29 print is NOT the
    official close, which is why --pdc-basis exists and why both are carried.
    """
    lookback = from_date - timedelta(days=15)
    # Only a file that actually COVERS the window is any use.
    best = None
    for name in sorted(os.listdir(DATA_DIR)):
        if not (name.startswith("nifty_1d_") and name.endswith(".json")):
            continue
        try:
            a, b = name[len("nifty_1d_"):-len(".json")].split("_")
            c_from, c_to = date.fromisoformat(a), date.fromisoformat(b)
        except ValueError:
            continue
        if c_from <= lookback and c_to >= to_date:
            span = (c_to - c_from).days
            if best is None or span < best[0]:
                best = (span, name)
    if best is not None:
        with open(os.path.join(DATA_DIR, best[1])) as f:
            raw = json.load(f)
        print(f"Loaded {len(raw)} NIFTY daily candles from {best[1]}")
        return {c["timestamp"][:10]: float(c["close"]) for c in raw}

    token = None if offline else _read_access_token()
    if token:
        try:
            raw = await get_candles(token, UNDERLYING_KEY, "1d", lookback, to_date)
            if raw:
                path = os.path.join(
                    DATA_DIR, f"nifty_1d_{lookback.isoformat()}_{to_date.isoformat()}.json")
                with open(path, "w") as f:
                    json.dump(raw, f)
                print(f"Fetched {len(raw)} daily candles.")
                return {c["timestamp"][:10]: float(c["close"]) for c in raw}
        except Exception as exc:                                  # noqa: BLE001
            print(f"  ! daily fetch failed ({exc})")
    print("  ! no daily candles; --pdc-basis daily will fall back to the 15:29 print.")
    return {}


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
# Bars
# ---------------------------------------------------------------------------

def session_minutes(minutes: list[dict], start: str = SESSION_START) -> list[dict]:
    """The regular session, as compact 1-minute bars."""
    out = []
    for c in minutes:
        hhmm = c["timestamp"][11:16]
        if start <= hhmm <= DAY_END:
            out.append({"t": hhmm,
                        "o": float(c["open"]), "h": float(c["high"]),
                        "l": float(c["low"]), "c": float(c["close"]),
                        "v": float(c.get("volume") or 0)})
    return out


def build_buckets(mins: list[dict], size: int) -> list[dict]:
    """Aggregate 1-minute bars into `size`-minute candles anchored at 09:15.

    Each bucket carries `mi0`/`mi1`, the index of its first and last minute in
    `mins`, because every entry and every exit is resolved on the 1-minute
    series even when the structure was read on 5-minute bars.
    """
    out: list[dict] = []
    cur = None
    key = None
    for i, m in enumerate(mins):
        h, mm = int(m["t"][:2]), int(m["t"][3:])
        off = (h * 60 + mm) - (9 * 60 + 15)
        k = off // size
        if k != key:
            if cur:
                out.append(cur)
            key = k
            cur = {"t": m["t"], "o": m["o"], "h": m["h"], "l": m["l"], "c": m["c"],
                   "v": m["v"], "mi0": i, "mi1": i}
        else:
            cur["h"] = max(cur["h"], m["h"])
            cur["l"] = min(cur["l"], m["l"])
            cur["c"] = m["c"]
            cur["v"] += m["v"]
            cur["mi1"] = i
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------------------
# Steps 1-2 - the previous session's profile, extended into today
# ---------------------------------------------------------------------------

def day_profile(prev_mins: list[dict], *, profile_tf: int, row_size: float,
                value_area: float, weight: str) -> dict | None:
    bars = build_buckets(prev_mins, profile_tf)
    if not bars:
        return None
    try:
        return build_profile(bars, row_size=row_size, value_area=value_area,
                             weight=weight)
    except ProfileDataError:
        return None


# ---------------------------------------------------------------------------
# Step 3 - the setup, and the confirmation
# ---------------------------------------------------------------------------

def setup_side(pdc: float, prof: dict) -> str | None:
    """This rule has no previous-close condition - step 3A says so explicitly.

    Kept so the report's day rows can still show where the previous session
    closed relative to value, which is useful context even though nothing in
    the rule depends on it.
    """
    if pdc < prof["val"]:
        return "below VAL"
    if pdc > prof["vah"]:
        return "above VAH"
    return "inside value"


def find_signals(bars: list[dict], mins: list[dict], *, vah: float, val: float,
                 wait_min: int, wait_max: int, confirm: str,
                 entry_until: str, acceptance: int = 1) -> tuple[list[dict], dict]:
    """Price is accepted outside a band, loses it, and the band turns on it.

    The sequence, for the VAH:

        price CLOSES above the VAH for `acceptance` candles   (traded above)
        a candle closes back BELOW the VAH                    (loses the level)
        the VAH is now resistance
        price comes back up to it and fails there             (retest)
        -> SHORT

    The VAL mirrors it exactly and produces a LONG.

    `acceptance` is the "traded above" part: at 1 a single candle outside is
    enough, which is the loosest reading; higher values require price to have
    been genuinely accepted out there before losing the level.

    `confirm` decides what "fails there" means:
      touch        the candle merely reaches the band again
      close        it reaches the band AND closes back inside  (default)
      two-candle   the touch and the closing-back-inside are separate candles
      reclaim      price CLOSES back outside the band first - a real reclaim -
                   and only then fails and closes inside.  This is the strictest
                   reading of "reclaims it, then retest, then confirmation".
    """
    out: list[dict] = []
    seen = {"broke": 0, "retested": 0, "held": 0}
    j = max(1, acceptance)
    while j < len(bars) - 1:
        b = bars[j]
        # ACCEPTED outside, then a close back inside - the level is lost
        above = all(bars[j - q]["c"] > vah for q in range(1, acceptance + 1))
        below = all(bars[j - q]["c"] < val for q in range(1, acceptance + 1))
        down = above and b["c"] < vah
        up = below and b["c"] > val
        if not (down or up):
            j += 1
            continue
        seen["broke"] += 1
        lvl = vah if down else val
        short_ = down
        hit = None
        touched_any = False
        for k in range(j + wait_min, min(j + wait_max + 1, len(bars) - 1)):
            nb = bars[k]
            touched = (nb["h"] >= lvl) if short_ else (nb["l"] <= lvl)
            if not touched:
                continue
            touched_any = True
            held = (nb["c"] < lvl) if short_ else (nb["c"] > lvl)
            if confirm == "touch":
                hit = k
                break
            if confirm == "close":
                if held:
                    hit = k
                    break
            elif confirm == "two-candle":
                for q in range(k + 1, min(k + 3, len(bars) - 1)):
                    if (bars[q]["c"] < lvl) if short_ else (bars[q]["c"] > lvl):
                        hit = q
                        break
                if hit is not None:
                    break
            else:                                   # reclaim
                # price must CLOSE back outside - a genuine reclaim of the level
                # - and only then fail and close inside again.
                reclaimed = (nb["c"] > lvl) if short_ else (nb["c"] < lvl)
                if not reclaimed:
                    continue
                for q in range(k + 1, min(k + 4, len(bars) - 1)):
                    if (bars[q]["c"] < lvl) if short_ else (bars[q]["c"] > lvl):
                        hit = q
                        break
                if hit is not None:
                    break
        if touched_any:
            seen["retested"] += 1
        if hit is None:
            j += 1
            continue
        seen["held"] += 1
        nxt = bars[hit + 1]
        if nxt["t"] < entry_until:
            out.append({"side": "SHORT" if short_ else "LONG",
                        "signal_time": bars[hit]["t"], "signal_i": hit,
                        "entry": round(nxt["o"], 2), "entry_time": nxt["t"],
                        "mi": nxt["mi0"], "band": lvl,
                        "band_name": "VAH" if short_ else "VAL",
                        "break_time": b["t"],
                        "sweep_high": round(bars[hit]["h"], 2),
                        "sweep_low": round(bars[hit]["l"], 2),
                        "sweep_close": round(bars[hit]["c"], 2)})
        j = hit + 1
    return out, seen


def stop_for(sig: dict, *, side: str, vah: float, val: float, stop_at: str,
             offset: float, long_reading: str) -> float:
    """The stop: `offset` points beyond the band, on the far side from the trade.

    A short taken on a VAH re-entry is wrong the moment price is back above the
    VAH, so the stop belongs above it; the long at the VAL mirrors that.
    """
    long_ = side == "LONG"
    if stop_at == "entry":
        return round(sig["entry"] - offset if long_ else sig["entry"] + offset, 2)
    # A SHORT is taken at the VAH and a LONG at the VAL, so "beyond the band" is
    # above it for the short and below it for the long - the same expression as
    # the retest rule, because the sides have swapped along with the bands.
    return round(sig["band"] - offset if long_ else sig["band"] + offset, 2)


# ---------------------------------------------------------------------------
# The exits - always on 1-minute candles
# ---------------------------------------------------------------------------
#
# Within any minute the order is square-off, then stop, then target, so a
# minute that spans both the stop and the target is scored a LOSS.  The walk
# INCLUDES the entry minute under `next` (the entry is that minute's open and
# the stop is often only a few points away, so excluding it would delete this
# rule's most common loss) and starts the minute AFTER the confirming candle
# under `close`.

def walk(mins: list[dict], mi_entry: int, side: str, sl: float,
         target: float | None, *, eod: str, square_off: str) -> dict:
    long_ = side == "LONG"
    for i in range(mi_entry, len(mins)):
        m = mins[i]
        if eod == "close" and m["t"] >= square_off:
            return {"exit": m["o"], "exit_time": m["t"], "exit_i": i,
                    "reason": "SQUARE OFF"}
        if (m["l"] <= sl) if long_ else (m["h"] >= sl):
            # A resting stop fills AT the level, unless the minute opened
            # through it, in which case the open is the honest fill and the
            # loss is worse than 1R.  `slip` is exactly that overshoot.
            fill = min(sl, m["o"]) if long_ else max(sl, m["o"])
            return {"exit": fill, "exit_time": m["t"], "exit_i": i, "reason": "STOP"}
        if target is not None and ((m["h"] >= target) if long_ else (m["l"] <= target)):
            fill = max(target, m["o"]) if long_ else min(target, m["o"])
            return {"exit": fill, "exit_time": m["t"], "exit_i": i, "reason": "TARGET"}
    last = mins[-1]
    return {"exit": last["c"], "exit_time": last["t"], "exit_i": len(mins) - 1,
            "reason": "EOD"}


def after_stop(mins, exit_i: int, side: str, sl: float, target: float,
               square_off: str) -> dict:
    """Keep walking once the stop is taken: does price come back?

    This exists because "it stopped me out and then went my way" is the most
    common complaint about any tight stop, and it is checkable rather than
    arguable.  Two numbers per stopped trade:

      came_back  the ORIGINAL target was reached later in the same session
      excess     how far past the stop price ran before it turned - which is
                 how much wider the stop would have had to sit to survive

    `excess` is the honest half.  A stop wide enough to hold through it also
    raises R, and the target is a multiple of R, so it moves the target the
    same distance further away.  Nothing here is free.
    """
    long_ = side == "LONG"
    excess = 0.0
    for i in range(exit_i, len(mins)):
        m = mins[i]
        if m["t"] >= square_off:
            break
        over = (sl - m["l"]) if long_ else (m["h"] - sl)
        if over > excess:
            excess = over
        if (m["h"] >= target) if long_ else (m["l"] <= target):
            return {"came_back": True, "excess": round(excess, 2),
                    "came_back_at": m["t"]}
    return {"came_back": False, "excess": round(excess, 2), "came_back_at": None}


PRICER = CachedPricer()


def _option_leg(pricer, info, t, res) -> dict:
    """The premium fields for one exit variant.

    A trade whose contract or candles could not be had STAYS in the book and
    stays visible; it is simply left out of the money totals.  Dropping it
    would quietly shrink the sample.
    """
    if pricer is None or info is None:
        return {"pnl_rs": None, "win": None, "opt_reason": "not priced",
                "prem_pts": None, "prem_perc": None, "entry_px": None,
                "exit_px": None}
    if info["reason"]:
        return {"strike": info["strike"], "opt_type": info["option_type"],
                "opt_symbol": info["symbol"], "entry_px": None, "exit_px": None,
                "prem_pts": None, "prem_perc": None, "pnl_rs": None, "win": None,
                "opt_reason": info["reason"]}
    if t["entry_time"] == res["exit_time"]:
        # The option cache holds one CLOSE per minute, so a trade that opens and
        # closes inside the same minute would look up the same premium twice and
        # score exactly 0.0 - which is not a flat trade, it is an unmeasurable
        # one, and it lands disproportionately on fast TARGET hits.  Recording
        # it as 0.0% would drag the mean toward zero and understate the winners.
        # It stays in the book, in the counts and in every R figure, and is left
        # out of the premium columns, which is how this repo treats any trade it
        # cannot price.
        return {"strike": info["strike"], "opt_type": info["option_type"],
                "opt_symbol": info["symbol"], "entry_px": None, "exit_px": None,
                "prem_pts": None, "prem_perc": None, "pnl_rs": None, "win": None,
                "opt_reason": "exit inside the entry minute"}
    o = CachedPricer.price_from(info, t["entry_time"], res["exit_time"])
    prem, px = o["prem_pts"], o["entry_px"]
    # THE HEADLINE NUMBER.  What the account risks on a bought option is what
    # the contract cost, so the return is measured against exactly that - and
    # it is independent of lot size, which is what makes variants comparable.
    perc = None if (prem is None or not px) else round(prem / px * 100, 2)
    return {"strike": o["strike"], "opt_type": o["option_type"],
            "opt_symbol": o["symbol"], "entry_px": px, "exit_px": o["exit_px"],
            "prem_pts": prem, "prem_perc": perc,
            "pnl_rs": None if prem is None else round(prem * LOT_SIZE, 2),
            "win": None if prem is None else prem > 0,
            "opt_reason": o["reason"]}


def price_trades(mins: list[dict], signals: list[dict], *, rr_values: list[float],
                 modes: list[str], eod: str, square_off: str, min_risk: float,
                 pricer=None, day: str = "", roll: str = "none") -> list[dict]:
    """Turn each signal into a trade carrying every (trade-mode, R) variant.

    ONE POSITION AT A TIME, enforced PER VARIANT, because the exit differs per
    variant: the same later signal can be legal under 1:2 (the earlier trade
    had closed) and illegal under 1:4 (it was still running).
    """
    keys = rr_keys(rr_values)
    trades: list[dict] = []
    for sig in signals:
        t = dict(sig)
        t["ex"] = {}
        # SIGNED risk.  A zero or negative risk is not a small trade, it is an
        # entry that filled on the wrong side of its own stop - which is
        # exactly what the literal step 3B produces on every long.
        if sig["risk"] <= 0:
            t["dead"] = "entry at or through the stop"
        elif sig["risk"] < min_risk:
            t["dead"] = f"risk {sig['risk']} below the {min_risk:g}-point floor"
        trades.append(t)

    day_info = {}
    if pricer is not None:
        for t in trades:
            day_info[id(t)] = pricer.day_prices(day, t["side"], t["entry"], roll)

    live = [t for t in trades if "dead" not in t]
    for mode in modes:
        for rk in keys:
            open_until = -1
            done_for_day = False
            r = float(rk.split(":")[1])
            for t in live:
                t["ex"].setdefault(mode, {})
                if mode == "session" and done_for_day:
                    t["ex"][mode][rk] = {"skipped": True, "why": "one trade per session"}
                    continue
                if t["mi"] <= open_until:
                    t["ex"][mode][rk] = {"skipped": True, "why": "a position was already open"}
                    continue
                entry, sl, risk = t["entry"], t["sl"], t["risk"]
                long_ = t["side"] == "LONG"
                tgt = entry + risk * r if long_ else entry - risk * r
                res = walk(mins, t["mi"], t["side"], sl, tgt, eod=eod,
                           square_off=square_off)
                pts = (res["exit"] - entry) if long_ else (entry - res["exit"])
                t["ex"][mode][rk] = {
                    "target": round(tgt, 2), "stop_level": round(sl, 2),
                    "exit": round(res["exit"], 2), "exit_time": res["exit_time"],
                    "reason": res["reason"], "points": round(pts, 2),
                    "r_multiple": round(pts / risk, 3),
                    "slip": (round(abs(res["exit"] - sl), 2)
                             if res["reason"] == "STOP" else 0.0),
                    **(after_stop(mins, res["exit_i"], t["side"], sl, tgt,
                                  square_off)
                       if res["reason"] == "STOP"
                       else {"came_back": None, "excess": None,
                             "came_back_at": None}),
                    # The rule is decided on SPOT and R comes from spot points;
                    # the percentage and the win flag come from the PREMIUM,
                    # because that is what the account actually sees.
                    **_option_leg(pricer, day_info.get(id(t)), t, res),
                    "skipped": False,
                }
                open_until = res["exit_i"]
                done_for_day = True
    return trades


# ---------------------------------------------------------------------------
# Aggregation - percentages and R first, rupees second
# ---------------------------------------------------------------------------

EMPTY_SUMMARY = {
    "days": 0, "trades": 0, "priced": 0, "unpriced": 0, "wins": 0, "losses": 0,
    "win_rate": 0.0, "pnl_prem": 0.0, "pnl_pts": 0.0, "pnl_rs": 0.0,
    "avg_prem_perc": 0.0, "avg_r": 0.0, "rr_real": 0.0, "worst_rs": 0.0,
    "stops": 0, "sqo": 0, "targets": 0, "eod": 0, "slip": 0.0,
    "avg_risk": 0.0, "med_risk": 0.0, "pretraded": 0, "pretraded_perc": 0.0,
    "same_minute": 0, "stopped": 0, "came_back": 0, "back_perc": 0.0,
    "excess_med": 0.0, "excess_p90": 0.0,
}


def summarise(trades: list[dict], mode: str, rk: str) -> dict:
    rows = []
    for t in trades:
        e = t.get("ex", {}).get(mode, {}).get(rk)
        if e and not e.get("skipped"):
            rows.append((t, e))
    if not rows:
        return dict(EMPTY_SUMMARY)
    priced = [(t, e) for t, e in rows if e.get("prem_pts") is not None]
    wins = [e for _, e in priced if e["prem_pts"] > 0]
    losses = [e for _, e in priced if e["prem_pts"] <= 0]
    risks = sorted(t["risk"] for t, _ in rows)
    percs = [e["prem_perc"] for _, e in priced if e["prem_perc"] is not None]
    avg_win = (sum(e["prem_pts"] for e in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(-e["prem_pts"] for e in losses) / len(losses)) if losses else 0.0
    pre = sum(1 for t, _ in rows if t.get("stop_pretraded"))
    same_min = sum(1 for _, e in rows
                   if e.get("opt_reason") == "exit inside the entry minute")
    stops = [e for _, e in rows if e["reason"] == "STOP"]
    back = [e for e in stops if e.get("came_back")]
    exc = sorted(e["excess"] for e in stops if e.get("excess") is not None)
    return {
        "days": len({t["date"] for t, _ in rows}),
        "trades": len(rows), "priced": len(priced),
        "unpriced": len(rows) - len(priced),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(priced) * 100, 1) if priced else 0.0,
        "pnl_prem": round(sum(e["prem_pts"] for _, e in priced), 2),
        "pnl_pts": round(sum(e["points"] for _, e in rows), 2),
        "pnl_rs": round(sum(e["pnl_rs"] for _, e in priced if e["pnl_rs"] is not None), 2),
        "avg_prem_perc": round(sum(percs) / len(percs), 2) if percs else 0.0,
        "avg_r": round(sum(e["r_multiple"] for _, e in rows) / len(rows), 3),
        "rr_real": round(avg_win / avg_loss, 2) if avg_loss else 0.0,
        "worst_rs": round(min((e["pnl_rs"] for _, e in priced
                               if e["pnl_rs"] is not None), default=0.0), 2),
        "stops": sum(1 for _, e in rows if e["reason"] == "STOP"),
        "sqo": sum(1 for _, e in rows if e["reason"] == "SQUARE OFF"),
        "targets": sum(1 for _, e in rows if e["reason"] == "TARGET"),
        "eod": sum(1 for _, e in rows if e["reason"] == "EOD"),
        "slip": round(sum(e["slip"] for _, e in rows), 2),
        "avg_risk": round(sum(risks) / len(risks), 2),
        "med_risk": round(risks[len(risks) // 2], 2),
        # THE diagnostic: how often the stop level had already traded during
        # the very candle that produced the signal.
        "pretraded": pre,
        "pretraded_perc": round(pre / len(rows) * 100, 1),
        # Resolved inside their own entry minute, so unpriceable off a
        # one-close-per-minute option cache.  Counted, never scored as 0.0.
        "same_minute": same_min,
        # "it stopped me then went my way", measured.  `back_perc` is how often
        # that is literally true; `excess_med` is what it would have cost to
        # sit through it, and a wider stop moves the target by the same amount.
        "stopped": len(stops),
        "came_back": len(back),
        "back_perc": round(len(back) / len(stops) * 100, 1) if stops else 0.0,
        "excess_med": round(exc[len(exc) // 2], 2) if exc else 0.0,
        "excess_p90": round(exc[int(len(exc) * 0.9)], 2) if exc else 0.0,
    }


def in_view(t: dict, view: str) -> bool:
    return view == "both" or (view == "long") == (t["side"] == "LONG")


# ---------------------------------------------------------------------------
# One session
# ---------------------------------------------------------------------------

def simulate_day(day: str, prev_mins: list[dict], minutes: list[dict], tf: int,
                 args, pdc_daily: float | None, pricer=None) -> dict:
    mins = session_minutes(minutes, args.session_start)
    prev = session_minutes(prev_mins, args.session_start)
    row = {"date": day, "status": "no data", "signals": 0, "trades": [],
           "profile": None, "side": None, "pdc": None, "pdc_last": None}
    if not mins or not prev:
        return row

    prof = day_profile(prev, profile_tf=args.profile_tf, row_size=args.row_size,
                       value_area=args.value_area, weight=args.weight)
    if prof is None:
        row["status"] = "no profile"
        return row
    row["profile"] = {k: prof[k] for k in
                      ("poc", "vah", "val", "high", "low", "va_rows",
                       "va_covered", "total", "bars", "row_size", "weight")}
    row["profile"]["rows"] = prof["rows"]

    pdc_last = round(prev[-1]["c"], 2)
    row["pdc_last"] = pdc_last
    pdc = pdc_daily if (args.pdc_basis == "daily" and pdc_daily is not None) else pdc_last
    row["pdc"] = round(pdc, 2)
    row["pdc_official"] = round(pdc_daily, 2) if pdc_daily is not None else None

    # Step 3A: this rule does NOT gate on the previous close.  Where it landed
    # is recorded for the report only.
    row["side"] = setup_side(pdc, prof)

    bars = build_buckets(mins, tf)
    if len(bars) < 2:
        row["status"] = "no bars"
        return row

    vah, val, poc = prof["vah"], prof["val"], prof["poc"]
    signals, seen = find_signals(bars, mins, vah=vah, val=val,
                                 wait_min=args.wait_min, wait_max=args.wait_max,
                                 confirm=args.confirm,
                                 entry_until=args.entry_until,
                                 acceptance=args.acceptance)
    row["broke"] = seen["broke"] > 0
    row["retested"] = seen["retested"] > 0
    row["reached_poc"] = seen["retested"] > 0      # the funnel's third rung
    row["signals"] = len(signals)
    if not signals:
        row["status"] = ("retested, never held" if seen["retested"]
                         else ("broke, no retest in the window" if seen["broke"]
                               else "no band break"))
        return row

    for sig in signals:
        sig["date"] = day
        sig["poc"] = poc
        sig["vah"] = vah
        sig["val"] = val
        sig["tf"] = tf
        sl = stop_for(sig, side=sig["side"], vah=vah, val=val,
                      stop_at=args.stop_at, offset=args.stop_offset,
                      long_reading=args.long_reading)
        sig["sl"] = sl
        sig["risk"] = round((sl - sig["entry"]) if sig["side"] == "SHORT"
                            else (sig["entry"] - sl), 2)
        # Had the stop level already traded during the signal candle itself?
        sig["stop_pretraded"] = bool(
            sig["sweep_high"] >= sl if sig["side"] == "SHORT"
            else sig["sweep_low"] <= sl)

    trades = price_trades(mins, signals, rr_values=args.rr_values,
                          modes=args.modes, eod=args.eod,
                          square_off=args.square_off, min_risk=args.min_risk,
                          pricer=pricer, day=day, roll=args.expiry_roll)
    row["trades"] = trades
    placeable = [t for t in trades if t.get("ex")]
    row["status"] = "traded" if placeable else "signal, unplaceable"
    return row


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>POC reversal v1</title>
<style>
  /* Same palette and the same light-default / dark-override structure as every
     other report in backend/reports, so a run of these can be read side by side
     and each one follows the reader's OS setting. */
  :root {
    color-scheme: light;
    --surface:#fcfcfb; --page:#f4f4f1; --ink:#0b0b0b; --ink2:#52514e; --muted:#8b8983;
    --grid:#e3e2db; --border:rgba(11,11,11,.10);
    --up:#128a5a; --down:#d0453f; --accent:#2a78d6; --warn:#b8860b; --zone:#7a5cd0;
    --chip:#eceae3;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --border:rgba(255,255,255,.10);
      --up:#3ecf8e; --down:#e66767; --accent:#5b9df0; --warn:#e0b341; --zone:#a68bf0;
      --chip:#262624;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --border:rgba(255,255,255,.10);
    --up:#3ecf8e; --down:#e66767; --accent:#5b9df0; --warn:#e0b341; --zone:#a68bf0;
    --chip:#262624;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--page);color:var(--ink);
       font:13px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
  .wrap{max-width:1500px;margin:0 auto;padding:20px 16px 80px}
  h1{font-size:20px;margin:0 0 4px}
  h2{font-size:15px;margin:28px 0 10px;color:var(--ink);
     border-bottom:1px solid var(--border);padding-bottom:6px}
  .sub{color:var(--muted);font-size:12px;margin-bottom:14px}
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:8px;
         padding:14px 16px;margin-bottom:14px}
  .note{background:var(--chip);border-left:3px solid var(--accent);
        border-radius:0 6px 6px 0;padding:10px 14px;margin:10px 0;
        color:var(--muted);font-size:12px}
  .note b{color:var(--ink)}
  .warn{border-left-color:var(--warn)}
  .controls{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;
            margin-bottom:14px}
  .ctl{display:flex;flex-direction:column;gap:4px}
  .ctl label{font-size:11px;color:var(--muted);text-transform:uppercase;
             letter-spacing:.04em}
  select,button{background:var(--chip);color:var(--ink);border:1px solid var(--border);
         border-radius:6px;padding:6px 10px;font:inherit}
  button{cursor:pointer}
  button:hover{border-color:var(--accent)}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
  .card{background:var(--chip);border:1px solid var(--border);border-radius:8px;
        padding:12px 14px}
  .card .k{font-size:11px;color:var(--muted);text-transform:uppercase;
           letter-spacing:.04em}
  .card .v{font-size:20px;font-weight:600;margin-top:3px}
  table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
  th,td{padding:6px 9px;text-align:right;border-bottom:1px solid var(--border);
        white-space:nowrap}
  th{color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase;
     letter-spacing:.03em;position:sticky;top:0;background:var(--surface)}
  td.l,th.l{text-align:left}
  tr:hover td{background:var(--chip)}
  .pos{color:var(--up)} .neg{color:var(--down)} .dimc{color:var(--muted)}
  .scroll{max-height:520px;overflow:auto;border:1px solid var(--border);
          border-radius:8px}
  .funnel{display:grid;grid-template-columns:1fr auto auto;gap:2px 16px;
          align-items:center;font-variant-numeric:tabular-nums}
  .funnel .bar{height:16px;background:var(--accent);border-radius:3px;opacity:.75}
  .funnel .lab{color:var(--muted)}
  .funnel .num{font-weight:600}
  svg{display:block;width:100%;height:auto;background:var(--surface);
      border:1px solid var(--border);border-radius:8px;touch-action:none}
  svg.drag{cursor:grabbing}
  #tip{position:fixed;pointer-events:none;display:none;background:var(--surface);
       border:1px solid var(--border);border-radius:6px;padding:6px 9px;
       font-size:11px;z-index:9;box-shadow:0 4px 16px rgba(0,0,0,.18)}
  .chartbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:8px 0}
  .chartbar label{color:var(--muted);font-size:12px;display:flex;gap:5px;
                  align-items:center}
  .tag{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;
       border:1px solid var(--border);color:var(--muted)}
  .setup{padding:8px 12px;border-radius:6px;margin:0 0 8px;font-size:12.5px;
         border:1px solid var(--border);background:var(--chip);color:var(--ink2)}
  .setup.neg{border-left:4px solid var(--down)}
  .setup.pos{border-left:4px solid var(--up)}
  .setup.dim{border-left:4px solid var(--muted);color:var(--muted)}
  .setup b{color:var(--ink)}
  .net{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px}
  .net .k{font-size:11px;color:var(--muted);text-transform:uppercase;
          letter-spacing:.04em}
  .net .v{font-size:26px;font-weight:650;margin-top:4px;
          font-variant-numeric:tabular-nums}
  details{margin-top:28px;border:1px solid var(--border);border-radius:8px;
          background:var(--surface);padding:0 14px}
  details[open]{padding-bottom:12px}
  summary{cursor:pointer;padding:12px 0;color:var(--ink2);font-size:13px;
          font-weight:500}
  summary:hover{color:var(--ink)}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  .pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:10.5px;
        font-weight:600;letter-spacing:.02em;white-space:nowrap}
  .pill.tgt{background:rgba(18,138,90,.15);color:var(--up)}
  .pill.sl{background:rgba(208,69,63,.15);color:var(--down)}
  .pill.eod{background:rgba(184,134,11,.15);color:var(--warn)}
  .pill.no{background:var(--chip);color:var(--muted)}
  .pill.ce{background:rgba(18,138,90,.15);color:var(--up)}
  .pill.pe{background:rgba(208,69,63,.15);color:var(--down)}
  .dim{color:var(--muted)}
</style>
</head>
<body>
<div class="wrap">
  <h1>POC reversal v1 &mdash; previous day&rsquo;s value area picks the side, the POC is the level</h1>
  <div class="sub" id="sub"></div>
  <div class="note warn" id="verdictShort"></div>

  <h2>Overall</h2>
  <div class="panel" id="netPanel"></div>
  <svg id="equity" viewBox="0 0 1200 210" preserveAspectRatio="xMidYMid meet"
       style="height:auto;margin-bottom:14px"></svg>
  <div class="controls">
    <div class="ctl"><label>Timeframe</label><select id="selTf"></select></div>
    <div class="ctl"><label>Target</label><select id="selRr"></select></div>
    <div class="ctl" id="modeCtl"><label>Trade mode</label><select id="selMode"></select></div>
    <div class="ctl"><label>Side</label><select id="selView"></select></div>
  </div>
  <div class="cards" id="cards"></div>

  <h2>NIFTY chart &mdash; the profile, the levels and the trade</h2>
  <div class="chartbar">
    <select id="daySel"></select>
    <label><input type="checkbox" id="showTrades" checked> entry / stop / target</label>
    <label><input type="checkbox" id="showLevels" checked> POC / VAH / VAL</label>
    <label><input type="checkbox" id="showProfile" checked> profile</label>
    <label><input type="checkbox" id="showPrev" checked> previous session</label>
    <label><input type="checkbox" id="showPdc" checked> previous close</label>
    <button id="zoomIn">+</button><button id="zoomOut">&minus;</button>
    <button id="zoomReset">reset</button>
    <span class="tag" id="dayTag"></span>
  </div>
  <div id="setupBanner" class="setup dim"></div>
  <svg id="chart" viewBox="0 0 1200 520" preserveAspectRatio="xMidYMid meet"></svg>
  <div id="tip"></div>

  <h2>Day-by-day</h2>
  <div class="chartbar">
    <label><input type="checkbox" id="onlyTrades" checked> only sessions that traded</label>
    <label><input type="checkbox" id="onlyPre"> only trades whose stop had already traded</label>
  </div>
  <div class="scroll"><table id="tblDays"></table></div>

  <h2>Weekly summary</h2>
  <div class="scroll"><table id="tblWeekly"></table></div>

  <h2>Monthly summary</h2>
  <div class="scroll"><table id="tblMonthly"></table></div>

  <h2>Every variant</h2>
  <div class="scroll"><table id="tblMatrix"></table></div>

  <h2>Net PnL matrix &mdash; &#8377; per lot</h2>
  <div class="scroll"><table id="matrix2"></table></div>

  <h2>How the sessions ended</h2>
  <div class="panel"><div id="funnel" class="funnel"></div></div>

  <h2>Stop width</h2>
  <div class="panel">
    <div id="stopBack"></div>
    <div class="scroll" style="margin-top:12px"><table id="tblStopSweep"></table></div>
  </div>

  <h2>Stability</h2>
  <div class="sub" id="splitSub"></div>
  <div class="scroll"><table id="tblHalves"></table></div>
  <div style="height:14px"></div>
  <div class="scroll"><table id="tblYears"></table></div>

  <details id="notes">
    <summary>Notes &mdash; the rule, the corrections it needed, and what limits these numbers</summary>
    <div class="panel" id="rule"></div>
    <div class="note" id="volnote"></div>
    <div class="note warn" id="verdict"></div>
    <div class="note warn" id="riskNote"></div>
  </details>
</div>

<script>
const DATA = __DATA_JSON__;
const M = DATA.meta;

/* ---------- helpers ---------- */
const $ = id => document.getElementById(id);
const fmt = (v, d = 2) => (v === null || v === undefined) ? '&mdash;'
  : Number(v).toLocaleString('en-IN', {minimumFractionDigits: d, maximumFractionDigits: d});
const sign = v => (v === null || v === undefined) ? 'dimc' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : 'dimc'));
const cell = (v, d = 2) => '<td class="' + sign(v) + '">' + fmt(v, d) + '</td>';

function fill(sel, opts, def) {
  sel.innerHTML = opts.map(o =>
    '<option value="' + o.k + '"' + (o.k === def ? ' selected' : '') + '>' + o.v + '</option>').join('');
}

let curTf = M.default_tf, curRr = M.default_rr, curMode = M.default_mode, curView = M.default_view;

/* ---------- header ---------- */
$('sub').innerHTML =
  M.sessions + ' traded sessions &nbsp;' + M.from + ' &rarr; ' + M.to +
  ' &nbsp;&middot;&nbsp; profile: ' + M.weight + ' weighting on ' + M.profile_tf +
  '-minute bars, ' + M.row_size + '-point rows, ' + Math.round(M.value_area * 100) +
  '% value area &nbsp;&middot;&nbsp; stop: ' + M.stop_at + ' &plusmn;' + M.stop_offset +
  ' &nbsp;&middot;&nbsp; entry: ' + M.entry_mode +
  ' &nbsp;&middot;&nbsp; 3B: ' + M.long_reading +
  ' &nbsp;&middot;&nbsp; prev close: ' + M.pdc_basis +
  ' &nbsp;&middot;&nbsp; stop ' + M.stop_offset + ' pts fixed, target min 1:' +
  M.min_rr +
  ' &nbsp;&middot;&nbsp; generated ' + M.generated;

$('volnote').innerHTML =
  '<b>Why this is a time profile, not a volume profile.</b> The NIFTY 50 index ' +
  'reports no volume on any endpoint &mdash; historical, intraday and quote all ' +
  'return 0 or null, and the full quote returns an <b>empty order book</b>. ' +
  'An index is not a traded instrument, so there are no transactions to report ' +
  'and no indicator can recover them. This profile weights <b>time</b> ' +
  '(Steidlmayer&rsquo;s Market Profile), which was measured against the ' +
  'alternatives first: a synthetic volume built from the real traded value of ' +
  '14 NIFTY constituents put the POC a median of <b>0.0 points</b> from plain ' +
  'TPO &mdash; the same answer &mdash; while real futures volume moved it a ' +
  'median 5 points but costs 2.5 years of history and a 40&ndash;64 point basis ' +
  'that drifts more than this rule&rsquo;s entire 5-point stop.';

$('rule').innerHTML =
  '<table><tbody>' +
  '<tr><td class="l" style="width:90px"><b class="neg">SHORT</b></td>' +
  '<td class="l">previous close <b>below the VAL</b> &rarr; price rallies up to the POC, ' +
  'a candle wicks <b>above</b> it and <b>closes back below</b> &rarr; short at the ' +
  (M.entry_mode === 'next' ? 'next candle&rsquo;s open' : 'confirming close') +
  ', stop ' + M.stop_offset + ' points above the ' + M.stop_at + ', target ' + M.default_rr + '</td></tr>' +
  '<tr><td class="l"><b class="pos">LONG</b></td>' +
  '<td class="l">previous close <b>above the VAH</b> &rarr; price falls down to the POC, ' +
  'a candle wicks <b>below</b> it and <b>closes back above</b> &rarr; long, stop ' +
  M.stop_offset + ' points below the ' + M.stop_at + ', target ' + M.default_rr + '</td></tr>' +
  '</tbody></table>' +
  '<div class="note warn" style="margin-bottom:0"><b>Step 3B was a copy of 3A.</b> ' +
  'As written it says the long also enters on a close <i>below</i> the POC with its ' +
  'stop <i>above</i> the POC &mdash; which puts the stop on the profit side and makes ' +
  'risk negative on every long, so the literal reading yields <b>zero placeable ' +
  'longs</b>. It is mirrored here (<code>--long-reading mirror</code>); ' +
  '<code>--long-reading literal</code> reproduces the defect.</div>';

$('verdict').innerHTML =
  '<b>Verdict: no edge found, and this run&rsquo;s stop is a tuned setting.</b> ' +
  'On the spec&rsquo;s own settings &mdash; 5-minute candles, 1:2, stop at POC ' +
  '&plusmn;5 &mdash; the book is 282 trades over 1166 sessions at <b>avg R ' +
  '&minus;0.025</b> and <b>&minus;0.68% mean premium</b>. Sweeping the row size, ' +
  'the parameter that decides where the POC lands, walks avg R through &minus;.075 ' +
  '/ &minus;.025 / &minus;.102 / &minus;.001 / +.135 / &minus;.087 / &minus;.043 ' +
  'for rows 2.5&hellip;25 &mdash; sign flipping with no pattern. Neither side nor ' +
  'any timeframe carries it.' +
  (M.stop_tuned
    ? ' <b>This run uses a stop of ' + M.stop_at + ' &plusmn;' + M.stop_offset +
      ', not the spec&rsquo;s ' + M.spec_stop_at + ' &plusmn;' + M.spec_stop_offset +
      '.</b> Both the basis and the width were chosen on this same sample, so ' +
      'neither is demonstrated out of sample. The <code>entry</code> basis makes ' +
      'the offset the risk itself, which is why its sweep has a broad plateau ' +
      'rather than one lucky cell &mdash; but a plateau found by looking is still ' +
      'found by looking. See the stop table below before reading anything above ' +
      'it as an edge.'
    : '') +
  ' Read this report as a negative result; the numbers below are here to be ' +
  'checked, not to be traded.';

$('verdictShort').innerHTML =
  '<b>Read this as a negative result.</b> The rule as specified &mdash; stop ' +
  'at POC &plusmn;5 &mdash; is flat to negative over 1166 sessions, and the ' +
  'settings this run uses instead were chosen on this same sample. ' +
  '<a href="#notes" style="color:var(--accent)">Full notes at the bottom.</a>';

/* ---------- funnel ---------- */
function renderFunnel() {
  const f = DATA.funnel[curTf];
  const rows = [
    ['sessions with a previous day', f.sessions],
    ['closed outside value (setup)', f.setup],
    ['price returned to the POC', f.reached],
    ['swept and closed back through', f.confirmed],
    ['placeable trades', f.placeable],
  ];
  const max = rows[0][1] || 1;
  $('funnel').innerHTML = rows.map(([lab, n]) =>
    '<div class="lab">' + lab + '</div>' +
    '<div class="num">' + n + '</div>' +
    '<div><div class="bar" style="width:' + Math.max(2, n / max * 320) + 'px"></div></div>'
  ).join('') +
    '<div class="lab">short setups / long setups</div><div class="num">' +
    f.short_setup + ' / ' + f.long_setup + '</div><div></div>';
}

/* ---------- cards ---------- */
/* THE BOTTOM LINE.  It was a small card among eight and the first question
   anyone asks of a backtest is what it made, so it gets its own row and its own
   curve.  The curve is the honest half: a total says what, a curve says WHEN,
   and a result that arrives in one cluster is a different thing from one that
   accrues steadily. */
function renderNet() {
  const s = DATA.summaries[curTf][curView][curMode][curRr];
  const per = s.priced ? s.pnl_rs / s.priced : 0;
  const box = (k, v, cls) =>
    '<div><div class="k">' + k + '</div><div class="v ' + (cls || '') + '">' + v +
    '</div></div>';
  $('netPanel').innerHTML =
    '<div class="net">' +
    box('Net result, &#8377; per lot', s.priced ? sgnRs(s.pnl_rs) : '&mdash;') +
    box('Per trade', s.priced ? sgnRs(per) : '&mdash;') +
    box('Total premium points', s.priced ? sgn(s.pnl_prem, 1) : '&mdash;') +
    box('Mean premium', s.priced ? sgn(s.avg_prem_perc) + '%' : '&mdash;') +
    box('Spot points', sgn(s.pnl_pts, 1)) +
    box('Trades', s.trades + ' <span class="dim" style="font-size:12px">over ' +
        M.sessions + ' sessions</span>') +
    '</div>' +
    '<div class="sub" style="margin:10px 0 0">' +
    (s.priced && s.pnl_rs > 0
      ? 'Positive on this selection. Check the curve for whether it accrues or arrives in a cluster, and the Stability section before believing it.'
      : 'This strategy does not make money on this selection. The ' +
        'rupee figure is one lot (' + M.lot + ') and is gross of brokerage and of ' +
        'the option spread, which at a ' + fmt(s.med_risk, 0) + '-point risk is a ' +
        'large share of the move &mdash; so the real result is worse than this, not better.') +
    '</div>';
  drawEquity();
}

/* cumulative premium P&L, per lot, in trade order */
function drawEquity() {
  const el = $('equity');
  const rows = tradeRows().filter(([t, e]) => e.pnl_rs !== null && e.pnl_rs !== undefined);
  if (rows.length < 2) { el.innerHTML = ''; return; }
  rows.sort((a, b) => a[0].date < b[0].date ? -1 : 1);
  let cum = 0;
  const pts = rows.map(([t, e]) => { cum += e.pnl_rs; return {d: t.date, v: cum}; });
  const W2 = 1200, H2 = 210, L = 74, R = 16, T = 14, B = 26;
  const lo = Math.min(0, ...pts.map(p => p.v)), hi = Math.max(0, ...pts.map(p => p.v));
  const pad = (hi - lo) * 0.08 || 1;
  const X = i => L + i / (pts.length - 1) * (W2 - L - R);
  const Y = v => T + (hi + pad - v) / (hi - lo + 2 * pad) * (H2 - T - B);
  let g = '';
  for (let k = 0; k <= 4; k++) {
    const v = lo - pad + (hi - lo + 2 * pad) * k / 4;
    g += '<line x1="' + L + '" y1="' + Y(v) + '" x2="' + (W2 - R) + '" y2="' + Y(v) +
      '" stroke="var(--grid)"/><text x="' + (L - 6) + '" y="' + (Y(v) + 3) +
      '" fill="var(--muted)" font-size="10" text-anchor="end">' +
      Math.round(v).toLocaleString('en-IN') + '</text>';
  }
  g += '<line x1="' + L + '" y1="' + Y(0) + '" x2="' + (W2 - R) + '" y2="' + Y(0) +
    '" stroke="var(--ink2)" stroke-width="1.2" stroke-dasharray="4 3"/>';
  const d = pts.map((p, i) => (i ? 'L' : 'M') + X(i) + ' ' + Y(p.v)).join(' ');
  const last = pts[pts.length - 1].v;
  const col = last >= 0 ? 'var(--up)' : 'var(--down)';
  g += '<path d="' + d + ' L' + X(pts.length - 1) + ' ' + Y(0) + ' L' + X(0) + ' ' +
    Y(0) + ' Z" fill="' + col + '" opacity="0.10"/>' +
    '<path d="' + d + '" fill="none" stroke="' + col + '" stroke-width="1.8"/>';
  const step = Math.max(1, Math.round(pts.length / 8));
  for (let i = 0; i < pts.length; i += step)
    g += '<text x="' + X(i) + '" y="' + (H2 - 8) + '" fill="var(--muted)" ' +
      'font-size="10" text-anchor="middle">' + pts[i].d.slice(2) + '</text>';
  g += '<text x="' + (W2 - R) + '" y="' + (Y(last) - 6) + '" fill="' + col +
    '" font-size="11" text-anchor="end">cumulative &#8377;' +
    Math.round(last).toLocaleString('en-IN') + '</text>';
  el.innerHTML = g;
}

function renderCards() {
  const s = DATA.summaries[curTf][curView][curMode][curRr];
  const cards = [
    ['trades', s.trades, 0, false],
    ['win rate', s.win_rate, 1, false, '%'],
    ['avg premium', s.avg_prem_perc, 2, true, '%'],
    ['avg R', s.avg_r, 3, true],
    ['median risk', s.med_risk, 1, false, ' pts'],
    ['stop pre-traded', s.pretraded_perc, 1, false, '%'],
    ['targets hit', s.targets, 0, false],
    ['net (Rs, lot ' + M.lot + ')', s.pnl_rs, 0, true],
  ];
  $('cards').innerHTML = cards.map(([k, v, d, col, suf]) => {
    const absent = !s.priced && (k === 'win rate' || k === 'avg premium' ||
                                 k.startsWith('net ('));
    return '<div class="card"><div class="k">' + k + '</div><div class="v' +
      (absent ? ' dimc' : (col ? ' ' + sign(v) : '')) + '">' +
      (absent ? '&mdash;' : fmt(v, d) + (suf || '')) + '</div></div>';
  }).join('');

  $('riskNote').innerHTML =
    '<b>Risk is tight, and it turned out not to matter.</b> Risk is a median of <b>' +
    fmt(s.med_risk, 1) + ' points</b> because the stop is pinned to the POC rather ' +
    'than to the sweep extreme, so a ' + curRr + ' target sits only ~' +
    fmt(s.med_risk * parseFloat(curRr.split(':')[1]), 0) + ' points away &mdash; genuinely ' +
    'reachable. Against that, the stop level had <b>already traded during the ' +
    'signal candle itself in ' + fmt(s.pretraded_perc, 1) + '%</b> of these trades ' +
    '(' + s.pretraded + ' of ' + s.trades + '), because the sweep wick runs further ' +
    'past the POC than the ' + M.stop_offset + '-point stop does. <b>Moving the ' +
    'stop beyond the sweep extreme instead</b> (<code>--stop-at sweep</code>) removes ' +
    'that entirely by construction and raises median risk by about half, and it ' +
    'changes avg R by almost nothing (5m: -0.025 vs -0.024) &mdash; so stop placement ' +
    'is not what is wrong with this rule. Of ' + s.trades +
    ' trades, ' + s.targets + ' reached target, ' + s.stops + ' were stopped, ' +
    s.sqo + ' squared off and ' + s.eod + ' ran to the last candle.' +
    (s.unpriced ? ' <b>' + s.unpriced + '</b> could not be priced and are excluded ' +
      'from the premium columns while staying in R and the counts' +
      (s.same_minute ? ', of which <b>' + s.same_minute + '</b> resolved inside their own ' +
        'entry minute (the option cache holds one close per minute, so those are ' +
        'unmeasurable rather than flat)' : '') +
      '; the rest predate the 2024-10 start of the option archive.' : '');
}

/* ---------- matrix ---------- */
const PRICED_COLS = new Set(['win_rate', 'avg_prem_perc', 'rr_real', 'pnl_rs']);
const MCOLS = [['trades', 'trades', 0], ['win_rate', 'win %', 1],
  ['avg_prem_perc', 'avg prem %', 2], ['avg_r', 'avg R', 3],
  ['rr_real', 'real R:R', 2], ['med_risk', 'med risk', 1],
  ['pretraded_perc', 'pre-traded %', 1], ['targets', 'target', 0],
  ['stops', 'stop', 0], ['sqo', 'sq-off', 0], ['pnl_rs', 'Rs', 0]];

function renderMatrix() {
  const oneMode = M.modes.length < 2;
  let h = '<thead><tr><th class="l">tf</th>' + (oneMode ? '' : '<th class="l">mode</th>') +
    '<th class="l">target</th>' +
    MCOLS.map(c => '<th class="num">' + c[1] + '</th>').join('') + '</tr></thead><tbody>';
  for (const tf of M.timeframes)
    for (const m of M.modes.map(x => x.key))
      for (const rk of M.rr_keys) {
        const s = DATA.summaries[tf][curView][m][rk];
        if (!s.trades) continue;
        const cur = (tf === curTf && m === curMode && rk === curRr);
        h += '<tr' + (cur ? ' style="outline:1px solid var(--accent)"' : '') + '>' +
          '<td class="l">' + tf + 'm</td>' + (oneMode ? '' : '<td class="l">' + m + '</td>') +
          '<td class="l">' + rk + '</td>' +
          MCOLS.map(c => {
            const v = s[c[0]];
            // Option history starts 2024-10. A cell with nothing priced must
            // read as absent, not as 0.0% - otherwise 2022 and 2023 look like
            // measured break-even instead of unmeasured.
            if (PRICED_COLS.has(c[0]) && !s.priced) return '<td class="dimc">&mdash;</td>';
            const col = ['avg_prem_perc', 'avg_r', 'pnl_rs'].includes(c[0]);
            return '<td class="' + (col ? sign(v) : '') + '">' + fmt(v, c[2]) + '</td>';
          }).join('') + '</tr>';
      }
  $('tblMatrix').innerHTML = h + '</tbody>';
}

/* ---------- halves ---------- */
function renderHalves() {
  $('splitSub').innerHTML = 'Split at <b>' + DATA.split_at + '</b>. Row size, the ' +
    'value area and the timeframe were chosen rather than given by the spec, so a ' +
    'setting that flips sign between the halves has not been demonstrated whatever ' +
    'the full-sample number says. <b>The verdict is taken on avg R, not on premium ' +
    '%</b>, because R covers every trade while the premium columns only cover ' +
    'trades after 2024-10, where the option archive begins. On a window that ' +
    'reaches back past that date a half can be entirely unpriced and would ' +
    'otherwise read 0.0% from absence; the per-half priced counts are shown so ' +
    'you can see which case this run is.';
  let h = '<thead><tr><th class="l">tf</th><th class="l">mode</th><th class="l">target</th>' +
    '<th>full R</th><th>trades</th><th>H1 R</th><th>H2 R</th><th class="l">agree?</th>' +
    '<th>full prem %</th><th>H1 prem %</th><th>H2 prem %</th></tr></thead><tbody>';
  for (const tf of M.timeframes)
    for (const m of M.modes.map(x => x.key))
      for (const rk of M.rr_keys) {
        const f = DATA.summaries[tf]['both'][m][rk];
        if (!f.trades) continue;
        const a = DATA.halves[tf].h1[m][rk], b = DATA.halves[tf].h2[m][rk];
        const ok = (a.avg_r >= 0) === (b.avg_r >= 0);
        const pc = x => x.priced ? cell(x.avg_prem_perc)
                                 : '<td class="dimc">unpriced</td>';
        h += '<tr><td class="l">' + tf + 'm</td><td class="l">' + m + '</td><td class="l">' + rk + '</td>' +
          cell(f.avg_r, 3) + '<td>' + f.trades + '</td>' +
          cell(a.avg_r, 3) + cell(b.avg_r, 3) +
          '<td class="l ' + (ok ? 'dimc' : 'neg') + '">' + (ok ? 'yes' : 'DISAGREE') + '</td>' +
          pc(f) + pc(a) + pc(b) + '</tr>';
      }
  $('tblHalves').innerHTML = h + '</tbody>';
}

/* ---------- years ---------- */
function renderYears() {
  let h = '<thead><tr><th class="l">year</th><th>trades</th><th>priced</th><th>win %</th>' +
    '<th>avg prem %</th><th>avg R</th><th>med risk</th><th>pre-traded %</th>' +
    '<th>target</th><th>stop</th><th>Rs</th></tr></thead><tbody>';
  for (const y of M.years) {
    const s = DATA.per_year[curTf][y];
    if (!s || !s.trades) continue;
    const dash = '<td class="dimc">&mdash;</td>';
    h += '<tr><td class="l">' + y + '</td><td>' + s.trades + '</td>' +
      '<td class="' + (s.priced ? '' : 'dimc') + '">' + s.priced + '</td>' +
      (s.priced ? '<td>' + fmt(s.win_rate, 1) + '</td>' + cell(s.avg_prem_perc)
                : dash + dash) +
      cell(s.avg_r, 3) + '<td>' + fmt(s.med_risk, 1) + '</td>' +
      '<td>' + fmt(s.pretraded_perc, 1) + '</td><td>' + s.targets + '</td><td>' + s.stops + '</td>' +
      (s.priced ? cell(s.pnl_rs, 0) : dash) + '</tr>';
  }
  $('tblYears').innerHTML = h + '</tbody>';
}

/* ---------- day-by-day, summaries and the PnL matrix ---------- */
const n0 = v => (v === null || v === undefined) ? '&mdash;'
  : Number(v).toLocaleString('en-IN', {maximumFractionDigits: 0});
const sgn = (v, d = 2) => (v === null || v === undefined) ? '<span class="dim">&mdash;</span>'
  : '<span class="' + sign(v) + '">' + fmt(v, d) + '</span>';
const sgnRs = v => (v === null || v === undefined) ? '<span class="dim">&mdash;</span>'
  : '<span class="' + sign(v) + '">' + Number(v).toLocaleString('en-IN',
      {maximumFractionDigits: 0}) + '</span>';

function closePill(ct) {
  if (ct === 'TARGET') return '<span class="pill tgt">TARGET</span>';
  if (ct === 'STOP') return '<span class="pill sl">STOPLOSS</span>';
  if (ct === 'SQUARE OFF') return '<span class="pill eod">SQUARE OFF</span>';
  if (ct === 'EOD') return '<span class="pill eod">EOD</span>';
  return '<span class="pill no">' + (ct || '&ndash;') + '</span>';
}

function tradeRows() {
  const out = [];
  for (const t of DATA.tf_trades[curTf]) {
    if (curView !== 'both' && ((curView === 'long') !== (t.side === 'LONG'))) continue;
    const e = (t.ex[curMode] || {})[curRr];
    if (!e || e.skipped) continue;
    if ($('onlyPre').checked && !t.stop_pretraded) continue;
    out.push([t, e]);
  }
  return out;
}

/* Sessions that produced no trade still carry WHY, which is most of what this
   study found - the setup fires on 43% of days but price only returns to the
   POC on about half of those. */
function renderDays() {
  const onlyTr = $('onlyTrades').checked;
  const byDay = {};
  for (const [t, e] of tradeRows()) (byDay[t.date] = byDay[t.date] || []).push([t, e]);
  const head = '<thead><tr><th class="l">Date</th><th class="l">Met</th>' +
    '<th class="num">Prev close</th><th class="num">VAL &ndash; VAH</th><th class="num">POC</th>' +
    '<th class="l">Trade</th><th class="num">Strike</th><th class="l">Symbol</th>' +
    '<th class="num">Opt entry</th><th class="num">Opt exit</th><th class="l">Close type</th>' +
    '<th class="num">PnL (pts)</th><th class="num">PnL (&#8377;)</th>' +
    '<th class="num">NIFTY @ t</th><th class="num">Target</th><th class="num">Stop</th>' +
    '<th class="num">NIFTY @ exit</th><th class="num">NIFTY pts</th>' +
    '<th class="l">Exit time</th><th class="l">Note</th></tr></thead>';
  let body = '';
  for (const r of DATA.tf_days[curTf]) {
    const rows = byDay[r.date] || [];
    const pf = r.profile;
    let ctx = '<td class="num dim">&mdash;</td><td class="num dim">&mdash;</td>' +
              '<td class="num dim">&mdash;</td>';
    if (pf) {
      const sideOf = c => c < pf.val ? 'SHORT' : (c > pf.vah ? 'LONG' : null);
      const other = M.pdc_basis === 'last' ? r.pdc_official : r.pdc_last;
      const clash = other !== null && other !== undefined
                    && sideOf(other) !== sideOf(r.pdc);
      ctx = '<td class="num' + (clash ? ' neg' : '') + '" title="' +
        (clash ? 'the other close basis (' + other + ') gives a different setup'
               : '') + '">' + fmt(r.pdc, 2) + (clash ? ' *' : '') + '</td>' +
        '<td class="num dim">' + pf.val + ' &ndash; ' + pf.vah + '</td>' +
        '<td class="num">' + pf.poc + '</td>';
    }
    if (!rows.length) {
      if (onlyTr) continue;
      body += '<tr><td class="l">' + r.date + '</td><td class="l dim">no</td>' + ctx +
        '<td colspan="14" class="dim">' + r.status + '</td></tr>';
      continue;
    }
    for (const [t, e] of rows) {
      const side = t.side === 'LONG'
        ? '<span class="pill ce">BUY CE</span>' : '<span class="pill pe">BUY PE</span>';
      body += '<tr><td class="l">' + t.date + '</td>' +
        '<td class="l pos">yes</td>' + ctx +
        '<td class="l">' + side + '</td>' +
        '<td class="num">' + n0(e.strike) + '</td>' +
        '<td class="l dim">' + (e.opt_symbol || '&mdash;') + '</td>' +
        '<td class="num">' + fmt(e.entry_px, 2) + '</td>' +
        '<td class="num">' + fmt(e.exit_px, 2) + '</td>' +
        '<td class="l">' + closePill(e.reason) + '</td>' +
        '<td class="num">' + sgn(e.prem_pts) + '</td>' +
        '<td class="num">' + sgnRs(e.pnl_rs) + '</td>' +
        '<td class="num">' + fmt(t.entry, 2) + '</td>' +
        '<td class="num">' + fmt(e.target, 2) + '</td>' +
        '<td class="num">' + fmt(t.sl, 2) + '</td>' +
        '<td class="num">' + fmt(e.exit, 2) + '</td>' +
        '<td class="num">' + sgn(e.points) + '</td>' +
        '<td class="l">' + e.exit_time + '</td>' +
        '<td class="l dim">' + (e.came_back
            ? 'stopped, then reached the target at ' + e.came_back_at +
              ' (' + fmt(e.excess, 1) + ' pts past the stop first)'
            : (e.opt_reason ? e.opt_reason
               : (t.stop_pretraded ? 'stop had already traded in the signal candle' : '')))
        + '</td></tr>';
    }
  }
  $('tblDays').innerHTML = head +
    '<tbody>' + (body || '<tr><td colspan="20" class="dim">no sessions</td></tr>') + '</tbody>';
}

/* ISO-ish week key, good enough to group a year of sessions. */
function weekKey(d) {
  const dt = new Date(d + 'T00:00:00Z');
  const day = (dt.getUTCDay() + 6) % 7;
  dt.setUTCDate(dt.getUTCDate() - day);
  return dt.toISOString().slice(0, 10);
}

function groupRows(keyFn) {
  const g = {};
  for (const [t, e] of tradeRows()) {
    const k = keyFn(t.date);
    const r = g[k] || (g[k] = {key: k, days: new Set(), trades: 0, wins: 0,
                               losses: 0, priced: 0, pnl_pts: 0, pnl_rs: 0,
                               nifty_pts: 0});
    r.days.add(t.date);
    r.trades++;
    r.nifty_pts += e.points;
    // Premium columns only count trades that could actually be priced; the
    // spot column counts every trade.  Mixing the two is how an unpriced
    // trade quietly becomes a break-even one.
    if (e.prem_pts !== null && e.prem_pts !== undefined) {
      r.priced++;
      r.pnl_pts += e.prem_pts;
      r.pnl_rs += (e.pnl_rs || 0);
      if (e.prem_pts > 0) r.wins++; else r.losses++;
    }
  }
  return Object.values(g).sort((a, b) => a.key < b.key ? -1 : 1).map(r => ({
    ...r, days: r.days.size,
    win_rate: r.priced ? r.wins / r.priced * 100 : null,
  }));
}

function summaryTable(el, rows, label) {
  const head = '<thead><tr><th class="l">' + label + '</th><th class="num">Trade days</th>' +
    '<th class="num">Trades</th><th class="num">Priced</th><th class="num">Success</th>' +
    '<th class="num">Fail</th><th class="num">Win %</th><th class="num">Net PnL (pts)</th>' +
    '<th class="num">Net PnL (&#8377;)</th><th class="num">NIFTY pts</th></tr></thead>';
  const body = rows.map(r =>
    '<tr><td class="l">' + r.key + '</td><td class="num">' + r.days + '</td>' +
    '<td class="num">' + r.trades + '</td>' +
    '<td class="num' + (r.priced ? '' : ' dim') + '">' + r.priced + '</td>' +
    '<td class="num pos">' + r.wins + '</td><td class="num neg">' + r.losses + '</td>' +
    '<td class="num">' + (r.win_rate === null ? '<span class="dim">&mdash;</span>'
                                              : r.win_rate.toFixed(1) + '%') + '</td>' +
    '<td class="num">' + (r.priced ? sgn(r.pnl_pts) : '<span class="dim">&mdash;</span>') + '</td>' +
    '<td class="num">' + (r.priced ? sgnRs(r.pnl_rs) : '<span class="dim">&mdash;</span>') + '</td>' +
    '<td class="num">' + sgn(r.nifty_pts, 1) + '</td></tr>').join('');
  el.innerHTML = head + '<tbody>' +
    (body || '<tr><td colspan="10" class="dim">no trades</td></tr>') + '</tbody>';
}

function renderStopBack() {
  const s = DATA.summaries[curTf][curView][curMode][curRr];
  const sw = DATA.stop_sweep || [];
  $('stopBack').innerHTML = s.stopped
    ? '<b>' + s.came_back + ' of ' + s.stopped + ' stopped trades (' +
      fmt(s.back_perc, 1) + '%) later reached the original target</b> before the ' +
      M.square_off + ' square-off. So the complaint is literally true about half ' +
      'the time. The cost of sitting through them is the other half of the ' +
      'question: price ran a median <b>' + fmt(s.excess_med, 1) + ' points</b> past ' +
      'the stop first (90th percentile ' + fmt(s.excess_p90, 1) + '), against a median ' +
      'risk of just ' + fmt(s.med_risk, 1) + ' points &mdash; so a stop that survived ' +
      'them has to be several times wider. And because the target is ' + curRr +
      ' <i>of R</i>, widening the stop pushes the target out by the same multiple. ' +
      'The table below re-runs the entire book at each stop width so that trade ' +
      'is visible rather than assumed.'
    : '<span class="dim">No stopped trades in this selection.</span>';

  let h = '<thead><tr><th class="l">stop</th><th class="num">Trades</th>' +
    '<th class="num">Median risk</th><th class="num">Win %</th><th class="num">Avg R</th>' +
    '<th class="num">Avg prem %</th><th class="num">Priced</th><th class="num">Target</th>' +
    '<th class="num">Stop</th><th class="num">Square-off</th>' +
    '<th class="num">Came back %</th></tr></thead><tbody>';
  for (const w of sw) {
    const cur = Math.abs(w.offset - M.stop_offset) < 1e-9;
    const spec = Math.abs(w.offset - M.spec_stop_offset) < 1e-9
                 && M.stop_at === M.spec_stop_at;
    const tag = (cur ? ' <span class="dim">(this run)</span>' : '') +
                (spec ? ' <span class="dim">(spec)</span>' : '');
    h += '<tr' + (cur ? ' style="outline:1px solid var(--accent)"' : '') + '>' +
      '<td class="l">' + M.stop_at + ' &plusmn;' + w.offset + tag + '</td>' +
      '<td class="num">' + w.trades + '</td>' +
      '<td class="num">' + fmt(w.med_risk, 2) + '</td>' +
      '<td class="num">' + (w.priced ? fmt(w.win_rate, 1) : '<span class="dim">&mdash;</span>') + '</td>' +
      '<td class="num">' + sgn(w.avg_r, 3) + '</td>' +
      '<td class="num">' + (w.priced ? sgn(w.avg_prem_perc) : '<span class="dim">&mdash;</span>') + '</td>' +
      '<td class="num dim">' + w.priced + '</td>' +
      '<td class="num">' + w.targets + '</td><td class="num">' + w.stops + '</td>' +
      '<td class="num">' + w.sqo + '</td>' +
      '<td class="num">' + fmt(w.back_perc, 1) + '</td></tr>';
  }
  $('tblStopSweep').innerHTML = h + '</tbody>';
}

function renderPnlMatrix() {
  let h = '<thead><tr><th class="l">tf \\ R:R</th>' +
    M.rr_keys.map(r => '<th class="num">' + r + '</th>').join('') + '</tr></thead><tbody>';
  for (const tf of M.timeframes) {
    h += '<tr><td class="l">' + tf + 'm</td>';
    for (const rk of M.rr_keys) {
      const s = DATA.summaries[tf][curView][curMode][rk];
      h += '<td class="num' + (tf === curTf && rk === curRr ? ' ' : '') + '">' +
        (s.priced ? sgnRs(s.pnl_rs) : '<span class="dim">&mdash;</span>') +
        '<br><span class="dim" style="font-size:10px">' + s.trades + ' tr</span></td>';
    }
    h += '</tr>';
  }
  $('matrix2').innerHTML = h + '</tbody>';
}

/* ---------- chart ---------- */
const W = 1200, H = 520, PADL = 62, PADR = 186, PADT = 16, PADB = 26;
let chartState = null;
const svg = $('chart'), tip = $('tip');

function renderChart() {
  const day = $('daySel').value;
  const c = DATA.chart_days[day];
  if (!c) { svg.innerHTML = ''; return; }
  // Two sessions end to end: the profiled day, then the traded day. `split` is
  // where the traded day starts, and every trade marker is looked up inside
  // that slice only - both sessions contain a 09:20 candle.
  const prev = ($('showPrev').checked && DATA.chart_prev) ? (DATA.chart_prev[day] || []) : [];
  const all = prev.concat(c);
  chartState = {day: day, prevDay: (DATA.prev_of || {})[day] || null,
                c: all, split: prev.length, i0: 0, i1: all.length,
                prof: DATA.day_profiles[day] || null,
                setup: (DATA.day_setup || {})[day] || null,
                trades: DATA.tf_trades[curTf].filter(t => t.date === day)};
  const p = chartState.prof, su = chartState.setup;
  $('dayTag').textContent = p
    ? 'POC ' + p.poc + '   VAH ' + p.vah + '   VAL ' + p.val + '   (' + p.weight + ')'
    : 'no profile';
  // Step 3 in one line: which side of value yesterday closed on, and therefore
  // which way the POC is being traded today.
  const b = $('setupBanner');
  if (p && su && su.side) {
    const short = su.side === 'SHORT';
    const edge = short ? 'VAL ' + p.val : 'VAH ' + p.vah;
    const gap = short ? (p.val - su.pdc) : (su.pdc - p.vah);
    b.className = 'setup ' + (short ? 'neg' : 'pos');
    // Both closes travel, and when they disagree about the setup the chart
    // would otherwise contradict the trade sitting on it.
    const sideOf = c => c < p.val ? 'SHORT' : (c > p.vah ? 'LONG' : null);
    const other = su.basis === 'last' ? su.pdc_official : su.pdc_last;
    const otherName = su.basis === 'last' ? 'official settlement close'
                                          : '15:29 print on the chart';
    const clash = other !== null && other !== undefined && sideOf(other) !== su.side;
    b.innerHTML = '<b>' + su.side + ' setup</b> &middot; previous close <b>' +
      fmt(su.pdc, 2) + '</b> (' +
      (su.basis === 'last' ? '15:29 print, the last candle drawn'
                           : 'official settlement close') +
      ') closed ' + (short ? 'BELOW ' : 'ABOVE ') + edge +
      ' by ' + fmt(gap, 2) + ' pts &rarr; the POC at <b>' + p.poc + '</b> is ' +
      (short ? 'resistance from below' : 'support from above') +
      (clash ? ' <b class="neg">&middot; the ' + otherName + ' was ' + fmt(other, 2) +
               ', which gives ' + (sideOf(other) || 'NO setup') +
               ' &mdash; the two disagree on this session</b>' : '') +
      (su.reached ? '' : ' &middot; but price never came back to it today') +
      '<br><span style="opacity:.75">The shaded half of the chart is ' +
      (chartState.prevDay || 'the previous session') + ', the session the profile ' +
      'was built from &mdash; the histogram on the right is those bars. Its last ' +
      'candle is where it closed.</span>';
  } else if (p && su) {
    b.className = 'setup dim';
    b.innerHTML = '<b>No setup</b> &middot; previous close <b>' + fmt(su.pdc, 2) +
      '</b> finished INSIDE the value area (' + p.val + ' &ndash; ' + p.vah +
      '), so the POC is not a reversal point and the day is not traded.';
  } else {
    b.className = 'setup dim';
    b.textContent = 'No profile for the previous session.';
  }
  drawChart();
}

function clampWindow(n, a, b) {
  let i0 = Math.max(0, Math.floor(a)), i1 = Math.min(n, Math.ceil(b));
  if (i1 - i0 < 8) { const m = (i0 + i1) / 2; i0 = Math.max(0, Math.floor(m - 4)); i1 = Math.min(n, i0 + 8); }
  return [i0, i1];
}

function drawChart() {
  if (!chartState) return;
  const {c, i0, i1, prof, trades, setup, split} = chartState;
  const view = c.slice(i0, i1);
  if (!view.length) return;
  let lo = Math.min(...view.map(x => x[3])), hi = Math.max(...view.map(x => x[2]));
  if (prof && $('showLevels').checked) {
    lo = Math.min(lo, prof.val); hi = Math.max(hi, prof.vah);
  }
  // The stop and the target are the two levels the trade is decided at, so they
  // are always in view - unlike the previous close, which can sit 200 points
  // away and is clamped instead.
  if ($('showTrades').checked) {
    for (const t of trades) {
      const e = (t.ex[curMode] || {})[curRr];
      if (!e || e.skipped) continue;
      lo = Math.min(lo, t.sl, e.target); hi = Math.max(hi, t.sl, e.target);
    }
  }
  const pad = (hi - lo) * 0.06 || 1;
  lo -= pad; hi += pad;
  const X = i => PADL + (i - i0) / (i1 - i0) * (W - PADL - PADR);
  const Y = p => PADT + (hi - p) / (hi - lo) * (H - PADT - PADB);
  const bw = Math.max(1.2, (W - PADL - PADR) / (i1 - i0) * 0.66);
  let s = '';

  /* The profiled session gets its own tint and a divider, so it is obvious
     which bars the histogram on the right was actually built from. */
  if (split > 0 && split > i0) {
    const xEnd = X(Math.min(split, i1) - 0.5);
    s += '<rect x="' + PADL + '" y="' + PADT + '" width="' + Math.max(0, xEnd - PADL) +
      '" height="' + (H - PADT - PADB) + '" fill="var(--muted)" opacity="0.06"/>';
    if (split < i1)
      s += '<line x1="' + xEnd + '" y1="' + PADT + '" x2="' + xEnd + '" y2="' + (H - PADB) +
        '" stroke="var(--muted)" stroke-width="1.2" stroke-dasharray="4 3" opacity="0.8"/>';
    s += '<text x="' + (PADL + 5) + '" y="' + (PADT + 11) + '" fill="var(--muted)" ' +
      'font-size="10">' + (chartState.prevDay || 'previous') +
      ' \u00b7 profiled session</text>';
    if (split < i1)
      s += '<text x="' + (xEnd + 5) + '" y="' + (PADT + 11) + '" fill="var(--ink2)" ' +
        'font-size="10">' + chartState.day + ' \u00b7 traded session</text>';
  }

  /* grid + price axis */
  const ticks = 6;
  for (let k = 0; k <= ticks; k++) {
    const p = lo + (hi - lo) * k / ticks, y = Y(p);
    s += '<line x1="' + PADL + '" y1="' + y + '" x2="' + (W - PADR) + '" y2="' + y +
      '" stroke="var(--grid)"/>' +
      '<text x="' + (PADL - 6) + '" y="' + (y + 3) + '" fill="var(--muted)" font-size="10" ' +
      'text-anchor="end">' + p.toFixed(0) + '</text>';
  }
  /* time axis */
  const step = Math.max(1, Math.round((i1 - i0) / 10));
  for (let i = i0; i < i1; i += step)
    s += '<text x="' + X(i) + '" y="' + (H - 8) + '" fill="var(--muted)" font-size="10" ' +
      'text-anchor="middle">' + c[i][0] + '</text>';

  /* the profile, drawn on the right like a fixed-range volume profile */
  if (prof && prof.rows && $('showProfile').checked) {
    const maxw = Math.max(...prof.rows.map(r => r.weight)) || 1;
    for (const r of prof.rows) {
      if (r.price_high < lo || r.price_low > hi) continue;
      const y0 = Y(r.price_high), y1 = Y(r.price_low);
      const w = r.weight / maxw * (PADR - 24);
      const inVA = r.price_low >= prof.val && r.price_high <= prof.vah;
      const isPOC = r.price_low <= prof.poc && prof.poc <= r.price_high;
      s += '<rect x="' + (W - PADR + 6) + '" y="' + y0 + '" width="' + Math.max(0.6, w) +
        '" height="' + Math.max(0.8, y1 - y0 - 0.6) + '" fill="' +
        (isPOC ? 'var(--warn)' : (inVA ? 'var(--accent)' : 'var(--muted)')) +
        '" opacity="' + (isPOC ? 0.95 : (inVA ? 0.6 : 0.4)) + '"/>';
    }
    s += '<text x="' + (W - PADR + 6) + '" y="' + (PADT + 9) +
      '" fill="var(--muted)" font-size="10">prev-day profile (' + prof.weight + ')</text>';
  }

  /* The value area as a band, so "below the VAL" and "above the VAH" are a
     position on the chart rather than only numbers in a table. */
  if (prof && $('showLevels').checked) {
    const yTop = Y(Math.min(prof.vah, hi)), yBot = Y(Math.max(prof.val, lo));
    if (yBot > yTop)
      s += '<rect x="' + PADL + '" y="' + yTop + '" width="' + (W - PADL - PADR) +
        '" height="' + (yBot - yTop) + '" fill="var(--accent)" opacity="0.055"/>';
  }

  /* POC / VAH / VAL, extended across the whole session - step 2 */
  if (prof && $('showLevels').checked) {
    const lv = [[prof.poc, 'var(--warn)', 'POC'], [prof.vah, 'var(--accent)', 'VAH'],
                [prof.val, 'var(--accent)', 'VAL']];
    for (const [p, col, lab] of lv) {
      if (p < lo || p > hi) continue;
      s += '<line x1="' + PADL + '" y1="' + Y(p) + '" x2="' + (W - PADR) + '" y2="' + Y(p) +
        '" stroke="' + col + '" stroke-width="1.2" stroke-dasharray="' +
        (lab === 'POC' ? 'none' : '5 4') + '" opacity="0.9"/>' +
        '<text x="' + (PADL + 4) + '" y="' + (Y(p) - 4) + '" fill="' + col +
        '" font-size="10">' + lab + ' ' + p + '</text>';
    }
  }

  /* STEP 3's PRECONDITION: where the previous session closed.  It is often far
     outside today's range - a close below the VAL can sit 200 points under the
     day's low - so it never rescales the chart. When it is off-screen it is
     drawn clamped to the edge with an arrow, which stays honest about direction
     without squashing every candle to make room for it. */
  if (setup && setup.side && prof && $('showPdc').checked) {
    const short = setup.side === 'SHORT';
    const col = short ? 'var(--down)' : 'var(--up)';
    const off = setup.pdc < lo || setup.pdc > hi;
    const y = Math.max(PADT + 10, Math.min(H - PADB - 4, Y(setup.pdc)));
    const arrow = setup.pdc < lo ? ' \u25be' : (setup.pdc > hi ? ' \u25b4' : '');
    s += '<line x1="' + PADL + '" y1="' + y + '" x2="' + (W - PADR) + '" y2="' + y +
      '" stroke="' + col + '" stroke-width="' + (off ? 2 : 1.4) +
      '" stroke-dasharray="2 3" opacity="' + (off ? 0.5 : 0.95) + '"/>' +
      '<text x="' + (W - PADR - 4) + '" y="' + (y - 5) + '" fill="' + col +
      '" font-size="10" text-anchor="end">prev close ' + setup.pdc +
      (off ? ' (off-chart' + arrow + ')' : '') + ' \u00b7 ' +
      (short ? 'below VAL' : 'above VAH') + ' \u2192 ' + setup.side + '</text>';
  }

  /* candles */
  for (let i = i0; i < i1; i++) {
    const [t, o, h2, l2, cl] = c[i];
    const col = cl >= o ? 'var(--up)' : 'var(--down)';
    const x = X(i);
    // The profiled session is context, not the trade - drawn back a little so
    // the eye lands on the day being traded.
    const op = i < split ? ' opacity="0.45"' : '';
    s += '<line x1="' + x + '" y1="' + Y(h2) + '" x2="' + x + '" y2="' + Y(l2) +
      '" stroke="' + col + '" stroke-width="1"' + op + '/>' +
      '<rect x="' + (x - bw / 2) + '" y="' + Y(Math.max(o, cl)) + '" width="' + bw +
      '" height="' + Math.max(1, Math.abs(Y(o) - Y(cl))) + '" fill="' + col + '"' + op + '/>';
  }

  /* entries, stops and targets */
  if ($('showTrades').checked) {
    // Both sessions hold a candle at any given HH:MM, so the search starts at
    // the split - otherwise every marker lands a day early.
    const idxOf = hhmm => {
      for (let k = split; k < c.length; k++) if (c[k][0] === hhmm) return k;
      return -1;
    };
    for (const t of trades) {
      const e = (t.ex[curMode] || {})[curRr];
      if (!e || e.skipped) continue;
      const ix = idxOf(t.entry_time), ex = idxOf(e.exit_time);
      if (ix < 0) continue;
      const x = X(ix), x2 = ex >= 0 ? X(ex) : W - PADR;
      const col = t.side === 'LONG' ? 'var(--up)' : 'var(--down)';
      s += '<rect x="' + x + '" y="' + Y(Math.max(t.entry, e.target)) + '" width="' +
        Math.max(2, x2 - x) + '" height="' + Math.abs(Y(t.entry) - Y(e.target)) +
        '" fill="var(--up)" opacity="0.13"/>' +
        '<rect x="' + x + '" y="' + Y(Math.max(t.entry, t.sl)) + '" width="' +
        Math.max(2, x2 - x) + '" height="' + Math.abs(Y(t.entry) - Y(t.sl)) +
        '" fill="var(--down)" opacity="0.13"/>' +
        '<line x1="' + x + '" y1="' + Y(t.entry) + '" x2="' + x2 + '" y2="' + Y(t.entry) +
        '" stroke="' + col + '" stroke-width="1.3"/>' +
        // The stop and the target as their own labelled levels. Solid, because
        // they are the two prices the trade is actually decided at, and the
        // exit reason says which one got there first.
        '<line x1="' + x + '" y1="' + Y(t.sl) + '" x2="' + x2 + '" y2="' + Y(t.sl) +
        '" stroke="var(--down)" stroke-width="1.4" stroke-dasharray="6 3"/>' +
        '<line x1="' + x + '" y1="' + Y(e.target) + '" x2="' + x2 + '" y2="' + Y(e.target) +
        '" stroke="var(--up)" stroke-width="1.4" stroke-dasharray="6 3"/>' +
        '<text x="' + (x2 + 4) + '" y="' + (Y(t.sl) + 3) + '" fill="var(--down)" ' +
        'font-size="10">SL ' + fmt(t.sl, 2) + (e.reason === 'STOP' ? ' \u2190 hit' : '') + '</text>' +
        '<text x="' + (x2 + 4) + '" y="' + (Y(e.target) + 3) + '" fill="var(--up)" ' +
        'font-size="10">TGT ' + fmt(e.target, 2) +
        (e.reason === 'TARGET' ? ' \u2190 hit' : '') + '</text>' +
        '<text x="' + (x2 + 4) + '" y="' + (Y(t.entry) + 3) + '" fill="' + col +
        '" font-size="10">entry ' + fmt(t.entry, 2) + '</text>' +
        '<circle cx="' + x + '" cy="' + Y(t.entry) + '" r="3.2" fill="' + col + '"/>' +
        '<text x="' + (x + 5) + '" y="' + (Y(t.entry) - 6) + '" fill="' + col +
        '" font-size="10">' + t.side + ' ' + t.entry_time + ' \u00b7 ' + e.reason +
        ' ' + (e.points >= 0 ? '+' : '') + fmt(e.points, 1) + ' pts</text>';
    }
  }
  svg.innerHTML = s;
}

function zoomAt(factor, anchor) {
  if (!chartState) return;
  const {i0, i1, c} = chartState;
  const a = anchor === undefined ? (i0 + i1) / 2 : anchor;
  const w = clampWindow(c.length, a - (a - i0) * factor, a + (i1 - a) * factor);
  chartState.i0 = w[0]; chartState.i1 = w[1];
  drawChart();
}
function resetZoom() {
  if (!chartState) return;
  chartState.i0 = 0; chartState.i1 = chartState.c.length; drawChart();
}
function idxAt(clientX, box) {
  const px = (clientX - box.left) / box.width * W;
  return chartState.i0 + (px - PADL) / (W - PADL - PADR) * (chartState.i1 - chartState.i0);
}
svg.addEventListener('wheel', e => {
  if (!chartState) return;
  e.preventDefault();
  zoomAt(e.deltaY < 0 ? 0.82 : 1.22, idxAt(e.clientX, svg.getBoundingClientRect()));
}, {passive: false});
let drag = null;
svg.addEventListener('pointerdown', e => {
  if (!chartState) return;
  drag = {x: e.clientX, i0: chartState.i0, i1: chartState.i1};
  svg.classList.add('drag');
  try { svg.setPointerCapture(e.pointerId); } catch (_) {}
});
svg.addEventListener('pointerup', e => {
  drag = null; svg.classList.remove('drag');
  try { svg.releasePointerCapture(e.pointerId); } catch (_) {}
});
svg.addEventListener('dblclick', resetZoom);
svg.addEventListener('pointermove', e => {
  if (!chartState) return;
  const box = svg.getBoundingClientRect();
  if (drag) {
    const dx = (e.clientX - drag.x) / box.width * W;
    const perPx = (drag.i1 - drag.i0) / (W - PADL - PADR);
    const w = clampWindow(chartState.c.length, drag.i0 - dx * perPx, drag.i1 - dx * perPx);
    chartState.i0 = w[0]; chartState.i1 = w[1];
    drawChart(); tip.style.display = 'none';
    return;
  }
  const i = Math.round(idxAt(e.clientX, box) - 0.5), c = chartState.c;
  if (i < 0 || i >= c.length) { tip.style.display = 'none'; return; }
  tip.innerHTML = '<b>' + c[i][0] + '</b> <span style="opacity:.65">' +
    (c[i][5] || chartState.day) + (i < chartState.split ? ' (profiled)' : '') +
    '</span><br>O ' + c[i][1].toFixed(2) + '<br>H ' + c[i][2].toFixed(2) +
    '<br>L ' + c[i][3].toFixed(2) + '<br>C ' + c[i][4].toFixed(2);
  tip.style.display = 'block';
  tip.style.left = Math.min(e.clientX + 14, window.innerWidth - 120) + 'px';
  tip.style.top = Math.max(4, e.clientY - 60) + 'px';
});
svg.addEventListener('pointerleave', () => { tip.style.display = 'none'; });

/* ---------- wiring ---------- */
fill($('selTf'), M.timeframes.map(t => ({k: t, v: t + '-minute'})), curTf);
fill($('selRr'), M.rr_keys.map(r => ({k: r, v: r})), curRr);
fill($('selMode'), M.modes.map(m => ({k: m.key, v: m.key + ' - ' + m.label})), curMode);
fill($('selView'), M.views.map(v => ({k: v.key, v: v.label})), curView);
if (M.modes.length < 2) $('modeCtl').style.display = 'none';

function renderAll() {
  renderFunnel(); renderNet(); renderCards(); renderMatrix();
  renderHalves(); renderYears();
  const sel = $('daySel');
  const days = Object.keys(DATA.chart_days).sort();
  const keep = sel.value;
  sel.innerHTML = days.map(d => '<option' + (d === keep ? ' selected' : '') + '>' + d + '</option>').join('');
  if (!keep && days.length) sel.value = days[0];
  renderChart();
  renderPnlMatrix();
  renderStopBack();
  renderDays();
  summaryTable($('tblWeekly'), groupRows(d => 'w/c ' + weekKey(d)), 'Week');
  summaryTable($('tblMonthly'), groupRows(d => d.slice(0, 7)), 'Month');
}
$('selTf').onchange = e => { curTf = e.target.value; renderAll(); };
$('selRr').onchange = e => { curRr = e.target.value; renderAll(); };
$('selMode').onchange = e => { curMode = e.target.value; renderAll(); };
$('selView').onchange = e => { curView = e.target.value; renderAll(); };
$('daySel').onchange = renderChart;
$('showProfile').onchange = drawChart;
$('showLevels').onchange = drawChart;
$('showPdc').onchange = drawChart;
$('showPrev').onchange = renderChart;
$('showTrades').onchange = drawChart;
$('onlyPre').onchange = () => { renderDays(); renderAll(); };
$('onlyTrades').onchange = renderDays;
$('zoomIn').onclick = () => zoomAt(0.7);
$('zoomOut').onclick = () => zoomAt(1.4);
$('zoomReset').onclick = resetZoom;
renderAll();
</script>
</body>
</html>
"""


def write_report(payload: dict, out_path: str) -> None:
    html = HTML_TEMPLATE.replace("__DATA_JSON__",
                                 json.dumps(payload, separators=(",", ":")))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  report {len(html) / 1e6:.1f} MB")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

async def run(args) -> None:
    candles = await load_nifty(args.offline, args.from_date, args.to_date)
    by_day = index_by_day(candles)
    days = sorted(d for d in by_day
                  if args.from_date.isoformat() <= d <= args.to_date.isoformat())
    if len(days) < 2:
        raise RuntimeError("Need at least two sessions: one to profile, one to trade.")
    daily_close = await load_daily(args.offline, args.from_date, args.to_date)

    keys = rr_keys(args.rr_values)
    views = [k for k, _ in VIEWS]
    pairs = list(zip(days, days[1:]))          # (profile day, trading day)

    # ---- two passes, and the order is the point ---------------------------
    # Pass 1 runs the rule on SPOT alone.  Entry, stop and target are decided
    # there and nowhere else; the option cannot move a level or change which
    # trades exist.  Only once the signals are known are the ATM contracts they
    # imply resolved and fetched.  Pass 2 re-runs the identical simulation with
    # those prices available, purely so each trade carries a premium.
    global PRICER
    needs = set()
    for tf in TIMEFRAMES:
        for prev, day in pairs:
            row = simulate_day(day, by_day[prev], by_day[day], tf, args,
                               daily_close.get(prev))
            for t in row["trades"]:
                if t.get("ex"):
                    needs.add((t["date"], t["side"], t["entry"]))
    print(f"  {len(needs)} distinct (day, side, entry) signals to price")
    PRICER = await ensure_cached(
        needs, None if args.offline else _read_access_token(), args.offline,
        roll=args.expiry_roll)

    tf_rows: dict[str, list[dict]] = {}
    tf_trades: dict[str, list[dict]] = {}
    for tf in TIMEFRAMES:
        rows = [simulate_day(day, by_day[prev], by_day[day], tf, args,
                             daily_close.get(prev), pricer=PRICER)
                for prev, day in pairs]
        tf_rows[str(tf)] = rows
        tf_trades[str(tf)] = [t for r in rows for t in r["trades"] if t.get("ex")]

    summaries = {
        str(tf): {v: {m: {rk: summarise(
                        [t for t in tf_trades[str(tf)] if in_view(t, v)], m, rk)
                      for rk in keys}
                  for m in args.modes}
                  for v in views}
        for tf in TIMEFRAMES}

    # ---- split-half -------------------------------------------------------
    # Row size, the value area and the timeframe were all chosen rather than
    # given.  Reporting each combination over the first and second half of the
    # sessions is the cheapest guard against shipping a number that lives in
    # only one half.  A setting that flips sign here is not demonstrated.
    mid = pairs[len(pairs) // 2][1]

    def half(trades, which):
        return ([t for t in trades if t["date"] < mid] if which == "h1"
                else [t for t in trades if t["date"] >= mid])

    halves = {
        str(tf): {h: {m: {rk: summarise(half(tf_trades[str(tf)], h), m, rk)
                          for rk in keys}
                      for m in args.modes}
                  for h in ("h1", "h2")}
        for tf in TIMEFRAMES}

    # ---- per-year, because 4.7 years is long enough to hold regimes --------
    years = sorted({d[:4] for _, d in pairs})
    per_year = {
        str(tf): {y: summarise([t for t in tf_trades[str(tf)] if t["date"][:4] == y],
                               args.mode, rr_label(args.default_rr))
                  for y in years}
        for tf in TIMEFRAMES}

    trade_days = sorted({t["date"] for tf in TIMEFRAMES for t in tf_trades[str(tf)]})
    def bars_for(d):
        return [[c["timestamp"][11:16], round(float(c["open"]), 2),
                 round(float(c["high"]), 2), round(float(c["low"]), 2),
                 round(float(c["close"]), 2), d]
                for c in by_day[d] if SESSION_START <= c["timestamp"][11:16] <= DAY_END]

    chart_days = {d: bars_for(d) for d in trade_days}
    # The session the profile was built from, drawn to the LEFT of the trading
    # day so the histogram can be read against the bars that produced it.
    prev_of = {d: pv for pv, d in pairs}
    chart_prev = {d: bars_for(prev_of[d]) for d in trade_days if prev_of.get(d)}
    day_profiles = {r["date"]: r["profile"]
                    for r in tf_rows[str(args.tf)]
                    if r["date"] in chart_days and r["profile"]}
    # Step 3's precondition, per session, so the chart can show WHY a day is a
    # short or a long rather than only showing the three levels it trades off.
    # Both closes travel: `pdc` is the one the rule was evaluated on and
    # `pdc_last` the 15:29 print, and they are not the same number.
    day_setup = {r["date"]: {"pdc": r["pdc"], "pdc_last": r["pdc_last"],
                             "pdc_official": r.get("pdc_official"),
                             "side": r["side"], "basis": args.pdc_basis,
                             "reached": bool(r.get("reached_poc")),
                             "status": r["status"]}
                 for r in tf_rows[str(args.tf)]
                 if r["date"] in chart_days and r["profile"]}

    unpriced = sum(1 for tf in TIMEFRAMES for t in tf_trades[str(tf)]
                   for m in args.modes for rk in keys
                   if t["ex"].get(m, {}).get(rk, {}).get("opt_reason"))

    # ---- stop-offset sweep ------------------------------------------------
    # Widening the stop is the obvious response to a high stop rate, so it is
    # computed rather than argued about.  The target is 2R of the NEW risk at
    # every rung, which is the whole point: a wider stop buys survival and sells
    # reachability, and only the book can say which wins.
    stop_sweep = []
    for off in args.stop_sweep:
        sa = argparse.Namespace(**vars(args))
        sa.stop_offset = off
        rows_o = [simulate_day(d, by_day[pv], by_day[d], args.tf, sa,
                               daily_close.get(pv), pricer=PRICER)
                  for pv, d in pairs]
        tr_o = [t for r in rows_o for t in r["trades"] if t.get("ex")]
        o = summarise(tr_o, args.mode, rr_label(args.default_rr))
        stop_sweep.append({"offset": off, **o})

    # ---- funnel, per timeframe -------------------------------------------
    # This rule's trade count is NOT limited by the close-outside-value test.
    # It is limited by price coming BACK to the POC the next day.  The funnel
    # is reported so that is visible rather than inferred.
    funnel = {}
    for tf in TIMEFRAMES:
        rows = tf_rows[str(tf)]
        funnel[str(tf)] = {
            "sessions": len(rows),
            "setup": sum(1 for r in rows if r.get("broke")),
            "short_setup": sum(1 for r in rows for t in r["trades"]
                               if t["side"] == "SHORT"),
            "long_setup": sum(1 for r in rows for t in r["trades"]
                              if t["side"] == "LONG"),
            "reached": sum(1 for r in rows if r.get("retested")),
            "confirmed": sum(1 for r in rows if r["signals"]),
            "signals": sum(r["signals"] for r in rows),
            "placeable": len(tf_trades[str(tf)]),
            "unplaceable": sum(1 for r in rows for t in r["trades"] if not t.get("ex")),
        }

    payload = {
        "meta": {
            "from": pairs[0][1], "to": pairs[-1][1], "sessions": len(pairs),
            "timeframes": [str(tf) for tf in TIMEFRAMES], "default_tf": str(args.tf),
            "profile_tf": args.profile_tf, "row_size": args.row_size,
            "value_area": args.value_area,
            "weight": args.weight, "weight_label": dict(WEIGHTS)[args.weight],
            "stop_offset": args.stop_offset,
            "spec_stop_offset": SPEC_STOP_OFFSET,
            "spec_stop_at": SPEC_STOP_AT,
            "stop_tuned": (args.stop_at != SPEC_STOP_AT
                           or abs(args.stop_offset - SPEC_STOP_OFFSET) > 1e-9),
            "stop_at": args.stop_at, "stop_at_label": dict(STOP_MODES)[args.stop_at],
            "wait_min": args.wait_min, "wait_max": args.wait_max,
            "confirm": args.confirm, "confirm_label": dict(CONFIRMS)[args.confirm],
            "acceptance": args.acceptance,
            "band_offset": args.stop_offset,
            "t_stat": None, "ci_lo": None, "ci_hi": None,
            "entry_mode": "next",
            "entry_label": "Open of the candle after the confirming close",
            "long_reading": args.long_reading,
            "long_label": dict(LONG_READINGS)[args.long_reading],
            "pdc_basis": args.pdc_basis, "pdc_label": dict(PDC_BASES)[args.pdc_basis],
            "require_approach": False,
            "rr_keys": keys, "default_rr": rr_label(args.default_rr),
            "min_rr": MIN_RR,
            "modes": [{"key": k, "label": v} for k, v in TRADE_MODES if k in args.modes],
            "default_mode": args.mode,
            "views": [{"key": k, "label": v} for k, v in VIEWS],
            "default_view": args.view,
            "min_risk": args.min_risk, "entry_until": args.entry_until,
            "eod": args.eod, "eod_label": dict(EOD_MODES)[args.eod],
            "square_off": args.square_off, "session_start": args.session_start,
            "expiry_roll": args.expiry_roll,
            "expiry_roll_label": dict(ROLL_MODES)[args.expiry_roll],
            "lot": LOT_SIZE, "unpriced": unpriced, "years": years,
            "generated": date.today().isoformat(),
        },
        "summaries": summaries, "halves": halves, "split_at": mid,
        "per_year": per_year, "funnel": funnel, "stop_sweep": stop_sweep,
        # The row histogram is identical on every timeframe and the chart reads
        # it from day_profiles, so carrying it three more times here only made
        # the report bigger.  Levels stay; the ~90 rows per session go.
        "tf_days": {k: [{**r, "profile": ({kk: vv for kk, vv in r["profile"].items()
                                           if kk != "rows"} if r["profile"] else None)}
                        for r in v]
                    for k, v in tf_rows.items()},
        "tf_trades": tf_trades,
        "chart_days": chart_days, "day_profiles": day_profiles,
        "chart_prev": chart_prev,
        "prev_of": {d: prev_of[d] for d in trade_days if prev_of.get(d)},
        "day_setup": day_setup,
    }

    # A mean without its interval invites reading noise as a result, so the
    # headline cell's t and 95% interval travel in the meta and the report
    # cannot show one without the other.
    _rk = rr_label(args.default_rr)
    _R = [t["ex"][args.mode][_rk]["r_multiple"] for t in tf_trades[str(args.tf)]
          if not t["ex"].get(args.mode, {}).get(_rk, {}).get("skipped", True)]
    if len(_R) > 1:
        _m = sum(_R) / len(_R)
        _v = sum((x - _m) ** 2 for x in _R) / (len(_R) - 1)
        _se = (_v / len(_R)) ** 0.5
        if _se:
            payload["meta"]["t_stat"] = round(_m / _se, 2)
            payload["meta"]["ci_lo"] = round(_m - 1.96 * _se, 3)
            payload["meta"]["ci_hi"] = round(_m + 1.96 * _se, 3)
    write_report(payload, args.out)
    write_csv(tf_trades, args.modes, keys, args.csv)

    # ---- console ----------------------------------------------------------
    print(f"\n{len(pairs)} traded sessions {pairs[0][1]} -> {pairs[-1][1]}")
    if (args.stop_at != SPEC_STOP_AT
            or abs(args.stop_offset - SPEC_STOP_OFFSET) > 1e-9):
        print(f"  ! STOP IS TUNED: {args.stop_at} +/-{args.stop_offset:g}, not the "
              f"spec's {SPEC_STOP_AT} +/-{SPEC_STOP_OFFSET:g}. The basis and the "
              f"width were both chosen off this sample, so neither is demonstrated "
              f"out of sample. --stop-at {SPEC_STOP_AT} --stop-offset "
              f"{SPEC_STOP_OFFSET:g} restores the rule as written.")
    print(f"  profile: {args.weight} weighting, {args.profile_tf}-minute bars, "
          f"{args.row_size:g}-point rows, {args.value_area:.0%} value area")
    for tf in TIMEFRAMES:
        f = funnel[str(tf)]
        print(f"\n  {tf}-minute")
        print(f"    setup (closed outside value)  {f['setup']:>5} / {f['sessions']}"
              f"   short {f['short_setup']}  long {f['long_setup']}")
        print(f"    price came back to the POC    {f['reached']:>5}"
              f"   <- the binding constraint")
        print(f"    confirmed (swept + closed)    {f['confirmed']:>5}"
              f"   {f['signals']} signals")
        print(f"    placeable                     {f['placeable']:>5}"
              f"   {f['unplaceable']} rejected on signed risk")
        for m in args.modes:
            for rk in keys:
                o = summaries[str(tf)]["both"][m][rk]
                if not o["trades"]:
                    continue
                print(f"    {m:<7} {rk:<5}: {o['trades']:>4} tr "
                      f"{o['wins']}W/{o['losses']}L  win {o['win_rate']:>5}%  "
                      f"avg prem {o['avg_prem_perc']:>7}%  avg R {o['avg_r']:>6}  "
                      f"Rs {o['pnl_rs']:>10,.0f}")
        o = summaries[str(tf)]["both"][args.mode][rr_label(args.default_rr)]
        if o["trades"]:
            print(f"    risk: median {o['med_risk']:g} pts, mean {o['avg_risk']:g}"
                  f"   |   stop already traded in the signal candle: "
                  f"{o['pretraded']}/{o['trades']} = {o['pretraded_perc']}%")
            print(f"    exits: {o['targets']} target, {o['stops']} stop, "
                  f"{o['sqo']} square-off, {o['eod']} EOD")
            if o["stopped"]:
                print(f"    after the stop: {o['came_back']}/{o['stopped']} = "
                      f"{o['back_perc']}% later reached the ORIGINAL target; to "
                      f"sit through them the stop needed a median "
                      f"{o['excess_med']:g} more points (p90 {o['excess_p90']:g})")

    print(f"\n  SPLIT-HALF at {mid}, judged on avg R - a setting that flips "
          f"sign here is not demonstrated, whatever the full-sample number says.")
    # Why R and not premium %: on a window reaching back before 2024-10 the
    # first half has nothing priced and its premium column would read 0.0%
    # from ABSENCE.  On a 12-month window both halves are priced and the
    # premium split is worth reading too, so say which case this run is.
    rk0 = rr_label(args.default_rr)
    h1_priced = sum(halves[str(tf)]["h1"][m][rk0]["priced"]
                    for tf in TIMEFRAMES for m in args.modes)
    h2_priced = sum(halves[str(tf)]["h2"][m][rk0]["priced"]
                    for tf in TIMEFRAMES for m in args.modes)
    if not h1_priced or not h2_priced:
        print(f"  R and NOT premium %: this window reaches back past the "
              f"2024-10 start of the option archive, so a half with nothing "
              f"priced would read 0.0% from ABSENCE, not from measurement.")
    else:
        print(f"  Judged on R because R covers every trade; both halves are "
              f"priced here ({h1_priced} / {h2_priced}), so the premium split "
              f"underneath each row is readable too.")
    rk = rr_label(args.default_rr)
    for tf in TIMEFRAMES:
        for m in args.modes:
            f_ = summaries[str(tf)]["both"][m][rk]
            a, b = halves[str(tf)]["h1"][m][rk], halves[str(tf)]["h2"][m][rk]
            if not f_["trades"]:
                continue
            agree = ("" if (a["avg_r"] >= 0) == (b["avg_r"] >= 0)
                     else "   <-- HALVES DISAGREE")
            print(f"    {tf}m {m:<7} {rk:<5} full R {f_['avg_r']:>7} "
                  f"({f_['trades']:>4} tr)   h1 {a['avg_r']:>7} ({a['trades']:>3} tr)"
                  f"   h2 {b['avg_r']:>7} ({b['trades']:>3} tr){agree}")
            ap = f"{a['avg_prem_perc']}%" if a["priced"] else "unpriced"
            bp = f"{b['avg_prem_perc']}%" if b["priced"] else "unpriced"
            print(f"        premium %: full {f_['avg_prem_perc']:>7}% "
                  f"({f_['priced']:>3} priced)   h1 {ap:>9} ({a['priced']:>3})"
                  f"   h2 {bp:>9} ({b['priced']:>3})")

    print(f"\n  WIDER STOPS ({args.tf}m, {args.mode}, {rk}) - target stays at "
          f"2R of the NEW risk, so widening moves the target out too")
    for w in stop_sweep:
        prem = f"{w['avg_prem_perc']:>7}%" if w["priced"] else " unpriced"
        print(f"    {args.stop_at} +/-{w['offset']:>4g}: {w['trades']:>4} tr  "
              f"medRisk {w['med_risk']:>6.2f}  avg R {w['avg_r']:>7}  "
              f"prem {prem}  tgt {w['targets']:>3} stop {w['stops']:>3}  "
              f"back {w['back_perc']:>5}%")

    print(f"\n  PER YEAR ({args.tf}m, {args.mode}, {rk})")
    for y in years:
        o = per_year[str(args.tf)][y]
        if not o["trades"]:
            continue
        prem = f"{o['avg_prem_perc']:>8}%" if o["priced"] else "  unpriced"
        win = f"{o['win_rate']:>5}%" if o["priced"] else "    -"
        print(f"    {y}: {o['trades']:>3} tr ({o['priced']:>3} priced)  win {win}  "
              f"avg prem {prem}  avg R {o['avg_r']:>7}  "
              f"Rs {o['pnl_rs']:>10,.0f}")

    if unpriced:
        print(f"\n  ! {unpriced} trade-variants had no option data and are "
              f"excluded from every percentage (option history starts 2024-10)")
    print(f"\nReport: {args.out}")
    print(f"Trades: {args.csv}")


def write_csv(tf_trades: dict, modes: list[str], keys: list[str], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    cols = ["date", "tf", "side", "trade_mode", "rr", "signal_time", "entry_time",
            "entry", "sl", "risk", "stop_pretraded", "poc", "vah", "val",
            "sweep_high", "sweep_low", "sweep_close", "target", "exit",
            "exit_time", "reason", "points", "r_multiple", "slip",
            "opt_symbol", "strike", "opt_type", "entry_px", "exit_px",
            "prem_pts", "prem_perc", "pnl_rs", "opt_reason"]
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for tf, trades in sorted(tf_trades.items(), key=lambda kv: int(kv[0])):
            for t in trades:
                for m in modes:
                    for rk in keys:
                        e = t["ex"].get(m, {}).get(rk)
                        if not e or e.get("skipped"):
                            continue
                        w.writerow({**t, **e, "tf": tf, "trade_mode": m, "rr": rk})
                        n += 1
    print(f"  {n} trade-variant rows -> {os.path.basename(path)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    today = date.today()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tf", type=int, choices=TIMEFRAMES, default=DEFAULT_TF,
                    help="signal timeframe the report opens on; all are computed")
    ap.add_argument("--profile-tf", type=int, default=PROFILE_TF,
                    help="candle size the previous day is profiled on (step 2 says 5)")
    ap.add_argument("--row-size", type=float, default=DEFAULT_ROW_SIZE,
                    help="profile row height in points - decides where the POC "
                         "lands and therefore every entry and stop")
    ap.add_argument("--value-area", type=float, default=DEFAULT_VALUE_AREA,
                    help="fraction of the profile inside the value area")
    ap.add_argument("--weight", choices=WEIGHT_KEYS, default="tpo",
                    help="tpo: time per row (the only option on the index, which "
                         "reports no volume). volume: traded quantity - raises on "
                         "a zero-volume series rather than returning zeros")
    ap.add_argument("--stop-at", choices=STOP_KEYS, default=DEFAULT_STOP,
                    help="poc: 5 points beyond the POC (the spec). sweep: 5 points "
                         "beyond the sweep candle's extreme")
    ap.add_argument("--stop-offset", type=float, default=STOP_OFFSET,
                    help=f"points beyond the stop basis. Default {STOP_OFFSET:g} "
                         f"was chosen off this sample, not given by the spec; "
                         f"pass {SPEC_STOP_OFFSET:g} for the rule as written")
    ap.add_argument("--stop-sweep", type=float, nargs="+", default=None,
                    metavar="PTS",
                    help="stop offsets to re-run the whole book at, so the "
                         "cost of widening the stop is visible rather than "
                         "argued about")
    ap.add_argument("--confirm", choices=[k for k, _ in CONFIRMS],
                    default=DEFAULT_CONFIRM,
                    help="what counts as the retest confirming: close (reach the "
                         "band and close beyond it), touch, or two-candle")
    ap.add_argument("--acceptance", type=int, default=DEFAULT_ACCEPTANCE,
                    help="candles price must have CLOSED outside the band before "
                         "losing it counts - the 'traded above the VAH' part")
    ap.add_argument("--wait-min", type=int, default=WAIT_MIN,
                    help="earliest candle after the break at which a retest counts")
    ap.add_argument("--wait-max", type=int, default=WAIT_MAX,
                    help="latest candle after the break at which a retest counts")
    ap.add_argument("--pdc-basis", choices=[k for k, _ in PDC_BASES],
                    default=DEFAULT_PDC,
                    help="which previous close step 3 compares against value")
    ap.add_argument("--rr", dest="rr_values", type=float, nargs="+",
                    default=RR_VALUES, metavar="R",
                    help=f"the R:R ladder. 1:{MIN_RR:g} is the FLOOR - a rung "
                         f"below it is refused")
    ap.add_argument("--target", dest="default_rr", type=float, default=DEFAULT_RR,
                    help=f"which rung the report opens on. Minimum "
                         f"1:{MIN_RR:g}")
    ap.add_argument("--mode", choices=[k for k, _ in TRADE_MODES],
                    default=DEFAULT_MODE, help="trade-count policy on open")
    ap.add_argument("--modes", nargs="+", choices=[k for k, _ in TRADE_MODES],
                    default=None,
                    help="which trade-count policies to compute. Default is "
                         "session alone - one trade per day")
    ap.add_argument("--view", choices=[k for k, _ in VIEWS], default=DEFAULT_VIEW)
    ap.add_argument("--min-risk", type=float, default=MIN_RISK,
                    help="reject a signal whose SIGNED risk is under this many "
                         "points (0 disables the floor)")
    ap.add_argument("--entry-until", default=None,
                    help="no new entry at or after this time (default: square-off)")
    ap.add_argument("--expiry-roll", choices=[k for k, _ in ROLL_MODES],
                    default=DEFAULT_ROLL,
                    help="which expiry to buy: none, zero-dte, always")
    ap.add_argument("--eod", choices=[k for k, _ in EOD_MODES], default=DEFAULT_EOD)
    ap.add_argument("--square-off", default=SQUARE_OFF)
    ap.add_argument("--session-start", default=SESSION_START)
    ap.add_argument("--offline", action="store_true", help="use local caches only")
    ap.add_argument("--out", default=REPORT_HTML)
    ap.add_argument("--csv", default=TRADES_CSV)
    # DEFAULT WINDOW IS 6 MONTHS, set by the user on 2026-09-18.  A 6-month run
    # is the one to look at day to day: it finishes fast, its option coverage is
    # near-complete (the expired-option archive starts 2024-10), and it is the
    # window the report is read on.  The cost is sample: this rule fires about
    # 2 trades a week, so 6 months is ~55 trades and can only resolve an edge of
    # roughly +-0.37 R.  Stability claims belong to a wider run, not to this one.
    ap.add_argument("--from", dest="from_date", type=date.fromisoformat,
                    default=today - timedelta(days=183),
                    help="default: 6 months back. Pass --from 2022-01-01 for the "
                         "full cached history (the 1m feed starts 2022-01-03)")
    ap.add_argument("--to", dest="to_date", type=date.fromisoformat, default=today)
    args = ap.parse_args()

    if args.stop_sweep is None:
        args.stop_sweep = (ENTRY_STOP_SWEEP if args.stop_at == "entry"
                           else STOP_SWEEP)
    if args.entry_until is None:
        args.entry_until = args.square_off
    args.long_reading = DEFAULT_LONG
    args.modes = args.modes or DEFAULT_MODES
    if args.mode not in args.modes:
        args.mode = args.modes[0]
    below = [r for r in args.rr_values if r < MIN_RR]
    if below:
        ap.error(f"--rr {' '.join(f'{r:g}' for r in below)} is under the "
                 f"1:{MIN_RR:g} floor; the target is a MINIMUM of "
                 f"1:{MIN_RR:g}. Pass --rr {MIN_RR:g} or higher.")
    if args.default_rr not in args.rr_values:
        args.default_rr = args.rr_values[0]
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
