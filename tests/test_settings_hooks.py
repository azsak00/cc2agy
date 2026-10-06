"""Unit tests for project hooks in .claude/settings.json and .claude/settings.local.json."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cc2agy.cli import main
from cc2agy.converters.hooks import convert_hooks_data


def _run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


def _command(handler: dict) -> str:
    """Original command of a converted handler (decoded from the hook runner spec)."""
    spec = json.loads(base64.urlsafe_b64decode(handler["command"].split()[-1]).decode("utf-8"))
    return spec["command"]


def _hook(command: str, matcher: str | None = None) -> dict:
    group = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        group["matcher"] = matcher
    return group


class TestSettingsHooks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.project = self.root / "proj"
        (self.project / ".claude").mkdir(parents=True)
        self.dest = self.root / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def _settings(self, name: str, data: dict, encoding: str = "utf-8") -> Path:
        path = self.project / ".claude" / name
        path.write_text(json.dumps(data), encoding=encoding)
        return path

    def _converted(self) -> dict:
        (group,) = json.loads((self.dest / "hooks.json").read_text(encoding="utf-8")).values()
        return group

    def test_project_settings_hooks_are_converted(self):
        self._settings("settings.json", {
            "permissions": {"allow": ["Bash(npm test)"]},
            "hooks": {"PreToolUse": [_hook('"$CLAUDE_PROJECT_DIR"/.claude/hooks/guard.sh', "Bash")]},
        })
        code, out, err = _run(["convert", str(self.project), "--dest", str(self.dest)])
        self.assertEqual(code, 0, err)
        group = self._converted()["PreToolUse"][0]
        self.assertEqual(group["matcher"], "run_command")
        self.assertEqual(_command(group["hooks"][0]), '"$CLAUDE_PROJECT_DIR"/.claude/hooks/guard.sh')
        self.assertIn("permissions", out)

    def test_shared_and_local_hooks_add_up_and_duplicates_run_once(self):
        self._settings("settings.json", {"hooks": {
            "PreToolUse": [_hook("echo a", "Bash")], "Stop": [_hook("echo s")]}})
        self._settings("settings.local.json", {"hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "echo a"}, {"type": "command", "command": "echo b"}]}]}})
        code, _, err = _run(["convert", str(self.project), "--dest", str(self.dest)])
        self.assertEqual(code, 0, err)
        converted = self._converted()
        commands = [_command(h) for g in converted["PreToolUse"] for h in g["hooks"]]
        self.assertEqual(commands, ["echo a", "echo b"])
        self.assertEqual([_command(h) for h in converted["Stop"]], ["echo s"])

    def test_disable_all_hooks_follows_settings_precedence(self):
        self._settings("settings.json", {"hooks": {"Stop": [_hook("echo s")]}})
        self._settings("settings.local.json", {"disableAllHooks": True})
        code, out, err = _run(["convert", str(self.project), "--dest", str(self.dest)])
        self.assertEqual(code, 0, err)
        self.assertFalse((self.dest / "hooks.json").exists())
        self.assertIn("disableAllHooks", out)

        # The local file's false overrides the shared file's true
        self._settings("settings.json", {"disableAllHooks": True, "hooks": {"Stop": [_hook("echo s")]}})
        self._settings("settings.local.json", {"disableAllHooks": False})
        code, _, err = _run(["convert", str(self.project), "--dest", str(self.dest)])
        self.assertEqual(code, 0, err)
        self.assertEqual([_command(h) for h in self._converted()["Stop"]], ["echo s"])

    def test_settings_without_hooks_is_not_a_hooks_source(self):
        self._settings("settings.json", {"permissions": {"allow": ["Read"]}})
        (self.project / ".claude" / "commands").mkdir()
        (self.project / ".claude" / "commands" / "go.md").write_text("Go", encoding="utf-8")
        code, out, err = _run(["convert", str(self.project), "--dest", str(self.dest)])
        self.assertEqual(code, 0, err)
        self.assertFalse((self.dest / "hooks.json").exists())
        self.assertNotIn("permissions", out)
        self.assertNotIn("Hooks", _run(["inspect", str(self.project)])[1])

    def test_settings_file_as_single_target(self):
        local = self._settings("settings.local.json", {"hooks": {"Stop": [_hook("echo s")]}})
        code, _, err = _run(["convert", str(local), "--dest", str(self.dest)])
        self.assertEqual(code, 0, err)
        self.assertEqual([_command(h) for h in self._converted()["Stop"]], ["echo s"])

    def test_inspect_lists_settings_hooks(self):
        self._settings("settings.json", {"hooks": {"Stop": [_hook("echo s")]}})
        self._settings("settings.local.json", {"hooks": {"Stop": [_hook("echo t")]}})
        code, out, _ = _run(["inspect", str(self.project)])
        self.assertEqual(code, 0)
        self.assertIn("settings.json, settings.local.json", out)

    def test_settings_saved_with_bom_are_read(self):
        # Windows PowerShell 5.1 writes UTF-8 with a BOM (Set-Content -Encoding utf8)
        self._settings("settings.json", {"hooks": {"Stop": [_hook("echo s")]}}, encoding="utf-8-sig")
        code, _, err = _run(["convert", str(self.project), "--dest", str(self.dest)])
        self.assertEqual(code, 0, err)
        self.assertIn("Stop", self._converted())

    def test_non_command_hook_types_are_reported(self):
        raw = {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "prompt", "prompt": "Is this safe? $ARGUMENTS"}, {"type": "command", "command": "echo ok"}]}],
            "Stop": [{"hooks": [{"type": "http", "url": "http://localhost:8080/stop"}]}]}
        converted, warnings = convert_hooks_data(raw, "p")
        self.assertEqual(len(converted["p-hooks"]["PreToolUse"][0]["hooks"]), 1)
        self.assertTrue(any("'prompt'" in w for w in warnings))
        self.assertTrue(any("'http'" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
