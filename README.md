# Options Movement Analysis Tool

Standalone analytics tool for studying how NIFTY/BANKNIFTY option prices respond to intraday swing moves (M1) and overnight gap moves (M2).

**No login. No database. Just backend + frontend + Upstox API.**

---

## Project Structure

```
option_analysis/
├── backend/          FastAPI app (Python)
├── frontend/         React + Vite + Tailwind app
├── README.md         This file
└── WorkItems.md      Design decisions and reuse map
```

---

## Prerequisites

- Python 3.11+
- Node.js 20+
- An active Upstox developer app ([https://developer.upstox.com](https://developer.upstox.com))

---

## Backend Setup

```bash
cd option_analysis/backend

# Create venv
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy env file (edit as needed)
cp .env.example .env

# Run
python main.py
# or
uvicorn main:app --reload --port 8000
```

Backend runs at **http://localhost:8000**  
API docs at **http://localhost:8000/docs**

---

## Frontend Setup

```bash
cd option_analysis/frontend

npm install

npm run dev
```

Frontend runs at **http://localhost:5173**  
API calls to `/api/*` are proxied to `http://localhost:8000` by Vite.

---

## Upstox Configuration

### Step 1 — Create an Upstox API App

1. Go to [https://developer.upstox.com](https://developer.upstox.com)
2. Create a new app
3. Set the redirect URI to: `http://localhost:5173/oauth/callback`
4. Note your **API Key** and **API Secret**

### Step 2 — Add Credentials in the UI

1. Open the app at `http://localhost:5173`
2. Click **"Add Upstox Account"** (top-right corner)
3. Enter:
   - API Key
   - API Secret
   - Redirect URL: `http://localhost:5173/oauth/callback`
4. Click **Save** — credentials are written to `backend/upstox_config.txt`

### Step 3 — Connect

1. Click **"Connect to Upstox"**
2. You will be redirected to Upstox OAuth
3. After login, you are redirected back to `/oauth/callback`
4. The app exchanges the code for an access token automatically
5. Button changes to **"✓ Upstox Connected"**

> **Note:** The access token is stored in-memory on the backend. It is lost on server restart — reconnect via Step 3.

---

## Usage

### Module 1 — Intraday Swing Analysis

- Select instrument, date range, pts_to_analyse, option_range, expiry_count
- Expand ATR Config to tune swing detection sensitivity
- Click **Run** — takes 1–10 minutes depending on date range and number of legs
- Chart shows candlesticks with Hill/Valley markers and qualifying leg lines
- Trade table (5A) shows each qualifying leg with configurable option price columns
- Summary (5B) aggregates profit metrics by day / week / overall

### Module 2 — Overnight Gap Analysis

- Select instrument, date range, parameters
- Click **Run**
- Every session where 3:15 PM → 9:25 AM data is available is analysed
- Summary includes a Gap Size breakdown (0–25 / 25–50 / 50–100 / 100+ pts)

### Column Picker

Both pages have a **Columns** button that opens a grouped checkbox panel:
- **Group A** — Instrument spot at intermediate checkpoints (M1 only)
- **Group B** — Along option prices (CE for up-move, PE for down-move)
- **Group C** — Against option prices
- **Group D/E** — DTE per expiry, % optimal option, profit % optimal option

---

## Result Files

Each Run saves a timestamped JSON:
```
backend/results/results_module1_YYYYMMDD_HHMMSS.json
backend/results/results_module2_YYYYMMDD_HHMMSS.json
```

The JSON contains **all computed columns** for all strikes, all expiries, all checkpoints — the frontend only filters the display.

---

## Key Analytical Definitions

| Term | Definition |
|---|---|
| ATM | Nearest strike to spot, rounded to `pts_to_analyse` interval |
| Along option | Option that profits if the move continues (CE for up, PE for down) |
| Against option | The opposite side |
| Cheapest Along | Most OTM Along in the grid (ATM+range for up, ATM-range for down) |
| percent_optimal_option | `abs(0% price − 100% price) / 0% price` |
| profit_percent_optimal_option | `abs(20% price − 80% price) / 20% price` |
| DTE bucket | Expiry Day / 1 DTE / 2 DTE / Near (3–5) / Short (6–10) / Mid (11–20) / Far (21+) |

---

## Technical Notes

- Upstox 1-minute historical data is limited to one calendar month per API call. The backend auto-chunks requests.
- Option contract keys are resolved live from `GET /v2/option/contract` at analysis start — no local instrument master needed.
- India VIX is fetched from `NSE_INDEX|India VIX` as daily OHLCV.
- The backend is single-process, single-user. Access token is stored in a Python dict (no Redis, no DB).
