"""
Volatility Regime Indicator
Quantitative vol analysis: VIX percentile, realized vs implied vol gap, put/call proxy.

Posts daily to Discord via webhook.

Indicators:
  - VIX 1-year percentile rank
  - 20-day realized vol (SPY) vs VIX (implied vol gap)
  - Vol regime classification: LOW / NORMAL / ELEVATED / EXTREME
  - VVIX (vol of vol) if available — measures uncertainty about uncertainty

Cost: $0.00 (Yahoo Finance chart API, no key needed)
"""

import json
import requests
import numpy as np
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Use project directory as base
PROJECT_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

# Discord webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1470447471695102234/OdDlYvW9GeIE1v8Hmauq-jx13RQtyDS3KDoYMLNYkFZG1bCEzfYppLhg9Qpb9dzt_97P"


def send_discord(message: str):
    """Send message to Discord via webhook."""
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Send failed: {e}")


def fetch_closes(ticker: str, period: str = "1y") -> list[float]:
    """Fetch daily closes from Yahoo Finance chart API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval=1d"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"  {ticker}: HTTP {resp.status_code}")
            return []
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            print(f"  {ticker}: no data in response")
            return []
        closes = result[0]["indicators"]["quote"][0]["close"]
        return [c for c in closes if c is not None]
    except Exception as e:
        print(f"  {ticker}: fetch error: {e}")
        return []


def fetch_vol_data() -> tuple:
    """Fetch VIX + SPY + VVIX, compute all metrics."""
    import time

    # VIX percentile (1 year)
    vix_stats = None
    vix_close = fetch_closes("%5EVIX", "1y")
    time.sleep(0.3)
    if len(vix_close) >= 20:
        current = vix_close[-1]
        pct_rank = (sum(1 for v in vix_close if v < current) / len(vix_close)) * 100
        vix_stats = {
            "current": round(current, 2),
            "percentile": round(pct_rank, 0),
            "avg_1y": round(np.mean(vix_close), 1),
            "median_1y": round(float(np.median(vix_close)), 1),
            "min_1y": round(min(vix_close), 1),
            "max_1y": round(max(vix_close), 1),
            "std_1y": round(float(np.std(vix_close)), 1),
        }
        print(f"  VIX: {current:.2f} ({pct_rank:.0f}th percentile, {len(vix_close)} days)")

    # Realized vol from SPY
    rv_20d = rv_10d = None
    spy_close = fetch_closes("SPY", "3mo")
    time.sleep(0.3)
    if len(spy_close) >= 21:
        spy_arr = np.array(spy_close)
        returns = np.diff(np.log(spy_arr))
        if len(returns) >= 20:
            rv_20d = round(float(np.std(returns[-20:]) * np.sqrt(252) * 100), 1)
        if len(returns) >= 10:
            rv_10d = round(float(np.std(returns[-10:]) * np.sqrt(252) * 100), 1)
        print(f"  SPY RV: 20D={rv_20d}%, 10D={rv_10d}%")

    # VVIX
    vvix = None
    vvix_close = fetch_closes("%5EVVIX", "1mo")
    if vvix_close:
        vvix = round(vvix_close[-1], 1)
        print(f"  VVIX: {vvix}")

    return vix_stats, rv_20d, rv_10d, vvix


def classify_vol_regime(vix_pct: float, rv: float | None, vix_level: float) -> str:
    """Classify current vol regime."""
    if vix_level >= 30 or vix_pct >= 90:
        return "EXTREME"
    elif vix_level >= 22 or vix_pct >= 75:
        return "ELEVATED"
    elif vix_level <= 14 or vix_pct <= 15:
        return "LOW (COMPLACENT)"
    else:
        return "NORMAL"


def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting volatility regime analysis")

    # Fetch all vol data
    vix_stats, rv_20d, rv_10d, vvix = fetch_vol_data()
    if not vix_stats:
        print("Failed to fetch VIX data")
        return

    # Implied vs Realized gap
    iv_rv_gap = None
    if rv_20d:
        iv_rv_gap = round(vix_stats["current"] - rv_20d, 1)

    # Vol regime classification
    regime = classify_vol_regime(vix_stats["percentile"], rv_20d, vix_stats["current"])

    # Build dashboard message
    lines = [f"**Volatility Regime** ({now_et.strftime('%a %b %d')})", ""]

    # Regime badge
    regime_icon = {"LOW (COMPLACENT)": "[LOW]", "NORMAL": "[OK]", "ELEVATED": "[!!]", "EXTREME": "[!!!]"}
    lines.append(f"{regime_icon.get(regime, '[?]')} Vol Regime: **{regime}**")
    lines.append("")

    # VIX stats
    lines.append(f"**VIX** {vix_stats['current']:.1f} | Percentile: **{vix_stats['percentile']:.0f}%** (1Y)")
    lines.append(f"  Range: {vix_stats['min_1y']:.1f} - {vix_stats['max_1y']:.1f} | Avg: {vix_stats['avg_1y']:.1f} | Median: {vix_stats['median_1y']:.1f}")

    # Realized vol
    if rv_20d:
        lines.append(f"**Realized Vol** (SPY): 20D={rv_20d:.1f}%" + (f" | 10D={rv_10d:.1f}%" if rv_10d else ""))

    # IV-RV gap
    if iv_rv_gap is not None:
        gap_label = "premium" if iv_rv_gap > 0 else "discount"
        gap_icon = ">>>" if iv_rv_gap > 5 else "<<<" if iv_rv_gap < -3 else "---"
        lines.append(f"{gap_icon} **IV-RV Gap**: {iv_rv_gap:+.1f}% ({gap_label})")
        if iv_rv_gap > 8:
            lines.append("  (Large premium = market pricing in more risk than realized)")
        elif iv_rv_gap < -3:
            lines.append("  (Discount = realized vol exceeding expectations — surprise moves)")

    # VVIX
    if vvix:
        lines.append(f"**VVIX** (vol of vol): {vvix:.1f}")

    dashboard = "\n".join(lines)
    send_discord(dashboard)
    print(f"Posted volatility regime ({len(dashboard)} chars)")

    # Alert on extreme conditions
    alerts = []
    if regime == "EXTREME":
        alerts.append(f"Vol regime EXTREME — VIX at {vix_stats['current']:.1f} ({vix_stats['percentile']:.0f}th percentile)")
    if regime == "LOW (COMPLACENT)" and vix_stats["percentile"] <= 5:
        alerts.append(f"Vol regime EXTREMELY LOW — VIX at {vix_stats['current']:.1f} (bottom 5% of 1Y range). Complacency warning.")
    if iv_rv_gap and iv_rv_gap > 10:
        alerts.append(f"Massive IV premium ({iv_rv_gap:+.1f}%) — market pricing significant upcoming risk")
    if iv_rv_gap and iv_rv_gap < -5:
        alerts.append(f"IV discount ({iv_rv_gap:+.1f}%) — realized vol exceeding implied. Surprise moves happening.")

    if alerts:
        alert_lines = [f"**Volatility Alert** ({now_et.strftime('%a %b %d')})", ""]
        for a in alerts:
            alert_lines.append(f"- {a}")
        send_discord("\n".join(alert_lines))
        print(f"Posted {len(alerts)} vol alerts")

    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} Volatility regime complete")


if __name__ == "__main__":
    main()
