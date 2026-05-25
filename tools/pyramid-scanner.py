"""
Pyramid Scanner — Add-to-Winners Decision Tool

Reads `pyramid-positions.json` (you maintain manually). For each open position:
  1. Re-derives fresh signals from bubble-scanner (entries A/E/F, exits, regime)
  2. Scores via a 0-100 "Add Quality" composite that integrates:
       regime gate + parent ETF bubble state + sector breadth + sector
       momentum + pullback quality + earnings proximity + position context
  3. Picks add-tier (1/2/3) based on gain-from-entry, applies tier-specific
     quality bar, computes vol-adjusted size and the new combined stop.
  4. Surfaces ADD / WAIT / TRIM recommendation per position to Discord.

Never auto-adds. To actually record an add: re-run with `--confirm-add NVDA`.

Usage:
  python pyramid-scanner.py                       # scan all open positions
  python pyramid-scanner.py --confirm-add NVDA    # record latest add for NVDA
  python pyramid-scanner.py --init NVDA 100 183.91 2026-04-09 SMH   # add new pos
"""

import io
import sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import json
import argparse
import importlib.util
import requests
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

# Discord webhook — set to None to print-only; user can fill in their channel
DISCORD_WEBHOOK_URL = None

POSITIONS_PATH = TOOLS_DIR / "pyramid-positions.json"

# Sizing — stab/main-add/final structure (probe-then-commit, NOT classic pyramid)
# Stab (10-20% of target) is taken manually by the user via --init.
# Main Add brings position to ~70% of target. Final Top-Up brings to 100%.
PHASE_TARGET_PCT = {"main_add": 0.70, "final": 1.00}
QUALITY_BAR = {"main_add": 50, "final": 60}
PHASE_SHARES_BAND = {  # (lower, upper) of shares_done/target_shares
    "main_add": (0.05, 0.30),    # eligible when current position is 5-30% of target (stab done)
    "final":    (0.30, 0.90),    # eligible when at 30-90% of target (main add done)
}
TARGET_VOL = 0.50              # for vol-adjusted sizing
TIMEOUT_SESSIONS = 30          # if no add in N sessions, raise bar +10 and surface TIMEOUT

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
CW_SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLC", "XLB", "XLRE"]


# ── Import bubble-scanner helpers (filename has hyphens) ─────────────────────

def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bs = _load_module("bubble_scanner", TOOLS_DIR / "bubble-scanner.py")
try:
    ts = _load_module("trade_setup", TOOLS_DIR / "trade-setup.py")
except Exception as e:
    print(f"  Warning: trade-setup not importable ({e}); pullback quality disabled.", file=sys.stderr)
    ts = None


# ── Discord ──────────────────────────────────────────────────────────────────

def send_discord(text: str):
    if not DISCORD_WEBHOOK_URL:
        return
    chunks = []
    cur = ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 1900:
            chunks.append(cur); cur = line
        else:
            cur = cur + "\n" + line if cur else line
    if cur:
        chunks.append(cur)
    for ch in chunks:
        try:
            r = requests.post(DISCORD_WEBHOOK_URL, json={"content": ch}, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"  Discord failed: {e}", file=sys.stderr)


# ── Positions State ──────────────────────────────────────────────────────────

def load_positions() -> dict:
    if not POSITIONS_PATH.exists():
        return {"positions": {}}
    with open(POSITIONS_PATH) as f:
        return json.load(f)


def save_positions(state: dict):
    with open(POSITIONS_PATH, "w") as f:
        json.dump(state, f, indent=2)


def init_position(ticker: str, shares: int, target: int, entry_price: float, entry_date: str, parent_etf: str):
    state = load_positions()
    if ticker in state["positions"]:
        print(f"{ticker} already exists. Refusing to overwrite.")
        return
    stab_pct = 100 * shares / target if target > 0 else 0
    state["positions"][ticker] = {
        "entry_date": entry_date,
        "entry_price": float(entry_price),
        "initial_shares": int(shares),         # the stab
        "target_shares": int(target),          # intended final size
        "parent_etf": parent_etf.upper(),
        "thesis": "",
        "adds": [],
        "current_stop": round(float(entry_price) * 0.92, 2),
        "status": "active",
    }
    save_positions(state)
    print(f"Initialized {ticker}: stab {shares}/{target} sh ({stab_pct:.0f}%) @ ${entry_price:.2f} on {entry_date}, parent={parent_etf}")


# ── Sector Breadth (inlined, lightweight) ────────────────────────────────────

def sector_breadth_score(parent_etf: str, holdings_data: dict[str, pd.DataFrame]) -> dict:
    """Compute % of parent ETF holdings > SMA50 and > SMA200. Returns dict with score."""
    if not holdings_data:
        return {"score": None, "label": "N/A", "pct_above_50": None, "pct_above_200": None}
    above_50 = 0
    above_200 = 0
    n = 0
    for t, df in holdings_data.items():
        if df is None or len(df) < 200:
            continue
        n += 1
        c = df["Close"]
        if c.iloc[-1] > bs.sma(c, 50).iloc[-1]:
            above_50 += 1
        if c.iloc[-1] > bs.sma(c, 200).iloc[-1]:
            above_200 += 1
    if n == 0:
        return {"score": None, "label": "N/A", "pct_above_50": None, "pct_above_200": None}
    pct50 = 100 * above_50 / n
    pct200 = 100 * above_200 / n
    score = 0.5 * pct50 / 100 + 0.5 * pct200 / 100
    if score >= 0.70:
        label = "STRONG"
    elif score >= 0.50:
        label = "HEALTHY"
    elif score >= 0.30:
        label = "MIXED"
    else:
        label = "WEAK"
    return {"score": score, "label": label, "pct_above_50": pct50, "pct_above_200": pct200, "n": n}


# ── Sector Momentum & RRG ────────────────────────────────────────────────────

def sector_momentum(parent_etf_df: pd.DataFrame, spy_df: pd.DataFrame) -> dict:
    """Classify sector momentum vs SPY: ACCELERATING / DECELERATING / NEUTRAL."""
    if parent_etf_df is None or spy_df is None:
        return {"phase": "N/A", "rs_1w": None, "rs_4w": None}
    pc = parent_etf_df["Close"]
    sc = spy_df["Close"]
    if len(pc) < 30 or len(sc) < 30:
        return {"phase": "N/A", "rs_1w": None, "rs_4w": None}
    rs_1w = (pc.iloc[-1] / pc.iloc[-6] - 1) - (sc.iloc[-1] / sc.iloc[-6] - 1)
    rs_4w = (pc.iloc[-1] / pc.iloc[-21] - 1) - (sc.iloc[-1] / sc.iloc[-21] - 1)
    if rs_1w > rs_4w and rs_1w > 0:
        phase = "ACCELERATING"
    elif rs_1w < rs_4w and rs_1w < 0:
        phase = "DECELERATING"
    else:
        phase = "NEUTRAL"
    return {"phase": phase, "rs_1w": rs_1w * 100, "rs_4w": rs_4w * 100}


def rrg_quadrant(parent_etf_df: pd.DataFrame, spy_df: pd.DataFrame) -> str:
    """RRG quadrant: Leading / Improving / Weakening / Lagging."""
    if parent_etf_df is None or spy_df is None or len(parent_etf_df) < 130 or len(spy_df) < 130:
        return "N/A"
    rs = parent_etf_df["Close"] / spy_df["Close"].reindex(parent_etf_df.index, method="ffill")
    rs = rs.dropna()
    if len(rs) < 130:
        return "N/A"
    # JdK style: RS-Ratio = current RS / SMA(63) RS, normalized. Momentum = ROC of ratio.
    ratio = rs / rs.rolling(63).mean()
    ratio_now = float(ratio.iloc[-1])
    ratio_5d_ago = float(ratio.iloc[-6])
    momentum_now = ratio_now - ratio_5d_ago
    if ratio_now > 1.0 and momentum_now > 0:
        return "Leading"
    elif ratio_now > 1.0 and momentum_now <= 0:
        return "Weakening"
    elif ratio_now <= 1.0 and momentum_now > 0:
        return "Improving"
    else:
        return "Lagging"


# ── Earnings Proximity (lightweight, no API call) ────────────────────────────
# Uses Yahoo's quoteSummary "calendarEvents" — same approach as fundamentals-scanner.

def earnings_days_away(ticker: str) -> int | None:
    url = (
        f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker.replace('.', '-')}"
        f"?modules=calendarEvents"
    )
    try:
        r = requests.get(url, headers=YAHOO_HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        events = (data.get("quoteSummary", {})
                      .get("result", [{}])[0]
                      .get("calendarEvents", {}))
        earnings_dates = events.get("earnings", {}).get("earningsDate", [])
        if not earnings_dates:
            return None
        next_ts = earnings_dates[0].get("raw")
        if next_ts is None:
            return None
        next_dt = datetime.fromtimestamp(next_ts, tz=ET)
        return (next_dt - datetime.now(ET)).days
    except Exception:
        return None


# ── Add Quality Scoring ──────────────────────────────────────────────────────

def score_add(regime, parent_qual, breadth, momentum, quadrant, pullback,
              earnings_days, gain_pct, vol_regime) -> dict:
    """Compute add quality 0-100 with per-component breakdown."""
    components = {}

    # Regime gate (20%)
    if regime["gate_open"] and regime["vol_regime"] == "LOW":
        components["Regime"] = ("🟢 GATE OPEN (vol LOW)", 20)
    elif regime["gate_open"] and regime["vol_regime"] == "NORMAL":
        components["Regime"] = ("🟢 GATE OPEN (vol NORMAL)", 15)
    elif regime["gate_open"]:
        components["Regime"] = (f"🟢 GATE OPEN (vol {regime['vol_regime']})", 5)
    elif regime["vol_regime"] in {"ELEVATED"}:
        components["Regime"] = (f"🔴 GATE CLOSED (vol {regime['vol_regime']})", -15)
    else:
        components["Regime"] = (f"🔴 GATE CLOSED (vol {regime['vol_regime']})", -30)

    # Parent ETF bubble state (15%)
    cls = parent_qual["classification"]
    if cls == "FULL BUBBLE":
        components["Parent"] = (f"FULL BUBBLE (1Y {parent_qual['ret_1y']*100:+.0f}%, stretch {parent_qual['stretch']:.1f}σ)", 15)
    elif cls == "EMERGING":
        components["Parent"] = (f"EMERGING (1Y {parent_qual['ret_1y']*100:+.0f}%)", 8)
    elif cls == "WATCHLIST":
        components["Parent"] = (f"WATCHLIST (1Y {parent_qual['ret_1y']*100:+.0f}%)", 2)
    else:
        components["Parent"] = (f"REJECT (1Y {parent_qual['ret_1y']*100:+.0f}%)", -10)

    # Sector RRG (15%)
    if quadrant == "Leading":
        components["RRG"] = ("Leading quadrant", 15)
    elif quadrant == "Improving":
        components["RRG"] = ("Improving quadrant", 10)
    elif quadrant == "Weakening":
        components["RRG"] = ("Weakening quadrant", -5)
    elif quadrant == "Lagging":
        components["RRG"] = ("Lagging quadrant", -20)
    else:
        components["RRG"] = ("N/A", 0)

    # Sector breadth (15%)
    if breadth["label"] == "STRONG":
        components["Breadth"] = (f"STRONG ({breadth['pct_above_50']:.0f}% >50MA)", 15)
    elif breadth["label"] == "HEALTHY":
        components["Breadth"] = (f"HEALTHY ({breadth['pct_above_50']:.0f}% >50MA)", 10)
    elif breadth["label"] == "MIXED":
        components["Breadth"] = (f"MIXED ({breadth['pct_above_50']:.0f}% >50MA)", -5)
    elif breadth["label"] == "WEAK":
        components["Breadth"] = (f"WEAK ({breadth['pct_above_50']:.0f}% >50MA)", -20)
    else:
        components["Breadth"] = ("N/A", 0)

    # Pullback quality (15%)
    if pullback is None:
        components["Pullback"] = ("N/A", 0)
    else:
        pb_cls = pullback.get("classification", "")
        pb_score = pullback.get("score", 0) or 0
        if "HEALTHY" in pb_cls:
            components["Pullback"] = (f"HEALTHY ({pb_score}/100)", 20)
        elif "ACCEPTABLE" in pb_cls:
            components["Pullback"] = (f"ACCEPTABLE ({pb_score}/100)", 10)
        elif "QUESTIONABLE" in pb_cls:
            components["Pullback"] = (f"QUESTIONABLE ({pb_score}/100)", -10)
        elif "UNHEALTHY" in pb_cls:
            components["Pullback"] = (f"UNHEALTHY ({pb_score}/100)", -25)
        else:
            components["Pullback"] = (f"{pb_cls or 'N/A'}", 0)

    # Sector momentum (10%)
    phase = momentum["phase"]
    if phase == "ACCELERATING":
        components["Momentum"] = (f"ACCELERATING (1W RS {momentum['rs_1w']:+.1f}%)", 10)
    elif phase == "DECELERATING":
        components["Momentum"] = (f"DECELERATING (1W RS {momentum['rs_1w']:+.1f}%)", -10)
    else:
        components["Momentum"] = (f"{phase}", 0)

    # Earnings proximity (5%)
    if earnings_days is None:
        components["Earnings"] = ("unknown", 0)
    elif earnings_days <= 5:
        components["Earnings"] = (f"RISK ({earnings_days}d away)", -25)
    elif earnings_days <= 14:
        components["Earnings"] = (f"APPROACHING ({earnings_days}d)", -10)
    else:
        components["Earnings"] = (f"CLEAR ({earnings_days}d)", 5)

    # Position context: gain from entry (5%)
    if gain_pct < 0.15:
        components["Position ctx"] = (f"Early-trend (+{gain_pct*100:.1f}% from entry)", 10)
    elif gain_pct < 0.40:
        components["Position ctx"] = (f"Mid-trend (+{gain_pct*100:.1f}%)", 5)
    elif gain_pct < 0.80:
        components["Position ctx"] = (f"Late-trend (+{gain_pct*100:.1f}%)", -5)
    else:
        components["Position ctx"] = (f"Parabolic (+{gain_pct*100:.0f}%)", -15)

    total = sum(pts for _, pts in components.values())
    total = max(0, min(100, total + 30))   # normalize: base 30 + signed components
    return {"total": total, "components": components}


# ── Red-Day Rule ─────────────────────────────────────────────────────────────
# Strategy: tool runs after today's close. If today was a red day (open > close),
# the recommendation becomes a NEXT-DAY ORB plan: tomorrow at 9:45 ET, watch the
# first 15-min bar. If the second 15-min bar (closing 10:00 ET) closes ABOVE the
# first bar's high by ≥ 0.1%, AND pre-market gap is ≤ +2%, execute the add at 10:00.

ORB_BUFFER = 0.001          # 0.1% required above OR-high for clean breakout
GAP_UP_MAX = 0.02           # skip add if pre-market gap > +2% vs prior close


def red_day_check(stock_df: pd.DataFrame) -> dict:
    """Detect whether today's session was a red day (open > close)."""
    if len(stock_df) < 2:
        return {"ok": False, "reason": "insufficient data"}
    last_date = stock_df.index[-1].date()
    # When the tool runs intraday during a session, iloc[-1] is today's partial bar
    # and we cannot evaluate the rule yet (today isn't over).
    today = datetime.now(ET).date()
    if last_date == today and datetime.now(ET).hour < 16:
        return {
            "ok": False,
            "reason": "tool ran during market hours; wait until after today's close",
            "today_session": last_date.isoformat(),
        }
    # iloc[-1] = the most recently completed session (today if after-close, else last trading day)
    today_open = float(stock_df["Open"].iloc[-1])
    today_close = float(stock_df["Close"].iloc[-1])
    today_high = float(stock_df["High"].iloc[-1])
    today_low = float(stock_df["Low"].iloc[-1])
    is_red = today_open > today_close
    return {
        "ok": is_red,
        "today_session": stock_df.index[-1].date().isoformat(),
        "today_open": today_open,
        "today_close": today_close,
        "today_high": today_high,
        "today_low": today_low,
        "is_red": is_red,
        "next_day_plan": {
            "orb_buffer_pct": ORB_BUFFER,
            "gap_up_max_pct": GAP_UP_MAX,
        } if is_red else None,
    }


# ── Phase Decision (shares-based, not gain-based) ────────────────────────────

def total_shares(pos: dict) -> int:
    return int(pos.get("initial_shares", 0)) + sum(int(a.get("shares", 0)) for a in pos.get("adds", []))


def decide_phase(pos: dict) -> str | None:
    """Determine which add phase the position is in based on shares accumulated vs target."""
    target = int(pos.get("target_shares") or 0)
    if target <= 0:
        return None  # no target set → can't compute phases
    done = total_shares(pos)
    frac = done / target
    if frac >= 0.95:
        return None  # at target
    if frac >= 0.30:
        return "final"
    if frac >= 0.05:
        return "main_add"
    return None  # haven't even taken the stab yet


def trigger_qualifies_for_phase(entries: list[dict], phase: str) -> tuple[bool, str]:
    """Phase-specific entry triggers."""
    if phase == "main_add":
        for e in entries:
            if e["type"] in {"A", "E", "F"}:
                return True, f"Entry {e['type']} ({e['name']})"
    elif phase == "final":
        for e in entries:
            if e["type"] in {"A", "E"}:
                return True, f"Entry {e['type']} ({e['name']})"
    return False, "no qualifying trigger today"


def sessions_since_last_action(pos: dict, stock_df: pd.DataFrame) -> int:
    """Sessions since stab or most recent add. Used for timeout."""
    actions = [pos["entry_date"]] + [a["date"] for a in pos.get("adds", [])]
    if not actions:
        return 0
    last = max(actions)
    try:
        last_dt = datetime.strptime(last, "%Y-%m-%d").date()
    except ValueError:
        return 0
    # Count trading sessions in stock_df strictly after last_dt
    return int((stock_df.index.date > last_dt).sum())


# ── Stop Computation ─────────────────────────────────────────────────────────

def new_stop_after_add(pos: dict, phase: str, current_price: float, atr_now: float) -> float:
    """After main_add: stop at stab entry price. After final: stop at weighted avg cost."""
    if phase == "main_add":
        return round(pos["entry_price"], 2)
    elif phase == "final":
        # Lock in: stop = average cost of main-add layer (highest-cost prior layer)
        if pos.get("adds"):
            last_add = pos["adds"][-1]
            return round(last_add["price"], 2)
        return round(pos["entry_price"], 2)
    return pos["current_stop"]


# ── Per-Position Analysis ────────────────────────────────────────────────────

def analyze_position(ticker: str, pos: dict, ctx: dict) -> dict:
    """Run the full scoring pipeline for one position. Returns structured result."""
    parent = pos["parent_etf"]
    stock_df = ctx["stocks"].get(ticker)
    parent_df = ctx["etfs"].get(parent)
    if stock_df is None:
        return {"ticker": ticker, "error": "no price data"}
    if parent_df is None:
        return {"ticker": ticker, "error": f"no data for parent {parent}"}

    px = float(stock_df["Close"].iloc[-1])
    entry = pos["entry_price"]
    gain_pct = (px / entry - 1)

    # Bubble-scanner core signals
    regime = ctx["regime"]
    parent_qual = bs.qualify_bubble(parent_df, regime)
    pbd = bs.bubble_days(parent_df, regime, lookback=60)
    entries = bs.detect_entries(stock_df, parent_df, pbd)
    exits = bs.detect_exits(stock_df)

    # Pullback quality
    pullback = None
    if ts is not None:
        try:
            pullback = ts.assess_pullback_quality(stock_df)
        except Exception:
            pullback = None

    # Sector breadth (using parent ETF holdings)
    breadth = sector_breadth_score(parent, ctx["holdings_data"].get(parent, {}))

    # Sector momentum + RRG (parent ETF vs SPY)
    momentum = sector_momentum(parent_df, ctx["spy"])
    quadrant = rrg_quadrant(parent_df, ctx["spy"])

    # Earnings proximity
    ed = earnings_days_away(ticker)

    # Score
    score = score_add(regime, parent_qual, breadth, momentum, quadrant, pullback,
                      ed, gain_pct, regime["vol_regime"])

    # Phase decision (shares-based, not gain-based)
    phase = decide_phase(pos)
    shares_done = total_shares(pos)
    target_shares = int(pos.get("target_shares") or 0)
    adds_done = len(pos.get("adds", []))

    # Red-day rule (precondition for any add)
    red_check = red_day_check(stock_df)

    # Timeout: if we've been waiting too long, raise the quality bar (Scenario 1)
    waited = sessions_since_last_action(pos, stock_df)
    timeout_active = waited >= TIMEOUT_SESSIONS

    # Trigger qualification
    trigger_ok, trigger_name = (False, "n/a")
    if phase is not None:
        trigger_ok, trigger_name = trigger_qualifies_for_phase(entries, phase)

    # Adjusted quality bar (timeout adds +10, but pulls in a "TIMEOUT" tag)
    effective_bar = QUALITY_BAR.get(phase, 100) + (10 if timeout_active else 0)

    # Decision logic (order matters: exit warnings first, then blockers, then quality)
    decision = "WAIT"
    reasons = []
    if exits["tier"] in {"RED", "ORANGE"}:
        decision = "TRIM"
        reasons.append(f"Exit ladder: {exits['tier']}")
    elif target_shares <= 0:
        decision = "NO TARGET"
        reasons.append("set target_shares in pyramid-positions.json")
    elif phase is None:
        if shares_done >= target_shares * 0.95:
            decision = "AT TARGET"
        elif shares_done == 0:
            decision = "NO STAB YET"
            reasons.append("take a 10-20% stab manually first, then --init")
        else:
            decision = "PHASE GAP"
            reasons.append(f"{shares_done}/{target_shares} sh, no phase matches")
    elif not red_check["ok"]:
        decision = "WAIT (red-day rule)"
        if "reason" in red_check:
            reasons.append(red_check["reason"])
        elif not red_check.get("is_red"):
            reasons.append(f"today {red_check['today_session']} closed green (O={red_check['today_open']:.2f} → C={red_check['today_close']:.2f})")
    elif not trigger_ok:
        decision = "WAIT"
        reasons.append(trigger_name)
    elif ed is not None and ed <= 5:
        decision = "BLOCKED (earnings)"
        reasons.append(f"earnings in {ed}d")
    elif regime["vol_regime"] in {"ELEVATED", "EXTREME"}:
        decision = "BLOCKED (vol)"
        reasons.append(f"vol regime {regime['vol_regime']}")
    elif phase == "final" and exits["tier"]:  # any tier (Flashing Yellow+)
        decision = "BLOCKED (de-risking)"
        reasons.append(f"Exit ladder: {exits['tier']} fires before final top-up")
    elif score["total"] < effective_bar:
        decision = "MARGINAL"
        reasons.append(f"quality {score['total']} < {phase} bar {effective_bar}{' (timeout +10)' if timeout_active else ''}")
    else:
        # When this branch fires, the decision is a NEXT-DAY ORB plan rather than
        # an immediate add (tool runs EOD; user executes tomorrow at 10:00 ET).
        decision = "ADD CANDIDATE (next-day ORB)" if score["total"] >= 70 else "ADD CANDIDATE (next-day ORB, marginal)"
        if timeout_active:
            reasons.append(f"TIMEOUT: {waited} sessions since last action, bar raised +10")

    # Sizing: bring position to phase target % of target_shares, scaled by quality + vol
    add_size = 0
    desired_total = 0
    if decision.startswith("ADD CANDIDATE") and phase is not None:
        phase_target_pct = PHASE_TARGET_PCT[phase]
        desired_total = int(round(target_shares * phase_target_pct))
        nominal = max(0, desired_total - shares_done)
        # Quality scaling: linear from bar → bar+20 maps to 0.5× → 1.0× (Scenario 7)
        scale = max(0.4, min(1.0, (score["total"] - effective_bar) / 20.0 + 0.5))
        # If marginal (not STRONG ADD), reduce further
        if "marginal" in decision.lower():
            scale *= 0.75
        # Vol-adjusted (Scenario 4)
        avol = bs.annualized_vol(stock_df["Close"], 60)
        vol_factor = min(1.0, TARGET_VOL / avol) if (avol and avol > 0) else 1.0
        add_size = max(1, int(round(nominal * scale * vol_factor))) if nominal > 0 else 0

    # Stop math
    atr_now = float(bs.atr(stock_df, 14).iloc[-1])
    new_stop = None
    if decision.startswith("ADD CANDIDATE") and phase is not None:
        new_stop = new_stop_after_add(pos, phase, px, atr_now)

    return {
        "ticker": ticker, "pos": pos, "current_price": px, "gain_pct": gain_pct,
        "parent_qual": parent_qual, "regime": regime, "entries": entries, "exits": exits,
        "breadth": breadth, "momentum": momentum, "quadrant": quadrant, "pullback": pullback,
        "earnings_days": ed, "score": score, "phase": phase, "shares_done": shares_done,
        "target_shares": target_shares, "adds_done": adds_done, "red_check": red_check,
        "timeout_active": timeout_active, "waited_sessions": waited,
        "effective_bar": effective_bar, "trigger": trigger_name, "decision": decision,
        "reasons": reasons, "add_size": add_size, "desired_total": desired_total,
        "new_stop": new_stop, "atr": atr_now,
    }


# ── Output Formatting ────────────────────────────────────────────────────────

def fmt_position(r: dict) -> str:
    if "error" in r:
        return f"\n{r['ticker']} — ⚠ {r['error']}\n"
    pos = r["pos"]
    px = r["current_price"]
    gain = r["gain_pct"] * 100
    lines = []
    lines.append(f"\n══════════════════════════════════════════")
    lines.append(f"POSITION: {r['ticker']} — Long since {pos['entry_date']} @ ${pos['entry_price']:.2f}")
    lines.append(f"  Current: ${px:.2f} ({gain:+.1f}% from entry)")
    lines.append(f"  Stab: {pos['initial_shares']} sh  |  Target: {r['target_shares']} sh  |  Filled: {r['shares_done']}/{r['target_shares']} ({100*r['shares_done']/max(r['target_shares'],1):.0f}%)")
    lines.append(f"  Adds done: {r['adds_done']}  |  Stop: ${pos['current_stop']:.2f}  |  Phase: {r.get('phase') or '—'}")
    if r["timeout_active"]:
        lines.append(f"  ⏰ TIMEOUT: {r['waited_sessions']} sessions since last action — bar raised +10")

    icon_map = {"ADD CANDIDATE (next-day ORB)": "🟢", "ADD CANDIDATE (next-day ORB, marginal)": "🟡",
                "MARGINAL": "🟡", "WAIT": "⚪", "WAIT (red-day rule)": "🟡", "TRIM": "🔴",
                "BLOCKED (earnings)": "🟠", "BLOCKED (vol)": "🟠",
                "BLOCKED (de-risking)": "🟠", "AT TARGET": "⚫",
                "NO STAB YET": "⚪", "NO TARGET": "⚠", "PHASE GAP": "⚪"}
    icon = icon_map.get(r["decision"], "")
    lines.append(f"\n  📊 ADD QUALITY: {r['score']['total']} / 100 — {icon} {r['decision']}")
    if r.get("phase"):
        band = PHASE_SHARES_BAND[r["phase"]]
        target_pct = PHASE_TARGET_PCT[r["phase"]] * 100
        lines.append(f"  Phase: {r['phase']} (eligible at {band[0]*100:.0f}-{band[1]*100:.0f}% filled, brings position to {target_pct:.0f}% of target, bar ≥ {r['effective_bar']})")
    lines.append(f"  Trigger: {r['trigger']}")
    # Red-day status
    rc = r.get("red_check", {})
    if rc and "today_open" in rc:
        red_str = f"today {rc.get('today_session','?')} O={rc.get('today_open',0):.2f} C={rc.get('today_close',0):.2f} {'🔴 RED' if rc.get('is_red') else '🟢 green'}"
        lines.append(f"  Red-day: {red_str}")
    elif rc and "reason" in rc:
        lines.append(f"  Red-day: {rc['reason']}")
    lines.append("  ──────────────────────────────────────")
    for name, (desc, pts) in r["score"]["components"].items():
        sign = "+" if pts >= 0 else ""
        lines.append(f"    {name:<14} {desc:<55} {sign}{pts}")
    lines.append("  ──────────────────────────────────────")
    if r["reasons"]:
        lines.append(f"  Why: {' | '.join(r['reasons'])}")
    if r["decision"].startswith("ADD CANDIDATE") and r["add_size"]:
        new_total = r["shares_done"] + r["add_size"]
        cost = pos["initial_shares"] * pos["entry_price"] + sum(a["shares"] * a["price"] for a in pos.get("adds", []))
        cost += r["add_size"] * px
        avg = cost / new_total
        lines.append(f"\n  NEXT-DAY ORB PLAN (execute tomorrow at ~10:00 ET):")
        lines.append(f"    1. Watch the first 15-min bar (9:30-9:45 ET). Note its high = OR_HIGH.")
        lines.append(f"    2. At 9:45 ET, second 15-min bar begins.")
        lines.append(f"    3. At 10:00 ET, check: did bar-2 close > OR_HIGH × 1.001 (need 0.1% buffer)?")
        lines.append(f"    4. ALSO check: pre-market gap ≤ +2% vs today's close ${rc.get('today_close', px):.2f} (skip if larger).")
        lines.append(f"    5. If BOTH conditions met → execute the add at ~10:00 ET.")
        lines.append(f"")
        lines.append(f"    Order: BUY {r['add_size']} sh of {r['ticker']} at market (or limit @ OR_HIGH × 1.005)")
        lines.append(f"    Brings position to {new_total}/{r['target_shares']} sh ({100*new_total/r['target_shares']:.0f}% of target)")
        lines.append(f"    Then: move stop to ${r['new_stop']:.2f}, new avg cost ≈ ${avg:.2f}")
        lines.append(f"")
        lines.append(f"    After executing, validate with: python pyramid-scanner.py --validate-orb {r['ticker']}")
        lines.append(f"    To record the add: python pyramid-scanner.py --confirm-add {r['ticker']}")
    if r["exits"]["tier"]:
        lines.append(f"\n  🟠 EXIT LADDER ACTIVE: {r['exits']['tier']}")
        for t in r["exits"]["triggers"][:3]:
            lines.append(f"      • {t}")
    return "\n".join(lines)


# ── Confirm Add (state writer) ───────────────────────────────────────────────

def confirm_add(ticker: str):
    """User confirms the most-recent add for a ticker; record it to state."""
    state = load_positions()
    if ticker not in state["positions"]:
        print(f"{ticker} not in positions.json"); return
    pos = state["positions"][ticker]
    # Re-run analysis to capture current quote + recommended add
    ctx = build_context([pos["parent_etf"]], [ticker])
    r = analyze_position(ticker, pos, ctx)
    if r.get("decision") not in {"STRONG ADD", "ADD"}:
        print(f"No active add recommendation for {ticker} (decision={r.get('decision')}). Nothing recorded.")
        return
    add_record = {
        "date": datetime.now(ET).strftime("%Y-%m-%d"),
        "price": r["current_price"],
        "shares": r["add_size"],
        "trigger": r["trigger"],
        "phase": r["phase"],
        "quality": r["score"]["total"],
    }
    pos.setdefault("adds", []).append(add_record)
    pos["current_stop"] = r["new_stop"]
    save_positions(state)
    print(f"Recorded {r['phase']} for {ticker}: {r['add_size']} sh @ ${r['current_price']:.2f}. New stop ${r['new_stop']:.2f}.")


# ── Context Builder ──────────────────────────────────────────────────────────

def build_context(parent_etfs: list[str], tickers: list[str]) -> dict:
    """Fetch all needed data once. Returns ctx dict shared across positions."""
    # 1) regime data: SPY, ^VIX, 11 CW sectors
    regime_universe = list(set(["SPY", "^VIX"] + CW_SECTORS))
    print(f"  Fetching regime data ({len(regime_universe)} symbols, 2y)...")
    regime_data = bs.batch_fetch(regime_universe, period="2y")

    # 2) parent ETFs
    print(f"  Fetching parent ETFs ({len(parent_etfs)})...")
    etf_data = bs.batch_fetch(list(set(parent_etfs)), period="2y")
    etfs_all = {**regime_data, **etf_data}

    # 3) tickers
    print(f"  Fetching positions ({len(tickers)} tickers)...")
    stock_data = bs.batch_fetch(tickers, period="2y")

    # 4) holdings per parent ETF for breadth
    with open(TOOLS_DIR / "etf-holdings.json") as f:
        holdings_json = json.load(f)
    holdings_data: dict[str, dict[str, pd.DataFrame]] = {}
    needed_holdings = set()
    parent_to_holdings: dict[str, list[str]] = {}
    for p in parent_etfs:
        h = holdings_json.get(p, {}).get("holdings", []) if not p.startswith("_") else []
        parent_to_holdings[p] = h
        for t in h:
            needed_holdings.add(t)
    needed_holdings -= set(stock_data) | set(etfs_all)
    if needed_holdings:
        print(f"  Fetching holdings for breadth ({len(needed_holdings)} tickers)...")
        extra = bs.batch_fetch(list(needed_holdings), period="1y")
    else:
        extra = {}
    all_data = {**etfs_all, **stock_data, **extra}
    for p, holdings in parent_to_holdings.items():
        holdings_data[p] = {t: all_data[t] for t in holdings if t in all_data}

    # Regime
    spy = regime_data.get("SPY")
    vix = regime_data.get("^VIX")
    sector_dfs = {t: regime_data[t] for t in CW_SECTORS if t in regime_data}
    regime = bs.compute_regime(spy, vix, sector_dfs)
    return {
        "regime": regime, "spy": spy, "vix": vix,
        "etfs": etfs_all, "stocks": stock_data, "holdings_data": holdings_data,
    }


# ── ORB Validation (post-hoc check) ──────────────────────────────────────────

def fetch_intraday_15m(ticker: str, days: int = 5) -> pd.DataFrame | None:
    """Fetch 15-min OHLCV bars from Yahoo, including pre/post market."""
    yticker = ticker.replace(".", "-")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yticker}"
        f"?range={days}d&interval=15m&includePrePost=true"
    )
    try:
        r = requests.get(url, headers=YAHOO_HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        ts = result[0].get("timestamp")
        if not ts:
            return None
        q = result[0]["indicators"]["quote"][0]
        df = pd.DataFrame({
            "Open": q.get("open"),
            "High": q.get("high"),
            "Low": q.get("low"),
            "Close": q.get("close"),
            "Volume": q.get("volume"),
        }, index=pd.to_datetime(ts, unit="s", utc=True))
        df.index = df.index.tz_convert("America/New_York")
        return df.dropna(subset=["Close"])
    except Exception:
        return None


def validate_orb(ticker: str, target_date: str | None = None):
    """
    Post-hoc ORB validation. Pulls 15-min data for the specified date (defaults
    to the most recent trading day), reports whether the ORB rule fired and what
    the 10:00 ET entry price would have been.
    """
    df = fetch_intraday_15m(ticker, days=5)
    if df is None or len(df) < 5:
        print(f"  Could not fetch 15-min data for {ticker}")
        return

    # Regular session bars only (09:30-16:00 ET)
    reg = df.between_time("09:30", "16:00")
    if target_date:
        day_str = target_date
    else:
        day_str = reg.index[-1].date().isoformat()
    day_mask = pd.Series([d.isoformat() == day_str for d in reg.index.date], index=reg.index)
    day_bars = reg[day_mask]
    if len(day_bars) < 2:
        print(f"  No intraday bars for {ticker} on {day_str}")
        return

    # Identify bar 1 (09:30-09:45) and bar 2 (09:45-10:00) by hour/minute
    bar1 = day_bars[(day_bars.index.hour == 9) & (day_bars.index.minute == 30)]
    bar2 = day_bars[(day_bars.index.hour == 9) & (day_bars.index.minute == 45)]
    if bar1.empty or bar2.empty:
        print(f"  Missing first or second 15-min bar for {ticker} {day_str}")
        print(f"  First bars of session: {[ts.strftime('%H:%M') for ts in day_bars.index[:4]]}")
        return

    or_high = float(bar1["High"].iloc[0])
    or_low = float(bar1["Low"].iloc[0])
    bar2_close = float(bar2["Close"].iloc[0])
    bar2_high = float(bar2["High"].iloc[0])

    # Prior day close + gap (last regular-session bar of a previous trading day)
    prior_close = None
    for offset in range(1, 6):
        d = (day_bars.index[0] - pd.Timedelta(days=offset)).date().isoformat()
        prev_day_mask = pd.Series([x.isoformat() == d for x in reg.index.date], index=reg.index)
        prev_day = reg[prev_day_mask & (reg.index.hour >= 15) & (reg.index.minute >= 45)]
        if not prev_day.empty:
            prior_close = float(prev_day["Close"].iloc[-1])
            break
    open_px = float(bar1["Open"].iloc[0])
    gap_pct = ((open_px / prior_close - 1) * 100) if prior_close else None

    # Did the ORB fire?
    breakout_level = or_high * (1 + ORB_BUFFER)
    orb_fired = bar2_close > breakout_level
    gap_ok = (gap_pct is None) or (gap_pct <= GAP_UP_MAX * 100)

    # What happened to EOD
    eod_close = float(day_bars["Close"].iloc[-1])
    intraday_high = float(day_bars["High"].max())
    intraday_low = float(day_bars["Low"].min())

    # Report
    print(f"\n══════════════════════════════════════════")
    print(f"ORB VALIDATION: {ticker}  date={day_str}")
    print(f"══════════════════════════════════════════")
    if prior_close is not None:
        print(f"  Prior close:    ${prior_close:.2f}")
        print(f"  Open ({bar1.index[0].strftime('%H:%M')}): ${open_px:.2f}  (gap {gap_pct:+.2f}%)  {'✓ within ±2%' if gap_ok else '✗ gap too large'}")
    print(f"  Bar 1 (09:30-09:45):  H ${or_high:.2f}  L ${or_low:.2f}  C ${float(bar1['Close'].iloc[0]):.2f}")
    print(f"  Bar 2 (09:45-10:00):  H ${bar2_high:.2f}  C ${bar2_close:.2f}")
    print(f"  ORB trigger level (OR_HIGH × {1+ORB_BUFFER:.3f}): ${breakout_level:.2f}")
    print(f"  Bar-2 close vs trigger: {'✓ ABOVE' if orb_fired else '✗ below'} (${bar2_close:.2f} vs ${breakout_level:.2f})")
    print(f"\n  RULE VERDICT: {'🟢 ORB FIRED — entry at $' + f'{bar2_close:.2f}' if (orb_fired and gap_ok) else '🔴 NO ENTRY'}")
    if not orb_fired:
        print(f"    Reason: bar-2 close did not exceed OR_HIGH × 1.001")
    elif not gap_ok:
        print(f"    Reason: pre-market gap {gap_pct:+.2f}% > +2% threshold")
    print(f"\n  Day played out:  Intraday H ${intraday_high:.2f}  L ${intraday_low:.2f}  Close ${eod_close:.2f}")
    if orb_fired and gap_ok:
        pnl = (eod_close - bar2_close) / bar2_close * 100
        print(f"  P&L from 10:00 entry to EOD close: {pnl:+.2f}%")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-add", metavar="TICKER", help="Record an add for ticker")
    parser.add_argument("--init", nargs=6,
                        metavar=("TICKER", "STAB_SHARES", "TARGET_SHARES", "PRICE", "DATE", "PARENT_ETF"),
                        help="Initialize a new position (stab is the shares already taken; target is intended final size)")
    parser.add_argument("--validate-orb", nargs="+", metavar=("TICKER", "DATE"),
                        help="Post-hoc check whether the 15-min ORB rule fired for ticker on a date (defaults to most recent session)")
    args = parser.parse_args()

    if args.init:
        t, s, tgt, p, d, pe = args.init
        init_position(t, int(s), int(tgt), float(p), d, pe)
        return

    if args.confirm_add:
        confirm_add(args.confirm_add.upper())
        return

    if args.validate_orb:
        t = args.validate_orb[0].upper()
        d = args.validate_orb[1] if len(args.validate_orb) > 1 else None
        validate_orb(t, d)
        return

    state = load_positions()
    positions = state.get("positions", {})
    open_pos = {t: p for t, p in positions.items() if p.get("status", "active") == "active"}
    if not open_pos:
        print("No open positions in pyramid-positions.json. Use --init to add one.")
        return

    now = datetime.now(ET)
    print(f"{now.strftime('%Y-%m-%d %H:%M')} pyramid-scanner starting ({len(open_pos)} positions)")

    parent_etfs = list({p["parent_etf"] for p in open_pos.values()})
    tickers = list(open_pos.keys())
    ctx = build_context(parent_etfs, tickers)
    regime = ctx["regime"]
    print(f"  Regime: vol={regime['vol_regime']} (VIX {regime['vix_level']:.1f}), breadth={regime['breadth']}, gate={'OPEN' if regime['gate_open'] else 'CLOSED'}")

    # Header
    out = []
    out.append("══════════════════════════════════════════")
    out.append(f"PYRAMID SCANNER — {now.strftime('%Y-%m-%d %H:%M ET')}")
    out.append("══════════════════════════════════════════")
    out.append(f"Regime: {'🟢 GATE OPEN' if regime['gate_open'] else '🔴 GATE CLOSED'}  vol={regime['vol_regime']} VIX={regime['vix_level']:.1f}  breadth={regime['breadth']} ({regime['pct_above_50']:.0f}%/{regime['pct_above_200']:.0f}%)")

    results = []
    for ticker, pos in open_pos.items():
        r = analyze_position(ticker, pos, ctx)
        results.append(r)
        out.append(fmt_position(r))

    text = "\n".join(out)
    print("\n" + text + "\n")
    send_discord("```\n" + text + "\n```")
    print(f"{datetime.now(ET).strftime('%Y-%m-%d %H:%M')} pyramid-scanner complete")


if __name__ == "__main__":
    main()
