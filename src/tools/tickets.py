from __future__ import annotations

import json
import sys

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


async def get_ticket(id: int) -> str:
    result = await zendesk_client.get_ticket(id)
    t = result.get("ticket") or result
    summary = {
        **_ticket_summary(t),
        "description": (t.get("description") or "")[:500],
        "satisfaction_rating": t.get("satisfaction_rating"),
    }
    return json.dumps(summary, indent=2)


async def create_ticket(
    subject: str,
    comment: str,
    priority: str | None = None,
    status: str | None = None,
    requester_id: int | None = None,
    assignee_id: int | None = None,
    group_id: int | None = None,
    type: str | None = None,
    tags: list[str] | None = None,
) -> str:
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
    if type is not None:
        ticket_data["type"] = type
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


async def update_ticket(
    id: int,
    subject: str | None = None,
    comment: str | None = None,
    internal_note: bool | None = None,
    priority: str | None = None,
    status: str | None = None,
    assignee_id: int | None = None,
    group_id: int | None = None,
    type: str | None = None,
    tags: list[str] | None = None,
) -> str:
    ticket_data: dict = {}
    if subject is not None:
        ticket_data["subject"] = subject
    if comment is not None:
        ticket_data["comment"] = {
            "body": comment,
            "public": not (internal_note is True),
        }
    if priority is not None:
        ticket_data["priority"] = priority
    if status is not None:
        ticket_data["status"] = status
    if assignee_id is not None:
        ticket_data["assignee_id"] = assignee_id
    if group_id is not None:
        ticket_data["group_id"] = group_id
    if type is not None:
        ticket_data["type"] = type
    if tags is not None:
        ticket_data["tags"] = tags

    result = await zendesk_client.update_ticket(id, ticket_data)
    ticket = result.get("ticket") or result
    summary = {
        "id": ticket.get("id"),
        "url": _ticket_url(ticket["id"]),
        "subject": ticket.get("subject"),
        "status": ticket.get("status"),
        "priority": ticket.get("priority"),
        "updated_at": ticket.get("updated_at"),
    }
    return f"Ticket #{id} updated successfully!\n\n{json.dumps(summary, indent=2)}"
