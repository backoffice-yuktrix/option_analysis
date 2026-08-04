"""M1 — Intraday Swing Analysis pipeline.

Steps:
1. Fetch instrument OHLC at ATR timeframe (5m/15m/30m) for date range
2. Compute ATR(period)
3. Detect alternating Hill/Valley swings
4. Filter legs by magnitude >= pts_to_analyse
5. For each qualifying leg: compute 6 time-proportional checkpoints
6. Resolve option contracts + expiries
7. Fetch 1m option candles per unique (instrument_key, date)
8. Extract option prices at each checkpoint using High/Low rule
9. Compute metrics
10. Save timestamped JSON; return Module1Result
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from config import settings
from schemas.module1 import Module1Request, Module1Result, LegRow, NonQualifyingLeg, SwingPoint as SchemaSwingPoint
from services.upstox_client import get_candles, get_option_contracts, get_vix_daily, INSTRUMENT_KEYS
from services.swing_detector import compute_atr, detect_swings, build_all_legs, SwingPoint
from services.option_analyzer import (
    build_strike_grid,
    resolve_expiries,
    default_expiry as pick_default_expiry,
    direction_from_leg_type,
    along_option_type,
    against_option_type,
    cheapest_along_strike,
    compute_dte,
    dte_bucket,
    interpolate_checkpoints,
    snap_to_candle,
    option_price_at_checkpoint,
    filter_contracts,
    percent_optimal_option,
    profit_percent_optimal_option,
    strike_label,
    along_col_key,
    against_col_key,
    cheapest_col_key,
    dte_col_key,
)

CHECKPOINTS = [0, 20, 40, 60, 80, 100]


def _run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candle_date_ist(ts: str) -> str:
    """Return YYYY-MM-DD for a timestamp, adjusted to IST."""
    ts = ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return ts[:10]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ist = dt + timedelta(hours=5, minutes=30)
    return ist.date().isoformat()


async def run_module1(req: Module1Request, access_token: str) -> Module1Result:
    from_d = date.fromisoformat(req.from_date)
    to_d = date.fromisoformat(req.to_date)
    instr_key = INSTRUMENT_KEYS[req.instrument]
    run_id = _run_id()
    print(f"[M1:{run_id}] Starting — instrument={req.instrument} range={req.from_date}→{req.to_date} at {_ts()}")

    # Step 1: fetch OHLC at ATR timeframe
    print(f"[M1:{run_id}] Step 1: Fetching ATR candles ({req.atr.candle_tf}) at {_ts()}")
    atr_candles = await get_candles(access_token, instr_key, req.atr.candle_tf, from_d, to_d)
    print(f"[M1:{run_id}] Step 1 done — {len(atr_candles)} candles at {_ts()}")

    # Step 2: compute ATR
    print(f"[M1:{run_id}] Step 2: Computing ATR(period={req.atr.period}) at {_ts()}")
    atr_values = compute_atr(atr_candles, req.atr.period, req.atr.price_source)
    print(f"[M1:{run_id}] Step 2 done — {len(atr_values)} ATR values at {_ts()}")

    # Step 3: detect swings
    print(f"[M1:{run_id}] Step 3: Detecting swings (multiplier={req.atr.multiplier}) at {_ts()}")
    raw_swings = detect_swings(atr_candles, atr_values, req.atr.multiplier)
    print(f"[M1:{run_id}] Step 3 done — {len(raw_swings)} swing points at {_ts()}")

    # Step 4: split legs into qualifying and non-qualifying
    print(f"[M1:{run_id}] Step 4: Filtering legs (pts_to_analyse={req.pts_to_analyse}) at {_ts()}")
    qualifying_legs, non_qualifying_legs_raw = build_all_legs(raw_swings, req.pts_to_analyse)
    print(f"[M1:{run_id}] Step 4 done — {len(qualifying_legs)} qualifying, {len(non_qualifying_legs_raw)} non-qualifying legs at {_ts()}")

    # Fetch 1m candles for instrument (need for checkpoint prices)
    print(f"[M1:{run_id}] Step 5: Fetching 1m instrument candles at {_ts()}")
    instr_1m_candles = await get_candles(access_token, instr_key, "1m", from_d, to_d)
    print(f"[M1:{run_id}] Step 5 done — {len(instr_1m_candles)} 1m candles at {_ts()}")

    # Build index: {date_str: [candles]} for fast lookup
    instr_1m_by_date: dict[str, list[dict]] = {}
    for c in instr_1m_candles:
        d_str = _candle_date_ist(c.get("timestamp", ""))
        instr_1m_by_date.setdefault(d_str, []).append(c)
    print(f"[M1:{run_id}] Step 5b: 1m index built — {len(instr_1m_by_date)} trading days at {_ts()}")

    # Fetch VIX daily
    print(f"[M1:{run_id}] Step 6: Fetching VIX daily data at {_ts()}")
    vix_by_date = await get_vix_daily(access_token, from_d, to_d)
    print(f"[M1:{run_id}] Step 6 done — VIX for {len(vix_by_date)} days at {_ts()}")

    # Step 5–9: for each leg
    # First resolve option contracts (one call covers all strikes/expiries)
    print(f"[M1:{run_id}] Step 7: Fetching option contracts for {req.instrument} at {_ts()}")
    all_contracts = await get_option_contracts(access_token, req.instrument)
    print(f"[M1:{run_id}] Step 7 done — {len(all_contracts)} contracts at {_ts()}")

    # Collect unique (instrument_key, date) pairs needed across all legs
    OptionKey = tuple  # (instrument_key, from_date, to_date)
    needed_option_candles: dict[tuple[str, str], list[dict]] = {}

    # We'll build leg data in two passes: first collect all option keys needed,
    # then batch-fetch, then compute.
    leg_metas: list[dict[str, Any]] = []

    print(f"[M1:{run_id}] Step 8: Building leg metadata & collecting option keys at {_ts()}")
    for start_pt, end_pt in qualifying_legs:
        t0 = start_pt.timestamp
        t1 = end_pt.timestamp
        t0_date = _candle_date_ist(t0)
        spot_candle = snap_to_candle(instr_1m_by_date.get(t0_date, []), t0)
        spot = float(spot_candle.get("close", 0)) if spot_candle else 0.0

        atm, grid = build_strike_grid(spot, req.pts_to_analyse, req.option_range)
        expiries = resolve_expiries(all_contracts, t0_date, req.expiry_count)
        if not expiries:
            continue

        direction = direction_from_leg_type(end_pt.swing_type)
        checkpoints_ts = interpolate_checkpoints(t0, t1, CHECKPOINTS)

        # For each (expiry, strike, opt_type), collect the instrument_key
        needed: list[tuple[str, str, str, str]] = []  # (ikey, expiry, strike_str, opt_type)
        for expiry in expiries:
            for strike in grid:
                for opt_type in ("CE", "PE"):
                    contract = filter_contracts(all_contracts, expiry, strike, opt_type)
                    if contract:
                        ikey = contract["instrument_key"]
                        ikey_date = (ikey, t0_date)
                        if ikey_date not in needed_option_candles:
                            needed_option_candles[ikey_date] = []  # placeholder
                        needed.append((ikey, expiry, str(strike), opt_type))

        leg_metas.append({
            "start": start_pt,
            "end": end_pt,
            "t0_date": t0_date,
            "spot": spot,
            "atm": atm,
            "grid": grid,
            "expiries": expiries,
            "direction": direction,
            "checkpoints_ts": checkpoints_ts,
            "needed": needed,
        })

    print(f"[M1:{run_id}] Step 8 done — {len(leg_metas)} legs, {len(needed_option_candles)} unique option (key,date) pairs at {_ts()}")

    # Batch-fetch option 1m candles — one task per (instrument_key, date)
    print(f"[M1:{run_id}] Step 9: Batch-fetching option 1m candles (concurrency=5) at {_ts()}")
    async def _fetch_opt_candles(ikey: str, d_str: str) -> tuple[tuple[str, str], list[dict]]:
        d = date.fromisoformat(d_str)
        candles = await get_candles(access_token, ikey, "1m", d, d)
        return (ikey, d_str), candles

    # Collect all unique (ikey, date) combos first (avoid duplicate fetches)
    unique_pairs = list(needed_option_candles.keys())
    sem = asyncio.Semaphore(5)

    async def _safe_fetch(ikey: str, d_str: str):
        async with sem:
            try:
                return await _fetch_opt_candles(ikey, d_str)
            except Exception:
                return (ikey, d_str), []

    fetch_tasks = [_safe_fetch(ikey, d_str) for ikey, d_str in unique_pairs]
    fetch_results = await asyncio.gather(*fetch_tasks)
    for key, candles in fetch_results:
        needed_option_candles[key] = candles
    print(f"[M1:{run_id}] Step 9 done — fetched candles for {len(fetch_results)} option (key,date) pairs at {_ts()}")

    # Build leg rows
    print(f"[M1:{run_id}] Step 10: Computing checkpoint prices & option metrics for each leg at {_ts()}")
    leg_rows: list[LegRow] = []
    for meta in leg_metas:
        start_pt: SwingPoint = meta["start"]
        end_pt: SwingPoint = meta["end"]
        t0_date = meta["t0_date"]
        atm = meta["atm"]
        grid = meta["grid"]
        expiries = meta["expiries"]
        direction = meta["direction"]
        checkpoints_ts = meta["checkpoints_ts"]
        spot = meta["spot"]

        # Spot prices at checkpoints
        instr_day_candles = instr_1m_by_date.get(t0_date, [])
        columns: dict[str, Any] = {}

        instr_checkpoint_prices: dict[int, float | None] = {}
        for i, pct in enumerate(CHECKPOINTS):
            c = snap_to_candle(instr_day_candles, checkpoints_ts[i])
            instr_checkpoint_prices[pct] = float(c.get("close", 0)) if c else None

        for pct in [20, 40, 60, 80]:
            columns[f"instr_{pct}pct"] = instr_checkpoint_prices.get(pct)
            ts = checkpoints_ts[CHECKPOINTS.index(pct)]
            columns[f"time_{pct}pct"] = ts[11:16] if len(ts) > 11 else ts

        # Option prices at checkpoints for each expiry × strike × type
        def_expiry = pick_default_expiry(expiries)
        along_type = along_option_type(direction)
        against_type = against_option_type(direction)
        cheap_strike = cheapest_along_strike(direction, atm, req.pts_to_analyse, req.option_range)

        cheapest_along_prices: dict[int, float | None] = {}

        # Build per-expiry option metadata for the output
        expiry_details: dict[str, Any] = {}
        for exp_n, expiry in enumerate(expiries, start=1):
            expiry_details[f"exp{exp_n}"] = {
                "expiry_date": expiry,
                "along_type": along_type,
                "against_type": against_type,
                "atm_strike": int(atm),
                "atm_along_name": f"{int(atm)}{along_type}",
                "cheapest_along_strike": int(cheap_strike),
                "cheapest_along_name": f"{int(cheap_strike)}{along_type}",
            }

        for exp_n, expiry in enumerate(expiries, start=1):
            for strike in grid:
                slabel = strike_label(atm, strike, req.pts_to_analyse)
                for opt_type, side in [(along_type, "along"), (against_type, "against")]:
                    contract = filter_contracts(all_contracts, expiry, strike, opt_type)
                    if not contract:
                        for pct in CHECKPOINTS:
                            col = along_col_key(exp_n, slabel, pct) if side == "along" else against_col_key(exp_n, slabel, pct)
                            columns[col] = None
                        continue

                    ikey = contract["instrument_key"]
                    opt_candles = needed_option_candles.get((ikey, t0_date), [])

                    for i, pct in enumerate(CHECKPOINTS):
                        is_exit = pct == 100
                        price = option_price_at_checkpoint(opt_candles, checkpoints_ts[i], is_exit)
                        col = along_col_key(exp_n, slabel, pct) if side == "along" else against_col_key(exp_n, slabel, pct)
                        columns[col] = price

                        # Track cheapest along prices for metrics
                        if side == "along" and abs(strike - cheap_strike) < 0.01 and expiry == def_expiry:
                            cheapest_along_prices[pct] = price

            # DTE for this expiry
            columns[dte_col_key(exp_n)] = compute_dte(t0_date, expiry)

        # Metrics
        columns["percent_optimal_option"] = percent_optimal_option(
            cheapest_along_prices.get(0), cheapest_along_prices.get(100)
        )
        columns["profit_percent_optimal_option"] = profit_percent_optimal_option(
            cheapest_along_prices.get(20), cheapest_along_prices.get(80)
        )

        # Cheapest along column aliases (for default column set)
        def_exp_n = expiries.index(def_expiry) + 1 if def_expiry in expiries else 1
        cheap_slabel = strike_label(atm, cheap_strike, req.pts_to_analyse)
        for pct in CHECKPOINTS:
            columns[cheapest_col_key("along", def_exp_n, pct)] = cheapest_along_prices.get(pct)

        t1_date = _candle_date_ist(end_pt.timestamp)
        leg_rows.append(LegRow(
            date=t0_date,
            end_date=t1_date,
            start_time=start_pt.timestamp[11:16] if len(start_pt.timestamp) > 11 else start_pt.timestamp,
            end_time=end_pt.timestamp[11:16] if len(end_pt.timestamp) > 11 else end_pt.timestamp,
            leg_type=end_pt.swing_type,
            vix=vix_by_date.get(t0_date),
            abs_pts=abs(end_pt.price - start_pt.price),
            start_price=start_pt.price,
            end_price=end_pt.price,
            expiry_details=expiry_details,
            columns=columns,
        ))

    print(f"[M1:{run_id}] Step 10 done — {len(leg_rows)} leg rows built at {_ts()}")

    # Build non-qualifying leg rows for chart overlay (grey connectors)
    non_qual_rows: list[NonQualifyingLeg] = []
    for s, e in non_qualifying_legs_raw:
        non_qual_rows.append(NonQualifyingLeg(
            date=_candle_date_ist(s.timestamp),
            end_date=_candle_date_ist(e.timestamp),
            start_time=s.timestamp[11:16] if len(s.timestamp) > 11 else s.timestamp,
            end_time=e.timestamp[11:16] if len(e.timestamp) > 11 else e.timestamp,
            start_price=s.price,
            end_price=e.price,
        ))

    # Build column metadata (for frontend column picker)
    print(f"[M1:{run_id}] Step 11: Building column metadata at {_ts()}")
    column_meta = _build_column_meta(req, leg_metas)
    print(f"[M1:{run_id}] Step 11 done — {len(column_meta)} columns defined at {_ts()}")

    # Schema swing points for chart overlay
    schema_swings = [
        SchemaSwingPoint(timestamp=sp.timestamp, price=sp.price, swing_type=sp.swing_type)
        for sp in raw_swings
    ]

    result = Module1Result(
        instrument=req.instrument,
        from_date=req.from_date,
        to_date=req.to_date,
        pts_to_analyse=req.pts_to_analyse,
        option_range=req.option_range,
        expiry_count=req.expiry_count,
        atr=req.atr,
        swing_points=schema_swings,
        legs=leg_rows,
        non_qualifying_legs=non_qual_rows,
        column_meta=column_meta,
        chart_candles=atr_candles,
        run_id=run_id,
    )

    # Save JSON
    print(f"[M1:{run_id}] Step 12: Saving results to disk at {_ts()}")
    os.makedirs(settings.RESULTS_DIR, exist_ok=True)
    out_path = os.path.join(settings.RESULTS_DIR, f"results_module1_{run_id}.json")
    with open(out_path, "w") as f:
        json.dump(result.model_dump(), f, default=str)
    print(f"[M1:{run_id}] Step 12 done — saved to {out_path} at {_ts()}")
    print(f"[M1:{run_id}] Completed at {_ts()}")

    return result


def _build_column_meta(req: Module1Request, leg_metas: list[dict]) -> dict[str, Any]:
    """Produce {column_key: {label, group, ...}} metadata for the frontend picker."""
    meta: dict[str, Any] = {}

    # Group A — instrument checkpoints (0% and 100% are must-have columns, not in picker)
    for pct in [20, 40, 60, 80]:
        key = f"instr_{pct}pct"
        meta[key] = {"label": f"Instr {pct}%", "group": "A"}

    for exp_n in range(1, req.expiry_count + 1):
        for k in range(-req.option_range, req.option_range + 1):
            slabel = strike_label(0, k * req.pts_to_analyse, req.pts_to_analyse)
            for pct in CHECKPOINTS:
                for side, group in [("along", "B"), ("against", "C")]:
                    col_fn = along_col_key if side == "along" else against_col_key
                    key = col_fn(exp_n, slabel, pct)
                    meta[key] = {
                        "label": f"Exp{exp_n} {slabel} {side.capitalize()} {pct}%",
                        "group": group,
                        "exp_n": exp_n,
                        "strike_label": slabel,
                        "side": side,
                        "pct": pct,
                    }

        # Cheapest along aliases for each expiry (default column set uses these)
        for pct in CHECKPOINTS:
            key = cheapest_col_key("along", exp_n, pct)
            meta[key] = {
                "label": f"Exp{exp_n} Cheapest Along {pct}%",
                "group": "B",
                "exp_n": exp_n,
                "strike_label": "cheapest",
                "side": "along",
                "pct": pct,
            }

    # Group D — metrics only (DTE is not a column picker item for M1 per PRD §4.6)
    meta["percent_optimal_option"] = {"label": "% Optimal Option", "group": "D"}
    meta["profit_percent_optimal_option"] = {"label": "Profit % Optimal Option", "group": "D"}
    return meta
