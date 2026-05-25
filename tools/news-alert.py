#!/home/nicknemo17/clawd/venv/bin/python
"""
Breaking News Alert — local replacement for Clawdbot Breaking News Scanner job.
Scans yfinance news for all holdings, filters high-impact items, posts to Discord.

Includes dedup: tracks seen news titles in seen-news.json to avoid repeat alerts.
Reads holdings from watchlist.json if available, falls back to hardcoded list.

Schedule: every 30 min, 6:00 AM - 5:00 PM ET weekdays
Cost: $0.00 (Tier 1 — yfinance only, no LLM)
"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

ET = ZoneInfo("America/New_York")
CLAWD = Path.home() / "clawd"
SEEN_FILE = CLAWD / "memory/seen-news.json"

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

RESEARCH_CH = CHANNELS.get("DISCORD_RESEARCH", "1468773228791992494")

# Fallback holdings
DEFAULT_HOLDINGS = [
    "COHR", "KSPI", "XNET", "JFIN", "JAKK", "RAIL", "QXO", "GENC",
    "OSCR", "KLAC", "ASX", "WBTN", "CMI", "TDOC", "NNDM", "EDIT", "AMD",
    "LITE", "PURR", "FJET",
]

BULLISH_KW = [
    "upgrade", "buy", "outperform", "beat", "exceeds", "raises", "higher",
    "growth", "record", "surge", "soar", "rally", "breakout", "bullish",
    "strong", "positive", "accelerat", "expand", "win", "award", "contract",
    "partnership", "acquisition", "dividend", "buyback", "guidance raise",
    "price target", "ai", "demand",
]

BEARISH_KW = [
    "downgrade", "sell", "underperform", "miss", "below", "cuts", "lower",
    "decline", "drop", "fall", "plunge", "crash", "bearish", "weak",
    "negative", "slow", "layoff", "lawsuit", "investigation", "recall",
    "guidance cut", "warning", "concern", "risk", "debt", "loss", "disappointing",
]

IMPACT_KW = [
    "earnings", "guidance", "acquisition", "merger", "fda", "approval",
    "contract", "billion", "million deal", "ceo", "sec", "investigation",
    "breakthrough", "patent", "lawsuit", "recall", "bankruptcy",
    "q1", "q2", "q3", "q4", "revenue", "profit", "outlook",
]

SKIP_PATTERNS = [
    "what to look for", "what to expect", "earnings preview", "ahead of earnings",
    "before earnings", "earnings snapshot", "will report", "set to report",
    "due to release", "due after",
]

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


def load_holdings() -> list[str]:
    """Load holdings from watchlist.json or current-theses.json, fallback to defaults."""
    for fname in ["watchlist.json", "current-theses.json"]:
        try:
            with open(CLAWD / "memory" / fname) as f:
                data = json.load(f)
            if "theses" in data:
                tickers = [t for t in data["theses"]
                           if t not in ("MACRO", "_VERIFICATION_WARNING", "_MANDATORY_TOOLS")]
                if tickers:
                    return tickers
            elif "holdings" in data:
                return list(data["holdings"].keys())
        except:
            continue
    return DEFAULT_HOLDINGS


def load_seen() -> set:
    """Load previously seen news titles."""
    try:
        with open(SEEN_FILE) as f:
            data = json.load(f)
        # Prune entries older than 7 days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        return {t for t, ts in data.items() if ts > cutoff}
    except:
        return set()


def save_seen(seen: set):
    """Save seen news titles with timestamps."""
    now = datetime.now(timezone.utc).isoformat()
    # Load existing to preserve timestamps
    existing = {}
    try:
        with open(SEEN_FILE) as f:
            existing = json.load(f)
    except:
        pass
    for title in seen:
        if title not in existing:
            existing[title] = now
    # Prune old
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    existing = {t: ts for t, ts in existing.items() if ts > cutoff}
    with open(SEEN_FILE, "w") as f:
        json.dump(existing, f)


def analyze(title: str, summary: str) -> dict:
    """Keyword-based sentiment analysis."""
    text = (title + " " + summary).lower()

    bull = sum(1 for kw in BULLISH_KW if kw in text)
    bear = sum(1 for kw in BEARISH_KW if kw in text)
    impact = sum(1 for kw in IMPACT_KW if kw in text)

    if bull > bear:
        sentiment = "BULLISH"
    elif bear > bull:
        sentiment = "BEARISH"
    else:
        sentiment = "NEUTRAL"

    move = min(5, max(1, impact + abs(bull - bear)))
    high_impact = impact > 0

    return {"sentiment": sentiment, "move": move, "high_impact": high_impact}


def fetch_news(ticker: str) -> list[dict]:
    """Fetch recent news for a ticker from yfinance."""
    try:
        stock = yf.Ticker(ticker)
        news = stock.news or []
    except:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    results = []

    for item in news[:5]:
        content = item.get("content", item)
        title = content.get("title", "")
        summary = content.get("summary", content.get("description", ""))

        pub_str = content.get("pubDate", content.get("displayTime", ""))
        try:
            if pub_str:
                pub_time = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            else:
                continue
        except:
            continue

        if pub_time < cutoff:
            continue

        # Skip speculation
        text_lower = (title + " " + summary).lower()
        if any(skip in text_lower for skip in SKIP_PATTERNS):
            continue

        analysis = analyze(title, summary)

        # Only keep high-impact or high move-potential
        if analysis["move"] < 3 and not analysis["high_impact"]:
            continue

        source = content.get("provider", {})
        source_name = source.get("displayName", "") if isinstance(source, dict) else ""

        results.append({
            "ticker": ticker,
            "title": title,
            "summary": summary[:200] + "..." if len(summary) > 200 else summary,
            "source": source_name,
            **analysis,
        })

    return results


def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} News scanner starting")

    holdings = load_holdings()
    seen = load_seen()

    # Parallel news fetch (4 workers to avoid rate limits)
    all_news = []

    def _fetch(t):
        return fetch_news(t)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch, t): t for t in holdings}
        for f in as_completed(futures):
            all_news.extend(f.result())

    # Dedup by title — skip already-seen
    new_items = []
    for item in all_news:
        if item["title"] not in seen:
            new_items.append(item)
            seen.add(item["title"])

    if not new_items:
        print("No new high-impact news")
        save_seen(seen)
        return

    # Sort by move potential
    new_items.sort(key=lambda x: x["move"], reverse=True)

    # Format and send
    lines = [f"**Breaking News** ({now_et.strftime('%I:%M %p ET')})"]
    lines.append("")

    for item in new_items[:5]:  # Max 5 items per run
        emoji = {"BULLISH": "+", "BEARISH": "-", "NEUTRAL": "~"}[item["sentiment"]]
        lines.append(f"[{emoji}] **[{item['ticker']}]** {item['sentiment']} (Move: {item['move']}/5)")
        lines.append(f"  {item['title']}")
        if item["summary"]:
            lines.append(f"  _{item['summary']}_")
        lines.append("")

    message = "\n".join(lines).strip()
    send_discord(RESEARCH_CH, message)
    save_seen(seen)

    print(f"Posted {len(new_items)} news items ({len(message)} chars)")


if __name__ == "__main__":
    main()
