"""Entra ID JWT validation for /mcp/dev path.

Validates Bearer tokens from Microsoft Entra ID using JWKS public keys.
Only used when ENTRA_CLIENT_ID and ENTRA_TENANT_ID env vars are set.
"""

from __future__ import annotations

import os
import sys
import time

import httpx
import jwt


class EntraValidator:
    """Validates Entra ID JWTs using JWKS public keys."""

    def __init__(self, client_id: str, tenant_id: str):
        self.client_id = client_id
        self.tenant_id = tenant_id
        self.issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        self.jwks_uri = (
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )
        self._jwks_client = jwt.PyJWKClient(self.jwks_uri, cache_keys=True)
        print(
            f"[entra-auth] OAuth enabled for /mcp/dev "
            f"(client: {client_id[:8]}..., tenant: {tenant_id[:8]}...)",
            file=sys.stderr,
        )

    @classmethod
    def from_env(cls) -> "EntraValidator | None":
        """Create from env vars. Returns None if not configured."""
        client_id = os.environ.get("ENTRA_CLIENT_ID")
        tenant_id = os.environ.get("ENTRA_TENANT_ID")
        if not client_id or not tenant_id:
            print(
                "[entra-auth] ENTRA_CLIENT_ID/ENTRA_TENANT_ID not set — "
                "OAuth disabled (all paths use API key auth)",
                file=sys.stderr,
            )
            return None
        return cls(client_id, tenant_id)

    async def validate(self, auth_header: str) -> str | None:
        """Validate a Bearer token. Returns error message or None if valid."""
        if not auth_header:
            return "Missing Authorization header. Use Bearer <token>."

        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return "Authorization header must be: Bearer <token>"

        token = parts[1]

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            decoded = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.issuer,
            )
            # Log successful auth
            user = decoded.get("preferred_username") or decoded.get("email") or "unknown"
            print(f"[entra-auth] Authenticated: {user}", file=sys.stderr)
            return None  # valid

        except jwt.ExpiredSignatureError:
            return "Token expired. Re-authenticate."
        except jwt.InvalidAudienceError:
            return f"Invalid audience. Expected: {self.client_id}"
        except jwt.InvalidIssuerError:
            return f"Invalid issuer. Expected: {self.issuer}"
        except jwt.PyJWKClientError as e:
            return f"Failed to fetch signing keys: {e}"
        except jwt.InvalidTokenError as e:
            return f"Invalid token: {e}"
        except Exception as e:
            return f"Auth error: {e}"
