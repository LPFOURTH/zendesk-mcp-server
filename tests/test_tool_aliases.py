"""Compat-shim regression tests: legacy `id` and `type` kwargs still work.

Saved Copilot Studio actions and Claude Code prompt-cached tool calls may pass
`id=...` (legacy) or `type=...` (legacy) to ticket tools. After the pylint
rename to `ticket_id` and `ticket_type`, those clients would break without
this shim. Each test patches the module-level `zendesk_client` and asserts
the legacy kwarg routes to the same call as the canonical kwarg.

Stdlib-only. Run: `python -m unittest tests.test_tool_aliases -v`
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.tools import tickets  # noqa: E402


def _patched_client() -> MagicMock:
    """Return a MagicMock with the methods/attributes get_ticket etc. expect."""
    mock = MagicMock()
    mock.get_ticket = AsyncMock(
        return_value={"ticket": {"id": 42, "subject": "x", "description": "d"}}
    )
    mock.create_ticket = AsyncMock(return_value={"ticket": {"id": 99, "subject": "y"}})
    mock.update_ticket = AsyncMock(return_value={"ticket": {"id": 42, "subject": "z"}})
    mock.get_agent_ticket_url = MagicMock(return_value="https://x.zendesk.com/agent/tickets/42")
    return mock


def run(coro):
    return asyncio.run(coro)


class GetTicketAliasTests(unittest.TestCase):
    def test_canonical_ticket_id_kwarg(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            run(tickets.get_ticket(ticket_id=42))
        mock.get_ticket.assert_awaited_once_with(42)

    def test_legacy_id_kwarg(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            run(tickets.get_ticket(id=42))
        mock.get_ticket.assert_awaited_once_with(42)

    def test_missing_raises_valueerror(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            with self.assertRaises(ValueError):
                run(tickets.get_ticket())
        mock.get_ticket.assert_not_awaited()

    def test_canonical_wins_when_both_passed(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            run(tickets.get_ticket(ticket_id=42, id=99))
        mock.get_ticket.assert_awaited_once_with(42)


class UpdateTicketAliasTests(unittest.TestCase):
    def test_canonical_ticket_id_kwarg(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            run(tickets.update_ticket(ticket_id=42, subject="z"))
        mock.update_ticket.assert_awaited_once()
        args, _ = mock.update_ticket.call_args
        self.assertEqual(args[0], 42)

    def test_legacy_id_kwarg(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            run(tickets.update_ticket(id=42, subject="z"))
        mock.update_ticket.assert_awaited_once()
        args, _ = mock.update_ticket.call_args
        self.assertEqual(args[0], 42)

    def test_missing_raises_valueerror(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            with self.assertRaises(ValueError):
                run(tickets.update_ticket(subject="z"))

    def test_legacy_type_kwarg_routes_to_ticket_type(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            run(tickets.update_ticket(ticket_id=42, type="incident"))
        mock.update_ticket.assert_awaited_once()
        _, kwargs = mock.update_ticket.call_args
        # update_ticket passes a data dict — extract from positional[1]
        args, _ = mock.update_ticket.call_args
        data = args[1]
        self.assertEqual(data.get("type"), "incident")

    def test_canonical_ticket_type_kwarg(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            run(tickets.update_ticket(ticket_id=42, ticket_type="question"))
        args, _ = mock.update_ticket.call_args
        self.assertEqual(args[1].get("type"), "question")


class CreateTicketAliasTests(unittest.TestCase):
    def test_legacy_type_kwarg(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            run(tickets.create_ticket(subject="s", comment="c", type="problem"))
        args, _ = mock.create_ticket.call_args
        self.assertEqual(args[0].get("type"), "problem")

    def test_canonical_ticket_type_kwarg(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            run(tickets.create_ticket(subject="s", comment="c", ticket_type="task"))
        args, _ = mock.create_ticket.call_args
        self.assertEqual(args[0].get("type"), "task")

    def test_canonical_wins_for_type(self):
        mock = _patched_client()
        with patch.object(tickets, "zendesk_client", mock):
            run(
                tickets.create_ticket(
                    subject="s", comment="c", ticket_type="task", type="problem"
                )
            )
        args, _ = mock.create_ticket.call_args
        # Canonical ticket_type wins
        self.assertEqual(args[0].get("type"), "task")


if __name__ == "__main__":
    unittest.main(verbosity=2)
