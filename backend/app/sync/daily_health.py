"""Garmin all-day health -> DailyHealth row mapping and idempotent sync.

Mirrors ``sync/sleep.py``'s per-day structure, but minimizes per-day call
count by using ``get_stats(cdate)`` as the PRIMARY bundle (steps, resting HR,
stress avg, intensity minutes, and -- per the CONFIRMED live fixture,
``backend/tests/fixtures/sample_daily_health.json`` -- SpO2 avg and waking
respiration avg all live in the same bundle) (RESEARCH.md recommendation,
D-anti-pattern: no double-calling per-field getters).

Field names below are the EXACT names confirmed against a real, live Garmin
``get_stats`` payload (see the fixture above and 02-01-SUMMARY.md) -- not
assumed from memory or documentation.

Typed-column source note (mirrors Plan 02-02's ``hrv_avg`` decision for
sleep): ``spo2_avg``/``respiration_avg`` are sourced from ``get_stats``'
own ``averageSpo2``/``avgWakingRespirationValue`` keys, since the CONFIRMED
fixture shows the bundle already carries them. ``get_spo2_data``/
``get_respiration_data`` are still called every day and merged into the
combined ``raw`` payload (DATA-07/D-06, defensiveness/future use per the
plan's supplement-getter design) but are not the typed-column source.
"""

import json
import time
from datetime import date

from app.models import DailyHealth
from app.sync.common import _daterange, _upsert

# Confirmed per-day getter throttle: lighter than sleep.py's 0.7s because
# daily_health makes 3 per-day calls (get_stats primary + 2 supplements)
# versus sleep's 5 per-day getters (RESEARCH Pitfall 2, proportional sizing).
_DEFAULT_THROTTLE = 0.4


def map_daily_health_to_row(
    stats: dict, cdate: str, spo2: dict | None = None, respiration: dict | None = None
) -> dict:
    """Map a per-day ``get_stats`` bundle (plus supplement payloads) onto a
    ``DailyHealth`` row dict.

    ``stats`` is the primary ``get_stats(cdate)`` bundle; ``spo2``/
    ``respiration`` are the supplement ``get_spo2_data``/
    ``get_respiration_data`` payloads, merged into ``raw`` for completeness
    but not the typed-column source (see module docstring).

    ``cdate`` (the calendar date) is the one required field -- missing/
    unparseable raises ``ValueError`` so the caller can skip that day
    without aborting the whole sync (CR-01/CR-02 lesson, mirrors
    ``map_sleep_to_row``). Every other field degrades to ``None`` when
    absent (e.g. a day missing SpO2/respiration still stores steps/
    resting_hr). ``raw`` is always preserved as
    ``json.dumps(..., sort_keys=True)`` (DATA-07/D-06).
    """
    if not cdate:
        raise ValueError("daily health row is missing required 'cdate'")
    row_date = date.fromisoformat(cdate)

    stats = stats or {}

    spo2_avg = stats.get("averageSpo2")
    if spo2_avg is not None:
        # Degrade only THIS field to None on a malformed value (WR-02): an
        # unconditional int() would raise ValueError and drop the entire
        # day's row (steps, resting HR, stress, ...), contradicting the
        # documented "a day missing SpO2 still stores steps/resting_hr".
        try:
            spo2_avg = int(spo2_avg)
        except (TypeError, ValueError):
            spo2_avg = None

    combined = {"stats": stats, "spo2": spo2, "respiration": respiration}

    return {
        "date": row_date,
        "total_steps": stats.get("totalSteps"),
        "resting_hr": stats.get("restingHeartRate"),
        "stress_avg": stats.get("averageStressLevel"),
        "spo2_avg": spo2_avg,
        "respiration_avg": stats.get("avgWakingRespirationValue"),
        "intensity_minutes_moderate": stats.get("moderateIntensityMinutes"),
        "intensity_minutes_vigorous": stats.get("vigorousIntensityMinutes"),
        "raw": json.dumps(combined, sort_keys=True),
    }


def _iter_daily_health_days(
    session, client, start: str, end: str, throttle: float = _DEFAULT_THROTTLE
) -> int:
    """Shared per-day loop backing both ``backfill_daily_health`` and
    ``sync_daily_health_window``.

    Reuses the already-authenticated ``client`` (never re-logs in inside the
    loop -- T-02-02). Per-day isolation: one malformed/errored day is
    skipped and logged, never aborting the whole run (CR-01/CR-02). Days
    with no stats bundle are skipped without counting as an error. The
    throttle sits *inside* the loop (mirrors sleep.py's Pitfall 2 handling).
    """
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)

    count = 0
    skipped = 0
    for d in _daterange(start_date, end_date):
        cdate = d.isoformat()
        row = None
        try:
            stats = client.get_stats(cdate)
            if not stats:
                continue
            spo2 = client.get_spo2_data(cdate)
            respiration = client.get_respiration_data(cdate)
            row = map_daily_health_to_row(stats, cdate, spo2=spo2, respiration=respiration)
        except Exception as exc:  # untrusted Garmin JSON: isolate the day, never abort the run (CR-01)
            # Broad on purpose (mirrors sleep.py): a wrong-shaped payload
            # raises AttributeError, which a narrow (KeyError, ValueError,
            # TypeError) tuple would let escape and abort the whole run.
            # KeyboardInterrupt/SystemExit are BaseException, so they still
            # propagate.
            skipped += 1
            print(f"[sync:daily_health] skipped {cdate}: {type(exc).__name__}: {exc}")
            continue
        finally:
            # Rate-limit insurance per per-day call batch (mirrors sleep.py).
            time.sleep(throttle)

        _upsert(session, DailyHealth, row, key="date")
        count += 1

    session.commit()
    if skipped:
        print(f"[sync:daily_health] window complete: {count} upserted, {skipped} skipped")
    return count


def backfill_daily_health(
    session, client, start: str = "2000-01-01", end: str | None = None
) -> int:
    """Full-history backfill: iterate every date from ``start`` to today and
    upsert each day's all-day health summary."""
    return _iter_daily_health_days(session, client, start, end or date.today().isoformat())


def sync_daily_health_window(session, client, start: str, end: str) -> int:
    """Incremental sync over an explicit ``[start, end]`` window (the
    scheduler's rolling/catch-up window from ``sync/common.window_for``)."""
    return _iter_daily_health_days(session, client, start, end)
