"""Standalone Upstox login helper.  Run from anywhere:

    python connect_upstox.py

upstox_config.txt (next to this file), 4 lines:
  1: api_key
  2: api_secret
  3: redirect_uri   e.g. http://localhost:5173/oauth/callback
  4: access_token   (written by this script)

Prints the Upstox login URL.  Open it in a browser and log in; Upstox redirects to
redirect_uri, where this script is listening (FastAPI + uvicorn on the redirect
URI's port), exchanges the code for a token, saves it as line 4 and exits.
Stop the frontend dev server first if it is using the same port.
"""
from __future__ import annotations

import os
import secrets
import sys
import threading
from urllib.parse import urlencode, urlparse

import httpx
import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upstox_config.txt")
UPSTOX_BASE = "https://api.upstox.com/v2"
TIMEOUT_SECONDS = 600


def read_config() -> tuple[str, str, str]:
    if not os.path.exists(CONFIG_FILE):
        sys.exit(f"Missing {CONFIG_FILE}\nPut api_key, api_secret, redirect_uri on lines 1-3.")
    with open(CONFIG_FILE, encoding="utf-8") as f:
        lines = [l.strip() for l in f.read().splitlines()]
    if len(lines) < 3 or not all(lines[:3]):
        sys.exit("upstox_config.txt needs api_key, api_secret, redirect_uri on lines 1-3.")
    return lines[0], lines[1], lines[2]


def save_token(api_key: str, api_secret: str, redirect_uri: str, token: str) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(f"{api_key}\n{api_secret}\n{redirect_uri}\n{token}\n")


def exchange_code(api_key: str, api_secret: str, redirect_uri: str, code: str) -> str:
    resp = httpx.post(
        f"{UPSTOX_BASE}/login/authorization/token",
        data={
            "code": code,
            "client_id": api_key,
            "client_secret": api_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        headers={"Accept": "application/json"},
        timeout=30.0,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Upstox auth failed (HTTP {resp.status_code}): {resp.text[:300]}")
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("Upstox returned no access_token")
    return token


def main() -> None:
    api_key, api_secret, redirect_uri = read_config()
    parsed = urlparse(redirect_uri)
    host, port, path = parsed.hostname or "localhost", parsed.port or 80, parsed.path or "/"
    state = secrets.token_urlsafe(16)

    login_url = f"{UPSTOX_BASE}/login/authorization/dialog?" + urlencode(
        {"client_id": api_key, "redirect_uri": redirect_uri, "response_type": "code", "state": state}
    )

    app = FastAPI()
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    result: dict[str, str] = {}

    def page(msg: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse(f"<h3>{msg}</h3><p>You can close this tab.</p>", status_code=status)

    @app.get(path)
    def callback(code: str | None = Query(None), state_in: str | None = Query(None, alias="state"),
                 error: str | None = Query(None)):
        if error or not code:
            result["error"] = error or "no code in redirect"
            server.should_exit = True
            return page(f"Upstox login failed: {result['error']}", 400)
        if state_in != state:
            result["error"] = "state mismatch"
            server.should_exit = True
            return page("State mismatch, aborted.", 400)
        try:
            save_token(api_key, api_secret, redirect_uri, exchange_code(api_key, api_secret, redirect_uri, code))
        except Exception as exc:
            result["error"] = str(exc)
            server.should_exit = True
            return page(f"Token exchange failed: {exc}", 500)
        result["ok"] = "1"
        server.should_exit = True
        return page("Upstox connected. Token saved.")

    def timeout() -> None:
        result.setdefault("error", f"no login within {TIMEOUT_SECONDS}s")
        server.should_exit = True

    timer = threading.Timer(TIMEOUT_SECONDS, timeout)
    timer.daemon = True
    timer.start()

    print("\nOpen this URL in your browser and log in to Upstox:\n")
    print(login_url)
    print(f"\nWaiting for redirect on {redirect_uri} ...")
    server.run()
    timer.cancel()

    if result.get("ok"):
        print(f"Connected. Access token saved to {CONFIG_FILE}")
    else:
        sys.exit(f"Failed: {result.get('error', 'server stopped')}")


if __name__ == "__main__":
    main()
