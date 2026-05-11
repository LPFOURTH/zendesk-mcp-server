"""Zendesk ticket tools: list, get, create, and update tickets."""

from __future__ import annotations

import base64
import json
import os
import sys
from typing import Literal

from ..constants import (
    IT_ACCESS_REQUEST_VALUES,
    IT_CLASSIFICATION_VALUES,
    IT_DISTRIBUTION_LIST_VALUES,
    IT_EIT_GENERAL_VALUES,
    IT_EMAIL_TRACE_VALUES,
    IT_FORM_CONFIG,
    IT_FOURTH_OFFICE_VALUES,
    IT_IMPACT_VALUES,
    IT_INC_BIZAPPS_VALUES,
    IT_INC_HARDWARE_VALUES,
    IT_INC_SECURITY_VALUES,
    IT_INC_SOFTWARE_VALUES,
    IT_INCIDENT_CATEGORY_VALUES,
    IT_LOCATION_VALUES,
    IT_PROD_ACCESS_REQUEST_VALUES,
    IT_PROD_INC_BIZAPPS_VALUES,
    IT_PROD_INC_EIT_ACCESS_MGMT_VALUES,
    IT_PROD_INC_EIT_EMAIL_COLLAB_VALUES,
    IT_PROD_INC_EIT_FACILITIES_VALUES,
    IT_PROD_INC_EIT_GENERAL_VALUES,
    IT_PROD_INC_EIT_NETWORK_VALUES,
    IT_PROD_INC_EIT_VM_VALUES,
    IT_PROD_INC_SECURITY_VALUES,
    IT_PROD_INC_SOFTWARE_VALUES,
    IT_PROD_SR_BIZAPPS_VALUES,
    IT_PROD_SR_SOFTWARE_VALUES,
    IT_RESTORE_DATA_VALUES,
    IT_SR_BIZAPPS_VALUES,
    IT_SR_CATEGORY_VALUES,
    IT_SR_HARDWARE_VALUES,
    IT_SR_SECURITY_VALUES,
    IT_SR_SOFTWARE_VALUES,
    IT_VM_VALUES,
)
from ..request_context import zendesk_environment_var
from ..zendesk_client import zendesk_client


def _get_authenticated_user_email() -> str | None:
    """Extract the authenticated user's email from the MCP access token.

    Returns the email from Entra JWT claims (preferred_username, email, or upn),
    or None if no authenticated user is available.
    """
    try:
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
        if token is None:
            return None
        claims = token.claims or {}
        email = (
            claims.get("preferred_username")
            or claims.get("email")
            or claims.get("upn")
        )
        if email:
            print(f"[zendesk-mcp] Authenticated user: {email}", file=sys.stderr)
        return email
    except Exception:
        return None


def _ticket_url(ticket_id: int) -> str:
    return zendesk_client.get_agent_ticket_url(ticket_id)


async def _resolve_user(user_id: int | None) -> str | None:
    """Resolve a Zendesk user ID to 'Name <email>' string."""
    if not user_id:
        return None
    try:
        result = await zendesk_client.request("GET", f"/users/{user_id}.json")
        u = result.get("user", {})
        name = u.get("name", "")
        email = u.get("email", "")
        return f"{name} <{email}>" if email else name or None
    except Exception:
        return None


def _ticket_summary(t: dict) -> dict:
    return {
        "id": t.get("id"),
        "url": _ticket_url(t["id"]),
        "subject": t.get("subject"),
        "status": t.get("status"),
        "priority": t.get("priority"),
        "type": t.get("type"),
        "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
        "requester_id": t.get("requester_id"),
        "assignee_id": t.get("assignee_id"),
        "group_id": t.get("group_id"),
        "tags": t.get("tags"),
        "via_channel": (t.get("via") or {}).get("channel"),
        "description": (t.get("description") or "")[:200],
    }


async def list_tickets(
    page: int | None = None,
    per_page: int | None = None,
    status: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> str:
    """List tickets with optional status filter and pagination."""
    params: dict = {}
    if page is not None:
        params["page"] = page
    if per_page is not None:
        params["per_page"] = per_page
    if sort_by is not None:
        params["sort_by"] = sort_by
    if sort_order is not None:
        params["sort_order"] = sort_order

    if status is not None:
        result = await zendesk_client.search(f"type:ticket status:{status}", params)
        tickets = [_ticket_summary(r) for r in result.get("results", [])]
    else:
        result = await zendesk_client.list_tickets(params)
        tickets = [_ticket_summary(t) for t in result.get("tickets", [])]

    summary = {
        "count": result.get("count"),
        "next_page": result.get("next_page"),
        "tickets": tickets,
    }
    return json.dumps(summary, indent=2)


async def get_ticket(
    ticket_id: int | None = None,
    id: int | None = None,  # pylint: disable=redefined-builtin
) -> str:
    """Fetch a single ticket by ID with all comments.

    Accepts both `ticket_id` (canonical) and `id` (legacy alias) so saved
    Copilot Studio actions and prompt-cached tool calls from before the
    pylint rename keep working. Canonical wins if both are provided.
    """
    rid = ticket_id if ticket_id is not None else id
    if rid is None:
        raise ValueError("ticket_id is required (legacy 'id' also accepted)")
    result = await zendesk_client.get_ticket(rid)
    t = result.get("ticket") or result
    requester = await _resolve_user(t.get("requester_id"))
    assignee = await _resolve_user(t.get("assignee_id"))
    summary = {
        **_ticket_summary(t),
        "requester": requester,
        "assignee": assignee,
        "description": (t.get("description") or "")[:500],
        "satisfaction_rating": t.get("satisfaction_rating"),
    }
    return json.dumps(summary, indent=2)


async def create_ticket(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    subject: str,
    comment: str,
    priority: str | None = None,
    status: str | None = None,
    requester_id: int | None = None,
    assignee_id: int | None = None,
    group_id: int | None = None,
    ticket_type: str | None = None,
    type: str | None = None,  # pylint: disable=redefined-builtin
    tags: list[str] | None = None,
) -> str:
    """Create a new Zendesk ticket.

    Accepts both `ticket_type` (canonical) and `type` (legacy alias).
    Canonical wins if both are provided.
    """
    rtype = ticket_type if ticket_type is not None else type
    ticket_data: dict = {
        "subject": subject,
        "comment": {"body": comment, "public": True},
    }
    if priority is not None:
        ticket_data["priority"] = priority
    if status is not None:
        ticket_data["status"] = status
    if requester_id is not None:
        ticket_data["requester_id"] = requester_id
    elif (user_email := _get_authenticated_user_email()):
        # Auto-attribute ticket to the authenticated user (requires admin role)
        ticket_data["requester"] = {"email": user_email}
    if assignee_id is not None:
        ticket_data["assignee_id"] = assignee_id
    if group_id is not None:
        ticket_data["group_id"] = group_id
    if rtype is not None:
        ticket_data["type"] = rtype
    if tags is not None:
        ticket_data["tags"] = tags

    result = await zendesk_client.create_ticket(ticket_data)
    t = result.get("ticket") or result
    summary = {
        "id": t.get("id"),
        "url": _ticket_url(t["id"]),
        "subject": t.get("subject"),
        "status": t.get("status"),
        "priority": t.get("priority"),
        "type": t.get("type"),
        "requester_id": t.get("requester_id"),
        "created_at": t.get("created_at"),
        "attributed_to": user_email if not requester_id and (user_email := _get_authenticated_user_email()) else None,
    }
    return f"Ticket #{t['id']} created successfully!\n\n{json.dumps(summary, indent=2)}"


async def update_ticket(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    ticket_id: int | None = None,
    id: int | None = None,  # pylint: disable=redefined-builtin
    subject: str | None = None,
    comment: str | None = None,
    internal_note: bool | None = None,
    priority: str | None = None,
    status: str | None = None,
    assignee_id: int | None = None,
    group_id: int | None = None,
    ticket_type: str | None = None,
    type: str | None = None,  # pylint: disable=redefined-builtin
    tags: list[str] | None = None,
) -> str:
    """Update an existing ticket; only provided fields are changed.

    Accepts legacy `id` / `type` kwargs in addition to canonical
    `ticket_id` / `ticket_type`. Canonical wins if both are provided.
    """
    rid = ticket_id if ticket_id is not None else id
    if rid is None:
        raise ValueError("ticket_id is required (legacy 'id' also accepted)")
    rtype = ticket_type if ticket_type is not None else type
    ticket_data: dict = {}
    if subject is not None:
        ticket_data["subject"] = subject
    if comment is not None:
        ticket_data["comment"] = {
            "body": comment,
            "public": internal_note is not True,
        }
    if priority is not None:
        ticket_data["priority"] = priority
    if status is not None:
        ticket_data["status"] = status
    if assignee_id is not None:
        ticket_data["assignee_id"] = assignee_id
    if group_id is not None:
        ticket_data["group_id"] = group_id
    if rtype is not None:
        ticket_data["type"] = rtype
    if tags is not None:
        ticket_data["tags"] = tags

    result = await zendesk_client.update_ticket(rid, ticket_data)
    ticket = result.get("ticket") or result
    summary = {
        "id": ticket.get("id"),
        "url": _ticket_url(ticket["id"]),
        "subject": ticket.get("subject"),
        "status": ticket.get("status"),
        "priority": ticket.get("priority"),
        "updated_at": ticket.get("updated_at"),
    }
    return f"Ticket #{rid} updated successfully!\n\n{json.dumps(summary, indent=2)}"


def _build_it_custom_fields(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-branches,too-many-locals,too-many-statements
    fids: dict,
    env: str,
    classification: str,
    incident_category: str | None,
    sr_category: str | None,
    incident_software_item: str | None,
    incident_hardware_item: str | None,
    incident_bizapps_item: str | None,
    incident_security_item: str | None,
    incident_email_collab_item: str | None,
    incident_network_item: str | None,
    incident_access_mgmt_item: str | None,
    incident_facilities_item: str | None,
    sr_software_item: str | None,
    sr_hardware_item: str | None,
    sr_bizapps_item: str | None,
    sr_security_item: str | None,
    eit_general_subcategory: str | None,
    inc_eit_general_subcategory: str | None,
    incident_vm_item: str | None,
    access_request_type: str | None,
    distribution_list_action: str | None,
    fourth_office_type: str | None,
    email_trace_type: str | None,
    restore_data_type: str | None,
    virtual_machine_type: str | None,
    impact: str | None,
    location: str | None,
) -> list[dict]:
    """Build the custom_fields payload for the IT Support Request form."""
    cf = []

    def add(field_key: str, value: str) -> None:
        cf.append({"id": fids[field_key], "value": value})

    # Select env-specific maps
    if env == "prod":
        inc_soft_map = IT_PROD_INC_SOFTWARE_VALUES
        inc_biz_map = IT_PROD_INC_BIZAPPS_VALUES
        inc_sec_map = IT_PROD_INC_SECURITY_VALUES
        sr_soft_map = IT_PROD_SR_SOFTWARE_VALUES
        sr_biz_map = IT_PROD_SR_BIZAPPS_VALUES
    else:
        inc_soft_map = IT_INC_SOFTWARE_VALUES
        inc_biz_map = IT_INC_BIZAPPS_VALUES
        inc_sec_map = IT_INC_SECURITY_VALUES
        sr_soft_map = IT_SR_SOFTWARE_VALUES
        sr_biz_map = IT_SR_BIZAPPS_VALUES

    # classification, inc_category, sr_category maps are now identical for dev and prod
    cls_map = IT_CLASSIFICATION_VALUES
    inc_cat_map = IT_INCIDENT_CATEGORY_VALUES
    sr_cat_map = IT_SR_CATEGORY_VALUES

    add("classification", cls_map[classification])

    if incident_category:
        add("inc_category", inc_cat_map[incident_category])
    if sr_category:
        add("sr_category", sr_cat_map[sr_category])

    if incident_software_item:
        add("inc_software", inc_soft_map[incident_software_item])
    if incident_hardware_item:
        add("inc_hardware", IT_INC_HARDWARE_VALUES[incident_hardware_item])
    if incident_bizapps_item:
        add("inc_bizapps", inc_biz_map[incident_bizapps_item])
    if incident_security_item:
        add("inc_security", inc_sec_map[incident_security_item])

    if sr_software_item:
        add("sr_software", sr_soft_map[sr_software_item])
    if sr_hardware_item:
        add("sr_hardware", IT_SR_HARDWARE_VALUES[sr_hardware_item])
    if sr_bizapps_item:
        add("sr_bizapps", sr_biz_map[sr_bizapps_item])
    if sr_security_item:
        if "sr_security" in fids:
            add("sr_security", IT_SR_SECURITY_VALUES[sr_security_item])
        elif "sr_security_ops" in fids:
            add("sr_security_ops", IT_SR_SECURITY_VALUES[sr_security_item])

    # SR EIT General path: dev uses 'eit_general', prod uses 'eit_general_sr'
    eit_gen_key = (
        "eit_general" if "eit_general" in fids
        else ("eit_general_sr" if "eit_general_sr" in fids else None)
    )
    if eit_gen_key:
        if eit_general_subcategory:
            add(eit_gen_key, IT_EIT_GENERAL_VALUES[eit_general_subcategory])
        # L4 fields
        access_req_map = (
            IT_PROD_ACCESS_REQUEST_VALUES
            if "eit_general_sr" in fids
            else IT_ACCESS_REQUEST_VALUES
        )
        if access_request_type:
            add("access_request_type", access_req_map[access_request_type])
        if distribution_list_action:
            add(
                "distribution_list_action",
                IT_DISTRIBUTION_LIST_VALUES[distribution_list_action],
            )
        if fourth_office_type:
            add("fourth_office_type", IT_FOURTH_OFFICE_VALUES[fourth_office_type])
        if email_trace_type:
            add("email_trace_type", IT_EMAIL_TRACE_VALUES[email_trace_type])
        if restore_data_type:
            add("restore_data_type", IT_RESTORE_DATA_VALUES[restore_data_type])
        if virtual_machine_type:
            add("vm_type", IT_VM_VALUES[virtual_machine_type])

    # Prod-only: Incident EIT General path (L3 + L4 sub-fields)
    if "inc_eit_general" in fids:
        if inc_eit_general_subcategory:
            add(
                "inc_eit_general",
                IT_PROD_INC_EIT_GENERAL_VALUES[inc_eit_general_subcategory],
            )
        if incident_network_item and inc_eit_general_subcategory == "network":
            add(
                "inc_eit_network",
                IT_PROD_INC_EIT_NETWORK_VALUES[incident_network_item],
            )
        if incident_access_mgmt_item and inc_eit_general_subcategory == "access_management":
            add(
                "inc_eit_access_mgmt",
                IT_PROD_INC_EIT_ACCESS_MGMT_VALUES[incident_access_mgmt_item],
            )
        if incident_email_collab_item and inc_eit_general_subcategory == "email_collaboration":
            add(
                "inc_eit_email_collab",
                IT_PROD_INC_EIT_EMAIL_COLLAB_VALUES[incident_email_collab_item],
            )
        if incident_facilities_item and inc_eit_general_subcategory == "facilities":
            add(
                "inc_eit_facilities",
                IT_PROD_INC_EIT_FACILITIES_VALUES[incident_facilities_item],
            )
        if incident_vm_item and inc_eit_general_subcategory == "virtual_machine":
            add(
                "inc_eit_vm",
                IT_PROD_INC_EIT_VM_VALUES[incident_vm_item],
            )

    if impact:
        add("impact", IT_IMPACT_VALUES[impact])
    if location:
        add("location", IT_LOCATION_VALUES[location])

    return cf


async def create_it_ticket(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches,too-many-statements
    subject: str,
    description: str,
    classification: Literal["incident", "service_request"],
    incident_category: (
        Literal[
            "bizapps",
            "eit_software",
            "eit_hardware",
            "eit_general",
            "eit_security_ops",
        ]
        | None
    ) = None,
    sr_category: (
        Literal[
            "bizapps",
            "eit_software",
            "eit_hardware",
            "eit_general",
            "eit_security_ops",
        ]
        | None
    ) = None,
    incident_software_item: (
        Literal[
            "1password",
            "8x8",
            "adobe_acrobat",
            "adobe_creative_cloud",
            "adobe_photoshop",
            "bacs_payment_services",
            "confluence",
            "copilot",
            "denver_other",
            "denver_timeclock_manager",
            "denver_ua",
            "denver_ua_database",
            "developer_apple_id",
            "github",
            "hmrc_tools",
            "hotschedules_app",
            "hs_support_site",
            "intranet",
            "lever",
            "logmein",
            "lucidchart",
            "ms_excel",
            "ms_onenote",
            "ms_powerpoint",
            "ms_project",
            "ms_visio",
            "ms_visual_studio",
            "ms_word",
            "navan",
            "onedrive",
            "openvpn",
            "peoplesystem_wfm",
            "prism_hrp",
            "rally",
            "redgate",
            "resharper",
            "sapling",
            "schoox",
            "seismic",
            "sharpen",
            "smartsheet",
            "suitepeople",
            "sumo",
            "testrail",
            "web_browser",
            "windows_upgrade",
            "xml_spy",
            "other",
            # prod-only additions
            "power_bi",
            "powerbi_desktop",
            "adobe_acrobat_pro",
            "ai_tooling",
            "ai_other",
            "ai_claude",
            "ai_chatgpt",
            "ai_copilot",
            "ai_copilot_studio",
            "gotoassist",
            "visual_studio_code",
            "ms_outlook",
            "ms_edge",
            "ms_todo",
            "google_chrome",
            "postman",
            "zoom_contact_center",
            "zoom_phone",
        ]
        | None
    ) = None,
    incident_hardware_item: (
        Literal[
            "cable",
            "desktop",
            "docking_station",
            "external_screen",
            "keyboard",
            "laptop",
            "mouse",
            "printer",
            "other",
        ]
        | None
    ) = None,
    incident_bizapps_item: (
        Literal[
            "zendesk",
            "salesforce",
            "netsuite",
            "jira",
            "jitterbit",
            "docusign",
            "other",
        ]
        | None
    ) = None,
    incident_security_item: (
        Literal[
            "email_blocked",
            "password_compromised",
            "phishing",
            "other",
        ]
        | None
    ) = None,
    incident_email_collab_item: Literal["confluence", "outlook", "sharepoint", "slack", "teams", "other"] | None = None,
    incident_network_item: Literal["internet", "vpn", "wifi", "slow_connection", "other"] | None = None,
    incident_access_mgmt_item: Literal["account_lockout", "mfa", "password_reset", "other"] | None = None,
    incident_facilities_item: (
        Literal[
            "door_access",
            "meeting_rooms",
            "office_tvs",
            "office_printer",
            "video_conferencing",
            "office_badge",
            "other",
        ]
        | None
    ) = None,
    sr_software_item: (
        Literal[
            "1password",
            "8x8",
            "admin_by_request",
            "adobe_acrobat",
            "adobe_creative_cloud",
            "adobe_photoshop",
            "concur",
            "confluence",
            "copilot",
            "denver_other",
            "denver_timeclock_manager",
            "denver_ua",
            "denver_ua_database",
            "gemalto_bacs",
            "github",
            "hmrc_tools",
            "hotschedules_app",
            "hs_support_site",
            "intranet",
            "lever",
            "logmein",
            "lucidchart",
            "managed_apple_id",
            "ms_excel",
            "ms_onenote",
            "ms_powerpoint",
            "ms_project",
            "ms_visio",
            "ms_word",
            "navan",
            "onedrive",
            "openvpn",
            "peoplesystem_wfm",
            "prism_hrp",
            "rally",
            "redgate",
            "resharper",
            "sapling",
            "schoox",
            "seismic",
            "sharpen",
            "smartsheet",
            "suitepeople",
            "sumo",
            "testrail",
            "visual_studio",
            "web_browser",
            "windows_upgrade",
            "xml_spy",
            "other",
            # prod-only additions
            "power_bi",
            "powerbi_desktop",
            "zoom",
            "adobe_acrobat_pro",
            "ai_tooling",
            "ai_other",
            "ai_claude",
            "ai_chatgpt",
            "ai_copilot",
            "ai_copilot_studio",
            "developer_apple_id",
            "gotoassist",
            "ms_visual_studio",
            "visual_studio_code",
            "ms_outlook",
            "ms_edge",
            "ms_todo",
            "google_chrome",
            "postman",
            "zoom_contact_center",
            "zoom_phone",
        ]
        | None
    ) = None,
    sr_hardware_item: (
        Literal[
            "cable",
            "desktop",
            "docking_station",
            "external_screen",
            "headset",
            "keyboard",
            "laptop",
            "mouse",
            "monitor",
            "printer",
            "other",
        ]
        | None
    ) = None,
    sr_bizapps_item: (
        Literal[
            "zendesk",
            "salesforce",
            "netsuite",
            "jira",
            "jitterbit",
            "docusign",
            "data_team",
            "gdpr_request",
            "other",
        ]
        | None
    ) = None,
    sr_security_item: (
        Literal[
            "security_request",
            "unblock_website",
            "unblock_email",
            "unblock_software",
            "audit",
            "other",
        ]
        | None
    ) = None,
    eit_general_subcategory: (
        Literal[
            "gdpr_request",
            "lad_maintenance",
            "access_request",
            "distribution_list",
            "fourth_office",
            "email_trace",
            "restore_lost_data",
            "virtual_machine",
            "other",
        ]
        | None
    ) = None,
    access_request_type: (
        Literal[
            "network_drive",
            "security_group",
            "web_portal",
            "mailbox",
            "other",
        ]
        | None
    ) = None,
    distribution_list_action: (
        Literal[
            "create",
            "update",
            "delete",
            "other",
        ]
        | None
    ) = None,
    fourth_office_type: (
        Literal[
            "desk_move",
            "office_move",
            "door_access",
            "printer_access",
            "other",
        ]
        | None
    ) = None,
    email_trace_type: (
        Literal[
            "fourth_customer_email",
            "fourth_user_email",
            "other",
        ]
        | None
    ) = None,
    restore_data_type: (
        Literal[
            "network_drives",
            "sharepoint",
            "onedrive",
            "emails",
            "other",
        ]
        | None
    ) = None,
    virtual_machine_type: (
        Literal[
            "remote_desktop_denver",
            "windows_365_cloud_pc",
            "other",
        ]
        | None
    ) = None,
    inc_eit_general_subcategory: (
        Literal[
            "network",
            "access_management",
            "email_collaboration",
            "facilities",
            "virtual_machine",
        ]
        | None
    ) = None,
    incident_vm_item: (
        Literal[
            "remote_desktop_denver",
            "windows_365_cloud_pc",
            "other",
        ]
        | None
    ) = None,
    cc_emails: list[str] | None = None,
    attachments: list[dict] | None = None,
    impact: Literal["low", "medium", "high", "very_high"] | None = None,
    location: (
        Literal[
            "atlanta",
            "austin",
            "cape_town",
            "denver",
            "london",
            "macclesfield",
            "miami",
            "remote",
            "shanghai",
            "sofia",
            "sydney",
            "tampa",
            "ukraine",
            "other",
            "remote_uk",
            "remote_us",
            "remote_germany",
            "remote_india",
            "remote_austria",
            "remote_armenia",
            "remote_poland",
            "remote_thailand",
            "remote_argentina",
            "remote_honduras",
            "remote_colombia",
            "remote_south_africa",
            "remote_ukraine",
            "remote_philippines",
        ]
        | None
    ) = None,
    additional_location_info: str | None = None,
    priority: Literal["low", "normal", "high", "urgent"] | None = None,
) -> str:
    """Create an IT Support Request ticket using the company's standard form."""
    # Resolve environment config.
    # Priority: HTTP contextvar (zendesk-environment header / path routing) → ZENDESK_ENVIRONMENT env var → "dev".
    env = zendesk_environment_var.get() or os.environ.get("ZENDESK_ENVIRONMENT") or "dev"
    config = IT_FORM_CONFIG.get(env) or IT_FORM_CONFIG["dev"]
    if config["fields"] is None:
        raise ValueError(
            f"IT form field IDs are not configured for environment '{env}'. "
            "See docs/it-form-update-guide.md for setup instructions."
        )
    fids = config["fields"]

    # Validate conditional consistency
    if classification == "incident" and sr_category is not None:
        raise ValueError(
            "sr_category must not be set when classification='incident'. " "Use incident_category instead."
        )
    if classification == "service_request" and incident_category is not None:
        raise ValueError(
            "incident_category must not be set when classification='service_request'. " "Use sr_category instead."
        )
    inc_l3_fields: dict[str, str | None] = {
        "incident_software_item": incident_software_item,
        "incident_hardware_item": incident_hardware_item,
        "incident_bizapps_item": incident_bizapps_item,
        "incident_security_item": incident_security_item,
    }
    sr_l3_fields: dict[str, str | None] = {
        "sr_software_item": sr_software_item,
        "sr_hardware_item": sr_hardware_item,
        "sr_bizapps_item": sr_bizapps_item,
        "sr_security_item": sr_security_item,
    }
    if classification == "service_request":
        for name, val in inc_l3_fields.items():
            if val is not None:
                raise ValueError(
                    f"{name} is for incidents only. Use the sr_* equivalent for service requests."
                )
    if classification == "incident":
        for name, val in sr_l3_fields.items():
            if val is not None:
                raise ValueError(
                    f"{name} is for service requests only. Use the incident_* equivalent for incidents."
                )

    # Validate L4 fields match eit_general_subcategory
    l4_requirements = {
        "access_request_type": "access_request",
        "distribution_list_action": "distribution_list",
        "fourth_office_type": "fourth_office",
        "email_trace_type": "email_trace",
        "restore_data_type": "restore_lost_data",
        "virtual_machine_type": "virtual_machine",
    }
    l4_values = {
        "access_request_type": access_request_type,
        "distribution_list_action": distribution_list_action,
        "fourth_office_type": fourth_office_type,
        "email_trace_type": email_trace_type,
        "restore_data_type": restore_data_type,
        "virtual_machine_type": virtual_machine_type,
    }
    for l4_param, required_subcategory in l4_requirements.items():
        if l4_values[l4_param] is not None and eit_general_subcategory != required_subcategory:
            raise ValueError(
                f"{l4_param} requires eit_general_subcategory='{required_subcategory}', "
                f"but got '{eit_general_subcategory}'."
            )

    # inc_eit_general_subcategory requires incident_category=eit_general
    if inc_eit_general_subcategory is not None and incident_category != "eit_general":
        raise ValueError(
            "inc_eit_general_subcategory requires incident_category='eit_general'."
        )

    # incident_vm_item requires inc_eit_general_subcategory=virtual_machine
    if incident_vm_item is not None and inc_eit_general_subcategory != "virtual_machine":
        raise ValueError(
            "incident_vm_item requires inc_eit_general_subcategory='virtual_machine'."
        )

    # incident L4 EIT General fields require inc_eit_general_subcategory (prod path only)
    _inc_eit_l4 = {
        "incident_network_item": ("network", incident_network_item),
        "incident_access_mgmt_item": ("access_management", incident_access_mgmt_item),
        "incident_email_collab_item": ("email_collaboration", incident_email_collab_item),
        "incident_facilities_item": ("facilities", incident_facilities_item),
        "incident_vm_item": ("virtual_machine", incident_vm_item),
    }
    for param_name, (required_sub, val) in _inc_eit_l4.items():
        if (
            val is not None
            and inc_eit_general_subcategory != required_sub
            and "inc_eit_general" in fids
        ):
            raise ValueError(
                f"{param_name} requires inc_eit_general_subcategory='{required_sub}'."
            )

    # Upload attachments first to obtain tokens
    upload_tokens: list[str] = []
    if attachments:
        for att in attachments:
            filename = att.get("filename", "attachment")
            content_type = att.get("content_type", "application/octet-stream")
            if "content_base64" in att:
                file_bytes = base64.b64decode(att["content_base64"])
            elif "url" in att:
                import httpx as _httpx  # pylint: disable=import-outside-toplevel
                async with _httpx.AsyncClient(timeout=30.0) as _client:
                    _resp = await _client.get(att["url"])
                    _resp.raise_for_status()
                    file_bytes = _resp.content
            else:
                raise ValueError(
                    f"Attachment must have 'content_base64' or 'url': {att}"
                )
            token = await zendesk_client.upload_file(file_bytes, filename, content_type)
            upload_tokens.append(token)

    custom_fields = _build_it_custom_fields(
        fids=fids,
        env=env,
        classification=classification,
        incident_category=incident_category,
        sr_category=sr_category,
        incident_software_item=incident_software_item,
        incident_hardware_item=incident_hardware_item,
        incident_bizapps_item=incident_bizapps_item,
        incident_security_item=incident_security_item,
        incident_email_collab_item=incident_email_collab_item,
        incident_network_item=incident_network_item,
        incident_access_mgmt_item=incident_access_mgmt_item,
        incident_facilities_item=incident_facilities_item,
        sr_software_item=sr_software_item,
        sr_hardware_item=sr_hardware_item,
        sr_bizapps_item=sr_bizapps_item,
        sr_security_item=sr_security_item,
        eit_general_subcategory=eit_general_subcategory,
        inc_eit_general_subcategory=inc_eit_general_subcategory,
        incident_vm_item=incident_vm_item,
        access_request_type=access_request_type,
        distribution_list_action=distribution_list_action,
        fourth_office_type=fourth_office_type,
        email_trace_type=email_trace_type,
        restore_data_type=restore_data_type,
        virtual_machine_type=virtual_machine_type,
        impact=impact,
        location=location,
    )

    if additional_location_info is not None:
        custom_fields.append(
            {
                "id": fids["additional_location_info"],
                "value": additional_location_info,
            }
        )

    ticket_data: dict = {
        "subject": subject,
        "comment": {"body": description},
        "ticket_form_id": config["form_id"],
        "custom_fields": custom_fields,
    }
    if config.get("brand_id"):
        ticket_data["brand_id"] = config["brand_id"]
    if upload_tokens:
        ticket_data["comment"]["uploads"] = upload_tokens
    if priority is not None:
        ticket_data["priority"] = priority
    if cc_emails:
        ticket_data["email_ccs"] = [
            {"user_email": e, "action": "put"} for e in cc_emails
        ]

    result = await zendesk_client.create_ticket(ticket_data)
    t = result.get("ticket") or result
    summary: dict = {
        "id": t.get("id"),
        "url": _ticket_url(t["id"]),
        "subject": t.get("subject"),
        "status": t.get("status"),
        "priority": t.get("priority"),
        "form": "IT Support Request",
        "created_at": t.get("created_at"),
    }
    if cc_emails:
        summary["cc_count"] = len(cc_emails)
    if upload_tokens:
        summary["attachments_uploaded"] = len(upload_tokens)
    return f"IT Support ticket #{t['id']} created successfully!\n\n{json.dumps(summary, indent=2)}"
