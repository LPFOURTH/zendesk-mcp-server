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

    # Build both Streamable HTTP (/mcp) and SSE (/sse + /messages) apps
    starlette_app = mcp.streamable_http_app()

    # Combine with SSE for backwards compatibility
    try:
        sse_app = mcp.sse_app()
        has_sse = True
    except Exception:
        sse_app = None
        has_sse = False

    if has_sse:
        # Route /sse and /messages to SSE app, everything else to Streamable HTTP
        original_app = starlette_app

        async def combined_app(scope, receive, send):
            path = scope.get("path", "")
            if path in ("/sse", "/messages", "/messages/"):
                await sse_app(scope, receive, send)
            else:
                await original_app(scope, receive, send)

        starlette_app = combined_app

    # Wrap with ASGI middleware for context extraction and CORS
    app = _make_context_middleware(starlette_app)

    print(f"[zendesk-mcp] HTTP server listening on {host}:{port}", file=sys.stderr)
    print(
        f"[zendesk-mcp] Streamable HTTP: http://{host}:{port}/mcp",
        file=sys.stderr,
    )
    if has_sse:
        print(
            f"[zendesk-mcp] SSE (legacy):     http://{host}:{port}/sse",
            file=sys.stderr,
        )
    print(
        f"[zendesk-mcp] Health check:     http://{host}:{port}/health",
        file=sys.stderr,
    )

    uvicorn.run(app, host=host, port=port, log_level="warning")


def _make_context_middleware(app):
    """Pure ASGI middleware that extracts Zendesk headers and sets context vars."""

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

        # For POST requests, buffer the body so we can inspect JSON-RPC method.
        # If it's an "initialize" request, strip any stale Mcp-Session-Id header
        # so the server always creates a fresh session.  This works around MCP
        # clients (e.g. Cursor) that cache a session ID across reconnects and
        # don't retry without it when the server returns 404.
        actual_receive = receive
        if method == "POST":
            body_chunks = []
            more = True
            while more:
                message = await receive()
                body_chunks.append(message.get("body", b""))
                more = message.get("more_body", False)
            body = b"".join(body_chunks)

            is_initialize = False
            try:
                payload = json.loads(body)
                if isinstance(payload, dict) and payload.get("method") == "initialize":
                    is_initialize = True
                elif isinstance(payload, list):
                    is_initialize = any(
                        isinstance(r, dict) and r.get("method") == "initialize"
                        for r in payload
                    )
            except (json.JSONDecodeError, TypeError):
                pass

            if is_initialize:
                raw_headers = [
                    (k, v)
                    for k, v in scope.get("headers", [])
                    if k.lower() != b"mcp-session-id"
                ]
                scope = {**scope, "headers": raw_headers}

            body_sent = False

            async def replay_receive():
                nonlocal body_sent
                if not body_sent:
                    body_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            actual_receive = replay_receive

        # Inject CORS headers into responses
        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                existing = list(message.get("headers", []))
                existing.extend(CORS_HEADERS)
                message = {**message, "headers": existing}
            await send(message)

        await app(scope, actual_receive, send_with_cors)

    return middleware


if __name__ == "__main__":
    main()
