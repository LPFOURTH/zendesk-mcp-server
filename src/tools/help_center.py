"""MCP tool handlers for Zendesk Help Center articles."""

from __future__ import annotations

import json

from ..attribution import apply_article_attribution, get_current_entra_email
from ..zendesk_client import zendesk_client
from ..zendesk_user_resolver import resolve_zendesk_user_id


def _article_summary(a: dict) -> dict:
    return {
        "id": a.get("id"),
        "url": a.get("html_url") or zendesk_client.get_help_center_article_url(a["id"]),
        "title": a.get("title"),
        "section_id": a.get("section_id"),
        "locale": a.get("locale"),
        "draft": a.get("draft"),
        "created_at": a.get("created_at"),
        "updated_at": a.get("updated_at"),
        "author_id": a.get("author_id"),
        "label_names": a.get("label_names"),
    }


async def list_articles(
    page: int | None = None,
    per_page: int | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
) -> str:
    """List Help Center articles with optional pagination and sorting."""
    params: dict = {}
    if page is not None:
        params["page"] = page
    if per_page is not None:
        params["per_page"] = per_page
    if sort_by is not None:
        params["sort_by"] = sort_by
    if sort_order is not None:
        params["sort_order"] = sort_order

    result = await zendesk_client.list_articles(params)
    articles = [_article_summary(a) for a in result.get("articles", [])]
    summary = {
        "count": result.get("count"),
        "next_page": result.get("next_page"),
        "articles": articles,
    }
    return json.dumps(summary, indent=2)


async def get_article(id: int) -> str:  # pylint: disable=redefined-builtin
    """Fetch a single Help Center article by ID, truncating the body to 2000 chars."""
    result = await zendesk_client.get_article(id)
    a = result.get("article") or result
    summary = {
        **_article_summary(a),
        "body": (a.get("body") or "")[:2000],
    }
    return json.dumps(summary, indent=2)


async def create_article(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    title: str,
    body: str,
    section_id: int,
    locale: str | None = None,
    draft: bool | None = None,
    permission_group_id: int | None = None,
    user_segment_id: int | None = None,
    label_names: list[str] | None = None,
) -> str:
    """Create a new Help Center article in the specified section."""
    article_data: dict = {"title": title, "body": body}
    if locale is not None:
        article_data["locale"] = locale
    if draft is not None:
        article_data["draft"] = draft
    if permission_group_id is not None:
        article_data["permission_group_id"] = permission_group_id
    article_data["user_segment_id"] = (
        user_segment_id if user_segment_id is not None else None
    )
    if label_names is not None:
        article_data["label_names"] = label_names

    # Architecture F attribution: when the caller didn't provide author_id,
    # use the authenticated Entra user's Zendesk user_id. See ADR-015.
    # update_article intentionally does NOT inject — changing author_id on
    # update rewrites the article's author, not "last editor".
    user_email = get_current_entra_email()
    if user_email and "author_id" not in article_data:
        user_id = await resolve_zendesk_user_id(user_email)
        if user_id:
            apply_article_attribution(article_data, user_id)

    result = await zendesk_client.create_article(article_data, section_id)
    a = result.get("article") or result
    summary = _article_summary(a)
    return (
        f"Article #{a['id']} created successfully!\n\n{json.dumps(summary, indent=2)}"
    )


async def update_article(  # pylint: disable=redefined-builtin,too-many-arguments,too-many-positional-arguments
    id: int,
    title: str | None = None,
    body: str | None = None,
    locale: str | None = None,
    draft: bool | None = None,
    permission_group_id: int | None = None,
    user_segment_id: int | None = None,
    label_names: list[str] | None = None,
) -> str:
    """Update an existing Help Center article by ID."""
    article_data: dict = {}
    if title is not None:
        article_data["title"] = title
    if body is not None:
        article_data["body"] = body
    if locale is not None:
        article_data["locale"] = locale
    if draft is not None:
        article_data["draft"] = draft
    if permission_group_id is not None:
        article_data["permission_group_id"] = permission_group_id
    if user_segment_id is not None:
        article_data["user_segment_id"] = user_segment_id
    if label_names is not None:
        article_data["label_names"] = label_names

    result = await zendesk_client.update_article(id, article_data)
    a = result.get("article") or result.get("translation") or result
    summary = _article_summary(a)
    return f"Article #{id} updated successfully!\n\n{json.dumps(summary, indent=2)}"
