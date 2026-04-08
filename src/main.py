from __future__ import annotations

import json
import os
import sys

import dotenv

dotenv.load_dotenv()

from .server import create_server
from .request_context import extract_request_context, set_request_context


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if "--transport" in sys.argv:
        idx = sys.argv.index("--transport")
        if idx + 1 < len(sys.argv):
            transport = sys.argv[idx + 1]

    mcp = create_server()

    if transport in ("http", "sse"):
        _run_http(mcp)
    else:
        print("[zendesk-mcp] Starting in stdio mode...", file=sys.stderr)
        mcp.run(transport="stdio")


def _run_http(mcp) -> None:
    import uvicorn
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.routing import Route

    port = int(os.environ.get("MCP_HTTP_PORT", "8000"))
    host = os.environ.get("MCP_HTTP_HOST", "0.0.0.0")

    health_body = json.dumps(
        {
            "status": "healthy",
            "service": "Zendesk MCP Server",
            "version": "2.0.0",
            "transports": ["streamable-http"],
        }
    )

    async def health(request: Request) -> Response:
        return Response(content=health_body, media_type="application/json")

    # Add health routes as custom routes to FastMCP's Starlette app
    mcp._custom_starlette_routes.extend([
        Route("/", health, methods=["GET"]),
        Route("/health", health, methods=["GET"]),
    ])

    # Build the MCP Starlette app (includes lifespan for session manager)
    starlette_app = mcp.streamable_http_app()

    # Wrap with ASGI middleware for context extraction and CORS
    app = _make_context_middleware(starlette_app)

    print(f"[zendesk-mcp] HTTP server listening on {host}:{port}", file=sys.stderr)
    print(
        f"[zendesk-mcp] Streamable HTTP: http://{host}:{port}/mcp",
        file=sys.stderr,
    )
    print(
        f"[zendesk-mcp] Health check:     http://{host}:{port}/health",
        file=sys.stderr,
    )

    uvicorn.run(app, host=host, port=port, log_level="warning")


def _make_context_middleware(app):
    """Pure ASGI middleware that extracts Zendesk headers and sets context vars.

    When ENTRA_CLIENT_ID and ENTRA_TENANT_ID are set, /mcp/dev requests
    require a valid Entra ID JWT. /mcp/prod is unaffected.
    """
    from .entra_auth import EntraValidator

    entra_validator = EntraValidator.from_env()

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

    async def middleware(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")

        # CORS preflight
        if method == "OPTIONS":
            await send(
                {
                    "type": "http.response.start",
                    "status": 204,
                    "headers": PREFLIGHT_HEADERS,
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        # Rewrite /mcp/dev and /mcp/prod to /mcp, injecting environment
        path_env = None
        if path == "/mcp/dev":
            path_env = "dev"
            scope = {**scope, "path": "/mcp"}

            # OAuth validation for /mcp/dev only
            if entra_validator and method == "POST":
                raw_headers = {
                    k.decode("latin-1").lower(): v.decode("latin-1")
                    for k, v in scope.get("headers", [])
                }
                auth_header = raw_headers.get("authorization", "")
                error = await entra_validator.validate(auth_header)
                if error:
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            *CORS_HEADERS,
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b'Bearer realm="zendesk-mcp"'),
                        ],
                    })
                    await send({
                        "type": "http.response.body",
                        "body": json.dumps({"error": error}).encode(),
                    })
                    return

        elif path == "/mcp/prod":
            path_env = "prod"
            scope = {**scope, "path": "/mcp"}

        # Extract headers into a dict
        headers = {}
        for key, value in scope.get("headers", []):
            headers[key.decode("latin-1").lower()] = value.decode("latin-1")

        # Path-based environment takes precedence over headers
        if path_env:
            headers["zendesk-environment"] = path_env

        ctx = extract_request_context(headers)
        set_request_context(ctx)

        auth_info = "yes" if ctx.get("authorization") else "no"
        target_info = (
            "yes"
            if ctx.get("zendesk_subdomain") or ctx.get("zendesk_base_url")
            else "no"
        )
        env_info = ctx.get("zendesk_environment") or "none"
        session_id = headers.get("mcp-session-id", "none")
        print(
            f"[zendesk-mcp] {method} {path} "
            f"(auth: {auth_info}, target: {target_info}, "
            f"env: {env_info}, session: {session_id})",
            file=sys.stderr,
        )

        # Inject CORS headers into responses
        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                existing = list(message.get("headers", []))
                existing.extend(CORS_HEADERS)
                message = {**message, "headers": existing}
            await send(message)

        await app(scope, receive, send_with_cors)

    return middleware


if __name__ == "__main__":
    main()
