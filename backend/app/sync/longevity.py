"""Garmin longevity markers (VO2max + training_load) -> LongevityMarker row
mapping and idempotent sync.

Mirrors ``sync/daily_health.py``'s per-day CR-01/WR-02 structure exactly.
Unlike Sleep/DailyHealth/BodyComposition (typed columns sourced from
``raw`` payloads already being fetched elsewhere), VO2max/training_load
have NO backing column or stored raw payload anywhere else today -- this
is a genuinely NEW Garmin sync (D-05/D-01 correction).

Field/key-path notes below are the EXACT shapes confirmed against a real,
live Garmin account (see ``backend/scripts/smoke_test_longevity.py``'s
module docstring "LIVE FINDINGS" -- not assumed from memory or
documentation):

- ``get_max_metrics(cdate)`` returns a LIST (often EMPTY on days the
  watch did not recalculate VO2max that day), each element shaped like
  ``{"generic": {"calendarDate": ..., "vo2MaxValue": ..., "fitnessAge":
  ...}, ...}``. ``map_longevity_to_row`` takes the first element (or
  ``{}`` if the list is empty/falsy).
- ``get_training_status(cdate)``'s numeric training-load value lives at
  ``mostRecentTrainingStatus.latestTrainingStatusData.<dynamic device
  id>.acuteTrainingLoadDTO.dailyTrainingLoadAcute`` (confirmed live;
  nested one level deeper than sleep.py's existing
  ``trainingStatusFeedbackPhrase`` lookup on the same
  ``mostRecentTrainingStatus.latestTrainingStatusData.<device id>``
  parent dict).
- Live date-variance smoke test CONFIRMED ``get_max_metrics`` is
  date-correct on this account (issue #74 same-day bug NOT present), so
  ``backfill_longevity`` below ships as a real per-day historical
  backfill, not a going-forward-only capture.
"""

import json
import time
from datetime import date

from app.models import LongevityMarker
from app.sync.common import _daterange, _upsert

# Confirmed per-day getter throttle: 2 per-day calls (get_max_metrics +
# get_training_status) -- lighter than sleep.py's 5-call 0.7s throttle,
# proportional sizing per PATTERNS.md guidance (mirrors daily_health.py's
# reasoning for its own 0.4s throttle).
_DEFAULT_THROTTLE = 0.4


def _num_or_none(v, cast):
    """Degrade a malformed/non-numeric Garmin value to None instead of
    persisting an untyped value that crashes get_trend's
    np.array(..., dtype=float) at read time (WR-01) -- same shape as the
    existing vo2max float(...) try/except below."""
    if v is None:
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def map_longevity_to_row(max_metrics: list | dict | None, training_status: dict | None, cdate: str) -> dict:
    """Map a per-day ``get_max_metrics`` + ``get_training_status`` payload
    pair onto a ``LongevityMarker`` row dict.

    ``cdate`` (the calendar date) is the one required field -- missing/
    unparseable raises ``ValueError`` so the caller can skip that day
    without aborting the whole sync (CR-01 parity, mirrors
    ``map_daily_health_to_row``). Every other field degrades to ``None``
    on a malformed/missing value rather than raising (WR-02 parity): a
    malformed ``vo2MaxValue`` never drops ``fitness_age``/
    ``training_load`` from the same row. ``raw`` is always preserved as
    ``json.dumps(..., sort_keys=True)`` (DATA-07/D-06).
    """
    if not cdate:
        raise ValueError("longevity row is missing required 'cdate'")
    row_date = date.fromisoformat(cdate)

    # get_max_metrics returns a LIST (often empty) -- take the first
    # element, defensively handling a bare dict too (belt-and-braces).
    if isinstance(max_metrics, list):
        first = max_metrics[0] if max_metrics else {}
    else:
        first = max_metrics or {}
    generic = (first or {}).get("generic") or {}

    vo2max = generic.get("vo2MaxValue")
    if vo2max is not None:
        try:
            vo2max = float(vo2max)
        except (TypeError, ValueError):
            vo2max = None

    fitness_age = _num_or_none(generic.get("fitnessAge"), int)

    training_load = None
    try:
        device_map = (
            (training_status or {}).get("mostRecentTrainingStatus") or {}
        ).get("latestTrainingStatusData") or {}
        for device_data in device_map.values():
            acute = (device_data or {}).get("acuteTrainingLoadDTO") or {}
            val = acute.get("dailyTrainingLoadAcute")
            if val is not None:
                training_load = val
                break
    except (AttributeError, TypeError):
        training_load = None
    training_load = _num_or_none(training_load, float)

    raw = json.dumps(
        {"max_metrics": max_metrics, "training_status": training_status}, sort_keys=True
    )

    return {
        "date": row_date,
        "vo2max": vo2max,
        "fitness_age": fitness_age,
        "training_load": training_load,
        "raw": raw,
    }


def _iter_longevity_days(
    session, client, start: str, end: str, throttle: float = _DEFAULT_THROTTLE
) -> int:
    """Shared per-day loop backing both ``backfill_longevity`` and
    ``sync_longevity_window``.

    Reuses the already-authenticated ``client`` (never re-logs in inside
    the loop -- T-02-02). Per-day isolation: one malformed/errored day is
    skipped and logged, never aborting the whole run (CR-01). Days with
    no data from either getter are skipped without counting as an error
    (mirrors the "no data that day" precedent in daily_health.py).

    Commits per day (not once at the end like the other domains) so that
    ``session.rollback()`` in the except handler below only ever discards
    the CURRENT failing day's uncommitted work -- never a previously
    successful day's already-upserted row, which is durable the moment
    its commit returns (WR-04's must-have: "every subsequent day in the
    same CLI backfill run still persists").
    """
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)

    count = 0
    skipped = 0
    for d in _daterange(start_date, end_date):
        cdate = d.isoformat()
        row = None
        try:
            max_metrics = client.get_max_metrics(cdate)
            training_status = client.get_training_status(cdate)
            if not max_metrics and not training_status:
                continue
            row = map_longevity_to_row(max_metrics, training_status, cdate)
            _upsert(session, LongevityMarker, row, key="date")
            session.commit()
            count += 1
        except Exception as exc:  # untrusted Garmin JSON / DB upsert: isolate the day, never abort the run (CR-01/WR-04)
            skipped += 1
            print(f"[sync:longevity] skipped {cdate}: {type(exc).__name__}: {exc}")
            # A genuine DB-level upsert failure leaves the session in a
            # pending-rollback state; without this, the NEXT day's
            # _upsert (or the final session.commit()) would itself raise,
            # cascading one bad day into aborting the whole run despite
            # the try/except (WR-04, matches scheduler.py's per-domain
            # rollback shape). Safe to call unconditionally here because
            # each day now commits its own work immediately above, so
            # there is never a PRIOR day's uncommitted row still pending
            # to be discarded by this rollback.
            session.rollback()
            continue
        finally:
            time.sleep(throttle)

    if skipped:
        print(f"[sync:longevity] window complete: {count} upserted, {skipped} skipped")
    return count


def backfill_longevity(
    session, client, start: str = "2000-01-01", end: str | None = None
) -> int:
    """Full-history backfill: iterate every date from ``start`` to today and
    upsert each day's VO2max/training_load.

    Safe to ship as a real per-day historical backfill on this account --
    the live smoke test (``backend/scripts/smoke_test_longevity.py``)
    CONFIRMED ``get_max_metrics`` is date-correct here (issue #74 same-day
    bug not present). If a future account/device DOES exhibit the same-day
    bug, re-run the smoke test and scope this function down to
    going-forward-only capture before trusting a backfill on that account.
    """
    return _iter_longevity_days(session, client, start, end or date.today().isoformat())


def sync_longevity_window(session, client, start: str, end: str) -> int:
    """Incremental sync over an explicit ``[start, end]`` window (the
    scheduler's rolling/catch-up window from ``sync/common.window_for``)."""
    return _iter_longevity_days(session, client, start, end)
