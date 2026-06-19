from __future__ import annotations


def test_legacy_manusift_app_entrypoint_launches_chat_tui(monkeypatch) -> None:
    """Old Windows launchers imported manusift.cli:app."""
    from manusift import cli

    called = {"ran": False}

    def fake_chat_main() -> None:
        called["ran"] = True

    monkeypatch.setattr(cli, "_run_chat_tui", fake_chat_main)

    assert cli.app() == 0
    assert called["ran"]

