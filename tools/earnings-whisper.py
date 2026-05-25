"""
Earnings Whisper Tracker
Stores consensus estimates at 30/14/7/3/1 days before earnings.
Detects estimate drift — a leading indicator of earnings surprises.

Posts to Discord via webhook when significant drift detected or when earnings are imminent.

Data flow:
  1. watchlist.json → ticker symbols (no dates — AV looks them up)
  2. Alpha Vantage EARNINGS_CALENDAR → full market earnings schedule + EPS estimates (1 API call)
  3. reference_data_enhanced.csv → portfolio tickers (highlighted in output)
  4. Cross-reference watchlist & portfolio tickers against AV calendar
  5. Snapshots EPS at 30d/14d/7d/3d/1d intervals, tracks drift over time

Cost: 1 Alpha Vantage API call per run (free tier: 500/day)
"""

import csv
import io
import json
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Use project directory as base
PROJECT_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

WHISPER_FILE = MEMORY_DIR / "earnings-whisper.json"
WATCHLIST_FILE = PROJECT_DIR / "tools" / "watchlist.json"
REFERENCE_CSV = PROJECT_DIR.parent.parent / "reference_data_enhanced.csv"

# Discord webhook URLs
DISCORD_WEBHOOK_EARNINGS = "https://discord.com/api/webhooks/1470313478052122634/ERcpnJvbOF9HwlXtu6-KlCJh-CNWxdVi480HGY8bv3S3ZpIGscJPUinF7cTCN5DKihfR"

ALPHAVANTAGE_API_KEY = "1SIVEVQAAYTRTLBV"


# ─── DATA LOADING ────────────────────────────────────────────────

def send_discord(message: str, webhook: str = None):
    """Send message to Discord via webhook."""
    url = webhook or DISCORD_WEBHOOK_EARNINGS
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        resp = requests.post(url, json={"content": message}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"Send failed: {e}")


def load_watchlist_tickers() -> set:
    """Load watchlist ticker symbols from watchlist.json."""
    try:
        with open(WATCHLIST_FILE) as f:
            data = json.load(f)
        tickers = set(data.get("tickers", []))
        print(f"  Watchlist: {len(tickers)} tickers from watchlist.json")
        return tickers
    except Exception as e:
        print(f"  Could not load watchlist: {e}")
        return set()


def load_portfolio_tickers() -> set:
    """Load portfolio tickers from reference_data_enhanced.csv."""
    tickers = set()
    try:
        with open(REFERENCE_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = row.get("Ticker", "").strip()
                if t and row.get("Status", "") == "SUCCESS":
                    tickers.add(t)
        print(f"  Portfolio: {len(tickers)} tickers from CSV")
    except Exception as e:
        print(f"  Could not load portfolio CSV: {e}")
    return tickers


def fetch_earnings_calendar() -> list[dict]:
    """Fetch upcoming earnings from Alpha Vantage EARNINGS_CALENDAR (single API call)."""
    url = (
        f"https://www.alphavantage.co/query"
        f"?function=EARNINGS_CALENDAR&horizon=3month&apikey={ALPHAVANTAGE_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"  AV calendar HTTP {resp.status_code}")
            return []

        # Detect rate-limit response (AV returns "Information" as CSV row)
        if resp.text.strip().endswith("I,n,f,o,r,m,a"):
            print("  AV calendar: daily API limit reached (25 req/day free tier)")
            return []

        reader = csv.DictReader(io.StringIO(resp.text))
        entries = []
        for row in reader:
            symbol = row.get("symbol", "").strip()
            report_date = row.get("reportDate", "").strip()
            if not symbol or not report_date:
                continue
            estimate_str = row.get("estimate", "").strip()
            estimate = None
            if estimate_str:
                try:
                    estimate = float(estimate_str)
                except ValueError:
                    pass

            timing_raw = row.get("timeOfTheDay", "").strip()
            if "pre" in timing_raw:
                timing = "BMO"
            elif "post" in timing_raw:
                timing = "AMC"
            else:
                timing = "?"

            entries.append({
                "ticker": symbol,
                "earnings_date": report_date,
                "timing": timing,
                "estimate_eps": estimate,
                "name": row.get("name", ""),
                "source": "alphavantage",
            })

        print(f"  AV calendar: {len(entries)} earnings loaded")
        return entries
    except Exception as e:
        print(f"  AV calendar error: {e}")
        return []


def load_whisper_data() -> dict:
    try:
        with open(WHISPER_FILE) as f:
            return json.load(f)
    except:
        return {"tickers": {}}


def save_whisper_data(data: dict):
    data["updated"] = datetime.now(ET).isoformat()
    with open(WHISPER_FILE, "w") as f:
        json.dump(data, f, indent=2)


def compute_drift(snapshots: list[dict]) -> dict | None:
    """Compute drift across snapshots."""
    if len(snapshots) < 2:
        return None

    first = snapshots[0]
    last = snapshots[-1]
    first_eps = first.get("eps")
    last_eps = last.get("eps")

    if first_eps is None or last_eps is None or first_eps == 0:
        return None

    eps_drift = last_eps - first_eps
    eps_drift_pct = (eps_drift / abs(first_eps)) * 100

    return {
        "eps_drift": round(eps_drift, 3),
        "eps_drift_pct": round(eps_drift_pct, 1),
        "direction": "UP" if eps_drift > 0 else "DOWN" if eps_drift < 0 else "FLAT",
        "first_date": first.get("snap_date", ""),
        "last_date": last.get("snap_date", ""),
        "snapshots_count": len(snapshots),
    }


# ─── POSTING HELPERS ─────────────────────────────────────────────

def _post_schedule(entries: list[dict], now_et: datetime, title: str):
    """Format and post an earnings schedule to Discord, splitting if needed."""
    by_date = {}
    for u in entries:
        by_date.setdefault(u["earnings_date"], []).append(u)

    lines = [f"{title} ({now_et.strftime('%a %b %d')})", ""]
    for date_str in sorted(by_date.keys()):
        date_entries = by_date[date_str]
        days = date_entries[0]["days_until"]
        day_label = "TODAY" if days == 0 else f"in {days}d"
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        lines.append(f"**{dt.strftime('%a %b %d')}** ({day_label})")

        for e in date_entries:
            timing = e.get("timing", "?")
            eps_str = f" | Est EPS: ${e['estimate_eps']:.2f}" if e.get("estimate_eps") is not None else ""
            note = e.get("category", "")
            note_str = f" — {note}" if note else ""
            lines.append(f"  {e['ticker']} ({timing}){eps_str}{note_str}")
        lines.append("")

    full = "\n".join(lines).strip()
    if len(full) <= 1950:
        send_discord(full)
    else:
        chunk = lines[0] + "\n"
        for date_str in sorted(by_date.keys()):
            date_entries = by_date[date_str]
            days = date_entries[0]["days_until"]
            day_label = "TODAY" if days == 0 else f"in {days}d"
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            block = f"\n**{dt.strftime('%a %b %d')}** ({day_label})\n"
            for e in date_entries:
                timing = e.get("timing", "?")
                eps_str = f" | Est EPS: ${e['estimate_eps']:.2f}" if e.get("estimate_eps") is not None else ""
                note = e.get("category", "")
                note_str = f" — {note}" if note else ""
                block += f"  {e['ticker']} ({timing}){eps_str}{note_str}\n"

            if len(chunk) + len(block) > 1900:
                send_discord(chunk.strip())
                time.sleep(0.5)
                chunk = "*(continued)*\n"
            chunk += block

        if chunk.strip():
            send_discord(chunk.strip())


# ─── MAIN ────────────────────────────────────────────────────────

def main():
    import sys
    now_et = datetime.now(ET)

    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        override = sys.argv[idx + 1]
        now_et = datetime.strptime(override, "%Y-%m-%d").replace(tzinfo=ET)
        print(f"[test mode] Overriding date to {override}")

    skip_fetch = "--no-fetch" in sys.argv
    today_str = now_et.strftime("%Y-%m-%d")
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting earnings whisper tracker")

    # ── 1. Load watchlist tickers (from watchlist.json) ──
    watchlist_tickers = load_watchlist_tickers()

    # ── 2. Load portfolio tickers (from CSV) ──
    portfolio_tickers = load_portfolio_tickers()

    # ── 3. Fetch Alpha Vantage earnings calendar (1 API call) ──
    av_calendar = []
    if not skip_fetch:
        av_calendar = fetch_earnings_calendar()
    else:
        print("  Skipping AV fetch (--no-fetch)")

    # ── 4. Cross-reference: watchlist tickers against AV calendar ──
    watchlist_entries = []
    for entry in av_calendar:
        if entry["ticker"] in watchlist_tickers:
            watchlist_entries.append(entry)

    # ── 5. Cross-reference: portfolio tickers against AV calendar ──
    portfolio_entries = []
    seen_portfolio = set()
    for entry in av_calendar:
        t = entry["ticker"]
        if t in portfolio_tickers and t not in seen_portfolio:
            entry["portfolio"] = True
            entry["category"] = entry.get("name", "")
            portfolio_entries.append(entry)
            seen_portfolio.add(t)

    # ── 6. Filter to next 30 days ──
    watchlist_upcoming = []
    for entry in watchlist_entries:
        try:
            earnings_date = datetime.strptime(entry["earnings_date"], "%Y-%m-%d")
        except:
            continue
        days_until = (earnings_date.date() - now_et.date()).days
        if 0 <= days_until <= 30:
            watchlist_upcoming.append({**entry, "days_until": days_until})
    watchlist_upcoming.sort(key=lambda x: x["days_until"])

    portfolio_upcoming = []
    for entry in portfolio_entries:
        try:
            earnings_date = datetime.strptime(entry["earnings_date"], "%Y-%m-%d")
        except:
            continue
        days_until = (earnings_date.date() - now_et.date()).days
        if 0 <= days_until <= 30:
            portfolio_upcoming.append({**entry, "days_until": days_until, "portfolio": True})
    portfolio_upcoming.sort(key=lambda x: x["days_until"])

    if not watchlist_upcoming and not portfolio_upcoming:
        print("No earnings in next 30 days")
        return

    print(f"Found {len(watchlist_upcoming)} watchlist + {len(portfolio_upcoming)} portfolio tickers with earnings in next 30 days")

    # ── 7a. Post WATCHLIST earnings schedule ──
    if watchlist_upcoming:
        _post_schedule(watchlist_upcoming, now_et, "**Upcoming Earnings — Watchlist**")
        print("Posted watchlist earnings schedule to Discord")

    # ── 7b. Post PORTFOLIO earnings schedule (separate notification) ──
    if portfolio_upcoming:
        _post_schedule(portfolio_upcoming, now_et, "**Upcoming Earnings — My Portfolio**")
        print("Posted portfolio earnings schedule to Discord")
    else:
        print("No portfolio earnings in next 30 days")

    # ── 8. Snapshot EPS estimates for drift tracking ──
    # Merge both lists, deduplicating by ticker
    all_upcoming = {e["ticker"]: e for e in watchlist_upcoming}
    for e in portfolio_upcoming:
        if e["ticker"] in all_upcoming:
            all_upcoming[e["ticker"]]["portfolio"] = True
        else:
            all_upcoming[e["ticker"]] = e

    whisper_data = load_whisper_data()
    snapshot_intervals = [30, 14, 7, 3, 1]

    reports = []
    imminent_reports = []

    for entry in all_upcoming.values():
        ticker = entry["ticker"]
        days_until = entry["days_until"]
        eps_estimate = entry.get("estimate_eps")

        if eps_estimate is None:
            continue

        should_snap = any(abs(days_until - interval) <= 1 for interval in snapshot_intervals)
        if ticker not in whisper_data["tickers"]:
            should_snap = True

        if not should_snap:
            continue

        if ticker not in whisper_data["tickers"]:
            whisper_data["tickers"][ticker] = {
                "earnings_date": entry["earnings_date"],
                "snapshots": [],
            }

        existing_dates = [s.get("snap_date") for s in whisper_data["tickers"][ticker]["snapshots"]]
        if today_str not in existing_dates:
            whisper_data["tickers"][ticker]["snapshots"].append({
                "eps": eps_estimate,
                "snap_date": today_str,
                "days_until": days_until,
            })

        drift = compute_drift(whisper_data["tickers"][ticker]["snapshots"])

        report = {
            "ticker": ticker,
            "days_until": days_until,
            "earnings_date": entry["earnings_date"],
            "timing": entry.get("timing", "?"),
            "category": entry.get("category", ""),
            "portfolio": entry.get("portfolio", False),
            "current_eps": eps_estimate,
            "drift": drift,
        }
        reports.append(report)
        if days_until <= 3:
            imminent_reports.append(report)

    save_whisper_data(whisper_data)

    # Clean up past earnings
    for ticker in list(whisper_data["tickers"].keys()):
        ed = whisper_data["tickers"][ticker].get("earnings_date", "")
        if ed and ed < today_str:
            del whisper_data["tickers"][ticker]
    save_whisper_data(whisper_data)

    # ── 9. Post imminent earnings with whisper data ──
    if imminent_reports:
        lines = [f"**Earnings Whisper** ({now_et.strftime('%a %b %d')})", ""]
        for r in imminent_reports:
            timing = r["timing"]
            tag = " [PORTFOLIO]" if r.get("portfolio") else ""

            lines.append(f"**{r['ticker']}** reports {r['earnings_date']} ({timing}) — {r['days_until']}d away{tag}")

            if r["current_eps"] is not None:
                lines.append(f"  Consensus EPS: ${r['current_eps']:.2f}")

            drift = r.get("drift")
            if drift:
                arrow = ">>>" if drift["direction"] == "UP" else "<<<" if drift["direction"] == "DOWN" else "---"
                lines.append(
                    f"  {arrow} EPS Drift: {drift['eps_drift_pct']:+.1f}% since {drift['first_date']} "
                    f"(${drift['eps_drift']:+.3f})"
                )
                if abs(drift["eps_drift_pct"]) >= 3:
                    if drift["direction"] == "UP":
                        lines.append("  Strong upward revision — historically bullish")
                    else:
                        lines.append("  Downward revision — expectations declining")
            lines.append("")

        send_discord("\n".join(lines))
        print(f"Posted {len(imminent_reports)} imminent earnings whispers")

    # ── 10. Drift summary table ──
    drifts_with_data = [r for r in reports if r.get("drift")]
    if drifts_with_data:
        summary_lines = [f"**Estimate Drift Summary** ({now_et.strftime('%a %b %d')})", ""]
        summary_lines.append("```")
        summary_lines.append(f"{'Ticker':<7} {'Days':>4} {'EPS':>7} {'Drift':>7} {'Src':<5}")
        summary_lines.append("-" * 33)

        for r in sorted(drifts_with_data, key=lambda x: x["days_until"]):
            d = r["drift"]
            eps_str = f"${r['current_eps']:.2f}" if r["current_eps"] else "N/A"
            drift_str = f"{d['eps_drift_pct']:+.1f}%"
            src = "PORT" if r.get("portfolio") else "WATCH"
            summary_lines.append(
                f"{r['ticker']:<7} {r['days_until']:>4} {eps_str:>7} {drift_str:>7} {src:<5}"
            )

        summary_lines.append("```")
        send_discord("\n".join(summary_lines))
        print("Posted drift summary")

    print(f"\nDone. {len(reports)} tickers tracked, {len(watchlist_upcoming)} watchlist + {len(portfolio_upcoming)} portfolio upcoming")


if __name__ == "__main__":
    main()
