from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class RunStatus(str, Enum):
    STARTING = "STARTING"
    WARMING_UP = "WARMING_UP"
    SUBSCRIBING = "SUBSCRIBING"
    RUNNING = "RUNNING"
    RECONNECTING = "RECONNECTING"
    RECONCILING = "RECONCILING"
    ORDER_PENDING = "ORDER_PENDING"
    ERROR = "ERROR"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


class PosState(str, Enum):
    NO_POSITION = "NO_POSITION"
    ENTRY_TRIGGERED = "ENTRY_TRIGGERED"
    ENTRY_ORDER_PENDING = "ENTRY_ORDER_PENDING"
    POSITION_OPEN = "POSITION_OPEN"
    EXIT_TRIGGERED = "EXIT_TRIGGERED"
    EXIT_ORDER_PENDING = "EXIT_ORDER_PENDING"


@dataclass
class Position:
    side: str
    quantity: int
    entry_price: float
    stop_loss: float
    target: float | None
    entry_minute: str
    entry_order_id: str
    opened_at: str
    nifty_entry: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        return cls(**data)
