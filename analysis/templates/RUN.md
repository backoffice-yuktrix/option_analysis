# RUN.md — turn a strategy prompt into a script and a report

**Inputs (four things):**
1. The user's strategy prompt (steps, in their own words).
2. This file.
3. `analysis/templates/py_funcs.py` — Upstox fetching, option resolution, the rules below as functions, costs, indicators, trade builder, report writer. **Every number in the report is computed here.**
4. `analysis/templates/sample.html` — the one report template (open it in a browser to see a demo). It only selects and formats what Python computed.

**Output:** `analysis/scripts/<slug>.py`, which when run writes `analysis/report/<slug>.html`.

Nothing is cached: every run fetches what it needs from Upstox.

---

## Rules to Live By

These hold for every strategy, whatever the prompt says. They are enforced by functions in `py_funcs.py`; a script that bypasses them is wrong. If a prompt contradicts one, **stop and ask** — do not silently choose.

| # | Rule | Why | Enforced by |
|---|------|-----|-------------|
| 1 | **Every BUY fills at the bar's HIGH, every SELL at the bar's LOW** — entry and exit alike. A long buys at the entry bar's high and sells at the exit bar's low; a short sells at the entry bar's low and buys back at the exit bar's high. | No fill in the backtest may be better than a real one could have been. | `worst_fills(side, entry_bar, exit_bar)` |
| 2 | **A signal from a candle is acted on in the next candle.** The signal candle must be *complete*; the trade (entry or exit) happens in the **next 1-minute bar** — whatever the signal timeframe. A 1m signal → the next 1m bar. A 5m candle starting 09:15 completes at 09:20 → the 1m bar starting 09:20. | The decision cannot use a price that had not yet finished forming. | `bar_after_candle(rows_1m, candle_start, tf)` |
| 3 | **Stops and targets are signals too.** A stop/target touched inside a completed bar exits in the *next* 1-minute bar (rule 1 prices apply). If one bar touches both, the **stop is assumed first**. A scheduled time exit (e.g. 15:14) fills in that bar itself. | Same reason as rule 2; the tie-break is the conservative one. | `scan_exit(bars, side, entry_key, stop, target, force_key)` |
| 4 | **Only completed candles are read.** Indicators, levels and tags for a decision use candles up to and including the signal candle, never later ones. | Look-ahead makes every backtest look better than it is. | index `i` = signal candle in `sma/ema/rsi/atr`, `crossed_above/below` |
| 5 | **Wins are counted net of costs.** Every trade carries its brokerage, STT, exchange, SEBI, stamp and GST; a trade that only covers costs is a loss. Never guess a rate for a non-option instrument — ask. | Gross profit that costs eat is not profit. | `make_trade` (options: `option_costs`); `costs=` required otherwise |
| 6 | **Bad data means no trade, said out loud.** A missing, duplicated or invalid candle, a short session, a missing option bar, or a missing contract → skip that day/trade and list it. Never fill from a later bar, from a close, or invent a high or low. | A gap filled with a guess is a fake fill. | `bar_after_candle(strict=True)`, `coverage()`; print every skip |
| 7 | **Use complete sessions only.** A full NIFTY session is 375 one-minute bars (09:15–15:29). Today's session is not used until it is over (after 15:45). | A half-day bar is not the day's bar. | `coverage(..., rows_per_session=375)` |
| 8 | **Instrument facts come from Upstox, never from memory.** Strike step, lot size, expiries, instrument keys. Take `qty` from the *resolved contract's* `lot_size`, per trade — never a constant. (Checked live: NIFTY was 25 in Dec 2024, 75 in Nov 2025, 65 now; the contract Upstox returns for a past expiry carries the size in force then. `capital` scales with it.) | Hardcoded facts go stale silently. | `find_instrument`, `option_chain_info`, `expiry_calendar`, `resolve_option` |
| 9 | **One position at a time** unless the prompt says otherwise. | Overlapping trades double-count the same capital. | strategy loop |
| 10 | **A bought option is not held through its expiry day.** Default expiry: the nearest one at least 1 day after the exit day, unless the prompt says otherwise. | Expiry-day premiums collapse; the numbers stop being comparable. | `next_expiry(expiries, day, min_days_after)` |
| 11 | **Selection is disclosed.** If the script picks parameters by looking at the same window it reports, say in `meta.limits` that the result is in-sample. Show all compared variants (as filters), not only the winner. | The best cell of a grid is mostly noise. | `variant=` on trades |
| 12 | **Tags describe the moment they are measured.** A tag for an entry condition is computed from candles complete at the entry signal; an exit tag from candles complete at the exit signal. | Same as rule 4, for the group-by columns. | strategy code |
| 13 | **Capital is stated with its source.** Bought option: premium × qty. Sold option: a margin estimate — say it is an estimate in `meta.limits`. | Return-on-capital is meaningless without it. | `make_trade(capital=)` |
| 14 | **Times are exchange time (IST) as `HH:MM`.** | Mixed time zones corrupt every join. | `sessions_from` |
| 15 | **Nothing is cached and nothing is written outside `analysis/scripts/` and `analysis/report/`.** | Stale caches were the source of the old "wrong window" bugs. | — |

---

## Procedure

Follow in order. Do not skip step 1.

### Step 1 — Validate the prompt (mandatory)

Read the user's prompt against the checklist below. Mark each item **clear**, **assumed** (a default applies) or **gap**.

* Any **gap** → stop. Ask every gap question in **one** message (use the question tool when available), each with a recommended default so the user can answer "default". **Write no code until every gap is closed.**
* Show the checklist result as a table (item · status · what you understood), even when there are no gaps. With zero gaps, carry on.
* Record every answer and assumption; they go into the script docstring and into `meta.limits`.

#### The checklist

| # | Item | **Clear** when the prompt states… | Typical gap questions |
|---|------|-----------------------------------|-----------------------|
| 1 | **Underlying** | the instrument the signal is read from | Which index/stock? |
| 2 | **Window** | from/to dates or "last N months" | Which range? |
| 3 | **Signal timeframe** | the interval (1m/5m/15m/1d). Higher timeframes are built from 1m | Which interval? |
| 4 | **Signal rule** | exact inputs (which candle, which price), the comparison, every threshold as a **number**, and every indicator with its parameters | "strong", "near", "breakout" with no number or definition |
| 5 | **Decision time** | when the decision is taken (at the close of which candle) — rule 2 fixes the fill | At what time / on which candle? |
| 6 | **Direction mapping** | what each signal does (up → buy CE? sell PE? long index?) | Which side for each signal? |
| 7 | **Traded instrument** | index / futures / equity / option | What is traded? |
| 8 | **Option specifics** *(if option)* | buy or sell · strike rule (ATM, N steps ITM/OTM) · expiry rule · lots | Strike? Expiry? Lots? |
| 9 | **Entry** | the signal that triggers it (fill is fixed by rules 1–2) | Any entry condition beyond the signal? |
| 10 | **Exit** | every way out with numbers: target, stop, time, signal; the first minute an exit may fire; stop/target basis (premium %, points, index level) | Stop? Target? Time exit? |
| 11 | **Holding period** | intraday, or overnight (then which session's bars) | Overnight allowed? |
| 12 | **Costs** | option: the standard schedule; anything else: the rates | Costs for this instrument? |
| 13 | **Position rules** | one at a time (default)? re-entry after a stop? | Can trades overlap? |
| 14 | **Missing data** | skip and list (default) or abort | — |
| 15 | **Filters (variants to compare)** | which parameters the user wants side by side — R:R values, exit types, strikes, timeframes. Each becomes a **filter** in the report (with `side`) | Which values of which parameters? |
| 16 | **Custom group-bys** | for each: the **indicator**, its **parameters and timeframe**, the **bucket definitions**, the **candle it is measured on**, the **side-aware wording**, and whether it stands **alone** or is **combined** with others (single or multi-indicator bucket) | See below |
| 17 | **Script name** | a slug | (default: derived from the prompt) |

**Custom group-by — what a clear description looks like.** Example the user gave: *"at entry, is the instrument above/crossing its SMA10 — for a Buy (buy CE) 'crossed above' vs 'not above'; for a Sell (buy PE) 'crossed below' vs 'not below'."* To be clear it needs: which instrument's price (the index), timeframe (the signal candle's), SMA period (10) on which price (close), what "crossed" means (previous close at/below SMA, this close above) and the measuring candle (the signal candle). Ambiguous → ask. Combined groups ("SMA10 with RSI bucket") need the second indicator defined the same way, and the RSI edges (`bucket(rsi, [40, 60], ["below 40", "40-60", "above 60"])`).

**Standard group-bys (added automatically, do not ask for them):** weekday, month, entry hour, exit reason, and — when the trades are options — option type (CE / PE, read from the contract symbol or `make_trade(option_type=)`) and DTE (days to expiry at entry, from `make_trade(expiry=)`; shown as "0 DTE", "1 DTE", …). If the direction of the signal (BUY/SELL, CE/PE) matters, put it in a tag called `direction` and add a group for it — do not duplicate weekday or side (side is a filter).

**Check the prompt for itself:**
* **Contradictions** — e.g. "exit at 15:15" and "hold overnight".
* **Rules that break the Rules to Live By** — e.g. "enter at the signal candle's close", "fill at the close". Say which rule it breaks and ask.
* **Unmeasurable words** — every adjective must become a number or formula.
* **Data Upstox cannot give** — order book, IV, delta history. Say so.
* **Too many filter combinations** — filters multiply (`side` × R:R × exit × …); the limit is `MAX_VIEWS = 400` combinations. Ask the user to trim.

#### Defaults (only when the user says "use defaults" or the item is marked *assumed*)

| Item | Default |
|------|---------|
| Costs | `option_costs` for options; otherwise ask |
| Lots | 1 lot; `qty = lots × lot_size` from the resolved contract |
| Missing data | skip, list in the console and in the answer to the user |
| Positions | one at a time |
| Expiry | nearest at least 1 day after the exit day |
| Session | 09:15–15:29, 375 one-minute bars |
| Window | last 6 months, ending yesterday |
| Stop and target tie in one bar | stop first |

### Step 2 — Write down the plan

Before coding, state in a few lines: data to fetch, the loop over days, the signal, how each trade is built, the tags/filters/groups, and the output. If `py_funcs.py` lacks something (e.g. futures costs), add it there as a general function — never bury it in one strategy.

### Step 3 — Write `analysis/scripts/<slug>.py`

* Docstring = the user's prompt, then the checklist answers and assumptions.
* Start with:
  ```python
  import os, sys
  sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
  from py_funcs import *
  ```
* CLI: `--from`, `--to` (defaults from the prompt).
* **All Upstox calls go through `py_funcs.Upstox`.**
* Split the file: `fetch` (async) · `signal` (pure, completed candles only) · `simulate` (pure: bars → exit, via `bar_after_candle`, `worst_fills`, `scan_exit`) · `main`.
* Every trade is built with `make_trade`: for options pass `expiry=contract["expiry"]` (required — it drives the DTE breakdown) and `qty=lots * contract["lot_size"]`; pass `stop`/`target` prices (drawn on the chart), `levels` for anything the rule uses (zones, SMA at the signal, previous-day levels), `mfe`/`mae` from `excursion`, `variant={...}` for the filter values, `tags={...}` for the group-by conditions.
* Print every skipped day and why. There is no signal log in the report, so the skip list goes to the console and into the answer to the user.
* Finish with:
  ```python
  payload = build_payload(meta, trades, index_sessions, option_sessions, groups)
  path = write_report(payload, "<slug>")
  print(console_summary(trades)); print(path)
  ```
  where `groups = [{"name": "SMA10 cross at entry", "keys": ["sma10"]}, {"name": "SMA10 × RSI", "keys": ["sma10", "rsi"]}]` — each `keys` entry names a tag; several keys = a multi-indicator bucket.
* `meta`: `title`, `subtitle`, `instrument`, `from`, `to`, `lot_size`, `fill_rule`, `cost_model`, `params`, `rule_steps` (the rule in plain English, one string per step), `limits` (assumptions, "what this is not", the in-sample note from rule 11), `coverage` (from `coverage()`).

**What Python computes, per filter combination (a "view")** — you do not code any of this:
overview (trades, win %, net, gross, costs, profit factor, expectancy, average win/loss, payoff, best/worst, max drawdown with dates, streaks, t-stat, capital, return on capital, hold time, sessions) · equity, drawdown and rolling-20 win-rate series · standard and custom group-by tables · stability (halves, thirds, quarters with date ranges; without the best/worst 10% of trades, rounded up). Values are unrounded (6 decimals, for file size only); the browser rounds for display.

**Filters and the overview popup.** `side` plus every `variant` key become dropdowns. When the report opens, a popup (95% width) lists the overview under every filter combination side by side; clicking a row's first cell (the filter condition) applies those filters and closes the popup. The *show all* button next to the Overview heading reopens it.

### Step 4 — Run

```
analysis/.venv/Scripts/python.exe analysis/scripts/<slug>.py
```

(Windows, from the repository root.) A `PermissionError` about the token means: run `analysis/.venv/Scripts/python.exe analysis/connect_upstox.py`, log in, re-run.

### Step 5 — Verify before telling the user it is done

1. The script finished, printed the `console_summary` line and the report path. `validate_payload` passed (it runs inside `build_payload`).
2. **Rules check on three trades** (one win, one loss, one time-exit) in the report's *Cross-check* view: the signal candle is complete and earlier than the entry bar; the entry bar is the 1-minute bar right after it; entry price = that bar's high (long) / low (short); exit price = the exit bar's low (long) / high (short); a stop/target exit sits one bar after the bar that touched it.
3. **Counts add up:** sessions in the window, sessions skipped (with reasons), trades.
4. Open the HTML (headless Chrome screenshot is enough): no console errors, overview populated, filters change the numbers, chart shows the selected trade.
5. Tell the user: the report path, the headline numbers, every **assumption**, every **skipped** day with its reason, and — plainly — if the sample is small or the result is in-sample.

---

## `py_funcs.py` at a glance

| Need | Call |
|------|------|
| Token | `read_access_token()` (line 4 of `analysis/upstox_config.txt`) |
| Instrument key | `await up.find_instrument("NIFTY")`, `("RELIANCE", "NSE_EQ")` |
| Strike step, lot size, live expiries | `await up.option_chain_info(key)` |
| Expiries incl. expired | `await up.expiry_calendar(key, frm, to)` |
| Option contract (live or expired) | `await up.resolve_option(key, expiry, strike, "CE"/"PE")` |
| Index/stock candles | `await up.candles(key, "1m"/"5m"/"15m"/"1d", frm, to)` → `sessions_from(...)` |
| Option bars for a day | `await up.option_candles(contract, day)` |
| Strike maths | `atm_strike`, `strike_offset(spot, step, n, "CE", itm=True)`, `next_expiry` |
| Bars | `bar_at`, `resample(rows, minutes)` |
| **Rules** | `bar_after_candle`, `worst_fills`, `scan_exit`, `candle_done_at` |
| Indicators | `sma`, `ema`, `rsi`, `atr`, `crossed_above`, `crossed_below`, `bucket` |
| Costs | `option_costs`, `option_round_trip` |
| Trades and report | `make_trade`, `excursion`, `build_payload`, `write_report`, `console_summary`, `coverage` |

Upstox facts already handled inside: the v3 candle URL takes `to` before `from`; minute data is capped at one month per request (chunked); today's candles come from the intraday endpoint; expired option contracts carry a dated instrument key and use a different candles endpoint.

## How `sample.html` is used on each run

* `sample.html` is **never modified by a backtest**. `write_report()` reads it as text, replaces what sits between `/*DATA_START*/` and `/*DATA_END*/` with the run's data, and writes the result to `analysis/report/<name>.html`.
* Those markers are on the **last line** of the file, inside the final `<script>main(/*DATA_START*/{...}/*DATA_END*/);</script>`. Everything above it is the report code, wrapped in `function main(DATA) {...}`. **To change the report, edit the code above that last script and never touch the data line.** Keep exactly one pair of markers.
* Whatever data the template holds (empty, or the synthetic demo) is what you see when you open `sample.html` directly. To refresh the demo after editing the template, call `write_report(payload, <path of sample.html>)` with any payload.
