"""
bank-cycle-backtest.py — Did the "asset-sensitive = hike winner" thesis actually pay off?

Measures total return (dividend-adjusted) for the shortlist banks vs benchmarks across the phases
of the last real Fed hiking cycle:

  PRICING-IN  : 2021-03-16 → 2022-03-16  (the 12 months before liftoff, market repricing hawkish)
  HIKING      : 2022-03-16 → 2023-07-26  (first hike → terminal, +525bp) — includes Mar-2023 crisis
  HIKE+PLATEAU: 2022-03-16 → 2024-09-18  (liftoff → first cut, full higher-for-longer regime)
  SVB CRISIS  : worst drawdown within 2023-02-01 → 2023-05-31

Data: Yahoo chart API adjusted close. No key.
"""
from __future__ import annotations
import sys, time
import requests
from datetime import datetime, timezone

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

NAMES = ["WSFS", "FFBC", "WSBC", "EWBC"]
BENCH = ["KRE", "XLF", "SPY"]

WINDOWS = {
    "PRICING-IN (prior 12mo)": ("2021-03-16", "2022-03-16"),
    "HIKING (Mar22→Jul23)":    ("2022-03-16", "2023-07-26"),
    "HIKE+PLATEAU (→1st cut)":  ("2022-03-16", "2024-09-18"),
}
CRISIS = ("2023-02-01", "2023-05-31")


def ts(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def fetch(ticker: str) -> tuple[list[int], list[float]]:
    """Return (timestamps, adjusted closes) for 2021-01-01 → 2024-12-31."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={ts('2021-01-01')}&period2={ts('2024-12-31')}&interval=1d&events=div")
    r = requests.get(url, headers=HEADERS, timeout=20)
    res = r.json()["chart"]["result"][0]
    t = res["timestamp"]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    # drop None holes
    out_t, out_a = [], []
    for ti, ai in zip(t, adj):
        if ai is not None:
            out_t.append(ti); out_a.append(ai)
    return out_t, out_a


def price_on(t: list[int], a: list[float], date: str, mode: str = "after") -> float | None:
    """Adjusted close on/after (or on/before) a date."""
    target = ts(date)
    if mode == "after":
        for ti, ai in zip(t, a):
            if ti >= target:
                return ai
    else:
        last = None
        for ti, ai in zip(t, a):
            if ti <= target:
                last = ai
            else:
                break
        return last
    return None


def window_ret(t, a, start, end) -> float | None:
    p0 = price_on(t, a, start, "after")
    p1 = price_on(t, a, end, "before")
    if p0 and p1:
        return (p1 / p0 - 1) * 100
    return None


def max_drawdown(t, a, start, end) -> float | None:
    s, e = ts(start), ts(end)
    seg = [ai for ti, ai in zip(t, a) if s <= ti <= e]
    if not seg:
        return None
    peak = seg[0]; mdd = 0.0
    for v in seg:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return mdd * 100


def main():
    data = {}
    for tk in NAMES + BENCH:
        try:
            data[tk] = fetch(tk)
        except Exception as e:
            print(f"  {tk}: fetch err {e}", file=sys.stderr)
        time.sleep(0.3)

    kre_t, kre_a = data["KRE"]
    kre_rets = {w: window_ret(kre_t, kre_a, *r) for w, r in WINDOWS.items()}

    hdr = f"{'TKR':<6}" + "".join(f"{w[:22]:>24}" for w in WINDOWS) + f"{'SVB DD':>9}"
    print(hdr); print("-" * len(hdr))
    for tk in NAMES + BENCH:
        if tk not in data:
            continue
        t, a = data[tk]
        cells = ""
        for w, r in WINDOWS.items():
            ret = window_ret(t, a, *r)
            rel = (ret - kre_rets[w]) if (ret is not None and kre_rets[w] is not None) else None
            if tk in NAMES and rel is not None:
                cells += f"{f'{ret:+.0f}% ({rel:+.0f} vKRE)':>24}"
            else:
                cells += f"{f'{ret:+.0f}%' if ret is not None else 'n/a':>24}"
        dd = max_drawdown(t, a, *CRISIS)
        cells += f"{f'{dd:+.0f}%' if dd is not None else 'n/a':>9}"
        tag = " *" if tk in NAMES else ""
        print(f"{tk:<6}{cells}{tag}")
    print("\n* = shortlist asset-sensitive names. vKRE = relative to regional-bank ETF (KRE).")
    print("SVB DD = worst peak-to-trough drawdown Feb 1 – May 31 2023 (regional-bank crisis).")


if __name__ == "__main__":
    main()
