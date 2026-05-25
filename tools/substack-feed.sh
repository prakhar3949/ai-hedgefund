#!/bin/bash
# Substack Feed - Posts new Substack articles to Discord #substack-feed
# Runs every 30 minutes via cron

CLAWD_DIR="$HOME/clawd"
CHANNEL="1468334855946375431"  # #substack-feed
LOG="$CLAWD_DIR/logs/substack-feed.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG"; }

# Get new posts from substack-monitor.js (Gmail-based, with dedup)
POSTS=$(node "$CLAWD_DIR/tools/substack-monitor.js" 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$POSTS" ]; then
    log "No output from substack-monitor.js"
    exit 0
fi

# Parse and post each new article
echo "$POSTS" | "$CLAWD_DIR/venv/bin/python" -c "
import sys, json

try:
    posts = json.loads(sys.stdin.read())
    if not posts:
        sys.exit(0)
    for post in posts:
        author = post.get('from', '').split('<')[0].strip().strip('\"')
        subject = post.get('subject', 'New Post')
        url = post.get('url', '')
        # Output one message per line, pipe-delimited
        print(f'{author}|{subject}|{url}')
except Exception:
    pass
" | while IFS='|' read -r author subject url; do
    [ -z "$url" ] && continue

    MSG="**${author}**
${subject}
${url}"

    clawdbot message send --channel discord --target "channel:$CHANNEL" --message "$MSG" 2>/dev/null
    log "Posted: $subject ($url)"
    sleep 1
done
