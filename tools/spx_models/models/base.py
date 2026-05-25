"""
Common interface for all fair-value models.

Each model implements:
    class XxxModel:
        name: str
        family: str  # "single_ratio" | "predictor_zoo" | "intrinsic" | ...
        def predict(self, panel: pd.DataFrame, horizon_months: int = 12) -> ModelOutput

ModelOutput shape:
    spx_fair          : fair-value SPX level at horizon (None if model only predicts return)
    expected_return   : annualized expected log return (None if level-only model)
    implied_pe        : implied fair P/E (if applicable)
    components        : dict of attribution components for the report
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelOutput:
    name: str
    family: str
    spx_fair: float | None = None
    expected_return: float | None = None
    implied_pe: float | None = None
    components: dict = field(default_factory=dict)
    notes: str = ""

    def fmt_line(self, current_spx: float) -> str:
        bits = [f"{self.name:30}", f"[{self.family:14}]"]
        if self.spx_fair is not None:
            gap = (self.spx_fair - current_spx) / current_spx * 100
            bits.append(f"fair={self.spx_fair:7.0f}  gap={gap:+6.1f}%")
        if self.implied_pe is not None:
            bits.append(f"PE_fair={self.implied_pe:5.1f}")
        if self.expected_return is not None:
            bits.append(f"E[r]={self.expected_return * 100:+5.1f}%/yr")
        return "  ".join(bits)
