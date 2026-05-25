#!/bin/bash
# Continuous liquidation monitoring
cd ~/clawd

while true; do
    # Get current prices
    PRICES=$(./venv/bin/python tools/crypto-monitor.py 2>/dev/null)
    
    # Log with timestamp
    echo "$(date '+%Y-%m-%d %H:%M:%S') $PRICES" >> memory/crypto-monitor.log
    
    # Alert logic will be added once we have liquidation levels
    
    # Check every 30 seconds
    sleep 30
done
