"""Garmin activity -> Workout row mapping and idempotent backfill sync.

Field names below are the EXACT names confirmed against a real, live Garmin
activity payload (see ``backend/tests/fixtures/sample_activity.json`` and
Plan 01's SUMMARY.md) -- not assumed from memory or documentation, per
RESEARCH.md Pitfall 2.
"""

import json
import time
from datetime import date, datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models import Workout

# Garmin's activity list endpoint returns startTimeLocal formatted like
# "2026-07-04 12:09:00" (confirmed via the live fixture).
_START_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def map_activity_to_row(raw: dict) -> dict:
    """Map a raw Garmin activity dict onto a ``Workout`` row dict.

    Optional summary fields degrade to ``None`` rather than raising
    (T-02-01 mitigation). The two fields a row cannot exist without --
    ``activityId`` (primary key) and ``startTimeLocal`` -- raise ``ValueError``
    if absent/unparseable so the caller can skip *that* activity without
    aborting the whole backfill (see ``backfill_workouts``). ``activity_type``
    is a NOT NULL column, so a missing ``typeKey`` degrades to ``"unknown"``
    rather than producing an ``IntegrityError``. The full raw payload is always
    preserved in the ``raw`` column (D-03/DATA-07) regardless of mapping.
    """
    activity_type_field = raw.get("activityType") or {}

    activity_id = raw.get("activityId")
    if activity_id is None:
        raise ValueError("activity is missing required 'activityId'")

    start_time_raw = raw.get("startTimeLocal")
    if not start_time_raw:
        raise ValueError("activity is missing required 'startTimeLocal'")
    # strptime raises ValueError on a malformed value -- surfaced to the caller.
    start_time = datetime.strptime(start_time_raw, _START_TIME_FORMAT)

    average_hr = raw.get("averageHR")
    calories = raw.get("calories")

    return {
        "activity_id": int(activity_id),
        "activity_type": activity_type_field.get("typeKey") or "unknown",
        "start_time": start_time,
        "distance_m": raw.get("distance"),
        "duration_s": raw.get("duration"),
        "average_hr": int(average_hr) if average_hr is not None else None,
        "calories": int(calories) if calories is not None else None,
        "raw": json.dumps(raw, sort_keys=True),
    }


def _upsert_workout(session, row: dict) -> None:
    stmt = sqlite_insert(Workout).values(**row)
    stmt = stmt.on_conflict_do_update(
        index_elements=["activity_id"],
        set_={k: v for k, v in row.items() if k != "activity_id"},
    )
    session.execute(stmt)


def backfill_workouts(session, client, start: str = "2000-01-01", end: str | None = None) -> int:
    """Full-history backfill: fetch every Garmin activity and upsert it.

    Reuses the already-authenticated ``client`` (never re-logs in inside
    this loop -- T-02-02 mitigation). Idempotent: re-running does not
    create duplicate rows, and changed fields are updated in place.
    """
    activities = client.get_activities_by_date(
        start,
        end or date.today().isoformat(),
        sortorder="asc",
    )
    # Cheap insurance against Garmin's unofficial-API rate limiting
    # (RESEARCH.md Pitfall 3) -- one delay per page-fetching call.
    time.sleep(0.2)

    count = 0
    skipped = 0
    for raw in activities:
        try:
            row = map_activity_to_row(raw)
        except (KeyError, ValueError, TypeError) as exc:
            # One malformed/renamed activity must never abort the whole backfill
            # (T-02-01). Skip it -- its data is not silently lost, since a
            # re-run will pick it up once Garmin's payload is well-formed again.
            skipped += 1
            aid = raw.get("activityId") if isinstance(raw, dict) else None
            print(f"[sync] skipped unmappable activity {aid!r}: {exc}")
            continue
        _upsert_workout(session, row)
        count += 1

    session.commit()
    if skipped:
        print(f"[sync] backfill complete: {count} upserted, {skipped} skipped")
    return count
