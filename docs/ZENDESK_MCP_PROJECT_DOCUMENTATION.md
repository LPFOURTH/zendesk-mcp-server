# Zendesk MCP Server & Product Mentor Integration

**Project Timeline:** 2026-03-02 to 2026-03-03  
**Status:** MCP server ready for deployment; Product Mentor PR open for review

---

## Table of Contents

1. [Project Goal](#1-project-goal)
2. [Phase 1: Forking and Security Hardening](#2-phase-1-forking-and-security-hardening)
3. [Phase 2: Dual Transport (stdio + HTTP/SSE)](#3-phase-2-dual-transport-stdio--httpsse)
4. [Phase 3: Tool Configuration System](#4-phase-3-tool-configuration-system)
5. [Phase 4: Azure Deployment Infrastructure](#5-phase-4-azure-deployment-infrastructure)
6. [Phase 5: Release Note MCP Tool](#6-phase-5-release-note-mcp-tool)
7. [Phase 6: Product Mentor Integration (PR)](#7-phase-6-product-mentor-integration-pr)
8. [Repository Structure](#8-repository-structure)
9. [How to Run Locally](#9-how-to-run-locally)
10. [How to Deploy to Azure](#10-how-to-deploy-to-azure)
11. [Testing Summary](#11-testing-summary)

---

## 1. Project Goal

Build a hardened, remotely deployable Zendesk MCP (Model Context Protocol) server and integrate it with the existing Product Mentor bot to replace its AbacusAI-based Zendesk workflow.

The Product Mentor bot previously ran on the AbacusAI platform and called Python modules to interact with Zendesk. The migration moves all Zendesk operations to a standalone MCP server that any MCP-compatible LLM client can use -- removing the AbacusAI dependency entirely.

---

## 2. Phase 1: Forking and Security Hardening

### Source

Forked from [mattcoatsworth/zendesk-mcp-server](https://github.com/mattcoatsworth/zendesk-mcp-server) (MIT license, v1.0.0, commit c422cd3).

The original server exposed **49 tools** across 10 Zendesk API modules with no security controls.

### What was done

**Dependency updates** -- all four dependencies upgraded to patched versions:

| Package | Original | Hardened |
|---------|----------|----------|
| @modelcontextprotocol/sdk | ^1.0.0 | ^1.12.1 (resolves to 1.27.1) |
| axios | ^1.6.2 | ^1.8.4 |
| dotenv | ^16.3.1 | ^16.4.7 |
| zod | ^3.22.4 | ^3.24.2 |

Post-update: `npm audit` returns **0 vulnerabilities** across 104 packages.

**Tool surface reduction** -- 49 tools reduced to 9:

- Kept: `list_tickets`, `get_ticket`, `create_ticket`, `update_ticket`, `list_articles`, `get_article`, `create_article`, `update_article`, `search`
- Removed: all DELETE operations (9 tools), all user/org/group/macro/view/trigger/automation management, Talk, Chat, Support modules

**Security controls added:**

- `.gitignore` created (`.env` was previously tracked in git)
- Subdomain regex validation to prevent SSRF: `/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/i`
- Rate limiter class: sliding window, configurable via `ZENDESK_RATE_LIMIT` (default 200/min)
- Request hardening: 30s timeout, 10MB max content/body length on all axios calls
- Input validation bounds: `per_page` capped at 100, string length limits on all fields
- Sanitized error responses: only status code + error message returned; full errors logged server-side
- MCP tool annotations: `readOnlyHint`, `destructiveHint`, `idempotentHint` on every tool
- `console.log` changed to `console.error` throughout to avoid conflict with stdio transport

A full security report was generated: `zendesk-mcp-server/SECURITY_REPORT.md`  
13 findings (2 critical, 5 high, 4 medium, 2 low) -- all resolved.

### Files created/modified

- `zendesk-mcp-server/.gitignore` -- new
- `zendesk-mcp-server/package.json` -- updated dependencies
- `zendesk-mcp-server/src/zendesk-client.js` -- added rate limiter, subdomain validation, request limits, error sanitization; removed unused API methods
- `zendesk-mcp-server/src/tools/tickets.js` -- removed delete tool, added input bounds and annotations
- `zendesk-mcp-server/src/tools/help-center.js` -- removed delete tool, added input bounds and annotations
- `zendesk-mcp-server/src/tools/search.js` -- added query length limit and annotations
- `zendesk-mcp-server/SECURITY_REPORT.md` -- new, full compliance report

---

## 3. Phase 2: Dual Transport (stdio + HTTP/SSE)

The original server only supported `stdio` transport (local IDE use). For remote deployment to Azure, HTTP/SSE transport was required.

### What was done

Rewrote `src/index.js` to support both transports based on the `MCP_TRANSPORT` environment variable:

- **stdio** (default): uses `StdioServerTransport` from the MCP SDK. Standard for local IDE connections (Cursor, Claude Desktop).
- **http/sse**: uses Node.js native `http.createServer` with `SSEServerTransport` from the MCP SDK. Three endpoints:
  - `GET /health` -- JSON health check
  - `GET /sse` -- SSE connection endpoint (creates session, returns message endpoint URL)
  - `POST /messages?sessionId=<id>` -- JSON-RPC message handler

Express was intentionally not used. The native `http` module was chosen after debugging a `stream is not readable` error that occurred with Express due to how it consumed the request body before the MCP SDK could read it. The solution was to manually consume the stream with `for await (const chunk of req)`, parse the JSON, and pass the parsed body to `sseTransport.handlePostMessage()`.

Sessions are tracked in a `Map` and cleaned up when the SSE connection closes.

### Files created/modified

- `zendesk-mcp-server/src/index.js` -- rewritten with dual transport
- `zendesk-mcp-server/.env.example` -- extended with `MCP_TRANSPORT`, `MCP_HTTP_PORT`, `MCP_HTTP_HOST`

---

## 4. Phase 3: Tool Configuration System

### What was done

Created a centralized tool configuration file (`tools.config.json`) that controls which tools are enabled at server startup. The system supports three layers of configuration:

1. **Config file** (`tools.config.json`): each tool has an `enabled: true/false` flag
2. **Presets** (`TOOLS_PRESET` env var): named profiles like `read_only`, `full`, `tickets_only`, `articles_only`
3. **Runtime override** (`DISABLED_TOOLS` env var): comma-separated list of tool names to disable on top of whatever the config/preset says

`server.js` was rewritten to load the config at startup, resolve presets, merge environment overrides, and only register the resulting enabled tools with the MCP server.

### Configuration file structure

```json
{
  "tools": {
    "list_tickets": { "enabled": true, "category": "tickets", "operation": "read" },
    "create_release_note": { "enabled": true, "category": "release_notes", "operation": "write" }
  },
  "presets": {
    "read_only": { "enable": ["list_tickets", "get_ticket", ...], "disable": ["create_ticket", ...] },
    "full": { "enable": [...all tools...], "disable": [] }
  }
}
```

### Files created/modified

- `zendesk-mcp-server/tools.config.json` -- new, central tool configuration
- `zendesk-mcp-server/src/server.js` -- rewritten with config loading, preset resolution, tool filtering

---

## 5. Phase 4: Azure Deployment Infrastructure

### Decision

Deployed as a **separate Azure infrastructure** from the existing Rally MCP server. Separate Resource Group, Container Registry, Container App Environment, and Container App.

### What was created

**Bicep IaC template** (`deployment/azure/bicep/main.bicep`):

| Resource | Name | Spec |
|----------|------|------|
| Resource Group | fourth-zendesk-prod | North Europe |
| Container Registry | fourthzendeskzap | Basic SKU |
| Log Analytics | fourth-zendesk-env-logs | 30-day retention |
| Container App Environment | fourth-zendesk-env | Linked to Log Analytics |
| Container App | fourth-zendesk-mcp-server | 0.5 vCPU, 1 GiB RAM |

Scaling: 1-10 replicas, HTTP-based at 100 concurrent requests per replica, cron rules for business hours (7am-2am UTC).

Ingress: external, port 8000, HTTPS only, sticky sessions enabled (required for SSE).

Health probes: liveness (30s interval, `/health`) and readiness (10s interval, `/health`).

**Dockerfile** (`Dockerfile`):

- Multi-stage build from `node:20-slim`
- Non-root user `mcpuser` (UID 1000)
- HTTP health check built in
- Environment defaults: `MCP_TRANSPORT=http`, port 8000

**CLI deployment scripts** (`deployment/azure/scripts/`):

| Script | Purpose |
|--------|---------|
| `1-create-infrastructure.sh` | Creates Resource Group + deploys Bicep template |
| `2-build-and-deploy.sh` | Builds Docker image, pushes to ACR, updates Container App |
| `3-setup-custom-domain.sh` | Configures custom domain + Azure-managed TLS |
| `update-env.sh` | Updates environment variables (Zendesk credentials) on running app |
| `verify.sh` | Runs health check and SSE connectivity test |
| `logs.sh` | Tails Container App logs |

### Files created

- `zendesk-mcp-server/Dockerfile`
- `zendesk-mcp-server/deployment/azure/bicep/main.bicep`
- `zendesk-mcp-server/deployment/azure/scripts/*.sh` (6 scripts)

---

## 6. Phase 5: Release Note MCP Tool

### Why this was needed

The Product Mentor bot's release note creation involved complex HTML template assembly -- concatenating hardcoded HTML header/middle/footer blocks with dynamically generated feature lists. This logic was too complex to replicate reliably via LLM instructions alone. The solution was to port it into a dedicated MCP tool that handles the template assembly deterministically.

### What was ported

The Python logic from three files in the `product_mentor` repository was ported to JavaScript:

**Source (Python):**
- `src/constants/zendesk_constants.py` -- 5 HTML template constants (US header, US middle, UK header, UK middle, feature details footer)
- `src/helpers/zendesk_utils.py` -- markdown parsing pipeline and HTML assembly functions
- `src/zendesk_functions/create_release_note.py` -- main orchestration function

**Destination (JavaScript):**
- `zendesk-mcp-server/src/tools/release-notes.js` -- single file containing everything

### What the tool does

The `create_release_note` MCP tool accepts:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `markdown_content` | string | yes | Markdown with `### Functionality N Name/Description` sections |
| `use_us_template` | boolean | no | `true` for US template, `false` (default) for UK |
| `section_id` | number | yes | Zendesk Help Center section ID |
| `title` | string | no | Custom title; auto-generated from feature names if omitted |
| `locale` | string | no | Default `en-us` |
| `draft` | boolean | no | Default `true` |
| `permission_group_id` | number | no | Zendesk permission group |
| `user_segment_id` | number | no | Zendesk user segment |
| `author_id` | number | no | Zendesk author user |

Processing pipeline:

1. **Parse** markdown content -- extract functionality names and descriptions using regex
2. **Validate** -- must have at least one functionality with both Name and Description
3. **Generate title** -- if not provided, auto-generates based on template (US: `New Release | Main: Features... | Mmm DD YYYY`, UK: `New Release | Product Name: Features... | DD Mmm YYYY`)
4. **Assemble HTML** -- concatenates the appropriate template header + "What's New" feature list + template middle + "Release Note Info/Steps" section with Y/N checklist footer per feature
5. **Create article** -- calls `zendeskClient.createArticle()` to create a draft article in Zendesk

The HTML templates were ported **exactly as-is** -- the output is byte-identical to what the Python code produced.

### Registration

- Added to `server.js` import and `allTools` array
- Added to `tools.config.json` under `release_notes` category
- Added to `full` and `articles_only` presets
- Server now registers **10 tools** (was 9)

### Files created/modified

- `zendesk-mcp-server/src/tools/release-notes.js` -- new
- `zendesk-mcp-server/src/server.js` -- added import and registration
- `zendesk-mcp-server/tools.config.json` -- added tool entry and preset updates

---

## 7. Phase 6: Product Mentor Integration (PR)

### Repository

[fourth/product_mentor](https://github.com/fourth/product_mentor) -- the existing bot that was running on AbacusAI.

### What was changed

A single file was modified:  
`src/Behavior Instructions/Behavior Instructions Breakdown/Zendesk Reading, Drafting, Creating, Updating Release Note.txt`

This file contains the LLM behavior instructions that tell the bot how to handle Zendesk release notes. **All 6 AbacusAI code blocks were replaced** with MCP tool call references:

| Section | Before (AbacusAI) | After (MCP) |
|---------|-------------------|-------------|
| Read a release note | `from abacusai import ApiClient`; `zendesk_module.get_release_note(url)` | `get_article` tool with article ID extracted from URL |
| Create a release note | `zendesk_module.create_release_note(markdown_content, use_us_template)` | `create_release_note` tool with markdown_content, use_us_template, section_id |
| Example conversation | Python code block with AbacusAI imports | Tool call block referencing `create_release_note` |
| Update - read | `zendesk_module.get_release_note(url)` | `get_article` tool with article ID |
| Update - write | `zendesk_module.update_release_note(url, body, title)` | `update_article` tool with article ID, body, title |
| All "code execution" references | "Output from the code execution..." | "Output from the tool call..." |

### What was NOT changed

- The workflow steps (draft markdown, present to user, get approval, create/update) -- identical
- The markdown template format (`### Functionality N Name/Description`) -- identical
- UK/US template selection logic -- identical
- The example conversation content -- preserved (only the code block was replaced)
- No other files in the repository were touched

### Verification

`grep -i "abacus\|ApiClient\|import_module\|code execution"` returns **zero matches** in the modified file.

### PR

- Branch: `feature/zendesk-mcp-integration` (from `main`)
- PR: https://github.com/fourth/product_mentor/pull/8
- 1 file changed: 81 insertions, 92 deletions

---

## 8. Repository Structure

```
zendesk-mcp-server/
  .env.example                          # Environment variable reference
  .gitignore                            # Prevents .env and node_modules from tracking
  Dockerfile                            # Multi-stage, non-root, health-checked
  package.json                          # v1.1.0, 4 dependencies
  tools.config.json                     # Central tool enable/disable + presets
  SECURITY_REPORT.md                    # Full compliance report (13 findings, all resolved)
  README.md                             # Setup and deployment instructions
  src/
    index.js                            # Entry point: stdio or HTTP/SSE transport
    server.js                           # MCP server: config loading, tool registration
    zendesk-client.js                   # Zendesk API client with rate limiting + hardening
    tools/
      tickets.js                        # list, get, create, update tickets
      help-center.js                    # list, get, create, update articles
      search.js                         # search across Zendesk
      release-notes.js                  # create_release_note (templates + markdown parsing)
  deployment/
    azure/
      bicep/
        main.bicep                      # IaC: ACR, Log Analytics, Container App Env, Container App
      scripts/
        1-create-infrastructure.sh      # Create Azure resources
        2-build-and-deploy.sh           # Build Docker image, push to ACR, deploy
        3-setup-custom-domain.sh        # Custom domain + TLS
        update-env.sh                   # Update env vars on running app
        verify.sh                       # Health + SSE connectivity check
        logs.sh                         # Tail container logs
```

---

## 9. How to Run Locally

### stdio mode (for IDE integration)

```bash
cd zendesk-mcp-server
cp .env.example .env
# Edit .env with your Zendesk credentials
npm install
npm start
```

### HTTP/SSE mode (for remote testing)

```bash
MCP_TRANSPORT=http MCP_HTTP_PORT=8000 npm start
# Health check: curl http://localhost:8000/health
# SSE endpoint: http://localhost:8000/sse
```

---

## 10. How to Deploy to Azure

```bash
cd zendesk-mcp-server/deployment/azure/scripts

# Step 1: Create infrastructure
./1-create-infrastructure.sh

# Step 2: Build and deploy container
./2-build-and-deploy.sh

# Step 3: Set Zendesk credentials
./update-env.sh

# Step 4: (Optional) Configure custom domain
./3-setup-custom-domain.sh

# Verify
./verify.sh
```

---

## 11. Testing Summary

### MCP Server Tests (2026-03-02)

| Test | Result |
|------|--------|
| `npm audit` | 0 vulnerabilities |
| stdio transport: tool listing | 9 tools registered |
| HTTP/SSE transport: health check | `{"status":"healthy","service":"Zendesk MCP Server","version":"1.1.0","transport":"sse"}` |
| HTTP/SSE transport: tool listing | 9 tools registered via SSE |
| `DISABLED_TOOLS="create_ticket,create_article"` | 7 tools registered (2 disabled) |
| `TOOLS_PRESET=read_only` | 5 tools registered (write tools disabled) |

### Release Note Tool Tests (2026-03-03)

| Test | Result |
|------|--------|
| HTTP/SSE tool listing after adding release-notes.js | **10/10 tools** registered, `create_release_note` visible |
| Valid markdown call | Parsed successfully, templates assembled, Zendesk API call attempted (fails gracefully with "credentials not configured") |
| Invalid markdown call (no sections) | Returns `"Release note must include at least one functionality name section"` |
| Empty markdown call | Returns `"Markdown content cannot be empty"` |

### Product Mentor PR Verification (2026-03-03)

| Check | Result |
|-------|--------|
| AbacusAI references in modified file | **0 matches** |
| File count changed | 1 file (behavior instructions only) |
| Diff | 81 insertions, 92 deletions |
| PR | https://github.com/fourth/product_mentor/pull/8 |
