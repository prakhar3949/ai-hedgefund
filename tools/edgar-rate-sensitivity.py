"""
edgar-rate-sensitivity.py — Pull each bank's ACTUAL interest-rate-risk (EAR) table from its
latest 10-Q/10-K and extract the Net-Interest-Income-at-Risk sensitivity (ΔNII per rate shock).

This is the real confirmation of the rate-hike-beneficiary thesis — the bank's own one-year NII
simulation under parallel +/-100/200/300bp shocks, disclosed in the Quantitative/Qualitative
Disclosures About Market Risk (Item 3) section. Asset-sensitive (hike winner) ⇒ +200bp row is
POSITIVE. Liability-sensitive (cut winner) ⇒ +200bp row is NEGATIVE.

Usage: python edgar-rate-sensitivity.py MCB WSBC FFBC NRIM AMAL OPHC BFC BHRB ORRF
"""

from __future__ import annotations
import re
import sys
import time
import requests
from bs4 import BeautifulSoup

H = {"User-Agent": "Prakhar Goyal prakhar3949@gmail.com"}

_TICKERS_MAP: dict[str, str] = {}


def cik_for(ticker: str) -> str | None:
    global _TICKERS_MAP
    if not _TICKERS_MAP:
        d = requests.get("https://www.sec.gov/files/company_tickers.json", headers=H, timeout=20).json()
        for _, v in d.items():
            _TICKERS_MAP[(v.get("ticker") or "").upper()] = str(v.get("cik_str")).zfill(10)
    return _TICKERS_MAP.get(ticker.upper())


def latest_filing(cik: str) -> tuple[str, str, str] | None:
    """Return (form, filingDate, doc_url) for the most recent 10-Q (fallback 10-K)."""
    sub = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=H, timeout=20).json()
    rec = sub["filings"]["recent"]
    for want in ("10-Q", "10-K"):
        for i, f in enumerate(rec["form"]):
            if f == want:
                acc = rec["accessionNumber"][i].replace("-", "")
                doc = rec["primaryDocument"][i]
                cik_int = int(cik)
                url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/{doc}"
                return f, rec["filingDate"][i], url
    return None


def get_text(url: str) -> str:
    html = requests.get(url, headers=H, timeout=40).text
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    # Strip zero-width / non-breaking spaces that EDGAR HTML litters between cells
    text = text.replace("​", " ").replace("\xa0", " ").replace(" ", " ")
    return re.sub(r"[ \t]+", " ", text)


_SHOCK_TOKEN = re.compile(r"[+\-−](?:100|200|300)\b")


def _find_region(text: str, length: int = 1700) -> tuple[int, str] | None:
    """Locate the NII table by shock-token density: the window holding the most
    +/-100/200/300 tokens with 'interest income' nearby."""
    low = text.lower()
    positions = [m.start() for m in _SHOCK_TOKEN.finditer(text)]
    if not positions:
        return None
    best_pos, best_cnt = None, 0
    for p in positions:
        cnt = sum(1 for q in positions if p <= q < p + length)
        if cnt > best_cnt and "interest income" in low[max(0, p - 500):p + length]:
            best_cnt, best_pos = cnt, p
    if best_pos is None or best_cnt < 3:
        return None
    return best_pos, text[best_pos:best_pos + length]


def parse_shock_rows(region: str) -> list[tuple[int, float]]:
    """Extract (bp_shock, pct_change) rows. Parens ⇒ negative. $ amount column optional."""
    # signed 3-digit bp, optional $ amount, then a percentage (maybe parenthesised)
    pat = re.compile(
        r"([+\-−])\s?(100|200|300)\b[^%\dA-Za-z(]{0,15}(?:\$?\s?[\d,]{3,}\s+)?(\(?\s?\d+\.\d+\s?\)?)")
    rows = []
    seen = set()
    for m in pat.finditer(region):
        sign = -1 if m.group(1) in "-−" else 1
        bp = sign * int(m.group(2))
        pct_raw = m.group(3).replace(" ", "")
        neg = pct_raw.startswith("(")
        try:
            pct = float(pct_raw.strip("()"))
        except ValueError:
            continue
        if neg:
            pct = -pct
        if bp in seen:          # repeats ⇒ next table started
            break
        seen.add(bp)
        rows.append((bp, pct))
    rows.sort(key=lambda r: r[0], reverse=True)
    return rows


def parse_column_major(region: str) -> list[tuple[int, float]]:
    """Transposed layout: bp shocks in a header row, %ΔNII in a separate 'NII / Year 1' row.
    e.g. '... rates -100 bps +100 bps +200 bps NII-Year 1 (3.34)% 2.45% 4.32% ...'"""
    for anchor in re.finditer(r"(NII[\s-]*Year\s*1|Net interest income|Year\s*1)", region, re.I):
        before = region[max(0, anchor.start() - 300):anchor.start()]
        after = region[anchor.end():anchor.end() + 250]
        bps = [(-1 if s in "-−" else 1) * int(n)
               for s, n in re.findall(r"([+\-−])\s?(100|200|300)\s*bp", before, re.I)]
        pcts = []
        for p in re.findall(r"(\(?\s?\d+\.\d+\s?\)?)\s*%", after):
            p = p.replace(" ", "")
            pcts.append(-float(p.strip("()")) if p.startswith("(") else float(p.strip("()")))
        pcts = pcts[:len(bps)]
        if len(bps) >= 2 and len(bps) == len(pcts):
            return sorted(zip(bps, pcts), key=lambda r: r[0], reverse=True)
    return []


def classify(rows: list[tuple[int, float]]) -> str:
    d = dict(rows)
    up = d.get(200, d.get(100))
    if up is None:
        return "UNKNOWN"
    if up >= 1.0:
        return f"ASSET-SENSITIVE (hike winner): +200bp ⇒ {d.get(200, up):+.2f}% NII"
    if up <= -1.0:
        return f"LIABILITY-SENSITIVE (cut winner): +200bp ⇒ {d.get(200, up):+.2f}% NII"
    return f"~NEUTRAL: +200bp ⇒ {d.get(200, up):+.2f}% NII"


def run(ticker: str):
    print(f"\n{'='*68}\n{ticker}")
    cik = cik_for(ticker)
    if not cik:
        print("  no CIK"); return
    f = latest_filing(cik)
    if not f:
        print("  no 10-Q/10-K"); return
    form, date, url = f
    print(f"  {form} filed {date}")
    try:
        text = get_text(url)
    except Exception as e:
        print(f"  fetch err: {e}"); return

    reg = _find_region(text)
    if not reg:
        print("  NII-at-risk table not located (non-standard format — check filing manually)")
        return
    rows = parse_shock_rows(reg[1])
    if len(rows) < 2:
        rows = parse_column_major(reg[1])
    if len(rows) < 2:
        print("  table found but rows unparsed; raw snippet:")
        print("   " + re.sub(r"\s+", " ", reg[1][:600]))
        return
    print(f"  NII-at-Risk (1yr ΔNII):  " + "  ".join(f"{bp:+d}bp:{pct:+.2f}%" for bp, pct in rows))
    print(f"  → {classify(rows)}")


def main():
    tickers = [t.upper().lstrip("$") for t in sys.argv[1:]] or \
              ["MCB", "WSBC", "FFBC", "NRIM", "AMAL", "OPHC", "BFC", "BHRB", "ORRF"]
    for t in tickers:
        try:
            run(t)
        except Exception as e:
            print(f"  [{t}] ERROR: {e}")
        time.sleep(0.7)  # SEC fair-access


if __name__ == "__main__":
    main()
