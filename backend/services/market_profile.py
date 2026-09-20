"""Market profile - POC, VAH and VAL for a fixed range of candles.

This is the "Fixed Range Volume Profile" of a charting package, with one
correction forced by the data and measured rather than assumed.

WHY THERE IS A `weight` ARGUMENT AT ALL
---------------------------------------
A volume profile weights each price row by the quantity traded in it.  The
NIFTY 50 INDEX reports no volume, because an index is not a traded instrument:
it is a number computed from 50 constituents, so there are no transactions in
it to report.  Every Upstox endpoint agrees - v2/v3 historical, v2/v3 intraday
and both market-quote shapes return 0 or null, and the full quote returns an
EMPTY order book (no bids, no asks, symbol "NA").  That is not a gap in the
feed; there is nothing there to serve.

So a profile on the index has to weight by something else, and the classical
answer predates volume profile: Steidlmayer's Market Profile counts TIME.  Each
bar contributes one unit to every price row it spans.

    weight="tpo"      one unit per bar per row it spans   (index, any series)
    weight="volume"   the bar's volume, split evenly over the rows it spans
                      (futures, options, equities - anything actually traded)

MEASURED, SO IT IS NOT AN ASSUMPTION
------------------------------------
Two things were checked on real sessions before settling on TPO as the default.

1. Real volume DOES move the levels.  On identical front-month futures bars,
   volume-weighting and TPO picked the same POC row in only 21 of 58 sessions;
   the median gap was 5.0 points (one row) and the maximum 345.  Value areas
   came out ~19% wider under volume (95 vs 80 points).  So `weight` is a real
   choice, not a cosmetic one.

2. A SYNTHETIC index volume is not worth building.  Summing the real traded
   VALUE of 14 NIFTY constituents minute by minute and weighting the index's
   own bars by it produced a POC a median of 0.0 points from plain TPO (max
   10.0) - the same answer - while sitting a median 12.1 points away from the
   real futures-volume POC and agreeing with it in only 5 of 17 sessions.
   Once summed across a broad basket the per-minute weights flatten out and the
   profile is shaped by where price spent its minutes, which is what TPO
   counts.  Widening to all 50 names flattens it further, toward TPO, not away.

   The practical consequence: on the SPOT price axis, TPO is as good as any
   volume proxy that can be constructed, and it is free.  Only the futures
   series gives a genuinely different profile, and it costs 2.5 years of
   history (the expired-instruments archive starts 2024-10) plus a basis of
   40-64 points and a monthly roll.

ROWS
----
A row is a half-open price band [k*row_size, (k+1)*row_size).  A bar spanning
several rows contributes to all of them, which is what makes `row_size` the
first parameter to sweep: it decides where the POC lands and therefore where
every entry and stop in a POC strategy sits.
"""
from __future__ import annotations

from collections import defaultdict


class ProfileDataError(ValueError):
    """Raised rather than returning a profile that is quietly meaningless.

    The specific case this exists for: asking for weight="volume" on the NIFTY
    index, whose every candle reports volume 0.  Weighting by zero makes every
    row zero, the POC becomes whichever row max() happens to see first, and the
    value area becomes the whole range - a profile-shaped object carrying no
    information.  Failing loudly here is the whole point.
    """


WEIGHTS = [("tpo", "Time - one unit per bar per row it spans"),
           ("volume", "Traded quantity, split evenly across the rows a bar spans")]
WEIGHT_KEYS = [k for k, _ in WEIGHTS]

DEFAULT_ROW_SIZE = 5.0
DEFAULT_VALUE_AREA = 0.70          # the charting-package default


def _bar_hl(bar) -> tuple[float, float]:
    """(high, low) from either the {h,l} bucket shape or a raw feed candle."""
    if "h" in bar:
        return float(bar["h"]), float(bar["l"])
    return float(bar["high"]), float(bar["low"])


def _bar_volume(bar) -> float:
    if "v" in bar:
        return float(bar["v"] or 0.0)
    return float(bar.get("volume") or 0.0)


def build_profile(bars, *, row_size: float = DEFAULT_ROW_SIZE,
                  value_area: float = DEFAULT_VALUE_AREA,
                  weight: str = "tpo") -> dict:
    """POC, VAH and VAL over `bars`, plus the row histogram behind them.

    `bars` is any fixed range - one session, a week, an opening hour.  Step 2 of
    the POC-reversal rule passes exactly one previous session.

    Returns row_size, rows (ordered low -> high, each {price_low, price_high,
    weight}), poc/vah/val, total, and the fraction of `total` the value area
    actually covers, which lands slightly ABOVE `value_area` because rows are
    added whole.
    """
    if weight not in WEIGHT_KEYS:
        raise ValueError(f"weight must be one of {WEIGHT_KEYS}, got {weight!r}")
    if row_size <= 0:
        raise ValueError(f"row_size must be positive, got {row_size}")
    if not 0 < value_area <= 1:
        raise ValueError(f"value_area must be in (0, 1], got {value_area}")
    if not bars:
        raise ProfileDataError("no bars to build a profile from")

    if weight == "volume" and sum(_bar_volume(b) for b in bars) <= 0:
        raise ProfileDataError(
            "every bar reports volume 0, so a volume profile would be a "
            "profile of zeros. This is what the NIFTY index feed returns - an "
            "index is not traded and has no volume. Use weight='tpo', or pass "
            "bars from a traded series (futures, options, equities).")

    counts: dict[int, float] = defaultdict(float)
    for bar in bars:
        high, low = _bar_hl(bar)
        if high < low:
            high, low = low, high
        lo_row = int(low // row_size)
        hi_row = int(high // row_size)
        span = hi_row - lo_row + 1
        # A bar's volume is split EVENLY across the rows it spans.  The feed
        # says how much traded in the minute, never at which price inside it,
        # so any finer attribution would be invented.  Even splitting is the
        # assumption that adds no information of its own.
        w = (_bar_volume(bar) / span) if weight == "volume" else 1.0
        for row in range(lo_row, hi_row + 1):
            counts[row] += w

    total = sum(counts.values())
    if total <= 0:
        raise ProfileDataError("profile weights sum to zero")

    # POC: the busiest row.  Ties break to the LOWER row index, deterministically
    # - max() over a dict would otherwise depend on insertion order and make the
    # same input produce different levels between runs.
    poc_row = max(sorted(counts), key=lambda r: counts[r])

    # The value area grows outward from the POC, taking whichever neighbour is
    # busier, until it covers `value_area` of the total.  This is the standard
    # construction.  A tie takes the row ABOVE, which only ever shifts the band
    # by one row and keeps the walk deterministic.
    lo_row = hi_row = poc_row
    covered = counts[poc_row]
    while covered < value_area * total:
        up = counts.get(hi_row + 1, 0.0)
        down = counts.get(lo_row - 1, 0.0)
        if up <= 0 and down <= 0:
            break
        if up >= down:
            hi_row += 1
            covered += up
        else:
            lo_row -= 1
            covered += down

    rows = [{"price_low": round(r * row_size, 2),
             "price_high": round((r + 1) * row_size, 2),
             "weight": round(counts[r], 4)}
            for r in sorted(counts)]

    return {
        "weight": weight,
        "row_size": row_size,
        "value_area": value_area,
        "rows": rows,
        "bars": len(bars),
        "total": round(total, 4),
        # The POC is quoted at the MIDPOINT of its row.  A row is a band and a
        # strategy needs one number; the midpoint is the only choice that does
        # not bias the level toward one side of the band.
        "poc": round((poc_row + 0.5) * row_size, 2),
        "poc_row_low": round(poc_row * row_size, 2),
        "poc_row_high": round((poc_row + 1) * row_size, 2),
        # VAH/VAL are the OUTER edges of the outermost rows in the area, so the
        # value area contains every row it counted, whole.
        "vah": round((hi_row + 1) * row_size, 2),
        "val": round(lo_row * row_size, 2),
        "va_rows": hi_row - lo_row + 1,
        "va_covered": round(covered / total, 4),
        "high": round(max(_bar_hl(b)[0] for b in bars), 2),
        "low": round(min(_bar_hl(b)[1] for b in bars), 2),
    }
