"""A plugin skill whose 'name' already carries the plugin's own prefix ('meu-plugin:fancy')
loses it, as Claude Code does not add the prefix again."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cc2agy.converters.plugin import convert_plugin
from cc2agy.converters.skills import migrate_skills_directory
from cc2agy.detector import detect_claude_project


def _write_skill(folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\ncorpo\n", encoding="utf-8")


def _make_plugin(root: Path) -> Path:
    plugin = root / "meu-plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "meu-plugin"}), encoding="utf-8")
    return plugin


class TestSkillPrefix(unittest.TestCase):
    def test_skills_folder_name_with_plugin_prefix(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path)
            _write_skill(plugin / "skills" / "revisao", "meu-plugin:fancy")

            plugin_dir, _ = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            skill_file = plugin_dir / "skills" / "fancy" / "SKILL.md"
            self.assertTrue(skill_file.exists(), sorted(p.name for p in (plugin_dir / "skills").iterdir()))
            self.assertIn("name: fancy\n", skill_file.read_text(encoding="utf-8"))

    def test_root_skill_name_with_plugin_prefix(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path)
            _write_skill(plugin, "meu-plugin:fancy")

            plugin_dir, _ = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertTrue((plugin_dir / "skills" / "fancy" / "SKILL.md").exists())

    def test_other_prefix_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path)
            _write_skill(plugin / "skills" / "revisao", "outro:fancy")

            plugin_dir, _ = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertTrue((plugin_dir / "skills" / "outrofancy" / "SKILL.md").exists())

    def test_outside_a_plugin_nothing_changes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            _write_skill(tmp_path / "skills" / "revisao", "meu-plugin:fancy")

            results = migrate_skills_directory(tmp_path / "skills", tmp_path / "out")

            self.assertEqual([r.parent.name for r in results], ["meu-pluginfancy"])

    def test_inspect_lists_skill_without_prefix(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = _make_plugin(Path(tmp_dir))
            _write_skill(plugin / "skills" / "revisao", "meu-plugin:fancy")

            summary = detect_claude_project(plugin).summary()

            self.assertIn("/fancy\n", summary + "\n")
            self.assertNotIn("meu-pluginfancy", summary)


if __name__ == "__main__":
    unittest.main()
