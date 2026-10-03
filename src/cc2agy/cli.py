"""Command-line interface for cc2agy."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.cc2agy import __version__
from src.cc2agy.converters.commands import convert_command_file, convert_commands_directory
from src.cc2agy.detector import detect_claude_project


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

    return parser


def handle_inspect(target: Path) -> int:
    info = detect_claude_project(target)
    print(info.summary())
    return 0 if info.is_claude_project else 1


def handle_convert(target: Path, dest: Path, overwrite: bool) -> int:
    info = detect_claude_project(target)
    if not info.is_claude_project and not (target.is_file() and target.suffix == ".md"):
        print(f"[!] No Claude Code resources found at: {target}", file=sys.stderr)
        return 1

    skills_dest = dest if dest.name == "skills" else dest / "skills"
    skills_dest.mkdir(parents=True, exist_ok=True)

    print(f"[*] Converting Claude Code resources from: {target}")
    print(f"[*] Destination: {dest}")

    converted_skills = 0
    if target.is_file() and target.suffix == ".md":
        try:
            res = convert_command_file(target, skills_dest, overwrite=overwrite)
            print(f"  [+] Skill generated: {res.parent.name} -> {res}")
            converted_skills += 1
        except FileExistsError as e:
            print(f"  [!] Skipped existing skill (use --overwrite to replace): {e}", file=sys.stderr)
    else:
        for c_dir in info.commands_dirs:
            results = convert_commands_directory(c_dir, skills_dest, overwrite=overwrite)
            for res in results:
                print(f"  [+] Skill generated: {res.parent.name} -> {res}")
                converted_skills += 1

    print(f"\n[OK] Conversion completed: {converted_skills} skill(s) generated.")
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
        return handle_convert(parsed_args.target, parsed_args.dest, parsed_args.overwrite)

    return 0


if __name__ == "__main__":
    sys.exit(main())
