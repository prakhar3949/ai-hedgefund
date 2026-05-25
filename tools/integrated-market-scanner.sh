#!/bin/bash

#
# INTEGRATED MARKET SCANNER
# Combines sentiment analysis + retail vulnerability scanning
# For comprehensive short opportunity identification
#

set -e

TOOLS_DIR="$HOME/clawd/tools"
OUTPUT_DIR="$HOME/clawd/output"
DATE=$(date +%Y%m%d-%H%M)

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "════════════════════════════════════════════════════════════════"
echo -e "${BLUE}  INTEGRATED MARKET SCANNER${NC}"
echo -e "  $(date '+%B %d, %Y @ %H:%M %Z')"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

# ==============================================================================
# PART 1: SENTIMENT ANALYSIS
# ==============================================================================

echo -e "${YELLOW}[1/2] Running Sentiment Screener...${NC}"
echo "  Analyzing Substack + Twitter for financial signals..."
echo ""

SENTIMENT_OUTPUT="$OUTPUT_DIR/sentiment-$DATE.json"

if timeout 90 "$TOOLS_DIR/sentiment-screener.js" > "$SENTIMENT_OUTPUT" 2>/tmp/sentiment-stderr.txt; then
    echo -e "${GREEN}✓ Sentiment analysis complete${NC}"
    
    # Parse key metrics
    TOTAL_SIGNALS=$(cat "$SENTIMENT_OUTPUT" | node -e "console.log(JSON.parse(require('fs').readFileSync(0)).summary.total)")
    URGENT=$(cat "$SENTIMENT_OUTPUT" | node -e "console.log(JSON.parse(require('fs').readFileSync(0)).summary.byPriority.urgent)")
    HIGH=$(cat "$SENTIMENT_OUTPUT" | node -e "console.log(JSON.parse(require('fs').readFileSync(0)).summary.byPriority.high)")
    
    echo "  📊 Signals: $TOTAL_SIGNALS total (🚨 $URGENT urgent, 🔴 $HIGH high)"
    
    # Show urgent signals
    if [ "$URGENT" -gt 0 ]; then
        echo ""
        echo -e "${RED}  🚨 URGENT SIGNALS:${NC}"
        cat /tmp/sentiment-stderr.txt | grep -A 15 "URGENT PRIORITY" | head -20 | sed 's/^/  /'
    fi
else
    echo -e "${RED}✗ Sentiment analysis failed or timed out${NC}"
    SENTIMENT_OUTPUT=""
fi

echo ""
echo "────────────────────────────────────────────────────────────────"
echo ""

# ==============================================================================
# PART 2: RETAIL VULNERABILITY SCAN
# ==============================================================================

echo -e "${YELLOW}[2/2] Running Retail Vulnerability Scanner...${NC}"
echo "  Identifying overbought retail-loved stocks..."
echo ""

RETAIL_OUTPUT="$OUTPUT_DIR/retail-$DATE.json"

if timeout 120 "$TOOLS_DIR/retail-vulnerability-scanner.js" > "$RETAIL_OUTPUT" 2>/tmp/retail-stderr.txt; then
    echo -e "${GREEN}✓ Retail vulnerability scan complete${NC}"
    
    # Parse key metrics
    ANALYZED=$(cat "$RETAIL_OUTPUT" | node -e "console.log(JSON.parse(require('fs').readFileSync(0)).summary.totalAnalyzed)")
    VULNERABLE=$(cat "$RETAIL_OUTPUT" | node -e "console.log(JSON.parse(require('fs').readFileSync(0)).summary.vulnerableTargets)")
    
    echo "  🎯 Analyzed: $ANALYZED stocks ($VULNERABLE vulnerable targets)"
    
    # Show top 3 candidates
    echo ""
    echo -e "${RED}  📉 TOP SHORT CANDIDATES:${NC}"
    cat /tmp/retail-stderr.txt | grep -A 25 "TOP SHORT CANDIDATES" | head -30 | sed 's/^/  /'
else
    echo -e "${RED}✗ Retail vulnerability scan failed or timed out${NC}"
    RETAIL_OUTPUT=""
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""

# ==============================================================================
# PART 3: CROSS-ANALYSIS
# ==============================================================================

if [ -n "$SENTIMENT_OUTPUT" ] && [ -n "$RETAIL_OUTPUT" ]; then
    echo -e "${YELLOW}[Bonus] Cross-Analysis: Sentiment × Vulnerability${NC}"
    echo "  Finding stocks with BOTH bearish sentiment AND high vulnerability..."
    echo ""
    
    # Extract tickers from both sources
    SENTIMENT_BEARISH=$(cat "$SENTIMENT_OUTPUT" | node -e "
        const data = JSON.parse(require('fs').readFileSync(0));
        const bearish = data.signals
            .filter(s => s.sentiment.overall === 'bearish' && s.priority !== 'low')
            .flatMap(s => s.mentions.stocks);
        console.log(JSON.stringify([...new Set(bearish)]));
    ")
    
    VULNERABLE_TICKERS=$(cat "$RETAIL_OUTPUT" | node -e "
        const data = JSON.parse(require('fs').readFileSync(0));
        const vulnerable = data.topCandidates
            .filter(c => c.vulnerabilityScore >= 70)
            .map(c => c.ticker);
        console.log(JSON.stringify(vulnerable));
    ")
    
    # Find intersection
    OVERLAP=$(node -e "
        const bearish = $SENTIMENT_BEARISH;
        const vulnerable = $VULNERABLE_TICKERS;
        const overlap = bearish.filter(t => vulnerable.includes(t));
        if (overlap.length > 0) {
            console.log('${GREEN}✓ CONVERGENCE DETECTED${NC}');
            console.log('  Stocks with bearish sentiment AND high vulnerability:');
            overlap.forEach(t => console.log('    • ' + t + ' (HIGH CONVICTION SHORT)'));
        } else {
            console.log('${YELLOW}• No direct overlap${NC}');
            console.log('  Bearish sentiment: ' + bearish.join(', '));
            console.log('  Vulnerable: ' + vulnerable.slice(0, 5).join(', '));
        }
    " 2>/dev/null || echo -e "${YELLOW}  • Analysis complete (check individual reports)${NC}")
    
    echo "$OVERLAP"
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""

# ==============================================================================
# SUMMARY & OUTPUT
# ==============================================================================

echo -e "${BLUE}📂 OUTPUT FILES:${NC}"

if [ -n "$SENTIMENT_OUTPUT" ]; then
    SIZE=$(ls -lh "$SENTIMENT_OUTPUT" | awk '{print $5}')
    echo "  ✓ Sentiment: $SENTIMENT_OUTPUT ($SIZE)"
fi

if [ -n "$RETAIL_OUTPUT" ]; then
    SIZE=$(ls -lh "$RETAIL_OUTPUT" | awk '{print $5}')
    echo "  ✓ Retail Vulnerability: $RETAIL_OUTPUT ($SIZE)"
fi

echo ""
echo -e "${BLUE}📋 NEXT STEPS:${NC}"
echo "  1. Review urgent sentiment signals (high-priority alerts)"
echo "  2. Check top short candidates (vulnerability >75)"
echo "  3. Look for convergence (bearish sentiment + high vulnerability)"
echo "  4. Cross-reference with price action (stock-monitor)"
echo "  5. Size positions appropriately and set stops"
echo ""

echo "════════════════════════════════════════════════════════════════"
echo -e "${GREEN}✓ SCAN COMPLETE${NC}"
echo "════════════════════════════════════════════════════════════════"
