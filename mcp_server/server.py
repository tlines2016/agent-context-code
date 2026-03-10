"""FastMCP server for Claude Code integration - main entry point."""
import sys
from pathlib import Path

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

from common_utils import VERSION

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logging.getLogger("mcp").setLevel(logging.DEBUG)
logging.getLogger("fastmcp").setLevel(logging.DEBUG)

from mcp_server.code_search_server import CodeSearchServer
from mcp_server.code_search_mcp import CodeSearchMCP


def main():
    """Main entry point for the server."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Code Search MCP Server – local semantic code search for Claude Code.",
        epilog=(
            "Examples:\n"
            "  %(prog)s                    # Start with default stdio transport\n"
            "  %(prog)s --transport sse    # Start with Server-Sent Events transport\n"
            "  %(prog)s --version          # Show version and exit\n"
            "\n"
            "Register with Claude Code:\n"
            "  claude mcp add code-search --scope user -- uv run --directory <install-dir> python mcp_server/server.py\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"agent-context-code {VERSION}",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default="stdio",
        help="Transport protocol to use (default: stdio)"
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Host for HTTP transport (default: localhost)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transport (default: 8000)"
    )

    args = parser.parse_args()

    logger.info("Starting Code Search MCP Server v%s (transport=%s)", VERSION, args.transport)

    # Create and run server
    server = CodeSearchServer()
    mcp_server = CodeSearchMCP(server)
    mcp_server.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
