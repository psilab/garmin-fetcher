---
phase: 03-analysis-engine
plan: 01
subsystem: api
tags: [numpy, scipy, mcp, analysis, spearman, ols, mad-zscore]

# Dependency graph
requires:
  - phase: 02-domain-sync
    provides: Sleep/DailyHealth/BodyComposition typed columns (resting_hr, hrv_avg, sleep_score, stress_avg, total_steps, weight_g, body_fat_pct) backing the metric registry
provides:
  - Generic metric registry (backend/app/analysis/registry.py) mapping name -> (model, column) for the 7 pre-existing metrics
  - Pure numpy/scipy functions: compute_trend (OLS slope + robust deviation verdict), compute_correlation (lagged Spearman), detect_anomalies (median/MAD z-score), downsample (bounded series)
  - Three generic MCP tools: get_trend, get_correlations, detect_anomalies
affects: [03-02-longevity-markers, 03-03-longevity-mcp-tools]

# Tech tracking
tech-stack:
  added: [numpy==2.5.1, scipy==1.18.0]
  patterns:
    - "Pure analysis functions (backend/app/analysis/*.py) take already-fetched list[tuple[date, value|None]] rows and return plain dicts -- zero SQLAlchemy imports, callable by both MCP tools now and a future scheduler (D-04)"
    - "_resolve_metric(name) raises ValueError against a fixed METRICS dict lookup BEFORE SessionLocal() is opened -- mirrors the existing _validate_range 'raise before DB' shape (T-03-01)"
    - "downsample() bounds every series response to ~40 points by target point-count (not fixed stride), so short date ranges aren't gutted"

key-files:
  created:
    - backend/app/analysis/__init__.py
    - backend/app/analysis/registry.py
    - backend/app/analysis/trend.py
    - backend/app/analysis/correlate.py
    - backend/app/analysis/anomaly.py
    - backend/app/analysis/downsample.py
    - backend/tests/test_analysis_trend.py
    - backend/tests/test_analysis_correlate.py
    - backend/tests/test_analysis_anomaly.py
    - backend/tests/test_mcp_analysis_tools.py
  modified:
    - backend/requirements.txt
    - backend/app/mcp/server.py

key-decisions:
  - "Registry holds EXACTLY the 7 pre-existing typed-column metrics (resting_hr, hrv, sleep_score, stress, steps, weight, body_fat_pct); vo2max/training_load are deliberately excluded until Plan 03-02's LongevityMarker table lands"
  - "compute_trend additionally returns a robust deviation verdict (median/MAD z-score of the latest point vs. its preceding window) beyond the plan's minimum OLS slope/baseline ask, since the plan's <behavior> and RESEARCH.md both specify this shape"

patterns-established:
  - "Metric-agnostic MCP tool + registry lookup (D-02) -- no per-metric tool functions"
  - "Pure computation module convention for backend/app/analysis/*.py: no ORM/session import, first line always drops None values"

requirements-completed: [ANLZ-01, ANLZ-02, ANLZ-03]

# Metrics
duration: 45min
completed: 2026-07-07
---

# Phase 3 Plan 1: Analysis Engine Summary

**Generic trend/correlation/anomaly analysis engine (numpy/scipy) over the 7 existing health metrics, exposed as get_trend/get_correlations/detect_anomalies MCP tools.**

## Performance

- **Duration:** ~45 min
- **Tasks:** 2/2 completed
- **Files modified:** 12 (10 created, 2 modified)

## Accomplishments
- Metric registry (`METRICS` dict) generalizes all 7 pre-existing typed-column metrics (resting_hr, hrv, sleep_score, stress, steps, weight, body_fat_pct) behind a single lookup, no per-metric branching
- Pure `compute_trend`/`compute_correlation`/`detect_anomalies` functions (numpy + scipy, zero SQLAlchemy imports) deliver OLS trend + robust deviation verdict, lagged Spearman correlation, and median/MAD outlier detection
- Three generic MCP tools (`get_trend`, `get_correlations`, `detect_anomalies`) wrap the pure functions and reuse the existing `_validate_range`/`_apply_date_filters` helpers verbatim
- Unknown-metric names raise `ValueError` before any DB session is opened (T-03-01 mitigation), verified by a test that fails the test itself if `SessionLocal` is ever called
- Full backend test suite green: 110 passed (16 new tests: 9 pure-function unit tests + 7 MCP-tool integration tests)

## Task Commits

Each task was committed atomically (TDD RED -> GREEN per task):

1. **Task 1: Pure analysis engine (registry + trend + correlate + anomaly + downsample)**
   - `297230e` (test) - unit tests for compute_trend/compute_correlation/detect_anomalies
   - `435de66` (feat) - registry.py, trend.py, correlate.py, anomaly.py, downsample.py, numpy/scipy pins
2. **Task 2: get_trend / get_correlations / detect_anomalies MCP tools**
   - `98ba8d6` (test) - integration tests for the three new MCP tools
   - `fcdb0e9` (feat) - the three MCP tool definitions + `_resolve_metric` helper in `backend/app/mcp/server.py`

_Note: this worktree agent does not create a separate plan-metadata commit; SUMMARY.md/STATE.md/ROADMAP.md updates are owned by the orchestrator after merge. `.planning/` is untracked/gitignored in this repo (per the user's global gitignore), so this SUMMARY.md is not itself committed to git -- it is written to disk for the orchestrator to read._

## Files Created/Modified
- `backend/app/analysis/__init__.py` - empty package marker (mirrors `app/sync/__init__.py`)
- `backend/app/analysis/registry.py` - `MetricSpec` dataclass + `METRICS: dict[str, MetricSpec]` (exactly 7 entries)
- `backend/app/analysis/trend.py` - `compute_trend` (OLS slope via `scipy.stats.linregress` + median/MAD deviation verdict for the latest point)
- `backend/app/analysis/correlate.py` - `compute_correlation` (date-joined lagged `scipy.stats.spearmanr`)
- `backend/app/analysis/anomaly.py` - `detect_anomalies` (rolling median/MAD z-score loop)
- `backend/app/analysis/downsample.py` - `downsample` (point-count-targeted stride)
- `backend/app/mcp/server.py` - added `_resolve_metric` + `get_trend`/`get_correlations`/`detect_anomalies` tools
- `backend/requirements.txt` - added `numpy==2.5.1`, `scipy==1.18.0`
- `backend/tests/test_analysis_trend.py`, `test_analysis_correlate.py`, `test_analysis_anomaly.py` - pure-function unit tests
- `backend/tests/test_mcp_analysis_tools.py` - MCP tool integration tests

## Decisions Made
- Kept the registry to exactly the 7 columns already backed by real data, per the plan's explicit instruction not to add `vo2max`/`training_load` yet (no backing column exists until Plan 03-02).
- `compute_trend`'s deviation verdict uses the preceding `window_days`-sized slice (excluding the latest point itself) for the median/MAD baseline, exactly as specified in the plan's `<action>` block.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed a self-authored test bug: constant baseline gave MAD=0, so the "notable deviation" case never got exercised**
- **Found during:** Task 1, first test run
- **Issue:** `test_compute_trend_flags_notable_deviation_on_latest_point` seeded 30 identical baseline values (`50.0`), so `mad == 0` and `compute_trend` correctly returned `deviation: None` per its own "MAD == 0 -> no verdict" guard -- the test's synthetic data, not `compute_trend`, was wrong.
- **Fix:** Added `(i % 2)` noise to the synthetic baseline so `mad != 0`, letting the outlier actually get compared against a real robust baseline.
- **Files modified:** `backend/tests/test_analysis_trend.py`
- **Verification:** Full pure-function suite passes (9/9).
- **Committed in:** `297230e` (Task 1 test commit)

**2. [Rule 1 - Bug] Fixed a test using a detached SQLAlchemy instance attribute after commit**
- **Found during:** Task 2, first test run
- **Issue:** `test_detect_anomalies_flags_planted_outlier_day` accessed `days[35].date` after `db_session.commit()` expired the instance, raising `DetachedInstanceError` on attribute access outside the session.
- **Fix:** Captured `outlier_date_iso = days[35].date.isoformat()` before `commit()`.
- **Files modified:** `backend/tests/test_mcp_analysis_tools.py`
- **Verification:** `test_mcp_analysis_tools.py` passes (7/7); full suite passes (110/110).
- **Committed in:** `98ba8d6` (Task 2 test commit)

**3. [Rule 2 - Missing critical] Rephrased analysis-module docstrings to avoid the literal string "sqlalchemy"**
- **Found during:** Task 1, acceptance-criteria check
- **Issue:** The plan's acceptance criteria requires `grep -c 'sqlalchemy'` to report 0 matches in `trend.py`/`correlate.py`/`anomaly.py`/`downsample.py`. My first draft's docstrings said "No sqlalchemy import anywhere in this file", which is itself a grep match even though it's a comment, not an import.
- **Fix:** Reworded to "No ORM/DB-layer import anywhere in this file" -- same intent, satisfies the literal grep gate.
- **Files modified:** `backend/app/analysis/trend.py`, `correlate.py`, `anomaly.py`
- **Verification:** `grep -c 'sqlalchemy' backend/app/analysis/{trend,correlate,anomaly,downsample}.py` reports 0 in all four files.
- **Committed in:** `435de66` (Task 1 feat commit)

---

**Total deviations:** 3 auto-fixed (2 test bugs, 1 acceptance-criteria wording fix)
**Impact on plan:** All three were self-inflicted test/wording issues caught and fixed before the task commit; no scope creep, no change to the delivered analysis logic.

## Issues Encountered
- `docker compose run` against the default `docker-compose.yml` failed with `network web declared as external, but could not be found` (that file targets the deployed Traefik environment). Used `docker compose -f docker-compose.dev.yml run --rm backend pytest ...` instead (the project's local-dev compose file, which builds the image locally with no external network dependency) plus `MCP_TOKEN=test-token` on the host env for the `:?` env-var guard. This is a local-environment workaround, not a code change.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `backend/app/analysis/registry.py`'s `METRICS` dict and the pure `compute_trend`/`compute_correlation`/`detect_anomalies` functions are ready for Plan 03-03 to extend with `vo2max`/`training_load` entries once Plan 03-02's `LongevityMarker` table lands.
- Full backend test suite green (110 passed) at hand-off.

---
*Phase: 03-analysis-engine*
*Completed: 2026-07-07*

## Self-Check: PASSED

All 10 created source/test files verified present on disk; all 5 commit
hashes (297230e, 435de66, 98ba8d6, fcdb0e9, 5a4f540) verified present in
git log.
