"""Converter for Claude Code governance rules to Google Antigravity AGENTS.md.

Claude Code defines project rules and behavior instructions in `CLAUDE.md`.
Google Antigravity defines directory-based workspace rules in `AGENTS.md` (or `GEMINI.md`).
According to official Antigravity specifications (rules.md):
- Standalone AGENTS.md files DO NOT support YAML frontmatter.
- Each rule file has a per-file size limit of 24 KB (24,000 bytes).
- Aggregate rules budget across the workspace is 20,000 tokens.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

# Per-file size cap defined by Antigravity rules.md (24 KB)
MAX_RULE_FILE_BYTES = 24000


def clean_rules_content(content: str) -> Tuple[str, bool]:
    """Strip YAML frontmatter if present and sanitize rule content.

    Returns:
        Tuple of (cleaned_content, had_frontmatter).
    """
    had_frontmatter = False
    cleaned = content.strip()

    # Antigravity AGENTS.md does not support YAML frontmatter.
    pattern = r"^---\r?\n.*?\r?\n---\r?\n(.*)$"
    match = re.search(pattern, cleaned, re.DOTALL)
    if match:
        had_frontmatter = True
        cleaned = match.group(1).strip()

    # Prepend comment marker for tracking lineage without violating pure Markdown format
    banner = "<!-- AGENTS.md — Converted from CLAUDE.md by cc2agy -->\n\n"
    if not cleaned.startswith("<!--"):
        cleaned = banner + cleaned

    return cleaned, had_frontmatter


def convert_rules_file(
    source_file: Path,
    dest_dir: Path,
    custom_filename: str = "AGENTS.md",
    overwrite: bool = False
) -> Tuple[Path, list[str]]:
    """Convert a Claude Code CLAUDE.md file into an Antigravity AGENTS.md file.

    Args:
        source_file: Path to source CLAUDE.md file.
        dest_dir: Target directory where AGENTS.md will be placed.
        custom_filename: Target filename (default: "AGENTS.md").
        overwrite: Whether to overwrite existing destination file.

    Returns:
        Tuple of (target_file_path, warnings_list).

    Raises:
        FileNotFoundError: If source_file does not exist.
        FileExistsError: If target file exists and overwrite is False.
    """
    if not source_file.exists() or not source_file.is_file():
        raise FileNotFoundError(f"Source rules file not found: {source_file}")

    raw_content = source_file.read_text(encoding="utf-8")
    cleaned_content, had_frontmatter = clean_rules_content(raw_content)

    warnings: list[str] = []
    if had_frontmatter:
        warnings.append("YAML frontmatter was detected and stripped (AGENTS.md requires pure Markdown).")

    # Check byte size against Antigravity 24 KB per-file cap
    content_bytes = len(cleaned_content.encode("utf-8"))
    if content_bytes > MAX_RULE_FILE_BYTES:
        warnings.append(
            f"Rule size ({content_bytes} bytes) exceeds the Antigravity per-file recommendation of "
            f"{MAX_RULE_FILE_BYTES} bytes. Rules exceeding the budget may be truncated or demoted to on-demand reads."
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    target_file = dest_dir / custom_filename

    if target_file.exists() and not overwrite:
        raise FileExistsError(
            f"Target rules file already exists: '{target_file}'. Pass overwrite=True to allow replacement."
        )

    target_file.write_text(cleaned_content, encoding="utf-8")
    return target_file, warnings
