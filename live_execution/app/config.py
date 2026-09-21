from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "upstox_config.txt"
DB_FILE = BASE_DIR / "data" / "live_execution.db"
LOG_FILE = BASE_DIR / "logs" / "live_execution.log"
FRONTEND_DIR = BASE_DIR / "frontend"

IST = timezone(timedelta(hours=5, minutes=30))
API = "https://api.upstox.com"
HFT_API = "https://api-hft.upstox.com"

SIGNAL_KEY = "NSE_INDEX|Nifty 50"
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def read_token() -> str:
    if not CONFIG_FILE.exists():
        raise RuntimeError(f"Missing {CONFIG_FILE}. Run connect_upstox.py first.")
    lines = [l.strip() for l in CONFIG_FILE.read_text(encoding="utf-8").splitlines()]
    if len(lines) < 4 or not lines[3]:
        raise RuntimeError("No access token on line 4 of upstox_config.txt. Run connect_upstox.py first.")
    return lines[3]


@dataclass(frozen=True)
class Settings:
    live: bool = False
    warmup_late_second: int = 50
    warmup_settle_seconds: int = 3
    history_days: int = 5
    max_candles: int = 500
    reconcile_retries: int = 8
    reconcile_retry_delay: float = 1.5
    max_signal_tick_age: float = 5.0
    entry_start: time = time(9, 20)
    entry_end: time = time(15, 10)
    squareoff: time = time(15, 10)
    max_entries_per_day: int = 10
    max_daily_loss: float = 3000.0
    order_poll_interval: float = 0.5
    order_timeout: float = 15.0
    max_exit_failures: int = 3
    exit_retry_delay: float = 3.0


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    strategy_name: str
    underlying_key: str
    strike: float
    option_type: str
    expiry: str
    lots: int = 1


STRATEGY_SPECS: dict[str, StrategySpec] = {
    "buy": StrategySpec("buy_strategy", "MyStrategy_Buy", SIGNAL_KEY, 23600.0, "CE", "2026-09-22"),
    "sell": StrategySpec("sell_strategy", "MyStrategy_Sell", SIGNAL_KEY, 23200.0, "PE", "2026-09-22"),
}


def load_settings() -> Settings:
    return Settings(live=True)


def selected_strategies() -> list[str]:
    raw = os.environ.get("LIVE_STRATEGIES", "buy,sell")
    return [k.strip() for k in raw.split(",") if k.strip() in STRATEGY_SPECS]
