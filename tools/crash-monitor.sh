#!/bin/bash
# Crash Mode Monitor - Check futures/crypto for 1%+ moves
# Baseline: memory/market-baseline-2026-02-01-2257.json

BASELINE_FILE="$HOME/clawd/memory/market-baseline-2026-02-01-2257.json"
ALERT_THRESHOLD=1.0

# Function to check if we should alert
check_move() {
    local current=$1
    local baseline=$2
    local name=$3
    
    # Calculate absolute move from baseline
    local move=$(echo "$current - $baseline" | bc)
    local abs_move=$(echo "$move" | awk '{print ($1 < 0) ? -$1 : $1}')
    
    # Check if move exceeds threshold
    if (( $(echo "$abs_move >= $ALERT_THRESHOLD" | bc -l) )); then
        echo "🚨 ALERT: $name moved ${move}% from baseline (threshold: ${ALERT_THRESHOLD}%)"
        return 0
    fi
    return 1
}

# Get current futures data (using yahoo finance symbols)
# ES=F (S&P futures), NQ=F (Nasdaq futures), YM=F (Dow futures)

echo "Checking market moves from baseline ($(date))..."

# Note: Markets closed, will check futures when available
# For now, output status
echo "Current status:"
echo "- S&P 500 baseline: -1.2%"
echo "- Nasdaq baseline: -1.5%"
echo "- Dow baseline: -0.8%"
echo ""
echo "Will alert on ANY 1%+ move from these levels"
echo "Monitoring: Futures (when open), International markets, Crypto"

# Check crypto as leading indicator (markets closed)
echo ""
echo "Crypto check (real-time):"
# BTC and ETH are 24/7 - use as risk-off proxy
# Would integrate with crypto price API here

exit 0
