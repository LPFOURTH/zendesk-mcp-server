# MCP Server Testing Guide

A comprehensive guide for testing Model Context Protocol (MCP) servers, derived from official specifications, community best practices, and lessons learned from the Zendesk MCP Server deployment.

## Table of Contents

1. [Testing Dimensions](#testing-dimensions)
2. [Transport Layer Testing (SSE)](#transport-layer-testing-sse)
3. [Protocol Compliance (JSON-RPC 2.0)](#protocol-compliance-json-rpc-20)
4. [Tool Discovery and Registration](#tool-discovery-and-registration)
5. [Functional Testing per Tool](#functional-testing-per-tool)
6. [Data Lifecycle Testing](#data-lifecycle-testing)
7. [Input Validation and Boundary Testing](#input-validation-and-boundary-testing)
8. [Security Testing](#security-testing)
9. [Error Handling and Resilience](#error-handling-and-resilience)
10. [Performance and Concurrency](#performance-and-concurrency)
11. [Tooling and References](#tooling-and-references)

---

## Testing Dimensions

Every MCP server test suite should cover these seven dimensions:

| Dimension | What it validates | Example |
|-----------|-------------------|---------|
| **Protocol** | JSON-RPC 2.0 compliance, MCP handshake | `tools/list` returns valid structure |
| **Transport** | SSE connection, session lifecycle, reconnect | Session ID in endpoint, connection cleanup |
| **Discovery** | Tool schemas, descriptions, annotations | Each tool has `inputSchema.type === "object"` |
| **Functional** | Happy-path tool execution | `search` returns results for valid query |
| **Boundary** | Edge cases, min/max values | `per_page: 0`, `per_page: 100`, `per_page: 101` |
| **Security** | Injection, credential leaks, rate limits | SQL/shell metacharacters in inputs |
| **Reliability** | Concurrent sessions, rapid calls, large payloads | 5 parallel sessions, 10 sequential tool calls |

## Transport Layer Testing (SSE)

### Connection Establishment

```javascript
// Verify SSE connection returns an endpoint event
const res = await fetch(`${BASE_URL}/sse`);
assert(res.headers.get('content-type').includes('text/event-stream'));
// First event must be: event: endpoint\ndata: /messages?sessionId=<uuid>
```

### Session Management

- **Unique session IDs**: Each SSE connection gets a unique UUID-based session.
- **Session isolation**: Tool calls on session A must not affect session B.
- **Session cleanup**: After closing the SSE connection, POSTing to the old session ID should return 400.
- **Invalid session**: POSTing to `/messages?sessionId=nonexistent` returns 400.

### Health Endpoint

- `GET /health` returns 200 with `{ status: "healthy" }`.
- `GET /` also returns the health response (alias).
- Non-existent paths return 404.

## Protocol Compliance (JSON-RPC 2.0)

### Required Fields

Every request must have `jsonrpc: "2.0"`, a numeric `id`, a `method`, and optional `params`. Responses must echo the `id`.

### Error Codes

| Code | Meaning |
|------|---------|
| -32700 | Parse error (malformed JSON) |
| -32600 | Invalid request (missing required fields) |
| -32601 | Method not found |
| -32602 | Invalid params |
| -32603 | Internal error |

### Test Cases

- Send malformed JSON → expect parse error or 500.
- Send valid JSON-RPC with unknown method → expect method-not-found or graceful error.
- Send `tools/call` with wrong argument types → expect -32602.
- Verify response `id` matches request `id`.

## Tool Discovery and Registration

### `tools/list`

- Returns array of tools with `name`, `description`, `inputSchema`.
- Each `inputSchema` has `type: "object"` and `properties`.
- Descriptions are non-empty and meaningful (>10 chars).
- Tool count matches expected configuration.
- No duplicate tool names.

### Tool Annotations (MCP 2024-11 spec)

Verify `readOnlyHint`, `destructiveHint`, and `idempotentHint` for each tool:
- Read tools (`list_*`, `get_*`, `search`) → `readOnlyHint: true`
- Write tools (`create_*`, `update_*`) → `readOnlyHint: false`
- No tool should have `destructiveHint: true` (we removed all delete operations).

## Functional Testing per Tool

### Structure

Each tool needs tests in these categories:

1. **Happy path** – valid input, verify response shape and content.
2. **Missing required params** – omit each required field, expect error.
3. **Invalid types** – pass string where number expected, etc.
4. **Boundary values** – min, max, just over max for each numeric param.
5. **Empty/null inputs** – empty strings, null values.
6. **Special characters** – Unicode, HTML entities, newlines.

### Response Shape Validation

All tool responses follow MCP content format:

```json
{
  "result": {
    "content": [{ "type": "text", "text": "..." }],
    "isError": false
  }
}
```

Error responses set `isError: true` and `text` contains a human-readable message.

## Data Lifecycle Testing

### CRUD Lifecycle Pattern

```
Create → Read (verify) → Update → Read (verify update) → Search (find)
```

For articles:
1. Create draft article with known title/body.
2. `get_article` to verify it exists with correct fields.
3. `update_article` to change title and body.
4. `get_article` to verify update applied (with retry for eventual consistency).
5. `search` to find it by title.

For tickets:
1. Create ticket with known subject and tags.
2. `get_ticket` to verify fields.
3. `update_ticket` to change status and add tags.
4. `get_ticket` to verify update.
5. `search` to find by subject.

### Eventual Consistency

Zendesk Help Center has eventual consistency. Article updates via the translations API may take 1-5 seconds to propagate to GET endpoints. Tests must use retry loops rather than immediate assertions.

## Input Validation and Boundary Testing

### Numeric Boundaries

| Parameter | Schema | Test values |
|-----------|--------|-------------|
| `per_page` | `1..100` | 0, 1, 50, 100, 101, -1, 999 |
| `page` | `min(1)` | 0, 1, 999999 |
| `id` | `number` | 0, -1, 999999999, NaN |

### String Boundaries

| Parameter | Schema | Test values |
|-----------|--------|-------------|
| `subject` | `max(300)` | empty, 1 char, 300 chars, 301 chars |
| `query` | `max(1000)` | empty, 1 char, 1000 chars, 1001 chars |
| `comment` | `max(65536)` | empty, 64KB, 65537 chars |

### Special Character Handling

- Unicode: `"Tëst Ünïcödé Tïtlé 日本語"` in titles/subjects.
- HTML entities in article bodies: `<script>alert('xss')</script>`.
- Newlines: `\n`, `\r\n`, `\r` in text fields.
- Very long single-line strings (no newlines).

## Security Testing

### Input Injection

Test that metacharacters don't cause unexpected behavior:

```javascript
const injectionPayloads = [
  '"; DROP TABLE tickets; --',      // SQL injection
  '<script>alert(1)</script>',       // XSS
  '{{constructor.constructor}}',     // Prototype pollution
  '../../../etc/passwd',             // Path traversal
  '`whoami`',                        // Command injection
  '${7*7}',                          // Template injection
];
```

For each payload, verify the server either rejects it or handles it as literal text.

### Credential Leak Prevention

- Error messages must never contain API tokens, passwords, or Base64 auth headers.
- Stack traces should not appear in tool error responses.
- The health endpoint should not expose sensitive configuration.

### Tool Poisoning Detection

Scan all tool descriptions and schemas for suspicious patterns:
- "ignore previous instructions"
- `<system>` tags
- ANSI escape sequences
- Base64-encoded payloads

### Rate Limiting

If configured, verify that exceeding the rate limit returns appropriate errors rather than crashing.

## Error Handling and Resilience

### Server Error Isolation

One failing tool call must not crash the SSE session. After an error, subsequent calls on the same session should still work.

### Non-existent Resources

- `get_ticket(999999999)` → clear error, not crash.
- `get_article(999999999)` → clear error, not crash.
- `update_ticket(999999999, ...)` → clear error.

### Invalid Argument Combinations

- `create_ticket` with only `subject` (missing `comment`) → schema validation error.
- `create_article` with only `title` (missing `body`, `section_id`) → schema validation error.
- `update_ticket` without `id` → schema validation error.

## Performance and Concurrency

### Concurrent Sessions

Open multiple SSE connections simultaneously. Each should:
- Get its own session ID.
- Execute tools independently.
- Not interfere with other sessions.

### Rapid Sequential Calls

Send 10+ tool calls in rapid succession on the same session. All should return correctly without dropped messages or out-of-order responses.

### Large Payloads

- Create article with 100KB HTML body.
- Search returning many results.

## Tooling and References

### Official Tools

| Tool | Purpose | URL |
|------|---------|-----|
| **MCP Inspector** | Browser-based interactive testing | `npx @modelcontextprotocol/inspector` |
| **MCP Conformance** | Specification compliance tests | github.com/modelcontextprotocol/conformance |
| **MCP Validator** | Protocol validation (Python) | github.com/Janix-ai/mcp-validator |

### Community Tools

| Tool | Purpose |
|------|---------|
| **mcp-testing-kit** | TypeScript test utilities (thoughtspot) |
| **mcp-scan** | Security vulnerability scanner |
| **mcp-check** | Turnkey conformance suites |
| **mcpjam Inspector** | LLM interaction testing |

### Key References

- [MCP Specification](https://modelcontextprotocol.io/docs)
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)
- [Merge.dev: 6 MCP Testing Best Practices](https://merge.dev/blog/mcp-server-testing)
- [Traceloop: Guide to Testing MCP Applications](https://www.traceloop.com/blog/a-guide-to-properly-testing-mcp-applications)
- [MCPcat Security Testing Guide](https://mcpcat.io/guides/security-tests-mcp-server-endpoints/)
- [Snyk: Building Secure MCP Servers](https://snyk.io/articles/building-secure-mcp-servers/)
- [Promptfoo: MCP Security Testing](https://www.promptfoo.dev/docs/red-team/mcp-security-testing/)

### Principles

1. **Test one thing at a time** – each test validates a single behavior.
2. **Use sandbox data exclusively** – never test against production.
3. **Make tests independent** – no test should depend on another's output (except explicit lifecycle chains).
4. **Use descriptive names** – test names should read like specifications.
5. **Fail fast, fail clear** – assertions should pinpoint exactly what went wrong.
6. **Tag test artifacts** – all created resources should be clearly marked as test data.
7. **Suppress notifications** – use test requesters/emails to avoid spamming real users.
