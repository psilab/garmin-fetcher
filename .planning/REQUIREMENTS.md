# Requirements — Personal Longevity Platform (v1)

Derived from `.planning/PROJECT.md` and the locked stack in `docs/STACK.md`.
Core value: a conversational AI coach (Claude via MCP) giving smart recommendations
grounded in long-term analysis of the user's own health data.

## v1 Requirements

### Data ingestion & storage (SQLite)
- [x] **DATA-01**: Sync Garmin workouts (type, distance, duration, HR, calories) into local SQLite
- [x] **DATA-02**: Sync sleep & recovery (sleep stages/score, HRV, body battery, training readiness/status)
- [x] **DATA-03**: Sync all-day health (steps, resting HR, stress, SpO2, respiration, intensity minutes)
- [x] **DATA-04**: Sync body composition & weight (weight, body-fat %, when weigh-ins exist)
- [x] **DATA-05**: Backfill full available history on first run; then daily incremental sync over a rolling window (self-healing on late/edited data)
- [ ] **DATA-06**: User can add a free-text, timestamped subjective journal entry ("tweaked my leg", mood, pain)
- [x] **DATA-07**: Each source table keeps a raw payload alongside typed columns (resilient to Garmin schema drift)

### Analysis engine (Python, deterministic)
- [x] **ANLZ-01**: Compute trends and rolling baselines for any metric over an arbitrary date range
- [x] **ANLZ-02**: Compute correlations between metrics (e.g., sleep vs next-day HRV, training load vs resting HR)
- [ ] **ANLZ-03**: Detect notable deviations/anomalies from a metric's baseline
- [x] **ANLZ-04**: Track longevity-marker trajectories over time (VO2max, HRV, resting HR, body composition)

### Coach (MCP server + Claude)
- [x] **COACH-01**: MCP server exposes read tools over stored data and analysis outputs
- [ ] **COACH-02**: MCP tool to query the journal by keyword (FTS5) and/or date range
- [ ] **COACH-03**: MCP write tool to log a journal note from the conversation
- [x] **COACH-04**: In Claude Code, the coach answers plain-language questions grounded in the user's history via the MCP tools
- [ ] **COACH-05**: A scheduled routine produces a morning briefing (recovery status, what to watch, suggestion for the day)
- [ ] **COACH-06**: Recommendations are oriented to longevity as the north star, layered with user-set goals

### Access & security
- [x] **SEC-01**: MCP server exposed over HTTPS behind Traefik (`mcp.garmin.psi.makeup`)
- [x] **SEC-02**: Bearer-token auth on the MCP server — requests without a valid token are rejected (401)
- [x] **SEC-03**: Garmin auth bootstrapped via `login.py` (MFA), tokens persisted in a Docker volume, reused non-interactively

### Dashboards (lightweight, optional)
- [ ] **DASH-01**: Read-only Next.js dashboard rendering key metric charts (kept light for the 1 GB server)

## v2 / Deferred

- OAuth 2.1 on the MCP server (enables the coach in the claude.ai app / mobile)
- Nutrition data: automatic entry (manual capture only in v1) or integration (Cronometer/MyFitnessPal)
- Blood-biomarker PDF parsing (manual entry only in v1; user rarely tests)
- Embeddings / semantic journal search (FTS5 keyword search is enough at current scale)
- Auto-generated training plans pushed back to the Garmin device
- Proactive alerts / notifications (beyond the daily briefing)

## Out of Scope

- Multi-tenant SaaS / selling to others — single-user focus; revisit only if a market appears
- Real-time / intraday streaming from the watch — long-term analysis is the point
- Medical diagnosis or treatment — advises on lifestyle/training only
- Official Garmin Developer Program integration — unofficial library suffices for personal use

## Traceability

REQ-ID → Phase (see `.planning/ROADMAP.md`). Coverage: 21/21 mapped.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SEC-03 | Phase 1 | Complete |
| DATA-01 | Phase 1 | Complete |
| DATA-07 | Phase 1 | Complete |
| SEC-01 | Phase 1 | Complete |
| SEC-02 | Phase 1 | Complete |
| COACH-01 | Phase 1 | Complete |
| COACH-04 | Phase 1 | Complete |
| DATA-02 | Phase 2 | Complete |
| DATA-03 | Phase 2 | Complete |
| DATA-04 | Phase 2 | Complete |
| DATA-05 | Phase 2 | Complete |
| ANLZ-01 | Phase 3 | Complete |
| ANLZ-02 | Phase 3 | Complete |
| ANLZ-03 | Phase 3 | Pending |
| ANLZ-04 | Phase 3 | Complete |
| DATA-06 | Phase 4 | Pending |
| COACH-02 | Phase 4 | Pending |
| COACH-03 | Phase 4 | Pending |
| COACH-05 | Phase 5 | Pending |
| COACH-06 | Phase 5 | Pending |
| DASH-01 | Phase 6 | Pending |

---
*Created: 2026-07-04*
