#!/bin/bash
# Curated Tweet Feed - Picks trending market-related tweets from For You timeline
# Runs hourly during market hours, posts top 3 to Discord #tweet-feed

CLAWD_DIR="$HOME/clawd"
LOG="$CLAWD_DIR/logs/tweet-feed.log"
SEEN_FILE="$CLAWD_DIR/memory/tweet-feed-seen.json"
TIMELINE_FILE="/tmp/tweet-curated-timeline.json"

source "$CLAWD_DIR/credentials/twitter-creds.sh"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG"; }

# Initialize seen file if needed
[ -f "$SEEN_FILE" ] || echo '{"seen":[]}' > "$SEEN_FILE"

# Fetch 40 tweets from For You timeline to temp file
bird home -n 40 --json --plain \
    --auth-token "$TWITTER_AUTH_TOKEN" --ct0 "$TWITTER_CT0" \
    > "$TIMELINE_FILE" 2>/dev/null

if [ $? -ne 0 ] || [ ! -s "$TIMELINE_FILE" ]; then
    log "Curated: home timeline fetch failed"
    exit 1
fi

# Filter, rank, and post
"$CLAWD_DIR/venv/bin/python" << 'PYEOF'
import json
import subprocess
import re
import time
from datetime import datetime, timedelta, timezone

SEEN_FILE = "/home/nicknemo17/clawd/memory/tweet-feed-seen.json"
TIMELINE_FILE = "/tmp/tweet-curated-timeline.json"
CHANNEL = "1468334902557802598"  # #tweet-feed
LOG = "/home/nicknemo17/clawd/logs/tweet-feed.log"
MAX_POSTS = 3

MARKET_KEYWORDS = re.compile(
    r'\b('
    r'stock|stocks|market|markets|bull|bear|rally|sell.?off|crash|correction|'
    r'earning|earnings|revenue|eps|beat|miss|guidance|'
    r'fed|fomc|rate.?cut|rate.?hike|powell|inflation|cpi|ppi|jobs|nonfarm|gdp|'
    r'tariff|tariffs|trade.?war|sanction|'
    r'sp500|s&p|nasdaq|dow|russell|vix|'
    r'btc|bitcoin|eth|ethereum|crypto|sol|solana|'
    r'ipo|merger|acquisition|buyback|dividend|'
    r'ai\b|nvidia|nvda|tsla|tesla|aapl|apple|msft|meta|googl|amzn|amazon|amd|'
    r'semiconductor|chip|hbm|gpu|datacenter|'
    r'oil|gold|silver|treasury|bond|yield|dollar|'
    r'short.?squeeze|options|calls|puts|gamma|'
    r'breaking|just.in|report|surge|plunge|soar|tank|dump|pump|moon'
    r')\b', re.IGNORECASE
)

def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")

# Load seen
try:
    with open(SEEN_FILE) as f:
        seen = set(json.load(f).get("seen", []))
except Exception:
    seen = set()

# Load timeline from file
try:
    with open(TIMELINE_FILE) as f:
        tweets = json.load(f)
except Exception:
    log("Curated: failed to parse timeline JSON")
    exit(1)

cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
candidates = []

for tw in tweets:
    tid = str(tw.get("id", ""))
    if not tid or tid in seen:
        continue

    text = tw.get("text", "")
    if not text or text.startswith("RT @"):
        continue

    # Check recency
    created = tw.get("createdAt", tw.get("created_at", ""))
    if created:
        try:
            dt = datetime.strptime(created, "%a %b %d %H:%M:%S %z %Y")
            if dt < cutoff:
                continue
        except ValueError:
            pass

    # Must be market-related
    matches = MARKET_KEYWORDS.findall(text)
    if not matches:
        continue

    author = tw.get("author", {})
    handle = author.get("username", tw.get("user", {}).get("screen_name", ""))
    name = author.get("name", tw.get("user", {}).get("name", handle))

    likes = tw.get("likeCount", tw.get("favorite_count", 0)) or 0
    rts = tw.get("retweetCount", tw.get("retweet_count", 0)) or 0
    replies = tw.get("replyCount", tw.get("reply_count", 0)) or 0

    # Engagement score: weighted combo
    score = likes + (rts * 3) + (replies * 2) + (len(matches) * 50)

    candidates.append({
        "tid": tid,
        "handle": handle,
        "name": name,
        "text": text[:400],
        "likes": likes,
        "rts": rts,
        "score": score,
    })

# Sort by score, take top N
candidates.sort(key=lambda x: x["score"], reverse=True)
top = candidates[:MAX_POSTS]

if not top:
    log(f"Curated: no new market tweets (checked {len(tweets)}, {len(candidates)} candidates)")
    exit(0)

posted = 0
for tw in top:
    engagement = []
    if tw["likes"] >= 50:
        engagement.append(f"{tw['likes']:,} likes")
    if tw["rts"] >= 10:
        engagement.append(f"{tw['rts']:,} RTs")
    eng_str = f"\n_{', '.join(engagement)}_" if engagement else ""

    msg = f"**{tw['name']}** (@{tw['handle']})\n{tw['text']}{eng_str}"

    result = subprocess.run(
        ["clawdbot", "message", "send",
         "--channel", "discord",
         "--target", f"channel:{CHANNEL}",
         "--message", msg],
        capture_output=True, text=True, timeout=30
    )

    if result.returncode == 0:
        seen.add(tw["tid"])
        posted += 1
        log(f"Curated: @{tw['handle']} (score={tw['score']}, {tw['likes']} likes)")
    time.sleep(1)

# Save seen (keep last 500)
seen_list = list(seen)[-500:]
with open(SEEN_FILE, "w") as f:
    json.dump({"seen": seen_list}, f)

log(f"Curated: posted {posted}/{len(candidates)} market tweets")
PYEOF
