from __future__ import annotations

import asyncio
import hashlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.zendesk_token_verifier import ZendeskTokenVerifier


FAKE_TOKEN = "abc123_opaque_zendesk_token"
FAKE_USER = {
    "user": {
        "id": 12345,
        "email": "luke@fourth.com",
        "name": "Luke Pelcner",
        "role": "agent",
    }
}


@pytest.fixture
def verifier():
    return ZendeskTokenVerifier(zendesk_subdomain="hotschedules1760632913")


@pytest.mark.asyncio
async def test_valid_token_returns_access_token(verifier):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = FAKE_USER
    mock_response.raise_for_status = MagicMock()

    with patch.object(verifier._http, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
        result = await verifier.verify_token(FAKE_TOKEN)

    assert result is not None
    assert result.token == FAKE_TOKEN
    assert result.client_id == "12345"
    assert result.scopes == ["read", "write"]
    assert result.claims["email"] == "luke@fourth.com"
    assert result.claims["zendesk_user_id"] == 12345
    mock_get.assert_called_once_with(
        "https://hotschedules1760632913.zendesk.com/api/v2/users/me",
        headers={"Authorization": f"Bearer {FAKE_TOKEN}"},
    )


@pytest.mark.asyncio
async def test_invalid_token_returns_none(verifier):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Unauthorized", request=MagicMock(), response=mock_response
    )

    with patch.object(verifier._http, "get", new_callable=AsyncMock, return_value=mock_response):
        result = await verifier.verify_token(FAKE_TOKEN)

    assert result is None


@pytest.mark.asyncio
async def test_network_error_returns_none(verifier):
    with patch.object(
        verifier._http, "get", new_callable=AsyncMock, side_effect=httpx.ConnectError("connection refused")
    ):
        result = await verifier.verify_token(FAKE_TOKEN)

    assert result is None


@pytest.mark.asyncio
async def test_cache_hit_skips_http_call(verifier):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = FAKE_USER
    mock_response.raise_for_status = MagicMock()

    with patch.object(verifier._http, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
        result1 = await verifier.verify_token(FAKE_TOKEN)
        result2 = await verifier.verify_token(FAKE_TOKEN)

    assert result1 is not None
    assert result2 is not None
    assert result2.client_id == result1.client_id
    mock_get.assert_called_once()  # Only one HTTP call, second was cached


@pytest.mark.asyncio
async def test_cache_expires_after_ttl(verifier):
    verifier._cache_ttl = 0.1  # 100ms for testing

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = FAKE_USER
    mock_response.raise_for_status = MagicMock()

    with patch.object(verifier._http, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
        await verifier.verify_token(FAKE_TOKEN)
        await asyncio.sleep(0.15)  # Wait past TTL
        await verifier.verify_token(FAKE_TOKEN)

    assert mock_get.call_count == 2  # Two HTTP calls — cache expired


@pytest.mark.asyncio
async def test_failures_are_cached_within_negative_ttl(verifier):
    """AUDIT-007: invalid-token validation results are cached for
    `negative_cache_ttl_seconds` (default 30s) to defend against spray DoS.

    INVERTS pre-AUDIT-007 behaviour where failures were never cached.
    Trade-off accepted: revalidation of a token that becomes valid takes up
    to 30s. The DoS defense is more important than the freshness of
    transient-failure revalidation.
    """
    fail_response = MagicMock()
    fail_response.status_code = 401
    fail_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Unauthorized", request=MagicMock(), response=fail_response
    )

    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.json.return_value = FAKE_USER
    ok_response.raise_for_status = MagicMock()

    with patch.object(
        verifier._http, "get", new_callable=AsyncMock, side_effect=[fail_response, ok_response]
    ) as mock_get:
        result1 = await verifier.verify_token(FAKE_TOKEN)
        result2 = await verifier.verify_token(FAKE_TOKEN)

    assert result1 is None
    # Second call short-circuits via negative cache — Zendesk never asked
    # the second time even though it WOULD have returned 200. Only 1 HTTP call.
    assert result2 is None, "negative cache should short-circuit second call"
    assert mock_get.call_count == 1, (
        f"expected 1 Zendesk call (second served from negative cache), got {mock_get.call_count}"
    )


@pytest.mark.asyncio
async def test_failures_revalidate_after_negative_ttl_expires(verifier):
    """After the negative TTL window passes, the same previously-bad token
    is re-asked of Zendesk — so genuinely-fixed accounts come back online."""
    verifier._negative_cache_ttl = 0.1  # 100ms negative TTL for this test

    fail_response = MagicMock()
    fail_response.status_code = 401
    fail_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Unauthorized", request=MagicMock(), response=fail_response
    )
    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.json.return_value = FAKE_USER
    ok_response.raise_for_status = MagicMock()

    with patch.object(
        verifier._http, "get", new_callable=AsyncMock,
        side_effect=[fail_response, ok_response],
    ) as mock_get:
        result1 = await verifier.verify_token(FAKE_TOKEN)
        await asyncio.sleep(0.15)   # past negative TTL
        result2 = await verifier.verify_token(FAKE_TOKEN)

    assert result1 is None
    assert result2 is not None     # revalidated successfully
    assert mock_get.call_count == 2
