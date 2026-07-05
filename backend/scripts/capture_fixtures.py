"""Capture live Garmin payloads as redacted fixtures (Wave 0 discovery).

This is the RESEARCH Pitfall-1 mitigation: typed-column source keys for the new
domains (sleep / daily_health / body_composition) are LOW-confidence until they
are confirmed against a *real* payload — exactly as Phase 1 did for activities.

It calls each new-domain getter once against the saved token volume, prints the
top-level keys of each payload (so field names, the body-battery source, and the
weigh-in natural key can be confirmed by eye), and writes redacted sample
payloads under ``backend/tests/fixtures/`` for the Plan 02-02 mapper tests.

Run (human — may prompt for MFA on first login):

    docker compose -f docker-compose.dev.yml run --rm backend python login.py   # if tokens stale
    docker compose -f docker-compose.dev.yml run --rm backend \
        python -m scripts.capture_fixtures --date 2026-07-01

Nothing here talks to the network except the Garmin getters; no password is
handled (``get_client`` only resumes from the /tokens volume).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from app.garmin import NotAuthenticated, get_client

# tests/fixtures relative to this file: backend/scripts/ -> backend/tests/fixtures
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# Obvious PII / account-identifying keys to strip before writing a fixture.
# Redaction is recursive so nested payloads are covered too.
PII_KEYS = {
    "userProfilePK",
    "userProfileId",
    "userProfileNumber",
    "ownerId",
    "ownerDisplayName",
    "ownerFullName",
    "ownerProfileImageUrlSmall",
    "ownerProfileImageUrlMedium",
    "ownerProfileImageUrlLarge",
    "email",
    "userName",
    "displayName",
    "fullName",
    "profileId",
}


def redact(obj):
    """Recursively strip obvious PII keys from dict/list payloads."""
    if isinstance(obj, dict):
        return {k: redact(v) for k, v in obj.items() if k not in PII_KEYS}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def _first_elem_keys(payload):
    """Keys of the first element for list-returning getters, else the dict keys."""
    if isinstance(payload, dict):
        return sorted(payload.keys())
    if isinstance(payload, list):
        if not payload:
            return "[] (empty list)"
        first = payload[0]
        if isinstance(first, dict):
            return sorted(first.keys())
        return f"[{type(first).__name__}, ...] (non-dict elements)"
    if payload is None:
        return "None"
    return f"({type(payload).__name__})"


def _call(label: str, fn, *args):
    """Call a getter defensively, print its top-level key shape, return payload."""
    try:
        payload = fn(*args)
    except Exception as exc:  # noqa: BLE001 - discovery script: never abort on one getter
        print(f"  {label:<24} ERROR: {exc}")
        return None
    print(f"  {label:<24} keys: {_first_elem_keys(payload)}")
    return payload


def _write(name: str, payload) -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURES_DIR / name
    with open(path, "w") as f:
        json.dump(redact(payload), f, indent=2, default=str)
    print(f"  wrote {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        required=True,
        help="A recent calendar date WITH data, YYYY-MM-DD (e.g. 2026-07-01).",
    )
    parser.add_argument(
        "--weigh-in-days",
        type=int,
        default=30,
        help="Look-back window (days) for get_weigh_ins so a real weigh-in is caught.",
    )
    args = parser.parse_args()

    try:
        cdate = dt.date.fromisoformat(args.date)
    except ValueError:
        print(f"Invalid --date {args.date!r}: expected YYYY-MM-DD", file=sys.stderr)
        return 2
    date = cdate.isoformat()
    wi_start = (cdate - dt.timedelta(days=args.weigh_in_days)).isoformat()
    wi_end = date

    try:
        client = get_client()
    except NotAuthenticated as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"\n=== Sleep / recovery getters ({date}) ===")
    sleep = _call("get_sleep_data", client.get_sleep_data, date)
    _call("get_hrv_data", client.get_hrv_data, date)
    _call("get_training_readiness", client.get_training_readiness, date)
    _call("get_training_status", client.get_training_status, date)
    body_battery = _call("get_body_battery", client.get_body_battery, date, date)

    print(f"\n=== All-day health getters ({date}) ===")
    stats = _call("get_stats", client.get_stats, date)
    _call("get_spo2_data", client.get_spo2_data, date)
    _call("get_respiration_data", client.get_respiration_data, date)

    print(f"\n=== Body composition getters ({wi_start} .. {wi_end}) ===")
    weigh_ins = _call("get_weigh_ins", client.get_weigh_ins, wi_start, wi_end)

    print("\n=== Writing fixtures ===")
    # Combine sleep + body_battery so the Plan 02-02 mapper fixture has the real
    # body-battery source alongside the sleep payload (body battery may live in
    # get_body_battery and/or inside get_sleep_data).
    _write("sample_sleep.json", {"sleep": sleep, "body_battery": body_battery})
    _write("sample_daily_health.json", stats)
    _write("sample_weigh_ins.json", weigh_ins)

    print(
        "\nDone. Confirm from the printed keys above:\n"
        "  - sleep typed-column source keys (score, stage durations, HRV)\n"
        "  - the body-battery source getter + field(s) for high/low\n"
        "  - daily_health source keys (steps, resting HR, stress, SpO2, respiration, intensity)\n"
        "  - body_composition typed-column keys (weight, body-fat %)\n"
        "  - the stable per-weigh-in natural key (e.g. samplePk) for the PK\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
