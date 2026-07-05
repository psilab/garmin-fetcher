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
