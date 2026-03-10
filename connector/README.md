# Zendesk MCP Connector

Use these files to create the Power Platform custom connector that fronts the Zendesk MCP server in Copilot Studio.

## Files

| File | Purpose |
|------|---------|
| `openapidefinition.json` | Swagger definition to import into Power Platform |
| `connectionparameters.json` | Per-user `Authorization` header secret |

## Request Model

Each request can provide:

- `Authorization`: the user's Zendesk auth header
- `zendesk-subdomain`: optional Zendesk target, such as `fourthsandbox`
- `zendesk-base-url`: optional full Zendesk host, such as `https://fourthsandbox.zendesk.com`
- `zendesk-environment`: optional environment selector (`dev` for sandbox, `prod` for production; default: `prod`)

The server also accepts `x-zendesk-subdomain`, `x-zendesk-base-url`, and `x-zendesk-environment`, but Copilot Studio custom connectors typically surface the non-`X-` names more reliably.

## How Per-User Auth Works

1. Import `openapidefinition.json` and `connectionparameters.json` into Power Platform.
2. Each user creates their own connection and stores an `Authorization` value.
3. In the Copilot Studio action, keep `connectionProperties.mode: Invoker`.
4. The server forwards the request `Authorization` header to Zendesk. If no auth header is present, local `.env` credentials are used as a fallback.

## Auth Header Formats

OAuth bearer token:

```text
Bearer <zendesk_oauth_token>
```

API token via Basic auth:

```text
Basic <base64(email/token:api_token)>
```

Generate the Basic value with:

```bash
echo -n "user@example.com/token:your_api_token" | base64
```

## Copilot Studio Action YAML

```yaml
connectionProperties:
  mode: Invoker

operationDetails:
  kind: ModelContextProtocolMetadata
  operationId: InvokeServer
```

## Sandbox vs Prod

Use one server instance for both environments by supplying either:

- `zendesk-subdomain: your-prod-subdomain`
- `zendesk-subdomain: your-sandbox-subdomain`

or:

- `zendesk-base-url: https://your-prod-subdomain.zendesk.com`
- `zendesk-base-url: https://your-sandbox-subdomain.zendesk.com`

If neither target header is sent, the server falls back to `ZENDESK_SUBDOMAIN` or `ZENDESK_BASE_URL` from the environment.
