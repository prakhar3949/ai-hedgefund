"""
Economic Data Predictive Model
Tests whether macro releases (jobs, CPI, PMI, housing, etc.) predict forward equity returns.

Methodology:
  - Fetches monthly economic data from FRED (free CSV, no API key)
  - Computes month-over-month changes for each indicator
  - Correlates with FORWARD market returns (SPY/QQQ/IWM) at 1-month and 3-month horizons
  - Uses exponentially-weighted correlation (halflife=18 months) for recency bias
  - Reports: coefficient direction, strength, and statistical significance
  - A t-stat > 2.0 suggests genuine predictive power (95% confidence)

Posts to Discord via webhook.

Cost: $0.00 (Tier 1 — FRED CSV + Yahoo Finance, no LLM)
"""

import io
import json
import time
import requests
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")

# Use project directory as base
PROJECT_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

# Discord webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471466326710288559/oOh2ApQCZ__k9feKMzgzJvuDb3jESFDZvyY8mYObjoDU_RIRLKAhpZK3vzZC2ijeRFNj"


def send_discord(message: str):
    """Send message to Discord via webhook."""
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Send failed: {e}")


# ─── FRED DATA ───────────────────────────────────────────────────

ECON_SERIES = {
    # FRED_ID: (display_name, transform)
    # transform: "chg" = month-over-month change, "pct" = % change, "level" = use as-is
    "PAYEMS":   ("Nonfarm Payrolls", "chg"),
    "UNRATE":   ("Unemployment", "chg"),
    "CPIAUCSL": ("CPI", "pct"),
    "CPILFESL": ("Core CPI", "pct"),
    "PCEPI":    ("PCE Prices", "pct"),
    "HOUST":    ("Housing Starts", "pct"),
    "RSAFS":    ("Retail Sales", "pct"),
    "INDPRO":   ("Indust. Prod.", "pct"),
    "DGORDER":  ("Durable Goods", "pct"),
    "UMCSENT":  ("Consumer Sent.", "chg"),
    "ICSA":     ("Jobless Claims", "chg"),
    "MANEMP":   ("Mfg Employment", "chg"),
}


def fetch_fred_series(series_id: str, start: str = "2015-01-01") -> pd.Series | None:
    """Fetch a FRED series via direct CSV download (no API key needed)."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = resp.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(data), parse_dates=["observation_date"], index_col="observation_date")
        series = df[series_id].replace(".", np.nan).astype(float).dropna()
        return series
    except Exception as e:
        print(f"  Failed to fetch {series_id}: {e}")
        return None


def fetch_all_fred(series_ids: list[str]) -> dict[str, pd.Series]:
    """Fetch multiple FRED series in parallel."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}

    def _fetch(sid):
        return sid, fetch_fred_series(sid)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_fetch, sid) for sid in series_ids]
        for f in as_completed(futures):
            sid, data = f.result()
            if data is not None and len(data) >= 24:
                results[sid] = data
                print(f"  {sid}: {len(data)} observations")
            else:
                print(f"  {sid}: insufficient data")
    return results


def transform_series(series: pd.Series, transform: str) -> pd.Series:
    """Transform raw FRED data into changes."""
    if transform == "chg":
        return series.diff().dropna()
    elif transform == "pct":
        return series.pct_change().dropna() * 100
    else:
        return series


def fetch_equity_monthly(ticker: str) -> pd.Series | None:
    """Fetch monthly closes from Yahoo Finance chart API, return monthly % returns."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=10y&interval=1mo"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"  {ticker}: HTTP {resp.status_code}")
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        timestamps = result[0]["timestamp"]
        closes = result[0]["indicators"]["quote"][0]["close"]

        # Build pandas Series with datetime index
        dates = [datetime.fromtimestamp(ts) for ts in timestamps]
        series = pd.Series(closes, index=pd.DatetimeIndex(dates), name=ticker)
        series = series.dropna()

        # Compute monthly % returns
        returns = series.pct_change().dropna() * 100
        print(f"  {ticker}: {len(returns)} monthly returns")
        return returns
    except Exception as e:
        print(f"  {ticker}: fetch error: {e}")
        return None


def ewm_predictive_corr(indicator: pd.Series, forward_returns: pd.Series,
                         halflife: int = 18) -> dict | None:
    """
    Compute EWM correlation between an economic indicator change and FORWARD market returns.
    Both series must be monthly-aligned.
    """
    df = pd.DataFrame({"indicator": indicator, "fwd_ret": forward_returns}).dropna()
    if len(df) < 24:
        return None

    n = len(df)

    # EWM correlation
    ewm = df.ewm(halflife=halflife)
    cov_matrix = ewm.cov()
    last_idx = df.index[-1]

    try:
        cov_xy = cov_matrix.loc[(last_idx, "indicator"), "fwd_ret"]
        var_x = cov_matrix.loc[(last_idx, "indicator"), "indicator"]
        var_y = cov_matrix.loc[(last_idx, "fwd_ret"), "fwd_ret"]
    except:
        return None

    if var_x <= 0 or var_y <= 0:
        return None

    corr = cov_xy / np.sqrt(var_x * var_y)

    # T-statistic (approximate for EWM — use effective sample size)
    effective_n = min(n, halflife * 3)
    if effective_n < 5:
        return None
    t_stat = corr * np.sqrt(effective_n - 2) / np.sqrt(1 - corr**2 + 1e-10)

    # Simple OLS beta with EWM weights
    x = df["indicator"].values
    y = df["fwd_ret"].values
    alpha = 1 - np.exp(-np.log(2) / halflife)
    weights = np.array([(1 - alpha) ** (n - 1 - i) for i in range(n)])
    weights /= weights.sum()

    x_w = x * weights
    x_mean = np.sum(x_w)
    y_mean = np.sum(y * weights)

    beta = np.sum(weights * (x - x_mean) * (y - y_mean)) / (np.sum(weights * (x - x_mean)**2) + 1e-10)

    return {
        "corr": round(float(corr), 3),
        "t_stat": round(float(t_stat), 2),
        "beta": round(float(beta), 4),
        "n": n,
        "significant": abs(t_stat) >= 1.65,
        "strong": abs(t_stat) >= 2.0,
    }


def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting economic predictor model")

    # ── 1. Fetch all FRED data in parallel ──
    print("Fetching FRED economic data...")
    fred_data = fetch_all_fred(list(ECON_SERIES.keys()))

    if len(fred_data) < 5:
        print("ERROR: Too few FRED series fetched")
        return

    # ── 2. Fetch equity monthly returns ──
    indexes = ["SPY", "QQQ", "IWM"]
    print("Fetching equity data...")
    monthly_returns = {}
    for idx in indexes:
        ret = fetch_equity_monthly(idx)
        if ret is not None:
            monthly_returns[idx] = ret
        time.sleep(0.3)

    if not monthly_returns:
        print("ERROR: No equity data")
        return

    # ── 3. Transform economic data and compute forward returns ──
    results = {}

    for sid, (name, transform) in ECON_SERIES.items():
        if sid not in fred_data:
            continue

        indicator = transform_series(fred_data[sid], transform)
        indicator = indicator.resample("ME").last().dropna()

        results[sid] = {"name": name}

        for idx in indexes:
            if idx not in monthly_returns:
                continue

            ret = monthly_returns[idx]
            ret_monthly = ret.resample("ME").last().dropna()

            # Forward 1-month return
            fwd_1m = ret_monthly.shift(-1).dropna()
            # Forward 3-month return
            fwd_3m = ret_monthly.shift(-1).rolling(3).sum().shift(-2).dropna()

            stats_1m = ewm_predictive_corr(indicator, fwd_1m, halflife=18)
            stats_3m = ewm_predictive_corr(indicator, fwd_3m, halflife=18)

            results[sid][idx] = {
                "1m": stats_1m,
                "3m": stats_3m,
            }

    # ── 4. Format output ──
    lines = [f"**Economic Predictor Model** ({now_et.strftime('%a %b %d')}) | halflife=18mo", ""]
    lines.append("**1-Month Forward Prediction** (does this month's data predict next month's return?)")
    lines.append("```")
    header = f"{'Indicator':<16} {'SPY':>8} {'QQQ':>8} {'IWM':>8} {'Sig?':>5}"
    lines.append(header)
    lines.append("-" * len(header))

    # Sort by average absolute t-stat
    sorted_sids = []
    for sid in results:
        if "name" not in results[sid]:
            continue
        t_stats = []
        for idx in indexes:
            s = results[sid].get(idx, {}).get("1m")
            if s:
                t_stats.append(abs(s["t_stat"]))
        if t_stats:
            sorted_sids.append((sid, np.mean(t_stats)))
    sorted_sids.sort(key=lambda x: x[1], reverse=True)

    for sid, avg_t in sorted_sids:
        name = results[sid]["name"]
        row = f"{name:<16}"
        any_sig = False
        for idx in indexes:
            s = results[sid].get(idx, {}).get("1m")
            if s:
                marker = "*" if s["strong"] else "~" if s["significant"] else " "
                row += f"{s['corr']:>+7.2f}{marker}"
                if s["significant"]:
                    any_sig = True
            else:
                row += f"{'N/A':>8}"
        row += f"  {'**' if any_sig else '  '}"
        lines.append(row)

    lines.append("```")
    lines.append("*=p<0.10  \\*=p<0.05  Correlations are EWM-weighted (recent data matters more)*")
    lines.append("")

    # 3-month forward prediction
    lines.append("**3-Month Forward Prediction**")
    lines.append("```")
    lines.append(header)
    lines.append("-" * len(header))

    for sid, avg_t in sorted_sids:
        name = results[sid]["name"]
        row = f"{name:<16}"
        any_sig = False
        for idx in indexes:
            s = results[sid].get(idx, {}).get("3m")
            if s:
                marker = "*" if s["strong"] else "~" if s["significant"] else " "
                row += f"{s['corr']:>+7.2f}{marker}"
                if s["significant"]:
                    any_sig = True
            else:
                row += f"{'N/A':>8}"
        row += f"  {'**' if any_sig else '  '}"
        lines.append(row)

    lines.append("```")
    lines.append("")

    # Insights
    insights = []
    for sid, _ in sorted_sids:
        name = results[sid]["name"]
        for idx in indexes:
            for horizon in ["1m", "3m"]:
                s = results[sid].get(idx, {}).get(horizon)
                if s and s["strong"]:
                    direction = "bullish" if s["corr"] > 0 else "bearish"
                    insights.append(
                        f"{name} -> {idx} ({horizon}): {direction} signal "
                        f"(r={s['corr']:+.2f}, t={s['t_stat']:.1f})"
                    )

    if insights:
        lines.append("**Significant Predictors (p<0.05):**")
        for i in insights[:6]:
            lines.append(f"- {i}")
    else:
        lines.append("*No indicators reaching 95% significance at current halflife.*")

    message = "\n".join(lines)

    if len(message) > 1950:
        split_at = message.index("**3-Month Forward")
        send_discord(message[:split_at].strip())
        time.sleep(0.5)
        send_discord(message[split_at:].strip())
    else:
        send_discord(message)

    print(f"Posted economic predictor ({len(message)} chars)")
    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} Economic predictor complete")


if __name__ == "__main__":
    main()
