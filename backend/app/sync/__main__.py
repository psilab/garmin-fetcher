"""CLI entrypoint for Garmin sync jobs.

Usage:
    python -m app.sync backfill

Never prompts interactively -- reuses the already-bootstrapped Garmin
token volume (SEC-03). If no valid tokens exist, prints the same
"run login.py" bootstrap message as the PoC and exits non-zero.
"""

import argparse
import sys

from app.db import SessionLocal
from app.garmin import NotAuthenticated, get_client
from app.sync.sleep import backfill_sleep
from app.sync.workouts import backfill_workouts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.sync")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backfill", help="Full-history backfill of Garmin workouts into SQLite")
    subparsers.add_parser(
        "backfill-sleep", help="Full-history backfill of Garmin sleep & recovery into SQLite"
    )

    args = parser.parse_args(argv)

    if args.command == "backfill":
        try:
            client = get_client()
        except NotAuthenticated as exc:
            print(str(exc), file=sys.stderr)
            return 1

        session = SessionLocal()
        try:
            count = backfill_workouts(session, client)
        finally:
            session.close()

        print(f"Synced {count} workouts.")
        return 0

    if args.command == "backfill-sleep":
        try:
            client = get_client()
        except NotAuthenticated as exc:
            print(str(exc), file=sys.stderr)
            return 1

        session = SessionLocal()
        try:
            count = backfill_sleep(session, client)
        finally:
            session.close()

        print(f"Synced {count} sleep days.")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
