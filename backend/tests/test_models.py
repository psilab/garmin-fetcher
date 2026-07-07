import json
from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import LongevityMarker, Workout


def test_wal_pragma_enabled(tmp_path, monkeypatch):
    """WAL is a no-op on :memory: DBs, so this test builds its own
    file-based engine against a path whose parent dir does not exist yet —
    proving both WAL-on-file-DB and auto-mkdir-before-create_engine.
    """
    db_path = tmp_path / "sub" / "garmin.db"
    assert not db_path.parent.exists()

    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    # Re-run db.py's engine-construction logic against the overridden URL
    # rather than importing the already-initialized module-level engine.
    import importlib

    import app.db as db_module

    importlib.reload(db_module)

    assert db_path.parent.exists()

    with db_module.engine.connect() as conn:
        result = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        assert result.lower() == "wal"

    # Restore the module to its default (in-memory-friendly) state for
    # any other test that imports it afresh.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    importlib.reload(db_module)


def test_workout_stores_raw_payload(db_session, sample_activity):
    raw_json = json.dumps(sample_activity)
    workout = Workout(
        activity_id=sample_activity["activityId"],
        activity_type=sample_activity["activityType"]["typeKey"],
        start_time=datetime(2026, 7, 4, 12, 9, 0),
        distance_m=sample_activity.get("distance"),
        duration_s=sample_activity.get("duration"),
        average_hr=sample_activity.get("averageHR"),
        calories=sample_activity.get("calories"),
        raw=raw_json,
    )
    db_session.add(workout)
    db_session.commit()

    fetched = db_session.get(Workout, sample_activity["activityId"])
    assert fetched.raw == raw_json


def test_workout_unique_activity_id(db_session):
    common_kwargs = dict(
        activity_id=12345,
        activity_type="running",
        start_time=datetime(2026, 7, 1, 8, 0, 0),
        raw="{}",
    )
    db_session.add(Workout(**common_kwargs))
    db_session.commit()

    db_session.add(Workout(**common_kwargs))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_longevity_marker_stores_raw_payload(db_session):
    raw_json = json.dumps({"max_metrics": {"generic": {"vo2MaxValue": 43.0}}})
    marker = LongevityMarker(
        date=date(2026, 7, 4),
        vo2max=43.0,
        fitness_age=26,
        training_load=335.0,
        raw=raw_json,
    )
    db_session.add(marker)
    db_session.commit()

    fetched = db_session.get(LongevityMarker, date(2026, 7, 4))
    assert fetched.raw == raw_json
    assert fetched.vo2max == 43.0
    assert fetched.fitness_age == 26
    assert fetched.training_load == 335.0
