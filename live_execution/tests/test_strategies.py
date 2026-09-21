from datetime import datetime

import pandas as pd
import pytest

from app.config import IST
from app.execution.state import Position
from app.market_data.candle_store import CandleStore
from app.strategies.my_strategy_buy import MyStrategyBuy
from app.strategies.my_strategy_sell import MyStrategySell


def t(m):
    return datetime(2026, 9, 21, 10, m, tzinfo=IST)


def candle(m, close, low=None):
    return {"timestamp": t(m), "open": close, "high": close, "low": close if low is None else low,
            "close": close, "volume": 0}


def frames(c2_close, c1_close, opt_low=8.0, c1_source="official"):
    sig, opt = CandleStore(), CandleStore()
    sig.upsert(candle(15, c2_close), "official")
    sig.upsert(candle(16, c1_close), c1_source)
    opt.upsert(candle(15, 9, low=opt_low), "official")
    return sig.frame(), opt.frame()


LIVE = {"timestamp": t(17)}


def test_buy_signal_when_close_rises():
    sig, opt = frames(100, 101)
    d = MyStrategyBuy.evaluate_entry(sig, LIVE, opt, 10.0)
    assert d["confirmed"] and d["stop_loss"] == 8.0 and d["target"] == 14.0


def test_buy_no_signal_when_equal_or_lower():
    for c1 in (100, 99):
        sig, opt = frames(100, c1)
        assert MyStrategyBuy.evaluate_entry(sig, LIVE, opt, 10.0) is None


def test_buy_needs_official_previous_candle():
    sig, opt = frames(100, 101, c1_source="local")
    assert MyStrategyBuy.evaluate_entry(sig, LIVE, opt, 10.0) is None


def test_buy_rejects_when_price_below_stop():
    sig, opt = frames(100, 101, opt_low=12.0)
    d = MyStrategyBuy.evaluate_entry(sig, LIVE, opt, 10.0)
    assert d["confirmed"] is False


def test_buy_missing_option_candle_is_rejected():
    sig, _ = frames(100, 101)
    d = MyStrategyBuy.evaluate_entry(sig, LIVE, CandleStore().frame(), 10.0)
    assert d["confirmed"] is False


def test_sell_signal_when_close_falls():
    sig, opt = frames(100, 99, opt_low=13.0)
    d = MyStrategySell.evaluate_entry(sig, LIVE, opt, 10.0)
    assert d["confirmed"] and d["stop_loss"] == 13.0 and d["target"] == 4.0


def test_sell_rejects_when_stop_not_above_entry():
    sig, opt = frames(100, 99, opt_low=8.0)
    d = MyStrategySell.evaluate_entry(sig, LIVE, opt, 10.0)
    assert d["confirmed"] is False


def test_sell_no_signal_when_close_rises():
    sig, opt = frames(100, 101)
    assert MyStrategySell.evaluate_entry(sig, LIVE, opt, 10.0) is None


def test_levels():
    assert MyStrategyBuy.levels(120, 110) == 140
    assert MyStrategyBuy.levels(120, 125) is None
    assert MyStrategySell.levels(120, 130) == 100
    assert MyStrategySell.levels(120, 110) is None
    assert MyStrategySell.levels(10, 30) is None


def position(side, sl, target):
    return Position(side, 65, 10.0, sl, target, "x", "o", "2026-09-21T10:17:00+05:30")


@pytest.mark.parametrize(
    "side,sl,target,price,expected",
    [
        ("LONG", 8, 14, 7.9, "STOP_LOSS"), ("LONG", 8, 14, 14, "TARGET"), ("LONG", 8, 14, 11, None),
        ("SHORT", 13, 4, 13, "STOP_LOSS"), ("SHORT", 13, 4, 3.9, "TARGET"), ("SHORT", 13, 4, 10, None),
    ],
)
def test_exit_rules(side, sl, target, price, expected):
    cls = MyStrategyBuy if side == "LONG" else MyStrategySell
    d = cls.evaluate_exit(position(side, sl, target), price)
    assert (d["reason"] if d else None) == expected


def test_calculate_does_not_touch_ohlcv():
    sig, _ = frames(100, 101)
    out = MyStrategyBuy.calculate(sig)
    assert list(out["close"]) == list(sig["close"]) and "close_change" in out.columns
