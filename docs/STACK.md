# Tech Stack & Architecture — LOCKED

Personal longevity platform. Decisions below are fixed as of 2026-07-04.
Supersedes the architecture sketch in `docs/PLAN.md` (Postgres / dashboards-first /
in-app chat — no longer the plan).

## Architecture: "Claude is the brain"

The app is **not** a self-contained AI product with its own chat UI. Instead the
app is a private **data + analysis layer**, and the coach IS Claude (Claude
app / Claude Code) connected over **MCP**. The heavy, mechanical work (fetching,
storing, computing) runs on the user's server; the *thinking* is done by Claude.

```
        user's server — everything private, in Docker
┌────────────────────────────────────────────────────┐
│  scheduler ──► Garmin ──► SQLite (your data)          │
│                              │                         │
│               analysis engine (Python: trends, corr.)  │
│                              │                         │
│                    FastAPI app (one backend)           │
│                    /                    \              │
│              REST (dashboards)        MCP (tools)       │
└──────────────┼──────────────────────────┼─────────────┘
               │                           │
          Next.js                    Claude (chat coach)
        (charts, read-only)      + routine (daily briefing)
```

## Components

| Layer | Choice | Notes |
|-------|--------|-------|
| **Datastore** | **SQLite + FTS5** | Single-user, tiny data → embedded file, ~0 idle RAM. Perfect for a weak server. WAL mode. Backup = copy the file. |
| **Sync** | In-app scheduler + worker | Pulls Garmin → SQLite. Mechanical, **no LLM**. Reliability-focused. |
| **Analysis engine** | Python: `pandas`, `numpy`, `scipy`/`statsmodels` | Trends, rolling baselines, correlations, anomaly detection, longevity-marker trajectories. Plain functions, called by both the scheduler and the MCP tools. "Smart from the start." |
| **Backend** | **FastAPI** (one app) | Serves **REST** (for dashboards) *and* hosts the **MCP server** (tools for Claude). Not two backends — one. |
| **ORM / migrations** | SQLAlchemy 2.0 + Alembic | Works identically on SQLite; cheap migration to Postgres later if the server grows. |
| **The brain** | **Claude via MCP** | No custom chat UI, no in-app LLM orchestration, no API-key juggling for chat. Always latest Opus, with tools. |
| **Background thinking** | **Claude Code routines** (`/schedule`) | Daily briefing = a scheduled agent that connects to the MCP server. Not a dumb cron — a reasoning agent. |
| **Frontend** | Next.js 16 (App Router) | Read-only dashboards & charts (**Recharts**). Consult in-container Next 16 docs before FE work (`frontend/AGENTS.md`). |
| **Garmin access** | `python-garminconnect` | Tokens in Docker volume; `login.py` bootstrap (MFA). Unofficial API — sync layer decouples app from Garmin breakage. |
| **Runtime** | **Docker only** | Compose: `sqlite`(file volume) · `backend` (REST+MCP) · `sync worker` · `frontend`. Prod = GHCR + Traefik. |

## Explicitly dropped (for now)

- **Postgres** — overkill for single-user tiny data on a weak server. Revisit only if the server grows or we ingest high-frequency intraday series (then Timescale).
- **Embeddings / vector search / pgvector** — journal is small; SQLite FTS5 (keyword) + letting Claude read a filtered slice is enough. Add later only if the journal grows and keyword search feels dumb.
- **Local embedding model & Voyage** — both moot once embeddings are dropped; no extra RAM hog, no extra API key.
- **Custom chat backend / streaming chat UI** — replaced by Claude + MCP.
- **Blood-biomarker PDF parsing** — user rarely tests; a simple manual biomarker table, low priority.

## Data domains

From Garmin (via sync): workouts, sleep & recovery (HRV, body battery, training
readiness), all-day health (steps/HR/stress/SpO2), body composition.
Outside Garmin: nutrition (manual), subjective journal (free text the coach
factors in — "tweaked my leg"), biomarkers (manual, low priority).

## MCP tools (indicative)

`get_metrics(range)`, `get_trend(metric, range)`, `get_correlations(...)`,
`query_journal(text/date)`, `log_note(text)`, `get_longevity_markers()`,
`get_recent_activities(...)`. Read tools + a couple of write tools (journal).

## MCP auth (LOCKED)

- **Transport:** remote MCP over HTTPS behind Traefik at `mcp.garmin.psi.makeup`.
- **Auth:** **static bearer token** — server rejects any request without `Authorization: Bearer <secret>` (401). Verified supported by Claude Code remote MCP and by cloud routines; for headless routines a static token is *preferable* to OAuth (OAuth can't complete non-interactively).
- **Config:** `.mcp.json` committed to the repo with the token via env expansion (`Authorization: Bearer ${MCP_TOKEN}`) so routines inherit it. The secret itself is never committed.
- **Chat surface:** **Claude Code** (terminal/IDE) — same bearer token works for interactive chat *and* routines. No OAuth anywhere.
- **Deferred:** OAuth 2.1 — only needed later if we want the coach in the claude.ai / Claude Desktop app or on mobile (their custom-connector UI is OAuth-only, no bearer field). Not building it for v1.
- Sources: [Claude Code MCP](https://code.claude.com/docs/en/mcp.md), [Routines](https://code.claude.com/docs/en/routines.md), [MCP auth spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).

## Server budget (1 CPU / 1 GB)

- Fold the sync scheduler into the FastAPI process (APScheduler background thread) — avoids a second Python runtime.
- Next.js (`next start`) is the RAM hog (~150–300 MB) — keep dashboards light or defer them; the coach (Claude+MCP) doesn't need the frontend to function.
- SQLite is in-process (~0 idle RAM) — the right call at this size.

---
*Locked: 2026-07-04*
