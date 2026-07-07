"""Generic metric registry (D-01) mapping a stable metric name to enough
metadata for the pure analysis functions to fetch and interpret it, without
per-metric branching anywhere in trend/correlation/anomaly code.

EXACTLY the 7 metrics already backed by existing typed columns. Do NOT add
`vo2max`/`training_load` here -- no backing column exists yet; those land in
Plan 03-03 once Plan 03-02's LongevityMarker table exists.
"""

from dataclasses import dataclass

from ..models import BodyComposition, DailyHealth, Sleep


@dataclass(frozen=True)
class MetricSpec:
    model: type
    column: str
    date_col: str = "date"
    default_window_days: int = 30


METRICS: dict[str, MetricSpec] = {
    "resting_hr": MetricSpec(DailyHealth, "resting_hr"),
    "hrv": MetricSpec(Sleep, "hrv_avg"),
    "sleep_score": MetricSpec(Sleep, "sleep_score"),
    "stress": MetricSpec(DailyHealth, "stress_avg"),
    "steps": MetricSpec(DailyHealth, "total_steps"),
    "weight": MetricSpec(BodyComposition, "weight_g"),
    "body_fat_pct": MetricSpec(BodyComposition, "body_fat_pct"),
}
