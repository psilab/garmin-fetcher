"""Unit tests for compute_correlation against synthetic rows -- no DB
session, no SQLAlchemy."""

import json
from datetime import date, timedelta

from app.analysis.correlate import compute_correlation


def test_compute_correlation_recovers_known_correlation_with_lag():
    base = date(2026, 1, 1)
    lag = 2
    rows_a = [(base + timedelta(days=i), float(i)) for i in range(20)]
    # rows_b is rows_a's series, shifted forward by `lag` days -- i.e. the
    # value that appeared in a on day d appears in b on day d+lag.
    rows_b = [(base + timedelta(days=i) + timedelta(days=lag), float(i)) for i in range(20)]

    result = compute_correlation(rows_a, rows_b, lag_days=lag)

    assert result["correlation"] is not None
    assert result["correlation"] >= 0.99
    assert result["strength"] == "strong"
    assert result["count"] == 20


def test_compute_correlation_insufficient_overlap_returns_note_not_garbage():
    rows_a = [(date(2026, 1, 1), 1.0), (date(2026, 1, 2), 2.0)]
    rows_b = [(date(2026, 1, 1), 5.0)]

    result = compute_correlation(rows_a, rows_b, lag_days=0)

    assert result["correlation"] is None
    assert result["note"] == "insufficient_overlap"


def test_compute_correlation_constant_series_returns_undefined_note():
    # CR-01b regression: two zero-variance series make spearmanr return
    # nan for rho, which must degrade to an explicit note -- never a raw
    # NaN token, and never silently mislabeled "weak" strength.
    base = date(2026, 1, 1)
    rows_a = [(base + timedelta(days=i), 5.0) for i in range(5)]
    rows_b = [(base + timedelta(days=i), 9.0) for i in range(5)]

    result = compute_correlation(rows_a, rows_b, lag_days=0)

    assert result["correlation"] is None
    assert result["p_value"] is None
    assert result["note"] == "undefined_constant_series"
    json.dumps(result, allow_nan=False)
