"""Converter for Claude Code commands to Google Antigravity Skills.

Claude Code defines custom commands in `commands/*.md` (or `.claude/commands/*.md`).
Antigravity uses native Skills in `skills/<name>/SKILL.md` with YAML frontmatter.
This module translates Claude Code commands directly into Antigravity Skills.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def sanitize_skill_name(raw_name: str) -> str:
    """Normalize a command name into a valid Antigravity skill directory name (kebab-case).

    Transliterates Unicode accented characters (e.g. 'validação' -> 'validacao')
    and cleans special characters and whitespace into hyphens.
    """
    # Decompose Unicode characters (e.g. 'ã' -> 'a' + combining tilde)
    normalized = unicodedata.normalize("NFKD", raw_name)
    # Strip combining marks to preserve ASCII base characters
    ascii_text = "".join(c for c in normalized if not unicodedata.combining(c))

    # Replace spaces and underscores with hyphens
    name = re.sub(r"[_\s]+", "-", ascii_text.strip().lower())
    # Remove any character that isn't alphanumeric or hyphen
    name = re.sub(r"[^a-z0-9\-]", "", name)
    # Deduplicate consecutive hyphens
    name = re.sub(r"-+", "-", name)
    return name.strip("-") or "custom-command"


def parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    """Parse YAML frontmatter supporting block scalars ('>-', '>', '|', '|-')."""
    frontmatter: Dict[str, str] = {}
    body = content

    pattern = r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return frontmatter, body.strip()

    raw_meta, body = match.group(1), match.group(2)
    lines = raw_meta.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()

            # Handle multiline YAML block scalars: >-, >, |, |-
            if val in (">-", ">", "|", "|-"):
                multiline_val: List[str] = []
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    # Indented lines belong to the multiline block
                    if next_line.startswith("  ") or next_line.startswith("\t"):
                        multiline_val.append(next_line.strip())
                        i += 1
                    elif not next_line.strip():
                        i += 1
                    else:
                        break
                if val.startswith(">"):
                    # Folded scalar: join lines with spaces
                    frontmatter[key] = " ".join(multiline_val).strip()
                else:
                    # Literal scalar: join lines with newlines
                    frontmatter[key] = "\n".join(multiline_val).strip()
                continue
            else:
                frontmatter[key] = val.strip("\"'")
        i += 1

    return frontmatter, body.strip()


def escape_yaml_string(text: str) -> str:
    """Safely format a string for YAML double-quoted scalar."""
    clean = text.replace("\\", "\\\\").replace('"', '\\"')
    clean = " ".join(clean.splitlines()).strip()
    return clean


def extract_description(body: str, metadata: Dict[str, str], command_name: str) -> str:
    """Extract or synthesize an accurate 3rd-person description for the Skill frontmatter."""
    # 1. Prefer frontmatter description if present
    if "description" in metadata and metadata["description"]:
        desc = metadata["description"].strip()
        if desc not in (">-", ">", "|", "|-"):
            return desc

    # 2. Look for the first Markdown heading
    heading_match = re.search(r"^#+\s+(.+)$", body, re.MULTILINE)
    if heading_match:
        heading_text = heading_match.group(1).strip()
        if heading_text.lower() != command_name.lower():
            return f"Executes the /{command_name} routine: {heading_text}."

    # 3. Look for the first non-empty paragraph
    lines = [line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")]
    if lines:
        first_line = lines[0]
        clean_line = re.sub(r"[\*`_]", "", first_line)
        if len(clean_line) > 120:
            clean_line = clean_line[:117] + "..."
        return clean_line

    # 4. Default fallback
    return f"Executes the /{command_name} command migrated from Claude Code."


def adapt_prompt_arguments(body: str) -> str:
    """Adapt Claude Code argument placeholders ($ARGUMENTS, $1..$9) for Antigravity instructions.

    Isolates markdown code blocks (fenced ``` and inline `) to avoid corrupting bash scripts
    or code examples, and applies strict word boundaries to avoid replacing monetary values ($50).
    """
    code_blocks: List[str] = []

    def _stash_code(match: re.Match) -> str:
        code_blocks.append(match.group(0))
        return f"__CC2AGY_CODE_STASH_{len(code_blocks)-1}__"

    # 1. Stash fenced code blocks, then inline code
    protected = re.sub(r"```[\s\S]*?```", _stash_code, body)
    protected = re.sub(r"`[^`\n]+`", _stash_code, protected)

    # 2. Check for legitimate argument variables with strict word boundary
    # (no \b before "$": "$" is not a word character, so \b would demand a letter before it)
    has_arguments = bool(re.search(r"(?:\$ARGUMENTS\b|\$[1-9]\b)", protected))

    if has_arguments:
        # Replace $ARGUMENTS
        protected = re.sub(r"\$ARGUMENTS\b", "[User Arguments provided after the slash command]", protected)
        # Replace $1..$9 (guaranteeing not matching $50, $100, etc.)
        protected = re.sub(r"\$([1-9])\b", r"[Argument \1 provided by user]", protected)

        notice = (
            "> [!NOTE]\n"
            "> This skill was migrated from a Claude Code slash command. "
            "Any user parameters passed after the slash command should be applied to the placeholders below.\n\n"
        )
        protected = notice + protected

    # 3. Restore code blocks
    for idx, block in enumerate(code_blocks):
        protected = protected.replace(f"__CC2AGY_CODE_STASH_{idx}__", block)

    return protected


def _resolve_skill_name(meta: Dict[str, str], source_file: Path, custom_name: Optional[str] = None) -> str:
    """Determine the canonical skill name for a command file."""
    return sanitize_skill_name(custom_name or meta.get("name") or source_file.stem)


def command_skill_name(source_file: Path) -> str:
    """Return the skill name a command file converts to (same rule as convert_command_file)."""
    meta, _ = parse_frontmatter(source_file.read_text(encoding="utf-8"))
    return _resolve_skill_name(meta, source_file)


def convert_command_file(
    source_file: Path,
    dest_skills_dir: Path,
    custom_name: Optional[str] = None,
    overwrite: bool = False
) -> Path:
    """Convert a single Claude Code command file into an Antigravity Skill folder."""
    raw_content = source_file.read_text(encoding="utf-8")
    meta, raw_body = parse_frontmatter(raw_content)

    # Determine canonical skill name
    skill_name = _resolve_skill_name(meta, source_file, custom_name)

    # Generate description and adapt body
    description = extract_description(raw_body, meta, skill_name)
    body = adapt_prompt_arguments(raw_body)

    # Target folder and SKILL.md path
    skill_folder = dest_skills_dir / skill_name
    skill_folder.mkdir(parents=True, exist_ok=True)
    target_skill_file = skill_folder / "SKILL.md"

    if target_skill_file.exists() and not overwrite:
        raise FileExistsError(
            f"Target skill file already exists: '{target_skill_file}'. "
            "Pass overwrite=True to allow overwriting."
        )

    escaped_desc = escape_yaml_string(description)
    skill_content = (
        "---\n"
        f"name: {skill_name}\n"
        f'description: "{escaped_desc}"\n'
        "---\n\n"
        f"{body}\n"
    )

    target_skill_file.write_text(skill_content, encoding="utf-8")
    return target_skill_file


def convert_commands_directory(
    commands_dir: Path,
    dest_skills_dir: Path,
    overwrite: bool = False,
    skip_names: Optional[Set[str]] = None,
    failures: Optional[List[Tuple[Path, Exception]]] = None,
) -> list[Path]:
    """Scan and convert all markdown command files inside a directory (including nested subfolders).

    Args:
        skip_names: Skill names already provided elsewhere (e.g. modular skills);
            commands resolving to one of these names are not converted.
        failures: When given, per-file read/conversion errors are collected here as
            (source_file, exception) and the remaining files are still converted.
            When omitted, the first error is raised.
    """
    if not commands_dir.exists() or not commands_dir.is_dir():
        return []

    converted: list[Path] = []
    # Collect all markdown files recursively
    for md_file in sorted(commands_dir.rglob("*.md")):
        if md_file.is_file():
            try:
                if skip_names and command_skill_name(md_file) in skip_names:
                    continue
                skill_path = convert_command_file(md_file, dest_skills_dir, overwrite=overwrite)
                converted.append(skill_path)
            except FileExistsError:
                # Safe skip when overwrite is False
                continue
            except (ValueError, OSError) as e:
                if failures is None:
                    raise
                failures.append((md_file, e))

    return converted
