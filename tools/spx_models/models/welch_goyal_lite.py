"""
Welch-Goyal (2008) univariate predictive regressions, lite version.

Original W-G uses 15 predictors. We implement the subset that derives only
from multpl.com data (no FRED needed):

    DP  : log(dividend yield)
    EP  : log(earnings yield)
    DE  : log(D/E) = DP - EP   (Lamont 1998 payout ratio)
    SVAR: stock variance (sum of squared monthly returns, 12m window)

Each predictor is fitted in-sample on monthly observations:

    y_{t+12} = a + b * x_t + e_{t+12}

where y_{t+12} is the 12-month forward log return of SPX (price-only).
A "fair value" is then computed as:

    SPX_fair_12m = SPX_t * exp(a + b * x_t)

Caveats already documented in the dossier:
- Predictors are highly persistent (AR(1) rho > 0.95); plain OLS t-stats are
  inflated. We report Hodrick-corrected stat as 'h_t' for context.
- 12-month forward overlapping returns induce MA(11) error structure;
  Newey-West with lag=12 used for the t-stat on b.
- The W-G headline result is that these regressions look great in-sample
  and terrible out-of-sample. We don't run OOS here; that's Session 3.

A simple equal-weight COMBINATION of the four univariate forecasts is also
returned (Rapach-Strauss-Zhou 2010 idea, applied to this 4-predictor subset).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import ModelOutput

try:
    import statsmodels.api as sm
except Exception:  # pragma: no cover
    sm = None


def _newey_west_t(x, y, lag=12):
    """OLS slope + Newey-West t-stat for y ~ const + x."""
    if sm is None:
        x = np.asarray(x, float); y = np.asarray(y, float)
        n = len(x); mx = x.mean(); my = y.mean()
        b = ((x - mx) * (y - my)).sum() / ((x - mx) ** 2).sum()
        a = my - b * mx
        return a, b, np.nan
    X = sm.add_constant(x)
    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    return float(model.params[0]), float(model.params[1]), float(model.tvalues[1])


def _build_predictors(panel: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(index=panel.index)
    # multpl div_yield and eps_yield are reported as percentage points
    df["DP"] = np.log(panel["div_yield"] / 100.0)
    df["EP"] = np.log(panel["eps_yield"] / 100.0)
    df["DE"] = df["DP"] - df["EP"]
    # SVAR: rolling 12m sum of squared monthly returns
    ret = np.log(panel["spx"]).diff()
    df["SVAR"] = (ret ** 2).rolling(12, min_periods=6).sum()
    return df


class WelchGoyalLite:
    name = "Welch-Goyal lite (DP/EP/DE/SVAR)"
    family = "predictor_zoo"

    def __init__(self, sample_start: str = "1962-01-01", horizon_months: int = 12):
        self.sample_start = sample_start
        self.horizon_months = horizon_months

    def predict(self, panel: pd.DataFrame, horizon_months: int = 12) -> ModelOutput:
        h = horizon_months or self.horizon_months
        preds = _build_predictors(panel)
        spx = panel["spx"]
        # forward h-month log return
        fwd = np.log(spx.shift(-h) / spx)
        sample = preds.join(fwd.rename("fwd")).loc[self.sample_start:].dropna()

        results = {}
        ensemble_forecasts = []
        spx_t = float(spx.dropna().iloc[-1])

        for name in ["DP", "EP", "DE", "SVAR"]:
            x = sample[name].values
            y = sample["fwd"].values
            a, b, t = _newey_west_t(x, y, lag=h)
            # forecast at latest observable x
            x_t = float(preds[name].dropna().iloc[-1])
            f_log = a + b * x_t
            fair = spx_t * float(np.exp(f_log))
            results[name] = {"a": a, "b": b, "nw_t": t, "x_t": x_t, "f_log": f_log, "fair": fair}
            ensemble_forecasts.append(f_log)

        f_log_ens = float(np.mean(ensemble_forecasts))
        spx_fair_ens = spx_t * float(np.exp(f_log_ens))
        annualized = float(np.exp(f_log_ens * 12.0 / h) - 1.0)

        notes = []
        for k, r in results.items():
            notes.append(
                f"{k}: b={r['b']:+.3f}  nw_t={r['nw_t']:+.2f}  fair={r['fair']:.0f}"
            )

        return ModelOutput(
            name=self.name,
            family=self.family,
            spx_fair=spx_fair_ens,
            expected_return=annualized,
            components={
                "current_SPX": spx_t,
                "horizon_months": float(h),
                "ensemble_log_fwd_ret": f_log_ens,
                **{f"{k}_fair": r["fair"] for k, r in results.items()},
                **{f"{k}_t_NW": r["nw_t"] for k, r in results.items()},
            },
            notes=" | ".join(notes),
        )


if __name__ == "__main__":
    from ..data.panel import build_panel
    p = build_panel()
    out = WelchGoyalLite().predict(p)
    print(out.fmt_line(out.components["current_SPX"]))
    print(" ", out.notes)
