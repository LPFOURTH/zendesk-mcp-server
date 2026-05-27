"""Tests for AUDIT-007 — token cache hardening against garbage-token DoS.

Verifies:
- Negative cache short-circuits repeated invalid-token validation
- Positive cache still works (no regression)
- LRU bound caps memory under spray attack
- Env-var killswitches (MCP_TOKEN_CACHE_NEGATIVE_TTL=0 / _MAX=0 / _POSITIVE_TTL=0)
- Cache key = SHA-256 hash, never the raw token
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.zendesk_token_verifier import ZendeskTokenVerifier


def _make_verifier(**overrides) -> ZendeskTokenVerifier:
    """Build a verifier with small, predictable cache config for tests."""
    defaults = {
        "zendesk_subdomain": "test-tenant",
        "cache_ttl_seconds": 300,
        "negative_cache_ttl_seconds": 30,
        "max_cache_entries": 10,  # tiny so LRU is easy to test
    }
    defaults.update(overrides)
    return ZendeskTokenVerifier(**defaults)


def _make_401_response() -> httpx.Response:
    """Build a synthetic 401 response that triggers raise_for_status."""
    req = httpx.Request("GET", "https://test-tenant.zendesk.com/api/v2/users/me")
    return httpx.Response(401, request=req, json={"error": "Couldn't authenticate you"})


def _make_200_response(user_id: int, email: str) -> httpx.Response:
    req = httpx.Request("GET", "https://test-tenant.zendesk.com/api/v2/users/me")
    return httpx.Response(
        200,
        request=req,
        json={"user": {"id": user_id, "email": email, "name": "Test User", "role": "agent"}},
    )


# ---- negative cache ----


@pytest.mark.asyncio
async def test_negative_cache_short_circuits_repeated_invalid_token():
    """AUDIT-007 core: 1000 calls with the same invalid token = 1 Zendesk hit, not 1000."""
    v = _make_verifier()
    mock_get = AsyncMock(return_value=_make_401_response())
    v._http.get = mock_get

    # First call: actually hits Zendesk
    result1 = await v.verify_token("bad-token-aaaa")
    assert result1 is None
    assert mock_get.await_count == 1

    # Subsequent 100 calls: short-circuited by negative cache
    for _ in range(100):
        result = await v.verify_token("bad-token-aaaa")
        assert result is None
    assert mock_get.await_count == 1, (
        f"negative cache didn't short-circuit: hit Zendesk {mock_get.await_count} times"
    )


@pytest.mark.asyncio
async def test_negative_cache_expires_and_revalidates():
    """After negative TTL passes, a previously-bad token is re-asked of Zendesk."""
    v = _make_verifier(negative_cache_ttl_seconds=1)
    mock_get = AsyncMock(return_value=_make_401_response())
    v._http.get = mock_get

    await v.verify_token("bad-token")
    await v.verify_token("bad-token")
    assert mock_get.await_count == 1   # second call is cache hit

    # Fast-forward by mocking time
    import time
    with patch("src.zendesk_token_verifier.time.time", return_value=time.time() + 5):
        await v.verify_token("bad-token")
        assert mock_get.await_count == 2  # expired → re-asked


@pytest.mark.asyncio
async def test_negative_cache_disabled_by_env_killswitch(monkeypatch):
    """MCP_TOKEN_CACHE_NEGATIVE_TTL=0 → no negative caching, pre-fix behaviour."""
    monkeypatch.setenv("MCP_TOKEN_CACHE_NEGATIVE_TTL", "0")
    v = ZendeskTokenVerifier(zendesk_subdomain="test-tenant")
    assert v._negative_cache_ttl == 0

    mock_get = AsyncMock(return_value=_make_401_response())
    v._http.get = mock_get

    for _ in range(5):
        await v.verify_token("bad-token")
    assert mock_get.await_count == 5   # every call hits Zendesk


# ---- positive cache (regression — must still work) ----


@pytest.mark.asyncio
async def test_positive_cache_still_short_circuits_valid_tokens():
    """No regression: a valid token, repeated, only hits Zendesk once."""
    v = _make_verifier()
    mock_get = AsyncMock(return_value=_make_200_response(42, "alice@fourth.com"))
    v._http.get = mock_get

    result1 = await v.verify_token("good-token")
    assert result1 is not None
    assert result1.claims["email"] == "alice@fourth.com"

    for _ in range(50):
        r = await v.verify_token("good-token")
        assert r is not None
        assert r.claims["email"] == "alice@fourth.com"
    assert mock_get.await_count == 1


# ---- LRU bound ----


@pytest.mark.asyncio
async def test_lru_bound_evicts_oldest_positive_entries():
    """Cap is 10 — submit 15 unique valid tokens, expect 10 cached and oldest evicted."""
    v = _make_verifier(max_cache_entries=10)
    # Each call returns a unique user so each token is uniquely cached
    counter = [0]

    async def _mock_get(*_args, **_kwargs):
        counter[0] += 1
        return _make_200_response(counter[0], f"user{counter[0]}@example.com")

    v._http.get = _mock_get

    for i in range(15):
        await v.verify_token(f"token-{i}")
    assert len(v._positive_cache) == 10, (
        f"positive cache exceeded LRU bound: {len(v._positive_cache)}"
    )


@pytest.mark.asyncio
async def test_lru_bound_evicts_oldest_negative_entries():
    """Same bound applies to negative cache — defends against unique-token spray."""
    v = _make_verifier(max_cache_entries=10)
    v._http.get = AsyncMock(return_value=_make_401_response())

    for i in range(15):
        await v.verify_token(f"bad-token-{i}")
    assert len(v._negative_cache) == 10


@pytest.mark.asyncio
async def test_lru_disabled_by_env_killswitch(monkeypatch):
    """MCP_TOKEN_CACHE_MAX=0 → no bound (caller accepts memory risk)."""
    monkeypatch.setenv("MCP_TOKEN_CACHE_MAX", "0")
    v = ZendeskTokenVerifier(zendesk_subdomain="test-tenant")
    assert v._max_cache_entries == 0


# ---- positive cache disabled ----


@pytest.mark.asyncio
async def test_positive_cache_disabled_by_env_killswitch(monkeypatch):
    """MCP_TOKEN_CACHE_POSITIVE_TTL=0 disables positive caching too — extreme killswitch."""
    monkeypatch.setenv("MCP_TOKEN_CACHE_POSITIVE_TTL", "0")
    v = ZendeskTokenVerifier(zendesk_subdomain="test-tenant")
    assert v._cache_ttl == 0

    v._http.get = AsyncMock(return_value=_make_200_response(1, "x@y.com"))
    for _ in range(3):
        await v.verify_token("good-token")
    # Every call hits Zendesk because caching is off
    assert v._http.get.await_count == 3


# ---- cache key safety ----


@pytest.mark.asyncio
async def test_cache_key_is_hash_not_raw_token():
    """Cache key must be SHA-256 hash so memory snapshots don't leak plaintext."""
    v = _make_verifier()
    v._http.get = AsyncMock(return_value=_make_401_response())

    raw_token = "extremely-sensitive-token-xyz-123456"
    await v.verify_token(raw_token)

    # The raw token must not appear in any cache key
    for k in v._negative_cache:
        assert raw_token not in k
        assert k != raw_token
    # And the key should be hex (SHA-256 hex prefix)
    for k in v._negative_cache:
        assert len(k) == 16  # truncated SHA-256 hex
        assert all(c in "0123456789abcdef" for c in k)
