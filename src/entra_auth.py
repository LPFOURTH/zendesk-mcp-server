"""Entra ID JWT validation.

Validates Bearer tokens from Microsoft Entra ID (Azure AD) using JWKS public
keys. Used by /zendesk-sso (Architecture E / Path B) to authenticate the user
before minting a Zendesk JWT.

Supports both v1 and v2 token formats:
  v1: iss=https://sts.windows.net/{tenant}/, aud=api://{client_id}
  v2: iss=https://login.microsoftonline.com/{tenant}/v2.0, aud={client_id}

JWKS is fetched lazily and cached by PyJWKClient. Audience and issuer are
validated cryptographically — a token signed by Entra but for a different
tenant or app will be rejected.

Originally extracted from commit 8cbfd41 / 46fcbd9 (the first Architecture B
deployment), removed in cae8802 when /mcp/dev moved to Architecture C with
direct Zendesk OAuth. Restored here for the JWT SSO Remote Login URL flow,
where we re-need a way to authenticate browser-bound users via Entra at the
HTTP layer.
"""

from __future__ import annotations

import asyncio
import os
import sys

import jwt as pyjwt


class EntraValidator:
    """Validates Entra ID JWTs using JWKS public keys.

    Constructed once per server startup. Holds a JWKS client that lazily
    fetches and caches signing keys. Pass the validated token's bytes to
    `decode_and_get_claims` to get back a dict of claims (or None if
    validation fails for any reason).
    """

    def __init__(self, client_id: str, tenant_id: str):
        if not client_id:
            raise ValueError("client_id is required")
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.client_id = client_id
        self.tenant_id = tenant_id
        # Entra issues tokens with different issuers depending on token version
        self.valid_issuers = [
            f"https://login.microsoftonline.com/{tenant_id}/v2.0",
            f"https://sts.windows.net/{tenant_id}/",
        ]
        # v2.0 JWKS endpoint covers both v1 and v2 tokens
        self.jwks_uri = (
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )
        self._jwks_client = pyjwt.PyJWKClient(self.jwks_uri, cache_keys=True)
        print(
            f"[entra-auth] Validator ready (client={client_id[:8]}..., "
            f"tenant={tenant_id[:8]}...)",
            file=sys.stderr,
        )

    @classmethod
    def from_env(cls) -> "EntraValidator | None":
        """Build from ENTRA_CLIENT_ID + ENTRA_TENANT_ID. Returns None if either
        is unset (lets callers fall through to no-auth or other paths)."""
        client_id = os.environ.get("ENTRA_CLIENT_ID")
        tenant_id = os.environ.get("ENTRA_TENANT_ID")
        if not client_id or not tenant_id:
            return None
        return cls(client_id, tenant_id)

    async def decode_and_get_claims(self, token: str) -> dict | None:
        """Validate the JWT signature, audience, issuer, and expiry.

        Returns the decoded claims dict on success, or None on any validation
        failure (expired, wrong audience, wrong issuer, malformed, signature
        invalid). Errors are logged to stderr — never raised.

        JWKS lookups are network-bound; we run the synchronous PyJWT calls
        in an executor to avoid blocking the event loop.
        """
        if not token:
            return None

        try:
            return await asyncio.to_thread(self._decode_sync, token)
        except Exception as exc:
            # Catch-all: never let a token validation error crash the request
            print(
                f"[entra-auth] Validation failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return None

    def _decode_sync(self, token: str) -> dict | None:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            valid_audiences = [
                self.client_id,
                f"api://{self.client_id}",
            ]
            decoded = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=valid_audiences,
                issuer=self.valid_issuers,
            )
            return decoded
        except pyjwt.ExpiredSignatureError:
            print("[entra-auth] Rejected: token expired", file=sys.stderr)
            return None
        except pyjwt.InvalidAudienceError:
            print(
                f"[entra-auth] Rejected: invalid audience (expected {self.client_id})",
                file=sys.stderr,
            )
            return None
        except pyjwt.InvalidIssuerError:
            print(
                f"[entra-auth] Rejected: invalid issuer (expected one of {self.valid_issuers})",
                file=sys.stderr,
            )
            return None
        except pyjwt.PyJWKClientError as exc:
            print(f"[entra-auth] JWKS lookup failed: {exc}", file=sys.stderr)
            return None
        except pyjwt.InvalidTokenError as exc:
            print(f"[entra-auth] Invalid token: {exc}", file=sys.stderr)
            return None


def get_user_email(claims: dict | None) -> str | None:
    """Extract a user email from validated Entra claims.

    Per Microsoft docs, the email-like claim varies by token version + tenant
    config. Preferred order:
        preferred_username (v2)  >  upn (v1)  >  email  >  None

    Returns None if claims is None or no usable claim is present.
    """
    if not claims:
        return None
    return (
        claims.get("preferred_username")
        or claims.get("upn")
        or claims.get("email")
        or None
    )


def get_user_name(claims: dict | None) -> str | None:
    """Extract a display name from validated Entra claims. Returns None if absent."""
    if not claims:
        return None
    return claims.get("name") or None
