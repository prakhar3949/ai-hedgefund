"""
Bubble Scanner — Trend Entry & Exit Planner (Druckenmiller / AQR / PTJ)

Identifies sectors / subsectors in a bubble regime, then surfaces stock-level
entries (A: New-Leg Breakout, B: Boring Pullback, C: Failed Breakdown,
D: RS Leadership) and graduated exit signals (Flashing Yellow / Solid Yellow
/ Orange / Red) on holdings inside the bubble universe.

Universe: 48 ETFs from etf-holdings.json (subsectors + EW + CW sector ETFs).
Stock universe inside a bubble theme = ETF holdings ∩ watchlist ∪ ETF itself.

Output sections to Discord:
  1. Header — regime gate (breadth + vol) GATE OPEN / CLOSED
  2. FULL BUBBLES (4/4 met)
  3. EMERGING (3/4 met)
  4. WATCHLIST (2/4 met)
  5. Entry signals today
  6. Exit signals today
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1504380703645761536/"
    "NrBply5IJF3F8h8BB8qANuB1-8lLsPp4xEz_zywcj5205cS0ZzMJNacAsdTj3029RduR"
)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# Sizing
TARGET_VOL = 0.50          # 50% annualized target vol
BASE_SIZE_FULL = 0.05      # 5% base for FULL BUBBLE
BASE_SIZE_EMERGING = 0.03  # 3% base for EMERGING
PER_NAME_CAP = 0.25        # 25% per-name cap


# ── Discord ──────────────────────────────────────────────────────────────────

def send_discord_text(text: str):
    if not DISCORD_WEBHOOK_URL:
        print(f"  [no webhook] {text[:120]}...")
        return
    # Discord 2000 char limit — split on blank lines
    chunks = []
    cur = ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 1900:
            chunks.append(cur)
            cur = line
        else:
            cur = cur + "\n" + line if cur else line
    if cur:
        chunks.append(cur)
    for ch in chunks:
        try:
            r = requests.post(DISCORD_WEBHOOK_URL, json={"content": ch}, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"  Discord text failed: {e}")


def send_discord_image(buf: io.BytesIO, filename: str):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        r = requests.post(
            DISCORD_WEBHOOK_URL,
            files={"file": (filename, buf, "image/png")},
            timeout=30,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"  Discord image failed: {e}")


# ── Data Fetch ───────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame | None:
    yticker = ticker.replace(".", "-")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yticker}"
        f"?range={period}&interval={interval}"
    )
    try:
        r = requests.get(url, headers=YAHOO_HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        ts = result[0].get("timestamp")
        if not ts:
            return None
        q = result[0]["indicators"]["quote"][0]
        df = pd.DataFrame({
            "Open": q.get("open"),
            "High": q.get("high"),
            "Low": q.get("low"),
            "Close": q.get("close"),
            "Volume": q.get("volume"),
        }, index=pd.to_datetime(ts, unit="s", utc=True))
        df.index = df.index.tz_convert("America/New_York")
        df = df.dropna(subset=["Close"])
        if len(df) < 50:
            return None
        return df
    except Exception:
        return None


def batch_fetch(tickers: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    out = {}
    bsize = 40
    for i in range(0, len(tickers), bsize):
        batch = tickers[i:i + bsize]
        if i > 0:
            time.sleep(2)
        with ThreadPoolExecutor(max_workers=5) as pool:
            fut = {pool.submit(fetch_ohlcv, t, period): t for t in batch}
            for f in as_completed(fut):
                t = fut[f]
                try:
                    df = f.result()
                    if df is not None:
                        out[t] = df
                except Exception:
                    pass
    return out


# ── Indicators ───────────────────────────────────────────────────────────────

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = atr(df, n)
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / tr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / tr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def annualized_vol(close: pd.Series, n: int = 60) -> float:
    r = close.pct_change().dropna().tail(n)
    if len(r) < 20:
        return np.nan
    return float(r.std() * np.sqrt(252))


# ── Regime Gate ──────────────────────────────────────────────────────────────

def compute_regime(spy: pd.DataFrame, vix: pd.DataFrame, sector_etfs: dict[str, pd.DataFrame]) -> dict:
    """Approximate breadth + vol regime gate without depending on other scripts."""
    # Vol regime from VIX level
    vix_level = float(vix["Close"].iloc[-1])
    vix_1y = vix["Close"].tail(252)
    vix_pct = float((vix_1y <= vix_level).mean() * 100)
    if vix_level >= 30 or vix_pct >= 90:
        vol_regime = "EXTREME"
    elif vix_level >= 22 or vix_pct >= 75:
        vol_regime = "ELEVATED"
    elif vix_level <= 14 or vix_pct <= 15:
        vol_regime = "LOW"
    else:
        vol_regime = "NORMAL"

    # Breadth proxy: % of 11 CW sector ETFs above their SMA50 and SMA200
    above_50 = 0
    above_200 = 0
    n = 0
    for t, df in sector_etfs.items():
        if df is None or len(df) < 200:
            continue
        n += 1
        c = df["Close"]
        if c.iloc[-1] > sma(c, 50).iloc[-1]:
            above_50 += 1
        if c.iloc[-1] > sma(c, 200).iloc[-1]:
            above_200 += 1
    pct50 = 100 * above_50 / n if n else 0
    pct200 = 100 * above_200 / n if n else 0
    score = 0.5 * pct50 / 100 + 0.5 * pct200 / 100
    if score >= 0.70:
        breadth = "STRONG"
    elif score >= 0.50:
        breadth = "HEALTHY"
    elif score >= 0.30:
        breadth = "MIXED"
    else:
        breadth = "WEAK"

    gate_open = breadth in {"STRONG", "HEALTHY"} and vol_regime in {"LOW", "NORMAL"}
    return {
        "vix_level": vix_level, "vix_pct": vix_pct, "vol_regime": vol_regime,
        "pct_above_50": pct50, "pct_above_200": pct200, "breadth": breadth,
        "gate_open": gate_open,
    }


# ── Stage 1: Bubble Qualifier ────────────────────────────────────────────────

def qualify_bubble(df: pd.DataFrame, regime: dict) -> dict:
    """Evaluate 4 bubble conditions on a single ETF's daily data."""
    c = df["Close"]
    if len(c) < 260:
        return {"classification": "REJECT", "reason": "insufficient_data"}

    # C1: 12-month total return
    ret_1y = float(c.iloc[-1] / c.iloc[-252] - 1)
    c1 = ret_1y > 1.0

    # C2: price stretch from 200-day SMA in σ
    s200 = sma(c, 200)
    devs = ((c - s200) / s200).dropna().tail(252)
    if len(devs) < 60:
        return {"classification": "REJECT", "reason": "insufficient_data"}
    sigma = float(devs.std())
    cur_dev = float((c.iloc[-1] - s200.iloc[-1]) / s200.iloc[-1])
    stretch = cur_dev / sigma if sigma > 0 else 0
    c2 = stretch > 2.0

    # C3: accelerating momentum
    ret_3m = float(c.iloc[-1] / c.iloc[-63] - 1)
    ret_3m_ann = (1 + ret_3m) ** 4 - 1
    c3 = ret_3m_ann > ret_1y

    # C4: regime gate
    c4 = regime["gate_open"]

    met = sum([c1, c2, c3, c4])
    # C1 (12-month total return > +100%) alone is sufficient for FULL BUBBLE.
    if c1:
        cls = "FULL BUBBLE"
    elif met == 3:
        cls = "EMERGING"
    elif met == 2:
        cls = "WATCHLIST"
    else:
        cls = "REJECT"

    return {
        "classification": cls,
        "c1": c1, "c2": c2, "c3": c3, "c4": c4, "met": met,
        "ret_1y": ret_1y, "stretch": stretch,
        "ret_3m_ann": ret_3m_ann,
    }


# ── Stage 3: Entry Detection ─────────────────────────────────────────────────

def detect_entries(stock: pd.DataFrame, parent_etf: pd.DataFrame, parent_bubble_days: int) -> list[dict]:
    """Return list of entry signals (A/B/C/D) firing today for this stock."""
    signals = []
    if stock is None or len(stock) < 220:
        return signals
    c = stock["Close"]
    v = stock["Volume"]
    h = stock["High"]
    l = stock["Low"]

    ema21 = ema(c, 21)
    s50 = sma(c, 50)
    s200 = sma(c, 200)
    r14 = rsi(c, 14)
    adx14 = adx(stock, 14)
    vol_avg20 = v.rolling(20).mean()
    atr14 = atr(stock, 14)

    last = -1
    px = float(c.iloc[last])

    # RS line vs parent ETF (aligned)
    if parent_etf is not None and len(parent_etf) >= 252:
        joined = pd.concat([c, parent_etf["Close"]], axis=1, join="inner").dropna()
        joined.columns = ["s", "b"]
        rs_line = joined["s"] / joined["b"]
    else:
        rs_line = None

    # Entry A — Tight-Flag Breakout (5–10 day base, bubble-pace continuation)
    if parent_bubble_days >= 3 and len(c) >= 15:
        cur_atr = float(atr14.iloc[last])
        a_fired = False
        for base_len in (5, 7, 10):
            base_h = h.iloc[-(base_len + 1):-1]
            base_l = l.iloc[-(base_len + 1):-1]
            base_high = float(base_h.max())
            base_low = float(base_l.min())
            base_range = base_high - base_low
            cond_tight = base_range < 2.5 * cur_atr
            cond_break = px > base_high
            cond_vol = float(v.iloc[last]) > 1.5 * float(vol_avg20.iloc[last])
            cond_adx = float(adx14.iloc[last]) > 25 if not np.isnan(adx14.iloc[last]) else False
            cond_rs = False
            if rs_line is not None and len(rs_line) >= 60:
                cond_rs = rs_line.iloc[-1] >= rs_line.tail(60).max() * 0.999
            if cond_tight and cond_break and cond_vol and cond_adx and cond_rs:
                signals.append({"type": "A", "name": f"Tight-Flag Breakout ({base_len}d)",
                                "detail": f"base ${base_low:.2f}-${base_high:.2f} ({base_range/cur_atr:.1f}×ATR), break>{base_high:.2f}, vol={v.iloc[last]/vol_avg20.iloc[last]:.1f}×, ADX={adx14.iloc[last]:.0f}"})
                a_fired = True
                break  # one A signal is enough

    # Entry B — Boring Pullback (widened: within 1×ATR of EMA21/SMA50 for bubble-pace names)
    if (px > s50.iloc[last] * 0.95 and s50.iloc[last] > s200.iloc[last]
            and s50.iloc[last] > s50.iloc[-10] and s200.iloc[last] > s200.iloc[-10]):
        cur_atr_b = float(atr14.iloc[last])
        near_ema21 = abs(px - ema21.iloc[last]) < cur_atr_b
        near_s50 = (abs(px - s50.iloc[last]) < cur_atr_b
                    and c.iloc[-10:].max() > s50.iloc[last] + cur_atr_b)
        respected = (c.iloc[-10:] >= np.minimum(ema21.iloc[-10:], s50.iloc[-10:]) * 0.99).all()
        rsi_cur = float(r14.iloc[last])
        rsi_prior_hot = (r14.iloc[-20:-3] > 65).any()
        cool = 40 <= rsi_cur <= 55 and rsi_prior_hot
        # bullish reversal candle today
        body = c.iloc[last] - stock["Open"].iloc[last]
        lower_wick = min(stock["Open"].iloc[last], c.iloc[last]) - l.iloc[last]
        hammer = (body > 0 and lower_wick > 1.5 * abs(body))
        engulfing = (c.iloc[last] > stock["Open"].iloc[last]
                     and c.iloc[-2] < stock["Open"].iloc[-2]
                     and c.iloc[last] > stock["Open"].iloc[-2]
                     and stock["Open"].iloc[last] < c.iloc[-2])
        reversal = hammer or engulfing
        vol_ok = float(v.iloc[last]) > float(vol_avg20.iloc[last])
        if (near_ema21 or near_s50) and respected and cool and reversal and vol_ok:
            ma_label = "EMA21" if near_ema21 else "SMA50"
            signals.append({"type": "B", "name": "Boring Pullback",
                            "detail": f"pullback to {ma_label}, RSI={rsi_cur:.0f}, reversal candle"})

    # Entry C — Failed Breakdown / Spring
    if len(c) >= 30:
        sup = min(c.iloc[-30:-3].min(), ema21.iloc[last])
        # in last 2 sessions price dipped below sup intraday and closed back above
        recent_break = False
        for k in range(-3, 0):
            if l.iloc[k] < sup and c.iloc[k] > sup:
                recent_break = True
                break_idx = k
        rsi_now = float(r14.iloc[last])
        rsi_min3 = float(r14.iloc[-3:].min())
        rebounded = rsi_min3 < 40 and rsi_now > 50
        vol_ok = float(v.iloc[last]) > 1.5 * float(vol_avg20.iloc[last])
        if recent_break and rebounded and vol_ok:
            signals.append({"type": "C", "name": "Failed Breakdown",
                            "detail": f"spring below {sup:.2f}, RSI {rsi_min3:.0f}→{rsi_now:.0f}, vol {v.iloc[last]/vol_avg20.iloc[last]:.1f}x"})

    # Entry D — RS Leadership Confirmation
    if parent_bubble_days >= 3 and rs_line is not None and len(rs_line) >= 182:
        ret_13w = float(c.iloc[last] / c.iloc[-65] - 1) if len(c) >= 65 else None
        rs_26w = float(rs_line.iloc[-1] / rs_line.iloc[-130] - 1) if len(rs_line) >= 130 else None
        above_all = (px > ema21.iloc[last] and px > s50.iloc[last] and px > s200.iloc[last])
        # weekly RSI: resample
        wk = c.resample("W").last().dropna()
        wkrsi = rsi(wk, 14)
        wkrsi_now = float(wkrsi.iloc[-1])
        wkrsi_rising = wkrsi.iloc[-1] > wkrsi.iloc[-2]
        # 10-week MA
        wkma10 = wk.rolling(10).mean()
        adx_ok = float(adx14.iloc[last]) > 25 if not np.isnan(adx14.iloc[last]) else False
        if (ret_13w is not None and rs_26w is not None and rs_26w > 0
                and above_all and wkrsi_now > 55 and wkrsi_rising
                and wk.iloc[-1] > wkma10.iloc[-1] and adx_ok):
            signals.append({"type": "D", "name": "RS Leadership",
                            "detail": f"13w={ret_13w*100:+.0f}%, RS26w={rs_26w*100:+.0f}%, wkRSI={wkrsi_now:.0f}"})

    # Entry E — Inside-Day / NR7 Breakout (micro-coil continuation for bubble names)
    if len(c) >= 8 and px > s50.iloc[last] and s50.iloc[last] > s200.iloc[last]:
        prior_h = float(h.iloc[-2])
        prior_l = float(l.iloc[-2])
        # Inside day: prior session's range contained within session before that
        inside_day = prior_h < float(h.iloc[-3]) and prior_l > float(l.iloc[-3])
        # NR7: prior session has smallest range of last 7
        recent_ranges = (h - l).iloc[-8:-1]
        nr7 = float(recent_ranges.iloc[-1]) == float(recent_ranges.min())
        cond_break = px > prior_h
        cond_vol = float(v.iloc[last]) > 1.2 * float(vol_avg20.iloc[last])
        if (inside_day or nr7) and cond_break and cond_vol:
            pattern = "Inside-Day" if inside_day else "NR7"
            prev_close = float(c.iloc[-2])
            day_gain = (px / prev_close - 1) * 100
            signals.append({"type": "E", "name": f"{pattern} Breakout",
                            "detail": f"px ${px:.2f} ({day_gain:+.1f}% vs prev ${prev_close:.2f}), break>{prior_h:.2f}, vol={v.iloc[last]/vol_avg20.iloc[last]:.1f}×"})

    # Entry F — Reclaim of Key MA (recovery-rally catcher)
    # Price closes back above SMA50 after being below for >= 8 sessions.
    # Volume only needs to be ≥ average (the reclaim itself is the signal).
    if len(c) >= 60:
        below_10 = (c.iloc[-11:-1] < s50.iloc[-11:-1]).sum()
        reclaim = c.iloc[last] > s50.iloc[last] and c.iloc[-2] < s50.iloc[-2]
        cond_vol_f = float(v.iloc[last]) >= float(vol_avg20.iloc[last])
        cond_above_200 = c.iloc[last] > s200.iloc[last]  # still in a long-term uptrend
        if below_10 >= 8 and reclaim and cond_above_200:
            vol_note = "vol confirmed" if cond_vol_f else "light vol"
            signals.append({"type": "F", "name": "SMA50 Reclaim",
                            "detail": f"reclaimed ${s50.iloc[last]:.2f} after {int(below_10)}/10d below, vol={v.iloc[last]/vol_avg20.iloc[last]:.1f}× ({vol_note})"})

    # Entry G — Higher-Low + Higher-High (generic trend resumption)
    # Last swing low > prior swing low AND today closes above the most recent swing high
    try:
        from scipy.signal import argrelextrema
        # local minima/maxima with window 5
        if len(c) >= 60:
            close_arr = c.values
            lows_idx = argrelextrema(close_arr, np.less, order=5)[0]
            highs_idx = argrelextrema(close_arr, np.greater, order=5)[0]
            # recent points (within last 40 sessions)
            recent_lows = [i for i in lows_idx if i >= len(c) - 40]
            recent_highs = [i for i in highs_idx if i >= len(c) - 40]
            if len(recent_lows) >= 2 and len(recent_highs) >= 1:
                last_low_val = close_arr[recent_lows[-1]]
                prior_low_val = close_arr[recent_lows[-2]]
                last_high_val = close_arr[recent_highs[-1]]
                higher_low = last_low_val > prior_low_val * 1.005
                # higher high = today closes above the most recent swing high (which formed before last_low)
                higher_high = (px > last_high_val
                               and recent_highs[-1] < recent_lows[-1])
                cond_vol_g = float(v.iloc[last]) > float(vol_avg20.iloc[last])
                cond_above_50 = px > s50.iloc[last]
                if higher_low and higher_high and cond_vol_g and cond_above_50:
                    signals.append({"type": "G", "name": "Higher-Low/Higher-High",
                                    "detail": f"prior low ${prior_low_val:.2f} → ${last_low_val:.2f}, break>${last_high_val:.2f}, vol={v.iloc[last]/vol_avg20.iloc[last]:.1f}×"})
    except ImportError:
        pass

    return signals


# ── Stage 4: Exit Ladder ─────────────────────────────────────────────────────

def detect_exits(stock: pd.DataFrame) -> dict:
    """Detect Flashing/Solid Yellow, Orange, Red triggers for a position."""
    if stock is None or len(stock) < 220:
        return {"tier": None, "triggers": []}
    c = stock["Close"]
    v = stock["Volume"]
    h = stock["High"]
    l = stock["Low"]
    o = stock["Open"]

    ema21 = ema(c, 21)
    s50 = sma(c, 50)
    s10wk = c.resample("W").last().rolling(10).mean()
    r14 = rsi(c, 14)
    atr14 = atr(stock, 14)
    vol20 = v.rolling(20).mean()

    yellow = []  # flashing yellow triggers
    orange = []
    red = []

    # Flashing Yellow checks
    wk = c.resample("W").last()
    wkrsi = rsi(wk, 14)
    if len(wkrsi) >= 5:
        peak_idx = wkrsi.tail(20).idxmax() if not wkrsi.tail(20).empty else None
        if peak_idx is not None and float(wkrsi.loc[peak_idx]) > 70:
            # 2 consecutive weekly RSI declines after peak
            after = wkrsi.loc[peak_idx:]
            if len(after) >= 3 and after.iloc[-1] < after.iloc[-2] < after.iloc[-3]:
                yellow.append(f"Weekly RSI peaked {float(wkrsi.loc[peak_idx]):.0f}, declining 2wks")

    # ROC compare
    if len(c) >= 25:
        roc5 = c.pct_change(5)
        roc20 = c.pct_change(20)
        if (roc5.iloc[-3:] < roc20.iloc[-3:]).all():
            yellow.append("5d ROC < 20d ROC for 3 sessions")

    # Distance from 21EMA percentile
    if len(c) >= 252:
        dist = ((c - ema21) / ema21).tail(252)
        cur = dist.iloc[-1]
        pct = (dist <= cur).mean() * 100
        if pct >= 95:
            yellow.append(f"Distance from 21EMA at {pct:.0f}th pctile")

    # Parabolic warning
    if len(c) >= 20:
        rng = (h - l).tail(20)
        wide = (rng > 2 * atr14.tail(20)).sum()
        if wide >= 5:
            yellow.append(f"Parabolic: {wide} sessions w/ range>2×ATR in last 20")

    # Orange
    # Bearish weekly RSI divergence — but only if price isn't actively making a
    # new 20-day high (in a parabolic move RSI gets pinned and this fires daily)
    if len(wk) >= 9 and len(wkrsi) >= 9:
        recent_high_idx = wk.tail(8).idxmax()
        if recent_high_idx == wk.index[-1]:
            prior_max = wk.iloc[-9:-1].max()
            if wk.iloc[-1] > prior_max:
                prior_rsi_max = wkrsi.iloc[-9:-1].max()
                making_new_daily_high = (len(c) >= 20 and c.iloc[-1] >= c.iloc[-20:].max())
                if wkrsi.iloc[-1] < prior_rsi_max and not making_new_daily_high:
                    orange.append(f"Bearish weekly RSI divergence")

    if c.iloc[-1] < ema21.iloc[-1]:
        orange.append("Daily close below 21EMA")

    # up/down volume ratio
    if len(c) >= 11:
        ret = c.pct_change()
        up_v = v.where(ret > 0, 0).tail(10).sum()
        dn_v = v.where(ret < 0, 0).tail(10).sum()
        ratio = up_v / dn_v if dn_v > 0 else np.inf
        if ratio < 0.8:
            orange.append(f"Up/Down vol ratio 10d = {ratio:.2f}")

    # 2σ down day on high vol
    if len(c) >= 30:
        ret = c.pct_change()
        std = ret.tail(60).std()
        if ret.iloc[-1] < -2 * std and v.iloc[-1] > 2 * vol20.iloc[-1]:
            orange.append(f"2σ down day on {v.iloc[-1]/vol20.iloc[-1]:.1f}× volume")

    # Red triggers
    if len(c) >= 11:
        pivot_low_10 = l.iloc[-11:-1].min()
        if c.iloc[-1] < pivot_low_10:
            red.append(f"Close below 10d pivot low {pivot_low_10:.2f}")

    if len(s10wk.dropna()) >= 2 and not np.isnan(s10wk.iloc[-1]):
        if wk.iloc[-1] < s10wk.iloc[-1]:
            red.append("Weekly close below 10wk MA")

    # 3 lower highs after parabolic
    if len(h) >= 25:
        # parabolic = 5 wide-range days in last 25
        wide25 = ((h - l).tail(25) > 2 * atr14.tail(25)).sum()
        recent_hh = h.tail(6)
        if wide25 >= 5 and (recent_hh.diff().tail(3) < 0).all():
            red.append("3 lower highs after parabolic phase")

    # Gap below 50SMA on volume
    if len(c) >= 2:
        if o.iloc[-1] < s50.iloc[-1] and c.iloc[-2] > s50.iloc[-2] and v.iloc[-1] > 1.5 * vol20.iloc[-1]:
            red.append(f"Gap below 50SMA on {v.iloc[-1]/vol20.iloc[-1]:.1f}× volume")

    # Resolve tier
    tier = None
    triggers = []
    if red:
        tier = "RED"
        triggers = red
    elif orange:
        tier = "ORANGE"
        triggers = orange
    elif len(yellow) >= 2:
        tier = "SOLID YELLOW"
        triggers = yellow
    elif len(yellow) == 1:
        tier = "FLASHING YELLOW"
        triggers = yellow
    return {"tier": tier, "triggers": triggers}


# ── Stage 5: Position Sizing ─────────────────────────────────────────────────

def vol_adjusted_size(stock: pd.DataFrame, classification: str) -> float | None:
    if stock is None:
        return None
    avol = annualized_vol(stock["Close"], 60)
    if not np.isfinite(avol) or avol <= 0:
        return None
    base = BASE_SIZE_FULL if classification == "FULL BUBBLE" else BASE_SIZE_EMERGING
    size = base * (TARGET_VOL / avol)
    return min(size, PER_NAME_CAP)


# ── Output Building ──────────────────────────────────────────────────────────

def fmt_flags(q: dict) -> str:
    return f"[C1{'✓' if q.get('c1') else '✗'} C2{'✓' if q.get('c2') else '✗'} C3{'✓' if q.get('c3') else '✗'} C4{'✓' if q.get('c4') else '✗'}]"


def bubble_days(df: pd.DataFrame, regime: dict, lookback: int = 60) -> int:
    """Count recent days where ETF would have classified as FULL BUBBLE.
    Under current rule, C1 (1Y > +100%) alone is sufficient."""
    c = df["Close"]
    if len(c) < 260:
        return 0
    count = 0
    for k in range(-min(lookback, len(c) - 252), 0):
        if k - 252 < -len(c):
            continue
        ret1y = c.iloc[k] / c.iloc[k - 252] - 1
        if ret1y > 1.0:
            count += 1
    return count


def main():
    now = datetime.now(ET)
    print(f"{now.strftime('%Y-%m-%d %H:%M:%S')} bubble-scanner starting")

    # Load ETFs + watchlist
    with open(TOOLS_DIR / "etf-holdings.json") as f:
        holdings = json.load(f)
    etfs = [k for k in holdings if not k.startswith("_")]
    print(f"  Loaded {len(etfs)} ETFs")

    watchlist = []
    try:
        with open(TOOLS_DIR / "watchlist.json") as f:
            wl = json.load(f)
        watchlist = wl.get("tickers", [])
    except Exception:
        pass

    # Fetch ETFs + SPY + VIX
    print("  Fetching ETF + benchmark data (2y daily)...")
    universe = list(set(etfs + ["SPY", "^VIX"]))
    etf_data = batch_fetch(universe, period="2y")
    spy = etf_data.get("SPY")
    vix = etf_data.get("^VIX")
    if spy is None or vix is None:
        print("FATAL: missing SPY or VIX", file=sys.stderr)
        sys.exit(1)

    # CW sector ETFs for breadth proxy
    CW_SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLC", "XLB", "XLRE"]
    sector_data = {t: etf_data[t] for t in CW_SECTORS if t in etf_data}
    regime = compute_regime(spy, vix, sector_data)
    print(f"  Regime: vol={regime['vol_regime']} (VIX {regime['vix_level']:.1f}), breadth={regime['breadth']}, gate={'OPEN' if regime['gate_open'] else 'CLOSED'}")

    # Stage 1: classify each ETF
    qualified = {}
    for t in etfs:
        df = etf_data.get(t)
        if df is None:
            continue
        q = qualify_bubble(df, regime)
        q["sector_name"] = holdings[t].get("name", "")
        q["parent_sector"] = holdings[t].get("sector", "")
        qualified[t] = q

    full = {t: q for t, q in qualified.items() if q["classification"] == "FULL BUBBLE"}
    emerging = {t: q for t, q in qualified.items() if q["classification"] == "EMERGING"}
    watchlist_cls = {t: q for t, q in qualified.items() if q["classification"] == "WATCHLIST"}
    print(f"  FULL={len(full)} EMERGING={len(emerging)} WATCHLIST={len(watchlist_cls)}")

    # Stage 2: tradeable universe per bubble theme
    tradeable: dict[str, list[str]] = {}
    for t in list(full) + list(emerging):
        stock_pool = list(holdings[t].get("holdings", []))
        inter = [s for s in stock_pool if s in watchlist]
        chosen = inter if inter else stock_pool
        # always include the ETF itself
        tradeable[t] = list(dict.fromkeys(chosen + [t]))

    # Fetch stock-level data for tradeable universe
    all_stocks = sorted({s for v in tradeable.values() for s in v} - set(etf_data))
    if all_stocks:
        print(f"  Fetching {len(all_stocks)} tradeable constituents...")
        stock_data = batch_fetch(all_stocks, period="2y")
    else:
        stock_data = {}
    # merge
    def get_df(t):
        return etf_data.get(t) or stock_data.get(t)

    # Stage 3 + 4 + 5: per stock
    entry_rows = []   # (etf, ticker, entries[], size)
    exit_rows = []    # (etf, ticker, tier, triggers)
    for etf, stocks in tradeable.items():
        parent_df = etf_data.get(etf)
        pbd = bubble_days(parent_df, regime, lookback=60) if parent_df is not None else 0
        cls = qualified[etf]["classification"]
        for s in stocks:
            sdf = get_df(s)
            if sdf is None:
                continue
            entries = detect_entries(sdf, parent_df, pbd)
            if entries:
                size = vol_adjusted_size(sdf, cls)
                entry_rows.append((etf, s, entries, size))
            exits = detect_exits(sdf)
            if exits["tier"]:
                exit_rows.append((etf, s, exits["tier"], exits["triggers"]))

    # ── Compose Discord post ────────────────────────────────────────────────
    lines = []
    lines.append("══════════════════════════════════════════")
    lines.append(f"BUBBLE SCANNER — {now.strftime('%Y-%m-%d %H:%M ET')}")
    lines.append("══════════════════════════════════════════")
    gate = "🟢 GATE OPEN" if regime["gate_open"] else "🔴 GATE CLOSED"
    lines.append(f"{gate}  Breadth: {regime['breadth']} ({regime['pct_above_50']:.0f}% >50MA, {regime['pct_above_200']:.0f}% >200MA)")
    lines.append(f"            Vol: {regime['vol_regime']}  VIX={regime['vix_level']:.1f} ({regime['vix_pct']:.0f}th pctile)")
    lines.append("")

    def fmt_etf_line(t, q):
        return (f"{t:<6} {fmt_flags(q)}  1Y={q['ret_1y']*100:+.0f}%  "
                f"stretch={q['stretch']:.1f}σ  3M_ann={q['ret_3m_ann']*100:+.0f}%")

    if full:
        lines.append("── FULL BUBBLES (4/4) ──")
        for t, q in sorted(full.items(), key=lambda kv: -kv[1]["ret_1y"]):
            lines.append(fmt_etf_line(t, q) + f"  — {q['sector_name']}")
        lines.append("")

    if emerging:
        lines.append("── EMERGING (3/4) ──")
        for t, q in sorted(emerging.items(), key=lambda kv: -kv[1]["ret_1y"]):
            missing = []
            if not q["c1"]: missing.append("1Y<+100%")
            if not q["c2"]: missing.append("stretch<2σ")
            if not q["c3"]: missing.append("not accel")
            if not q["c4"]: missing.append("regime")
            lines.append(fmt_etf_line(t, q) + f"  (missing: {','.join(missing)})")
        lines.append("")

    if watchlist_cls:
        lines.append("── WATCHLIST (2/4) ──")
        names = " ".join(f"{t}{fmt_flags(q)}" for t, q in sorted(watchlist_cls.items(), key=lambda kv: -kv[1]["ret_1y"]))
        lines.append(names)
        lines.append("")

    # Entry signals
    if entry_rows:
        lines.append("── ENTRY SIGNALS TODAY ──")
        for etf, s, sigs, size in entry_rows:
            types = "/".join(x["type"] for x in sigs)
            size_str = f"size={size*100:.1f}%" if size else "size=n/a"
            lines.append(f"  {s:<6} ({etf}) [{types}]  {size_str}")
            for x in sigs:
                lines.append(f"    {x['type']} {x['name']}: {x['detail']}")
        lines.append("")
    else:
        lines.append("── ENTRY SIGNALS TODAY ──  (none)")
        lines.append("")

    # Exit signals
    if exit_rows:
        # Order tier severity
        tier_rank = {"RED": 0, "ORANGE": 1, "SOLID YELLOW": 2, "FLASHING YELLOW": 3}
        exit_rows.sort(key=lambda r: tier_rank.get(r[2], 9))
        lines.append("── EXIT SIGNALS TODAY ──")
        for etf, s, tier, trigs in exit_rows:
            icon = {"RED": "🔴", "ORANGE": "🟠", "SOLID YELLOW": "🟡", "FLASHING YELLOW": "🟨"}.get(tier, "")
            lines.append(f"  {icon} {s:<6} ({etf}) {tier}")
            for tr in trigs[:3]:
                lines.append(f"      • {tr}")
        lines.append("")
    else:
        lines.append("── EXIT SIGNALS TODAY ──  (none)")
        lines.append("")

    lines.append("Ride → De-risk → exit on break. Don't fade early.")
    text = "\n".join(lines)
    print("\n" + text + "\n")
    send_discord_text("```\n" + text + "\n```")
    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} bubble-scanner complete")


if __name__ == "__main__":
    main()
