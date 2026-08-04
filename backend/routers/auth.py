"""Upstox OAuth endpoints.

State machine:
  GET  /api/upstox/status       → {has_credentials, is_connected}
  POST /api/upstox/credentials  → save api_key/secret/redirect_uri to upstox_config.txt
  GET  /api/upstox/auth-url     → return OAuth redirect URL for frontend to navigate to
  POST /api/upstox/token        → exchange code for access token (persisted to upstox_config.txt)
  POST /api/upstox/disconnect   → clear token from memory and upstox_config.txt

upstox_config.txt format (4 lines):
  line 0: api_key
  line 1: api_secret
  line 2: redirect_uri
  line 3: access_token  (empty string when not connected)
"""
from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
from schemas.common import UpstoxConfig, UpstoxStatus
from services.upstox_client import get_auth_url, exchange_code

router = APIRouter(prefix="/api/upstox", tags=["upstox"])


# ---------------------------------------------------------------------------
# Config file helpers
# ---------------------------------------------------------------------------

def _read_config() -> UpstoxConfig | None:
    if not os.path.exists(settings.CONFIG_FILE):
        return None
    try:
        with open(settings.CONFIG_FILE) as f:
            lines = [l.strip() for l in f.readlines()]
        if len(lines) < 3:
            return None
        return UpstoxConfig(api_key=lines[0], api_secret=lines[1], redirect_uri=lines[2])
    except Exception:
        return None


def _read_token_from_file() -> str | None:
    """Return persisted access token from line 3 of the config file, or None."""
    if not os.path.exists(settings.CONFIG_FILE):
        return None
    try:
        with open(settings.CONFIG_FILE) as f:
            lines = [l.strip() for l in f.readlines()]
        token = lines[3] if len(lines) >= 4 else ""
        return token if token else None
    except Exception:
        return None


def _write_config(cfg: UpstoxConfig, token: str | None = None) -> None:
    """Write credentials + optional token to config file."""
    with open(settings.CONFIG_FILE, "w") as f:
        f.write(f"{cfg.api_key}\n{cfg.api_secret}\n{cfg.redirect_uri}\n{token or ''}\n")


def _persist_token(token: str | None) -> None:
    """Update only line 3 (access_token) without touching credentials."""
    cfg = _read_config()
    if cfg is None:
        return
    _write_config(cfg, token)


# ---------------------------------------------------------------------------
# In-memory session — initialised from file on startup
# ---------------------------------------------------------------------------

_session: dict = {
    "access_token": _read_token_from_file(),
    "oauth_state": None,
}


def get_access_token() -> str | None:
    return _session.get("access_token")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status", response_model=UpstoxStatus)
async def get_status():
    cfg = _read_config()
    return UpstoxStatus(
        has_credentials=cfg is not None,
        is_connected=_session["access_token"] is not None,
    )


@router.post("/credentials")
async def save_credentials(cfg: UpstoxConfig):
    # Preserve any existing token when re-saving credentials
    _write_config(cfg, _session.get("access_token"))
    return {"ok": True, "message": "Credentials saved. Click Connect to authenticate."}


@router.get("/auth-url")
async def get_upstox_auth_url():
    cfg = _read_config()
    if not cfg:
        raise HTTPException(400, "No credentials saved. Add credentials first.")
    state = secrets.token_urlsafe(16)
    _session["oauth_state"] = state
    url = get_auth_url(cfg.api_key, cfg.redirect_uri, state)
    return {"auth_url": url}


class TokenRequest(BaseModel):
    code: str
    state: str | None = None


@router.post("/token")
async def exchange_token(req: TokenRequest):
    cfg = _read_config()
    if not cfg:
        raise HTTPException(400, "No credentials saved.")
    if req.state and _session.get("oauth_state") and req.state != _session["oauth_state"]:
        raise HTTPException(400, "OAuth state mismatch. Possible CSRF.")
    try:
        token = await exchange_code(cfg.api_key, cfg.api_secret, req.code, cfg.redirect_uri)
    except Exception as exc:
        raise HTTPException(502, f"Upstox token exchange failed: {exc}")
    _session["access_token"] = token
    _session["oauth_state"] = None
    _persist_token(token)          # write to upstox_config.txt
    return {"ok": True, "message": "Connected to Upstox."}


@router.post("/disconnect")
async def disconnect():
    _session["access_token"] = None
    _persist_token(None)           # clear from upstox_config.txt
    return {"ok": True, "message": "Disconnected."}
