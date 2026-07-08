"""Tests for the journal domain's coach-facing MCP tools (query_journal,
log_note, update_note -- DATA-06/COACH-02/COACH-03).

These tests use a migration-based fixture (journal_db_session), NOT the
plain db_session fixture in conftest.py. journal_fts and its sync triggers
are created via raw op.execute() DDL inside Alembic migration 0004 -- they
are invisible to Base.metadata.create_all(), so the plain db_session fixture
would raise `sqlite3.OperationalError: no such table: journal_fts` the
moment `text=` is exercised (RESEARCH.md Pitfall 1).
"""

import os
from datetime import date

os.environ.setdefault("MCP_TOKEN", "test-secret-for-tool-tests")

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import JournalEntry
from tests.test_migrations import _migrate_to_head


@pytest.fixture
def journal_db_session(tmp_path):
    """File-backed, fully-migrated session so journal_fts + its AFTER
    INSERT/UPDATE/DELETE triggers actually exist (RESEARCH.md Pitfall 1)."""
    _, engine = _migrate_to_head(tmp_path)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _patch_session_local(monkeypatch, journal_db_session):
    """Point app.mcp.server at the migrated journal_db_session for every test."""
    import app.mcp.server as server_module

    monkeypatch.setattr(server_module, "SessionLocal", lambda: journal_db_session)


def test_log_note_persists_entry(journal_db_session):
    from app.mcp.server import log_note

    result = log_note(body="tweaked my leg", tags="injury, leg")

    assert result["body"] == "tweaked my leg"
    assert result["tags"] == "injury, leg"
    assert result["occurred_at"] == date.today()
    assert result["end_date"] is None


def test_query_journal_text_search_orders_by_relevance(journal_db_session):
    from app.mcp.server import query_journal

    journal_db_session.add_all(
        [
            JournalEntry(
                body="knee knee knee pain, my knee really hurts today, knee knee",
                occurred_at=date(2026, 1, 1),
            ),
            JournalEntry(
                body="great run, felt strong, barely noticed my knee",
                occurred_at=date(2026, 1, 2),
            ),
        ]
    )
    journal_db_session.commit()

    result = query_journal(text="knee")

    assert len(result) == 2
    assert "knee knee knee" in result[0]["body"]


def test_query_journal_date_overlap_open_ended(journal_db_session):
    from app.mcp.server import query_journal

    journal_db_session.add(
        JournalEntry(body="ongoing leg issue", occurred_at=date(2026, 1, 1), end_date=None)
    )
    journal_db_session.commit()

    today = date(2026, 6, 1)
    result = query_journal(start=today, end=today)

    assert len(result) == 1
    assert result[0]["body"] == "ongoing leg issue"


def test_journal_overlap_filter_boundary_cases(journal_db_session):
    from app.mcp.server import query_journal

    journal_db_session.add(
        JournalEntry(
            body="fixed-span note", occurred_at=date(2026, 1, 5), end_date=date(2026, 1, 10)
        )
    )
    journal_db_session.commit()

    # start after end_date -> excluded
    assert query_journal(start=date(2026, 1, 12)) == []

    # start inside the span -> included
    assert len(query_journal(start=date(2026, 1, 8))) == 1

    # end before occurred_at -> excluded
    assert query_journal(end=date(2026, 1, 3)) == []

    # end inside the span -> included
    assert len(query_journal(end=date(2026, 1, 7))) == 1

    # both bounds spanning the note -> included
    assert len(query_journal(start=date(2026, 1, 1), end=date(2026, 1, 20))) == 1

    # neither bound -> included
    assert len(query_journal()) == 1


def test_log_note_then_query_journal_finds_entry(journal_db_session):
    from app.mcp.server import log_note, query_journal

    logged = log_note(body="rolled my ankle playing basketball", tags="injury")

    found = query_journal(text="ankle")

    assert any(e["id"] == logged["id"] for e in found)


def test_update_note_resyncs_fts_index(journal_db_session):
    from app.mcp.server import log_note, query_journal, update_note

    logged = log_note(body="old text unique_marker_a")
    update_note(id=logged["id"], body="new text unique_marker_b")

    assert len(query_journal(text="unique_marker_b")) == 1
    assert query_journal(text="unique_marker_a") == []


def test_query_journal_malformed_match_raises_valueerror(journal_db_session):
    from app.mcp.server import query_journal

    with pytest.raises(ValueError):
        query_journal(text='"unterminated quote')
