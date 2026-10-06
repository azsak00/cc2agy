"""Claude Code plugin variables and user configuration, resolved for Antigravity.

Claude Code substitutes ${CLAUDE_PLUGIN_ROOT}, ${CLAUDE_PLUGIN_DATA}, ${CLAUDE_PROJECT_DIR} and
${user_config.KEY} in MCP configs, hooks and skill/command/agent content, and exports them to
hook and MCP processes. Antigravity documents none of them, so cc2agy resolves what it can at
conversion time (absolute paths, values passed with --user-config or declared defaults) and
leaves the project folder, known only at run time, to the generated hook runner.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


PLUGIN_ROOT_RE = re.compile(r"\$\{?CLAUDE_PLUGIN_ROOT\}?")
PLUGIN_DATA_RE = re.compile(r"\$\{?CLAUDE_PLUGIN_DATA\}?")
PROJECT_DIR_RE = re.compile(r"\$\{?CLAUDE_PROJECT_DIR\}?")
USER_CONFIG_RE = re.compile(r"\$\{user_config\.([A-Za-z_][A-Za-z0-9_]*)\}")
# Hook commands that read these from the environment need the hook runner to set them
RUNTIME_ENV_RE = re.compile(r"CLAUDE_(?:PROJECT_DIR|PLUGIN_OPTION_)")
SCRIPT_ENV_RE = re.compile(r"CLAUDE_(?:PLUGIN_ROOT|PLUGIN_DATA|PROJECT_DIR|PLUGIN_OPTION_)")
VARIABLE_MARKERS = ("CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA", "CLAUDE_PROJECT_DIR", "user_config.")

DATA_DIR_NAME = "cc2agy_data"
_SCAN_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
_SCAN_SKIP_SUFFIXES = {".md", ".json"}
_SCAN_MAX_BYTES = 512 * 1024


@dataclass
class PluginVariables:
    """What each Claude Code variable becomes in one conversion.

    root: absolute folder ${CLAUDE_PLUGIN_ROOT} stands for (Path(".") keeps the legacy relative form).
    data_dir: folder for ${CLAUDE_PLUGIN_DATA}, created when first handed out.
    values / sensitive / declared: resolved userConfig values, sensitive keys, declared keys.
    plugin: True for a packaged plugin (MCP servers then receive CLAUDE_PLUGIN_ROOT/DATA).
    scripts_read_env: the plugin's scripts read CLAUDE_* variables from the environment,
        so every hook runs through the runner that sets them.
    """

    root: Path
    data_dir: Optional[Path] = None
    values: Dict[str, str] = field(default_factory=dict)
    sensitive: Set[str] = field(default_factory=set)
    declared: Set[str] = field(default_factory=set)
    plugin: bool = False
    scripts_read_env: bool = False

    @property
    def absolute_root(self) -> bool:
        return self.root.is_absolute()

    def data_path(self) -> Optional[str]:
        """The data folder as a forward-slash path, created on first use (as Claude Code does)."""
        if self.data_dir is None:
            return None
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir.as_posix()


def _warn(warnings: List[str], message: str) -> None:
    if message not in warnings:
        warnings.append(message)


def _format_value(value: Any) -> Optional[str]:
    """Render a userConfig value as text; None for values with no single text form (lists)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def resolve_user_config(
    declared: Any, provided: Dict[str, str], warnings: List[str]
) -> Tuple[Dict[str, str], Set[str], Set[str]]:
    """Resolve plugin.json userConfig: a --user-config value first, then the field's default.

    Returns (values, sensitive keys, declared keys). Keys without a value stay unresolved and
    are reported where they are referenced.
    """
    fields = declared if isinstance(declared, dict) else {}
    values: Dict[str, str] = {}
    sensitive: Set[str] = set()
    for key, spec in fields.items():
        spec = spec if isinstance(spec, dict) else {}
        if spec.get("sensitive") is True:
            sensitive.add(key)
        if key in provided:
            values[key] = provided[key]
        elif "default" in spec:
            text = _format_value(spec["default"])
            if text is None:
                _warn(warnings, f"userConfig '{key}': default {spec['default']!r} has no single text form; not used.")
            else:
                values[key] = text
    for key in provided:
        if key not in fields:
            _warn(warnings, f"--user-config '{key}' is not declared in plugin.json userConfig; ignored.")
    return values, sensitive, set(fields)


def substitute(text: str, variables: PluginVariables, where: str, warnings: List[str]) -> str:
    """Replace Claude Code variables in one text.

    where: 'markdown' (skill, command and agent content), 'mcp' (MCP server fields),
    'hook_exec' (exec-form hook command/args) or 'hook_shell' (shell-form hook command).
    Hook text keeps ${CLAUDE_PROJECT_DIR} for the hook runner, which knows the workspace.
    """
    if not text or not any(marker in text for marker in VARIABLE_MARKERS):
        return text

    root = variables.root.as_posix()
    text = PLUGIN_ROOT_RE.sub(lambda _: root, text)

    if PLUGIN_DATA_RE.search(text):
        data = variables.data_path()
        if data is None:
            _warn(warnings, "${CLAUDE_PLUGIN_DATA} has no Antigravity equivalent here; left unchanged.")
        else:
            text = PLUGIN_DATA_RE.sub(lambda _: data, text)

    if PROJECT_DIR_RE.search(text):
        if where == "markdown":
            # Antigravity runs the agent's commands from the workspace, so the project root is "."
            text = PROJECT_DIR_RE.sub(".", text)
        elif where == "mcp":
            _warn(
                warnings,
                "${CLAUDE_PROJECT_DIR} in an MCP server has no Antigravity equivalent (the project folder "
                "is only known at run time); left unchanged, replace it with the project path.",
            )

    def _user_value(match: re.Match) -> str:
        key = match.group(1)
        if where == "hook_shell":
            _warn(
                warnings,
                f"Shell-form hook command references ${{user_config.{key}}}, which Claude Code rejects; "
                f"left unchanged. Use 'args' (exec form) or read $CLAUDE_PLUGIN_OPTION_{key.upper()}.",
            )
            return match.group(0)
        if key not in variables.values:
            if key in variables.declared:
                _warn(
                    warnings,
                    f"userConfig '{key}' has no value; ${{user_config.{key}}} left unchanged. "
                    f"Pass --user-config {key}=VALUE.",
                )
            else:
                _warn(warnings, f"${{user_config.{key}}} is not declared in plugin.json userConfig; left unchanged.")
            return match.group(0)
        if key in variables.sensitive:
            if where == "markdown":
                _warn(
                    warnings,
                    f"userConfig '{key}' is sensitive and is not written into skill or agent content "
                    "(Claude Code does the same); left unchanged.",
                )
                return match.group(0)
            _warn(
                warnings,
                f"userConfig '{key}' is sensitive and was written in plain text into the converted "
                "configuration; keep that file out of version control.",
            )
        return variables.values[key]

    return USER_CONFIG_RE.sub(_user_value, text)


def hook_environment(variables: PluginVariables, warnings: List[str]) -> Dict[str, str]:
    """Environment Claude Code exports to hook processes (CLAUDE_PROJECT_DIR is set at run time)."""
    env: Dict[str, str] = {}
    if variables.absolute_root:
        env["CLAUDE_PLUGIN_ROOT"] = variables.root.as_posix()
    if variables.plugin:
        data = variables.data_path()
        if data is not None:
            env["CLAUDE_PLUGIN_DATA"] = data
    for key, value in variables.values.items():
        env[f"CLAUDE_PLUGIN_OPTION_{key.upper()}"] = value
        if key in variables.sensitive:
            _warn(
                warnings,
                f"userConfig '{key}' is sensitive and is stored in hooks.json (base64-encoded, not "
                "encrypted) so hooks receive it; keep that file out of version control.",
            )
    return env


def scripts_read_environment(folder: Path) -> bool:
    """True when a script in folder reads CLAUDE_* plugin variables from its environment."""
    if not folder.is_dir():
        return False
    for current, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in _SCAN_SKIP_DIRS]
        for name in files:
            path = Path(current) / name
            if path.suffix.lower() in _SCAN_SKIP_SUFFIXES:
                continue
            try:
                if path.stat().st_size > _SCAN_MAX_BYTES:
                    continue
                if SCRIPT_ENV_RE.search(path.read_text(encoding="utf-8", errors="ignore")):
                    return True
            except OSError:
                continue
    return False


def standalone_variables(source_file: Path, dest_dir: Path, scan_scripts: bool = False) -> PluginVariables:
    """Variables for converting a single hooks or MCP file: the plugin root is the source folder.

    Scripts are not copied in a standalone conversion, so ${CLAUDE_PLUGIN_ROOT} points to the
    source plugin folder (hooks/hooks.json and .claude/*.json live one level below it).
    """
    root = source_file.resolve().parent
    if root.name.lower() in ("hooks", ".claude"):
        root = root.parent
    return PluginVariables(
        root=root,
        data_dir=dest_dir.resolve() / DATA_DIR_NAME,
        scripts_read_env=scan_scripts and scripts_read_environment(root),
    )
