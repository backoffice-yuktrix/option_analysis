"""ONH v5 - the rolling two-week chart (the user, 2026-10-03: "build the working strategy report for v5").

The same page as onh_v4_weekly.py, built on the FINAL v5 rule's own book.  It reads the trades already embedded in
analysis/report/index_options/onh_v5_rule.html (no fetching, no re-simulation), keeps the rule's settings - 6 strikes
ITM, the selected exit (from 09:20 sell when a candle's low is above paid + costs, else at 14:00) - and writes analysis/working strategy reports/onh_v5_weekly.html.

The chart engine is onh_v4_weekly.py's own (its panels, its formulas, its page): this script imports it, points it at
the v5 report, gives it the v5 entries, and changes the page's words where they name v4.  Every change to the page is a
checked replacement, so if the v4 page is edited this script stops and says which text it no longer finds.

  Panel 1  trades in the pair of weeks / trading days in the pair x 100
  Panel 2  mean pnl % per trade in the pair, and the same with the pair's best two trades left out
  Panel 3  buy cost per trading day, and the same with the pair's two cheapest trades left out
  Scatter  one column of dots per traded night.  A dot = an entry that stood behind the trade:
             the day's side was bought   -> each of entries 1-7 and 10 that was true
             the opposite side was bought -> entry 8 or entry 9 (both when both were true; the one that decided first)
           colour = the entry (10 colours); size = that night's pnl %; filled = a profit, hollow = a loss.

The v5 report holds only the final rule's trades, so every trade at the rule's strike and exit is in the book.

Run:  analysis/.venv/Scripts/python.exe analysis/scripts/index_options/onh_v5_weekly.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import onh_v4_weekly as W4          # noqa: E402   the chart engine and the page

SRC = os.path.join(W4.REPORT_DIR, "onh_v5_rule.html")
OUT = os.path.join(W4.CHART_DIR, "onh_v5_weekly.html")
RULE_VARIANT = {"moneyness": "6", "first_exit": "above_line", "strike_plan": "stable"}      # onh_v4.py RULE_EXIT, the selected exit
KIND_TAG, WHY_TAG, CONF_TAG = "what is bought", "decided by", "facts agreeing"     # onh_v5_rule.py's trade tags (fair rule)
K_DAY = "the day's side"
DAY_ENTRIES = ("1", "2", "3", "4")    # the fair redesign, 2026-10-06: four facts, a 2-of-4 vote
# THE FOUR FACTS (onh_v5_rule.py): (number, which side it buys, what it needs, unused)
ENTRIES = [
    ("1", "day's side", "closed beyond the 5-day closes", None),
    ("2", "day's side", "close on the day's side of the 20-day average", None),
    ("3", "day's side", "opened in the day's direction", None),
    ("4", "day's side", "the first hour went the day's way", None),
]


def entries_true(t: dict) -> list[str]:
    """The entries that stood behind this trade, from its tags."""
    tg = t["tags"]
    flag = lambda n: tg.get(f"fact {n} true") == "yes"       # noqa: E731
    out = [n for n in DAY_ENTRIES if flag(n)]
    if not out:
        raise SystemExit(f"{t['day']} {t['symbol']}: a rule trade with no entry behind it - the report's tags have changed")
    return out


# point the engine at the v5 book
W4.RULE_VARIANT, W4.RULE_TAGS, W4.ENTRIES, W4.entries_true = RULE_VARIANT, {}, ENTRIES, entries_true

# The page: onh_v4_weekly.py's, with the words that name v4 changed.  (old text, new text, times it must be there)
PATCHES = [
    ("<title>ONH v4 Rolling Weeks</title>", "<title>ONH v5 Rolling Weeks</title>", 1),
    ("Over night Hold v4 &middot; the rule's own book", "Over night Hold v5 &middot; the final rule's own book", 1),
    ("Two-week rolling read of the ONH v4 rule", "Two-week rolling read of the ONH v5 rule", 1),
    ("height = how many of the 8 entries were true", "height = how many entries stood behind the trade", 1),
    ('aria-label="The 8 entries; press one to show it alone"', 'aria-label="The 10 entries; press one to show it alone"', 1),
    ("--c8:#e34948;", "--c8:#e34948; --c9:#0e8fa3; --c10:#8a5a2b;", 1),                       # two more entry colours
    ("--c8:#e66767;", "--c8:#e66767; --c9:#35b6c9; --c10:#c08a55;", 2),
    ("The trades are read from the ONH v4 report's own data at its panel defaults",
     "The trades are read from the ONH v5 report's own data (onh_v5_rule.html) at its panel defaults", 1),
    ("buy cost (the 15:20 premium &times; lot size)", "buy cost (the premium paid &times; lot size)", 1),
    ("the sum of the pair's buy costs (the 15:20 premium &times; lot size, one lot)",
     "the sum of the pair's buy costs (the premium paid &times; lot size, one lot)", 1),
    ("A night gets one dot for each of the rule's 8 entries that was true, stacked from 1 upward in entry order, so the "
     "top of the column is the count of entries true.",
     "A night gets one dot for each entry that stood behind the trade, stacked from 1 upward in entry order, so the top "
     "of the column is the count: on a night the day's side was bought, each of entries 1 to 7 and 10 that was true; on "
     "a night the opposite side was bought, entry 8 or entry 9 (both when both were true).", 1),
    (" Entry 7 is counted whenever its two parts are true, also on nights a scenario fired. Entry 8 is only checked when "
     "1 to 7 are all false, so it always stands alone.",
     " Entries 8 and 9 are used only when no day-side entry is true, so they never share a column with entries 1 to 7 "
     "and 10.", 1),
    ('<div class="row"><span class="k">Entries true</span><span class="n">${best.entries.length}</span></div>',
     '<div class="row"><span class="k">Entries behind the trade</span><span class="n">${best.entries.length}</span></div>\n'
     '      <div class="row"><span class="k">Side bought</span><span class="n">${best.side}</span></div>\n'
     '      <div class="row"><span class="k">Facts agreeing</span><span class="n">${best.conf}</span></div>', 1),
    ("const h = ['Night', 'Bought', 'Entries true', 'Count', 'pnl %', 'Buy cost'];",
     "const h = ['Night', 'Bought', 'Side bought', 'Confirmations', 'Entries behind the trade', 'Count', 'pnl %', 'Buy cost'];", 1),
    ("<td>${n.symbol}</td><td>${n.entries.map(e => e + ' ' + ENT[e].name).join(', ')}</td>",
     "<td>${n.symbol}</td><td>${n.side}</td><td>${n.conf}</td><td>${n.entries.join(', ')}</td>", 1),
]


def page() -> str:
    html = W4.PAGE
    for old, new, n in PATCHES:
        if html.count(old) != n:
            raise SystemExit(f"onh_v4_weekly.py's page has changed: expected {n} of {old[:70]!r}, found {html.count(old)}")
        html = html.replace(old, new)
    return html


def build(payload: dict) -> dict:
    meta = payload["meta"]
    series = []
    for inst in meta.get("instruments") or [None]:
        s = W4.series_for(inst, payload["trades"], payload["sessions"])
        by_day = {t["day"]: t for t in payload["trades"] if t.get("instrument") == inst and W4.is_rule_trade(t)}
        for n in s["nights"]:                       # what the v5 page adds to a night: the side bought, the confirmations
            t = by_day[n["day"]]
            n["side"] = f"{t['tags'][KIND_TAG]} ({t['option_type']})"
            n["conf"] = t["tags"][CONF_TAG]
        series.append(s)
    return {
        "title": meta.get("title", "Over night Hold v5"),
        "from": meta.get("from"), "to": meta.get("to"), "generated": meta.get("generated"),
        "rule": f"{RULE_VARIANT['moneyness']} strikes ITM, exit: from 09:20 sell when a candle's low is above paid + costs, else at 14:00; "
                "the v5 rule (redesigned 2026-10-06): at least 2 of the 4 facts agree with the day -> buy the day's side",
        "drop_best": W4.DROP_BEST, "drop_cheap": W4.DROP_CHEAP,
        "entries": [{"num": num, "name": name, "what": what} for num, name, what, _tag in ENTRIES],
        "series": series,
    }


def main() -> None:
    data = build(W4.read_payload(SRC))
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    os.makedirs(W4.CHART_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(page().replace("__DATA__", blob))
    for s in data["series"]:
        tr = f"{s['trimmed']:+.1f}%" if s["trimmed"] is not None else "n/a"
        print(f"{s['instrument'] or 'index'}: {s['trades']} rule trades on {s['days']} trading days "
              f"({s['rate']:.0f}% of days), {s['weeks']} weeks -> {len(s['points'])} two-week points; "
              f"mean pnl {s['mean']:+.1f}% a trade, without the best {W4.DROP_BEST}: {tr}; "
              f"buy cost Rs {s['cost_day']:,.0f} a trading day, without the {W4.DROP_CHEAP} cheapest: "
              f"Rs {s['cost_day_trim']:,.0f}")
        print("   entries behind the trades: " + "; ".join(
            f"{num}: {s['entry_stats'][num]['n']} nights" + (f", {s['entry_stats'][num]['win']:.0f}% won" if s['entry_stats'][num]['n'] else "")
            for num, *_ in ENTRIES))
    print(OUT)


if __name__ == "__main__":
    main()
