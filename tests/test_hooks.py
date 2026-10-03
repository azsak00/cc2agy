"""Unit tests for Lifecycle Hooks converter (cc2agy.converters.hooks)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cc2agy.converters.hooks import (
    convert_hooks_data,
    convert_hooks_file,
    sanitize_hook_command,
)


class TestHooksConverter(unittest.TestCase):
    def test_sanitize_hook_command(self):
        cmd1 = 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"'
        self.assertEqual(sanitize_hook_command(cmd1), 'bash "./hooks/session-start.sh"')

        cmd2 = 'python3 "$CLAUDE_PLUGIN_ROOT/scripts/lint.py"'
        self.assertEqual(sanitize_hook_command(cmd2), 'python3 "./scripts/lint.py"')

        cmd3 = 'echo ${CLAUDE_PLUGIN_ROOT}'
        self.assertEqual(sanitize_hook_command(cmd3), 'echo .')

    def test_convert_hooks_data_mapping_and_unwrapping(self):
        raw_claude_hooks = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"',
                            }
                        ]
                    }
                ],
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" "${CLAUDE_PLUGIN_ROOT}/hooks/stop-check.py"',
                                "timeout": 15,
                            }
                        ]
                    }
                ],
                "PreToolUse": [
                    {
                        "matcher": "run_command",
                        "hooks": [
                            {
                                "command": 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/guard.sh"'
                            }
                        ]
                    }
                ]
            }
        }

        converted, warnings = convert_hooks_data(raw_claude_hooks, plugin_name="test-plug")
        self.assertIn("test-plug-hooks", converted)
        hook_spec = converted["test-plug-hooks"]

        # Check SessionStart mapped to PreInvocation
        self.assertIn("PreInvocation", hook_spec)
        self.assertEqual(len(hook_spec["PreInvocation"]), 1)
        self.assertEqual(hook_spec["PreInvocation"][0]["command"], 'bash "./hooks/session-start.sh"')
        self.assertEqual(hook_spec["PreInvocation"][0]["type"], "command")

        # Check Stop flat unwrapping
        self.assertIn("Stop", hook_spec)
        self.assertEqual(len(hook_spec["Stop"]), 1)
        self.assertEqual(
            hook_spec["Stop"][0]["command"],
            'bash "./hooks/python.sh" "./hooks/stop-check.py"'
        )
        self.assertEqual(hook_spec["Stop"][0]["timeout"], 15)

        # Check PreToolUse grouping with matcher
        self.assertIn("PreToolUse", hook_spec)
        self.assertEqual(len(hook_spec["PreToolUse"]), 1)
        self.assertEqual(hook_spec["PreToolUse"][0]["matcher"], "run_command")
        self.assertEqual(hook_spec["PreToolUse"][0]["hooks"][0]["command"], 'bash "./scripts/guard.sh"')

    def test_convert_hooks_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "hooks.json"
            dest_dir = tmp_path / "out"

            raw_data = {
                "SessionStart": [
                    {"command": "python test.py"}
                ]
            }
            source_file.write_text(json.dumps(raw_data), encoding="utf-8")

            res_path, warnings = convert_hooks_file(source_file, dest_dir, plugin_name="demo")
            self.assertTrue(res_path.exists())
            self.assertEqual(res_path.name, "hooks.json")

            with open(res_path, "r", encoding="utf-8") as f:
                saved_data = json.load(f)

            self.assertIn("demo-hooks", saved_data)
            self.assertIn("PreInvocation", saved_data["demo-hooks"])
            self.assertEqual(saved_data["demo-hooks"]["PreInvocation"][0]["command"], "python test.py")

    def test_hooks_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "hooks.json"
            dest_dir = tmp_path / "out"
            dest_dir.mkdir(parents=True, exist_ok=True)
            existing_file = dest_dir / "hooks.json"
            existing_file.write_text("{}", encoding="utf-8")

            source_file.write_text('{"Stop": [{"command": "echo stop"}]}', encoding="utf-8")

            with self.assertRaises(FileExistsError):
                convert_hooks_file(source_file, dest_dir, overwrite=False)

            # With overwrite=True
            res, _ = convert_hooks_file(source_file, dest_dir, overwrite=True)
            self.assertTrue(res.exists())


if __name__ == "__main__":
    unittest.main()
