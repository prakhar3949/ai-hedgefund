"""
multpl.com scraper.

multpl.com hosts the canonical Robert Shiller dataset as HTML tables, updated
monthly. Used because Shiller's own .xls hasn't been refreshed since Sep 2023
and the datahub mirror is also stale at that boundary.

Series available (slug -> meaning):
    s-p-500-earnings           -> TTM EPS for SPX
    shiller-pe                  -> CAPE
    s-p-500-pe-ratio            -> trailing P/E
    s-p-500-dividend-yield      -> trailing dividend yield (pct)
    s-p-500-earnings-yield      -> trailing E/P (pct)
    s-p-500-book-value          -> SPX book value per share
    s-p-500-historical-prices   -> SPX monthly close
    10-year-treasury-rate       -> nominal 10Y yield (pct)
    cpi                          -> CPI level (index)
    inflation-rate              -> headline CPI YoY (pct)
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

CACHE_DIR = Path(__file__).resolve().parent.parent / "_cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL_SECONDS = 24 * 60 * 60

_CELL_RE = re.compile(r"<td[^>]*>([^<]+)</td>", re.DOTALL)
_DATE_RE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")
_WS_RE = re.compile(r"[\s  ]+|&#x[0-9a-fA-F]+;|&nbsp;")


def _cache_path(slug):
    return CACHE_DIR / ("multpl_" + slug + ".parquet")


def _is_fresh(path):
    if not path.exists():
        return False
    age = datetime.now().timestamp() - path.stat().st_mtime
    return age < CACHE_TTL_SECONDS


def fetch(slug, force=False):
    path = _cache_path(slug)
    if not force and _is_fresh(path):
        s = pd.read_parquet(path).iloc[:, 0]
        s.name = slug
        return s

    url = "https://www.multpl.com/" + slug + "/table/by-month"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    html = r.text

    raw_cells = _CELL_RE.findall(html)
    cells = [_WS_RE.sub(" ", c).strip() for c in raw_cells]

    rows = []
    for i in range(len(cells) - 1):
        if _DATE_RE.match(cells[i]):
            v = cells[i + 1].replace(",", "").replace("$", "").replace("%", "").strip()
            m = _NUM_RE.search(v)
            if m:
                try:
                    val = float(m.group(0).replace(",", ""))
                except ValueError:
                    continue
                dt = pd.to_datetime(cells[i]).to_period("M").to_timestamp()
                rows.append((dt, val))

    if not rows:
        raise RuntimeError("multpl parse returned 0 rows for " + slug)

    s = pd.Series({d: v for d, v in rows}).sort_index()
    s.name = slug
    s.to_frame().to_parquet(path)
    return s


if __name__ == "__main__":
    for slug in [
        "s-p-500-earnings",
        "shiller-pe",
        "s-p-500-historical-prices",
        "10-year-treasury-rate",
        "cpi",
    ]:
        s = fetch(slug, force=True)
        print(slug, "n=", len(s), s.index.min().date(), "->", s.index.max().date(), "latest=", s.iloc[-1])
