"""
bank-risk-screen.py — The "third leg": balance-sheet fragility that the EAR table can't see.

Separates FFBC-type survivors from EWBC-type fragile names using the exact factors that blew up
regionals in March 2023 (and which forward NII-sensitivity says nothing about):

  UNINSURED DEPOSIT %   = uninsured deposits / total deposits        (deposit-flight / funding-run risk)
  CRE CONCENTRATION     = investor-CRE / total loans                 (asset-concentration risk)
  CRE / CAPITAL         = investor-CRE / total risk-based capital     (the 2006 interagency 300% guidance)
  AOCI / TCE            = accumulated OCI / tangible common equity    (unrealized securities-loss drag)

Investor-CRE (per regulatory guidance) = construction&land + multifamily + non-owner-occ nonfarm-nonres
(excludes owner-occupied, which is operating-business risk, not CRE-cycle risk).

Data:
  FDIC Financial (Call Report) API — uninsured deposits, CRE buckets, loans, capital  (by bank CERT)
  SEC EDGAR XBRL companyconcept    — AOCI total + its 2022-23 trough                  (by holding-co CIK)

CERTs hand-mapped for the shortlist (lead bank of each holding co) for accuracy — fuzzy name search
is unreliable and FDIC has no ticker field. Add more in CERT_MAP to extend.

Usage: python bank-risk-screen.py            (shortlist)
       python bank-risk-screen.py WSFS EWBC
"""
from __future__ import annotations
import sys, time
import requests

H = {"User-Agent": "Prakhar Goyal prakhar3949@gmail.com"}

# ticker → (FDIC CERT of lead bank, bank name)
CERT_MAP = {
    "WSFS": (17838, "Wilmington Savings Fund Society, FSB"),
    "FFBC": (6600,  "First Financial Bank (Cincinnati)"),
    "WSBC": (803,   "WesBanco Bank, Inc."),
    "EWBC": (31628, "East West Bank"),
}

FDIC_FIELDS = ("REPDTE,DEP,DEPUNA,LNLSGR,LNRECONS,LNREMULT,LNRENROT,LNRENROW,"
               "RBC,RBCT1J,EQ,INTAN,ASSET,SCAF,SCHA")


def fdic_latest(cert: int) -> dict | None:
    r = requests.get("https://banks.data.fdic.gov/api/financials",
                     params={"filters": f"CERT:{cert}", "fields": FDIC_FIELDS,
                             "sort_by": "REPDTE", "sort_order": "DESC", "limit": 1, "format": "json"},
                     headers=H, timeout=20)
    d = r.json().get("data", [])
    return d[0]["data"] if d else None


_CIK: dict[str, str] = {}


def cik_for(ticker: str) -> str | None:
    global _CIK
    if not _CIK:
        ct = requests.get("https://www.sec.gov/files/company_tickers.json", headers=H, timeout=20).json()
        for _, v in ct.items():
            _CIK[(v.get("ticker") or "").upper()] = str(v.get("cik_str")).zfill(10)
    return _CIK.get(ticker.upper())


def edgar_aoci(ticker: str) -> tuple[float | None, float | None, str | None]:
    """Return (latest AOCI, worst AOCI 2022-2024, latest date) in $thousands (to match FDIC)."""
    cik = cik_for(ticker)
    if not cik:
        return None, None, None
    url = (f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/"
           "AccumulatedOtherComprehensiveIncomeLossNetOfTax.json")
    r = requests.get(url, headers=H, timeout=20)
    if r.status_code != 200:
        return None, None, None
    pts = [x for x in r.json().get("units", {}).get("USD", []) if x.get("end")]
    if not pts:
        return None, None, None
    pts.sort(key=lambda x: x["end"])
    latest = pts[-1]
    trough = min((x for x in pts if "2022-01-01" <= x["end"] <= "2024-12-31"),
                 key=lambda x: x["val"], default=None)
    return (latest["val"] / 1e3, (trough["val"] / 1e3 if trough else None), latest["end"])


def compute(ticker: str) -> dict:
    cert, name = CERT_MAP.get(ticker, (None, None))
    m = {"ticker": ticker, "name": name}
    if cert is None:
        m["err"] = "no CERT mapped"
        return m
    f = fdic_latest(cert)
    if not f:
        m["err"] = "FDIC no data"
        return m

    dep, depuna = f.get("DEP"), f.get("DEPUNA")
    loans = f.get("LNLSGR")
    rbc = f.get("RBC")
    eq, intan = f.get("EQ"), f.get("INTAN") or 0
    investor_cre = (f.get("LNRECONS") or 0) + (f.get("LNREMULT") or 0) + (f.get("LNRENROT") or 0)
    tce = eq - intan if eq is not None else None

    m["repdte"] = f.get("REPDTE")
    m["uninsured_pct"] = (depuna / dep * 100) if (depuna and dep) else None
    m["cre_loans_pct"] = (investor_cre / loans * 100) if (investor_cre and loans) else None
    m["cre_capital_pct"] = (investor_cre / rbc * 100) if (investor_cre and rbc) else None

    aoci, aoci_trough, asof = edgar_aoci(ticker)
    m["aoci_tce_pct"] = (aoci / tce * 100) if (aoci is not None and tce) else None
    m["aoci_trough_tce_pct"] = (aoci_trough / tce * 100) if (aoci_trough is not None and tce) else None
    m["aoci_asof"] = asof
    return m


def flags(m: dict) -> str:
    out = []
    if (m.get("uninsured_pct") or 0) > 40:
        out.append("HIGH-UNINSURED")
    if (m.get("cre_capital_pct") or 0) > 300:
        out.append("CRE>300%CAP")
    elif (m.get("cre_capital_pct") or 0) > 200:
        out.append("CRE-elevated")
    if (m.get("aoci_tce_pct") or 0) < -10:
        out.append("AOCI-DRAG")
    return " ".join(out) or "clean"


def main():
    tickers = [t.upper().lstrip("$") for t in sys.argv[1:]] or list(CERT_MAP)
    rows = [compute(t) for t in tickers]

    def fp(v, suf="%"):
        return f"{v:.0f}{suf}" if v is not None else "—"

    hdr = (f"{'TKR':<6}{'Uninsured':>11}{'CRE/Loans':>11}{'CRE/Cap':>9}"
           f"{'AOCI/TCE':>10}{'AOCI low':>10}  Flags")
    print(hdr); print("-" * (len(hdr) + 18))
    for m in rows:
        if m.get("err"):
            print(f"{m['ticker']:<6}  {m['err']}"); continue
        print(f"{m['ticker']:<6}{fp(m['uninsured_pct']):>11}{fp(m['cre_loans_pct']):>11}"
              f"{fp(m['cre_capital_pct']):>9}{fp(m['aoci_tce_pct']):>10}"
              f"{fp(m['aoci_trough_tce_pct']):>10}  {flags(m)}")
    rd = next((m.get("repdte") for m in rows if m.get("repdte")), "?")
    print(f"\nFDIC Call Report as of {rd}. Investor-CRE = constr+multifam+non-owner-occ CRE.")
    print("CRE/Cap vs the 2006 interagency 300%-of-capital guidance threshold.")
    print("AOCI/TCE: current unrealized-loss drag; 'AOCI low' = worst 2022-24 reading / current TCE.")


if __name__ == "__main__":
    main()
