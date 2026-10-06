"""Full Plugin packager and migrator for converting Claude Code plugins to Antigravity plugins."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from cc2agy.converters.commands import (
    convert_command_file,
    convert_commands_directory,
    sanitize_skill_name,
)
from cc2agy.converters.hooks import convert_hooks_file
from cc2agy.converters.mcp import convert_mcp_file
from cc2agy.converters.rules import convert_rules_file
from cc2agy.converters.skills import migrate_skills_directory
from cc2agy.detector import CLAUDE_PLUGIN_DIR, _find_case_insensitive


AUXILIARY_DIRS = {
    "scripts",
    "templates",
    "espec",
    "agents",
    "hooks",
    "resources",
    "references",
    "docs",
    "context",
}


def sanitize_skill_content(content: str) -> str:
    """Sanitize ${CLAUDE_PLUGIN_ROOT} references in SKILL.md.

    Since skills in a plugin reside in skills/<skill_name>/SKILL.md,
    the relative path back to the plugin root is ../../.
    """
    if not content:
        return content

    # Replace ${CLAUDE_PLUGIN_ROOT}/ or $CLAUDE_PLUGIN_ROOT/ with ../../
    cleaned = re.sub(r"\$\{?CLAUDE_PLUGIN_ROOT\}?/", "../../", content)
    # Replace standalone ${CLAUDE_PLUGIN_ROOT} with ../..
    cleaned = re.sub(r"\$\{?CLAUDE_PLUGIN_ROOT\}?", "../..", cleaned)
    return cleaned


def find_plugin_manifest(source_dir: Path) -> Optional[Path]:
    """Locate the Claude Code plugin manifest (.claude-plugin/plugin.json only)."""
    return _find_case_insensitive(source_dir / CLAUDE_PLUGIN_DIR, "plugin.json")


def convert_plugin(
    source_dir: Path,
    dest_dir: Path,
    overwrite: bool = False,
    as_subfolder: bool = True,
) -> Tuple[Path, Dict[str, Any]]:
    """Convert an entire Claude Code plugin to canonical Antigravity plugin structure.

    Resulting Antigravity structure:
    plugins/<plugin_name>/
    ├── plugin.json
    ├── mcp_config.json   (optional)
    ├── hooks.json        (optional)
    ├── rules/            (optional)
    │   └── AGENTS.md
    ├── skills/           (optional)
    │   └── <skill>/SKILL.md
    ├── scripts/          (preserved)
    ├── templates/        (preserved)
    └── ...               (auxiliary dirs preserved)
    """
    source_dir = source_dir.resolve()
    dest_dir = dest_dir.resolve()

    if not source_dir.exists() or not source_dir.is_dir():
        raise ValueError(f"Source plugin directory does not exist: {source_dir}")

    # 1. Read manifest or fallback to directory name
    manifest_file = find_plugin_manifest(source_dir)
    manifest_data: Dict[str, Any] = {}
    if manifest_file:
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception:
            manifest_data = {}

    raw_name = manifest_data.get("name") or source_dir.name
    plugin_name = sanitize_skill_name(raw_name)

    # 2. Determine target plugin directory
    if dest_dir.name == plugin_name or sanitize_skill_name(dest_dir.name) == plugin_name:
        target_plugin_dir = dest_dir
    elif dest_dir.name == "plugins":
        target_plugin_dir = dest_dir / plugin_name
    elif not as_subfolder:
        target_plugin_dir = dest_dir
    else:
        target_plugin_dir = dest_dir / "plugins" / plugin_name

    target_plugin_manifest = target_plugin_dir / "plugin.json"
    if target_plugin_manifest.exists() and not overwrite:
        raise FileExistsError(
            f"Target plugin manifest already exists: {target_plugin_manifest}. Use overwrite=True to replace."
        )

    target_plugin_dir.mkdir(parents=True, exist_ok=True)

    summary: Dict[str, Any] = {
        "plugin_name": plugin_name,
        "plugin_path": target_plugin_dir,
        "manifest": None,
        "skills_migrated": 0,
        "rules_migrated": 0,
        "mcp_migrated": 0,
        "hooks_migrated": 0,
        "auxiliary_dirs_copied": [],
        "warnings": [],
    }

    # 3. Write canonical Antigravity plugin.json
    canonical_manifest: Dict[str, Any] = {
        "name": plugin_name,
    }
    for field_name in ["description", "version", "author", "keywords", "homepage", "repository", "license"]:
        if field_name in manifest_data:
            canonical_manifest[field_name] = manifest_data[field_name]

    with open(target_plugin_manifest, "w", encoding="utf-8") as f:
        json.dump(canonical_manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    summary["manifest"] = target_plugin_manifest

    # 4. Migrate Skills & Commands into skills/
    skills_dest = target_plugin_dir / "skills"
    skills_dest.mkdir(parents=True, exist_ok=True)

    # Migrate modular skills first (prioritize rich, multi-file modular skill definitions)
    modular_skill_names: Set[str] = set()
    source_skills_dir = source_dir / "skills"
    if not source_skills_dir.exists():
        source_skills_dir = source_dir / ".claude" / "skills"
    if source_skills_dir.exists() and source_skills_dir.is_dir():
        sk_results = migrate_skills_directory(source_skills_dir, skills_dest, overwrite=overwrite)
        summary["skills_migrated"] += len(sk_results)
        modular_skill_names = {r.parent.name if r.is_file() else r.name for r in sk_results}

    # Convert commands, honoring overwrite, but never replacing a modular skill of the same name
    commands_dir = source_dir / "commands"
    if not commands_dir.exists():
        commands_dir = source_dir / ".claude" / "commands"
    if commands_dir.exists() and commands_dir.is_dir():
        cmd_results = convert_commands_directory(
            commands_dir, skills_dest, overwrite=overwrite, skip_names=modular_skill_names
        )
        summary["skills_migrated"] += len(cmd_results)

    # Sanitize ${CLAUDE_PLUGIN_ROOT} in all SKILL.md files
    for skill_file in skills_dest.rglob("*.md"):
        if skill_file.is_file() and skill_file.name.lower() == "skill.md":
            try:
                content = skill_file.read_text(encoding="utf-8", errors="ignore")
                if "CLAUDE_PLUGIN_ROOT" in content:
                    updated = sanitize_skill_content(content)
                    skill_file.write_text(updated, encoding="utf-8")
            except Exception as e:
                summary["warnings"].append(f"Could not sanitize skill {skill_file.name}: {e}")

    # 5. Migrate Rules to rules/AGENTS.md
    rules_candidates = [
        source_dir / "CLAUDE.md",
        source_dir / ".claude" / "CLAUDE.md",
        source_dir / "rules" / "CLAUDE.md",
    ]
    for r_cand in rules_candidates:
        if r_cand.exists() and r_cand.is_file():
            rules_dest = target_plugin_dir / "rules"
            try:
                res, w = convert_rules_file(r_cand, rules_dest, overwrite=overwrite)
                summary["rules_migrated"] += 1
                summary["warnings"].extend(w)
            except FileExistsError:
                summary["warnings"].append("Rules file already exists in plugin; skipped.")
            break

    # 6. Migrate MCP config to mcp_config.json
    mcp_candidates = [
        source_dir / ".mcp.json",
        source_dir / "mcp.json",
        source_dir / ".claude.json",
        source_dir / ".claude" / "mcp.json",
    ]
    for m_cand in mcp_candidates:
        if m_cand.exists() and m_cand.is_file():
            try:
                res, w = convert_mcp_file(m_cand, target_plugin_dir, overwrite=overwrite)
                summary["mcp_migrated"] += 1
                summary["warnings"].extend(w)
            except FileExistsError:
                summary["warnings"].append("MCP config already exists in plugin; skipped.")
            break

    # 7. Migrate Hooks to hooks.json
    hooks_candidates = [
        source_dir / "hooks" / "hooks.json",
        source_dir / "hooks.json",
        source_dir / ".claude" / "hooks.json",
    ]
    for h_cand in hooks_candidates:
        if h_cand.exists() and h_cand.is_file():
            try:
                res, w = convert_hooks_file(
                    h_cand,
                    target_plugin_dir,
                    plugin_name=plugin_name,
                    overwrite=overwrite,
                )
                summary["hooks_migrated"] += 1
                summary["warnings"].extend(w)
            except FileExistsError:
                summary["warnings"].append("Hooks file already exists in plugin; skipped.")
            break

    # 8. Copy auxiliary directories (scripts, templates, espec, agents, etc.)
    for item in sorted(source_dir.iterdir()):
        if not item.is_dir():
            continue
        item_lower = item.name.lower()
        if item_lower in AUXILIARY_DIRS:
            dest_aux = target_plugin_dir / item.name
            try:
                shutil.copytree(
                    item,
                    dest_aux,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git*"),
                )
                # If hooks directory was copied, remove hooks.json inside it to avoid duplicate configuration
                if item_lower == "hooks":
                    nested_hooks_json = dest_aux / "hooks.json"
                    if nested_hooks_json.exists():
                        try:
                            nested_hooks_json.unlink()
                        except OSError:
                            pass

                summary["auxiliary_dirs_copied"].append(item.name)
            except Exception as e:
                summary["warnings"].append(f"Failed to copy auxiliary directory '{item.name}': {e}")

    # 9. Copy auxiliary root documentation / license files
    auxiliary_files = ["README.md", "LICENSE", "LICENSE.md", "CHANGELOG.md"]
    for aux_name in auxiliary_files:
        aux_src = _find_case_insensitive(source_dir, aux_name)
        if aux_src and aux_src.is_file():
            aux_dest = target_plugin_dir / aux_src.name
            if not aux_dest.exists() or overwrite:
                try:
                    shutil.copy2(aux_src, aux_dest)
                except Exception as e:
                    summary["warnings"].append(f"Failed to copy auxiliary file '{aux_src.name}': {e}")

    return target_plugin_dir, summary
