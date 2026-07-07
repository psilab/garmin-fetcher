"""Pure robust anomaly detection via rolling median/MAD z-score (D-03, D-04).

No ORM/DB-layer import anywhere in this file.
"""

import numpy as np


def detect_anomalies(rows: list[tuple], window_days: int = 30, z_threshold: float = 2.5) -> list[dict]:
    """rows: [(date, value_or_None), ...] sorted ascending."""
    clean = [(d, v) for d, v in rows if v is not None]
    flagged = []
    values = [v for _, v in clean]
    for i, (d, v) in enumerate(clean):
        window = values[max(0, i - window_days):i]
        if len(window) < 5:
            continue
        window_arr = np.array(window, dtype=float)
        med = np.median(window_arr)
        mad = np.median(np.abs(window_arr - med)) * 1.4826
        if mad == 0:
            continue
        z = (v - med) / mad
        if abs(z) >= z_threshold:
            flagged.append(
                {
                    "date": d.isoformat(),
                    "value": float(v),
                    "z": float(z),
                    "direction": "up" if z > 0 else "down",
                }
            )
    return flagged
