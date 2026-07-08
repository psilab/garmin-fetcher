"""Tests for the get_latest_briefing MCP tool (COACH-05).

get_latest_briefing is a plain ORM tag-equality filter -- no FTS5 involved --
so these tests use the PLAIN db_session fixture from conftest.py (not the
migration-based journal_db_session fixture used by
test_mcp_journal_tools.py's text-search tests).
"""

import os
from datetime import date

os.environ.setdefault("MCP_TOKEN", "test-secret-for-tool-tests")

import pytest

from app.models import JournalEntry


@pytest.fixture(autouse=True)
def _patch_session_local(monkeypatch, db_session):
    """Point app.mcp.server at the plain in-memory db_session for every test."""
    import app.mcp.server as server_module

    monkeypatch.setattr(server_module, "SessionLocal", lambda: db_session)


def test_get_latest_briefing_returns_tagged_entry(db_session):
    from app.mcp.server import get_latest_briefing, log_note

    log_note(body="AI-generated morning briefing", tags="briefing")
    db_session.add(
        JournalEntry(body="tweaked my leg", occurred_at=date.today(), tags="injury")
    )
    db_session.commit()

    result = get_latest_briefing()

    assert len(result) == 1
    assert result[0]["body"] == "AI-generated morning briefing"
    assert result[0]["tags"] == "briefing"


def test_get_latest_briefing_orders_most_recent_first(db_session):
    from app.mcp.server import get_latest_briefing

    db_session.add_all(
        [
            JournalEntry(
                body="older briefing", occurred_at=date(2026, 1, 1), tags="briefing"
            ),
            JournalEntry(
                body="newer briefing", occurred_at=date(2026, 1, 2), tags="briefing"
            ),
        ]
    )
    db_session.commit()

    result_one = get_latest_briefing(limit=1)
    assert len(result_one) == 1
    assert result_one[0]["body"] == "newer briefing"

    result_two = get_latest_briefing(limit=2)
    assert len(result_two) == 2
    assert result_two[0]["body"] == "newer briefing"
    assert result_two[1]["body"] == "older briefing"


def test_get_latest_briefing_empty_when_none_exist(db_session):
    from app.mcp.server import get_latest_briefing

    db_session.add(
        JournalEntry(body="just a note", occurred_at=date.today(), tags="mood")
    )
    db_session.commit()

    result = get_latest_briefing()

    assert result == []
