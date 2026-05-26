"""Sanity test for compute_oi_metrics — synthetic 7-day history for NVDA."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import importlib.util
from pathlib import Path
from datetime import date, timedelta

TOOLS_DIR = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ves", TOOLS_DIR / "volume-exhaustion-scanner.py")
ves = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ves)


def build_synthetic_history(start_call=10_000_000, start_put=5_000_000,
                              call_growth=0.05, put_growth=0.15, days=7):
    """Generate a synthetic OI series with call OI growing 5%/day and put OI growing 15%/day.
    With these values: 5-day total OI growth ≈ +43%, 5d call ≈ +28%, 5d put ≈ +101%.
    Should fire put_oi_surge and call_oi_surge."""
    today = date.today()
    series = []
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        call_oi = int(start_call * (1 + call_growth) ** i)
        put_oi = int(start_put * (1 + put_growth) ** i)
        pc = put_oi / call_oi
        series.append({
            "date": d.isoformat(),
            "total_call_oi": call_oi,
            "total_put_oi": put_oi,
            "put_call_oi_ratio": round(pc, 4),
            "top_call_strikes": [],
            "top_put_strikes": [],
        })
    return series


def main():
    print("Test 1 — both surges (call+put 5d growth above 25%)")
    history = {"NVDA": build_synthetic_history(call_growth=0.05, put_growth=0.15)}
    metrics = ves.compute_oi_metrics("NVDA", history)
    print(f"  snapshots_in_history: {metrics['snapshots_in_history']}")
    print(f"  oi_pct_change_1d:     {metrics['oi_pct_change_1d']}")
    print(f"  oi_pct_change_5d:     {metrics['oi_pct_change_5d']}")
    print(f"  call_oi_pct_change_5d: {metrics['call_oi_pct_change_5d']}")
    print(f"  put_oi_pct_change_5d:  {metrics['put_oi_pct_change_5d']}")
    print(f"  put_call_ratio_today: {metrics['put_call_ratio_today']}")
    print(f"  put_call_ratio_20d_avg: {metrics['put_call_ratio_20d_avg']}")
    print(f"  put_call_ratio_delta: {metrics['put_call_ratio_delta']}")
    print(f"  oi_trend:             {metrics['oi_trend']}")
    print(f"  call_oi_surge:        {metrics['call_oi_surge']}")
    print(f"  put_oi_surge:         {metrics['put_oi_surge']}")

    print()
    print("Test 2 — declining OI (call -5%/day, put -10%/day)")
    history = {"NVDA": build_synthetic_history(call_growth=-0.05, put_growth=-0.10)}
    metrics = ves.compute_oi_metrics("NVDA", history)
    print(f"  oi_pct_change_5d: {metrics['oi_pct_change_5d']}  trend={metrics['oi_trend']}")
    print(f"  put_call_ratio_delta: {metrics['put_call_ratio_delta']}")
    print(f"  call_surge={metrics['call_oi_surge']}  put_surge={metrics['put_oi_surge']}")

    print()
    print("Test 3 — flat OI (no daily growth)")
    history = {"NVDA": build_synthetic_history(call_growth=0.0, put_growth=0.0)}
    metrics = ves.compute_oi_metrics("NVDA", history)
    print(f"  oi_pct_change_5d: {metrics['oi_pct_change_5d']}  trend={metrics['oi_trend']}")

    print()
    print("Test 4 — only 1 snapshot (should return None)")
    history = {"NVDA": build_synthetic_history(days=1)}
    metrics = ves.compute_oi_metrics("NVDA", history)
    print(f"  metrics: {metrics}")

    print()
    print("Test 5 — _format_oi_annotation for CAPITULATION + put surge")
    history = {"NVDA": build_synthetic_history(call_growth=0.0, put_growth=0.20)}
    metrics = ves.compute_oi_metrics("NVDA", history)
    annotation = ves._format_oi_annotation("CAPITULATION", metrics, has_today_snapshot=True)
    print(f"  {annotation}")

    print()
    print("Test 6 — _format_oi_annotation for BLOWOFF + call surge")
    history = {"NVDA": build_synthetic_history(call_growth=0.15, put_growth=0.0)}
    metrics = ves.compute_oi_metrics("NVDA", history)
    annotation = ves._format_oi_annotation("BLOWOFF", metrics, has_today_snapshot=True)
    print(f"  {annotation}")

    print()
    print("Test 7 — _format_oi_annotation for WANING + decreasing OI")
    history = {"NVDA": build_synthetic_history(call_growth=-0.05, put_growth=-0.05)}
    metrics = ves.compute_oi_metrics("NVDA", history)
    annotation = ves._format_oi_annotation("WANING", metrics, has_today_snapshot=True)
    print(f"  {annotation}")

    print()
    print("Test 8 — no options data path")
    annotation = ves._format_oi_annotation("CAPITULATION", None, has_today_snapshot=False)
    print(f"  {annotation}")


if __name__ == "__main__":
    main()
