from __future__ import annotations

import hashlib
import sys
import time

import httpx

from fastmcp.server.auth.providers.jwt import AccessToken, TokenVerifier


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
