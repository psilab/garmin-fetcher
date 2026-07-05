"""In-app self-healing daily sync scheduler (DATA-05).

`build_scheduler()` returns an APScheduler `BackgroundScheduler` (NOT
`AsyncIOScheduler` -- the sync job is a long, blocking, synchronous run and
must execute on its own thread, off the FastAPI event loop, so `/mcp`
requests are never blocked while a sync is running; T-02-15) with exactly
one daily job registered: `run_daily_sync`.

`run_daily_sync()` is the job body: acquire ONE Garmin client + ONE DB
session for the whole run (T-02-02 -- never re-authenticate per domain),
then iterate the three domains. Each domain is wrapped in its own
try/except so one domain's failure (Garmin schema break, transient error)
never aborts the others (CR-01/CR-02 lesson, T-02-14). Per domain, the
catch-up window comes from `sync/common.window_for`: an empty table
(`start is None`) falls back to that domain's full `backfill_*`, otherwise
the rolling/catch-up `sync_*_window` runs over `[start, end]`.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import SessionLocal
from app.garmin import get_client
from app.models import BodyComposition, DailyHealth, Sleep
from app.sync.body_composition import backfill_body_composition, sync_body_composition_window
from app.sync.common import window_for
from app.sync.daily_health import backfill_daily_health, sync_daily_health_window
from app.sync.sleep import backfill_sleep, sync_sleep_window

logger = logging.getLogger(__name__)

# (model, sync_window_fn, backfill_fn, human-readable domain name) --
# window_for(session, model) drives backfill-vs-window per domain.
_DOMAIN_REGISTRY = [
    (Sleep, sync_sleep_window, backfill_sleep, "sleep"),
    (DailyHealth, sync_daily_health_window, backfill_daily_health, "daily_health"),
    (BodyComposition, sync_body_composition_window, backfill_body_composition, "body_composition"),
]


def run_daily_sync() -> None:
    """Job body for the "daily_sync" APScheduler job.

    One client + one session for the whole run. Each domain is isolated:
    a raised exception is caught, logged, and the loop continues -- the
    other domains still run and no exception escapes this function.
    """
    try:
        client = get_client()
    except Exception:  # noqa: BLE001 - can't sync anything without a client
        logger.exception("[sync:scheduler] could not obtain Garmin client; skipping run")
        return

    session = SessionLocal()
    try:
        for model, sync_window_fn, backfill_fn, name in _DOMAIN_REGISTRY:
            try:
                start, end = window_for(session, model)
                if start is None:
                    count = backfill_fn(session, client)
                else:
                    count = sync_window_fn(session, client, start.isoformat(), end.isoformat())
                logger.info("[sync:scheduler] %s: synced %s rows", name, count)
            except Exception:  # noqa: BLE001 - per-domain isolation (T-02-14/CR-01/CR-02)
                logger.exception("[sync:scheduler] %s: sync failed, continuing other domains", name)
                continue
    finally:
        session.close()


def build_scheduler() -> BackgroundScheduler:
    """Build (but do not start) a BackgroundScheduler with the single daily
    "daily_sync" job registered on a 04:00 CronTrigger.

    `coalesce=True` + `misfire_grace_time=3600` mean a run missed during
    downtime fires once on restart rather than piling up -- pairs with the
    catch-up window in `run_daily_sync` (T-02-14).
    """
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_daily_sync,
        CronTrigger(hour=4, minute=0),
        id="daily_sync",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    return scheduler
