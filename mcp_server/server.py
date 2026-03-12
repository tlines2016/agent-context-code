"""FastMCP server for AI coding assistant integration - main entry point."""
import logging
import os

try:
    from common_utils import VERSION, is_installed_package, detect_gpu_index_url  # works when installed as package
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common_utils import VERSION, is_installed_package, detect_gpu_index_url

from mcp_server.code_search_server import CodeSearchServer
from mcp_server.code_search_mcp import CodeSearchMCP


def _check_gpu_hint() -> None:
    """Log a hint if GPU hardware is detected but torch is CPU-only.

    This helps users who cloned the repo directly without running install
    scripts or gpu-setup.
    """
    try:
        import torch
    except ImportError:
        return

    if torch.cuda.is_available():
        return  # GPU torch already working

    # Check if GPU hardware exists but torch can't use it
    vendor, _ver, _name, index_url = detect_gpu_index_url()
    if not index_url:
        return  # No GPU or MPS (no action needed)

    logger = logging.getLogger(__name__)
    logger.warning(
        "GPU detected (%s) but PyTorch is CPU-only (torch %s). "
        "Server running without GPU acceleration. "
        "Fix: re-run the install script or 'gpu-setup' CLI command.",
        vendor,
        getattr(__import__("torch"), "__version__", "?"),
    )


def _configure_logging(verbose: bool = False) -> None:
    """Set up logging with sensible defaults.

    Default level is WARNING.  Override via ``AGENT_CONTEXT_LOG_LEVEL`` env
    var (DEBUG, INFO, WARNING, ERROR) or the ``--verbose`` / ``-v`` CLI flag.
    """
    env_level = os.environ.get("AGENT_CONTEXT_LOG_LEVEL", "").upper()
    if verbose:
        level = logging.DEBUG
    elif env_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = getattr(logging, env_level)
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger("mcp").setLevel(level)
    logging.getLogger("fastmcp").setLevel(level)


def main():
    """Main entry point for the server."""
    import argparse

    # Build epilog dynamically based on install mode
    if is_installed_package():
        mcp_cmd = "agent-context-local-mcp"
        register_example = (
            "Register with your MCP client (example for Claude Code):\n"
            "  claude mcp add code-search --scope user -- agent-context-local-mcp\n"
        )
    else:
        mcp_cmd = "uv run --directory <install-dir> python mcp_server/server.py"
        register_example = (
            "Register with your MCP client (example for Claude Code):\n"
            f"  claude mcp add code-search --scope user -- {mcp_cmd}\n"
        )

    parser = argparse.ArgumentParser(
        description="Code Search MCP Server – local semantic code search for AI coding assistants.",
        epilog=(
            "Examples:\n"
            f"  {mcp_cmd}                    # Start with default stdio transport\n"
            f"  {mcp_cmd} --transport sse    # Start with Server-Sent Events transport\n"
            f"  {mcp_cmd} --version          # Show version and exit\n"
            "\n"
            f"{register_example}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"agent-context-local {VERSION}",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default="stdio",
        help="Transport protocol to use (default: stdio)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging (overrides AGENT_CONTEXT_LOG_LEVEL)"
    )
    args = parser.parse_args()

    _configure_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    # Log hint if GPU hardware exists but torch is CPU-only
    try:
        _check_gpu_hint()
    except Exception:
        pass  # Non-critical — don't block server startup

    logger.info("Starting Code Search MCP Server v%s (transport=%s)", VERSION, args.transport)

    # Create and run server
    server = CodeSearchServer()
    mcp_server = CodeSearchMCP(server)
    mcp_server.run(transport=args.transport)


if __name__ == "__main__":
    main()
