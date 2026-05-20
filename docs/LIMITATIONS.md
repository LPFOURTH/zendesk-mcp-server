# Limitations and Accepted Risks

> Branch: PR #3 to `fourth/main`. Tip: `9243eda`.
> **Current live state (2026-05-20):** revision `--0000111`, `MCP_AUTH_MODE=zendesk` (Architecture C — per-user Zendesk OAuth on prod Zendesk).
> These are constraints a **security reviewer or on-call operator** must know about. Each was a deliberate trade-off recorded in an ADR.

---

## RISK-001 — `/mcp/dev` pointed at production Zendesk with write tools exposed

**Severity:** High (for ongoing operation)
**Source:** ADR-011
**Still current:** Yes — revision `--0000111` live

`/mcp/dev` is currently authenticated against `hotschedules.zendesk.com` (prod Zendesk) via prod OAuth client `45458893611149`. Write tools — `create_it_ticket`, `update_ticket`, `create_article`, `update_article`, `create_release_note` — are fully exposed. There is **no `TOOLS_PRESET=read_only` and no Zendesk OAuth scope restriction.** Read-only behaviour is enforced by operator discipline only.

**Root cause:** Sandbox Zendesk `hotschedules1760632913.zendesk.com` has broken SAML (`/access/saml` → 302 `/hc/restricted`), blocking end-to-end Architecture C validation on sandbox. Prod Zendesk OAuth was wired in as an unblock (ADR-011).

**Revert triggers (ADR-011):**
- (a) Stefan/Entra admin fixes sandbox SAML → flip `MCP_DEV_ENVIRONMENT=SANDBOX1`
- (b) Test completes and prod pointer is no longer needed
- (c) Any incident traceable to this configuration

**Revert command:**
```bash
az containerapp update -n fourth-zendesk-mcp-server -g fourth-ai-prod \
  --set-env-vars "MCP_DEV_ENVIRONMENT=SANDBOX1"
```

**Implementation reference:** `src/server.py:_create_dev_server_zendesk_oauth()`; `src/zendesk_token_verifier.py:ZendeskOAuthProxy`.

---

## RISK-002 — `/mcp/prod` uses a shared service-account API token (broad Zendesk privilege)

**Severity:** Medium (by design; known since ADR-003)
**Source:** ADR-003; `~/Documents/ObsidianVault/Infrastructure/Zendesk API.md`
**Still current:** Yes — `/mcp/prod` unchanged across all architecture iterations

All Zendesk API calls on the `/mcp/prod` path are authenticated as `Lukasz.Pelcner@fourth.com` using a long-lived API token. This account has full Zendesk agent permissions.

**Blast radius of token leak:** Any holder of the token can read and write all Zendesk tickets, articles, and community posts as this user. No per-user granularity — revocation requires rotating the token and updating the Key Vault secret + Container App env var.

**Vault note:** The email is marked "temporary — should move to a dedicated service account." A dedicated `Fourth MCP Service` Zendesk user would isolate the blast radius.

**Rotation:** Manual. No automated rotation exists. Calendar reminder is the only control.

**Implementation reference:** `src/zendesk_client.py` (reads `ZENDESK_EMAIL`, `ZENDESK_API_TOKEN`).

---

## RISK-003 — No Zendesk SAML/JWT SSO on `hotschedules.zendesk.com`

**Severity:** Medium (architectural constraint)
**Source:** ADR-015, ADR-011
**Still current:** Yes — carried constraint from 2026-04-22 onwards

The prod Zendesk tenant has no SAML, JWT SSO, or Google Apps SSO configured. `/access/saml` and `/access/jwt` return 404 or redirect to unauthenticated pages. This was the root blocker for Architecture E (JWT SSO Remote Login URL) and the reason Architecture F was adopted briefly before this PR returned to Architecture C.

**Consequence for Architecture C (live now):** Users on `/mcp/dev` who do not have a Zendesk-specific agent password cannot authenticate. They must use the "Switch to agent sign-in" toggle and set one, or be pre-created by a Zendesk admin.

**Consequence for Architecture E (dormant):** `src/zendesk_sso_route.py` and `src/zendesk_jwt_sso.py` are compiled in but register only when `ZENDESK_JWT_SSO_SECRET` is present (currently absent). The route is a no-op in all current deployments.

**Who can unblock:** Zendesk global admin (Stefan Nikolov) would need to enable JWT SSO and provide a shared secret. Declined in prior discussions.

---

## RISK-004 — Zendesk audit log shows service account as API submitter (under Architecture F)

**Severity:** Low-Medium (compliance concern)
**Source:** ADR-015
**Still current:** Conditional — applies when `MCP_AUTH_MODE=entra` (Architecture F). Architecture F is the code default in this PR but dormant in production. Currently NOT an active risk on the live revision.

Under Architecture F, all Zendesk API calls use the service-account credential. Per-user attribution is injected into ticket `requester`, `comment.author_id`, and article `author_id`. However, Zendesk's internal audit chain records the API submitter as the service account, not the user. A Zendesk admin inspecting raw API logs sees `Lukasz.Pelcner@fourth.com` for every action.

Visible ticket UI shows the correct requester and comment author. Zendesk also renders a "Submitted by Lukasz Pelcner on behalf of the author" badge on comments (Zendesk's anti-impersonation disclosure — not suppressible without SSO federation).

**Mitigations (not yet implemented):**
- Dedicated `Fourth MCP Service` Zendesk user with its own API token
- Architecture E (JWT SSO) — enables true Zendesk-level identity; blocked on admin
- Accept it

**Current relevance:** Eliminated by Architecture C deployment. Returns if `MCP_AUTH_MODE` flips back to `entra`.

---

## RISK-005 — First-time Zendesk users get silent attribution fallback (under Architecture F)

**Severity:** Low
**Source:** ADR-015
**Applies when:** `MCP_AUTH_MODE=entra` (currently dormant)

When a new Fourth employee whose email is not yet in Zendesk calls a write tool under Architecture F, `ZendeskUserResolver` returns `None`. `apply_ticket_attribution` / `apply_article_attribution` silently no-op — the ticket is created with the service account as both submitter and requester. No error raised; no user notification.

**Mitigation:** Zendesk auto-creates user records on email receipt; subsequent calls succeed. Pre-existing onboarding or a Zendesk welcome ticket would pre-populate the record.

---

## RISK-006 — Cosmos DB OAuth store: mock-only test coverage, no emulator

**Severity:** Low
**Source:** ADR-010
**Still current:** Yes

`src/storage/cosmos_store.py` is covered by mock-based unit tests only. The Microsoft Cosmos DB emulator is amd64-only and unreliable on Apple Silicon. No CI-gated integration tests against real Cosmos.

**Compensating controls:**
- One-shot manual smoke test (put/get/delete) at initial provisioning
- Azure MCP server can query the real `oauth_state` container for live inspection
- Any material change to the adapter should re-run the manual smoke test before merge

**Accepted risk (ADR-010):** "A change to the adapter would warrant re-running the manual smoke test before merge. Not gated by CI — accepted risk at our scale."

---

## RISK-007 — Entra client secret rotation is manual; Copilot Studio connectors break on expiry

**Severity:** Medium
**Source:** ADR-007
**Still current:** Yes

The Entra app `79da6be7-9ea8-4e39-8edc-6863da932f2b` client secret is stored in:
- Azure Key Vault as `entra-client-secret`
- Power Platform connector config (each connector instance has its own copy)

Expiry causes silent Copilot Studio connector failures — users see "unable to sign in." No automated rotation. Quarterly calendar reminder is the only control.

**Rotation procedure:** Update Key Vault secret → trigger Container App revision restart → update each Copilot Studio connector's secret field manually.

---

## RISK-008 — Prod Zendesk OAuth client secret transmitted via Slack

**Severity:** Medium (historical — from ADR-011)
**Source:** ADR-011
**Still current:** Partially — secret is in Key Vault (`zendesk-prod-oauth-secret`); Slack transmission is a historical fact

The prod Zendesk OAuth client secret was transmitted via Slack by Stefan when prod Zendesk OAuth was wired up. Not rotated since. Stored in Key Vault; rotation requires Stefan to regenerate.

**When to rotate:** (a) When the `MCP_DEV_ENVIRONMENT=PROD` temporary state is reverted, or (b) proactively if the Slack channel is accessible to users outside the team.

---

## RISK-009 — Ideas data up to 1 week stale; ETag race on initial load

**Severity:** Low
**Source:** ADR-004, ADR-012
**Still current:** Yes

The Ideas cache is a weekly snapshot. Vote/comment counts and new posts may be up to 7 days behind. The four Ideas tools (`list_ideas`, `get_idea`, `search_ideas`, `ideas_analytics`) operate on this snapshot.

A minor ETag race exists: initial blob load (`download_blob` + `get_blob_properties`) makes two separate HTTP requests. An intervening Monday refresh would store the wrong ETag with correct content, causing the next 12:00 UTC check to skip a reload. Operationally negligible at weekly cadence (tracked as a follow-up in ADR-012).

---

## RISK-010 — Fail-closed safelist protects only the deprecated `create_ticket`, not the active write tools

**Severity:** Medium (architectural gap)
**Source:** ADR-014 (post-v3.10.3 flip at commit `ebaa612`); this PR audit
**Still current:** Yes

`_FAIL_CLOSED_TOOLS = frozenset({"create_ticket"})` in `src/server.py:23` ensures that if `tools.config.json` is absent or unparseable at startup, the deprecated `create_ticket` is blocked. **However, the safelist does not self-extend to the currently-active write tools.** If config load fails, the fallback defaults (`server.py:42`) set `disabled = _FAIL_CLOSED_TOOLS` — meaning `create_it_ticket`, `update_ticket`, `create_article`, `update_article`, and `create_release_note` would all register (their default `enabled` state in the fallback path is True unless explicitly disabled).

In practice, a corrupt `tools.config.json` would:
- Block `create_ticket` (the deprecated tool) ✓
- **Allow `create_it_ticket` and other write tools** to register with their default behaviour ✗

This is correct for `create_it_ticket` specifically (it has its own form validation and is the intended active tool), but a future operator adding a higher-risk write tool would need to explicitly add it to `_FAIL_CLOSED_TOOLS` to get the protection.

**Mitigation:** If a future write tool needs fail-closed protection, add it to the frozenset alongside `create_ticket`. Document in code comments why.

---

## RISK-011 — Live 429 handling missing on non-Ideas tools

**Severity:** Low
**Source:** `~/Documents/ObsidianVault/Infrastructure/Zendesk API.md`
**Still current:** Yes

The Ideas export script (`export_ideas.py`) has exponential backoff on 429s. The live MCP tool paths (`src/tools/tickets.py`, `src/tools/help_center.py`, etc.) do not. Current traffic is low enough that this hasn't triggered, but a burst of parallel tool calls from multiple Copilot Studio agents could exhaust the per-minute quota.

**Mitigation:** Add a `retry-after`-aware 429 handler in `src/zendesk_client.py` before any broad rollout.

---

## RISK-012 — Zendesk Bearer token format is opaque; revocation is immediate but tokens cannot be inspected

**Severity:** Informational (architectural property, not a defect)
**Source:** Zendesk OAuth implementation; observed behavior of `ZendeskTokenVerifier`
**Still current:** Yes

Architecture C uses Zendesk's opaque OAuth tokens (not JWTs). Implications:
- **Pro:** Revocation is instant — when Zendesk invalidates a token, the next `/api/v2/users/me` validation returns 401 and the user is forced to re-authenticate.
- **Con:** Tokens cannot be inspected without a Zendesk API call. There is no way to read claims (email, role, scopes) locally; every validation needs a Zendesk round-trip (mitigated by 5-min in-memory cache).
- **Validation cost:** ~50-100ms per first-time call, near-zero for cached.
- **No offline validation possible** if Zendesk is unreachable. The 5-min cache is the only resilience window.

This is a deliberate Zendesk design choice; not within our control. Documented for reviewer awareness.

---

## RISK-013 — `MCP_AUTH_MODE` env var can be silently cleared by a Container App update

**Severity:** Medium
**Source:** This PR (architecture-flip behaviour audit)
**Still current:** Yes

The auth-mode dispatch is a single env var: `MCP_AUTH_MODE=zendesk` selects Architecture C; unset or any other value falls back to Architecture F (the code default, see `src/server.py:create_dev_server`). If an operator runs `az containerapp update --set-env-vars` with a partial env-var list that omits `MCP_AUTH_MODE`, **Azure Container Apps replaces the entire env-var collection** and the var is removed. The next revision boots into Architecture F silently.

Consequences:
- Live `/mcp/dev` users get their Zendesk Bearer rejected by `AzureProvider` and are forced through the Microsoft picker flow.
- Reads silently regain service-account-scope visibility (RISK-002 amplification).
- No alarm fires; the change is only visible in revision env vars.

**Mitigations:**
- Always include `MCP_AUTH_MODE=zendesk` in every `az containerapp update --set-env-vars` call, even when not changing auth.
- The startup log emits the resolved auth mode (`src/server.py:875`) — check via `az containerapp logs show --revision <name>` after any update.
- Prior revisions stay as warm-rollback targets; flipping back is ~30 seconds via traffic shift.

**Detection:** `az containerapp revision show --revision <name> --query "properties.template.containers[0].env"` shows the bound env vars. Should be run before any traffic shift.

---

## RISK-014 — No structured audit log of MCP tool calls

**Severity:** Medium (compliance / forensics)
**Source:** This PR (omission audit)
**Still current:** Yes

The server does not emit a structured audit log of MCP tool invocations. There is no per-call record of:
- Which authenticated user (Zendesk OAuth identity) called the tool
- When the call happened
- What arguments were passed
- Whether the call succeeded or failed (and why)

Container App `stdout` from `print(...)` calls in `src/server.py` and `src/zendesk_client.py` flows to Azure Log Analytics, but these are debug-flavored and not designed for security audit. The Zendesk side records the API call but cannot easily be correlated back to "user X invoked `create_it_ticket` via MCP" — Zendesk only sees a Bearer token hitting its REST API.

**Consequences:**
- Forensic investigation of misuse (e.g. someone exfiltrating ticket data via repeated `list_tickets`) requires correlating Cosmos OAuth tokens to user identities at call time and joining against any Zendesk-side API audit.
- No way to alert on patterns like "user invoked write tool N times in M minutes."
- Compliance asks (GDPR / SOC2) for "who accessed what data" cannot be answered from MCP logs alone.

**Mitigations (not yet implemented):**
- Level A (~1h work): add a structured JSON log line per tool entry/exit in `src/main.py` middleware or via a FastMCP hook. Route to Azure Log Analytics with a custom table and Kusto saved queries.
- Level B (~half day): Application Insights wiring + Azure Workbook dashboard.
- Level C (~1 day): dedicated Cosmos `tool_usage` container for queryable history.

---

## Historical risks (no longer active)

| Risk | Was active | Resolved by |
|---|---|---|
| File-based OAuth state wiped on deploy (users re-auth on every deploy) | v3.7.x and earlier | ADR-008 — Cosmos persistence, live since v3.8.0 |
| `create_it_ticket` could register via broken config (fail-open) | Pre-v3.9.0 | ADR-014 — `_FAIL_CLOSED_TOOLS` frozenset |
| `id`/`type` parameter rename breaks saved Copilot Studio actions | Pre-v3.9.0 | ADR-014 — compat shim for legacy aliases |
| OAuth state resources in `lukasz-ai-experiments` (personal RG) | 2026-04-28 → 2026-04-29 | ADR-009 (superseded) — resources moved to `fourth-ai-prod` |
| `ZendeskOAuthProxy` Zendesk sign-in form blocks most Fourth users | v3.8.0 → v3.9.0 (Arch C era 1) | Briefly resolved by Architecture F (ADR-015); now re-accepted in Architecture C for the IT-support audience that all have agent accounts |
| Privilege escalation: every Entra user reads service-account-scoped Zendesk data | v3.10.0 → v3.10.4 (Arch F) | This PR — Architecture C restored, per-user Bearer flows through |

---

_Vault sources consulted: `~/Documents/ObsidianVault/Decisions/ADR-001` through `ADR-015`, `~/Documents/ObsidianVault/OAuth/`, `~/Documents/ObsidianVault/Infrastructure/Zendesk API.md`, `~/Documents/ObsidianVault/Architecture/Persistent OAuth Storage.md`, `~/Documents/ObsidianVault/Migration/Migration plan.md`._
