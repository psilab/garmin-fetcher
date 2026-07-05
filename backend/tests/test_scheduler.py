"""Tests for the self-healing daily-sync scheduler (DATA-05, Plan 02-05).

Covers: (a) build_scheduler() registers exactly one job under id
"daily_sync"; (b) run_daily_sync isolates a per-domain failure -- one
domain raising does not stop the other two, and no exception escapes;
(c) an empty table (window_for returns start=None) falls back to that
domain's full backfill.
"""

import app.sync.scheduler as scheduler_mod
from app.sync.scheduler import build_scheduler, run_daily_sync


def test_build_scheduler_registers_exactly_one_daily_sync_job():
    scheduler = build_scheduler()
    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "daily_sync"
    assert jobs[0].func is run_daily_sync


def test_run_daily_sync_isolates_a_domain_failure(monkeypatch, db_session):
    """One domain's sync function raises; the other two still run and no
    exception propagates out of run_daily_sync."""
    monkeypatch.setattr(scheduler_mod, "get_client", lambda: object())
    monkeypatch.setattr(scheduler_mod, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    calls = {"sleep": 0, "daily_health": 0, "body_composition": 0}

    def sleep_backfill(session, client):
        calls["sleep"] += 1
        return 1

    def daily_health_backfill(session, client):
        raise RuntimeError("simulated daily_health failure")

    def body_comp_backfill(session, client):
        calls["body_composition"] += 1
        return 3

    monkeypatch.setattr(
        scheduler_mod,
        "_DOMAIN_REGISTRY",
        [
            (scheduler_mod.Sleep, scheduler_mod.sync_sleep_window, sleep_backfill, "sleep"),
            (
                scheduler_mod.DailyHealth,
                scheduler_mod.sync_daily_health_window,
                daily_health_backfill,
                "daily_health",
            ),
            (
                scheduler_mod.BodyComposition,
                scheduler_mod.sync_body_composition_window,
                body_comp_backfill,
                "body_composition",
            ),
        ],
    )

    # Should not raise even though daily_health's backfill_fn raises.
    run_daily_sync()

    assert calls["sleep"] == 1
    assert calls["body_composition"] == 1


def test_run_daily_sync_falls_back_to_backfill_on_empty_table(monkeypatch, db_session):
    """window_for returns (None, today) for an empty table -- run_daily_sync
    must call the domain's backfill_* fn, not its sync_*_window fn."""
    monkeypatch.setattr(scheduler_mod, "get_client", lambda: object())
    monkeypatch.setattr(scheduler_mod, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    called = {"backfill": False, "window": False}

    def fake_backfill(session, client):
        called["backfill"] = True
        return 5

    def fake_window(session, client, start, end):
        called["window"] = True
        return 0

    monkeypatch.setattr(
        scheduler_mod,
        "_DOMAIN_REGISTRY",
        [(scheduler_mod.Sleep, fake_window, fake_backfill, "sleep")],
    )

    run_daily_sync()

    assert called["backfill"] is True
    assert called["window"] is False
