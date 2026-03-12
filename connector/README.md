# Zendesk MCP Connector

Use these files to create the Power Platform custom connector that fronts the Zendesk MCP server in Copilot Studio.

## Files

### Active (API Key Auth)

| File | Purpose |
|------|---------|
| `openapidefinition.json` | Swagger definition — **prod** |
| `connectionparameters.json` | Connection params — **prod** |
| `openapidefinition-dev.json` | Swagger definition — **dev / sandbox** |
| `connectionparameters-dev.json` | Connection params — **dev / sandbox** |

### Future (OAuth 2.0) — ready to switch

| File | Purpose |
|------|---------|
| `openapidefinition-oauth.json` | Swagger with OAuth — **prod** |
| `connectionparameters-oauth.json` | OAuth connection params — **prod** |
| `openapidefinition-dev-oauth.json` | Swagger with OAuth — **dev / sandbox** |
| `connectionparameters-dev-oauth.json` | OAuth connection params — **dev / sandbox** |

## Setup: Two Connectors (Dev + Prod)

Import each pair as a separate custom connector in Copilot Studio:
- **"Fourth Zendesk MCP (Prod)"** — `openapidefinition.json` + `connectionparameters.json`
- **"Fourth Zendesk MCP (Dev)"** — `openapidefinition-dev.json` + `connectionparameters-dev.json`

### Step 1: Generate API Key Tokens

For each Zendesk instance, generate a Base64-encoded auth token:

```bash
# Prod
echo -n "your-email@fourth.com/token:your_prod_api_token" | base64

# Dev (sandbox)
echo -n "your-email@fourth.com/token:your_dev_api_token" | base64
```

Prepend `Basic ` to the output. Example: `Basic dXNlckBleGFtcGxlLmNvbS90b2tlbjp5b3VyX2FwaV90b2tlbg==`

### Step 2: Import Connectors

1. Go to **Power Platform** → **Custom Connectors** → **+ New** → **Import an OpenAPI file**
2. Upload `openapidefinition.json`, name it **"Fourth Zendesk MCP (Prod)"**
3. Save the connector
4. Repeat with `openapidefinition-dev.json`, name it **"Fourth Zendesk MCP (Dev)"**

### Step 3: Create Connections

1. **Connections** → **+ New connection** → pick **Fourth Zendesk MCP (Prod)**
2. Paste the prod `Basic <token>` value
3. Repeat for **Fourth Zendesk MCP (Dev)** with the dev token

### Step 4: Use in Copilot Studio

Add both connectors as actions in your Copilot:

```yaml
connectionProperties:
  mode: Invoker

operationDetails:
  kind: ModelContextProtocolMetadata
  operationId: InvokeServer
```

## How It Works

1. Each connector creates a connection with a `Basic <token>` Authorization header
2. On each request, Copilot Studio sends `Authorization: Basic <token>`
3. The MCP server forwards the `Authorization` header as-is to Zendesk
4. The dev connector hits the sandbox, the prod connector hits production

Environment variable credentials (`ZENDESK_EMAIL`, `ZENDESK_API_TOKEN`) remain as a fallback for local/stdio use.

## Request Headers

Each request can optionally include:

| Header | Purpose |
|--------|---------|
| `zendesk-subdomain` | Target a specific Zendesk instance (e.g., `fourthsandbox`) |
| `zendesk-base-url` | Full Zendesk URL (e.g., `https://fourthsandbox.zendesk.com`) |
| `zendesk-environment` | `dev` for sandbox, `prod` for production (default: `prod`) |

## Switching to OAuth Later

When ready to switch to OAuth 2.0:
1. Create OAuth clients in Zendesk (see `*-oauth.json` files for URLs)
2. Replace the active files with the `-oauth` variants
3. Re-import connectors in Copilot Studio
4. Users will authenticate via Zendesk consent screen instead of pasting tokens
