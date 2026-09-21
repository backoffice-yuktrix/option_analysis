from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import date, datetime
from typing import Callable

from app.config import IST, SIGNAL_KEY, Settings, StrategySpec
from app.execution.order_manager import OrderError, OrderManager, OrderResult
from app.execution.state import PosState, Position, RunStatus
from app.logs import log_event
from app.market_data.candle_builder import CandleBuilder
from app.market_data.candle_reconciler import CandleReconciler
from app.market_data.candle_store import CandleStore
from app.market_data.upstox_client import UpstoxClient
from app.models import Tick
from app.strategies.base_strategy import BaseStrategy
from app.timeutil import MINUTE, floor_minute, to_ts

LIVE_PUBLISH_INTERVAL = 0.25


def candle_json(c: dict) -> dict:
    ts = to_ts(c["timestamp"])
    return {
        "time": int(ts.timestamp()),
        "timestamp": ts.isoformat(),
        "open": float(c["open"]),
        "high": float(c["high"]),
        "low": float(c["low"]),
        "close": float(c["close"]),
        "volume": float(c["volume"]),
        "source": c.get("source"),
    }


class StrategyExecutor:
    def __init__(
        self,
        spec: StrategySpec,
        strategy: type[BaseStrategy],
        client: UpstoxClient,
        order_manager: OrderManager,
        reconciler: CandleReconciler,
        db,
        settings: Settings,
        publish: Callable[[dict], None],
    ):
        self.spec = spec
        self.strategy = strategy
        self.client = client
        self.orders = order_manager
        self.reconciler = reconciler
        self.db = db
        self.settings = settings
        self.publish = publish

        self.contract: dict = {}
        self.option_key = ""
        self.quantity = 0
        self.signal_builder = CandleBuilder(SIGNAL_KEY)
        self.signal_store = CandleStore(settings.max_candles)

        self.run_status = RunStatus.STARTING
        self.pos_state = PosState.NO_POSITION
        self.position: Position | None = None
        self.error: str | None = None
        self.events: deque[dict] = deque(maxlen=500)
        self.metrics = {
            "ticks_received": 0, "candles_reconciled": 0, "candle_mismatches": 0,
            "entry_signals": 0, "exit_signals": 0, "orders_submitted": 0, "orders_filled": 0,
            "orders_rejected": 0, "last_processing_ms": 0.0, "last_order_ms": 0,
        }
        self.last_price: dict[str, tuple[float, float]] = {}
        self.feed_connected = False

        self._ever_connected = False
        self._min_ts: datetime | None = None
        self._ready_minute: datetime | None = None
        self._pending_from: datetime | None = None
        self._entry_attempt_minute: datetime | None = None
        self._no_entry_until: datetime | None = None
        self._forced_exit_reason: str | None = None
        self._next_exit_retry = 0.0
        self._exit_failures = 0
        self._entries_today = 0
        self._daily_pnl = 0.0
        self._day = date.today().isoformat()
        self._last_block_reason: str | None = None
        self._last_live_publish = 0.0
        self._dirty = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._loop_task: asyncio.Task | None = None

    def _emit(self, type_: str, **data) -> None:
        event = {
            "type": type_,
            "strategy_id": self.spec.strategy_id,
            "timestamp": datetime.now(IST).isoformat(timespec="milliseconds"),
            **data,
        }
        self.events.append(event)
        log_event(event)
        self.publish(event)

    def _set_status(self, status: RunStatus) -> None:
        if status == self.run_status:
            return
        self.run_status = status
        self._emit("strategy_state", status=status.value, position_state=self.pos_state.value)

    def _set_pos(self, state: PosState) -> None:
        self.pos_state = state
        self._save_state()
        self._emit("strategy_state", status=self.run_status.value, position_state=state.value)

    def _fail(self, message: str) -> None:
        self.error = message
        self.run_status = RunStatus.ERROR
        self._emit("error", message=message)
        self._emit("strategy_state", status=RunStatus.ERROR.value, position_state=self.pos_state.value)

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _save_state(self) -> None:
        self.db.save_state(
            self.spec.strategy_id,
            {
                "day": self._day,
                "pos_state": self.pos_state.value,
                "position": self.position.to_dict() if self.position else None,
                "entries_today": self._entries_today,
                "daily_pnl": self._daily_pnl,
            },
        )

    def keys(self) -> list[str]:
        return [SIGNAL_KEY, self.option_key]

    def _option_ltp(self) -> float:
        latest = self.last_price.get(self.option_key)
        return latest[0] if latest else 0.0

    def _current_minute(self) -> datetime | None:
        live = self.signal_builder.live
        return live["timestamp"] if live else None

    async def prepare(self) -> bool:
        try:
            self.contract = await self.client.find_option(
                self.spec.underlying_key, self.spec.expiry, self.spec.strike, self.spec.option_type
            )
            self.option_key = self.contract["instrument_key"]
            self.quantity = int(self.contract["lot_size"]) * self.spec.lots
            self._load_persisted()
            await self._verify_against_broker()
        except Exception as exc:
            self._fail(f"prepare failed: {type(exc).__name__}: {exc}")
            return False
        self._emit(
            "strategy_start",
            instrument=self.contract.get("trading_symbol"),
            instrument_key=self.option_key,
            quantity=self.quantity,
            mode="live" if self.settings.live else "paper",
        )
        return True

    def _load_persisted(self) -> None:
        saved = self.db.load_state(self.spec.strategy_id)
        if not saved:
            return
        if saved.get("day") == self._day:
            self._entries_today = int(saved.get("entries_today", 0))
            self._daily_pnl = float(saved.get("daily_pnl", 0.0))
        if saved.get("position"):
            position = Position.from_dict(saved["position"])
            if position.nifty_entry is None:
                raise RuntimeError(
                    "Saved position was created by an older version with option-based levels. "
                    "Close it manually at the broker and clear the strategy_state row before starting."
                )
            if self.settings.live or position.opened_at[:10] == self._day:
                self.position = position
                self.pos_state = PosState.POSITION_OPEN

    async def _verify_against_broker(self) -> None:
        if not self.settings.live:
            return
        self._emit("recovery_started")
        positions = await self.client.positions()
        net = sum(int(p.get("quantity") or 0) for p in positions if p.get("instrument_token") == self.option_key)
        expected = 0
        if self.position is not None:
            held = self.position.quantity
            expected = held if self.strategy.entry_order_side == "BUY" else -held
        if net != expected:
            raise RuntimeError(
                f"Broker holds net {net} of {self.contract.get('trading_symbol')} but local state expects {expected}. "
                "Resolve the position manually before starting."
            )
        self._emit("recovery_completed", broker_net_quantity=net, resumed_position=self.position is not None)

    async def load_history(self) -> None:
        try:
            start = floor_minute(datetime.now(IST))
            self._min_ts = start
            self._pending_from = start - 3 * MINUTE
            self._emit("historical_fetch_start")
            for c in await self.client.recent_candles(SIGNAL_KEY, self.settings.history_days):
                if c["timestamp"] < start:
                    self.signal_store.upsert(c, "official")
            self._emit("historical_fetch_complete", signal_candles=len(self.signal_store.tail(10_000)))
        except Exception as exc:
            self._fail(f"history load failed: {type(exc).__name__}: {exc}")

    def start(self) -> None:
        if self.run_status == RunStatus.ERROR:
            return
        self._set_status(RunStatus.SUBSCRIBING)
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self.run_status = RunStatus.STOPPING
        self._emit("strategy_state", status="STOPPING", position_state=self.pos_state.value)
        self._dirty.set()
        for task in list(self._tasks) + ([self._loop_task] if self._loop_task else []):
            task.cancel()
        self.run_status = RunStatus.STOPPED
        self._emit("strategy_state", status="STOPPED", position_state=self.pos_state.value)

    def on_feed_status(self, connected: bool) -> None:
        self.feed_connected = connected
        if self.run_status in (RunStatus.ERROR, RunStatus.STOPPING, RunStatus.STOPPED):
            return
        if not connected:
            self._emit("websocket_disconnected")
            if self.run_status in (RunStatus.RUNNING, RunStatus.WARMING_UP, RunStatus.RECONCILING):
                self._set_status(RunStatus.RECONNECTING)
        else:
            self._emit("websocket_reconnected" if self._ever_connected else "websocket_connected")
            if self.run_status == RunStatus.RECONNECTING:
                self._set_status(RunStatus.RECONCILING)
            self._ever_connected = True

    def on_tick(self, tick: Tick) -> None:
        try:
            self._on_tick(tick)
        except Exception as exc:
            self._emit("error", message=f"tick handling failed: {type(exc).__name__}: {exc}")

    def _on_tick(self, tick: Tick) -> None:
        is_signal = tick.key == SIGNAL_KEY
        if not is_signal and tick.key != self.option_key:
            return
        self.metrics["ticks_received"] += 1
        self.last_price[tick.key] = (tick.price, time.monotonic())
        if self.run_status == RunStatus.SUBSCRIBING:
            self._set_status(RunStatus.WARMING_UP)
        if is_signal and self._min_ts is not None and tick.ts >= self._min_ts:
            for c in self.signal_builder.on_tick(tick):
                self._on_signal_minute_end(c, self.signal_builder.live["timestamp"])
        self._dirty.set()

    def _on_signal_minute_end(self, finalized: dict, new_minute: datetime) -> None:
        self.signal_store.upsert(finalized, "local")
        self._emit("minute_transition", minute=new_minute.isoformat())
        self._emit("candle_finalized", series="signal", candle=candle_json(finalized))
        start = finalized["timestamp"]
        if self._pending_from is not None and self._pending_from < start:
            start = self._pending_from
        self._spawn(self._reconcile(start, new_minute))

    async def _reconcile(self, start: datetime, end: datetime) -> None:
        self._emit("official_candle_request", start=start.isoformat(), end=end.isoformat())
        try:
            signal_result = await self.reconciler.reconcile(
                strategy_id=self.spec.strategy_id, key=SIGNAL_KEY, store=self.signal_store, start=start,
                end=end, series="signal", require_all=True, emit=self._emit,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._emit("error", message=f"signal reconcile failed: {type(exc).__name__}: {exc}")
            return
        self.metrics["candles_reconciled"] += len(signal_result.reconciled)
        self.metrics["candle_mismatches"] += signal_result.corrected
        if signal_result.missing:
            self._emit("reconcile_incomplete", missing=[m.isoformat() for m in signal_result.missing])
            return
        self._pending_from = end
        if self._ready_minute is None or end > self._ready_minute:
            self._ready_minute = end
        if self.run_status in (RunStatus.WARMING_UP, RunStatus.RECONCILING) and self.feed_connected:
            self._set_status(RunStatus.RUNNING)
        self._dirty.set()

    async def _run_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._dirty.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            self._dirty.clear()
            if self.run_status in (RunStatus.STOPPING, RunStatus.STOPPED):
                return
            started = time.perf_counter()
            try:
                await self._process_latest()
            except OrderError as exc:
                self._fail(str(exc))
            except Exception as exc:
                self._fail(f"processing failed: {type(exc).__name__}: {exc}")
            self.metrics["last_processing_ms"] = round((time.perf_counter() - started) * 1000, 2)

    async def _process_latest(self) -> None:
        now = datetime.now(IST)
        self._roll_day(now)
        self._publish_live()
        if self.run_status == RunStatus.ERROR:
            return
        if self.pos_state == PosState.POSITION_OPEN and now.time() >= self.settings.squareoff:
            await self._process_exit(now)
            return
        if self.run_status != RunStatus.RUNNING:
            return
        if self.pos_state == PosState.POSITION_OPEN:
            await self._process_exit(now)
        elif self.pos_state == PosState.NO_POSITION:
            await self._process_entry(now)

    def _roll_day(self, now: datetime) -> None:
        today = now.date().isoformat()
        if today != self._day:
            self._day = today
            self._entries_today = 0
            self._daily_pnl = 0.0
            self._entry_attempt_minute = None
            self._save_state()

    def _publish_live(self) -> None:
        mono = time.monotonic()
        if mono - self._last_live_publish < LIVE_PUBLISH_INTERVAL:
            return
        self._last_live_publish = mono
        live = self.signal_builder.live
        if live:
            self.publish(
                {
                    "type": "live_candle",
                    "strategy_id": self.spec.strategy_id,
                    "series": "signal",
                    "candle": candle_json(live),
                    "last_tick_price": live["last_tick_price"],
                    "last_tick_timestamp": live["last_tick_timestamp"],
                    "market_version": live["market_version"],
                }
            )

    def _data_health(self) -> str | None:
        if not self.feed_connected:
            return "market data feed disconnected"
        sig = self.last_price.get(SIGNAL_KEY)
        if sig is None or time.monotonic() - sig[1] > self.settings.max_signal_tick_age:
            return "NIFTY ticks are stale"
        return None

    def _entry_block_reason(self, now: datetime) -> str | None:
        if not (self.settings.entry_start <= now.time() < self.settings.entry_end):
            return "outside entry window"
        if self._entries_today >= self.settings.max_entries_per_day:
            return "daily entry limit reached"
        if self._daily_pnl <= -self.settings.max_daily_loss:
            return "daily loss limit reached"
        return self._data_health()

    async def _process_entry(self, now: datetime) -> None:
        minute = self._current_minute()
        if minute is None or self._ready_minute != minute or self._entry_attempt_minute == minute:
            return
        if self._no_entry_until is not None and minute < self._no_entry_until:
            return
        reason = self._entry_block_reason(now)
        if reason:
            if reason != self._last_block_reason:
                self._emit("entry_blocked", reason=reason)
                self._last_block_reason = reason
            return
        self._last_block_reason = None

        decision = self.strategy.evaluate_entry(
            self.signal_store.frame().pipe(self.strategy.calculate),
            self.signal_builder.live,
            self.last_price[SIGNAL_KEY][0],
        )
        self._entry_attempt_minute = minute
        if decision is None:
            return
        self.metrics["entry_signals"] += 1
        if not decision["confirmed"]:
            self._emit("entry_rejected", **{k: v for k, v in decision.items() if k != "confirmed"})
            return
        self._emit("entry_signal", **decision)
        await self._place_entry(decision, minute)

    async def _place_entry(self, decision: dict, minute: datetime) -> None:
        self._set_pos(PosState.ENTRY_TRIGGERED)
        side = self.strategy.entry_order_side
        self._set_pos(PosState.ENTRY_ORDER_PENDING)
        self._set_status(RunStatus.ORDER_PENDING)
        self._entries_today += 1
        self.metrics["orders_submitted"] += 1
        try:
            result = await self.orders.place_market(
                strategy_id=self.spec.strategy_id, instrument_key=self.option_key,
                instrument_name=self.contract.get("trading_symbol", self.option_key), side=side,
                quantity=self.quantity, reason="ENTRY", ref_price=self._option_ltp(),
                stop_loss=decision["stop_loss"], target=decision["target"], emit=self._emit,
            )
        except OrderError as exc:
            self._fail(str(exc))
            return
        self.metrics["last_order_ms"] = result.latency_ms
        if not result.filled:
            self.metrics["orders_rejected"] += 1
            self.position = None
            self._set_pos(PosState.NO_POSITION)
            self._set_status(RunStatus.RUNNING)
            return

        self.metrics["orders_filled"] += 1
        entry_price = float(result.average_price or self._option_ltp())
        self.position = Position(
            side=self.strategy.side, quantity=result.filled_quantity, entry_price=entry_price,
            stop_loss=decision["stop_loss"], target=decision["target"], entry_minute=minute.isoformat(),
            entry_order_id=result.order_id, opened_at=datetime.now(IST).isoformat(),
            nifty_entry=decision["reference_price"],
        )
        self._exit_failures = 0
        self._set_pos(PosState.POSITION_OPEN)
        self._set_status(RunStatus.RUNNING)
        self._emit(
            "position_opened", side=self.strategy.side, option_entry_price=entry_price,
            nifty_entry=decision["reference_price"], nifty_stop_loss=decision["stop_loss"],
            nifty_target=decision["target"], skip_exit_for_current_candle=True,
        )

    async def _process_exit(self, now: datetime) -> None:
        pos = self.position
        latest = self.last_price.get(SIGNAL_KEY)
        if pos is None or latest is None or time.monotonic() < self._next_exit_retry:
            return
        price = latest[0]
        reason = None
        if now.time() >= self.settings.squareoff:
            reason = "EOD_SQUAREOFF"
        elif self._forced_exit_reason:
            reason = self._forced_exit_reason
        else:
            minute = self._current_minute()
            if minute is not None and pos.entry_minute == minute.isoformat():
                return
            decision = self.strategy.evaluate_exit(pos, price)
            if decision and decision["confirmed"]:
                reason = decision["reason"]
        if reason is None:
            return
        self.metrics["exit_signals"] += 1
        self._emit("exit_signal", reason=reason, price=price)
        await self._place_exit(reason, price)

    async def _place_exit(self, reason: str, ref_price: float) -> None:
        pos = self.position
        self._set_pos(PosState.EXIT_TRIGGERED)
        self._set_pos(PosState.EXIT_ORDER_PENDING)
        self._set_status(RunStatus.ORDER_PENDING)
        side = "SELL" if self.strategy.entry_order_side == "BUY" else "BUY"
        self.metrics["orders_submitted"] += 1
        try:
            result = await self.orders.place_market(
                strategy_id=self.spec.strategy_id, instrument_key=self.option_key,
                instrument_name=self.contract.get("trading_symbol", self.option_key), side=side,
                quantity=pos.quantity, reason=reason, ref_price=self._option_ltp(), stop_loss=pos.stop_loss,
                target=pos.target, emit=self._emit,
            )
        except OrderError as exc:
            self._fail(str(exc))
            return
        self.metrics["last_order_ms"] = result.latency_ms
        if result.filled_quantity > 0:
            self.metrics["orders_filled"] += 1
            self._close_trade(pos, result, reason)
            return
        self.metrics["orders_rejected"] += 1
        self._exit_failures += 1
        self._next_exit_retry = time.monotonic() + self.settings.exit_retry_delay
        self._set_pos(PosState.POSITION_OPEN)
        self._set_status(RunStatus.RUNNING)
        if self._exit_failures >= self.settings.max_exit_failures:
            self._fail(f"exit order failed {self._exit_failures} times; position is still open, act manually")

    def _close_trade(self, pos: Position, result: OrderResult, reason: str) -> None:
        exit_price = float(result.average_price or self._option_ltp())
        closed = min(result.filled_quantity, pos.quantity)
        sign = 1 if self.strategy.entry_order_side == "BUY" else -1
        pnl = round((exit_price - pos.entry_price) * closed * sign, 2)
        self._daily_pnl += pnl
        self.db.insert_trade(
            {
                "strategy_id": self.spec.strategy_id, "instrument": self.contract.get("trading_symbol"),
                "side": pos.side, "quantity": closed, "entry_order_id": pos.entry_order_id,
                "exit_order_id": result.order_id, "entry_price": pos.entry_price, "exit_price": exit_price,
                "stop_loss": pos.stop_loss, "target": pos.target, "pnl": pnl, "exit_reason": reason,
                "entry_time": pos.opened_at, "exit_time": datetime.now(IST).isoformat(),
            }
        )
        self._emit("trade_closed", side=pos.side, quantity=closed, entry_price=pos.entry_price,
                   exit_price=exit_price, pnl=pnl, reason=reason, daily_pnl=round(self._daily_pnl, 2))
        pos.quantity -= closed
        self._exit_failures = 0
        if pos.quantity > 0:
            self._set_pos(PosState.POSITION_OPEN)
        else:
            self.position = None
            self._forced_exit_reason = None
            minute = self._current_minute() or floor_minute(datetime.now(IST))
            self._no_entry_until = minute + MINUTE
            self._set_pos(PosState.NO_POSITION)
        self._set_status(RunStatus.RUNNING)

    def snapshot(self) -> dict:
        now = time.monotonic()

        def px(key: str) -> dict | None:
            v = self.last_price.get(key)
            return None if v is None else {"price": v[0], "age_seconds": round(now - v[1], 2)}

        return {
            "strategy_id": self.spec.strategy_id,
            "name": self.spec.strategy_name,
            "status": self.run_status.value,
            "position_state": self.pos_state.value,
            "error": self.error,
            "mode": "live" if self.settings.live else "paper",
            "instrument": self.contract.get("trading_symbol"),
            "instrument_key": self.option_key,
            "quantity": self.quantity,
            "feed_connected": self.feed_connected,
            "prices": {"signal": px(SIGNAL_KEY), "option": px(self.option_key)},
            "position": self.position.to_dict() if self.position else None,
            "day": {"entries": self._entries_today, "pnl": round(self._daily_pnl, 2)},
            "ready_minute": self._ready_minute.isoformat() if self._ready_minute else None,
            "metrics": dict(self.metrics),
        }

    def candles(self, series: str, limit: int) -> dict:
        live = self.signal_builder.live
        return {
            "candles": [candle_json(c) for c in self.signal_store.tail(limit)],
            "live": candle_json(live) if live else None,
        }
