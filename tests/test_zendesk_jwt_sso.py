"""Tests for the Zendesk JWT SSO minter.

Tests cover JWT minting (HS256, required claims, replay protection) and the
auto-submit HTML form rendering. Per Zendesk's JWT SSO spec:
https://support.zendesk.com/hc/en-us/articles/4408881965722-Anatomy-of-a-JWT-request
"""

from __future__ import annotations

import time
from typing import Any

import jwt as pyjwt
import pytest


SHARED_SECRET = "testing-shared-secret-do-not-use-in-prod-32+-bytes"


@pytest.fixture
def minter():
    from src.zendesk_jwt_sso import ZendeskJwtMinter
    return ZendeskJwtMinter(shared_secret=SHARED_SECRET)


# ---- mint() tests ----


def test_mint_returns_hs256_jwt(minter):
    token = minter.mint(email="alice@fourth.com", name="Alice")
    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "HS256"
    assert header["typ"] == "JWT"


def test_mint_includes_required_claims(minter):
    token = minter.mint(email="alice@fourth.com", name="Alice Smith")
    decoded: dict[str, Any] = pyjwt.decode(
        token, SHARED_SECRET, algorithms=["HS256"], options={"verify_signature": True}
    )
    # Per Zendesk: iat, jti, email, name are required
    assert "iat" in decoded
    assert "jti" in decoded
    assert decoded["email"] == "alice@fourth.com"
    assert decoded["name"] == "Alice Smith"


def test_mint_jti_unique_across_calls(minter):
    a = pyjwt.decode(
        minter.mint(email="a@fourth.com", name="A"),
        SHARED_SECRET,
        algorithms=["HS256"],
    )
    b = pyjwt.decode(
        minter.mint(email="a@fourth.com", name="A"),
        SHARED_SECRET,
        algorithms=["HS256"],
    )
    assert a["jti"] != b["jti"]


def test_mint_iat_close_to_now(minter):
    before = int(time.time())
    token = minter.mint(email="a@fourth.com", name="A")
    after = int(time.time())
    decoded = pyjwt.decode(token, SHARED_SECRET, algorithms=["HS256"])
    assert before <= decoded["iat"] <= after


def test_mint_signature_validates_with_shared_secret(minter):
    token = minter.mint(email="a@fourth.com", name="A")
    # Should NOT raise
    pyjwt.decode(token, SHARED_SECRET, algorithms=["HS256"])


def test_mint_signature_invalid_with_wrong_secret(minter):
    token = minter.mint(email="a@fourth.com", name="A")
    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(token, "wrong-secret", algorithms=["HS256"])


def test_mint_email_required(minter):
    with pytest.raises(ValueError, match="email"):
        minter.mint(email="", name="A")


def test_mint_name_required(minter):
    with pytest.raises(ValueError, match="name"):
        minter.mint(email="a@fourth.com", name="")


def test_mint_extra_claims_passed_through(minter):
    token = minter.mint(
        email="a@fourth.com",
        name="A",
        external_id="user-42",
        organization="Fourth Ltd",
    )
    decoded = pyjwt.decode(token, SHARED_SECRET, algorithms=["HS256"])
    assert decoded["external_id"] == "user-42"
    assert decoded["organization"] == "Fourth Ltd"


def test_mint_email_verified_defaults_false(minter):
    """Per Zendesk security guidance, do not assert email_verified=true unless we
    have proof. Default to False."""
    token = minter.mint(email="a@fourth.com", name="A")
    decoded = pyjwt.decode(token, SHARED_SECRET, algorithms=["HS256"])
    assert decoded.get("email_verified") in (False, None)


# ---- render_auto_submit_html() tests ----


def test_render_html_contains_jwt_in_hidden_input(minter):
    token = minter.mint(email="a@fourth.com", name="A")
    html = minter.render_auto_submit_html(
        jwt_token=token, zendesk_subdomain="hotschedules"
    )
    assert f'name="jwt"' in html
    assert token in html
    assert 'type="hidden"' in html


def test_render_html_post_action_is_zendesk_jwt_endpoint(minter):
    token = minter.mint(email="a@fourth.com", name="A")
    html = minter.render_auto_submit_html(
        jwt_token=token, zendesk_subdomain="hotschedules"
    )
    assert 'method="POST"' in html or "method='POST'" in html or 'method="post"' in html
    assert "https://hotschedules.zendesk.com/access/jwt" in html


def test_render_html_includes_return_to_when_provided(minter):
    token = minter.mint(email="a@fourth.com", name="A")
    html = minter.render_auto_submit_html(
        jwt_token=token,
        zendesk_subdomain="hotschedules",
        return_to="https://hotschedules.zendesk.com/oauth/authorizations/new?client_id=abc",
    )
    assert 'name="return_to"' in html
    # The URL should appear in the form (HTML-escaped is fine — & becomes &amp;)
    assert "client_id=abc" in html or "client_id%3Dabc" in html


def test_render_html_omits_return_to_when_absent(minter):
    token = minter.mint(email="a@fourth.com", name="A")
    html = minter.render_auto_submit_html(
        jwt_token=token, zendesk_subdomain="hotschedules"
    )
    assert 'name="return_to"' not in html


def test_render_html_auto_submits(minter):
    token = minter.mint(email="a@fourth.com", name="A")
    html = minter.render_auto_submit_html(
        jwt_token=token, zendesk_subdomain="hotschedules"
    )
    # Auto-submit happens via inline script (form.submit())
    assert "submit" in html.lower()


def test_render_html_rejects_malformed_subdomain(minter):
    """Defense in depth: any subdomain that wouldn't pass Zendesk's own format
    check (alphanumeric + hyphens, 3-63 chars) must be rejected with ValueError
    rather than silently producing an HTML page with an injection-prone URL."""
    token = minter.mint(email="a@fourth.com", name="A")
    bad_subdomains = [
        "evil.attacker.com/path?x=",  # path injection attempt
        "with spaces",
        "UPPERCASE",
        "-leading-hyphen",
        "trailing-hyphen-",
        "ab",  # too short
        "",
    ]
    for bad in bad_subdomains:
        with pytest.raises(ValueError, match="subdomain"):
            minter.render_auto_submit_html(jwt_token=token, zendesk_subdomain=bad)


def test_render_html_accepts_valid_subdomain(minter):
    """Counterpart to the rejection test — confirm normal subdomains succeed."""
    token = minter.mint(email="a@fourth.com", name="A")
    html_out = minter.render_auto_submit_html(
        jwt_token=token, zendesk_subdomain="hotschedules"
    )
    assert "hotschedules.zendesk.com/access/jwt" in html_out
