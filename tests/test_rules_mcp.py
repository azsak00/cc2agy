"""Unit tests for Claude Code rules (CLAUDE.md -> AGENTS.md), MCP configuration, and integrated CLI."""

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
from cc2agy.converters.mcp import (
    convert_mcp_config,
    convert_mcp_file,
    extract_servers_dict,
    normalize_server_entry,
)
from cc2agy.converters.rules import (
    MAX_RULE_FILE_BYTES,
    clean_rules_content,
    convert_rules_file,
)
from cc2agy.detector import detect_claude_project


class TestRulesConverter(unittest.TestCase):

    def test_clean_rules_strips_yaml_frontmatter(self):
        content_with_yaml = (
            "---\n"
            "description: Project instructions for Claude\n"
            "version: 1.0\n"
            "---\n\n"
            "# Development Guidelines\n\n- Follow TDD\n- Keep code clean\n"
        )
        cleaned, had_fm = clean_rules_content(content_with_yaml)
        self.assertTrue(had_fm)
        self.assertNotIn("description: Project instructions", cleaned)
        self.assertNotIn("version: 1.0", cleaned)
        self.assertIn("# Development Guidelines", cleaned)
        self.assertIn("- Follow TDD", cleaned)
        # Verify comment marker
        self.assertIn("<!-- AGENTS.md — Converted from CLAUDE.md by cc2agy -->", cleaned)

    def test_clean_rules_without_frontmatter(self):
        pure_markdown = "# Coding Standards\n\nAlways use typing."
        cleaned, had_fm = clean_rules_content(pure_markdown)
        self.assertFalse(had_fm)
        self.assertIn("# Coding Standards", cleaned)
        self.assertIn("Always use typing.", cleaned)

    def test_convert_rules_file_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "CLAUDE.md"
            source_file.write_text("# Project Rules\n\nDo not push broken code.", encoding="utf-8")

            dest_dir = tmp_path / "out"
            target_path, warnings = convert_rules_file(source_file, dest_dir)

            self.assertTrue(target_path.exists())
            self.assertEqual(target_path.name, "AGENTS.md")
            content = target_path.read_text(encoding="utf-8")
            self.assertIn("# Project Rules", content)
            self.assertIn("Do not push broken code.", content)
            self.assertEqual(len(warnings), 0)

    def test_convert_rules_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "CLAUDE.md"
            source_file.write_text("# Rules", encoding="utf-8")

            dest_dir = tmp_path / "out"
            # First write
            convert_rules_file(source_file, dest_dir, overwrite=False)

            # Second write without overwrite
            with self.assertRaises(FileExistsError):
                convert_rules_file(source_file, dest_dir, overwrite=False)

            # With overwrite=True
            convert_rules_file(source_file, dest_dir, overwrite=True)

    def test_convert_rules_size_warning(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "CLAUDE.md"
            # Create content exceeding 24 KB
            large_content = "# Large Rules\n\n" + ("a" * (MAX_RULE_FILE_BYTES + 500))
            source_file.write_text(large_content, encoding="utf-8")

            dest_dir = tmp_path / "out"
            _, warnings = convert_rules_file(source_file, dest_dir)

            self.assertTrue(any("exceeds the Antigravity per-file recommendation" in w for w in warnings))


class TestMCPConverter(unittest.TestCase):

    def test_extract_servers_dict_standard(self):
        data = {
            "mcpServers": {
                "sqlite": {"command": "sqlite-mcp", "args": ["db.sqlite"]}
            }
        }
        extracted = extract_servers_dict(data)
        self.assertIn("sqlite", extracted)

    def test_extract_servers_dict_flat_map(self):
        data = {
            "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}
        }
        extracted = extract_servers_dict(data)
        self.assertIn("fetch", extracted)

    def test_normalize_stdio_server(self):
        raw_cfg = {
            "type": "stdio",
            "command": "node",
            "args": ["build/index.js", "--verbose"],
            "env": {"DEBUG": "true"}
        }
        norm, warnings = normalize_server_entry("my-server", raw_cfg)
        self.assertEqual(norm["command"], "node")
        self.assertEqual(norm["args"], ["build/index.js", "--verbose"])
        self.assertEqual(norm["env"], {"DEBUG": "true"})
        self.assertNotIn("type", norm)

    def test_normalize_sse_server_mapping(self):
        raw_cfg = {
            "url": "https://mcp.example.com/sse"
        }
        norm, warnings = normalize_server_entry("remote", raw_cfg)
        self.assertEqual(norm.get("serverUrl"), "https://mcp.example.com/sse")
        self.assertNotIn("url", norm)

    def test_remote_server_headers_are_preserved(self):
        raw_cfg = {
            "type": "http",
            "url": "https://api.example.com/mcp",
            "headers": {"Authorization": "Bearer abc123", "X-Client": "cc2agy"},
        }
        norm, warnings = normalize_server_entry("api", raw_cfg)
        self.assertEqual(
            norm,
            {
                "serverUrl": "https://api.example.com/mcp",
                "headers": {"Authorization": "Bearer abc123", "X-Client": "cc2agy"},
            },
        )
        self.assertTrue(any("'Authorization'" in w and "plaintext secret" in w for w in warnings))
        self.assertFalse(any("'X-Client'" in w for w in warnings))

    def test_remote_server_header_variable_and_unsupported_auth_warn(self):
        raw_cfg = {
            "type": "http",
            "url": "https://api.example.com/mcp",
            "headers": {"Authorization": "Bearer ${API_KEY}"},
            "headersHelper": "./get-token.sh",
            "oauth": {"clientId": "abc", "callbackPort": 8080},
        }
        norm, warnings = normalize_server_entry("api", raw_cfg)
        self.assertEqual(norm["headers"], {"Authorization": "Bearer ${API_KEY}"})
        self.assertNotIn("headersHelper", norm)
        self.assertNotIn("oauth", norm)
        self.assertTrue(any("variable expansion" in w for w in warnings))
        self.assertTrue(any("'headersHelper'" in w for w in warnings))
        self.assertTrue(any("'oauth'" in w for w in warnings))

    def test_plaintext_secret_warning(self):
        raw_cfg = {
            "command": "python",
            "env": {
                "API_KEY": "sk-1234567890abcdef",
                "SAFE_VAR": "$MY_ENV_VAR"
            }
        }
        norm, warnings = normalize_server_entry("secure-srv", raw_cfg)
        self.assertTrue(any("plaintext secret" in w for w in warnings))

    def test_convert_mcp_file_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / ".mcp.json"
            source_data = {
                "mcpServers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
                    },
                    "remote-api": {
                        "url": "https://api.example.com/mcp"
                    }
                }
            }
            source_file.write_text(json.dumps(source_data), encoding="utf-8")

            dest_dir = tmp_path / "out"
            target_path, warnings = convert_mcp_file(source_file, dest_dir)

            self.assertTrue(target_path.exists())
            self.assertEqual(target_path.name, "mcp_config.json")

            parsed = json.loads(target_path.read_text(encoding="utf-8"))
            self.assertIn("mcpServers", parsed)
            servers = parsed["mcpServers"]
            self.assertIn("filesystem", servers)
            self.assertIn("remote-api", servers)
            self.assertEqual(servers["remote-api"]["serverUrl"], "https://api.example.com/mcp")

    def test_convert_mcp_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / ".mcp.json"
            source_file.write_text('{"mcpServers": {"srv": {"command": "cmd"}}}', encoding="utf-8")

            dest_dir = tmp_path / "out"
            convert_mcp_file(source_file, dest_dir, overwrite=False)

            with self.assertRaises(FileExistsError):
                convert_mcp_file(source_file, dest_dir, overwrite=False)

            convert_mcp_file(source_file, dest_dir, overwrite=True)


class TestCLIIntegration(unittest.TestCase):

    def test_cli_convert_full_project(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            # 1. Create commands
            cmd_dir = root / "commands"
            cmd_dir.mkdir()
            (cmd_dir / "review.md").write_text("# Review Code\nCheck for bugs.", encoding="utf-8")

            # 2. Create rules
            (root / "CLAUDE.md").write_text("# Project Rules\n\nBe concise.", encoding="utf-8")

            # 3. Create MCP
            (root / ".mcp.json").write_text(
                '{"mcpServers": {"tool": {"command": "tool-cmd"}}}',
                encoding="utf-8"
            )

            # Run CLI convert
            out_dir = root / "out"
            code = main(["convert", str(root), "--dest", str(out_dir)])
            self.assertEqual(code, 0)

            # Check that all 3 canonical Antigravity assets were generated
            self.assertTrue((out_dir / "skills" / "review" / "SKILL.md").exists())
            self.assertTrue((out_dir / "AGENTS.md").exists())
            self.assertTrue((out_dir / "mcp_config.json").exists())

    def test_cli_convert_filters(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            cmd_dir = root / "commands"
            cmd_dir.mkdir()
            (cmd_dir / "review.md").write_text("Review", encoding="utf-8")
            (root / "CLAUDE.md").write_text("Rules", encoding="utf-8")
            (root / ".mcp.json").write_text('{"mcpServers": {"t": {"command": "c"}}}', encoding="utf-8")

            # Rules-only
            out_rules = root / "out_rules"
            main(["convert", str(root), "--dest", str(out_rules), "--rules-only"])
            self.assertTrue((out_rules / "AGENTS.md").exists())
            self.assertFalse((out_rules / "mcp_config.json").exists())
            self.assertFalse((out_rules / "skills").exists())

            # MCP-only
            out_mcp = root / "out_mcp"
            main(["convert", str(root), "--dest", str(out_mcp), "--mcp-only"])
            self.assertTrue((out_mcp / "mcp_config.json").exists())
            self.assertFalse((out_mcp / "AGENTS.md").exists())
            self.assertFalse((out_mcp / "skills").exists())

    def test_cli_convert_direct_single_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            # Direct rules file
            claude_md = root / "CLAUDE.md"
            claude_md.write_text("# Single Rule", encoding="utf-8")
            out_dir1 = root / "out1"
            main(["convert", str(claude_md), "--dest", str(out_dir1)])
            self.assertTrue((out_dir1 / "AGENTS.md").exists())

            # Direct MCP file
            mcp_json = root / ".mcp.json"
            mcp_json.write_text('{"mcpServers": {"srv": {"command": "test"}}}', encoding="utf-8")
            out_dir2 = root / "out2"
            main(["convert", str(mcp_json), "--dest", str(out_dir2)])
            self.assertTrue((out_dir2 / "mcp_config.json").exists())

    def _run_cli_capturing_stderr(self, argv):
        stderr = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stderr.getvalue()

    def test_cli_malformed_mcp_reports_error_and_continues(self):
        """A broken .mcp.json must not crash the CLI nor block the other components."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "commands").mkdir()
            (root / "commands" / "review.md").write_text("# Review\nCheck.", encoding="utf-8")
            (root / ".mcp.json").write_text("{ broken", encoding="utf-8")

            out_dir = root / "out"
            code, err = self._run_cli_capturing_stderr(["convert", str(root), "--dest", str(out_dir)])

            self.assertEqual(code, 1)
            self.assertIn(".mcp.json", err)
            self.assertIn("1 error(s)", err)
            self.assertTrue((out_dir / "skills" / "review" / "SKILL.md").exists())
            self.assertFalse((out_dir / "mcp_config.json").exists())

    def test_cli_non_utf8_command_reports_file_and_continues(self):
        """A command saved in Windows-1252 is reported by name; the other commands still convert."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "commands").mkdir()
            (root / "commands" / "peticao.md").write_bytes("# Petição\nRedija.".encode("cp1252"))
            (root / "commands" / "review.md").write_text("# Review\nCheck.", encoding="utf-8")

            out_dir = root / "out"
            code, err = self._run_cli_capturing_stderr(["convert", str(root), "--dest", str(out_dir)])

            self.assertEqual(code, 1)
            self.assertIn("peticao.md", err)
            self.assertIn("not valid UTF-8", err)
            self.assertTrue((out_dir / "skills" / "review" / "SKILL.md").exists())

    def test_cli_skill_overlapping_destination_reports_error(self):
        """The overlap refusal from migrate_skill_folder surfaces as a clean CLI error."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            skills_root = Path(tmp_dir) / ".agents" / "skills"
            skill = skills_root / "my-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: my-skill\n---\nKeep me", encoding="utf-8")

            code, err = self._run_cli_capturing_stderr(
                ["convert", str(skill), "--dest", str(skills_root), "--overwrite"]
            )

            self.assertEqual(code, 1)
            self.assertIn("overlap", err)
            self.assertTrue((skill / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
