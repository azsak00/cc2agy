"""Converter for Claude Code MCP server configurations to Google Antigravity mcp_config.json.

Claude Code defines MCP configurations in:
- `.mcp.json` or `mcp.json`
- `.claude.json` (inside the "mcpServers" key)

Google Antigravity defines MCP configurations in `mcp_config.json`:
- Global: `~/.gemini/config/mcp_config.json`
- Plugin: `plugins/<plugin_name>/mcp_config.json`
- Schema requires a root "mcpServers" object mapping server IDs to configs.
- Stdio transport: requires "command" (string), optional "args" (list[str]), optional "env" (dict).
- SSE transport: requires "serverUrl" (string starting with http:// or https://),
  optional "headers" (dict) for authentication.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cc2agy.converters.variables import PluginVariables, standalone_variables, substitute

# Header names that usually carry credentials
SECRET_HEADER_HINTS = ("authorization", "key", "token", "secret", "password")


def extract_servers_dict(raw_data: Any) -> Dict[str, Any]:
    """Extract server dictionary from various Claude Code JSON structures.

    Handles:
    - {"mcpServers": {"server-id": {...}}}
    - {"server-id": {"command": ...}}
    - Complex configurations where mcpServers is a sub-object
    """
    if not isinstance(raw_data, dict):
        raise ValueError("Invalid MCP configuration: root must be a JSON object.")

    if "mcpServers" in raw_data and isinstance(raw_data["mcpServers"], dict):
        return raw_data["mcpServers"]

    # Check if the dictionary itself is a map of servers (e.g., {"fetch": {"command": "..."}})
    is_server_map = any(
        isinstance(v, dict) and ("command" in v or "args" in v or "url" in v or "serverUrl" in v)
        for v in raw_data.values()
    )
    if is_server_map:
        return raw_data

    return {}


def normalize_server_entry(
    server_id: str, raw_config: Dict[str, Any], variables: Optional[PluginVariables] = None
) -> Tuple[Dict[str, Any], List[str]]:
    """Normalize a single server definition to Antigravity canonical schema.

    With variables, Claude Code plugin variables and ${user_config.KEY} are resolved in
    command, args, env, url and headers, and a plugin's stdio servers receive
    CLAUDE_PLUGIN_ROOT and CLAUDE_PLUGIN_DATA in env, as Claude Code exports them.

    Returns:
        Tuple of (normalized_config_dict, warnings_list).
    """
    warnings: List[str] = []
    normalized: Dict[str, Any] = {}

    if not isinstance(raw_config, dict):
        warnings.append(f"Server '{server_id}' configuration is not an object. Skipped.")
        return {}, warnings

    def resolve(value: Any) -> str:
        text = str(value)
        return substitute(text, variables, "mcp", warnings) if variables is not None else text

    # 1. Detect SSE transport
    server_url = raw_config.get("serverUrl") or raw_config.get("url") or raw_config.get("endpoint")
    if server_url and isinstance(server_url, str):
        if not (server_url.startswith("http://") or server_url.startswith("https://")):
            warnings.append(f"Server '{server_id}' SSE url '{server_url}' does not start with http:// or https://.")
        normalized["serverUrl"] = resolve(server_url)

        # Authentication headers (Antigravity documents 'headers' for remote servers)
        headers = raw_config.get("headers")
        if headers is not None:
            if isinstance(headers, dict):
                normalized["headers"] = {str(k): resolve(v) for k, v in headers.items()}
                for k, v in normalized["headers"].items():
                    if "${" in v:
                        warnings.append(
                            f"Server '{server_id}' header '{k}' uses ${{...}} variable expansion. "
                            "The Antigravity documentation does not state that variables are expanded, "
                            "so the literal text may be sent; replace it with the real value if authentication fails."
                        )
                    elif any(sec in k.lower() for sec in SECRET_HEADER_HINTS):
                        warnings.append(
                            f"Server '{server_id}' header '{k}' appears to contain a plaintext secret. "
                            "Keep this mcp_config.json out of version control."
                        )
            else:
                warnings.append(f"Server '{server_id}' 'headers' must be a dictionary.")

        if "headersHelper" in raw_config:
            warnings.append(
                f"Server '{server_id}' 'headersHelper' has no Antigravity equivalent and was not converted; "
                "set the resulting headers manually in 'headers'."
            )
        if "oauth" in raw_config:
            warnings.append(
                f"Server '{server_id}' Claude Code 'oauth' settings were not converted; "
                "Antigravity expects 'oauth' with 'clientId' and 'clientSecret', configure it manually."
            )

    # 2. Detect Stdio transport
    command = raw_config.get("command")
    if command:
        normalized["command"] = resolve(command).strip()

        args = raw_config.get("args")
        if args is not None:
            if isinstance(args, list):
                normalized["args"] = [resolve(arg) for arg in args]
            else:
                warnings.append(f"Server '{server_id}' 'args' must be a list of strings.")

        env = raw_config.get("env")
        if env is not None:
            if isinstance(env, dict):
                normalized["env"] = {str(k): resolve(v) for k, v in env.items()}
                # Check for plaintext credentials
                for k, v in env.items():
                    val = str(v)
                    if any(sec in k.lower() for sec in ("key", "token", "secret", "password")):
                        if not (val.startswith("$") or val.startswith("%")):
                            warnings.append(
                                f"Server '{server_id}' environment variable '{k}' appears to contain a "
                                f"plaintext secret. Consider using environment variable expansion."
                            )
            else:
                warnings.append(f"Server '{server_id}' 'env' must be a dictionary.")

        if variables is not None and variables.plugin:
            plugin_env = normalized.setdefault("env", {})
            plugin_env.setdefault("CLAUDE_PLUGIN_ROOT", variables.root.as_posix())
            data = variables.data_path()
            if data is not None:
                plugin_env.setdefault("CLAUDE_PLUGIN_DATA", data)

    # Validation: must have either command or serverUrl
    if "command" not in normalized and "serverUrl" not in normalized:
        warnings.append(f"Server '{server_id}' specifies neither 'command' (stdio) nor 'serverUrl' (sse).")
        return {}, warnings

    return normalized, warnings


def convert_mcp_config(
    raw_data: Any, variables: Optional[PluginVariables] = None
) -> Tuple[Dict[str, Any], List[str]]:
    """Convert raw Claude Code MCP data into canonical Antigravity mcp_config structure."""
    servers_dict = extract_servers_dict(raw_data)
    if not servers_dict:
        return {"mcpServers": {}}, ["No valid MCP servers found in source configuration."]

    normalized_servers: Dict[str, Any] = {}
    all_warnings: List[str] = []

    for server_id, server_cfg in servers_dict.items():
        clean_cfg, warnings = normalize_server_entry(server_id, server_cfg, variables)
        all_warnings.extend(warnings)
        if clean_cfg:
            normalized_servers[server_id] = clean_cfg

    return {"mcpServers": normalized_servers}, all_warnings


def convert_mcp_file(
    source_file: Path,
    dest_dir: Path,
    custom_filename: str = "mcp_config.json",
    overwrite: bool = False,
    merge: bool = False,
) -> Tuple[Path, List[str]]:
    """Convert a Claude Code MCP JSON file into an Antigravity mcp_config.json file.

    Args:
        source_file: Path to source .mcp.json or .claude.json file.
        dest_dir: Target directory where mcp_config.json will be saved.
        custom_filename: Target filename (default: "mcp_config.json").
        overwrite: Whether to overwrite existing destination file.
        merge: Add the converted servers to an existing destination file (see write_mcp_data).

    Returns:
        Tuple of (target_file_path, warnings_list).

    Raises:
        FileNotFoundError: If source_file does not exist.
        ValueError: If source_file does not contain valid JSON.
        FileExistsError: If target file exists and overwrite is False.
    """
    if not source_file.exists() or not source_file.is_file():
        raise FileNotFoundError(f"Source MCP file not found: {source_file}")

    # utf-8-sig also reads files saved with a BOM (Windows PowerShell 5.1)
    content = source_file.read_text(encoding="utf-8-sig")
    try:
        raw_data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse source MCP file as JSON: {e}") from e

    return write_mcp_data(
        raw_data, dest_dir, custom_filename=custom_filename, overwrite=overwrite,
        variables=standalone_variables(source_file, dest_dir), merge=merge,
    )


def read_json_for_merge(target_file: Path) -> Dict[str, Any]:
    """Load an existing JSON object that converted data will be merged into.

    Raises ValueError when the file is not a valid JSON object, so it is never replaced.
    """
    try:
        data = json.loads(target_file.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"Existing '{target_file}' is not valid JSON ({e}); left untouched.") from e
    if not isinstance(data, dict):
        raise ValueError(f"Existing '{target_file}' is not a JSON object; left untouched.")
    return data


def write_json_with_backup(target_file: Path, data: Dict[str, Any]) -> None:
    """Save the current target_file as <name>.cc2agy.bak, then write data over it."""
    shutil.copy2(target_file, target_file.with_name(target_file.name + ".cc2agy.bak"))
    target_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_mcp_data(
    raw_data: Any,
    dest_dir: Path,
    custom_filename: str = "mcp_config.json",
    overwrite: bool = False,
    variables: Optional[PluginVariables] = None,
    merge: bool = False,
) -> Tuple[Path, List[str]]:
    """Convert already-loaded Claude Code MCP data and write it as an Antigravity mcp_config.json.

    With merge, an existing file is kept: converted servers are added to it, servers already
    there are never touched, and a converted server with the same name as an existing one is
    skipped with a warning (replaced, alone, with overwrite). The previous file is saved as
    <name>.cc2agy.bak.
    """
    config, warnings = convert_mcp_config(raw_data, variables)

    dest_dir.mkdir(parents=True, exist_ok=True)
    target_file = dest_dir / custom_filename

    if merge and target_file.exists():
        existing = read_json_for_merge(target_file)
        servers = existing.get("mcpServers")
        if servers is None:
            servers = existing["mcpServers"] = {}
        elif not isinstance(servers, dict):
            raise ValueError(f"Existing '{target_file}' has an invalid 'mcpServers' value; left untouched.")
        changed = False
        for name, server in config["mcpServers"].items():
            if name in servers and not overwrite:
                warnings.append(
                    f"Server '{name}' already exists in '{target_file}'; kept as is (use --overwrite to replace it)."
                )
                continue
            servers[name] = server
            changed = True
        if changed:
            write_json_with_backup(target_file, existing)
        return target_file, warnings

    if target_file.exists() and not overwrite:
        raise FileExistsError(
            f"Target MCP config file already exists: '{target_file}'. Pass overwrite=True to allow replacement."
        )

    formatted_json = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    target_file.write_text(formatted_json, encoding="utf-8")

    return target_file, warnings
