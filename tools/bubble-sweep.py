"""
Sweep a date range and report every session where bubble-scanner fires an
entry or exit on a given ticker.

Usage:  python bubble-sweep.py MU 2026-03-01 2026-04-20 [PARENT_ETF]
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import json
import importlib.util
from pathlib import Path
import pandas as pd

TOOLS_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bubble_scanner", TOOLS_DIR / "bubble-scanner.py")
bs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bs)


def truncate(df, asof_ts):
    if df is None:
        return None
    cut = df[df.index <= asof_ts]
    return cut if len(cut) >= 252 else None


def main():
    if len(sys.argv) < 4:
        print("usage: python bubble-sweep.py TICKER START_DATE END_DATE [PARENT_ETF]")
        sys.exit(2)
    ticker = sys.argv[1].upper()
    start = pd.Timestamp(sys.argv[2], tz="America/New_York")
    end = pd.Timestamp(sys.argv[3], tz="America/New_York")

    with open(TOOLS_DIR / "etf-holdings.json") as f:
        holdings = json.load(f)
    parent = None
    if len(sys.argv) >= 5:
        parent = sys.argv[4].upper()
    else:
        for etf, meta in holdings.items():
            if etf.startswith("_"): continue
            if ticker in meta.get("holdings", []):
                parent = etf; break
    if not parent:
        print("No parent ETF found"); sys.exit(2)
    print(f"Ticker={ticker} Parent={parent} Range={start.date()}→{end.date()}")

    CW = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLC", "XLB", "XLRE"]
    universe = list(set([ticker, parent, "SPY", "^VIX"] + CW))
    print(f"Fetching 5y data for {len(universe)} symbols...")
    raw = bs.batch_fetch(universe, period="5y")
    if raw.get(ticker) is None or raw.get(parent) is None:
        print("Missing core data"); sys.exit(1)

    # Iterate over each trading day in the ticker's data within the window
    tdf = raw[ticker]
    sessions = tdf[(tdf.index >= start) & (tdf.index <= end + pd.Timedelta(hours=23))].index
    print(f"Scanning {len(sessions)} sessions...\n")

    header = f"{'DATE':<12} {'CLOSE':>8} {'CLS':<12} {'BD':>3} {'ENTRIES':<35} {'EXIT':<18}"
    print(header)
    print("─" * len(header))

    entry_count = 0
    exit_count = 0
    summary_rows = []
    for asof in sessions:
        data = {t: truncate(df, asof) for t, df in raw.items()}
        spy = data.get("SPY"); vix = data.get("^VIX")
        if spy is None or vix is None: continue
        if data.get(ticker) is None or data.get(parent) is None: continue
        sector_data = {t: data[t] for t in CW if data.get(t) is not None}
        regime = bs.compute_regime(spy, vix, sector_data)
        q = bs.qualify_bubble(data[parent], regime)
        pbd = bs.bubble_days(data[parent], regime, lookback=60)
        entries = bs.detect_entries(data[ticker], data[parent], pbd)
        exits = bs.detect_exits(data[ticker])
        close = float(data[ticker]["Close"].iloc[-1])
        cls = q["classification"]
        entry_str = ""
        if entries:
            entry_str = ",".join(f"{e['type']}:{e['name'][:18]}" for e in entries)
            entry_count += 1
        exit_str = exits["tier"] or ""
        if exits["tier"]: exit_count += 1
        if entries or exits["tier"]:
            print(f"{asof.strftime('%Y-%m-%d'):<12} {close:>8.2f} {cls:<12} {pbd:>3} {entry_str:<35} {exit_str:<18}")
            summary_rows.append({"date": asof.strftime('%Y-%m-%d'), "close": close, "cls": cls, "bd": pbd,
                                 "entries": [e["type"] for e in entries], "exit_tier": exits["tier"],
                                 "entry_details": entries, "exit_triggers": exits["triggers"]})

    print()
    print(f"Total sessions scanned: {len(sessions)}")
    print(f"Sessions with entry signals: {entry_count}")
    print(f"Sessions with exit signals:  {exit_count}")
    if summary_rows:
        print("\n── DETAILED FIRES ──")
        for r in summary_rows:
            print(f"\n{r['date']} close=${r['close']:.2f} [{r['cls']}, bd={r['bd']}]")
            for e in r["entry_details"]:
                print(f"  ✓ Entry {e['type']} — {e['name']}: {e['detail']}")
            if r["exit_tier"]:
                print(f"  {r['exit_tier']}: " + " | ".join(r["exit_triggers"]))


if __name__ == "__main__":
    main()
