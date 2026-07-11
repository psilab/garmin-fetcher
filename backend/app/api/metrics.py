"""REST façade over Phase 3's analysis engine (Plan 06-01, DASH-01).

- ``GET /api/metrics/{name}`` — a thin REST port of the MCP ``get_trend``
  tool: resolve ``name`` against the fixed ``METRICS`` registry, run the
  existing pure ``compute_trend`` over the metric's ``(date, value)`` series.
- ``GET /api/workouts/daily`` — a bespoke daily rollup over the event-grained
  ``workouts`` table (many rows/day), which does NOT fit compute_trend's
  one-row-per-day shape.

Security (T-06-01, Tampering/SQLi): ``name`` is whitelisted against
``METRICS.keys()`` (404 before DB) and ``range`` against the fixed
``RANGE_DAYS`` set (400 before DB). User input never reaches raw SQL — only
parameterized SQLAlchemy ``select()`` builders are used. Errors surface a
short, non-sensitive ``detail`` only (T-06-02).

``SessionLocal`` is imported at module scope so tests can monkeypatch it on
THIS module (``app.api.metrics``) to point at a seeded in-memory session.
"""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from ..analysis.registry import METRICS
from ..analysis.trend import compute_trend
from ..db import SessionLocal
from ..models import Workout

# Range switcher set (D-03: 30d / 90d / 1y / all). "all" maps to None (no
# lower-bound date filter). This fixed whitelist is the SQLi mitigation for
# the ``range`` param (T-06-01) — it is validated before any DB access.
RANGE_DAYS: dict[str, int | None] = {"30d": 30, "90d": 90, "1y": 365, "all": None}

router = APIRouter(prefix="/api/metrics")
workouts_router = APIRouter(prefix="/api/workouts")


def _validate_range(range_: str) -> int | None:
    """Return the day-count for a whitelisted range, raising 400 BEFORE any
    SessionLocal() is opened for an unknown range (T-06-01 input validation)."""
    if range_ not in RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"unknown range: {range_}")
    return RANGE_DAYS[range_]


def _resolve_metric(name: str):
    """Look up ``name`` in the fixed METRICS registry, raising 404 BEFORE any
    SessionLocal() is opened for an unknown metric (T-06-01; mirrors the MCP
    tool's _resolve_metric "raise before touching the DB" guard)."""
    spec = METRICS.get(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown metric: {name}")
    return spec


@router.get("/{name}")
def metric_series(name: str, range: str = Query(default="90d")):
    """Trend + rolling baseline + downsampled series for a registered metric.

    Thin REST port of the MCP ``get_trend`` tool — same registry lookup, same
    ``compute_trend`` call, plus a range-switcher lower-bound date filter.
    """
    # Validate BOTH inputs against fixed whitelists before opening a session
    # (T-06-01): bad range -> 400, unknown metric -> 404, neither touches the DB.
    days = _validate_range(range)
    spec = _resolve_metric(name)

    session = SessionLocal()
    try:
        col = getattr(spec.model, spec.column)
        date_col = getattr(spec.model, spec.date_col)
        stmt = select(date_col, col)
        if days is not None:
            stmt = stmt.where(date_col >= date.today() - timedelta(days=days))
        stmt = stmt.order_by(date_col.asc())
        rows = session.execute(stmt).all()
        return compute_trend(rows, window_days=spec.default_window_days)
    finally:
        session.close()


@workouts_router.get("/daily")
def workouts_daily(range: str = Query(default="90d")):
    """Per-day rollup over the event-grained ``workouts`` table.

    ``value`` is the daily workout COUNT (the primary charted series);
    duration/calories/HR feed the tooltip (D-01 "training load/workouts";
    RESEARCH Open Q3). ``func.date()`` truncates the ``DateTime`` start_time
    to a calendar day so late-night workouts bucket by their own day
    (RESEARCH Pitfall 2 / Assumption A3). ``day`` is an ISO ``YYYY-MM-DD``
    string, so the lower-bound filter compares against ``.isoformat()``.
    """
    days = _validate_range(range)

    session = SessionLocal()
    try:
        day = func.date(Workout.start_time)
        stmt = select(
            day.label("day"),
            func.count(Workout.activity_id),
            func.sum(Workout.duration_s),
            func.sum(Workout.calories),
            func.avg(Workout.average_hr),
        )
        if days is not None:
            stmt = stmt.where(day >= (date.today() - timedelta(days=days)).isoformat())
        stmt = stmt.group_by(day).order_by(day.asc())
        rows = session.execute(stmt).all()
        return {
            "series": [
                {
                    "date": r[0],
                    "value": r[1],
                    "duration_s": r[2],
                    "calories": r[3],
                    "average_hr": r[4],
                }
                for r in rows
            ]
        }
    finally:
        session.close()
