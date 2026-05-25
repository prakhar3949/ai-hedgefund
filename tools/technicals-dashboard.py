"""
Technical Dashboard — Daily after-close scanner for watchlist tickers.

Scans for:
  1. Upside Reversal — lower low than yesterday but closed above yesterday's close
  2. Power of Three (PoT) — swept below prev low, closed near/above prev high (ICT)
  3. OOPS Reversal — gapped below prev low, recovered to close above it (Larry Williams)
  4. Relative Strength vs SPY — 1W/4W/12W composite RS ranking
  5. Full Technicals — SMA crossovers, RSI, MACD, Bollinger, volume spike, VWAP, 3mo hi/lo

Data source: Yahoo Finance chart API (no API key, no yfinance dependency)
Run daily after market close (~4:30 PM ET).
"""

import json
import time
import requests
import numpy as np
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

PROJECT_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

WATCHLIST_FILE = PROJECT_DIR / "tools" / "watchlist.json"
RS_STATE_FILE = MEMORY_DIR / "relative-strength-prev.json"

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1470466815397335183/GZyX60SqadXRFM1OFTwAJz2l9p5GGheseUCKQ370jtE0pxJ3UHNWHQpbDWpDOAWd-CHK"


def send_discord(message: str):
    """Send message to Discord via webhook."""
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Send failed: {e}")


# ─── DATA FETCHING ───────────────────────────────────────────────

def fetch_ohlcv(ticker: str, range_: str = "1y") -> dict | None:
    """Fetch OHLCV data from Yahoo Finance chart API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_}&interval=1d"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        quote = result[0]["indicators"]["quote"][0]
        timestamps = result[0]["timestamp"]
        n = len(timestamps)

        # Build arrays, filtering out None values at the end
        opens = [quote["open"][i] for i in range(n)]
        highs = [quote["high"][i] for i in range(n)]
        lows = [quote["low"][i] for i in range(n)]
        closes = [quote["close"][i] for i in range(n)]
        volumes = [quote["volume"][i] for i in range(n)]

        # Find valid data range (skip None entries)
        valid = []
        for i in range(n):
            if all(v is not None for v in [opens[i], highs[i], lows[i], closes[i], volumes[i]]):
                valid.append(i)

        if len(valid) < 50:
            return None

        return {
            "open": np.array([opens[i] for i in valid]),
            "high": np.array([highs[i] for i in valid]),
            "low": np.array([lows[i] for i in valid]),
            "close": np.array([closes[i] for i in valid]),
            "volume": np.array([volumes[i] for i in valid], dtype=float),
        }
    except Exception as e:
        print(f"  {ticker}: fetch error: {e}")
        return None


# ─── REVERSAL PATTERNS ──────────────────────────────────────────

def detect_upside_reversal(ohlcv: dict) -> bool:
    """Today's low < yesterday's low BUT today's close > yesterday's close."""
    if len(ohlcv["close"]) < 2:
        return False
    today_low = ohlcv["low"][-1]
    prev_low = ohlcv["low"][-2]
    today_close = ohlcv["close"][-1]
    prev_close = ohlcv["close"][-2]
    return today_low < prev_low and today_close > prev_close


def detect_power_of_three(ohlcv: dict) -> bool:
    """ICT Power of Three: swept below prev low (manipulation), closed near/above prev high."""
    if len(ohlcv["close"]) < 2:
        return False
    today_low = ohlcv["low"][-1]
    today_close = ohlcv["close"][-1]
    prev_low = ohlcv["low"][-2]
    prev_high = ohlcv["high"][-2]
    prev_range = prev_high - prev_low
    # Swept below prev low AND closed within top 25% of prev range or above prev high
    threshold = prev_high - (prev_range * 0.25)
    return today_low < prev_low and today_close >= threshold


def detect_oops_reversal(ohlcv: dict) -> bool:
    """Larry Williams OOPS: gapped below prev low on open, recovered to close above it."""
    if len(ohlcv["close"]) < 2:
        return False
    today_open = ohlcv["open"][-1]
    today_close = ohlcv["close"][-1]
    prev_low = ohlcv["low"][-2]
    return today_open < prev_low and today_close > prev_low


# ─── TECHNICAL INDICATORS ───────────────────────────────────────

def compute_sma(close: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average."""
    if len(close) < period:
        return np.full(len(close), np.nan)
    result = np.full(len(close), np.nan)
    for i in range(period - 1, len(close)):
        result[i] = np.mean(close[i - period + 1:i + 1])
    return result


def compute_ema(close: np.ndarray, span: int) -> np.ndarray:
    """Exponential moving average."""
    alpha = 2 / (span + 1)
    result = np.zeros(len(close))
    result[0] = close[0]
    for i in range(1, len(close)):
        result[i] = alpha * close[i] + (1 - alpha) * result[i - 1]
    return result


def compute_rsi(close: np.ndarray, period: int = 14) -> float:
    """RSI (14-period)."""
    if len(close) < period + 1:
        return 50.0
    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def compute_technicals(ticker: str, ohlcv: dict) -> dict:
    """Compute full technical analysis for a ticker."""
    close = ohlcv["close"]
    high = ohlcv["high"]
    low = ohlcv["low"]
    volume = ohlcv["volume"]
    open_ = ohlcv["open"]

    price = close[-1]
    prev_close = close[-2] if len(close) > 1 else price

    result = {"ticker": ticker, "price": round(price, 2), "signals": []}

    # ── Reversal Patterns ──
    if detect_upside_reversal(ohlcv):
        result["signals"].append("UPSIDE REVERSAL")
    if detect_power_of_three(ohlcv):
        result["signals"].append("POWER OF THREE (PoT)")
    if detect_oops_reversal(ohlcv):
        result["signals"].append("OOPS REVERSAL")

    # ── Moving Averages ──
    sma_20 = compute_sma(close, 20)
    sma_50 = compute_sma(close, 50)
    sma_200 = compute_sma(close, 200) if len(close) >= 200 else None

    result["sma_20"] = round(sma_20[-1], 2) if not np.isnan(sma_20[-1]) else None
    result["sma_50"] = round(sma_50[-1], 2) if not np.isnan(sma_50[-1]) else None
    result["sma_200"] = round(sma_200[-1], 2) if sma_200 is not None and not np.isnan(sma_200[-1]) else None

    result["above_20"] = price > sma_20[-1] if not np.isnan(sma_20[-1]) else None
    result["above_50"] = price > sma_50[-1] if not np.isnan(sma_50[-1]) else None
    result["above_200"] = price > sma_200[-1] if sma_200 is not None and not np.isnan(sma_200[-1]) else None

    # Golden/Death cross (50/200)
    if sma_200 is not None and len(sma_50) > 1 and not np.isnan(sma_200[-2]) and not np.isnan(sma_50[-2]):
        if sma_50[-2] <= sma_200[-2] and sma_50[-1] > sma_200[-1]:
            result["signals"].append("GOLDEN CROSS (50 > 200 SMA)")
        elif sma_50[-2] >= sma_200[-2] and sma_50[-1] < sma_200[-1]:
            result["signals"].append("DEATH CROSS (50 < 200 SMA)")

    # 20/50 crossover
    if not np.isnan(sma_20[-2]) and not np.isnan(sma_50[-2]):
        if sma_20[-2] <= sma_50[-2] and sma_20[-1] > sma_50[-1]:
            result["signals"].append("BULLISH 20/50 CROSS")
        elif sma_20[-2] >= sma_50[-2] and sma_20[-1] < sma_50[-1]:
            result["signals"].append("BEARISH 20/50 CROSS")

    # Price reclaim/loss of key MAs
    if not np.isnan(sma_50[-2]):
        if close[-2] <= sma_50[-2] and price > sma_50[-1]:
            result["signals"].append("RECLAIMED 50 SMA")
        elif close[-2] >= sma_50[-2] and price < sma_50[-1]:
            result["signals"].append("LOST 50 SMA")

    if sma_200 is not None and not np.isnan(sma_200[-2]):
        if close[-2] <= sma_200[-2] and price > sma_200[-1]:
            result["signals"].append("RECLAIMED 200 SMA")
        elif close[-2] >= sma_200[-2] and price < sma_200[-1]:
            result["signals"].append("LOST 200 SMA")

    # ── RSI ──
    result["rsi"] = compute_rsi(close, 14)
    if result["rsi"] >= 75:
        result["signals"].append(f"RSI OVERBOUGHT ({result['rsi']})")
    elif result["rsi"] <= 25:
        result["signals"].append(f"RSI OVERSOLD ({result['rsi']})")

    # ── MACD ──
    ema_12 = compute_ema(close, 12)
    ema_26 = compute_ema(close, 26)
    macd_line = ema_12 - ema_26
    macd_signal = compute_ema(macd_line, 9)
    macd_hist = macd_line - macd_signal
    result["macd_hist"] = round(macd_hist[-1], 3)

    if len(macd_hist) > 1:
        if macd_hist[-2] <= 0 and macd_hist[-1] > 0:
            result["signals"].append("MACD BULLISH CROSSOVER")
        elif macd_hist[-2] >= 0 and macd_hist[-1] < 0:
            result["signals"].append("MACD BEARISH CROSSOVER")

    # ── Bollinger Bands ──
    if len(close) >= 20:
        bb_mid = sma_20
        bb_std = np.array([np.std(close[max(0, i - 19):i + 1]) for i in range(len(close))])
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_width = np.where(bb_mid > 0, ((bb_upper - bb_lower) / bb_mid) * 100, 0)

        result["bb_upper"] = round(bb_upper[-1], 2) if not np.isnan(bb_upper[-1]) else None
        result["bb_lower"] = round(bb_lower[-1], 2) if not np.isnan(bb_lower[-1]) else None

        # Squeeze detection
        if len(bb_width) >= 21:
            recent_min = np.nanmin(bb_width[-21:-1])
            was_squeezed = bb_width[-2] <= recent_min * 1.05
            if was_squeezed and price > bb_upper[-1]:
                result["signals"].append("BOLLINGER SQUEEZE BREAKOUT (upside)")
            elif was_squeezed and price < bb_lower[-1]:
                result["signals"].append("BOLLINGER SQUEEZE BREAKDOWN (downside)")

    # ── 20-Day Rolling VWAP ──
    if len(close) >= 20:
        tp = (high + low + close) / 3
        vol_sum = np.convolve(volume, np.ones(20), 'valid')
        tpv_sum = np.convolve(tp * volume, np.ones(20), 'valid')
        if len(vol_sum) > 0 and vol_sum[-1] > 0:
            vwap_20d = tpv_sum[-1] / vol_sum[-1]
            result["vwap_20d"] = round(vwap_20d, 2)
            result["above_vwap"] = price > vwap_20d

    # ── Volume Spike ──
    if len(volume) >= 20:
        avg_vol = np.mean(volume[-21:-1])
        today_vol = volume[-1]
        result["vol_ratio"] = round(today_vol / avg_vol, 1) if avg_vol > 0 else 1.0
        if result["vol_ratio"] >= 2.5:
            result["signals"].append(f"VOLUME SPIKE ({result['vol_ratio']}x avg)")

    # ── 3-Month High/Low ──
    if len(close) >= 63:
        high_3m = np.max(close[-63:])
        low_3m = np.min(close[-63:])
        if price >= high_3m:
            result["signals"].append("NEW 3-MONTH HIGH")
        elif price <= low_3m:
            result["signals"].append("NEW 3-MONTH LOW")

    # ── ATR ──
    if len(close) >= 15:
        tr = np.maximum(
            high[-14:] - low[-14:],
            np.maximum(
                np.abs(high[-14:] - close[-15:-1]),
                np.abs(low[-14:] - close[-15:-1])
            )
        )
        atr = np.mean(tr)
        result["atr"] = round(atr, 2)
        result["atr_pct"] = round((atr / price) * 100, 1)

    return result


# ─── RELATIVE STRENGTH ──────────────────────────────────────────

def compute_returns(close: np.ndarray) -> dict:
    """Compute 1W, 4W, 12W returns."""
    price = close[-1]
    ret = {}
    ret["ret_1w"] = round((price / close[-6] - 1) * 100, 2) if len(close) >= 6 else 0.0
    ret["ret_4w"] = round((price / close[-21] - 1) * 100, 2) if len(close) >= 21 else ret["ret_1w"]
    ret["ret_12w"] = round((price / close[-61] - 1) * 100, 2) if len(close) >= 61 else ret["ret_4w"]
    return ret


def compute_relative_strength(ticker_returns: dict, spy_returns: dict) -> dict:
    """Compute RS vs SPY and composite score."""
    rs_1w = round(ticker_returns["ret_1w"] - spy_returns["ret_1w"], 2)
    rs_4w = round(ticker_returns["ret_4w"] - spy_returns["ret_4w"], 2)
    rs_12w = round(ticker_returns["ret_12w"] - spy_returns["ret_12w"], 2)
    composite = round(rs_1w * 0.20 + rs_4w * 0.40 + rs_12w * 0.40, 2)
    return {"rs_1w": rs_1w, "rs_4w": rs_4w, "rs_12w": rs_12w, "composite": composite}


# ─── MAIN ────────────────────────────────────────────────────────

def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting technical dashboard")

    # Load watchlist
    try:
        with open(WATCHLIST_FILE) as f:
            data = json.load(f)
        tickers = data.get("tickers", [])
    except Exception as e:
        print(f"Failed to load watchlist: {e}")
        return

    if not tickers:
        print("No tickers in watchlist")
        return

    # Add SPY for relative strength benchmark
    all_tickers = ["SPY"] + [t for t in tickers if t != "SPY"]
    print(f"Scanning {len(tickers)} watchlist tickers + SPY benchmark")

    # Fetch all OHLCV data
    all_data = {}
    for ticker in all_tickers:
        ohlcv = fetch_ohlcv(ticker, "1y")
        if ohlcv:
            all_data[ticker] = ohlcv
        else:
            print(f"  {ticker}: no data")
        time.sleep(0.3)

    print(f"  Fetched {len(all_data)}/{len(all_tickers)} tickers")

    if "SPY" not in all_data:
        print("ERROR: Could not fetch SPY benchmark")
        return

    spy_returns = compute_returns(all_data["SPY"]["close"])

    # Compute everything for each ticker
    results = []
    for ticker in tickers:
        if ticker not in all_data:
            continue
        ohlcv = all_data[ticker]
        tech = compute_technicals(ticker, ohlcv)
        ret = compute_returns(ohlcv["close"])
        rs = compute_relative_strength(ret, spy_returns)
        tech.update(ret)
        tech.update(rs)
        results.append(tech)

    if not results:
        print("No results computed")
        return

    # ── BUILD DASHBOARD ──

    # 1. Reversal Patterns (only tickers that triggered)
    reversal_patterns = ["UPSIDE REVERSAL", "POWER OF THREE (PoT)", "OOPS REVERSAL"]
    triggered = []
    for r in results:
        patterns = [s for s in r["signals"] if s in reversal_patterns]
        if patterns:
            triggered.append((r["ticker"], r["price"], patterns))

    msg1_lines = [f"**Technical Dashboard** ({now_et.strftime('%a %b %d')})", ""]

    if triggered:
        msg1_lines.append("**--- REVERSAL PATTERNS ---**")
        for ticker, price, patterns in triggered:
            msg1_lines.append(f"  **{ticker}** ${price:.2f} — {', '.join(patterns)}")
        msg1_lines.append("")
    else:
        msg1_lines.append("*No reversal patterns triggered today.*")
        msg1_lines.append("")

    # 2. Technical Signals (tickers with any non-reversal signal)
    tech_signals = []
    for r in results:
        non_reversal = [s for s in r["signals"] if s not in reversal_patterns]
        if non_reversal:
            tech_signals.append((r["ticker"], r["price"], non_reversal))

    if tech_signals:
        msg1_lines.append("**--- TECHNICAL SIGNALS ---**")
        for ticker, price, sigs in tech_signals:
            sig_str = " | ".join(sigs[:3])
            if len(sigs) > 3:
                sig_str += f" +{len(sigs) - 3} more"
            msg1_lines.append(f"  **{ticker}** ${price:.2f} — {sig_str}")
        msg1_lines.append("")

    msg1 = "\n".join(msg1_lines)
    send_discord(msg1)
    print(f"Posted reversal + signals ({len(msg1)} chars)")
    time.sleep(0.5)

    # 3. Relative Strength Rankings
    results.sort(key=lambda x: x["composite"], reverse=True)

    # Load previous rankings for shift detection
    prev_ranks = {}
    try:
        with open(RS_STATE_FILE) as f:
            prev_data = json.load(f)
            prev_ranks = {r["ticker"]: i + 1 for i, r in enumerate(prev_data.get("rankings", []))}
    except:
        pass

    spy_ret = spy_returns
    rs_lines = [f"**Relative Strength Rankings** ({now_et.strftime('%a %b %d')})", ""]
    rs_lines.append(f"SPY: 1W={spy_ret['ret_1w']:+.1f}% | 4W={spy_ret['ret_4w']:+.1f}% | 12W={spy_ret['ret_12w']:+.1f}%")
    rs_lines.append("")
    rs_lines.append("```")
    rs_lines.append(f"{'#':>2} {'Tkr':<6} {'RS(C)':>6} {'1W':>6} {'4W':>6} {'12W':>6}  Shift")
    rs_lines.append("-" * 48)

    for i, r in enumerate(results):
        rank = i + 1
        prev_rank = prev_ranks.get(r["ticker"])
        if prev_rank:
            shift = prev_rank - rank
            shift_str = f"+{shift}" if shift > 0 else str(shift) if shift < 0 else "="
        else:
            shift_str = "NEW"

        rs_lines.append(
            f"{rank:>2} {r['ticker']:<6} {r['composite']:>+6.1f} "
            f"{r['rs_1w']:>+6.1f} {r['rs_4w']:>+6.1f} {r['rs_12w']:>+6.1f}  {shift_str:>4}"
        )

    rs_lines.append("```")

    # Leaders / Laggards
    leaders = [r for r in results[:3] if r["composite"] > 0]
    laggards = [r for r in results[-3:] if r["composite"] < 0]
    if leaders:
        leader_str = ", ".join(f"{r['ticker']}({r['composite']:+.1f})" for r in leaders)
        rs_lines.append(f"Leaders: {leader_str}")
    if laggards:
        laggard_str = ", ".join(f"{r['ticker']}({r['composite']:+.1f})" for r in laggards)
        rs_lines.append(f"Laggards: {laggard_str}")

    rs_msg = "\n".join(rs_lines)
    send_discord(rs_msg)
    print(f"Posted RS rankings ({len(rs_msg)} chars)")
    time.sleep(0.5)

    # 4. Holdings Summary Table
    summary_lines = [f"**Holdings Overview** ({now_et.strftime('%a %b %d')})", ""]
    summary_lines.append("```")
    summary_lines.append(f"{'Tkr':<6} {'Price':>8} {'RSI':>5} {'MACD':>6} {'MA':>6} {'Vol':>5}")
    summary_lines.append("-" * 42)

    for r in sorted(results, key=lambda x: len(x.get("signals", [])), reverse=True):
        # MA position shorthand
        if r.get("above_200") is False:
            ma = "<200"
        elif r.get("above_50") is False:
            ma = "<50"
        elif r.get("above_20") is False:
            ma = "<20"
        else:
            ma = ">all"

        vol = f"{r.get('vol_ratio', 1.0):.1f}x"
        macd = f"{r.get('macd_hist', 0):+.2f}"

        summary_lines.append(
            f"{r['ticker']:<6} {r['price']:>8.2f} {r['rsi']:>5.1f} {macd:>6} {ma:>6} {vol:>5}"
        )

    summary_lines.append("```")

    summary_msg = "\n".join(summary_lines)
    send_discord(summary_msg)
    print(f"Posted holdings overview ({len(summary_msg)} chars)")

    # Save RS rankings for next run comparison
    save_data = {
        "date": now_et.strftime("%Y-%m-%d"),
        "rankings": [{"ticker": r["ticker"], "composite": r["composite"]} for r in results],
    }
    with open(RS_STATE_FILE, "w") as f:
        json.dump(save_data, f, indent=2)

    print(f"\n{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} Dashboard complete — "
          f"{len(results)} tickers, {len(triggered)} reversals, {len(tech_signals)} with signals")


if __name__ == "__main__":
    main()
