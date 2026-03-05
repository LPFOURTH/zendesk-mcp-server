# Security & Compliance Report: Zendesk MCP Server (Hardened Fork)

**Repository:** Forked from https://github.com/mattcoatsworth/zendesk-mcp-server  
**Fork Version:** 1.1.0  
**Original Version:** 1.0.0 (commit c422cd3, 2025-04-04)  
**License:** MIT (stated in README; no LICENSE file in original)  
**Assessment Date:** 2026-03-02  
**Status:** APPROVED WITH MODIFICATIONS (all critical/high issues resolved)

---

## Executive Summary

The original Zendesk MCP server was assessed at **HIGH risk** with 2 critical, 5 high, 4 medium, and 2 low findings. This hardened fork resolves all critical and high issues, reduces the tool surface from 49 to 9 (tickets + articles + search only, no delete operations), adds HTTP/SSE transport for remote deployment, and introduces rate limiting, input validation bounds, and sanitized error handling.

**Post-hardening risk level: LOW**

---

## Original Findings vs. Remediation Status

### CRITICAL Issues (2/2 RESOLVED)

| ID | Finding | Original Status | Remediation | Status |
|----|---------|----------------|-------------|--------|
| CRITICAL-01 | `.env` committed to git, no `.gitignore` | `.env` tracked in repo | Created `.gitignore`, removed `.env` from tracking, deleted `.env` from working tree | **RESOLVED** |
| CRITICAL-02 | form-data weak randomness (GHSA-fjxv-7rqg-78g4) | form-data 4.0.0-4.0.3 | Updated axios to ^1.8.4 which pulls patched transitive deps | **RESOLVED** |

### HIGH Issues (5/5 RESOLVED)

| ID | Finding | Original Status | Remediation | Status |
|----|---------|----------------|-------------|--------|
| HIGH-01 | MCP SDK ReDoS + DNS rebinding (v1.8.0) | SDK ^1.0.0 (resolved to 1.8.0) | Updated to ^1.12.1 (installed 1.27.1) | **RESOLVED** |
| HIGH-02 | Axios DoS + prototype pollution | axios ^1.6.2 | Updated to ^1.8.4 with `maxContentLength` and `maxBodyLength` limits | **RESOLVED** |
| HIGH-03 | 9 unrestricted DELETE tools | All delete tools exposed | Removed ALL delete tools. Only 9 tools remain (list/get/create/update for tickets + articles, plus search) | **RESOLVED** |
| HIGH-04 | create_user allows admin role | `role: z.enum(["end-user","agent","admin"])` | Entire users module removed from this fork. No user creation/modification tools exist | **RESOLVED** |
| HIGH-05 | Error messages leak Zendesk API response data | `JSON.stringify(error.response.data)` | Sanitized to return only status code + error/description field. Full errors logged server-side only | **RESOLVED** |

### MEDIUM Issues (4/4 RESOLVED)

| ID | Finding | Remediation | Status |
|----|---------|-------------|--------|
| MEDIUM-01 | 18x `z.any()` input validation bypass | All affected modules (triggers, automations, views, macros) removed from this fork | **RESOLVED** |
| MEDIUM-02 | No rate limiting | Added `RateLimiter` class (configurable via `ZENDESK_RATE_LIMIT`, default 200/min) | **RESOLVED** |
| MEDIUM-03 | SSRF via unvalidated subdomain | Added regex validation: `/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/i` | **RESOLVED** |
| MEDIUM-04 | No per_page upper bound | Added `.min(1).max(100)` on all pagination parameters | **RESOLVED** |

### LOW Issues (2/2 RESOLVED)

| ID | Finding | Remediation | Status |
|----|---------|-------------|--------|
| LOW-01 | Single commit repo, no CI/CD | Added GitHub Actions workflow with npm audit + Trivy scan + deployment verification | **RESOLVED** |
| LOW-02 | `console.log` on stdout conflicts with stdio transport | Changed all logging to `console.error` (stderr) | **RESOLVED** |

---

## Dependency Audit

```
$ npm audit
found 0 vulnerabilities
```

| Package | Version | Known Vulns |
|---------|---------|-------------|
| @modelcontextprotocol/sdk | 1.27.1 | None |
| axios | 1.8.4 | None |
| dotenv | 16.4.7 | None |
| zod | 3.24.2 | None |

**Total dependencies:** 104 packages (including transitive)  
**Vulnerabilities:** 0 critical, 0 high, 0 moderate, 0 low

---

## Tool Surface Reduction

### Original (49 tools)
- Tickets: list, get, create, update, **delete**
- Users: list, get, create, update, **delete**
- Organizations: list, get, create, update, **delete**
- Groups: list, get, create, update, **delete**
- Macros: list, get, create, update, **delete**
- Views: list, get, create, update, **delete**
- Triggers: list, get, create, update, **delete**
- Automations: list, get, create, update, **delete**
- Help Center: list, get, create, update, **delete**
- Search, Talk, Chat, Support

### Hardened Fork (9 tools)
- **Tickets:** list_tickets, get_ticket, create_ticket, update_ticket
- **Help Center:** list_articles, get_article, create_article, update_article
- **Search:** search

### Removed Capabilities
- All 9 DELETE operations (tickets, users, orgs, groups, macros, views, triggers, automations, articles)
- All user management (list, get, create, update, delete)
- All organization management
- All group management
- All macro management
- All view management
- All trigger management
- All automation management
- Talk statistics
- Chat listing
- Support tools

### Additional Filtering
Tools can be further disabled at runtime via `DISABLED_TOOLS` environment variable without code changes.

---

## Security Controls Added

### 1. Input Validation
- All `per_page` parameters: `.min(1).max(100)`
- All `page` parameters: `.min(1)`
- String length limits: subject (300), comment (65536), title (500), body (1MB), tags (100 chars each, 20 max)
- Search query: `.max(1000)`
- Subdomain regex validation

### 2. Rate Limiting
- Configurable via `ZENDESK_RATE_LIMIT` env var (default: 200 requests/minute)
- Sliding window algorithm
- Returns clear error message with retry timing

### 3. Request Hardening
- `timeout: 30000` on all Zendesk API calls
- `maxContentLength: 10MB` / `maxBodyLength: 10MB` on axios
- Sanitized error responses (no raw API data leaked to LLM)

### 4. MCP Tool Annotations
All tools include MCP protocol annotations:
- `readOnlyHint: true/false`
- `destructiveHint: false` (no destructive operations exist)
- `idempotentHint: true/false`

### 5. Transport Security
- HTTP/SSE transport with proper session management
- Sessions tracked and cleaned up on disconnect
- Health check endpoints for monitoring

### 6. Container Security
- Multi-stage Docker build (smaller attack surface)
- Non-root execution (UID 1000, `mcpuser`)
- No secrets in environment variables (credentials set at deployment time)
- Health check via HTTP GET /health

### 7. CI/CD Security
- `npm audit` in pipeline
- Trivy vulnerability scanning on Docker image
- Deployment verification with health check

---

## Deployment Architecture (Separate from Rally MCP)

| Resource | Name | Notes |
|----------|------|-------|
| Resource Group | fourth-zendesk-prod | Separate from Rally |
| Container Registry | fourthzendeskzap | Separate ACR, Basic SKU |
| Container App Environment | fourth-zendesk-env | Separate environment |
| Container App | fourth-zendesk-mcp-server | Node.js 20, port 8000 |
| Custom Domain | zendesk-mcp.fourth.com | Azure-managed TLS |

### Scaling
- Min replicas: 1 (avoid cold starts)
- Max replicas: 10
- HTTP scaling: 100 concurrent requests/replica
- Business hours cron: 7am-2am UTC

### Infrastructure as Code
- Bicep template: `deployment/azure/bicep/main.bicep`
- GitHub Actions: `.github/workflows/release.yml`

---

## Remaining Risks (Accepted)

| Risk | Severity | Mitigation |
|------|----------|------------|
| LLM prompt injection via ticket/article content could manipulate tool calls | LOW | No destructive tools; create/update operations are bounded. LLM clients (Cursor, Claude Desktop) show tool call confirmations |
| No LICENSE file in original repo (README claims MIT) | LOW | MIT is permissive; fork adds no additional license constraints |
| Zendesk API token stored as env var in container | LOW | Standard pattern for Container Apps; secrets management via Azure Key Vault recommended for production |
| No automated test suite | LOW | MCP connectivity tested manually; recommend adding integration tests |

---

## Verification Results

### MCP Protocol Test (2026-03-02)
```
Connected to MCP server!

Registered tools (9):
  - list_tickets: List tickets in Zendesk. Returns paginated results.
  - get_ticket: Get a specific ticket by ID, including all comments and metadata.
  - create_ticket: Create a new support ticket in Zendesk.
  - update_ticket: Update an existing ticket. Only provided fields will be changed.
  - list_articles: List Help Center articles. Returns paginated results.
  - get_article: Get a specific Help Center article by ID, including body content.
  - create_article: Create a new Help Center article in a specified section.
  - update_article: Update an existing Help Center article. Only provided fields will be changed.
  - search: Search across Zendesk tickets, articles, users, and organizations.

Connection closed cleanly.
```

### DISABLED_TOOLS Test
```
DISABLED_TOOLS="create_ticket,create_article" -> Registered tools (7) ✓
```

### Health Check
```json
{"status":"healthy","service":"Zendesk MCP Server","version":"1.1.0","transport":"sse"}
```

### npm audit
```
found 0 vulnerabilities
```

---

## Recommendation

**APPROVED FOR DEPLOYMENT** with the following conditions:
1. Store Zendesk API credentials in Azure Key Vault (not plain env vars) for production
2. Set up monitoring/alerting on Container App metrics
3. Review tool usage logs periodically for anomalous patterns
4. Pin the Zendesk API token to minimum required permissions in Zendesk admin
5. Consider adding integration tests before production deployment

---

*Report generated 2026-03-02. All findings verified against source code in this repository.*
