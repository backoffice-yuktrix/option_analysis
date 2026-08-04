"""M1 — Intraday Swing Analysis router."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from config import settings
from routers.auth import get_access_token
from schemas.module1 import Module1Request, Module1Result
from services.module1_service import run_module1

router = APIRouter(prefix="/api/module1", tags=["module1"])

_RUN_ID_RE = re.compile(r"^results_module1_\d{8}_\d{6}$")


def _require_token() -> str:
    token = get_access_token()
    if not token:
        raise HTTPException(401, "Not connected to Upstox. Please authenticate first.")
    return token


@router.get("/results/{run_id}", response_model=Module1Result)
async def get_result(run_id: str):
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(400, "Invalid run ID format")
    path = os.path.join(settings.RESULTS_DIR, f"{run_id}.json")
    if not os.path.isfile(path):
        raise HTTPException(404, f"Result '{run_id}' not found")
    with open(path, "r") as f:
        data = json.load(f)
    return Module1Result(**data)


@router.post("/run", response_model=Module1Result)
async def run(req: Module1Request):
    token = _require_token()
    start = datetime.now(timezone.utc)
    print(f"[Module1] Starting run at {start.isoformat()}")
    try:
        result = await run_module1(req, token)
        end = datetime.now(timezone.utc)
        print(f"[Module1] Ended run at {end.isoformat()} (duration: {(end - start).total_seconds():.2f}s)")
        return result
    except PermissionError as exc:
        raise HTTPException(401, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Analysis failed: {exc}")
