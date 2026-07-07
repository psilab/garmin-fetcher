"""Pure lagged Spearman correlation computation (D-02, D-03, D-04).

No ORM/DB-layer import anywhere in this file.
"""

import math
from datetime import timedelta

from scipy.stats import spearmanr


def compute_correlation(rows_a: list[tuple], rows_b: list[tuple], lag_days: int = 0) -> dict:
    """rows_a/rows_b: [(date, value_or_None), ...]. Joins on
    date_a + lag_days == date_b (Pitfall 2 -- align on the date axis, never
    by list index, since either series may have missing days)."""
    map_a = {d: v for d, v in rows_a if v is not None}
    map_b = {d: v for d, v in rows_b if v is not None}

    pairs = [
        (v, map_b[d + timedelta(days=lag_days)])
        for d, v in map_a.items()
        if (d + timedelta(days=lag_days)) in map_b
    ]

    if len(pairs) < 3:
        return {
            "correlation": None,
            "p_value": None,
            "count": len(pairs),
            "lag_days": lag_days,
            "note": "insufficient_overlap",
        }

    xs, ys = zip(*pairs)
    rho, p = spearmanr(xs, ys)

    if not math.isfinite(rho):
        # A zero-variance series (e.g. a flat metric) makes spearmanr
        # return nan -- json.dumps(float("nan")) is invalid JSON per RFC
        # 8259, and letting it fall through the strength ladder below
        # would misleadingly label an undefined correlation "weak"
        # (CR-01b).
        return {
            "correlation": None,
            "p_value": None,
            "count": len(pairs),
            "lag_days": lag_days,
            "note": "undefined_constant_series",
        }

    if abs(rho) >= 0.6:
        strength = "strong"
    elif abs(rho) >= 0.3:
        strength = "moderate"
    else:
        strength = "weak"

    return {
        "correlation": float(rho),
        "p_value": float(p),
        "lag_days": lag_days,
        "count": len(pairs),
        "strength": strength,
    }
