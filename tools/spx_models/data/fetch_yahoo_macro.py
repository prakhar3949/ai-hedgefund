"""
Yahoo Finance Chart-API fetcher for macro proxies.

Used as fallback when fred.stlouisfed.org is unreachable from this network.
Coverage:
    ^TNX  -> 10Y Treasury yield  (proxy for FRED DGS10)
    ^IRX  -> 13W T-bill yield    (proxy for FRED DTB3 / TBL)
    ^FVX  -> 5Y Treasury yield
    ^TYX  -> 30Y Treasury yield  (proxy for FRED DGS30)
    ^VIX  -> CBOE volatility index (proxy for FRED VIXCLS)

Returns monthly-start-indexed Series, cached for 24h (same convention as
fetch_fred and fetch_multpl).

Limitations relative to FRED:
- Yahoo ^TNX / ^IRX / ^FVX history begins 1986-06; FRED DGS10 starts 1962.
  This caps W-G-expanded fits to a post-1986 sample.
- ^VIX begins 1990-02. Same constraint.

Note on Yahoo quirks for ^TNX family:
- `range=max&interval=1mo` returns ~159 sparse rows (quarterly spaced).
- `range=40y&interval=1mo` returns 481 rows but drops monthly samples in the
  most recent ~24 months (everything after mid-2024 falls out except the very
  last point). Confirmed empirically May 2026.
- `range=40y&interval=1d` returns the full ~10k daily samples cleanly.

Therefore we fetch daily and resample to month-start (last value of each
month). That gives complete monthly coverage 1986-06 .. now.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

CACHE_DIR = Path(__file__).resolve().parent.parent / "_cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL_SECONDS = 24 * 60 * 60


def _cache_path(symbol: str) -> Path:
    safe = symbol.replace("^", "ix_")
    return CACHE_DIR / f"yfm_{safe}.parquet"


def _is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    return datetime.now().timestamp() - path.stat().st_mtime < CACHE_TTL_SECONDS


def _fetch_daily(symbol: str, range_str: str = "40y") -> pd.Series:
    """Fetch daily closes via Yahoo chart API."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?range={range_str}&interval=1d"
    )
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    j = r.json()
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    dates = [
        pd.Timestamp(datetime.fromtimestamp(t, tz=timezone.utc).replace(tzinfo=None)).normalize()
        for t in ts
    ]
    s = pd.Series(closes, index=dates, name=symbol).dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def fetch(symbol: str, force: bool = False) -> pd.Series:
    """Monthly series (month-start indexed, last value of month)."""
    path = _cache_path(symbol)
    if not force and _is_fresh(path):
        s = pd.read_parquet(path).iloc[:, 0]
        s.name = symbol
        return s
    daily = _fetch_daily(symbol, "40y")
    monthly = daily.resample("MS").last().dropna()
    monthly.name = symbol
    monthly.to_frame().to_parquet(path)
    return monthly


if __name__ == "__main__":
    for sym in ["^TNX", "^IRX", "^FVX", "^TYX", "^VIX"]:
        try:
            s = fetch(sym, force=True)
            print(f"{sym:6} n={len(s):4d}  {s.index[0].date()} -> {s.index[-1].date()}  "
                  f"latest={float(s.iloc[-1]):.2f}")
        except Exception as e:
            print(f"{sym:6} FAILED  {type(e).__name__}: {e}")
