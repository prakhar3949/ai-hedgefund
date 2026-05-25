"""
Trade Setup Scanner — Entry, Stop Loss & Targets

For each stock surfaced by stock-discovery.py, computes precise entry zones,
stop loss levels, and profit targets with explicit risk/reward ratios.
Also evaluates pullback quality (healthy vs unhealthy).

Input:
  - Default: auto-reads discovery-output.json
  - CLI override: python trade-setup.py NVDA AMAT CL
  - Fallback: reads watchlist.json

Modules:
  1. Support & Resistance Level Detection
  2. Entry Zone Calculation
  3. Stop Loss Placement
  4. Profit Target Calculation
  5. Risk/Reward Assessment + Position Sizing
  6. Multi-Timeframe Alignment Check
  7. Earnings Proximity Check (Alpha Vantage)
  8. Pullback Quality Assessment

Output: Discord text + per-stock chart (6mo daily with S/R, entry, stop, targets)
"""

import io
import json
import sys
import traceback
import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from scipy.signal import argrelextrema

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

# ── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1470466815397335183/"
    "GZyX60SqadXRFM1OFTwAJz2l9p5GGheseUCKQ370jtE0pxJ3UHNWHQpbDWpDOAWd-CHK"
)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

ALPHA_VANTAGE_KEY = "1SIVEVQAAYTRTLBV"


# ── Data Fetching ────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame | None:
    """Fetch OHLCV data from Yahoo Finance chart API."""
    yticker = ticker.replace(".", "-")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yticker}"
        f"?range={period}&interval={interval}"
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


def batch_fetch(tickers: list[str], period: str = "1y", interval: str = "1d") -> dict[str, pd.DataFrame]:
    """Parallel fetch OHLCV for multiple tickers."""
    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fetch_ohlcv, t, period, interval): t for t in tickers}
        for f in as_completed(futures):
            t = futures[f]
            try:
                df = f.result()
                if df is not None:
                    results[t] = df
            except Exception:
                pass
    return results


# ── Discord ──────────────────────────────────────────────────────────────────

def send_discord_text(text: str):
    """Send text to Discord, splitting if needed."""
    chunks = []
    while len(text) > 1950:
        split_at = text.rfind("\n", 0, 1950)
        if split_at == -1:
            split_at = 1950
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text.strip():
        chunks.append(text)
    for chunk in chunks:
        try:
            resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=30)
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


# ── Input Loading ────────────────────────────────────────────────────────────

def load_tickers() -> list[str]:
    """Load tickers from CLI args, discovery-output.json, or watchlist.json."""
    # CLI override
    if len(sys.argv) > 1:
        tickers = [t.upper() for t in sys.argv[1:]]
        print(f"  CLI override: {len(tickers)} tickers")
        return tickers

    # Try discovery-output.json
    discovery_path = TOOLS_DIR / "discovery-output.json"
    if discovery_path.exists():
        try:
            with open(discovery_path) as f:
                data = json.load(f)
            all_tickers = set()
            for etf, picks in data.get("top_picks", {}).items():
                for t in picks:
                    all_tickers.add(t.upper())
            if all_tickers:
                tickers = sorted(all_tickers)
                print(f"  Loaded {len(tickers)} tickers from discovery-output.json")
                return tickers
        except Exception:
            pass

    # Fallback to watchlist.json
    wl_path = TOOLS_DIR / "watchlist.json"
    if wl_path.exists():
        with open(wl_path) as f:
            data = json.load(f)
        tickers = data.get("tickers", [])
        print(f"  Loaded {len(tickers)} tickers from watchlist.json")
        return tickers

    print("  No ticker source found", file=sys.stderr)
    return []


# ── Technical Helpers ────────────────────────────────────────────────────────

def calc_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period).mean()


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
    atr = calc_atr(df, period)
    plus_di = 100 * calc_ema(plus_dm, period) / atr.replace(0, np.nan)
    minus_di = 100 * calc_ema(minus_dm, period) / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return calc_ema(dx, period)


def calc_obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["Close"].diff()).fillna(0)
    return (df["Volume"] * direction).cumsum()


def calc_cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    mfv = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / \
          (df["High"] - df["Low"]).replace(0, np.nan) * df["Volume"]
    return mfv.rolling(period).sum() / df["Volume"].rolling(period).sum()


def calc_vwap_rolling(df: pd.DataFrame, period: int = 20) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    return (tp * df["Volume"]).rolling(period).sum() / df["Volume"].rolling(period).sum()


# ── Module 1: Support & Resistance ──────────────────────────────────────────

def find_support_resistance(df: pd.DataFrame) -> dict:
    """
    Identify support and resistance levels using:
    - Swing highs/lows (scipy argrelextrema)
    - Moving averages
    - Round numbers
    - Fibonacci retracement
    """
    close = df["Close"].values
    high = df["High"].values
    low = df["Low"].values
    current_price = close[-1]

    levels = []  # list of {"price", "type", "strength", "description"}

    # --- Horizontal S/R from swing points ---
    order = 10
    if len(close) > 2 * order:
        swing_highs_idx = argrelextrema(high, np.greater_equal, order=order)[0]
        swing_lows_idx = argrelextrema(low, np.less_equal, order=order)[0]

        # Collect raw swing levels
        raw_levels = []
        for idx in swing_highs_idx:
            raw_levels.append({"price": high[idx], "idx": idx, "kind": "high"})
        for idx in swing_lows_idx:
            raw_levels.append({"price": low[idx], "idx": idx, "kind": "low"})

        # Cluster nearby levels (within 1.5%)
        raw_levels.sort(key=lambda x: x["price"])
        clusters = []
        used = set()
        for i, lv in enumerate(raw_levels):
            if i in used:
                continue
            cluster_prices = [lv["price"]]
            cluster_indices = [lv["idx"]]
            for j in range(i + 1, len(raw_levels)):
                if j in used:
                    continue
                if abs(raw_levels[j]["price"] - lv["price"]) / lv["price"] < 0.015:
                    cluster_prices.append(raw_levels[j]["price"])
                    cluster_indices.append(raw_levels[j]["idx"])
                    used.add(j)
            used.add(i)
            avg_price = np.mean(cluster_prices)
            touches = len(cluster_prices)
            recency = max(cluster_indices) / len(close)  # 0 to 1
            strength = min(5, touches) + recency * 2
            clusters.append({
                "price": round(avg_price, 2),
                "type": "Horizontal",
                "strength": round(strength, 1),
                "description": f"{touches} touches" + (", recent" if recency > 0.8 else ""),
            })

        levels.extend(clusters)

    # --- Moving Average Support/Resistance ---
    ma_configs = [
        ("EMA(21)", calc_ema(df["Close"], 21)),
        ("SMA(20)", calc_sma(df["Close"], 20)),
        ("SMA(50)", calc_sma(df["Close"], 50)),
        ("SMA(200)", calc_sma(df["Close"], 200)),
    ]
    for name, ma_series in ma_configs:
        if ma_series.isna().all():
            continue
        ma_val = ma_series.iloc[-1]
        if np.isnan(ma_val):
            continue
        dist_pct = (current_price - ma_val) / current_price * 100
        # Strength based on proximity and trend
        strength = max(1, 4 - abs(dist_pct) / 2)
        levels.append({
            "price": round(ma_val, 2),
            "type": name,
            "strength": round(strength, 1),
            "description": f"dynamic, {dist_pct:+.1f}% from price",
        })

    # --- Rolling VWAP ---
    vwap_20 = calc_vwap_rolling(df, 20)
    if not vwap_20.isna().all():
        vwap_val = vwap_20.iloc[-1]
        if not np.isnan(vwap_val):
            levels.append({
                "price": round(vwap_val, 2),
                "type": "VWAP(20d)",
                "strength": 2.5,
                "description": "institutional cost basis",
            })

    # --- Round Numbers ---
    # Find nearest round numbers within 10% of price
    if current_price > 10:
        step = 10 if current_price < 100 else (25 if current_price < 500 else 50)
        low_bound = current_price * 0.90
        high_bound = current_price * 1.10
        rnd = int(low_bound / step) * step
        while rnd <= high_bound:
            if rnd > 0 and abs(rnd - current_price) / current_price > 0.005:
                levels.append({
                    "price": float(rnd),
                    "type": "Round#",
                    "strength": 1.5,
                    "description": "psychological level",
                })
            rnd += step

    # --- Fibonacci Retracement ---
    fib_info = calc_fibonacci(df)
    if fib_info:
        for fib_level, fib_price in fib_info["levels"].items():
            levels.append({
                "price": round(fib_price, 2),
                "type": f"Fib {fib_level}",
                "strength": 2.5 if fib_level == "50.0%" else 2.0,
                "description": f"of ${fib_info['swing_low']:.0f}-${fib_info['swing_high']:.0f} swing",
            })

    # Sort into supports and resistances
    supports = sorted(
        [lv for lv in levels if lv["price"] < current_price * 0.998],
        key=lambda x: x["price"], reverse=True
    )
    resistances = sorted(
        [lv for lv in levels if lv["price"] > current_price * 1.002],
        key=lambda x: x["price"]
    )

    return {
        "current_price": current_price,
        "supports": supports[:8],
        "resistances": resistances[:8],
        "all_levels": levels,
    }


def calc_fibonacci(df: pd.DataFrame) -> dict | None:
    """Calculate Fibonacci retracement from last major swing (>15% move in 3 months)."""
    close = df["Close"].values
    last_90 = close[-min(63, len(close)):]

    swing_high = np.max(last_90)
    swing_low = np.min(last_90)
    swing_pct = (swing_high - swing_low) / swing_low * 100

    if swing_pct < 15:
        return None

    high_idx = np.argmax(last_90)
    low_idx = np.argmin(last_90)

    # Determine direction: if low came first, it's an upswing (retracement down)
    if low_idx < high_idx:
        # Upswing — fib retracement measures pullback from high
        diff = swing_high - swing_low
        levels = {
            "23.6%": swing_high - diff * 0.236,
            "38.2%": swing_high - diff * 0.382,
            "50.0%": swing_high - diff * 0.500,
            "61.8%": swing_high - diff * 0.618,
        }
    else:
        # Downswing — fib retracement measures bounce from low
        diff = swing_high - swing_low
        levels = {
            "23.6%": swing_low + diff * 0.236,
            "38.2%": swing_low + diff * 0.382,
            "50.0%": swing_low + diff * 0.500,
            "61.8%": swing_low + diff * 0.618,
        }

    return {
        "swing_high": swing_high,
        "swing_low": swing_low,
        "swing_pct": swing_pct,
        "direction": "up" if low_idx < high_idx else "down",
        "levels": levels,
    }


# ── Module 2: Entry Zone Calculation ────────────────────────────────────────

def calc_entry_zone(df: pd.DataFrame, sr: dict) -> dict:
    """Determine entry zone and classification."""
    price = sr["current_price"]
    supports = sr["supports"]
    resistances = sr["resistances"]

    ema21 = calc_ema(df["Close"], 21).iloc[-1]
    sma50 = calc_sma(df["Close"], 50).iloc[-1]
    sma200 = calc_sma(df["Close"], 200).iloc[-1]

    # Uptrend check: price above SMA50 and SMA50 above SMA200
    uptrend = False
    if not np.isnan(sma50) and not np.isnan(sma200):
        uptrend = price > sma50 and sma50 > sma200
    elif not np.isnan(sma50):
        uptrend = price > sma50

    # Find nearest support distance
    nearest_support_dist = None
    nearest_support = None
    if supports:
        nearest_support = supports[0]
        nearest_support_dist = (price - nearest_support["price"]) / price * 100

    # Find nearest resistance distance
    nearest_resistance = None
    if resistances:
        nearest_resistance = resistances[0]

    # Entry zone: between nearest 2 supports
    entry_low = supports[1]["price"] if len(supports) > 1 else (supports[0]["price"] * 0.98 if supports else price * 0.95)
    entry_high = supports[0]["price"] if supports else price * 0.97

    # Classification
    if not supports:
        classification = "BROKEN_DOWN"
        reason = "No support levels identified below price"
    elif nearest_support_dist is not None and nearest_support_dist < 2 and uptrend:
        classification = "PULLBACK_ENTRY"
        reason = f"Within {nearest_support_dist:.1f}% of {nearest_support['type']} support, uptrend intact"
    elif nearest_resistance and (nearest_resistance["price"] - price) / price * 100 < 1.5:
        classification = "BREAKOUT_WATCH"
        reason = f"At {nearest_resistance['type']} resistance ${nearest_resistance['price']:.2f}"
    elif nearest_support_dist is not None and nearest_support_dist > 5:
        classification = "EXTENDED"
        reason = f"{nearest_support_dist:.1f}% above nearest support — don't chase"
    elif price < sma200 if not np.isnan(sma200) else False:
        classification = "BROKEN_DOWN"
        reason = "Below SMA(200) — avoid unless accumulation signals"
    else:
        classification = "IN_NO_MANS_LAND"
        reason = "Between support and resistance, no clear entry"

    return {
        "classification": classification,
        "reason": reason,
        "entry_low": round(entry_low, 2),
        "entry_high": round(entry_high, 2),
        "entry_mid": round((entry_low + entry_high) / 2, 2),
        "uptrend": uptrend,
        "nearest_support_dist_pct": nearest_support_dist,
    }


# ── Module 3: Stop Loss Placement ──────────────────────────────────────────

def calc_stop_loss(df: pd.DataFrame, entry: dict, sr: dict) -> dict:
    """Calculate stop loss using structure, ATR, and MA methods."""
    entry_price = entry["entry_mid"]
    atr = calc_atr(df).iloc[-1]
    supports = sr["supports"]

    stops = {}

    # Structure stop: 0.5% below nearest support below entry
    structure_support = None
    for s in supports:
        if s["price"] < entry_price:
            structure_support = s
            break
    if structure_support:
        struct_stop = structure_support["price"] * 0.995
        struct_risk = (entry_price - struct_stop) / entry_price * 100
        stops["structure"] = {
            "price": round(struct_stop, 2),
            "risk_pct": round(struct_risk, 1),
            "description": f"0.5% below {structure_support['type']} at ${structure_support['price']:.2f}",
            "level_info": structure_support,
        }

    # ATR stops
    for label, mult in [("conservative", 2.0), ("moderate", 1.5), ("aggressive", 1.0)]:
        atr_stop = entry_price - mult * atr
        atr_risk = (entry_price - atr_stop) / entry_price * 100
        stops[f"atr_{label}"] = {
            "price": round(atr_stop, 2),
            "risk_pct": round(atr_risk, 1),
            "description": f"{mult}x ATR(14) = ${mult * atr:.2f}",
        }

    # MA stop
    ema21 = calc_ema(df["Close"], 21).iloc[-1]
    sma50 = calc_sma(df["Close"], 50).iloc[-1]
    sma200 = calc_sma(df["Close"], 200).iloc[-1]
    adx = calc_adx(df).iloc[-1]

    ma_stop_val = None
    ma_stop_desc = ""
    if not np.isnan(adx) and adx > 30 and not np.isnan(ema21) and ema21 < entry_price:
        ma_stop_val = ema21 * 0.995
        ma_stop_desc = f"below EMA(21) ${ema21:.2f} (strong trend, ADX={adx:.0f})"
    elif not np.isnan(sma50) and sma50 < entry_price:
        ma_stop_val = sma50 * 0.995
        ma_stop_desc = f"below SMA(50) ${sma50:.2f} (moderate trend)"
    elif not np.isnan(sma200) and sma200 < entry_price:
        ma_stop_val = sma200 * 0.995
        ma_stop_desc = f"below SMA(200) ${sma200:.2f} (slow trend)"

    if ma_stop_val:
        ma_risk = (entry_price - ma_stop_val) / entry_price * 100
        stops["ma"] = {
            "price": round(ma_stop_val, 2),
            "risk_pct": round(ma_risk, 1),
            "description": ma_stop_desc,
        }

    # Recommended stop: prefer 3-7% risk, pick structure if in range, else ATR moderate
    recommended = None
    for key in ["structure", "atr_moderate", "ma", "atr_conservative"]:
        if key in stops and 2.5 <= stops[key]["risk_pct"] <= 7.5:
            recommended = key
            break
    if recommended is None:
        recommended = "atr_moderate" if "atr_moderate" in stops else list(stops.keys())[0] if stops else None

    return {
        "stops": stops,
        "recommended": recommended,
        "atr_value": round(atr, 2),
    }


# ── Module 4: Profit Targets ───────────────────────────────────────────────

def calc_targets(df: pd.DataFrame, entry: dict, sr: dict, stop_info: dict) -> dict:
    """Calculate profit targets using resistance levels, ATR, and Fibonacci extensions."""
    entry_price = entry["entry_mid"]
    atr = stop_info["atr_value"]
    resistances = sr["resistances"]

    targets = []

    # Resistance targets
    for i, res in enumerate(resistances[:3]):
        gain_pct = (res["price"] - entry_price) / entry_price * 100
        targets.append({
            "price": res["price"],
            "type": f"Resistance ({res['type']})",
            "gain_pct": round(gain_pct, 1),
            "description": res["description"],
        })

    # ATR-based targets
    atr_targets = [
        ("ATR T1 (1-2wk)", 2.0),
        ("ATR T2 (2-4wk)", 3.5),
        ("ATR T3 (4+wk)", 5.0),
    ]
    for label, mult in atr_targets:
        t_price = entry_price + mult * atr
        gain_pct = (t_price - entry_price) / entry_price * 100
        targets.append({
            "price": round(t_price, 2),
            "type": label,
            "gain_pct": round(gain_pct, 1),
            "description": f"{mult}x ATR(14)",
        })

    # Fibonacci extension targets
    fib = calc_fibonacci(df)
    if fib and fib["direction"] == "up":
        diff = fib["swing_high"] - fib["swing_low"]
        for ext_name, ext_mult in [("100%", 1.0), ("127.2%", 1.272), ("161.8%", 1.618)]:
            ext_price = fib["swing_low"] + diff * ext_mult
            if ext_price > entry_price:
                gain_pct = (ext_price - entry_price) / entry_price * 100
                targets.append({
                    "price": round(ext_price, 2),
                    "type": f"Fib Ext {ext_name}",
                    "gain_pct": round(gain_pct, 1),
                    "description": f"of ${fib['swing_low']:.0f}-${fib['swing_high']:.0f}",
                })

    # Sort by price, deduplicate nearby targets (within 1%)
    targets.sort(key=lambda x: x["price"])
    deduped = []
    for t in targets:
        if deduped and abs(t["price"] - deduped[-1]["price"]) / t["price"] < 0.01:
            # Keep the one with more description
            if len(t["description"]) > len(deduped[-1]["description"]):
                deduped[-1] = t
        else:
            deduped.append(t)

    # Select T1, T2, T3 from deduped (first 3 above entry)
    final_targets = [t for t in deduped if t["price"] > entry_price * 1.01][:3]

    return {
        "all_targets": deduped,
        "primary_targets": final_targets,
    }


# ── Module 5: Risk/Reward ──────────────────────────────────────────────────

def calc_risk_reward(entry: dict, stop_info: dict, target_info: dict) -> dict:
    """Calculate R/R ratios and position sizing."""
    entry_price = entry["entry_mid"]
    rec_key = stop_info["recommended"]
    if rec_key is None or rec_key not in stop_info["stops"]:
        return {"rr_ratios": [], "position_sizes": {}, "assessment": "NO STOP LEVEL"}

    stop_price = stop_info["stops"][rec_key]["price"]
    risk = entry_price - stop_price
    if risk <= 0:
        return {"rr_ratios": [], "position_sizes": {}, "assessment": "INVALID STOP"}

    risk_pct = risk / entry_price * 100

    rr_ratios = []
    for i, t in enumerate(target_info["primary_targets"]):
        reward = t["price"] - entry_price
        rr = reward / risk
        rr_ratios.append({
            "label": f"T{i+1}",
            "target_price": t["price"],
            "gain_pct": t["gain_pct"],
            "rr_ratio": round(rr, 1),
            "win_rate_required": round(1 / (1 + rr) * 100, 0),
            "type": t["type"],
        })

    # Position sizing for account sizes
    position_sizes = {}
    for acct in [25000, 50000, 100000]:
        risk_amt = acct * 0.01  # 1% risk
        shares = int(risk_amt / risk)
        cost = shares * entry_price
        position_sizes[acct] = {
            "shares": shares,
            "cost": round(cost, 0),
            "max_loss": round(risk_amt, 0),
        }

    # Assessment
    best_rr = max(r["rr_ratio"] for r in rr_ratios) if rr_ratios else 0
    if rr_ratios and rr_ratios[0]["rr_ratio"] >= 2.0:
        assessment = "GOOD"
    elif rr_ratios and rr_ratios[0]["rr_ratio"] >= 1.5:
        assessment = "ACCEPTABLE"
    else:
        assessment = "POOR R/R — SKIP or wait for better entry"

    return {
        "rr_ratios": rr_ratios,
        "position_sizes": position_sizes,
        "risk_pct": round(risk_pct, 1),
        "stop_price": stop_price,
        "assessment": assessment,
        "best_rr": round(best_rr, 1),
    }


# ── Module 6: Multi-Timeframe Alignment ────────────────────────────────────

def calc_mtf_alignment(daily_df: pd.DataFrame, weekly_df: pd.DataFrame | None) -> dict:
    """Check weekly trend + daily setup alignment."""
    price = daily_df["Close"].iloc[-1]

    # Daily analysis
    daily_sma50 = calc_sma(daily_df["Close"], 50).iloc[-1]
    daily_ema21 = calc_ema(daily_df["Close"], 21).iloc[-1]
    daily_above_50 = price > daily_sma50 if not np.isnan(daily_sma50) else None

    # Check if daily is pulling back (price near or below EMA21 but above SMA50)
    daily_pullback = False
    if not np.isnan(daily_ema21) and not np.isnan(daily_sma50):
        dist_to_ema21 = (price - daily_ema21) / price * 100
        daily_pullback = -2 < dist_to_ema21 < 1 and price > daily_sma50

    # Weekly analysis
    weekly_uptrend = None
    weekly_desc = "No weekly data"
    if weekly_df is not None and len(weekly_df) >= 40:
        w_close = weekly_df["Close"]
        w_sma10 = calc_sma(w_close, 10).iloc[-1]  # ~10 weeks
        w_sma40 = calc_sma(w_close, 40).iloc[-1]  # ~40 weeks
        w_price = w_close.iloc[-1]

        if not np.isnan(w_sma10) and not np.isnan(w_sma40):
            weekly_uptrend = w_price > w_sma40 and w_sma10 > w_sma40
            if weekly_uptrend:
                # Check if SMA10 is rising
                w_sma10_prev = calc_sma(w_close, 10).iloc[-5] if len(w_close) > 45 else w_sma10
                rising = w_sma10 > w_sma10_prev if not np.isnan(w_sma10_prev) else True
                weekly_desc = f"Uptrend (price > 40wk SMA, 10wk > 40wk" + (", rising)" if rising else ")")
            else:
                if w_price < w_sma40:
                    weekly_desc = "Downtrend (price below 40wk SMA)"
                else:
                    weekly_desc = "Sideways (10wk below 40wk)"

    # Alignment score
    if weekly_uptrend is True and daily_pullback:
        alignment = "STRONG ALIGNMENT"
        alignment_emoji = "+"
    elif weekly_uptrend is True and daily_above_50:
        alignment = "PARTIAL ALIGNMENT"
        alignment_emoji = "~"
    elif weekly_uptrend is False:
        if daily_above_50:
            alignment = "MISALIGNED"
            alignment_emoji = "!"
        else:
            alignment = "AVOID"
            alignment_emoji = "X"
    else:
        alignment = "PARTIAL ALIGNMENT"
        alignment_emoji = "~"

    return {
        "alignment": alignment,
        "alignment_emoji": alignment_emoji,
        "weekly_trend": "UPTREND" if weekly_uptrend else ("DOWNTREND" if weekly_uptrend is False else "UNKNOWN"),
        "weekly_desc": weekly_desc,
        "daily_pullback": daily_pullback,
        "daily_above_50": daily_above_50,
    }


# ── Module 7: Earnings Proximity ───────────────────────────────────────────

def check_earnings_proximity(ticker: str) -> dict:
    """Check if earnings are within 14 days using Alpha Vantage."""
    try:
        url = (
            f"https://www.alphavantage.co/query?function=EARNINGS_CALENDAR"
            f"&symbol={ticker}&horizon=3month&apikey={ALPHA_VANTAGE_KEY}"
        )
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return {"status": "UNKNOWN", "description": "Could not check earnings", "days": None}

        lines = resp.text.strip().split("\n")
        if len(lines) < 2:
            return {"status": "CLEAR", "description": "No upcoming earnings found", "days": None}

        # Parse CSV
        header = lines[0].split(",")
        date_idx = 0  # reportDate is first column typically
        for i, h in enumerate(header):
            if "reportDate" in h.lower() or "date" in h.lower():
                date_idx = i
                break

        now = datetime.now(ET).date()
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) <= date_idx:
                continue
            try:
                earn_date = datetime.strptime(parts[date_idx].strip(), "%Y-%m-%d").date()
                days_until = (earn_date - now).days
                if days_until < 0:
                    continue
                if days_until <= 5:
                    return {
                        "status": "EARNINGS_RISK",
                        "description": f"Reports in {days_until} days ({earn_date.strftime('%b %d')}) — Do not hold through earnings",
                        "days": days_until,
                    }
                elif days_until <= 14:
                    return {
                        "status": "EARNINGS_APPROACHING",
                        "description": f"Reports in {days_until} days ({earn_date.strftime('%b %d')}) — Plan exit before report",
                        "days": days_until,
                    }
                else:
                    return {
                        "status": "CLEAR",
                        "description": f"Next earnings in {days_until} days ({earn_date.strftime('%b %d')})",
                        "days": days_until,
                    }
            except ValueError:
                continue

        return {"status": "CLEAR", "description": "No upcoming earnings found", "days": None}

    except Exception:
        return {"status": "UNKNOWN", "description": "Earnings check failed", "days": None}


# ── Module 8: Pullback Quality ─────────────────────────────────────────────

def assess_pullback_quality(df: pd.DataFrame) -> dict:
    """
    Score pullback quality 0-100 across 5 criteria:
    1. Orderly decline (20 pts)
    2. Declining volume (20 pts)
    3. Holds key MA (20 pts)
    4. Shallow retracement (20 pts)
    5. Accumulation signs (20 pts)
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    atr = calc_atr(df)

    # Identify the most recent pullback
    # Find the most recent swing high
    if len(close) < 30:
        return {"score": 0, "classification": "INSUFFICIENT DATA", "details": {}}

    order = 5
    swing_high_idx = argrelextrema(close.values, np.greater_equal, order=order)[0]
    if len(swing_high_idx) == 0:
        return {"score": 50, "classification": "NO CLEAR PULLBACK", "details": {}}

    last_swing_high_pos = swing_high_idx[-1]
    if last_swing_high_pos >= len(close) - 3:
        # Price is near the high, no pullback yet
        return {"score": 50, "classification": "NO PULLBACK (AT HIGHS)", "details": {}}

    swing_high_price = close.iloc[last_swing_high_pos]
    current_price = close.iloc[-1]

    # The pullback period is from swing high to now
    pullback_slice = df.iloc[last_swing_high_pos:]
    if len(pullback_slice) < 3:
        return {"score": 50, "classification": "PULLBACK TOO SHORT", "details": {}}

    # Find prior advance (for volume comparison)
    advance_start = max(0, last_swing_high_pos - 20)
    advance_slice = df.iloc[advance_start:last_swing_high_pos]

    scores = {}

    # 1. Orderly decline: max single-day drop < 1.5x ATR(14)
    atr_at_high = atr.iloc[last_swing_high_pos] if last_swing_high_pos < len(atr) else atr.iloc[-1]
    if np.isnan(atr_at_high) or atr_at_high == 0:
        atr_at_high = close.iloc[-1] * 0.02
    pb_daily_drops = pullback_slice["Close"].diff().dropna()
    max_drop = abs(pb_daily_drops.min()) if len(pb_daily_drops) > 0 else 0
    orderly_ratio = max_drop / (1.5 * atr_at_high) if atr_at_high > 0 else 2
    if orderly_ratio < 0.7:
        scores["orderly"] = 20
    elif orderly_ratio < 1.0:
        scores["orderly"] = 15
    elif orderly_ratio < 1.5:
        scores["orderly"] = 8
    else:
        scores["orderly"] = 2

    # 2. Declining volume: pullback avg vol < 80% of advance avg vol
    pb_avg_vol = pullback_slice["Volume"].mean()
    adv_avg_vol = advance_slice["Volume"].mean() if len(advance_slice) > 0 else pb_avg_vol
    if adv_avg_vol > 0:
        vol_ratio = pb_avg_vol / adv_avg_vol
        if vol_ratio < 0.6:
            scores["volume"] = 20
        elif vol_ratio < 0.8:
            scores["volume"] = 15
        elif vol_ratio < 1.0:
            scores["volume"] = 8
        else:
            scores["volume"] = 2
    else:
        scores["volume"] = 10

    # 3. Holds key MA: low of pullback above EMA(21) or SMA(50)
    ema21 = calc_ema(close, 21)
    sma50 = calc_sma(close, 50)
    pb_low = pullback_slice["Low"].min()
    ema21_at_pb = ema21.iloc[last_swing_high_pos:].min()
    sma50_at_pb = sma50.iloc[last_swing_high_pos:].min()

    holds_ema21 = pb_low >= ema21_at_pb * 0.995 if not np.isnan(ema21_at_pb) else False
    holds_sma50 = pb_low >= sma50_at_pb * 0.995 if not np.isnan(sma50_at_pb) else False

    if holds_ema21:
        scores["holds_ma"] = 20
    elif holds_sma50:
        scores["holds_ma"] = 14
    else:
        scores["holds_ma"] = 3

    # 4. Shallow retracement: pullback retraces < 50% of prior swing
    # Find the swing low before the swing high
    swing_low_idx = argrelextrema(close.values[:last_swing_high_pos + 1], np.less_equal, order=order)[0]
    if len(swing_low_idx) > 0:
        swing_low_price = close.iloc[swing_low_idx[-1]]
        swing_range = swing_high_price - swing_low_price
        if swing_range > 0:
            retrace_pct = (swing_high_price - current_price) / swing_range * 100
            if retrace_pct < 23.6:
                scores["shallow"] = 20
            elif retrace_pct < 38.2:
                scores["shallow"] = 17
            elif retrace_pct < 50:
                scores["shallow"] = 12
            elif retrace_pct < 61.8:
                scores["shallow"] = 6
            else:
                scores["shallow"] = 2
        else:
            scores["shallow"] = 10
    else:
        scores["shallow"] = 10

    # 5. Accumulation signs: CMF stays positive, OBV flat/rising during pullback
    cmf = calc_cmf(df)
    obv = calc_obv(df)
    cmf_during_pb = cmf.iloc[last_swing_high_pos:]
    obv_during_pb = obv.iloc[last_swing_high_pos:]

    cmf_positive = cmf_during_pb.mean() > 0 if not cmf_during_pb.isna().all() else False
    obv_rising = False
    if len(obv_during_pb) >= 3:
        obv_slope = np.polyfit(range(len(obv_during_pb)), obv_during_pb.values, 1)[0]
        obv_rising = obv_slope >= 0

    if cmf_positive and obv_rising:
        scores["accumulation"] = 20
    elif cmf_positive or obv_rising:
        scores["accumulation"] = 12
    else:
        scores["accumulation"] = 3

    total = sum(scores.values())

    if total >= 80:
        classification = "HEALTHY"
    elif total >= 60:
        classification = "ACCEPTABLE"
    elif total >= 40:
        classification = "QUESTIONABLE"
    else:
        classification = "UNHEALTHY"

    return {
        "score": total,
        "classification": classification,
        "details": scores,
        "retracement_pct": round(retrace_pct, 1) if 'retrace_pct' in dir() else None,
    }


# ── Full Analysis Per Ticker ────────────────────────────────────────────────

def analyze_ticker(ticker: str, daily_df: pd.DataFrame, weekly_df: pd.DataFrame | None) -> dict | None:
    """Run all 8 modules for a single ticker."""
    if daily_df is None or len(daily_df) < 100:
        return None

    try:
        # Module 1: S/R
        sr = find_support_resistance(daily_df)

        # Module 2: Entry Zone
        entry = calc_entry_zone(daily_df, sr)

        # Module 3: Stop Loss
        stop = calc_stop_loss(daily_df, entry, sr)

        # Module 4: Targets
        targets = calc_targets(daily_df, entry, sr, stop)

        # Module 5: R/R
        rr = calc_risk_reward(entry, stop, targets)

        # Module 6: MTF
        mtf = calc_mtf_alignment(daily_df, weekly_df)

        # Module 7: Earnings (skip in bulk to avoid API limits)
        earnings = {"status": "UNCHECKED", "description": "Skipped in batch mode", "days": None}

        # Module 8: Pullback Quality
        pullback = assess_pullback_quality(daily_df)

        # Price context
        close = daily_df["Close"]
        high_52 = close.max()
        low_52 = close.min()
        current = close.iloc[-1]
        adx_val = calc_adx(daily_df).iloc[-1]
        rsi_val = calc_rsi(close).iloc[-1]

        # MA distances
        sma50 = calc_sma(close, 50).iloc[-1]
        sma200 = calc_sma(close, 200).iloc[-1]
        ema21 = calc_ema(close, 21).iloc[-1]

        ma_status = []
        for name, val in [("EMA21", ema21), ("SMA50", sma50), ("SMA200", sma200)]:
            if not np.isnan(val):
                if current > val:
                    ma_status.append(f">{name}")
                else:
                    ma_status.append(f"<{name}")

        return {
            "ticker": ticker,
            "price": current,
            "high_52": high_52,
            "low_52": low_52,
            "high_52_pct": round((current - high_52) / high_52 * 100, 1),
            "low_52_pct": round((current - low_52) / low_52 * 100, 1),
            "adx": round(adx_val, 0) if not np.isnan(adx_val) else None,
            "rsi": round(rsi_val, 0) if not np.isnan(rsi_val) else None,
            "ma_status": " | ".join(ma_status),
            "sr": sr,
            "entry": entry,
            "stop": stop,
            "targets": targets,
            "rr": rr,
            "mtf": mtf,
            "earnings": earnings,
            "pullback": pullback,
        }
    except Exception as e:
        print(f"  Error analyzing {ticker}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None


# ── Discord Text Formatting ─────────────────────────────────────────────────

def format_setup_text(result: dict) -> str:
    """Format a single ticker's trade setup as Discord text."""
    r = result
    entry = r["entry"]
    stop = r["stop"]
    rr = r["rr"]
    mtf = r["mtf"]
    pullback = r["pullback"]

    # Header
    entry_emoji = {
        "PULLBACK_ENTRY": "+",
        "BREAKOUT_WATCH": "?",
        "IN_NO_MANS_LAND": "~",
        "EXTENDED": "X",
        "BROKEN_DOWN": "X",
    }.get(entry["classification"], "?")

    best_rr = rr.get("best_rr", 0)
    weekly = mtf["weekly_trend"]

    lines = []
    lines.append(f"```")
    lines.append(f"{'='*50}")
    lines.append(f"{r['ticker']} — {entry['classification']} [{entry_emoji}] | Weekly: {weekly} | R/R: {best_rr}:1")
    lines.append(f"{'='*50}")
    lines.append("")

    # Price action
    lines.append("PRICE ACTION:")
    lines.append(f"  Current: ${r['price']:.2f} | 52wk High: ${r['high_52']:.2f} ({r['high_52_pct']:+.1f}%) | 52wk Low: ${r['low_52']:.2f} ({r['low_52_pct']:+.1f}%)")
    adx_str = f"ADX: {r['adx']:.0f}" if r["adx"] else "ADX: n/a"
    rsi_str = f"RSI: {r['rsi']:.0f}" if r["rsi"] else "RSI: n/a"
    lines.append(f"  Trend: {r['ma_status']} | {adx_str} | {rsi_str}")
    lines.append("")

    # Supports
    lines.append("SUPPORT LEVELS:")
    for i, s in enumerate(r["sr"]["supports"][:4]):
        stars = "*" * min(5, int(s["strength"]))
        lines.append(f"  S{i+1}: ${s['price']:>8.2f}  {s['type']:<12s} — {s['description']:<30s} {stars}")
    lines.append("")

    # Resistances
    lines.append("RESISTANCE LEVELS:")
    for i, res in enumerate(r["sr"]["resistances"][:4]):
        stars = "*" * min(5, int(res["strength"]))
        lines.append(f"  R{i+1}: ${res['price']:>8.2f}  {res['type']:<12s} — {res['description']:<30s} {stars}")
    lines.append("")

    # Trade plan
    lines.append(f"{'-'*50}")
    lines.append("TRADE PLAN:")
    lines.append(f"  ENTRY ZONE:  ${entry['entry_low']:.2f} — ${entry['entry_high']:.2f}")
    lines.append(f"  REASON:      {entry['reason']}")

    if stop["recommended"] and stop["recommended"] in stop["stops"]:
        rec_stop = stop["stops"][stop["recommended"]]
        lines.append(f"  STOP LOSS:   ${rec_stop['price']:.2f}  ({rec_stop['description']}, {rec_stop['risk_pct']:.1f}% risk)")
    lines.append("")

    # Targets
    for i, t in enumerate(rr.get("rr_ratios", [])):
        marker = " <-- PRIMARY" if i == 1 else ""
        lines.append(f"  TARGET {t['label']}:   ${t['target_price']:.2f}  ({t['type']})  +{t['gain_pct']:.1f}%  R/R {t['rr_ratio']}:1{marker}")
    lines.append("")

    # Scaling plan
    if len(rr.get("rr_ratios", [])) >= 2:
        lines.append("  SCALING:")
        for i, t in enumerate(rr["rr_ratios"]):
            if i == 0:
                lines.append(f"    At {t['label']} (${t['target_price']:.2f}): Sell 1/3, move stop to breakeven")
            elif i == 1:
                prev = rr["rr_ratios"][i-1]
                lines.append(f"    At {t['label']} (${t['target_price']:.2f}): Sell 1/3, trail stop to ${prev['target_price']:.2f}")
            else:
                lines.append(f"    At {t['label']} (${t['target_price']:.2f}): Sell final 1/3")
        lines.append("")

    # Position sizing
    lines.append(f"{'-'*50}")
    lines.append("POSITION SIZING (1% account risk):")
    for acct, ps in rr.get("position_sizes", {}).items():
        lines.append(f"  ${acct//1000}K account: {ps['shares']:>4d} shares (${ps['cost']:,.0f}) | Max loss: ${ps['max_loss']:.0f}")
    lines.append("")

    # MTF
    lines.append(f"MULTI-TIMEFRAME: [{mtf['alignment_emoji']}] {mtf['alignment']}")
    lines.append(f"  Weekly: {mtf['weekly_desc']}")
    pb_desc = "Pulling back to support" if mtf["daily_pullback"] else ("Above SMA50" if mtf["daily_above_50"] else "Below SMA50")
    lines.append(f"  Daily:  {pb_desc}")
    lines.append("")

    # Pullback quality
    lines.append(f"PULLBACK: {pullback['classification']} ({pullback['score']}/100)")
    for k, v in pullback.get("details", {}).items():
        lines.append(f"  {k}: {v}/20")
    lines.append("")

    # Earnings
    earn = r["earnings"]
    earn_icon = {"CLEAR": "+", "EARNINGS_APPROACHING": "!", "EARNINGS_RISK": "!!", "UNKNOWN": "?", "UNCHECKED": "~"}.get(earn["status"], "?")
    lines.append(f"EARNINGS: [{earn_icon}] {earn['description']}")

    # Assessment
    lines.append("")
    lines.append(f"ASSESSMENT: {rr['assessment']}")
    lines.append(f"{'='*50}")
    lines.append("```")

    return "\n".join(lines)


# ── Chart Generation ────────────────────────────────────────────────────────

def generate_chart(ticker: str, daily_df: pd.DataFrame, result: dict) -> io.BytesIO | None:
    """Generate trade setup chart with S/R lines, entry zone, stop, targets."""
    try:
        # Use last 6 months
        df = daily_df.iloc[-130:].copy() if len(daily_df) > 130 else daily_df.copy()

        fig, axes = plt.subplots(3, 1, figsize=(14, 10),
                                  gridspec_kw={"height_ratios": [5, 1.5, 1.5]},
                                  sharex=True)
        fig.patch.set_facecolor("#1a1a2e")

        for ax in axes:
            ax.set_facecolor("#1a1a2e")
            ax.tick_params(colors="white", labelsize=8)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_color("#444")
            ax.spines["bottom"].set_color("#444")

        ax_price, ax_vol, ax_rsi = axes

        dates = df.index
        close = df["Close"]

        # Price line
        ax_price.plot(dates, close, color="#00d4ff", linewidth=1.2, label="Close")

        # MAs
        ema21 = calc_ema(close, 21)
        sma50 = calc_sma(close, 50)
        sma200 = calc_sma(close, 200)
        ax_price.plot(dates, ema21, color="#4fc3f7", linewidth=0.8, alpha=0.7, label="EMA(21)")
        ax_price.plot(dates, sma50, color="#ff9800", linewidth=0.8, alpha=0.7, label="SMA(50)")
        if not sma200.isna().all():
            ax_price.plot(dates, sma200, color="#f44336", linewidth=0.8, alpha=0.7, label="SMA(200)")

        # S/R lines
        entry = result["entry"]
        sr = result["sr"]
        rr = result["rr"]
        stop = result["stop"]

        for s in sr["supports"][:4]:
            color = "#4caf50" if s["strength"] >= 3 else ("#ffeb3b" if s["strength"] >= 2 else "#666")
            ax_price.axhline(s["price"], color=color, linewidth=0.6, alpha=0.5, linestyle="--")
            ax_price.text(dates[-1], s["price"], f" S ${s['price']:.1f}", color=color,
                         fontsize=7, va="center", ha="left")

        for r in sr["resistances"][:4]:
            color = "#f44336" if r["strength"] >= 3 else ("#ffeb3b" if r["strength"] >= 2 else "#666")
            ax_price.axhline(r["price"], color=color, linewidth=0.6, alpha=0.5, linestyle="--")
            ax_price.text(dates[-1], r["price"], f" R ${r['price']:.1f}", color=color,
                         fontsize=7, va="center", ha="left")

        # Entry zone shading
        ax_price.axhspan(entry["entry_low"], entry["entry_high"],
                        color="#2196f3", alpha=0.12, label="Entry Zone")

        # Stop loss line
        if stop["recommended"] and stop["recommended"] in stop["stops"]:
            stop_price = stop["stops"][stop["recommended"]]["price"]
            ax_price.axhline(stop_price, color="#ff1744", linewidth=1.2, linestyle="-.",
                           label=f"Stop ${stop_price:.2f}")

        # Target lines
        for i, t in enumerate(rr.get("rr_ratios", [])[:3]):
            ax_price.axhline(t["target_price"], color="#00e676", linewidth=0.8, linestyle=":",
                           alpha=0.7)
            ax_price.text(dates[0], t["target_price"], f"T{i+1} ${t['target_price']:.1f} ",
                         color="#00e676", fontsize=7, va="center", ha="right")

        ax_price.legend(loc="upper left", fontsize=7, facecolor="#1a1a2e",
                       edgecolor="#444", labelcolor="white")

        # Title
        entry_cls = entry["classification"]
        best_rr = rr.get("best_rr", 0)
        ax_price.set_title(
            f"{result['ticker']} — {entry_cls} | R/R: {best_rr}:1 | Pullback: {result['pullback']['classification']}",
            color="white", fontsize=11, fontweight="bold", pad=10,
        )
        ax_price.yaxis.label.set_color("white")

        # Volume
        vol = df["Volume"]
        vol_avg = vol.rolling(20).mean()
        colors_vol = ["#4caf50" if c >= o else "#f44336"
                      for c, o in zip(df["Close"], df["Open"])]
        ax_vol.bar(dates, vol, color=colors_vol, alpha=0.6, width=0.8)
        ax_vol.plot(dates, vol_avg, color="#ffeb3b", linewidth=0.8, alpha=0.6, label="Vol Avg(20)")
        ax_vol.set_ylabel("Volume", color="white", fontsize=8)
        ax_vol.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x/1e6:.0f}M" if x >= 1e6 else f"{x/1e3:.0f}K"))
        ax_vol.legend(loc="upper left", fontsize=6, facecolor="#1a1a2e",
                     edgecolor="#444", labelcolor="white")

        # RSI
        rsi = calc_rsi(close)
        ax_rsi.plot(dates, rsi, color="#ba68c8", linewidth=0.9)
        ax_rsi.axhline(70, color="#f44336", linewidth=0.5, linestyle="--", alpha=0.5)
        ax_rsi.axhline(50, color="#888", linewidth=0.5, linestyle="--", alpha=0.3)
        ax_rsi.axhline(30, color="#4caf50", linewidth=0.5, linestyle="--", alpha=0.5)
        ax_rsi.set_ylabel("RSI(14)", color="white", fontsize=8)
        ax_rsi.set_ylim(15, 85)

        ax_rsi.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax_rsi.xaxis.set_major_locator(mdates.MonthLocator())
        plt.xticks(rotation=45, ha="right")

        fig.tight_layout(pad=1.0)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, facecolor="#1a1a2e", bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf

    except Exception as e:
        print(f"  Chart error for {ticker}: {e}", file=sys.stderr)
        return None


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(ET)
    print(f"Trade Setup Scanner — {now.strftime('%Y-%m-%d %I:%M %p ET')}")

    tickers = load_tickers()
    if not tickers:
        print("  No tickers to analyze", file=sys.stderr)
        return

    # Skip Japanese tickers (8411.T etc — no options/earnings data)
    tickers = [t for t in tickers if not t.endswith(".T")]

    print(f"  Analyzing {len(tickers)} tickers...")

    # Fetch daily (1y) and weekly (2y) data in parallel
    print("  Fetching daily data (1y)...")
    daily_data = batch_fetch(tickers, period="1y", interval="1d")
    print(f"  Got daily data for {len(daily_data)}/{len(tickers)} tickers")

    print("  Fetching weekly data (2y)...")
    weekly_data = batch_fetch(list(daily_data.keys()), period="2y", interval="1wk")
    print(f"  Got weekly data for {len(weekly_data)} tickers")

    # Check earnings for first 5 tickers (Alpha Vantage rate limit: 5/min)
    earnings_tickers = list(daily_data.keys())[:5]
    earnings_results = {}
    for t in earnings_tickers:
        earnings_results[t] = check_earnings_proximity(t)

    # Analyze each ticker
    results = []
    for ticker in sorted(daily_data.keys()):
        result = analyze_ticker(ticker, daily_data[ticker], weekly_data.get(ticker))
        if result is None:
            continue
        # Attach earnings if we checked
        if ticker in earnings_results:
            result["earnings"] = earnings_results[ticker]
        results.append(result)

    if not results:
        print("  No valid setups found")
        return

    print(f"  Generated {len(results)} trade setups")

    # Sort: PULLBACK_ENTRY first, then by R/R
    priority = {"PULLBACK_ENTRY": 0, "BREAKOUT_WATCH": 1, "IN_NO_MANS_LAND": 2, "EXTENDED": 3, "BROKEN_DOWN": 4}
    results.sort(key=lambda x: (priority.get(x["entry"]["classification"], 5), -x["rr"].get("best_rr", 0)))

    # Post header
    header = (
        f"```\n"
        f"{'='*50}\n"
        f"TRADE SETUP SCANNER — Entry, Stop & Targets\n"
        f"{now.strftime('%A, %B %d, %Y %I:%M %p ET')}\n"
        f"{'='*50}\n"
        f"Analyzed: {len(results)} stocks\n"
        f"```"
    )
    send_discord_text(header)

    # Summary table
    summary_lines = ["```"]
    summary_lines.append(f"{'TICKER':<8} {'SETUP':<18} {'ENTRY':>8} {'STOP':>8} {'T1':>8} {'R/R':>5} {'WEEKLY':<10} {'PB QUAL':<12}")
    summary_lines.append("-" * 85)
    for r in results:
        entry_cls = r["entry"]["classification"][:16]
        entry_mid = f"${r['entry']['entry_mid']:.2f}"
        stop_price = ""
        if r["stop"]["recommended"] and r["stop"]["recommended"] in r["stop"]["stops"]:
            stop_price = f"${r['stop']['stops'][r['stop']['recommended']]['price']:.2f}"
        t1_price = f"${r['rr']['rr_ratios'][0]['target_price']:.2f}" if r["rr"].get("rr_ratios") else "n/a"
        best_rr = f"{r['rr'].get('best_rr', 0):.1f}"
        weekly = r["mtf"]["weekly_trend"][:8]
        pb_qual = r["pullback"]["classification"][:10]
        summary_lines.append(f"{r['ticker']:<8} {entry_cls:<18} {entry_mid:>8} {stop_price:>8} {t1_price:>8} {best_rr:>5} {weekly:<10} {pb_qual:<12}")
    summary_lines.append("```")
    send_discord_text("\n".join(summary_lines))

    # Post detailed setups (top entries only — PULLBACK_ENTRY and BREAKOUT_WATCH)
    actionable = [r for r in results if r["entry"]["classification"] in ("PULLBACK_ENTRY", "BREAKOUT_WATCH")]
    if not actionable:
        # If no actionable, show top 3 by R/R
        actionable = results[:3]

    for r in actionable[:8]:  # max 8 detailed setups
        text = format_setup_text(r)
        send_discord_text(text)

        # Generate and post chart
        chart_buf = generate_chart(r["ticker"], daily_data[r["ticker"]], r)
        if chart_buf:
            send_discord_image(chart_buf, f"trade-setup-{r['ticker'].lower()}.png")

    # Post non-actionable tickers as brief summary
    non_actionable = [r for r in results if r not in actionable]
    if non_actionable:
        na_lines = ["```", "NON-ACTIONABLE (wait for better entry):", ""]
        for r in non_actionable:
            rr_str = f"R/R {r['rr'].get('best_rr', 0):.1f}:1"
            na_lines.append(f"  {r['ticker']:<8} {r['entry']['classification']:<18} ${r['price']:.2f}  {rr_str}  {r['entry']['reason'][:40]}")
        na_lines.append("```")
        send_discord_text("\n".join(na_lines))

    print(f"  Posted {len(actionable)} detailed setups + {len(non_actionable)} summaries to Discord")


if __name__ == "__main__":
    main()
