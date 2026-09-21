from __future__ import annotations

from app.strategies.base_strategy import BaseStrategy


class MyStrategyBuy(BaseStrategy):
    name = "MyStrategy_Buy"
    side = "LONG"

    @classmethod
    def signal(cls, close_prev: float, close_prev2: float) -> bool:
        return close_prev > close_prev2

    @classmethod
    def levels(cls, entry_price: float, stop_loss: float) -> float | None:
        risk = entry_price - stop_loss
        if risk <= 0:
            return None
        return round(entry_price + 2 * risk, 2)
