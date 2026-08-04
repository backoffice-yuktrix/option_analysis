# WorkItems — Options Movement Analysis Tool

**PRD:** `option_analysis/PRD_options_movement_analysis.md`  
**Standalone project:** No DB, no login. File-based config + in-memory session token.

---

## Project Structure

```
option_analysis/
├── WorkItems.md              ← this file
├── README.md
├── .env.example
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   ├── main.py               ← FastAPI app, CORS, lifespan
│   ├── config.py             ← Pydantic Settings from .env
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py           ← Upstox OAuth endpoints
│   │   ├── module1.py        ← Intraday swing analysis
│   │   └── module2.py        ← Overnight gap analysis
│   ├── services/
│   │   ├── __init__.py
│   │   ├── upstox_client.py  ← Direct Upstox REST API calls (no DB)
│   │   ├── swing_detector.py ← ATR computation + Hill/Valley detection
│   │   ├── option_analyzer.py← Shared: strike grid, expiry resolution, pricing
│   │   ├── module1_service.py← M1 pipeline orchestration
│   │   └── module2_service.py← M2 pipeline orchestration
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py         ← Shared types (CheckpointData, StrikeOptionData)
│   │   ├── module1.py        ← M1 request/response schemas
│   │   └── module2.py        ← M2 request/response schemas
│   └── results/              ← auto-created; timestamped JSON run outputs
└── frontend/
    ├── package.json
    ├── index.html
    ├── vite.config.ts
    ├── tsconfig.json
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── index.css         ← exact same CSS variables as main app
        ├── api/
        │   ├── client.ts     ← axios instance, base URL
        │   ├── upstox.ts     ← /api/upstox/* calls
        │   ├── module1.ts    ← /api/module1/* calls
        │   └── module2.ts    ← /api/module2/* calls
        ├── components/
        │   ├── ui/           ← button, input, label, select, dialog, badge, tabs
        │   ├── UpstoxButton.tsx  ← 3-state Upstox connection button
        │   ├── ColumnPicker.tsx  ← grouped checkbox panel for column selection
        │   └── CandlestickChart.tsx ← lightweight-charts wrapper with swing overlays
        ├── pages/
        │   ├── Module1.tsx   ← full M1 page layout
        │   └── Module2.tsx   ← full M2 page layout
        ├── hooks/
        │   ├── useUpstox.ts  ← Upstox connection state (zustand)
        │   ├── useModule1.ts ← TanStack Query for M1 run
        │   └── useModule2.ts ← TanStack Query for M2 run
        └── lib/
            ├── utils.ts      ← cn(), formatNumber(), formatPercent()
            └── queryClient.ts← TanStack QueryClient singleton
```

---

## Codebase Reuse Map

### Backend — copy/adapt from existing app

| Existing file | Used in standalone | What's reused |
|---|---|---|
| `app/broker/plugins/upstox/auth.py` | `services/upstox_client.py` | `get_auth_url()`, `handle_auth_callback()` logic verbatim; without the BrokerNotSupportedError wrapping |
| `app/broker/plugins/upstox/_urls.py` | `services/upstox_client.py` | URL composition pattern: `https://api.upstox.com/v2` and `/v3` |
| `app/broker/plugins/upstox/data.py` | `services/upstox_client.py` | `get_history()`, `get_option_contracts()`, `get_option_chain()`, `_get()` HTTP helper pattern, `_INTERVAL_TO_UNIT` mapping |
| `app/market_data/history_client.py` | `services/upstox_client.py` | `_UPSTOX_MONTHLY_INTERVALS`, `_next_chunk_end()`, calendar-month chunking for 1m data |
| `app/core/logging.py` | `services/*.py`, `routers/*.py` | `get_logger(__name__)` pattern (stdlib logging fallback in standalone) |
| `app/main.py` | `main.py` | `@asynccontextmanager lifespan`, CORS middleware pattern, `app.include_router()` |
| `app/config.py` | `config.py` | `pydantic_settings.BaseSettings` with `SettingsConfigDict(env_file=".env")` pattern |

### Backend — new (no equivalent in existing app)

| File | Why new |
|---|---|
| `services/swing_detector.py` | ATR computation and alternating Hill/Valley swing detection is not implemented elsewhere |
| `services/option_analyzer.py` | Strike grid, expiry resolution, cheapest Along, checkpoint price extraction are new analytical primitives |
| `services/module1_service.py` | M1 pipeline (detect → checkpoint → option prices → metrics) |
| `services/module2_service.py` | M2 pipeline (session pairs → option prices → metrics) |
| `schemas/common.py` | Shared pydantic models for option pricing output |

### Frontend — copy/adapt from existing app

| Existing file | Used in standalone | What's reused |
|---|---|---|
| `frontend/src/index.css` | `src/index.css` | Exact CSS variables (OKLch palette, dark mode, Tailwind @theme block) |
| `frontend/src/lib/utils.ts` | `src/lib/utils.ts` | `cn()`, `formatNumber()`, `formatPercent()` |
| `frontend/src/components/ui/button.tsx` | `src/components/ui/button.tsx` | Exact copy |
| `frontend/src/components/ui/*.tsx` (input, label, select, dialog, badge, tabs) | `src/components/ui/` | Exact copies |
| `frontend/src/pages/DataControl.tsx` | Module1/Module2 page layout | Sub-tab nav pattern, page header with icon pattern |
| `frontend/src/pages/LiveMarketFeed.tsx` | Module1/Module2 | Button + table layout pattern |
| Axios interceptor pattern from `api/client.ts` | `src/api/client.ts` | Base URL, timeout variants — stripped of JWT auth headers |

### Frontend — new

| File | Why new |
|---|---|
| `components/UpstoxButton.tsx` | 3-state (no creds / creds saved / connected) button with modal for credential entry |
| `components/ColumnPicker.tsx` | Grouped checkbox panel (Groups A/B/C/D) with collapse/expand per group |
| `components/CandlestickChart.tsx` | `lightweight-charts` candlestick + swing markers + leg connector lines |
| `pages/Module1.tsx` | Full M1 page (input panel + ATR config + chart + 5A table + 5B summary tabs) |
| `pages/Module2.tsx` | M2 page (input panel + 5A table + 5B summary with gap buckets) |

---

## Key Design Decisions (standalone constraints)

### No instrument master DB
Existing app resolves symbols via `canonical_instrument_master` + `broker_instrument_map`. In standalone:
- NIFTY → `NSE_INDEX|Nifty 50` (hardcoded)
- BANKNIFTY → `NSE_INDEX|Nifty Bank` (hardcoded)
- India VIX → `NSE_INDEX|India VIX` (hardcoded)
- Option contracts: fetched live via `GET /v2/option/contract?instrument_key=<underlying_key>` at analysis time

### No DB — file-based state
- Upstox credentials: `upstox_config.txt` in backend working directory (newline-separated: `api_key\napi_secret\nredirect_uri`)
- Access token: in-memory dict on the FastAPI process (session-only; re-OAuth on restart)
- Run results: `results/results_module1_YYYYMMDD_HHMMSS.json` and `results_module2_...`

### Upstox 1m data chunking
Upstox v3 caps 1m data at one calendar month per call. The `upstox_client.py` replicates the monthly-chunking logic from `history_client.py` without the DB cache layer.

### VIX data
Fetched as daily candles for `NSE_INDEX|India VIX` across the full date range at analysis start. Joined by date into each leg/session row.

### OAuth callback flow
Frontend is the redirect target (`http://localhost:5173/oauth/callback`). Frontend extracts `code` from URL params, calls `POST /api/upstox/token {code}`, backend exchanges for access_token and stores in-memory.

---

## Work Items Checklist

### Phase 1 — Backend
- [x] `WorkItems.md` (this file)
- [ ] `backend/requirements.txt`
- [ ] `backend/.env.example`
- [ ] `backend/config.py`
- [ ] `backend/schemas/common.py`
- [ ] `backend/schemas/module1.py`
- [ ] `backend/schemas/module2.py`
- [ ] `backend/services/upstox_client.py`
- [ ] `backend/services/swing_detector.py`
- [ ] `backend/services/option_analyzer.py`
- [ ] `backend/services/module1_service.py`
- [ ] `backend/services/module2_service.py`
- [ ] `backend/routers/__init__.py`
- [ ] `backend/routers/auth.py`
- [ ] `backend/routers/module1.py`
- [ ] `backend/routers/module2.py`
- [ ] `backend/main.py`

### Phase 2 — Frontend
- [ ] `frontend/package.json`
- [ ] `frontend/index.html`
- [ ] `frontend/vite.config.ts`
- [ ] `frontend/tsconfig.json`
- [ ] `frontend/src/index.css`
- [ ] `frontend/src/main.tsx`
- [ ] `frontend/src/App.tsx`
- [ ] `frontend/src/lib/utils.ts`
- [ ] `frontend/src/lib/queryClient.ts`
- [ ] `frontend/src/api/client.ts`
- [ ] `frontend/src/api/upstox.ts`
- [ ] `frontend/src/api/module1.ts`
- [ ] `frontend/src/api/module2.ts`
- [ ] `frontend/src/components/ui/button.tsx`
- [ ] `frontend/src/components/ui/input.tsx`
- [ ] `frontend/src/components/ui/label.tsx`
- [ ] `frontend/src/components/ui/select.tsx`
- [ ] `frontend/src/components/ui/dialog.tsx`
- [ ] `frontend/src/components/ui/badge.tsx`
- [ ] `frontend/src/components/ui/tabs.tsx`
- [ ] `frontend/src/components/ui/checkbox.tsx`
- [ ] `frontend/src/components/ui/collapsible.tsx`
- [ ] `frontend/src/components/UpstoxButton.tsx`
- [ ] `frontend/src/components/ColumnPicker.tsx`
- [ ] `frontend/src/components/CandlestickChart.tsx`
- [ ] `frontend/src/hooks/useUpstox.ts`
- [ ] `frontend/src/hooks/useModule1.ts`
- [ ] `frontend/src/hooks/useModule2.ts`
- [ ] `frontend/src/pages/Module1.tsx`
- [ ] `frontend/src/pages/Module2.tsx`

### Phase 3 — Docs
- [ ] `README.md`
- [ ] `.env.example`
