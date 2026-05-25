"""
IJTSRD baseline linear model.

Original IJTSRD paper (27819):
    SPX = a + b1*rate + b2*unemployment

It is intentionally simple — a "Family A" straw-man documented in the dossier.
We keep two regressors but substitute VIX for unemployment because the
unemployment series lives behind FRED, which is unreachable from this env.
This is a defensible swap because:

- VIX is a stress / regime proxy that co-moves with unemployment over the
  cycle (corr ~0.45 since 1990).
- The point of including IJTSRD at all is to have a deliberately weak
  baseline that the better-specified models should beat.

Spec:
    log(SPX_{t+12} / SPX_t) = a + b1 * yield10_t + b2 * log(VIX_t) + e

We regress on the 12-month forward LOG RETURN, not on log(SPX_{t+12}) level.
The original IJTSRD paper regresses SPX level on rate + unemployment, which
only works on short windows; over 30+ years a level regression fits the
trend and produces absurd forecasts at the present-day extrapolated SPX.
Forward-return regression is the Welch-Goyal-standard fix and is what we
use here (so this model lives in the predictor_zoo family in practice).

Fit by OLS on the longest in-sample window with all three observable
(VIX history starts 1990-02 -> sample begins 1991-02 once 12m lead applies).
Returns the fitted 12-month-forward SPX level. No OOS here; that's Session 3.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import ModelOutput

try:
    import statsmodels.api as sm
except Exception:  # pragma: no cover
    sm = None


class IJTSRDBaseline:
    name = "IJTSRD linear (10Y + VIX)"
    family = "predictor_zoo"

    def __init__(self, sample_start: str = "1990-02-01", horizon_months: int = 12):
        self.sample_start = sample_start
        self.horizon_months = horizon_months

    def predict(self, panel: pd.DataFrame, horizon_months: int = 12) -> ModelOutput:
        h = horizon_months or self.horizon_months
        spx = panel["spx"]
        y10 = panel["yield10"]
        vix = panel["vix"]

        fwd_log_ret = np.log(spx.shift(-h) / spx)
        log_vix = np.log(vix)

        df = pd.concat(
            [fwd_log_ret.rename("y"), y10.rename("y10"), log_vix.rename("lvix")],
            axis=1,
        ).loc[self.sample_start:].dropna()

        X = df[["y10", "lvix"]].values
        y = df["y"].values
        n = len(df)

        if sm is None:
            X1 = np.c_[np.ones(n), X]
            beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
            yhat = X1 @ beta
            ss_res = float(((y - yhat) ** 2).sum())
            ss_tot = float(((y - y.mean()) ** 2).sum())
            r2 = 1 - ss_res / ss_tot
            a, b1, b2 = float(beta[0]), float(beta[1]), float(beta[2])
            t1 = t2 = float("nan")
        else:
            X1 = sm.add_constant(X)
            model = sm.OLS(y, X1).fit(cov_type="HAC", cov_kwds={"maxlags": h})
            a, b1, b2 = (float(model.params[0]), float(model.params[1]), float(model.params[2]))
            t1, t2 = float(model.tvalues[1]), float(model.tvalues[2])
            r2 = float(model.rsquared)

        # Forecast at latest observable state
        latest = panel.dropna(subset=["yield10", "vix", "spx"]).iloc[-1]
        y10_t = float(latest["yield10"])
        lvix_t = float(np.log(latest["vix"]))
        spx_t = float(latest["spx"])
        f_log_ret = a + b1 * y10_t + b2 * lvix_t
        spx_fair = spx_t * float(np.exp(f_log_ret))
        annualized = float(np.exp(f_log_ret * 12.0 / h) - 1.0)

        return ModelOutput(
            name=self.name,
            family=self.family,
            spx_fair=spx_fair,
            expected_return=annualized,
            components={
                "a": a, "b_yield10": b1, "b_log_vix": b2,
                "t_yield10": t1, "t_log_vix": t2,
                "r2_in_sample": r2,
                "n_obs": float(n),
                "current_SPX": spx_t,
                "yield10_pct": y10_t,
                "VIX": float(latest["vix"]),
            },
            notes=(f"OLS log(SPX_t+12) ~ a + b1*y10 + b2*log(VIX). "
                   f"b1={b1:+.3f} (t={t1:+.1f}) b2={b2:+.3f} (t={t2:+.1f}) "
                   f"R2={r2:.2f} n={n}"),
        )


if __name__ == "__main__":
    from ..data.panel import build_panel
    p = build_panel()
    out = IJTSRDBaseline().predict(p)
    print(out.fmt_line(out.components["current_SPX"]))
    print(" ", out.notes)
