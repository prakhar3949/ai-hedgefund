"""
Market Breadth Scanner
Confirms whether sector strength is broad-based (durable) or narrow (fragile,
driven by a few mega-caps).

Scans all 11 S&P 500 sector ETFs and their top 20 constituents to compute:
  Metric 1: % Above Key Moving Averages (SMA50, SMA200, EMA21)
  Metric 2: Advance/Decline (A/D ratio, new highs/lows)
  Metric 3: Equal-Weight vs Cap-Weight Divergence
  Metric 4: Breadth Thrust / Collapse Detection

Input:
  - Default: all 11 CW sector ETFs
  - Override: python breadth-scanner.py XLK XLP XLE

Output:
  - Breadth table with health scores per sector
  - Alerts (narrow leadership, thrust, collapse)
  - Heatmap chart + breadth momentum line chart
  - Posted to Discord

Cost: $0.00 (Yahoo Chart API, no API key needed)
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

# ── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1473219539482447932/"
    "ldQgJErtPUj1aYnwgCj_HsMvt_BbuQRdzhdQ-9eXc4fvBx1R9ypYrAUzmIUbcb2_Mp2B"
)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ── Sector Definitions ───────────────────────────────────────────────────────
CW_SECTORS = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Health Care", "XLI": "Industrials", "XLP": "Cons. Staples",
    "XLY": "Cons. Discret.", "XLU": "Utilities", "XLC": "Comms",
    "XLB": "Materials", "XLRE": "Real Estate",
}


# ── Discord Posting ──────────────────────────────────────────────────────────

def send_discord_text(text: str):
    if not DISCORD_WEBHOOK_URL:
        print(f"  [no webhook] {text[:120]}...")
        return
    if len(text) > 1950:
        text = text[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Discord text failed: {e}")


def send_discord_image(buf: io.BytesIO, filename: str):
    if not DISCORD_WEBHOOK_URL:
        print(f"  [no webhook] Would post {filename}")
        return
    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            files={"file": (filename, buf, "image/png")},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  Discord image failed: {e}")


# ── Data Fetching ────────────────────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str = "1y") -> pd.DataFrame | None:
    """Fetch OHLCV data from Yahoo Finance chart API."""
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
        }, index=pd.to_datetime(timestamps, unit="s", utc=True))
        df.index = df.index.tz_convert("America/New_York")
        df = df.dropna(subset=["Close"])
        if len(df) < 50:
            return None
        return df
    except Exception:
        return None


def batch_fetch(tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Parallel fetch OHLCV with batching to avoid rate limits."""
    results = {}
    batch_size = 50
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        if i > 0:
            time.sleep(2)  # 2s delay between batches
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(fetch_ohlcv, t, period): t for t in batch}
            for f in as_completed(futures):
                t = futures[f]
                try:
                    df = f.result()
                    if df is not None:
                        results[t] = df
                except Exception:
                    pass
    return results


RUSSELL_CACHE = TOOLS_DIR / "russell-3000.json"
RUSSELL_CACHE_DAYS = 7
NASDAQ_URL = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_full_tickers.json"
NYSE_URL = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nyse/nyse_full_tickers.json"
# Names that aren't common stocks — filter them out of the Russell 3000 proxy
NON_COMMON_PATTERNS = (
    "right", "warrant", " unit", " units", "preferred", "depositary",
    "% note", " notes", " bond", " trust ", "% senior", "% subordinated",
    "etn ", " etn", "leveraged", "inverse",
)


def build_russell_3000_universe() -> list[dict]:
    """Build a Russell-3000 proxy: top 3000 US-listed common stocks by market cap.

    Source: rreichel3/US-Stock-Symbols GitHub mirror (NASDAQ + NYSE full lists).
    Cached locally to russell-3000.json; refreshed weekly.

    Returns list of dicts with keys: symbol, name, sector, market_cap.
    """
    if RUSSELL_CACHE.exists():
        age_days = (time.time() - RUSSELL_CACHE.stat().st_mtime) / 86400
        if age_days < RUSSELL_CACHE_DAYS:
            try:
                return json.loads(RUSSELL_CACHE.read_text())
            except Exception:
                pass

    rows = []
    for url in (NASDAQ_URL, NYSE_URL):
        try:
            resp = requests.get(url, headers=YAHOO_HEADERS, timeout=30)
            resp.raise_for_status()
            rows.extend(resp.json())
        except Exception as e:
            print(f"  Russell list fetch failed for {url}: {e}", file=sys.stderr)

    if not rows:
        print("  All Russell sources failed; using cached list if present", file=sys.stderr)
        if RUSSELL_CACHE.exists():
            return json.loads(RUSSELL_CACHE.read_text())
        return []

    def _passes(r):
        if (r.get("country") or "") != "United States":
            return False
        sym = (r.get("symbol") or "").strip()
        if not sym or len(sym) > 5:
            return False
        # Exclude rights, warrants, units, preferreds via name patterns
        nm = (r.get("name") or "").lower()
        if any(p in nm for p in NON_COMMON_PATTERNS):
            return False
        # Exclude tickers ending with R / W / U (typical rights/warrants/units suffixes)
        if len(sym) >= 4 and sym[-1] in "RW" and sym[-2].isalpha():
            return False
        try:
            mc = float(r.get("marketCap") or 0)
        except ValueError:
            mc = 0
        if mc < 100_000_000:  # filter sub-$100M to drop SPACs / micro illiquids
            return False
        return True

    filtered = [r for r in rows if _passes(r)]
    # Dedup by symbol (some are dual-listed)
    seen = {}
    for r in filtered:
        sym = r["symbol"].strip()
        try:
            mc = float(r.get("marketCap") or 0)
        except ValueError:
            mc = 0
        if sym not in seen or mc > seen[sym]["_mc"]:
            seen[sym] = {**r, "_mc": mc}
    deduped = sorted(seen.values(), key=lambda r: r["_mc"], reverse=True)[:3000]

    universe = [
        {"symbol": r["symbol"].strip(), "name": r.get("name", ""),
         "sector": r.get("sector", "") or "Unknown",
         "market_cap": r["_mc"]}
        for r in deduped
    ]
    try:
        RUSSELL_CACHE.write_text(json.dumps(universe))
    except Exception as e:
        print(f"  Russell cache write failed: {e}", file=sys.stderr)
    return universe


def fetch_52w_meta(ticker: str, session: requests.Session | None = None) -> dict | None:
    """Fetch 52w high/low + current price from Yahoo chart meta (one request, tiny payload)."""
    yt = ticker.replace(".", "-")  # BRK.B -> BRK-B
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yt}?range=1d&interval=1d"
    try:
        getter = session.get if session is not None else requests.get
        resp = getter(url, headers=YAHOO_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        m = resp.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
        price = m.get("regularMarketPrice")
        hi = m.get("fiftyTwoWeekHigh")
        lo = m.get("fiftyTwoWeekLow")
        if price is None or hi is None or lo is None or hi <= 0:
            return None
        return {"price": float(price), "high_52w": float(hi), "low_52w": float(lo)}
    except Exception:
        return None


def scan_russell_52w_breadth(universe: list[dict]) -> dict:
    """Fetch 52w high/low for all tickers in universe; classify each as NH / NL / neither.

    NH definition: price >= 99.9% of fiftyTwoWeekHigh (true tape new high, allows 0.1% slack)
    NL definition: price <= 100.1% of fiftyTwoWeekLow
    """
    symbols = [u["symbol"] for u in universe]
    sym_meta = {u["symbol"]: u for u in universe}
    results = {}

    print(f"  [52w breadth] fetching {len(symbols)} tickers (max_workers=20, session pool)...")
    t0 = time.time()
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=0)
    session.mount("https://", adapter)
    try:
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = {ex.submit(fetch_52w_meta, s, session): s for s in symbols}
            for i, fut in enumerate(as_completed(futures), 1):
                sym = futures[fut]
                try:
                    data = fut.result()
                except Exception:
                    data = None
                if data is not None:
                    results[sym] = data
                if i % 500 == 0:
                    print(f"    progress: {i}/{len(symbols)}  ({len(results)} valid)")
    finally:
        session.close()
    elapsed = time.time() - t0
    print(f"  [52w breadth] {len(results)}/{len(symbols)} valid in {elapsed:.0f}s")

    nh, nl = [], []
    sector_stats = {}  # sector -> {"nh": n, "nl": n, "total": n}
    for sym, d in results.items():
        meta = sym_meta.get(sym, {})
        sec = meta.get("sector", "Unknown") or "Unknown"
        st = sector_stats.setdefault(sec, {"nh": 0, "nl": 0, "total": 0})
        st["total"] += 1
        is_nh = d["price"] >= d["high_52w"] * 0.999
        is_nl = d["price"] <= d["low_52w"] * 1.001
        if is_nh:
            from_low = (d["price"] / d["low_52w"] - 1.0) * 100 if d["low_52w"] > 0 else 0
            nh.append({"symbol": sym, "name": meta.get("name", ""), "sector": sec,
                       "price": d["price"], "from_low_pct": from_low})
            st["nh"] += 1
        if is_nl:
            from_high = (1.0 - d["price"] / d["high_52w"]) * 100 if d["high_52w"] > 0 else 0
            nl.append({"symbol": sym, "name": meta.get("name", ""), "sector": sec,
                       "price": d["price"], "from_high_pct": from_high})
            st["nl"] += 1

    nh.sort(key=lambda r: r["from_low_pct"], reverse=True)
    nl.sort(key=lambda r: r["from_high_pct"], reverse=True)
    return {
        "universe_size": len(symbols),
        "scanned": len(results),
        "nh": nh,
        "nl": nl,
        "sector_stats": sector_stats,
    }


def format_52w_breadth(stats: dict) -> list[str]:
    """Return one or more Discord-ready text chunks summarizing the 52w scan."""
    n_uni = stats["universe_size"]
    n_scan = stats["scanned"]
    n_nh = len(stats["nh"])
    n_nl = len(stats["nl"])
    cov = (n_scan / n_uni * 100) if n_uni else 0
    nh_pct = (n_nh / n_scan * 100) if n_scan else 0
    nl_pct = (n_nl / n_scan * 100) if n_scan else 0
    if n_nl == 0:
        ratio_str = "inf (no new lows)"
        regime = "EXTREME RISK-ON"
    else:
        ratio = n_nh / n_nl
        ratio_str = f"{ratio:.2f}"
        if ratio >= 5: regime = "STRONG RISK-ON"
        elif ratio >= 2: regime = "RISK-ON"
        elif ratio >= 0.5: regime = "NEUTRAL"
        elif ratio >= 0.2: regime = "RISK-OFF"
        else: regime = "STRONG RISK-OFF"

    out = []
    head = ["```", "=" * 52, "RUSSELL 3000 — 52-WEEK BREADTH", "=" * 52,
            f"Universe: {n_uni}  |  Scanned: {n_scan} ({cov:.1f}%)",
            "",
            f"NEW HIGHS: {n_nh:>4} ({nh_pct:.1f}%)",
            f"NEW LOWS : {n_nl:>4} ({nl_pct:.1f}%)",
            f"NH/NL Ratio: {ratio_str}    Regime: {regime}",
            "",
            "By Sector (NH | NL | total):"]
    secs = sorted(stats["sector_stats"].items(), key=lambda kv: kv[1]["nh"], reverse=True)
    for sec, s in secs:
        if s["total"] < 5:
            continue
        head.append(f"  {sec:<22}  {s['nh']:>3} | {s['nl']:>3} | {s['total']:>4}")
    head.append("```")
    out.append("\n".join(head))

    if stats["nh"]:
        top_nh = stats["nh"][:15]
        lines = ["```", f"TOP {len(top_nh)} NEW HIGHS (sorted by % from 52w low):", "-" * 52,
                 f"{'TICKER':<8}{'%FROM_LOW':>12}  {'PRICE':>10}  SECTOR"]
        for r in top_nh:
            lines.append(f"{r['symbol']:<8}{r['from_low_pct']:>11.0f}%  ${r['price']:>9,.2f}  {r['sector']}")
        lines.append("```")
        out.append("\n".join(lines))

    if stats["nl"]:
        top_nl = stats["nl"][:15]
        lines = ["```", f"TOP {len(top_nl)} NEW LOWS (sorted by drawdown from 52w high):", "-" * 52,
                 f"{'TICKER':<8}{'DRAWDOWN':>12}  {'PRICE':>10}  SECTOR"]
        for r in top_nl:
            lines.append(f"{r['symbol']:<8}{r['from_high_pct']:>11.0f}%  ${r['price']:>9,.2f}  {r['sector']}")
        lines.append("```")
        out.append("\n".join(lines))

    return out


def load_etf_holdings() -> dict:
    path = TOOLS_DIR / "etf-holdings.json"
    with open(path) as f:
        return json.load(f)


# ── Breadth Metrics ──────────────────────────────────────────────────────────

def compute_ma_breadth(constituents: dict[str, pd.DataFrame]) -> dict:
    """Metric 1: % of constituents above key moving averages."""
    above_50 = 0
    above_200 = 0
    above_21e = 0
    total = len(constituents)
    if total == 0:
        return {"pct_above_50": 0, "pct_above_200": 0, "pct_above_21e": 0, "trend_50": 0}

    # Also compute % above SMA50 for each of the last 63 days (for thrust detection)
    daily_above_50 = []

    for ticker, df in constituents.items():
        close = df["Close"]
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        ema21 = close.ewm(span=21).mean()

        if len(close) > 0 and not pd.isna(sma50.iloc[-1]):
            if close.iloc[-1] > sma50.iloc[-1]:
                above_50 += 1
        if len(close) > 0 and not pd.isna(sma200.iloc[-1]):
            if close.iloc[-1] > sma200.iloc[-1]:
                above_200 += 1
        if len(close) > 0 and not pd.isna(ema21.iloc[-1]):
            if close.iloc[-1] > ema21.iloc[-1]:
                above_21e += 1

    pct_50 = above_50 / total * 100
    pct_200 = above_200 / total * 100
    pct_21e = above_21e / total * 100

    # 10-day trend in % above SMA50: compute for last 63 days
    lookback = min(63, min(len(df) for df in constituents.values()) - 50)
    if lookback < 10:
        lookback = 10
    pct_50_series = []
    for day_offset in range(lookback, -1, -1):
        count = 0
        for ticker, df in constituents.items():
            close = df["Close"]
            sma50 = close.rolling(50).mean()
            idx = len(close) - 1 - day_offset
            if idx >= 0 and not pd.isna(sma50.iloc[idx]):
                if close.iloc[idx] > sma50.iloc[idx]:
                    count += 1
        pct_50_series.append(count / total * 100)

    trend_50 = pct_50_series[-1] - pct_50_series[-11] if len(pct_50_series) >= 11 else 0

    return {
        "pct_above_50": round(pct_50, 1),
        "pct_above_200": round(pct_200, 1),
        "pct_above_21e": round(pct_21e, 1),
        "trend_50": round(trend_50, 1),
        "pct_50_series": pct_50_series,
    }


def compute_ad_metrics(constituents: dict[str, pd.DataFrame]) -> dict:
    """Metric 2: Advance/Decline ratio and new highs/lows."""
    advancing_5d = 0
    declining_5d = 0
    new_20d_highs = 0
    new_20d_lows = 0
    new_63d_highs = 0
    new_63d_lows = 0
    total = len(constituents)

    for ticker, df in constituents.items():
        close = df["Close"]
        if len(close) < 5:
            continue

        # 5-day return
        ret_5d = (close.iloc[-1] / close.iloc[-5] - 1) if len(close) >= 5 else 0
        if ret_5d > 0:
            advancing_5d += 1
        elif ret_5d < 0:
            declining_5d += 1

        # New 20-day highs/lows
        if len(close) >= 20:
            high_20 = close.iloc[-20:].max()
            low_20 = close.iloc[-20:].min()
            if close.iloc[-1] >= high_20 * 0.99:  # within 1% of 20d high
                new_20d_highs += 1
            if close.iloc[-1] <= low_20 * 1.01:
                new_20d_lows += 1

        # New 63-day highs/lows
        if len(close) >= 63:
            high_63 = close.iloc[-63:].max()
            low_63 = close.iloc[-63:].min()
            if close.iloc[-1] >= high_63 * 0.99:
                new_63d_highs += 1
            if close.iloc[-1] <= low_63 * 1.01:
                new_63d_lows += 1

    ad_ratio = advancing_5d / max(declining_5d, 1)

    return {
        "advancing_5d": advancing_5d,
        "declining_5d": declining_5d,
        "ad_ratio": round(ad_ratio, 1),
        "new_20d_highs": new_20d_highs,
        "new_20d_lows": new_20d_lows,
        "new_63d_highs": new_63d_highs,
        "new_63d_lows": new_63d_lows,
    }


def compute_ew_cw_divergence(
    constituents: dict[str, pd.DataFrame],
    etf_df: pd.DataFrame | None,
) -> dict:
    """Metric 3: Equal-weight vs cap-weight return divergence."""
    if not constituents or etf_df is None:
        return {"ew_1w": 0, "cw_1w": 0, "ew_4w": 0, "cw_4w": 0, "div_4w": 0}

    etf_close = etf_df["Close"]

    # CW returns (the actual ETF)
    cw_1w = (etf_close.iloc[-1] / etf_close.iloc[-5] - 1) * 100 if len(etf_close) >= 5 else 0
    cw_4w = (etf_close.iloc[-1] / etf_close.iloc[-20] - 1) * 100 if len(etf_close) >= 20 else 0

    # EW returns (mean of all constituents)
    rets_1w = []
    rets_4w = []
    for ticker, df in constituents.items():
        c = df["Close"]
        if len(c) >= 5:
            rets_1w.append((c.iloc[-1] / c.iloc[-5] - 1) * 100)
        if len(c) >= 20:
            rets_4w.append((c.iloc[-1] / c.iloc[-20] - 1) * 100)

    ew_1w = np.mean(rets_1w) if rets_1w else 0
    ew_4w = np.mean(rets_4w) if rets_4w else 0

    return {
        "ew_1w": round(ew_1w, 2),
        "cw_1w": round(cw_1w, 2),
        "ew_4w": round(ew_4w, 2),
        "cw_4w": round(cw_4w, 2),
        "div_4w": round(cw_4w - ew_4w, 2),
    }


def detect_thrust_collapse(pct_50_series: list[float]) -> list[str]:
    """Metric 4: Detect breadth thrust or collapse in %above SMA50 series."""
    alerts = []
    if len(pct_50_series) < 11:
        return alerts

    current = pct_50_series[-1]

    # Look for thrust/collapse in the last 10 days
    for window_start in range(max(0, len(pct_50_series) - 15), len(pct_50_series) - 10):
        past_val = pct_50_series[window_start]
        # Thrust: <40% -> >60% within 10 days
        if past_val < 40 and current > 60:
            alerts.append(f"THRUST -- %above 50MA jumped {past_val:.0f}% to {current:.0f}% in {len(pct_50_series) - 1 - window_start} days")
            break
        # Collapse: >60% -> <40% within 10 days
        if past_val > 60 and current < 40:
            alerts.append(f"COLLAPSE -- %above 50MA dropped {past_val:.0f}% to {current:.0f}% in {len(pct_50_series) - 1 - window_start} days")
            break

    return alerts


def compute_breadth_score(ma: dict, ad: dict, div: dict) -> tuple[float, str]:
    """Compute composite breadth health score."""
    # Normalize A/D ratio: 2.0+ = 1.0, 1.0 = 0.5, 0.5 = 0.25, 0 = 0
    ad_norm = min(ad["ad_ratio"] / 2.0, 1.0)

    # EW/CW divergence penalty: 0 if aligned, up to 0.5 if >4% divergence
    div_penalty = min(abs(div["div_4w"]) / 8.0, 0.5)

    score = (
        0.30 * (ma["pct_above_50"] / 100)
        + 0.20 * (ma["pct_above_200"] / 100)
        + 0.25 * ad_norm
        + 0.25 * (1.0 - div_penalty)
    )
    score = round(score, 2)

    if score >= 0.70:
        status = "STRONG"
    elif score >= 0.50:
        status = "HEALTHY"
    elif score >= 0.30:
        status = "MIXED"
    else:
        status = "WEAK"

    return score, status


# ── Output Formatting ────────────────────────────────────────────────────────

def format_breadth_table(sector_results: list[dict]) -> str:
    """Build monospace breadth table for Discord."""
    lines = []
    lines.append("**MARKET BREADTH REPORT -- Sector Health**")
    lines.append("```")
    lines.append(
        f"{'SECTOR':<6} {'NAME':<14} {'>50MA':>5} {'>200MA':>6} {'>21EMA':>6} "
        f"{'A/D':>5} {'NH/NL':>6} {'EW-CW':>6} {'SCORE':>6} STATUS"
    )
    lines.append("-" * 78)

    for r in sorted(sector_results, key=lambda x: -x["score"]):
        nh_nl = f"{r['ad']['new_20d_highs']}/{r['ad']['new_20d_lows']}"
        div_str = f"{r['div']['div_4w']:+.1f}%"
        status = r["status"]
        if abs(r["div"]["div_4w"]) > 2.0:
            status += " !"

        lines.append(
            f"{r['sector']:<6} {r['name']:<14} {r['ma']['pct_above_50']:>4.0f}% "
            f"{r['ma']['pct_above_200']:>5.0f}% {r['ma']['pct_above_21e']:>5.0f}% "
            f"{r['ad']['ad_ratio']:>4.1f}:1 {nh_nl:>6} {div_str:>6} "
            f"{r['score']:>5.2f}  {status}"
        )

    lines.append("```")
    return "\n".join(lines)


def format_alerts(sector_results: list[dict]) -> str:
    """Build alerts section."""
    alerts = []
    for r in sector_results:
        sector = r["sector"]
        # Narrow leadership
        if abs(r["div"]["div_4w"]) > 2.0:
            direction = "CW > EW" if r["div"]["div_4w"] > 0 else "EW > CW"
            alerts.append(
                f"  {sector}: NARROW LEADERSHIP -- {direction} by "
                f"{abs(r['div']['div_4w']):.1f}% (4W)"
            )
        # Thrust/collapse
        for a in r.get("thrust_alerts", []):
            if "THRUST" in a:
                alerts.append(f"  {sector}: Breadth {a}")
            else:
                alerts.append(f"  {sector}: Breadth {a}")
        # Trend deterioration
        if r["ma"]["trend_50"] < -15:
            alerts.append(
                f"  {sector}: DETERIORATING -- %above 50MA dropped "
                f"{r['ma']['trend_50']:+.0f}pp in 10 days"
            )
        elif r["ma"]["trend_50"] > 15:
            alerts.append(
                f"  {sector}: IMPROVING -- %above 50MA gained "
                f"{r['ma']['trend_50']:+.0f}pp in 10 days"
            )

    if not alerts:
        return ""
    return "**ALERTS:**\n```\n" + "\n".join(alerts) + "\n```"


# ── Chart Rendering ──────────────────────────────────────────────────────────

def render_heatmap(sector_results: list[dict]) -> io.BytesIO:
    """Render breadth heatmap: sectors (rows) x metrics (columns)."""
    sectors = [r["sector"] for r in sorted(sector_results, key=lambda x: -x["score"])]
    metrics = [">50MA", ">200MA", ">21EMA", "A/D", "Score"]

    data = []
    for r in sorted(sector_results, key=lambda x: -x["score"]):
        ad_norm = min(r["ad"]["ad_ratio"] / 2.0, 1.0) * 100
        data.append([
            r["ma"]["pct_above_50"],
            r["ma"]["pct_above_200"],
            r["ma"]["pct_above_21e"],
            ad_norm,
            r["score"] * 100,
        ])
    data = np.array(data)

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=0, vmax=100)

    ax.set_xticks(range(len(metrics)))
    ax.set_xticklabels(metrics, color="white", fontsize=10)
    ax.set_yticks(range(len(sectors)))
    ax.set_yticklabels(sectors, color="white", fontsize=10)

    # Annotate cells
    for i in range(len(sectors)):
        for j in range(len(metrics)):
            val = data[i, j]
            color = "white" if val < 40 or val > 80 else "black"
            if j == 4:  # Score column
                txt = f"{val / 100:.2f}"
            elif j == 3:  # A/D column
                txt = f"{sector_results[i]['ad']['ad_ratio']:.1f}"
            else:
                txt = f"{val:.0f}%"
            ax.text(j, i, txt, ha="center", va="center", color=color, fontsize=9, fontweight="bold")

    ax.set_title("Market Breadth Heatmap", color="white", fontsize=13, pad=10)
    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.ax.tick_params(colors="white", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#444")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor="#1a1a2e")
    plt.close(fig)
    buf.seek(0)
    return buf


def render_breadth_momentum(sector_results: list[dict]) -> io.BytesIO:
    """Render line chart: % above SMA(50) over last 3 months per sector."""
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    colors = plt.cm.tab10(np.linspace(0, 1, 11))

    for i, r in enumerate(sorted(sector_results, key=lambda x: -x["score"])):
        series = r["ma"].get("pct_50_series", [])
        if series:
            ax.plot(range(len(series)), series, color=colors[i % len(colors)],
                    label=r["sector"], linewidth=1.5, alpha=0.85)

    # Threshold lines
    ax.axhline(60, color="#4CAF50", linestyle="--", alpha=0.4, linewidth=1)
    ax.axhline(40, color="#F44336", linestyle="--", alpha=0.4, linewidth=1)
    ax.text(0, 61, "Healthy (60%)", color="#4CAF50", fontsize=8, alpha=0.6)
    ax.text(0, 35, "Weak (40%)", color="#F44336", fontsize=8, alpha=0.6)

    ax.set_ylabel("% Above SMA(50)", color="white", fontsize=11)
    ax.set_xlabel("Trading Days (recent 3 months)", color="white", fontsize=10)
    ax.set_title("Breadth Momentum -- % Above 50-Day MA", color="white", fontsize=13, pad=10)
    ax.tick_params(colors="white", labelsize=9)
    ax.legend(loc="upper left", fontsize=8, ncol=3, framealpha=0.3,
              facecolor="#1a1a2e", edgecolor="#444", labelcolor="white")
    ax.grid(True, alpha=0.15, color="#444")
    for spine in ax.spines.values():
        spine.set_color("#444")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor="#1a1a2e")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting Market Breadth Scanner")

    # Determine which sectors to scan
    if len(sys.argv) > 1:
        target_sectors = {s.upper(): CW_SECTORS.get(s.upper(), s.upper()) for s in sys.argv[1:]}
        print(f"  CLI override: {', '.join(target_sectors)}")
    else:
        target_sectors = dict(CW_SECTORS)
        print(f"  Scanning all {len(target_sectors)} sectors")

    # Load holdings
    holdings = load_etf_holdings()

    # Collect all unique tickers to fetch
    sector_tickers = {}  # sector -> list of tickers
    all_tickers = set()
    for sector in target_sectors:
        info = holdings.get(sector)
        if not info or not info.get("holdings"):
            print(f"  {sector}: no holdings in etf-holdings.json, skipping")
            continue
        tickers = info["holdings"]
        sector_tickers[sector] = tickers
        all_tickers.update(tickers)
    all_tickers.update(target_sectors.keys())  # also fetch ETF prices

    print(f"  Fetching {len(all_tickers)} unique tickers (1y daily)...")

    # Batch fetch all data
    ohlcv = batch_fetch(list(all_tickers), period="1y")
    fetched_count = len(ohlcv)
    print(f"  Fetched {fetched_count}/{len(all_tickers)} tickers")

    # Compute breadth for each sector
    sector_results = []
    for sector, name in target_sectors.items():
        if sector not in sector_tickers:
            continue
        tickers = sector_tickers[sector]
        constituents = {t: ohlcv[t] for t in tickers if t in ohlcv}
        if len(constituents) < 5:
            print(f"  {sector}: only {len(constituents)} constituents fetched, skipping")
            continue

        etf_df = ohlcv.get(sector)

        # Compute all 4 metrics
        ma = compute_ma_breadth(constituents)
        ad = compute_ad_metrics(constituents)
        div = compute_ew_cw_divergence(constituents, etf_df)
        thrust_alerts = detect_thrust_collapse(ma.get("pct_50_series", []))
        score, status = compute_breadth_score(ma, ad, div)

        sector_results.append({
            "sector": sector,
            "name": name,
            "ma": ma,
            "ad": ad,
            "div": div,
            "thrust_alerts": thrust_alerts,
            "score": score,
            "status": status,
            "n_constituents": len(constituents),
        })
        print(f"  {sector} ({name}): {len(constituents)} stocks, score={score:.2f} ({status})")

    if not sector_results:
        print("No sectors with sufficient data")
        return

    # ── Post results to Discord ──────────────────────────────────────────

    # Header
    header = (
        f"**Market Breadth Scanner** ({now_et.strftime('%a %b %d %I:%M %p ET')})\n"
        f"Sectors: {len(sector_results)} | "
        f"Stocks: {sum(r['n_constituents'] for r in sector_results)}"
    )
    send_discord_text(header)

    # Main breadth table
    table = format_breadth_table(sector_results)
    send_discord_text(table)
    print(f"  Posted breadth table ({len(table)} chars)")

    # Alerts
    alerts = format_alerts(sector_results)
    if alerts:
        send_discord_text(alerts)
        print(f"  Posted alerts ({len(alerts)} chars)")

    # Heatmap chart
    buf = render_heatmap(sector_results)
    if buf.getbuffer().nbytes > 0:
        send_discord_image(buf, "breadth_heatmap.png")
        print("  Posted heatmap chart")

    # Breadth momentum line chart
    buf = render_breadth_momentum(sector_results)
    if buf.getbuffer().nbytes > 0:
        send_discord_image(buf, "breadth_momentum.png")
        print("  Posted momentum chart")

    # ── Russell 3000 52-week high/low breadth ────────────────────────────────
    try:
        universe = build_russell_3000_universe()
        if universe:
            print(f"  Russell universe: {len(universe)} names (top of $-weighted US listings)")
            stats = scan_russell_52w_breadth(universe)
            for chunk in format_52w_breadth(stats):
                send_discord_text(chunk)
            print(f"  52w breadth: {len(stats['nh'])} NH / {len(stats['nl'])} NL across {stats['scanned']} stocks")
        else:
            print("  Russell universe unavailable; skipping 52w breadth")
    except Exception as e:
        print(f"  52w breadth section failed: {e}", file=sys.stderr)

    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} Market Breadth Scanner complete")


if __name__ == "__main__":
    main()
