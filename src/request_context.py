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
    if ctx.get("authorization") is not None:
        authorization_var.set(ctx["authorization"])
    if ctx.get("zendesk_subdomain") is not None:
        zendesk_subdomain_var.set(ctx["zendesk_subdomain"])
    if ctx.get("zendesk_base_url") is not None:
        zendesk_base_url_var.set(ctx["zendesk_base_url"])
    if ctx.get("zendesk_environment") is not None:
        zendesk_environment_var.set(ctx["zendesk_environment"])
