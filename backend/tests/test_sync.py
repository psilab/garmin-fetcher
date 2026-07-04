import json
from datetime import datetime

from app.sync.workouts import map_activity_to_row


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
