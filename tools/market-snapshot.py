#!/home/nicknemo17/clawd/venv/bin/python
"""
Hourly Market Snapshot — local replacement for Clawdbot job.
Posts market overview to Discord #market-dashboard every hour.

Uses batch yfinance download for efficiency.
Posts: indexes + all 11 sectors sorted by performance + regime context.

Schedule: hourly 9:00 AM - 4:00 PM ET weekdays (runs at top of hour)
Cost: $0.00 (Tier 1 — yfinance only, no LLM)
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

ET = ZoneInfo("America/New_York")
CLAWD = Path.home() / "clawd"

# Load channel IDs
CHANNELS = {}
try:
    with open(CLAWD / "tools/discord-channels.sh") as f:
        for line in f:
            if line.startswith("DISCORD_") and "=" in line:
                key, val = line.split("=", 1)
                val = val.strip()
                if val.startswith('"'):
                    val = val[1:val.index('"', 1)]
                else:
                    val = val.split()[0].split("#")[0].strip()
                CHANNELS[key.strip()] = val
except:
    pass

DASHBOARD_CH = CHANNELS.get("DISCORD_MARKET_DASHBOARD", "1468334675041976422")

_pending_sends = []


def send_discord(channel_id: str, message: str):
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        proc = subprocess.Popen(
            ["clawdbot", "message", "send",
             "--channel", "discord",
             "--target", f"channel:{channel_id}",
             "--message", message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _pending_sends.append(proc)
    except:
        pass


def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Market snapshot")

    # All tickers in one batch
    indexes = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000"}
    sectors = {
        "XLK": "Tech", "XLF": "Financials", "XLE": "Energy", "XLV": "Healthcare",
        "XLI": "Industrials", "XLC": "Comm Svcs", "XLY": "Cons Disc",
        "XLP": "Cons Staples", "XLU": "Utilities", "XLRE": "Real Estate", "XLB": "Materials",
    }

    all_tickers = list(indexes.keys()) + list(sectors.keys())
    batch = yf.download(all_tickers, period="2d", group_by="ticker",
                        threads=True, progress=False)

    # Compute daily % change
    results = {}
    for ticker in all_tickers:
        try:
            close = batch[ticker]["Close"].dropna()
            if len(close) >= 2:
                curr = close.iloc[-1]
                prev = close.iloc[-2]
                pct = (curr / prev - 1) * 100
                results[ticker] = {"price": curr, "pct": pct}
        except:
            continue

    if not results:
        print("ERROR: No data")
        return

    # Format message
    lines = [f"**Market Snapshot** ({now_et.strftime('%I:%M %p ET')})"]
    lines.append("")

    # Indexes
    for ticker, name in indexes.items():
        r = results.get(ticker)
        if r:
            arrow = "+" if r["pct"] > 0 else ""
            lines.append(f"**{name}** (${r['price']:.2f}): {arrow}{r['pct']:.1f}%")
    lines.append("")

    # Sectors sorted by performance
    sector_perf = []
    for ticker, name in sectors.items():
        r = results.get(ticker)
        if r:
            sector_perf.append((name, ticker, r["pct"]))
    sector_perf.sort(key=lambda x: x[2], reverse=True)

    # Top 3
    lines.append("**Leading:**")
    for name, ticker, pct in sector_perf[:3]:
        lines.append(f"  {name} ({ticker}): {pct:+.1f}%")

    # Bottom 3
    lines.append("**Lagging:**")
    for name, ticker, pct in sector_perf[-3:]:
        lines.append(f"  {name} ({ticker}): {pct:+.1f}%")

    # Add regime context if available
    try:
        with open(CLAWD / "memory/regime-state.json") as f:
            regime = json.load(f)
        vix = regime.get("vix_close")
        regime_label = regime.get("regime", "")
        if vix and regime_label:
            lines.append("")
            lines.append(f"Regime: {regime_label} | VIX: {vix:.1f}")
    except:
        pass

    message = "\n".join(lines)
    send_discord(DASHBOARD_CH, message)
    print(f"Posted snapshot ({len(message)} chars)")


if __name__ == "__main__":
    main()
