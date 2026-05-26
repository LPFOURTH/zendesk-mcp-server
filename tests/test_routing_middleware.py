"""Tests for src/main.py routing-middleware helpers.

Focused on AUDIT-009: caller-controlled environment-routing headers must
not be able to override the path-derived env_name that the middleware
injects.
"""

from __future__ import annotations

from src.main import _strip_caller_environment_headers
from src.request_context import extract_request_context


def test_strip_removes_both_x_prefixed_and_canonical_env_headers():
    """AUDIT-009: both `x-zendesk-environment` and `zendesk-environment`
    forms must be removed so neither can leak through extract_request_context.
    """
    h = {
        "x-zendesk-environment": "prod",
        "zendesk-environment": "prod",
        "authorization": "Bearer x",
        "content-type": "application/json",
    }
    _strip_caller_environment_headers(h)
    assert "x-zendesk-environment" not in h
    assert "zendesk-environment" not in h
    # Other headers untouched
    assert h["authorization"] == "Bearer x"
    assert h["content-type"] == "application/json"


def test_strip_is_safe_when_headers_absent():
    """Stripping when keys don't exist must not raise."""
    h = {"authorization": "Bearer x"}
    _strip_caller_environment_headers(h)
    assert h == {"authorization": "Bearer x"}


def test_caller_x_zendesk_environment_cannot_override_path_derived():
    """End-to-end: a malicious caller sending X-Zendesk-Environment: prod
    on a request routed by path to env_name='dev' must end up with
    zendesk_environment='dev' in the extracted context."""
    raw_headers = {
        "x-zendesk-environment": "prod",   # attacker tries to redirect to prod
        "authorization": "Bearer x",
    }

    # Simulate the middleware's behaviour:
    _strip_caller_environment_headers(raw_headers)
    raw_headers["zendesk-environment"] = "dev"   # path-derived value

    ctx = extract_request_context(raw_headers)
    assert ctx["zendesk_environment"] == "dev", (
        "caller-controlled X-Zendesk-Environment leaked into context"
    )


def test_caller_canonical_zendesk_environment_also_cannot_override():
    """Same as above but with the canonical header name instead of the
    X-prefixed form."""
    raw_headers = {
        "zendesk-environment": "prod",
        "authorization": "Bearer x",
    }
    _strip_caller_environment_headers(raw_headers)
    raw_headers["zendesk-environment"] = "dev"

    ctx = extract_request_context(raw_headers)
    assert ctx["zendesk_environment"] == "dev"
