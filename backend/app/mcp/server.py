"""FastMCP server exposing the D-04 coach read tools over the workouts table.

Mounted by ``app/main.py`` (Plan 04) at ``/mcp``:

    app = FastAPI(lifespan=mcp_app.lifespan)
    app.mount("/mcp", mcp_app)

``mcp_app`` bundles the hand-rolled ``BearerAuthMiddleware`` (SEC-02) so every
request to the mount is bearer-checked before it ever reaches a tool.
"""

from datetime import date, datetime, time, timedelta

from fastmcp import FastMCP
from sqlalchemy import func, select
from starlette.middleware import Middleware

from ..db import SessionLocal
from ..models import Sleep, Workout
from .auth import BearerAuthMiddleware

mcp = FastMCP("Garmin Coach")

# Columns returned to the coach -- excludes `raw` to keep payloads small
# (the coach doesn't need the raw Garmin JSON, per the plan's action notes).
_SUMMARY_COLUMNS = (
    "activity_id",
    "activity_type",
    "start_time",
    "distance_m",
    "duration_s",
    "average_hr",
    "calories",
    "synced_at",
)


def _to_dict(workout: Workout) -> dict:
    return {col: getattr(workout, col) for col in _SUMMARY_COLUMNS}


def _validate_range(start: date | None, end: date | None) -> None:
    if start and end and start > end:
        raise ValueError("start must be <= end")


def _apply_filters(stmt, activity_type: str | None, start: date | None, end: date | None):
    """Parameterized filters only -- never string-format user input into SQL
    (T-03-04, SQL injection mitigation)."""
    _validate_range(start, end)
    if activity_type is not None:
        stmt = stmt.where(Workout.activity_type == activity_type)
    if start is not None:
        stmt = stmt.where(Workout.start_time >= datetime.combine(start, time.min))
    if end is not None:
        stmt = stmt.where(
            Workout.start_time < datetime.combine(end, time.min) + timedelta(days=1)
        )
    return stmt


def _aggregate(session, activity_type: str | None, start: date | None, end: date | None) -> dict:
    stmt = select(
        func.count(Workout.activity_id),
        func.sum(Workout.distance_m),
        func.sum(Workout.duration_s),
        func.sum(Workout.calories),
        func.avg(Workout.average_hr),
    )
    stmt = _apply_filters(stmt, activity_type, start, end)
    count, total_distance_m, total_duration_s, total_calories, avg_hr = session.execute(
        stmt
    ).one()
    return {
        "count": count or 0,
        "total_distance_m": total_distance_m,
        "total_duration_s": total_duration_s,
        "total_calories": total_calories,
        "avg_hr": avg_hr,
    }


@mcp.tool
def list_recent_workouts(limit: int = 10) -> list[dict]:
    """Most recent workouts, newest first."""
    session = SessionLocal()
    try:
        stmt = select(Workout).order_by(Workout.start_time.desc()).limit(limit)
        return [_to_dict(w) for w in session.execute(stmt).scalars().all()]
    finally:
        session.close()


@mcp.tool
def filter_workouts(
    activity_type: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    """Workouts filtered by type and/or date range."""
    session = SessionLocal()
    try:
        stmt = _apply_filters(select(Workout), activity_type, start, end)
        stmt = stmt.order_by(Workout.start_time.desc())
        return [_to_dict(w) for w in session.execute(stmt).scalars().all()]
    finally:
        session.close()


@mcp.tool
def aggregate_workouts(
    activity_type: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """Totals (count, distance, duration, calories) for a filtered set."""
    session = SessionLocal()
    try:
        return _aggregate(session, activity_type, start, end)
    finally:
        session.close()


@mcp.tool
def compare_periods(
    period_a_start: date,
    period_a_end: date,
    period_b_start: date,
    period_b_end: date,
    activity_type: str | None = None,
) -> dict:
    """Plain count/sum comparison between two date ranges (no trend analysis)."""
    session = SessionLocal()
    try:
        return {
            "period_a": _aggregate(session, activity_type, period_a_start, period_a_end),
            "period_b": _aggregate(session, activity_type, period_b_start, period_b_end),
        }
    finally:
        session.close()


# --- Sleep tools (D-07 -- list/filter/aggregate, mirroring the workout trio) ---

# Excludes `raw` -- the coach doesn't need the raw Garmin sleep JSON, and
# `raw` may carry PII/intraday detail (T-02-06 mitigation).
_SLEEP_SUMMARY_COLUMNS = (
    "date",
    "sleep_score",
    "deep_s",
    "light_s",
    "rem_s",
    "awake_s",
    "hrv_avg",
    "body_battery_high",
    "body_battery_low",
    "training_readiness",
    "training_status",
    "synced_at",
)


def _sleep_to_dict(sleep: Sleep) -> dict:
    return {col: getattr(sleep, col) for col in _SLEEP_SUMMARY_COLUMNS}


def _apply_date_filters(stmt, col, start: date | None, end: date | None):
    """Parameterized date-range filter only -- never string-format user
    input into SQL (T-02-04, generalized from Workout's ``_apply_filters``)."""
    _validate_range(start, end)
    if start is not None:
        stmt = stmt.where(col >= start)
    if end is not None:
        stmt = stmt.where(col <= end)
    return stmt


@mcp.tool
def list_recent_sleep(limit: int = 10) -> list[dict]:
    """Most recent nights of sleep/recovery data, newest first."""
    session = SessionLocal()
    try:
        stmt = select(Sleep).order_by(Sleep.date.desc()).limit(limit)
        return [_sleep_to_dict(s) for s in session.execute(stmt).scalars().all()]
    finally:
        session.close()


@mcp.tool
def filter_sleep(start: date | None = None, end: date | None = None) -> list[dict]:
    """Sleep/recovery rows within an inclusive date range."""
    session = SessionLocal()
    try:
        stmt = _apply_date_filters(select(Sleep), Sleep.date, start, end)
        stmt = stmt.order_by(Sleep.date.desc())
        return [_sleep_to_dict(s) for s in session.execute(stmt).scalars().all()]
    finally:
        session.close()


@mcp.tool
def aggregate_sleep(start: date | None = None, end: date | None = None) -> dict:
    """Count + averages (sleep score, HRV, body battery, training
    readiness) over a filtered set of nights."""
    session = SessionLocal()
    try:
        stmt = select(
            func.count(Sleep.date),
            func.avg(Sleep.sleep_score),
            func.avg(Sleep.hrv_avg),
            func.avg(Sleep.body_battery_high),
            func.avg(Sleep.body_battery_low),
            func.avg(Sleep.training_readiness),
        )
        stmt = _apply_date_filters(stmt, Sleep.date, start, end)
        (
            count,
            avg_sleep_score,
            avg_hrv,
            avg_body_battery_high,
            avg_body_battery_low,
            avg_training_readiness,
        ) = session.execute(stmt).one()
        return {
            "count": count or 0,
            "avg_sleep_score": avg_sleep_score,
            "avg_hrv": avg_hrv,
            "avg_body_battery_high": avg_body_battery_high,
            "avg_body_battery_low": avg_body_battery_low,
            "avg_training_readiness": avg_training_readiness,
        }
    finally:
        session.close()


# path="/" because the whole sub-app is mounted at /mcp by the parent app.
# Middleware scoped only to this sub-app — never attached to the parent
# FastAPI app, so REST routes remain unauthenticated in Phase 1.
mcp_app = mcp.http_app(path="/", middleware=[Middleware(BearerAuthMiddleware)])
