#!/bin/bash
# Thesis Monitor — checks portfolio for thesis-breaking events
# Schedule: 1:30 PM PST weekdays (after portfolio tracker)
# Checks: price target hits, >15% drawdowns, 52w lows, abnormal volume
# Only invokes Dexter (costs tokens) when a trigger fires.
# Zero LLM cost on quiet days.

set -euo pipefail

CLAWD_DIR="$HOME/clawd"
VENV="$CLAWD_DIR/venv/bin/python"
source "$CLAWD_DIR/tools/discord-channels.sh"

LOG="$CLAWD_DIR/logs/thesis-monitor.log"
exec >> "$LOG" 2>&1
echo "$(date '+%Y-%m-%d %H:%M:%S') Starting thesis monitor"

# Check for triggers (Tier 1 — FREE)
TRIGGERS=$("$VENV" << 'PYEOF'
import json
from pathlib import Path

CLAWD = Path.home() / "clawd"

import yfinance as yf

with open(CLAWD / "memory/watchlist.json") as f:
    wl = json.load(f)
holdings = wl.get("stocks", {}).get("holdings", {})

with open(CLAWD / "memory/current-theses.json") as f:
    theses = json.load(f).get("theses", {})

triggers = []

for ticker, info in holdings.items():
    if not info.get("weight"):
        continue

    thesis = theses.get(ticker, {})
    if not thesis:
        continue

    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        hist = t.history(period="3mo")

        price = fi.last_price
        prev_close = fi.previous_close
        day_pct = ((price / prev_close) - 1) * 100
        volume = fi.last_volume

        # Calculate metrics
        high_3m = hist["High"].max() if not hist.empty else price
        low_52w = fi.year_low if hasattr(fi, "year_low") else hist["Low"].min()
        avg_vol = hist["Volume"].rolling(20).mean().iloc[-1] if len(hist) >= 20 else volume

        # Check triggers
        reasons = []

        # 1. Price target hit (if thesis has a price target)
        pt = thesis.get("priceTarget")
        if pt and price >= pt:
            reasons.append(f"PRICE TARGET HIT: ${price:.2f} >= ${pt} target")

        # 2. Large drawdown from recent high
        if high_3m > 0:
            drawdown = ((price / high_3m) - 1) * 100
            if drawdown <= -15:
                reasons.append(f"DRAWDOWN: {drawdown:.1f}% from 3-month high (${high_3m:.2f})")

        # 3. Near 52-week low (within 5%)
        if low_52w > 0 and price > 0:
            dist_from_low = ((price / low_52w) - 1) * 100
            if dist_from_low <= 5:
                reasons.append(f"NEAR 52W LOW: ${price:.2f} vs ${low_52w:.2f} low ({dist_from_low:.1f}% above)")

        # 4. Abnormal volume (>3x average)
        if avg_vol > 0 and volume > avg_vol * 3:
            vol_ratio = volume / avg_vol
            reasons.append(f"VOLUME SPIKE: {vol_ratio:.1f}x average ({volume:,.0f} vs {avg_vol:,.0f} avg)")

        # 5. Big daily move (>5% either direction)
        if abs(day_pct) >= 5:
            direction = "UP" if day_pct > 0 else "DOWN"
            reasons.append(f"BIG MOVE {direction}: {day_pct:+.1f}% today")

        if reasons:
            triggers.append({
                "ticker": ticker,
                "price": round(price, 2),
                "weight": info.get("weight", 0),
                "status": thesis.get("status", "N/A"),
                "reasons": reasons,
                "thesis_summary": thesis.get("thesis", thesis.get("summary", ""))[:200],
            })

    except Exception as e:
        continue

# Output triggers as JSON
if triggers:
    print(json.dumps(triggers))
PYEOF
)

if [ -z "$TRIGGERS" ] || [ "$TRIGGERS" = "null" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') No thesis triggers today"
    exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') Triggers detected: $TRIGGERS"

# Process each trigger
"$VENV" -c "
import json, subprocess, os

triggers = json.loads('''$TRIGGERS''')

CLAWD = '$CLAWD_DIR'
DEXTER_RUN = f'{CLAWD}/tools/dexter-run.sh'

for t in triggers:
    ticker = t['ticker']
    reasons = '; '.join(t['reasons'])
    weight = t['weight']
    status = t['status']

    # Post immediate alert to #trade-alerts (free, no LLM)
    alert = f\"\"\"**Thesis Alert: {ticker}** ({weight}% | {status})

{chr(10).join('- ' + r for r in t['reasons'])}

Price: \${t['price']}\"\"\"

    subprocess.run([
        'clawdbot', 'message', 'send',
        '--channel', 'discord',
        '--target', 'channel:$DISCORD_TRADE_ALERTS',
        '--message', alert[:1950],
    ], capture_output=True, timeout=30)

    # For holdings with significant triggers, spawn Dexter for quick validation
    significant = any(
        'DRAWDOWN' in r or 'PRICE TARGET' in r or '52W LOW' in r
        for r in t['reasons']
    )

    if significant and weight and float(weight) >= 5:
        query = (
            f'Quick thesis check for {ticker} (current: \${t[\"price\"]}). '
            f'Trigger: {reasons}. '
            f'Thesis [{status}]: {t[\"thesis_summary\"]}. '
            f'In 3-4 sentences: is the thesis still intact? What should we watch?'
        )

        env = os.environ.copy()
        env['PATH'] = f'{os.path.expanduser(\"~\")}/.bun/bin:' + env.get('PATH', '')

        subprocess.Popen(
            [DEXTER_RUN, 'query', '--model', 'claude-sonnet-4-20250514',
             '--max-iterations', '3', query],
            stdout=open(f'{CLAWD}/logs/thesis-dexter-{ticker}.txt', 'w'),
            stderr=subprocess.DEVNULL,
            env=env,
        )
        print(f'Spawned Dexter thesis check for {ticker}')
" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') Thesis monitor complete"
