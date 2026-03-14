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
        type=int,
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
            # 1.5 s gives uvicorn time to bind and accept connections on slower systems.
            time.sleep(1.5)
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
