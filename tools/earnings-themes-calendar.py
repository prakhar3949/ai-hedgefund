"""
Earnings Themes Calendar — high-level seasonal view of US earnings season.

Rather than listing every stock's report date, this groups the calendar into
~13 curated themes in the conventional order they hit the tape each season:

  🏦 Big Banks (kick off) → 🏛️ Regional Banks → 📺 Streaming → 🏭 Industrials →
  🛡️ Defense → 💉 Healthcare → 🛒 Staples → 💻 Mega-Cap Tech → ⚡ Semis →
  ⚙️ Software → 🛍️ Retail (closes season) → ⛽ Energy → 🔬 NVDA (always last).

For each theme we use 4-6 representative bellwether tickers, look up their next
earnings dates from Alpha Vantage's EARNINGS_CALENDAR, and report the date
window (earliest → latest) plus the actual reporters.

Output: Discord post with the curated-order calendar.
"""

import csv
import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import requests
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from collections import defaultdict

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1504817802307964969/"
    "Am950RZWRjFb3YlIS30CVDHyJLMGfiy_-SCgYyJ-i6R5GdAlnwGAkAM0Hfn7Vzbcgx8e"
)
ALPHAVANTAGE_API_KEY = "1SIVEVQAAYTRTLBV"

# Curated theme order — represents the conventional earnings-season cadence.
# Each theme has 4-6 bellwether tickers whose dates anchor the theme window.
THEMES = [
    ("🏦 Big Banks",          ["JPM", "BAC", "WFC", "C", "GS", "MS"]),
    ("🏛️ Regional Banks",     ["USB", "PNC", "TFC", "RF", "FITB", "MTB"]),
    ("🚛 Trucking/Marine Shipping", ["JBHT", "ODFL", "KNX", "XPO", "LSTR",
                                       "FDX", "UPS",
                                       "MATX", "KEX", "ZIM"]),
    ("💳 Credit/Payments",    ["V", "MA", "AXP", "PYPL", "COF", "DFS"]),
    ("📺 Streaming/Media",    ["NFLX", "DIS", "WBD", "CMCSA"]),
    ("🏭 Industrials/Rails",  ["UNP", "CSX", "NSC", "HON", "GE", "CAT", "MMM", "EMR", "ETN"]),
    ("🛡️ Defense",            ["LMT", "NOC", "RTX", "GD", "LHX"]),
    ("💉 Healthcare",         ["JNJ", "PFE", "MRK", "ABBV", "UNH", "LLY"]),
    ("🛒 Consumer Staples",   ["PG", "KO", "PEP", "CL", "KMB", "MO"]),
    ("💻 Mega-Cap Tech",      ["AAPL", "MSFT", "GOOG", "GOOGL", "AMZN", "META", "TSLA"]),
    ("⚡ Semiconductors",     ["AVGO", "AMD", "INTC", "QCOM", "TXN", "MU", "AMAT"]),
    ("⚙️ Software/SaaS",      ["CRM", "ORCL", "NOW", "ADBE", "WDAY"]),
    ("🛍️ Retail",             ["WMT", "TGT", "HD", "LOW", "COST", "BBY", "TJX"]),
    ("⛽ Energy",             ["XOM", "CVX", "COP", "SLB", "EOG", "PSX"]),
    ("🔬 NVDA (closes the season)", ["NVDA"]),
]


def send_discord(text: str):
    chunks = []
    cur = ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 1900:
            chunks.append(cur); cur = line
        else:
            cur = cur + "\n" + line if cur else line
    if cur: chunks.append(cur)
    for ch in chunks:
        try:
            r = requests.post(DISCORD_WEBHOOK_URL, json={"content": ch}, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"  Discord failed: {e}")


def fetch_earnings_calendar() -> dict[str, list[dict]]:
    """Fetch 3-month AV earnings calendar and index by symbol."""
    url = (f"https://www.alphavantage.co/query"
           f"?function=EARNINGS_CALENDAR&horizon=3month&apikey={ALPHAVANTAGE_API_KEY}")
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        print(f"  AV HTTP {resp.status_code}", file=sys.stderr)
        return {}
    if resp.text.strip().endswith("I,n,f,o,r,m,a"):
        print("  AV daily limit reached", file=sys.stderr)
        return {}
    reader = csv.DictReader(io.StringIO(resp.text))
    out: dict[str, list[dict]] = defaultdict(list)
    for row in reader:
        symbol = row.get("symbol", "").strip()
        date = row.get("reportDate", "").strip()
        if not symbol or not date: continue
        timing_raw = row.get("timeOfTheDay", "").strip().lower()
        timing = "BMO" if "pre" in timing_raw else "AMC" if "post" in timing_raw else ""
        out[symbol].append({
            "date": date, "timing": timing,
            "name": row.get("name", "").strip(),
        })
    return out


def week_of(date_str: str) -> str:
    """Return 'Week of Mon DD' label."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    monday = d - timedelta(days=d.weekday())
    return monday.strftime("Week of %b %d")


def main():
    now = datetime.now(ET)
    print(f"{now.strftime('%Y-%m-%d %H:%M')} earnings-themes-calendar starting")

    cal = fetch_earnings_calendar()
    if not cal:
        send_discord("⚠️ Earnings Themes Calendar: AV data unavailable today.")
        return

    # Resolve each theme's upcoming dates — always list every bellwether,
    # marking those without a date in AV's 3-month horizon as "(next quarter)".
    theme_rows = []
    for theme_name, tickers in THEMES:
        reports = []   # has a date
        no_date = []   # bellwether with no upcoming date
        for t in tickers:
            entries = cal.get(t, [])
            entries_sorted = sorted(entries, key=lambda e: e["date"])
            if entries_sorted:
                reports.append({"ticker": t, **entries_sorted[0]})
            else:
                no_date.append(t)
        reports.sort(key=lambda r: r["date"])
        theme_rows.append({
            "theme": theme_name,
            "reports": reports,
            "no_date": no_date,
            "first": reports[0]["date"] if reports else None,
            "last": reports[-1]["date"] if reports else None,
        })

    # Compose output
    lines = []
    lines.append("══════════════════════════════════════════")
    lines.append(f"EARNINGS THEMES CALENDAR — generated {now.strftime('%Y-%m-%d')}")
    lines.append("══════════════════════════════════════════")
    lines.append("")
    lines.append("Curated order of how US earnings season historically unfolds.")
    lines.append("Dates are the actual upcoming reports for each theme's bellwethers.")
    lines.append("")

    # High-level summary first
    season_first = min((r["first"] for r in theme_rows if r["first"]), default=None)
    season_last = max((r["last"] for r in theme_rows if r["last"]), default=None)
    if season_first and season_last:
        lines.append(f"📅 SEASON WINDOW: {season_first} → {season_last}")
        lines.append("")

    # Theme-by-theme breakdown (curated order preserved)
    for row in theme_rows:
        lines.append(f"── {row['theme']} ──")
        # Date window
        if row["first"] and row["last"]:
            if row["first"] == row["last"]:
                lines.append(f"   📅 {row['first']}")
            else:
                lines.append(f"   📅 {row['first']} → {row['last']}")
        else:
            lines.append("   📅 (no reports in next 3 months)")
        # List reporters with upcoming dates
        for r in row["reports"]:
            timing = f" [{r['timing']}]" if r['timing'] else ""
            lines.append(f"     • {r['date']}{timing}  {r['ticker']}")
        # List bellwethers with no upcoming date (so the theme always shows
        # every name we track, even when their next report is > 3 months out)
        if row["no_date"]:
            lines.append(f"     • (next quarter)  {', '.join(row['no_date'])}")
        lines.append("")

    # Week-of view for the next 4 weeks
    lines.append("──────────────────────────────────────────")
    lines.append("WEEKLY ROLLUP (next 4 weeks):")
    lines.append("──────────────────────────────────────────")
    week_buckets: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    cutoff = (now + timedelta(days=28)).strftime("%Y-%m-%d")
    for row in theme_rows:
        for r in row["reports"]:
            if r["date"] <= cutoff:
                week_buckets[week_of(r["date"])].append((r["date"], r["ticker"], row["theme"]))
    for wk in sorted(week_buckets.keys(), key=lambda w: datetime.strptime(w.replace("Week of ", "") + " " + str(now.year), "%b %d %Y")):
        lines.append(f"\n{wk}:")
        items = sorted(week_buckets[wk])
        # group by theme within the week
        by_theme = defaultdict(list)
        for date, ticker, theme in items:
            by_theme[theme].append((date, ticker))
        for theme, theme_items in by_theme.items():
            tickers_str = ", ".join(f"{t} ({d[5:]})" for d, t in theme_items)
            lines.append(f"  {theme}  →  {tickers_str}")

    text = "\n".join(lines)
    print("\n" + text + "\n")
    send_discord("```\n" + text + "\n```")
    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M')} earnings-themes-calendar complete")


if __name__ == "__main__":
    main()
