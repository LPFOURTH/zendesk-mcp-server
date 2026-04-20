from __future__ import annotations

import json
import os
import sys

import dotenv

dotenv.load_dotenv()

from .server import create_server, create_prod_server, create_dev_server
from .request_context import extract_request_context, set_request_context


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if "--transport" in sys.argv:
        idx = sys.argv.index("--transport")
        if idx + 1 < len(sys.argv):
            transport = sys.argv[idx + 1]

    if transport in ("http", "sse"):
        _run_http()
    else:
        mcp = create_server()
        print("[zendesk-mcp] Starting in stdio mode...", file=sys.stderr)
        mcp.run(transport="stdio")


def _run_http() -> None:
    import uvicorn
    from contextlib import asynccontextmanager
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.routing import Route

    port = int(os.environ.get("MCP_HTTP_PORT", "8000"))
    host = os.environ.get("MCP_HTTP_HOST", "0.0.0.0")

    health_body = json.dumps(
        {
            "status": "healthy",
            "service": "Zendesk MCP Server",
            "version": "3.0.0",
            "transports": ["streamable-http"],
        }
    )

    async def health(request: Request) -> Response:
        return Response(content=health_body, media_type="application/json")

    # Create two FastMCP instances: prod (no auth) and dev (AzureProvider)
    prod_server = create_prod_server()
    dev_server = create_dev_server()

    prod_app = prod_server.http_app(path="/mcp")
    dev_app = dev_server.http_app(path="/mcp")

    @asynccontextmanager
    async def combined_lifespan(app):
        async with prod_app.router.lifespan_context(app):
            async with dev_app.router.lifespan_context(app):
                yield

    parent = Starlette(
        routes=[
            Route("/", health, methods=["GET"]),
            Route("/health", health, methods=["GET"]),
        ],
        lifespan=combined_lifespan,
    )

    app = _make_routing_middleware(parent, prod_app, dev_app)

    print(f"[zendesk-mcp] HTTP server listening on {host}:{port}", file=sys.stderr)
    print(f"[zendesk-mcp] /mcp/prod  (no auth, service account)", file=sys.stderr)
    print(f"[zendesk-mcp] /mcp/dev   (Entra OAuth via AzureProvider)", file=sys.stderr)
    print(f"[zendesk-mcp] Health check: http://{host}:{port}/health", file=sys.stderr)

    uvicorn.run(app, host=host, port=port, log_level="warning")


def _make_routing_middleware(parent_app, prod_app, dev_app):
    """ASGI middleware that routes /mcp/prod and /mcp/dev to separate FastMCP
    apps, strips the prefix, injects environment contextvars, and adds CORS.

    FastMCP v3 AzureProvider handles OAuth endpoints, OIDC discovery, and auth
    enforcement automatically — no manual proxy logic needed."""

    CORS_HEADERS = [
        (b"access-control-allow-origin", b"*"),
        (b"access-control-expose-headers", b"Mcp-Session-Id"),
    ]

    PREFLIGHT_HEADERS = [
        (b"access-control-allow-origin", b"*"),
        (b"access-control-allow-methods", b"GET, POST, DELETE, OPTIONS"),
        (
            b"access-control-allow-headers",
            b"Content-Type, Authorization, Mcp-Session-Id, mcp-session-id, "
            b"X-Zendesk-Subdomain, X-Zendesk-Base-Url, X-Zendesk-Environment, "
            b"zendesk-subdomain, zendesk-base-url, zendesk-environment",
        ),
        (b"access-control-max-age", b"86400"),
    ]

    PREFIX_MAP = {
        "/mcp/prod": ("prod", prod_app),
        "/mcp/dev": ("dev", dev_app),
    }

    async def middleware(scope, receive, send):
        if scope["type"] != "http":
            await parent_app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")

        if method == "OPTIONS":
            await send({"type": "http.response.start", "status": 204, "headers": PREFLIGHT_HEADERS})
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                existing = list(message.get("headers", []))
                existing.extend(CORS_HEADERS)
                message = {**message, "headers": existing}
            await send(message)

        # Serve RFC 9728 oauth-protected-resource at the server root
        # (Claude Code looks here based on the origin of the MCP URL)
        if path == "/.well-known/oauth-protected-resource":
            public_url = os.environ.get("MCP_PUBLIC_URL", "")
            resource_body = json.dumps({
                "resource": f"{public_url}/mcp/dev",
                "authorization_servers": [f"{public_url}/mcp/dev"],
            }).encode()
            await send_with_cors({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": resource_body})
            return

        # Route other /.well-known/ paths to dev app (for OIDC discovery)
        if path.startswith("/.well-known/"):
            await dev_app(scope, receive, send_with_cors)
            return

        for prefix, (env_name, target_app) in PREFIX_MAP.items():
            if path.startswith(prefix):
                inner_path = path[len(prefix):] or "/mcp"

                # Serve RFC 9728 oauth-protected-resource for MCP clients (e.g. Claude Code)
                # AzureProvider only serves RFC 8414 oauth-authorization-server natively
                if inner_path in ("/.well-known/oauth-protected-resource",
                                  "/mcp/.well-known/oauth-protected-resource"):
                    public_url = os.environ.get("MCP_PUBLIC_URL", "")
                    resource_body = json.dumps({
                        "resource": f"{public_url}{prefix}",
                        "authorization_servers": [f"{public_url}{prefix}"],
                    }).encode()
                    await send_with_cors({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body", "body": resource_body})
                    return

                # Serve openid-configuration with OIDC-required fields
                # Claude Code's SDK requests openid-configuration and validates OIDC fields
                # (jwks_uri, subject_types_supported, id_token_signing_alg_values_supported)
                # that oauth-authorization-server doesn't include.
                if inner_path in ("/.well-known/openid-configuration",
                                  "/mcp/.well-known/openid-configuration"):
                    public_url = os.environ.get("MCP_PUBLIC_URL", "")
                    tenant_id = os.environ.get("ENTRA_TENANT_ID", "")
                    client_id = os.environ.get("ENTRA_CLIENT_ID", "")
                    oidc_body = json.dumps({
                        "issuer": f"{public_url}{prefix}",
                        "authorization_endpoint": f"{public_url}{prefix}/authorize",
                        "token_endpoint": f"{public_url}{prefix}/token",
                        "registration_endpoint": f"{public_url}{prefix}/register",
                        "jwks_uri": f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
                        "scopes_supported": [
                            f"api://{client_id}/access_as_user",
                            "openid", "profile", "email", "offline_access",
                        ],
                        "response_types_supported": ["code"],
                        "grant_types_supported": ["authorization_code", "refresh_token"],
                        "subject_types_supported": ["pairwise"],
                        "id_token_signing_alg_values_supported": ["RS256"],
                        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
                        "code_challenge_methods_supported": ["S256"],
                    }).encode()
                    await send_with_cors({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body", "body": oidc_body})
                    return

                inner_scope = {**scope, "path": inner_path, "root_path": scope.get("root_path", "") + prefix}

                # Inject zendesk-environment header for request context
                headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
                headers["zendesk-environment"] = env_name
                ctx = extract_request_context(headers)
                # Don't leak MCP auth tokens (Entra/FastMCP Bearer) to Zendesk API
                # The zendesk client should use its own credentials (API token)
                ctx["authorization"] = None
                set_request_context(ctx)

                session_id = headers.get("mcp-session-id", "none")
                print(f"[zendesk-mcp] {method} {path} (env: {env_name}, session: {session_id})", file=sys.stderr)

                # Route to the correct app — AzureProvider on dev_app enforces auth
                await target_app(inner_scope, receive, send_with_cors)
                return

        # No prefix matched — fall through to parent (health, etc.)
        await parent_app(scope, receive, send_with_cors)

    return middleware


if __name__ == "__main__":
    main()
