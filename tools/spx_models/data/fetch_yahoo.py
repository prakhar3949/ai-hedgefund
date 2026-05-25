"""
Yahoo Finance Chart API fetcher. Used for live SPX price (multpl lags by ~1mo).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import requests


def fetch_monthly_close(ticker, period="max"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + ticker +
           "?range=" + period + "&interval=1mo")
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    j = r.json()
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    dates = [pd.Timestamp(datetime.utcfromtimestamp(t)).to_period("M").to_timestamp() for t in ts]
    s = pd.Series(closes, index=dates, name=ticker).dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def fetch_daily_close(ticker, period="2y"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + ticker +
           "?range=" + period + "&interval=1d")
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    j = r.json()
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    dates = [pd.Timestamp(datetime.utcfromtimestamp(t)).normalize() for t in ts]
    return pd.Series(closes, index=dates, name=ticker).dropna()


if __name__ == "__main__":
    s = fetch_monthly_close("^GSPC", "max")
    print("SPX monthly n=", len(s), "first=", s.index[0].date(), "last=", s.index[-1].date(),
          "latest close=", round(float(s.iloc[-1]), 2))
