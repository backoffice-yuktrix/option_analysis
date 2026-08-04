"""Shared option analysis primitives used by both M1 and M2.

Responsibilities:
- Strike grid construction (ATM ± option_range × pts_to_analyse)
- Expiry resolution (N nearest from T0)
- Default expiry selection (2nd if available, else 1st)
- Along/Against direction tagging
- Cheapest Along option identification
- Option price extraction from 1m candles (High for entry, Low for exit)
- DTE computation (calendar days; trading-day count approximation)
- Checkpoint pricing: snapshot option price at timestamp from candle list
"""
from __future__ import annotations

import bisect
from datetime import date, datetime, timedelta, timezone
from typing import Literal

# ---------------------------------------------------------------------------
# Strike grid
# ---------------------------------------------------------------------------

def build_strike_grid(
    spot: float,
    pts_to_analyse: int,
    option_range: int,
) -> tuple[float, list[float]]:
    """Return (atm_strike, [ATM-range, ..., ATM, ..., ATM+range])."""
    atm = round(spot / pts_to_analyse) * pts_to_analyse
    grid = [atm + k * pts_to_analyse for k in range(-option_range, option_range + 1)]
    return float(atm), [float(s) for s in grid]


# ---------------------------------------------------------------------------
# Expiry resolution
# ---------------------------------------------------------------------------

def resolve_expiries(
    contracts: list[dict],
    t0_date: str,
    expiry_count: int,
) -> list[str]:
    """Return up to expiry_count expiry dates >= t0_date, sorted ascending."""
    all_expiries = sorted({c["expiry"] for c in contracts if c.get("expiry") >= t0_date})
    return all_expiries[:expiry_count]


def default_expiry(expiries: list[str]) -> str:
    """2nd expiry if available, else 1st."""
    if len(expiries) >= 2:
        return expiries[1]
    return expiries[0] if expiries else ""


# ---------------------------------------------------------------------------
# Direction and Along/Against
# ---------------------------------------------------------------------------

def direction_from_leg_type(leg_type: str) -> Literal["up", "down"]:
    """Hill = up move (Valley→Hill), Valley = down move (Hill→Valley)."""
    return "up" if leg_type == "Hill" else "down"


def along_option_type(direction: str) -> str:
    """Along option type for the move direction. up→CE, down→PE."""
    return "CE" if direction == "up" else "PE"


def against_option_type(direction: str) -> str:
    return "PE" if direction == "up" else "CE"


def cheapest_along_strike(
    direction: str,
    atm: float,
    pts_to_analyse: int,
    option_range: int,
) -> float:
    """Most OTM Along strike in the grid (cheapest Along option by strike).

    up move → calls → most OTM call = ATM + range × pts
    down move → puts → most OTM put = ATM - range × pts
    """
    if direction == "up":
        return atm + option_range * pts_to_analyse
    return atm - option_range * pts_to_analyse


# ---------------------------------------------------------------------------
# DTE
# ---------------------------------------------------------------------------

def compute_dte(t0_date: str, expiry_date: str) -> int:
    """Trading days (weekdays Mon–Fri) from t0_date to expiry_date (≥ 0).

    Counts weekdays strictly after t0 up to and including expiry_date.
    Weekend days are excluded; NSE holidays are not separately modelled.
    """
    t0 = date.fromisoformat(t0_date)
    exp = date.fromisoformat(expiry_date)
    if exp <= t0:
        return 0
    count = 0
    d = t0 + timedelta(days=1)
    while d <= exp:
        if d.weekday() < 5:   # Mon=0 … Fri=4
            count += 1
        d += timedelta(days=1)
    return count


def dte_bucket(dte: int) -> str:
    if dte == 0:
        return "Expiry Day"
    if dte == 1:
        return "1 DTE"
    if dte == 2:
        return "2 DTE"
    if dte <= 5:
        return "Near"
    if dte <= 10:
        return "Short"
    if dte <= 20:
        return "Mid"
    return "Far"


# ---------------------------------------------------------------------------
# Checkpoint timestamp interpolation
# ---------------------------------------------------------------------------

def interpolate_checkpoints(
    t0: str, t1: str, pcts: list[int]
) -> list[str]:
    """Return ISO timestamps at each percentage of the (T1-T0) interval."""
    def _parse(s: str) -> datetime:
        s = s.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    dt0 = _parse(t0)
    dt1 = _parse(t1)
    span = (dt1 - dt0).total_seconds()
    result = []
    for pct in pcts:
        offset = span * pct / 100
        ts = dt0 + timedelta(seconds=offset)
        result.append(ts.isoformat())
    return result


def snap_to_candle(candles: list[dict], target_ts: str) -> dict | None:
    """Find the closest candle (by timestamp) to target_ts."""
    if not candles:
        return None

    def _ts_seconds(s: str) -> float:
        s = s.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return 0.0
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    target_sec = _ts_seconds(target_ts)
    ts_list = [_ts_seconds(c.get("timestamp", "")) for c in candles]
    idx = bisect.bisect_left(ts_list, target_sec)

    if idx == 0:
        return candles[0]
    if idx >= len(candles):
        return candles[-1]
    # Pick nearest
    before = candles[idx - 1]
    after = candles[idx]
    if abs(ts_list[idx] - target_sec) < abs(ts_list[idx - 1] - target_sec):
        return after
    return before


# ---------------------------------------------------------------------------
# Option contract lookup helpers
# ---------------------------------------------------------------------------

def filter_contracts(
    contracts: list[dict],
    expiry: str,
    strike: float,
    option_type: str,
) -> dict | None:
    """Return the first contract matching (expiry, strike, option_type) or None."""
    for c in contracts:
        if (
            c.get("expiry") == expiry
            and abs(c.get("strike", 0) - strike) < 0.01
            and c.get("option_type", "").upper() == option_type.upper()
        ):
            return c
    return None


# ---------------------------------------------------------------------------
# Option price extraction using candle High/Low rule
# ---------------------------------------------------------------------------

def option_price_at_checkpoint(
    candles: list[dict],
    target_ts: str,
    is_exit: bool,
) -> float | None:
    """Snap to nearest candle and return High (entry) or Low (exit)."""
    candle = snap_to_candle(candles, target_ts)
    if candle is None:
        return None
    field = "low" if is_exit else "high"
    val = candle.get(field)
    return float(val) if val is not None else None


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def percent_optimal_option(price_0pct: float | None, price_100pct: float | None) -> float | None:
    """abs(0% price - 100% price) / 0% price as a percentage."""
    if price_0pct is None or price_100pct is None or price_0pct == 0:
        return None
    return abs(price_0pct - price_100pct) / price_0pct * 100


def profit_percent_optimal_option(
    price_20pct: float | None, price_80pct: float | None
) -> float | None:
    """abs(20% price - 80% price) / 20% price as a percentage.

    For M2: 20% ≡ 0% and 80% ≡ 100% so this equals percent_optimal_option.
    """
    if price_20pct is None or price_80pct is None or price_20pct == 0:
        return None
    return abs(price_20pct - price_80pct) / price_20pct * 100


# ---------------------------------------------------------------------------
# Column key generation
# ---------------------------------------------------------------------------

STRIKE_LABELS = {
    -3: "ATMm3", -2: "ATMm2", -1: "ATMm1",
    0: "ATM",
    1: "ATMp1", 2: "ATMp2", 3: "ATMp3",
}


def strike_label(atm: float, strike: float, pts: int) -> str:
    offset = round((strike - atm) / pts)
    return STRIKE_LABELS.get(offset, f"ATM{offset:+d}".replace("+", "p").replace("-", "m"))


def along_col_key(exp_n: int, slabel: str, pct: int) -> str:
    return f"along_exp{exp_n}_{slabel}_{pct}pct"


def against_col_key(exp_n: int, slabel: str, pct: int) -> str:
    return f"against_exp{exp_n}_{slabel}_{pct}pct"


def cheapest_col_key(side: str, exp_n: int, pct: int) -> str:
    return f"{side}_exp{exp_n}_cheapest_{pct}pct"


def dte_col_key(exp_n: int) -> str:
    return f"dte_exp{exp_n}"
