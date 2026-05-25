#!/home/nicknemo17/clawd/venv/bin/python
"""
Options-Implied Earnings Move Calculator
Calculates expected move from options straddle pricing before earnings.

Runs on earnings days:
  - Pre-earnings (6:05 AM PST): posts expected move to #trade-alerts
  - Post-earnings (next day 9:30 AM EST): compares actual vs expected

Schedule: called by morning-briefing or standalone at 6:05 AM PST on earnings days.
Also runs standalone for post-earnings comparison at 6:15 AM PST day after.

Data source: yfinance options chains (free, no API cost).

Methodology:
  - Find nearest expiry AFTER earnings date
  - Get ATM straddle price (call + put at strike nearest current price)
  - Expected move = straddle price / stock price
  - Compare to historical earnings moves
"""

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf
import numpy as np

ET = ZoneInfo("America/New_York")
CLAWD = Path.home() / "clawd"
STATE_FILE = CLAWD / "memory/options-implied-moves.json"

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


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"expected_moves": {}, "history": []}


def save_state(state: dict):
    # Keep last 50 entries in history
    state["history"] = state["history"][-50:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_implied_move(ticker: str) -> dict | None:
    """Calculate options-implied earnings move from ATM straddle."""
    try:
        t = yf.Ticker(ticker)
        price = t.history(period="1d")["Close"].iloc[-1]

        # Get options expirations
        exps = t.options
        if not exps:
            return None

        # Find nearest expiry that's at least 1 day away
        now = datetime.now(ET).date()
        valid_exps = [e for e in exps if datetime.strptime(e, "%Y-%m-%d").date() > now]
        if not valid_exps:
            return None

        nearest_exp = valid_exps[0]

        # Get options chain
        chain = t.option_chain(nearest_exp)
        calls = chain.calls
        puts = chain.puts

        if calls.empty or puts.empty:
            return None

        # Find ATM strike (closest to current price)
        strikes = calls["strike"].values
        atm_idx = np.argmin(np.abs(strikes - price))
        atm_strike = strikes[atm_idx]

        # Get ATM call and put prices (use mid of bid/ask)
        atm_call = calls[calls["strike"] == atm_strike]
        atm_put = puts[puts["strike"] == atm_strike]

        if atm_call.empty or atm_put.empty:
            return None

        call_mid = (atm_call["bid"].iloc[0] + atm_call["ask"].iloc[0]) / 2
        put_mid = (atm_put["bid"].iloc[0] + atm_put["ask"].iloc[0]) / 2

        straddle_price = call_mid + put_mid
        implied_move_pct = (straddle_price / price) * 100

        # Get IV from the options
        call_iv = atm_call["impliedVolatility"].iloc[0] * 100 if "impliedVolatility" in atm_call.columns else None
        put_iv = atm_put["impliedVolatility"].iloc[0] * 100 if "impliedVolatility" in atm_put.columns else None

        # Days to expiry for context
        dte = (datetime.strptime(nearest_exp, "%Y-%m-%d").date() - now).days

        return {
            "ticker": ticker,
            "price": round(float(price), 2),
            "atm_strike": float(atm_strike),
            "straddle_price": round(float(straddle_price), 2),
            "implied_move_pct": round(float(implied_move_pct), 1),
            "implied_move_dollar": round(float(straddle_price), 2),
            "expiry": nearest_exp,
            "dte": dte,
            "call_iv": round(float(call_iv), 1) if call_iv else None,
            "put_iv": round(float(put_iv), 1) if put_iv else None,
        }
    except Exception as e:
        print(f"  Error computing implied move for {ticker}: {e}")
        return None


def get_historical_earnings_moves(ticker: str, n: int = 4) -> list[float]:
    """Get actual moves from last N earnings (from yfinance earnings_dates)."""
    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is None or ed.empty:
            return []

        now = datetime.now(ET)
        past_dates = []
        for idx in sorted(ed.index, reverse=True):
            dt = idx.to_pydatetime()
            if hasattr(dt, 'tzinfo') and dt.tzinfo:
                pass
            else:
                dt = dt.replace(tzinfo=ET)
            if dt.date() < now.date():
                reported = ed.loc[idx].get("Reported EPS")
                if reported is not None and not (isinstance(reported, float) and reported != reported):
                    past_dates.append(dt.strftime("%Y-%m-%d"))
                    if len(past_dates) >= n:
                        break

        if not past_dates:
            return []

        # Get historical prices and compute actual moves
        hist = t.history(period="2y", interval="1d")
        if hist.empty:
            return []

        moves = []
        for date_str in past_dates:
            try:
                # Find the trading day at/after earnings
                mask = hist.index >= date_str
                if not mask.any():
                    continue
                post_idx = hist.index[mask][0]
                post_pos = hist.index.get_loc(post_idx)
                if post_pos < 1:
                    continue
                pre_close = hist["Close"].iloc[post_pos - 1]
                # Use the next day's open for overnight moves or close for intraday
                post_price = hist["Close"].iloc[post_pos]
                move = ((post_price - pre_close) / pre_close) * 100
                moves.append(round(float(move), 1))
            except:
                continue

        return moves
    except:
        return []


def run_pre_earnings():
    """Pre-earnings: calculate and post expected moves for today's reporters."""
    now_et = datetime.now(ET)
    today_str = now_et.strftime("%Y-%m-%d")

    # Load earnings schedule
    try:
        with open(CLAWD / "memory/earnings-schedule.json") as f:
            schedule = json.load(f)
    except:
        print("No earnings schedule found")
        return

    today_earnings = schedule.get("by_date", {}).get(today_str, [])
    if not today_earnings:
        print(f"No earnings today ({today_str})")
        return

    state = load_state()
    results = []

    for entry in today_earnings:
        ticker = entry["ticker"]
        timing = entry.get("timing", "?")
        category = entry.get("category", "")
        weight = entry.get("weight")

        print(f"  Computing implied move for {ticker}...")
        im = get_implied_move(ticker)
        if not im:
            continue

        # Historical moves for context
        hist_moves = get_historical_earnings_moves(ticker)
        im["hist_moves"] = hist_moves
        im["avg_hist_move"] = round(np.mean([abs(m) for m in hist_moves]), 1) if hist_moves else None
        im["timing"] = timing
        im["category"] = category
        im["weight"] = weight
        results.append(im)

        # Save for post-earnings comparison
        state["expected_moves"][ticker] = {
            "date": today_str,
            "price_before": im["price"],
            "implied_move_pct": im["implied_move_pct"],
            "timing": timing,
        }

    if not results:
        print("No options data available for today's earnings")
        return

    # Build message
    lines = [f"**Earnings Expected Moves** ({now_et.strftime('%a %b %d')})", ""]

    for r in sorted(results, key=lambda x: x["implied_move_pct"], reverse=True):
        ticker = r["ticker"]
        timing_str = "BMO" if r["timing"] == "BMO" else "AMC"
        weight_str = f" | {r['weight']:.1f}% of port" if r.get("weight") else ""
        category_str = f" [{r['category']}]" if r.get("category") else ""

        lines.append(f"**{ticker}** ({timing_str}){category_str}{weight_str}")
        lines.append(f"  Price: ${r['price']:.2f} | Expected Move: **{r['implied_move_pct']:.1f}%** (${r['implied_move_dollar']:.2f})")
        lines.append(f"  Straddle: ${r['straddle_price']:.2f} @ {r['atm_strike']:.0f} strike | Exp: {r['expiry']} ({r['dte']}d)")

        if r.get("avg_hist_move"):
            hist_str = ", ".join(f"{m:+.1f}%" for m in r["hist_moves"][:4])
            over_under = "over-pricing" if r["implied_move_pct"] > r["avg_hist_move"] * 1.2 else "under-pricing" if r["implied_move_pct"] < r["avg_hist_move"] * 0.8 else "fairly pricing"
            lines.append(f"  Hist avg: {r['avg_hist_move']:.1f}% | Last 4: {hist_str}")
            lines.append(f"  Market {over_under} this earnings move")

        lines.append("")

    message = "\n".join(lines).strip()
    send_discord(RESEARCH_CH, message)
    print(f"Posted earnings expected moves ({len(message)} chars)")

    save_state(state)


def run_post_earnings():
    """Post-earnings: compare actual move to implied move for yesterday's reporters."""
    now_et = datetime.now(ET)
    state = load_state()

    # Find yesterday's expected moves
    yesterday = (now_et - timedelta(days=1)).strftime("%Y-%m-%d")
    comparisons = []

    for ticker, expected in list(state["expected_moves"].items()):
        if expected["date"] != yesterday:
            continue

        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d", interval="1d")
            if len(hist) < 2:
                continue

            current_price = hist["Close"].iloc[-1]
            actual_move = ((current_price - expected["price_before"]) / expected["price_before"]) * 100

            comparisons.append({
                "ticker": ticker,
                "expected_pct": expected["implied_move_pct"],
                "actual_pct": round(float(actual_move), 1),
                "price_before": expected["price_before"],
                "price_after": round(float(current_price), 2),
                "beat_implied": abs(actual_move) > expected["implied_move_pct"],
            })

            # Move to history
            state["history"].append({
                "ticker": ticker,
                "date": yesterday,
                "expected": expected["implied_move_pct"],
                "actual": round(float(actual_move), 1),
            })
            del state["expected_moves"][ticker]

        except:
            continue

    if not comparisons:
        print("No post-earnings comparisons to make")
        return

    # Build message
    lines = [f"**Earnings Move Scorecard** ({now_et.strftime('%a %b %d')})", ""]

    for c in sorted(comparisons, key=lambda x: abs(x["actual_pct"]), reverse=True):
        direction = "📈" if c["actual_pct"] > 0 else "📉"
        surprise = "BEAT IMPLIED" if c["beat_implied"] else "within expected"

        lines.append(
            f"{direction} **{c['ticker']}**: {c['actual_pct']:+.1f}% actual vs "
            f"{c['expected_pct']:.1f}% expected — **{surprise}**"
        )
        lines.append(f"  ${c['price_before']:.2f} -> ${c['price_after']:.2f}")

    message = "\n".join(lines)
    send_discord(RESEARCH_CH, message)
    print(f"Posted earnings scorecard ({len(message)} chars)")

    save_state(state)


def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"

    now_et = datetime.now(ET)
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Options implied move ({mode})")

    if mode == "post":
        run_post_earnings()
    else:
        run_pre_earnings()

    # Popen sends complete independently after script exits
    print(f"{now_et.strftime('%Y-%m-%d %H:%M:%S')} Complete")


if __name__ == "__main__":
    main()
