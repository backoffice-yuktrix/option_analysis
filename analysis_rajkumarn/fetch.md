# fetch.md: historical option-chain candles from Upstox

This file is a runbook for Claude, and a reference for anyone reading the data. It covers how
index and option candles are fetched into `candle_datas/` and how to read them back. When this
file is given with a request to fetch, **follow the "Runbook" section step by step**.

Everything lives in `analysis_rajkumarn/`. Run commands from that folder with its venv
(`.venv/Scripts/python`). The access token is line 4 of `upstox_config.txt`. If it has expired
(HTTP 401/403), the user refreshes it with `upstox_connect.py`.

---

## 1. Approach

For every expiry of an instrument in a date range:

1. **Window**: `expiry - 20 days .. expiry`. For a Tuesday expiry that is three weeks, from the
   Wednesday three weeks back to expiry day (Jan 27, 2026 Tue → Jan 7, 2026 Wed .. Jan 27, 2026).
2. **Range**: the high and low of the index's 1-minute candles inside that window.
3. **Strikes**: every *listed* strike in `[low - tolerance, high + tolerance]` that is a multiple
   of the chosen strike interval (NIFTY: tolerance 500, interval 50). Both CE and PE, so
   contracts = strikes × 2.
4. **Fetch** each contract's 1-minute candles for the window, into `candle_datas/`.

Upstox facts this is built on (measured 2026-09-29):

| | |
|---|---|
| Rate limits (published, "Other Standard APIs") | 50/s, 500/min, **2000 per 30 min**. The 30-min cap is the one that binds (~66/min on average) |
| v3 historical candles, 1–15 min | max range **1 calendar month**: `to` may be at most the same day next month (Feb 15..Mar 15 ok, ..Mar 16 → `UDAPI1148 Invalid date range`). So batches are Jan 1..Jan 31, Feb 1..Feb 28, … not a fixed 30 days |
| Expired-contract candles (`/v2/expired-instruments/historical-candle`) | needs the Upstox Plus plan (available on this account); a 21-day window comes back complete in **one call** |
| Latency | ~90–210 ms per call |
| Missing option minutes | normal: Upstox returns only minutes that traded; far-OTM/deep-ITM strikes have gaps, and some days have none |

**Pacing:** one call per second (~1800 per 30 min), with 90% of the published caps as a safety
net. This never reaches the 30-min cap, where a breach locks the account out for minutes. A
429 still makes the client cool down and slow itself (`upstox_funcs.Upstox.get`).

**Resumable:** every file is saved as soon as its batch arrives and records the date ranges
already fetched, so a re-run only asks for what is missing. Stop at any time and run again.

Reference run: NIFTY, expiries Jan 6 – Jul 28, 2026 (30 expiries), tolerance 500, 50-pt strikes → 2812
contracts, 2811 calls in 47m 51s, 0 throttled, 0 failed, ~835 MB.

---

## 2. Runbook for Claude

### Ask first
Ask the user for anything the request does not already give:

| Input | Example | Notes |
|---|---|---|
| instrument | `NIFTY` | index name as in `fetch_candles.UNDERLYING_KEYS` (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY) or any NSE symbol |
| from | `2026-01-01` | expiries on or after this date |
| to | `2026-07-31` | expiries on or before this date; must be a past date (only closed sessions are fetched) |
| strike interval | `50` for NIFTY, `100` for BANKNIFTY | only strikes that are multiples of this are fetched |
| low/high tolerance | `500` | points below the window's low and above its high; strikes in `[low - tol, high + tol]` are fetched |

The window (20 days before expiry) is fixed unless the user says otherwise (`--window`).

### Then run these in order. Do not skip ahead.

**Step 1: fetch the instrument (index) candles.** Start 20 days before `from` so the first
expiry's window is covered:
```
.venv/Scripts/python fetch_candles.py candles NIFTY --from <from - 20 days> --to <to>
```

**Step 2: fetch the expiry list.**
```
.venv/Scripts/python fetch_candles.py expiries NIFTY --from <from> --to <to>
```
Show the user the expiries (count, and any that are not on the usual weekday because of holidays).

**Step 3: calculate each 3-week window and the CE/PE list.** Run the [plan script](#plan-script)
with a heredoc. It writes `candle_datas/<INSTRUMENT>_option_plan.json`. It makes one contract-list
call per new expiry (then cached), and with `--probe` one real option fetch to confirm access and
batch size:
```
.venv/Scripts/python - NIFTY <from> <to> <strike interval> <tolerance> --probe <<'EOF'
...plan script...
EOF
```

**Step 4: present the report.** Restate the inputs (instrument, from, to, strike interval, tolerance).
From the plan script's output, give a per-expiry table (window,
low/high, strike range, CE, PE, calls), totals (contracts, calls still to make), measured latency,
the probe result, the time for each pacing option, and the disk estimate (~300 KB per liquid
contract). Recommend the 1 call/s steady pace.

**Step 5: wait for approval.** Stop and wait for the user to approve and choose the pace/order
(`--pace`, `--newest-first`). Do not fetch before that.

**Step 6: fetch all expiry data.** Run the [run script](#run-script) in the background, output to a
file, and watch it (progress every 500 calls, any `  ! `, `rate limited`, `STOPPED`, `Traceback`,
and the final `done in`):
```
.venv/Scripts/python -u - NIFTY --pace 1.0 > candle_datas/run_option_fetch.out 2>&1 <<'EOF'
...run script...
EOF
```
Report the result: calls, time, throttled, failed (from `candle_datas/<INSTRUMENT>_option_fetch_log.json`),
file counts (CE and PE), and folder size. If it stopped on an expired token, ask the user to refresh it, then
run step 6 again. Contracts already on disk are skipped.

---

## 3. Reading the data

### `candle_datas/` layout
| File | Content |
|---|---|
| `NIFTY_candles.json` | the index, 1-minute |
| `NIFTY_<CE\|PE>_<strike>_<expiry>_candles.json` | one option contract, 1-minute, e.g. `NIFTY_CE_25000_2026-01-27_candles.json` |
| `NIFTY_expiry.json` | `{instrument, instrument_key, from, to, expiries: ["2026-01-06", ...]}` |
| `NIFTY_contracts.json` | `{expiry: [{instrument_key, trading_symbol, strike, type, lot_size, expired}, ...]}` (past expiries only) |
| `NIFTY_option_plan.json` | the plan from step 3: per-expiry summary + one job per contract |
| `NIFTY_option_fetch_log.json`, `run_option_fetch.out` | result and console output of the last step-6 run |

Other intervals get a suffix before `_candles`: `NIFTY_5m_candles.json`.

Each candle file:
```json
{"instrument": "NIFTY", "option": "CE_25000_2026-01-27",       // option is null for the index
 "instrument_key": "NSE_FO|...|27-01-2026", "trading_symbol": "NIFTY 25000 CE 27 JAN 26",
 "interval": "1m",
 "fetched": [["2026-01-07", "2026-01-27"]],                    // date ranges already asked for
 "candles": [["2026-01-07T09:15:00+05:30", o, h, l, c, volume, oi], ...]}   // oldest first
```
`fetched` covers holidays and no-trade days too, so a range with no candles is not re-requested.

### `fetch_candles.py`
```python
from datetime import date
from fetch_candles import fetch, fetch_broker, fetch_expiries, load_expiries

nifty = fetch("NIFTY", None, date(2026, 1, 7), date(2026, 1, 27))   # from disk, no API
ce    = fetch("NIFTY", "CE_25000_2026-01-27")                        # whole file
pe    = fetch("NIFTY", ("PE", 25000, date(2026, 1, 27)), date(2026, 1, 20), date(2026, 1, 27))
# -> [{"timestamp", "open", "high", "low", "close", "volume", "oi"}, ...]

exps = load_expiries("NIFTY")                                        # [date, ...] from NIFTY_expiry.json

rows = await fetch_broker("NIFTY", "CE_25000_2026-01-27", date(2026, 1, 7), date(2026, 1, 27))
# from Upstox in API-sized batches, merged into candle_datas/, only the missing ranges
```
- `fetch(instrument, ce_pe_strikeprice_expiry=None, frm=None, to=None, interval="1m")`: reads disk;
  warns if part of `[frm, to]` was never fetched; raises `FileNotFoundError` if the file does not exist.
- `fetch_broker(...)`: same arguments plus `up=` (reuse one `Upstox` client), `force=True` (re-fetch),
  `quiet=True`. `to` is cut to yesterday and, for an option, to its expiry.
- `ce_pe_strikeprice_expiry`: `None` for the index, `"CE_25000_2026-01-27"`, or `("CE", 25000, date)`.
- `MAX_RANGE` sets how much one request may cover (`"month"` or a number of days).

CLI:
```
python fetch_candles.py candles  NIFTY --from 2026-01-01 --to 2026-07-31 [--interval 5m] [--force]
python fetch_candles.py candles  NIFTY --opt CE_25000_2026-01-27 --from 2026-01-07 --to 2026-01-27
python fetch_candles.py expiries NIFTY --from 2026-01-01 --to 2026-07-31
```

---

## 4. Scripts

Both import `fetch_candles` / `upstox_funcs`, so run them from `analysis_rajkumarn/` (a heredoc on
stdin puts the working directory on `sys.path`).

### Plan script
`args: INSTRUMENT FROM TO STRIKE_INTERVAL TOLERANCE [--window 20] [--probe]`

```python
"""Plan the option-candle fetch: which contracts, how many API calls, how long."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from collections import deque
from datetime import date, timedelta

from fetch_candles import (DATA_DIR, MAX_RANGE, _load, batches, candle_file, contracts, fetch, fetch_broker,
                           gaps, load_expiries, option_name)
from upstox_funcs import Upstox

PUBLISHED = ((1.0, 50), (60.0, 500), (1800.0, 2000))        # upstox rate-limiting page
SAFETY = ((1.0, 45), (60.0, 450), (1800.0, 1800))           # what the run script uses


def simulate(n: int, latency: float, limits, min_interval: float = 0.0) -> float:
    """Seconds for n sequential calls of `latency` each, never exceeding any (window, cap)."""
    sent: deque[float] = deque()
    t = 0.0
    longest = max(w for w, _ in limits)
    for _ in range(n):
        while sent and t - sent[0] > longest:
            sent.popleft()
        start = t
        for win, cap in limits:
            inwin = [s for s in sent if start - s < win]
            if len(inwin) >= cap:
                start = max(start, inwin[-cap] + win)
        sent.append(start)
        t = start + max(latency, min_interval)
    return t


def fmt(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("instrument")
    ap.add_argument("frm")
    ap.add_argument("to")
    ap.add_argument("step", type=float, help="strike interval, e.g. 50 for NIFTY")
    ap.add_argument("--window", type=int, default=20, help="days before expiry")
    ap.add_argument("tolerance", type=float, help="points below the window low / above its high, e.g. 500")
    ap.add_argument("--probe", action="store_true", help="fetch one real contract to check access")
    a = ap.parse_args()
    inst, frm, to = a.instrument.upper(), date.fromisoformat(a.frm), date.fromisoformat(a.to)

    expiries = [e for e in load_expiries(inst) if frm <= e <= to]
    if not expiries:
        raise SystemExit(f"no {inst} expiries in {frm}..{to} - run step 2 first")
    jobs, per_expiry = [], []
    async with Upstox() as up:
        first = min(expiries) - timedelta(days=a.window)
        idx = _load(candle_file(inst))
        if idx is None or gaps(first, max(expiries), idx["fetched"]):
            print(f"index: filling gaps in {first}..{max(expiries)}")
            await fetch_broker(inst, None, first, max(expiries), up=up)

        for e in expiries:
            w0 = e - timedelta(days=a.window)
            cs = fetch(inst, None, w0, e)
            if not cs:
                print(f"  ! {e}: no index candles in {w0}..{e}, skipped")
                continue
            hi, lo = max(c["high"] for c in cs), min(c["low"] for c in cs)
            chain = await contracts(up, inst, e)
            pick = [c for c in chain if lo - a.tolerance <= c["strike"] <= hi + a.tolerance and c["strike"] % a.step == 0]
            calls = 0
            for c in sorted(pick, key=lambda c: (c["strike"], c["type"])):
                opt = option_name(c["type"], c["strike"], e)
                blob = _load(candle_file(inst, opt))
                todo = gaps(w0, e, blob["fetched"]) if blob else [(w0, e)]
                k = sum(len(batches(ga, gb, MAX_RANGE["expired"])) for ga, gb in todo)
                calls += k
                jobs.append({"expiry": e.isoformat(), "option": opt, "from": w0.isoformat(),
                             "to": e.isoformat(), "calls": k})
            strikes = sorted({c["strike"] for c in pick})
            per_expiry.append({"expiry": e.isoformat(), "from": w0.isoformat(),
                               "sessions": len({c["timestamp"][:10] for c in cs}), "low": lo, "high": hi,
                               "strike_lo": strikes[0] if strikes else None,
                               "strike_hi": strikes[-1] if strikes else None,
                               "ce": sum(c["type"] == "CE" for c in pick),
                               "pe": sum(c["type"] == "PE" for c in pick), "calls": calls})

        probe = None
        if a.probe and any(j["calls"] for j in jobs):
            j = next(j for j in jobs if j["calls"])
            n0, t0 = up.calls, time.perf_counter()
            rows = await fetch_broker(inst, j["option"], date.fromisoformat(j["from"]),
                                      date.fromisoformat(j["to"]), up=up, quiet=True)
            probe = {"option": j["option"], "calls": up.calls - n0, "seconds": time.perf_counter() - t0,
                     "candles": len(rows), "sessions": len({r["timestamp"][:10] for r in rows}),
                     "bytes": os.path.getsize(candle_file(inst, j["option"]))}
            j["calls"] = 0
            next(r for r in per_expiry if r["expiry"] == j["expiry"])["calls"] -= probe["calls"]
        lat = statistics.mean(up.latencies) if up.latencies else 0.2
        api_calls = up.calls

    with open(os.path.join(DATA_DIR, f"{inst}_option_plan.json"), "w", encoding="utf-8") as f:
        json.dump({"instrument": inst, "from": frm.isoformat(), "to": to.isoformat(), "step": a.step,
                   "window_days": a.window, "tolerance": a.tolerance, "expiries": per_expiry, "jobs": jobs}, f, indent=1)

    print(f"\n{'expiry':<11} {'window from':<11} {'sess':>4} {'low':>9} {'high':>9} {'strikes':>13} "
          f"{'CE':>4} {'PE':>4} {'calls':>5}")
    for r in per_expiry:
        rng = f"{r['strike_lo']:g}-{r['strike_hi']:g}" if r["strike_lo"] is not None else "-"
        print(f"{r['expiry']:<11} {r['from']:<11} {r['sessions']:>4} {r['low']:>9.2f} {r['high']:>9.2f} "
              f"{rng:>13} {r['ce']:>4} {r['pe']:>4} {r['calls']:>5}")
    n_calls = sum(j["calls"] for j in jobs)
    print(f"\ncontracts: {len(jobs)} ({sum(r['ce'] for r in per_expiry)} CE + {sum(r['pe'] for r in per_expiry)} PE)"
          f" over {len(per_expiry)} expiries, strike interval {a.step:g}, tolerance {a.tolerance:g}")
    print(f"candle calls still to make: {n_calls}  ({len(jobs) - sum(1 for j in jobs if j['calls'])} contracts already on disk)")
    print(f"api calls made by this planner: {api_calls}, avg latency {lat * 1000:.0f} ms")
    if probe:
        print(f"probe {probe['option']}: {probe['calls']} call(s), {probe['seconds']:.2f}s, "
              f"{probe['candles']} candles over {probe['sessions']} sessions, {probe['bytes'] / 1024:.0f} KB")
    print("\ntime estimates:")
    for name, lim, gap in [("A published limits, burst", PUBLISHED, 0.0),
                           ("B 90% of published, burst", SAFETY, 0.0),
                           ("C steady 1 call/s (recommended)", SAFETY, 1.0),
                           ("D upstox_funcs defaults", Upstox.RATE_LIMITS, 0.25)]:
        print(f"  {name:<34} {fmt(simulate(n_calls, lat, lim, gap))}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Run script
`args: INSTRUMENT [--pace 1.0] [--newest-first]`. Reads `candle_datas/<INSTRUMENT>_option_plan.json`.

```python
"""Fetch every contract in the plan at a steady pace.  Resumable: contracts on disk are skipped."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import date, datetime

from fetch_candles import DATA_DIR, MAX_RANGE, _load, batches, candle_file, fetch_broker, gaps
from upstox_funcs import IST, Upstox

SAFETY_LIMITS = ((1.0, 45), (60.0, 450), (1800.0, 1800))    # 90% of the published caps
PROGRESS_EVERY = 50


def fmt(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def remaining_calls(inst: str, job: dict) -> int:
    blob = _load(candle_file(inst, job["option"]))
    frm, to = date.fromisoformat(job["from"]), date.fromisoformat(job["to"])
    todo = gaps(frm, to, blob["fetched"]) if blob else [(frm, to)]
    return sum(len(batches(a, b, MAX_RANGE["expired"])) for a, b in todo)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("instrument")
    ap.add_argument("--pace", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--newest-first", action="store_true")
    a = ap.parse_args()
    inst = a.instrument.upper()

    with open(os.path.join(DATA_DIR, f"{inst}_option_plan.json"), encoding="utf-8") as f:
        plan = json.load(f)
    jobs = sorted(plan["jobs"], key=lambda j: (j["expiry"], j["option"]), reverse=a.newest_first)
    todo = [(j, n) for j in jobs if (n := remaining_calls(inst, j))]
    total = sum(n for _, n in todo)
    print(f"{len(jobs)} contracts in the plan, {len(jobs) - len(todo)} already on disk, "
          f"{len(todo)} to fetch = {total} calls at {a.pace:g}s -> about {fmt(total * a.pace)}", flush=True)
    if not todo:
        return

    failed: list[dict] = []
    empty = 0
    t0 = time.perf_counter()
    up = Upstox(min_interval=a.pace)
    up.RATE_LIMITS = SAFETY_LIMITS
    async with up:
        for i, (j, _) in enumerate(todo, 1):
            try:
                rows = await fetch_broker(inst, j["option"], date.fromisoformat(j["from"]),
                                          date.fromisoformat(j["to"]), up=up, quiet=True)
                empty += not rows
            except PermissionError as exc:                  # token expired: nothing else will work
                print(f"\nSTOPPED at {j['option']}: {exc}", flush=True)
                break
            except (RuntimeError, LookupError) as exc:
                failed.append({"option": j["option"], "error": str(exc)[:300]})
                print(f"  ! {j['option']}: {str(exc)[:160]}", flush=True)
            if i % PROGRESS_EVERY == 0 or i == len(todo):
                el = time.perf_counter() - t0
                print(f"{datetime.now(IST):%H:%M:%S}  {i}/{len(todo)}  expiry {j['expiry']}  "
                      f"calls {up.calls}  throttled {up.throttled}  failed {len(failed)}  "
                      f"elapsed {fmt(el)}  eta {fmt(el / i * (len(todo) - i))}", flush=True)

    log = os.path.join(DATA_DIR, f"{inst}_option_fetch_log.json")
    with open(log, "w", encoding="utf-8") as f:
        json.dump({"finished": datetime.now(IST).isoformat(timespec="seconds"), "calls": up.calls,
                   "throttled": up.throttled, "empty_contracts": empty, "failed": failed}, f, indent=1)
    left = sum(remaining_calls(inst, j) for j in jobs)
    print(f"\ndone in {fmt(time.perf_counter() - t0)}: {up.calls} calls, {up.throttled} throttled, "
          f"{empty} contracts with no trades, {len(failed)} failed -> {log}")
    print("complete" if left == 0 else f"{left} calls still outstanding - run again to resume")


if __name__ == "__main__":
    asyncio.run(main())
```
