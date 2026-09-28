from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from second_brain.config import load_config
from second_brain.db.migrate import apply_migrations

try:
    from second_brain import mcp_server
    MCP_AVAILABLE = True
except ModuleNotFoundError:
    # The `mcp` package may not be installed in every environment.
    MCP_AVAILABLE = False


@unittest.skipUnless(MCP_AVAILABLE, "mcp package not installed")
class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.db_path = ROOT / "data" / "test_mcp.db"
        if self.db_path.exists():
            self.db_path.unlink()
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.db_path) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        env = {
            "APP_ENV": "test",
            "VAULT_PATH": "tests/fixtures/vault",
            "DATABASE_URL": f"sqlite:///{self.db_path}",
            "ATTACHMENT_TEMP_DIR": str(ROOT / "data" / "tmp" / "test-mcp"),
            "LOG_LEVEL": "INFO",
            "HERMES_INTERNAL_TOOL_TOKEN": "test-token",
        }
        config = load_config(env=env, env_file=None, project_root=ROOT)
        apply_migrations(config)
        # Inject the test config so _dispatch uses the test DB (not the dev DB).
        mcp_server._config = config

    def tearDown(self):
        mcp_server._config = None

    def _tool_names(self):
        import asyncio

        return {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}

    def test_phase3_tools_are_registered(self):
        self.assertEqual(
            self._tool_names(),
            {
                # Phase 1: status
                "second_brain_health_check",
                "second_brain_job_status",
                "second_brain_sync_status",
                # Phase 2: capture
                "second_brain_capture_note",
                # Phase 3: search + organize + unified undo
                "second_brain_search_vault",
                "second_brain_get_note",
                "second_brain_move_note",
                "second_brain_update_note",
                "second_brain_undo",
            },
        )

    def test_disabled_and_retired_tools_not_exposed(self):
        from second_brain.tools.capabilities import INITIAL_CAPABILITIES

        names = self._tool_names()
        disabled = [c.id for c in INITIAL_CAPABILITIES if not c.enabled]
        # approve_media (Phase 6) must stay disabled until its phase.
        self.assertIn("approve_media", disabled)
        for forbidden in disabled:
            self.assertNotIn(forbidden, names)
            self.assertNotIn(f"second_brain_{forbidden}", names)
        # undo_capture was replaced by the unified `undo` tool in Phase 3.
        self.assertNotIn("second_brain_undo_capture", names)

    def test_health_check_dispatch(self):
        data = json.loads(mcp_server._dispatch("health_check"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["result"]["service"], "second-brain-core")
        self.assertTrue(data["operation_id"].startswith("op_"))

    def test_disabled_capability_is_rejected(self):
        # approve_media is still disabled (Phase 6).
        data = json.loads(mcp_server._dispatch("approve_media"))
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "CAPABILITY_REJECTED")


if __name__ == "__main__":
    unittest.main()
