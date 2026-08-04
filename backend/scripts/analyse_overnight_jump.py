"""Overnight-jump analysis: buy ATM call+put near the close, sell them the next morning.

Strategy being back-tested, per trading day T:
  1. Take the NIFTY 15:25 candle close as the reference spot price; ATM strike
     = that price rounded to the nearest 50.
  2. Pick the nearest upcoming NIFTY expiry. If T itself IS that expiry's
     date (the contract would already be dead on T+1), roll to the next
     expiry instead, since the position is held overnight.
  3. Buy price = high(ATM call, 15:25-15:29) + high(ATM put, 15:25-15:29)
     (highs can occur on different minutes for each leg).
  4. On the next trading day T+1, for every 1-minute candle from 09:15 to
     10:59 (105 candles), sell price = low(call) + low(put) at that minute.
  5. diff% = (sell_price - buy_price) / buy_price * 100, one value per minute.
  6. Bucket every diff% into 8 bins (4 loss magnitudes, 4 profit magnitudes)
     and roll the distribution up by day / week / month into an HTML report.

Data sources:
  - NIFTY spot candles: read from nifty_jan1_july31.json (run
    fetch_nifty_jan1_july31.py first). Also fixes the trading-day calendar,
    so "next trading day" is just the next date present in that file.
  - Option contracts/candles: Upstox live /option/contract + historical-candle
    for expiries that haven't happened yet (via services/upstox_client.py),
    and the Expired Instruments API (Upstox Plus) for everything else — same
    approach as check_past_expiry_data.py. A hardcoded 2026 H1 expiry
    calendar (FALLBACK_EXPIRIES_2026) fills in if Upstox's expiry-list
    endpoint doesn't reach far enough back.

Run from backend/ (after fetch_nifty_jan1_july31.py has produced the JSON):
    python scripts/analyse_overnight_jump.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import quote

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.upstox_client import get_candles, get_option_contracts, INSTRUMENT_KEYS  # noqa: E402

SCRIPT_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(SCRIPT_DIR, "..", "upstox_config.txt")
NIFTY_JSON = os.path.join(SCRIPT_DIR, "nifty_jan1_july31.json")
REPORT_HTML = os.path.join(SCRIPT_DIR, "overnight_jump_report.html")

BASE_V2 = "https://api.upstox.com/v2"
UNDERLYING = "NIFTY"
UNDERLYING_KEY = INSTRUMENT_KEYS[UNDERLYING]
STRIKE_STEP = 50

RANGE_FROM = date(2026, 1, 1)
RANGE_TO = date(2026, 7, 31)

BUY_TIMES = ["15:25", "15:26", "15:27", "15:28", "15:29"]
SELL_START, SELL_END = "09:15", "10:59"

FALLBACK_EXPIRIES_2026: list[date] = [
    date(2026, 1, 6), date(2026, 1, 13), date(2026, 1, 20), date(2026, 1, 27),
    date(2026, 2, 3), date(2026, 2, 10), date(2026, 2, 17), date(2026, 2, 24),
    date(2026, 3, 2), date(2026, 3, 10), date(2026, 3, 17), date(2026, 3, 24), date(2026, 3, 30),
    date(2026, 4, 7), date(2026, 4, 13), date(2026, 4, 21), date(2026, 4, 28),
    date(2026, 5, 5), date(2026, 5, 12), date(2026, 5, 19), date(2026, 5, 26),
    date(2026, 6, 2), date(2026, 6, 9), date(2026, 6, 16), date(2026, 6, 23), date(2026, 6, 30),
    date(2026, 7, 7), date(2026, 7, 14), date(2026, 7, 21), date(2026, 7, 28),
]

BINS = [
    ("loss >10%", lambda p: p <= -10),
    ("loss 5-10%", lambda p: -10 < p <= -5),
    ("loss 1-5%", lambda p: -5 < p <= -1),
    ("loss 0-1%", lambda p: -1 < p < 0),
    ("profit 0-1%", lambda p: 0 <= p < 1),
    ("profit 1-5%", lambda p: 1 <= p < 5),
    ("profit 5-10%", lambda p: 5 <= p < 10),
    ("profit >10%", lambda p: p >= 10),
]


def classify(pct: float) -> int:
    for idx, (_, test) in enumerate(BINS):
        if test(pct):
            return idx
    return -1


def _read_access_token() -> str:
    with open(CONFIG_FILE) as f:
        lines = [l.strip() for l in f.readlines()]
    if len(lines) < 4 or not lines[3]:
        raise RuntimeError(f"No access_token found in {CONFIG_FILE}. Connect to Upstox first.")
    return lines[3]


async def _get(url: str, token: str, params: dict | None = None) -> dict:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code == 200:
        return resp.json()
    raise RuntimeError(f"Upstox HTTP {resp.status_code} for {url}: {resp.text[:300]}")


async def get_expired_expiries(token: str, instrument_key: str) -> list[date]:
    data = await _get(f"{BASE_V2}/expired-instruments/expiries", token, {"instrument_key": instrument_key})
    return sorted(date.fromisoformat(s) for s in data.get("data", []) or [])


async def get_expired_option_contracts(token: str, instrument_key: str, expiry: date) -> list[dict]:
    data = await _get(
        f"{BASE_V2}/expired-instruments/option/contract",
        token,
        {"instrument_key": instrument_key, "expiry_date": expiry.isoformat()},
    )
    return data.get("data", []) or []


async def get_expired_candles(token: str, expired_instrument_key: str, from_date: date, to_date: date) -> list[dict]:
    key_enc = quote(expired_instrument_key, safe="")
    url = f"{BASE_V2}/expired-instruments/historical-candle/{key_enc}/1minute/{to_date.isoformat()}/{from_date.isoformat()}"
    data = await _get(url, token)
    raw = (data.get("data", {}) or {}).get("candles", [])
    return [
        {"timestamp": c[0], "high": float(c[2]), "low": float(c[3])}
        for c in raw
        if len(c) >= 5
    ]


def _load_nifty_by_day() -> dict[str, dict[str, dict]]:
    if not os.path.exists(NIFTY_JSON):
        raise RuntimeError(f"{NIFTY_JSON} not found. Run fetch_nifty_jan1_july31.py first.")
    with open(NIFTY_JSON) as f:
        candles = json.load(f)
    by_day: dict[str, dict[str, dict]] = defaultdict(dict)
    for c in candles:
        day, time_part = c["timestamp"][:10], c["timestamp"][11:16]
        by_day[day][time_part] = c
    return by_day


def _week_key(d: date) -> str:
    monday = d - timedelta(days=d.weekday())
    return f"Week of {monday.isoformat()}"


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


async def main() -> None:
    token = _read_access_token()

    nifty_by_day = _load_nifty_by_day()
    trading_days = sorted(nifty_by_day.keys())
    print(f"Loaded {len(trading_days)} trading days from {NIFTY_JSON}")

    expired_expiries = [e for e in await get_expired_expiries(token, UNDERLYING_KEY) if RANGE_FROM <= e <= RANGE_TO]
    live_contracts = await get_option_contracts(token, UNDERLYING)
    live_expiries = sorted({date.fromisoformat(c["expiry"][:10]) for c in live_contracts})
    fallback_expiries = [e for e in FALLBACK_EXPIRIES_2026 if RANGE_FROM <= e <= RANGE_TO]
    all_expiries = sorted(set(expired_expiries) | set(live_expiries) | set(fallback_expiries))
    print(f"Known expiries in range: {[e.isoformat() for e in all_expiries]}")

    live_by_key: dict[tuple[str, float, str], dict] = {
        (c["expiry"][:10], c["strike"], c["option_type"]): c for c in live_contracts
    }
    live_expiry_set = set(live_expiries)
    expired_contracts_cache: dict[date, list[dict]] = {}

    def nearest_trade_expiry(d: date) -> date | None:
        idx = None
        for i, e in enumerate(all_expiries):
            if e >= d:
                idx = i
                break
        if idx is None:
            return None
        if all_expiries[idx] == d:
            return all_expiries[idx + 1] if idx + 1 < len(all_expiries) else None
        return all_expiries[idx]

    async def resolve_contract(expiry: date, strike: float, option_type: str) -> dict | None:
        if expiry in live_expiry_set:
            c = live_by_key.get((expiry.isoformat(), strike, option_type))
            return {"trading_symbol": c["trading_symbol"], "instrument_key": c["instrument_key"], "expired": False} if c else None
        if expiry not in expired_contracts_cache:
            try:
                expired_contracts_cache[expiry] = await get_expired_option_contracts(token, UNDERLYING_KEY, expiry)
            except RuntimeError as exc:
                print(f"    ! failed to fetch expired contracts for {expiry.isoformat()}: {exc}")
                expired_contracts_cache[expiry] = []
        for c in expired_contracts_cache[expiry]:
            if float(c.get("strike_price", 0)) == strike and c.get("instrument_type") == option_type:
                return {"trading_symbol": c.get("trading_symbol", ""), "instrument_key": c.get("instrument_key", ""), "expired": True}
        return None

    async def fetch_leg_candles(contract: dict, from_date: date, to_date: date) -> dict[str, dict]:
        try:
            if contract["expired"]:
                candles = await get_expired_candles(token, contract["instrument_key"], from_date, to_date)
            else:
                candles = await get_candles(token, contract["instrument_key"], "1m", from_date, to_date)
        except RuntimeError as exc:
            print(f"    ! candle fetch failed for {contract['trading_symbol']}: {exc}")
            return {}
        return {c["timestamp"][:16]: c for c in candles}

    records: list[dict] = []  # {date, week, month, pct, bin, sell_price}
    day_meta: dict[str, dict] = {}  # date -> {buy_price, expiry, atm_strike, ce, pe, next_date}

    for i, day_str in enumerate(trading_days[:-1]):
        T = date.fromisoformat(day_str)
        next_day_str = trading_days[i + 1]
        T1 = date.fromisoformat(next_day_str)

        ref_candle = nifty_by_day[day_str].get("15:25")
        if ref_candle is None:
            print(f"{day_str}: no 15:25 NIFTY candle, skipping")
            continue
        ref_close = ref_candle["close"]
        atm_strike = float(round(ref_close / STRIKE_STEP) * STRIKE_STEP)

        expiry = nearest_trade_expiry(T)
        if expiry is None:
            print(f"{day_str}: no usable expiry found, skipping")
            continue

        ce = await resolve_contract(expiry, atm_strike, "CE")
        pe = await resolve_contract(expiry, atm_strike, "PE")
        if not ce or not pe:
            print(f"{day_str}: could not resolve {atm_strike} CE/PE for expiry {expiry.isoformat()}, skipping")
            continue

        ce_candles = await fetch_leg_candles(ce, T, T1)
        pe_candles = await fetch_leg_candles(pe, T, T1)

        call_buy_high = max(
            (ce_candles[f"{day_str}T{t}"]["high"] for t in BUY_TIMES if f"{day_str}T{t}" in ce_candles),
            default=None,
        )
        put_buy_high = max(
            (pe_candles[f"{day_str}T{t}"]["high"] for t in BUY_TIMES if f"{day_str}T{t}" in pe_candles),
            default=None,
        )
        if call_buy_high is None or put_buy_high is None:
            print(f"{day_str}: no buy-window (15:25-15:29) candles for {ce['trading_symbol']}/{pe['trading_symbol']}, skipping")
            continue
        buy_price = call_buy_high + put_buy_high

        week, month = _week_key(T), _month_key(T)
        day_records: list[dict] = []
        t = datetime.strptime(SELL_START, "%H:%M")
        end = datetime.strptime(SELL_END, "%H:%M")
        while t <= end:
            hhmm = t.strftime("%H:%M")
            key = f"{next_day_str}T{hhmm}"
            call_c, put_c = ce_candles.get(key), pe_candles.get(key)
            if call_c is not None and put_c is not None:
                sell_price = call_c["low"] + put_c["low"]
                pct = (sell_price - buy_price) / buy_price * 100
                day_records.append({
                    "date": day_str, "week": week, "month": month,
                    "pct": pct, "bin": classify(pct), "sell_price": sell_price,
                })
            t += timedelta(minutes=1)
        records.extend(day_records)

        if day_records:
            day_meta[day_str] = {
                "buy_price": buy_price,
                "expiry": expiry.isoformat(),
                "atm_strike": atm_strike,
                "ce": ce["trading_symbol"],
                "pe": pe["trading_symbol"],
                "next_date": next_day_str,
            }

        day_counts, day_sums = _bin_stats(day_records)
        print(
            f"{day_str}: expiry={expiry.isoformat()} atm={atm_strike:.0f} "
            f"buy={buy_price:.2f} ({ce['trading_symbol']} / {pe['trading_symbol']}) "
            f"sell_minutes={len(day_records)}/105 -> next={next_day_str} "
            f"| top bin: {_top_bin_text(day_counts, day_sums)}"
        )
        time.sleep(5)


    print(f"\nTotal analysable minute-samples across {len(trading_days) - 1} candidate days: {len(records)}")
    if records:
        write_report(records, day_meta)
        print(f"Report written to {REPORT_HTML}")
    else:
        print("No records collected - report not written.")


def _bin_stats(recs: list[dict]) -> tuple[list[int], list[float]]:
    counts = [0] * len(BINS)
    sums = [0.0] * len(BINS)
    for r in recs:
        counts[r["bin"]] += 1
        sums[r["bin"]] += r["pct"]
    return counts, sums


def _top_bin_text(counts: list[int], sums: list[float]) -> str:
    total = sum(counts)
    if total == 0:
        return "n/a"
    idx = max(range(len(BINS)), key=lambda i: counts[i])
    if counts[idx] == 0:
        return "n/a"
    avg = sums[idx] / counts[idx]
    pct_of_total = counts[idx] / total * 100
    return f"{BINS[idx][0]} ({pct_of_total:.1f}% of minutes, avg {avg:+.2f}%)"


def _group_rows(records: list[dict], key: str) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        groups[r[key]].append(r)
    return sorted(groups.items())


def _bar_html(counts: list[int]) -> str:
    total = sum(counts) or 1
    segs = []
    for idx, cnt in enumerate(counts):
        pct = cnt / total * 100
        if pct <= 0:
            continue
        segs.append(f'<div class="seg bin-{idx}" style="width:{pct:.3f}%" title="{BINS[idx][0]}: {pct:.1f}%"></div>')
    return f'<div class="bar">{"".join(segs)}</div>'


def _top_bins_html(counts: list[int], sums: list[float], n: int = 3) -> str:
    total = sum(counts) or 1
    ranked = sorted(range(len(BINS)), key=lambda i: counts[i], reverse=True)[:n]
    parts = []
    for idx in ranked:
        if counts[idx] == 0:
            continue
        avg = sums[idx] / counts[idx]
        pct_of_total = counts[idx] / total * 100
        parts.append(f'<span class="topbin bin-{idx}-text">{BINS[idx][0]}: {pct_of_total:.1f}% (avg {avg:+.2f}%)</span>')
    return " &nbsp;·&nbsp; ".join(parts)


def _table_rows(groups: list[tuple[str, list[dict]]]) -> str:
    rows = []
    for label, recs in groups:
        counts, sums = _bin_stats(recs)
        rows.append(
            f"<tr><td class='label'>{label}</td>"
            f"<td class='n'>{len(recs)}</td>"
            f"<td class='barcell'>{_bar_html(counts)}</td>"
            f"<td class='topbins'>{_top_bins_html(counts, sums)}</td></tr>"
        )
    return "\n".join(rows)


def _daily_table_rows(groups: list[tuple[str, list[dict]]], day_meta: dict[str, dict]) -> str:
    rows = []
    for label, recs in groups:
        counts, sums = _bin_stats(recs)
        meta = day_meta.get(label, {})
        buy_price = meta.get("buy_price")
        sell_prices = [r["sell_price"] for r in recs]
        buy_cell = f"{buy_price:.2f}" if buy_price is not None else "-"
        if sell_prices:
            sell_cell = (
                f"{sum(sell_prices) / len(sell_prices):.2f} "
                f"<span class='range'>({min(sell_prices):.2f}–{max(sell_prices):.2f})</span>"
            )
        else:
            sell_cell = "-"
        legs = f"{meta.get('ce', '')} / {meta.get('pe', '')}" if meta else ""
        rows.append(
            f"<tr><td class='label'>{label}</td>"
            f"<td class='n'>{len(recs)}</td>"
            f"<td class='price'>{buy_cell}</td>"
            f"<td class='price'>{sell_cell}</td>"
            f"<td class='legs'>{legs}</td>"
            f"<td class='barcell'>{_bar_html(counts)}</td>"
            f"<td class='topbins'>{_top_bins_html(counts, sums)}</td></tr>"
        )
    return "\n".join(rows)


def write_report(records: list[dict], day_meta: dict[str, dict]) -> None:
    overall_counts, overall_sums = _bin_stats(records)
    total = len(records)

    legend = "".join(
        f'<span class="legend-item"><span class="swatch bin-{idx}"></span>{label}</span>'
        for idx, (label, _) in enumerate(BINS)
    )

    daily_rows = _daily_table_rows(_group_rows(records, "date"), day_meta)
    weekly_rows = _table_rows(_group_rows(records, "week"))
    monthly_rows = _table_rows(_group_rows(records, "month"))

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Overnight Jump Analysis — NIFTY ATM CE+PE</title>
<style>
  :root {{
    color-scheme: light;
    --surface: #fcfcfb; --page: #f9f9f7; --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
    --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
    --red: 227,73,72; --blue: 42,120,214;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) {{
      color-scheme: dark;
      --surface: #1a1a19; --page: #0d0d0d; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781;
      --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
      --red: 230,103,103; --blue: 57,135,229;
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --surface: #1a1a19; --page: #0d0d0d; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
    --red: 230,103,103; --blue: 57,135,229;
  }}
  * {{ box-sizing: border-box; }}
  body {{ background: var(--page); color: var(--ink); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0; padding: 24px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .subtitle {{ color: var(--ink2); font-size: 13px; margin-bottom: 20px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; margin-bottom: 20px; }}
  .stat-row {{ display: flex; gap: 24px; flex-wrap: wrap; }}
  .stat {{ min-width: 140px; }}
  .stat .v {{ font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; }}
  .stat .l {{ font-size: 12px; color: var(--muted); }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 14px; margin: 10px 0 6px; font-size: 12px; color: var(--ink2); }}
  .legend-item {{ display: inline-flex; align-items: center; gap: 6px; }}
  .swatch {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; }}
  .bin-0, .swatch.bin-0 {{ background: rgba(var(--red), 1.0); }}
  .bin-1, .swatch.bin-1 {{ background: rgba(var(--red), 0.72); }}
  .bin-2, .swatch.bin-2 {{ background: rgba(var(--red), 0.46); }}
  .bin-3, .swatch.bin-3 {{ background: rgba(var(--red), 0.24); }}
  .bin-4, .swatch.bin-4 {{ background: rgba(var(--blue), 0.24); }}
  .bin-5, .swatch.bin-5 {{ background: rgba(var(--blue), 0.46); }}
  .bin-6, .swatch.bin-6 {{ background: rgba(var(--blue), 0.72); }}
  .bin-7, .swatch.bin-7 {{ background: rgba(var(--blue), 1.0); }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th {{ text-align: left; color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; padding: 6px 8px; border-bottom: 1px solid var(--grid); }}
  td {{ padding: 6px 8px; border-bottom: 1px solid var(--grid); vertical-align: middle; }}
  td.label {{ white-space: nowrap; font-variant-numeric: tabular-nums; }}
  td.n {{ color: var(--muted); text-align: right; width: 50px; }}
  td.price {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }}
  td.price .range {{ color: var(--muted); font-size: 11px; }}
  td.legs {{ color: var(--ink2); font-size: 11px; white-space: nowrap; }}
  td.barcell {{ width: 220px; }}
  .bar {{ display: flex; height: 14px; width: 100%; border-radius: 4px; overflow: hidden; background: var(--grid); }}
  .seg {{ height: 100%; }}
  .topbins {{ color: var(--ink2); font-size: 12px; }}
  .table-scroll {{ overflow-x: auto; }}
  .table-scroll.tall {{ max-height: 480px; overflow-y: auto; }}
</style>
</head>
<body>

<h1>Overnight Jump Analysis — NIFTY ATM Call + Put</h1>
<div class="subtitle">Buy ATM CE+PE high (15:25-15:29) &rarr; sell low (09:15-10:59 next trading day) &middot; {RANGE_FROM.isoformat()} to {RANGE_TO.isoformat()}</div>

<div class="card">
  <div class="stat-row">
    <div class="stat"><div class="v">{total}</div><div class="l">minute-samples analyzed</div></div>
    <div class="stat"><div class="v">{sum(overall_counts[4:])}</div><div class="l">profit samples</div></div>
    <div class="stat"><div class="v">{sum(overall_counts[:4])}</div><div class="l">loss samples</div></div>
    <div class="stat"><div class="v">{sum(overall_counts[4:]) / total * 100:.1f}%</div><div class="l">overall win rate</div></div>
  </div>
  <div class="legend">{legend}</div>
  {_bar_html(overall_counts)}
  <div class="topbins" style="margin-top:8px">{_top_bins_html(overall_counts, overall_sums)}</div>
</div>

<div class="card">
  <h2 style="font-size:15px;margin:0 0 10px">Monthly</h2>
  <div class="table-scroll"><table><thead><tr><th>Month</th><th>N</th><th>Distribution</th><th>Top bins (avg diff%)</th></tr></thead><tbody>
  {monthly_rows}
  </tbody></table></div>
</div>

<div class="card">
  <h2 style="font-size:15px;margin:0 0 10px">Weekly</h2>
  <div class="table-scroll tall"><table><thead><tr><th>Week</th><th>N</th><th>Distribution</th><th>Top bins (avg diff%)</th></tr></thead><tbody>
  {weekly_rows}
  </tbody></table></div>
</div>

<div class="card">
  <h2 style="font-size:15px;margin:0 0 10px">Daily</h2>
  <div class="subtitle" style="margin-bottom:10px">Buy Price = total_buy_price at 15:25-15:29 &middot; Sell Price = avg (min–max) of total_sell_price across the next day's 09:15-10:59 candles</div>
  <div class="table-scroll tall"><table><thead><tr><th>Date</th><th>N</th><th>Buy Price</th><th>Sell Price</th><th>Legs (CE / PE)</th><th>Distribution</th><th>Top bins (avg diff%)</th></tr></thead><tbody>
  {daily_rows}
  </tbody></table></div>
</div>

</body>
</html>
"""
    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    asyncio.run(main())
