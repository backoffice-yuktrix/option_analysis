"""Price a spot-triggered signal as the ATM option that would actually be bought.

WHY THIS EXISTS
---------------
Every backtest in backend/scripts decides its entries and exits on NIFTY SPOT,
and several of them then reported rupee PnL as `spot points x LOT_SIZE`.  That
is the payoff of a NIFTY FUTURES lot.  It is NOT what a bought option pays: the
premium moves at delta, and it bleeds theta while the position is held.

Measured on reversal_v3's own 868 traded rows, the option premium moved a
MEDIAN of 0.546 of the underlying move (mean 0.584).  Over that whole book the
premium made +3,599.7 points (Rs 233,982) where `spot points x 65` would have
claimed +5,325.7 points (Rs 346,173) - a 48% overstatement.  A flat delta
factor is not a fix either, because it cannot show theta: it would scale the
headline and still hide the decay on a position held for hours.

So the only honest answer is to resolve the contract that would really have
been bought and read its real 1-minute prices.  reversal_v3 already did that;
this module is that logic lifted out so the other strategies share it instead
of each growing their own copy.  The copies are the reason the earlier bugs
(abs() risk, stale paths, drifted docstring counts) went unnoticed for so long.

WHAT IT ASSUMES, STATED ONCE
----------------------------
  strike     ATM = round(spot at entry / 50) * 50
  expiry     the nearest expiry on or AFTER the trade date, so an entry on
             expiry day is priced on that day's 0-DTE contract - which is
             where theta is most brutal, and that is the point.
  direction  the position is always LONG PREMIUM: a bullish signal buys the
             ATM CE, a bearish one buys the ATM PE.  A short signal is NOT
             modelled as a written option.
  fills      the contract's 1-minute CLOSE at the entry minute and at the exit
             minute.  The spot exit can happen inside a minute (a stop touch),
             so this is an approximation - the same one reversal_v3 makes.
  missing    when the contract or its candles cannot be had, the trade is
             returned with premium fields None and `reason` set.  It is the
             CALLER's job to keep showing that trade and exclude it from money
             aggregates.  Do not let it silently vanish from the book.

Caches (shared by every strategy, so a contract fetched once is never fetched
again) live in backend/data:
    nifty_expiry_cache.json     the expiry calendar
    nifty_contract_cache.json   expiry|strike|type  -> instrument_key
    nifty_option_cache.json     instrument_key|day  -> {"HH:MM": close}
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date, timedelta
from urllib.parse import quote

import httpx

SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(SERVICES_DIR, "..")
DATA_DIR = os.path.join(BACKEND_DIR, "data")

EXPIRY_CACHE = os.path.join(DATA_DIR, "nifty_expiry_cache.json")
CONTRACT_CACHE = os.path.join(DATA_DIR, "nifty_contract_cache.json")
OPTION_CACHE = os.path.join(DATA_DIR, "nifty_option_cache.json")

# Seeded from the reversal_v* runs so their fetches are not repeated.
LEGACY_CONTRACT_CACHE = os.path.join(DATA_DIR, "reversal_contract_cache.json")
LEGACY_OPTION_CACHE = os.path.join(DATA_DIR, "reversal_option_cache.json")
LEGACY_EXPIRY_CACHE = os.path.join(DATA_DIR, "reversal_expiry_cache.json")

BASE_V2 = "https://api.upstox.com/v2"
STRIKE_STEP = 50

from services.upstox_client import (  # noqa: E402
    INSTRUMENT_KEYS, get_option_contracts)

UNDERLYING_KEY = INSTRUMENT_KEYS["NIFTY"]


def atm_strike(spot: float) -> float:
    return float(round(spot / STRIKE_STEP) * STRIKE_STEP)


def _load(path: str, fallback: str | None = None):
    for p in (path, fallback):
        if p and os.path.exists(p):
            try:
                with open(p) as f:
                    return json.load(f)
            except (OSError, ValueError):
                continue
    return None


class RateLimiter:
    def __init__(self, interval: float = 0.25) -> None:
        self._interval = interval
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now < self._next_at:
                await asyncio.sleep(self._next_at - now)
                now = loop.time()
            self._next_at = now + self._interval


async def api_get(client: httpx.AsyncClient, url: str, token: str,
                  limiter: RateLimiter, params: dict | None = None, *,
                  retries: int = 4) -> dict:
    delay = 2.0
    for attempt in range(retries + 1):
        await limiter.wait()
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        try:
            resp = await client.get(url, headers=headers, params=params)
        except httpx.RequestError as exc:
            if attempt == retries:
                raise RuntimeError(f"network error for {url}: {exc}") from exc
            await asyncio.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            await asyncio.sleep(delay)
            delay *= 2
            continue
        raise RuntimeError(f"Upstox HTTP {resp.status_code} for {url}: {resp.text[:200]}")
    raise RuntimeError(f"exhausted retries for {url}")


async def _expired_expiries(client, token, limiter) -> list[date]:
    data = await api_get(client, f"{BASE_V2}/expired-instruments/expiries", token,
                         limiter, {"instrument_key": UNDERLYING_KEY})
    return sorted(date.fromisoformat(s) for s in data.get("data", []) or [])


async def _expired_contracts(client, token, limiter, expiry: date) -> list[dict]:
    data = await api_get(client, f"{BASE_V2}/expired-instruments/option/contract",
                         token, limiter,
                         {"instrument_key": UNDERLYING_KEY,
                          "expiry_date": expiry.isoformat()})
    return data.get("data", []) or []


async def _day_candles(client, token, limiter, instrument_key: str,
                       expired: bool, day: date) -> dict[str, float]:
    """{"HH:MM": close} of the contract's 1-minute candles for one session."""
    key_enc = quote(instrument_key, safe="")
    if expired:
        url = (f"{BASE_V2}/expired-instruments/historical-candle/{key_enc}"
               f"/1minute/{day.isoformat()}/{day.isoformat()}")
    else:
        url = (f"https://api.upstox.com/v3/historical-candle/{key_enc}"
               f"/minutes/1/{day.isoformat()}/{day.isoformat()}")
    data = await api_get(client, url, token, limiter)
    raw = (data.get("data", {}) or {}).get("candles", []) or []
    return {c[0][11:16]: float(c[4]) for c in raw if len(c) >= 5}


def _candle_keys(contract: dict, day: str) -> list[str]:
    """Every spelling a contract's day may be cached under, stable one first.

    A contract cached while LIVE carries an undated instrument key
    (NSE_FO|45104); once expired the same contract resolves to a dated one
    (NSE_FO|45104|18-08-2026).  Candles written under one spelling were
    invisible under the other, which is how a fully-available day showed as
    'no option candles'.  The stable key is the contract's identity, which
    never changes.
    """
    keys = []
    if contract.get("ckey"):
        keys.append(f"{contract['ckey']}|{day}")
    ik = contract["instrument_key"]
    keys.append(f"{ik}|{day}")
    parts = ik.split("|")
    if len(parts) == 3:                         # dated -> also try undated
        keys.append(f"{parts[0]}|{parts[1]}|{day}")
    return keys


class OptionPricer:
    """Resolves contracts and serves their 1-minute closes, caching everything."""

    def __init__(self, client, token, limiter, offline: bool) -> None:
        self.client, self.token, self.limiter = client, token, limiter
        self.offline = offline
        self.contracts: dict = _load(CONTRACT_CACHE, LEGACY_CONTRACT_CACHE) or {}
        self.candles: dict = _load(OPTION_CACHE, LEGACY_OPTION_CACHE) or {}
        cal = _load(EXPIRY_CACHE, LEGACY_EXPIRY_CACHE) or []
        self.expiries: list[date] = sorted(date.fromisoformat(s) for s in cal)
        self.live_by_key: dict = {}
        self.live_expiries: set[date] = set()
        self._expired_by_expiry: dict[str, list[dict]] = {}
        self.fetched_contracts = 0
        self.fetched_days = 0

    # -- calendar --------------------------------------------------------
    async def load_calendar(self, from_date: date, to_date: date) -> None:
        if self.offline or not self.token:
            return
        try:
            exp = [e for e in await _expired_expiries(self.client, self.token, self.limiter)
                   if from_date - timedelta(days=7) <= e <= to_date + timedelta(days=30)]
            self.expiries = sorted(set(self.expiries) | set(exp))
        except RuntimeError as exc:
            print(f"  ! expired-expiries lookup failed ({exc}); using the cached calendar")
        try:
            live = await get_option_contracts(self.token, "NIFTY")
            self.live_by_key = {(c["expiry"][:10], c["strike"], c["option_type"]): c
                                for c in live}
            self.live_expiries = {date.fromisoformat(c["expiry"][:10]) for c in live}
            self.expiries = sorted(set(self.expiries) | self.live_expiries)
        except Exception as exc:                                   # noqa: BLE001
            print(f"  ! live option contracts lookup failed ({exc})")
        self.save()

    def expiries_for(self, d: date, limit: int = 3) -> list[date]:
        return [e for e in self.expiries if e >= d][:limit]

    # -- contracts -------------------------------------------------------
    async def _resolve(self, expiry: date, strike: float, opt: str) -> dict | None:
        key = f"{expiry.isoformat()}|{strike:.0f}|{opt}"
        if key in self.contracts:
            c = self.contracts[key]
            if c:
                c = dict(c, ckey=key)
            # A contract cached while it was LIVE keeps a key with no expiry
            # suffix and expired=False.  Once its expiry has passed, the live
            # candle endpoint rejects that key ("Invalid Instrument key"), so
            # the entry has to be re-resolved through the expired-contract
            # list, which carries the dated key.  Drop it and fall through.
            if not (c and not c.get("expired") and expiry < date.today()
                    and not self.offline and self.token):
                return c
        if self.offline or not self.token:
            return None
        found = None
        if expiry in self.live_expiries:
            c = self.live_by_key.get((expiry.isoformat(), strike, opt))
            if c:
                found = {"trading_symbol": c["trading_symbol"],
                         "instrument_key": c["instrument_key"], "expired": False,
                         "lot_size": int(c.get("lot_size") or 0)}
        else:
            ek = expiry.isoformat()
            if ek not in self._expired_by_expiry:
                try:
                    self._expired_by_expiry[ek] = await _expired_contracts(
                        self.client, self.token, self.limiter, expiry)
                except RuntimeError as exc:
                    print(f"  ! contracts for expiry {ek}: {exc}")
                    return None          # transient - do not cache a miss
            for c in self._expired_by_expiry[ek]:
                if (float(c.get("strike_price", 0)) == strike
                        and c.get("instrument_type") == opt):
                    found = {"trading_symbol": c["trading_symbol"],
                             "instrument_key": c["instrument_key"], "expired": True,
                             "lot_size": int(c.get("lot_size") or 0)}
                    break
        self.contracts[key] = found
        self.fetched_contracts += 1
        return dict(found, ckey=key) if found else None

    async def contract_for(self, day: date, strike: float, opt: str) -> dict | None:
        for expiry in self.expiries_for(day):
            c = await self._resolve(expiry, strike, opt)
            if c:
                return c
        return None

    # -- prices ----------------------------------------------------------
    async def candles_for(self, contract: dict, day: date) -> dict[str, float]:
        for k in _candle_keys(contract, day.isoformat()):
            if self.candles.get(k):
                return self.candles[k]
        key = _candle_keys(contract, day.isoformat())[0]
        if (not contract.get("expired") and contract.get("ckey")
                and date.fromisoformat(contract["ckey"].split("|")[0]) < date.today()
                and not self.offline and self.token):
            # cached while live (undated key, expired=False) but its expiry has
            # now passed: the live endpoint rejects it, so re-resolve through the
            # expired-contract list to get the dated key.  Decided on the
            # contract's OWN expiry - the earlier "day older than a week" guess
            # wrongly sent still-live far-expiry contracts to the expired
            # endpoint, which rejects undated keys ("invalid format").
            exp = date.fromisoformat(contract["ckey"].split("|")[0])
            strike, opt = float(contract["ckey"].split("|")[1]), contract["ckey"].split("|")[2]
            self.contracts.pop(contract["ckey"], None)
            fresh = await self._resolve(exp, strike, opt)
            if fresh:
                contract = fresh
        if self.offline or not self.token:
            return {}
        try:
            got = await _day_candles(self.client, self.token, self.limiter,
                                     contract["instrument_key"], contract["expired"], day)
        except RuntimeError as exc:
            print(f"  ! candles {contract['trading_symbol']} {day}: {exc}")
            return {}                    # transient - do not cache the empty result
        self.candles[key] = got
        self.fetched_days += 1
        return got

    def save(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CONTRACT_CACHE, "w") as f:
            json.dump(self.contracts, f, indent=0)
        with open(OPTION_CACHE, "w") as f:
            json.dump(self.candles, f)
        with open(EXPIRY_CACHE, "w") as f:
            json.dump([e.isoformat() for e in self.expiries], f, indent=0)

    # -- the thing callers actually want ---------------------------------
    async def price(self, day: str, side: str, spot_entry: float,
                    entry_hhmm: str, exit_hhmm: str | None) -> dict:
        """Premium for one spot-triggered trade.

        `side` is LONG or SHORT; LONG buys the ATM CE, SHORT the ATM PE.
        Always returns a dict - never raises - with `reason` set when the
        trade could not be priced, so the caller can show it and leave it out
        of the money totals.
        """
        d = date.fromisoformat(day)
        strike = atm_strike(spot_entry)
        opt = "CE" if side == "LONG" else "PE"
        out = {"strike": strike, "option_type": opt, "symbol": None,
               "entry_px": None, "exit_px": None, "prem_pts": None,
               "reason": None}
        contract = await self.contract_for(d, strike, opt)
        if not contract:
            out["reason"] = "no contract"
            return out
        out["symbol"] = contract["trading_symbol"]
        candles = await self.candles_for(contract, d)
        if not candles:
            out["reason"] = "no option candles"
            return out
        entry_px = candles.get(entry_hhmm)
        exit_px = candles.get(exit_hhmm) if exit_hhmm else None
        if entry_px is None:
            out["reason"] = f"no premium at entry {entry_hhmm}"
            return out
        out["entry_px"] = round(entry_px, 2)
        if exit_px is None:
            out["reason"] = f"no premium at exit {exit_hhmm}"
            return out
        out["exit_px"] = round(exit_px, 2)
        # long premium either way, so the option's own move IS the PnL
        out["prem_pts"] = round(exit_px - entry_px, 2)
        return out


async def open_pricer(token: str | None, offline: bool,
                      from_date: date, to_date: date):
    """Async context helper: an OptionPricer with its calendar loaded."""
    client = httpx.AsyncClient(timeout=30.0)
    pricer = OptionPricer(client, token, RateLimiter(), offline or not token)
    await pricer.load_calendar(from_date, to_date)
    return pricer, client


class CachedPricer:
    """Synchronous, network-free pricing straight out of the shared caches.

    The strategy scripts use THIS, not OptionPricer: by report time every
    contract has already been fetched (one fetch pulls a contract's whole day,
    so every stop-rule / target variant reads its own exit minute out of the
    same cached day).  Keeping the scripts off the network means a report can
    always be regenerated offline, and it keeps the async plumbing in one place.

    Returns a dict for EVERY trade, priced or not.  When it could not be
    priced, `prem_pts` is None and `reason` says why - the caller must still
    show that trade and leave it out of the money totals.
    """

    def __init__(self) -> None:
        self.contracts: dict = _load(CONTRACT_CACHE, LEGACY_CONTRACT_CACHE) or {}
        self.candles: dict = _load(OPTION_CACHE, LEGACY_OPTION_CACHE) or {}
        cal = _load(EXPIRY_CACHE, LEGACY_EXPIRY_CACHE) or []
        self.expiries = sorted(date.fromisoformat(s) for s in cal)

    def _contract(self, day: date, strike: float, opt: str) -> dict | None:
        for expiry in [e for e in self.expiries if e >= day][:3]:
            key = f"{expiry.isoformat()}|{strike:.0f}|{opt}"
            c = self.contracts.get(key)
            if c:
                return dict(c, ckey=key)
        return None

    def day_prices(self, day: str, side: str, spot_entry: float) -> dict:
        """{'symbol','strike','option_type','candles'} for the contract a trade
        on this day and side would have bought.  `candles` is {'HH:MM': close}
        for the whole session, so any exit minute can be looked up."""
        d = date.fromisoformat(day)
        strike = atm_strike(spot_entry)
        opt = "CE" if side == "LONG" else "PE"
        out = {"strike": strike, "option_type": opt, "symbol": None,
               "candles": {}, "reason": None}
        c = self._contract(d, strike, opt)
        if not c:
            out["reason"] = "no contract"
            return out
        out["symbol"] = c["trading_symbol"]
        out["candles"] = next((self.candles[k] for k in _candle_keys(c, day)
                               if self.candles.get(k)), {})
        if not out["candles"]:
            out["reason"] = "no option candles"
        return out

    def price(self, day: str, side: str, spot_entry: float,
              entry_hhmm: str, exit_hhmm: str | None) -> dict:
        info = self.day_prices(day, side, spot_entry)
        out = {"strike": info["strike"], "option_type": info["option_type"],
               "symbol": info["symbol"], "entry_px": None, "exit_px": None,
               "prem_pts": None, "reason": info["reason"]}
        if info["reason"]:
            return out
        return self.price_from(info, entry_hhmm, exit_hhmm)

    @staticmethod
    def price_from(info: dict, entry_hhmm: str, exit_hhmm: str | None) -> dict:
        """Same as price(), reusing an already-fetched day - the hot path when
        one trade is scored under ten different exit variants."""
        out = {"strike": info["strike"], "option_type": info["option_type"],
               "symbol": info["symbol"], "entry_px": None, "exit_px": None,
               "prem_pts": None, "reason": None}
        candles = info["candles"]
        entry_px = candles.get(entry_hhmm)
        if entry_px is None:
            out["reason"] = f"no premium at entry {entry_hhmm}"
            return out
        out["entry_px"] = round(entry_px, 2)
        exit_px = candles.get(exit_hhmm) if exit_hhmm else None
        if exit_px is None:
            out["reason"] = f"no premium at exit {exit_hhmm}"
            return out
        out["exit_px"] = round(exit_px, 2)
        out["prem_pts"] = round(exit_px - entry_px, 2)
        return out


    def reload(self) -> None:
        """Re-read the caches after a fetch pass has topped them up."""
        self.__init__()


async def ensure_cached(needs, token: str | None, offline: bool = False) -> "CachedPricer":
    """Fetch whatever the requested date range needs, then hand back a pricer.

    `needs` is an iterable of (day, side, spot_entry) - one per SIGNAL, taken
    from a simulation that has already run on spot.  That ordering matters and
    is the whole design: the underlying decides entry, stop and target, and the
    option is resolved afterwards only to put a rupee figure on the result.
    Nothing here can move a level or change which trades exist.

    One fetch pulls a contract's WHOLE day, so the unit of work is a distinct
    (day, strike, type) and every stop-rule / target variant then reads its own
    exit minute out of the same cached day.  Anything already cached is skipped,
    so re-running the same window costs nothing.
    """
    want = {(d, atm_strike(spot), "CE" if side == "LONG" else "PE")
            for d, side, spot in needs}
    pricer = CachedPricer()
    missing = []
    for day, strike, opt in sorted(want):
        info = pricer.day_prices(day, "LONG" if opt == "CE" else "SHORT", strike)
        if not info["reason"]:
            continue
        missing.append((day, strike, opt))
    if not missing:
        return pricer
    if offline or not token:
        print(f"  ! {len(missing)} option series missing and no token "
              f"(offline={offline}) - those trades will show 'no option data'")
        return pricer
    print(f"  fetching {len(missing)} option series for the requested range ...")
    client = httpx.AsyncClient(timeout=30.0)
    op = OptionPricer(client, token, RateLimiter(), offline=False)
    await op.load_calendar(date.fromisoformat(min(m[0] for m in missing)),
                           date.fromisoformat(max(m[0] for m in missing)))
    got = 0
    for i, (day, strike, opt) in enumerate(missing, 1):
        d = date.fromisoformat(day)
        contract = await op.contract_for(d, strike, opt)
        if contract and await op.candles_for(contract, d):
            got += 1
        if i % 25 == 0:
            op.save()
    op.save()
    await client.aclose()
    print(f"  fetched {got}/{len(missing)} (contracts {op.fetched_contracts}, "
          f"days {op.fetched_days})")
    pricer.reload()
    return pricer


# ---------------------------------------------------------------------------
# Compatibility shims for the reversal_v* scripts
# ---------------------------------------------------------------------------
#
# Those four scripts each grew their own copy of the two classes below, and the
# copies had already drifted apart (four different hashes for the same logic).
# These shims keep their call sites working verbatim while routing every fetch
# and every cache write through the SHARED store above, so a contract resolved
# by one strategy is never fetched again by another.

class ContractResolver:
    """Same surface the reversal scripts already call, shared cache underneath."""

    def __init__(self, client, token, limiter, all_expiries, live_expiries,
                 live_by_key, offline) -> None:
        self._p = OptionPricer(client, token, limiter, offline)
        if all_expiries:
            self._p.expiries = sorted(set(self._p.expiries) | set(all_expiries))
        self._p.live_expiries = set(live_expiries or [])
        self._p.live_by_key = live_by_key or {}

    @property
    def cache(self):
        return self._p.contracts

    def expiries_for(self, d: date, limit: int = 3) -> list[date]:
        return self._p.expiries_for(d, limit)

    async def resolve(self, expiry: date, strike: float, option_type: str):
        return await self._p._resolve(expiry, strike, option_type)

    def save(self) -> None:
        self._p.save()


class OptionCandleStore:
    """Same surface, shared cache underneath."""

    def __init__(self, client, token, limiter, offline) -> None:
        self._p = OptionPricer(client, token, limiter, offline)

    @property
    def cache(self):
        return self._p.candles

    async def get(self, contract: dict, day: date) -> dict[str, float]:
        return await self._p.candles_for(contract, day)

    def save(self) -> None:
        self._p.save()


get_expired_expiries = _expired_expiries

get_expired_option_contracts = _expired_contracts

get_option_day_candles = _day_candles