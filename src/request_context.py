from __future__ import annotations

import contextvars

authorization_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "authorization", default=None
)
zendesk_subdomain_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "zendesk_subdomain", default=None
)
zendesk_base_url_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "zendesk_base_url", default=None
)
zendesk_environment_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "zendesk_environment", default=None
)


def _read_header(headers: dict, name: str) -> str | None:
    value = headers.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value if value else None


def _read_first_header(headers: dict, *names: str) -> str | None:
    for name in names:
        value = _read_header(headers, name)
        if value is not None and value != "":
            return value
    return None


def extract_request_context(headers: dict) -> dict:
    authorization = _read_first_header(headers, "authorization")

    target_header_names = [
        "x-zendesk-subdomain",
        "zendesk-subdomain",
        "x-zendesk-base-url",
        "zendesk-base-url",
    ]
    has_any_target = any(h in headers for h in target_header_names)

    subdomain = _read_first_header(headers, "x-zendesk-subdomain", "zendesk-subdomain")
    base_url = _read_first_header(headers, "x-zendesk-base-url", "zendesk-base-url")
    environment = _read_first_header(
        headers, "x-zendesk-environment", "zendesk-environment"
    )

    return {
        "authorization": authorization,
        "zendesk_subdomain": subdomain if has_any_target else None,
        "zendesk_base_url": base_url if has_any_target else None,
        "zendesk_environment": environment,
    }


def set_request_context(ctx: dict) -> None:
    """Set every per-request contextvar.

    AUDIT-003 fix: always call .set() — including to None when a key is
    absent — so a stale value from a previous request can never leak into
    the current request. The earlier guarded form (`if value is not None`)
    left the prior request's value in place when the new request lacked
    that header, which under stateless_http=True can mean User B sees
    User A's Authorization.
    """
    authorization_var.set(ctx.get("authorization"))
    zendesk_subdomain_var.set(ctx.get("zendesk_subdomain"))
    zendesk_base_url_var.set(ctx.get("zendesk_base_url"))
    zendesk_environment_var.set(ctx.get("zendesk_environment"))
