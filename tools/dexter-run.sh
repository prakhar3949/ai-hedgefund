#!/bin/bash
# Dexter CLI wrapper — unified entry point for shell/python scripts
#
# Usage:
#   dexter-run.sh query "What is COHR's intrinsic value?"
#   dexter-run.sh query --model claude-opus-4-6 "Deep analysis of KSPI"
#   dexter-run.sh data price-snapshot COHR
#   dexter-run.sh data batch-snapshot COHR,KSPI,XNET
#
# The "query" command uses a lockfile to prevent concurrent Dexter agent runs
# (Pi has limited RAM — one agent at a time). The "data" command has no lock
# since it's just direct API calls.

DEXTER_DIR="$HOME/clawd/tools/dexter"
BUN="$HOME/.bun/bin/bun"
LOCKFILE="$HOME/clawd/memory/.dexter-lock"
LOCKFILE_TIMEOUT=300  # 5 minutes max wait

if [ ! -x "$BUN" ]; then
    echo "Error: Bun not found at $BUN" >&2
    exit 1
fi

case "$1" in
    query)
        shift
        # Acquire lock (only for agent queries which use significant RAM)
        if ! mkdir "$LOCKFILE" 2>/dev/null; then
            # Check if lock is stale (older than 5 min)
            if [ -d "$LOCKFILE" ]; then
                lock_age=$(( $(date +%s) - $(stat -c %Y "$LOCKFILE" 2>/dev/null || echo 0) ))
                if [ "$lock_age" -gt "$LOCKFILE_TIMEOUT" ]; then
                    echo "[dexter-run] Stale lock detected (${lock_age}s old), removing" >&2
                    rmdir "$LOCKFILE" 2>/dev/null
                    mkdir "$LOCKFILE" 2>/dev/null || { echo "Error: Could not acquire lock" >&2; exit 1; }
                else
                    echo "Error: Dexter agent already running (lock age: ${lock_age}s). Try again later." >&2
                    exit 1
                fi
            fi
        fi
        trap "rmdir '$LOCKFILE' 2>/dev/null" EXIT

        cd "$DEXTER_DIR" && "$BUN" run scripts/dexter-query.ts "$@"
        ;;
    data)
        shift
        # No lock needed for direct API calls
        # Filter out dotenv log lines that pollute stdout
        cd "$DEXTER_DIR" && "$BUN" run scripts/dexter-data.ts "$@" 2>/dev/null | grep -v '^\[dotenv'
        ;;
    *)
        echo "Usage: dexter-run.sh {query|data} [args...]"
        echo ""
        echo "Commands:"
        echo "  query [--model M] [--max-iterations N] [--json] \"question\""
        echo "    Run Dexter agent for research (uses LLM, ~\$0.15-0.50/query)"
        echo ""
        echo "  data <command> [args...]"
        echo "    Direct API calls, zero LLM cost. Run 'dexter-run.sh data --help' for commands."
        exit 1
        ;;
esac
