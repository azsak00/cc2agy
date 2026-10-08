"""Detector for Claude Code plugins, commands, rules, and configuration files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from cc2agy import locations
from cc2agy.converters.commands import command_default_name
from cc2agy.converters.hooks import SETTINGS_FILES
from cc2agy.converters.skills import skill_name_for
from cc2agy.locations import CLAUDE_PLUGIN_DIR, find_case_insensitive


def _settings_hook_keys(path: Path) -> Set[str]:
    """Hook keys ('hooks', 'disableAllHooks') a settings file sets; an unreadable file counts
    as holding hooks, so the conversion reports its error instead of dropping it."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"hooks"}
    if not isinstance(data, dict):
        return {"hooks"}
    return {k for k in ("hooks", "disableAllHooks") if k in data}


def _is_claude_plugin_manifest(path: Path) -> bool:
    """True for the canonical Claude Code manifest location: .claude-plugin/plugin.json."""
    return path.name.lower() == "plugin.json" and path.parent.name.lower() == CLAUDE_PLUGIN_DIR


@dataclass
class ClaudeProjectInfo:
    """Holds information about discovered Claude Code resources in a directory."""
    root_path: Path
    commands_dirs: List[Path] = field(default_factory=list)
    command_files: List[Path] = field(default_factory=list)
    skills_dir: Optional[Path] = None
    rules_file: Optional[Path] = None
    mcp_file: Optional[Path] = None
    plugin_manifest: Optional[Path] = None
    hooks_file: Optional[Path] = None
    settings_files: List[Path] = field(default_factory=list)
    agents_dirs: List[Path] = field(default_factory=list)
    agent_files: List[Path] = field(default_factory=list)
    auxiliary_dirs: List[Path] = field(default_factory=list)

    @property
    def has_commands(self) -> bool:
        return bool(self.command_files)

    @property
    def has_rules(self) -> bool:
        return self.rules_file is not None and self.rules_file.exists()

    @property
    def has_mcp(self) -> bool:
        return self.mcp_file is not None and self.mcp_file.exists()

    @property
    def has_skills(self) -> bool:
        return self.skills_dir is not None and self.skills_dir.exists()

    @property
    def hook_sources(self) -> List[Path]:
        """hooks.json, then .claude/settings.json and .claude/settings.local.json (precedence order)."""
        sources = [self.hooks_file] if self.hooks_file is not None and self.hooks_file.exists() else []
        return sources + [f for f in self.settings_files if f.exists()]

    @property
    def has_hooks(self) -> bool:
        return bool(self.hook_sources)

    @property
    def has_agents(self) -> bool:
        return bool(self.agent_files)

    @property
    def is_plugin(self) -> bool:
        return self.plugin_manifest is not None and self.plugin_manifest.exists()

    @property
    def is_claude_project(self) -> bool:
        return (
            self.has_commands
            or self.has_rules
            or self.has_mcp
            or self.has_skills
            or self.has_hooks
            or self.has_agents
            or self.is_plugin
        )

    def _command_name(self, cmd: Path) -> str:
        """Name a command file with its subfolders (commands/git/commit.md -> git-commit)."""
        for c_dir in self.commands_dirs:
            if cmd.is_relative_to(c_dir):
                return command_default_name(cmd, c_dir)
        return cmd.stem

    def summary(self) -> str:
        """Return a formatted string describing the detected resources."""
        lines = [f"Analysis of: {self.root_path}"]
        if not self.is_claude_project:
            lines.append("  [!] No standard Claude Code components detected.")
            return "\n".join(lines)

        lines.append("  [+] Claude Code components found:")
        if self.has_commands:
            dirs_str = ", ".join(str(d.name) for d in self.commands_dirs)
            lines.append(f"    - Commands ({len(self.command_files)} files in [{dirs_str}]):")
            for cmd in self.command_files[:5]:
                lines.append(f"        /{self._command_name(cmd)}")
            if len(self.command_files) > 5:
                lines.append(f"        ... and {len(self.command_files) - 5} more")

        if self.has_rules and self.is_plugin:
            lines.append(
                f"    - {self.rules_file.name} at plugin level (not converted: Claude Code does not load it in a plugin)"
            )
        elif self.has_rules:
            lines.append(f"    - Project Rules at: {self.rules_file.name}")

        if self.has_mcp:
            lines.append(f"    - MCP Server Config at: {self.mcp_file.name}")

        if self.has_skills:
            if (self.skills_dir / "SKILL.md").exists() or (self.skills_dir / "skill.md").exists():
                lines.append(f"    - Modular Skill: {skill_name_for(self.skills_dir)}")
            else:
                try:
                    skills_found = [
                        skill_name_for(d) for d in sorted(self.skills_dir.iterdir())
                        if d.is_dir() and ((d / "SKILL.md").exists() or (d / "skill.md").exists())
                    ]
                except (PermissionError, OSError):
                    skills_found = []

                if skills_found:
                    lines.append(f"    - Existing Modular Skills ({len(skills_found)} in [{self.skills_dir.name}]):")
                    for s_name in skills_found[:5]:
                        lines.append(f"        /{s_name}")
                    if len(skills_found) > 5:
                        lines.append(f"        ... and {len(skills_found) - 5} more")
                else:
                    lines.append(f"    - Existing Skills at: {self.skills_dir.name}")

        if self.plugin_manifest:
            lines.append(f"    - Plugin Manifest at: {self.plugin_manifest.name}")

        if self.has_hooks and self.is_plugin:
            # A plugin's hooks come from hooks.json; its .claude/settings*.json are not loaded
            plugin_hooks = [f for f in self.hook_sources if f not in self.settings_files]
            if plugin_hooks:
                lines.append(f"    - Lifecycle Hooks at: {', '.join(f.name for f in plugin_hooks)}")
            for f in self.settings_files:
                if f.exists() and "hooks" in _settings_hook_keys(f):
                    lines.append(
                        f"    - Hooks in .claude/{f.name} (not converted: Claude Code does not load them in a plugin)"
                    )
        elif self.has_hooks:
            lines.append(f"    - Lifecycle Hooks at: {', '.join(f.name for f in self.hook_sources)}")

        if self.has_agents:
            dirs_str = ", ".join(str(d.name) for d in self.agents_dirs)
            lines.append(f"    - Subagents ({len(self.agent_files)} files in [{dirs_str}])")

        if self.auxiliary_dirs:
            aux_str = ", ".join(d.name for d in self.auxiliary_dirs)
            lines.append(f"    - Auxiliary Plugin Directories ({len(self.auxiliary_dirs)}): [{aux_str}]")

        return "\n".join(lines)


def detect_claude_project(target_path: Path) -> ClaudeProjectInfo:
    """Inspect target_path and locate all Claude Code assets with cross-platform robustness."""
    target_path = target_path.resolve()
    info = ClaudeProjectInfo(root_path=target_path)

    if not target_path.exists():
        return info

    # If target is directly a single command, skill, rules, MCP config, or hooks file
    if target_path.is_file():
        if target_path.suffix.lower() == ".md":
            if target_path.name.lower() == "claude.md":
                info.rules_file = target_path
            elif target_path.name.lower() == "skill.md":
                # A SKILL.md stands for its whole folder (references/, scripts/, ...)
                info.skills_dir = target_path.parent
            else:
                info.command_files.append(target_path)
                info.commands_dirs.append(target_path.parent)
            return info
        elif target_path.suffix.lower() == ".json":
            if target_path.name.lower() in SETTINGS_FILES:
                if "hooks" in _settings_hook_keys(target_path):
                    info.settings_files.append(target_path)
                return info
            if "mcp" in target_path.name.lower() or "claude" in target_path.name.lower():
                info.mcp_file = target_path
                return info
            elif "hook" in target_path.name.lower():
                info.hooks_file = target_path
                return info
            elif _is_claude_plugin_manifest(target_path):
                info.plugin_manifest = target_path
                return info

    # 1. Discover command directories recursively and exhaustively
    seen_files: Set[Path] = set()
    for c_dir in locations.command_dirs(target_path):
        info.commands_dirs.append(c_dir)
        for md_file in sorted(c_dir.rglob("*.md")):
            resolved = md_file.resolve()
            if resolved not in seen_files:
                seen_files.add(resolved)
                info.command_files.append(md_file)

    # 2. Discover skills directories
    # In a plugin, a root SKILL.md is the plugin's single skill only when there is no skills/
    # folder, as in Claude Code
    root_is_skill = target_path.is_dir() and (
        (target_path / "SKILL.md").exists() or (target_path / "skill.md").exists()
    )
    if root_is_skill and locations.plugin_manifest(target_path) is not None:
        root_is_skill = locations.skills_dir(target_path) is None
    if root_is_skill:
        info.skills_dir = target_path
    else:
        info.skills_dir = locations.skills_dir(target_path)

    # 3. Discover project rules (case-insensitive for Linux/Unix)
    info.rules_file = locations.rules_file(target_path)

    # 4. Discover MCP configuration (.mcp.json, mcp.json, .claude.json, etc.)
    info.mcp_file = locations.mcp_file(target_path)

    # 5. Discover plugin manifest. Claude Code only reads .claude-plugin/plugin.json;
    # a root plugin.json or manifest.json belongs to other tools (web app manifests,
    # already-converted Antigravity plugins) and must not trigger plugin packaging.
    info.plugin_manifest = locations.plugin_manifest(target_path)

    # 6. Discover lifecycle hooks (hooks.json, etc.)
    info.hooks_file = locations.hooks_file(target_path)

    # Project hooks live in .claude/settings.json and .claude/settings.local.json. A file that
    # only sets disableAllHooks counts when some other source holds hooks.
    settings_dir = target_path if target_path.name.lower() == ".claude" else target_path / ".claude"
    settings_found = []
    for fname in SETTINGS_FILES:
        found_settings = find_case_insensitive(settings_dir, fname)
        if found_settings:
            keys = _settings_hook_keys(found_settings)
            if keys:
                settings_found.append((found_settings, keys))
    if info.hooks_file or any("hooks" in keys for _, keys in settings_found):
        info.settings_files = [f for f, _ in settings_found]

    # 7. Discover subagents (plugin agents/ and project .claude/agents/, scanned recursively)
    for a_dir in locations.agent_dirs(target_path):
        files = [f for f in sorted(a_dir.rglob("*.md")) if f.is_file()]
        if files:
            info.agents_dirs.append(a_dir)
            info.agent_files.extend(files)

    # 8. Discover the plugin folders the plugin conversion copies as they are
    if info.is_plugin:
        info.auxiliary_dirs = locations.copied_plugin_dirs(target_path)

    return info
