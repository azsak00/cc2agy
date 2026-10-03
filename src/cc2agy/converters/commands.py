"""Converter for Claude Code commands to Google Antigravity Skills.

Claude Code defines custom commands in `commands/*.md` (or `.claude/commands/*.md`).
Antigravity uses native Skills in `skills/<name>/SKILL.md` with YAML frontmatter.
This module translates Claude Code commands directly into Antigravity Skills.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional, Tuple


def sanitize_skill_name(raw_name: str) -> str:
    """Normalize a command name into a valid Antigravity skill directory name (kebab-case)."""
    # Replace spaces and underscores with hyphens
    name = re.sub(r"[_\s]+", "-", raw_name.strip().lower())
    # Remove any character that isn't alphanumeric or hyphen
    name = re.sub(r"[^a-z0-9\-]", "", name)
    # Deduplicate consecutive hyphens
    name = re.sub(r"-+", "-", name)
    return name.strip("-") or "custom-command"


def parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    """Parse simple YAML frontmatter if present, returning (metadata_dict, body)."""
    frontmatter: Dict[str, str] = {}
    body = content

    pattern = r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$"
    match = re.search(pattern, content, re.DOTALL)
    if match:
        raw_meta, body = match.group(1), match.group(2)
        for line in raw_meta.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip().strip("\"'")
                frontmatter[key] = val

    return frontmatter, body.strip()


def extract_description(body: str, metadata: Dict[str, str], command_name: str) -> str:
    """Extract or synthesize an accurate 3rd-person description for the Skill frontmatter."""
    # 1. Prefer frontmatter description if present
    if "description" in metadata and metadata["description"]:
        desc = metadata["description"].strip()
        # Ensure it starts nicely or is concise
        return desc

    # 2. Look for the first Markdown heading
    heading_match = re.search(r"^#+\s+(.+)$", body, re.MULTILINE)
    if heading_match:
        heading_text = heading_match.group(1).strip()
        # If heading is not just the command name, use it
        if heading_text.lower() != command_name.lower():
            return f"Executes the /{command_name} routine: {heading_text}."

    # 3. Look for the first non-empty paragraph
    lines = [line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")]
    if lines:
        first_line = lines[0]
        # Clean markdown formatting like asterisks or backticks
        clean_line = re.sub(r"[\*`_]", "", first_line)
        if len(clean_line) > 120:
            clean_line = clean_line[:117] + "..."
        return clean_line

    # 4. Default fallback
    return f"Executes the /{command_name} command migrated from Claude Code."


def adapt_prompt_arguments(body: str) -> str:
    """Adapt Claude Code argument placeholders ($ARGUMENTS, $1, etc.) for Antigravity instructions."""
    # Claude commands often use $ARGUMENTS or $1..$9
    has_arguments = bool(re.search(r"\$(ARGUMENTS|[0-9])", body))
    if not has_arguments:
        return body

    adapted = body
    # Replace $ARGUMENTS with clear Antigravity prompt instructions
    adapted = re.sub(r"\$ARGUMENTS", "[User Arguments provided after the slash command]", adapted)
    # Replace $1, $2, etc.
    adapted = re.sub(r"\$([1-9])", r"[Argument \1 provided by user]", adapted)

    # Prepend a small clarification block if not already documented
    notice = (
        "> [!NOTE]\n"
        "> This skill was migrated from a Claude Code slash command. "
        "Any user parameters passed after the slash command should be applied to the placeholders below.\n\n"
    )
    return notice + adapted


def convert_command_file(
    source_file: Path,
    dest_skills_dir: Path,
    custom_name: Optional[str] = None
) -> Path:
    """Convert a single Claude Code command file into an Antigravity Skill folder."""
    raw_content = source_file.read_text(encoding="utf-8")
    meta, raw_body = parse_frontmatter(raw_content)

    # Determine canonical skill name
    cmd_name = custom_name or meta.get("name") or source_file.stem
    skill_name = sanitize_skill_name(cmd_name)

    # Generate description and adapt body
    description = extract_description(raw_body, meta, skill_name)
    body = adapt_prompt_arguments(raw_body)

    # Target folder and SKILL.md path
    skill_folder = dest_skills_dir / skill_name
    skill_folder.mkdir(parents=True, exist_ok=True)
    target_skill_file = skill_folder / "SKILL.md"

    # Assemble canonical Antigravity SKILL.md
    skill_content = (
        "---\n"
        f"name: {skill_name}\n"
        f"description: \"{description}\"\n"
        "---\n\n"
        f"{body}\n"
    )

    target_skill_file.write_text(skill_content, encoding="utf-8")
    return target_skill_file


def convert_commands_directory(
    commands_dir: Path,
    dest_skills_dir: Path
) -> list[Path]:
    """Scan and convert all markdown command files inside a directory."""
    if not commands_dir.exists() or not commands_dir.is_dir():
        return []

    converted: list[Path] = []
    # Collect all markdown files
    for md_file in sorted(commands_dir.glob("*.md")):
        if md_file.is_file():
            skill_path = convert_command_file(md_file, dest_skills_dir)
            converted.append(skill_path)

    return converted
