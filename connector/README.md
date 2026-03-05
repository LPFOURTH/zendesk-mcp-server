# Zendesk MCP — CoPilot Studio Connector

These files define the Power Platform custom connector for the Zendesk MCP server,
following the same pattern as the Rally MCP connector.

## Files

| File | Purpose |
|------|---------|
| `openapidefinition.json` | Swagger/OpenAPI definition imported into Power Platform |
| `connectionparameters.json` | Defines per-user credential prompt (securestring) |

## How Per-User Auth Works

```
User → CoPilot Studio → Power Platform connector → Zendesk MCP Server → Zendesk API
                         ↑                          ↑
                   Injects user's stored       Reads Authorization header,
                   token into Authorization    forwards to Zendesk API.
                   header automatically.       Falls back to env vars if
                                               no header present.
```

1. **Connector import** — Import `openapidefinition.json` as a custom connector in Power Platform.
2. **Connection creation** — Each user creates a personal connection, entering their Zendesk auth token.
3. **Action config** — In the agent action, set `connectionProperties.mode: Invoker`.
4. **Server behavior** — The MCP server reads the `Authorization` header from each request and uses it
   for Zendesk API calls. If no header is present (e.g., local dev), it falls back to env vars.

## Auth Token Formats

Users can provide their token in either format:

### Option A: OAuth Bearer Token (recommended)
```
Bearer <zendesk_oauth_token>
```
Requires a Zendesk OAuth application. Tokens are scoped per-user.

### Option B: API Token (Basic Auth)
```
Basic <base64_encoded>
```
Where the base64 value encodes `email/token:api_token`. Generate with:
```bash
echo -n "user@example.com/token:your_api_token" | base64
```

## Copilot Studio Action YAML

```yaml
connectionReference: auto_agent_W5SKI.shared_fourth-zendesk-mcp.<guid>
connectionProperties:
  mode: Invoker

operationDetails:
  kind: ModelContextProtocolMetadata
  operationId: InvokeServer
```
