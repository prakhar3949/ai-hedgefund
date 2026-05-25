#!/usr/bin/env python3
"""
COHR Earnings Monitor
Checks for earnings release and compares to estimates + thesis
"""

import yfinance as yf
import json
import subprocess
from datetime import datetime

# Consensus estimates (from yfinance as of 2026-02-03)
ESTIMATES = {
    "eps": {
        "consensus": 1.21,
        "low": 1.10,
        "high": 1.26,
        "year_ago": 0.95
    },
    "revenue": {
        "consensus": 1.64e9,  # $1.64B
        "low": 1.61e9,
        "high": 1.67e9,
        "year_ago": 1.43e9
    }
}

# Nick's thesis key points
THESIS = {
    "core": "Optical interconnects = picks-and-shovels of AI boom",
    "key_drivers": [
        "Memory wall creates two-speed datacenter - optics running full speed",
        "Scale advantage over LITE",
        "HBM shortage validates thesis",
        "AI datacenter demand accelerating"
    ],
    "watch_for": [
        "AI/datacenter revenue growth",
        "Transceiver demand commentary",
        "Gross margin expansion",
        "Guidance vs LITE's +18% beat"
    ]
}

def get_earnings():
    """Check if COHR has reported earnings"""
    t = yf.Ticker('COHR')

    # Get latest quarterly earnings
    try:
        earnings = t.quarterly_earnings
        if earnings is not None and len(earnings) > 0:
            latest = earnings.iloc[0]
            return {
                "reported": True,
                "eps": latest.get('Actual', None),
                "revenue": None  # Need to get from financials
            }
    except:
        pass

    # Try news for earnings announcement
    news = t.news
    for item in news[:10]:
        content = item.get('content', item)
        title = (content.get('title', '') or '').lower()
        if 'coherent' in title and ('earnings' in title or 'q2' in title or 'results' in title):
            if 'report' in title or 'beat' in title or 'miss' in title:
                return {"reported": True, "news": content.get('title', '')}

    return {"reported": False}

def analyze_results(eps_actual, rev_actual):
    """Compare actuals to estimates and thesis"""

    analysis = []

    # EPS analysis
    eps_est = ESTIMATES['eps']['consensus']
    eps_beat = ((eps_actual - eps_est) / eps_est) * 100
    eps_yoy = ((eps_actual - ESTIMATES['eps']['year_ago']) / ESTIMATES['eps']['year_ago']) * 100

    if eps_actual > ESTIMATES['eps']['high']:
        analysis.append(f"🟢 EPS SMASH: ${eps_actual:.2f} vs ${eps_est:.2f} est (+{eps_beat:.1f}% beat)")
    elif eps_actual > eps_est:
        analysis.append(f"🟢 EPS BEAT: ${eps_actual:.2f} vs ${eps_est:.2f} est (+{eps_beat:.1f}%)")
    elif eps_actual < ESTIMATES['eps']['low']:
        analysis.append(f"🔴 EPS MISS: ${eps_actual:.2f} vs ${eps_est:.2f} est ({eps_beat:.1f}%)")
    else:
        analysis.append(f"⚪ EPS IN-LINE: ${eps_actual:.2f} vs ${eps_est:.2f} est")

    analysis.append(f"   YoY: +{eps_yoy:.1f}% (vs +27% expected)")

    # Revenue analysis
    if rev_actual:
        rev_est = ESTIMATES['revenue']['consensus']
        rev_beat = ((rev_actual - rev_est) / rev_est) * 100
        rev_yoy = ((rev_actual - ESTIMATES['revenue']['year_ago']) / ESTIMATES['revenue']['year_ago']) * 100

        if rev_actual > ESTIMATES['revenue']['high']:
            analysis.append(f"🟢 REV SMASH: ${rev_actual/1e9:.2f}B vs ${rev_est/1e9:.2f}B est (+{rev_beat:.1f}%)")
        elif rev_actual > rev_est:
            analysis.append(f"🟢 REV BEAT: ${rev_actual/1e9:.2f}B vs ${rev_est/1e9:.2f}B est (+{rev_beat:.1f}%)")
        elif rev_actual < ESTIMATES['revenue']['low']:
            analysis.append(f"🔴 REV MISS: ${rev_actual/1e9:.2f}B vs ${rev_est/1e9:.2f}B est ({rev_beat:.1f}%)")
        else:
            analysis.append(f"⚪ REV IN-LINE: ${rev_actual/1e9:.2f}B vs ${rev_est/1e9:.2f}B est")

        analysis.append(f"   YoY: +{rev_yoy:.1f}% (vs +14% expected)")

    return analysis

def thesis_check(eps_actual, rev_actual, guidance_beat=None):
    """Check results against Nick's thesis"""

    checks = []

    # Core thesis validation
    checks.append("\n📋 THESIS CHECK:")
    checks.append(f"Core: {THESIS['core']}")

    # Compare to LITE's +18% beat
    eps_beat_pct = ((eps_actual - ESTIMATES['eps']['consensus']) / ESTIMATES['eps']['consensus']) * 100

    if eps_beat_pct >= 18:
        checks.append("✅ Beat matches/exceeds LITE's +18% - optics demand CONFIRMED")
    elif eps_beat_pct >= 10:
        checks.append("✅ Strong beat - thesis intact, optics demand solid")
    elif eps_beat_pct >= 0:
        checks.append("⚠️ Modest beat - thesis holds but watch guidance")
    else:
        checks.append("⚠️ Miss - need to hear call for thesis validation")

    checks.append("\n🔍 WATCH FOR ON CALL:")
    for item in THESIS['watch_for']:
        checks.append(f"  • {item}")

    return checks

def format_alert(results, analysis, thesis):
    """Format the full alert message"""

    lines = [
        "🚨 **COHR EARNINGS RELEASED**",
        "",
        "**Results vs Estimates:**"
    ]
    lines.extend(analysis)
    lines.extend(thesis)

    lines.append("\n📊 Position: 14.9% of portfolio (LARGEST HOLDING)")
    lines.append("🎯 Status: HIGH_CONVICTION")

    return "\n".join(lines)

if __name__ == "__main__":
    import sys

    # For testing with manual input
    if len(sys.argv) >= 2:
        eps = float(sys.argv[1])
        rev = float(sys.argv[2]) * 1e9 if len(sys.argv) > 2 else None

        analysis = analyze_results(eps, rev)
        thesis = thesis_check(eps, rev)
        alert = format_alert(None, analysis, thesis)
        print(alert)
    else:
        # Check if earnings released
        result = get_earnings()
        print(json.dumps(result, indent=2, default=str))
