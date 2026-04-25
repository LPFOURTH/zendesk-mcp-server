"""Community Ideas MCP tools — read-only, served from in-memory cache."""

from __future__ import annotations

import json

from ..ideas_cache import ideas_cache as _cache


def _post_summary(p: dict) -> dict:
    """Truncate details for list views."""
    return {
        "id": p["id"],
        "title": p.get("title", ""),
        "details": (p.get("details") or "")[:200],
        "status": p.get("status", ""),
        "topic": p.get("topic", ""),
        "author": p.get("author", ""),
        "organization": p.get("organization", ""),
        "created_at": p.get("created_at", ""),
        "updated_at": p.get("updated_at", ""),
        "tags": p.get("tags", []),
        "vote_count": p.get("vote_count", 0),
        "vote_sum": p.get("vote_sum", 0),
        "follower_count": p.get("follower_count", 0),
        "comment_count": p.get("comment_count", 0),
        "html_url": p.get("html_url", ""),
    }


async def list_ideas(
    topic: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    page: int | None = None,
    per_page: int | None = None,
    include_archived: bool | None = None,
) -> str:
    if not _cache.is_loaded:
        return json.dumps({"error": "Ideas data not available. Try again later."})

    result = _cache.list_ideas(
        topic=topic,
        tag=tag,
        status=status,
        sort_by=sort_by or "votes",
        sort_order=sort_order or "desc",
        page=page or 1,
        per_page=per_page or 25,
        include_archived=include_archived or False,
    )
    return json.dumps({
        "total": result["total"],
        "page": result["page"],
        "per_page": result["per_page"],
        "archived_count": result["archived_count"],
        "data_freshness": _cache.exported_at,
        "posts": [_post_summary(p) for p in result["posts"]],
    }, indent=2)


async def get_idea(
    id: int,
    include_archived: bool | None = None,
) -> str:
    if not _cache.is_loaded:
        return json.dumps({"error": "Ideas data not available. Try again later."})

    post = _cache.get_by_id(id, include_archived=include_archived or False)
    if post is None:
        return json.dumps({"error": f"Idea {id} not found (may be archived — use include_archived=true)."})

    return json.dumps(post, indent=2)


async def search_ideas(
    query: str,
    topic: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    page: int | None = None,
    per_page: int | None = None,
    include_archived: bool | None = None,
) -> str:
    if not _cache.is_loaded:
        return json.dumps({"error": "Ideas data not available. Try again later."})

    result = _cache.search(
        query=query,
        topic=topic,
        tag=tag,
        status=status,
        page=page or 1,
        per_page=per_page or 25,
        include_archived=include_archived or False,
    )
    return json.dumps({
        "total": result["total"],
        "page": result["page"],
        "per_page": result["per_page"],
        "archived_count": result["archived_count"],
        "data_freshness": _cache.exported_at,
        "posts": [_post_summary(p) for p in result["posts"]],
    }, indent=2)


async def ideas_analytics(
    group_by: str | None = None,
    top_n: int | None = None,
    include_archived: bool | None = None,
) -> str:
    if not _cache.is_loaded:
        return json.dumps({"error": "Ideas data not available. Try again later."})

    result = _cache.analytics(
        group_by=group_by,
        top_n=top_n or 10,
        include_archived=include_archived or False,
    )
    return json.dumps(result, indent=2)
