"""Unit tests for modular Skills migration and synchronization in cc2agy."""

import tempfile
import unittest
from pathlib import Path

import sys
ROOT_DIR = str(Path(__file__).resolve().parent.parent)
SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")

while ROOT_DIR in sys.path:
    sys.path.remove(ROOT_DIR)
while "" in sys.path:
    sys.path.remove("")

if SRC_DIR in sys.path:
    sys.path.remove(SRC_DIR)
sys.path.insert(0, SRC_DIR)

from cc2agy.cli import main
from cc2agy.converters.skills import migrate_skill_folder, migrate_skills_directory
from cc2agy.detector import detect_claude_project


class TestSkillsMigrator(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_migrate_single_skill_folder(self):
        skill_src = self.base / "build-mcp"
        skill_src.mkdir()
        (skill_src / "SKILL.md").write_text(
            "---\nname: build-mcp\ndescription: Test description\n---\n\n# Body\nContent",
            encoding="utf-8"
        )
        refs = skill_src / "references"
        refs.mkdir()
        (refs / "guide.md").write_text("Reference content", encoding="utf-8")

        dest = self.base / "out_skills"
        res = migrate_skill_folder(skill_src, dest)

        self.assertTrue(res.exists())
        self.assertEqual(res.parent.name, "build-mcp")
        self.assertTrue((dest / "build-mcp" / "references" / "guide.md").exists())
        self.assertEqual(
            (dest / "build-mcp" / "references" / "guide.md").read_text(encoding="utf-8"),
            "Reference content"
        )

    def test_migrate_skills_directory_multiple(self):
        skills_root = self.base / "skills"
        skills_root.mkdir()

        skill_a = skills_root / "skill-a"
        skill_a.mkdir()
        (skill_a / "SKILL.md").write_text(
            "---\nname: skill-a\ndescription: Skill A\n---\n\n# Skill A",
            encoding="utf-8"
        )

        skill_b = skills_root / "skill-b"
        skill_b.mkdir()
        (skill_b / "SKILL.md").write_text(
            "---\nname: skill-b\ndescription: Skill B\n---\n\n# Skill B",
            encoding="utf-8"
        )

        dest = self.base / "out_dest"
        results = migrate_skills_directory(skills_root, dest)

        self.assertEqual(len(results), 2)
        names = {r.parent.name for r in results}
        self.assertEqual(names, {"skill-a", "skill-b"})

    def test_migrate_skill_overwrite_protection(self):
        skill_src = self.base / "my-skill"
        skill_src.mkdir()
        (skill_src / "SKILL.md").write_text("---\nname: my-skill\n---\nOriginal", encoding="utf-8")

        dest = self.base / "out"
        migrate_skill_folder(skill_src, dest)

        # Re-attempt without overwrite
        with self.assertRaises(FileExistsError):
            migrate_skill_folder(skill_src, dest, overwrite=False)

        # Attempt with overwrite
        (skill_src / "SKILL.md").write_text("---\nname: my-skill\n---\nUpdated", encoding="utf-8")
        res = migrate_skill_folder(skill_src, dest, overwrite=True)
        self.assertIn("Updated", res.read_text(encoding="utf-8"))

    def test_migrate_skill_name_frontmatter_normalization(self):
        # Folder is named 'My_Plugin_Skill' which sanitizes to 'my-plugin-skill'
        skill_src = self.base / "My_Plugin_Skill"
        skill_src.mkdir()
        (skill_src / "SKILL.md").write_text(
            "---\nname: old-mismatched-name\ndescription: Some desc\n---\n\n# Body",
            encoding="utf-8"
        )

        dest = self.base / "out"
        res = migrate_skill_folder(skill_src, dest)

        self.assertEqual(res.parent.name, "my-plugin-skill")
        content = res.read_text(encoding="utf-8")
        self.assertIn("name: my-plugin-skill", content)

    def test_cli_convert_modular_skills(self):
        plugin_root = self.base / "mcp-server-dev"
        plugin_root.mkdir()
        skills_folder = plugin_root / "skills"
        skills_folder.mkdir()

        skill1 = skills_folder / "tool-a"
        skill1.mkdir()
        (skill1 / "SKILL.md").write_text("---\nname: tool-a\ndescription: Desc A\n---\nBody", encoding="utf-8")

        dest = self.base / "cli_out"
        ret = main(["convert", str(plugin_root), "--dest", str(dest)])
        self.assertEqual(ret, 0)
        self.assertTrue((dest / "skills" / "tool-a" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
