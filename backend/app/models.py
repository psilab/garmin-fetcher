"""ORM models for the Garmin Fetcher SQLite store."""

from datetime import date as date_, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Workout(Base):
    """A single synced Garmin activity.

    Keyed on Garmin's own ``activity_id`` (not an autoincrement surrogate)
    so repeated syncs can upsert idempotently. Typed summary columns are
    kept alongside the full raw JSON payload (DATA-07) so nothing is lost
    even if the typed-column mapping is imperfect or incomplete.
    """

    __tablename__ = "workouts"

    activity_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    activity_type: Mapped[str] = mapped_column(String, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calories: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class Sleep(Base):
    """A single day's sleep / recovery summary.

    Keyed on the calendar ``date`` so repeated syncs upsert idempotently.
    Typed columns mirror confirmed live get_sleep_data / get_training_* keys;
    the full raw JSON payload is kept (DATA-07) so nothing is lost.

    Body-battery high/low have no clean scalar in get_sleep_data/get_body_battery
    (see 02-01-SUMMARY) — Plan 02-02 chooses the source; the columns stay Integer.
    """

    __tablename__ = "sleep"

    date: Mapped[date_] = mapped_column(Date, primary_key=True)
    sleep_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deep_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    light_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    rem_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    awake_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_battery_high: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_low: Mapped[int | None] = mapped_column(Integer, nullable=True)
    training_readiness: Mapped[int | None] = mapped_column(Integer, nullable=True)
    training_status: Mapped[str | None] = mapped_column(String, nullable=True)
    raw: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class DailyHealth(Base):
    """A single day's all-day health summary (from get_stats).

    Keyed on the calendar ``date``. Typed columns mirror confirmed get_stats
    keys; the full raw JSON payload is kept (DATA-07).
    """

    __tablename__ = "daily_health"

    date: Mapped[date_] = mapped_column(Date, primary_key=True)
    total_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resting_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stress_avg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spo2_avg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    respiration_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    intensity_minutes_moderate: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    intensity_minutes_vigorous: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    raw: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class BodyComposition(Base):
    """A single weigh-in event (body composition).

    Keyed on Garmin's stable per-event ``sample_pk`` (confirmed ``samplePk`` in
    the live get_weigh_ins payload) so repeated syncs upsert idempotently. The
    calendar ``date`` is a NON-PK NOT-NULL column used by the catch-up window
    (Plan 05) and MCP filters. Full raw JSON payload is kept (DATA-07).
    """

    __tablename__ = "body_composition"

    sample_pk: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date_] = mapped_column(Date, nullable=False)
    weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
