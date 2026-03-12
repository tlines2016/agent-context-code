"""Code Search MCP - FastMCP server for tool registration and management."""

import json
import logging
from importlib import resources as _importlib_resources
from pathlib import Path

from mcp.server.fastmcp import FastMCP
import yaml
from mcp_server.code_search_server import CodeSearchServer

# Configure logging
logger = logging.getLogger(__name__)


class CodeSearchMCP(FastMCP if FastMCP else object):
    """MCP server that manages FastMCP instance and tool registration."""

    def __init__(self, server: "CodeSearchServer"):
        """Initialize the MCP server with a code search server instance."""
        super().__init__("Code Search")
        self.server = server
        self._strings = self._load_strings()
        self._setup()

    def _load_strings(self) -> dict:
        """Load all strings (tool descriptions and help text) from strings.yaml file."""
        data = None
        # Prefer importlib.resources for installed-package compatibility
        try:
            ref = _importlib_resources.files("mcp_server").joinpath("strings.yaml")
            data = yaml.safe_load(ref.read_text(encoding="utf-8"))
        except Exception:
            pass

        # Filesystem fallback for source checkouts
        if data is None:
            strings_file = Path(__file__).parent / "strings.yaml"
            with open(strings_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

        if not isinstance(data, dict):
            logger.error(
                "strings.yaml did not parse to a dict (got %s) — "
                "tool descriptions will be empty",
                type(data).__name__,
            )
            return {"tools": {}, "help": ""}

        return {
            "tools": data.get("tools", {}),
            "help": data.get("help", ""),
        }

    def _setup(self):
        """Setup all MCP tools, resources, and prompts."""

        # Register tools using getattr
        for tool_name, description in self._strings["tools"].items():
            try:
                server_method = getattr(self.server, tool_name)
            except AttributeError:
                logger.warning(
                    "Tool '%s' defined in strings.yaml but not found on "
                    "CodeSearchServer — skipping",
                    tool_name,
                )
                continue
            self.tool(description=description)(server_method)

        # Register resources
        @self.resource("search://stats")
        def get_search_statistics() -> str:
            """Get detailed search index statistics."""
            try:
                index_manager = self.server.get_index_manager()
                stats = index_manager.get_stats()
                return json.dumps(stats, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Failed to get statistics: {str(e)}"})

        # Register prompts
        @self.prompt()
        def search_help() -> str:
            """Get help on using code search tools."""
            return self._strings["help"]

    def run(self, transport: str = "stdio"):
        """Run the MCP server with specified transport."""
        if transport == "http":
            transport = "sse"
        return super().run(transport=transport)
