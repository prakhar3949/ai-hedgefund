"""
Macro SPX Fair-Value Model
==========================
Estimates S&P 500 fair value as EPS x P/E_fair, where P/E_fair is regressed on
macro variables: 10Y yield, CPI YoY, and the forward 12-month change in the
Fed Funds rate (a proxy for "expected cuts/hikes").

Data:
  - Shiller monthly dataset (datahub mirror): SP500, Earnings (TTM), CPI, Long Rate
  - FRED FEDFUNDS for forward-rate-path proxy
  - Sample: 1962-present (post-Treasury-Fed Accord modern era)

Model:
  P/E_t = a + b1*Yield10_t + b2*CPI_YoY_t + b3*FedFunds_Change_Fwd12m_t + e

Then:
  SPX_fair = current_TTM_EPS x predict_PE(scenario)

Scenarios checked: Calvasina's two anchors + a 5x5 sensitivity grid.

Posts to Discord (econ-predictor channel by default).
"""

import io
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import urllib.request
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

# Reuses econ-predictor webhook (macro topic). Swap if a dedicated channel is created.
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1471466326710288559/oOh2ApQCZ__k9feKMzgzJvuDb3jESFDZvyY8mYObjoDU_RIRLKAhpZK3vzZC2ijeRFNj"

SHILLER_URL = "https://datahub.io/core/s-and-p-500/r/data.csv"
FRED_FEDFUNDS = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS"

SAMPLE_START = "1962-01-01"

# Forward 2026 SPX EPS consensus (~$290 bottom-up, ~$275 top-down strategist median).
# Shiller dataset reports TTM and lags ~6 months; this is the forward EPS Calvasina
# is multiplying her implied P/E against. CLI override: python macro-spx-model.py --eps 285
DEFAULT_FWD_EPS = 290.0


# ─── Data ───────────────────────────────────────────────────────────

def fetch_shiller() -> pd.DataFrame:
    raw = urllib.request.urlopen(SHILLER_URL, timeout=30).read().decode()
    df = pd.read_csv(io.StringIO(raw))
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    df = df.rename(columns={
        "SP500": "spx",
        "Earnings": "eps_ttm",
        "Consumer Price Index": "cpi",
        "Long Interest Rate": "yield10",
    })[["spx", "eps_ttm", "cpi", "yield10"]]
    df["eps_ttm"] = pd.to_numeric(df["eps_ttm"], errors="coerce")
    return df.dropna(subset=["spx", "eps_ttm", "cpi", "yield10"])


def fetch_fedfunds() -> pd.Series:
    raw = urllib.request.urlopen(FRED_FEDFUNDS, timeout=30).read().decode()
    df = pd.read_csv(io.StringIO(raw))
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col).sort_index()
    s = pd.to_numeric(df["FEDFUNDS"], errors="coerce").dropna()
    s.name = "fedfunds"
    return s


def build_panel() -> pd.DataFrame:
    sh = fetch_shiller()
    ff = fetch_fedfunds()
    # Align to month-start
    sh.index = sh.index.to_period("M").to_timestamp()
    ff.index = ff.index.to_period("M").to_timestamp()
    df = sh.join(ff, how="left")
    df["cpi_yoy"] = df["cpi"].pct_change(12) * 100
    df["pe"] = df["spx"] / df["eps_ttm"]
    # Forward 12-month change in Fed Funds = realized "delivered" cuts/hikes
    df["ff_fwd12m_chg"] = df["fedfunds"].shift(-12) - df["fedfunds"]
    return df.loc[SAMPLE_START:].copy()


# ─── Model ──────────────────────────────────────────────────────────

def fit_model(df: pd.DataFrame) -> sm.regression.linear_model.RegressionResultsWrapper:
    # Trim implausible P/E (negative earnings, GFC/COVID spikes >50)
    fit_df = df.dropna(subset=["pe", "yield10", "cpi_yoy", "ff_fwd12m_chg"]).copy()
    fit_df = fit_df[(fit_df["pe"] > 5) & (fit_df["pe"] < 50)]
    X = fit_df[["yield10", "cpi_yoy", "ff_fwd12m_chg"]]
    X = sm.add_constant(X)
    y = fit_df["pe"]
    return sm.OLS(y, X).fit()


def predict_pe(model, yield10: float, cpi_yoy: float, ff_chg: float) -> float:
    p = model.params
    return (p["const"] + p["yield10"] * yield10 +
            p["cpi_yoy"] * cpi_yoy + p["ff_fwd12m_chg"] * ff_chg)


# ─── Scenarios ──────────────────────────────────────────────────────

# Calvasina (Bloomberg, ~May 2026):
#   S1: CPI 3.3%, 0 cuts, 10Y 4.5%, AI P/E holds  -> SPX 7929
#   S2: CPI 3.8%, 2 hikes (~+50bp), 10Y 5.0%      -> SPX 7400
CALVASINA = [
    {"name": "S1 (RBC base)",      "cpi": 3.3, "yield10": 4.5, "ff_chg":  0.00, "rbc_target": 7929},
    {"name": "S2 (RBC stagflation)","cpi": 3.8, "yield10": 5.0, "ff_chg": +0.50, "rbc_target": 7400},
]


def build_sensitivity(model, current_eps: float, ff_chg: float = 0.0) -> pd.DataFrame:
    cpi_grid = [2.0, 2.5, 3.0, 3.5, 4.0]
    y10_grid = [3.5, 4.0, 4.5, 5.0, 5.5]
    rows = []
    for cpi in cpi_grid:
        row = {"CPI": cpi}
        for y10 in y10_grid:
            pe = predict_pe(model, y10, cpi, ff_chg)
            row[f"{y10:.1f}"] = round(pe * current_eps, 0)
        rows.append(row)
    return pd.DataFrame(rows)


# ─── Output ─────────────────────────────────────────────────────────

def send_discord(message: str, image: bytes | None = None, filename: str = "chart.png"):
    try:
        if image:
            files = {"file": (filename, image, "image/png")}
            data = {"content": message[:1950]}
            requests.post(DISCORD_WEBHOOK_URL, data=data, files=files, timeout=30).raise_for_status()
        else:
            for chunk in [message[i:i+1950] for i in range(0, len(message), 1950)]:
                requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=30).raise_for_status()
    except Exception as e:
        print(f"Discord send failed: {e}", file=sys.stderr)


def make_heatmap(grid: pd.DataFrame, current_spx: float) -> bytes:
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(9, 5), facecolor="#1a1a2e")
    ax.set_facecolor("#1a1a2e")
    data = grid.drop(columns="CPI").values
    im = ax.imshow(data, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(len(grid.columns) - 1))
    ax.set_xticklabels(grid.columns[1:])
    ax.set_yticks(range(len(grid)))
    ax.set_yticklabels([f"{c:.1f}%" for c in grid["CPI"]])
    ax.set_xlabel("10Y Yield (%)")
    ax.set_ylabel("CPI YoY (%)")
    ax.set_title(f"SPX Fair Value Grid (cuts=0)  |  Current SPX: {current_spx:.0f}")
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            ax.text(j, i, f"{int(data[i,j])}", ha="center", va="center",
                    color="black", fontsize=10, fontweight="bold")
    plt.colorbar(im, ax=ax, label="SPX Fair Value")
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=110, facecolor="#1a1a2e")
    plt.close()
    buf.seek(0)
    return buf.read()


def main():
    print("Fetching macro panel...")
    df = build_panel()
    model = fit_model(df)
    p, t, se = model.params, model.tvalues, model.bse
    r2 = model.rsquared
    n = int(model.nobs)

    valid = df[(df["eps_ttm"] > 0) & (df["yield10"] > 0) & df["cpi_yoy"].notna()]
    latest = valid.iloc[-1]
    eps_arg = float(sys.argv[sys.argv.index("--eps") + 1]) if "--eps" in sys.argv else DEFAULT_FWD_EPS
    current_eps = eps_arg
    current_spx = float(latest["spx"])
    current_pe = current_spx / current_eps
    current_y10 = float(latest["yield10"])
    current_cpi = float(latest["cpi_yoy"])
    asof = latest.name.strftime("%Y-%m")

    # Calvasina scenario check
    scen_lines = []
    for s in CALVASINA:
        pe_fair = predict_pe(model, s["yield10"], s["cpi"], s["ff_chg"])
        spx_fair = pe_fair * current_eps
        delta = spx_fair - s["rbc_target"]
        scen_lines.append(
            f"  {s['name']:<22} CPI={s['cpi']}%  10Y={s['yield10']}%  ffΔ={s['ff_chg']:+.2f}\n"
            f"    -> Model P/E={pe_fair:.1f}  SPX_fair={spx_fair:,.0f}   "
            f"(RBC: {s['rbc_target']:,}  | diff: {delta:+,.0f})"
        )

    grid = build_sensitivity(model, current_eps, ff_chg=0.0)

    msg = (
        f"```\n"
        f"════════════════════════════════════════════════════════\n"
        f"MACRO SPX FAIR-VALUE MODEL  ({datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')})\n"
        f"════════════════════════════════════════════════════════\n"
        f"\n"
        f"Data: Shiller monthly + FRED FEDFUNDS  |  Sample: {SAMPLE_START} -> {asof}  |  N={n}\n"
        f"\n"
        f"REGRESSION: P/E ~ 10Y + CPI_YoY + FedFunds_Fwd12m_Change\n"
        f"  const          {p['const']:+7.3f}   t={t['const']:+5.2f}\n"
        f"  10Y yield      {p['yield10']:+7.3f}   t={t['yield10']:+5.2f}   (P/E pts per 1% yield)\n"
        f"  CPI YoY        {p['cpi_yoy']:+7.3f}   t={t['cpi_yoy']:+5.2f}   (P/E pts per 1% CPI)\n"
        f"  FF fwd12m chg  {p['ff_fwd12m_chg']:+7.3f}   t={t['ff_fwd12m_chg']:+5.2f}   (P/E pts per 1% rate path)\n"
        f"  R^2 = {r2:.3f}\n"
        f"\n"
        f"CURRENT STATE (Shiller asof {asof}, fwd EPS assumption):\n"
        f"  SPX={current_spx:,.0f}  Fwd EPS=${current_eps:.0f}  Implied P/E={current_pe:.1f}\n"
        f"  10Y={current_y10:.2f}%  CPI YoY={current_cpi:.2f}%\n"
        f"\n"
        f"CALVASINA SCENARIO CHECK (RBC, May 2026):\n"
        + "\n".join(scen_lines) + "\n"
        f"\n"
        f"SENSITIVITY GRID (cuts=0, EPS={current_eps:.0f}):\n"
        f"{grid.to_string(index=False)}\n"
        f"```"
    )

    print(msg)
    img = make_heatmap(grid, current_spx)
    send_discord(msg, image=img, filename="spx-fair-value.png")


if __name__ == "__main__":
    main()
