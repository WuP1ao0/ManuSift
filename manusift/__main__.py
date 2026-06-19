"""Console-script wrapper for the `manusift` command (R-2026-06-12).

The previous entry point
(`manusift.cli:main`)
ran a one-shot PDF
analyzer, but the
user-facing command
should launch the
**chat TUI** (the
conversational
review interface at
``manusift/tui/chat_app.py``)
so the user gets the
review experience
immediately on
``manusift``.

The legacy entry points
are still available as
``manusift-workspace``
(``manusift/tui/app.py``,
the workspace browser)
and ``manusift-analyze``
(``manusift/cli.py``, the
one-shot PDF analyzer).
"""
from manusift.tui.chat_app import main


if __name__ == "__main__":
    main()
