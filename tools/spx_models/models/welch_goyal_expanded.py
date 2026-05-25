"""
Welch-Goyal (2008) expanded univariate predictive regressions.

This file replaces the 4-predictor "lite" version with 10 of the 15 W-G
canonical predictors — every one we can compute from multpl + Yahoo without
hitting FRED.

Predictors implemented:
    DP   : log(D/P)        -- multpl dividend yield
    DY   : log(D_t / P_{t-1})  -- W-G lagged-price div yield (panel `dy_lag`)
    EP   : log(E/P)        -- multpl earnings yield
    DE   : DP - EP         -- payout ratio (Lamont 1998)
    BM   : book / market   -- multpl book value / spx
    TBL  : 3M T-bill yield -- Yahoo ^IRX
    LTY  : 10Y yield       -- multpl 10-year-treasury-rate
    TMS  : term spread     -- LTY - TBL (panel `term_spread`)
    INFL : CPI YoY %       -- multpl cpi
    SVAR : 12m rolling sum of squared monthly log returns

Deferred to a future session when FRED is reachable:
    NTIS : net equity issuance / market cap   -- needs WRDS or FRED proxy
    DFY  : Baa - Aaa default spread           -- FRED BAA10YM / AAA
    DFR  : LT corp return - LT govt return    -- FRED corp/treasury indices
    LTR  : LT bond return                     -- FRED
    IK   : Cochrane investment-capital ratio  -- BEA NIPA quarterly

Regression spec (Welch & Goyal 2008):
    r_{t+h} = a + b * x_t + e_{t+h}

where r_{t+h} is the SPX log return over months t -> t+h (default h = 12).
Newey-West HAC standard errors with lag = h are used; plain OLS t-stats are
inflated because the regressors are AR(1) with rho close to 1.

Forecast at the latest observable x_t gives implied forward log return and
fair-value SPX = SPX_t * exp(f_log).

The "ensemble" output is the equal-weight mean of the 10 univariate forecasts.
This is the simplest Rapach-Strauss-Zhou (2010) combination; a separate
RapachCombination class provides the dispersion / weight-by-fit variants.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import ModelOutput

try:
    import statsmodels.api as sm
except Exception:  # pragma: no cover
    sm = None


PREDICTOR_FNS: dict[str, "callable"] = {}


def predictor(name):
    def deco(fn):
        PREDICTOR_FNS[name] = fn
        return fn
    return deco


@predictor("DP")
def _dp(panel):
    return np.log(panel["div_yield"] / 100.0)


@predictor("DY")
def _dy(panel):
    # `dy_lag` = log(D_t / P_{t-1})  — already computed in panel.py
    return panel["dy_lag"]


@predictor("EP")
def _ep(panel):
    return np.log(panel["eps_yield"] / 100.0)


@predictor("DE")
def _de(panel):
    return np.log(panel["div_yield"] / 100.0) - np.log(panel["eps_yield"] / 100.0)


@predictor("BM")
def _bm(panel):
    return np.log(panel["bm"])


@predictor("TBL")
def _tbl(panel):
    return panel["tbl"] / 100.0  # as decimal


@predictor("LTY")
def _lty(panel):
    return panel["yield10"] / 100.0


@predictor("TMS")
def _tms(panel):
    return panel["term_spread"] / 100.0


@predictor("INFL")
def _infl(panel):
    return panel["cpi_yoy"] / 100.0


@predictor("SVAR")
def _svar(panel):
    ret = np.log(panel["spx"]).diff()
    return (ret ** 2).rolling(12, min_periods=6).sum()


def _nw_fit(x, y, lag):
    """OLS slope + Newey-West t-stat for y ~ const + x."""
    if sm is None:
        x = np.asarray(x, float); y = np.asarray(y, float)
        n = len(x); mx = x.mean(); my = y.mean()
        b = ((x - mx) * (y - my)).sum() / ((x - mx) ** 2).sum()
        a = my - b * mx
        return a, b, float("nan"), float("nan")
    X = sm.add_constant(x)
    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    return float(model.params[0]), float(model.params[1]), float(model.tvalues[1]), float(model.rsquared)


class WelchGoyalExpanded:
    name = "Welch-Goyal expanded (10 predictors)"
    family = "predictor_zoo"

    def __init__(self, sample_start: str = "1990-02-01", horizon_months: int = 12):
        # 1990-02 = first month with VIX available; TBL/TMS available 1986-05.
        # We start at 1990-02 because some predictors (BM) ffill from quarterly
        # multpl points and we want a uniform sample across predictors. Models
        # that don't need VIX could go earlier; for simplicity, single window.
        self.sample_start = sample_start
        self.horizon_months = horizon_months

    def _fit_all(self, panel, h):
        spx = panel["spx"]
        fwd = np.log(spx.shift(-h) / spx).rename("y")
        results = {}
        for name, fn in PREDICTOR_FNS.items():
            try:
                x_series = fn(panel).rename("x")
            except KeyError:
                continue
            sample = pd.concat([x_series, fwd], axis=1).loc[self.sample_start:].dropna()
            if len(sample) < 60:
                continue
            a, b, t, r2 = _nw_fit(sample["x"].values, sample["y"].values, lag=h)
            x_t_series = x_series.dropna()
            if x_t_series.empty:
                continue
            x_t = float(x_t_series.iloc[-1])
            f_log = a + b * x_t
            results[name] = {
                "a": a, "b": b, "nw_t": t, "r2": r2,
                "x_t": x_t, "f_log": f_log, "n": float(len(sample)),
            }
        return results

    def predict(self, panel: pd.DataFrame, horizon_months: int = 12) -> ModelOutput:
        h = horizon_months or self.horizon_months
        spx_t = float(panel["spx"].dropna().iloc[-1])
        results = self._fit_all(panel, h)
        if not results:
            return ModelOutput(name=self.name, family=self.family,
                               notes="no predictors fittable")
        ens = float(np.mean([r["f_log"] for r in results.values()]))
        spx_fair = spx_t * float(np.exp(ens))
        annualized = float(np.exp(ens * 12.0 / h) - 1.0)
        notes = " | ".join(
            f"{k}: b={r['b']:+.3f} t={r['nw_t']:+.1f} fair={spx_t * np.exp(r['f_log']):.0f}"
            for k, r in results.items()
        )
        components = {"current_SPX": spx_t, "horizon_months": float(h),
                      "ensemble_log_fwd_ret": ens, "n_predictors": float(len(results))}
        for k, r in results.items():
            components[f"{k}_fair"] = spx_t * float(np.exp(r["f_log"]))
            components[f"{k}_b"] = r["b"]
            components[f"{k}_t_NW"] = r["nw_t"]
            components[f"{k}_R2"] = r["r2"]
        return ModelOutput(
            name=self.name,
            family=self.family,
            spx_fair=spx_fair,
            expected_return=annualized,
            components=components,
            notes=notes,
        )


if __name__ == "__main__":
    from ..data.panel import build_panel
    p = build_panel()
    out = WelchGoyalExpanded().predict(p)
    print(out.fmt_line(out.components["current_SPX"]))
    print(" ", out.notes)
