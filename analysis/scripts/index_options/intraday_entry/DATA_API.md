# Cheat sheet: research harness on D:/YUKTRIX/option_analysis local data

Sources read in full: `D:/YUKTRIX/option_analysis/analysis/templates/py_funcs.py` (2,833 lines), `D:/YUKTRIX/option_analysis/analysis/templates/RUN.md` (620 lines), `D:/YUKTRIX/option_analysis/analysis/scripts/index_options/orr_v1.py`, `D:/YUKTRIX/option_analysis/analysis/scripts/index_options/stretch_fade_v1.py`. Line refs are to `py_funcs.py` unless stated. Section 3 numbers were measured with read-only snippets; no file in the repo was modified.

Python is `D:/YUKTRIX/option_analysis/analysis/.venv/Scripts/python.exe` (3.13.13, 8 cores). numpy 2.2.1 and httpx are installed; pandas, scipy, sklearn, statsmodels, orjson, matplotlib are not.

## 1. API

### Import
```python
import sys; sys.path.insert(0, r"D:/YUKTRIX/option_analysis/analysis/templates")
from py_funcs import *            # underscore names (_ACTIVE, _admits, _option_file) need an explicit import
```
Importing does no network I/O. `ALLOW_FETCH` (L101) is False unless env `PYFUNCS_ALLOW_FETCH=1`; leave it unset.

### Raw files (`LOCAL_DATA_DIR` = `D:/YUKTRIX/option_analysis/analysis/candle_datas`, L96)
- **Index candles** `NIFTY_candles.json`, `SENSEX_candles.json`, `VIX_candles.json`: `{"instrument","option":null,"instrument_key","trading_symbol","interval":"1m","fetched":[[from,to]],"candles":[[ts,o,h,l,c,0,0],...]}`. `ts` is `"2026-01-01T09:15:00+05:30"`; volume and OI are always 0.
- **Option candles** `<NAME>_<CE|PE>_<strike:g>_<expiry>_candles.json` (e.g. `NIFTY_CE_25000_2026-02-03_candles.json`): same keys, `"option":"CE_25000_2026-02-03"`, rows `[ts,o,h,l,c,volume,oi]`. Volume is in units, always a multiple of the lot.
- **Expiries** `<NAME>_expiry.json`: `{"instrument","instrument_key","from","to","expiries":[...]}`.
- **Contracts** `<NAME>_contracts.json`: `{expiry: [{"instrument_key","trading_symbol","strike","type","lot_size","expired"}]}`.
- **Yahoo dailies** `yahoo_<N225|HSI|KS11|000001_SS|AXJO|GSPC|INDIAVIX>_daily.json`: `{ticker,name,source,fetched_utc,timezone,fetched,candles:[[day,o,h,l,c]]}`. Read with `await yahoo_daily("^N225", frm, to)` (L1224), which returns `[[day,o,h,l,c]]` in the exchange's own calendar day.

### Client: `class Upstox` (L404), `async with Upstox() as up:`
All data methods are `async` but purely local. `__aexit__` (L438) prints a `NOT ON LOCAL DISK` block if anything was noted missing.

- **`await up.find_instrument(query, segment=None, exchange="NSE") -> dict`** (L545). Returns `{"instrument_key","trading_symbol","name","segment","instrument_type","lot_size":None,"exchange"}`. Keys on disk: `NSE_INDEX|Nifty 50` (NIFTY), `BSE_INDEX|SENSEX`, `NSE_INDEX|India VIX` (query `"VIX"`). Not on disk raises `LookupError`. House style is `find_instrument(instrument())`.
- **`instrument() -> str`** (L355) is the active index, from `_ACTIVE["instrument"]` (L346, default `"NIFTY"`). Only `run_instruments` changes it; a standalone harness must set `py_funcs._ACTIVE["instrument"] = "SENSEX"` itself.
- **`await up.minute_sessions(key, frm: date, to: date, volume=False) -> {day: [[HH:MM,o,h,l,c]]}`** (L714). `volume=True` adds a sixth column (0 for an index). Days with no candles are simply absent. `to` is clamped to yesterday. Measured: 0.13 s first call, 0.06 s after.
- **`await up.candles(key, interval, frm, to) -> [{"timestamp","open","high","low","close","volume","oi"}]`** (L690). `"5m"`, `"15m"`, `"1h"`, `"1d"` are built from the 1-minute file (`_aggregate`, L217). A built daily close is the average of (h+l+c)/3 over 15:00–15:29, not the 15:29 close. `sessions_from(candles)` (L785) converts to the `{day: rows}` shape.
- **`await up.expiry_calendar(key, frm, to) -> list[date]`** (L589). Expiries from `frm`−7d to `to`+30d, sorted; `[]` if the file is missing.
- **`next_expiry(expiries, day: date, min_days_after=0) -> date | None`** (L826). The house rule is `next_expiry(cal, day, 1)`, which never returns today's expiry.
- **`await up.option_chain_info(key) -> {"expiries","strike_step","lot_size","strikes","contracts"}`** (L568). Describes the latest expiry on disk only.
- **`strike_step(name=None) -> float`** (L389): 50.0 NIFTY, 100.0 SENSEX. `LookupError` if there is no contract list.
- **`price_scale(name=None) -> float`** (L365): 1.0 for NIFTY, 3.2215 for SENSEX (median close ratio over the whole window).
- **`atm_strike(spot, step) -> float`** (L810) = `float(round(spot/step)*step)`.
- **`strike_offset(spot, step, steps, option_type, itm=True) -> float`** (L814). ATM moved `steps` NIFTY strikes: CE in the money is below spot, PE above. On SENSEX `n = round(steps*50*price_scale()/step)`, so depths 0..6 become 0, 2, 3, 5, 6, 8, 10 SENSEX strikes. It reads the active instrument.
- **`await up.resolve_option(key, expiry: date, strike: float, option_type) -> dict | None`** (L602). Returns `{"trading_symbol","instrument_key","expired","lot_size","expiry":"YYYY-MM-DD","strike","option_type","underlying"}`, e.g. `'NIFTY 25000 CE 03 FEB 26'`. An unlisted strike returns None silently; an unknown expiry returns None and notes a missing fetch. If `_ACTIVE["rung"]` is non-zero it shifts the strike (see section 4).
- **`await up.option_candles(contract, day: date, interval_minutes=1, volume=False) -> [[HH:MM,o,h,l,c(,volume)]]`** (L725). Returns `[]` in three cases:
  - no file (noted missing);
  - the day is outside the file's `fetched` ranges (noted missing);
  - the day is inside the ranges but has no candles (not noted).
  
  OI is dropped. It is backed by `_option_file` (L187), an `lru_cache(maxsize=32)` of whole parsed files.
- **`bar_at(rows, hhmm, tolerance=3, direction=-1) -> row | None`** (L835). Falls back to a bar up to 3 minutes earlier by default.
- **`bar_after_candle(rows_1m, candle_start, tf, strict=True) -> row | None`** (L1301). Returns the 1-minute bar stamped `candle_start + tf` minutes; None if that exact minute is missing. A 1m signal candle `"11:00"` gives the `"11:01"` bar; a 5m candle `"09:15"` gives `"09:20"`.
- **`candle_done_at(candle_start, tf) -> "HH:MM"`** (L1295); **`resample(rows, minutes, start="09:15")`** (L794); **`hhmm_minutes(t)`** (L831).
- **`worst_fills(side, entry_bar, exit_bar) -> (entry_px, exit_px)`** (L1316). LONG gives `(entry_bar[2], exit_bar[3])`; SHORT gives `(entry_bar[3], exit_bar[2])`.
- **`scan_exit(bars, side, entry_key, stop=None, target=None, force_key=None) -> {"bar","reason","trigger"}`** (L1362).
  - Scans bars with `key > entry_key`.
  - A bar equal to `force_key` returns `{"bar": that bar, "reason": "time exit"}`; this is checked before stop/target.
  - A stop or target touched in a bar returns the next bar of the same list as the fill bar; stop wins a tie. `bar` is None if the next bar is missing or later than `force_key`.
  - No exit returns `{"bar": None, "reason": "no exit found"}`.
  - It does not look at volume. If you scan index bars, look up the option bar at `sc["bar"][0]` yourself (orr_v1 L168–174).
- **`excursion(rows, side, entry_px, t0, t1) -> (mfe, mae)`** (L859).
- **Indicators** (L1394–1463): `sma`, `ema`, `rsi`, `atr(rows, n)`, `crossed_above/below(a, b, i)`, `bucket(x, edges, labels)`.

### Costs (L938–1007)
```
option_costs(buy_turnover, sell_turnover, orders=2, day=None, exchange=None, sell_day=None) -> dict   # L981
option_round_trip(side, entry_px, exit_px, qty, day=None, exchange=None, exit_day=None) -> float      # L1000
trade_costs(category, side, entry_px, exit_px, qty, day=None, exit_day=None) -> float                 # L1079
exchange_of(symbol=None) -> "BSE" | "NSE"                                                             # L360
```
`exchange_of` returns BSE when the first word of the symbol is SENSEX/BANKEX/SENSEX50; with no symbol it uses the active index.

Formula for a bought option, with B = entry_px×qty and S = exit_px×qty:
```
brokerage = 30 × 2 = 60
stt       = rate × S         rate = 0.001 if sale day < 2026-04-01, else 0.0015 (OPT_STT_SCHEDULE, L954)
exchange  = NSE: (0.0003503 + 0.000005) × (B+S) = 0.0003553 × (B+S)      BSE: 0.00005 × (B+S)
sebi      = NSE: 0.000001 × (B+S)                                        BSE: 0
stamp     = 0.00003 × B
gst       = 0.18 × (brokerage + exchange + sebi)
total     = round(sum, 2)
```
Checked examples:

| Trade | Sale before 2026-04-01 | Sale from 2026-04-01 | Flat round trip per unit |
|---|---|---|---|
| NIFTY, 65 × (200 → 220) | Rs 96.97 | Rs 104.12 | about 1.5 premium points |
| SENSEX, 20 × (600 → 660) | Rs 85.85 | Rs 92.45 | about 4.2–4.5 points |

### `make_trade` (L1487), keyword-only
```
make_trade(*, day, side, symbol, entry_time, entry_px, exit_time, exit_px, qty,
           exit_day=None, exit_reason="", kind="option", costs=None, capital=None,
           entry_spot=None, exit_spot=None, stop=None, target=None, mfe=None, mae=None,
           variant=None, tags=None, levels=None, note="", option_type=None, expiry=None) -> dict
```
- Required: `day`, `side` ("LONG" for any bought option), `symbol` (`contract["trading_symbol"]`), `entry_time`, `entry_px`, `exit_time`, `exit_px`, `qty` (`lots * contract["lot_size"]`).
- For `kind="option"`, `expiry=contract["expiry"]` is also required, else `ValueError`.
- With `costs=None` it computes `option_round_trip(side, entry_px, exit_px, qty, day=day, exchange=exchange_of(symbol), exit_day=exit_day)`.
- `net = round(gross - costs, 2)`. Pass `capital=entry_px*qty`. `variant` and `tags` values are stringified.

### Settings, log, report
- **`setting(key, label, *, kind="other", mode="sweep", values=None, options=None, default=None, unit="", help="", rerun=False)`** (L1599). `kind` is one of entry/exit/strike/sizing/other. Pass exactly one of `values` or `options`. A filter needs at least one option with `tag={tag_key: [allowed]}` or `var=`. The default must be one of the values.
- `SETTINGS` is a module-level list of these. Helpers: `combos(SETTINGS)` (L1661, raises above `MAX_COMBOS` = 400), `default_combo` (L1680), `settings_cli(ap, SETTINGS)` (L1690, adds `--<key>` with dest `set_<key>`), `narrow(SETTINGS, args)` (L1700).
- **`session_row(day, status, note="", **facts)`** (L1801). Status must be one of `("traded","declined","no signal","no data")`.
- **`coverage(sessions, frm, to, rows_per_session=None) -> {"sessions","weekday_gaps","short_sessions"}`** (L915).
- **`check_window(frm, to)`** (L896): `SystemExit` if outside `START_DATE = date(2026,1,1)` .. `END_DATE = date(2026,7,31)` (L877–878).
- **`build_payload(meta, trades, index_sessions, option_sessions=None, groups=None, settings=None, chart="default", sessions_log=None, worst_only=False, index_by=None) -> dict`** (L2230).
  - `index_sessions` is `{day: rows}`; `option_sessions` is `{trading_symbol: {day: rows}}`; `groups` is `[{"name","keys":[tag names]}]`.
  - meta keys: `title, subtitle, instrument, category, from, to, lot_size, fill_rule, params, rule_steps, limits, rejected, coverage, break_date`.
- **`write_report(payload, name, template=SAMPLE_HTML) -> path`** (L2497). A bare slug writes `analysis/report/<category>/<slug>.html`; a name with a directory part writes to exactly that path.
- **`console_summary(trades) -> str`** (L2542).
- **`run_instruments(script, instruments=("NIFTY","SENSEX"), ladder=(6,5,4,3,2,1,0)) -> path`** (L2703).
  - Re-executes the script file with `run_name="__instrument__"` once per index and rung (14 runs by default) and writes one combined report.
  - CLI narrowing: `--instruments NIFTY`, `--rungs 0` or `--moneyness 6,0`.
  - It decides "own ladder" by the literal source text `setting("moneyness"`. If present, it also runs the file once with `run_name="__settings__"` to read `SETTINGS`, then passes `--moneyness N` per run.
  - If absent, it sets `_ACTIVE["rung"]=N` and `resolve_option` shifts the strike.
  - Non-rule rungs keep only trades whose sweep variants equal the rule's defaults, and their session log is dropped.

## 2. Minimal `index_options` script

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *
import argparse
CATEGORY = "index_options"; SLUG = "my_slug"; STEP = strike_step(); LOTS = 1
SETTINGS = [setting("moneyness", "Strike depth", kind="strike", default=0,
                    options=[{"value": v, "label": rung_label(v), "raw": v} for v in STRIKE_LADDER]),
            setting(... kind="entry", mode="filter", options=[{"value":"any","tag":None}, {"value":"x","tag":{"tagkey":["v"]}}])]

async def run(frm, to, settings):
    trades, log, option_sessions = [], [], {}
    async with Upstox() as up:
        key = (await up.find_instrument(instrument()))["instrument_key"]
        sessions = await up.minute_sessions(key, frm, to)
        cal = await up.expiry_calendar(key, frm, to)
        for d, rows in sorted(sessions.items()):
            if len(rows) != 375: log.append(session_row(d, "no data", "short session")); continue
            # signal on completed candles -> opt_type, spot, signal minute sig
            exp = next_expiry(cal, date.fromisoformat(d), 1)
            strike = strike_offset(spot, STEP, depth, opt_type)
            c = await up.resolve_option(key, exp, strike, opt_type)            # None -> "no data"
            orows = await up.option_candles(c, date.fromisoformat(d), volume=True)
            eb = bar_after_candle(orows, sig, 1)                               # None or eb[5]==0 -> "no data"
            xb = ...                                                           # scan_exit(...) or the 15:14 bar
            ep, xp = worst_fills("LONG", eb, xb); qty = LOTS * c["lot_size"]
            trades.append(make_trade(day=d, side="LONG", symbol=c["trading_symbol"], entry_time=eb[0], entry_px=ep,
                exit_time=xb[0], exit_px=xp, qty=qty, exit_reason="time exit 15:14", capital=ep*qty,
                expiry=c["expiry"], option_type=opt_type, variant={"moneyness": depth}, tags={"direction": ...}))
            option_sessions.setdefault(c["trading_symbol"], {})[d] = orows
            log.append(session_row(d, "traded", "..."))                         # exactly one row per day
    return trades, log, sessions, option_sessions

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat()); ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS); a = ap.parse_args(); settings = narrow(SETTINGS, a)
    frm, to = date.fromisoformat(a.frm), date.fromisoformat(a.to); check_window(frm, to)
    trades, log, sessions, osess = asyncio.run(run(frm, to, settings))
    meta = {"title": "...", "subtitle": "...", "instrument": "NIFTY 50 weekly options", "category": CATEGORY,
            "from": a.frm, "to": a.to, "lot_size": ..., "fill_rule": "...", "params": {...}, "rule_steps": [...],
            "limits": [...], "rejected": [...], "coverage": coverage(sessions, frm, to, 375)}
    groups = [{"name": "Direction", "keys": ["direction"]}] if trades else []
    payload = build_payload(meta, trades, sessions, osess, groups, settings=settings, chart="default",
                            sessions_log=log, worst_only=True)
    print(console_summary(trades)); print(write_report(payload, SLUG))

if __name__ == "__main__":
    run_instruments(__file__)
elif __name__ == "__instrument__":
    main()
```

What `build_payload` and `validate_payload` (L2448) refuse, all as `ValueError`:
- **Groups:** a group key that no trade carries as a tag. This also fires with zero trades, hence `if trades else []`.
- **Chart:** `chart` not `"default"` or `"all"`.
- **Category:** no `meta["category"]` and the script is not under `analysis/scripts/<category>/`; or the category disagrees with the script's folder.
- **Worst fill:** with `worst_only=True`, any trade whose embedded candles show a fill other than entry-bar HIGH / exit-bar LOW (tolerance 0.006).
- **Trade fields:** a trade missing any of `day, exit_day, side, symbol, entry_time, entry_px, exit_time, exit_px, qty, gross, costs, net`; or `|gross − costs − net| > 0.05`.
- **Index candles:** a trade day or exit day with no index candles in `index_sessions`.
- **Session log, when given:** a trade day absent from the log; a row logged `traded` with no trade; a day appearing twice.

Other behaviour to know:
- `setting()` raises on a bad kind, mode or default, duplicate values, or a filter with no tag.
- `check_settings` (L1754) only prints `WARNING` lines (sweep value with no trade, filter option admitting nothing).
- With `settings=None` a panel is derived and a warning printed.
- The second "signal candle" view (`_price_fills`, L2023) needs `option_sessions[symbol][day]`. An exit keeps its own minute only if `exit_reason` matches `time exit|fixed exit|next-morning|square[- ]?off|expiry|end of day` (L2008).

## 3. Measured data facts

### Sessions
- NIFTY, SENSEX and VIX each have 175 sessions on disk, 2025-11-24 .. 2026-08-07, 65,625 rows. Every session is exactly 375 bars, 09:15–15:29, sorted, with no duplicates and no invalid OHLC.
- In the window 2026-01-01..2026-07-31 there are 143 sessions for each, all complete. None is short or missing.
- 27 warm-up sessions precede the window (2025-11-24..2025-12-31).
- Weekday holidays in the window (10): 01-15 Thu, 01-26 Mon, 03-03 Tue, 03-26 Thu, 03-31 Tue, 04-03 Fri, 04-14 Tue, 05-01 Fri, 05-28 Thu, 06-26 Fri.
- One weekend session: Sunday 2026-02-01, 375 bars on both indices, NIFTY range 24,571–25,441. Option files cover it (330 NIFTY and 311 SENSEX files have candles that day).

### Expiries
- **NIFTY:** 31 expiries, 2026-01-06..2026-08-04. Tuesday, except Monday 03-02, 03-30 and 04-13 (holiday shifts).
- **SENSEX:** 32 expiries, 2026-01-01..2026-08-06. Thursday, except Wednesday 01-14, 03-25 and 05-27.
- Every expiry has a contract list.
- Sessions that are an expiry day: NIFTY 30, SENSEX 31.

Calendar days to expiry from `next_expiry(cal, day, 1)`, as sessions per DTE:

| DTE | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| NIFTY | 26 | 1 | 3 | 27 | 29 | 30 | 24 | 3 |
| SENSEX | 30 | 27 | 26 | 1 | 3 | 28 | 25 | 3 |

### Lot sizes and strikes
- Lot size is constant over the window: NIFTY 65 and SENSEX 20 for every contract of every expiry.
- NIFTY step is 50; expiries 03-30 and 06-30 also list far strikes at 500/1000 gaps. SENSEX step is 100; 06-25 has a few 700/1000 gaps.

### Option files
- 7,501 files, 1.78 GB, 27.4M rows: NIFTY 2,854 files (866 MB), SENSEX 4,647 files (913 MB).
- All are sorted, with no duplicate timestamps, no invalid OHLC, rows of length 7, and a `:00+05:30` suffix.
- Zero-volume bars: NIFTY 3.79M of 13.28M (28.5%), SENSEX 5.90M of 14.08M (41.9%). Every one has o = h = l = c.
- OI is 0 on 36k NIFTY bars and 130k SENSEX bars.
- 172 SENSEX files have an empty `candles` list.
- A file holds candles for 1–16 sessions (median 11); candles start at the contract's first print, not at `fetched[0]`.
- 22 files have two `fetched` ranges.
- 260 bars fall outside 09:15–15:29, all on 2026-08-03 (outside the window).

### Availability at the entry minute and at 15:14
Method: spot is the index close of minute T−1, the strike comes from `strike_offset`, and the expiry from `next_expiry(cal, day, 1)`. Counts are out of 143 sessions.
- **volT**: bar at T with volume > 0.
- **vol1514**: bar at 15:14 with volume > 0.
- **both**: both of those.
- **both±2**: a traded bar within T..T+2 and within 15:14..15:16.

Cells are `volT / vol1514 / both / both±2`.

NIFTY (depth in NIFTY strikes):

| T | Depth | CE | PE |
|---|---|---|---|
| 09:20 | ATM | 143/143/143/143 | 143/143/143/143 |
| 09:20 | 2 ITM | 143/143/143/143 | 142/143/142/142 |
| 09:20 | 4 ITM | 143/142/142/143 | 143/143/143/143 |
| 09:20 | 6 ITM | 142/142/141/143 | 142/140/140/142 |
| 11:00 | ATM | 143/143/143/143 | 143/143/143/143 |
| 11:00 | 2 ITM | 143/143/143/143 | 143/143/143/143 |
| 11:00 | 4 ITM | 143/143/143/143 | 143/143/143/143 |
| 11:00 | 6 ITM | 138/137/133/139 | 138/141/138/142 |
| 14:30 | ATM | 143/143/143/143 | 143/143/143/143 |
| 14:30 | 2 ITM | 143/143/143/143 | 143/143/143/143 |
| 14:30 | 4 ITM | 143/143/143/143 | 143/143/143/143 |
| 14:30 | 6 ITM | 138/142/137/142 | 141/141/140/142 |

- The NIFTY file existed for every combination except one: 07-31 14:30 6-ITM PE 24700 of expiry 08-04.
- One file's fetched range missed the day: 07-28 09:20 6-ITM PE 24350.
- The 2026-08-04 NIFTY expiry has only 42 files (strikes about 23650–24650) with per-file fetched ranges, so 07-28..07-31 are thin beyond about 4 ITM.

SENSEX (depths 2, 4, 6 are 3, 6, 10 SENSEX strikes):

| T | Depth | CE | PE |
|---|---|---|---|
| 09:20 | ATM | 142/143/142/142 | 143/142/142/143 |
| 09:20 | 2 | 142/139/139/141 | 143/139/139/143 |
| 09:20 | 4 | 136/130/125/135 | 139/130/127/139 |
| 09:20 | 6 | 116/97/84/114 | 125/109/97/128 |
| 11:00 | ATM | 143/143/143/143 | 143/143/143/143 |
| 11:00 | 2 | 137/141/135/140 | 137/141/135/141 |
| 11:00 | 4 | 125/133/122/131 | 136/131/124/137 |
| 11:00 | 6 | 85/99/66/98 | 105/95/75/122 |
| 14:30 | ATM | 142/142/142/142 | 143/143/143/143 |
| 14:30 | 2 | 141/141/140/143 | 142/142/141/142 |
| 14:30 | 4 | 131/130/127/136 | 135/138/131/142 |
| 14:30 | 6 | 93/100/78/108 | 109/106/89/126 |

- SENSEX files existed and covered the day for every combination except two on 07-31: one with no file, one outside the fetched range.

Share of a session's 375 minutes that traded, for the contract picked at 11:00:

| Index | Depth | Median | 10th percentile | Minimum |
|---|---|---|---|---|
| NIFTY | ATM | 100% | 100% | 99% |
| NIFTY | 4 ITM | 100% | 99% | 82% |
| NIFTY | 6 ITM | 100% | 89–98% | 47% |
| SENSEX | ATM | 100% | 99.7% | 86% |
| SENSEX | 2 | 100% | 86–91% | 25% |
| SENSEX | 4 | 99.5% | 54–66% | 8% |
| SENSEX | 6 | 70–82% | 13–28% | 0% |

Bars are occasionally absent altogether: a SENSEX 4-ITM CE had 79 bars in a day, and a 6-ITM CE had 0.

### Read speed
- Index file (4.5 MB): `json.load` takes 0.05–0.06 s.
- Option file (average 237 KB, about 3,650 rows): about 7 ms each, almost all of it parsing.
- All 7,501 files: 5.2 s read plus 24.9 s `json.loads`, about 30 s single-process.
- Just the files needed for ATM/2/4/6 ITM × CE/PE × three decision times × 143 days: NIFTY 1,087 files, 337 MB, 9.2 s; SENSEX 1,558 files, 353 MB, 9.7 s.
- `up.option_candles`: 80 distinct contracts in 0.53 s (6.6 ms each when uncached). The cache holds 32 files, so a loop over many strikes and days re-parses constantly.

Fastest approach:
- Build the list of needed `(name, ot, strike, expiry)` from the index sessions first, then `json.load` each file once directly.
- File name: `f"{name}_{ot}_{strike:g}_{expiry}_candles.json"`.
- Keep only the needed days as `{day: {HH:MM: row}}` (or numpy arrays), or keep your own dict cache.
- Check `fetched` yourself.
- Do not hold all 27M rows as Python lists; that would be several GB (estimated, not measured).

## 4. Gotchas that silently corrupt a harness

1. **Zero-volume bars are not fills.** They carry the last traded price with o = h = l = c, so the worst-fill rule gives no protection. `option_candles` without `volume=True` hides the column, and `bar_at`, `bar_after_candle`, `scan_exit`, `worst_fills` and `excursion` never look at it. Require `bar[5] > 0` on both the entry and exit bar. stretch_fade_v1 L170–180 waits up to 2 minutes for a traded bar, else logs no data.
2. **Missing minutes exist too.** A dict lookup returns None; never substitute a neighbour. `bar_at` defaults to `tolerance=3, direction=-1` and will hand back an earlier bar, so use `tolerance=0` for anything that is a fill.
3. **`option_candles` returns `[]` for three different reasons** (see section 1). Calls to missing contracts fill the module-global `_MISSING`, which prints a long block on exit and adds a line to `meta.limits`.
4. **Caches keyed on the index.**
   - `_price_scale` is keyed on the name, which is fine.
   - `STEP = strike_step()` at module level, `strike_offset`, `price_scale()` and `option_round_trip(exchange=None)` / `trade_costs` all read the active instrument. A harness that loops NIFTY then SENSEX in one process must set `_ACTIVE["instrument"]`, recompute `STEP`, and pass `exchange="BSE"` (or use `make_trade`, which reads the symbol). Otherwise SENSEX gets NIFTY strike depths and NSE charges.
   - Key your own caches on `(index, ot, strike, expiry, day)`.
5. **`price_scale()` is hindsight.** It is the median ratio over the whole window, used for SENSEX strike depth and point scaling. onh_v4 passes its own pre-window ratio via `meta["price_ratio"]`.
6. **Strike-ladder double shift.** Under `run_instruments`, a script whose source lacks the literal `setting("moneyness"` gets `resolve_option` shifting every strike by the rung, on top of any `strike_offset` you applied. Either declare `setting("moneyness", ...)` with all of `STRIKE_LADDER`'s values and honour `--moneyness`, or always ask for ATM. Module-level code runs 15 times or more, including once as `__settings__`; keep it side-effect free.
7. **Expiry day.** Always use `next_expiry(cal, day, 1)`. The default `min_days_after=0` returns today's expiring contract. On about 30 sessions per index the traded contract is next week's. A day before expiry (DTE 1: 26 NIFTY, 30 SENSEX sessions) behaves very differently from DTE 7; make DTE a tag, not a tuned filter. The weekday is not fixed, so read the calendar.
8. **Sunday 2026-02-01 is a real full session.** `coverage()` only lists weekday gaps. The weekday group shows "Sun", and its ISO week is the previous one. "Previous session" logic must use the sorted session list, not calendar arithmetic. Its expiry is 02-03 (DTE 2).
9. **Duplicates.** There are none on disk, but py_funcs does not dedupe, and a `{HH:MM: row}` dict would keep the last silently. orr_v1 `valid_session` (L88–98) is the house check.
10. **Time strings.** Timestamps are ISO with `+05:30`; py_funcs slices `[:10]` and `[11:16]`. Never convert to UTC. Compare `"HH:MM"` as strings. `scan_exit` keys must be the same form as `entry_key`. Yahoo daily dates are the foreign exchange's own calendar day, so decide what was known at the NSE minute; the S&P 500 close of day D is only known on D+1 IST.
11. **Daily closes** from `up.candles(key, "1d")` are synthetic (average of the last 30 minutes). Do not mix them with 15:29 closes without saying so.
12. **`atm_strike` uses banker's rounding.** 25025 gives 25000 but 25075 gives 25100.
13. **`scan_exit` with a missing `force_key` bar** never time-exits and returns `bar=None`; handle that as no data. Its force check comes before stop/target in that bar.
14. **STT step on 2026-04-01** raises costs by about 7% of a typical round trip. Any before/after split at that date mixes a cost change with a regime split.
15. **End of window.** 07-28..07-31 use expiries 08-04 (NIFTY) and 08-06 (SENSEX), which have only about 40 files with partial fetched ranges, so deeper strikes drop out there.
16. **OI is not available through py_funcs** (`_option_file` keeps volume only); read the raw file. The index has no volume, so there is no index VWAP.
17. **Writes.**
    - `write_report(payload, "slug")` writes into `D:/YUKTRIX/option_analysis/analysis/report/index_options/`.
    - Pass a full path to write elsewhere.
    - For a script outside `analysis/scripts/index_options/`, set `meta["category"]="index_options"`.
    - A pure research harness needs neither `build_payload` nor `write_report`.
18. **RUN.md is stale on one number.** It says `MAX_COMBOS` is 240; the code says 400 (L1591).
19. **No trades from a rule that `continue`s past declined days.** The house pattern is to trade every candidate, tag it, and let a filter setting select. With filters declared this way, a pooled `console_summary(trades)` is not the rule's book; filter by defaults as in stretch_fade_v1 `rule_trades` (L377).

Scratch scripts used for the measurements are in `C:\Users\Vijayan\AppData\Local\Temp\claude\d--YUKTRIX-option-analysis\8ccad862-0c78-4f1b-abdd-8ad11f90d261\scratchpad\` (`m1.py`–`m6.py`, plus `miss_NIFTY.json` and `miss_SENSEX.json`, which list every missed day per time/depth/type).