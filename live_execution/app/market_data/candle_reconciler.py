from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from app.config import MARKET_CLOSE, MARKET_OPEN, Settings
from app.market_data.candle_store import CandleStore
from app.market_data.upstox_client import TokenExpired, UpstoxClient, UpstoxError
from app.timeutil import MINUTE, floor_minute, minute_key, to_ts

FIELDS = ("open", "high", "low", "close", "volume")
TOLERANCE = 1e-6


@dataclass
class ReconcileResult:
    reconciled: list[datetime] = field(default_factory=list)
    corrected: int = 0
    missing: list[datetime] = field(default_factory=list)


def _view(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {k: row[k] for k in FIELDS} | {"timestamp": to_ts(row["timestamp"]).isoformat()}


class CandleReconciler:
    def __init__(self, client: UpstoxClient, settings: Settings, db):
        self.client = client
        self.settings = settings
        self.db = db

    async def reconcile(
        self,
        *,
        strategy_id: str,
        key: str,
        store: CandleStore,
        start: datetime,
        end: datetime,
        series: str,
        require_all: bool,
        emit: Callable[..., None],
    ) -> ReconcileResult:
        minutes: list[datetime] = []
        m = floor_minute(start)
        while m < end:
            if MARKET_OPEN <= m.time() < MARKET_CLOSE:
                minutes.append(m)
            m += MINUTE

        pending = []
        for m in minutes:
            row = store.get(m)
            if row is None or row["source"] != "official":
                pending.append((m, row))
        result = ReconcileResult()
        if not pending:
            return result

        required = {minute_key(m) for m, row in pending if require_all or row is not None}
        official: dict[int, dict] = {}
        for attempt in range(self.settings.reconcile_retries):
            try:
                official = {minute_key(c["timestamp"]): c for c in await self.client.intraday_candles(key)}
            except TokenExpired:
                raise
            except UpstoxError:
                official = {}
            if all(k in official for k in required):
                break
            if attempt < self.settings.reconcile_retries - 1:
                await asyncio.sleep(self.settings.reconcile_retry_delay)

        for m, local in pending:
            off = official.get(minute_key(m))
            if off is None:
                continue
            difference = {}
            if local is not None:
                for f in FIELDS:
                    d = float(off[f]) - float(local[f])
                    if abs(d) > TOLERANCE:
                        difference[f] = round(d, 6)
            store.upsert(off, "official")
            corrected = bool(difference)
            result.reconciled.append(m)
            result.corrected += int(corrected)
            self.db.insert_diag(
                strategy_id=strategy_id,
                series=series,
                instrument=key,
                minute=m.isoformat(),
                local=_view(local),
                official=_view(store.get(m)),
                difference=difference,
                corrected=corrected,
            )
            emit(
                "candle_reconciled",
                series=series,
                minute=m.isoformat(),
                local=_view(local),
                official=_view(store.get(m)),
                difference=difference,
                corrected=corrected,
                gap_filled=local is None,
            )

        result.missing = [m for m, _ in pending if minute_key(m) in required and minute_key(m) not in official]
        return result
