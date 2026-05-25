"""
Sortino Ratio Portfolio Optimizer
Optimizes portfolio weights to maximize the Sortino ratio across three groups
and three timeframes, then posts results to Discord.

Groups:
  1. 11 S&P 500 sector ETFs
  2. 26 subsector / thematic ETFs
  3. 26 watchlist stocks (from watchlist.json)

Timeframes:
  1W (5 trading days), 4W (20 trading days), 3M (63 trading days)

Methodology:
  - Sortino ratio = (Rp - Rf) / downside_deviation
  - Downside deviation = sqrt(mean(min(r - Rf, 0)^2))
  - scipy SLSQP optimizer with 6 random starting points, long-only constraint
  - Risk-free rate from FRED FEDFUNDS series

Cost: $0.00 (Yahoo Chart API + FRED CSV, no LLM)
"""

import io
import json
import sys
import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from scipy.optimize import minimize

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

# ── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1471847874877984880/"
    "GyBts1ebRF-dO-ZGp5Wz5AIVypIrCc9mjqn2LOERF9v4UTUEYwIM_oqoJgqSK-dyRmri"
)

# ── Sector ETFs (11) ─────────────────────────────────────────────────────────
SECTOR_ETFS = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Health Care", "XLI": "Industrials", "XLP": "Staples",
    "XLY": "Discret.", "XLU": "Utilities", "XLC": "Comms",
    "XLB": "Materials", "XLRE": "Real Estate",
}

# ── Equal-Weight Sector ETFs (11) ────────────────────────────────────────────
EW_SECTOR_ETFS = {
    "RSPT": "EW Tech", "RSPF": "EW Financ.", "RSPG": "EW Energy",
    "RSPH": "EW Health", "RSPN": "EW Indust.", "RSPS": "EW Staples",
    "RSPD": "EW Discret.", "RSPU": "EW Utilities", "RSPC": "EW Comms",
    "RSPM": "EW Materials", "RSPR": "EW RealEst.",
}

# ── Subsector / Thematic ETFs (26) ───────────────────────────────────────────
SUBSECTOR_ETFS = {
    "ITA": "Aerospace", "ITB": "Homebuilders", "IBB": "Biotech",
    "VNQ": "REITs", "IYZ": "Telecom", "BOTZ": "Robotics",
    "SOCL": "Social Media", "XRT": "Retail", "KRE": "Reg. Banks",
    "IHI": "Med Devices", "IGV": "Software", "KWEB": "China Tech",
    "CIBR": "Cybersec", "BETZ": "Sports Bet", "AIQ": "AI & Big Data",
    "QTUM": "Quantum/AI", "SLX": "Steel", "SMH": "Semis",
    "JETS": "Airlines", "IYT": "Transport", "TAN": "Solar",
    "ARKG": "Genomics", "IBIT": "Bitcoin", "VUG": "Growth",
    "GDX": "Gold Miners", "SIL": "Silver Min.",
}

# ── Timeframes ───────────────────────────────────────────────────────────────
TIMEFRAMES = [
    ("1W", 5),
    ("4W", 20),
    ("3M", 63),
]

# ── Yahoo Chart API ──────────────────────────────────────────────────────────
YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def fetch_close(ticker: str, period: str = "6mo") -> pd.Series | None:
    """Fetch close prices via Yahoo Chart API."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?range={period}&interval=1d"
    )
    try:
        resp = requests.get(url, headers=YAHOO_HEADERS, timeout=15)
        data = resp.json()["chart"]["result"][0]
        timestamps = data["timestamp"]
        closes = data["indicators"]["quote"][0]["close"]
        idx = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert("America/New_York").normalize()
        s = pd.Series(closes, index=idx, name=ticker, dtype=float).dropna()
        s.index = s.index.tz_localize(None)
        return s if len(s) >= 20 else None
    except Exception as e:
        print(f"  fetch_close({ticker}): {e}", file=sys.stderr)
        return None


def fetch_all_closes(tickers: list[str], period: str = "6mo") -> dict[str, pd.Series]:
    """Parallel fetch close prices for multiple tickers."""
    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fetch_close, t, period): t for t in tickers}
        for f in as_completed(futures):
            t = futures[f]
            try:
                s = f.result()
                if s is not None:
                    results[t] = s
            except Exception as e:
                print(f"  {t}: error: {e}", file=sys.stderr)
    return results


# ── FRED risk-free rate ──────────────────────────────────────────────────────
def get_risk_free_rate() -> float:
    """Fetch current Fed Funds rate from FRED, return as daily rate."""
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS"
        df = pd.read_csv(url, parse_dates=["observation_date"])
        df["FEDFUNDS"] = pd.to_numeric(df["FEDFUNDS"], errors="coerce")
        df = df.dropna()
        annual_rate = df["FEDFUNDS"].iloc[-1] / 100.0
        daily_rate = annual_rate / 252.0
        print(f"  Risk-free rate: {annual_rate*100:.2f}% annual ({daily_rate*100:.4f}% daily)")
        return daily_rate
    except Exception as e:
        print(f"  FRED FEDFUNDS fetch failed ({e}), using 5.0% default", file=sys.stderr)
        return 0.05 / 252.0


# ── Sortino optimization ────────────────────────────────────────────────────
def compute_sortino(weights: np.ndarray, returns: np.ndarray, rf_daily: float) -> float:
    """Compute Sortino ratio for given weights. Returns negative for minimization."""
    port_returns = returns @ weights
    excess = port_returns - rf_daily
    mean_excess = np.mean(excess)
    downside = excess.copy()
    downside[downside > 0] = 0
    dd = np.sqrt(np.mean(downside ** 2))
    if dd < 1e-10:
        return -100.0 if mean_excess > 0 else 0.0
    return -(mean_excess / dd)


def optimize_sortino(
    returns: np.ndarray,
    rf_daily: float,
    n_starts: int = 6,
) -> tuple[np.ndarray, float]:
    """
    Maximize Sortino ratio using SLSQP with multiple random starts.
    Returns (optimal_weights, best_sortino_ratio).
    """
    n = returns.shape[1]
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = [(0.0, 1.0)] * n

    best_result = None
    best_val = np.inf

    for i in range(n_starts):
        if i == 0:
            w0 = np.ones(n) / n  # equal weight start
        else:
            w0 = np.random.dirichlet(np.ones(n))

        try:
            res = minimize(
                compute_sortino,
                w0,
                args=(returns, rf_daily),
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": 500, "ftol": 1e-12},
            )
            if res.fun < best_val:
                best_val = res.fun
                best_result = res
        except Exception:
            continue

    if best_result is None:
        return np.ones(n) / n, 0.0

    weights = best_result.x
    weights[weights < 0.01] = 0.0
    weights /= weights.sum()
    return weights, -best_val


def interpret_sortino(s: float) -> str:
    """Interpret Sortino ratio value."""
    if s >= 3.0:
        return "Elite"
    elif s >= 2.0:
        return "Excellent"
    elif s >= 1.0:
        return "Good"
    else:
        return "Risky"


# ── Chart rendering ──────────────────────────────────────────────────────────
def render_bar_chart(
    tickers: list[str],
    weights_by_tf: dict[str, np.ndarray],
    sortinos_by_tf: dict[str, float],
    group_label: str,
) -> io.BytesIO:
    """Render grouped bar chart of optimal weights across timeframes."""
    # Filter to tickers with any non-zero weight
    active_indices = set()
    for w in weights_by_tf.values():
        for i, v in enumerate(w):
            if v >= 0.01:
                active_indices.add(i)

    if not active_indices:
        return io.BytesIO()

    active_indices = sorted(active_indices)
    active_tickers = [tickers[i] for i in active_indices]
    tf_labels = list(weights_by_tf.keys())

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    x = np.arange(len(active_tickers))
    width = 0.25
    colors = ["#00d4ff", "#51cf66", "#ffd43b"]

    for j, tf in enumerate(tf_labels):
        w = weights_by_tf[tf]
        vals = [w[i] * 100 for i in active_indices]
        sortino = sortinos_by_tf[tf]
        rating = interpret_sortino(sortino)
        bars = ax.bar(
            x + j * width, vals, width,
            label=f"{tf} (S={sortino:.2f} {rating})",
            color=colors[j], alpha=0.85,
        )
        for bar, val in zip(bars, vals):
            if val >= 3.0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                    f"{val:.0f}%", ha="center", va="bottom",
                    color="white", fontsize=6, fontweight="bold",
                )

    ax.set_xticks(x + width)
    ax.set_xticklabels(active_tickers, rotation=45, ha="right", color="white", fontsize=8)
    ax.set_ylabel("Weight (%)", color="white", fontsize=10)
    ax.set_title(
        f"Sortino-Optimal Weights — {group_label}",
        color="white", fontsize=13, fontweight="bold", pad=12,
    )
    ax.tick_params(colors="white", labelsize=8)
    ax.legend(loc="upper right", fontsize=8, facecolor="#2a2a3e", edgecolor="#444", labelcolor="white")
    for spine in ax.spines.values():
        spine.set_color("#444")
    ax.grid(axis="y", alpha=0.15, color="white")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor="#1a1a2e")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── Text table builder ───────────────────────────────────────────────────────
def build_text_table(
    tickers: list[str],
    names: dict[str, str],
    weights_by_tf: dict[str, np.ndarray],
    sortinos_by_tf: dict[str, float],
    group_label: str,
    now_et: datetime,
) -> str:
    """Build monospace text table of optimal weights."""
    lines = [f"**Sortino Optimizer — {group_label}** ({now_et.strftime('%a %b %d %I:%M %p ET')})"]

    # Sortino summary line
    parts = []
    for tf, s in sortinos_by_tf.items():
        parts.append(f"{tf}: {s:.2f} ({interpret_sortino(s)})")
    lines.append(f"Portfolio Sortino: {' | '.join(parts)}")
    lines.append("")

    # Collect tickers with any allocation
    active = []
    for i, t in enumerate(tickers):
        max_w = max(weights_by_tf[tf][i] for tf in weights_by_tf)
        if max_w >= 0.01:
            active.append((i, t))

    if not active:
        lines.append("No allocations above 1%.")
        return "\n".join(lines)

    lines.append("```")
    tf_labels = list(weights_by_tf.keys())
    header = f"{'Ticker':<8} {'Name':<14}" + "".join(f"{tf:>8}" for tf in tf_labels)
    lines.append(header)
    lines.append("-" * len(header))

    # Sort by max weight descending
    active.sort(key=lambda x: max(weights_by_tf[tf][x[0]] for tf in weights_by_tf), reverse=True)

    for i, t in active:
        name = names.get(t, t)[:13]
        row = f"{t:<8} {name:<14}"
        for tf in tf_labels:
            w = weights_by_tf[tf][i] * 100
            row += f"{w:>7.1f}%" if w >= 0.5 else f"{'—':>8}"
        lines.append(row)

    lines.append("```")
    return "\n".join(lines)


# ── Discord posting ──────────────────────────────────────────────────────────
def send_discord_text(text: str):
    if len(text) > 1950:
        text = text[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Discord text failed: {e}")


def send_discord_image(buf: io.BytesIO, filename: str):
    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            files={"file": (filename, buf, "image/png")},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  Discord image failed: {e}")


# ── Group runner ─────────────────────────────────────────────────────────────
def run_group(
    tickers_dict: dict[str, str],
    group_label: str,
    price_data: dict[str, pd.Series],
    rf_daily: float,
    now_et: datetime,
):
    """Run Sortino optimization for one group across all timeframes."""
    # Filter to tickers with enough data
    valid_tickers = []
    for t in tickers_dict:
        if t in price_data and len(price_data[t]) >= 63:
            valid_tickers.append(t)

    if len(valid_tickers) < 2:
        print(f"  {group_label}: only {len(valid_tickers)} tickers with data, skipping")
        return

    print(f"  {group_label}: {len(valid_tickers)} tickers with data")

    # Build returns DataFrame (aligned on common dates)
    closes = pd.DataFrame({t: price_data[t] for t in valid_tickers}).dropna()
    if len(closes) < 63:
        print(f"  {group_label}: only {len(closes)} common trading days, skipping")
        return

    daily_returns = closes.pct_change().dropna()

    weights_by_tf = {}
    sortinos_by_tf = {}

    for tf_label, tf_days in TIMEFRAMES:
        if len(daily_returns) < tf_days:
            print(f"  {group_label} {tf_label}: not enough data ({len(daily_returns)} < {tf_days})")
            continue

        ret_slice = daily_returns.iloc[-tf_days:].values
        w, s = optimize_sortino(ret_slice, rf_daily)
        weights_by_tf[tf_label] = w
        sortinos_by_tf[tf_label] = s
        print(f"    {tf_label}: Sortino={s:.2f} ({interpret_sortino(s)}), top={valid_tickers[np.argmax(w)]} {w.max()*100:.1f}%")

    if not weights_by_tf:
        return

    # Build and post text table
    text = build_text_table(valid_tickers, tickers_dict, weights_by_tf, sortinos_by_tf, group_label, now_et)
    send_discord_text(text)
    print(f"  Posted {group_label} text ({len(text)} chars)")

    # Build and post bar chart
    buf = render_bar_chart(valid_tickers, weights_by_tf, sortinos_by_tf, group_label)
    if buf.getbuffer().nbytes > 0:
        send_discord_image(buf, f"sortino_{group_label.lower().replace(' ', '_')}.png")
        print(f"  Posted {group_label} chart")


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting Sortino Optimizer")

    # Load watchlist
    watchlist_path = TOOLS_DIR / "watchlist.json"
    try:
        with open(watchlist_path) as f:
            wl = json.load(f)
        watchlist_tickers = {t: t for t in wl["tickers"]}
    except Exception as e:
        print(f"  Failed to load watchlist: {e}", file=sys.stderr)
        watchlist_tickers = {}

    # Collect all unique tickers
    all_tickers = list(set(
        list(SECTOR_ETFS.keys()) +
        list(EW_SECTOR_ETFS.keys()) +
        list(SUBSECTOR_ETFS.keys()) +
        list(watchlist_tickers.keys())
    ))
    print(f"  Fetching {len(all_tickers)} tickers...")

    # Fetch price data (6mo gives enough for 3M = 63 days)
    price_data = fetch_all_closes(all_tickers, period="6mo")
    print(f"  Got data for {len(price_data)}/{len(all_tickers)} tickers")

    # Get risk-free rate
    rf_daily = get_risk_free_rate()

    # Run each group
    run_group(SECTOR_ETFS, "Sectors", price_data, rf_daily, now_et)
    run_group(EW_SECTOR_ETFS, "EW Sectors", price_data, rf_daily, now_et)
    run_group(SUBSECTOR_ETFS, "Subsectors", price_data, rf_daily, now_et)
    if watchlist_tickers:
        run_group(watchlist_tickers, "Watchlist", price_data, rf_daily, now_et)

    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} Sortino Optimizer complete")


if __name__ == "__main__":
    main()
