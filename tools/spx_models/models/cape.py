"""
Shiller CAPE mean-reversion model.

Fair_PE   = rolling mean of CAPE over the past `lookback_years` years
SPX_fair  = Fair_PE * trailing 10-year average real earnings

The model assumes the long-run multiple is the right multiple. Famously says
nothing about timing — but is a robust 10-year forward return anchor.
"""

from __future__ import annotations

import pandas as pd

from .base import ModelOutput


class CAPEModel:
    name = "Shiller CAPE (mean-reversion)"
    family = "single_ratio"

    def __init__(self, lookback_years: int = 30):
        self.lookback_years = lookback_years

    def predict(self, panel: pd.DataFrame, horizon_months: int = 12) -> ModelOutput:
        # Compute trailing 10y avg of real EPS at each month
        cpi = panel["cpi"]
        eps = panel["eps_ttm"]
        # real EPS deflated to latest CPI
        latest_cpi = cpi.dropna().iloc[-1]
        real_eps = eps * (latest_cpi / cpi)
        avg_real_eps_10y = real_eps.rolling(window=120, min_periods=60).mean()

        current_row = panel.dropna(subset=["cape"]).iloc[-1]
        current_spx = float(current_row["spx"])
        current_cape = float(current_row["cape"])

        fair_pe = float(
            panel["cape"].dropna().rolling(window=self.lookback_years * 12, min_periods=120).mean().iloc[-1]
        )
        avg_real_eps = avg_real_eps_10y.loc[:current_row.name].dropna().iloc[-1]
        spx_fair = fair_pe * float(avg_real_eps)

        # Long-run expected return (Shiller's heuristic: 1/CAPE - real growth ~ 1.5%)
        implied_long_run_real = (1.0 / current_cape) - 0.0
        expected_return = implied_long_run_real

        return ModelOutput(
            name=self.name,
            family=self.family,
            spx_fair=spx_fair,
            expected_return=expected_return,
            implied_pe=fair_pe,
            components={
                "current_CAPE": current_cape,
                "fair_CAPE_30y_avg": fair_pe,
                "avg_real_EPS_10y": float(avg_real_eps),
                "current_SPX": current_spx,
            },
            notes=f"Mean-reverts current CAPE {current_cape:.1f} to {self.lookback_years}y avg {fair_pe:.1f}",
        )


if __name__ == "__main__":
    from ..data.panel import build_panel
    p = build_panel()
    out = CAPEModel().predict(p)
    print(out.fmt_line(out.components["current_SPX"]))
    print(" ", out.notes)
    for k, v in out.components.items():
        print(f"  {k}: {v:.2f}")
