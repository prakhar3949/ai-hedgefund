#!/home/nicknemo17/clawd/venv/bin/python
"""
Recency-Weighted Correlation Matrix
Computes exponentially-weighted correlations between indexes (SPY/QQQ/IWM)
and macro variables + sector ETFs.

Recency weighting: halflife=21 trading days (1 month).
Data from 21 days ago carries half the weight of today's data.
Older data decays exponentially — captures regime shifts faster than equal-weight.

Posts to #econometrics.
Schedule: 4:55 PM EST Fridays (after sector rotation)

Cost: $0.00 (Tier 1 — yfinance only, no LLM)
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import yfinance as yf

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

ECON_CH = CHANNELS.get("DISCORD_ECONOMETRICS", "1469851672577704211")

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


# ─── ASSET DEFINITIONS ───────────────────────────────────────────

INDEXES = ["SPY", "QQQ", "IWM"]

MACRO_VARS = {
    "^VIX":      "VIX",
    "^TNX":      "10Y Yield",
    "DX-Y.NYB":  "Dollar",
    "TLT":       "LT Treas",
    "HYG":       "HY Credit",
    "GLD":       "Gold",
    "USO":       "Oil",
}

SECTORS = {
    "XLK": "Tech",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLC": "Comm Svcs",
    "XLY": "Cons Disc",
    "XLP": "Cons Staples",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLB": "Materials",
}


def fetch_returns(tickers: list[str], period: str = "1y") -> dict:
    """Batch-download and compute daily returns for all tickers."""
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)

    batch = yf.download(tickers, period=period, group_by="ticker", threads=True, progress=False)
    returns = {}
    for ticker in tickers:
        try:
            if len(tickers) == 1:
                close = batch["Close"]
            else:
                close = batch[ticker]["Close"]
            close = close.dropna()
            if len(close) >= 60:
                returns[ticker] = close.pct_change().dropna()
        except:
            continue
    return returns


def ewm_correlation(returns_x, returns_y, halflife: int = 21) -> float:
    """Compute exponentially-weighted correlation between two return series."""
    import pandas as pd
    # Align series
    df = pd.DataFrame({"x": returns_x, "y": returns_y}).dropna()
    if len(df) < 30:
        return np.nan

    # EWM covariance and variances
    ewm = df.ewm(halflife=halflife)
    cov_matrix = ewm.cov()

    # Extract final covariance values
    last_idx = df.index[-1]
    cov_xy = cov_matrix.loc[(last_idx, "x"), "y"]
    var_x = cov_matrix.loc[(last_idx, "x"), "x"]
    var_y = cov_matrix.loc[(last_idx, "y"), "y"]

    if var_x <= 0 or var_y <= 0:
        return np.nan
    return cov_xy / np.sqrt(var_x * var_y)


def corr_bar(val: float) -> str:
    """Visual bar for correlation strength."""
    if np.isnan(val):
        return "  ---  "
    abs_val = abs(val)
    if abs_val >= 0.7:
        blocks = 5
    elif abs_val >= 0.5:
        blocks = 4
    elif abs_val >= 0.3:
        blocks = 3
    elif abs_val >= 0.15:
        blocks = 2
    else:
        blocks = 1
    bar = "#" * blocks + " " * (5 - blocks)
    sign = "+" if val >= 0 else "-"
    return f"{sign}[{bar}]"


def main():
    import pandas as pd
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting correlation matrix")

    # Fetch all returns in one batch
    all_tickers = INDEXES + list(MACRO_VARS.keys()) + list(SECTORS.keys())
    print(f"Fetching {len(all_tickers)} tickers...")
    returns = fetch_returns(all_tickers)
    print(f"Got returns for {len(returns)} tickers")

    if not any(t in returns for t in INDEXES):
        print("ERROR: No index data")
        return

    halflife = 21  # 1 month — data from 21 trading days ago has half the weight

    # ── Compute correlations: Indexes vs Macro Variables ──
    macro_corrs = {}  # {index: [(label, ticker, corr), ...]}
    for idx in INDEXES:
        if idx not in returns:
            continue
        corrs = []
        for ticker, label in MACRO_VARS.items():
            if ticker not in returns:
                continue
            r = ewm_correlation(returns[idx], returns[ticker], halflife)
            corrs.append((label, ticker, r))
        corrs.sort(key=lambda x: abs(x[2]) if not np.isnan(x[2]) else 0, reverse=True)
        macro_corrs[idx] = corrs

    # ── Compute correlations: Indexes vs Sectors ──
    sector_corrs = {}
    for idx in INDEXES:
        if idx not in returns:
            continue
        corrs = []
        for ticker, label in SECTORS.items():
            if ticker not in returns:
                continue
            r = ewm_correlation(returns[idx], returns[ticker], halflife)
            corrs.append((label, ticker, r))
        corrs.sort(key=lambda x: x[2] if not np.isnan(x[2]) else 0, reverse=True)
        sector_corrs[idx] = corrs

    # ── Format: Macro Correlations ──
    lines = [f"**Correlation Matrix** ({now_et.strftime('%a %b %d')}) | halflife={halflife}d", ""]
    lines.append("**Indexes vs Macro Variables** (sorted by strength)")
    lines.append("```")

    # Header
    idx_labels = [idx for idx in INDEXES if idx in macro_corrs]
    header = f"{'Variable':<12}" + "".join(f"{idx:>10}" for idx in idx_labels)
    lines.append(header)
    lines.append("-" * len(header))

    # Collect all macro vars, sort by average absolute correlation
    all_macro = {}
    for ticker, label in MACRO_VARS.items():
        vals = []
        for idx in idx_labels:
            for lbl, tk, r in macro_corrs.get(idx, []):
                if tk == ticker:
                    vals.append(r)
        if vals:
            all_macro[ticker] = (label, vals, np.nanmean([abs(v) for v in vals]))

    for ticker, (label, _, avg) in sorted(all_macro.items(), key=lambda x: x[1][2], reverse=True):
        row = f"{label:<12}"
        for idx in idx_labels:
            val = np.nan
            for lbl, tk, r in macro_corrs.get(idx, []):
                if tk == ticker:
                    val = r
                    break
            if np.isnan(val):
                row += f"{'N/A':>10}"
            else:
                row += f"{val:>+10.2f}"
        lines.append(row)

    lines.append("```")
    lines.append("")

    # ── Format: Sector Correlations ──
    lines.append("**Indexes vs Sectors** (sorted by SPY corr)")
    lines.append("```")

    header2 = f"{'Sector':<14}" + "".join(f"{idx:>10}" for idx in idx_labels)
    lines.append(header2)
    lines.append("-" * len(header2))

    # Sort sectors by SPY correlation
    spy_sector_order = []
    for ticker, label in SECTORS.items():
        spy_r = np.nan
        for lbl, tk, r in sector_corrs.get("SPY", []):
            if tk == ticker:
                spy_r = r
                break
        spy_sector_order.append((ticker, label, spy_r))
    spy_sector_order.sort(key=lambda x: x[2] if not np.isnan(x[2]) else 0, reverse=True)

    for ticker, label, _ in spy_sector_order:
        row = f"{label:<14}"
        for idx in idx_labels:
            val = np.nan
            for lbl, tk, r in sector_corrs.get(idx, []):
                if tk == ticker:
                    val = r
                    break
            if np.isnan(val):
                row += f"{'N/A':>10}"
            else:
                row += f"{val:>+10.2f}"
        lines.append(row)

    lines.append("```")
    lines.append("")

    # ── Insights: Notable correlations ──
    insights = []
    for idx in idx_labels:
        for label, ticker, r in macro_corrs.get(idx, []):
            if not np.isnan(r) and abs(r) >= 0.6:
                direction = "positively" if r > 0 else "inversely"
                insights.append(f"{idx} strongly {direction} correlated with {label} ({r:+.2f})")

    # Sector divergences: sectors with very different QQQ vs IWM correlations
    if "QQQ" in sector_corrs and "IWM" in sector_corrs:
        qqq_map = {tk: r for _, tk, r in sector_corrs["QQQ"]}
        iwm_map = {tk: r for _, tk, r in sector_corrs["IWM"]}
        for ticker, label in SECTORS.items():
            q = qqq_map.get(ticker, np.nan)
            i = iwm_map.get(ticker, np.nan)
            if not np.isnan(q) and not np.isnan(i) and abs(q - i) >= 0.15:
                leader = "QQQ" if q > i else "IWM"
                insights.append(f"{label} tilts toward {leader} (QQQ:{q:+.2f} vs IWM:{i:+.2f})")

    if insights:
        lines.append("**Notable:**")
        for insight in insights[:8]:
            lines.append(f"- {insight}")

    message = "\n".join(lines)

    # May need to split if too long
    if len(message) > 1950:
        # Split into macro + sector messages
        macro_end = message.index("**Indexes vs Sectors**")
        send_discord(ECON_CH, message[:macro_end].strip())
        send_discord(ECON_CH, message[macro_end:].strip())
    else:
        send_discord(ECON_CH, message)

    print(f"Posted correlation matrix ({len(message)} chars)")

    # Popen sends complete independently after script exits
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Correlation matrix complete")


if __name__ == "__main__":
    main()
