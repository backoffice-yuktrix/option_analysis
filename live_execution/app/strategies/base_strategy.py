from __future__ import annotations

import pandas as pd

from app.timeutil import MINUTE


def row_at(df: pd.DataFrame, ts) -> pd.Series | None:
    if df.empty:
        return None
    hits = df[df["timestamp"] == pd.Timestamp(ts)]
    return None if hits.empty else hits.iloc[-1]


class BaseStrategy:
    name = ""
    side = ""

    @staticmethod
    def calculate(candle_df: pd.DataFrame) -> pd.DataFrame:
        df = candle_df.copy()
        df["close_change"] = df["close"].astype(float).diff()
        return df

    @classmethod
    def signal(cls, close_prev: float, close_prev2: float) -> bool:
        raise NotImplementedError

    @classmethod
    def levels(cls, entry_price: float, stop_loss: float) -> float | None:
        raise NotImplementedError

    @classmethod
    def evaluate_entry(cls, signal_df, signal_live: dict, option_df, option_price: float) -> dict | None:
        minute = pd.Timestamp(signal_live["timestamp"])
        c1 = row_at(signal_df, minute - MINUTE)
        c2 = row_at(signal_df, minute - 2 * MINUTE)
        if c1 is None or c2 is None or c1["source"] != "official":
            return None
        if not cls.signal(float(c1["close"]), float(c2["close"])):
            return None

        decision = {
            "confirmed": False,
            "side": cls.side,
            "entry_reason": f"Close(Cn-1)={c1['close']} vs Close(Cn-2)={c2['close']}",
            "signal_minute": minute.isoformat(),
            "reference_price": option_price,
        }
        o2 = row_at(option_df, minute - 2 * MINUTE)
        if o2 is None:
            return decision | {"reason": "option candle Cn-2 missing, cannot set stop loss"}
        stop = float(o2["low"])
        target = cls.levels(option_price, stop)
        if target is None:
            return decision | {
                "stop_loss": stop,
                "reason": f"invalid stop loss {stop} for {cls.side} at reference price {option_price}",
            }
        return decision | {"confirmed": True, "stop_loss": stop, "target": target, "risk_reward": "1:2"}

    @classmethod
    def evaluate_exit(cls, position, price: float) -> dict | None:
        if position.side == "LONG":
            if price <= position.stop_loss:
                return {"confirmed": True, "reason": "STOP_LOSS"}
            if position.target is not None and price >= position.target:
                return {"confirmed": True, "reason": "TARGET"}
        else:
            if price >= position.stop_loss:
                return {"confirmed": True, "reason": "STOP_LOSS"}
            if position.target is not None and price <= position.target:
                return {"confirmed": True, "reason": "TARGET"}
        return None
