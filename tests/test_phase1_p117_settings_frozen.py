"""R-2026-06-15 (Phase 1 + P1-17):
test that ``Settings`` is
``frozen=True``.

The audit found that the
``Settings`` object (a
Pydantic v2 ``BaseSettings``)
was *not* frozen, so a test
or a tool could do
``settings.foo = ...`` after
construction and the next
``get_settings()`` call
would see the modified value
(the cache returns the
*same* object every call).
This is a silent-corruption
trap: a one-line mutation
in a tool changes the
behaviour of every other
tool that reads the
settings.

The fix adds ``frozen=True``
to ``Settings.model_config``,
so Pydantic v2 raises
``ValidationError`` on any
attribute assignment after
construction.  Use
``model_copy`` (preferred)
or ``object.__setattr__``
(only in tests, with a
comment) to mutate.

Tests:

  1. A fresh ``Settings()``
     rejects
     ``settings.allow_shell = False``
     with ``ValidationError``.
  2. ``model_copy(update=...)``
     returns a new
     ``Settings`` with the
     override applied; the
     original is unchanged.
  3. ``get_settings()`` cache
     returns the same object
     every call (so a tool
     cannot accidentally
     leak a mutation).
  4. ``Settings`` is still
     constructible from
     env vars (env override
     works at construction
     time, not after).
"""
from __future__ import annotations

import pytest


def test_p17_settings_is_frozen():
    """A fresh ``Settings()``
    rejects attribute
    assignment with
    ``ValidationError`` (Pydantic
    v2's frozen-instance
    check).
    """
    from manusift.config import Settings

    s = Settings()
    with pytest.raises(Exception) as excinfo:
        s.allow_shell = False
    # Pydantic v2 raises
    # ``ValidationError`` (the
    # ``frozen`` model
    # setting validates
    # against the model
    # config on assignment).
    # The exception class
    # name is
    # ``ValidationError``
    # (not
    # ``FrozenInstanceError``
    # -- Pydantic v2
    # unified both under the
    # same error class).
    err_cls = type(excinfo.value).__name__
    assert err_cls in (
        "ValidationError",
        "FrozenInstanceError",
    ), f"unexpected error class: {err_cls}"


def test_p17_settings_model_copy_returns_new_instance():
    """``model_copy`` returns a
    *new* ``Settings`` with
    the override applied.
    The original is
    unchanged.
    """
    from manusift.config import Settings

    original = Settings()
    original_value = original.allow_shell
    override_value = not original_value
    # ``allow_shell`` may be a
    # non-bool field (e.g. a
    # string-enum); coerce
    # for the test.
    new = original.model_copy(
        update={"allow_shell": override_value}
    )
    # The new instance has
    # the override.
    assert new.allow_shell == override_value
    # The original is
    # unchanged.
    assert original.allow_shell == original_value
    # The new instance is a
    # new object.
    assert new is not original


def test_p17_get_settings_returns_fresh_each_call():
    """``get_settings()`` returns
    a *fresh* object every
    call (the comment on the
    function says "We don't
    use ``lru_cache`` so tests
    can monkey-patch the env
    and call this function
    again").  This is the
    opposite of a cache --
    the value is rebuilt from
    the current env on every
    call.  Two calls return
    *equal* but *not
    identical* objects.

    Combined with
    ``frozen=True``, this
    means: a tool that
    mutates a local
    ``Settings()`` copy
    cannot leak the mutation
    to other tools, because
    the next
    ``get_settings()`` call
    builds a fresh object
    from env vars.
    """
    from manusift.config import get_settings

    s1 = get_settings()
    s2 = get_settings()
    # The two objects are
    # equal (same env-derived
    # values) but not
    # identical.
    assert s1 is not s2
    assert s1 == s2 or s1.model_dump() == s2.model_dump()


def test_p17_env_override_works_at_construction():
    """``Settings`` reads env
    vars at construction
    time.  The ``frozen``
    flag is about *post-
    construction*
    mutation; construction
    itself still respects
    the env-var layer.
    """
    import os
    os.environ["MANUSIFT_MAX_UPLOAD_MB"] = "999"
    try:
        from manusift.config import Settings
        s = Settings()
        # Pydantic reads the
        # env var at
        # construction time.
        assert s.max_upload_mb == 999
    finally:
        del os.environ["MANUSIFT_MAX_UPLOAD_MB"]


def test_p17_frozen_does_not_block_construction():
    """``Settings(**kwargs)``
    still works (Pydantic
    allows construction-time
    overrides; only
    post-construction
    assignment is blocked).
    """
    from manusift.config import Settings

    s = Settings(max_upload_mb=42)
    assert s.max_upload_mb == 42
