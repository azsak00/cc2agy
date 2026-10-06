"""Unit tests for argument placeholders and variables in modular skills (SKILL.md)."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cc2agy.cli import main
from cc2agy.converters.skills import migrate_skill_folder


def _run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class TestSkillArguments(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.dest = self.root / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def _skill(self, body: str, frontmatter: str = "name: fix\ndescription: Fixes an issue\n",
               folder: Path | None = None) -> Path:
        skill = (folder or self.root / "src") / "fix"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8", newline="")
        return skill

    def test_placeholders_follow_claude_code(self):
        skill = self._skill(
            "Fix issue $issue on $branch.\nAll: $ARGUMENTS. First: $0. Second: $ARGUMENTS[1].\n"
            "Costs \\$1.00, not $50.\n`echo $1`\n",
            "name: fix\ndescription: Fixes an issue\narguments: [issue, branch]\n",
        )
        result = migrate_skill_folder(skill, self.dest).read_text(encoding="utf-8")
        self.assertTrue(result.startswith("---\nname: fix\ndescription: Fixes an issue\narguments: [issue, branch]\n---\n"))
        self.assertIn("Fix issue [Argument 1 ('issue') provided by user] on [Argument 2 ('branch') provided by user].", result)
        self.assertIn("All: [User Arguments provided after the slash command].", result)
        self.assertIn("First: [Argument 1 provided by user]. Second: [Argument 2 provided by user].", result)
        self.assertIn("Costs $1.00, not $50.", result)
        self.assertIn("`echo $1`", result)
        self.assertIn("migrated from a Claude Code skill", result)

    def test_skill_without_placeholders_is_left_as_is(self):
        body = "# Review\nRead the diff and report problems.\n"
        skill = self._skill(body)
        result = migrate_skill_folder(skill, self.dest).read_text(encoding="utf-8")
        self.assertEqual(result, "---\nname: fix\ndescription: Fixes an issue\n---\n" + body)

    def test_skill_dir_becomes_the_converted_folder(self):
        skill = self._skill("Run `python ${CLAUDE_SKILL_DIR}/scripts/run.py` and read $CLAUDE_SKILL_DIR/references/a.md.\n")
        result = migrate_skill_folder(skill, self.dest).read_text(encoding="utf-8")
        target = (self.dest / "fix").as_posix()
        self.assertIn(f"`python {target}/scripts/run.py`", result)
        self.assertIn(f"read {target}/references/a.md.", result)

    def test_project_dir_and_variables_without_equivalent(self):
        skill = self._skill("Open ${CLAUDE_PROJECT_DIR}/README.md. Log to ${CLAUDE_SESSION_ID}.log at ${CLAUDE_EFFORT}.\n")
        warnings: list[str] = []
        result = migrate_skill_folder(skill, self.dest, warnings=warnings).read_text(encoding="utf-8")
        self.assertIn("Open ./README.md.", result)
        self.assertIn("${CLAUDE_SESSION_ID}.log at ${CLAUDE_EFFORT}.", result)
        self.assertTrue(any("CLAUDE_SESSION_ID" in w for w in warnings), warnings)
        self.assertTrue(any("CLAUDE_EFFORT" in w for w in warnings), warnings)

    def test_folder_and_plugin_modes_adapt_skills_and_show_warnings(self):
        project = self.root / "proj"
        self._skill("Use $ARGUMENTS at ${CLAUDE_EFFORT}.\n", folder=project / "skills")
        code, out, err = _run(["convert", str(project), "--dest", str(self.dest)])
        self.assertEqual(code, 0, err)
        self.assertIn("[User Arguments provided after the slash command]",
                      (self.dest / "skills" / "fix" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("CLAUDE_EFFORT", out)

        plugin = self.root / "plug"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "plug"}), encoding="utf-8")
        self._skill("Run ${CLAUDE_SKILL_DIR}/x.py with $0 at ${CLAUDE_EFFORT}.\n", folder=plugin / "skills")
        plugin_dest = self.root / "pout"
        code, out, err = _run(["convert", str(plugin), "--dest", str(plugin_dest)])
        self.assertEqual(code, 0, err)
        skill_dir = plugin_dest / "plugins" / "plug" / "skills" / "fix"
        result = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(f"Run {skill_dir.as_posix()}/x.py with [Argument 1 provided by user]", result)
        self.assertIn("CLAUDE_EFFORT", out)


if __name__ == "__main__":
    unittest.main()
