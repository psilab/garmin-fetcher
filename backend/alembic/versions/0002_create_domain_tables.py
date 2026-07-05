"""create sleep, daily_health, body_composition tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sleep",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("sleep_score", sa.Integer(), nullable=True),
        sa.Column("deep_s", sa.Float(), nullable=True),
        sa.Column("light_s", sa.Float(), nullable=True),
        sa.Column("rem_s", sa.Float(), nullable=True),
        sa.Column("awake_s", sa.Float(), nullable=True),
        sa.Column("hrv_avg", sa.Float(), nullable=True),
        sa.Column("body_battery_high", sa.Integer(), nullable=True),
        sa.Column("body_battery_low", sa.Integer(), nullable=True),
        sa.Column("training_readiness", sa.Integer(), nullable=True),
        sa.Column("training_status", sa.String(), nullable=True),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "daily_health",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("total_steps", sa.Integer(), nullable=True),
        sa.Column("resting_hr", sa.Integer(), nullable=True),
        sa.Column("stress_avg", sa.Integer(), nullable=True),
        sa.Column("spo2_avg", sa.Integer(), nullable=True),
        sa.Column("respiration_avg", sa.Float(), nullable=True),
        sa.Column("intensity_minutes_moderate", sa.Integer(), nullable=True),
        sa.Column("intensity_minutes_vigorous", sa.Integer(), nullable=True),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "body_composition",
        sa.Column("sample_pk", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("weight_g", sa.Float(), nullable=True),
        sa.Column("body_fat_pct", sa.Float(), nullable=True),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("body_composition")
    op.drop_table("daily_health")
    op.drop_table("sleep")
