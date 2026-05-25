#!/usr/bin/env python3
"""
Compare yfinance vs OpenBB for crypto data quality
"""

import json
import sys
import time
from datetime import datetime

def test_yfinance():
    """Test yfinance crypto data"""
    import yfinance as yf
    
    cryptos = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"]
    results = {
        "library": "yfinance",
        "timestamp": datetime.now().isoformat(),
        "data": []
    }
    
    start_time = time.time()
    
    for ticker in cryptos:
        try:
            tick = yf.Ticker(ticker)
            info = tick.info
            hist = tick.history(period="1d", interval="1m")
            
            # Get available metrics
            data_point = {
                "symbol": ticker,
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "change": info.get("regularMarketChange"),
                "changePercent": info.get("regularMarketChangePercent"),
                "volume": info.get("regularMarketVolume") or info.get("volume24Hr"),
                "volume_24h": info.get("volume24Hr"),
                "high_24h": info.get("dayHigh") or info.get("regularMarketDayHigh"),
                "low_24h": info.get("dayLow") or info.get("regularMarketDayLow"),
                "market_cap": info.get("marketCap"),
                "circulating_supply": info.get("circulatingSupply"),
                "last_updated": info.get("regularMarketTime"),
                "available_fields": len([k for k, v in info.items() if v is not None]),
                "history_points": len(hist) if not hist.empty else 0
            }
            
            results["data"].append(data_point)
        except Exception as e:
            results["data"].append({"symbol": ticker, "error": str(e)})
    
    results["fetch_time_seconds"] = round(time.time() - start_time, 2)
    return results

def test_openbb():
    """Test OpenBB crypto data"""
    try:
        from openbb import obb
        
        cryptos = ["BTC", "ETH", "SOL", "XRP"]
        results = {
            "library": "openbb",
            "timestamp": datetime.now().isoformat(),
            "data": []
        }
        
        start_time = time.time()
        
        for symbol in cryptos:
            try:
                # Try crypto.price.historical
                quote_data = obb.crypto.price.historical(
                    symbol=f"{symbol}USD",
                    provider="yfinance",
                    interval="1d",
                    period="1d"
                )
                
                if quote_data and hasattr(quote_data, 'results') and quote_data.results:
                    latest = quote_data.results[-1]
                    
                    # Calculate 24h change
                    if len(quote_data.results) >= 2:
                        prev = quote_data.results[-2]
                        change = latest.close - prev.close
                        change_pct = (change / prev.close) * 100
                    else:
                        change = latest.close - latest.open
                        change_pct = (change / latest.open) * 100
                    
                    data_point = {
                        "symbol": f"{symbol}-USD",
                        "price": latest.close,
                        "open": latest.open,
                        "high_24h": latest.high,
                        "low_24h": latest.low,
                        "volume": latest.volume,
                        "change": change,
                        "changePercent": change_pct,
                        "timestamp": str(latest.date) if hasattr(latest, 'date') else None,
                        "data_points": len(quote_data.results)
                    }
                    
                    results["data"].append(data_point)
                else:
                    results["data"].append({"symbol": f"{symbol}-USD", "error": "No data returned"})
                    
            except Exception as e:
                results["data"].append({"symbol": f"{symbol}-USD", "error": str(e)})
        
        results["fetch_time_seconds"] = round(time.time() - start_time, 2)
        return results
        
    except ImportError as e:
        return {"library": "openbb", "error": f"Import failed: {e}"}

def main():
    print("=" * 70)
    print("CRYPTO DATA COMPARISON: yfinance vs OpenBB")
    print("=" * 70)
    
    # Test yfinance
    print("\n[1/2] Testing yfinance...")
    yf_results = test_yfinance()
    
    # Test OpenBB
    print("[2/2] Testing OpenBB...")
    obb_results = test_openbb()
    
    # Output results
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    print("\n### YFINANCE ###")
    print(json.dumps(yf_results, indent=2))
    
    print("\n### OPENBB ###")
    print(json.dumps(obb_results, indent=2))
    
    # Summary comparison
    print("\n" + "=" * 70)
    print("SUMMARY COMPARISON")
    print("=" * 70)
    
    if "error" not in yf_results and "error" not in obb_results:
        print(f"\nFetch Speed:")
        print(f"  yfinance: {yf_results.get('fetch_time_seconds', 'N/A')}s")
        print(f"  OpenBB:   {obb_results.get('fetch_time_seconds', 'N/A')}s")
        
        print(f"\nData Completeness (BTC example):")
        yf_btc = next((d for d in yf_results['data'] if d.get('symbol') == 'BTC-USD'), {})
        obb_btc = next((d for d in obb_results['data'] if d.get('symbol') == 'BTC-USD'), {})
        
        print(f"  yfinance fields: {yf_btc.get('available_fields', 'N/A')}")
        print(f"  yfinance price: ${yf_btc.get('price', 'N/A')}")
        print(f"  yfinance change%: {yf_btc.get('changePercent', 'N/A')}")
        
        print(f"  OpenBB price: ${obb_btc.get('price', 'N/A')}")
        print(f"  OpenBB change%: {obb_btc.get('changePercent', 'N/A')}")

if __name__ == "__main__":
    main()
