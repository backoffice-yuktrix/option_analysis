from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

from app.config import API, HFT_API, IST
from app.timeutil import to_ts


class UpstoxError(Exception):
    def __init__(self, message: str, status: int | None = None, ambiguous: bool = False):
        super().__init__(message)
        self.status = status
        self.ambiguous = ambiguous


class TokenExpired(UpstoxError):
    pass


def parse_candles(payload: dict) -> list[dict]:
    rows = (payload.get("data") or {}).get("candles") or []
    out = [
        {
            "timestamp": to_ts(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5] or 0),
        }
        for r in rows
    ]
    out.sort(key=lambda c: c["timestamp"])
    return out


class UpstoxClient:
    def __init__(self, token: str):
        self._http = httpx.AsyncClient(
            timeout=15.0,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        try:
            resp = await self._http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise UpstoxError(f"network error: {type(exc).__name__}", ambiguous=True) from exc
        if resp.status_code == 401:
            raise TokenExpired("Access token rejected (401). Re-run connect_upstox.py.", status=401)
        if resp.status_code >= 400:
            raise UpstoxError(
                f"HTTP {resp.status_code}: {resp.text[:300]}",
                status=resp.status_code,
                ambiguous=resp.status_code >= 500,
            )
        return resp.json()

    async def validate_token(self) -> None:
        await self._request("GET", f"{API}/v2/user/profile")

    async def find_option(self, underlying_key: str, expiry: str, strike: float, option_type: str) -> dict:
        data = await self._request(
            "GET",
            f"{API}/v2/option/contract",
            params={"instrument_key": underlying_key, "expiry_date": expiry},
        )
        for c in data.get("data", []):
            if float(c.get("strike_price", 0)) == strike and c.get("instrument_type") == option_type:
                return c
        raise UpstoxError(f"No {option_type} {strike:g} contract found for expiry {expiry}.")

    async def intraday_candles(self, key: str) -> list[dict]:
        url = f"{API}/v3/historical-candle/intraday/{quote(key, safe='')}/minutes/1"
        return parse_candles(await self._request("GET", url))

    async def historical_candles(self, key: str, days: int) -> list[dict]:
        today = datetime.now(IST).date()
        start = today - timedelta(days=days)
        url = f"{API}/v3/historical-candle/{quote(key, safe='')}/minutes/1/{today.isoformat()}/{start.isoformat()}"
        return parse_candles(await self._request("GET", url))

    async def recent_candles(self, key: str, days: int) -> list[dict]:
        merged: dict[int, dict] = {}
        for loader in (lambda: self.historical_candles(key, days), lambda: self.intraday_candles(key)):
            try:
                for c in await loader():
                    merged[int(c["timestamp"].timestamp())] = c
            except TokenExpired:
                raise
            except UpstoxError:
                continue
        return [merged[k] for k in sorted(merged)]

    async def place_order(self, body: dict) -> list[str]:
        data = await self._request(
            "POST",
            f"{HFT_API}/v3/order/place",
            json=body,
            headers={"Content-Type": "application/json"},
        )
        return list((data.get("data") or {}).get("order_ids") or [])

    async def order_details(self, order_id: str) -> dict:
        data = await self._request("GET", f"{API}/v2/order/details", params={"order_id": order_id})
        return data.get("data") or {}

    async def cancel_order(self, order_id: str) -> None:
        await self._request("DELETE", f"{HFT_API}/v3/order/cancel", params={"order_id": order_id})

    async def list_orders(self) -> list[dict]:
        data = await self._request("GET", f"{API}/v2/order/retrieve-all")
        return data.get("data") or []

    async def positions(self) -> list[dict]:
        data = await self._request("GET", f"{API}/v2/portfolio/short-term-positions")
        return data.get("data") or []
