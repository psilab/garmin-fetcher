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


def test_alembic_upgrade_head_creates_workouts_table(tmp_path):
    db_path = tmp_path / "migrated.db"
    database_url = f"sqlite:///{db_path}"

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "workouts" in inspector.get_table_names()

    columns = {col["name"] for col in inspector.get_columns("workouts")}
    assert columns == EXPECTED_COLUMNS
