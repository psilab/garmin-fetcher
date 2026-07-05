"""Tests for the four D-04 coach read tools (list/filter/aggregate/compare).

These call the tool functions directly (not through the MCP/ASGI transport --
that plumbing is covered by test_mcp_auth.py) against a seeded in-memory
SQLite session, monkeypatching app.mcp.server's SessionLocal so the tools
read from the test session instead of the real app.db.SessionLocal.
"""

import os
from datetime import date, datetime

import pytest

# app.mcp.server reads MCP_TOKEN at import time (fails fast if unset) --
# these tests exercise the tool functions directly, not auth, so a fixed
# test value is fine here (mirrors test_mcp_auth.py's monkeypatch, but must
# be set before the first import of app.mcp.server regardless of test order).
os.environ.setdefault("MCP_TOKEN", "test-secret-for-tool-tests")

from app.models import DailyHealth, Sleep, Workout


@pytest.fixture(autouse=True)
def _patch_session_local(monkeypatch, db_session):
    """Point app.mcp.server at the seeded in-memory db_session for every test."""
    import app.mcp.server as server_module

    monkeypatch.setattr(server_module, "SessionLocal", lambda: db_session)


def _make_workout(activity_id, activity_type, start_time, **overrides):
    defaults = dict(
        activity_id=activity_id,
        activity_type=activity_type,
        start_time=start_time,
        distance_m=5000.0,
        duration_s=1800.0,
        average_hr=140,
        calories=400,
        raw="{}",
    )
    defaults.update(overrides)
    return Workout(**defaults)


def test_list_recent_workouts_orders_newest_first(db_session):
    from app.mcp.server import list_recent_workouts

    db_session.add_all(
        [
            _make_workout(1, "running", datetime(2026, 1, 1, 7, 0, 0)),
            _make_workout(2, "running", datetime(2026, 1, 3, 7, 0, 0)),
            _make_workout(3, "cycling", datetime(2026, 1, 2, 7, 0, 0)),
        ]
    )
    db_session.commit()

    result = list_recent_workouts(limit=2)

    assert [w["activity_id"] for w in result] == [2, 3]


def test_filter_workouts_by_type_and_date_range(db_session):
    from app.mcp.server import filter_workouts

    db_session.add_all(
        [
            _make_workout(1, "running", datetime(2026, 1, 1, 7, 0, 0)),
            _make_workout(2, "running", datetime(2026, 2, 1, 7, 0, 0)),
            _make_workout(3, "cycling", datetime(2026, 1, 15, 7, 0, 0)),
        ]
    )
    db_session.commit()

    result = filter_workouts(
        activity_type="running", start=date(2026, 1, 1), end=date(2026, 1, 31)
    )

    assert [w["activity_id"] for w in result] == [1]


def test_aggregate_workouts_totals(db_session):
    from app.mcp.server import aggregate_workouts

    db_session.add_all(
        [
            _make_workout(
                1,
                "running",
                datetime(2026, 1, 1, 7, 0, 0),
                distance_m=5000.0,
                duration_s=1800.0,
                average_hr=140,
                calories=400,
            ),
            _make_workout(
                2,
                "running",
                datetime(2026, 1, 2, 7, 0, 0),
                distance_m=10000.0,
                duration_s=3600.0,
                average_hr=150,
                calories=800,
            ),
            _make_workout(
                3,
                "cycling",
                datetime(2026, 1, 3, 7, 0, 0),
                distance_m=20000.0,
                duration_s=3600.0,
                average_hr=130,
                calories=600,
            ),
        ]
    )
    db_session.commit()

    result = aggregate_workouts(activity_type="running")

    assert result["count"] == 2
    assert result["total_distance_m"] == 15000.0
    assert result["total_duration_s"] == 5400.0
    assert result["total_calories"] == 1200
    assert result["avg_hr"] == pytest.approx(145.0)


def test_compare_periods_counts_and_sums(db_session):
    from app.mcp.server import compare_periods

    db_session.add_all(
        [
            _make_workout(
                1, "running", datetime(2026, 1, 5, 7, 0, 0), distance_m=5000.0, calories=400
            ),
            _make_workout(
                2, "running", datetime(2026, 1, 10, 7, 0, 0), distance_m=6000.0, calories=450
            ),
            _make_workout(
                3, "running", datetime(2026, 2, 5, 7, 0, 0), distance_m=7000.0, calories=500
            ),
        ]
    )
    db_session.commit()

    result = compare_periods(
        period_a_start=date(2026, 1, 1),
        period_a_end=date(2026, 1, 31),
        period_b_start=date(2026, 2, 1),
        period_b_end=date(2026, 2, 28),
        activity_type="running",
    )

    assert result["period_a"]["count"] == 2
    assert result["period_a"]["total_distance_m"] == 11000.0
    assert result["period_b"]["count"] == 1
    assert result["period_b"]["total_distance_m"] == 7000.0


def test_filter_workouts_rejects_start_after_end(db_session):
    from app.mcp.server import filter_workouts

    with pytest.raises(ValueError):
        filter_workouts(start=date(2026, 2, 1), end=date(2026, 1, 1))


def _make_sleep(day, sleep_score=80, **overrides):
    defaults = dict(
        date=day,
        sleep_score=sleep_score,
        deep_s=4380.0,
        light_s=19500.0,
        rem_s=9420.0,
        awake_s=0.0,
        hrv_avg=34.0,
        body_battery_high=84,
        body_battery_low=39,
        training_readiness=55,
        training_status="PRODUCTIVE",
        raw="{}",
    )
    defaults.update(overrides)
    return Sleep(**defaults)


def test_list_recent_sleep_orders_newest_first(db_session):
    from app.mcp.server import list_recent_sleep

    db_session.add_all(
        [
            _make_sleep(date(2026, 1, 1)),
            _make_sleep(date(2026, 1, 3)),
            _make_sleep(date(2026, 1, 2)),
        ]
    )
    db_session.commit()

    result = list_recent_sleep(limit=2)

    assert [s["date"] for s in result] == [date(2026, 1, 3), date(2026, 1, 2)]


def test_list_recent_sleep_excludes_raw(db_session):
    from app.mcp.server import list_recent_sleep

    db_session.add(_make_sleep(date(2026, 1, 1)))
    db_session.commit()

    result = list_recent_sleep(limit=1)

    assert "raw" not in result[0]


def test_filter_sleep_by_date_range(db_session):
    from app.mcp.server import filter_sleep

    db_session.add_all(
        [
            _make_sleep(date(2026, 1, 1)),
            _make_sleep(date(2026, 2, 1)),
            _make_sleep(date(2026, 1, 15)),
        ]
    )
    db_session.commit()

    result = filter_sleep(start=date(2026, 1, 1), end=date(2026, 1, 31))

    assert sorted(s["date"] for s in result) == [date(2026, 1, 1), date(2026, 1, 15)]


def test_filter_sleep_rejects_start_after_end(db_session):
    from app.mcp.server import filter_sleep

    with pytest.raises(ValueError):
        filter_sleep(start=date(2026, 2, 1), end=date(2026, 1, 1))


def test_aggregate_sleep_totals(db_session):
    from app.mcp.server import aggregate_sleep

    db_session.add_all(
        [
            _make_sleep(date(2026, 1, 1), sleep_score=80, hrv_avg=30.0),
            _make_sleep(date(2026, 1, 2), sleep_score=90, hrv_avg=40.0),
        ]
    )
    db_session.commit()

    result = aggregate_sleep(start=date(2026, 1, 1), end=date(2026, 1, 31))

    assert result["count"] == 2
    assert result["avg_sleep_score"] == pytest.approx(85.0)
    assert result["avg_hrv"] == pytest.approx(35.0)


def _make_daily_health(day, total_steps=5928, **overrides):
    defaults = dict(
        date=day,
        total_steps=total_steps,
        resting_hr=56,
        stress_avg=24,
        spo2_avg=95,
        respiration_avg=15.0,
        intensity_minutes_moderate=40,
        intensity_minutes_vigorous=5,
        raw="{}",
    )
    defaults.update(overrides)
    return DailyHealth(**defaults)


def test_list_recent_daily_health_orders_newest_first(db_session):
    from app.mcp.server import list_recent_daily_health

    db_session.add_all(
        [
            _make_daily_health(date(2026, 1, 1)),
            _make_daily_health(date(2026, 1, 3)),
            _make_daily_health(date(2026, 1, 2)),
        ]
    )
    db_session.commit()

    result = list_recent_daily_health(limit=2)

    assert [d["date"] for d in result] == [date(2026, 1, 3), date(2026, 1, 2)]


def test_list_recent_daily_health_excludes_raw(db_session):
    from app.mcp.server import list_recent_daily_health

    db_session.add(_make_daily_health(date(2026, 1, 1)))
    db_session.commit()

    result = list_recent_daily_health(limit=1)

    assert "raw" not in result[0]


def test_filter_daily_health_by_date_range(db_session):
    from app.mcp.server import filter_daily_health

    db_session.add_all(
        [
            _make_daily_health(date(2026, 1, 1)),
            _make_daily_health(date(2026, 2, 1)),
            _make_daily_health(date(2026, 1, 15)),
        ]
    )
    db_session.commit()

    result = filter_daily_health(start=date(2026, 1, 1), end=date(2026, 1, 31))

    assert sorted(d["date"] for d in result) == [date(2026, 1, 1), date(2026, 1, 15)]


def test_filter_daily_health_rejects_start_after_end(db_session):
    from app.mcp.server import filter_daily_health

    with pytest.raises(ValueError):
        filter_daily_health(start=date(2026, 2, 1), end=date(2026, 1, 1))


def test_aggregate_daily_health_totals(db_session):
    from app.mcp.server import aggregate_daily_health

    db_session.add_all(
        [
            _make_daily_health(date(2026, 1, 1), total_steps=5000, resting_hr=50),
            _make_daily_health(date(2026, 1, 2), total_steps=7000, resting_hr=60),
        ]
    )
    db_session.commit()

    result = aggregate_daily_health(start=date(2026, 1, 1), end=date(2026, 1, 31))

    assert result["count"] == 2
    assert result["avg_total_steps"] == pytest.approx(6000.0)
    assert result["avg_resting_hr"] == pytest.approx(55.0)
