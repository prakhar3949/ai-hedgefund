#!/bin/bash
# Market Update - Posts to Discord #levels-technicals
# Runs hourly 8am-5pm EST

CLAWD_DIR="$HOME/clawd"
CHANNEL="1468334675041976422"

# Get market data
MARKET=$($CLAWD_DIR/tools/quick-lookup.sh market 2>/dev/null)
SECTORS=$($CLAWD_DIR/tools/quick-lookup.sh sectors 2>/dev/null)

# Format message
MSG="**Hourly Market Update** ($(TZ=America/New_York date '+%I:%M %p EST'))

$MARKET

$SECTORS"

# Post to Discord
clawdbot message send --channel discord --target "channel:$CHANNEL" --message "$MSG" 2>/dev/null
