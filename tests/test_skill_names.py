"""A skill takes the name Claude Code gives it: its frontmatter `name`, or its folder name."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cc2agy.converters.plugin import convert_plugin
from cc2agy.converters.skills import migrate_skill_folder, migrate_skills_directory
from cc2agy.detector import detect_claude_project


def _skill(folder: Path, frontmatter: str, body: str = "Corpo.") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}\n", encoding="utf-8")
    return folder


class TestSkillNames(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_skill_takes_its_frontmatter_name(self):
        skill = _skill(self.base / "revisao", "name: revisor\ndescription: d")
        warnings: list[str] = []

        res = migrate_skill_folder(skill, self.base / "out", warnings=warnings)

        self.assertEqual(res.parent.name, "revisor")
        self.assertIn("name: revisor", res.read_text(encoding="utf-8"))
        self.assertTrue(any("revisao" in w and "revisor" in w for w in warnings), warnings)

    def test_skill_without_name_keeps_its_folder_name(self):
        skill = _skill(self.base / "revisao", "description: d")
        warnings: list[str] = []

        res = migrate_skill_folder(skill, self.base / "out", warnings=warnings)

        self.assertEqual(res.parent.name, "revisao")
        self.assertIn("name: revisao", res.read_text(encoding="utf-8"))
        self.assertEqual(warnings, [])

    def test_two_skills_with_the_same_name_are_both_kept(self):
        root = self.base / "skills"
        _skill(root / "a", "name: dup\ndescription: d", "PRIMEIRA")
        _skill(root / "b", "name: dup\ndescription: d", "SEGUNDA")
        warnings: list[str] = []

        results = migrate_skills_directory(root, self.base / "out", warnings=warnings)

        self.assertEqual(sorted(r.parent.name for r in results), ["dup", "dup-2"])
        self.assertIn("PRIMEIRA", (self.base / "out" / "dup" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("SEGUNDA", (self.base / "out" / "dup-2" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertTrue(any("dup-2" in w for w in warnings), warnings)

    def test_plugin_skill_folders_with_the_same_name_are_both_kept_on_overwrite(self):
        plugin = self.base / "plug"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "plug", "skills": ["./extra/"]}), encoding="utf-8"
        )
        _skill(plugin / "skills" / "dup", "name: dup\ndescription: d", "PADRAO")
        _skill(plugin / "extra" / "dup", "name: dup\ndescription: d", "EXTRA")

        plugin_dir, summary = convert_plugin(plugin, self.base / "out", overwrite=True)

        skills = plugin_dir / "skills"
        self.assertEqual(sorted(p.name for p in skills.iterdir()), ["dup", "dup-2"])
        self.assertIn("PADRAO", (skills / "dup" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("EXTRA", (skills / "dup-2" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertTrue(any("dup-2" in w for w in summary["warnings"]))

    def test_inspect_lists_skills_by_the_name_they_will_get(self):
        project = self.base / "proj"
        _skill(project / "skills" / "revisao", "name: revisor\ndescription: d")

        summary = detect_claude_project(project).summary()

        self.assertIn("/revisor", summary)
        self.assertNotIn("/revisao", summary)


if __name__ == "__main__":
    unittest.main()
