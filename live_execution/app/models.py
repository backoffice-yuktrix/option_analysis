from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Tick:
    key: str
    price: float
    ts: datetime
    volume_total: float | None = None
