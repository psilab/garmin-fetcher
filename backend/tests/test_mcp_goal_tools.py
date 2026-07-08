"""Tests for the goals domain's coach-facing MCP tools (set_goal, list_goals,
update_goal -- COACH-06).

Unlike the journal domain, goals need no migration-based fixture -- there is
no FTS5/trigger DDL invisible to Base.metadata.create_all(), so the plain
db_session fixture from conftest.py is sufficient.
"""

import os

os.environ.setdefault("MCP_TOKEN", "test-secret-for-tool-tests")

import pytest

# Module-level import ensures app.models (and therefore Goal) is registered
# on Base.metadata before the db_session fixture calls
# Base.metadata.create_all() -- mirrors test_mcp_journal_tools.py's
# module-level `from app.models import JournalEntry` for the same reason.
from app.models import Goal  # noqa: F401


@pytest.fixture(autouse=True)
def _patch_session_local(monkeypatch, db_session):
    """Point app.mcp.server at the plain db_session for every test."""
    import app.mcp.server as server_module

    monkeypatch.setattr(server_module, "SessionLocal", lambda: db_session)


def test_set_goal_persists_goal(db_session):
    from app.mcp.server import set_goal

    result = set_goal(description="reduce resting HR to 55")

    assert result["status"] == "active"
    assert result["description"] == "reduce resting HR to 55"
    assert result["target_metric"] is None
    assert result["target_value"] is None


def test_set_goal_rejects_blank_description(db_session):
    from app.mcp.server import set_goal

    with pytest.raises(ValueError):
        set_goal(description="   ")


def test_list_goals_filters_by_status(db_session):
    from app.mcp.server import list_goals, set_goal, update_goal

    active_goal = set_goal(description="stay active")
    paused_goal = set_goal(description="paused goal")
    update_goal(id=paused_goal["id"], status="paused")

    only_active = list_goals(status="active")
    assert len(only_active) == 1
    assert only_active[0]["id"] == active_goal["id"]

    both = list_goals()
    assert len(both) == 2


def test_update_goal_mutates_status_and_bumps_updated_at(db_session):
    from app.mcp.server import set_goal, update_goal

    goal = set_goal(description="reduce resting HR to 55")
    original_updated_at = goal["updated_at"]

    updated = update_goal(id=goal["id"], status="done")

    assert updated["status"] == "done"
    assert updated["updated_at"] >= goal["created_at"]
    assert updated["updated_at"] != original_updated_at


def test_update_goal_nonexistent_raises(db_session):
    from app.mcp.server import update_goal

    with pytest.raises(ValueError):
        update_goal(id=999999, status="done")
