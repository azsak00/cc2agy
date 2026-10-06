"""Unit tests for Claude Code plugin variables and userConfig in converted Antigravity plugins."""

from __future__ import annotations

import base64
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cc2agy.cli import main
from cc2agy.converters.hooks import convert_hooks_data
from cc2agy.converters.plugin import convert_plugin
from cc2agy.converters.variables import PluginVariables, resolve_user_config, substitute


USER_CONFIG = {
    "api_url": {"type": "string", "title": "URL", "description": "d", "default": "https://default.example"},
    "api_token": {"type": "string", "title": "Token", "description": "d", "sensitive": True},
    "verbose": {"type": "boolean", "title": "Verbose", "description": "d", "default": True},
    "tags": {"type": "string", "title": "Tags", "description": "d", "multiple": True, "default": ["a", "b"]},
    "region": {"type": "string", "title": "Region", "description": "d"},
}


def _spec(command: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(command.split()[-1]).decode("utf-8"))


def _make_plugin(root: Path, manifest: dict) -> Path:
    plugin = root / "plug"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return plugin


class TestUserConfig(unittest.TestCase):
    def test_value_precedence_and_defaults(self):
        warnings: list = []
        values, sensitive, declared = resolve_user_config(
            USER_CONFIG, {"api_url": "https://given.example", "api_token": "s3cr3t", "unknown": "x"}, warnings
        )
        self.assertEqual(values["api_url"], "https://given.example")
        self.assertEqual(values["api_token"], "s3cr3t")
        self.assertEqual(values["verbose"], "true")
        self.assertNotIn("tags", values)
        self.assertNotIn("region", values)
        self.assertEqual(sensitive, {"api_token"})
        self.assertEqual(declared, set(USER_CONFIG))
        self.assertTrue(any("'tags'" in w for w in warnings))
        self.assertTrue(any("'unknown'" in w for w in warnings))


class TestSubstitute(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name) / "my plugin"
        self.vars = PluginVariables(
            root=root, data_dir=root / "cc2agy_data", values={"api_url": "https://u", "api_token": "tok"},
            sensitive={"api_token"}, declared={"api_url", "api_token", "region"}, plugin=True,
        )
        self.root = root.as_posix()

    def tearDown(self):
        self._tmp.cleanup()

    def test_markdown(self):
        warnings: list = []
        text = (
            "Run ${CLAUDE_PLUGIN_ROOT}/x.sh, cache in ${CLAUDE_PLUGIN_DATA}, open ${CLAUDE_PROJECT_DIR}/src, "
            "call ${user_config.api_url} with ${user_config.api_token} in ${user_config.region}"
        )
        result = substitute(text, self.vars, "markdown", warnings)
        self.assertEqual(
            result,
            f"Run {self.root}/x.sh, cache in {self.root}/cc2agy_data, open ./src, "
            "call https://u with ${user_config.api_token} in ${user_config.region}",
        )
        self.assertTrue((Path(self.root) / "cc2agy_data").is_dir())
        self.assertTrue(any("'api_token' is sensitive" in w for w in warnings))
        self.assertTrue(any("--user-config region=VALUE" in w for w in warnings))

    def test_mcp_and_hook_contexts(self):
        warnings: list = []
        self.assertEqual(substitute("${user_config.api_token}", self.vars, "mcp", warnings), "tok")
        self.assertTrue(any("plain text" in w for w in warnings))
        self.assertEqual(substitute("${CLAUDE_PROJECT_DIR}", self.vars, "mcp", warnings), "${CLAUDE_PROJECT_DIR}")
        self.assertTrue(any("MCP server" in w for w in warnings))

        warnings = []
        shell = substitute("curl ${user_config.api_url}", self.vars, "hook_shell", warnings)
        self.assertEqual(shell, "curl ${user_config.api_url}")
        self.assertTrue(any("CLAUDE_PLUGIN_OPTION_API_URL" in w for w in warnings))
        self.assertEqual(substitute("${user_config.api_url}", self.vars, "hook_exec", []), "https://u")
        self.assertEqual(substitute("${CLAUDE_PROJECT_DIR}", self.vars, "hook_exec", []), "${CLAUDE_PROJECT_DIR}")


class TestHooksWithVariables(unittest.TestCase):
    def test_runner_is_used_only_when_needed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "plug"
            variables = PluginVariables(root=root, values={"api_url": "https://u"}, declared={"api_url"})
            raw = {"PostToolUse": [{"matcher": "Write", "hooks": [
                {"command": "node", "args": ["${CLAUDE_PLUGIN_ROOT}/fmt.js", "${user_config.api_url}", "a b"]},
                {"command": 'bash "${CLAUDE_PLUGIN_ROOT}/plain.sh"'},
                {"command": 'bash "$CLAUDE_PROJECT_DIR/check.sh"'},
            ]}]}
            converted, _ = convert_hooks_data(raw, "p", helper_dir=Path(tmp_dir), variables=variables)

            exec_hook, plain_hook, env_hook = converted["p-hooks"]["PostToolUse"][0]["hooks"]
            spec = _spec(exec_hook["command"])
            self.assertEqual(spec["command"], "node")
            self.assertEqual(spec["args"], [f"{root.as_posix()}/fmt.js", "https://u", "a b"])
            self.assertEqual(spec["env"]["CLAUDE_PLUGIN_OPTION_API_URL"], "https://u")
            self.assertEqual(plain_hook["command"], f'bash "{root.as_posix()}/plain.sh"')
            self.assertEqual(_spec(env_hook["command"])["args"], None)

    def test_scripts_reading_environment_wrap_every_hook(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            variables = PluginVariables(root=Path(tmp_dir), scripts_read_env=True)
            raw = {"Stop": [{"hooks": [{"command": "bash stop.sh"}]}]}
            converted, _ = convert_hooks_data(raw, "p", helper_dir=Path(tmp_dir), variables=variables)
            self.assertEqual(_spec(converted["p-hooks"]["Stop"][0]["command"])["command"], "bash stop.sh")

    def test_runner_executes_exec_form_with_environment(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = _make_plugin(Path(tmp_dir), {"name": "plug"})
            (plugin / "hooks").mkdir()
            script = (
                "import os, sys; print(sys.argv[1], os.environ['CLAUDE_PROJECT_DIR'], "
                "os.environ['CLAUDE_PLUGIN_ROOT'] == sys.argv[2]); sys.exit(3)"
            )
            (plugin / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
                {"command": sys.executable, "args": ["-c", script, "${CLAUDE_PROJECT_DIR}/x", "${CLAUDE_PLUGIN_ROOT}"]}
            ]}]}}), encoding="utf-8")

            plugin_dir, _ = convert_plugin(plugin, Path(tmp_dir) / "out", overwrite=True)

            hooks = json.loads((plugin_dir / "hooks.json").read_text(encoding="utf-8"))
            runner = plugin_dir / "cc2agy_hooks" / "hook_runner.py"
            encoded = hooks["plug-hooks"]["Stop"][0]["command"].split()[-1]
            result = subprocess.run(
                [sys.executable, str(runner), encoded],
                input=json.dumps({"workspacePaths": ["/work/space"]}), capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 3)
            self.assertEqual(result.stdout.split(), ["/work/space/x", "/work/space", "True"])


class TestPluginWithVariables(unittest.TestCase):
    def test_mcp_skills_agents_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {
                "name": "plug", "description": "Desc", "version": "1.0.0", "author": {"name": "X"},
                "userConfig": USER_CONFIG,
                "mcpServers": {
                    "local": {"command": "${CLAUDE_PLUGIN_ROOT}/bin/srv", "args": ["--db", "${CLAUDE_PLUGIN_DATA}/db"],
                              "env": {"TOKEN": "${user_config.api_token}"}},
                    "remote": {"type": "http", "url": "${user_config.api_url}/mcp",
                               "headers": {"X-Region": "${user_config.region}"}},
                },
            })
            (plugin / "skills" / "use").mkdir(parents=True)
            (plugin / "skills" / "use" / "SKILL.md").write_text(
                "---\nname: use\ndescription: d\n---\nCall ${user_config.api_url} from ${CLAUDE_PROJECT_DIR}\n",
                encoding="utf-8",
            )
            (plugin / "agents").mkdir()
            (plugin / "agents" / "a.md").write_text(
                "---\nname: a\ndescription: d\n---\nUse ${user_config.api_url}\n", encoding="utf-8"
            )

            plugin_dir, summary = convert_plugin(
                plugin, tmp_path / "out", overwrite=True, user_config={"api_token": "tok"}
            )

            manifest = json.loads((plugin_dir / "plugin.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest, {"name": "plug", "description": "Desc"})

            servers = json.loads((plugin_dir / "mcp_config.json").read_text(encoding="utf-8"))["mcpServers"]
            root = plugin_dir.as_posix()
            self.assertEqual(servers["local"]["command"], f"{root}/bin/srv")
            self.assertEqual(servers["local"]["args"], ["--db", f"{root}/cc2agy_data/db"])
            self.assertEqual(servers["local"]["env"]["TOKEN"], "tok")
            self.assertEqual(servers["local"]["env"]["CLAUDE_PLUGIN_ROOT"], root)
            self.assertEqual(servers["local"]["env"]["CLAUDE_PLUGIN_DATA"], f"{root}/cc2agy_data")
            self.assertTrue((plugin_dir / "cc2agy_data").is_dir())
            self.assertEqual(servers["remote"]["serverUrl"], "https://default.example/mcp")
            self.assertEqual(servers["remote"]["headers"]["X-Region"], "${user_config.region}")
            self.assertNotIn("env", servers["remote"])

            skill = (plugin_dir / "skills" / "use" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("Call https://default.example from .", skill)
            self.assertIn("Use https://default.example", (plugin_dir / "agents" / "a.md").read_text(encoding="utf-8"))

            warnings = summary["warnings"]
            self.assertTrue(any("'api_token' is sensitive" in w for w in warnings))
            self.assertTrue(any("--user-config region=VALUE" in w for w in warnings))


class TestCLIUserConfig(unittest.TestCase):
    def _run(self, *args: str) -> tuple:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue() + stderr.getvalue()

    def test_cli_passes_values_and_rejects_malformed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            plugin = _make_plugin(tmp_path, {
                "name": "plug", "userConfig": {"region": USER_CONFIG["region"]},
                "mcpServers": {"s": {"command": "srv", "args": ["${user_config.region}"]}},
            })
            out = tmp_path / "out"

            code, _ = self._run("convert", str(plugin), "--dest", str(out), "--user-config", "region=eu=west")
            self.assertEqual(code, 0)
            servers = json.loads((out / "plugins" / "plug" / "mcp_config.json").read_text(encoding="utf-8"))
            self.assertEqual(servers["mcpServers"]["s"]["args"], ["eu=west"])

            code, output = self._run("convert", str(plugin), "--dest", str(out), "--user-config", "region")
            self.assertEqual(code, 1)
            self.assertIn("KEY=VALUE", output)

            (tmp_path / "proj" / "commands").mkdir(parents=True)
            (tmp_path / "proj" / "commands" / "c.md").write_text("Body", encoding="utf-8")
            code, output = self._run(
                "convert", str(tmp_path / "proj"), "--dest", str(tmp_path / "o2"), "--user-config", "a=b"
            )
            self.assertEqual(code, 0)
            self.assertIn("only applies to plugin conversion", output)


if __name__ == "__main__":
    unittest.main()
