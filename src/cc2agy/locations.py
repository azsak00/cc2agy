"""Where Claude Code components are looked for, shared by the detector (inspect and folder
mode) and the plugin converter, so the conversion covers exactly what inspect reports.

This module imports nothing from cc2agy, so the detector and the converters can both use it.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional


CLAUDE_PLUGIN_DIR = ".claude-plugin"

# Command folders: every one found is scanned
COMMAND_DIRS = (("commands",), (".claude", "commands"), ("prompts",))
# Skill folders: the first one found is used
SKILL_DIRS = (("skills",), (".claude", "skills"))
# Subagent folders: every one found is scanned
AGENT_DIRS = (("agents",), (".claude", "agents"))
# Rules, MCP and hooks files: the first match wins, folder by folder, then file name by file name
RULES_DIRS = ((), (".claude",), ("rules",))
RULES_FILES = ("CLAUDE.md",)
MCP_DIRS = ((), (".claude",))
MCP_FILES = (".mcp.json", "mcp.json", ".claude.json")
HOOKS_DIRS = (("hooks",), (), (".claude",))
HOOKS_FILES = ("hooks.json",)

# Top-level plugin folders that are not copied as is: the components converted above, the
# folders of components with no equivalent (they are reported instead), and rules/, since
# Antigravity loads every file in a plugin's rules/ as an active rule. Every other folder
# (scripts, MCP servers in dist/, src/, lib/ ...) is copied, as Claude Code keeps the whole
# plugin folder and ${CLAUDE_PLUGIN_ROOT} paths may point anywhere in it.
NOT_COPIED_DIRS = {
    ".claude-plugin",
    ".claude",
    "skills",
    "commands",
    "prompts",
    "agents",
    "rules",
    "output-styles",
    "workflows",
    "themes",
    "monitors",
}


def find_case_insensitive(directory: Path, filename: str) -> Optional[Path]:
    """Locate a file within a directory in a case-insensitive manner (cross-platform / Linux safe)."""
    if not directory.exists() or not directory.is_dir():
        return None

    direct_path = directory / filename
    if direct_path.exists() and direct_path.is_file():
        return direct_path

    target_lower = filename.lower()
    try:
        for item in directory.iterdir():
            if item.is_file() and item.name.lower() == target_lower:
                return item
    except (PermissionError, OSError):
        pass

    return None


def _existing_dirs(root: Path, candidates) -> List[Path]:
    return [root.joinpath(*parts) for parts in candidates if root.joinpath(*parts).is_dir()]


def _first_file(root: Path, dirs, filenames) -> Optional[Path]:
    for parts in dirs:
        for filename in filenames:
            found = find_case_insensitive(root.joinpath(*parts), filename)
            if found:
                return found
    return None


def command_dirs(root: Path) -> List[Path]:
    return _existing_dirs(root, COMMAND_DIRS)


def skills_dir(root: Path) -> Optional[Path]:
    found = _existing_dirs(root, SKILL_DIRS)
    return found[0] if found else None


def agent_dirs(root: Path) -> List[Path]:
    return _existing_dirs(root, AGENT_DIRS)


def rules_file(root: Path) -> Optional[Path]:
    return _first_file(root, RULES_DIRS, RULES_FILES)


def rules_files(root: Path) -> List[Path]:
    """Every rules file found, one per folder, in search order."""
    found = (find_case_insensitive(root.joinpath(*parts), name) for parts in RULES_DIRS for name in RULES_FILES)
    return [f for f in found if f is not None]


def mcp_file(root: Path) -> Optional[Path]:
    return _first_file(root, MCP_DIRS, MCP_FILES)


def hooks_file(root: Path) -> Optional[Path]:
    return _first_file(root, HOOKS_DIRS, HOOKS_FILES)


def plugin_manifest(root: Path) -> Optional[Path]:
    """The Claude Code plugin manifest (.claude-plugin/plugin.json only)."""
    return find_case_insensitive(root / CLAUDE_PLUGIN_DIR, "plugin.json")


def copied_plugin_dirs(root: Path) -> List[Path]:
    """Top-level plugin folders the plugin conversion copies as they are."""
    try:
        items = sorted(root.iterdir())
    except (PermissionError, OSError):
        return []
    return [
        item for item in items
        if item.is_dir() and item.name.lower() not in NOT_COPIED_DIRS and not item.name.lower().startswith(".git")
    ]
