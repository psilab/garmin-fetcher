import json

import pytest

from app.models import BodyComposition
from app.sync.body_composition import (
    backfill_body_composition,
    map_body_comp_to_row,
    sync_body_composition_window,
)


class FakeGarminClient:
    """Stand-in for garminconnect.Garmin -- returns a canned get_weigh_ins
    RANGE payload. Tracks call count to prove the range getter is called
    ONCE per window, never per-day (RESEARCH KEY DIVERGENCE)."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get_weigh_ins(self, startdate, enddate):
        self.calls += 1
        return self.payload


def _entry(sample_pk, calendar_date, weight=76000.0, body_fat=None):
    return {
        "samplePk": sample_pk,
        "calendarDate": calendar_date,
        "weight": weight,
        "bodyFat": body_fat,
        "sourceType": "MANUAL",
    }


def _payload(*entries):
    return {"dailyWeightSummaries": [{"allWeightMetrics": [e]} for e in entries]}


def test_map_body_comp_to_row_maps_known_fields_from_live_fixture(sample_weigh_ins):
    entry = sample_weigh_ins["dailyWeightSummaries"][0]["allWeightMetrics"][0]

    row = map_body_comp_to_row(entry)

    assert row["sample_pk"] == entry["samplePk"]
    assert isinstance(row["sample_pk"], int)
    assert row["date"].isoformat() == entry["calendarDate"]
    assert row["weight_g"] == entry["weight"]
    assert row["body_fat_pct"] is None  # live fixture entry has null bodyFat
    assert row["raw"] == json.dumps(entry, sort_keys=True)


def test_map_body_comp_to_row_handles_null_body_fat():
    entry = _entry(1, "2026-01-01", weight=75000.0, body_fat=None)

    row = map_body_comp_to_row(entry)

    assert row["weight_g"] == 75000.0
    assert row["body_fat_pct"] is None


def test_map_body_comp_to_row_handles_present_body_fat():
    entry = _entry(1, "2026-01-01", weight=75000.0, body_fat=18.5)

    row = map_body_comp_to_row(entry)

    assert row["body_fat_pct"] == 18.5


def test_map_body_comp_raises_on_missing_essential_fields():
    with pytest.raises(ValueError):
        map_body_comp_to_row({"calendarDate": "2026-01-01"})  # no samplePk
    with pytest.raises(ValueError):
        map_body_comp_to_row({"samplePk": 1})  # no calendarDate
    with pytest.raises(ValueError):
        map_body_comp_to_row({"samplePk": 1, "calendarDate": "not-a-date"})


def test_sync_window_calls_range_getter_exactly_once(db_session):
    client = FakeGarminClient(_payload(_entry(1, "2026-01-01")))

    sync_body_composition_window(db_session, client, "2026-01-01", "2026-01-31")

    assert client.calls == 1


def test_sync_window_no_weigh_ins_produces_zero_rows(db_session):
    client = FakeGarminClient({"dailyWeightSummaries": []})

    count = sync_body_composition_window(db_session, client, "2026-01-01", "2026-01-31")

    assert count == 0
    assert db_session.query(BodyComposition).count() == 0


def test_sync_window_missing_daily_summaries_key_produces_zero_rows(db_session):
    client = FakeGarminClient({})

    count = sync_body_composition_window(db_session, client, "2026-01-01", "2026-01-31")

    assert count == 0
    assert db_session.query(BodyComposition).count() == 0


def test_sync_window_inserts_rows(db_session):
    client = FakeGarminClient(
        _payload(
            _entry(1, "2026-01-01", weight=75000.0),
            _entry(2, "2026-01-15", weight=75500.0),
        )
    )

    count = sync_body_composition_window(db_session, client, "2026-01-01", "2026-01-31")

    assert count == 2
    assert db_session.query(BodyComposition).count() == 2


def test_sync_window_keyed_on_sample_pk_not_date_self_heals(db_session):
    """Re-syncing a window with a corrected weigh-in updates the existing
    event row in place -- never a duplicate (T-02-13)."""
    payload = _payload(_entry(1, "2026-01-01", weight=75000.0))
    client = FakeGarminClient(payload)

    sync_body_composition_window(db_session, client, "2026-01-01", "2026-01-31")
    assert db_session.query(BodyComposition).count() == 1

    # Simulate a correction on Garmin's side between runs -- same samplePk,
    # same calendar date, different weight.
    payload["dailyWeightSummaries"][0]["allWeightMetrics"][0]["weight"] = 74500.0

    count = sync_body_composition_window(db_session, client, "2026-01-01", "2026-01-31")

    assert count == 1
    assert db_session.query(BodyComposition).count() == 1
    updated = db_session.get(BodyComposition, 1)
    assert updated.weight_g == 74500.0


def test_sync_window_skips_malformed_entries_without_aborting(db_session):
    payload = _payload(
        _entry(1, "2026-01-01"),
        {"weight": 76000.0},  # malformed: no samplePk/calendarDate
        _entry(2, "2026-01-15"),
    )
    client = FakeGarminClient(payload)

    count = sync_body_composition_window(db_session, client, "2026-01-01", "2026-01-31")

    assert count == 2
    assert db_session.query(BodyComposition).count() == 2


def test_sync_window_skips_wrong_shaped_entry_without_aborting(db_session):
    """Regression (CR-01): a wrong-shaped weigh-in (a non-dict, e.g. a bare
    string) raises AttributeError on ``entry.get`` inside map_body_comp_to_row.
    The narrow (KeyError, ValueError, TypeError) catch let it escape the loop
    and abort the run before commit, discarding every already-processed
    entry. The malformed entry must be skipped and the good ones persisted."""
    payload = _payload(
        _entry(1, "2026-01-01"),
        "not-a-dict",  # non-dict entry -> entry.get raises AttributeError
        _entry(2, "2026-01-15"),
    )
    client = FakeGarminClient(payload)

    count = sync_body_composition_window(db_session, client, "2026-01-01", "2026-01-31")

    assert count == 2
    assert db_session.query(BodyComposition).count() == 2


def test_backfill_body_composition_inserts_rows(db_session):
    client = FakeGarminClient(
        _payload(_entry(1, "2026-01-01"), _entry(2, "2026-01-15"))
    )

    count = backfill_body_composition(db_session, client)

    assert count == 2
    assert client.calls == 1
    assert db_session.query(BodyComposition).count() == 2
