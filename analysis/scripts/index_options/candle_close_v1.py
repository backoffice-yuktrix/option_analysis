"""
Candle close theory - v1 (the user, 2026-10-08; rebuilt to the user's exact rules 2026-10-10)

The user's rules, as written (2026-10-10, "these are my exact rules, make it in the v1"):

    Common rules for all variations
    1. Timeframe: Use the 3-minute or 5-minute chart. The speaker mostly uses the 3-minute timeframe.
    2. Mark C1: Mark the overall high and low of the previous day's last candle.
    3. Wait for price action: Observe how the next day's price behaves around the C1 zone.
    Variation 1 - C1 as Support Zone
       price opens above the C1 zone; wait for a candle to close inside the C1 zone; wait for a rejection at
       the same side of the C1 zone; once the rejection happens, place a buy entry.
       Stop-loss: bottom of the C1 zone.  Target: minimum risk-to-reward ratio of 1:2.
    Variation 2 - C1 as Resistance Zone (the user's text: inferred as the opposite side)
       price opens below the C1 zone; wait for a candle to close inside the C1 zone; wait for rejection at the
       same side; once rejection happens, place a sell entry.
       Stop-loss: top of the C1 zone.  Target: minimum risk-to-reward ratio of 1:2.
    Variation 3 - Trend Continuation
       price opens above the C1 zone; wait for a candle to close inside the C1 zone; instead of waiting for
       rejection, wait for a breakout; once a candle closes in the opposite direction, take the entry.
       Stop-loss: at the opposite boundary of C1 (the bottom in one example, the top in another - ambiguous).
       Target: minimum risk-to-reward ratio of 1:2.
    Variation 4 - No-Trade Zone
       if price does not reach the C1 zone during the day, do not take a trade.

The user, 2026-10-10, earlier the same day: "not only one check, check multiple time on that entry zone" - the
zone is checked again after every trade.

Checklist (Step 1 of RUN.md) - what was clear, what was assumed:

  underlying        NIFTY and SENSEX (every index strategy); weekly options                     clear
  window            START_DATE .. END_DATE from py_funcs (2026-01-01 .. 2026-07-31)
  timeframe         3-minute is the rule ("mostly uses the 3-minute"); 5-minute beside it        clear
  C1                the previous session's LAST completed candle of the timeframe
                    (3m: 15:27-15:29, 5m: 15:25-15:29); its high and low are the zone            clear
  opens above/below the session's first 1-minute open (09:15) above C1's high / below its low;
                    a day that opens inside C1 belongs to no variation (no trade)                 assumed
  close inside      a completed candle of the timeframe with C1 low <= close <= C1 high           clear
  rejection (V1/V2) a LATER candle that trades into the zone and shows one of three shapes:
                      wick       a wick on the zone side of at least half the candle's range, the
                                 close in the far half
                      engulfing  a candle whose body covers the previous opposite-coloured body
                      reclaim    a close back outside the zone on the opening side
                    any of the three fires; each shape alone is a panel setting                    assumed
  breakout (V3)     after the close inside, a candle closing below C1's low ("closes in the
                    opposite direction" of the open above)                                         clear
  V3 direction      the trend continues down through the zone: buy a PE                            clear
  V3 stop           "the opposite boundary of C1" - for a break below the zone that is its TOP
                    (the rule); its bottom is offered beside it, as the text is ambiguous         assumed
  V2 / V3 on the    V3 is written for an open above only and is traded only there; V2 has no
  other side        break-out twin.  On an open-below day a close above C1's high just waits for a
                    fresh close inside                                                             as written
  V4                a day whose candles never trade into C1 is logged 'no trade (variation 4)'    clear
  entry             the 1-minute bar after the signal candle; the option is bought at its HIGH     clear
                    (rule 1 / rule 2); 'buy entry' = buy a CE, 'sell entry' = buy a PE
  strike            ATM of the signal candle's close; the runner adds the 6 ITM .. ATM ladder      default
  expiry            the nearest expiry at least one day after the trade day (rule 10)              default
  stop / target     on the index: target = entry level +/- 2 x (distance to the stop); 1:3 beside
                    it ("minimum 1:2").  A touch in a completed 1-minute bar sells the option in
                    the next minute at its LOW; one bar touching both = the stop                   clear
  time exit         a trade still open at 15:14 is sold there (intraday)                            assumed
  last entry        no entry bar after 15:00                                                       assumed
  re-checks         one position at a time; after a trade ends the zone needs a FRESH close
                    inside before the next signal; every later setup of the day is traded          the user
  skipped signals   a signal whose entry is already beyond its stop (risk <= 0) is skipped and
                    the zone keeps being watched                                                   assumed
  not tuned         nothing in this file was chosen by looking at a result

Fills: worst price only (rule 1).  Costs: the index_options schedule.  Data: local only.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates"))
from py_funcs import *          # noqa: F401,F403

CATEGORY = "index_options"
SLUG = "candle_close_v1"

LOTS = 1
TIME_EXIT = "15:14"
LAST_ENTRY = "15:00"            # an entry bar after this is not taken
MIN_DAYS_AFTER = 1              # expiry at least one day after the trade day (rule 10)
BREAK_DATE = "2026-05-01"       # the halves read in Stability

SETUP_LABEL = {"V1": "V1 support: buy CE", "V2": "V2 resistance: buy PE", "V3": "V3 breakdown: buy PE"}

SETTINGS = [
    setting("tf", "Candle timeframe", kind="entry", values=[3, 5], default=3, unit="-minute",
            help="the candle C1, the close inside, the rejection and the breakout are read on (the rule: 3-minute)"),
    setting("rejection", "Rejection shape (variations 1 and 2)", kind="entry", mode="sweep", default="any",
            options=[{"value": "any", "label": "any of the three (the rule)"},
                     {"value": "wick", "label": "long wick on the zone side only"},
                     {"value": "engulfing", "label": "engulfing candle only"},
                     {"value": "reclaim", "label": "closed back outside the zone only"}],
            help="which candle counts as the rejection of the zone"),
    setting("v3_stop", "Variation 3 stop", kind="exit", mode="sweep", default="top",
            options=[{"value": "top", "label": "the top of C1 - its opposite boundary (the rule)"},
                     {"value": "bottom", "label": "the bottom of C1"}],
            help="the user's text names both; the target is the risk multiplied from the entry"),
    setting("rr", "Risk : reward", kind="exit", values=[2, 3], default=2, unit="x the risk",
            help="target = entry index level + this many times the distance to the stop (the rule: minimum 1:2)"),
    setting("setup", "Variation", kind="entry", mode="filter", default="any",
            options=[{"value": "any", "label": "all three (the rule)", "tag": None},
                     {"value": "V1", "label": SETUP_LABEL["V1"], "tag": {"setup": [SETUP_LABEL["V1"]]}},
                     {"value": "V2", "label": SETUP_LABEL["V2"], "tag": {"setup": [SETUP_LABEL["V2"]]}},
                     {"value": "V3", "label": SETUP_LABEL["V3"], "tag": {"setup": [SETUP_LABEL["V3"]]}}]),
    setting("checks", "Trades a day", kind="entry", mode="filter", default="every",
            options=[{"value": "every", "label": "every check of the zone (the rule)", "tag": None},
                     {"value": "first", "label": "the first trade of the day only", "tag": {"check": ["1st"]}}],
            help="after each trade the zone needs a fresh close inside before the next one"),
]


# ---------------------------------------------------------------------------
# signal - pure, completed candles only
# ---------------------------------------------------------------------------
def rejection_shapes(c: list, prev: list | None, lo: float, hi: float, bull: bool) -> list[str]:
    """Which rejection shapes a completed candle shows at the zone [lo, hi].  bull=True reads it as a
    rejection of the zone as support (lower wick, bullish engulfing, close back above hi); bull=False
    mirrors it (upper wick, bearish engulfing, close back below lo)."""
    _, o, h, l, cl = c[:5]
    rng = h - l
    out = []
    if bull:
        if rng > 0 and (min(o, cl) - l) >= 0.5 * rng and cl >= l + 0.5 * rng:
            out.append("wick")
        if prev is not None and prev[4] < prev[1] and cl > o and o <= prev[4] and cl >= prev[1]:
            out.append("engulfing")
        if cl > hi:
            out.append("reclaim")
    else:
        if rng > 0 and (h - max(o, cl)) >= 0.5 * rng and cl <= h - 0.5 * rng:
            out.append("wick")
        if prev is not None and prev[4] > prev[1] and cl < o and o >= prev[4] and cl <= prev[1]:
            out.append("engulfing")
        if cl < lo:
            out.append("reclaim")
    return out


def next_signal(candles: list[list], tf: int, lo: float, hi: float, opened: str, want: str,
                after: str, armed: bool) -> tuple | None:
    """The next signal among the candles that complete after `after` (HH:MM).

    opened  "above" -> variation 1 (rejection, buy CE) or variation 3 (close below C1, buy PE)
            "below" -> variation 2 (rejection, buy PE)
    armed   False: a close inside C1 is needed first (the start of the day, and after every trade)
    Returns (variation, index, candle, shape) or None."""
    for i, c in enumerate(candles):
        if candle_done_at(c[0], tf) <= after:
            continue
        cl = c[4]
        if not armed:
            if lo <= cl <= hi:
                armed = True
            continue
        if opened == "above":
            if cl < lo:
                return "V3", i, c, "breakout below C1"
            if c[3] <= hi:
                shapes = rejection_shapes(c, candles[i - 1] if i > 0 else None, lo, hi, True)
                if shapes and (want == "any" or want in shapes):
                    return "V1", i, c, "+".join(shapes)
        else:
            if cl > hi:                      # resistance gave way: wait for a fresh close inside
                armed = False
                continue
            if c[2] >= lo:
                shapes = rejection_shapes(c, candles[i - 1] if i > 0 else None, lo, hi, False)
                if shapes and (want == "any" or want in shapes):
                    return "V2", i, c, "+".join(shapes)
    return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
async def run(args) -> None:
    frm, to = date.fromisoformat(args.frm), date.fromisoformat(args.to)
    check_window(frm, to)
    settings = narrow(SETTINGS, args)
    rule = default_combo(settings)
    # at a ladder rung other than the rule's only the rule's own settings are kept - simulate just those
    use = combos(settings) if ladder_rung() in (None, 0) else [rule]
    print(f"{instrument()}: {len(use)} setting combination(s), rung {ladder_rung()}")

    async with Upstox() as up:
        idx = await up.find_instrument(instrument())
        key = idx["instrument_key"]
        STEP = strike_step()
        chain = await up.option_chain_info(key)
        expiries = await up.expiry_calendar(key, frm, to)
        # ten extra days before the window so the first session has a previous close candle
        sessions = await up.minute_sessions(key, frm - timedelta(days=10), to)
        days = sorted(d for d in sessions if frm.isoformat() <= d <= to.isoformat())
        all_days = sorted(sessions)
        cov = coverage({d: sessions[d] for d in days}, frm, to, rows_per_session=375)
        print(f"{len(days)} sessions in the window, {len(cov['short_sessions'])} short")
        print(fetch_estimate(len(days) * len(use) * 2))

        trades, log, option_sessions = [], [], {}
        lot_size = chain["lot_size"]
        contracts: dict = {}
        ocache: dict = {}

        for d in days:
            rows = sessions[d]
            i = all_days.index(d)
            prev = sessions[all_days[i - 1]] if i > 0 else None
            if prev is None:
                log.append(session_row(d, "no data", "no previous session on disk"))
                print(d, "no data: no previous session")
                continue
            if len(rows) < 375 or len(prev) < 375:
                log.append(session_row(d, "no data", f"short session ({len(rows)} bars today, {len(prev)} yesterday)"))
                print(d, "no data: short session")
                continue
            expiry = next_expiry(expiries, date.fromisoformat(d), MIN_DAYS_AFTER)
            day_status, day_note, day_facts = None, "", {}
            for combo in use:
                tf, want, v3_stop, rr = combo["tf"], combo["rejection"], combo["v3_stop"], combo["rr"]
                is_rule = combo == rule
                c1 = resample(prev, tf)[-1]
                lo, hi = c1[3], c1[2]
                cands = resample(rows, tf)
                o = rows[0][1]
                opened = "above" if o > hi else "below" if o < lo else "inside"
                facts = {"C1 low": lo, "C1 high": hi, "C1 pts": round(hi - lo, 2), "open": o, "opened": opened}
                if not any(c[3] <= hi and c[2] >= lo for c in cands):
                    if is_rule:
                        day_status, day_note, day_facts = ("no signal", "no trade (variation 4): price never "
                                                           "reached the C1 zone", facts)
                    continue
                if opened == "inside":
                    if is_rule:
                        day_status, day_note, day_facts = "no signal", "opened inside C1 - no variation applies", facts
                    continue
                after, armed, n_done, notes = "00:00", False, 0, []
                while True:
                    sig = next_signal(cands, tf, lo, hi, opened, want, after, armed)
                    if sig is None:
                        break
                    var, si, c, shape = sig
                    done = candle_done_at(c[0], tf)
                    eb = bar_after_candle(rows, c[0], tf)
                    if eb is None:
                        notes.append(f"{c[0]} {var}: no 1-minute bar after the candle")
                        after, armed = done, True
                        continue
                    if eb[0] > LAST_ENTRY:
                        notes.append(f"{c[0]} {var}: entry would be after {LAST_ENTRY}")
                        break
                    bull = var == "V1"
                    es = eb[4]
                    if var == "V1":
                        stop_lvl = lo
                    elif var == "V2":
                        stop_lvl = hi
                    else:
                        stop_lvl = hi if v3_stop == "top" else lo
                    risk = (es - stop_lvl) if bull else (stop_lvl - es)
                    if risk <= 0:
                        notes.append(f"{c[0]} {var}: entry {es:.2f} already beyond the stop {stop_lvl:.2f}")
                        after, armed = done, True
                        continue
                    target_lvl = es + rr * risk if bull else es - rr * risk
                    ot = "CE" if bull else "PE"
                    if expiry is None:
                        notes.append("no expiry on disk after the trade day")
                        break
                    strike = atm_strike(c[4], STEP)
                    ck = (expiry, strike, ot)
                    if ck not in contracts:
                        contracts[ck] = await up.resolve_option(key, expiry, strike, ot)
                    contract = contracts[ck]
                    if contract is None:
                        notes.append(f"{c[0]} {var}: no {ot} {strike:.0f} contract for {expiry} on disk")
                        after, armed = done, True
                        continue
                    okk = (contract["trading_symbol"], d)
                    if okk not in ocache:
                        ocache[okk] = await up.option_candles(contract, date.fromisoformat(d))
                    obars = ocache[okk]
                    oby = {b[0]: b for b in obars}
                    ex = scan_exit(rows, "LONG" if bull else "SHORT", eb[0], stop_lvl, target_lvl, TIME_EXIT)
                    if ex["bar"] is None:
                        notes.append(f"{c[0]} {var}: no exit bar found ({ex['reason']})")
                        break
                    exit_bar = ex["bar"]
                    if eb[0] not in oby or exit_bar[0] not in oby:
                        notes.append(f"{c[0]} {var}: {contract['trading_symbol']} has no option bar at "
                                     f"{eb[0] if eb[0] not in oby else exit_bar[0]}")
                        after, armed = exit_bar[0], False
                        continue
                    e_px, x_px = worst_fills("LONG", oby[eb[0]], oby[exit_bar[0]])
                    qty = LOTS * contract["lot_size"]
                    mfe, mae = excursion(obars, "LONG", e_px, eb[0], exit_bar[0])
                    n_done += 1
                    tags = {
                        "setup": SETUP_LABEL[var],
                        "signal": shape,
                        "check": "1st" if n_done == 1 else "2nd" if n_done == 2 else "3rd or later",
                        "entry hour": eb[0][:2] + ":00",
                        "risk on the index": bucket(risk / es * 100, [0.05, 0.15],
                                                    ["under 0.05%", "0.05-0.15%", "over 0.15%"]),
                        "C1 width": bucket((hi - lo) / lo * 100, [0.05, 0.15], ["under 0.05%", "0.05-0.15%", "over 0.15%"]),
                        "half": "Jan-Apr" if d < BREAK_DATE else "May-Jul",
                    }
                    t = make_trade(
                        day=d, side="LONG", symbol=contract["trading_symbol"], entry_time=eb[0], entry_px=e_px,
                        exit_time=exit_bar[0], exit_px=x_px, qty=qty, exit_reason=ex["reason"], kind="option",
                        capital=e_px * qty, entry_spot=es, exit_spot=exit_bar[4],
                        stop=None, target=None, mfe=mfe, mae=mae, variant=combo, tags=tags,
                        levels=[{"name": "previous day's last candle (C1)", "price": hi, "price2": lo,
                                 "from": rows[0][0], "to": rows[-1][0]},
                                {"name": "stop (index)", "price": stop_lvl, "from": eb[0], "to": exit_bar[0]},
                                {"name": "target (index)", "price": target_lvl, "from": eb[0], "to": exit_bar[0]}],
                        option_type=ot, expiry=contract["expiry"],
                        note=f"{SETUP_LABEL[var]}: {shape} at {c[0]}, check {n_done}; stop {stop_lvl:.2f}, "
                             f"target {target_lvl:.2f} on the index; out {exit_bar[0]} ({ex['reason']})")
                    trades.append(t)
                    if is_rule or ladder_rung() not in (None, 0):
                        option_sessions.setdefault(contract["trading_symbol"], {})[d] = obars
                    after, armed = exit_bar[0], False          # the next check needs a fresh close inside
                if is_rule:
                    day_facts = dict(facts, **{"trades": n_done})
                    if n_done:
                        day_status = "traded"
                        day_note = f"{n_done} trade(s)" + (f"; {'; '.join(notes)}" if notes else "")
                    elif notes:
                        day_status, day_note = "declined", "; ".join(notes)
                    else:
                        day_status = "no signal"
                        day_note = (f"opened {opened} C1, reached it, but no close inside followed by a "
                                    + ("rejection or breakout" if opened == "above" else "rejection"))
            if day_status is None:          # the rule combination was not simulated at this rung
                day_status, day_note = "no signal", "not simulated at this strike"
            if day_status == "declined":
                print(d, day_status, day_note)
            log.append(session_row(d, day_status, day_note, **day_facts))

        print(await broker_check(up, CATEGORY, key, lot_size, 100.0))

    groups = [
        {"name": "Variation", "keys": ["setup"]},
        {"name": "Signal (rejection shape or breakout)", "keys": ["signal"]},
        {"name": "Check of the zone that day (1st, 2nd, 3rd or later)", "keys": ["check"]},
        {"name": "Variation x check", "keys": ["setup", "check"]},
        {"name": "Hour of the entry", "keys": ["entry hour"]},
        {"name": "Risk on the index (entry to stop)", "keys": ["risk on the index"]},
        {"name": "Width of C1", "keys": ["C1 width"]},
        {"name": "Half of the window x variation", "keys": ["half", "setup"]},
    ]
    meta = {
        "title": "Candle close v1 - the user's four variations",
        "subtitle": "the previous day's last candle (C1) as a zone: support (V1), resistance (V2), trend continuation "
                    "through it (V3), no trade when price never reaches it (V4); stop on the C1 boundary, 1:2 target, "
                    "the zone checked again after every trade",
        "category": CATEGORY, "instrument": instrument(), "from": args.frm, "to": args.to,
        "lot_size": lot_size, "break_date": BREAK_DATE,
        "fill_rule": "worst price: the option is bought at its 1-minute bar's HIGH, sold at the LOW",
        "params": {
            "C1": "the previous session's last completed candle of the timeframe (3m: 15:27-15:29; 5m: 15:25-15:29)",
            "timeframe": "3-minute (the rule); 5-minute beside it",
            "variation 1": "opens above C1, a close inside C1, then a candle that trades into C1 and rejects it "
                           "(wick / engulfing / close back above) -> buy CE; stop C1's bottom",
            "variation 2": "opens below C1, a close inside C1, then a candle that trades into C1 and rejects it "
                           "(wick / engulfing / close back below) -> buy PE; stop C1's top",
            "variation 3": "opens above C1, a close inside C1, then a candle closing below C1 -> buy PE; stop C1's top "
                           "(the opposite boundary; the bottom is in the panel)",
            "variation 4": "price never reaches C1 during the day -> no trade",
            "target": "entry index level + 2 x (distance to the stop) - 1:2; 1:3 in the panel",
            "re-checks": "one position at a time; after a trade ends the zone needs a fresh close inside, then the "
                         "next rejection or breakout is traded again",
            "entry": "the 1-minute bar after the signal candle; ATM of the signal candle's close",
            "exits": "stop or target touched in a completed 1-minute index bar -> sold in the next minute; both in one "
                     f"bar = stop; else sold at {TIME_EXIT}",
            "last entry": f"an entry bar after {LAST_ENTRY} is not taken",
            "expiry": "nearest at least 1 day after the trade day", "lots": LOTS,
        },
        "rule_steps": [
            "Take the previous session's last 3-minute candle (15:27 to 15:29). Its high and low are the zone, C1.",
            "If price never reaches C1 during the day, there is no trade (variation 4). A day that opens inside C1 "
            "belongs to no variation.",
            "Opened above C1: wait for a 3-minute candle to close inside C1. Then either a later candle trades into "
            "C1 and rejects it (a long lower wick, a bullish engulfing candle, or a close back above C1) - buy the "
            "ATM CE, stop at C1's bottom (variation 1) - or a candle closes below C1 - buy the ATM PE, stop at C1's "
            "top (variation 3).",
            "Opened below C1: wait for a 3-minute candle to close inside C1, then a later candle that trades into C1 "
            "and rejects it (a long upper wick, a bearish engulfing candle, or a close back below C1) - buy the ATM "
            "PE, stop at C1's top (variation 2).",
            "Buy in the one-minute bar after the signal candle, at that bar's high. Target: the entry index level plus "
            "twice the distance to the stop (1:2).",
            f"Sell in the minute after the index touches the stop or the target (both in one bar counts as the stop); "
            f"otherwise sell at {TIME_EXIT}. No entry after {LAST_ENTRY}.",
            "After a trade ends, wait for a fresh close inside C1 and trade the next rejection or breakout the same "
            "way. One trade open at a time.",
        ],
        "limits": [
            "Nothing in this rule was chosen by looking at a result: every number is the user's or a plain default "
            "named in the parameters. The panel's other values (5-minute, each rejection shape alone, variation 3's "
            "bottom stop, 1:3, the first trade of the day only) are comparisons on the same window, so any of them "
            "that looks better is in-sample.",
            "Variation 2 is the user's inferred opposite of variation 1. Variation 3 is written for an open above C1 "
            "only and is traded only there.",
            "Variation 3's stop is ambiguous in the user's text (the bottom in one example, the top in another); the "
            "rule takes the top, the opposite boundary of a break below C1, and the panel shows the bottom.",
            "'Rejection' is defined three ways (wick, engulfing, close back outside); the rule fires on the first "
            "candle showing any. Other definitions were not tried.",
            "Stop and target are index levels; the option is sold at its own bar's low in the minute after the index "
            "touches the level, so the rupee outcome is not exactly 1:2 on the premium. A thin C1 gives a small risk, "
            "and a small 1:2 target can be eaten by the worst-price fills.",
            f"Intraday only: a trade still open at {TIME_EXIT} is sold there.",
            "Capital is premium x quantity for a bought option.",
        ],
        "rejected": [
            "A minimum risk (a floor on entry-to-stop) - not in the user's rules; adding one would be tuning.",
            "A breakout twin of variation 3 for an open below C1 - not in the user's rules.",
            "A trailing stop or a partial exit - the rules are a fixed stop and a 1:2 target.",
            "Holding overnight - the rules name no overnight hold.",
        ],
        "coverage": cov,
        "sources": upstox_sources(options_used="every fill of the traded contract") + [costs_source()],
    }
    # at a ladder rung other than the rule's only the rule's own values were simulated: declare just those,
    # so build_payload does not warn about values this rung never ran (the runner keeps the full panel)
    declared = settings if use != [rule] or len(use) == len(combos(settings)) else [
        dict(s, options=[o for o in s["options"] if o["value"] == s["default"]]) if s["mode"] == "sweep" else s
        for s in settings]
    payload = build_payload(meta, trades, {d: sessions[d] for d in days}, option_sessions, groups,
                            settings=declared, chart="default", sessions_log=log)
    path = write_report(payload, SLUG)
    rule_trades = [t for t in trades if all(str(t["variant"].get(k)) == str(v) for k, v in rule.items())]
    print("the rule:", console_summary(rule_trades))
    for v in ("V1", "V2", "V3"):
        print(f"  {SETUP_LABEL[v]}:", console_summary([t for t in rule_trades if t["tags"]["setup"] == SETUP_LABEL[v]]))
    for h in ("Jan-Apr", "May-Jul"):
        print(f"  {h}:", console_summary([t for t in rule_trades if t["tags"]["half"] == h]))
    print("every setting pooled:", console_summary(trades))
    print(path)
    mr = missing_report()
    if mr:
        print(mr)


def main() -> None:
    import argparse, asyncio
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--from", dest="frm", default=START_DATE.isoformat())
    ap.add_argument("--to", dest="to", default=END_DATE.isoformat())
    settings_cli(ap, SETTINGS)
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    run_instruments(__file__)
elif __name__ == "__instrument__":
    main()
