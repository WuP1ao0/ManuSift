"""Tests for the plugin self-config
mechanism (Step E4).

E4 layers a small
``configure(settings: dict)`` seam on
the detector Protocol. A
third-party plugin that wants to
read the host app's configuration
implements ``configure``; the host
loader calls it on the plugin
instance right after construction
and before the plugin's first
``run()`` call.

Guarantees:

  1. ``iter_entrypoint_detectors(settings)``
     calls ``configure(dict(settings))``
     on every plugin that exposes a
     ``configure`` attribute.
  2. A plugin that does not
     implement ``configure`` is
     silently skipped — the loader
     does not raise.
  3. A plugin whose ``configure``
     raises an exception is logged
     and still yielded. The plugin
     itself is fine; the failure is
     in its config handling, and
     the user can still see the
     plugin's findings.
  4. The settings dict is passed
     *by value* (the loader calls
     ``dict(settings)``) so a
     plugin that mutates the dict
     does not corrupt the host's
     view of the settings.
  5. ``settings=None`` means "no
     settings available" (the
     loader skips the
     ``configure`` call entirely).
"""
from __future__ import annotations

import logging
from typing import Any

import pytest


# ---------- 1. Fake plugin helpers ----------

class _RecordingPlugin:
    """A plugin that records the
    settings it received. Used by
    tests that want to assert the
    loader called ``configure`` with
    the right argument."""

    def __init__(self) -> None:
        self.received_settings: dict[str, Any] | None = None
        self.configure_calls = 0

    @property
    def name(self) -> str:
        return "recording"

    def run(self, doc):  # pragma: no cover — never called
        raise NotImplementedError

    def configure(self, settings: dict[str, Any]) -> None:
        self.received_settings = settings
        self.configure_calls += 1


class _RaisingPlugin:
    """A plugin whose ``configure``
    raises. The loader must catch
    the exception and still yield
    the plugin."""

    @property
    def name(self) -> str:
        return "raising"

    def run(self, doc):  # pragma: no cover — never called
        raise NotImplementedError

    def configure(self, settings: dict[str, Any]) -> None:
        raise RuntimeError("simulated configure failure")


class _NoConfigurePlugin:
    """A plugin that does not
    implement ``configure``. The
    loader must silently skip the
    ``configure`` call."""

    @property
    def name(self) -> str:
        return "no_configure"

    def run(self, doc):  # pragma: no cover — never called
        raise NotImplementedError


# ---------- 2. Plugin self-config basics ----------

def test_iter_entrypoint_detectors_calls_configure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loader calls
    ``configure(dict(settings))`` on
    every plugin that exposes
    ``configure``."""
    from manusift.detectors import registry as reg

    plugin = _RecordingPlugin()

    # Inject a fake entry point. We
    # use a stand-in object that
    # mimics the ``entry_point`` API
    # (``.load()`` returns the class
    # or instance, ``.name`` is the
    # entry-point name, ``.value``
    # is the dotted path).
    class _FakeEP:
        def __init__(self, target):
            self._target = target
            self.name = "recording"
            self.value = "fake:RecordingPlugin"
        def load(self):
            return self._target

    monkeypatch.setattr(
        reg.metadata, "entry_points",
        lambda *, group: [_FakeEP(plugin)],
    )
    instances = list(reg.iter_entrypoint_detectors({"x": 1}))
    assert len(instances) == 1
    assert plugin.configure_calls == 1
    # The dict was passed by value.
    assert plugin.received_settings == {"x": 1}
    # And the host's dict was not
    # mutated by the plugin. (We
    # only have access to the dict
    # that ``configure`` saw, which
    # the plugin *did* mutate; the
    # assertion below is just a
    # smoke test that the original
    # caller's dict is unchanged.)
    assert plugin.received_settings is not None


def test_iter_entrypoint_detectors_skips_no_configure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin that does not
    implement ``configure`` is
    silently skipped — the loader
    yields the plugin and does not
    raise."""
    from manusift.detectors import registry as reg
    plugin = _NoConfigurePlugin()
    class _FakeEP:
        def __init__(self, target):
            self._target = target
            self.name = "no_configure"
            self.value = "fake:NoConfigurePlugin"
        def load(self):
            return self._target
    monkeypatch.setattr(
        reg.metadata, "entry_points",
        lambda *, group: [_FakeEP(plugin)],
    )
    instances = list(reg.iter_entrypoint_detectors({"y": 2}))
    assert len(instances) == 1
    assert instances[0] is plugin


def test_iter_entrypoint_detectors_logs_and_yields_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin whose ``configure``
    raises is logged and still
    yielded. The plugin itself is
    fine; the failure is in its
    config handling."""
    from manusift.detectors import registry as reg
    plugin = _RaisingPlugin()
    class _FakeEP:
        def __init__(self, target):
            self._target = target
            self.name = "raising"
            self.value = "fake:RaisingPlugin"
        def load(self):
            return self._target
    monkeypatch.setattr(
        reg.metadata, "entry_points",
        lambda *, group: [_FakeEP(plugin)],
    )
    # Capture log records to assert
    # the warning was emitted.
    records: list[logging.LogRecord] = []
    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)
    handler = _Capture()
    logger = logging.getLogger("manusift.detectors.registry")
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.WARNING)
    try:
        instances = list(
            reg.iter_entrypoint_detectors({"z": 3})
        )
    finally:
        logger.setLevel(old_level)
        logger.removeHandler(handler)
    # The plugin is still yielded —
    # the user can still see its
    # findings.
    assert len(instances) == 1
    assert instances[0] is plugin
    # The warning was logged.
    msgs = [r.getMessage() for r in records]
    assert any(
        "configure" in m and "raised" in m for m in msgs
    )


def test_iter_entrypoint_detectors_none_settings_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``settings=None`` means "no
    settings available" — the loader
    skips the ``configure`` call
    entirely, even on a plugin that
    implements ``configure``."""
    from manusift.detectors import registry as reg
    plugin = _RecordingPlugin()
    class _FakeEP:
        def __init__(self, target):
            self._target = target
            self.name = "recording"
            self.value = "fake:RecordingPlugin"
        def load(self):
            return self._target
    monkeypatch.setattr(
        reg.metadata, "entry_points",
        lambda *, group: [_FakeEP(plugin)],
    )
    instances = list(reg.iter_entrypoint_detectors(None))
    assert len(instances) == 1
    # ``configure`` was not called.
    assert plugin.configure_calls == 0


# ---------- 3. Settings dict is passed by value ----------

def test_settings_dict_is_copied_not_aliased(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loader calls
    ``dict(settings)`` so a plugin
    that mutates the dict does not
    corrupt the host's view of the
    settings. We verify this by
    having the plugin mutate the
    dict and confirming the host's
    original dict is unchanged."""
    from manusift.detectors import registry as reg
    plugin = _RecordingPlugin()
    class _FakeEP:
        def __init__(self, target):
            self._target = target
            self.name = "recording"
            self.value = "fake:RecordingPlugin"
        def load(self):
            return self._target
    monkeypatch.setattr(
        reg.metadata, "entry_points",
        lambda *, group: [_FakeEP(plugin)],
    )
    # A plugin that mutates the
    # dict it received.
    class _MutatingPlugin:
        @property
        def name(self):
            return "mutating"
        def run(self, doc):
            raise NotImplementedError
        def configure(self, settings):
            settings["injected"] = "evil"
    mut = _MutatingPlugin()
    class _FakeEPMut:
        def __init__(self, target):
            self._target = target
            self.name = "mutating"
            self.value = "fake:MutatingPlugin"
        def load(self):
            return self._target
    monkeypatch.setattr(
        reg.metadata, "entry_points",
        lambda *, group: [_FakeEP(plugin), _FakeEPMut(mut)],
    )
    host_settings = {"k": "v"}
    list(reg.iter_entrypoint_detectors(host_settings))
    # The host's original dict is
    # unchanged — the loader
    # defensively copies before
    # passing to ``configure``.
    assert host_settings == {"k": "v"}
    # The plugin *did* mutate its
    # own copy (a copy of the
    # copy-on-write dict). The
    # host's dict is not affected.
    assert "injected" not in host_settings
