"""
Late Trend & Distribution Detection Scanner
Identifies when trends are exhausting and entering distribution/accumulation phases.

Modules:
  1. Trend Maturity Analysis
  2. Distribution/Accumulation Patterns (Wyckoff)
  3. Volume Distribution Analysis
  4. Momentum Deterioration
  5. Relative Weakness vs Market
  6. Failed Breakout / Breakdown
  7. Advanced Price Patterns (H&S, Wedges, Double Top/Bottom)
  8. High Implied Volatility (IBKR — graceful skip if unavailable)

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
    "https://discord.com/api/webhooks/1472505093311037523/"
    "JyiuPbsRxyFpthQTnGD2wphK36T5AJOrnaPZaD13rMC7DyU8W6vYA8-rFko5z6haN9zM"
)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


# ── Data Fetching ─────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame | None:
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


def batch_download(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
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


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    # When +DM > -DM, -DM = 0 and vice versa
    cond = plus_dm > minus_dm
    minus_dm[cond] = 0
    plus_dm[~cond] = 0

    atr = calc_atr(df, period)
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(period).mean()
    return adx


def calc_obv(df: pd.DataFrame) -> pd.Series:
    obv = pd.Series(0, index=df.index, dtype=float)
    for i in range(1, len(df)):
        if df["Close"].iloc[i] > df["Close"].iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] + df["Volume"].iloc[i]
        elif df["Close"].iloc[i] < df["Close"].iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] - df["Volume"].iloc[i]
        else:
            obv.iloc[i] = obv.iloc[i - 1]
    return obv


def find_swing_points(series: pd.Series, order: int = 5) -> tuple[list, list]:
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


# ── Module 1: Trend Maturity Analysis ─────────────────────────────────────────

def detect_trend_maturity(df: pd.DataFrame) -> list[dict]:
    signals = []
    close = df["Close"]
    if len(close) < 100:
        return signals

    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean() if len(close) >= 200 else None
    rsi = calc_rsi(close)
    atr = calc_atr(df, 20)
    price = close.iloc[-1]

    # Days above/below MA50
    above_ma50 = close > ma50
    days_above = 0
    for i in range(len(above_ma50) - 1, -1, -1):
        if above_ma50.iloc[i]:
            days_above += 1
        else:
            break

    days_below = 0
    if days_above == 0:
        for i in range(len(above_ma50) - 1, -1, -1):
            if not above_ma50.iloc[i]:
                days_below += 1
            else:
                break

    # Find trend start and magnitude
    if days_above > 0:
        trend_start_idx = max(0, len(close) - days_above)
        trend_start_price = close.iloc[trend_start_idx]
        magnitude = (price / trend_start_price - 1) * 100

        # RSI consecutive overbought days
        rsi_ob_days = 0
        for i in range(len(rsi) - 1, -1, -1):
            if not np.isnan(rsi.iloc[i]) and rsi.iloc[i] > 70:
                rsi_ob_days += 1
            else:
                break

        # Distance from MA200 in standard deviations
        dist_200_std = None
        if ma200 is not None and len(ma200.dropna()) > 20:
            ma200_val = ma200.iloc[-1]
            if not np.isnan(ma200_val):
                ma200_std = close.rolling(200).std().iloc[-1]
                if ma200_std > 0:
                    dist_200_std = (price - ma200_val) / ma200_std

        # Recent 20-day acceleration
        gain_20d = (price / close.iloc[-20] - 1) * 100 if len(close) >= 20 else 0
        atr_pct = (atr.iloc[-1] / price * 100) if atr.iloc[-1] > 0 else 1

        # Bearish exhaustion in uptrend
        reasons = []
        if days_above > 90:
            reasons.append(f"Trend extended {days_above} days above MA(50)")
        if magnitude > 40:
            reasons.append(f"+{magnitude:.0f}% from trend start")
        if rsi_ob_days >= 5:
            reasons.append(f"RSI overbought {rsi_ob_days} consecutive days")
        if dist_200_std is not None and dist_200_std > 2:
            reasons.append(f"{dist_200_std:.1f} std devs above MA(200)")
        if gain_20d > atr_pct * 40:
            reasons.append(f"Recent 20d gain {gain_20d:.1f}% (parabolic)")

        if len(reasons) >= 2:
            signals.append({
                "type": "BEARISH",
                "module": "Trend Maturity",
                "detail": " | ".join(reasons),
            })

    elif days_below > 0:
        trend_start_idx = max(0, len(close) - days_below)
        trend_start_price = close.iloc[trend_start_idx]
        magnitude = (price / trend_start_price - 1) * 100

        rsi_os_days = 0
        for i in range(len(rsi) - 1, -1, -1):
            if not np.isnan(rsi.iloc[i]) and rsi.iloc[i] < 30:
                rsi_os_days += 1
            else:
                break

        dist_200_std = None
        if ma200 is not None and len(ma200.dropna()) > 20:
            ma200_val = ma200.iloc[-1]
            if not np.isnan(ma200_val):
                ma200_std = close.rolling(200).std().iloc[-1]
                if ma200_std > 0:
                    dist_200_std = (price - ma200_val) / ma200_std

        reasons = []
        if days_below > 90:
            reasons.append(f"Downtrend extended {days_below} days below MA(50)")
        if magnitude < -30:
            reasons.append(f"{magnitude:.0f}% from trend start")
        if rsi_os_days >= 5:
            reasons.append(f"RSI oversold {rsi_os_days} consecutive days")
        if dist_200_std is not None and dist_200_std < -2:
            reasons.append(f"{abs(dist_200_std):.1f} std devs below MA(200)")

        if len(reasons) >= 2:
            signals.append({
                "type": "BULLISH",
                "module": "Trend Maturity",
                "detail": " | ".join(reasons),
            })

    return signals


# ── Module 2: Distribution/Accumulation (Wyckoff) ─────────────────────────────

def detect_wyckoff_distribution(df: pd.DataFrame) -> list[dict]:
    signals = []
    if len(df) < 60:
        return signals

    close = df["Close"]
    volume = df["Volume"]
    high = df["High"]
    low = df["Low"]
    avg_vol_20 = volume.rolling(20).mean()

    # Find potential Buying Climax: highest volume in 60 days + reversal
    last60 = df.iloc[-60:]
    vol_60 = last60["Volume"]
    max_vol_idx_rel = vol_60.argmax()
    max_vol_idx = len(df) - 60 + max_vol_idx_rel

    if max_vol_idx < 5 or max_vol_idx >= len(df) - 2:
        return signals

    climax_vol = volume.iloc[max_vol_idx]
    climax_date = df.index[max_vol_idx]
    climax_close = close.iloc[max_vol_idx]
    climax_open = df["Open"].iloc[max_vol_idx]
    avg_v = avg_vol_20.iloc[max_vol_idx]

    if avg_v == 0 or np.isnan(avg_v):
        return signals

    vol_multiple = climax_vol / avg_v

    # Must be significant volume spike (>2.5x avg)
    if vol_multiple < 2.5:
        return signals

    # Check if reversal candle (for BC: high close to high of day then drops)
    days_since = len(df) - 1 - max_vol_idx

    # Is this in an uptrend context? Check 20 days before climax
    if max_vol_idx >= 20:
        pre_trend = (climax_close / close.iloc[max_vol_idx - 20] - 1) * 100
    else:
        pre_trend = 0

    if pre_trend > 5:  # Uptrend before climax = potential distribution
        # Check subsequent behavior: lower volume tests
        post_data = df.iloc[max_vol_idx + 1:]
        if len(post_data) >= 3:
            post_avg_vol = post_data["Volume"].mean()
            vol_decline = post_avg_vol / climax_vol

            # Secondary tests on lower volume?
            high_after = post_data["High"].max()
            retested = high_after >= climax_close * 0.98

            reasons = [
                f"Buying Climax on {climax_date.strftime('%b %d')} "
                f"(vol: {climax_vol/1e6:.1f}M, {vol_multiple:.1f}x avg)"
            ]

            if retested and vol_decline < 0.6:
                reasons.append(
                    f"Secondary tests on {vol_decline:.0%} of climax volume — weak demand"
                )

            if len(reasons) >= 1 and days_since <= 40:
                signals.append({
                    "type": "BEARISH",
                    "module": "Wyckoff Distribution",
                    "detail": " | ".join(reasons),
                })

    elif pre_trend < -5:  # Downtrend before climax = potential accumulation
        post_data = df.iloc[max_vol_idx + 1:]
        if len(post_data) >= 3:
            post_avg_vol = post_data["Volume"].mean()
            vol_decline = post_avg_vol / climax_vol
            low_after = post_data["Low"].min()
            retested = low_after <= climax_close * 1.02

            reasons = [
                f"Selling Climax on {climax_date.strftime('%b %d')} "
                f"(vol: {climax_vol/1e6:.1f}M, {vol_multiple:.1f}x avg)"
            ]

            if retested and vol_decline < 0.6:
                reasons.append(
                    f"Retests on {vol_decline:.0%} of climax volume — selling exhaustion"
                )

            if days_since <= 40:
                signals.append({
                    "type": "BULLISH",
                    "module": "Wyckoff Accumulation",
                    "detail": " | ".join(reasons),
                })

    return signals


# ── Module 3: Volume Distribution Analysis ────────────────────────────────────

def detect_volume_distribution(df: pd.DataFrame) -> list[dict]:
    signals = []
    if len(df) < 25:
        return signals

    close = df["Close"]
    volume = df["Volume"]

    # Up/Down Volume Ratio (last 20 days)
    last20 = df.iloc[-20:]
    up_mask = last20["Close"] > last20["Close"].shift(1)
    down_mask = last20["Close"] < last20["Close"].shift(1)
    up_vol = last20.loc[up_mask, "Volume"].sum()
    down_vol = last20.loc[down_mask, "Volume"].sum()
    ud_ratio = up_vol / down_vol if down_vol > 0 else 999

    # Track ratio trend: compare first 10 vs last 10
    first10 = df.iloc[-20:-10]
    last10 = df.iloc[-10:]
    up1 = first10.loc[first10["Close"] > first10["Close"].shift(1), "Volume"].sum()
    dn1 = first10.loc[first10["Close"] < first10["Close"].shift(1), "Volume"].sum()
    up2 = last10.loc[last10["Close"] > last10["Close"].shift(1), "Volume"].sum()
    dn2 = last10.loc[last10["Close"] < last10["Close"].shift(1), "Volume"].sum()
    ratio1 = up1 / dn1 if dn1 > 0 else 999
    ratio2 = up2 / dn2 if dn2 > 0 else 999

    # OBV Divergence
    obv = calc_obv(df)
    obv_change_20 = (obv.iloc[-1] - obv.iloc[-20]) / abs(obv.iloc[-20]) * 100 if obv.iloc[-20] != 0 else 0
    price_change_20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100

    # Distribution: uptrend + down volume increasing
    if price_change_20 > 3 and ud_ratio < 1.0:
        signals.append({
            "type": "BEARISH",
            "module": "Volume Distribution",
            "detail": (
                f"Up/Down vol ratio {ud_ratio:.2f} (down volume dominant) "
                f"despite price +{price_change_20:.1f}% — distribution"
            ),
        })

    if price_change_20 > 3 and ratio1 > 1.5 and ratio2 < 1.0:
        signals.append({
            "type": "BEARISH",
            "module": "Volume Distribution",
            "detail": (
                f"Up/Down ratio declined from {ratio1:.1f} to {ratio2:.1f} "
                f"over 20 days — selling pressure building"
            ),
        })

    # OBV divergence
    if price_change_20 > 5 and obv_change_20 < -5:
        signals.append({
            "type": "BEARISH",
            "module": "OBV Divergence",
            "detail": (
                f"Price +{price_change_20:.1f}% but OBV {obv_change_20:.1f}% "
                f"over 20 days — smart money exiting"
            ),
        })
    elif price_change_20 < -5 and obv_change_20 > 5:
        signals.append({
            "type": "BULLISH",
            "module": "OBV Divergence",
            "detail": (
                f"Price {price_change_20:.1f}% but OBV +{obv_change_20:.1f}% "
                f"over 20 days — accumulation"
            ),
        })

    # Volume climax without price progress
    avg_vol = volume.rolling(20).mean()
    for i in range(-5, 0):
        idx = len(df) + i
        if idx < 20:
            continue
        v = volume.iloc[idx]
        av = avg_vol.iloc[idx]
        if av > 0 and v > av * 3:
            # High volume but no follow-through
            price_move = abs(close.iloc[idx] - close.iloc[idx - 1]) / close.iloc[idx - 1] * 100
            if price_move < 1.5:
                signals.append({
                    "type": "BEARISH" if close.iloc[idx] > close.iloc[idx - 5] else "BULLISH",
                    "module": "Volume Climax",
                    "detail": (
                        f"Extreme volume ({v/av:.1f}x avg) on {df.index[idx].strftime('%b %d')} "
                        f"with only {price_move:.1f}% price change — churning"
                    ),
                })
                break

    return signals


# ── Module 4: Momentum Deterioration ──────────────────────────────────────────

def detect_momentum_deterioration(df: pd.DataFrame) -> list[dict]:
    signals = []
    close = df["Close"]
    if len(close) < 30:
        return signals

    rsi = calc_rsi(close)
    _, _, macd_hist = calc_macd(close)
    adx = calc_adx(df)

    price_change_20 = (close.iloc[-1] / close.iloc[-21] - 1) * 100

    reasons = []

    # RSI rolling over from overbought
    rsi_peak = rsi.iloc[-20:].max()
    rsi_current = rsi.iloc[-1]
    if not np.isnan(rsi_peak) and not np.isnan(rsi_current):
        if rsi_peak > 70 and rsi_current < 70 and rsi_current > 50:
            reasons.append(f"RSI peaked at {rsi_peak:.0f}, now {rsi_current:.0f} (rolling over)")

        # RSI rolling up from oversold
        rsi_trough = rsi.iloc[-20:].min()
        if rsi_trough < 30 and rsi_current > 30 and rsi_current < 50:
            reasons.append(f"RSI troughed at {rsi_trough:.0f}, now {rsi_current:.0f} (recovering)")

    # MACD histogram declining
    hist_valid = macd_hist.iloc[-10:].dropna()
    if len(hist_valid) >= 5:
        x = np.arange(len(hist_valid))
        slope = np.polyfit(x, hist_valid.values, 1)[0]
        if hist_valid.iloc[-1] > 0 and slope < 0:
            # Positive but declining = momentum fading in uptrend
            consecutive_decline = 0
            for i in range(len(hist_valid) - 1, 0, -1):
                if hist_valid.iloc[i] < hist_valid.iloc[i - 1]:
                    consecutive_decline += 1
                else:
                    break
            if consecutive_decline >= 3:
                reasons.append(f"MACD histogram declining {consecutive_decline} straight days")
        elif hist_valid.iloc[-1] < 0 and slope > 0:
            # Negative but rising = momentum recovering in downtrend
            consecutive_rise = 0
            for i in range(len(hist_valid) - 1, 0, -1):
                if hist_valid.iloc[i] > hist_valid.iloc[i - 1]:
                    consecutive_rise += 1
                else:
                    break
            if consecutive_rise >= 3:
                reasons.append(f"MACD histogram rising {consecutive_rise} straight days (recovering)")

    # ADX weakening
    adx_valid = adx.iloc[-20:].dropna()
    if len(adx_valid) >= 10:
        adx_high = adx_valid.max()
        adx_current = adx_valid.iloc[-1]
        if adx_high > 30 and adx_current < adx_high * 0.8:
            reasons.append(f"ADX dropped from {adx_high:.0f} to {adx_current:.0f} — weakening trend")

    # Rate of change divergence
    roc_20 = (close / close.shift(20) - 1) * 100
    roc_current = roc_20.iloc[-1]
    if not np.isnan(roc_current):
        if price_change_20 > 5 and roc_current < roc_20.iloc[-10]:
            reasons.append(f"ROC declining ({roc_current:.1f}%) despite price rising")

    if len(reasons) >= 2:
        # Determine direction
        if price_change_20 > 0:
            sig_type = "BEARISH"
        else:
            sig_type = "BULLISH"

        signals.append({
            "type": sig_type,
            "module": "Momentum Deterioration",
            "detail": " | ".join(reasons),
        })

    return signals


# ── Module 5: Relative Weakness vs Market ─────────────────────────────────────

def detect_relative_weakness(df: pd.DataFrame, spy_df: pd.DataFrame) -> list[dict]:
    signals = []
    close = df["Close"]
    spy_close = spy_df["Close"]

    if len(close) < 60 or len(spy_close) < 60:
        return signals

    # Align dates
    common = close.index.intersection(spy_close.index)
    if len(common) < 40:
        return signals

    tc = close.reindex(common).dropna()
    sc = spy_close.reindex(common).dropna()
    common2 = tc.index.intersection(sc.index)
    tc = tc.reindex(common2)
    sc = sc.reindex(common2)

    if len(tc) < 40:
        return signals

    # Relative Strength ratio
    rs_ratio = tc / sc

    # RS 20-day slope
    rs_20 = rs_ratio.iloc[-20:]
    x = np.arange(len(rs_20))
    rs_slope_20 = np.polyfit(x, rs_20.values, 1)[0]

    # RS vs its MA50
    rs_ma50 = rs_ratio.rolling(50).mean() if len(rs_ratio) >= 50 else None

    # 20-day relative performance
    ticker_ret = (tc.iloc[-1] / tc.iloc[-20] - 1) * 100
    spy_ret = (sc.iloc[-1] / sc.iloc[-20] - 1) * 100
    relative_perf = ticker_ret - spy_ret

    # 20-day correlation
    if len(tc) >= 22:
        ticker_rets = tc.pct_change().iloc[-20:]
        spy_rets = sc.pct_change().iloc[-20:]
        corr = ticker_rets.corr(spy_rets)
    else:
        corr = 1.0

    reasons = []

    if relative_perf < -5:
        reasons.append(f"Underperforming SPY by {abs(relative_perf):.1f}% over 20 days")

    if rs_slope_20 < -0.001:
        reasons.append(f"RS ratio declining (20d slope: {rs_slope_20:.4f})")

    if rs_ma50 is not None and len(rs_ma50.dropna()) > 0:
        rs_val = rs_ratio.iloc[-1]
        rs_ma = rs_ma50.iloc[-1]
        if not np.isnan(rs_ma) and rs_val < rs_ma:
            reasons.append(f"RS ratio below 50-day avg — structural weakness")

    if not np.isnan(corr) and corr < 0.5:
        reasons.append(f"Low correlation with SPY ({corr:.2f}) — diverging")

    if len(reasons) >= 2:
        signals.append({
            "type": "BEARISH",
            "module": "Relative Weakness",
            "detail": " | ".join(reasons),
        })

    # Also check for relative strength (bullish)
    if relative_perf > 5 and rs_slope_20 > 0.001:
        signals.append({
            "type": "BULLISH",
            "module": "Relative Strength",
            "detail": (
                f"Outperforming SPY by +{relative_perf:.1f}% over 20 days, "
                f"RS ratio rising"
            ),
        })

    return signals


# ── Module 6: Failed Breakout / Breakdown ─────────────────────────────────────

def detect_failed_breakouts(df: pd.DataFrame) -> list[dict]:
    signals = []
    if len(df) < 30:
        return signals

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    avg_vol = volume.rolling(20).mean()

    ma50 = close.rolling(50).mean()

    # Find swing highs/lows as resistance/support
    highs_idx, lows_idx = find_swing_points(close, order=5)

    if len(highs_idx) < 2 or len(lows_idx) < 2:
        return signals

    resistance = close.iloc[highs_idx[-1]]
    support = close.iloc[lows_idx[-1]]

    # Check last 10 days for failed breakout/breakdown
    for days_back in range(1, 11):
        i = len(df) - days_back
        if i < 5:
            break

        day_close = close.iloc[i]
        day_high = high.iloc[i]
        day_low = low.iloc[i]
        day_vol = volume.iloc[i]
        av = avg_vol.iloc[i]
        if av == 0 or np.isnan(av):
            continue

        # Failed breakout above resistance
        if day_high > resistance * 1.005:  # Broke above
            # Check if subsequent days close below
            after = close.iloc[i + 1:] if i + 1 < len(close) else pd.Series()
            if len(after) >= 1 and after.iloc[-1] < resistance:
                break_vol = day_vol / av
                signals.append({
                    "type": "BEARISH",
                    "module": "Failed Breakout",
                    "detail": (
                        f"Broke resistance ${resistance:.2f} on "
                        f"{df.index[i].strftime('%b %d')} "
                        f"(vol: {break_vol:.1f}x avg), "
                        f"closed back below — bulls rejected"
                    ),
                })
                break

        # Failed breakdown below support
        if day_low < support * 0.995:  # Broke below
            after = close.iloc[i + 1:] if i + 1 < len(close) else pd.Series()
            if len(after) >= 1 and after.iloc[-1] > support:
                break_vol = day_vol / av
                signals.append({
                    "type": "BULLISH",
                    "module": "Failed Breakdown",
                    "detail": (
                        f"Broke support ${support:.2f} on "
                        f"{df.index[i].strftime('%b %d')} "
                        f"(vol: {break_vol:.1f}x avg), "
                        f"recovered above — bears trapped"
                    ),
                })
                break

    return signals


# ── Module 7: Advanced Price Patterns ─────────────────────────────────────────

def detect_advanced_patterns(df: pd.DataFrame) -> list[dict]:
    signals = []
    close = df["Close"]
    volume = df["Volume"]

    if len(close) < 60:
        return signals

    highs_idx, lows_idx = find_swing_points(close, order=7)

    # Double Top: Two highs within 3% at approximately same level
    if len(highs_idx) >= 2:
        h1_idx, h2_idx = highs_idx[-2], highs_idx[-1]
        h1, h2 = close.iloc[h1_idx], close.iloc[h2_idx]
        if abs(h1 - h2) / h1 < 0.03:  # Within 3%
            # Check for lower close between them (neckline)
            between = close.iloc[h1_idx:h2_idx + 1]
            neckline = between.min()
            current = close.iloc[-1]
            days_since = len(close) - 1 - h2_idx

            if days_since <= 15:
                if current < neckline:
                    signals.append({
                        "type": "BEARISH",
                        "module": "Double Top",
                        "detail": (
                            f"Tops at ${h1:.2f} and ${h2:.2f}, "
                            f"neckline ${neckline:.2f} broken — "
                            f"target ${neckline - (h1 - neckline):.2f}"
                        ),
                    })
                elif current < h2 * 0.98:
                    signals.append({
                        "type": "BEARISH",
                        "module": "Double Top",
                        "detail": (
                            f"Tops at ${h1:.2f} and ${h2:.2f}, "
                            f"neckline at ${neckline:.2f} — watch for breakdown"
                        ),
                    })

    # Double Bottom: Two lows within 3%
    if len(lows_idx) >= 2:
        l1_idx, l2_idx = lows_idx[-2], lows_idx[-1]
        l1, l2 = close.iloc[l1_idx], close.iloc[l2_idx]
        if abs(l1 - l2) / l1 < 0.03:
            between = close.iloc[l1_idx:l2_idx + 1]
            neckline = between.max()
            current = close.iloc[-1]
            days_since = len(close) - 1 - l2_idx

            if days_since <= 15:
                if current > neckline:
                    signals.append({
                        "type": "BULLISH",
                        "module": "Double Bottom",
                        "detail": (
                            f"Bottoms at ${l1:.2f} and ${l2:.2f}, "
                            f"neckline ${neckline:.2f} broken — "
                            f"target ${neckline + (neckline - l1):.2f}"
                        ),
                    })
                elif current > l2 * 1.02:
                    signals.append({
                        "type": "BULLISH",
                        "module": "Double Bottom",
                        "detail": (
                            f"Bottoms at ${l1:.2f} and ${l2:.2f}, "
                            f"neckline at ${neckline:.2f} — watch for breakout"
                        ),
                    })

    # Head & Shoulders (need 3 highs)
    if len(highs_idx) >= 3:
        ls_idx, h_idx, rs_idx = highs_idx[-3], highs_idx[-2], highs_idx[-1]
        ls, head, rs = close.iloc[ls_idx], close.iloc[h_idx], close.iloc[rs_idx]

        # Head should be highest, shoulders roughly equal
        if head > ls and head > rs:
            shoulder_diff = abs(ls - rs) / ls
            if shoulder_diff < 0.05:  # Shoulders within 5%
                # Neckline from lows between shoulders
                between1 = close.iloc[ls_idx:h_idx + 1].min()
                between2 = close.iloc[h_idx:rs_idx + 1].min()
                neckline = (between1 + between2) / 2
                current = close.iloc[-1]
                days_since = len(close) - 1 - rs_idx

                if days_since <= 15:
                    if current < neckline:
                        signals.append({
                            "type": "BEARISH",
                            "module": "Head & Shoulders",
                            "detail": (
                                f"LS ${ls:.2f}, Head ${head:.2f} (+{(head/ls-1)*100:.0f}%), "
                                f"RS ${rs:.2f}, Neckline ${neckline:.2f} broken"
                            ),
                        })
                    else:
                        signals.append({
                            "type": "BEARISH",
                            "module": "Head & Shoulders",
                            "detail": (
                                f"LS ${ls:.2f}, Head ${head:.2f}, RS ${rs:.2f} — "
                                f"forming, neckline at ${neckline:.2f}"
                            ),
                        })

    # Inverse H&S (need 3 lows)
    if len(lows_idx) >= 3:
        ls_idx, h_idx, rs_idx = lows_idx[-3], lows_idx[-2], lows_idx[-1]
        ls, head, rs = close.iloc[ls_idx], close.iloc[h_idx], close.iloc[rs_idx]

        if head < ls and head < rs:
            shoulder_diff = abs(ls - rs) / ls
            if shoulder_diff < 0.05:
                between1 = close.iloc[ls_idx:h_idx + 1].max()
                between2 = close.iloc[h_idx:rs_idx + 1].max()
                neckline = (between1 + between2) / 2
                current = close.iloc[-1]
                days_since = len(close) - 1 - rs_idx

                if days_since <= 15:
                    if current > neckline:
                        signals.append({
                            "type": "BULLISH",
                            "module": "Inverse H&S",
                            "detail": (
                                f"LS ${ls:.2f}, Head ${head:.2f}, RS ${rs:.2f}, "
                                f"Neckline ${neckline:.2f} broken"
                            ),
                        })
                    else:
                        signals.append({
                            "type": "BULLISH",
                            "module": "Inverse H&S",
                            "detail": (
                                f"LS ${ls:.2f}, Head ${head:.2f}, RS ${rs:.2f} — "
                                f"forming, neckline at ${neckline:.2f}"
                            ),
                        })

    return signals


# ── Module 8: High IV (IBKR) ─────────────────────────────────────────────────

def detect_high_volatility(df: pd.DataFrame) -> list[dict]:
    """Detect high historical volatility after extended move — signals distribution/hedging.
    Uses HV percentile ranking over 60 days."""
    signals = []
    close = df["Close"]
    if len(close) < 80:
        return signals

    # 20-day historical volatility (annualized)
    returns = np.log(close / close.shift(1))
    hv_20 = returns.rolling(20).std() * np.sqrt(252) * 100
    hv_20 = hv_20.dropna()

    if len(hv_20) < 60:
        return signals

    current_hv = hv_20.iloc[-1]
    recent_60 = hv_20.iloc[-60:]
    hv_percentile = (recent_60 < current_hv).sum() / len(recent_60) * 100

    # HV expansion rate (% change over 10 days)
    if len(hv_20) >= 10:
        hv_10_ago = hv_20.iloc[-10]
        if hv_10_ago > 0:
            hv_expansion = (current_hv / hv_10_ago - 1) * 100
        else:
            hv_expansion = 0
    else:
        hv_expansion = 0

    if hv_percentile >= 80:
        severity = "Very High" if hv_percentile >= 90 else "High"
        detail = (
            f"HV(20) at {current_hv:.1f}% ({hv_percentile:.0f}th pctl)"
        )
        if hv_expansion > 30:
            detail += f", up {hv_expansion:.0f}% in 10 days"
        detail += f" — {severity.lower()} vol after extended move, fear building"

        signals.append({
            "type": "BEARISH",
            "module": "High Volatility",
            "detail": detail,
        })

    return signals


# ── Signal Aggregation ────────────────────────────────────────────────────────

def scan_ticker(ticker: str, df: pd.DataFrame, spy_df: pd.DataFrame | None) -> dict | None:
    """Run all modules on a single ticker."""
    all_signals = []

    modules = [
        ("Trend Maturity", lambda: detect_trend_maturity(df)),
        ("Wyckoff Distribution", lambda: detect_wyckoff_distribution(df)),
        ("Volume Distribution", lambda: detect_volume_distribution(df)),
        ("Momentum", lambda: detect_momentum_deterioration(df)),
        ("Failed Breakouts", lambda: detect_failed_breakouts(df)),
        ("Advanced Patterns", lambda: detect_advanced_patterns(df)),
        ("High Volatility", lambda: detect_high_volatility(df)),
    ]

    for name, func in modules:
        try:
            all_signals.extend(func())
        except Exception as e:
            print(f"  {ticker} {name} error: {e}", file=sys.stderr)

    # Relative weakness needs SPY data
    if spy_df is not None:
        try:
            all_signals.extend(detect_relative_weakness(df, spy_df))
        except Exception as e:
            print(f"  {ticker} Relative Weakness error: {e}", file=sys.stderr)

    if not all_signals:
        return None

    return {
        "ticker": ticker,
        "price": round(df["Close"].iloc[-1], 2),
        "signals": all_signals,
    }


# ── Chart Rendering ───────────────────────────────────────────────────────────

def render_ticker_chart(ticker: str, df: pd.DataFrame, signals: list[dict],
                        spy_df: pd.DataFrame | None = None) -> io.BytesIO:
    """Render multi-panel chart for late trend signals."""
    close = df["Close"]
    volume = df["Volume"]
    rsi = calc_rsi(close)
    _, _, macd_hist = calc_macd(close)
    obv = calc_obv(df)

    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean() if len(close) >= 200 else None

    n_panels = 4 if spy_df is not None else 3
    height_ratios = [3, 1, 1, 1] if n_panels == 4 else [3, 1, 1]
    fig, axes = plt.subplots(n_panels, 1, figsize=(12, 3 * n_panels),
                             gridspec_kw={"height_ratios": height_ratios})
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

    ax1v = ax1.twinx()
    colors_vol = ["#51cf66" if close.iloc[i] >= close.iloc[max(0, i-1)] else "#ff6b6b"
                  for i in range(len(close))]
    ax1v.bar(dates, volume, color=colors_vol, alpha=0.2, width=0.8)
    ax1v.set_ylim(0, volume.max() * 4)
    ax1v.tick_params(labelright=False)

    signal_types = set(s["module"] for s in signals)
    ax1.set_title(
        f"{ticker} — Late Trend Signals: {', '.join(signal_types)}",
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

    # Panel 4: Relative Strength vs SPY
    if spy_df is not None and n_panels == 4:
        ax4 = axes[3]
        spy_close = spy_df["Close"]
        common = close.index.intersection(spy_close.index)
        if len(common) > 20:
            tc = close.reindex(common)
            sc = spy_close.reindex(common)
            rs = tc / sc
            rs_ma = rs.rolling(50).mean() if len(rs) >= 50 else None
            ax4.plot(common, rs, color="#00d4ff", linewidth=0.9, label="RS Ratio")
            if rs_ma is not None:
                ax4.plot(common, rs_ma, color="#ffd43b", linewidth=0.7, alpha=0.7, label="RS MA50")
            ax4.set_ylabel("RS vs SPY", color="white", fontsize=8)
            ax4.legend(loc="upper left", fontsize=7, facecolor="#1a1a2e", edgecolor="#444",
                       labelcolor="white")

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator())

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
    now_et = datetime.now(ET)
    messages = []

    header = (
        f"```\n"
        f"{'='*50}\n"
        f"  LATE TREND / DISTRIBUTION ALERTS\n"
        f"  {now_et.strftime('%a %b %d, %Y %I:%M %p ET')}\n"
        f"{'='*50}\n"
        f"```"
    )
    messages.append(header)

    # Separate distribution (bearish) and accumulation (bullish)
    dist_results = [r for r in results if any(s["type"] == "BEARISH" for s in r["signals"])]
    accum_results = [r for r in results if any(s["type"] == "BULLISH" for s in r["signals"])]

    if dist_results:
        messages.append("**DISTRIBUTION SIGNALS (Bearish - Late Uptrend)**")
        for r in sorted(dist_results, key=lambda x: len(x["signals"]), reverse=True):
            bear_sigs = [s for s in r["signals"] if s["type"] == "BEARISH"]
            if not bear_sigs:
                continue
            lines = [f"**{r['ticker']}** (${r['price']:.2f}) — Distribution Evidence"]
            lines.append("```")
            for s in bear_sigs:
                lines.append(f"  + {s['module']}: {s['detail']}")
            lines.append("```")
            messages.append("\n".join(lines))

    if accum_results:
        messages.append("**ACCUMULATION SIGNALS (Bullish - Late Downtrend)**")
        for r in sorted(accum_results, key=lambda x: len(x["signals"]), reverse=True):
            bull_sigs = [s for s in r["signals"] if s["type"] == "BULLISH"]
            if not bull_sigs:
                continue
            lines = [f"**{r['ticker']}** (${r['price']:.2f}) — Accumulation Evidence"]
            lines.append("```")
            for s in bull_sigs:
                lines.append(f"  + {s['module']}: {s['detail']}")
            lines.append("```")
            messages.append("\n".join(lines))

    if not results:
        messages.append("No late trend / distribution signals detected today.")

    return messages


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting Late Trend Scanner")

    # Load watchlist
    with open(TOOLS_DIR / "watchlist.json") as f:
        wl = json.load(f)
    tickers = wl.get("tickers", [])

    # Always include SPY for relative strength comparison
    all_tickers = list(set(tickers + ["SPY"]))
    print(f"Scanning {len(tickers)} tickers from watchlist (+ SPY benchmark)")

    # Batch download 1y data
    print("Fetching 1-year OHLCV data...")
    all_data = batch_download(all_tickers, period="1y")
    print(f"Got data for {len(all_data)}/{len(all_tickers)} tickers")

    spy_df = all_data.get("SPY")
    if spy_df is None:
        print("WARNING: No SPY data — relative strength module disabled", file=sys.stderr)

    # Scan each ticker
    results = []
    for ticker in tickers:
        df = all_data.get(ticker)
        if df is None or len(df) < 200:
            print(f"  {ticker}: insufficient data ({len(df) if df is not None else 0} days, need 200)")
            continue

        result = scan_ticker(ticker, df, spy_df)
        if result:
            results.append(result)
            print(f"  {ticker}: {len(result['signals'])} signal(s) detected")
        else:
            print(f"  {ticker}: no signals")

    print(f"\nTotal: {len(results)} tickers with signals")

    # Post text summaries
    messages = format_signals(results)
    for msg in messages:
        send_discord(msg)
        time.sleep(0.5)
    print(f"Posted {len(messages)} text messages")

    # Post charts for tickers with 3+ signals
    chart_count = 0
    for r in results:
        if len(r["signals"]) >= 3:
            ticker = r["ticker"]
            df = all_data[ticker]
            buf = render_ticker_chart(ticker, df, r["signals"], spy_df)
            send_discord_image(buf, f"late_trend_{ticker.lower()}.png")
            chart_count += 1
            time.sleep(1)

    print(f"Posted {chart_count} charts")
    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} Late Trend Scanner complete")


if __name__ == "__main__":
    main()
