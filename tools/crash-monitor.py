#!/usr/bin/env python3
"""
Crash Monitor - Real-time index monitoring with 1% alert threshold
Monitors: S&P futures, Nasdaq futures, Dow futures, BTC, ETH
Baseline: Daily baseline from memory/market-baseline-YYYY-MM-DD.json
"""

import sys
import json
from datetime import datetime
from pathlib import Path

# Check if yfinance is available
try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance", file=sys.stderr)
    sys.exit(1)

def load_baseline():
    """Load baseline from heartbeat state"""
    try:
        state_file = Path.home() / "clawd" / "memory" / "heartbeat-state.json"
        with open(state_file) as f:
            state = json.load(f)
        
        baseline_file = Path.home() / "clawd" / state["crashMode"]["baselineFile"]
        with open(baseline_file) as f:
            baseline_data = json.load(f)
        
        # Extract baseline percentages (0.0 for daily open)
        return {
            "sp500": baseline_data["baselines"]["ES=F"]["baseline_pct"],
            "nasdaq": baseline_data["baselines"]["NQ=F"]["baseline_pct"],
            "dow": baseline_data["baselines"]["YM=F"]["baseline_pct"],
            "russell": baseline_data["baselines"].get("RTY=F", {}).get("baseline_pct", 0.0),
        }
    except Exception as e:
        print(f"WARNING: Could not load baseline: {e}", file=sys.stderr)
        # Fallback to 0.0 (compare to today's open)
        return {"sp500": 0.0, "nasdaq": 0.0, "dow": 0.0, "russell": 0.0}

BASELINE = load_baseline()
ALERT_THRESHOLD = 1.0  # 1% move triggers alert

SYMBOLS = {
    "sp500": "ES=F",    # S&P 500 futures
    "nasdaq": "NQ=F",   # Nasdaq futures
    "dow": "YM=F",      # Dow futures
    "russell": "RTY=F", # Russell 2000 futures
    "btc": "BTC-USD",   # Bitcoin (24/7 leading indicator)
    "eth": "ETH-USD",   # Ethereum (24/7 leading indicator)
}

def get_current_prices():
    """Fetch current prices for all symbols"""
    results = {}
    
    for name, symbol in SYMBOLS.items():
        try:
            ticker = yf.Ticker(symbol)
            # Get most recent price
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
                prev_close = ticker.info.get('previousClose', ticker.info.get('regularMarketPreviousClose'))
                
                if prev_close:
                    change_pct = ((current_price - prev_close) / prev_close) * 100
                    results[name] = {
                        "symbol": symbol,
                        "price": current_price,
                        "change_pct": round(change_pct, 2),
                        "prev_close": prev_close
                    }
        except Exception as e:
            results[name] = {"error": str(e)}
    
    return results

def check_alerts(prices):
    """Check if any moves exceed alert threshold (DOWN only)"""
    alerts = []
    
    # Check indices against baseline - ONLY DOWN MOVES
    for index in ["sp500", "nasdaq", "dow", "russell"]:
        if index in prices and "change_pct" in prices[index]:
            baseline = BASELINE.get(index, 0)
            current = prices[index]["change_pct"]
            
            # Calculate move from baseline
            move_from_baseline = current - baseline
            
            # ONLY ALERT ON DOWN MOVES >= 1%
            if move_from_baseline <= -ALERT_THRESHOLD:
                alerts.append({
                    "asset": index.upper(),
                    "move": round(move_from_baseline, 2),
                    "direction": "DOWN",
                    "current": current,
                    "baseline": baseline,
                    "urgent": True
                })
    
    # Check crypto (no baseline, just flag large DOWN moves)
    for crypto in ["btc", "eth"]:
        if crypto in prices and "change_pct" in prices[crypto]:
            change = prices[crypto]["change_pct"]
            if change <= -5.0:  # 5% down threshold for crypto
                alerts.append({
                    "asset": crypto.upper(),
                    "move": change,
                    "direction": "DOWN",
                    "urgent": False
                })
    
    return alerts

def main():
    print(f"🔍 Crash Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S PST')}")
    print(f"Alert threshold: {ALERT_THRESHOLD}% from baseline\n")
    
    # Get current prices
    prices = get_current_prices()
    
    # Display current status
    print("Current Status:")
    print("-" * 60)
    for name, data in prices.items():
        if "error" in data:
            print(f"{name.upper():10} - Error: {data['error']}")
        else:
            symbol = data['symbol']
            price = data['price']
            change = data['change_pct']
            baseline = BASELINE.get(name, 0)
            
            if name in BASELINE:
                move_from_baseline = change - baseline
                print(f"{name.upper():10} {symbol:8} - ${price:.2f} ({change:+.2f}% today, {move_from_baseline:+.2f}% from baseline)")
            else:
                print(f"{name.upper():10} {symbol:8} - ${price:.2f} ({change:+.2f}% today)")
    
    print("-" * 60)
    
    # Check for alerts
    alerts = check_alerts(prices)
    
    if alerts:
        print("\n🚨 ALERTS:")
        for alert in alerts:
            if alert.get("urgent"):
                print(f"⚠️  {alert['asset']} moved {alert['move']:+.2f}% from baseline!")
                print(f"   Current: {alert['current']:.2f}% | Baseline: {alert['baseline']:.2f}%")
            else:
                print(f"💡 {alert['asset']} moved {alert['move']:+.2f}% today")
        
        # Return exit code 1 to signal alerts
        return 1
    else:
        print("\n✅ No alerts - all within threshold")
        return 0

if __name__ == "__main__":
    sys.exit(main())
