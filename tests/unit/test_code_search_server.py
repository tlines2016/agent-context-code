"""Unit tests for mcp_server/code_search_server.CodeSearchServer.

Tests focus on:
- Input validation (empty query, out-of-range k, bad paths)
- Stable JSON error/success schema
- Cross-project non-mutation: providing project_path= must not change
  _current_project, _index_manager, or _searcher on the server instance.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mcp_server.code_search_server import CodeSearchServer


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def server():
    """Return a bare CodeSearchServer with no active project."""
    return CodeSearchServer()


def _mock_searcher_with_results(results: list | None = None):
    """Build a mock IntelligentSearcher that returns the given results list."""
    from search.searcher import SearchResult
    mock_s = MagicMock()
    if results is None:
        results = []
    mock_s.search.return_value = results
    mock_s.index_manager = MagicMock()
    mock_s.index_manager.get_stats.return_value = {"total_chunks": len(results)}
    return mock_s


def _fake_search_result(
    chunk_id: str = "c0",
    relative_path: str = "foo.py",
    start_line: int = 1,
    end_line: int = 5,
    chunk_type: str = "function",
    score: float = 0.9,
    name: str = "my_func",
    content_preview: str = "def my_func(): pass",
):
    from search.searcher import SearchResult
    return SearchResult(
        chunk_id=chunk_id,
        similarity_score=score,
        content_preview=content_preview,
        file_path=f"/proj/{relative_path}",
        relative_path=relative_path,
        folder_structure=["proj"],
        chunk_type=chunk_type,
        name=name,
        parent_name=None,
        start_line=start_line,
        end_line=end_line,
        docstring=None,
        tags=[],
        context_info={},
    )


# ---------------------------------------------------------------------------
# Input validation — query
# ---------------------------------------------------------------------------

class TestQueryValidation:
    def test_empty_query_returns_error_json(self, server):
        result = json.loads(server.search_code(""))
        assert "error" in result

    def test_whitespace_only_query_returns_error_json(self, server):
        result = json.loads(server.search_code("   "))
        assert "error" in result

    def test_error_json_has_suggestion_key(self, server):
        result = json.loads(server.search_code(""))
        assert "suggestion" in result

    def test_valid_query_does_not_return_query_validation_error(self, server):
        # Patch get_searcher so we do not trigger real indexing
        mock_searcher = _mock_searcher_with_results()
        with patch.object(server, "get_searcher", return_value=mock_searcher), \
             patch.object(server, "embedder", return_value=MagicMock()):
            server._current_project = "/some/project"
            result = json.loads(server.search_code("authentication logic", auto_reindex=False))
        # A missing-index condition would produce an error, but not a query-validation error
        assert result.get("error") != "Search query must not be empty."


# ---------------------------------------------------------------------------
# Input validation — k
# ---------------------------------------------------------------------------

class TestKValidation:
    def test_k_zero_returns_error(self, server):
        result = json.loads(server.search_code("auth", k=0))
        assert "error" in result

    def test_k_negative_returns_error(self, server):
        result = json.loads(server.search_code("auth", k=-5))
        assert "error" in result

    def test_k_above_100_returns_error(self, server):
        result = json.loads(server.search_code("auth", k=101))
        assert "error" in result

    def test_k_100_is_valid(self, server):
        """k=100 is the maximum allowed value; it should not trigger a validation error."""
        mock_searcher = _mock_searcher_with_results()
        with patch.object(server, "get_searcher", return_value=mock_searcher), \
             patch.object(server, "embedder", return_value=MagicMock()):
            server._current_project = "/some/project"
            result = json.loads(server.search_code("auth", k=100, auto_reindex=False))
        # Should not be a k-validation error
        error = result.get("error", "")
        assert "k must be between" not in error

    def test_k_1_is_valid(self, server):
        mock_searcher = _mock_searcher_with_results()
        with patch.object(server, "get_searcher", return_value=mock_searcher), \
             patch.object(server, "embedder", return_value=MagicMock()):
            server._current_project = "/some/project"
            result = json.loads(server.search_code("auth", k=1, auto_reindex=False))
        error = result.get("error", "")
        assert "k must be between" not in error


# ---------------------------------------------------------------------------
# JSON schema — error responses
# ---------------------------------------------------------------------------

class TestErrorSchema:
    def test_empty_query_error_schema(self, server):
        result = json.loads(server.search_code(""))
        assert isinstance(result["error"], str)
        assert len(result["error"]) > 0

    def test_k_out_of_range_error_schema(self, server):
        result = json.loads(server.search_code("auth", k=0))
        assert isinstance(result["error"], str)

    def test_index_directory_nonexistent_path_returns_error(self, server):
        result = json.loads(server.index_directory("/this/path/does/not/exist_xyz_12345"))
        assert "error" in result

    def test_index_directory_file_path_returns_error(self, tmp_path):
        """Providing a file path instead of a directory must return an error."""
        f = tmp_path / "somefile.txt"
        f.write_text("content")
        server = CodeSearchServer()
        result = json.loads(server.index_directory(str(f)))
        assert "error" in result

    def test_switch_project_nonexistent_path_returns_error(self, server):
        result = json.loads(server.switch_project("/no/such/path_xyz_12345"))
        assert "error" in result


# ---------------------------------------------------------------------------
# JSON schema — success responses
# ---------------------------------------------------------------------------

class TestSuccessSchema:
    def test_search_code_returns_query_and_results_keys(self, server):
        mock_searcher = _mock_searcher_with_results([_fake_search_result()])
        with patch.object(server, "get_searcher", return_value=mock_searcher), \
             patch.object(server, "embedder", return_value=MagicMock()):
            server._current_project = "/some/project"
            result = json.loads(server.search_code("auth", auto_reindex=False))
        assert "query" in result
        assert "results" in result

    def test_search_code_results_is_list(self, server):
        mock_searcher = _mock_searcher_with_results([_fake_search_result()])
        with patch.object(server, "get_searcher", return_value=mock_searcher), \
             patch.object(server, "embedder", return_value=MagicMock()):
            server._current_project = "/some/project"
            result = json.loads(server.search_code("auth", auto_reindex=False))
        assert isinstance(result["results"], list)

    def test_search_result_item_has_required_keys(self, server):
        mock_searcher = _mock_searcher_with_results([_fake_search_result()])
        with patch.object(server, "get_searcher", return_value=mock_searcher), \
             patch.object(server, "embedder", return_value=MagicMock()):
            server._current_project = "/some/project"
            result = json.loads(server.search_code("auth", auto_reindex=False))
        if result.get("results"):
            item = result["results"][0]
            assert "file" in item
            assert "lines" in item
            assert "kind" in item
            assert "score" in item
            assert "chunk_id" in item

    def test_list_projects_returns_projects_key(self, tmp_path, server):
        with patch("mcp_server.code_search_server.get_storage_dir", return_value=tmp_path):
            result = json.loads(server.list_projects())
        assert "projects" in result
        assert "count" in result


# ---------------------------------------------------------------------------
# _make_snippet
# ---------------------------------------------------------------------------

class TestMakeSnippet:
    def test_empty_preview_returns_empty_string(self):
        assert CodeSearchServer._make_snippet("") == ""

    def test_none_preview_returns_empty_string(self):
        assert CodeSearchServer._make_snippet(None) == ""

    def test_whitespace_only_returns_empty_string(self):
        assert CodeSearchServer._make_snippet("   \n   ") == ""

    def test_single_line_returned_as_is(self):
        result = CodeSearchServer._make_snippet("def foo(): pass")
        assert result == "def foo(): pass"

    def test_multi_line_returns_first_nonblank(self):
        result = CodeSearchServer._make_snippet("\n\ndef foo(): pass\nmore code")
        assert result == "def foo(): pass"

    def test_long_line_truncated_to_160(self):
        long_line = "x" * 200
        result = CodeSearchServer._make_snippet(long_line)
        assert len(result) <= 160


# ---------------------------------------------------------------------------
# Cross-project non-mutation invariant
# ---------------------------------------------------------------------------

class TestCrossProjectNonMutation:
    """When project_path= is provided, _current_project/_index_manager/_searcher
    must remain unchanged on the CodeSearchServer instance."""

    def test_search_with_project_path_does_not_change_current_project(self, tmp_path):
        server = CodeSearchServer()
        original_project = "/original/project"
        original_im = MagicMock()
        original_searcher = MagicMock()
        server._current_project = original_project
        server._index_manager = original_im
        server._searcher = original_searcher

        # Target project directory that exists but has no index
        target = tmp_path / "other_project"
        target.mkdir()

        with patch.object(server, "get_project_storage_dir") as mock_dir, \
             patch("mcp_server.code_search_server.CodeIndexManager") as MockIM, \
             patch.object(server, "embedder", return_value=MagicMock()), \
             patch.object(server, "reranker", return_value=None):
            target_index_dir = tmp_path / "other_project_idx"
            target_index_dir.mkdir()
            mock_dir.return_value = target_index_dir
            # Make the transient index manager report size 0 → "not indexed" error path
            mock_im_instance = MagicMock()
            mock_im_instance.get_index_size.return_value = 0
            MockIM.return_value = mock_im_instance

            server.search_code("query", project_path=str(target))

        # All three active-state attributes must be unchanged
        assert server._current_project == original_project
        assert server._index_manager is original_im
        assert server._searcher is original_searcher

    def test_search_with_project_path_does_not_replace_index_manager(self, tmp_path):
        server = CodeSearchServer()
        original_im = MagicMock()
        server._current_project = "/original/project"
        server._index_manager = original_im

        target = tmp_path / "other"
        target.mkdir()

        with patch.object(server, "get_project_storage_dir") as mock_dir, \
             patch("mcp_server.code_search_server.CodeIndexManager") as MockIM, \
             patch.object(server, "embedder", return_value=MagicMock()), \
             patch.object(server, "reranker", return_value=None):
            idx_dir = tmp_path / "idx"
            idx_dir.mkdir()
            mock_dir.return_value = idx_dir
            mock_im_instance = MagicMock()
            mock_im_instance.get_index_size.return_value = 0
            MockIM.return_value = mock_im_instance

            server.search_code("query", project_path=str(target))

        assert server._index_manager is original_im

    def test_search_with_project_path_returns_project_error_when_not_indexed(self, tmp_path):
        """An un-indexed project path must return a descriptive error JSON."""
        server = CodeSearchServer()
        server._current_project = None

        target = tmp_path / "unindexed_proj"
        target.mkdir()

        with patch.object(server, "get_project_storage_dir") as mock_dir, \
             patch("mcp_server.code_search_server.CodeIndexManager") as MockIM, \
             patch.object(server, "embedder", return_value=MagicMock()), \
             patch.object(server, "reranker", return_value=None):
            idx_dir = tmp_path / "idx"
            idx_dir.mkdir()
            mock_dir.return_value = idx_dir
            mock_im_instance = MagicMock()
            mock_im_instance.get_index_size.return_value = 0
            MockIM.return_value = mock_im_instance

            raw = server.search_code("query", project_path=str(target))

        result = json.loads(raw)
        assert "error" in result


# ---------------------------------------------------------------------------
# get_graph_context
# ---------------------------------------------------------------------------

class TestGetGraphContext:
    def test_get_graph_context_requires_active_or_target_project(self, server):
        result = json.loads(server.get_graph_context("c1"))
        assert "error" in result

    def test_get_graph_context_rejects_negative_depth(self, server):
        server._current_project = "/some/project"
        result = json.loads(server.get_graph_context("c1", max_depth=-1))
        assert "error" in result
        assert "max_depth must be >= 0" in result["error"]

    def test_get_graph_context_rejects_non_integer_depth(self, server):
        server._current_project = "/some/project"
        result = json.loads(server.get_graph_context("c1", max_depth="2"))
        assert "error" in result
        assert "max_depth must be a non-negative integer" in result["error"]

    def test_get_graph_context_rejects_boolean_depth(self, server):
        server._current_project = "/some/project"
        result = json.loads(server.get_graph_context("c1", max_depth=True))
        assert "error" in result
        assert "max_depth must be a non-negative integer" in result["error"]

    def test_get_graph_context_response_counts_match_payload(self, server):
        server._current_project = "/some/project"
        mock_graph = MagicMock()
        mock_graph.get_symbol.return_value = {"chunk_id": "a", "name": "A"}
        mock_graph.get_connected_subgraph.return_value = {
            "symbols": [{"chunk_id": "a"}, {"chunk_id": "b"}],
            "edges": [{"source_chunk_id": "a", "target_chunk_id": "b", "edge_type": "contains"}],
        }
        with patch.object(server, "get_code_graph", return_value=mock_graph), \
             patch.object(server, "_graph_db_path") as mock_gpath:
            mock_gpath.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = json.loads(server.get_graph_context("a", max_depth=2))
        assert result["found"] is True
        assert result["symbol_count"] == len(result["symbols"])
        assert result["edge_count"] == len(result["edges"])

    def test_get_graph_context_with_project_path_does_not_mutate_active_state(self, server, tmp_path):
        original_project = "/original/project"
        original_im = MagicMock()
        original_searcher = MagicMock()
        server._current_project = original_project
        server._index_manager = original_im
        server._searcher = original_searcher

        target_project = str(tmp_path / "other_project")
        mock_graph = MagicMock()
        mock_graph.get_symbol.return_value = {"chunk_id": "chunk_1", "name": "Foo"}
        mock_graph.get_connected_subgraph.return_value = {"symbols": [], "edges": []}

        with patch.object(server, "_open_transient_graph", return_value=mock_graph) as open_graph:
            result = json.loads(server.get_graph_context("chunk_1", project_path=target_project))

        assert "error" not in result
        assert result["found"] is True
        assert server._current_project == original_project
        assert server._index_manager is original_im
        assert server._searcher is original_searcher
        open_graph.assert_called_once()
        mock_graph.close.assert_called_once()


# ---------------------------------------------------------------------------
# clear_index
# ---------------------------------------------------------------------------

class TestClearIndex:
    def test_clear_index_always_clears_graph_and_snapshot(self, server):
        server._current_project = "/active/project"
        mock_index_manager = MagicMock()
        mock_graph = MagicMock()

        with patch.object(server, "get_index_manager", return_value=mock_index_manager), \
             patch.object(server, "_graph_db_path") as mock_gpath, \
             patch("mcp_server.code_search_server.CodeGraph", return_value=mock_graph), \
             patch("merkle.snapshot_manager.SnapshotManager") as SnapshotManagerMock:
            mock_gpath.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = json.loads(server.clear_index())

        assert result["success"] is True
        assert result["vector_cleared"] is True
        assert result["graph_cleared"] is True
        assert result["snapshot_cleared"] is True
        mock_index_manager.clear_index.assert_called_once()
        mock_graph.clear.assert_called_once()
        SnapshotManagerMock.return_value.delete_snapshot.assert_called_once_with("/active/project")


# ---------------------------------------------------------------------------
# get_index_status
# ---------------------------------------------------------------------------

class TestGetIndexStatus:
    def test_status_does_not_create_graph_db_when_missing(self, server, tmp_path):
        server._current_project = "/active/project"
        mock_index_manager = MagicMock()
        mock_index_manager.get_stats.return_value = {"total_chunks": 0}
        mock_embedder = MagicMock()
        mock_embedder.get_model_info.return_value = {"model": "test"}
        missing_graph_path = tmp_path / "index" / "code_graph.db"

        with patch.object(server, "get_index_manager", return_value=mock_index_manager), \
             patch.object(server, "embedder", return_value=mock_embedder), \
             patch.object(server, "reranker", return_value=None), \
             patch.object(server, "_graph_db_path", return_value=missing_graph_path), \
             patch("mcp_server.code_search_server.CodeGraph") as code_graph_cls:
            result = json.loads(server.get_index_status())

        assert "error" not in result
        assert "graph_statistics" not in result
        code_graph_cls.assert_not_called()
