"""M1 — Intraday Swing Analysis schemas."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ATRConfig(BaseModel):
    period: int = Field(14, ge=2, le=100)
    multiplier: float = Field(2.0, ge=0.1, le=20.0)
    candle_tf: str = Field("15m", pattern="^(5m|15m|30m)$")
    price_source: str = Field("close", pattern="^(close|hl)$")


class Module1Request(BaseModel):
    instrument: str = Field("NIFTY", pattern="^(NIFTY|BANKNIFTY)$")
    from_date: str          # YYYY-MM-DD
    to_date: str            # YYYY-MM-DD
    pts_to_analyse: int = Field(100, ge=25, le=500)
    option_range: int = Field(3, ge=0, le=10)
    expiry_count: int = Field(2, ge=0, le=5)
    atr: ATRConfig = Field(default_factory=ATRConfig)


class SwingPoint(BaseModel):
    timestamp: str
    price: float
    swing_type: str           # Hill | Valley


class NonQualifyingLeg(BaseModel):
    date: str
    end_date: str
    start_time: str
    end_time: str
    start_price: float
    end_price: float


class LegRow(BaseModel):
    date: str
    end_date: str
    start_time: str
    end_time: str
    leg_type: str             # Hill | Valley
    vix: float | None
    abs_pts: float
    start_price: float
    end_price: float
    # Per-expiry option details: {"exp1": {expiry_date, along_type, against_type, atm_strike, atm_along_name, cheapest_along_strike, cheapest_along_name}, ...}
    expiry_details: dict[str, Any] = Field(default_factory=dict)
    # All generated column values (along/against option prices, metrics, etc.)
    columns: dict[str, Any]


class Module1Result(BaseModel):
    instrument: str
    from_date: str
    to_date: str
    pts_to_analyse: int
    option_range: int
    expiry_count: int
    atr: ATRConfig
    swing_points: list[SwingPoint]
    legs: list[LegRow]
    non_qualifying_legs: list[NonQualifyingLeg]
    # Column metadata: {key: {label, group, expiry_n, strike_label, pct, ...}}
    column_meta: dict[str, Any]
    # OHLC candles for the chart (at ATR candle timeframe)
    chart_candles: list[dict]
    run_id: str               # YYYYMMDD_HHMMSS
