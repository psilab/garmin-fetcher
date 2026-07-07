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

from ..analysis.anomaly import detect_anomalies as _detect_anomalies
from ..analysis.correlate import compute_correlation
from ..analysis.registry import METRICS
from ..analysis.trend import compute_trend
from ..db import SessionLocal
from ..models import BodyComposition, DailyHealth, Sleep, Workout
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


# --- Daily-health tools (DATA-03 -- list/filter/aggregate, mirroring the
# sleep trio) ---

# Excludes `raw` -- the coach doesn't need the raw Garmin get_stats/spo2/
# respiration JSON (T-02-09 mitigation).
_DAILY_HEALTH_SUMMARY_COLUMNS = (
    "date",
    "total_steps",
    "resting_hr",
    "stress_avg",
    "spo2_avg",
    "respiration_avg",
    "intensity_minutes_moderate",
    "intensity_minutes_vigorous",
    "synced_at",
)


def _daily_health_to_dict(daily_health: DailyHealth) -> dict:
    return {col: getattr(daily_health, col) for col in _DAILY_HEALTH_SUMMARY_COLUMNS}


@mcp.tool
def list_recent_daily_health(limit: int = 10) -> list[dict]:
    """Most recent days of all-day health data, newest first."""
    session = SessionLocal()
    try:
        stmt = select(DailyHealth).order_by(DailyHealth.date.desc()).limit(limit)
        return [_daily_health_to_dict(d) for d in session.execute(stmt).scalars().all()]
    finally:
        session.close()


@mcp.tool
def filter_daily_health(start: date | None = None, end: date | None = None) -> list[dict]:
    """All-day health rows within an inclusive date range."""
    session = SessionLocal()
    try:
        stmt = _apply_date_filters(select(DailyHealth), DailyHealth.date, start, end)
        stmt = stmt.order_by(DailyHealth.date.desc())
        return [_daily_health_to_dict(d) for d in session.execute(stmt).scalars().all()]
    finally:
        session.close()


@mcp.tool
def aggregate_daily_health(start: date | None = None, end: date | None = None) -> dict:
    """Count + averages (steps, resting HR, stress, SpO2, respiration,
    intensity minutes) over a filtered set of days."""
    session = SessionLocal()
    try:
        stmt = select(
            func.count(DailyHealth.date),
            func.avg(DailyHealth.total_steps),
            func.avg(DailyHealth.resting_hr),
            func.avg(DailyHealth.stress_avg),
            func.avg(DailyHealth.spo2_avg),
            func.avg(DailyHealth.respiration_avg),
            func.avg(DailyHealth.intensity_minutes_moderate),
            func.avg(DailyHealth.intensity_minutes_vigorous),
        )
        stmt = _apply_date_filters(stmt, DailyHealth.date, start, end)
        (
            count,
            avg_total_steps,
            avg_resting_hr,
            avg_stress_avg,
            avg_spo2_avg,
            avg_respiration_avg,
            avg_intensity_minutes_moderate,
            avg_intensity_minutes_vigorous,
        ) = session.execute(stmt).one()
        return {
            "count": count or 0,
            "avg_total_steps": avg_total_steps,
            "avg_resting_hr": avg_resting_hr,
            "avg_stress_avg": avg_stress_avg,
            "avg_spo2_avg": avg_spo2_avg,
            "avg_respiration_avg": avg_respiration_avg,
            "avg_intensity_minutes_moderate": avg_intensity_minutes_moderate,
            "avg_intensity_minutes_vigorous": avg_intensity_minutes_vigorous,
        }
    finally:
        session.close()


# --- Body-composition tools (DATA-04 -- list/filter/aggregate, mirroring
# the daily-health trio). Event-grained (keyed on sample_pk, not date), but
# reads are still filtered/ordered on the non-PK `date` column like every
# other domain's MCP tools. ---

# Excludes `raw` -- the coach doesn't need the raw Garmin weigh-in JSON
# (T-02-12 mitigation).
_BODY_COMP_SUMMARY_COLUMNS = (
    "sample_pk",
    "date",
    "weight_g",
    "body_fat_pct",
    "synced_at",
)


def _body_comp_to_dict(body_comp: BodyComposition) -> dict:
    return {col: getattr(body_comp, col) for col in _BODY_COMP_SUMMARY_COLUMNS}


@mcp.tool
def list_recent_body_composition(limit: int = 10) -> list[dict]:
    """Most recent weigh-in events, newest first."""
    session = SessionLocal()
    try:
        stmt = select(BodyComposition).order_by(BodyComposition.date.desc()).limit(limit)
        return [_body_comp_to_dict(b) for b in session.execute(stmt).scalars().all()]
    finally:
        session.close()


@mcp.tool
def filter_body_composition(start: date | None = None, end: date | None = None) -> list[dict]:
    """Weigh-in events within an inclusive date range."""
    session = SessionLocal()
    try:
        stmt = _apply_date_filters(select(BodyComposition), BodyComposition.date, start, end)
        stmt = stmt.order_by(BodyComposition.date.desc())
        return [_body_comp_to_dict(b) for b in session.execute(stmt).scalars().all()]
    finally:
        session.close()


@mcp.tool
def aggregate_body_composition(start: date | None = None, end: date | None = None) -> dict:
    """Count + averages (weight, body fat %) over a filtered set of
    weigh-in events."""
    session = SessionLocal()
    try:
        stmt = select(
            func.count(BodyComposition.sample_pk),
            func.avg(BodyComposition.weight_g),
            func.avg(BodyComposition.body_fat_pct),
        )
        stmt = _apply_date_filters(stmt, BodyComposition.date, start, end)
        count, avg_weight_g, avg_body_fat_pct = session.execute(stmt).one()
        return {
            "count": count or 0,
            "avg_weight_g": avg_weight_g,
            "avg_body_fat_pct": avg_body_fat_pct,
        }
    finally:
        session.close()


# --- Analysis tools (D-02/D-04 -- generic, metric-agnostic; ANLZ-01/02/03).
# Reuse the Task 1 pure functions + the registry's "raise before touching
# the DB" gate (T-03-01 mitigation). ---


def _resolve_metric(name: str):
    """Look up ``name`` in the fixed METRICS registry, raising ValueError
    on any unknown name BEFORE SessionLocal() is opened (V5 input
    validation, mirrors _validate_range's "raise before DB" shape)."""
    spec = METRICS.get(name)
    if spec is None:
        raise ValueError(f"unknown metric: {name!r}")
    return spec


@mcp.tool
def get_trend(metric: str, start: date | None = None, end: date | None = None) -> dict:
    """Trend + rolling baseline + robust deviation verdict for a registered
    metric over a date range."""
    spec = _resolve_metric(metric)
    session = SessionLocal()
    try:
        col = getattr(spec.model, spec.column)
        date_col = getattr(spec.model, spec.date_col)
        stmt = select(date_col, col)
        stmt = _apply_date_filters(stmt, date_col, start, end)
        stmt = stmt.order_by(date_col.asc())
        rows = session.execute(stmt).all()
        return compute_trend(rows, window_days=spec.default_window_days)
    finally:
        session.close()


@mcp.tool
def get_correlations(
    metrics: list[str],
    start: date | None = None,
    end: date | None = None,
    lag_days: int = 0,
) -> dict:
    """Lagged Spearman correlation between exactly two registered metrics."""
    if len(metrics) != 2:
        raise ValueError("get_correlations requires exactly two metric names")
    spec_a = _resolve_metric(metrics[0])
    spec_b = _resolve_metric(metrics[1])
    session = SessionLocal()
    try:
        col_a = getattr(spec_a.model, spec_a.column)
        date_col_a = getattr(spec_a.model, spec_a.date_col)
        stmt_a = select(date_col_a, col_a)
        stmt_a = _apply_date_filters(stmt_a, date_col_a, start, end)
        stmt_a = stmt_a.order_by(date_col_a.asc())
        rows_a = session.execute(stmt_a).all()

        col_b = getattr(spec_b.model, spec_b.column)
        date_col_b = getattr(spec_b.model, spec_b.date_col)
        stmt_b = select(date_col_b, col_b)
        stmt_b = _apply_date_filters(stmt_b, date_col_b, start, end)
        stmt_b = stmt_b.order_by(date_col_b.asc())
        rows_b = session.execute(stmt_b).all()

        result = compute_correlation(rows_a, rows_b, lag_days=lag_days)
        result.update({"metric_a": metrics[0], "metric_b": metrics[1]})
        return result
    finally:
        session.close()


@mcp.tool
def detect_anomalies(
    metric: str,
    start: date | None = None,
    end: date | None = None,
    window_days: int | None = None,
    z_threshold: float = 2.5,
) -> list[dict]:
    """Dates in a registered metric's history that are notable outliers
    vs its rolling median/MAD baseline."""
    spec = _resolve_metric(metric)
    session = SessionLocal()
    try:
        col = getattr(spec.model, spec.column)
        date_col = getattr(spec.model, spec.date_col)
        stmt = select(date_col, col)
        stmt = _apply_date_filters(stmt, date_col, start, end)
        stmt = stmt.order_by(date_col.asc())
        rows = session.execute(stmt).all()
        return _detect_anomalies(
            rows,
            window_days=window_days or spec.default_window_days,
            z_threshold=z_threshold,
        )
    finally:
        session.close()


# path="/" because the whole sub-app is mounted at /mcp by the parent app.
# Middleware scoped only to this sub-app — never attached to the parent
# FastAPI app, so REST routes remain unauthenticated in Phase 1.
mcp_app = mcp.http_app(path="/", middleware=[Middleware(BearerAuthMiddleware)])
