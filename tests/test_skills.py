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

    def test_migrate_skill_rename_preserves_other_frontmatter(self):
        """Renaming must touch only the 'name' line: lists and colon values stay intact."""
        skill_src = self.base / "My_Skill"
        skill_src.mkdir()
        original = (
            "---\n"
            "name: Old_Name\n"
            "description: \"Use when: reviewing a brief\"\n"
            "allowed-tools:\n"
            "  - Bash(git add:*)\n"
            "  - Read\n"
            "metadata:\n"
            "  name: nested-value\n"
            "---\n\n"
            "# Body\n"
        )
        (skill_src / "SKILL.md").write_text(original, encoding="utf-8")

        res = migrate_skill_folder(skill_src, self.base / "out")
        content = res.read_text(encoding="utf-8")

        self.assertEqual(content, original.replace("name: Old_Name", "name: my-skill", 1))

    def test_migrate_skill_inserts_missing_name_and_keeps_crlf(self):
        skill_src = self.base / "tool-x"
        skill_src.mkdir()
        (skill_src / "SKILL.md").write_bytes(b"---\r\ndescription: Desc\r\n---\r\nBody\r\n")

        res = migrate_skill_folder(skill_src, self.base / "out")

        self.assertEqual(res.read_bytes(), b"---\r\nname: tool-x\r\ndescription: Desc\r\n---\r\nBody\r\n")

    def test_migrate_skill_same_source_and_dest_is_refused(self):
        """Converting a skill onto itself with overwrite must never delete the source."""
        skills_root = self.base / ".agents" / "skills"
        skill_src = skills_root / "my-skill"
        skill_src.mkdir(parents=True)
        (skill_src / "SKILL.md").write_text("---\nname: my-skill\n---\nKeep me", encoding="utf-8")

        with self.assertRaises(ValueError):
            migrate_skill_folder(skill_src, skills_root, overwrite=True)
        with self.assertRaises(ValueError):
            migrate_skills_directory(skill_src, skills_root, overwrite=True)

        self.assertEqual((skill_src / "SKILL.md").read_text(encoding="utf-8"), "---\nname: my-skill\n---\nKeep me")

    def test_single_skill_md_file_migrates_whole_folder(self):
        """Pointing the CLI at a SKILL.md migrates its folder, not a command copy of the file."""
        skill = self.base / "reviewer"
        (skill / "references").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: reviewer\ndescription: Reviews briefs\n---\nSee references/guide.md\n",
            encoding="utf-8",
        )
        (skill / "references" / "guide.md").write_text("Guide", encoding="utf-8")

        info = detect_claude_project(skill / "SKILL.md")
        self.assertEqual(info.command_files, [])
        self.assertEqual(info.skills_dir, skill.resolve())

        dest = self.base / "out"
        ret = main(["convert", str(skill / "SKILL.md"), "--dest", str(dest)])

        self.assertEqual(ret, 0)
        self.assertTrue((dest / "skills" / "reviewer" / "references" / "guide.md").exists())
        self.assertEqual(
            (dest / "skills" / "reviewer" / "SKILL.md").read_text(encoding="utf-8"),
            (skill / "SKILL.md").read_text(encoding="utf-8"),
        )

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
