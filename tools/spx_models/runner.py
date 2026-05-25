"""
spx_models unified runner.

Runs every implemented model against the current macro panel, prints a
side-by-side comparison, and posts to Discord (econ-predictor channel by
default; CLAUDE.md does not yet assign a dedicated webhook for this tool).

Usage:
    python -m spx_models.runner            # run all, post to Discord
    python -m spx_models.runner --no-post  # print only
"""

from __future__ import annotations

import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .data.panel import build_panel
from .models.cape import CAPEModel
from .models.excess_cape_yield import ExcessCAPEYieldModel
from .models.fed_model import FedModel
from .models.ijtsrd_baseline import IJTSRDBaseline
from .models.rapach_combination import RapachCombination
from .models.welch_goyal_expanded import WelchGoyalExpanded
from .models.welch_goyal_lite import WelchGoyalLite

ET = ZoneInfo("America/New_York")

DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1471466326710288559/"
    "oOh2ApQCZ__k9feKMzgzJvuDb3jESFDZvyY8mYObjoDU_RIRLKAhpZK3vzZC2ijeRFNj"
)


def send_discord(msg: str):
    for chunk in [msg[i:i + 1950] for i in range(0, len(msg), 1950)]:
        try:
            r = requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"Discord send failed: {e}", file=sys.stderr)


def calvasina_scenarios(panel):
    """
    Apply the two Calvasina scenarios via the Fed Model with a *real* yield
    adjustment, since that is closest to what Calvasina actually described.
    Returns dict of {name: (inputs, spx_fair)}.
    """
    eps = float(panel.dropna(subset=["eps_ttm_ffill"]).iloc[-1]["eps_ttm_ffill"])
    out = {}
    scenarios = [
        ("S1 RBC base       (CPI 3.3, 10Y 4.5, 0 cuts)", 3.3, 4.5),
        ("S2 RBC stagflation (CPI 3.8, 10Y 5.0, 2 hikes)", 3.8, 5.0),
    ]
    for name, cpi, y10 in scenarios:
        # Fed Model: fair PE = 1/y10
        fair_pe_naive = 100.0 / y10
        fair_naive = fair_pe_naive * eps
        # ECY-style: fair multiple such that 1/PE - real_y10 = ECY_mean (use 2.56)
        real_y10 = y10 - cpi
        fair_eyield_pct = 2.56 + real_y10
        fair_pe_ecy = 100.0 / fair_eyield_pct if fair_eyield_pct > 0 else float("nan")
        fair_ecy = fair_pe_ecy * eps if fair_pe_ecy == fair_pe_ecy else float("nan")
        out[name] = {"eps": eps, "fed_pe": fair_pe_naive, "fed_fair": fair_naive,
                     "ecy_pe": fair_pe_ecy, "ecy_fair": fair_ecy}
    return out


def main():
    post = "--no-post" not in sys.argv

    panel = build_panel()
    cur_spx = float(panel["spx"].dropna().iloc[-1])
    asof = panel.dropna(subset=["spx"]).index[-1].strftime("%Y-%m")

    models = [
        CAPEModel(),
        ExcessCAPEYieldModel(),
        FedModel(),
        IJTSRDBaseline(),
        WelchGoyalLite(),
        WelchGoyalExpanded(),
        RapachCombination(),
    ]
    outputs = [m.predict(panel) for m in models]

    fair_values = [o.spx_fair for o in outputs if o.spx_fair is not None]
    ensemble_fair = sum(fair_values) / len(fair_values) if fair_values else None

    lines = []
    lines.append("``````")
    lines.append(f"MACRO SPX MODELS (Session 2b)  {datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}")
    lines.append("=" * 70)
    lines.append(f"Current SPX: {cur_spx:,.0f}  (asof Shiller/multpl {asof})")
    lines.append(f"EPS (TTM): ${float(panel['eps_ttm_ffill'].dropna().iloc[-1]):.2f}")
    lines.append(f"10Y nominal: {float(panel['yield10'].dropna().iloc[-1]):.2f}%  "
                 f"CPI YoY: {float(panel['cpi_yoy'].dropna().iloc[-1]):.2f}%")
    lines.append("")
    lines.append("PER-MODEL FAIR VALUE:")
    for o in outputs:
        lines.append("  " + o.fmt_line(cur_spx))
        if o.notes:
            lines.append("    " + o.notes)
    lines.append("")
    if ensemble_fair is not None:
        gap = (ensemble_fair - cur_spx) / cur_spx * 100
        lines.append(f"EQUAL-WEIGHT ENSEMBLE: fair={ensemble_fair:,.0f}  gap={gap:+.1f}%")
    lines.append("")
    # Family-level breakdown so dispersion is visible at a glance
    single_ratio_outputs = [o for o in outputs if o.family == "single_ratio" and o.spx_fair]
    pzoo_outputs        = [o for o in outputs if o.family == "predictor_zoo" and o.spx_fair]
    if single_ratio_outputs:
        sr_mean = sum(o.spx_fair for o in single_ratio_outputs) / len(single_ratio_outputs)
        lines.append(f"FAMILY MEAN [single_ratio]:   {sr_mean:,.0f}  "
                     f"({(sr_mean-cur_spx)/cur_spx*100:+.1f}%, n={len(single_ratio_outputs)})")
    if pzoo_outputs:
        pz_mean = sum(o.spx_fair for o in pzoo_outputs) / len(pzoo_outputs)
        lines.append(f"FAMILY MEAN [predictor_zoo]:  {pz_mean:,.0f}  "
                     f"({(pz_mean-cur_spx)/cur_spx*100:+.1f}%, n={len(pzoo_outputs)})")
    lines.append("")
    lines.append("CALVASINA SCENARIO CHECK (RBC, May 2026):")
    lines.append("  RBC anchors: S1 -> 7929, S2 -> 7400")
    scen = calvasina_scenarios(panel)
    for name, r in scen.items():
        lines.append(f"  {name}")
        lines.append(f"     Fed Model  PE={r['fed_pe']:.1f}  fair={r['fed_fair']:,.0f}")
        lines.append(f"     ECY-frame  PE={r['ecy_pe']:.1f}  fair={r['ecy_fair']:,.0f}")
    lines.append("")
    lines.append("[Session 2b = multpl + Yahoo-macro (FRED unreachable from this env).")
    lines.append(" Models live: CAPE, ECY, Fed, IJTSRD, W-G lite, W-G expanded (10pred),")
    lines.append(" Rapach combination. Still deferred (need FRED): Chen-Roll-Ross IP/UPR")
    lines.append(" channel, full W-G with DFY/DFR/NTIS, FRBNY adaptive factors, CAY,")
    lines.append(" DDM (forward EPS via FRED proxy), Damodaran ERP, Gu-Kelly-Xiu NN.]")
    lines.append("``````")

    msg = "\n".join(lines)
    print(msg)
    if post:
        send_discord(msg)


if __name__ == "__main__":
    main()
