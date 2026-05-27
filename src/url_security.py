"""Outbound URL safety checks (AUDIT-001 — SSRF deny-list).

Used by tools that fetch URLs supplied by callers (today: only
`create_it_ticket` attachment URLs). Validates that the resolved IP
address of the URL's host is NOT in any of the blocked networks below.

Blocked networks (variant B per the master findings doc):
- IPv4 link-local (169.254.0.0/16)  — Azure IMDS lives here
- IPv4 loopback (127.0.0.0/8)
- IPv4 RFC1918 private (10/8, 172.16/12, 192.168/16)
- IPv4 multicast / unspecified / limited broadcast
- IPv6 loopback (::1/128) and unspecified (::/128)
- IPv6 ULA (fc00::/7) and link-local (fe80::/10)
- IPv6 multicast (ff00::/8)
- IPv6 IPv4-mapped catches the same RFC1918 / loopback set when an
  attacker tries to bypass the v4 check via ::ffff:10.0.0.1.

Hostname → IP resolution uses `socket.getaddrinfo` so a CNAME pointing
at IMDS still gets caught. All A and AAAA records are checked — if
ANY resolved address is blocked, the URL is refused. Otherwise it's
allowed.

Killswitch (operational emergency): set env var
`MCP_ATTACHMENT_URL_VALIDATION=permissive` and restart the container
to skip the check. The 5-second `az containerapp update` triggers a
revision recreate; rolling back is the inverse. Use only if a
legitimate URL is being false-positive blocked.

See `docs/SECURITY-OVERVIEW.md` Layer 5 and
`docs/security-audits/2026-05-26-Q2.md` for context.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import sys
from urllib.parse import urlparse


class OutboundURLNotAllowed(ValueError):
    """Raised by validate_outbound_url when the target is blocked."""


# IPv4 networks we refuse to dial.
_BLOCKED_IPV4_NETWORKS: list[ipaddress.IPv4Network] = [
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("0.0.0.0/8"),
    ipaddress.IPv4Network("224.0.0.0/4"),
    ipaddress.IPv4Network("255.255.255.255/32"),
]

# IPv6 networks we refuse to dial.
_BLOCKED_IPV6_NETWORKS: list[ipaddress.IPv6Network] = [
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fc00::/7"),
    ipaddress.IPv6Network("fe80::/10"),
    ipaddress.IPv6Network("ff00::/8"),
    ipaddress.IPv6Network("::/128"),
    # IPv4-mapped IPv6 catches attempts to bypass IPv4 deny-list via ::ffff:X.
    ipaddress.IPv6Network("::ffff:0:0/96"),
]

# Default cap on bytes we'll read from a single outbound fetch.
DEFAULT_OUTBOUND_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB


def _check_ip_blocked(ip: ipaddress._BaseAddress) -> str | None:
    """Return a human-readable reason if the IP is blocked, else None."""
    if isinstance(ip, ipaddress.IPv4Address):
        for net in _BLOCKED_IPV4_NETWORKS:
            if ip in net:
                return f"IPv4 {ip} is in blocked range {net}"
    elif isinstance(ip, ipaddress.IPv6Address):
        for net in _BLOCKED_IPV6_NETWORKS:
            if ip in net:
                return f"IPv6 {ip} is in blocked range {net}"
    return None


def _validate_url_sync(url: str) -> str:
    """Synchronous core. Returns the URL on success, raises OutboundURLNotAllowed.

    Caller-facing async wrapper below (`validate_outbound_url`) offloads
    the DNS lookup to a thread so the event loop isn't blocked.
    """
    if os.environ.get("MCP_ATTACHMENT_URL_VALIDATION", "").lower() == "permissive":
        print(
            f"[url-security] WARNING: permissive mode — skipping SSRF check for {url}",
            file=sys.stderr,
        )
        return url

    try:
        parsed = urlparse(url)
    except (ValueError, AttributeError) as exc:
        raise OutboundURLNotAllowed(f"Malformed URL: {url!r}") from exc

    if parsed.scheme != "https":
        raise OutboundURLNotAllowed(
            f"Only https:// outbound URLs allowed; got scheme={parsed.scheme!r}"
        )
    if not parsed.hostname:
        raise OutboundURLNotAllowed(f"URL has no host: {url!r}")

    # If the host is already a literal IP, skip DNS and check directly.
    try:
        literal_ip = ipaddress.ip_address(parsed.hostname)
        reason = _check_ip_blocked(literal_ip)
        if reason:
            raise OutboundURLNotAllowed(f"Refused outbound to {url!r}: {reason}")
        return url
    except ValueError:
        pass  # not a literal IP — fall through to DNS resolution

    try:
        addrinfo = socket.getaddrinfo(
            parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise OutboundURLNotAllowed(
            f"DNS resolution failed for {parsed.hostname!r}: {exc}"
        ) from exc

    for family, _, _, _, sockaddr in addrinfo:
        if family == socket.AF_INET:
            ip = ipaddress.IPv4Address(sockaddr[0])
        elif family == socket.AF_INET6:
            ip = ipaddress.IPv6Address(sockaddr[0])
        else:
            continue
        reason = _check_ip_blocked(ip)
        if reason:
            raise OutboundURLNotAllowed(
                f"Refused outbound to {url!r}: hostname {parsed.hostname} → {reason}"
            )

    # Log every passed validation so we have a per-fetch audit trail.
    # (Format kept terse — full attribution lives in the Layer 2 audit log
    # middleware once that lands.)
    print(
        f"[url-security] outbound allowed: host={parsed.hostname} url={url[:80]}",
        file=sys.stderr,
    )
    return url


async def validate_outbound_url(url: str) -> str:
    """Async wrapper for _validate_url_sync — runs DNS lookup off-thread."""
    return await asyncio.to_thread(_validate_url_sync, url)
