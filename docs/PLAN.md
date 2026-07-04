# Garmin Fetcher → Personal Fitness Platform — Analysis & Plan

Single-user personal fitness platform built on Garmin Connect data.
Status: **PoC proven** (live activity fetch works end-to-end). This document is
the analysis and roadmap for turning it into the platform.

---

## 1. Current state (Phase 0 — done)

| Layer | Now |
|-------|-----|
| Backend | Python / FastAPI + `python-garminconnect` 0.3.6, **live-proxying** Garmin on every request |
| Auth | Interactive `login.py` (email/pass + MFA) → tokens in `garmin_tokens` Docker volume; auto-refresh |
| Frontend | Next.js 16 (App Router, server components) rendering `/api/activities` |
| Infra | Docker only. Dev via compose; prod via GHCR images + Traefik (`garmin.psi.makeup`) |

### What's fragile / missing for a platform
1. **No persistence.** Every page view hits Garmin live — slow, fragile (they break auth periodically), and rate-limit-exposed.
2. **No history.** No backfill of past data; nothing survives if Garmin locks the account.
3. **One data type.** Only activities. We want sleep/recovery, daily health, and body composition too.
4. **No analytics layer.** Raw list only — no trends, aggregations, or insights.

**Conclusion:** the #1 next move is a **local data layer + sync**, decoupling
the whole app from live Garmin calls. Everything else builds on it.

---

## 2. Target architecture

```
                 ┌─────────────────┐   scheduled + backfill    ┌──────────────┐
                 │   sync worker   │ ────────────────────────► │    Garmin    │
                 │ (APScheduler)   │ ◄──────────────────────── │   Connect    │
                 └────────┬────────┘        (python-garminconnect)
                          │ upsert
                          ▼
                 ┌─────────────────┐
                 │    Postgres     │  ← single source of truth (raw JSON + typed cols)
                 └────────┬────────┘
                          │ read
                          ▼
   Next.js 16  ────►  FastAPI  ────►  serves data + computed analytics from DB
   (dashboards)       (/api/*)
```

- **Postgres** — single source of truth. Garmin is just an upstream feed.
- **Sync worker** — a separate container (same image, different command) running
  a scheduler. Isolated from the API so an API restart never interrupts a sync,
  and a Garmin outage never takes down the UI.
- **FastAPI** — reads exclusively from Postgres. No live Garmin calls on the request path.
- **Next.js** — dashboards and views over the API.

### Why a dedicated worker vs. a cron/background thread
Single responsibility, independent restarts, and clear failure isolation. Same
Docker image keeps the build simple (`command:` override in compose).

---

## 3. Data scope & library method map

All four requested domains are covered by `python-garminconnect`. Most daily
metrics are **keyed by date**, so sync = iterate over dates.

| Domain | Key library methods | Notes |
|--------|--------------------|-------|
| **Workouts** | `get_activities_by_date(start,end)`, `get_activities(0,n)`, `get_activity_details(id)`, `get_activity_splits(id)`, `get_activity_weather(id)` | Backfill by date range; details/splits fetched lazily per activity |
| **Sleep & recovery** | `get_sleep_data(date)`, `get_hrv_data(date)`, `get_all_day_stress(date)`, `get_body_battery(start,end)`, `get_rhr_day(date)`, `get_training_readiness(date)`, `get_training_status(date)` | The recovery/readiness core |
| **Daily health** | `get_stats(date)` / `get_user_summary(date)`, `get_steps_data(date)`, `get_heart_rates(date)`, `get_respiration_data(date)`, `get_spo2_data(date)`, `get_intensity_minutes_data(date)`, `get_floors(date)` | `get_stats` is the daily rollup; others add granularity |
| **Weight / body** | `get_body_composition(start,end)`, `get_daily_weigh_ins(date)`, `get_weigh_ins(start,end)` | Sparse — only on days you weigh in |
| **Performance (bonus)** | `get_max_metrics(date)` (VO2max), `get_endurance_score(...)`, `get_race_predictions()`, `get_hill_score(...)`, `get_lactate_threshold()` | High-value for analytics/coaching later |

---

## 4. Data model (proposed)

**Hybrid storage** — every row keeps typed columns for the fields we actually
query **plus** a `raw jsonb` column with the full Garmin payload. This makes us
resilient to Garmin schema drift: if they add/rename a field, the raw blob still
has it and we backfill a column later without re-syncing.

| Table | Key | Typed columns (indicative) |
|-------|-----|----------------------------|
| `activities` | `activity_id` (Garmin) | start_time, type, distance_m, duration_s, avg_hr, calories, raw |
| `sleep_days` | `date` | total_sleep_s, deep_s, rem_s, light_s, awake_s, sleep_score, hrv_avg, raw |
| `health_days` | `date` | steps, resting_hr, stress_avg, body_battery_high/low, spo2_avg, respiration_avg, intensity_minutes, calories, raw |
| `body_measurements` | `date` | weight_g, body_fat_pct, muscle_mass_g, bmi, raw |
| `readiness_days` | `date` | training_readiness, training_status, vo2max, raw |
| `sync_runs` | `id` | started_at, finished_at, domain, from_date, to_date, status, records, error |

Migrations via **Alembic**; ORM via **SQLAlchemy 2.0** (typed). Upserts are
idempotent (`ON CONFLICT DO UPDATE`) so re-running a sync is always safe.

---

## 5. Sync strategy

- **Backfill (one-time):** loop historical date ranges (e.g. months back) per
  domain, throttled, resumable via `sync_runs`. Kicked off by a CLI command.
- **Incremental (scheduled):** daily job pulls a **rolling window** (last ~5–7
  days, not just yesterday) because Garmin data arrives late and gets edited
  (sleep finalizes, activities get renamed). Overlap + upsert = self-healing.
- **Resilience:** exponential backoff on errors; a failed domain doesn't block
  others; every run recorded in `sync_runs`; alert (log/notify) on repeated failure.
- **Auth:** unchanged — worker resumes from the shared token volume. If the
  refresh token expires, sync fails loudly → re-run `login.py`.

---

## 6. Roadmap

### Phase 1 — Data Foundation ⭐ (the enabler)
Postgres + SQLAlchemy/Alembic; the 5 domain tables; sync worker container with
APScheduler; backfill CLI + daily incremental for all 4 domains; migrate the API
to read from DB. **Exit:** all my Garmin data lives locally and refreshes daily.

### Phase 2 — Insights & Dashboards
Aggregation endpoints (weekly load, HR-zone distribution, sleep vs. performance,
weight trend, readiness timeline) + charts in the frontend (Recharts; follow the
`dataviz` design guidance). **Exit:** I read my fitness like a dashboard.

### Phase 3 — AI Coach
LLM (Claude) over the local data: natural-language Q&A ("how was my training
this week?"), trend explanations, and recommendations that factor in
readiness/fatigue. **Exit:** conversational coach that knows my history.

### Phase 4 — Training Planner
Build workouts/plans in-app and push them to the watch (library supports workout
upload + scheduling). **Exit:** plan here → sync to Garmin device.

### Cross-cutting (ongoing)
Postgres backups (`pg_dump` volume), sync monitoring/alerts, secrets handling,
observability.

---

## 7. Tech decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Datastore | **Postgres** (container) | Relational + strong `jsonb`; room for time-series queries |
| ORM / migrations | **SQLAlchemy 2.0 + Alembic** | Typed, mature, migration story |
| Scheduler | **APScheduler** in a dedicated worker container | Simple, in-process, isolated from API |
| Charts | **Recharts** (Phase 2) | React-native fit for Next; see `dataviz` skill |
| AI | **Claude API** (Phase 3) | Best models; see `claude-api` skill when we get there |
| Everything | **Docker only** | Per project rule — no host runtimes |

---

## 8. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Garmin breaks auth (again) | DB decouples reads from Garmin; UI keeps working; sync fails loudly, re-run `login.py` |
| Garmin schema drift | Store raw `jsonb` alongside typed cols; backfill new cols without re-sync |
| Rate limiting on backfill | Throttle + backoff; resumable via `sync_runs`; incremental uses small windows |
| Unofficial API (ToS) | Personal single-user use; keep footprint low; official Dev Program remains a fallback |
| Data loss | Scheduled `pg_dump` backups of the Postgres volume |

---

## 9. Immediate next step

Start **Phase 1**: stand up Postgres in compose, define the schema + Alembic
migrations, and build the sync worker with an activities backfill first (we
already know that shape), then add sleep / health / body. Ship each domain
incrementally.
