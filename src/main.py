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

    # Create two FastMCP instances: prod (no auth) and dev (Zendesk OAuthProxy)
    prod_server = create_prod_server()
    dev_server = create_dev_server()

    prod_app = prod_server.http_app(path="/mcp")
    # stateless_http=True on dev: works around Copilot Studio's MCP-connector
    # double-click consent bug. With state held client-side per request, the
    # consent flow doesn't depend on a session that gets recycled between
    # the first and second click. See Simon Doy 2025-11-18 + ADR (TODO).
    dev_app = dev_server.http_app(path="/mcp", stateless_http=True)

    @asynccontextmanager
    async def combined_lifespan(app):
        async with prod_app.router.lifespan_context(app):
            async with dev_app.router.lifespan_context(app):
                yield

    routes = [
        Route("/", health, methods=["GET"]),
        Route("/health", health, methods=["GET"]),
    ]

    # Architecture E (Path B) — Zendesk JWT SSO Remote Login URL.
    # Enabled when ZENDESK_JWT_SSO_SECRET + ENTRA_CLIENT_ID/TENANT_ID +
    # ZENDESK_PROD_SUBDOMAIN are set (typically via Key Vault refs in deploy).
    # When disabled, the route just isn't registered — Zendesk falls back to
    # its own login form. See spec
    # docs/superpowers/specs/2026-05-07-zendesk-jwt-sso-remote-login-design.md
    from .zendesk_sso_route import make_zendesk_sso_route_from_env
    zendesk_sso_handler = make_zendesk_sso_route_from_env()
    if zendesk_sso_handler is not None:
        routes.append(Route("/zendesk-sso", zendesk_sso_handler, methods=["GET", "POST"]))

    parent = Starlette(
        routes=routes,
        lifespan=combined_lifespan,
    )

    app = _make_routing_middleware(parent, prod_app, dev_app)

    print(f"[zendesk-mcp] HTTP server listening on {host}:{port}", file=sys.stderr)
    print(f"[zendesk-mcp] /mcp/prod  (no auth, service account)", file=sys.stderr)
    print(f"[zendesk-mcp] /mcp/dev   (Zendesk OAuth via OAuthProxy)", file=sys.stderr)
    if zendesk_sso_handler is not None:
        print(f"[zendesk-mcp] /zendesk-sso (Zendesk JWT SSO via Entra)", file=sys.stderr)
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

        # Route other /.well-known/ paths to the appropriate app.
        # RFC 8414 §3: clients construct the OAuth auth server metadata URL by
        # inserting /.well-known/oauth-authorization-server between host and
        # path — e.g. /.well-known/oauth-authorization-server/mcp/dev for an
        # auth server at /mcp/dev. FastMCP registers the route at
        # /.well-known/oauth-authorization-server (no suffix), so we strip the
        # /mcp/dev (or /mcp/prod) suffix before forwarding.
        # The RFC 9728 /.well-known/oauth-protected-resource/<path> URL does
        # encode the path suffix in its route, so we don't strip for that one.
        if path.startswith("/.well-known/"):
            target_app = dev_app
            target_path = path
            if not path.startswith("/.well-known/oauth-protected-resource"):
                for prefix, (_, app) in PREFIX_MAP.items():
                    if path.endswith(prefix):
                        target_app = app
                        target_path = path[: -len(prefix)]
                        break
            inner_scope = {**scope, "path": target_path}
            await target_app(inner_scope, receive, send_with_cors)
            return

        for prefix, (env_name, target_app) in PREFIX_MAP.items():
            if path.startswith(prefix):
                inner_path = path[len(prefix):] or "/mcp"

                # Inject missing Content-Type and Accept headers if absent
                # Power Platform custom connectors don't always send these,
                # but FastMCP Streamable HTTP requires them
                raw_headers = list(scope.get("headers", []))
                header_names = {k.decode("latin-1").lower() for k, _ in raw_headers}
                if "content-type" not in header_names and method == "POST":
                    raw_headers.append((b"content-type", b"application/json"))
                if "accept" not in header_names:
                    raw_headers.append((b"accept", b"application/json, text/event-stream"))

                inner_scope = {**scope, "path": inner_path, "root_path": scope.get("root_path", "") + prefix, "headers": raw_headers}

                # Inject zendesk-environment header for request context
                headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
                headers["zendesk-environment"] = env_name
                ctx = extract_request_context(headers)
                # Don't pass raw MCP Bearer token to ZendeskClient as-is.
                # ZendeskClient reads the upstream Zendesk token from
                # get_access_token() (via OAuthProxy token swap).
                ctx["authorization"] = None
                set_request_context(ctx)

                session_id = headers.get("mcp-session-id", "none")
                print(f"[zendesk-mcp] {method} {path} (env: {env_name}, session: {session_id})", file=sys.stderr)

                # Route to the correct app — OAuthProxy on dev_app enforces auth
                await target_app(inner_scope, receive, send_with_cors)
                return

        # No prefix matched — fall through to parent (health, etc.)
        await parent_app(scope, receive, send_with_cors)

    return middleware


if __name__ == "__main__":
    main()
