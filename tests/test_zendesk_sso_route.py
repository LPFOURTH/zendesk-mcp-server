"""Tests for the /zendesk-sso route handler.

Uses a mocked EntraValidator (we don't need the full RSA/JWKS flow here —
that's covered by test_entra_auth) and a real ZendeskJwtMinter. Focus is
on the request → response behavior of the route.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient


SHARED_SECRET = "testing-shared-secret-do-not-use-in-prod-32+-bytes"


@pytest.fixture
def make_app():
    """Factory that builds a minimal Starlette app with the /zendesk-sso route
    wired to a mock validator + real minter."""
    from src.zendesk_jwt_sso import ZendeskJwtMinter
    from src.zendesk_sso_route import make_zendesk_sso_route

    def _factory(*, validator_returns: dict | None = None, validator_raises: bool = False):
        mock_validator = MagicMock()
        if validator_raises:
            mock_validator.decode_and_get_claims = AsyncMock(side_effect=RuntimeError("boom"))
        else:
            mock_validator.decode_and_get_claims = AsyncMock(return_value=validator_returns)
        minter = ZendeskJwtMinter(shared_secret=SHARED_SECRET)
        route = make_zendesk_sso_route(
            entra_validator=mock_validator,
            zendesk_jwt_minter=minter,
            zendesk_subdomain="hotschedules",
        )
        app = Starlette(routes=[Route("/zendesk-sso", route, methods=["GET", "POST"])])
        return app, mock_validator

    return _factory


def test_returns_401_when_no_token(make_app):
    app, _ = make_app(validator_returns=None)
    client = TestClient(app)
    resp = client.get("/zendesk-sso")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "unauthorized"


def test_returns_401_when_token_invalid(make_app):
    app, _ = make_app(validator_returns=None)  # validator returns None → invalid
    client = TestClient(app)
    resp = client.get("/zendesk-sso", headers={"Authorization": "Bearer fake-token"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_token"


def test_returns_400_when_claims_missing_email(make_app):
    app, _ = make_app(
        validator_returns={"sub": "abc", "name": "Alice"}  # no email-like claim
    )
    client = TestClient(app)
    resp = client.get(
        "/zendesk-sso", headers={"Authorization": "Bearer fake-token"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "missing_claims"


def test_returns_403_when_email_not_fourth(make_app):
    app, _ = make_app(
        validator_returns={
            "sub": "abc",
            "preferred_username": "alice@otherco.com",
            "name": "Alice",
        }
    )
    client = TestClient(app)
    resp = client.get(
        "/zendesk-sso", headers={"Authorization": "Bearer fake-token"}
    )
    assert resp.status_code == 403
    assert resp.json()["error"] == "forbidden"


def test_happy_path_returns_html_form_with_jwt(make_app):
    app, _ = make_app(
        validator_returns={
            "sub": "abc",
            "preferred_username": "alice@fourth.com",
            "name": "Alice Smith",
        }
    )
    client = TestClient(app)
    resp = client.get(
        "/zendesk-sso", headers={"Authorization": "Bearer fake-token"}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    html = resp.text
    assert 'name="jwt"' in html
    assert "hotschedules.zendesk.com/access/jwt" in html
    # Auto-submit script
    assert "submit" in html.lower()


def test_return_to_query_param_propagates_to_form(make_app):
    app, _ = make_app(
        validator_returns={
            "sub": "abc",
            "preferred_username": "alice@fourth.com",
            "name": "Alice",
        }
    )
    client = TestClient(app)
    resp = client.get(
        "/zendesk-sso?return_to=https%3A%2F%2Fhotschedules.zendesk.com%2Foauth%2Fauthorizations%2Fnew%3Fclient_id%3Dabc",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert resp.status_code == 200
    assert 'name="return_to"' in resp.text
    assert "client_id=abc" in resp.text or "client_id%3Dabc" in resp.text


def test_cookie_token_accepted_when_no_header(make_app):
    app, _ = make_app(
        validator_returns={
            "sub": "abc",
            "preferred_username": "alice@fourth.com",
            "name": "Alice",
        }
    )
    client = TestClient(app)
    resp = client.get("/zendesk-sso", cookies={"entra_id_token": "fake-token"})
    assert resp.status_code == 200
    assert 'name="jwt"' in resp.text


def test_header_takes_precedence_over_cookie(make_app):
    """If both header and cookie present, header wins (more explicit)."""
    app, mock_validator = make_app(
        validator_returns={
            "sub": "abc",
            "preferred_username": "alice@fourth.com",
            "name": "Alice",
        }
    )
    client = TestClient(app)
    resp = client.get(
        "/zendesk-sso",
        headers={"Authorization": "Bearer header-token"},
        cookies={"entra_id_token": "cookie-token"},
    )
    assert resp.status_code == 200
    # The validator should have been called with the header token, not cookie
    mock_validator.decode_and_get_claims.assert_awaited_once_with("header-token")


def test_email_lookup_uses_upn_fallback(make_app):
    """v1-style token uses upn instead of preferred_username."""
    app, _ = make_app(
        validator_returns={
            "sub": "abc",
            "upn": "bob@fourth.com",
            "name": "Bob",
        }
    )
    client = TestClient(app)
    resp = client.get(
        "/zendesk-sso", headers={"Authorization": "Bearer fake-token"}
    )
    assert resp.status_code == 200
    # JWT should be minted for bob@fourth.com — decode and verify
    import re
    m = re.search(r'name="jwt" value="([^"]+)"', resp.text)
    assert m
    import jwt as pyjwt
    decoded = pyjwt.decode(m.group(1), SHARED_SECRET, algorithms=["HS256"])
    assert decoded["email"] == "bob@fourth.com"
    assert decoded["name"] == "Bob"


def test_malformed_authorization_header_falls_through_to_cookie(make_app):
    """Authorization: Basic ... should be ignored (only Bearer is honored)."""
    app, _ = make_app(
        validator_returns={
            "sub": "abc",
            "preferred_username": "alice@fourth.com",
            "name": "Alice",
        }
    )
    client = TestClient(app)
    # Basic-scheme header is ignored; cookie used instead
    resp = client.get(
        "/zendesk-sso",
        headers={"Authorization": "Basic abcd1234"},
        cookies={"entra_id_token": "cookie-token"},
    )
    assert resp.status_code == 200


def test_no_token_no_cookie_basic_header_returns_401(make_app):
    app, _ = make_app(validator_returns=None)
    client = TestClient(app)
    resp = client.get(
        "/zendesk-sso", headers={"Authorization": "Basic abcd1234"}
    )
    assert resp.status_code == 401
