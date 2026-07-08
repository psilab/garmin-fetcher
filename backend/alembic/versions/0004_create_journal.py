"""create journal_entries + journal_fts (external-content FTS5) + sync triggers

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-08

Schema-only migration -- no network-calling client library is imported or
invoked here (Pitfall 4: entrypoint.sh runs `alembic upgrade head` on every
container start, so any network call here would re-run every restart).

This is the first FTS5 use and the first raw-`op.execute()`-only migration
content in the codebase. `journal_fts` is an external-content FTS5 virtual
table (`content='journal_entries', content_rowid='id'`) kept in sync purely
via three AFTER INSERT/UPDATE/DELETE triggers -- SQLite's own documented
pattern for external-content tables (RESEARCH.md Pattern 1). No application
code ever writes to `journal_fts` directly.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("tags", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.execute(
        """
        CREATE VIRTUAL TABLE journal_fts USING fts5(
            body, tags, content='journal_entries', content_rowid='id'
        )
        """
    )

    op.execute(
        """
        CREATE TRIGGER journal_entries_ai AFTER INSERT ON journal_entries BEGIN
          INSERT INTO journal_fts(rowid, body, tags) VALUES (new.id, new.body, new.tags);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER journal_entries_ad AFTER DELETE ON journal_entries BEGIN
          INSERT INTO journal_fts(journal_fts, rowid, body, tags)
          VALUES('delete', old.id, old.body, old.tags);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER journal_entries_au AFTER UPDATE ON journal_entries BEGIN
          INSERT INTO journal_fts(journal_fts, rowid, body, tags)
          VALUES('delete', old.id, old.body, old.tags);
          INSERT INTO journal_fts(rowid, body, tags) VALUES (new.id, new.body, new.tags);
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS journal_entries_au")
    op.execute("DROP TRIGGER IF EXISTS journal_entries_ad")
    op.execute("DROP TRIGGER IF EXISTS journal_entries_ai")
    op.execute("DROP TABLE IF EXISTS journal_fts")
    op.drop_table("journal_entries")
