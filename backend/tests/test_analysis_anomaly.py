"""Unit tests for detect_anomalies against synthetic rows -- no DB session,
no SQLAlchemy."""

from datetime import date, timedelta

from app.analysis.anomaly import detect_anomalies


def test_detect_anomalies_flags_planted_outlier_only():
    base = date(2026, 1, 1)
    # 40 days of normal noise alternating 50/51, with a single planted
    # outlier at index 35.
    rows = [(base + timedelta(days=i), 50.0 + (i % 2)) for i in range(40)]
    rows[35] = (rows[35][0], 500.0)

    flagged = detect_anomalies(rows, window_days=30, z_threshold=2.5)

    flagged_dates = {f["date"] for f in flagged}
    assert rows[35][0].isoformat() in flagged_dates
    # No normal-noise day (any day other than the planted outlier) should
    # be flagged.
    assert len(flagged) == 1


def test_detect_anomalies_downward_outlier_reports_down_direction():
    base = date(2026, 1, 1)
    rows = [(base + timedelta(days=i), 50.0 + (i % 2)) for i in range(40)]
    rows[35] = (rows[35][0], -500.0)

    flagged = detect_anomalies(rows, window_days=30, z_threshold=2.5)

    assert len(flagged) == 1
    assert flagged[0]["direction"] == "down"
