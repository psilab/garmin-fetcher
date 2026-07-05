"""Shared sync helpers reused by every date-keyed domain (sleep, daily_health,
body_composition): date-range iteration, a model-agnostic idempotent upsert,
and the self-healing catch-up window helper (DATA-05).

Generalized from ``backend/app/sync/workouts.py``'s ``_upsert_workout`` -- see
Plan 02-02 and RESEARCH.md Pattern 1/2.
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


def _daterange(start: date, end: date):
    """Yield every date from ``start`` to ``end`` inclusive."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _upsert(session, model, row: dict, key: str) -> None:
    """Insert ``row`` into ``model``'s table, or update all non-key columns
    in place on a conflicting ``key`` (idempotent self-heal -- DATA-05)."""
    stmt = sqlite_insert(model).values(**row)
    stmt = stmt.on_conflict_do_update(
        index_elements=[key],
        set_={k: v for k, v in row.items() if k != key},
    )
    session.execute(stmt)


def window_for(
    session, model, today: date | None = None, min_days: int = 7
) -> tuple[date | None, date]:
    """Return the ``(start, end)`` catch-up window for an incremental sync.

    - Empty table (no rows yet) -> ``(None, today)``, signalling the caller
      should run a full backfill instead (D-03).
    - Otherwise, the window always re-covers at least ``min_days`` (rolling
      window, the self-healing mechanism -- re-scored days upsert in place)
      and widens further back to the last-synced date if the gap since the
      last sync exceeds ``min_days`` (catch-up after downtime, D-05).
    """
    today = today or date.today()
    last = session.execute(select(func.max(model.date))).scalar_one_or_none()
    if last is None:
        return None, today
    start = min(last, today - timedelta(days=min_days))
    return start, today
