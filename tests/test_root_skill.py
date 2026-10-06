"""A SKILL.md at a plugin root, which Claude Code loads as one skill."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cc2agy.converters.plugin import convert_plugin
from cc2agy.detector import detect_claude_project

SKILL = (
    "---\nname: revisor\ndescription: Revisa texto.\n---\n"
    "Leia ${CLAUDE_SKILL_DIR}/references/guia.md e rode ${CLAUDE_PLUGIN_ROOT}/scripts/x.py.\n"
)


def _make_plugin(root: Path, manifest: dict, files: dict) -> Path:
    plugin = root / "meu-plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    for rel, text in files.items():
        (plugin / rel).parent.mkdir(parents=True, exist_ok=True)
        (plugin / rel).write_text(text, encoding="utf-8")
    return plugin


ROOT_FILES = {"SKILL.md": SKILL, "references/guia.md": "guia", "scripts/x.py": "print(1)"}


class TestRootSkill(unittest.TestCase):
    def test_root_skill_is_converted_with_its_frontmatter_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {"name": "plug"}, ROOT_FILES)

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            skill = plugin_dir / "skills" / "revisor" / "SKILL.md"
            self.assertTrue(skill.is_file())
            self.assertEqual(summary["skills_migrated"], 1)
            content = skill.read_text(encoding="utf-8")
            root = plugin_dir.as_posix()
            self.assertIn(f"Leia {root}/references/guia.md e rode {root}/scripts/x.py.", content)
            self.assertIn(f"`{root}`", content)
            self.assertEqual(sorted(p.name for p in (plugin_dir / "skills" / "revisor").iterdir()), ["SKILL.md"])
            self.assertFalse((plugin_dir / "SKILL.md").exists())
            self.assertTrue((plugin_dir / "references" / "guia.md").is_file())

    def test_root_skill_without_name_takes_the_plugin_folder_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {"name": "plug"}, {"SKILL.md": "---\ndescription: d\n---\nFaz algo.\n"})

            plugin_dir, _ = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            skill = plugin_dir / "skills" / "meu-plugin" / "SKILL.md"
            self.assertTrue(skill.is_file())
            self.assertIn("name: meu-plugin", skill.read_text(encoding="utf-8"))

    def test_skills_key_naming_the_root_does_not_copy_the_plugin_into_the_skill(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {"name": "plug", "skills": ["./"]}, ROOT_FILES)

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            skill_dir = plugin_dir / "skills" / "revisor"
            self.assertEqual(sorted(p.name for p in skill_dir.iterdir()), ["SKILL.md"])
            self.assertEqual(sorted(p.name for p in (plugin_dir / "skills").iterdir()), ["revisor"])
            self.assertEqual(summary["skills_migrated"], 1)

    def test_root_skill_next_to_skills_folder_is_not_converted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {"name": "plug"}, {
                **ROOT_FILES,
                "skills/outra/SKILL.md": "---\nname: outra\ndescription: d\n---\nOutra.\n",
            })

            plugin_dir, _ = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertEqual(sorted(p.name for p in (plugin_dir / "skills").iterdir()), ["outra"])

    def test_inspect_follows_claude_code_for_a_plugin_root_skill(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {"name": "plug"}, {
                **ROOT_FILES,
                "skills/outra/SKILL.md": "---\nname: outra\ndescription: d\n---\nOutra.\n",
            })

            info = detect_claude_project(plugin)

            self.assertEqual(info.skills_dir, (plugin / "skills").resolve())


if __name__ == "__main__":
    unittest.main()
