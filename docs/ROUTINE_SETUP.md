# Daily Briefing Routine — Setup Runbook (v1)

**Version:** 1 — 2026-07-08

This is a human-executable runbook. **No code in this repo creates or configures the
claude.ai cloud routine** — there is no API/CLI for it, and the user explicitly does not want
Claude Code running on `psi.makeup` (D-07). This document exists so a human can click through
setup without guessing.

## 1. Prerequisite check

Confirm your claude.ai account plan actually supports **Routines** (scheduled cloud tasks).
This is not verifiable from this repo — check your plan's feature list on claude.ai before
proceeding.

## 2. Create a new scheduled Routine

On claude.ai, create a new Routine and select **this GitHub repo** as its source. Selecting
the repo makes the committed `.mcp.json` (the `garmin-coach` MCP server entry) and
`docs/BRIEFING_RUBRIC.md` available in the routine's cloned checkout.

## 3. Set `MCP_TOKEN` as an environment variable

In the routine's cloud environment configuration, add an environment variable named
`MCP_TOKEN`, using the **same value** as the production `MCP_TOKEN` already configured in the
Docker/Traefik deployment.

**Never paste the token into the routine's prompt text.** The routine's execution environment
does not inherit local shell env vars, GitHub Actions secrets, or `.env` files from the repo —
it must be set explicitly here, or `.mcp.json`'s `${MCP_TOKEN}` expansion will be empty and
every MCP call will return 401.

## 4. Set Network access to Custom and allow `garmin.psi.makeup`

In the routine's environment settings, set **Network access** to **Custom** and add
`garmin.psi.makeup` to **Allowed domains**. The default "Trusted" network tier only
allow-lists common package registries/cloud provider APIs — it does not include personal
domains. Without this step, MCP tool calls will fail with a `403` and
`x-deny-reason: host_not_allowed`, even though `MCP_TOKEN` and `.mcp.json` are both correct.

## 5. Set the routine prompt

Paste the following as the routine's prompt:

```text
Read docs/BRIEFING_RUBRIC.md from this repository checkout. Follow it exactly: call the
listed MCP tools (via the repo's committed .mcp.json connection to the garmin-coach server),
compose the fixed 3-section morning briefing, and persist it with log_note(tags="briefing").
Do not write any other files or open any pull request -- this routine's only side effect is
the log_note call.
```

Do not paste the rubric content itself into the prompt box — the prompt must instruct Claude
to *read* `docs/BRIEFING_RUBRIC.md` from the checkout each run, so future edits to the rubric
take effect immediately without needing to edit the routine.

## 6. Set the schedule

Set the schedule to run daily, ~07:00, confirming the exact timezone at setup time. The exact
time is intentionally not hardcoded in this repo — pick whatever suits your morning routine.

## 7. Open question — Connector fallback

The claude.ai Routines feature is in research preview, and its documentation has an internal
inconsistency about whether a repo-committed `.mcp.json` (rather than an account-level
"Connector") is reachable from a Cloud routine.

**If the routine's MCP tool calls are unavailable** via the repo-committed `.mcp.json` path,
fall back to registering `garmin-coach` as an account-level Connector at
`claude.ai/customize/connectors`, using the identical connection info:

```json
{
  "url": "https://garmin.psi.makeup/mcp/",
  "headers": {
    "Authorization": "Bearer <same MCP_TOKEN value>"
  }
}
```

This is the same URL and bearer header as `.mcp.json` — only the claude.ai click-path
differs, no architectural change.

## 8. Verify

After the first scheduled (or manually triggered) run:

1. Call `get_latest_briefing` (or ask the coach "show me today's briefing").
2. Confirm the returned entry:
   - has exactly three sections: recovery status / what to watch / one suggestion
   - is tagged `tags="briefing"`
   - contains no diagnostic/treatment language
   - references your active goals if you have any set (via `list_goals`)

If verification fails, note the exact failure mode (e.g. `403 host_not_allowed`,
`401` on every call, "routine has no MCP tool access") — these map directly to the pitfalls
in steps 3, 4, and 7 above.
