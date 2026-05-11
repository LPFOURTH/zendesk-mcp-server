"""v3.10.3 gating regression test: create_it_ticket is the active IT-ticket
tool; create_ticket (the generic one) is deprecated and gated off.

v3.10.3 inversion (relative to earlier ADR-014):
  - create_it_ticket is now the primary tool — IT-form-aware, properly
    categorized, with Architecture F per-user attribution.
  - create_ticket (raw) is disabled. It was deprecated in favor of
    create_it_ticket so users can't bypass the IT form's categorization.
  - The fail-closed safelist flipped to {"create_ticket"} for the same
    reason: a broken config shouldn't accidentally resurface the
    deprecated tool.

Stdlib-only. Run: `python tests/test_tool_gating.py`
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


class CreateItTicketEnabled(unittest.TestCase):
    """create_it_ticket MUST register at server startup as of v3.10.3."""

    def test_file_flag_is_true(self):
        config = json.loads((REPO_ROOT / "tools.config.json").read_text())
        flag = config["tools"]["create_it_ticket"]["enabled"]
        self.assertTrue(
            flag,
            "create_it_ticket must be enabled in v3.10.3 — it replaces create_ticket.",
        )

    def test_with_ideas_preset_includes_create_it_ticket(self):
        config = json.loads((REPO_ROOT / "tools.config.json").read_text())
        with_ideas = config["presets"]["with_ideas"]["enable"]
        self.assertIn(
            "create_it_ticket", with_ideas,
            "with_ideas preset must include create_it_ticket (the IT-form tool).",
        )

    def test_create_server_registers_it(self):
        import asyncio
        env_clean = {k: v for k, v in os.environ.items() if k not in {"TOOLS_PRESET", "DISABLED_TOOLS"}}
        env_clean["TOOLS_CONFIG"] = str(REPO_ROOT / "tools.config.json")
        with patch.dict(os.environ, env_clean, clear=True):
            for mod in [m for m in list(sys.modules) if m.startswith("src.")]:
                sys.modules.pop(mod, None)
            from src.server import create_server  # noqa: WPS433
            mcp = create_server()
            tools = asyncio.run(mcp.list_tools())
            tool_names = {t.name for t in tools}
        self.assertIn(
            "create_it_ticket", tool_names,
            "create_it_ticket must be registered in v3.10.3.",
        )


class CreateTicketGated(unittest.TestCase):
    """create_ticket (the generic raw-ticket creator) is deprecated and must
    NOT register at server startup. Users should use create_it_ticket so the
    IT-form's categorization is enforced.
    """

    def test_file_flag_is_false(self):
        config = json.loads((REPO_ROOT / "tools.config.json").read_text())
        flag = config["tools"]["create_ticket"]["enabled"]
        self.assertFalse(
            flag,
            "create_ticket must be disabled in v3.10.3 — it bypasses IT-form categorization.",
        )

    def test_no_preset_force_enables_create_ticket(self):
        """No active preset should force-enable create_ticket. (The 'full' and
        'tickets_only' presets historically listed it — keep them updated to
        match the deprecation.)"""
        config = json.loads((REPO_ROOT / "tools.config.json").read_text())
        # with_ideas is the active preset in prod; it MUST NOT enable create_ticket.
        self.assertNotIn(
            "create_ticket",
            config["presets"]["with_ideas"]["enable"],
            "with_ideas preset must not pre-enable the deprecated create_ticket.",
        )

    def test_create_server_does_not_register_create_ticket(self):
        import asyncio
        env_clean = {k: v for k, v in os.environ.items() if k not in {"TOOLS_PRESET", "DISABLED_TOOLS"}}
        env_clean["TOOLS_CONFIG"] = str(REPO_ROOT / "tools.config.json")
        with patch.dict(os.environ, env_clean, clear=True):
            for mod in [m for m in list(sys.modules) if m.startswith("src.")]:
                sys.modules.pop(mod, None)
            from src.server import create_server  # noqa: WPS433
            mcp = create_server()
            tools = asyncio.run(mcp.list_tools())
            tool_names = {t.name for t in tools}
        self.assertNotIn(
            "create_ticket",
            tool_names,
            "create_ticket must not be registered in v3.10.3 (use create_it_ticket).",
        )
        # sanity: read tools still work
        self.assertIn("get_ticket", tool_names)
        self.assertIn("create_it_ticket", tool_names)

    def test_fallback_when_config_missing_keeps_create_ticket_disabled(self):
        """If tools.config.json is missing/corrupt, fail-closed must keep the
        deprecated create_ticket disabled. v3.10.3 moved the safelist
        membership from create_it_ticket to create_ticket.
        """
        import asyncio
        env_clean = {k: v for k, v in os.environ.items() if k not in {"TOOLS_PRESET", "DISABLED_TOOLS"}}
        env_clean["TOOLS_CONFIG"] = "/nonexistent/tools.config.json"
        with patch.dict(os.environ, env_clean, clear=True):
            for mod in [m for m in list(sys.modules) if m.startswith("src.")]:
                sys.modules.pop(mod, None)
            from src.server import create_server  # noqa: WPS433
            mcp = create_server()
            tools = asyncio.run(mcp.list_tools())
            tool_names = {t.name for t in tools}
        self.assertNotIn(
            "create_ticket",
            tool_names,
            "create_ticket must stay disabled on the config-missing fallback path.",
        )
        self.assertIn("get_ticket", tool_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
