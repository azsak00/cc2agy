"""${VAR} and ${VAR:-default} in an MCP config: Claude Code expands them from the environment,
Antigravity passes the text unchanged, so each field holding one is reported."""

from __future__ import annotations

import unittest

from cc2agy.converters.mcp import normalize_server_entry


def _expansion_warnings(warnings):
    return [w for w in warnings if "variable expansion" in w]


class TestMcpEnvVars(unittest.TestCase):
    def test_stdio_fields_with_variables_are_reported(self):
        raw_cfg = {
            "command": "${NODE_BIN}",
            "args": ["server.js", "--token", "${API_TOKEN}"],
            "env": {"DB_URL": "${DATABASE_URL}", "MODE": "prod"},
        }
        norm, warnings = normalize_server_entry("srv", raw_cfg)

        self.assertEqual(norm["args"], ["server.js", "--token", "${API_TOKEN}"])
        found = _expansion_warnings(warnings)
        self.assertEqual(len(found), 3, warnings)
        self.assertTrue(any("'command'" in w and "${NODE_BIN}" in w for w in found))
        self.assertTrue(any("'args'" in w and "${API_TOKEN}" in w for w in found))
        self.assertTrue(any("env 'DB_URL'" in w and "${DATABASE_URL}" in w for w in found))

    def test_url_with_variable_and_default_is_reported(self):
        raw_cfg = {"type": "http", "url": "${API_BASE_URL:-https://api.example.com}/mcp"}
        _, warnings = normalize_server_entry("api", raw_cfg)

        found = _expansion_warnings(warnings)
        self.assertEqual(len(found), 1, warnings)
        self.assertIn("'url'", found[0])
        self.assertIn("${API_BASE_URL}", found[0])

    def test_header_with_variable_gets_one_warning_and_no_secret_warning(self):
        raw_cfg = {
            "type": "http",
            "url": "https://api.example.com/mcp",
            "headers": {"Authorization": "Bearer ${API_KEY}"},
        }
        _, warnings = normalize_server_entry("api", raw_cfg)

        self.assertEqual(len([w for w in warnings if "Authorization" in w]), 1, warnings)
        self.assertTrue(any("header 'Authorization'" in w and "${API_KEY}" in w for w in warnings))

    def test_claude_code_variables_are_not_reported_as_environment_variables(self):
        raw_cfg = {
            "command": "python",
            "args": ["${CLAUDE_PLUGIN_ROOT}/server.py", "${user_config.porta}"],
        }
        _, warnings = normalize_server_entry("srv", raw_cfg)

        self.assertEqual(_expansion_warnings(warnings), [])

    def test_plaintext_secret_warning_does_not_recommend_expansion(self):
        raw_cfg = {"command": "python", "env": {"API_KEY": "sk-1234567890abcdef"}}
        _, warnings = normalize_server_entry("srv", raw_cfg)

        secret = [w for w in warnings if "plaintext secret" in w]
        self.assertEqual(len(secret), 1, warnings)
        self.assertNotIn("expansion", secret[0])


if __name__ == "__main__":
    unittest.main()
