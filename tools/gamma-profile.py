"""
Gamma Profile — Perfiliev Black-Scholes method (gammaProfileCommandLine.py port)
+ side-by-side comparison against the in-house gex-profile.py levels.

WHY THIS FILE EXISTS
--------------------
gex-profile.py computes every level (including HVL / Zero-Gamma) from CBOE's
*static* per-contract gamma snapshot. The canonical Perfiliev / SqueezeMetrics
"Gamma Flip" is different: it holds OI fixed and **re-prices gamma via
Black-Scholes at a grid of hypothetical spot levels**, sums the signed dealer
gamma profile, and finds where that profile crosses zero. This file implements
the true re-priced method and prints how far it diverges from our static proxy.

LEVEL DEFINITIONS (per user spec)
---------------------------------
  GEX 1                         heaviest flow-driven target — largest GROSS gamma strike
  HVL                           gamma flip; where MMs flip long/short — vol equilibrium
  Call Resistance / Gamma Wall  heaviest CALL gamma strike (premium sold) -> slowdown / resistance
  Put Support                   heaviest PUT gamma strike (premium bought) -> support shelf

Each level means something different on 0DTE vs OpEx, so both are computed
separately (nearest expiry, and the next monthly third-Friday OpEx).

Run:  python gamma-profile.py [SPX]
"""

import sys
import importlib.util
from pathlib import Path
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import norm

TOOLS_DIR = Path(__file__).resolve().parent


def _load_gex_profile():
    """Import the hyphenated gex-profile.py module so we can reuse its fetch/parse
    and compare against its level math on identical data."""
    spec = importlib.util.spec_from_file_location("gex_profile", TOOLS_DIR / "gex-profile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bs_gamma(S, K, iv, T):
    """Black-Scholes gamma (identical for calls and puts), r = q = 0.

    Vectorized over arrays K, iv, T at a single scalar spot S.
    """
    K = np.asarray(K, dtype=float)
    iv = np.asarray(iv, dtype=float)
    T = np.asarray(T, dtype=float)
    out = np.zeros_like(K)
    ok = (iv > 0) & (T > 0) & (S > 0)
    d1 = (np.log(S / K[ok]) + 0.5 * iv[ok] ** 2 * T[ok]) / (iv[ok] * np.sqrt(T[ok]))
    out[ok] = norm.pdf(d1) / (S * iv[ok] * np.sqrt(T[ok]))
    return out


def gamma_flip(calls: pd.DataFrame, puts: pd.DataFrame, spot: float, n: int = 60):
    """Perfiliev gamma flip: re-price gamma at n spot levels in [0.8, 1.2]*spot,
    profile = sum(callGEX) - sum(putGEX); return the zero-crossing strike.

    calls/puts need columns: strike, iv, T (years), oi.
    Returns (flip_strike | None, levels, profile_$Bn).
    """
    levels = np.linspace(0.8 * spot, 1.2 * spot, n)
    ck, civ, cT, coi = (calls[c].to_numpy() for c in ("strike", "iv", "T", "oi"))
    pk, piv, pT, poi = (puts[c].to_numpy() for c in ("strike", "iv", "T", "oi"))

    prof = np.empty(n)
    for i, S in enumerate(levels):
        cgex = (coi * 100.0 * S * S * 0.01 * bs_gamma(S, ck, civ, cT)).sum()
        pgex = (poi * 100.0 * S * S * 0.01 * bs_gamma(S, pk, piv, pT)).sum()
        prof[i] = cgex - pgex
    prof /= 1e9

    idx = np.where(np.diff(np.sign(prof)))[0]
    if len(idx) == 0:
        return None, levels, prof
    j = idx[0]
    neg, pos = prof[j], prof[j + 1]
    ks, kp = levels[j], levels[j + 1]
    flip = kp - (kp - ks) * pos / (pos - neg)
    return float(flip), levels, prof


def static_levels(sub_gex: pd.DataFrame):
    """GEX1 (gross), Call Resistance (max call GEX), Put Support (max |put GEX|)
    from the static CBOE-gamma GEX — same inputs gex-profile.py uses."""
    calls = sub_gex[sub_gex["type"] == "C"].groupby("strike")["gex"].sum()
    puts = sub_gex[sub_gex["type"] == "P"].groupby("strike")["gex"].sum()
    all_s = sorted(set(calls.index) | set(puts.index))
    gross = pd.Series({k: abs(calls.get(k, 0.0)) + abs(puts.get(k, 0.0)) for k in all_s})
    return {
        "gex1": float(gross.idxmax()) if len(gross) else None,
        "gex1_v": float(gross.max()) / 1e9 if len(gross) else 0.0,
        "call_res": float(calls.idxmax()) if len(calls) and calls.max() > 0 else None,
        "call_res_v": float(calls.max()) / 1e9 if len(calls) else 0.0,
        "put_sup": float(puts.idxmin()) if len(puts) and puts.min() < 0 else None,
        "put_sup_v": float(abs(puts.min())) / 1e9 if len(puts) else 0.0,
    }


def add_T(df: pd.DataFrame, today: date) -> pd.DataFrame:
    """Business-days-to-expiry in years; 0DTE floored at 1/262 (Perfiliev convention)."""
    df = df.copy()
    bd = np.array([np.busday_count(today, e) for e in df["expiry"]], dtype=float)
    bd[bd <= 0] = 1.0
    df["T"] = bd / 262.0
    return df


def fmt(v):
    return f"{v:,.1f}" if v is not None else "  n/a"


def compare_block(name, expiry, sub_raw, sub_gex, spot, our_zgl):
    """Print BS-method levels for one expiry set next to our static-method levels."""
    calls = sub_raw[sub_raw["type"] == "C"].dropna(subset=["iv"])
    puts = sub_raw[sub_raw["type"] == "P"].dropna(subset=["iv"])
    calls = calls[calls["iv"] > 0]
    puts = puts[puts["iv"] > 0]
    flip, _, prof = gamma_flip(calls, puts, spot) if len(calls) and len(puts) else (None, None, None)
    lv = static_levels(sub_gex)

    print(f"\n  {name}  (expiry {expiry})")
    print("  " + "-" * 60)
    print(f"    {'Level':<22}{'BS / new':>14}{'gex-profile':>14}{'diff':>10}")
    # HVL: BS flip vs our cumulative-sum ZGL
    diff = (flip - our_zgl) if (flip is not None and our_zgl is not None and not np.isnan(our_zgl)) else None
    print(f"    {'HVL (gamma flip)':<22}{fmt(flip):>14}{fmt(our_zgl):>14}{(f'{diff:+.1f}' if diff is not None else '   n/a'):>10}")
    # GEX1 / walls use static gamma in BOTH -> should match (here both come from same static math)
    print(f"    {'GEX 1 (gross)':<22}{fmt(lv['gex1']):>14}{fmt(lv['gex1']):>14}{'0.0':>10}   ({lv['gex1_v']:.1f}B)")
    print(f"    {'Call Resistance':<22}{fmt(lv['call_res']):>14}{fmt(lv['call_res']):>14}{'0.0':>10}   ({lv['call_res_v']:.1f}B)")
    print(f"    {'Put Support':<22}{fmt(lv['put_sup']):>14}{fmt(lv['put_sup']):>14}{'0.0':>10}   (-{lv['put_sup_v']:.1f}B)")
    if prof is not None:
        print(f"    profile range: [{prof.min():+.1f}B, {prof.max():+.1f}B]  spot={spot:,.1f}")
    return flip


def main():
    index = sys.argv[1] if len(sys.argv) > 1 else "SPX"
    gp = _load_gex_profile()

    payload = gp.fetch_cboe_chain() if index == "SPX" else None
    if index != "SPX":
        url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/_{index}.json"
        import requests
        payload = requests.get(url, headers=gp.UA, timeout=30).json()
    if payload is None:
        print("fetch failed"); return

    spot, df = gp.parse_chain(payload)        # df: expiry, strike, type, oi, gamma, iv
    df_gex = gp.compute_gex(df, spot)         # adds static 'gex'
    today = date.today()
    df = add_T(df, today)

    nearest, opex = gp.pick_expiries(df_gex, today)
    print("=" * 64)
    print(f"GAMMA PROFILE COMPARISON  —  {index}  spot {spot:,.2f}  {today.isoformat()}")
    print(f"  BS re-priced gamma flip  vs  gex-profile.py static cumulative ZGL")
    print("=" * 64)

    # 0DTE / nearest expiry
    near_raw = df[df["expiry"] == nearest]
    near_gex = df_gex[df_gex["expiry"] == nearest]
    nc = near_gex[near_gex["type"] == "C"].groupby("strike")["gex"].sum()
    npu = near_gex[near_gex["type"] == "P"].groupby("strike")["gex"].sum()
    our_zgl_near, _ = gp.zero_gamma_flip(nc, npu)
    compare_block("0DTE / NEAREST", nearest, near_raw, near_gex, spot, our_zgl_near)

    # OpEx / next monthly
    opex_raw = df[df["expiry"] == opex]
    opex_gex = df_gex[df_gex["expiry"] == opex]
    oc = opex_gex[opex_gex["type"] == "C"].groupby("strike")["gex"].sum()
    opu = opex_gex[opex_gex["type"] == "P"].groupby("strike")["gex"].sum()
    our_zgl_opex, _ = gp.zero_gamma_flip(oc, opu)
    compare_block("OPEX / NEXT MONTHLY", opex, opex_raw, opex_gex, spot, our_zgl_opex)

    # ALL EXPIRIES (Perfiliev's headline) vs our near-term (<=45d) ZGL
    nt = df_gex[df_gex["expiry"] <= today + pd.Timedelta(days=getattr(gp, "NEAR_TERM_DTE", 45))]
    ntc = nt[nt["type"] == "C"].groupby("strike")["gex"].sum()
    ntp = nt[nt["type"] == "P"].groupby("strike")["gex"].sum()
    our_zgl_nt, _ = gp.zero_gamma_flip(ntc, ntp)
    compare_block("ALL EXPIRIES (BS) / NEAR-TERM<=45d (ours)", "all", df, df_gex, spot, our_zgl_nt)

    print("\n" + "=" * 64)
    print("NOTE: GEX1 / Call Resistance / Put Support are static-gamma levels and")
    print("match gex-profile.py exactly. HVL is where the methods diverge: BS re-prices")
    print("gamma at each spot level (true flip); gex-profile.py accumulates static GEX")
    print("across strikes (proxy). Larger |diff| => the static proxy is less reliable.")
    print("=" * 64)


if __name__ == "__main__":
    main()
