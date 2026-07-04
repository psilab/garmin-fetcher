"""ORM models for the Garmin Fetcher SQLite store."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
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
