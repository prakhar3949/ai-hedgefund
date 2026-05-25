"""
fundamental-thesis.py — Per-ticker fundamental thesis builder.

Inputs (priority): CLI tickers > thesis-candidates.json > error.
For each ticker: sector classification, latest quarterly financials, forward guidance proxy
(analyst consensus next Q / FY), value/growth (Russell-style), sector-specific metric pack,
quality/moat, growth durability, balance sheet, sentiment (short interest, days-to-cover,
analyst target dispersion), insider buys (Alpha Vantage), last offering (SEC EDGAR),
Scion Tragic Algebra ΔE lookup, bull/bear case paragraphs.

Output: per-ticker Discord text post + scatter chart, then summary table comparing tickers.
"""

from __future__ import annotations
import io
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests

from market_utils import yahoo_quote_summary, YAHOO_HEADERS as _YHEADERS_SHARED  # noqa: F401

TOOLS_DIR = Path(__file__).resolve().parent

DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1506874137174474782/"
    "UtCFhd_UkykNtsx-0X4u_iT3GYIAwsIhYNWQPv5kVCU9HwGIB36LPsfJEMkSE_XSj0LJ"
)

ALPHA_VANTAGE_KEY = "1SIVEVQAAYTRTLBV"

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
EDGAR_HEADERS = {"User-Agent": "Prakhar Goyal prakhar3949@gmail.com"}


# ── Discord ───────────────────────────────────────────────────────────────────

def send_discord_text(text: str):
    # Chunk to 2000 chars
    for i in range(0, len(text), 1900):
        chunk = text[i:i + 1900]
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=30)
            time.sleep(0.4)
        except Exception as e:
            print(f"  discord text err: {e}", file=sys.stderr)


def send_discord_image(buf: io.BytesIO, filename: str):
    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            files={"file": (filename, buf, "image/png")},
            timeout=60,
        )
        time.sleep(0.5)
    except Exception as e:
        print(f"  discord img err: {e}", file=sys.stderr)


# ── Inputs ────────────────────────────────────────────────────────────────────

def load_tickers() -> list[str]:
    if len(sys.argv) > 1:
        return [t.upper().strip() for t in sys.argv[1:] if t.strip()]
    p = TOOLS_DIR / "thesis-candidates.json"
    if p.exists():
        try:
            d = json.loads(p.read_text())
            return [t.upper().strip() for t in d.get("tickers", []) if t.strip()]
        except Exception:
            pass
    print("no tickers — pass CLI args or populate thesis-candidates.json", file=sys.stderr)
    return []


def load_tragic_algebra() -> dict:
    p = TOOLS_DIR / "tragic-algebra.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text()).get("tickers", {})
    except Exception:
        return {}


# ── Yahoo quoteSummary ────────────────────────────────────────────────────────

QS_MODULES = ",".join([
    "assetProfile", "summaryDetail", "financialData", "defaultKeyStatistics",
    "earningsTrend", "incomeStatementHistory", "incomeStatementHistoryQuarterly",
    "balanceSheetHistory", "balanceSheetHistoryQuarterly",
    "cashflowStatementHistory", "cashflowStatementHistoryQuarterly",
    "insiderTransactions", "recommendationTrend", "price",
])


def fetch_quote_summary(ticker: str) -> dict | None:
    return yahoo_quote_summary(ticker, QS_MODULES)


def _safe(d, *keys, default=None):
    if d is None:
        return default
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, list) and isinstance(k, int):
            d = d[k] if -len(d) <= k < len(d) else None
        else:
            return default
        if d is None:
            return default
    return d


def raw(d, *keys):
    """Get nested .raw value."""
    v = _safe(d, *keys, "raw")
    return v


# ── Sector classification & metric packs ──────────────────────────────────────

SECTOR_PACK = {
    # Maps Yahoo sector → metric pack identifier
    "Technology": "TECH",
    "Communication Services": "TECH",
    "Financial Services": "FIN",
    "Healthcare": "HEALTH",
    "Energy": "ENERGY",
    "Real Estate": "REIT",
    "Consumer Cyclical": "CONS",
    "Consumer Defensive": "STAPLES",
    "Industrials": "INDU",
    "Utilities": "UTIL",
    "Basic Materials": "MATL",
}

# Industries that override sector pack
INDUSTRY_OVERRIDE = {
    "insurance": "INSURANCE",
    "banks": "BANK",
    "bank": "BANK",
    "credit services": "FIN",
    "biotechnology": "BIOTECH",
    "drug manufacturers": "PHARMA",
    "semiconductor": "SEMI",
    "software": "SOFTWARE",
    "internet retail": "TECH",
    "internet content": "TECH",
    "reit": "REIT",
    "auto manufacturers": "AUTO",
}


def classify_sector(profile: dict) -> tuple[str, str, str]:
    sector = profile.get("sector") or "Unknown"
    industry = profile.get("industry") or ""
    pack = SECTOR_PACK.get(sector, "GENERIC")
    il = industry.lower()
    for k, v in INDUSTRY_OVERRIDE.items():
        if k in il:
            pack = v
            break
    return sector, industry, pack


# ── Metric extraction ─────────────────────────────────────────────────────────

def extract_base(qs: dict) -> dict:
    fd = qs.get("financialData") or {}
    ks = qs.get("defaultKeyStatistics") or {}
    sd = qs.get("summaryDetail") or {}
    et = qs.get("earningsTrend") or {}
    pr = qs.get("price") or {}

    m = {
        "price": raw(fd, "currentPrice") or raw(pr, "regularMarketPrice"),
        "market_cap": raw(pr, "marketCap") or raw(sd, "marketCap"),
        "enterprise_value": raw(ks, "enterpriseValue"),
        "shares_out": raw(ks, "sharesOutstanding"),
        "float": raw(ks, "floatShares"),
        "beta": raw(ks, "beta"),

        # Valuation
        "trailing_pe": raw(ks, "trailingPE") or raw(sd, "trailingPE"),
        "forward_pe": raw(ks, "forwardPE") or raw(sd, "forwardPE"),
        "peg": raw(ks, "pegRatio"),
        "ps": raw(ks, "priceToSalesTrailingTwelveMonths") or raw(sd, "priceToSalesTrailingTwelveMonths"),
        "pb": raw(ks, "priceToBook"),
        "ev_revenue": raw(ks, "enterpriseToRevenue"),
        "ev_ebitda": raw(ks, "enterpriseToEbitda"),

        # Income / margins
        "revenue": raw(fd, "totalRevenue"),
        "rev_growth_yoy": raw(fd, "revenueGrowth"),
        "earnings_growth_yoy": raw(fd, "earningsGrowth"),
        "gross_margin": raw(fd, "grossMargins"),
        "op_margin": raw(fd, "operatingMargins"),
        "profit_margin": raw(fd, "profitMargins"),
        "ebitda": raw(fd, "ebitda"),
        "ebit": raw(fd, "ebit"),
        "roe": raw(fd, "returnOnEquity"),
        "roa": raw(fd, "returnOnAssets"),

        # Cash
        "fcf": raw(fd, "freeCashflow"),
        "op_cashflow": raw(fd, "operatingCashflow"),
        "total_cash": raw(fd, "totalCash"),
        "total_debt": raw(fd, "totalDebt"),
        "current_ratio": raw(fd, "currentRatio"),
        "debt_to_equity": raw(fd, "debtToEquity"),
        "book_value": raw(ks, "bookValue"),

        # Dividends
        "div_yield": raw(sd, "dividendYield") or raw(sd, "trailingAnnualDividendYield"),
        "payout_ratio": raw(sd, "payoutRatio"),

        # Sentiment — short interest
        "short_float_pct": raw(ks, "shortPercentOfFloat"),
        "shares_short": raw(ks, "sharesShort"),
        "short_prior": raw(ks, "sharesShortPriorMonth"),
        "short_ratio": raw(ks, "shortRatio"),  # days-to-cover

        # Analyst targets
        "tgt_mean": raw(fd, "targetMeanPrice"),
        "tgt_high": raw(fd, "targetHighPrice"),
        "tgt_low": raw(fd, "targetLowPrice"),
        "tgt_median": raw(fd, "targetMedianPrice"),
        "rec_mean": raw(fd, "recommendationMean"),
        "n_analysts": raw(fd, "numberOfAnalystOpinions"),
    }

    # Forward guidance proxy — analyst estimates current Q, next Q, current Y, next Y
    trend = et.get("trend") or []
    guidance = {}
    for entry in trend:
        period = entry.get("period")
        if period in ("0q", "+1q", "0y", "+1y"):
            guidance[period] = {
                "revenue_est_avg": _safe(entry, "revenueEstimate", "avg", "raw"),
                "rev_growth_avg": _safe(entry, "revenueEstimate", "growth", "raw"),
                "eps_est_avg": _safe(entry, "earningsEstimate", "avg", "raw"),
                "eps_growth_avg": _safe(entry, "earningsEstimate", "growth", "raw"),
                "eps_30d_ago": _safe(entry, "epsTrend", "30daysAgo", "raw"),
                "eps_current": _safe(entry, "epsTrend", "current", "raw"),
            }
    m["guidance"] = guidance

    # EPS revision direction (3M trend on current FY)
    cy = guidance.get("0y", {})
    cur = cy.get("eps_current")
    ago30 = cy.get("eps_30d_ago")
    if cur is not None and ago30 not in (None, 0):
        m["eps_revision_30d_pct"] = (cur - ago30) / abs(ago30) * 100
    else:
        m["eps_revision_30d_pct"] = None

    return m


def extract_quarterly(qs: dict) -> dict:
    """Pull latest quarterly + 3 prior for trend."""
    inc_q = _safe(qs, "incomeStatementHistoryQuarterly", "incomeStatementHistory") or []
    cf_q = _safe(qs, "cashflowStatementHistoryQuarterly", "cashflowStatements") or []
    bs_q = _safe(qs, "balanceSheetHistoryQuarterly", "balanceSheetStatements") or []

    def _q(stmt_list, *keys):
        out = []
        for s in stmt_list[:4]:
            v = s
            for k in keys:
                v = (v or {}).get(k) if isinstance(v, dict) else None
            out.append(_safe(s, *keys, "raw"))
        return out

    sbc_q = _q(cf_q, "stockBasedCompensation")
    rev_q = _q(inc_q, "totalRevenue")
    ni_q = _q(inc_q, "netIncome")
    ocf_q = _q(cf_q, "totalCashFromOperatingActivities")
    capex_q = _q(cf_q, "capitalExpenditures")
    dates_q = [_safe(s, "endDate", "fmt") for s in inc_q[:4]]

    # SBC as % of revenue (latest Q)
    sbc_pct = None
    if sbc_q and rev_q and sbc_q[0] and rev_q[0]:
        sbc_pct = sbc_q[0] / rev_q[0] * 100

    # FCF conversion (latest TTM-ish: sum 4 Q)
    ocf_sum = sum(x for x in ocf_q if x)
    capex_sum = sum(x for x in capex_q if x)
    ni_sum = sum(x for x in ni_q if x)
    fcf_conv = None
    if ocf_sum and ni_sum and ni_sum > 0:
        fcf_conv = (ocf_sum + capex_sum) / ni_sum  # capex is negative

    # Rev decel: latest YoY vs avg of prior 3 Q YoY (approx — would need 8Q for real, here use linear delta)
    rev_seq_growth = None
    if len(rev_q) >= 2 and rev_q[0] and rev_q[1]:
        rev_seq_growth = (rev_q[0] / rev_q[1] - 1) * 100  # QoQ

    # Goodwill / total assets
    goodwill = _safe(bs_q, 0, "goodWill", "raw")
    total_assets = _safe(bs_q, 0, "totalAssets", "raw")
    goodwill_pct_assets = None
    if goodwill and total_assets:
        goodwill_pct_assets = goodwill / total_assets * 100

    # LT vs ST debt
    lt_debt = _safe(bs_q, 0, "longTermDebt", "raw")
    st_debt = _safe(bs_q, 0, "shortLongTermDebt", "raw")

    return {
        "latest_q_end": dates_q[0] if dates_q else None,
        "sbc_q": sbc_q,
        "rev_q": rev_q,
        "ni_q": ni_q,
        "sbc_pct_rev_latest": sbc_pct,
        "fcf_conversion_ttm": fcf_conv,
        "rev_qoq_growth_pct": rev_seq_growth,
        "goodwill_pct_assets": goodwill_pct_assets,
        "lt_debt": lt_debt,
        "st_debt": st_debt,
    }


# ── Share buybacks (capital return) ───────────────────────────────────────────

def extract_buybacks(qs: dict, m: dict) -> dict:
    """TTM share buybacks + dividend yield → total shareholder yield (Damodaran).

    Sources: cashflowStatementHistoryQuarterly (last 4Q) + cashflowStatementHistory
    (annual, for YoY trend). Yahoo reports repurchases as negative cash outflows;
    we sign-flip to positive "dollars spent on buybacks."
    """
    cf_q = _safe(qs, "cashflowStatementHistoryQuarterly", "cashflowStatements") or []
    cf_a = _safe(qs, "cashflowStatementHistory", "cashflowStatements") or []

    def _pull(stmts, key):
        return [_safe(s, key, "raw") for s in stmts]

    # Yahoo uses either name depending on filing; check both
    rep_q = _pull(cf_q[:4], "repurchaseOfStock")
    if not any(v for v in rep_q if v is not None):
        rep_q = _pull(cf_q[:4], "commonStockRepurchased")
    rep_a = _pull(cf_a[:3], "repurchaseOfStock")
    if not any(v for v in rep_a if v is not None):
        rep_a = _pull(cf_a[:3], "commonStockRepurchased")

    iss_q = _pull(cf_q[:4], "issuanceOfStock")
    sbc_q = _pull(cf_q[:4], "stockBasedCompensation")

    def _spent(vals):
        # Repurchases are reported negative; sign-flip to $ spent
        return sum(-v for v in vals if v is not None and v < 0)

    buyback_ttm = _spent(rep_q)
    iss_ttm = sum(v for v in iss_q if v is not None and v > 0)
    net_buyback_ttm = buyback_ttm - iss_ttm

    sbc_ttm = sum(v for v in sbc_q if v is not None and v > 0)
    sbc_adj_buyback_ttm = buyback_ttm - sbc_ttm  # buybacks net of SBC dilution drag

    mcap = m.get("market_cap")
    def _yld(num):
        return (num / mcap * 100) if (mcap and mcap > 0) else None

    buyback_yield = _yld(buyback_ttm) if buyback_ttm else None
    net_buyback_yield = _yld(net_buyback_ttm)
    sbc_adj_yield = _yld(sbc_adj_buyback_ttm) if sbc_adj_buyback_ttm else None

    div_yield = m.get("div_yield")  # Yahoo: fraction (0.025 = 2.5%)
    div_yield_pct = (div_yield * 100) if div_yield is not None else 0.0
    total_yield = (buyback_yield or 0) + div_yield_pct

    consistency = sum(1 for v in rep_q if v is not None and v < 0)
    latest_q = -rep_q[0] if (rep_q and rep_q[0] is not None and rep_q[0] < 0) else 0
    prior_q = -rep_q[1] if (len(rep_q) > 1 and rep_q[1] is not None and rep_q[1] < 0) else 0

    rep_a_pos = [-v for v in rep_a if v is not None and v < 0]
    annual_yoy = None
    if len(rep_a_pos) >= 2 and rep_a_pos[1] > 0:
        annual_yoy = (rep_a_pos[0] / rep_a_pos[1] - 1) * 100

    return {
        "buyback_ttm": buyback_ttm,
        "issuance_ttm": iss_ttm,
        "net_buyback_ttm": net_buyback_ttm,
        "sbc_adj_buyback_ttm": sbc_adj_buyback_ttm,
        "sbc_ttm": sbc_ttm,
        "buyback_yield_pct": buyback_yield,
        "net_buyback_yield_pct": net_buyback_yield,
        "sbc_adj_yield_pct": sbc_adj_yield,
        "div_yield_pct": div_yield_pct,
        "total_shareholder_yield_pct": total_yield,
        "consistency_4q": consistency,
        "latest_q": latest_q,
        "prior_q": prior_q,
        "annual_history_pos": rep_a_pos[:3],
        "annual_yoy_pct": annual_yoy,
    }


# ── Insider transactions (Yahoo) ─────────────────────────────────────────────

def extract_insider(qs: dict) -> dict:
    it = qs.get("insiderTransactions") or {}
    txns = it.get("transactions") or []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=180)).timestamp()
    buys = 0
    sells = 0
    buy_value = 0
    sell_value = 0
    for t in txns:
        ts = _safe(t, "startDate", "raw")
        if not ts or ts < cutoff:
            continue
        txt = (t.get("transactionText") or "").lower()
        val = _safe(t, "value", "raw") or 0
        if "purchase" in txt or "buy" in txt or "p - purchase" in txt:
            buys += 1
            buy_value += val
        elif "sale" in txt or "sell" in txt or "s - sale" in txt:
            sells += 1
            sell_value += val
    return {
        "insider_buys_180d": buys,
        "insider_sells_180d": sells,
        "insider_buy_value_180d": buy_value,
        "insider_sell_value_180d": sell_value,
        "insider_net_value_180d": buy_value - sell_value,
    }


# ── Alpha Vantage insider transactions (backup / richer) ──────────────────────

def fetch_av_insider(ticker: str) -> dict | None:
    url = f"https://www.alphavantage.co/query?function=INSIDER_TRANSACTIONS&symbol={ticker}&apikey={ALPHA_VANTAGE_KEY}"
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return None
        d = r.json()
        data = d.get("data") or []
        if not data:
            return None
        cutoff = datetime.now() - timedelta(days=180)
        buys = sells = 0
        buy_val = sell_val = 0.0
        for row in data:
            try:
                dt = datetime.strptime(row.get("transaction_date", ""), "%Y-%m-%d")
            except Exception:
                continue
            if dt < cutoff:
                continue
            atype = (row.get("acquisition_or_disposal") or "").upper()
            shares = float(row.get("shares") or 0)
            price = float(row.get("share_price") or 0)
            val = shares * price
            if atype == "A":
                buys += 1
                buy_val += val
            elif atype == "D":
                sells += 1
                sell_val += val
        return {
            "av_buys": buys, "av_sells": sells,
            "av_buy_val": buy_val, "av_sell_val": sell_val,
            "av_net_val": buy_val - sell_val,
        }
    except Exception as e:
        print(f"  av_insider({ticker}): {e}", file=sys.stderr)
        return None


# ── SEC EDGAR — last offering ─────────────────────────────────────────────────

_CIK_CACHE: dict[str, str] = {}


def get_cik(ticker: str) -> str | None:
    if ticker in _CIK_CACHE:
        return _CIK_CACHE[ticker]
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         headers=EDGAR_HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json()
        for _, v in data.items():
            t = (v.get("ticker") or "").upper()
            cik = str(v.get("cik_str") or "").zfill(10)
            _CIK_CACHE[t] = cik
        return _CIK_CACHE.get(ticker.upper())
    except Exception:
        return None


def fetch_last_offering(ticker: str) -> dict | None:
    cik = get_cik(ticker)
    if not cik:
        return None
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        r = requests.get(url, headers=EDGAR_HEADERS, timeout=20)
        if r.status_code != 200:
            return None
        d = r.json()
        recent = _safe(d, "filings", "recent") or {}
        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        offering_forms = {"S-1", "S-3", "S-3ASR", "424B1", "424B2", "424B3", "424B4", "424B5", "S-3/A", "F-1", "F-3"}
        cutoff = datetime.now() - timedelta(days=365)
        for i, f in enumerate(forms):
            if f in offering_forms:
                try:
                    fd = datetime.strptime(dates[i], "%Y-%m-%d")
                except Exception:
                    continue
                if fd >= cutoff:
                    return {"form": f, "date": dates[i],
                            "days_ago": (datetime.now() - fd).days}
        return {"form": None, "date": None, "days_ago": None}
    except Exception as e:
        print(f"  edgar({ticker}): {e}", file=sys.stderr)
        return None


# ── Russell-style Value/Growth ────────────────────────────────────────────────

def russell_vg(m: dict) -> tuple[str, float]:
    """Score -100 (deep value) to +100 (deep growth). Returns label, score."""
    # Value side: low fwd P/E, low P/B, high div yield
    # Growth side: high LT growth, high revenue growth, high momentum (proxy: low fwd P/E means cheap, high rev growth)
    value_pts = 0
    growth_pts = 0

    fpe = m.get("forward_pe")
    if fpe is not None:
        if fpe > 0 and fpe < 12:
            value_pts += 25
        elif fpe > 0 and fpe < 18:
            value_pts += 10
        elif fpe > 30:
            growth_pts += 15
        elif fpe > 50:
            growth_pts += 25

    pb = m.get("pb")
    if pb is not None:
        if pb < 1.5:
            value_pts += 20
        elif pb < 3:
            value_pts += 5
        elif pb > 8:
            growth_pts += 15

    dy = m.get("div_yield")
    if dy is not None:
        if dy > 0.03:
            value_pts += 20
        elif dy > 0.015:
            value_pts += 10
        elif dy == 0 or dy is None:
            growth_pts += 10

    rg = m.get("rev_growth_yoy")
    if rg is not None:
        if rg > 0.25:
            growth_pts += 30
        elif rg > 0.15:
            growth_pts += 20
        elif rg > 0.05:
            growth_pts += 5
        elif rg < 0:
            value_pts += 10

    eg = m.get("earnings_growth_yoy")
    if eg is not None:
        if eg > 0.20:
            growth_pts += 15
        elif eg < 0:
            value_pts += 5

    score = growth_pts - value_pts  # +ve growth, -ve value
    if score > 30:
        label = "GROWTH"
    elif score > 10:
        label = "GROWTH-TILT"
    elif score > -10:
        label = "BLEND"
    elif score > -30:
        label = "VALUE-TILT"
    else:
        label = "VALUE"
    return label, score


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_b(v):
    if v is None:
        return "n/a"
    if abs(v) >= 1e9:
        return f"${v/1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v/1e6:.1f}M"
    return f"${v:.0f}"


def _fmt_pct(v, scale=100):
    if v is None:
        return "n/a"
    return f"{v*scale:+.1f}%" if scale == 100 else f"{v:+.1f}%"


def _fmt_pct_abs(v, scale=100):
    if v is None:
        return "n/a"
    return f"{v*scale:.1f}%" if scale == 100 else f"{v:.1f}%"


def _fmt_x(v):
    return "n/a" if v is None else f"{v:.2f}x"


def _fmt_num(v):
    return "n/a" if v is None else f"{v:.2f}"


# ── Sector-specific extras ────────────────────────────────────────────────────

def sector_extras(pack: str, m: dict, q: dict, qs: dict) -> list[str]:
    """Returns a list of bullet strings for the sector-specific pack."""
    out = []
    if pack in ("TECH", "SOFTWARE", "SEMI"):
        rg = m.get("rev_growth_yoy")
        op = m.get("op_margin")
        rule40 = None
        if rg is not None and op is not None:
            rule40 = (rg + op) * 100
        out.append(f"Rule of 40: {f'{rule40:.0f}' if rule40 is not None else 'n/a'} (≥40 = elite SaaS)")
        out.append(f"EV/Revenue: {_fmt_x(m.get('ev_revenue'))}")
        sbc_v = q.get('sbc_pct_rev_latest')
        out.append(f"SBC %Rev (latest Q): {f'{sbc_v:.1f}%' if sbc_v is not None else 'n/a'}")
        out.append(f"Gross Margin: {_fmt_pct_abs(m.get('gross_margin'))}")
    elif pack == "BANK":
        out.append(f"P/Tangible Book proxy (P/B): {_fmt_x(m.get('pb'))}")
        out.append(f"ROE: {_fmt_pct_abs(m.get('roe'))}")
        out.append(f"Efficiency (1-OpMargin proxy): {_fmt_pct_abs(1 - m['op_margin']) if m.get('op_margin') is not None else 'n/a'}")
    elif pack == "INSURANCE":
        out.append(f"Combined ratio proxy: n/a (needs underwriting detail)")
        out.append(f"ROE: {_fmt_pct_abs(m.get('roe'))}")
        out.append(f"P/Book: {_fmt_x(m.get('pb'))}")
    elif pack == "REIT":
        # FCF ≈ AFFO proxy
        fcf_yield = None
        if m.get("fcf") and m.get("market_cap"):
            fcf_yield = m["fcf"] / m["market_cap"] * 100
        out.append(f"FCF Yield (AFFO proxy): {f'{fcf_yield:.1f}%' if fcf_yield is not None else 'n/a'}")
        out.append(f"P/Book: {_fmt_x(m.get('pb'))}")
        de_v = m.get('debt_to_equity')
        out.append(f"Debt/Equity: {f'{de_v:.0f}' if de_v else 'n/a'}")
        out.append(f"Div Yield: {_fmt_pct_abs(m.get('div_yield'))}")
    elif pack == "ENERGY":
        fcf_yield = None
        if m.get("fcf") and m.get("market_cap"):
            fcf_yield = m["fcf"] / m["market_cap"] * 100
        out.append(f"FCF Yield: {f'{fcf_yield:.1f}%' if fcf_yield is not None else 'n/a'}")
        out.append(f"Div Yield: {_fmt_pct_abs(m.get('div_yield'))}")
        nde_v = ((m.get('total_debt') or 0) - (m.get('total_cash') or 0)) / m['ebitda'] if m.get('total_debt') and m.get('ebitda') else None
        out.append(f"Net Debt/EBITDA: {f'{nde_v:.2f}x' if nde_v is not None else 'n/a'}")
    elif pack == "BIOTECH":
        runway_q = None
        if m.get("total_cash") and m.get("op_cashflow") and m["op_cashflow"] < 0:
            runway_q = m["total_cash"] / abs(m["op_cashflow"])
        out.append(f"Cash runway (Q at current burn): {f'{runway_q:.1f}Q' if runway_q is not None else 'n/a'}")
        out.append(f"Cash on hand: {_fmt_b(m.get('total_cash'))}")
        out.append(f"R&D-intensive — pipeline catalysts not modeled here")
    elif pack == "PHARMA":
        out.append(f"ROE: {_fmt_pct_abs(m.get('roe'))}")
        out.append(f"Op Margin: {_fmt_pct_abs(m.get('op_margin'))}")
        out.append(f"Div Yield: {_fmt_pct_abs(m.get('div_yield'))}")
    elif pack == "STAPLES":
        out.append(f"Div Yield: {_fmt_pct_abs(m.get('div_yield'))}")
        out.append(f"Payout Ratio: {_fmt_pct_abs(m.get('payout_ratio'))}")
        out.append(f"Op Margin: {_fmt_pct_abs(m.get('op_margin'))}")
    elif pack == "UTIL":
        out.append(f"Div Yield: {_fmt_pct_abs(m.get('div_yield'))}")
        out.append(f"Payout Ratio: {_fmt_pct_abs(m.get('payout_ratio'))}")
        de_v = m.get('debt_to_equity')
        out.append(f"Debt/Equity: {f'{de_v:.0f}' if de_v else 'n/a'}")
    elif pack == "AUTO":
        out.append(f"Op Margin: {_fmt_pct_abs(m.get('op_margin'))}")
        out.append(f"Gross Margin: {_fmt_pct_abs(m.get('gross_margin'))}")
        out.append(f"Rev Growth YoY: {_fmt_pct_abs(m.get('rev_growth_yoy'))}")
    elif pack == "INDU":
        out.append(f"Op Margin: {_fmt_pct_abs(m.get('op_margin'))}")
        out.append(f"ROIC proxy (ROA): {_fmt_pct_abs(m.get('roa'))}")
    return out


# ── Bull/bear thesis ──────────────────────────────────────────────────────────

def build_thesis(m: dict, q: dict, insider: dict, av_ins: dict | None,
                 tragic: dict | None, pack: str, vg_label: str,
                 buybacks: dict | None = None) -> tuple[list[str], list[str]]:
    bull = []
    bear = []

    # Valuation
    fpe = m.get("forward_pe")
    if fpe is not None:
        if 0 < fpe < 15:
            bull.append(f"Fwd P/E {fpe:.1f}x — attractive vs market")
        elif fpe > 40:
            bear.append(f"Fwd P/E {fpe:.1f}x — priced for perfection")

    eve = m.get("ev_ebitda")
    if eve is not None:
        if 0 < eve < 10:
            bull.append(f"EV/EBITDA {eve:.1f}x — cheap on cash earnings")
        elif eve > 25:
            bear.append(f"EV/EBITDA {eve:.1f}x — expensive on cash earnings")

    # Growth
    rg = m.get("rev_growth_yoy")
    if rg is not None:
        if rg > 0.20:
            bull.append(f"Revenue growing {rg*100:.0f}% YoY — strong top-line")
        elif rg < -0.05:
            bear.append(f"Revenue declining {rg*100:.0f}% YoY — top-line breakdown")

    # Margins
    om = m.get("op_margin")
    if om is not None:
        if om > 0.25:
            bull.append(f"Operating margin {om*100:.0f}% — high-quality business")
        elif om < 0.05:
            bear.append(f"Operating margin {om*100:.0f}% — thin profitability")

    # Cash flow
    fcf = m.get("fcf")
    if fcf is not None and m.get("market_cap"):
        fcf_yield = fcf / m["market_cap"] * 100
        if fcf > 0 and fcf_yield > 5:
            bull.append(f"FCF yield {fcf_yield:.1f}% — strong cash generation")
        elif fcf < 0:
            bear.append(f"Negative FCF ({_fmt_b(fcf)}) — burning cash")

    # Balance sheet
    if m.get("total_debt") and m.get("ebitda") and m["ebitda"] > 0:
        nd_ebitda = (m["total_debt"] - (m.get("total_cash") or 0)) / m["ebitda"]
        if nd_ebitda < 1:
            bull.append(f"Net Debt/EBITDA {nd_ebitda:.1f}x — fortress balance sheet")
        elif nd_ebitda > 4:
            bear.append(f"Net Debt/EBITDA {nd_ebitda:.1f}x — leveraged, refinancing risk")

    # ROE
    roe = m.get("roe")
    if roe is not None:
        if roe > 0.20:
            bull.append(f"ROE {roe*100:.0f}% — efficient capital deployment")
        elif roe < 0.05 and roe > -0.05:
            bear.append(f"ROE {roe*100:.0f}% — weak returns on equity")

    # SBC drag (live)
    sbc_pct = q.get("sbc_pct_rev_latest")
    if sbc_pct is not None:
        if sbc_pct > 15:
            bear.append(f"SBC {sbc_pct:.1f}% of revenue — heavy dilution drag")
        elif sbc_pct < 3:
            bull.append(f"SBC only {sbc_pct:.1f}% of revenue — minimal dilution")

    # Tragic Algebra
    if tragic:
        de = tragic.get("delta_e_pct")
        tier = tragic.get("tier")
        if tier == "TRAGIC":
            bear.append(f"Scion Tragic Tier: ΔE {de:+.0f}% — owner earnings negative once true SBC counted")
        elif tier == "NEGATIVE_OE":
            bear.append(f"Scion: cumulative owner earnings negative (true SBC cost = {_fmt_b(tragic.get('true_sbc_b')*1e9)})")
        elif de is not None and de > 95:
            bull.append(f"Scion ΔE {de:.0f}% — GAAP closely tracks true owner earnings, low SBC drag")
        elif de is not None and de < 75:
            bear.append(f"Scion ΔE {de:.0f}% — material SBC drag on owner earnings")

    # Insider
    nbuy = insider.get("insider_buys_180d", 0) + ((av_ins or {}).get("av_buys") or 0)
    if nbuy >= 3:
        bull.append(f"{nbuy} insider buy transactions in last 180d — insiders accumulating")
    nsell = insider.get("insider_sells_180d", 0) + ((av_ins or {}).get("av_sells") or 0)
    if nsell >= 10 and nbuy == 0:
        bear.append(f"{nsell} insider sells, zero buys in 180d — heavy insider distribution")

    # Short interest
    sf = m.get("short_float_pct")
    if sf is not None:
        if sf > 0.20:
            bear.append(f"Short interest {sf*100:.1f}% of float — heavy short bet against name")
        elif sf > 0.10:
            bear.append(f"Short interest {sf*100:.1f}% — elevated bearish positioning")

    # EPS revisions
    epsr = m.get("eps_revision_30d_pct")
    if epsr is not None:
        if epsr > 2:
            bull.append(f"FY EPS estimate revised +{epsr:.1f}% in 30d — analyst upgrades")
        elif epsr < -2:
            bear.append(f"FY EPS estimate revised {epsr:.1f}% in 30d — analyst downgrades")

    # Goodwill
    gw = q.get("goodwill_pct_assets")
    if gw is not None and gw > 40:
        bear.append(f"Goodwill {gw:.0f}% of assets — write-down risk")

    # Share buybacks / total shareholder yield
    if buybacks:
        nby = buybacks.get("net_buyback_yield_pct")
        sby = buybacks.get("sbc_adj_yield_pct")
        total = buybacks.get("total_shareholder_yield_pct") or 0
        if nby is not None:
            if nby >= 5:
                bull.append(f"Net buyback yield {nby:+.1f}% — aggressive shareholder return")
            elif nby <= -3:
                bear.append(f"Net dilution {nby:+.1f}% — issuing more than buying back")
        if total >= 8:
            bull.append(f"Total shareholder yield {total:.1f}% (buyback + div) — high cash return")
        if sby is not None and sby < -2 and (buybacks.get("buyback_ttm") or 0) > 0:
            bear.append(f"SBC-adj buyback yield {sby:+.1f}% — buybacks fail to offset SBC dilution")

    return bull, bear


# ── Render per-ticker report ──────────────────────────────────────────────────

def render_report(ticker: str, profile_meta: dict, m: dict, q: dict, guidance: dict,
                  insider: dict, av_ins: dict | None, offering: dict | None,
                  tragic: dict | None, sector: str, industry: str, pack: str,
                  vg_label: str, vg_score: float, bull: list[str], bear: list[str],
                  buybacks: dict | None = None) -> str:
    L = []
    L.append("═" * 56)
    L.append(f"FUNDAMENTAL THESIS — {ticker}")
    L.append("═" * 56)
    L.append(f"{profile_meta.get('longName') or profile_meta.get('shortName') or ticker}")
    L.append(f"Sector: {sector} | Industry: {industry} | Pack: {pack}")
    L.append(f"Style: {vg_label} (score {vg_score:+.0f})  |  Price: ${m.get('price') or 0:.2f}  |  MCap: {_fmt_b(m.get('market_cap'))}")
    L.append("")

    # Latest quarter financials
    L.append(f"── LAST QUARTER (period end: {q.get('latest_q_end') or 'n/a'}) ──")
    rev_q = q.get("rev_q") or []
    ni_q = q.get("ni_q") or []
    L.append(f"  Revenue (Q): {_fmt_b(rev_q[0] if rev_q else None)}  |  Net Income (Q): {_fmt_b(ni_q[0] if ni_q else None)}")
    L.append(f"  Revenue YoY: {_fmt_pct_abs(m.get('rev_growth_yoy'))}  |  Earnings YoY: {_fmt_pct_abs(m.get('earnings_growth_yoy'))}")
    L.append(f"  Gross Margin: {_fmt_pct_abs(m.get('gross_margin'))}  |  Op Margin: {_fmt_pct_abs(m.get('op_margin'))}  |  Profit Margin: {_fmt_pct_abs(m.get('profit_margin'))}")
    L.append(f"  EBITDA: {_fmt_b(m.get('ebitda'))}  |  Op CF: {_fmt_b(m.get('op_cashflow'))}  |  FCF: {_fmt_b(m.get('fcf'))}")
    L.append("")

    # Forward guidance proxy
    L.append("── FORWARD GUIDANCE (analyst consensus proxy) ──")
    for period, label in [("0q", "Current Q"), ("+1q", "Next Q"), ("0y", "Current FY"), ("+1y", "Next FY")]:
        g = guidance.get(period)
        if not g:
            continue
        rg = g.get("rev_growth_avg")
        eg = g.get("eps_growth_avg")
        L.append(f"  {label}: Rev {_fmt_pct_abs(rg)} | EPS Growth {_fmt_pct_abs(eg)} | EPS est ${g.get('eps_est_avg') or 0:.2f}")
    epsr = m.get("eps_revision_30d_pct")
    if epsr is not None:
        L.append(f"  FY EPS revision (30d): {epsr:+.1f}%")
    L.append("")

    # Valuation
    L.append("── VALUATION ──")
    L.append(f"  Trailing P/E: {_fmt_x(m.get('trailing_pe'))}  |  Fwd P/E: {_fmt_x(m.get('forward_pe'))}  |  PEG: {_fmt_x(m.get('peg'))}")
    L.append(f"  EV/EBITDA: {_fmt_x(m.get('ev_ebitda'))}  |  EV/Revenue: {_fmt_x(m.get('ev_revenue'))}  |  P/S: {_fmt_x(m.get('ps'))}  |  P/B: {_fmt_x(m.get('pb'))}")
    fcfy = None
    if m.get("fcf") and m.get("market_cap"):
        fcfy = m["fcf"] / m["market_cap"] * 100
    L.append(f"  FCF Yield: {f'{fcfy:.1f}%' if fcfy is not None else 'n/a'}  |  Div Yield: {_fmt_pct_abs(m.get('div_yield'))}")
    L.append("")

    # Quality / moat
    L.append("── QUALITY / MOAT ──")
    L.append(f"  ROE: {_fmt_pct_abs(m.get('roe'))}  |  ROA: {_fmt_pct_abs(m.get('roa'))}")
    fcfc = q.get('fcf_conversion_ttm')
    sbcp = q.get('sbc_pct_rev_latest')
    L.append(f"  FCF Conversion (TTM): {f'{fcfc:.2f}x NI' if fcfc is not None else 'n/a'}")
    L.append(f"  SBC % Revenue (latest Q): {f'{sbcp:.1f}%' if sbcp is not None else 'n/a'}")
    L.append("")

    # Balance sheet
    L.append("── BALANCE SHEET ──")
    nd = None
    if m.get("total_debt") is not None:
        nd = (m["total_debt"]) - (m.get("total_cash") or 0)
    nd_ebitda = None
    if nd is not None and m.get("ebitda") and m["ebitda"] > 0:
        nd_ebitda = nd / m["ebitda"]
    L.append(f"  Cash: {_fmt_b(m.get('total_cash'))}  |  Total Debt: {_fmt_b(m.get('total_debt'))}  |  Net Debt: {_fmt_b(nd)}")
    L.append(f"  ST Debt: {_fmt_b(q.get('st_debt'))}  |  LT Debt: {_fmt_b(q.get('lt_debt'))}")
    dev = m.get('debt_to_equity')
    gwp = q.get('goodwill_pct_assets')
    L.append(f"  Net Debt/EBITDA: {f'{nd_ebitda:.2f}x' if nd_ebitda is not None else 'n/a'}  |  D/E: {f'{dev:.0f}' if dev else 'n/a'}  |  Current Ratio: {_fmt_num(m.get('current_ratio'))}")
    L.append(f"  Goodwill % Assets: {f'{gwp:.0f}%' if gwp is not None else 'n/a'}")
    L.append("")

    # Share buybacks + dividends (total shareholder yield, Damodaran framework)
    L.append("── CAPITAL RETURN — BUYBACKS & DIVIDENDS ──")
    if buybacks:
        bb = buybacks
        if bb["buyback_ttm"]:
            L.append(f"  Buybacks TTM: {_fmt_b(bb['buyback_ttm'])}  |  Issuance TTM: {_fmt_b(bb['issuance_ttm'])}  |  Net: {_fmt_b(bb['net_buyback_ttm'])}")
        else:
            L.append(f"  Buybacks TTM: none reported  |  Issuance TTM: {_fmt_b(bb['issuance_ttm'])}")
        by = bb.get("buyback_yield_pct")
        nby = bb.get("net_buyback_yield_pct")
        sby = bb.get("sbc_adj_yield_pct")
        L.append(f"  Buyback Yield: {f'{by:.2f}%' if by is not None else 'n/a'}  |  Net (− issuance): {f'{nby:+.2f}%' if nby is not None else 'n/a'}  |  SBC-adj: {f'{sby:+.2f}%' if sby is not None else 'n/a'}")
        L.append(f"  Div Yield: {bb['div_yield_pct']:.2f}%  |  Total Shareholder Yield: {bb['total_shareholder_yield_pct']:.2f}% (buyback + div)")
        L.append(f"  Consistency: {bb['consistency_4q']}/4 quarters had buybacks  |  Latest Q: {_fmt_b(bb['latest_q'])}  |  Prior Q: {_fmt_b(bb['prior_q'])}")
        ay = bb.get("annual_yoy_pct")
        ah = bb.get("annual_history_pos") or []
        if ah:
            hist = " → ".join(_fmt_b(x) for x in reversed(ah))
            L.append(f"  Annual history (oldest → newest): {hist}" + (f"  |  YoY: {ay:+.0f}%" if ay is not None else ""))
        if bb.get("sbc_ttm"):
            L.append(f"  (SBC TTM: {_fmt_b(bb['sbc_ttm'])} — subtract from gross buybacks for real per-share accretion)")
    else:
        L.append("  No cashflow data available")
    L.append("")

    # Sector pack
    extras = sector_extras(pack, m, q, {})
    if extras:
        L.append(f"── {pack} METRIC PACK ──")
        for x in extras:
            L.append(f"  {x}")
        L.append("")

    # Tragic Algebra
    L.append("── SCION TRAGIC ALGEBRA (ΔE) ──")
    if tragic:
        L.append(f"  Years covered: {tragic.get('years')}  |  NDX wt: {tragic.get('ndx_wt_pct')}%")
        L.append(f"  GAAP NI: ${tragic.get('gaap_ni_b'):.1f}B  |  Wall St Adj: ${tragic.get('ws_adj_b'):.1f}B  |  True Owner Earnings: ${tragic.get('true_oe_b'):.1f}B")
        L.append(f"  True SBC Cost: ${tragic.get('true_sbc_b'):.1f}B  |  Tier: {tragic.get('tier')}")
        de = tragic.get('delta_e_pct')
        de_str = f"{de:+.1f}%" if abs(de) < 1000 else ("N/M (very large)" if de > 0 else "N/M (very negative)")
        L.append(f"  ΔE (OE/GAAP): {de_str}  |  GAAP overstate: {tragic.get('gaap_overstate_pct'):+.1f}%  |  WS overstate: {tragic.get('ws_overstate_pct'):+.1f}%")
    else:
        sbc_pct = q.get("sbc_pct_rev_latest")
        L.append(f"  No Scion data (outside NDX-97)")
        L.append(f"  Proxy: live SBC % Rev = {f'{sbc_pct:.1f}%' if sbc_pct is not None else 'n/a'} (>15% = heavy dilution drag)")
    L.append("")

    # Sentiment
    L.append("── SENTIMENT & POSITIONING ──")
    sf = m.get("short_float_pct")
    L.append(f"  Short % Float: {f'{sf*100:.2f}%' if sf is not None else 'n/a'}  |  Days-to-Cover: {_fmt_num(m.get('short_ratio'))}")
    if m.get("short_prior") and m.get("shares_short"):
        delta_short = (m["shares_short"] - m["short_prior"]) / m["short_prior"] * 100
        L.append(f"  Short interest MoM: {delta_short:+.1f}%")
    L.append(f"  Analyst Rec Mean: {_fmt_num(m.get('rec_mean'))} (1=StrongBuy, 5=Sell)  |  # Analysts: {m.get('n_analysts')}")
    if m.get("tgt_mean") and m.get("price"):
        upside = (m["tgt_mean"] / m["price"] - 1) * 100
        dispersion = None
        if m.get("tgt_high") and m.get("tgt_low") and m["tgt_mean"]:
            dispersion = (m["tgt_high"] - m["tgt_low"]) / m["tgt_mean"] * 100
        L.append(f"  Target: ${m['tgt_mean']:.2f} ({upside:+.1f}% upside) | Range ${m.get('tgt_low') or 0:.0f}-${m.get('tgt_high') or 0:.0f} | Dispersion: {f'{dispersion:.0f}%' if dispersion else 'n/a'}")
    L.append("")

    # Insider
    L.append("── INSIDER ACTIVITY (180d) ──")
    nb = insider.get("insider_buys_180d", 0)
    ns = insider.get("insider_sells_180d", 0)
    L.append(f"  Yahoo: {nb} buys (${insider.get('insider_buy_value_180d', 0)/1e6:.1f}M) | {ns} sells (${insider.get('insider_sell_value_180d', 0)/1e6:.1f}M) | Net: ${insider.get('insider_net_value_180d', 0)/1e6:+.1f}M")
    if av_ins:
        L.append(f"  AlphaV: {av_ins.get('av_buys', 0)} buys (${av_ins.get('av_buy_val', 0)/1e6:.1f}M) | {av_ins.get('av_sells', 0)} sells (${av_ins.get('av_sell_val', 0)/1e6:.1f}M) | Net: ${av_ins.get('av_net_val', 0)/1e6:+.1f}M")
    L.append("")

    # Offering
    L.append("── CAPITAL RAISES (SEC EDGAR, last 12mo) ──")
    if offering and offering.get("form"):
        L.append(f"  {offering['form']} filed {offering['date']} ({offering['days_ago']}d ago) — dilution / debt raise event")
    else:
        L.append(f"  No S-1/S-3/424B filings in last 12mo — clean")
    L.append("")

    # Bull / bear
    L.append("── BULL CASE ──")
    if bull:
        for b in bull:
            L.append(f"  + {b}")
    else:
        L.append("  (no strong bullish factors detected)")
    L.append("")
    L.append("── BEAR CASE ──")
    if bear:
        for b in bear:
            L.append(f"  - {b}")
    else:
        L.append("  (no strong bearish factors detected)")
    L.append("")
    L.append("═" * 56)
    return "\n".join(L)


# ── Scatter chart per ticker ──────────────────────────────────────────────────

def render_scatter(rows: list[dict]) -> io.BytesIO | None:
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(11, 7), facecolor="#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    for r in rows:
        x = r.get("ev_ebitda")
        y = r.get("roe")
        if x is None or y is None:
            continue
        size = max(80, min(800, (r.get("rev_growth") or 0) * 100 * 30 + 100))
        color = "#22c55e" if r.get("vg_label", "").startswith("VALUE") else (
                "#3b82f6" if r.get("vg_label") == "BLEND" else "#f59e0b")
        if r.get("tragic_tier") in ("TRAGIC", "NEGATIVE_OE"):
            color = "#ef4444"
        ax.scatter(x, y * 100, s=size, c=color, alpha=0.7, edgecolors="white", linewidth=1.0)
        ax.annotate(r["ticker"], (x, y * 100), color="white", fontsize=9,
                    xytext=(5, 5), textcoords="offset points")

    ax.set_xlabel("EV/EBITDA (lower = cheaper)", color="white", fontsize=11)
    ax.set_ylabel("ROE %", color="white", fontsize=11)
    ax.set_title("Fundamental Thesis Scatter — size=Rev Growth, color=Style (red=Scion Tragic)",
                 color="white", fontsize=12, pad=12)
    ax.tick_params(colors="white")
    ax.grid(True, alpha=0.2, color="white")
    for s in ax.spines.values():
        s.set_color("white")

    buf = io.BytesIO()
    plt.savefig(buf, format="png", facecolor="#1a1a2e", bbox_inches="tight", dpi=120)
    plt.close()
    buf.seek(0)
    return buf


# ── Summary table ─────────────────────────────────────────────────────────────

def render_summary(rows: list[dict]) -> str:
    L = ["", "═" * 80, "SUMMARY TABLE", "═" * 80, "```"]
    hdr = f"{'TKR':<6} {'STYLE':<11} {'FwdPE':>7} {'EV/EBI':>7} {'RevG':>7} {'OpM':>6} {'ROE':>6} {'ΔE':>7} {'TIER':<13}"
    L.append(hdr)
    L.append("-" * 80)
    for r in rows:
        fpe = r.get("forward_pe")
        eve = r.get("ev_ebitda")
        rg = r.get("rev_growth")
        om = r.get("op_margin")
        roe = r.get("roe")
        de = r.get("delta_e_pct")
        tier = r.get("tragic_tier") or "n/a"
        de_str = (f"{de:+.0f}%" if de is not None and abs(de) < 1000 else
                  ("N/M+" if de is not None and de > 0 else ("N/M-" if de is not None else "n/a")))
        L.append(
            f"{r['ticker']:<6} {r.get('vg_label','n/a'):<11} "
            f"{f'{fpe:.1f}' if fpe else 'n/a':>7} "
            f"{f'{eve:.1f}' if eve else 'n/a':>7} "
            f"{f'{rg*100:+.0f}%' if rg is not None else 'n/a':>7} "
            f"{f'{om*100:.0f}%' if om is not None else 'n/a':>6} "
            f"{f'{roe*100:.0f}%' if roe is not None else 'n/a':>6} "
            f"{de_str:>7} "
            f"{tier:<13}"
        )
    L.append("```")
    return "\n".join(L)


# ── Main pipeline per ticker ──────────────────────────────────────────────────

def process_ticker(ticker: str, tragic_db: dict) -> dict | None:
    print(f"\n[{ticker}] fetching...", file=sys.stderr)
    qs = fetch_quote_summary(ticker)
    if qs is None:
        print(f"  [{ticker}] no Yahoo data — skipping", file=sys.stderr)
        return None

    profile = qs.get("assetProfile") or {}
    price_meta = qs.get("price") or {}
    sector, industry, pack = classify_sector(profile)

    m = extract_base(qs)
    q = extract_quarterly(qs)
    insider = extract_insider(qs)
    buybacks = extract_buybacks(qs, m)

    print(f"  [{ticker}] fetching insider (AV) + EDGAR offering...", file=sys.stderr)
    av_ins = fetch_av_insider(ticker)
    offering = fetch_last_offering(ticker)

    tragic = tragic_db.get(ticker.upper())
    vg_label, vg_score = russell_vg(m)

    guidance = m.get("guidance", {})
    bull, bear = build_thesis(m, q, insider, av_ins, tragic, pack, vg_label, buybacks)

    report = render_report(
        ticker, price_meta, m, q, guidance,
        insider, av_ins, offering, tragic,
        sector, industry, pack, vg_label, vg_score, bull, bear,
        buybacks=buybacks,
    )

    print(f"  [{ticker}] posting to Discord...", file=sys.stderr)
    send_discord_text(report)

    return {
        "ticker": ticker,
        "vg_label": vg_label,
        "forward_pe": m.get("forward_pe"),
        "ev_ebitda": m.get("ev_ebitda"),
        "rev_growth": m.get("rev_growth_yoy"),
        "op_margin": m.get("op_margin"),
        "roe": m.get("roe"),
        "delta_e_pct": (tragic or {}).get("delta_e_pct"),
        "tragic_tier": (tragic or {}).get("tier"),
    }


def main():
    tickers = load_tickers()
    if not tickers:
        sys.exit(1)
    tragic_db = load_tragic_algebra()

    print(f"Processing {len(tickers)} tickers: {', '.join(tickers)}", file=sys.stderr)
    rows = []
    for t in tickers:
        try:
            r = process_ticker(t, tragic_db)
            if r:
                rows.append(r)
        except Exception as e:
            print(f"  [{t}] ERROR: {e}", file=sys.stderr)
        time.sleep(1.5)  # be polite to Yahoo / AV

    if rows:
        send_discord_text(render_summary(rows))
        buf = render_scatter(rows)
        if buf:
            send_discord_image(buf, "fundamental-thesis-scatter.png")

    print(f"\nDone. {len(rows)}/{len(tickers)} tickers processed.", file=sys.stderr)


if __name__ == "__main__":
    main()
