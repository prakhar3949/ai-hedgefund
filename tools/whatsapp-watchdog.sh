#!/bin/bash
# WhatsApp Watchdog - Auto-reconnect + Alert
# Runs every 2 minutes via systemd timer (whatsapp-watchdog.timer)
# Uses a lock file to prevent concurrent runs

CLAWD_DIR="$HOME/clawd"
LOG_FILE="$CLAWD_DIR/logs/whatsapp-watchdog.log"
LOCK_FILE="/tmp/whatsapp-watchdog.lock"
FAIL_COUNT_FILE="/tmp/whatsapp-watchdog-failures"
DISCORD_CHANNEL="1468334675041976422"
MAX_RETRIES=3
RETRY_DELAY=20
STABILIZE_DELAY=25

mkdir -p "$CLAWD_DIR/logs"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

# Prevent concurrent runs with lock file
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        # Another watchdog is still running - skip this run
        exit 0
    fi
    # Stale lock file - remove it
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"

check_whatsapp() {
    # Check multiple times to avoid false positives during transient states
    for check in 1 2 3; do
        STATUS=$(clawdbot channels status 2>/dev/null | grep -i "whatsapp" | head -1)
        if echo "$STATUS" | grep -q "connected"; then
            return 0  # Connected
        fi
        sleep 3
    done
    return 1  # Not connected after 3 checks
}

get_fail_count() {
    if [ -f "$FAIL_COUNT_FILE" ]; then
        cat "$FAIL_COUNT_FILE"
    else
        echo 0
    fi
}

set_fail_count() {
    echo "$1" > "$FAIL_COUNT_FILE"
}

# Check if gateway service is running at all
if ! systemctl --user is-active clawdbot-gateway >/dev/null 2>&1; then
    log "WARNING: Gateway service not running. Starting it..."
    systemctl --user start clawdbot-gateway 2>/dev/null
    sleep "$STABILIZE_DELAY"
fi

# Initial check
if check_whatsapp; then
    # Reset failure counter on success
    PREV_FAILS=$(get_fail_count)
    set_fail_count 0

    # Log recovery if we were previously failing
    if [ "$PREV_FAILS" -gt 0 ]; then
        log "RECOVERED: WhatsApp reconnected after $PREV_FAILS failed cycles"
        clawdbot message send --channel discord --target "channel:$DISCORD_CHANNEL" \
            --message "WhatsApp Watchdog: Connection recovered after $PREV_FAILS failed cycles" 2>/dev/null
    fi

    # Log health every 20 minutes
    MINUTE=$(date +%M)
    if [ $((MINUTE % 20)) -eq 0 ]; then
        log "OK: WhatsApp connected"
    fi
    exit 0
fi

# Not connected - increment failure counter for backoff
FAILS=$(get_fail_count)
FAILS=$((FAILS + 1))
set_fail_count "$FAILS"

# Exponential backoff: skip some cycles if we've been failing repeatedly
# After 5+ consecutive failures, only try every other cycle
# After 10+ failures, only try every 3rd cycle
if [ "$FAILS" -gt 10 ] && [ $((FAILS % 3)) -ne 0 ]; then
    log "BACKOFF: Skipping recovery attempt (failure cycle $FAILS, trying every 3rd)"
    exit 1
elif [ "$FAILS" -gt 5 ] && [ $((FAILS % 2)) -ne 0 ]; then
    log "BACKOFF: Skipping recovery attempt (failure cycle $FAILS, trying every 2nd)"
    exit 1
fi

log "WARNING: WhatsApp disconnected (failure cycle $FAILS). Starting recovery..."

for i in $(seq 1 $MAX_RETRIES); do
    log "Attempt $i/$MAX_RETRIES: Restarting gateway..."

    # Graceful restart
    systemctl --user restart clawdbot-gateway 2>/dev/null

    # Wait for gateway to fully start and stabilize
    sleep "$STABILIZE_DELAY"

    # Check connection
    if check_whatsapp; then
        log "SUCCESS: WhatsApp reconnected after attempt $i"
        set_fail_count 0

        clawdbot message send --channel discord --target "channel:$DISCORD_CHANNEL" \
            --message "WhatsApp Watchdog: Reconnected after disconnect (attempt $i, cycle $FAILS)" 2>/dev/null

        exit 0
    fi

    log "Attempt $i failed. Waiting before retry..."
    sleep 5
done

# All retries failed
log "CRITICAL: WhatsApp failed to reconnect after $MAX_RETRIES attempts (cycle $FAILS)"

# Only send Discord alert on first failure and then every 5th cycle to avoid spam
if [ "$FAILS" -eq 1 ] || [ $((FAILS % 5)) -eq 0 ]; then
    clawdbot message send --channel discord --target "channel:$DISCORD_CHANNEL" \
        --message "CRITICAL: WhatsApp disconnected and won't reconnect (cycle $FAILS). Check gateway!" 2>/dev/null
fi

# Nuclear option only on first cycle or every 5th
if [ "$FAILS" -le 2 ] || [ $((FAILS % 5)) -eq 0 ]; then
    log "Attempting nuclear restart (stop/wait/start)..."
    systemctl --user stop clawdbot-gateway 2>/dev/null
    sleep 15
    systemctl --user start clawdbot-gateway 2>/dev/null
    sleep "$STABILIZE_DELAY"

    if check_whatsapp; then
        log "Nuclear restart succeeded"
        set_fail_count 0
        clawdbot message send --channel discord --target "channel:$DISCORD_CHANNEL" \
            --message "WhatsApp Watchdog: Nuclear restart worked (cycle $FAILS)" 2>/dev/null
        exit 0
    fi

    log "FAILED: Nuclear restart did not work (cycle $FAILS). Manual intervention may be required."
    log "Status: $(clawdbot channels status 2>/dev/null | grep -i whatsapp)"
fi
