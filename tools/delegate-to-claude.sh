#!/bin/bash
# Delegate tasks to terminal Claude (FREE - no API costs)

TASK="$1"
WORKDIR="${2:-$PWD}"

if [ -z "$TASK" ]; then
    echo "Usage: $0 'task description' [working-directory]"
    exit 1
fi

cd "$WORKDIR" || exit 1

# Run Claude CLI in non-interactive mode
# This uses local compute, not API credits
echo "🤖 Delegating to terminal Claude (FREE compute)..."
echo "Task: $TASK"
echo "Working directory: $WORKDIR"
echo ""

# Create a temporary prompt file
PROMPT_FILE="/tmp/claude-task-$$.txt"
cat > "$PROMPT_FILE" << EOF
You are working in: $WORKDIR

Context: Read .claude.md for workspace rules and context.

Task: $TASK

Requirements:
- Follow all rules in .claude.md
- Optimize for cost (use free tools)
- Document what you did
- Return results in structured format

Execute the task now.
EOF

# Run Claude with the prompt (--print for non-interactive)
claude --print < "$PROMPT_FILE"

rm "$PROMPT_FILE"
