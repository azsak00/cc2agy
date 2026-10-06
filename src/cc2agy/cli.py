"""Command-line interface for cc2agy."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cc2agy import __version__
from cc2agy.converters.agents import convert_agents_directory
from cc2agy.converters.commands import (
    command_skill_name,
    convert_command_file,
    convert_commands_directory,
    sanitize_skill_name,
)
from cc2agy.converters.hooks import convert_hooks_files
from cc2agy.converters.mcp import convert_mcp_file
from cc2agy.converters.plugin import convert_plugin
from cc2agy.converters.rules import convert_rules_file
from cc2agy.converters.skills import migrate_skill_folder, migrate_skills_directory
from cc2agy.detector import detect_claude_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cc2agy",
        description="cc2agy: Bridge and migration tool from Claude Code to Google Antigravity.",
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"cc2agy {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Subcommand: inspect
    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a target directory or file and list discovered Claude Code assets."
    )
    inspect_parser.add_argument(
        "target",
        type=Path,
        help="Path to Claude Code project, plugin, or file."
    )

    # Subcommand: convert
    convert_parser = subparsers.add_parser(
        "convert",
        help="Convert Claude Code assets into canonical Antigravity resources."
    )
    convert_parser.add_argument(
        "target",
        type=Path,
        help="Source directory or file to convert."
    )
    convert_parser.add_argument(
        "--dest", "-d",
        type=Path,
        default=None,
        help="Destination directory for converted Antigravity assets (default: ./output)."
    )
    convert_parser.add_argument(
        "--install",
        choices=["project", "user"],
        default=None,
        help="Convert straight into the folders Antigravity reads: 'project' uses .agents/ in the "
             "current folder, 'user' uses ~/.gemini/config/. Existing mcp_config.json and hooks.json "
             "are merged, not replaced (a copy is kept as <file>.cc2agy.bak). Cannot be used with --dest."
    )
    convert_parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Allow overwriting existing files in destination."
    )
    convert_parser.add_argument(
        "--plugin",
        action="store_true",
        default=False,
        help="Package target into a full Antigravity plugin (plugins/<name>/)."
    )
    convert_parser.add_argument(
        "--skills-only",
        action="store_true",
        default=False,
        help="Convert only commands into Skills."
    )
    convert_parser.add_argument(
        "--rules-only",
        action="store_true",
        default=False,
        help="Convert only CLAUDE.md into AGENTS.md rules."
    )
    convert_parser.add_argument(
        "--mcp-only",
        action="store_true",
        default=False,
        help="Convert only MCP server configurations."
    )
    convert_parser.add_argument(
        "--hooks-only",
        action="store_true",
        default=False,
        help="Convert only lifecycle hooks configurations."
    )
    convert_parser.add_argument(
        "--user-config",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Value for a plugin.json userConfig key (repeatable). Antigravity cannot prompt for "
             "these values, so they are written into the converted plugin."
    )

    return parser


def _error_message(exc: Exception) -> str:
    """Turn a conversion error into a short, user-facing message."""
    if isinstance(exc, UnicodeDecodeError):
        return "file is not valid UTF-8 text (re-save it with UTF-8 encoding)"
    return str(exc)


def _parse_user_config(entries: list[str]) -> dict[str, str]:
    """Parse repeated KEY=VALUE options; raise ValueError on an entry without '='."""
    values: dict[str, str] = {}
    for entry in entries:
        key, sep, value = entry.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"--user-config expects KEY=VALUE, got '{entry}'")
        values[key.strip()] = value
    return values


def install_base(install: str) -> Path:
    """Folder Antigravity reads converted assets from: <cwd>/.agents or ~/.gemini/config."""
    if install == "project":
        return Path.cwd() / ".agents"
    return Path.home() / ".gemini" / "config"


def _source_name(target: Path) -> str:
    """Name the converted source (its folder, skipping .claude/ and hooks/) for its hook group."""
    folder = target.resolve()
    if folder.is_file():
        folder = folder.parent
    while folder.name.lower() in (".claude", "hooks") and folder.parent != folder:
        folder = folder.parent
    return sanitize_skill_name(folder.name) or "project"


def handle_inspect(target: Path) -> int:
    info = detect_claude_project(target)
    print(info.summary())
    return 0 if info.is_claude_project else 1


def handle_convert(
    target: Path,
    dest: Path,
    overwrite: bool,
    plugin: bool = False,
    skills_only: bool = False,
    rules_only: bool = False,
    mcp_only: bool = False,
    hooks_only: bool = False,
    user_config: list[str] | None = None,
    install: str | None = None,
) -> int:
    """Convert target into dest. With install ('project' or 'user'), dest is the Antigravity
    folder from install_base: plugins go to plugins/<name>/, rules to rules/AGENTS.md, and
    mcp_config.json and hooks.json are merged into existing files instead of replaced."""
    try:
        user_values = _parse_user_config(user_config or [])
    except ValueError as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1

    info = detect_claude_project(target)
    if not info.is_claude_project:
        print(f"[!] No Claude Code resources found at: {target}", file=sys.stderr)
        return 1

    # Check if target should be packaged as a full plugin
    any_filter = skills_only or rules_only or mcp_only or hooks_only
    is_plugin_conversion = plugin or (info.is_plugin and not any_filter)

    dest.mkdir(parents=True, exist_ok=True)
    print(f"[*] Converting Claude Code resources from: {target}")
    print(f"[*] Destination: {dest}")

    if is_plugin_conversion and target.is_dir():
        try:
            plugin_path, p_summary = convert_plugin(
                target, dest / "plugins" if install else dest, overwrite=overwrite, user_config=user_values
            )
            print(f"  [+] Full Plugin packaged: {p_summary['plugin_name']} -> {plugin_path}")
            print(f"      - Manifest: plugin.json")
            print(f"      - Skills/Commands: {p_summary['skills_migrated']}")
            print(f"      - Rules: {p_summary['rules_migrated']}")
            print(f"      - MCP configs: {p_summary['mcp_migrated']}")
            print(f"      - Lifecycle Hooks: {p_summary['hooks_migrated']}")
            print(f"      - Subagents: {p_summary['agents_migrated']}")
            if p_summary["auxiliary_dirs_copied"]:
                print(f"      - Auxiliary dirs: {', '.join(p_summary['auxiliary_dirs_copied'])}")
            for w in p_summary["warnings"]:
                print(f"      [!] Warning: {w}")
            print(f"\n[OK] Plugin package complete: {p_summary['plugin_name']}")
            return 0
        except FileExistsError as e:
            print(f"  [!] Skipped existing plugin (use --overwrite to replace): {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"  [-] Plugin conversion failed: {e}", file=sys.stderr)
            return 1

    if user_values:
        print("      [!] Warning: --user-config only applies to plugin conversion; ignored.")

    # Antigravity reads rules from rules/*.md in its folders, not from a loose AGENTS.md there
    rules_dest = dest / "rules" if install else dest
    merge = install is not None
    hooks_group = _source_name(target) if install else "plugin"

    do_skills = skills_only if any_filter else True
    do_rules = rules_only if any_filter else True
    do_mcp = mcp_only if any_filter else True
    do_hooks = hooks_only if any_filter else True

    converted_skills = 0
    converted_rules = 0
    converted_mcp = 0
    converted_hooks = 0
    converted_agents = 0
    failures = 0

    def report_failure(what: str, source: Path, exc: Exception) -> None:
        nonlocal failures
        failures += 1
        print(f"  [-] Failed to convert {what} '{source}': {_error_message(exc)}", file=sys.stderr)

    def convert_hooks() -> None:
        nonlocal converted_hooks
        sources = info.hook_sources
        try:
            res, warnings = convert_hooks_files(
                sources, dest, plugin_name=hooks_group, overwrite=overwrite, merge=merge
            )
            if res is not None:
                print(f"  [+] Hooks generated: {res.name} -> {res}")
                converted_hooks += 1
            for w in warnings:
                print(f"      [!] Warning: {w}")
        except FileExistsError as e:
            print(f"  [!] Skipped existing hooks file (use --overwrite to replace): {e}", file=sys.stderr)
        except (ValueError, OSError) as e:
            report_failure("hooks from", ", ".join(str(s) for s in sources), e)

    # 1. Handle single-file target
    if target.is_file():
        # Rules file
        if info.rules_file:
            if do_rules:
                try:
                    res, warnings = convert_rules_file(info.rules_file, rules_dest, overwrite=overwrite)
                    print(f"  [+] Rules generated: {res.name} -> {res}")
                    for w in warnings:
                        print(f"      [!] Warning: {w}")
                    converted_rules += 1
                except FileExistsError as e:
                    print(f"  [!] Skipped existing rules file (use --overwrite to replace): {e}", file=sys.stderr)
                except (ValueError, OSError) as e:
                    report_failure("rules file", info.rules_file, e)
        # MCP file
        elif info.mcp_file:
            if do_mcp:
                try:
                    res, warnings = convert_mcp_file(info.mcp_file, dest, overwrite=overwrite, merge=merge)
                    print(f"  [+] MCP config generated: {res.name} -> {res}")
                    for w in warnings:
                        print(f"      [!] Warning: {w}")
                    converted_mcp += 1
                except FileExistsError as e:
                    print(f"  [!] Skipped existing MCP file (use --overwrite to replace): {e}", file=sys.stderr)
                except (ValueError, OSError) as e:
                    report_failure("MCP file", info.mcp_file, e)
        # Hooks file (hooks.json or a settings file)
        elif info.has_hooks:
            if do_hooks:
                convert_hooks()
        # Command file
        elif info.command_files:
            if do_skills:
                skills_dest = dest if dest.name == "skills" else dest / "skills"
                skills_dest.mkdir(parents=True, exist_ok=True)
                try:
                    name_warnings: list[str] = []
                    command_skill_name(info.command_files[0], warnings=name_warnings)
                    res = convert_command_file(
                        info.command_files[0], skills_dest, overwrite=overwrite, warnings=name_warnings
                    )
                    print(f"  [+] Skill generated: {res.parent.name} -> {res}")
                    for w in name_warnings:
                        print(f"      [!] Warning: {w}")
                    converted_skills += 1
                except FileExistsError as e:
                    print(f"  [!] Skipped existing skill (use --overwrite to replace): {e}", file=sys.stderr)
                except (ValueError, OSError) as e:
                    report_failure("command", info.command_files[0], e)
        # Direct SKILL.md file
        elif target.name.lower() == "skill.md":
            if do_skills:
                skills_dest = dest if dest.name == "skills" else dest / "skills"
                skills_dest.mkdir(parents=True, exist_ok=True)
                try:
                    res = migrate_skill_folder(target.parent, skills_dest, overwrite=overwrite)
                    print(f"  [+] Skill migrated: {res.parent.name} -> {res}")
                    converted_skills += 1
                except FileExistsError as e:
                    print(f"  [!] Skipped existing skill (use --overwrite to replace): {e}", file=sys.stderr)
                except (ValueError, OSError) as e:
                    report_failure("skill", target.parent, e)

    # 2. Handle directory target
    else:
        # Convert Commands to Skills
        if do_skills and info.has_commands:
            skills_dest = dest if dest.name == "skills" else dest / "skills"
            skills_dest.mkdir(parents=True, exist_ok=True)
            # Shared across command folders so commands/ and .claude/commands/ never collide
            claimed_names: dict[str, str] = {}
            for c_dir in info.commands_dirs:
                cmd_failures: list[tuple[Path, Exception]] = []
                cmd_warnings: list[str] = []
                results = convert_commands_directory(
                    c_dir, skills_dest, overwrite=overwrite, failures=cmd_failures,
                    claimed=claimed_names, warnings=cmd_warnings,
                )
                for res in results:
                    print(f"  [+] Skill generated: {res.parent.name} -> {res}")
                    converted_skills += 1
                for w in cmd_warnings:
                    print(f"      [!] Warning: {w}")
                for src, exc in cmd_failures:
                    report_failure("command", src, exc)

        # Migrate Existing Modular Skills
        if do_skills and info.has_skills and info.skills_dir:
            skills_dest = dest if dest.name == "skills" else dest / "skills"
            skills_dest.mkdir(parents=True, exist_ok=True)
            skill_failures: list[tuple[Path, Exception]] = []
            results = migrate_skills_directory(
                info.skills_dir, skills_dest, overwrite=overwrite, failures=skill_failures
            )
            for res in results:
                print(f"  [+] Skill migrated: {res.parent.name} -> {res}")
                converted_skills += 1
            for src, exc in skill_failures:
                report_failure("skill", src, exc)

        # Convert Rules to AGENTS.md
        if do_rules and info.has_rules and info.rules_file:
            try:
                res, warnings = convert_rules_file(info.rules_file, rules_dest, overwrite=overwrite)
                print(f"  [+] Rules generated: {res.name} -> {res}")
                for w in warnings:
                    print(f"      [!] Warning: {w}")
                converted_rules += 1
            except FileExistsError as e:
                print(f"  [!] Skipped existing rules file (use --overwrite to replace): {e}", file=sys.stderr)
            except (ValueError, OSError) as e:
                report_failure("rules file", info.rules_file, e)

        # Convert MCP to mcp_config.json
        if do_mcp and info.has_mcp and info.mcp_file:
            try:
                res, warnings = convert_mcp_file(info.mcp_file, dest, overwrite=overwrite, merge=merge)
                print(f"  [+] MCP config generated: {res.name} -> {res}")
                for w in warnings:
                    print(f"      [!] Warning: {w}")
                converted_mcp += 1
            except FileExistsError as e:
                print(f"  [!] Skipped existing MCP file (use --overwrite to replace): {e}", file=sys.stderr)
            except (ValueError, OSError) as e:
                report_failure("MCP file", info.mcp_file, e)

        # Convert Hooks (hooks.json, .claude/settings.json, .claude/settings.local.json) to hooks.json
        if do_hooks and info.has_hooks:
            convert_hooks()

        # Convert subagents to agents/<name>.md (project rules: name comes from frontmatter only)
        if not any_filter and info.has_agents:
            agents_dest = dest if dest.name == "agents" else dest / "agents"
            agent_claimed: dict[str, str] = {}
            for a_dir in info.agents_dirs:
                agent_failures: list[tuple[Path, Exception]] = []
                agent_warnings: list[str] = []
                results = convert_agents_directory(
                    a_dir, agents_dest, agent_claimed, agent_warnings, overwrite=overwrite, failures=agent_failures
                )
                for res in results:
                    print(f"  [+] Subagent generated: {res.stem} -> {res}")
                    converted_agents += 1
                for w in agent_warnings:
                    print(f"      [!] Warning: {w}")
                for src, exc in agent_failures:
                    report_failure("subagent", src, exc)

    counts = (
        f"{converted_skills} skill(s), {converted_rules} rule(s), "
        f"{converted_mcp} MCP config(s), {converted_hooks} hooks config(s), "
        f"{converted_agents} subagent(s) generated"
    )
    if failures:
        print(f"\n[!] Conversion finished with {failures} error(s): {counts}.", file=sys.stderr)
        return 1
    print(f"\n[OK] Conversion completed: {counts}.")
    return 0


def main(args: list[str] | None = None) -> int:
    parser = build_parser()
    parsed_args = parser.parse_args(args)

    if not parsed_args.command:
        parser.print_help()
        return 0

    if parsed_args.command == "inspect":
        return handle_inspect(parsed_args.target)
    elif parsed_args.command == "convert":
        if parsed_args.install and parsed_args.dest is not None:
            parser.error("--install chooses the destination itself; it cannot be used with --dest")
        if parsed_args.install:
            dest = install_base(parsed_args.install)
        else:
            dest = parsed_args.dest or Path("./output")
        return handle_convert(
            target=parsed_args.target,
            dest=dest,
            overwrite=parsed_args.overwrite,
            plugin=parsed_args.plugin,
            skills_only=parsed_args.skills_only,
            rules_only=parsed_args.rules_only,
            mcp_only=parsed_args.mcp_only,
            hooks_only=parsed_args.hooks_only,
            user_config=parsed_args.user_config,
            install=parsed_args.install,
        )

    return 0



if __name__ == "__main__":
    sys.exit(main())
