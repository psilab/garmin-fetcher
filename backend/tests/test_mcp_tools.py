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

from app.models import Workout


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
