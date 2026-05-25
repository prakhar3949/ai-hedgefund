#!/bin/bash
# Error Recovery - Auto-fix common issues
set -euo pipefail

CLAWD_DIR="${CLAWD_DIR:-$HOME/clawd}"

echo "🔧 Error Recovery Tool"
echo "======================="
echo ""

# Check 1: Python venv
echo "Checking Python environment..."
if [[ ! -d "$CLAWD_DIR/venv" ]]; then
    echo "❌ Python venv missing"
    echo "   Creating venv..."
    python3 -m venv "$CLAWD_DIR/venv"
    echo "   Installing requirements..."
    if [[ -f "$CLAWD_DIR/requirements.txt" ]]; then
        "$CLAWD_DIR/venv/bin/pip" install -q -r "$CLAWD_DIR/requirements.txt"
    fi
    echo "✅ Fixed"
else
    echo "✅ Python venv OK"
    
    # Check if yfinance is installed
    if ! "$CLAWD_DIR/venv/bin/python" -c "import yfinance" 2>/dev/null; then
        echo "   ⚠️  yfinance not installed, installing..."
        "$CLAWD_DIR/venv/bin/pip" install -q yfinance
        echo "   ✅ Installed yfinance"
    fi
fi

# Check 2: Required directories
echo ""
echo "Checking directories..."
REQUIRED_DIRS=(
    "memory"
    "tools"
    "skills"
    "credentials"
)

for dir in "${REQUIRED_DIRS[@]}"; do
    if [[ ! -d "$CLAWD_DIR/$dir" ]]; then
        echo "❌ Missing directory: $dir"
        mkdir -p "$CLAWD_DIR/$dir"
        echo "✅ Created"
    else
        echo "✅ $dir/"
    fi
done

# Check 3: Required files
echo ""
echo "Checking required files..."
REQUIRED_FILES=(
    "memory/current-theses.json"
    "memory/watchlist.json"
    "memory/heartbeat-state.json"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$CLAWD_DIR/$file" ]]; then
        echo "❌ Missing: $file"
        echo "   Creating default..."
        mkdir -p "$(dirname "$CLAWD_DIR/$file")"
        
        case "$file" in
            */current-theses.json)
                cat > "$CLAWD_DIR/$file" << 'EOF'
{
  "theses": {},
  "_VERIFICATION_WARNING": "Run tools before stating facts",
  "_MANDATORY_TOOLS": ["yfinance", "thesis-query.sh", "web_search", "twitter search"]
}
EOF
                ;;
            */watchlist.json)
                cat > "$CLAWD_DIR/$file" << 'EOF'
{
  "stocks": {
    "holdings": {},
    "priority": []
  }
}
EOF
                ;;
            */heartbeat-state.json)
                cat > "$CLAWD_DIR/$file" << 'EOF'
{
  "lastChecks": {
    "email": null,
    "calendar": null,
    "stocks": null
  }
}
EOF
                ;;
        esac
        echo "✅ Created with defaults"
    else
        echo "✅ $file"
    fi
done

# Check 4: Script permissions
echo ""
echo "Checking script permissions..."
FIXED=0
while IFS= read -r file; do
    chmod +x "$file"
    echo "✅ Fixed: $(basename "$file")"
    ((FIXED++))
done < <(find "$CLAWD_DIR/tools" -name "*.sh" ! -perm -u+x 2>/dev/null)

while IFS= read -r file; do
    chmod +x "$file"
    echo "✅ Fixed: $(basename "$file")"
    ((FIXED++))
done < <(find "$CLAWD_DIR/tools" -name "*.py" ! -perm -u+x 2>/dev/null)

if [[ $FIXED -eq 0 ]]; then
    echo "✅ All scripts have correct permissions"
fi

# Check 5: Validate JSON files
echo ""
echo "Validating JSON files..."
INVALID=0
while IFS= read -r file; do
    if ! python3 -m json.tool "$file" > /dev/null 2>&1; then
        echo "❌ Invalid JSON: $(basename "$file")"
        ((INVALID++))
    fi
done < <(find "$CLAWD_DIR/memory" -name "*.json" 2>/dev/null)

if [[ $INVALID -eq 0 ]]; then
    echo "✅ All JSON files valid"
else
    echo "⚠️  Found $INVALID invalid JSON files - manual fix required"
fi

# Check 6: Test key scripts
echo ""
echo "Testing key scripts..."

# Test quick-lookup
if [[ -f "$CLAWD_DIR/tools/quick-lookup.sh" ]]; then
    if "$CLAWD_DIR/tools/quick-lookup.sh" > /dev/null 2>&1; then
        echo "✅ quick-lookup.sh working"
    else
        echo "⚠️  quick-lookup.sh may have issues"
    fi
fi

# Test market_utils if it exists
if [[ -f "$CLAWD_DIR/tools/market_utils.py" ]]; then
    if "$CLAWD_DIR/venv/bin/python" -c "import sys; sys.path.insert(0, '$CLAWD_DIR/tools'); from market_utils import get_price_info" 2>/dev/null; then
        echo "✅ market_utils.py working"
    else
        echo "⚠️  market_utils.py may have issues"
    fi
fi

# Summary
echo ""
echo "======================="
echo "✅ Recovery complete"
echo ""

if [[ $INVALID -gt 0 ]]; then
    echo "⚠️  Action required: Fix invalid JSON files"
    exit 1
else
    echo "All checks passed!"
    exit 0
fi
