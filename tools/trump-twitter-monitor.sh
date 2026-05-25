#!/bin/bash
# Monitor Trump's Twitter for market pump tweets

TWEETS=$(~/clawd/tools/twitter-monitor.sh search "from:realDonaldTrump" -n 3 2>&1)

# Check for market-positive keywords
if echo "$TWEETS" | grep -iE "(market|stocks|economy|winning|great|record|dow|nasdaq|s&p|bull|surge|soaring)" > /dev/null; then
  echo "🚨 TRUMP MARKET PUMP DETECTED 🚨"
  echo "$TWEETS"
  exit 1  # Non-zero exit signals alert needed
else
  echo "No market pump tweets detected"
  exit 0
fi
