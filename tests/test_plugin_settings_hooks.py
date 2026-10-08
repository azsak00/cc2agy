"""Hooks in a plugin's .claude/settings*.json are not plugin hooks: reported, not converted."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from cc2agy.converters.plugin import convert_plugin
from cc2agy.detector import detect_claude_project

SETTINGS_HOOKS = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo settings"}]}]}}
PLUGIN_HOOKS = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo plugin"}]}]}}


def _make_plugin(root: Path, files: dict) -> Path:
    plugin = root / "plug"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "plug"}), encoding="utf-8")
    for rel, data in files.items():
        (plugin / rel).parent.mkdir(parents=True, exist_ok=True)
        (plugin / rel).write_text(json.dumps(data), encoding="utf-8")
    return plugin


class TestPluginSettingsHooks(unittest.TestCase):
    def test_conversion_reports_settings_hooks_as_not_converted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {
                ".claude/settings.json": SETTINGS_HOOKS,
                ".claude/settings.local.json": SETTINGS_HOOKS,
            })

            plugin_dir, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertFalse((plugin_dir / "hooks.json").exists())
            self.assertEqual(summary["hooks_migrated"], 0)
            for rel in (".claude/settings.json", ".claude/settings.local.json"):
                self.assertTrue(
                    any(w.startswith(rel + " ") and "not converted" in w for w in summary["warnings"]),
                    (rel, summary["warnings"]),
                )

    def test_settings_without_hooks_are_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {".claude/settings.json": {"permissions": {"allow": []}}})

            _, summary = convert_plugin(plugin, tmp_path / "out", overwrite=True)

            self.assertFalse(any("settings.json" in w for w in summary["warnings"]), summary["warnings"])

    def test_inspect_separates_plugin_hooks_from_settings_hooks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = _make_plugin(Path(tmp_dir), {
                "hooks/hooks.json": PLUGIN_HOOKS,
                ".claude/settings.json": SETTINGS_HOOKS,
            })

            summary = detect_claude_project(plugin).summary()

            self.assertIn("Lifecycle Hooks at: hooks.json\n", summary + "\n")
            self.assertIn("settings.json", summary)
            self.assertIn("not converted", summary)


if __name__ == "__main__":
    unittest.main()
