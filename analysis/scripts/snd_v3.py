"""Supply and Demand - v3 (the zone alone, no sweep and no micro break)

USER PROMPT (verbatim)
----------------------
v3 SnD
### v3 - the zone alone, no sweep and no micro break
* The three-part confirmation is GONE. The entry is the close of the candle that touches the zone.
* The 13:00 entry cut-off stays. The stop is the far edge of the zone itself, flush with the edge.
* Being shaken out more often is accepted.

Step 1 - A swing high is a candle whose high is higher than the 3 highs before it and the 3 highs after it, and a
swing low is the opposite; a swing only counts once 3 candles have closed after it.
Step 2 - The first candle of the day that CLOSES beyond the most recent confirmed swing sets the direction: above a
swing high is bullish, below a swing low is bearish. A wick through is not a break, and only the first break of the
day counts.
Step 3 - The zone is the last opposite-coloured candle in the 3 candles before the break, taken as its full range,
low to high. A bullish break gives a demand zone, a bearish break a supply zone. If none of those 3 candles is the
opposite colour there is no zone and the day is over.
Step 4 - Wait for price to come back and touch the zone: the candle's low is at or below the zone high and its high
is at or above the zone low.
Step 5 - THE TOUCH IS THE ENTRY. Buy at the close of that candle for a demand zone, sell at its close for a supply zone.
Step 6 - No new entry at or after 13:00. A touch at or after that time is recorded and the day is finished.
Step 7 - The stop is the far edge of the zone: the zone low for a long and the zone high for a short, flush with the
edge, nothing added.
Step 8 - Risk is the distance from the entry to the stop; below 1 point there is no trade and the day's slot is used
up anyway.
Step 9 - The target is the entry plus 2 times the risk, mirrored for a short; also score 1:1, 1:3 and 1:5, and an
opposing-liquidity target - the session extreme standing before the entry candle, or the latest confirmed swing
beyond it, whichever is further away. If there is nothing on the far side, the trade has no target and runs on its
stop and the square-off alone.
Step 10 - The setup dies if any candle CLOSES more than 4 zone widths past the far edge of the zone; check that
before the touch test on every candle, so a candle that dips in and also closes that far past counts as the death,
not the entry.
Step 11 - One trade a day at most; once I am in, the zone dying no longer matters.
Step 12 - Watch the stop and target on 1-minute prices from the candle after the entry; inside any one minute the
order is square-off, then stop, then target. Square off at 15:15.
Step 13 - 3-minute candles by default, 1-minute alongside.

CHECKLIST (RUN.md Step 1) - ASSUMED items are marked
----------------------------------------------------
 1 Underlying        ASSUMED  NIFTY 50 (the prompt names none).
 2 Window            ASSUMED  2026-01-01 through the current IST date (--from/--to override).
 3 Signal timeframe  clear    3-minute (default) and 1-minute, both built from 1-minute candles; variant `tf`.
 4 Signal rule       clear    steps 1-4 and 10 exactly; swings/zones are intraday (see assumptions).
 5 Decision time     clear    the close of the candle that touches the zone (before 13:00 by candle start).
 6 Direction mapping ASSUMED  demand zone (long) -> buy an ATM CE; supply zone (short) -> buy an ATM PE.
 7 Traded instrument ASSUMED  ATM option (the prompt trades index points; no futures costs exist in py_funcs).
 8 Option specifics  ASSUMED  buy ATM (strike nearest the touch candle close), 1 lot, expiry = nearest at least
                              1 day after the trade day (Rule 10).
 9 Entry             clear    the touch; fill per Rules 1-2 (see conflicts below).
10 Exit              clear    stop = zone edge, target ladder (variant `target`), square-off 15:15; stop and
                              target are evaluated on 1-minute INDEX prices, the exit fills in the next option bar.
11 Holding           clear    intraday.
12 Costs             ASSUMED  option_costs (standard option schedule).
13 Positions         clear    one trade per day per (tf, target) scenario; the scenarios are alternatives, not
                              simultaneous positions.
14 Missing data      ASSUMED  skip and list.
15 Variants          clear    tf (3m, 1m) x target (1:1, 1:2, 1:3, 1:5, opposing liquidity) = 10 variants.
16 Group-bys         ASSUMED  direction (demand/supply), risk-in-points bucket (edges 10/20/40 are my choice),
                              and direction x risk.
17 Script name       snd_v3

OTHER ASSUMPTIONS
* Swings and the break/zone are computed from the current day's candles only (nothing carried from the previous day).
* A swing at candle j counts from candle j+3 on (its third confirming candle has closed); "higher than the 3 highs
  before / after" is strict (>). Doji candles (close == open) are not coloured, so never the zone candle.
* The touch search starts with the candle after the break candle. The 13:00 rule uses the touch candle's START time.
* Reference entry for risk and target = the CLOSE of the touch candle (index). Risk = close - zone low (long) or
  zone high - close (short); < 1 point (or negative) = no trade, day used up.
* Opposing liquidity (long) = the higher of {highest high of the candles before the touch candle, latest confirmed
  swing high} that lies above the reference entry (mirrored for a short); nothing above -> no target.
* Stop/target are checked from the entry bar itself (first 1-minute bar after the touch candle completes), using the
  index 1-minute high/low; the option exit is the option's next 1-minute bar (low).
* Sessions must have exactly the 375 one-minute bars 09:15-15:29 with no duplicates; else the day is skipped.
* Option capital = premium x qty (bought option).
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates"))
from py_funcs import *  # noqa: E402,F401,F403

SLUG = "snd_v3"
TIMEFRAMES = [3, 1]                       # minutes; 3m is the default, 1m alongside
TARGETS = ["1:1", "1:2", "1:3", "1:5", "opposing liquidity"]
MULT = {"1:1": 1.0, "1:2": 2.0, "1:3": 3.0, "1:5": 5.0}
CUTOFF = "13:00"                          # no entry at/after (touch candle start)
SQUARE_OFF = "15:15"
DEATH_WIDTHS = 4.0
MIN_RISK = 1.0
SWING_N = 3
LOTS = 1
EXPECTED = [f"{m // 60:02d}:{m % 60:02d}" for m in range(9 * 60 + 15, 15 * 60 + 30)]   # 375 minutes

# The axes the source (nes_supply_demand_v3) compares that APPLY to this rule.
# Its STOP_ANCHORS list has four values, but three of them name a sweep and a micro-BOS that
# v3 does not have - it is "the zone alone" - so only the zone anchor is real here. Recorded
# in meta["rejected"] rather than faked.
STOP_TRIGGERS = [("touch", "an order resting at the level, filled on touch"),
                 ("close", "a candle CLOSE beyond the level, filled next bar")]
EOD_MODES = [("close", "square off at the session close time"),
             ("hold", "run to stop or target, give up at the last candle")]
NEVER = "99:99"                 # a force-exit key later than any bar: "hold" runs to the end
RULE = {"trigger": "touch", "eod": "close"}

SETTINGS = [
    setting("tf", "Signal timeframe", kind="other", default="3m",
            values=[f"{t}m" for t in TIMEFRAMES]),
    setting("target", "Target", kind="exit", values=TARGETS, default="1:2"),
    setting("trigger", "Stop trigger", kind="exit", default=RULE["trigger"],
            options=[{"value": k, "label": v, "raw": k} for k, v in STOP_TRIGGERS]),
    setting("eod", "End of day", kind="exit", default=RULE["eod"],
            options=[{"value": k, "label": v, "raw": k} for k, v in EOD_MODES]),
]


def _vals(key):
    return [o["raw"] for o in next(x for x in SETTINGS if x["key"] == key)["options"]]


def scan_close_stop(bars, side, entry_key, stop, target, force_key):
    """Close-confirmed stop: a bar must CLOSE beyond the stop, which is a signal, so the exit
    is the NEXT bar (rule 3). The target stays a touch. Stop first if a bar does both."""
    for i, r in enumerate(bars):
        if r[0] <= entry_key:
            continue
        if r[0] == force_key:
            return {"bar": r, "reason": "time exit", "trigger": None}
        hit_stop = r[4] < stop if side == "LONG" else r[4] > stop
        hit_tgt = target is not None and (r[2] >= target if side == "LONG" else r[3] <= target)
        if hit_stop or hit_tgt:
            nxt = bars[i + 1] if i + 1 < len(bars) else None
            if nxt is not None and nxt[0] > force_key:
                nxt = None
            return {"bar": nxt, "reason": "stop (close-confirmed)" if hit_stop else "target",
                    "trigger": r}
    return {"bar": None, "reason": "no exit found", "trigger": None}
RISK_EDGES, RISK_LABELS = [10, 20, 40], ["risk < 10", "risk 10-20", "risk 20-40", "risk 40+"]


# ---------------------------------------------------------------------------
# signal: pure, completed candles only
# ---------------------------------------------------------------------------
def find_setup(c: list[list], tf: int) -> dict:
    """Steps 1-6, 8, 10 on one session of tf-minute candles [[HH:MM,o,h,l,c],...].
    Returns {"skip": reason} or a setup dict with the touch candle index k and the zone."""
    n = len(c)
    O, H, L, C = ([r[j] for r in c] for j in (1, 2, 3, 4))
    is_h = [SWING_N <= j < n - SWING_N and H[j] > max(H[j - SWING_N:j]) and H[j] > max(H[j + 1:j + 1 + SWING_N])
            for j in range(n)]
    is_l = [SWING_N <= j < n - SWING_N and L[j] < min(L[j - SWING_N:j]) and L[j] < min(L[j + 1:j + 1 + SWING_N])
            for j in range(n)]
    brk = None
    for i in range(n):
        last = i - SWING_N                                   # swings up to j = i-3 are confirmed at candle i's close
        sh = next((j for j in range(last, -1, -1) if is_h[j]), None)
        sl = next((j for j in range(last, -1, -1) if is_l[j]), None)
        if sh is not None and C[i] > H[sh]:
            brk = (i, "bullish", sh)
            break
        if sl is not None and C[i] < L[sl]:
            brk = (i, "bearish", sl)
            break
    if brk is None:
        return {"skip": "no candle closed beyond a confirmed swing (no break)"}
    i, kind, sw = brk
    zi = None
    for j in range(i - 1, i - 1 - SWING_N, -1):              # last opposite-coloured candle of the 3 before the break
        if (kind == "bullish" and C[j] < O[j]) or (kind == "bearish" and C[j] > O[j]):
            zi = j
            break
    if zi is None:
        return {"skip": f"{kind} break at {c[i][0]} but none of the 3 candles before it is opposite-coloured (no zone)"}
    zl, zh = L[zi], H[zi]
    w = zh - zl
    if w <= 0:
        return {"skip": f"zone candle {c[zi][0]} has zero range"}
    for k in range(i + 1, n):
        if kind == "bullish" and C[k] < zl - DEATH_WIDTHS * w:
            return {"skip": f"demand zone died: {c[k][0]} closed {DEATH_WIDTHS:g} zone widths below it"}
        if kind == "bearish" and C[k] > zh + DEATH_WIDTHS * w:
            return {"skip": f"supply zone died: {c[k][0]} closed {DEATH_WIDTHS:g} zone widths above it"}
        if L[k] <= zh and H[k] >= zl:                        # touch
            if c[k][0] >= CUTOFF:
                return {"skip": f"touch at {c[k][0]} is at/after {CUTOFF}: recorded, day finished"}
            side = "LONG" if kind == "bullish" else "SHORT"
            entry_ref = C[k]
            stop = zl if side == "LONG" else zh
            risk = entry_ref - stop if side == "LONG" else stop - entry_ref
            if risk < MIN_RISK:
                return {"skip": f"touch at {c[k][0]}: risk {risk:.2f} pts < {MIN_RISK:g}, slot used"}
            # opposing liquidity, from candles complete before the touch candle + swings confirmed at its close
            ext = max(H[:k]) if side == "LONG" else min(L[:k])
            lastk = k - SWING_N
            if side == "LONG":
                sj = next((j for j in range(lastk, -1, -1) if is_h[j]), None)
                cands = [x for x in (ext, H[sj] if sj is not None else None) if x is not None and x > entry_ref]
                liq = max(cands) if cands else None
            else:
                sj = next((j for j in range(lastk, -1, -1) if is_l[j]), None)
                cands = [x for x in (ext, L[sj] if sj is not None else None) if x is not None and x < entry_ref]
                liq = min(cands) if cands else None
            return {"skip": None, "kind": kind, "side": side, "k": k, "start": c[k][0], "break_time": c[i][0],
                    "zone_time": c[zi][0], "zl": zl, "zh": zh, "entry_ref": entry_ref, "stop": stop,
                    "risk": risk, "liq": liq, "swing_time": c[sw][0], "delay": k - i}
    return {"skip": f"{kind} zone at {zl:.2f}-{zh:.2f} was never touched"}


# ---------------------------------------------------------------------------
# simulate: pure, bars -> exit
# ---------------------------------------------------------------------------
def target_price(setup: dict, target: str) -> float | None:
    if target == "opposing liquidity":
        return setup["liq"]
    m = MULT[target]
    return setup["entry_ref"] + m * setup["risk"] * (1 if setup["side"] == "LONG" else -1)


def sane(bar: list | None) -> bool:
    return bool(bar) and bar[3] > 0 and bar[2] >= bar[3] and bar[3] <= bar[1] <= bar[2] and bar[3] <= bar[4] <= bar[2]


def simulate(setup: dict, tf: int, target: str, idx_rows: list[list], opt_rows: list[list],
             trigger: str = "touch", eod: str = "close") -> dict:
    """Index stop/target scan -> exit minute -> option fills (Rules 1-3). {"skip":...} or the fill data."""
    entry_idx = bar_after_candle(idx_rows, setup["start"], tf)
    entry_opt = bar_after_candle(opt_rows, setup["start"], tf)
    if entry_idx is None:
        return {"skip": "index 1m bar after the touch candle is missing"}
    if not sane(entry_opt):
        return {"skip": "option entry bar missing or invalid"}
    key0 = candle_done_at(setup["start"], tf - 1) if tf > 1 else setup["start"]   # last minute of the touch candle
    tgt = target_price(setup, target)
    scan = scan_exit if trigger == "touch" else scan_close_stop
    ex = scan(idx_rows, setup["side"], key0, setup["stop"], tgt,
              SQUARE_OFF if eod == "close" else NEVER)
    if ex["bar"] is None:
        return {"skip": f"no exit bar ({ex['reason']}; trigger {ex['trigger'][0] if ex['trigger'] else '-'})"}
    exit_opt = next((r for r in opt_rows if r[0] == ex["bar"][0]), None)
    if not sane(exit_opt):
        return {"skip": f"option exit bar {ex['bar'][0]} missing or invalid"}
    entry_px, exit_px = worst_fills("LONG", entry_opt, exit_opt)      # the option is always bought
    return {"skip": None, "entry_bar": entry_opt, "exit_bar": exit_opt, "entry_px": entry_px, "exit_px": exit_px,
            "reason": ex["reason"], "target": tgt}


# ---------------------------------------------------------------------------
# fetch + main
# ---------------------------------------------------------------------------
async def main(frm: date, to: date) -> None:
    use_tfs = [int(v[:-1]) for v in _vals("tf")]
    use_targets = _vals("target")
    use_triggers = _vals("trigger")
    use_eods = _vals("eod")
    now = datetime.now(IST)
    skips: list[str] = []
    trades: list[dict] = []
    option_sessions: dict[str, dict[str, list[list]]] = {}
    opt_cache: dict[tuple, list[list]] = {}
    contract_cache: dict[tuple, dict | None] = {}
    async with Upstox() as up:
        und = await up.find_instrument("NIFTY")
        key = und["instrument_key"]
        info = await up.option_chain_info(key)
        step = info["strike_step"]
        expiries = await up.expiry_calendar(key, frm, to)
        print(f"{und['trading_symbol']} strike step {step}, {len(expiries)} expiries known")
        cs = await up.candles(key, "1m", frm, to)
        sessions = sessions_from(cs)
        cov = coverage(sessions, frm, to, rows_per_session=375)
        for d in cov["weekday_gaps"]:
            skips.append(f"{d}: no index candles (holiday or feed miss)")
            print(f"SKIP {d}: no index candles (holiday or feed miss)")

        usable: dict[str, list[list]] = {}
        for day, rows in sessions.items():
            if day == now.date().isoformat() and now.strftime("%H:%M") < "15:45":
                print(f"SKIP {day}: today's session is not over"); continue
            if [r[0] for r in rows] != EXPECTED or any(not sane(r) for r in rows):
                msg = f"{day}: incomplete/duplicate/invalid session ({len(rows)} bars)"
                skips.append(msg); print("SKIP " + msg); continue
            usable[day] = rows

        for day, rows in usable.items():
            dd = date.fromisoformat(day)
            for tf in use_tfs:
                tag = f"{day} {tf}m"
                cd = rows if tf == 1 else resample(rows, tf)
                setup = find_setup(cd, tf)
                if setup["skip"]:
                    skips.append(f"{tag}: {setup['skip']}"); print(f"SKIP {tag}: {setup['skip']}"); continue
                otype = "CE" if setup["side"] == "LONG" else "PE"
                expiry = next_expiry(expiries, dd, 1)
                if expiry is None:
                    msg = f"{tag}: no expiry at least 1 day after the trade day"
                    skips.append(msg); print("SKIP " + msg); continue
                strike = atm_strike(setup["entry_ref"], step)
                ck = (expiry, strike, otype)
                try:
                    if ck not in contract_cache:
                        contract_cache[ck] = await up.resolve_option(key, expiry, strike, otype)
                    contract = contract_cache[ck]
                    if contract is None:
                        msg = f"{tag}: no contract {strike:g} {otype} exp {expiry}"
                        skips.append(msg); print("SKIP " + msg); continue
                    ok = (contract["instrument_key"], day)
                    if ok not in opt_cache:
                        opt_cache[ok] = await up.option_candles(contract, dd)
                except RuntimeError as exc:
                    msg = f"{tag}: option data error ({exc})"
                    skips.append(msg); print("SKIP " + msg); continue
                orows = opt_cache[ok]
                if not orows:
                    msg = f"{tag}: option {contract['trading_symbol']} has no bars"
                    skips.append(msg); print("SKIP " + msg); continue
                for target in use_targets:
                  for trig in use_triggers:
                   for eod in use_eods:
                    sim = simulate(setup, tf, target, rows, orows, trig, eod)
                    if sim["skip"]:
                        msg = f"{tag} {target}: {sim['skip']}"
                        skips.append(msg); print("SKIP " + msg); continue
                    eb, xb = sim["entry_bar"], sim["exit_bar"]
                    qty = LOTS * contract["lot_size"]
                    option_sessions.setdefault(contract["trading_symbol"], {})[day] = orows
                    lv = [{"name": f"{setup['kind']} zone", "price": setup["zl"], "price2": setup["zh"],
                           "from": setup["zone_time"], "to": xb[0]},
                          {"name": "stop (index)", "price": setup["stop"], "from": eb[0], "to": xb[0]}]
                    if sim["target"] is not None:
                        lv.append({"name": f"target {target} (index)", "price": sim["target"],
                                   "from": eb[0], "to": xb[0]})
                    mfe, mae = excursion(orows, "LONG", sim["entry_px"], eb[0], xb[0])
                    trades.append(make_trade(
                        day=day, side="LONG", symbol=contract["trading_symbol"], entry_time=eb[0],
                        entry_px=sim["entry_px"], exit_time=xb[0], exit_px=sim["exit_px"], qty=qty,
                        exit_reason=sim["reason"], kind="option", capital=sim["entry_px"] * qty,
                        stop=None, target=None, mfe=mfe, mae=mae, expiry=contract["expiry"],
                        option_type=otype, levels=lv,
                        variant={"tf": f"{tf}m", "target": target, "trigger": trig, "eod": eod},
                        tags={"direction": "demand (buy CE)" if setup["side"] == "LONG" else "supply (buy PE)",
                              "risk": bucket(setup["risk"], RISK_EDGES, RISK_LABELS)},
                        note=(f"{setup['kind']} break {setup['break_time']} (swing {setup['swing_time']}), zone "
                              f"{setup['zl']:.2f}-{setup['zh']:.2f} from {setup['zone_time']}, touch candle "
                              f"{setup['start']} close {setup['entry_ref']:.2f}, index risk {setup['risk']:.2f}")))

    print(f"\n{len(skips)} skips listed above; {len(usable)} usable sessions of {len(sessions)} fetched.")
    if not trades:
        print("No trades; no report written.")
        return
    meta = {
        "title": "Supply and Demand v3 - zone touch, no confirmation",
        "subtitle": "NIFTY 3m and 1m first-break zones, ATM option bought on the touch",
        "instrument": f"{und['trading_symbol']} index signal, ATM option traded",
        "from": frm.isoformat(), "to": to.isoformat(), "lot_size": info["lot_size"],
        "fill_rule": "Every BUY at the bar's high, every SELL at the bar's low; a signal candle is acted on in the "
                     "next 1-minute bar; stops/targets exit in the bar after the touch.",
        "cost_model": "Standard option schedule (option_costs): brokerage, STT, exchange, SEBI, stamp, GST.",
        "params": {"timeframes": "3m, 1m", "swing": "3 before / 3 after", "entry cut-off": CUTOFF,
                   "square-off": SQUARE_OFF, "zone death": f"{DEATH_WIDTHS:g} zone widths", "min risk": f"{MIN_RISK:g} pt",
                   "targets": ", ".join(TARGETS), "lots": LOTS, "strike": "ATM", "expiry": "nearest >= 1 day after"},
        "rule_steps": [
            "Build 3-minute (and 1-minute) candles; use only completed candles.",
            "Swing high/low: high above the 3 highs before and after (low: mirrored); counts once 3 candles closed after it.",
            "The first candle of the day to CLOSE beyond the latest confirmed swing sets the direction (bullish above a swing high, bearish below a swing low).",
            "Zone = full range of the last opposite-coloured candle in the 3 candles before the break; none = day over.",
            "From the candle after the break: first check the zone is not dead (a close more than 4 zone widths past the far edge), then check the touch (low <= zone high and high >= zone low).",
            "The touch is the entry signal: demand -> buy an ATM CE, supply -> buy an ATM PE, filled in the next 1-minute bar at that option bar's high. No entry when the touch candle starts at/after 13:00.",
            "Stop = far edge of the zone (index level); risk = touch-candle close to stop, below 1 point = no trade.",
            "Targets (variants): 1R, 2R, 3R, 5R from the touch-candle close, or opposing liquidity (session extreme before the touch candle / latest confirmed swing, whichever is further; none = no target).",
            "1-minute index prices are watched from the first bar after the touch candle: square-off 15:15 first, then stop, then target (stop first when one bar touches both); a stop/target exit sells the option at the low of the NEXT 1-minute bar.",
            "One trade per day per scenario."],
        "limits": [
            "ASSUMED: underlying is NIFTY 50; the prompt names none.",
            "ASSUMED: the prompt trades index points; here the traded instrument is an ATM option (demand -> CE, supply -> PE), 1 lot, expiry nearest at least 1 day after the trade day. Stops and targets are index levels, so option P&L is not the index R multiple.",
            "ASSUMED: swings, break and zone use the current day's candles only; swings need strictly higher/lower highs/lows; the 13:00 cut-off uses the touch candle's start time.",
            "ASSUMED: risk and targets are measured from the touch candle's close (the prompt's entry price), but the real fill is the option bar after the candle at its high (Rules 1-2), so results are worse than the prompt's idealised fill.",
            "ASSUMED: stop/target are checked from the entry bar itself; opposing liquidity = further of (highest high before the touch candle, latest confirmed swing high) above the entry (mirrored for shorts).",
            "ASSUMED: risk buckets (10/20/40 points) are descriptive edges chosen by the script.",
            "The variants (timeframe x target) are shown side by side but are alternative scenarios on the same days, not simultaneous positions; 1m and 3m trades on the same day overlap in time.",
            "In-sample: no parameter was tuned here, but the prompt's rules were chosen after looking at earlier windows; treat the result as in-sample.",
            "Option capital is premium x qty; option costs use the standard schedule. Expired-option data comes from Upstox; days with a missing option bar or contract are skipped and were listed on the console."],
        "coverage": cov,
    }
    groups = [{"name": "direction", "keys": ["direction"]},
              {"name": "risk at entry", "keys": ["risk"]},
              {"name": "direction x risk", "keys": ["direction", "risk"]}]
    meta.setdefault("rejected", []).append(
        ["Three of the source's four stop anchors",
         "its STOP_ANCHORS list offers the sweep candle's extreme, the micro-BOS candle's "
         "extreme and the nearer of the two. This rule is the zone alone - it has no sweep and "
         "no micro-BOS - so only the zone anchor exists to price."])
    payload = build_payload(meta, trades, usable, option_sessions, groups,
                            settings=SETTINGS, chart="default")
    path = write_report(payload, SLUG)
    print(console_summary(trades))
    print(path)


if __name__ == "__main__":
    yesterday = datetime.now(IST).date() - timedelta(days=1)
    ap = argparse.ArgumentParser(description="Supply and Demand v3 backtest")
    ap.add_argument("--from", dest="frm", type=date.fromisoformat, default=START_DATE)
    ap.add_argument("--to", dest="to", type=date.fromisoformat, default=END_DATE)
    settings_cli(ap, SETTINGS)
    a = ap.parse_args()
    SETTINGS[:] = narrow(SETTINGS, a)
    check_window(a.frm, a.to)
    print(f"axes: {len(combos(SETTINGS))} simulated combinations")
    asyncio.run(main(a.frm, a.to))
