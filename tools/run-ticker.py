"""
Run Ticker-Specific Analysis

Runs all per-ticker analysis tools on one or more tickers sequentially:
  1. fundamental-thesis.py    — per-ticker fundamental thesis (sector pack, bull/bear, buybacks)
  2. fundamentals-scanner.py  — quality + valuation overlay (cohort scoring)
  3. entry-analyzer.py        — multi-timeframe entry scoring (PRIME/GOOD/MIXED/AVOID + first-phase plan)
  4. gex-profile-equity.py    — per-ticker GEX profile (CBOE delayed options chain)

Each tool posts to its own Discord webhook. Tickers can be passed with or without
the leading `$` (e.g. `EXLS` or `$EXLS`).

Usage:
    python run-ticker.py EXLS G
    python run-ticker.py $AAPL $TSLA $NVDA
"""

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOOLS_DIR = Path(__file__).resolve().parent

# (filename, human label, timeout_seconds)
SCRIPTS = [
    ("fundamental-thesis.py",   "Fundamental Thesis",     300),
    ("fundamentals-scanner.py", "Fundamentals Scanner",   300),
    ("entry-analyzer.py",       "Entry Analyzer",         300),
    ("gex-profile-equity.py",   "GEX Profile (Equity)",   300),
]


def run_script(filename: str, label: str, tickers: list[str], timeout: int) -> bool:
    """Run a single script with tickers as positional args. Returns True on success."""
    script_path = TOOLS_DIR / filename
    if not script_path.exists():
        print(f"  SKIP {label} — {filename} not found")
        return False

    # PYTHONIOENCODING=utf-8 avoids Windows cp1252 crashes on arrow/unicode chars
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    cmd = [sys.executable, str(script_path), *tickers]

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(TOOLS_DIR),
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = time.time() - start
        if result.returncode == 0:
            print(f"  OK   {label} ({elapsed:.1f}s)")
            if result.stdout.strip():
                for line in result.stdout.strip().split("\n")[-8:]:
                    print(f"        {line}")
            return True
        else:
            print(f"  FAIL {label} (exit {result.returncode}, {elapsed:.1f}s)")
            tail = (result.stderr or result.stdout or "").strip().split("\n")[-8:]
            for line in tail:
                print(f"        {line}")
            return False
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT {label} (>{timeout}s)")
        return False
    except Exception as e:
        print(f"  ERROR {label}: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python run-ticker.py TICKER [TICKER ...]")
        print("Example: python run-ticker.py EXLS G AAPL")
        sys.exit(1)

    tickers = [t.upper().lstrip("$").strip() for t in sys.argv[1:] if t.strip()]
    tickers = [t for t in tickers if t]
    if not tickers:
        print("No valid tickers parsed from arguments.")
        sys.exit(1)

    now = datetime.now(ET)
    print(f"{'='*60}")
    print(f"  Ticker Analysis Runner")
    print(f"  {now.strftime('%A, %B %d, %Y %I:%M %p ET')}")
    print(f"  Tickers ({len(tickers)}): {', '.join(tickers)}")
    print(f"{'='*60}\n")

    passed = 0
    failed = 0
    for filename, label, timeout in SCRIPTS:
        if run_script(filename, label, tickers, timeout):
            passed += 1
        else:
            failed += 1
        print()

    print(f"{'='*60}")
    print(f"  Done: {passed} passed, {failed} failed  |  {datetime.now(ET).strftime('%I:%M %p ET')}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
