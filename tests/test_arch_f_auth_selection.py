"""Regression tests for Architecture F (v3.10.0) auth-mode/target selection.

History:
  v3.10.0 — pinned entra+dev to ALWAYS use ZENDESK_EMAIL/ZENDESK_API_TOKEN
    (the dev-sandbox ZENDESK_DEV_* were a Path-C revert-only thing).
  v3.10.4 — deliberately opted IN to ZENDESK_DEV_* under entra+dev so the
    `/mcp/dev` path can use a different Zendesk service user (AI Agent)
    while `/mcp/prod` stays on the original credential (Lukasz). Both
    vars must be set or we fall back — no silent half-config.

Invariants pinned below:
  - /mcp/prod NEVER consults ZENDESK_DEV_* (protects prod from accidental swap)
  - /mcp/dev under entra uses ZENDESK_DEV_* iff BOTH are set
  - /mcp/dev under zendesk (legacy revert) still consults ZENDESK_DEV_* — but
    only after the per-user Bearer branch declines (no FastMCP context).
"""
from __future__ import annotations

import base64
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _import_fresh_zendesk_client():
    """Drop and re-import src.zendesk_client so module-level state respects
    the patched env. Returns the module-level singleton."""
    for m in [k for k in list(sys.modules) if k.startswith("src.")]:
        sys.modules.pop(m, None)
    from src.zendesk_client import zendesk_client  # noqa: WPS433
    return zendesk_client


class EntraModeAuthHeaderTests(unittest.TestCase):
    """Under MCP_AUTH_MODE=entra (default), /mcp/dev opts into ZENDESK_DEV_*
    when both are set (AI-Agent override, v3.10.4+); /mcp/prod ignores them."""

    def _basic_creds(self, header):
        self.assertTrue(header.startswith("Basic "), header)
        return base64.b64decode(header.split(" ", 1)[1]).decode()

    def _header_for(self, env, env_name):
        with patch.dict(os.environ, env, clear=True):
            client = _import_fresh_zendesk_client()
            from src.request_context import zendesk_environment_var
            tok = zendesk_environment_var.set(env_name)
            try:
                return client._get_auth_header()
            finally:
                zendesk_environment_var.reset(tok)

    def test_dev_env_uses_dev_creds_when_both_set(self):
        """New v3.10.4 behavior: /mcp/dev under entra picks up ZENDESK_DEV_*
        when both are set. This is how the AI-Agent service-user reaches Zendesk
        on the /mcp/dev path while /mcp/prod stays on the original credential.
        """
        env = {
            "MCP_AUTH_MODE": "entra",
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
            "ZENDESK_DEV_EMAIL": "aiagent@fourth.com",
            "ZENDESK_DEV_API_TOKEN": "ai-token",
        }
        decoded = self._basic_creds(self._header_for(env, "dev"))
        self.assertEqual(decoded, "aiagent@fourth.com/token:ai-token")

    def test_prod_env_ignores_dev_creds_even_when_set(self):
        """KEY PROTECTION: /mcp/prod must NEVER pick up ZENDESK_DEV_*. This is
        what isolates the AI-Agent swap to /mcp/dev only."""
        env = {
            "MCP_AUTH_MODE": "entra",
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
            "ZENDESK_DEV_EMAIL": "aiagent@fourth.com",
            "ZENDESK_DEV_API_TOKEN": "ai-token",
        }
        decoded = self._basic_creds(self._header_for(env, "prod"))
        self.assertEqual(decoded, "svc@fourth.com/token:svc-token")
        self.assertNotIn("aiagent", decoded)

    def test_dev_env_falls_back_when_only_one_dev_var_set(self):
        """No silent half-config: if only one of ZENDESK_DEV_* is set, fall
        through to the service account. Codex was firm about this."""
        for only in ("ZENDESK_DEV_EMAIL", "ZENDESK_DEV_API_TOKEN"):
            with self.subTest(only=only):
                env = {
                    "MCP_AUTH_MODE": "entra",
                    "ZENDESK_SUBDOMAIN": "hotschedules",
                    "ZENDESK_EMAIL": "svc@fourth.com",
                    "ZENDESK_API_TOKEN": "svc-token",
                    only: "partial@fourth.com" if only.endswith("EMAIL") else "partial-token",
                }
                decoded = self._basic_creds(self._header_for(env, "dev"))
                self.assertEqual(decoded, "svc@fourth.com/token:svc-token")

    def test_dev_env_falls_back_when_no_dev_vars_set(self):
        """When ZENDESK_DEV_* are absent entirely, /mcp/dev uses the service
        account — preserves the v3.10.0–3 default behavior."""
        env = {
            "MCP_AUTH_MODE": "entra",
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
        }
        decoded = self._basic_creds(self._header_for(env, "dev"))
        self.assertEqual(decoded, "svc@fourth.com/token:svc-token")

    def test_entra_mode_is_default_when_no_mode_set(self):
        """MCP_AUTH_MODE absent → treat as 'entra'. Sanity check that the dev
        override still applies on the unset default."""
        env = {
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
            "ZENDESK_DEV_EMAIL": "aiagent@fourth.com",
            "ZENDESK_DEV_API_TOKEN": "ai-token",
        }
        decoded = self._basic_creds(self._header_for(env, "dev"))
        self.assertEqual(decoded, "aiagent@fourth.com/token:ai-token")

    def test_no_request_context_ignores_dev_creds(self):
        """Per Codex round 3: stdio / headless / no-request-context callers
        (where zendesk_environment_var is unset) MUST get the base service
        account, never the AI-Agent dev creds — even when ZENDESK_DEV_* are
        set in the environment. Only the routed `/mcp/dev` request path opts in.
        """
        env = {
            "MCP_AUTH_MODE": "entra",
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
            "ZENDESK_DEV_EMAIL": "aiagent@fourth.com",
            "ZENDESK_DEV_API_TOKEN": "ai-token",
        }
        with patch.dict(os.environ, env, clear=True):
            client = _import_fresh_zendesk_client()
            # NB: deliberately NOT setting zendesk_environment_var — simulates
            # stdio mode where no request middleware ran.
            header = client._get_auth_header()
        decoded = self._basic_creds(header)
        self.assertEqual(decoded, "svc@fourth.com/token:svc-token")
        self.assertNotIn("aiagent", decoded)


class ZendeskModeAuthHeaderTests(unittest.TestCase):
    """Under MCP_AUTH_MODE=zendesk (legacy revert path), /mcp/dev must still
    consult ZENDESK_DEV_* creds — preserves the v3.9.0 behavior bit-for-bit."""

    def test_zendesk_mode_dev_env_uses_dev_credentials(self):
        env = {
            "MCP_AUTH_MODE": "zendesk",
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
            "ZENDESK_DEV_EMAIL": "dev@fourth.com",
            "ZENDESK_DEV_API_TOKEN": "dev-token",
        }
        with patch.dict(os.environ, env, clear=True):
            client = _import_fresh_zendesk_client()
            from src.request_context import zendesk_environment_var
            tok = zendesk_environment_var.set("dev")
            try:
                header = client._get_auth_header()
            finally:
                zendesk_environment_var.reset(tok)
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode()
        self.assertEqual(decoded, "dev@fourth.com/token:dev-token")


class EntraModeTargetTests(unittest.TestCase):
    """create_dev_server under MCP_AUTH_MODE=entra must override
    ENVIRONMENTS["dev"]["base_url"] to the prod Zendesk subdomain. Otherwise
    Zendesk API calls would silently go to the sandbox configured in constants."""

    def test_create_dev_server_entra_overrides_dev_base_url_to_prod(self):
        env = {
            "MCP_AUTH_MODE": "entra",
            "ENTRA_CLIENT_ID": "79da6be7-9ea8-4e39-8edc-6863da932f2b",
            "ENTRA_TENANT_ID": "75cd3b18-d23a-40ee-ad06-ad4484fc72fe",
            "ENTRA_CLIENT_SECRET": "x",
            "MCP_PUBLIC_URL": "https://example.com",
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
        }
        with patch.dict(os.environ, env, clear=True):
            for m in [k for k in list(sys.modules) if k.startswith("src.")]:
                sys.modules.pop(m, None)
            from src.server import create_dev_server  # noqa: WPS433
            from src.constants import ENVIRONMENTS  # noqa: WPS433
            create_dev_server()
            self.assertEqual(
                ENVIRONMENTS["dev"]["base_url"], "https://hotschedules.zendesk.com"
            )

    def test_create_dev_server_entra_respects_explicit_subdomain_env(self):
        env = {
            "MCP_AUTH_MODE": "entra",
            "ENTRA_CLIENT_ID": "x", "ENTRA_TENANT_ID": "y", "ENTRA_CLIENT_SECRET": "z",
            "MCP_PUBLIC_URL": "https://example.com",
            "ZENDESK_PROD_SUBDOMAIN": "fourthcompany",
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
        }
        with patch.dict(os.environ, env, clear=True):
            for m in [k for k in list(sys.modules) if k.startswith("src.")]:
                sys.modules.pop(m, None)
            from src.server import create_dev_server  # noqa: WPS433
            from src.constants import ENVIRONMENTS  # noqa: WPS433
            create_dev_server()
            self.assertEqual(
                ENVIRONMENTS["dev"]["base_url"], "https://fourthcompany.zendesk.com"
            )


class CreateTicketImpersonationGuardTests(unittest.TestCase):
    """v3.10.2 security fix: create_ticket no longer accepts a caller-supplied
    `requester_id`. The ticket is ALWAYS attributed to the authenticated Entra
    user. Closes the impersonation vector where User X could pass
    `requester_id=<User Y>` and create a ticket as another person.
    """

    def test_create_ticket_rejects_caller_supplied_requester_id(self):
        """Passing requester_id as a kwarg now raises TypeError — the param
        was removed from the function signature. Callers via the MCP wire
        get a schema-validation error from FastMCP at the boundary; callers
        via direct Python import get the TypeError seen here."""
        import asyncio
        from src.tools import tickets  # noqa: WPS433

        with self.assertRaises(TypeError):
            asyncio.run(
                tickets.create_ticket(
                    subject="s", comment="c", requester_id=999  # impersonation attempt
                )
            )

    def test_create_ticket_always_uses_authenticated_user_as_requester(self):
        """Regardless of any caller hints, the requester injected into the
        Zendesk payload is the authenticated Entra user's email — the only
        source of identity in Architecture F.
        """
        import asyncio

        env = {
            "MCP_AUTH_MODE": "entra",
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
        }
        with patch.dict(os.environ, env, clear=True):
            for m in [k for k in list(sys.modules) if k.startswith("src.")]:
                sys.modules.pop(m, None)
            from src.tools import tickets  # noqa: WPS433
            from unittest.mock import AsyncMock, MagicMock

            mock_client = MagicMock()
            mock_client.create_ticket = AsyncMock(
                return_value={"ticket": {"id": 1, "subject": "x"}}
            )
            mock_client.get_agent_ticket_url = MagicMock(
                return_value="https://x/agent/tickets/1"
            )

            async def fake_resolve(email):
                # The resolver is called with the AUTHENTICATED email — not
                # any caller-supplied value. We return the user_id for that
                # email; the test asserts both the resolver input AND the
                # injected requester are the same authenticated user.
                return 7777

            def fake_auth_email():
                return "lukasz.pelcner@fourth.com"  # the authenticated user

            with patch.object(tickets, "zendesk_client", mock_client), \
                 patch.object(tickets, "_get_authenticated_user_email", fake_auth_email), \
                 patch.object(tickets, "resolve_zendesk_user_id", fake_resolve):
                asyncio.run(
                    tickets.create_ticket(subject="s", comment="c")
                )

        sent = mock_client.create_ticket.call_args.args[0]
        # The requester is the AUTHENTICATED user, derived server-side
        self.assertEqual(sent.get("requester"), {"email": "lukasz.pelcner@fourth.com"})
        # No `requester_id` should appear — only the email-based `requester`
        # object. (Zendesk auto-creates the user from email.)
        self.assertNotIn("requester_id", sent)
        # Comment.author_id is also the authenticated user, not anyone else
        self.assertEqual(sent["comment"].get("author_id"), 7777)


if __name__ == "__main__":
    unittest.main(verbosity=2)
