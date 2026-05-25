#!/bin/bash
# Morning Digest - Consolidated morning update
# Usage: ~/clawd/skills/morning-digest.sh

cd ~/clawd

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              📊 MORNING DIGEST $(date +%Y-%m-%d)                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📈 STOCK MARKET - Holdings & Watchlist"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f ./venv/bin/python ] && [ -f tools/stock-monitor-yfinance.py ]; then
    ./venv/bin/python tools/stock-monitor-yfinance.py --holdings 2>/dev/null || echo "❌ Stock monitor failed"
else
    echo "⚠️  Stock monitor not configured"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📅 CALENDAR - Both Accounts"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f tools/gmail-multi-account.js ]; then
    node tools/gmail-multi-account.js calendar all 2>/dev/null || echo "❌ Calendar check failed"
else
    echo "⚠️  Gmail multi-account not configured"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📰 SUBSTACK - Last 24 Hours"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f tools/substack-monitor.js ]; then
    node tools/substack-monitor.js 2>/dev/null || echo "❌ Substack monitor failed"
else
    echo "⚠️  Substack monitor not configured"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🐦 TWITTER - Top 20 Timeline"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f tools/twitter-monitor.sh ]; then
    ./tools/twitter-monitor.sh home -n 20 2>/dev/null | head -50 || echo "❌ Twitter monitor failed"
else
    echo "⚠️  Twitter monitor not configured"
fi
echo ""

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    ✅ Digest Complete                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
