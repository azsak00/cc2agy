"""Unit tests for --install (conversion straight into Antigravity's install folders)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cc2agy.cli import main


HOOKS = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}]}}


def _run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(args)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class TestInstall(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self._cwd = os.getcwd()
        os.chdir(self.workspace)
        self._home_patch = mock.patch.object(Path, "home", return_value=self.home)
        self._home_patch.start()

    def tearDown(self):
        self._home_patch.stop()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _make_project(self, name: str = "proj", server: str = "docs") -> Path:
        project = self.root / name
        (project / ".claude" / "commands").mkdir(parents=True)
        (project / ".claude" / "commands" / "review.md").write_text("Review $ARGUMENTS", encoding="utf-8")
        (project / ".claude" / "agents").mkdir()
        (project / ".claude" / "agents" / "checker.md").write_text(
            "---\nname: checker\ndescription: Checks\n---\nCheck.", encoding="utf-8"
        )
        (project / "CLAUDE.md").write_text("# Rules\nBe precise.", encoding="utf-8")
        (project / ".mcp.json").write_text(
            json.dumps({"mcpServers": {server: {"command": "npx", "args": ["docs-server"]}}}), encoding="utf-8"
        )
        (project / "hooks.json").write_text(json.dumps(HOOKS), encoding="utf-8")
        return project

    def _make_plugin(self) -> Path:
        plugin = self.root / "src-plugin"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "demo"}), encoding="utf-8")
        (plugin / "commands").mkdir()
        (plugin / "commands" / "go.md").write_text("Go", encoding="utf-8")
        return plugin

    def test_plugin_install_project(self):
        code, _, err = _run(["convert", str(self._make_plugin()), "--install", "project"])
        self.assertEqual(code, 0, err)
        plugin_dir = self.workspace / ".agents" / "plugins" / "demo"
        self.assertTrue((plugin_dir / "plugin.json").is_file())
        self.assertTrue((plugin_dir / "skills" / "go" / "SKILL.md").is_file())

    def test_plugin_install_user(self):
        code, _, err = _run(["convert", str(self._make_plugin()), "--install", "user"])
        self.assertEqual(code, 0, err)
        self.assertTrue((self.home / ".gemini" / "config" / "plugins" / "demo" / "plugin.json").is_file())

    def test_folder_install_project_layout(self):
        code, _, err = _run(["convert", str(self._make_project()), "--install", "project"])
        self.assertEqual(code, 0, err)
        base = self.workspace / ".agents"
        self.assertTrue((base / "skills" / "review" / "SKILL.md").is_file())
        self.assertTrue((base / "agents" / "checker.md").is_file())
        self.assertTrue((base / "rules" / "AGENTS.md").is_file())
        self.assertFalse((base / "AGENTS.md").exists())
        mcp = json.loads((base / "mcp_config.json").read_text(encoding="utf-8"))
        self.assertIn("docs", mcp["mcpServers"])
        hooks = json.loads((base / "hooks.json").read_text(encoding="utf-8"))
        self.assertIn("proj-hooks", hooks)

    def test_folder_install_user_layout(self):
        code, _, err = _run(["convert", str(self._make_project()), "--install", "user"])
        self.assertEqual(code, 0, err)
        base = self.home / ".gemini" / "config"
        self.assertTrue((base / "skills" / "review" / "SKILL.md").is_file())
        self.assertTrue((base / "rules" / "AGENTS.md").is_file())
        self.assertTrue((base / "mcp_config.json").is_file())

    def test_install_merges_existing_mcp_and_hooks(self):
        base = self.workspace / ".agents"
        base.mkdir()
        (base / "mcp_config.json").write_text(
            json.dumps({"mcpServers": {"mine": {"command": "my-server"}}}), encoding="utf-8"
        )
        (base / "hooks.json").write_text(json.dumps({"my-hook": {"Stop": []}}), encoding="utf-8")

        code, _, err = _run(["convert", str(self._make_project()), "--install", "project"])

        self.assertEqual(code, 0, err)
        mcp = json.loads((base / "mcp_config.json").read_text(encoding="utf-8"))
        self.assertEqual(set(mcp["mcpServers"]), {"mine", "docs"})
        hooks = json.loads((base / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(set(hooks), {"my-hook", "proj-hooks"})
        backup = json.loads((base / "mcp_config.json.cc2agy.bak").read_text(encoding="utf-8"))
        self.assertEqual(set(backup["mcpServers"]), {"mine"})
        self.assertTrue((base / "hooks.json.cc2agy.bak").is_file())

    def test_install_same_server_name_needs_overwrite(self):
        base = self.workspace / ".agents"
        base.mkdir()
        (base / "mcp_config.json").write_text(
            json.dumps({"mcpServers": {"docs": {"command": "original"}, "mine": {"command": "my-server"}}}),
            encoding="utf-8",
        )
        project = self._make_project()

        code, out, err = _run(["convert", str(project), "--install", "project"])
        self.assertEqual(code, 0, err)
        mcp = json.loads((base / "mcp_config.json").read_text(encoding="utf-8"))
        self.assertEqual(mcp["mcpServers"]["docs"]["command"], "original")
        self.assertIn("docs", out + err)

        code, _, err = _run(["convert", str(project), "--install", "project", "--overwrite"])
        self.assertEqual(code, 0, err)
        mcp = json.loads((base / "mcp_config.json").read_text(encoding="utf-8"))
        self.assertEqual(mcp["mcpServers"]["docs"]["command"], "npx")
        self.assertEqual(mcp["mcpServers"]["mine"]["command"], "my-server")

    def test_reinstall_same_hook_group_needs_overwrite(self):
        project = self._make_project()
        self.assertEqual(_run(["convert", str(project), "--install", "project"])[0], 0)
        base = self.workspace / ".agents"
        hooks_file = base / "hooks.json"
        hooks = json.loads(hooks_file.read_text(encoding="utf-8"))
        hooks["other"] = {"Stop": []}
        hooks_file.write_text(json.dumps(hooks), encoding="utf-8")

        _, out, err = _run(["convert", str(project), "--install", "project"])
        self.assertIn("proj-hooks", out + err)

        code, _, err = _run(["convert", str(project), "--install", "project", "--overwrite"])
        self.assertEqual(code, 0, err)
        self.assertEqual(set(json.loads(hooks_file.read_text(encoding="utf-8"))), {"proj-hooks", "other"})

    def test_install_refuses_invalid_existing_json(self):
        base = self.workspace / ".agents"
        base.mkdir()
        (base / "mcp_config.json").write_text("{not json", encoding="utf-8")

        code, _, err = _run(["convert", str(self._make_project()), "--install", "project"])

        self.assertEqual(code, 1)
        self.assertIn("mcp_config.json", err)
        self.assertEqual((base / "mcp_config.json").read_text(encoding="utf-8"), "{not json")

    def test_install_with_dest_is_an_error(self):
        code, _, err = _run(["convert", str(self._make_project()), "--install", "project", "--dest", "out"])
        self.assertNotEqual(code, 0)
        self.assertIn("--install", err)
        self.assertFalse((self.workspace / "out").exists())


if __name__ == "__main__":
    unittest.main()
