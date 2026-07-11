"""REST façade over Phase 3's analysis engine (Plan 06-01, DASH-01).

``GET /api/metrics/{name}`` — a thin REST port of the MCP ``get_trend``
tool: resolve ``name`` against the fixed ``METRICS`` registry, run the
existing pure ``compute_trend`` over the metric's ``(date, value)`` series.
(Plan 06-01 Task 2 adds a second, bespoke ``/api/workouts/daily`` rollup to
this module.)

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
from sqlalchemy import select

from ..analysis.registry import METRICS
from ..analysis.trend import compute_trend
from ..db import SessionLocal

# Range switcher set (D-03: 30d / 90d / 1y / all). "all" maps to None (no
# lower-bound date filter). This fixed whitelist is the SQLi mitigation for
# the ``range`` param (T-06-01) — it is validated before any DB access.
RANGE_DAYS: dict[str, int | None] = {"30d": 30, "90d": 90, "1y": 365, "all": None}

router = APIRouter(prefix="/api/metrics")


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
