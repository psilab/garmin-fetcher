"""Hand-rolled bearer-token middleware for the MCP mount (SEC-02).

Deliberately NOT using ``fastmcp.server.auth.providers.jwt.StaticTokenVerifier``:
the official FastMCP docs state that verifier stores tokens as plain text and
"should never be used in production environments" — it's designed for dev/test.
A single static shared secret only needs a constant-time compare, not a
JWT-oriented auth stack.

Scoped only to the MCP sub-app (``mcp.http_app(middleware=[BearerAuthMiddleware])``)
— never attached to the parent FastAPI app, so REST routes stay unaffected.
"""

import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

EXPECTED_TOKEN = os.environ["MCP_TOKEN"]  # fail fast if unset


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Rejects any MCP request without a valid ``Authorization: Bearer <token>`` header.

    - Constant-time comparison (``secrets.compare_digest``) to avoid timing
      side-channels on the token check (T-03-03).
    - Generic 401 body that never echoes the submitted token, and the
      submitted token is never logged (T-03-02).
    """

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(token, EXPECTED_TOKEN):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)
