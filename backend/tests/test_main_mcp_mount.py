"""Tests for mounting the Plan 03 MCP sub-app into the FastAPI app (Plan 04).

Covers RESEARCH.md Pitfall 1 (lifespan passthrough) and Open Question 2
(bearer middleware scoped only to /mcp, REST stays unauthenticated).
"""

import asyncio
import os

import httpx
import pytest

# app.mcp.auth reads MCP_TOKEN at import time (fails fast if unset) --
# app.main imports app.mcp.server -> app.mcp.auth, so this must be set
# before the first import of app.main below. setdefault mirrors
# test_mcp_tools.py's approach so this is safe regardless of test order.
os.environ.setdefault("MCP_TOKEN", "test-secret-for-main-mount-tests")
MCP_TOKEN = os.environ["MCP_TOKEN"]

from app.main import app  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_mcp_mount_without_token_401():
    """/mcp with no Authorization header returns 401 -- proves the bearer
    middleware is active on the mounted path, not bypassed by mount ordering."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/mcp/", json={})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_rest_routes_still_unauthenticated():
    """/health stays open with no auth header -- REST is out of MCP's
    bearer-auth scope in Phase 1 (RESEARCH.md Open Question 2 resolution)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_lifespan_starts_without_hanging():
    """The MCP session manager initializes when the app's lifespan runs --
    regression test for RESEARCH.md Pitfall 1 (lifespan not passed through
    causes hangs/RuntimeErrors, not clean errors, on non-401 requests)."""
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await asyncio.wait_for(
                client.post(
                    "/mcp/",
                    json={},
                    headers={"Authorization": f"Bearer {MCP_TOKEN}"},
                ),
                timeout=5,
            )
    assert response.status_code != 401
