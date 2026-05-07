"""HTTP route for the Zendesk JWT SSO Remote Login URL.

When Zendesk redirects an unauthenticated user here, this handler:
  1. Validates the user's Entra ID token (from Authorization header or cookie).
  2. Mints a Zendesk JWT signed with the shared secret.
  3. Returns an auto-submitting HTML form that POSTs the JWT to
     https://{subdomain}.zendesk.com/access/jwt.

After Zendesk validates the JWT it creates an agent session for the user and
redirects to the original `return_to` URL — typically the OAuth authorize URL
the user was originally trying to reach.

What's not implemented yet (deliberate scope split for autonomous session):
- Browser-side Entra OAuth Auth Code Flow with PKCE. When no Authorization
  header / cookie is present, we currently return 401. A complete impl would
  redirect the user to Microsoft's authorize endpoint, handle the callback,
  exchange the code for a token, and continue. That belongs in a follow-up
  session because it requires Entra app redirect-URI changes and PKCE state
  management.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from .entra_auth import EntraValidator, get_user_email, get_user_name
from .zendesk_jwt_sso import ZendeskJwtMinter


_ALLOWED_EMAIL_DOMAINS = {"@fourth.com"}


def _extract_bearer_token(request: Request) -> str | None:
    """Pull the Entra token from the Authorization header (Bearer scheme)."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def _extract_cookie_token(request: Request) -> str | None:
    """Pull the Entra token from a cookie (browser flow). Cookie name is
    `entra_id_token` — set by the future OAuth Auth Code callback."""
    return request.cookies.get("entra_id_token")


def _email_domain_allowed(email: str) -> bool:
    """Defense in depth: only mint Zendesk JWTs for verified Fourth users."""
    if not email:
        return False
    return any(email.lower().endswith(d) for d in _ALLOWED_EMAIL_DOMAINS)


def make_zendesk_sso_route(
    entra_validator: EntraValidator,
    zendesk_jwt_minter: ZendeskJwtMinter,
    zendesk_subdomain: str,
):
    """Build a Starlette-compatible async route handler.

    Closure over the validator + minter + subdomain so the route is testable
    without env-var manipulation. main.py constructs once and registers.
    """

    async def zendesk_sso(request: Request):
        # 1. Find the Entra token
        token = _extract_bearer_token(request) or _extract_cookie_token(request)
        if not token:
            # See module docstring re: browser OAuth flow being a follow-up.
            return JSONResponse(
                {
                    "error": "unauthorized",
                    "error_description": (
                        "Entra ID token required. Provide via Authorization: "
                        "Bearer <token> header, or via entra_id_token cookie."
                    ),
                },
                status_code=401,
            )

        # 2. Validate it
        claims: dict[str, Any] | None = await entra_validator.decode_and_get_claims(token)
        if not claims:
            return JSONResponse(
                {
                    "error": "invalid_token",
                    "error_description": (
                        "Entra token validation failed (expired, wrong "
                        "audience/issuer, or invalid signature)."
                    ),
                },
                status_code=401,
            )

        # 3. Extract identity
        email = get_user_email(claims)
        name = get_user_name(claims) or email
        if not email or not name:
            return JSONResponse(
                {
                    "error": "missing_claims",
                    "error_description": (
                        "Validated Entra token did not contain a usable email "
                        "(preferred_username, upn, or email) or name claim."
                    ),
                },
                status_code=400,
            )

        # 4. Domain allowlist
        if not _email_domain_allowed(email):
            print(
                f"[zendesk-sso] REJECTED — email domain not allowed: {email}",
                file=sys.stderr,
            )
            return JSONResponse(
                {
                    "error": "forbidden",
                    "error_description": (
                        f"Email {email} is not in the allowlist. Zendesk JWTs "
                        "are minted only for @fourth.com users."
                    ),
                },
                status_code=403,
            )

        # 5. Mint the Zendesk JWT
        try:
            jwt_token = zendesk_jwt_minter.mint(email=email, name=name)
        except ValueError as exc:
            print(f"[zendesk-sso] mint failed: {exc}", file=sys.stderr)
            return JSONResponse(
                {"error": "internal_error", "error_description": str(exc)},
                status_code=500,
            )

        # 6. Audit log — every JWT mint records who, what, when
        print(
            f"[zendesk-sso] Minted Zendesk JWT for {email} "
            f"(sub={claims.get('sub')}, ip={request.client.host if request.client else '?'}, "
            f"ua={request.headers.get('user-agent', '?')[:80]})",
            file=sys.stderr,
        )

        # 7. Render the auto-submit form
        return_to = request.query_params.get("return_to")
        try:
            html = zendesk_jwt_minter.render_auto_submit_html(
                jwt_token=jwt_token,
                zendesk_subdomain=zendesk_subdomain,
                return_to=return_to,
            )
        except ValueError as exc:
            print(f"[zendesk-sso] render failed: {exc}", file=sys.stderr)
            return JSONResponse(
                {"error": "internal_error", "error_description": str(exc)},
                status_code=500,
            )

        return HTMLResponse(html)

    return zendesk_sso


def make_zendesk_sso_route_from_env():
    """Build the route handler from env vars. Returns None if unconfigured.

    Required env:
      ZENDESK_JWT_SSO_SECRET — shared secret with Zendesk
      ENTRA_CLIENT_ID + ENTRA_TENANT_ID — Entra app for token validation
      ZENDESK_PROD_SUBDOMAIN — Zendesk subdomain, e.g. "hotschedules"
    """
    shared_secret = os.environ.get("ZENDESK_JWT_SSO_SECRET")
    subdomain = os.environ.get("ZENDESK_PROD_SUBDOMAIN")
    if not shared_secret or not subdomain:
        print(
            "[zendesk-sso] ZENDESK_JWT_SSO_SECRET or ZENDESK_PROD_SUBDOMAIN not set "
            "— /zendesk-sso route disabled",
            file=sys.stderr,
        )
        return None

    entra_validator = EntraValidator.from_env()
    if entra_validator is None:
        print(
            "[zendesk-sso] ENTRA_CLIENT_ID/TENANT_ID not set — /zendesk-sso route "
            "disabled",
            file=sys.stderr,
        )
        return None

    minter = ZendeskJwtMinter(shared_secret=shared_secret)
    print(
        f"[zendesk-sso] Route enabled — subdomain={subdomain}, "
        f"entra_tenant={entra_validator.tenant_id[:8]}...",
        file=sys.stderr,
    )
    return make_zendesk_sso_route(entra_validator, minter, subdomain)
