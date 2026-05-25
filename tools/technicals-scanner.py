"""
Technical Analysis Scanner
Runs at market close. Two outputs:

1. Index dashboard — Daily index levels (SPY/QQQ/IWM): MAs, VWAP, Bollinger, RSI
2. Trade alerts — ONLY when a holding triggers a significant signal

Signals tracked:
  - 20/50/200 SMA crossovers and price vs MA positioning
  - Rolling 20-day VWAP
  - Anchored VWAP from last earnings date
  - RSI extremes (>75 overbought, <25 oversold)
  - Bollinger squeeze → breakout
  - MACD crossover (histogram sign flip)
  - 3-month high/low breach
  - Volume spike (>2.5x 20-day avg)

Posts to Discord via webhook.
Schedule: cron at 1:00 PM PST / 4:00 PM EST weekdays (before portfolio tracker)
"""

import json
import requests
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")

# Use the project directory as base
PROJECT_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)
TOOLS_DIR = Path(__file__).resolve().parent

# Discord webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471470797687357557/sDi1EQwqIItykMRbV3_JEecRv-yitMyg8apus_ko8bMzKJZ2RNZbbQPKmn7VguraMN4G"

# ─── TECHNICAL CALCULATIONS ───────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str = "1y") -> "pd.DataFrame | None":
    """Fetch OHLCV data from Yahoo Finance chart API (no yfinance library)."""
    import pandas as pd
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval=1d"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
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
    except:
        return None


def batch_download(tickers: list[str], period: str = "1y") -> dict:
    """Download OHLCV data for all tickers via Yahoo chart API."""
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

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


def compute_technicals(ticker: str, period: str = "1y", hist=None) -> dict | None:
    """Compute all technical indicators for a ticker. Accepts pre-downloaded hist."""
    try:
        if hist is None:
            hist = fetch_ohlcv(ticker, period)
        if hist is None or hist.empty or len(hist) < 50:
            return None

        close = hist["Close"]
        high = hist["High"]
        low = hist["Low"]
        volume = hist["Volume"]
        price = close.iloc[-1]
        prev_close = close.iloc[-2] if len(close) > 1 else price

        result = {"ticker": ticker, "price": round(price, 2)}

        # ── Moving Averages ──
        sma_20 = close.rolling(20).mean()
        sma_50 = close.rolling(50).mean()
        sma_200 = close.rolling(200).mean() if len(close) >= 200 else None

        result["sma_20"] = round(sma_20.iloc[-1], 2)
        result["sma_50"] = round(sma_50.iloc[-1], 2)
        result["sma_200"] = round(sma_200.iloc[-1], 2) if sma_200 is not None and not np.isnan(sma_200.iloc[-1]) else None

        # Price vs MAs
        result["above_20"] = price > sma_20.iloc[-1]
        result["above_50"] = price > sma_50.iloc[-1]
        result["above_200"] = price > sma_200.iloc[-1] if result["sma_200"] else None

        # MA crossover detection (today vs yesterday)
        result["signals"] = []

        # Golden/Death cross (50/200)
        if result["sma_200"] and len(sma_50) > 1 and sma_200 is not None:
            prev_50 = sma_50.iloc[-2]
            prev_200 = sma_200.iloc[-2]
            curr_50 = sma_50.iloc[-1]
            curr_200 = sma_200.iloc[-1]
            if not np.isnan(prev_200):
                if prev_50 <= prev_200 and curr_50 > curr_200:
                    result["signals"].append("GOLDEN CROSS (50 crossed above 200 SMA)")
                elif prev_50 >= prev_200 and curr_50 < curr_200:
                    result["signals"].append("DEATH CROSS (50 crossed below 200 SMA)")

        # 20/50 crossover
        if len(sma_20) > 1 and len(sma_50) > 1:
            if sma_20.iloc[-2] <= sma_50.iloc[-2] and sma_20.iloc[-1] > sma_50.iloc[-1]:
                result["signals"].append("BULLISH 20/50 CROSS (20 SMA crossed above 50)")
            elif sma_20.iloc[-2] >= sma_50.iloc[-2] and sma_20.iloc[-1] < sma_50.iloc[-1]:
                result["signals"].append("BEARISH 20/50 CROSS (20 SMA crossed below 50)")

        # Price crossing key MAs
        if close.iloc[-2] <= sma_50.iloc[-2] and price > sma_50.iloc[-1]:
            result["signals"].append("RECLAIMED 50 SMA")
        elif close.iloc[-2] >= sma_50.iloc[-2] and price < sma_50.iloc[-1]:
            result["signals"].append("LOST 50 SMA")

        if result["sma_200"] and sma_200 is not None and not np.isnan(sma_200.iloc[-2]):
            if close.iloc[-2] <= sma_200.iloc[-2] and price > sma_200.iloc[-1]:
                result["signals"].append("RECLAIMED 200 SMA")
            elif close.iloc[-2] >= sma_200.iloc[-2] and price < sma_200.iloc[-1]:
                result["signals"].append("LOST 200 SMA — TREND BREAK")

        # ── RSI (14-period) ──
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        result["rsi"] = round(rsi.iloc[-1], 1)

        if result["rsi"] >= 75:
            result["signals"].append(f"RSI OVERBOUGHT ({result['rsi']})")
        elif result["rsi"] <= 25:
            result["signals"].append(f"RSI OVERSOLD ({result['rsi']})")

        # ── MACD ──
        ema_12 = close.ewm(span=12).mean()
        ema_26 = close.ewm(span=26).mean()
        macd_line = ema_12 - ema_26
        signal_line = macd_line.ewm(span=9).mean()
        macd_hist = macd_line - signal_line
        result["macd"] = round(macd_line.iloc[-1], 2)
        result["macd_signal"] = round(signal_line.iloc[-1], 2)
        result["macd_hist"] = round(macd_hist.iloc[-1], 2)

        # MACD histogram flip (crossover)
        if len(macd_hist) > 1:
            if macd_hist.iloc[-2] <= 0 and macd_hist.iloc[-1] > 0:
                result["signals"].append("MACD BULLISH CROSSOVER")
            elif macd_hist.iloc[-2] >= 0 and macd_hist.iloc[-1] < 0:
                result["signals"].append("MACD BEARISH CROSSOVER")

        # ── Bollinger Bands ──
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_width = ((bb_upper - bb_lower) / bb_mid) * 100

        result["bb_upper"] = round(bb_upper.iloc[-1], 2)
        result["bb_lower"] = round(bb_lower.iloc[-1], 2)
        result["bb_width"] = round(bb_width.iloc[-1], 1)

        # Bollinger squeeze detection (width at 20-day low then breakout)
        min_width_20 = bb_width.rolling(20).min()
        if len(bb_width) >= 21:
            was_squeezed = bb_width.iloc[-2] <= min_width_20.iloc[-2] * 1.05
            if was_squeezed and price > bb_upper.iloc[-1]:
                result["signals"].append("BOLLINGER SQUEEZE BREAKOUT (upside)")
            elif was_squeezed and price < bb_lower.iloc[-1]:
                result["signals"].append("BOLLINGER SQUEEZE BREAKDOWN (downside)")

        # ── Rolling 20-Day VWAP ──
        tp = (high + low + close) / 3
        rolling_vwap = (tp * volume).rolling(20).sum() / volume.rolling(20).sum()
        result["vwap_20d"] = round(rolling_vwap.iloc[-1], 2)
        result["above_vwap"] = price > rolling_vwap.iloc[-1]

        # ── Volume ──
        avg_vol = volume.rolling(20).mean().iloc[-1]
        today_vol = volume.iloc[-1]
        result["volume_ratio"] = round(today_vol / avg_vol, 1) if avg_vol > 0 else 1.0

        if result["volume_ratio"] >= 2.5:
            result["signals"].append(f"VOLUME SPIKE ({result['volume_ratio']}x average)")

        # ── 3-Month High/Low ──
        high_3m = close.tail(63).max()
        low_3m = close.tail(63).min()
        if price >= high_3m:
            result["signals"].append(f"NEW 3-MONTH HIGH (${price:.2f})")
        elif price <= low_3m:
            result["signals"].append(f"NEW 3-MONTH LOW (${price:.2f})")

        # ── ATR ──
        tr = pd.concat([
            high - low,
            abs(high - close.shift()),
            abs(low - close.shift())
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        result["atr"] = round(atr, 2)
        result["atr_pct"] = round((atr / price) * 100, 1)

        return result

    except Exception as e:
        return None


def compute_anchored_vwap(ticker: str, anchor_date: str, hist=None) -> float | None:
    """Compute VWAP anchored from a specific date. Uses pre-downloaded hist if available."""
    try:
        if hist is None:
            hist = fetch_ohlcv(ticker, "1y")
            if hist is not None:
                hist = hist.loc[anchor_date:]
        else:
            # Slice pre-downloaded data from anchor date
            hist = hist.loc[anchor_date:]
        if hist.empty:
            return None
        tp = (hist["High"] + hist["Low"] + hist["Close"]) / 3
        avwap = (tp * hist["Volume"]).cumsum() / hist["Volume"].cumsum()
        return round(avwap.iloc[-1], 2)
    except:
        return None


def get_last_earnings_date(ticker: str) -> str | None:
    """Find the most recent past earnings date for a ticker via Yahoo chart API."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=6mo&interval=1d&includePrePost=false"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        events = data.get("chart", {}).get("result", [{}])[0].get("events", {})
        earnings = events.get("earnings", {})
        if not earnings:
            return None
        now = datetime.now(ET)
        dates = []
        for ts_key in earnings:
            dt = datetime.fromtimestamp(int(ts_key), tz=ET)
            if dt.date() < now.date():
                dates.append(dt.strftime("%Y-%m-%d"))
        return max(dates) if dates else None
    except:
        return None


# ─── OUTPUT FORMATTERS ────────────────────────────────────────────

def format_index_dashboard(results: list[dict]) -> str:
    """Format index technical levels for #market-dashboard."""
    now_et = datetime.now(ET)
    lines = [f"**Technical Levels** ({now_et.strftime('%a %b %d')})", ""]

    for r in results:
        ticker = r["ticker"]
        price = r["price"]

        # MA positioning summary
        ma_status = []
        if r.get("above_200") is True:
            ma_status.append("above 200")
        elif r.get("above_200") is False:
            ma_status.append("BELOW 200")
        if r["above_50"]:
            ma_status.append("above 50")
        else:
            ma_status.append("below 50")

        # Compact format
        lines.append(f"**{ticker}** ${price:.2f} | RSI {r['rsi']}")
        lines.append(
            f"  20: ${r['sma_20']} | 50: ${r['sma_50']}"
            + (f" | 200: ${r['sma_200']}" if r.get('sma_200') else "")
        )
        lines.append(
            f"  VWAP(20d): ${r['vwap_20d']} | "
            f"BB: ${r['bb_lower']}-${r['bb_upper']}"
        )

        if r.get("avwap_earnings"):
            lines.append(f"  Earnings VWAP: ${r['avwap_earnings']}")

        if r["signals"]:
            for s in r["signals"]:
                lines.append(f"  >> {s}")
        lines.append("")

    return "\n".join(lines).strip()


def format_holding_alerts(results: list[dict]) -> list[str]:
    """Format holding alerts for #trade-alerts. Returns list of alert messages."""
    alerts = []
    for r in results:
        if not r["signals"]:
            continue

        ticker = r["ticker"]
        price = r["price"]

        # Build context line
        context_parts = [f"RSI {r['rsi']}"]
        if r["above_50"]:
            context_parts.append("above 50 SMA")
        else:
            context_parts.append("below 50 SMA")
        if r.get("above_vwap"):
            context_parts.append("above 20D VWAP")
        else:
            context_parts.append("below 20D VWAP")

        msg_lines = [
            f"**Technical Alert: {ticker}** (${price:.2f})",
            "",
        ]
        for s in r["signals"]:
            msg_lines.append(f"- {s}")
        msg_lines.append("")
        msg_lines.append(f"Context: {', '.join(context_parts)}")

        if r.get("avwap_earnings"):
            pos = "above" if price > r["avwap_earnings"] else "BELOW"
            msg_lines.append(f"Earnings VWAP: ${r['avwap_earnings']} (price {pos})")

        alerts.append("\n".join(msg_lines))

    return alerts


# ─── DISCORD SEND ─────────────────────────────────────────────────

def send_discord(message: str):
    """Send message to Discord via webhook."""
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Send failed: {e}")


# ─── MAIN ─────────────────────────────────────────────────────────

def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting technicals scan")

    # ── 1. Batch download all data in one request ──
    with open(TOOLS_DIR / "watchlist.json") as f:
        wl = json.load(f)
    holdings = {t: h for t, h in wl.get("stocks", {}).get("holdings", {}).items()
                if h.get("weight")}

    indexes = ["SPY", "QQQ", "IWM", "DIA"]
    all_tickers = indexes + list(holdings.keys())
    print(f"Batch downloading {len(all_tickers)} tickers...")
    all_data = batch_download(all_tickers)
    print(f"Got data for {len(all_data)} tickers")

    # ── 2. Index Dashboard ──
    index_results = []
    for idx in indexes:
        hist = all_data.get(idx)
        r = compute_technicals(idx, hist=hist) if hist is not None else None
        if r:
            index_results.append(r)

    if index_results:
        dashboard = format_index_dashboard(index_results)
        send_discord(dashboard)
        print(f"Posted index dashboard ({len(dashboard)} chars)")

    # ── 3. Holdings Scan ──
    # Load cached earnings dates (persistent file avoids 16 yfinance lookups)
    ED_CACHE = MEMORY_DIR / "earnings-dates-cache.json"
    ed_cache = {}
    try:
        with open(ED_CACHE) as f:
            ed_cache = json.load(f)
    except:
        pass

    # Also check earnings schedule for recent dates
    try:
        with open(MEMORY_DIR / "earnings-schedule.json") as f:
            sched = json.load(f)
        for date_str, entries in sched.get("by_date", {}).items():
            for entry in entries:
                t = entry["ticker"]
                if t in holdings and date_str < now_et.strftime("%Y-%m-%d"):
                    cached = ed_cache.get(t, {}).get("date", "")
                    if date_str > cached:
                        ed_cache[t] = {"date": date_str, "updated": now_et.strftime("%Y-%m-%d")}
    except:
        pass

    # Find tickers needing yfinance lookup (not cached or stale >7 days)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    needs_lookup = []
    for t in holdings:
        entry = ed_cache.get(t)
        if not entry or not entry.get("date"):
            needs_lookup.append(t)
        else:
            age = (now_et.date() - datetime.strptime(entry["updated"], "%Y-%m-%d").date()).days
            if age > 7:
                needs_lookup.append(t)

    # Parallel yfinance lookup only for uncached tickers
    if needs_lookup:
        def _lookup_ed(ticker):
            ed = get_last_earnings_date(ticker)
            return ticker, ed
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(_lookup_ed, t) for t in needs_lookup]
            for f in as_completed(futures):
                ticker, ed = f.result()
                ed_cache[ticker] = {"date": ed, "updated": now_et.strftime("%Y-%m-%d")}
        # Save cache for next run
        try:
            with open(ED_CACHE, "w") as f:
                json.dump(ed_cache, f, indent=2)
        except:
            pass

    # Compute anchored VWAPs using batch-downloaded data (no extra API calls)
    avwap_results = {}
    for ticker in holdings:
        ed = (ed_cache.get(ticker) or {}).get("date")
        if ed and ticker in all_data:
            avwap = compute_anchored_vwap(ticker, ed, hist=all_data[ticker])
            if avwap:
                avwap_results[ticker] = (ed, avwap)

    holding_results = []
    for ticker in holdings:
        hist = all_data.get(ticker)
        r = compute_technicals(ticker, hist=hist) if hist is not None else None
        if not r:
            continue

        # Add anchored VWAP from parallel results
        if ticker in avwap_results:
            ed, avwap = avwap_results[ticker]
            r["avwap_earnings"] = avwap
            r["avwap_date"] = ed

        holding_results.append(r)

    # Post alerts for holdings with signals
    alerts = format_holding_alerts(holding_results)
    if alerts:
        for alert in alerts[:5]:  # Max 5 alerts per day to avoid spam
            send_discord(alert)
        print(f"Posted {len(alerts)} holding alerts")
    else:
        print("No holding alerts today (quiet is good)")

    # ── 3. Summary to #research ──
    # Compact holdings overview (always post, for reference)
    summary_lines = [f"**Holdings Technicals** ({now_et.strftime('%a %b %d')})", ""]
    for r in sorted(holding_results, key=lambda x: len(x.get("signals", [])), reverse=True):
        ticker = r["ticker"]
        price = r["price"]
        rsi = r["rsi"]

        # Compact MA position
        ma_pos = ""
        if r.get("above_200") is False:
            ma_pos = "< 200"
        elif not r["above_50"]:
            ma_pos = "< 50"
        elif not r["above_20"]:
            ma_pos = "< 20"
        else:
            ma_pos = "> all"

        vwap_pos = ">" if r.get("above_vwap") else "<"

        signals = f" | {'  '.join(r['signals'])}" if r["signals"] else ""
        summary_lines.append(
            f"{ticker} ${price:.2f} | RSI {rsi} | MA: {ma_pos} | VWAP {vwap_pos}{signals}"
        )

    summary = "\n".join(summary_lines)
    send_discord(summary)
    print(f"Posted holdings summary ({len(summary)} chars)")

    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Scan complete")


if __name__ == "__main__":
    main()
