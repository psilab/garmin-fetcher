"""Contract tests for the registry-backed REST metric endpoint
(Plan 06-01, DASH-01).

Mirrors test_main_mcp_mount.py's "set MCP_TOKEN before importing app.main"
bootstrap (app.main -> app.mcp.server -> app.mcp.auth reads MCP_TOKEN at
import time) and test_mcp_analysis_tools.py's SessionLocal-monkeypatch
pattern -- but the SessionLocal that must be patched lives in the ROUTE's
module (app.api.metrics), not app.mcp.server.

Unlike the MCP tool tests (which call the tool functions directly, in the
test thread), these tests exercise the routes through the ASGI app. FastAPI
dispatches sync route handlers to a worker THREAD, so the shared conftest
``db_session`` (a default per-thread :memory: connection) would be invisible
to the handler. A ``StaticPool`` + ``check_same_thread=False`` engine shares
one connection across threads, so the seeded rows are visible to the route.

Covers T-06-01 (unknown metric 404 / bad range 400 raised BEFORE any DB
session opens) and the coach-independence regression (/health 200 and
POST /mcp/ 401 still hold after the router include).
"""

import os
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# app.mcp.auth reads MCP_TOKEN at import time -- must be set before the first
# import of app.main below (setdefault is order-safe, mirrors the MCP tests).
os.environ.setdefault("MCP_TOKEN", "test-secret-for-api-metrics-tests")

from app.db import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DailyHealth, Sleep  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def api_session(monkeypatch):
    """A cross-thread-safe in-memory session factory, with the route module's
    ``SessionLocal`` monkeypatched to it. Yields a session for seeding; the
    route opens its own sessions on the SAME shared connection."""
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


def _seed_resting_hr(session, days=5):
    """Seed consecutive-day DailyHealth rows within the default 90d window."""
    start = date.today() - timedelta(days=days)
    session.add_all(
        [
            DailyHealth(date=start + timedelta(days=i), resting_hr=50 + i, raw="{}")
            for i in range(days)
        ]
    )
    session.commit()


def _seed_hrv(session, days=5):
    start = date.today() - timedelta(days=days)
    session.add_all(
        [
            Sleep(
                date=start + timedelta(days=i),
                sleep_score=80,
                hrv_avg=30.0 + i,
                raw="{}",
            )
            for i in range(days)
        ]
    )
    session.commit()


@pytest.mark.anyio
async def test_metric_series_returns_compute_trend_shape(api_session):
    _seed_resting_hr(api_session)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/metrics/resting_hr?range=90d")

    assert response.status_code == 200
    body = response.json()
    assert "series" in body
    assert "direction" in body
    assert "baseline" in body
    # series items are {date, value} objects
    assert body["series"]
    first = body["series"][0]
    assert "date" in first and "value" in first


@pytest.mark.anyio
async def test_metric_series_default_range_is_90d(api_session):
    _seed_hrv(api_session)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # range omitted -> default 90d; seeded rows fall inside it
        response = await client.get("/api/metrics/hrv")

    assert response.status_code == 200
    assert response.json()["series"]


@pytest.mark.anyio
async def test_unknown_metric_returns_404_before_touching_db(monkeypatch):
    def _boom():
        raise AssertionError("SessionLocal must not be opened for an unknown metric")

    import app.api.metrics as metrics_module

    monkeypatch.setattr(metrics_module, "SessionLocal", _boom)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/metrics/not_a_metric?range=90d")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_bad_range_returns_400_before_touching_db(monkeypatch):
    def _boom():
        raise AssertionError("SessionLocal must not be opened for an unknown range")

    import app.api.metrics as metrics_module

    monkeypatch.setattr(metrics_module, "SessionLocal", _boom)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/metrics/resting_hr?range=bogus")

    assert response.status_code == 400


@pytest.mark.anyio
async def test_health_and_mcp_still_behave_after_router_include():
    """Coach independence: /health open, POST /mcp/ (no auth) still 401
    after the new metrics router is included in main.py."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        mcp = await client.post("/mcp/", json={})

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert mcp.status_code == 401
