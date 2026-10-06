"""Unit tests for Lifecycle Hooks converter (cc2agy.converters.hooks)."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cc2agy.converters.hooks import (
    convert_hooks_data,
    convert_hooks_file,
    sanitize_hook_command,
    sanitize_matcher,
    write_hooks_data,
)


def _decode_spec(command: str) -> dict:
    """Return the JSON spec from a hook-runner command."""
    return json.loads(base64.urlsafe_b64decode(command.split()[-1]).decode("utf-8"))


def _decode_wrapped(command: str):
    """Return (mode, original command) from a hook-runner command."""
    spec = _decode_spec(command)
    return spec["mode"], spec["command"]


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
            # SessionStart runs through the generated context helper, once per conversation
            command = saved_data["demo-hooks"]["PreInvocation"][0]["command"]
            self.assertEqual(_decode_wrapped(command), ("once", "python test.py"))
            self.assertTrue((dest_dir / "cc2agy_hooks" / "hook_runner.py").exists())

    def test_sanitize_hook_command_absolute_root(self):
        root = Path(tempfile.gettempdir()) / "my plugin"
        cmd = 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/start.sh" $CLAUDE_PLUGIN_ROOT'
        expected = f'bash "{root.as_posix()}/hooks/start.sh" {root.as_posix()}'
        self.assertEqual(sanitize_hook_command(cmd, root), expected)
        self.assertNotIn("\\", sanitize_hook_command(cmd, root))

    def test_edit_matchers_cover_both_antigravity_edit_tools(self):
        self.assertEqual(sanitize_matcher("Edit"), "(?:replace_file_content|multi_replace_file_content)")
        self.assertEqual(sanitize_matcher("MultiEdit"), "multi_replace_file_content")
        self.assertEqual(
            sanitize_matcher("Write|Edit"),
            "write_to_file|(?:replace_file_content|multi_replace_file_content)",
        )

    def test_session_start_matchers_without_startup_are_skipped(self):
        raw = {"SessionStart": [
            {"matcher": "startup|resume", "hooks": [{"command": "echo a"}]},
            {"matcher": "compact", "hooks": [{"command": "echo b"}]},
            {"hooks": [{"command": "echo c"}]},
        ]}
        with tempfile.TemporaryDirectory() as tmp_dir:
            converted, warnings = convert_hooks_data(raw, "p", Path(tmp_dir), Path(tmp_dir))
        commands = [_decode_wrapped(h["command"])[1] for h in converted["p-hooks"]["PreInvocation"]]
        self.assertEqual(commands, ["echo a", "echo c"])
        self.assertTrue(any("'compact'" in w for w in warnings))

    def test_user_prompt_submit_runs_always_with_warning(self):
        raw = {"UserPromptSubmit": [{"hooks": [{"command": "echo ctx"}]}]}
        with tempfile.TemporaryDirectory() as tmp_dir:
            converted, warnings = convert_hooks_data(raw, "p", Path(tmp_dir), Path(tmp_dir))
        self.assertEqual(_decode_wrapped(converted["p-hooks"]["PreInvocation"][0]["command"]), ("always", "echo ctx"))
        self.assertTrue(any("every model invocation" in w for w in warnings))

    def test_unquoted_plugin_root_with_spaces_warns(self):
        raw = {"Stop": [{"hooks": [{"command": "bash ${CLAUDE_PLUGIN_ROOT}/stop.sh"}]}]}
        root = Path(tempfile.gettempdir()) / "my plugin"
        _, warnings = convert_hooks_data(raw, "p", root)
        self.assertTrue(any("without quotes" in w for w in warnings))

        quoted = {"Stop": [{"hooks": [{"command": 'bash "${CLAUDE_PLUGIN_ROOT}/stop.sh"'}]}]}
        _, warnings = convert_hooks_data(quoted, "p", root)
        self.assertFalse(any("without quotes" in w for w in warnings))

    def test_standalone_hooks_file_points_to_source_plugin_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = Path(tmp_dir) / "plug"
            (plugin / "hooks").mkdir(parents=True)
            source = plugin / "hooks" / "hooks.json"
            source.write_text(json.dumps({"hooks": {"Stop": [
                {"hooks": [{"command": 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/stop.sh"'}]}]}}), encoding="utf-8")

            res, _ = convert_hooks_file(source, Path(tmp_dir) / "out", plugin_name="plug")
            command = json.loads(res.read_text(encoding="utf-8"))["plug-hooks"]["Stop"][0]["command"]
            self.assertEqual(command, f'bash "{plugin.resolve().as_posix()}/hooks/stop.sh"')

    def test_context_helper_runs_once_and_injects_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir) / "out"
            write_hooks_data({"SessionStart": [{"hooks": [{"command": "echo ctx"}]}]}, dest, "p")
            helper = dest / "cc2agy_hooks" / "hook_runner.py"
            spec = {"mode": "once", "command": "echo ctx", "args": None, "env": {}}
            encoded = base64.urlsafe_b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")

            def run(invocation_num):
                result = subprocess.run(
                    [sys.executable, str(helper), encoded],
                    input=json.dumps({"invocationNum": invocation_num}),
                    capture_output=True, text=True, check=True,
                )
                return json.loads(result.stdout)

            self.assertEqual(run(0), {"injectSteps": [{"ephemeralMessage": "ctx"}]})
            self.assertEqual(run(1), {})

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
