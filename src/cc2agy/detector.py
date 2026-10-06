"""Detector for Claude Code plugins, commands, rules, and configuration files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from cc2agy.converters.commands import command_default_name


CLAUDE_PLUGIN_DIR = ".claude-plugin"


def _is_claude_plugin_manifest(path: Path) -> bool:
    """True for the canonical Claude Code manifest location: .claude-plugin/plugin.json."""
    return path.name.lower() == "plugin.json" and path.parent.name.lower() == CLAUDE_PLUGIN_DIR


def _find_case_insensitive(directory: Path, filename: str) -> Optional[Path]:
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
    def has_hooks(self) -> bool:
        return self.hooks_file is not None and self.hooks_file.exists()

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

        if self.has_rules:
            lines.append(f"    - Project Rules at: {self.rules_file.name}")

        if self.has_mcp:
            lines.append(f"    - MCP Server Config at: {self.mcp_file.name}")

        if self.has_skills:
            if (self.skills_dir / "SKILL.md").exists() or (self.skills_dir / "skill.md").exists():
                lines.append(f"    - Modular Skill: {self.skills_dir.name}")
            else:
                try:
                    skills_found = [
                        d.name for d in sorted(self.skills_dir.iterdir())
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

        if self.has_hooks:
            lines.append(f"    - Lifecycle Hooks at: {self.hooks_file.name}")

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
    candidate_cmd_dirs = [
        target_path / "commands",
        target_path / ".claude" / "commands",
        target_path / "prompts",
    ]
    seen_files: Set[Path] = set()
    for c_dir in candidate_cmd_dirs:
        if c_dir.exists() and c_dir.is_dir():
            info.commands_dirs.append(c_dir)
            for md_file in sorted(c_dir.rglob("*.md")):
                resolved = md_file.resolve()
                if resolved not in seen_files:
                    seen_files.add(resolved)
                    info.command_files.append(md_file)

    # 2. Discover skills directories
    if target_path.is_dir() and ((target_path / "SKILL.md").exists() or (target_path / "skill.md").exists()):
        info.skills_dir = target_path
    else:
        candidate_skill_dirs = [
            target_path / "skills",
            target_path / ".claude" / "skills",
        ]
        for s_dir in candidate_skill_dirs:
            if s_dir.exists() and s_dir.is_dir():
                info.skills_dir = s_dir
                break

    # 3. Discover project rules (case-insensitive for Linux/Unix)
    search_dirs_rules = [target_path, target_path / ".claude", target_path / "rules"]
    for s_dir in search_dirs_rules:
        found_rule = _find_case_insensitive(s_dir, "CLAUDE.md")
        if found_rule:
            info.rules_file = found_rule
            break

    # 4. Discover MCP configuration (.mcp.json, mcp.json, .claude.json, etc.)
    search_dirs_mcp = [target_path, target_path / ".claude"]
    mcp_filenames = [".mcp.json", "mcp.json", ".claude.json"]
    for s_dir in search_dirs_mcp:
        for fname in mcp_filenames:
            found_mcp = _find_case_insensitive(s_dir, fname)
            if found_mcp:
                info.mcp_file = found_mcp
                break
        if info.mcp_file:
            break

    # 5. Discover plugin manifest. Claude Code only reads .claude-plugin/plugin.json;
    # a root plugin.json or manifest.json belongs to other tools (web app manifests,
    # already-converted Antigravity plugins) and must not trigger plugin packaging.
    info.plugin_manifest = _find_case_insensitive(target_path / CLAUDE_PLUGIN_DIR, "plugin.json")

    # 6. Discover lifecycle hooks (hooks.json, etc.)
    search_dirs_hooks = [target_path / "hooks", target_path, target_path / ".claude"]
    for h_dir in search_dirs_hooks:
        found_hooks = _find_case_insensitive(h_dir, "hooks.json")
        if found_hooks:
            info.hooks_file = found_hooks
            break

    # 7. Discover subagents (plugin agents/ and project .claude/agents/, scanned recursively)
    for a_dir in (target_path / "agents", target_path / ".claude" / "agents"):
        if a_dir.is_dir():
            files = [f for f in sorted(a_dir.rglob("*.md")) if f.is_file()]
            if files:
                info.agents_dirs.append(a_dir)
                info.agent_files.extend(files)

    # 8. Discover auxiliary plugin directories
    if target_path.is_dir():
        known_aux = {
            "scripts",
            "templates",
            "espec",
            "hooks",
            "resources",
            "references",
            "docs",
            "context",
        }
        try:
            for item in sorted(target_path.iterdir()):
                if item.is_dir() and item.name.lower() in known_aux:
                    info.auxiliary_dirs.append(item)
        except (PermissionError, OSError):
            pass

    return info
