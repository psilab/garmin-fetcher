"""create longevity_markers table

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-07

Schema-only migration -- no network-calling client library is imported or
invoked here (Pitfall 4: entrypoint.sh runs `alembic upgrade head` on every
container start, so any network call here would re-run every restart).
Historical data capture lives exclusively in `app/sync/longevity.py`'s
`backfill_longevity`.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "longevity_markers",
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("vo2max", sa.Float(), nullable=True),
        sa.Column("fitness_age", sa.Integer(), nullable=True),
        sa.Column("training_load", sa.Float(), nullable=True),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("longevity_markers")
