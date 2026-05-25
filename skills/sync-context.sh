#!/bin/bash
# Context Sync - Aggregate last 7 days of context
# Usage: ~/clawd/skills/sync-context.sh

echo "📥 Syncing context from last 7 days..."
echo ""

cd ~/clawd/memory 2>/dev/null || cd ~/clawd

echo "━━━ Recent Memory Files ━━━"
if [ -d ~/clawd/memory ]; then
    ls -1t ~/clawd/memory/202*.md 2>/dev/null | head -7
else
    echo "⚠️  No memory directory found"
fi

echo ""
echo "━━━ Recent Subagent Logs ━━━"
if [ -d ~/clawd/memory ]; then
    ls -1t ~/clawd/memory/subagent-*.log 2>/dev/null | head -10
else
    echo "⚠️  No subagent logs found"
fi

echo ""
echo "━━━ Git Activity (last 7 days) ━━━"
cd ~/clawd
git log --since="7 days ago" --oneline --all 2>/dev/null | head -20 || echo "⚠️  Not a git repository"

echo ""
echo "━━━ Recent File Changes ━━━"
find ~/clawd -type f -name "*.js" -o -name "*.py" -o -name "*.sh" -o -name "*.md" 2>/dev/null | \
    xargs ls -lt 2>/dev/null | head -15 | awk '{print $9, $6, $7, $8}'

echo ""
echo "✅ Context sync complete"
echo ""
echo "💡 Tip: Review these files to catch up on recent activity"
