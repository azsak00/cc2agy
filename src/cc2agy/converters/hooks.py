"""Converter for Claude Code lifecycle hooks to canonical Antigravity hooks.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


EVENT_MAPPING = {
    "sessionstart": "PreInvocation",
    "preinvocation": "PreInvocation",
    "postinvocation": "PostInvocation",
    "stop": "Stop",
    "pretooluse": "PreToolUse",
    "posttooluse": "PostToolUse",
}

VALID_ANTIGRAVITY_EVENTS = {
    "PreInvocation",
    "PostInvocation",
    "Stop",
    "PreToolUse",
    "PostToolUse",
}


def sanitize_hook_command(command: str) -> str:
    """Sanitize ${CLAUDE_PLUGIN_ROOT} and similar Claude variables in hook command strings.

    In Antigravity, hooks execute with the working directory set to the folder
    containing hooks.json (the plugin root). Thus, ${CLAUDE_PLUGIN_ROOT}/ becomes ./.
    """
    if not command:
        return command

    # Replace ${CLAUDE_PLUGIN_ROOT}/ or $CLAUDE_PLUGIN_ROOT/ with ./
    cleaned = re.sub(r"\$\{?CLAUDE_PLUGIN_ROOT\}?/", "./", command)
    # Replace standalone ${CLAUDE_PLUGIN_ROOT} with .
    cleaned = re.sub(r"\$\{?CLAUDE_PLUGIN_ROOT\}?", ".", cleaned)
    return cleaned


def extract_flat_handlers(items: List[Any], warnings: List[str]) -> List[Dict[str, Any]]:
    """Extract flat handler objects from potentially nested Claude Code hooks lists."""
    handlers: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # Claude Code often nests handlers inside {"hooks": [...]}
        if "hooks" in item and isinstance(item["hooks"], list):
            for sub_item in item["hooks"]:
                if isinstance(sub_item, dict):
                    cmd = sub_item.get("command", "")
                    handler: Dict[str, Any] = {
                        "type": sub_item.get("type", "command"),
                        "command": sanitize_hook_command(str(cmd)),
                    }
                    if "timeout" in sub_item and isinstance(sub_item["timeout"], int):
                        handler["timeout"] = sub_item["timeout"]
                    handlers.append(handler)
        elif "command" in item:
            handler = {
                "type": item.get("type", "command"),
                "command": sanitize_hook_command(str(item["command"])),
            }
            if "timeout" in item and isinstance(item["timeout"], int):
                handler["timeout"] = item["timeout"]
            handlers.append(handler)
        else:
            warnings.append(f"Ignored unrecognized hook handler structure: {item}")
    return handlers


def extract_grouped_handlers(items: List[Any], warnings: List[str]) -> List[Dict[str, Any]]:
    """Extract grouped matcher handler objects for PreToolUse and PostToolUse."""
    groups: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        matcher = item.get("matcher", "*")
        sub_hooks = item.get("hooks", [])
        handlers: List[Dict[str, Any]] = []
        if isinstance(sub_hooks, list):
            for h in sub_hooks:
                if isinstance(h, dict) and "command" in h:
                    clean_h: Dict[str, Any] = {
                        "type": h.get("type", "command"),
                        "command": sanitize_hook_command(str(h["command"])),
                    }
                    if "timeout" in h and isinstance(h["timeout"], int):
                        clean_h["timeout"] = h["timeout"]
                    handlers.append(clean_h)
        elif "command" in item:
            handlers.append({
                "type": item.get("type", "command"),
                "command": sanitize_hook_command(str(item["command"])),
            })

        if handlers:
            groups.append({
                "matcher": matcher,
                "hooks": handlers,
            })
    return groups


def convert_hooks_data(
    raw_data: Dict[str, Any],
    plugin_name: str = "plugin",
) -> Tuple[Dict[str, Any], List[str]]:
    """Convert raw Claude Code hooks dictionary into Antigravity canonical hooks dictionary."""
    warnings: List[str] = []

    # If data has a top-level "hooks" wrapper: {"hooks": { ... }}
    hooks_dict = raw_data.get("hooks", raw_data)
    if not isinstance(hooks_dict, dict):
        warnings.append("Root hooks entry is not a dictionary.")
        hooks_dict = {}

    converted_events: Dict[str, Any] = {}

    for raw_event, event_content in hooks_dict.items():
        mapped_event = EVENT_MAPPING.get(raw_event.lower())
        if not mapped_event:
            warnings.append(f"Skipped unsupported hook event: '{raw_event}'.")
            continue

        if raw_event.lower() != mapped_event.lower():
            warnings.append(f"Mapped event '{raw_event}' -> '{mapped_event}'.")

        if not isinstance(event_content, list):
            warnings.append(f"Hook event '{raw_event}' does not contain a list of handlers.")
            continue

        if mapped_event in ("PreToolUse", "PostToolUse"):
            groups = extract_grouped_handlers(event_content, warnings)
            if groups:
                converted_events[mapped_event] = groups
        else:
            handlers = extract_flat_handlers(event_content, warnings)
            if handlers:
                converted_events[mapped_event] = handlers

    hook_id = f"{plugin_name}-hooks"
    final_hooks_config = {
        hook_id: converted_events
    }
    return final_hooks_config, warnings


def convert_hooks_file(
    source_path: Path,
    dest_dir: Path,
    plugin_name: str = "plugin",
    overwrite: bool = False,
) -> Tuple[Path, List[str]]:
    """Read source hooks.json, convert to Antigravity format, and write to dest_dir/hooks.json."""
    source_path = source_path.resolve()
    dest_dir = dest_dir.resolve()
    dest_file = dest_dir / "hooks.json"

    if dest_file.exists() and not overwrite:
        raise FileExistsError(f"Destination hooks file already exists: {dest_file}")

    try:
        with open(source_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as e:
        raise ValueError(f"Failed to read/parse hooks JSON from {source_path}: {e}")

    converted_config, warnings = convert_hooks_data(raw_data, plugin_name=plugin_name)

    dest_dir.mkdir(parents=True, exist_ok=True)
    with open(dest_file, "w", encoding="utf-8") as f:
        json.dump(converted_config, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return dest_file, warnings
