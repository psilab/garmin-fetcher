import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def db_session():
    """In-memory SQLite session with all tables created."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_activity():
    with open(FIXTURES_DIR / "sample_activity.json") as f:
        return json.load(f)


@pytest.fixture
def sample_sleep():
    """Live-captured {"sleep": get_sleep_data(...), "body_battery":
    get_body_battery(...)} payload (see Plan 02-01's capture_fixtures.py)."""
    with open(FIXTURES_DIR / "sample_sleep.json") as f:
        return json.load(f)


@pytest.fixture
def sample_daily_health():
    """Live-captured get_stats(cdate) bundle (see Plan 02-01's
    capture_fixtures.py) -- the PRIMARY daily-health getter."""
    with open(FIXTURES_DIR / "sample_daily_health.json") as f:
        return json.load(f)


@pytest.fixture
def sample_weigh_ins():
    """Live-captured get_weigh_ins(start, end) RANGE payload (see Plan
    02-01's capture_fixtures.py) -- dailyWeightSummaries -> allWeightMetrics."""
    with open(FIXTURES_DIR / "sample_weigh_ins.json") as f:
        return json.load(f)
