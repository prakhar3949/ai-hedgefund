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
import re
import sys
import requests
import numpy as np
import pandas as pd
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

# SPX option symbol: e.g. "SPXW260613C07450000" or "SPX260618P07000000"
SYMBOL_RE = re.compile(r"^SPX[W]?(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")


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
        rows.append({
            "expiry": exp,
            "strike": strike,
            "type": cp,
            "oi": float(oi),
            "gamma": float(gamma),
        })
    df = pd.DataFrame(rows)
    return float(spot), df


def compute_gex(df: pd.DataFrame, spot: float) -> pd.DataFrame:
    df = df.copy()
    df["gex"] = df["gamma"] * df["oi"] * 100.0 * (spot ** 2) * 0.01
    df.loc[df["type"] == "P", "gex"] *= -1.0
    return df


def pick_expiries(df: pd.DataFrame, today: date) -> tuple[date | None, date | None]:
    """Return (nearest_expiry, opex_expiry).

    nearest_expiry: smallest expiry >= today, else None
    opex_expiry: expiry within today+10..today+45 with highest total OI
                 (falls back to first expiry >= today+10 if window empty)
    """
    expiries = sorted(df["expiry"].unique())
    if not expiries:
        return None, None

    future = [e for e in expiries if e >= today]
    nearest = future[0] if future else None

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


def compute_named_levels(df: pd.DataFrame, near_df: pd.DataFrame) -> dict:
    """MenthorQ-style level taxonomy from the GEX chain.

    Full-chain: Call Resistance, Put Support, HVL (Zero Gamma).
    0DTE-only:  Call Resistance 0DTE / Gamma Wall 0DTE, Put Support 0DTE, HVL 0DTE.
    GEX 1-5:    Top 5 strikes by |net GEX| across the full chain.
    """
    def _levels(sub: pd.DataFrame) -> dict:
        calls = sub[sub["type"] == "C"].groupby("strike")["gex"].sum()
        puts = sub[sub["type"] == "P"].groupby("strike")["gex"].sum()
        all_s = sorted(set(calls.index) | set(puts.index))
        net = pd.Series(
            {k: float(calls.get(k, 0.0)) + float(puts.get(k, 0.0)) for k in all_s}
        ).sort_index()
        zgl, _ = zero_gamma_flip(calls, puts)
        return {
            "call_wall": float(calls.idxmax()) if not calls.empty and calls.max() > 0 else None,
            "call_wall_v": float(calls.max()) if not calls.empty else 0.0,
            "put_wall": float(puts.idxmin()) if not puts.empty and puts.min() < 0 else None,
            "put_wall_v": float(abs(puts.min())) if not puts.empty else 0.0,
            "zgl": zgl,
            "net": net,
        }

    full = _levels(df)
    zerod = _levels(near_df) if not near_df.empty else None
    top5_idx = full["net"].abs().sort_values(ascending=False).head(5).index
    top5 = [(float(k), float(full["net"].loc[k])) for k in top5_idx]
    return {"full": full, "zerod": zerod, "gex_top5": top5}


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


def zero_gamma_flip(calls: pd.Series, puts: pd.Series) -> tuple[float, float]:
    """Compute the per-expiry Zero-Gamma Level (ZGL) — Perfiliev / SqueezeMetrics canonical.

    Walk strikes low → high, accumulate net GEX. The flip is where cumulative crosses zero.
    Below the flip dealers are net short gamma (vol expansion); above, net long gamma (pinning).
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


def per_expiry_key_strikes(df: pd.DataFrame, expiries: list[date]) -> pd.DataFrame:
    """For each expiry: max call wall, max put wall, and Zero-Gamma Level (ZGL)."""
    rows = []
    for exp in expiries:
        sub = df[df["expiry"] == exp]
        if sub.empty:
            continue
        calls = sub[sub["type"] == "C"].groupby("strike")["gex"].sum()
        puts = sub[sub["type"] == "P"].groupby("strike")["gex"].sum()

        max_call = (float(calls.idxmax()), float(calls.max())) if not calls.empty and calls.max() > 0 else (np.nan, 0.0)
        max_put = (float(puts.idxmin()), float(abs(puts.min()))) if not puts.empty and puts.min() < 0 else (np.nan, 0.0)
        zgl_strike, zgl_mag = zero_gamma_flip(calls, puts)

        rows.append({
            "expiry": exp,
            "call_strike": max_call[0], "call_mag": max_call[1],
            "put_strike": max_put[0],   "put_mag": max_put[1],
            "net_strike": zgl_strike,   "net_mag": zgl_mag,
        })
    return pd.DataFrame(rows)


def render_evolution(key: pd.DataFrame, spot: float) -> io.BytesIO:
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


def build_levels_report(spot: float, levels: dict, today: date) -> str:
    """MenthorQ-style named-levels block: Call Resistance / Put Support / HVL +
    0DTE variants + GEX 1-5 magnets + regime read."""
    full = levels["full"]
    zerod = levels["zerod"]
    lines = ["```"]
    lines.append("=" * 56)
    lines.append(f"SPX KEY GEX LEVELS  —  Spot {spot:,.2f}   {today.isoformat()}")
    lines.append("=" * 56)
    lines.append("")
    lines.append("FULL CHAIN (all expirations):")
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
    lines.append("GEX 1-5 (top magnets, full chain):")
    for i, (k, v) in enumerate(levels["gex_top5"], 1):
        side = "CALL+" if v > 0 else "PUT- "
        lines.append(f"  GEX {i}: {k:>8,.0f}   {side} {fmt_gex(abs(v))}")
    lines.append("")
    lines.append("REGIME (spot vs HVL):")
    if full["zgl"] is not None and not np.isnan(full["zgl"]):
        d = spot - full["zgl"]
        reg = "LONG GAMMA (pin/dampen)" if d >= 0 else "SHORT GAMMA (vol expansion)"
        lines.append(f"  Full chain : {d:+6.1f}   {reg}")
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

    # Per-expiry ZGLs for the panel annotations (computed on UNCLIPPED data for accuracy)
    near_zgl, _ = zero_gamma_flip(*aggregate_strikes(near_df))
    opex_zgl, _ = zero_gamma_flip(*aggregate_strikes(opex_df))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 5), facecolor="#1a1a2e")
    render_panel(ax1, near_calls, near_puts, spot, f"SPX {nearest.isoformat()}", zgl=near_zgl)
    render_panel(ax2, opex_calls, opex_puts, spot, f"SPX OpEx ({opex.isoformat()})", zgl=opex_zgl)
    ax2.legend(loc="upper right", facecolor="#1a1a2e", edgecolor="#444444", labelcolor="white")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor="#1a1a2e")
    plt.close(fig)

    report = build_text_report(spot, today, nearest, opex, near_calls, near_puts, opex_calls, opex_puts)
    send_discord_text(report)
    send_discord_image(buf, f"spx_gex_{today.isoformat()}.png")

    # MenthorQ-style named-levels post (full chain + 0DTE + GEX 1-5 + regime)
    levels = compute_named_levels(df, near_df)
    send_discord_text(build_levels_report(spot, levels, today))

    # Evolution chart: max call / max put / max net GEX strike for today + next 10 expiries
    all_expiries = sorted(df["expiry"].unique())
    future_expiries = [e for e in all_expiries if e >= today][:11]
    if len(future_expiries) >= 2:
        key = per_expiry_key_strikes(df, future_expiries)
        if not key.empty:
            evo_buf = render_evolution(key, spot)
            send_discord_image(evo_buf, f"spx_gex_evolution_{today.isoformat()}.png")
            print(f"[GEX] evolution chart sent ({len(key)} expiries)")
    print("[GEX] done")


if __name__ == "__main__":
    main()
