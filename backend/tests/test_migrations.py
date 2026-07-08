from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

ALEMBIC_INI = Path(__file__).parent.parent / "alembic.ini"

EXPECTED_COLUMNS = {
    "activity_id",
    "activity_type",
    "start_time",
    "distance_m",
    "duration_s",
    "average_hr",
    "calories",
    "raw",
    "synced_at",
}

# Phase 2 domain tables (migration 0002). Column sets confirmed against live
# Garmin payloads captured in Wave 0 (Plan 02-01 Task 2).
EXPECTED_SLEEP_COLUMNS = {
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
    "raw",
    "synced_at",
}

EXPECTED_DAILY_HEALTH_COLUMNS = {
    "date",
    "total_steps",
    "resting_hr",
    "stress_avg",
    "spo2_avg",
    "respiration_avg",
    "intensity_minutes_moderate",
    "intensity_minutes_vigorous",
    "raw",
    "synced_at",
}

EXPECTED_BODY_COMPOSITION_COLUMNS = {
    "sample_pk",
    "date",
    "weight_g",
    "body_fat_pct",
    "raw",
    "synced_at",
}

# Phase 3 longevity-marker table (migration 0003). New Garmin sync
# (VO2max + training_load), not backfilled from any existing raw payload.
EXPECTED_LONGEVITY_MARKERS_COLUMNS = {
    "date",
    "vo2max",
    "fitness_age",
    "training_load",
    "raw",
    "synced_at",
}

# Phase 4 journal table (migration 0004). Data originates in-app, not from a
# Garmin sync -- deliberately no `raw` column (D-01).
EXPECTED_JOURNAL_COLUMNS = {
    "id",
    "body",
    "occurred_at",
    "end_date",
    "tags",
    "created_at",
}


def _migrate_to_head(tmp_path):
    db_path = tmp_path / "migrated.db"
    database_url = f"sqlite:///{db_path}"

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    return config, engine


def test_alembic_upgrade_head_creates_workouts_table(tmp_path):
    _, engine = _migrate_to_head(tmp_path)
    inspector = inspect(engine)
    assert "workouts" in inspector.get_table_names()

    columns = {col["name"] for col in inspector.get_columns("workouts")}
    assert columns == EXPECTED_COLUMNS


def test_alembic_upgrade_head_creates_domain_tables(tmp_path):
    _, engine = _migrate_to_head(tmp_path)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    for table, expected in (
        ("sleep", EXPECTED_SLEEP_COLUMNS),
        ("daily_health", EXPECTED_DAILY_HEALTH_COLUMNS),
        ("body_composition", EXPECTED_BODY_COMPOSITION_COLUMNS),
    ):
        assert table in table_names, f"{table} table missing after upgrade"
        columns = {col["name"] for col in inspector.get_columns(table)}
        assert columns == expected, f"{table} column set mismatch"


def test_alembic_downgrade_drops_domain_tables(tmp_path):
    config, engine = _migrate_to_head(tmp_path)

    # Downgrade one revision (0002 -> 0001) should drop the three domain tables
    # while leaving workouts intact.
    command.downgrade(config, "0001")

    inspector = inspect(create_engine(str(engine.url)))
    table_names = set(inspector.get_table_names())
    assert "workouts" in table_names
    for table in ("sleep", "daily_health", "body_composition"):
        assert table not in table_names, f"{table} not dropped on downgrade"


def test_alembic_upgrade_head_creates_longevity_markers_table(tmp_path):
    _, engine = _migrate_to_head(tmp_path)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert "longevity_markers" in table_names
    columns = {col["name"] for col in inspector.get_columns("longevity_markers")}
    assert columns == EXPECTED_LONGEVITY_MARKERS_COLUMNS


def test_alembic_downgrade_drops_longevity_markers_while_others_remain(tmp_path):
    config, engine = _migrate_to_head(tmp_path)

    # Downgrade one revision (0003 -> 0002) should drop only longevity_markers.
    command.downgrade(config, "0002")

    inspector = inspect(create_engine(str(engine.url)))
    table_names = set(inspector.get_table_names())
    assert "longevity_markers" not in table_names
    for table in ("workouts", "sleep", "daily_health", "body_composition"):
        assert table in table_names, f"{table} unexpectedly dropped"


def test_alembic_upgrade_head_creates_journal_table(tmp_path):
    _, engine = _migrate_to_head(tmp_path)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert "journal_entries" in table_names
    columns = {col["name"] for col in inspector.get_columns("journal_entries")}
    assert columns == EXPECTED_JOURNAL_COLUMNS

    # FTS5 virtual tables register in sqlite_master, so get_table_names()
    # lists journal_fts too.
    assert "journal_fts" in table_names


def test_alembic_downgrade_drops_journal_while_others_remain(tmp_path):
    config, engine = _migrate_to_head(tmp_path)

    # Downgrade one revision (0004 -> 0003) should drop only the journal
    # objects (table + FTS5 virtual table); all prior domain tables remain.
    command.downgrade(config, "0003")

    inspector = inspect(create_engine(str(engine.url)))
    table_names = set(inspector.get_table_names())
    assert "journal_entries" not in table_names
    assert "journal_fts" not in table_names
    for table in (
        "workouts",
        "sleep",
        "daily_health",
        "body_composition",
        "longevity_markers",
    ):
        assert table in table_names, f"{table} unexpectedly dropped"


def test_journal_fts_trigger_syncs_on_insert(tmp_path):
    """Direct proof that the AFTER INSERT trigger keeps journal_fts in sync.

    Deliberately bypasses JournalEntry/SessionLocal and inserts via a raw
    SQLAlchemy connection -- this proves the sync is a DB-level guarantee
    from the trigger DDL itself, not something that only works because the
    ORM happens to cooperate. Plan 04-02's log_note/query_journal tools
    depend on this holding true without any FTS5-specific application code.
    """
    _, engine = _migrate_to_head(tmp_path)

    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO journal_entries (body, occurred_at, tags, created_at)
                VALUES ('tweaked my leg today', '2026-07-08', 'injury, leg', '2026-07-08 00:00:00')
                """
            )
        )
        conn.commit()

        rows = conn.execute(
            text("SELECT rowid FROM journal_fts WHERE journal_fts MATCH 'leg'")
        ).fetchall()

    assert len(rows) == 1
