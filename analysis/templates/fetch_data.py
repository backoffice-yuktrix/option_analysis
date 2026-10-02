"""Fetch candles into analysis/candle_datas (indices) and analysis/stock_datas (stocks).

The local data moved from analysis_rajkumarn/ into analysis/ on 2026-09-30 (the user).  The fetch tool itself,
analysis_rajkumarn/fetch_candles.py, is left exactly as it is: this module imports it and only points it at the
analysis/ folders -
    an index (NIFTY, SENSEX, BANKNIFTY ...) and its options   -> analysis/candle_datas
    any other instrument (a stock and its options)             -> analysis/stock_datas
The access token stays where that tool reads it (line 4 of analysis_rajkumarn/upstox_config.txt, refreshed with
its upstox_connect.py).  Nothing is fetched without the user's permission (RUN.md, Data).

CLI - from the repository root, the same arguments as fetch_candles.py:
    analysis/.venv/Scripts/python.exe analysis/templates/fetch_data.py candles NIFTY --from 2026-01-01 --to 2026-07-31
    analysis/.venv/Scripts/python.exe analysis/templates/fetch_data.py candles NIFTY --opt CE_23000_2026-01-27 --from 2026-01-07 --to 2026-01-27
    analysis/.venv/Scripts/python.exe analysis/templates/fetch_data.py candles RELIANCE --from 2026-01-01 --to 2026-07-31
    analysis/.venv/Scripts/python.exe analysis/templates/fetch_data.py expiries NIFTY --from 2026-01-01 --to 2026-07-31

In Python (for example the option-chain plan / run scripts of analysis_rajkumarn/fetch.md): put this folder on the
path and `import fetch_data` BEFORE `from fetch_candles import ...`, so DATA_DIR and every function already point
at analysis/.  Fetch one instrument at a time: the folder is switched per call.
"""
from __future__ import annotations

import asyncio
import functools
import os
import sys

ANALYSIS_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TOOL_DIR = os.path.abspath(os.path.join(ANALYSIS_DIR, "..", "analysis_rajkumarn"))
if TOOL_DIR not in sys.path:
    sys.path.insert(0, TOOL_DIR)
import fetch_candles as F  # noqa: E402   (the fetch tool, used as it is)

DATA_DIR = os.path.join(ANALYSIS_DIR, "candle_datas")          # indices and their options
STOCK_DATA_DIR = os.path.join(ANALYSIS_DIR, "stock_datas")     # stocks and their options
# BSE indices are not in the tool's own key table (its find_instrument searches NSE only); the keys are the ones
# at the head of the SENSEX files on disk (2026-09-30).
F.UNDERLYING_KEYS.setdefault("SENSEX", "BSE_INDEX|SENSEX")
F.UNDERLYING_KEYS.setdefault("BANKEX", "BSE_INDEX|BANKEX")
INDEX_NAMES = set(F.UNDERLYING_KEYS) | {"SENSEX", "BANKEX", "VIX"}      # VIX = India VIX (NSE_INDEX|India VIX), an index


def data_dir(instrument: str) -> str:
    """analysis/candle_datas for an index and its options, analysis/stock_datas for anything else."""
    return DATA_DIR if str(instrument).upper() in INDEX_NAMES else STOCK_DATA_DIR


def _route(fn, pos: int):
    """Run `fn` with the tool's DATA_DIR set to the folder of the instrument in argument `pos`."""
    if asyncio.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def run(*a, **k):
            inst = a[pos] if len(a) > pos else k.get("instrument")
            old, F.DATA_DIR = F.DATA_DIR, data_dir(inst)
            try:
                return await fn(*a, **k)
            finally:
                F.DATA_DIR = old
    else:
        @functools.wraps(fn)
        def run(*a, **k):
            inst = a[pos] if len(a) > pos else k.get("instrument")
            old, F.DATA_DIR = F.DATA_DIR, data_dir(inst)
            try:
                return fn(*a, **k)
            finally:
                F.DATA_DIR = old
    return run


# Every path the tool builds goes through DATA_DIR at call time, so switching it per instrument is enough.
F.DATA_DIR = DATA_DIR                    # the default for paths a runbook script builds itself (plans, logs)
for _name, _pos in (("candle_file", 0), ("fetch", 0), ("_contracts_file", 0), ("load_expiries", 0),
                    ("fetch_broker", 0), ("fetch_expiries", 0), ("contracts", 1)):
    setattr(F, _name, _route(getattr(F, _name), _pos))

candle_file, fetch, fetch_broker, fetch_expiries, load_expiries = (F.candle_file, F.fetch, F.fetch_broker,
                                                                   F.fetch_expiries, F.load_expiries)

if __name__ == "__main__":
    asyncio.run(F._main())
