"""ONH v4 - the rolling two-week chart (the user, 2026-09-30).

Reads the trades already embedded in analysis/report/index_options/onh_v4.html (no fetching, no
re-simulation), keeps only THE RULE's own book - the panel's defaults: 6 strikes ITM, first exit 09:30,
the v4 direction check on (a scenario A-F, the Asia rescue or the reverse), never a holiday night -
and writes analysis/working strategy reports/onh_v4_weekly.html (the user, 2026-10-01: charts of this type -
analysis pages built on a working strategy's report - live in that folder, not in analysis/report).

  pnl % of a trade = 100 x net profit (after costs) / buy cost (premium x qty)   - the report's 'rom'

  X axis   calendar weeks (Monday-Sunday), week 1 = the week of the window's first session.  Week 1 alone
           is skipped; the point for week k (k >= 2) is the PAIR of weeks k-1 and k, so every point is a
           two-week window and neighbouring points share one week.
  Panel 1  trades in the pair / trading days in the pair x 100
  Panel 2  mean pnl % per trade in the pair (sum of pnl % / trades), and the same mean with the best two
           trades of the pair left out (sum of pnl % less the two largest, / (trades - 2); blank when the
           pair holds two trades or fewer)
  Panel 3  buy cost per trading day: sum of the pair's buy costs (premium x qty, rupees) / trading days in the
           pair, and the same with the pair's two CHEAPEST trades left out: (sum of buy costs less the two
           smallest) / (trading days - 2) - the user's formula, 2026-09-30 (blank when the pair holds two
           trades or fewer)

  Scatter  (the user, 2026-10-01) one column of dots per traded night.  X = trading days of the window; Y = how
           many of the rule's 8 entries were TRUE that night (the dots stack 1, 2, 3 ... so the column's top is
           the count); colour = which entry (8 colours); size = that night's pnl % (area, capped at the 95th
           percentile; a filled dot is a profit, a hollow one a loss).  The entries are read from the trade's
           tags: 1-6 = scenarios A-F, 7 = Asia against the day AND a strong close, 8 = the opposite side.

Trading days = every session in the report's session log for that index (traded, declined or no data):
the market was open, the rule looked.  Both indices in the report are charted, NIFTY first.

Run:  analysis/.venv/Scripts/python.exe analysis/scripts/index_options/onh_v4_weekly.py
"""
import json
import os
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "report", "index_options"))
SRC = os.path.join(REPORT_DIR, "onh_v4.html")
# Analysis charts built on a working strategy go to their own folder (the user, 2026-10-01), not analysis/report.
CHART_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "working strategy reports"))
OUT = os.path.join(CHART_DIR, "onh_v4_weekly.html")
DATA_START, DATA_END = "/*DATA_START*/", "/*DATA_END*/"

# THE RULE, as the report's panel defaults it (onh_v4.py SETTINGS): a sweep value per variant key,
# and a filter tag per filter setting.
RULE_VARIANT = {"moneyness": "6", "first_exit": "09:30"}
RULE_TAGS = {"v4 rule": "yes", "holiday night": "no"}
DROP_BEST = 2                      # the trimmed mean leaves out this many of the pair's best trades
DROP_CHEAP = 2                     # the trimmed buy cost leaves out this many of the pair's cheapest trades


# THE 8 ENTRIES (onh_v4.py ENTRY_POINTS, the user, 2026-10-01): two parts joined by AND; the night is entered when at
# least one of 1-7 is true, or - only when 1-7 are all false - entry 8, which buys the other way.
#   (number, short name, the two parts, the trade tag that says scenario A-F fired)
ENTRIES = [
    ("1", "A", "5-day trend agrees + normal range", "A trend + normal range"),
    ("2", "B", "strong close + normal range", "B strong close + normal range"),
    ("3", "C", "small day + normal range", "C small day + normal range"),
    ("4", "D", "small day + late pull-back", "D small day + late pull-back"),
    ("5", "E", "late pull-back + time value 15% or less", "E late pull-back + time value <= 15%"),
    ("6", "F", "small day + middle close", "F small day + middle close"),
    ("7", "Asia", "at most half of Asia moved our way + strong close", None),
    ("8", "Opposite side", "day moved 0.6% or more + India VIX 17 or more", None),
]


def entries_true(t: dict) -> list[str]:
    """The numbers of the entries that were true on this trade's night, from its tags."""
    tg = t["tags"]
    if tg.get("side vs day", "").startswith("against"):                 # entry 8: checked only when 1-7 are all false
        return ["8"]
    out = [num for num, _n, _w, tag in ENTRIES if tag and tg.get(tag) == "yes"]
    if tg.get("Asia today") == "against the day" and tg.get("close location", "").startswith("strong"):
        out.append("7")
    if not out:
        raise SystemExit(f"{t['day']} {t['symbol']}: a rule trade with no entry true - the report's tags have changed")
    return out


def read_payload(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        html = f.read()
    a, b = html.index(DATA_START) + len(DATA_START), html.index(DATA_END)
    return json.loads(html[a:b].replace("<\\/", "</"))


def monday_of(day: str) -> date:
    d = date.fromisoformat(day)
    return d - timedelta(days=d.weekday())


def is_rule_trade(t: dict) -> bool:
    return (all(t["variant"].get(k) == v for k, v in RULE_VARIANT.items())
            and all(t["tags"].get(k) == v for k, v in RULE_TAGS.items()))


def pnl_pct(t: dict) -> float:
    return 100.0 * t["net"] / t["capital"]


def fmt_day(d: date) -> str:
    return d.strftime("%d %b").lstrip("0")


def series_for(inst: str | None, trades: list[dict], sessions: list[dict]) -> dict:
    """The rolling pairs for one index."""
    days = sorted(r["day"] for r in sessions if r.get("instrument") == inst)
    book = sorted((t for t in trades if t.get("instrument") == inst and is_rule_trade(t)), key=lambda t: t["day"])
    if not days:
        raise SystemExit(f"{inst}: no sessions in the report's log")
    first_monday = monday_of(days[0])
    n_weeks = (monday_of(days[-1]) - first_monday).days // 7 + 1
    week_of = lambda day: (monday_of(day) - first_monday).days // 7 + 1      # noqa: E731
    days_by_week: dict[int, list[str]] = {}
    for d in days:
        days_by_week.setdefault(week_of(d), []).append(d)
    trades_by_week: dict[int, list[dict]] = {}
    for t in book:
        trades_by_week.setdefault(week_of(t["day"]), []).append(t)
    points = []
    for k in range(2, n_weeks + 1):
        pair = (k - 1, k)
        pdays = [d for w in pair for d in days_by_week.get(w, [])]
        ptr = [t for w in pair for t in trades_by_week.get(w, [])]
        pnls = sorted((pnl_pct(t) for t in ptr), reverse=True)
        n = len(pnls)
        total = sum(pnls)
        best = pnls[:DROP_BEST]
        trimmed = (total - sum(best)) / (n - DROP_BEST) if n > DROP_BEST else None
        costs = sorted(t["capital"] for t in ptr)
        cost_sum = sum(costs)
        cheap = costs[:DROP_CHEAP]
        nd = len(pdays)
        cost_trim = ((cost_sum - sum(cheap)) / (nd - DROP_CHEAP)
                     if n > DROP_CHEAP and nd > DROP_CHEAP else None)
        mon = first_monday + timedelta(weeks=k - 2)
        points.append({
            "k": k, "weeks": f"W{k - 1}+W{k}",
            "from": pdays[0] if pdays else mon.isoformat(),
            "to": pdays[-1] if pdays else (mon + timedelta(days=13)).isoformat(),
            "monday": mon.isoformat(),
            "days": len(pdays), "trades": n,
            "rate": 100.0 * n / len(pdays) if pdays else None,
            "sum": total, "mean": total / n if n else None,
            "best": [round(v, 2) for v in best], "trimmed": trimmed,
            "cost_sum": round(cost_sum, 2), "cost_day": cost_sum / nd if nd else None,
            "cheap": [round(v, 2) for v in cheap], "cost_day_trim": cost_trim,
            "list": [{"day": t["day"], "symbol": t["symbol"], "pnl": round(pnl_pct(t), 2), "cost": round(t["capital"], 2)}
                     for t in ptr],
        })
    day_no = {d: i for i, d in enumerate(days)}
    nights = [{"day": t["day"], "i": day_no[t["day"]], "symbol": t["symbol"], "pnl": round(pnl_pct(t), 2),
               "cost": round(t["capital"], 2), "entries": entries_true(t)} for t in book]
    entry_stats = {}
    for num, *_ in ENTRIES:
        hit = [x["pnl"] for x in nights if num in x["entries"]]
        entry_stats[num] = {"n": len(hit), "win": 100.0 * sum(v > 0 for v in hit) / len(hit) if hit else None,
                            "mean": sum(hit) / len(hit) if hit else None}
    all_pnl = sorted((pnl_pct(t) for t in book), reverse=True)
    n = len(all_pnl)
    all_cost = sorted(t["capital"] for t in book)
    nd = len(days)
    return {
        "instrument": inst, "weeks": n_weeks, "days": len(days), "trades": n,
        "first_day": days[0], "last_day": days[-1],
        "rate": 100.0 * n / len(days), "mean": sum(all_pnl) / n if n else None,
        "trimmed": (sum(all_pnl) - sum(all_pnl[:DROP_BEST])) / (n - DROP_BEST) if n > DROP_BEST else None,
        "cost_day": sum(all_cost) / nd if nd else None,
        "cost_day_trim": ((sum(all_cost) - sum(all_cost[:DROP_CHEAP])) / (nd - DROP_CHEAP)
                          if n > DROP_CHEAP and nd > DROP_CHEAP else None),
        "points": points,
        "sessions": days, "nights": nights, "entry_stats": entry_stats,
    }


def build(payload: dict) -> dict:
    meta = payload["meta"]
    insts = meta.get("instruments") or [None]
    data = [series_for(i, payload["trades"], payload["sessions"]) for i in insts]
    return {
        "title": meta.get("title", "Over night Hold v4"),
        "from": meta.get("from"), "to": meta.get("to"), "generated": meta.get("generated"),
        "rule": f"{RULE_VARIANT['moneyness']} strikes ITM, first exit {RULE_VARIANT['first_exit']}, "
                f"the v4 rule (a scenario A-F, the Asia rescue or the reverse), no holiday nights, "
                f"time-value check off",
        "drop_best": DROP_BEST, "drop_cheap": DROP_CHEAP,
        "entries": [{"num": num, "name": name, "what": what} for num, name, what, _tag in ENTRIES],
        "series": data,
    }


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>ONH v4 Rolling Weeks</title>
<style>
:root{
  color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#eb6834;
  --c1:#2a78d6; --c2:#eb6834; --c3:#1baf7a; --c4:#eda100; --c5:#e87ba4; --c6:#008300; --c7:#4a3aa7; --c8:#e34948; --good:#006300; --bad:#d03b3b;
  --tip:#ffffff;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    color-scheme: dark;
    --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#d95926;
  --c1:#3987e5; --c2:#d95926; --c3:#199e70; --c4:#c98500; --c5:#d55181; --c6:#008300; --c7:#9085e9; --c8:#e66767; --good:#0ca30c; --bad:#e66767;
    --tip:#232322;
  }
}
:root[data-theme="dark"]{
  color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926;
  --c1:#3987e5; --c2:#d95926; --c3:#199e70; --c4:#c98500; --c5:#d55181; --c6:#008300; --c7:#9085e9; --c8:#e66767; --good:#0ca30c; --bad:#e66767;
  --tip:#232322;
}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;
  padding-block:20px 40px;padding-inline:16px}
.wrap{max-width:1040px;margin:0 auto;display:flex;flex-direction:column;gap:18px}
h1{font-size:22px;line-height:1.2;margin:0;font-weight:650;text-wrap:balance}
h2{font-size:15px;margin:0;font-weight:650}
p{margin:0}
.sub{color:var(--ink-2);max-width:72ch}
.eyebrow{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600}
.toolbar{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center}
.seg{display:inline-flex;border:1px solid var(--axis);border-radius:8px;overflow:hidden}
.seg button{background:transparent;border:0;color:var(--ink-2);padding:6px 14px;font:inherit;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--surface)}
.seg button:focus-visible{outline:2px solid var(--s1);outline-offset:-2px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:10px 12px}
.tile .l{font-size:12px;color:var(--ink-2)}
.tile .v{font-size:22px;font-weight:600;margin-top:2px}
.tile .d{font-size:12px;color:var(--muted)}
.panel{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:14px 14px 8px;position:relative}
.panel header{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px 16px;align-items:baseline;margin-bottom:4px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--ink-2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.legend i{display:inline-block;width:18px;height:0;border-top:2px solid var(--s1);border-radius:2px}
.legend i.s2{border-color:var(--s2)}
.legend i.rate{border-color:var(--s1)}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{font:11px system-ui,-apple-system,"Segoe UI",sans-serif;fill:var(--muted);font-variant-numeric:tabular-nums}
svg .grid{stroke:var(--grid);stroke-width:1}
svg .axis{stroke:var(--axis);stroke-width:1}
svg .zero{stroke:var(--ink-2);stroke-width:1}
svg .line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
svg .l1{stroke:var(--s1)} svg .l2{stroke:var(--s2)}
svg .wash{fill:var(--s1);opacity:.10}
svg .dot{stroke:var(--surface);stroke-width:2}
svg .d1{fill:var(--s1)} svg .d2{fill:var(--s2)}
svg .dot.gap{fill:var(--surface);stroke:var(--s2)}
svg .endlab{fill:var(--ink);font-weight:600}
svg .xhair{stroke:var(--ink-2);stroke-width:1;opacity:0;pointer-events:none}
svg .hit{fill:transparent;cursor:crosshair}
.tip{position:absolute;pointer-events:none;background:var(--tip);color:var(--ink);border:1px solid var(--ring);
  border-radius:8px;padding:8px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.14);min-width:200px;
  opacity:0;transition:opacity .08s;z-index:2}
.tip b{font-weight:600}
.tip .row{display:flex;justify-content:space-between;gap:14px}
.tip .k{color:var(--ink-2)}
.tip .n{font-variant-numeric:tabular-nums}
.tip .tr{margin-top:6px;padding-top:6px;border-top:1px solid var(--grid);color:var(--ink-2);font-size:11px;line-height:1.5}
.tip .tr .n{color:var(--ink)}
.up{color:var(--good)} .dn{color:var(--bad)}
details{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:10px 14px}
summary{cursor:pointer;font-weight:600}
.tablewrap{overflow-x:auto;margin-top:10px}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
th{color:var(--ink-2);font-weight:600;font-size:12px}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){text-align:left}
tr:hover td{background:color-mix(in srgb,var(--s1) 6%,transparent)}
.notes{color:var(--ink-2);font-size:13px;display:grid;gap:6px;max-width:80ch}
.notes li{margin:0}
.notes ul{margin:0;padding-left:18px;display:grid;gap:4px}
.scroll{overflow-x:auto}
.scroll svg{max-width:none}
.entleg svg,.sizekey svg,.tip svg{width:auto;height:auto;display:inline-block;flex:none;vertical-align:middle}
svg .bub.win{fill:var(--c);stroke:var(--surface);stroke-width:1.5;opacity:.92}
svg .bub.loss{fill:var(--surface);stroke:var(--c);stroke-width:2}
svg .bub.dim{opacity:.08}
.entleg{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:6px;margin:10px 0 6px}
.entleg button{display:grid;grid-template-columns:14px 1fr;column-gap:8px;row-gap:1px;align-items:center;text-align:left;
  background:transparent;border:1px solid var(--ring);border-radius:8px;padding:6px 8px;font:inherit;font-size:12px;
  color:var(--ink);cursor:pointer}
.entleg button[aria-pressed="true"]{border-color:var(--ink);background:color-mix(in srgb,var(--ink) 6%,transparent)}
.entleg button:focus-visible{outline:2px solid var(--s1);outline-offset:1px}
.entleg .st{grid-column:2;color:var(--ink-2);font-variant-numeric:tabular-nums}
.sizekey{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;font-size:12px;color:var(--ink-2)}
.sizekey span{display:inline-flex;align-items:center;gap:5px}
.tip .ent{display:flex;align-items:center;gap:6px}
details + details{margin-top:-8px}
@media (prefers-reduced-motion: reduce){.tip{transition:none}}
</style>
</head>
<body>
<div class="wrap">
  <div>
    <div class="eyebrow">Over night Hold v4 &middot; the rule's own book</div>
    <h1>Two-week rolling read of the ONH v4 rule</h1>
    <p class="sub" id="sub"></p>
  </div>

  <div class="toolbar">
    <div class="seg" role="group" aria-label="Index" id="inst"></div>
    <span class="eyebrow" id="rule"></span>
  </div>

  <div class="tiles" id="tiles"></div>

  <section class="panel" id="p1">
    <header>
      <div><h2>Trades per trading day</h2><div class="eyebrow">trades in the pair &divide; trading days in the pair &times; 100</div></div>
    </header>
    <svg id="svg1" role="img" aria-label="Trade rate per two-week window"></svg>
    <div class="tip" id="tip1"></div>
  </section>

  <section class="panel" id="p2">
    <header>
      <div><h2>Mean pnl % per trade</h2><div class="eyebrow">pnl % = 100 &times; net profit &divide; buy cost; the second line drops the pair's best two trades</div></div>
      <div class="legend"><span><i></i>mean of all trades</span><span><i class="s2"></i>mean without the best 2</span></div>
    </header>
    <svg id="svg2" role="img" aria-label="Mean pnl per trade per two-week window, with and without the best two trades"></svg>
    <div class="tip" id="tip2"></div>
  </section>

  <section class="panel" id="p3">
    <header>
      <div><h2>Buy cost per trading day</h2><div class="eyebrow">sum of the pair's buy costs (premium &times; lot) &divide; trading days; the second line drops the pair's 2 cheapest trades and 2 days</div></div>
      <div class="legend"><span><i></i>all trades &divide; trading days</span><span><i class="s2"></i>without the 2 cheapest &divide; (trading days &minus; 2)</span></div>
    </header>
    <svg id="svg3" role="img" aria-label="Buy cost per trading day per two-week window, with and without the two cheapest trades"></svg>
    <div class="tip" id="tip3"></div>
  </section>

  <section class="panel" id="p4">
    <header>
      <div><h2>Which entries were true each night</h2><div class="eyebrow">one column per traded night &middot; height = how many of the 8 entries were true &middot; colour = the entry &middot; size = that night's pnl %</div></div>
      <div class="sizekey" id="key4"></div>
    </header>
    <div class="scroll"><svg id="svg4" role="img" aria-label="Scatter of traded nights: trading days across, number of entries true up, coloured by entry, sized by the night's pnl percent"></svg></div>
    <div class="tip" id="tip4"></div>
    <div class="entleg" id="leg4" role="group" aria-label="The 8 entries; press one to show it alone"></div>
  </section>

  <details>
    <summary>The numbers behind the chart</summary>
    <div class="tablewrap"><table id="tbl"></table></div>
  </details>

  <details>
    <summary>The nights behind the scatter</summary>
    <div class="tablewrap"><table id="tbl4"></table></div>
  </details>

  <div class="notes" id="notes"></div>
</div>

<script>
const DATA = /*DATA_START*/__DATA__/*DATA_END*/;
let cur = 0;
const $ = id => document.getElementById(id);
const sgn = v => v == null ? '–' : (v > 0 ? '+' : '') + v.toFixed(1) + '%';
const pct = v => v == null ? '–' : v.toFixed(0) + '%';
const cls = v => v == null ? '' : v >= 0 ? 'up' : 'dn';
const rs = v => v == null ? '–' : '₹' + (Math.abs(v) >= 1e5 ? (v / 1e5).toFixed(2) + 'L' : Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(0));
const rsFull = v => v == null ? '–' : '₹' + Math.round(v).toLocaleString('en-IN');
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const dm = iso => { const d = new Date(iso + 'T00:00:00'); return d.getDate() + ' ' + MON[d.getMonth()]; };
const dmy = iso => dm(iso) + ' ' + iso.slice(0, 4);

function init() {
  $('sub').textContent = `Every point is a pair of calendar weeks, ${DATA.from ? dmy(DATA.from) : ''} to ${DATA.to ? dmy(DATA.to) : ''}: week 1 alone is skipped, then weeks 1+2, 2+3, 3+4 and so on, so neighbouring points share a week. Only the nights the rule itself traded are counted, at the panel's default settings.`;
  $('rule').textContent = DATA.rule;
  const seg = $('inst');
  DATA.series.forEach((s, i) => {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = s.instrument || 'index'; b.id = 'inst-' + i;
    b.setAttribute('aria-pressed', i === cur);
    b.onclick = () => { cur = i; [...seg.children].forEach((c, j) => c.setAttribute('aria-pressed', j === i)); render(); };
    seg.appendChild(b);
  });
  if (DATA.series.length < 2) seg.hidden = true;
  render();
  addEventListener('resize', render);
}

function tiles(s) {
  const t = [
    ['Trades', s.trades, `${s.days} trading days, ${s.weeks} weeks`],
    ['Trades per trading day', pct(s.rate), 'whole window'],
    ['Mean pnl % per trade', sgn(s.mean), 'all trades, net of costs'],
    [`Mean without the best ${DATA.drop_best}`, sgn(s.trimmed), 'whole window'],
    ['Buy cost per trading day', rs(s.cost_day), 'all trades ÷ trading days'],
    [`Without the ${DATA.drop_cheap} cheapest`, rs(s.cost_day_trim), `÷ (trading days − ${DATA.drop_cheap})`],
  ];
  $('tiles').innerHTML = t.map(([l, v, d]) => `<div class="tile"><div class="l">${l}</div><div class="v ${typeof v === 'string' && v[0] === '+' ? 'up' : typeof v === 'string' && v[0] === '-' ? 'dn' : ''}">${v}</div><div class="d">${d}</div></div>`).join('');
}

// ---- the scatter: one column of dots per traded night
let iso = null;                                    // the entry shown alone (legend press), or null
const CAP = (() => {                               // size cap: the 95th percentile of |pnl %| over both indices
  const v = DATA.series.flatMap(s => s.nights.map(n => Math.abs(n.pnl))).sort((a, b) => a - b);
  return v.length ? Math.max(1, v[Math.floor((v.length - 1) * 0.95)]) : 1;
})();
const R_MAX = 11, rad = v => Math.max(2.5, R_MAX * Math.sqrt(Math.min(1, Math.abs(v) / CAP)));
const ENT = Object.fromEntries(DATA.entries.map(e => [e.num, e]));
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const entName = e => `<b>${e.num}</b> &middot; ${e.name}: ${e.what}`;
const sw = (num, r) => `<svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="${r || 6}" style="fill:var(--c${num})"/></svg>`;

function scatterKey() {
  const top = Math.max(10, Math.round(CAP / 10) * 10), vals = [10, 50, top].filter((v, i, a) => v <= top && a.indexOf(v) === i);
  const circ = (r, fill) => `<svg width="${2 * r + 4}" height="${2 * r + 4}" aria-hidden="true"><circle cx="${r + 2}" cy="${r + 2}" r="${r}" style="${fill ? 'fill:var(--muted)' : 'fill:none;stroke:var(--muted);stroke-width:2'}"/></svg>`;
  $('key4').innerHTML = vals.map((v, i) => `<span>${circ(rad(v), true)}${v}%${i === vals.length - 1 ? ' or more' : ''}</span>`).join('')
    + `<span>${circ(6, true)}profit</span><span>${circ(6, false)}loss</span>`;
}

function scatterLegend(s) {
  const leg = $('leg4');
  leg.innerHTML = DATA.entries.map(e => {
    const st = s.entry_stats[e.num];
    return `<button type="button" id="ent-${e.num}" data-e="${e.num}" aria-pressed="${iso === e.num}">${sw(e.num)}<span>${entName(e)}</span><span class="st">${st.n ? `${st.n} nights &middot; ${pct(st.win)} won &middot; mean ${sgn(st.mean)}` : 'never true on a traded night'}</span></button>`;
  }).join('');
  [...leg.children].forEach(b => { b.onclick = () => { iso = iso === b.dataset.e ? null : b.dataset.e; scatterLegend(s); scatter(s); }; });
}

function scatter(s) {
  const svg = $('svg4'), box = svg.parentElement, nights = s.nights, days = s.sessions;
  const W = Math.max(720, box.clientWidth), levels = Math.max(2, ...nights.map(n => n.entries.length));
  const m = { l: 34, r: 16, t: 14, b: 30 }, band = 44, ih = levels * band, H = m.t + ih + m.b, iw = W - m.l - m.r;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('height', H); svg.style.width = W + 'px';
  const x = i => m.l + 14 + (days.length > 1 ? i / (days.length - 1) : .5) * (iw - 28);
  const y = k => m.t + ih - (k - .5) * band;
  let out = '';
  for (let k = 1; k <= levels; k++) out += `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${y(k)}" y2="${y(k)}"/><text x="${m.l - 10}" y="${y(k) + 4}" text-anchor="end">${k}</text>`;
  out += `<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih}" y2="${m.t + ih}"/>`;
  days.forEach((d, i) => {
    if (i === 0 || d.slice(5, 7) !== days[i - 1].slice(5, 7))
      out += `<line class="axis" x1="${x(i)}" x2="${x(i)}" y1="${m.t + ih}" y2="${m.t + ih + 5}"/><text x="${x(i)}" y="${m.t + ih + 19}" text-anchor="start">${MON[+d.slice(5, 7) - 1]}${i === 0 ? ' ' + d.slice(0, 4) : ''}</text>`;
  });
  const dots = [];
  nights.forEach(n => n.entries.forEach((e, j) => dots.push({ n, e, k: j + 1, r: rad(n.pnl) })));
  dots.sort((a, b) => b.r - a.r);                  // small dots on top of large ones
  dots.forEach(d => { out += `<circle class="bub ${d.n.pnl >= 0 ? 'win' : 'loss'}${iso && d.e !== iso ? ' dim' : ''}" cx="${x(d.n.i)}" cy="${y(d.k)}" r="${d.r.toFixed(1)}" style="--c:var(--c${d.e})"/>`; });
  out += `<line class="xhair" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}"/><rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}"/>`;
  svg.innerHTML = out;
  const xh = svg.querySelector('.xhair'), hit = svg.querySelector('.hit'), tip = $('tip4');
  hit.onmousemove = hit.ontouchmove = ev => {
    const rect = svg.getBoundingClientRect(), cx = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - rect.left) * (W / rect.width);
    let best = null, bd = 1e9;
    nights.forEach(n => { if (iso && !n.entries.includes(iso)) return; const d = Math.abs(x(n.i) - cx); if (d < bd) { bd = d; best = n; } });
    if (!best) return;
    const px = x(best.i); xh.setAttribute('x1', px); xh.setAttribute('x2', px); xh.style.opacity = 1;
    tip.innerHTML = `<b>${WD[new Date(best.day + 'T00:00:00').getDay()]} ${dmy(best.day)}</b>
      <div class="row"><span class="k">Bought</span><span class="n">${best.symbol}</span></div>
      <div class="row"><span class="k">pnl %</span><span class="n ${cls(best.pnl)}">${sgn(best.pnl)}</span></div>
      <div class="row"><span class="k">Buy cost</span><span class="n">${rsFull(best.cost)}</span></div>
      <div class="row"><span class="k">Entries true</span><span class="n">${best.entries.length}</span></div>
      <div class="tr">${best.entries.map(e => `<div class="ent">${sw(e, 5)}<span>${entName(ENT[e])}</span></div>`).join('')}</div>`;
    tip.style.opacity = 1;
    const prect = tip.parentElement.getBoundingClientRect(), left = rect.left - prect.left + px * (rect.width / W);
    const tw = tip.offsetWidth, flip = left + 14 + tw > prect.width - 8;
    tip.style.left = Math.max(4, flip ? left - 14 - tw : left + 14) + 'px';
    tip.style.top = (rect.top - prect.top + 4) + 'px';
  };
  hit.onmouseleave = () => { xh.style.opacity = 0; tip.style.opacity = 0; };
}

function nightsTable(s) {
  const h = ['Night', 'Bought', 'Entries true', 'Count', 'pnl %', 'Buy cost'];
  const rows = s.nights.map(n => `<tr><td>${WD[new Date(n.day + 'T00:00:00').getDay()]} ${dm(n.day)}</td><td>${n.symbol}</td><td>${n.entries.map(e => e + ' ' + ENT[e].name).join(', ')}</td><td>${n.entries.length}</td><td class="${cls(n.pnl)}">${sgn(n.pnl)}</td><td>${rsFull(n.cost)}</td></tr>`).join('');
  $('tbl4').innerHTML = `<thead><tr>${h.map(v => `<th>${v}</th>`).join('')}</tr></thead><tbody>${rows}</tbody>`;
}

function niceTicks(lo, hi, n) {
  const span = hi - lo || 1, raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * p).find(s => s >= raw) || p * 10;
  const a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step, out = [];
  for (let v = a; v <= b + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function chart(svg, pts, lines, opts) {
  const W = Math.max(320, svg.parentElement.clientWidth - 28), H = opts.h || 240;
  const m = { l: 44, r: 54, t: 14, b: 34 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('height', H);
  const vals = lines.flatMap(l => pts.map(p => p[l.key]).filter(v => v != null));
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  if (opts.min != null) lo = Math.min(lo, opts.min);
  if (opts.max != null) hi = Math.max(hi, opts.max);
  const ticks = niceTicks(lo, hi, 5); lo = ticks[0]; hi = ticks[ticks.length - 1];
  const x = i => m.l + (pts.length > 1 ? i / (pts.length - 1) * iw : iw / 2);
  const y = v => m.t + (hi - v) / (hi - lo) * ih;
  let out = '';
  ticks.forEach(v => { out += `<line class="${v === 0 && lo < 0 ? 'zero' : 'grid'}" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${opts.tick ? opts.tick(v) : v + opts.unit}</text>`; });
  out += `<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${m.t + ih}" y2="${m.t + ih}"/>`;
  const step = pts.length > 1 ? iw / (pts.length - 1) : iw, every = step >= 30 ? 1 : step >= 16 ? 2 : step >= 10 ? 3 : 4;
  pts.forEach((p, i) => {
    if (i % every === 0 || i === pts.length - 1) {
      out += `<text x="${x(i)}" y="${m.t + ih + 14}" text-anchor="middle">W${p.k}</text>`;
      if (step * every >= 44) out += `<text x="${x(i)}" y="${m.t + ih + 27}" text-anchor="middle" style="fill:var(--muted);font-size:10px">${dm(p.monday)}</text>`;
    }
  });
  lines.forEach((l, li) => {
    const segs = []; let seg = [];
    pts.forEach((p, i) => { if (p[l.key] == null) { if (seg.length) segs.push(seg); seg = []; } else seg.push([x(i), y(p[l.key])]); });
    if (seg.length) segs.push(seg);
    if (l.wash) segs.forEach(s => { out += `<path class="wash" d="M${s[0][0]},${y(lo)} ${s.map(([a, b]) => `L${a},${b}`).join(' ')} L${s[s.length - 1][0]},${y(lo)} Z"/>`; });
    segs.forEach(s => { out += `<path class="line ${l.cls}" d="${s.map(([a, b], i) => (i ? 'L' : 'M') + a + ',' + b).join(' ')}"/>`; });
    pts.forEach((p, i) => { if (p[l.key] != null) out += `<circle class="dot ${l.dot}" cx="${x(i)}" cy="${y(p[l.key])}" r="4"/>`; });
    // end label: the last defined value
    let last = -1; pts.forEach((p, i) => { if (p[l.key] != null) last = i; });
    if (last >= 0) out += `<text class="endlab" x="${x(last) + 9}" y="${y(pts[last][l.key]) + 4 + (li ? 12 : -8) * (lines.length > 1 && lines.some((o, j) => j !== li && pts[last][o.key] != null && Math.abs(y(pts[last][o.key]) - y(pts[last][l.key])) < 14) ? 1 : 0)}">${l.fmt(pts[last][l.key])}</text>`;
  });
  out += `<line class="xhair" id="${svg.id}-xh" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}"/>`;
  out += `<rect class="hit" x="${m.l - 10}" y="${m.t}" width="${iw + 20}" height="${ih}"/>`;
  svg.innerHTML = out;
  return { x, m, W, H, ih };
}

function tipHtml(p) {
  const list = p.list.map(t => `<div class="row"><span>${dm(t.day)} &middot; ${t.symbol.replace(/ \d\d [A-Z]{3} \d\d$/, '')} &middot; ${rs(t.cost)}</span><span class="n ${cls(t.pnl)}">${sgn(t.pnl)}</span></div>`).join('');
  return `<b>${p.weeks}</b> &middot; ${dm(p.from)} – ${dmy(p.to)}
    <div class="row"><span class="k">Trades / trading days</span><span class="n">${p.trades} / ${p.days} = ${pct(p.rate)}</span></div>
    <div class="row"><span class="k">Sum of pnl %</span><span class="n ${cls(p.sum)}">${sgn(p.sum)}</span></div>
    <div class="row"><span class="k">Mean per trade</span><span class="n ${cls(p.mean)}">${sgn(p.mean)}</span></div>
    <div class="row"><span class="k">Best ${DATA.drop_best}</span><span class="n">${p.best.map(sgn).join(', ') || '–'}</span></div>
    <div class="row"><span class="k">Mean without them</span><span class="n ${cls(p.trimmed)}">${p.trimmed == null ? (p.trades ? 'needs 3+ trades' : '–') : sgn(p.trimmed)}</span></div>
    <div class="row"><span class="k">Buy cost, sum</span><span class="n">${rsFull(p.cost_sum)}</span></div>
    <div class="row"><span class="k">Per trading day</span><span class="n">${rsFull(p.cost_day)}</span></div>
    <div class="row"><span class="k">Cheapest ${DATA.drop_cheap}</span><span class="n">${p.cheap.map(rsFull).join(', ') || '–'}</span></div>
    <div class="row"><span class="k">Without them ÷ (days − ${DATA.drop_cheap})</span><span class="n">${p.cost_day_trim == null ? (p.trades ? 'needs 3+ trades' : '–') : rsFull(p.cost_day_trim)}</span></div>
    ${list ? `<div class="tr">${list}</div>` : ''}`;
}

function hover(views, pts) {
  const svgs = views.map(v => v.svg), tips = views.map(v => v.tip), xhs = svgs.map(s => s.querySelector('.xhair'));
  function show(i, src) {
    pts.forEach(() => {});
    const p = pts[i];
    views.forEach((v, vi) => {
      const px = v.g.x(i);
      xhs[vi].setAttribute('x1', px); xhs[vi].setAttribute('x2', px); xhs[vi].style.opacity = 1;
      const tip = tips[vi];
      if (vi === src) {
        tip.innerHTML = tipHtml(p); tip.style.opacity = 1;
        const panel = tip.parentElement, rect = svgs[vi].getBoundingClientRect(), prect = panel.getBoundingClientRect();
        const scale = rect.width / v.g.W, left = rect.left - prect.left + px * scale;
        const tw = tip.offsetWidth, flip = left + 14 + tw > prect.width - 8;
        tip.style.left = (flip ? left - 14 - tw : left + 14) + 'px';
        tip.style.top = (rect.top - prect.top + 8) + 'px';
      } else tip.style.opacity = 0;
    });
  }
  function hide() { xhs.forEach(h => h.style.opacity = 0); tips.forEach(t => t.style.opacity = 0); }
  svgs.forEach((svg, vi) => {
    const hit = svg.querySelector('.hit'), g = views[vi].g;
    hit.onmousemove = hit.ontouchmove = e => {
      const rect = svg.getBoundingClientRect(), cx = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
      const vx = cx * (g.W / rect.width);
      let best = 0, bd = 1e9; pts.forEach((p, i) => { const d = Math.abs(g.x(i) - vx); if (d < bd) { bd = d; best = i; } });
      show(best, vi);
    };
    hit.onmouseleave = hide;
  });
}

function table(s) {
  const h = ['Weeks', 'Sessions', 'Trading days', 'Trades', 'Trades / day', 'Sum pnl %', 'Mean pnl %', `Best ${DATA.drop_best}`, `Mean without best ${DATA.drop_best}`, 'Buy cost, sum', 'Cost / trading day', `Cheapest ${DATA.drop_cheap}`, `Cost without cheapest ÷ (days − ${DATA.drop_cheap})`];
  const rows = s.points.map(p => `<tr><td>${p.weeks}</td><td>${dm(p.from)} – ${dm(p.to)}</td><td>${p.days}</td><td>${p.trades}</td><td>${pct(p.rate)}</td><td class="${cls(p.sum)}">${sgn(p.sum)}</td><td class="${cls(p.mean)}">${sgn(p.mean)}</td><td>${p.best.map(sgn).join(', ') || '–'}</td><td class="${cls(p.trimmed)}">${p.trimmed == null ? '–' : sgn(p.trimmed)}</td><td>${rsFull(p.cost_sum)}</td><td>${rsFull(p.cost_day)}</td><td>${p.cheap.map(rsFull).join(', ') || '–'}</td><td>${p.cost_day_trim == null ? '–' : rsFull(p.cost_day_trim)}</td></tr>`).join('');
  $('tbl').innerHTML = `<thead><tr>${h.map(x => `<th>${x}</th>`).join('')}</tr></thead><tbody>${rows}</tbody>`;
}

function notes(s) {
  $('notes').innerHTML = `<div class="eyebrow">How to read it</div><ul>
    <li><b>The book.</b> The trades are read from the ONH v4 report's own data at its panel defaults (${DATA.rule}). Nothing is re-simulated; change the report and re-run the script to refresh this page.</li>
    <li><b>pnl %</b> of a trade is 100 &times; net profit (after the broker-read costs) &divide; buy cost (the 15:20 premium &times; lot size), the report's return on capital. Worst fill: bought at the minute's high, sold at its low.</li>
    <li><b>Weeks</b> are Monday to Sunday. Week 1 is the week of ${dmy(s.first_day)}, the window's first session; the last is week ${s.weeks}, ending ${dmy(s.last_day)}. Each point covers the two weeks named, so a holiday week or a part week simply has fewer trading days.</li>
    <li><b>Trading days</b> are every session in the report's log for ${s.instrument || 'the index'}: the market was open and the rule looked, whether it traded, declined or had no data.</li>
    <li><b>Mean without the best ${DATA.drop_best}</b> leaves out the pair's two largest pnl % values and divides by the remaining count. It is blank when the pair holds ${DATA.drop_best} trades or fewer. Where the two lines part company, the pair's result rests on one or two nights.</li>
    <li><b>Buy cost per trading day</b> is the sum of the pair's buy costs (the 15:20 premium &times; lot size, one lot) divided by the pair's trading days, traded or not: the capital the rule tied up per market day. <b>Without the ${DATA.drop_cheap} cheapest</b> leaves out the pair's two smallest buy costs and divides by (trading days &minus; ${DATA.drop_cheap}), as asked. It is blank when the pair holds ${DATA.drop_cheap} trades or fewer.</li>
    <li><b>The scatter</b> has one column of dots per night the rule traded, across the window's trading days. A night gets one dot for each of the rule's 8 entries that was true, stacked from 1 upward in entry order, so the top of the column is the count of entries true. The colour names the entry; the dot's area is that night's pnl % (one trade a night on each index, so the night's average is that trade), capped at the 95th percentile; filled is a profit, hollow a loss. Entry 7 is counted whenever its two parts are true, also on nights a scenario fired. Entry 8 is only checked when 1 to 7 are all false, so it always stands alone. Press an entry in the legend to show it alone.</li>
  </ul>`;
}

function render() {
  const s = DATA.series[cur], pts = s.points;
  tiles(s);
  const g1 = chart($('svg1'), pts, [{ key: 'rate', cls: 'l1', dot: 'd1', wash: true, fmt: pct }], { unit: '%', min: 0, max: 100, h: 200 });
  const g2 = chart($('svg2'), pts, [
    { key: 'mean', cls: 'l1', dot: 'd1', fmt: sgn },
    { key: 'trimmed', cls: 'l2', dot: 'd2', fmt: sgn },
  ], { unit: '%', h: 280 });
  const g3 = chart($('svg3'), pts, [
    { key: 'cost_day', cls: 'l1', dot: 'd1', fmt: rs },
    { key: 'cost_day_trim', cls: 'l2', dot: 'd2', fmt: rs },
  ], { unit: '', tick: rs, min: 0, h: 240 });
  hover([{ svg: $('svg1'), tip: $('tip1'), g: g1 }, { svg: $('svg2'), tip: $('tip2'), g: g2 }, { svg: $('svg3'), tip: $('tip3'), g: g3 }], pts);
  scatterKey(); scatterLegend(s); scatter(s); nightsTable(s);
  table(s); notes(s);
}
init();
</script>
</body>
</html>
"""


def main() -> None:
    payload = read_payload(SRC)
    data = build(payload)
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    os.makedirs(CHART_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(PAGE.replace("__DATA__", blob))
    for s in data["series"]:
        tr = f"{s['trimmed']:+.1f}%" if s["trimmed"] is not None else "n/a"
        print(f"{s['instrument'] or 'index'}: {s['trades']} rule trades on {s['days']} trading days "
              f"({s['rate']:.0f}% of days), {s['weeks']} weeks -> {len(s['points'])} two-week points; "
              f"mean pnl {s['mean']:+.1f}% a trade, without the best {DROP_BEST}: {tr}; "
              f"buy cost Rs {s['cost_day']:,.0f} a trading day, without the {DROP_CHEAP} cheapest: "
              f"Rs {s['cost_day_trim']:,.0f}")
    print(OUT)


if __name__ == "__main__":
    main()
