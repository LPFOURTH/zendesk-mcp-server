"""Zendesk ticket tools: list, get, create, and update tickets."""

from __future__ import annotations

import json
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


def _ticket_url(ticket_id: int) -> str:
    return zendesk_client.get_agent_ticket_url(ticket_id)


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


async def get_ticket(ticket_id: int) -> str:
    """Fetch a single ticket by ID with all comments."""
    result = await zendesk_client.get_ticket(ticket_id)
    t = result.get("ticket") or result
    summary = {
        **_ticket_summary(t),
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
    tags: list[str] | None = None,
) -> str:
    """Create a new Zendesk ticket."""
    ticket_data: dict = {
        "subject": subject,
        "comment": {"body": comment},
    }
    if priority is not None:
        ticket_data["priority"] = priority
    if status is not None:
        ticket_data["status"] = status
    if requester_id is not None:
        ticket_data["requester_id"] = requester_id
    if assignee_id is not None:
        ticket_data["assignee_id"] = assignee_id
    if group_id is not None:
        ticket_data["group_id"] = group_id
    if ticket_type is not None:
        ticket_data["type"] = ticket_type
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
        "created_at": t.get("created_at"),
    }
    return f"Ticket #{t['id']} created successfully!\n\n{json.dumps(summary, indent=2)}"


async def update_ticket(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    ticket_id: int,
    subject: str | None = None,
    comment: str | None = None,
    internal_note: bool | None = None,
    priority: str | None = None,
    status: str | None = None,
    assignee_id: int | None = None,
    group_id: int | None = None,
    ticket_type: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Update an existing ticket; only provided fields are changed."""
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
    if ticket_type is not None:
        ticket_data["type"] = ticket_type
    if tags is not None:
        ticket_data["tags"] = tags

    result = await zendesk_client.update_ticket(ticket_id, ticket_data)
    ticket = result.get("ticket") or result
    summary = {
        "id": ticket.get("id"),
        "url": _ticket_url(ticket["id"]),
        "subject": ticket.get("subject"),
        "status": ticket.get("status"),
        "priority": ticket.get("priority"),
        "updated_at": ticket.get("updated_at"),
    }
    return (
        f"Ticket #{ticket_id} updated successfully!\n\n{json.dumps(summary, indent=2)}"
    )


def _build_it_custom_fields(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-branches,too-many-locals
    fids: dict,
    classification: str,
    incident_category: str | None,
    sr_category: str | None,
    incident_software_item: str | None,
    incident_hardware_item: str | None,
    incident_bizapps_item: str | None,
    incident_security_item: str | None,
    sr_software_item: str | None,
    sr_hardware_item: str | None,
    sr_bizapps_item: str | None,
    sr_security_item: str | None,
    eit_general_subcategory: str | None,
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

    add("classification", IT_CLASSIFICATION_VALUES[classification])

    if incident_category:
        add("inc_category", IT_INCIDENT_CATEGORY_VALUES[incident_category])
    if sr_category:
        add("sr_category", IT_SR_CATEGORY_VALUES[sr_category])

    if incident_software_item:
        add("inc_software", IT_INC_SOFTWARE_VALUES[incident_software_item])
    if incident_hardware_item:
        add("inc_hardware", IT_INC_HARDWARE_VALUES[incident_hardware_item])
    if incident_bizapps_item:
        add("inc_bizapps", IT_INC_BIZAPPS_VALUES[incident_bizapps_item])
    if incident_security_item:
        add("inc_security", IT_INC_SECURITY_VALUES[incident_security_item])

    if sr_software_item:
        add("sr_software", IT_SR_SOFTWARE_VALUES[sr_software_item])
    if sr_hardware_item:
        add("sr_hardware", IT_SR_HARDWARE_VALUES[sr_hardware_item])
    if sr_bizapps_item:
        add("sr_bizapps", IT_SR_BIZAPPS_VALUES[sr_bizapps_item])
    if sr_security_item:
        add("sr_security", IT_SR_SECURITY_VALUES[sr_security_item])

    if eit_general_subcategory:
        add("eit_general", IT_EIT_GENERAL_VALUES[eit_general_subcategory])

    if access_request_type:
        add("access_request_type", IT_ACCESS_REQUEST_VALUES[access_request_type])
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

    if impact:
        add("impact", IT_IMPACT_VALUES[impact])
    if location:
        add("location", IT_LOCATION_VALUES[location])

    return cf


async def create_it_ticket(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches
    subject: str,
    description: str,
    classification: Literal["incident", "service_request"],
    incident_category: (
        Literal[
            "bizapps", "eit_software", "eit_hardware", "eit_general", "eit_security_ops"
        ]
        | None
    ) = None,
    sr_category: (
        Literal[
            "bizapps", "eit_software", "eit_hardware", "eit_general", "eit_security_ops"
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
    # Resolve environment config
    env = zendesk_environment_var.get() or "dev"
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
            "sr_category must not be set when classification='incident'. "
            "Use incident_category instead."
        )
    if classification == "service_request" and incident_category is not None:
        raise ValueError(
            "incident_category must not be set when classification='service_request'. "
            "Use sr_category instead."
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
                    f"{name} is for incidents only. "
                    "Use the sr_* equivalent for service requests."
                )
    if classification == "incident":
        for name, val in sr_l3_fields.items():
            if val is not None:
                raise ValueError(
                    f"{name} is for service requests only. "
                    "Use the incident_* equivalent for incidents."
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
        if (
            l4_values[l4_param] is not None
            and eit_general_subcategory != required_subcategory
        ):
            raise ValueError(
                f"{l4_param} requires eit_general_subcategory='{required_subcategory}', "
                f"but got '{eit_general_subcategory}'."
            )

    custom_fields = _build_it_custom_fields(
        fids=fids,
        classification=classification,
        incident_category=incident_category,
        sr_category=sr_category,
        incident_software_item=incident_software_item,
        incident_hardware_item=incident_hardware_item,
        incident_bizapps_item=incident_bizapps_item,
        incident_security_item=incident_security_item,
        sr_software_item=sr_software_item,
        sr_hardware_item=sr_hardware_item,
        sr_bizapps_item=sr_bizapps_item,
        sr_security_item=sr_security_item,
        eit_general_subcategory=eit_general_subcategory,
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
    if priority is not None:
        ticket_data["priority"] = priority

    result = await zendesk_client.create_ticket(ticket_data)
    t = result.get("ticket") or result
    summary = {
        "id": t.get("id"),
        "url": _ticket_url(t["id"]),
        "subject": t.get("subject"),
        "status": t.get("status"),
        "priority": t.get("priority"),
        "form": "IT Support Request",
        "created_at": t.get("created_at"),
    }
    return f"IT Support ticket #{t['id']} created successfully!\n\n{json.dumps(summary, indent=2)}"
