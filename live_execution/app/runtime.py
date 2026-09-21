from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from app.config import DB_FILE, IST, SIGNAL_KEY, STRATEGY_SPECS, Settings, read_token
from app.db import Database
from app.execution.order_manager import OrderManager
from app.execution.state import RunStatus
from app.execution.strategy_executor import StrategyExecutor
from app.market_data.candle_reconciler import CandleReconciler
from app.market_data.feed import MarketFeed
from app.market_data.upstox_client import UpstoxClient
from app.models import Tick
from app.strategies import STRATEGY_CLASSES
from app.timeutil import MINUTE, floor_minute


class Runtime:
    def __init__(self, settings: Settings, strategy_keys: list[str]):
        self.settings = settings
        self.strategy_keys = strategy_keys
        self.executors: dict[str, StrategyExecutor] = {}
        self.subscribers: set[asyncio.Queue] = set()
        self.client: UpstoxClient | None = None
        self.feed: MarketFeed | None = None
        self.db: Database | None = None
        self.startup_error: str | None = None

    def publish(self, event: dict) -> None:
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        token = read_token()
        self.client = UpstoxClient(token)
        try:
            await self.client.validate_token()
        except Exception as exc:
            self.startup_error = f"Upstox token check failed: {exc}"
            return

        self.db = Database(DB_FILE)
        orders = OrderManager(self.client, self.db, self.settings)
        reconciler = CandleReconciler(self.client, self.settings, self.db)
        for key in self.strategy_keys:
            spec = STRATEGY_SPECS[key]
            self.executors[spec.strategy_id] = StrategyExecutor(
                spec, STRATEGY_CLASSES[spec.strategy_name], self.client, orders, reconciler, self.db,
                self.settings, self.publish,
            )

        prepared = await asyncio.gather(*(e.prepare() for e in self.executors.values()))
        active = [e for e, ok in zip(self.executors.values(), prepared) if ok]
        if not active:
            return

        await self._wait_for_clean_minute()
        await asyncio.gather(*(e.load_history() for e in active))
        active = [e for e in active if e.run_status != RunStatus.ERROR]
        if not active:
            return

        keys = sorted({SIGNAL_KEY} | {e.option_key for e in active})
        self.feed = MarketFeed(token, keys, loop, self._dispatch_ticks, self._on_feed_status)
        self.feed.start()
        for executor in active:
            executor.start()

    async def _wait_for_clean_minute(self) -> None:
        now = datetime.now(IST)
        if now.second >= self.settings.warmup_late_second:
            target = floor_minute(now) + MINUTE + timedelta(seconds=self.settings.warmup_settle_seconds)
            await asyncio.sleep((target - now).total_seconds())

    def _dispatch_ticks(self, ticks: list[Tick]) -> None:
        for tick in ticks:
            for executor in self.executors.values():
                executor.on_tick(tick)

    def _on_feed_status(self, connected: bool) -> None:
        for executor in self.executors.values():
            executor.on_feed_status(connected)

    async def stop(self) -> None:
        if self.feed is not None:
            self.feed.stop()
        for executor in self.executors.values():
            await executor.stop()
        if self.client is not None:
            await self.client.close()

    def health(self) -> dict:
        return {
            "mode": "live" if self.settings.live else "paper",
            "startup_error": self.startup_error,
            "feed_connected": bool(self.feed and self.feed.connected),
            "strategies": {sid: e.run_status.value for sid, e in self.executors.items()},
        }
