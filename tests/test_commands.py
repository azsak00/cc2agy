"""Unit tests for Claude Code command conversion and project detection."""

import tempfile
import unittest
from pathlib import Path

from src.cc2agy.converters.commands import (
    adapt_prompt_arguments,
    convert_command_file,
    convert_commands_directory,
    extract_description,
    parse_frontmatter,
    sanitize_skill_name,
)
from src.cc2agy.detector import detect_claude_project


class TestCommandsConverter(unittest.TestCase):

    def test_sanitize_skill_name(self):
        self.assertEqual(sanitize_skill_name("commit_message"), "commit-message")
        self.assertEqual(sanitize_skill_name("Review PR"), "review-pr")
        self.assertEqual(sanitize_skill_name("  --Deploy__App--  "), "deploy-app")
        self.assertEqual(sanitize_skill_name("special@#chars!"), "specialchars")
        self.assertEqual(sanitize_skill_name(""), "custom-command")

    def test_parse_frontmatter_with_yaml(self):
        content = (
            "---\n"
            "name: test-cmd\n"
            "description: A test command\n"
            "---\n\n"
            "# Heading\n\nPrompt body goes here."
        )
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta.get("name"), "test-cmd")
        self.assertEqual(meta.get("description"), "A test command")
        self.assertIn("# Heading", body)
        self.assertNotIn("---", body)

    def test_parse_frontmatter_without_yaml(self):
        content = "# Heading\n\nPure markdown body."
        meta, body = parse_frontmatter(content)
        self.assertEqual(meta, {})
        self.assertEqual(body, content)

    def test_extract_description_sources(self):
        # 1. From metadata
        desc = extract_description("Body text", {"description": "Meta description"}, "cmd")
        self.assertEqual(desc, "Meta description")

        # 2. From heading
        desc2 = extract_description("# Optimize Database Query\nBody", {}, "optimize-db")
        self.assertIn("Optimize Database Query", desc2)

        # 3. From first paragraph
        desc3 = extract_description("Analyzes git diff for breaking changes.", {}, "diff")
        self.assertEqual(desc3, "Analyzes git diff for breaking changes.")

    def test_adapt_prompt_arguments(self):
        prompt = "Run test on file $1 with extra flags $ARGUMENTS"
        adapted = adapt_prompt_arguments(prompt)
        self.assertIn("[Argument 1 provided by user]", adapted)
        self.assertIn("[User Arguments provided after the slash command]", adapted)
        self.assertIn("migrated from a Claude Code slash command", adapted)

    def test_convert_single_command_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "review-pr.md"
            source_file.write_text(
                "---\n"
                "description: Review a pull request against guidelines\n"
                "---\n\n"
                "Please review the PR diff carefully for security issues.",
                encoding="utf-8"
            )

            skills_output_dir = tmp_path / "skills"
            skill_md = convert_command_file(source_file, skills_output_dir)

            self.assertTrue(skill_md.exists())
            self.assertEqual(skill_md.parent.name, "review-pr")
            self.assertEqual(skill_md.name, "SKILL.md")

            content = skill_md.read_text(encoding="utf-8")
            self.assertIn("name: review-pr", content)
            self.assertIn("description: \"Review a pull request against guidelines\"", content)
            self.assertIn("Please review the PR diff carefully", content)

    def test_convert_commands_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            cmd_dir = tmp_path / "commands"
            cmd_dir.mkdir()

            (cmd_dir / "commit.md").write_text("# Generate Commit Message\nCreate commit.", encoding="utf-8")
            (cmd_dir / "explain_code.md").write_text("# Explain\nExplains code.", encoding="utf-8")

            skills_dir = tmp_path / "skills"
            converted = convert_commands_directory(cmd_dir, skills_dir)

            self.assertEqual(len(converted), 2)
            self.assertTrue((skills_dir / "commit" / "SKILL.md").exists())
            self.assertTrue((skills_dir / "explain-code" / "SKILL.md").exists())


class TestDetector(unittest.TestCase):

    def test_detect_claude_structure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cmd_dir = root / "commands"
            cmd_dir.mkdir()
            (cmd_dir / "test.md").write_text("Test", encoding="utf-8")
            (root / "CLAUDE.md").write_text("Rules", encoding="utf-8")
            (root / ".mcp.json").write_text("{}", encoding="utf-8")

            info = detect_claude_project(root)

            self.assertTrue(info.is_claude_project)
            self.assertTrue(info.has_commands)
            self.assertTrue(info.has_rules)
            self.assertTrue(info.has_mcp)
            self.assertEqual(len(info.command_files), 1)
            self.assertIn("Commands (1 files)", info.summary())


if __name__ == "__main__":
    unittest.main()
