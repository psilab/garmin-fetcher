"""SQLAlchemy 2.0 engine/session setup.

- Reads ``DATABASE_URL`` (defaults to a file-based SQLite DB under
  ``/app/data/garmin.db``, matching the dev bind mount).
- For file-based SQLite URLs, ensures the parent directory exists before
  ``create_engine()`` is ever called — SQLite does not create missing
  parent directories itself, and on a fresh checkout ``data/`` does not
  exist under the ``./backend:/app`` dev bind mount.
- Enables WAL journal mode + foreign keys on every new connection.
"""

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:////app/data/garmin.db")


def _ensure_sqlite_dir_exists(database_url: str) -> None:
    """Create the parent directory of a file-based SQLite DB, if needed.

    No-op for ``sqlite:///:memory:`` and any non-sqlite URL.
    """
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return
    db_path = url.database
    if not db_path or db_path == ":memory:":
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def _build_engine(database_url: str):
    _ensure_sqlite_dir_exists(database_url)
    engine = create_engine(database_url)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


engine = _build_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass
