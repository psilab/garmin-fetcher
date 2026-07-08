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


class LongevityMarker(Base):
    """A single day's longevity markers (VO2max, fitness age, training load).

    Keyed on the calendar ``date`` so repeated syncs upsert idempotently.
    D-05/D-01 correction: unlike Sleep/DailyHealth/BodyComposition (typed
    columns sourced from ``raw`` payloads already being fetched elsewhere),
    these columns are populated by a NEW Garmin sync
    (``app/sync/longevity.py`` calling ``get_max_metrics``/
    ``get_training_status``), never backfilled from any existing ``raw``
    payload. Full raw JSON payload is kept (DATA-07).
    """

    __tablename__ = "longevity_markers"

    date: Mapped[date_] = mapped_column(Date, primary_key=True)
    vo2max: Mapped[float | None] = mapped_column(Float, nullable=True)
    fitness_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    training_load: Mapped[float | None] = mapped_column(Float, nullable=True)
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


class JournalEntry(Base):
    """A free-text subjective journal entry (D-01).

    Unlike every other table in this module, this data originates in-app
    (typed by the user or written by an MCP tool), not from a Garmin sync --
    so there is deliberately NO ``raw`` column and no structured mood/severity
    enum, only a free-text ``body`` plus optional ``tags``.

    ``id`` is the FIRST autoincrement surrogate PK in this codebase (every
    prior table keys on a Garmin natural key or ``date``). It MUST stay a
    single-column ``INTEGER PRIMARY KEY`` -- SQLite's true ``rowid`` alias --
    because the ``journal_fts`` external-content FTS5 table (migration 0004)
    is wired via ``content_rowid='id'`` and depends on ``id`` always equalling
    the underlying SQLite rowid (RESEARCH.md Pitfall 3).

    ``occurred_at`` (start) plus optional ``end_date`` (D-02) let an entry
    represent either a point in time or an open-ended span so the coach can
    correlate it against other domains by date.
    """

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[date_] = mapped_column(Date, nullable=False)
    end_date: Mapped[date_ | None] = mapped_column(Date, nullable=True)
    tags: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class Goal(Base):
    """A user-set longevity/fitness goal (COACH-06), managed by the coach.

    Unlike `JournalEntry` (append-only, never mutated after creation), `Goal`
    is mutable structured state -- `update_goal` patches fields on an
    existing row in place. There is no `goals_fts` table, so no FTS5
    rowid-equality constraint applies to `id` the way it does for
    `JournalEntry` (RESEARCH.md Pitfall 3 does not apply here).
    """

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    target_metric: Mapped[str | None] = mapped_column(String, nullable=True)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
