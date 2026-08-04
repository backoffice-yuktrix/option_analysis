"""M2 — Overnight Gap Analysis pipeline.

Steps:
1. Fetch 1m instrument OHLC for the date range
2. Build session list: 3:15 PM day D → 9:25 AM day D+1 (skip if T1 unavailable)
3. For each session: resolve option contracts, fetch T0/T1 option prices
4. Compute metrics, save JSON
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from config import settings
from schemas.module2 import Module2Request, Module2Result, SessionRow
from services.upstox_client import get_candles, get_option_contracts, get_vix_daily, INSTRUMENT_KEYS
from services.option_analyzer import (
    build_strike_grid,
    resolve_expiries,
    default_expiry as pick_default_expiry,
    direction_from_leg_type,
    along_option_type,
    against_option_type,
    cheapest_along_strike,
    compute_dte,
    snap_to_candle,
    filter_contracts,
    option_price_at_checkpoint,
    percent_optimal_option,
    profit_percent_optimal_option,
    strike_label,
    along_col_key,
    against_col_key,
    cheapest_col_key,
    dte_col_key,
)

# Market times (IST expressed as UTC offset)
_ENTRY_HOUR_UTC = 9     # 15:15 IST = 09:45 UTC (use candle at 09:45)
_ENTRY_MIN_UTC = 45
_EXIT_HOUR_UTC = 3      # 09:25 IST = 03:55 UTC
_EXIT_MIN_UTC = 55


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(s: str) -> datetime:
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _candle_date_ist(ts: str) -> str:
    dt = _parse_ts(ts)
    ist = dt + timedelta(hours=5, minutes=30)
    return ist.date().isoformat()


def _build_1m_index(candles: list[dict]) -> dict[str, list[dict]]:
    """Index 1m candles by IST date → list[candle]."""
    idx: dict[str, list[dict]] = {}
    for c in candles:
        d = _candle_date_ist(c.get("timestamp", ""))
        idx.setdefault(d, []).append(c)
    return idx


def _find_candle_at(candles_for_day: list[dict], hour_utc: int, min_utc: int) -> dict | None:
    """Find the 1m candle whose timestamp matches hour:minute (UTC)."""
    for c in candles_for_day:
        try:
            dt = _parse_ts(c.get("timestamp", "")).astimezone(timezone.utc)
            if dt.hour == hour_utc and dt.minute == min_utc:
                return c
        except Exception:
            continue
    return None


def _sorted_trading_days(candle_index: dict[str, list[dict]]) -> list[str]:
    return sorted(candle_index.keys())


async def run_module2(req: Module2Request, access_token: str) -> Module2Result:
    from_d = date.fromisoformat(req.from_date)
    to_d = date.fromisoformat(req.to_date)
    instr_key = INSTRUMENT_KEYS[req.instrument]
    run_id = _run_id()
    print(f"[M2:{run_id}] Starting — instrument={req.instrument} range={req.from_date}→{req.to_date} at {_ts()}")

    # Fetch 1m instrument data for range (entry at 3:15 PM, exit at 9:25 AM next day)
    # We need slightly beyond to_date to get the next-day 9:25 AM candle
    extended_to = to_d + timedelta(days=4)  # covers weekends
    print(f"[M2:{run_id}] Step 1: Fetching 1m instrument candles (extended to {extended_to}) at {_ts()}")
    instr_1m = await get_candles(access_token, instr_key, "1m", from_d, extended_to)
    print(f"[M2:{run_id}] Step 1 done — {len(instr_1m)} 1m candles at {_ts()}")

    candle_by_date = _build_1m_index(instr_1m)
    trading_days = _sorted_trading_days(candle_by_date)
    print(f"[M2:{run_id}] Step 1b: Index built — {len(trading_days)} trading days at {_ts()}")

    print(f"[M2:{run_id}] Step 2: Fetching VIX daily data at {_ts()}")
    vix_by_date = await get_vix_daily(access_token, from_d, extended_to)
    print(f"[M2:{run_id}] Step 2 done — VIX for {len(vix_by_date)} days at {_ts()}")

    print(f"[M2:{run_id}] Step 3: Fetching option contracts for {req.instrument} at {_ts()}")
    all_contracts = await get_option_contracts(access_token, req.instrument)
    print(f"[M2:{run_id}] Step 3 done — {len(all_contracts)} contracts at {_ts()}")

    # Build sessions
    print(f"[M2:{run_id}] Step 4: Building overnight gap sessions at {_ts()}")
    sessions_meta: list[dict[str, Any]] = []
    for i, d_str in enumerate(trading_days):
        d_date = date.fromisoformat(d_str)
        if d_date < from_d or d_date > to_d:
            continue

        t0_candle = _find_candle_at(candle_by_date.get(d_str, []), _ENTRY_HOUR_UTC, _ENTRY_MIN_UTC)
        if not t0_candle:
            continue

        # Find next trading day
        next_days = trading_days[i + 1:]
        if not next_days:
            continue
        next_d_str = next_days[0]
        t1_candle = _find_candle_at(candle_by_date.get(next_d_str, []), _EXIT_HOUR_UTC, _EXIT_MIN_UTC)
        if not t1_candle:
            continue

        t0_price = float(t0_candle.get("close", 0))
        t1_price = float(t1_candle.get("close", 0))
        gap_pts = t1_price - t0_price
        direction = "up" if gap_pts >= 0 else "down"

        atm, grid = build_strike_grid(t0_price, req.pts_to_analyse, req.option_range)
        expiries = resolve_expiries(all_contracts, d_str, req.expiry_count)
        if not expiries:
            continue

        sessions_meta.append({
            "date": d_str,
            "next_date": next_d_str,
            "t0_candle": t0_candle,
            "t1_candle": t1_candle,
            "t0_price": t0_price,
            "t1_price": t1_price,
            "gap_pts": gap_pts,
            "direction": direction,
            "atm": atm,
            "grid": grid,
            "expiries": expiries,
        })

    print(f"[M2:{run_id}] Step 4 done — {len(sessions_meta)} valid overnight sessions at {_ts()}")

    # Collect unique option (ikey, date) combos
    print(f"[M2:{run_id}] Step 5: Collecting unique option (key, date) pairs at {_ts()}")
    needed: dict[tuple[str, str], list[dict]] = {}
    for meta in sessions_meta:
        d_str = meta["date"]
        next_d_str = meta["next_date"]
        for expiry in meta["expiries"]:
            for strike in meta["grid"]:
                for opt_type in ("CE", "PE"):
                    contract = filter_contracts(all_contracts, expiry, strike, opt_type)
                    if contract:
                        ikey = contract["instrument_key"]
                        for fetch_date in (d_str, next_d_str):
                            needed.setdefault((ikey, fetch_date), [])

    print(f"[M2:{run_id}] Step 5 done — {len(needed)} unique option (key,date) pairs at {_ts()}")

    # Batch-fetch option candles
    print(f"[M2:{run_id}] Step 6: Batch-fetching option 1m candles (concurrency=5) at {_ts()}")
    sem = asyncio.Semaphore(5)

    async def _fetch(ikey: str, d_str: str) -> tuple[tuple[str, str], list[dict]]:
        async with sem:
            try:
                d = date.fromisoformat(d_str)
                candles = await get_candles(access_token, ikey, "1m", d, d)
                return (ikey, d_str), candles
            except Exception:
                return (ikey, d_str), []

    results = await asyncio.gather(*(_fetch(ik, ds) for ik, ds in needed.keys()))
    opt_candles: dict[tuple[str, str], list[dict]] = {k: v for k, v in results}
    print(f"[M2:{run_id}] Step 6 done — fetched candles for {len(results)} option (key,date) pairs at {_ts()}")

    # Build session rows
    print(f"[M2:{run_id}] Step 7: Computing option prices & metrics for each session at {_ts()}")
    session_rows: list[SessionRow] = []
    for meta in sessions_meta:
        d_str = meta["date"]
        next_d_str = meta["next_date"]
        atm = meta["atm"]
        grid = meta["grid"]
        expiries = meta["expiries"]
        direction = meta["direction"]
        t0_candle = meta["t0_candle"]
        t1_candle = meta["t1_candle"]
        t0_ts = t0_candle["timestamp"]
        t1_ts = t1_candle["timestamp"]

        along_type = along_option_type(direction)
        against_type = against_option_type(direction)
        def_expiry = pick_default_expiry(expiries)
        cheap_strike = cheapest_along_strike(direction, atm, req.pts_to_analyse, req.option_range)

        columns: dict[str, Any] = {}
        cheapest_t0: float | None = None
        cheapest_t1: float | None = None

        for exp_n, expiry in enumerate(expiries, start=1):
            columns[dte_col_key(exp_n)] = compute_dte(d_str, expiry)

            for strike in grid:
                slabel = strike_label(atm, strike, req.pts_to_analyse)
                for opt_type, side in [(along_type, "along"), (against_type, "against")]:
                    contract = filter_contracts(all_contracts, expiry, strike, opt_type)
                    if not contract:
                        for pct in [0, 100]:
                            col = along_col_key(exp_n, slabel, pct) if side == "along" else against_col_key(exp_n, slabel, pct)
                            columns[col] = None
                        continue

                    ikey = contract["instrument_key"]
                    t0_cans = opt_candles.get((ikey, d_str), [])
                    t1_cans = opt_candles.get((ikey, next_d_str), [])

                    price_t0 = option_price_at_checkpoint(t0_cans, t0_ts, is_exit=False)
                    price_t1 = option_price_at_checkpoint(t1_cans, t1_ts, is_exit=True)

                    col_0 = along_col_key(exp_n, slabel, 0) if side == "along" else against_col_key(exp_n, slabel, 0)
                    col_100 = along_col_key(exp_n, slabel, 100) if side == "along" else against_col_key(exp_n, slabel, 100)
                    columns[col_0] = price_t0
                    columns[col_100] = price_t1

                    if side == "along" and abs(strike - cheap_strike) < 0.01 and expiry == def_expiry:
                        cheapest_t0 = price_t0
                        cheapest_t1 = price_t1

        # Cheapest along aliases
        def_exp_n = expiries.index(def_expiry) + 1 if def_expiry in expiries else 1
        columns[cheapest_col_key("along", def_exp_n, 0)] = cheapest_t0
        columns[cheapest_col_key("along", def_exp_n, 100)] = cheapest_t1

        # Metrics (for M2: 20%≡0% and 80%≡100%)
        columns["percent_optimal_option"] = percent_optimal_option(cheapest_t0, cheapest_t1)
        columns["profit_percent_optimal_option"] = profit_percent_optimal_option(cheapest_t0, cheapest_t1)

        gap_dir_label = "GapUp" if meta["gap_pts"] >= 0 else "GapDown"
        session_rows.append(SessionRow(
            date=d_str,
            entry_time="15:15",
            exit_time="09:25",
            gap_pts=round(meta["gap_pts"], 2),
            gap_direction=gap_dir_label,
            vix=vix_by_date.get(d_str),
            start_price=meta["t0_price"],
            end_price=meta["t1_price"],
            columns=columns,
        ))

    print(f"[M2:{run_id}] Step 7 done — {len(session_rows)} session rows built at {_ts()}")

    print(f"[M2:{run_id}] Step 8: Building column metadata at {_ts()}")
    column_meta = _build_column_meta(req)
    print(f"[M2:{run_id}] Step 8 done — {len(column_meta)} columns defined at {_ts()}")

    result = Module2Result(
        instrument=req.instrument,
        from_date=req.from_date,
        to_date=req.to_date,
        pts_to_analyse=req.pts_to_analyse,
        option_range=req.option_range,
        expiry_count=req.expiry_count,
        sessions=session_rows,
        column_meta=column_meta,
        run_id=run_id,
    )

    print(f"[M2:{run_id}] Step 9: Saving results to disk at {_ts()}")
    os.makedirs(settings.RESULTS_DIR, exist_ok=True)
    out_path = os.path.join(settings.RESULTS_DIR, f"results_module2_{run_id}.json")
    with open(out_path, "w") as f:
        json.dump(result.model_dump(), f, default=str)
    print(f"[M2:{run_id}] Step 9 done — saved to {out_path} at {_ts()}")
    print(f"[M2:{run_id}] Completed at {_ts()}")

    return result


def _build_column_meta(req: Module2Request) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for exp_n in range(1, req.expiry_count + 1):
        # Group E — DTE per expiry
        meta[dte_col_key(exp_n)] = {"label": f"DTE Exp{exp_n}", "group": "E"}

        for k in range(-req.option_range, req.option_range + 1):
            slabel = strike_label(0, k * req.pts_to_analyse, req.pts_to_analyse)
            for pct in [0, 100]:
                for side, group in [("along", "B"), ("against", "C")]:
                    col_fn = along_col_key if side == "along" else against_col_key
                    key = col_fn(exp_n, slabel, pct)
                    meta[key] = {
                        "label": f"Exp{exp_n} {slabel} {side.capitalize()} {'Entry' if pct == 0 else 'Exit'}",
                        "group": group,
                        "exp_n": exp_n,
                        "strike_label": slabel,
                        "side": side,
                        "pct": pct,
                    }

        # Cheapest along aliases for each expiry (default column set uses these)
        for pct in [0, 100]:
            key = cheapest_col_key("along", exp_n, pct)
            meta[key] = {
                "label": f"Exp{exp_n} Cheapest Along {'Entry' if pct == 0 else 'Exit'}",
                "group": "B",
                "exp_n": exp_n,
                "strike_label": "cheapest",
                "side": "along",
                "pct": pct,
            }

    # Group E — metrics
    meta["percent_optimal_option"] = {"label": "% Optimal Option", "group": "E"}
    meta["profit_percent_optimal_option"] = {"label": "Profit % Optimal", "group": "E"}
    return meta
