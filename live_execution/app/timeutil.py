from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from app.config import IST

MINUTE = timedelta(minutes=1)


def floor_minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def to_ts(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(IST)
    return ts.tz_convert(IST)


def minute_key(value) -> int:
    return int(to_ts(value).timestamp())
