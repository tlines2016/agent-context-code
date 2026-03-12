"""Tests for MCP tool descriptions and their lengths.

Phase 3: Updated to work with LanceDB-based CodeIndexManager.
"""

from mcp_server.code_search_server import CodeSearchServer
from mcp_server.code_search_mcp import CodeSearchMCP

MAX_TOOL_DESCRIPTION_LENGTH = 2000


class TestMCPToolDescriptions:
    """Test descriptions for all MCP tools."""

    def setup_method(self):
        """Setup test by getting tools from MCP."""
        server = CodeSearchServer()
        mcp = CodeSearchMCP(server)
        self.tools = mcp._tool_manager._tools

    def _assert_description_length(self, tool_name):
        """Get tool description length."""
        tool = self.tools.get(tool_name)
        desc_len = len(tool.description.strip())
        assert desc_len > 0, f"Tool '{tool_name}' has no description"
        # Keep a generous upper bound so rich guidance in strings.yaml is allowed
        # while still catching accidental runaway description growth.
        assert desc_len < MAX_TOOL_DESCRIPTION_LENGTH, (
            f"Tool '{tool_name}' description too long: {desc_len} chars"
        )

    def test_search_code_description(self):
        """Test search_code tool has description."""
        self._assert_description_length('search_code')
       
    def test_index_directory_description(self):
        """Test index_directory tool has description."""
        self._assert_description_length('index_directory')
       
    def test_find_similar_code_description(self):
        """Test find_similar_code tool has description."""
        self._assert_description_length('find_similar_code')
       
    def test_get_index_status_description(self):
        """Test get_index_status tool has description."""
        self._assert_description_length('get_index_status')
        
    def test_list_projects_description(self):
        """Test list_projects tool has description."""
        self._assert_description_length('list_projects')
        
    def test_switch_project_description(self):
        """Test switch_project tool has description."""
        self._assert_description_length('switch_project')
        
    def test_index_test_project_description(self):
        """Test index_test_project tool has description."""
        self._assert_description_length('index_test_project')

    def test_clear_index_description(self):
        """Test clear_index tool has description."""
        self._assert_description_length('clear_index')
