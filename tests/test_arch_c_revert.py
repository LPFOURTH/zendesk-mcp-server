"""Regression tests for the Architecture C revert path (v3.10.x).

Architecture C is `/mcp/dev` with `MCP_AUTH_MODE=zendesk`: per-user Zendesk
OAuth via `ZendeskOAuthProxy`. The Zendesk API caller IS the user, so we MUST
NOT inject `requester` or `comment.author_id` on top — Zendesk attributes
correctly natively, and double-injection can 422 if the user lacks
`set_author_on_create` permission.

Architecture F (default, MCP_AUTH_MODE=entra) is unchanged — service-account
calls require the attribution payload injection or the audit chain attributes
everything to the service account.

Tests pinned here:
  - create_ticket / update_ticket / create_it_ticket skip attribution under C
  - create_ticket / update_ticket / create_it_ticket STILL inject under F (regression)
  - _create_dev_server_zendesk_oauth overrides IT_FORM_CONFIG["dev"] to prod
    when MCP_DEV_ENVIRONMENT=PROD; leaves sandbox values for SANDBOX1/default.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _reset_src_modules():
    for m in [k for k in list(sys.modules) if k.startswith("src.")]:
        sys.modules.pop(m, None)


class AttributionGatedToArchFTests(unittest.TestCase):
    """create_ticket / update_ticket / create_it_ticket must skip the
    attribution helpers when MCP_AUTH_MODE=zendesk (Architecture C revert)."""

    def _run_create_ticket(self, auth_mode: str) -> dict:
        env = {
            "MCP_AUTH_MODE": auth_mode,
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
        }
        with patch.dict(os.environ, env, clear=True):
            _reset_src_modules()
            from src.tools import tickets  # noqa: WPS433

            mock_client = MagicMock()
            mock_client.create_ticket = AsyncMock(
                return_value={"ticket": {"id": 1, "subject": "x"}}
            )
            mock_client.get_agent_ticket_url = MagicMock(
                return_value="https://x/agent/tickets/1"
            )

            async def fake_resolve(email):
                return 7777

            def fake_auth_email():
                return "lukasz.pelcner@fourth.com"

            with patch.object(tickets, "zendesk_client", mock_client), \
                 patch.object(tickets, "_get_authenticated_user_email", fake_auth_email), \
                 patch.object(tickets, "resolve_zendesk_user_id", fake_resolve):
                asyncio.run(tickets.create_ticket(subject="s", comment="c"))

            return mock_client.create_ticket.call_args.args[0]

    def test_create_ticket_skips_attribution_under_arch_c(self):
        """Under MCP_AUTH_MODE=zendesk: no requester injection, no
        comment.author_id. The Zendesk OAuth bearer carries the identity."""
        sent = self._run_create_ticket(auth_mode="zendesk")
        self.assertNotIn("requester", sent)
        self.assertNotIn("author_id", sent.get("comment", {}))

    def test_create_ticket_injects_attribution_under_arch_f(self):
        """Regression: MCP_AUTH_MODE=entra (default) must still inject
        requester and comment.author_id — Arch F semantics unchanged."""
        sent = self._run_create_ticket(auth_mode="entra")
        self.assertEqual(sent.get("requester"), {"email": "lukasz.pelcner@fourth.com"})
        self.assertEqual(sent["comment"].get("author_id"), 7777)

    def test_create_ticket_default_mode_is_entra(self):
        """When MCP_AUTH_MODE is unset, default to Arch F (entra) behavior —
        guards against accidentally regressing prod with a missing env var."""
        env = {
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
        }
        with patch.dict(os.environ, env, clear=True):
            _reset_src_modules()
            from src.tools import tickets  # noqa: WPS433

            mock_client = MagicMock()
            mock_client.create_ticket = AsyncMock(
                return_value={"ticket": {"id": 1, "subject": "x"}}
            )
            mock_client.get_agent_ticket_url = MagicMock(
                return_value="https://x/agent/tickets/1"
            )

            with patch.object(tickets, "zendesk_client", mock_client), \
                 patch.object(tickets, "_get_authenticated_user_email",
                              lambda: "u@fourth.com"), \
                 patch.object(tickets, "resolve_zendesk_user_id",
                              AsyncMock(return_value=5555)):
                asyncio.run(tickets.create_ticket(subject="s", comment="c"))

        sent = mock_client.create_ticket.call_args.args[0]
        self.assertEqual(sent.get("requester"), {"email": "u@fourth.com"})

    def _run_update_ticket(self, auth_mode: str) -> dict:
        env = {
            "MCP_AUTH_MODE": auth_mode,
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
        }
        with patch.dict(os.environ, env, clear=True):
            _reset_src_modules()
            from src.tools import tickets  # noqa: WPS433

            mock_client = MagicMock()
            mock_client.update_ticket = AsyncMock(
                return_value={"ticket": {"id": 99, "subject": "x"}}
            )
            mock_client.get_agent_ticket_url = MagicMock(
                return_value="https://x/agent/tickets/99"
            )

            with patch.object(tickets, "zendesk_client", mock_client), \
                 patch.object(tickets, "_get_authenticated_user_email",
                              lambda: "u@fourth.com"), \
                 patch.object(tickets, "resolve_zendesk_user_id",
                              AsyncMock(return_value=5555)):
                asyncio.run(
                    tickets.update_ticket(ticket_id=99, comment="follow-up")
                )

            return mock_client.update_ticket.call_args.args[1]

    def test_update_ticket_skips_attribution_under_arch_c(self):
        sent = self._run_update_ticket(auth_mode="zendesk")
        self.assertNotIn("author_id", sent.get("comment", {}))

    def test_update_ticket_injects_attribution_under_arch_f(self):
        sent = self._run_update_ticket(auth_mode="entra")
        self.assertEqual(sent["comment"].get("author_id"), 5555)


class CreateItTicketAttributionTests(unittest.TestCase):
    """Direct create_it_ticket payload tests (per codex code-review NIT).
    Pins that the gate applies to the headline write tool too."""

    def _run_create_it_ticket(self, auth_mode: str | None) -> dict:
        env = {
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
        }
        if auth_mode is not None:
            env["MCP_AUTH_MODE"] = auth_mode
        with patch.dict(os.environ, env, clear=True):
            _reset_src_modules()
            from src.tools import tickets  # noqa: WPS433
            from src.constants import IT_FORM_CONFIG  # noqa: WPS433
            # Ensure dev IT form has a brand_id so the test exercises the
            # standard payload-build path.
            self.assertIsNotNone(IT_FORM_CONFIG["dev"]["fields"])

            mock_client = MagicMock()
            mock_client.create_ticket = AsyncMock(
                return_value={"ticket": {"id": 42, "subject": "x"}}
            )
            mock_client.get_agent_ticket_url = MagicMock(
                return_value="https://x/agent/tickets/42"
            )

            with patch.object(tickets, "zendesk_client", mock_client), \
                 patch.object(tickets, "_get_authenticated_user_email",
                              lambda: "user@fourth.com"), \
                 patch.object(tickets, "resolve_zendesk_user_id",
                              AsyncMock(return_value=9999)):
                asyncio.run(
                    tickets.create_it_ticket(
                        subject="Test",
                        description="body",
                        classification="service_request",
                        sr_category="eit_general",
                    )
                )

            return mock_client.create_ticket.call_args.args[0]

    def test_create_it_ticket_skips_attribution_under_arch_c(self):
        sent = self._run_create_it_ticket(auth_mode="zendesk")
        self.assertNotIn("requester", sent)
        self.assertNotIn("author_id", sent.get("comment", {}))

    def test_create_it_ticket_injects_attribution_under_arch_f(self):
        sent = self._run_create_it_ticket(auth_mode="entra")
        self.assertEqual(sent.get("requester"), {"email": "user@fourth.com"})
        self.assertEqual(sent["comment"].get("author_id"), 9999)

    def test_create_it_ticket_default_mode_is_entra(self):
        """Missing MCP_AUTH_MODE → arch-F semantics (no silent drop)."""
        sent = self._run_create_it_ticket(auth_mode=None)
        self.assertEqual(sent.get("requester"), {"email": "user@fourth.com"})


class CreateArticleAttributionGatedTests(unittest.TestCase):
    """help_center.create_article must skip author_id injection under
    Architecture C (codex BLOCK from 2026-05-14 code review)."""

    def _run_create_article(self, auth_mode: str) -> dict:
        env = {
            "MCP_AUTH_MODE": auth_mode,
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
        }
        with patch.dict(os.environ, env, clear=True):
            _reset_src_modules()
            from src.tools import help_center  # noqa: WPS433

            mock_client = MagicMock()
            mock_client.create_article = AsyncMock(
                return_value={"article": {"id": 1, "title": "x"}}
            )
            mock_client.get_help_center_article_url = MagicMock(
                return_value="https://x/hc/articles/1"
            )

            with patch.object(help_center, "zendesk_client", mock_client), \
                 patch.object(help_center, "get_current_entra_email",
                              lambda: "author@fourth.com"), \
                 patch.object(help_center, "resolve_zendesk_user_id",
                              AsyncMock(return_value=4242)):
                asyncio.run(
                    help_center.create_article(
                        title="t", body="b", section_id=123
                    )
                )

            return mock_client.create_article.call_args.args[0]

    def test_create_article_skips_author_under_arch_c(self):
        sent = self._run_create_article(auth_mode="zendesk")
        self.assertNotIn("author_id", sent)

    def test_create_article_injects_author_under_arch_f(self):
        sent = self._run_create_article(auth_mode="entra")
        self.assertEqual(sent.get("author_id"), 4242)


class CreateReleaseNoteAttributionGatedTests(unittest.TestCase):
    """release_notes.create_release_note must skip the hardcoded
    env_config["author_id"] under Architecture C — under per-user OAuth,
    setting a different author_id can 422 if the user lacks permission
    (codex BLOCK from 2026-05-14 code review)."""

    SAMPLE_MD = (
        "### Functionality 1 Name\n"
        "Test Feature\n\n"
        "### Functionality 1 Description\n"
        "Description body\n"
    )

    def _run_create_release_note(self, auth_mode: str) -> dict:
        env = {
            "MCP_AUTH_MODE": auth_mode,
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
        }
        with patch.dict(os.environ, env, clear=True):
            _reset_src_modules()
            from src.tools import release_notes  # noqa: WPS433

            mock_client = MagicMock()
            mock_client.create_article = AsyncMock(
                return_value={"article": {"id": 9, "title": "rn",
                                         "html_url": "https://x/hc/9"}}
            )

            with patch.object(release_notes, "zendesk_client", mock_client):
                asyncio.run(
                    release_notes.create_release_note(
                        markdown_content=self.SAMPLE_MD,
                        use_us_template=False,
                    )
                )

            return mock_client.create_article.call_args.args[0]

    def test_release_note_skips_hardcoded_author_under_arch_c(self):
        sent = self._run_create_release_note(auth_mode="zendesk")
        self.assertNotIn("author_id", sent)

    def test_release_note_keeps_hardcoded_author_under_arch_f(self):
        """Arch F behavior preserved: bot author_id is set per env config."""
        sent = self._run_create_release_note(auth_mode="entra")
        self.assertIn("author_id", sent)
        self.assertIsInstance(sent["author_id"], int)


class ArchCProdItFormOverrideTests(unittest.TestCase):
    """_create_dev_server_zendesk_oauth must override IT_FORM_CONFIG["dev"]
    to the prod values when MCP_DEV_ENVIRONMENT=PROD — otherwise
    create_it_ticket on /mcp/dev (now pointing at prod Zendesk) would send
    sandbox brand/form/field IDs and get 422 "Brand is invalid"."""

    def _base_env(self, extras: dict) -> dict:
        env = {
            "MCP_AUTH_MODE": "zendesk",
            "MCP_PUBLIC_URL": "https://example.com",
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
        }
        env.update(extras)
        return env

    def test_arch_c_prod_overrides_it_form_config(self):
        """MCP_DEV_ENVIRONMENT=PROD → IT_FORM_CONFIG["dev"] mirrors prod."""
        env = self._base_env({
            "MCP_DEV_ENVIRONMENT": "PROD",
            "ZENDESK_PROD_SUBDOMAIN": "hotschedules",
            "ZENDESK_PROD_OAUTH_CLIENT_ID": "cid",
            "ZENDESK_PROD_OAUTH_SECRET": "secret",
        })
        with patch.dict(os.environ, env, clear=True):
            _reset_src_modules()
            from src.server import create_dev_server  # noqa: WPS433
            from src.constants import IT_FORM_CONFIG  # noqa: WPS433
            create_dev_server()
            self.assertEqual(IT_FORM_CONFIG["dev"]["brand_id"], 360004744852)
            self.assertEqual(IT_FORM_CONFIG["dev"]["form_id"], 45108529620365)
            self.assertEqual(
                IT_FORM_CONFIG["dev"]["fields"], IT_FORM_CONFIG["prod"]["fields"]
            )

    def test_arch_c_sandbox_keeps_sandbox_it_form_config(self):
        """MCP_DEV_ENVIRONMENT=SANDBOX1 (default) → IT_FORM_CONFIG["dev"]
        stays at the sandbox values defined in src/constants.py."""
        env = self._base_env({
            "MCP_DEV_ENVIRONMENT": "SANDBOX1",
            "ZENDESK_SANDBOX1_SUBDOMAIN": "hotschedules1760632913",
            "ZENDESK_SANDBOX1_OAUTH_CLIENT_ID": "cid",
            "ZENDESK_SANDBOX1_OAUTH_SECRET": "secret",
        })
        with patch.dict(os.environ, env, clear=True):
            _reset_src_modules()
            # Snapshot the original sandbox values BEFORE create_dev_server runs.
            from src.constants import IT_FORM_CONFIG  # noqa: WPS433
            sandbox_form_id = IT_FORM_CONFIG["dev"]["form_id"]
            sandbox_brand_id = IT_FORM_CONFIG["dev"]["brand_id"]

            from src.server import create_dev_server  # noqa: WPS433
            create_dev_server()
            # Sandbox values preserved — no override fired.
            self.assertEqual(IT_FORM_CONFIG["dev"]["form_id"], sandbox_form_id)
            self.assertEqual(IT_FORM_CONFIG["dev"]["brand_id"], sandbox_brand_id)
            # Crucially, NOT equal to prod (the regression we're guarding against).
            self.assertNotEqual(
                IT_FORM_CONFIG["dev"]["form_id"], IT_FORM_CONFIG["prod"]["form_id"]
            )


class ArchCJwtSigningKeyTests(unittest.TestCase):
    """T1: _create_dev_server_zendesk_oauth must pass None (not empty string)
    for jwt_signing_key when MCP_JWT_SIGNING_KEY is unset, matching the
    Entra branch. Empty string was rejected by some FastMCP versions."""

    def test_unset_jwt_signing_key_does_not_crash_boot(self):
        env = {
            "MCP_AUTH_MODE": "zendesk",
            "MCP_DEV_ENVIRONMENT": "PROD",
            "MCP_PUBLIC_URL": "https://example.com",
            "ZENDESK_PROD_SUBDOMAIN": "hotschedules",
            "ZENDESK_PROD_OAUTH_CLIENT_ID": "cid",
            "ZENDESK_PROD_OAUTH_SECRET": "secret",
            "ZENDESK_SUBDOMAIN": "hotschedules",
            "ZENDESK_EMAIL": "svc@fourth.com",
            "ZENDESK_API_TOKEN": "svc-token",
            # MCP_JWT_SIGNING_KEY intentionally absent
        }
        with patch.dict(os.environ, env, clear=True):
            _reset_src_modules()
            from src.server import create_dev_server  # noqa: WPS433
            # Should not raise.
            server = create_dev_server()
            self.assertIsNotNone(server)


if __name__ == "__main__":
    unittest.main(verbosity=2)
