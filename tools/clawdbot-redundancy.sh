#!/bin/bash
# Clawdbot Redundancy Layer
# Handles: credential backup, health monitoring, Discord failover,
# session recovery, and connection quality tracking.
# Run via systemd timer every 10 minutes.

CLAWD_DIR="$HOME/clawd"
CLAWDBOT_DIR="$HOME/.clawdbot"
BACKUP_DIR="$CLAWD_DIR/backups/clawdbot"
LOG_FILE="$CLAWD_DIR/logs/redundancy.log"
HEALTH_FILE="$CLAWD_DIR/logs/connection-health.json"
LOCK_FILE="/tmp/clawdbot-redundancy.lock"
DISCORD_CHANNEL="1468334675041976422"

mkdir -p "$CLAWD_DIR/logs" "$BACKUP_DIR"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

# Lock file
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"

# ─── 1. CREDENTIAL BACKUP ───────────────────────────────────────────
backup_credentials() {
    local TIMESTAMP=$(date '+%Y%m%d-%H%M')
    local CREDS_SRC="$CLAWDBOT_DIR/credentials/whatsapp/default"
    local BACKUP_DEST="$BACKUP_DIR/creds-$TIMESTAMP"

    # Only backup if creds.json has changed since last backup
    local LATEST_BACKUP=$(ls -td "$BACKUP_DIR"/creds-* 2>/dev/null | head -1)
    if [ -n "$LATEST_BACKUP" ] && [ -f "$LATEST_BACKUP/creds.json" ]; then
        if diff -q "$CREDS_SRC/creds.json" "$LATEST_BACKUP/creds.json" >/dev/null 2>&1; then
            return 0  # No changes
        fi
    fi

    # Backup creds.json and key files
    mkdir -p "$BACKUP_DEST"
    cp "$CREDS_SRC/creds.json" "$BACKUP_DEST/" 2>/dev/null
    cp "$CREDS_SRC"/sender-key-*.json "$BACKUP_DEST/" 2>/dev/null
    cp "$CREDS_SRC"/session-*.json "$BACKUP_DEST/" 2>/dev/null

    # Keep only last 10 backups
    ls -td "$BACKUP_DIR"/creds-* 2>/dev/null | tail -n +11 | xargs rm -rf 2>/dev/null

    log "BACKUP: Credentials backed up to $BACKUP_DEST"
}

# ─── 2. CONNECTION HEALTH TRACKING ──────────────────────────────────
track_health() {
    local NOW=$(date '+%Y-%m-%dT%H:%M:%S')
    local WA_STATUS="disconnected"
    local DISCORD_STATUS="disconnected"
    local GATEWAY_STATUS="down"

    # Check gateway
    if systemctl --user is-active clawdbot-gateway >/dev/null 2>&1; then
        GATEWAY_STATUS="running"
    fi

    # Check WhatsApp
    local STATUS_OUTPUT=$(clawdbot channels status 2>/dev/null)
    if echo "$STATUS_OUTPUT" | grep -q "WhatsApp.*connected"; then
        WA_STATUS="connected"
    elif echo "$STATUS_OUTPUT" | grep -q "WhatsApp.*running"; then
        WA_STATUS="running_not_connected"
    fi

    # Check Discord
    if echo "$STATUS_OUTPUT" | grep -q "Discord.*running"; then
        DISCORD_STATUS="connected"
    fi

    # Write health snapshot
    cat > "$HEALTH_FILE" <<EOF
{
  "timestamp": "$NOW",
  "gateway": "$GATEWAY_STATUS",
  "whatsapp": "$WA_STATUS",
  "discord": "$DISCORD_STATUS",
  "uptime_seconds": $(systemctl --user show clawdbot-gateway --property=ExecMainStartTimestamp 2>/dev/null | cut -d= -f2 | xargs -I{} bash -c 'echo $(( $(date +%s) - $(date -d "{}" +%s 2>/dev/null || echo $(date +%s)) ))'),
  "pid": $(systemctl --user show clawdbot-gateway --property=MainPID 2>/dev/null | cut -d= -f2),
  "memory_mb": $(ps -o rss= -p $(systemctl --user show clawdbot-gateway --property=MainPID 2>/dev/null | cut -d= -f2) 2>/dev/null | awk '{printf "%.1f", $1/1024}' || echo "0")
}
EOF
}

# ─── 3. DISCORD FAILOVER ────────────────────────────────────────────
# When WhatsApp is down, ensure Discord is still operational for alerts
check_discord_failover() {
    # Don't check if gateway started recently (let it stabilize)
    local PID=$(systemctl --user show clawdbot-gateway --property=MainPID 2>/dev/null | cut -d= -f2)
    if [ -n "$PID" ] && [ "$PID" != "0" ]; then
        local START_TIME=$(ps -o etimes= -p "$PID" 2>/dev/null | tr -d ' ')
        if [ -n "$START_TIME" ] && [ "$START_TIME" -lt 60 ]; then
            log "INFO: Gateway started ${START_TIME}s ago, skipping failover check"
            return 0
        fi
    fi

    local STATUS_OUTPUT=$(clawdbot channels status 2>/dev/null)

    # If WhatsApp is down but Discord is up, that's our failover
    if ! echo "$STATUS_OUTPUT" | grep -q "WhatsApp.*connected"; then
        if echo "$STATUS_OUTPUT" | grep -q "Discord.*running"; then
            log "FAILOVER: WhatsApp down, Discord active as fallback"
            return 0
        else
            # Both down - leave restart to the watchdog, just log
            log "CRITICAL: Both WhatsApp and Discord are down. Watchdog will handle recovery."
            return 1
        fi
    fi
    return 0
}

# ─── 4. LOG ROTATION ────────────────────────────────────────────────
rotate_logs() {
    local MAX_SIZE=5242880  # 5MB
    for logfile in "$CLAWD_DIR/logs"/*.log; do
        if [ -f "$logfile" ]; then
            local SIZE=$(stat -c%s "$logfile" 2>/dev/null || echo 0)
            if [ "$SIZE" -gt "$MAX_SIZE" ]; then
                mv "$logfile" "${logfile}.old"
                log "ROTATE: Rotated $(basename "$logfile") ($SIZE bytes)"
            fi
        fi
    done
}

# ─── 5. SESSION RECOVERY CHECK ──────────────────────────────────────
check_session_integrity() {
    local CREDS_FILE="$CLAWDBOT_DIR/credentials/whatsapp/default/creds.json"

    # Check if credentials file exists and is valid JSON
    if [ ! -f "$CREDS_FILE" ]; then
        log "CRITICAL: WhatsApp credentials file missing!"

        # Attempt restore from backup
        local LATEST_BACKUP=$(ls -td "$BACKUP_DIR"/creds-* 2>/dev/null | head -1)
        if [ -n "$LATEST_BACKUP" ] && [ -f "$LATEST_BACKUP/creds.json" ]; then
            log "RESTORE: Restoring credentials from $LATEST_BACKUP"
            cp "$LATEST_BACKUP/creds.json" "$CREDS_FILE"
            systemctl --user restart clawdbot-gateway 2>/dev/null

            clawdbot message send --channel discord --target "channel:$DISCORD_CHANNEL" \
                --message "RECOVERY: WhatsApp credentials restored from backup. Restarting gateway." 2>/dev/null
        else
            clawdbot message send --channel discord --target "channel:$DISCORD_CHANNEL" \
                --message "CRITICAL: WhatsApp credentials missing and no backup available. Manual re-pairing required." 2>/dev/null
        fi
        return 1
    fi

    # Check if creds.json is valid JSON
    if ! python3 -c "import json; json.load(open('$CREDS_FILE'))" 2>/dev/null; then
        log "WARNING: Credentials file appears corrupt"

        local LATEST_BACKUP=$(ls -td "$BACKUP_DIR"/creds-* 2>/dev/null | head -1)
        if [ -n "$LATEST_BACKUP" ] && [ -f "$LATEST_BACKUP/creds.json" ]; then
            log "RESTORE: Replacing corrupt credentials from backup"
            cp "$LATEST_BACKUP/creds.json" "$CREDS_FILE"
            systemctl --user restart clawdbot-gateway 2>/dev/null
        fi
        return 1
    fi

    return 0
}

# ─── 6. GATEWAY PROCESS HEALTH ──────────────────────────────────────
check_gateway_health() {
    local PID=$(systemctl --user show clawdbot-gateway --property=MainPID 2>/dev/null | cut -d= -f2)

    if [ -z "$PID" ] || [ "$PID" = "0" ]; then
        log "WARNING: Gateway has no running PID, restarting..."
        systemctl --user restart clawdbot-gateway 2>/dev/null
        return 1
    fi

    # Check memory usage (alert if over 500MB - common Baileys leak)
    local MEM_KB=$(ps -o rss= -p "$PID" 2>/dev/null)
    if [ -n "$MEM_KB" ] && [ "$MEM_KB" -gt 512000 ]; then
        local MEM_MB=$((MEM_KB / 1024))
        log "WARNING: Gateway memory usage high (${MEM_MB}MB). Restarting to prevent OOM."
        systemctl --user restart clawdbot-gateway 2>/dev/null
        sleep 25
        clawdbot message send --channel discord --target "channel:$DISCORD_CHANNEL" \
            --message "WhatsApp gateway restarted due to high memory usage (${MEM_MB}MB)" 2>/dev/null
    fi

    return 0
}

# ─── RUN ALL CHECKS ─────────────────────────────────────────────────
log "--- Redundancy check starting ---"

# Backup first (doesn't need gateway running)
backup_credentials
rotate_logs

# Only run live checks if gateway is actually running and stable
if systemctl --user is-active clawdbot-gateway >/dev/null 2>&1; then
    UPTIME_SECS=$(systemctl --user show clawdbot-gateway --property=ActiveEnterTimestampMonotonic 2>/dev/null | cut -d= -f2)
    NOW_MONO=$(cat /proc/uptime | cut -d' ' -f1 | cut -d. -f1)

    # Wait for gateway to be up at least 30 seconds before running health checks
    if [ -n "$UPTIME_SECS" ] && [ "$UPTIME_SECS" != "" ]; then
        check_session_integrity || { log "Session issue detected, skipping further checks"; log "--- Redundancy check complete ---"; exit 1; }
        check_gateway_health || { log "Gateway restarted, skipping further checks"; log "--- Redundancy check complete ---"; exit 0; }
        check_discord_failover
        track_health
    else
        log "INFO: Gateway uptime unknown, skipping live checks"
    fi
else
    log "WARNING: Gateway not running, starting it..."
    systemctl --user start clawdbot-gateway 2>/dev/null
    check_session_integrity
fi

log "--- Redundancy check complete ---"
