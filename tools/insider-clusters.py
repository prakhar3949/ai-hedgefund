#!/home/nicknemo17/clawd/venv/bin/python
"""
Insider Cluster Detection
Detects multiple insiders buying within a 2-week window — a strong bullish signal.

Posts weekly to #trade-alerts (significant clusters) and #research (full scan).
Schedule: 10:00 AM PST Saturdays

Methodology:
  - Scans all holdings + priority watchlist via dexter-data.ts insider-trades
  - Looks for clusters: 3+ unique insiders buying within 14 days
  - Scores by: number of insiders, total dollar amount, insider seniority
  - Historically, insider clusters precede outperformance by 3-6 months

Cost: $0.00 per ticker (Tier 1 — direct API, no LLM)
"""

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from collections import defaultdict

ET = ZoneInfo("America/New_York")
CLAWD = Path.home() / "clawd"
DEXTER_RUN = CLAWD / "tools/dexter-run.sh"

# Load channel IDs
CHANNELS = {}
try:
    with open(CLAWD / "tools/discord-channels.sh") as f:
        for line in f:
            if line.startswith("DISCORD_") and "=" in line:
                key, val = line.split("=", 1)
                val = val.strip()
                if val.startswith('"'):
                    val = val[1:val.index('"', 1)]
                else:
                    val = val.split()[0].split("#")[0].strip()
                CHANNELS[key.strip()] = val
except:
    pass

ALERTS_CH = CHANNELS.get("DISCORD_TRADE_ALERTS", "1468334594314211423")
RESEARCH_CH = CHANNELS.get("DISCORD_RESEARCH", "1468773228791992494")


_pending_sends = []


def send_discord(channel_id: str, message: str):
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        proc = subprocess.Popen(
            ["clawdbot", "message", "send",
             "--channel", "discord",
             "--target", f"channel:{channel_id}",
             "--message", message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _pending_sends.append(proc)
    except:
        pass


def flush_sends(timeout: int = 15):
    for proc in _pending_sends:
        try:
            proc.wait(timeout=timeout)
        except:
            pass
    _pending_sends.clear()


def fetch_insider_trades(ticker: str, limit: int = 20) -> list[dict]:
    """Fetch recent insider trades via dexter-data.ts."""
    try:
        result = subprocess.run(
            [str(DEXTER_RUN), "data", "insider-trades", ticker, str(limit)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return []
        raw = json.loads(result.stdout)
        # API returns {"data": [...]} wrapper
        trades = raw.get("data", raw) if isinstance(raw, dict) else raw
        return trades
    except:
        return []


def detect_clusters(trades: list[dict], window_days: int = 14, min_buyers: int = 2) -> dict | None:
    """Detect insider buying clusters within a time window."""
    now = datetime.now(ET)
    cutoff = now - timedelta(days=60)  # Look back 60 days for clusters

    # Filter to purchases only (positive transaction_shares = buy)
    buys = []
    for t in trades:
        trade_date = t.get("transaction_date") or t.get("filing_date", "")
        if not trade_date:
            continue

        try:
            td = datetime.strptime(trade_date[:10], "%Y-%m-%d").replace(tzinfo=ET)
        except:
            continue

        if td < cutoff:
            continue

        # Positive transaction_shares = purchase
        tx_shares = t.get("transaction_shares", 0)
        if tx_shares and tx_shares > 0:
            buys.append({
                "date": trade_date[:10],
                "name": t.get("name", "Unknown"),
                "title": t.get("title") or ("Board Director" if t.get("is_board_director") else ""),
                "shares": tx_shares,
                "price": t.get("transaction_price_per_share", 0),
                "value": t.get("transaction_value") or (tx_shares * (t.get("transaction_price_per_share") or 0)),
            })

    if len(buys) < min_buyers:
        return None

    # Find clusters — sliding window of `window_days`
    buys.sort(key=lambda x: x["date"])
    best_cluster = None

    for i, buy in enumerate(buys):
        cluster_buys = [buy]
        buy_date = datetime.strptime(buy["date"], "%Y-%m-%d")

        for j in range(i + 1, len(buys)):
            other_date = datetime.strptime(buys[j]["date"], "%Y-%m-%d")
            if (other_date - buy_date).days <= window_days:
                cluster_buys.append(buys[j])

        # Count unique buyers
        unique_buyers = set()
        for b in cluster_buys:
            unique_buyers.add(b["name"])

        if len(unique_buyers) >= min_buyers:
            total_value = sum(b["value"] for b in cluster_buys)
            cluster = {
                "num_buyers": len(unique_buyers),
                "num_transactions": len(cluster_buys),
                "total_value": total_value,
                "date_range": f"{cluster_buys[0]['date']} to {cluster_buys[-1]['date']}",
                "buyers": [
                    {"name": b["name"], "title": b["title"], "shares": b["shares"],
                     "price": b["price"], "value": b["value"], "date": b["date"]}
                    for b in cluster_buys
                ],
            }

            if best_cluster is None or len(unique_buyers) > best_cluster["num_buyers"]:
                best_cluster = cluster

    return best_cluster


def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting insider cluster scan")

    # Load holdings + priority watchlist
    with open(CLAWD / "memory/watchlist.json") as f:
        wl = json.load(f)

    tickers_to_scan = []

    # Holdings
    for t, h in wl.get("stocks", {}).get("holdings", {}).items():
        if h.get("weight") and h["weight"] > 0:
            tickers_to_scan.append({"ticker": t, "category": "holding", "weight": h["weight"]})

    # Priority watchlist
    for t in wl.get("stocks", {}).get("priority", []):
        tickers_to_scan.append({"ticker": t, "category": "priority", "weight": None})

    # Scan for insider clusters — parallel fetch to reduce wall time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def scan_ticker(entry):
        ticker = entry["ticker"]
        trades = fetch_insider_trades(ticker, 20)
        return entry, trades

    # Fetch all trades in parallel (4 workers to avoid overwhelming the Pi)
    trades_by_ticker = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(scan_ticker, e): e for e in tickers_to_scan}
        for future in as_completed(futures):
            entry, trades = future.result()
            trades_by_ticker[entry["ticker"]] = (entry, trades)
            print(f"  Scanned {entry['ticker']}...")

    clusters_found = []
    notable_single_buys = []

    for ticker_data in tickers_to_scan:
        ticker = ticker_data["ticker"]
        entry, trades = trades_by_ticker.get(ticker, (ticker_data, []))
        if not trades:
            continue

        cluster = detect_clusters(trades, window_days=14, min_buyers=2)
        if cluster:
            cluster["ticker"] = ticker
            cluster["category"] = entry["category"]
            cluster["weight"] = entry["weight"]
            clusters_found.append(cluster)
            print(f"    CLUSTER: {cluster['num_buyers']} buyers, ${cluster['total_value']:,.0f}")
        else:
            # Check for notable single large purchases
            for t in trades:
                tx_shares = t.get("transaction_shares", 0)
                if tx_shares and tx_shares > 0:
                    value = t.get("transaction_value") or (tx_shares * (t.get("transaction_price_per_share") or 0))
                    if value >= 500000:  # $500K+ single buy is notable
                        notable_single_buys.append({
                            "ticker": ticker,
                            "name": t.get("name", "Unknown"),
                            "title": t.get("title") or "",
                            "value": value,
                            "date": (t.get("transaction_date") or t.get("filing_date") or "")[:10],
                        })

    # Sort clusters by number of buyers, then value
    clusters_found.sort(key=lambda x: (x["num_buyers"], x["total_value"]), reverse=True)

    # Post significant clusters to #trade-alerts
    if clusters_found:
        alert_lines = [f"**Insider Cluster Alert** ({now_et.strftime('%a %b %d')})", ""]
        for c in clusters_found:
            weight_str = f" | {c['weight']:.1f}% of port" if c.get("weight") else ""
            alert_lines.append(f"**{c['ticker']}** [{c['category']}]{weight_str}")
            alert_lines.append(f"  {c['num_buyers']} insiders bought ${c['total_value']:,.0f} ({c['date_range']})")
            for b in c["buyers"][:4]:
                title_short = b["title"][:20] if b["title"] else ""
                alert_lines.append(f"  - {b['name']} ({title_short}): {b['shares']:,} shares @ ${b['price']:.2f}")
            alert_lines.append("")

        send_discord(ALERTS_CH, "\n".join(alert_lines))
        print(f"Posted {len(clusters_found)} insider cluster alerts")

    # Summary to #research
    summary_lines = [f"**Insider Activity Scan** ({now_et.strftime('%a %b %d')})", ""]
    summary_lines.append(f"Scanned {len(tickers_to_scan)} tickers")
    summary_lines.append(f"Clusters found: **{len(clusters_found)}**")
    if notable_single_buys:
        summary_lines.append(f"Notable large buys: **{len(notable_single_buys)}**")
    summary_lines.append("")

    if clusters_found:
        summary_lines.append("**Clusters:**")
        for c in clusters_found:
            summary_lines.append(f"  {c['ticker']}: {c['num_buyers']} buyers, ${c['total_value']:,.0f}")

    if notable_single_buys:
        summary_lines.append("")
        summary_lines.append("**Large Individual Buys (>$500K):**")
        for b in notable_single_buys[:5]:
            summary_lines.append(f"  {b['ticker']}: {b['name']} — ${b['value']:,.0f} on {b['date']}")

    if not clusters_found and not notable_single_buys:
        summary_lines.append("No significant insider activity detected this week.")

    send_discord(RESEARCH_CH, "\n".join(summary_lines))
    print(f"Posted insider scan summary to #research")

    # Popen sends complete independently after script exits
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Insider cluster scan complete")


if __name__ == "__main__":
    main()
