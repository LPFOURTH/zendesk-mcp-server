"""Tests for src/url_security.py — AUDIT-001 SSRF deny-list.

Covers every blocked network class, the literal-IP fast path, the DNS
resolution path, malformed inputs, and the operational killswitch.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from src.url_security import (
    OutboundURLNotAllowed,
    _check_ip_blocked,
    _validate_url_sync,
    validate_outbound_url,
)


# ---- literal-IP path: no DNS, immediate decision ----


@pytest.mark.parametrize("url,reason_fragment", [
    # IMDS — the headline attack URL
    ("https://169.254.169.254/metadata/identity/oauth2/token", "169.254"),
    # IPv4 loopback
    ("https://127.0.0.1/admin", "127.0.0.0/8"),
    # RFC1918 private ranges
    ("https://10.0.0.1/secrets", "10.0.0.0/8"),
    ("https://172.16.5.4/", "172.16.0.0/12"),
    ("https://192.168.1.1/", "192.168.0.0/16"),
    # IPv6 loopback
    ("https://[::1]/", "::1/128"),
    # IPv6 ULA
    ("https://[fc00::1]/", "fc00::/7"),
    # IPv6 link-local
    ("https://[fe80::1]/", "fe80::/10"),
])
def test_blocked_literal_ips_rejected(url, reason_fragment):
    with pytest.raises(OutboundURLNotAllowed) as exc_info:
        _validate_url_sync(url)
    assert reason_fragment in str(exc_info.value)


@pytest.mark.parametrize("url", [
    # Public IP literals that should be allowed (well-known DNS resolvers)
    "https://8.8.8.8/",
    "https://1.1.1.1/",
    # Public IPv6 (Google)
    "https://[2001:4860:4860::8888]/",
])
def test_public_literal_ips_allowed(url):
    result = _validate_url_sync(url)
    assert result == url


# ---- DNS resolution path: hostname → IP check ----


def _mock_getaddrinfo(ipv4_addresses: list[str], ipv6_addresses: list[str] | None = None):
    """Build a mock socket.getaddrinfo return for testing."""
    entries = []
    for addr in ipv4_addresses:
        entries.append((socket.AF_INET, socket.SOCK_STREAM, 0, "", (addr, 443)))
    if ipv6_addresses:
        for addr in ipv6_addresses:
            entries.append((socket.AF_INET6, socket.SOCK_STREAM, 0, "", (addr, 443, 0, 0)))
    return entries


def test_hostname_resolving_to_imds_is_blocked():
    """A CNAME / A record pointing at IMDS must be caught even if hostname looks innocent."""
    with patch(
        "src.url_security.socket.getaddrinfo",
        return_value=_mock_getaddrinfo(["169.254.169.254"]),
    ):
        with pytest.raises(OutboundURLNotAllowed) as exc_info:
            _validate_url_sync("https://innocent-looking.example.com/")
        assert "169.254" in str(exc_info.value)


def test_hostname_resolving_to_public_ip_is_allowed():
    with patch(
        "src.url_security.socket.getaddrinfo",
        return_value=_mock_getaddrinfo(["140.82.121.4"]),  # github.com
    ):
        result = _validate_url_sync("https://github.com/")
        assert result == "https://github.com/"


def test_hostname_with_mixed_v4_v6_blocks_if_any_is_private():
    """If a hostname resolves to BOTH a public v4 and a private v6, refuse."""
    with patch(
        "src.url_security.socket.getaddrinfo",
        return_value=_mock_getaddrinfo(
            ipv4_addresses=["140.82.121.4"],
            ipv6_addresses=["fc00::1"],
        ),
    ):
        with pytest.raises(OutboundURLNotAllowed) as exc_info:
            _validate_url_sync("https://dual-stack.example.com/")
        assert "fc00::/7" in str(exc_info.value)


def test_dns_failure_is_rejected():
    """If DNS fails, we don't fetch — fail closed."""
    with patch(
        "src.url_security.socket.getaddrinfo",
        side_effect=socket.gaierror("nodename not known"),
    ):
        with pytest.raises(OutboundURLNotAllowed) as exc_info:
            _validate_url_sync("https://nonexistent.invalid/")
        assert "DNS resolution failed" in str(exc_info.value)


# ---- malformed / unsupported inputs ----


def test_http_scheme_rejected():
    """Only https:// outbound. http:// might be MITM-able even to a public host."""
    with pytest.raises(OutboundURLNotAllowed) as exc_info:
        _validate_url_sync("http://example.com/")
    assert "scheme" in str(exc_info.value)


def test_file_scheme_rejected():
    with pytest.raises(OutboundURLNotAllowed):
        _validate_url_sync("file:///etc/passwd")


def test_url_without_host_rejected():
    with pytest.raises(OutboundURLNotAllowed):
        _validate_url_sync("https:///path-only")


# ---- killswitch ----


def test_permissive_killswitch_bypasses_check(monkeypatch):
    """MCP_ATTACHMENT_URL_VALIDATION=permissive disables the deny-list.

    Operational escape hatch — if a legitimate URL is being false-positive
    blocked, flip this env var to unblock until the deny-list is tuned."""
    monkeypatch.setenv("MCP_ATTACHMENT_URL_VALIDATION", "permissive")
    # Even an IMDS URL passes when permissive
    result = _validate_url_sync("https://169.254.169.254/metadata")
    assert "169.254" in result


def test_permissive_killswitch_case_insensitive(monkeypatch):
    """Accept "permissive" / "PERMISSIVE" / "Permissive" — common env-var gotcha."""
    monkeypatch.setenv("MCP_ATTACHMENT_URL_VALIDATION", "PERMISSIVE")
    result = _validate_url_sync("https://169.254.169.254/")
    assert result.startswith("https://")


def test_killswitch_default_does_not_bypass(monkeypatch):
    """Unset / empty / other-value env var must NOT bypass — only the literal."""
    monkeypatch.delenv("MCP_ATTACHMENT_URL_VALIDATION", raising=False)
    with pytest.raises(OutboundURLNotAllowed):
        _validate_url_sync("https://169.254.169.254/")
    monkeypatch.setenv("MCP_ATTACHMENT_URL_VALIDATION", "strict")
    with pytest.raises(OutboundURLNotAllowed):
        _validate_url_sync("https://169.254.169.254/")


# ---- async wrapper ----


@pytest.mark.asyncio
async def test_async_wrapper_returns_url_on_success():
    """validate_outbound_url is the public async entry point."""
    with patch(
        "src.url_security.socket.getaddrinfo",
        return_value=_mock_getaddrinfo(["8.8.8.8"]),
    ):
        result = await validate_outbound_url("https://dns.google/")
        assert result == "https://dns.google/"


@pytest.mark.asyncio
async def test_async_wrapper_raises_on_blocked():
    with pytest.raises(OutboundURLNotAllowed):
        await validate_outbound_url("https://169.254.169.254/")


# ---- internal helper: _check_ip_blocked ----


def test_check_ip_blocked_helper_directly():
    import ipaddress as _ip
    assert _check_ip_blocked(_ip.IPv4Address("169.254.169.254")) is not None
    assert _check_ip_blocked(_ip.IPv4Address("8.8.8.8")) is None
    assert _check_ip_blocked(_ip.IPv6Address("::1")) is not None
    assert _check_ip_blocked(_ip.IPv6Address("2001:4860:4860::8888")) is None
