from datetime import date

import pytest

from app.models import DailyHealth
from app.sync.daily_health import (
    backfill_daily_health,
    map_daily_health_to_row,
    sync_daily_health_window,
)


class FakeGarminClient:
    """Stand-in for garminconnect.Garmin -- per-day daily-health getters.

    ``days`` maps an ISO date string to a dict of per-getter overrides for
    that day; a day absent from ``days`` (or explicitly ``None``) simulates
    "no data" (get_stats returns falsy). Tracks per-getter call counts so
    tests can assert exactly one call per day (throttle placement, no
    double-calling per-field getters).
    """

    def __init__(self, days: dict):
        self.days = days
        self.calls = {
            "get_stats": 0,
            "get_spo2_data": 0,
            "get_respiration_data": 0,
        }

    def get_stats(self, cdate):
        self.calls["get_stats"] += 1
        day = self.days.get(cdate)
        if day is None:
            return None
        return day.get("stats")

    def get_spo2_data(self, cdate):
        self.calls["get_spo2_data"] += 1
        day = self.days.get(cdate) or {}
        return day.get("spo2")

    def get_respiration_data(self, cdate):
        self.calls["get_respiration_data"] += 1
        day = self.days.get(cdate) or {}
        return day.get("respiration")


def _synthetic_day(
    total_steps=5928,
    resting_hr=56,
    stress_avg=24,
    spo2_avg=95.0,
    respiration_avg=15.0,
    moderate=40,
    vigorous=5,
):
    return {
        "stats": {
            "calendarDate": "placeholder",
            "totalSteps": total_steps,
            "restingHeartRate": resting_hr,
            "averageStressLevel": stress_avg,
            "averageSpo2": spo2_avg,
            "avgWakingRespirationValue": respiration_avg,
            "moderateIntensityMinutes": moderate,
            "vigorousIntensityMinutes": vigorous,
        },
        "spo2": {"averageSpo2": spo2_avg},
        "respiration": {"avgWakingRespirationValue": respiration_avg},
    }


def _synthetic_days(n=3):
    return {f"2026-01-0{i + 1}": _synthetic_day(total_steps=5000 + i) for i in range(n)}


# --- map_daily_health_to_row ------------------------------------------------


def test_map_daily_health_to_row_maps_known_fields_from_live_fixture(sample_daily_health):
    row = map_daily_health_to_row(
        sample_daily_health, "2026-07-04", spo2=None, respiration=None
    )

    assert row["date"] == date(2026, 7, 4)
    assert row["total_steps"] == 5928
    assert row["resting_hr"] == 56
    assert row["stress_avg"] == 24
    assert row["spo2_avg"] == 95
    assert row["respiration_avg"] == 15.0
    assert row["intensity_minutes_moderate"] == 40
    assert row["intensity_minutes_vigorous"] == 5


def test_map_daily_health_to_row_null_spo2_still_stores_steps_and_hr():
    stats = _synthetic_day()["stats"]
    stats["averageSpo2"] = None
    stats["avgWakingRespirationValue"] = None

    row = map_daily_health_to_row(stats, "2026-01-01", spo2=None, respiration=None)

    assert row["total_steps"] == 5928
    assert row["resting_hr"] == 56
    assert row["spo2_avg"] is None
    assert row["respiration_avg"] is None


def test_map_daily_health_to_row_tolerates_missing_stats_fields():
    row = map_daily_health_to_row({}, "2026-01-01")

    assert row["total_steps"] is None
    assert row["resting_hr"] is None
    assert row["stress_avg"] is None
    assert row["spo2_avg"] is None
    assert row["respiration_avg"] is None
    assert row["intensity_minutes_moderate"] is None
    assert row["intensity_minutes_vigorous"] is None


def test_map_daily_health_to_row_raises_on_missing_cdate():
    with pytest.raises(ValueError):
        map_daily_health_to_row({}, "")


def test_map_daily_health_to_row_raises_on_unparseable_cdate():
    with pytest.raises(ValueError):
        map_daily_health_to_row({}, "not-a-date")


# --- backfill_daily_health / sync_daily_health_window ----------------------


def test_backfill_daily_health_inserts_rows(db_session):
    client = FakeGarminClient(_synthetic_days(3))

    count = backfill_daily_health(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 3
    assert db_session.query(DailyHealth).count() == 3


def test_backfill_daily_health_skips_days_with_no_data_without_counting_as_error(db_session):
    days = _synthetic_days(3)
    days["2026-01-02"] = None  # no stats bundle that day
    client = FakeGarminClient(days)

    count = backfill_daily_health(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 2
    assert db_session.query(DailyHealth).count() == 2


def test_backfill_daily_health_skips_malformed_day_without_aborting(db_session, monkeypatch):
    days = _synthetic_days(3)
    client = FakeGarminClient(days)

    original_get_spo2 = client.get_spo2_data

    def flaky_get_spo2(cdate):
        if cdate == "2026-01-02":
            raise TypeError("simulated malformed payload")
        return original_get_spo2(cdate)

    monkeypatch.setattr(client, "get_spo2_data", flaky_get_spo2)

    count = backfill_daily_health(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 2
    assert db_session.query(DailyHealth).count() == 2


def test_backfill_daily_health_skips_wrong_shaped_day_without_losing_other_days(db_session):
    """Regression (CR-01): a wrong-shaped stats bundle (a non-dict where a
    dict is expected) raises AttributeError inside map_daily_health_to_row.
    The narrow (KeyError, ValueError, TypeError) catch let it escape the
    per-day loop and abort the run before the end-only commit, discarding
    every already-processed day. The malformed day must be skipped and the
    good days on either side must still be upserted."""
    days = _synthetic_days(3)
    # stats is a list instead of a dict -> stats.get(...) raises AttributeError.
    days["2026-01-02"]["stats"] = ["not", "a", "dict"]
    client = FakeGarminClient(days)

    count = backfill_daily_health(db_session, client, start="2026-01-01", end="2026-01-03")

    assert count == 2
    assert db_session.query(DailyHealth).count() == 2
    assert db_session.get(DailyHealth, date(2026, 1, 1)) is not None
    assert db_session.get(DailyHealth, date(2026, 1, 3)) is not None
    assert db_session.get(DailyHealth, date(2026, 1, 2)) is None


def test_sync_daily_health_window_is_idempotent_and_self_heals(db_session):
    days = _synthetic_days(2)
    client = FakeGarminClient(days)

    sync_daily_health_window(db_session, client, start="2026-01-01", end="2026-01-02")
    assert db_session.query(DailyHealth).count() == 2

    # Simulate a re-scored day between runs (Garmin revises stress avg).
    days["2026-01-01"]["stats"]["averageStressLevel"] = 55

    count = sync_daily_health_window(db_session, client, start="2026-01-01", end="2026-01-02")

    assert count == 2
    assert db_session.query(DailyHealth).count() == 2  # no duplicates
    updated = db_session.get(DailyHealth, date(2026, 1, 1))
    assert updated.stress_avg == 55


def test_backfill_daily_health_calls_get_stats_once_per_day_no_double_calling(db_session):
    client = FakeGarminClient(_synthetic_days(3))

    backfill_daily_health(db_session, client, start="2026-01-01", end="2026-01-03")

    assert client.calls["get_stats"] == 3
    assert client.calls["get_spo2_data"] == 3
    assert client.calls["get_respiration_data"] == 3


def test_backfill_daily_health_throttles_inside_the_loop(db_session, monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "app.sync.daily_health.time.sleep", lambda seconds: sleeps.append(seconds)
    )
    client = FakeGarminClient(_synthetic_days(3))

    backfill_daily_health(db_session, client, start="2026-01-01", end="2026-01-03")

    # One throttle call per day iterated (not once for the whole backfill).
    assert len(sleeps) == 3
