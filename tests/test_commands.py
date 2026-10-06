"""Unit tests for Claude Code command conversion, project detection, and CLI."""

import contextlib
import io
import json
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
from cc2agy.converters.commands import (
    adapt_prompt_arguments,
    convert_command_file,
    convert_commands_directory,
    escape_yaml_string,
    extract_description,
    parse_frontmatter,
    sanitize_skill_name,
)
from cc2agy.converters.plugin import convert_plugin
from cc2agy.detector import detect_claude_project


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
        # $N is 0-based in Claude Code: $1 is the second argument
        self.assertIn("[Argument 2 provided by user]", adapted)
        self.assertIn("[User Arguments provided after the slash command]", adapted)
        self.assertIn("migrated from a Claude Code slash command", adapted)

    def test_adapt_prompt_arguments_standalone_arguments(self):
        """$ARGUMENTS alone, preceded by a space or at line start, must be adapted."""
        adapted = adapt_prompt_arguments("Review the file $ARGUMENTS now.")
        self.assertIn("Review the file [User Arguments provided after the slash command] now.", adapted)
        self.assertIn("migrated from a Claude Code slash command", adapted)

        adapted_line_start = adapt_prompt_arguments("$ARGUMENTS")
        self.assertIn("[User Arguments provided after the slash command]", adapted_line_start)

        # Longer identifiers are not placeholders
        untouched = adapt_prompt_arguments("Set $ARGUMENTS_LIST manually.")
        self.assertTrue(untouched.startswith("Set $ARGUMENTS_LIST manually."))
        self.assertNotIn("[User Arguments", untouched)

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
        self.assertIn("Apply user argument [Argument 2 provided by user] now.", adapted)

    def test_adapt_prompt_arguments_follow_claude_code_placeholders(self):
        adapted = adapt_prompt_arguments(
            "Fix issue $0 on branch $1; first again: $ARGUMENTS[0], third: $ARGUMENTS[2]. "
            "Literal: \\$1 and \\$ARGUMENTS. Named: $issue / $branch, not $other.",
            ["issue", "branch"],
        )
        self.assertIn("Fix issue [Argument 1 provided by user] on branch [Argument 2 provided by user]", adapted)
        self.assertIn("first again: [Argument 1 provided by user], third: [Argument 3 provided by user]", adapted)
        self.assertIn("Literal: $1 and $ARGUMENTS.", adapted)
        self.assertIn("Named: [Argument 1 ('issue') provided by user] / [Argument 2 ('branch') provided by user], "
                      "not $other.", adapted)

    def test_adapt_prompt_arguments_without_placeholder_appends_arguments_note(self):
        adapted = adapt_prompt_arguments("Summarize the current diff.")
        self.assertTrue(adapted.startswith("Summarize the current diff."))
        self.assertIn("treat them as `ARGUMENTS: <what the user typed>`", adapted)
        self.assertNotIn("ARGUMENTS: <what", adapt_prompt_arguments("Review $ARGUMENTS"))

    def test_command_metadata_goes_into_description_or_warnings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source = tmp_path / "deploy.md"
            source.write_text(
                "---\n"
                "description: Deploys the app\n"
                "when_to_use: Use when the user asks to ship a release.\n"
                "argument-hint: [environment] [version]\n"
                "arguments:\n"
                "  - environment\n"
                "  - version\n"
                "allowed-tools: Bash(git *)\n"
                "model: opus\n"
                "disable-model-invocation: true\n"
                "---\n"
                "Deploy $version to $environment.\n",
                encoding="utf-8",
            )
            warnings: list = []
            skill = convert_command_file(source, tmp_path / "skills", warnings=warnings)
            content = skill.read_text(encoding="utf-8")
        self.assertIn('description: "Deploys the app. Use when the user asks to ship a release. '
                      'Arguments: [environment] [version]"', content)
        self.assertIn("Deploy [Argument 2 ('version') provided by user] to "
                      "[Argument 1 ('environment') provided by user].", content)
        self.assertTrue(any("dropped: allowed-tools, disable-model-invocation, model." in w for w in warnings))
        self.assertTrue(any("may run the converted skill on its own" in w for w in warnings))

    def test_plugin_manifest_command_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = Path(tmp_dir) / "plug"
            (plugin / ".claude-plugin").mkdir(parents=True)
            (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "plug", "commands": {
                "about": {"content": "Explain the plugin.", "description": "About the plugin",
                          "argumentHint": "[topic]", "model": "haiku", "allowedTools": ["Read"]}}}), encoding="utf-8")
            plugin_dir, summary = convert_plugin(plugin, Path(tmp_dir) / "out", overwrite=True)
            content = (plugin_dir / "skills" / "about" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('description: "About the plugin. Arguments: [topic]"', content)
        self.assertTrue(any("plugin.json commands.about" in w and "plugin.json allowedTools, plugin.json model" in w
                            for w in summary["warnings"]))

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
            # Like Claude Code (/git:push), the subfolder is part of the name
            self.assertTrue((skills_dir / "git-push" / "SKILL.md").exists())

    def test_nested_command_does_not_collide_with_root_command(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            cmd_dir = tmp_path / "commands"
            (cmd_dir / "git").mkdir(parents=True)
            (cmd_dir / "commit.md").write_text("# Commit\nROOT COMMIT", encoding="utf-8")
            (cmd_dir / "git" / "commit.md").write_text("# Git Commit\nGIT COMMIT", encoding="utf-8")

            skills_dir = tmp_path / "skills"
            converted = convert_commands_directory(cmd_dir, skills_dir, overwrite=True)

            self.assertEqual(len(converted), 2)
            root_skill = (skills_dir / "commit" / "SKILL.md").read_text(encoding="utf-8")
            git_skill = (skills_dir / "git-commit" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("ROOT COMMIT", root_skill)
            self.assertIn("GIT COMMIT", git_skill)
            self.assertIn("name: git-commit", git_skill)


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

    def _convert(self, root: Path, out_dir: Path) -> tuple:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["convert", str(root), "--dest", str(out_dir), "--overwrite"])
        return code, stdout.getvalue() + stderr.getvalue()

    def test_cli_command_frontmatter_name_is_ignored_with_warning(self):
        """Claude Code ignores name: in commands, so two commands declaring the same name keep their file names."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cmd_dir = root / "commands"
            cmd_dir.mkdir()
            (cmd_dir / "a.md").write_text("---\nname: deploy\n---\nFROM A", encoding="utf-8")
            (cmd_dir / "b.md").write_text("---\nname: deploy\n---\nFROM B", encoding="utf-8")
            (cmd_dir / "same.md").write_text("---\nname: same\n---\nSAME", encoding="utf-8")
            out_dir = root / "out"

            code, output = self._convert(root, out_dir)

            self.assertEqual(code, 0)
            skills = out_dir / "skills"
            self.assertIn("FROM A", (skills / "a" / "SKILL.md").read_text(encoding="utf-8"))
            second = (skills / "b" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("FROM B", second)
            self.assertIn("name: b", second)
            self.assertFalse((skills / "deploy").exists())
            self.assertIn("declares name 'deploy'", output)
            self.assertNotIn("declares name 'same'", output)

    def test_cli_single_command_file_ignores_frontmatter_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "review.md"
            source.write_text("---\nname: other\n---\nBody", encoding="utf-8")
            out_dir = root / "out"

            code, output = self._convert(source, out_dir)

            self.assertEqual(code, 0)
            self.assertTrue((out_dir / "skills" / "review" / "SKILL.md").exists())
            self.assertIn("declares name 'other'", output)

    def test_cli_same_command_name_in_two_command_folders(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "commands").mkdir()
            (root / ".claude" / "commands").mkdir(parents=True)
            (root / "commands" / "review.md").write_text("# Review\nFROM COMMANDS", encoding="utf-8")
            (root / ".claude" / "commands" / "review.md").write_text("# Review\nFROM DOT CLAUDE", encoding="utf-8")
            out_dir = root / "out"

            code, output = self._convert(root, out_dir)

            self.assertEqual(code, 0)
            skills = out_dir / "skills"
            self.assertIn("FROM COMMANDS", (skills / "review" / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIn("FROM DOT CLAUDE", (skills / "review-2" / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIn("review-2", output)

    def test_cli_inspect_shows_subfolder_in_command_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "commands" / "git").mkdir(parents=True)
            (root / "commands" / "git" / "commit.md").write_text("# Commit", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main(["inspect", str(root)])

            self.assertIn("/git-commit", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
