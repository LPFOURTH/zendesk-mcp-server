# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN
```

## Running the Server

**stdio mode** (used by Claude Code / Cursor via `.mcp.json`):
```bash
python -m src.main
```

**HTTP mode** (local Streamable HTTP on port 8000):
```bash
MCP_TRANSPORT=http python -m src.main
# Health check: http://localhost:8000/health
# MCP endpoint: http://localhost:8000/mcp
```

**Docker:**
```bash
docker build -t zendesk-mcp .
docker run -p 8000:8000 -e ZENDESK_SUBDOMAIN=... -e ZENDESK_EMAIL=... -e ZENDESK_API_TOKEN=... zendesk-mcp
```

## Tests

```bash
cd zendesk-mcp-server
.venv/bin/python -m pytest tests/ -q
```

148 tests across 12 files. Includes: tool gating, attribution gating per architecture, OAuth proxy URL handling, Cosmos KV store, Ideas cache, Architecture E JWT-SSO (dormant), Architecture C revert behaviour.

## Architecture

```
MCP Client (Claude Code / Claude Desktop / Copilot Studio / Cursor)
         │
         │  stdio (local)  or  Streamable HTTP (remote)
         ▼
    src/main.py          — transport dispatch; ASGI middleware extracts
                           Authorization + zendesk-* headers into contextvars
         │
         ▼ path routing rewrites /mcp/dev and /mcp/prod to /mcp
         │
    src/server.py        — three server factories:
         │                   • create_prod_server()     → Architecture B (API key)
         │                   • create_dev_server()      → dispatch on MCP_AUTH_MODE
         │                       └─ _create_dev_server_zendesk_oauth()  (Arch C, live)
         │                       └─ _create_dev_server_entra()           (Arch F, dormant)
         │                   • create_server()          → stdio mode
         ▼
    src/tools/*.py       — 14 async functions across 4 modules under `with_ideas` preset
         ▼
    src/zendesk_client.py — singleton httpx client; per-request auth + target
                            resolved from contextvars → env vars → ENVIRONMENTS
```

**Path-based routing** (HTTP mode): `/mcp/dev` and `/mcp/prod` rewrite to `/mcp` with `zendesk-environment` injected. The two paths share tool code but differ in auth model.

**Current live deployment (2026-05-14 → ):** revision `--0000111` on image `v3.10.5`. `MCP_AUTH_MODE=zendesk`, `MCP_DEV_ENVIRONMENT=PROD` → Architecture C on `/mcp/dev`. Architecture F is the code default but unused at this revision.

See `docs/DESIGN_DECISIONS.md` for the full rationale, `docs/LIMITATIONS.md` for accepted risks.

## Key Files

- **`src/main.py`** — entry point; ASGI `_make_context_middleware` extracts per-request headers (`Authorization`, `zendesk-subdomain`, `zendesk-base-url`, `zendesk-environment`) and writes them to `contextvars`
- **`src/server.py`** — three factory functions:
  - `create_prod_server()` (line ~698) → Architecture B (`/mcp/prod`, no auth)
  - `_create_dev_server_zendesk_oauth()` (line ~812) → Architecture C (Zendesk OAuth, **live**)
  - `_create_dev_server_entra()` (line ~736) → Architecture F (Entra OAuth, dormant)
  - `create_dev_server()` (line ~883) → dispatch on `MCP_AUTH_MODE`
  - `create_server()` (line ~897) → stdio mode alias for `_create_base_server`
- **`src/zendesk_client.py`** — `ZendeskClient` singleton; `_get_target()` + `_get_auth_header()` resolve per-request from `contextvars` with env-var fallback; built-in `RateLimiter` (default 200 req/min sliding window)
- **`src/zendesk_token_verifier.py`** — `ZendeskOAuthProxy` (Arch C), `EntraOAuthProxy` (Arch F), `ZendeskTokenVerifier` (validates Zendesk opaque tokens via `/api/v2/users/me`, 5-min cache)
- **`src/attribution.py`** — Architecture-F-only attribution helpers; gated off under Arch C (see `docs/DESIGN_DECISIONS.md` B7)
- **`src/storage/cosmos_store.py`** — Cosmos KV adapter for OAuth state persistence, Fernet-encrypted at value level (ADR-008)
- **`src/ideas_cache.py`** — Blob-backed Ideas cache loader; daily 12:00 UTC ETag check
- **`src/request_context.py`** — `contextvars` definitions (`authorization_var`, `zendesk_subdomain_var`, etc.)
- **`src/constants.py`** — `ENVIRONMENTS` dict + `IT_FORM_CONFIG` (prod IT-form field IDs); UK/US release-note HTML templates
- **`tools.config.json`** — per-tool enable/disable; presets (`read_only`, `full`, `tickets_only`, `articles_only`, `with_ideas`, `ideas_only`) activated via `TOOLS_PRESET` env var

## Authentication

The server has **three auth surfaces**, selected by URL path and env var:

### `/mcp/dev` under Architecture C (current live)

`MCP_AUTH_MODE=zendesk` → `_create_dev_server_zendesk_oauth()`. Each user authenticates via Zendesk OAuth in their browser (Dynamic Client Registration → authorize → token). The user's own Zendesk Bearer is forwarded on every API call. No service account on the request path. Zendesk's role-based access controls enforce per-token visibility.

OAuth state (DCR client IDs, encrypted tokens) persisted in Cosmos DB (`oauth_state` container).

### `/mcp/dev` under Architecture F (code default, dormant)

`MCP_AUTH_MODE=entra` (or unset) → `_create_dev_server_entra()`. Each user authenticates via Microsoft Entra (silent picker for M365 sessions). The server validates the Entra JWT against Microsoft's JWKS, then makes all Zendesk API calls using the service-account credential. Per-user attribution is injected into `requester` / `comment.author_id` / `author_id` payload fields. Trade-off: read paths return service-account-scope data regardless of user role.

### `/mcp/prod` — Architecture B

No OAuth. Each request carries its own Zendesk credentials in the `Authorization` header (e.g., `Basic <base64 email:apitoken>`). The ASGI middleware stores it in `authorization_var`; `ZendeskClient` forwards it verbatim. Used for headless automation and Copilot Studio service-principal flows.

### stdio mode (local)

No `Authorization` contextvar → client constructs `Basic` token from `ZENDESK_EMAIL` + `ZENDESK_API_TOKEN` env vars.

## Tools

14 tools live in `src/tools/` as plain `async def` functions, registered via `server.py` filtered through `tools.config.json` and `DISABLED_TOOLS`. **No delete operations** by design.

| Tool | Module | Notes |
|------|--------|-------|
| `list_tickets` | tickets.py | Status filter uses Zendesk search API internally |
| `get_ticket` | tickets.py | Includes comments; description truncated to 500 chars |
| `create_it_ticket` | tickets.py | **Active write path** — IT-form-aware (form `45108529620365`). Fail-closed-safelisted. |
| `update_ticket` | tickets.py | `internal_note` flag for private agent notes |
| `create_ticket` | tickets.py | **Disabled** in `tools.config.json` since v3.10.3 — `create_it_ticket` supersedes |
| `list_articles` | help_center.py | |
| `get_article` | help_center.py | Body truncated to 2000 chars |
| `create_article` | help_center.py | Author attribution gated on `MCP_AUTH_MODE` |
| `update_article` | help_center.py | Splits into translation + metadata API calls; no attribution injection (intentional) |
| `search` | search.py | Infers ticket vs. article scope; normalizes query |
| `create_release_note` | release_notes.py | Markdown → UK/US HTML template. Hardcoded author_id gated on `MCP_AUTH_MODE` |
| `list_ideas` | community.py | Pre-computed cache, weekly refresh |
| `get_idea` | community.py | |
| `search_ideas` | community.py | |
| `ideas_analytics` | community.py | Aggregates over the cached snapshot |

`tools.config.json` schema: each tool has `enabled` (bool), `_description`, `_usage`, optional `_disable_reason` and `_enabled_in` annotations. Presets (`with_ideas` is the deployed default) bulk-enable groups.

## Deployment

Live deployment (Azure North Europe):

- Resource group: `fourth-ai-prod`
- Managed environment: `fourth-ai-env`
- Container Registry: `fourthzendeskmcp`
- Container App: `fourth-zendesk-mcp-server`
- Cosmos DB account: `cosmos-db-ai-enablement` (database `mcp`, container `oauth_state`)
- Key Vault: `mcp-kv-ai-enablement`
- Storage account (Ideas): `fourthzendeskideas`

Build/deploy via `deployment/azure/scripts/2-build-and-deploy.sh`. Pre-reqs: `4-provision-oauth-storage.sh` must have run once. CI/CD via `.github/workflows/release.yml` on git tags.

Power Platform connector assets in `connector/` — `connectionparameters-entra.json` is the active OAuth 2.0 spec; legacy `*-oauth.json` files kept for revert.
