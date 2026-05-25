"""
Economic Release Analysis — polls FRED for new data after releases, posts impact analysis.

Flow:
  1. Checks calendar for today's releases (from macro-calendar.json)
  2. For each release with a fred_id: polls FRED every 2 min until new data appears
  3. On new data: compares to previous, loads model coefficients, predicts impact
  4. Posts analysis to Discord via webhook

Modes:
  - No args (default): poll for 8:30 AM ET releases (runs at 8:32 AM ET)
  - "late": poll for 10:00 AM ET releases + retry 8:30 misses (runs at 10:02 AM ET)
  - "--date YYYY-MM-DD": override date for testing (skips polling, fetches latest)

Cost: $0.00 (Tier 1 — FRED CSV, no LLM)
"""

import io
import json
import sys
import time
import urllib.request
import requests
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")

# Use project directory as base
PROJECT_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

CALENDAR_FILE = MEMORY_DIR / "macro-calendar.json"
MODEL_STATE_FILE = MEMORY_DIR / "econ-model-state.json"
RELEASE_STATE_FILE = MEMORY_DIR / "econ-release-state.json"

# Discord webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1470442159751565419/4fJthzTsNqGNDoCBacARt88JeIhoL9LP-RUiCjT8LyBneCUQ3fQFeL3mbDN27CoCfPKe"


def send_discord(message: str):
    """Send message to Discord via webhook."""
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"Send failed: {e}")


# ─── STATE MANAGEMENT ─────────────────────────────────────────────

def load_release_state() -> dict:
    """Load last-alerted dates per series. Prevents duplicate alerts."""
    try:
        with open(RELEASE_STATE_FILE) as f:
            return json.load(f)
    except:
        return {}


def save_release_state(state: dict):
    try:
        with open(RELEASE_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except:
        pass


def load_model_state() -> dict:
    try:
        with open(MODEL_STATE_FILE) as f:
            return json.load(f)
    except:
        return {}


def load_calendar() -> dict:
    try:
        with open(CALENDAR_FILE) as f:
            data = json.load(f)
        return data.get("events", {})
    except:
        return {}


# ─── FRED POLLING ─────────────────────────────────────────────────

def fetch_fred_latest(series_id: str) -> dict | None:
    """Fetch last 6 months from FRED, return latest observation."""
    start = (datetime.now() - pd.DateOffset(months=6)).strftime("%Y-%m-%d")
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = resp.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(data), parse_dates=["observation_date"])
        df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
        df = df.dropna()
        if df.empty:
            return None
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else None
        result = {
            "date": latest["observation_date"].strftime("%Y-%m-%d"),
            "value": float(latest[series_id]),
        }
        if prev is not None:
            result["prev_date"] = prev["observation_date"].strftime("%Y-%m-%d")
            result["prev_value"] = float(prev[series_id])
        return result
    except Exception as e:
        print(f"  FRED fetch {series_id}: {e}")
        return None


def poll_for_new_data(series_id: str, known_latest_date: str,
                      max_minutes: int = 30, interval_sec: int = 120) -> dict | None:
    """Poll FRED every interval_sec until new data appears or timeout."""
    max_attempts = max(1, max_minutes * 60 // interval_sec)

    for attempt in range(max_attempts):
        if attempt > 0:
            print(f"  {series_id}: attempt {attempt + 1}/{max_attempts}, waiting {interval_sec}s...")
            time.sleep(interval_sec)

        data = fetch_fred_latest(series_id)
        if data and data["date"] > known_latest_date:
            print(f"  {series_id}: NEW DATA detected! {known_latest_date} -> {data['date']}")
            return data
        elif data:
            print(f"  {series_id}: latest still {data['date']} (waiting for > {known_latest_date})")

    print(f"  {series_id}: no new data after {max_minutes} min")
    return None


# ─── ANALYSIS ─────────────────────────────────────────────────────

def compute_change(new_val: float, prev_val: float, transform: str) -> tuple[float, str]:
    """Compute the change and a human-readable description."""
    if transform == "pct":
        chg = (new_val / prev_val - 1) * 100
        return chg, f"{chg:+.2f}% MoM"
    else:
        chg = new_val - prev_val
        return chg, f"{chg:+.1f}"


def analyze_release(event_name: str, fred_id: str, new_data: dict,
                    model: dict) -> tuple[str, str]:
    """
    Analyze a new release. Returns (trade_alert_msg, detailed_msg).
    Uses model coefficients to predict index/sector impact.
    """
    econ = model.get("econ", {}).get(fred_id, {})
    sectors = model.get("sectors", {})
    name = econ.get("name", event_name)
    transform = econ.get("transform", "pct")

    new_val = new_data["value"]
    prev_val = new_data.get("prev_value")

    # Compute current change
    if prev_val:
        chg_val, chg_str = compute_change(new_val, prev_val, transform)
    else:
        chg_val, chg_str = 0, "N/A"

    # Compare to model's stored previous change (direction shift?)
    model_prev_raw = econ.get("latest_raw")
    model_prev_prev = econ.get("prev_raw")
    prev_chg_str = ""
    if model_prev_raw and model_prev_prev:
        if transform == "pct":
            prev_chg = (model_prev_raw / model_prev_prev - 1) * 100
            prev_chg_str = f"{prev_chg:+.2f}%"
        else:
            prev_chg = model_prev_raw - model_prev_prev
            prev_chg_str = f"{prev_chg:+.1f}"

    # Direction assessment
    if prev_val and chg_val != 0:
        if fred_id in ("CPIAUCSL", "CPILFESL", "PCEPI"):
            direction = "HOTTER" if chg_val > 0.01 else "COOLER" if chg_val < -0.01 else "FLAT"
        elif fred_id in ("UNRATE", "ICSA"):
            direction = "WEAKER" if chg_val > 0 else "STRONGER"
        elif fred_id in ("PAYEMS", "MANEMP"):
            direction = "STRONGER" if chg_val > 0 else "WEAKER"
        else:
            direction = "UP" if chg_val > 0 else "DOWN"
    else:
        direction = ""

    # ── Build concise trade alert ──
    alert_lines = [f"**Econ Release: {name}**"]
    alert_lines.append(f"**{chg_str}** {f'(prev: {prev_chg_str})' if prev_chg_str else ''} "
                       f"{'— ' + direction if direction else ''}")

    # Index impact from model
    corrs_1m = econ.get("1m", {})
    if corrs_1m:
        parts = []
        for idx in ["SPY", "QQQ", "IWM"]:
            c = corrs_1m.get(idx, {})
            if c:
                r = c.get("corr", 0)
                t = c.get("t_stat", 0)
                sig = "**" if abs(t) >= 2.0 else "*" if abs(t) >= 1.65 else ""
                signal = "BULL" if r > 0 else "BEAR"
                parts.append(f"{idx}: {signal} (r={r:+.2f}{sig})")
        if parts:
            alert_lines.append("Impact: " + " | ".join(parts))

    trade_msg = "\n".join(alert_lines)

    # ── Build detailed econometrics message ──
    detail_lines = [f"**Economic Release Analysis: {name}** ({new_data['date']})"]
    detail_lines.append("")
    detail_lines.append(f"**New print:** {chg_str} {f'(prev: {prev_chg_str})' if prev_chg_str else ''}")
    if direction:
        detail_lines.append(f"**Direction:** {direction}")
    detail_lines.append("")

    # 1-month and 3-month model predictions
    for horizon, label in [("1m", "1-Month"), ("3m", "3-Month")]:
        corrs = econ.get(horizon, {})
        if corrs:
            detail_lines.append(f"**{label} Forward Model:**")
            detail_lines.append("```")
            for idx in ["SPY", "QQQ", "IWM"]:
                c = corrs.get(idx, {})
                if c:
                    r = c.get("corr", 0)
                    t = c.get("t_stat", 0)
                    sig = "**" if abs(t) >= 2.0 else "*" if abs(t) >= 1.65 else ""
                    signal = "BULLISH" if r > 0 else "BEARISH"
                    detail_lines.append(f"  {idx}: r={r:+.3f} t={t:+.2f}{sig} -> {signal}")
            detail_lines.append("```")

    # Sector exposure
    if sectors and corrs_1m:
        detail_lines.append("**Sector Exposure** (pass-through via index correlation):")
        detail_lines.append("```")

        best_idx = None
        best_t = 0
        for idx in ["SPY", "QQQ", "IWM"]:
            c = corrs_1m.get(idx, {})
            if c and abs(c.get("t_stat", 0)) > abs(best_t):
                best_t = c.get("t_stat", 0)
                best_idx = idx

        if best_idx:
            econ_r = corrs_1m[best_idx].get("corr", 0)
            sector_impacts = []
            for ticker, sdata in sectors.items():
                beta = sdata.get(best_idx, 0)
                if isinstance(beta, (int, float)) and beta != 0:
                    passthrough = econ_r * beta
                    sector_impacts.append((sdata.get("name", ticker), passthrough, beta))
            sector_impacts.sort(key=lambda x: abs(x[1]), reverse=True)
            for sname, pt, beta in sector_impacts[:8]:
                signal = "+" if pt > 0 else "-"
                detail_lines.append(f"  {sname:<14} {signal}{abs(pt):.3f}  (beta={beta:+.2f} via {best_idx})")

        detail_lines.append("```")

    detail_msg = "\n".join(detail_lines)

    return trade_msg, detail_msg


# ─── MAIN ─────────────────────────────────────────────────────────

def main():
    now_et = datetime.now(ET)

    # Allow --date YYYY-MM-DD override for testing
    test_mode = False
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        override = sys.argv[idx + 1]
        now_et = datetime.strptime(override, "%Y-%m-%d").replace(tzinfo=ET)
        test_mode = True
        print(f"[test mode] Overriding date to {override}")

    late_mode = "late" in sys.argv[1:]
    mode_str = "late" if late_mode else "early"
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Econ release analysis ({mode_str} mode)")

    # 1. Load calendar, model state, release state
    calendar = load_calendar()
    model = load_model_state()
    release_state = load_release_state()
    today_str = now_et.strftime("%Y-%m-%d")
    day_of_week = now_et.weekday()

    if not model.get("econ"):
        print("WARNING: No model state found — run econometrics-report.py first")
        print("  Will still detect new data but without impact predictions")

    # 2. Find today's releases that have FRED IDs
    events = list(calendar.get(today_str, []))

    # Add jobless claims every Thursday
    if day_of_week == 3:
        events.append({
            "name": "Initial Jobless Claims",
            "fred_id": "ICSA",
            "time": "8:30 AM ET",
        })

    # Filter to events with fred_id
    fred_events = [(e["name"], e["fred_id"]) for e in events if e.get("fred_id")]

    if not fred_events:
        print(f"No FRED-linked releases today ({today_str})")
        return

    # Filter by release time (skip in test mode — process all)
    if not late_mode and not test_mode:
        early_events = [(n, fid) for n, fid in fred_events
                        if any(e.get("time", "").startswith(("8:30", "9:15"))
                               for e in events if e.get("fred_id") == fid)]
        fred_events = early_events

    if not fred_events:
        print(f"No releases to poll in {mode_str} mode")
        return

    # 3. Determine which series need polling (skip already-alerted)
    alerted = release_state.get("alerted", {})
    to_poll = []
    for event_name, fred_id in fred_events:
        econ = model.get("econ", {}).get(fred_id, {})
        known_date = econ.get("latest_date", "2020-01-01")

        last_alerted = alerted.get(fred_id, "2020-01-01")
        if last_alerted > known_date and not test_mode:
            print(f"  {fred_id}: already alerted ({last_alerted}), skipping")
            continue

        to_poll.append((event_name, fred_id, known_date))

    if not to_poll:
        print("All releases already processed")
        return

    print(f"Polling {len(to_poll)} series: {', '.join(fid for _, fid, _ in to_poll)}")

    # 4. Poll each series (in test mode: just fetch latest, no polling loop)
    poll_time = 20 if late_mode else 30
    poll_interval = 120

    for event_name, fred_id, known_date in to_poll:
        print(f"\n{'Fetching' if test_mode else 'Polling'} {fred_id} ({event_name})...")

        if test_mode:
            # In test mode, just fetch latest data directly
            new_data = fetch_fred_latest(fred_id)
            if not new_data:
                print(f"  {fred_id}: no data from FRED")
                continue
            print(f"  {fred_id}: latest data {new_data['date']} = {new_data['value']}")
        else:
            new_data = poll_for_new_data(fred_id, known_date, poll_time, poll_interval)
            if not new_data:
                continue

        # 5. Analyze and post
        trade_msg, detail_msg = analyze_release(event_name, fred_id, new_data, model)

        # Post both messages to Discord
        send_discord(trade_msg)
        time.sleep(0.5)
        send_discord(detail_msg)
        print(f"  Posted analysis for {fred_id}")

        # Mark as alerted
        alerted[fred_id] = new_data["date"]
        release_state["alerted"] = alerted
        release_state["last_run"] = now_et.isoformat()
        save_release_state(release_state)

    print(f"\n{datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S')} Release analysis complete")


if __name__ == "__main__":
    main()
