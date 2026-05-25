"""
Entry Analyzer — Multi-Timeframe Entry Candidate Scoring

Run on a list of tickers you're considering buying. Produces per-ticker:
  - Daily / Weekly / Monthly trend classification
  - 30-week SMA position (Minervini Stage 2 check)
  - Volume analysis (rel vol, up/down ratio, CMF)
  - Fibonacci retracement levels (daily + weekly swings)
  - Best AVWAP picked from 5 anchor candidates
  - Pullback quality (reuses trade-setup Module 8)
  - Composite Entry Score (0-100) and classification
  - Concrete entry plan: entry zone, stop, T1/T2/T3, R/R
  - 3-panel chart: daily / weekly / monthly with all overlays

Inputs (in priority order):
  1. CLI args:     python entry-analyzer.py FIVN BB AMRC GTLB BLDP SHLS
  2. JSON file:    entry-candidates.json with {"tickers": [...]}
  3. Interactive:  prompt for comma-separated tickers

For pre-entry decisions on candidates you do NOT yet own. See pyramid-scanner.py
for adding to existing positions.
"""

import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import json
import argparse
import importlib.util
import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent
INPUT_JSON = TOOLS_DIR / "entry-candidates.json"

DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1505424654259458159/"
    "Q1JLLuLETKzh1KhSHqzWYS0HZP1uZjNb5zxFpHfwLTAVBTX7RFQ5RHsr4pNqdgYGMM-g"
)


# ── Load helper modules (filenames have hyphens) ─────────────────────────────

def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bs = _load("bubble_scanner", TOOLS_DIR / "bubble-scanner.py")
ts = _load("trade_setup", TOOLS_DIR / "trade-setup.py")


# ── Discord ──────────────────────────────────────────────────────────────────

def send_discord_text(text: str):
    if not DISCORD_WEBHOOK_URL:
        return
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 1900:
            chunks.append(cur); cur = line
        else:
            cur = cur + "\n" + line if cur else line
    if cur:
        chunks.append(cur)
    for ch in chunks:
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": ch}, timeout=30).raise_for_status()
        except Exception as e:
            print(f"  Discord text failed: {e}", file=sys.stderr)


def send_discord_image(buf: io.BytesIO, filename: str):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL,
                      files={"file": (filename, buf, "image/png")},
                      timeout=30).raise_for_status()
    except Exception as e:
        print(f"  Discord image failed: {e}", file=sys.stderr)


# ── Ticker Input ─────────────────────────────────────────────────────────────

def load_tickers(cli_args: list[str]) -> list[str]:
    if cli_args:
        return [t.strip().upper() for t in cli_args if t.strip()]
    if INPUT_JSON.exists():
        with open(INPUT_JSON) as f:
            data = json.load(f)
        return [t.upper() for t in data.get("tickers", [])]
    try:
        raw = input("Enter tickers (comma-separated): ")
    except EOFError:
        return []
    return [t.strip().upper() for t in raw.replace(",", " ").split() if t.strip()]


# ── Module 1: Multi-Timeframe SMA Stack ──────────────────────────────────────

def daily_trend(daily: pd.DataFrame) -> dict:
    c = daily["Close"]
    e21 = bs.ema(c, 21).iloc[-1]
    s20 = bs.sma(c, 20).iloc[-1]
    s50 = bs.sma(c, 50).iloc[-1]
    s200 = bs.sma(c, 200).iloc[-1] if len(c) >= 200 else np.nan
    px = float(c.iloc[-1])
    mas = {"EMA21": e21, "SMA20": s20, "SMA50": s50, "SMA200": s200}
    above = {k: px > v for k, v in mas.items() if not np.isnan(v)}
    above_count = sum(above.values())
    total = len(above)
    if above_count == total and not np.isnan(s200) and s50 > s200:
        label = "UPTREND"
    elif above_count >= total * 0.5:
        label = "PARTIAL_UP"
    elif not np.isnan(s200) and px < s200:
        label = "DOWN"
    else:
        label = "MIXED"
    return {"label": label, "mas": mas, "above": above, "price": px}


def weekly_trend(weekly: pd.DataFrame) -> dict:
    if weekly is None or len(weekly) < 40:
        return {"label": "INSUFFICIENT", "mas": {}, "above": {}, "price": None}
    c = weekly["Close"]
    s10 = bs.sma(c, 10).iloc[-1]
    s20 = bs.sma(c, 20).iloc[-1]
    s40 = bs.sma(c, 40).iloc[-1]
    px = float(c.iloc[-1])
    mas = {"SMA10wk": s10, "SMA20wk": s20, "SMA40wk": s40}
    above = {k: px > v for k, v in mas.items() if not np.isnan(v)}
    above_count = sum(above.values())
    if above_count == 3 and s10 > s40:
        label = "UPTREND"
    elif above_count >= 2:
        label = "PARTIAL_UP"
    elif above_count == 0:
        label = "DOWN"
    else:
        label = "MIXED"
    return {"label": label, "mas": mas, "above": above, "price": px}


def monthly_trend(monthly: pd.DataFrame) -> dict:
    if monthly is None or len(monthly) < 13:
        return {"label": "INSUFFICIENT", "mas": {}, "above": {}, "price": None}
    c = monthly["Close"]
    s6 = bs.sma(c, 6).iloc[-1]
    s12 = bs.sma(c, 12).iloc[-1]
    px = float(c.iloc[-1])
    mas = {"SMA6mo": s6, "SMA12mo": s12}
    above = {k: px > v for k, v in mas.items() if not np.isnan(v)}
    above_count = sum(above.values())
    if above_count == 2 and s6 > s12:
        label = "UPTREND"
    elif above_count == 1:
        label = "PARTIAL_UP"
    elif above_count == 0:
        label = "DOWN"
    else:
        label = "MIXED"
    return {"label": label, "mas": mas, "above": above, "price": px}


# ── Module 2: 30-Week SMA (Minervini Stage 2) ────────────────────────────────

def thirty_week_sma(daily: pd.DataFrame) -> dict:
    c = daily["Close"]
    if len(c) < 150:
        return {"valid": False, "reason": "insufficient data (need 150 days)"}
    s = bs.sma(c, 150)  # 30 trading weeks = 150 sessions
    cur_sma = float(s.iloc[-1])
    px = float(c.iloc[-1])
    # Slope over last 20 sessions (≈ 4 weeks)
    slope = (s.iloc[-1] - s.iloc[-21]) / 21 if len(s) >= 21 else 0
    pct_slope = (slope / cur_sma) * 100 if cur_sma > 0 else 0
    rising = slope > 0
    rising_4wk = (s.iloc[-1] > s.iloc[-21]) if len(s) >= 21 else False
    distance_pct = (px - cur_sma) / cur_sma * 100
    return {
        "valid": True, "sma": cur_sma, "series": s,
        "price_above": px > cur_sma, "distance_pct": distance_pct,
        "rising": rising, "rising_4wk": rising_4wk, "pct_slope_per_day": pct_slope,
    }


# ── Module 3: Volume Analysis ────────────────────────────────────────────────

def volume_analysis(daily: pd.DataFrame) -> dict:
    v = daily["Volume"]
    c = daily["Close"]
    h = daily["High"]
    l = daily["Low"]
    avg20 = float(v.rolling(20).mean().iloc[-1])
    today = float(v.iloc[-1])
    rel = today / avg20 if avg20 > 0 else 0
    low_liq = avg20 < 100_000

    # Up/down volume ratio over last 20 sessions
    ret = c.pct_change()
    up_v = v.where(ret > 0, 0).tail(20).sum()
    dn_v = v.where(ret < 0, 0).tail(20).sum()
    ud_ratio = (up_v / dn_v) if dn_v > 0 else float("inf") if up_v > 0 else 1.0

    # Volume slope (10-day linear regression)
    last10 = v.tail(10).values
    if len(last10) >= 10:
        x = np.arange(10)
        slope, _ = np.polyfit(x, last10, 1)
        slope_pct = (slope * 10 / avg20) * 100 if avg20 > 0 else 0
    else:
        slope_pct = 0

    # Chaikin Money Flow (20)
    mfm = ((c - l) - (h - c)) / (h - l).replace(0, np.nan)
    mfv = mfm * v
    cmf = float(mfv.tail(20).sum() / v.tail(20).sum()) if v.tail(20).sum() > 0 else 0

    return {
        "avg_20d": avg20, "today": today, "rel_today": rel,
        "up_down_ratio_20d": float(ud_ratio) if np.isfinite(ud_ratio) else 99.0,
        "vol_slope_10d_pct": slope_pct, "cmf_20": cmf, "low_liquidity": low_liq,
    }


# ── Module 4: Fibonacci based on the LATEST SWING ───────────────────────────
# Use scipy.argrelextrema to identify swing highs and lows, then walk back
# from the most recent pivot to find the latest meaningful pivot-to-pivot move.
# Direction (UP/DOWN) is preserved so the breakout interpretation is correct.

def _build_swing_dict(a_pivot: dict, b_pivot: dict, df: pd.DataFrame) -> dict | None:
    """Build a swing dict from two consecutive pivots (a is later in time)."""
    if a_pivot["type"] == b_pivot["type"]:
        return None
    if a_pivot["type"] == "H" and b_pivot["type"] == "L":
        sl, sh = b_pivot["price"], a_pivot["price"]
        direction = "UP"
        low_idx, high_idx = b_pivot["idx"], a_pivot["idx"]
    else:  # a=L, b=H
        sh, sl = b_pivot["price"], a_pivot["price"]
        direction = "DOWN"
        low_idx, high_idx = a_pivot["idx"], b_pivot["idx"]
    pct = (sh - sl) / sl * 100 if sl > 0 else 0
    diff = sh - sl
    if direction == "UP":
        levels = {
            "0.0%":   sh,
            "23.6%":  sh - 0.236 * diff,
            "38.2%":  sh - 0.382 * diff,
            "50.0%":  sh - 0.5 * diff,
            "61.8%":  sh - 0.618 * diff,
            "78.6%":  sh - 0.786 * diff,
            "100.0%": sl,
        }
    else:
        levels = {
            "0.0%":   sl,
            "23.6%":  sl + 0.236 * diff,
            "38.2%":  sl + 0.382 * diff,
            "50.0%":  sl + 0.5 * diff,
            "61.8%":  sl + 0.618 * diff,
            "78.6%":  sl + 0.786 * diff,
            "100.0%": sh,
        }
    return {
        "direction": direction,
        "swing_low": sl, "swing_high": sh,
        "swing_low_date": df.index[low_idx].date().isoformat(),
        "swing_high_date": df.index[high_idx].date().isoformat(),
        "swing_low_idx": int(low_idx), "swing_high_idx": int(high_idx),
        "swing_pct": pct, "levels": levels,
    }


def validate_fib_levels(swing: dict, df: pd.DataFrame, atr_val: float | None = None,
                        threshold_pct: float = 0.01) -> dict:
    """
    Validate Fib levels by checking if local trend reversals (sub-pivots within
    the swing window) cluster near the levels. A level is "important" only if
    multiple reversals happened at/near it — that's empirical S/R, not just
    geometry.

    Returns dict with `validated` bool, `pivot_match_rate`, per-level
    `touch_counts`, and the `important_levels` list (>= 2 reversal touches).
    """
    from scipy.signal import argrelextrema
    levels = swing["levels"]
    threshold = max(threshold_pct * swing["swing_high"],
                    0.5 * atr_val if atr_val and atr_val > 0 else 0)

    # Window = swing duration + short post-swing tail (catch retracement reversals)
    start_idx = min(swing["swing_low_idx"], swing["swing_high_idx"])
    end_idx = max(swing["swing_low_idx"], swing["swing_high_idx"])
    swing_duration = end_idx - start_idx
    post_tail = min(20, swing_duration)
    window_end = min(len(df) - 1, end_idx + post_tail)
    window = df.iloc[start_idx:window_end + 1]
    base_reject = {
        "validated": False, "total_pivots": 0, "pivots_matched": 0,
        "pivot_match_rate": 0.0, "touch_counts": {lab: 0 for lab in levels},
        "important_levels": [], "levels_with_2_plus_touches": 0,
        "threshold_used": threshold, "window_bars": int(len(window)),
    }
    if len(window) < 15:
        return {**base_reject, "reason": "insufficient bars"}

    # Sub-pivot detection — order=3 catches mini-reversals, not master swing
    high_arr = window["High"].values
    low_arr = window["Low"].values
    high_idx_local = list(argrelextrema(high_arr, np.greater_equal, order=3)[0])
    low_idx_local = list(argrelextrema(low_arr, np.less_equal, order=3)[0])

    master_low_abs = swing["swing_low_idx"]
    master_high_abs = swing["swing_high_idx"]
    pivots = []
    for i in high_idx_local:
        abs_idx = start_idx + i
        if abs_idx == master_low_abs or abs_idx == master_high_abs:
            continue
        pivots.append({"idx": abs_idx, "price": float(high_arr[i]), "type": "H"})
    for i in low_idx_local:
        abs_idx = start_idx + i
        if abs_idx == master_low_abs or abs_idx == master_high_abs:
            continue
        pivots.append({"idx": abs_idx, "price": float(low_arr[i]), "type": "L"})

    if len(pivots) < 4:
        return {**base_reject, "total_pivots": len(pivots), "reason": "too few pivots"}

    # Per-pivot nearest-level lookup
    touch_counts = {lab: 0 for lab in levels}
    pivots_matched = 0
    for p in pivots:
        nearest_lab, nearest_dist = None, float("inf")
        for lab, lvl in levels.items():
            d = abs(p["price"] - lvl)
            if d < nearest_dist:
                nearest_dist, nearest_lab = d, lab
        if nearest_dist <= threshold:
            touch_counts[nearest_lab] += 1
            pivots_matched += 1

    pivot_match_rate = pivots_matched / len(pivots) if pivots else 0.0
    important_levels = [lab for lab, n in touch_counts.items() if n >= 2]
    levels_with_2_plus = len(important_levels)

    # User spec: "more often than not" → match rate >= 0.50, AND at least one
    # Fib line has been tested by >=2 reversals (real S/R, not a single coincidence).
    validated = pivot_match_rate >= 0.50 and levels_with_2_plus >= 1

    return {
        "validated": validated,
        "total_pivots": len(pivots),
        "pivots_matched": pivots_matched,
        "pivot_match_rate": pivot_match_rate,
        "touch_counts": touch_counts,
        "important_levels": important_levels,
        "levels_with_2_plus_touches": levels_with_2_plus,
        "threshold_used": threshold,
        "window_bars": int(len(window)),
    }


# Validate-and-retry candidate budget. Picks first validated swing with high
# confidence (match rate >= 0.60); for borderline cases (0.50-0.59), compares
# up to 2 candidates and returns the better one.
MAX_SWING_CANDIDATES = 5
HIGH_CONFIDENCE_RATE = 0.60
BORDERLINE_FLOOR_RATE = 0.50


def latest_swing_fib(df: pd.DataFrame, min_swing_pct: float = 10.0,
                     pivot_order: int = 5, atr_val: float | None = None) -> dict | None:
    """
    Detect candidate swing pivot pairs, walk backward through them, and return
    the first that VALIDATES (i.e., its Fib levels are confirmed by sub-pivot
    reversals within the swing window). Decision rules:
      - match_rate >= 0.60 → return immediately (high confidence)
      - 0.50 <= match_rate < 0.60 → borderline; record and try next, pick best
      - match_rate < 0.50 → reject, continue walking
    Cap at MAX_SWING_CANDIDATES total attempts. Returns None if nothing validates.
    """
    from scipy.signal import argrelextrema
    if df is None or len(df) < 30:
        return None

    high = df["High"].values
    low = df["Low"].values
    high_idx = list(argrelextrema(high, np.greater_equal, order=pivot_order)[0])
    low_idx = list(argrelextrema(low, np.less_equal, order=pivot_order)[0])
    pivots = []
    for i in high_idx:
        pivots.append({"idx": int(i), "price": float(high[i]), "type": "H"})
    for i in low_idx:
        pivots.append({"idx": int(i), "price": float(low[i]), "type": "L"})
    if len(pivots) < 2:
        return None
    pivots.sort(key=lambda p: p["idx"])

    cleaned = []
    for p in pivots:
        if cleaned and cleaned[-1]["type"] == p["type"]:
            if p["type"] == "H" and p["price"] > cleaned[-1]["price"]:
                cleaned[-1] = p
            elif p["type"] == "L" and p["price"] < cleaned[-1]["price"]:
                cleaned[-1] = p
        else:
            cleaned.append(p)
    if len(cleaned) < 2:
        return None

    n_tried = 0
    attempts_log = []
    borderline = []  # list of (swing_dict, validation_dict)

    for i in range(len(cleaned) - 1, 0, -1):
        if n_tried >= MAX_SWING_CANDIDATES:
            break
        a, b = cleaned[i], cleaned[i - 1]
        swing = _build_swing_dict(a, b, df)
        if swing is None:
            continue
        if swing["swing_pct"] < min_swing_pct:
            continue
        n_tried += 1

        validation = validate_fib_levels(swing, df, atr_val=atr_val)
        attempts_log.append({
            "swing_low": swing["swing_low"],
            "swing_high": swing["swing_high"],
            "swing_low_date": swing["swing_low_date"],
            "swing_high_date": swing["swing_high_date"],
            "swing_pct": swing["swing_pct"],
            "pivot_match_rate": validation["pivot_match_rate"],
            "total_pivots": validation["total_pivots"],
            "pivots_matched": validation["pivots_matched"],
            "validated": validation["validated"],
            "reason": validation.get("reason"),
        })

        rate = validation["pivot_match_rate"]

        # Decoupled gates:
        #   • Match rate ≥ 0.60 → accept immediately even without multi-touch.
        #     Parabolic swings often have few sub-pivots; demanding multi-touch
        #     here would push us back to old/small swings whose levels are
        #     stranded far from current price. Match rate is the trustworthy
        #     signal at this level.
        #   • Match rate 0.50–0.59 → borderline; record and try next, pick best.
        #     We DO require multi-touch in this band because at marginal match
        #     rates, multi-touch is what separates real S/R from coincidence.
        #   • Match rate < 0.50 → reject outright.
        # Either way, the multi-touch result is preserved in `important_levels`
        # which drives the ★ markers and full-weight scoring downstream.
        if rate >= HIGH_CONFIDENCE_RATE:
            swing["validation"] = validation
            swing["attempts"] = attempts_log
            return swing

        if rate >= BORDERLINE_FLOOR_RATE and validation["validated"]:
            borderline.append((swing, validation))
            if len(borderline) >= 2:
                break
        # else: rejected outright, continue walking back

    if borderline:
        borderline.sort(key=lambda bv: -bv[1]["pivot_match_rate"])
        best_swing, best_val = borderline[0]
        best_swing["validation"] = best_val
        best_swing["attempts"] = attempts_log
        return best_swing

    return None


def _safe_atr(df: pd.DataFrame, n: int = 14) -> float | None:
    if df is None or len(df) < n + 1:
        return None
    try:
        v = float(bs.atr(df, n).iloc[-1])
        return v if np.isfinite(v) and v > 0 else None
    except Exception:
        return None


def fib_daily(daily: pd.DataFrame) -> dict | None:
    """Latest validated swing on the daily chart. Min swing 10%."""
    r = latest_swing_fib(daily, min_swing_pct=10.0, pivot_order=5,
                          atr_val=_safe_atr(daily, 14))
    if r is not None:
        r["timeframe"] = "daily"
    return r


def fib_weekly(weekly: pd.DataFrame) -> dict | None:
    """Latest validated swing on the weekly chart. Min swing 15%."""
    if weekly is None or len(weekly) < 20:
        return None
    r = latest_swing_fib(weekly, min_swing_pct=15.0, pivot_order=3,
                          atr_val=_safe_atr(weekly, 14))
    if r is not None:
        r["timeframe"] = "weekly"
    return r


def fib_monthly(monthly: pd.DataFrame) -> dict | None:
    """Latest validated swing on the monthly chart. Min swing 25%."""
    if monthly is None or len(monthly) < 13:
        return None
    r = latest_swing_fib(monthly, min_swing_pct=25.0, pivot_order=2,
                          atr_val=_safe_atr(monthly, 14))
    if r is not None:
        r["timeframe"] = "monthly"
    return r


# Timeframe multiplier for breakout scoring — higher TF levels are slightly
# less precise on the daily chart, so de-rate their points.
TF_MULTIPLIER = {"daily": 1.0, "weekly": 0.85, "monthly": 0.70}


def best_swing_fib(daily: pd.DataFrame, weekly: pd.DataFrame | None,
                   monthly: pd.DataFrame | None) -> dict | None:
    """
    Multi-timeframe fallback orchestrator (hedge-fund standard):
      1. Daily swing (10% min)
      2. Weekly swing (15% min) if daily fails
      3. Monthly swing (25% min) if weekly also fails
    Returns the first found, annotated with `timeframe`. None only when all three TFs
    have no qualifying swing — a true sideways chop across years.
    """
    r = fib_daily(daily)
    if r is not None:
        return r
    r = fib_weekly(weekly)
    if r is not None:
        return r
    r = fib_monthly(monthly)
    return r


# ── Module 5: Multi-Anchor AVWAP ─────────────────────────────────────────────

def avwap_series(df: pd.DataFrame, anchor_idx) -> pd.Series:
    """Compute anchored VWAP from anchor_idx onwards."""
    s = df.loc[anchor_idx:]
    if s.empty:
        return pd.Series(dtype=float)
    tp = (s["High"] + s["Low"] + s["Close"]) / 3
    return (tp * s["Volume"]).cumsum() / s["Volume"].cumsum()


def best_avwap(daily: pd.DataFrame, ticker: str) -> dict:
    closes = daily["Close"]
    px = float(closes.iloc[-1])

    candidates: dict[str, pd.Timestamp] = {}
    candidates["52wk_low"] = closes.idxmin()
    candidates["52wk_high"] = closes.idxmax()
    # Last significant swing low (60-day window)
    if len(daily) >= 60:
        candidates["swing_low_60d"] = daily["Low"].tail(60).idxmin()
    # 200 sessions ago
    if len(daily) >= 200:
        candidates["200d_ago"] = daily.index[-200]
    # Try last earnings via trade-setup
    try:
        ed = ts.get_last_earnings_date(ticker)
        if ed:
            ts_ed = pd.Timestamp(ed, tz=daily.index.tz)
            # Snap to nearest available index date
            after = daily.index[daily.index >= ts_ed]
            if not after.empty:
                candidates["last_earnings"] = after[0]
    except Exception:
        pass

    series_dict: dict[str, tuple[pd.Timestamp, pd.Series]] = {}
    for name, idx in candidates.items():
        try:
            s = avwap_series(daily, idx)
            if len(s) >= 5:
                series_dict[name] = (idx, s)
        except Exception:
            continue

    # Pick best = below price AND rising (acting as supportive trend)
    best_name, best_dist = None, float("inf")
    for name, (idx, s) in series_dict.items():
        cur = float(s.iloc[-1])
        if cur >= px:
            continue
        # Rising over last 20 bars
        if len(s) >= 20 and s.iloc[-1] > s.iloc[-20]:
            dist = px - cur
            if dist < best_dist:
                best_name, best_dist = name, dist

    # Fallback: if none supportive, pick the closest-below regardless of slope
    if best_name is None:
        for name, (idx, s) in series_dict.items():
            cur = float(s.iloc[-1])
            if cur < px:
                dist = px - cur
                if dist < best_dist:
                    best_name, best_dist = name, dist

    return {
        "anchors": series_dict, "best": best_name, "price": px,
        "best_value": float(series_dict[best_name][1].iloc[-1]) if best_name else None,
        "best_anchor_date": series_dict[best_name][0].date().isoformat() if best_name else None,
    }


# ── Module 6: Pullback Quality (reuse) ───────────────────────────────────────

def pullback_quality(daily: pd.DataFrame) -> dict:
    return ts.assess_pullback_quality(daily)


# ── Module 7: Composite Score ────────────────────────────────────────────────

FIB_KEY_LEVELS = ["23.6%", "38.2%", "50.0%", "61.8%", "100.0%"]


def fib_breakout_signal(daily: pd.DataFrame, fib_d: dict | None, vol: dict) -> tuple[str, int]:
    """
    Detect Fibonacci breakouts/breakdowns at key levels (23.6, 38.2, 50, 61.8, 100).
    Returns (description, points). Positive = breakout/hold above; negative = break below.
    """
    if not fib_d:
        return ("no swing on any TF", 0)
    levels = fib_d["levels"]
    # Include the swing high as a "100%" level (a full retracement back to top)
    levels_with_100 = dict(levels)
    levels_with_100["100.0%"] = fib_d["swing_high"]
    tf = fib_d.get("timeframe", "daily")
    tf_mult = TF_MULTIPLIER.get(tf, 1.0)
    tf_tag = "" if tf == "daily" else f" [{tf[0].upper()}]"  # [W] or [M]

    px = float(daily["Close"].iloc[-1])
    prev = float(daily["Close"].iloc[-2]) if len(daily) >= 2 else px
    vol_confirm = vol["rel_today"] >= 1.5

    bullish_break, bearish_break = [], []
    held_above, held_below = [], []
    for lab in FIB_KEY_LEVELS:
        if lab not in levels_with_100:
            continue
        lvl = levels_with_100[lab]
        # Breakout today: prev was below, today is above
        if prev <= lvl and px > lvl:
            bullish_break.append(lab)
        elif prev >= lvl and px < lvl:
            bearish_break.append(lab)
        # Holding within 2% (support/resistance pivot)
        elif abs(px - lvl) / px < 0.02:
            if px >= lvl:
                held_above.append(lab)
            else:
                held_below.append(lab)

    if bullish_break:
        base = min(15, 8 * len(bullish_break))
        bonus = 3 if vol_confirm else 0
        pts = int(round((base + bonus) * tf_mult))
        return (f"BREAKOUT above Fib{tf_tag} {','.join(bullish_break)}" + (" on vol" if vol_confirm else ""), pts)
    if bearish_break:
        base = min(15, 8 * len(bearish_break))
        pts = int(round(-base * tf_mult))
        return (f"BREAKDOWN below Fib{tf_tag} {','.join(bearish_break)}", pts)
    if held_above:
        return (f"holding above Fib{tf_tag} {','.join(held_above)} (support)", int(round(6 * tf_mult)))
    if held_below:
        return (f"sitting below Fib{tf_tag} {','.join(held_below)} (resistance)", int(round(-4 * tf_mult)))
    # No breakouts and not at a key level → near or between
    nearest, nearest_dist = None, float("inf")
    for lab, lvl in levels_with_100.items():
        d = abs(px - lvl) / px
        if d < nearest_dist:
            nearest_dist, nearest = d, lab
    return (f"between Fib{tf_tag} levels (closest {nearest} @ {nearest_dist*100:.1f}%)", 0)


def ma_confluence_score(daily: pd.DataFrame, sma30: dict, fib_d: dict | None,
                        avwap: dict, price: float) -> tuple[str, int]:
    """
    Moving averages score points ONLY when they confluent with a Fibonacci key
    level OR the best AVWAP. +3 per confluence, capped at +10. Standalone MAs
    contribute nothing — this is intentional per the user's scoring philosophy.
    """
    levels_to_check = []
    if fib_d:
        for lab in FIB_KEY_LEVELS:
            if lab in fib_d["levels"]:
                levels_to_check.append(("Fib " + lab, fib_d["levels"][lab]))
        levels_to_check.append(("Fib 100%", fib_d["swing_high"]))
    if avwap["best"] and avwap["best_value"]:
        levels_to_check.append((f"AVWAP-{avwap['best']}", avwap["best_value"]))

    if not levels_to_check:
        return ("no Fib/AVWAP to confluent with", 0)

    c = daily["Close"]
    mas = {}
    if len(c) >= 21: mas["EMA21"] = float(bs.ema(c, 21).iloc[-1])
    if len(c) >= 50: mas["SMA50"] = float(bs.sma(c, 50).iloc[-1])
    if len(c) >= 200: mas["SMA200"] = float(bs.sma(c, 200).iloc[-1])
    if sma30["valid"]: mas["30wk"] = sma30["sma"]

    confluences = []
    for ma_name, ma_val in mas.items():
        for lvl_name, lvl_val in levels_to_check:
            if abs(ma_val - lvl_val) / price < 0.02:
                confluences.append(f"{ma_name}≈{lvl_name}")
    if not confluences:
        return ("no MA-Fib/AVWAP confluences (MAs alone score 0)", 0)
    pts = min(10, 3 * len(confluences))
    return (f"confluences: {', '.join(confluences[:3])}{'...' if len(confluences) > 3 else ''}", pts)


def score_components(daily, daily_t, weekly_t, monthly_t, sma30, vol, fib_d,
                     avwap, pullback, rsi_val, atr_val, price,
                     entry_cls=None, best_rr=None) -> dict:
    """
    Re-weighted scoring (per user spec):
      PRIMARY (entry quality, heavy weight):
        - Pullback, RSI, Entry class, Chasing, R/R
      SECONDARY (Fibonacci-based):
        - Fibonacci breakouts/breakdowns at 23.6/38.2/50/61.8/100% levels
        - AVWAP proximity
      CONFLUENCE-ONLY (MAs):
        - MAs score ONLY when within 2% of a Fib level or best AVWAP
      Volume kept as a standalone signal.
      Daily/Weekly/Monthly trend labels are NOT scored — shown in report for context.
    """
    comp = {}

    # ── PRIMARY: Pullback (max +20 / min -20) ──
    pb_cls = pullback.get("classification", "")
    if "HEALTHY" in pb_cls and "UN" not in pb_cls:
        comp["Pullback"] = (f"HEALTHY ({pullback.get('score',0)}/100)", 20)
    elif "ACCEPTABLE" in pb_cls:
        comp["Pullback"] = (f"ACCEPTABLE ({pullback.get('score',0)}/100)", 10)
    elif "QUESTIONABLE" in pb_cls:
        comp["Pullback"] = (f"QUESTIONABLE ({pullback.get('score',0)}/100)", -10)
    elif "UNHEALTHY" in pb_cls:
        comp["Pullback"] = (f"UNHEALTHY ({pullback.get('score',0)}/100)", -20)
    else:
        comp["Pullback"] = (f"{pb_cls or 'N/A'}", 0)

    # ── PRIMARY: RSI band (max +10 / min -25) ──
    if np.isnan(rsi_val):
        comp["RSI"] = ("n/a", 0)
    elif 40 <= rsi_val <= 60:
        comp["RSI"] = (f"healthy {rsi_val:.0f}", 10)
    elif rsi_val > 75:
        comp["RSI"] = (f"extreme overheated {rsi_val:.0f}", -25)
    elif rsi_val > 70:
        comp["RSI"] = (f"overheated {rsi_val:.0f}", -15)
    elif rsi_val < 30:
        comp["RSI"] = (f"oversold {rsi_val:.0f}", 5)
    else:
        comp["RSI"] = (f"{rsi_val:.0f}", 3)

    # ── PRIMARY: Entry classification (max +25 / min -30) ──
    if entry_cls == "PULLBACK_ENTRY":
        comp["Entry class"] = ("PULLBACK_ENTRY (preferred)", 25)
    elif entry_cls == "BREAKOUT_WATCH":
        comp["Entry class"] = ("BREAKOUT_WATCH", 10)
    elif entry_cls == "IN_NO_MANS_LAND":
        comp["Entry class"] = ("IN_NO_MANS_LAND", -10)
    elif entry_cls == "EXTENDED":
        comp["Entry class"] = ("EXTENDED (do not chase)", -25)
    elif entry_cls == "BROKEN_DOWN":
        comp["Entry class"] = ("BROKEN_DOWN (avoid)", -30)
    else:
        comp["Entry class"] = (str(entry_cls or "?"), 0)

    # ── PRIMARY: Chasing penalty (max 0 / min -35) ──
    pb_cls_l = (pullback.get("classification") or "").upper()
    at_highs = "AT HIGHS" in pb_cls_l or "NO PULLBACK" in pb_cls_l
    if entry_cls == "EXTENDED" and at_highs and not np.isnan(rsi_val) and rsi_val > 65:
        comp["Chasing"] = ("EXTENDED + at highs + RSI > 65", -35)
    elif entry_cls == "EXTENDED" and at_highs:
        comp["Chasing"] = ("EXTENDED + at highs", -20)
    else:
        comp["Chasing"] = ("not chasing", 0)

    # ── PRIMARY: R/R (max +20 / min -15) ──
    if best_rr is None or best_rr == "?" or best_rr == 0:
        comp["R/R"] = ("n/a", 0)
    else:
        try:
            rr_v = float(best_rr)
            if rr_v >= 3.0:
                comp["R/R"] = (f"{rr_v:.1f}:1 (good)", 20)
            elif rr_v >= 2.0:
                comp["R/R"] = (f"{rr_v:.1f}:1 (acceptable)", 10)
            elif rr_v >= 1.5:
                comp["R/R"] = (f"{rr_v:.1f}:1 (marginal)", -5)
            else:
                comp["R/R"] = (f"{rr_v:.1f}:1 (poor)", -15)
        except (ValueError, TypeError):
            comp["R/R"] = (str(best_rr), 0)

    # ── SECONDARY: Fibonacci breakouts/breakdowns at key levels (max +18 / min -15) ──
    fib_desc, fib_pts = fib_breakout_signal(daily, fib_d, vol)
    comp["Fibonacci"] = (fib_desc, fib_pts)

    # ── SECONDARY: AVWAP proximity (max +10 / min -10) ──
    if avwap["best"] is None:
        comp["AVWAP"] = ("NO SUPPORTIVE AVWAP (all anchors above px)", -10)
    else:
        gap = price - avwap["best_value"]
        gap_in_atr = gap / atr_val if atr_val > 0 else 99
        if gap_in_atr < 1.0 and gap > 0:
            comp["AVWAP"] = (f"at AVWAP-{avwap['best']} ${avwap['best_value']:.2f} ({gap_in_atr:.1f}×ATR above)", 10)
        elif gap_in_atr < 2.5:
            comp["AVWAP"] = (f"AVWAP-{avwap['best']} ${avwap['best_value']:.2f} ({gap_in_atr:.1f}×ATR below px)", 5)
        else:
            comp["AVWAP"] = (f"AVWAP-{avwap['best']} far below ({gap_in_atr:.1f}×ATR)", 0)

    # ── CONFLUENCE: MAs score ONLY when matching Fib/AVWAP (max +10 / min 0) ──
    ma_desc, ma_pts = ma_confluence_score(daily, sma30, fib_d, avwap, price)
    comp["MA confluence"] = (ma_desc, ma_pts)

    # ── Volume (standalone, max +12 / min -10) ──
    if vol["low_liquidity"]:
        comp["Volume"] = (f"LOW LIQUIDITY (avg20d {vol['avg_20d']/1000:.0f}k)", -5)
    else:
        pts, bits = 0, []
        if vol["rel_today"] >= 1.5:
            pts += 4; bits.append(f"rel today {vol['rel_today']:.1f}×")
        elif vol["rel_today"] < 0.5:
            pts -= 4; bits.append(f"rel today only {vol['rel_today']:.1f}×")
        if vol["up_down_ratio_20d"] >= 1.3:
            pts += 4; bits.append(f"up/dn {vol['up_down_ratio_20d']:.2f}")
        elif vol["up_down_ratio_20d"] < 0.7:
            pts -= 4; bits.append(f"up/dn {vol['up_down_ratio_20d']:.2f}")
        if vol["cmf_20"] >= 0.05:
            pts += 4; bits.append(f"CMF +{vol['cmf_20']:.2f}")
        elif vol["cmf_20"] <= -0.05:
            pts -= 4; bits.append(f"CMF {vol['cmf_20']:.2f}")
        if not bits:
            bits = ["neutral"]
        comp["Volume"] = (", ".join(bits), max(-10, min(12, pts)))

    return comp


def total_score(components: dict) -> tuple[int, str]:
    """
    Composite: signed sum of component points, clamped to ±50, then anchored at
    base 50. Math:
        signed_sum  ∈ [theoretical -160, +130] → clamp ±50 → [-50, +50]
        total       = 50 + clamped  → always ∈ [0, 100]
    Reaching 100 requires the *clamped* signed sum to saturate at +50, meaning
    the net positive minus net negative must be ≥ +50 — so a single penalty
    above some threshold (like -25 chasing) actually moves the score by 1 pt
    less than its nominal weight when the rest is already saturated. This is
    intentional: at the ceiling the score reflects "as good as the rubric goes."
    """
    raw_sum = sum(pts for _, pts in components.values())
    clamped = max(-50, min(50, raw_sum))
    total = int(50 + clamped)
    if total >= 80:
        cls = "PRIME ENTRY"
    elif total >= 60:
        cls = "GOOD ENTRY"
    elif total >= 40:
        cls = "MIXED"
    else:
        cls = "AVOID"
    return total, cls


def has_timeframe_conflict(daily_t, weekly_t, monthly_t) -> bool:
    labels = {daily_t["label"], weekly_t["label"], monthly_t["label"]}
    return ("UPTREND" in labels and "DOWN" in labels)


# ── Entry Plan (reuse trade-setup pieces) ────────────────────────────────────

def entry_plan(daily: pd.DataFrame, weekly: pd.DataFrame | None) -> dict:
    sr = ts.find_support_resistance(daily)
    entry = ts.calc_entry_zone(daily, sr)
    stop = ts.calc_stop_loss(daily, entry, sr)
    targets = ts.calc_targets(daily, entry, sr, stop)
    rr = ts.calc_risk_reward(entry, stop, targets)
    mtf = ts.calc_mtf_alignment(daily, weekly) if weekly is not None else {"weekly_trend": "UNKNOWN", "alignment": "N/A"}
    return {"sr": sr, "entry": entry, "stop": stop, "targets": targets, "rr": rr, "mtf": mtf}


# ── Per-Ticker Analysis ──────────────────────────────────────────────────────

def analyze(ticker: str, daily: pd.DataFrame, weekly: pd.DataFrame | None,
            monthly: pd.DataFrame | None) -> dict:
    daily_t = daily_trend(daily)
    weekly_t = weekly_trend(weekly)
    monthly_t = monthly_trend(monthly)
    sma30 = thirty_week_sma(daily)
    vol = volume_analysis(daily)
    # Multi-TF orchestrator: daily → weekly → monthly. fib_d holds the BEST available fib.
    fib_d = best_swing_fib(daily, weekly, monthly)
    fib_w = fib_weekly(weekly)  # kept separately for chart's weekly panel
    aw = best_avwap(daily, ticker)
    pullback = pullback_quality(daily)
    plan = entry_plan(daily, weekly)

    rsi_val = float(bs.rsi(daily["Close"], 14).iloc[-1])
    atr_val = float(bs.atr(daily, 14).iloc[-1])
    px = float(daily["Close"].iloc[-1])

    components = score_components(daily, daily_t, weekly_t, monthly_t, sma30, vol,
                                  fib_d, aw, pullback, rsi_val, atr_val, px,
                                  entry_cls=plan["entry"].get("classification"),
                                  best_rr=plan["rr"].get("best_rr"))
    total, cls = total_score(components)
    conflict = has_timeframe_conflict(daily_t, weekly_t, monthly_t)

    # Mitigation-visibility flags (worst-case items 4/7/8/9 surfaced in summary)
    raw_sum = sum(pts for _, pts in components.values())
    flags = []
    if conflict:
        flags.append("CONFLICT")            # #9 timeframe disagreement
    if aw["best"] is None:
        flags.append("NO-AVWAP")            # #4 no supportive AVWAP
    chasing_pts = components.get("Chasing", ("", 0))[1]
    if chasing_pts <= -15:
        flags.append("CHASE")               # #8 chasing penalty active
    if raw_sum >= 60 and total == 100:
        flags.append("CEILING")             # #7 score saturated at +50 clamp
    if raw_sum <= -60 and total == 0:
        flags.append("FLOOR")               # symmetric: saturated at -50 clamp
    # FIB-UNVALIDATED: Fib levels present but no important_levels (or no fib at all)
    if fib_d is not None:
        v = fib_d.get("validation") or {}
        if not v.get("important_levels"):
            flags.append("FIB-UNVALIDATED")

    high52 = float(daily["Close"].max())
    low52 = float(daily["Close"].min())

    return {
        "ticker": ticker, "price": px, "rsi": rsi_val, "atr": atr_val,
        "high52": high52, "low52": low52,
        "daily_t": daily_t, "weekly_t": weekly_t, "monthly_t": monthly_t,
        "sma30": sma30, "volume": vol, "fib_d": fib_d, "fib_w": fib_w,
        "avwap": aw, "pullback": pullback, "components": components,
        "score": total, "class": cls, "conflict": conflict, "plan": plan,
        "flags": flags, "raw_sum": raw_sum,
        "daily_df": daily, "weekly_df": weekly, "monthly_df": monthly,
    }


def attach_first_phase(r: dict):
    """Compute and attach the first-phase recommendation to a result dict."""
    r["first_phase"] = recommend_first_phase_entry(r)
    return r


# ── Flag rendering ───────────────────────────────────────────────────────────

_FLAG_LABELS = {
    "CONFLICT":         "🚨 CONFLICT (timeframe disagreement)",
    "NO-AVWAP":         "⚠ NO-AVWAP (all anchors above px)",
    "CHASE":            "⛔ CHASE (EXTENDED + at-highs + RSI hot)",
    "CEILING":          "📈 CEILING (score capped at 100)",
    "FLOOR":            "📉 FLOOR (score floored at 0)",
    "FIB-UNVALIDATED":  "⚠ FIB-UNVALIDATED (no level has ≥2 reversal touches)",
}


def _flag_label(f: str) -> str:
    return _FLAG_LABELS.get(f, f)


# ── Text Report ──────────────────────────────────────────────────────────────

def fmt_text_report(r: dict) -> str:
    cls_icon = {"PRIME ENTRY": "🟢🟢", "GOOD ENTRY": "🟢", "MIXED": "🟡", "AVOID": "🔴"}.get(r["class"], "")
    lines = []
    lines.append("══════════════════════════════════════════")
    lines.append(f"{r['ticker']}  ${r['price']:.2f}  —  {cls_icon} {r['class']} (score {r['score']}/100)")
    lines.append("══════════════════════════════════════════")
    if r["flags"]:
        flag_text = "  ".join(_flag_label(f) for f in r["flags"])
        lines.append(f"FLAGS: {flag_text}")
    if r.get("raw_sum") is not None and abs(r["raw_sum"]) > 50:
        lines.append(f"  (raw signed sum {r['raw_sum']:+d} — clamped to ±50 before base 50)")

    # Trends
    lines.append("\nTRENDS:")
    dt = r["daily_t"]; wt = r["weekly_t"]; mt = r["monthly_t"]
    lines.append(f"  Daily:   {dt['label']:<12} ({sum(dt['above'].values())}/{len(dt['above'])} MAs above)")
    lines.append(f"  Weekly:  {wt['label']:<12}")
    lines.append(f"  Monthly: {mt['label']:<12}")

    # 30wk SMA
    s30 = r["sma30"]
    if s30["valid"]:
        sl = "rising" if s30["rising"] else "flat/falling"
        side = "above" if s30["price_above"] else "below"
        lines.append(f"  30wk SMA: ${s30['sma']:.2f} (px {side}, {s30['distance_pct']:+.1f}%; slope {sl})")
    else:
        lines.append(f"  30wk SMA: N/A ({s30.get('reason','')})")

    # Volume
    v = r["volume"]
    lines.append("\nVOLUME:")
    lines.append(f"  Today {v['today']/1e6:.1f}M vs 20d avg {v['avg_20d']/1e6:.1f}M ({v['rel_today']:.2f}×)")
    lines.append(f"  Up/Dn 20d: {v['up_down_ratio_20d']:.2f}  |  CMF-20: {v['cmf_20']:+.3f}  |  10d slope: {v['vol_slope_10d_pct']:+.1f}%")
    if v["low_liquidity"]:
        lines.append("  ⚠ LOW LIQUIDITY")

    # Fibonacci (from latest detected swing)
    lines.append("\nFIBONACCI (validated swing — multi-TF: daily → weekly → monthly):")
    if r["fib_d"]:
        f = r["fib_d"]
        tf = f.get("timeframe", "daily")
        tf_label = tf.upper()
        v = f.get("validation") or {}
        lines.append(f"  {tf_label} {f['direction']} swing: ${f['swing_low']:.2f} ({f['swing_low_date']}) → ${f['swing_high']:.2f} ({f['swing_high_date']}) = {f['swing_pct']:.1f}%")
        # Validation summary
        important = set(v.get("important_levels") or [])
        if v:
            match_pct = v.get("pivot_match_rate", 0) * 100
            lines.append(f"  Sub-pivot match: {v.get('pivots_matched',0)}/{v.get('total_pivots',0)} reversals at Fib levels "
                         f"({match_pct:.0f}%), threshold ${v.get('threshold_used',0):.2f}, window {v.get('window_bars',0)} bars")
            sr_check = "✓" if important else "✗"
            if important:
                imp_str = ", ".join(f"Fib {lab} ({v['touch_counts'].get(lab,0)} touches)" for lab in important)
                lines.append(f"  S/R confirmed: {sr_check} important levels (≥2 reversal touches): {imp_str}")
            else:
                lines.append(f"  S/R confirmed: {sr_check} no level had ≥2 reversal touches (swing levels still drawn but at half weight in scoring)")
        # Per-level listing with ★ markers
        for lab, lvl in f["levels"].items():
            star = " ★" if lab in important else ""
            marker = " ← current price" if abs(r["price"] - lvl) / r["price"] < 0.015 else ""
            n = v.get("touch_counts", {}).get(lab, 0)
            tcount = f" [{n} touch{'es' if n != 1 else ''}]" if n > 0 else ""
            lines.append(f"    {lab:<6} ${lvl:.2f}{star}{tcount}{marker}")
        # Attempts trail (only if we tried more than the first one)
        attempts = f.get("attempts") or []
        if len(attempts) > 1:
            lines.append(f"  Attempts: {len(attempts)} candidates evaluated (last shown was selected)")
            for j, att in enumerate(attempts):
                selected = (j == len(attempts) - 1)
                tag = "→" if selected else " "
                reason = att.get("reason") or f"match {att.get('pivots_matched',0)}/{att.get('total_pivots',0)} ({att.get('pivot_match_rate',0)*100:.0f}%)"
                lines.append(f"     {tag} ${att['swing_low']:.2f} ({att['swing_low_date']}) → ${att['swing_high']:.2f} ({att['swing_high_date']}) = {att['swing_pct']:.1f}%  — {reason}")
    else:
        lines.append("  No validated swing on any TF (true chop / no S/R respect)")
    if r["fib_w"] and (r["fib_d"] is None or r["fib_d"].get("timeframe") != "weekly"):
        # Always show the weekly fib summary line for chart context, unless the
        # main fib already IS weekly (which would duplicate the info).
        f = r["fib_w"]
        lines.append(f"  Weekly (chart panel) {f['direction']} swing ${f['swing_low']:.2f} → ${f['swing_high']:.2f} ({f['swing_pct']:.1f}%): 38.2 ${f['levels']['38.2%']:.2f} | 50 ${f['levels']['50.0%']:.2f} | 61.8 ${f['levels']['61.8%']:.2f}")

    # AVWAP
    aw = r["avwap"]
    lines.append("\nAVWAP (multi-anchor):")
    if aw["best"]:
        lines.append(f"  Best = {aw['best']} (anchor {aw['best_anchor_date']}): ${aw['best_value']:.2f} ({(r['price']/aw['best_value']-1)*100:+.1f}% from price)")
    else:
        lines.append("  ⚠ All AVWAP anchors above price — no supportive AVWAP")
    for name, (idx, s) in aw["anchors"].items():
        if name == aw["best"]:
            continue
        lines.append(f"    {name:<18} ${float(s.iloc[-1]):.2f}")

    # Component table
    lines.append("\nSCORE COMPONENTS:")
    for name, (desc, pts) in r["components"].items():
        sign = "+" if pts >= 0 else ""
        lines.append(f"  {name:<14} {desc:<55} {sign}{pts}")

    # Entry plan
    plan = r["plan"]
    entry = plan["entry"]
    stop = plan["stop"]
    tgts = plan["targets"]
    rr = plan["rr"]
    lines.append("\nENTRY PLAN:")
    lines.append(f"  Classification: {entry.get('classification','?')}")
    if entry.get("zone_low") and entry.get("zone_high"):
        lines.append(f"  Entry zone:   ${entry['zone_low']:.2f} – ${entry['zone_high']:.2f}")
    elif entry.get("trigger"):
        lines.append(f"  Trigger:      {entry['trigger']}")
    if stop.get("recommended"):
        sr_val = stop.get("recommended")
        try:
            lines.append(f"  Stop:         ${float(sr_val):.2f}  (risk {stop.get('risk_pct','?')}%, method {stop.get('method','?')})")
        except (ValueError, TypeError):
            lines.append(f"  Stop:         {sr_val}")
    if tgts.get("t1"):
        lines.append(f"  Targets:      T1 ${tgts['t1']:.2f}  T2 ${tgts.get('t2',0) or 0:.2f}  T3 ${tgts.get('t3',0) or 0:.2f}")
    if rr.get("best_rr"):
        lines.append(f"  R/R:          T1 {rr.get('t1_rr','?')}  T2 {rr.get('t2_rr','?')}  T3 {rr.get('t3_rr','?')}  Best {rr.get('best_rr','?')}:1")
    lines.append(f"  Weekly trend: {plan['mtf']['weekly_trend']}  Alignment: {plan['mtf']['alignment']}")

    # First-phase entry recommendation block (attached by attach_first_phase)
    fp = r.get("first_phase")
    if fp:
        lines.append("\nFIRST-PHASE RECOMMENDATION:")
        action = fp["action"]
        if action == "AVOID":
            lines.append(f"  ⛔ AVOID — {fp.get('note','')}")
        elif action == "INSUFFICIENT_STRUCTURE":
            lines.append(f"  ⚠ INSUFFICIENT_STRUCTURE — {fp.get('note','')}")
        elif action == "STRATEGY":
            lines.append(f"  📝 STRATEGY (no price target): {fp.get('strategy_text','')}")
        else:
            lines.append(f"  ✅ {action} @ ${fp['entry_price']:.2f}  |  stab {fp['stab_pct']}% of intended size")
            lines.append(f"     Tight stop ${fp['tight_stop']:.2f} (risk {fp['tight_risk_pct']:.1f}%)")
            lines.append(f"     Worst-case ${fp['worst_stop']:.2f} (risk {fp['worst_risk_pct']:.1f}%)" +
                         (f"  [{fp['worst_note']}]" if fp.get('worst_note') else ""))
            lines.append(f"     Confluence: {fp['confluence_desc']}")
            if fp.get("flags"):
                lines.append(f"     Flags: {', '.join(fp['flags'])}")

    return "\n".join(lines)


# ── Summary Table ────────────────────────────────────────────────────────────

def fmt_summary_table(results: list[dict]) -> str:
    lines = []
    lines.append("\n══════════════════════════════════════════")
    lines.append("SUMMARY (sorted by composite score)")
    lines.append("══════════════════════════════════════════")
    header = f"{'Ticker':<6} {'Score':>5} {'Class':<12} {'EntryCls':<14} {'Daily':<11} {'Weekly':<11} {'Mthly':<11} {'30wk':<5} {'RSI':>4} {'Vol':>5} {'R/R':>4}  Flags"
    lines.append(header)
    lines.append("─" * len(header))
    for r in sorted(results, key=lambda x: -x["score"]):
        s30_mark = "✓" if (r["sma30"]["valid"] and r["sma30"]["price_above"] and r["sma30"]["rising_4wk"]) else "✗"
        rel = r["volume"]["rel_today"]
        rsi_v = r["rsi"]
        best_rr = r["plan"]["rr"].get("best_rr", "?")
        ec = r["plan"]["entry"].get("classification", "?")[:14]
        flags = ",".join(r.get("flags", [])) if r.get("flags") else ""
        lines.append(
            f"{r['ticker']:<6} {r['score']:>5} {r['class']:<12} {ec:<14} {r['daily_t']['label']:<11} {r['weekly_t']['label']:<11} {r['monthly_t']['label']:<11} {s30_mark:<5} {rsi_v:>4.0f} {rel:>4.1f}× {best_rr}  {flags}"
        )
    return "\n".join(lines)


# ── First-Phase Entry Recommendation ─────────────────────────────────────────

def recommend_first_phase_entry(r: dict) -> dict:
    """
    Build a first-phase (stab) recommendation per the approved plan:
      - Confluence-driven sizing (10-30%)
      - Two stops: tight (cluster invalidation) + worst-case (thesis broken)
      - Action: BUY-LIMIT / WAIT / STRATEGY / INSUFFICIENT_STRUCTURE / AVOID
    """
    daily = r["daily_df"]
    px = r["price"]
    atr = r["atr"]
    rsi = r["rsi"]
    fib_d = r["fib_d"]
    avwap = r["avwap"]
    sma30 = r["sma30"]
    plan = r["plan"]
    composite_class = r["class"]
    entry_cls = plan["entry"].get("classification")
    best_rr = plan["rr"].get("best_rr")
    vol_info = r["volume"]

    # Composite AVOID → AVOID (per scoring rules)
    if composite_class == "AVOID":
        return {"action": "AVOID", "note": f"composite score AVOID ({r['score']}/100)"}

    # ── Step 1: build level catalogue (only levels BELOW price) ──
    levels = []  # list of dicts {price, type, desc}

    # Fibonacci levels (multi-TF — fib_d carries timeframe metadata + validation)
    # Important (validated, ≥2 reversal touches) Fib levels count as full "Fib"
    # type in the confluence catalogue. Non-validated Fib levels still appear
    # so the user sees them on the chart, but they're tagged as "FibX" (weak)
    # which the clustering scorer counts at half-type-weight downstream.
    if fib_d:
        tf_label = fib_d.get("timeframe", "daily")
        tag = "" if tf_label == "daily" else f"({tf_label[0].upper()})"
        important = set((fib_d.get("validation") or {}).get("important_levels") or [])
        for lab in ["23.6%", "38.2%", "50.0%", "61.8%", "78.6%"]:
            if lab in fib_d["levels"]:
                p = fib_d["levels"][lab]
                if p < px:
                    if lab in important:
                        levels.append({"price": p, "type": "Fib", "desc": f"Fib{tag} {lab} ★"})
                    else:
                        levels.append({"price": p, "type": "FibX", "desc": f"Fib{tag} {lab} (unverified)"})

    # AVWAP — all 5 anchor values that fall below px
    for name, (idx, series) in avwap.get("anchors", {}).items():
        try:
            v = float(series.iloc[-1])
            if v < px:
                levels.append({"price": v, "type": "AVWAP", "desc": f"AVWAP-{name}"})
        except Exception:
            continue

    # Moving averages — compute current values
    c = daily["Close"]
    ma_candidates = []
    if len(c) >= 21: ma_candidates.append(("EMA21", float(bs.ema(c, 21).iloc[-1])))
    if len(c) >= 50: ma_candidates.append(("SMA50", float(bs.sma(c, 50).iloc[-1])))
    if len(c) >= 200: ma_candidates.append(("SMA200", float(bs.sma(c, 200).iloc[-1])))
    if sma30["valid"]: ma_candidates.append(("30wk", sma30["sma"]))
    for name, val in ma_candidates:
        if val < px:
            levels.append({"price": val, "type": "MA", "desc": name})

    # Horizontal S/R from trade-setup — but trade-setup's `type` field can be
    # "Fib 38.2%", "VWAP", "SMA(50)" etc. Normalize so dedup works correctly.
    def _classify_support_type(stype: str) -> str:
        s = (stype or "").lower()
        if s.startswith("fib"):
            return "Fib"
        if "vwap" in s:
            return "AVWAP"
        if "sma" in s or "ema" in s:
            return "MA"
        return "Horiz"

    for s in plan["sr"].get("supports", []):
        try:
            p = float(s["price"])
            if p < px:
                raw_type = s.get("type", "Horiz")
                classified = _classify_support_type(raw_type)
                # Skip Fib levels from trade-setup — we already have our own
                # multi-TF Fib above, and trade-setup's fixed-window fib double-counts.
                if classified == "Fib":
                    continue
                levels.append({"price": p, "type": classified, "desc": raw_type})
        except (KeyError, TypeError, ValueError):
            continue

    # ── STRATEGY case: no levels below price (extended/ATH) ──
    if not levels:
        ema21_val = ma_candidates[0][1] if ma_candidates and ma_candidates[0][0] == "EMA21" else None
        sma50_val = next((v for n, v in ma_candidates if n == "SMA50"), None)
        parts = []
        if ema21_val: parts.append(f"EMA21 ~${ema21_val:.2f}")
        if sma50_val: parts.append(f"SMA50 ~${sma50_val:.2f}")
        targets = " or ".join(parts) if parts else "next key MA"
        return {
            "action": "STRATEGY",
            "strategy_text": (f"watch for low-vol pullback (vol < 80% of 20d avg) to test {targets}; "
                              "on bullish reversal candle with vol confirm, stab 10-15% with stop below tested MA × 0.985"),
        }

    # Deduplicate: if two levels are within 0.05% of each other (same number),
    # keep the one with the more specific type priority (Fib > AVWAP > MA > Horiz).
    type_priority = {"Fib": 0, "AVWAP": 1, "MA": 2, "Horiz": 3}
    levels.sort(key=lambda L: (round(L["price"], 2), type_priority.get(L["type"], 9)))
    deduped = []
    for L in levels:
        if deduped and abs(deduped[-1]["price"] - L["price"]) / max(L["price"], 1) < 0.0005:
            continue  # already have this price with higher-priority type
        deduped.append(L)
    levels = deduped

    # ── Step 2: cluster levels by proximity ──
    levels.sort(key=lambda L: -L["price"])
    proximity = max(0.015 * px, 0.5 * atr if atr > 0 else 0)
    clusters = []
    for L in levels:
        if clusters and abs(clusters[-1]["levels"][-1]["price"] - L["price"]) <= proximity:
            clusters[-1]["levels"].append(L)
        else:
            clusters.append({"levels": [L]})

    # ── Step 3: score each cluster ──
    # FibX (unverified Fib) counts at half-type-weight: 1 point instead of 2.
    # Triple-confluence bonus still requires validated Fib (not FibX).
    for cluster in clusters:
        types = set(L["type"] for L in cluster["levels"])
        n_levels = len(cluster["levels"])
        prices = [L["price"] for L in cluster["levels"]]
        cluster["types"] = types
        cluster["n_levels"] = n_levels
        cluster["avg_price"] = sum(prices) / len(prices)
        cluster["cluster_low"] = min(prices)
        cluster["cluster_high"] = max(prices)
        cluster["pullback_pct"] = (px - cluster["avg_price"]) / px * 100
        # Type points: validated types (Fib/AVWAP/MA/Horiz) = 2 each; FibX = 1
        score = 0
        for t in types:
            score += 1 if t == "FibX" else 2
        score += n_levels
        if {"Fib", "MA", "AVWAP"}.issubset(types):
            score += 1  # validated triple-confluence bonus
        if cluster["pullback_pct"] > 15:
            score -= 1
        cluster["score"] = score

    # ── INSUFFICIENT_STRUCTURE: only one level total ──
    total_levels = sum(c["n_levels"] for c in clusters)
    if total_levels <= 1:
        return {
            "action": "INSUFFICIENT_STRUCTURE",
            "note": "less data — wait for clearer structure to form",
        }

    # Pick best cluster (highest score; tie-break by closest to price)
    clusters.sort(key=lambda c: (-c["score"], -c["avg_price"]))
    best = clusters[0]
    deeper = clusters[1:]

    entry_price = round(best["avg_price"], 2)
    pullback_pct = best["pullback_pct"]
    types = best["types"]
    n_levels = best["n_levels"]
    n_types = len(types)
    confluence_desc = " + ".join(L["desc"] for L in best["levels"][:4])

    # If cluster is too far below (>15%) → STRATEGY rather than WAIT (per plan)
    if pullback_pct > 15:
        ema21_val = next((v for n, v in ma_candidates if n == "EMA21"), None)
        sma50_val = next((v for n, v in ma_candidates if n == "SMA50"), None)
        parts = []
        if ema21_val: parts.append(f"EMA21 ~${ema21_val:.2f}")
        if sma50_val: parts.append(f"SMA50 ~${sma50_val:.2f}")
        targets = " or ".join(parts) if parts else f"~${entry_price:.2f}"
        return {
            "action": "STRATEGY",
            "strategy_text": (f"watch for low-vol pullback to test {targets} "
                              f"(strongest cluster ${entry_price:.2f} is {pullback_pct:.1f}% below px); "
                              "on bullish reversal candle stab 10-15% with stop below tested MA × 0.985"),
        }

    # ── Step 4: size the stab ──
    if n_types >= 4:
        base_stab = 28
    elif n_types == 3:
        base_stab = 22
    elif n_types == 2:
        base_stab = 16
    elif n_levels >= 2:
        base_stab = 12
    else:
        # Single level (only 1 cluster with 1 level — but we already handled total=1 above)
        base_stab = 10

    stab = base_stab
    flags = []
    if not np.isnan(rsi):
        if rsi < 45: stab += 3
        elif rsi > 70: stab -= 5
    try:
        rr_v = float(best_rr) if best_rr else 0
        if rr_v >= 3.0: stab += 3
        elif rr_v < 1.5: stab -= 5
    except (ValueError, TypeError):
        pass

    if vol_info.get("low_liquidity"):
        stab = min(stab, 12)
        flags.append("LOW-LIQ")
    if entry_cls == "BROKEN_DOWN" and composite_class in {"GOOD ENTRY", "PRIME ENTRY"}:
        stab = min(stab, 20)
        flags.append("BROKEN-DN")
    stab = max(10, min(30, stab))

    # ── Step 5: stops ──
    cluster_low = best["cluster_low"]
    if abs(px - cluster_low) / px < 0.01:
        tight_stop = entry_price - atr
    else:
        tight_stop = cluster_low - 0.5 * atr

    # SMA200 snap (uptrend)
    if len(c) >= 200:
        sma200_val = float(bs.sma(c, 200).iloc[-1])
        if px > sma200_val and tight_stop < sma200_val:
            tight_stop = sma200_val + 0.25 * atr

    # Floor at 1.5% risk
    floor_stop = entry_price * 0.985
    tight_stop = min(tight_stop, floor_stop)
    tight_stop = round(tight_stop, 2)
    tight_risk = (entry_price - tight_stop) / entry_price * 100

    if tight_risk > 6:
        flags.append("WIDE-STOP")

    # Worst-case stop
    worst_stop = None
    worst_note = ""
    for d in deeper:
        if d["score"] >= 4 and d["avg_price"] <= tight_stop * 0.98:
            worst_stop = round(d["cluster_low"] - 0.5 * atr, 2)
            break
    if worst_stop is None and fib_d and "100.0%" in fib_d["levels"]:
        fib_100 = fib_d["levels"]["100.0%"]
        if fib_100 < tight_stop:
            worst_stop = round(fib_100 - 0.5 * atr, 2)
    if worst_stop is None:
        worst_stop = round(entry_price - 2 * atr, 2)
        worst_note = "ATR-based, no deeper support"

    if worst_stop >= tight_stop:
        worst_stop = round(tight_stop - atr, 2)
        worst_note = "forced wider than tight stop"
    worst_risk = (entry_price - worst_stop) / entry_price * 100

    # ── Step 6: action ──
    action = "BUY-LIMIT" if pullback_pct < 5 else "WAIT"

    return {
        "action": action,
        "entry_price": entry_price,
        "stab_pct": stab,
        "tight_stop": tight_stop,
        "tight_risk_pct": round(tight_risk, 1),
        "worst_stop": worst_stop,
        "worst_risk_pct": round(worst_risk, 1),
        "worst_note": worst_note,
        "confluence_count": n_levels,
        "confluence_types": sorted(types),
        "confluence_desc": confluence_desc,
        "flags": flags,
        "pullback_pct": round(pullback_pct, 1),
    }


def fmt_first_phase_table(results: list[dict]) -> str:
    """Side-by-side table of first-phase entry recommendations."""
    lines = []
    lines.append("\n══════════════════════════════════════════")
    lines.append("FIRST-PHASE ENTRY RECOMMENDATIONS (stab 10-30%)")
    lines.append("══════════════════════════════════════════")
    header = (f"{'Ticker':<6} {'Current':>9} {'Action':<11} {'Entry':>9} {'Stab':>5} "
              f"{'TightStop':>10} {'Risk%':>6} {'WorstStop':>10} {'Worst%':>7}  {'Flags':<11} Confluence / Note")
    lines.append(header)
    lines.append("─" * len(header))
    strategy_rows = []
    for r in sorted(results, key=lambda x: -x["score"]):
        rec = r.get("first_phase")
        if rec is None:
            continue
        ticker = r["ticker"]
        px = r["price"]
        action = rec["action"]
        if action in {"STRATEGY", "INSUFFICIENT_STRUCTURE", "AVOID"}:
            note = rec.get("strategy_text") or rec.get("note") or ""
            strategy_rows.append((ticker, px, action, note))
            continue
        ep = rec["entry_price"]
        stab = rec["stab_pct"]
        ts = rec["tight_stop"]
        tr = rec["tight_risk_pct"]
        ws = rec["worst_stop"]
        wr = rec["worst_risk_pct"]
        flags_str = ",".join(rec.get("flags", [])) if rec.get("flags") else "—"
        conf = rec["confluence_desc"]
        if rec.get("worst_note"):
            conf = conf + f"  ({rec['worst_note']})"
        lines.append(
            f"{ticker:<6} ${px:>8.2f} {action:<11} ${ep:>8.2f} {stab:>4}% "
            f"${ts:>9.2f} {tr:>5.1f}% ${ws:>9.2f} {wr:>6.1f}%  {flags_str:<11} {conf}"
        )
    # Strategy / insufficient / avoid rows at the bottom, full-width notes
    for ticker, px, action, note in strategy_rows:
        lines.append(f"{ticker:<6} ${px:>8.2f} {action:<11} {'—':>9} {'—':>5} {'—':>10} {'—':>6} {'—':>10} {'—':>7}  {'—':<11} {note}")
    return "\n".join(lines)


# ── Chart Rendering ──────────────────────────────────────────────────────────

DARK_BG = "#1a1a2e"
GRID = "#2c2c44"


def render_chart(r: dict) -> io.BytesIO:
    daily = r["daily_df"].tail(252)   # 1 year daily
    weekly = r["weekly_df"].tail(156) if r["weekly_df"] is not None else None  # 3y weekly
    monthly = r["monthly_df"].tail(60) if r["monthly_df"] is not None else None  # 5y monthly

    rows = 3 if (weekly is not None and monthly is not None) else (2 if weekly is not None else 1)
    fig = plt.figure(figsize=(13, 4.5 * rows + 1.5), facecolor=DARK_BG)

    # === Panel 1: Daily ===
    ax_d = fig.add_subplot(rows, 1, 1)
    ax_d.set_facecolor(DARK_BG)
    ax_d.plot(daily.index, daily["Close"], color="#ffffff", linewidth=1.5, label="Close")
    ax_d.plot(daily.index, bs.ema(daily["Close"], 21), color="#5dade2", linewidth=1, label="EMA21", alpha=0.8)
    ax_d.plot(daily.index, bs.sma(daily["Close"], 50), color="#f39c12", linewidth=1, label="SMA50", alpha=0.8)
    if len(r["daily_df"]) >= 200:
        sma200 = bs.sma(r["daily_df"]["Close"], 200)
        ax_d.plot(daily.index, sma200.loc[daily.index], color="#e74c3c", linewidth=1, label="SMA200", alpha=0.8)
    # 30wk SMA — bold
    if r["sma30"]["valid"]:
        sma30s = r["sma30"]["series"]
        ax_d.plot(daily.index, sma30s.loc[daily.index].values, color="#9b59b6", linewidth=2.2, label="30wk SMA (Minervini)")
    # Best AVWAP
    if r["avwap"]["best"]:
        idx, s = r["avwap"]["anchors"][r["avwap"]["best"]]
        s_in = s[s.index.isin(daily.index)]
        ax_d.plot(s_in.index, s_in.values, color="#1abc9c", linewidth=1.8, linestyle="--",
                  label=f"AVWAP ({r['avwap']['best']})")
    # Fibonacci levels — bold for validated "important" levels, thin/dim otherwise
    if r["fib_d"]:
        important = set((r["fib_d"].get("validation") or {}).get("important_levels") or [])
        for lab, lvl in r["fib_d"]["levels"].items():
            if lab in important:
                ax_d.axhline(lvl, color="#f39c12", linewidth=1.4, linestyle="--", alpha=0.95)
                ax_d.text(daily.index[-1], lvl, f" {lab} ★", color="#f39c12", fontsize=8, va="center", fontweight="bold")
            else:
                ax_d.axhline(lvl, color="#f1c40f", linewidth=0.5, linestyle=":", alpha=0.45)
                ax_d.text(daily.index[-1], lvl, f" {lab}", color="#f1c40f", fontsize=7, va="center", alpha=0.6)
    cls_color = {"PRIME ENTRY": "#2ecc71", "GOOD ENTRY": "#3498db",
                 "MIXED": "#f1c40f", "AVOID": "#e74c3c"}.get(r["class"], "#ffffff")
    ax_d.set_title(f"{r['ticker']}  ${r['price']:.2f}   [{r['class']}]  score {r['score']}/100",
                   color=cls_color, fontsize=12, fontweight="bold")
    ax_d.legend(loc="upper left", facecolor=DARK_BG, edgecolor=GRID, labelcolor="#ffffff", fontsize=8)
    ax_d.grid(True, color=GRID, alpha=0.5)
    ax_d.tick_params(colors="#ffffff")
    ax_d.set_ylabel("Daily (1y)", color="#ffffff")

    # === Panel 2: Weekly ===
    if weekly is not None:
        ax_w = fig.add_subplot(rows, 1, 2)
        ax_w.set_facecolor(DARK_BG)
        ax_w.plot(weekly.index, weekly["Close"], color="#ffffff", linewidth=1.5, label="Close")
        if len(r["weekly_df"]) >= 10:
            ax_w.plot(weekly.index, bs.sma(r["weekly_df"]["Close"], 10).loc[weekly.index].values, color="#5dade2", linewidth=1.2, label="SMA10wk")
        if len(r["weekly_df"]) >= 20:
            ax_w.plot(weekly.index, bs.sma(r["weekly_df"]["Close"], 20).loc[weekly.index].values, color="#f39c12", linewidth=1.2, label="SMA20wk")
        if len(r["weekly_df"]) >= 40:
            ax_w.plot(weekly.index, bs.sma(r["weekly_df"]["Close"], 40).loc[weekly.index].values, color="#e74c3c", linewidth=1.2, label="SMA40wk")
        if r["fib_w"]:
            for lab, lvl in r["fib_w"]["levels"].items():
                ax_w.axhline(lvl, color="#f1c40f", linewidth=0.5, linestyle=":", alpha=0.5)
        ax_w.legend(loc="upper left", facecolor=DARK_BG, edgecolor=GRID, labelcolor="#ffffff", fontsize=8)
        ax_w.grid(True, color=GRID, alpha=0.5)
        ax_w.tick_params(colors="#ffffff")
        ax_w.set_ylabel("Weekly (3y)", color="#ffffff")

    # === Panel 3: Monthly ===
    if monthly is not None and rows == 3:
        ax_m = fig.add_subplot(rows, 1, 3)
        ax_m.set_facecolor(DARK_BG)
        ax_m.plot(monthly.index, monthly["Close"], color="#ffffff", linewidth=1.5, label="Close")
        if len(r["monthly_df"]) >= 6:
            ax_m.plot(monthly.index, bs.sma(r["monthly_df"]["Close"], 6).loc[monthly.index].values, color="#5dade2", linewidth=1.2, label="SMA6mo")
        if len(r["monthly_df"]) >= 12:
            ax_m.plot(monthly.index, bs.sma(r["monthly_df"]["Close"], 12).loc[monthly.index].values, color="#f39c12", linewidth=1.2, label="SMA12mo")
        ax_m.legend(loc="upper left", facecolor=DARK_BG, edgecolor=GRID, labelcolor="#ffffff", fontsize=8)
        ax_m.grid(True, color=GRID, alpha=0.5)
        ax_m.tick_params(colors="#ffffff")
        ax_m.set_ylabel("Monthly (5y)", color="#ffffff")

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", facecolor=DARK_BG, dpi=110)
    plt.close(fig)
    buf.seek(0)
    return buf


# ── Main ─────────────────────────────────────────────────────────────────────

def fetch_all_frames(ticker: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    daily = bs.fetch_ohlcv(ticker, "2y", "1d")
    if daily is None:
        return None, None, None
    # Weekly: resample daily 5y
    weekly_raw = bs.fetch_ohlcv(ticker, "5y", "1d")
    if weekly_raw is not None and len(weekly_raw) >= 50:
        weekly = weekly_raw.resample("W").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum"
        }).dropna()
    else:
        weekly = None
    # Monthly: direct fetch at interval=1mo
    monthly = bs.fetch_ohlcv(ticker, "10y", "1mo")
    if monthly is not None and len(monthly) < 13:
        # Fallback: resample 5y daily to monthly
        if weekly_raw is not None:
            monthly = weekly_raw.resample("ME").agg({
                "Open": "first", "High": "max", "Low": "min",
                "Close": "last", "Volume": "sum"
            }).dropna()
    return daily, weekly, monthly


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="*", help="Ticker symbols")
    args = parser.parse_args()
    tickers = load_tickers(args.tickers)
    if not tickers:
        print("No tickers provided.")
        return

    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}  entry-analyzer  ({len(tickers)} tickers)")
    results = []
    for t in tickers:
        print(f"\nProcessing {t}...")
        daily, weekly, monthly = fetch_all_frames(t)
        if daily is None or len(daily) < 100:
            print(f"  {t}: DATA_ERROR — fetch failed or insufficient history")
            continue
        try:
            r = analyze(t, daily, weekly, monthly)
            attach_first_phase(r)
            results.append(r)
            text = fmt_text_report(r)
            print("\n" + text)
            send_discord_text("```\n" + text + "\n```")
            chart = render_chart(r)
            send_discord_image(chart, f"{t}_entry.png")
        except Exception as e:
            print(f"  {t}: analysis failed — {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)

    if results:
        summary = fmt_summary_table(results)
        print(summary)
        send_discord_text("```\n" + summary + "\n```")
        first_phase = fmt_first_phase_table(results)
        print(first_phase)
        send_discord_text("```\n" + first_phase + "\n```")

    print(f"\n{datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}  entry-analyzer complete")


if __name__ == "__main__":
    main()
