"""Command-line interface for cc2agy."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cc2agy import __version__
from cc2agy.converters.commands import convert_command_file, convert_commands_directory
from cc2agy.converters.mcp import convert_mcp_file
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
        default=Path("./output"),
        help="Destination directory for converted Antigravity assets (default: ./output)."
    )
    convert_parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Allow overwriting existing files in destination."
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

    return parser


def handle_inspect(target: Path) -> int:
    info = detect_claude_project(target)
    print(info.summary())
    return 0 if info.is_claude_project else 1


def handle_convert(
    target: Path,
    dest: Path,
    overwrite: bool,
    skills_only: bool = False,
    rules_only: bool = False,
    mcp_only: bool = False
) -> int:
    info = detect_claude_project(target)
    if not info.is_claude_project:
        print(f"[!] No Claude Code resources found at: {target}", file=sys.stderr)
        return 1

    # If any specific filter flag is set, only convert requested types. Otherwise convert all.
    any_filter = skills_only or rules_only or mcp_only
    do_skills = skills_only if any_filter else True
    do_rules = rules_only if any_filter else True
    do_mcp = mcp_only if any_filter else True

    dest.mkdir(parents=True, exist_ok=True)
    print(f"[*] Converting Claude Code resources from: {target}")
    print(f"[*] Destination: {dest}")

    converted_skills = 0
    converted_rules = 0
    converted_mcp = 0

    # 1. Handle single-file target
    if target.is_file():
        # Rules file
        if info.rules_file:
            if do_rules:
                try:
                    res, warnings = convert_rules_file(info.rules_file, dest, overwrite=overwrite)
                    print(f"  [+] Rules generated: {res.name} -> {res}")
                    for w in warnings:
                        print(f"      [!] Warning: {w}")
                    converted_rules += 1
                except FileExistsError as e:
                    print(f"  [!] Skipped existing rules file (use --overwrite to replace): {e}", file=sys.stderr)
        # MCP file
        elif info.mcp_file:
            if do_mcp:
                try:
                    res, warnings = convert_mcp_file(info.mcp_file, dest, overwrite=overwrite)
                    print(f"  [+] MCP config generated: {res.name} -> {res}")
                    for w in warnings:
                        print(f"      [!] Warning: {w}")
                    converted_mcp += 1
                except FileExistsError as e:
                    print(f"  [!] Skipped existing MCP file (use --overwrite to replace): {e}", file=sys.stderr)
        # Command file
        elif info.command_files:
            if do_skills:
                skills_dest = dest if dest.name == "skills" else dest / "skills"
                skills_dest.mkdir(parents=True, exist_ok=True)
                try:
                    res = convert_command_file(info.command_files[0], skills_dest, overwrite=overwrite)
                    print(f"  [+] Skill generated: {res.parent.name} -> {res}")
                    converted_skills += 1
                except FileExistsError as e:
                    print(f"  [!] Skipped existing skill (use --overwrite to replace): {e}", file=sys.stderr)
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

    # 2. Handle directory target
    else:
        # Convert Commands to Skills
        if do_skills and info.has_commands:
            skills_dest = dest if dest.name == "skills" else dest / "skills"
            skills_dest.mkdir(parents=True, exist_ok=True)
            for c_dir in info.commands_dirs:
                results = convert_commands_directory(c_dir, skills_dest, overwrite=overwrite)
                for res in results:
                    print(f"  [+] Skill generated: {res.parent.name} -> {res}")
                    converted_skills += 1

        # Migrate Existing Modular Skills
        if do_skills and info.has_skills and info.skills_dir:
            skills_dest = dest if dest.name == "skills" else dest / "skills"
            skills_dest.mkdir(parents=True, exist_ok=True)
            results = migrate_skills_directory(info.skills_dir, skills_dest, overwrite=overwrite)
            for res in results:
                print(f"  [+] Skill migrated: {res.parent.name} -> {res}")
                converted_skills += 1

        # Convert Rules to AGENTS.md
        if do_rules and info.has_rules and info.rules_file:
            try:
                res, warnings = convert_rules_file(info.rules_file, dest, overwrite=overwrite)
                print(f"  [+] Rules generated: {res.name} -> {res}")
                for w in warnings:
                    print(f"      [!] Warning: {w}")
                converted_rules += 1
            except FileExistsError as e:
                print(f"  [!] Skipped existing rules file (use --overwrite to replace): {e}", file=sys.stderr)

        # Convert MCP to mcp_config.json
        if do_mcp and info.has_mcp and info.mcp_file:
            try:
                res, warnings = convert_mcp_file(info.mcp_file, dest, overwrite=overwrite)
                print(f"  [+] MCP config generated: {res.name} -> {res}")
                for w in warnings:
                    print(f"      [!] Warning: {w}")
                converted_mcp += 1
            except FileExistsError as e:
                print(f"  [!] Skipped existing MCP file (use --overwrite to replace): {e}", file=sys.stderr)

    print(
        f"\n[OK] Conversion completed: {converted_skills} skill(s), "
        f"{converted_rules} rule(s), {converted_mcp} MCP config(s) generated."
    )
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
        return handle_convert(
            target=parsed_args.target,
            dest=parsed_args.dest,
            overwrite=parsed_args.overwrite,
            skills_only=parsed_args.skills_only,
            rules_only=parsed_args.rules_only,
            mcp_only=parsed_args.mcp_only,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
