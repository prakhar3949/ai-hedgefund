#!/bin/bash
# Morning Pre-Market Briefing
# Posts comprehensive daily briefing to #research
# Schedule: 6:15 AM PST weekdays (9:15 AM EST, before market open)

set -euo pipefail

CLAWD_DIR="$HOME/clawd"
VENV="$CLAWD_DIR/venv/bin/python"
source "$CLAWD_DIR/tools/discord-channels.sh"

LOG="$CLAWD_DIR/logs/morning-briefing.log"
exec >> "$LOG" 2>&1
echo "$(date '+%Y-%m-%d %H:%M:%S') Starting morning briefing"

# ---- GATHER ALL DATA (Tier 1 — FREE) ----
BRIEFING=$("$VENV" << 'PYEOF'
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CLAWD = Path.home() / "clawd"
now_et = datetime.now(ET)

sections = []

# ── SECTION 1: Futures ──
try:
    import yfinance as yf
    futures = {"ES=F": "S&P", "NQ=F": "Nasdaq", "YM=F": "Dow", "RTY=F": "Russell"}
    lines = []
    for sym, name in futures.items():
        t = yf.Ticker(sym)
        fi = t.fast_info
        pct = ((fi.last_price / fi.previous_close) - 1) * 100
        arrow = "+" if pct >= 0 else ""
        lines.append(f"{name}: {arrow}{pct:.1f}%")

    # VIX
    vix = yf.Ticker("^VIX").fast_info.last_price
    lines.append(f"VIX: {vix:.1f}")

    sections.append("**Futures**\n" + "\n".join(lines))
except Exception as e:
    sections.append(f"**Futures**: Error - {e}")

# ── SECTION 2: Top Holdings Pre-Market ──
try:
    with open(CLAWD / "memory/watchlist.json") as f:
        wl = json.load(f)
    holdings = wl.get("stocks", {}).get("holdings", {})

    sorted_h = sorted(
        [(t, h) for t, h in holdings.items() if h.get("weight")],
        key=lambda x: x[1].get("weight", 0), reverse=True
    )

    lines = []
    total_day_pnl = 0
    for ticker, info in sorted_h[:8]:
        try:
            t = yf.Ticker(ticker)
            fi = t.fast_info
            pct = ((fi.last_price / fi.previous_close) - 1) * 100
            cost = info.get("costBasis", 0)
            shares = info.get("shares", 0)
            total_pct = ((fi.last_price / cost) - 1) * 100 if cost else 0

            if shares:
                total_day_pnl += (fi.last_price - fi.previous_close) * shares

            arrow = "+" if pct >= 0 else ""
            total_arrow = "+" if total_pct >= 0 else ""
            lines.append(
                f"{ticker} ({info['weight']}%): ${fi.last_price:.2f} "
                f"({arrow}{pct:.1f}% day, {total_arrow}{total_pct:.0f}% total)"
            )
        except:
            lines.append(f"{ticker} ({info.get('weight',0)}%): data unavailable")

    day_str = f"+${total_day_pnl:,.0f}" if total_day_pnl >= 0 else f"-${abs(total_day_pnl):,.0f}"
    sections.append(f"**Holdings** (est. day P&L: {day_str})\n" + "\n".join(lines))
except Exception as e:
    sections.append(f"**Holdings**: Error - {e}")

# ── SECTION 3: Earnings Today ──
try:
    today_str = now_et.strftime("%Y-%m-%d")
    with open(CLAWD / "memory/earnings-schedule.json") as f:
        sched = json.load(f)
    tickers = sched.get("by_date", {}).get(today_str, [])
    if not tickers:
        sections.append("**Earnings Today**: None scheduled")
    else:
        lines = []
        for t in tickers:
            weight = f" ({t['weight']}%)" if t.get("weight") else ""
            lines.append(f"{t['ticker']}{weight} - {t['timing']} ({t['category']})")
        sections.append("**Earnings Today**\n" + "\n".join(lines))
except Exception as e:
    sections.append(f"**Earnings Today**: Error loading schedule")

# ── SECTION 4: Macro Events Today ──
try:
    with open(CLAWD / "memory/macro-calendar.json") as f:
        macro = json.load(f)
    today_events = macro.get("events", {}).get(today_str, [])
    if today_events:
        lines = [f"{e['name']} ({e['impact']})" for e in today_events]
        sections.append("**Macro Events**\n" + "\n".join(lines))
except:
    pass  # Macro calendar may not exist yet

# ── SECTION 5: Crypto Overnight ──
try:
    crypto = {"BTC-USD": "BTC", "ETH-USD": "ETH", "SOL-USD": "SOL"}
    lines = []
    for sym, name in crypto.items():
        t = yf.Ticker(sym)
        fi = t.fast_info
        pct = ((fi.last_price / fi.previous_close) - 1) * 100
        arrow = "+" if pct >= 0 else ""
        price_fmt = f"${fi.last_price:,.0f}" if fi.last_price > 100 else f"${fi.last_price:.2f}"
        lines.append(f"{name}: {price_fmt} ({arrow}{pct:.1f}%)")
    sections.append("**Crypto**\n" + "\n".join(lines))
except:
    pass

# ── ASSEMBLE ──
header = f"**Morning Briefing** ({now_et.strftime('%a %b %d, %I:%M %p EST')})"
print(header + "\n\n" + "\n\n".join(sections))
PYEOF
)

if [ -z "$BRIEFING" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') Briefing generation failed"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') Briefing generated (${#BRIEFING} chars)"

# Post to #research
send_discord "$DISCORD_RESEARCH" "$BRIEFING"

echo "$(date '+%Y-%m-%d %H:%M:%S') Morning briefing posted"
