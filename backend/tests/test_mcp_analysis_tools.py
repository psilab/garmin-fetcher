"""Integration tests for the ANLZ generic analysis MCP tools (get_trend,
get_correlations, detect_anomalies) -- calls the tool functions directly
against a seeded in-memory SQLite session, mirroring test_mcp_tools.py's
SessionLocal-monkeypatch pattern.
"""

import os
from datetime import date, timedelta

import pytest

# app.mcp.server reads MCP_TOKEN at import time (fails fast if unset).
os.environ.setdefault("MCP_TOKEN", "test-secret-for-tool-tests")

from app.models import BodyComposition, DailyHealth, LongevityMarker, Sleep


@pytest.fixture(autouse=True)
def _patch_session_local(monkeypatch, db_session):
    import app.mcp.server as server_module

    monkeypatch.setattr(server_module, "SessionLocal", lambda: db_session)


def _make_daily_health(day, **overrides):
    defaults = dict(
        date=day,
        total_steps=5000,
        resting_hr=55,
        stress_avg=25,
        raw="{}",
    )
    defaults.update(overrides)
    return DailyHealth(**defaults)


def _make_sleep(day, **overrides):
    defaults = dict(
        date=day,
        sleep_score=80,
        hrv_avg=34.0,
        raw="{}",
    )
    defaults.update(overrides)
    return Sleep(**defaults)


def _seed_rising_resting_hr(db_session, days=15, start=date(2026, 1, 1)):
    db_session.add_all(
        [
            _make_daily_health(start + timedelta(days=i), resting_hr=50 + i)
            for i in range(days)
        ]
    )
    db_session.commit()


# --- get_trend ---------------------------------------------------------


def test_get_trend_returns_compute_trend_shape_for_seeded_rows(db_session):
    from app.mcp.server import get_trend

    _seed_rising_resting_hr(db_session)

    result = get_trend(
        metric="resting_hr", start=date(2026, 1, 1), end=date(2026, 1, 15)
    )

    assert result["direction"] == "up"
    assert result["count"] == 15
    assert "series" in result


def test_get_trend_unknown_metric_raises_before_touching_session_local(
    db_session, monkeypatch
):
    from app.mcp.server import get_trend

    def _boom():
        raise AssertionError("SessionLocal should not be called for an unknown metric")

    import app.mcp.server as server_module

    monkeypatch.setattr(server_module, "SessionLocal", _boom)

    with pytest.raises(ValueError):
        get_trend(metric="not_a_real_metric")


# --- get_correlations ----------------------------------------------------


def test_get_correlations_recovers_planted_correlation(db_session):
    from app.mcp.server import get_correlations

    base = date(2026, 1, 1)
    lag = 1
    # hrv on day d predicts resting_hr on day d + lag (planted linear
    # relationship, inverse so the recovered correlation is strong).
    db_session.add_all(
        [_make_sleep(base + timedelta(days=i), hrv_avg=float(30 + i)) for i in range(15)]
    )
    db_session.add_all(
        [
            _make_daily_health(
                base + timedelta(days=i) + timedelta(days=lag), resting_hr=80 - i
            )
            for i in range(15)
        ]
    )
    db_session.commit()

    result = get_correlations(metrics=["hrv", "resting_hr"], lag_days=lag)

    assert result["correlation"] is not None
    assert result["correlation"] <= -0.99
    assert result["metric_a"] == "hrv"
    assert result["metric_b"] == "resting_hr"


def test_get_correlations_requires_exactly_two_metrics(db_session):
    from app.mcp.server import get_correlations

    with pytest.raises(ValueError):
        get_correlations(metrics=["hrv"])


def test_get_correlations_unknown_metric_raises_value_error(db_session):
    from app.mcp.server import get_correlations

    with pytest.raises(ValueError):
        get_correlations(metrics=["hrv", "not_a_real_metric"])


# --- detect_anomalies -----------------------------------------------------


def test_detect_anomalies_flags_planted_outlier_day(db_session):
    from app.mcp.server import detect_anomalies

    base = date(2026, 1, 1)
    days = [
        _make_daily_health(base + timedelta(days=i), total_steps=5000 + (i % 2) * 100)
        for i in range(40)
    ]
    days[35].total_steps = 50000
    outlier_date_iso = days[35].date.isoformat()
    db_session.add_all(days)
    db_session.commit()

    result = detect_anomalies(metric="steps")

    flagged_dates = {d["date"] for d in result}
    assert outlier_date_iso in flagged_dates


def test_detect_anomalies_unknown_metric_raises_value_error(db_session):
    from app.mcp.server import detect_anomalies

    with pytest.raises(ValueError):
        detect_anomalies(metric="not_a_real_metric")


# --- get_longevity_markers (D-06 fixed 5-marker set) ----------------------


def _make_body_comp(day, **overrides):
    defaults = dict(
        sample_pk=int(day.strftime("%Y%m%d")),
        date=day,
        weight_g=70000,
        body_fat_pct=18.0,
        raw="{}",
    )
    defaults.update(overrides)
    return BodyComposition(**defaults)


def _make_longevity_marker(day, **overrides):
    defaults = dict(
        date=day,
        vo2max=None,
        fitness_age=None,
        training_load=None,
        raw="{}",
    )
    defaults.update(overrides)
    return LongevityMarker(**defaults)


def test_get_longevity_markers_returns_exactly_five_d06_keys(db_session):
    from app.mcp.server import get_longevity_markers

    base = date(2026, 1, 1)
    db_session.add_all(
        [_make_sleep(base + timedelta(days=i)) for i in range(3)]
    )
    db_session.add_all(
        [_make_daily_health(base + timedelta(days=i)) for i in range(3)]
    )
    db_session.add_all(
        [_make_body_comp(base + timedelta(days=i)) for i in range(3)]
    )
    # One row has vo2max=None to exercise the insufficient-data path
    # alongside a fully-populated row.
    db_session.add_all(
        [
            _make_longevity_marker(base, vo2max=None),
            _make_longevity_marker(base + timedelta(days=1), vo2max=45.0),
        ]
    )
    db_session.commit()

    result = get_longevity_markers()

    assert set(result["markers"].keys()) == {
        "vo2max",
        "hrv",
        "resting_hr",
        "weight",
        "body_fat_pct",
    }
    assert "training_load" not in result["markers"]


def test_get_longevity_markers_degrades_empty_vo2max_range_to_insufficient_data(
    db_session,
):
    from app.mcp.server import get_longevity_markers

    base = date(2026, 1, 1)
    db_session.add_all(
        [_make_sleep(base + timedelta(days=i)) for i in range(3)]
    )
    db_session.add_all(
        [_make_daily_health(base + timedelta(days=i)) for i in range(3)]
    )
    db_session.add_all(
        [_make_body_comp(base + timedelta(days=i)) for i in range(3)]
    )
    # No LongevityMarker rows at all -- VO2max not yet backfilled.
    db_session.commit()

    result = get_longevity_markers()

    assert result["markers"]["vo2max"]["direction"] == "insufficient_data"
