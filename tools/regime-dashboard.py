#!/home/nicknemo17/clawd/venv/bin/python
"""
Cross-Asset Regime Dashboard
Tracks macro regime via VIX term structure, yields, credit spreads, dollar, and treasuries.

Posts daily to #market-dashboard. Alerts #trade-alerts on regime flips.
Schedule: 4:35 PM EST weekdays (after technicals scanner)

Assets tracked:
  - VIX spot (^VIX) vs 3-month VIX (^VIX3M) → term structure
  - 10Y yield (^TNX)
  - US Dollar Index (DX-Y.NYB)
  - Credit: HYG (high yield) vs LQD (investment grade) → spread proxy
  - TLT (20+ year treasuries)
  - Gold (GLD) as risk barometer

Regime signals:
  - VIX term structure flip (contango → backwardation = stress)
  - VIX spike above 25 / above 30
  - Credit spread widening (HYG underperforming LQD)
  - Yield curve moves (TNX direction + magnitude)
  - Dollar breakout/breakdown
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
STATE_FILE = CLAWD / "memory/regime-state.json"

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


def flush_sends(timeout: int = 15):
    for proc in _pending_sends:
        try:
            proc.wait(timeout=timeout)
        except:
            pass
    _pending_sends.clear()


def load_prev_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {}


def save_state(state: dict):
    state["updated"] = datetime.now(ET).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_all_assets(tickers: list[str], period: str = "6mo") -> dict:
    """Batch-fetch price data for all assets in a single HTTP request."""
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)

    batch = yf.download(tickers, period=period, group_by="ticker", threads=True, progress=False)
    results = {}

    for ticker in tickers:
        try:
            if len(tickers) == 1:
                close = batch["Close"].dropna()
            else:
                close = batch[ticker]["Close"].dropna()

            if close.empty or len(close) < 5:
                continue

            price = close.iloc[-1]
            prev = close.iloc[-2]
            daily_chg = ((price - prev) / prev) * 100
            week_chg = ((price - close.iloc[-5]) / close.iloc[-5]) * 100 if len(close) >= 5 else 0

            last_20 = close.tail(20)
            pct_rank = ((last_20 < price).sum() / len(last_20)) * 100
            yr_rank = ((close < price).sum() / len(close)) * 100

            results[ticker] = {
                "ticker": ticker,
                "price": round(float(price), 2),
                "daily_chg": round(float(daily_chg), 2),
                "week_chg": round(float(week_chg), 2),
                "pct_rank_20d": round(float(pct_rank), 0),
                "pct_rank_yr": round(float(yr_rank), 0),
                "high_52w": round(float(close.max()), 2),
                "low_52w": round(float(close.min()), 2),
            }
        except Exception as e:
            print(f"  Error processing {ticker}: {e}")

    return results


def compute_vix_term_structure(vix_data: dict | None, vix3m_data: dict | None) -> dict:
    """Analyze VIX term structure."""
    if not vix_data or not vix3m_data:
        return {"structure": "unknown", "ratio": None}

    ratio = vix_data["price"] / vix3m_data["price"]
    if ratio > 1.0:
        structure = "BACKWARDATION"  # stress — near-term fear > long-term
    elif ratio > 0.9:
        structure = "FLAT"  # cautious
    else:
        structure = "CONTANGO"  # normal — near-term calm

    return {
        "structure": structure,
        "ratio": round(ratio, 3),
        "vix": vix_data["price"],
        "vix3m": vix3m_data["price"],
    }


def compute_credit_spread(hyg_data: dict | None, lqd_data: dict | None) -> dict:
    """Compute credit spread proxy from HYG vs LQD relative performance."""
    if not hyg_data or not lqd_data:
        return {"spread_direction": "unknown"}

    # HYG underperforming LQD = spreads widening = stress
    spread_chg_1d = hyg_data["daily_chg"] - lqd_data["daily_chg"]
    spread_chg_1w = hyg_data["week_chg"] - lqd_data["week_chg"]

    if spread_chg_1w < -1.0:
        direction = "WIDENING FAST"
    elif spread_chg_1w < -0.3:
        direction = "WIDENING"
    elif spread_chg_1w > 0.3:
        direction = "TIGHTENING"
    else:
        direction = "STABLE"

    return {
        "spread_direction": direction,
        "hyg_vs_lqd_1d": round(spread_chg_1d, 2),
        "hyg_vs_lqd_1w": round(spread_chg_1w, 2),
    }


def determine_regime(vix_data, term_struct, credit, tnx_data, dxy_data, tlt_data) -> str:
    """Determine overall market regime."""
    stress_signals = 0
    risk_on_signals = 0

    # VIX level
    if vix_data and vix_data["price"] > 30:
        stress_signals += 2
    elif vix_data and vix_data["price"] > 25:
        stress_signals += 1
    elif vix_data and vix_data["price"] < 15:
        risk_on_signals += 1

    # Term structure
    if term_struct["structure"] == "BACKWARDATION":
        stress_signals += 2
    elif term_struct["structure"] == "CONTANGO":
        risk_on_signals += 1

    # Credit
    if credit["spread_direction"] == "WIDENING FAST":
        stress_signals += 2
    elif credit["spread_direction"] == "WIDENING":
        stress_signals += 1
    elif credit["spread_direction"] == "TIGHTENING":
        risk_on_signals += 1

    # TLT rising = flight to safety
    if tlt_data and tlt_data["week_chg"] > 1.5:
        stress_signals += 1
    elif tlt_data and tlt_data["week_chg"] < -1.5:
        risk_on_signals += 1

    if stress_signals >= 4:
        return "RISK-OFF (HIGH STRESS)"
    elif stress_signals >= 2:
        return "CAUTIOUS"
    elif risk_on_signals >= 3:
        return "RISK-ON"
    else:
        return "NEUTRAL"


def detect_regime_flips(current_regime: str, prev_state: dict) -> list[str]:
    """Detect regime changes vs previous day."""
    alerts = []
    prev_regime = prev_state.get("regime", "NEUTRAL")

    if current_regime != prev_regime:
        alerts.append(f"REGIME FLIP: {prev_regime} -> {current_regime}")

    # VIX level changes
    prev_vix = prev_state.get("vix", 0)
    curr_vix = prev_state.get("_new_vix", 0)
    if prev_vix < 25 and curr_vix >= 25:
        alerts.append(f"VIX CROSSED ABOVE 25 ({curr_vix:.1f})")
    elif prev_vix < 30 and curr_vix >= 30:
        alerts.append(f"VIX SPIKED ABOVE 30 ({curr_vix:.1f})")
    elif prev_vix >= 25 and curr_vix < 20:
        alerts.append(f"VIX COLLAPSED BACK BELOW 20 ({curr_vix:.1f})")

    # Term structure flip
    prev_struct = prev_state.get("term_structure", "CONTANGO")
    curr_struct = prev_state.get("_new_term_structure", "CONTANGO")
    if prev_struct == "CONTANGO" and curr_struct == "BACKWARDATION":
        alerts.append("VIX TERM STRUCTURE INVERTED (backwardation) — elevated near-term fear")
    elif prev_struct == "BACKWARDATION" and curr_struct == "CONTANGO":
        alerts.append("VIX TERM STRUCTURE NORMALIZED (back to contango) — fear subsiding")

    # Credit spread change
    prev_credit = prev_state.get("credit_direction", "STABLE")
    curr_credit = prev_state.get("_new_credit_direction", "STABLE")
    if prev_credit != "WIDENING FAST" and curr_credit == "WIDENING FAST":
        alerts.append("CREDIT SPREADS WIDENING RAPIDLY — risk asset caution")

    return alerts


def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting regime dashboard")

    prev_state = load_prev_state()

    # Fetch all assets in a single batch request
    asset_map = {
        "VIX": "^VIX",
        "VIX3M": "^VIX3M",
        "TNX": "^TNX",
        "DXY": "DX-Y.NYB",
        "HYG": "HYG",
        "LQD": "LQD",
        "TLT": "TLT",
        "GLD": "GLD",
    }

    all_data = fetch_all_assets(list(asset_map.values()))
    data = {}
    for name, ticker in asset_map.items():
        d = all_data.get(ticker)
        data[name] = d
        if d:
            print(f"  {name}: ${d['price']} ({d['daily_chg']:+.2f}%)")

    # Compute regime indicators
    term_struct = compute_vix_term_structure(data["VIX"], data["VIX3M"])
    credit = compute_credit_spread(data["HYG"], data["LQD"])
    regime = determine_regime(data["VIX"], term_struct, credit, data["TNX"], data["DXY"], data["TLT"])

    # Build dashboard message
    lines = [f"**Regime Dashboard** ({now_et.strftime('%a %b %d')})", ""]
    lines.append(f"Regime: **{regime}**")
    lines.append("")

    # VIX section
    if data["VIX"]:
        vix = data["VIX"]
        vix_emoji = "🟢" if vix["price"] < 18 else "🟡" if vix["price"] < 25 else "🔴"
        lines.append(f"{vix_emoji} **VIX** {vix['price']:.1f} ({vix['daily_chg']:+.1f}%) | Yr Pctile: {vix['pct_rank_yr']:.0f}%")
        if term_struct["ratio"]:
            struct_emoji = "🟢" if term_struct["structure"] == "CONTANGO" else "🟡" if term_struct["structure"] == "FLAT" else "🔴"
            lines.append(f"  {struct_emoji} Term Structure: {term_struct['structure']} (ratio: {term_struct['ratio']:.3f})")

    # Yields
    if data["TNX"]:
        tnx = data["TNX"]
        lines.append(f"**10Y Yield** {tnx['price']:.2f}% ({tnx['daily_chg']:+.2f}%) | 1W: {tnx['week_chg']:+.2f}%")

    # Dollar
    if data["DXY"]:
        dxy = data["DXY"]
        lines.append(f"**Dollar (DXY)** {dxy['price']:.1f} ({dxy['daily_chg']:+.1f}%) | 1W: {dxy['week_chg']:+.1f}%")

    # Credit
    credit_emoji = "🟢" if credit["spread_direction"] in ("STABLE", "TIGHTENING") else "🟡" if credit["spread_direction"] == "WIDENING" else "🔴"
    lines.append(f"{credit_emoji} **Credit Spreads** {credit['spread_direction']} (HYG-LQD 1W: {credit.get('hyg_vs_lqd_1w', 0):+.2f}%)")

    # Treasuries & Gold
    if data["TLT"]:
        tlt = data["TLT"]
        lines.append(f"**TLT** ${tlt['price']:.2f} ({tlt['daily_chg']:+.1f}%) | 1W: {tlt['week_chg']:+.1f}%")
    if data["GLD"]:
        gld = data["GLD"]
        lines.append(f"**Gold** ${gld['price']:.2f} ({gld['daily_chg']:+.1f}%) | 1W: {gld['week_chg']:+.1f}%")

    dashboard = "\n".join(lines)
    send_discord(DASHBOARD_CH, dashboard)
    print(f"Posted regime dashboard ({len(dashboard)} chars)")

    # Detect regime flips and alert
    prev_state["_new_vix"] = data["VIX"]["price"] if data["VIX"] else 0
    prev_state["_new_term_structure"] = term_struct["structure"]
    prev_state["_new_credit_direction"] = credit["spread_direction"]

    flip_alerts = detect_regime_flips(regime, prev_state)
    if flip_alerts:
        alert_lines = [f"**Regime Alert** ({now_et.strftime('%a %b %d')})", ""]
        for a in flip_alerts:
            alert_lines.append(f"- {a}")
        alert_msg = "\n".join(alert_lines)
        send_discord(DASHBOARD_CH, alert_msg)
        print(f"Posted {len(flip_alerts)} regime alerts")

    # Save state
    new_state = {
        "regime": regime,
        "vix": data["VIX"]["price"] if data["VIX"] else 0,
        "term_structure": term_struct["structure"],
        "credit_direction": credit["spread_direction"],
        "date": now_et.strftime("%Y-%m-%d"),
    }
    save_state(new_state)
    # Popen sends complete independently after script exits
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Regime dashboard complete")


if __name__ == "__main__":
    main()
