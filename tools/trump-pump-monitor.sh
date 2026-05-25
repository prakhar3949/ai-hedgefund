#!/bin/bash
# Trump Twitter Pump Monitor — local replacement for Clawdbot job
# Runs trump-twitter-monitor.sh and sends alerts directly (zero tokens)
# Schedule: every 5 min, 6am-11pm PST
#
# Cost: $0.00 (Tier 1 — shell script, no LLM)

CLAWD="$HOME/clawd"
LOGFILE="$CLAWD/logs/trump-pump.log"

source "$CLAWD/tools/discord-channels.sh"

RESULT=$("$CLAWD/tools/trump-twitter-monitor.sh" 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -eq 1 ]; then
    # Pump detected — alert immediately
    TIMESTAMP=$(TZ=America/New_York date '+%I:%M %p ET')
    MSG="**TRUMP MARKET PUMP** ($TIMESTAMP)

$RESULT"

    # WhatsApp alert (time-sensitive)
    clawdbot message send --channel whatsapp --target "$WHATSAPP_TARGET" --message "$MSG" \
        > /dev/null 2>&1 &

    # Discord #tweet-feed (it's a tweet)
    clawdbot message send --channel discord --target "channel:$DISCORD_TWEET_FEED" --message "$MSG" \
        > /dev/null 2>&1 &

    echo "$(date '+%Y-%m-%d %H:%M:%S') PUMP DETECTED — alerts sent" >> "$LOGFILE"
else
    # Log only every 30 min to avoid huge log files
    MINUTE=$(date '+%M')
    if [ "$MINUTE" = "00" ] || [ "$MINUTE" = "30" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') No pump tweets" >> "$LOGFILE"
    fi
fi
