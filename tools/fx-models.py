"""
FX Econometric Models
Multi-factor analysis of major currency pairs with predictive signals.

Models:
  1. Carry: Yield differential (US vs foreign) — higher carry attracts capital
  2. Momentum: 20/50/200 SMA positioning — trend-following signal
  3. Mean Reversion: Z-score vs 100-day mean — extreme deviations revert
  4. Equity Beta: FX correlation with SPY — risk-on/risk-off sensitivity
  5. Commodity Link: AUD/CAD vs commodity prices — terms-of-trade effect
  6. Composite: Weighted score across all factors → net directional signal

Posts to Discord via webhook.
Schedule: 4:55 PM EST Fridays (combined run with econ-predictor)

Cost: $0.00 (Tier 1 — yfinance + FRED CSV, no LLM)
"""

import io
import json
import requests
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

ET = ZoneInfo("America/New_York")

# Discord webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471466040931258431/MFf5gibpTsLv3eAfwDSJafTyS9lLLCHxMvOZYdnhS85X8TARZpfHzug3OsOMhsIz-2mW"


def send_discord(message: str):
    """Send message to Discord via webhook."""
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Send failed: {e}")


# ─── PAIR DEFINITIONS ────────────────────────────────────────────

FX_PAIRS = {
    "EURUSD=X": {"name": "EUR/USD", "quote": "USD_per_EUR", "foreign_rate": "IRLTLT01DEM156N",
                  "commodity": None, "risk": "risk-on"},
    "USDJPY=X": {"name": "USD/JPY", "quote": "JPY_per_USD", "foreign_rate": "IRLTLT01JPM156N",
                  "commodity": None, "risk": "risk-on"},
    "GBPUSD=X": {"name": "GBP/USD", "quote": "USD_per_GBP", "foreign_rate": "IRLTLT01GBM156N",
                  "commodity": None, "risk": "risk-on"},
    "AUDUSD=X": {"name": "AUD/USD", "quote": "USD_per_AUD", "foreign_rate": "IRLTLT01AUM156N",
                  "commodity": "GC=F", "risk": "risk-on"},
    "USDCAD=X": {"name": "USD/CAD", "quote": "CAD_per_USD", "foreign_rate": "IRLTLT01CAM156N",
                  "commodity": "CL=F", "risk": "neutral"},
}


# Alpha Vantage API key (free tier, 25 calls/day)
ALPHAVANTAGE_API_KEY = "1SIVEVQAAYTRTLBV"

# Map yfinance FX ticker → Alpha Vantage from/to currency codes
AV_FX_MAP = {
    "EURUSD=X": ("EUR", "USD"),
    "USDJPY=X": ("USD", "JPY"),
    "GBPUSD=X": ("GBP", "USD"),
    "AUDUSD=X": ("AUD", "USD"),
    "USDCAD=X": ("USD", "CAD"),
}


def fetch_fx_alphavantage(yf_ticker: str) -> pd.Series | None:
    """Fetch daily FX close prices from Alpha Vantage as fallback."""
    pair = AV_FX_MAP.get(yf_ticker)
    if not pair:
        return None
    from_cur, to_cur = pair
    url = (
        f"https://www.alphavantage.co/query?function=FX_DAILY"
        f"&from_symbol={from_cur}&to_symbol={to_cur}"
        f"&outputsize=full&apikey={ALPHAVANTAGE_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=20)
        data = resp.json()
        ts = data.get("Time Series FX (Daily)", {})
        if not ts:
            print(f"  AV {yf_ticker}: no data returned")
            return None
        dates = []
        closes = []
        for date_str, vals in sorted(ts.items()):
            dates.append(pd.Timestamp(date_str))
            closes.append(float(vals["4. close"]))
        series = pd.Series(closes, index=dates, name=yf_ticker)
        print(f"  AV {yf_ticker}: {len(series)} days")
        return series
    except Exception as e:
        print(f"  AV {yf_ticker}: fetch error: {e}")
        return None


def fetch_fred(series_id: str, start: str = "2023-01-01") -> pd.Series | None:
    """Fetch FRED series via CSV."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = resp.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(data), parse_dates=["observation_date"], index_col="observation_date")
        return df[series_id].replace(".", np.nan).astype(float).dropna()
    except:
        return None


def compute_momentum(close: pd.Series) -> dict:
    """Compute momentum signals from moving averages."""
    if len(close) < 200:
        return {"sma20": None, "sma50": None, "sma200": None, "signal": "N/A"}

    price = close.iloc[-1]
    sma20 = close.rolling(20).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]

    # Momentum score: +1 for each MA above, -1 for below
    score = 0
    score += 1 if price > sma20 else -1
    score += 1 if price > sma50 else -1
    score += 1 if price > sma200 else -1

    # Trend strength
    if score >= 2:
        signal = "BULLISH"
    elif score <= -2:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"

    # 20/50 cross detection
    prev_20 = close.rolling(20).mean().iloc[-2]
    prev_50 = close.rolling(50).mean().iloc[-2]
    cross = ""
    if prev_20 <= prev_50 and sma20 > sma50:
        cross = " (20/50 bull cross)"
    elif prev_20 >= prev_50 and sma20 < sma50:
        cross = " (20/50 bear cross)"

    return {
        "price": round(price, 4),
        "sma20": round(sma20, 4),
        "sma50": round(sma50, 4),
        "sma200": round(sma200, 4),
        "score": score,
        "signal": signal + cross,
        "pct_from_200": round((price / sma200 - 1) * 100, 1),
    }


def compute_mean_reversion(close: pd.Series, window: int = 100) -> dict:
    """Z-score vs rolling mean — extreme values tend to revert."""
    if len(close) < window + 20:
        return {"zscore": 0, "signal": "N/A"}

    mean = close.rolling(window).mean().iloc[-1]
    std = close.rolling(window).std().iloc[-1]

    if std == 0:
        return {"zscore": 0, "signal": "N/A"}

    zscore = (close.iloc[-1] - mean) / std

    if zscore > 2.0:
        signal = "OVERBOUGHT"
    elif zscore > 1.0:
        signal = "EXTENDED HIGH"
    elif zscore < -2.0:
        signal = "OVERSOLD"
    elif zscore < -1.0:
        signal = "EXTENDED LOW"
    else:
        signal = "FAIR VALUE"

    return {
        "zscore": round(float(zscore), 2),
        "signal": signal,
    }


def compute_carry(us_rate: pd.Series, foreign_rate: pd.Series, pair_quote: str) -> dict | None:
    """Carry signal from yield differential."""
    if us_rate is None or foreign_rate is None:
        return None
    if us_rate.empty or foreign_rate.empty:
        return None

    us_latest = us_rate.iloc[-1]
    # Foreign rates are monthly — take latest
    foreign_latest = foreign_rate.iloc[-1]
    diff = us_latest - foreign_latest

    # Positive diff = USD carries more → bullish for USD
    # For XXX/USD pairs (EURUSD, GBPUSD, AUDUSD): positive diff → bearish for pair
    # For USD/XXX pairs (USDJPY, USDCAD): positive diff → bullish for pair

    if "per_USD" in pair_quote:
        # USD/JPY, USD/CAD — higher US rate = bullish
        carry_direction = "LONG" if diff > 0.5 else "SHORT" if diff < -0.5 else "NEUTRAL"
    else:
        # EUR/USD, GBP/USD, AUD/USD — higher US rate = bearish for pair
        carry_direction = "SHORT" if diff > 0.5 else "LONG" if diff < -0.5 else "NEUTRAL"

    return {
        "us_rate": round(us_latest, 2),
        "foreign_rate": round(foreign_latest, 2),
        "differential": round(diff, 2),
        "signal": carry_direction,
    }


def compute_equity_beta(fx_returns: pd.Series, spy_returns: pd.Series, halflife: int = 21) -> dict | None:
    """EWM beta of FX pair to SPY — measures risk-on/risk-off sensitivity."""
    df = pd.DataFrame({"fx": fx_returns, "spy": spy_returns}).dropna()
    if len(df) < 60:
        return None

    ewm = df.ewm(halflife=halflife)
    cov_matrix = ewm.cov()
    last_idx = df.index[-1]

    try:
        cov_xy = cov_matrix.loc[(last_idx, "fx"), "spy"]
        var_x = cov_matrix.loc[(last_idx, "fx"), "fx"]
        var_spy = cov_matrix.loc[(last_idx, "spy"), "spy"]
    except:
        return None

    if var_x <= 0 or var_spy <= 0:
        return None

    corr = cov_xy / np.sqrt(var_x * var_spy)
    beta = cov_xy / var_spy  # How much FX moves per 1% SPY move

    return {
        "corr": round(float(corr), 2),
        "beta": round(float(beta), 3),
    }


def compute_commodity_link(fx_close: pd.Series, commodity_close: pd.Series,
                            halflife: int = 21) -> dict | None:
    """Correlation between FX pair and linked commodity."""
    fx_ret = fx_close.pct_change().dropna()
    com_ret = commodity_close.pct_change().dropna()

    df = pd.DataFrame({"fx": fx_ret, "com": com_ret}).dropna()
    if len(df) < 60:
        return None

    ewm = df.ewm(halflife=halflife)
    cov_matrix = ewm.cov()
    last_idx = df.index[-1]

    try:
        cov_xy = cov_matrix.loc[(last_idx, "fx"), "com"]
        var_x = cov_matrix.loc[(last_idx, "fx"), "fx"]
        var_y = cov_matrix.loc[(last_idx, "com"), "com"]
    except:
        return None

    if var_x <= 0 or var_y <= 0:
        return None

    return {"corr": round(float(cov_xy / np.sqrt(var_x * var_y)), 2)}


def composite_signal(momentum: dict, mean_rev: dict, carry: dict | None,
                      equity: dict | None) -> str:
    """Aggregate all factors into a single directional signal."""
    score = 0
    weights_used = 0

    # Momentum (weight: 3)
    if momentum.get("score") is not None:
        score += momentum["score"]  # -3 to +3
        weights_used += 3

    # Mean reversion (weight: 2, inverted — extreme high = sell)
    zs = mean_rev.get("zscore", 0)
    if abs(zs) > 0.5:
        score += -2 if zs > 1.5 else -1 if zs > 0.5 else 2 if zs < -1.5 else 1 if zs < -0.5 else 0
        weights_used += 2

    # Carry (weight: 2)
    if carry:
        if carry["signal"] == "LONG":
            score += 2
        elif carry["signal"] == "SHORT":
            score -= 2
        weights_used += 2

    # Equity beta direction (weight: 1)
    if equity and abs(equity.get("corr", 0)) > 0.3:
        # Strong positive equity beta during risk-on = supportive
        score += 1 if equity["corr"] > 0.3 else -1 if equity["corr"] < -0.3 else 0
        weights_used += 1

    if weights_used == 0:
        return "N/A"

    normalized = score / weights_used
    if normalized > 0.3:
        return "BULLISH" if normalized > 0.6 else "LEAN LONG"
    elif normalized < -0.3:
        return "BEARISH" if normalized < -0.6 else "LEAN SHORT"
    else:
        return "NEUTRAL"


def main():
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)

    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting FX models")

    # ── 1. Fetch all market data ──
    fx_tickers = list(FX_PAIRS.keys())
    extra_tickers = ["SPY", "DX-Y.NYB", "CL=F", "GC=F"]
    all_tickers = fx_tickers + extra_tickers

    # Try yfinance first
    price_data = {}
    print(f"Fetching {len(all_tickers)} tickers via yfinance...")
    try:
        batch = yf.download(all_tickers, period="2y", group_by="ticker", threads=True, progress=False)
        for t in all_tickers:
            try:
                close = batch[t]["Close"].dropna()
                if len(close) >= 200:
                    price_data[t] = close
            except:
                continue
    except Exception as e:
        print(f"  yfinance batch download failed: {e}")

    print(f"  yfinance: {len(price_data)} tickers")

    # Fallback to Alpha Vantage for any missing FX pairs
    missing_fx = [t for t in fx_tickers if t not in price_data]
    if missing_fx:
        print(f"  Falling back to Alpha Vantage for {len(missing_fx)} FX pairs...")
        import time
        for t in missing_fx:
            series = fetch_fx_alphavantage(t)
            if series is not None and len(series) >= 200:
                price_data[t] = series
            time.sleep(1)  # AV rate limit: 5 calls/min on free tier

    # Fallback for extra tickers (SPY, DXY, commodities) — individual yfinance calls
    missing_extra = [t for t in extra_tickers if t not in price_data]
    if missing_extra:
        print(f"  Retrying {len(missing_extra)} extra tickers individually...")
        import time
        time.sleep(2)
        for t in missing_extra:
            try:
                df = yf.download(t, period="2y", progress=False)
                if "Close" in df.columns:
                    close = df["Close"].dropna()
                else:
                    close = df[("Close", t)].dropna() if ("Close", t) in df.columns else pd.Series(dtype=float)
                if len(close) >= 200:
                    price_data[t] = close
                    print(f"  {t}: {len(close)} days (retry)")
            except:
                continue
            time.sleep(1)

    print(f"Got data for {len(price_data)} tickers total")

    # ── 2. Fetch FRED yield data ──
    from concurrent.futures import ThreadPoolExecutor, as_completed

    us_2y = fetch_fred("DGS2", "2023-01-01")

    foreign_rates = {}
    def _fetch_rate(pair_ticker):
        cfg = FX_PAIRS[pair_ticker]
        return pair_ticker, fetch_fred(cfg["foreign_rate"], "2023-01-01")

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_fetch_rate, t) for t in fx_tickers]
        for f in as_completed(futures):
            pair, rate = f.result()
            if rate is not None:
                foreign_rates[pair] = rate

    # SPY returns for equity beta
    spy_returns = price_data.get("SPY", pd.Series(dtype=float)).pct_change().dropna()

    # ── 3. Compute all models for each pair ──
    pair_results = {}
    for pair_ticker, cfg in FX_PAIRS.items():
        if pair_ticker not in price_data:
            continue

        close = price_data[pair_ticker]
        name = cfg["name"]
        print(f"  Analyzing {name}...")

        # Momentum
        mom = compute_momentum(close)

        # Mean reversion
        mr = compute_mean_reversion(close, window=100)

        # Carry
        carry = compute_carry(us_2y, foreign_rates.get(pair_ticker), cfg["quote"])

        # Equity beta
        fx_ret = close.pct_change().dropna()
        eq_beta = compute_equity_beta(fx_ret, spy_returns)

        # Commodity link
        com_link = None
        if cfg["commodity"] and cfg["commodity"] in price_data:
            com_link = compute_commodity_link(close, price_data[cfg["commodity"]])

        # Composite
        composite = composite_signal(mom, mr, carry, eq_beta)

        pair_results[pair_ticker] = {
            "name": name,
            "momentum": mom,
            "mean_reversion": mr,
            "carry": carry,
            "equity_beta": eq_beta,
            "commodity_link": com_link,
            "composite": composite,
        }

    # ── 4. Format output ──
    # DXY context
    dxy_mom = compute_momentum(price_data["DX-Y.NYB"]) if "DX-Y.NYB" in price_data else None

    lines = [f"**FX Models** ({now_et.strftime('%a %b %d')})", ""]

    if dxy_mom:
        lines.append(f"**Dollar Index (DXY)**: {dxy_mom['price']:.2f} | "
                     f"{dxy_mom['signal']} | {dxy_mom['pct_from_200']:+.1f}% from 200d")
        lines.append("")

    # Signal dashboard
    lines.append("**Signal Dashboard**")
    lines.append("```")
    header = f"{'Pair':<10} {'Price':>8} {'Momentum':>10} {'MeanRev':>9} {'Carry':>8} {'EqBeta':>7} {'NET':>10}"
    lines.append(header)
    lines.append("-" * len(header))

    for pair_ticker in FX_PAIRS:
        r = pair_results.get(pair_ticker)
        if not r:
            continue

        name = r["name"]
        mom = r["momentum"]
        mr = r["mean_reversion"]
        carry = r["carry"]
        eq = r["equity_beta"]

        price_str = f"{mom['price']:.4f}" if mom.get("price") else "N/A"

        # Compact momentum: +3 to -3
        mom_str = f"{mom['score']:+d}" if mom.get("score") is not None else "N/A"

        # Mean reversion z-score
        mr_str = f"{mr['zscore']:+.1f}" if mr.get("zscore") else "N/A"

        # Carry direction
        carry_str = carry["signal"][:5] if carry else "N/A"

        # Equity beta
        eq_str = f"{eq['corr']:+.2f}" if eq else "N/A"

        # Composite
        net = r["composite"]

        lines.append(
            f"{name:<10} {price_str:>8} {mom_str:>10} {mr_str:>9} {carry_str:>8} {eq_str:>7} {net:>10}"
        )

    lines.append("```")
    lines.append("")

    # Detailed pair analysis
    lines.append("**Pair Detail**")
    for pair_ticker in FX_PAIRS:
        r = pair_results.get(pair_ticker)
        if not r:
            continue

        name = r["name"]
        mom = r["momentum"]
        carry = r["carry"]
        com = r["commodity_link"]

        detail_parts = [f"**{name}**"]

        # MA positioning
        if mom.get("sma200"):
            detail_parts.append(f"{mom['pct_from_200']:+.1f}% from 200d")

        # Carry detail
        if carry:
            detail_parts.append(f"carry: {carry['differential']:+.1f}% (US:{carry['us_rate']:.1f}% vs {carry['foreign_rate']:.1f}%)")

        # Commodity
        if com:
            com_name = "Oil" if FX_PAIRS[pair_ticker]["commodity"] == "CL=F" else "Gold"
            detail_parts.append(f"{com_name} corr: {com['corr']:+.2f}")

        lines.append(" | ".join(detail_parts))

    message = "\n".join(lines)
    send_discord(message)
    print(f"Posted FX models ({len(message)} chars)")

    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} FX models complete")


if __name__ == "__main__":
    main()
