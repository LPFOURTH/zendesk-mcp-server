#!/usr/bin/env python3
"""
Interactive MCP Client for the Zendesk MCP Server.

Connects to the deployed server via SSE and lets you call any tool
from the command line. Purely local — nothing is pushed anywhere.

Usage:
    python tests/interactive_client.py [server-url]

Default server:
    https://fourth-zendesk-mcp-server.bluewave-95f931ef.northeurope.azurecontainerapps.io
"""

import http.client
import json
import ssl
import sys
import textwrap
import threading
import time
from urllib.parse import urlparse

SERVER = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "https://fourth-zendesk-mcp-server.bluewave-95f931ef.northeurope.azurecontainerapps.io"
)

parsed = urlparse(SERVER)
HOST = parsed.hostname
PORT = parsed.port or (443 if parsed.scheme == "https" else 80)
USE_SSL = parsed.scheme == "https"
SSL_CTX = ssl.create_default_context() if USE_SSL else None
if SSL_CTX is not None:
    SSL_CTX.check_hostname = False
    SSL_CTX.verify_mode = ssl.CERT_NONE

TOOL_HELP = {
    "list_tickets": {
        "desc": "List tickets (paginated)",
        "params": {
            "page": "int?",
            "per_page": "int? (1-100)",
            "sort_by": "str?",
            "sort_order": "asc|desc?",
        },
        "example": '{"per_page": 5}',
    },
    "get_ticket": {
        "desc": "Get a single ticket by ID",
        "params": {"id": "int (required)"},
        "example": '{"id": 12345}',
    },
    "create_ticket": {
        "desc": "Create a new ticket",
        "params": {
            "subject": "str (required, max 300)",
            "comment": "str (required, max 65536)",
            "priority": "urgent|high|normal|low?",
            "status": "new|open|pending|hold|solved|closed?",
            "type": "problem|incident|question|task?",
            "tags": "list[str]?",
        },
        "example": '{"subject": "Test ticket", "comment": "Hello from MCP", "priority": "low"}',
    },
    "update_ticket": {
        "desc": "Update an existing ticket",
        "params": {
            "id": "int (required)",
            "subject": "str?",
            "comment": "str?",
            "priority": "urgent|high|normal|low?",
            "status": "new|open|pending|hold|solved|closed?",
            "tags": "list[str]?",
        },
        "example": '{"id": 12345, "status": "pending", "comment": "Following up"}',
    },
    "list_articles": {
        "desc": "List Help Center articles (paginated)",
        "params": {
            "page": "int?",
            "per_page": "int? (1-100)",
            "sort_by": "str?",
            "sort_order": "asc|desc?",
        },
        "example": '{"per_page": 5}',
    },
    "get_article": {
        "desc": "Get an article by ID (includes body HTML)",
        "params": {"id": "int (required)"},
        "example": '{"id": 44001234567890}',
    },
    "create_article": {
        "desc": "Create a Help Center article in a section",
        "params": {
            "title": "str (required, max 500)",
            "body": "str (required, HTML)",
            "section_id": "int (required)",
            "locale": "str? (e.g. en-us)",
            "draft": "bool? (default true)",
            "permission_group_id": "int?",
        },
        "example": '{"title": "My Article", "body": "<p>Hello</p>", "section_id": 123, "draft": true}',
    },
    "update_article": {
        "desc": "Update an existing article (title/body via translations API)",
        "params": {
            "id": "int (required)",
            "title": "str?",
            "body": "str? (HTML)",
            "draft": "bool?",
        },
        "example": '{"id": 44001234567890, "title": "Updated Title"}',
    },
    "search": {
        "desc": "Search tickets, articles, users (Zendesk query syntax)",
        "params": {
            "query": "str (required, max 1000)",
            "sort_by": "str?",
            "sort_order": "asc|desc?",
            "page": "int?",
            "per_page": "int? (1-100)",
        },
        "example": '{"query": "type:ticket status:open", "per_page": 5}',
    },
    "create_release_note": {
        "desc": "Create a formatted release note from markdown",
        "params": {
            "markdown_content": "str (required) — ### Functionality N Name/Description",
            "use_us_template": "bool? (false=UK, true=US)",
            "section_id": "int (required)",
            "title": "str? (overrides auto title)",
            "permission_group_id": "int?",
        },
        "example": (
            '{"markdown_content": "### Functionality 1 Name\\nFeature'
            '\\n### Functionality 1 Description\\nDesc", "section_id": 123}'
        ),
    },
}

# ── HTTP helpers ─────────────────────────────────────────────────────────────


def _make_conn():
    """Return an HTTP(S) connection to the configured server."""
    if USE_SSL:
        return http.client.HTTPSConnection(HOST, PORT, context=SSL_CTX, timeout=30)
    return http.client.HTTPConnection(HOST, PORT, timeout=30)


def http_get(path):
    """Perform a synchronous GET request and return (status, body) as strings."""
    conn = _make_conn()
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    return resp.status, body


def http_post(path, data):
    """Perform a synchronous POST request with JSON body and return the status code."""
    body = json.dumps(data).encode()
    conn = _make_conn()
    conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    return resp.status


# ── SSE Session ──────────────────────────────────────────────────────────────


class MCPSession:
    """Manages a persistent SSE connection to the MCP server and dispatches JSON-RPC calls."""

    def __init__(self):
        """Initialise session state and synchronisation primitives."""
        self.endpoint = None
        self.session_id = None
        self._next_id = 1
        self._pending = {}
        self._lock = threading.Lock()
        self._connected = threading.Event()
        self._buf = ""

    def connect(self):
        """Start the background SSE listener thread and block until the session is established."""
        print(f"  Connecting to {SERVER}/sse ...")
        t = threading.Thread(target=self._sse_loop, daemon=True)
        t.start()
        if not self._connected.wait(timeout=30):
            raise TimeoutError(
                "SSE connection timed out (30s). Server may be cold-starting — try again."
            )

    def _sse_loop(self):  # pylint: disable=too-many-branches
        while True:
            try:
                if USE_SSL:
                    conn = http.client.HTTPSConnection(
                        HOST, PORT, context=SSL_CTX, timeout=300
                    )
                else:
                    conn = http.client.HTTPConnection(HOST, PORT, timeout=300)
                conn.request("GET", "/sse", headers={"Accept": "text/event-stream"})
                resp = conn.getresponse()

                self._buf = ""
                while True:
                    try:
                        line = resp.readline()
                    except http.client.IncompleteRead:
                        break
                    if not line:
                        break
                    self._buf += line.decode("utf-8", errors="replace")
                    self._process_events()
            except Exception as e:  # pylint: disable=broad-exception-caught
                if not self._connected.is_set():
                    print(f"\n  \033[31mSSE error: {e}\033[0m")
                    return

            if not self._connected.is_set():
                return

            # Connection dropped — reconnect
            time.sleep(1)
            print("\n  \033[33m(reconnecting SSE...)\033[0m")
            self.endpoint = None
            self._buf = ""
            try:
                if USE_SSL:
                    conn = http.client.HTTPSConnection(
                        HOST, PORT, context=SSL_CTX, timeout=300
                    )
                else:
                    conn = http.client.HTTPConnection(HOST, PORT, timeout=300)
                conn.request("GET", "/sse", headers={"Accept": "text/event-stream"})
                resp = conn.getresponse()
                while True:
                    try:
                        line = resp.readline()
                    except http.client.IncompleteRead:
                        break
                    if not line:
                        break
                    self._buf += line.decode("utf-8", errors="replace")
                    self._process_events()
            except Exception:  # pylint: disable=broad-exception-caught
                pass

    def _process_events(self):
        """Parse buffered SSE data, extract the session endpoint, and resolve pending calls."""
        if not self.endpoint:
            for line in self._buf.split("\n"):
                stripped = line.strip()
                if stripped.startswith("data:") and "sessionId=" in stripped:
                    self.endpoint = stripped.split("data:", 1)[1].strip()
                    try:
                        self.session_id = self.endpoint.split("sessionId=")[1].split(
                            "&"
                        )[0]
                    except IndexError:
                        self.session_id = "unknown"
                    self._connected.set()
                    break

        for part in self._buf.split("\nevent: message\ndata: ")[1:]:
            json_str = part.split("\n")[0]
            try:
                data = json.loads(json_str)
                rid = data.get("id")
                with self._lock:
                    if rid in self._pending:
                        self._pending[rid]["result"] = data
                        self._pending[rid]["event"].set()
            except (json.JSONDecodeError, KeyError):
                pass

    def call(self, method, params=None, timeout=60):
        """Send a JSON-RPC request and block until the response arrives or the timeout expires."""
        with self._lock:
            rid = self._next_id
            self._next_id += 1
            evt = threading.Event()
            self._pending[rid] = {"event": evt, "result": None}

        payload = json.dumps(
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        ).encode()
        http_post(self.endpoint, json.loads(payload))

        if not evt.wait(timeout=timeout):
            with self._lock:
                self._pending.pop(rid, None)
            raise TimeoutError(f"Timed out after {timeout}s")

        with self._lock:
            return self._pending.pop(rid)["result"]

    def call_tool(self, name, args=None):
        """Call a named MCP tool with optional arguments dict."""
        return self.call("tools/call", {"name": name, "arguments": args or {}})

    def list_tools(self):
        """Request the full list of available tools from the MCP server."""
        return self.call("tools/list", {})


# ── Output formatting ────────────────────────────────────────────────────────


def pretty(resp):
    """Print a JSON-RPC response to stdout, pretty-printing JSON content and colouring errors."""
    if resp.get("error"):
        err = resp["error"]
        print(
            f"\n  \033[31mERROR {err.get('code', '?')}: {err.get('message', '?')}\033[0m"
        )
        return

    result = resp.get("result", {})
    is_err = result.get("isError", False)
    for item in result.get("content", []):
        text = item.get("text", "")
        color = "\033[31m" if is_err else ""
        reset = "\033[0m" if color else ""
        try:
            obj = json.loads(text)
            formatted = json.dumps(obj, indent=2)
            if len(formatted) > 4000:
                print(
                    f"\n{color}{formatted[:4000]}{reset}\n  ... (truncated, {len(formatted)} chars)"
                )
            else:
                print(f"\n{color}{formatted}{reset}")
        except json.JSONDecodeError:
            if len(text) > 4000:
                print(f"\n{color}{text[:4000]}{reset}\n  ... (truncated)")
            else:
                print(f"\n{color}{text}{reset}")


def print_tools():
    """Print all available tools with their parameters and example invocations."""
    print("\n\033[1m  Available Tools (10):\033[0m\n")
    for name, info in TOOL_HELP.items():
        print(f"  \033[36m{name}\033[0m — {info['desc']}")
        for p, t in info["params"].items():
            print(f"      {p}: {t}")
        print(f"      \033[2mExample: {info['example']}\033[0m\n")


def print_help():
    """Print the REPL command reference."""
    print(textwrap.dedent("""
    \033[1m  Commands:\033[0m
      tools                      — List all tools with params and examples
      <tool_name> <json_args>    — Call a tool with JSON arguments
      <tool_name>                — Call a tool with empty/default args
      raw <method> <json_params> — Send any JSON-RPC method
      health                     — Check server health
      help                       — Show this help
      quit / exit / q            — Exit

    \033[1m  Quick examples:\033[0m
      list_tickets {"per_page": 3}
      get_ticket {"id": 12345}
      search {"query": "type:ticket status:open", "per_page": 5}
      list_articles {"per_page": 3}
      get_article {"id": 44001234567890}
    """))


# ── REPL ─────────────────────────────────────────────────────────────────────


def main():  # pylint: disable=too-many-branches,too-many-statements
    """Run the interactive REPL — connect to the MCP server and dispatch tool calls."""
    print(f"\n{'='*60}")
    print("  Zendesk MCP Interactive Client")
    print(f"  Server: {SERVER}")
    print(f"{'='*60}")

    # Warm up the container
    print("  Warming up server ...")
    try:
        _, body = http_get("/health")
        data = json.loads(body)
        print(f"  Health: {data.get('status')} (v{data.get('version')})\n")
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"  \033[33mHealth check: {e} (server may be cold-starting)\033[0m\n")

    session = MCPSession()
    try:
        session.connect()
        print(f"  Connected! Session: {session.session_id}\n")
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"\n  \033[31m{e}\033[0m")
        sys.exit(1)

    print_help()

    while True:
        try:
            line = input("\033[1mmcp>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Bye!")
            break

        if not line:
            continue
        if line in ("quit", "exit", "q"):
            print("  Bye!")
            break
        if line == "help":
            print_help()
            continue
        if line == "tools":
            print_tools()
            continue

        if line == "health":
            try:
                _, body = http_get("/health")
                print(f"\n  {json.dumps(json.loads(body), indent=2)}\n")
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"\n  \033[31m{e}\033[0m\n")
            continue

        if line.startswith("raw "):
            parts = line[4:].strip().split(" ", 1)
            method = parts[0]
            params = json.loads(parts[1]) if len(parts) > 1 else {}
            print(f"  Calling {method} ...")
            try:
                resp = session.call(method, params)
                pretty(resp)
            except Exception as e:  # pylint: disable=broad-exception-caught
                print(f"\n  \033[31m{e}\033[0m")
            print()
            continue

        parts = line.split(" ", 1)
        tool_name = parts[0]

        if tool_name not in TOOL_HELP:
            print(
                f"  \033[33mUnknown: '{tool_name}'. Type 'tools' for the list.\033[0m\n"
            )
            continue

        args = {}
        if len(parts) > 1:
            try:
                args = json.loads(parts[1])
            except json.JSONDecodeError as e:
                print(f"  \033[31mBad JSON: {e}\033[0m")
                print(
                    f"  \033[2mExample: {tool_name} {TOOL_HELP[tool_name]['example']}\033[0m\n"
                )
                continue

        print(f"  Calling {tool_name} ...")
        t0 = time.time()
        try:
            resp = session.call_tool(tool_name, args)
            pretty(resp)
            print(f"\n  \033[2m({time.time() - t0:.1f}s)\033[0m\n")
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"\n  \033[31m{e}\033[0m\n")


if __name__ == "__main__":
    main()
