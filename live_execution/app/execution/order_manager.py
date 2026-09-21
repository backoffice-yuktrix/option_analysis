from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from app.config import IST, Settings
from app.market_data.upstox_client import TokenExpired, UpstoxClient, UpstoxError

TERMINAL = {"complete", "rejected", "cancelled"}


class OrderError(Exception):
    pass


@dataclass
class OrderResult:
    order_id: str
    status: str
    filled_quantity: int
    average_price: float | None
    fill_time: str | None
    message: str | None
    latency_ms: int

    @property
    def filled(self) -> bool:
        return self.status == "complete" and self.filled_quantity > 0


def _now() -> str:
    return datetime.now(IST).isoformat(timespec="milliseconds")


class OrderManager:
    def __init__(self, client: UpstoxClient, db, settings: Settings):
        self.client = client
        self.db = db
        self.settings = settings

    async def place_market(
        self,
        *,
        strategy_id: str,
        instrument_key: str,
        instrument_name: str,
        side: str,
        quantity: int,
        reason: str,
        ref_price: float,
        stop_loss: float | None,
        target: float | None,
        emit: Callable[..., None],
    ) -> OrderResult:
        tag = strategy_id.replace("_", "")[:12] + uuid.uuid4().hex[:8]
        started = time.monotonic()
        record = {
            "tag": tag, "order_id": None, "strategy_id": strategy_id, "instrument": instrument_name,
            "side": side, "quantity": quantity, "order_type": "MARKET", "trigger_reason": reason,
            "reference_price": ref_price, "stop_loss": stop_loss, "target": target,
            "submitted_at": _now(), "acknowledged_at": None, "status": "submitting",
            "filled_quantity": 0, "average_price": None, "fill_time": None, "broker_message": None,
            "mode": "live" if self.settings.live else "paper", "latency_ms": None,
        }
        self.db.upsert_order(record)
        emit("order_submitted", tag=tag, side=side, quantity=quantity, reason=reason, reference_price=ref_price,
             mode=record["mode"])

        if not self.settings.live:
            result = OrderResult(
                order_id=f"PAPER-{tag}", status="complete", filled_quantity=quantity, average_price=ref_price,
                fill_time=_now(), message="paper fill at last traded price", latency_ms=0,
            )
            emit("order_acknowledged", tag=tag, order_id=result.order_id)
            return self._finish(record, result, emit)

        body = {
            "quantity": quantity,
            "product": "I",
            "validity": "DAY",
            "price": 0,
            "tag": tag,
            "instrument_token": instrument_key,
            "order_type": "MARKET",
            "transaction_type": side,
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
            "slice": False,
            "market_protection": -1,
        }
        try:
            ids = await self.client.place_order(body)
            order_id = ids[0] if ids else None
            if order_id is None:
                raise OrderError("Upstox accepted the order but returned no order id; check the broker.")
        except TokenExpired as exc:
            raise OrderError(str(exc)) from exc
        except UpstoxError as exc:
            if not exc.ambiguous:
                result = OrderResult("", "rejected", 0, None, None, str(exc), int((time.monotonic() - started) * 1000))
                return self._finish(record, result, emit)
            found = await self._find_by_tag(tag)
            if found is None:
                raise OrderError(
                    f"Order submission outcome unknown (tag {tag}): {exc}. Check the broker before restarting."
                ) from exc
            order_id = str(found["order_id"])

        record["order_id"] = order_id
        record["acknowledged_at"] = _now()
        record["status"] = "acknowledged"
        self.db.upsert_order(record)
        emit("order_acknowledged", tag=tag, order_id=order_id)

        details = await self._await_final(order_id)
        avg = details.get("average_price")
        result = OrderResult(
            order_id=order_id,
            status=str(details.get("status", "")).lower(),
            filled_quantity=int(details.get("filled_quantity") or 0),
            average_price=float(avg) if avg else None,
            fill_time=details.get("exchange_timestamp") or details.get("order_timestamp"),
            message=details.get("status_message"),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return self._finish(record, result, emit)

    def _finish(self, record: dict, result: OrderResult, emit: Callable[..., None]) -> OrderResult:
        record.update(
            order_id=result.order_id or record["order_id"], status=result.status,
            filled_quantity=result.filled_quantity, average_price=result.average_price,
            fill_time=result.fill_time, broker_message=result.message, latency_ms=result.latency_ms,
        )
        self.db.upsert_order(record)
        if result.filled_quantity > 0:
            emit("order_filled", tag=record["tag"], order_id=result.order_id, status=result.status,
                 filled_quantity=result.filled_quantity, average_price=result.average_price,
                 fill_time=result.fill_time, latency_ms=result.latency_ms)
        else:
            emit("order_rejected", tag=record["tag"], order_id=result.order_id, status=result.status,
                 message=result.message, latency_ms=result.latency_ms)
        return result

    async def _find_by_tag(self, tag: str) -> dict | None:
        for _ in range(3):
            await asyncio.sleep(1.0)
            try:
                for order in await self.client.list_orders():
                    if order.get("tag") == tag:
                        return order
            except TokenExpired as exc:
                raise OrderError(str(exc)) from exc
            except UpstoxError:
                continue
        return None

    async def _fetch_details(self, order_id: str) -> dict | None:
        try:
            return await self.client.order_details(order_id)
        except TokenExpired as exc:
            raise OrderError(str(exc)) from exc
        except UpstoxError:
            return None

    async def _await_final(self, order_id: str) -> dict:
        deadline = time.monotonic() + self.settings.order_timeout
        while time.monotonic() < deadline:
            details = await self._fetch_details(order_id)
            if details and str(details.get("status", "")).lower() in TERMINAL:
                return details
            await asyncio.sleep(self.settings.order_poll_interval)
        try:
            await self.client.cancel_order(order_id)
        except UpstoxError:
            pass
        for _ in range(4):
            await asyncio.sleep(1.0)
            details = await self._fetch_details(order_id)
            if details and str(details.get("status", "")).lower() in TERMINAL:
                return details
        raise OrderError(f"Order {order_id} did not reach a final state; check the broker.")
