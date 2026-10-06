"""Unit tests for Full Plugin Converter (cc2agy.converters.plugin)."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cc2agy.cli import main
from cc2agy.converters.plugin import convert_plugin, sanitize_skill_content
from cc2agy.detector import detect_claude_project


class TestPluginConverter(unittest.TestCase):
    def test_sanitize_skill_content(self):
        text = '1. Run script: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lint.py"`'
        expected = '1. Run script: `python3 "../../scripts/lint.py"`'
        self.assertEqual(sanitize_skill_content(text), expected)

        text2 = 'Link to [tool]($CLAUDE_PLUGIN_ROOT/scripts/tool.py)'
        expected2 = 'Link to [tool](../../scripts/tool.py)'
        self.assertEqual(sanitize_skill_content(text2), expected2)

        root = Path(tempfile.gettempdir()) / "plugins" / "demo"
        self.assertEqual(
            sanitize_skill_content(text, root),
            f'1. Run script: `python3 "{root.as_posix()}/scripts/lint.py"`',
        )

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
            self.assertIn(f'"{plugin_dir.as_posix()}/scripts/lint.py"', linter_content)

            # Verify AGENTS.md frontmatter stripped
            agents_content = (plugin_dir / "rules" / "AGENTS.md").read_text(encoding="utf-8")
            self.assertNotIn("---", agents_content)
            self.assertIn("# Rules", agents_content)

    def test_reconvert_with_overwrite_updates_command_skills(self):
        """--overwrite must refresh skills generated from commands, not keep the stale copy."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_plugin = tmp_path / "plug"
            (source_plugin / ".claude-plugin").mkdir(parents=True)
            (source_plugin / ".claude-plugin" / "plugin.json").write_text('{"name": "plug"}', encoding="utf-8")
            (source_plugin / "commands").mkdir()
            command = source_plugin / "commands" / "hello.md"
            dest_root = tmp_path / "out"

            command.write_text("# Hello\nVERSION 1", encoding="utf-8")
            convert_plugin(source_plugin, dest_root)

            command.write_text("# Hello\nVERSION 2", encoding="utf-8")
            plugin_dir, summary = convert_plugin(source_plugin, dest_root, overwrite=True)

            content = (plugin_dir / "skills" / "hello" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("VERSION 2", content)
            self.assertEqual(summary["skills_migrated"], 1)

    def test_overwrite_never_replaces_modular_skill_with_same_named_command(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_plugin = tmp_path / "plug"
            (source_plugin / ".claude-plugin").mkdir(parents=True)
            (source_plugin / ".claude-plugin" / "plugin.json").write_text('{"name": "plug"}', encoding="utf-8")
            (source_plugin / "commands").mkdir()
            (source_plugin / "commands" / "review.md").write_text("# Review\nFROM COMMAND", encoding="utf-8")
            (source_plugin / "skills" / "review").mkdir(parents=True)
            (source_plugin / "skills" / "review" / "SKILL.md").write_text(
                "---\nname: review\ndescription: Modular\n---\nFROM MODULAR SKILL\n", encoding="utf-8"
            )

            plugin_dir, summary = convert_plugin(source_plugin, tmp_path / "out", overwrite=True)

            content = (plugin_dir / "skills" / "review" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("FROM MODULAR SKILL", content)
            self.assertNotIn("FROM COMMAND", content)
            self.assertEqual(summary["skills_migrated"], 1)

    def _make_plugin(self, root: Path, manifest: dict) -> Path:
        plugin = root / "plug"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        return plugin

    def test_manifest_inline_mcp_servers_merge_with_mcp_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {
                "name": "plug",
                "mcpServers": [
                    {"fs": {"command": "npx", "args": ["fs-v2"]}},
                    "./config/extra-mcp.json",
                    "./bundle.mcpb",
                ],
            })
            (plugin / ".mcp.json").write_text(
                json.dumps({"mcpServers": {"fs": {"command": "npx", "args": ["fs-v1"]},
                                           "git": {"command": "git-mcp"}}}),
                encoding="utf-8",
            )
            (plugin / "config").mkdir()
            (plugin / "config" / "extra-mcp.json").write_text(
                json.dumps({"api": {"url": "https://api.example.com/mcp"}}), encoding="utf-8"
            )

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out")

            servers = json.loads((plugin_dir / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]
            self.assertEqual(set(servers), {"fs", "git", "api"})
            self.assertEqual(servers["fs"]["args"], ["fs-v2"])  # declared later replaces .mcp.json
            self.assertEqual(servers["api"]["serverUrl"], "https://api.example.com/mcp")
            self.assertEqual(summary["mcp_migrated"], 1)
            self.assertTrue(any("bundle.mcpb" in w for w in summary["warnings"]))

    def test_manifest_hooks_merge_with_default_hooks_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {
                "name": "plug",
                "hooks": [
                    "./config/extra-hooks.json",
                    {"PostToolUse": [{"matcher": "Write", "hooks": [
                        {"type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}\"/scripts/format.sh"}]}]},
                ],
            })
            (plugin / "hooks").mkdir()
            (plugin / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": "echo stop"}]}]}}), encoding="utf-8")
            (plugin / "config").mkdir()
            (plugin / "config" / "extra-hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "check.sh"}]}]}}), encoding="utf-8")

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out")

            events = json.loads((plugin_dir / "hooks.json").read_text(encoding="utf-8"))["plug-hooks"]
            self.assertEqual(set(events), {"Stop", "PreToolUse", "PostToolUse"})
            self.assertEqual(events["PreToolUse"][0]["matcher"], "run_command")
            self.assertEqual(events["PostToolUse"][0]["matcher"], "write_to_file")
            self.assertEqual(
                events["PostToolUse"][0]["hooks"][0]["command"], f'"{plugin_dir.as_posix()}"/scripts/format.sh'
            )
            self.assertEqual(summary["hooks_migrated"], 1)

    def test_manifest_commands_map_and_paths_replace_default_folder(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {
                "name": "plug",
                "commands": {
                    "status": {"source": "./custom/status.md", "description": "Show deployment status"},
                    "about": {"content": "Explain what this plugin provides.", "description": "Describe plugin"},
                    "outside": {"source": "../escape.md"},
                },
            })
            (plugin / "custom").mkdir()
            (plugin / "custom" / "status.md").write_text("# Status\nCheck the deploy.", encoding="utf-8")
            (plugin / "commands").mkdir()
            (plugin / "commands" / "ignored.md").write_text("# Ignored\nNot listed.", encoding="utf-8")
            (tmp_path / "escape.md").write_text("# Escape", encoding="utf-8")

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out")

            skills = plugin_dir / "skills"
            status = (skills / "status" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn('description: "Show deployment status"', status)
            self.assertIn("Check the deploy.", status)
            about = (skills / "about" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn('description: "Describe plugin"', about)
            self.assertIn("Explain what this plugin provides.", about)
            self.assertFalse((skills / "ignored").exists())
            self.assertFalse((skills / "outside").exists())
            self.assertTrue(any("escapes the plugin folder" in w for w in summary["warnings"]))
            self.assertEqual(summary["skills_migrated"], 2)

    def test_manifest_commands_path_list_and_extra_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {
                "name": "plug",
                "commands": ["./commands/", "./extras/deploy.md"],
                "skills": ["./extra-skills/"],
            })
            (plugin / "commands").mkdir()
            (plugin / "commands" / "hello.md").write_text("# Hello\nHi.", encoding="utf-8")
            (plugin / "extras").mkdir()
            (plugin / "extras" / "deploy.md").write_text("# Deploy\nShip it.", encoding="utf-8")
            (plugin / "skills" / "base").mkdir(parents=True)
            (plugin / "skills" / "base" / "SKILL.md").write_text("---\nname: base\n---\nBase", encoding="utf-8")
            (plugin / "extra-skills" / "bonus").mkdir(parents=True)
            (plugin / "extra-skills" / "bonus" / "SKILL.md").write_text("---\nname: bonus\n---\nBonus", encoding="utf-8")

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out")

            for name in ("hello", "deploy", "base", "bonus"):
                self.assertTrue((plugin_dir / "skills" / name / "SKILL.md").exists(), name)
            self.assertEqual(summary["skills_migrated"], 4)

    def test_plugin_nested_commands_do_not_collide(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {"name": "plug"})
            (plugin / "commands" / "git").mkdir(parents=True)
            (plugin / "commands" / "commit.md").write_text("# Commit\nROOT COMMIT", encoding="utf-8")
            (plugin / "commands" / "git" / "commit.md").write_text("# Commit\nGIT COMMIT", encoding="utf-8")

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            skills = plugin_dir / "skills"
            self.assertIn("ROOT COMMIT", (skills / "commit" / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIn("GIT COMMIT", (skills / "git-commit" / "SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual(summary["skills_migrated"], 2)

    def test_manifest_commands_with_same_name_keep_both_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {
                "name": "plug",
                "commands": ["./commands/", "./extras/commit.md"],
            })
            (plugin / "commands").mkdir()
            (plugin / "commands" / "commit.md").write_text("# Commit\nFROM COMMANDS", encoding="utf-8")
            (plugin / "extras").mkdir()
            (plugin / "extras" / "commit.md").write_text("# Commit\nFROM EXTRAS", encoding="utf-8")

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            skills = plugin_dir / "skills"
            self.assertIn("FROM COMMANDS", (skills / "commit" / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIn("FROM EXTRAS", (skills / "commit-2" / "SKILL.md").read_text(encoding="utf-8"))
            self.assertEqual(summary["skills_migrated"], 2)
            self.assertTrue(any("commit-2" in w for w in summary["warnings"]))

    def test_command_frontmatter_name_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {"name": "plug", "commands": ["./extras/ship.md"]})
            (plugin / "extras").mkdir()
            (plugin / "extras" / "ship.md").write_text("---\nname: deploy\n---\nShip it", encoding="utf-8")

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertTrue((plugin_dir / "skills" / "ship" / "SKILL.md").exists())
            self.assertFalse((plugin_dir / "skills" / "deploy").exists())
            self.assertTrue(any("declares name 'deploy'" in w for w in summary["warnings"]))

    def test_components_without_antigravity_equivalent_warn(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {
                "name": "plug",
                "lspServers": {"go": {"command": "gopls", "extensionToLanguage": {".go": "go"}}},
                "experimental": {"monitors": [{"name": "m", "command": "poll", "description": "d"}]},
                "themes": "./themes/",
                "channels": [{"server": "telegram"}],
                "dependencies": ["secrets-vault"],
                "settings": {"agent": "reviewer"},
            })
            for folder in ("output-styles", "workflows", "themes"):
                (plugin / folder).mkdir()
            (plugin / "output-styles" / "terse.md").write_text("Be terse.", encoding="utf-8")
            (plugin / "settings.json").write_text('{"agent": "reviewer"}', encoding="utf-8")

            _, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            unsupported = [w for w in summary["warnings"] if "no Antigravity plugin equivalent" in w]
            self.assertEqual(len(unsupported), 8, unsupported)
            for origin in (
                "output-styles/", "plugin.json 'lspServers'", "workflows/", "themes/",
                "plugin.json 'themes'", "plugin.json 'experimental.monitors'", "settings.json",
                "plugin.json 'settings'", "plugin.json 'channels'", "plugin.json 'dependencies'",
            ):
                self.assertTrue(any(origin in w for w in unsupported), origin)

    def test_default_lsp_and_monitor_files_warn(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {"name": "plug"})
            (plugin / ".lsp.json").write_text("{}", encoding="utf-8")
            (plugin / "monitors").mkdir()
            (plugin / "monitors" / "monitors.json").write_text("[]", encoding="utf-8")

            _, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            unsupported = [w for w in summary["warnings"] if "no Antigravity plugin equivalent" in w]
            self.assertEqual(len(unsupported), 2, unsupported)
            self.assertTrue(any(".lsp.json" in w for w in unsupported))
            self.assertTrue(any("monitors/monitors.json" in w for w in unsupported))

    def test_plugin_without_unsupported_components_has_no_such_warning(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {"name": "plug", "experimental": {}})
            (plugin / "commands").mkdir()
            (plugin / "commands" / "go.md").write_text("Go", encoding="utf-8")

            _, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertFalse(any("no Antigravity plugin equivalent" in w for w in summary["warnings"]))
            self.assertFalse(any("PATH" in w for w in summary["warnings"]))

    def test_bin_directory_is_copied_with_path_warning(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {"name": "plug"})
            (plugin / "bin").mkdir()
            (plugin / "bin" / "deploy-tool").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertTrue((plugin_dir / "bin" / "deploy-tool").is_file())
            self.assertIn("bin", summary["auxiliary_dirs_copied"])
            self.assertTrue(any("bin/" in w and "PATH" in w for w in summary["warnings"]))

    def test_every_other_plugin_folder_is_copied(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {"name": "plug"})
            files = {
                "servers/eco_server.py": "print('mcp')",
                "dist/index.js": "console.log('mcp')",
                "node_modules/dep/index.js": "module.exports = 1",
                "commands/go.md": "Go",
                "agents/helper.md": "---\nname: helper\ndescription: d\n---\nHelp.",
                "output-styles/terse.md": "Be terse.",
                "rules/CLAUDE.md": "Rule.",
                "rules/style.md": "Style guide.",
                ".git/config": "[core]",
            }
            for rel, text in files.items():
                (plugin / rel).parent.mkdir(parents=True, exist_ok=True)
                (plugin / rel).write_text(text, encoding="utf-8")
            (plugin / ".mcp.json").write_text(json.dumps({"mcpServers": {"eco": {
                "command": "python", "args": ["${CLAUDE_PLUGIN_ROOT}/servers/eco_server.py"]}}}), encoding="utf-8")

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            server = json.loads((plugin_dir / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]["eco"]
            self.assertTrue(Path(server["args"][0]).is_file())
            self.assertTrue((plugin_dir / "dist" / "index.js").is_file())
            self.assertTrue((plugin_dir / "node_modules" / "dep" / "index.js").is_file())
            for skipped in ("commands", "output-styles", ".git", ".claude-plugin"):
                self.assertFalse((plugin_dir / skipped).exists(), skipped)
            self.assertFalse((plugin_dir / "rules" / "style.md").exists())
            self.assertTrue(any("rules/ not copied" in w and "style.md" in w for w in summary["warnings"]))
            self.assertEqual(sorted(summary["auxiliary_dirs_copied"]), ["dist", "node_modules", "servers"])

    def test_destination_inside_plugin_is_not_copied_into_itself(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = self._make_plugin(Path(tmp_dir), {"name": "plug"})
            (plugin / "scripts").mkdir()
            (plugin / "scripts" / "run.sh").write_text("echo ok", encoding="utf-8")

            plugin_dir, summary = convert_plugin(plugin, plugin / "output", overwrite=True)

            self.assertEqual(plugin_dir, (plugin / "output" / "plugins" / "plug").resolve())
            self.assertTrue((plugin_dir / "scripts" / "run.sh").is_file())
            self.assertFalse((plugin_dir / "output").exists())
            self.assertEqual(summary["auxiliary_dirs_copied"], ["scripts"])

    def test_cli_convert_plugin_autodetect(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_plugin = tmp_path / "auto-plugin"
            dest_root = tmp_path / "cli_out"

            (source_plugin / ".claude-plugin").mkdir(parents=True)
            (source_plugin / ".claude-plugin" / "plugin.json").write_text(
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

    def test_root_manifests_do_not_trigger_plugin_mode(self):
        """A web app manifest.json or a root plugin.json is not a Claude Code plugin manifest."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            site = tmp_path / "my-site"
            (site / "docs").mkdir(parents=True)
            (site / "scripts").mkdir()
            (site / "manifest.json").write_text(json.dumps({"name": "My Site"}), encoding="utf-8")
            (site / "plugin.json").write_text(json.dumps({"name": "other-tool"}), encoding="utf-8")

            info = detect_claude_project(site)
            self.assertFalse(info.is_plugin)
            self.assertFalse(info.is_claude_project)

            dest_root = tmp_path / "out"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                exit_code = main(["convert", str(site), "--dest", str(dest_root)])
            self.assertEqual(exit_code, 1)
            self.assertFalse((dest_root / "plugins").exists())

    def test_single_root_manifest_file_is_not_a_plugin(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest = Path(tmp_dir) / "manifest.json"
            manifest.write_text(json.dumps({"name": "My Site"}), encoding="utf-8")
            self.assertFalse(detect_claude_project(manifest).is_claude_project)

            canonical = Path(tmp_dir) / ".claude-plugin" / "plugin.json"
            canonical.parent.mkdir()
            canonical.write_text(json.dumps({"name": "real"}), encoding="utf-8")
            self.assertTrue(detect_claude_project(canonical).is_plugin)


if __name__ == "__main__":
    unittest.main()
