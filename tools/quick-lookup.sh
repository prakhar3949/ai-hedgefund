#!/bin/bash
# Quick Lookup - NO TOKENS NEEDED
# Usage: quick-lookup.sh [command] [args]

CLAWD_DIR="$HOME/clawd"
VENV="$CLAWD_DIR/venv/bin/python"

case "$1" in
    price|p)
        # Get stock price + market cap - NO TOKENS
        TICKER="${2:-SPY}"
        $VENV -c "
import yfinance as yf
t = yf.Ticker('$TICKER')
i = t.fast_info
info = t.info
prev = i.previous_close
curr = i.last_price
pct = ((curr/prev)-1)*100
cap = info.get('marketCap', 0)
if cap >= 1e12:
    cap_str = f'\${cap/1e12:.2f}T'
elif cap >= 1e9:
    cap_str = f'\${cap/1e9:.2f}B'
elif cap >= 1e6:
    cap_str = f'\${cap/1e6:.0f}M'
else:
    cap_str = 'N/A'
print(f'**$TICKER** \${curr:.2f} ({pct:+.1f}%) | MCap: {cap_str}')
"
        ;;

    thesis|t)
        # Get thesis - NO TOKENS
        TICKER="${2:-COHR}"
        $VENV -c "
import json
with open('$CLAWD_DIR/memory/current-theses.json') as f:
    data = json.load(f)
t = data.get('theses', {}).get('$TICKER', {})
if t:
    print(f\"**$TICKER** - {t.get('status', 'N/A')}\")
    print(f\"Thesis: {t.get('thesis', 'N/A')}\")
    print(f\"PT: {t.get('pt', 'N/A')}\")
    print(f\"Position: {t.get('position', 'N/A')}\")
else:
    print('No thesis found for $TICKER')
"
        ;;

    market|m)
        # Market snapshot - NO TOKENS
        $VENV -c "
import yfinance as yf
tickers = {'SPY': 'S&P 500', 'QQQ': 'Nasdaq', 'IWM': 'Russell'}
print('📊 **Market Snapshot**\n')
for sym, name in tickers.items():
    t = yf.Ticker(sym)
    i = t.fast_info
    pct = ((i.last_price/i.previous_close)-1)*100
    arrow = '🟢' if pct > 0 else '🔴'
    print(f'{arrow} {name}: \${i.last_price:.2f} ({pct:+.1f}%)')
"
        ;;

    sectors|s)
        # Sector performance - NO TOKENS
        $VENV -c "
import yfinance as yf
sectors = {'XLK':'Tech','XLF':'Fins','XLE':'Energy','XLV':'Health','XLI':'Indust','XLC':'Comm','XLY':'Disc','XLP':'Staples','XLU':'Utils','XLRE':'RE','XLB':'Matls'}
results = []
for sym, name in sectors.items():
    t = yf.Ticker(sym)
    i = t.fast_info
    pct = ((i.last_price/i.previous_close)-1)*100
    results.append((pct, name, sym))
results.sort(reverse=True)
print('📈 **Best Sectors**')
for pct, name, sym in results[:3]:
    print(f'🟢 {name} ({sym}): {pct:+.1f}%')
print('\n📉 **Worst Sectors**')
for pct, name, sym in results[-3:]:
    print(f'🔴 {name} ({sym}): {pct:+.1f}%')
"
        ;;

    holdings|h)
        # Holdings performance - NO TOKENS
        $VENV -c "
import yfinance as yf
import json
with open('$CLAWD_DIR/memory/current-theses.json') as f:
    data = json.load(f)
tickers = [t for t in data.get('theses', {}).keys() if t not in ['MACRO', '_VERIFICATION_WARNING', '_MANDATORY_TOOLS']]
print('📊 **Holdings**\n')
for sym in tickers[:10]:
    try:
        t = yf.Ticker(sym)
        i = t.fast_info
        pct = ((i.last_price/i.previous_close)-1)*100
        arrow = '🟢' if pct > 0 else '🔴' if pct < 0 else '⚪'
        print(f'{arrow} {sym}: \${i.last_price:.2f} ({pct:+.1f}%)')
    except:
        pass
"
        ;;

    faq|f)
        # FAQ lookup - NO TOKENS
        QUERY="${2:-help}"
        grep -i "$QUERY" "$CLAWD_DIR/tools/FAQ.md" 2>/dev/null || echo "No FAQ match for: $QUERY"
        ;;

    info|i)
        # Full stock info - NO TOKENS
        TICKER="${2:-SPY}"
        $VENV -c "
import yfinance as yf
t = yf.Ticker('$TICKER')
i = t.fast_info
info = t.info

# Price
prev = i.previous_close
curr = i.last_price
pct = ((curr/prev)-1)*100

# Market cap
cap = info.get('marketCap', 0)
if cap >= 1e12:
    cap_str = f'\${cap/1e12:.2f}T'
elif cap >= 1e9:
    cap_str = f'\${cap/1e9:.2f}B'
elif cap >= 1e6:
    cap_str = f'\${cap/1e6:.0f}M'
else:
    cap_str = 'N/A'

# Other metrics
fpe = info.get('forwardPE', 'N/A')
if fpe != 'N/A':
    fpe = f'{fpe:.1f}x'
beta = info.get('beta', 'N/A')
if beta != 'N/A':
    beta = f'{beta:.2f}'
high52 = info.get('fiftyTwoWeekHigh', 0)
low52 = info.get('fiftyTwoWeekLow', 0)
ma50 = info.get('fiftyDayAverage', 0)
ma200 = info.get('twoHundredDayAverage', 0)

print(f'**$TICKER**')
print(f'Price: \${curr:.2f} ({pct:+.1f}%)')
print(f'MCap: {cap_str}')
print(f'Forward P/E: {fpe}')
print(f'Beta: {beta}')
print(f'52w Range: \${low52:.2f} - \${high52:.2f}')
print(f'50d MA: \${ma50:.2f} | 200d MA: \${ma200:.2f}')
vs50 = ((curr/ma50)-1)*100 if ma50 else 0
vs200 = ((curr/ma200)-1)*100 if ma200 else 0
print(f'vs MAs: 50d {vs50:+.1f}% | 200d {vs200:+.1f}%')
"
        ;;

    *)
        echo "Quick Lookup - Zero Token Usage"
        echo ""
        echo "Commands:"
        echo "  price [TICKER]  - Price + market cap"
        echo "  info [TICKER]   - Full info (PE, beta, MAs, 52w)"
        echo "  thesis [TICKER] - Investment thesis"
        echo "  market          - SPY/QQQ/IWM snapshot"
        echo "  sectors         - Best/worst sectors"
        echo "  holdings        - All holdings prices"
        echo "  faq [query]     - Search FAQ"
        ;;
esac
