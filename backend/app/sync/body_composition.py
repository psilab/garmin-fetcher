"""Garmin weigh-ins -> BodyComposition row mapping and idempotent sync.

EVENT-grained (not per-day): keyed on Garmin's stable ``samplePk`` event key,
not the calendar date -- rows only exist when weigh-ins exist. Uses the cheap
RANGE getter ``get_weigh_ins(start, end)``, which returns a whole date span in
ONE call (RESEARCH KEY DIVERGENCE from sleep/daily_health's per-day loop --
this module is modeled on ``sync/workouts.py``'s range-getter backfill shape,
NOT the per-day loop). See ``backend/tests/fixtures/sample_weigh_ins.json``
and 02-01-SUMMARY.md for the confirmed live payload shape.

Field names below are the EXACT names confirmed against a real, live Garmin
``get_weigh_ins`` payload -- not assumed from memory or documentation, per
RESEARCH.md Pitfall 2.
"""

import json
import time
from datetime import date

from app.models import BodyComposition
from app.sync.common import _upsert

# Cheap insurance against Garmin's unofficial-API rate limiting (RESEARCH.md
# Pitfall 3) -- a single delay per range-fetching call, mirroring
# backfill_workouts' one-call-one-throttle shape (not a per-day loop).
_DEFAULT_THROTTLE = 0.2


def map_body_comp_to_row(entry: dict) -> dict:
    """Map a single weigh-in event (one item from ``allWeightMetrics``) onto
    a ``BodyComposition`` row dict.

    ``samplePk`` (the stable per-event key -> the ``sample_pk`` PK) and
    ``calendarDate`` (-> the non-PK ``date`` column) are the two fields a row
    cannot exist without -- missing/unparseable raises ``ValueError`` so the
    caller can skip *that* weigh-in without aborting the whole sync (mirrors
    ``map_activity_to_row``'s CR-01/CR-02 lesson). ``weight``/``bodyFat``
    degrade to ``None`` when absent (T-02-1x). ``raw`` is always preserved as
    ``json.dumps(entry, sort_keys=True)`` (DATA-07/D-06).
    """
    sample_pk = entry.get("samplePk")
    if sample_pk is None:
        raise ValueError("weigh-in entry is missing required 'samplePk'")

    calendar_date = entry.get("calendarDate")
    if not calendar_date:
        raise ValueError("weigh-in entry is missing required 'calendarDate'")
    # date.fromisoformat raises ValueError on a malformed value -- surfaced
    # to the caller, who skips this one entry.
    row_date = date.fromisoformat(calendar_date)

    weight = entry.get("weight")
    body_fat = entry.get("bodyFat")

    return {
        "sample_pk": int(sample_pk),
        "date": row_date,
        "weight_g": float(weight) if weight is not None else None,
        "body_fat_pct": float(body_fat) if body_fat is not None else None,
        "raw": json.dumps(entry, sort_keys=True),
    }


def _iter_weigh_in_entries(payload: dict):
    """Flatten a ``get_weigh_ins`` payload's ``dailyWeightSummaries`` ->
    ``allWeightMetrics`` structure into individual weigh-in event dicts.

    Missing/empty keys degrade to zero entries (D-04 -- weigh-ins are sparse,
    a span with none is not an error) rather than raising.
    """
    payload = payload or {}
    for day in payload.get("dailyWeightSummaries") or []:
        yield from (day.get("allWeightMetrics") or [])


def sync_body_composition_window(
    session, client, start: str, end: str, throttle: float = _DEFAULT_THROTTLE
) -> int:
    """Sync a single ``[start, end]`` window via ONE call to the RANGE getter
    ``get_weigh_ins`` (RESEARCH KEY DIVERGENCE -- no per-day iteration, unlike
    ``sleep``/``daily_health``; this is the same one-call shape as
    ``backfill_workouts``).

    Reuses the already-authenticated ``client`` (never re-logs in -- T-02-02).
    Per-entry isolation: one malformed weigh-in is skipped and logged, never
    aborting the whole run (CR-01/CR-02 lesson). A span with zero weigh-ins
    produces zero rows without raising (D-04). Re-syncing a window with a
    corrected weigh-in updates the existing event row in place (self-heal --
    upsert is keyed on ``sample_pk``, never ``date``).
    """
    try:
        payload = client.get_weigh_ins(start, end)
    finally:
        time.sleep(throttle)

    count = 0
    skipped = 0
    for entry in _iter_weigh_in_entries(payload):
        try:
            row = map_body_comp_to_row(entry)
        except (KeyError, ValueError, TypeError) as exc:
            skipped += 1
            spk = entry.get("samplePk") if isinstance(entry, dict) else None
            print(f"[sync:body_composition] skipped weigh-in {spk!r}: {exc}")
            continue
        _upsert(session, BodyComposition, row, key="sample_pk")
        count += 1

    session.commit()
    if skipped:
        print(
            f"[sync:body_composition] window complete: {count} upserted, {skipped} skipped"
        )
    return count


def backfill_body_composition(
    session, client, start: str = "2000-01-01", end: str | None = None
) -> int:
    """Full-history backfill: one range-getter call spanning ``start``..today
    (or ``end``), upserting every weigh-in event found."""
    return sync_body_composition_window(
        session, client, start, end or date.today().isoformat()
    )
