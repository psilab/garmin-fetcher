"""Contract test for the bespoke workout daily-rollup route
(Plan 06-01 Task 2, DASH-01).

Unlike every registry metric (one row per calendar day), ``Workout`` rows are
event-grained (many per day) and ``start_time`` is a ``DateTime`` (not a
``Date``). This test proves ``func.date(start_time)`` truncates to a calendar
day correctly across a midnight boundary (RESEARCH Pitfall 2 / Assumption A3):
two workouts on the same day collapse to one bucket (count == 2, summed
duration/calories), and a workout at 00:30 the next day lands in its own
bucket (count == 1).

Uses the same StaticPool cross-thread harness as test_api_metrics.py (FastAPI
dispatches sync routes to a worker thread, so the in-memory DB must share one
connection).
"""

import os
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("MCP_TOKEN", "test-secret-for-api-workouts-tests")

from app.db import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Workout  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def api_session(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    import app.api.metrics as metrics_module

    monkeypatch.setattr(metrics_module, "SessionLocal", TestSession)

    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def _seed_midnight_boundary(session):
    """Two workouts on one calendar day + one at 00:30 the next day."""
    base_day = date.today() - timedelta(days=10)
    session.add_all(
        [
            Workout(
                activity_id=1,
                activity_type="running",
                start_time=datetime.combine(base_day, datetime.min.time()).replace(
                    hour=10
                ),
                duration_s=1800.0,
                calories=300,
                average_hr=140,
                raw="{}",
            ),
            Workout(
                activity_id=2,
                activity_type="cycling",
                start_time=datetime.combine(base_day, datetime.min.time()).replace(
                    hour=23, minute=30
                ),
                duration_s=1200.0,
                calories=200,
                average_hr=130,
                raw="{}",
            ),
            # 00:30 the following day -> a SEPARATE bucket (Pitfall 2)
            Workout(
                activity_id=3,
                activity_type="running",
                start_time=datetime.combine(
                    base_day + timedelta(days=1), datetime.min.time()
                ).replace(hour=0, minute=30),
                duration_s=900.0,
                calories=100,
                average_hr=120,
                raw="{}",
            ),
        ]
    )
    session.commit()
    return base_day


@pytest.mark.anyio
async def test_workouts_daily_buckets_across_midnight(api_session):
    base_day = _seed_midnight_boundary(api_session)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/workouts/daily?range=90d")

    assert response.status_code == 200
    series = response.json()["series"]
    # Two distinct day buckets, ascending by date.
    assert len(series) == 2

    same_day, next_day = series[0], series[1]
    assert same_day["date"] == base_day.isoformat()
    assert same_day["value"] == 2  # count of the same-day pair
    assert same_day["duration_s"] == 1800.0 + 1200.0
    assert same_day["calories"] == 300 + 200

    assert next_day["date"] == (base_day + timedelta(days=1)).isoformat()
    assert next_day["value"] == 1  # the post-midnight workout alone


@pytest.mark.anyio
async def test_workouts_daily_bad_range_returns_400(monkeypatch):
    def _boom():
        raise AssertionError("SessionLocal must not be opened for an unknown range")

    import app.api.metrics as metrics_module

    monkeypatch.setattr(metrics_module, "SessionLocal", _boom)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/workouts/daily?range=bogus")

    assert response.status_code == 400
