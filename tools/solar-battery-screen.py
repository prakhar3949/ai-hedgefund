"""One-off screen: solar + battery stock operating margins & quality.
Pulls Yahoo quoteSummary (financialData + defaultKeyStatistics) for the
solar/battery universe and ranks by operating margin. No Discord post —
prints a table to stdout for the grid-additions research goal.
"""
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from market_utils import yahoo_quote_summary

# Solar + battery / storage universe, grouped
UNIVERSE = {
    "FSLR":  "Solar — utility-scale modules (thin-film)",
    "NXT":   "Solar — trackers (utility-scale)",
    "ARRY":  "Solar — trackers (utility-scale)",
    "SHLS":  "Solar — BOS/EBOS components",
    "ENPH":  "Solar — microinverters (resi)",
    "SEDG":  "Solar — inverters/optimizers (resi/C&I)",
    "RUN":   "Solar — resi installer/financier",
    "CSIQ":  "Solar — modules (China/global)",
    "JKS":   "Solar — modules (China)",
    "MAXN":  "Solar — modules",
    "FLNC":  "Battery — grid-scale storage integrator",
    "STEM":  "Battery — storage + AI software",
    "EOSE":  "Battery — zinc long-duration storage",
    "TSLA":  "Battery — Megapack/Powerwall (energy seg)",
    "GEV":   "Power — grid equipment + storage",
    "BE":    "Fuel cells — distributed power",
    "AMRC":  "Energy efficiency / renewables dev",
    "NEP":   "Yieldco — solar/wind/storage assets",
    "RNW":   "Renewable IPP — solar/wind (India)",
}


def _safe(d, *keys):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def fetch(ticker):
    raw = yahoo_quote_summary(ticker, "financialData,defaultKeyStatistics,earningsTrend", timeout=15)
    if not raw:
        return ticker, None
    fd = raw.get("financialData") or {}
    ks = raw.get("defaultKeyStatistics") or {}
    row = {
        "op_margin":   _safe(fd, "operatingMargins", "raw"),
        "gross_margin": _safe(fd, "grossMargins", "raw"),
        "profit_margin": _safe(fd, "profitMargins", "raw"),
        "ebitda_margin": _safe(fd, "ebitdaMargins", "raw"),
        "rev_growth":  _safe(fd, "revenueGrowth", "raw"),
        "earn_growth": _safe(fd, "earningsGrowth", "raw"),
        "revenue":     _safe(fd, "totalRevenue", "raw"),
        "ebitda":      _safe(fd, "ebitda", "raw"),
        "roe":         _safe(fd, "returnOnEquity", "raw"),
        "fwd_pe":      _safe(ks, "forwardPE", "raw"),
        "cash":        _safe(fd, "totalCash", "raw"),
        "debt":        _safe(fd, "totalDebt", "raw"),
        "rec":         _safe(fd, "recommendationKey"),
    }
    return ticker, row


def pct(x):
    return f"{x*100:6.1f}%" if isinstance(x, (int, float)) else "    n/a"


def bil(x):
    if not isinstance(x, (int, float)):
        return "    n/a"
    return f"{x/1e9:6.2f}B" if abs(x) >= 1e9 else f"{x/1e6:6.0f}M"


def main():
    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(fetch, t): t for t in UNIVERSE}
        for f in as_completed(futs):
            t, row = f.result()
            if row:
                results[t] = row

    rows = [(t, r) for t, r in results.items()]
    # sort by operating margin desc, None last
    rows.sort(key=lambda x: (x[1]["op_margin"] is None, -(x[1]["op_margin"] or -99)))

    hdr = f"{'TICK':5} {'OpMgn':>7} {'GrMgn':>7} {'NetMgn':>7} {'EBITDAm':>7} {'RevGr':>7} {'Revenue':>8} {'FwdPE':>7} {'ROE':>7}  Description"
    print(hdr)
    print("-" * len(hdr))
    for t, r in rows:
        fpe = f"{r['fwd_pe']:6.1f}" if isinstance(r['fwd_pe'], (int, float)) else "   n/a"
        print(f"{t:5} {pct(r['op_margin'])} {pct(r['gross_margin'])} {pct(r['profit_margin'])} "
              f"{pct(r['ebitda_margin'])} {pct(r['rev_growth'])} {bil(r['revenue'])} {fpe} {pct(r['roe'])}  {UNIVERSE[t]}")

    missing = [t for t in UNIVERSE if t not in results]
    if missing:
        print("\nNo data:", ", ".join(missing))


if __name__ == "__main__":
    main()
