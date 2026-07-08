"""create goals table

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-08

Schema-only migration -- no network-calling client library is imported or
invoked here (Pitfall 4: entrypoint.sh runs `alembic upgrade head` on every
container start, so any network call here would re-run every restart).

Unlike the journal domain (migration 0004), `goals` needs no FTS5 virtual
table or sync triggers -- it is simple mutable structured state, not
free-text content requiring keyword search.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("target_metric", sa.String(), nullable=True),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("goals")
