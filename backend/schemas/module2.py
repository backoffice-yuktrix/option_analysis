"""M2 — Overnight Gap Analysis schemas."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class Module2Request(BaseModel):
    instrument: str = Field("NIFTY", pattern="^(NIFTY|BANKNIFTY)$")
    from_date: str          # YYYY-MM-DD
    to_date: str            # YYYY-MM-DD
    pts_to_analyse: int = Field(100, ge=25, le=500)
    option_range: int = Field(3, ge=1, le=10)
    expiry_count: int = Field(2, ge=1, le=5)


class SessionRow(BaseModel):
    date: str               # entry date (Day D)
    entry_time: str         # 15:15
    exit_time: str          # 09:25 next day
    gap_pts: float          # signed T1-T0
    gap_direction: str      # GapUp | GapDown
    vix: float | None
    start_price: float
    end_price: float
    columns: dict[str, Any]


class Module2Result(BaseModel):
    instrument: str
    from_date: str
    to_date: str
    pts_to_analyse: int
    option_range: int
    expiry_count: int
    sessions: list[SessionRow]
    column_meta: dict[str, Any]
    run_id: str
