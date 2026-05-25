"""
Fed Model (Yardeni 1998 / Asness 2003 critique).

Fair_E/P = 10Y_nominal_yield
Fair_PE  = 1 / 10Y
SPX_fair = Fair_PE * TTM_EPS

Industry-standard straw man. Asness shows it's mostly a nominal artifact:
real expected stock returns and real bond yields don't actually co-move
1:1, so this model overstates how much equities should derate when nominal
rates rise. Kept for comparison.
"""

from __future__ import annotations

import pandas as pd

from .base import ModelOutput


class FedModel:
    name = "Fed Model (naive 1/10Y)"
    family = "single_ratio"

    def predict(self, panel: pd.DataFrame, horizon_months: int = 12) -> ModelOutput:
        valid = panel.dropna(subset=["yield10", "eps_ttm_ffill", "spx"])
        row = valid.iloc[-1]
        y10 = float(row["yield10"]) / 100.0
        eps = float(row["eps_ttm_ffill"])
        spx = float(row["spx"])
        fair_pe = 1.0 / y10
        spx_fair = fair_pe * eps
        return ModelOutput(
            name=self.name,
            family=self.family,
            spx_fair=spx_fair,
            implied_pe=fair_pe,
            components={
                "10Y_yield_pct": y10 * 100,
                "TTM_EPS": eps,
                "current_SPX": spx,
                "current_PE": spx / eps,
            },
            notes=f"Naive: Fair P/E=1/10Y={fair_pe:.1f}x at 10Y={y10*100:.2f}%",
        )


if __name__ == "__main__":
    from ..data.panel import build_panel
    p = build_panel()
    out = FedModel().predict(p)
    print(out.fmt_line(out.components["current_SPX"]))
    print(" ", out.notes)
    for k, v in out.components.items():
        print(f"  {k}: {v:.2f}")
