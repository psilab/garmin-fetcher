---
phase: 03-analysis-engine
plan: 02
subsystem: database
tags: [sqlalchemy, alembic, garminconnect, apscheduler, sqlite]

# Dependency graph
requires:
  - phase: 02-domain-sync
    provides: per-day sync pattern (sleep/daily_health/body_composition), _DOMAIN_REGISTRY scheduler, _upsert/_daterange helpers
provides:
  - longevity_markers table + LongevityMarker ORM model (schema-only migration 0003)
  - backend/app/sync/longevity.py (map_longevity_to_row, backfill_longevity, sync_longevity_window)
  - longevity added as 4th domain in the nightly self-healing scheduler
  - live-verified get_max_metrics response shape + training-load key path (backend/scripts/smoke_test_longevity.py)
affects: [03-03 (CLI backfill + MCP tool exposing longevity data)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Live smoke-test-before-code for any Garmin getter whose response shape or date-correctness is unconfirmed (mirrors capture_fixtures.py's Wave-0 discovery pattern, extended to a BLOCKING pre-implementation gate)"

key-files:
  created:
    - backend/scripts/smoke_test_longevity.py
    - backend/alembic/versions/0003_add_longevity_markers.py
    - backend/app/sync/longevity.py
    - backend/tests/test_sync_longevity.py
  modified:
    - backend/app/models.py
    - backend/app/sync/scheduler.py
    - backend/tests/test_migrations.py
    - backend/tests/test_models.py
    - backend/tests/test_scheduler.py

key-decisions:
  - "get_max_metrics returns a LIST (often empty), not the bare dict RESEARCH.md assumed -- corrected live and documented in the smoke test's own docstring before Task 3 wrote any parsing code"
  - "Live smoke test confirmed get_max_metrics is date-correct on this account (39.0 on 2025-01-13 vs 43.0 on 2025-06-14) -- issue #74 same-day bug NOT present, so backfill_longevity ships as a real per-day historical backfill"
  - "training_load parsed from mostRecentTrainingStatus.latestTrainingStatusData.<device id>.acuteTrainingLoadDTO.dailyTrainingLoadAcute -- confirmed live, one level deeper than sleep.py's existing trainingStatusFeedbackPhrase lookup on the same parent dict"

patterns-established:
  - "Pattern: BLOCKING live smoke test as its own committed script (not a pytest file) when a getter's response shape/date-correctness is unconfirmed and materially affects backfill correctness -- findings recorded in the script's own docstring, not a separate doc, so the finding travels with the code that depends on it"

requirements-completed: [ANLZ-04]

# Metrics
duration: 55min
completed: 2026-07-07
---

# Phase 03 Plan 02: Longevity Marker Sync (VO2max + Training Load) Summary

**New Garmin longevity-marker sync (VO2max/training_load) added as a 4th self-healing scheduler domain, gated by a live smoke test that corrected RESEARCH.md's assumed `get_max_metrics` response shape before any backfill code was written.**

## Performance

- **Duration:** 55 min
- **Started:** 2026-07-07T12:51:41Z (approx, per STATE.md session start)
- **Completed:** 2026-07-07
- **Tasks:** 3 completed
- **Files modified:** 9 (4 created, 5 modified)

## Accomplishments

- Live smoke test (`backend/scripts/smoke_test_longevity.py`) proved `get_max_metrics` is date-correct on this account BEFORE any backfill loop was written, and discovered the real (list-shaped) response shape and the exact `training_load` key path -- both materially different from RESEARCH.md's assumptions
- `longevity_markers` table + `LongevityMarker` ORM model, via a schema-only Alembic migration (grep-gated: zero network-client references)
- `backend/app/sync/longevity.py` mirrors `daily_health.py`'s CR-01 (per-day isolation)/WR-02 (single-field degrade-to-None) pattern exactly
- `longevity` wired into the nightly `_DOMAIN_REGISTRY` as a 4th domain with zero changes to `run_daily_sync` itself
- Full backend test suite green: 108 passed

## Task Commits

Each task was committed atomically:

1. **Task 1: Live smoke test — VO2max date-variance + training-load key-path discovery** - `3030479` (feat)
2. **Task 2: longevity_markers migration + LongevityMarker model** - `7cd2e10` (test, RED) -> `84aa63c` (feat, GREEN)
3. **Task 3: sync/longevity.py per-day sync + nightly scheduler wiring** - `1ba832b` (test, RED) -> `5fa6485` (feat, GREEN)

_TDD tasks (2, 3) each have a `test(...)` commit before the `feat(...)` commit, per the plan's RED/GREEN gate requirement._

## Files Created/Modified

- `backend/scripts/smoke_test_longevity.py` - Live (non-pytest) smoke test; module docstring records the confirmed date-variance and training-load findings
- `backend/alembic/versions/0003_add_longevity_markers.py` - Schema-only migration creating `longevity_markers` (revision 0003, down_revision 0002)
- `backend/app/models.py` - Added `class LongevityMarker(Base)` (date PK, vo2max, fitness_age, training_load, raw, synced_at)
- `backend/app/sync/longevity.py` - `map_longevity_to_row`, `_iter_longevity_days`, `backfill_longevity`, `sync_longevity_window`
- `backend/app/sync/scheduler.py` - `LongevityMarker`/`backfill_longevity`/`sync_longevity_window` imports + 4th `_DOMAIN_REGISTRY` tuple
- `backend/tests/test_migrations.py` - `EXPECTED_LONGEVITY_MARKERS_COLUMNS` + upgrade/downgrade tests for `longevity_markers`
- `backend/tests/test_models.py` - `test_longevity_marker_stores_raw_payload`
- `backend/tests/test_sync_longevity.py` - Full coverage of `map_longevity_to_row`/`backfill_longevity`/`sync_longevity_window` behavior (CR-01/WR-02 parity, idempotency, throttle)
- `backend/tests/test_scheduler.py` - `test_run_daily_sync_isolates_a_fourth_domain_failure` (4-domain isolation regression guard)

## Decisions Made

- Corrected `get_max_metrics`'s assumed response shape from RESEARCH.md's bare-dict assumption to the confirmed live LIST shape (often empty on days without a new reading) -- caught by actually running the smoke test rather than trusting the plan's interface contract verbatim
- Adjusted the smoke test's two probe dates from the plan's suggested `2025-01-15`/`2025-06-15` (both returned empty lists) to `2025-01-13`/`2025-06-14` (confirmed live to carry real VO2max readings), per the plan's own "adjust if either returns nothing" instruction
- Added `sys.path` bootstrap to the smoke test script so the plan's literal acceptance-criteria invocation (`python scripts/smoke_test_longevity.py`, not `-m scripts...`) works standalone
- `backfill_longevity` ships as a real per-day historical backfill (not going-forward-only) since the live smoke test confirmed date-correctness on this account

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected the smoke test's own `get_max_metrics` parsing (list vs. dict) before trusting its date-variance verdict**
- **Found during:** Task 1
- **Issue:** The first script draft parsed `get_max_metrics`'s response as a bare dict (`{"generic": {...}}`), per RESEARCH.md's [MEDIUM confidence] assumption. Running it live against real dates showed `get_max_metrics` actually returns a LIST (often empty). Parsing it as a dict silently produced `None`/`None` for every call, which would have been misdiagnosed as the issue #74 same-day bug (a false positive).
- **Fix:** Unwrapped the list's first element (or `{}` if empty) before reading `.get("generic")`, in both the smoke test and `map_longevity_to_row`. Re-ran the smoke test with two dates confirmed to carry real readings; verified DIFFERENT `calendarDate`/`vo2MaxValue` pairs (39.0 vs 43.0).
- **Files modified:** `backend/scripts/smoke_test_longevity.py`
- **Verification:** `docker compose run --rm backend python scripts/smoke_test_longevity.py` exits 0 and prints `CONFIRMED: get_max_metrics is date-correct on this account`
- **Committed in:** `3030479` (Task 1 commit)

**2. [Rule 3 - Blocking] Fixed the acceptance-criteria's literal invocation (`python scripts/smoke_test_longevity.py`) failing with `ModuleNotFoundError: No module named 'app'`**
- **Found during:** Task 1
- **Issue:** Running the script as a plain file (not `-m scripts.smoke_test_longevity`, unlike `capture_fixtures.py`'s documented `-m`-only convention) put `scripts/` on `sys.path` instead of `/app`, so `from app.garmin import ...` failed. The plan's own `<verify>` block mandates the plain-script form.
- **Fix:** Inserted `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` before the `app` import.
- **Files modified:** `backend/scripts/smoke_test_longevity.py`
- **Verification:** `docker compose run --rm backend python scripts/smoke_test_longevity.py` (exact acceptance-criteria command) exits 0
- **Committed in:** `3030479` (Task 1 commit)

**3. [Rule 1 - Bug] Removed forbidden literal strings from migration 0003's own docstring to satisfy the Pitfall-4 grep gate**
- **Found during:** Task 2
- **Issue:** The migration's explanatory docstring mentioned "garminconnect"/"connectapi" by name (explaining why they're absent), which made `grep -c "get_max_metrics\|get_training_status\|garminconnect\|connectapi"` return 1 instead of the required 0 -- a literal-text false positive, not an actual network call.
- **Fix:** Reworded the docstring to describe the constraint without naming the forbidden substrings ("no network-calling client library is imported or invoked here").
- **Files modified:** `backend/alembic/versions/0003_add_longevity_markers.py`
- **Verification:** `grep -c "get_max_metrics\|get_training_status\|garminconnect\|connectapi" backend/alembic/versions/0003_add_longevity_markers.py` returns 0
- **Committed in:** `84aa63c` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (2 bugs, 1 blocking)
**Impact on plan:** All three were necessary to make the plan's own literal acceptance criteria pass and to avoid a false "issue #74 present" diagnosis. No scope creep.

## Issues Encountered

None beyond the deviations documented above.

## User Setup Required

None - no external service configuration required. The live smoke test used the already-bootstrapped Garmin tokens volume (`garmin-fetcher_garmin_tokens`), shared across worktrees via `docker compose -p garmin-fetcher`.

## Next Phase Readiness

- `longevity_markers` table, `LongevityMarker` model, and `sync/longevity.py`'s `map_longevity_to_row`/`backfill_longevity`/`sync_longevity_window` are ready for Plan 03-03 to expose via CLI backfill + MCP tool
- The nightly scheduler already captures VO2max/training_load going forward with the same per-domain isolation as sleep/daily_health/body_composition -- no further scheduler changes needed
- Plan 03-03 should read `backend/scripts/smoke_test_longevity.py`'s docstring for the confirmed `get_max_metrics` list-shape and `training_load` key path before writing any CLI-facing summary/reporting code that re-parses these payloads

---
*Phase: 03-analysis-engine*
*Completed: 2026-07-07*

## Self-Check: PASSED

- FOUND: backend/scripts/smoke_test_longevity.py
- FOUND: backend/alembic/versions/0003_add_longevity_markers.py
- FOUND: backend/app/sync/longevity.py
- FOUND: backend/tests/test_sync_longevity.py
- Commit 3030479: FOUND
- Commit 7cd2e10: FOUND
- Commit 84aa63c: FOUND
- Commit 1ba832b: FOUND
- Commit 5fa6485: FOUND
