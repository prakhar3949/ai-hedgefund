#!/bin/bash
# Post-Earnings Deep Analysis
# Triggered by edgar-monitor.py after filing detection.
# Uses Dexter for deep fundamental analysis, posts to #sec-filings and #research.
#
# Usage: earnings-deep-analysis.sh TICKER "EPS:1.29,REV:1.69B,EST_EPS:1.21,EST_REV:1.64B" [CATEGORY]

set -euo pipefail

TICKER="${1:-}"
EARNINGS_DATA="${2:-}"
CATEGORY="${3:-watchlist}"

if [ -z "$TICKER" ]; then
    echo "Usage: earnings-deep-analysis.sh TICKER EARNINGS_DATA [CATEGORY]" >&2
    exit 1
fi

CLAWD_DIR="$HOME/clawd"
DEXTER_RUN="$CLAWD_DIR/tools/dexter-run.sh"
source "$CLAWD_DIR/tools/discord-channels.sh"

LOG="$CLAWD_DIR/logs/earnings-deep-analysis.log"
exec >> "$LOG" 2>&1
echo "$(date '+%Y-%m-%d %H:%M:%S') Starting deep analysis for $TICKER"

# Load thesis for context
THESIS=$("$CLAWD_DIR/venv/bin/python" -c "
import json
try:
    with open('$CLAWD_DIR/memory/current-theses.json') as f:
        theses = json.load(f).get('theses', {})
    t = theses.get('$TICKER', {})
    if t:
        status = t.get('status', 'N/A')
        thesis_text = t.get('thesis', t.get('summary', 'N/A'))[:300]
        print(f'[{status}] {thesis_text}')
    else:
        print('No thesis on file')
except:
    print('No thesis on file')
" 2>/dev/null)

# Build the Dexter query
QUERY="Post-earnings analysis for $TICKER. Reported: $EARNINGS_DATA. Investment thesis: $THESIS.

Analyze concisely (max 1500 chars):
1) Beat/miss vs estimates and significance
2) Revenue quality and margin trends
3) Key balance sheet changes
4) Thesis impact — does this confirm or challenge the thesis?
5) One-line action: hold, add, trim, or watch

Be specific with numbers. Skip pleasantries."

# Run Dexter (timeout 3 minutes)
export PATH="$HOME/.bun/bin:$PATH"
ANALYSIS=$(timeout 180 "$DEXTER_RUN" query --model claude-sonnet-4-20250514 --max-iterations 6 "$QUERY" 2>/dev/null) || true

if [ -z "$ANALYSIS" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') Dexter returned empty for $TICKER, skipping"
    exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') Got analysis for $TICKER (${#ANALYSIS} chars)"

# Post to #sec-filings
MSG="**${TICKER} Deep Earnings Analysis**

${ANALYSIS}"

send_discord "$DISCORD_SEC_FILINGS" "$MSG"

# Also post to #research if it's a holding or priority
if [ "$CATEGORY" = "holding" ] || [ "$CATEGORY" = "priority" ]; then
    send_discord "$DISCORD_RESEARCH" "$MSG"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') Posted analysis for $TICKER"
