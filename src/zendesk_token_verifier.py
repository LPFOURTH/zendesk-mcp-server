from __future__ import annotations

import hashlib
import os
import sys
import time
from collections import OrderedDict

import httpx
from pydantic import AnyHttpUrl

from fastmcp.server.auth import OAuthProxy
from fastmcp.server.auth.providers.azure import AzureProvider
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


class EntraOAuthProxy(AzureProvider):
    """AzureProvider that advertises the base_url as the protected-resource URL.

    Same fix as ZendeskOAuthProxy but for the Architecture F (Entra) auth path:
    FastMCP's default appends `/mcp` to base_url when constructing the
    protected-resource metadata, yielding `.../mcp/dev/mcp`. MCP clients
    (Claude Code's SDK) compare the advertised resource URL against the URL
    they registered with — `.../mcp/dev` — and refuse to proceed on mismatch
    (observed in v3.10.0: "SDK auth failed: Protected resource ... does not
    match expected ... (or origin)").

    Without this override the OAuth dance never makes it to the Microsoft
    picker — the SDK aborts during metadata discovery.
    """

    def _get_resource_url(self, path: str | None = None) -> AnyHttpUrl | None:
        return self.resource_base_url or self.base_url


_DEFAULT_POSITIVE_TTL = 300       # 5 min: successful validation stays cached
_DEFAULT_NEGATIVE_TTL = 30        # 30 s: failed validation stays cached
_DEFAULT_MAX_CACHE_ENTRIES = 10000  # LRU bound, shared across positive + negative


def _int_env(name: str, default: int) -> int:
    """Read a non-negative integer from env; fall back to default on parse failure."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        return value if value >= 0 else default
    except ValueError:
        return default


class ZendeskTokenVerifier(TokenVerifier):
    """Validates Zendesk opaque OAuth tokens by calling /api/v2/users/me.

    Two-layer cache (AUDIT-007 hardening):

    - **Positive cache** — successful validations stored for cache_ttl_seconds
      (default 300s). Avoids hitting Zendesk on every MCP tool call from a
      legitimate user.
    - **Negative cache** — failed validations stored for negative_cache_ttl_seconds
      (default 30s). Defends against garbage-token spray DoS: an attacker
      sending 1000 invalid tokens/sec would have hit Zendesk's /users/me
      endpoint 1000 times before the fix; now only on the first attempt per
      token, then cache short-circuits for 30s.

    Both caches share an LRU bound (default 10k entries each). Excess entries
    evict oldest-first via `OrderedDict.popitem(last=False)`. Prevents
    memory exhaustion when the attacker sprays unique tokens (each one would
    permanently allocate a cache entry without the bound).

    Operational killswitches (env vars, no redeploy needed):
      MCP_TOKEN_CACHE_NEGATIVE_TTL=0   disables negative caching (falls back
                                       to pre-fix behaviour — hit Zendesk
                                       on every invalid token)
      MCP_TOKEN_CACHE_MAX=0            disables LRU bound (unbounded growth)
      MCP_TOKEN_CACHE_POSITIVE_TTL=0   disables positive caching entirely

    Cache keys are SHA-256(token)[:16] — token plaintext never sits in the
    cache. Reduces blast radius if a crash dump or memory snapshot leaks.
    """

    def __init__(
        self,
        zendesk_subdomain: str,
        cache_ttl_seconds: int | None = None,
        negative_cache_ttl_seconds: int | None = None,
        max_cache_entries: int | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._subdomain = zendesk_subdomain
        # Constructor args win; env vars override defaults; defaults are last resort.
        self._cache_ttl = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else _int_env("MCP_TOKEN_CACHE_POSITIVE_TTL", _DEFAULT_POSITIVE_TTL)
        )
        self._negative_cache_ttl = (
            negative_cache_ttl_seconds
            if negative_cache_ttl_seconds is not None
            else _int_env("MCP_TOKEN_CACHE_NEGATIVE_TTL", _DEFAULT_NEGATIVE_TTL)
        )
        self._max_cache_entries = (
            max_cache_entries
            if max_cache_entries is not None
            else _int_env("MCP_TOKEN_CACHE_MAX", _DEFAULT_MAX_CACHE_ENTRIES)
        )
        self._positive_cache: OrderedDict[str, tuple[AccessToken, float]] = OrderedDict()
        self._negative_cache: OrderedDict[str, float] = OrderedDict()
        self._http = httpx.AsyncClient(timeout=10.0)

    # ---- internal cache helpers ----

    def _evict_expired(self, now: float) -> None:
        """Drop expired entries from both caches. Cheap — runs every verify."""
        expired_positive = [k for k, (_, exp) in self._positive_cache.items() if exp <= now]
        for k in expired_positive:
            del self._positive_cache[k]
        expired_negative = [k for k, exp in self._negative_cache.items() if exp <= now]
        for k in expired_negative:
            del self._negative_cache[k]

    def _set_positive(self, key: str, value: AccessToken, expires_at: float) -> None:
        if self._cache_ttl == 0:
            return
        self._positive_cache[key] = (value, expires_at)
        self._positive_cache.move_to_end(key)
        if self._max_cache_entries:
            while len(self._positive_cache) > self._max_cache_entries:
                self._positive_cache.popitem(last=False)

    def _set_negative(self, key: str, expires_at: float) -> None:
        if self._negative_cache_ttl == 0:
            return
        self._negative_cache[key] = expires_at
        self._negative_cache.move_to_end(key)
        if self._max_cache_entries:
            while len(self._negative_cache) > self._max_cache_entries:
                self._negative_cache.popitem(last=False)

    # ---- public API ----

    async def verify_token(self, token: str) -> AccessToken | None:
        cache_key = hashlib.sha256(token.encode()).hexdigest()[:16]
        now = time.time()

        self._evict_expired(now)

        # Positive cache hit — valid user, skip the Zendesk round-trip.
        positive = self._positive_cache.get(cache_key)
        if positive and positive[1] > now:
            self._positive_cache.move_to_end(cache_key)
            return positive[0]

        # Negative cache hit — already known-bad, skip the Zendesk round-trip.
        # This is the DoS defense: 1000 garbage-token requests = 1 Zendesk call,
        # not 1000.
        negative_exp = self._negative_cache.get(cache_key)
        if negative_exp and negative_exp > now:
            return None

        # Cache miss — actually ask Zendesk.
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
            self._set_negative(cache_key, now + self._negative_cache_ttl)
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
        self._set_positive(cache_key, access_token, now + self._cache_ttl)
        return access_token
