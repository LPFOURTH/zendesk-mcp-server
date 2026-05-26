"""Tests for src/request_context.py — per-request contextvar handling.

Most critically, AUDIT-003 regression: a request that doesn't carry an
Authorization header must NOT inherit the previous request's Authorization
value from a stale contextvar.
"""

from __future__ import annotations

import pytest

from src.request_context import (
    authorization_var,
    extract_request_context,
    set_request_context,
    zendesk_environment_var,
    zendesk_subdomain_var,
)


@pytest.fixture(autouse=True)
def reset_contextvars():
    """Reset every contextvar to None before each test so state doesn't leak."""
    authorization_var.set(None)
    zendesk_subdomain_var.set(None)
    zendesk_environment_var.set(None)
    yield


def test_set_request_context_clears_authorization_when_absent():
    """AUDIT-003 regression: a context with no authorization key must
    overwrite (not inherit) the previous request's authorization value."""
    # Request A: arrives with an Authorization header
    set_request_context({"authorization": "Bearer alice-token"})
    assert authorization_var.get() == "Bearer alice-token"

    # Request B: arrives WITHOUT an Authorization header
    set_request_context({})
    assert authorization_var.get() is None, (
        "Authorization contextvar leaked from request A to request B"
    )


def test_set_request_context_clears_authorization_when_explicit_none():
    """Explicit `authorization: None` must clear the var (same scenario as
    extract_request_context returning {'authorization': None})."""
    set_request_context({"authorization": "Bearer alice-token"})
    set_request_context({"authorization": None})
    assert authorization_var.get() is None


def test_set_request_context_clears_all_vars_when_absent():
    """Every per-request contextvar follows the same overwrite-or-clear rule."""
    set_request_context({
        "authorization": "Bearer x",
        "zendesk_subdomain": "alpha",
        "zendesk_environment": "prod",
    })
    set_request_context({})
    assert authorization_var.get() is None
    assert zendesk_subdomain_var.get() is None
    assert zendesk_environment_var.get() is None


def test_set_request_context_overwrites_with_new_values():
    """A new request's values must replace prior values, not merge."""
    set_request_context({
        "authorization": "Bearer alice",
        "zendesk_subdomain": "alpha",
    })
    set_request_context({
        "authorization": "Bearer bob",
        "zendesk_subdomain": "beta",
    })
    assert authorization_var.get() == "Bearer bob"
    assert zendesk_subdomain_var.get() == "beta"


def test_extract_request_context_preserves_existing_behaviour():
    """Sanity: extract_request_context still returns the expected shape."""
    headers = {
        "authorization": "Bearer x",
        "x-zendesk-subdomain": "alpha",
        "x-zendesk-environment": "prod",
    }
    ctx = extract_request_context(headers)
    assert ctx["authorization"] == "Bearer x"
    assert ctx["zendesk_subdomain"] == "alpha"
    assert ctx["zendesk_environment"] == "prod"
