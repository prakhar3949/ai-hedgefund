#!/home/nicknemo17/clawd/venv/bin/python
"""
Estimate Revision Tracker
Weekly snapshot of analyst estimates, tracks direction of revisions over time.

Posts weekly to #research (Monday morning).
Schedule: 6:30 AM PST Mondays

Methodology:
  - Fetches analyst estimates for all holdings via dexter-data.ts
  - Stores weekly snapshots in ~/clawd/memory/estimate-snapshots.json
  - Compares current estimates to previous week
  - Detects: upward revisions, downward revisions, large moves
  - Estimate revisions are one of the strongest alpha signals in quant finance

Cost: $0.00 (Tier 1 — direct API only, no LLM)
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
CLAWD = Path.home() / "clawd"
SNAPSHOT_FILE = CLAWD / "memory/estimate-snapshots.json"
DEXTER_RUN = CLAWD / "tools/dexter-run.sh"

# Load channel IDs
CHANNELS = {}
try:
    with open(CLAWD / "tools/discord-channels.sh") as f:
        for line in f:
            if line.startswith("DISCORD_") and "=" in line:
                key, val = line.split("=", 1)
                val = val.strip()
                if val.startswith('"'):
                    val = val[1:val.index('"', 1)]
                else:
                    val = val.split()[0].split("#")[0].strip()
                CHANNELS[key.strip()] = val
except:
    pass

RESEARCH_CH = CHANNELS.get("DISCORD_RESEARCH", "1468773228791992494")


_pending_sends = []


def send_discord(channel_id: str, message: str):
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        proc = subprocess.Popen(
            ["clawdbot", "message", "send",
             "--channel", "discord",
             "--target", f"channel:{channel_id}",
             "--message", message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _pending_sends.append(proc)
    except:
        pass


def flush_sends(timeout: int = 15):
    for proc in _pending_sends:
        try:
            proc.wait(timeout=timeout)
        except:
            pass
    _pending_sends.clear()


def fetch_estimates(ticker: str) -> dict | None:
    """Fetch analyst estimates via dexter-data.ts (zero LLM cost)."""
    try:
        result = subprocess.run(
            [str(DEXTER_RUN), "data", "analyst-estimates", ticker, "quarterly", "4"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None

        raw = json.loads(result.stdout)
        # API returns {"data": [...]} wrapper
        estimates = raw.get("data", raw) if isinstance(raw, dict) else raw
        if not estimates:
            return None

        # Find future quarters (fiscal_period > today)
        now = datetime.now(ET)
        today_str = now.strftime("%Y-%m-%d")
        future = [e for e in estimates if e.get("fiscal_period", "") >= today_str]
        if not future:
            future = estimates[:2]

        result_data = {"ticker": ticker}
        for i, est in enumerate(future[:2]):
            prefix = "nq" if i == 0 else "nq2"
            result_data[f"{prefix}_date"] = est.get("fiscal_period", "")
            result_data[f"{prefix}_eps"] = est.get("earnings_per_share")

        return result_data

    except Exception as e:
        print(f"  Error fetching estimates for {ticker}: {e}")
        return None


def load_snapshots() -> dict:
    try:
        with open(SNAPSHOT_FILE) as f:
            return json.load(f)
    except:
        return {"snapshots": []}


def save_snapshots(data: dict):
    # Keep last 12 weeks
    data["snapshots"] = data["snapshots"][-12:]
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def compute_revisions(current: dict, previous: dict) -> list[dict]:
    """Compare current estimates to previous week, find revisions."""
    revisions = []
    for ticker, curr in current.items():
        prev = previous.get(ticker)
        if not prev:
            continue

        for prefix, label in [("nq", "Next Q"), ("nq2", "Q+2")]:
            curr_eps = curr.get(f"{prefix}_eps")
            prev_eps = prev.get(f"{prefix}_eps")

            if curr_eps is None or prev_eps is None or prev_eps == 0:
                continue

            eps_chg = curr_eps - prev_eps
            eps_chg_pct = (eps_chg / abs(prev_eps)) * 100

            if abs(eps_chg_pct) < 0.5:
                continue  # ignore tiny changes

            revisions.append({
                "ticker": ticker,
                "period": label,
                "date": curr.get(f"{prefix}_date", ""),
                "eps_prev": prev_eps,
                "eps_curr": curr_eps,
                "eps_chg": round(eps_chg, 3),
                "eps_chg_pct": round(eps_chg_pct, 1),
                "direction": "UP" if eps_chg > 0 else "DOWN",
            })

    return revisions


def main():
    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Starting estimate revision tracker")

    # Load holdings
    with open(CLAWD / "memory/watchlist.json") as f:
        wl = json.load(f)
    holdings = {t: h for t, h in wl.get("stocks", {}).get("holdings", {}).items()
                if h.get("weight") and h["weight"] > 0}

    # Fetch current estimates — parallel for speed
    from concurrent.futures import ThreadPoolExecutor, as_completed

    current_estimates = {}
    def _fetch(t):
        return t, fetch_estimates(t)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_fetch, t) for t in holdings]
        for f in as_completed(futures):
            ticker, est = f.result()
            if est:
                current_estimates[ticker] = est
                print(f"  {ticker}: NQ EPS={est.get('nq_eps', 'N/A')}")
            else:
                print(f"  {ticker}: no estimates available")

    if not current_estimates:
        print("No estimates fetched")
        return

    # Load previous snapshots
    snap_data = load_snapshots()
    prev_snap = snap_data["snapshots"][-1] if snap_data["snapshots"] else None

    # Compute revisions
    revisions = []
    if prev_snap:
        revisions = compute_revisions(current_estimates, prev_snap.get("estimates", {}))
        revisions.sort(key=lambda x: abs(x["eps_chg_pct"]), reverse=True)

    # Save current snapshot
    snap_data["snapshots"].append({
        "date": now_et.strftime("%Y-%m-%d"),
        "estimates": current_estimates,
    })
    save_snapshots(snap_data)

    # Build message
    lines = [f"**Estimate Revisions** ({now_et.strftime('%a %b %d')})", ""]

    if revisions:
        up = [r for r in revisions if r["direction"] == "UP"]
        down = [r for r in revisions if r["direction"] == "DOWN"]

        if up:
            lines.append("**Upward Revisions:**")
            for r in up:
                lines.append(
                    f"  {r['ticker']} ({r['period']}): EPS ${r['eps_prev']:.2f} -> ${r['eps_curr']:.2f} "
                    f"({r['eps_chg_pct']:+.1f}%)"
                )
            lines.append("")

        if down:
            lines.append("**Downward Revisions:**")
            for r in down:
                lines.append(
                    f"  {r['ticker']} ({r['period']}): EPS ${r['eps_prev']:.2f} -> ${r['eps_curr']:.2f} "
                    f"({r['eps_chg_pct']:+.1f}%)"
                )
            lines.append("")

        if not up and not down:
            lines.append("No significant estimate changes this week.")
    else:
        # First run — show current estimates
        lines.append("*First snapshot captured — revisions will be tracked next week.*")
        lines.append("")
        lines.append("```")
        lines.append(f"{'Ticker':<7} {'NQ EPS':>8} {'NQ Date':>11} {'# Analysts':>10}")
        lines.append("-" * 40)
        for ticker, est in sorted(current_estimates.items()):
            eps = est.get("nq_eps")
            date = est.get("nq_date", "")[:10]
            num = est.get("nq_num", "?")
            if eps is not None:
                lines.append(f"{ticker:<7} ${eps:>7.2f} {date:>11} {num:>10}")
        lines.append("```")

    message = "\n".join(lines)
    send_discord(RESEARCH_CH, message)
    print(f"Posted estimate revisions ({len(message)} chars)")

    # Alert on big revisions (>5% EPS change on holdings >5% weight)
    if revisions:
        big_revisions = [r for r in revisions
                         if abs(r["eps_chg_pct"]) >= 5
                         and holdings.get(r["ticker"], {}).get("weight", 0) >= 5]
        if big_revisions:
            alert_lines = [f"**Estimate Alert** ({now_et.strftime('%a %b %d')})", ""]
            for r in big_revisions:
                emoji = "📈" if r["direction"] == "UP" else "📉"
                alert_lines.append(
                    f"{emoji} **{r['ticker']}** {r['period']} EPS revised {r['eps_chg_pct']:+.1f}% "
                    f"(${r['eps_prev']:.2f} -> ${r['eps_curr']:.2f})"
                )
            send_discord(RESEARCH_CH, "\n".join(alert_lines))
            print(f"Posted {len(big_revisions)} big revision alerts")

    # Popen sends complete independently after script exits
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Estimate revision tracker complete")


if __name__ == "__main__":
    main()
