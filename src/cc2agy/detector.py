"""Detector for Claude Code plugins, commands, rules, and configuration files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ClaudeProjectInfo:
    """Holds information about discovered Claude Code resources in a directory."""
    root_path: Path
    commands_dir: Optional[Path] = None
    command_files: List[Path] = field(default_factory=list)
    skills_dir: Optional[Path] = None
    rules_file: Optional[Path] = None
    mcp_file: Optional[Path] = None
    plugin_manifest: Optional[Path] = None

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
    def is_claude_project(self) -> bool:
        return (
            self.has_commands
            or self.has_rules
            or self.has_mcp
            or self.has_skills
            or self.plugin_manifest is not None
        )

    def summary(self) -> str:
        """Return a formatted string describing the detected resources."""
        lines = [f"Analysis of: {self.root_path}"]
        if not self.is_claude_project:
            lines.append("  [!] No standard Claude Code components detected.")
            return "\n".join(lines)

        lines.append("  [+] Claude Code components found:")
        if self.has_commands:
            lines.append(f"    - Commands ({len(self.command_files)} files) at: {self.commands_dir}")
            for cmd in self.command_files[:5]:
                lines.append(f"        /{cmd.stem}")
            if len(self.command_files) > 5:
                lines.append(f"        ... and {len(self.command_files) - 5} more")

        if self.has_rules:
            lines.append(f"    - Project Rules at: {self.rules_file}")

        if self.has_mcp:
            lines.append(f"    - MCP Server Config at: {self.mcp_file}")

        if self.has_skills:
            lines.append(f"    - Existing Skills at: {self.skills_dir}")

        if self.plugin_manifest:
            lines.append(f"    - Plugin Manifest at: {self.plugin_manifest}")

        return "\n".join(lines)


def detect_claude_project(target_path: Path) -> ClaudeProjectInfo:
    """Inspect target_path and locate all Claude Code assets."""
    target_path = target_path.resolve()
    info = ClaudeProjectInfo(root_path=target_path)

    if not target_path.exists():
        return info

    # If target is directly a single command markdown file
    if target_path.is_file() and target_path.suffix.lower() == ".md":
        if target_path.name.upper() == "CLAUDE.MD":
            info.rules_file = target_path
        else:
            info.command_files.append(target_path)
            info.commands_dir = target_path.parent
        return info

    # Check for commands directory
    candidate_cmd_dirs = [
        target_path / "commands",
        target_path / ".claude" / "commands",
        target_path / "prompts",
    ]
    for c_dir in candidate_cmd_dirs:
        if c_dir.exists() and c_dir.is_dir():
            info.commands_dir = c_dir
            info.command_files.extend(sorted(c_dir.glob("*.md")))
            break

    # Check for existing skills directory
    candidate_skill_dirs = [
        target_path / "skills",
        target_path / ".claude" / "skills",
    ]
    for s_dir in candidate_skill_dirs:
        if s_dir.exists() and s_dir.is_dir():
            info.skills_dir = s_dir
            break

    # Check for project rules (CLAUDE.md)
    candidate_rules = [
        target_path / "CLAUDE.md",
        target_path / ".claude" / "CLAUDE.md",
        target_path / "rules" / "CLAUDE.md",
    ]
    for r_file in candidate_rules:
        if r_file.exists() and r_file.is_file():
            info.rules_file = r_file
            break

    # Check for MCP configuration (.mcp.json or mcp.json)
    candidate_mcp = [
        target_path / ".mcp.json",
        target_path / "mcp.json",
        target_path / ".claude" / "mcp.json",
    ]
    for m_file in candidate_mcp:
        if m_file.exists() and m_file.is_file():
            info.mcp_file = m_file
            break

    # Check for plugin manifest
    candidate_manifests = [
        target_path / "plugin.json",
        target_path / "manifest.json",
        target_path / ".claude" / "plugin.json",
    ]
    for mf in candidate_manifests:
        if mf.exists() and mf.is_file():
            info.plugin_manifest = mf
            break

    return info
