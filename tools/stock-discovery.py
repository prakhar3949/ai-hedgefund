"""
Dynamic Stock Discovery Scanner
Bridges the gap between "hot subsector identified" and "buy this specific stock."

Pulls holdings from top subsector ETFs, fetches 6-month daily OHLCV for every
constituent, and ranks them using a multi-factor composite:

  Module 1: Relative Strength vs Subsector ETF    (30%)
  Module 2: Momentum Composite                    (25%)
  Module 3: Volume Characteristics                (25%)
  Module 4: Technical Setup Quality               (20%)
  Module 5: Risk Filters (flags, no score impact)

Input:
  - Default: reads sector-rotation.py / rrg-scanner.py output to pick top ETFs
  - Override: python stock-discovery.py SMH XRT ITA   (manual ETF list)

Output:
  - Top 10 ranked stocks per subsector ETF
  - Scatter chart (X=Momentum, Y=RS, size=Volume, color=Technical)
  - Posted to Discord

Cost: $0.00 (Yahoo Chart API, no API key needed)
"""

import io
import json
import sys
import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

# ── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1473040356659564565/"
    "g5-0D2rF-SsnUk_p-4uejtmUht56AkNY2E4pffKpnjXOCFIOlrQmugL_6BdQZzl-hatc"
)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ── Cap-Weighted Sector ETF names ─────────────────────────────────────────────
CW_SECTOR_NAMES = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Health Care", "XLI": "Industrials", "XLP": "Cons. Staples",
    "XLY": "Cons. Discret.", "XLU": "Utilities", "XLC": "Comms",
    "XLB": "Materials", "XLRE": "Real Estate","IBB": "Biotech"
}

# ── Equal-Weight Sector ETF names ─────────────────────────────────────────────
EW_SECTOR_NAMES = {
    "RSPT": "EW Technology", "RSPF": "EW Financials", "RSPG": "EW Energy",
    "RSPH": "EW Health Care", "RSPN": "EW Industrials", "RSPS": "EW Staples",
    "RSPD": "EW Discret.", "RSPU": "EW Utilities", "RSPC": "EW Comms",
    "RSPM": "EW Materials", "RSPR": "EW Real Estate", "XBI": "EW Biotech",
}

# ── CW <-> EW mapping ────────────────────────────────────────────────────────
CW_TO_EW = {
    "XLK": "RSPT", "XLF": "RSPF", "XLE": "RSPG", "XLV": "RSPH",
    "XLI": "RSPN", "XLP": "RSPS", "XLY": "RSPD", "XLU": "RSPU",
    "XLC": "RSPC", "XLB": "RSPM", "XLRE": "RSPR", "IBB": "XBI",
}
EW_TO_CW = {v: k for k, v in CW_TO_EW.items()}

# ── Subsector -> parent CW sector mapping ────────────────────────────────────
SUBSECTOR_TO_CW = {
    "SMH": "XLK", "IGV": "XLK", "CIBR": "XLK", "AIQ": "XLK", "QTUM": "XLK",
    "BOTZ": "XLI", "IBB": "XLV", "IHI": "XLV", "ARKG": "XLV",
    "KRE": "XLF", "ITB": "XLY", "VNQ": "XLRE", "XRT": "XLY",
    "ITA": "XLI", "IYT": "XLI", "JETS": "XLI", "SLX": "XLB",
    "GDX": "XLB", "SIL": "XLB", "TAN": "XLE", "KWEB": "XLC",
    "SOCL": "XLC", "IYZ": "XLC", "BETZ": "XLY"
}

# Sectors with no or weak subsector ETF coverage
SECTORS_NO_SUBSECTORS = {"XLP", "XLU", "IBB"}
SECTORS_WEAK_COVERAGE = {"XLE", "XLF"}

# ── Subsector ETF names (same as sector-rotation.py) ─────────────────────────
SUBSECTOR_NAMES = {
    "SMH": "Semiconductors", "IGV": "Software", "CIBR": "Cybersecurity",
    "AIQ": "AI & Big Data", "QTUM": "Quantum/AI", "BOTZ": "Robotics",
    "IBB": "Biotech", "IHI": "Med Devices", "ARKG": "Genomics",
    "KRE": "Reg. Banks", "ITB": "Homebuilders", "VNQ": "REITs",
    "XRT": "Retail", "ITA": "Aerospace", "IYT": "Transport",
    "JETS": "Airlines", "SLX": "Steel", "GDX": "Gold Miners",
    "SIL": "Silver Min.", "TAN": "Solar", "KWEB": "China Tech",
    "SOCL": "Social Media", "IYZ": "Telecom", "BETZ": "Sports Bet",
    "IBIT": "Bitcoin", "VUG": "Growth",
}

# Default top ETFs if no CLI args and no auto-detection
DEFAULT_ETFS = ["SMH", "XRT", "ITB"]


# ── Data Fetching ────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str = "6mo") -> pd.DataFrame | None:
    """Fetch OHLCV data from Yahoo Finance chart API."""
    # Yahoo uses hyphens not dots (BRK-B not BRK.B, MOG-A not MOG.A)
    yticker = ticker.replace(".", "-")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yticker}"
        f"?range={period}&interval=1d"
    )
    try:
        resp = requests.get(url, headers=YAHOO_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        timestamps = result[0]["timestamp"]
        quote = result[0]["indicators"]["quote"][0]
        df = pd.DataFrame({
            "Open": quote["open"],
            "High": quote["high"],
            "Low": quote["low"],
            "Close": quote["close"],
            "Volume": quote["volume"],
        }, index=pd.to_datetime(timestamps, unit="s"))
        df = df.dropna(subset=["Close"])
        return df if len(df) >= 50 else None
    except Exception:
        return None


def batch_fetch(tickers: list[str], period: str = "6mo") -> dict[str, pd.DataFrame]:
    """Parallel fetch OHLCV for multiple tickers."""
    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fetch_ohlcv, t, period): t for t in tickers}
        for f in as_completed(futures):
            t = futures[f]
            try:
                df = f.result()
                if df is not None:
                    results[t] = df
            except Exception:
                pass
    return results


def load_etf_holdings() -> dict:
    """Load ETF holdings from etf-holdings.json."""
    path = TOOLS_DIR / "etf-holdings.json"
    with open(path) as f:
        data = json.load(f)
    return data


# ── Discord ──────────────────────────────────────────────────────────────────

def send_discord_text(text: str):
    if len(text) > 1950:
        text = text[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Discord text failed: {e}")


def send_discord_image(buf: io.BytesIO, filename: str):
    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            files={"file": (filename, buf, "image/png")},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  Discord image failed: {e}")


# ── Module 1: Relative Strength vs Subsector ETF ────────────────────────────

def score_relative_strength(stock_close: pd.Series, etf_close: pd.Series) -> dict:
    """
    Mansfield Relative Strength — stock/ETF normalized to zero line.
    Returns RS percentile rank, RS trend slope.
    """
    # Align on common dates
    common = stock_close.index.intersection(etf_close.index)
    if len(common) < 50:
        return {"rs_score": 50.0, "rs_ratio": 0.0, "rs_slope": 0.0}

    sc = stock_close.loc[common]
    ec = etf_close.loc[common]

    # RS ratio line
    rs_line = sc / ec

    # Mansfield RS: normalize to 0 using SMA(50) of RS line
    rs_sma = rs_line.rolling(50).mean()
    mansfield = ((rs_line / rs_sma) - 1) * 100
    current_rs = mansfield.iloc[-1] if not np.isnan(mansfield.iloc[-1]) else 0.0

    # RS 3-month return (percentile proxy)
    rs_3m = (rs_line.iloc[-1] / rs_line.iloc[-63] - 1) * 100 if len(rs_line) >= 63 else 0.0

    # RS trend: 10-day slope of RS line (rising = gaining leadership)
    rs_recent = rs_line.iloc[-10:].values
    if len(rs_recent) == 10:
        x = np.arange(10)
        slope = np.polyfit(x, rs_recent, 1)[0]
        rs_slope = slope / rs_recent.mean() * 100  # normalize as %
    else:
        rs_slope = 0.0

    return {
        "rs_score": float(current_rs),  # raw score, will percentile-rank later
        "rs_3m": float(rs_3m),
        "rs_slope": float(rs_slope),
    }


# ── Module 2: Momentum Composite ────────────────────────────────────────────

def score_momentum(df: pd.DataFrame) -> dict:
    """
    Momentum composite: weighted ROC + MA alignment + MACD histogram direction.
    """
    close = df["Close"]
    n = len(close)

    # Rate of Change
    roc5 = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if n >= 6 else 0.0
    roc20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if n >= 21 else 0.0
    roc63 = (close.iloc[-1] / close.iloc[-64] - 1) * 100 if n >= 64 else 0.0

    # Weighted composite
    mom_score = 0.4 * roc5 + 0.35 * roc20 + 0.25 * roc63

    # MA Alignment check: Price > EMA10 > EMA21 > SMA50 > SMA200
    price = close.iloc[-1]
    ema10 = close.ewm(span=10).mean().iloc[-1]
    ema21 = close.ewm(span=21).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1] if n >= 200 else np.nan

    alignment = 0
    if price > ema10:
        alignment += 1
    if ema10 > ema21:
        alignment += 1
    if ema21 > sma50:
        alignment += 1
    if not np.isnan(sma200) and sma50 > sma200:
        alignment += 1

    # MACD histogram direction
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9).mean()
    hist = macd_line - signal
    macd_rising = hist.iloc[-1] > hist.iloc[-2] if n >= 2 else False

    return {
        "mom_raw": float(mom_score),  # will percentile-rank later
        "roc5": float(roc5),
        "roc20": float(roc20),
        "roc63": float(roc63),
        "ma_alignment": alignment,     # 0-4
        "macd_rising": bool(macd_rising),
    }


# ── Module 3: Volume Characteristics ────────────────────────────────────────

def score_volume(df: pd.DataFrame) -> dict:
    """
    Volume analysis: relative volume, up/down ratio, A/D line, CMF.
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    n = len(df)

    # Relative Volume: 5-day avg / 20-day avg
    vol5 = volume.iloc[-5:].mean()
    vol20 = volume.iloc[-20:].mean() if n >= 20 else vol5
    rel_vol = vol5 / vol20 if vol20 > 0 else 1.0

    # Up/Down Volume Ratio (20 days)
    changes = close.diff()
    recent = changes.iloc[-20:]
    recent_vol = volume.iloc[-20:]
    up_vol = recent_vol[recent > 0].sum()
    dn_vol = recent_vol[recent < 0].sum()
    ud_ratio = up_vol / dn_vol if dn_vol > 0 else 2.0

    # Volume trend on advances (10-day regression on up-day volumes)
    up_days = [(i, v) for i, (c, v) in enumerate(zip(changes.iloc[-10:], volume.iloc[-10:])) if c > 0]
    vol_trend = 0.0
    if len(up_days) >= 3:
        x = np.array([u[0] for u in up_days])
        y = np.array([u[1] for u in up_days], dtype=float)
        if y.mean() > 0:
            slope = np.polyfit(x, y, 1)[0]
            vol_trend = slope / y.mean()

    # Chaikin Money Flow (20-day)
    mfm = ((close - low) - (high - close)) / (high - low + 1e-10)
    mfv = mfm * volume
    cmf20 = mfv.iloc[-20:].sum() / volume.iloc[-20:].sum() if n >= 20 else 0.0

    # Composite volume score (raw, will percentile-rank later)
    # Normalize components: rel_vol centered at 1, ud_ratio centered at 1, cmf centered at 0
    vol_composite = (
        0.25 * min(rel_vol, 3.0) / 3.0 * 100 +           # 0-100, higher rel vol = better
        0.30 * min(ud_ratio, 3.0) / 3.0 * 100 +           # 0-100, higher ratio = better
        0.20 * (cmf20 + 1.0) / 2.0 * 100 +                # 0-100, -1 to +1 mapped to 0-100
        0.25 * min(max(vol_trend + 0.5, 0), 1.0) * 100    # 0-100
    )

    return {
        "vol_raw": float(vol_composite),
        "rel_vol": round(float(rel_vol), 2),
        "ud_ratio": round(float(ud_ratio), 2),
        "cmf20": round(float(cmf20), 3),
        "vol_trend": round(float(vol_trend), 3),
    }


# ── Module 4: Technical Setup Quality ───────────────────────────────────────

def score_technical(df: pd.DataFrame) -> dict:
    """
    Technical quality: ADX trend strength, RSI position, Bollinger position,
    distance from 52-week high, ATR compression.
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    n = len(df)
    price = close.iloc[-1]

    # --- ADX(14) ---
    tr = pd.concat([
        high - low,
        abs(high - close.shift()),
        abs(low - close.shift())
    ], axis=1).max(axis=1)

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    atr14 = tr.rolling(14).mean()
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr14)
    minus_di = 100 * (minus_dm.rolling(14).mean() / atr14)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = dx.rolling(14).mean()

    adx_val = adx.iloc[-1] if not np.isnan(adx.iloc[-1]) else 15.0
    bullish_trend = plus_di.iloc[-1] > minus_di.iloc[-1]

    # ADX score: trending (>25) and bullish = best
    if adx_val >= 25 and bullish_trend:
        adx_score = min(adx_val, 50) / 50 * 100  # 50-100
    elif adx_val >= 25 and not bullish_trend:
        adx_score = 20  # trending but bearish
    else:
        adx_score = 40  # weak trend

    # --- RSI(14) ---
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).iloc[-1]

    # RSI score: 50-65 ideal for pullback entry, avoid extremes
    if 50 <= rsi <= 65:
        rsi_score = 100
    elif 40 <= rsi < 50 or 65 < rsi <= 70:
        rsi_score = 70
    elif 30 <= rsi < 40 or 70 < rsi <= 75:
        rsi_score = 40
    else:
        rsi_score = 15  # overbought (>75) or oversold (<30)

    # --- Bollinger position ---
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_width = ((bb_upper - bb_lower) / bb_mid * 100)

    bb_pos = (price - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1] + 1e-10)
    bb_pos = min(max(bb_pos, 0), 1)

    # Near lower band in uptrend = pullback entry opportunity
    if bb_pos < 0.3 and bullish_trend:
        bb_score = 90  # pullback to lower band in uptrend
    elif 0.3 <= bb_pos <= 0.7:
        bb_score = 70  # middle of band, neutral
    elif bb_pos > 0.7 and adx_val > 25:
        bb_score = 60  # near upper band with trend = ok
    else:
        bb_score = 40

    # --- Distance from 52-week high ---
    high_52w = close.max()  # using available data (6mo max)
    dist_high = (1 - price / high_52w) * 100 if high_52w > 0 else 50.0

    if dist_high <= 5:
        dist_score = 100  # near highs
    elif dist_high <= 15:
        dist_score = 70   # healthy pullback zone
    elif dist_high <= 25:
        dist_score = 40   # deeper pullback
    else:
        dist_score = 15   # lagging

    # --- ATR compression ---
    atr_pct = (atr14 / close * 100)
    current_atr_pct = atr_pct.iloc[-1]
    avg_atr_pct = atr_pct.iloc[-60:].mean() if n >= 60 else atr_pct.mean()
    compression = current_atr_pct / avg_atr_pct if avg_atr_pct > 0 else 1.0

    # Low ATR compression = energy building, good for breakout
    if compression < 0.7:
        atr_score = 90  # tight consolidation
    elif compression < 0.9:
        atr_score = 70
    elif compression < 1.1:
        atr_score = 50  # normal
    else:
        atr_score = 30  # expanded volatility

    # Composite technical score
    tech_composite = (
        0.25 * adx_score +
        0.25 * rsi_score +
        0.15 * bb_score +
        0.20 * dist_score +
        0.15 * atr_score
    )

    return {
        "tech_raw": float(tech_composite),
        "adx": round(float(adx_val), 1),
        "rsi": round(float(rsi), 1),
        "bullish_trend": bool(bullish_trend),
        "bb_pos": round(float(bb_pos), 2),
        "dist_from_high": round(float(dist_high), 1),
        "atr_compression": round(float(compression), 2),
        "atr_pct": round(float(current_atr_pct), 2),
    }


# ── Module 5: Risk Filters ──────────────────────────────────────────────────

def apply_risk_filters(df: pd.DataFrame, ticker: str) -> list[str]:
    """
    Flag stocks with risk factors. Does NOT affect composite score.
    """
    flags = []
    close = df["Close"]
    volume = df["Volume"]
    price = close.iloc[-1]

    # Average daily volume < 500K
    avg_vol = volume.iloc[-20:].mean()
    if avg_vol < 500_000:
        flags.append("LOW LIQ")

    # Price below SMA(200)
    if len(close) >= 200:
        sma200 = close.rolling(200).mean().iloc[-1]
        if price < sma200:
            flags.append("BELOW 200MA")

    # RSI extremes
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).iloc[-1]
    if rsi > 80:
        flags.append("OVERBOUGHT")
    elif rsi < 20:
        flags.append("OVERSOLD")

    # Bottom quartile RS will be added later after percentile ranking

    return flags


# ── Percentile Ranking ───────────────────────────────────────────────────────

def percentile_rank(values: list[float]) -> list[float]:
    """Convert raw scores to 0-100 percentile ranks."""
    n = len(values)
    if n == 0:
        return []
    sorted_vals = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    for rank, idx in enumerate(sorted_vals):
        ranks[idx] = (rank / max(n - 1, 1)) * 100
    return ranks


# ── Composite Scoring ────────────────────────────────────────────────────────

def compute_composite(stocks: list[dict]) -> list[dict]:
    """
    Percentile-rank each module, then combine:
    Final Score = 0.30*RS + 0.25*Momentum + 0.25*Volume + 0.20*Technical
    """
    if not stocks:
        return []

    # Extract raw scores
    rs_raw = [s["rs_score"] for s in stocks]
    mom_raw = [s["mom_raw"] for s in stocks]
    vol_raw = [s["vol_raw"] for s in stocks]
    tech_raw = [s["tech_raw"] for s in stocks]

    # Percentile rank
    rs_pct = percentile_rank(rs_raw)
    mom_pct = percentile_rank(mom_raw)
    vol_pct = percentile_rank(vol_raw)
    tech_pct = percentile_rank(tech_raw)

    for i, s in enumerate(stocks):
        s["rs_pct"] = round(rs_pct[i], 1)
        s["mom_pct"] = round(mom_pct[i], 1)
        s["vol_pct"] = round(vol_pct[i], 1)
        s["tech_pct"] = round(tech_pct[i], 1)

        s["final_score"] = round(
            0.30 * rs_pct[i] +
            0.25 * mom_pct[i] +
            0.25 * vol_pct[i] +
            0.20 * tech_pct[i],
            1
        )

        # Add LOW RS flag if bottom quartile
        if rs_pct[i] < 25:
            s["flags"].append("LOW RS")

    # Sort by final score descending
    stocks.sort(key=lambda s: s["final_score"], reverse=True)
    return stocks


# ── Output Formatting ────────────────────────────────────────────────────────

def format_text_table(etf: str, name: str, stocks: list[dict], num_scanned: int) -> str:
    """Build monospace text table for Discord."""
    lines = []
    lines.append(f"{etf} — {name.upper()} ({num_scanned} constituents scanned)")
    lines.append("")
    lines.append("```")
    lines.append(f"{'RK':<4} {'TICKER':<7} {'SCORE':>6} {'RS%':>5} {'MOM%':>5} {'VOL%':>5} {'TECH%':>6}  FLAGS")
    lines.append("-" * 58)

    top10 = stocks[:10]
    for i, s in enumerate(top10, 1):
        flags_str = " ".join(s["flags"]) if s["flags"] else ""
        lines.append(
            f"{i:<4} {s['ticker']:<7} {s['final_score']:>6.1f} "
            f"{s['rs_pct']:>5.0f} {s['mom_pct']:>5.0f} {s['vol_pct']:>5.0f} {s['tech_pct']:>6.0f}"
            f"  {flags_str}"
        )

    lines.append("```")
    lines.append(
        "KEY: RS%=Relative Strength, MOM%=Momentum, VOL%=Volume, TECH%=Technical Quality"
    )
    return "\n".join(lines)


def render_scatter(etf: str, name: str, stocks: list[dict]) -> io.BytesIO:
    """Scatter plot: X=Momentum, Y=RS, size=Volume, color=Technical."""
    fig, ax = plt.subplots(figsize=(10, 7))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    top15 = stocks[:15]
    if not top15:
        plt.close(fig)
        return io.BytesIO()

    x = [s["mom_pct"] for s in top15]
    y = [s["rs_pct"] for s in top15]
    sizes = [max(s["vol_pct"], 10) * 3 for s in top15]
    colors = [s["tech_pct"] for s in top15]
    tickers = [s["ticker"] for s in top15]

    scatter = ax.scatter(
        x, y, s=sizes, c=colors, cmap="RdYlGn",
        vmin=0, vmax=100, alpha=0.85, edgecolors="white", linewidths=0.5,
    )

    # Annotate top 5
    for i in range(min(5, len(top15))):
        ax.annotate(
            tickers[i],
            (x[i], y[i]),
            textcoords="offset points",
            xytext=(8, 8),
            fontsize=9,
            fontweight="bold",
            color="white",
        )
    # Annotate 6-15 smaller
    for i in range(5, len(top15)):
        ax.annotate(
            tickers[i],
            (x[i], y[i]),
            textcoords="offset points",
            xytext=(6, 6),
            fontsize=7,
            color="#aaa",
        )

    cbar = fig.colorbar(scatter, ax=ax, label="Technical Quality %", pad=0.02)
    cbar.ax.yaxis.label.set_color("white")
    cbar.ax.tick_params(colors="white")

    ax.set_xlabel("Momentum Score (%ile)", color="white", fontsize=11)
    ax.set_ylabel("Relative Strength (%ile)", color="white", fontsize=11)
    ax.set_title(
        f"Stock Discovery — {etf} ({name})",
        color="white", fontsize=14, fontweight="bold", pad=12,
    )

    ax.set_xlim(-5, 105)
    ax.set_ylim(-5, 105)
    ax.axhline(50, color="#444", linestyle="--", linewidth=0.5)
    ax.axvline(50, color="#444", linestyle="--", linewidth=0.5)

    # Quadrant labels
    ax.text(75, 92, "Leaders", color="#51cf66", fontsize=9, ha="center", alpha=0.6)
    ax.text(25, 92, "Improving", color="#ffd43b", fontsize=9, ha="center", alpha=0.6)
    ax.text(25, 8, "Laggards", color="#ff6b6b", fontsize=9, ha="center", alpha=0.6)
    ax.text(75, 8, "Weakening", color="#ff922b", fontsize=9, ha="center", alpha=0.6)

    ax.tick_params(colors="white", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#444")
    ax.grid(alpha=0.1, color="white")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor="#1a1a2e")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── Cross-Validation: Sector Rotation + RRG + Sortino ────────────────────────

RS_WINDOW = 10  # RRG rolling z-score lookback (same as rrg-scanner.py)


def _fetch_closes_list(ticker: str, range_: str = "6mo") -> list[float]:
    """Fetch closing prices as a plain list (lightweight, for cross-validation)."""
    yticker = ticker.replace(".", "-")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yticker}"
        f"?range={range_}&interval=1d"
    )
    try:
        r = requests.get(url, headers=YAHOO_HEADERS, timeout=15)
        data = r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        return [c for c in data if c is not None]
    except Exception:
        return []


def _fetch_all_closes_list(
    tickers: list[str], range_: str = "6mo",
) -> dict[str, list[float]]:
    """Parallel fetch close price lists for cross-validation."""
    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_fetch_closes_list, t, range_): t for t in tickers}
        for f in as_completed(futures):
            t = futures[f]
            try:
                c = f.result()
                if c and len(c) >= 20:
                    results[t] = c
            except Exception:
                pass
    return results


def rank_by_sector_rotation(
    etfs: list[str], closes: dict[str, list[float]], spy: list[float],
) -> list[tuple[str, float, str]]:
    """
    Sector-rotation style ranking: 1W return relative strength vs SPY,
    plus momentum phase classification.
    Returns [(etf, rs_1w, phase), ...] sorted by rs_1w desc.
    """
    spy_1w = spy[-1] / spy[-6] - 1 if len(spy) >= 6 else 0
    spy_4w = spy[-1] / spy[-21] - 1 if len(spy) >= 21 else spy_1w

    ranked = []
    for etf in etfs:
        c = closes.get(etf)
        if not c or len(c) < 6:
            continue
        ret_1w = (c[-1] / c[-6] - 1)
        ret_4w = (c[-1] / c[-21] - 1) if len(c) >= 21 else ret_1w
        rs_1w = ret_1w - spy_1w
        # Momentum phase (same logic as sector-rotation.py)
        weekly_rate = ret_4w / 4 if ret_4w != 0 else 0
        if ret_1w > 0 and ret_1w > weekly_rate:
            phase = "ACCEL"
        elif ret_1w > 0:
            phase = "DECEL"
        elif ret_1w < 0 and ret_1w < weekly_rate:
            phase = "WEAK"
        else:
            phase = "STAB"
        ranked.append((etf, rs_1w, phase))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked


def rank_by_rrg_quadrant(
    etfs: list[str], closes: dict[str, list[float]], spy: list[float],
) -> list[tuple[str, str, float, float]]:
    """
    RRG quadrant classification (same math as rrg-scanner.py).
    Returns [(etf, quadrant, rs_ratio, rs_momentum), ...] sorted with Leading first.
    """
    results = []
    for etf in etfs:
        c = closes.get(etf)
        if not c:
            continue
        min_len = min(len(c), len(spy))
        tc = np.array(c[-min_len:], dtype=float)
        bc = np.array(spy[-min_len:], dtype=float)

        raw_rs = (tc / bc) * 100

        if len(raw_rs) < RS_WINDOW * 2 + 1:
            continue

        # RS-Ratio: 100 + z-score
        rs_ratio = np.full_like(raw_rs, np.nan)
        for i in range(RS_WINDOW, len(raw_rs)):
            seg = raw_rs[i - RS_WINDOW: i + 1]
            mean, std = seg.mean(), seg.std()
            rs_ratio[i] = 100 + (raw_rs[i] - mean) / std if std > 0 else 100.0

        # RS-Momentum: 100 + z-score of RS-Ratio change
        rs_mom = np.full_like(rs_ratio, np.nan)
        ratio_diff = np.diff(rs_ratio)
        ratio_diff = np.insert(ratio_diff, 0, np.nan)
        for i in range(RS_WINDOW * 2, len(rs_ratio)):
            seg = ratio_diff[i - RS_WINDOW: i + 1]
            seg = seg[~np.isnan(seg)]
            if len(seg) < 2:
                continue
            mean, std = seg.mean(), seg.std()
            rs_mom[i] = 100 + (ratio_diff[i] - mean) / std if std > 0 else 100.0

        # Get latest valid point
        rr = rs_ratio[-1]
        rm = rs_mom[-1]
        if np.isnan(rr) or np.isnan(rm):
            continue

        if rr >= 100 and rm >= 100:
            quad = "Leading"
        elif rr < 100 and rm >= 100:
            quad = "Improving"
        elif rr >= 100 and rm < 100:
            quad = "Weakening"
        else:
            quad = "Lagging"

        results.append((etf, quad, float(rr), float(rm)))

    # Sort: Leading > Improving > Weakening > Lagging, then by RS-Ratio desc
    quad_order = {"Leading": 0, "Improving": 1, "Weakening": 2, "Lagging": 3}
    results.sort(key=lambda x: (quad_order[x[1]], -x[2]))
    return results


def rank_by_sortino(
    etfs: list[str], closes: dict[str, list[float]],
) -> list[tuple[str, float]]:
    """
    Simplified Sortino ratio ranking (4W = 20 trading days).
    Returns [(etf, sortino), ...] sorted by sortino desc.
    """
    # Use 5% annual risk-free default (avoid FRED call for validation step)
    rf_daily = 0.05 / 252.0

    scored = []
    for etf in etfs:
        c = closes.get(etf)
        if not c or len(c) < 25:
            continue
        arr = np.array(c[-21:], dtype=float)
        rets = np.diff(arr) / arr[:-1]  # daily returns, last 20 days
        excess = rets - rf_daily
        mean_excess = np.mean(excess)
        downside = excess.copy()
        downside[downside > 0] = 0
        dd = np.sqrt(np.mean(downside ** 2))
        sortino = mean_excess / dd if dd > 1e-10 else (10.0 if mean_excess > 0 else 0.0)
        scored.append((etf, float(sortino)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def cross_validate_subsectors() -> tuple[list[str], str]:
    """
    Run three independent analyses on all subsector ETFs and cross-validate:
      1. Sector Rotation (1W RS vs SPY + momentum phase)
      2. RRG Quadrant (Leading/Improving/Weakening/Lagging)
      3. Sortino Ratio (4W risk-adjusted return)

    Returns (consensus_etfs, validation_report_text).
    consensus_etfs: ETFs to scan (top from consensus or best available).
    validation_report_text: Discord message showing agreement/disagreement.
    """
    print("  Cross-validating subsector + EW + CW sector ETFs across 3 methods...")

    all_etf_names = {**SUBSECTOR_NAMES, **EW_SECTOR_NAMES, **CW_SECTOR_NAMES}
    etfs_to_check = [e for e in all_etf_names if e != "IBIT"]
    all_tickers = etfs_to_check + ["SPY"]

    # Single fetch for all ETFs (reused by all 3 methods)
    closes = _fetch_all_closes_list(all_tickers, "6mo")

    if "SPY" not in closes:
        print("  Could not fetch SPY, using defaults")
        return DEFAULT_ETFS, ""

    spy = closes["SPY"]
    valid_etfs = [e for e in etfs_to_check if e in closes]

    # ── Method 1: Sector Rotation ────────────────────────────────────────
    sr_ranked = rank_by_sector_rotation(valid_etfs, closes, spy)
    sr_top5 = set(e for e, _, _ in sr_ranked[:5])
    sr_top3 = [e for e, _, _ in sr_ranked[:3]]

    # ── Method 2: RRG Quadrant ───────────────────────────────────────────
    rrg_ranked = rank_by_rrg_quadrant(valid_etfs, closes, spy)
    rrg_leading = [e for e, q, _, _ in rrg_ranked if q == "Leading"]
    rrg_improving = [e for e, q, _, _ in rrg_ranked if q == "Improving"]
    rrg_top5 = set((rrg_leading + rrg_improving)[:5])

    # ── Method 3: Sortino ────────────────────────────────────────────────
    sortino_ranked = rank_by_sortino(valid_etfs, closes)
    sortino_top5 = set(e for e, _ in sortino_ranked[:5])
    sortino_top3 = [e for e, _ in sortino_ranked[:3]]

    # ── Consensus Analysis ───────────────────────────────────────────────
    # Count how many methods picked each ETF in their top 5
    vote_count = {}
    for etf in valid_etfs:
        votes = 0
        if etf in sr_top5:
            votes += 1
        if etf in rrg_top5:
            votes += 1
        if etf in sortino_top5:
            votes += 1
        if votes > 0:
            vote_count[etf] = votes

    consensus_3 = sorted([e for e, v in vote_count.items() if v == 3])
    consensus_2 = sorted([e for e, v in vote_count.items() if v == 2])
    only_1 = sorted([e for e, v in vote_count.items() if v == 1])

    # Pick ETFs to scan: all 3/3 consensus + 2/3 consensus, cap at 5
    scan_list = consensus_3 + consensus_2
    if not scan_list:
        # No consensus — fall back to SR top 3
        scan_list = sr_top3
    scan_list = scan_list[:5]

    # ── Fallback escalation for underserved sectors ────────────────────
    # Determine which CW sectors are already covered by the scan list
    covered_cw = set()
    for etf in scan_list:
        if etf in CW_SECTOR_NAMES:
            covered_cw.add(etf)
        elif etf in EW_TO_CW:
            covered_cw.add(EW_TO_CW[etf])
        elif etf in SUBSECTOR_TO_CW:
            covered_cw.add(SUBSECTOR_TO_CW[etf])

    # If an EW sector is selected but its parent CW sector has no/weak
    # subsector coverage, add the CW sector too for broader stock discovery
    for etf in list(scan_list):
        if etf in EW_TO_CW:
            cw = EW_TO_CW[etf]
            if cw not in scan_list and cw in (SECTORS_NO_SUBSECTORS | SECTORS_WEAK_COVERAGE):
                scan_list.append(cw)
                covered_cw.add(cw)

    # If a CW sector got 2+ votes but didn't make top 5, and no subsector
    # from that sector is already in the list, escalate it
    for cw_etf in CW_SECTOR_NAMES:
        if cw_etf in scan_list or cw_etf in covered_cw:
            continue
        if vote_count.get(cw_etf, 0) >= 2:
            subsectors_of = [s for s, c in SUBSECTOR_TO_CW.items() if c == cw_etf]
            if not any(s in scan_list for s in subsectors_of):
                scan_list.append(cw_etf)

    scan_list = scan_list[:7]  # allow up to 7 with escalation

    # ── Build validation report ──────────────────────────────────────────
    lines = []
    def _etf_type(e):
        if e in CW_SECTOR_NAMES: return "CW"
        if e in EW_SECTOR_NAMES: return "EW"
        return "SUB"

    lines.append("**Cross-Validation Report** (Subsectors + EW + CW Sectors)")
    lines.append("```")
    lines.append(f"{'ETF':<6} {'TYP':<4} {'Sector Rot':>10} {'RRG Quad':>10} {'Sortino':>10}  CONSENSUS")
    lines.append("-" * 60)

    # Build lookup dicts for display
    sr_dict = {e: (rs, ph) for e, rs, ph in sr_ranked}
    rrg_dict = {e: (q, rr) for e, q, rr, _ in rrg_ranked}
    sort_dict = {e: s for e, s in sortino_ranked}

    # Show all ETFs that got at least 1 vote, sorted by vote count
    display_etfs = consensus_3 + consensus_2 + only_1
    for etf in display_etfs:
        votes = vote_count.get(etf, 0)
        sr_rs, sr_ph = sr_dict.get(etf, (0.0, "?"))
        rrg_q, _ = rrg_dict.get(etf, ("?", 0))
        sort_s = sort_dict.get(etf, 0.0)

        sr_str = f"{sr_rs*100:+.1f}% {sr_ph}"
        rrg_str = rrg_q[:4]  # Lead/Impr/Weak/Lagg
        sort_str = f"{sort_s:.2f}"

        consensus_str = f"{'*' * votes}/3"
        if votes == 3:
            consensus_str += " STRONG"
        elif votes == 2:
            consensus_str += " AGREE"
        else:
            consensus_str += " SPLIT"

        lines.append(f"{etf:<6} {_etf_type(etf):<4} {sr_str:>10} {rrg_str:>10} {sort_str:>10}  {consensus_str}")

    lines.append("```")

    # Disagreement alerts
    if not consensus_3 and not consensus_2:
        lines.append("No consensus across methods — using Sector Rotation top picks")
    elif consensus_3:
        lines.append(
            f"STRONG consensus ({'/'.join(consensus_3)}): "
            "all 3 methods agree these subsectors are leading"
        )
    if only_1:
        lines.append(
            f"SPLIT signals: {', '.join(only_1)} — "
            "only 1 method ranks these in top 5, proceed with caution"
        )

    lines.append(f"\nScanning: **{', '.join(scan_list)}**")

    report = "\n".join(lines)
    print(f"  Consensus: {len(consensus_3)} strong, {len(consensus_2)} agree, {len(only_1)} split")
    print(f"  Scanning: {', '.join(scan_list)}")

    return scan_list, report


# ── Main Scanner ─────────────────────────────────────────────────────────────

def scan_etf(etf: str, holdings_data: dict, spy_data: pd.DataFrame) -> tuple[str, list[dict], int] | None:
    """Run full discovery scan for one ETF."""
    etf_info = holdings_data.get(etf)
    if not etf_info:
        print(f"  {etf}: not found in etf-holdings.json")
        return None

    constituents = etf_info.get("holdings", [])
    if not constituents:
        print(f"  {etf}: no holdings listed")
        return None

    name = etf_info.get("name", etf)
    print(f"  Scanning {etf} ({name}): {len(constituents)} constituents")

    # Fetch all constituent + ETF data
    all_tickers = list(set(constituents + [etf]))
    ohlcv = batch_fetch(all_tickers, "6mo")

    if etf not in ohlcv:
        print(f"  {etf}: could not fetch ETF data")
        return None

    etf_close = ohlcv[etf]["Close"]
    fetched = [t for t in constituents if t in ohlcv]
    print(f"    Fetched {len(fetched)}/{len(constituents)} constituents")

    if len(fetched) < 3:
        print(f"    Too few constituents, skipping")
        return None

    # Score each constituent
    scored = []
    for ticker in fetched:
        df = ohlcv[ticker]
        if len(df) < 50:
            continue

        try:
            # Module 1: RS
            rs = score_relative_strength(df["Close"], etf_close)

            # Module 2: Momentum
            mom = score_momentum(df)

            # Module 3: Volume
            vol = score_volume(df)

            # Module 4: Technical
            tech = score_technical(df)

            # Module 5: Risk filters
            flags = apply_risk_filters(df, ticker)

            entry = {
                "ticker": ticker,
                "price": round(float(df["Close"].iloc[-1]), 2),
                # Raw scores (will be percentile-ranked)
                "rs_score": rs["rs_score"],
                "rs_3m": rs.get("rs_3m", 0),
                "rs_slope": rs.get("rs_slope", 0),
                "mom_raw": mom["mom_raw"],
                "roc5": mom["roc5"],
                "roc20": mom["roc20"],
                "roc63": mom["roc63"],
                "ma_alignment": mom["ma_alignment"],
                "macd_rising": mom["macd_rising"],
                "vol_raw": vol["vol_raw"],
                "rel_vol": vol["rel_vol"],
                "ud_ratio": vol["ud_ratio"],
                "cmf20": vol["cmf20"],
                "tech_raw": tech["tech_raw"],
                "adx": tech["adx"],
                "rsi": tech["rsi"],
                "bullish_trend": tech["bullish_trend"],
                "dist_from_high": tech["dist_from_high"],
                "atr_pct": tech["atr_pct"],
                "flags": flags,
            }
            scored.append(entry)
        except Exception as e:
            print(f"    {ticker}: scoring error: {e}", file=sys.stderr)

    if not scored:
        print(f"    No stocks scored successfully")
        return None

    # Compute composite with percentile ranking
    scored = compute_composite(scored)
    print(f"    Ranked {len(scored)} stocks, top: {scored[0]['ticker']} ({scored[0]['final_score']:.1f})")

    return etf, scored, len(constituents)


def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting Stock Discovery Scanner")

    # Load ETF holdings
    try:
        holdings_data = load_etf_holdings()
    except Exception as e:
        print(f"Failed to load etf-holdings.json: {e}", file=sys.stderr)
        return

    # Determine which ETFs to scan
    validation_report = ""
    if len(sys.argv) > 1:
        target_etfs = [a.upper() for a in sys.argv[1:]]
        print(f"  CLI override: {', '.join(target_etfs)}")
    else:
        target_etfs, validation_report = cross_validate_subsectors()

    # Filter out ETFs without holdings
    target_etfs = [
        e for e in target_etfs
        if e in holdings_data and holdings_data[e].get("holdings")
    ]

    if not target_etfs:
        print("No valid ETFs to scan")
        return

    # Fetch SPY for reference
    spy_data = fetch_ohlcv("SPY", "6mo")

    # Post validation report first (if auto-detected)
    if validation_report:
        send_discord_text(validation_report)
        print(f"  Posted cross-validation report ({len(validation_report)} chars)")

    # Header message
    header = (
        f"**Stock Discovery Scanner** ({now_et.strftime('%a %b %d %I:%M %p ET')})\n"
        f"ETFs Scanned: {', '.join(target_etfs)}\n"
        f"Method: RS(30%) + Momentum(25%) + Volume(25%) + Technical(20%)"
    )
    send_discord_text(header)

    # Scan each ETF
    all_results = []
    for etf in target_etfs:
        result = scan_etf(etf, holdings_data, spy_data)
        if result is None:
            continue

        etf_sym, scored, num_total = result
        all_results.append((etf_sym, scored, num_total))
        name = holdings_data[etf_sym].get("name", etf_sym)

        # Post text table
        text = format_text_table(etf_sym, name, scored, num_total)
        send_discord_text(text)
        print(f"  Posted {etf_sym} text ({len(text)} chars)")

        # Post scatter chart
        buf = render_scatter(etf_sym, name, scored)
        if buf.getbuffer().nbytes > 0:
            send_discord_image(buf, f"discovery_{etf_sym.lower()}.png")
            print(f"  Posted {etf_sym} chart")

    # ── Multi-ETF dedup + consensus detection ────────────────────────────
    if len(all_results) > 1:
        # Track which stocks appear in multiple ETF top-10 lists
        stock_appearances = {}  # ticker -> [(etf, rank, score), ...]
        for etf_sym, scored, _ in all_results:
            for i, s in enumerate(scored[:10], 1):
                t = s["ticker"]
                if t not in stock_appearances:
                    stock_appearances[t] = []
                stock_appearances[t].append((etf_sym, i, s["final_score"]))

        consensus = {t: apps for t, apps in stock_appearances.items() if len(apps) >= 2}
        if consensus:
            clines = ["**Multi-ETF Consensus** (deduped — best rank shown)"]
            clines.append("```")
            clines.append(f"{'TICKER':<7} {'BEST':>5} {'SCORE':>6}  ALSO RANKED IN")
            clines.append("-" * 52)
            for ticker, apps in sorted(
                consensus.items(),
                key=lambda x: (-len(x[1]), -max(a[2] for a in x[1]))
            ):
                # Best rank = lowest rank number (highest position)
                best = min(apps, key=lambda a: a[1])
                others = [f"{e}(#{r})" for e, r, _ in apps if e != best[0]]
                clines.append(
                    f"{ticker:<7} {best[0]}#{best[1]:<3} {best[2]:5.1f}  {', '.join(others)}"
                )
            clines.append("```")
            msg = "\n".join(clines)
            send_discord_text(msg)
            print(f"  Posted multi-ETF consensus ({len(consensus)} stocks deduped)")

    # ── Save output for downstream scanners ──────────────────────────────
    if all_results:
        output = {
            "timestamp": now_et.isoformat(),
            "etfs_scanned": [r[0] for r in all_results],
            "top_picks": {
                etf: [s["ticker"] for s in scored[:10]]
                for etf, scored, _ in all_results
            },
        }
        out_path = TOOLS_DIR / "discovery-output.json"
        try:
            with open(out_path, "w") as f:
                json.dump(output, f, indent=2)
            print(f"  Saved discovery output to {out_path.name}")
        except Exception as e:
            print(f"  Failed to save discovery output: {e}", file=sys.stderr)

    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} Stock Discovery complete")


if __name__ == "__main__":
    main()
