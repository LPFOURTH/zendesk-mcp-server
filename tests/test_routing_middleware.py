"""Tests for src/main.py routing-middleware helpers.

Focused on AUDIT-009: caller-controlled environment-routing headers must
not be able to override the path-derived env_name that the middleware
injects.
"""

from __future__ import annotations

from src.main import (
    _DEFAULT_CORS_ALLOWLIST,
    _origin_allowed,
    _parse_cors_origins,
    _strip_caller_environment_headers,
)
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


# ---- AUDIT-005: CORS allowlist ----


def test_parse_cors_origins_uses_safe_default_when_unset():
    """No MCP_CORS_ORIGINS → ship the safe default allowlist (Claude,
    Copilot Studio, Power Platform, localhost). Not wildcard."""
    result = _parse_cors_origins("")
    assert result == _DEFAULT_CORS_ALLOWLIST
    assert "*" not in result


def test_parse_cors_origins_parses_comma_separated():
    result = _parse_cors_origins("https://a.example,https://b.example")
    assert result == ["https://a.example", "https://b.example"]


def test_parse_cors_origins_preserves_wildcard_killswitch():
    """MCP_CORS_ORIGINS=* must be honored as a killswitch."""
    assert _parse_cors_origins("*") == ["*"]


def test_origin_allowed_exact_match():
    assert _origin_allowed("https://claude.ai", ["https://claude.ai"])
    assert not _origin_allowed("https://evil.example", ["https://claude.ai"])


def test_origin_allowed_wildcard_subdomain():
    """`https://*.copilotstudio.microsoft.com` must match subdomains."""
    allow = ["https://*.copilotstudio.microsoft.com"]
    assert _origin_allowed("https://foo.copilotstudio.microsoft.com", allow)
    assert _origin_allowed("https://bar-baz.copilotstudio.microsoft.com", allow)
    assert not _origin_allowed("https://copilotstudio.microsoft.com", allow)
    assert not _origin_allowed("https://evil.example.com", allow)


def test_origin_allowed_wildcard_port_localhost():
    """`http://localhost:*` must match any port on localhost."""
    allow = ["http://localhost:*"]
    assert _origin_allowed("http://localhost:3000", allow)
    assert _origin_allowed("http://localhost:8080", allow)
    assert not _origin_allowed("http://evil:3000", allow)


def test_origin_allowed_wildcard_killswitch():
    """Literal `*` in allowlist permits any origin (killswitch behaviour)."""
    assert _origin_allowed("https://any.example.com", ["*"])
    assert _origin_allowed("https://attacker.evil", ["*"])


def test_origin_allowed_rejects_empty_origin():
    """No Origin header → not allowed (no CORS headers emitted, browser blocks
    cross-origin; same-origin and non-browser callers unaffected)."""
    assert not _origin_allowed("", ["https://claude.ai"])
    assert not _origin_allowed("", _DEFAULT_CORS_ALLOWLIST)


def test_default_allowlist_does_not_contain_wildcard():
    """Sanity: a typo-free default allowlist never silently accepts `*`."""
    assert "*" not in _DEFAULT_CORS_ALLOWLIST
    for entry in _DEFAULT_CORS_ALLOWLIST:
        assert entry.startswith(("http://", "https://"))
