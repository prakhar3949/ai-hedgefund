#!/bin/bash
# Thesis Query Skill
# Usage: thesis-query.sh "TICKER" or thesis-query.sh "question"

THESIS_FILE="$HOME/clawd/memory/current-theses.json"
DEV_FILE="$HOME/clawd/THESIS-DEVELOPMENT.md"

query="$1"
ticker=$(echo "$query" | grep -oE '\b(COHR|AMD|CMI|XNET|KSPI|JFIN|FJET|LITE|RAIL)\b' | head -1)

if [ -z "$ticker" ]; then
    echo "No ticker found in query. Supported: COHR, AMD, CMI, XNET, KSPI, JFIN, FJET, LITE, RAIL"
    exit 1
fi

echo "=== $ticker Thesis ==="
echo ""

# Extract thesis from JSON
python3 << EOF
import json

with open("$THESIS_FILE") as f:
    data = json.load(f)

thesis = data.get("theses", {}).get("$ticker", {})
if thesis:
    print(f"Position: {thesis.get('position', 'N/A')}")
    print(f"Thesis: {thesis.get('thesis', 'N/A')}")
    print(f"PT: {thesis.get('pt', 'N/A')}")
    print(f"Status: {thesis.get('status', 'N/A')}")
    print(f"\nKey Points:")
    for point in thesis.get('key_points', []):
        print(f"  • {point}")
else:
    print("No thesis found for $ticker")
EOF

echo ""
echo "=== News Instructions ==="
python3 << EOF
import json

with open("$THESIS_FILE") as f:
    data = json.load(f)

instructions = data.get("news_instructions", {})
for key, val in instructions.items():
    if "$ticker" in key.upper():
        print(f"{val}")
EOF
