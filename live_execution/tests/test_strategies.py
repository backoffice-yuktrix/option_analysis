from datetime import datetime

import pytest

from app.config import IST
from app.execution.state import Position
from app.market_data.candle_store import CandleStore
from app.strategies.my_strategy_buy import MyStrategyBuy
from app.strategies.my_strategy_sell import MyStrategySell


def t(m):
    return datetime(2026, 9, 21, 10, m, tzinfo=IST)


def candle(m, close, low):
    return {"timestamp": t(m), "open": close, "high": close, "low": low, "close": close, "volume": 0}


def frame(c2_close, c1_close, c2_low, c1_source="official"):
    store = CandleStore()
    store.upsert(candle(15, c2_close, c2_low), "official")
    store.upsert(candle(16, c1_close, c1_close), c1_source)
    return store.frame()


LIVE = {"timestamp": t(17)}


def test_buy_signal_and_levels_in_nifty_points():
    d = MyStrategyBuy.evaluate_entry(frame(23400, 23410, 23390), LIVE, 23415.0)
    assert d["confirmed"] and d["stop_loss"] == 23390 and d["target"] == 23465.0


def test_buy_no_signal_when_equal_or_lower():
    for c1 in (23400, 23390):
        assert MyStrategyBuy.evaluate_entry(frame(23400, c1, 23390), LIVE, 23415.0) is None


def test_buy_needs_official_previous_candle():
    assert MyStrategyBuy.evaluate_entry(frame(23400, 23410, 23390, "local"), LIVE, 23415.0) is None


def test_buy_rejected_when_price_at_or_below_stop():
    d = MyStrategyBuy.evaluate_entry(frame(23400, 23410, 23420), LIVE, 23415.0)
    assert d["confirmed"] is False


def test_sell_valid_when_nifty_broke_below_prior_low():
    d = MyStrategySell.evaluate_entry(frame(23400, 23380, 23390), LIVE, 23385.0)
    assert d["confirmed"] and d["stop_loss"] == 23390 and d["target"] == 23375.0


def test_sell_rejected_when_stop_not_above_entry():
    d = MyStrategySell.evaluate_entry(frame(23400, 23392, 23380), LIVE, 23392.0)
    assert d["confirmed"] is False


def test_sell_no_signal_when_close_rises():
    assert MyStrategySell.evaluate_entry(frame(23400, 23410, 23390), LIVE, 23415.0) is None


def test_levels():
    assert MyStrategyBuy.levels(120, 110) == 140
    assert MyStrategyBuy.levels(120, 125) is None
    assert MyStrategySell.levels(120, 130) == 100
    assert MyStrategySell.levels(120, 110) is None


def position(side, sl, target):
    return Position(side, 65, 10.0, sl, target, "x", "o", "2026-09-21T10:17:00+05:30", 23400.0)


@pytest.mark.parametrize(
    "side,sl,target,price,expected",
    [
        ("LONG", 23390, 23450, 23389, "STOP_LOSS"), ("LONG", 23390, 23450, 23450, "TARGET"),
        ("LONG", 23390, 23450, 23420, None),
        ("SHORT", 23410, 23350, 23410, "STOP_LOSS"), ("SHORT", 23410, 23350, 23349, "TARGET"),
        ("SHORT", 23410, 23350, 23380, None),
    ],
)
def test_exit_rules(side, sl, target, price, expected):
    cls = MyStrategyBuy if side == "LONG" else MyStrategySell
    d = cls.evaluate_exit(position(side, sl, target), price)
    assert (d["reason"] if d else None) == expected


def test_calculate_does_not_touch_ohlcv():
    df = frame(23400, 23410, 23390)
    out = MyStrategyBuy.calculate(df)
    assert list(out["close"]) == list(df["close"]) and "close_change" in out.columns
