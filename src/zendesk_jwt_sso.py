"""Zendesk JWT SSO minter.

Implements Zendesk's JWT SSO format (HMAC-SHA256, shared secret) per the
official spec:
  https://support.zendesk.com/hc/en-us/articles/4408881965722-Anatomy-of-a-JWT-request

Used by the /zendesk-sso endpoint (Architecture E / Path B): when an
unauthenticated user hits a Zendesk URL, Zendesk redirects them to our
endpoint, we authenticate them via Entra, mint a Zendesk JWT, and POST it
back to https://{subdomain}.zendesk.com/access/jwt via an auto-submitting
HTML form. Zendesk validates the signature, creates a session, and
redirects the user to the original return_to.

Security model:
- HS256 signing with a shared secret stored in Azure Key Vault.
- Required claims iat + jti for replay protection (Zendesk validates jti
  uniqueness within its 3-min clock-skew window).
- email_verified defaults to false — per Zendesk security guidance, never
  assert email_verified=true unless we have positive proof of ownership.
- This module does NOT authenticate the user; that's the caller's job.
  Only mint a JWT after cryptographically validating an Entra (or other)
  upstream identity.
"""

from __future__ import annotations

import html
import re
import secrets
import time
import urllib.parse
from typing import Any

import jwt as pyjwt


_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")


def _is_valid_subdomain(subdomain: str) -> bool:
    """Zendesk subdomains are 3-63 chars, alphanumeric + hyphens, no leading/trailing hyphen."""
    return bool(_SUBDOMAIN_RE.match(subdomain))


class ZendeskJwtMinter:
    """Mints Zendesk JWT SSO tokens and renders the auto-submit form.

    Use a single instance per Zendesk subdomain configuration.
    """

    def __init__(self, shared_secret: str):
        if not shared_secret:
            raise ValueError("shared_secret is required")
        self._secret = shared_secret

    def mint(
        self,
        *,
        email: str,
        name: str,
        ttl_seconds: int = 60,
        **extra_claims: Any,
    ) -> str:
        """Mint a Zendesk-format JWT.

        Args:
            email: User's email (becomes the Zendesk identity). Required.
            name: User's display name. Required.
            ttl_seconds: Reserved for future enforcement; Zendesk validates
                its own clock-skew window (3 min by default), so we don't
                emit `exp` — the iat + jti combination is what Zendesk uses.
            **extra_claims: Additional claims to include (external_id,
                organization, role, tags, etc.). Passed through verbatim.

        Returns:
            The signed JWT as a compact string.

        Raises:
            ValueError: if email or name is empty.
        """
        if not email:
            raise ValueError("email is required")
        if not name:
            raise ValueError("name is required")

        now = int(time.time())
        payload: dict[str, Any] = {
            "iat": now,
            "jti": secrets.token_urlsafe(16),
            "email": email,
            "name": name,
            "email_verified": False,  # per Zendesk security guidance
        }
        payload.update(extra_claims)

        return pyjwt.encode(payload, self._secret, algorithm="HS256")

    def render_auto_submit_html(
        self,
        *,
        jwt_token: str,
        zendesk_subdomain: str,
        return_to: str | None = None,
    ) -> str:
        """Render an HTML page that POSTs the JWT to Zendesk's /access/jwt endpoint.

        Zendesk requires POST (not GET) for security — a JWT in a URL would land in
        browser history and server logs. The form auto-submits via inline script
        so the user sees a brief blank page then lands on Zendesk.

        Args:
            jwt_token: The JWT minted by mint().
            zendesk_subdomain: Zendesk subdomain, e.g. "hotschedules". Must be
                a valid Zendesk subdomain (alphanumeric + hyphens).
            return_to: Optional URL to land on after Zendesk creates the session.
                Typically the original /oauth/authorizations/new URL.

        Returns:
            HTML as a string.

        Raises:
            ValueError: if zendesk_subdomain is malformed (defense in depth).
        """
        if not _is_valid_subdomain(zendesk_subdomain):
            raise ValueError(
                f"invalid Zendesk subdomain {zendesk_subdomain!r}: "
                "must be 3-63 chars, lowercase alphanumeric + hyphens"
            )

        action_url = f"https://{zendesk_subdomain}.zendesk.com/access/jwt"
        jwt_escaped = html.escape(jwt_token, quote=True)

        return_to_input = ""
        if return_to:
            # The return_to value must survive HTML attribute encoding. We
            # escape for HTML; Zendesk handles URL-decode on its side.
            return_to_escaped = html.escape(return_to, quote=True)
            return_to_input = (
                f'<input type="hidden" name="return_to" value="{return_to_escaped}">'
            )

        # Auto-submit: vanilla JS form.submit() runs as soon as the page parses.
        # No external resources, no jQuery, no CSP headaches.
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Signing in to Zendesk…</title>
<meta name="referrer" content="no-referrer">
</head>
<body>
<noscript>
  <p>JavaScript is required to complete sign-in. Click the button below to continue.</p>
</noscript>
<form id="zendesk-sso-form" method="POST" action="{action_url}">
  <input type="hidden" name="jwt" value="{jwt_escaped}">
  {return_to_input}
  <noscript><button type="submit">Continue to Zendesk</button></noscript>
</form>
<script>
  // Auto-submit on page load.
  document.getElementById("zendesk-sso-form").submit();
</script>
</body>
</html>"""
