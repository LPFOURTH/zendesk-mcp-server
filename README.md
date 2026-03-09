# Zendesk MCP Server

Hardened Zendesk MCP server for tickets, Help Center articles, search, and release note creation. This fork keeps the tool surface intentionally small, supports local `stdio` plus remote Streamable HTTP, and can target either production or sandbox Zendesk per request.

## Highlights

- Reduced tool surface from the original broad Zendesk fork to `10` focused tools
- No delete operations
- Per-user auth via request `Authorization` header, with `.env` fallback for local use
- Dynamic Zendesk targeting via `zendesk-subdomain` or `zendesk-base-url`
- Ticket and article responses include direct Zendesk URLs
- Dependency audit clean: `0` vulnerabilities
- Azure Container Apps deployment scripts and GitHub Actions included

## Available Tools

| Tool | Type | Description |
|------|------|-------------|
| `list_tickets` | Read | List tickets with pagination and optional status targeting |
| `get_ticket` | Read | Get a ticket by ID |
| `create_ticket` | Write | Create a ticket |
| `update_ticket` | Write | Update a ticket |
| `list_articles` | Read | List Help Center articles |
| `get_article` | Read | Get an article by ID |
| `create_article` | Write | Create an article |
| `update_article` | Write | Update an article |
| `search` | Read | Search tickets, articles, or all supported Zendesk content |
| `create_release_note` | Write | Create a Help Center release note from structured markdown |

## Quick Start

### Local `stdio`

```bash
cp .env.example .env
npm install
npm start
```

### Local Streamable HTTP

```bash
cp .env.example .env
npm install
npm run start:http
```

Health check: `http://localhost:8000/health`

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ZENDESK_SUBDOMAIN` | unset | Default Zendesk subdomain |
| `ZENDESK_BASE_URL` | unset | Alternative to `ZENDESK_SUBDOMAIN`, for example `https://company.zendesk.com` |
| `ZENDESK_EMAIL` | unset | Zendesk agent email for local fallback auth |
| `ZENDESK_API_TOKEN` | unset | Zendesk API token for local fallback auth |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `MCP_HTTP_PORT` | `8000` | HTTP port |
| `MCP_HTTP_HOST` | `0.0.0.0` | HTTP bind host |
| `DISABLED_TOOLS` | empty | Comma-separated tools to disable |
| `ZENDESK_RATE_LIMIT` | `200` | Max Zendesk API calls per minute |

## Dynamic Targeting

For remote clients such as Copilot Studio, send one of these headers on each request:

- `zendesk-subdomain: your-subdomain`
- `zendesk-base-url: https://your-subdomain.zendesk.com`

The server also accepts `x-zendesk-subdomain` and `x-zendesk-base-url`.

If neither header is present, the server uses `ZENDESK_SUBDOMAIN` or `ZENDESK_BASE_URL` from the environment.

## Tests

```bash
npm run test:targeting
npm run test:regression
```

## Connector

Power Platform connector assets live in `connector/`. See `connector/README.md` for per-user auth and sandbox/prod configuration.

## Azure Deployment

The checked-in scripts and workflow are aligned to the current live deployment:

- Resource group: `fourth-ai-prod`
- Managed environment: `fourth-ai-env`
- Container registry: `fourthzendeskmcp`
- Container app: `fourth-zendesk-mcp-server`

Use `deployment/azure/scripts/2-build-and-deploy.sh` for manual deploys or `.github/workflows/release.yml` for tagged releases.

## Security

See `SECURITY_REPORT.md` for the current security summary and remediation history.
