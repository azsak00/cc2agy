"""Converter for Claude Code subagents to Google Antigravity custom subagents.

Claude Code defines subagents as Markdown files with YAML frontmatter in `.claude/agents/`
(project) or a plugin's `agents/`. Antigravity reads the same shape from `.agents/agents/`
or `plugins/<name>/agents/`, but with its own tool names and model tiers. Antigravity
documents that an unknown tool name in `tools` may hang the subagent, so tools without an
equivalent are removed instead of copied.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cc2agy.converters.commands import claim_skill_name, escape_yaml_string, sanitize_skill_name


# Claude Code tool -> Antigravity tools (names from antigravity.google/docs/hooks).
TOOL_MAP: Dict[str, List[str]] = {
    "Read": ["view_file"],
    "Write": ["write_to_file"],
    "Edit": ["replace_file_content", "multi_replace_file_content"],
    "Glob": ["find_by_name", "list_dir"],
    "Grep": ["grep_search"],
    "Bash": ["run_command"],
    "PowerShell": ["run_command"],
    "WebFetch": ["read_url_content"],
    "WebSearch": ["search_web"],
    "Agent": ["invoke_subagent"],
    "SendMessage": ["send_message"],
}

# Every tool Antigravity documents; used to turn a Claude Code denylist into an allowlist.
ANTIGRAVITY_TOOLS: List[str] = [
    "view_file",
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
    "list_dir",
    "find_by_name",
    "grep_search",
    "search_web",
    "read_url_content",
    "run_command",
    "manage_task",
    "schedule",
    "list_permissions",
    "ask_permission",
    "invoke_subagent",
    "define_subagent",
    "send_message",
    "manage_subagents",
    "ask_question",
    "generate_image",
]

CONVERTED_FIELDS = {"name", "description", "tools", "disallowedTools", "model", "skills"}

_BLOCK_SCALARS = (">-", ">", "|", "|-", ">+", "|+")


def parse_agent_frontmatter(content: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Split an agent file into (frontmatter, body); frontmatter is None when the file has none.

    Values are strings, lists (block `- item` or inline `[a, b]`) or, for nested maps such as
    `hooks` and `mcpServers`, the raw indented text (those fields are only reported, not converted).
    """
    match = re.match(r"---\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n(.*))?$", content, re.DOTALL)
    if not match:
        return None, content.strip()

    lines = match.group(1).splitlines()
    body = match.group(2) or ""
    meta: Dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#") or line[0] in " \t" or ":" not in line:
            i += 1
            continue
        key, val = (part.strip() for part in line.split(":", 1))
        i += 1
        block: List[str] = []
        while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t" or lines[i].startswith("-")):
            block.append(lines[i])
            i += 1
        items = [b.strip() for b in block if b.strip()]
        if val in _BLOCK_SCALARS:
            meta[key] = (" " if val.startswith(">") else "\n").join(items)
        elif val.startswith("[") and val.endswith("]"):
            meta[key] = [_unquote(v) for v in val[1:-1].split(",") if v.strip()]
        elif val:
            meta[key] = _unquote(val)
        elif items and all(item.startswith("- ") or item == "-" for item in items):
            meta[key] = [_unquote(item[1:]) for item in items if item[1:].strip()]
        else:
            meta[key] = "\n".join(block)
    return meta, body.strip()


def _unquote(value: str) -> str:
    return value.strip().strip("\"'")


def _tool_entries(value: Any) -> List[str]:
    """Normalize a tools field (comma-separated string or list) into tool entries."""
    raw = value if isinstance(value, list) else str(value).split(",")
    return [entry.strip() for entry in raw if entry.strip()]


def _map_tools(entries: List[str], unmapped: List[str]) -> List[str]:
    """Translate Claude Code tool entries; entries without an equivalent go to `unmapped`."""
    mapped: List[str] = []
    for entry in entries:
        # `Agent(worker)` or `Bash(git *)` name the tool before the parenthesis
        base = entry.split("(", 1)[0].strip()
        targets = TOOL_MAP.get(base)
        if targets is None:
            if entry not in unmapped:
                unmapped.append(entry)
            continue
        mapped.extend(t for t in targets if t not in mapped)
    return mapped


def map_model(value: str) -> Optional[str]:
    """Map a Claude Code model alias or ID to an Antigravity tier (inherit, flash or pro)."""
    lowered = value.strip().lower()
    if lowered == "inherit":
        return "inherit"
    if "haiku" in lowered:
        return "flash"
    if any(family in lowered for family in ("sonnet", "opus", "fable")):
        return "pro"
    return None


def agent_subfolders(source_file: Path, agents_dir: Path) -> List[str]:
    """Subfolders between agents_dir and the file (agents/review/security.md -> ['review'])."""
    try:
        return list(source_file.relative_to(agents_dir).parent.parts)
    except ValueError:
        return []


def convert_agent_text(
    content: str,
    source: str,
    dest_agents_dir: Path,
    claimed: Dict[str, str],
    warnings: List[str],
    plugin_name: Optional[str] = None,
    subfolders: Optional[List[str]] = None,
    overwrite: bool = False,
) -> Optional[Path]:
    """Convert one Claude Code agent file into an Antigravity subagent file.

    With plugin_name, the agent follows plugin rules: it loads even without frontmatter, and
    its subfolders join its name (agents/review/security.md -> review-security; a frontmatter
    `name` replaces only the file name). Without it, the file follows project rules: the name
    comes only from frontmatter, and a file without `name` or `description` is skipped, as
    Claude Code skips it. Returns the written file, or None when the agent was skipped.
    """
    meta, body = parse_agent_frontmatter(content)
    if meta is None:
        meta = {}

    description = meta.get("description") if isinstance(meta.get("description"), str) else ""
    if plugin_name is not None:
        declared = meta.get("name") if isinstance(meta.get("name"), str) else ""
        raw_name = "-".join([*(subfolders or []), declared or Path(source).stem])
        description = description or f"Agent from {plugin_name} plugin"
    else:
        raw_name = meta.get("name") if isinstance(meta.get("name"), str) else ""
        if not raw_name:
            warnings.append(f"Agent file '{source}' has no 'name' (Claude Code treats it as documentation); skipped.")
            return None
        if not description:
            warnings.append(f"Agent '{raw_name}' ({source}) has no 'description' (required by both tools); skipped.")
            return None

    name = claim_skill_name(sanitize_skill_name(raw_name), source, claimed, warnings=warnings, kind="Agent")
    label = f"Agent '{name}'"

    lines = ["---", f"name: {name}", f'description: "{escape_yaml_string(description)}"']

    unmapped: List[str] = []
    allowed = _map_tools(_tool_entries(meta["tools"]), unmapped) if "tools" in meta else None
    denied = _map_tools(_tool_entries(meta["disallowedTools"]), unmapped) if "disallowedTools" in meta else []
    if denied:
        base = allowed if allowed is not None else ANTIGRAVITY_TOOLS
        allowed = [t for t in base if t not in denied]
        if "tools" not in meta:
            warnings.append(
                f"{label}: 'disallowedTools' has no Antigravity equivalent; it became an allowlist of the "
                "documented tools, so MCP and browser tools are no longer available to this agent."
            )
    if unmapped:
        warnings.append(f"{label}: tools without an Antigravity equivalent were removed: {', '.join(unmapped)}.")
    if allowed is not None:
        if allowed:
            lines.append("tools:")
            lines.extend(f"  - {tool}" for tool in allowed)
        else:
            warnings.append(
                f"{label}: no listed tool has an Antigravity equivalent, so 'tools' was left out; "
                "review the agent's tool access in Antigravity."
            )

    if isinstance(meta.get("model"), str) and meta["model"].strip():
        tier = map_model(meta["model"])
        if tier:
            lines.append(f"model: {tier}")
        else:
            warnings.append(f"{label}: model '{meta['model']}' has no Antigravity tier; left out (inherits).")

    skills = meta.get("skills")
    if skills:
        lines.append("skills:")
        lines.extend(f"  - skills/{sanitize_skill_name(s)}" for s in _tool_entries(skills))

    dropped = [key for key in meta if key not in CONVERTED_FIELDS]
    if dropped:
        warnings.append(f"{label}: fields not supported by Antigravity were dropped: {', '.join(dropped)}.")

    lines.extend(["---", "", body, ""])

    dest_agents_dir.mkdir(parents=True, exist_ok=True)
    target = dest_agents_dir / f"{name}.md"
    if target.exists() and not overwrite:
        raise FileExistsError(f"Target agent file already exists: '{target}'. Pass overwrite=True to allow overwriting.")
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def convert_agents_directory(
    agents_dir: Path,
    dest_agents_dir: Path,
    claimed: Dict[str, str],
    warnings: List[str],
    plugin_name: Optional[str] = None,
    overwrite: bool = False,
    failures: Optional[List[Tuple[Path, Exception]]] = None,
) -> List[Path]:
    """Convert every agent `.md` under agents_dir (recursively) into dest_agents_dir."""
    converted: List[Path] = []
    for md_file in sorted(agents_dir.rglob("*.md")):
        if not md_file.is_file():
            continue
        try:
            result = convert_agent_file(
                md_file, dest_agents_dir, claimed, warnings, plugin_name=plugin_name,
                subfolders=agent_subfolders(md_file, agents_dir), overwrite=overwrite,
            )
            if result is not None:
                converted.append(result)
        except FileExistsError:
            continue
        except (ValueError, OSError) as e:
            if failures is None:
                raise
            failures.append((md_file, e))
    return converted


def convert_agent_file(
    source_file: Path,
    dest_agents_dir: Path,
    claimed: Dict[str, str],
    warnings: List[str],
    plugin_name: Optional[str] = None,
    subfolders: Optional[List[str]] = None,
    overwrite: bool = False,
) -> Optional[Path]:
    """Convert one agent file (see convert_agent_text)."""
    return convert_agent_text(
        # utf-8-sig also reads files saved with a BOM (Windows PowerShell 5.1)
        source_file.read_text(encoding="utf-8-sig"),
        str(source_file),
        dest_agents_dir,
        claimed,
        warnings,
        plugin_name=plugin_name,
        subfolders=subfolders,
        overwrite=overwrite,
    )
