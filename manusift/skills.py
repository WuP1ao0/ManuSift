"""Skill system (Step P4.2).

A "skill" is a small, named bundle of
instructions the agent can pull into the
context on demand. The format is a
markdown file with a YAML frontmatter and a
markdown body:

    ---
    name: analyze_paper
    description: Run all five detectors on a PDF.
    arguments:
      - name: trace_id
        required: true
    ---

    # analyze_paper

    Call the metadata, image_dup,
    image_forensics, text_patterns, and
    citation_network detectors in order on
    the bound PDF. Then summarize the
    findings in plain English.

Skills live in ``settings.skills_dir``
(default ``./data/skills``). Host agents or
library ``create_agent_loop`` sessions may
load a skill body as a user-role instruction
so it composes with tool-calling. The old
chat TUI ``/skill`` slash command is gone
(product B+C).

Guarantees:

  * ``load_skill(name)`` returns a
    ``Skill`` dataclass with the parsed
    frontmatter and the body markdown.
  * ``list_skills()`` returns names sorted
    alphabetically, deduped.
  * Skills with malformed frontmatter are
    skipped, not raised, so one bad file
    in ``data/skills/`` does not break
    every other skill.
  * Skills without a ``name`` field use
    the file's stem as the name.
  * ``SkillNotFound`` is raised for an
    unknown name.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .trace import get_logger

log = get_logger(__name__)


class SkillNotFound(LookupError):
    """Raised when ``load_skill(name)`` is
    called for a name that does not exist
    in the configured skills directory."""


@dataclass
class SkillArgument:
    """One argument declared in the skill's
    YAML frontmatter. ``required`` defaults
    to ``False`` so hosts can pre-fill an
    empty value when the user omits one."""
    name: str
    description: str = ""
    required: bool = False


@dataclass
class Skill:
    """A parsed ``SKILL.md`` file."""
    name: str
    description: str
    body: str
    arguments: list[SkillArgument] = field(default_factory=list)
    # The path the skill was loaded from.
    # ``None`` for in-memory skills (the
    # tests construct one directly without
    # touching the filesystem).
    path: Path | None = None


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown file into (yaml dict,
    body). The frontmatter is the block
    between the first pair of ``---``
    markers. If the file does not start
    with ``---``, there is no frontmatter
    and the body is the whole file.
    """
    if not text.startswith("---"):
        return {}, text
    # Find the closing ``---`` line.
    m = re.search(r"\n---\s*\n", text[3:])
    if not m:
        return {}, text
    yaml_text = text[3 : 3 + m.start()]
    body = text[3 + m.end() :]
    try:
        meta = yaml.safe_load(yaml_text) or {}
        if not isinstance(meta, dict):
            log.warning(
                "skill frontmatter is not a dict",
                extra={"meta_type": type(meta).__name__},
            )
            return None
        return meta, body
    except yaml.YAMLError as exc:
        log.warning(
            "skill frontmatter parse failed",
            extra={"err": str(exc)},
        )
        return None


def list_skills(skills_dir: Path) -> list[str]:
    """Return the names of every skill in
    ``skills_dir``, sorted alphabetically
    and deduped. Files that fail to parse
    are skipped, not raised — a single bad
    skill file does not break the listing.
    """
    if not skills_dir.is_dir():
        return []
    names: set[str] = set()
    for f in sorted(skills_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".md", ".markdown"):
            continue
        try:
            skill = load_skill_from_path(f)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "could not load skill file",
                extra={"file": f.name, "err": str(exc)},
            )
            continue
        if skill is not None:
            names.add(skill.name)
    return sorted(names)


def load_skill(name: str, skills_dir: Path) -> Skill:
    """Load the skill named ``name`` from
    ``skills_dir``. Raises ``SkillNotFound``
    if no file in the directory has a
    matching name (either the frontmatter
    ``name`` or the file stem)."""
    if not skills_dir.is_dir():
        raise SkillNotFound(
            f"skills directory {skills_dir!r} does not exist"
        )
    for f in sorted(skills_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".md", ".markdown"):
            continue
        skill = load_skill_from_path(f)
        if skill is not None and skill.name == name:
            return skill
    raise SkillNotFound(
        f"no skill named {name!r} in {skills_dir}"
    )


def load_skill_from_path(path: Path) -> Skill | None:
    """Parse a single ``SKILL.md``-style
    file. Returns ``None`` (after logging)
    if the file is unreadable or the
    frontmatter is malformed beyond
    recovery. The two error cases we
    tolerate are:

      * the file is empty or unreadable;
      * the frontmatter is not a YAML dict.

    Anything else (a missing name, a
    malformed arguments list, etc.) is left
    to the caller to surface — those are
    user errors, not internal failures.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning(
            "could not read skill file",
            extra={"file": path.name, "err": str(exc)},
        )
        return None
    result = _parse_frontmatter(text)
    if result is None:
        return None
    meta, body = result
    name = str(meta.get("name") or path.stem)
    description = str(meta.get("description") or "")
    raw_args = meta.get("arguments") or []
    arguments: list[SkillArgument] = []
    if isinstance(raw_args, list):
        for a in raw_args:
            if not isinstance(a, dict):
                continue
            arguments.append(
                SkillArgument(
                    name=str(a.get("name") or ""),
                    description=str(a.get("description") or ""),
                    required=bool(a.get("required", False)),
                )
            )
    return Skill(
        name=name,
        description=description,
        body=body.strip(),
        arguments=arguments,
        path=path,
    )
