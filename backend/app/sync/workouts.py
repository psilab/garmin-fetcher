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

    Every optional field lookup degrades to ``None`` rather than raising
    ``KeyError`` (T-02-01 mitigation) -- a missing/renamed field must never
    crash the whole backfill. The full raw payload is always preserved in
    the ``raw`` column (D-03/DATA-07) regardless of mapping accuracy.
    """
    activity_type_field = raw.get("activityType") or {}

    average_hr = raw.get("averageHR")
    calories = raw.get("calories")

    return {
        "activity_id": int(raw["activityId"]),
        "activity_type": activity_type_field.get("typeKey"),
        "start_time": datetime.strptime(raw["startTimeLocal"], _START_TIME_FORMAT),
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
    for raw in activities:
        row = map_activity_to_row(raw)
        _upsert_workout(session, row)
        count += 1

    session.commit()
    return count
