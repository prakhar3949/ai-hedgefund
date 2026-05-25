"""
Rapach-Strauss-Zhou (2010, RFS) forecast combination.

W-G (2008) shows individual predictors fail OOS. Rapach-Strauss-Zhou show
that simple *combinations* of those same predictors beat the historical-mean
benchmark OOS. The simplest and most robust variant is the equal-weight mean,
which is what we report here as our primary number — with a few additional
combination schemes shown for context (mean, median, trimmed mean, DMSPE).

DMSPE (discount-mean-squared-prediction-error) is the RSZ headline result.
It weights each model i by:
    w_i = phi_i / sum_j phi_j
    phi_i = 1 / [ sum_{tau=1..t-1} theta^(t-1-tau) * (r_tau - r_hat_i,tau)^2 ]

with theta in {0.9, 1.0}. theta=1.0 gives equal weighting on past errors;
theta < 1 emphasizes recent performance. We implement theta = 1.0 here as
the in-sample stand-in. A proper recursive DMSPE evaluation is Session 3
(walk-forward backtest territory).

Reference: Rapach, Strauss & Zhou (2010) "Out-of-sample equity premium
prediction: Combination forecasts and links to the real economy", RFS.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import ModelOutput
from .welch_goyal_expanded import WelchGoyalExpanded


class RapachCombination:
    name = "Rapach-Strauss-Zhou combination"
    family = "predictor_zoo"

    def __init__(self, sample_start: str = "1990-02-01", horizon_months: int = 12,
                 dmspe_theta: float = 1.0):
        self.sample_start = sample_start
        self.horizon_months = horizon_months
        self.dmspe_theta = dmspe_theta

    def predict(self, panel: pd.DataFrame, horizon_months: int = 12) -> ModelOutput:
        h = horizon_months or self.horizon_months
        spx_t = float(panel["spx"].dropna().iloc[-1])

        wge = WelchGoyalExpanded(sample_start=self.sample_start, horizon_months=h)
        results = wge._fit_all(panel, h)
        if not results:
            return ModelOutput(name=self.name, family=self.family,
                               notes="no predictors fittable")

        names = list(results.keys())
        f_logs = np.array([results[k]["f_log"] for k in names])

        # 1. Equal-weight mean (the RSZ headline)
        f_mean = float(f_logs.mean())
        # 2. Median
        f_median = float(np.median(f_logs))
        # 3. Trimmed mean (drop 1 highest + 1 lowest)
        if len(f_logs) > 4:
            trimmed = np.sort(f_logs)[1:-1]
            f_trim = float(trimmed.mean())
        else:
            f_trim = f_mean
        # 4. DMSPE (in-sample variant): weight each predictor by 1 / in-sample MSE
        #    fitted on the W-G univariate regressions. theta=1 -> equal weighting
        #    on past errors -> w_i ~ 1 / SSR_i. We approximate SSR via 1-R2 of fit.
        r2s = np.array([results[k]["r2"] for k in names])
        # phi_i = 1 / (1 - R2_i); guard against R2 close to 1 (rare here)
        phi = 1.0 / np.clip(1.0 - r2s, 1e-3, None)
        w = phi / phi.sum()
        f_dmspe = float((w * f_logs).sum())

        outputs = {
            "mean": f_mean, "median": f_median, "trim_mean": f_trim, "dmspe_theta1": f_dmspe,
        }
        fair = {k: spx_t * float(np.exp(v)) for k, v in outputs.items()}
        spx_fair = fair["mean"]  # headline = equal-weight (RSZ recommendation)
        annualized = float(np.exp(f_mean * 12.0 / h) - 1.0)

        # Dispersion of individual forecasts -- a model uncertainty proxy
        spx_per_predictor = spx_t * np.exp(f_logs)
        disp_pct = float(spx_per_predictor.std() / spx_per_predictor.mean() * 100)

        notes_bits = [
            f"mean fair={fair['mean']:.0f}",
            f"median={fair['median']:.0f}",
            f"trim={fair['trim_mean']:.0f}",
            f"DMSPE={fair['dmspe_theta1']:.0f}",
            f"dispersion={disp_pct:.1f}% (sd/mean across {len(names)} predictors)",
        ]

        components = {
            "current_SPX": spx_t,
            "horizon_months": float(h),
            "n_predictors": float(len(names)),
            "dispersion_pct": disp_pct,
            **{f"fair_{k}": v for k, v in fair.items()},
            **{f"weight_dmspe_{k}": float(wi) for k, wi in zip(names, w)},
        }
        return ModelOutput(
            name=self.name,
            family=self.family,
            spx_fair=spx_fair,
            expected_return=annualized,
            components=components,
            notes=" | ".join(notes_bits),
        )


if __name__ == "__main__":
    from ..data.panel import build_panel
    p = build_panel()
    out = RapachCombination().predict(p)
    print(out.fmt_line(out.components["current_SPX"]))
    print(" ", out.notes)
