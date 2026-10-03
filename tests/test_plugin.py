"""Unit tests for Full Plugin Converter (cc2agy.converters.plugin)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cc2agy.cli import main
from cc2agy.converters.plugin import convert_plugin, sanitize_skill_content


class TestPluginConverter(unittest.TestCase):
    def test_sanitize_skill_content(self):
        text = '1. Run script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lint.py"`'
        expected = '1. Run script: `python3 "../../scripts/lint.py"`'
        self.assertEqual(sanitize_skill_content(text), expected)

        text2 = 'Link to [tool]($CLAUDE_PLUGIN_ROOT/scripts/tool.py)'
        expected2 = 'Link to [tool](../../scripts/tool.py)'
        self.assertEqual(sanitize_skill_content(text2), expected2)

    def test_convert_full_plugin_complete_structure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_plugin = tmp_path / "mock-plugin"
            dest_root = tmp_path / "out"

            # Create mock Claude Code plugin structure
            (source_plugin / ".claude-plugin").mkdir(parents=True)
            manifest = {
                "name": "mock-plugin",
                "description": "Mock plugin description for unit testing.",
                "version": "1.2.0",
                "author": {"name": "Dev Team"},
            }
            (source_plugin / ".claude-plugin" / "plugin.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            # Commands
            (source_plugin / "commands").mkdir()
            (source_plugin / "commands" / "quick-test.md").write_text(
                "---\ndescription: Run quick tests\n---\nRun `pytest`.\n", encoding="utf-8"
            )

            # Skills
            (source_plugin / "skills" / "linter").mkdir(parents=True)
            (source_plugin / "skills" / "linter" / "SKILL.md").write_text(
                "---\nname: linter\ndescription: Run comprehensive lint checks on codebase.\n---\n"
                'Execute `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lint.py"`.\n',
                encoding="utf-8",
            )

            # Rules
            (source_plugin / "CLAUDE.md").write_text(
                "---\ntitle: Claude Rules\n---\n# Rules\nAlways verify.\n", encoding="utf-8"
            )

            # MCP
            (source_plugin / ".mcp.json").write_text(
                json.dumps({"test-srv": {"command": "npx", "args": ["-y", "srv"]}}),
                encoding="utf-8",
            )

            # Hooks
            (source_plugin / "hooks").mkdir()
            hooks_data = {
                "SessionStart": [
                    {"hooks": [{"type": "command", "command": 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/init.sh"'}]}
                ]
            }
            (source_plugin / "hooks" / "hooks.json").write_text(
                json.dumps(hooks_data), encoding="utf-8"
            )
            (source_plugin / "hooks" / "init.sh").write_text("echo starting", encoding="utf-8")

            # Auxiliary directories
            (source_plugin / "scripts").mkdir()
            (source_plugin / "scripts" / "lint.py").write_text("print('linting')", encoding="utf-8")

            (source_plugin / "templates").mkdir()
            (source_plugin / "templates" / "template.txt").write_text("Hello template", encoding="utf-8")

            (source_plugin / "context").mkdir()
            (source_plugin / "context" / "persona.md").write_text("Default persona", encoding="utf-8")
            (source_plugin / "README.md").write_text("# Mock Plugin Readme", encoding="utf-8")

            # Convert plugin
            plugin_dir, summary = convert_plugin(source_plugin, dest_root, overwrite=True)

            self.assertEqual(summary["plugin_name"], "mock-plugin")
            self.assertEqual(summary["skills_migrated"], 2)
            self.assertEqual(summary["rules_migrated"], 1)
            self.assertEqual(summary["mcp_migrated"], 1)
            self.assertEqual(summary["hooks_migrated"], 1)
            self.assertIn("scripts", summary["auxiliary_dirs_copied"])
            self.assertIn("templates", summary["auxiliary_dirs_copied"])
            self.assertIn("context", summary["auxiliary_dirs_copied"])

            # Verify directory output
            self.assertTrue((plugin_dir / "plugin.json").exists())
            self.assertTrue((plugin_dir / "README.md").exists())
            self.assertTrue((plugin_dir / "mcp_config.json").exists())
            self.assertTrue((plugin_dir / "hooks.json").exists())
            self.assertTrue((plugin_dir / "rules" / "AGENTS.md").exists())
            self.assertTrue((plugin_dir / "skills" / "quick-test" / "SKILL.md").exists())
            self.assertTrue((plugin_dir / "skills" / "linter" / "SKILL.md").exists())
            self.assertTrue((plugin_dir / "scripts" / "lint.py").exists())
            self.assertTrue((plugin_dir / "templates" / "template.txt").exists())
            self.assertTrue((plugin_dir / "context" / "persona.md").exists())
            self.assertTrue((plugin_dir / "hooks" / "init.sh").exists())
            # Ensure hooks.json was moved to root and removed from hooks/ subfolder
            self.assertFalse((plugin_dir / "hooks" / "hooks.json").exists())

            # Verify SKILL.md path sanitization
            linter_content = (plugin_dir / "skills" / "linter" / "SKILL.md").read_text(encoding="utf-8")
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", linter_content)
            self.assertIn('../../scripts/lint.py', linter_content)

            # Verify AGENTS.md frontmatter stripped
            agents_content = (plugin_dir / "rules" / "AGENTS.md").read_text(encoding="utf-8")
            self.assertNotIn("---", agents_content)
            self.assertIn("# Rules", agents_content)

    def test_cli_convert_plugin_autodetect(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_plugin = tmp_path / "auto-plugin"
            dest_root = tmp_path / "cli_out"

            source_plugin.mkdir(parents=True)
            (source_plugin / "plugin.json").write_text(
                json.dumps({"name": "auto-plugin", "version": "0.1.0"}),
                encoding="utf-8",
            )
            (source_plugin / "commands").mkdir()
            (source_plugin / "commands" / "foo.md").write_text(
                "---\ndescription: Test command foo\n---\nDo foo.\n",
                encoding="utf-8",
            )

            exit_code = main(["convert", str(source_plugin), "--dest", str(dest_root), "--overwrite"])
            self.assertEqual(exit_code, 0)

            expected_manifest = dest_root / "plugins" / "auto-plugin" / "plugin.json"
            self.assertTrue(expected_manifest.exists())


if __name__ == "__main__":
    unittest.main()
