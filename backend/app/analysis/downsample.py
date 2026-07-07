"""Bound a series to ~target_points regardless of range width (D-07).

Targets a point COUNT, not a fixed stride, so short ranges aren't gutted
(Pitfall 5 -- RESEARCH.md).
"""


def downsample(series: list, target_points: int = 40) -> list:
    if len(series) <= target_points:
        return series
    stride = max(1, len(series) // target_points)
    return series[::stride]
