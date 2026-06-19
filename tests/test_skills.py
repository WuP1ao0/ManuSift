"""Tests for the skill system (Step P4.2).

A "skill" is a small, named bundle of
instructions the agent can pull into the
context on demand. Skills live in
``settings.skills_dir`` as markdown files
with a YAML frontmatter and a markdown
body.

Guarantees:

  1. ``load_skill(name)`` returns a
     ``Skill`` dataclass with the parsed
     frontmatter and the body.
  2. ``list_skills()`` returns names sorted
     alphabetically, deduped, ignoring
     non-markdown files.
  3. A skill file with a malformed
     frontmatter is skipped, not raised.
  4. A skill file with no ``name`` field
     uses the file's stem as the name.
  5. ``SkillNotFound`` is raised for an
     unknown name.
  6. The chat TUI's ``/skill <name>``
     command loads the skill and injects
     its body as a user-role message; the
     agent then runs with the skill
     instructions in context.
  7. ``/skills`` lists the names of every
     available skill.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------- helpers ----------

def _write_skill(
    parent: Path, name: str, body: str, **kwargs
) -> Path:
    """Write a single skill file to
    ``parent`` and return its path."""
    target = parent / f"{name}.md"
    front = {"name": name, "description": kwargs.get("description", "")}
    if "arguments" in kwargs:
        front["arguments"] = kwargs["arguments"]
    yaml_block = "\n".join(
        f"{k}: {json.dumps(v)}" for k, v in front.items()
    )
    target.write_text(
        f"---\n{yaml_block}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return target


# ---------- 1. load_skill returns Skill ----------

def test_load_skill_returns_parsed_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``load_skill(name)`` returns a
    ``Skill`` with the parsed frontmatter
    and the body markdown."""
    from manusift.skills import load_skill
    _write_skill(
        tmp_path, "analyze_paper",
        "Run all five detectors.",
        description="Full analysis",
    )
    s = load_skill("analyze_paper", tmp_path)
    assert s.name == "analyze_paper"
    assert s.description == "Full analysis"
    assert "Run all five detectors." in s.body


def test_load_skill_parses_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``arguments`` frontmatter is
    parsed into a list of ``SkillArgument``
    with the right ``required`` flag."""
    from manusift.skills import load_skill
    _write_skill(
        tmp_path, "compare",
        "compare two PDFs",
        arguments=[
            {"name": "path_a", "required": True},
            {"name": "path_b", "required": False},
        ],
    )
    s = load_skill("compare", tmp_path)
    assert len(s.arguments) == 2
    assert s.arguments[0].name == "path_a"
    assert s.arguments[0].required is True
    assert s.arguments[1].name == "path_b"
    assert s.arguments[1].required is False


# ---------- 2. list_skills sorted, deduped ----------

def test_list_skills_returns_sorted_unique_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``list_skills`` returns names sorted
    alphabetically, deduped, ignoring
    non-markdown files."""
    from manusift.skills import list_skills
    _write_skill(tmp_path, "zebra", "z")
    _write_skill(tmp_path, "alpha", "a")
    _write_skill(tmp_path, "mike", "m")
    # Drop a non-markdown file in there.
    (tmp_path / "README.txt").write_text("not a skill", encoding="utf-8")
    names = list_skills(tmp_path)
    assert names == ["alpha", "mike", "zebra"]


def test_list_skills_empty_when_no_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``list_skills`` returns an empty
    list when the directory does not exist
    (rather than raising)."""
    from manusift.skills import list_skills
    bogus = tmp_path / "does_not_exist"
    assert list_skills(bogus) == []


# ---------- 3. Malformed frontmatter is skipped ----------

def test_malformed_frontmatter_skill_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skill file with a malformed
    frontmatter is skipped silently — its
    name does not appear in
    ``list_skills``, and ``load_skill`` for
    that name raises ``SkillNotFound``."""
    from manusift.skills import list_skills, load_skill, SkillNotFound
    # A skill whose frontmatter is
    # valid YAML but not a dict (e.g. a
    # bare list). ``yaml.safe_load`` returns
    # a list, and our parser treats that as
    # "no frontmatter" and falls back to the
    # file stem as the name. So this file
    # is loaded, not skipped — let us write
    # a file that *cannot* be parsed at
    # all instead.
    bad = tmp_path / "bad.md"
    bad.write_text(
        "---\n: invalid: yaml: : :\n---\n\nbody\n",
        encoding="utf-8",
    )
    # The malformed file is logged and
    # skipped, so it does not appear in
    # ``list_skills``.
    assert "bad" not in list_skills(tmp_path)
    # And ``load_skill("bad", tmp_path)``
    # raises ``SkillNotFound``.
    with pytest.raises(SkillNotFound):
        load_skill("bad", tmp_path)


# ---------- 4. Stem-as-name fallback ----------

def test_skill_with_no_name_uses_file_stem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A skill file with no ``name`` field
    in the frontmatter uses the file's
    stem as the skill name."""
    from manusift.skills import load_skill
    # No frontmatter at all.
    (tmp_path / "my_skill.md").write_text(
        "just a body, no frontmatter\n",
        encoding="utf-8",
    )
    s = load_skill("my_skill", tmp_path)
    assert s.name == "my_skill"
    assert "just a body" in s.body


# ---------- 5. SkillNotFound for unknown name ----------

def test_load_unknown_skill_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``load_skill("nope", dir)`` raises
    ``SkillNotFound`` when there is no
    file with that name in the
    directory."""
    from manusift.skills import load_skill, SkillNotFound
    _write_skill(tmp_path, "real_skill", "body")
    with pytest.raises(SkillNotFound):
        load_skill("imaginary_skill", tmp_path)


# ---------- 6. /skill injects the body ----------

def test_skill_command_injects_body_into_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chat TUI's ``/skill <name>``
    command loads the skill and appends
    its body as a user-role message. The
    agent then runs with the skill
    instructions in context. We assert
    that the chat history contains the
    skill body before the agent's
    response."""
    from manusift.llm import MockLLM
    from manusift.config import get_settings
    from manusift.tui import chat_app as _chat_mod
    from manusift.tui.chat_app import ChatApp
    import uuid
    # Set up a workspace + skills dir under
    # it.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    skills_dir = workspace / "skills"
    skills_dir.mkdir()
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(workspace)
    )
    monkeypatch.setenv("MANUSIFT_SKILLS_DIR", str(skills_dir))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    _write_skill(
        skills_dir, "analyze",
        "Run all five detectors in order.",
        description="Full pipeline",
    )
    app = ChatApp.__new__(ChatApp)
    app._session_id = uuid.uuid4().hex[:12]
    app._session_dir = _chat_mod._chat_dir(app._session_id)
    app._llm = MockLLM()
    app._tools = []
    app._agent_running = False
    app._parsed_doc = None
    from manusift.tools import ToolContext
    app._ctx = ToolContext(trace_id=app._session_id)
    captured: list = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._set_status = lambda t: None  # type: ignore[method-assign]
    # Dispatch the slash command. We use
    # ``_handle_command`` directly to avoid
    # the textual event loop.
    app._handle_command("/skill analyze")
    # The skill body is in the captured
    # history as a user-role message.
    skill_msgs = [
        m for m in captured
        if "running skill" in getattr(m, "content", "")
    ]
    assert len(skill_msgs) == 1
    assert "Run all five detectors" in skill_msgs[0].content


def test_skill_command_unknown_name_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown skill name surfaces a
    system message that mentions
    ``/skills`` (so the user can discover
    the right name)."""
    from manusift.llm import MockLLM
    from manusift.config import get_settings
    from manusift.tui import chat_app as _chat_mod
    from manusift.tui.chat_app import ChatApp
    import uuid
    workspace = tmp_path / "ws"
    workspace.mkdir()
    skills_dir = workspace / "skills"
    skills_dir.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_SKILLS_DIR", str(skills_dir))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    app = ChatApp.__new__(ChatApp)
    app._session_id = uuid.uuid4().hex[:12]
    app._session_dir = _chat_mod._chat_dir(app._session_id)
    app._llm = MockLLM()
    app._tools = []
    app._agent_running = False
    app._parsed_doc = None
    from manusift.tools import ToolContext
    app._ctx = ToolContext(trace_id=app._session_id)
    captured: list = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._set_status = lambda t: None  # type: ignore[method-assign]
    app._handle_command("/skill no_such_skill")
    sys_msgs = [
        m for m in captured
        if "no skill named" in getattr(m, "content", "")
    ]
    assert len(sys_msgs) == 1
    assert "/skills" in sys_msgs[0].content


# ---------- 7. /skills lists available skills ----------

def test_skills_command_lists_skill_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``/skills`` slash command
    appends a system message listing
    every skill in the skills directory.
    """
    from manusift.llm import MockLLM
    from manusift.config import get_settings
    from manusift.tui import chat_app as _chat_mod
    from manusift.tui.chat_app import ChatApp
    import uuid
    workspace = tmp_path / "ws"
    workspace.mkdir()
    skills_dir = workspace / "skills"
    skills_dir.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_SKILLS_DIR", str(skills_dir))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    _write_skill(skills_dir, "analyze", "a")
    _write_skill(skills_dir, "compare", "c")
    app = ChatApp.__new__(ChatApp)
    app._session_id = uuid.uuid4().hex[:12]
    app._session_dir = _chat_mod._chat_dir(app._session_id)
    app._llm = MockLLM()
    app._tools = []
    app._agent_running = False
    app._parsed_doc = None
    from manusift.tools import ToolContext
    app._ctx = ToolContext(trace_id=app._session_id)
    captured: list = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._set_status = lambda t: None  # type: ignore[method-assign]
    app._handle_command("/skills")
    sys_msgs = [
        m for m in captured
        if "skills:" in getattr(m, "content", "")
    ]
    assert len(sys_msgs) == 1
    assert "analyze" in sys_msgs[0].content
    assert "compare" in sys_msgs[0].content


def test_skills_command_empty_dir_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the skills directory is empty,
    ``/skills`` says so and points the
    user to the directory location so they
    know where to drop a new skill."""
    from manusift.llm import MockLLM
    from manusift.config import get_settings
    from manusift.tui import chat_app as _chat_mod
    from manusift.tui.chat_app import ChatApp
    import uuid
    workspace = tmp_path / "ws"
    workspace.mkdir()
    skills_dir = workspace / "skills"
    skills_dir.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_SKILLS_DIR", str(skills_dir))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    app = ChatApp.__new__(ChatApp)
    app._session_id = uuid.uuid4().hex[:12]
    app._session_dir = _chat_mod._chat_dir(app._session_id)
    app._llm = MockLLM()
    app._tools = []
    app._agent_running = False
    app._parsed_doc = None
    from manusift.tools import ToolContext
    app._ctx = ToolContext(trace_id=app._session_id)
    captured: list = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._set_status = lambda t: None  # type: ignore[method-assign]
    app._handle_command("/skills")
    sys_msgs = [
        m for m in captured
        if "no skills found" in getattr(m, "content", "")
    ]
    assert len(sys_msgs) == 1
    assert str(skills_dir) in sys_msgs[0].content
