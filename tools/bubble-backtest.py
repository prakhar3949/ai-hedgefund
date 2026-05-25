"""
Backtest harness for bubble-scanner — re-evaluates one ticker at a historical
as-of date.

Usage:  python bubble-backtest.py MU 2026-04-09
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import json
import importlib.util
from pathlib import Path
from datetime import datetime
import pandas as pd

TOOLS_DIR = Path(__file__).resolve().parent

# Load bubble-scanner module by path (hyphenated filename)
spec = importlib.util.spec_from_file_location("bubble_scanner", TOOLS_DIR / "bubble-scanner.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)


def truncate(df, asof_ts):
    if df is None:
        return None
    # df index is tz-aware America/New_York
    cut = df[df.index <= asof_ts]
    return cut if len(cut) >= 50 else None


def main():
    if len(sys.argv) < 3:
        print("usage: python bubble-backtest.py TICKER YYYY-MM-DD [PARENT_ETF]")
        sys.exit(2)
    ticker = sys.argv[1].upper()
    asof = sys.argv[2]
    asof_ts = pd.Timestamp(asof + " 16:00", tz="America/New_York")

    # Find parent ETF (first ETF in etf-holdings containing the ticker)
    with open(TOOLS_DIR / "etf-holdings.json") as f:
        holdings = json.load(f)
    parent_etf = None
    if len(sys.argv) >= 4:
        parent_etf = sys.argv[3].upper()
    else:
        for etf, meta in holdings.items():
            if etf.startswith("_"):
                continue
            if ticker in meta.get("holdings", []):
                parent_etf = etf
                break
    if not parent_etf:
        print(f"No parent ETF found for {ticker}; please pass one explicitly.")
        sys.exit(2)
    print(f"Parent ETF: {parent_etf} ({holdings[parent_etf]['name']})")

    # Fetch 5y range so we have enough history before asof
    print(f"Fetching 5y daily for {ticker}, {parent_etf}, SPY, ^VIX, 11 CW sectors...")
    CW = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLC", "XLB", "XLRE"]
    universe = list(set([ticker, parent_etf, "SPY", "^VIX"] + CW))
    raw = bs.batch_fetch(universe, period="5y")

    # Truncate everything to asof
    data = {t: truncate(df, asof_ts) for t, df in raw.items()}
    spy = data.get("SPY")
    vix = data.get("^VIX")
    if spy is None or vix is None:
        print("Missing SPY or VIX after truncation"); sys.exit(1)
    if data.get(ticker) is None:
        print(f"{ticker} has no data on/before {asof}"); sys.exit(1)
    if data.get(parent_etf) is None:
        print(f"{parent_etf} has no data on/before {asof}"); sys.exit(1)

    print(f"\nAs-of date: {data[ticker].index[-1].strftime('%Y-%m-%d')} (close {data[ticker]['Close'].iloc[-1]:.2f})")

    # Regime
    sector_data = {t: data[t] for t in CW if data.get(t) is not None}
    regime = bs.compute_regime(spy, vix, sector_data)
    print("\n── REGIME ──")
    print(f"  Vol: {regime['vol_regime']}  VIX={regime['vix_level']:.1f} ({regime['vix_pct']:.0f}th pctile)")
    print(f"  Breadth: {regime['breadth']}  ({regime['pct_above_50']:.0f}% >50MA, {regime['pct_above_200']:.0f}% >200MA)")
    print(f"  Gate: {'OPEN' if regime['gate_open'] else 'CLOSED'}")

    # Stage 1 — qualify the parent ETF
    q = bs.qualify_bubble(data[parent_etf], regime)
    print(f"\n── STAGE 1: {parent_etf} qualifier ──")
    print(f"  Classification: {q['classification']}  {bs.fmt_flags(q)}")
    print(f"  C1 1Y return:   {q['ret_1y']*100:+.1f}%  (need > +100%)")
    print(f"  C2 stretch:     {q['stretch']:.2f}σ      (need > 2.0σ)")
    print(f"  C3 3M_ann:      {q['ret_3m_ann']*100:+.1f}%  vs 1Y={q['ret_1y']*100:+.1f}%  (need 3M_ann > 1Y)")
    print(f"  C4 regime gate: {'PASS' if q['c4'] else 'FAIL'}")

    # Bubble days lookback for parent
    pbd = bs.bubble_days(data[parent_etf], regime, lookback=60)
    print(f"  Parent bubble-days (last 60): {pbd}")

    # Stage 3 — entries on ticker
    print(f"\n── STAGE 3: {ticker} entry signals ──")
    entries = bs.detect_entries(data[ticker], data[parent_etf], pbd)
    if entries:
        for e in entries:
            print(f"  ✓ Entry {e['type']} — {e['name']}: {e['detail']}")
        size = bs.vol_adjusted_size(data[ticker], q["classification"])
        print(f"  Vol-adjusted size: {size*100:.2f}%" if size else "  Size: n/a")
    else:
        print("  (no entry signals firing)")

    # Per-entry diagnostics
    print(f"\n── ENTRY DIAGNOSTICS ──")
    sdf = data[ticker]
    c2 = sdf["Close"]; h2 = sdf["High"]; l2 = sdf["Low"]; v2 = sdf["Volume"]
    px2 = float(c2.iloc[-1])
    atr_now = float(bs.atr(sdf, 14).iloc[-1])
    ema21_now = float(bs.ema(c2, 21).iloc[-1])
    s50_now = float(bs.sma(c2, 50).iloc[-1])
    s200_now = float(bs.sma(c2, 200).iloc[-1])
    vol20 = float(v2.rolling(20).mean().iloc[-1])
    vol_today = float(v2.iloc[-1])
    adx_now = float(bs.adx(sdf, 14).iloc[-1])
    rsi_now = float(bs.rsi(c2, 14).iloc[-1])
    print(f"  ATR(14)={atr_now:.2f}  vol_today={vol_today/1e6:.1f}M vs avg20={vol20/1e6:.1f}M ({vol_today/vol20:.2f}×)")
    print(f"  ADX={adx_now:.0f}  RSI={rsi_now:.1f}")
    # Entry A diagnostics for each base length
    for bl in (5, 7, 10):
        bh = float(h2.iloc[-(bl+1):-1].max())
        blow = float(l2.iloc[-(bl+1):-1].min())
        rng = bh - blow
        print(f"  A({bl}d): base ${blow:.2f}-${bh:.2f} = {rng/atr_now:.2f}×ATR  | px>{bh:.2f}? {'Y' if px2>bh else 'N'}  | tight<1.5×ATR? {'Y' if rng<1.5*atr_now else 'N'}  | vol>1.5×? {'Y' if vol_today>1.5*vol20 else 'N'}  | ADX>25? {'Y' if adx_now>25 else 'N'}")
    # Entry B
    near_e21 = abs(px2 - ema21_now) < atr_now
    near_s50 = abs(px2 - s50_now) < atr_now and c2.iloc[-10:].max() > s50_now + atr_now
    print(f"  B: near EMA21 (within 1×ATR)? {'Y' if near_e21 else 'N'} (gap={px2-ema21_now:+.2f}, ATR={atr_now:.2f})  | near SMA50? {'Y' if near_s50 else 'N'}  | RSI 40-55? {'Y' if 40<=rsi_now<=55 else 'N'} ({rsi_now:.0f})")
    # Entry E
    prior_h = float(h2.iloc[-2]); prior_l = float(l2.iloc[-2])
    inside = prior_h < float(h2.iloc[-3]) and prior_l > float(l2.iloc[-3])
    ranges7 = (h2 - l2).iloc[-8:-1]
    nr7 = float(ranges7.iloc[-1]) == float(ranges7.min())
    print(f"  E: prior day inside? {'Y' if inside else 'N'}  | NR7? {'Y' if nr7 else 'N'}  | px>{prior_h:.2f}? {'Y' if px2>prior_h else 'N'}  | vol>1.2×? {'Y' if vol_today>1.2*vol20 else 'N'}")

    # Stage 4 — exits on ticker
    print(f"\n── STAGE 4: {ticker} exit signals ──")
    exits = bs.detect_exits(data[ticker])
    if exits["tier"]:
        print(f"  Tier: {exits['tier']}")
        for tr in exits["triggers"]:
            print(f"    • {tr}")
    else:
        print("  (no exit triggers)")

    # Quick diagnostics — recent price context
    c = data[ticker]["Close"]
    print(f"\n── {ticker} CONTEXT ──")
    if len(c) >= 252:
        print(f"  1Y return:   {(c.iloc[-1]/c.iloc[-252]-1)*100:+.1f}%")
    if len(c) >= 63:
        print(f"  3M return:   {(c.iloc[-1]/c.iloc[-63]-1)*100:+.1f}%")
    if len(c) >= 21:
        print(f"  1M return:   {(c.iloc[-1]/c.iloc[-21]-1)*100:+.1f}%")
    if len(c) >= 5:
        print(f"  1W return:   {(c.iloc[-1]/c.iloc[-5]-1)*100:+.1f}%")
    ema21 = bs.ema(c, 21).iloc[-1]
    s50 = bs.sma(c, 50).iloc[-1]
    s200 = bs.sma(c, 200).iloc[-1]
    r14 = bs.rsi(c, 14).iloc[-1]
    print(f"  Price={c.iloc[-1]:.2f}  EMA21={ema21:.2f}  SMA50={s50:.2f}  SMA200={s200:.2f}  RSI14={r14:.1f}")


if __name__ == "__main__":
    main()
