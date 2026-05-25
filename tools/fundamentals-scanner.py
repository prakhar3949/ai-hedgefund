"""
Fundamentals Scanner
Layers fundamental quality + valuation on top of stock-discovery.py picks.

For each stock surfaced by stock-discovery.py, fetches Yahoo quoteSummary data
and scores it on three dimensions:

  Valuation Score    (40%): EV/EBITDA, Forward P/E, Price-to-Book
  Quality Score      (35%): ROIC-WACC spread, Gross Margin, Operating Margin
  Forward Outlook    (25%): EPS growth (next FY + current FY), Revenue Growth

All scores are percentile-ranked within the ETF cohort.

Computes:
  - EV/EBITDA, P/E (trailing + forward), EV/Sales, P/B, EV/Gross Profit
  - ROIC = EBIT*(1-0.21) / (totalDebt + bookValue*shares)
  - WACC ≈ 4.5% + beta*5.5%   (ROIC-WACC spread = value creation indicator)
  - Gross Margin, Operating Margin, Net Margin
  - Sector-specific extras (FCF Yield, Div Yield, ROE, Op Leverage, etc.)

Input:
  - Default: reads discovery-output.json (written by stock-discovery.py)
  - Override: python fundamentals-scanner.py NVDA MSFT AAPL  (manual tickers)
  - Fallback: watchlist.json

Output:
  - 3 Discord text messages per ETF bucket (header/top5 + full table + sector context)
  - 1 scatter chart per ETF bucket (X=valuation attractiveness, Y=ROIC spread)
"""

import io
import json
import math
import sys
import time
import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

# ── Discord ───────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1475327530025222164/"
    "_IAvJ8JX2HWXRPDYER00UN5qj07DyoPNTZlk04TFV3SDrEaHcIxxe0-4J85LNgziGE39"
)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ── ROIC / WACC assumptions ───────────────────────────────────────────────────
TAX_RATE  = 0.21   # US corporate blended effective rate
RISK_FREE = 0.045  # ~4.5% (approximate 10-year Treasury)
ERP       = 0.055  # 5.5% equity risk premium (Damodaran estimate)

# ── Sector display names ──────────────────────────────────────────────────────
SECTOR_DISPLAY = {
    "XLK": "Technology",    "XLF": "Financials",     "XLE": "Energy",
    "XLV": "Health Care",   "XLI": "Industrials",    "XLP": "Cons. Staples",
    "XLY": "Cons. Discret.", "XLU": "Utilities",     "XLC": "Comms",
    "XLB": "Materials",     "XLRE": "Real Estate",
}


# ── Input loading ─────────────────────────────────────────────────────────────

def load_input_tickers() -> dict[str, list[str]]:
    """
    Returns etf_buckets: {"ETF": [tickers...], ...}

    Priority:
    1. CLI args → single bucket {"CUSTOM": sys.argv[1:]}
    2. discovery-output.json (fresh < 24h) → {"XLP": [...], ...}
    3. watchlist.json fallback → {"WATCHLIST": [...]}
    """
    if len(sys.argv) > 1:
        tickers = [t.upper().strip() for t in sys.argv[1:]]
        print(f"  CLI override: {len(tickers)} tickers → CUSTOM bucket")
        return {"CUSTOM": tickers}

    discovery_path = TOOLS_DIR / "discovery-output.json"
    if discovery_path.exists():
        age_hours = (time.time() - discovery_path.stat().st_mtime) / 3600
        if age_hours < 24:
            with open(discovery_path) as f:
                data = json.load(f)
            picks = data.get("top_picks", {})
            if picks:
                total = sum(len(v) for v in picks.values())
                print(f"  discovery-output.json ({age_hours:.1f}h old): {len(picks)} ETFs, {total} tickers")
                return picks
        else:
            print(f"  discovery-output.json is {age_hours:.1f}h old — using watchlist fallback")

    watchlist_path = TOOLS_DIR / "watchlist.json"
    if watchlist_path.exists():
        with open(watchlist_path) as f:
            wl = json.load(f)
        tickers = wl.get("tickers", list(wl.get("stocks", {}).get("holdings", {}).keys()))
        print(f"  Watchlist fallback: {len(tickers)} tickers")
        return {"WATCHLIST": tickers}

    print("  No input found — exiting", file=sys.stderr)
    sys.exit(1)


def load_etf_holdings() -> dict:
    path = TOOLS_DIR / "etf-holdings.json"
    with open(path) as f:
        return json.load(f)


def resolve_sector(etf: str, holdings_data: dict) -> str:
    """Maps ETF symbol to CW sector string (e.g. 'XLK', 'XLF')."""
    entry = holdings_data.get(etf, {})
    sector = entry.get("sector", "")
    if sector in SECTOR_DISPLAY:
        return sector
    # If ETF is itself a CW sector ETF
    if etf in SECTOR_DISPLAY:
        return etf
    # EW sector → map to CW
    ew_to_cw = {
        "RSPT": "XLK", "RSPF": "XLF", "RSPG": "XLE", "RSPH": "XLV",
        "RSPN": "XLI", "RSPS": "XLP", "RSPD": "XLY", "RSPU": "XLU",
        "RSPC": "XLC", "RSPM": "XLB", "RSPR": "XLRE",
    }
    return ew_to_cw.get(etf, "UNKNOWN")


def get_etf_display_name(etf: str, holdings_data: dict) -> str:
    """Returns a human-readable name for an ETF."""
    entry = holdings_data.get(etf, {})
    name = entry.get("name", "")
    if name:
        return name
    return SECTOR_DISPLAY.get(etf, etf)


# ── Data fetching ─────────────────────────────────────────────────────────────

from market_utils import yahoo_quote_summary as _yahoo_quote_summary


def fetch_fundamentals(ticker: str) -> dict | None:
    """Fetch Yahoo quoteSummary for a single ticker. Returns result[0] or None."""
    return _yahoo_quote_summary(ticker, "financialData,defaultKeyStatistics,earningsTrend", timeout=15)


def batch_fetch_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """Fetch quoteSummary for multiple tickers in rate-limit-safe batches."""
    results = {}
    BATCH_SIZE = 10

    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fetch_fundamentals, t): t for t in batch}
            for f in as_completed(futures):
                t = futures[f]
                try:
                    data = f.result()
                    if data is not None:
                        results[t] = data
                except Exception:
                    pass

        if i + BATCH_SIZE < len(tickers):
            time.sleep(2)

    return results


# ── Metric extraction ─────────────────────────────────────────────────────────

def _safe(d, *keys, default=None):
    """Safely traverse nested dict/list. Returns default if any key is missing."""
    if d is None:
        return default
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, list) and isinstance(k, int):
            d = d[k] if k < len(d) else None
        else:
            return default
        if d is None:
            return default
    return d


def compute_metrics(raw: dict, ticker: str) -> dict:
    """Parse quoteSummary result[0] into a flat metric dict."""
    fd = raw.get("financialData") or {}
    ks = raw.get("defaultKeyStatistics") or {}
    et = raw.get("earningsTrend") or {}

    price    = _safe(fd, "currentPrice", "raw")
    shares   = _safe(ks, "sharesOutstanding", "raw")
    ev       = _safe(ks, "enterpriseValue", "raw")

    revenue       = _safe(fd, "totalRevenue", "raw")
    gross_profit  = _safe(fd, "grossProfits", "raw")
    ebitda        = _safe(fd, "ebitda", "raw")
    ebit          = _safe(fd, "ebit", "raw")
    fcf           = _safe(fd, "freeCashflow", "raw")
    total_debt    = _safe(fd, "totalDebt", "raw")
    total_cash    = _safe(fd, "totalCash", "raw")
    book_value    = _safe(ks, "bookValue", "raw")

    trailing_pe = _safe(ks, "trailingPE", "raw")
    forward_pe  = _safe(ks, "forwardPE", "raw")
    ps_ratio    = _safe(ks, "priceToSalesTrailingTwelveMonths", "raw")
    pb_ratio    = _safe(ks, "priceToBook", "raw")
    beta        = _safe(ks, "beta", "raw")

    rev_growth   = _safe(fd, "revenueGrowth", "raw")
    earn_growth  = _safe(fd, "earningsGrowth", "raw")
    gross_margin = _safe(fd, "grossMargins", "raw")
    op_margin    = _safe(fd, "operatingMargins", "raw")
    net_margin   = _safe(fd, "profitMargins", "raw")
    roe          = _safe(fd, "returnOnEquity", "raw")
    roa          = _safe(fd, "returnOnAssets", "raw")
    div_yield    = _safe(fd, "dividendYield", "raw")

    # Forward estimates from earningsTrend
    trends = _safe(et, "trend") or []
    trend_0y = next((t for t in trends if isinstance(t, dict) and t.get("period") == "0y"), {})
    trend_1y = next((t for t in trends if isinstance(t, dict) and t.get("period") == "+1y"), {})
    fwd_eps_0y   = _safe(trend_0y, "earningsEstimate", "avg", "raw")
    fwd_eps_1y   = _safe(trend_1y, "earningsEstimate", "avg", "raw")
    fwd_rev_0y   = _safe(trend_0y, "revenueEstimate", "avg", "raw")
    fwd_rev_1y   = _safe(trend_1y, "revenueEstimate", "avg", "raw")
    eps_growth_0y = _safe(trend_0y, "growth", "raw")
    eps_growth_1y = _safe(trend_1y, "growth", "raw")

    # Computed multiples
    ev_ebitda = (ev / ebitda)        if (ev and ebitda and ebitda > 0)       else None
    ev_sales  = (ev / revenue)       if (ev and revenue and revenue > 0)     else None
    ev_gp     = (ev / gross_profit)  if (ev and gross_profit and gross_profit > 0) else None

    market_cap = (price * shares) if (price and shares) else None
    fcf_yield  = (fcf / market_cap) if (fcf and market_cap and market_cap > 0) else None

    return {
        "ticker": ticker,
        "price": price, "shares": shares, "market_cap": market_cap, "ev": ev,
        "revenue": revenue, "gross_profit": gross_profit, "ebitda": ebitda,
        "ebit": ebit, "fcf": fcf, "total_debt": total_debt,
        "total_cash": total_cash, "book_value": book_value,
        "trailing_pe": trailing_pe, "forward_pe": forward_pe,
        "ps_ratio": ps_ratio, "pb_ratio": pb_ratio, "beta": beta,
        "rev_growth": rev_growth, "earn_growth": earn_growth,
        "gross_margin": gross_margin, "op_margin": op_margin, "net_margin": net_margin,
        "roe": roe, "roa": roa, "div_yield": div_yield,
        "ev_ebitda": ev_ebitda, "ev_sales": ev_sales, "ev_gp": ev_gp,
        "fcf_yield": fcf_yield,
        "fwd_eps_0y": fwd_eps_0y, "fwd_eps_1y": fwd_eps_1y,
        "fwd_rev_0y": fwd_rev_0y, "fwd_rev_1y": fwd_rev_1y,
        "eps_growth_0y": eps_growth_0y, "eps_growth_1y": eps_growth_1y,
        "neg_equity": False,  # set by compute_roic_wacc
    }


def compute_roic_wacc(m: dict) -> dict:
    """
    ROIC = NOPAT / Invested Capital
      NOPAT = EBIT * (1 - 0.21)
      Invested Capital = totalDebt + (bookValue * shares)

    WACC ≈ 4.5% + min(beta, 3.0) * 5.5%
    Spread = ROIC% - WACC%
    """
    roic = wacc = spread = None
    neg_equity = False

    if m["ebit"] is not None:
        nopat = m["ebit"] * (1 - TAX_RATE)

        equity_capital = None
        if m["book_value"] is not None and m["shares"] is not None:
            equity_capital = m["book_value"] * m["shares"]

        debt_capital = m["total_debt"] or 0

        if equity_capital is not None and equity_capital < 0:
            neg_equity = True
            # Highly leveraged / buyback-heavy — use debt alone
            equity_capital = 0

        invested_capital = (equity_capital or 0) + debt_capital
        if invested_capital > 0:
            roic = nopat / invested_capital

    beta_raw = m["beta"]
    if beta_raw is None or beta_raw <= 0:
        beta_raw = 1.0  # assume market beta
    beta_capped = min(beta_raw, 3.0)
    wacc = RISK_FREE + beta_capped * ERP

    if roic is not None:
        spread = (roic - wacc) * 100

    return {
        "roic_pct":  round(roic * 100, 1) if roic is not None else None,
        "wacc_pct":  round(wacc * 100, 1),
        "spread":    round(spread, 1) if spread is not None else None,
        "neg_equity": neg_equity,
    }


def compute_sector_extras(m: dict, sector: str) -> dict:
    """Compute sector-appropriate supplementary display metrics."""
    extras = {}

    def _pct(val, sign=False):
        if val is None:
            return "N/A"
        pct = val * 100
        return f"{pct:+.1f}%" if sign else f"{pct:.1f}%"

    def _mult(val):
        return f"{val:.1f}x" if val is not None else "N/A"

    if sector == "XLK":
        extras["Rev Growth"] = _pct(m["rev_growth"], sign=True)
        extras["FCF Yield"]  = _pct(m["fcf_yield"])

    elif sector == "XLF":
        extras["ROE"] = _pct(m["roe"])
        extras["P/Book"] = _mult(m["pb_ratio"])

    elif sector == "XLE":
        extras["FCF Yield"] = _pct(m["fcf_yield"])
        extras["Div Yield"] = _pct(m["div_yield"])

    elif sector == "XLV":
        extras["Rev Growth"] = _pct(m["rev_growth"], sign=True)
        extras["Net Margin"] = _pct(m["net_margin"])

    elif sector == "XLI":
        op_lev = None
        if m["op_margin"] is not None and m["gross_margin"] and m["gross_margin"] != 0:
            op_lev = m["op_margin"] / m["gross_margin"]
        extras["Op Leverage"] = _mult(op_lev)
        extras["FCF Yield"]   = _pct(m["fcf_yield"])

    elif sector == "XLP":
        extras["Div Yield"]    = _pct(m["div_yield"])
        extras["Gross Margin"] = _pct(m["gross_margin"])

    elif sector == "XLY":
        extras["Rev Growth"] = _pct(m["rev_growth"], sign=True)
        extras["Op Margin"]  = _pct(m["op_margin"])

    elif sector == "XLU":
        extras["Div Yield"] = _pct(m["div_yield"])
        if m["fcf"] and m["market_cap"] and m["div_yield"]:
            div_amount = m["div_yield"] * m["market_cap"]
            payout = div_amount / m["fcf"] if m["fcf"] > 0 else None
            extras["Payout Ratio"] = f"{payout*100:.0f}%" if payout else "N/A"
        else:
            extras["Payout Ratio"] = "N/A"

    elif sector == "XLC":
        extras["EV/EBITDA"]  = _mult(m["ev_ebitda"])
        extras["Rev Growth"] = _pct(m["rev_growth"], sign=True)

    elif sector == "XLB":
        extras["EV/EBITDA"] = _mult(m["ev_ebitda"])
        extras["FCF Yield"] = _pct(m["fcf_yield"])

    elif sector == "XLRE":
        extras["P/Book"]   = _mult(m["pb_ratio"])
        extras["Div Yield"] = _pct(m["div_yield"])
        extras["Note"]      = "EBITDA/ROIC distorted (REIT)"

    else:
        # Generic fallback
        extras["Rev Growth"] = _pct(m["rev_growth"], sign=True)
        extras["FCF Yield"]  = _pct(m["fcf_yield"])

    return extras


# ── Scoring ───────────────────────────────────────────────────────────────────

def percentile_rank(values: list) -> list:
    """Higher raw value → higher rank (0-100). NaN → 50 (neutral)."""
    n = len(values)
    if n == 0:
        return []
    valid_idx = [i for i, v in enumerate(values)
                 if v is not None and not (isinstance(v, float) and math.isnan(v))]
    ranks = [50.0] * n
    if len(valid_idx) < 2:
        return ranks
    sorted_idx = sorted(valid_idx, key=lambda i: values[i])
    for rank_pos, idx in enumerate(sorted_idx):
        ranks[idx] = (rank_pos / max(len(sorted_idx) - 1, 1)) * 100
    return ranks


def percentile_rank_inverted(values: list) -> list:
    """Lower raw value → higher rank (inverted, for valuation multiples)."""
    n = len(values)
    if n == 0:
        return []
    valid_idx = [i for i, v in enumerate(values)
                 if v is not None and not (isinstance(v, float) and math.isnan(v))]
    ranks = [50.0] * n
    if len(valid_idx) < 2:
        return ranks
    # Sort descending → first item gets rank 100 (highest, meaning cheapest)
    sorted_idx = sorted(valid_idx, key=lambda i: values[i], reverse=True)
    for rank_pos, idx in enumerate(sorted_idx):
        ranks[idx] = (rank_pos / max(len(sorted_idx) - 1, 1)) * 100
    return ranks


def get_val_weights(sector: str) -> tuple:
    """Returns (ev_ebitda_w, fwd_pe_w, pb_w) for valuation sub-score."""
    if sector == "XLF":
        return (0.0, 0.60, 0.40)
    if sector == "XLRE":
        return (0.20, 0.30, 0.50)
    return (0.40, 0.40, 0.20)


def score_cohort(stocks: list[dict], sector: str) -> list[dict]:
    """Percentile-rank and score all stocks within an ETF cohort."""
    if len(stocks) < 2:
        for s in stocks:
            s.update({"val_score": 50, "qual_score": 50, "fwd_score": 50,
                       "final_score": 50, "thesis": "MIXED",
                       "ev_ebitda_rank": 50, "fwd_pe_rank": 50})
        return stocks

    def safe_list(key):
        return [s.get(key) for s in stocks]

    # Valuation (lower multiple = better = higher rank)
    ev_ebitda_ranks = percentile_rank_inverted(safe_list("ev_ebitda"))
    fwd_pe_ranks    = percentile_rank_inverted(safe_list("forward_pe"))
    pb_ranks        = percentile_rank_inverted(safe_list("pb_ratio"))

    # Quality (higher = better)
    spread_ranks = percentile_rank(safe_list("spread"))
    gm_ranks     = percentile_rank(safe_list("gross_margin"))
    om_ranks     = percentile_rank(safe_list("op_margin"))

    # Forward outlook (higher = better)
    rev_ranks    = percentile_rank(safe_list("rev_growth"))
    eps1y_ranks  = percentile_rank(safe_list("eps_growth_1y"))
    eps0y_ranks  = percentile_rank(safe_list("eps_growth_0y"))

    ev_w, pe_w, pb_w = get_val_weights(sector)

    for i, s in enumerate(stocks):
        val_score  = 40 * (ev_w * ev_ebitda_ranks[i] + pe_w * fwd_pe_ranks[i] + pb_w * pb_ranks[i]) / 100
        qual_score = 35 * (0.45 * spread_ranks[i] + 0.30 * gm_ranks[i] + 0.25 * om_ranks[i]) / 100
        fwd_score  = 25 * (0.35 * rev_ranks[i] + 0.40 * eps1y_ranks[i] + 0.25 * eps0y_ranks[i]) / 100

        s["val_score"]       = round(val_score, 1)
        s["qual_score"]      = round(qual_score, 1)
        s["fwd_score"]       = round(fwd_score, 1)
        s["final_score"]     = round(val_score + qual_score + fwd_score, 1)
        s["ev_ebitda_rank"]  = ev_ebitda_ranks[i]
        s["fwd_pe_rank"]     = fwd_pe_ranks[i]

        score = s["final_score"]
        if score >= 80:
            s["thesis"] = "STRONG"
        elif score >= 60:
            s["thesis"] = "GOOD"
        elif score >= 40:
            s["thesis"] = "MIXED"
        else:
            s["thesis"] = "WEAK"

    stocks.sort(key=lambda s: s["final_score"], reverse=True)
    return stocks


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fm(val, fmt=".1f", suffix="x", na="N/A") -> str:
    """Format a numeric value with suffix. Returns na if None/NaN."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return na
    return f"{val:{fmt}}{suffix}"


def _fp(val, sign=False, na="N/A") -> str:
    """Format a decimal as percentage (0.738 → '73.8%')."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return na
    pct = val * 100
    if sign:
        return f"{pct:+.1f}%"
    return f"{pct:.1f}%"


def _fs(val, na="N/A") -> str:
    """Format ROIC-WACC spread (already in %, has sign)."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return na
    return f"{val:+.1f}"


# ── Output formatting ─────────────────────────────────────────────────────────

def format_text_header(etf: str, etf_name: str, n: int, date_str: str, sector: str) -> str:
    lines = [
        "══════════════════════════════════════════",
        f"FUNDAMENTALS SCANNER — {etf} ({etf_name})",
        f"{n} stocks analyzed | {date_str}",
        f"Sector: {SECTOR_DISPLAY.get(sector, sector)} | Scoring: Valuation(40%) + Quality(35%) + Outlook(25%)",
        "══════════════════════════════════════════",
        "",
        "TOP 5 FUNDAMENTAL PICKS:",
    ]
    return "\n".join(lines)


def format_top5(stocks: list[dict]) -> str:
    lines = []
    for i, s in enumerate(stocks[:5], 1):
        flags = " ⚠ NEG EQUITY" if s.get("neg_equity") else ""
        thesis_full = {
            "STRONG": "STRONG FUNDAMENTAL THESIS",
            "GOOD":   "GOOD FUNDAMENTAL THESIS",
            "MIXED":  "MIXED THESIS",
            "WEAK":   "WEAK FUNDAMENTALS",
        }.get(s["thesis"], s["thesis"])
        lines.append(f"#{i} {s['ticker']:<6} Score: {s['final_score']:.0f}  {thesis_full}{flags}")
    return "\n".join(lines)


def format_full_table(stocks: list[dict], sector: str) -> str:
    """Returns the full monospace metrics table wrapped in a Discord code block."""
    # Header row
    hdr = f"{'TICKER':<7} {'EV/EBITDA':>9} {'P/E':>7} {'FwdPE':>6} {'EV/S':>6} {'P/B':>6} {'ROIC%':>6} {'WACC%':>6} {'Spread':>7} {'GrMgn':>6} {'OpMgn':>6} {'Score':>5}  Thesis"
    sep = "─" * len(hdr)

    rows = [hdr, sep]
    for s in stocks:
        ticker = s["ticker"]
        ev_eb  = _fm(s.get("ev_ebitda"), ".1f")
        tpe    = _fm(s.get("trailing_pe"), ".1f")
        fpe    = _fm(s.get("forward_pe"), ".1f")
        ev_s   = _fm(s.get("ev_sales"), ".1f")
        pb     = _fm(s.get("pb_ratio"), ".1f")
        roic   = f"{s['roic_pct']:.1f}" if s.get("roic_pct") is not None else "N/A"
        wacc   = f"{s['wacc_pct']:.1f}" if s.get("wacc_pct") is not None else "N/A"
        spread = _fs(s.get("spread"))
        gm     = _fp(s.get("gross_margin"))
        om     = _fp(s.get("op_margin"))
        score  = f"{s['final_score']:.0f}"
        thesis = s.get("thesis", "N/A")
        flag   = "⚠" if s.get("neg_equity") else " "

        rows.append(
            f"{ticker:<7} {ev_eb:>9} {tpe:>7} {fpe:>6} {ev_s:>6} {pb:>6} "
            f"{roic:>6} {wacc:>6} {spread:>7} {gm:>6} {om:>6} {score:>5}  {thesis}{flag}"
        )

    table = "\n".join(rows)
    return f"```\nFULL BREAKDOWN:\n{table}\n```"


def format_sector_context(top5: list[dict], sector: str, etf_name: str) -> str:
    """Format sector-specific supplementary metrics for top 5 stocks."""
    if not top5:
        return ""

    sector_full = SECTOR_DISPLAY.get(sector, sector)
    lines = [f"SECTOR CONTEXT ({sector_full}-Specific):"]

    # Collect all extra keys present across top 5
    all_keys = []
    for s in top5:
        for k in (s.get("sector_extras") or {}):
            if k not in all_keys and k != "Note":
                all_keys.append(k)

    for key in all_keys:
        parts = []
        for s in top5:
            val = (s.get("sector_extras") or {}).get(key, "N/A")
            parts.append(f"{s['ticker']} {val}")
        lines.append(f"  {key:<12}: {' | '.join(parts)}")

    # Show note (e.g. REIT distortion warning) if any
    for s in top5:
        note = (s.get("sector_extras") or {}).get("Note")
        if note:
            lines.append(f"  Note: {note}")
            break

    # Also show EV/Gross Profit if available
    evgp_parts = []
    for s in top5:
        evgp = _fm(s.get("ev_gp"), ".1f")
        evgp_parts.append(f"{s['ticker']} {evgp}")
    if any(s.get("ev_gp") is not None for s in top5):
        lines.append(f"  {'EV/GrossProfit':<12}: {' | '.join(evgp_parts)}")

    return "\n".join(lines)


# ── Chart ──────────────────────────────────────────────────────────────────────

def render_scatter(etf: str, etf_name: str, stocks: list[dict]) -> io.BytesIO:
    """
    Scatter: X = EV/EBITDA valuation attractiveness (percentile, 100=cheapest)
             Y = ROIC-WACC spread (%)
             Size = Revenue growth (larger = faster growth)
             Color = Fwd P/E attractiveness (green=cheap, red=expensive)
    """
    BG = "#1a1a2e"
    fig, ax = plt.subplots(figsize=(11, 8))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    xs, ys, szs, cs, labels = [], [], [], [], []

    for s in stocks:
        x = s.get("ev_ebitda_rank")
        y = s.get("spread")
        if x is None or y is None:
            continue
        rev_g = s.get("rev_growth") or 0
        size = max(40, min(abs(rev_g) * 1200 + 50, 500))
        fwd_rank = s.get("fwd_pe_rank", 50)

        xs.append(x)
        ys.append(y)
        szs.append(size)
        cs.append(fwd_rank)
        labels.append(s["ticker"])

    if not xs:
        ax.text(0.5, 0.5, "Insufficient data for chart", color="white",
                ha="center", va="center", transform=ax.transAxes, fontsize=14)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, facecolor=BG, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf

    scatter = ax.scatter(xs, ys, s=szs, c=cs, cmap="RdYlGn", vmin=0, vmax=100,
                         alpha=0.85, edgecolors="white", linewidths=0.5)

    # Reference lines
    ax.axhline(0, color="#666", linestyle="--", linewidth=0.9, zorder=0)
    ax.axvline(50, color="#666", linestyle="--", linewidth=0.9, zorder=0)

    # Quadrant labels (smaller, subtle)
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    pad_x = (xlim[1] - xlim[0]) * 0.05
    pad_y = (ylim[1] - ylim[0]) * 0.04
    quad_kw = dict(color="#888", fontsize=7.5, ha="center", va="center", style="italic")
    mid_x_r = (50 + min(105, xlim[1])) / 2
    mid_x_l = (max(-5, xlim[0]) + 50) / 2
    mid_y_t = (0 + ylim[1]) / 2
    mid_y_b = (ylim[0] + 0) / 2
    ax.text(mid_x_r, mid_y_t, "Cheap + Value Creators",  **quad_kw)
    ax.text(mid_x_l, mid_y_t, "Pricey + Value Creators", **quad_kw)
    ax.text(mid_x_r, mid_y_b, "Cheap + Destroyers",      **quad_kw)
    ax.text(mid_x_l, mid_y_b, "Pricey + Destroyers",     **quad_kw)

    # Annotations
    for i, (x, y, label) in enumerate(zip(xs, ys, labels)):
        is_top5 = i < len([s for s in stocks if s.get("ev_ebitda_rank") is not None and
                            s.get("spread") is not None])
        rank_in_score = next((j for j, s in enumerate(stocks) if s["ticker"] == label), 99)
        color  = "white"  if rank_in_score < 5  else "#aaaaaa"
        weight = "bold"   if rank_in_score < 5  else "normal"
        fsize  = 9        if rank_in_score < 5  else 7.5
        ax.annotate(label, (x, y), xytext=(8, 6), textcoords="offset points",
                    color=color, fontsize=fsize, fontweight=weight)

    # Colorbar
    cbar = plt.colorbar(scatter, ax=ax, pad=0.02, fraction=0.03)
    cbar.set_label("Fwd P/E Attractiveness\n(100 = Cheapest)", color="white", fontsize=8)
    cbar.ax.yaxis.set_tick_params(color="white")
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="white", fontsize=7)

    # Legend note
    ax.text(0.98, 0.02, "Bubble size ∝ Revenue Growth",
            transform=ax.transAxes, color="#888", fontsize=7.5,
            ha="right", va="bottom")

    ax.set_xlabel("Valuation Attractiveness — EV/EBITDA %-ile (100 = Cheapest)",
                  color="white", fontsize=9)
    ax.set_ylabel("ROIC − WACC Spread  (%pts)", color="white", fontsize=9)
    ax.set_title(f"Fundamentals: {etf} ({etf_name})", color="white", fontsize=13, fontweight="bold")

    ax.tick_params(colors="white", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#444")
    ax.grid(alpha=0.08, color="white")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── Discord posting ───────────────────────────────────────────────────────────

def send_discord_text(text: str):
    if len(text) > 1950:
        text = text[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Discord text failed: {e}")


def send_discord_image(buf: io.BytesIO, filename: str):
    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            files={"file": (filename, buf, "image/png")},
            timeout=60,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  Discord image failed: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} ET  Starting Fundamentals Scanner")

    holdings_data = load_etf_holdings()
    etf_buckets   = load_input_tickers()

    total_tickers = sum(len(v) for v in etf_buckets.values())
    print(f"  {len(etf_buckets)} ETF bucket(s), {total_tickers} tickers total")

    # Header post
    etf_list = ", ".join(etf_buckets.keys())
    send_discord_text(
        f"**Fundamentals Scanner** — {now_et.strftime('%a %b %d %I:%M %p ET')}\n"
        f"ETFs: {etf_list} | Stocks: {total_tickers}\n"
        f"Scoring: Valuation(40%) + Quality(35%) + Forward Outlook(25%)"
    )

    for etf, tickers in etf_buckets.items():
        print(f"\n  [{etf}] {len(tickers)} tickers: {', '.join(tickers)}")

        sector   = resolve_sector(etf, holdings_data)
        etf_name = get_etf_display_name(etf, holdings_data)

        # Fetch
        raw_data = batch_fetch_fundamentals(tickers)
        print(f"    Fetched {len(raw_data)}/{len(tickers)} tickers")

        if len(raw_data) < 2:
            send_discord_text(
                f"**{etf}**: Only {len(raw_data)} tickers returned data — skipping."
            )
            continue

        # Compute
        all_metrics = []
        for ticker, raw in raw_data.items():
            try:
                m = compute_metrics(raw, ticker)
                roic_wacc = compute_roic_wacc(m)
                m.update(roic_wacc)
                m["sector_extras"] = compute_sector_extras(m, sector)
                all_metrics.append(m)
            except Exception as e:
                print(f"    {ticker}: metric error: {e}", file=sys.stderr)

        if not all_metrics:
            continue

        # Score and rank
        all_metrics = score_cohort(all_metrics, sector)

        date_str = now_et.strftime("%Y-%m-%d")

        # Message 1: header + top5
        header  = format_text_header(etf, etf_name, len(all_metrics), date_str, sector)
        top5_str = format_top5(all_metrics)
        send_discord_text(f"{header}\n{top5_str}")

        # Message 2: full table
        table_msg = format_full_table(all_metrics, sector)
        # Split if over limit (rare but possible with many tickers)
        if len(table_msg) > 1950:
            half = len(all_metrics) // 2
            send_discord_text(format_full_table(all_metrics[:half], sector))
            send_discord_text(format_full_table(all_metrics[half:], sector))
        else:
            send_discord_text(table_msg)

        # Message 3: sector context (top 5 only)
        context_msg = format_sector_context(all_metrics[:5], sector, etf_name)
        if context_msg:
            send_discord_text(context_msg)

        # Chart
        buf = render_scatter(etf, etf_name, all_metrics)
        if buf.getbuffer().nbytes > 500:
            send_discord_image(buf, f"fundamentals_{etf.lower()}.png")
            print(f"    Chart posted for {etf}")

    print(f"\n{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} ET  Fundamentals Scanner complete")


if __name__ == "__main__":
    main()
