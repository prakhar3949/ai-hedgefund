"""
Econometrics Report — combined weekly analysis
Three reports in one script, sharing data and startup cost:

1. Correlation Matrix: EWM correlations between indexes vs macro/sectors
2. Economic Predictor: FRED macro data → forward return prediction
3. FX Models: Carry, momentum, mean-reversion, equity beta

Yahoo Chart API (28 tickers) + cached FRED data.
Posts to Discord via webhook.
Schedule: 4:55 PM EST Fridays

Cost: $0.00 (Tier 1 — Yahoo Chart API + FRED CSV, no LLM)
"""

import io
import json
import requests
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")

# Use the project directory as base
PROJECT_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

FRED_CACHE = MEMORY_DIR / "fred-cache.json"
MODEL_STATE = MEMORY_DIR / "econ-model-state.json"

# Discord webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471470640816197725/fO2N3HV360Pfs6WfAQOTIokJrjE60akxbkKa9cmj0Fs-jJvSJyXZLdotbCssmY3v30MV"


def send_discord(message: str):
    """Send message to Discord via webhook."""
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Send failed: {e}")


# ─── SHARED UTILITIES ────────────────────────────────────────────

def fast_ewm_corr(x: np.ndarray, y: np.ndarray, halflife: int) -> float:
    """Direct numpy EWM correlation — avoids pandas DataFrame overhead."""
    n = len(x)
    if n < 30:
        return np.nan
    alpha = 1 - np.exp(-np.log(2) / halflife)
    w = np.array([(1 - alpha) ** (n - 1 - i) for i in range(n)])
    w /= w.sum()
    wx, wy = np.sum(w * x), np.sum(w * y)
    dx, dy = x - wx, y - wy
    cov = np.sum(w * dx * dy)
    vx, vy = np.sum(w * dx**2), np.sum(w * dy**2)
    if vx <= 0 or vy <= 0:
        return np.nan
    return float(cov / np.sqrt(vx * vy))


YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def fetch_close(ticker: str, period: str = "2y", interval: str = "1d") -> pd.Series | None:
    """Fetch close prices via Yahoo Chart API. Returns pd.Series or None."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval={interval}"
    try:
        resp = requests.get(url, headers=YAHOO_HEADERS, timeout=15)
        data = resp.json()["chart"]["result"][0]
        timestamps = data["timestamp"]
        closes = data["indicators"]["quote"][0]["close"]
        idx = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert("America/New_York").normalize()
        s = pd.Series(closes, index=idx, name=ticker, dtype=float).dropna()
        s.index = s.index.tz_localize(None)
        if len(s) >= 50:
            return s
    except Exception as e:
        print(f"  fetch_close({ticker}): {e}")
    return None


def batch_download(tickers: list[str], period: str = "2y") -> dict[str, pd.Series]:
    """Parallel download via Yahoo Chart API → dict of close price series."""
    result = {}

    def _fetch(t):
        return t, fetch_close(t, period=period)

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(_fetch, t) for t in tickers]
        for f in as_completed(futures):
            t, s = f.result()
            if s is not None:
                result[t] = s

    return result


# ─── FRED DATA (with caching) ────────────────────────────────────

ALL_FRED_SERIES = [
    # Economic indicators
    "PAYEMS", "UNRATE", "CPIAUCSL", "CPILFESL", "PCEPI", "HOUST",
    "RSAFS", "INDPRO", "DGORDER", "UMCSENT", "ICSA", "MANEMP",
    "CES0500000003",  # Average Hourly Earnings (wage growth)
    # Yield data for FX carry
    "DGS2", "IRLTLT01DEM156N", "IRLTLT01JPM156N", "IRLTLT01GBM156N",
    "IRLTLT01AUM156N", "IRLTLT01CAM156N",
]


def fetch_fred_series(series_id: str, start: str = "2015-01-01") -> list | None:
    """Fetch FRED series, return as list of [date_str, value] for JSON caching."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = resp.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(data), parse_dates=["observation_date"])
        df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
        df = df.dropna()
        return [[r["observation_date"].strftime("%Y-%m-%d"), float(r[series_id])]
                for _, r in df.iterrows()]
    except:
        return None


def load_fred_data() -> dict[str, pd.Series]:
    """Load FRED data from cache or fetch fresh. Cache valid for 6 hours."""
    cache = {}
    try:
        with open(FRED_CACHE) as f:
            cache = json.load(f)
    except:
        pass

    now_str = datetime.now(ET).strftime("%Y-%m-%d %H:%M")
    cache_age_ok = False
    if cache.get("updated"):
        try:
            updated = datetime.strptime(cache["updated"], "%Y-%m-%d %H:%M")
            cache_age_ok = (datetime.now() - updated).total_seconds() < 6 * 3600
        except:
            pass

    if cache_age_ok and all(sid in cache.get("data", {}) for sid in ALL_FRED_SERIES):
        print("  FRED: using cache")
        result = {}
        for sid, rows in cache["data"].items():
            s = pd.Series(
                [r[1] for r in rows],
                index=pd.to_datetime([r[0] for r in rows]),
                name=sid,
            )
            result[sid] = s
        return result

    # Fetch fresh in parallel
    print("  FRED: fetching fresh data...")
    fresh_data = {}

    def _fetch(sid):
        return sid, fetch_fred_series(sid)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_fetch, sid) for sid in ALL_FRED_SERIES]
        for f in as_completed(futures):
            sid, rows = f.result()
            if rows:
                fresh_data[sid] = rows

    # Save cache
    try:
        with open(FRED_CACHE, "w") as f:
            json.dump({"updated": now_str, "data": fresh_data}, f)
    except:
        pass

    result = {}
    for sid, rows in fresh_data.items():
        s = pd.Series(
            [r[1] for r in rows],
            index=pd.to_datetime([r[0] for r in rows]),
            name=sid,
        )
        result[sid] = s
    return result


# ─── REPORT 1: CORRELATION MATRIX ────────────────────────────────

INDEXES = ["SPY", "QQQ", "IWM"]
MACRO_VARS = {
    "^VIX": "VIX", "^TNX": "10Y Yield", "DX-Y.NYB": "Dollar",
    "TLT": "LT Treas", "HYG": "HY Credit", "GLD": "Gold", "USO": "Oil",
}
SECTORS = {
    "XLK": "Tech", "XLF": "Financials", "XLE": "Energy", "XLV": "Healthcare",
    "XLI": "Industrials", "XLC": "Comm Svcs", "XLY": "Cons Disc",
    "XLP": "Cons Staples", "XLU": "Utilities", "XLRE": "Real Estate", "XLB": "Materials",
}


def build_correlation_report(price_data: dict, now_et: datetime) -> str:
    """Build correlation matrix report from shared price data."""
    halflife = 21

    # Compute daily returns
    returns = {}
    for t, close in price_data.items():
        ret = close.pct_change().dropna()
        if len(ret) >= 60:
            returns[t] = ret.values
            # Keep index for alignment
            returns[f"_idx_{t}"] = ret.index

    # Align all returns to common dates via DataFrame
    ret_df = pd.DataFrame({t: price_data[t].pct_change() for t in price_data if t in
                           (list(MACRO_VARS.keys()) + list(SECTORS.keys()) + INDEXES)}).dropna()

    idx_labels = [idx for idx in INDEXES if idx in ret_df.columns]
    if not idx_labels:
        return "", {}, {}

    # Compute all correlations using fast numpy
    macro_data = {}  # {macro_ticker: {index: corr}}
    for ticker, label in MACRO_VARS.items():
        if ticker not in ret_df.columns:
            continue
        y = ret_df[ticker].values
        corrs = {}
        for idx in idx_labels:
            x = ret_df[idx].values
            corrs[idx] = fast_ewm_corr(x, y, halflife)
        macro_data[ticker] = (label, corrs)

    sector_data = {}
    for ticker, label in SECTORS.items():
        if ticker not in ret_df.columns:
            continue
        y = ret_df[ticker].values
        corrs = {}
        for idx in idx_labels:
            x = ret_df[idx].values
            corrs[idx] = fast_ewm_corr(x, y, halflife)
        sector_data[ticker] = (label, corrs)

    # Format
    lines = [f"**Correlation Matrix** ({now_et.strftime('%a %b %d')}) | halflife={halflife}d", ""]
    lines.append("**Indexes vs Macro Variables** (sorted by strength)")
    lines.append("```")
    header = f"{'Variable':<12}" + "".join(f"{idx:>10}" for idx in idx_labels)
    lines.append(header)
    lines.append("-" * len(header))

    sorted_macro = sorted(macro_data.items(),
                          key=lambda x: np.nanmean([abs(v) for v in x[1][1].values()]), reverse=True)
    for ticker, (label, corrs) in sorted_macro:
        row = f"{label:<12}"
        for idx in idx_labels:
            v = corrs.get(idx, np.nan)
            row += f"{v:>+10.2f}" if not np.isnan(v) else f"{'N/A':>10}"
        lines.append(row)

    lines.append("```")
    lines.append("")
    lines.append("**Indexes vs Sectors** (sorted by SPY corr)")
    lines.append("```")
    header2 = f"{'Sector':<14}" + "".join(f"{idx:>10}" for idx in idx_labels)
    lines.append(header2)
    lines.append("-" * len(header2))

    sorted_sectors = sorted(sector_data.items(),
                            key=lambda x: x[1][1].get("SPY", 0), reverse=True)
    for ticker, (label, corrs) in sorted_sectors:
        row = f"{label:<14}"
        for idx in idx_labels:
            v = corrs.get(idx, np.nan)
            row += f"{v:>+10.2f}" if not np.isnan(v) else f"{'N/A':>10}"
        lines.append(row)

    lines.append("```")
    lines.append("")

    # Notable insights
    insights = []
    for ticker, (label, corrs) in sorted_macro:
        for idx in idx_labels:
            r = corrs.get(idx, 0)
            if not np.isnan(r) and abs(r) >= 0.6:
                d = "positively" if r > 0 else "inversely"
                insights.append(f"{idx} strongly {d} correlated with {label} ({r:+.2f})")

    if "QQQ" in idx_labels and "IWM" in idx_labels:
        for ticker, (label, corrs) in sorted_sectors:
            q, i = corrs.get("QQQ", 0), corrs.get("IWM", 0)
            if abs(q - i) >= 0.15:
                leader = "QQQ" if q > i else "IWM"
                insights.append(f"{label} tilts toward {leader} (QQQ:{q:+.2f} vs IWM:{i:+.2f})")

    if insights:
        lines.append("**Notable:**")
        for ins in insights[:8]:
            lines.append(f"- {ins}")

    return "\n".join(lines), macro_data, sector_data


# ─── REPORT 2: ECONOMIC PREDICTOR ────────────────────────────────

ECON_SERIES = {
    "PAYEMS": ("Nonfarm Payrolls", "chg"), "UNRATE": ("Unemployment", "chg"),
    "CPIAUCSL": ("CPI", "pct"), "CPILFESL": ("Core CPI", "pct"),
    "PCEPI": ("PCE Prices", "pct"), "HOUST": ("Housing Starts", "pct"),
    "RSAFS": ("Retail Sales", "pct"), "INDPRO": ("Indust. Prod.", "pct"),
    "DGORDER": ("Durable Goods", "pct"), "UMCSENT": ("Consumer Sent.", "chg"),
    "ICSA": ("Jobless Claims", "chg"), "MANEMP": ("Mfg Employment", "chg"),
    "CES0500000003": ("Avg Hourly Earn", "pct"),
}


def build_econ_report(fred_data: dict, price_data: dict, now_et: datetime) -> str:
    """Build economic predictor report."""
    indexes = ["SPY", "QQQ", "IWM"]

    # Need 10y monthly data for meaningful regressions — fetch via Yahoo Chart API
    monthly_returns = {}
    for idx in indexes:
        close = fetch_close(idx, period="10y", interval="1mo")
        if close is not None:
            ret = close.resample("ME").last().pct_change().dropna() * 100
            if len(ret) >= 24:
                monthly_returns[idx] = ret

    if not monthly_returns:
        return "", {}

    halflife = 18
    results = {}

    for sid, (name, transform) in ECON_SERIES.items():
        if sid not in fred_data or len(fred_data[sid]) < 24:
            continue

        series = fred_data[sid]
        if transform == "chg":
            indicator = series.diff().dropna()
        elif transform == "pct":
            indicator = series.pct_change().dropna() * 100
        else:
            indicator = series
        indicator = indicator.resample("ME").last().dropna()

        results[sid] = {"name": name}
        for idx in indexes:
            if idx not in monthly_returns:
                continue

            ret = monthly_returns[idx]
            fwd_1m = ret.shift(-1).dropna()
            fwd_3m = ret.shift(-1).rolling(3).sum().shift(-2).dropna()

            for horizon, fwd in [("1m", fwd_1m), ("3m", fwd_3m)]:
                df = pd.DataFrame({"ind": indicator, "fwd": fwd}).dropna()
                if len(df) < 24:
                    continue
                corr = fast_ewm_corr(df["ind"].values, df["fwd"].values, halflife)
                n = len(df)
                eff_n = min(n, halflife * 3)
                t_stat = corr * np.sqrt(eff_n - 2) / np.sqrt(1 - corr**2 + 1e-10) if not np.isnan(corr) else 0
                results[sid].setdefault(idx, {})[horizon] = {
                    "corr": round(corr, 3) if not np.isnan(corr) else 0,
                    "t_stat": round(t_stat, 2),
                    "significant": abs(t_stat) >= 1.65,
                    "strong": abs(t_stat) >= 2.0,
                }

    # Format
    lines = [f"**Economic Predictor Model** ({now_et.strftime('%a %b %d')}) | halflife={halflife}mo", ""]

    for horizon, label in [("1m", "1-Month Forward"), ("3m", "3-Month Forward")]:
        lines.append(f"**{label} Prediction**")
        lines.append("```")
        header = f"{'Indicator':<16} {'SPY':>8} {'QQQ':>8} {'IWM':>8}"
        lines.append(header)
        lines.append("-" * len(header))

        sorted_sids = []
        for sid in results:
            if "name" not in results[sid]:
                continue
            t_stats = []
            for idx in indexes:
                s = results[sid].get(idx, {}).get(horizon)
                if s:
                    t_stats.append(abs(s["t_stat"]))
            if t_stats:
                sorted_sids.append((sid, np.mean(t_stats)))
        sorted_sids.sort(key=lambda x: x[1], reverse=True)

        for sid, _ in sorted_sids:
            name = results[sid]["name"]
            row = f"{name:<16}"
            for idx in indexes:
                s = results[sid].get(idx, {}).get(horizon)
                if s:
                    m = "*" if s["strong"] else "~" if s["significant"] else " "
                    row += f"{s['corr']:>+7.2f}{m}"
                else:
                    row += f"{'N/A':>8}"
            lines.append(row)

        lines.append("```")
        if horizon == "1m":
            lines.append("")

    # Significant insights
    insights = []
    for sid, _ in sorted_sids:
        name = results[sid]["name"]
        for idx in indexes:
            for hz in ["1m", "3m"]:
                s = results[sid].get(idx, {}).get(hz)
                if s and s["strong"]:
                    d = "bullish" if s["corr"] > 0 else "bearish"
                    insights.append(f"{name} → {idx} ({hz}): {d} (r={s['corr']:+.2f}, t={s['t_stat']:.1f})")
    if insights:
        lines.append("")
        lines.append("**Significant (p<0.05):**")
        for i in insights[:6]:
            lines.append(f"- {i}")

    return "\n".join(lines), results


# ─── REPORT 3: FX MODELS ─────────────────────────────────────────

FX_PAIRS = {
    "EURUSD=X": ("EUR/USD", "USD_per_EUR", "IRLTLT01DEM156N", None),
    "USDJPY=X": ("USD/JPY", "JPY_per_USD", "IRLTLT01JPM156N", None),
    "GBPUSD=X": ("GBP/USD", "USD_per_GBP", "IRLTLT01GBM156N", None),
    "AUDUSD=X": ("AUD/USD", "USD_per_AUD", "IRLTLT01AUM156N", "GC=F"),
    "USDCAD=X": ("USD/CAD", "CAD_per_USD", "IRLTLT01CAM156N", "CL=F"),
}


def build_fx_report(price_data: dict, fred_data: dict, now_et: datetime) -> str:
    """Build FX models report."""
    us_2y = fred_data.get("DGS2")
    spy_ret = price_data["SPY"].pct_change().dropna() if "SPY" in price_data else None

    pair_results = []
    for ticker, (name, quote, rate_id, commodity) in FX_PAIRS.items():
        if ticker not in price_data:
            continue
        close = price_data[ticker]
        price = close.iloc[-1]

        # Momentum
        if len(close) >= 200:
            sma20 = close.rolling(20).mean().iloc[-1]
            sma50 = close.rolling(50).mean().iloc[-1]
            sma200 = close.rolling(200).mean().iloc[-1]
            mom_score = sum(1 if price > ma else -1 for ma in [sma20, sma50, sma200])
            pct_200 = round((price / sma200 - 1) * 100, 1)
        else:
            mom_score, pct_200 = 0, 0.0

        # Mean reversion
        if len(close) >= 120:
            mean100 = close.rolling(100).mean().iloc[-1]
            std100 = close.rolling(100).std().iloc[-1]
            zscore = round(float((price - mean100) / std100), 2) if std100 > 0 else 0.0
        else:
            zscore = 0.0

        # Carry
        carry_sig, carry_diff, us_r, for_r = "N/A", 0.0, 0.0, 0.0
        foreign_rate = fred_data.get(rate_id)
        if us_2y is not None and foreign_rate is not None and len(us_2y) > 0 and len(foreign_rate) > 0:
            us_r = us_2y.iloc[-1]
            for_r = foreign_rate.iloc[-1]
            carry_diff = round(us_r - for_r, 2)
            if "per_USD" in quote:
                carry_sig = "LONG" if carry_diff > 0.5 else "SHORT" if carry_diff < -0.5 else "NEUTR"
            else:
                carry_sig = "SHORT" if carry_diff > 0.5 else "LONG" if carry_diff < -0.5 else "NEUTR"

        # Equity beta
        eq_corr = 0.0
        if spy_ret is not None:
            fx_ret = close.pct_change().dropna()
            df = pd.DataFrame({"fx": fx_ret, "spy": spy_ret}).dropna()
            if len(df) >= 60:
                eq_corr = fast_ewm_corr(df["fx"].values, df["spy"].values, 21)

        # Commodity link
        com_corr, com_name = None, None
        if commodity and commodity in price_data:
            fx_ret = close.pct_change().dropna()
            com_ret = price_data[commodity].pct_change().dropna()
            df = pd.DataFrame({"fx": fx_ret, "com": com_ret}).dropna()
            if len(df) >= 60:
                com_corr = fast_ewm_corr(df["fx"].values, df["com"].values, 21)
                com_name = "Oil" if commodity == "CL=F" else "Gold"

        # Composite signal
        score, wt = 0, 0
        score += mom_score; wt += 3
        if abs(zscore) > 0.5:
            score += (-2 if zscore > 1.5 else -1 if zscore > 0.5 else 2 if zscore < -1.5 else 1)
            wt += 2
        if carry_sig == "LONG": score += 2; wt += 2
        elif carry_sig == "SHORT": score -= 2; wt += 2
        elif carry_sig == "NEUTR": wt += 2
        if abs(eq_corr) > 0.3:
            score += (1 if eq_corr > 0.3 else -1); wt += 1

        norm = score / wt if wt > 0 else 0
        net = ("BULLISH" if norm > 0.6 else "LEAN LONG" if norm > 0.3 else
               "BEARISH" if norm < -0.6 else "LEAN SHORT" if norm < -0.3 else "NEUTRAL")

        pair_results.append({
            "name": name, "ticker": ticker, "price": price, "mom_score": mom_score,
            "pct_200": pct_200, "zscore": zscore, "carry_sig": carry_sig,
            "carry_diff": carry_diff, "us_r": us_r, "for_r": for_r,
            "eq_corr": eq_corr, "com_corr": com_corr, "com_name": com_name, "net": net,
        })

    # DXY context
    dxy_line = ""
    if "DX-Y.NYB" in price_data and len(price_data["DX-Y.NYB"]) >= 200:
        dxy = price_data["DX-Y.NYB"]
        dxy_price = dxy.iloc[-1]
        dxy_200 = dxy.rolling(200).mean().iloc[-1]
        dxy_score = sum(1 if dxy_price > ma else -1 for ma in
                        [dxy.rolling(20).mean().iloc[-1], dxy.rolling(50).mean().iloc[-1], dxy_200])
        dxy_sig = "BULLISH" if dxy_score >= 2 else "BEARISH" if dxy_score <= -2 else "NEUTRAL"
        dxy_pct = round((dxy_price / dxy_200 - 1) * 100, 1)
        dxy_line = f"**Dollar Index (DXY)**: {dxy_price:.2f} | {dxy_sig} | {dxy_pct:+.1f}% from 200d"

    # Format
    lines = [f"**FX Models** ({now_et.strftime('%a %b %d')})", ""]
    if dxy_line:
        lines.append(dxy_line)
        lines.append("")

    lines.append("**Signal Dashboard**")
    lines.append("```")
    header = f"{'Pair':<10} {'Price':>8} {'Mom':>5} {'ZScr':>6} {'Carry':>6} {'EqB':>6} {'NET':>10}"
    lines.append(header)
    lines.append("-" * len(header))

    for r in pair_results:
        lines.append(
            f"{r['name']:<10} {r['price']:>8.4f} {r['mom_score']:>+5d} {r['zscore']:>+6.1f} "
            f"{r['carry_sig']:>6} {r['eq_corr']:>+5.2f} {r['net']:>10}"
        )
    lines.append("```")
    lines.append("")

    lines.append("**Detail**")
    for r in pair_results:
        parts = [f"**{r['name']}**", f"{r['pct_200']:+.1f}% from 200d"]
        if r["carry_sig"] != "N/A":
            parts.append(f"carry: {r['carry_diff']:+.1f}% (US:{r['us_r']:.1f}% vs {r['for_r']:.1f}%)")
        if r["com_corr"] is not None:
            parts.append(f"{r['com_name']} corr: {r['com_corr']:+.2f}")
        lines.append(" | ".join(parts))

    return "\n".join(lines)


# ─── REPORT 4: RETAIL SALES DATA EXTRACTION ──────────────────────

def build_retail_sales_report(fred_data: dict, now_et: datetime) -> str:
    """Build retail sales data extraction report from FRED RSAFS series."""
    rsafs = fred_data.get("RSAFS")
    if rsafs is None or len(rsafs) < 13:
        return ""

    latest = rsafs.iloc[-1]
    prev = rsafs.iloc[-2]
    year_ago = rsafs.iloc[-13]  # 12 months back from previous

    mom_chg = (latest / prev - 1) * 100
    yoy_chg = (latest / year_ago - 1) * 100

    # 3-month annualized trend
    trend_3m = None
    if len(rsafs) >= 4:
        three_mo_ago = rsafs.iloc[-4]
        trend_3m = ((latest / three_mo_ago) ** 4 - 1) * 100

    # 6-month annualized trend
    trend_6m = None
    if len(rsafs) >= 7:
        six_mo_ago = rsafs.iloc[-7]
        trend_6m = ((latest / six_mo_ago) ** 2 - 1) * 100

    latest_date = rsafs.index[-1].strftime("%b %Y")

    lines = [f"**Retail Sales Report** ({now_et.strftime('%a %b %d')})", ""]
    lines.append(f"Latest: ${latest:,.0f}M ({latest_date})")
    lines.append(f"MoM Change: {mom_chg:+.2f}%")
    lines.append(f"YoY Change: {yoy_chg:+.2f}%")
    if trend_3m is not None:
        lines.append(f"3-Mo Trend (ann.): {trend_3m:+.1f}%")
    if trend_6m is not None:
        lines.append(f"6-Mo Trend (ann.): {trend_6m:+.1f}%")

    # Spending direction signal
    if mom_chg > 0.5:
        signal = "EXPANDING"
    elif mom_chg < -0.5:
        signal = "CONTRACTING"
    else:
        signal = "FLAT"
    lines.append(f"Consumer Spending Signal: **{signal}**")

    # Recent 6-month history table
    lines.append("")
    lines.append("**Recent History:**")
    lines.append("```")
    header = f"{'Month':<10} {'Value ($M)':>12} {'MoM%':>8} {'YoY%':>8}"
    lines.append(header)
    lines.append("-" * len(header))

    lookback = min(6, len(rsafs) - 13)
    for i in range(-lookback, 0):
        val = rsafs.iloc[i]
        date_label = rsafs.index[i].strftime("%b %Y")
        prev_val = rsafs.iloc[i - 1]
        yoy_val = rsafs.iloc[i - 12] if abs(i) + 12 <= len(rsafs) else None
        m_chg = (val / prev_val - 1) * 100
        y_chg = (val / yoy_val - 1) * 100 if yoy_val is not None else float("nan")
        y_str = f"{y_chg:>+8.2f}%" if not np.isnan(y_chg) else f"{'N/A':>9}"
        lines.append(f"{date_label:<10} {val:>12,.0f} {m_chg:>+8.2f}%{y_str}")

    lines.append("```")

    return "\n".join(lines)


# ─── REPORT 5: JOBS REPORT (NFP + UNEMPLOYMENT + WAGE GROWTH) ────

def build_jobs_report(fred_data: dict, now_et: datetime) -> str:
    """Build combined Jobs Report: Nonfarm Payrolls, Unemployment Rate, Avg Hourly Earnings."""
    payems = fred_data.get("PAYEMS")
    unrate = fred_data.get("UNRATE")
    ahe = fred_data.get("CES0500000003")

    if payems is None or len(payems) < 13:
        return ""

    lines = [f"**Jobs Report Summary** ({now_et.strftime('%a %b %d')})", ""]

    # ── Nonfarm Payrolls ──
    nfp_latest = payems.iloc[-1]
    nfp_prev = payems.iloc[-2]
    nfp_chg = nfp_latest - nfp_prev  # thousands of jobs added
    nfp_3m_avg = np.mean([payems.iloc[-i] - payems.iloc[-i - 1] for i in range(1, 4)]) if len(payems) >= 4 else None
    nfp_date = payems.index[-1].strftime("%b %Y")

    lines.append(f"**Nonfarm Payrolls** ({nfp_date})")
    lines.append(f"  Jobs Added: {nfp_chg:+,.0f}K")
    if nfp_3m_avg is not None:
        lines.append(f"  3-Mo Avg: {nfp_3m_avg:+,.0f}K")
    lines.append("")

    # ── Unemployment Rate ──
    if unrate is not None and len(unrate) >= 13:
        ur_latest = unrate.iloc[-1]
        ur_prev = unrate.iloc[-2]
        ur_yoy = unrate.iloc[-13]
        ur_chg = ur_latest - ur_prev
        ur_yoy_chg = ur_latest - ur_yoy
        ur_date = unrate.index[-1].strftime("%b %Y")

        lines.append(f"**Unemployment Rate** ({ur_date})")
        lines.append(f"  Rate: {ur_latest:.1f}%")
        lines.append(f"  MoM Change: {ur_chg:+.1f}pp")
        lines.append(f"  YoY Change: {ur_yoy_chg:+.1f}pp")
        lines.append("")

    # ── Average Hourly Earnings (Wage Growth) ──
    if ahe is not None and len(ahe) >= 13:
        ahe_latest = ahe.iloc[-1]
        ahe_prev = ahe.iloc[-2]
        ahe_yoy = ahe.iloc[-13]
        ahe_mom = (ahe_latest / ahe_prev - 1) * 100
        ahe_yoy_chg = (ahe_latest / ahe_yoy - 1) * 100
        ahe_date = ahe.index[-1].strftime("%b %Y")

        # 3-month annualized wage trend
        ahe_trend_3m = None
        if len(ahe) >= 4:
            ahe_trend_3m = ((ahe_latest / ahe.iloc[-4]) ** 4 - 1) * 100

        # Wage-inflation signal
        if ahe_yoy_chg > 4.0:
            wage_signal = "HOT — inflationary pressure"
        elif ahe_yoy_chg > 3.0:
            wage_signal = "WARM — above Fed comfort"
        elif ahe_yoy_chg > 2.0:
            wage_signal = "MODERATE — within range"
        else:
            wage_signal = "COOL — disinflation"

        lines.append(f"**Avg Hourly Earnings** ({ahe_date})")
        lines.append(f"  Hourly Rate: ${ahe_latest:.2f}/hr")
        lines.append(f"  MoM Change: {ahe_mom:+.2f}%")
        lines.append(f"  YoY Change: {ahe_yoy_chg:+.2f}%")
        if ahe_trend_3m is not None:
            lines.append(f"  3-Mo Trend (ann.): {ahe_trend_3m:+.1f}%")
        lines.append(f"  Wage Signal: **{wage_signal}**")
        lines.append("")

    # ── Combined history table ──
    lines.append("**Recent History:**")
    lines.append("```")
    header = f"{'Month':<10} {'Jobs(K)':>8} {'URate%':>8} {'AHE$/hr':>8} {'WageYoY':>8}"
    lines.append(header)
    lines.append("-" * len(header))

    lookback = min(6, len(payems) - 13)
    for i in range(-lookback, 0):
        date_label = payems.index[i].strftime("%b %Y")
        jobs = payems.iloc[i] - payems.iloc[i - 1]
        ur_str = f"{unrate.iloc[i]:>8.1f}" if unrate is not None and abs(i) < len(unrate) else f"{'N/A':>8}"
        if ahe is not None and abs(i) < len(ahe) and abs(i) + 12 <= len(ahe):
            w_yoy = (ahe.iloc[i] / ahe.iloc[i - 12] - 1) * 100
            ahe_str = f"{ahe.iloc[i]:>8.2f}"
            wyoy_str = f"{w_yoy:>+8.1f}%"
        else:
            ahe_str = f"{'N/A':>8}"
            wyoy_str = f"{'N/A':>9}"
        lines.append(f"{date_label:<10} {jobs:>+8.0f}{ur_str}{ahe_str}{wyoy_str}")

    lines.append("```")

    return "\n".join(lines)


# ─── MODEL STATE ──────────────────────────────────────────────────

def save_model_state(fred_data, econ_results, macro_corrs, sector_corrs, now_et):
    """Save model coefficients + latest FRED values for econ-release-analysis.py."""
    state = {
        "updated": now_et.strftime("%Y-%m-%d %H:%M"),
        "econ": {},
        "sectors": {},
        "macro": {},
    }

    # Econ predictor: correlations + latest values per FRED series
    for sid, data in econ_results.items():
        if "name" not in data:
            continue
        entry = {
            "name": data["name"],
            "transform": ECON_SERIES[sid][1],
        }
        if sid in fred_data:
            s = fred_data[sid]
            entry["latest_date"] = s.index[-1].strftime("%Y-%m-%d")
            entry["latest_raw"] = round(float(s.iloc[-1]), 4)
            if len(s) >= 2:
                entry["prev_raw"] = round(float(s.iloc[-2]), 4)
        for hz in ["1m", "3m"]:
            for idx in ["SPY", "QQQ", "IWM"]:
                stats = data.get(idx, {}).get(hz)
                if stats:
                    entry.setdefault(hz, {})[idx] = {
                        "corr": stats["corr"],
                        "t_stat": stats["t_stat"],
                    }
        state["econ"][sid] = entry

    # Sector correlations with indexes
    for ticker, (label, corrs) in sector_corrs.items():
        state["sectors"][ticker] = {"name": label}
        for idx, r in corrs.items():
            if not np.isnan(r):
                state["sectors"][ticker][idx] = round(r, 3)

    # Macro variable correlations with indexes
    for ticker, (label, corrs) in macro_corrs.items():
        state["macro"][ticker] = {"name": label}
        for idx, r in corrs.items():
            if not np.isnan(r):
                state["macro"][ticker][idx] = round(r, 3)

    try:
        with open(MODEL_STATE, "w") as f:
            json.dump(state, f, indent=2)
        print(f"  Model state saved ({len(state['econ'])} econ, {len(state['sectors'])} sectors)")
    except Exception as e:
        print(f"  Failed to save model state: {e}")


# ─── MAIN ─────────────────────────────────────────────────────────

def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting econometrics report")

    # ── 1. Parallel Yahoo Chart API download (all 28 tickers) ──
    corr_tickers = INDEXES + list(MACRO_VARS.keys()) + list(SECTORS.keys())
    fx_tickers = list(FX_PAIRS.keys()) + ["CL=F", "GC=F"]
    all_tickers = list(set(corr_tickers + fx_tickers))  # Deduplicate
    print(f"Fetching {len(all_tickers)} tickers via Yahoo Chart API...")
    price_data = batch_download(all_tickers, period="2y")
    print(f"Got data for {len(price_data)} tickers")

    # ── 2. Load FRED data (cached or fresh) ──
    fred_data = load_fred_data()
    print(f"FRED: {len(fred_data)} series loaded")

    # ── 3. Build all 3 reports ──
    msg1, macro_corrs, sector_corrs = build_correlation_report(price_data, now_et)
    if msg1:
        if len(msg1) > 1950:
            split = msg1.index("**Indexes vs Sectors**")
            send_discord(msg1[:split].strip())
            send_discord(msg1[split:].strip())
        else:
            send_discord(msg1)
        print(f"  Correlation matrix: {len(msg1)} chars")

    msg2, econ_results = build_econ_report(fred_data, price_data, now_et)
    if msg2:
        if len(msg2) > 1950:
            split = msg2.index("**3-Month Forward")
            send_discord(msg2[:split].strip())
            send_discord(msg2[split:].strip())
        else:
            send_discord(msg2)
        print(f"  Economic predictor: {len(msg2)} chars")

    msg3 = build_fx_report(price_data, fred_data, now_et)
    if msg3:
        send_discord(msg3)
        print(f"  FX models: {len(msg3)} chars")

    msg4 = build_retail_sales_report(fred_data, now_et)
    if msg4:
        send_discord(msg4)
        print(f"  Retail sales: {len(msg4)} chars")

    msg5 = build_jobs_report(fred_data, now_et)
    if msg5:
        send_discord(msg5)
        print(f"  Jobs report: {len(msg5)} chars")

    # ── 4. Save model state for release analysis ──
    if econ_results:
        save_model_state(fred_data, econ_results, macro_corrs, sector_corrs, now_et)

    # Popen sends complete independently after script exits
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Econometrics report complete")


if __name__ == "__main__":
    main()
