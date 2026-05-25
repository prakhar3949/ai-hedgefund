"""
Macro Economic Calendar — Posts daily reminders with model-based predictions.
Schedule: 6:00 AM PST weekdays (runs before morning briefing)
Posts to Discord via webhook on event days.
Also maintains memory/macro-calendar.json for morning briefing integration.

Enhanced: links events to FRED series IDs, loads econometric model state
to predict which indexes/sectors will move on each release.

Cost: $0.00 (Tier 1 — reads local JSON, no API calls)
"""

import json
import requests
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Use the project directory as base, not ~/clawd
PROJECT_DIR = Path(__file__).resolve().parent.parent
MEMORY_DIR = PROJECT_DIR / "memory"
MEMORY_DIR.mkdir(exist_ok=True)

CALENDAR_FILE = MEMORY_DIR / "macro-calendar.json"
MODEL_STATE_FILE = MEMORY_DIR / "econ-model-state.json"

# Discord webhook URL
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1470302148775641252/Bgicj_L7b_HwvoZEo7wgrrk7EnDRvxQkyq0lh1pDntPFgJ5_Ltaj6UbbHbakzMjtRCEl"

# ─── BUILD 2026 MACRO ECONOMIC CALENDAR ─────────────────────────
# Built via add() to handle multiple events on the same date cleanly.

MACRO_EVENTS_2026 = {}


def _add(date: str, name: str, impact: str, time: str, fred_id: str = None):
    event = {"name": name, "impact": impact, "time": time}
    if fred_id:
        event["fred_id"] = fred_id
    MACRO_EVENTS_2026.setdefault(date, []).append(event)


# ── FOMC Rate Decisions ──
for d in ["2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
          "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16"]:
    _add(d, "FOMC Rate Decision", "HIGH", "2:00 PM ET")

# ── CPI (Consumer Price Index) — BLS, ~2nd week ──
_cpi = [("01-14", "Dec"), ("02-12", "Jan"), ("03-11", "Feb"), ("04-14", "Mar"),
        ("05-13", "Apr"), ("06-10", "May"), ("07-15", "Jun"), ("08-12", "Jul"),
        ("09-11", "Aug"), ("10-13", "Sep"), ("11-12", "Oct"), ("12-10", "Nov")]
for md, period in _cpi:
    _add(f"2026-{md}", f"CPI ({period})", "HIGH", "8:30 AM ET", "CPIAUCSL")

# ── NFP (Non-Farm Payrolls) — BLS, 1st Friday ──
# PAYEMS + UNRATE + MANEMP all release same day
_nfp = [("01-09", "Dec"), ("02-06", "Jan"), ("03-06", "Feb"), ("04-03", "Mar"),
        ("05-08", "Apr"), ("06-05", "May"), ("07-02", "Jun"), ("08-07", "Jul"),
        ("09-04", "Aug"), ("10-02", "Sep"), ("11-06", "Oct"), ("12-04", "Nov")]
for md, period in _nfp:
    _add(f"2026-{md}", f"Jobs Report ({period} NFP)", "HIGH", "8:30 AM ET", "PAYEMS")

# ── PCE Price Index — BEA, ~last week ──
_pce = [("01-30", "Dec"), ("02-27", "Jan"), ("03-27", "Feb"), ("04-30", "Mar"),
        ("05-29", "Apr"), ("06-26", "May"), ("07-31", "Jun"), ("08-28", "Jul"),
        ("09-25", "Aug"), ("10-30", "Sep"), ("11-25", "Oct"), ("12-23", "Nov")]
for md, period in _pce:
    _add(f"2026-{md}", f"PCE Prices ({period})", "HIGH", "8:30 AM ET", "PCEPI")

# ── GDP (Advance Estimates) — BEA, quarterly ──
_add("2026-01-29", "GDP Q4 2025 (Advance)", "MEDIUM", "8:30 AM ET")
_add("2026-04-29", "GDP Q1 2026 (Advance)", "MEDIUM", "8:30 AM ET")
_add("2026-07-30", "GDP Q2 2026 (Advance)", "MEDIUM", "8:30 AM ET")
_add("2026-10-29", "GDP Q3 2026 (Advance)", "MEDIUM", "8:30 AM ET")

# ── Retail Sales — Census, ~mid-month ──
_retail = [("01-16", "Dec"), ("02-18", "Jan"), ("03-17", "Feb"), ("04-15", "Mar"),
           ("05-15", "Apr"), ("06-16", "May"), ("07-16", "Jun"), ("08-14", "Jul"),
           ("09-16", "Aug"), ("10-16", "Sep"), ("11-17", "Oct"), ("12-16", "Nov")]
for md, period in _retail:
    _add(f"2026-{md}", f"Retail Sales ({period})", "MEDIUM", "8:30 AM ET", "RSAFS")

# ── Housing Starts — Census, ~3rd week ──
_housing = [("01-21", "Dec"), ("02-19", "Jan"), ("03-18", "Feb"), ("04-16", "Mar"),
            ("05-19", "Apr"), ("06-17", "May"), ("07-17", "Jun"), ("08-19", "Jul"),
            ("09-17", "Aug"), ("10-21", "Sep"), ("11-18", "Oct"), ("12-17", "Nov")]
for md, period in _housing:
    _add(f"2026-{md}", f"Housing Starts ({period})", "LOW", "8:30 AM ET", "HOUST")

# ── Industrial Production — Fed, ~mid-month ──
_indpro = [("01-17", "Dec"), ("02-14", "Jan"), ("03-17", "Feb"), ("04-17", "Mar"),
           ("05-16", "Apr"), ("06-16", "May"), ("07-17", "Jun"), ("08-15", "Jul"),
           ("09-15", "Aug"), ("10-17", "Sep"), ("11-17", "Oct"), ("12-16", "Nov")]
for md, period in _indpro:
    _add(f"2026-{md}", f"Industrial Production ({period})", "LOW", "9:15 AM ET", "INDPRO")

# ── Durable Goods Orders — Census, ~26th ──
_durable = [("01-27", "Dec"), ("02-26", "Jan"), ("03-25", "Feb"), ("04-24", "Mar"),
            ("05-27", "Apr"), ("06-25", "May"), ("07-28", "Jun"), ("08-26", "Jul"),
            ("09-25", "Aug"), ("10-27", "Sep"), ("11-25", "Oct"), ("12-24", "Nov")]
for md, period in _durable:
    _add(f"2026-{md}", f"Durable Goods ({period})", "MEDIUM", "8:30 AM ET", "DGORDER")

# ── Consumer Sentiment (UMich) — ~2nd Friday (preliminary) ──
_umcsent = [("01-17", "Jan"), ("02-13", "Feb"), ("03-13", "Mar"), ("04-10", "Apr"),
            ("05-16", "May"), ("06-12", "Jun"), ("07-10", "Jul"), ("08-14", "Aug"),
            ("09-11", "Sep"), ("10-10", "Oct"), ("11-14", "Nov"), ("12-11", "Dec")]
for md, period in _umcsent:
    _add(f"2026-{md}", f"Consumer Sentiment Prelim ({period})", "LOW", "10:00 AM ET", "UMCSENT")

# ── ISM Manufacturing PMI — 1st business day of each month ──
_ism = [("01-02", "Dec"), ("02-02", "Jan"), ("03-02", "Feb"), ("04-01", "Mar"),
        ("05-01", "Apr"), ("06-01", "May"), ("07-01", "Jun"), ("08-03", "Jul"),
        ("09-01", "Aug"), ("10-01", "Sep"), ("11-02", "Oct"), ("12-01", "Nov")]
for md, period in _ism:
    _add(f"2026-{md}", f"ISM Manufacturing PMI ({period})", "HIGH", "10:00 AM ET", "NAPM")

# ── Employment Cost Index (ECI) — BLS, quarterly, ~last business day of month after quarter end ──
_eci = [("01-30", "Q4 2025"), ("04-30", "Q1 2026"), ("07-31", "Q2 2026"), ("10-30", "Q3 2026")]
for md, period in _eci:
    _add(f"2026-{md}", f"Employment Cost Index ({period})", "HIGH", "8:30 AM ET", "CES0500000003")

# ── Average Hourly Earnings — released with NFP (already in Jobs Report above) ──
# Noted here for reference: AHE (CES0500000003) releases on the same day as NFP.
# The Jobs Report entries above cover this. Wage growth is also tracked via ECI quarterly.


# ─── HELPER FUNCTIONS ────────────────────────────────────────────

def save_calendar():
    """Save macro calendar to JSON for morning briefing and release analysis integration."""
    data = {"events": MACRO_EVENTS_2026, "updated": datetime.now(ET).isoformat()}
    with open(CALENDAR_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_model_state() -> dict:
    """Load econometric model coefficients (saved weekly by econometrics-report.py)."""
    try:
        with open(MODEL_STATE_FILE) as f:
            return json.load(f)
    except:
        return {}


def send_discord(message: str):
    """Send message to Discord via webhook."""
    if len(message) > 1950:
        message = message[:1947] + "..."
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"Send failed: {e}")


def format_model_predictions(fred_id: str, model: dict) -> list[str]:
    """Format model-based predictions for a FRED series release."""
    econ = model.get("econ", {}).get(fred_id, {})
    if not econ:
        return []

    lines = []
    transform = econ.get("transform", "pct")
    latest_raw = econ.get("latest_raw")
    prev_raw = econ.get("prev_raw")
    if latest_raw is not None and prev_raw is not None:
        if transform == "pct":
            chg = (latest_raw / prev_raw - 1) * 100
            lines.append(f"Last print: {chg:+.2f}% MoM")
        else:
            chg = latest_raw - prev_raw
            lines.append(f"Last print: {chg:+.1f} change")

    # 1-month forward correlations
    corrs_1m = econ.get("1m", {})
    if corrs_1m:
        parts = []
        for idx in ["SPY", "QQQ", "IWM"]:
            c = corrs_1m.get(idx, {})
            if c:
                r, t = c.get("corr", 0), c.get("t_stat", 0)
                sig = "**" if abs(t) >= 2.0 else "*" if abs(t) >= 1.65 else ""
                direction = "bull" if r > 0 else "bear"
                parts.append(f"{idx}: r={r:+.2f}{sig} ({direction})")
        if parts:
            lines.append("Model: " + " | ".join(parts))

    # Most exposed sectors
    sectors = model.get("sectors", {})
    if sectors and corrs_1m:
        max_idx = max(corrs_1m, key=lambda i: abs(corrs_1m[i].get("corr", 0)))
        sector_list = []
        for ticker, sdata in sectors.items():
            idx_corr = sdata.get(max_idx, 0)
            if isinstance(idx_corr, (int, float)):
                sector_list.append((sdata.get("name", ticker), idx_corr))
        if sector_list:
            sector_list.sort(key=lambda x: abs(x[1]), reverse=True)
            top = sector_list[:3]
            lines.append(f"Top sectors (by {max_idx} beta): " +
                         ", ".join(f"{n} ({c:+.2f})" for n, c in top))

    return lines


def get_next_event_date(now_et: datetime, keyword: str) -> tuple | None:
    """Find the next upcoming release date for events matching keyword."""
    today_str = now_et.strftime("%Y-%m-%d")
    candidates = []
    for date_str, events in MACRO_EVENTS_2026.items():
        if date_str < today_str:
            continue
        for event in events:
            if keyword in event["name"]:
                candidates.append((date_str, event))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0]
    return None


def main():
    import sys
    now_et = datetime.now(ET)

    # Allow --date YYYY-MM-DD override for testing
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        override = sys.argv[idx + 1]
        now_et = datetime.strptime(override, "%Y-%m-%d").replace(tzinfo=ET)
        print(f"[test mode] Overriding date to {override}")

    today_str = now_et.strftime("%Y-%m-%d")
    day_of_week = now_et.weekday()  # 0=Mon, 3=Thu

    # Always save calendar
    save_calendar()

    # Collect today's events
    events = list(MACRO_EVENTS_2026.get(today_str, []))

    # Add jobless claims every Thursday (ICSA)
    if day_of_week == 3:  # Thursday
        events.append({
            "name": "Initial Jobless Claims",
            "impact": "LOW",
            "time": "8:30 AM ET",
            "fred_id": "ICSA",
        })

    if not events:
        print(f"{today_str}: No macro events today")
        show_upcoming_release(now_et, "Retail Sales", "Retail Sales")
        show_upcoming_release(now_et, "Employment Cost Index", "Wage Growth (ECI)")
        return

    # Load model state for predictions
    model = load_model_state()

    # Build alert
    lines = [f"**Macro Calendar** ({now_et.strftime('%a %b %d')})"]
    lines.append("")

    for event in events:
        impact_emoji = {"HIGH": "!!!", "MEDIUM": "!!", "LOW": "!"}.get(event["impact"], "")
        lines.append(f"[{impact_emoji}] **{event['name']}** at {event['time']}")

        # Add model predictions if FRED series linked
        fred_id = event.get("fred_id")
        if fred_id and model:
            pred_lines = format_model_predictions(fred_id, model)
            for pl in pred_lines:
                lines.append(f"  {pl}")
        lines.append("")

    message = "\n".join(lines).strip()
    send_discord(message)
    print(f"{today_str}: Posted macro alert — {', '.join(e['name'] for e in events)}")

    # Always show upcoming release dates
    show_upcoming_release(now_et, "Retail Sales", "Retail Sales")
    show_upcoming_release(now_et, "Employment Cost Index", "Wage Growth (ECI)")


def show_upcoming_release(now_et: datetime, keyword: str, label: str):
    """Print the next upcoming release date for a given event type."""
    result = get_next_event_date(now_et, keyword)
    if result:
        date_str, event = result
        release_date = datetime.strptime(date_str, "%Y-%m-%d")
        days_away = (release_date - now_et.replace(tzinfo=None)).days
        print(f"\n--- {label} Release ---")
        print(f"  {event['name']}")
        print(f"  Date: {release_date.strftime('%A, %B %d, %Y')}")
        print(f"  Time: {event['time']}")
        if days_away == 0:
            print(f"  Status: TODAY")
        elif days_away == 1:
            print(f"  Status: TOMORROW")
        else:
            print(f"  Status: {days_away} days away")
    else:
        print(f"\nNo upcoming {label} release date found for 2026.")


if __name__ == "__main__":
    main()
