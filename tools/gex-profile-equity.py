"""
GEX Profile Scanner — Equity Edition (per-ticker)

Forked from gex-profile.py (SPX-only). Pulls per-ticker options chain from CBOE
delayed-quotes JSON, computes per-strike Gamma Exposure (GEX) using the standard
dealer-positioning convention (call GEX positive, put GEX negative), and posts a
two-panel Discord chart for each ticker:

  Left panel : nearest expiration
  Right panel: next monthly OpEx (10-45 days out, largest OI)

Plus per-ticker MenthorQ-style named levels (Call Resistance / Put Support /
HVL / GEX 1-5) and a key-strike evolution chart across the next ~10 expiries.

Usage:
    python gex-profile-equity.py AAPL TSLA EXLS G

Formula (Perfiliev):
    GEX_per_strike = gamma * OI * 100 * spot^2 * 0.01
    Puts get a negative sign (dealer-short-put convention)

Data: https://cdn.cboe.com/api/global/delayed_quotes/options/{TICKER}.json
Free, EOD-delayed 15-20 min, no API key. Works for any optionable US equity/ETF.
Thinly-traded names will yield sparse profiles.
"""

import argparse
import io
import re
import sys
import requests
import numpy as np
import pandas as pd
from scipy.stats import norm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1508366696212205660/WvjfoSkPzWNbIhNjL0R5eHFatKPzbCUDOTDqAslSgnPIa0N8-0sGLLaLoFMiSIBxsnjt"

CBOE_URL_TEMPLATE = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

DEFAULT_MIN_OI = 10
THIN_CHAIN_MIN_OI = 1  # fallback when DEFAULT_MIN_OI yields too few strikes
THIN_CHAIN_THRESHOLD = 15  # if <15 strikes survive DEFAULT_MIN_OI, retry at THIN_CHAIN_MIN_OI
SPOT_BAND_PCT = 0.20  # ±20% (wider than SPX ±5% — equity chains are thinner)

# Structural named levels (Call Resistance / Put Support / HVL / GEX 1-5) are computed on
# the near-dated window so far-dated round-strike LEAPS OI can't hijack them (mirrors SPX).
NEAR_TERM_DTE = 45
# GEX 1-5 gross-gamma walls are picked within this band of spot (wider than SPX's 2% —
# equity strikes are spaced further apart relative to price and chains are thinner).
GEX_BAND_PCT = 0.10


def build_symbol_regex(ticker: str) -> re.Pattern:
    """Equity option symbols look like 'AAPL260618C00185000' or 'AAPLW260612C...'."""
    return re.compile(rf"^{re.escape(ticker)}[W]?(\d{{2}})(\d{{2}})(\d{{2}})([CP])(\d{{8}})$")


def send_discord_text(message: str):
    if not message:
        return
    chunks = []
    cur = ""
    for line in message.split("\n"):
        if len(cur) + len(line) + 1 > 1900:
            chunks.append(cur)
            cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        chunks.append(cur)
    for c in chunks:
        try:
            r = requests.post(DISCORD_WEBHOOK_URL, json={"content": c}, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"Discord text send failed: {e}", file=sys.stderr)


def send_discord_image(buf: io.BytesIO, filename: str):
    buf.seek(0)
    try:
        r = requests.post(
            DISCORD_WEBHOOK_URL,
            files={"file": (filename, buf, "image/png")},
            timeout=60,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"Discord image send failed: {e}", file=sys.stderr)


def fetch_yahoo_spot(ticker: str) -> float | None:
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d"
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        return float(closes[-1]) if closes else None
    except Exception:
        return None


def fetch_cboe_chain(ticker: str) -> dict | None:
    try:
        r = requests.get(CBOE_URL_TEMPLATE.format(ticker=ticker), headers=UA, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"CBOE fetch failed for {ticker}: {e}", file=sys.stderr)
        return None


def parse_chain(payload: dict, ticker: str, min_oi: int) -> tuple[float, pd.DataFrame]:
    data = payload["data"]
    spot = data.get("current_price") or data.get("close") or data.get("last") or 0.0
    if not spot or spot <= 0:
        fallback = fetch_yahoo_spot(ticker)
        if fallback:
            spot = fallback
        else:
            raise RuntimeError(f"No spot price available from CBOE or Yahoo for {ticker}")

    symbol_re = build_symbol_regex(ticker)
    rows = []
    for opt in data.get("options", []):
        sym = opt.get("option", "")
        m = symbol_re.match(sym)
        if not m:
            continue
        yy, mm, dd, cp, strike_raw = m.groups()
        try:
            exp = date(2000 + int(yy), int(mm), int(dd))
            strike = int(strike_raw) / 1000.0
        except ValueError:
            continue
        gamma = opt.get("gamma")
        oi = opt.get("open_interest")
        if gamma is None or oi is None:
            continue
        if oi < min_oi or gamma <= 0:
            continue
        iv = opt.get("iv")
        rows.append({
            "expiry": exp,
            "strike": strike,
            "type": cp,
            "oi": float(oi),
            "gamma": float(gamma),
            "iv": float(iv) if iv is not None else float("nan"),
        })
    df = pd.DataFrame(rows)
    return float(spot), df


def compute_gex(df: pd.DataFrame, spot: float) -> pd.DataFrame:
    df = df.copy()
    df["gex"] = df["gamma"] * df["oi"] * 100.0 * (spot ** 2) * 0.01
    df.loc[df["type"] == "P", "gex"] *= -1.0
    return df


def _easter(year: int) -> date:
    """Easter Sunday (Anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    mm = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * mm + 114) // 31
    day = ((h + l - 7 * mm + 114) % 31) + 1
    return date(year, month, day)


def _third_friday(year: int, month: int) -> date:
    """3rd Friday of the month — the standard US monthly options expiration."""
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def _is_market_holiday(d: date) -> bool:
    """NYSE full-day closures that can fall on a 3rd Friday: Good Friday and
    Juneteenth (observed). Other NYSE holidays never land on a mid-month Friday."""
    if d == _easter(d.year) - timedelta(days=2):          # Good Friday
        return True
    if d.year >= 2022:                                     # Juneteenth (observed)
        j = date(d.year, 6, 19)
        wd = j.weekday()
        obs = j - timedelta(days=1) if wd == 5 else j + timedelta(days=1) if wd == 6 else j
        if d == obs:
            return True
    return False


def _next_monthly_opex(today: date) -> date:
    """Soonest standard monthly OpEx (3rd Friday, holiday-adjusted) that is >= today.
    When the 3rd Friday is an exchange closure (e.g. Juneteenth, Good Friday) the
    AM-settled monthly rolls back to the Thursday before."""
    y, m = today.year, today.month
    for _ in range(13):
        fri = _third_friday(y, m)
        opex = fri - timedelta(days=1) if _is_market_holiday(fri) else fri
        if opex >= today:
            return opex
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return _third_friday(today.year, today.month)  # unreachable in practice


def pick_expiries(df: pd.DataFrame, today: date) -> tuple[date | None, date | None]:
    expiries = sorted(df["expiry"].unique())
    if not expiries:
        return None, None
    future = [e for e in expiries if e >= today]
    nearest = future[0] if future else None

    monthly = _next_monthly_opex(today)
    if nearest is not None and monthly == nearest:
        # Front expiry is itself the monthly — advance to next month's OpEx so
        # the two panels stay distinct.
        monthly = _next_monthly_opex(nearest + timedelta(days=1))

    if monthly in expiries:
        opex = monthly
    else:
        window_lo = today + timedelta(days=10)
        window_hi = today + timedelta(days=45)
        candidates = [e for e in expiries if window_lo <= e <= window_hi]
        if candidates:
            oi_by_exp = df[df["expiry"].isin(candidates)].groupby("expiry")["oi"].sum()
            opex = oi_by_exp.idxmax()
        else:
            later = [e for e in expiries if e >= window_lo]
            opex = later[0] if later else (expiries[-1] if expiries else None)

    if nearest == opex:
        later = [e for e in expiries if e > nearest] if nearest else []
        opex = later[0] if later else opex

    return nearest, opex


def aggregate_strikes(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    calls = df[df["type"] == "C"].groupby("strike")["gex"].sum()
    puts = df[df["type"] == "P"].groupby("strike")["gex"].sum()
    return calls.sort_index(), puts.sort_index()


def compute_named_levels(df: pd.DataFrame, near_df: pd.DataFrame, spot: float) -> dict:
    """Level taxonomy (definitions):
      GEX 1          heaviest flow-driven target — largest GROSS gamma wall near spot
      HVL            gamma flip (BS re-priced) — where MMs flip long/short, vol equilibrium
      Call Resistance heaviest call gamma AT/ABOVE spot (premium sold -> ceiling/slowdown)
      Put Support    heaviest put gamma AT/BELOW spot (premium bought -> support shelf)
    """
    def _levels(sub: pd.DataFrame) -> dict:
        calls = sub[sub["type"] == "C"].groupby("strike")["gex"].sum()
        puts = sub[sub["type"] == "P"].groupby("strike")["gex"].sum()
        all_s = sorted(set(calls.index) | set(puts.index))
        net = pd.Series(
            {k: float(calls.get(k, 0.0)) + float(puts.get(k, 0.0)) for k in all_s}
        ).sort_index()
        # Gross gamma per strike: |call_gex| + |put_gex| — the true magnitude of gamma at
        # the strike. Net cancellation hides the dominant wall, so GEX 1-5 rank by gross.
        gross = pd.Series(
            {k: abs(float(calls.get(k, 0.0))) + abs(float(puts.get(k, 0.0))) for k in all_s}
        ).sort_index()
        zgl, _ = gamma_flip_bs(sub, spot)
        # Call Resistance is a CEILING (>= spot); Put Support is a FLOOR (<= spot).
        calls_res = calls[calls.index >= spot]
        puts_sup = puts[puts.index <= spot]
        has_cr = not calls_res.empty and calls_res.max() > 0
        has_ps = not puts_sup.empty and puts_sup.min() < 0
        return {
            "call_wall": float(calls_res.idxmax()) if has_cr else None,
            "call_wall_v": float(calls_res.max()) if has_cr else 0.0,
            "put_wall": float(puts_sup.idxmin()) if has_ps else None,
            "put_wall_v": float(abs(puts_sup.min())) if has_ps else 0.0,
            "zgl": zgl,
            "net": net,
            "gross": gross,
        }

    full = _levels(df)
    zerod = _levels(near_df) if not near_df.empty else None
    # GEX 1-5: largest gross-gamma walls within spot +/- GEX_BAND_PCT (fallback to full).
    band = full["gross"][(full["gross"].index >= spot * (1 - GEX_BAND_PCT)) &
                         (full["gross"].index <= spot * (1 + GEX_BAND_PCT))]
    if band.empty:
        band = full["gross"]
    top5_idx = band.sort_values(ascending=False).head(5).index
    top5 = [(float(k), float(full["net"].loc[k]), float(full["gross"].loc[k])) for k in top5_idx]
    return {"full": full, "zerod": zerod, "gex_top5": top5}


def compute_expected_move(df: pd.DataFrame, spot: float, nearest: date) -> tuple[float, float, float] | None:
    """1-day expected move from ATM IV of the nearest expiry (1D Max / 1D Min).
    move = spot * atm_iv * sqrt(1/252). Returns (hi, lo, atm_iv) or None."""
    if "iv" not in df.columns:
        return None
    sub = df[df["expiry"] == nearest].dropna(subset=["iv"])
    sub = sub[sub["iv"] > 0]
    if sub.empty:
        return None
    atm_strike = sub.loc[(sub["strike"] - spot).abs().idxmin(), "strike"]
    atm_iv = float(sub[sub["strike"] == atm_strike]["iv"].mean())
    if not (atm_iv > 0):
        return None
    move = spot * atm_iv * np.sqrt(1.0 / 252.0)
    return (spot + move, spot - move, atm_iv)


def clip_strike_range(calls: pd.Series, puts: pd.Series, spot: float):
    """Clip to strikes with meaningful |GEX| (>= 1% of max) plus a wide spot band."""
    strikes = sorted(set(calls.index) | set(puts.index))
    if not strikes:
        return calls, puts
    combined_abs = pd.Series(
        {s: abs(calls.get(s, 0)) + abs(puts.get(s, 0)) for s in strikes}
    )
    max_abs = combined_abs.max()
    if max_abs <= 0:
        return calls, puts
    keep = combined_abs[combined_abs >= 0.01 * max_abs].index
    band_lo = spot * (1 - SPOT_BAND_PCT)
    band_hi = spot * (1 + SPOT_BAND_PCT)
    keep = sorted(set(list(keep)) | {s for s in strikes if band_lo <= s <= band_hi})
    return calls.reindex(keep).fillna(0), puts.reindex(keep).fillna(0)


def fmt_gex(v: float) -> str:
    if abs(v) >= 1e9:
        return f"{v/1e9:+.2f}B"
    if abs(v) >= 1e6:
        return f"{v/1e6:+.1f}M"
    if abs(v) >= 1e3:
        return f"{v/1e3:+.1f}K"
    return f"{v:+.0f}"


def fmt_axis(v: float, _pos=None) -> str:
    if v == 0:
        return "0"
    if abs(v) >= 1e9:
        return f"{v/1e9:.0f}B"
    if abs(v) >= 1e6:
        return f"{v/1e6:.0f}M"
    if abs(v) >= 1e3:
        return f"{v/1e3:.0f}K"
    return f"{v:.0f}"


def fmt_strike(k: float) -> str:
    """Equity strikes can be $1-$5000+ — pick precision dynamically."""
    if k >= 100:
        return f"{k:,.0f}"
    return f"{k:,.2f}"


def gamma_walls(calls: pd.Series, puts: pd.Series, n: int = 3) -> tuple[list, list]:
    top_calls = calls.sort_values(ascending=False).head(n)
    top_puts = puts.sort_values(ascending=True).head(n)
    call_walls = [(float(k), float(v)) for k, v in top_calls.items() if v > 0]
    put_walls = [(float(k), float(v)) for k, v in top_puts.items() if v < 0]
    return call_walls, put_walls


def render_panel(ax, calls: pd.Series, puts: pd.Series, spot: float, title: str, zgl: float | None = None):
    strikes = sorted(set(calls.index) | set(puts.index))
    cv = np.array([calls.get(s, 0) for s in strikes])
    pv = np.array([puts.get(s, 0) for s in strikes])

    width = max((strikes[-1] - strikes[0]) / max(len(strikes), 1) * 0.85, 0.5) if len(strikes) > 1 else 1.0

    ax.bar(strikes, cv, width=width, color="#a8e6a8", label="Call GEX")
    ax.bar(strikes, pv, width=width, color="#e6a8d3", label="Put GEX")
    ax.axvline(spot, color="#00d9ff", lw=2, label="Spot Price")
    if zgl is not None and not np.isnan(zgl):
        ax.axvline(zgl, color="#f0e833", lw=1.5, ls="--", label=f"HVL {fmt_strike(zgl)}")
    ax.axhline(0, color="#888888", lw=0.5)

    ax.set_title(title, color="white", fontsize=13)
    ax.set_xlabel("Strike Price", color="white")
    ax.set_ylabel("Gamma Exposure", color="white")
    ax.set_facecolor("#1a1a2e")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#444444")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(fmt_axis))
    ax.grid(axis="y", alpha=0.15, color="white")


def add_dte(df: pd.DataFrame, today: date) -> pd.DataFrame:
    """Add business-days-to-expiry in years (T). 0DTE floored at 1/262 so it isn't
    excluded by the Black-Scholes gamma (Perfiliev convention)."""
    df = df.copy()
    bd = np.array([np.busday_count(today, e) for e in df["expiry"]], dtype=float)
    bd[bd <= 0] = 1.0
    df["T"] = bd / 262.0
    return df


def _bs_gamma(S: float, K, iv, T):
    """Black-Scholes gamma (identical for calls and puts), r = q = 0.
    Vectorized over arrays K, iv, T at a single scalar spot S."""
    K = np.asarray(K, dtype=float)
    iv = np.asarray(iv, dtype=float)
    T = np.asarray(T, dtype=float)
    out = np.zeros_like(K)
    ok = (iv > 0) & (T > 0) & (S > 0) & (K > 0)
    if not ok.any():
        return out
    d1 = (np.log(S / K[ok]) + 0.5 * iv[ok] ** 2 * T[ok]) / (iv[ok] * np.sqrt(T[ok]))
    out[ok] = norm.pdf(d1) / (S * iv[ok] * np.sqrt(T[ok]))
    return out


def gamma_flip_bs(sub: pd.DataFrame, spot: float, n: int = 60) -> tuple[float, float]:
    """Perfiliev re-priced Gamma Flip (HVL) — re-prices gamma via Black-Scholes at n spot
    levels across [0.8, 1.2]*spot, sums the signed dealer profile (call gamma - put gamma),
    and returns the zero-crossing nearest spot. Far more accurate than accumulating static
    snapshot gamma across strikes. `sub` needs columns: strike, type, iv, T, oi.
    Returns (flip_strike | nan, peak_|profile| as magnitude in $)."""
    if sub is None or sub.empty or "iv" not in sub.columns or "T" not in sub.columns:
        return (float("nan"), 0.0)
    c = sub[sub["type"] == "C"].dropna(subset=["iv", "T"])
    p = sub[sub["type"] == "P"].dropna(subset=["iv", "T"])
    c = c[c["iv"] > 0]
    p = p[p["iv"] > 0]
    if c.empty or p.empty:
        return (float("nan"), 0.0)
    ck, civ, cT, coi = (c[x].to_numpy() for x in ("strike", "iv", "T", "oi"))
    pk, piv, pT, poi = (p[x].to_numpy() for x in ("strike", "iv", "T", "oi"))

    levels = np.linspace(0.8 * spot, 1.2 * spot, n)
    prof = np.empty(n)
    for i, S in enumerate(levels):
        cgex = (coi * 100.0 * S * S * 0.01 * _bs_gamma(S, ck, civ, cT)).sum()
        pgex = (poi * 100.0 * S * S * 0.01 * _bs_gamma(S, pk, piv, pT)).sum()
        prof[i] = cgex - pgex
    mag = float(np.abs(prof).max())
    if mag <= 0:
        return (float("nan"), 0.0)

    idx = np.where(np.diff(np.sign(prof)))[0]
    if len(idx) == 0:
        return (float("nan"), mag)
    # Reject spurious near-zero edge crossings (short-dated gamma underflows far from spot),
    # then pick the crossing nearest spot (the real short->long dealer transition).
    thresh = 0.02 * mag
    cands = [j for j in idx if max(abs(prof[j]), abs(prof[j + 1])) >= thresh] or list(idx)
    best = None
    for j in cands:
        neg, pos = prof[j], prof[j + 1]
        if pos == neg:
            continue
        ks, kp = levels[j], levels[j + 1]
        f = kp - (kp - ks) * pos / (pos - neg)
        if best is None or abs(f - spot) < abs(best - spot):
            best = f
    return (float(best), mag) if best is not None else (float("nan"), mag)


def per_expiry_key_strikes(df: pd.DataFrame, expiries: list[date], spot: float) -> pd.DataFrame:
    rows = []
    for exp in expiries:
        sub = df[df["expiry"] == exp]
        if sub.empty:
            continue
        calls = sub[sub["type"] == "C"].groupby("strike")["gex"].sum()
        puts = sub[sub["type"] == "P"].groupby("strike")["gex"].sum()

        max_call = (float(calls.idxmax()), float(calls.max())) if not calls.empty and calls.max() > 0 else (np.nan, 0.0)
        max_put = (float(puts.idxmin()), float(abs(puts.min()))) if not puts.empty and puts.min() < 0 else (np.nan, 0.0)
        zgl_strike, zgl_mag = gamma_flip_bs(sub, spot)

        rows.append({
            "expiry": exp,
            "call_strike": max_call[0], "call_mag": max_call[1],
            "put_strike": max_put[0],   "put_mag": max_put[1],
            "net_strike": zgl_strike,   "net_mag": zgl_mag,
        })
    return pd.DataFrame(rows)


def render_evolution(key: pd.DataFrame, spot: float, ticker: str) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(14, 7), facecolor="#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    x = pd.to_datetime(key["expiry"])
    all_mags = pd.concat([key["call_mag"], key["put_mag"], key["net_mag"]])
    mmax = float(all_mags.max()) if len(all_mags) and all_mags.max() > 0 else 1.0

    def bsize(s: pd.Series) -> np.ndarray:
        return 80 + 1700 * (s.values / mmax)

    ax.plot(x, key["call_strike"], color="#7ed87e", lw=2, marker="", label="Max Call GEX Strike", zorder=2)
    ax.scatter(x, key["call_strike"], s=bsize(key["call_mag"]), color="#7ed87e", alpha=0.55, edgecolors="#7ed87e", zorder=3)

    ax.plot(x, key["put_strike"], color="#e6a8d3", lw=2, marker="", label="Max Put GEX Strike (magnitude)", zorder=2)
    ax.scatter(x, key["put_strike"], s=bsize(key["put_mag"]), color="#e6a8d3", alpha=0.55, edgecolors="#e6a8d3", zorder=3)

    ax.plot(x, key["net_strike"], color="#f0e833", lw=2, marker="", label="Zero-Gamma Flip (ZGL)", zorder=2)
    ax.scatter(x, key["net_strike"], s=bsize(key["net_mag"]), color="#f0e833", alpha=0.55, edgecolors="#f0e833", zorder=3)

    for _, r in key.iterrows():
        xd = pd.Timestamp(r["expiry"])
        if not np.isnan(r["call_strike"]):
            ax.annotate(fmt_strike(r["call_strike"]), (xd, r["call_strike"]),
                        xytext=(0, 12), textcoords="offset points", ha="center", color="white", fontsize=8)
        if not np.isnan(r["put_strike"]):
            ax.annotate(fmt_strike(r["put_strike"]), (xd, r["put_strike"]),
                        xytext=(0, -16), textcoords="offset points", ha="center", color="white", fontsize=8)
        if not np.isnan(r["net_strike"]):
            ax.annotate(fmt_strike(r["net_strike"]), (xd, r["net_strike"]),
                        xytext=(0, 12), textcoords="offset points", ha="center", color="white", fontsize=8)

    ax.axhline(spot, color="#00d9ff", lw=1.2, ls="--", alpha=0.8)
    ax.text(x.iloc[-1], spot, f"  Spot {fmt_strike(spot)}", color="#00d9ff", va="center", fontsize=9)

    ax.set_title(f"{ticker} — Key Strike Evolution with GEX Magnitude Bubbles\nNext {len(key)} Expiries",
                 color="white", fontsize=13)
    ax.set_xlabel("Expiry", color="white")
    ax.set_ylabel("Strike Price", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#444444")
    ax.grid(True, alpha=0.2, color="white")
    ax.legend(loc="upper left", facecolor="#0d0d1f", edgecolor="#444444", labelcolor="white")
    fig.autofmt_xdate()
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor="#1a1a2e")
    plt.close(fig)
    return buf


def render_levels_map(ticker: str, spot: float, levels: dict, em: tuple | None,
                      today: date, nearest: date) -> io.BytesIO:
    """MenthorQ-style level map: horizontal lines on a price axis with labels —
    Call Resistance / GEX 1-5 / HVL / Put Support, nearest-expiry variants, 1D Max/Min, spot."""
    full = levels["full"]
    zerod = levels["zerod"]
    near_tag = "0DTE" if nearest == today else "Near"

    RED, GREEN, YEL, CYAN, ORANGE = "#e06666", "#5fd35f", "#f0e833", "#4dd0e1", "#ff9933"
    L = []

    def add(price, label, color, ls="-", lw=1.5, weight="normal"):
        if price is None:
            return
        try:
            if np.isnan(price):
                return
        except TypeError:
            pass
        L.append({"p": float(price), "label": label, "color": color,
                  "ls": ls, "lw": lw, "w": weight})

    add(full.get("call_wall"), "Call Resistance", RED, lw=2.2)
    add(full.get("put_wall"), "Put Support", GREEN, lw=2.2)
    add(full.get("zgl"), "HVL (Zero Gamma)", YEL, ls="--")
    if zerod:
        add(zerod.get("call_wall"), f"Call Resistance {near_tag} / Gamma Wall", RED)
        add(zerod.get("put_wall"), f"Put Support {near_tag}", GREEN)
        add(zerod.get("zgl"), f"HVL {near_tag}", YEL, ls=":")
    for i, (k, net_v, gross_v) in enumerate(levels["gex_top5"], 1):
        if i == 1:
            add(k, f"GEX {i} (primary)", YEL, ls="--", lw=2.2, weight="bold")
        else:
            add(k, f"GEX {i}", CYAN, lw=1.3)
    if em:
        add(em[0], "1D Max", ORANGE)
        add(em[1], "1D Min", ORANGE)
    add(spot, "SPOT", CYAN, ls=":", lw=2.0, weight="bold")

    fig, ax = plt.subplots(figsize=(11, 9), facecolor="#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    prices = [x["p"] for x in L]
    ymin, ymax = min(prices), max(prices)
    pad = max((ymax - ymin) * 0.05, spot * 0.005)
    ax.set_ylim(ymin - pad, ymax + pad)
    ax.set_xlim(0, 1)

    for x in L:
        ax.axhline(x["p"], color=x["color"], ls=x["ls"], lw=x["lw"], alpha=0.85, zorder=1)

    mingap = (ymax - ymin + 2 * pad) * 0.028
    order = sorted(L, key=lambda z: z["p"])
    last_y = -1e18
    for x in order:
        ty = x["p"]
        if ty - last_y < mingap:
            ty = last_y + mingap
        last_y = ty
        ax.text(0.015, ty, f"{x['label']}  {fmt_strike(x['p'])}",
                transform=ax.get_yaxis_transform(), color=x["color"],
                fontsize=9.5, va="center", ha="left", weight=x["w"], zorder=4,
                bbox=dict(boxstyle="round,pad=0.15", fc="#0d0d1f", ec="none", alpha=0.65))

    ax.set_title(f"{ticker} GEX LEVEL MAP  —  Spot {fmt_strike(spot)}   {today.isoformat()}",
                 color="white", fontsize=13)
    ax.set_ylabel("Price", color="white")
    ax.get_xaxis().set_visible(False)
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#444444")
    ax.grid(axis="y", alpha=0.12, color="white")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor="#1a1a2e")
    plt.close(fig)
    return buf


def build_text_report(
    ticker: str,
    spot: float,
    today: date,
    nearest: date,
    opex: date | None,
    near_calls: pd.Series, near_puts: pd.Series,
    opex_calls: pd.Series | None, opex_puts: pd.Series | None,
) -> str:
    near_net = float(near_calls.sum() + near_puts.sum())
    near_call_walls, near_put_walls = gamma_walls(near_calls, near_puts)

    lines = []
    lines.append("```")
    lines.append("=" * 56)
    lines.append(f"{ticker} GEX PROFILE  —  Spot {fmt_strike(spot)}   {today.isoformat()}")
    lines.append("=" * 56)
    lines.append("")
    lines.append(f"NEAREST EXPIRY ({nearest.isoformat()})  Net GEX: {fmt_gex(near_net)}")
    lines.append("-" * 56)
    lines.append("  Call Walls (resistance):")
    for k, v in near_call_walls:
        lines.append(f"    {fmt_strike(k):>10}   {fmt_gex(v):>10}")
    lines.append("  Put Walls (support):")
    for k, v in near_put_walls:
        lines.append(f"    {fmt_strike(k):>10}   {fmt_gex(v):>10}")
    lines.append("")

    if opex is not None and opex_calls is not None and opex_puts is not None:
        opex_net = float(opex_calls.sum() + opex_puts.sum())
        opex_call_walls, opex_put_walls = gamma_walls(opex_calls, opex_puts)
        lines.append(f"NEXT OPEX ({opex.isoformat()})  Net GEX: {fmt_gex(opex_net)}")
        lines.append("-" * 56)
        lines.append("  Call Walls (resistance):")
        for k, v in opex_call_walls:
            lines.append(f"    {fmt_strike(k):>10}   {fmt_gex(v):>10}")
        lines.append("  Put Walls (support):")
        for k, v in opex_put_walls:
            lines.append(f"    {fmt_strike(k):>10}   {fmt_gex(v):>10}")
    lines.append("```")
    return "\n".join(lines)


def build_levels_report(ticker: str, spot: float, levels: dict, today: date,
                        nearest: date, em: tuple | None = None) -> str:
    full = levels["full"]
    zerod = levels["zerod"]
    lines = ["```"]
    lines.append("=" * 56)
    lines.append(f"{ticker} KEY GEX LEVELS  —  Spot {fmt_strike(spot)}   {today.isoformat()}")
    lines.append("=" * 56)
    lines.append("")
    if em:
        lines.append(f"1D EXPECTED MOVE (ATM IV {em[2]*100:.1f}%):")
        lines.append(f"  1D Max               : {fmt_strike(em[0]):>10}")
        lines.append(f"  1D Min               : {fmt_strike(em[1]):>10}")
        lines.append("")
    lines.append(f"NEAR-TERM (<= {NEAR_TERM_DTE} DTE):")
    if full["call_wall"] is not None:
        lines.append(f"  Call Resistance      : {fmt_strike(full['call_wall']):>10}   ({fmt_gex(full['call_wall_v'])})")
    if full["put_wall"] is not None:
        lines.append(f"  Put Support          : {fmt_strike(full['put_wall']):>10}   ({fmt_gex(-full['put_wall_v'])})")
    if full["zgl"] is not None and not np.isnan(full["zgl"]):
        lines.append(f"  HVL (Zero Gamma)     : {fmt_strike(full['zgl']):>10}")
    lines.append("")
    # Only show "nearest expiry" levels — equities don't have daily expiries like SPX
    if zerod is not None and nearest == today:
        lines.append(f"0DTE ONLY (expiring {today.isoformat()}):")
        if zerod["call_wall"] is not None:
            lines.append(f"  Call Resistance 0DTE : {fmt_strike(zerod['call_wall']):>10}   (Gamma Wall 0DTE)")
        if zerod["put_wall"] is not None:
            lines.append(f"  Put Support 0DTE     : {fmt_strike(zerod['put_wall']):>10}")
        if zerod["zgl"] is not None and not np.isnan(zerod["zgl"]):
            lines.append(f"  HVL 0DTE             : {fmt_strike(zerod['zgl']):>10}")
        lines.append("")
    elif zerod is not None:
        lines.append(f"NEAREST EXPIRY ONLY ({nearest.isoformat()}):")
        if zerod["call_wall"] is not None:
            lines.append(f"  Call Resistance      : {fmt_strike(zerod['call_wall']):>10}")
        if zerod["put_wall"] is not None:
            lines.append(f"  Put Support          : {fmt_strike(zerod['put_wall']):>10}")
        if zerod["zgl"] is not None and not np.isnan(zerod["zgl"]):
            lines.append(f"  HVL                  : {fmt_strike(zerod['zgl']):>10}")
        lines.append("")
    lines.append("GEX 1-5 (top gamma walls near spot, by gross):")
    for i, (k, net_v, gross_v) in enumerate(levels["gex_top5"], 1):
        side = "CALL+" if net_v > 0 else "PUT- "
        lines.append(f"  GEX {i}: {fmt_strike(k):>10}   {side} {fmt_gex(gross_v)}")
    lines.append("")
    lines.append("REGIME (spot vs HVL):")
    if full["zgl"] is not None and not np.isnan(full["zgl"]):
        d = spot - full["zgl"]
        reg = "LONG GAMMA (pin/dampen)" if d >= 0 else "SHORT GAMMA (vol expansion)"
        lines.append(f"  Near-term  : {d:+7.2f}   {reg}")
    if zerod is not None and zerod["zgl"] is not None and not np.isnan(zerod["zgl"]):
        d = spot - zerod["zgl"]
        reg = "LONG GAMMA (pin/dampen)" if d >= 0 else "SHORT GAMMA (vol expansion)"
        lines.append(f"  Nearest    : {d:+7.2f}   {reg}")
    lines.append("```")
    return "\n".join(lines)


def process_ticker(ticker: str, min_oi: int) -> bool:
    """Returns True on success."""
    now = datetime.now(ET)
    today = now.date()
    print(f"\n[GEX:{ticker}] {now.isoformat()} fetching CBOE chain...")

    payload = fetch_cboe_chain(ticker)
    if payload is None:
        send_discord_text(f"GEX scanner: CBOE fetch failed for {ticker} at {now.isoformat()}")
        return False

    try:
        spot, df = parse_chain(payload, ticker, min_oi=min_oi)
    except Exception as e:
        send_discord_text(f"GEX scanner: parse failed for {ticker} — {e}")
        return False

    # Thin-chain fallback: retry with min_oi=1 if too few strikes survived
    if len(df) < THIN_CHAIN_THRESHOLD and min_oi > THIN_CHAIN_MIN_OI:
        print(f"[GEX:{ticker}] only {len(df)} contracts above OI>={min_oi}, retrying with OI>={THIN_CHAIN_MIN_OI}")
        spot, df = parse_chain(payload, ticker, min_oi=THIN_CHAIN_MIN_OI)

    if df.empty:
        send_discord_text(f"GEX scanner: no parseable contracts for {ticker}")
        return False

    df = compute_gex(df, spot)
    df = add_dte(df, today)  # T (years to expiry) for the Black-Scholes gamma flip
    print(f"[GEX:{ticker}] spot={spot:.2f}  rows={len(df)}  expiries={df['expiry'].nunique()}")

    nearest, opex = pick_expiries(df, today)
    if nearest is None:
        send_discord_text(f"GEX scanner: no future expiries for {ticker} (today={today})")
        return False
    print(f"[GEX:{ticker}] nearest={nearest}  opex={opex}")

    near_df = df[df["expiry"] == nearest]
    near_calls, near_puts = aggregate_strikes(near_df)
    near_calls, near_puts = clip_strike_range(near_calls, near_puts, spot)
    near_zgl, _ = gamma_flip_bs(near_df, spot)

    if opex is not None and opex != nearest:
        opex_df = df[df["expiry"] == opex]
        opex_calls, opex_puts = aggregate_strikes(opex_df)
        opex_calls, opex_puts = clip_strike_range(opex_calls, opex_puts, spot)
        opex_zgl, _ = gamma_flip_bs(opex_df, spot)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 5), facecolor="#1a1a2e")
        render_panel(ax1, near_calls, near_puts, spot, f"{ticker} {nearest.isoformat()}", zgl=near_zgl)
        render_panel(ax2, opex_calls, opex_puts, spot, f"{ticker} OpEx ({opex.isoformat()})", zgl=opex_zgl)
        ax1.legend(loc="upper right", facecolor="#1a1a2e", edgecolor="#444444", labelcolor="white", fontsize=8)
        ax2.legend(loc="upper right", facecolor="#1a1a2e", edgecolor="#444444", labelcolor="white", fontsize=8)
    else:
        opex_calls = opex_puts = None
        fig, ax1 = plt.subplots(1, 1, figsize=(10, 5), facecolor="#1a1a2e")
        render_panel(ax1, near_calls, near_puts, spot, f"{ticker} {nearest.isoformat()}", zgl=near_zgl)
        ax1.legend(loc="upper right", facecolor="#1a1a2e", edgecolor="#444444", labelcolor="white")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor="#1a1a2e")
    plt.close(fig)

    report = build_text_report(ticker, spot, today, nearest, opex, near_calls, near_puts, opex_calls, opex_puts)
    send_discord_text(report)
    send_discord_image(buf, f"{ticker}_gex_{today.isoformat()}.png")

    near_term_df = df[df["expiry"] <= today + timedelta(days=NEAR_TERM_DTE)]
    if near_term_df.empty:
        near_term_df = df
    levels = compute_named_levels(near_term_df, near_df, spot)
    em = compute_expected_move(df, spot, nearest)
    send_discord_text(build_levels_report(ticker, spot, levels, today, nearest, em))

    map_buf = render_levels_map(ticker, spot, levels, em, today, nearest)
    send_discord_image(map_buf, f"{ticker}_gex_map_{today.isoformat()}.png")

    all_expiries = sorted(df["expiry"].unique())
    future_expiries = [e for e in all_expiries if e >= today][:11]
    if len(future_expiries) >= 2:
        key = per_expiry_key_strikes(df, future_expiries, spot)
        if not key.empty:
            evo_buf = render_evolution(key, spot, ticker)
            send_discord_image(evo_buf, f"{ticker}_gex_evolution_{today.isoformat()}.png")
            print(f"[GEX:{ticker}] evolution chart sent ({len(key)} expiries)")
    else:
        print(f"[GEX:{ticker}] only {len(future_expiries)} future expiries — skipping evolution chart")

    print(f"[GEX:{ticker}] done")
    return True


def main():
    parser = argparse.ArgumentParser(description="Per-ticker GEX profile scanner (CBOE delayed quotes)")
    parser.add_argument("tickers", nargs="+", help="One or more equity/ETF tickers (e.g. AAPL TSLA EXLS)")
    parser.add_argument("--min-oi", type=int, default=DEFAULT_MIN_OI,
                        help=f"Minimum open interest per contract (default {DEFAULT_MIN_OI}; auto-relaxes to {THIN_CHAIN_MIN_OI} for thin chains)")
    args = parser.parse_args()

    tickers = [t.upper().lstrip("$").strip() for t in args.tickers if t.strip()]
    print(f"Processing {len(tickers)} ticker(s): {', '.join(tickers)}")

    ok = 0
    for t in tickers:
        try:
            if process_ticker(t, min_oi=args.min_oi):
                ok += 1
        except Exception as e:
            print(f"[GEX:{t}] FAILED — {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            send_discord_text(f"GEX scanner: {t} failed — {e}")

    print(f"\nDone. {ok}/{len(tickers)} ticker(s) processed.")


if __name__ == "__main__":
    main()
