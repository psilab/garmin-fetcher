"""Garmin sleep & recovery -> Sleep row mapping and idempotent sync.

Sleep is the reference/per-day domain: mirrors ``sync/workouts.py`` but the
Garmin getters here are per-day (one HTTP call per calendar day rather than
one range call), so the rate-limit throttle moves *inside* the date loop and
is larger (RESEARCH.md Pitfall 2).

Field names below are the EXACT names confirmed against a real, live Garmin
sleep + body-battery payload (see ``backend/tests/fixtures/sample_sleep.json``
and Plan 02-01's SUMMARY.md) -- not assumed from memory or documentation.

Body-battery high/low: neither ``get_sleep_data`` nor ``get_body_battery``
exposes a clean daily scalar (02-01-SUMMARY). We derive
``body_battery_high``/``body_battery_low`` as the max/min of the day's
``bodyBatteryValuesArray`` level column from ``get_body_battery`` -- this
keeps the sleep slice self-contained (does not depend on ``get_stats``,
which Plan 02-03 owns for ``daily_health``).
"""

import json
import time
from datetime import date

from app.models import Sleep
from app.sync.common import _daterange, _upsert

# Confirmed per-day getter throttle: heavier than workouts.py's single
# range-call throttle (0.2s) because sleep syncs make five per-day calls
# (sleep, HRV, training readiness, training status, body battery).
_DEFAULT_THROTTLE = 0.7


def _body_battery_high_low(body_battery) -> tuple[int | None, int | None]:
    """Derive (high, low) body-battery levels from a get_body_battery result.

    ``get_body_battery`` returns a list of per-day entries; each entry's
    ``bodyBatteryValuesArray`` is a list of ``[timestamp, ...]`` rows whose
    column order is described by ``bodyBatteryValueDescriptorDTOList``
    (confirmed live: index 0 = timestamp, index 1 = bodyBatteryLevel).
    Defensive: tolerates an empty/None list, missing descriptor, or short
    rows -- degrades to ``(None, None)`` rather than raising.
    """
    if not body_battery:
        return None, None
    entry = body_battery[0] if isinstance(body_battery, list) else body_battery
    if not isinstance(entry, dict):
        return None, None

    values_array = entry.get("bodyBatteryValuesArray") or []
    descriptor = entry.get("bodyBatteryValueDescriptorDTOList") or []

    level_idx = 1  # confirmed default per live fixture
    for d in descriptor:
        if d.get("bodyBatteryValueDescriptorKey") == "bodyBatteryLevel":
            level_idx = d.get("bodyBatteryValueDescriptorIndex", level_idx)
            break

    levels = [
        row[level_idx]
        for row in values_array
        if isinstance(row, list) and len(row) > level_idx and row[level_idx] is not None
    ]
    if not levels:
        return None, None
    return max(levels), min(levels)


def map_sleep_to_row(raw: dict, cdate: str) -> dict:
    """Map a combined per-day sleep payload onto a ``Sleep`` row dict.

    ``raw`` is the combined dict assembled by ``_iter_sleep_days``:
    ``{"sleep": get_sleep_data(cdate), "hrv": get_hrv_data(cdate),
    "training_readiness": get_training_readiness(cdate),
    "training_status": get_training_status(cdate),
    "body_battery": get_body_battery(cdate, cdate)}``.

    ``cdate`` (the calendar date) is the one required field -- missing/
    unparseable raises ``ValueError`` so the caller can skip that day
    without aborting the whole sync (CR-01/CR-02 lesson). Every other
    field degrades to ``None`` when absent (Pitfall 3: ``get_hrv_data``
    may be ``None``, ``get_training_readiness`` returns a list, body
    battery may be an empty list). ``raw`` is always preserved as
    ``json.dumps(raw, sort_keys=True)`` (DATA-07/D-06) regardless of how
    much of the typed mapping below succeeds.
    """
    if not cdate:
        raise ValueError("sleep row is missing required 'cdate'")
    row_date = date.fromisoformat(cdate)

    sleep_dto = (raw or {}).get("sleep") or {}
    daily_sleep = sleep_dto.get("dailySleepDTO") or {}

    sleep_scores = daily_sleep.get("sleepScores") or {}
    overall = sleep_scores.get("overall") or {}
    sleep_score = overall.get("value")

    training_readiness_list = (raw or {}).get("training_readiness") or []
    training_readiness = None
    if isinstance(training_readiness_list, list) and training_readiness_list:
        training_readiness = (training_readiness_list[0] or {}).get("score")

    training_status_dto = (raw or {}).get("training_status") or {}
    training_status = training_status_dto.get("mostRecentTrainingStatus")

    body_battery_high, body_battery_low = _body_battery_high_low(
        (raw or {}).get("body_battery")
    )

    return {
        "date": row_date,
        "sleep_score": sleep_score,
        "deep_s": daily_sleep.get("deepSleepSeconds"),
        "light_s": daily_sleep.get("lightSleepSeconds"),
        "rem_s": daily_sleep.get("remSleepSeconds"),
        "awake_s": daily_sleep.get("awakeSleepSeconds"),
        "hrv_avg": sleep_dto.get("avgOvernightHrv"),
        "body_battery_high": body_battery_high,
        "body_battery_low": body_battery_low,
        "training_readiness": training_readiness,
        "training_status": training_status,
        "raw": json.dumps(raw, sort_keys=True),
    }


def _iter_sleep_days(session, client, start: str, end: str, throttle: float = _DEFAULT_THROTTLE) -> int:
    """Shared per-day loop backing both ``backfill_sleep`` and
    ``sync_sleep_window``.

    Reuses the already-authenticated ``client`` (never re-logs in inside the
    loop -- T-02-02). Per-day isolation: one malformed/errored day is
    skipped and logged, never aborting the whole run (CR-01/CR-02). Days
    with no sleep data are skipped without counting as an error (Pitfall 3).
    The throttle sits *inside* the loop (Pitfall 2 -- five per-day calls,
    heavier than the single range-call throttle in workouts.py).
    """
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)

    count = 0
    skipped = 0
    for d in _daterange(start_date, end_date):
        cdate = d.isoformat()
        row = None
        try:
            sleep_data = client.get_sleep_data(cdate)
            if not sleep_data:
                continue
            hrv_data = client.get_hrv_data(cdate)
            training_readiness = client.get_training_readiness(cdate)
            training_status = client.get_training_status(cdate)
            body_battery = client.get_body_battery(cdate, cdate)
            combined = {
                "sleep": sleep_data,
                "hrv": hrv_data,
                "training_readiness": training_readiness,
                "training_status": training_status,
                "body_battery": body_battery,
            }
            row = map_sleep_to_row(combined, cdate)
        except (KeyError, ValueError, TypeError) as exc:
            skipped += 1
            print(f"[sync:sleep] skipped {cdate}: {exc}")
            continue
        finally:
            # Rate-limit insurance per per-day call batch (RESEARCH Pitfall 2)
            # -- applied whether the day succeeded, was skipped, or errored.
            time.sleep(throttle)

        _upsert(session, Sleep, row, key="date")
        count += 1

    session.commit()
    if skipped:
        print(f"[sync:sleep] window complete: {count} upserted, {skipped} skipped")
    return count


def backfill_sleep(session, client, start: str = "2000-01-01", end: str | None = None) -> int:
    """Full-history backfill: iterate every date from ``start`` to today and
    upsert each day's sleep/recovery summary."""
    return _iter_sleep_days(session, client, start, end or date.today().isoformat())


def sync_sleep_window(session, client, start: str, end: str) -> int:
    """Incremental sync over an explicit ``[start, end]`` window (the
    scheduler's rolling/catch-up window from ``sync/common.window_for``)."""
    return _iter_sleep_days(session, client, start, end)
