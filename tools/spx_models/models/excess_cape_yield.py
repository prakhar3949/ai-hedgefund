"""
Shiller Excess CAPE Yield (ECY), introduced Dec 2020.

    ECY = (1 / CAPE) - real_10Y_yield

Interpretation: expected real annualized excess return of stocks over 10Y TIPS
over the next decade. Higher ECY -> stocks attractive vs bonds.

For "fair value SPX": there's no direct level forecast. Instead we map the
current ECY percentile (vs. its post-1981 history) into an implied multiple
adjustment and back into a level. This is a heuristic, not in Shiller's
original write-up.

Historical reference: ECY averaged ~3% post-1980. ECY > 4% historically
preceded above-average 10y forward returns; ECY < 1% preceded below average.
"""

from __future__ import annotations

import pandas as pd

from .base import ModelOutput


class ExcessCAPEYieldModel:
    name = "Excess CAPE Yield (Shiller 2020)"
    family = "single_ratio"

    def __init__(self, sample_start: str = "1981-01-01"):
        self.sample_start = sample_start

    def predict(self, panel: pd.DataFrame, horizon_months: int = 12) -> ModelOutput:
        cape = panel["cape"]
        real_y10 = panel["real_yield10"]
        ecy = (1.0 / cape) * 100 - real_y10
        ecy = ecy.dropna()

        current_row = panel.loc[ecy.index[-1]]
        current_spx = float(current_row["spx"])
        current_ecy = float(ecy.iloc[-1])
        current_cape = float(current_row["cape"])

        hist = ecy.loc[self.sample_start:]
        ecy_mean = float(hist.mean())
        ecy_pctl = float((hist <= current_ecy).mean() * 100)

        # Heuristic: mean-revert to historical ECY mean by shifting fair CAPE
        # Fair CAPE solves: (1/fair_CAPE)*100 - real_y10 = ecy_mean
        target_eyield_pct = ecy_mean + float(current_row["real_yield10"])
        fair_cape = 100.0 / target_eyield_pct if target_eyield_pct > 0 else float("nan")
        # Apply to current 10y avg real EPS for SPX_fair (same as CAPE model)
        latest_cpi = panel["cpi"].dropna().iloc[-1]
        real_eps = panel["eps_ttm"] * (latest_cpi / panel["cpi"])
        avg_real_eps = real_eps.rolling(120, min_periods=60).mean().loc[:ecy.index[-1]].dropna().iloc[-1]
        spx_fair = fair_cape * float(avg_real_eps) if fair_cape == fair_cape else None

        # Expected real return over 10y: current ECY + real bond yield = current 1/CAPE
        exp_return = current_ecy / 100.0 + float(current_row["real_yield10"]) / 100.0

        return ModelOutput(
            name=self.name,
            family=self.family,
            spx_fair=spx_fair,
            expected_return=exp_return,
            implied_pe=fair_cape,
            components={
                "current_CAPE": current_cape,
                "current_ECY_pct": current_ecy,
                "ECY_post1981_mean_pct": ecy_mean,
                "ECY_percentile": ecy_pctl,
                "current_real_10Y_pct": float(current_row["real_yield10"]),
                "current_SPX": current_spx,
            },
            notes=(f"Current ECY={current_ecy:.2f}% ({ecy_pctl:.0f}th pctl since 1981); "
                   f"historical mean {ecy_mean:.2f}%"),
        )


if __name__ == "__main__":
    from ..data.panel import build_panel
    p = build_panel()
    out = ExcessCAPEYieldModel().predict(p)
    print(out.fmt_line(out.components["current_SPX"]))
    print(" ", out.notes)
    for k, v in out.components.items():
        print(f"  {k}: {v:.2f}")
