from __future__ import annotations

import json
import os
import sys

from mcp.server.fastmcp import FastMCP

from .tools import tickets, help_center, search, release_notes


def _load_tools_config() -> dict:
    config_path = os.environ.get(
        "TOOLS_CONFIG",
        os.path.join(os.path.dirname(__file__), "..", "tools.config.json"),
    )
    try:
        with open(config_path) as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[zendesk-mcp] No tools.config.json found ({exc}), using defaults", file=sys.stderr)
        return {"enabled": None, "disabled": set(), "source": "defaults"}

    preset = os.environ.get("TOOLS_PRESET")
    if preset and preset in config.get("presets", {}):
        p = config["presets"][preset]
        print(
            f"[zendesk-mcp] Using preset: {preset} — {p.get('_description', '')}",
            file=sys.stderr,
        )
        return {
            "enabled": set(p.get("enable", [])),
            "disabled": set(p.get("disable", [])),
            "source": f"preset:{preset}",
        }

    disabled = set()
    enabled = set()
    for name, cfg in config.get("tools", {}).items():
        if cfg.get("enabled") is False:
            disabled.add(name)
        else:
            enabled.add(name)
    return {"enabled": enabled, "disabled": disabled, "source": config_path}


ALL_TOOLS = [
    # -- tickets --
    {
        "name": "list_tickets",
        "description": (
            "List Zendesk tickets with pagination, sorting, and optional status "
            "filtering. Use this for recent tickets, open tickets, and paged ticket "
            "lists instead of the generic search tool."
        ),
        "parameters": {
            "page": {"type": "integer", "description": "Page number for pagination", "required": False},
            "per_page": {"type": "integer", "description": "Number of tickets per page (1-100)", "required": False},
            "status": {"type": "string", "description": "Optional ticket status filter", "required": False, "enum": ["new", "open", "pending", "hold", "solved", "closed"]},
            "sort_by": {"type": "string", "description": "Field to sort by", "required": False},
            "sort_order": {"type": "string", "description": "Sort order (asc or desc)", "required": False, "enum": ["asc", "desc"]},
        },
        "fn": tickets.list_tickets,
    },
    {
        "name": "get_ticket",
        "description": "Get a specific ticket by ID, including all comments and metadata.",
        "parameters": {
            "id": {"type": "integer", "description": "Ticket ID", "required": True},
        },
        "fn": tickets.get_ticket,
    },
    {
        "name": "create_ticket",
        "description": "Create a new support ticket in Zendesk.",
        "parameters": {
            "subject": {"type": "string", "description": "Ticket subject", "required": True},
            "comment": {"type": "string", "description": "Ticket comment/description", "required": True},
            "priority": {"type": "string", "description": "Ticket priority", "required": False, "enum": ["urgent", "high", "normal", "low"]},
            "status": {"type": "string", "description": "Ticket status", "required": False, "enum": ["new", "open", "pending", "hold", "solved", "closed"]},
            "requester_id": {"type": "integer", "description": "User ID of the requester", "required": False},
            "assignee_id": {"type": "integer", "description": "User ID of the assignee", "required": False},
            "group_id": {"type": "integer", "description": "Group ID for the ticket", "required": False},
            "type": {"type": "string", "description": "Ticket type", "required": False, "enum": ["problem", "incident", "question", "task"]},
            "tags": {"type": "array", "description": "Tags for the ticket", "required": False},
        },
        "fn": tickets.create_ticket,
    },
    {
        "name": "update_ticket",
        "description": (
            "Update an existing ticket. Only provided fields will be changed. "
            "Use internal_note=true for private comments visible only to agents. "
            "Messaging-channel tickets may not allow comments — if you get a 422 error, "
            "retry without the comment field."
        ),
        "parameters": {
            "id": {"type": "integer", "description": "Ticket ID to update", "required": True},
            "subject": {"type": "string", "description": "Updated ticket subject", "required": False},
            "comment": {"type": "string", "description": "New comment to add to the ticket", "required": False},
            "internal_note": {"type": "boolean", "description": "If true, the comment is an internal note (private, visible to agents only). Defaults to false (public comment).", "required": False},
            "priority": {"type": "string", "description": "Updated ticket priority", "required": False, "enum": ["urgent", "high", "normal", "low"]},
            "status": {"type": "string", "description": "Updated ticket status", "required": False, "enum": ["new", "open", "pending", "hold", "solved", "closed"]},
            "assignee_id": {"type": "integer", "description": "User ID of the new assignee", "required": False},
            "group_id": {"type": "integer", "description": "New group ID for the ticket", "required": False},
            "type": {"type": "string", "description": "Updated ticket type", "required": False, "enum": ["problem", "incident", "question", "task"]},
            "tags": {"type": "array", "description": "Updated tags for the ticket", "required": False},
        },
        "fn": tickets.update_ticket,
    },
    # -- help center --
    {
        "name": "list_articles",
        "description": "List Help Center articles. Returns paginated results.",
        "parameters": {
            "page": {"type": "integer", "description": "Page number for pagination", "required": False},
            "per_page": {"type": "integer", "description": "Number of articles per page (1-100)", "required": False},
            "sort_by": {"type": "string", "description": "Field to sort by", "required": False},
            "sort_order": {"type": "string", "description": "Sort order (asc or desc)", "required": False, "enum": ["asc", "desc"]},
        },
        "fn": help_center.list_articles,
    },
    {
        "name": "get_article",
        "description": "Get a specific Help Center article by ID, including body content.",
        "parameters": {
            "id": {"type": "integer", "description": "Article ID", "required": True},
        },
        "fn": help_center.get_article,
    },
    {
        "name": "create_article",
        "description": "Create a new Help Center article in a specified section.",
        "parameters": {
            "title": {"type": "string", "description": "Article title", "required": True},
            "body": {"type": "string", "description": "Article body content (HTML)", "required": True},
            "section_id": {"type": "integer", "description": "Section ID where the article will be created", "required": True},
            "locale": {"type": "string", "description": "Article locale (e.g., 'en-us')", "required": False},
            "draft": {"type": "boolean", "description": "Whether the article is a draft", "required": False},
            "permission_group_id": {"type": "integer", "description": "Permission group ID for the article", "required": False},
            "user_segment_id": {"type": "integer", "description": "User segment ID for the article", "required": False},
            "label_names": {"type": "array", "description": "Labels for the article", "required": False},
        },
        "fn": help_center.create_article,
    },
    {
        "name": "update_article",
        "description": "Update an existing Help Center article. Only provided fields will be changed.",
        "parameters": {
            "id": {"type": "integer", "description": "Article ID to update", "required": True},
            "title": {"type": "string", "description": "Updated article title", "required": False},
            "body": {"type": "string", "description": "Updated article body content (HTML)", "required": False},
            "locale": {"type": "string", "description": "Updated article locale (e.g., 'en-us')", "required": False},
            "draft": {"type": "boolean", "description": "Whether the article is a draft", "required": False},
            "permission_group_id": {"type": "integer", "description": "Updated permission group ID", "required": False},
            "user_segment_id": {"type": "integer", "description": "Updated user segment ID", "required": False},
            "label_names": {"type": "array", "description": "Updated labels", "required": False},
        },
        "fn": help_center.update_article,
    },
    # -- search --
    {
        "name": "search",
        "description": (
            "Keyword-search Zendesk tickets or Help Center articles. Set scope=tickets "
            "for ticket searches and scope=articles for Help Center article searches. "
            "Use this only when the user explicitly asks to search; for listing, sorting, "
            "pagination, or direct ticket/article lookup, prefer list_tickets, list_articles, "
            "get_ticket, or get_article."
        ),
        "parameters": {
            "query": {"type": "string", "description": "Search keywords or Zendesk query string", "required": True},
            "scope": {"type": "string", "description": "Search scope: tickets for Zendesk tickets, articles for Help Center articles, or all for mixed search", "required": False, "enum": ["all", "tickets", "articles"]},
            "sort_by": {"type": "string", "description": "Field to sort by", "required": False},
            "sort_order": {"type": "string", "description": "Sort order (asc or desc)", "required": False, "enum": ["asc", "desc"]},
            "page": {"type": "integer", "description": "Page number for pagination", "required": False},
            "per_page": {"type": "integer", "description": "Number of results per page (1-100)", "required": False},
        },
        "fn": search.search,
    },
    # -- release notes --
    {
        "name": "create_release_note",
        "description": (
            "Create a Zendesk Help Center release note article from structured markdown. "
            'Parses "### Functionality N Name / Description" sections, assembles HTML '
            "using the UK or US template, and creates a draft article via the Zendesk API. "
            "Section ID, permission group, user segment, and author are automatically "
            "resolved from the environment (dev/prod). Only markdown_content is required."
        ),
        "parameters": {
            "markdown_content": {"type": "string", "description": 'Markdown content with "### Functionality N Name" and "### Functionality N Description" sections', "required": True},
            "use_us_template": {"type": "boolean", "description": "Use the US release note template (default: false = UK template)", "required": False},
            "title": {"type": "string", "description": "Custom article title. If omitted, auto-generated from feature names.", "required": False},
        },
        "fn": release_notes.create_release_note,
    },
]


def create_server() -> FastMCP:
    config = _load_tools_config()

    env_disabled = {
        t.strip()
        for t in os.environ.get("DISABLED_TOOLS", "").split(",")
        if t.strip()
    }
    all_disabled = config["disabled"] | env_disabled

    enabled_tools = []
    for tool in ALL_TOOLS:
        if tool["name"] in all_disabled:
            continue
        if config["enabled"] is not None and tool["name"] not in config["enabled"]:
            continue
        enabled_tools.append(tool)

    print(f"[zendesk-mcp] Config source: {config['source']}", file=sys.stderr)
    print(
        f"[zendesk-mcp] Registered {len(enabled_tools)}/{len(ALL_TOOLS)} tools: "
        f"{', '.join(t['name'] for t in enabled_tools)}",
        file=sys.stderr,
    )
    if all_disabled:
        print(
            f"[zendesk-mcp] Disabled: {', '.join(sorted(all_disabled))}",
            file=sys.stderr,
        )

    mcp = FastMCP(
        "Zendesk API",
        instructions=(
            "MCP Server for Zendesk API - Tickets & Articles "
            "(read/create/update only, no delete operations)"
        ),
        host=os.environ.get("MCP_HTTP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_HTTP_PORT", "8000")),
    )

    # Disable DNS rebinding protection for production deployment
    # (Azure Container Apps uses custom hostnames)
    if mcp.settings.transport_security:
        mcp.settings.transport_security.enable_dns_rebinding_protection = False

    for tool_def in enabled_tools:
        fn = tool_def["fn"]
        mcp.tool(
            name=tool_def["name"],
            description=tool_def["description"],
        )(fn)

    return mcp
