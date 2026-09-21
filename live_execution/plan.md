# Live Algo Trading Execution System — Implementation Plan

## 1. Objective

Build a production-style live execution framework for running multiple 1-minute candle strategies through Upstox.

The first two strategies are intentionally simple:

- `MyStrategy_Buy`
- `MyStrategy_Sell`

They are primarily system-validation strategies. The goal is to generate enough real market activity to validate:

- historical candle loading
- live tick subscription
- live OHLCV candle construction
- official previous-candle reconciliation
- strategy calculation
- entry/exit execution
- order state handling
- WebSocket live monitoring
- candle consistency between local/live and broker-fetched candles
- recovery/error visibility

The system should be reusable so future strategies can use the same `StrategyExecutor`.

---

## 2. High-Level Architecture

```text
                         +----------------------+
                         |     FastAPI Server   |
                         |  REST + WebSocket    |
                         +----------+-----------+
                                    |
                                    | live state/events
                                    v
+---------------------------------------------------------------+
|                     Strategy Runtime                          |
|                                                               |
|  +----------------------+        +----------------------+     |
|  | StrategyExecutor #1  |        | StrategyExecutor #2  |     |
|  |                      |        |                      |     |
|  | StrategyData =       |        | StrategyData =       |     |
|  | MyStrategy_Buy       |        | MyStrategy_Sell      |     |
|  +----------+-----------+        +----------+-----------+     |
|             |                               |                 |
|             +---------------+---------------+                 |
|                             v                                 |
|                     Upstox Market Data                        |
|                     + Order API                               |
+-----------------------------+---------------------------------+
                              |
                              v
                           Upstox
```

One `StrategyExecutor` instance represents one running strategy instance.

---

## 3. Core Design Principle

Separate the system into:

```text
Market Data
    ->
Candle State
    ->
Strategy Decision
    ->
Order Execution
```

`MyStrategy_*` must not directly place orders or directly depend on Upstox order APIs.

`StrategyExecutor` owns the execution lifecycle and broker interaction.

---

## 4. Main Components

Recommended project structure:

```text
app/
├── main.py
├── config.py
│
├── strategies/
│   ├── base_strategy.py
│   ├── my_strategy_buy.py
│   └── my_strategy_sell.py
│
├── execution/
│   ├── strategy_executor.py
│   ├── order_manager.py
│   ├── position_manager.py
│   └── execution_state.py
│
├── market_data/
│   ├── upstox_client.py
│   ├── tick_processor.py
│   ├── candle_builder.py
│   ├── candle_store.py
│   └── candle_reconciler.py
│
├── api/
│   ├── routes.py
│   └── websocket_manager.py
│
├── models/
│   ├── candle.py
│   ├── tick.py
│   ├── order.py
│   └── strategy_state.py
│
└── frontend/
    ├── index.html
    ├── app.js
    └── styles.css
```

---

## 5. StrategyExecutor

`StrategyExecutor` is the runtime engine for one strategy.

Responsibilities:

1. Load historical candles.
2. Subscribe to live ticks.
3. Build the current live candle.
4. Fetch/reconcile the previous completed candle.
5. Maintain the candle DataFrame.
6. Call strategy calculation.
7. Call entry evaluation.
8. Call exit evaluation.
9. Maintain position/order state.
10. Place market orders.
11. Publish live state to FastAPI/WebSocket.
12. Handle reconnect/recovery.
13. Maintain execution logs.
14. Prevent duplicate entry/exit orders.

Conceptual class:

```python
class StrategyExecutor:

    def __init__(self, strategy_data, upstox_client):
        self.StrategyData = strategy_data
        self.upstox = upstox_client

        self.candle_df = None
        self.live_candle = None

        self.current_position = None
        self.current_order = None

        self.execution_state = None
        self.last_processed_market_version = 0

    async def start(self):
        # startup / warmup
        pass

    async def stop(self):
        # unsubscribe / cleanup
        pass

    async def on_tick(self, tick):
        # live tick entry point
        pass

    async def process_new_market_state(self):
        # process latest market snapshot
        pass

    async def process_entry(self):
        pass

    async def process_exit(self):
        pass

    async def place_entry_order(self, decision):
        pass

    async def place_exit_order(self, decision):
        pass
```

The exact implementation can differ; ownership is the important part.

---

## 6. Strategy Interface

The strategy behaves as a definition/template.

Recommended interface:

```python
class BaseStrategy:

    @staticmethod
    def calculate(candle_df):
        # Add/update indicator and derived columns.
        # Must NOT modify OHLCV columns.
        pass

    @staticmethod
    def evaluate_entry(candle_df, live_candle):
        # Return entry decision or None.
        pass

    @staticmethod
    def evaluate_exit(candle_df, live_candle, exit_details):
        # Return exit confirmation or None.
        pass
```

`StrategyExecutor` owns the DataFrame.

The strategy enriches it with calculated columns.

---

## 7. DataFrame Contract

The DataFrame contains completed candles.

```text
timestamp | open | high | low | close | volume | indicator_1 | indicator_2
```

Rules:

- `open/high/low/close/volume` are market-data fields.
- Strategy calculations may add/update derived columns.
- Strategy code must never rewrite OHLCV values.
- The currently forming candle remains outside the completed-candle DataFrame until finalized/reconciled.

---

## 8. Live Candle

The current minute is represented separately.

```python
live_candle = {
    "timestamp": ...,
    "open": ...,
    "high": ...,
    "low": ...,
    "close": ...,
    "volume": ...,
    "last_tick_price": ...,
    "last_tick_timestamp": ...,
    "market_version": ...
}
```

Every incoming tick updates:

- open
- high
- low
- close
- volume
- last tick price
- last tick timestamp
- market version

The strategy does not need to process every tick synchronously.

---

## 9. Latest-State Processing

Do not maintain a queue containing every tick for strategy evaluation.

If strategy processing takes 1.5 seconds while six ticks arrive:

```text
Tick 1 -> strategy processing starts
Tick 2 -> latest state updated
Tick 3 -> latest state updated
Tick 4 -> latest state updated
Tick 5 -> latest state updated
Tick 6 -> latest state updated
```

When processing finishes:

```text
process latest state
```

rather than processing five stale strategy evaluations.

Use a monotonically increasing `market_version`.

Example:

```text
Tick 1 -> version 101
Tick 2 -> version 102
Tick 3 -> version 103
...
```

The strategy processor remembers the last processed version.

---

## 10. Minute Transition

At the first tick of a new minute, two activities happen in parallel.

Example:

```text
10:17 first tick
      |
      +-------------------+
      |                   |
      v                   v
Live Candle          Fetch official
Builder              10:16 candle
      |                   |
      v                   v
Start 10:17          Reconcile 10:16
candle               + calculations
      |                   |
      +---------+---------+
                v
         Strategy execution
```

The live tick/candle builder must not wait for the historical API response.

---

## 11. Strategy Startup / Warmup

Example:

```text
10:16:23
strategy starts
```

Startup:

1. Determine current minute.
2. If startup occurs too late in a minute (for example after approximately second 50), wait for the next minute and start after the initial few seconds.
3. Fetch the latest completed historical candle.
4. Subscribe to live ticks.
5. Collect the initial live candle.
6. Do not initiate a trade during the initial warmup.
7. At the next usable minute:
   - build current live candle
   - fetch previous official candle
   - calculate strategy columns
   - enable strategy execution.

The exact warmup threshold should be configurable.

---

## 12. Historical Candle Reconciliation

At every new minute:

```text
Current minute = 10:17

Live:
    build 10:17

Historical:
    fetch official 10:16
```

After the official candle is received:

1. Replace/reconcile the local 10:16 candle.
2. Verify OHLCV.
3. Calculate/update strategy columns.
4. Publish the corrected candle to the frontend.
5. Make the strategy eligible to execute for the current minute.

The frontend should visibly show:

```text
10:16 local/live candle
        ->
official 10:16 candle
        ->
final reconciled 10:16 candle
```

Any discrepancy should be visible/logged.

---

## 13. MyStrategy_Buy

### Strategy

Use NIFTY 1-minute candles.

Entry:

```text
Close(Cn-1) > Close(Cn-2)
```

Then during current candle `Cn`, enter a long position.

Instrument:

```text
NIFTY 23600 CE
Expiry: 22 September 2026
```

The actual broker instrument identifier should be resolved from broker instrument metadata/configuration rather than relying only on the display name.

### Stop Loss

```text
Stop Loss = Low(Cn-2)
```

### Target

```text
Risk = Entry Price - Stop Loss

Target = Entry Price + 2 * Risk
```

Therefore:

```text
Risk : Reward = 1 : 2
```

Example:

```text
Entry = 120
SL    = 110

Risk = 10

Target = 120 + (2 * 10)
       = 140
```

### Strategy response

Conceptually:

```python
{
    "confirmed": True,
    "side": "LONG",
    "instrument": "...",
    "entry_reason": "...",
    "stop_loss": ...,
    "target": ...,
    "risk_reward": "1:2"
}
```

---

## 14. MyStrategy_Sell

### Strategy

Use NIFTY 1-minute candles.

Entry:

```text
Close(Cn-1) < Close(Cn-2)
```

Then during current candle `Cn`, enter a short position.

Instrument:

```text
NIFTY 23200 PE
Expiry: 22 September 2026
```

Again, resolve the actual broker instrument identifier through instrument metadata/configuration.

### Stop Loss

The requested rule is:

```text
Stop Loss = Low(Cn-2)
```

For a conventional short-position risk model, this requires validation because a short stop is normally above the entry price. If `Low(Cn-2)` is below the short entry, the resulting stop/risk calculation is invalid.

Therefore validate:

```text
stop_loss > entry_price
```

before accepting the short entry.

Do not silently invert the rule.

### Target

For a valid short trade:

```text
Risk = Stop Loss - Entry Price

Target = Entry Price - (2 * Risk)
```

Example:

```text
Entry = 120
SL    = 130

Risk = 10

Target = 120 - (2 * 10)
       = 100
```

---

## 15. Important Strategy Timing Rule

If an entry happens during current candle `Cn`:

```text
Cn
|
+-- entry triggered
+-- order placed
+-- position becomes active
```

Do not immediately evaluate an exit within the same candle.

The executor should mark:

```text
skip_exit_for_current_candle = True
```

and wait for the next candle.

At the next minute:

```text
Cn+1
   ->
normal exit monitoring begins
```

This rule belongs in `StrategyExecutor`, because it is an execution-policy rule rather than strategy-specific logic.

---

## 16. Entry State Machine

Recommended states:

```text
NO_POSITION
     |
     v
ENTRY_TRIGGERED
     |
     v
ENTRY_ORDER_PENDING
     |
     +-- FILLED ----------> POSITION_OPEN
     |
     +-- REJECTED --------> NO_POSITION
```

Do not allow another entry while:

```text
ENTRY_ORDER_PENDING
POSITION_OPEN
EXIT_ORDER_PENDING
```

unless a future strategy explicitly supports multiple concurrent positions.

---

## 17. Exit State Machine

```text
POSITION_OPEN
     |
     v
EXIT_TRIGGERED
     |
     v
EXIT_ORDER_PENDING
     |
     +-- FILLED ----------> POSITION_CLOSED
     |
     +-- REJECTED --------> POSITION_OPEN / ERROR
```

After successful exit:

```text
POSITION_CLOSED
     ->
NO_POSITION
     ->
next valid entry can be evaluated
```

---

## 18. Market Order Handling

The executor is responsible for placing the market order.

Strategy only returns a decision.

```text
MyStrategy
    ->
ENTRY CONFIRMED
    ->
StrategyExecutor
    ->
OrderManager
    ->
Upstox
```

Record at minimum:

```text
strategy_id
order_id
instrument
side
quantity
order_type
trigger_reason
target
stop_loss
timestamp
broker_status
filled_quantity
average_fill_price
```

Distinguish:

- trigger price
- submitted time
- broker acknowledgement
- actual fill price
- fill time

---

## 19. FastAPI Monitoring Server

FastAPI provides REST and WebSocket monitoring.

### REST

Possible endpoints:

```text
GET /api/strategies
GET /api/strategies/{strategy_id}
GET /api/strategies/{strategy_id}/candles
GET /api/strategies/{strategy_id}/orders
GET /api/strategies/{strategy_id}/state
GET /api/health
```

### WebSocket

```text
/ws
```

Push live events such as:

```text
tick
live_candle
candle_finalized
candle_reconciled
strategy_state
entry_signal
exit_signal
order_submitted
order_filled
order_rejected
error
connection_status
```

---

## 20. Frontend

The HTML/JS frontend should show one panel per running strategy.

Example:

```text
+------------------------------------------------+
| MyStrategy_Buy                                 |
| Status: RUNNING                                |
| Instrument: NIFTY 23600 CE                     |
|                                                |
|              Candlestick Chart                 |
|                                                |
|  10:15  completed candle                       |
|  10:16  reconciled candle                      |
|  10:17  live candle                            |
|                                                |
|  Current Price: 123.40                         |
|                                                |
|  Position: OPEN                                |
|  Entry: 120                                    |
|  SL: 110                                       |
|  Target: 140                                   |
+------------------------------------------------+

Orders / Events
------------------------------------------------
10:17:03  ENTRY SIGNAL
10:17:04  MARKET ORDER SUBMITTED
10:17:05  ORDER FILLED @ 121.20
```

---

## 21. Candle Visualization Requirement

The frontend should clearly distinguish:

### Historical/final candles

Normal completed candle.

### Current live candle

Continuously moving OHLCV candle.

### Reconciled candle

When the official broker candle arrives:

```text
10:16
local candle
     ->
official candle
     ->
reconciled/final
```

If values differ, display something like:

```text
10:16  CANDLE CORRECTED
```

and expose:

```text
local OHLCV
official OHLCV
difference
```

This makes missed ticks or data glitches easy to diagnose.

---

## 22. Event Architecture

Avoid frontend polling every 100 ms.

Use:

```text
StrategyExecutor
      |
      v
Event Publisher
      |
      v
WebSocket Manager
      |
      v
Browser
```

Example event:

```json
{
  "type": "live_candle",
  "strategy_id": "buy_strategy",
  "timestamp": "2026-09-21T10:17:23",
  "candle": {
    "open": 100,
    "high": 105,
    "low": 99,
    "close": 103,
    "volume": 12000
  },
  "last_tick_price": 103,
  "last_tick_timestamp": "...",
  "market_version": 1234
}
```

---

## 23. Error and Connection State

Expose these states in logs and frontend:

```text
STARTING
WARMING_UP
SUBSCRIBING
RUNNING
RECONNECTING
RECONCILING
ORDER_PENDING
ERROR
STOPPING
STOPPED
```

Market-data connection status should be visible.

Example:

```text
WebSocket: CONNECTED
Last tick: 10:17:43.231
Last candle update: 10:17:43
```

---

## 24. Reconnection

The system must handle:

```text
Upstox WebSocket disconnected
```

Flow:

```text
CONNECTED
   ->
DISCONNECTED
   ->
RECONNECTING
   ->
SUBSCRIBE AGAIN
   ->
CHECK DATA GAP
   ->
RECONCILE
   ->
RUNNING
```

If ticks were missed during the gap, the affected candle should be marked for reconciliation.

---

## 25. Application Restart / Recovery

On restart:

1. Load persisted strategy/order state.
2. Query broker for current orders/positions.
3. Compare broker state with local state.
4. Reconcile.
5. Fetch required historical candles.
6. Reconnect live data.
7. Resume execution only after state is consistent.

Never assume:

```text
local state == broker reality
```

after a crash/restart.

---

## 26. Persistence

Do not rely only on in-memory objects.

Persist:

### Strategy run state

```text
strategy_id
start_time
status
current_candle
last_processed_market_version
```

### Orders

```text
order_id
strategy_id
instrument
side
quantity
status
fill_price
timestamps
```

### Trades

```text
trade_id
entry_order
exit_order
entry_price
exit_price
SL
target
P&L
```

### Candle diagnostics

```text
timestamp
local OHLCV
official OHLCV
difference
```

---

## 27. Logging

Use structured logs.

At minimum:

```text
strategy_start
historical_fetch_start
historical_fetch_complete
tick_received
candle_updated
minute_transition
official_candle_received
candle_reconciled
strategy_calculated
entry_signal
exit_signal
order_submitted
order_acknowledged
order_filled
order_rejected
websocket_disconnected
websocket_reconnected
recovery_started
recovery_completed
```

Include `strategy_id`, timestamp, instrument, and market version where applicable.

---

## 28. Important Safety Guards

Before placing an order:

```text
1. Strategy is RUNNING
2. Market data is healthy
3. Strategy has no conflicting pending order
4. Position state is valid
5. Entry has not already been executed for this signal
6. Instrument is valid
7. Quantity is valid
8. Stop loss is valid
9. Target is valid
10. Risk/reward calculation is valid
```

For the sell strategy under the stated rule:

```text
SL > entry price
```

must be validated.

---

## 29. Live Validation

`MyStrategy_Buy` and `MyStrategy_Sell` should initially be treated as system-validation strategies.

Monitor:

```text
number of signals
number of orders
filled orders
rejected orders
entry latency
exit latency
candle discrepancies
WebSocket reconnects
missed tick gaps
strategy processing latency
order response latency
```

The purpose is to validate the execution infrastructure independently of strategy sophistication.

---

## 30. Metrics Dashboard

Show:

```text
Strategy
Status
Ticks received
Last tick age
Current candle
Completed candles
Candle reconciliation count
Candle mismatch count
Entry signals
Exit signals
Orders submitted
Orders filled
Orders rejected
Open position
Current P&L
Strategy processing latency
Order latency
WebSocket status
```

---

## 31. Concurrency Model

Recommended conceptual separation:

```text
Upstox Tick Listener
        |
        v
Tick / Candle Builder
        |
        v
Latest Market State
        |
        +--------------------> WebSocket publisher
        |
        v
Strategy Processor
        |
        v
Order Manager
        |
        v
Upstox Order API
```

Historical candle fetching and reconciliation must not block tick reception.

Order placement must not block tick reception.

Frontend broadcasting must not block trading logic.

---

## 32. One Source of Truth Per Concern

```text
Tick stream
    -> market-data source

Candle Builder
    -> current candle

Official candle API
    -> completed candle reconciliation

Strategy
    -> trading decision

StrategyExecutor
    -> strategy lifecycle

OrderManager
    -> broker order interaction

Broker
    -> actual order/position reality

WebSocket
    -> monitoring only
```

The frontend must never participate in trading decisions.

---

## 33. Complete Execution Flow

```text
START
  |
  v
Create StrategyExecutor
  |
  v
Assign StrategyData
  |
  v
Load persisted state
  |
  v
Check broker position/order state
  |
  v
Fetch historical candles
  |
  v
Run strategy calculation
  |
  v
Subscribe live ticks
  |
  v
Warmup
  |
  v
NEW MINUTE
  |
  +----------------+
  |                |
  v                v
Build live       Fetch previous
candle           official candle
  |                |
  |                v
  |             Reconcile
  |                |
  |                v
  |             Calculate
  |                |
  +--------+-------+
           v
    Strategy evaluation
           |
      +----+----+
      |         |
    Entry      Exit
      |         |
      v         v
  Decision   Decision
      |         |
      +----+----+
           v
      OrderManager
           |
           v
         Upstox
           |
           v
      Update state
           |
           v
    Publish WebSocket
           |
           v
        Frontend
```

---

## 34. Implementation Order

### Phase 1 — Data layer

1. Upstox historical candle client
2. Upstox live tick client
3. Tick model
4. Live candle builder
5. Candle store
6. Candle reconciliation

### Phase 2 — Strategy layer

7. Base strategy interface
8. `MyStrategy_Buy`
9. `MyStrategy_Sell`

### Phase 3 — Execution layer

10. `StrategyExecutor`
11. Position state machine
12. Order manager
13. Entry/exit order handling
14. Duplicate-order protection
15. Same-candle exit suppression
16. Recovery/reconciliation

### Phase 4 — Monitoring

17. FastAPI
18. WebSocket manager
19. HTML/JS candle chart
20. Live candle updates
21. Official candle replacement/reconciliation visualization
22. Order/event feed

### Phase 5 — Reliability

23. Structured logging
24. Reconnection
25. API failure handling
26. Restart recovery
27. Persistence
28. Metrics/diagnostics

### Phase 6 — Validation

29. Run Buy strategy
30. Run Sell strategy
31. Compare local vs official candles
32. Verify order lifecycle
33. Verify frontend live state
34. Stress-test delayed strategy processing
35. Stress-test WebSocket reconnects
36. Validate recovery after application restart

---

## 35. Final Architecture

```text
                  +---------------------+
                  |   MyStrategy_Buy    |
                  +----------+----------+
                             |
                  +----------v----------+
                  | StrategyExecutor #1 |
                  +----------+----------+
                             |
                  +----------v----------+
                  |  Market Data Layer  |
                  +----------+----------+
                             |
                  +----------v----------+
                  |   Order Manager     |
                  +----------+----------+
                             |
                  +----------v----------+
                  |       Upstox        |
                  +----------+----------+
                             |
                  +----------v----------+
                  |   FastAPI / WS      |
                  +----------+----------+
                             |
                  +----------v----------+
                  |     HTML / JS UI    |
                  +---------------------+


                  +---------------------+
                  |   MyStrategy_Sell   |
                  +----------+----------+
                             |
                  +----------v----------+
                  | StrategyExecutor #2 |
                  +---------------------+
```

The framework is designed so that the two initial strategies can later be replaced by more complex strategies without changing the market-data, execution, order, recovery, or monitoring infrastructure.
