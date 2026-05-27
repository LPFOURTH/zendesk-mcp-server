"""Tests for the Layer 2 audit log middleware (R2 / AUDIT-004).

Covers:
- Default behaviour: a StructuredLoggingMiddleware instance is built
- Killswitch: MCP_AUDIT_LOG=disabled → no middleware (None returned)
- Redaction policy: include_payloads=False, include_payload_length=True
- Scope: listens to tools/call only

Does NOT call the live FastMCP server — just verifies our wiring of
the framework-provided middleware. The framework's own tests cover the
emission mechanics.
"""

from __future__ import annotations

import pytest


def test_default_builds_structured_logging_middleware(monkeypatch):
    """No MCP_AUDIT_LOG env var → middleware is built (default-enabled)."""
    monkeypatch.delenv("MCP_AUDIT_LOG", raising=False)

    from src.server import _build_audit_middleware
    from fastmcp.server.middleware.logging import StructuredLoggingMiddleware

    mw = _build_audit_middleware()
    assert mw is not None
    assert isinstance(mw, StructuredLoggingMiddleware)


def test_killswitch_disables_middleware(monkeypatch):
    """MCP_AUDIT_LOG=disabled → middleware returns None, no logging happens.

    Operational use: if Log Analytics ingest cost spikes or a downstream
    consumer breaks, flipping this env var stops the audit stream without
    needing a code redeploy."""
    monkeypatch.setenv("MCP_AUDIT_LOG", "disabled")

    from src.server import _build_audit_middleware

    assert _build_audit_middleware() is None


def test_killswitch_case_insensitive(monkeypatch):
    monkeypatch.setenv("MCP_AUDIT_LOG", "DISABLED")
    from src.server import _build_audit_middleware
    assert _build_audit_middleware() is None

    monkeypatch.setenv("MCP_AUDIT_LOG", "Disabled")
    assert _build_audit_middleware() is None


def test_other_values_do_not_disable(monkeypatch):
    """Only the literal 'disabled' (case-insensitive) is the killswitch.

    Set to 'enabled' / 'true' / random → middleware still built. Defensive
    against typos and partial deploys."""
    from src.server import _build_audit_middleware

    for value in ["enabled", "true", "yes", "1", "on", ""]:
        monkeypatch.setenv("MCP_AUDIT_LOG", value)
        mw = _build_audit_middleware()
        assert mw is not None, f"value={value!r} unexpectedly disabled the middleware"


def test_middleware_does_not_include_payloads_by_default(monkeypatch):
    """Redaction policy: payload bodies (ticket comments, search text)
    must NOT appear in the audit log. Sizes and lengths are fine."""
    monkeypatch.delenv("MCP_AUDIT_LOG", raising=False)
    from src.server import _build_audit_middleware

    mw = _build_audit_middleware()
    assert mw.include_payloads is False, (
        "audit log must redact payload content (PII / ticket bodies risk)"
    )


def test_middleware_includes_payload_length(monkeypatch):
    """Per codex's brainstorm: log sizes/counts so we can detect anomalies
    (e.g. unusually large tool args) without seeing the content itself."""
    monkeypatch.delenv("MCP_AUDIT_LOG", raising=False)
    from src.server import _build_audit_middleware

    mw = _build_audit_middleware()
    assert mw.include_payload_length is True


def test_middleware_scoped_to_tools_call(monkeypatch):
    """The audit log focuses on tool invocations — the action that mutates
    Zendesk. tools/list and other discovery messages are noise; we log
    only tools/call."""
    monkeypatch.delenv("MCP_AUDIT_LOG", raising=False)
    from src.server import _build_audit_middleware

    mw = _build_audit_middleware()
    assert mw.methods == ["tools/call"], f"unexpected scoped methods: {mw.methods}"


def test_middleware_uses_dedicated_logger(monkeypatch):
    """The audit middleware should use a named logger so KQL queries can
    filter on it (rather than mixing with everything else on stderr).

    Side effect: the logger should not propagate to root to avoid double
    logging or capture by other handlers."""
    import logging

    monkeypatch.delenv("MCP_AUDIT_LOG", raising=False)
    from src.server import _build_audit_middleware

    mw = _build_audit_middleware()
    audit_logger = logging.getLogger("zendesk-mcp-audit")
    assert mw.logger is audit_logger
    assert audit_logger.propagate is False
    # Has at least one StreamHandler attached
    assert any(isinstance(h, logging.StreamHandler) for h in audit_logger.handlers)
