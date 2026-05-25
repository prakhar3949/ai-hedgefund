#!/usr/bin/env python3

import json
import sys
from pathlib import Path
import yfinance as yf

WATCHLIST_PATH = Path.home() / "clawd/memory/watchlist.json"

def load_watchlist():
    with open(WATCHLIST_PATH) as f:
        data = json.load(f)
    
    # Get all unique tickers with category
    tickers = {}
    for ticker in data["stocks"].get("holdings", {}).keys():
        tickers[ticker] = "holding"
    for ticker in data["stocks"].get("priority", []):
        if ticker not in tickers:
            tickers[ticker] = "priority"
    
    return tickers, data

def get_quotes(tickers_list):
    """Get quotes for multiple tickers"""
    try:
        data = yf.download(tickers_list, period="1d", interval="1d", progress=False)
        results = []
        
        for ticker in tickers_list:
            try:
                tick = yf.Ticker(ticker)
                info = tick.info
                
                result = {
                    "symbol": ticker,
                    "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                    "change": info.get("regularMarketChange"),
                    "changePercent": info.get("regularMarketChangePercent"),
                    "volume": info.get("regularMarketVolume"),
                    "high": info.get("dayHigh") or info.get("regularMarketDayHigh"),
                    "low": info.get("dayLow") or info.get("regularMarketDayLow")
                }
                results.append(result)
            except Exception as e:
                results.append({"symbol": ticker, "error": str(e)})
        
        return results
    except Exception as e:
        return [{"error": f"Batch fetch failed: {e}"}]

def main():
    tickers_dict, watchlist = load_watchlist()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--holdings":
        # Only check holdings
        tickers_dict = {k: v for k, v in tickers_dict.items() if v == "holding"}
    
    tickers_list = list(tickers_dict.keys())
    quotes = get_quotes(tickers_list)
    
    # Add category to each quote
    for quote in quotes:
        if "symbol" in quote:
            quote["category"] = tickers_dict.get(quote["symbol"], "unknown")
    
    print(json.dumps(quotes, indent=2))

if __name__ == "__main__":
    main()
