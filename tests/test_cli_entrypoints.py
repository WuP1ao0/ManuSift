from __future__ import annotations


def test_legacy_manusift_app_entrypoint_delegates_to_main(monkeypatch) -> None:
    """Old Windows launchers imported manusift.cli:app.

    The conversational chat TUI was removed (see cli.py
    header); ``app()`` remains as the legacy entry name and
    must delegate to the argparse ``main()``.
    """
    from manusift import cli

    called = {"argv": None}

    def fake_main(argv=None) -> int:
        called["argv"] = argv
        return 0

    monkeypatch.setattr(cli, "main", fake_main)

    assert cli.app() == 0
    assert called["argv"] is None  # app() passes through argv=None


