#!/bin/bash
# Spawn a terminal Claude subagent for parallel work

TASK="$1"
NAME="${2:-subagent}"
LOGFILE="$HOME/clawd/memory/subagent-$NAME-$(date +%s).log"

if [ -z "$TASK" ]; then
    echo "Usage: $0 'task description' [agent-name]"
    exit 1
fi

echo "🚀 Spawning subagent: $NAME"
echo "Task: $TASK"
echo "Log: $LOGFILE"

# Run in background terminal
cd ~/clawd || exit 1

# Create task file for subagent
TASK_FILE="/tmp/subagent-$NAME-$$.txt"
cat > "$TASK_FILE" << EOF
Subagent: $NAME
Started: $(date)

Context:
- Read ~/clawd/.claude.md for workspace rules
- You are a subagent working in parallel
- Report results to $LOGFILE
- Use free tools, minimize API costs

Task:
$TASK

Execute and log results.
EOF

# Spawn Claude in background (don't delete task file immediately)
nohup claude --print < "$TASK_FILE" > "$LOGFILE" 2>&1 &
SUBAGENT_PID=$!

echo "✅ Subagent spawned (PID: $SUBAGENT_PID)"
echo "Monitor: tail -f $LOGFILE"

# Sleep briefly to let Claude read the file before deleting
sleep 2
rm -f "$TASK_FILE"
