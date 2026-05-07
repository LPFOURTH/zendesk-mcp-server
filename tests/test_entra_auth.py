"""Tests for the Entra ID JWT validator.

The validator is used by the /zendesk-sso endpoint to authenticate users
before minting a Zendesk JWT. Per Architecture E (Path B), the Entra token
proves identity; we trust the Entra signature and pass the user's email +
name into the Zendesk JWT.

Tests use a self-signed RSA key + mocked JWKS so we don't depend on
Microsoft's live infrastructure.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


CLIENT_ID = "test-client-79da6be7"
TENANT_ID = "test-tenant-75cd3b18"


@pytest.fixture
def rsa_keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_key = private.public_key()
    return private_pem, public_key


def _make_v2_token(private_pem: bytes, *, claims_override: dict | None = None) -> str:
    base = {
        "iss": f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
        "aud": CLIENT_ID,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "sub": "subject-uuid",
        "preferred_username": "alice@fourth.com",
        "name": "Alice Smith",
    }
    if claims_override:
        base.update(claims_override)
    return pyjwt.encode(base, private_pem, algorithm="RS256")


def _make_v1_token(private_pem: bytes, *, claims_override: dict | None = None) -> str:
    base = {
        "iss": f"https://sts.windows.net/{TENANT_ID}/",
        "aud": f"api://{CLIENT_ID}",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "sub": "subject-uuid",
        "upn": "alice@fourth.com",
        "name": "Alice Smith",
    }
    if claims_override:
        base.update(claims_override)
    return pyjwt.encode(base, private_pem, algorithm="RS256")


@pytest.fixture
def validator_with_mocked_jwks(rsa_keys):
    """Build an EntraValidator with its JWKS client patched to return our RSA key."""
    from src.entra_auth import EntraValidator

    private_pem, public_key = rsa_keys

    v = EntraValidator(client_id=CLIENT_ID, tenant_id=TENANT_ID)

    # Patch the JWKS client to return our test public key
    fake_signing_key = MagicMock()
    fake_signing_key.key = public_key
    v._jwks_client.get_signing_key_from_jwt = MagicMock(return_value=fake_signing_key)

    return v, private_pem


# ---- decode_and_get_claims() ----


@pytest.mark.asyncio
async def test_validate_accepts_valid_v2_token(validator_with_mocked_jwks):
    v, private_pem = validator_with_mocked_jwks
    token = _make_v2_token(private_pem)
    claims = await v.decode_and_get_claims(token)
    assert claims is not None
    assert claims["preferred_username"] == "alice@fourth.com"
    assert claims["name"] == "Alice Smith"


@pytest.mark.asyncio
async def test_validate_accepts_valid_v1_token(validator_with_mocked_jwks):
    v, private_pem = validator_with_mocked_jwks
    token = _make_v1_token(private_pem)
    claims = await v.decode_and_get_claims(token)
    assert claims is not None
    assert claims["upn"] == "alice@fourth.com"


@pytest.mark.asyncio
async def test_validate_rejects_expired_token(validator_with_mocked_jwks):
    v, private_pem = validator_with_mocked_jwks
    token = _make_v2_token(
        private_pem,
        claims_override={"exp": int(time.time()) - 60, "iat": int(time.time()) - 3600},
    )
    claims = await v.decode_and_get_claims(token)
    assert claims is None


@pytest.mark.asyncio
async def test_validate_rejects_wrong_audience(validator_with_mocked_jwks):
    v, private_pem = validator_with_mocked_jwks
    token = _make_v2_token(private_pem, claims_override={"aud": "different-client"})
    claims = await v.decode_and_get_claims(token)
    assert claims is None


@pytest.mark.asyncio
async def test_validate_rejects_wrong_issuer(validator_with_mocked_jwks):
    v, private_pem = validator_with_mocked_jwks
    token = _make_v2_token(
        private_pem,
        claims_override={"iss": "https://login.microsoftonline.com/other-tenant/v2.0"},
    )
    claims = await v.decode_and_get_claims(token)
    assert claims is None


@pytest.mark.asyncio
async def test_validate_rejects_garbage_token(validator_with_mocked_jwks):
    v, _ = validator_with_mocked_jwks
    claims = await v.decode_and_get_claims("not.a.valid.jwt")
    assert claims is None


@pytest.mark.asyncio
async def test_validate_rejects_empty_token(validator_with_mocked_jwks):
    v, _ = validator_with_mocked_jwks
    claims = await v.decode_and_get_claims("")
    assert claims is None


# ---- factory / from_env ----


def test_from_env_returns_none_when_unconfigured(monkeypatch):
    from src.entra_auth import EntraValidator

    monkeypatch.delenv("ENTRA_CLIENT_ID", raising=False)
    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
    assert EntraValidator.from_env() is None


def test_from_env_builds_validator_when_configured(monkeypatch):
    from src.entra_auth import EntraValidator

    monkeypatch.setenv("ENTRA_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("ENTRA_TENANT_ID", TENANT_ID)
    v = EntraValidator.from_env()
    assert v is not None
    assert v.client_id == CLIENT_ID
    assert v.tenant_id == TENANT_ID


# ---- email/name extraction helper ----


@pytest.mark.asyncio
async def test_get_user_email_prefers_preferred_username(validator_with_mocked_jwks):
    """preferred_username (v2) > upn (v1) > email > None."""
    v, private_pem = validator_with_mocked_jwks
    token = _make_v2_token(
        private_pem,
        claims_override={
            "preferred_username": "alice@fourth.com",
            "upn": "alice-different@fourth.com",
            "email": "alice-third@fourth.com",
        },
    )
    claims = await v.decode_and_get_claims(token)
    from src.entra_auth import get_user_email

    assert get_user_email(claims) == "alice@fourth.com"


@pytest.mark.asyncio
async def test_get_user_email_falls_back_to_upn(validator_with_mocked_jwks):
    v, private_pem = validator_with_mocked_jwks
    token = _make_v1_token(private_pem)  # has upn, no preferred_username
    claims = await v.decode_and_get_claims(token)
    from src.entra_auth import get_user_email

    assert get_user_email(claims) == "alice@fourth.com"


def test_get_user_email_returns_none_for_empty_claims():
    from src.entra_auth import get_user_email

    assert get_user_email({}) is None
    assert get_user_email(None) is None
