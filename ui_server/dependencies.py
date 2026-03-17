"""FastAPI dependency injection helpers for the UI server.

The ``CodeSearchServer`` instance is created once at startup and shared across
all requests via a module-level singleton.  This mirrors the pattern used by
the MCP server, where a single server instance is kept alive for the lifetime
of the process.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Module-level singleton — set by app.py at startup via set_server().
_server_instance: Optional[object] = None


def set_server(server: object) -> None:
    """Register the shared CodeSearchServer instance."""
    global _server_instance
    _server_instance = server


def get_server():
    """FastAPI dependency: yield the shared CodeSearchServer.

    Raises RuntimeError when the server has not been initialised yet
    (this should never happen in normal usage because app.py calls
    set_server() before the first request).
    """
    if _server_instance is None:
        raise RuntimeError(
            "CodeSearchServer has not been initialised. "
            "Call ui_server.dependencies.set_server() before serving requests."
        )
    return _server_instance
