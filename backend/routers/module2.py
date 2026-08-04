"""M2 — Overnight Gap Analysis router."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from config import settings
from routers.auth import get_access_token
from schemas.module2 import Module2Request, Module2Result
from services.module2_service import run_module2

router = APIRouter(prefix="/api/module2", tags=["module2"])

_RUN_ID_RE = re.compile(r"^results_module2_\d{8}_\d{6}$")


def _require_token() -> str:
    token = get_access_token()
    if not token:
        raise HTTPException(401, "Not connected to Upstox. Please authenticate first.")
    return token


@router.get("/results/{run_id}", response_model=Module2Result)
async def get_result(run_id: str):
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(400, "Invalid run ID format")
    path = os.path.join(settings.RESULTS_DIR, f"{run_id}.json")
    if not os.path.isfile(path):
        raise HTTPException(404, f"Result '{run_id}' not found")
    with open(path, "r") as f:
        data = json.load(f)
    return Module2Result(**data)


@router.post("/run", response_model=Module2Result)
async def run(req: Module2Request):
    token = _require_token()
    start = datetime.now(timezone.utc)
    print(f"[Module2] Starting run at {start.isoformat()}")
    try:
        result = await run_module2(req, token)
        end = datetime.now(timezone.utc)
        print(f"[Module2] Ended run at {end.isoformat()} (duration: {(end - start).total_seconds():.2f}s)")
        return result
    except PermissionError as exc:
        raise HTTPException(401, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Analysis failed: {exc}")
