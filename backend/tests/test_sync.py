import json
from datetime import datetime

from app.models import Workout
from app.sync.workouts import backfill_workouts, map_activity_to_row


class FakeGarminClient:
    """Stand-in for garminconnect.Garmin -- returns a canned activity list."""

    def __init__(self, activities):
        self.activities = activities
        self.calls = 0

    def get_activities_by_date(self, startdate, enddate, sortorder="asc"):
        self.calls += 1
        return self.activities


def _synthetic_activities():
    return [
        {
            "activityId": 100 + i,
            "activityType": {"typeKey": "running"},
            "startTimeLocal": f"2026-01-0{i + 1} 07:00:00",
            "distance": 5000.0 + i,
            "duration": 1800.0 + i,
            "averageHR": 140,
            "calories": 400,
        }
        for i in range(3)
    ]


def test_map_activity_to_row_maps_known_fields(sample_activity):
    row = map_activity_to_row(sample_activity)

    assert row["activity_id"] == sample_activity["activityId"]
    assert isinstance(row["activity_id"], int)
    assert row["activity_type"] == sample_activity["activityType"]["typeKey"]
    assert row["start_time"] == datetime.strptime(
        sample_activity["startTimeLocal"], "%Y-%m-%d %H:%M:%S"
    )
    assert row["distance_m"] == sample_activity["distance"]
    assert row["duration_s"] == sample_activity["duration"]
    assert row["average_hr"] == int(sample_activity["averageHR"])
    assert row["calories"] == int(sample_activity["calories"])
    assert row["raw"] == json.dumps(sample_activity, sort_keys=True)


def test_map_activity_to_row_handles_missing_optional_fields():
    synthetic = {
        "activityId": 999,
        "activityType": {"typeKey": "manual_entry"},
        "startTimeLocal": "2026-01-01 07:00:00",
        # no distance, duration, averageHR, calories - a manually-logged activity
    }

    row = map_activity_to_row(synthetic)

    assert row["activity_id"] == 999
    assert row["activity_type"] == "manual_entry"
    assert row["distance_m"] is None
    assert row["duration_s"] is None
    assert row["average_hr"] is None
    assert row["calories"] is None
    assert row["raw"] == json.dumps(synthetic, sort_keys=True)


def test_map_activity_defaults_activity_type_when_typekey_missing():
    # activity_type is NOT NULL; a missing typeKey must degrade to "unknown"
    # rather than producing None (which would raise IntegrityError on insert).
    row = map_activity_to_row(
        {"activityId": 7, "startTimeLocal": "2026-01-01 07:00:00"}
    )
    assert row["activity_type"] == "unknown"


def test_map_activity_raises_on_missing_essential_fields():
    import pytest

    with pytest.raises(ValueError):
        map_activity_to_row({"startTimeLocal": "2026-01-01 07:00:00"})  # no activityId
    with pytest.raises(ValueError):
        map_activity_to_row({"activityId": 1})  # no startTimeLocal
    with pytest.raises(ValueError):
        map_activity_to_row({"activityId": 1, "startTimeLocal": "not-a-date"})


def test_backfill_skips_unmappable_rows_without_aborting(db_session):
    activities = _synthetic_activities()  # 3 good rows
    activities.insert(1, {"activityType": {"typeKey": "running"}})  # bad: no id/time
    client = FakeGarminClient(activities)

    count = backfill_workouts(db_session, client)

    # The one bad row is skipped; the 3 good rows still persist.
    assert count == 3
    assert db_session.query(Workout).count() == 3


def test_backfill_workouts_inserts_rows(db_session):
    client = FakeGarminClient(_synthetic_activities())

    count = backfill_workouts(db_session, client)

    assert count == 3
    assert db_session.query(Workout).count() == 3


def test_backfill_workouts_is_idempotent(db_session):
    activities = _synthetic_activities()
    client = FakeGarminClient(activities)

    backfill_workouts(db_session, client)
    assert db_session.query(Workout).count() == 3

    # Simulate an edit on Garmin's side between runs (e.g. corrected calories).
    activities[0]["calories"] = 999

    count = backfill_workouts(db_session, client)

    assert count == 3
    assert db_session.query(Workout).count() == 3
    updated = db_session.get(Workout, activities[0]["activityId"])
    assert updated.calories == 999
