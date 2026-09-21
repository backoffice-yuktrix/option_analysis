from __future__ import annotations

from app.strategies.base_strategy import BaseStrategy


class MyStrategySell(BaseStrategy):
    name = "MyStrategy_Sell"
    side = "SHORT"

    @classmethod
    def signal(cls, close_prev: float, close_prev2: float) -> bool:
        return close_prev < close_prev2

    @classmethod
    def levels(cls, entry_price: float, stop_loss: float) -> float | None:
        risk = stop_loss - entry_price
        if risk <= 0:
            return None
        target = round(entry_price - 2 * risk, 2)
        return target if target > 0 else None
