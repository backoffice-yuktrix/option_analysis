from __future__ import annotations

import pandas as pd

from app.timeutil import MINUTE


def row_at(df: pd.DataFrame, ts) -> pd.Series | None:
    if df.empty:
        return None
    hits = df[df["timestamp"] == pd.Timestamp(ts)]
    return None if hits.empty else hits.iloc[-1]


class BaseStrategy:
    """All prices here are NIFTY index points. The option is only the instrument orders are sent to."""

    name = ""
    side = ""
    entry_order_side = "BUY"
    stop_field = "low"

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
    def evaluate_entry(cls, signal_df, signal_live: dict, nifty_price: float) -> dict | None:
        minute = pd.Timestamp(signal_live["timestamp"])
        c1 = row_at(signal_df, minute - MINUTE)
        c2 = row_at(signal_df, minute - 2 * MINUTE)
        if c1 is None or c2 is None or c1["source"] != "official":
            return None
        if not cls.signal(float(c1["close"]), float(c2["close"])):
            return None

        stop = float(c2[cls.stop_field])
        decision = {
            "confirmed": False,
            "side": cls.side,
            "entry_reason": f"NIFTY Close(Cn-1)={c1['close']} vs Close(Cn-2)={c2['close']}",
            "signal_minute": minute.isoformat(),
            "reference_price": nifty_price,
            "stop_loss": stop,
        }
        target = cls.levels(nifty_price, stop)
        if target is None:
            return decision | {"reason": f"invalid NIFTY stop loss {stop} for {cls.side} at NIFTY {nifty_price}"}
        return decision | {"confirmed": True, "target": target, "risk_reward": "1:2"}

    @classmethod
    def evaluate_exit(cls, position, nifty_price: float) -> dict | None:
        if position.side == "LONG":
            if nifty_price <= position.stop_loss:
                return {"confirmed": True, "reason": "STOP_LOSS"}
            if position.target is not None and nifty_price >= position.target:
                return {"confirmed": True, "reason": "TARGET"}
        else:
            if nifty_price >= position.stop_loss:
                return {"confirmed": True, "reason": "STOP_LOSS"}
            if position.target is not None and nifty_price <= position.target:
                return {"confirmed": True, "reason": "TARGET"}
        return None
