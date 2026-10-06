"""Migrator and synchronizer for modular Claude Code Skills to Google Antigravity.

Claude Code plugins often include pre-packaged modular skills in `skills/<skill-name>/`
containing `SKILL.md`, references, and auxiliary scripts. Antigravity shares this
exact architectural pattern. This module safely migrates, sanitizes, and synchronizes
modular skills into canonical Antigravity skill folders.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path
from typing import List, Optional, Tuple

from .commands import sanitize_skill_name


def _remove_readonly(func, path, excinfo):
    """Clear the readonly bit and reattempt removal on Windows platforms."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


_FRONTMATTER_RE = re.compile(r"\A(---\r?\n)(.*?)(\r?\n---[ \t]*(?:\r?\n|\Z))", re.DOTALL)
_TOP_LEVEL_NAME_RE = re.compile(r"^name[ \t]*:[^\r\n]*", re.MULTILINE)


def _set_frontmatter_name(content: str, skill_name: str) -> Optional[str]:
    """Return content with the top-level frontmatter 'name' set to skill_name.

    Only the 'name' line is touched; every other line (lists, nested keys, quoting,
    line endings) is preserved verbatim. Returns None when no change is needed or
    when the file has no frontmatter.
    """
    fm_match = _FRONTMATTER_RE.match(content)
    if not fm_match:
        return None

    opening, block, closing = fm_match.groups()
    new_line = f"name: {skill_name}"
    name_match = _TOP_LEVEL_NAME_RE.search(block)

    if name_match:
        current = name_match.group(0).split(":", 1)[1].strip().strip("\"'")
        if current == skill_name:
            return None
        new_block = block[:name_match.start()] + new_line + block[name_match.end():]
    else:
        newline = "\r\n" if opening.endswith("\r\n") else "\n"
        new_block = new_line + newline + block

    return opening + new_block + closing + content[fm_match.end():]


def migrate_skill_folder(
    source_skill_dir: Path,
    dest_skills_dir: Path,
    overwrite: bool = False
) -> Path:
    """Migrate an existing modular skill folder into the destination skills directory.

    Preserves all auxiliary subdirectories (references/, scripts/, assets/, etc.).
    Ensures canonical kebab-case naming and YAML frontmatter compliance.
    """
    if not source_skill_dir.exists() or not source_skill_dir.is_dir():
        raise FileNotFoundError(f"Source skill folder not found: {source_skill_dir}")

    skill_name = sanitize_skill_name(source_skill_dir.name)
    target_skill_dir = dest_skills_dir / skill_name

    # Refuse overlapping source/destination: the overwrite step below would delete the source
    source_resolved = source_skill_dir.resolve()
    target_resolved = target_skill_dir.resolve()
    if (
        source_resolved == target_resolved
        or source_resolved.is_relative_to(target_resolved)
        or target_resolved.is_relative_to(source_resolved)
    ):
        raise ValueError(
            f"Source and destination skill folders overlap: '{source_skill_dir}' -> '{target_skill_dir}'. "
            "Choose a destination outside the source skill folder."
        )

    if target_skill_dir.exists() and not overwrite:
        raise FileExistsError(
            f"Target skill directory already exists: '{target_skill_dir}'. "
            "Pass overwrite=True to allow overwriting."
        )

    if target_skill_dir.exists() and overwrite:
        shutil.rmtree(target_skill_dir, onerror=_remove_readonly)

    # Recursively copy all contents (SKILL.md, references/, scripts/, etc.)
    shutil.copytree(source_skill_dir, target_skill_dir)

    # Ensure SKILL.md exists with canonical casing
    target_skill_file = target_skill_dir / "SKILL.md"
    if not target_skill_file.exists():
        for f in target_skill_dir.iterdir():
            if f.is_file() and f.name.lower() == "skill.md":
                f.rename(target_skill_file)
                break

    # Normalize frontmatter name to match directory, rewriting only the 'name' line
    if target_skill_file.exists():
        # newline="" keeps the original line endings untouched on read and write
        with open(target_skill_file, "r", encoding="utf-8", errors="replace", newline="") as f:
            content = f.read()
        new_content = _set_frontmatter_name(content, skill_name)
        if new_content is not None:
            with open(target_skill_file, "w", encoding="utf-8", newline="") as f:
                f.write(new_content)

    return target_skill_file if target_skill_file.exists() else target_skill_dir


def migrate_skills_directory(
    skills_source: Path,
    dest_skills_dir: Path,
    overwrite: bool = False,
    failures: Optional[List[Tuple[Path, Exception]]] = None,
) -> List[Path]:
    """Scan and migrate all modular skills from a source directory.

    Handles:
    1. A single skill directory containing SKILL.md.
    2. A directory containing multiple skill subdirectories.

    When `failures` is given, per-skill errors are collected there as
    (skill_folder, exception) and the remaining skills are still migrated.
    When omitted, the first error is raised.
    """
    if not skills_source.exists() or not skills_source.is_dir():
        return []

    dest_skills_dir.mkdir(parents=True, exist_ok=True)
    migrated: List[Path] = []

    # Case 1: The source directory itself is a single skill folder
    if (skills_source / "SKILL.md").exists() or (skills_source / "skill.md").exists():
        candidates = [skills_source]
    # Case 2: The source directory contains multiple skill subdirectories
    else:
        candidates = [
            item for item in sorted(skills_source.iterdir())
            if item.is_dir() and ((item / "SKILL.md").exists() or (item / "skill.md").exists())
        ]

    for item in candidates:
        try:
            res = migrate_skill_folder(item, dest_skills_dir, overwrite=overwrite)
            migrated.append(res)
        except FileExistsError:
            continue
        except (ValueError, OSError) as e:
            if failures is None:
                raise
            failures.append((item, e))

    return migrated
