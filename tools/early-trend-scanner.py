"""
Early Trend Change Detection Scanner
Detects early signs of trend reversals using multi-factor analysis:

Modules:
  1. Price-RSI Divergence
  2. Price-MACD Divergence
  3. Volume Divergence
  4. Wyckoff Springs & Upthrusts
  5. Moving Average Compression
  6. Candlestick Reversal Patterns at Key Levels
  7. Low Implied Volatility (IBKR — graceful skip if unavailable)

Posts results to Discord via webhook.
"""

import io
import json
import sys
import time
import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1472504894396043295/"
    "O0SmP-j18vPQuARqSePh6sctNX23qjVHflnVblRUyflAZOVPS-4Lz6lW_XgRwd-c0EnP"
)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


# ── Data Fetching ─────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame | None:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
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


def batch_download(tickers: list[str], period: str = "6mo") -> dict[str, pd.DataFrame]:
    result = {}
    def _fetch(t):
        return t, fetch_ohlcv(t, period)
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(_fetch, t) for t in tickers]
        for f in as_completed(futures):
            ticker, df = f.result()
            if df is not None:
                result[ticker] = df
    return result


# ── Technical Helpers ─────────────────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series):
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9).mean()
    histogram = macd_line - signal
    return macd_line, signal, histogram


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df["High"] - df["Low"],
        abs(df["High"] - df["Close"].shift()),
        abs(df["Low"] - df["Close"].shift())
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def find_swing_points(series: pd.Series, order: int = 5) -> tuple[list, list]:
    """Find swing highs and lows. Returns (highs_indices, lows_indices)."""
    highs, lows = [], []
    values = series.values
    for i in range(order, len(values) - order):
        if all(values[i] >= values[i - j] for j in range(1, order + 1)) and \
           all(values[i] >= values[i + j] for j in range(1, order + 1)):
            highs.append(i)
        if all(values[i] <= values[i - j] for j in range(1, order + 1)) and \
           all(values[i] <= values[i + j] for j in range(1, order + 1)):
            lows.append(i)
    return highs, lows


def get_support_resistance(df: pd.DataFrame) -> tuple[list[float], list[float]]:
    """Get support and resistance levels from MAs, swing points, round numbers."""
    close = df["Close"]
    price = close.iloc[-1]
    levels_support, levels_resist = [], []

    # MAs as levels
    for period in [20, 50, 200]:
        if len(close) >= period:
            ma_val = close.rolling(period).mean().iloc[-1]
            if not np.isnan(ma_val):
                if ma_val < price:
                    levels_support.append(ma_val)
                else:
                    levels_resist.append(ma_val)

    # Recent swing points
    _, lows_idx = find_swing_points(close, order=5)
    highs_idx, _ = find_swing_points(close, order=5)

    for idx in lows_idx[-5:]:
        levels_support.append(close.iloc[idx])
    for idx in highs_idx[-5:]:
        levels_resist.append(close.iloc[idx])

    # Round numbers near price
    base = round(price, -1)  # nearest 10
    for offset in [-10, 0, 10]:
        rnd = base + offset
        if rnd > 0:
            if rnd < price:
                levels_support.append(rnd)
            else:
                levels_resist.append(rnd)

    return sorted(set(levels_support)), sorted(set(levels_resist))


# ── Module 1: Price-RSI Divergence ────────────────────────────────────────────

def detect_rsi_divergence(df: pd.DataFrame) -> list[dict]:
    signals = []
    close = df["Close"]
    rsi = calc_rsi(close)

    price_highs_idx, price_lows_idx = find_swing_points(close, order=5)
    rsi_highs_idx, rsi_lows_idx = find_swing_points(rsi, order=5)

    # Bullish: price lower low, RSI higher low
    if len(price_lows_idx) >= 2 and len(rsi_lows_idx) >= 2:
        # Use last two lows
        p1, p2 = price_lows_idx[-2], price_lows_idx[-1]
        # Find corresponding RSI lows near those price lows
        r_lows_near_p1 = [i for i in rsi_lows_idx if abs(i - p1) <= 3]
        r_lows_near_p2 = [i for i in rsi_lows_idx if abs(i - p2) <= 3]

        if r_lows_near_p1 and r_lows_near_p2:
            r1 = r_lows_near_p1[-1]
            r2 = r_lows_near_p2[-1]
            if close.iloc[p2] < close.iloc[p1] and rsi.iloc[r2] > rsi.iloc[r1]:
                # Check recency — last swing should be within 20 bars of end
                if len(close) - p2 <= 20:
                    signals.append({
                        "type": "BULLISH",
                        "module": "RSI Divergence",
                        "detail": (
                            f"Price lower low at ${close.iloc[p2]:.2f} "
                            f"({df.index[p2].strftime('%b %d')}), "
                            f"RSI higher low ({rsi.iloc[r1]:.0f} -> {rsi.iloc[r2]:.0f})"
                        ),
                        "strength": min(100, int(abs(rsi.iloc[r2] - rsi.iloc[r1]) * 10)),
                    })

    # Bearish: price higher high, RSI lower high
    if len(price_highs_idx) >= 2 and len(rsi_highs_idx) >= 2:
        p1, p2 = price_highs_idx[-2], price_highs_idx[-1]
        r_highs_near_p1 = [i for i in rsi_highs_idx if abs(i - p1) <= 3]
        r_highs_near_p2 = [i for i in rsi_highs_idx if abs(i - p2) <= 3]

        if r_highs_near_p1 and r_highs_near_p2:
            r1 = r_highs_near_p1[-1]
            r2 = r_highs_near_p2[-1]
            if close.iloc[p2] > close.iloc[p1] and rsi.iloc[r2] < rsi.iloc[r1]:
                if len(close) - p2 <= 20:
                    signals.append({
                        "type": "BEARISH",
                        "module": "RSI Divergence",
                        "detail": (
                            f"Price higher high at ${close.iloc[p2]:.2f} "
                            f"({df.index[p2].strftime('%b %d')}), "
                            f"RSI lower high ({rsi.iloc[r1]:.0f} -> {rsi.iloc[r2]:.0f})"
                        ),
                        "strength": min(100, int(abs(rsi.iloc[r1] - rsi.iloc[r2]) * 10)),
                    })

    return signals


# ── Module 2: Price-MACD Divergence ───────────────────────────────────────────

def detect_macd_divergence(df: pd.DataFrame) -> list[dict]:
    signals = []
    close = df["Close"]
    _, _, histogram = calc_macd(close)

    price_highs_idx, price_lows_idx = find_swing_points(close, order=5)
    hist_highs_idx, hist_lows_idx = find_swing_points(histogram, order=5)

    # Bullish: price lower low, MACD histogram higher low
    if len(price_lows_idx) >= 2 and len(hist_lows_idx) >= 2:
        p1, p2 = price_lows_idx[-2], price_lows_idx[-1]
        h_near_p1 = [i for i in hist_lows_idx if abs(i - p1) <= 5]
        h_near_p2 = [i for i in hist_lows_idx if abs(i - p2) <= 5]

        if h_near_p1 and h_near_p2:
            h1, h2 = h_near_p1[-1], h_near_p2[-1]
            if close.iloc[p2] < close.iloc[p1] and histogram.iloc[h2] > histogram.iloc[h1]:
                if len(close) - p2 <= 20:
                    signals.append({
                        "type": "BULLISH",
                        "module": "MACD Divergence",
                        "detail": (
                            f"Price lower low at ${close.iloc[p2]:.2f}, "
                            f"MACD histogram higher low "
                            f"({histogram.iloc[h1]:.3f} -> {histogram.iloc[h2]:.3f})"
                        ),
                    })

    # Bearish: price higher high, MACD histogram lower high
    if len(price_highs_idx) >= 2 and len(hist_highs_idx) >= 2:
        p1, p2 = price_highs_idx[-2], price_highs_idx[-1]
        h_near_p1 = [i for i in hist_highs_idx if abs(i - p1) <= 5]
        h_near_p2 = [i for i in hist_highs_idx if abs(i - p2) <= 5]

        if h_near_p1 and h_near_p2:
            h1, h2 = h_near_p1[-1], h_near_p2[-1]
            if close.iloc[p2] > close.iloc[p1] and histogram.iloc[h2] < histogram.iloc[h1]:
                if len(close) - p2 <= 20:
                    signals.append({
                        "type": "BEARISH",
                        "module": "MACD Divergence",
                        "detail": (
                            f"Price higher high at ${close.iloc[p2]:.2f}, "
                            f"MACD histogram lower high "
                            f"({histogram.iloc[h1]:.3f} -> {histogram.iloc[h2]:.3f})"
                        ),
                    })

    return signals


# ── Module 3: Volume Divergence ───────────────────────────────────────────────

def detect_volume_divergence(df: pd.DataFrame) -> list[dict]:
    signals = []
    close = df["Close"]
    volume = df["Volume"]
    avg_vol_20 = volume.rolling(20).mean()

    if len(df) < 25:
        return signals

    current_vol = volume.iloc[-1]
    avg_vol = avg_vol_20.iloc[-1]
    if avg_vol == 0 or np.isnan(avg_vol):
        return signals

    vol_ratio = current_vol / avg_vol

    # Low volume: < 60% of 20-day avg for 3+ of last 5 days
    last5_ratios = (volume.iloc[-5:] / avg_vol_20.iloc[-5:]).dropna()
    low_vol_days = (last5_ratios < 0.6).sum()

    # Volume trend (10-day linear regression slope)
    vol_10 = volume.iloc[-10:].values.astype(float)
    x = np.arange(len(vol_10))
    if len(vol_10) >= 10 and not np.any(np.isnan(vol_10)):
        slope = np.polyfit(x, vol_10, 1)[0]
        vol_declining = slope < 0
    else:
        slope = 0
        vol_declining = False

    # Up vs down volume (last 20 days)
    last20 = df.iloc[-20:]
    up_days = last20[last20["Close"] > last20["Close"].shift(1)]
    down_days = last20[last20["Close"] < last20["Close"].shift(1)]
    up_vol = up_days["Volume"].sum() if len(up_days) > 0 else 0
    down_vol = down_days["Volume"].sum() if len(down_days) > 0 else 0

    # Price trend direction
    price_change_20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100

    # Volume divergence: price rising + volume falling (bearish)
    if price_change_20 > 3 and vol_declining and low_vol_days >= 3:
        signals.append({
            "type": "BEARISH",
            "module": "Volume Divergence",
            "detail": (
                f"Price up {price_change_20:.1f}% over 20d but volume declining — "
                f"{low_vol_days}/5 days below 60% avg, "
                f"current vol {vol_ratio:.0%} of 20d avg"
            ),
        })

    # Volume divergence: price falling + volume falling (bullish — selling exhaustion)
    if price_change_20 < -3 and vol_declining and low_vol_days >= 3:
        signals.append({
            "type": "BULLISH",
            "module": "Volume Divergence",
            "detail": (
                f"Price down {price_change_20:.1f}% over 20d with declining volume — "
                f"selling pressure exhausting, "
                f"current vol {vol_ratio:.0%} of 20d avg"
            ),
        })

    # Down volume exceeding up volume in uptrend
    if price_change_20 > 3 and down_vol > up_vol * 1.2 and down_vol > 0:
        signals.append({
            "type": "BEARISH",
            "module": "Volume Divergence",
            "detail": (
                f"Down volume ({down_vol/1e6:.1f}M) exceeds up volume "
                f"({up_vol/1e6:.1f}M) over last 20d despite price rising"
            ),
        })

    return signals


# ── Module 4: Wyckoff Springs & Upthrusts ─────────────────────────────────────

def detect_wyckoff_events(df: pd.DataFrame) -> list[dict]:
    signals = []
    if len(df) < 30:
        return signals

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    avg_vol_20 = volume.rolling(20).mean()
    atr = calc_atr(df, 14)
    atr_60 = calc_atr(df, 60) if len(df) >= 65 else atr

    # Support/resistance from 20-day rolling min/max
    rolling_low_20 = low.rolling(20).min()
    rolling_high_20 = high.rolling(20).max()

    # Check for ATR compression (consolidation context)
    if len(df) >= 65:
        recent_atr = atr.iloc[-1]
        avg_atr_60 = atr_60.iloc[-1]
        in_consolidation = recent_atr < avg_atr_60 * 0.8 if not np.isnan(avg_atr_60) else False
    else:
        in_consolidation = False

    # Check last 5 days for spring/upthrust
    for i in range(-5, 0):
        idx = len(df) + i
        if idx < 20:
            continue

        day_low = low.iloc[idx]
        day_high = high.iloc[idx]
        day_close = close.iloc[idx]
        day_vol = volume.iloc[idx]
        avg_v = avg_vol_20.iloc[idx]
        support = rolling_low_20.iloc[idx - 1]
        resistance = rolling_high_20.iloc[idx - 1]

        if np.isnan(support) or np.isnan(resistance) or avg_v == 0:
            continue

        vol_spike = day_vol > avg_v * 1.5

        # Spring: low breaks support but close above support
        if day_low < support and day_close > support:
            # Check for reversal in next days
            remaining = df.iloc[idx + 1:]
            if len(remaining) > 0:
                reversal_up = remaining["Close"].iloc[0] > day_close if len(remaining) >= 1 else False
                if vol_spike or reversal_up:
                    signals.append({
                        "type": "BULLISH",
                        "module": "Wyckoff Spring",
                        "detail": (
                            f"Broke support at ${support:.2f} on "
                            f"{df.index[idx].strftime('%b %d')}, "
                            f"reversed on {day_vol / avg_v:.0%} volume"
                            + (" (consolidation context)" if in_consolidation else "")
                        ),
                    })
                    break

        # Upthrust: high breaks resistance but close below resistance
        if day_high > resistance and day_close < resistance:
            remaining = df.iloc[idx + 1:]
            if len(remaining) > 0:
                reversal_down = remaining["Close"].iloc[0] < day_close if len(remaining) >= 1 else False
                if vol_spike or reversal_down:
                    signals.append({
                        "type": "BEARISH",
                        "module": "Wyckoff Upthrust",
                        "detail": (
                            f"Broke resistance at ${resistance:.2f} on "
                            f"{df.index[idx].strftime('%b %d')}, "
                            f"reversed on {day_vol / avg_v:.0%} volume"
                            + (" (consolidation context)" if in_consolidation else "")
                        ),
                    })
                    break

    return signals


# ── Module 5: Moving Average Compression ──────────────────────────────────────

def detect_ma_compression(df: pd.DataFrame) -> list[dict]:
    signals = []
    close = df["Close"]
    if len(close) < 60:
        return signals

    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()

    # Compression: stdev of MAs / price
    compression = pd.Series(index=close.index, dtype=float)
    for i in range(49, len(close)):
        vals = [ma10.iloc[i], ma20.iloc[i], ma50.iloc[i]]
        if not any(np.isnan(v) for v in vals):
            compression.iloc[i] = np.std(vals) / close.iloc[i] * 100

    compression = compression.dropna()
    if len(compression) < 60:
        return signals

    # Percentile of current compression vs last 60 days
    recent = compression.iloc[-60:]
    current = compression.iloc[-1]
    percentile = (recent < current).sum() / len(recent) * 100

    # Bollinger Band width percentile
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_width = ((bb_mid + 2 * bb_std) - (bb_mid - 2 * bb_std)) / bb_mid * 100
    bb_width = bb_width.dropna()

    if len(bb_width) >= 60:
        bb_recent = bb_width.iloc[-60:]
        bb_current = bb_width.iloc[-1]
        bb_percentile = (bb_recent < bb_current).sum() / len(bb_recent) * 100
    else:
        bb_percentile = 50

    # Direction bias
    price = close.iloc[-1]
    above_mas = sum([
        1 if price > ma10.iloc[-1] else -1,
        1 if price > ma20.iloc[-1] else -1,
        1 if price > ma50.iloc[-1] else -1,
    ])
    bias = "BULLISH" if above_mas > 0 else "BEARISH" if above_mas < 0 else "NEUTRAL"

    if percentile <= 15:
        severity = "Extreme" if percentile <= 5 else "High"
        signals.append({
            "type": bias if bias != "NEUTRAL" else "BULLISH",
            "module": "MA Compression",
            "detail": (
                f"{severity} compression: {percentile:.0f}th percentile "
                f"(BBW at {bb_percentile:.0f}th pctl) — "
                f"volatility expansion likely, bias {bias.lower()}"
            ),
        })

    return signals


# ── Module 6: Candlestick Reversal Patterns ───────────────────────────────────

def detect_candlestick_patterns(df: pd.DataFrame) -> list[dict]:
    signals = []
    if len(df) < 25:
        return signals

    close = df["Close"]
    open_ = df["Open"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    avg_vol = volume.rolling(20).mean()

    support_levels, resist_levels = get_support_resistance(df)
    price = close.iloc[-1]

    # Check last 3 days for patterns
    for offset in range(-3, 0):
        i = len(df) + offset
        if i < 2:
            continue

        o, h, l, c = open_.iloc[i], high.iloc[i], low.iloc[i], close.iloc[i]
        body = abs(c - o)
        upper_shadow = h - max(o, c)
        lower_shadow = min(o, c) - l
        full_range = h - l
        vol_ratio = volume.iloc[i] / avg_vol.iloc[i] if avg_vol.iloc[i] > 0 else 1
        date_str = df.index[i].strftime('%b %d')

        if full_range == 0:
            continue

        # Check proximity to key levels
        near_support = any(abs(l - s) / price < 0.01 for s in support_levels) if support_levels else False
        near_resist = any(abs(h - r) / price < 0.01 for r in resist_levels) if resist_levels else False
        nearest_level = None
        if near_support:
            nearest_level = min(support_levels, key=lambda s: abs(l - s))
        elif near_resist:
            nearest_level = min(resist_levels, key=lambda r: abs(h - r))

        # Hammer (bullish): small body at top, long lower shadow
        if lower_shadow > body * 2 and upper_shadow < body * 0.5 and near_support:
            if vol_ratio > 1.2:
                signals.append({
                    "type": "BULLISH",
                    "module": "Candlestick Pattern",
                    "detail": (
                        f"Hammer at ${nearest_level:.2f} ({date_str}), "
                        f"volume {vol_ratio:.0%} of avg"
                    ),
                })
                break

        # Shooting Star (bearish): small body at bottom, long upper shadow
        if upper_shadow > body * 2 and lower_shadow < body * 0.5 and near_resist:
            if vol_ratio > 1.2:
                signals.append({
                    "type": "BEARISH",
                    "module": "Candlestick Pattern",
                    "detail": (
                        f"Shooting Star at ${nearest_level:.2f} ({date_str}), "
                        f"volume {vol_ratio:.0%} of avg"
                    ),
                })
                break

        # Bullish Engulfing
        if i >= 1:
            prev_o, prev_c = open_.iloc[i - 1], close.iloc[i - 1]
            if prev_c < prev_o and c > o:  # prev red, current green
                if o <= prev_c and c >= prev_o:  # engulfs
                    if near_support and vol_ratio > 1.2:
                        signals.append({
                            "type": "BULLISH",
                            "module": "Candlestick Pattern",
                            "detail": (
                                f"Bullish Engulfing near ${nearest_level:.2f} ({date_str}), "
                                f"volume {vol_ratio:.0%} of avg"
                            ),
                        })
                        break

        # Bearish Engulfing
        if i >= 1:
            prev_o, prev_c = open_.iloc[i - 1], close.iloc[i - 1]
            if prev_c > prev_o and c < o:  # prev green, current red
                if o >= prev_c and c <= prev_o:  # engulfs
                    if near_resist and vol_ratio > 1.2:
                        signals.append({
                            "type": "BEARISH",
                            "module": "Candlestick Pattern",
                            "detail": (
                                f"Bearish Engulfing near ${nearest_level:.2f} ({date_str}), "
                                f"volume {vol_ratio:.0%} of avg"
                            ),
                        })
                        break

    return signals


# ── Module 7: Low Implied Volatility (IBKR) ──────────────────────────────────

def detect_low_volatility(df: pd.DataFrame) -> list[dict]:
    """Detect low historical volatility — often precedes large moves (volatility expansion).
    Uses HV percentile ranking over 60 days as a proxy for IV percentile."""
    signals = []
    close = df["Close"]
    if len(close) < 80:
        return signals

    # 20-day historical volatility (annualized)
    returns = np.log(close / close.shift(1))
    hv_20 = returns.rolling(20).std() * np.sqrt(252) * 100  # as percentage
    hv_20 = hv_20.dropna()

    if len(hv_20) < 60:
        return signals

    current_hv = hv_20.iloc[-1]
    recent_60 = hv_20.iloc[-60:]
    hv_percentile = (recent_60 < current_hv).sum() / len(recent_60) * 100

    # Also check Bollinger Band width percentile (tighter proxy for IV)
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_width = (2 * bb_std * 2) / bb_mid * 100  # BB width as % of price
    bb_width = bb_width.dropna()

    if len(bb_width) >= 60:
        bb_recent = bb_width.iloc[-60:]
        bb_pctl = (bb_recent < bb_width.iloc[-1]).sum() / len(bb_recent) * 100
    else:
        bb_pctl = 50

    if hv_percentile <= 20:
        severity = "Very Low" if hv_percentile <= 10 else "Low"
        signals.append({
            "type": "BULLISH",
            "module": "Low Volatility",
            "detail": (
                f"HV(20) at {current_hv:.1f}% ({hv_percentile:.0f}th pctl), "
                f"BBW at {bb_pctl:.0f}th pctl — "
                f"{severity.lower()} vol, expansion likely (coiled spring)"
            ),
        })

    return signals


# ── Signal Aggregation ────────────────────────────────────────────────────────

def scan_ticker(ticker: str, df: pd.DataFrame) -> dict | None:
    """Run all modules on a single ticker. Returns signal dict or None."""
    all_signals = []

    try:
        all_signals.extend(detect_rsi_divergence(df))
    except Exception as e:
        print(f"  {ticker} RSI divergence error: {e}", file=sys.stderr)

    try:
        all_signals.extend(detect_macd_divergence(df))
    except Exception as e:
        print(f"  {ticker} MACD divergence error: {e}", file=sys.stderr)

    try:
        all_signals.extend(detect_volume_divergence(df))
    except Exception as e:
        print(f"  {ticker} volume divergence error: {e}", file=sys.stderr)

    try:
        all_signals.extend(detect_wyckoff_events(df))
    except Exception as e:
        print(f"  {ticker} Wyckoff error: {e}", file=sys.stderr)

    try:
        all_signals.extend(detect_ma_compression(df))
    except Exception as e:
        print(f"  {ticker} MA compression error: {e}", file=sys.stderr)

    try:
        all_signals.extend(detect_candlestick_patterns(df))
    except Exception as e:
        print(f"  {ticker} candlestick error: {e}", file=sys.stderr)

    # Module 7: Low Volatility (HV percentile — proxy for IV)
    try:
        all_signals.extend(detect_low_volatility(df))
    except Exception as e:
        print(f"  {ticker} Low Volatility error: {e}", file=sys.stderr)

    if not all_signals:
        return None

    return {
        "ticker": ticker,
        "price": round(df["Close"].iloc[-1], 2),
        "signals": all_signals,
    }


# ── Chart Rendering ───────────────────────────────────────────────────────────

def render_ticker_chart(ticker: str, df: pd.DataFrame, signals: list[dict]) -> io.BytesIO:
    """Render a multi-panel chart for a ticker with detected signals."""
    close = df["Close"]
    volume = df["Volume"]
    rsi = calc_rsi(close)
    _, _, macd_hist = calc_macd(close)

    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean() if len(close) >= 200 else None

    fig, axes = plt.subplots(3, 1, figsize=(12, 9), gridspec_kw={"height_ratios": [3, 1, 1]})
    fig.patch.set_facecolor("#1a1a2e")

    for ax in axes:
        ax.set_facecolor("#1a1a2e")
        ax.tick_params(colors="white", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#444")
        ax.grid(True, alpha=0.1, color="white")

    dates = df.index

    # Panel 1: Price + Volume + MAs
    ax1 = axes[0]
    ax1.plot(dates, close, color="#00d4ff", linewidth=1.2, label="Close")
    ax1.plot(dates, ma20, color="#ffd43b", linewidth=0.8, alpha=0.7, label="MA20")
    ax1.plot(dates, ma50, color="#ff922b", linewidth=0.8, alpha=0.7, label="MA50")
    if ma200 is not None:
        ax1.plot(dates, ma200, color="#ff6b6b", linewidth=0.8, alpha=0.7, label="MA200")

    # Volume bars on secondary axis
    ax1v = ax1.twinx()
    colors_vol = ["#51cf66" if close.iloc[i] >= close.iloc[max(0, i-1)] else "#ff6b6b"
                  for i in range(len(close))]
    ax1v.bar(dates, volume, color=colors_vol, alpha=0.2, width=0.8)
    ax1v.set_ylim(0, volume.max() * 4)
    ax1v.tick_params(labelright=False)

    # Mark signal types on chart
    bull_signals = [s for s in signals if s["type"] == "BULLISH"]
    bear_signals = [s for s in signals if s["type"] == "BEARISH"]

    signal_types = set(s["module"] for s in signals)
    signal_text = ", ".join(signal_types)

    ax1.set_title(
        f"{ticker} — Early Trend Signals: {signal_text}",
        color="white", fontsize=11, fontweight="bold", pad=8,
    )
    ax1.legend(loc="upper left", fontsize=7, facecolor="#1a1a2e", edgecolor="#444",
               labelcolor="white")
    ax1.set_ylabel("Price", color="white", fontsize=8)

    # Panel 2: RSI
    ax2 = axes[1]
    ax2.plot(dates, rsi, color="#cc5de8", linewidth=0.9)
    ax2.axhline(70, color="#ff6b6b", alpha=0.5, linewidth=0.5, linestyle="--")
    ax2.axhline(30, color="#51cf66", alpha=0.5, linewidth=0.5, linestyle="--")
    ax2.fill_between(dates, 70, 100, alpha=0.05, color="#ff6b6b")
    ax2.fill_between(dates, 0, 30, alpha=0.05, color="#51cf66")
    ax2.set_ylabel("RSI", color="white", fontsize=8)
    ax2.set_ylim(10, 90)

    # Panel 3: MACD Histogram
    ax3 = axes[2]
    colors_macd = ["#51cf66" if v >= 0 else "#ff6b6b" for v in macd_hist]
    ax3.bar(dates, macd_hist, color=colors_macd, alpha=0.7, width=0.8)
    ax3.axhline(0, color="white", alpha=0.3, linewidth=0.5)
    ax3.set_ylabel("MACD Hist", color="white", fontsize=8)

    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax3.xaxis.set_major_locator(mdates.MonthLocator())

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor="#1a1a2e")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── Discord Posting ───────────────────────────────────────────────────────────

def send_discord(message: str):
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Discord send failed: {e}")


def send_discord_image(buf: io.BytesIO, filename: str):
    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            files={"file": (filename, buf, "image/png")},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Discord image send failed: {e}")


# ── Output Formatting ─────────────────────────────────────────────────────────

def format_signals(results: list[dict]) -> list[str]:
    """Format all detected signals into Discord messages."""
    now_et = datetime.now(ET)
    messages = []

    # Split by bullish/bearish
    bullish_results = [r for r in results if any(s["type"] == "BULLISH" for s in r["signals"])]
    bearish_results = [r for r in results if any(s["type"] == "BEARISH" for s in r["signals"])]

    header = (
        f"```\n"
        f"{'='*50}\n"
        f"  EARLY TREND CHANGE SIGNALS\n"
        f"  {now_et.strftime('%a %b %d, %Y %I:%M %p ET')}\n"
        f"{'='*50}\n"
        f"```"
    )
    messages.append(header)

    for r in sorted(results, key=lambda x: len(x["signals"]), reverse=True):
        ticker = r["ticker"]
        price = r["price"]
        bull_sigs = [s for s in r["signals"] if s["type"] == "BULLISH"]
        bear_sigs = [s for s in r["signals"] if s["type"] == "BEARISH"]

        if bull_sigs:
            direction = "BULLISH"
        elif bear_sigs:
            direction = "BEARISH"
        else:
            direction = "MIXED"

        lines = [f"**{ticker}** (${price:.2f}) — {direction} Setup"]
        lines.append("```")
        for s in r["signals"]:
            lines.append(f"  + {s['module']}: {s['detail']}")
        lines.append("```")

        msg = "\n".join(lines)
        messages.append(msg)

    if not results:
        messages.append("No early trend change signals detected today.")

    return messages


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting Early Trend Scanner")

    # Load watchlist
    with open(TOOLS_DIR / "watchlist.json") as f:
        wl = json.load(f)
    tickers = wl.get("tickers", [])
    print(f"Scanning {len(tickers)} tickers from watchlist")

    # Batch download 6mo data
    print("Fetching 6-month OHLCV data...")
    all_data = batch_download(tickers, period="6mo")
    print(f"Got data for {len(all_data)}/{len(tickers)} tickers")

    # Scan each ticker
    results = []
    for ticker in tickers:
        df = all_data.get(ticker)
        if df is None or len(df) < 120:
            print(f"  {ticker}: insufficient data (skipped)")
            continue

        result = scan_ticker(ticker, df)
        if result:
            results.append(result)
            print(f"  {ticker}: {len(result['signals'])} signal(s) detected")
        else:
            print(f"  {ticker}: no signals")

    print(f"\nTotal: {len(results)} tickers with signals")

    # Post text summaries to Discord
    messages = format_signals(results)
    for msg in messages:
        send_discord(msg)
        time.sleep(0.5)
    print(f"Posted {len(messages)} text messages")

    # Post charts for tickers with 2+ signals
    chart_count = 0
    for r in results:
        if len(r["signals"]) >= 2:
            ticker = r["ticker"]
            df = all_data[ticker]
            buf = render_ticker_chart(ticker, df, r["signals"])
            send_discord_image(buf, f"early_trend_{ticker.lower()}.png")
            chart_count += 1
            time.sleep(1)

    print(f"Posted {chart_count} charts")
    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} Early Trend Scanner complete")


if __name__ == "__main__":
    main()
