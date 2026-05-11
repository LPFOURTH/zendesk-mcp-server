"""A3 regression test: create_it_ticket is gated off by default.

If someone flips `tools.config.json` → `create_it_ticket.enabled = true`
before Phase E1 verification (form IDs + tag maps in prod), this test
fails. The gate is intentional. See `.debate/tasks.md` Phase A3.

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


class CreateItTicketGated(unittest.TestCase):
    """create_it_ticket must NOT register at server startup until verified."""

    def test_file_flag_is_false(self):
        config = json.loads((REPO_ROOT / "tools.config.json").read_text())
        flag = config["tools"]["create_it_ticket"]["enabled"]
        self.assertFalse(
            flag,
            "create_it_ticket must stay disabled until Phase A4-A6 verifies prod form IDs.",
        )

    def test_no_preset_force_enables_it(self):
        """Even if TOOLS_PRESET is set, no preset should pre-enable create_it_ticket."""
        config = json.loads((REPO_ROOT / "tools.config.json").read_text())
        for preset_name, preset in config.get("presets", {}).items():
            self.assertNotIn(
                "create_it_ticket",
                preset.get("enable", []),
                f"Preset '{preset_name}' must not enable create_it_ticket while gated.",
            )

    def test_create_server_does_not_register_it(self):
        """With default env (no preset, no DISABLED_TOOLS override) create_it_ticket must be skipped."""
        env_clean = {k: v for k, v in os.environ.items() if k not in {"TOOLS_PRESET", "DISABLED_TOOLS"}}
        # Force config path to repo root regardless of cwd
        env_clean["TOOLS_CONFIG"] = str(REPO_ROOT / "tools.config.json")
        with patch.dict(os.environ, env_clean, clear=True):
            # Re-import server module fresh so module-level state respects patched env
            for mod in [m for m in list(sys.modules) if m.startswith("src.")]:
                sys.modules.pop(mod, None)
            from src.server import create_server  # noqa: WPS433
            mcp = create_server()
            tool_names = set(mcp._tool_manager._tools.keys())  # pylint: disable=protected-access
        self.assertNotIn(
            "create_it_ticket",
            tool_names,
            "create_it_ticket must not be registered while tools.config.json gate is false.",
        )
        self.assertIn("get_ticket", tool_names)  # sanity: other tools still register


if __name__ == "__main__":
    unittest.main(verbosity=2)
