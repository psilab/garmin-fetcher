---
phase: 03-analysis-engine
plan: 03
subsystem: api
tags: [mcp, analysis, cli, longevity]

# Dependency graph
requires:
  - phase: 03-analysis-engine (Plan 03-01)
    provides: Generic metric registry (METRICS/MetricSpec), compute_trend, get_trend/get_correlations/detect_anomalies MCP tools
  - phase: 03-analysis-engine (Plan 03-02)
    provides: LongevityMarker model/table, backfill_longevity/sync_longevity_window, longevity as 4th scheduler domain
provides:
  - backfill-longevity CLI subcommand (manual, one-off historical backfill; also folded into backfill-all)
  - vo2max (180-day window) and training_load (30-day default) registered in the generic METRICS registry
  - get_longevity_markers MCP tool returning the fixed D-06 five-marker trajectory set
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "get_longevity_markers takes no metric argument -- every marker name comes from a hardcoded _LONGEVITY_MARKERS tuple resolved through the same _resolve_metric/METRICS registry as get_trend, eliminating any injection surface (T-03-07)"

key-files:
  created: []
  modified:
    - backend/app/sync/__main__.py
    - backend/app/analysis/registry.py
    - backend/app/mcp/server.py
    - backend/tests/test_mcp_analysis_tools.py

key-decisions:
  - "training_load is registered as a generic metric (get_trend/get_correlations/detect_anomalies) but deliberately excluded from get_longevity_markers's fixed 5-key D-06 marker set"
  - "vo2max uses a 180-day default_window_days (longer-arc trajectory per D-06/RESEARCH.md Pattern 1); training_load keeps the standard 30-day default"

patterns-established: []

requirements-completed: [ANLZ-04]

# Metrics
duration: 20min
completed: 2026-07-07
---

# Phase 03 Plan 03: Longevity MCP Tool Exposure Summary

**Registered vo2max/training_load in the generic metric registry, added a manually-invocable `backfill-longevity` CLI subcommand, and added the `get_longevity_markers` MCP tool returning the fixed D-06 five-marker (VO2max/HRV/resting-HR/weight/body-fat%) trajectory set by reusing `compute_trend` -- completing ANLZ-04 end-to-end.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 2/2 completed
- **Files modified:** 4 (0 created, 4 modified)

## Accomplishments

- `backend/app/sync/__main__.py`: new `backfill-longevity` subcommand mirrors the existing `backfill-daily-health` try/finally shape exactly; also folded into `backfill-all` so a fresh-install bootstrap covers all four domains in one command
- `backend/app/analysis/registry.py`: `vo2max` (180-day window, per D-06's longer-arc trajectory guidance) and `training_load` (standard 30-day window) now registered against `LongevityMarker`, usable by `get_trend`/`get_correlations`/`detect_anomalies` with zero per-metric branching
- `backend/app/mcp/server.py`: new `get_longevity_markers()` MCP tool returns exactly the D-06 five-marker set (`vo2max`, `hrv`, `resting_hr`, `weight`, `body_fat_pct`) under a `"markers"` dict, reusing `compute_trend` per marker; `training_load` is deliberately excluded (registered elsewhere as a first-class metric, not a D-06 longevity marker)
- No special-casing needed for VO2max before its historical backfill has run -- `compute_trend`'s existing `<2` clean-points branch already returns `{"direction": "insufficient_data", ...}`
- Full backend test suite green: 126 passed (9 tests in `test_mcp_analysis_tools.py`, 2 new for `get_longevity_markers`)

## Task Commits

Each task was committed atomically (TDD RED -> GREEN for Task 2):

1. **Task 1: backfill-longevity CLI subcommand + registry entries for vo2max/training_load**
   - `b853eae` (feat) - `backend/app/sync/__main__.py` subcommand + `backend/app/analysis/registry.py` two new `METRICS` entries
2. **Task 2: get_longevity_markers MCP tool (D-06 fixed marker set)**
   - `987a6f6` (test, RED) - failing tests for the 5-key marker set + insufficient-data degrade path
   - `ac4a941` (feat, GREEN) - `get_longevity_markers` tool + `_LONGEVITY_MARKERS` constant in `backend/app/mcp/server.py`

## Files Created/Modified

- `backend/app/sync/__main__.py` - `backfill-longevity` subcommand; `backfill_longevity` import; folded into `backfill-all`
- `backend/app/analysis/registry.py` - `LongevityMarker` import; `vo2max`/`training_load` `METRICS` entries with D-05/D-01 correction comment
- `backend/app/mcp/server.py` - `_LONGEVITY_MARKERS` constant + `get_longevity_markers` MCP tool
- `backend/tests/test_mcp_analysis_tools.py` - `_make_body_comp`/`_make_longevity_marker` seed helpers; two new tests (exact 5-key set + training_load exclusion; VO2max-empty range degrades to insufficient_data)

## Decisions Made

- `training_load` is a registered generic metric but is NOT one of the 5 keys `get_longevity_markers` returns, per the plan's explicit D-06 marker-set boundary.
- `vo2max`'s 180-day default window differs from every other registered metric's 30-day default, matching the plan's explicit instruction (D-06/RESEARCH.md Pattern 1's longer-arc trajectory guidance).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test fixture used a string `sample_pk` against an Integer primary-key column**
- **Found during:** Task 2, first test run
- **Issue:** `_make_body_comp`'s first draft set `sample_pk=f"pk-{day.isoformat()}"`, but `BodyComposition.sample_pk` is declared `Mapped[int]` (`Integer`, primary key) in `backend/app/models.py`. SQLite raised `IntegrityError: datatype mismatch` on insert.
- **Fix:** Changed the test helper to derive a numeric `sample_pk` from the date (`int(day.strftime("%Y%m%d"))`), matching the column's real type.
- **Files modified:** `backend/tests/test_mcp_analysis_tools.py`
- **Verification:** `docker compose run --rm backend pytest tests/test_mcp_analysis_tools.py -x` passes (9/9); full suite passes (126/126).
- **Committed in:** `ac4a941` (Task 2 feat/GREEN commit)

---

**Total deviations:** 1 auto-fixed (test fixture type bug)
**Impact on plan:** Self-inflicted test-fixture issue caught and fixed before the task commit; no scope creep, no change to the delivered `get_longevity_markers` logic.

## Issues Encountered

None beyond the deviation documented above. Used `docker compose -f docker-compose.dev.yml run --rm backend ...` (with `MCP_TOKEN=test-token` on the host env) for all verification, consistent with Plan 03-01/03-02's documented local-dev workaround (the default `docker-compose.yml` targets the deployed Traefik environment and fails locally with a missing external `web` network).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ANLZ-04 is fully delivered end-to-end: VO2max/training_load are registered metrics, backfillable via `python -m app.sync backfill-longevity` (never auto-run by Alembic), and exposed through both the generic tools (`get_trend`/`get_correlations`/`detect_anomalies`) and the dedicated `get_longevity_markers` tool returning the exact D-06 five-marker set.
- Full backend test suite green (126 passed) at hand-off.
- Phase 03 (analysis-engine) is now complete across all 3 plans (03-01 generic analysis engine, 03-02 longevity marker sync, 03-03 this plan's tool exposure).

---
*Phase: 03-analysis-engine*
*Completed: 2026-07-07*

## Self-Check: PASSED

- FOUND: backend/app/sync/__main__.py (backfill-longevity subcommand)
- FOUND: backend/app/analysis/registry.py (vo2max/training_load entries)
- FOUND: backend/app/mcp/server.py (get_longevity_markers)
- FOUND: backend/tests/test_mcp_analysis_tools.py (new tests)
- Commit b853eae: FOUND
- Commit 987a6f6: FOUND
- Commit ac4a941: FOUND
