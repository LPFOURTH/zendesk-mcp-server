"""Resolve a Fourth user's Entra email → their Zendesk user_id.

Used by Architecture F (v3.10.0+) write tools to set `requester_id` /
`author_id` on payloads sent to Zendesk so per-user attribution is preserved
in Zendesk audit logs even though all API calls authenticate with the
service-account credential.

Lookup uses Zendesk's user search API. Results are cached in-process with a
configurable TTL (default 5 minutes). Per-pod cache is intentional — the
email→user_id mapping is stable, so the cost of a cold lookup per pod is one
GET, and cross-pod cache sharing isn't worth the Cosmos dependency.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable


class ZendeskUserResolver:
    """Async resolver: Entra email → Zendesk user_id, with TTL cache.

    The Zendesk client is injected (not imported) so tests can substitute a
    fake without spinning up the module-level singleton.
    """

    def __init__(
        self,
        search_fn: Callable[[str], Awaitable[dict]],
        cache_ttl_seconds: int = 300,
    ) -> None:
        self._search = search_fn
        self._ttl = cache_ttl_seconds
        # email_lower -> (user_id_or_None, expires_at)
        self._cache: dict[str, tuple[int | None, float]] = {}
        # one in-flight lookup per email to avoid thundering-herd
        self._locks: dict[str, asyncio.Lock] = {}

    async def resolve(self, email: str | None) -> int | None:
        """Return the Zendesk user_id for `email`, or None if unresolvable.

        - Empty/missing email → None
        - Multiple agents share the email → first match wins (Zendesk should
          enforce email uniqueness; the multi-match path is a safety net)
        - Zendesk lookup fails or returns no user → None (cached as None to
          avoid retry-storm) but with a shorter TTL than positive entries
        """
        if not email:
            return None
        key = email.strip().lower()
        if not key:
            return None

        now = time.time()
        cached = self._cache.get(key)
        if cached is not None and cached[1] > now:
            return cached[0]

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Re-check under the lock — another coroutine may have populated
            cached = self._cache.get(key)
            if cached is not None and cached[1] > now:
                return cached[0]

            try:
                body = await self._search(key)
            except Exception:
                # Negative-cache transient errors briefly so we don't hammer
                # Zendesk during an outage. 30s = TTL/10.
                self._cache[key] = (None, now + max(30, self._ttl // 10))
                return None

            users = body.get("users") or []
            user_id: int | None = None
            for u in users:
                if (u.get("email") or "").strip().lower() == key:
                    user_id = u.get("id")
                    if user_id is not None:
                        break
            self._cache[key] = (user_id, now + self._ttl)
            return user_id


def make_default_search_fn() -> Callable[[str], Awaitable[dict]]:
    """Return a search_fn bound to the module-level `zendesk_client`.

    Importing here is deliberate — keeps the resolver class itself
    dependency-free for testing.
    """
    from .zendesk_client import zendesk_client

    async def _search(email: str) -> dict:
        return await zendesk_client.request(
            "GET",
            "/users/search.json",
            params={"query": f"email:{email}"},
        )

    return _search


# Module-level default resolver used by tools. Tests should construct their
# own ZendeskUserResolver with a stub search_fn.
_default_resolver: ZendeskUserResolver | None = None


def get_default_resolver() -> ZendeskUserResolver:
    """Lazy-init the module-level resolver bound to the real Zendesk client."""
    global _default_resolver
    if _default_resolver is None:
        _default_resolver = ZendeskUserResolver(make_default_search_fn())
    return _default_resolver


async def resolve_zendesk_user_id(email: str | None) -> int | None:
    """Convenience: resolve via the default module-level resolver."""
    return await get_default_resolver().resolve(email)
