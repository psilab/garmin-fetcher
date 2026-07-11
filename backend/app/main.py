"""Garmin Fetcher — PoC API.

Serves your own Garmin Connect activity data as JSON.
"""

import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .api.metrics import router as metrics_router
from .garmin import NotAuthenticated, get_client
from .mcp.server import mcp_app
from .sync.scheduler import build_scheduler

# Observability for the in-app self-healing scheduler (Plan 02-05): uvicorn
# does not configure the root logger, so app + APScheduler INFO records
# (e.g. run_daily_sync's "[sync:scheduler] ... synced N rows") are silently
# dropped (root defaults to WARNING). Configure once, at INFO, to stdout.
# basicConfig is idempotent (no-op if the root logger already has handlers),
# and uvicorn's own loggers keep propagate=False so access logs are not
# duplicated into this stream.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger("apscheduler").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


# RESEARCH.md Pattern 3 / Phase 1 Pitfall 1: the scheduler must be composed
# INTO the lifespan, not replace it -- dropping mcp_app's lifespan makes
# every /mcp request hang or fail with a RuntimeError (the MCP session
# manager's task group never initializes). The `async with` line below,
# entering mcp_app's own lifespan context, is the load-bearing line (T-02-16).
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = build_scheduler()
    scheduler.start()
    try:
        async with mcp_app.lifespan(app):  # MUST keep -- MCP session manager
            yield
    finally:
        scheduler.shutdown(wait=False)  # graceful stop on app shutdown


app = FastAPI(title="Garmin Fetcher", version="0.2.0", lifespan=lifespan)

# PoC: allow the Next.js frontend (any origin) to call us.
# Scoped only to this parent app -- the /mcp mount below carries its own
# BearerAuthMiddleware (Plan 03) and deliberately does NOT inherit this
# permissive CORS policy (RESEARCH.md Open Question 2).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/me")
def me():
    """Basic profile info — also a quick check that auth works."""
    try:
        client = get_client()
        return client.get_full_name(), client.get_unit_system()
    except NotAuthenticated as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/api/activities")
def activities(limit: int = Query(default=10, ge=1, le=100)):
    """Most recent activities (newest first)."""
    try:
        client = get_client()
        return client.get_activities(0, limit)
    except NotAuthenticated as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/api/activities/range")
def activities_range(
    start: date | None = Query(default=None, description="YYYY-MM-DD, defaults to 30 days ago"),
    end: date | None = Query(default=None, description="YYYY-MM-DD, defaults to today"),
):
    """Activities within a date range."""
    end = end or date.today()
    start = start or (end - timedelta(days=30))
    if start > end:
        raise HTTPException(status_code=400, detail="start must be <= end")
    try:
        client = get_client()
        return client.get_activities_by_date(start.isoformat(), end.isoformat())
    except NotAuthenticated as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# Phase 6 (Plan 06-01, DASH-01) adds the read-only dashboard REST façade over
# the Phase 3 analysis engine: `/api/metrics/*` (registry-backed trend series)
# via the included router below. The `/mcp` mount MUST stay the LAST
# route-registration statement so the REST routes above (and this router) are
# unaffected by anything on the /mcp sub-app.
app.include_router(metrics_router)

app.mount("/mcp", mcp_app)
