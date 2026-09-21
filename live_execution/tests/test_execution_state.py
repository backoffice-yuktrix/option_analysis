import asyncio
import time
from datetime import datetime

from app.config import IST, SIGNAL_KEY, STRATEGY_SPECS, Settings
from app.execution.order_manager import OrderResult
from app.execution.state import PosState, RunStatus
from app.execution.strategy_executor import StrategyExecutor
from app.strategies.my_strategy_buy import MyStrategyBuy
from app.strategies.my_strategy_sell import MyStrategySell

OPTION_KEY = "NSE_FO|1"


def t(h, m, s=0):
    return datetime(2026, 9, 21, h, m, s, tzinfo=IST)


class FakeDb:
    def __init__(self):
        self.trades = []

    def save_state(self, *_):
        pass

    def insert_trade(self, trade):
        self.trades.append(trade)


class FakeOrders:
    def __init__(self, status="complete"):
        self.calls = []
        self.status = status

    async def place_market(self, **kw):
        self.calls.append(kw)
        filled = kw["quantity"] if self.status == "complete" else 0
        return OrderResult("O1", self.status, filled, kw["ref_price"] if filled else None, None, None, 5)


def make_executor(orders=None, settings=None):
    ex = StrategyExecutor(
        STRATEGY_SPECS["buy"], MyStrategyBuy, None, orders or FakeOrders(), None, FakeDb(),
        settings or Settings(), lambda e: None,
    )
    ex.option_key = OPTION_KEY
    ex.quantity = 65
    ex.contract = {"trading_symbol": "NIFTY TEST"}
    ex.run_status = RunStatus.RUNNING
    ex.feed_connected = True
    ex.signal_store.upsert(
        {"timestamp": t(10, 15), "open": 23400, "high": 23410, "low": 23390.0, "close": 23400.0, "volume": 0},
        "official",
    )
    ex.signal_store.upsert(
        {"timestamp": t(10, 16), "open": 23400, "high": 23420, "low": 23395, "close": 23410.0, "volume": 0},
        "official",
    )
    ex.signal_builder.live = {"timestamp": t(10, 17), "last_tick_price": 23415.0, "open": 23410, "high": 23415,
                              "low": 23410, "close": 23415, "volume": 0, "last_tick_timestamp": "",
                              "market_version": 1}
    ex._ready_minute = t(10, 17)
    mono = time.monotonic()
    ex.last_price = {SIGNAL_KEY: (23415.0, mono), OPTION_KEY: (10.0, mono)}
    return ex


def set_nifty(ex, price):
    ex.last_price[SIGNAL_KEY] = (price, time.monotonic())


def run(coro):
    return asyncio.run(coro)


def test_entry_places_one_order_and_opens_position():
    async def go():
        orders = FakeOrders()
        ex = make_executor(orders)
        await ex._process_entry(t(10, 17, 5))
        await ex._process_entry(t(10, 17, 6))
        return ex, orders

    ex, orders = run(go())
    assert len(orders.calls) == 1
    assert orders.calls[0]["side"] == "BUY" and orders.calls[0]["quantity"] == 65
    assert ex.pos_state == PosState.POSITION_OPEN
    assert ex.position.stop_loss == 23390.0 and ex.position.target == 23415.0 + 2 * 25.0
    assert ex.position.nifty_entry == 23415.0 and ex.position.entry_price == 10.0


def test_sell_strategy_buys_the_put_and_sells_it_on_exit():
    async def go():
        orders = FakeOrders()
        ex = StrategyExecutor(
            STRATEGY_SPECS["sell"], MyStrategySell, None, orders, None, FakeDb(), Settings(), lambda e: None
        )
        ex.option_key, ex.quantity, ex.contract = OPTION_KEY, 65, {"trading_symbol": "PUT"}
        ex.run_status, ex.feed_connected = RunStatus.RUNNING, True
        for m, close, low in ((15, 23400.0, 23390.0), (16, 23380.0, 23375.0)):
            ex.signal_store.upsert(
                {"timestamp": t(10, m), "open": close, "high": close + 10, "low": low, "close": close, "volume": 0},
                "official",
            )
        ex.signal_builder.live = {"timestamp": t(10, 17), "last_tick_price": 23385.0, "open": 23385,
                                  "high": 23385, "low": 23385, "close": 23385, "volume": 0,
                                  "last_tick_timestamp": "", "market_version": 1}
        ex._ready_minute = t(10, 17)
        mono = time.monotonic()
        ex.last_price = {SIGNAL_KEY: (23385.0, mono), OPTION_KEY: (10.0, mono)}
        await ex._process_entry(t(10, 17, 5))
        ex.signal_builder.live["timestamp"] = t(10, 18)
        set_nifty(ex, 23415.0)
        await ex._process_exit(t(10, 18, 2))
        return ex, orders

    ex, orders = run(go())
    assert ex.db.trades[0]["stop_loss"] == 23410.0
    assert [c["side"] for c in orders.calls] == ["BUY", "SELL"]
    assert ex.db.trades[0]["exit_reason"] == "STOP_LOSS"


def test_entry_rejection_returns_to_no_position():
    async def go():
        ex = make_executor(FakeOrders(status="rejected"))
        await ex._process_entry(t(10, 17, 5))
        return ex

    ex = run(go())
    assert ex.pos_state == PosState.NO_POSITION and ex.position is None
    assert ex.metrics["orders_rejected"] == 1


def test_no_entry_before_official_candle_ready():
    async def go():
        orders = FakeOrders()
        ex = make_executor(orders)
        ex._ready_minute = t(10, 16)
        await ex._process_entry(t(10, 17, 5))
        return orders

    assert run(go()).calls == []


def test_no_entry_outside_window():
    async def go():
        orders = FakeOrders()
        ex = make_executor(orders)
        await ex._process_entry(t(15, 10, 0))
        return orders

    assert run(go()).calls == []


def test_same_candle_exit_suppressed_then_exit_next_candle():
    async def go():
        orders = FakeOrders()
        ex = make_executor(orders)
        await ex._process_entry(t(10, 17, 5))
        set_nifty(ex, 23380.0)
        await ex._process_exit(t(10, 17, 20))
        same_candle_calls = len(orders.calls)
        ex.signal_builder.live["timestamp"] = t(10, 18)
        await ex._process_exit(t(10, 18, 2))
        return ex, orders, same_candle_calls

    ex, orders, same_candle_calls = run(go())
    assert same_candle_calls == 1
    assert len(orders.calls) == 2 and orders.calls[1]["side"] == "SELL"
    assert ex.pos_state == PosState.NO_POSITION
    assert ex.db.trades[0]["exit_reason"] == "STOP_LOSS"


def test_no_immediate_reentry_after_exit():
    async def go():
        orders = FakeOrders()
        ex = make_executor(orders)
        await ex._process_entry(t(10, 17, 5))
        ex.signal_builder.live["timestamp"] = t(10, 18)
        set_nifty(ex, 23470.0)
        await ex._process_exit(t(10, 18, 2))
        ex._ready_minute = t(10, 18)
        await ex._process_entry(t(10, 18, 3))
        return ex, orders

    ex, orders = run(go())
    assert len(orders.calls) == 2
    assert ex.db.trades[0]["exit_reason"] == "TARGET"


def test_eod_squareoff_ignores_entry_candle_skip():
    async def go():
        orders = FakeOrders()
        ex = make_executor(orders)
        await ex._process_entry(t(10, 17, 5))
        await ex._process_exit(t(15, 10, 1))
        return ex, orders

    ex, orders = run(go())
    assert len(orders.calls) == 2 and ex.db.trades[0]["exit_reason"] == "EOD_SQUAREOFF"


def test_daily_entry_limit():
    async def go():
        orders = FakeOrders()
        ex = make_executor(orders, Settings(max_entries_per_day=0))
        await ex._process_entry(t(10, 17, 5))
        return orders

    assert run(go()).calls == []
