"""Unit tests for source files saved with a UTF-8 BOM (Windows PowerShell 5.1: Set-Content -Encoding utf8)."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cc2agy.cli import main


BOM = b"\xef\xbb\xbf"


def _run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class TestBomSources(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.project = self.root / "proj"
        self.project.mkdir()
        self.dest = self.root / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, relative: str, text: str, root: Path | None = None) -> Path:
        path = (root or self.project) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8-sig")
        return path

    def _convert(self, target: Path) -> tuple[int, str, str]:
        return _run(["convert", str(target), "--dest", str(self.dest)])

    def test_mcp_config_with_bom(self):
        self._write(".mcp.json", json.dumps({"mcpServers": {"docs": {"command": "npx"}}}))
        code, _, err = self._convert(self.project)
        self.assertEqual(code, 0, err)
        mcp = json.loads((self.dest / "mcp_config.json").read_text(encoding="utf-8"))
        self.assertIn("docs", mcp["mcpServers"])

    def test_hooks_file_with_bom(self):
        self._write("hooks.json", json.dumps({"hooks": {"Stop": [{"hooks": [{"command": "echo s"}]}]}}))
        code, _, err = self._convert(self.project)
        self.assertEqual(code, 0, err)
        (group,) = json.loads((self.dest / "hooks.json").read_text(encoding="utf-8")).values()
        self.assertIn("Stop", group)

    def test_plugin_manifest_with_bom(self):
        plugin = self.root / "plug"
        self._write(".claude-plugin/plugin.json", json.dumps({"name": "outro-nome", "description": "Demo"}), plugin)
        code, _, err = self._convert(plugin)
        self.assertEqual(code, 0, err)
        manifest = json.loads((self.dest / "plugins" / "outro-nome" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest, {"name": "outro-nome", "description": "Demo"})

    def test_unreadable_plugin_manifest_is_an_error(self):
        plugin = self.root / "plug"
        self._write(".claude-plugin/plugin.json", '{"name": "outro-nome",}', plugin)
        code, _, err = self._convert(plugin)
        self.assertEqual(code, 1)
        self.assertIn("plugin.json", err)
        self.assertFalse((self.dest / "plugins").exists())

    def test_command_with_bom(self):
        self._write(".claude/commands/revisar.md", "---\ndescription: Revisa o texto\n---\nRevise $ARGUMENTS")
        code, _, err = self._convert(self.project)
        self.assertEqual(code, 0, err)
        skill = (self.dest / "skills" / "revisar" / "SKILL.md").read_bytes()
        self.assertNotIn(BOM, skill)
        self.assertRegex(skill, rb'(?m)^description: "?Revisa o texto"?\r?$')

    def test_agent_with_bom(self):
        self._write(".claude/agents/checker.md", "---\nname: checker\ndescription: Confere\n---\nConfira.")
        code, out, err = self._convert(self.project)
        self.assertEqual(code, 0, err)
        agent = (self.dest / "agents" / "checker.md").read_bytes()
        self.assertNotIn(BOM, agent)
        self.assertRegex(agent, rb'(?m)^description: "?Confere"?\r?$')

    def test_skill_with_bom_is_written_without_it(self):
        self._write("skills/rev/SKILL.md", "---\nname: outro\ndescription: Skill de revisao\n---\nCorpo.")
        code, _, err = self._convert(self.project)
        self.assertEqual(code, 0, err)
        # The frontmatter name is read through the BOM, so the skill takes it (as in Claude Code)
        skill = (self.dest / "skills" / "outro" / "SKILL.md").read_bytes()
        self.assertRegex(skill, rb"\A---\r?\nname: outro\r?\n")

    def test_rules_with_bom_are_written_without_it(self):
        self._write("CLAUDE.md", "# Regras\nSeja preciso.")
        code, _, err = self._convert(self.project)
        self.assertEqual(code, 0, err)
        rules = (self.dest / "AGENTS.md").read_bytes()
        self.assertNotIn(BOM, rules)
        self.assertIn(b"Seja preciso.", rules)


if __name__ == "__main__":
    unittest.main()
