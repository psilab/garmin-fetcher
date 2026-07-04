"""Garmin Fetcher — PoC API.

Serves your own Garmin Connect activity data as JSON.
"""

from datetime import date, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .garmin import NotAuthenticated, get_client

app = FastAPI(title="Garmin Fetcher", version="0.1.0")

# PoC: allow the Next.js frontend (any origin) to call us.
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
