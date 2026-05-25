#!/usr/bin/env python3

import json
import sys
from pathlib import Path
from openbb import obb

WATCHLIST_PATH = Path.home() / "clawd/memory/watchlist.json"
STATE_PATH = Path.home() / "clawd/memory/stock-state.json"

def load_watchlist():
    with open(WATCHLIST_PATH) as f:
        data = json.load(f)
    
    # Get all unique tickers with priority flag
    tickers = {}
    for ticker in data["stocks"].get("holdings", {}).keys():
        tickers[ticker] = "holding"
    for ticker in data["stocks"].get("priority", []):
        if ticker not in tickers:
            tickers[ticker] = "priority"
    for ticker in data["stocks"].get("aiInfrastructure", []):
        if ticker not in tickers:
            tickers[ticker] = "watchlist"
    for ticker in data["stocks"].get("megacapTech", []):
        if ticker not in tickers:
            tickers[ticker] = "watchlist"
    
    return tickers, data

def get_quote(ticker):
    """Get current quote data for a ticker"""
    try:
        result = obb.equity.price.quote(ticker, provider="yfinance")
        if result and len(result.results) > 0:
            quote = result.results[0]
            return {
                "symbol": quote.symbol,
                "price": quote.last_price,
                "change": quote.change,
                "changePercent": quote.change_percent,
                "volume": quote.volume,
                "timestamp": str(quote.last_price_timestamp) if hasattr(quote, 'last_price_timestamp') else None
            }
    except Exception as e:
        return {"symbol": ticker, "error": str(e)}
    return {"symbol": ticker, "error": "No data"}

def main():
    tickers, watchlist = load_watchlist()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--holdings":
        # Only check holdings
        tickers = {k: v for k, v in tickers.items() if v == "holding"}
    
    results = []
    for ticker, category in tickers.items():
        print(f"Fetching {ticker}...", file=sys.stderr)
        quote = get_quote(ticker)
        quote["category"] = category
        results.append(quote)
    
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
