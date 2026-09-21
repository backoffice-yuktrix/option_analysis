"""Place a sample 1-lot NIFTY option order on Upstox.  Run from anywhere:

    python place_sample_order.py                       # dry run: resolve contract, print payload
    python place_sample_order.py --place --price 5.0   # really send a LIMIT order
    python place_sample_order.py --market --place      # really send a MARKET order
    python place_sample_order.py --status ORDER_ID     # check an order
    python place_sample_order.py --cancel ORDER_ID     # cancel an open order

Reads the access token from line 4 of upstox_config.txt (see connect_upstox.py).
Default is a dry run: nothing is sent to the order endpoint without --place.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import httpx

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upstox_config.txt")
API = "https://api.upstox.com"
HFT_API = "https://api-hft.upstox.com"
UNDERLYING_KEY = "NSE_INDEX|Nifty 50"
EXPIRY = "2026-09-22"
STRIKE = 23600.0
OPTION_TYPE = "CE"
LOTS = 1


def read_token() -> str:
    if not os.path.exists(CONFIG_FILE):
        sys.exit(f"Missing {CONFIG_FILE}. Run connect_upstox.py first.")
    with open(CONFIG_FILE, encoding="utf-8") as f:
        lines = [l.strip() for l in f.read().splitlines()]
    if len(lines) < 4 or not lines[3]:
        sys.exit("No access token on line 4 of upstox_config.txt. Run connect_upstox.py first.")
    return lines[3]


def headers(token: str) -> dict[str, str]:
    return {"Accept": "application/json", "Authorization": f"Bearer {token}"}


def fail(resp: httpx.Response) -> None:
    sys.exit(f"Upstox HTTP {resp.status_code}: {resp.text[:500]}")


def find_contract(token: str) -> dict:
    resp = httpx.get(
        f"{API}/v2/option/contract",
        params={"instrument_key": UNDERLYING_KEY, "expiry_date": EXPIRY},
        headers=headers(token),
        timeout=30.0,
    )
    if resp.status_code != 200:
        fail(resp)
    for c in resp.json().get("data", []):
        if float(c.get("strike_price", 0)) == STRIKE and c.get("instrument_type") == OPTION_TYPE:
            return c
    sys.exit(f"No {OPTION_TYPE} {STRIKE:g} contract found for expiry {EXPIRY}.")


def get_ltp(token: str, instrument_key: str) -> float | None:
    resp = httpx.get(
        f"{API}/v3/market-quote/ltp",
        params={"instrument_key": instrument_key},
        headers=headers(token),
        timeout=30.0,
    )
    if resp.status_code != 200:
        return None
    for quote in resp.json().get("data", {}).values():
        return quote.get("last_price")
    return None


def place(token: str, args: argparse.Namespace) -> None:
    contract = find_contract(token)
    lot_size = int(contract["lot_size"])
    quantity = lot_size * LOTS
    key = contract["instrument_key"]
    expiry_ms = contract.get("expiry")
    expiry_txt = (
        datetime.fromtimestamp(expiry_ms / 1000, tz=timezone.utc).date().isoformat()
        if isinstance(expiry_ms, (int, float)) else EXPIRY
    )
    print(f"Contract : {contract.get('trading_symbol')}  key={key}  expiry={expiry_txt}")
    print(f"Lot size : {lot_size}   quantity to send: {quantity}   freeze qty: {contract.get('freeze_quantity')}")
    print(f"LTP      : {get_ltp(token, key)}")

    tick = float(contract.get("tick_size") or 0.05)
    if args.market:
        price = 0.0
    else:
        if args.price is None:
            print("\nNo --price or --market given. Dry run only.")
            return
        if abs(round(args.price / tick) * tick - args.price) > 1e-9 or args.price <= 0:
            sys.exit(f"--price must be positive and a multiple of tick size {tick}.")
        price = args.price

    body = {
        "quantity": quantity,
        "product": args.product,
        "validity": "DAY",
        "price": price,
        "tag": "sample-order",
        "instrument_token": key,
        "order_type": "MARKET" if args.market else "LIMIT",
        "transaction_type": args.side,
        "disclosed_quantity": 0,
        "trigger_price": 0,
        "is_amo": False,
        "slice": False,
    }
    if args.market:
        body["market_protection"] = -1
    print("\nOrder payload:")
    print(json.dumps(body, indent=2))
    if not args.place:
        print("\nDRY RUN: nothing sent. Add --place to send it.")
        return

    resp = httpx.post(
        f"{HFT_API}/v3/order/place",
        json=body,
        headers={**headers(token), "Content-Type": "application/json"},
        timeout=30.0,
    )
    print(f"\nHTTP {resp.status_code}")
    print(resp.text)


def status(token: str, order_id: str) -> None:
    resp = httpx.get(
        f"{API}/v2/order/details",
        params={"order_id": order_id},
        headers=headers(token),
        timeout=30.0,
    )
    print(f"HTTP {resp.status_code}")
    print(resp.text)


def cancel(token: str, order_id: str) -> None:
    resp = httpx.delete(
        f"{HFT_API}/v3/order/cancel",
        params={"order_id": order_id},
        headers=headers(token),
        timeout=30.0,
    )
    print(f"HTTP {resp.status_code}")
    print(resp.text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample 1-lot NIFTY 23600 CE 22-SEP-2026 order")
    parser.add_argument("--price", type=float, help="LIMIT price per unit")
    parser.add_argument("--market", action="store_true", help="MARKET order (price 0, auto market protection)")
    parser.add_argument("--side", choices=["BUY", "SELL"], default="BUY")
    parser.add_argument("--product", choices=["I", "D"], default="I", help="I=intraday, D=delivery/carry")
    parser.add_argument("--place", action="store_true", help="actually send the order")
    parser.add_argument("--status", metavar="ORDER_ID")
    parser.add_argument("--cancel", metavar="ORDER_ID")
    args = parser.parse_args()

    token = read_token()
    if args.status:
        status(token, args.status)
    elif args.cancel:
        cancel(token, args.cancel)
    else:
        place(token, args)


if __name__ == "__main__":
    main()
