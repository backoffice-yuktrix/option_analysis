# PRD: Options Movement Analysis Tool
**Version:** 3.2  
**Status:** Draft  
**Purpose:** Two analytical modules added to the existing app for studying how Nifty/BankNifty option prices respond to intraday swing moves (M1) and overnight gap moves (M2), across strikes, expiries, and time checkpoints.

---

## Table of Contents
1. [Background & Goal](#1-background--goal)
2. [Shared Infrastructure — Upstox Integration](#2-shared-infrastructure--upstox-integration)
3. [Shared Concepts & Definitions](#3-shared-concepts--definitions)
4. [Module 1 — Intraday Swing Analysis (`/module1`)](#4-module-1--intraday-swing-analysis-module1)
5. [Module 2 — Overnight Gap Analysis (`/module2`)](#5-module-2--overnight-gap-analysis-module2)
6. [Data Requirements](#6-data-requirements)
7. [Out of Scope (v1)](#7-out-of-scope-v1)

---

## 1. Background & Goal

The user wants to empirically understand — from historical data — **how option prices at various strikes and expiries respond to Nifty/BankNifty movement**, both intraday and overnight. The primary analytical lens is P&L: *if I held a strike at the start of a move, what happened to its price at 20%, 40%, 60%, 80%, and 100% through the move?*

Two modules:
- **M1 (`/module1`):** Intraday swing legs detected via ATR-based reversal, analysed at time-proportional checkpoints within each leg
- **M2 (`/module2`):** Overnight sessions (3:15 PM entry → 9:25 AM exit), same strike and metric framework

---

## 2. Shared Infrastructure — Upstox Integration

Applies to both `/module1` and `/module2`.

### 2.1 Upstox Account Button (top-right, both pages)

**State 1 — No credentials saved:**
- Button: **"Add Upstox Account"**
- On click: modal/popup collects:
  - Redirect URL
  - API Key
  - API Secret
- On save: write to `upstox_config.txt` (local file on server). Transition to State 2.

**State 2 — Credentials saved, not yet connected:**
- Button: **"Connect to Upstox"**
- On click: redirect to Upstox OAuth flow
- On successful OAuth callback: write access token to session. Transition to State 3.

**State 3 — Connected:**
- Button: **"Upstox Connected"** (static label, or with a small disconnect option)
- Access token available for all data fetch calls in this session

**Persistence:** `upstox_config.txt` is read on every server start and page load. Credentials never need re-entry after first save. Access token is session-only (re-OAuth on next session).

---

## 3. Shared Concepts & Definitions

### 3.1 Expiry Selection Input

Both modules include an **Expiry Count** input field:

| Field | Type | Default | Description |
|---|---|---|---|
| Expiry Count | Number input | 2 | How many upcoming expiries to include in analysis (1, 2, 3, ...) |

**Resolution logic at T₀ (for any leg or session):**
- Identify all available expiry dates for the instrument from T₀ onwards, sorted ascending
- Take the first N expiries where N = Expiry Count
- Example: Trade date = Monday 1st, weekly expiries = 4th, 11th, 18th, 25th
  - Expiry Count = 1 → only 4th
  - Expiry Count = 2 → 4th and 11th
  - Expiry Count = 3 → 4th, 11th, 18th

**All N expiries are computed in the backend** for every leg/session. The expiry selection only controls which columns appear in the **default column set** in the frontend — all computed data is always stored in the result JSON.

### 3.2 Default Expiry for Display

When rendering default columns (before user customises), use this rule to pick which expiry to show:
- Rank expiries 1st, 2nd, 3rd... (nearest first)
- **Default = 2nd expiry** if it exists, else fall back to 1st expiry
- Example: Trade date = Monday 1st, Expiry Count = 2 → expiries are 4th (1st) and 11th (2nd) → **default display = 11th**
- Example: Trade date = Wednesday 3rd (1 day before expiry 4th), Expiry Count = 1 → only 4th available → **default display = 4th**

This ensures the default view avoids very short-dated (expiry-day-risk) options while still showing a nearby contract.

### 3.3 Strike Grid

At T₀ for any leg or session:
- **ATM** = nearest strike to the instrument's spot price at T₀
- **pts_to_analyse** = user-defined strike interval (default: 100)
- **option_range** = number of strikes above and below ATM (default: 3)
- **Strike grid** = ATM ± (k × pts_to_analyse) for k = 1 to option_range, plus ATM itself

Example: `pts_to_analyse = 100`, `option_range = 3`
```
ATM−300, ATM−200, ATM−100, ATM, ATM+100, ATM+200, ATM+300
```
Total = (2 × option_range + 1) strikes = 7. For each strike: both **Call** and **Put**.

Strike labels are always relative (ATM−3, ATM−2, ATM−1, ATM, ATM+1, ATM+2, ATM+3) so comparisons across different dates are normalised, regardless of absolute strike levels.

### 3.4 Along vs Against

Each leg or session has a direction. Options are tagged accordingly:

| Direction | Along (profits if move continues) | Against |
|---|---|---|
| Hill / Gap Up | Call | Put |
| Valley / Gap Down | Put | Call |

### 3.5 Cheapest Along Option

- Hill / Gap Up: Along = Calls → cheapest Along = **ATM + (option_range × pts_to_analyse)** (most OTM call in grid)
- Valley / Gap Down: Along = Puts → cheapest Along = **ATM − (option_range × pts_to_analyse)** (most OTM put in grid)

Used as the reference strike for `percent_optimal_option` and `profit_percent_optimal_option`.

### 3.6 Option Price Candle Rule

Option prices sourced from **1-minute OHLC candles**:
- **Entry / any buy price** (at T₀ or any checkpoint): use candle **High** (worst-case fill)
- **Exit / any sell price** (at T₁ or 100% checkpoint): use candle **Low** (worst-case fill)

### 3.7 Time Checkpoints (M1 only)

For any M1 leg from T₀ to T₁:

| Label | Time offset | Formula |
|---|---|---|
| 0% | Start | T₀ |
| 20% | CP1 | T₀ + 0.20 × (T₁ − T₀) |
| 40% | CP2 | T₀ + 0.40 × (T₁ − T₀) |
| 60% | CP3 | T₀ + 0.60 × (T₁ − T₀) |
| 80% | CP4 | T₀ + 0.80 × (T₁ − T₀) |
| 100% | CP5 | T₁ |

At each checkpoint: snap to closest available 1-min candle for both instrument price and option prices.

**Instrument price field:** use candle `close` at each checkpoint. The High/Low candle rule (§3.6) applies to option prices only, not to the instrument spot observation.

### 3.8 Computed Metrics

Applied to the **cheapest Along option** at each leg/session:

```
percent_optimal_option        = abs(price_at_0% − price_at_100%) / price_at_0%
profit_percent_optimal_option = abs(price_at_20% − price_at_80%) / price_at_20%
```

Both expressed as a percentage.

> For M2 (no intermediate checkpoints): 20% ≡ 0% and 80% ≡ 100%, so both metrics resolve to the same value = `abs(T₁ price − T₀ price) / T₀ price`.

### 3.9 Result Persistence

Each Run saves its full output as a **JSON file** on the server with a timestamp in the filename:
```
results_module1_<YYYYMMDD_HHMMSS>.json
results_module2_<YYYYMMDD_HHMMSS>.json
```

The JSON contains **all computed data** for all strikes, all expiries (up to Expiry Count), all checkpoints, all metrics — regardless of what columns are currently visible in the UI. The frontend filters/shows columns from this data; it does not re-fetch.

The `run_id` (`YYYYMMDD_HHMMSS`) is included in every API response so the frontend can reference or share the result.

**Loading a previous run (implemented):**
- API endpoint: `GET /api/module1/results/{run_id}` — reads the saved JSON and returns it as a full `Module1Result`
- Browser URL: `/module1/{run_id}` — navigating to this URL loads the saved result, pre-fills the input panel with the original params, and renders the chart and tables exactly as if the run had just completed. The user can then modify params and hit Run again.
- `run_id` format is validated server-side (`results_module1_YYYYMMDD_HHMMSS`) to prevent path traversal.

### 3.10 DTE Buckets

| Bucket Label | DTE Range |
|---|---|
| Expiry Day | 0 |
| 1 DTE | 1 |
| 2 DTE | 2 |
| Near | 3–5 |
| Short | 6–10 |
| Mid | 11–20 |
| Far | 21+ |

DTE = number of trading days from T₀ to the contract's expiry date.

**Implementation note:** DTE is computed by counting Mon–Fri weekdays between T₀ and expiry. NSE market holidays are not separately modelled (holiday-adjusted DTE is out of scope for v1).

---

## 4. Module 1 — Intraday Swing Analysis (`/module1`)

### 4.1 Overview

Detect significant intraday swing legs (Valley→Hill or Hill→Valley) in Nifty/BankNifty using an ATR-based reversal detector. For each qualifying leg (magnitude ≥ `pts_to_analyse`), record instrument and option prices at 6 time-proportional checkpoints (0%, 20%, 40%, 60%, 80%, 100%) within the leg's actual duration. Present a candlestick chart with annotated swings, a configurable trade table (5A), and summary stats (5B).

---

### 4.2 User Input Panel

| Field | Type | Default | Notes |
|---|---|---|---|
| Instrument | Dropdown | NIFTY | Options: NIFTY, BANKNIFTY |
| From Date | Date picker | — | Start of historical range |
| To Date | Date picker | — | End of historical range |
| pts_to_analyse | Number input | 100 | Minimum leg magnitude; also the strike interval |
| option_range | Number input | 3 | Strikes above and below ATM |
| Expiry Count | Number input | 2 | Number of upcoming expiries to compute (see §3.1) |
| ATR Config | Expandable section | (see §4.3) | Click to expand inline |
| **Run** | Button | — | Triggers backend processing |

---

### 4.3 ATR Configuration Panel

Collapsed by default. Expands inline on click.

| Parameter | Default | Description |
|---|---|---|
| ATR Period | 14 | Lookback candles for ATR computation |
| ATR Multiplier | 2.0 | Reversal threshold = ATR × Multiplier. Higher = fewer, larger swings detected |
| Candle Timeframe | 15min | OHLC resolution for ATR and swing detection. Options: 5min, 15min, 30min |
| Price Source | Close | OHLC field used for ATR. Options: Close, High/Low |

**Default rationale:** ATR(14) × 2.0 on 15min Close is well-suited for detecting meaningful intraday reversals in Nifty/BankNifty without overreacting to noise. ATR Multiplier is the primary sensitivity knob.

---

### 4.4 Backend Processing Logic

Triggered on Run:

**Step 1 — Fetch & compute ATR**
- Fetch instrument OHLC for selected date range at configured candle timeframe
- Compute ATR(period) using configured price source

**Step 2 — Detect swing points**
- Apply ATR × Multiplier as the reversal threshold
- Output: alternating sequence of `{ timestamp, price, type: Hill | Valley }`
- Swings must strictly alternate (no two consecutive Hills or Valleys)

**Step 3 — Day boundary enforcement**
- At 3:15 PM each day: if a swing leg is still open (no reversal yet), force-close it with T₁ = 3:15 PM candle
- The forced-close leg is included in analysis (not discarded), with T₁ = 3:15 PM price
- Next day begins fresh — the first detected swing point of each new trading day starts a new leg sequence
- **Implementation note:** Upstox candle timestamps are IST (`+05:30`). The 3:15 PM IST candle is identified by converting to UTC and checking `(hour, minute) == (9, 45)`. Consecutive swing-point pairs whose dates differ are excluded from leg building — the force-close point ends day N's sequence and is never paired with day N+1's first point.

**Step 4 — Leg qualification**
- For each Valley→Hill or Hill→Valley pair, compute magnitude = |end price − start price|
- If magnitude < `pts_to_analyse`: skip entirely (record as filtered, not shown in table)
- If magnitude ≥ `pts_to_analyse`: qualify for analysis

**Step 5 — Checkpoint computation**
- T₀ = swing start timestamp, T₁ = swing end timestamp (or forced 3:15 PM)
- Compute 6 timestamps: 0%, 20%, 40%, 60%, 80%, 100% of (T₁ − T₀)
- Snap each to closest available 1-min candle

**Step 6 — Option data fetch**
- At each of the 6 checkpoint timestamps, fetch 1-min option candles for:
  - All strikes in the grid (ATM ± option_range)
  - All expiries up to Expiry Count, from T₀
  - Both Call and Put for each strike/expiry combination
- Apply candle rule: High for 0%/20%/40%/60%/80% (entry/holding), Low for 100% (exit)

**Step 7 — Metric computation**
- Tag each option as Along or Against based on leg direction (§3.4)
- Identify cheapest Along option (§3.5)
- Compute `percent_optimal_option` and `profit_percent_optimal_option` (§3.8) per leg

**Step 8 — Save result JSON & return response**
- Persist full result to timestamped JSON file (§3.9)
- The API response (`Module1Result`) includes:

| Field | Description |
|---|---|
| `instrument`, `from_date`, `to_date`, `pts_to_analyse`, `option_range`, `expiry_count`, `atr` | Echo of input params |
| `run_id` | `YYYYMMDD_HHMMSS` identifier; also used in the saved filename and load URL (§3.9) |
| `legs` | Qualifying leg rows (see §4.6 for schema) |
| `non_qualifying_legs` | Legs with magnitude < pts_to_analyse — included for chart grey-connector overlay only, not shown in the table |
| `swing_points` | All detected Hill/Valley swing points — included for chart marker overlay |
| `chart_candles` | Instrument OHLC at the configured ATR candle timeframe — used to render the candlestick chart |
| `column_meta` | `{ column_key: { label, group, exp_n, strike_label, side, pct } }` — metadata for the frontend column picker |

---

### 4.5 Instrument Chart

Displayed between the input panel and the trade table.

- **Candlestick chart** of the instrument over the selected date range, at the ATR candle timeframe
- All detected **swing points plotted:**
  - Hill: downward triangle (▼) above the candle high
  - Valley: upward triangle (▲) below the candle low
- **Qualifying legs** (≥ pts_to_analyse): connector line between Valley and Hill
  - Up leg (Valley→Hill): green line
  - Down leg (Hill→Valley): red line
- **Non-qualifying legs** (< pts_to_analyse): grey connector, no fill
- Clicking a leg connector on the chart scrolls to that row in the 5A table and highlights it

---

### 4.6 Trade Table — 5A (Individual Legs)

#### Must-have Columns (always shown, not removable)

| Column | Description |
|---|---|
| Date | Calendar date of T₀ (leg start) |
| Start Time | T₀ time (HH:MM IST) |
| End Time | T₁ time (HH:MM IST) — actual reversal or forced 3:15 PM |
| Type | `Hill` (up move) or `Valley` (down move) |
| VIX | India VIX daily close value at T₀ date |
| Abs Pts | \|end price − start price\| |
| Start Price | Instrument spot at T₀ |
| End Price | Instrument spot at T₁ |

**`LegRow` schema note:** The response also carries `end_date` (calendar date of T₁). After day-boundary enforcement, `end_date` always equals `date` for qualifying legs (all legs are within a single trading day). It is included in the schema to allow the chart to reconstruct exact timestamps for connector lines without ambiguity.

#### Custom Columns (column picker)

A panel listing all available columns with checkboxes. Grouped as follows:

---

**Group A — Instrument checkpoints**

| Column key | Description |
|---|---|
| `instr_20pct` | Instrument spot at 20% checkpoint |
| `instr_40pct` | Instrument spot at 40% checkpoint |
| `instr_60pct` | Instrument spot at 60% checkpoint |
| `instr_80pct` | Instrument spot at 80% checkpoint |

*(0% = Start Price and 100% = End Price are already must-have columns)*

---

**Group B — Along options**

For each expiry (Expiry 1, Expiry 2, ... up to Expiry Count), for each strike (ATM−range ... ATM ... ATM+range), for each checkpoint (0%, 20%, 40%, 60%, 80%, 100%):

Column key format: `along_exp{N}_{strike_label}_{pct}pct`

Example columns (Expiry Count=2, option_range=3, pts_to_analyse=100):
```
along_exp1_ATMm3_0pct   along_exp1_ATMm3_20pct  ... along_exp1_ATMm3_100pct
along_exp1_ATMm2_0pct   ...
...
along_exp1_ATM_0pct     ...
...
along_exp1_ATMp3_0pct   ...
along_exp2_ATMm3_0pct   ...   (repeated for 2nd expiry)
...
```

Strike order in picker: ATM−range first, ascending to ATM+range.

---

**Group C — Against options**

Same structure as Group B, prefix `against_` instead of `along_`.

---

**Group D — Metrics**

| Column key | Description |
|---|---|
| `percent_optimal_option` | `abs(0% price − 100% price) / 0% price` on cheapest Along |
| `profit_percent_optimal_option` | `abs(20% price − 80% price) / 20% price` on cheapest Along |

---

#### Default Column Set (on first load / before user customises)

Using the **default expiry** (2nd expiry if available, else 1st — see §3.2) and **cheapest Along option**:

| Column | Notes |
|---|---|
| Date, Start Time, End Time, Type, Abs Pts, Start Price, End Price | Must-have |
| `instr_20pct` | 20% instrument value |
| `instr_80pct` | 80% instrument value |
| `along_exp{default}_cheapest_0pct` | Along cheapest option at entry |
| `along_exp{default}_cheapest_20pct` | Along cheapest option at 20% |
| `along_exp{default}_cheapest_80pct` | Along cheapest option at 80% |
| `along_exp{default}_cheapest_100pct` | Along cheapest option at exit |
| `profit_percent_optimal_option` | Summary metric |

---

### 4.7 Summary Table — 5B

Separate tab or section. Three sub-views:

#### Day-wise

| Column | Description |
|---|---|
| Date | Calendar date |
| Total Trades | Qualifying legs that day |
| Total profit_percent_optimal_option | Sum across legs |
| Avg profit_percent_optimal_option | Mean across legs |

#### Week-wise

| Column | Description |
|---|---|
| Week (start date) | Monday of that week |
| Total Trades | Qualifying legs that week |
| Total profit_percent_optimal_option | Sum |
| Avg profit_percent_optimal_option | Mean |

#### Overall

| Metric | Value |
|---|---|
| Total Trades | All qualifying legs in date range |
| Total profit_percent_optimal_option | Sum |
| Avg profit_percent_optimal_option | Mean |
| Best Day | Date with highest avg profit_percent_optimal_option |
| Worst Day | Date with lowest avg profit_percent_optimal_option |

---

## 5. Module 2 — Overnight Gap Analysis (`/module2`)

### 5.1 Overview

For every trading session in the selected date range, treat **3:15 PM as entry (T₀)** and **9:25 AM the next trading day as exit (T₁)**. No ATR detection. Every eligible overnight session is a trade. Same strike grid, expiry logic, along/against framework, and metric computation as M1.

---

### 5.2 User Input Panel

| Field | Type | Default | Notes |
|---|---|---|---|
| Instrument | Dropdown | NIFTY | Options: NIFTY, BANKNIFTY |
| From Date | Date picker | — | |
| To Date | Date picker | — | |
| pts_to_analyse | Number input | 100 | Strike interval only (no leg magnitude filtering in M2) |
| option_range | Number input | 3 | Strikes above and below ATM |
| Expiry Count | Number input | 2 | Number of upcoming expiries to compute |
| **Run** | Button | — | Triggers backend processing |

No ATR config for M2.

---

### 5.3 Session Eligibility

For each trading day D in the selected range:
- **T₀** = 3:15 PM candle on day D
- **T₁** = 9:25 AM candle on the **next calendar trading day** (skip weekends and market holidays)
- **Skip the session entirely** if T₁'s day does not open at normal market time (e.g. delayed opening, no data at 9:25 AM) — do not include, do not flag
- Sessions spanning a weekend (Friday → Monday) or a single market holiday are included as normal — no special treatment or separate flagging

---

### 5.4 Backend Processing Logic

**Step 1 — Fetch instrument 1-min data** for selected date range

**Step 2 — Build session list**
- For each eligible day D (per §5.3): record T₀ = 3:15 PM, T₁ = 9:25 AM next trading day
- Skip sessions where T₁ candle is unavailable

**Step 3 — For each session:**
- Compute overnight move = T₁ instrument price − T₀ instrument price (signed)
- Determine direction: Gap Up (positive) or Gap Down (negative)
- Compute ATM at T₀, build strike grid
- Resolve N expiries from T₀ (§3.1)
- Fetch 1-min option candles at T₀ and T₁ for all strikes × all expiries
- Apply candle rule: T₀ = High (entry), T₁ = Low (exit)
- Tag Along / Against (§3.4), identify cheapest Along (§3.5)
- Compute DTE for each expiry at T₀
- Compute `percent_optimal_option` and `profit_percent_optimal_option` (§3.8)

**Step 4 — Save** full result to timestamped JSON (§3.9)

---

### 5.5 Trade Table — 5A (Individual Sessions)

#### Must-have Columns

| Column | Description |
|---|---|
| Date | Entry date (Day D) |
| Entry Time | 3:15 PM |
| Exit Time | 9:25 AM day D+1 |
| Gap Pts | T₁ price − T₀ price (signed) |
| Gap Direction | Gap Up / Gap Down |
| VIX | India VIX daily close value at T₀ date |
| Start Price | Instrument at T₀ |
| End Price | Instrument at T₁ |

#### Custom Columns (column picker, same UI as M1)

**Group B — Along options**
For each expiry (1..N), for each strike (ATM−range..ATM+range):
- `along_exp{N}_{strike_label}_0pct` — T₀ price (entry)
- `along_exp{N}_{strike_label}_100pct` — T₁ price (exit)

**Group C — Against options**
Same structure as Group B, prefix `against_`.

**Group D — DTE**
`dte_exp{N}` — trading days from T₀ to expiry N

**Group E — Metrics**
- `percent_optimal_option`
- `profit_percent_optimal_option`

#### Default Column Set

| Column |
|---|
| Date, Entry Time, Exit Time, Gap Pts, Gap Direction, Start Price, End Price |
| `along_exp{default}_cheapest_0pct` |
| `along_exp{default}_cheapest_100pct` |
| `dte_exp{default}` |
| `profit_percent_optimal_option` |

*(Default expiry = 2nd if available, else 1st — §3.2)*

---

### 5.6 Summary Table — 5B

Same three sub-views as M1 (§4.7): Day-wise, Week-wise, Overall.

Additionally, in the **Overall** section, include a **Gap Size breakdown**:

| Gap Bucket | Session Count | Avg profit_percent_optimal_option |
|---|---|---|
| 0–25 pts | | |
| 25–50 pts | | |
| 50–100 pts | | |
| 100+ pts | | |

---

## 6. Data Requirements

Already available in the existing app:
- Instrument OHLC at 1-min and multi-minute timeframes (5min, 15min, 30min)
- Historical options 1-min OHLC for all strikes and expiries

New processing this PRD introduces:

| Requirement | Module |
|---|---|
| ATR computation on instrument OHLC | M1 |
| ATR-based alternating Hill/Valley swing detection | M1 |
| Day boundary force-close at 3:15 PM | M1 |
| Leg magnitude filtering (skip < pts_to_analyse) | M1 |
| Time-proportional checkpoint computation (0/20/40/60/80/100%) | M1 |
| Overnight session pairing (3:15 PM → 9:25 AM next trading day) | M2 |
| Session skip when T₁ 9:25 AM candle unavailable | M2 |
| Expiry resolution: N nearest expiries from T₀ | Both |
| Default expiry selection (2nd if available, else 1st) | Both (frontend) |
| ATM computation at T₀ per leg/session | Both |
| India VIX daily close fetch & tag at T₀ date | Both |
| Strike grid generation (ATM ± option_range × pts_to_analyse) | Both |
| Along/Against tagging per direction | Both |
| Cheapest Along identification | Both |
| Option price fetch at checkpoints with High/Low candle rule | Both |
| percent_optimal_option + profit_percent_optimal_option | Both |
| Full result saved as timestamped JSON per Run | Both |
| Upstox credential read/write (upstox_config.txt) | Both |
| Upstox OAuth flow + session token management | Both |

---

## 7. Out of Scope (v1)

- IV / Greeks (Delta, Gamma, Vega, Theta)
- Strategy P&L (Straddle, Strangle, Spreads, Hedging)
- Live / real-time data — historical analysis only
- Lot size, margin, or brokerage in P&L
- Alerts or notifications
- Instruments beyond NIFTY and BANKNIFTY
- Annotating or tagging individual legs
- Reloading past run JSONs from the UI (files saved to disk; loading is manual for v1)
- Bidirectional chart ↔ table linking (chart click scrolls to table row, but table row click does not highlight chart)

---

## 8. UI Page Structure

High-level layout for both pages. Both share the same structural pattern; M2 omits the ATR config and chart sections.

---

### 8.1 `/module1` — Page Layout

```
┌─────────────────────────────────────────────────────────────┐
│  [Module 1 Title]                   [Upstox Button — top right] │
├─────────────────────────────────────────────────────────────┤
│  INPUT PANEL                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │Instrument│ │From Date │ │ To Date  │ │pts_to_   │       │
│  │ dropdown │ │ picker   │ │ picker   │ │ analyse  │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ┌──────────┐ ┌──────────┐                                  │
│  │option_   │ │Expiry    │                                  │
│  │ range    │ │ Count    │                                  │
│  └──────────┘ └──────────┘                                  │
│  [▶ ATR Config]  ← collapsible, expands inline below        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ ATR Period | ATR Multiplier | Candle TF | Price Src  │    │
│  │ (collapsed by default)                               │    │
│  └─────────────────────────────────────────────────────┘    │
│                                          [ Run ▶ ]          │
├─────────────────────────────────────────────────────────────┤
│  CHART                                                       │
│  Instrument candlestick chart for selected date range        │
│  • ▲ Valley markers (below candle), ▼ Hill markers (above)  │
│  • Qualifying legs: green (up) / red (down) connector lines  │
│  • Non-qualifying legs: grey connector                       │
│  • Click leg → scrolls to + highlights that row in 5A table │
├─────────────────────────────────────────────────────────────┤
│  SECTION 5A — TRADE TABLE                                    │
│  [Column Picker ▼]  ← dropdown/panel with checkboxes        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Columns grouped:                                      │   │
│  │  A. Instrument checkpoints (20%, 40%, 60%, 80%)       │   │
│  │  B. Along options  [Exp1] [Exp2]  ATM-3 … ATM+3       │   │
│  │     per strike: 0%, 20%, 40%, 60%, 80%, 100%          │   │
│  │  C. Against options (same structure)                   │   │
│  │  D. Metrics: percent_optimal, profit_percent_optimal   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  TABLE (horizontal scroll for wide column sets)             │
│  ┌────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐   │
│  │Date│Start │ End  │ Type │ VIX  │Abs Pt│Start │ End  │... │   │
│  │    │ Time │ Time │H / V │      │Price │Price │custom│   │
│  ├────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┤   │
│  │    │      │      │      │      │      │      │      │   │
│  └────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘   │
├─────────────────────────────────────────────────────────────┤
│  SECTION 5B — SUMMARY                                        │
│  [Day-wise] [Week-wise] [Overall]  ← tabs                   │
│                                                              │
│  Day-wise tab:                                               │
│  ┌──────────┬─────────────┬────────────────┬─────────────┐  │
│  │   Date   │Total Trades │ Total profit%  │  Avg profit%│  │
│  └──────────┴─────────────┴────────────────┴─────────────┘  │
│                                                              │
│  Week-wise tab: same columns, grouped by week               │
│                                                              │
│  Overall tab: single summary row + best/worst day           │
└─────────────────────────────────────────────────────────────┘
```

---

### 8.2 Upstox Button States (top-right, both pages)

```
State 1 — No credentials:
  [ + Add Upstox Account ]
        ↓ click
  ┌─────────────────────────────┐
  │  Redirect URL  [__________] │
  │  API Key       [__________] │
  │  API Secret    [__________] │
  │              [Cancel] [Save]│
  └─────────────────────────────┘
        ↓ save → writes upstox_config.txt

State 2 — Credentials saved:
  [ Connect to Upstox ]
        ↓ click → redirect to Upstox OAuth

State 3 — OAuth complete:
  [ ✓ Upstox Connected ]
```

---

### 8.3 ATR Config — Expanded State

```
[▼ ATR Config]
┌──────────────────────────────────────────────────────────┐
│  ATR Period      [  14  ]                                 │
│  ATR Multiplier  [ 2.0  ]                                 │
│  Candle TF       [ 15min ▼]  (5min / 15min / 30min)      │
│  Price Source    [ Close ▼]  (Close / High-Low)           │
└──────────────────────────────────────────────────────────┘
```

---

### 8.4 Column Picker — Structure

```
[Column Picker ▼]
┌──────────────────────────────────────────────────────────┐
│  ▶ Group A — Instrument Checkpoints                       │
│    ☑ 20%   ☑ 40%   ☐ 60%   ☑ 80%                        │
│                                                           │
│  ▶ Group B — Along Options                               │
│    Expiry 1 (e.g. 4th Aug)   Expiry 2 (e.g. 11th Aug)   │
│    Strike   0% 20% 40% 60% 80% 100%                      │
│    ATM-3    ☐  ☐   ☐   ☐   ☐   ☐                         │
│    ATM-2    ☐  ☐   ☐   ☐   ☐   ☐                         │
│    ATM-1    ☐  ☐   ☐   ☐   ☐   ☐                         │
│    ATM      ☐  ☐   ☐   ☐   ☐   ☐                         │
│    ATM+1    ☐  ☐   ☐   ☐   ☐   ☐                         │
│    ATM+2    ☐  ☐   ☐   ☐   ☐   ☐                         │
│    ATM+3    ☑  ☑   ☐   ☐   ☑   ☑   ← default cheapest   │
│                                                           │
│  ▶ Group C — Against Options  (same grid structure)      │
│                                                           │
│  ▶ Group D — Metrics                                     │
│    ☐ percent_optimal_option                              │
│    ☑ profit_percent_optimal_option                       │
└──────────────────────────────────────────────────────────┘
```

Default checked state on first load = the default column set defined in §4.6.

---

### 8.5 `/module2` — Page Layout

Same overall structure as `/module1` with two differences:

1. **No ATR Config section** — removed entirely
2. **No Chart section** — removed entirely

```
┌─────────────────────────────────────────────────────────────┐
│  [Module 2 Title]                   [Upstox Button]          │
├─────────────────────────────────────────────────────────────┤
│  INPUT PANEL                                                 │
│  Instrument | From Date | To Date | pts_to_analyse           │
│  option_range | Expiry Count                                 │
│                                          [ Run ▶ ]          │
├─────────────────────────────────────────────────────────────┤
│  SECTION 5A — TRADE TABLE                                    │
│  [Column Picker ▼]                                           │
│                                                              │
│  TABLE                                                       │
│  Date | Entry | Exit | Gap Pts | Direction | VIX | Start | End │
│  + custom columns (Along/Against @ 0% and 100%, DTE, metrics)│
├─────────────────────────────────────────────────────────────┤
│  SECTION 5B — SUMMARY                                        │
│  [Day-wise] [Week-wise] [Overall + Gap Breakdown]  ← tabs   │
└─────────────────────────────────────────────────────────────┘
```

The column picker for M2 follows the same group structure (B, C, D, E) as M1 but with only 0% and 100% checkpoints (no intermediate checkpoints in M2).
