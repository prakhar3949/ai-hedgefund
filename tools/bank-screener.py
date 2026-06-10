"""
bank-screener.py — Regional-bank fundamental comparison + rate-hike beneficiary screen.

Built for the "which good banks benefit from upcoming rate hikes" question. Computes the
bank-specific metrics the generic fundamentals tools miss:

  TANGIBLE BOOK  — real TCE = StockholdersEquity - Goodwill - OtherIntangibles
                   P/TBV (price / tangible book per share), ROTCE (return on tangible common equity)
  RATE SENSITIVITY (asset-sensitivity proxies — who wins when rates rise):
                   NIB deposit %  (non-interest-bearing deposits / total deposits — low deposit beta)
                   NIM + NIM trend (net interest margin, expanding = currently benefiting)
                   funding cost   (interest expense annualized / avg deposits)
                   loan/deposit   (asset deployment)
                   securities/assets (AFS book — high = AOCI/duration drag that erodes TBV in hikes)
  QUALITY/VALUE  — ROA, ROE, equity/assets (capital), trailing/fwd P/E, EPS growth, div yield

Data: Yahoo quoteSummary (defaultKeyStatistics, financialData, summaryDetail, earningsTrend,
assetProfile) + Yahoo fundamentals-timeseries (~5 recent quarters of balance-sheet / NII line items).
No API key. See memory: reference-yahoo-timeseries-bank-fields.

Two composite scores, each percentile-ranked WITHIN the core-regional cohort:
  GOOD-BANK score   = profitability + value + growth + balance-sheet quality
  RATE-BENEFIT score = NIB% + NIM trend + low funding cost + loan/deposit + low securities/assets

Usage:
  python bank-screener.py                      # uses BANK_LIST below
  python bank-screener.py EWBC WSFS OCFC ...    # explicit tickers
  python bank-screener.py --discord            # also post a summary to Discord

IMPORTANT LIMITATION: definitive asset-sensitivity is in each bank's 10-Q interest-rate-risk
(EAR) table, not in any free API. The NIB%/NIM/securities proxies here are a strong screen, not
a substitute for that disclosure. TCE ignores preferred stock (minor for most small regionals).
"""

from __future__ import annotations

import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

from market_utils import yahoo_quote_summary, get_yahoo_session

TOOLS_DIR = Path(__file__).resolve().parent
OUT_CSV = TOOLS_DIR / "bank-screener-output.csv"

DISCORD_WEBHOOK_URL = (  # reuse fundamentals-scanner channel
    "https://discord.com/api/webhooks/1475327530025222164/"
    "_IAvJ8JX2HWXRPDYER00UN5qj07DyoPNTZlk04TFV3SDrEaHcIxxe0-4J85LNgziGE39"
)

# ── Universe (from the user's regional-banks list) ────────────────────────────
# The "###HIGH NII" group was pre-tagged by the user as high net-interest-income names.
HIGH_NII = {"GCBC", "MCB", "UVSP", "EWBC", "BOKF", "WAFD", "ONB"}

# Non-core-regional names get segmented out of the core cohort scoring.
ETF          = {"KRE"}                                  # SPDR Regional Bank ETF (benchmark, no per-share TBV)
MONEY_CENTER = {"GS", "BK", "STT"}                      # i-bank / custody / trust — different model
FINTECH      = {"SOFI", "CHYM", "CURR", "RKT"}          # digital banks / mortgage (RKT benefits from CUTS)

BANK_LIST = [
    "ATLO", "OCFC", "BHRB", "INBK", "RRBI", "NIC", "WSFS", "FBLA", "WASH", "AMAL",
    "PGC", "SRBK", "CASH", "BFC", "FFBC", "ORRF", "CCB", "MBIN", "EGBN", "OBK",
    "SFBS", "FGBI", "NRIM", "STEL", "KRE", "CARE", "FRST", "RBKB", "HAFC", "GBCI",
    "NBN", "LOB", "MSBI", "FBNC", "RBB", "WSBC", "OPHC", "BCBP", "PBHC", "STT",
    "BK", "ASRV", "CHYM", "GS", "RKT", "SOFI", "CURR", "FFIC",
    "GCBC", "MCB", "UVSP", "EWBC", "BOKF", "WAFD", "ONB",
]

TS_TYPES = [
    "quarterlyStockholdersEquity", "quarterlyGoodwill", "quarterlyOtherIntangibleAssets",
    "quarterlyTotalAssets", "quarterlyNetLoan", "quarterlyTotalDeposits",
    "quarterlyNonInterestBearingDeposits", "quarterlyAvailableForSaleSecurities",
    "quarterlyInterestIncome", "quarterlyInterestExpense", "quarterlyNetInterestIncome",
    "quarterlyTotalRevenue", "quarterlyNetIncome",
]


def segment_of(t: str) -> str:
    if t in ETF:
        return "ETF"
    if t in MONEY_CENTER:
        return "MONEY_CENTER"
    if t in FINTECH:
        return "FINTECH"
    return "REGIONAL"


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _r(d, *keys):
    """Pull nested .raw, tolerating missing keys."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
        if d is None:
            return None
    if isinstance(d, dict):
        return d.get("raw")
    return d


def fetch_timeseries(ticker: str) -> dict[str, list[float]]:
    """Returns {type: [vals oldest→newest]} for the line items we need."""
    sess, crumb = get_yahoo_session()
    if not sess:
        return {}
    yt = ticker.replace(".", "-")
    now = int(time.time())
    url = (f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{yt}"
           f"?symbol={yt}&type={','.join(TS_TYPES)}&period1=1546300800&period2={now}")
    out: dict[str, list[float]] = {}
    try:
        rr = sess.get(url, timeout=20)
        if rr.status_code != 200:
            return {}
        results = rr.json().get("timeseries", {}).get("result", [])
        for item in results:
            typ = (item.get("meta", {}).get("type") or ["?"])[0]
            rows = item.get(typ) or []
            pairs = [(v.get("asOfDate"), _r(v, "reportedValue")) for v in rows if v]
            pairs = [(d, val) for d, val in pairs if d and val is not None]
            pairs.sort(key=lambda x: x[0])
            out[typ] = [val for _, val in pairs]
    except Exception as e:
        print(f"  timeseries({ticker}): {e}", file=sys.stderr)
    return out


def fetch_summary(ticker: str) -> dict:
    qs = yahoo_quote_summary(
        ticker, "assetProfile,price,summaryDetail,defaultKeyStatistics,financialData,earningsTrend"
    ) or {}
    ap, pr, sd = qs.get("assetProfile") or {}, qs.get("price") or {}, qs.get("summaryDetail") or {}
    ks, fd, et = qs.get("defaultKeyStatistics") or {}, qs.get("financialData") or {}, qs.get("earningsTrend") or {}

    # Forward FY EPS growth from earningsTrend +1y
    fwd_eps_g = None
    for e in (et.get("trend") or []):
        if e.get("period") == "+1y":
            fwd_eps_g = _r(e, "growth")
            break

    return {
        "name": (pr.get("longName") or pr.get("shortName") or ticker),
        "industry": ap.get("industry"),
        "price": _r(fd, "currentPrice") or _r(pr, "regularMarketPrice"),
        "shares": _r(ks, "sharesOutstanding"),
        "market_cap": _r(pr, "marketCap") or _r(sd, "marketCap"),
        "book_value_ps": _r(ks, "bookValue"),
        "pb": _r(ks, "priceToBook"),
        "trailing_pe": _r(ks, "trailingPE") or _r(sd, "trailingPE"),
        "forward_pe": _r(ks, "forwardPE") or _r(sd, "forwardPE"),
        "roe": _r(fd, "returnOnEquity"),
        "roa": _r(fd, "returnOnAssets"),
        "profit_margin": _r(fd, "profitMargins"),
        "rev_growth": _r(fd, "revenueGrowth"),
        "earn_growth": _r(fd, "earningsGrowth"),
        "div_yield": _r(sd, "dividendYield"),
        "fwd_eps_growth": fwd_eps_g,
    }


# ── Metric computation ────────────────────────────────────────────────────────

def _ttm(vals: list[float]) -> float | None:
    """Sum of last 4 quarters; if <4 available, annualize latest ×4."""
    if not vals:
        return None
    if len(vals) >= 4:
        return sum(vals[-4:])
    return vals[-1] * 4


def _avg_last(vals: list[float], n: int = 5) -> float | None:
    if not vals:
        return None
    tail = vals[-n:]
    return sum(tail) / len(tail)


def compute(ticker: str, summ: dict, ts: dict) -> dict:
    m = {"ticker": ticker, "segment": segment_of(ticker), "high_nii": ticker in HIGH_NII,
         "name": summ.get("name"), "flags": []}
    m.update({k: summ.get(k) for k in (
        "price", "shares", "market_cap", "pb", "trailing_pe", "forward_pe",
        "roe", "roa", "rev_growth", "earn_growth", "div_yield", "fwd_eps_growth")})

    eq   = ts.get("quarterlyStockholdersEquity") or []
    gw   = ts.get("quarterlyGoodwill") or []
    intg = ts.get("quarterlyOtherIntangibleAssets") or []
    ta   = ts.get("quarterlyTotalAssets") or []
    loan = ts.get("quarterlyNetLoan") or []
    dep  = ts.get("quarterlyTotalDeposits") or []
    nib  = ts.get("quarterlyNonInterestBearingDeposits") or []
    afs  = ts.get("quarterlyAvailableForSaleSecurities") or []
    nii  = ts.get("quarterlyNetInterestIncome") or []
    iexp = ts.get("quarterlyInterestExpense") or []
    ni   = ts.get("quarterlyNetIncome") or []

    n_q = len(eq)
    if n_q < 2 or not ta:
        m["flags"].append("DATA_THIN")
        return m
    if n_q < 4:
        m["flags"].append("PARTIAL_TTM")

    def last(x):
        return x[-1] if x else None

    eq0, ta0 = last(eq), last(ta)
    gw0  = last(gw) or 0
    int0 = last(intg) or 0

    # Tangible common equity & P/TBV
    tce = eq0 - gw0 - int0 if eq0 is not None else None
    m["tce"] = tce
    if tce and tce > 0 and m["shares"]:
        m["tbv_ps"] = tce / m["shares"]
        if m["price"]:
            m["p_tbv"] = m["price"] / m["tbv_ps"]
    m.setdefault("tbv_ps", None)
    m.setdefault("p_tbv", None)

    # ROTCE (TTM net income / avg TCE), ROA (TTM NI / avg assets)
    ttm_ni = _ttm(ni)
    avg_tce = None
    if eq:
        eq_tce = [e - (gw[i] if i < len(gw) and gw[i] else 0) - (intg[i] if i < len(intg) and intg[i] else 0)
                  for i, e in enumerate(eq)]
        avg_tce = _avg_last(eq_tce)
    m["rotce"] = (ttm_ni / avg_tce) if (ttm_ni and avg_tce and avg_tce > 0) else None
    avg_ta = _avg_last(ta)
    m["roa_ttm"] = (ttm_ni / avg_ta) if (ttm_ni and avg_ta and avg_ta > 0) else None

    # Capital, deployment, securities
    m["equity_assets"] = (eq0 / ta0) if (eq0 and ta0) else None       # capital ratio proxy
    m["loan_deposit"]  = (last(loan) / last(dep)) if (last(loan) and last(dep)) else None
    m["securities_assets"] = (last(afs) / ta0) if (last(afs) and ta0) else None  # AOCI/duration drag proxy

    # Deposit franchise — NIB %
    m["nib_pct"] = (last(nib) / last(dep)) if (last(nib) and last(dep)) else None

    # NIM (annualized NII / avg earning assets≈loans+securities) + trend
    def earning_assets(i):
        l = loan[i] if i < len(loan) and loan[i] else 0
        s = afs[i] if i < len(afs) and afs[i] else 0
        return (l + s) or None

    def nim_q(i):
        ea = earning_assets(i)
        if ea and i < len(nii) and nii[i]:
            return nii[i] * 4 / ea
        return None

    m["nim"] = nim_q(len(nii) - 1) if nii else None
    nim_yago = nim_q(len(nii) - 5) if len(nii) >= 5 else (nim_q(0) if len(nii) >= 2 else None)
    m["nim_trend_bps"] = ((m["nim"] - nim_yago) * 10000) if (m["nim"] and nim_yago) else None

    # Funding cost (interest expense annualized / avg deposits) — incl. borrowings, so "funding" not "deposit"
    ttm_iexp = _ttm(iexp)
    avg_dep = _avg_last(dep)
    m["funding_cost"] = (ttm_iexp / avg_dep) if (ttm_iexp and avg_dep and avg_dep > 0) else None

    return m


# ── Scoring (percentile-ranked within the REGIONAL cohort) ────────────────────

def pct_rank(values: list, invert: bool = False) -> list:
    n = len(values)
    valid = [i for i, v in enumerate(values) if v is not None]
    ranks = [50.0] * n
    if len(valid) < 2:
        return ranks
    order = sorted(valid, key=lambda i: values[i], reverse=invert)
    for pos, i in enumerate(order):
        ranks[i] = pos / (len(order) - 1) * 100
    return ranks


def score_cohort(rows: list[dict]):
    if len(rows) < 2:
        for r in rows:
            r["good_score"] = r["rate_score"] = 50.0
        return

    def col(k):
        return [r.get(k) for r in rows]

    # GOOD-BANK: profitability + value + growth + balance-sheet quality
    roa_r   = pct_rank(col("roa_ttm"))
    rotce_r = pct_rank(col("rotce"))
    ptbv_r  = pct_rank(col("p_tbv"), invert=True)      # cheaper TBV = better
    fpe_r   = pct_rank(col("forward_pe"), invert=True)
    growth_r = pct_rank(col("fwd_eps_growth"))
    cap_r   = pct_rank(col("equity_assets"))            # more capital = safer
    # loan/deposit: penalize extremes (>1.0 liquidity risk, <0.6 under-deployed) → score closeness to 0.85
    ld_vals = col("loan_deposit")
    ld_q = [(-abs((v or 0.85) - 0.85)) if v is not None else None for v in ld_vals]
    ld_r = pct_rank(ld_q)

    # RATE-BENEFIT: NIB% + NIM trend + low funding cost + loan/deposit + low securities/assets
    nib_r   = pct_rank(col("nib_pct"))
    nimt_r  = pct_rank(col("nim_trend_bps"))
    nim_r   = pct_rank(col("nim"))
    fund_r  = pct_rank(col("funding_cost"), invert=True)   # lower funding cost = better
    sec_r   = pct_rank(col("securities_assets"), invert=True)  # less AFS = less AOCI drag
    ldp_r   = pct_rank(col("loan_deposit"))                # more deployed = more asset-sensitive

    for i, r in enumerate(rows):
        r["good_score"] = round(
            0.22 * roa_r[i] + 0.20 * rotce_r[i] + 0.20 * ptbv_r[i] +
            0.12 * fpe_r[i] + 0.14 * growth_r[i] + 0.07 * cap_r[i] + 0.05 * ld_r[i], 1)
        r["rate_score"] = round(
            0.30 * nib_r[i] + 0.20 * nimt_r[i] + 0.15 * nim_r[i] +
            0.15 * fund_r[i] + 0.12 * sec_r[i] + 0.08 * ldp_r[i], 1)


# ── Formatting ────────────────────────────────────────────────────────────────

def _f(v, fmt, scale=1.0, suffix="", na="—"):
    if v is None:
        return na
    try:
        return f"{v*scale:{fmt}}{suffix}"
    except Exception:
        return na


def render_table(rows: list[dict], title: str) -> str:
    hdr = (f"{'TKR':<6}{'P/TBV':>6}{'ROTCE':>7}{'ROA':>6}{'FwdPE':>6}{'EPSg':>6}"
           f"{'NIB%':>6}{'NIM':>6}{'NIMΔ':>7}{'Fund':>6}{'Sec%':>6}{'GOOD':>6}{'RATE':>6}")
    out = [title, hdr, "-" * len(hdr)]
    for r in rows:
        out.append(
            f"{r['ticker']:<6}"
            f"{_f(r.get('p_tbv'), '.2f', suffix='x'):>6}"
            f"{_f(r.get('rotce'), '.1f', 100, '%'):>7}"
            f"{_f(r.get('roa_ttm'), '.2f', 100, '%'):>6}"
            f"{_f(r.get('forward_pe'), '.1f', suffix='x'):>6}"
            f"{_f(r.get('fwd_eps_growth'), '.0f', 100, '%'):>6}"
            f"{_f(r.get('nib_pct'), '.0f', 100, '%'):>6}"
            f"{_f(r.get('nim'), '.2f', 100, '%'):>6}"
            f"{_f(r.get('nim_trend_bps'), '+.0f', suffix=''):>7}"
            f"{_f(r.get('funding_cost'), '.2f', 100, '%'):>6}"
            f"{_f(r.get('securities_assets'), '.0f', 100, '%'):>6}"
            f"{_f(r.get('good_score'), '.0f'):>6}"
            f"{_f(r.get('rate_score'), '.0f'):>6}"
        )
    return "\n".join(out)


CSV_COLS = ["ticker", "segment", "high_nii", "name", "price", "market_cap",
            "p_tbv", "tbv_ps", "pb", "rotce", "roa_ttm", "roe", "trailing_pe",
            "forward_pe", "fwd_eps_growth", "rev_growth", "div_yield",
            "equity_assets", "loan_deposit", "securities_assets",
            "nib_pct", "nim", "nim_trend_bps", "funding_cost",
            "good_score", "rate_score", "flags"]


def write_csv(rows: list[dict]):
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for r in rows:
            w.writerow([("|".join(r["flags"]) if c == "flags" else r.get(c)) for c in CSV_COLS])


def send_discord(text: str):
    for i in range(0, len(text), 1900):
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": text[i:i+1900]}, timeout=30)
            time.sleep(0.4)
        except Exception as e:
            print(f"  discord: {e}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    post = "--discord" in sys.argv
    tickers = [a.lstrip("$").upper() for a in args] if args else BANK_LIST

    print(f"Bank screener — {len(tickers)} tickers", file=sys.stderr)
    rows = []

    def work(t):
        try:
            summ = fetch_summary(t)
            if summ.get("price") is None:          # v10 throttled — retry once
                time.sleep(3)
                summ = fetch_summary(t)
            ts = fetch_timeseries(t)
            return compute(t, summ, ts)
        except Exception as e:
            print(f"  [{t}] {e}", file=sys.stderr)
            return {"ticker": t, "segment": segment_of(t), "high_nii": t in HIGH_NII,
                    "flags": ["FETCH_ERR"]}

    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = {pool.submit(work, t): t for t in tickers}
        for fut in as_completed(futs):
            rows.append(fut.result())
            print(".", end="", file=sys.stderr, flush=True)
    print("", file=sys.stderr)

    # Score only the core regional cohort (apples-to-apples); others get cohort-relative too but flagged
    regional = [r for r in rows if r["segment"] == "REGIONAL" and "DATA_THIN" not in r["flags"]
                and "FETCH_ERR" not in r["flags"]]
    score_cohort(regional)

    others = [r for r in rows if r not in regional]
    # give "others" a cohort score among themselves so the table isn't blank, but keep them separate
    for seg in ("MONEY_CENTER", "FINTECH"):
        grp = [r for r in others if r["segment"] == seg and "DATA_THIN" not in r["flags"]
               and "FETCH_ERR" not in r["flags"]]
        score_cohort(grp)

    regional.sort(key=lambda r: (r.get("good_score") or 0), reverse=True)
    write_csv(rows)

    # ── Output ────────────────────────────────────────────────────────────────
    print(f"\nSaved {len(rows)} rows → {OUT_CSV.name}\n")

    print(render_table(regional, "═══ CORE REGIONAL BANKS — ranked by GOOD-BANK score ═══"))
    print()
    rate_sorted = sorted(regional, key=lambda r: (r.get("rate_score") or 0), reverse=True)
    print(render_table(rate_sorted, "═══ SAME COHORT — ranked by RATE-HIKE BENEFIT score ═══"))

    for seg, label in [("MONEY_CENTER", "MONEY-CENTER / CUSTODY (GS, BK, STT)"),
                       ("FINTECH", "FINTECH / MORTGAGE (separate model)")]:
        grp = sorted([r for r in others if r["segment"] == seg],
                     key=lambda r: (r.get("good_score") or 0), reverse=True)
        if grp:
            print()
            print(render_table(grp, f"═══ {label} ═══"))

    skipped = [r for r in rows if "DATA_THIN" in r["flags"] or "FETCH_ERR" in r["flags"]]
    if skipped:
        print("\nSkipped / thin data: " + ", ".join(
            f"{r['ticker']}({'/'.join(r['flags'])})" for r in skipped))

    if post:
        top = regional[:12]
        msg = "**BANK SCREENER — Regional banks, rate-hike beneficiary screen**\n```\n"
        msg += render_table(top, "Top 12 by GOOD-BANK score") + "\n```"
        send_discord(msg)
        send_discord("```\n" + render_table(rate_sorted[:12], "Top 12 by RATE-BENEFIT score") + "\n```")
        print("\nPosted to Discord.")


if __name__ == "__main__":
    main()
