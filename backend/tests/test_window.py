from datetime import date

from app.models import Sleep
from app.sync.common import _daterange, _upsert, window_for


def _sleep_row(d: date, sleep_score: int | None = 80) -> dict:
    return {
        "date": d,
        "sleep_score": sleep_score,
        "deep_s": None,
        "light_s": None,
        "rem_s": None,
        "awake_s": None,
        "hrv_avg": None,
        "body_battery_high": None,
        "body_battery_low": None,
        "training_readiness": None,
        "training_status": None,
        "raw": "{}",
    }


def test_daterange_yields_inclusive_dates():
    days = list(_daterange(date(2026, 1, 1), date(2026, 1, 3)))
    assert days == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]


def test_daterange_single_day():
    days = list(_daterange(date(2026, 1, 5), date(2026, 1, 5)))
    assert days == [date(2026, 1, 5)]


def test_upsert_inserts_new_row(db_session):
    _upsert(db_session, Sleep, _sleep_row(date(2026, 1, 1)), key="date")
    db_session.commit()

    assert db_session.query(Sleep).count() == 1
    row = db_session.get(Sleep, date(2026, 1, 1))
    assert row.sleep_score == 80


def test_upsert_updates_in_place_on_conflict(db_session):
    _upsert(db_session, Sleep, _sleep_row(date(2026, 1, 1), sleep_score=80), key="date")
    db_session.commit()

    _upsert(db_session, Sleep, _sleep_row(date(2026, 1, 1), sleep_score=99), key="date")
    db_session.commit()

    assert db_session.query(Sleep).count() == 1
    row = db_session.get(Sleep, date(2026, 1, 1))
    assert row.sleep_score == 99


def test_window_for_empty_table_returns_full_backfill(db_session):
    start, end = window_for(db_session, Sleep, today=date(2026, 7, 5))
    assert start is None
    assert end == date(2026, 7, 5)


def test_window_for_recent_sync_returns_min_days_window(db_session):
    # Last-synced row is yesterday -- well within the rolling window, so the
    # window still re-covers the full min_days (self-heal), not just 1 day.
    _upsert(db_session, Sleep, _sleep_row(date(2026, 7, 4)), key="date")
    db_session.commit()

    start, end = window_for(db_session, Sleep, today=date(2026, 7, 5), min_days=7)

    assert start == date(2026, 6, 28)  # today - 7 days
    assert end == date(2026, 7, 5)


def test_window_for_stale_sync_widens_to_catchup(db_session):
    # Last sync was 20 days ago (downtime) -- gap exceeds min_days, so the
    # window widens back to the last-synced date instead of just 7 days.
    _upsert(db_session, Sleep, _sleep_row(date(2026, 6, 15)), key="date")
    db_session.commit()

    start, end = window_for(db_session, Sleep, today=date(2026, 7, 5), min_days=7)

    assert start == date(2026, 6, 15)
    assert end == date(2026, 7, 5)
