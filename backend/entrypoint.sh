#!/usr/bin/env sh
# Prod container entrypoint: bring the database schema up to date before the
# app starts, then hand off to the CMD (uvicorn). Alembic is idempotent — it
# only applies migrations newer than the DB's current revision — so this is a
# safe no-op on an already-migrated volume and self-heals a fresh/behind volume
# (closes the phase-02 "migration 0002 never applied on deploy" gap).
#
# Single backend container per host (single-user box), so there is no
# concurrent-migration race. `set -e` makes a failed migration abort startup
# loudly rather than booting the app against a stale/absent schema.
set -e

echo "[entrypoint] running alembic upgrade head..."
alembic upgrade head
echo "[entrypoint] migrations applied; starting app: $*"

exec "$@"
