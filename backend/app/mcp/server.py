"""FastMCP server exposing the D-04 coach read tools over the workouts table.

Mounted by ``app/main.py`` (Plan 04) at ``/mcp``:

    app = FastAPI(lifespan=mcp_app.lifespan)
    app.mount("/mcp", mcp_app)

``mcp_app`` bundles the hand-rolled ``BearerAuthMiddleware`` (SEC-02) so every
request to the mount is bearer-checked before it ever reaches a tool.
"""

from datetime import date

from fastmcp import FastMCP
from starlette.middleware import Middleware

from .auth import BearerAuthMiddleware

mcp = FastMCP("Garmin Coach")


@mcp.tool
def list_recent_workouts(limit: int = 10) -> list[dict]:
    """Most recent workouts, newest first."""
    return []


@mcp.tool
def filter_workouts(
    activity_type: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    """Workouts filtered by type and/or date range."""
    return []


@mcp.tool
def aggregate_workouts(
    activity_type: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """Totals (count, distance, duration, calories) for a filtered set."""
    return {}


@mcp.tool
def compare_periods(
    period_a_start: date,
    period_a_end: date,
    period_b_start: date,
    period_b_end: date,
    activity_type: str | None = None,
) -> dict:
    """Plain count/sum comparison between two date ranges (no trend analysis)."""
    return {}


# path="/" because the whole sub-app is mounted at /mcp by the parent app.
# Middleware scoped only to this sub-app — never attached to the parent
# FastAPI app, so REST routes remain unauthenticated in Phase 1.
mcp_app = mcp.http_app(path="/", middleware=[Middleware(BearerAuthMiddleware)])
