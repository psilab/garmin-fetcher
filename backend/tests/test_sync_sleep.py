from datetime import date

import pytest

from app.models import Sleep
from app.sync.sleep import backfill_sleep, map_sleep_to_row, sync_sleep_window


class FakeGarminClient:
    """Stand-in for garminconnect.Garmin -- per-day sleep/recovery getters.

    ``days`` maps an ISO date string to a dict of per-getter overrides for
    that day; a day absent from ``days`` (or explicitly ``None``) simulates
    "no data" (get_sleep_data returns falsy). Tracks per-getter call counts
    so tests can assert exactly one call per day (throttle placement).
    """

    def __init__(self, days: dict):
        self.days = days
        self.calls = {
            "get_sleep_data": 0,
            "get_hrv_data": 0,
            "get_training_readiness": 0,
            "get_training_status": 0,
            "get_body_battery": 0,
        }

    def get_sleep_data(self, cdate):
        self.calls["get_sleep_data"] += 1
        day = self.days.get(cdate)
        if day is None:
            return None
        return day.get("sleep")

    def get_hrv_data(self, cdate):
        self.calls["get_hrv_data"] += 1
        day = self.days.get(cdate) or {}
        return day.get("hrv")

    def get_training_readiness(self, cdate):
        self.calls["get_training_readiness"] += 1
        day = self.days.get(cdate) or {}
        return day.get("training_readiness", [])

    def get_training_status(self, cdate):
        self.calls["get_training_status"] += 1
        day = self.days.get(cdate) or {}
        return day.get("training_status", {})

    def get_body_battery(self, startdate, enddate=None):
        self.calls["get_body_battery"] += 1
        day = self.days.get(startdate) or {}
        return day.get("body_battery", [])


def _synthetic_day(sleep_score=80, deep_s=4000.0, hrv_avg=34.0):
    return {
        "sleep": {
            "dailySleepDTO": {
                "deepSleepSeconds": deep_s,
                "lightSleepSeconds": 19500.0,
                "remSleepSeconds": 9420.0,
                "awakeSleepSeconds": 0.0,
                "sleepScores": {"overall": {"value": sleep_score}},
            },
            "avgOvernightHrv": hrv_avg,
        },
        "hrv": None,
        "training_readiness": [{"score": 55}],
        "training_status": {"mostRecentTrainingStatus": "PRODUCTIVE"},
        "body_battery": [
            {
                "date": "placeholder",
                "bodyBatteryValueDescriptorDTOList": [
                    {"bodyBatteryValueDescriptorIndex": 0, "bodyBatteryValueDescriptorKey": "timestamp"},
                    {"bodyBatteryValueDescriptorIndex": 1, "bodyBatteryValueDescriptorKey": "bodyBatteryLevel"},
                ],
                "bodyBatteryValuesArray": [
                    [1000, 42],
                    [2000, 84],
                    [3000, 39],
                ],
            }
        ],
    }


def _synthetic_days(n=3):
    return {f"2026-01-0{i + 1}": _synthetic_day(sleep_score=70 + i) for i in range(n)}


# --- map_sleep_to_row -------------------------------------------------------


def test_map_sleep_to_row_maps_known_fields_from_live_fixture(sample_sleep):
    combined = {
        "sleep": sample_sleep["sleep"],
        "hrv": None,
        "training_readiness": [{"score": 55}],
        "training_status": {"mostRecentTrainingStatus": "PRODUCTIVE"},
        "body_battery": sample_sleep["body_battery"],
    }

    row = map_sleep_to_row(combined, "2026-07-04")

    assert row["date"] == date(2026, 7, 4)
    assert row["sleep_score"] == 86
    assert row["deep_s"] == 4380
    assert row["light_s"] == 19500
    assert row["rem_s"] == 9420
    assert row["awake_s"] == 0
    assert row["hrv_avg"] == 34.0
    assert row["training_readiness"] == 55
    assert row["training_status"] == "PRODUCTIVE"
    assert row["body_battery_high"] == 84
    assert row["body_battery_low"] == 39


def test_map_sleep_to_row_body_battery_absent_degrades_to_none(sample_sleep):
    combined = {
        "sleep": sample_sleep["sleep"],
        "hrv": None,
        "training_readiness": [],
        "training_status": {},
        "body_battery": [],
    }

    row = map_sleep_to_row(combined, "2026-07-04")

    assert row["body_battery_high"] is None
    assert row["body_battery_low"] is None


def test_map_sleep_to_row_tolerates_none_hrv_and_empty_readiness():
    combined = {
        "sleep": _synthetic_day()["sleep"],
        "hrv": None,  # get_hrv_data can return None (Pitfall 3)
        "training_readiness": [],  # empty list, not indexable naively
        "training_status": None,
        "body_battery": None,
    }

    row = map_sleep_to_row(combined, "2026-01-01")

    assert row["training_readiness"] is None
    assert row["training_status"] is None
    assert row["body_battery_high"] is None
    assert row["body_battery_low"] is None


def test_map_sleep_to_row_raises_on_missing_cdate():
    with pytest.raises(ValueError):
        map_sleep_to_row({"sleep": {}}, "")


def test_map_sleep_to_row_raises_on_unparseable_cdate():
    with pytest.raises(ValueError):
        map_sleep_to_row({"sleep": {}}, "not-a-date")


# --- backfill_sleep / sync_sleep_window ------------------------------------


def test_backfill_sleep_inserts_rows(db_session):
    client = FakeGarminClient(_synthetic_days(3))

    count = backfill_sleep(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 3
    assert db_session.query(Sleep).count() == 3


def test_backfill_sleep_skips_days_with_no_data_without_counting_as_error(db_session):
    days = _synthetic_days(3)
    days["2026-01-02"] = None  # no sleep data that day
    client = FakeGarminClient(days)

    count = backfill_sleep(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 2
    assert db_session.query(Sleep).count() == 2


def test_backfill_sleep_skips_malformed_day_without_aborting(db_session, monkeypatch):
    days = _synthetic_days(3)
    client = FakeGarminClient(days)

    # Force a malformed day by making get_hrv_data raise for one date only.
    original_get_hrv = client.get_hrv_data

    def flaky_get_hrv(cdate):
        if cdate == "2026-01-02":
            raise TypeError("simulated malformed payload")
        return original_get_hrv(cdate)

    monkeypatch.setattr(client, "get_hrv_data", flaky_get_hrv)

    count = backfill_sleep(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 2
    assert db_session.query(Sleep).count() == 2


def test_sync_sleep_window_is_idempotent_and_self_heals(db_session):
    days = _synthetic_days(2)
    client = FakeGarminClient(days)

    sync_sleep_window(db_session, client, start="2026-01-01", end="2026-01-02")
    assert db_session.query(Sleep).count() == 2

    # Simulate a re-scored day between runs (Garmin revises sleep score).
    days["2026-01-01"]["sleep"]["dailySleepDTO"]["sleepScores"]["overall"]["value"] = 95

    count = sync_sleep_window(db_session, client, start="2026-01-01", end="2026-01-02")

    assert count == 2
    assert db_session.query(Sleep).count() == 2  # no duplicates
    updated = db_session.get(Sleep, date(2026, 1, 1))
    assert updated.sleep_score == 95


def test_backfill_sleep_calls_each_getter_once_per_day(db_session):
    client = FakeGarminClient(_synthetic_days(3))

    backfill_sleep(db_session, client, start="2026-01-01", end="2026-01-03")

    assert client.calls["get_sleep_data"] == 3
    assert client.calls["get_hrv_data"] == 3
    assert client.calls["get_training_readiness"] == 3
    assert client.calls["get_training_status"] == 3
    assert client.calls["get_body_battery"] == 3


def test_backfill_sleep_throttles_inside_the_loop(db_session, monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "app.sync.sleep.time.sleep", lambda seconds: sleeps.append(seconds)
    )
    client = FakeGarminClient(_synthetic_days(3))

    backfill_sleep(db_session, client, start="2026-01-01", end="2026-01-03")

    # One throttle call per day iterated (not once for the whole backfill).
    assert len(sleeps) == 3
