"""A folder conversion reports every skill, command and subagent it skips because it already exists."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from cc2agy.cli import main


def _run(args: list[str]) -> str:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        main(args)
    return out.getvalue() + err.getvalue()


def _make_project(root: Path) -> Path:
    project = root / "proj"
    files = {
        "skills/s1/SKILL.md": "---\nname: s1\ndescription: d\n---\nS1\n",
        "commands/c1.md": "---\ndescription: c\n---\nC\n",
        ".claude/agents/a1.md": "---\nname: a1\ndescription: d\n---\nA\n",
    }
    for rel, text in files.items():
        (project / rel).parent.mkdir(parents=True, exist_ok=True)
        (project / rel).write_text(text, encoding="utf-8")
    return project


class TestSkippedItems(unittest.TestCase):
    def test_second_conversion_reports_each_skipped_item(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            project = _make_project(tmp_path)
            dest = tmp_path / "out"
            _run(["convert", str(project), "--dest", str(dest)])

            output = _run(["convert", str(project), "--dest", str(dest)])

            self.assertIn("Skipped existing skill from s1/", output)
            self.assertIn("Skipped existing skill from command c1.md", output)
            self.assertIn("Skipped existing subagent from a1.md", output)
            self.assertEqual(output.count("use --overwrite to replace"), 3, output)

    def test_overwrite_reports_nothing_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            project = _make_project(tmp_path)
            dest = tmp_path / "out"
            _run(["convert", str(project), "--dest", str(dest)])

            output = _run(["convert", str(project), "--dest", str(dest), "--overwrite"])

            self.assertNotIn("Skipped existing", output)
            self.assertIn("2 skill(s)", output)
            self.assertIn("1 subagent(s)", output)


if __name__ == "__main__":
    unittest.main()
