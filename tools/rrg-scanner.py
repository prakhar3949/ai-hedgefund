"""
Relative Rotation Graph (RRG) Scanner
Plots S&P 500 sector ETFs + subsector/thematic ETFs on JdK RRG charts.

Produces daily (6mo) and weekly (2y) RRG scatter charts with trailing tails,
classifies tickers into 4 quadrants (Leading/Weakening/Lagging/Improving),
and posts results to Discord.

Methodology (JdK EMA-ratio):
  1. Compute raw RS = (ticker_close / benchmark_close) * 100
  2. RS-Ratio   = EMA(RS, RS_SHORT) / EMA(RS, RS_LONG) × 100
  3. RS-Momentum = EMA(RS-Ratio, RS_SHORT) / EMA(RS-Ratio, RS_LONG) × 100
  4. Data clipped to last completed Friday to avoid partial-bar distortion
  5. Plot current position + trailing tail on 4-quadrant chart

Cost: $0.00 (Yahoo chart API, no API key needed)
"""

import io
import sys
import time
import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

# ── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1471735980288512084/"
    "elHYE5X2rdUpudK_8K-5pdiSPGEfetkh0IYFO_TFTMeiBUarcgJ5nYgzvEreEry2E5fR"
)

# ── RRG parameters ───────────────────────────────────────────────────────────
RS_SHORT    = 10     # short EMA period for JdK RS-Ratio / RS-Momentum
RS_LONG     = 26     # long EMA period  (MACD-standard; tested 8/11 accuracy vs StockCharts)
TAIL_LENGTH = 5      # trailing dots on chart (plus current = 6 points)

# ── Sector ETFs (11) vs SPY ─────────────────────────────────────────────────
SECTOR_ETFS = {
    "XLK":  "Technology",
    "XLF":  "Financials",
    "XLE":  "Energy",
    "XLV":  "Health Care",
    "XLI":  "Industrials",
    "XLP":  "Staples",
    "XLY":  "Discret.",
    "XLU":  "Utilities",
    "XLC":  "Comms",
    "XLB":  "Materials",
    "XLRE": "Real Estate",
}

# ── Equal-Weight Sector ETFs (11) vs RSP ───────────────────────────────────
EW_SECTOR_ETFS = {
    "RSPT": "EW Tech",
    "RSPF": "EW Financ.",
    "RSPG": "EW Energy",
    "RSPH": "EW Health",
    "RSPN": "EW Indust.",
    "RSPS": "EW Staples",
    "RSPD": "EW Discret.",
    "RSPU": "EW Utilities",
    "RSPC": "EW Comms",
    "RSPM": "EW Materials",
    "RSPR": "EW RealEst.",
}

# ── Subsector / Thematic ETFs (31) vs SPY ────────────────────────────────────
SUBSECTOR_ETFS = {
    "ITA":  "Aerospace",
    "ITB":  "Homebuilders",
    "IBB":  "Biotech",
    "VNQ":  "REITs",
    "IYZ":  "Telecom",
    "BOTZ": "Robotics",
    "SOCL": "Social Media",
    "XRT":  "Retail",
    "KRE":  "Reg. Banks",
    "IHI":  "Med Devices",
    "IGV":  "Software",
    "KWEB": "China Tech",
    "CIBR": "Cybersec",
    "BETZ": "Sports Bet",
    "AIQ":  "AI & Big Data",
    "QTUM": "Quantum/AI",
    "SLX":  "Steel",
    "SMH":  "Semis",
    "JETS": "Airlines",
    "IYT":  "Transport",
    "TAN":  "Solar",
    "ARKG": "Genomics",
    "IBIT": "Bitcoin",
    "VUG":  "Growth",
    "GDX":  "Gold Miners",
    "SIL":  "Silver Min.",
}

# ── Color palettes ───────────────────────────────────────────────────────────
SECTOR_COLORS = [
    "#00d4ff", "#ff6b6b", "#51cf66", "#ffd43b", "#cc5de8",
    "#ff922b", "#20c997", "#e599f7", "#74c0fc", "#f783ac", "#ced4da",
]

SUBSECTOR_COLORS = [
    "#00d4ff", "#ff6b6b", "#51cf66", "#ffd43b", "#cc5de8",
    "#ff922b", "#20c997", "#e599f7", "#74c0fc", "#f783ac",
    "#ced4da", "#a9e34b", "#f06595", "#845ef7", "#22b8cf",
    "#fab005", "#fd7e14", "#82c91e", "#be4bdb", "#4dabf7",
    "#e64980", "#15aabf", "#7950f2", "#12b886", "#fcc419",
    "#ff8787", "#da77f2", "#748ffc", "#63e6be", "#ffa94d", "#adb5bd",
]


# ── Yahoo chart API ──────────────────────────────────────────────────────────
YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def get_last_friday() -> date:
    """Return the most recent completed Friday (today if today is Friday)."""
    today = date.today()
    days_back = (today.weekday() - 4) % 7   # weekday(): Mon=0 … Fri=4
    return today - timedelta(days=days_back)


def clip_to_last_friday(
    timestamps: list[int], closes: list[float], interval: str
) -> list[float]:
    """
    Trim data to only include complete bars through the last Friday close.

    Daily (1d):  bar_end = bar_date             → include if bar_date <= last_friday
    Weekly (1wk): bar_end = bar_date + 4 days  → include if bar_date + 4d <= last_friday
                  (Yahoo weekly timestamps = Monday of that week)
    """
    last_fri = get_last_friday()
    offset = timedelta(days=4) if interval == "1wk" else timedelta(days=0)
    result = []
    for ts, c in zip(timestamps, closes):
        bar_date = date.fromtimestamp(ts)
        if bar_date + offset <= last_fri:
            result.append(c)
    return result


def fetch_closes(
    ticker: str, range_: str = "6mo", interval: str = "1d"
) -> tuple[list[int], list[float]]:
    """Fetch closing prices + timestamps for a single ticker from Yahoo chart API."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?range={range_}&interval={interval}"
    )
    try:
        resp = requests.get(url, headers=YAHOO_HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  {ticker}: HTTP {resp.status_code}", file=sys.stderr)
            return [], []
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return [], []
        timestamps = result[0]["timestamp"]
        closes = result[0]["indicators"]["quote"][0]["close"]
        pairs = [(ts, c) for ts, c in zip(timestamps, closes) if c is not None]
        return [p[0] for p in pairs], [p[1] for p in pairs]
    except Exception as e:
        print(f"  {ticker}: fetch error: {e}", file=sys.stderr)
        return [], []


def fetch_all_closes(
    tickers: list[str], range_: str = "6mo", interval: str = "1d"
) -> dict[str, list[float]]:
    """Fetch closes for multiple tickers in parallel, clipped to last Friday."""
    results = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(fetch_closes, t, range_, interval): t for t in tickers
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                timestamps, closes = future.result()
                if closes:
                    clipped = clip_to_last_friday(timestamps, closes, interval)
                    if clipped:
                        results[ticker] = clipped
            except Exception as e:
                print(f"  {ticker}: error: {e}", file=sys.stderr)
    return results


# ── RRG math ─────────────────────────────────────────────────────────────────
def compute_rrg_series(
    ticker_closes: list[float],
    benchmark_closes: list[float],
) -> tuple[list[float], list[float]]:
    """
    Compute JdK RS-Ratio and RS-Momentum series using the EMA-ratio method.

    This matches the StockCharts / Julius de Kempenaer implementation:
      RS-Ratio   = EMA(RS_line, RS_SHORT) / EMA(RS_line, RS_LONG) × 100
      RS-Momentum = EMA(RS-Ratio, RS_SHORT) / EMA(RS-Ratio, RS_LONG) × 100

    Both are centered at 100 (100 = neutral, >100 = bullish, <100 = bearish).
    Requires RS_LONG * ~2 bars of history to fully warm up the EMAs.
    """
    min_len = min(len(ticker_closes), len(benchmark_closes))
    tc = np.array(ticker_closes[-min_len:], dtype=float)
    bc = np.array(benchmark_closes[-min_len:], dtype=float)

    # Raw relative strength line (indexed to 100)
    rs_line = pd.Series(tc / bc * 100)

    # RS-Ratio: short EMA vs long EMA of the RS line
    ema_s = rs_line.ewm(span=RS_SHORT, adjust=False).mean()
    ema_l = rs_line.ewm(span=RS_LONG,  adjust=False).mean()
    rs_ratio = (ema_s / ema_l) * 100

    # RS-Momentum: short EMA vs long EMA of the RS-Ratio series
    mom_ema_s = rs_ratio.ewm(span=RS_SHORT, adjust=False).mean()
    mom_ema_l = rs_ratio.ewm(span=RS_LONG,  adjust=False).mean()
    rs_mom = (mom_ema_s / mom_ema_l) * 100

    return rs_ratio.tolist(), rs_mom.tolist()


def compute_rrg_points(
    tickers: dict[str, str],
    data: dict[str, list[float]],
    benchmark_closes: list[float],
) -> dict[str, list[tuple[float, float]]]:
    """
    For each ticker, compute the last (TAIL_LENGTH+1) RRG (ratio, momentum) points.
    Returns {ticker: [(ratio, mom), ...]} — oldest first.
    """
    points = {}
    for ticker in tickers:
        closes = data.get(ticker)
        if not closes:
            continue
        rs_ratio, rs_mom = compute_rrg_series(closes, benchmark_closes)
        # Collect last TAIL_LENGTH+1 valid points
        valid = [
            (rs_ratio[i], rs_mom[i])
            for i in range(len(rs_ratio))
            if not (np.isnan(rs_ratio[i]) or np.isnan(rs_mom[i]))
        ]
        if len(valid) < 2:
            continue
        tail = valid[-(TAIL_LENGTH + 1) :]
        points[ticker] = tail
    return points


# ── Chart rendering ──────────────────────────────────────────────────────────
def render_rrg_chart(
    rrg_points: dict[str, list[tuple[float, float]]],
    ticker_names: dict[str, str],
    title: str,
    colors: list[str],
) -> io.BytesIO:
    """Render a 4-quadrant RRG scatter chart. Returns PNG BytesIO buffer."""
    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    # Determine axis bounds symmetrically around 100
    all_x, all_y = [], []
    for pts in rrg_points.values():
        for x, y in pts:
            all_x.append(x)
            all_y.append(y)

    if not all_x:
        buf = io.BytesIO()
        plt.close(fig)
        return buf

    margin = 0.5
    max_dev = max(
        max(abs(v - 100) for v in all_x),
        max(abs(v - 100) for v in all_y),
        1.5,  # minimum range
    ) + margin
    ax.set_xlim(100 - max_dev, 100 + max_dev)
    ax.set_ylim(100 - max_dev, 100 + max_dev)

    # Quadrant shading
    quad_alpha = 0.08
    ax.axhspan(100, 100 + max_dev, xmin=0.5, xmax=1.0, color="#51cf66", alpha=quad_alpha)   # Leading (top-right)
    ax.axhspan(100, 100 + max_dev, xmin=0.0, xmax=0.5, color="#74c0fc", alpha=quad_alpha)   # Improving (top-left)
    ax.axhspan(100 - max_dev, 100, xmin=0.5, xmax=1.0, color="#ffd43b", alpha=quad_alpha)   # Weakening (bottom-right)
    ax.axhspan(100 - max_dev, 100, xmin=0.0, xmax=0.5, color="#ff6b6b", alpha=quad_alpha)   # Lagging (bottom-left)

    # Quadrant labels
    label_style = dict(fontsize=9, alpha=0.35, fontweight="bold", color="white")
    ax.text(100 + max_dev * 0.75, 100 + max_dev * 0.9, "LEADING", ha="center", **label_style)
    ax.text(100 - max_dev * 0.75, 100 + max_dev * 0.9, "IMPROVING", ha="center", **label_style)
    ax.text(100 + max_dev * 0.75, 100 - max_dev * 0.9, "WEAKENING", ha="center", **label_style)
    ax.text(100 - max_dev * 0.75, 100 - max_dev * 0.9, "LAGGING", ha="center", **label_style)

    # Center gridlines
    ax.axhline(100, color="white", alpha=0.3, linewidth=0.8)
    ax.axvline(100, color="white", alpha=0.3, linewidth=0.8)

    # Plot each ticker
    sorted_tickers = sorted(rrg_points.keys())
    for idx, ticker in enumerate(sorted_tickers):
        pts = rrg_points[ticker]
        color = colors[idx % len(colors)]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]

        # Trailing tail with fading alpha
        for i in range(len(xs) - 1):
            alpha = 0.15 + 0.7 * (i / max(len(xs) - 1, 1))
            ax.plot(
                xs[i : i + 2], ys[i : i + 2],
                color=color, alpha=alpha, linewidth=1.5,
            )
            ax.scatter(xs[i], ys[i], color=color, alpha=alpha, s=15, zorder=3)

        # Current position (larger dot)
        ax.scatter(xs[-1], ys[-1], color=color, s=60, zorder=5, edgecolors="white", linewidths=0.5)

        # Label at current position
        label = ticker
        ax.annotate(
            label,
            (xs[-1], ys[-1]),
            textcoords="offset points",
            xytext=(6, 6),
            fontsize=7,
            color=color,
            fontweight="bold",
            path_effects=[pe.withStroke(linewidth=2, foreground="#1a1a2e")],
        )

    # Axes styling
    ax.set_xlabel("JdK RS-Ratio →", color="white", fontsize=10)
    ax.set_ylabel("JdK RS-Momentum →", color="white", fontsize=10)
    ax.set_title(title, color="white", fontsize=13, fontweight="bold", pad=12)
    ax.tick_params(colors="white", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#444")

    ax.grid(True, alpha=0.1, color="white")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor="#1a1a2e")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── Quadrant classification & text summary ───────────────────────────────────
def classify_quadrant(x: float, y: float) -> str:
    if x >= 100 and y >= 100:
        return "Leading"
    elif x >= 100 and y < 100:
        return "Weakening"
    elif x < 100 and y >= 100:
        return "Improving"
    else:
        return "Lagging"


def build_text_summary(
    rrg_points: dict[str, list[tuple[float, float]]],
    ticker_names: dict[str, str],
    group_label: str,
    benchmark_name: str,
) -> str:
    """Build a text summary of quadrant positions."""
    quadrants = {"Leading": [], "Weakening": [], "Lagging": [], "Improving": []}

    for ticker, pts in sorted(rrg_points.items()):
        x, y = pts[-1]
        q = classify_quadrant(x, y)
        quadrants[q].append(f"{ticker}({ticker_names.get(ticker, ticker)})")

    lines = [f"**RRG {group_label}** vs {benchmark_name}"]
    for q_name, emoji in [("Leading", "+"), ("Improving", "^"), ("Weakening", "v"), ("Lagging", "-")]:
        members = quadrants[q_name]
        if members:
            lines.append(f"  [{emoji}] {q_name}: {', '.join(members)}")

    return "\n".join(lines)


# ── Discord posting ──────────────────────────────────────────────────────────
def send_discord_message(text: str):
    if len(text) > 1950:
        text = text[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": text}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Discord text send failed: {e}")


def send_discord_image(buf: io.BytesIO, filename: str):
    try:
        resp = requests.post(
            DISCORD_WEBHOOK_URL,
            files={"file": (filename, buf, "image/png")},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Discord image send failed: {e}")


# ── Modular RRG runner ───────────────────────────────────────────────────────
def run_rrg(
    tickers: dict[str, str],
    benchmark: str,
    benchmark_name: str,
    group_label: str,
    colors: list[str],
):
    """
    Run RRG analysis for a group of tickers vs a benchmark.
    Produces daily + weekly charts and posts to Discord.
    """
    all_tickers = list(tickers.keys()) + [benchmark]

    # ── Daily (1y, 1d) ─────────────────────────────────────────────────
    # 1y (~252 days) ensures EMA(26) is well warmed-up (needs ~52+ bars)
    print(f"  Fetching daily data for {group_label} ({len(all_tickers)} tickers)...")
    daily_data = fetch_all_closes(all_tickers, range_="1y", interval="1d")
    bench_daily = daily_data.get(benchmark)

    if not bench_daily:
        print(f"  ERROR: No benchmark data for {benchmark} (daily)", file=sys.stderr)
        return

    daily_points = compute_rrg_points(tickers, daily_data, bench_daily)
    print(f"  Daily: {len(daily_points)}/{len(tickers)} tickers computed")

    last_fri = get_last_friday()
    last_fri_str = last_fri.strftime("%b %d, %Y")

    if daily_points:
        daily_chart = render_rrg_chart(
            daily_points, tickers,
            f"RRG — {group_label} vs {benchmark_name} (Daily, as of {last_fri_str})",
            colors,
        )
        daily_summary = build_text_summary(daily_points, tickers, f"{group_label} Daily", benchmark_name)
    else:
        daily_chart = None
        daily_summary = f"No daily RRG data for {group_label}"

    # Brief pause before weekly fetch
    time.sleep(1)

    # ── Weekly (3y, 1wk) ────────────────────────────────────────────────
    # 3y (~156 weeks) ensures EMA(26) is well warmed-up (needs ~52+ bars)
    print(f"  Fetching weekly data for {group_label}...")
    weekly_data = fetch_all_closes(all_tickers, range_="3y", interval="1wk")
    bench_weekly = weekly_data.get(benchmark)

    if not bench_weekly:
        print(f"  ERROR: No benchmark data for {benchmark} (weekly)", file=sys.stderr)
        return

    weekly_points = compute_rrg_points(tickers, weekly_data, bench_weekly)
    print(f"  Weekly: {len(weekly_points)}/{len(tickers)} tickers computed")

    if weekly_points:
        weekly_chart = render_rrg_chart(
            weekly_points, tickers,
            f"RRG — {group_label} vs {benchmark_name} (Weekly, week ending {last_fri_str})",
            colors,
        )
        weekly_summary = build_text_summary(weekly_points, tickers, f"{group_label} Weekly", benchmark_name)
    else:
        weekly_chart = None
        weekly_summary = f"No weekly RRG data for {group_label}"

    # ── Post to Discord ─────────────────────────────────────────────────
    now_et = datetime.now(ET)
    header = f"**RRG Scanner — {group_label}** ({now_et.strftime('%a %b %d %I:%M %p ET')})\n"
    full_text = header + daily_summary + "\n\n" + weekly_summary
    send_discord_message(full_text)
    print(f"  Posted text summary ({len(full_text)} chars)")

    if daily_chart:
        send_discord_image(daily_chart, f"rrg_{group_label.lower().replace(' ', '_')}_daily.png")
        print("  Posted daily chart")
        time.sleep(1)

    if weekly_chart:
        send_discord_image(weekly_chart, f"rrg_{group_label.lower().replace(' ', '_')}_weekly.png")
        print("  Posted weekly chart")


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting RRG Scanner")

    # Run sectors vs SPY
    run_rrg(
        tickers=SECTOR_ETFS,
        benchmark="SPY",
        benchmark_name="SPY",
        group_label="Sectors",
        colors=SECTOR_COLORS,
    )

    time.sleep(2)

    # Run EW sectors vs RSP (equal-weight benchmark)
    run_rrg(
        tickers=EW_SECTOR_ETFS,
        benchmark="RSP",
        benchmark_name="RSP",
        group_label="EW Sectors",
        colors=SECTOR_COLORS,
    )

    time.sleep(2)

    # Run subsectors vs SPY
    run_rrg(
        tickers=SUBSECTOR_ETFS,
        benchmark="SPY",
        benchmark_name="SPY",
        group_label="Subsectors",
        colors=SUBSECTOR_COLORS,
    )

    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} RRG Scanner complete")


if __name__ == "__main__":
    main()
