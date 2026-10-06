"""Unit tests for Claude Code subagent conversion to Antigravity custom subagents."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cc2agy.cli import main
from cc2agy.converters.agents import convert_agent_text, parse_agent_frontmatter
from cc2agy.converters.plugin import convert_plugin


def _convert(content: str, dest: Path, plugin_name=None, subfolders=None):
    warnings: list = []
    result = convert_agent_text(
        content, "agent.md", dest, {}, warnings, plugin_name=plugin_name, subfolders=subfolders
    )
    return result, warnings


class TestAgentConverter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dest = Path(self._tmp.name) / "agents"

    def tearDown(self):
        self._tmp.cleanup()

    def test_tools_and_model_are_translated(self):
        result, warnings = _convert(
            "---\nname: reviewer\ndescription: Reviews code\ntools: Read, Grep, Bash, NotebookEdit\n"
            "model: sonnet\n---\n\nYou review code.\n",
            self.dest,
        )
        content = result.read_text(encoding="utf-8")
        meta, body = parse_agent_frontmatter(content)
        self.assertEqual(result.name, "reviewer.md")
        self.assertEqual(meta["name"], "reviewer")
        self.assertEqual(meta["description"], "Reviews code")
        self.assertEqual(meta["tools"], ["view_file", "grep_search", "run_command"])
        self.assertEqual(meta["model"], "pro")
        self.assertEqual(body, "You review code.")
        self.assertTrue(any("NotebookEdit" in w for w in warnings))

    def test_model_tiers(self):
        for model, tier in (("haiku", "flash"), ("inherit", "inherit"), ("claude-opus-5-5", "pro"), ("fable", "pro")):
            result, _ = _convert(f"---\nname: m\ndescription: d\nmodel: {model}\n---\nx", self.dest)
            self.assertEqual(parse_agent_frontmatter(result.read_text(encoding="utf-8"))[0]["model"], tier)
            result.unlink()

    def test_unknown_model_is_left_out_with_warning(self):
        result, warnings = _convert("---\nname: m\ndescription: d\nmodel: gpt-9\n---\nx", self.dest)
        self.assertNotIn("model", parse_agent_frontmatter(result.read_text(encoding="utf-8"))[0])
        self.assertTrue(any("gpt-9" in w for w in warnings))

    def test_tools_as_yaml_lists(self):
        for tools in ("tools:\n  - Edit\n  - Glob", "tools:\n- Edit\n- Glob", "tools: [Edit, Glob]"):
            result, _ = _convert(f"---\nname: t\ndescription: d\n{tools}\n---\nx", self.dest)
            meta, _ = parse_agent_frontmatter(result.read_text(encoding="utf-8"))
            self.assertEqual(
                meta["tools"], ["replace_file_content", "multi_replace_file_content", "find_by_name", "list_dir"]
            )
            result.unlink()

    def test_disallowed_tools_alone_become_an_allowlist(self):
        result, warnings = _convert(
            "---\nname: no-writes\ndescription: d\ndisallowedTools: Write, Edit\n---\nx", self.dest
        )
        tools = parse_agent_frontmatter(result.read_text(encoding="utf-8"))[0]["tools"]
        self.assertIn("view_file", tools)
        self.assertIn("run_command", tools)
        for denied in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
            self.assertNotIn(denied, tools)
        self.assertTrue(any("allowlist" in w for w in warnings))

    def test_disallowed_tools_are_removed_from_tools(self):
        result, _ = _convert(
            "---\nname: t\ndescription: d\ntools: Read, Bash\ndisallowedTools: Bash(git push *)\n---\nx", self.dest
        )
        self.assertEqual(parse_agent_frontmatter(result.read_text(encoding="utf-8"))[0]["tools"], ["view_file"])

    def test_tools_without_any_equivalent_are_left_out_with_warning(self):
        result, warnings = _convert("---\nname: t\ndescription: d\ntools: mcp__github, TodoWrite\n---\nx", self.dest)
        self.assertNotIn("tools", parse_agent_frontmatter(result.read_text(encoding="utf-8"))[0])
        self.assertTrue(any("mcp__github" in w for w in warnings))
        self.assertTrue(any("no listed tool" in w for w in warnings))

    def test_missing_tools_stay_missing(self):
        result, warnings = _convert("---\nname: t\ndescription: d\n---\nx", self.dest)
        self.assertNotIn("tools", parse_agent_frontmatter(result.read_text(encoding="utf-8"))[0])
        self.assertEqual(warnings, [])

    def test_skills_and_unsupported_fields(self):
        result, warnings = _convert(
            "---\nname: t\ndescription: d\nskills:\n  - api-conventions\ncolor: blue\npermissionMode: plan\n"
            "hooks:\n  PreToolUse:\n    - matcher: Bash\nmaxTurns: 5\n---\nx",
            self.dest,
        )
        content = result.read_text(encoding="utf-8")
        meta, _ = parse_agent_frontmatter(content)
        self.assertEqual(meta["skills"], ["skills/api-conventions"])
        self.assertNotIn("PreToolUse", content)
        dropped = [w for w in warnings if "dropped" in w]
        self.assertEqual(len(dropped), 1)
        for field in ("color", "permissionMode", "hooks", "maxTurns"):
            self.assertIn(field, dropped[0])

    def test_project_agent_without_name_or_description_is_skipped(self):
        result, warnings = _convert("---\ndescription: d\n---\nx", self.dest)
        self.assertIsNone(result)
        result, warnings2 = _convert("---\nname: t\n---\nx", self.dest)
        self.assertIsNone(result)
        result, warnings3 = _convert("Just documentation.", self.dest)
        self.assertIsNone(result)
        self.assertEqual(len(warnings + warnings2 + warnings3), 3)
        self.assertFalse(self.dest.exists() and any(self.dest.iterdir()))

    def test_plugin_agent_name_rules(self):
        result, _ = _convert("---\nname: audit\ndescription: d\n---\nx", self.dest, "plug", ["review"])
        self.assertEqual(result.name, "review-audit.md")
        result, _ = _convert("No frontmatter at all.", self.dest, "plug", ["review"])
        self.assertEqual(result.name, "review-agent.md")
        meta, body = parse_agent_frontmatter(result.read_text(encoding="utf-8"))
        self.assertEqual(meta["description"], "Agent from plug plugin")
        self.assertEqual(body, "No frontmatter at all.")


class TestAgentsInPlugin(unittest.TestCase):
    def _make_plugin(self, root: Path, manifest: dict) -> Path:
        plugin = root / "plug"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        return plugin

    def test_plugin_agents_are_converted_not_copied(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {"name": "plug"})
            (plugin / "agents" / "review").mkdir(parents=True)
            (plugin / "agents" / "reviewer.md").write_text(
                "---\nname: reviewer\ndescription: Reviews\ntools: Read, Bash\n---\n"
                "Run ${CLAUDE_PLUGIN_ROOT}/scripts/check.py\n",
                encoding="utf-8",
            )
            (plugin / "agents" / "review" / "security.md").write_text(
                "---\ndescription: Security\n---\nCheck secrets.\n", encoding="utf-8"
            )

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            agents = plugin_dir / "agents"
            self.assertEqual(sorted(p.name for p in agents.rglob("*")), ["review-security.md", "reviewer.md"])
            content = (agents / "reviewer.md").read_text(encoding="utf-8")
            self.assertIn("  - view_file", content)
            self.assertNotIn("Read", content)
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", content)
            self.assertIn(f"{plugin_dir.as_posix()}/scripts/check.py", content)
            self.assertEqual(summary["agents_migrated"], 2)
            self.assertNotIn("agents", summary["auxiliary_dirs_copied"])

    def test_manifest_agents_replace_default_folder(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(
                tmp_path, {"name": "plug", "agents": ["./custom/review/security.md", "./custom/"]}
            )
            (plugin / "agents").mkdir()
            (plugin / "agents" / "default.md").write_text("---\nname: default\ndescription: d\n---\nx", encoding="utf-8")
            (plugin / "custom" / "review").mkdir(parents=True)
            (plugin / "custom" / "review" / "security.md").write_text(
                "---\ndescription: Security\n---\nx", encoding="utf-8"
            )

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertEqual([p.name for p in (plugin_dir / "agents").iterdir()], ["security.md"])
            self.assertTrue(any("'./custom/'" in w for w in summary["warnings"]))

    def test_plugin_agents_with_same_name_keep_both(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = self._make_plugin(tmp_path, {"name": "plug"})
            (plugin / "agents").mkdir()
            (plugin / "agents" / "a.md").write_text("---\nname: dup\ndescription: d\n---\nFROM A", encoding="utf-8")
            (plugin / "agents" / "b.md").write_text("---\nname: dup\ndescription: d\n---\nFROM B", encoding="utf-8")

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertIn("FROM A", (plugin_dir / "agents" / "dup.md").read_text(encoding="utf-8"))
            self.assertIn("FROM B", (plugin_dir / "agents" / "dup-2.md").read_text(encoding="utf-8"))
            self.assertTrue(any("dup-2" in w for w in summary["warnings"]))


class TestAgentsInFolderMode(unittest.TestCase):
    def test_cli_converts_project_agents(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            agents = root / ".claude" / "agents"
            (agents / "review").mkdir(parents=True)
            (agents / "review" / "security.md").write_text(
                "---\nname: sec\ndescription: Security\ntools: Grep\n---\nx", encoding="utf-8"
            )
            (agents / "notes.md").write_text("# Notes about our agents", encoding="utf-8")
            out_dir = root / "out"

            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                inspect_code = main(["inspect", str(root)])
                code = main(["convert", str(root), "--dest", str(out_dir)])
            output = stdout.getvalue() + stderr.getvalue()

            self.assertEqual(inspect_code, 0)
            self.assertEqual(code, 0)
            self.assertIn("Subagents (2 files", output)
            self.assertEqual([p.name for p in (out_dir / "agents").iterdir()], ["sec.md"])
            self.assertIn("  - grep_search", (out_dir / "agents" / "sec.md").read_text(encoding="utf-8"))
            self.assertIn("notes.md", output)
            self.assertIn("1 subagent(s)", output)


if __name__ == "__main__":
    unittest.main()
