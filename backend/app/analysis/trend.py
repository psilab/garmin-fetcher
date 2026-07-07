"""Pure trend + rolling-baseline computation (D-03, D-04).

No ORM/DB-layer import anywhere in this file -- callable by both the MCP
tools and the future scheduler without any DB coupling.
"""

import numpy as np
from scipy.stats import linregress

from .downsample import downsample


def compute_trend(rows: list[tuple], window_days: int | None = None, z_threshold: float = 2.5) -> dict:
    """rows: [(date, value_or_None), ...] sorted ascending."""
    clean = [(d, v) for d, v in rows if v is not None]
    if len(clean) < 2:
        return {
            "direction": "insufficient_data",
            "count": len(clean),
            "dropped": len(rows) - len(clean),
        }

    window_days = window_days or 30

    dates, values = zip(*clean)
    x = np.array([(d - dates[0]).days for d in dates], dtype=float)
    y = np.array(values, dtype=float)
    result = linregress(x, y)

    baseline_window = values[-window_days:] if len(values) >= window_days else values
    baseline = float(np.mean(baseline_window))

    direction = "up" if result.slope > 0 else "down" if result.slope < 0 else "flat"

    latest = float(values[-1])
    preceding = values[:-1][-window_days:]
    deviation = None
    z = None
    if len(preceding) >= 5:
        window_arr = np.array(preceding, dtype=float)
        med = np.median(window_arr)
        mad = np.median(np.abs(window_arr - med)) * 1.4826
        if mad != 0:
            z = float((latest - med) / mad)
            deviation = "notable" if abs(z) >= z_threshold else "normal"

    return {
        "direction": direction,
        "slope": float(result.slope),
        "r_value": float(result.rvalue),
        "p_value": float(result.pvalue),
        "baseline": baseline,
        "latest": latest,
        "count": len(clean),
        "dropped": len(rows) - len(clean),
        "deviation": deviation,
        "z": z,
        "series": downsample([{"date": d.isoformat(), "value": v} for d, v in clean]),
    }
