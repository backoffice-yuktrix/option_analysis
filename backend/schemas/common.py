"""Shared pydantic types used by both module schemas."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel


class UpstoxConfig(BaseModel):
    api_key: str
    api_secret: str
    redirect_uri: str


class UpstoxStatus(BaseModel):
    has_credentials: bool
    is_connected: bool


class OptionPrice(BaseModel):
    """Single option contract price at one checkpoint."""
    instrument_key: str
    strike: float
    option_type: str          # CE | PE
    expiry: str               # YYYY-MM-DD
    price: float | None       # None when candle unavailable


class CheckpointPrices(BaseModel):
    """Option prices for all strikes × option types at one checkpoint (0/20/.../100)."""
    pct: int                  # 0, 20, 40, 60, 80, or 100
    timestamp: str            # ISO-8601 of the snapped 1-min candle
    instrument_price: float | None
    options: list[OptionPrice]


class LegResult(BaseModel):
    """Common fields for both M1 leg and M2 session results."""
    date: str                              # YYYY-MM-DD
    instrument: str                        # NIFTY | BANKNIFTY
    direction: str                         # Hill | Valley (M1) or GapUp | GapDown (M2)
    start_price: float
    end_price: float
    abs_pts: float
    vix: float | None
    expiries: list[str]                    # ordered list of expiry dates resolved at T0
    default_expiry: str                    # 2nd expiry if available else 1st
    atm_strike: float
    strike_grid: list[float]               # ordered ATM-range … ATM+range
    pts_to_analyse: int
    option_range: int
    # Flat dict of all computed column values (keyed by column_key)
    columns: dict[str, Any]
