"""Unit tests for compute_trend against synthetic rows -- no DB session, no
SQLAlchemy (D-04's pure-function requirement flowing into a pure unit test)."""

from datetime import date, timedelta

from app.analysis.trend import compute_trend


def test_compute_trend_rising_series_reports_up():
    rows = [(date(2026, 1, 1) + timedelta(days=i), float(i)) for i in range(10)]

    result = compute_trend(rows)

    assert result["direction"] == "up"
    assert result["count"] == 10


def test_compute_trend_drops_none_values():
    rows = [
        (date(2026, 1, 1), 10.0),
        (date(2026, 1, 2), None),
        (date(2026, 1, 3), 12.0),
    ]

    result = compute_trend(rows)

    assert result["count"] == 2
    assert result["dropped"] == 1


def test_compute_trend_insufficient_data_does_not_raise():
    rows = [(date(2026, 1, 1), 10.0)]

    result = compute_trend(rows)

    assert result["direction"] == "insufficient_data"
    assert result["count"] == 1

    result_empty = compute_trend([])
    assert result_empty["direction"] == "insufficient_data"
    assert result_empty["count"] == 0


def test_compute_trend_flags_notable_deviation_on_latest_point():
    # 30 days of normal noise followed by a wild outlier as the latest point.
    rows = [(date(2026, 1, 1) + timedelta(days=i), 50.0 + (i % 2)) for i in range(30)]
    rows.append((date(2026, 1, 31), 500.0))

    result = compute_trend(rows, window_days=30)

    assert result["deviation"] == "notable"
    assert result["z"] is not None
    assert abs(result["z"]) >= 2.5


def test_compute_trend_normal_latest_point_not_flagged():
    rows = [(date(2026, 1, 1) + timedelta(days=i), 50.0 + (i % 2)) for i in range(30)]
    rows.append((date(2026, 1, 31), 51.0))

    result = compute_trend(rows, window_days=30)

    assert result["deviation"] == "normal"
