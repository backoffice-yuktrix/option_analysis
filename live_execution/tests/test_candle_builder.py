from datetime import datetime

from app.config import IST
from app.market_data.candle_builder import CandleBuilder
from app.models import Tick


def tick(h, m, s, price, vtt=None):
    return Tick("K", price, datetime(2026, 9, 21, h, m, s, tzinfo=IST), vtt)


def test_first_tick_starts_candle():
    b = CandleBuilder("K")
    assert b.on_tick(tick(10, 17, 3, 100)) == []
    assert b.live["open"] == b.live["close"] == 100
    assert b.live["timestamp"] == datetime(2026, 9, 21, 10, 17, tzinfo=IST)


def test_multiple_ticks_update_ohlc():
    b = CandleBuilder("K")
    for s, p in [(1, 100), (2, 105), (3, 98), (4, 102)]:
        b.on_tick(tick(10, 17, s, p))
    assert (b.live["open"], b.live["high"], b.live["low"], b.live["close"]) == (100, 105, 98, 102)


def test_same_price_ticks_are_kept():
    b = CandleBuilder("K")
    b.on_tick(tick(10, 17, 1, 100))
    b.on_tick(tick(10, 17, 2, 100))
    assert b.version == 2


def test_new_minute_finalizes_previous():
    b = CandleBuilder("K")
    b.on_tick(tick(10, 17, 1, 100))
    b.on_tick(tick(10, 17, 30, 110))
    done = b.on_tick(tick(10, 18, 0, 111))
    assert len(done) == 1
    assert done[0]["close"] == 110 and done[0]["high"] == 110
    assert b.live["open"] == 111


def test_duplicate_tick_ignored():
    b = CandleBuilder("K")
    b.on_tick(tick(10, 17, 1, 100, vtt=10))
    b.on_tick(tick(10, 17, 1, 100, vtt=10))
    assert b.version == 1 and b.ignored_duplicates == 1


def test_out_of_order_tick_ignored():
    b = CandleBuilder("K")
    b.on_tick(tick(10, 18, 1, 100))
    assert b.on_tick(tick(10, 17, 59, 90)) == []
    assert b.ignored_out_of_order == 1 and b.live["low"] == 100


def test_volume_from_cumulative_total():
    b = CandleBuilder("K")
    b.on_tick(tick(10, 17, 1, 100, vtt=1000))
    b.on_tick(tick(10, 17, 2, 101, vtt=1030))
    b.on_tick(tick(10, 17, 3, 102, vtt=1050))
    assert b.live["volume"] == 50


def test_gap_of_missing_minutes_still_finalizes():
    b = CandleBuilder("K")
    b.on_tick(tick(10, 17, 1, 100))
    done = b.on_tick(tick(10, 21, 0, 105))
    assert len(done) == 1 and b.live["timestamp"].minute == 21


def test_roll_to_finalizes_without_tick():
    b = CandleBuilder("K")
    b.on_tick(tick(10, 17, 1, 100))
    done = b.roll_to(datetime(2026, 9, 21, 10, 18, tzinfo=IST))
    assert len(done) == 1 and b.live is None
