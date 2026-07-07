---
phase: 03-analysis-engine
plan: 04
subsystem: analysis
tags: [scipy, numpy, sqlalchemy, gap-closure, json-rpc, mcp]

# Dependency graph
requires:
  - phase: 03-analysis-engine
    provides: compute_trend/compute_correlation pure functions (Plan 03-01), longevity sync (Plan 03-03)
provides:
  - _finite_or_none guard in compute_trend so slope/r_value/p_value never leak a raw NaN token into a JSON-RPC response
  - undefined_constant_series short-circuit in compute_correlation before the strength ladder
  - _num_or_none guard on fitness_age/training_load matching vo2max's existing degrade-to-None contract
  - per-day commit + rollback isolation in _iter_longevity_days so one bad day never cascades into losing later days
  - continue-scanning training_load device loop (no longer gives up after the first device)
affects: [03-verification, 03-review, future MCP client hardening]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_finite_or_none(x) / _num_or_none(v, cast) guard helpers: try/except or math.isfinite check that degrades a malformed/non-finite numeric value to None instead of letting it reach a JSON encoder or a typed DB column"
    - "Per-day commit inside a backfill loop (not one commit at the end) so a per-day session.rollback() in the except handler only ever discards the CURRENT day's uncommitted work, never a prior day's already-persisted row"

key-files:
  created: []
  modified:
    - backend/app/analysis/trend.py
    - backend/app/analysis/correlate.py
    - backend/app/sync/longevity.py
    - backend/tests/test_analysis_trend.py
    - backend/tests/test_analysis_correlate.py
    - backend/tests/test_sync_longevity.py

key-decisions:
  - "_iter_longevity_days now commits after each successful day's upsert (previously committed once at the end of the whole window) -- required for the per-day session.rollback() fix to isolate a failing day without discarding already-successful, still-uncommitted prior days in the same run"
  - "compute_trend's slope is left as a real finite 0.0 for a zero-variance series (Sxy=0/Sxx is mathematically well-defined and never NaN) -- only r_value/p_value (which ARE NaN for a constant y, since correlation is undefined) are guarded/degraded to None"

requirements-completed: [ANLZ-01, ANLZ-02, ANLZ-04]

# Metrics
duration: 68min
completed: 2026-07-08
---

# Phase 3 Plan 04: Gap Closure (CR-01a/b, WR-01/04/05) Summary

**Guarded NaN out of compute_trend/compute_correlation's JSON-RPC output and made longevity.py's malformed-value degradation, multi-device training_load lookup, and per-day backfill isolation match their documented contracts, each with a regression test that fails before the fix and passes after.**

## Performance

- **Duration:** 68 min
- **Started:** 2026-07-08T08:37:00+10:00 (approx, worktree base commit)
- **Completed:** 2026-07-08T08:53:23+10:00
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- `compute_trend`/`compute_correlation` can no longer emit a raw `NaN` token for a zero-variance input series (an ordinary flat metric, not an adversarial input) -- both are now proven `json.dumps(..., allow_nan=False)`-safe
- `fitness_age`/`training_load` in `longevity.py` now degrade to `None` on a malformed Garmin value instead of persisting an untyped value that crashes `get_trend` at read time
- `training_load`'s device loop now scans every device until it finds a real value instead of giving up after the first device
- A genuine DB-level `_upsert` failure for one day during `backfill_longevity`/`sync_longevity_window` is isolated: the session is rolled back and stays usable, and every other day in the same run still persists -- proven by a regression test that reproduces a real ORM-level `IntegrityError` (not a plain Python `raise`) and fails without the `session.rollback()` fix

## Task Commits

Each task was committed atomically:

1. **Task 1: NaN guards in compute_trend and compute_correlation (CR-01a, CR-01b)** - `c71493e` (fix)
2. **Task 2: longevity.py robustness fixes (WR-01, WR-04, WR-05)** - `ef320fd` (fix)

**Plan metadata:** (this SUMMARY commit, applied by the orchestrator after merge)

_Note: this is a gap-closure plan; both tasks are `type="auto" tdd="true"` and their test+implementation changes are combined into one commit per task rather than separate RED/GREEN commits, since the plan's own acceptance criteria specify a manual RED-check step (stash source, confirm new test fails, restore) rather than a formal TDD commit gate._

## Files Created/Modified
- `backend/app/analysis/trend.py` - `_finite_or_none` helper; `slope`/`r_value`/`p_value` wrapped before returning
- `backend/app/analysis/correlate.py` - `math.isfinite(rho)` short-circuit before the strength ladder, returning `undefined_constant_series`
- `backend/app/sync/longevity.py` - `_num_or_none` helper; `fitness_age`/`training_load` coerced; device loop keeps scanning until a non-`None` value; `_upsert` moved inside the per-day `try`, per-day `session.commit()` added, `session.rollback()` added to the `except` handler
- `backend/tests/test_analysis_trend.py` - regression test for the constant-series NaN guard
- `backend/tests/test_analysis_correlate.py` - regression test for the constant-series NaN guard
- `backend/tests/test_sync_longevity.py` - regression tests for both malformed-value degradation paths, multi-device fallthrough, and the rollback-gated real-DB-error test

## Decisions Made
- Committing per day inside `_iter_longevity_days` (rather than once at the end of the window) was required to make the WR-04 must-have truth actually hold: without it, `session.rollback()` in the except handler would discard every prior day's still-uncommitted upsert in the same run, not just the failing day's. This was discovered by writing the RED-check test with a genuine ORM-level `IntegrityError` (not a plain Python raise) and observing `count == 1` instead of `2` even with the naive fix applied -- see Deviations below.
- `compute_trend`'s `slope` for a constant series is real, finite `0.0` (verified against live scipy: `Sxy=0/Sxx` for a series with x-variance and zero y-variance) and is correctly left untouched by `_finite_or_none` -- only `r_value`/`p_value` (undefined correlation) are actually `NaN` and need guarding. The plan's `<behavior>` text describing "slope ... equal to None" for a constant series does not match real scipy output; the regression test asserts `slope == 0.0` instead.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_iter_longevity_days` needed a per-day commit, not just a per-day rollback, to satisfy WR-04's must-have truth**
- **Found during:** Task 2, while writing the RED-check for `test_backfill_longevity_rolls_back_and_persists_later_days_on_real_db_error`
- **Issue:** The plan's action text specified moving `_upsert` inside the per-day `try` and adding `session.rollback()` in the `except` handler, with `session.commit()` remaining once at the end of the loop (as in the pre-existing code and every sibling domain -- sleep.py, daily_health.py, body_composition.py all commit once at the end). With that shape, a `session.rollback()` triggered by day N's failure discards ALL uncommitted work from days 1..N-1 in the same run too, since nothing had been committed yet -- directly violating the must-have truth "every subsequent day in the same CLI backfill run still persists." Confirmed via a real ORM-level `IntegrityError` test (two ORM-tracked inserts for the same primary key in one flush): `count == 1` instead of `2` even with `session.rollback()` present, because the rollback also erased day 1's pending upsert.
- **Fix:** Added `session.commit()` immediately after each successful day's `_upsert` (before `count += 1`), so each day's row is durable before the loop moves to the next date. This makes the per-day `session.rollback()` in the except handler safe and correctly scoped to only the current failing day's uncommitted work. Removed the old single `session.commit()` after the loop (redundant once every successful day already commits itself).
- **Files modified:** `backend/app/sync/longevity.py`
- **Verification:** `test_backfill_longevity_rolls_back_and_persists_later_days_on_real_db_error` -- manually verified it fails (`count == 1`, `assert count == 2` fails) with `session.rollback()` removed, and passes (`count == 2`, day 1 and day 3 both queryable, day 2 absent) with the full fix (commit-per-day + rollback) in place. Full backend suite green (133 passed) with the fix.
- **Committed in:** `ef320fd` (Task 2 commit)

**2. [Rule 1 - Bug] Corrected `test_compute_trend_constant_series_returns_none_not_nan`'s `slope` assertion**
- **Found during:** Task 1, first test run
- **Issue:** The plan's `<behavior>` text stated slope/r_value/p_value should all be `None` for a constant series. Running the actual guarded code against real scipy showed `slope == 0.0` (finite, not NaN) for a series with x-variance and constant y -- only `r_value`/`p_value` are `NaN` (correlation undefined for zero-variance y). The written test initially asserted `result["slope"] is None`, which failed against the correct implementation.
- **Fix:** Changed the assertion to `result["slope"] == 0.0`, keeping the `r_value is None`/`p_value is None`/`json.dumps(allow_nan=False)` assertions unchanged.
- **Files modified:** `backend/tests/test_analysis_trend.py`
- **Verification:** `docker compose -f docker-compose.dev.yml run --rm backend pytest tests/test_analysis_trend.py tests/test_analysis_correlate.py tests/test_sync_longevity.py -x` -- all 24 tests pass.
- **Committed in:** `ef320fd` (bundled with Task 2's commit since it was discovered while verifying Task 2's test run; the underlying `trend.py`/`correlate.py` source from Task 1 was already correct and unchanged)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bug fixes)
**Impact on plan:** Both fixes were necessary to make the plan's own must-have truths and acceptance criteria actually hold against real scipy/SQLAlchemy behavior. No scope creep -- WR-02/WR-03 were untouched, no new files, no schema changes.

## Issues Encountered
- The dev Docker image (`docker-compose.dev.yml`) was stale and missing `numpy` (declared in `requirements.txt` but not present in the built image); rebuilt with `docker compose -f docker-compose.dev.yml build --no-cache backend` before any tests would import `app.analysis.trend`. Not a plan deviation -- a pre-existing environment staleness issue, resolved by rebuilding, no source changes needed.
- Early test runs were silently executed against the MAIN REPO's `backend/` directory instead of the worktree's `backend/` directory (both `docker compose` invocations must run with `cwd` inside the worktree, since `docker-compose.dev.yml` mounts `./backend:/app` relative to the invoking shell's `cwd`, and this agent's shell `cwd` resets between Bash calls). Caught by comparing `grep -c "_finite_or_none"` between the two paths (0 in main repo vs 4 in worktree) after a test run reported an implausible pass. All subsequent `docker compose` invocations explicitly `cd` into the worktree root first.
- `.planning/` is excluded by this machine's global `~/.gitignore_global`, so it is not tracked in this repository's git history at all -- it only exists as a plain filesystem directory in the main repo checkout, not inside this worktree's checkout. This SUMMARY.md was written directly into the worktree's `.planning/phases/03-analysis-engine/` path (created for this purpose) and force-added to this worktree's branch so the orchestrator can pick it up after merge; the equivalent file also needs to land at the main repo's `.planning/phases/03-analysis-engine/03-04-SUMMARY.md` path on disk since that is the actual location every other planning doc in this project lives at and is read from.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both BLOCKER-severity gaps (CR-01a/CR-01b) and all 3 WARNING-severity gaps (WR-01/WR-04/WR-05) from `03-VERIFICATION.md`/`03-REVIEW.md` are closed with a passing regression test each; must-have truths #1 and #2 from `03-VERIFICATION.md` should now verify as fully VERIFIED rather than PARTIAL.
- WR-02 (calendar-window semantics) and WR-03 (duplicate-date collapse) remain open and untouched, as scoped -- out of this plan's boundary.
- Full backend suite (133 tests) green; Phase 3 is ready for its next verification pass.

---
*Phase: 03-analysis-engine*
*Completed: 2026-07-08*

## Self-Check: PASSED

All 6 modified files and the 3 task/summary commit hashes (`c71493e`, `ef320fd`, `89722fa`) verified present on disk / in git log.
