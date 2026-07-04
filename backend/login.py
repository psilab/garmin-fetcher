"""One-time interactive login to Garmin Connect.

Run this once to create the token store; the API service then reuses it and
never needs your password again. Tokens auto-refresh until the refresh token
expires (typically ~1 year), at which point you re-run this.

    docker compose -f docker-compose.dev.yml run --rm backend python login.py

Credentials are read from GARMIN_EMAIL / GARMIN_PASSWORD if set, otherwise
you'll be prompted. If your account has MFA enabled, you'll be asked for the
code interactively.
"""

import getpass
import os
import sys

from garminconnect import Garmin

TOKENSTORE = os.environ.get("GARMINTOKENS", "/tokens")


def prompt_mfa() -> str:
    return input("MFA code: ").strip()


def main() -> int:
    email = os.environ.get("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = os.environ.get("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")

    print(f"Logging in as {email} ...")
    garmin = Garmin(email=email, password=password, prompt_mfa=prompt_mfa)
    garmin.login()

    os.makedirs(TOKENSTORE, exist_ok=True)
    garmin.client.dump(TOKENSTORE)
    print(f"Success. Tokens saved to {TOKENSTORE}")
    print(f"Logged in as: {garmin.get_full_name()}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Login failed: {exc}", file=sys.stderr)
        sys.exit(1)
