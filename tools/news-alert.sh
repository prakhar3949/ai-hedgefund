#!/bin/bash
# News Alert - Posts high-impact news to Discord
# Runs every 30 minutes during market hours

CLAWD_DIR="$HOME/clawd"
CHANNEL="1468334594314211423"  # #trade-alerts (was #levels-technicals)
SEEN_FILE="$CLAWD_DIR/memory/news-seen.json"

# Initialize seen file if needed
[ -f "$SEEN_FILE" ] || echo '{"seen":[]}' > "$SEEN_FILE"

# Get news
NEWS=$($CLAWD_DIR/venv/bin/python $CLAWD_DIR/tools/news-scanner.py 2>/dev/null)

# Check for high-impact news
echo "$NEWS" | $CLAWD_DIR/venv/bin/python -c "
import sys
import json

try:
    news = json.loads(sys.stdin.read())
    
    # Load seen
    with open('$SEEN_FILE') as f:
        seen_data = json.load(f)
    seen = set(seen_data.get('seen', []))
    
    alerts = []
    new_seen = list(seen)
    
    for item in news:
        if not item.get('high_impact'):
            continue
        link = item.get('link', '')
        if link in seen:
            continue
        
        ticker = item.get('ticker', 'N/A')
        title = item.get('title', 'N/A')[:100]
        sentiment = item.get('sentiment', 'NEUTRAL')
        emoji = '🟢' if sentiment == 'BULLISH' else '🔴' if sentiment == 'BEARISH' else '⚪'
        
        alerts.append(f'{emoji} **\${ticker}**: {title}')
        new_seen.append(link)
    
    # Save seen
    with open('$SEEN_FILE', 'w') as f:
        json.dump({'seen': new_seen[-100:]}, f)
    
    if alerts:
        print('🚨 **Breaking News Alert**\\n')
        print('\\n'.join(alerts[:5]))
except Exception as e:
    pass
" > /tmp/news_alert.txt

# Post if we have alerts
if [ -s /tmp/news_alert.txt ]; then
    MSG=$(cat /tmp/news_alert.txt)
    clawdbot message send --channel discord --target "channel:$CHANNEL" --message "$MSG" 2>/dev/null
fi
