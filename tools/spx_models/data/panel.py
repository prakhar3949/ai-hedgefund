"""
Build the unified monthly macro panel for SPX fair-value models.

Columns (all month-start indexed):
    spx         : SPX monthly close. multpl pre-2010 + Yahoo extension to live.
    eps_ttm     : trailing-12m operating EPS for SPX (multpl).
    cape        : Shiller CAPE = SPX / 10y avg of real EPS (multpl direct).
    pe_ttm      : trailing P/E (multpl direct).
    div_yield   : trailing dividend yield in pct (multpl).
    eps_yield   : trailing earnings yield in pct (multpl).
    book_value  : SPX book value per share (multpl).
    bm          : computed book-to-market = book_value / spx.
    cpi         : CPI level (multpl, sourced from BLS via multpl).
    cpi_yoy     : 12m % change in CPI.
    yield10     : 10Y Treasury nominal yield in pct (multpl, history back to 1871).
    real_yield10: 10Y real yield = yield10 - cpi_yoy.

Yahoo-macro overlay (post-1986 only — fills in FRED gap when FRED unreachable):
    tbl         : 3-month T-bill yield in pct from ^IRX. Welch-Goyal's TBL.
    lty         : 10Y nominal from ^TNX. Used to validate multpl `yield10` and as
                  the W-G `LTY` predictor.
    yield30     : 30Y nominal from ^TYX.
    yield5      : 5Y nominal from ^FVX.
    term_spread : lty - tbl. Welch-Goyal's TMS.
    vix         : CBOE volatility index from ^VIX. (post-1990 only.)
    dy_lag      : log-dividend-yield with t-1 price = log(D_t / P_{t-1}). Welch-Goyal DY.
                  (`div_yield` from multpl already uses contemporaneous prices, so
                   we compute the lagged version separately for W-G fidelity.)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import fetch_multpl, fetch_yahoo, fetch_yahoo_macro


def build_panel():
    # multpl provides full monthly SPX back to 1871, current through last completed month.
    spx = fetch_multpl.fetch("s-p-500-historical-prices").copy()
    spx.name = "spx"

    # Yahoo provides live intra-month spot — append as a "current" row past multpl's tail.
    try:
        spx_live = fetch_yahoo.fetch_monthly_close("^GSPC", "1y")
        live_latest = spx_live.iloc[-1:]
        if live_latest.index[-1] > spx.index[-1]:
            spx = pd.concat([spx, live_latest]).sort_index()
    except Exception:
        pass

    df = pd.DataFrame({"spx": spx})
    eps = fetch_multpl.fetch("s-p-500-earnings")
    df["eps_ttm"] = eps
    # Forward-fill EPS up to 6 months for live SPX months that out-run S&P's reporting cycle.
    df["eps_ttm_ffill"] = eps.reindex(df.index).ffill(limit=12)
    df["cape"] = fetch_multpl.fetch("shiller-pe")
    df["div_yield"] = fetch_multpl.fetch("s-p-500-dividend-yield")
    df["book_value"] = fetch_multpl.fetch("s-p-500-book-value")
    df["cpi"] = fetch_multpl.fetch("cpi")
    df["yield10"] = fetch_multpl.fetch("10-year-treasury-rate")

    # Computed (more reliable than multpl's pe-ratio which placeholders to 1.0 when EPS missing)
    df["pe_ttm"] = df["spx"] / df["eps_ttm_ffill"]
    df["eps_yield"] = 100 / df["pe_ttm"]
    # multpl reports book value quarterly with up to 6m lag; ffill for monthly use.
    df["book_value_ffill"] = df["book_value"].ffill(limit=12)
    df["bm"] = df["book_value_ffill"] / df["spx"]
    df["cpi_yoy"] = df["cpi"].pct_change(12, fill_method=None) * 100
    df["real_yield10"] = df["yield10"] - df["cpi_yoy"]

    # Welch-Goyal DY uses the *lagged* price: log(D_t / P_{t-1}). Multpl's
    # div_yield is D_t / P_t (contemporaneous), so reconstruct.
    div_level = df["div_yield"] / 100.0 * df["spx"]  # implied annual dividend
    df["dy_lag"] = np.log((div_level / df["spx"].shift(1)).replace(0, np.nan))

    # Yahoo-macro overlay (post-1986 except VIX post-1990). Reindexed to df.
    for sym, col in [("^IRX", "tbl"), ("^TNX", "lty"), ("^TYX", "yield30"),
                     ("^FVX", "yield5"), ("^VIX", "vix")]:
        try:
            s = fetch_yahoo_macro.fetch(sym)
            df[col] = s.reindex(df.index)
        except Exception:
            df[col] = float("nan")

    df["term_spread"] = df["lty"] - df["tbl"]

    return df.sort_index()


if __name__ == "__main__":
    p = build_panel()
    print("Panel shape:", p.shape)
    print("Date range:", p.index.min().date(), "->", p.index.max().date())
    print()
    print("Latest 6 rows of selected columns:")
    cols = ["spx", "eps_ttm_ffill", "cape", "pe_ttm", "yield10",
            "cpi_yoy", "real_yield10", "bm", "tbl", "term_spread", "vix"]
    print(p[cols].tail(6).round(2).to_string())
