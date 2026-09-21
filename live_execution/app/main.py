from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from app.config import FRONTEND_DIR, load_settings, selected_strategies
from app.logs import setup_logging
from app.runtime import Runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    runtime = Runtime(load_settings(), selected_strategies())
    app.state.runtime = runtime
    await runtime.start()
    yield
    await runtime.stop()


app = FastAPI(title="Live Execution", lifespan=lifespan)


def _executor(strategy_id: str):
    executor = app.state.runtime.executors.get(strategy_id)
    if executor is None:
        raise HTTPException(status_code=404, detail="unknown strategy")
    return executor


@app.get("/api/health")
def health() -> dict:
    return app.state.runtime.health()


@app.get("/api/strategies")
def strategies() -> list[dict]:
    return [e.snapshot() for e in app.state.runtime.executors.values()]


@app.get("/api/strategies/{strategy_id}")
def strategy(strategy_id: str) -> dict:
    return _executor(strategy_id).snapshot()


@app.get("/api/strategies/{strategy_id}/state")
def strategy_state(strategy_id: str) -> dict:
    executor = _executor(strategy_id)
    return executor.snapshot() | {"recent_events": list(executor.events)[-100:]}


@app.get("/api/strategies/{strategy_id}/candles")
def candles(strategy_id: str, series: str = "option", limit: int = 120) -> dict:
    if series not in ("signal", "option"):
        raise HTTPException(status_code=422, detail="series must be signal or option")
    return _executor(strategy_id).candles(series, min(limit, 500))


@app.get("/api/strategies/{strategy_id}/orders")
def orders(strategy_id: str) -> dict:
    executor = _executor(strategy_id)
    return {
        "orders": executor.db.orders_for(strategy_id),
        "trades": executor.db.trades_for(strategy_id),
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    runtime: Runtime = app.state.runtime
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
    runtime.subscribers.add(queue)

    async def pump() -> None:
        while True:
            await ws.send_json(await queue.get())

    task = asyncio.create_task(pump())
    try:
        await ws.send_json({"type": "connection_status", "health": runtime.health()})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        runtime.subscribers.discard(queue)


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")
