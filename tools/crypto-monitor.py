#!/usr/bin/env python3

import json
import sys
import yfinance as yf

# Crypto tickers to monitor
CRYPTO_TICKERS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"]

# Alert thresholds (%)
THRESHOLDS = {
    "BTC-USD": 5.0,
    "ETH-USD": 5.0,
    "SOL-USD": 7.0,
    "XRP-USD": 7.0
}

def get_crypto_quotes(tickers_list):
    """Get quotes for multiple crypto tickers"""
    try:
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
                    "volume": info.get("regularMarketVolume") or info.get("volume24Hr"),
                    "high": info.get("dayHigh") or info.get("regularMarketDayHigh"),
                    "low": info.get("dayLow") or info.get("regularMarketDayLow"),
                    "threshold": THRESHOLDS.get(ticker, 5.0)
                }
                
                # Mark if alert threshold exceeded
                if result["changePercent"] is not None:
                    result["alert"] = abs(result["changePercent"]) > THRESHOLDS.get(ticker, 5.0)
                else:
                    result["alert"] = False
                
                results.append(result)
            except Exception as e:
                results.append({"symbol": ticker, "error": str(e)})
        
        return results
    except Exception as e:
        return [{"error": f"Batch fetch failed: {e}"}]

def main():
    # Check specific tickers if provided
    if len(sys.argv) > 1 and sys.argv[1] not in ["--help", "-h"]:
        tickers = sys.argv[1:]
    else:
        tickers = CRYPTO_TICKERS
    
    quotes = get_crypto_quotes(tickers)
    print(json.dumps(quotes, indent=2))

if __name__ == "__main__":
    main()
