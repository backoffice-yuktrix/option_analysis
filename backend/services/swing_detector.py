"""ATR computation and alternating Hill/Valley swing detection for M1.

Algorithm:
1. Compute ATR(period) on OHLCV candles using configured price source.
2. Walk candles maintaining a current extreme (high for up-move, low for down-move).
   A reversal is confirmed when the move from the extreme exceeds ATR × multiplier.
3. Force-close any open leg at the 3:15 PM IST candle (09:45 UTC) each trading day.
4. Output: alternating [{timestamp, price, type: Hill|Valley}] list.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal


@dataclass
class SwingPoint:
    timestamp: str          # ISO-8601 string from candle
    price: float
    swing_type: Literal["Hill", "Valley"]


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO-8601 candle timestamp to aware datetime."""
    s = ts_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _candle_date(ts_str: str) -> str:
    """Return YYYY-MM-DD of candle in IST (+05:30)."""
    try:
        from datetime import timedelta
        dt = _parse_ts(ts_str)
        ist = dt + timedelta(hours=5, minutes=30)
        return ist.date().isoformat()
    except Exception:
        return ts_str[:10]


def _to_utc(dt: datetime) -> datetime:
    """Convert aware datetime to UTC."""
    return dt.astimezone(timezone.utc)


def _is_at_or_after_market_close(ts_str: str) -> bool:
    """True when candle timestamp is at or after 3:15 PM IST (09:45 UTC)."""
    try:
        dt = _to_utc(_parse_ts(ts_str))
        return (dt.hour, dt.minute) >= (9, 45)
    except Exception:
        return False


def _find_market_close_candle(candles: list[dict], up_to_idx: int, day_str: str) -> dict | None:
    """Find the last candle on day_str at or before 3:15 PM IST (09:45 UTC).

    Walks backward from up_to_idx so the search is fast even for large lists.
    """
    result: dict | None = None
    for j in range(up_to_idx, -1, -1):
        c = candles[j]
        ts = c.get("timestamp", "")
        if _candle_date(ts) != day_str:
            break
        dt_utc = _to_utc(_parse_ts(ts))
        if (dt_utc.hour, dt_utc.minute) <= (9, 45):
            result = c
            break
    return result


def compute_atr(
    candles: list[dict],
    period: int = 14,
    price_source: str = "close",
) -> list[float]:
    """Return ATR value for each candle (first `period` values = None, then filled).

    price_source: "close" → Wilder's ATR using close-based TR; "hl" → TR = High-Low only.
    """
    n = len(candles)
    if n < 2:
        return [0.0] * n

    trs: list[float] = []
    for i in range(n):
        h = float(candles[i].get("high", 0))
        lo = float(candles[i].get("low", 0))
        if price_source == "hl":
            tr = h - lo
        else:
            prev_c = float(candles[i - 1].get("close", 0)) if i > 0 else h
            tr = max(h - lo, abs(h - prev_c), abs(lo - prev_c))
        trs.append(tr)

    if n < period:
        avg = sum(trs) / n if trs else 0.0
        return [avg] * n

    seed = sum(trs[:period]) / period
    atr_vals: list[float] = [0.0] * period
    atr_vals.append(seed)
    for i in range(period, n - 1):
        atr_val = (atr_vals[-1] * (period - 1) + trs[i]) / period
        atr_vals.append(atr_val)

    padded = [seed] * period + atr_vals[period:]
    return padded[:n]


def detect_swings(
    candles: list[dict],
    atr_values: list[float],
    multiplier: float = 2.0,
) -> list[SwingPoint]:
    """Detect alternating Hill/Valley swing points using ATR × multiplier reversal threshold.

    A new swing is confirmed when price moves ATR*multiplier against the current extreme.
    Day boundaries force-close open legs at the 3:15 PM IST candle.
    """
    if not candles or len(candles) < 2:
        return []

    points: list[SwingPoint] = []

    c0_close = float(candles[0].get("close", 0))
    c1_close = float(candles[1].get("close", 0))
    looking_for: Literal["Hill", "Valley"] = "Hill" if c1_close >= c0_close else "Valley"

    extreme_price = float(candles[0].get("close", 0))
    extreme_ts = candles[0].get("timestamp", "")
    extreme_idx = 0

    prev_date = _candle_date(candles[0].get("timestamp", ""))

    for i, candle in enumerate(candles):
        ts = candle.get("timestamp", "")
        cur_date = _candle_date(ts)
        close = float(candle.get("close", 0))
        high = float(candle.get("high", 0))
        low = float(candle.get("low", 0))
        atr = atr_values[i] if i < len(atr_values) else 0.0
        threshold = atr * multiplier

        # Day boundary: force-close open leg at the 3:15 PM IST candle of prev_date
        if cur_date != prev_date and points:
            close_candle = _find_market_close_candle(candles, i - 1, prev_date)
            if close_candle is None:
                close_candle = candles[i - 1]

            force_close_price = float(close_candle.get("close", extreme_price))
            force_close_ts = close_candle.get("timestamp", extreme_ts)

            # forced_type is what we were looking for — it closes the current open leg
            forced_type: Literal["Hill", "Valley"] = looking_for
            if not points or points[-1].swing_type != forced_type:
                points.append(SwingPoint(
                    timestamp=force_close_ts,
                    price=force_close_price,
                    swing_type=forced_type,
                ))

            # New day: reset extreme and direction based on what was just force-closed
            extreme_price = close
            extreme_ts = ts
            extreme_idx = i
            looking_for = "Valley" if forced_type == "Hill" else "Hill"

        prev_date = cur_date

        if looking_for == "Hill":
            if high > extreme_price:
                extreme_price = high
                extreme_ts = ts
                extreme_idx = i
            if extreme_price - close >= threshold and threshold > 0:
                points.append(SwingPoint(
                    timestamp=extreme_ts,
                    price=extreme_price,
                    swing_type="Hill",
                ))
                looking_for = "Valley"
                extreme_price = low
                extreme_ts = ts
                extreme_idx = i
        else:
            if low < extreme_price:
                extreme_price = low
                extreme_ts = ts
                extreme_idx = i
            if close - extreme_price >= threshold and threshold > 0:
                points.append(SwingPoint(
                    timestamp=extreme_ts,
                    price=extreme_price,
                    swing_type="Valley",
                ))
                looking_for = "Hill"
                extreme_price = high
                extreme_ts = ts
                extreme_idx = i

    # Close any open leg at the last candle
    if candles:
        last = candles[-1]
        last_ts = last.get("timestamp", "")
        last_price = float(last.get("close", 0))
        pending_type: Literal["Hill", "Valley"] = looking_for
        if not points or points[-1].timestamp != last_ts:
            points.append(SwingPoint(
                timestamp=last_ts,
                price=last_price,
                swing_type=pending_type,
            ))

    # Deduplicate consecutive same-type swings (keep first occurrence)
    deduped: list[SwingPoint] = []
    for pt in points:
        if not deduped or deduped[-1].swing_type != pt.swing_type:
            deduped.append(pt)

    return deduped


def build_legs(
    swing_points: list[SwingPoint],
    pts_to_analyse: int,
) -> list[tuple[SwingPoint, SwingPoint]]:
    """Return only qualifying legs where magnitude >= pts_to_analyse."""
    qualifying, _ = build_all_legs(swing_points, pts_to_analyse)
    return qualifying


def build_all_legs(
    swing_points: list[SwingPoint],
    pts_to_analyse: int,
) -> tuple[list[tuple[SwingPoint, SwingPoint]], list[tuple[SwingPoint, SwingPoint]]]:
    """Pair consecutive alternating swings into (start, end) legs.

    PRD §4.4 Step 3: each day's sequence is independent — pairs that cross a day
    boundary are not legs (the force-close point ends day N; day N+1 starts fresh).

    Returns (qualifying_legs, non_qualifying_legs) split by magnitude vs pts_to_analyse.
    """
    qualifying: list[tuple[SwingPoint, SwingPoint]] = []
    non_qualifying: list[tuple[SwingPoint, SwingPoint]] = []
    for i in range(len(swing_points) - 1):
        s = swing_points[i]
        e = swing_points[i + 1]
        if _candle_date(s.timestamp) != _candle_date(e.timestamp):
            continue  # cross-day pair — not a leg
        magnitude = abs(e.price - s.price)
        if magnitude >= pts_to_analyse:
            qualifying.append((s, e))
        else:
            non_qualifying.append((s, e))
    return qualifying, non_qualifying
