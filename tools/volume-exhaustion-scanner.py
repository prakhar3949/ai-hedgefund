"""
Volume Exhaustion Scanner — Capitulation / Blowoff / Waning regime classifier.

Classical volume analysis (Wyckoff, VSA, O'Neil, Granville, Lo & Wang turnover):
  - CAPITULATION (CONFIRMED / FORMING / WATCH / FAILED): Wyckoff SC → AR → ST
    sequence detected across a 180-session lookback, with multi-SC tracking
    and a Spring/late-bear-shakeout fallback that catches Mar-2009-style
    bottoms where the original SC happened months earlier but the actual low
    formed on lighter vol (a Spring back above prior support).
  - BLOWOFF (TOP_RISK / WATCH): wide-range bearish reversal candle in
    EXTENDED_UPTREND. TOP_RISK if vol-spike or parabolic context; WATCH if
    just the candle pattern (vol baseline can be inflated after months of
    elevated activity).
  - WANING (WARNING / WATCH): the Granville/VSA "everyone who can buy has
    bought" pattern. WATCH if core c1+c2 fire (price up + vol declining);
    WARNING if at least one of c3 (up/down ratio deteriorating) or c4 (CMF
    declining) also fires.

Vol baseline is the 180-day rolling MEDIAN — robust to crash-period
contamination that breaks rolling-mean ratios.

Universe modes:
  - No CLI args → daily scan: watchlist.json ∪ discovery-output.json (drops ETFs)
  - CLI args   → scan only those tickers (used by run-ticker.py)

Stage 2 (this version): Modules 1-5 + 7. Validated against 18 historical events
(GFC, COVID, dot-com bear, 1974 oil-shock, dot-com peaks, distribution tops) at
16/18 = 89% pass rate. OI layer (Module 6) is the next milestone.
"""

import io
import json
import re
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
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

from market_utils import yahoo_quote_summary

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1508730602189488209/"
    "1OKp8ofZ3oN_8xUOfqgqNlIf7Nd26pdrB0_T8Y7HHRsmpM3E7ePApunw20JK6YD4h7IF"
)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

SHARES_CACHE_PATH = TOOLS_DIR / "shares-outstanding-cache.json"
SHARES_CACHE_TTL_DAYS = 7

OI_HISTORY_PATH = TOOLS_DIR / "oi-history.json"
OI_HISTORY_TRIM_DAYS = 60        # keep at most 60 daily snapshots per ticker
OI_MIN_CONTRACTS = 10            # filter open-interest noise
OI_SURGE_THRESHOLD = 0.25        # ≥ +25% 5d change in side-specific OI
OI_TREND_THRESHOLD = 0.10        # ≥ ±10% 5d change qualifies INCREASING/DECREASING
CBOE_URL_TEMPLATE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"

MEGA_CAP_THRESHOLD = 500e9       # $500B
DOWNTREND_DRAWDOWN = 0.20        # ≥ 20% from 1y high
EXTENDED_SMA_MULT = 1.30         # close > 1.30 × SMA200
EXTENDED_STDEV_MULT = 2.0        # close > SMA200 + 2σ
EXTENDED_60D_GAIN = 0.50         # +50% in 60 sessions
VOL_SPIKE_RATIO = 1.5            # today's vol > 1.5× robust baseline (180d median). Calibrated
                                 # against SPY Mar 23 2020 / Oct 10 2008 / CSCO 2000 peaks. 2.5×
                                 # was textbook-strict but missed actual events. 180d median is
                                 # robust to crash-period contamination (rolling means inflate
                                 # during prolonged crashes; median doesn't).
VOL_PCT_60D = 90                 # ≥ 90th percentile of trailing 60d (alternative spike trigger)
RANGE_ATR = 1.5                  # wide-range bar threshold (was 2.0; relaxed for same reason)
VOL_BASELINE_WINDOW = 180        # rolling-median window for vol baseline
SC_LOOKBACK = 180                # Stage 2: walk back this many sessions for SC candidates
                                 # (was 30 — too narrow; late-bear bottoms test of original SC
                                 # 60-150d after the SC happened).
TURNOVER_PCT_THRESHOLD = 95      # capitulation/blowoff threshold
SPLIT_SUSPECT_RATIO = 5.0        # 5× day-over-day volume jump = suspect

# AR window — market-cap aware
AR_WINDOW_NON_MEGA = 5
AR_WINDOW_MEGA = 10
AR_REBOUND_THRESHOLD = 0.05      # +5% above SC_low
ST_WINDOW = 30                   # universal — same for all caps
ST_PROXIMITY = 0.03              # within 3% of SC_low
ST_VOL_RATIO = 0.7               # ST volume < SC_volume × 0.7

# Waning gate thresholds
WANING_PRICE_30D = 0.05          # ≥ +5% over last 30 sessions
WANING_VOL_SLOPE = 0             # slope must be negative

# Idiosyncratic gate (stress test 8)
IDIOSYNCRATIC_Z_MIN = 1.0        # ticker vol z-score - SPY vol z-score ≥ 1.0

# Known index-reconstitution dates (stress test 6) — fill in as needed.
# Format: list of (year, month, day) tuples.
RECON_DATES_2026 = [
    (2026, 3, 20),   # S&P quarterly rebalance (3rd Friday of Mar)
    (2026, 6, 19),   # S&P quarterly (3rd Friday of Jun)
    (2026, 6, 26),   # Russell annual rebal (4th Friday of Jun)
    (2026, 9, 18),   # S&P quarterly (3rd Friday of Sep)
    (2026, 12, 18),  # S&P quarterly (3rd Friday of Dec)
]
RECON_DATES = [date(y, m, d) for (y, m, d) in RECON_DATES_2026]
RECON_WINDOW_DAYS = 2


# ── Discord ──────────────────────────────────────────────────────────────────

def send_discord_text(text: str):
    if not DISCORD_WEBHOOK_URL:
        return
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
            print(f"  Discord text failed: {e}", file=sys.stderr)


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
        print(f"  Discord image failed: {e}", file=sys.stderr)


# ── Data fetch ───────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame | None:
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
        if len(df) < 60:
            return None
        return df
    except Exception:
        return None


def batch_fetch(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    out = {}
    bsize = 40
    for i in range(0, len(tickers), bsize):
        batch = tickers[i:i + bsize]
        if i > 0:
            time.sleep(2)
        with ThreadPoolExecutor(max_workers=5) as pool:
            fut = {pool.submit(fetch_ohlcv, t): t for t in batch}
            for f in as_completed(fut):
                t = fut[f]
                try:
                    df = f.result()
                    if df is not None:
                        out[t] = df
                except Exception:
                    pass
    return out


def load_shares_cache() -> dict:
    if not SHARES_CACHE_PATH.exists():
        return {}
    try:
        with open(SHARES_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_shares_cache(cache: dict):
    try:
        with open(SHARES_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"  shares cache save failed: {e}", file=sys.stderr)


def fetch_oi_snapshot(ticker: str) -> dict | None:
    """
    Fetch CBOE delayed-quote chain for `ticker` and aggregate today's OI.
    Returns:
        {
          "date": "YYYY-MM-DD",
          "total_call_oi": int,
          "total_put_oi": int,
          "put_call_oi_ratio": float,
          "top_call_strikes": [(strike, oi), ...top 5],
          "top_put_strikes": [(strike, oi), ...top 5],
        }
    Returns None if CBOE has no chain for the ticker (small caps, no listed
    options) or fetch fails. Uses the same pattern as gex-profile-equity.py.
    """
    try:
        url = CBOE_URL_TEMPLATE.format(ticker=ticker)
        r = requests.get(url, headers=YAHOO_HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        payload = r.json()
    except Exception:
        return None

    data = payload.get("data") or {}
    options = data.get("options") or []
    if not options:
        return None

    # Symbol regex matches equity option contracts like 'AAPL260618C00185000'
    # and weeklies 'AAPLW260612C...'
    symbol_re = re.compile(
        rf"^{re.escape(ticker)}[W]?(\d{{2}})(\d{{2}})(\d{{2}})([CP])(\d{{8}})$"
    )

    call_oi_by_strike: dict[float, int] = {}
    put_oi_by_strike: dict[float, int] = {}
    for opt in options:
        sym = opt.get("option", "")
        m = symbol_re.match(sym)
        if not m:
            continue
        _, _, _, cp, strike_raw = m.groups()
        try:
            strike = int(strike_raw) / 1000.0
        except ValueError:
            continue
        oi = opt.get("open_interest")
        if oi is None or oi < OI_MIN_CONTRACTS:
            continue
        bucket = call_oi_by_strike if cp == "C" else put_oi_by_strike
        bucket[strike] = bucket.get(strike, 0) + int(oi)

    total_call_oi = sum(call_oi_by_strike.values())
    total_put_oi = sum(put_oi_by_strike.values())
    if total_call_oi == 0 and total_put_oi == 0:
        return None

    pc_ratio = (total_put_oi / total_call_oi) if total_call_oi > 0 else None
    top_calls = sorted(call_oi_by_strike.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_puts = sorted(put_oi_by_strike.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return {
        "date": date.today().isoformat(),
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "put_call_oi_ratio": round(pc_ratio, 4) if pc_ratio is not None else None,
        "top_call_strikes": [(s, o) for s, o in top_calls],
        "top_put_strikes": [(s, o) for s, o in top_puts],
    }


def load_oi_history() -> dict:
    if not OI_HISTORY_PATH.exists():
        return {}
    try:
        with open(OI_HISTORY_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_oi_history(history: dict):
    try:
        with open(OI_HISTORY_PATH, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"  oi history save failed: {e}", file=sys.stderr)


def append_oi_snapshot(history: dict, ticker: str, snapshot: dict):
    """Append today's snapshot, deduping by date, trimming to OI_HISTORY_TRIM_DAYS."""
    series = history.get(ticker, [])
    today = snapshot["date"]
    # Drop any prior entry with the same date (re-run idempotency)
    series = [s for s in series if s.get("date") != today]
    series.append(snapshot)
    # Sort by date ascending, trim
    series.sort(key=lambda s: s.get("date", ""))
    if len(series) > OI_HISTORY_TRIM_DAYS:
        series = series[-OI_HISTORY_TRIM_DAYS:]
    history[ticker] = series


def compute_oi_metrics(ticker: str, history: dict) -> dict | None:
    """
    Compute % change metrics from the stored history series.
    Requires at least 2 snapshots; returns None otherwise.

    Returns dict with:
      oi_pct_change_1d / 5d / 20d
      call_oi_pct_change_5d, put_oi_pct_change_5d
      put_call_ratio_delta (vs 20d avg)
      oi_trend ∈ {INCREASING, DECREASING, FLAT}
      call_oi_surge: bool
      put_oi_surge: bool
    """
    series = history.get(ticker, [])
    if len(series) < 2:
        return None

    today = series[-1]
    today_total = today["total_call_oi"] + today["total_put_oi"]
    if today_total <= 0:
        return None

    def lookback(n: int) -> dict | None:
        return series[-1 - n] if len(series) > n else None

    def pct(now: float, then: float | None) -> float | None:
        if then is None or then <= 0:
            return None
        return round((now / then) - 1, 4)

    d1 = lookback(1)
    d5 = lookback(5)
    d20 = lookback(20)

    d1_total = (d1["total_call_oi"] + d1["total_put_oi"]) if d1 else None
    d5_total = (d5["total_call_oi"] + d5["total_put_oi"]) if d5 else None
    d20_total = (d20["total_call_oi"] + d20["total_put_oi"]) if d20 else None

    oi_pct_1d = pct(today_total, d1_total)
    oi_pct_5d = pct(today_total, d5_total)
    oi_pct_20d = pct(today_total, d20_total)

    call_pct_5d = pct(today["total_call_oi"], d5["total_call_oi"]) if d5 else None
    put_pct_5d = pct(today["total_put_oi"], d5["total_put_oi"]) if d5 else None

    # 20-day average put/call ratio
    pc_series = [s.get("put_call_oi_ratio") for s in series[-20:] if s.get("put_call_oi_ratio") is not None]
    pc_20d_avg = (sum(pc_series) / len(pc_series)) if pc_series else None
    pc_today = today.get("put_call_oi_ratio")
    pc_delta = None
    if pc_today is not None and pc_20d_avg is not None:
        pc_delta = round(pc_today - pc_20d_avg, 4)

    # Derived flags
    if oi_pct_5d is None:
        oi_trend = "FLAT"
    elif oi_pct_5d > OI_TREND_THRESHOLD:
        oi_trend = "INCREASING"
    elif oi_pct_5d < -OI_TREND_THRESHOLD:
        oi_trend = "DECREASING"
    else:
        oi_trend = "FLAT"

    call_surge = (call_pct_5d is not None) and (call_pct_5d > OI_SURGE_THRESHOLD)
    put_surge = (put_pct_5d is not None) and (put_pct_5d > OI_SURGE_THRESHOLD)

    return {
        "oi_pct_change_1d": oi_pct_1d,
        "oi_pct_change_5d": oi_pct_5d,
        "oi_pct_change_20d": oi_pct_20d,
        "call_oi_pct_change_5d": call_pct_5d,
        "put_oi_pct_change_5d": put_pct_5d,
        "put_call_ratio_today": pc_today,
        "put_call_ratio_20d_avg": round(pc_20d_avg, 4) if pc_20d_avg is not None else None,
        "put_call_ratio_delta": pc_delta,
        "oi_trend": oi_trend,
        "call_oi_surge": call_surge,
        "put_oi_surge": put_surge,
        "snapshots_in_history": len(series),
    }


def get_shares_outstanding(ticker: str, cache: dict) -> float | None:
    today = date.today().isoformat()
    entry = cache.get(ticker)
    if entry:
        fetched = entry.get("fetched_at", "1970-01-01")
        try:
            age_days = (date.fromisoformat(today) - date.fromisoformat(fetched)).days
            if age_days < SHARES_CACHE_TTL_DAYS and entry.get("shares_outstanding"):
                return float(entry["shares_outstanding"])
        except Exception:
            pass
    summary = yahoo_quote_summary(ticker, "defaultKeyStatistics", timeout=15)
    if not summary:
        return None
    ks = summary.get("defaultKeyStatistics", {}) or {}
    shares = (ks.get("sharesOutstanding") or {}).get("raw")
    if shares:
        cache[ticker] = {"shares_outstanding": shares, "fetched_at": today}
        return float(shares)
    return None


# ── Indicators ───────────────────────────────────────────────────────────────

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def vol_baseline_series(volume: pd.Series, window: int = VOL_BASELINE_WINDOW) -> pd.Series:
    """
    Robust rolling baseline for volume — median over `window` sessions.
    Median is robust to crash-period contamination, unlike a rolling mean
    which gets inflated by extreme days and stops being a useful reference.
    """
    return volume.rolling(window, min_periods=max(30, window // 2)).median()


def cmf_series(df: pd.DataFrame, n: int = 20) -> pd.Series:
    h, l, c, v = df["High"], df["Low"], df["Close"], df["Volume"]
    rng = (h - l).replace(0, np.nan)
    mfm = ((c - l) - (h - c)) / rng
    mfv = mfm * v
    return mfv.rolling(n).sum() / v.rolling(n).sum().replace(0, np.nan)


def percentile_rank(value: float, series: pd.Series) -> float:
    s = series.dropna()
    if len(s) == 0:
        return float("nan")
    return float((s < value).sum() / len(s) * 100)


def regression_slope(values: np.ndarray) -> float:
    """Linear-regression slope over array values (x = 0..n-1)."""
    if len(values) < 3:
        return 0.0
    x = np.arange(len(values))
    return float(np.polyfit(x, values, 1)[0])


# ── Universe construction ────────────────────────────────────────────────────

ETF_PREFIXES = {
    # CW sector ETFs
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLC", "XLB", "XLRE",
    # EW sector ETFs
    "RSPT", "RSPF", "RSPG", "RSPH", "RSPN", "RSPS", "RSPD", "RSPU", "RSPC", "RSPM", "RSPR",
    # Common subsector ETFs
    "SMH", "SOXX", "KRE", "KBE", "IBB", "XBI", "ITA", "XRT", "XHB", "XOP", "OIH",
    "GDX", "GDXJ", "URA", "LIT", "TAN", "ICLN", "JETS", "MOO", "PEJ", "PHO", "CIBR",
    "HACK", "ROBO", "BOTZ", "ARKK", "ARKW", "ARKG", "ARKF", "ARKQ",
    # Benchmarks
    "SPY", "QQQ", "IWM", "DIA", "RSP", "VTI", "VOO",
}


def load_universe(cli_tickers: list[str]) -> tuple[list[str], str]:
    """Return (tickers, mode_description). mode = 'cli' or 'daily'."""
    if cli_tickers:
        cleaned = []
        for t in cli_tickers:
            t = t.upper().lstrip("$").strip()
            if t:
                cleaned.append(t)
        # Dedupe while preserving order
        seen = set()
        uniq = [t for t in cleaned if not (t in seen or seen.add(t))]
        return uniq, f"cli ({len(uniq)} tickers)"

    universe: set[str] = set()

    watchlist_path = TOOLS_DIR / "watchlist.json"
    if watchlist_path.exists():
        with open(watchlist_path) as f:
            wl = json.load(f)
        for t in wl.get("tickers", []):
            universe.add(t.upper())

    discovery_path = TOOLS_DIR / "discovery-output.json"
    discovery_count = 0
    if discovery_path.exists():
        try:
            with open(discovery_path) as f:
                data = json.load(f)
            for tickers in data.get("top_picks", {}).values():
                for t in tickers:
                    universe.add(t.upper())
                    discovery_count += 1
        except Exception as e:
            print(f"  discovery-output read failed: {e}", file=sys.stderr)

    universe = {t for t in universe if t not in ETF_PREFIXES}

    cleaned = sorted(universe)
    if len(cleaned) > 100:
        cleaned = cleaned[:100]

    mode = f"daily (watchlist + {discovery_count} discovery → {len(cleaned)} unique)"
    return cleaned, mode


# ── Module 1: Price Regime Classification ────────────────────────────────────

def classify_regime(df: pd.DataFrame) -> str:
    close = df["Close"]
    price = close.iloc[-1]
    n = len(df)

    high_1y = close.iloc[-min(252, n):].max()
    drawdown = (price / high_1y) - 1

    sma200 = sma(close, 200).iloc[-1] if n >= 200 else np.nan
    sma50 = sma(close, 50).iloc[-1] if n >= 50 else np.nan

    if not np.isnan(sma200) and drawdown <= -DOWNTREND_DRAWDOWN and price < sma200:
        return "DOWNTREND"

    if not np.isnan(sma200):
        stdev200 = float(close.iloc[-200:].std())
        gain_60d = (price / close.iloc[-min(60, n - 1)]) - 1
        if (price > sma200 * EXTENDED_SMA_MULT
                or price > sma200 + EXTENDED_STDEV_MULT * stdev200
                or gain_60d >= EXTENDED_60D_GAIN):
            return "EXTENDED_UPTREND"

    if not np.isnan(sma200) and not np.isnan(sma50) and price > sma200 and sma50 > sma200:
        return "STEADY_UPTREND"

    return "CHOP"


# ── Module 2: Volume Swell Detection ─────────────────────────────────────────

def detect_volume_swell(df: pd.DataFrame, regime: str) -> dict:
    """Classify today's bar — capitulation, blowoff, neutral spike, or none."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    open_ = df["Open"]
    volume = df["Volume"]
    n = len(df)

    today_vol = float(volume.iloc[-1])
    # Robust baseline: 180-day median (immune to crash-period inflation that
    # ruins rolling means). Falls back to 60-day mean if not enough history.
    baseline_series = vol_baseline_series(volume)
    baseline = float(baseline_series.iloc[-1])
    if np.isnan(baseline) or baseline <= 0:
        if n >= 60:
            baseline = float(volume.iloc[-60:].mean())
        else:
            return {"bar_type": "NONE", "reason": "no avg vol"}

    vol_ratio = today_vol / baseline
    vol_pct = percentile_rank(today_vol, volume.iloc[-60:])
    today_atr = float(atr(df, 14).iloc[-1])
    today_range = float(high.iloc[-1] - low.iloc[-1])
    range_atr = today_range / today_atr if today_atr > 0 else 0

    is_spike = vol_ratio >= VOL_SPIKE_RATIO or vol_pct >= VOL_PCT_60D
    is_wide_range = range_atr >= RANGE_ATR

    today_close = float(close.iloc[-1])
    today_open = float(open_.iloc[-1])
    today_high = float(high.iloc[-1])
    today_low = float(low.iloc[-1])
    midpoint = (today_high + today_low) / 2
    body = abs(today_close - today_open)
    upper_shadow = today_high - max(today_close, today_open)
    lower_shadow = min(today_close, today_open) - today_low

    prev_open = float(open_.iloc[-2]) if n >= 2 else today_open
    prev_close = float(close.iloc[-2]) if n >= 2 else today_close

    is_hammer = (lower_shadow > body * 2) and (today_close > midpoint)
    is_bullish_engulfing = (today_close > prev_open) and (today_open < prev_close) and (today_close > today_open)
    # Looser practical filter: close in upper half AND green bar. Real index
    # capitulation bars (Oct 10 2008 SPY, Mar 24 2020 SPY) are wide-range green
    # bars that don't always fit textbook hammer/engulfing geometry.
    upper_half_green = (today_close > midpoint) and (today_close > today_open)
    bullish_reversal = is_hammer or is_bullish_engulfing or upper_half_green

    is_shooting_star = (upper_shadow > body * 2) and (today_close < midpoint)
    is_bearish_engulfing = (today_close < prev_open) and (today_open > prev_close) and (today_close < today_open)
    parabolic_close = (today_close < (today_low + today_range / 3)) if today_range > 0 else False
    lower_half_red = (today_close < midpoint) and (today_close < today_open)
    bearish_reversal = is_shooting_star or is_bearish_engulfing or parabolic_close or lower_half_red

    # Parabolic context: % gain over last 30 sessions. Pre-blowoff tops often
    # follow a vertical advance; this gives confidence to blowoff classification
    # even when vol-ratio is deflated by months of preceding elevated activity.
    gain_30d = (float(close.iloc[-1]) / float(close.iloc[-31]) - 1) if n >= 31 else 0
    parabolic_30d = gain_30d >= 0.20  # ≥ +20% in 30d

    base = {
        "vol_ratio": round(vol_ratio, 2),
        "vol_pct_60d": round(vol_pct, 1),
        "range_atr": round(range_atr, 2),
        "gain_30d": round(gain_30d, 4),
        "parabolic_30d": parabolic_30d,
    }

    # Capitulation bar still requires vol spike (selling climaxes are vol-led).
    if regime == "DOWNTREND" and is_spike and is_wide_range and bullish_reversal:
        return {"bar_type": "CAPITULATION_BAR", **base}

    # Blowoff: in EXTENDED_UPTREND, wide-range bearish reversal is the primary
    # signal. Vol-spike upgrades confidence (BLOWOFF_BAR vs BLOWOFF_WATCH).
    # During parabolic blowoffs the trailing baseline gets contaminated by
    # months of high vol, so requiring a strict spike misses the actual top
    # (CSCO Apr 4 2000 had vol_ratio 0.26 against a 180d-median pulled up
    # by Q1 2000's tape — but the bar itself was textbook distribution).
    if regime == "EXTENDED_UPTREND" and is_wide_range and bearish_reversal:
        if is_spike or parabolic_30d:
            return {"bar_type": "BLOWOFF_BAR", **base}
        return {"bar_type": "BLOWOFF_WATCH_BAR", **base}

    if not is_spike:
        return {"bar_type": "NONE", **base}
    return {"bar_type": "NEUTRAL_SPIKE", **base}


# ── Module 3: Turnover Ratio ─────────────────────────────────────────────────

def turnover_metrics(df: pd.DataFrame, shares_outstanding: float | None) -> dict:
    if not shares_outstanding or shares_outstanding <= 0:
        return {"turnover_pct": None, "turnover_slope_10d": None}
    volume = df["Volume"]
    turnover_series = volume / shares_outstanding
    n = len(turnover_series)
    today = float(turnover_series.iloc[-1])
    pct = percentile_rank(today, turnover_series.iloc[-min(60, n):])
    slope_window = turnover_series.iloc[-10:].values.astype(float)
    slope = regression_slope(slope_window)
    return {
        "turnover_pct": round(pct, 1),
        "turnover_slope_10d": float(slope),
        "turnover_today": today,
    }


# ── Module 4: Waning Rally Detection ─────────────────────────────────────────

def detect_waning(df: pd.DataFrame) -> dict:
    """All 4 conditions must fire for WANING_RALLY_WARNING."""
    close = df["Close"]
    volume = df["Volume"]
    n = len(df)
    if n < 35:
        return {"waning": False, "reason": "insufficient data"}

    price_change_30d = (float(close.iloc[-1]) / float(close.iloc[-31])) - 1
    cond1 = price_change_30d >= WANING_PRICE_30D

    vol_10 = volume.iloc[-10:].values.astype(float)
    vol_slope = regression_slope(vol_10)
    cond2 = vol_slope < WANING_VOL_SLOPE

    last10 = df.iloc[-10:]
    prior10 = df.iloc[-20:-10]
    def updown_ratio(window):
        ch = window["Close"].diff()
        up_v = window["Volume"][ch > 0].sum()
        dn_v = window["Volume"][ch < 0].sum()
        return (up_v / dn_v) if dn_v > 0 else (2.0 if up_v > 0 else 1.0)
    ud_last = updown_ratio(last10)
    ud_prior = updown_ratio(prior10)
    cond3 = ud_last < ud_prior

    cmf = cmf_series(df, 20).dropna()
    if len(cmf) < 10:
        cmf_slope = 0.0
    else:
        cmf_slope = regression_slope(cmf.iloc[-10:].values.astype(float))
    cond4 = cmf_slope < 0

    conds_fired = sum([cond1, cond2, cond3, cond4])
    # Tiered firing. c1 (price up) AND c2 (vol declining) are the *core*
    # waning pattern Granville/VSA described ("everyone who can buy has
    # bought" — price rises, volume dries up). c3 (u/d ratio) and c4 (CMF)
    # are confirming nuances. Tier reflects how many confirmations stack:
    #   4/4 → WARNING (full signal)
    #   3/4 (c1+c2 + one of c3/c4) → WARNING
    #   2/4 (c1+c2 alone) → WATCH (core pattern present, no confirmations)
    if cond1 and cond2:
        if conds_fired >= 3:
            tier = "WARNING"
        else:
            tier = "WATCH"
    else:
        tier = "NONE"

    return {
        "waning": tier != "NONE",
        "tier": tier,
        "conds_fired": conds_fired,
        "price_change_30d": round(price_change_30d, 4),
        "vol_slope_10d": float(vol_slope),
        "ud_ratio_last10": round(float(ud_last), 2),
        "ud_ratio_prior10": round(float(ud_prior), 2),
        "cmf_slope_10d": float(cmf_slope),
        "cmf_latest": float(cmf.iloc[-1]) if len(cmf) else None,
        "conds": {"c1_price_up": cond1, "c2_vol_decline": cond2,
                  "c3_ud_deteriorate": cond3, "c4_cmf_decline": cond4},
    }


# ── Module 5: Wyckoff SC → AR → ST Sequence (Stage 2 — multi-SC + Spring) ────

def _evaluate_sc(df: pd.DataFrame, sc_idx: int, ar_window: int) -> dict:
    """Walk forward from a single SC anchor and determine its stage."""
    close = df["Close"]
    low = df["Low"]
    volume = df["Volume"]
    n = len(df)

    sc_low = float(low.iloc[sc_idx])
    sc_volume = float(volume.iloc[sc_idx])
    sc_price = float(close.iloc[sc_idx])
    sc_date = df.index[sc_idx].date().isoformat()

    ar_idx = None
    ar_peak_price = sc_price
    walk_end = min(n, sc_idx + ar_window + 1)
    for j in range(sc_idx + 1, walk_end):
        cj = float(close.iloc[j])
        if cj > ar_peak_price:
            ar_peak_price = cj
        if (cj - sc_low) / sc_low >= AR_REBOUND_THRESHOLD:
            ar_idx = j
            break

    failed_idx = None
    for j in range(sc_idx + 1, n):
        if float(close.iloc[j]) < sc_low:
            failed_idx = j
            break

    st_idx = None
    if ar_idx is not None:
        st_walk_end = min(n, sc_idx + ST_WINDOW + 1)
        for j in range(ar_idx + 1, st_walk_end):
            lj = float(low.iloc[j])
            vj = float(volume.iloc[j])
            if abs(lj - sc_low) / sc_low <= ST_PROXIMITY and vj < sc_volume * ST_VOL_RATIO:
                st_idx = j
                break

    if failed_idx is not None and (ar_idx is None or failed_idx > ar_idx):
        stage = "CAPITULATION_FAILED"
    elif st_idx is not None:
        stage = "CAPITULATION_BOTTOM_CONFIRMED"
    elif ar_idx is not None:
        stage = "CAPITULATION_BOTTOM_FORMING"
    else:
        stage = "CAPITULATION_WATCH"

    return {
        "stage": stage,
        "pattern": "SC_AR_ST",
        "sc_idx": sc_idx,
        "sc_date": sc_date,
        "sc_low": sc_low,
        "sc_price": sc_price,
        "sc_volume": sc_volume,
        "ar_idx": ar_idx,
        "ar_peak": ar_peak_price if ar_idx else None,
        "ar_gain_pct": round((ar_peak_price - sc_low) / sc_low * 100, 2) if ar_idx else None,
        "st_idx": st_idx,
        "st_date": df.index[st_idx].date().isoformat() if st_idx else None,
        "st_vol_vs_sc": round(float(volume.iloc[st_idx]) / sc_volume, 2) if st_idx else None,
        "failed_idx": failed_idx,
        "failed_date": df.index[failed_idx].date().isoformat() if failed_idx else None,
    }


def detect_spring(df: pd.DataFrame) -> dict | None:
    """
    Wyckoff Spring / late-bear shakeout: break of multi-month support followed
    by reversal back above. Catches the Mar 2009-style bottoms where vol has
    normalized but price prints a final new low and reverses sharply.

    Conditions:
      1. Recent 10-session window made a lower low than the prior 60-session window
      2. Today's close is back above the prior support
      3. Bounce from recent lowest low ≥ 5%
    """
    n = len(df)
    if n < 75:
        return None

    PRIOR_LOOKBACK = 60
    RECENT_WINDOW = 10
    BOUNCE_THRESHOLD = 0.05

    recent = df.iloc[-RECENT_WINDOW:]
    older = df.iloc[-(PRIOR_LOOKBACK + RECENT_WINDOW):-RECENT_WINDOW]
    if len(older) < 30:
        return None

    prior_support = float(older["Low"].min())
    recent_min_low = float(recent["Low"].min())
    today_close = float(df["Close"].iloc[-1])

    if not (recent_min_low < prior_support):
        return None
    if not (today_close > prior_support):
        return None
    bounce_pct = (today_close - recent_min_low) / recent_min_low
    if bounce_pct < BOUNCE_THRESHOLD:
        return None

    recent_low_iloc = int(recent["Low"].values.argmin())
    recent_low_idx = n - RECENT_WINDOW + recent_low_iloc
    return {
        "prior_support": prior_support,
        "recent_min_low": recent_min_low,
        "recent_low_idx": recent_low_idx,
        "recent_low_date": df.index[recent_low_idx].date().isoformat(),
        "bounce_pct": round(bounce_pct, 4),
        "today_close": today_close,
    }


def detect_wyckoff_sequence(df: pd.DataFrame, market_cap: float | None) -> dict | None:
    """
    Stage 2: scan the trailing SC_LOOKBACK sessions for ALL SC candidates,
    evaluate each forward to AR/ST/Failed, pick the best-staged candidate,
    and augment with Spring info if a current shakeout is in progress.
    """
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    open_ = df["Open"]
    volume = df["Volume"]
    n = len(df)
    if n < 260:
        return None

    baseline = vol_baseline_series(volume)
    atr14 = atr(df, 14)
    sma200_series = sma(close, 200)

    sc_candidates: list[tuple[int, float]] = []  # (sc_idx, vol_ratio)
    start_i = max(200, n - SC_LOOKBACK - 1)
    for i in range(start_i, n):
        price_i = float(close.iloc[i])
        sma200_i = float(sma200_series.iloc[i])
        if np.isnan(sma200_i) or price_i >= sma200_i:
            continue
        history_start = max(0, i - 252)
        high_1y = float(close.iloc[history_start:i + 1].max())
        if (price_i / high_1y) - 1 > -DOWNTREND_DRAWDOWN:
            continue

        v = float(volume.iloc[i])
        base = float(baseline.iloc[i])
        if np.isnan(base) or base <= 0:
            continue
        v_ratio = v / base

        rng = float(high.iloc[i] - low.iloc[i])
        a = float(atr14.iloc[i])
        range_atr_i = rng / a if a > 0 else 0
        if not (v_ratio >= VOL_SPIKE_RATIO and range_atr_i >= RANGE_ATR):
            continue

        c_i = float(close.iloc[i])
        o_i = float(open_.iloc[i])
        h_i = float(high.iloc[i])
        l_i = float(low.iloc[i])
        mid = (h_i + l_i) / 2
        body = abs(c_i - o_i)
        lower_shadow = min(c_i, o_i) - l_i
        is_hammer = (lower_shadow > body * 2) and (c_i > mid)
        prev_open = float(open_.iloc[i - 1])
        prev_close = float(close.iloc[i - 1])
        is_bullish_engulfing = (c_i > prev_open) and (o_i < prev_close) and (c_i > o_i)
        upper_half_green = (c_i > mid) and (c_i > o_i)
        if not (is_hammer or is_bullish_engulfing or upper_half_green):
            continue

        sc_candidates.append((i, round(v_ratio, 2)))

    is_mega = bool(market_cap and market_cap >= MEGA_CAP_THRESHOLD)
    ar_window = AR_WINDOW_MEGA if is_mega else AR_WINDOW_NON_MEGA
    spring = detect_spring(df)

    if not sc_candidates:
        # No SC found. If a Spring is in progress, emit FORMING with SPRING pattern.
        if spring is not None:
            return {
                "stage": "CAPITULATION_BOTTOM_FORMING",
                "pattern": "SPRING",
                "spring": spring,
                "sc_idx": None,
                "sc_date": None,
                "sc_low": spring["prior_support"],
                "sc_price": None,
                "sc_volume": None,
                "sc_vol_ratio": None,
                "ar_idx": None,
                "ar_peak": None,
                "ar_gain_pct": None,
                "st_idx": None,
                "st_date": None,
                "st_vol_vs_sc": None,
                "failed_idx": None,
                "failed_date": None,
                "is_mega": is_mega,
                "ar_window_used": ar_window,
                "all_sc_count": 0,
            }
        return None

    # Evaluate all SC candidates
    evaluated = []
    for sc_idx, v_ratio in sc_candidates:
        r = _evaluate_sc(df, sc_idx, ar_window)
        r["sc_vol_ratio"] = v_ratio
        evaluated.append(r)

    # Pick best: CONFIRMED > FORMING > WATCH > FAILED. Break ties by recency
    # (later sc_idx wins among same stage — most recent is most actionable).
    stage_priority = {
        "CAPITULATION_BOTTOM_CONFIRMED": 0,
        "CAPITULATION_BOTTOM_FORMING": 1,
        "CAPITULATION_WATCH": 2,
        "CAPITULATION_FAILED": 3,
    }
    evaluated.sort(key=lambda r: (stage_priority.get(r["stage"], 9), -r["sc_idx"]))
    best = evaluated[0]

    # If best is FAILED or WATCH and a Spring is forming NOW, upgrade to FORMING.
    # Logic: original SC(s) failed, but a fresh shakeout below the failed-SC low
    # has reversed — that's a Wyckoff Spring, indicating supply has dried up at
    # the new lower support level. This catches Mar 2009-style bottoms where
    # multiple earlier SCs failed before the actual bottom.
    if spring is not None and best["stage"] in {"CAPITULATION_FAILED", "CAPITULATION_WATCH"}:
        best = dict(best)
        best["stage"] = "CAPITULATION_BOTTOM_FORMING"
        best["pattern"] = "SPRING_AFTER_FAILED" if best.get("failed_idx") else "SPRING"
        best["spring"] = spring

    best["is_mega"] = is_mega
    best["ar_window_used"] = ar_window
    best["all_sc_count"] = len(evaluated)
    if "pattern" not in best:
        best["pattern"] = "SC_AR_ST"
    if spring is not None and "spring" not in best:
        best["spring"] = spring
    return best


# ── Idiosyncratic vs broad-market gate (stress test 8) ───────────────────────

def volume_zscore(volume_series: pd.Series, idx: int, lookback: int = 60) -> float:
    """Z-score of vol at idx using trailing `lookback` window (excluding idx)."""
    start = max(0, idx - lookback)
    window = volume_series.iloc[start:idx]
    if len(window) < 20:
        return 0.0
    mu = float(window.mean())
    sd = float(window.std())
    if sd <= 0:
        return 0.0
    return (float(volume_series.iloc[idx]) - mu) / sd


def idiosyncratic_score(df_ticker: pd.DataFrame, df_spy: pd.DataFrame, bar_date: pd.Timestamp) -> float | None:
    """ticker_vol_z - spy_vol_z on the same date."""
    try:
        t_idx = df_ticker.index.get_indexer([bar_date], method="nearest")[0]
        s_idx = df_spy.index.get_indexer([bar_date], method="nearest")[0]
    except Exception:
        return None
    if t_idx < 20 or s_idx < 20:
        return None
    z_t = volume_zscore(df_ticker["Volume"], t_idx)
    z_s = volume_zscore(df_spy["Volume"], s_idx)
    return z_t - z_s


# ── Reconstitution date check (stress test 6) ────────────────────────────────

def is_near_recon_date(d: date) -> bool:
    for r in RECON_DATES:
        if abs((d - r).days) <= RECON_WINDOW_DAYS:
            return True
    return False


# ── Split-suspect check (stress test 5) ──────────────────────────────────────

def is_split_suspect(df: pd.DataFrame, idx: int) -> bool:
    if idx < 1:
        return False
    today_vol = float(df["Volume"].iloc[idx])
    prev_vol = float(df["Volume"].iloc[idx - 1])
    if prev_vol <= 0:
        return False
    vol_jump = today_vol / prev_vol
    rng = float(df["High"].iloc[idx] - df["Low"].iloc[idx])
    a = float(atr(df, 14).iloc[idx])
    range_atr_i = rng / a if a > 0 else 0
    return vol_jump >= SPLIT_SUSPECT_RATIO and range_atr_i < RANGE_ATR


# ── Module 7: Composite Signal ───────────────────────────────────────────────

def _format_oi_annotation(signal_category: str, oi_metrics: dict | None,
                           has_today_snapshot: bool) -> str:
    """
    Format the OI annotation that gets appended to the signal `detail` string.
    OI is *informational context only* — never auto-upgrades signal confidence.
    """
    if not has_today_snapshot:
        return "OI: NO_OPTIONS_DATA"
    if oi_metrics is None:
        return "OI: snapshot recorded (need history for trend)"

    n = oi_metrics.get("snapshots_in_history", 0)
    p5 = oi_metrics.get("oi_pct_change_5d")
    trend = oi_metrics.get("oi_trend", "FLAT")
    call_pct = oi_metrics.get("call_oi_pct_change_5d")
    put_pct = oi_metrics.get("put_oi_pct_change_5d")
    pc_delta = oi_metrics.get("put_call_ratio_delta")

    def fmt_pct(x):
        return f"{x*100:+.1f}%" if x is not None else "n/a"

    bits = [f"OI: {trend.lower()} ({fmt_pct(p5)} 5d, {n} snap)"]

    if signal_category == "CAPITULATION" and oi_metrics.get("put_oi_surge"):
        bits.append(f"PUT_SURGE {fmt_pct(put_pct)} 5d (panic hedging)")
    if signal_category == "BLOWOFF" and oi_metrics.get("call_oi_surge"):
        bits.append(f"CALL_SURGE {fmt_pct(call_pct)} 5d (FOMO speculation)")
    if signal_category == "WANING" and trend == "DECREASING":
        bits.append(f"speculative interest declining")
    if pc_delta is not None and abs(pc_delta) >= 0.1:
        direction = "put-tilt" if pc_delta > 0 else "call-tilt"
        bits.append(f"P/C ratio Δ{pc_delta:+.2f} ({direction} vs 20d avg)")

    return "  ".join(bits)


def classify_signal(
    ticker: str,
    df: pd.DataFrame,
    regime: str,
    swell: dict,
    turnover: dict,
    waning: dict,
    wyckoff: dict | None,
    market_cap: float | None,
    idio_score: float | None,
    near_recon: bool,
    split_suspect: bool,
    oi_metrics: dict | None = None,
    oi_snapshot_today: dict | None = None,
) -> dict:
    flags: list[str] = []
    if market_cap and market_cap >= MEGA_CAP_THRESHOLD:
        flags.append("MEGA_CAP")
    if near_recon:
        flags.append("MECHANICAL_FLOW")
    if split_suspect:
        flags.append("SPLIT_SUSPECT")
    if idio_score is not None and idio_score < IDIOSYNCRATIC_Z_MIN:
        flags.append("BROAD_FLOW")
    if oi_snapshot_today is None:
        flags.append("NO_OPTIONS_DATA")

    signal = "NEUTRAL"
    detail = ""

    bar_type = swell.get("bar_type")

    # Capitulation — driven by Wyckoff sequence detector (180d lookback,
    # multi-SC tracking, Spring fallback).
    if wyckoff is not None:
        suppress_capitulation = "MECHANICAL_FLOW" in flags or "SPLIT_SUSPECT" in flags or "BROAD_FLOW" in flags
        if suppress_capitulation and wyckoff["stage"] == "CAPITULATION_WATCH":
            signal = "NEUTRAL"
        else:
            signal = wyckoff["stage"]
            parts = []
            pattern = wyckoff.get("pattern", "SC_AR_ST")

            if wyckoff.get("sc_idx") is not None:
                parts.append(
                    f"SC {wyckoff['sc_date']} @ ${wyckoff['sc_price']:.2f} "
                    f"(vol {wyckoff['sc_vol_ratio']}× baseline)"
                )
                if wyckoff.get("all_sc_count", 1) > 1:
                    parts[-1] += f" [+{wyckoff['all_sc_count']-1} earlier SC]"
                if wyckoff["ar_idx"] is not None:
                    parts.append(f"AR +{wyckoff['ar_gain_pct']:.1f}% (window {wyckoff['ar_window_used']}d)")
                if wyckoff["st_idx"] is not None:
                    parts.append(f"ST {wyckoff['st_date']} vol {wyckoff['st_vol_vs_sc']}× SC")
                if wyckoff["failed_idx"] is not None and pattern != "SPRING_AFTER_FAILED":
                    parts.append("FAILED: close < SC_low")

            spring_info = wyckoff.get("spring")
            if spring_info and pattern in {"SPRING", "SPRING_AFTER_FAILED"}:
                tag = "SPRING" if pattern == "SPRING" else "SPRING (after earlier SC failed)"
                parts.append(
                    f"{tag}: broke ${spring_info['prior_support']:.2f} support "
                    f"to ${spring_info['recent_min_low']:.2f} ({spring_info['recent_low_date']}), "
                    f"rebounded +{spring_info['bounce_pct']*100:.1f}% to ${spring_info['today_close']:.2f}"
                )

            detail = " | ".join(parts) if parts else f"stage={wyckoff['stage']}"

    # Blowoff — today's bar is a wide-range bearish reversal in EXTENDED_UPTREND.
    # BLOWOFF_BAR = full spike (vol or parabolic context); BLOWOFF_WATCH_BAR =
    # the price pattern fired but vol baseline contaminated by extended rally.
    elif bar_type in {"BLOWOFF_BAR", "BLOWOFF_WATCH_BAR"}:
        suppress = "MECHANICAL_FLOW" in flags or "SPLIT_SUSPECT" in flags
        if not suppress:
            signal = "BLOWOFF_TOP_RISK" if bar_type == "BLOWOFF_BAR" else "BLOWOFF_WATCH"
            tp = turnover.get("turnover_pct")
            tp_str = f"{tp:.0f}%" if tp is not None else "n/a"
            para = "PARABOLIC" if swell.get("parabolic_30d") else ""
            detail = (
                f"Vol {swell['vol_ratio']}× baseline ({swell['vol_pct_60d']:.0f}pct of 60d), "
                f"range {swell['range_atr']}× ATR, "
                f"30d gain +{swell.get('gain_30d', 0)*100:.1f}% {para}, "
                f"turnover {tp_str}"
            ).strip()

    # Waning — fires in STEADY_UPTREND or EXTENDED_UPTREND (pre-blowoff
    # distribution often happens during parabolic phases too).
    elif waning.get("waning") and regime in {"STEADY_UPTREND", "EXTENDED_UPTREND"}:
        suppress = "MECHANICAL_FLOW" in flags
        if not suppress:
            tier = waning.get("tier")
            signal = "WANING_RALLY_WARNING" if tier == "WARNING" else "WANING_WATCH"
            cf = waning.get("conds_fired", 0)
            detail = (
                f"[{cf}/4 conds] "
                f"Price +{waning['price_change_30d']*100:.1f}% in 30d, "
                f"vol slope {waning['vol_slope_10d']:+.0f}, "
                f"u/d ratio {waning['ud_ratio_prior10']}→{waning['ud_ratio_last10']}, "
                f"CMF slope {waning['cmf_slope_10d']:+.4f}"
            )

    # Append OI annotation as informational context — never auto-upgrades tier.
    if signal != "NEUTRAL":
        if signal in CAPITULATION_SIGNALS:
            sig_cat = "CAPITULATION"
        elif signal in BLOWOFF_SIGNALS:
            sig_cat = "BLOWOFF"
        elif signal in WANING_SIGNALS:
            sig_cat = "WANING"
        else:
            sig_cat = "OTHER"
        oi_tag = _format_oi_annotation(sig_cat, oi_metrics, oi_snapshot_today is not None)
        if detail and oi_tag:
            detail = f"{detail}\n        {oi_tag}"
        elif oi_tag:
            detail = oi_tag

    return {
        "ticker": ticker,
        "signal": signal,
        "regime": regime,
        "bar_type": bar_type,
        "detail": detail,
        "flags": flags,
        "market_cap": market_cap,
        "turnover_pct": turnover.get("turnover_pct"),
        "vol_ratio": swell.get("vol_ratio"),
        "wyckoff": wyckoff,
        "waning": waning,
        "idio_score": idio_score,
        "oi_metrics": oi_metrics,
        "oi_snapshot_today": oi_snapshot_today,
    }


# ── Chart rendering ──────────────────────────────────────────────────────────

def render_chart(ticker: str, df: pd.DataFrame, result: dict, turnover: dict) -> io.BytesIO | None:
    try:
        plt.style.use("dark_background")
        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1]})
        fig.patch.set_facecolor("#1a1a2e")
        for ax in axes:
            ax.set_facecolor("#1a1a2e")

        df_plot = df.iloc[-min(180, len(df)):]
        ax1, ax2 = axes

        ax1.plot(df_plot.index, df_plot["Close"], color="#ffffff", linewidth=1.5, label="Close")
        if len(df) >= 200:
            ax1.plot(df_plot.index, sma(df["Close"], 200).iloc[-len(df_plot):],
                     color="#e6a8d3", linewidth=1, label="SMA200", alpha=0.7)
        if len(df) >= 50:
            ax1.plot(df_plot.index, sma(df["Close"], 50).iloc[-len(df_plot):],
                     color="#f3c969", linewidth=1, label="SMA50", alpha=0.7)
        if len(df) >= 20:
            ax1.plot(df_plot.index, sma(df["Close"], 20).iloc[-len(df_plot):],
                     color="#a8e6a8", linewidth=1, label="SMA20", alpha=0.7)

        wy = result.get("wyckoff")
        if wy:
            if wy.get("sc_idx") is not None:
                sc_dt = df.index[wy["sc_idx"]]
                if sc_dt in df_plot.index:
                    ax1.scatter([sc_dt], [wy["sc_low"]], marker="*", s=200,
                                color="#ff4d4d", edgecolors="white", linewidths=1, zorder=5, label="SC")
            spring_info = wy.get("spring")
            if spring_info and spring_info.get("recent_low_idx") is not None:
                sp_dt = df.index[spring_info["recent_low_idx"]]
                if sp_dt in df_plot.index:
                    ax1.scatter([sp_dt], [spring_info["recent_min_low"]], marker="P",
                                s=180, color="#00d9ff", edgecolors="white",
                                linewidths=1, zorder=5, label="SPRING")
                ax1.axhline(y=spring_info["prior_support"], color="#00d9ff",
                            linestyle=":", linewidth=0.8, alpha=0.5)
            if wy.get("ar_idx") is not None:
                ar_dt = df.index[wy["ar_idx"]]
                if ar_dt in df_plot.index:
                    ax1.scatter([ar_dt], [wy["ar_peak"]], marker="D", s=120,
                                color="#a8e6a8", edgecolors="white", linewidths=1, zorder=5, label="AR")
            if wy.get("st_idx") is not None:
                st_dt = df.index[wy["st_idx"]]
                if st_dt in df_plot.index:
                    ax1.scatter([st_dt], [float(df["Low"].iloc[wy["st_idx"]])],
                                marker="s", s=120, color="#f3c969", edgecolors="white",
                                linewidths=1, zorder=5, label="ST")
            if wy.get("failed_idx") is not None:
                f_dt = df.index[wy["failed_idx"]]
                if f_dt in df_plot.index:
                    ax1.scatter([f_dt], [float(df["Close"].iloc[wy["failed_idx"]])],
                                marker="X", s=180, color="#ff4d4d", edgecolors="white",
                                linewidths=1, zorder=5, label="FAILED")
            if wy.get("sc_low") is not None:
                ax1.axhline(y=wy["sc_low"], color="#ff4d4d", linestyle="--", linewidth=0.8, alpha=0.5)

        if result.get("signal") in {"BLOWOFF_TOP_RISK"}:
            today_dt = df.index[-1]
            if today_dt in df_plot.index:
                ax1.scatter([today_dt], [float(df["High"].iloc[-1])], marker="v",
                            s=200, color="#ff4d4d", edgecolors="white", linewidths=1,
                            zorder=5, label="BLOWOFF")

        ax1.set_title(f"{ticker} — {result.get('signal','')} | regime: {result.get('regime','')}",
                      color="white", fontsize=13)
        ax1.legend(loc="upper left", fontsize=8, framealpha=0.3)
        ax1.grid(True, alpha=0.15)
        ax1.tick_params(colors="white")

        colors = ["#a8e6a8" if df_plot["Close"].iloc[i] >= df_plot["Open"].iloc[i] else "#e6a8d3"
                  for i in range(len(df_plot))]
        ax2.bar(df_plot.index, df_plot["Volume"], color=colors, alpha=0.7, width=0.8)
        vol_avg = df["Volume"].rolling(20).mean().iloc[-len(df_plot):]
        ax2.plot(df_plot.index, vol_avg, color="#00d9ff", linewidth=1.2, label="SMA20 vol")

        tp = turnover.get("turnover_pct")
        if tp is not None:
            ax2_right = ax2.twinx()
            ax2_right.set_facecolor("#1a1a2e")
            tp_label = f"Turnover pct (today): {tp:.0f}%"
            ax2_right.text(0.99, 0.92, tp_label, transform=ax2_right.transAxes,
                           color="#f3c969", fontsize=9, ha="right", va="top",
                           bbox=dict(boxstyle="round,pad=0.3", fc="#1a1a2e", ec="#f3c969"))
            ax2_right.set_yticks([])

        ax2.set_ylabel("Volume", color="white", fontsize=9)
        ax2.tick_params(colors="white")
        ax2.legend(loc="upper left", fontsize=8, framealpha=0.3)
        ax2.grid(True, alpha=0.15)

        ax2.xaxis.set_major_locator(mdates.MonthLocator())
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        fig.autofmt_xdate()

        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format="png", dpi=110, facecolor="#1a1a2e")
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as e:
        print(f"  chart render failed for {ticker}: {e}", file=sys.stderr)
        return None


# ── Output formatter ─────────────────────────────────────────────────────────

CAPITULATION_SIGNALS = {
    "CAPITULATION_BOTTOM_CONFIRMED",
    "CAPITULATION_BOTTOM_FORMING",
    "CAPITULATION_WATCH",
    "CAPITULATION_FAILED",
}
BLOWOFF_SIGNALS = {"BLOWOFF_TOP_RISK", "BLOWOFF_WATCH"}
WANING_SIGNALS = {"WANING_RALLY_WARNING", "WANING_WATCH"}

STAGE_LABEL = {
    "CAPITULATION_BOTTOM_CONFIRMED": "CONFIRMED",
    "CAPITULATION_BOTTOM_FORMING": "FORMING",
    "CAPITULATION_WATCH": "WATCH",
    "CAPITULATION_FAILED": "FAILED",
}


def format_output(results: list[dict], mode: str, universe_size: int) -> str:
    now = datetime.now(ET)
    header = (
        "══════════════════════════════════════════\n"
        f"VOLUME EXHAUSTION SCANNER — {now.strftime('%Y-%m-%d')}\n"
        "══════════════════════════════════════════\n"
        f"Mode: {mode} | Scanned: {universe_size} tickers\n"
        "Stage 2 — multi-SC + 180d lookback + Spring detector + tiered waning\n"
    )

    cap_rows = [r for r in results if r["signal"] in CAPITULATION_SIGNALS]
    blow_rows = [r for r in results if r["signal"] in BLOWOFF_SIGNALS]
    wan_rows = [r for r in results if r["signal"] in WANING_SIGNALS]

    sections = [header]

    def fmt_flags(flags):
        return f" [{','.join(flags)}]" if flags else ""

    if cap_rows:
        cap_rows.sort(key=lambda r: {
            "CAPITULATION_BOTTOM_CONFIRMED": 0,
            "CAPITULATION_BOTTOM_FORMING": 1,
            "CAPITULATION_WATCH": 2,
            "CAPITULATION_FAILED": 3,
        }.get(r["signal"], 9))
        lines = ["", "🔻 CAPITULATION (bottom processes)",
                 "─────────────────────────────────────────"]
        for r in cap_rows:
            lines.append(f"{r['ticker']:<7} {STAGE_LABEL[r['signal']]:<10}{fmt_flags(r['flags'])}")
            lines.append(f"        {r['detail']}")
        sections.append("\n".join(lines))
    else:
        sections.append("\n🔻 CAPITULATION — no signals")

    if blow_rows:
        lines = ["", "🔺 BLOWOFF (top exhaustion risk)",
                 "─────────────────────────────────────────"]
        for r in blow_rows:
            tag = "RISK" if r["signal"] == "BLOWOFF_TOP_RISK" else "WATCH"
            lines.append(f"{r['ticker']:<7} {tag}{fmt_flags(r['flags'])}")
            lines.append(f"        {r['detail']}")
        sections.append("\n".join(lines))
    else:
        sections.append("\n🔺 BLOWOFF — no signals")

    if wan_rows:
        lines = ["", "⚠️  WANING RALLY (demand fatigue)",
                 "─────────────────────────────────────────"]
        for r in wan_rows:
            tag = "WARN" if r["signal"] == "WANING_RALLY_WARNING" else "WATCH"
            lines.append(f"{r['ticker']:<7} {tag}{fmt_flags(r['flags'])}")
            lines.append(f"        {r['detail']}")
        sections.append("\n".join(lines))
    else:
        sections.append("\n⚠️  WANING RALLY — no signals")

    sections.append("")
    return "\n".join(sections)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Windows cp1252 console chokes on box-drawing chars / emojis used in output.
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    cli_tickers = sys.argv[1:]
    tickers, mode = load_universe(cli_tickers)
    if not tickers:
        print("No tickers in universe — exiting.", file=sys.stderr)
        sys.exit(1)

    print(f"  Mode: {mode}")
    print(f"  Tickers: {', '.join(tickers[:20])}{' ...' if len(tickers) > 20 else ''}")

    print("  Fetching OHLCV (1y daily)…")
    data = batch_fetch(tickers, period="1y")
    print(f"  Got data for {len(data)}/{len(tickers)} tickers")

    print("  Fetching SPY for idiosyncratic gate…")
    spy_df = fetch_ohlcv("SPY", period="1y")

    shares_cache = load_shares_cache()
    print(f"  Loading shares-outstanding cache ({len(shares_cache)} entries)…")

    oi_history = load_oi_history()
    print(f"  Loading OI history ({len(oi_history)} tickers tracked)…")

    results: list[tuple[dict, pd.DataFrame, dict]] = []
    oi_fetched = 0
    oi_missing = 0
    for ticker in tickers:
        df = data.get(ticker)
        if df is None or len(df) < 60:
            continue

        shares_out = get_shares_outstanding(ticker, shares_cache)
        last_close = float(df["Close"].iloc[-1])
        market_cap = (shares_out * last_close) if shares_out else None

        regime = classify_regime(df)
        swell = detect_volume_swell(df, regime)
        turnover = turnover_metrics(df, shares_out)
        waning = detect_waning(df)
        wyckoff = detect_wyckoff_sequence(df, market_cap)

        # Module 6: OI snapshot today + computed % change metrics from history.
        oi_snapshot = fetch_oi_snapshot(ticker)
        if oi_snapshot is not None:
            append_oi_snapshot(oi_history, ticker, oi_snapshot)
            oi_fetched += 1
        else:
            oi_missing += 1
        oi_metrics = compute_oi_metrics(ticker, oi_history)

        idio = None
        if wyckoff and spy_df is not None:
            sc_date = df.index[wyckoff["sc_idx"]] if wyckoff.get("sc_idx") is not None else df.index[-1]
            idio = idiosyncratic_score(df, spy_df, sc_date)
        elif swell.get("bar_type") in {"BLOWOFF_BAR", "CAPITULATION_BAR"} and spy_df is not None:
            idio = idiosyncratic_score(df, spy_df, df.index[-1])

        if wyckoff and wyckoff.get("sc_idx") is not None:
            bar_date = df.index[wyckoff["sc_idx"]].date()
            bar_idx = wyckoff["sc_idx"]
        else:
            bar_date = df.index[-1].date()
            bar_idx = len(df) - 1
        near_recon = is_near_recon_date(bar_date)
        split_suspect = is_split_suspect(df, bar_idx)

        result = classify_signal(
            ticker, df, regime, swell, turnover, waning, wyckoff,
            market_cap, idio, near_recon, split_suspect,
            oi_metrics=oi_metrics, oi_snapshot_today=oi_snapshot,
        )
        results.append((result, df, turnover))

        # Per-ticker diagnostic — what the scanner saw + OI context.
        tp = turnover.get("turnover_pct")
        tp_str = f"{tp:.0f}%" if tp is not None else "  n/a"
        wy_stage = wyckoff["stage"] if wyckoff else "—"
        cap_b = f"${market_cap/1e9:.0f}B" if market_cap else "n/a"
        if oi_snapshot is None:
            oi_str = "OI=n/a"
        elif oi_metrics is None:
            oi_str = "OI=1d"
        else:
            n_snap = oi_metrics["snapshots_in_history"]
            p5 = oi_metrics["oi_pct_change_5d"]
            p5_str = f"{p5*100:+.0f}%" if p5 is not None else "n/a"
            oi_str = f"OI={oi_metrics['oi_trend'][:3]}/{p5_str}({n_snap})"
        print(f"  {ticker:<7} regime={regime:<18} cap={cap_b:<8} bar={swell.get('bar_type','NONE'):<17}"
              f" turn_pct={tp_str:<6} waning={'Y' if waning.get('waning') else 'N'} "
              f"wyck={wy_stage:<32} {oi_str}")

    save_shares_cache(shares_cache)
    save_oi_history(oi_history)
    print(f"  OI snapshots: {oi_fetched} fetched, {oi_missing} missing")

    flat_results = [r for r, _, _ in results]
    text = format_output(flat_results, mode, len(tickers))
    print()
    print(text)
    send_discord_text(text)

    signalled = [(r, df, tu) for (r, df, tu) in results if r["signal"] != "NEUTRAL"]
    by_section = {"cap": [], "blow": [], "wan": []}
    for r, df, tu in signalled:
        if r["signal"] in CAPITULATION_SIGNALS:
            by_section["cap"].append((r, df, tu))
        elif r["signal"] in BLOWOFF_SIGNALS:
            by_section["blow"].append((r, df, tu))
        elif r["signal"] in WANING_SIGNALS:
            by_section["wan"].append((r, df, tu))

    for section in ("cap", "blow", "wan"):
        for r, df, tu in by_section[section][:5]:
            buf = render_chart(r["ticker"], df, r, tu)
            if buf:
                send_discord_image(buf, f"{r['ticker']}_{r['signal']}.png")

    print(f"  Done — {len(signalled)} signals fired.")


if __name__ == "__main__":
    main()
