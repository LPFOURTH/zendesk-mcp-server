"""Tests for src/zendesk_client.py error sanitization.

AUDIT-006: error messages returned to the MCP caller must not leak
Zendesk-internal information (field IDs, custom-field metadata, allowed
values, partial record data).
"""

from __future__ import annotations

import pytest

from src.zendesk_client import _sanitized_zendesk_error


def test_sanitized_includes_status_code():
    """Status code is preserved — callers can still distinguish 401/403/404 etc."""
    assert "422" in _sanitized_zendesk_error(422)
    assert "401" in _sanitized_zendesk_error(401)
    assert "500" in _sanitized_zendesk_error(500)


def test_sanitized_uses_generic_mapping_for_common_codes():
    """Common HTTP statuses map to plain-English categories with no Zendesk specifics."""
    assert "validation failed" in _sanitized_zendesk_error(422)
    assert "authentication failed" in _sanitized_zendesk_error(401)
    assert "permission denied" in _sanitized_zendesk_error(403)
    assert "resource not found" in _sanitized_zendesk_error(404)
    assert "rate limited" in _sanitized_zendesk_error(429)


def test_sanitized_falls_back_to_generic_for_unknown_codes():
    """Unmapped status codes still return a non-empty, non-leaky message."""
    msg = _sanitized_zendesk_error(418)
    assert "418" in msg
    assert "request failed" in msg


def test_sanitized_does_not_include_field_ids_or_record_data():
    """Structural guarantee: only status code is input → no Zendesk-internal
    data can leak. Spot-check the message against common leak markers."""
    import re

    msg = _sanitized_zendesk_error(422)
    # No Zendesk-specific record types in the user-facing message
    assert "field_id" not in msg.lower()
    assert "custom_field" not in msg.lower()
    assert "brand_id" not in msg.lower()
    assert "ticket_id" not in msg.lower()
    # No email addresses
    assert "@" not in msg
    # The only digits should be the status code itself
    digits = re.findall(r"\d+", msg)
    assert digits == ["422"], f"unexpected digits leaked into message: {digits}"


def test_sanitized_directs_caller_to_server_logs():
    """The message tells the caller where to find the full details (server logs)
    instead of returning them — auditable trail without exposing schema."""
    msg = _sanitized_zendesk_error(500)
    assert "server logs" in msg.lower()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 429, 500, 502, 503, 504])
def test_sanitized_handles_all_documented_status_codes(status):
    """No KeyError, no empty message, status round-trips."""
    msg = _sanitized_zendesk_error(status)
    assert msg
    assert str(status) in msg
