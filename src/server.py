"""FastMCP server for the Zendesk MCP integration."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from fastmcp import FastMCP

from .tools import tickets, help_center, search, release_notes, community


# Tools that must NEVER fail-open. If tools.config.json is missing/corrupt,
# these stay disabled regardless of fallback behaviour.
#
# v3.10.3: create_it_ticket removed from the fail-closed set — it's now the
# primary IT-ticket creation tool and replaces create_ticket. create_ticket
# (the generic one) is now in the set since it's been deprecated and we
# don't want a broken config to accidentally surface a deprecated tool that
# bypasses IT-form categorization.
_FAIL_CLOSED_TOOLS: frozenset[str] = frozenset({"create_ticket"})


def _load_tools_config() -> dict:
    config_path = os.environ.get(
        "TOOLS_CONFIG",
        os.path.join(os.path.dirname(__file__), "..", "tools.config.json"),
    )
    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"[zendesk-mcp] No tools.config.json found ({exc}), using defaults "
            f"— fail-closed tools stay disabled: {sorted(_FAIL_CLOSED_TOOLS)}",
            file=sys.stderr,
        )
        return {
            "enabled": None,
            "disabled": set(_FAIL_CLOSED_TOOLS),
            "source": "defaults+fail-closed",
        }

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


ALL_TOOLS: list[dict[str, Any]] = [
    # -- tickets --
    {
        "name": "list_tickets",
        "description": (
            "List Zendesk tickets with pagination, sorting, and optional status "
            "filtering. Use this for recent tickets, open tickets, and paged ticket "
            "lists instead of the generic search tool."
        ),
        "parameters": {
            "page": {
                "type": "integer",
                "description": "Page number for pagination",
                "required": False,
            },
            "per_page": {
                "type": "integer",
                "description": "Number of tickets per page (1-100)",
                "required": False,
            },
            "status": {
                "type": "string",
                "description": "Optional ticket status filter",
                "required": False,
                "enum": ["new", "open", "pending", "hold", "solved", "closed"],
            },
            "sort_by": {
                "type": "string",
                "description": "Field to sort by",
                "required": False,
            },
            "sort_order": {
                "type": "string",
                "description": "Sort order (asc or desc)",
                "required": False,
                "enum": ["asc", "desc"],
            },
        },
        "fn": tickets.list_tickets,
    },
    {
        "name": "get_ticket",
        "description": (
            "Get a specific ticket by ID, including all comments and metadata. "
            "REQUIRES `ticket_id` (integer). Also accepts legacy alias `id` for "
            "backward compatibility with saved Copilot Studio actions."
        ),
        "parameters": {
            "ticket_id": {
                "type": "integer",
                "description": "Ticket ID",
                "required": True,
            },
        },
        "fn": tickets.get_ticket,
    },
    {
        "name": "create_ticket",
        "description": "Create a new support ticket in Zendesk.",
        "parameters": {
            "subject": {
                "type": "string",
                "description": "Ticket subject",
                "required": True,
            },
            "comment": {
                "type": "string",
                "description": "Ticket comment/description",
                "required": True,
            },
            "priority": {
                "type": "string",
                "description": "Ticket priority",
                "required": False,
                "enum": ["urgent", "high", "normal", "low"],
            },
            "status": {
                "type": "string",
                "description": "Ticket status",
                "required": False,
                "enum": ["new", "open", "pending", "hold", "solved", "closed"],
            },
            "assignee_id": {
                "type": "integer",
                "description": "User ID of the assignee",
                "required": False,
            },
            "group_id": {
                "type": "integer",
                "description": "Group ID for the ticket",
                "required": False,
            },
            "ticket_type": {
                "type": "string",
                "description": "Ticket type",
                "required": False,
                "enum": ["problem", "incident", "question", "task"],
            },
            "tags": {
                "type": "array",
                "description": "Tags for the ticket",
                "required": False,
            },
        },
        "fn": tickets.create_ticket,
    },
    {
        "name": "create_it_ticket",
        "description": (
            "Create an IT Support Request ticket using the company's standard IT form. "
            "Use this instead of create_ticket for all internal IT requests. "
            "Follow the classification hierarchy: "
            "(1) Set classification to 'incident' (something broken) or 'service_request' (need something). "
            "(2) Set incident_category OR sr_category (matching classification) to one of: "
            "bizapps | eit_software | eit_hardware | eit_general | eit_security_ops. "
            "(3) Set the matching L3 field: incident+bizapps→incident_bizapps_item, "
            "incident+eit_software→incident_software_item, "
            "incident+eit_hardware→incident_hardware_item, "
            "incident+eit_security_ops→incident_security_item, "
            "service_request+bizapps→sr_bizapps_item, "
            "service_request+eit_software→sr_software_item, "
            "service_request+eit_hardware→sr_hardware_item, "
            "service_request+eit_security_ops→sr_security_item, "
            "either+eit_general→eit_general_subcategory. "
            "(4) For eit_general_subcategory, also set the L4 field when applicable: "
            "access_request→access_request_type, distribution_list→distribution_list_action, "
            "fourth_office→fourth_office_type, email_trace→email_trace_type, "
            "restore_lost_data→restore_data_type, virtual_machine→virtual_machine_type. "
            "Always set impact and location. Do not set both incident_category and sr_category."
        ),
        "parameters": {
            "subject": {
                "type": "string",
                "description": "One-line summary of the issue or request",
                "required": True,
            },
            "description": {
                "type": "string",
                "description": "Full description: what the user was doing, what went wrong, steps taken, outcome",
                "required": True,
            },
            "classification": {
                "type": "string",
                "required": True,
                "enum": ["incident", "service_request"],
            },
            "incident_category": {
                "type": "string",
                "required": False,
                "enum": [
                    # dev
                    "bizapps",
                    "eit_software",
                    "eit_hardware",
                    "eit_general",
                    "eit_security_ops",
                    # prod
                    "software",
                    "hardware",
                    "email_collaboration",
                    "network",
                    "access_management",
                    "security",
                    "facilities_office",
                    "other",
                ],
            },
            "sr_category": {
                "type": "string",
                "required": False,
                "enum": [
                    # dev
                    "bizapps",
                    "eit_software",
                    "eit_hardware",
                    "eit_general",
                    "eit_security_ops",
                    # prod
                    "software",
                    "application_access_request",
                    "create_distribution_group",
                    "desk_office_move",
                    "dev_access",
                    "email_trace",
                    "file_restores",
                    "fileshares",
                    "gdpr_request",
                    "lad_maintenance",
                    "leaver_request",
                    "new_software_request",
                    "new_starter",
                    "unblock_website",
                    "update_distribution_group",
                    "other",
                ],
            },
            "incident_email_collab_item": {
                "type": "string",
                "required": False,
                "description": "Prod only. For incident + email_collaboration category.",
                "enum": ["confluence", "outlook", "sharepoint", "slack", "teams"],
            },
            "incident_network_item": {
                "type": "string",
                "required": False,
                "description": "Prod only. For incident + network category.",
                "enum": ["internet", "vpn", "wifi", "slow_connection"],
            },
            "incident_access_mgmt_item": {
                "type": "string",
                "required": False,
                "description": "Prod only. For incident + access_management category.",
                "enum": ["account_lockout", "mfa", "password_reset"],
            },
            "incident_facilities_item": {
                "type": "string",
                "required": False,
                "description": "Prod only. For incident + facilities_office category.",
                "enum": [
                    "door_access",
                    "meeting_rooms",
                    "display_tvs",
                    "printer",
                    "video_conferencing",
                ],
            },
            "impact": {
                "type": "string",
                "required": False,
                "enum": ["low", "medium", "high", "very_high"],
            },
            "location": {
                "type": "string",
                "required": False,
                "description": "User's current office or remote location",
            },
            "priority": {
                "type": "string",
                "required": False,
                "enum": ["low", "normal", "high", "urgent"],
            },
        },
        "fn": tickets.create_it_ticket,
    },
    {
        "name": "update_ticket",
        "description": (
            "Update an existing ticket. REQUIRES `ticket_id` (integer); also accepts "
            "legacy alias `id`. Only provided fields will be changed. "
            "Use internal_note=true for private comments visible only to agents. "
            "Messaging-channel tickets may not allow comments — if you get a 422 error, "
            "retry without the comment field."
        ),
        "parameters": {
            "ticket_id": {
                "type": "integer",
                "description": "Ticket ID to update",
                "required": True,
            },
            "subject": {
                "type": "string",
                "description": "Updated ticket subject",
                "required": False,
            },
            "comment": {
                "type": "string",
                "description": "New comment to add to the ticket",
                "required": False,
            },
            "internal_note": {
                "type": "boolean",
                "description": (
                    "If true, the comment is an internal note (private, visible to agents only)."
                    " Defaults to false (public comment)."
                ),
                "required": False,
            },
            "priority": {
                "type": "string",
                "description": "Updated ticket priority",
                "required": False,
                "enum": ["urgent", "high", "normal", "low"],
            },
            "status": {
                "type": "string",
                "description": "Updated ticket status",
                "required": False,
                "enum": ["new", "open", "pending", "hold", "solved", "closed"],
            },
            "assignee_id": {
                "type": "integer",
                "description": "User ID of the new assignee",
                "required": False,
            },
            "group_id": {
                "type": "integer",
                "description": "New group ID for the ticket",
                "required": False,
            },
            "ticket_type": {
                "type": "string",
                "description": "Updated ticket type",
                "required": False,
                "enum": ["problem", "incident", "question", "task"],
            },
            "tags": {
                "type": "array",
                "description": "Updated tags for the ticket",
                "required": False,
            },
        },
        "fn": tickets.update_ticket,
    },
    # -- help center --
    {
        "name": "list_articles",
        "description": "List Help Center articles. Returns paginated results.",
        "parameters": {
            "page": {
                "type": "integer",
                "description": "Page number for pagination",
                "required": False,
            },
            "per_page": {
                "type": "integer",
                "description": "Number of articles per page (1-100)",
                "required": False,
            },
            "sort_by": {
                "type": "string",
                "description": "Field to sort by",
                "required": False,
            },
            "sort_order": {
                "type": "string",
                "description": "Sort order (asc or desc)",
                "required": False,
                "enum": ["asc", "desc"],
            },
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
            "title": {
                "type": "string",
                "description": "Article title",
                "required": True,
            },
            "body": {
                "type": "string",
                "description": "Article body content (HTML)",
                "required": True,
            },
            "section_id": {
                "type": "integer",
                "description": "Section ID where the article will be created",
                "required": True,
            },
            "locale": {
                "type": "string",
                "description": "Article locale (e.g., 'en-us')",
                "required": False,
            },
            "draft": {
                "type": "boolean",
                "description": "Whether the article is a draft",
                "required": False,
            },
            "permission_group_id": {
                "type": "integer",
                "description": "Permission group ID for the article",
                "required": False,
            },
            "user_segment_id": {
                "type": "integer",
                "description": "User segment ID for the article",
                "required": False,
            },
            "label_names": {
                "type": "array",
                "description": "Labels for the article",
                "required": False,
            },
        },
        "fn": help_center.create_article,
    },
    {
        "name": "update_article",
        "description": "Update an existing Help Center article. Only provided fields will be changed.",
        "parameters": {
            "id": {
                "type": "integer",
                "description": "Article ID to update",
                "required": True,
            },
            "title": {
                "type": "string",
                "description": "Updated article title",
                "required": False,
            },
            "body": {
                "type": "string",
                "description": "Updated article body content (HTML)",
                "required": False,
            },
            "locale": {
                "type": "string",
                "description": "Updated article locale (e.g., 'en-us')",
                "required": False,
            },
            "draft": {
                "type": "boolean",
                "description": "Whether the article is a draft",
                "required": False,
            },
            "permission_group_id": {
                "type": "integer",
                "description": "Updated permission group ID",
                "required": False,
            },
            "user_segment_id": {
                "type": "integer",
                "description": "Updated user segment ID",
                "required": False,
            },
            "label_names": {
                "type": "array",
                "description": "Updated labels",
                "required": False,
            },
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
            "query": {
                "type": "string",
                "description": "Search keywords or Zendesk query string",
                "required": True,
            },
            "scope": {
                "type": "string",
                "description": (
                    "Search scope: tickets for Zendesk tickets, articles for Help Center"
                    " articles, or all for mixed search"
                ),
                "required": False,
                "enum": ["all", "tickets", "articles"],
            },
            "sort_by": {
                "type": "string",
                "description": "Field to sort by",
                "required": False,
            },
            "sort_order": {
                "type": "string",
                "description": "Sort order (asc or desc)",
                "required": False,
                "enum": ["asc", "desc"],
            },
            "page": {
                "type": "integer",
                "description": "Page number for pagination",
                "required": False,
            },
            "per_page": {
                "type": "integer",
                "description": "Number of results per page (1-100)",
                "required": False,
            },
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
            "markdown_content": {
                "type": "string",
                "description": (
                    'Markdown content with "### Functionality N Name"' ' and "### Functionality N Description" sections'
                ),
                "required": True,
            },
            "use_us_template": {
                "type": "boolean",
                "description": "Use the US release note template (default: false = UK template)",
                "required": False,
            },
        },
        "fn": release_notes.create_release_note,
    },
    # -- community ideas --
    {
        "name": "list_ideas",
        "description": (
            "List community Ideas posts with filtering by topic, tag, and status. "
            "Returns pre-computed data updated weekly. Posts older than 2 years are "
            "excluded by default — set include_archived=true to include them."
        ),
        "parameters": {
            "topic": {"type": "string", "description": "Filter by topic name (partial match)", "required": False},
            "tag": {"type": "string", "description": "Filter by tag name (exact match)", "required": False},
            "status": {"type": "string", "description": "Filter by status", "required": False, "enum": ["planned", "not_planned", "completed", "answered", "none"]},
            "sort_by": {"type": "string", "description": "Sort by field", "required": False, "enum": ["votes", "date", "updated"]},
            "sort_order": {"type": "string", "description": "Sort order", "required": False, "enum": ["asc", "desc"]},
            "page": {"type": "integer", "description": "Page number", "required": False},
            "per_page": {"type": "integer", "description": "Results per page (1-100)", "required": False},
            "include_archived": {"type": "boolean", "description": "Include ideas older than 2 years", "required": False},
        },
        "fn": community.list_ideas,
    },
    {
        "name": "get_idea",
        "description": "Get a specific community Idea by ID with full details and comments.",
        "parameters": {
            "id": {"type": "integer", "description": "Idea post ID", "required": True},
            "include_archived": {"type": "boolean", "description": "Include if idea is older than 2 years", "required": False},
        },
        "fn": community.get_idea,
    },
    {
        "name": "search_ideas",
        "description": (
            "Search community Ideas by keyword across titles, details, and tags. "
            "Posts older than 2 years excluded by default."
        ),
        "parameters": {
            "query": {"type": "string", "description": "Search keywords", "required": True},
            "topic": {"type": "string", "description": "Filter by topic name (partial match)", "required": False},
            "tag": {"type": "string", "description": "Filter by tag name", "required": False},
            "status": {"type": "string", "description": "Filter by status", "required": False, "enum": ["planned", "not_planned", "completed", "answered", "none"]},
            "page": {"type": "integer", "description": "Page number", "required": False},
            "per_page": {"type": "integer", "description": "Results per page (1-100)", "required": False},
            "include_archived": {"type": "boolean", "description": "Include ideas older than 2 years", "required": False},
        },
        "fn": community.search_ideas,
    },
    {
        "name": "ideas_analytics",
        "description": (
            "Get summary analytics for community Ideas: top voted, status distribution, "
            "breakdowns by topic or tag. Pre-computed data updated weekly."
        ),
        "parameters": {
            "group_by": {"type": "string", "description": "Group results by field", "required": False, "enum": ["topic", "tag", "status"]},
            "top_n": {"type": "integer", "description": "Number of top ideas to show (default 10)", "required": False},
            "include_archived": {"type": "boolean", "description": "Include ideas older than 2 years in stats", "required": False},
        },
        "fn": community.ideas_analytics,
    },
]


def _create_base_server(name_suffix: str = "", auth=None) -> FastMCP:
    config = _load_tools_config()

    env_disabled = {t.strip() for t in os.environ.get("DISABLED_TOOLS", "").split(",") if t.strip()}
    all_disabled = config["disabled"] | env_disabled

    enabled_tools = []
    for tool in ALL_TOOLS:
        if tool["name"] in all_disabled:
            continue
        if config["enabled"] is not None and tool["name"] not in config["enabled"]:
            continue
        enabled_tools.append(tool)

    print(f"[zendesk-mcp{name_suffix}] Config source: {config['source']}", file=sys.stderr)
    print(
        f"[zendesk-mcp{name_suffix}] Registered {len(enabled_tools)}/{len(ALL_TOOLS)} tools: "
        f"{', '.join(t['name'] for t in enabled_tools)}",
        file=sys.stderr,
    )
    if all_disabled:
        print(
            f"[zendesk-mcp{name_suffix}] Disabled: {', '.join(sorted(all_disabled))}",
            file=sys.stderr,
        )

    kwargs = {
        "name": f"Zendesk Ideas API{name_suffix}",
        "instructions": (
            "MCP Server for Zendesk API — Tickets, Articles & Community Ideas "
            "(read-only ideas, read/write tickets & articles)"
        ),
    }
    if auth is not None:
        kwargs["auth"] = auth

    mcp = FastMCP(**kwargs)

    for tool_def in enabled_tools:
        fn = tool_def["fn"]
        mcp.tool(
            name=tool_def["name"],
            description=tool_def["description"],
        )(fn)

    return mcp


def create_prod_server() -> FastMCP:
    """No auth, service account only."""
    return _create_base_server(name_suffix=" (prod)")


def _build_cosmos_client_storage() -> object | None:
    """Build the Cosmos-backed, Fernet-encrypted OAuth state store, or None
    when not configured. Shared by both /mcp/dev auth modes."""
    cosmos_endpoint = os.environ.get("COSMOS_ENDPOINT")
    storage_key = os.environ.get("MCP_STORAGE_ENCRYPTION_KEY")
    if not (cosmos_endpoint and storage_key):
        print(
            "[zendesk-mcp] OAuth state: FastMCP default (file-based, wiped on deploy "
            "— set COSMOS_ENDPOINT and MCP_STORAGE_ENCRYPTION_KEY for persistence)",
            file=sys.stderr,
        )
        return None
    from cryptography.fernet import Fernet
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

    from .storage.cosmos_store import CosmosKeyValueStore

    cosmos_store = CosmosKeyValueStore(
        endpoint=cosmos_endpoint,
        database="mcp",
        container="oauth_state",
    )
    client_storage = FernetEncryptionWrapper(
        key_value=cosmos_store,
        fernet=Fernet(storage_key.encode()),
    )
    print(
        "[zendesk-mcp] OAuth state: Cosmos DB (persistent, Fernet-encrypted)",
        file=sys.stderr,
    )
    return client_storage


def _create_dev_server_entra() -> FastMCP:
    """Architecture F — Entra-on-Bearer.

    `/mcp/dev` is protected by `AzureProvider` (Microsoft Entra ID OAuth).
    The OAuth dance lands users on the Microsoft account picker; the resulting
    Entra access token is validated server-side. Zendesk API calls happen
    server-side using the service-account `ZENDESK_EMAIL` + `ZENDESK_API_TOKEN`
    credentials; per-user attribution is injected into write-tool payloads
    (`requester_id`, `comment.author_id`, `article.author_id`) — see
    `src/attribution.py` and `src/zendesk_user_resolver.py`.

    Required env vars: `ENTRA_CLIENT_ID`, `ENTRA_TENANT_ID`, `ENTRA_CLIENT_SECRET`,
    `MCP_PUBLIC_URL`. Optional: `COSMOS_ENDPOINT`+`MCP_STORAGE_ENCRYPTION_KEY`
    for persistent OAuth state, `MCP_JWT_SIGNING_KEY` for FastMCP JWT signing.
    """
    from .zendesk_token_verifier import EntraOAuthProxy

    client_id = os.environ.get("ENTRA_CLIENT_ID")
    tenant_id = os.environ.get("ENTRA_TENANT_ID")
    client_secret = os.environ.get("ENTRA_CLIENT_SECRET")
    public_url = os.environ.get("MCP_PUBLIC_URL", "")
    if not all([client_id, tenant_id, client_secret, public_url]):
        print(
            "[zendesk-mcp] Entra OAuth not configured (need ENTRA_CLIENT_ID, "
            "ENTRA_TENANT_ID, ENTRA_CLIENT_SECRET, MCP_PUBLIC_URL) — "
            "dev server has no auth",
            file=sys.stderr,
        )
        return _create_base_server(name_suffix=" (dev)")

    # Under Architecture F, /mcp/dev is logically "prod-Zendesk-with-Entra-
    # validated-users". Route Zendesk REST calls to the prod subdomain
    # (override the sandbox default in constants.ENVIRONMENTS["dev"]).
    # Configurable via ZENDESK_PROD_SUBDOMAIN; default matches our prod tenant.
    from .constants import ENVIRONMENTS, IT_FORM_CONFIG
    prod_subdomain = os.environ.get("ZENDESK_PROD_SUBDOMAIN", "hotschedules")
    ENVIRONMENTS["dev"]["base_url"] = f"https://{prod_subdomain}.zendesk.com"
    # Per Boyan's PR #1 design: IT_FORM_CONFIG keys match the actual Zendesk
    # target. Under Architecture F, /mcp/dev IS prod Zendesk, so create_it_ticket
    # on /mcp/dev must use the prod form_id, brand_id (Fourth IT Help =
    # 360004744852), and field IDs. Without this override the dev config would
    # send sandbox brand_id 40387882303501 to prod Zendesk → 422 "Brand is invalid".
    # Under MCP_AUTH_MODE=zendesk (revert path, _create_dev_server_zendesk_oauth),
    # /mcp/dev returns to sandbox Zendesk and the original IT_FORM_CONFIG["dev"]
    # sandbox values stay correct — no override there.
    IT_FORM_CONFIG["dev"] = IT_FORM_CONFIG["prod"]

    client_storage = _build_cosmos_client_storage()

    azure_kwargs: dict[str, object] = dict(
        client_id=client_id,
        client_secret=client_secret,
        tenant_id=tenant_id,
        # Entra app exposes `access_as_user` under api://{client_id}/.
        # AzureProvider prefixes it with identifier_uri automatically.
        required_scopes=["access_as_user"],
        base_url=f"{public_url}/mcp/dev",
        require_authorization_consent=False,
        # Pass None (not empty string) so FastMCP derives a 32-byte key
        # from the upstream client_secret via PBKDF2 instead of accepting
        # an empty low-entropy literal.
        jwt_signing_key=os.environ.get("MCP_JWT_SIGNING_KEY") or None,
    )
    if client_storage is not None:
        azure_kwargs["client_storage"] = client_storage

    auth = EntraOAuthProxy(**azure_kwargs)

    print(
        f"[zendesk-mcp] Dev server: Entra OAuth (tenant {tenant_id}, "
        f"client {client_id}) — Zendesk calls via service-account",
        file=sys.stderr,
    )
    return _create_base_server(name_suffix=" (dev)", auth=auth)


def _create_dev_server_zendesk_oauth() -> FastMCP:
    """Architecture C — per-user Zendesk OAuth via ZendeskOAuthProxy.

    Triggered by `MCP_AUTH_MODE=zendesk`. **Current live mode** as of
    2026-05-14 (revision --0000111). Each user authenticates directly with
    Zendesk through a browser OAuth flow; the user's own Zendesk Bearer is
    forwarded on every downstream API call. No service-account credential on
    the request path — Zendesk-side role-based access controls apply per
    token.

    See ADR-011 for the prod-Zendesk-pointer decision, ADR-015 for the
    historical comparison with Architecture F, and `docs/DESIGN_DECISIONS.md`
    section B3 for the full rationale.

    Multi-env config: MCP_DEV_ENVIRONMENT selects which set of
    ZENDESK_<NAME>_* env vars to read (default: SANDBOX1). Currently PROD
    in production — see ADR-011 and `docs/LIMITATIONS.md` RISK-001.
    """
    from .zendesk_token_verifier import ZendeskOAuthProxy, ZendeskTokenVerifier

    env_name = os.environ.get("MCP_DEV_ENVIRONMENT", "SANDBOX1").upper()
    subdomain = os.environ.get(f"ZENDESK_{env_name}_SUBDOMAIN")
    oauth_client_id = os.environ.get(f"ZENDESK_{env_name}_OAUTH_CLIENT_ID")
    oauth_secret = os.environ.get(f"ZENDESK_{env_name}_OAUTH_SECRET")
    public_url = os.environ.get("MCP_PUBLIC_URL", "")

    if not all([subdomain, oauth_client_id, oauth_secret, public_url]):
        print(
            f"[zendesk-mcp] Zendesk OAuth not configured for {env_name} "
            f"-- dev server has no auth",
            file=sys.stderr,
        )
        return _create_base_server(name_suffix=" (dev)")

    from .constants import ENVIRONMENTS, IT_FORM_CONFIG
    ENVIRONMENTS["dev"]["base_url"] = f"https://{subdomain}.zendesk.com"

    # When MCP_DEV_ENVIRONMENT=PROD under Architecture C, /mcp/dev points at the
    # prod Zendesk tenant via per-user OAuth. The IT_FORM_CONFIG["dev"] sandbox
    # form/brand/field IDs would 422 against prod ("Brand is invalid"), so swap
    # in the prod values — same override Architecture F applies in the Entra
    # branch (_create_dev_server_entra). For SANDBOX1/other dev envs the
    # sandbox defaults stay correct.
    if env_name == "PROD":
        IT_FORM_CONFIG["dev"] = IT_FORM_CONFIG["prod"]

    token_verifier = ZendeskTokenVerifier(zendesk_subdomain=subdomain)
    client_storage = _build_cosmos_client_storage()

    auth_kwargs: dict[str, object] = dict(
        upstream_authorization_endpoint=f"https://{subdomain}.zendesk.com/oauth/authorizations/new",
        upstream_token_endpoint=f"https://{subdomain}.zendesk.com/oauth/tokens",
        upstream_client_id=oauth_client_id,
        upstream_client_secret=oauth_secret,
        token_verifier=token_verifier,
        base_url=f"{public_url}/mcp/dev",
        token_endpoint_auth_method="client_secret_post",
        valid_scopes=["read", "write"],
        require_authorization_consent=False,
        # Pass None (not empty string) so FastMCP derives a 32-byte key
        # at boot. Empty string is rejected by some FastMCP versions. Matches
        # the Entra branch's handling at _create_dev_server_entra.
        jwt_signing_key=os.environ.get("MCP_JWT_SIGNING_KEY") or None,
    )
    if client_storage is not None:
        auth_kwargs["client_storage"] = client_storage

    auth = ZendeskOAuthProxy(**auth_kwargs)
    print(
        f"[zendesk-mcp] Dev server: Architecture C ({env_name}) "
        f"— per-user Zendesk OAuth, subdomain {subdomain} (MCP_AUTH_MODE=zendesk)",
        file=sys.stderr,
    )
    return _create_base_server(name_suffix=" (dev)", auth=auth)


def create_dev_server() -> FastMCP:
    """Dispatch /mcp/dev to one of two auth architectures based on
    `MCP_AUTH_MODE`. Both paths are fully wired; the dispatch is the only
    runtime difference.

    - `MCP_AUTH_MODE=zendesk` → `_create_dev_server_zendesk_oauth`
      (Architecture C, per-user Zendesk OAuth). **Current live mode**.
    - `MCP_AUTH_MODE=entra` → `_create_dev_server_entra`
      (Architecture F, Entra OAuth + service-account Zendesk).
    - Unset → defaults to `entra` (regression guard against accidentally
      dropping auth in prod).

    Flipping this env var is the documented L1 revert (~30s, no redeploy).
    See `docs/DESIGN_DECISIONS.md` section B2 and `docs/LIMITATIONS.md`.
    """
    mode = os.environ.get("MCP_AUTH_MODE", "entra").lower()
    if mode == "zendesk":
        return _create_dev_server_zendesk_oauth()
    return _create_dev_server_entra()


# Backward-compatible alias for stdio mode
def create_server() -> FastMCP:
    return _create_base_server()
