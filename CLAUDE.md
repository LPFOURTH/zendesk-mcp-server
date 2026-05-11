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

Integration tests are Node.js `.mjs` scripts (no Python unit test suite):
```bash
npm run test:targeting    # tests/zendesk-targeting.mjs
npm run test:regression   # tests/regression.mjs
```

## Architecture

```
MCP Client (Claude Code / Copilot Studio)
         │
         │  stdio (local)  or  Streamable HTTP (remote)
         ▼
    src/main.py          — transport dispatch; HTTP: ASGI middleware extracts
                           Authorization + zendesk-* headers into contextvars
         ▼
    src/server.py        — FastMCP server; registers tools from ALL_TOOLS list
                           filtered by tools.config.json and DISABLED_TOOLS env
         ▼
    src/tools/*.py       — plain async functions; 10 tools across 4 modules
         ▼
    src/zendesk_client.py — singleton httpx client; per-request auth + target
                            resolved from contextvars → env vars → ENVIRONMENTS
```

**Path-based routing** (HTTP mode): `/mcp/dev` and `/mcp/prod` rewrite to `/mcp` with `zendesk-environment` injected, so one server instance handles both sandbox and production Zendesk.

## Key Files

- **`src/main.py`** — entry point; ASGI `_make_context_middleware` extracts per-request headers (`Authorization`, `zendesk-subdomain`, `zendesk-base-url`, `zendesk-environment`) and writes them to `contextvars`
- **`src/server.py`** — `create_server()` builds the FastMCP instance and registers enabled tools
- **`src/zendesk_client.py`** — `ZendeskClient` singleton; `_get_target()` + `_get_auth_header()` resolve per-request from `contextvars` with env-var fallback; built-in `RateLimiter` (default 200 req/min sliding window)
- **`src/request_context.py`** — `contextvars` definitions (`authorization_var`, `zendesk_subdomain_var`, etc.)
- **`src/constants.py`** — `ENVIRONMENTS` dict (prod/dev Zendesk base URLs, section IDs, author IDs); UK/US release note HTML templates
- **`tools.config.json`** — per-tool enable/disable; presets (`read_only`, `full`, `tickets_only`, `articles_only`) activated via `TOOLS_PRESET` env var

## Authentication

**Remote / HTTP**: Each request carries its own Zendesk credentials via the `Authorization` header (e.g., `Basic <base64 email/token:apitoken>`). The ASGI middleware stores it in `authorization_var`; `ZendeskClient` forwards it verbatim. This enables per-user auth in Copilot Studio.

**Local / stdio**: No `Authorization` contextvar → client constructs `Basic` token from `ZENDESK_EMAIL` + `ZENDESK_API_TOKEN` env vars.

## Tools

All tools live in `src/tools/` as plain `async def` functions registered via `server.py`. No delete operations exist by design.

| Tool | Module | Notes |
|------|--------|-------|
| `list_tickets` | tickets.py | Status filter uses Zendesk search API internally |
| `get_ticket` | tickets.py | Includes comments; description truncated to 500 chars |
| `create_ticket` | tickets.py | |
| `update_ticket` | tickets.py | `internal_note` flag for private agent notes |
| `list_articles` | help_center.py | |
| `get_article` | help_center.py | Body truncated to 2000 chars |
| `create_article` | help_center.py | |
| `update_article` | help_center.py | Splits into translation + metadata API calls |
| `search` | search.py | Infers ticket vs. article scope; normalizes query |
| `create_release_note` | release_notes.py | Parses `### Functionality N Name/Description` markdown → UK/US HTML template → draft article |

## Deployment

CI/CD via `.github/workflows/release.yml`: on git tags, builds Docker image → Trivy security scan → deploys to Azure Container Apps. IaC and deploy scripts are in `deployment/azure/`. Power Platform connector assets (OpenAPI spec + connection parameters) are in `connector/`.
