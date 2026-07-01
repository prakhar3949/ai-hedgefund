"""
GEX Profile Scanner (Perfiliev method)

Pulls SPX options chain from CBOE delayed-quotes JSON, computes per-strike
Gamma Exposure (GEX) using the standard dealer-positioning convention
(call GEX positive, put GEX negative), and posts a two-panel Discord chart:

  Left panel : nearest expiration (today / next trading day)
  Right panel: next monthly OpEx (10-45 days out, largest OI)

Also reports the top 3 call walls + top 3 put walls by |GEX| for each panel.

Formula (Perfiliev):
    GEX_per_strike = gamma * OI * 100 * spot^2 * 0.01
    Puts get a negative sign (dealer-short-put convention)

Data: https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json
Free, EOD-delayed 15-20 min, no API key.
"""

import io
import json
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

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1507392186222776422/HaApw51ljzILxhNqne8P5u_u5YwbSA5aF3qjQ1ieTtZatbx1MrooeLVzfOKg3OWtyNRr"

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Structural named levels (Call Resistance / Put Support / HVL / GEX 1-5) are computed on
# the near-dated window only. The full chain lets far-OTM round-strike LEAPS OI (e.g. 7000
# puts) hijack the put-support level; restricting to <=45 DTE reproduces MenthorQ's levels.
NEAR_TERM_DTE = 45

# SPX option symbol: e.g. "SPXW260613C07450000" or "SPX260618P07000000"
SYMBOL_RE = re.compile(r"^SPX[W]?(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")

# Persisted top-3 put-GEX watch dates from the previous run (for day-over-day diffing)
PUT_WATCH_FILE = TOOLS_DIR / "gex-put-watch.json"


def send_discord_text(message: str):
    if not message:
        return
    # Chunk under 2000 chars at line boundaries
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


def fetch_yahoo_spx_spot() -> float | None:
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=5d&interval=1d"
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        return float(closes[-1]) if closes else None
    except Exception:
        return None


def fetch_cboe_chain() -> dict | None:
    try:
        r = requests.get(CBOE_URL, headers=UA, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"CBOE fetch failed: {e}", file=sys.stderr)
        return None


def parse_chain(payload: dict) -> tuple[float, pd.DataFrame]:
    data = payload["data"]
    spot = data.get("current_price") or data.get("close") or data.get("last") or 0.0
    if not spot or spot <= 0:
        fallback = fetch_yahoo_spx_spot()
        if fallback:
            spot = fallback
        else:
            raise RuntimeError("No spot price available from CBOE or Yahoo")

    rows = []
    for opt in data.get("options", []):
        sym = opt.get("option", "")
        m = SYMBOL_RE.match(sym)
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
        if oi < 10 or gamma <= 0:
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
    """Return (nearest_expiry, opex_expiry).

    nearest_expiry: smallest expiry >= today, else None
    opex_expiry: the next standard monthly OpEx (3rd Friday, holiday-adjusted),
                 computed directly so an imminent monthly (<10 days out) is not
                 skipped. Falls back to the highest-OI expiry in the today+10..+45
                 window only when the computed monthly isn't listed in the chain.
    """
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
    """MenthorQ-style level taxonomy from the GEX chain.

    Near-term: Call Resistance, Put Support, HVL (Zero Gamma).
    0DTE-only: Call Resistance 0DTE / Gamma Wall 0DTE, Put Support 0DTE, HVL 0DTE.
    GEX 1-5:   Top 5 gross-gamma walls within spot +/-2%.
    """
    def _levels(sub: pd.DataFrame) -> dict:
        calls = sub[sub["type"] == "C"].groupby("strike")["gex"].sum()
        puts = sub[sub["type"] == "P"].groupby("strike")["gex"].sum()
        all_s = sorted(set(calls.index) | set(puts.index))
        net = pd.Series(
            {k: float(calls.get(k, 0.0)) + float(puts.get(k, 0.0)) for k in all_s}
        ).sort_index()
        # Gross gamma per strike: |call_gex| + |put_gex|. This is the true magnitude of
        # gamma sitting at the strike. Net (call - put) cancellation hides the dominant
        # wall — e.g. 7600 has +11.8B call / -7.8B put = only +4B net but ~19.4B gross,
        # which is why MenthorQ flags 7600 as the primary GEX level, not a net-ranked strike.
        gross = pd.Series(
            {k: abs(float(calls.get(k, 0.0))) + abs(float(puts.get(k, 0.0))) for k in all_s}
        ).sort_index()
        zgl, _ = gamma_flip_bs(sub, spot)
        # Call Resistance is a CEILING (premium sold heaviest -> slowdowns), so it must
        # sit at/above spot; Put Support is a FLOOR (premium bought heaviest -> support
        # shelf), so it must sit at/below spot. Without the side constraint the heaviest
        # call/put gamma can land on the wrong side of spot and mislabel a level (e.g.
        # "Put Support" printing above spot, which is not a support shelf at all).
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
    # GEX 1-5: largest gross gamma walls near spot (spot +/-2%). Ranking by gross (not net)
    # so the dominant wall surfaces as GEX 1; band keeps far round-strike OI (e.g. 7000) out.
    band = full["gross"][(full["gross"].index >= spot * 0.98) & (full["gross"].index <= spot * 1.02)]
    if band.empty:
        band = full["gross"]
    top5_idx = band.sort_values(ascending=False).head(5).index
    top5 = [(float(k), float(full["net"].loc[k]), float(full["gross"].loc[k])) for k in top5_idx]
    return {"full": full, "zerod": zerod, "gex_top5": top5}


def compute_expected_move(df: pd.DataFrame, spot: float, nearest: date) -> tuple[float, float, float] | None:
    """1-day expected move from ATM IV of the nearest expiry (MenthorQ 1D Max / 1D Min).

    move = spot * atm_iv * sqrt(1/252).  Returns (hi, lo, atm_iv) or None if no IV data.
    """
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
    """Clip to strikes with meaningful |GEX| (>= 1% of max) plus a spot band."""
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
    # Always include a ±5% spot band
    band_lo = spot * 0.95
    band_hi = spot * 1.05
    keep = sorted(set(list(keep)) | {s for s in strikes if band_lo <= s <= band_hi})
    return calls.reindex(keep).fillna(0), puts.reindex(keep).fillna(0)


def fmt_gex(v: float) -> str:
    """Format GEX in $B or $M."""
    if abs(v) >= 1e9:
        return f"{v/1e9:+.2f}B"
    if abs(v) >= 1e6:
        return f"{v/1e6:+.0f}M"
    return f"{v:+.0f}"


def fmt_axis(v: float, _pos=None) -> str:
    if v == 0:
        return "0"
    if abs(v) >= 1e9:
        return f"{v/1e9:.0f}B"
    if abs(v) >= 1e6:
        return f"{v/1e6:.0f}M"
    return f"{v:.0f}"


def gamma_walls(calls: pd.Series, puts: pd.Series, n: int = 3) -> tuple[list, list]:
    top_calls = calls.sort_values(ascending=False).head(n)
    top_puts = puts.sort_values(ascending=True).head(n)  # puts are negative
    call_walls = [(float(k), float(v)) for k, v in top_calls.items() if v > 0]
    put_walls = [(float(k), float(v)) for k, v in top_puts.items() if v < 0]
    return call_walls, put_walls


def render_panel(ax, calls: pd.Series, puts: pd.Series, spot: float, title: str, zgl: float | None = None):
    strikes = sorted(set(calls.index) | set(puts.index))
    cv = np.array([calls.get(s, 0) for s in strikes])
    pv = np.array([puts.get(s, 0) for s in strikes])

    width = max((strikes[-1] - strikes[0]) / max(len(strikes), 1) * 0.85, 1.0) if len(strikes) > 1 else 5.0

    ax.bar(strikes, cv, width=width, color="#a8e6a8", label="Call GEX")
    ax.bar(strikes, pv, width=width, color="#e6a8d3", label="Put GEX")
    ax.axvline(spot, color="#00d9ff", lw=2, label="Spot Price")
    if zgl is not None and not np.isnan(zgl):
        ax.axvline(zgl, color="#f0e833", lw=1.5, ls="--", label=f"HVL {zgl:,.1f}")
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
    """Perfiliev re-priced Gamma Flip (HVL) — the canonical SqueezeMetrics method.

    Holds OI fixed and RE-PRICES gamma via Black-Scholes at n spot levels across
    [0.8, 1.2]*spot, sums the signed dealer gamma profile (call gamma − put gamma),
    and returns the zero-crossing strike. This is materially more accurate than
    accumulating static snapshot gamma across strikes (see gamma-profile.py
    comparison: the static proxy mislocated HVL by 180–325 pts).

    `sub` needs per-contract columns: strike, type ('C'/'P'), iv, T (years), oi.
    Returns (flip_strike | nan, peak_|profile| as magnitude in $).
    """
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
    # Reject spurious edge crossings: for short-dated expiries the profile underflows
    # to ~0 far from spot, so tiny sign flicker at the edges creates fake crossings
    # (e.g. a flip printed at 0.82*spot). Require meaningful profile magnitude on at
    # least one side, then pick the crossing nearest spot (the real dealer flip).
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


def zero_gamma_flip(calls: pd.Series, puts: pd.Series) -> tuple[float, float]:
    """LEGACY static-gamma ZGL proxy — superseded by gamma_flip_bs() in production.

    Walks strikes low → high accumulating static net GEX and returns the cumulative
    zero-cross. Retained only so gamma-profile.py can show the legacy-vs-BS delta;
    NOT used by the main GEX run anymore (it mislocates the flip by 180–325 pts
    because static snapshot gamma at far strikes does not reflect the gamma those
    strikes would carry at the candidate spot).
    Returns (flip_strike, peak_|cumulative| as magnitude).
    """
    all_strikes = sorted(set(calls.index) | set(puts.index))
    if not all_strikes:
        return (float("nan"), 0.0)
    net = pd.Series({k: float(calls.get(k, 0.0)) + float(puts.get(k, 0.0)) for k in all_strikes}).sort_index()
    cum = net.cumsum()
    mag = float(cum.abs().max())

    strikes = cum.index.to_numpy()
    vals = cum.to_numpy()
    # First sign change going up
    for i in range(1, len(vals)):
        if vals[i - 1] == 0:
            return (float(strikes[i - 1]), mag)
        if (vals[i - 1] < 0 < vals[i]) or (vals[i - 1] > 0 > vals[i]):
            v1, v2 = vals[i - 1], vals[i]
            k1, k2 = strikes[i - 1], strikes[i]
            frac = -v1 / (v2 - v1)
            return (float(k1 + frac * (k2 - k1)), mag)
    # No sign change — dealer gamma never flips in the observed strike range
    if vals[-1] > 0:
        return (float(strikes[0]), mag)
    return (float(strikes[-1]), mag)


def per_expiry_key_strikes(df: pd.DataFrame, expiries: list[date], spot: float) -> pd.DataFrame:
    """For each expiry: max call wall, max put wall, and Zero-Gamma Level (ZGL / BS flip)."""
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


def top_put_watch_dates(key: pd.DataFrame, today: date, n: int = 3) -> pd.DataFrame:
    """Top-n expiries by max-put-GEX magnitude from the evolution key-strikes table.

    Today's expiry (0DTE) is excluded — it would occupy a slot every day and churn
    the watch list on every run. Expiries whose put-GEX magnitudes are similar
    (within 10% of each other) are treated as equivalent, and within such a group
    the LOWEST put-wall strike wins (the deepest SPX level is the one to watch).
    """
    cand = key[(key["expiry"] > today) & (key["put_mag"] > 0)]
    if cand.empty:
        return cand
    by_mag = cand.sort_values("put_mag", ascending=False)
    # Walk down by magnitude, grouping rows within 10% of the group's leader;
    # inside a group order by put_strike ascending, then take the top n overall.
    ordered, group, leader = [], [], None
    for _, r in by_mag.iterrows():
        if leader is not None and r["put_mag"] < 0.9 * leader:
            ordered.extend(sorted(group, key=lambda x: x["put_strike"]))
            group, leader = [], None
        if leader is None:
            leader = r["put_mag"]
        group.append(r)
    ordered.extend(sorted(group, key=lambda x: x["put_strike"]))
    top = pd.DataFrame(ordered[:n])
    return top.sort_values("expiry").reset_index(drop=True)


def load_put_watch() -> dict | None:
    """Previous run's watch state, or None on first run / unreadable file."""
    try:
        with open(PUT_WATCH_FILE, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state.get("dates"), dict):
            return None
        return state
    except Exception:
        return None


def save_put_watch(today: date, watch: pd.DataFrame):
    state = {
        "run_date": today.isoformat(),
        "dates": {
            r["expiry"].isoformat(): {
                "put_strike": float(r["put_strike"]),
                "put_mag": float(r["put_mag"]),
            }
            for _, r in watch.iterrows()
        },
    }
    try:
        with open(PUT_WATCH_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"put-watch state save failed: {e}", file=sys.stderr)


def diff_put_watch(prev: dict, watch: pd.DataFrame, today: date) -> list[str]:
    """Day-over-day watch-list diff lines.

    A date dropping out because it expired (or is today) is expected churn and gets
    an informational note; a date dropping while still in the future means dealer
    put positioning moved and gets the loud flag.
    """
    prev_dates = prev.get("dates", {})
    cur = {r["expiry"].isoformat(): r for _, r in watch.iterrows()}
    lines = []
    changed = False
    for d in sorted(set(prev_dates) - set(cur)):
        try:
            still_future = date.fromisoformat(d) > today
        except ValueError:
            still_future = False
        if still_future:
            lines.append(f"  ⚠ WATCH DATE CHANGED: {d} dropped while still in the future")
            changed = True
        else:
            lines.append(f"  note: {d} left the watch (expired / is today)")
    for d in sorted(set(cur) - set(prev_dates)):
        r = cur[d]
        lines.append(f"  ⚠ ADDED: {d}   put wall {r['put_strike']:,.0f}   {fmt_gex(-r['put_mag'])}")
        changed = True
    for d in sorted(set(cur) & set(prev_dates)):
        r, p = cur[d], prev_dates[d]
        ps = p.get("put_strike")
        pm = fmt_gex(-p.get("put_mag", 0.0))
        cm = fmt_gex(-r["put_mag"])
        if ps is not None and abs(ps - float(r["put_strike"])) >= 0.5:
            lines.append(f"  {d}: put wall moved {ps:,.0f} -> {r['put_strike']:,.0f}  (mag {pm} -> {cm})")
        else:
            lines.append(f"  {d}: put wall unchanged at {r['put_strike']:,.0f}  (mag {pm} -> {cm})")
    if not changed:
        lines.append("  watch dates unchanged")
    return lines


def build_put_watch_report(spot: float, today: date, watch: pd.DataFrame, prev: dict | None) -> str:
    lines = ["```"]
    lines.append("=" * 56)
    lines.append(f"SPX PUT GEX WATCH  —  Spot {spot:,.2f}   {today.isoformat()}")
    lines.append(f"Top {len(watch)} max-put-GEX expiries (next 10 trading days)")
    lines.append("=" * 56)
    lines.append("")
    for rank, (_, r) in enumerate(watch.iterrows(), 1):
        dte = (r["expiry"] - today).days
        lines.append(
            f"  #{rank}  {r['expiry'].isoformat()}  ({dte:>2}d)   "
            f"put wall {r['put_strike']:>8,.0f}   {fmt_gex(-r['put_mag'])}"
        )
    lines.append("")
    if prev is None:
        lines.append("First run — watch dates saved; comparison starts next run.")
    else:
        lines.append(f"VS PREVIOUS RUN ({prev.get('run_date', '?')}):")
        lines.extend(diff_put_watch(prev, watch, today))
    lines.append("```")
    return "\n".join(lines)


def render_put_watch_chart(df: pd.DataFrame, exp: date, spot: float, rank: int,
                           put_strike: float, today: date) -> io.BytesIO:
    """Full-size GEX bar chart for one put-watch expiry, visually flagged orange."""
    sub = df[df["expiry"] == exp]
    calls, puts = aggregate_strikes(sub)
    calls, puts = clip_strike_range(calls, puts, spot)
    zgl, _ = gamma_flip_bs(sub, spot)
    dte = (exp - today).days

    fig, ax = plt.subplots(figsize=(14, 6), facecolor="#1a1a2e")
    render_panel(ax, calls, puts, spot, "", zgl=zgl)
    if not np.isnan(put_strike):
        ax.axvline(put_strike, color="#ff9933", lw=2, ls="--", label=f"Max Put GEX {put_strike:,.0f}")
    ax.set_title(f"PUT WATCH #{rank}  —  SPX {exp.isoformat()}  ({dte} DTE)",
                 color="#ff9933", fontsize=13, weight="bold")
    ax.legend(loc="upper right", facecolor="#1a1a2e", edgecolor="#444444", labelcolor="white", fontsize=8)
    fig.patch.set_linewidth(4)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor="#1a1a2e", edgecolor="#ff9933")
    plt.close(fig)
    return buf


def render_evolution(key: pd.DataFrame, spot: float, watch_dates: list[date] | None = None) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(14, 7), facecolor="#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    x = pd.to_datetime(key["expiry"])
    # Normalize bubble size by global max magnitude across all three series
    all_mags = pd.concat([key["call_mag"], key["put_mag"], key["net_mag"]])
    mmax = float(all_mags.max()) if len(all_mags) and all_mags.max() > 0 else 1.0

    def bsize(s: pd.Series) -> np.ndarray:
        return 80 + 1700 * (s.values / mmax)

    # Lines + bubbles
    ax.plot(x, key["call_strike"], color="#7ed87e", lw=2, marker="", label="Max Call GEX Strike", zorder=2)
    ax.scatter(x, key["call_strike"], s=bsize(key["call_mag"]), color="#7ed87e", alpha=0.55, edgecolors="#7ed87e", zorder=3)

    ax.plot(x, key["put_strike"], color="#e6a8d3", lw=2, marker="", label="Max Put GEX Strike (magnitude)", zorder=2)
    ax.scatter(x, key["put_strike"], s=bsize(key["put_mag"]), color="#e6a8d3", alpha=0.55, edgecolors="#e6a8d3", zorder=3)

    ax.plot(x, key["net_strike"], color="#f0e833", lw=2, marker="", label="Zero-Gamma Flip (ZGL)", zorder=2)
    ax.scatter(x, key["net_strike"], s=bsize(key["net_mag"]), color="#f0e833", alpha=0.55, edgecolors="#f0e833", zorder=3)

    # Per-point strike labels
    for _, r in key.iterrows():
        xd = pd.Timestamp(r["expiry"])
        if not np.isnan(r["call_strike"]):
            ax.annotate(f"{r['call_strike']:,.0f}", (xd, r["call_strike"]),
                        xytext=(0, 12), textcoords="offset points", ha="center", color="white", fontsize=8)
        if not np.isnan(r["put_strike"]):
            ax.annotate(f"{r['put_strike']:,.0f}", (xd, r["put_strike"]),
                        xytext=(0, -16), textcoords="offset points", ha="center", color="white", fontsize=8)
        if not np.isnan(r["net_strike"]):
            ax.annotate(f"{r['net_strike']:,.0f}", (xd, r["net_strike"]),
                        xytext=(0, 12), textcoords="offset points", ha="center", color="white", fontsize=8)

    # Spot line
    ax.axhline(spot, color="#00d9ff", lw=1.2, ls="--", alpha=0.8)
    ax.text(x.iloc[-1], spot, f"  Spot {spot:,.2f}", color="#00d9ff", va="center", fontsize=9)

    # Put-watch dates: vertical orange markers on the top-3 max-put-GEX expiries
    if watch_dates:
        for i, d in enumerate(watch_dates):
            ax.axvline(pd.Timestamp(d), color="#ff9933", lw=1.5, ls="--", alpha=0.8,
                       zorder=1, label="PUT WATCH" if i == 0 else None)

    ax.set_title("SPX — Key Strike Evolution with GEX Magnitude Bubbles\nToday + Next 10 Trading Days",
                 color="white", fontsize=13)
    ax.set_xlabel("Trading Day", color="white")
    ax.set_ylabel("Strike Price", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("#444444")
    ax.grid(True, alpha=0.2, color="white")
    leg = ax.legend(loc="upper left", facecolor="#0d0d1f", edgecolor="#444444", labelcolor="white")
    fig.autofmt_xdate()
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor="#1a1a2e")
    plt.close(fig)
    return buf


def render_levels_map(spot: float, levels: dict, em: tuple | None, today: date) -> io.BytesIO:
    """MenthorQ-style level map: horizontal lines on a price axis with labels.

    Mirrors the TradingView overlay — Call Resistance / GEX 1-5 / HVL / Put Support,
    0DTE variants, 1D Max/Min (IV expected move), and spot.
    """
    full = levels["full"]
    zerod = levels["zerod"]

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
        add(zerod.get("call_wall"), "Call Resistance 0DTE / Gamma Wall", RED)
        add(zerod.get("put_wall"), "Put Support 0DTE", GREEN)
        add(zerod.get("zgl"), "HVL 0DTE", YEL, ls=":")
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

    # De-collide labels: nudge text y (lines stay at true price)
    mingap = (ymax - ymin + 2 * pad) * 0.028
    order = sorted(L, key=lambda z: z["p"])
    last_y = -1e18
    for x in order:
        ty = x["p"]
        if ty - last_y < mingap:
            ty = last_y + mingap
        last_y = ty
        ax.text(0.015, ty, f"{x['label']}  {x['p']:,.0f}",
                transform=ax.get_yaxis_transform(), color=x["color"],
                fontsize=9.5, va="center", ha="left", weight=x["w"], zorder=4,
                bbox=dict(boxstyle="round,pad=0.15", fc="#0d0d1f", ec="none", alpha=0.65))

    ax.set_title(f"SPX GEX LEVEL MAP  —  Spot {spot:,.2f}   {today.isoformat()}",
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
    spot: float,
    today: date,
    nearest: date,
    opex: date,
    near_calls: pd.Series, near_puts: pd.Series,
    opex_calls: pd.Series, opex_puts: pd.Series,
) -> str:
    near_net = float(near_calls.sum() + near_puts.sum())
    opex_net = float(opex_calls.sum() + opex_puts.sum())

    near_call_walls, near_put_walls = gamma_walls(near_calls, near_puts)
    opex_call_walls, opex_put_walls = gamma_walls(opex_calls, opex_puts)

    lines = []
    lines.append("```")
    lines.append("=" * 56)
    lines.append(f"SPX GEX PROFILE  —  Spot {spot:,.2f}   {today.isoformat()}")
    lines.append("=" * 56)
    lines.append("")
    lines.append(f"NEAREST EXPIRY ({nearest.isoformat()})  Net GEX: {fmt_gex(near_net)}")
    lines.append("-" * 56)
    lines.append("  Call Walls (resistance):")
    for k, v in near_call_walls:
        lines.append(f"    {k:>8,.0f}   {fmt_gex(v):>10}")
    lines.append("  Put Walls (support):")
    for k, v in near_put_walls:
        lines.append(f"    {k:>8,.0f}   {fmt_gex(v):>10}")
    lines.append("")
    lines.append(f"NEXT OPEX ({opex.isoformat()})  Net GEX: {fmt_gex(opex_net)}")
    lines.append("-" * 56)
    lines.append("  Call Walls (resistance):")
    for k, v in opex_call_walls:
        lines.append(f"    {k:>8,.0f}   {fmt_gex(v):>10}")
    lines.append("  Put Walls (support):")
    for k, v in opex_put_walls:
        lines.append(f"    {k:>8,.0f}   {fmt_gex(v):>10}")
    lines.append("```")
    return "\n".join(lines)


def build_levels_report(spot: float, levels: dict, today: date, em: tuple | None = None) -> str:
    """MenthorQ-style named-levels block: Call Resistance / Put Support / HVL +
    0DTE variants + GEX 1-5 magnets + 1D expected move + regime read."""
    full = levels["full"]
    zerod = levels["zerod"]
    lines = ["```"]
    lines.append("=" * 56)
    lines.append(f"SPX KEY GEX LEVELS  —  Spot {spot:,.2f}   {today.isoformat()}")
    lines.append("=" * 56)
    lines.append("")
    if em:
        lines.append(f"1D EXPECTED MOVE (ATM IV {em[2]*100:.1f}%):")
        lines.append(f"  1D Max               : {em[0]:>8,.0f}")
        lines.append(f"  1D Min               : {em[1]:>8,.0f}")
        lines.append("")
    lines.append(f"NEAR-TERM (<= {NEAR_TERM_DTE} DTE):")
    if full["call_wall"] is not None:
        lines.append(f"  Call Resistance      : {full['call_wall']:>8,.0f}   ({fmt_gex(full['call_wall_v'])})")
    if full["put_wall"] is not None:
        lines.append(f"  Put Support          : {full['put_wall']:>8,.0f}   ({fmt_gex(-full['put_wall_v'])})")
    if full["zgl"] is not None and not np.isnan(full["zgl"]):
        lines.append(f"  HVL (Zero Gamma)     : {full['zgl']:>8,.1f}")
    lines.append("")
    if zerod is not None:
        lines.append(f"0DTE ONLY (expiring {today.isoformat()}):")
        if zerod["call_wall"] is not None:
            lines.append(f"  Call Resistance 0DTE : {zerod['call_wall']:>8,.0f}   (Gamma Wall 0DTE)")
        if zerod["put_wall"] is not None:
            lines.append(f"  Put Support 0DTE     : {zerod['put_wall']:>8,.0f}")
        if zerod["zgl"] is not None and not np.isnan(zerod["zgl"]):
            lines.append(f"  HVL 0DTE             : {zerod['zgl']:>8,.1f}")
        lines.append("")
    lines.append("GEX 1-5 (top gamma walls near spot, by gross):")
    for i, (k, net_v, gross_v) in enumerate(levels["gex_top5"], 1):
        side = "CALL+" if net_v > 0 else "PUT- "
        lines.append(f"  GEX {i}: {k:>8,.0f}   {side} {gross_v/1e9:.2f}B")
    lines.append("")
    lines.append("REGIME (spot vs HVL):")
    if full["zgl"] is not None and not np.isnan(full["zgl"]):
        d = spot - full["zgl"]
        reg = "LONG GAMMA (pin/dampen)" if d >= 0 else "SHORT GAMMA (vol expansion)"
        lines.append(f"  Near-term  : {d:+6.1f}   {reg}")
    if zerod is not None and zerod["zgl"] is not None and not np.isnan(zerod["zgl"]):
        d = spot - zerod["zgl"]
        reg = "LONG GAMMA (pin/dampen)" if d >= 0 else "SHORT GAMMA (vol expansion)"
        lines.append(f"  0DTE       : {d:+6.1f}   {reg}")
    lines.append("```")
    return "\n".join(lines)


def main():
    now = datetime.now(ET)
    today = now.date()
    print(f"[GEX] {now.isoformat()} fetching CBOE SPX chain...")

    payload = fetch_cboe_chain()
    if payload is None:
        send_discord_text(f"GEX scanner: CBOE fetch failed at {now.isoformat()}")
        return

    try:
        spot, df = parse_chain(payload)
    except Exception as e:
        send_discord_text(f"GEX scanner: parse failed — {e}")
        return

    if df.empty:
        send_discord_text(f"GEX scanner: no parseable contracts in CBOE response")
        return

    df = compute_gex(df, spot)
    df = add_dte(df, today)  # T (years to expiry) for the Black-Scholes gamma flip
    print(f"[GEX] spot={spot:.2f}  rows={len(df)}  expiries={df['expiry'].nunique()}")

    nearest, opex = pick_expiries(df, today)
    if nearest is None or opex is None:
        send_discord_text(f"GEX scanner: could not resolve expiries (today={today})")
        return
    print(f"[GEX] nearest={nearest}  opex={opex}")

    near_df = df[df["expiry"] == nearest]
    opex_df = df[df["expiry"] == opex]

    near_calls, near_puts = aggregate_strikes(near_df)
    opex_calls, opex_puts = aggregate_strikes(opex_df)

    near_calls, near_puts = clip_strike_range(near_calls, near_puts, spot)
    opex_calls, opex_puts = clip_strike_range(opex_calls, opex_puts, spot)

    # Per-expiry HVL (Perfiliev BS gamma flip) for the panel annotations
    near_zgl, _ = gamma_flip_bs(near_df, spot)
    opex_zgl, _ = gamma_flip_bs(opex_df, spot)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 5), facecolor="#1a1a2e")
    render_panel(ax1, near_calls, near_puts, spot, f"SPX {nearest.isoformat()}", zgl=near_zgl)
    render_panel(ax2, opex_calls, opex_puts, spot, f"SPX OpEx ({opex.isoformat()})", zgl=opex_zgl)
    ax1.legend(loc="upper right", facecolor="#1a1a2e", edgecolor="#444444", labelcolor="white", fontsize=8)
    ax2.legend(loc="upper right", facecolor="#1a1a2e", edgecolor="#444444", labelcolor="white", fontsize=8)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor="#1a1a2e")
    plt.close(fig)

    report = build_text_report(spot, today, nearest, opex, near_calls, near_puts, opex_calls, opex_puts)
    send_discord_text(report)
    send_discord_image(buf, f"spx_gex_{today.isoformat()}.png")

    # MenthorQ-style named-levels post (near-term structural + 0DTE + GEX 1-5 + 1D move + regime)
    near_term_df = df[df["expiry"] <= today + timedelta(days=NEAR_TERM_DTE)]
    levels = compute_named_levels(near_term_df, near_df, spot)
    em = compute_expected_move(df, spot, nearest)
    send_discord_text(build_levels_report(spot, levels, today, em))

    # MenthorQ-style level map (horizontal lines on a price axis)
    map_buf = render_levels_map(spot, levels, em, today)
    send_discord_image(map_buf, f"spx_gex_map_{today.isoformat()}.png")

    # Evolution chart: max call / max put / max net GEX strike for today + next 10 expiries
    all_expiries = sorted(df["expiry"].unique())
    future_expiries = [e for e in all_expiries if e >= today][:11]
    if len(future_expiries) >= 2:
        key = per_expiry_key_strikes(df, future_expiries, spot)
        if not key.empty:
            # Put-GEX watch: top 3 future expiries by max-put-GEX magnitude
            watch = top_put_watch_dates(key, today)
            evo_buf = render_evolution(key, spot, watch_dates=list(watch["expiry"]) if not watch.empty else None)
            send_discord_image(evo_buf, f"spx_gex_evolution_{today.isoformat()}.png")
            print(f"[GEX] evolution chart sent ({len(key)} expiries)")

            if watch.empty:
                print("[GEX] put-watch: no future expiries with put gamma — section skipped", file=sys.stderr)
            else:
                prev = load_put_watch()
                send_discord_text(build_put_watch_report(spot, today, watch, prev))
                for rank, (_, r) in enumerate(watch.iterrows(), 1):
                    wbuf = render_put_watch_chart(df, r["expiry"], spot, rank, r["put_strike"], today)
                    send_discord_image(wbuf, f"spx_gex_putwatch{rank}_{r['expiry'].isoformat()}.png")
                save_put_watch(today, watch)
                print(f"[GEX] put-watch sent ({len(watch)} dates: {[e.isoformat() for e in watch['expiry']]})")
    print("[GEX] done")


if __name__ == "__main__":
    main()
