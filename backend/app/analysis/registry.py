"""Generic metric registry (D-01) mapping a stable metric name to enough
metadata for the pure analysis functions to fetch and interpret it, without
per-metric branching anywhere in trend/correlation/anomaly code.

The original 7 metrics are backed by existing typed columns
(resting_hr/hrv/sleep_score/stress/steps/weight/body_fat_pct). Plan 03-03
adds `vo2max`/`training_load`, backed by the `longevity_markers` table.
"""

from dataclasses import dataclass

from ..models import BodyComposition, DailyHealth, LongevityMarker, Sleep


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
    # D-05/D-01 correction: backed by the NEW `longevity_markers` table
    # populated by Plan 03-02's sync, not a backfill from any pre-existing
    # `raw` payload. 180-day default window for VO2max's longer-arc
    # trajectory per D-06/RESEARCH.md Pattern 1.
    "vo2max": MetricSpec(LongevityMarker, "vo2max", default_window_days=180),
    "training_load": MetricSpec(LongevityMarker, "training_load"),
}
