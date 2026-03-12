"""Test MCP server project-specific storage functionality.

Phase 3: Updated to work with LanceDB-based CodeIndexManager.
"""

import json
import pytest
import numpy as np

from mcp_server.code_search_server import CodeSearchServer
from search.indexer import CodeIndexManager
from embeddings.embedder import EmbeddingResult


@pytest.mark.integration
class TestMCPProjectStorage:
    """Test suite for MCP server project-specific storage."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        self.server = CodeSearchServer()

    def test_index_test_project(self):
        """Test indexing the test project."""
        result = self.server.index_test_project()
        result_data = json.loads(result)

        assert "error" not in result_data, f"Failed to index test project: {result_data.get('error')}"
        # Successful indexing must set success=True and include demo_info
        assert result_data.get("success") is True, (
            f"index_test_project must report success=True; got: {result_data}"
        )
        assert "demo_info" in result_data, "index_test_project must return demo_info on success"
        # chunks_added is a non-negative integer (may be 0 on incremental re-runs)
        chunks_added = result_data.get("chunks_added")
        assert isinstance(chunks_added, int) and chunks_added >= 0, (
            f"chunks_added must be a non-negative integer; got {chunks_added!r}"
        )

    def test_list_projects(self):
        """Test listing projects after indexing."""
        # First index a project
        self.server.index_test_project()

        # List projects
        projects_result = self.server.list_projects()
        projects_data = json.loads(projects_result)

        assert "count" in projects_data, "Projects result should include count"
        assert projects_data.get("count", 0) >= 1, "Should have at least one project after indexing"
        assert "projects" in projects_data, "Projects result should include projects list"

        if projects_data.get("projects"):
            for project in projects_data["projects"]:
                assert "project_name" in project, "Project should have project_name"
                assert "project_hash" in project, "Project should have project_hash"

    def test_search_code_in_project(self):
        """Test searching code in the indexed project."""
        # First index a project — after this, _current_project is set
        self.server.index_test_project()

        # Search — must succeed since we just indexed
        search_result = self.server.search_code("authentication functions", k=3)
        search_data = json.loads(search_result)

        assert "error" not in search_data, (
            f"Search failed after indexing: {search_data.get('error')}"
        )
        assert "results" in search_data, "Search result must include 'results' key"
        results = search_data.get("results", [])
        assert isinstance(results, list), "Results must be a list"

        # Each result must have the required schema keys
        for result in results:
            assert "file" in result, f"Result missing 'file' key: {result}"
            assert "kind" in result, f"Result missing 'kind' key: {result}"
            assert "score" in result, f"Result missing 'score' key: {result}"
            assert "chunk_id" in result, f"Result missing 'chunk_id' key: {result}"

    def test_get_index_status(self):
        """Test retrieving index status."""
        # First index a project — after this, _current_project is set
        self.server.index_test_project()

        # Get status — must succeed since a project is now active
        status_result = self.server.get_index_status()
        status_data = json.loads(status_result)

        assert "error" not in status_data, (
            f"get_index_status failed after indexing: {status_data.get('error')}"
        )
        assert "index_statistics" in status_data, "Status must include 'index_statistics'"
        stats = status_data["index_statistics"]
        assert "total_chunks" in stats, "Statistics must include 'total_chunks'"
        assert "files_indexed" in stats, "Statistics must include 'files_indexed'"
        # Both values must be non-negative integers
        assert isinstance(stats["total_chunks"], int) and stats["total_chunks"] >= 0, (
            f"total_chunks must be a non-negative integer; got {stats['total_chunks']!r}"
        )
        assert isinstance(stats["files_indexed"], int) and stats["files_indexed"] >= 0, (
            f"files_indexed must be a non-negative integer; got {stats['files_indexed']!r}"
        )

    def test_project_isolation(self):
        """Test that projects are isolated in storage."""
        # Index test project
        result1 = self.server.index_test_project()
        result1_data = json.loads(result1)

        assert "error" not in result1_data, "First index should succeed"

        # Get projects list
        projects_result = self.server.list_projects()
        projects_data = json.loads(projects_result)

        # Should have at least one project
        assert len(projects_data.get("projects", [])) >= 1, "Should have at least one project"

        # Each project should have isolated storage
        projects = projects_data.get("projects", [])
        for project in projects:
            assert "project_hash" in project, "Project should have a hash for isolation"

    def test_switch_project_checks_lancedb_not_faiss(self, tmp_path):
        """switch_project must accept a LanceDB-indexed project.

        Before the fix, switch_project checked for code.index (FAISS) which
        would always fail after the Phase 3 LanceDB migration.

        This test is self-contained: it creates a real LanceDB table directly
        via CodeIndexManager so that the test does not depend on internet
        access, model loading, or pre-existing state in ~/.agent_code_search/.
        """
        # Use a fresh directory so the test never depends on pre-existing state.
        fake_project = tmp_path / "lancedb_switch_project"
        fake_project.mkdir()

        # Create the index storage structure that CodeSearchServer expects.
        project_dir = self.server.get_project_storage_dir(str(fake_project))
        index_dir = project_dir / "index"
        index_dir.mkdir(parents=True, exist_ok=True)

        # Populate a real LanceDB table with one dummy embedding.
        # CodeIndexManager.add_embeddings() creates the table if needed, so
        # lance_dir will have actual table files after this call.
        manager = CodeIndexManager(str(index_dir))
        dummy = EmbeddingResult(
            chunk_id="hello::1-5:function",
            embedding=np.random.RandomState(0).randn(768).astype(np.float32),
            metadata={
                "content_preview": "def hello(): pass",
                "file_path": str(fake_project / "hello.py"),
                "relative_path": "hello.py",
                "chunk_type": "function",
                "project_name": "lancedb_switch_project",
            },
        )
        manager.add_embeddings([dummy])

        # switch_project should succeed — it must check the LanceDB directory,
        # NOT the old FAISS code.index file.
        switch_result = json.loads(self.server.switch_project(str(fake_project)))
        assert "error" not in switch_result, (
            f"switch_project should not fail for a LanceDB-indexed project: "
            f"{switch_result.get('error')}"
        )
        assert switch_result.get("success") is True

    def test_cross_project_search_via_project_path(self, tmp_path):
        """search_code(project_path=...) queries another project without changing active context.

        This is the primary mechanism for an AI agent in one workspace to read
        the semantic index of a different workspace.

        Like test_switch_project_checks_lancedb_not_faiss, this test creates its
        own LanceDB data directly so it does not depend on internet access,
        model loading, or pre-existing storage state.
        """
        target_project = tmp_path / "cross_search_target"
        target_project.mkdir()

        # Build the storage path and populate a real LanceDB table.
        project_dir = self.server.get_project_storage_dir(str(target_project))
        index_dir = project_dir / "index"
        index_dir.mkdir(parents=True, exist_ok=True)

        manager = CodeIndexManager(str(index_dir))
        dummy = EmbeddingResult(
            chunk_id="auth::1-10:function",
            embedding=np.random.RandomState(42).randn(768).astype(np.float32),
            metadata={
                "content_preview": "def authenticate(user): pass",
                "file_path": str(target_project / "auth.py"),
                "relative_path": "auth.py",
                "chunk_type": "function",
                "project_name": "cross_search_target",
            },
        )
        manager.add_embeddings([dummy])

        active_before = self.server._current_project

        # Search the target project while staying in the original context.
        result = json.loads(
            self.server.search_code("authentication", k=3, project_path=str(target_project))
        )

        # KEY invariant: active project must not change — the whole point of
        # the project_path parameter is non-mutating cross-project lookup.
        assert self.server._current_project == active_before, (
            "search_code with project_path must not change the active project"
        )

        # search_code may succeed or fail depending on embedder availability in
        # this environment.  Either way, the active-project invariant holds.
        if "error" not in result:
            assert result.get("project") == str(target_project), (
                "Response must reference the queried project, not the active one"
            )
            assert isinstance(result.get("results"), list)

    def test_cross_project_search_nonexistent_path_returns_error(self):
        """search_code(project_path=...) with an unindexed path returns a clear error."""
        result = json.loads(
            self.server.search_code("anything", project_path="/nonexistent/path/to/project")
        )
        assert "error" in result, "Should return error for unindexed project path"
