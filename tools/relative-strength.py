#!/home/nicknemo17/clawd/venv/bin/python
"""
Relative Strength Rankings
Ranks all holdings by performance vs SPY over 1/4/12 week windows.

Posts weekly to #research (Friday after close).
Schedule: 4:45 PM EST Fridays

Methodology:
  - For each holding, compute return over 1W, 4W, 12W
  - Compute SPY return over same windows
  - Relative Strength = holding return - SPY return
  - Composite RS score = weighted average (1W: 20%, 4W: 40%, 12W: 40%)
  - Rank from strongest to weakest
  - Flag momentum shifts (RS improving or deteriorating)
"""

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf
import numpy as np

ET = ZoneInfo("America/New_York")
CLAWD = Path.home() / "clawd"
STATE_FILE = CLAWD / "memory/relative-strength-prev.json"

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

RESEARCH_CH = CHANNELS.get("DISCORD_RESEARCH", "1468773228791992494")


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


def flush_sends(timeout: int = 15):
    for proc in _pending_sends:
        try:
            proc.wait(timeout=timeout)
        except:
            pass
    _pending_sends.clear()


def compute_all_returns(tickers: list[str]) -> dict:
    """Batch-compute 1W, 4W, 12W returns for all tickers in one download."""
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)

    batch = yf.download(tickers, period="4mo", group_by="ticker", threads=True, progress=False)
    results = {}

    for ticker in tickers:
        try:
            if len(tickers) == 1:
                close = batch["Close"].dropna()
            else:
                close = batch[ticker]["Close"].dropna()

            if close.empty or len(close) < 10:
                continue

            price = close.iloc[-1]
            result = {"ticker": ticker, "price": round(float(price), 2)}

            if len(close) >= 6:
                result["ret_1w"] = round(float((price / close.iloc[-6] - 1) * 100), 2)
            else:
                result["ret_1w"] = 0.0

            if len(close) >= 21:
                result["ret_4w"] = round(float((price / close.iloc[-21] - 1) * 100), 2)
            else:
                result["ret_4w"] = result["ret_1w"]

            if len(close) >= 61:
                result["ret_12w"] = round(float((price / close.iloc[-61] - 1) * 100), 2)
            else:
                result["ret_12w"] = result["ret_4w"]

            results[ticker] = result
        except:
            continue

    return results


def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting relative strength rankings")

    # Load holdings
    with open(CLAWD / "memory/watchlist.json") as f:
        wl = json.load(f)
    holdings = {t: h for t, h in wl.get("stocks", {}).get("holdings", {}).items()
                if h.get("weight") and h["weight"] > 0}

    # Batch fetch all holdings + SPY in one request
    all_tickers = ["SPY"] + list(holdings.keys())
    all_returns = compute_all_returns(all_tickers)

    spy = all_returns.get("SPY")
    if not spy:
        print("Failed to fetch SPY data")
        return

    print(f"SPY: 1W={spy['ret_1w']:+.1f}% | 4W={spy['ret_4w']:+.1f}% | 12W={spy['ret_12w']:+.1f}%")

    # Compute RS for all holdings
    results = []
    for ticker in holdings:
        r = all_returns.get(ticker)
        if not r:
            continue

        # Relative strength vs SPY
        rs_1w = round(r["ret_1w"] - spy["ret_1w"], 2)
        rs_4w = round(r["ret_4w"] - spy["ret_4w"], 2)
        rs_12w = round(r["ret_12w"] - spy["ret_12w"], 2)

        # Composite score (weighted)
        composite = round(rs_1w * 0.20 + rs_4w * 0.40 + rs_12w * 0.40, 2)

        r["rs_1w"] = rs_1w
        r["rs_4w"] = rs_4w
        r["rs_12w"] = rs_12w
        r["composite"] = composite
        r["weight"] = holdings[ticker]["weight"]
        results.append(r)

    # Sort by composite RS
    results.sort(key=lambda x: x["composite"], reverse=True)

    # Load previous rankings for momentum shift detection
    prev_ranks = {}
    try:
        with open(STATE_FILE) as f:
            prev_data = json.load(f)
            prev_ranks = {r["ticker"]: i + 1 for i, r in enumerate(prev_data.get("rankings", []))}
    except:
        pass

    # Build message
    lines = [f"**Relative Strength Rankings** ({now_et.strftime('%a %b %d')})", ""]
    lines.append(f"Benchmark: SPY 1W={spy['ret_1w']:+.1f}% | 4W={spy['ret_4w']:+.1f}% | 12W={spy['ret_12w']:+.1f}%")
    lines.append("")
    lines.append("```")
    lines.append(f"{'#':>2} {'Ticker':<6} {'Wt%':>5} {'RS(C)':>7} {'1W':>7} {'4W':>7} {'12W':>7}  Shift")
    lines.append("-" * 60)

    for i, r in enumerate(results):
        rank = i + 1
        ticker = r["ticker"]

        # Momentum shift indicator
        prev_rank = prev_ranks.get(ticker)
        if prev_rank:
            shift = prev_rank - rank  # positive = improved
            if shift >= 3:
                shift_str = f"  +{shift}"
            elif shift <= -3:
                shift_str = f"  {shift}"
            elif shift > 0:
                shift_str = f"  +{shift}"
            elif shift < 0:
                shift_str = f"  {shift}"
            else:
                shift_str = "    ="
        else:
            shift_str = "  NEW"

        lines.append(
            f"{rank:>2} {ticker:<6} {r['weight']:>5.1f} {r['composite']:>+7.1f} "
            f"{r['rs_1w']:>+7.1f} {r['rs_4w']:>+7.1f} {r['rs_12w']:>+7.1f}{shift_str}"
        )

    lines.append("```")
    lines.append("")

    # Highlight leaders and laggards
    leaders = [r for r in results[:3] if r["composite"] > 0]
    laggards = [r for r in results[-3:] if r["composite"] < 0]

    if leaders:
        leader_str = ", ".join(f"{r['ticker']} ({r['composite']:+.1f})" for r in leaders)
        lines.append(f"Leaders: {leader_str}")
    if laggards:
        laggard_str = ", ".join(f"{r['ticker']} ({r['composite']:+.1f})" for r in laggards)
        lines.append(f"Laggards: {laggard_str}")

    # Big momentum shifts
    big_shifts = []
    for i, r in enumerate(results):
        prev_rank = prev_ranks.get(r["ticker"])
        if prev_rank:
            shift = prev_rank - (i + 1)
            if abs(shift) >= 4:
                direction = "improving" if shift > 0 else "weakening"
                big_shifts.append(f"{r['ticker']} ({direction}, moved {abs(shift)} spots)")

    if big_shifts:
        lines.append(f"Momentum shifts: {', '.join(big_shifts)}")

    message = "\n".join(lines)
    send_discord(RESEARCH_CH, message)
    print(f"Posted RS rankings ({len(message)} chars)")

    # Save current rankings for next week comparison
    save_data = {
        "date": now_et.strftime("%Y-%m-%d"),
        "rankings": [{"ticker": r["ticker"], "composite": r["composite"]} for r in results],
    }
    with open(STATE_FILE, "w") as f:
        json.dump(save_data, f, indent=2)

    # Popen sends complete independently after script exits
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} RS rankings complete")


if __name__ == "__main__":
    main()
