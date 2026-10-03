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
from typing import List, Optional

from .commands import parse_frontmatter, sanitize_skill_name


def _remove_readonly(func, path, excinfo):
    """Clear the readonly bit and reattempt removal on Windows platforms."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


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

    # Validate and normalize frontmatter name matching directory
    if target_skill_file.exists():
        content = target_skill_file.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(content)
        if meta and meta.get("name") != skill_name:
            meta["name"] = skill_name
            frontmatter_lines = ["---"]
            for k, v in meta.items():
                if "\n" in v or '"' in v:
                    escaped_v = v.replace('"', '\\"')
                    frontmatter_lines.append(f'{k}: "{escaped_v}"')
                else:
                    frontmatter_lines.append(f"{k}: {v}")
            frontmatter_lines.append("---\n")
            new_content = "\n".join(frontmatter_lines) + "\n" + body.strip() + "\n"
            target_skill_file.write_text(new_content, encoding="utf-8")

    return target_skill_file if target_skill_file.exists() else target_skill_dir


def migrate_skills_directory(
    skills_source: Path,
    dest_skills_dir: Path,
    overwrite: bool = False
) -> List[Path]:
    """Scan and migrate all modular skills from a source directory.

    Handles:
    1. A single skill directory containing SKILL.md.
    2. A directory containing multiple skill subdirectories.
    """
    if not skills_source.exists() or not skills_source.is_dir():
        return []

    dest_skills_dir.mkdir(parents=True, exist_ok=True)
    migrated: List[Path] = []

    # Case 1: The source directory itself is a single skill folder
    if (skills_source / "SKILL.md").exists() or (skills_source / "skill.md").exists():
        try:
            res = migrate_skill_folder(skills_source, dest_skills_dir, overwrite=overwrite)
            migrated.append(res)
        except FileExistsError:
            pass
        return migrated

    # Case 2: The source directory contains multiple skill subdirectories
    for item in sorted(skills_source.iterdir()):
        if item.is_dir():
            if (item / "SKILL.md").exists() or (item / "skill.md").exists():
                try:
                    res = migrate_skill_folder(item, dest_skills_dir, overwrite=overwrite)
                    migrated.append(res)
                except FileExistsError:
                    continue

    return migrated
