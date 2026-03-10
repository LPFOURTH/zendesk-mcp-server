# Security Report: Zendesk MCP Server

**Repository:** https://github.com/fourth/zendesk-mcp-fourth  
**Base Fork:** https://github.com/mattcoatsworth/zendesk-mcp-server  
**Current Version:** 1.4.0  
**Assessment Updated:** 2026-03-07  
**Status:** Approved for deployment

## Executive Summary

This fork remains in a low-risk posture after hardening. The current codebase keeps a limited Zendesk tool surface, blocks destructive delete operations, sanitizes upstream errors, validates Zendesk host targeting, and now supports per-request sandbox or production routing through validated headers.

Current dependency audit status:

```text
found 0 vulnerabilities
```

## Remediated Areas

| Area | Outcome |
|------|---------|
| Dependency vulnerabilities | Resolved by upgrading direct dependencies and pinning patched transitive packages with `overrides` |
| Over-broad tool surface | Reduced from the original broad Zendesk surface to `10` focused tools |
| Destructive operations | Delete operations removed |
| Error leakage | Zendesk API errors sanitized before being returned to MCP clients |
| SSRF / host injection risk | Subdomains and base URLs validated before use |
| Request abuse | Rate limiting retained and configurable |
| Remote transport | Streamable HTTP support retained with health checks and session handling |
| Copilot Studio compatibility | Added support for `zendesk-subdomain` and `zendesk-base-url` request headers |

## Current Security Controls

- `Authorization` header passthrough for per-user auth, with local env fallback only when the header is absent
- Validated Zendesk target resolution for `zendesk-subdomain`, `zendesk-base-url`, `x-zendesk-subdomain`, and `x-zendesk-base-url`
- Input bounds on pagination and user-controlled strings
- Axios request timeout and body size limits
- Sanitized tool errors instead of raw upstream payloads
- Runtime tool filtering via `DISABLED_TOOLS`
- Non-root container execution and health endpoint support
- CI/CD audit and image scan steps in `.github/workflows/release.yml`

## Dependency State

| Package | Version |
|---------|---------|
| `@modelcontextprotocol/sdk` | 1.27.1 |
| `axios` | 1.8.4 |
| `dotenv` | 16.4.7 |
| `zod` | 3.24.2 |

Transitive packages explicitly pinned through `overrides`:

- `@hono/node-server`
- `express-rate-limit`
- `hono`

## Tool Surface

The server currently exposes these `10` tools:

- `list_tickets`
- `get_ticket`
- `create_ticket`
- `update_ticket`
- `list_articles`
- `get_article`
- `create_article`
- `update_article`
- `search`
- `create_release_note`

## Deployment References

| Resource | Value |
|----------|-------|
| Resource group | `fourth-ai-prod` |
| Managed environment | `fourth-ai-env` |
| Container registry | `fourthzendeskmcp` |
| Container app | `fourth-zendesk-mcp-server` |
| Default Azure FQDN | `fourth-zendesk-mcp-server.bluewave-95f931ef.northeurope.azurecontainerapps.io` |

## Residual Risks

- Production credentials are still typically stored as app secrets or environment variables in Azure; Key Vault-backed secret references would be stronger.
- Tool outputs can still include Zendesk-authored content, so downstream copilots should keep normal tool-use controls enabled.
- Manual Copilot Studio validation was completed for the targeted flows, but there is not a full browser-based end-to-end suite in this cleaned repo.

## Recommendation

The repo is suitable for ongoing use and publication in its current state. Recommended next hardening steps are:

1. Move production secrets to Azure Key Vault-backed references.
2. Add lightweight CI checks for `npm run test:targeting` and `npm run test:regression`.
3. Periodically review connector configuration changes in Copilot Studio when Microsoft updates the UI.
