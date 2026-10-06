"""Full Plugin packager and migrator for converting Claude Code plugins to Antigravity plugins."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from cc2agy.converters.commands import (
    claim_skill_name,
    command_skill_name,
    convert_command_file,
    convert_command_text,
    convert_commands_directory,
    sanitize_skill_name,
)
from cc2agy.converters.hooks import write_hooks_data
from cc2agy.converters.mcp import extract_servers_dict, write_mcp_data
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


def sanitize_skill_content(content: str, plugin_root: Optional[Path] = None) -> str:
    """Replace ${CLAUDE_PLUGIN_ROOT} references in SKILL.md.

    With plugin_root, the variable becomes that absolute folder (forward slashes): paths in a
    skill are followed by the agent from wherever it runs commands, which Antigravity does not
    tie to the skill folder. Without plugin_root, the legacy relative form (../..) is kept,
    since skills reside in skills/<skill_name>/SKILL.md.
    """
    if not content:
        return content
    root = plugin_root.as_posix() if plugin_root is not None else "../.."
    return re.sub(r"\$\{?CLAUDE_PLUGIN_ROOT\}?", lambda _: root, content)


def find_plugin_manifest(source_dir: Path) -> Optional[Path]:
    """Locate the Claude Code plugin manifest (.claude-plugin/plugin.json only)."""
    return _find_case_insensitive(source_dir / CLAUDE_PLUGIN_DIR, "plugin.json")


def _manifest_entries(value: Any) -> List[Any]:
    """Normalize a plugin.json component field (single value or array) into a list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _resolve_component_path(source_dir: Path, raw: Any, field: str, warnings: List[str]) -> Optional[Path]:
    """Resolve a plugin.json component path relative to the plugin root.

    Mirrors Claude Code's rules: the path must stay inside the plugin folder and exist.
    """
    if not isinstance(raw, str) or not raw.strip():
        warnings.append(f"plugin.json '{field}': unsupported entry {raw!r}; skipped.")
        return None
    candidate = (source_dir / raw).resolve()
    if not candidate.is_relative_to(source_dir):
        warnings.append(f"plugin.json '{field}': path '{raw}' escapes the plugin folder; skipped.")
        return None
    if not candidate.exists():
        warnings.append(f"plugin.json '{field}': path '{raw}' not found; skipped.")
        return None
    return candidate


def _read_json(path: Path) -> Any:
    """Load a JSON file, raising ValueError that names the file on any read/parse failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"Failed to read/parse JSON from {path}: {e}") from e


def _merge_hook_events(
    hook_events: Dict[str, List[Any]], raw: Any, origin: str, warnings: List[str]
) -> None:
    """Append the event handlers in `raw` (with or without a "hooks" wrapper) to hook_events."""
    events = raw.get("hooks", raw) if isinstance(raw, dict) else None
    if not isinstance(events, dict):
        warnings.append(f"Hooks in {origin} are not an object of events; skipped.")
        return
    for event, items in events.items():
        if isinstance(items, list):
            hook_events.setdefault(event, []).extend(items)
        else:
            warnings.append(f"Hook event '{event}' in {origin} does not contain a list of handlers.")


def _convert_declared_commands(
    declared: Any,
    source_dir: Path,
    skills_dest: Path,
    overwrite: bool,
    skip_names: Set[str],
    warnings: List[str],
    claimed: Dict[str, str],
) -> int:
    """Convert the commands declared in plugin.json (path, array of paths, or name map)."""
    converted = 0

    if isinstance(declared, dict):
        for name, spec in declared.items():
            skill_name = sanitize_skill_name(name)
            if skill_name in skip_names:
                continue
            if not isinstance(spec, dict):
                warnings.append(f"plugin.json 'commands.{name}' is not an object; skipped.")
                continue
            description = spec.get("description") if isinstance(spec.get("description"), str) else None
            try:
                if isinstance(spec.get("content"), str):
                    skill_name = claim_skill_name(
                        skill_name, f"plugin.json commands.{name}", claimed, skip_names, warnings
                    )
                    convert_command_text(
                        spec["content"], skills_dest, default_name=name,
                        custom_name=skill_name, overwrite=overwrite, description=description,
                    )
                elif "source" in spec:
                    path = _resolve_component_path(source_dir, spec["source"], f"commands.{name}", warnings)
                    if path is None:
                        continue
                    skill_name = claim_skill_name(
                        skill_name, f"plugin.json commands.{name}", claimed, skip_names, warnings
                    )
                    convert_command_file(
                        path, skills_dest, custom_name=skill_name, overwrite=overwrite, description=description
                    )
                else:
                    warnings.append(f"plugin.json 'commands.{name}' needs 'source' or 'content'; skipped.")
                    continue
                converted += 1
            except FileExistsError:
                continue
        return converted

    for raw in _manifest_entries(declared):
        path = _resolve_component_path(source_dir, raw, "commands", warnings)
        if path is None:
            continue
        if path.is_dir():
            converted += len(
                convert_commands_directory(
                    path, skills_dest, overwrite=overwrite, skip_names=skip_names,
                    claimed=claimed, warnings=warnings,
                )
            )
        else:
            skill_name = command_skill_name(path)
            if skill_name in skip_names:
                continue
            skill_name = claim_skill_name(skill_name, str(path), claimed, skip_names, warnings)
            try:
                convert_command_file(path, skills_dest, custom_name=skill_name, overwrite=overwrite)
                converted += 1
            except FileExistsError:
                continue
    return converted


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

    warnings: List[str] = summary["warnings"]

    # Migrate modular skills first (prioritize rich, multi-file modular skill definitions).
    # plugin.json "skills" adds directories to the default skills/ scan.
    skill_dirs: List[Path] = []
    source_skills_dir = source_dir / "skills"
    if not source_skills_dir.exists():
        source_skills_dir = source_dir / ".claude" / "skills"
    if source_skills_dir.exists() and source_skills_dir.is_dir():
        skill_dirs.append(source_skills_dir.resolve())
    for raw in _manifest_entries(manifest_data.get("skills")):
        path = _resolve_component_path(source_dir, raw, "skills", warnings)
        if path is None:
            continue
        if not path.is_dir():
            warnings.append(f"plugin.json 'skills': '{raw}' is not a directory; skipped.")
        elif path not in skill_dirs:
            skill_dirs.append(path)

    modular_skill_names: Set[str] = set()
    for s_dir in skill_dirs:
        sk_results = migrate_skills_directory(s_dir, skills_dest, overwrite=overwrite)
        summary["skills_migrated"] += len(sk_results)
        modular_skill_names.update(r.parent.name if r.is_file() else r.name for r in sk_results)

    # Convert commands, honoring overwrite, but never replacing a modular skill of the same name.
    # plugin.json "commands" replaces the default commands/ scan.
    claimed_names: Dict[str, str] = {}
    if "commands" in manifest_data:
        summary["skills_migrated"] += _convert_declared_commands(
            manifest_data["commands"], source_dir, skills_dest, overwrite, modular_skill_names, warnings,
            claimed_names,
        )
    else:
        commands_dir = source_dir / "commands"
        if not commands_dir.exists():
            commands_dir = source_dir / ".claude" / "commands"
        if commands_dir.exists() and commands_dir.is_dir():
            cmd_results = convert_commands_directory(
                commands_dir, skills_dest, overwrite=overwrite, skip_names=modular_skill_names,
                claimed=claimed_names, warnings=warnings,
            )
            summary["skills_migrated"] += len(cmd_results)

    # Sanitize ${CLAUDE_PLUGIN_ROOT} in all SKILL.md files
    for skill_file in skills_dest.rglob("*.md"):
        if skill_file.is_file() and skill_file.name.lower() == "skill.md":
            try:
                content = skill_file.read_text(encoding="utf-8", errors="ignore")
                if "CLAUDE_PLUGIN_ROOT" in content:
                    updated = sanitize_skill_content(content, target_plugin_dir)
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

    # 6. Migrate MCP config to mcp_config.json: the default file first, then plugin.json
    # "mcpServers" entries in order (a server name declared later replaces an earlier one)
    mcp_candidates = [
        source_dir / ".mcp.json",
        source_dir / "mcp.json",
        source_dir / ".claude.json",
        source_dir / ".claude" / "mcp.json",
    ]
    mcp_servers: Dict[str, Any] = {}
    mcp_sources = 0
    for m_cand in mcp_candidates:
        if m_cand.exists() and m_cand.is_file():
            mcp_servers.update(extract_servers_dict(_read_json(m_cand)))
            mcp_sources += 1
            break
    for raw in _manifest_entries(manifest_data.get("mcpServers")):
        if isinstance(raw, dict):
            mcp_servers.update(extract_servers_dict(raw))
            mcp_sources += 1
        elif isinstance(raw, str) and raw.lower().endswith((".mcpb", ".dxt")):
            warnings.append(f"plugin.json 'mcpServers': MCP bundle '{raw}' cannot be converted; skipped.")
        else:
            path = _resolve_component_path(source_dir, raw, "mcpServers", warnings)
            if path is not None:
                mcp_servers.update(extract_servers_dict(_read_json(path)))
                mcp_sources += 1
    if mcp_sources:
        try:
            res, w = write_mcp_data({"mcpServers": mcp_servers}, target_plugin_dir, overwrite=overwrite)
            summary["mcp_migrated"] += 1
            warnings.extend(w)
        except FileExistsError:
            warnings.append("MCP config already exists in plugin; skipped.")

    # 7. Migrate Hooks to hooks.json: the default file merged with plugin.json "hooks"
    # entries (file paths carry a top-level "hooks" wrapper; inline objects are the event map)
    hooks_candidates = [
        source_dir / "hooks" / "hooks.json",
        source_dir / "hooks.json",
        source_dir / ".claude" / "hooks.json",
    ]
    hook_events: Dict[str, List[Any]] = {}
    hook_sources = 0
    for h_cand in hooks_candidates:
        if h_cand.exists() and h_cand.is_file():
            _merge_hook_events(hook_events, _read_json(h_cand), h_cand.name, warnings)
            hook_sources += 1
            break
    for raw in _manifest_entries(manifest_data.get("hooks")):
        if isinstance(raw, dict):
            _merge_hook_events(hook_events, raw, "plugin.json", warnings)
            hook_sources += 1
        else:
            path = _resolve_component_path(source_dir, raw, "hooks", warnings)
            if path is not None:
                _merge_hook_events(hook_events, _read_json(path), path.name, warnings)
                hook_sources += 1
    if hook_sources:
        try:
            res, w = write_hooks_data(
                hook_events,
                target_plugin_dir,
                plugin_name=plugin_name,
                overwrite=overwrite,
            )
            summary["hooks_migrated"] += 1
            warnings.extend(w)
        except FileExistsError:
            warnings.append("Hooks file already exists in plugin; skipped.")

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
