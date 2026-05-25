#!/bin/bash
# Tech Debt Scanner - Find duplicate code and anti-patterns
# Usage: ~/clawd/skills/techdebt.sh [directory]

DIR="${1:-.}"
echo "🔍 Scanning for tech debt in: $DIR"
echo ""

echo "━━━ Duplicate Function Names ━━━"
# Find duplicate function definitions (basic pattern matching)
find "$DIR" -type f \( -name "*.js" -o -name "*.py" -o -name "*.sh" \) -exec grep -Hn "^function \|^def \|^async function" {} \; 2>/dev/null | \
    awk -F: '{print $NF}' | sort | uniq -d | head -20

echo ""
echo "━━━ TODO/FIXME Comments ━━━"
find "$DIR" -type f \( -name "*.js" -o -name "*.py" -o -name "*.sh" -o -name "*.md" \) -exec grep -Hn "TODO\|FIXME\|HACK\|XXX" {} \; 2>/dev/null | head -20

echo ""
echo "━━━ Large Files (>500 lines) ━━━"
find "$DIR" -type f \( -name "*.js" -o -name "*.py" \) -exec wc -l {} \; 2>/dev/null | awk '$1 > 500' | sort -rn | head -10

echo ""
echo "━━━ Potential Security Issues ━━━"
echo "Checking for common security anti-patterns..."
find "$DIR" -type f \( -name "*.js" -o -name "*.py" -o -name "*.sh" \) -exec grep -Hn "eval(\|exec(\|rm -rf\|password.*=.*['\"]" {} \; 2>/dev/null | head -10

echo ""
echo "✅ Tech debt scan complete"
echo ""
echo "💡 Tip: Fix high-priority items before your next PR"
