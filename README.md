# Zendesk MCP Server

Fourth's hardened Zendesk MCP server. Backs Claude Code, Claude Desktop, Copilot Studio, and other MCP clients with tools for tickets, Help Center articles, community Ideas, and IT-ticket creation. Live at `https://fourth-zendesk-mcp-server.bluewave-95f931ef.northeurope.azurecontainerapps.io`.

## Highlights

- **14 tools** under the `with_ideas` preset (10 ticket/article/search + 4 community Ideas + `create_it_ticket` with IT-form awareness)
- **No delete operations** by design
- **Two HTTP paths with different auth models** — `/mcp/dev` per-user Zendesk OAuth (Architecture C, live), `/mcp/prod` service-account API key (Architecture B, for automation)
- **Persistent OAuth state** in Azure Cosmos DB (Fernet-encrypted); users don't re-auth across container restarts
- **Pre-computed Ideas cache** refreshed weekly from Azure Blob (~4 MB, ~1,600 posts)
- Azure Container Apps deploy + GitHub Actions release workflow

## Authentication architecture

The server runs two MCP endpoints with deliberately different auth models. Which architecture is "live" at any given time is controlled by a single env var (`MCP_AUTH_MODE`) — see `docs/DESIGN_DECISIONS.md` for the rationale and `docs/LIMITATIONS.md` for accepted risks.

| Endpoint | Architecture | Auth model | Used by |
|---|---|---|---|
| `/mcp/dev` | **C (live)** when `MCP_AUTH_MODE=zendesk` | Per-user Zendesk OAuth (browser flow). Each user's own Bearer reaches Zendesk. | Claude Code, Claude Desktop, Copilot Studio interactive |
| `/mcp/dev` | F (dormant) when `MCP_AUTH_MODE=entra` | Microsoft Entra OAuth (silent picker) + service-account Zendesk + per-user attribution injection | Code default; revert path |
| `/mcp/prod` | B | Static Zendesk API token in `Authorization: Basic` header | Headless automation, Copilot Studio service-principal flows |

`docs/zendesk-mcp-workflows.html` is an interactive sequence diagram of the live Architecture C flows (OAuth dance, `create_it_ticket`, `list_tickets`).

## Available tools

| Tool | Module | Notes |
|---|---|---|
| `list_tickets` | tickets.py | Pagination + status filter |
| `get_ticket` | tickets.py | Includes comments; description truncated to 500 chars |
| `create_it_ticket` | tickets.py | **Active write path** — IT-form-aware payload builder (form `45108529620365`) |
| `update_ticket` | tickets.py | `internal_note` flag for private agent notes |
| `create_ticket` | tickets.py | **Disabled** in `tools.config.json` since v3.10.3 (kept for revert; `create_it_ticket` supersedes) |
| `list_articles` | help_center.py | |
| `get_article` | help_center.py | Body truncated to 2000 chars |
| `create_article` | help_center.py | Author attribution gated on `MCP_AUTH_MODE` |
| `update_article` | help_center.py | Splits into translation + metadata API calls |
| `search` | search.py | Infers ticket vs. article scope |
| `create_release_note` | release_notes.py | Parses `### Functionality N` markdown → UK/US HTML template |
| `list_ideas` | community.py | Pre-computed cache, weekly refresh |
| `get_idea` | community.py | |
| `search_ideas` | community.py | |
| `ideas_analytics` | community.py | Aggregates over the cached snapshot |

Tool registration is governed by `tools.config.json` (per-tool `enabled` flag, `_disable_reason`, `_enabled_in` annotations) and the `TOOLS_PRESET` env var. The deprecated `create_ticket` is additionally pinned in a fail-closed safelist (`_FAIL_CLOSED_TOOLS = frozenset({"create_ticket"})` in `src/server.py`) so it never registers even if the config file is broken — see ADR-014 and `docs/DESIGN_DECISIONS.md` B6.

## Quick start (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN
```

### stdio mode (Claude Code / Cursor local)

```bash
python -m src.main
```

### Local Streamable HTTP

```bash
MCP_TRANSPORT=http python -m src.main
# Health: http://localhost:8000/health
# MCP:    http://localhost:8000/mcp
```

### Docker

```bash
docker build -t zendesk-mcp .
docker run -p 8000:8000 \
  -e ZENDESK_SUBDOMAIN=hotschedules \
  -e ZENDESK_EMAIL=svc@example.com \
  -e ZENDESK_API_TOKEN=… \
  zendesk-mcp
```

## Configuration

### Required (all deployments)

| Variable | Description |
|---|---|
| `ZENDESK_SUBDOMAIN` / `ZENDESK_BASE_URL` | Default Zendesk target |
| `ZENDESK_EMAIL` | Service-account email for `/mcp/prod` and background calls |
| `ZENDESK_API_TOKEN` | Service-account API token for `/mcp/prod` and background calls |

### Auth-mode dispatch (production deployment)

| Variable | Values | Description |
|---|---|---|
| `MCP_AUTH_MODE` | `zendesk` (live) \| `entra` (default, dormant) | Selects Architecture C vs F on `/mcp/dev`. See `src/server.py:create_dev_server()`. |
| `MCP_DEV_ENVIRONMENT` | `PROD` (live) \| `SANDBOX1` | Which Zendesk tenant `/mcp/dev` targets under Architecture C. Currently `PROD` per ADR-011. |
| `MCP_PUBLIC_URL` | https URL | Used by FastMCP `OAuthProxy` to build `base_url`. Required for `/mcp/dev`. |
| `TOOLS_PRESET` | `with_ideas` (live) \| `read_only` \| `full` \| `tickets_only` \| `articles_only` \| `ideas_only` | Bulk tool registration toggle. |
| `DISABLED_TOOLS` | comma-separated | Hard-disable specific tools regardless of preset. |
| `ZENDESK_RATE_LIMIT` | `200` (default) | Max Zendesk API calls per minute. |

### Architecture C (`MCP_AUTH_MODE=zendesk`) — current live

| Variable | Description |
|---|---|
| `ZENDESK_PROD_SUBDOMAIN` | When `MCP_DEV_ENVIRONMENT=PROD`: prod Zendesk subdomain (e.g. `hotschedules`) |
| `ZENDESK_PROD_OAUTH_CLIENT_ID` | Prod Zendesk OAuth client ID (`mcp-server-copilot-prod` / `45458893611149`) |
| `ZENDESK_PROD_OAUTH_SECRET` | Prod Zendesk OAuth client secret (in Key Vault as `zendesk-prod-oauth-secret`) |
| `ZENDESK_SANDBOX1_*` | Same three vars for sandbox env when `MCP_DEV_ENVIRONMENT=SANDBOX1` |
| `MCP_JWT_SIGNING_KEY` | Optional. FastMCP internal state signing. Unset → FastMCP derives a 32-byte key at boot. |

### Architecture F (`MCP_AUTH_MODE=entra`) — code default, dormant

| Variable | Description |
|---|---|
| `ENTRA_CLIENT_ID` | `79da6be7-9ea8-4e39-8edc-6863da932f2b` |
| `ENTRA_TENANT_ID` | `75cd3b18-d23a-40ee-ad06-ad4484fc72fe` |
| `ENTRA_CLIENT_SECRET` | In Key Vault as `entra-client-secret` |

### Persistent OAuth state (Cosmos DB)

| Variable | Description |
|---|---|
| `COSMOS_ENDPOINT` | `https://cosmos-db-ai-enablement.documents.azure.com:443/` |
| `MCP_STORAGE_ENCRYPTION_KEY` | Fernet key for at-rest token encryption (in Key Vault as `storage-encryption-key`) |

### Ideas cache (blob-backed)

| Variable | Description |
|---|---|
| `IDEAS_BLOB_ACCOUNT` | `fourthzendeskideas` |
| `IDEAS_BLOB_CONTAINER` | `ideas-data` |
| `IDEAS_BLOB_NAME` | `ideas_latest.json` |

### Transport

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `MCP_HTTP_PORT` | `8000` | HTTP bind port |
| `MCP_HTTP_HOST` | `0.0.0.0` | HTTP bind host |

## Dynamic targeting (Architecture B / `/mcp/prod` only)

The `/mcp/prod` path supports header-based per-request targeting for headless callers that need to switch subdomains at runtime. Send one of:

- `zendesk-subdomain: your-subdomain`
- `zendesk-base-url: https://your-subdomain.zendesk.com`

The `x-zendesk-*` prefix is also accepted. If neither header is present, the server falls back to `ZENDESK_SUBDOMAIN` / `ZENDESK_BASE_URL`. **Does not apply to `/mcp/dev`** — that path's target is resolved from `MCP_DEV_ENVIRONMENT` + the corresponding `ZENDESK_<ENV>_*` env vars.

## Tests

```bash
cd zendesk-mcp-server
.venv/bin/python -m pytest tests/ -q
```

148 tests across 12 files: tool gating, attribution gating per architecture, OAuth proxy URL handling, Cosmos KV store, Ideas cache, Architecture E JWT-SSO (dormant), Architecture C revert behaviour.

## Connector

Power Platform connector assets in `connector/`. `connectionparameters-entra.json` is the active (OAuth 2.0) connector spec. Legacy `*-oauth.json` files are kept for revert reference.

## Azure deployment

Live deployment:

- Resource group: `fourth-ai-prod` (North Europe)
- Managed environment: `fourth-ai-env`
- Container Registry: `fourthzendeskmcp`
- Container App: `fourth-zendesk-mcp-server`
- Cosmos DB: `cosmos-db-ai-enablement`
- Key Vault: `mcp-kv-ai-enablement`
- Storage (Ideas): `fourthzendeskideas`

### Manual deploy

```bash
cd zendesk-mcp-server
ZENDESK_EMAIL=... ZENDESK_API_TOKEN=... \
  bash deployment/azure/scripts/2-build-and-deploy.sh v3.10.5
```

Pre-reqs: `4-provision-oauth-storage.sh` must have run once (creates Key Vault secrets + Cosmos roles).

### Revert recipes

```bash
# L1 — flip auth mode (~30s, no redeploy)
az containerapp update -n fourth-zendesk-mcp-server -g fourth-ai-prod \
  --set-env-vars MCP_AUTH_MODE=entra

# L2 — traffic shift to prior revision
az containerapp ingress traffic set -n fourth-zendesk-mcp-server -g fourth-ai-prod \
  --revision-weight fourth-zendesk-mcp-server--0000110=100 fourth-zendesk-mcp-server--0000111=0

# L3 — git revert (last resort)
git revert <commit>
```

## Documentation

- `docs/DESIGN_DECISIONS.md` — architectural choices (ADR-1 through ADR-15)
- `docs/LIMITATIONS.md` — accepted risks for security reviewers
- `docs/zendesk-mcp-workflows.html` — interactive sequence diagram of the live Architecture C flows
- `docs/architecture-b-vs-f.md` — side-by-side auth model comparison (historical; B vs F)
- `docs/architecture-f-user-experience.md` — Architecture F UX rationale (historical)
- `docs/zendesk-oauth-implementation-guide.md` — OAuth implementation walkthrough
- `connector/README.md` — Power Platform connector setup
