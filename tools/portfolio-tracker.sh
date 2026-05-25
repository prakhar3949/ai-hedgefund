#!/bin/bash
# Daily Portfolio P&L Tracker
# Posts end-of-day portfolio summary to #research
# Schedule: 1:15 PM PST weekdays (4:15 PM EST, after market close)

set -euo pipefail

CLAWD_DIR="$HOME/clawd"
VENV="$CLAWD_DIR/venv/bin/python"
source "$CLAWD_DIR/tools/discord-channels.sh"

LOG="$CLAWD_DIR/logs/portfolio-tracker.log"
exec >> "$LOG" 2>&1
echo "$(date '+%Y-%m-%d %H:%M:%S') Starting portfolio tracker"

MSG=$("$VENV" << 'PYEOF'
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CLAWD = Path.home() / "clawd"
now_et = datetime.now(ET)

import yfinance as yf

# Load data
with open(CLAWD / "memory/watchlist.json") as f:
    wl = json.load(f)
holdings = wl.get("stocks", {}).get("holdings", {})

with open(CLAWD / "memory/current-theses.json") as f:
    theses = json.load(f).get("theses", {})

# Sort by weight
sorted_h = sorted(
    [(t, h) for t, h in holdings.items() if h.get("weight") and h.get("shares")],
    key=lambda x: x[1].get("weight", 0), reverse=True
)

total_value = 0
total_cost = 0
total_day_pnl = 0
lines = []
winners = []
losers = []

for ticker, info in sorted_h:
    shares = info.get("shares", 0)
    cost_basis = info.get("costBasis", 0)
    if not shares or not cost_basis:
        continue

    try:
        t = yf.Ticker(ticker)
        fi = t.fast_info
        price = fi.last_price
        prev = fi.previous_close

        pos_value = price * shares
        pos_cost = cost_basis * shares
        day_change = (price - prev) * shares
        day_pct = ((price / prev) - 1) * 100
        total_pct = ((price / cost_basis) - 1) * 100

        total_value += pos_value
        total_cost += pos_cost
        total_day_pnl += day_change

        # Thesis status
        thesis = theses.get(ticker, {})
        status = thesis.get("status", "")
        status_short = {
            "HIGH_CONVICTION": "HC",
            "CONVICTION_BUY": "CB",
            "PATIENCE_HOLD": "PH",
            "SLEEPER_AWAKENING": "SA",
            "HELD": "HD",
        }.get(status, status[:2] if status else "--")

        arrow = "+" if day_pct >= 0 else ""
        total_arrow = "+" if total_pct >= 0 else ""

        line = (
            f"{ticker} ({info['weight']}%): ${price:.2f} "
            f"({arrow}{day_pct:.1f}% | {total_arrow}{total_pct:.0f}% total) "
            f"[{status_short}]"
        )
        lines.append(line)

        if day_pct >= 1.0:
            winners.append((ticker, day_pct))
        elif day_pct <= -1.0:
            losers.append((ticker, day_pct))

    except Exception as e:
        lines.append(f"{ticker}: Error - {e}")

# Summary
total_pnl_pct = ((total_value / total_cost) - 1) * 100 if total_cost else 0
day_str = f"+${total_day_pnl:,.0f}" if total_day_pnl >= 0 else f"-${abs(total_day_pnl):,.0f}"
total_str = f"+${total_value - total_cost:,.0f}" if total_value >= total_cost else f"-${abs(total_value - total_cost):,.0f}"

header = f"**Portfolio Close** ({now_et.strftime('%a %b %d')})"
summary = (
    f"**Total:** ${total_value:,.0f} ({total_str}, "
    f"{'+'if total_pnl_pct>=0 else ''}{total_pnl_pct:.1f}%)\n"
    f"**Today:** {day_str}"
)

# Movers
movers = ""
if winners:
    winners.sort(key=lambda x: x[1], reverse=True)
    w = ", ".join(f"{t} +{p:.1f}%" for t, p in winners[:3])
    movers += f"\nWinners: {w}"
if losers:
    losers.sort(key=lambda x: x[1])
    l = ", ".join(f"{t} {p:.1f}%" for t, p in losers[:3])
    movers += f"\nLosers: {l}"

msg = f"{header}\n\n{summary}{movers}\n\n" + "\n".join(lines)
print(msg)
PYEOF
)

if [ -z "$MSG" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') Portfolio tracker failed"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') Portfolio report generated (${#MSG} chars)"

send_discord "$DISCORD_RESEARCH" "$MSG"

echo "$(date '+%Y-%m-%d %H:%M:%S') Portfolio report posted"
