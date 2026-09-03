"""fetch_cursor_agent_models：优先独立 agent，避免 cursor shim / Workspace Trust。"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cursor_automation import (
    cursor_agent_models_argv,
    fetch_cursor_agent_models,
    resolve_cursor_models_cli,
)


class ResolveModelsCliTests(unittest.TestCase):
    def test_prefers_agent_over_cursor(self) -> None:
        def which(name: str) -> str | None:
            return {
                "agent": "/usr/bin/agent",
                "cursor-agent": "/usr/bin/cursor-agent",
                "cursor": "/usr/bin/cursor",
            }.get(name)

        with mock.patch("cursor_automation.shutil.which", side_effect=which):
            self.assertEqual(resolve_cursor_models_cli(), "/usr/bin/agent")

    def test_falls_back_to_resolve_cursor_cli(self) -> None:
        with mock.patch("cursor_automation.shutil.which", return_value=None):
            with mock.patch(
                "cursor_automation.resolve_cursor_cli",
                return_value="/Applications/Cursor.app/Contents/Resources/app/bin/cursor",
            ):
                self.assertTrue(
                    resolve_cursor_models_cli().endswith("/bin/cursor")  # type: ignore[union-attr]
                )


class FetchModelsTests(unittest.TestCase):
    def test_uses_agent_models_argv_without_trust(self) -> None:
        stdout = (
            "Available models\n"
            "\n"
            "composer-2.5 - Composer 2.5\n"
            "cursor-grok-4.6-high-fast - Cursor Grok 4.6 Fast\n"
            "\n"
            "Tip: use --model <id>\n"
        )
        cp = mock.Mock(returncode=0, stdout=stdout, stderr="")
        with mock.patch(
            "cursor_automation.resolve_cursor_models_cli",
            return_value="/root/.local/bin/agent",
        ):
            with mock.patch("cursor_automation.subprocess.run", return_value=cp) as run:
                rows = fetch_cursor_agent_models()
        self.assertEqual(run.call_args.args[0], ["/root/.local/bin/agent", "models"])
        self.assertEqual([r["id"] for r in rows], ["composer-2.5", "cursor-grok-4.6-high-fast"])

    def test_adds_trust_for_unified_cursor_cli(self) -> None:
        cp = mock.Mock(returncode=0, stdout="auto - Auto (default)\n", stderr="")
        with mock.patch(
            "cursor_automation.resolve_cursor_models_cli",
            return_value="/usr/local/bin/cursor",
        ):
            with mock.patch("cursor_automation.subprocess.run", return_value=cp) as run:
                rows = fetch_cursor_agent_models()
        self.assertEqual(
            run.call_args.args[0],
            ["/usr/local/bin/cursor", "agent", "models", "--trust"],
        )
        self.assertEqual(rows[0]["id"], "auto")

    def test_cursor_agent_models_argv_standalone(self) -> None:
        self.assertEqual(cursor_agent_models_argv("/bin/agent"), ["/bin/agent", "models"])
        self.assertEqual(
            cursor_agent_models_argv("/bin/cursor"),
            ["/bin/cursor", "agent", "models"],
        )


if __name__ == "__main__":
    unittest.main()
