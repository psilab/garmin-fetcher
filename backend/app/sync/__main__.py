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
from app.sync.body_composition import backfill_body_composition
from app.sync.daily_health import backfill_daily_health
from app.sync.longevity import backfill_longevity
from app.sync.sleep import backfill_sleep
from app.sync.workouts import backfill_workouts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.sync")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backfill", help="Full-history backfill of Garmin workouts into SQLite")
    subparsers.add_parser(
        "backfill-sleep", help="Full-history backfill of Garmin sleep & recovery into SQLite"
    )
    subparsers.add_parser(
        "backfill-daily-health",
        help="Full-history backfill of Garmin all-day health into SQLite",
    )
    subparsers.add_parser(
        "backfill-body-composition",
        help="Full-history backfill of Garmin weigh-ins / body composition into SQLite",
    )
    subparsers.add_parser(
        "backfill-longevity",
        help="One-off historical backfill of Garmin VO2max/training-load into SQLite (never run by Alembic)",
    )
    subparsers.add_parser(
        "backfill-all",
        help="Full-history backfill of every domain (sleep, daily-health, body-composition, longevity) into SQLite",
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

    if args.command == "backfill-daily-health":
        try:
            client = get_client()
        except NotAuthenticated as exc:
            print(str(exc), file=sys.stderr)
            return 1

        session = SessionLocal()
        try:
            count = backfill_daily_health(session, client)
        finally:
            session.close()

        print(f"Synced {count} daily-health days.")
        return 0

    if args.command == "backfill-body-composition":
        try:
            client = get_client()
        except NotAuthenticated as exc:
            print(str(exc), file=sys.stderr)
            return 1

        session = SessionLocal()
        try:
            count = backfill_body_composition(session, client)
        finally:
            session.close()

        print(f"Synced {count} weigh-in events.")
        return 0

    if args.command == "backfill-longevity":
        try:
            client = get_client()
        except NotAuthenticated as exc:
            print(str(exc), file=sys.stderr)
            return 1

        session = SessionLocal()
        try:
            count = backfill_longevity(session, client)
        finally:
            session.close()

        print(f"Synced {count} longevity-marker days.")
        return 0

    if args.command == "backfill-all":
        try:
            client = get_client()
        except NotAuthenticated as exc:
            print(str(exc), file=sys.stderr)
            return 1

        session = SessionLocal()
        try:
            sleep_count = backfill_sleep(session, client)
            daily_health_count = backfill_daily_health(session, client)
            body_comp_count = backfill_body_composition(session, client)
            longevity_count = backfill_longevity(session, client)
        finally:
            session.close()

        print(f"Synced {sleep_count} sleep days.")
        print(f"Synced {daily_health_count} daily-health days.")
        print(f"Synced {body_comp_count} weigh-in events.")
        print(f"Synced {longevity_count} longevity-marker days.")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
