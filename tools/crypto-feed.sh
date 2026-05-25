#!/bin/bash
# Crypto Feed - Posts crypto snapshots and alerts to Discord #crypto
# Runs every 30 minutes via cron
# Posts a snapshot every run; bold alert header when thresholds breached

CLAWD_DIR="$HOME/clawd"
CHANNEL="1468424649531457619"  # #crypto
LOG="$CLAWD_DIR/logs/crypto-feed.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG"; }

# Get crypto quotes
QUOTES=$("$CLAWD_DIR/venv/bin/python" "$CLAWD_DIR/tools/crypto-monitor.py" 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$QUOTES" ]; then
    log "ERROR: crypto-monitor.py failed"
    exit 1
fi

# Format message
MSG=$("$CLAWD_DIR/venv/bin/python" -c "
import sys, json
from datetime import datetime

quotes = json.loads(sys.stdin.read())
any_alert = any(q.get('alert') for q in quotes if 'error' not in q)

lines = []
if any_alert:
    lines.append('**CRYPTO ALERT**')
else:
    lines.append('**Crypto Update**')
lines.append('')

for q in quotes:
    if 'error' in q:
        continue
    sym = q['symbol'].replace('-USD', '')
    price = q.get('price')
    pct = q.get('changePercent')
    if price is None:
        continue

    if price >= 1000:
        price_str = f'\${price:,.0f}'
    elif price >= 1:
        price_str = f'\${price:.2f}'
    else:
        price_str = f'\${price:.4f}'

    if pct is not None:
        direction = '+' if pct >= 0 else ''
        pct_str = f'({direction}{pct:.1f}%)'
        # Flag big movers
        if q.get('alert'):
            lines.append(f'**{sym}**: {price_str} {pct_str} !')
        else:
            lines.append(f'{sym}: {price_str} {pct_str}')
    else:
        lines.append(f'{sym}: {price_str}')

now = datetime.now().strftime('%H:%M ET')
lines.append(f'')
lines.append(f'{now}')
print('\n'.join(lines))
" <<< "$QUOTES")

if [ -z "$MSG" ]; then
    log "No quotes to post"
    exit 0
fi

clawdbot message send --channel discord --target "channel:$CHANNEL" --message "$MSG" 2>/dev/null
log "Posted crypto update"
