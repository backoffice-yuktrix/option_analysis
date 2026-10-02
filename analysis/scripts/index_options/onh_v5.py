"""ONH v5: preserve v4 entries 1-8 and add the researched relative-time-value entry 9.

Only after entries 1-8 fail, and never on a holiday night:
    D = 10,000 * (TV_day_side - TV_opposite_side) / index_close_15_19
    TV = option_close_15_19 - max(intrinsic, 0)
Buy the opposite side when D <= -0.77 bps and that option's 15:19 volume is positive.
Both options use the same expiry and their own equivalent ITM depth. No gap filter.

This is the user's 2026-10-02 research candidate, not an independently validated strategy.
Keep v4's worst-minute fill convention to reproduce the comparison; disclose zero-volume
entry/exit candles rather than silently excluding them. Missing exit data is never priced.
Uses only analysis/ data and the existing report template. No scratch-file dependencies.
"""
import argparse
import os
import runpy
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'templates')))
from py_funcs import *  # noqa: F401,F403

# Fresh namespace on each run_instruments execution: v4's STEP and ratio cache are
# instrument-dependent. A normal cached import would retain NIFTY's STEP on SENSEX.
V4 = SimpleNamespace(**runpy.run_path(os.path.join(HERE, 'onh_v4.py'), run_name='__v4_rules__'))
SLUG = 'onh_v5'
TV_DIFFERENCE_MAX_BPS = -0.77
RULE_TAG = 'v5 rule'
SOURCE_TAG = 'v5 entry source'
QUALITY_TAG = 'fill volume quality'
SETTINGS = [
    setting('confirm', 'Entry rule', kind='entry', mode='filter', default='rule', options=[
        {'value': 'rule', 'label': 'v5: original entries 1-8 plus time-value entry 9',
         'tag': {RULE_TAG: ['yes']}},
        {'value': 'v4', 'label': 'v4 entries 1-8 only (comparison)',
         'tag': {V4.RULE_TAG: ['yes']}}]),
    setting('first_exit', 'First exit candle', kind='exit', values=['09:30'], default='09:30'),
    setting("moneyness", 'Strike depth', kind='strike', default=6, rerun=True,
            options=[{'value': v, 'label': V4.rung_label(v), 'raw': v} for v in V4.LADDER]),
]


def intrinsic(spot, strike, side):
    return max(spot - strike if side == 'CE' else strike - spot, 0.0)


def time_value_entry(spot, day_strike, day_side, day_bar, opposite_strike, opposite_bar):
    """Completed 15:19 bars only; return (eligible, normalized difference, explanation)."""
    if not day_bar or not opposite_bar or day_bar[4] <= 0 or opposite_bar[4] <= 0:
        return False, None, 'entry 9 unavailable: both positive 15:19 option prices are required'
    if len(opposite_bar) < 6 or opposite_bar[5] <= 0:
        return False, None, 'entry 9 false: opposite option has no positive 15:19 volume'
    opposite_side = 'PE' if day_side == 'CE' else 'CE'
    day_tv = day_bar[4] - intrinsic(spot, day_strike, day_side)
    opposite_tv = opposite_bar[4] - intrinsic(spot, opposite_strike, opposite_side)
    difference = 10000.0 * (day_tv - opposite_tv) / spot
    return difference <= TV_DIFFERENCE_MAX_BPS, difference, (
        f'entry 9: relative time value {difference:.6f} bps '
        f'{"<=" if difference <= TV_DIFFERENCE_MAX_BPS else ">"} {TV_DIFFERENCE_MAX_BPS} bps')


async def run(frm, to, settings):
    trades, log, skips, option_sessions = [], [], [], {}
    rungs = V4.values_of(settings, 'moneyness')
    rule_rung = default_combo(settings)['moneyness']
    first_exit = default_combo(settings)['first_exit']
    now = datetime.now(IST)
    async with Upstox() as up:
        key = (await up.find_instrument(instrument()))['instrument_key']
        info = await up.option_chain_info(key)
        fetch_to = min(to + timedelta(days=7), now.date())
        sessions = sessions_from(await up.candles(key, '1m', frm - timedelta(days=V4.TREND_LOOKBACK_DAYS), fetch_to))
        full = {d: r for d, r in sessions.items()
                if V4.ENTRY_MINUTES <= {x[0] for x in r}
                and not (d == now.date().isoformat() and now.strftime('%H:%M') < '15:45')}
        days = sorted(full)
        cal = await up.expiry_calendar(key, frm, to)
        asia = await V4.asia_reads(frm - timedelta(days=V4.TREND_LOOKBACK_DAYS), fetch_to)
        us_bars = await yahoo_daily(V4.US_TICKER, frm - timedelta(days=V4.TREND_LOOKBACK_DAYS), fetch_to) or []
        us_days = {b[0] for b in us_bars}
        us_span = (us_bars[0][0], us_bars[-1][0]) if us_bars else None
        ivix = {}
        try:
            vkey = (await up.find_instrument(V4.IVIX_NAME))['instrument_key']
            for d, rows in (await up.minute_sessions(vkey, frm, fetch_to)).items():
                bar = bar_at(rows, V4.READ_MIN, tolerance=0)
                if bar is not None:
                    ivix[d] = bar[4]
        except LookupError as exc:
            skips.append(f'India VIX unavailable: {exc}; entry 8 cannot qualify')
        if instrument() != REFERENCE_INSTRUMENT:
            V4.PRE_RATIOS[instrument()] = await V4.pre_window_ratio(up, instrument(), frm)

        async def option(side, strike, expiry, day):
            c = await up.resolve_option(key, expiry, strike, side)
            rows = await up.option_candles(c, date.fromisoformat(day), volume=True) if c else []
            return c, rows, {r[0]: r for r in rows}

        for d in sorted(sessions):
            if not frm.isoformat() <= d <= to.isoformat():
                continue
            if d not in full:
                log.append(session_row(d, 'no data', 'incomplete index session before 15:20'))
                continue
            side, reason, opening, closing = V4.signal(full[d])
            if side is None:
                log.append(session_row(d, 'no signal', reason))
                continue
            checks = V4.direction_checks(full, days, d, side, closing)
            ar = V4.asia_check(asia, d, side)
            us_closed = us_span is not None and us_span[0] <= d <= us_span[1] and d not in us_days
            holiday = ar['open'] < V4.ASIA_MIN_OPEN or us_closed
            facts = {'direction': 'up day' if side == 'CE' else 'down day',
                     'day move %': (closing / opening - 1) * 100,
                     V4.TREND_TAG: checks[V4.TREND_TAG], 'range ratio': checks['range ratio'],
                     'close location': checks['close location'], V4.IVIX_TAG: ivix.get(d),
                     'Asian markets open': ar['open'], V4.ASIA_TAG: ar['tag'],
                     V4.HOLIDAY_TAG: 'yes' if holiday else 'no'}
            if holiday:
                log.append(session_row(d, 'declined', 'holiday night: Asia thin or US closed; no entry permitted', **facts))
                continue
            later = [x for x in days if x > d]
            if not later or (date.fromisoformat(later[0]) - date.fromisoformat(d)).days > 5:
                log.append(session_row(d, 'no data', 'next complete session unavailable or more than five days away', **facts))
                continue
            exit_day = later[0]
            expiry = next_expiry(cal, date.fromisoformat(exit_day), 1)
            if expiry is None:
                log.append(session_row(d, 'no data', 'no expiry at least one day after exit day', **facts))
                continue
            spot = bar_at(full[d], V4.READ_MIN, tolerance=0)[4]
            rescue = ar['tag'] == V4.ASIA_AGAINST and checks['close location'] >= V4.STRONG_CLOSE
            iv = ivix.get(d)
            reverse_pre = checks['day move %'] >= V4.REVERSE_MOVE and iv is not None and iv >= V4.REVERSE_IVIX
            seen = session_row(d, 'declined', 'none of entries 1-9 qualifies', **facts)
            for depth in rungs:
                current_facts = dict(facts, **{'strike depth': depth})

                def record(status, note):
                    nonlocal seen
                    if depth == rule_rung:
                        seen = session_row(d, status, note, **current_facts)
                    if status == 'no data':
                        skips.append(f'{d} [{depth} ITM]: {note}')

                day_strike = V4.strike_at(spot, depth, side)
                c, rows, by = await option(side, day_strike, expiry, d)
                day_bar = by.get(V4.READ_MIN)
                premium = day_bar[4] if day_bar and day_bar[4] > 0 else None
                # Preserve v4's entry-5 calculation exactly, including at non-default rungs.
                day_intrinsic = spot - day_strike if side == 'CE' else day_strike - spot
                share = (premium - day_intrinsic) / premium if premium else None
                scen = dict(checks['scen'], E=checks['late pull-back'] and share is not None and share <= V4.TV_MAX_SHARE)
                fired = [k for k in 'ABCDEF' if scen[k]]
                reverse = not fired and not rescue and reverse_pre
                original = bool(fired or rescue or reverse)
                entry9, difference = False, None
                bought_side, strike = side, day_strike
                explanation = 'original entries 1-6' if fired else 'original entry 7' if rescue else 'original entry 8'
                if reverse or not original:
                    other_side = 'PE' if side == 'CE' else 'CE'
                    other_strike = V4.strike_at(spot, depth, other_side)
                    other_c, other_rows, other_by = await option(other_side, other_strike, expiry, d)
                    if not original:
                        entry9, difference, explanation = time_value_entry(
                            spot, day_strike, side, day_bar, other_strike, other_by.get(V4.READ_MIN))
                        current_facts.update({'relative time value (bps)': difference,
                                              'entry 9 true': 'yes' if entry9 else 'no'})
                    if reverse or entry9:
                        c, rows, by = other_c, other_rows, other_by
                        bought_side, strike = other_side, other_strike
                if not original and not entry9:
                    record('declined', 'entries 1-8 false; ' + explanation)
                    continue
                current_facts.update({'v4 rule': 'yes' if original else 'no',
                                      'side': bought_side, 'strike': strike,
                                      'entry source': 'original v4' if original else 'entry 9: relative time value'})
                entry = by.get(V4.ENTRY_MIN)
                if c is None or entry is None or c.get('lot_size', 0) <= 0 or entry[2] <= 0:
                    record('no data', explanation + '; bought contract, lot size or positive 15:20 candle unavailable')
                    continue
                xrows = await up.option_candles(c, date.fromisoformat(exit_day), volume=True)
                qty = V4.LOTS * c['lot_size']
                line = V4.breakeven_line(entry[2], qty, d, exit_day)
                ex = V4.simulate_exit(xrows, line, first_exit)
                if ex['bar'] is None:
                    record('no data', explanation + f'; {bought_side} signal unpriced: {ex["reason"]} on {exit_day}')
                    continue
                xb = ex['bar']
                ep, xp = worst_fills('LONG', entry, xb)
                quality = ('zero-volume entry and exit' if entry[5] <= 0 and xb[5] <= 0 else
                           'zero-volume entry' if entry[5] <= 0 else
                           'zero-volume exit' if xb[5] <= 0 else 'positive-volume entry and exit')
                current_facts.update({'entry volume': entry[5], 'exit volume': xb[5], QUALITY_TAG: quality})
                tags = {RULE_TAG: 'yes', V4.RULE_TAG: 'yes' if original else 'no',
                        SOURCE_TAG: 'original v4' if original else 'entry 9: relative time value',
                        V4.HOLIDAY_TAG: 'no', V4.SCEN_TAG: '+'.join(fired) or 'none',
                        V4.ASIA_TAG: ar['tag'], V4.TREND_TAG: checks[V4.TREND_TAG],
                        'direction': facts['direction'] + f': buy {bought_side}',
                        V4.SIDE_TAG: V4.AGAINST_DAY if reverse or entry9 else V4.WITH_DAY,
                        QUALITY_TAG: quality,
                        **{V4.entry_tag(str(i)): 'yes' if scen[k] else 'no' for i, k in enumerate('ABCDEF', 1)},
                        V4.entry_tag('7'): 'yes' if rescue else 'no',
                        V4.entry_tag('8'): 'yes' if reverse else 'no',
                        V4.entry_tag('9'): 'yes' if entry9 else 'no'}
                dated = [[f'{dd} {r[0]}'] + r[1:5] for dd, rr in [(d, rows), (exit_day, xrows)] for r in rr]
                mfe, mae = excursion(dated, 'LONG', ep, f'{d} {entry[0]}', f'{exit_day} {xb[0]}')
                xs = bar_at(full[exit_day], V4.prev_minute(xb[0]), tolerance=3, direction=-1)
                trades.append(make_trade(
                    day=d, exit_day=exit_day, side='LONG', symbol=c['trading_symbol'],
                    entry_time=entry[0], entry_px=ep, exit_time=xb[0], exit_px=xp, qty=qty,
                    exit_reason=ex['reason'], capital=ep * qty, entry_spot=spot,
                    exit_spot=xs[4] if xs else None, target=round(line, 2), mfe=mfe, mae=mae,
                    expiry=c['expiry'], option_type=bought_side,
                    variant={'moneyness': depth, 'first_exit': first_exit}, tags=tags,
                    levels=[{'name': '09:15 open', 'price': opening}, {'name': '15:14 close', 'price': closing},
                            {'name': 'strike', 'price': strike}],
                    note=f'{explanation}; {quality}; entry volume {entry[5]}, exit volume {xb[5]}; '
                         f'sell-line (paid + costs) {line:.2f}'))
                if depth == rule_rung:
                    option_sessions.setdefault(c['trading_symbol'], {}).update({d: rows, exit_day: xrows})
                record('traded', f'{explanation}; buy {bought_side} at 15:20; {quality}')
            log.append(seen)
    return trades, skips, log, full, option_sessions, info


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--from', dest='frm', default=START_DATE.isoformat())
    ap.add_argument('--to', default=END_DATE.isoformat())
    ap.add_argument('--rule-only', action='store_true', help='write onh_v5_rule.html with the v5 rule selected')
    settings_cli(ap, SETTINGS)
    args = ap.parse_args()
    if args.rule_only:
        args.set_confirm = 'rule'
    args.set_moneyness = args.set_moneyness or '6'
    settings = narrow(SETTINGS, args)
    frm, to = date.fromisoformat(args.frm), date.fromisoformat(args.to)
    check_window(frm, to)
    trades, skips, log, sessions, option_sessions, info = asyncio.run(run(frm, to, settings))
    V4.report_skips(skips)
    entry_zero = sum(t['tags'][QUALITY_TAG] in ('zero-volume entry', 'zero-volume entry and exit') for t in trades)
    exit_zero = sum(t['tags'][QUALITY_TAG] in ('zero-volume exit', 'zero-volume entry and exit') for t in trades)
    unpriced = sum(s['status'] == 'no data' and s['facts'].get('entry 9 true') == 'yes' for s in log)
    steps = [
        'Read the 09:15 index open and completed 15:14 close. Up day: CE; down day: PE; equal or missing: no signal.',
        'Keep the v4 holiday skip: fewer than four Asian markets open, or the US closed tonight, means no trade.',
        'Entry 1: five-session trend agrees AND range is normal. Entry 2: strong close AND normal range. '
        'Entry 3: small day AND normal range. Entry 4: small day AND late pull-back. '
        'Entry 5: late pull-back AND day-side time value <=15% of premium. Entry 6: small day AND middle close. '
        'Any of entries 1-6 buys with the day; matching several still produces only one position.',
        'Entry 7: if 1-6 fail, at least four Asian markets open, at most half agree with the day, AND a strong close: buy with the day.',
        'Entry 8: if 1-7 fail, absolute day move >=0.6% AND India VIX at 15:19 >=17: buy opposite to the day.',
        'Entry 9: only if all v4 entries fail, read the day-side and opposite-side options at 15:19, using the same expiry '
        'and each side\'s own ITM strike. Both prices must be positive; opposite-side 15:19 volume must be positive.',
        'For entry 9, TV = premium minus max(intrinsic value, 0). D = 10,000 x (TV_day - TV_opposite) / index at 15:19. '
        f'If D <= {TV_DIFFERENCE_MAX_BPS} bps, buy opposite to the day; otherwise do not enter.',
        'Use the nearest expiry at least one day after the next complete session. Buy one contract lot at the 15:20 high.',
        'Sell-line = paid plus round-trip costs per unit. From 09:30 next session, a completed candle LOW above the line '
        'triggers sale at the NEXT minute LOW. Otherwise sell at the 15:14 LOW. No stop or target.',
        'Missing entry/exit candles leave the signal unpriced. Zero-volume fill candles are retained for comparison and explicitly flagged.',
    ]
    limits = [
        'RESEARCH CANDIDATE. The -0.77 bps threshold was mined using January-March 2026, checked on April and then May-July. '
        'This is not untouched validation: v4 already used this history. The add-on did not improve May-July profit factor.',
        'NO ORIGINAL TRADES REMOVED. Entries 1-8 take precedence; entry 9 cannot reverse or filter out a qualifying v4 position. '
        'There is no opening-gap filter and no additional global time-value filter.',
        f'ZERO-VOLUME FILLS. {entry_zero} recorded entries and {exit_zero} recorded exits have zero volume in this run. '
        'Counts overlap. Their candle prices do not prove executable fills. Retained to reproduce the user-approved comparison.',
        f'MISSING DATA. {unpriced} qualifying entry-9 signals have no complete priced outcome. They remain no data in Every day '
        'and contribute neither a fabricated profit nor a fabricated loss.',
        'Original entries 1-8 reuse v4 signal, strike and exit helpers. Entry 9 uses its own complete option volume read. '
        'Data, costs, trade construction and HTML format come from py_funcs; no scratch artifacts or external downloads are required.',
        'Normal range: >=0.8 and <1.2 times the previous 20 sessions\' mean range. Small day: <0.3%. '
        'Strong close: directional location >=0.8. Middle close: >=0.5 and <0.8. Late pull-back: 14:59 to 15:14, including flat.',
        'Strike depth is expressed in NIFTY strikes; SENSEX uses its price ratio from before the window, rounded to its own strike step.',
        'US closure is inferred from local S&P 500 daily dates inside their coverage span, as in v4; missing coverage does not establish a holiday.',
        'Both indices may hold positions on the same date. Their trades are correlated. Time value also reflects carry and stale quotes, not just mispricing.',
    ]
    meta = dict(title='Over night Hold v5' + (' - the rule' if args.rule_only else ''),
                subtitle='Original v4 entries 1-8 plus entry 9: relative option time value. Original trade dates retained; '
                         'opposite-side add-on only after v4 declines. Missing outcomes and zero-volume fills disclosed.',
                instrument=instrument() + ' options', category='index_options',
                **{'from': frm.isoformat(), 'to': to.isoformat()},
                lot_size=trades[-1]['qty'] if trades else info['lot_size'],
                fill_rule='WORST ONLY: buy at 15:20 HIGH; sell at next trigger minute LOW or scheduled 15:14 LOW.',
                params={'entry': '15:20', 'first exit candle': '09:30', 'time exit': '15:14', 'lots': V4.LOTS,
                        'entry 9 threshold': f'D <= {TV_DIFFERENCE_MAX_BPS} bps',
                        'entry 9 formula': 'D = 10,000 x (TV_day - TV_opposite) / spot at 15:19',
                        'entry 9 volume': 'opposite option 15:19 volume >0',
                        'priority': 'entries 1-6, then 7, then 8, then 9; never a holiday night',
                        'expiry': 'nearest >=1 day after exit day', 'strike': V4.depth_text()},
                rule_steps=steps, limits=limits, coverage=coverage(sessions, frm, to, V4.ROWS_PER_SESSION),
                price_ratio=dict(V4.PRE_RATIOS),
                price_ratio_basis=f'median close ratio of the {V4.TREND_LOOKBACK_DAYS} calendar days before {frm}')
    groups = [{'name': 'Original v4 or entry 9', 'keys': [SOURCE_TAG]},
              {'name': 'Fill volume quality', 'keys': [QUALITY_TAG]},
              {'name': 'Direction', 'keys': ['direction']},
              {'name': 'Original scenarios', 'keys': [V4.SCEN_TAG]}]
    payload = build_payload(meta, trades, sessions, option_sessions, groups, settings=settings,
                            chart='default', sessions_log=log, worst_only=True)
    print(console_summary(trades))
    print(write_report(payload, SLUG + ('_rule' if args.rule_only else '')))


if __name__ == '__main__':
    run_instruments(__file__, ladder=(6,))
elif __name__ == '__instrument__':
    main()
