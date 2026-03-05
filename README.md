# Zendesk MCP Server (Hardened Fork)

Security-hardened fork of [mattcoatsworth/zendesk-mcp-server](https://github.com/mattcoatsworth/zendesk-mcp-server) with reduced tool surface, dependency fixes, and Azure Container Apps deployment support.

## Changes from Original

- **Tool surface reduced from 49 to 9** (tickets + articles + search only)
- **All DELETE operations removed**
- **All user/org/group/macro/view/trigger/automation tools removed**
- **Dependencies updated** (0 known vulnerabilities)
- **HTTP/SSE transport added** for remote deployment
- **Rate limiting** (configurable, default 200 req/min)
- **Input validation bounds** (per_page, string lengths)
- **Error sanitization** (no raw API data leaked)
- **Subdomain validation** (SSRF prevention)
- **Docker + Azure Bicep + GitHub Actions CI/CD**

## Available Tools

| Tool | Type | Description |
|------|------|-------------|
| `list_tickets` | Read | List tickets with pagination |
| `get_ticket` | Read | Get ticket by ID |
| `create_ticket` | Write | Create a new ticket |
| `update_ticket` | Write | Update an existing ticket |
| `list_articles` | Read | List Help Center articles |
| `get_article` | Read | Get article by ID |
| `create_article` | Write | Create a Help Center article |
| `update_article` | Write | Update an existing article |
| `search` | Read | Search across Zendesk data |

## Quick Start

### Local (stdio mode for Cursor/Claude Desktop)

```bash
cp .env.example .env
# Edit .env with your Zendesk credentials
npm install
npm start
```

### Local (HTTP/SSE mode for testing remote transport)

```bash
npm run start:http
# Server at http://localhost:8000/sse
# Health check at http://localhost:8000/health
```

### Docker

```bash
docker build -t zendesk-mcp-server .
docker run -p 8000:8000 \
  -e ZENDESK_SUBDOMAIN=your-subdomain \
  -e ZENDESK_EMAIL=your-email@example.com \
  -e ZENDESK_API_TOKEN=your-api-token \
  zendesk-mcp-server
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ZENDESK_SUBDOMAIN` | (required) | Your Zendesk subdomain |
| `ZENDESK_EMAIL` | (required) | Zendesk agent email |
| `ZENDESK_API_TOKEN` | (required) | Zendesk API token |
| `MCP_TRANSPORT` | `stdio` | Transport: `stdio` or `http` |
| `MCP_HTTP_PORT` | `8000` | HTTP server port |
| `MCP_HTTP_HOST` | `0.0.0.0` | HTTP server host |
| `DISABLED_TOOLS` | (empty) | Comma-separated tool names to disable |
| `ZENDESK_RATE_LIMIT` | `200` | Max Zendesk API calls per minute |

## Azure Deployment

See `deployment/azure/bicep/main.bicep` for infrastructure-as-code and `.github/workflows/release.yml` for CI/CD.

## Security

See [SECURITY_REPORT.md](SECURITY_REPORT.md) for the full compliance and security assessment.
