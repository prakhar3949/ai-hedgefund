"""
FRED CSV fetcher. No API key required.

Returns monthly-resampled Series by default. Pass freq=None to keep raw cadence.
Cached daily.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / "_cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_TTL_SECONDS = 24 * 60 * 60


def _cache_path(series_id, freq):
    return CACHE_DIR / ("fred_" + series_id + "_" + str(freq) + ".parquet")


def _is_fresh(path):
    if not path.exists():
        return False
    return datetime.now().timestamp() - path.stat().st_mtime < CACHE_TTL_SECONDS


def fetch(series_id, freq="M", force=False):
    """
    freq: 'M' (month-end) | 'MS' (month-start) | None (raw)
    """
    path = _cache_path(series_id, freq)
    if not force and _is_fresh(path):
        s = pd.read_parquet(path).iloc[:, 0]
        s.name = series_id
        return s

    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series_id
    last_err = None
    for attempt in range(3):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tf:
                tmp_path = tf.name
            cmd = ["curl", "-sSL", "--max-time", "30",
                   "-A", "Mozilla/5.0", "-o", tmp_path, url]
            proc = subprocess.run(cmd, capture_output=True, timeout=45)
            if proc.returncode != 0:
                raise RuntimeError("curl exit " + str(proc.returncode) + ": " + proc.stderr.decode(errors="ignore"))
            with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
            Path(tmp_path).unlink(missing_ok=True)
            if not raw.lstrip().startswith("observation_date") and not raw.lstrip().startswith("DATE"):
                raise RuntimeError("FRED bad response head: " + raw[:120])
            break
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    else:
        raise last_err
    df = pd.read_csv(io.StringIO(raw))
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    s = pd.to_numeric(df[series_id], errors="coerce").dropna()
    s.index = df[date_col].iloc[s.index]
    s = s.sort_index()

    if freq is not None:
        s = s.resample("MS").last().ffill(limit=1)

    s.name = series_id
    s.to_frame().to_parquet(path)
    return s


if __name__ == "__main__":
    for sid in ["CPIAUCSL", "DGS10", "FEDFUNDS", "BAA10Y", "T10YIE",
                "VIXCLS", "USREC", "NFCI", "INDPRO", "PCEC96"]:
        try:
            s = fetch(sid)
            print(sid, "n=", len(s), s.index.min().date(), "->", s.index.max().date(),
                  "latest=", round(float(s.iloc[-1]), 3))
        except Exception as e:
            print(sid, "FAILED", e)
        time.sleep(0.5)
