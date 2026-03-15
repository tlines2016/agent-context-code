"""Entry point for the agent-context-local web dashboard server.

Usage
-----
Installed package::

    agent-context-local-ui

Source checkout::

    uv run python ui_server/server.py

Options
-------
--port PORT         TCP port to listen on (default: 7432 or CODE_SEARCH_UI_PORT)
--no-browser        Skip opening the system browser automatically
--verbose / -v      Enable DEBUG-level logging
"""

import argparse
import logging
import os
import sys
import webbrowser
from pathlib import Path

# Delay before opening the browser after uvicorn starts.
# 1.5 s gives the server time to bind and accept connections on slower systems.
_BROWSER_OPEN_DELAY_S = 1.5

# Localhost addresses that are considered safe to bind to without a warning.
_LOCALHOST_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _configure_logging(verbose: bool = False) -> None:
    """Configure logging, mirroring the MCP server's approach."""
    env_level = os.environ.get("AGENT_CONTEXT_LOG_LEVEL", "").upper()
    if verbose:
        level = logging.DEBUG
    elif env_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = getattr(logging, env_level)
    else:
        level = logging.INFO  # INFO by default for the UI server (show startup messages)

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def _parse_port(value: str) -> int:
    """Argparse type that validates TCP port range (1–65535)."""
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a valid integer port number.")
    if not (1 <= port <= 65535):
        raise argparse.ArgumentTypeError(
            f"Port {port} is out of range; must be between 1 and 65535."
        )
    return port


def main() -> None:
    """Launch the FastAPI UI server with uvicorn."""
    parser = argparse.ArgumentParser(
        description="Agent Context Local — Web Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  agent-context-local-ui               # Start on default port 7432\n"
            "  agent-context-local-ui --port 8080   # Custom port\n"
            "  agent-context-local-ui --no-browser  # Skip auto-open\n"
        ),
    )
    parser.add_argument(
        "--port",
        type=_parse_port,
        default=int(os.environ.get("CODE_SEARCH_UI_PORT", "7432")),
        help="TCP port to serve on (default: 7432 or CODE_SEARCH_UI_PORT env var)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the system browser automatically on startup",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    args = parser.parse_args()

    _configure_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    # Warn when the server is bound to a non-loopback address, as that exposes
    # the local code index to other machines on the same network.
    if args.host not in _LOCALHOST_HOSTS:
        logger.warning(
            "Server is binding to %s — this exposes your local code index to "
            "other hosts on the network. Use 127.0.0.1 unless you intend this.",
            args.host,
        )

    # Add repo root to sys.path so imports work in source-checkout mode.
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Lazy-import heavy dependencies after path setup.
    try:
        import uvicorn
    except ImportError:
        logger.error(
            "uvicorn is not installed. Install it with: pip install 'uvicorn[standard]'"
        )
        sys.exit(1)

    from mcp_server.code_search_server import CodeSearchServer
    from ui_server.app import create_app

    logger.info("Initialising CodeSearchServer…")
    server = CodeSearchServer()

    logger.info("Building FastAPI application…")
    app = create_app(server)

    url = f"http://{args.host}:{args.port}"
    logger.info("Starting UI server at %s", url)
    print(f"\n  Agent Context Local — Web Dashboard\n  {url}\n")

    # Open the browser after a short delay so uvicorn has time to bind.
    if not args.no_browser:
        import threading
        def _open_browser() -> None:
            import time
            time.sleep(_BROWSER_OPEN_DELAY_S)
            webbrowser.open(url)
        threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="debug" if args.verbose else "warning",
    )


if __name__ == "__main__":
    main()
