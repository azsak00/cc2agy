"""The plugin conversion looks for components where the detector (inspect) finds them."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cc2agy.converters.plugin import convert_plugin
from cc2agy.detector import detect_claude_project

SRC_DIR = Path(__file__).resolve().parent.parent / "src"


def _make_plugin(root: Path, files: dict) -> Path:
    plugin = root / "plug"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "plug"}), encoding="utf-8")
    for rel, text in files.items():
        (plugin / rel).parent.mkdir(parents=True, exist_ok=True)
        (plugin / rel).write_text(text, encoding="utf-8")
    return plugin


class TestSharedLocations(unittest.TestCase):
    def test_plugin_reads_mcp_config_from_claude_folder(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {
                ".claude/.mcp.json": json.dumps({"mcpServers": {"eco": {"command": "python", "args": ["x.py"]}}}),
            })

            info = detect_claude_project(plugin)
            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertEqual(info.mcp_file.name, ".mcp.json")
            self.assertEqual(summary["mcp_migrated"], 1)
            servers = json.loads((plugin_dir / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]
            self.assertIn("eco", servers)

    def test_plugin_converts_the_commands_inspect_lists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {
                "commands/alpha.md": "---\ndescription: a\n---\nA",
                ".claude/commands/beta.md": "---\ndescription: b\n---\nB",
                "prompts/gamma.md": "---\ndescription: c\n---\nC",
                "prompts/alpha.md": "---\ndescription: a2\n---\nA2",
            })

            info = detect_claude_project(plugin)
            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            skills = sorted(p.name for p in (plugin_dir / "skills").iterdir())
            self.assertEqual(len(info.command_files), 4)
            self.assertEqual(skills, ["alpha", "alpha-2", "beta", "gamma"])
            self.assertEqual(summary["skills_migrated"], 4)
            self.assertNotIn("prompts", summary["auxiliary_dirs_copied"])
            self.assertTrue(any("alpha-2" in w for w in summary["warnings"]))

    def test_plugin_converts_agents_from_claude_folder(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {
                ".claude/agents/helper.md": "---\nname: helper\ndescription: d\n---\nHelp.",
            })

            info = detect_claude_project(plugin)
            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertEqual(len(info.agent_files), 1)
            self.assertEqual(summary["agents_migrated"], 1)
            self.assertTrue((plugin_dir / "agents" / "helper.md").is_file())

    def test_inspect_lists_the_folders_the_plugin_conversion_copies(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {
                "servers/eco.py": "print('mcp')",
                "bin/tool": "echo ok",
                "scripts/lint.py": "print('lint')",
                "commands/go.md": "Go",
                "rules/CLAUDE.md": "Rule.",
                ".git/config": "[core]",
            })

            info = detect_claude_project(plugin)
            _, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            listed = [d.name for d in info.auxiliary_dirs]
            self.assertEqual(listed, ["bin", "scripts", "servers"])
            self.assertEqual(sorted(summary["auxiliary_dirs_copied"]), listed)
            self.assertIn("bin", info.summary())

    def test_folder_that_is_not_a_plugin_lists_no_auxiliary_folders(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            project = Path(tmp_dir)
            (project / "scripts").mkdir()
            (project / "commands").mkdir()
            (project / "commands" / "go.md").write_text("Go", encoding="utf-8")

            self.assertEqual(detect_claude_project(project).auxiliary_dirs, [])

    def test_detector_imports_on_its_own(self):
        result = subprocess.run(
            [sys.executable, "-c", "import cc2agy.detector"],
            cwd=SRC_DIR, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
