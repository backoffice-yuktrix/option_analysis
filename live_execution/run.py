"""Launch the live execution server.  Run from this folder:

    python run.py                    # paper mode: simulated fills, no real orders
    python run.py --live             # REAL orders on your Upstox account
    python run.py --strategies buy   # only MyStrategy_Buy

Open http://127.0.0.1:8000 for the monitoring page.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="send real orders to Upstox")
    parser.add_argument("--yes", action="store_true", help="skip the live-mode confirmation prompt")
    parser.add_argument("--strategies", default="buy,sell", help="comma list of: buy, sell")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.live and not args.yes:
        answer = input("LIVE MODE places REAL market orders with real money. Type YES to continue: ")
        if answer.strip() != "YES":
            sys.exit("Aborted.")

    os.environ["LIVE_MODE"] = "live" if args.live else "paper"
    os.environ["LIVE_STRATEGIES"] = args.strategies
    print(f"Mode: {os.environ['LIVE_MODE']}   strategies: {args.strategies}")
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
