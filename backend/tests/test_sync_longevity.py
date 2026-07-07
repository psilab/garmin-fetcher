from datetime import date

import pytest

from app.models import LongevityMarker
from app.sync.longevity import backfill_longevity, map_longevity_to_row, sync_longevity_window


def _max_metrics_payload(vo2max=43.0, fitness_age=26, cdate="2026-01-01"):
    return [
        {
            "generic": {
                "calendarDate": cdate,
                "vo2MaxValue": vo2max,
                "fitnessAge": fitness_age,
            }
        }
    ]


def _training_status_payload(training_load=335, device_id="3476168089"):
    return {
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {
                device_id: {
                    "acuteTrainingLoadDTO": {
                        "dailyTrainingLoadAcute": training_load,
                    }
                }
            }
        }
    }


class FakeGarminClient:
    """Stand-in for garminconnect.Garmin -- per-day longevity getters.

    ``days`` maps an ISO date string to a dict with optional
    ``max_metrics``/``training_status`` overrides for that day; a day
    absent from ``days`` simulates "no data" (both getters return falsy).
    """

    def __init__(self, days: dict):
        self.days = days
        self.calls = {"get_max_metrics": 0, "get_training_status": 0}

    def get_max_metrics(self, cdate):
        self.calls["get_max_metrics"] += 1
        day = self.days.get(cdate)
        if day is None:
            return []
        return day.get("max_metrics", [])

    def get_training_status(self, cdate):
        self.calls["get_training_status"] += 1
        day = self.days.get(cdate)
        if day is None:
            return {}
        return day.get("training_status", {})


def _synthetic_day(cdate, vo2max=43.0, training_load=335):
    return {
        "max_metrics": _max_metrics_payload(vo2max=vo2max, cdate=cdate),
        "training_status": _training_status_payload(training_load=training_load),
    }


def _synthetic_days(n=3):
    return {
        f"2026-01-0{i + 1}": _synthetic_day(f"2026-01-0{i + 1}", vo2max=40.0 + i)
        for i in range(n)
    }


# --- map_longevity_to_row ---------------------------------------------------


def test_map_longevity_to_row_maps_known_fields():
    max_metrics = _max_metrics_payload(vo2max=43.0, fitness_age=26, cdate="2026-01-01")
    training_status = _training_status_payload(training_load=335)

    row = map_longevity_to_row(max_metrics, training_status, "2026-01-01")

    assert row["date"] == date(2026, 1, 1)
    assert row["vo2max"] == 43.0
    assert row["fitness_age"] == 26
    assert row["training_load"] == 335


def test_map_longevity_to_row_raises_on_missing_cdate():
    with pytest.raises(ValueError):
        map_longevity_to_row(_max_metrics_payload(), _training_status_payload(), "")


def test_map_longevity_to_row_degrades_malformed_vo2max_without_dropping_other_fields():
    max_metrics = [
        {
            "generic": {
                "calendarDate": "2026-01-01",
                "vo2MaxValue": "not-a-number",
                "fitnessAge": 26,
            }
        }
    ]
    training_status = _training_status_payload(training_load=335)

    row = map_longevity_to_row(max_metrics, training_status, "2026-01-01")

    assert row["vo2max"] is None
    assert row["fitness_age"] == 26
    assert row["training_load"] == 335


def test_map_longevity_to_row_tolerates_empty_max_metrics_list():
    row = map_longevity_to_row([], _training_status_payload(training_load=335), "2026-01-01")

    assert row["vo2max"] is None
    assert row["fitness_age"] is None
    assert row["training_load"] == 335


def test_map_longevity_to_row_degrades_malformed_training_status():
    max_metrics = _max_metrics_payload(vo2max=43.0, fitness_age=26, cdate="2026-01-01")

    for ts in (None, {}, {"mostRecentTrainingStatus": {}}, {"mostRecentTrainingStatus": None}):
        row = map_longevity_to_row(max_metrics, ts, "2026-01-01")
        assert row["training_load"] is None
        assert row["vo2max"] == 43.0
        assert row["fitness_age"] == 26


def test_map_longevity_to_row_degrades_malformed_fitness_age():
    # WR-01 regression: a non-numeric fitnessAge must degrade to None
    # instead of persisting the raw string (crashes get_trend at read time).
    max_metrics = [
        {
            "generic": {
                "calendarDate": "2026-01-01",
                "vo2MaxValue": 43.0,
                "fitnessAge": "N/A",
            }
        }
    ]
    training_status = _training_status_payload(training_load=335)

    row = map_longevity_to_row(max_metrics, training_status, "2026-01-01")

    assert row["fitness_age"] is None
    assert row["vo2max"] == 43.0
    assert row["training_load"] == 335


def test_map_longevity_to_row_degrades_malformed_training_load():
    # WR-01 regression: a non-numeric dailyTrainingLoadAcute must degrade
    # to None instead of persisting the raw string.
    max_metrics = _max_metrics_payload(vo2max=43.0, fitness_age=26, cdate="2026-01-01")
    training_status = {
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {
                "3476168089": {
                    "acuteTrainingLoadDTO": {"dailyTrainingLoadAcute": "unknown"}
                }
            }
        }
    }

    row = map_longevity_to_row(max_metrics, training_status, "2026-01-01")

    assert row["training_load"] is None
    assert row["vo2max"] == 43.0
    assert row["fitness_age"] == 26


def test_map_longevity_to_row_falls_through_to_second_device_for_training_load():
    # WR-05 regression: the first device lacking acuteTrainingLoadDTO must
    # not stop the scan -- a later device's real value should be used.
    max_metrics = _max_metrics_payload(vo2max=43.0, fitness_age=26, cdate="2026-01-01")
    training_status = {
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {
                "device-without-load": {"acuteTrainingLoadDTO": {}},
                "device-with-load": {
                    "acuteTrainingLoadDTO": {"dailyTrainingLoadAcute": 512}
                },
            }
        }
    }

    row = map_longevity_to_row(max_metrics, training_status, "2026-01-01")

    assert row["training_load"] == 512


# --- backfill_longevity / sync_longevity_window -----------------------------


def test_backfill_longevity_inserts_rows(db_session):
    client = FakeGarminClient(_synthetic_days(3))

    count = backfill_longevity(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 3
    assert db_session.query(LongevityMarker).count() == 3


def test_backfill_longevity_skips_days_with_no_data_without_counting_as_error(db_session):
    days = _synthetic_days(3)
    days["2026-01-02"] = None

    client = FakeGarminClient(days)

    count = backfill_longevity(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 2
    assert db_session.query(LongevityMarker).count() == 2


def test_backfill_longevity_skips_malformed_day_without_losing_other_days(db_session):
    """Regression (CR-01): a wrong-shaped Garmin payload must not abort the
    whole run -- the malformed day is skipped and the other days persist."""
    days = _synthetic_days(3)
    # Wrong-shaped: "generic" is a bare int, not a dict -> .get raises
    # AttributeError inside map_longevity_to_row.
    days["2026-01-02"]["max_metrics"] = [{"generic": 42}]

    client = FakeGarminClient(days)

    count = backfill_longevity(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 2
    assert db_session.query(LongevityMarker).count() == 2
    assert db_session.get(LongevityMarker, date(2026, 1, 1)) is not None
    assert db_session.get(LongevityMarker, date(2026, 1, 3)) is not None
    assert db_session.get(LongevityMarker, date(2026, 1, 2)) is None


def test_sync_longevity_window_is_idempotent_and_self_heals(db_session):
    days = _synthetic_days(2)
    client = FakeGarminClient(days)

    sync_longevity_window(db_session, client, start="2026-01-01", end="2026-01-02")
    assert db_session.query(LongevityMarker).count() == 2

    # Simulate a revised VO2max value between runs.
    days["2026-01-01"]["max_metrics"][0]["generic"]["vo2MaxValue"] = 50.0

    count = sync_longevity_window(db_session, client, start="2026-01-01", end="2026-01-02")

    assert count == 2
    assert db_session.query(LongevityMarker).count() == 2  # no duplicates
    updated = db_session.get(LongevityMarker, date(2026, 1, 1))
    assert updated.vo2max == 50.0


def test_backfill_longevity_skips_day_on_upsert_failure_without_aborting_run(db_session, monkeypatch):
    """WR-04 regression: an _upsert failure for one day must be skipped
    (not inserted), never aborting the run -- the other days still persist."""
    import app.sync.longevity as longevity_mod

    real_upsert = longevity_mod._upsert

    def fake_upsert(session, model, row, key):
        if row["date"] == date(2026, 1, 2):
            raise Exception("db error")
        return real_upsert(session, model, row, key)

    monkeypatch.setattr(longevity_mod, "_upsert", fake_upsert)

    client = FakeGarminClient(_synthetic_days(3))

    count = backfill_longevity(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 2
    assert db_session.get(LongevityMarker, date(2026, 1, 1)) is not None
    assert db_session.get(LongevityMarker, date(2026, 1, 2)) is None
    assert db_session.get(LongevityMarker, date(2026, 1, 3)) is not None


def test_backfill_longevity_rolls_back_and_persists_later_days_on_real_db_error(db_session, monkeypatch):
    """WR-04 rollback regression: a genuine DB-level failure (not a plain
    Python raise) mid-loop must be rolled back so the session stays usable
    -- every subsequent good day still persists and is queryable AFTER the
    run. This test fails if session.rollback() is removed from the except
    handler (PendingRollbackError cascades into later days/final commit)."""
    import app.sync.longevity as longevity_mod

    real_upsert = longevity_mod._upsert

    def fake_upsert(session, model, row, key):
        if row["date"] == date(2026, 1, 2):
            # A genuine ORM-level failure against the live test session
            # (not a plain Python raise): two ORM-tracked inserts for the
            # same primary key within one flush raise a real
            # IntegrityError, which puts the Session itself into a
            # pending-rollback state -- the same failure mode a real
            # constraint violation or driver error would produce.
            session.add(model(date=row["date"], vo2max=1.0, fitness_age=None, training_load=None, raw="{}"))
            session.flush()
            session.add(model(date=row["date"], vo2max=2.0, fitness_age=None, training_load=None, raw="{}"))
            session.flush()
            return
        return real_upsert(session, model, row, key)

    monkeypatch.setattr(longevity_mod, "_upsert", fake_upsert)

    client = FakeGarminClient(_synthetic_days(3))

    count = backfill_longevity(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 2
    assert db_session.get(LongevityMarker, date(2026, 1, 1)) is not None
    assert db_session.get(LongevityMarker, date(2026, 1, 3)) is not None
    assert db_session.get(LongevityMarker, date(2026, 1, 2)) is None


def test_backfill_longevity_throttles_inside_the_loop(db_session, monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "app.sync.longevity.time.sleep", lambda seconds: sleeps.append(seconds)
    )
    client = FakeGarminClient(_synthetic_days(3))

    backfill_longevity(db_session, client, start="2026-01-01", end="2026-01-03")

    assert len(sleeps) == 3
