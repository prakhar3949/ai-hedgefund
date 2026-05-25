#!/bin/bash
# CRITICAL: Two-way alerts for SHORT positions

cd ~/clawd

# UPWARD moves = liquidation risk
BTC_ALERT_UP=0.5  # Alert if BTC moves up >0.5%
ETH_ALERT_UP=0.5  # Alert if ETH moves up >0.5%

# DOWNWARD moves = profit-taking opportunities
BTC_PROFIT_TARGET=76000  # Alert if BTC drops to $76k (take profits)
BTC_PROFIT_TARGET_2=75000  # Alert if BTC drops to $75k (take more profits)

while true; do
    PRICES=$(./venv/bin/python tools/crypto-monitor.py 2>/dev/null)
    
    # Parse prices
    BTC=$(echo "$PRICES" | jq -r '.prices.BTC')
    ETH=$(echo "$PRICES" | jq -r '.prices.ETH')
    SOL=$(echo "$PRICES" | jq -r '.prices.SOL // empty')
    
    BTC_CHANGE=$(echo "$PRICES" | jq -r '.changes_24h.BTC // 0')
    ETH_CHANGE=$(echo "$PRICES" | jq -r '.changes_24h.ETH // 0')
    
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Log current prices
    echo "$TIMESTAMP BTC=$BTC ETH=$ETH SOL=$SOL" >> memory/crypto-monitor.log
    
    # Check for UPWARD moves (liquidation risk for shorts)
    if (( $(echo "$BTC_CHANGE > -6" | bc -l) )); then
        echo "🚨 BTC BOUNCE at $BTC (change: $BTC_CHANGE%) - LIQUIDATION RISK" >> memory/alerts.log
    fi
    
    if (( $(echo "$ETH_CHANGE > -9" | bc -l) )); then
        echo "🚨 ETH BOUNCE at $ETH (change: $ETH_CHANGE%) - LIQUIDATION RISK" >> memory/alerts.log
    fi
    
    # Check for DOWNWARD moves (profit-taking opportunities)
    if (( $(echo "$BTC < 76500" | bc -l) )); then
        echo "💰 BTC at $BTC - APPROACHING PROFIT TARGET ($76k) - Consider taking profits" >> memory/alerts.log
    fi
    
    if (( $(echo "$BTC < 75500" | bc -l) )); then
        echo "💰💰 BTC at $BTC - STRONG PROFIT TARGET ($75k) - Take profits!" >> memory/alerts.log
    fi
    
    # Check every 30 seconds
    sleep 30
done
