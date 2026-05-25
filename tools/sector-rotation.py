"""
Sector Rotation Flow Tracker
Tracks 11 SPDR sector ETFs + 26 subsector/thematic ETFs to detect money
rotating between sectors and themes.

Methodology:
  - Track 1-week vs 4-week performance for all sectors & subsectors
  - Classify each: ACCELERATING (1W > 4W), DECELERATING, WEAKENING, STABILIZING
  - Detect rotation: money moving from defensive (XLU, XLP, XLV) to cyclical (XLI, XLY, XLF)
  - Compare to SPY for relative flow direction

Cost: $0.00 (Yahoo chart API, no API key needed)
"""

import requests
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

SECTORS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLP": "Cons. Staples",
    "XLY": "Cons. Discret.",
    "XLU": "Utilities",
    "XLC": "Comms",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "IBB": "Biotech"
}

SUBSECTORS = {
    "SMH":  "Semis",
    "IGV":  "Software",
    "CIBR": "Cybersec",
    "AIQ":  "AI & Big Data",
    "QTUM": "Quantum/AI",
    "BOTZ": "Robotics",
    "IBB":  "Biotech",
    "BBC": "Biotech2",
    "IHI":  "Med Devices",
    "ARKG": "Genomics",
    "KRE":  "Reg. Banks",
    "ITB":  "Homebuilders",
    "VNQ":  "REITs",
    "XRT":  "Retail",
    "ITA":  "Aerospace",
    "IYT":  "Transport",
    "JETS": "Airlines",
    "SLX":  "Steel",
    "GDX":  "Gold Miners",
    "SIL":  "Silver Min.",
    "TAN":  "Solar",
    "KWEB": "China Tech",
    "SOCL": "Social Media",
    "IYZ":  "Telecom",
    "BETZ": "Sports Bet",
    "IBIT": "Bitcoin",
    "VUG":  "Growth",
    "PICK": "Metals and Mining",
    "MEDI": "Healthcare",
    "XME": "Metals and Mining2",
    "BOAT": "Global Shipping ETF",
    "VEGI": "Agriculture",
    "PDBC": "Hedge"
}

EW_SECTORS = {
    "RSPT": "Technology",
    "RSPF": "Financials",
    "RSPG": "Energy",
    "RSPH": "Health Care",
    "RSPN": "Industrials",
    "RSPS": "Cons. Staples",
    "RSPD": "Cons. Discret.",
    "RSPU": "Utilities",
    "RSPC": "Comms",
    "RSPM": "Materials",
    "RSPR": "Real Estate",
    "IBB": "Biotech"
}

# Mapping from EW ETF to cap-weight ETF for side-by-side comparison
EW_TO_CW = {
    "RSPT": "XLK", "RSPF": "XLF", "RSPG": "XLE", "RSPH": "XLV",
    "RSPN": "XLI", "RSPS": "XLP", "RSPD": "XLY", "RSPU": "XLU",
    "RSPC": "XLC", "RSPM": "XLB", "RSPR": "XLRE", "XBI": "IBB",
}

CYCLICAL = {"XLK", "XLF", "XLI", "XLY", "XLC", "XLB"}
DEFENSIVE = {"XLU", "XLP", "XLV", "XLRE"}

# Discord webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1470444998011916423/oME5DBVEBixjtSkJoYddSv4QG5EGQNSZMyKak5Zt8LehjQ_3b7jpj14t9U2JEhnPE9pI"

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def send_discord(message: str):
    """Send message to Discord via webhook."""
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Send failed: {e}")


def fetch_ticker_closes(ticker: str) -> list[float]:
    """Fetch 2 months of daily closes from Yahoo Finance chart API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=2mo&interval=1d"
    try:
        resp = requests.get(url, headers=YAHOO_HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return []
        closes = result[0]["indicators"]["quote"][0]["close"]
        return [c for c in closes if c is not None]
    except Exception as e:
        print(f"  {ticker}: fetch error: {e}")
        return []


def fetch_all_tickers(
    ticker_names: dict[str, str],
    benchmarks: dict | None = None,
) -> tuple[dict, dict]:
    """Fetch all tickers + benchmarks (SPY, RSP) via Yahoo chart API.
    Returns (results_dict, benchmarks_dict).
    If benchmarks is provided, reuses it (skip re-fetching)."""
    tickers = list(ticker_names.keys())
    need_benchmarks = benchmarks is None
    if need_benchmarks:
        tickers.extend(["SPY", "RSP"])

    raw = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fetch_ticker_closes, t): t for t in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                closes = future.result()
                if closes and len(closes) >= 10:
                    raw[ticker] = closes
                elif closes:
                    print(f"  {ticker}: insufficient data ({len(closes)} points)")
            except Exception as e:
                print(f"  {ticker}: error: {e}")

    all_names = {**ticker_names, "SPY": "SPY", "RSP": "RSP"}
    results = {}
    for ticker, closes in raw.items():
        price = closes[-1]
        ret_1w = float((price / closes[-6] - 1) * 100) if len(closes) >= 6 else 0
        ret_4w = float((price / closes[-21] - 1) * 100) if len(closes) >= 21 else ret_1w
        results[ticker] = {
            "ticker": ticker,
            "name": all_names.get(ticker, ticker),
            "price": round(float(price), 2),
            "ret_1w": round(ret_1w, 2),
            "ret_4w": round(ret_4w, 2),
        }

    if need_benchmarks:
        fetched_benchmarks = {}
        for bm in ("SPY", "RSP"):
            if bm in results:
                fetched_benchmarks[bm] = results.pop(bm)
        if "SPY" not in fetched_benchmarks:
            fetched_benchmarks = None
    else:
        fetched_benchmarks = benchmarks

    print(f"  Fetched {len(results)}/{len(ticker_names)} tickers")
    return results, fetched_benchmarks


def classify_momentum(ret_1w: float, ret_4w: float) -> str:
    """Classify sector momentum phase."""
    weekly_rate = ret_4w / 4 if ret_4w != 0 else 0

    if ret_1w > 0 and ret_1w > weekly_rate:
        return "ACCELERATING"
    elif ret_1w > 0 and ret_1w <= weekly_rate:
        return "DECELERATING"
    elif ret_1w < 0 and ret_1w < weekly_rate:
        return "WEAKENING"
    else:
        return "STABILIZING"


def enrich_results(
    ticker_names: dict,
    data: dict,
    spy_1w: float,
    spy_4w: float,
    rsp_1w: float | None = None,
    rsp_4w: float | None = None,
) -> list[dict]:
    """Add RS vs SPY, RS vs RSP, and momentum classification to fetched data."""
    results = []
    for ticker in ticker_names:
        d = data.get(ticker)
        if d:
            d["rs_1w"] = round(d["ret_1w"] - spy_1w, 2)
            d["rs_4w"] = round(d["ret_4w"] - spy_4w, 2)
            if rsp_1w is not None:
                d["rsp_rs_1w"] = round(d["ret_1w"] - rsp_1w, 2)
                d["rsp_rs_4w"] = round(d["ret_4w"] - rsp_4w, 2)
            d["momentum"] = classify_momentum(d["ret_1w"], d["ret_4w"])
            results.append(d)
    results.sort(key=lambda x: x["rs_1w"], reverse=True)
    return results


def build_table(results: list[dict], name_col: str = "Sector", col_width: int = 15, has_rsp: bool = False) -> str:
    """Build a monospace table from results."""
    lines = []
    if has_rsp:
        lines.append(f"{'ETF':<5} {name_col:<{col_width}} {'1W':>6} {'4W':>6} {'vSPY':>6} {'vRSP':>6}  Phase")
        lines.append("-" * (43 + col_width))
    else:
        lines.append(f"{'ETF':<5} {name_col:<{col_width}} {'1W':>6} {'4W':>6} {'RS(1W)':>7}  Phase")
        lines.append("-" * (38 + col_width))
    for r in results:
        phase_short = {
            "ACCELERATING": "ACCEL",
            "DECELERATING": "DECEL",
            "WEAKENING": "WEAK",
            "STABILIZING": "STAB",
        }.get(r["momentum"], "?")
        if has_rsp and "rsp_rs_1w" in r:
            lines.append(
                f"{r['ticker']:<5} {r['name']:<{col_width}} {r['ret_1w']:>+6.1f} {r['ret_4w']:>+6.1f} "
                f"{r['rs_1w']:>+6.1f} {r['rsp_rs_1w']:>+6.1f}  {phase_short}"
            )
        else:
            lines.append(
                f"{r['ticker']:<5} {r['name']:<{col_width}} {r['ret_1w']:>+6.1f} {r['ret_4w']:>+6.1f} "
                f"{r['rs_1w']:>+7.1f}  {phase_short}"
            )
    return "\n".join(lines)


def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting sector rotation analysis")

    # ── Fetch sectors + SPY + RSP ────────────────────────────────────────
    sector_data, benchmarks = fetch_all_tickers(SECTORS)
    if not sector_data or not benchmarks or "SPY" not in benchmarks:
        print("No sector data fetched")
        return

    spy_entry = benchmarks["SPY"]
    rsp_entry = benchmarks.get("RSP")
    spy_1w = spy_entry["ret_1w"]
    spy_4w = spy_entry["ret_4w"]
    rsp_1w = rsp_entry["ret_1w"] if rsp_entry else None
    rsp_4w = rsp_entry["ret_4w"] if rsp_entry else None
    has_rsp = rsp_entry is not None

    results = enrich_results(SECTORS, sector_data, spy_1w, spy_4w, rsp_1w, rsp_4w)
    for r in results:
        r["is_cyclical"] = r["ticker"] in CYCLICAL

    if not results:
        print("No sector data fetched")
        return

    # Rotation score (cyclical vs defensive)
    cyc = [r for r in results if r["is_cyclical"]]
    dfs = [r for r in results if not r["is_cyclical"]]
    cyclical_avg = sum(r["ret_1w"] for r in cyc) / max(1, len(cyc))
    defensive_avg = sum(r["ret_1w"] for r in dfs) / max(1, len(dfs))
    rotation_score = round(cyclical_avg - defensive_avg, 2)

    if rotation_score > 1.0:
        rotation_dir = "RISK-ON (cyclicals leading)"
    elif rotation_score < -1.0:
        rotation_dir = "RISK-OFF (defensives leading)"
    else:
        rotation_dir = "NEUTRAL (no clear rotation)"

    # SPY vs RSP divergence — shows cap-weight vs equal-weight skew
    spy_rsp_note = ""
    if has_rsp:
        spy_rsp_div = spy_1w - rsp_1w
        if spy_rsp_div > 1.0:
            spy_rsp_note = f" | SPY-RSP gap: {spy_rsp_div:+.1f}% (mega-cap driven)"
        elif spy_rsp_div < -1.0:
            spy_rsp_note = f" | SPY-RSP gap: {spy_rsp_div:+.1f}% (broad strength)"
        else:
            spy_rsp_note = f" | SPY-RSP gap: {spy_rsp_div:+.1f}% (balanced)"

    # Build sector message
    lines = [f"**Sector Rotation** ({now_et.strftime('%a %b %d')})", ""]
    bm_line = f"SPY: 1W={spy_1w:+.1f}% | 4W={spy_4w:+.1f}%"
    if has_rsp:
        bm_line += f"  ||  RSP: 1W={rsp_1w:+.1f}% | 4W={rsp_4w:+.1f}%"
    lines.append(bm_line)
    lines.append(f"Rotation: **{rotation_dir}** (score: {rotation_score:+.1f}){spy_rsp_note}")
    lines.append("")
    lines.append("```")
    lines.append(build_table(results, "Sector", 15, has_rsp=has_rsp))
    lines.append("```")
    if has_rsp:
        lines.append("vSPY=RS vs SPY (cap-wt) | vRSP=RS vs RSP (equal-wt)")
    lines.append("")

    top_3 = results[:3]
    bot_3 = results[-3:]
    inflow_str = ", ".join(f"{r['ticker']}({r['name']})" for r in top_3)
    outflow_str = ", ".join(f"{r['ticker']}({r['name']})" for r in bot_3)
    lines.append(f"Inflows: {inflow_str}")
    lines.append(f"Outflows: {outflow_str}")

    accel = [r for r in results if r["momentum"] == "ACCELERATING"]
    if accel:
        lines.append(f"Accelerating: {', '.join(r['ticker'] for r in accel)}")

    # Flag sectors where SPY RS and RSP RS disagree significantly
    if has_rsp:
        divergent = []
        for r in results:
            spy_rs = r["rs_1w"]
            rsp_rs = r.get("rsp_rs_1w", spy_rs)
            diff = spy_rs - rsp_rs
            if abs(diff) > 1.5:
                direction = "looks weaker vs RSP" if diff > 0 else "looks stronger vs RSP"
                divergent.append(f"{r['ticker']}({direction})")
        if divergent:
            lines.append(f"SPY/RSP divergence: {', '.join(divergent)}")

    message = "\n".join(lines)
    send_discord(message)
    print(f"  Posted sector rotation ({len(message)} chars)")

    # ── Fetch subsectors (reuse benchmark data) ──────────────────────────
    print("  Fetching subsector data...")
    sub_data, _ = fetch_all_tickers(SUBSECTORS, benchmarks=benchmarks)

    if not sub_data:
        print("  No subsector data fetched")
    else:
        sub_results = enrich_results(SUBSECTORS, sub_data, spy_1w, spy_4w, rsp_1w, rsp_4w)

        if sub_results:
            sub_lines = [f"**Subsector Rotation** ({now_et.strftime('%a %b %d')})", ""]
            sub_lines.append("```")
            sub_lines.append(build_table(sub_results, "Theme", 14, has_rsp=has_rsp))
            sub_lines.append("```")
            if has_rsp:
                sub_lines.append("vSPY=RS vs SPY | vRSP=RS vs RSP (equal-wt)")
            sub_lines.append("")

            sub_top = sub_results[:5]
            sub_bot = sub_results[-5:]
            sub_in = ", ".join(f"{r['ticker']}({r['name']})" for r in sub_top)
            sub_out = ", ".join(f"{r['ticker']}({r['name']})" for r in sub_bot)
            sub_lines.append(f"Inflows: {sub_in}")
            sub_lines.append(f"Outflows: {sub_out}")

            sub_accel = [r for r in sub_results if r["momentum"] == "ACCELERATING"]
            if sub_accel:
                sub_lines.append(f"Accelerating: {', '.join(r['ticker'] for r in sub_accel)}")

            sub_message = "\n".join(sub_lines)

            # Split if over 2000 chars
            if len(sub_message) > 1950:
                split_idx = sub_message.find("```\n\n") + 3
                send_discord(sub_message[:split_idx])
                send_discord(sub_message[split_idx:])
                print(f"  Posted subsector rotation ({len(sub_message)} chars, split)")
            else:
                send_discord(sub_message)
                print(f"  Posted subsector rotation ({len(sub_message)} chars)")

    # ── Fetch EW sectors (reuse benchmark data) ────────────────────────
    print("  Fetching equal-weight sector data...")
    ew_data, _ = fetch_all_tickers(EW_SECTORS, benchmarks=benchmarks)

    if not ew_data:
        print("  No EW sector data fetched")
    else:
        ew_results = enrich_results(EW_SECTORS, ew_data, spy_1w, spy_4w, rsp_1w, rsp_4w)

        if ew_results:
            ew_lines = [f"**Equal-Weight Sectors** ({now_et.strftime('%a %b %d')})", ""]

            # Show CW vs EW divergence per sector
            ew_lines.append("Cap-wt vs Equal-wt divergence (same sector):")
            ew_lines.append("```")
            ew_lines.append(f"{'Sector':<14} {'CW 1W':>7} {'EW 1W':>7} {'Gap':>6}  Note")
            ew_lines.append("-" * 52)
            for ew_r in ew_results:
                ew_ticker = ew_r["ticker"]
                cw_ticker = EW_TO_CW.get(ew_ticker)
                cw_match = next((r for r in results if r["ticker"] == cw_ticker), None) if cw_ticker else None
                if cw_match:
                    gap = cw_match["ret_1w"] - ew_r["ret_1w"]
                    if abs(gap) > 1.5:
                        note = "NARROW" if gap > 0 else "BROAD"
                    else:
                        note = ""
                    ew_lines.append(
                        f"{ew_r['name']:<14} {cw_match['ret_1w']:>+7.1f} {ew_r['ret_1w']:>+7.1f} {gap:>+6.1f}  {note}"
                    )
            ew_lines.append("```")
            ew_lines.append("Gap = CW - EW | NARROW = mega-cap driven | BROAD = equal-weight stronger")
            ew_lines.append("")

            ew_lines.append("```")
            ew_lines.append(build_table(ew_results, "EW Sector", 14, has_rsp=has_rsp))
            ew_lines.append("```")

            ew_message = "\n".join(ew_lines)

            if len(ew_message) > 1950:
                split_idx = ew_message.find("Gap = CW")
                send_discord(ew_message[:split_idx])
                send_discord(ew_message[split_idx:])
                print(f"  Posted EW sectors ({len(ew_message)} chars, split)")
            else:
                send_discord(ew_message)
                print(f"  Posted EW sectors ({len(ew_message)} chars)")

    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} Sector rotation complete")


if __name__ == "__main__":
    main()
