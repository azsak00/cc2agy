"""Unit tests for Lifecycle Hooks converter (cc2agy.converters.hooks)."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from cc2agy.converters.hooks import (
    convert_hooks_data,
    convert_hooks_file,
    sanitize_hook_command,
    sanitize_matcher,
    write_hooks_data,
)


def _decode_spec(command: str) -> dict:
    """Return the JSON spec from a hook-runner command."""
    return json.loads(base64.urlsafe_b64decode(command.split()[-1]).decode("utf-8"))


def _decode_wrapped(command: str):
    """Return (mode, original command) from a hook-runner command."""
    spec = _decode_spec(command)
    return spec["mode"], spec["command"]


class TestHooksConverter(unittest.TestCase):
    def test_sanitize_hook_command(self):
        cmd1 = 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"'
        self.assertEqual(sanitize_hook_command(cmd1), 'bash "./hooks/session-start.sh"')

        cmd2 = 'python3 "$CLAUDE_PLUGIN_ROOT/scripts/lint.py"'
        self.assertEqual(sanitize_hook_command(cmd2), 'python3 "./scripts/lint.py"')

        cmd3 = 'echo ${CLAUDE_PLUGIN_ROOT}'
        self.assertEqual(sanitize_hook_command(cmd3), 'echo .')

    def test_convert_hooks_data_mapping_and_unwrapping(self):
        raw_claude_hooks = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"',
                            }
                        ]
                    }
                ],
                "Stop": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/python.sh" "${CLAUDE_PLUGIN_ROOT}/hooks/stop-check.py"',
                                "timeout": 15,
                            }
                        ]
                    }
                ],
                "PreToolUse": [
                    {
                        "matcher": "run_command",
                        "hooks": [
                            {
                                "command": 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/guard.sh"'
                            }
                        ]
                    }
                ]
            }
        }

        converted, warnings = convert_hooks_data(raw_claude_hooks, plugin_name="test-plug")
        self.assertIn("test-plug-hooks", converted)
        hook_spec = converted["test-plug-hooks"]

        # Check SessionStart mapped to PreInvocation
        self.assertIn("PreInvocation", hook_spec)
        self.assertEqual(len(hook_spec["PreInvocation"]), 1)
        self.assertEqual(hook_spec["PreInvocation"][0]["command"], 'bash "./hooks/session-start.sh"')
        self.assertEqual(hook_spec["PreInvocation"][0]["type"], "command")

        # Check Stop flat unwrapping
        self.assertIn("Stop", hook_spec)
        self.assertEqual(len(hook_spec["Stop"]), 1)
        self.assertEqual(
            hook_spec["Stop"][0]["command"],
            'bash "./hooks/python.sh" "./hooks/stop-check.py"'
        )
        self.assertEqual(hook_spec["Stop"][0]["timeout"], 15)

        # Check PreToolUse grouping with matcher
        self.assertIn("PreToolUse", hook_spec)
        self.assertEqual(len(hook_spec["PreToolUse"]), 1)
        self.assertEqual(hook_spec["PreToolUse"][0]["matcher"], "run_command")
        self.assertEqual(hook_spec["PreToolUse"][0]["hooks"][0]["command"], 'bash "./scripts/guard.sh"')

    def test_convert_hooks_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "hooks.json"
            dest_dir = tmp_path / "out"

            raw_data = {
                "SessionStart": [
                    {"command": "python test.py"}
                ]
            }
            source_file.write_text(json.dumps(raw_data), encoding="utf-8")

            res_path, warnings = convert_hooks_file(source_file, dest_dir, plugin_name="demo")
            self.assertTrue(res_path.exists())
            self.assertEqual(res_path.name, "hooks.json")

            with open(res_path, "r", encoding="utf-8") as f:
                saved_data = json.load(f)

            self.assertIn("demo-hooks", saved_data)
            self.assertIn("PreInvocation", saved_data["demo-hooks"])
            # SessionStart runs through the generated context helper, once per conversation
            command = saved_data["demo-hooks"]["PreInvocation"][0]["command"]
            self.assertEqual(_decode_wrapped(command), ("once", "python test.py"))
            self.assertTrue((dest_dir / "cc2agy_hooks" / "hook_runner.py").exists())

    def test_sanitize_hook_command_absolute_root(self):
        root = Path(tempfile.gettempdir()) / "my plugin"
        cmd = 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/start.sh" $CLAUDE_PLUGIN_ROOT'
        expected = f'bash "{root.as_posix()}/hooks/start.sh" {root.as_posix()}'
        self.assertEqual(sanitize_hook_command(cmd, root), expected)
        self.assertNotIn("\\", sanitize_hook_command(cmd, root))

    def test_edit_matchers_cover_both_antigravity_edit_tools(self):
        self.assertEqual(sanitize_matcher("Edit"), "(?:replace_file_content|multi_replace_file_content)")
        self.assertEqual(sanitize_matcher("MultiEdit"), "multi_replace_file_content")
        self.assertEqual(
            sanitize_matcher("Write|Edit"),
            "write_to_file|(?:replace_file_content|multi_replace_file_content)",
        )

    def test_session_start_matchers_without_startup_are_skipped(self):
        raw = {"SessionStart": [
            {"matcher": "startup|resume", "hooks": [{"command": "echo a"}]},
            {"matcher": "compact", "hooks": [{"command": "echo b"}]},
            {"hooks": [{"command": "echo c"}]},
        ]}
        with tempfile.TemporaryDirectory() as tmp_dir:
            converted, warnings = convert_hooks_data(raw, "p", Path(tmp_dir), Path(tmp_dir))
        commands = [_decode_wrapped(h["command"])[1] for h in converted["p-hooks"]["PreInvocation"]]
        self.assertEqual(commands, ["echo a", "echo c"])
        self.assertTrue(any("'compact'" in w for w in warnings))

    def test_user_prompt_submit_runs_always_with_warning(self):
        raw = {"UserPromptSubmit": [{"hooks": [{"command": "echo ctx"}]}]}
        with tempfile.TemporaryDirectory() as tmp_dir:
            converted, warnings = convert_hooks_data(raw, "p", Path(tmp_dir), Path(tmp_dir))
        self.assertEqual(_decode_wrapped(converted["p-hooks"]["PreInvocation"][0]["command"]), ("always", "echo ctx"))
        self.assertTrue(any("every model invocation" in w for w in warnings))

    def test_unquoted_plugin_root_with_spaces_warns(self):
        raw = {"Stop": [{"hooks": [{"command": "bash ${CLAUDE_PLUGIN_ROOT}/stop.sh"}]}]}
        root = Path(tempfile.gettempdir()) / "my plugin"
        _, warnings = convert_hooks_data(raw, "p", root)
        self.assertTrue(any("without quotes" in w for w in warnings))

        quoted = {"Stop": [{"hooks": [{"command": 'bash "${CLAUDE_PLUGIN_ROOT}/stop.sh"'}]}]}
        _, warnings = convert_hooks_data(quoted, "p", root)
        self.assertFalse(any("without quotes" in w for w in warnings))

    def test_standalone_hooks_file_points_to_source_plugin_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plugin = Path(tmp_dir) / "plug"
            (plugin / "hooks").mkdir(parents=True)
            source = plugin / "hooks" / "hooks.json"
            source.write_text(json.dumps({"hooks": {"Stop": [
                {"hooks": [{"command": 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/stop.sh"'}]}]}}), encoding="utf-8")

            res, _ = convert_hooks_file(source, Path(tmp_dir) / "out", plugin_name="plug")
            command = json.loads(res.read_text(encoding="utf-8"))["plug-hooks"]["Stop"][0]["command"]
            self.assertEqual(_decode_wrapped(command), ("stop", f'bash "{plugin.resolve().as_posix()}/hooks/stop.sh"'))

    def test_context_helper_runs_once_and_injects_output(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir) / "out"
            write_hooks_data({"SessionStart": [{"hooks": [{"command": "echo ctx"}]}]}, dest, "p")
            helper = dest / "cc2agy_hooks" / "hook_runner.py"
            spec = {"mode": "once", "command": "echo ctx", "args": None, "env": {}}
            encoded = base64.urlsafe_b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")

            def run(invocation_num):
                result = subprocess.run(
                    [sys.executable, str(helper), encoded],
                    input=json.dumps({"invocationNum": invocation_num}),
                    capture_output=True, text=True, check=True,
                )
                return json.loads(result.stdout)

            self.assertEqual(run(0), {"injectSteps": [{"ephemeralMessage": "ctx"}]})
            self.assertEqual(run(1), {})

    def test_hooks_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            source_file = tmp_path / "hooks.json"
            dest_dir = tmp_path / "out"
            dest_dir.mkdir(parents=True, exist_ok=True)
            existing_file = dest_dir / "hooks.json"
            existing_file.write_text("{}", encoding="utf-8")

            source_file.write_text('{"Stop": [{"command": "echo stop"}]}', encoding="utf-8")

            with self.assertRaises(FileExistsError):
                convert_hooks_file(source_file, dest_dir, overwrite=False)

            # With overwrite=True
            res, _ = convert_hooks_file(source_file, dest_dir, overwrite=True)
            self.assertTrue(res.exists())


class TestHookRunnerOutput(unittest.TestCase):
    """The generated runner turns Claude Code hook results into what Antigravity parses."""

    # Hook stand-in: prints argv[1] to stdout and argv[2] to stderr, exits with argv[3]
    FAKE_HOOK = "import sys; sys.stdout.write(sys.argv[1]); sys.stderr.write(sys.argv[2]); sys.exit(int(sys.argv[3]))"

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        dest = Path(cls._tmp.name)
        write_hooks_data({"SessionStart": [{"hooks": [{"command": "echo x"}]}]}, dest, "p")
        cls.runner = dest / "cc2agy_hooks" / "hook_runner.py"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_hook(self, mode, stdout="", stderr="", code=0):
        spec = {"mode": mode, "command": sys.executable, "args": ["-c", self.FAKE_HOOK, stdout, stderr, str(code)],
                "env": {}}
        encoded = base64.urlsafe_b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")
        result = subprocess.run(
            [sys.executable, str(self.runner), encoded],
            input=json.dumps({"invocationNum": 0}), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return (json.loads(result.stdout) if result.stdout.strip() else None), result.stderr

    def pre_tool(self, output):
        return self.run_hook("pre_tool", json.dumps(output))[0]

    def test_pre_tool_exit_codes(self):
        self.assertEqual(self.run_hook("pre_tool", stderr="rm is not allowed", code=2)[0],
                         {"decision": "deny", "reason": "rm is not allowed"})
        # Exit 2 blocks even when the JSON allows (Claude Code ignores the JSON then)
        allow = json.dumps({"hookSpecificOutput": {"permissionDecision": "allow", "permissionDecisionReason": "ok"}})
        self.assertEqual(self.run_hook("pre_tool", allow, "blocked", 2)[0], {"decision": "deny", "reason": "blocked"})
        # Other codes are non-blocking errors in Claude Code: the tool runs
        self.assertIsNone(self.run_hook("pre_tool", "partial output", "boom", 1)[0])

    def test_pre_tool_plain_text_and_invalid_json_make_no_decision(self):
        self.assertIsNone(self.run_hook("pre_tool", "Checking command...")[0])
        self.assertIsNone(self.run_hook("pre_tool", "{not json}")[0])
        self.assertIsNone(self.run_hook("pre_tool", "")[0])

    def test_pre_tool_permission_decisions(self):
        self.assertEqual(
            self.pre_tool({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                  "permissionDecisionReason": "Database writes are not allowed"}}),
            {"decision": "deny", "reason": "Database writes are not allowed"},
        )
        self.assertEqual(
            self.pre_tool({"hookSpecificOutput": {"permissionDecision": "allow", "permissionDecisionReason": "Safe.",
                                                  "additionalContext": "Uses the test DB."}}),
            {"decision": "allow", "reason": "Safe. Uses the test DB."},
        )
        self.assertEqual(self.pre_tool({"hookSpecificOutput": {"permissionDecision": "ask"}}), {"decision": "ask"})
        self.assertIsNone(self.pre_tool({"hookSpecificOutput": {"permissionDecision": "defer"}}))
        self.assertIsNone(self.pre_tool({"suppressOutput": True}))

    def test_pre_tool_deprecated_fields_and_continue(self):
        self.assertEqual(self.pre_tool({"decision": "approve"}), {"decision": "allow"})
        self.assertEqual(self.pre_tool({"decision": "block", "reason": "No."}), {"decision": "deny", "reason": "No."})
        self.assertEqual(self.pre_tool({"continue": False, "stopReason": "Build failed"}),
                         {"decision": "deny", "reason": "Build failed"})

    def test_pre_tool_updated_input_asks_instead_of_running_unchanged(self):
        decision = self.pre_tool({"hookSpecificOutput": {"permissionDecision": "allow",
                                                         "updatedInput": {"command": "npm run lint"}}})
        self.assertEqual(decision["decision"], "ask")
        self.assertIn("cannot apply", decision["reason"])
        denied = self.pre_tool({"hookSpecificOutput": {"permissionDecision": "deny", "updatedInput": {}}})
        self.assertEqual(denied, {"decision": "deny"})

    def test_post_tool_and_stop_print_nothing_and_report_what_is_lost(self):
        output, stderr = self.run_hook("post_tool", json.dumps({"decision": "block", "reason": "Tests must pass"}))
        self.assertIsNone(output)
        self.assertIn("block after the tool ran", stderr)
        output, stderr = self.run_hook(
            "post_tool", json.dumps({"hookSpecificOutput": {"additionalContext": "Lint passed."}}), code=2)
        self.assertIsNone(output)
        self.assertIn("additionalContext", stderr)
        self.assertEqual(self.run_hook("stop", "done", code=1), (None, ""))
        output, stderr = self.run_hook("stop", json.dumps({"continue": False, "decision": "block"}))
        self.assertIsNone(output)
        self.assertIn("stop the agent", stderr)

    # Hook stand-in that echoes its stdin to stderr, and then prints argv[1] and exits with argv[2]
    ECHO_HOOK = ("import sys; sys.stderr.write(sys.stdin.read()); "
                 "sys.stdout.write(sys.argv[1]); sys.exit(int(sys.argv[2]))")

    def run_echo(self, mode, payload, stdout="", code=0):
        spec = {"mode": mode, "command": sys.executable, "args": ["-c", self.ECHO_HOOK, stdout, str(code)],
                "env": {}}
        encoded = base64.urlsafe_b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")
        result = subprocess.run([sys.executable, str(self.runner), encoded],
                                input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return (json.loads(result.stdout) if result.stdout.strip() else None), json.loads(result.stderr)

    def test_tool_input_gets_claude_code_fields(self):
        # Shape seen in a real Antigravity CLI run (agy 1.2.13)
        payload = {"conversationId": "c1", "transcriptPath": "/t.jsonl", "workspacePaths": ["/proj"], "stepIdx": 3,
                   "toolCall": {"name": "replace_file_content", "args": {
                       "TargetFile": "/proj/a.txt", "TargetContent": "dois", "ReplacementContent": "DOIS",
                       "AllowMultiple": False, "StartLine": 2, "toolSummary": "Replace in a.txt"}}}
        _, seen = self.run_echo("pre_tool", payload)
        self.assertEqual(seen["tool_name"], "Edit")
        self.assertEqual(seen["tool_input"], {"file_path": "/proj/a.txt", "old_string": "dois",
                                              "new_string": "DOIS", "replace_all": False})
        self.assertEqual((seen["session_id"], seen["transcript_path"], seen["cwd"], seen["hook_event_name"]),
                         ("c1", "/t.jsonl", "/proj", "PreToolUse"))
        self.assertEqual(seen["toolCall"], payload["toolCall"])

        _, seen = self.run_echo("pre_tool", {"toolCall": {"name": "view_file", "args": {
            "AbsolutePath": "/a.txt", "StartLine": 5, "EndLine": 9}}})
        self.assertEqual((seen["tool_name"], seen["tool_input"]),
                         ("Read", {"file_path": "/a.txt", "offset": 5, "limit": 5}))
        _, seen = self.run_echo("post_tool", {"toolCall": {"name": "run_command", "args": {
            "CommandLine": "echo oi", "Cwd": "/proj"}}, "error": "exit status 1"})
        self.assertEqual((seen["tool_name"], seen["tool_input"], seen["tool_response"]),
                         ("Bash", {"command": "echo oi"}, {"error": "exit status 1"}))
        # Tools without confirmed arguments keep the Antigravity name and arguments
        _, seen = self.run_echo("pre_tool", {"toolCall": {"name": "grep_search", "args": {
            "Query": "x", "toolAction": "Searching"}}})
        self.assertEqual((seen["tool_name"], seen["tool_input"]), ("grep_search", {"Query": "x"}))

    def test_stop_block_continues_once_with_stop_hook_active(self):
        # A typical Claude Code Stop hook: blocks once, then lets the agent stop
        hook = ("import json, sys; d = json.load(sys.stdin); sys.stderr.write(json.dumps(d)); "
                "print('' if d['stop_hook_active'] else json.dumps({'decision': 'block', 'reason': 'Run the tests first'}))")
        spec = {"mode": "stop", "command": sys.executable, "args": ["-c", hook], "env": {}}
        encoded = base64.urlsafe_b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")
        payload = json.dumps({"conversationId": "stop-" + uuid.uuid4().hex})

        def stop():
            r = subprocess.run([sys.executable, str(self.runner), encoded], input=payload, capture_output=True, text=True)
            return (json.loads(r.stdout) if r.stdout.strip() else None), json.loads(r.stderr)

        output, seen = stop()
        self.assertEqual(output, {"decision": "continue", "reason": "Run the tests first"})
        self.assertIs(seen["stop_hook_active"], False)
        self.assertEqual(seen["hook_event_name"], "Stop")
        # The next Stop of the same conversation tells the hook it already kept the agent running
        output, seen = stop()
        self.assertIsNone(output)
        self.assertIs(seen["stop_hook_active"], True)
        output, seen = stop()
        self.assertIs(seen["stop_hook_active"], False)
        output, _ = self.run_echo("stop", {"conversationId": "stop-" + uuid.uuid4().hex}, "", code=2)
        self.assertEqual(output["decision"], "continue")

    def run_raw(self, mode, payload):
        """Runs the echo hook (prints 'ctx', exit 0); returns the runner's stdout and stderr."""
        spec = {"mode": mode, "command": sys.executable, "args": ["-c", self.ECHO_HOOK, "ctx", "0"], "env": {}}
        encoded = base64.urlsafe_b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")
        result = subprocess.run([sys.executable, str(self.runner), encoded],
                                input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip(), result.stderr

    def test_session_start_runs_once_per_conversation_even_when_invocation_num_restarts(self):
        # Seen in agy 1.2.13: after a subagent returns, the main conversation starts again at invocationNum 0
        payload = {"conversationId": "once-" + uuid.uuid4().hex, "invocationNum": 0}
        self.assertEqual(json.loads(self.run_raw("once", payload)[0]), {"injectSteps": [{"ephemeralMessage": "ctx"}]})
        self.assertEqual(self.run_raw("once", payload), ("{}", ""))

    def test_session_start_and_stop_skip_subagent_conversations(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            brain = Path(tmp_dir) / "brain"
            parent, child = "main-" + uuid.uuid4().hex, "sub-" + uuid.uuid4().hex
            link = brain / parent / ".system_generated" / "subagents"
            link.mkdir(parents=True)
            (link / f"{child}.json").write_text(json.dumps({"conversationId": child}), encoding="utf-8")
            sub = {"conversationId": child, "artifactDirectoryPath": (brain / child).as_posix(), "invocationNum": 0}
            self.assertEqual(self.run_raw("once", sub), ("{}", ""))
            self.assertEqual(self.run_raw("stop", sub), ("", ""))
            main = {"conversationId": parent, "artifactDirectoryPath": (brain / parent).as_posix(), "invocationNum": 0}
            self.assertEqual(json.loads(self.run_raw("once", main)[0]), {"injectSteps": [{"ephemeralMessage": "ctx"}]})
            self.assertIn('"hook_event_name": "Stop"', self.run_raw("stop", main)[1])

    def test_conversion_warns_that_subagent_detection_is_undocumented(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _, warnings = convert_hooks_data(
                {"SessionStart": [{"hooks": [{"command": "echo a"}]}], "Stop": [{"hooks": [{"command": "echo b"}]}]},
                helper_dir=Path(tmp_dir))
        self.assertEqual(sum("undocumented Antigravity file" in w for w in warnings), 2)

    def test_hooks_run_in_the_project_folder(self):
        # Claude Code runs hooks in the session folder; Antigravity ran plugin hooks in the plugin folder
        hook = "import os; print(os.getcwd())"
        with tempfile.TemporaryDirectory() as project:
            for mode in ("plain", "always"):
                spec = {"mode": mode, "command": sys.executable, "args": ["-c", hook], "env": {}}
                encoded = base64.urlsafe_b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")
                result = subprocess.run([sys.executable, str(self.runner), encoded], capture_output=True, text=True,
                                        input=json.dumps({"workspacePaths": [project]}))
                self.assertEqual(result.returncode, 0, result.stderr)
                out = result.stdout.strip()
                cwd = json.loads(out)["injectSteps"][0]["ephemeralMessage"] if mode == "always" else out
                self.assertTrue(Path(cwd).samefile(project), (mode, cwd))

    def test_context_hooks_read_additional_context_and_need_exit_zero(self):
        context = json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "Use pnpm."}})
        self.assertEqual(self.run_hook("once", context)[0], {"injectSteps": [{"ephemeralMessage": "Use pnpm."}]})
        self.assertEqual(self.run_hook("always", json.dumps({"systemMessage": "hi"}))[0], {})
        self.assertEqual(self.run_hook("once", "plain context")[0], {"injectSteps": [{"ephemeralMessage": "plain context"}]})
        self.assertEqual(self.run_hook("once", "context", code=1)[0], {})


if __name__ == "__main__":
    unittest.main()
