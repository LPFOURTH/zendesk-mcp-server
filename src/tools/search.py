from __future__ import annotations

import json
import re

from ..zendesk_client import zendesk_client

_ARTICLE_QUERY_HINT = re.compile(
    r"\b(article|articles|help center|help centre|knowledge base|kb)\b", re.IGNORECASE
)
_TICKET_QUERY_HINT = re.compile(r"\btickets?\b", re.IGNORECASE)
_ABOUT_QUOTED_TEXT = re.compile(r"\b(?:about|for)\s+['\"]([^'\"]+)['\"]", re.IGNORECASE)


def _result_url(r: dict) -> str | None:
    if r.get("result_type") == "ticket":
        return zendesk_client.get_agent_ticket_url(r["id"])
    if r.get("html_url"):
        return r["html_url"]
    return None


def _infer_mode(query: str) -> str:
    has_article = bool(_ARTICLE_QUERY_HINT.search(query)) or bool(
        re.search(r"\btype:article\b", query, re.IGNORECASE)
    )
    has_ticket = bool(_TICKET_QUERY_HINT.search(query)) or bool(
        re.search(r"\btype:ticket\b", query, re.IGNORECASE)
    )
    if has_article and not has_ticket:
        return "articles"
    if has_ticket and not has_article:
        return "tickets"
    return "general"


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_quoted_topic(query: str) -> str | None:
    m = _ABOUT_QUOTED_TEXT.search(query)
    return m.group(1).strip() if m else None


def _normalize_ticket_query(query: str) -> str:
    if re.search(r"\btype:ticket\b", query, re.IGNORECASE):
        return _normalize_whitespace(query)

    topic = _extract_quoted_topic(query)
    filters = ["type:ticket"]
    text = query

    if re.search(r"\bopen tickets?\b", text, re.IGNORECASE):
        filters.append("status:open")
        text = re.sub(r"\bopen tickets?\b", " ", text, flags=re.IGNORECASE)

    for pattern in [
        r"\bsearch zendesk\b",
        r"\bsearch\b",
        r"\bzendesk\b",
        r"\btickets?\b",
        r"\bsorted by updated date\b",
        r"\bmost recent\b",
        r"\blatest\b",
        r"\babout\b",
        r"\bfor\b",
    ]:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    keywords = _normalize_whitespace(topic or text)
    return _normalize_whitespace(f"{' '.join(filters)} {keywords}")


def _normalize_article_query(query: str) -> str:
    topic = _extract_quoted_topic(query)
    text = query
    for pattern in [
        r"\btype:article\b",
        r"\bsearch zendesk\b",
        r"\bsearch\b",
        r"\bzendesk\b",
        r"\bhelp center\b",
        r"\bhelp centre\b",
        r"\bknowledge base\b",
        r"\bkb\b",
        r"\barticles?\b",
        r"\babout\b",
        r"\bfor\b",
    ]:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return _normalize_whitespace(topic or text)


def _normalize_search_request(query: str) -> dict:
    mode = _infer_mode(query)
    if mode == "tickets":
        return {"mode": mode, "query": _normalize_ticket_query(query)}
    if mode == "articles":
        return {"mode": mode, "query": _normalize_article_query(query)}
    return {"mode": mode, "query": _normalize_whitespace(query)}


def _trim_result(r: dict) -> dict:
    base = {
        "id": r.get("id"),
        "result_type": r.get("result_type"),
        "url": _result_url(r),
    }
    if r.get("result_type") == "ticket":
        return {
            **base,
            "subject": r.get("subject"),
            "status": r.get("status"),
            "priority": r.get("priority"),
            "type": r.get("type"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "description": (r.get("description") or "")[:200],
        }
    if r.get("result_type") == "article":
        return {
            **base,
            "title": r.get("title"),
            "section_id": r.get("section_id"),
            "locale": r.get("locale"),
            "draft": r.get("draft"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
        }
    return {**base, "name": r.get("name") or r.get("title") or r.get("subject")}


async def search(
    query: str,
    scope: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    page: int | None = None,
    per_page: int | None = None,
) -> str:
    params: dict = {}
    if sort_by is not None:
        params["sort_by"] = sort_by
    if sort_order is not None:
        params["sort_order"] = sort_order
    if page is not None:
        params["page"] = page
    if per_page is not None:
        params["per_page"] = per_page

    if scope and scope != "all":
        normalized = _normalize_search_request(f"{scope} {query}")
    else:
        normalized = _normalize_search_request(query)

    if normalized["mode"] == "articles":
        result = await zendesk_client.search_articles(normalized["query"], params)
    else:
        result = await zendesk_client.search(normalized["query"], params)

    results = [_trim_result(r) for r in result.get("results", [])]
    summary = {
        "query": normalized["query"],
        "scope": normalized["mode"],
        "count": result.get("count", len(results)),
        "next_page": result.get("next_page"),
        "results": results,
    }
    return json.dumps(summary, indent=2)
