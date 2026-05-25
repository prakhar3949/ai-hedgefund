#!/usr/bin/env python3
"""
News Scanner - Scans for breaking news on holdings
Returns JSON with news items, sentiment analysis, and move potential
"""

import yfinance as yf
import json
import sys
from datetime import datetime, timedelta, timezone

# Holdings from watchlist.json
HOLDINGS = [
    "COHR", "KSPI", "XNET", "JFIN", "JAKK", "RAIL", "QXO", "GENC",
    "OSCR", "KLAC", "ASX", "WBTN", "CMI", "TDOC", "NNDM", "EDIT", "AMD"
]

PRIORITY = ["LITE", "PURR", "FJET"]

# Keywords for sentiment analysis
BULLISH_KEYWORDS = [
    "upgrade", "buy", "outperform", "beat", "exceeds", "raises", "higher",
    "growth", "record", "surge", "soar", "rally", "breakout", "bullish",
    "strong", "positive", "accelerat", "expand", "win", "award", "contract",
    "partnership", "acquisition", "dividend", "buyback", "guidance raise",
    "price target", "ai", "demand"
]

BEARISH_KEYWORDS = [
    "downgrade", "sell", "underperform", "miss", "below", "cuts", "lower",
    "decline", "drop", "fall", "plunge", "crash", "bearish", "weak",
    "negative", "slow", "layoff", "lawsuit", "investigation", "recall",
    "guidance cut", "warning", "concern", "risk", "debt", "loss", "disappointing"
]

# Skip these - pre-earnings speculation, not actionable
SKIP_PATTERNS = [
    "what to look for", "what to expect", "earnings preview", "ahead of earnings",
    "before earnings", "earnings snapshot", "will report", "set to report",
    "due to release", "due after"
]

HIGH_IMPACT_KEYWORDS = [
    "earnings", "guidance", "acquisition", "merger", "fda", "approval",
    "contract", "billion", "million deal", "ceo", "sec", "investigation",
    "breakthrough", "patent", "lawsuit", "recall", "bankruptcy", "q1", "q2",
    "q3", "q4", "revenue", "profit", "outlook"
]

def analyze_sentiment(title, summary=""):
    """Analyze news sentiment and impact potential"""
    text = (title + " " + summary).lower()

    bullish_score = sum(1 for kw in BULLISH_KEYWORDS if kw in text)
    bearish_score = sum(1 for kw in BEARISH_KEYWORDS if kw in text)
    impact_score = sum(1 for kw in HIGH_IMPACT_KEYWORDS if kw in text)

    if bullish_score > bearish_score:
        sentiment = "BULLISH"
        strength = bullish_score
    elif bearish_score > bullish_score:
        sentiment = "BEARISH"
        strength = bearish_score
    else:
        sentiment = "NEUTRAL"
        strength = 0

    # Move potential: 1-5 scale
    move_potential = min(5, max(1, impact_score + abs(bullish_score - bearish_score)))

    return {
        "sentiment": sentiment,
        "strength": strength,
        "move_potential": move_potential,
        "high_impact": impact_score > 0
    }

def get_news(ticker):
    """Fetch recent news for a ticker"""
    try:
        stock = yf.Ticker(ticker)
        news = stock.news

        if not news:
            return []

        results = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        for item in news[:5]:
            # Handle nested content structure
            content = item.get('content', item)

            title = content.get('title', '')
            summary = content.get('summary', content.get('description', ''))

            # Parse publish date
            pub_str = content.get('pubDate', content.get('displayTime', ''))
            try:
                if pub_str:
                    pub_time = datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
                else:
                    continue
            except:
                continue

            # Skip old news (more than 24h)
            if pub_time < cutoff:
                continue

            # Get URL
            url_obj = content.get('canonicalUrl', content.get('clickThroughUrl', {}))
            link = url_obj.get('url', '') if isinstance(url_obj, dict) else ''

            # Get source
            provider = content.get('provider', {})
            source = provider.get('displayName', '') if isinstance(provider, dict) else ''

            analysis = analyze_sentiment(title, summary)

            # Skip pre-earnings speculation articles
            text_lower = (title + " " + summary).lower()
            if any(skip in text_lower for skip in SKIP_PATTERNS):
                continue

            results.append({
                "ticker": ticker,
                "title": title,
                "summary": summary[:200] + "..." if len(summary) > 200 else summary,
                "link": link,
                "published": pub_time.strftime("%Y-%m-%d %H:%M UTC"),
                "source": source,
                **analysis
            })

        return results
    except Exception as e:
        print(f"Error fetching {ticker}: {e}", file=sys.stderr)
        return []

def main():
    all_tickers = HOLDINGS + PRIORITY
    all_news = []

    for ticker in all_tickers:
        news = get_news(ticker)
        all_news.extend(news)

    # Sort by move potential (highest first), then by high_impact
    all_news.sort(key=lambda x: (x['move_potential'], x['high_impact']), reverse=True)

    # Remove duplicates by title
    seen_titles = set()
    unique_news = []
    for item in all_news:
        if item['title'] not in seen_titles:
            seen_titles.add(item['title'])
            unique_news.append(item)

    print(json.dumps(unique_news, indent=2))

if __name__ == "__main__":
    main()
