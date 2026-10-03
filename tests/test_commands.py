"""Unit tests for Claude Code command conversion, project detection, and CLI."""

import tempfile
import unittest
from pathlib import Path

from src.cc2agy.cli import main
from src.cc2agy.converters.commands import (
    adapt_prompt_arguments,
    convert_command_file,
    convert_commands_directory,
    escape_yaml_string,
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

    def test_sanitize_skill_name_accents(self):
        """Ensure accented/diacritical characters are transliterated to ASCII base."""
        self.assertEqual(sanitize_skill_name("validação"), "validacao")
        self.assertEqual(sanitize_skill_name("revisão_rápida"), "revisao-rapida")
        self.assertEqual(sanitize_skill_name("ação judicial"), "acao-judicial")

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

    def test_parse_frontmatter_multiline_scalars(self):
        """Test YAML folded (>-) and literal (|) multiline block scalars."""
        content_folded = (
            "---\n"
            "description: >-\n"
            "  Generates standardized commit messages\n"
            "  following conventional commit standards.\n"
            "---\n\n"
            "Prompt body."
        )
        meta_folded, _ = parse_frontmatter(content_folded)
        self.assertEqual(
            meta_folded.get("description"),
            "Generates standardized commit messages following conventional commit standards."
        )

        content_literal = (
            "---\n"
            "description: |\n"
            "  Line 1.\n"
            "  Line 2.\n"
            "---\n\n"
            "Prompt body."
        )
        meta_literal, _ = parse_frontmatter(content_literal)
        self.assertEqual(meta_literal.get("description"), "Line 1.\nLine 2.")

    def test_escape_yaml_string(self):
        self.assertEqual(
            escape_yaml_string('Executes test with "smoke" tag'),
            'Executes test with \\"smoke\\" tag'
        )

    def test_extract_description_sources(self):
        desc = extract_description("Body text", {"description": "Meta description"}, "cmd")
        self.assertEqual(desc, "Meta description")

        desc2 = extract_description("# Optimize Database Query\nBody", {}, "optimize-db")
        self.assertIn("Optimize Database Query", desc2)

        desc3 = extract_description("Analyzes git diff for breaking changes.", {}, "diff")
        self.assertEqual(desc3, "Analyzes git diff for breaking changes.")

    def test_adapt_prompt_arguments(self):
        prompt = "Run test on file $1 with extra flags $ARGUMENTS"
        adapted = adapt_prompt_arguments(prompt)
        self.assertIn("[Argument 1 provided by user]", adapted)
        self.assertIn("[User Arguments provided after the slash command]", adapted)
        self.assertIn("migrated from a Claude Code slash command", adapted)

    def test_adapt_prompt_arguments_protection(self):
        """Ensure monetary values ($50) and code blocks are not corrupted."""
        prompt = (
            "The budget is $50 USD and $100 EUR.\n"
            "Run script: `awk '{print $1}' input.txt`\n"
            "```bash\necho $1 and $ARGUMENTS\n```\n"
            "Apply user argument $1 now."
        )
        adapted = adapt_prompt_arguments(prompt)

        # Monetary values intact
        self.assertIn("$50 USD", adapted)
        self.assertIn("$100 EUR", adapted)

        # Code blocks intact
        self.assertIn("awk '{print $1}' input.txt", adapted)
        self.assertIn("echo $1 and $ARGUMENTS", adapted)

        # Legitimate outside parameter adapted
        self.assertIn("Apply user argument [Argument 1 provided by user] now.", adapted)

    def test_convert_single_command_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "review-pr.md"
            source_file.write_text(
                "---\n"
                "description: Review a PR with \"strict\" mode\n"
                "---\n\n"
                "Please review the PR diff carefully for security issues.",
                encoding="utf-8"
            )

            skills_output_dir = tmp_path / "skills"
            skill_md = convert_command_file(source_file, skills_output_dir)

            self.assertTrue(skill_md.exists())
            self.assertEqual(skill_md.parent.name, "review-pr")

            content = skill_md.read_text(encoding="utf-8")
            self.assertIn("name: review-pr", content)
            self.assertIn('description: "Review a PR with \\"strict\\" mode"', content)

    def test_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "deploy.md"
            source_file.write_text("Deploy command", encoding="utf-8")

            skills_output_dir = tmp_path / "skills"
            # First conversion succeeds
            convert_command_file(source_file, skills_output_dir, overwrite=False)

            # Second conversion without overwrite raises FileExistsError
            with self.assertRaises(FileExistsError):
                convert_command_file(source_file, skills_output_dir, overwrite=False)

            # Conversion with overwrite=True succeeds
            convert_command_file(source_file, skills_output_dir, overwrite=True)

    def test_convert_commands_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            cmd_dir = tmp_path / "commands"
            cmd_dir.mkdir()

            (cmd_dir / "commit.md").write_text("# Generate Commit Message\nCreate commit.", encoding="utf-8")
            sub_dir = cmd_dir / "git"
            sub_dir.mkdir()
            (sub_dir / "push.md").write_text("# Push Code\nPush code.", encoding="utf-8")

            skills_dir = tmp_path / "skills"
            converted = convert_commands_directory(cmd_dir, skills_dir, overwrite=True)

            self.assertEqual(len(converted), 2)
            self.assertTrue((skills_dir / "commit" / "SKILL.md").exists())
            self.assertTrue((skills_dir / "push" / "SKILL.md").exists())


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

    def test_detect_linux_case_insensitivity_and_claude_json(self):
        """Check discovery of lowercase claude.md and .claude.json."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "claude.md").write_text("Rules lowercase", encoding="utf-8")
            (root / ".claude.json").write_text("{}", encoding="utf-8")

            info = detect_claude_project(root)
            self.assertTrue(info.has_rules)
            self.assertEqual(info.rules_file.name.lower(), "claude.md")
            self.assertTrue(info.has_mcp)
            self.assertEqual(info.mcp_file.name, ".claude.json")


class TestCLI(unittest.TestCase):

    def test_cli_inspect_and_convert(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cmd_dir = root / "commands"
            cmd_dir.mkdir()
            (cmd_dir / "test.md").write_text("Test CLI command", encoding="utf-8")

            # Inspect command
            exit_code = main(["inspect", str(root)])
            self.assertEqual(exit_code, 0)

            # Convert command
            out_dir = root / "out"
            exit_code_convert = main(["convert", str(root), "--dest", str(out_dir)])
            self.assertEqual(exit_code_convert, 0)
            self.assertTrue((out_dir / "skills" / "test" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
