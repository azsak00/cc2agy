"""Converter for Claude Code commands to Google Antigravity Skills.

Claude Code defines custom commands in `commands/*.md` (or `.claude/commands/*.md`).
Antigravity uses native Skills in `skills/<name>/SKILL.md` with YAML frontmatter.
This module translates Claude Code commands directly into Antigravity Skills.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


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
            elif not val:
                # Block list ("key:" followed by "  - item" lines): items joined by newlines
                items: List[str] = []
                while i + 1 < len(lines) and re.match(r"^\s*-\s+", lines[i + 1]):
                    i += 1
                    items.append(re.sub(r"^\s*-\s+", "", lines[i]).strip().strip("\"'"))
                frontmatter[key] = "\n".join(items)
            else:
                frontmatter[key] = val.strip("\"'")
        i += 1

    return frontmatter, body.strip()


def frontmatter_list(value: Optional[str]) -> List[str]:
    """Items of a frontmatter list given as '[a, b]', 'a b', 'a, b' or a block list."""
    if not value:
        return []
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return [item.strip().strip("\"'") for item in re.split(r"[,\s]+", text) if item.strip().strip("\"'")]


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


def adapt_prompt_arguments(body: str, named: Optional[List[str]] = None, origin: str = "command") -> str:
    """Adapt Claude Code argument placeholders for Antigravity instructions.

    Placeholders, as Claude Code documents them: $ARGUMENTS (all arguments), $ARGUMENTS[N]
    and its shorthand $N (0-based: $0 is the first argument), and $name for the names
    declared in the `arguments` frontmatter (in order). A backslash before a placeholder
    (\\$1) keeps it literal, without the backslash. Without any placeholder, Claude Code
    appends the typed arguments as "ARGUMENTS: <value>"; for a command (origin "command")
    a closing note asks for the same, while a skill (origin "skill") is left unchanged,
    since the model usually invokes skills on its own.

    Isolates markdown code blocks (fenced ``` and inline `) to avoid corrupting bash scripts
    or code examples, and applies strict word boundaries to avoid replacing monetary values ($50).
    """
    stash: List[str] = []

    def _stash(text: str) -> str:
        stash.append(text)
        return f"__CC2AGY_CODE_STASH_{len(stash)-1}__"

    # 1. Stash fenced code blocks, then inline code, then escaped placeholders (kept literal)
    protected = re.sub(r"```[\s\S]*?```", lambda m: _stash(m.group(0)), body)
    protected = re.sub(r"`[^`\n]+`", lambda m: _stash(m.group(0)), protected)
    names = [n for n in (named or []) if re.fullmatch(r"[A-Za-z_]\w*", n) and n != "ARGUMENTS"]
    token = r"\$(?:ARGUMENTS(?:\[\d+\])?|[0-9]" + "".join(f"|{re.escape(n)}" for n in names) + r")\b"
    protected = re.sub(r"\\(" + token + r")", lambda m: _stash(m.group(1)), protected)

    # 2. Replace the placeholders (no \b before "$": it is not a word character)
    def _position(index: int) -> str:
        return f"[Argument {index + 1} provided by user]"

    count = 0

    def _count(text: str) -> str:
        nonlocal count
        count += 1
        return text

    protected = re.sub(r"\$ARGUMENTS\[(\d+)\]", lambda m: _count(_position(int(m.group(1)))), protected)
    protected = re.sub(r"\$ARGUMENTS\b", lambda m: _count("[User Arguments provided after the slash command]"), protected)
    # $0..$9, never $50 or $100
    protected = re.sub(r"\$([0-9])\b", lambda m: _count(_position(int(m.group(1)))), protected)
    for index, name in enumerate(names):
        protected = re.sub(
            r"\$" + re.escape(name) + r"\b",
            lambda m, i=index, n=name: _count(f"[Argument {i + 1} ('{n}') provided by user]"),
            protected,
        )

    source = "skill" if origin == "skill" else "slash command"
    if count:
        protected = (
            "> [!NOTE]\n"
            f"> This skill was migrated from a Claude Code {source}. "
            "Any user parameters passed after the slash command should be applied to the placeholders below.\n\n"
            + protected
        )
    elif origin == "skill":
        pass
    else:
        protected += (
            "\n\n> [!NOTE]\n"
            "> This skill was migrated from a Claude Code slash command. If the user typed arguments "
            "after the command name, treat them as `ARGUMENTS: <what the user typed>` for these instructions."
        )

    # 3. Restore code blocks and escaped placeholders
    for idx in range(len(stash) - 1, -1, -1):
        protected = protected.replace(f"__CC2AGY_CODE_STASH_{idx}__", stash[idx])

    return protected


def _resolve_skill_name(default_name: str, custom_name: Optional[str] = None) -> str:
    """Determine the canonical skill name for a command.

    Claude Code ignores `name:` in a command file (only skills read it), so the name comes
    from the file path or from the plugin.json commands map, never from the frontmatter.
    """
    return sanitize_skill_name(custom_name or default_name)


def command_default_name(source_file: Path, commands_dir: Optional[Path] = None) -> str:
    """Return a command's name before frontmatter overrides.

    Claude Code names a command in a subfolder after its path: commands/git/commit.md
    is /git:commit. Antigravity skill names are kebab-case, so it becomes git-commit.
    """
    if commands_dir is not None:
        try:
            return "-".join(source_file.relative_to(commands_dir).with_suffix("").parts)
        except ValueError:
            pass
    return source_file.stem


def command_skill_name(
    source_file: Path, default_name: Optional[str] = None, warnings: Optional[List[str]] = None
) -> str:
    """Return the skill name a command file converts to (same rule as convert_command_file).

    A frontmatter `name:` that differs from it is reported in `warnings`: Claude Code ignores
    it, and older cc2agy versions used it, so the skill may have changed name.
    """
    name = _resolve_skill_name(default_name or source_file.stem)
    if warnings is not None:
        meta, _ = parse_frontmatter(source_file.read_text(encoding="utf-8-sig"))
        declared = meta.get("name")
        if declared and sanitize_skill_name(declared) != name:
            warnings.append(
                f"Command '{source_file}' declares name '{declared}', which Claude Code ignores in "
                f"commands; converted as '{name}'."
            )
    return name


def claim_skill_name(
    name: str,
    source: str,
    claimed: Dict[str, str],
    reserved: Optional[Set[str]] = None,
    warnings: Optional[List[str]] = None,
    kind: str = "Command",
) -> str:
    """Reserve a unique name for `source` within one conversion run.

    The first source keeps `name`; a later one gets name-2, name-3, ... (skipping
    `reserved` names) and a warning, so nothing is dropped or overwritten.
    """
    unique = name
    suffix = 2
    while unique in claimed or (unique != name and reserved and unique in reserved):
        unique = f"{name}-{suffix}"
        suffix += 1
    if unique != name and warnings is not None:
        warnings.append(
            f"{kind} '{source}' resolves to name '{name}', already used by '{claimed[name]}'; "
            f"converted as '{unique}'."
        )
    claimed[unique] = source
    return unique


def convert_command_file(
    source_file: Path,
    dest_skills_dir: Path,
    custom_name: Optional[str] = None,
    overwrite: bool = False,
    description: Optional[str] = None,
    default_name: Optional[str] = None,
    warnings: Optional[List[str]] = None,
    manifest_spec: Optional[Dict[str, Any]] = None,
) -> Path:
    """Convert a single Claude Code command file into an Antigravity Skill folder."""
    return convert_command_text(
        # utf-8-sig also reads files saved with a BOM (Windows PowerShell 5.1)
        source_file.read_text(encoding="utf-8-sig"),
        dest_skills_dir,
        default_name=default_name or source_file.stem,
        custom_name=custom_name,
        overwrite=overwrite,
        description=description,
        warnings=warnings,
        manifest_spec=manifest_spec,
        label=str(source_file),
    )


# Command frontmatter fields the skill keeps: the name comes from the path, description,
# when_to_use and argument-hint go into the skill description, arguments names placeholders
CONVERTED_COMMAND_FIELDS = {"name", "description", "when_to_use", "argument-hint", "arguments"}
# plugin.json "commands" map fields the skill keeps
CONVERTED_MANIFEST_FIELDS = {"source", "content", "description", "argumentHint"}


def _report_dropped_fields(
    meta: Dict[str, str], manifest_spec: Dict[str, Any], label: str, warnings: Optional[List[str]]
) -> None:
    """Warn about command fields Antigravity skills have no equivalent for."""
    if warnings is None:
        return
    dropped = sorted(k for k in meta if k not in CONVERTED_COMMAND_FIELDS)
    dropped += sorted(f"plugin.json {k}" for k in manifest_spec if k not in CONVERTED_MANIFEST_FIELDS)
    if dropped:
        warnings.append(
            f"Command '{label}': fields with no Antigravity skill equivalent were dropped: {', '.join(dropped)}."
        )
    if meta.get("disable-model-invocation", "").strip().lower() == "true":
        warnings.append(
            f"Command '{label}' sets disable-model-invocation (only the user may run it), which Antigravity "
            "skills do not document: the model may run the converted skill on its own."
        )


def convert_command_text(
    raw_content: str,
    dest_skills_dir: Path,
    default_name: str,
    custom_name: Optional[str] = None,
    overwrite: bool = False,
    description: Optional[str] = None,
    warnings: Optional[List[str]] = None,
    manifest_spec: Optional[Dict[str, Any]] = None,
    label: Optional[str] = None,
) -> Path:
    """Convert Claude Code command Markdown (from a file or inline in plugin.json) into a Skill folder.

    `description`, when given, takes precedence over the frontmatter and body. `when_to_use`
    and the argument hint (frontmatter `argument-hint`, else plugin.json `argumentHint` in
    `manifest_spec`) are appended to it, as Claude Code lists them. Fields with no
    equivalent are reported in `warnings`.
    """
    meta, raw_body = parse_frontmatter(raw_content)
    manifest_spec = manifest_spec or {}

    # Determine canonical skill name
    skill_name = _resolve_skill_name(default_name, custom_name)
    _report_dropped_fields(meta, manifest_spec, label or skill_name, warnings)

    # Generate description and adapt body
    description = description or extract_description(raw_body, meta, skill_name)

    def _sentence(text: str) -> str:
        text = text.rstrip()
        return text if text.endswith((".", "!", "?", ":")) else text + "."

    if meta.get("when_to_use", "").strip():
        description = f"{_sentence(description)} {meta['when_to_use'].strip()}"
    hint = meta.get("argument-hint", "").strip()
    if not hint and isinstance(manifest_spec.get("argumentHint"), str):
        hint = manifest_spec["argumentHint"].strip()
    if hint:
        description = f"{_sentence(description)} Arguments: {hint}"
    body = adapt_prompt_arguments(raw_body, frontmatter_list(meta.get("arguments")))

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
    claimed: Optional[Dict[str, str]] = None,
    warnings: Optional[List[str]] = None,
) -> list[Path]:
    """Scan and convert all markdown command files inside a directory (including nested subfolders).

    Args:
        skip_names: Skill names already provided elsewhere (e.g. modular skills);
            commands resolving to one of these names are not converted.
        failures: When given, per-file read/conversion errors are collected here as
            (source_file, exception) and the remaining files are still converted.
            When omitted, the first error is raised.
        claimed: Skill names already given to commands in this run (name -> source);
            share it across calls so commands in different folders never collide.
        warnings: When given, a renamed command (name collision) or an ignored
            frontmatter `name:` is reported here.
    """
    if not commands_dir.exists() or not commands_dir.is_dir():
        return []

    if claimed is None:
        claimed = {}
    converted: list[Path] = []
    # Collect all markdown files recursively
    for md_file in sorted(commands_dir.rglob("*.md")):
        if md_file.is_file():
            try:
                default_name = command_default_name(md_file, commands_dir)
                name = command_skill_name(md_file, default_name, warnings)
                if skip_names and name in skip_names:
                    continue
                name = claim_skill_name(name, str(md_file), claimed, skip_names, warnings)
                skill_path = convert_command_file(
                    md_file, dest_skills_dir, custom_name=name, overwrite=overwrite, warnings=warnings
                )
                converted.append(skill_path)
            except FileExistsError:
                # Safe skip when overwrite is False
                continue
            except (ValueError, OSError) as e:
                if failures is None:
                    raise
                failures.append((md_file, e))

    return converted
