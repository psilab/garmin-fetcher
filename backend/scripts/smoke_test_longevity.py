"""Live smoke test: VO2max date-variance + training-load key-path discovery.

BLOCKING prerequisite for Plan 03-02 Task 3 (per upstream issue #74: some
Garmin accounts have been observed returning the SAME calendarDate/
vo2MaxValue pair for every historical date passed to get_max_metrics,
which would make a day-by-day historical backfill silently write an
identical (wrong) longevity trajectory for every day).

Run (live, against the bootstrapped tokens volume; not a pytest file --
there is no live Garmin account in CI, per 03-VALIDATION.md's Manual-Only
Verifications table):

    docker compose run --rm backend python scripts/smoke_test_longevity.py

--- LIVE FINDINGS (recorded after running this script on this account) ---

(a) get_max_metrics RESPONSE SHAPE CORRECTION (RESEARCH.md's assumed
    shape was wrong, corrected here from the real live payload):
    `get_max_metrics(cdate)` returns a LIST (`[{"generic": {...}, ...}]`),
    NOT a bare dict as RESEARCH.md's `{"generic": {...}}` assumption
    stated. It also returns an EMPTY LIST (`[]`) for most calendar
    dates -- the account's watch only pushes a VO2max reading on days
    it actually recalculates one, not every day. `map_longevity_to_row`
    must take the FIRST element of the list (or `{}` if the list is
    empty/falsy) before reading `.get("generic")`.

    get_max_metrics date-variance (once the list-shape bug above is
    fixed): CONFIRMED: get_max_metrics is date-correct on this account.
    2025-01-13 -> generic.calendarDate="2025-01-13",
    generic.vo2MaxValue=39.0; 2025-06-14 ->
    generic.calendarDate="2025-06-14", generic.vo2MaxValue=43.0 --
    DIFFERENT values on dates ~5 months apart, so the issue #74
    same-day bug is NOT present on this account. Historical backfill
    via backfill_longevity is safe to ship as a real per-day backfill.
    (NOTE: naively parsing get_max_metrics as a bare dict, as
    RESEARCH.md originally assumed, makes every call look like a
    same-day match -- always `generic=None` -- which would have been
    misdiagnosed as the issue #74 WARNING. Confirm the list-unwrap is
    in place before trusting any date-variance verdict.)

(b) get_training_status training-load key path: CONFIRMED. The live
    payload has NO top-level numeric "trainingLoad" field. The
    confirmed numeric acute/chronic training-load value lives at:

        mostRecentTrainingStatus
          .latestTrainingStatusData
            .<dynamic device id, e.g. "3476168089">
              .acuteTrainingLoadDTO
                .dailyTrainingLoadAcute   (int | None)

    -- nested one level deeper than sleep.py's existing
    `trainingStatusFeedbackPhrase` lookup (same
    `mostRecentTrainingStatus.latestTrainingStatusData.<device id>`
    parent dict), sibling keys `dailyTrainingLoadChronic`,
    `dailyAcuteChronicWorkloadRatio`, `acwrStatus` on the same
    `acuteTrainingLoadDTO` dict. `map_longevity_to_row` parses
    `dailyTrainingLoadAcute` via this exact path, degrading to `None`
    on any missing/malformed key rather than raising (WR-02 parity).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as a plain script (``python scripts/smoke_test_longevity.py``,
# the acceptance-criteria invocation) as well as as a module -- when run
# directly, Python puts scripts/ on sys.path, not /app, so `import app...`
# fails without this (mirrors the fix, not capture_fixtures.py's -m-only
# convention, since this script's own acceptance criteria mandates the
# plain-script invocation).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.garmin import NotAuthenticated, get_client  # noqa: E402

# Two historical dates >= 4 months apart. get_max_metrics only returns data
# on the (infrequent) days the watch actually recalculated VO2max -- these
# two were confirmed live to have a non-empty reading on this account.
# Adjust if either stops returning data (e.g. account/device change).
DATE_A = "2025-01-13"
DATE_B = "2025-06-14"


def _print_max_metrics(label: str, payload: list | None) -> tuple[str | None, float | None]:
    # get_max_metrics returns a LIST (often empty on days with no new
    # reading), not a bare dict -- see module docstring finding (a).
    first = (payload or [{}])[0] if isinstance(payload, list) else (payload or {})
    generic = (first or {}).get("generic") or {}
    cdate = generic.get("calendarDate")
    vo2max = generic.get("vo2MaxValue")
    print(f"  {label}: generic.calendarDate={cdate!r} generic.vo2MaxValue={vo2max!r}")
    return cdate, vo2max


def main() -> int:
    try:
        client = get_client()
    except NotAuthenticated as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"\n=== get_max_metrics date-variance check ({DATE_A} vs {DATE_B}) ===")
    metrics_a = client.get_max_metrics(DATE_A)
    metrics_b = client.get_max_metrics(DATE_B)
    cdate_a, vo2_a = _print_max_metrics(DATE_A, metrics_a)
    cdate_b, vo2_b = _print_max_metrics(DATE_B, metrics_b)

    if (cdate_a, vo2_a) == (cdate_b, vo2_b):
        print("WARNING: issue #74 same-day bug still present")
    else:
        print("CONFIRMED: get_max_metrics is date-correct on this account")

    print(f"\n=== get_training_status full payload ({DATE_A}) ===")
    status_a = client.get_training_status(DATE_A)
    print(json.dumps(status_a, indent=2, default=str))

    print(f"\n=== get_training_status full payload ({DATE_B}) ===")
    status_b = client.get_training_status(DATE_B)
    print(json.dumps(status_b, indent=2, default=str))

    print(
        "\nDone. Inspect the printed get_training_status JSON above to locate\n"
        "the numeric acute/chronic training-load key path, then record both\n"
        "findings in this script's module docstring (see LIVE FINDINGS)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
