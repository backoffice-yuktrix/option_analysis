"""The Upstox API on its own: instruments, expiries, option contracts and candles.

Extracted from analysis/templates/py_funcs.py (sections 1-4) so it can be used without the backtest/report code.
No disk cache here - every call goes to Upstox (option candles are memoised for the run only).

    import asyncio
    from datetime import date
    from upstox_funcs import Upstox, sessions_from

    async def main():
        async with Upstox() as up:
            und   = await up.find_instrument("NIFTY")                          # instrument key
            ukey  = und["instrument_key"]
            info  = await up.option_chain_info(ukey)                           # live expiries, strike step, lot
            exps  = await up.expiries(ukey)                                    # expired + live expiries
            cal   = await up.expiry_calendar(ukey, date(2026, 1, 1), date(2026, 3, 31))
            cs    = await up.candles(ukey, "1m", date(2026, 3, 2), date(2026, 3, 6))
            days  = sessions_from(cs)                                          # {day: [[HH:MM,o,h,l,c], ...]}
            c     = await up.resolve_option(ukey, cal[0], 22500, "CE")
            rows  = await up.option_candles(c, date(2026, 3, 2))               # [[HH:MM,o,h,l,c], ...]

    asyncio.run(main())

Sections: 1 config  2 client (rate limit, retry)  3 instruments  4 expiries and option contracts
          5 candles  6 candle helpers
"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import httpx

# ---------------------------------------------------------------------------
# 1  config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "upstox_config.txt")         # line 4 = access token

IST = timezone(timedelta(hours=5, minutes=30), "IST")
BASE_V2 = "https://api.upstox.com/v2"
BASE_V3 = "https://api.upstox.com/v3"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"

# Short names people type -> the Upstox index name.
INDEX_ALIASES = {"NIFTY": "Nifty 50", "NIFTY50": "Nifty 50", "BANKNIFTY": "Nifty Bank",
                 "FINNIFTY": "Nifty Fin Service", "MIDCPNIFTY": "NIFTY MID SELECT",
                 "VIX": "India VIX", "SENSEX": "SENSEX"}


def read_access_token() -> str:
    """Line 4 of analysis_rajkumarn/upstox_config.txt.  Run upstox_connect.py to refresh it."""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            lines = [l.strip() for l in f.read().splitlines()]
    except OSError:
        raise SystemExit(f"Missing {CONFIG_FILE}. Run analysis_rajkumarn/upstox_connect.py first.")
    if len(lines) < 4 or not lines[3]:
        raise SystemExit("No access token in upstox_config.txt (line 4). Run analysis_rajkumarn/upstox_connect.py.")
    return lines[3]


# ---------------------------------------------------------------------------
# 2  client
# ---------------------------------------------------------------------------
class Upstox:
    """One httpx client, a rate limit and retry.  Use as `async with Upstox() as up:`."""

    # Upstox meters per second, per minute AND per half hour, and a breach of the long window
    # puts the whole account in a penalty box for minutes.  The client paces itself to stay
    # inside every window.  Set a little under the published caps.
    RATE_LIMITS = ((1.0, 20), (60.0, 220), (1800.0, 880))      # (window seconds, max calls)
    MAX_INTERVAL = 4.0          # the slowest the adaptive gap will go
    COOLDOWN = 75.0             # a 429 means a window is spent; wait it out, do not hammer
    MAX_COOLDOWN = 240.0        # ... but never trust a server-supplied Retry-After blindly

    def __init__(self, token: str | None = None, min_interval: float = 0.25) -> None:
        self.token = token or read_access_token()
        self._min_interval = min_interval
        self._next_at = 0.0
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        self._instruments: dict[str, list[dict]] = {}          # exchange -> rows (this run only)
        self._contracts: dict[tuple[str, str], list[dict]] = {}   # (underlying, expiry|"live") -> rows
        self._bars: dict[tuple[str, str, int], list[list]] = {}   # (key, day, interval) -> rows
        self._times: list[float] = []      # when recent calls went out, for the rolling windows
        self._said_pacing = False
        self.calls = 0
        self.throttled = 0
        self.paced = 0.0                   # seconds spent waiting for a window to clear
        self.latencies: list[float] = []   # seconds per HTTP round trip (successful or not)

    async def __aenter__(self) -> "Upstox":
        self._client = httpx.AsyncClient(timeout=60.0)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    async def get(self, url: str, params: dict | None = None, *, retries: int = 8) -> dict:
        """GET with the bearer token; paces before each call, retries 429 and 5xx.

        A 429 means a whole window is spent, so the run waits `Retry-After` (or COOLDOWN)
        rather than retrying into the same wall, and permanently widens its own gap."""
        assert self._client, "use `async with Upstox() as up:`"
        delay = 2.0
        for attempt in range(retries + 1):
            await self._slot()
            t0 = asyncio.get_running_loop().time()
            try:
                r = await self._client.get(url, params=params, headers={
                    "Accept": "application/json", "Authorization": f"Bearer {self.token}"})
            except httpx.RequestError as exc:
                if attempt == retries:
                    raise RuntimeError(f"network error for {url}: {exc}") from exc
                await asyncio.sleep(delay); delay *= 2
                continue
            self.calls += 1
            self.latencies.append(asyncio.get_running_loop().time() - t0)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                raise PermissionError("Upstox token expired or unauthorised. Run analysis_rajkumarn/upstox_connect.py.")
            if r.status_code == 429:
                self.throttled += 1
                self._min_interval = min(self.MAX_INTERVAL, self._min_interval * 1.5)
                after = r.headers.get("Retry-After")
                pause = float(after) if (after or "").replace(".", "", 1).isdigit() else self.COOLDOWN
                pause = min(pause, self.MAX_COOLDOWN)
                if attempt < retries:
                    print(f"  rate limited ({self.throttled}), try {attempt + 1}/{retries} - cooling down "
                          f"{pause:.0f}s, then {self._min_interval:.2f}s between calls", flush=True)
                    self._times = []            # the window is spent; start counting again after the wait
                    await asyncio.sleep(pause)
                    continue
            if r.status_code in (500, 502, 503, 504) and attempt < retries:
                await asyncio.sleep(delay); delay = min(delay * 2, 60.0)
                continue
            raise RuntimeError(f"Upstox HTTP {r.status_code} for {url}: {r.text[:200]}")
        raise RuntimeError(f"exhausted retries for {url}")

    async def _slot(self) -> None:
        """Block until a call may go out under every rolling window, then book the slot."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            longest = self.RATE_LIMITS[-1][0]
            while True:
                now = loop.time()
                self._times = [t for t in self._times if now - t <= longest]
                wait = self._next_at - now
                for win, cap in self.RATE_LIMITS:
                    inwin = [t for t in self._times if now - t <= win]
                    if len(inwin) >= cap:
                        wait = max(wait, inwin[-cap] + win - now)
                if wait <= 0:
                    self._times.append(now)
                    self._next_at = now + self._min_interval
                    return
                if wait > 20 and not self._said_pacing:
                    self._said_pacing = True
                    print(f"  pacing: waiting {wait:.0f}s for a rate-limit window to clear", flush=True)
                self.paced += min(wait, 10.0)
                await asyncio.sleep(min(wait, 10.0))

    # -----------------------------------------------------------------------
    # 3  instruments
    # -----------------------------------------------------------------------
    async def instruments(self, exchange: str = "NSE") -> list[dict]:
        """The public instrument master for one exchange (NSE, BSE, MCX ...).
        Live instruments only; fetched once per run.  Rows carry segment, name,
        trading_symbol, instrument_key, instrument_type, lot_size, strike_price,
        expiry (epoch ms), underlying_symbol, underlying_key."""
        if exchange not in self._instruments:
            assert self._client, "use `async with Upstox() as up:`"
            r = await self._client.get(INSTRUMENTS_URL.format(exchange=exchange))
            r.raise_for_status()
            self._instruments[exchange] = json.loads(gzip.decompress(r.content))
        return self._instruments[exchange]

    async def find_instrument(self, query: str, segment: str | None = None,
                              exchange: str = "NSE") -> dict:
        """The instrument whose trading symbol or name equals `query` (case-blind).

        `find_instrument("NIFTY")`                    -> the Nifty 50 index (NSE_INDEX)
        `find_instrument("RELIANCE", "NSE_EQ")`       -> the equity
        `segment` is one of NSE_INDEX, NSE_EQ, NSE_FO ...; without it indices win, then
        equities.  Raises with the closest candidates when nothing matches."""
        q = INDEX_ALIASES.get(query.upper().replace(" ", ""), query).lower()
        rows = await self.instruments(exchange)
        order = [segment] if segment else ["NSE_INDEX", "NSE_EQ"]
        for seg in order:
            for r in rows:
                if r.get("segment") == seg and q in (str(r.get("trading_symbol", "")).lower(),
                                                     str(r.get("name", "")).lower()):
                    return {k: r.get(k) for k in ("instrument_key", "trading_symbol", "name", "segment",
                                                  "instrument_type", "lot_size", "exchange")}
        near = sorted({f"{r['segment']}|{r.get('trading_symbol')}" for r in rows
                       if q.split()[0] in str(r.get("trading_symbol", "")).lower()
                       and r.get("segment") in ("NSE_INDEX", "NSE_EQ")})[:8]
        raise LookupError(f"No instrument matching {query!r}. Closest: {near or 'none'}")

    # -----------------------------------------------------------------------
    # 4  expiries and option contracts
    # -----------------------------------------------------------------------
    async def option_contracts(self, underlying_key: str) -> list[dict]:
        """Every LIVE option contract of an underlying (GET /v2/option/contract).  Once per run."""
        ck = (underlying_key, "live")
        if ck not in self._contracts:
            d = await self.get(f"{BASE_V2}/option/contract", {"instrument_key": underlying_key})
            self._contracts[ck] = d.get("data") or []
        return self._contracts[ck]

    async def expired_option_contracts(self, underlying_key: str, expiry: date) -> list[dict]:
        """The option contracts of one PAST expiry (GET /v2/expired-instruments/option/contract).
        Their instrument keys carry a date suffix and only work with the expired candle endpoint."""
        ck = (underlying_key, expiry.isoformat())
        if ck not in self._contracts:
            d = await self.get(f"{BASE_V2}/expired-instruments/option/contract",
                               {"instrument_key": underlying_key, "expiry_date": expiry.isoformat()})
            self._contracts[ck] = d.get("data") or []
        return self._contracts[ck]

    async def live_expiries(self, underlying_key: str) -> list[date]:
        """Expiries that are still trading, oldest first."""
        return sorted({date.fromisoformat(str(c["expiry"])[:10])
                       for c in await self.option_contracts(underlying_key)})

    async def expired_expiries(self, underlying_key: str) -> list[date]:
        """Expiries that have already expired (GET /v2/expired-instruments/expiries), oldest first."""
        d = await self.get(f"{BASE_V2}/expired-instruments/expiries", {"instrument_key": underlying_key})
        return sorted(date.fromisoformat(s) for s in d.get("data") or [])

    async def expiries(self, underlying_key: str) -> list[date]:
        """The full expiry list: expired plus live, oldest first.  A failing side is reported
        and skipped, so one endpoint being down does not lose the other."""
        out: set[date] = set()
        try:
            out |= set(await self.expired_expiries(underlying_key))
        except RuntimeError as exc:
            print(f"  ! expired expiries unavailable ({exc})")
        try:
            out |= set(await self.live_expiries(underlying_key))
        except RuntimeError as exc:
            print(f"  ! live expiries unavailable ({exc})")
        return sorted(out)

    async def expiry_calendar(self, underlying_key: str, frm: date, to: date) -> list[date]:
        """Every option expiry from a week before `frm` to a month after `to`."""
        return [e for e in await self.expiries(underlying_key)
                if frm - timedelta(days=7) <= e <= to + timedelta(days=30)]

    async def option_chain_info(self, underlying_key: str) -> dict:
        """What the LIVE option chain of an underlying looks like:
        {expiries: [date...], strike_step, lot_size, strikes, contracts}.
        strike_step is the most common gap between adjacent strikes of the nearest
        expiry (NIFTY 50, BANKNIFTY 100, ...), so it is read, never assumed."""
        cs = await self.option_contracts(underlying_key)
        if not cs:
            raise LookupError(f"No live option contracts for {underlying_key}")
        expiries = sorted({date.fromisoformat(str(c["expiry"])[:10]) for c in cs})
        near = [c for c in cs if str(c["expiry"])[:10] == expiries[0].isoformat()]
        strikes = sorted({float(c["strike_price"]) for c in near})
        gaps = [b - a for a, b in zip(strikes, strikes[1:])]
        step = max(set(gaps), key=gaps.count) if gaps else None
        return {"expiries": expiries, "strike_step": step, "lot_size": int(cs[0].get("lot_size") or 0),
                "strikes": strikes, "contracts": cs}

    async def resolve_option(self, underlying_key: str, expiry: date, strike: float,
                             option_type: str) -> dict | None:
        """The contract for (expiry, strike, CE|PE) or None.  Live contracts come from
        /option/contract, past ones from /expired-instruments/option/contract; the
        instrument key differs, which is why `expired` is returned and must be passed on
        to `option_candles`."""
        if expiry >= datetime.now(IST).date():
            ek = expiry.isoformat()
            pool = [c for c in await self.option_contracts(underlying_key) if str(c["expiry"])[:10] == ek]
            expired = False
        else:
            pool, expired = await self.expired_option_contracts(underlying_key, expiry), True
        for c in pool:
            if float(c.get("strike_price", 0)) == float(strike) and c.get("instrument_type") == option_type:
                return {"trading_symbol": c["trading_symbol"], "instrument_key": c["instrument_key"],
                        "expired": expired, "lot_size": int(c.get("lot_size") or 0),
                        "expiry": expiry.isoformat(), "strike": float(strike), "option_type": option_type}
        return None

    # -----------------------------------------------------------------------
    # 5  candles
    # -----------------------------------------------------------------------
    async def candles(self, instrument_key: str, interval: str, frm: date, to: date) -> list[dict]:
        """OHLCV candles for any interval ('1m','3m','5m','15m','30m','1h','1d'), oldest
        first.  Upstox caps one request at a month (<=15m) or a quarter (30m, 1h), so the
        range is chunked.  Today's candles are added from the intraday endpoint for
        minute intervals, because the historical endpoint does not serve the current day.
        Each item: {timestamp, open, high, low, close, volume, oi}."""
        unit, n = _interval_unit(interval)
        key = quote(instrument_key, safe="")
        out: dict[str, dict] = {}
        today = datetime.now(IST).date()
        last = min(to, today - timedelta(days=1)) if unit == "minutes" else to
        cur = frm
        while cur <= last:
            end = min(_chunk_end(interval, cur), last)
            d = await self.get(f"{BASE_V3}/historical-candle/{key}/{unit}/{n}/{end.isoformat()}/{cur.isoformat()}")
            for raw in (d.get("data") or {}).get("candles") or []:
                c = _candle(raw)
                if c:
                    out[c["timestamp"]] = c
            cur = end + timedelta(days=1)
        if unit == "minutes" and frm <= today <= to:
            d = await self.get(f"{BASE_V3}/historical-candle/intraday/{key}/{unit}/{n}")
            for raw in (d.get("data") or {}).get("candles") or []:
                c = _candle(raw)
                if c and frm.isoformat() <= c["timestamp"][:10] <= to.isoformat():
                    out[c["timestamp"]] = c
        return [out[k] for k in sorted(out)]

    async def option_candles(self, contract: dict, day: date, interval_minutes: int = 1) -> list[list]:
        """One session of an option contract as [[HH:MM, o, h, l, c], ...] ([] if it did not trade).
        `contract` is what `resolve_option` returned.  Memoised for this run only (past days)."""
        key = quote(contract["instrument_key"], safe="")
        d_ = day.isoformat()
        today = datetime.now(IST).date()
        memo = (contract["instrument_key"], d_, interval_minutes)
        if memo in self._bars and day != today:
            return self._bars[memo]
        if contract["expired"]:
            url = f"{BASE_V2}/expired-instruments/historical-candle/{key}/{interval_minutes}minute/{d_}/{d_}"
        elif day == today:
            url = f"{BASE_V3}/historical-candle/intraday/{key}/minutes/{interval_minutes}"
        else:
            url = f"{BASE_V3}/historical-candle/{key}/minutes/{interval_minutes}/{d_}/{d_}"
        d = await self.get(url)
        raw = (d.get("data") or {}).get("candles") or []
        rows = sorted([c[0][11:16], float(c[1]), float(c[2]), float(c[3]), float(c[4])]
                      for c in raw if len(c) >= 5)
        self._bars[memo] = rows
        return rows


# ---------------------------------------------------------------------------
# 6  candle helpers
# ---------------------------------------------------------------------------
def _interval_unit(interval: str) -> tuple[str, int]:
    m = re.fullmatch(r"(\d+)([mhdw])", interval)
    if not m:
        raise ValueError(f"interval {interval!r}: use e.g. 1m 5m 15m 30m 1h 1d")
    return {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[m.group(2)], int(m.group(1))


def _chunk_end(interval: str, cur: date) -> date:
    unit, n = _interval_unit(interval)
    if unit == "minutes" and n <= 15:                            # one calendar month
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        return nxt - timedelta(days=1)
    if unit in ("minutes", "hours"):                             # one calendar quarter
        qm = ((cur.month - 1) // 3 + 1) * 3
        nxt = date(cur.year + (qm == 12), qm % 12 + 1, 1)
        return nxt - timedelta(days=1)
    return cur + timedelta(days=3650)


def _candle(raw: list) -> dict | None:
    if len(raw) < 5:
        return None
    return {"timestamp": raw[0], "open": float(raw[1]), "high": float(raw[2]), "low": float(raw[3]),
            "close": float(raw[4]), "volume": int(raw[5]) if len(raw) > 5 else 0,
            "oi": int(raw[6]) if len(raw) > 6 else 0}


def sessions_from(candles: list[dict]) -> dict[str, list[list]]:
    """{day: [[HH:MM, o, h, l, c], ...]} from the output of `Upstox.candles`."""
    out: dict[str, list[list]] = {}
    for c in candles:
        out.setdefault(c["timestamp"][:10], []).append(
            [c["timestamp"][11:16], c["open"], c["high"], c["low"], c["close"]])
    return {d: sorted(r) for d, r in sorted(out.items())}
