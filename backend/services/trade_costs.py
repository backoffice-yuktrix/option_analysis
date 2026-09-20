"""Capital and transaction costs for one NIFTY option lot - shared by every
strategy script so the numbers are computed one way.

CAPITAL PER LOT
    bought option   the premium paid (entry premium x lot size)
    sold option     SPAN + exposure margin.  The exchange sets SPAN from
                    volatility and no archive serves past values, so past nights
                    use a model calibrated on the broker's margin API on
                    2026-09-18 (index 23,346, lot 65, notional Rs 15.17 lakh):
                        sold ATM        SPAN 136,762  exposure 30,460  = 11.02% of notional
                        sold 2 OTM      SPAN 130,764  exposure 30,414  = 10.62%
                        sold 4 OTM      SPAN 125,070  exposure 30,387  = 10.24%
                        sold 6 OTM      SPAN 119,430  exposure 30,372  =  9.87%
                    exposure = 2.0% of notional; SPAN = 9.0% at the money,
                    falling ~0.38% per 100 points out of the money.  SPAN rises
                    with volatility, so the estimate runs LOW on panic nights.
                    `live_margin()` reads the broker's figure for a live contract.

TRANSACTION COSTS, one round trip (two orders), rates in force from 2024-10-01
    brokerage       Rs 20 per executed order (Upstox flat F&O rate)   x 2 orders
    STT             0.1%     of the SELL-side premium turnover
    exchange txn    0.03503% of the total premium turnover (NSE options)
    SEBI fee        Rs 10 per crore of turnover
    stamp duty      0.003%   of the BUY-side premium turnover
    GST             18% on brokerage + exchange + SEBI
Every trade here is squared off before expiry, so there is no exercise STT.
Rates are module constants: change them here when the schedule changes.
"""
from __future__ import annotations

import httpx

STRIKE_STEP = 50

# ---- capital -------------------------------------------------------------
EXPOSURE_RATE = 0.020
SPAN_RATE_ATM = 0.090
SPAN_DECAY_PER_100 = 0.0038
SPAN_RATE_FLOOR = 0.050
MARGIN_URL = "https://api.upstox.com/v2/charges/margin"

# ---- costs ---------------------------------------------------------------
BROKERAGE_PER_ORDER = 20.0
STT_SELL_RATE = 0.001
EXCHANGE_RATE = 0.0003503
SEBI_RATE = 10.0 / 1e7
STAMP_BUY_RATE = 0.00003
GST_RATE = 0.18


def capital_required(kind: str, spot: float, lot: int, entry_px: float | None,
                     offset_points: int = 0) -> float | None:
    """Rupees one lot ties up at entry.  `kind` is 'buy' or 'sell';
    `offset_points` is how far out of the money a SOLD strike sits."""
    if kind == "buy":
        return None if entry_px is None else round(entry_px * lot, 2)
    if spot is None:
        return None
    span = max(SPAN_RATE_FLOOR, SPAN_RATE_ATM - SPAN_DECAY_PER_100 * offset_points / 100.0)
    return round(spot * lot * (span + EXPOSURE_RATE), 2)


def round_trip_costs(buy_turnover: float, sell_turnover: float, orders: int = 2) -> dict:
    """Brokerage and statutory charges on one completed trade, from the rupee
    turnover of its buy leg and its sell leg."""
    brokerage = BROKERAGE_PER_ORDER * orders
    stt = STT_SELL_RATE * sell_turnover
    exchange = EXCHANGE_RATE * (buy_turnover + sell_turnover)
    sebi = SEBI_RATE * (buy_turnover + sell_turnover)
    stamp = STAMP_BUY_RATE * buy_turnover
    gst = GST_RATE * (brokerage + exchange + sebi)
    total = brokerage + stt + exchange + sebi + stamp + gst
    return {"brokerage": round(brokerage, 2), "stt": round(stt, 2), "exchange": round(exchange, 2),
            "sebi": round(sebi, 2), "stamp": round(stamp, 2), "gst": round(gst, 2),
            "total": round(total, 2)}


def option_round_trip(kind: str, entry_px: float, exit_px: float, lot: int) -> dict:
    """Costs of buying-then-selling ('buy') or selling-then-buying ('sell') one
    lot of an option at these premiums."""
    e, x = entry_px * lot, exit_px * lot
    if kind == "buy":
        return round_trip_costs(buy_turnover=e, sell_turnover=x)
    return round_trip_costs(buy_turnover=x, sell_turnover=e)


async def live_margin(client: httpx.AsyncClient, token: str, instrument_key: str,
                      kind: str, lot: int) -> float | None:
    """The broker's required margin for one lot right now; None if unavailable."""
    body = {"instruments": [{"instrument_key": instrument_key, "quantity": lot,
                             "transaction_type": "SELL" if kind == "sell" else "BUY",
                             "product": "D"}]}
    try:
        r = await client.post(MARGIN_URL, json=body, timeout=30.0,
                              headers={"Authorization": f"Bearer {token}",
                                       "Accept": "application/json",
                                       "Content-Type": "application/json"})
        v = (r.json().get("data") or {}).get("required_margin")
        return round(float(v), 2) if v is not None else None
    except Exception as exc:                                  # noqa: BLE001
        print(f"  ! margin lookup failed: {exc}")
        return None
