# RUN.md — turn a strategy prompt into a script and a report

**Inputs (four things):**
1. The user's strategy prompt (steps, in their own words).
2. This file.
3. `analysis/templates/py_funcs.py` — local data (candles, expiries, contracts from `analysis/candle_datas`), option resolution, the rules below as functions, costs, indicators, trade builder, the settings panel, report writer. **Every trade is built here**, and so is the baseline book the page checks itself against.
4. `analysis/templates/sample.html` — the one report template (open it in a browser to see a demo). It renders the control panel the script declares and recomputes the book for whatever settings and date range the reader picks.

The code here is self-contained: nothing depends on code outside `analysis/`, and nothing may be added that does. The **data** is here too, in `analysis/candle_datas` (and stocks in `analysis/stock_datas`); it is fetched with `analysis/templates/fetch_data.py`, which drives the unedited `analysis_rajkumarn/fetch_candles.py` (next section).

**Output:** `analysis/scripts/<category>/<slug>.py`, which when run writes `analysis/report/<category>/<slug>.html`.

## A new idea starts fresh — no old strategies, no memories (the user, 2026-10-02)

When the user brings a hypothesis or asks for a pattern to be found, work as a **fresh trader and data analyst**: go to the candles, mine what the data itself shows, and state the exact pattern that fits.

| | |
|---|---|
| Not read | the existing strategy scripts (`analysis/scripts/`), their reports, `STRATEGY_PROMPTS.md`, and saved memories of earlier studies - **unless the user says to, or gives permission when asked**. |
| Not carried over | an earlier strategy's conclusions, filters, exits or verdicts. A past result is not evidence for or against the new idea, and "an old study found X" is not an answer. |
| Still used | this file, `py_funcs.py` and `sample.html` (data, fills, costs, the report) and the Rules to Live By - they are how any idea is tested, not what an earlier one found. |
| The job | mine the idea itself: where and when the move the user describes really happens, under which conditions, and with which entry and exit - then give the exact rule with its numbers, and run it. Report what fits, not only that the first wording failed. |

## Data — local only, fetch only with permission (the user, 2026-09-29)

Every candle, expiry list and contract list a strategy reads comes from the files in `analysis/candle_datas` (stocks: `analysis/stock_datas`), which `analysis/templates/fetch_data.py` keeps - it runs `analysis_rajkumarn/fetch_candles.py` unchanged, pointed at these folders (layout and format: `analysis_rajkumarn/fetch.md`, section 3). Nothing under `analysis_rajkumarn/` is edited (the user, 2026-09-30). **A strategy run never fetches from Upstox.** Scripts are unchanged: `async with Upstox() as up:` and every `up.` data method read the local files.

| | |
|---|---|
| On disk now | NIFTY and SENSEX: the index 1-minute candles, expiry list, contract list, and the option 1-minute candles (with volume) of the fetched plan (`<INSTRUMENT>_option_plan.json`: strikes within the plan's band around each expiry's 20-day range). No daily candles. Stocks are kept apart in `analysis/stock_datas/` (git-ignored; `fetch_candles.py` puts any non-index instrument there, `py_funcs` reads both folders): RELIANCE, HDFCBANK, ICICIBANK 1-minute candles, 2026-01-01 .. 2026-07-31. |
| Missing data | **not fetched.** The run carries on with it as *no data* (rule 6), the report's limits say what was missing, and the run ends with a `NOT ON LOCAL DISK` block: one `analysis/.venv/Scripts/python.exe analysis/templates/fetch_data.py ...` command per gap, for exactly what the run needed. |
| Filling a gap | **Ask the user first.** Only with their yes, run the printed commands from the repository root (the full option-chain fetch follows `analysis_rajkumarn/fetch.md`'s runbook, with `import fetch_data` before `from fetch_candles import ...` so it writes into `analysis/`), then re-run the script. Never fetch more than the run reported missing. |
| Real no-trade vs missing | a day inside a file's `fetched` ranges with no candles is a real no-trade day; a day outside them is missing data. |
| Live calls | the broker's charges / margin calculators (`broker_check`, `broker_margin`), futures lots (`future_contract`), NSE results and dividends, Yahoo: all refuse unless `PYFUNCS_ALLOW_FETCH=1`, which is set only when the user allowed it for that run. `broker_check` then prints *SKIPPED*. |
| Other timeframes | **never fetched** (the user, 2026-09-29): `up.candles(key, "5m" / "15m" / "1h" / "1d", ...)` with no file of its own is built from the 1-minute file — minute and hour candles aligned to 09:15, a day from its whole session (open = first minute's open, high / low = the extremes, volume summed). A **daily close** is the average typical price (h + l + c) / 3 of the 15:00–15:29 minutes (volume-weighted for a stock), the way the exchange sets its official close: on 153 NIFTY days it was a median 1.4 points from Upstox's official close, 90% within 4.3 (the 15:29 minute's close was a median 11 points off, up to 86). Checked: 3m, 5m and 15m equal `resample()` on all 143 sessions, and the re-run reports reproduce the old live-data trades exactly on every shared day. The report says the candles were built (`built_note`). |
| Non-Upstox daily series | a market Upstox does not carry (the five Asian closes ONH v4's Asia rescue reads) lives in `analysis/candle_datas/yahoo_<ticker>_daily.json` (`py_funcs.yahoo_file`; `{ticker, name, source, fetched_utc, timezone, fetched, candles}`), and `yahoo_daily` reads that file first; only with no file and `PYFUNCS_ALLOW_FETCH=1` does it go to Yahoo. The five files on disk (Nikkei 225, Hang Seng, KOSPI, Shanghai, ASX 200; 2025-11-03 .. 2026-08-14) were placed by hand on 2026-09-30 from a verified copy (the Yahoo NIFTY close matched the local Upstox candles, median 1.4 points) - the one exception to the next row. |
| Writes | nothing under `analysis/` except `scripts/` and `report/`; the data folders `analysis/candle_datas` and `analysis/stock_datas` are only written by `fetch_data.py` (and the Yahoo daily files above). |

## Instruments — every index strategy runs on NIFTY and SENSEX (the user, 2026-09-30)

One `index_options` script, one report, every index on disk (`py_funcs.INDEX_INSTRUMENTS` = NIFTY, SENSEX). The script is written once, the NIFTY way, and ends with:

```python
if __name__ == "__main__":
    run_instruments(__file__)          # --instruments NIFTY (or SENSEX) runs just one
elif __name__ == "__instrument__":
    main()
```

`run_instruments` executes the file afresh for each index with `instrument()` set, collects what each run hands to `build_payload`, holds back its `write_report`, and writes **one** report. An index whose run fails is left out and the report says so.

| What differs by index | How the script gets it |
|---|---|
| the underlying | `await up.find_instrument(instrument())` — never the string "NIFTY" |
| strike step, lot size | read, never assumed: `STEP = strike_step()` (NIFTY 50, SENSEX 100); lot from the resolved contract (65 / 20) |
| a number written in NIFTY points (a stop, a floor, a profile row, a minimum risk) | **the same share of the price** (the user's choice): `25.0 * price_scale()` — `price_scale()` is the median SENSEX/NIFTY close ratio over the window (3.2215), 1.0 on NIFTY |
| strike depth "N strikes in the money" | `strike_offset(spot, STEP, N, ...)` counts N in NIFTY strikes (N × 50 points) and gives the same % distance rounded to the index's own step: 6 NIFTY strikes = 10 SENSEX strikes |
| costs | automatic: a SENSEX contract is charged BSE's rates (`exchange_of(symbol)`: 0.005% transaction, no IPFT or SEBI fee, read from the Upstox charges API on 2026-09-30); NIFTY stays NSE |
| free text ("NIFTY sessions", "11:00 NIFTY") | left as written; the combined report renames it for the other index, and session-log columns become "index" |

**Every report shows its instrument(s)** (the user, 2026-09-30): the template reads each trade's instrument — `instrument` when the report holds several indices, else the first word of the trade's symbol (NIFTY / SENSEX, the stock of a stock option, the stock itself in a cash book) — and always shows the Instrument dropdown, an *instrument* (or *stock*) column in the trades table, and an "Instrument(s):" line under the title. One instrument: the dropdown names it. Several (two indices, or the stocks of a book): *all (combined)* plus each one, and a by-instrument breakdown. A strategy setting keyed `side` keeps its key; the built-in Side dropdown then stays out (sharing the key once emptied a report).

**The report** (template, for everyone): an **Instrument** dropdown first in the settings row — *all (combined)* adds the books together (the default), each index shows its own book. Like *side* it is built in, not a strategy setting: the best-setting search keeps it where it is, and it never shows as "the rule". The trades table and *Every day* get an *index* column (the log follows the dropdown), the breakdowns get an *instrument* group, each trade is charted on its own index, and the header states the backtest window and its sessions. A day can hold a NIFTY and a SENSEX trade at once — the combined book is the two books added, not one position at a time.

Not run on SENSEX: the `stock_*` categories. (`stretch_fade_v2`, whose VWAP was built from the 50 NIFTY stocks, and the stock strategies were removed on 2026-09-30 - the user.)

### The strike ladder — every strategy on 6 ITM … ATM (the user, 2026-09-30)

`run_instruments` also runs every index strategy on `STRIKE_LADDER` = 6, 5, 4, 3, 2, 1 ITM and ATM — NIFTY strikes, the same % distance on SENSEX (10, 8, 6, 5, 3, 2 SENSEX strikes and ATM). The report gets a **Strike depth** setting with those seven values.

| | how |
|---|---|
| a script with its own `moneyness` setting (onh_v2–v4, stretch_fade_v1/v3) | its options are `STRIKE_LADDER`; the runner calls it once per strike with `--moneyness N` |
| a script that trades one strike (ATM: onh_v1, orr, snd, vpr) | untouched: at rung N `resolve_option` moves the contract it asks for N strikes in the money (a CE below the spot, a PE above), and the candles, fills, costs and lot follow the contract |
| which settings | **the rule on every strike** (the user's choice): the rule's own strike (ATM, or the script's declared depth) keeps every setting of the panel; every other strike keeps only the trades of the rule's own settings (a script with no declared panel: its panel defaults). Another setting at another strike has no trades — the combination table and the best-setting search list only what was simulated |
| order | the rule's strike runs first on each index; a failed non-rule strike is listed in the report, a failed rule strike drops the index |
| narrowing | `--rungs 6,0` (or `--moneyness 6,0`, what the report's re-run command writes) and `--instruments NIFTY` for a quick run |
| in the report | a section **The rule on every strike**: one row per strike, one column group per index (NIFTY and SENSEX never added into one count), the rule's settings with the window, side and filters as set; click a row to load it. Picking a strike in the panel while other sweeps are off the rule (the page opens on the *best* setting) moves them to the rule's values and says so — otherwise that strike would show no trades |

A cached helper must be keyed on the index it answers for: `price_scale()` once cached NIFTY's 1.0 for every later SENSEX run (2026-09-30, fixed) — SENSEX strike depths came out half as deep and its point amounts unscaled until the reports were re-run.

## Categories — pick one before anything else

Every strategy belongs to exactly one category. The category fixes the folder, what one unit of a trade is, how it is charged and what capital it ties up. It is declared once, in `py_funcs.CATEGORIES`. A script sets `CATEGORY = "<key>"` and puts it in `meta["category"]`. `build_payload` refuses a category that disagrees with the script's folder, and writes the category's cost model into the report itself.

| category | folder | traded | one unit | costs (`trade_costs`) | capital | holding |
|---|---|---|---|---|---|---|
| **stock_intraday** | `scripts/stock_intraday/`, `report/stock_intraday/` | cash equity, product MIS (`I`) | **one share** at the stock's full price — no lots, no leverage (the user, 2026-09-28) | `equity_round_trip`: brokerage ₹30 or 0.1% per order (lower), STT 0.025% on the sell leg, NSE 0.00297% + IPFT ₹10/cr, stamp 0.003% on the buy leg, SEBI, GST 18% | **not reported** — the broker gives no historical MIS margin, so the report is in points per share (`report_unit: "points"`), one stock or several; `broker_margin_ratio` still sizes a live trade | same session only |
| **index_options** | `scripts/index_options/`, `report/index_options/` | NIFTY / BANKNIFTY ... options | lots × the resolved contract's `lot_size` | `option_round_trip`: brokerage ₹30 per order, STT on the sale 0.1% of premium (**0.15% from 2026-04-01**, at the rate of the day of the sale - an overnight trade sold after a change pays the new rate), NSE 0.03503% + IPFT ₹0.50/lakh, stamp 0.003% on the buy leg, SEBI, GST 18% | bought: premium × qty; sold: the broker's SPAN + exposure margin (`broker_margin`) | intraday or overnight; not through expiry day |
| **stock_options** | `scripts/stock_options/`, `report/stock_options/` | stock options | lots × the resolved contract's `lot_size` | `option_round_trip` (NSE charges stock and index options alike) | as index options | never into expiry: stock options are physically settled |

**How each category reads in the report.** Each category has a `report_unit`.
- **`stock_intraday` → points.** Upstox gives no historical MIS margin, so an intraday-stock report has no rupees at all: no P&L, costs, quantity, margin or leverage. `build_payload` turns every trade into points per share with `points_view` (gross = net = points in the trade's favour, costs = 0). The same code then computes the whole book in points: win rate, profit factor, drawdown, t-stat, breakdowns, stability and combinations.
  - What the report shows: total points, points per trade, average move % (points ÷ entry, comparable across price levels), average win and loss, payoff, best and worst trade, drawdown, streaks, and average MFE / MAE with "capture" (points ÷ average MFE, how much of the favourable move the exit kept).
  - The equity curve plots cumulative points or cumulative move %.
  - A win is a trade that gained points; costs are not deducted in the report. A rule may still use costs in its own logic (an exit line), and the script prints `broker_check` to the console.
  - `console_summary` prints points for cash-equity trades.
- **A book of several stocks (added 2026-09-28)** stays in points per share, like every intraday-stock report — the user reads trades in the stock's own price, never in bps. A point on a ₹7,000 stock is a smaller move than on a ₹250 one, so say so in `meta["limits"]` and point the reader at *average move %*.
  - Pass each stock's own 1-minute sessions as `option_sessions={symbol: {day: rows}}` and the market index as `index_sessions`. The page charts every trade on **its own stock** (fills, stop/target, `levels`) with the index under it for context, the cross-check walks the stock's bars, the close-fill comparison re-prices from them, the trades table gets a *stock* column, and "the benchmark" is the stock's own move. With `chart="default"` a stock's candles are embedded only for the sessions the rule's own trades use. Set `meta["index_label"]` (e.g. "NIFTY 50") to name the context chart. (`minute_sessions(..., volume=True)` gives the volume a VWAP needs.) No stock_intraday strategy is kept: late_gap_fill_v5 and panic_buy_v1 were removed on 2026-09-30 (the user).
- **Options → rupees.** Options reports keep rupee P&L net of costs, with premium and underlying columns.
- The page decides from `meta.unit`, and its self-check covers the MFE, MAE and move totals.

### Stock options — the standard (checked against Upstox 2026-09-24)

A stock option is charged exactly like an index option (the charges API returns identical numbers for a ₹20,000 premium round trip on NIFTY, RELIANCE, HDFCBANK, ICICIBANK, INFY and SBIN), but the contract is different. A rule written for NIFTY is carried over only through these points:

| | NIFTY | stock options | what a `stock_options` script must do |
|---|---|---|---|
| Expiries | weekly and monthly | **monthly only** (last Tuesday) | "nearest weekly" becomes the nearest monthly; take it from `expiry_calendar(stock_key)` |
| Strike spacing | even (50) | **uneven**: RELIANCE/ICICIBANK/SBIN 10 then 20, HDFCBANK 10/20/40, INFY 20/40 | "N strikes ITM/OTM" steps through `up.listed_strikes(key, expiry, type)`; never `strike_offset` with one step |
| ATM | spot rounded to the step | the **listed** strike nearest the spot | `min(listed, key=abs(k - spot))` |
| Lot size | 65 | 400–750 and revised by NSE | `qty` from the resolved contract, per trade (rule 8) |
| Liquidity | every minute trades | **deep ITM and far strikes skip minutes** (2–33 of ~175 nights per stock for 6-ITM) | a missing entry/exit minute skips the night and is listed (rule 6); report the skip count in `meta.limits` |
| Settlement | cash | **physical**: an ITM option held into expiry is delivered | expiry at least one day after the exit day; an overnight hold never crosses it |
| Underlying chart | one index | one stock per report | one report per stock: `<slug>_<stock>.html`, the stock's own sessions as `index_sessions` |
| Evidence | — | a NIFTY-born rule is **in-sample for NIFTY, out-of-sample for stocks** | say so in `meta.limits`; judge it per stock and per half of the window, never on the pooled total |

What the first carry-over showed (ONH v1/v2/v3, Jan–Sep 2026, 1 lot, worst fills, broker costs): v1 lost on all five stocks (its 15:29 and 09:15 minutes are the widest of the day); v2 and v3 were positive on four of five (SBIN lost); v3's time-value check made the result steadier across halves, v2's total was larger but carried by single stocks and months.

**No stock-option strategy is kept (the user, 2026-09-30).** The ONH v2 / v3 stock-option scripts and their reports were removed, with the `scripts/stock_options/` and `report/stock_options/` folders; the category stays defined for a future one. Stock candles live apart from the index data, in `analysis/stock_datas/` (git-ignored); RELIANCE, HDFCBANK and ICICIBANK 1-minute candles for the window are there.

**Open issue — zero-volume minutes.** Upstox returns a candle for a minute with no trade (open = high = low = close, volume 0). About 80% of the 6-strikes-ITM entry minutes are such bars, so the worst-fill rule cannot protect against them: those fills are the last traded price, not a tradeable one. `option_candles(..., volume=True)` now returns the volume as a sixth column (from the contract's local file, added 2026-09-29; first user `scripts/index_options/stretch_fade_v1.py`, which fills only on minutes that traded); until a zero-volume minute is treated as "no trade" (rule 6) and the strike is chosen by depth in % of spot with a liquidity check, the stock v2/v3 results are provisional.

**Read from the broker.** The rates were read from the Upstox charges API (`/v2/charges/brokerage`, this account) on the date in `BROKER_READ_ON`. Brokerage is the account's plan, Upstox Plus at ₹30 per order (the standard plan is ₹20), so it applies to every date. Regulatory rates carry their effective dates, so a trade is charged what was in force on its own day. Every script calls `broker_check(up, CATEGORY, key, qty, price)` once and prints the line — a live call, so it prints *SKIPPED* unless the user allowed live calls for that run (`PYFUNCS_ALLOW_FETCH=1`); `DISAGREE` means a rate in py_funcs section 6 is stale. Fix it there, with its date and source, never in a script. Margins come from the margin API (`broker_margin`, `broker_margin_ratio`) and are today's numbers, so say so in `meta.limits`.

### Intraday stocks — how every strategy is backtested from now on (the user's standing rules, 2026-09-28)

These hold for every `stock_intraday` script. They are not settings; a strategy cannot switch them off. Where a line below disagrees with an older note elsewhere in this file, this section wins.

| # | What | The rule | Enforced by |
|---|------|----------|-------------|
| 1 | **Size** | **One share** per trade at the stock's full price. No F&O lots, no leverage, no margin — anywhere, including cost lines and console summaries. `qty=1` in `make_trade`; never call `up.future_contract` in a stock script. | the script (`QTY = 1`) |
| 2 | **Entry price** | **Worst price only.** The signal candle must be complete; the trade happens in the **next 1-minute candle**: a **BUY at its HIGH**, a **SELL at its LOW**. A signal known before the open (a gap, yesterday's facts) enters in the 09:15 candle at its high / low. There is **no pre-open auction price** (`preopen_fill` is for options only). | `build_payload` → `worst_fill_breaches` refuses the report |
| 3 | **Exit price** | **Worst price only.** A target / stop / exit line touched inside a completed minute exits in the **next minute**: a long is sold at that minute's **LOW**, a short is bought back at its **HIGH**. A scheduled time exit (e.g. 14:45, 15:14) fills in its own minute at the same worst side. Exits are checked from the minute **after** the entry minute. | `scan_exit`, `worst_fill_breaches` |
| 4 | **Second view: the signal candle** (the user, 2026-09-30 - replaces "worst case only") | Beside the worst case (the rule), every report re-prices the same trades one candle earlier: a buy in at the signal candle's HIGH and out at the exit candle's LOW; a sell in at the signal candle's LOW and out at the exit candle's HIGH. It is the *fill view* dropdown; worst stays the default and the only price a result is quoted at. | `_price_fills` (every category) |
| 5 | **Units** | **Points = rupees for that one share**, in the trade's favour (a short that falls ₹5 is +5), plus *average move %* to compare stocks. **Never bps.** A book of several stocks is still points; say in `meta.limits` that a point on a ₹250 stock is a bigger move than on a ₹7,000 one. | `points_view` |
| 6 | **Costs** | Not deducted in the report (a win = a trade that gained points). If a console line or the answer to the user shows costs, it is for **one share**: brokerage is ₹30 or 0.1% per order, whichever is lower, so one share pays about **0.27% of the price per round trip** (₹2.71 on a ₹1,000 share) — say so plainly, because it eats most small intraday edges. | the script / the answer |
| 7 | **Holding** | Same session only (MIS). Every exit is at or before 15:14 unless the rule says otherwise. | the script |
| 8 | **Data** | 1-minute candles via `up.minute_sessions(key, frm, to)` from the stock's local file (`volume=True` when a VWAP or relative volume is needed); "yesterday's close / high / low" from the **daily candle** (the official close, its own local file); results days and ex-dividend days from NSE (`nse_results_stamps`, `nse_exdividend_days` — live calls, only with the user's permission). No stock is on disk yet: a stock run reports what to fetch (see *Data*). Only complete 375-candle sessions trade (a Muhurat or short session is `no data`); a corporate action that makes a price jump (a demerger, a split) is skipped and named in `meta.limits`. | `coverage`, `session_row` |
| 9 | **Several stocks** | Pass each stock's own candles as `option_sessions={symbol: {day: rows}}`, the market index as `index_sessions`, and `meta["index_label"]`; the page charts each trade on its own stock. | `build_payload`, `sample.html` |
| 10 | **Words** | Plain trader's words in titles, rule steps, settings, tags and notes; amounts in rupees / points or % of the price; a worked number in the rule steps. | review |
| 11 | **Honesty** | Pick the rule's values on the first part of the window and read the rest (`meta["break_date"]`); state in `meta.limits` what was chosen with hindsight, how many ideas were tried, and whether the trades cluster on a few days — run the **day-level check** (days that made money, the median day, the result without the best 5 days) and print it. | `meta` |
| 12 | **Timeframes** | Bigger candles may decide the **entry** — a 5-minute or 15-minute signal candle (aligned to 09:15), the first hourly candle, the daily chart (yesterday and earlier) — using **completed candles only**. Every **fill** stays on the **1-minute candle** of rules 2–3 (the user, 2026-09-29: "the worst case rule checks in the 1 min only; the higher time frames are only for the entry models"). | the script, `worst_fill_breaches` |
| 13 | **Trade count** | The rule must make **at least 120 trades in the one-year window** (the user's minimum). A filter that lifts the win rate but drops the rule below 120 is a setting, not the rule. | the script / the answer |

**Why the time of day matters under rules 2–3.** The worst price costs about one candle's width per round trip, and the width changes through the day (median of the 50 NIFTY stocks, 2025-09..2026-09): **09:15 ≈ 0.67%** of the price, 09:20 ≈ 0.19%, 09:30 ≈ 0.14%, **10:15–14:30 ≈ 0.07–0.09%**, the 15:00 closing window ≈ 0.14%. A strategy that trades the opening minute gives most of its move away; waiting until about 10:30 avoids most of it.

---

## Rules to Live By

These hold for every strategy, whatever the prompt says. They are enforced by functions in `py_funcs.py`; a script that bypasses them is wrong. If a prompt contradicts one, **stop and ask** — do not silently choose.

| # | Rule | Why | Enforced by |
|---|------|-----|-------------|
| 1 | **Every BUY fills at the bar's HIGH, every SELL at the bar's LOW** — entry and exit alike: a long buys at the HIGH and sells at the LOW; a short sells at the LOW and buys back at the HIGH. For options, the same applies to the premium bars of whichever contract (CE or PE) is traded. This is **the rule, the default, and the only convention a result may be quoted at**. The report also re-prices the same trades in a **second view, the signal candle** (the user, 2026-09-30; it replaced the bar-close comparison): the same signals and exit minutes, a buy in at the **signal candle's high** (the 1-minute candle just before the entry minute, also when the signal came from a bigger candle) and out at the **exit candle's low** (the minute before the exit fill for an exit a price triggered; an exit at a set time - 15:14, 09:30, next morning - keeps its own minute); a short mirrors it. A leg whose signal or trigger minute has no candle (nothing traded, or a signal before the open) keeps its worst price, and the report counts them. Labelled a **comparison** - never a result. Worst and signal candle are the only two views computed. **One named exception (agreed 2026-09-24):** an equity entry order placed in the NSE **pre-open session (09:00–09:08)** is matched in the call auction and fills at the official open, i.e. the 09:15 bar's OPEN — `preopen_fill()`. It applies to that entry only; every exit and every order after the open stays on the worst fill. A strategy that uses it says so in `meta.limits` and offers the rule-1 entry beside it in the panel. **INTRADAY STOCKS — WORST PRICE ONLY, permanently (the user, 2026-09-28):** a buy signal buys at the HIGH of the candle after the signal and exits at the LOW of the candle after the exit signal; a sell signal sells at the LOW of the next candle and exits at the HIGH of the candle after the exit signal. For `stock_intraday` there is **no** pre-open exception, and `build_payload` **refuses** a report with any trade not filled at its candle's worst price (`worst_fill_breaches`); the pre-open exception remains for options only. The second view (signal candle) is shown for stocks too (the user, 2026-09-30), as a comparison beside the worst case. | No fill may be better than a real one could have been. But when the convention moves the answer more than the rule does, hiding it is its own dishonesty: across twelve strategies the worst-to-close swing ran Rs 73k to Rs 5.5 lakh and flipped **nine of twelve from loss to profit**. The pre-open auction is not a better-than-real fill: every pre-open order at the equilibrium price trades AT it. | `worst_fills(...)`, `worst_fill_breaches(...)` (stocks), `_price_fills` (options), `preopen_fill(...)` (options only) |
| 2 | **A signal from a candle is acted on in the next candle.** The signal candle must be *complete*; the trade (entry or exit) happens in the **next 1-minute bar** — whatever the signal timeframe. A 1m signal → the next 1m bar. A 5m candle starting 09:15 completes at 09:20 → the 1m bar starting 09:20. | The decision cannot use a price that had not yet finished forming. | `bar_after_candle(rows_1m, candle_start, tf)` |
| 3 | **Stops and targets are signals too.** A stop/target touched inside a completed bar exits in the *next* 1-minute bar (rule 1 prices apply). If one bar touches both, the **stop is assumed first**. A scheduled time exit (e.g. 15:14) fills in that bar itself. | Same reason as rule 2; the tie-break is the conservative one. | `scan_exit(bars, side, entry_key, stop, target, force_key)` |
| 4 | **Only completed candles are read.** Indicators, levels and tags for a decision use candles up to and including the signal candle, never later ones. | Look-ahead makes every backtest look better than it is. | index `i` = signal candle in `sma/ema/rsi/atr`, `crossed_above/below` |
| 5 | **Wins are counted net of costs.** Every trade carries its brokerage, STT, exchange, SEBI, stamp and GST; a trade that only covers costs is a loss. **Exception:** a points report (`stock_intraday`) has no costs in it, and its win is a trade that gained points; it says so on the page. The rates are the CATEGORY's, read from the broker and dated (see *Categories*); a new instrument type gets a new category with broker-read rates. Never guess a rate — ask. | Gross profit that costs eat is not profit. | `make_trade` (`kind='option'` → `option_round_trip`, `kind='equity'` → `equity_round_trip`, both on the trade's day); `trade_costs(category, ...)`; `broker_check` |
| 6 | **Bad data means no trade, said out loud — in the report, not only the console.** A missing, duplicated or invalid candle, a short session, a missing option bar, or a missing contract → skip that day and log it. Never fill from a later bar, from a close, or invent a high or low. | A gap filled with a guess is a fake fill, and a skip nobody sees is a silent one. | `bar_after_candle(strict=True)`, `coverage()`, `session_row(..., "no data")`; print every skip too |
| 7 | **Use complete sessions only.** A full NIFTY session is 375 one-minute bars (09:15–15:29). Today's session is not used until it is over (after 15:45). | A half-day bar is not the day's bar. | `coverage(..., rows_per_session=375)` |
| 8 | **Instrument facts come from Upstox, never from memory.** Strike step, lot size, expiries, instrument keys. Take `qty` from the *resolved contract's* `lot_size`, per trade — never a constant. An intraday-stock trade is **one share** — never a lot (the user, 2026-09-28). (Checked live: NIFTY was 25 in Dec 2024, 75 in Nov 2025, 65 now; the contract Upstox returns for a past expiry carries the size in force then. `capital` scales with it.) | Hardcoded facts go stale silently. | `find_instrument`, `option_chain_info`, `expiry_calendar`, `resolve_option`, `future_contract` |
| 9 | **One position at a time** unless the prompt says otherwise. | Overlapping trades double-count the same capital. | strategy loop |
| 10 | **A bought option is not held through its expiry day.** Default expiry: the nearest one at least 1 day after the exit day, unless the prompt says otherwise. | Expiry-day premiums collapse; the numbers stop being comparable. | `next_expiry(expiries, day, min_days_after)` |
| 11 | **Selection is disclosed.** If the script picks parameters by looking at the same window it reports, say in `meta.limits` that the result is in-sample. Every compared value goes in the control panel, not only the winner, and the rule's own value is the panel's default. | The best cell of a grid is mostly noise. | `setting()`, `variant=` on trades |
| 12 | **Tags describe the moment they are measured.** A tag for an entry condition is computed from candles complete at the entry signal; an exit tag from candles complete at the exit signal. | Same as rule 4, for the group-by columns. | strategy code |
| 13 | **Capital is stated with its source.** Bought option: premium × qty. Sold option: the broker's margin (`broker_margin`). Intraday stock: not reported — a points report (see *Categories*), because the broker has no historical MIS margin. A broker margin is today's number, so say so in `meta.limits` wherever one is used. | Return-on-capital is meaningless without it. | `make_trade(capital=)` |
| 14 | **Times are exchange time (IST) as `HH:MM`.** | Mixed time zones corrupt every join. | `sessions_from` |
| 15 | **Local data only; nothing fetched without the user's permission, and nothing written outside `analysis/scripts/` and `analysis/report/` (the data folders are written only by `fetch_data.py`).** Every read comes from `analysis/candle_datas` (see *Data*), closed sessions only. What is not on disk is *no data*, said in the report, and listed as the exact `fetch_candles.py` commands to fill it — run only after the user says yes, and only for what was listed. Nothing is interpolated, filled forward or reconstructed: a gap stays a gap. | A backtest must not hit the broker behind the user's back, and one data store means every strategy reads the same bars. | `Upstox` (local), `missing_report`, `missing_note`, `PYFUNCS_ALLOW_FETCH` |
| 16 | **The window is `START_DATE` .. `END_DATE` in `py_funcs.py`, and nowhere else.** **Both are fixed: 2026-01-01 .. 2026-07-31, the 143 sessions on local disk (the user, 2026-09-29: "strictly backtest on this period only").** Candles before the start may be read as an indicator's warm-up, never traded. No script defines its own defaults — a local copy shadows the shared values and can silently run a different period. Audit *every* date default in a script, not only `--from`. `check_window` refuses any window outside START_DATE .. END_DATE; the ends move only when the user asks. | Every strategy is judged on exactly the same sessions, all of them on disk. | `START_DATE`, `END_DATE`, `check_window()` |

| 17 | **Every session in the window is accounted for** with a `session_row()`: traded, declined, no signal, or no data. The report shows them as *Every session*, and `validate_payload` refuses a log that disagrees with the trades. | A report built from trades alone cannot answer "what about the other days?", and that is the first question a reader asks. | `session_row`, `build_payload(sessions_log=)` |
| 18 | **The report is fixed; the panel is the strategy's.** The metrics, the cards, where the charts sit, the trades table, the cross-check, Every session, Stability, the combination table — identical in every report, and never edited for one strategy. What changes per strategy is the **panel**: which settings a reader may move, what values they offer, and which one is the rule. A strategy that ships no panel has not been thought about. | One template is only worth having if nobody forks it. And a report you cannot interrogate is a screenshot: the numbers for one setting, with no way to ask whether a different one was better. | `setting()`, `groups=`, Step 1b |

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
| 2 | **Window** | nothing to state — rule 16 fixes it at `START_DATE`..`END_DATE`. Only a request for a *different* window is an item here | Different from the shared window? Say so and why |
| 3 | **Signal timeframe** | the interval (1m/5m/15m/1d). Higher timeframes are built from 1m | Which interval? |
| 4 | **Signal rule** | exact inputs (which candle, which price), the comparison, every threshold as a **number**, and every indicator with its parameters | "strong", "near", "breakout" with no number or definition |
| 5 | **Decision time** | when the decision is taken (at the close of which candle) — rule 2 fixes the fill | At what time / on which candle? |
| 6 | **Direction mapping** | what each signal does (up → buy CE? sell PE? long index?) | Which side for each signal? |
| 7 | **Traded instrument / category** | the category: `stock_intraday`, `index_options` or `stock_options` (see *Categories*) | What is traded? |
| 8 | **Option specifics** *(if option)* | buy or sell · strike rule (ATM, N steps ITM/OTM) · expiry rule · lots | Strike? Expiry? Lots? |
| 9 | **Entry** | the signal that triggers it (fill is fixed by rules 1–2) | Any entry condition beyond the signal? |
| 10 | **Exit** | every way out with numbers: target, stop, time, signal; the first minute an exit may fire; stop/target basis (premium %, points, index level) | Stop? Target? Time exit? |
| 11 | **Holding period** | intraday, or overnight (then which session's bars) | Overnight allowed? |
| 12 | **Costs** | option: the standard schedule; anything else: the rates | Costs for this instrument? |
| 13 | **Position rules** | one at a time (default)? re-entry after a stop? | Can trades overlap? |
| 14 | **Missing data** | skip, log as `no data`, and list (default) or abort | — |
| 14b | **Declined vs no signal** | which sessions the rule *saw but refused* (they become `declined`) and which it never fired on (`no signal`) | Is this condition part of the signal, or a filter over it? |
| 15 | **Settings (the control panel)** | never "clear" from the prompt alone — **you** derive the panel from the rule by Step 1b and put the proposal in the checklist table for the user to correct. The date range is built in, never a setting | Show the proposed panel as a table (setting · kind · mode · values · the rule). Ask only where a value list is a real judgement call |
| 16 | **Custom group-bys** | for each: the **indicator**, its **parameters and timeframe**, the **bucket definitions**, the **candle it is measured on**, the **side-aware wording**, and whether it stands **alone** or is **combined** with others (single or multi-indicator bucket) | See below |
| 17 | **Script name** | a slug | (default: derived from the prompt) |

**Custom group-by — what a clear description looks like.** Example the user gave: *"at entry, is the instrument above/crossing its SMA10 — for a Buy (buy CE) 'crossed above' vs 'not above'; for a Sell (buy PE) 'crossed below' vs 'not below'."* To be clear it needs: which instrument's price (the index), timeframe (the signal candle's), SMA period (10) on which price (close), what "crossed" means (previous close at/below SMA, this close above) and the measuring candle (the signal candle). Ambiguous → ask. Combined groups ("SMA10 with RSI bucket") need the second indicator defined the same way, and the RSI edges (`bucket(rsi, [40, 60], ["below 40", "40-60", "above 60"])`).

**`side` is not direction — carry a `direction` tag.** `side` is LONG or SHORT on the
*instrument traded*, so a bought put is LONG and an option-buying strategy has `side = LONG`
on every single trade. When side is constant the report drops it and shows **direction**
instead, taken from the trade's `direction` tag, falling back to CE/PE; the pill is coloured
from the option type, which is never ambiguous. Give every directional strategy a `direction`
tag, or the column reads "CE" / "PE" and says less than it could.

**Standard group-bys (added automatically, do not ask for them):** weekday, month, entry hour, exit reason, and — when the trades are options — option type (CE / PE, read from the contract symbol or `make_trade(option_type=)`) and DTE (days to expiry at entry, from `make_trade(expiry=)`; shown as "0 DTE", "1 DTE", …). If the direction of the signal (BUY/SELL, CE/PE) matters, put it in a tag called `direction` and add a group for it — do not duplicate weekday or side (side is a filter).

**Check the prompt for itself:**
* **Contradictions** — e.g. "exit at 15:15" and "hold overnight".
* **Rules that break the Rules to Live By** — e.g. "enter at the signal candle's close", "fill at the close". Say which rule it breaks and ask.
* **Unmeasurable words** — every adjective must become a number or formula.
* **Data Upstox cannot give** — order book, IV, delta history. Say so.
* **Too many sweep combinations** — sweeps multiply and each one is a separate simulation (and sometimes a separate fetch); the limit is `MAX_COMBOS = 240`. Filters are free, so prefer a filter whenever the knob only ever removes trades. Ask the user to trim the sweeps.

#### Defaults (only when the user says "use defaults" or the item is marked *assumed*)

| Item | Default |
|------|---------|
| Settings | none beyond the rule; the panel then shows only the window |
| Costs | the category's schedule (`trade_costs`); a new instrument type needs a new category — ask |
| Lots | 1 lot; `qty = lots × lot_size` from the resolved contract |
| Missing data | skip, list in the console and in the answer to the user |
| Positions | one at a time |
| Expiry | nearest at least 1 day after the exit day |
| Session | 09:15–15:29, 375 one-minute bars |
| Window | `START_DATE` 2026-01-01 through `END_DATE` 2026-07-31 (both fixed, the 143 sessions on disk) from `py_funcs` — see rule 16. Never define them in a script |
| Stop and target tie in one bar | stop first |

### Step 1b — Design the panel (mandatory, before any code)

The template fixes everything that is the same for every strategy. It cannot fix the one thing
that is not:

| Fixed by the template — never per strategy | Declared by the strategy |
|---|---|
| the overview metrics and what each one means | which settings appear in the panel, and their bands |
| where the charts sit and how they are drawn | the values each setting offers |
| the trades table and the cross-check walk | which value is **the rule** (the default) |
| Every session and its status tabs | the columns of the session log (`facts`) |
| Stability and its slices | the custom group-bys (`groups=`) |
| the combination table, the verdict, the window control | `rule_steps`, `params`, `limits`, `rejected` |

If a strategy needs something the template does not have, **put it in the template for
everyone**. Never add a section, a metric or a table to one report.

#### Walk the aspect catalogue first

Go down **[The aspect catalogue](#the-aspect-catalogue)** at the foot of this file, family by
family: does this strategy have something there, and what would it take? Most rows are already
free; the rest name the exact `setting`, `tag`, `group`, `levels` or `meta` key that turns them
on. Read the gaps list too, so you do not promise something the template cannot draw. That pass
is what stops a report shipping without the comparison the reader wanted.

#### Deriving the panel from the rule

Read the rule one sentence at a time. Every **number**, every **choice** and every
**condition** is a candidate. Put each one in exactly one box:

| Box | The test | Where it goes | Cost |
|-----|----------|---------------|------|
| **fixed** | changing it would make it a different strategy, not a setting of this one | a module constant, and a line in `meta["params"]` | — |
| **sweep** | it re-prices **the same sessions** under a different parameter — R:R, stop rule, strike depth, timeframe | `setting(mode="sweep")`, `variant=combo` | one simulation per value, sometimes one fetch |
| **partition** | it splits **which sessions** — a day is a gap-up or a gap-down, a long or a short, never both | `setting(mode="filter")` with an **"any"** option and `var={key: [value]}` | nothing extra; the script still stamps `variant=` |
| **filter** | it only ever *removes* trades that were already simulated | `setting(mode="filter")` + a tag on every trade | nothing |
| **group-by** | it does not change the rule at all; it splits the same trades to be read side by side | `groups=` + a tag | nothing |

**A sweep and a partition are not the same knob, and getting it wrong changes the strategy.**
A sweep must NOT offer "all": pooling a night's 1:2 and 1:3 versions is not a book. A partition
MUST offer "any": its values are disjoint halves of **one** book, and refusing to pool them
means the report can never show the strategy as it actually trades. That is not a display
nicety — a two-direction rule once opened on one direction and a third of its trades, and there
was no way to reach the whole book. The test is on the trades: **does the same session appear
under more than one value?** Yes → sweep. No → partition. `build_payload` runs that test
(`_axis_shape`) on any script that declares nothing, so no strategy's nature depends on a
declaration being remembered.

**One fact, one dropdown.** If a `variant` key and a `tag` carry the same information — a
perfect one-to-one mapping — they must not both become controls. Set them to disagreeing
values and the report shows nothing. The derivation detects this (`_one_to_one`), keeps one
control and lets the tag lend it its better name; the tag stays a group-by either way.

Three traps, all of which have already been hit here:

* **A declared axis is not automatically an applicable one.** A family of scripts often shares
  one list of choices, and some of them name things a given rule does not have. Check the rule,
  not the list: three of the four `STOP_ANCHORS` name a sweep and a micro-BOS that snd_v3 (the
  zone alone) and snd_v4 (the trailing rule) never produce. Do not fake it and do not silently
  leave it out — **refuse it in `meta["rejected"]` with the reason**, so the report says why the
  axis is absent. The same applies to an axis that would break a Rule to Live By.

* **A condition the rule applies at entry is a filter, not a skip.** If the script `continue`s
  past a night the condition rejects, that night has no trade and the reader can never switch
  the condition off. Trade every candidate, tag it, and let the filter select. The session log
  then marks it `declined` rather than hiding it.
* **Prefer a filter to a sweep whenever the test allows it.** Sweeps multiply, and each value
  of a strike-like sweep is a fresh fetch — a 7-rung ladder over 137 nights is ~1,900 requests
  and about an hour of pacing. Filters are free.

#### The five axes — cover what you can, and say what you did not

A panel with one dropdown is not a panel. Walk these and take what the strategy actually has:

| # | Axis | Typical settings |
|---|------|------------------|
| 1 | **What is traded** | strike depth / moneyness, expiry choice, lots, CE vs PE |
| 2 | **When it enters** | each entry condition on/off; each threshold at the rule's value and one either side; the decision minute |
| 3 | **When it exits** | stop, target, R:R, time exit, the first candle an exit may fire, trailing vs fixed |
| 4 | **On what timeframe** | the signal interval (1m / 3m / 5m / 15m) |
| 5 | **Which direction** | long vs short; `side` appears on its own when the trades have both |

Then the **group-bys**, which answer "when does this work?" rather than "what if I changed it":
weekday, month, entry hour, exit reason, option type and DTE come free. Add the strategy's own
context — the regime, the gap, the volatility bucket, the distance from a level at entry.

#### The floor, if you declare nothing

A script with no `SETTINGS` does not get an empty panel. `build_payload` **derives** one from
what the script already emits: every `variant` key becomes a sweep (it already was one), and
every `tag` with a handful of values becomes a filter with an "any" option, cheapest-first
until the combination count would get silly. Existing scripts therefore gained a working panel
without being edited.

It is a floor, not a substitute. A derived panel carries raw keys for labels, has **no rule**
(so nothing is marked "← the rule" and the reset button says *reset to defaults*), and has no
CLI flags. The build prints a warning saying so. When you next touch such a script, do Step 1b
properly and declare them.

#### Choosing the values

The rule's own value, plus **at least one on each side of it**, and stop. Three to five values
per setting. A grid is not analysis: `MAX_COMBOS` is 240 sweep combinations, the combination
table lists at most 1000 rows, and every extra sweep value on a strike-like axis is another
pass over the whole window. Print `fetch_estimate()` before a ladder starts.

#### What to show the user

In the Step 1 checklist, show the proposed panel as a table and let them correct it:

| setting | kind | mode | values | the rule |
|---------|------|------|--------|----------|
| Strike depth | strike | sweep | 6 ITM … ATM … 6 OTM (13 rungs) | 6 ITM |
| Time-value check | entry | filter | ≤15% of premium · ≤60 points · cheapest 75 in 100 · none | ≤15% |
| First exit candle | exit | sweep | 09:16, 09:30, 10:00 | 09:30 |

**A threshold usually has more than one shape, and they are not the same question.** That
time-value check is one number three ways: a share of the premium, a flat number of points,
and a rank against recent nights at the same rung. A flat bar is *absolute* — options are dear
when the market expects movement, so a nervous stretch refuses almost every night and a quiet
one almost none; a rank moves with the market. Offer the shapes side by side and add a
group-by that asks **do they agree?**, because where they disagree is the finding.

and name, in one line each, what you decided **not** to make a setting and why — that list goes
into `meta["rejected"]` and shows up as *What was tested and left out*.

### Step 2 — Write down the plan

Before coding, state in a few lines: data to fetch, the loop over days, the signal, how each trade is built, the tags/filters/groups, and the output. If `py_funcs.py` lacks something (e.g. futures costs), add it there as a general function — never bury it in one strategy.

### Step 3 — Write `analysis/scripts/<category>/<slug>.py`

* Docstring = the user's prompt, then the checklist answers and assumptions.
* Start with:
  ```python
  import os, sys
  sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
  from py_funcs import *
  CATEGORY = "index_options"     # stock_intraday | index_options | stock_options
  ```
  and put `"category": CATEGORY` in `meta`. Leave `meta["cost_model"]` out: `build_payload` writes the category's own.
  An `index_options` script reads its index with `find_instrument(instrument())`, its step with `strike_step()`, scales every NIFTY-point number by `price_scale()`, and ends with the `run_instruments` guard (see *Instruments*).
* CLI: `--from`, `--to` (defaults from the prompt).
* **All Upstox calls go through `py_funcs.Upstox`.**
* Split the file: `fetch` (async) · `signal` (pure, completed candles only) · `simulate` (pure: bars → exit, via `bar_after_candle`, `worst_fills`, `scan_exit`) · `main`.
* **Declare the control panel** as a module-level `SETTINGS` list, and make the defaults the rule exactly as the prompt states it:
  ```python
  SETTINGS = [
      setting("tv_check", "Time-value check", kind="entry", mode="filter", default="15",
              options=[{"value": "off", "label": "no check", "tag": None},
                       {"value": "15", "label": "skip above 15%",
                        "tag": {"time value": ["below intrinsic", "0-5%", "5-10%", "10-15%"]}}]),
      setting("first_exit", "First exit candle", kind="exit", values=["09:16", "09:30"], default="09:30"),
      setting("moneyness", "Strike depth", kind="strike", values=[0, 2, 4, 6, 8], default=6,
              unit=" strikes ITM", rerun=True),
  ]
  ```
  `kind` picks the band it appears under: `entry` · `exit` · `strike` · `sizing` · `other`. `mode` decides what it costs:

  | mode | what changes | what the script does | cost |
  |------|--------------|----------------------|------|
  | `sweep` | the **simulation** — each value produces its own trades | loop `combos(SETTINGS)` and pass `variant=combo` | one simulation, sometimes one fetch, per value |
  | `filter` | only **which existing trades count**, by tag | simulate once, tag every trade, declare the tag values each option admits | nothing |

  A filter that is on in the rule must still be simulated **off**: trade every candidate and tag it, or the trades the filter would exclude never exist and turning it off changes nothing. A sweep dimension has no "all" in the panel — pooling a night's 4-ITM trade with its own 8-ITM trade is not a book.
* `main()` wires the CLI: `settings_cli(ap, SETTINGS)` adds one `--<key>` flag per setting, and `settings = narrow(SETTINGS, args)` applies them, so `--moneyness 4,6,8` ships three rungs instead of the whole ladder. **The loops must read the narrowed values**, or a `--flag` silently does nothing.
* **Put `SETTINGS = [...]` after every constant it references**, and if the script uses
  `from py_funcs import (...)` rather than `import *`, add `setting, settings_cli, narrow,
  combos, check_window, START_DATE, END_DATE` to that list.
* **Adding an axis to an existing loop: never re-indent it by hand.** Re-indenting a deep loop
  with a find-and-replace is how a silent backtest bug gets in. Two safe moves:
  * **pair the axis into the loop header** — `for day, pdc in [(d, p) for d in days for p in use_pdc]:` adds an axis with no change to the body at all;
  * or **extract the per-combination body into a function** and drive it from a flat product loop.
* Every trade is built with `make_trade`: for options pass `expiry=contract["expiry"]` (required — it drives the DTE breakdown) and `qty=lots * contract["lot_size"]`; pass `stop`/`target` prices (drawn on the chart), `levels` for anything the rule uses (zones, SMA at the signal, previous-day levels), `mfe`/`mae` from `excursion`, `variant=combo` for the sweep values, `tags={...}` for the group-by conditions **and for anything a filter setting reads**.
* **Log every session**, not only the ones that traded: `log.append(session_row(day, status, note, **facts))` with status `traded` · `declined` · `no signal` · `no data`, and pass `sessions_log=log` to `build_payload`. `facts` become columns of the table in first-seen order — the day's move, the direction, the premium read, the share. With a sweep, the log records what **the rule's own combination** saw; say so in the note when a rung other than the rule's is the one that failed.
* Print every skipped day and why as well: the console list is for whoever runs the script, the session log is for whoever reads the report.
* Finish with:
  ```python
  payload = build_payload(meta, trades, index_sessions, option_sessions, groups,
                          settings=settings, chart="default")
  path = write_report(payload, "<slug>")
  print(console_summary(trades)); print(path)
  ```
  where `groups = [{"name": "SMA10 cross at entry", "keys": ["sma10"]}, {"name": "SMA10 × RSI", "keys": ["sma10", "rsi"]}]` — each `keys` entry names a tag; several keys = a multi-indicator bucket.
  `chart="default"` embeds option candles only for the trades the rule's own settings produce — a 7-rung ladder would otherwise carry seven times the option data for charts nobody opens; other settings still get every metric, just no option chart. `chart="all"` embeds the lot; say so in `meta.limits`.
* `meta`: `title`, `subtitle`, `instrument`, `from`, `to`, `lot_size`, `fill_rule`, `cost_model`, `params`, `rule_steps` (the rule in plain English, one string per step), `limits` (assumptions, "what this is not", the in-sample note from rule 11), `coverage` (from `coverage()`), and optionally `examples` (real nights worked through step by step: a list of `{title, intro, head, rows, open}`, each row one step as `[step, what we look at, the numbers, result]`; the template shows them under the rule as "Real nights, worked through step by step" - first user `onh_v4.py --rule-only`, 2026-10-01), and optionally `rule_sections` (the rule told in parts - each `{title, note, items}` for a numbered list or `{title, note, head, rows}` for a table, a one-cell row being a heading; when present the template shows a "How the rule works" section at the TOP of the page with the examples under it, and hides the flat step list at the bottom).
* **Write for a trader, in the stock's price (the user's standing request, 2026-09-28).** Titles, rule steps, setting labels and options, tag values, group names, session notes and limits use plain words: "the average daily range of the last 14 days (ATR14)", not "ATR14" alone; "above yesterday's high", not "outside the range". Amounts are in the instrument's own price — rupees / points per share — or in % of the price when a share of the price is meant. **Never basis points.** One short sentence per rule step, with a worked number where it helps ("a ₹1,000 share gapping to ₹1,012 is a 1.2% gap").

**What you get without coding any of it** — for the chosen settings and the chosen date range:
overview (trades, **average trades per week** — trades ÷ (trading days in the chosen window ÷ 5), exact for holiday weeks and part-weeks, from `meta.trading_days` which `build_payload` fills and checks — win %, net, gross, costs, profit factor, expectancy, average win/loss, payoff, best/worst, max drawdown with dates, streaks, t-stat, capital, return on capital, hold time, sessions) · equity, drawdown and rolling-20 win-rate series · standard and custom group-by tables · stability (halves, thirds, quarters with date ranges; without the best/worst 10% of trades, rounded up).

**Where those numbers are computed.** The payload carries the *trades*, not a precomputed answer per combination, and the page recomputes the book whenever a dropdown or a date moves — otherwise a free date range would need infinitely many precomputed views. The page's arithmetic is a line-for-line port of `_row` / `_book` / `_series` / `_groups` / `_stability`, and it is **checked**: `build_payload` also computes the same book over every trade as `payload["baseline"]`, the page recomputes it on load, and any disagreement puts a red banner at the top of the report. If you change one side, change the other and re-run — the banner is the test.

**Three zones, and the difference between them is the whole point.** A control that changes
the numbers and a control that changes a picture must not sit next to each other.

| zone | where | what it does | what lives there |
|---|---|---|---|
| **1 · which run** | one flat row under the title | changes **the numbers** — everything below re-renders | the window (free from/to plus a preset list) and one dropdown per `setting()`. `side` appears only when the trades have more than one |
| **2 · view options** | inside the section they belong to | changes **how that one section draws the same trades** | the equity curve's units (rupees / premium % / index %); the trades table's every / wins / losses; the session log's status tabs; the cross-check's bar depth; the group-by picker; the matrix's rows, columns and cell |
| **3 · chart controls** | beside the chart | changes **the picture only** | the session dropdown, *only sessions that traded*, *strategy levels*, *stop / target*, and the zoom buttons |

Zone 1 is deliberately **not banded by `kind`**: at that position a band header only asks the
reader to learn a taxonomy before they can click anything. `kind` still orders the controls
left to right, it just does not draw itself. Each dropdown marks the rule's own value
"← the rule" and carries its `help` as a tooltip, so the row stays a row.

The test for where something belongs: *does changing it change the overview cards?* Yes → zone
1. No, but it changes a table or a curve → zone 2, inside that section. No, it only changes
the chart → zone 3. Putting a chart toggle in zone 1 is the mistake this table exists to stop.

**The report opens on the best combination.** Not on the first value of each setting, and not
on the rule. "Best" is the lowest rank-sum of win rate and net — ranking, because win rate and
rupees share no unit — searched **across the sweeps only**, with filters left where they are,
over a sample floor that steps 20 → 10 → 5 trades. Searching the filters too cuts the book into
slivers: one strategy's "best" came out as a single trade at 100% before that was fixed, and if
nothing clears 5 trades the report names no best at all. The winning row is marked **★ best**,
a *best combination* button returns to it, and the verdict says plainly that it was chosen on
the same data it reports. When a rule is declared, the verdict **also** prints the rule's own
numbers, so opening on the best never hides what the rule did.

**Under it, the verdict** — one quotable paragraph for the settings and window on screen: sessions traded / declined / no signal / unusable, then trades, wins, win rate, gross less costs, net, profit factor, worst, drawdown, losing run, t-stat.

**The page speaks plain words (2026-09-28, the user's request).** The sections below keep their code names here, but the page shows them as: *Every setting compared* (Every setting, side by side) · *What each filter does* (What each condition costs) · *The benchmark* (the control) · *Profit curve, drawdown and recent win rate* · *Every day* (Every session; the statuses read *traded / skipped by the rule / no setup / bad data* for traded / declined / no signal / no data) · *Minute-by-minute check* (the cross-check); MFE / MAE read *best point / worst point*. Keep new wording in the same register.

**Then the sections**, in order: Overview (cards, led by the session counts) · **Every setting, side by side** · **What each condition costs** · Equity, drawdown, rolling win rate · Breakdowns · Stability · Trades and chart · **Every session** · the rule, parameters, limits and *what was tested and left out*.

*What each condition costs* is the analysis a panel exists for. The panel shows the book **with**
a condition on; this shows what switching it on **cost**. Every option of every filter is priced
on its own against the same run with all conditions off, and the two columns that matter are the
deltas — trades given up, and the win-rate points and rupees bought with them. Under it sits **the
control**: what the underlying itself did over those same trades, as it moved and with the signal.
A win rate has to be better than something, and 55% of trades where the index went your way is the
market, not the rule.

*Every setting, side by side* is the "which setting gives the best win rate and return" table: every combination of every dropdown, a full book each over the current window, every column sortable, the rule's own row marked. Clicking a row's first cell loads that combination.

*Every session* is the session log, with a tab per status and the day's net under the current settings, so a declined night and an unusable night are told apart at a glance.

A setting whose other values would need new data is declared `rerun=True`; the panel says so and the *re-run command* button copies the exact command line, from `meta["rerun"]` (filled by `write_report`, or set yourself with `rerun_command()`).

### Step 4 — Run

```
analysis/.venv/Scripts/python.exe analysis/scripts/<category>/<slug>.py
```

(Windows, from the repository root.) It makes no Upstox call. If it ends with a `NOT ON LOCAL DISK` block, show the user that list and ask before fetching anything; with their yes, run exactly those commands from the repository root (token: line 4 of `analysis_rajkumarn/upstox_config.txt`, refreshed with its `upstox_connect.py`) and re-run the script.

### Step 5 — Verify before telling the user it is done

1. The script finished, printed the `console_summary` line, the data size and the report path. `validate_payload` passed (it runs inside `build_payload`), and no `WARNING  setting …` line was printed (those mean a declared setting matches no trade).
2. **Rules check on three trades** (one win, one loss, one time-exit) in the report's *Cross-check* view: the signal candle is complete and earlier than the entry bar; the entry bar is the 1-minute bar right after it; entry price = that bar's high (long) / low (short); exit price = the exit bar's low (long) / high (short); a stop/target exit sits one bar after the bar that touched it.
3. **Counts add up:** sessions in the window, sessions skipped (with reasons), trades.
4. Open the HTML (headless Chrome screenshot is enough): **no red self-check banner at the top**, no console errors, overview populated, the panel opens on the rule, changing a setting and changing the dates both change the numbers, the combination table lists every combination, the chart shows the selected trade.
5. **The panel agrees with the console.** The overview on load (the rule's settings, whole window) must equal the `console_summary` line. If it does not, the defaults are not the rule.
6. **The aspect catalogue, second pass.** Walk it against the finished report and say, in the
   answer to the user, which families this strategy has nothing on and why. Any aspect marked
   *declare* that you skipped is a decision, and it goes in `meta["rejected"]`.
7. **The session log adds up.** *Every session* must hold one row per session in the window, and traded + declined + no signal + no data must equal that total. Every skip the console printed is findable there.
8. Tell the user: the report path, the headline numbers **under the rule**, what the combination table says the best setting was and that it is in-sample, every **assumption**, every **skipped** day with its reason, and — plainly — if the sample is small.

---

## The aspect catalogue

Twenty-four finished strategy reports, reduced to the aspects that kept recurring. **Walk it
twice**: in Step 1b while designing the panel, and again before calling a report done. An
aspect you cannot fill is nearly always a setting, a tag or a `session_row` you forgot to
declare. *free* = the template renders it; *declare* = it renders once the strategy declares
the right thing; *gap* = not in the template, so build it in **for everyone** (rule 18) and
move its row up.

| family | aspect | seen in | status | what it takes |
|---|---|---|---|---|
| **A · the book** | trades, average trades per week, win %, net, gross, costs, PF, expectancy, avg win/loss, payoff, best/worst, max drawdown, streaks, t-stat, capital, RoC, hold | all | free | — |
| | equity, drawdown, rolling win rate | most | free | — |
| | a one-paragraph verdict a reader can quote | some | free | — |
| | sessions traded / declined / no signal / unusable | some | declare | `session_row()` |
| **B · periods** | day-by-day | 13 | free | *Every session* |
| | weekly summary | 19 | free | the `week` group-by |
| | monthly summary | 19 | free | the `month` group-by |
| | weekday, entry hour | common | free | standard group-bys |
| **C · comparing settings** | a net-PnL **matrix**, two settings crossed, shaded, click to load | 17 | free | ≥2 settings with >1 value |
| | every combination as a sortable list | common | free | same |
| | "every timeframe × stop × target", "every side × …" | common | declare | one `setting()` per axis |
| | "the rule on each timeframe", "1 vs 3 vs 5-minute" | common | declare | a timeframe sweep |
| | a strike ladder, every rung on the same sessions | 1 | declare | `setting(kind="strike")` |
| | one threshold in several **shapes** (a share, an absolute, a rank against recent) | 1 | declare | one filter, one option per shape |
| | "do the checks agree?" | 1 | declare | a `groups=` entry over the check tags |
| | **"what each extra filter would cost"** — every condition on its own against the run with all of them off, with the delta in win-rate points and in rupees | 1 | free | declare the conditions as filters |
| **D · stability** | halves, thirds, quarters by trade order | common | free | — |
| | without the best 10% / worst 10% | — | free | — |
| | by year, by calendar half | 3 | free | — |
| | across a named structural break | 2 | declare | `meta["break_date"]` |
| | a free from/to range, and presets | — | free | — |
| **E · charts** | index 1-minute chart, entry and exit marked | 7+ | free | — |
| | the traded contract under the index | some | free | `option_sessions` |
| | strategy levels (zones, swings, the profile, previous-day levels) | 6+ | declare | `levels=[…]` |
| | stop and target lines; zoom, pan, focus | common | free | `stop=`, `target=` |
| | **chart a session that did NOT trade** | 23 | **gap** | see below |
| | per-overlay toggles | 6+ | **gap** | levels draw together |
| **F · audit trail** | trades table, sortable, click to chart | all | free | — |
| | cross-check, minute by minute against the rules | 2 | free | — |
| | every session, traded or not | 3 | declare | `session_row()` |
| | why sessions were skipped, what a condition removed | 2 | declare | `declined` vs `no data` |
| | coverage: sessions, weekday gaps, short sessions | — | free | `coverage()` |
| **G · outcomes** | how the sessions ended | 7 | free | `exit_reason=` |
| | by side, by direction | 2+ | free | `side`, a `direction` tag |
| | by trigger combination | 1 | declare | a multi-key `groups=` |
| | hold time | 1 | free | — |
| **H · instrument** | option type; which expiry priced it | 1+ | free | `expiry=` |
| | liquidity / data by strike | 1 | free | matrix trade counts + `no data` rows |
| | capital per trade, return on capital | — | free | `capital=` |
| **I · honesty** | "what this is not" | 3+ | free | `meta["limits"]` |
| | "what was tested and left out" | 1 | free | `meta["rejected"]` |
| | **fill view** — the same trades at the worst case and at the signal candle (the only two views computed) | all | free | every category; `build_payload` re-prices them (`_price_fills`), `refresh_report` does it from the embedded candles for a report that cannot be re-run; `worst` stays the rule |
| | **the control** — what the underlying itself did over the same trades, as it moved and with the signal | 1 | free | `entry_spot`/`exit_spot`, which `build_payload` fills |
| | cost sensitivity | — | free | gross, costs and net all shown |
| **J · explaining** | the rule in plain English, step by step | most | free | `meta["rule_steps"]` |
| | parameters, fill rule, cost model | most | free | `meta["params"]` |
| | why a threshold's shape matters, worked on real numbers | 1 | **gap** | prose |
| | hand-picked worked examples | 1 | **gap** | prose |

### Known gaps — the honest list

1. **Chart a session that did not trade.** 23 of 24 reports had a day dropdown; the template
   charts only a selected *trade*, and index candles are embedded only for days a trade
   touches. Needs an opt-in that widens what is embedded, with a size budget.
2. **Per-overlay chart toggles.** All `levels` draw at once.
3. **Worked-example prose.** A walk through the rule's arithmetic on two or three real
   sessions. The cross-check proves the fills; it does not explain the idea.

### Pre-flight — answer these before saying a report is done

1. Which families does this strategy have **nothing** on, and is that real or a forgotten
   declaration?
2. Does the panel have two settings with more than one value, so the matrix works?
3. Is every threshold offered in more than one shape, where more than one shape makes sense?
4. Does every session appear in the log, and do the four statuses add to the total?
5. Are the levels the rule actually uses drawn on the chart?
6. Is there a `break_date` worth naming?
7. Does `meta["rejected"]` say what you chose not to make a setting, and why?
8. Did any `WARNING  setting …` line print? None may be left unexplained.

## `py_funcs.py` at a glance

| Need | Call |
|------|------|
| Where the data is | `LOCAL_DATA_DIR` = `analysis/candle_datas`; `missing_local()` / `missing_report()` / `missing_note()` = what this run needed that was not there |
| Several indices | `run_instruments(__file__)`, `instrument()`, `strike_step()`, `price_scale()`, `exchange_of(symbol)`, `INDEX_INSTRUMENTS` — see *Instruments* |
| Token (live calls only) | `read_access_token()` (line 4 of `analysis/upstox_config.txt`), read only when `PYFUNCS_ALLOW_FETCH=1` |
| Instrument key | `await up.find_instrument("NIFTY")`, `("SENSEX")`, `("RELIANCE", "NSE_EQ")` — only names with files on disk |
| Strike step, lot size, expiries on disk | `await up.option_chain_info(key)` (the latest expiry on disk) |
| Expiries | `await up.expiry_calendar(key, frm, to)` (`<NAME>_expiry.json`) |
| Option contract | `await up.resolve_option(key, expiry, strike, "CE"/"PE")` (`<NAME>_contracts.json`) |
| Index/stock candles | `await up.candles(key, "1m"/"1d", frm, to)` → `sessions_from(...)`; `1d` is its own file (`<NAME>_1d_candles.json`) |
| Stock/index 1-minute sessions | `await up.minute_sessions(key, frm, to)` → `{day: rows}` |
| Non-Upstox markets (Asia, US, commodities, FX) | `await yahoo_daily("^N225", frm, to)` → `[[day, o, h, l, c], ...]` in the exchange's own calendar, or `None` when Yahoo is unreachable or live calls are off (say so) |
| Several stocks in one report | `option_sessions={symbol: {day: rows}}` + `meta["index_label"]`; still points per share (see *Categories*) |
| Option bars for a day | `await up.option_candles(contract, day)` |
| Strike maths | `atm_strike`, `strike_offset(spot, step, n, "CE", itm=True)`, `next_expiry` |
| Bars | `bar_at`, `resample(rows, minutes)` |
| **Rules** | `bar_after_candle`, `worst_fills`, `scan_exit`, `candle_done_at` |
| Indicators | `sma`, `ema`, `rsi`, `atr`, `crossed_above`, `crossed_below`, `bucket` |
| Category facts | `CATEGORIES`, `category_of(key)`, `script_category()` |
| Costs | `trade_costs(category, side, entry, exit, qty, day)`; underneath: `option_costs`, `option_round_trip`, `equity_intraday_costs`, `equity_round_trip` (all take `day=`) |
| Broker check | `await broker_check(up, category, key, qty, price)` — model vs Upstox's own charges |
| Broker margin | `await broker_margin(up, key, qty, price, side, product)`, `await broker_margin_ratio(up, key, qty, price)` |
| Stock F&O lot size on a day (options work only — intraday stocks trade 1 share) | `await up.future_contract(stock_key, day)` → `lot_size` of the near-month future (a live call: only with the user's permission) |
| Pre-open auction entry (rule 1 exception, **not for intraday stocks**) | `preopen_fill(rows_1m)` → the 09:15 bar's open |
| Trades and report | `make_trade`, `excursion`, `build_payload`, `write_report`, `console_summary`, `coverage` |
| Control panel | `setting`, `combos`, `default_combo`, `settings_cli`, `narrow`, `rerun_command` |
| Session log | `session_row(day, status, note, **facts)` |
| Window guard | `check_window(frm, to)` — refuses anything outside START_DATE .. END_DATE |
| Request budget | `fetch_estimate(n)` — print it before a ladder starts (with live calls off it says the reads are local) |

Upstox facts (the one-month cap per minute request, expired contracts' dated keys and their own candles endpoint, rate limits and pacing) are handled by `analysis_rajkumarn/fetch_candles.py` when the user allows a fetch — see its `fetch.md`. A strategy run makes no request; `up.calls` stays 0. The last 32 option contracts read are kept in memory (a trade reads its contract on the entry day and the exit day).

**Memory.** Do not accumulate option candles for a sweep value you will not chart. `build_payload(chart="default")` drops them anyway, but holding a seven-rung ladder first cost 365 MB; collect only the rung `default_combo(settings)` names.

## How `sample.html` is used on each run

* `sample.html` is **never modified by a backtest**. `write_report()` reads it as text, replaces what sits between `/*DATA_START*/` and `/*DATA_END*/` with the run's data, and writes the result to `analysis/report/<category>/<name>.html`.
* Those markers are on the **last line** of the file, inside the final `<script>main(/*DATA_START*/{...}/*DATA_END*/);</script>`. Everything above it is the report code, wrapped in `function main(DATA) {...}`. **To change the report, edit the code above that last script and never touch the data line.** Keep exactly one pair of markers.
* Whatever data the template holds (empty, or the synthetic demo) is what you see when you open `sample.html` directly. To refresh the demo after editing the template, call `write_report(payload, <path of sample.html>)` with any payload.
