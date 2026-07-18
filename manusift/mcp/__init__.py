"""MCP surface for ManuSift Domain Kernel tools.

Exposes detectors / inspection / ingest helpers as an MCP server so
external agents (Cursor, Claude Desktop, other runtimes) can call the
same local tools without embedding ManuSift's agent loop.
"""
from __future__ import annotations

__all__ = ["build_server", "main"]


def build_server(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    from .server import build_server as _build

    return _build(*args, **kwargs)


def main() -> None:
    from .server import main as _main

    _main()
