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
from pathlib import Path
from typing import Any, Dict, List, Tuple

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


def normalize_server_entry(server_id: str, raw_config: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Normalize a single server definition to Antigravity canonical schema.

    Returns:
        Tuple of (normalized_config_dict, warnings_list).
    """
    warnings: List[str] = []
    normalized: Dict[str, Any] = {}

    if not isinstance(raw_config, dict):
        warnings.append(f"Server '{server_id}' configuration is not an object. Skipped.")
        return {}, warnings

    # 1. Detect SSE transport
    server_url = raw_config.get("serverUrl") or raw_config.get("url") or raw_config.get("endpoint")
    if server_url and isinstance(server_url, str):
        if not (server_url.startswith("http://") or server_url.startswith("https://")):
            warnings.append(f"Server '{server_id}' SSE url '{server_url}' does not start with http:// or https://.")
        normalized["serverUrl"] = server_url

        # Authentication headers (Antigravity documents 'headers' for remote servers)
        headers = raw_config.get("headers")
        if headers is not None:
            if isinstance(headers, dict):
                normalized["headers"] = {str(k): str(v) for k, v in headers.items()}
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
        normalized["command"] = str(command).strip()

        args = raw_config.get("args")
        if args is not None:
            if isinstance(args, list):
                normalized["args"] = [str(arg) for arg in args]
            else:
                warnings.append(f"Server '{server_id}' 'args' must be a list of strings.")

        env = raw_config.get("env")
        if env is not None:
            if isinstance(env, dict):
                normalized["env"] = {str(k): str(v) for k, v in env.items()}
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

    # Validation: must have either command or serverUrl
    if "command" not in normalized and "serverUrl" not in normalized:
        warnings.append(f"Server '{server_id}' specifies neither 'command' (stdio) nor 'serverUrl' (sse).")
        return {}, warnings

    return normalized, warnings


def convert_mcp_config(raw_data: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Convert raw Claude Code MCP data into canonical Antigravity mcp_config structure."""
    servers_dict = extract_servers_dict(raw_data)
    if not servers_dict:
        return {"mcpServers": {}}, ["No valid MCP servers found in source configuration."]

    normalized_servers: Dict[str, Any] = {}
    all_warnings: List[str] = []

    for server_id, server_cfg in servers_dict.items():
        clean_cfg, warnings = normalize_server_entry(server_id, server_cfg)
        all_warnings.extend(warnings)
        if clean_cfg:
            normalized_servers[server_id] = clean_cfg

    return {"mcpServers": normalized_servers}, all_warnings


def convert_mcp_file(
    source_file: Path,
    dest_dir: Path,
    custom_filename: str = "mcp_config.json",
    overwrite: bool = False
) -> Tuple[Path, List[str]]:
    """Convert a Claude Code MCP JSON file into an Antigravity mcp_config.json file.

    Args:
        source_file: Path to source .mcp.json or .claude.json file.
        dest_dir: Target directory where mcp_config.json will be saved.
        custom_filename: Target filename (default: "mcp_config.json").
        overwrite: Whether to overwrite existing destination file.

    Returns:
        Tuple of (target_file_path, warnings_list).

    Raises:
        FileNotFoundError: If source_file does not exist.
        ValueError: If source_file does not contain valid JSON.
        FileExistsError: If target file exists and overwrite is False.
    """
    if not source_file.exists() or not source_file.is_file():
        raise FileNotFoundError(f"Source MCP file not found: {source_file}")

    content = source_file.read_text(encoding="utf-8")
    try:
        raw_data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse source MCP file as JSON: {e}") from e

    return write_mcp_data(raw_data, dest_dir, custom_filename=custom_filename, overwrite=overwrite)


def write_mcp_data(
    raw_data: Any,
    dest_dir: Path,
    custom_filename: str = "mcp_config.json",
    overwrite: bool = False
) -> Tuple[Path, List[str]]:
    """Convert already-loaded Claude Code MCP data and write it as an Antigravity mcp_config.json."""
    config, warnings = convert_mcp_config(raw_data)

    dest_dir.mkdir(parents=True, exist_ok=True)
    target_file = dest_dir / custom_filename

    if target_file.exists() and not overwrite:
        raise FileExistsError(
            f"Target MCP config file already exists: '{target_file}'. Pass overwrite=True to allow replacement."
        )

    formatted_json = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    target_file.write_text(formatted_json, encoding="utf-8")

    return target_file, warnings
