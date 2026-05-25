#!/bin/bash
# Tweet Feed - Posts notable tweets from priority accounts to Discord #tweet-feed
# Runs every 15 minutes during market hours via cron
# Fetches 2 most recent tweets per account, posts only unseen ones from last 2 hours

CLAWD_DIR="$HOME/clawd"
CHANNEL="1468334902557802598"  # #tweet-feed
LOG="$CLAWD_DIR/logs/tweet-feed.log"
SEEN_FILE="$CLAWD_DIR/memory/tweet-feed-seen.json"
ACCOUNTS_FILE="$CLAWD_DIR/memory/twitter-priority-accounts.json"
BATCH_FILE="/tmp/tweet-feed-batch.json"

source "$CLAWD_DIR/credentials/twitter-creds.sh"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG"; }

# Initialize seen file if needed
[ -f "$SEEN_FILE" ] || echo '{"seen":[]}' > "$SEEN_FILE"

# Load priority account handles
HANDLES=$("$CLAWD_DIR/venv/bin/python" -c "
import json
with open('$ACCOUNTS_FILE') as f:
    data = json.load(f)
for a in data.get('accounts', []):
    print(a.lstrip('@'))
" 2>/dev/null)

if [ -z "$HANDLES" ]; then
    log "ERROR: Could not load priority accounts"
    exit 1
fi

# Collect tweets from all accounts into one JSON array
echo "[]" > "$BATCH_FILE"

for handle in $HANDLES; do
    RAW=$(bird user-tweets "$handle" -n 2 --json --plain \
        --auth-token "$TWITTER_AUTH_TOKEN" --ct0 "$TWITTER_CT0" 2>/dev/null)

    if [ $? -ne 0 ] || [ -z "$RAW" ]; then
        continue
    fi

    # Append to batch (merge arrays)
    "$CLAWD_DIR/venv/bin/python" -c "
import sys, json
try:
    existing = json.load(open('$BATCH_FILE'))
    new_tweets = json.loads(sys.stdin.read())
    if isinstance(new_tweets, list):
        existing.extend(new_tweets)
    with open('$BATCH_FILE', 'w') as f:
        json.dump(existing, f)
except Exception:
    pass
" <<< "$RAW"

    sleep 1  # Rate limit
done

# Filter and post new tweets
"$CLAWD_DIR/venv/bin/python" << 'PYEOF'
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone

SEEN_FILE = "/home/nicknemo17/clawd/memory/tweet-feed-seen.json"
BATCH_FILE = "/tmp/tweet-feed-batch.json"
CHANNEL = "1468334902557802598"
LOG = "/home/nicknemo17/clawd/logs/tweet-feed.log"

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")

# Load seen
try:
    with open(SEEN_FILE) as f:
        seen_data = json.load(f)
    seen = set(seen_data.get("seen", []))
except Exception:
    seen = set()

# Load batch
try:
    with open(BATCH_FILE) as f:
        tweets = json.load(f)
except Exception:
    tweets = []

cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
posted = 0

for tw in tweets:
    # Get tweet ID
    tid = str(tw.get("id") or tw.get("rest_id", ""))
    if not tid or tid in seen:
        continue

    # Get text
    text = tw.get("text", tw.get("full_text", ""))
    if not text or text.startswith("RT @"):
        continue

    # Get user info
    user = tw.get("user", {})
    handle = user.get("screen_name", "")
    name = user.get("name", handle)

    if not handle:
        continue

    # Check recency
    created = tw.get("created_at", "")
    if created:
        try:
            dt = datetime.strptime(created, "%a %b %d %H:%M:%S %z %Y")
            if dt < cutoff:
                continue
        except ValueError:
            pass

    # Truncate long tweets
    if len(text) > 400:
        text = text[:397] + "..."

    msg = f"**{name}** (@{handle})\n{text}"

    result = subprocess.run(
        ["clawdbot", "message", "send",
         "--channel", "discord",
         "--target", f"channel:{CHANNEL}",
         "--message", msg],
        capture_output=True, text=True, timeout=30
    )

    if result.returncode == 0:
        seen.add(tid)
        posted += 1
        log(f"Posted tweet {tid} from @{handle}")
    else:
        log(f"Failed to post tweet {tid}: {result.stderr.strip()}")

    time.sleep(1)

# Save seen (keep last 500)
seen_list = list(seen)[-500:]
with open(SEEN_FILE, "w") as f:
    json.dump({"seen": seen_list}, f)

if posted == 0:
    log("No new tweets from priority accounts")
else:
    log(f"Posted {posted} tweets total")
PYEOF
