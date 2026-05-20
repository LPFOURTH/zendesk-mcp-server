# Design Decisions

> Compiled from Obsidian ADRs. Branch: PR #3 to `fourth/main`. Tip: `9243eda`.
> **Current live state (2026-05-20):** revision `--0000111`, `MCP_AUTH_MODE=zendesk` → Architecture C (per-user Zendesk OAuth). Architecture F is the **code default** but **dormant** at the running container.

---

## Section A — Decision register

| ADR | Title | Date | Status | One-line summary |
|---|---|---|---|---|
| ADR-001 | Python over Node.js | 2026-Q1 | Active | Single-language stack, mature OAuth/JWT libs, team skill alignment |
| ADR-002 | FastMCP over hand-rolled server | 2026-Q1 | Active | `@mcp.tool()` decorator + built-in SSE + OIDC proxy saves ~70 lines of custom OAuth |
| ADR-003 | Architecture B (Entra → service-account Zendesk) | 2026-Q1 | Historical (superseded by F, then current C deployment) | Adopted Entra for user identity while deferring per-user Zendesk creds |
| ADR-004 | Pre-computed Ideas cache | 2026-Q1 | Active | Weekly full-dataset export to JSON/blob, served from memory; avoids community-API rate limits |
| ADR-006 | MCPB Extension Bundle | 2026-04 | Proposed (not yet implemented) | Ship `.mcpb` extension + deeplink buttons; eliminates manual JSON edits for Claude Desktop / Cursor |
| ADR-007 | Copilot Studio client secret over managed identity | 2026-04-17 | Active | Managed identity fails self-app token requests (`AADSTS90009`); client secret is stable and debuggable |
| ADR-008 | Cosmos DB serverless for persistent OAuth storage | 2026-04-28 | Active | Org-standard datastore; serverless billing matches Container App scale-to-zero; Fernet at value level |
| ADR-009 | Sandbox RG for OAuth storage (initial provision) | 2026-04-28 | Superseded 2026-04-29 (moved to `fourth-ai-prod`) | Resources moved by Boyan; endpoint URLs unchanged |
| ADR-010 | Mock-based tests with live MCP inspection | 2026-04-28 | Active | Cosmos emulator unreliable on Apple Silicon; mock-only tests + Azure MCP live queries as compensating control |
| ADR-011 | Temporary prod Zendesk OAuth on `/mcp/dev` | 2026-04-29 | Active (current live state) | Sandbox SAML broken → pointed `/mcp/dev` at prod Zendesk OAuth to unblock end-to-end Architecture C test |
| ADR-012 | Blob-backed Ideas refresh | 2026-04-30 | Active | Replaced silently-failing in-container `az acr build` cron with a Storage Account hand-off |
| ADR-014 | Compat shim + fail-closed gate (v3.9.0) | 2026-05-11 | Active | Backwards-compat `id`/`type` aliases for renamed ticket params; `create_it_ticket` gated fail-closed |
| ADR-015 | Architecture F — Entra OAuth + service-account Zendesk | 2026-05-11 | Code default; dormant at current revision | Replaced Zendesk OAuth screen with Microsoft picker; per-user attribution via payload injection |

ADR-005 and ADR-013 do not exist in the vault (numbering jumps). All ADR source files live at `~/Documents/ObsidianVault/Decisions/`.

---

## Section B — Active design decisions

### B1. Python + FastMCP as the implementation stack

**Decision:** Python 3.11, FastMCP framework.

**Context (ADR-001, ADR-002):** The original prototype was Node.js. FastMCP matured to include one-decorator tool registration, built-in SSE/Streamable HTTP, and an OIDC proxy that replaced ~70 lines of hand-rolled Starlette routes. The Ideas export pipeline (`export_ideas.py`) was already Python; a single-language stack reduced cognitive overhead. Python's `PyJWT`, `msal`, and `azure-identity` libraries were more battle-tested for Entra OAuth than Node equivalents at evaluation time.

**Trade-off accepted:** Deploy times ~2 min vs ~1 min for Node. Dependency on FastMCP upstream release cadence for MCP-spec updates (typically days).

**Implementation:** `src/server.py`, `src/main.py`. Docker base: `python:3.11-slim`.

---

### B2. Dual-path routing: `/mcp/prod` (Architecture B) and `/mcp/dev` (Architecture C or F)

**Decision:** The ASGI entrypoint (`src/main.py`) mounts two FastMCP servers under separate URL prefixes. Auth model for `/mcp/dev` is selected at runtime via `MCP_AUTH_MODE`.

**Context:** `/mcp/prod` is stable API-key auth — never changed across architecture iterations, used for automation and Copilot Studio service-principal flows. `/mcp/dev` has evolved through three auth architectures (B → C → F → C) without touching `/mcp/prod`. The env-var dispatch (`src/server.py:create_dev_server()`, line ~883-893) makes architecture transitions a 30-second `az containerapp update --set-env-vars` with no redeploy.

**Current live state:** `MCP_AUTH_MODE=zendesk` → `_create_dev_server_zendesk_oauth()` → Architecture C (per-user Zendesk OAuth).
**Code default in this PR:** `MCP_AUTH_MODE=entra` → `_create_dev_server_entra()` → Architecture F.

---

### B3. Per-user Zendesk OAuth (Architecture C) — current live auth model

**Decision (ADR-011):** `/mcp/dev` uses `ZendeskOAuthProxy` (FastMCP's `OAuthProxy` subclass) to issue a per-user Zendesk OAuth flow. Each user authenticates to `hotschedules.zendesk.com` with their own credentials; the resulting Bearer is used for that user's Zendesk API calls. The service-account credentials (`ZENDESK_EMAIL` / `ZENDESK_API_TOKEN`) remain bound to the container as env vars but are **not used for authenticated `/mcp/dev` calls under Arch C** — `zendesk_client.py:223-244` forwards the user's Bearer from the request context. Service-account fallback exists for stdio mode and background calls outside a request context (see `docs/LIMITATIONS.md` RISK-013).

**Why C over F:**
- Per-user Zendesk-side audit chain (the API caller IS the user)
- Zendesk's own role-based access controls apply per token — no MCP-side scope enforcement needed
- Eliminates the privilege-escalation read pattern in F (where every Entra user reads what the service account can read)

**Context:** ADR-003 identified Architecture C as the ideal end-state but deferred pending OAuth client provisioning. ADR-011 documents pointing `/mcp/dev` at **prod** Zendesk (`hotschedules.zendesk.com`, OAuth client `45458893611149`) while sandbox SAML remains broken (`hotschedules1760632913` → `/access/saml` returns 404 or 302 to `/hc/restricted`).

**Accepted UX trade-off:** Users without Zendesk agent credentials cannot authenticate. End-users of the platform must toggle to "agent sign-in" or be pre-created by a Zendesk admin. This is the constraint that motivated Architecture F in the first place; revisited in Architecture C because the affected user population (the IT support team) all have agent accounts.

**Revert triggers (from ADR-011):**
- (a) Stefan/Entra admin fixes sandbox SAML → flip `MCP_DEV_ENVIRONMENT=SANDBOX1`
- (b) Test concludes and prod pointer is no longer needed
- (c) Any prod-data incident traceable to this configuration

**Implementation:** `src/zendesk_token_verifier.py:ZendeskOAuthProxy`, `src/server.py:_create_dev_server_zendesk_oauth()`. Env: `MCP_AUTH_MODE=zendesk`, `MCP_DEV_ENVIRONMENT=PROD`, `ZENDESK_PROD_OAUTH_CLIENT_ID`, `ZENDESK_PROD_OAUTH_SECRET`.

---

### B4. Cosmos DB serverless for OAuth token persistence

**Decision (ADR-008):** FastMCP's default file-based OAuth state store is replaced by `CosmosKeyValueStore`, wrapped in `FernetEncryptionWrapper`. Every OAuth token, DCR record, and in-flight state blob survives pod restarts and deploys.

**Context:** Without persistence, every Container App deploy forces all active users to re-authenticate. Three backends were compared: Redis (~$16/mo, 1-day effort), Postgres (~$12/mo, weeks of adapter work), Cosmos serverless (~$2-10/mo RU-priced, ~3 days of adapter work). Redis was the fastest path; Cosmos was chosen as the org-standard datastore on architect recommendation despite the higher engineering cost.

**Key details:**
- Account: `cosmos-db-ai-enablement` in `fourth-ai-prod`
- Database/container: `mcp` / `oauth_state`, partition key `/pk`
- Indexing disabled (write-RU saving ~50%)
- Per-document TTL via `py-key-value-aio` semantics
- Authentication: Container App system-assigned managed identity → Cosmos built-in data-contributor role (no connection string)
- Latency: 5-15 ms per token read (vs <2 ms for Redis)

**Implementation:** `src/storage/cosmos_store.py`. Tests: `tests/test_cosmos_store.py` (mock-based; see ADR-010 / `docs/LIMITATIONS.md` RISK-006).

---

### B5. Blob-backed Ideas cache with weekly refresh

**Decision (ADR-004, ADR-012):** Ideas data (~1,600 posts, ~4 MB) is pre-exported weekly and served from in-memory RAM. The blob-backed refresh model (ADR-012) replaced a silently-failing in-container `az acr build` cron with a Storage Account hand-off.

**Architecture:**
1. Monday 06:00 UTC: `fourth-ideas-refresh` Container Apps Job fetches from Zendesk Community API, uploads to `fourthzendeskideas/ideas-data/ideas_latest.json`.
2. MCP servers at boot: load from blob first, fall back to image-bundled `ideas_latest.json` on failure.
3. Daily 12:00 UTC: in-process thread-safe ETag check reloads if changed.

**Why pre-computed:** Zendesk community API is aggressively rate-limited; AI agents compose multiple queries per session; data changes slowly (weekly for votes/comments, daily for new posts).

**Accepted trade-off:** Data up to 1 week stale. A small ETag race exists at initial load (two HTTP calls for download + property fetch). Operationally negligible at weekly cadence — tracked as a follow-up.

**Implementation:** `src/ideas_cache.py`. Storage account: `fourthzendeskideas`. Env vars: `IDEAS_BLOB_ACCOUNT`, `IDEAS_BLOB_CONTAINER`, `IDEAS_BLOB_NAME`.

---

### B6. Compat shim + fail-closed gate for write tools

**Decision (ADR-014):** Two pre-merge guards are permanently in the codebase:

1. **Compat shim** in `src/tools/tickets.py`: `get_ticket`, `create_ticket`, `update_ticket` accept both the canonical `ticket_id`/`ticket_type` (post Boyan's PR #1 rename) and legacy aliased kwargs. Canonical wins on conflict; missing required param raises `ValueError` before any Zendesk call. Preserved because Copilot Studio saved actions and prompt-cached tool-use patterns hard-code the old `id=` parameter.

2. **Fail-closed safelist** in `src/server.py`: `_FAIL_CLOSED_TOOLS = frozenset({"create_ticket"})` ensures that if `tools.config.json` is missing, corrupt, or unparseable, the legacy `create_ticket` is never registered. Earlier versions (v3.9.0) protected `create_it_ticket` instead when its prod-form fields were unverified; the protection was flipped at commit `ebaa612` once the prod form was confirmed working. Under v3.10.3+ the active write path is `create_it_ticket`; the deprecated `create_ticket` is what we want never re-enabled by accident.

**Current tool gate state (v3.10.3+):** `create_it_ticket` is `enabled: true` in `tools.config.json` and is the active IT-ticket write path. `create_ticket` is `enabled: false` and is additionally in `_FAIL_CLOSED_TOOLS` so it cannot register even if the config file is broken.

---

### B7. Per-user attribution gates (this PR — Architecture C)

**Decision:** Write tools that inject `requester` / `comment.author_id` / `author_id` into Zendesk payloads (the "Architecture F attribution helpers") are gated behind `os.environ.get("MCP_AUTH_MODE", "entra") == "entra"`. Under Architecture C (`MCP_AUTH_MODE=zendesk`), these injections are skipped entirely.

**Context:** Under Architecture F, the Zendesk API caller is the service account; we must explicitly attribute the ticket/article to the authenticated Entra user via payload fields. Under Architecture C, the Zendesk API caller **is** the user — Zendesk attributes natively. Server-side override on top is redundant and can return 422 when the user lacks `set_author_on_create` permission.

**Six gated call sites (approximate line refs — see `src/tools/*.py` for current):**
- `src/tools/tickets.py` — `create_ticket` requester injection
- `src/tools/tickets.py` — `create_ticket` comment.author_id injection
- `src/tools/tickets.py` — `update_ticket` comment.author_id injection
- `src/tools/tickets.py` — `create_it_ticket` requester + comment.author_id injection
- `src/tools/help_center.py` — `create_article` author_id injection
- `src/tools/release_notes.py` — `create_release_note` hardcoded `env_config["author_id"]`

**Default-to-entra:** A missing `MCP_AUTH_MODE` env var preserves Architecture F semantics (regression guard against accidentally dropping attribution in prod).

---

### B8. Copilot Studio connector: client secret, not managed identity

**Decision (ADR-007):** Copilot Studio custom connectors use a client secret for the Entra app `79da6be7-...` rather than managed identity.

**Root cause of managed-identity failure:** When the connector's Client ID equals the Resource URL app ID (same Entra app for both), Entra requires the resource as a raw GUID. Power Platform auto-prepends `api://` and cannot be overridden — causing `AADSTS90009`. Each connector name slug also generates a unique Power Platform redirect URI that must be pre-registered in Entra (`global.consent.azure-apim.net/redirect/<slug>`).

**Operational consequence:** Client secret requires quarterly rotation; calendar reminder is the only control. Stored in Power Platform's connector config (encrypted at rest).

---

## Section C — See also

- `docs/LIMITATIONS.md` — accepted risks for security reviewers
- `docs/zendesk-mcp-workflows.html` — interactive sequence diagram of the current Architecture C flows
- Vault sources: `~/Documents/ObsidianVault/Decisions/ADR-*.md`, `~/Documents/ObsidianVault/OAuth/Architecture C (future).md`, `~/Documents/ObsidianVault/Architecture/Persistent OAuth Storage.md`, `~/Documents/ObsidianVault/Migration/Migration plan.md`
