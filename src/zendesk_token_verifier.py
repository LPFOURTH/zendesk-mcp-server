from __future__ import annotations

import hashlib
import sys
import time

import httpx
from pydantic import AnyHttpUrl

from fastmcp.server.auth import OAuthProxy
from fastmcp.server.auth.providers.jwt import AccessToken, TokenVerifier


class ZendeskOAuthProxy(OAuthProxy):
    """OAuthProxy that advertises the base_url as the protected resource URL.

    FastMCP's default behavior appends the MCP endpoint path (/mcp) to the
    base_url when constructing the resource URL, yielding e.g. /mcp/dev/mcp.
    MCP clients (Claude Code) require the resource URL in metadata to equal
    the URL they're registered with. Since users register the OAuth-gated
    URL (/mcp/dev), we override to return base_url unchanged.
    """

    def _get_resource_url(self, path: str | None = None) -> AnyHttpUrl | None:
        return self.resource_base_url or self.base_url


class ZendeskTokenVerifier(TokenVerifier):
    """Validates Zendesk opaque OAuth tokens by calling /api/v2/users/me.

    Caches successful validations in memory with a configurable TTL to avoid
    hitting the Zendesk API on every MCP tool call.
    """

    def __init__(
        self,
        zendesk_subdomain: str,
        cache_ttl_seconds: int = 300,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._subdomain = zendesk_subdomain
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[str, tuple[AccessToken, float]] = {}
        self._http = httpx.AsyncClient(timeout=10.0)

    async def verify_token(self, token: str) -> AccessToken | None:
        cache_key = hashlib.sha256(token.encode()).hexdigest()[:16]
        now = time.time()

        # Evict expired entries lazily
        expired = [k for k, (_, exp) in self._cache.items() if exp <= now]
        for k in expired:
            del self._cache[k]

        # Cache hit
        cached = self._cache.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]

        # Validate by calling Zendesk API
        try:
            resp = await self._http.get(
                f"https://{self._subdomain}.zendesk.com/api/v2/users/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            user = resp.json()["user"]
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError) as exc:
            print(
                f"[zendesk-token-verifier] Token validation failed: {exc}",
                file=sys.stderr,
            )
            return None

        access_token = AccessToken(
            token=token,
            client_id=str(user["id"]),
            scopes=["read", "write"],
            claims={
                "zendesk_user_id": user["id"],
                "email": user["email"],
                "name": user["name"],
                "role": user["role"],
            },
        )

        self._cache[cache_key] = (access_token, now + self._cache_ttl)
        return access_token
