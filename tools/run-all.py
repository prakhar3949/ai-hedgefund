"""
Run All Finance Tools
Executes all 15 analysis scripts in sequence.
Each script posts its results to its own Discord webhook.

Usage: python run-all.py
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

# Scripts to run in order. uses_yfinance=True adds a cooldown delay after the script.
SCRIPTS = [
    ("macro-calendar.py",        "Macro Calendar",        False),
    ("econ-release-analysis.py", "Econ Release Analysis", False),
    ("econometrics-report.py",   "Econometrics Report",   False),
    ("technicals-scanner.py",    "Technicals Scanner",    True),
    ("volatility-regime.py",     "Volatility Regime",     False),
    ("sector-rotation.py",       "Sector Rotation",       False),
    ("rrg-scanner.py",           "RRG Scanner",           False),
    ("breadth-scanner.py",       "Market Breadth",        False),
    ("bubble-scanner.py",        "Bubble Scanner",         False),
    ("volume-exhaustion-scanner.py", "Volume Exhaustion Scanner", False),
    ("gex-profile.py",           "GEX Profile",            False),
    ("fx-models.py",             "FX Models",             True),
    ("econ-predictor.py",        "Econ Predictor",        False),
    ("sortino-optimizer.py",     "Sortino Optimizer",     False),
    ("stock-discovery.py",        "Stock Discovery",        False),
    ("fundamentals-scanner.py",  "Fundamentals Scanner",   False),
    ("trade-setup.py",           "Trade Setup Scanner",    False),
    ("early-trend-scanner.py",   "Early Trend Scanner",   False),
    ("late-trend-scanner.py",    "Late Trend Scanner",    False),
]

YF_COOLDOWN = 10  # seconds between yfinance-heavy scripts


def run_script(filename: str, label: str) -> bool:
    """Run a single script and return True if it succeeded."""
    script_path = TOOLS_DIR / filename
    if not script_path.exists():
        print(f"  SKIP: {filename} not found")
        return False

    start = time.time()
    # breadth-scanner now includes a Russell-3000 52-week breadth scan (~5min Yahoo fetch),
    # so it gets a longer ceiling than other scripts.
    per_script_timeout = 900 if filename == "breadth-scanner.py" else 300
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=per_script_timeout,
            cwd=str(TOOLS_DIR),
        )
        elapsed = time.time() - start

        if result.returncode == 0:
            print(f"  OK   {label} ({elapsed:.1f}s)")
            if result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    print(f"        {line}")
            return True
        else:
            print(f"  FAIL {label} (exit {result.returncode}, {elapsed:.1f}s)")
            if result.stderr.strip():
                for line in result.stderr.strip().split("\n")[-5:]:
                    print(f"        {line}")
            return False

    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT {label} (>300s)")
        return False
    except Exception as e:
        print(f"  ERROR {label}: {e}")
        return False


def main():
    now = datetime.now(ET)
    print(f"{'='*50}")
    print(f"  Finance Tools Runner")
    print(f"  {now.strftime('%A, %B %d, %Y %I:%M %p ET')}")
    print(f"{'='*50}")
    print()

    passed = 0
    failed = 0

    for filename, label, uses_yf in SCRIPTS:
        if run_script(filename, label):
            passed += 1
        else:
            failed += 1
        print()
        # Cooldown after yfinance-heavy scripts to avoid rate limiting
        if uses_yf:
            print(f"        [cooldown {YF_COOLDOWN}s to avoid yfinance rate limit]")
            time.sleep(YF_COOLDOWN)
            print()

    print(f"{'='*50}")
    print(f"  Done: {passed} passed, {failed} failed")
    elapsed_total = time.time()
    print(f"  {datetime.now(ET).strftime('%I:%M %p ET')}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
