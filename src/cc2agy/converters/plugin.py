"""Full Plugin packager and migrator for converting Claude Code plugins to Antigravity plugins."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from cc2agy.converters.agents import convert_agent_file, convert_agents_directory
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
from cc2agy.converters.variables import (
    DATA_DIR_NAME,
    VARIABLE_MARKERS,
    PluginVariables,
    resolve_user_config,
    scripts_read_environment,
    substitute,
)
from cc2agy.detector import CLAUDE_PLUGIN_DIR, _find_case_insensitive


# Claude Code plugin components with no Antigravity counterpart (an Antigravity plugin holds
# only plugin.json, mcp_config.json, hooks.json, skills/, agents/ and rules/): label, default
# location under the plugin root, plugin.json keys that declare them, and an extra note.
UNSUPPORTED_COMPONENTS: List[Tuple[str, Optional[str], Tuple[str, ...], str]] = [
    ("Output styles", "output-styles", ("outputStyles",), ""),
    ("LSP servers", ".lsp.json", ("lspServers",), ""),
    ("Workflows", "workflows", ("workflows",), ""),
    ("Themes", "themes", ("experimental.themes", "themes"), ""),
    ("Monitors", "monitors/monitors.json", ("experimental.monitors", "monitors"), ""),
    ("Plugin settings", "settings.json", ("settings",), ""),
    ("Channels", None, ("channels",), ""),
    ("Dependencies", None, ("dependencies",), " Convert and install the plugins it depends on separately."),
]

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
    "agents",
    "rules",
    "output-styles",
    "workflows",
    "themes",
    "monitors",
}
# Root files not copied: files Antigravity would read as the converted plugin's own
# configuration, source files already converted (copying .mcp.json would also duplicate any
# credentials in it), and components with no equivalent (they are reported instead).
# Every other root file (server.py, package.json, .env ...) is copied, as Claude Code keeps
# the whole plugin folder.
NOT_COPIED_FILES = {
    "plugin.json",
    "hooks.json",
    "mcp_config.json",
    ".mcp.json",
    "mcp.json",
    ".claude.json",
    "claude.md",
    "settings.json",
    ".lsp.json",
}


def sanitize_skill_content(
    content: str,
    plugin_root: Optional[Path] = None,
    variables: Optional[PluginVariables] = None,
    warnings: Optional[List[str]] = None,
) -> str:
    """Replace Claude Code plugin variables in skill, command or agent content.

    With variables, every variable is resolved (see variables.substitute, 'markdown').
    Otherwise only ${CLAUDE_PLUGIN_ROOT} is replaced: with plugin_root, by that absolute
    folder (forward slashes), since paths in a skill are followed by the agent from wherever
    it runs commands, which Antigravity does not tie to the skill folder; without it, by the
    legacy relative form (../..), since skills reside in skills/<skill_name>/SKILL.md.
    """
    if not content:
        return content
    if variables is not None:
        return substitute(content, variables, "markdown", warnings if warnings is not None else [])
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


def _warn_unsupported_components(source_dir: Path, manifest_data: Dict[str, Any], warnings: List[str]) -> None:
    """Warn once per component that Antigravity plugins cannot hold (see UNSUPPORTED_COMPONENTS)."""
    experimental = manifest_data.get("experimental")
    for label, default, keys, note in UNSUPPORTED_COMPONENTS:
        origins: List[str] = []
        if default is not None:
            path = source_dir / default
            if path.is_dir():
                origins.append(f"{default}/")
            elif path.is_file():
                origins.append(default)
        for key in keys:
            if key.startswith("experimental."):
                value = experimental.get(key.split(".", 1)[1]) if isinstance(experimental, dict) else None
            else:
                value = manifest_data.get(key)
            if value not in (None, "", [], {}):
                origins.append(f"plugin.json '{key}'")
        if origins:
            warnings.append(
                f"{label} ({', '.join(origins)}): no Antigravity plugin equivalent; not converted.{note}"
            )


def _read_json(path: Path) -> Any:
    """Load a JSON file, raising ValueError that names the file on any read/parse failure."""
    try:
        # utf-8-sig also reads files saved with a BOM (Windows PowerShell 5.1)
        with open(path, "r", encoding="utf-8-sig") as f:
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
                        warnings=warnings, manifest_spec=spec, label=f"plugin.json commands.{name}",
                    )
                elif "source" in spec:
                    path = _resolve_component_path(source_dir, spec["source"], f"commands.{name}", warnings)
                    if path is None:
                        continue
                    skill_name = claim_skill_name(
                        skill_name, f"plugin.json commands.{name}", claimed, skip_names, warnings
                    )
                    convert_command_file(
                        path, skills_dest, custom_name=skill_name, overwrite=overwrite, description=description,
                        warnings=warnings, manifest_spec=spec,
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
            skill_name = command_skill_name(path, warnings=warnings)
            if skill_name in skip_names:
                continue
            skill_name = claim_skill_name(skill_name, str(path), claimed, skip_names, warnings)
            try:
                convert_command_file(path, skills_dest, custom_name=skill_name, overwrite=overwrite, warnings=warnings)
                converted += 1
            except FileExistsError:
                continue
    return converted


def convert_plugin(
    source_dir: Path,
    dest_dir: Path,
    overwrite: bool = False,
    as_subfolder: bool = True,
    user_config: Optional[Dict[str, str]] = None,
) -> Tuple[Path, Dict[str, Any]]:
    """Convert an entire Claude Code plugin to canonical Antigravity plugin structure.

    user_config: values for plugin.json userConfig keys (Antigravity cannot prompt for them);
    a key without a value falls back to its declared default.

    Resulting Antigravity structure:
    plugins/<plugin_name>/
    ├── plugin.json
    ├── mcp_config.json   (optional)
    ├── hooks.json        (optional)
    ├── rules/            (optional)
    │   └── AGENTS.md
    ├── skills/           (optional)
    │   └── <skill>/SKILL.md
    ├── agents/           (optional)
    │   └── <agent>.md
    └── ...               (every other plugin folder and root file, copied; see NOT_COPIED_DIRS
                           and NOT_COPIED_FILES)
    """
    source_dir = source_dir.resolve()
    dest_dir = dest_dir.resolve()

    if not source_dir.exists() or not source_dir.is_dir():
        raise ValueError(f"Source plugin directory does not exist: {source_dir}")

    # 1. Read manifest or fallback to directory name
    manifest_file = find_plugin_manifest(source_dir)
    manifest_data: Dict[str, Any] = {}
    if manifest_file:
        # An unreadable manifest stops the conversion: its name, components and userConfig
        # would otherwise be lost without notice
        manifest_data = _read_json(manifest_file)
        if not isinstance(manifest_data, dict):
            raise ValueError(f"Plugin manifest {manifest_file} does not hold a JSON object")

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
        "agents_migrated": 0,
        "auxiliary_dirs_copied": [],
        "warnings": [],
    }

    warnings: List[str] = summary["warnings"]

    # What ${CLAUDE_PLUGIN_ROOT}, ${CLAUDE_PLUGIN_DATA}, ${CLAUDE_PROJECT_DIR} and
    # ${user_config.KEY} become in this plugin
    values, sensitive, declared = resolve_user_config(manifest_data.get("userConfig"), user_config or {}, warnings)
    variables = PluginVariables(
        root=target_plugin_dir,
        data_dir=target_plugin_dir / DATA_DIR_NAME,
        values=values,
        sensitive=sensitive,
        declared=declared,
        plugin=True,
        scripts_read_env=scripts_read_environment(source_dir),
    )

    # 3. Write canonical Antigravity plugin.json. Its schema allows only name and description
    # ("additionalProperties": false), so version, author and the rest are not carried over.
    canonical_manifest: Dict[str, Any] = {
        "name": plugin_name,
    }
    if isinstance(manifest_data.get("description"), str):
        canonical_manifest["description"] = manifest_data["description"]

    with open(target_plugin_manifest, "w", encoding="utf-8") as f:
        json.dump(canonical_manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    summary["manifest"] = target_plugin_manifest

    # 4. Migrate Skills & Commands into skills/
    skills_dest = target_plugin_dir / "skills"
    skills_dest.mkdir(parents=True, exist_ok=True)

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
        sk_results = migrate_skills_directory(s_dir, skills_dest, overwrite=overwrite, warnings=warnings)
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

    # Resolve plugin variables and userConfig in all SKILL.md files
    for skill_file in skills_dest.rglob("*.md"):
        if skill_file.is_file() and skill_file.name.lower() == "skill.md":
            try:
                content = skill_file.read_text(encoding="utf-8-sig", errors="ignore")
                if any(marker in content for marker in VARIABLE_MARKERS):
                    updated = sanitize_skill_content(content, variables=variables, warnings=warnings)
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
            res, w = write_mcp_data(
                {"mcpServers": mcp_servers}, target_plugin_dir, overwrite=overwrite, variables=variables
            )
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
                variables=variables,
            )
            summary["hooks_migrated"] += 1
            warnings.extend(w)
        except FileExistsError:
            warnings.append("Hooks file already exists in plugin; skipped.")

    # 8. Convert subagents into agents/. plugin.json "agents" (.md files only) replaces the
    # default agents/ scan, and its files load without subfolder names.
    agents_dest = target_plugin_dir / "agents"
    agent_claimed: Dict[str, str] = {}
    agent_files: List[Path] = []
    if "agents" in manifest_data:
        for raw in _manifest_entries(manifest_data["agents"]):
            path = _resolve_component_path(source_dir, raw, "agents", warnings)
            if path is None:
                continue
            if path.is_file() and path.suffix.lower() == ".md":
                try:
                    result = convert_agent_file(
                        path, agents_dest, agent_claimed, warnings, plugin_name=plugin_name, overwrite=overwrite
                    )
                except FileExistsError:
                    result = None
                if result is not None:
                    agent_files.append(result)
            else:
                warnings.append(f"plugin.json 'agents': '{raw}' is not a .md file; skipped.")
    else:
        source_agents_dir = source_dir / "agents"
        if source_agents_dir.is_dir():
            agent_files = convert_agents_directory(
                source_agents_dir, agents_dest, agent_claimed, warnings, plugin_name=plugin_name, overwrite=overwrite
            )
    for agent_file in agent_files:
        content = agent_file.read_text(encoding="utf-8")
        if any(marker in content for marker in VARIABLE_MARKERS):
            agent_file.write_text(
                sanitize_skill_content(content, variables=variables, warnings=warnings), encoding="utf-8"
            )
    summary["agents_migrated"] = len(agent_files)

    # 9. Copy the other plugin folders (scripts, MCP servers, templates, bin, etc.)
    for item in sorted(source_dir.iterdir()):
        if not item.is_dir():
            continue
        item_lower = item.name.lower()
        if item_lower == "rules":
            extra = [p.name for p in item.iterdir() if p.name.lower() != "claude.md"]
            if extra:
                warnings.append(
                    f"{item.name}/ not copied: Antigravity would load its files as active rules "
                    f"({', '.join(sorted(extra))})."
                )
            continue
        # A destination inside the plugin folder (e.g. ./output) must not be copied into itself
        if item_lower in NOT_COPIED_DIRS or item_lower.startswith(".git") or target_plugin_dir.is_relative_to(item):
            continue
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
            if item_lower == "bin":
                warnings.append(
                    f"{item.name}/ copied, but Antigravity does not put it on PATH: calls to its "
                    f"executables by bare name will fail; use the full path ({dest_aux.as_posix()}/<file>)."
                )
        except Exception as e:
            summary["warnings"].append(f"Failed to copy auxiliary directory '{item.name}': {e}")

    # 10. Copy the other root files (MCP servers, package.json, scripts, docs, etc.)
    for item in sorted(source_dir.iterdir()):
        item_lower = item.name.lower()
        if not item.is_file() or item_lower in NOT_COPIED_FILES or item_lower.startswith(".git"):
            continue
        aux_dest = target_plugin_dir / item.name
        if aux_dest.exists() and not overwrite:
            continue
        try:
            shutil.copy2(item, aux_dest)
        except Exception as e:
            summary["warnings"].append(f"Failed to copy root file '{item.name}': {e}")
            continue
        if item_lower == ".env" or item_lower.startswith(".env."):
            warnings.append(
                f"{item.name} copied into the converted plugin: it may hold passwords or keys in plain text."
            )
        elif item_lower in ("agents.md", "gemini.md"):
            warnings.append(
                f"{item.name} copied to the plugin root; Antigravity's documentation does not say whether "
                "it is loaded there as a rule."
            )

    # 11. Warn about components Antigravity plugins cannot hold
    _warn_unsupported_components(source_dir, manifest_data, warnings)

    return target_plugin_dir, summary
