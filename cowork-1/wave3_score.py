"""
Wave-3 AI Productivity Beneficiary scoring.

Per-ticker fundamentals are pulled from Yahoo quoteSummary (no API key).
Modules requested: financialData, defaultKeyStatistics, incomeStatementHistory,
summaryDetail, price.

Each company is then scored on five factors that each represent the "how AI
helps". These are the factors I'm using and why:

  F1  REV_PER_EMP    revenue / fullTimeEmployees             (lower = more
                                                              labor-intensive
                                                              = more upside)
  F2  OP_MARGIN_INV  1 - operatingMargins                    (lower margin =
                                                              bigger expansion
                                                              runway)
  F3  GROSS_RUNWAY   1 - grossMargins                        (more room above
                                                              COGS to take
                                                              cost out)
  F4  EMPLOYEE_DENS  employees / revenue ($M)                (same as F1 but
                                                              inverted scale,
                                                              second sanity)
  F5  FCF_DRAG       1 - (FCF / NetIncome)                   (admin/working-cap
                                                              drag AI compresses)

Each factor is percentile-ranked across the universe (higher rank = more
attractive). Composite = average of factor percentiles, weighted:

    F1 30%   F2 25%   F3 15%   F4 20%   F5 10%

Then I overlay a sector "AI-substitution exposure" multiplier (0.7 - 1.2)
based on the primary_metric_tag — IT services, BPO, CX BPO and Tax services
get boosted; back-office gets neutral; banks get a small boost because of
operating-leverage potential; brokers (which are mostly fee businesses) get
trimmed.

Final composite is 0-100; classification:
   >= 75   PRIME    high conviction
   60-74   GOOD     candidate
   40-59   MIXED    needs additional confirm
   < 40    AVOID
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yfinance as yf

# wave3_universe is in the same folder
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wave3_universe import UNIVERSE  # noqa: E402


# ---------- fetchers -----------------------------------------------------

def fetch_fundamentals(ticker: str) -> dict:
    # normalize for Yahoo (BRK.B -> BRK-B)
    yt = ticker.replace(".", "-")
    try:
        info = yf.Ticker(yt).info or {}
    except Exception as e:
        return {"ticker": ticker, "error": f"fetch_failed: {type(e).__name__}"}

    if not info or not info.get("totalRevenue"):
        return {"ticker": ticker, "error": "no_result"}

    # SG&A from income statement; varies by company, safe-fallback to None
    sg_and_a = None
    try:
        df = yf.Ticker(yt).income_stmt
        if df is not None and not df.empty:
            for idx in df.index:
                if "selling" in str(idx).lower() and "admin" in str(idx).lower():
                    sg_and_a = float(df.loc[idx].iloc[0])
                    break
    except Exception:
        pass

    out = {
        "ticker": ticker,
        "name":           info.get("longName") or info.get("shortName"),
        "market_cap":     info.get("marketCap"),
        "revenue":        info.get("totalRevenue"),
        "gross_margin":   info.get("grossMargins"),
        "op_margin":      info.get("operatingMargins"),
        "profit_margin":  info.get("profitMargins"),
        "ebit_margin":    info.get("ebitdaMargins"),
        "fcf":            info.get("freeCashflow"),
        "op_cashflow":    info.get("operatingCashflow"),
        "rev_growth":     info.get("revenueGrowth"),
        "employees":      info.get("fullTimeEmployees"),
        "sga":            sg_and_a,
    }
    # net income proxy: revenue * profit_margin
    if out["revenue"] and out["profit_margin"]:
        out["net_income"] = out["revenue"] * out["profit_margin"]
    else:
        out["net_income"] = None
    return out


# ---------- derived metrics ----------------------------------------------

def derive(row: dict) -> dict:
    rev = row.get("revenue")
    emp = row.get("employees")
    fcf = row.get("fcf")
    ni  = row.get("net_income")
    sga = row.get("sga")
    om  = row.get("op_margin")
    gm  = row.get("gross_margin")

    rev_per_emp = (rev / emp) if (rev and emp and emp > 0) else None
    emp_per_mrev = (emp / (rev / 1e6)) if (rev and emp and rev > 0) else None
    fcf_conv = (fcf / ni) if (fcf is not None and ni and ni > 0) else None
    sga_pct = (sga / rev) if (sga and rev and rev > 0) else None

    return {
        "rev_per_emp":  rev_per_emp,
        "emp_per_mrev": emp_per_mrev,
        "fcf_conv":     fcf_conv,
        "sga_pct":      sga_pct,
        "op_margin":    om,
        "gross_margin": gm,
    }


# ---------- scoring -------------------------------------------------------

def percentile_rank(values: list[float | None], reverse: bool = False) -> list[float | None]:
    """Return 0-100 percentile rank. reverse=True means lower values rank higher."""
    paired = [(i, v) for i, v in enumerate(values) if v is not None]
    if not paired:
        return [None] * len(values)
    paired.sort(key=lambda x: x[1], reverse=not reverse)
    n = len(paired)
    ranks = [None] * len(values)
    for rank, (i, _) in enumerate(paired):
        ranks[i] = 100.0 * (n - 1 - rank) / max(n - 1, 1) if not reverse else \
                   100.0 * rank / max(n - 1, 1)
    # cleaner: when reverse=False we want highest value -> rank 100
    return ranks


def pct_rank(values, higher_is_better=True):
    """Return [0,100] percentile. None passes through."""
    idx_val = sorted(
        [(i, v) for i, v in enumerate(values) if v is not None],
        key=lambda x: x[1],
        reverse=not higher_is_better,
    )
    n = len(idx_val)
    out = [None] * len(values)
    for rank, (i, _) in enumerate(idx_val):
        out[i] = 100.0 * (rank / max(n - 1, 1))
    return out


# sector tag → exposure multiplier
EXPOSURE_MULT = {
    "LABOR_PCT":     1.20,   # Goldman headline metric — biggest AI upside
    "BILL_HOURS":    1.15,
    "BPO":           1.20,
    "CS_INTENSITY":  1.15,
    "CLAIMS_INTENS": 1.10,
    "KNOW_WORKER":   1.05,
    "BACKOFFICE":    1.00,
    "REV_PER_EMP":   1.00,
    "SGA_PCT":       1.00,
}


def score_universe(rows: list[dict]) -> list[dict]:
    # collect arrays
    rev_per_emp  = [r["derived"]["rev_per_emp"]  for r in rows]
    emp_per_mrev = [r["derived"]["emp_per_mrev"] for r in rows]
    op_margin    = [r["derived"]["op_margin"]    for r in rows]
    gross_margin = [r["derived"]["gross_margin"] for r in rows]
    fcf_conv     = [r["derived"]["fcf_conv"]     for r in rows]

    # Wave-3 attractive directions:
    #   low rev/emp        → high rank (more labor leverage)
    #   high emp/$M rev    → high rank (more labor leverage)
    #   low op_margin      → high rank (more expansion runway, BUT must be positive)
    #   low gross margin   → high rank (more COGS-side room)
    #   low fcf_conv       → high rank (more admin drag to compress)
    f1 = pct_rank(rev_per_emp,  higher_is_better=False)
    f2 = pct_rank(op_margin,    higher_is_better=False)
    f3 = pct_rank(gross_margin, higher_is_better=False)
    f4 = pct_rank(emp_per_mrev, higher_is_better=True)
    f5 = pct_rank(fcf_conv,     higher_is_better=False)

    # filter degenerate cases
    for i, r in enumerate(rows):
        om = r["derived"]["op_margin"]
        if om is None or om < -0.10:
            # company is losing money; expansion thesis doesn't apply
            f2[i] = None

    for i, r in enumerate(rows):
        weights = []
        values  = []
        for w, v in [(0.30, f1[i]), (0.25, f2[i]), (0.15, f3[i]),
                     (0.20, f4[i]), (0.10, f5[i])]:
            if v is not None:
                weights.append(w)
                values.append(v)
        if not weights:
            base = None
        else:
            base = sum(w * v for w, v in zip(weights, values)) / sum(weights)

        mult = EXPOSURE_MULT.get(r["tag"], 1.0)
        composite = (base * mult) if base is not None else None
        if composite is not None:
            composite = min(100.0, composite)

        r["factor_scores"] = {
            "F1_rev_per_emp":  round(f1[i], 1) if f1[i] is not None else None,
            "F2_op_margin":    round(f2[i], 1) if f2[i] is not None else None,
            "F3_gross_margin": round(f3[i], 1) if f3[i] is not None else None,
            "F4_emp_density":  round(f4[i], 1) if f4[i] is not None else None,
            "F5_fcf_drag":     round(f5[i], 1) if f5[i] is not None else None,
        }
        r["base_score"] = round(base, 1) if base is not None else None
        r["exposure_mult"] = mult
        r["composite"] = round(composite, 1) if composite is not None else None
        if composite is None:
            r["classification"] = "NO_DATA"
        elif composite >= 75:
            r["classification"] = "PRIME"
        elif composite >= 60:
            r["classification"] = "GOOD"
        elif composite >= 40:
            r["classification"] = "MIXED"
        else:
            r["classification"] = "AVOID"
    return rows


# ---------- main ---------------------------------------------------------

def main(out_dir: Path):
    print(f"[wave3] scoring {len(UNIVERSE)} tickers...", flush=True)

    fundamentals = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(fetch_fundamentals, t[0]): t for t in UNIVERSE}
        for i, fut in enumerate(as_completed(futures), 1):
            t = futures[fut]
            try:
                fundamentals[t[0]] = fut.result()
            except Exception as e:
                fundamentals[t[0]] = {"ticker": t[0], "error": str(e)}
            if i % 20 == 0:
                print(f"  ... {i}/{len(UNIVERSE)} fetched", flush=True)
            time.sleep(0.05)

    rows = []
    for ticker, bucket, how, tag in UNIVERSE:
        fd = fundamentals.get(ticker, {})
        derived = derive(fd) if "error" not in fd else {
            "rev_per_emp": None, "emp_per_mrev": None,
            "fcf_conv": None, "sga_pct": None,
            "op_margin": None, "gross_margin": None,
        }
        rows.append({
            "ticker":    ticker,
            "name":      fd.get("name") or ticker,
            "bucket":    bucket,
            "how":       how,
            "tag":       tag,
            "market_cap": fd.get("market_cap"),
            "revenue":   fd.get("revenue"),
            "employees": fd.get("employees"),
            "rev_growth": fd.get("rev_growth"),
            "derived":   derived,
            "error":     fd.get("error"),
        })

    rows = score_universe(rows)
    rows.sort(key=lambda r: r["composite"] if r["composite"] is not None else -1,
              reverse=True)

    out_json = out_dir / "wave3_ranked.json"
    out_json.write_text(json.dumps(rows, indent=2, default=str))
    print(f"[wave3] wrote {out_json}", flush=True)

    # CSV
    import csv
    out_csv = out_dir / "wave3_ranked.csv"
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "rank", "ticker", "name", "bucket", "tag", "composite", "class",
            "F1_rev_per_emp", "F2_op_margin", "F3_gross_margin",
            "F4_emp_density", "F5_fcf_drag",
            "rev_per_emp_$", "op_margin", "gross_margin",
            "employees", "revenue_$M", "market_cap_$M", "rev_growth",
            "how",
        ])
        for i, r in enumerate(rows, 1):
            d = r["derived"]
            w.writerow([
                i, r["ticker"], r["name"], r["bucket"], r["tag"],
                r["composite"], r["classification"],
                r["factor_scores"]["F1_rev_per_emp"],
                r["factor_scores"]["F2_op_margin"],
                r["factor_scores"]["F3_gross_margin"],
                r["factor_scores"]["F4_emp_density"],
                r["factor_scores"]["F5_fcf_drag"],
                round(d["rev_per_emp"], 0) if d["rev_per_emp"] else None,
                round(d["op_margin"] * 100, 1) if d["op_margin"] else None,
                round(d["gross_margin"] * 100, 1) if d["gross_margin"] else None,
                r["employees"],
                round(r["revenue"] / 1e6, 0) if r["revenue"] else None,
                round(r["market_cap"] / 1e6, 0) if r["market_cap"] else None,
                round(r["rev_growth"] * 100, 1) if r["rev_growth"] else None,
                r["how"],
            ])
    print(f"[wave3] wrote {out_csv}", flush=True)

    # quick summary
    by_class = {}
    for r in rows:
        by_class.setdefault(r["classification"], 0)
        by_class[r["classification"]] += 1
    print("[wave3] classification:", by_class, flush=True)
    # truncated tail rewrite
    print("[wave3] top 15:", flush=True)
    for r in rows[:15]:
        comp = r['composite'] if r['composite'] is not None else 0.0
        nm = (r.get('name') or r['ticker'])[:36]
        print("  %5.1f  %-6s  %-7s  %-22s  %s" % (
            comp, r['ticker'], r['classification'], r['bucket'][:22], nm),
            flush=True)


if __name__ == "__main__":
    main(Path(__file__).resolve().parent)
