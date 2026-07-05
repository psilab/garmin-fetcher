from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

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
