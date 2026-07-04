"""Thin wrapper around python-garminconnect.

Auth model for the PoC:

- Tokens live in a directory (``GARMINTOKENS``, default ``/tokens``) that is
  mounted as a Docker volume so they survive container restarts.
- The one-time login (which may require an MFA code) is done interactively via
  ``login.py``. The API service only ever *resumes* from saved tokens and never
  handles a password itself.
"""

import os

from garminconnect import Garmin

TOKENSTORE = os.environ.get("GARMINTOKENS", "/tokens")


class NotAuthenticated(RuntimeError):
    """Raised when there are no usable saved tokens yet."""


def get_client() -> Garmin:
    """Return a logged-in Garmin client using saved tokens.

    Raises ``NotAuthenticated`` if no valid tokens exist — in that case run
    the login bootstrap: ``docker compose run --rm backend python login.py``.
    """
    garmin = Garmin()
    try:
        garmin.login(TOKENSTORE)
    except Exception as exc:  # noqa: BLE001 - any resume failure means re-login needed
        raise NotAuthenticated(
            "No valid Garmin tokens found. Run the login bootstrap:\n"
            "  docker compose -f docker-compose.dev.yml run --rm backend python login.py"
        ) from exc
    return garmin
