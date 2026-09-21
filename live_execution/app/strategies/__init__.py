from app.strategies.base_strategy import BaseStrategy
from app.strategies.my_strategy_buy import MyStrategyBuy
from app.strategies.my_strategy_sell import MyStrategySell

STRATEGY_CLASSES: dict[str, type[BaseStrategy]] = {
    MyStrategyBuy.name: MyStrategyBuy,
    MyStrategySell.name: MyStrategySell,
}
