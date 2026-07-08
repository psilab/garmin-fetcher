"""Tests for the hand-rolled bearer-token middleware on the MCP mount (SEC-02)."""

import httpx
import pytest


@pytest.fixture
def mcp_app(monkeypatch):
    """Import app.mcp.server fresh with MCP_TOKEN set, returning its mcp_app.

    Reloads app.mcp.auth too (not just app.mcp.server) -- EXPECTED_TOKEN is
    read at app.mcp.auth's own import time, so reloading only server_module
    leaves EXPECTED_TOKEN stale if some other test module (e.g.
    test_main_mcp_mount.py, which may import app.main -> app.mcp.auth first
    depending on test collection order) already triggered auth.py's first
    import with a different MCP_TOKEN value.
    """
    monkeypatch.setenv("MCP_TOKEN", "test-secret")
    import importlib

    import app.mcp.auth as auth_module
    import app.mcp.server as server_module

    importlib.reload(auth_module)
    importlib.reload(server_module)
    return server_module.mcp_app


@pytest.fixture
async def client(mcp_app):
    # FastMCP's StreamableHTTPSessionManager only initializes its task group
    # inside the app's lifespan context — httpx's ASGITransport does not run
    # ASGI lifespan events on its own, so we enter it manually here (mirrors
    # the `app = FastAPI(lifespan=mcp_app.lifespan)` passthrough Plan 04 does
    # in production; RESEARCH.md Pitfall 1).
    transport = httpx.ASGITransport(app=mcp_app)
    async with mcp_app.lifespan(mcp_app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.anyio
async def test_missing_token_401(client):
    response = await client.post("/", json={})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_log_note_requires_bearer_token(client):
    """T-04-06: the first write tool in the codebase must be rejected
    without a valid bearer token, identically to every read tool.
    BearerAuthMiddleware rejects before the body is ever parsed as an MCP
    JSON-RPC request, so this proves the mount-wide 401 behavior covers
    write tools without needing to construct a tools/call envelope naming
    log_note specifically."""
    response = await client.post("/", json={})
    assert response.status_code == 401


@pytest.mark.anyio
async def test_invalid_token_401(client):
    response = await client.post(
        "/", json={}, headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_valid_token_ok(client):
    response = await client.post(
        "/", json={}, headers={"Authorization": "Bearer test-secret"}
    )
    assert response.status_code != 401


@pytest.mark.anyio
async def test_401_body_does_not_echo_submitted_token(client):
    submitted = "super-secret-wrong-token-xyz"
    response = await client.post(
        "/", json={}, headers={"Authorization": f"Bearer {submitted}"}
    )
    assert response.status_code == 401
    assert submitted not in response.text


def test_empty_mcp_token_refuses_to_import(monkeypatch):
    """An empty MCP_TOKEN must fail fast, not silently allow `Bearer ` bypass."""
    import importlib

    import app.mcp.auth as auth_module

    monkeypatch.setenv("MCP_TOKEN", "")
    with pytest.raises(RuntimeError):
        importlib.reload(auth_module)

    # Restore a valid token so reloading doesn't leave the module unusable
    # for any later test that imports it.
    monkeypatch.setenv("MCP_TOKEN", "test-secret")
    importlib.reload(auth_module)


@pytest.fixture
def anyio_backend():
    return "asyncio"
