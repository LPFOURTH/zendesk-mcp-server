"""Pure helpers that inject per-user attribution into Zendesk write payloads.

These functions exist for **Architecture F** (`MCP_AUTH_MODE=entra`), where
all Zendesk API calls authenticate as the service account and per-user
attribution must be recorded by setting `requester_id` / `author_id` fields
in the JSON body. See ADR-015.

**Bypassed under Architecture C** (`MCP_AUTH_MODE=zendesk`, current live
mode as of 2026-05-14): the Zendesk OAuth caller IS the user, so Zendesk
attributes the request natively. Call sites in `src/tools/tickets.py`,
`src/tools/help_center.py`, and `src/tools/release_notes.py` gate these
helpers behind an `MCP_AUTH_MODE == "entra"` check; under Arch C they
silently no-op. See `docs/DESIGN_DECISIONS.md` section B7.

These functions mutate the incoming dict in place and return None — callers
build the payload first, then inject. User-provided explicit `requester_id`
(if any) always wins; we only fill in what's missing.

Field semantics (per Zendesk REST API docs):

- `ticket.requester_id`: the user that *raised* the ticket. Defaults to the
  authenticated caller (= service account) if omitted, which is why we
  inject. The `submitter_id` always reflects the authenticated caller and
  cannot be overridden — service account remains the audit "submitter".

- `ticket.comment.author_id`: shown as the comment author in the ticket UI.
  Can be set on the first comment in `create_ticket` and on any comment
  added via `update_ticket`.

- `article.author_id`: the Help Center article author. Inject only when
  CREATING a new article (or release-note article). On `update_article`,
  do NOT inject — changing author_id rewrites the article's author, not
  "last editor", which is rarely the intent.
"""
from __future__ import annotations


def apply_ticket_attribution(
    payload: dict,
    user_id: int,
    *,
    set_requester: bool = True,
    set_comment_author: bool = True,
) -> None:
    """Inject `requester_id` and optional `comment.author_id` into a ticket
    create/update payload.

    Args:
        payload: the ticket dict (i.e. the value under the "ticket" key in the
            JSON the server sends to Zendesk).
        user_id: Zendesk user_id to attribute to.
        set_requester: when True (default), set `requester_id` if it's not
            already present.
        set_comment_author: when True (default), set `comment.author_id` if a
            comment is present in the payload and author_id is not already set.

    Mutates `payload` in place. No-op when user_id is falsy.
    """
    if not user_id:
        return
    if set_requester and "requester_id" not in payload:
        payload["requester_id"] = user_id
    if set_comment_author:
        comment = payload.get("comment")
        if isinstance(comment, dict) and "author_id" not in comment:
            comment["author_id"] = user_id


def apply_article_attribution(payload: dict, user_id: int) -> None:
    """Inject `author_id` into a Help Center article create payload.

    Caller should NOT use this for update_article (see module docstring).
    No-op when user_id is falsy or author_id is already set explicitly.
    """
    if not user_id:
        return
    if "author_id" not in payload:
        payload["author_id"] = user_id


def get_current_entra_email() -> str | None:
    """Pull the authenticated Entra user's email from the FastMCP access-token
    context. Returns None when not in an auth context: stdio mode, the /mcp/prod
    Architecture-B path, the /mcp/dev Architecture-C path
    (`MCP_AUTH_MODE=zendesk` — claims come from `ZendeskTokenVerifier` which
    populates `email` directly, not `preferred_username`/`upn`), or test
    fixtures without ContextVar wiring.

    Precedence matches src/entra_auth.py:get_user_email — `preferred_username`
    is the canonical Entra v2 claim for sign-in name. Falls through to `upn`
    (Windows-style UPN) and `email` (some external IdP federations).
    Architecture C callers do not invoke this function directly; the
    attribution call sites gate on `MCP_AUTH_MODE` before reaching here.
    """
    try:
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
    except (ImportError, RuntimeError):
        return None
    if token is None:
        return None
    claims = getattr(token, "claims", None) or {}
    for key in ("preferred_username", "upn", "email"):
        v = claims.get(key)
        if isinstance(v, str) and "@" in v:
            return v
    return None
