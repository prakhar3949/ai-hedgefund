#!/bin/bash
# Smart Router - Routes queries to scripts or AI
# Returns response OR "NEEDS_AI" if AI is required
# Usage: smart-router.sh "user message"

CLAWD_DIR="$HOME/clawd"
VENV="$CLAWD_DIR/venv/bin/python"
LOOKUP="$CLAWD_DIR/tools/quick-lookup.sh"
FAQ="$CLAWD_DIR/tools/FAQ.md"

MSG="$1"
MSG_LOWER=$(echo "$MSG" | tr '[:upper:]' '[:lower:]')

# Extract ticker if present
TICKER=$(echo "$MSG" | grep -oE '\b[A-Z]{2,5}\b' | head -1)

# Pattern matching - handle without AI

# Greetings
if [[ "$MSG_LOWER" =~ ^(hi|hey|hello|yo|sup)$ ]]; then
    echo "Hey! Ask me about stocks, theses, or markets."
    echo "Quick: \`price AMD\`, \`thesis COHR\`, \`market\`"
    exit 0
fi

# Help
if [[ "$MSG_LOWER" =~ (help|commands|what can you do) ]]; then
    echo "**Quick Commands:**"
    echo "• \`price TICKER\` - current price"
    echo "• \`thesis TICKER\` - investment thesis"
    echo "• \`market\` - SPY/QQQ/IWM"
    echo "• \`sectors\` - best/worst"
    echo "• \`holdings\` - all positions"
    exit 0
fi

# Price queries
if [[ "$MSG_LOWER" =~ ^price ]] || [[ "$MSG_LOWER" =~ (what.*(price|trading)|how.*much|current price) ]]; then
    if [ -n "$TICKER" ]; then
        $LOOKUP price "$TICKER"
        exit 0
    fi
fi

# Info / market cap queries
if [[ "$MSG_LOWER" =~ ^info ]] || [[ "$MSG_LOWER" =~ (market cap|mcap|valuation|pe ratio|beta|52.week|full info) ]]; then
    if [ -n "$TICKER" ]; then
        $LOOKUP info "$TICKER"
        exit 0
    fi
fi

# Thesis queries
if [[ "$MSG_LOWER" =~ ^thesis ]] || [[ "$MSG_LOWER" =~ (what.*thesis|why.*(own|hold|buy)|tell.*about) ]]; then
    if [ -n "$TICKER" ]; then
        $LOOKUP thesis "$TICKER"
        exit 0
    fi
fi

# Market snapshot
if [[ "$MSG_LOWER" =~ ^market$ ]] || [[ "$MSG_LOWER" =~ (market snapshot|how.*market|indexes) ]]; then
    $LOOKUP market
    exit 0
fi

# Sectors
if [[ "$MSG_LOWER" =~ ^sectors?$ ]] || [[ "$MSG_LOWER" =~ (sector.*perform|best.*sector|worst.*sector) ]]; then
    $LOOKUP sectors
    exit 0
fi

# Holdings
if [[ "$MSG_LOWER" =~ ^holdings?$ ]] || [[ "$MSG_LOWER" =~ (all positions|portfolio|what.*own) ]]; then
    $LOOKUP holdings
    exit 0
fi

# PT / Price target
if [[ "$MSG_LOWER" =~ (price target|pt|target) ]] && [ -n "$TICKER" ]; then
    grep -i "^### Q:.*$TICKER" -A1 "$FAQ" 2>/dev/null | grep "PT:" || echo "No PT found for $TICKER"
    exit 0
fi

# FAQ search
if [[ "$MSG_LOWER" =~ (faq|question about) ]]; then
    QUERY=$(echo "$MSG_LOWER" | sed 's/faq//g' | sed 's/question about//g' | xargs)
    grep -i "$QUERY" "$FAQ" | head -5
    exit 0
fi

# Simple yes/no questions about holdings
if [[ "$MSG_LOWER" =~ (do we own|is.*holding|position in) ]] && [ -n "$TICKER" ]; then
    if grep -q "\"$TICKER\"" "$CLAWD_DIR/memory/current-theses.json"; then
        echo "Yes, $TICKER is in the portfolio."
        $LOOKUP thesis "$TICKER"
    else
        echo "No, $TICKER is not a current holding."
    fi
    exit 0
fi

# Channel IDs
if [[ "$MSG_LOWER" =~ (channel id|discord channel) ]]; then
    echo "**Discord Channels:**"
    echo "• levels-technicals: 1468334675041976422"
    echo "• trade-alerts: 1468334594314211423"
    echo "• marketbot: 1468773228791992494"
    exit 0
fi

# If we get here, needs AI
echo "NEEDS_AI"
