"""Regression tests for Phases 1-4 plan changes.

Covers:
- Phase 1 — Consistency Barrier: graph sync failures prevent snapshot advance
- Phase 2 — Graph Enrichment: search results enriched with graph relationships
- Phase 3 — Deep Graph Endpoint: create_if_missing=False for cross-project lookups
- Phase 4 — Capability Honesty: (docstring-only; no runtime tests needed)

All tests are fully mocked — they do NOT require real model loading, LanceDB,
or SQLite databases.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mcp_server.code_search_server import CodeSearchServer
from search.incremental_indexer import IncrementalIndexer, IncrementalIndexResult


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_indexer_with_mocks(*, code_graph=None, has_snapshot=True):
    """Build an IncrementalIndexer wired to mock collaborators.

    Returns (inc, indexer_mock, snapshot_manager_mock, code_graph_mock).
    """
    indexer = MagicMock()
    embedder = MagicMock()
    chunker = MagicMock()
    chunker.get_indexing_config_signature.return_value = {"sig": "1"}
    chunker.is_supported.return_value = True
    chunker.chunk_file.return_value = [MagicMock(content="x")]
    snapshot_manager = MagicMock()
    snapshot_manager.has_snapshot.return_value = has_snapshot
    snapshot_manager.load_metadata.return_value = {"indexing_config": {"sig": "1"}}

    if code_graph is None:
        code_graph = MagicMock()

    inc = IncrementalIndexer(
        indexer=indexer,
        embedder=embedder,
        chunker=chunker,
        snapshot_manager=snapshot_manager,
        code_graph=code_graph,
    )
    return inc, indexer, snapshot_manager, code_graph


def _fake_search_result(
    chunk_id="c0",
    relative_path="foo.py",
    start_line=1,
    end_line=5,
    chunk_type="function",
    score=0.9,
    name="my_func",
    content_preview="def my_func(): pass",
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


def _mock_searcher_with_results(results=None):
    """Build a mock IntelligentSearcher that returns the given results list."""
    mock_s = MagicMock()
    if results is None:
        results = []
    mock_s.search.return_value = results
    mock_s.index_manager = MagicMock()
    mock_s.index_manager.get_stats.return_value = {"total_chunks": len(results)}
    return mock_s


# ===========================================================================
# 1. TestConsistencyBarrier (Phase 1)
# ===========================================================================

class TestConsistencyBarrier:
    """Phase 1 — graph sync failures must prevent snapshot advancement."""

    def test_graph_reconciliation_failure_prevents_snapshot_advance(self):
        """When resolve_cross_file_edges raises during incremental indexing,
        save_snapshot must NOT be called and the result must report
        success=False and graph_sync_ok=False.
        """
        from merkle.change_detector import FileChanges

        inc, indexer, snapshot_manager, code_graph = _make_indexer_with_mocks()
        code_graph.resolve_cross_file_edges.side_effect = RuntimeError("reconciliation boom")

        changes = FileChanges(
            added=["new.py"],
            removed=[],
            modified=[],
            unchanged=[],
        )

        with patch.object(inc, "detect_changes", return_value=(changes, MagicMock())), \
             patch.object(inc, "_remove_old_chunks", return_value=0), \
             patch.object(inc, "_add_new_chunks", return_value=3):
            result = inc.incremental_index("/project/path", project_name="proj")

        assert result.success is False
        assert result.graph_sync_ok is False
        assert result.graph_sync_error is not None
        snapshot_manager.save_snapshot.assert_not_called()

    def test_full_index_graph_file_error_prevents_snapshot_advance(self):
        """When index_file_chunks raises for at least one file during full
        indexing, the snapshot must NOT be advanced.
        """
        inc, indexer, snapshot_manager, code_graph = _make_indexer_with_mocks(
            has_snapshot=False
        )
        # index_file_chunks fails for the first file
        code_graph.index_file_chunks.side_effect = RuntimeError("graph file error")
        # resolve_cross_file_edges succeeds (but doesn't matter — per-file
        # errors already set graph_sync_ok=False)
        code_graph.resolve_cross_file_edges.return_value = 0

        # The full_index path calls MerkleDAG.build() and get_all_files().
        mock_dag = MagicMock()
        mock_dag.get_all_files.return_value = ["a.py"]

        with patch("search.incremental_indexer.MerkleDAG", return_value=mock_dag):
            result = inc._full_index("/project/path", "proj", 0.0, {"sig": "1"})

        assert result.success is False
        assert result.graph_sync_ok is False
        snapshot_manager.save_snapshot.assert_not_called()

    def test_successful_index_saves_snapshot(self):
        """Happy path: when no graph errors occur, the snapshot IS saved."""
        from merkle.change_detector import FileChanges

        inc, indexer, snapshot_manager, code_graph = _make_indexer_with_mocks()
        code_graph.resolve_cross_file_edges.return_value = 5
        code_graph.get_stats.return_value = {"total_symbols": 10, "total_edges": 5}

        changes = FileChanges(
            added=["new.py"],
            removed=[],
            modified=[],
            unchanged=[],
        )

        with patch.object(inc, "detect_changes", return_value=(changes, MagicMock())), \
             patch.object(inc, "_remove_old_chunks", return_value=0), \
             patch.object(inc, "_add_new_chunks", return_value=3):
            result = inc.incremental_index("/project/path", project_name="proj")

        assert result.success is True
        assert result.graph_sync_ok is True
        assert result.graph_sync_error is None
        snapshot_manager.save_snapshot.assert_called_once()

    def test_incremental_graph_failure_prevents_snapshot_advance(self):
        """Same as reconciliation failure test but exercises the incremental
        (not full) code path explicitly with a different error message.
        """
        from merkle.change_detector import FileChanges

        inc, indexer, snapshot_manager, code_graph = _make_indexer_with_mocks()
        code_graph.resolve_cross_file_edges.side_effect = OSError("db locked")

        changes = FileChanges(
            added=[],
            removed=[],
            modified=["mod.py"],
            unchanged=[],
        )

        with patch.object(inc, "detect_changes", return_value=(changes, MagicMock())), \
             patch.object(inc, "_remove_old_chunks", return_value=1), \
             patch.object(inc, "_add_new_chunks", return_value=2):
            result = inc.incremental_index("/project/path", project_name="proj")

        assert result.success is False
        assert result.graph_sync_ok is False
        assert "db locked" in result.graph_sync_error
        snapshot_manager.save_snapshot.assert_not_called()

    def test_embedding_failure_prevents_snapshot_advance(self):
        """Embedding failures in incremental add stage must block snapshot save."""
        from merkle.change_detector import FileChanges

        inc, indexer, snapshot_manager, code_graph = _make_indexer_with_mocks()
        # Allow graph sync stage to succeed so embedding failure is isolated.
        code_graph.resolve_cross_file_edges.return_value = 0
        inc.embedder.embed_chunks.side_effect = RuntimeError("embed failed")

        changes = FileChanges(
            added=["new.py"],
            removed=[],
            modified=[],
            unchanged=[],
        )

        with patch.object(inc, "detect_changes", return_value=(changes, MagicMock())), \
             patch.object(inc, "_remove_old_chunks", return_value=0):
            result = inc.incremental_index("/project/path", project_name="proj")

        assert result.success is False
        assert result.error is not None
        assert "Embedding failed" in result.error
        snapshot_manager.save_snapshot.assert_not_called()

    def test_graph_indexing_failure_in_add_stage_prevents_snapshot_advance(self):
        """Per-file graph indexing failures must block snapshot advancement."""
        from merkle.change_detector import FileChanges

        inc, indexer, snapshot_manager, code_graph = _make_indexer_with_mocks()
        code_graph.index_file_chunks.side_effect = RuntimeError("graph file fail")
        code_graph.resolve_cross_file_edges.return_value = 0

        changes = FileChanges(
            added=["new.py"],
            removed=[],
            modified=[],
            unchanged=[],
        )

        with patch.object(inc, "detect_changes", return_value=(changes, MagicMock())), \
             patch.object(inc, "_remove_old_chunks", return_value=0):
            result = inc.incremental_index("/project/path", project_name="proj")

        assert result.success is False
        assert result.graph_sync_ok is False
        assert "Graph sync failed" in (result.error or "")
        snapshot_manager.save_snapshot.assert_not_called()


# ===========================================================================
# 2. TestClearIndexTruthful (Phase 1)
# ===========================================================================

class TestClearIndexTruthful:
    """Phase 1 — clear_index must report truthful per-store outcomes."""

    def test_clear_index_reports_all_stores_cleared(self):
        """Happy path: all three stores cleared, success=True."""
        server = CodeSearchServer()
        server._current_project = "/active/project"

        mock_index_manager = MagicMock()
        mock_graph = MagicMock()

        with patch.object(server, "get_index_manager", return_value=mock_index_manager), \
             patch.object(server, "_graph_db_path") as mock_gpath, \
             patch("mcp_server.code_search_server.CodeGraph") as MockCG, \
             patch("merkle.snapshot_manager.SnapshotManager") as MockSM:
            mock_gpath.return_value = MagicMock(exists=MagicMock(return_value=True))
            MockCG.return_value = mock_graph

            result = json.loads(server.clear_index())

        assert result["success"] is True
        assert result["vector_cleared"] is True
        assert result["graph_cleared"] is True
        assert result["snapshot_cleared"] is True

    def test_clear_index_graph_failure_reports_partial(self):
        """When graph clear raises, success=False and graph_cleared=False."""
        server = CodeSearchServer()
        server._current_project = "/active/project"

        mock_index_manager = MagicMock()

        with patch.object(server, "get_index_manager", return_value=mock_index_manager), \
             patch.object(server, "_graph_db_path") as mock_gpath, \
             patch("mcp_server.code_search_server.CodeGraph") as MockCG, \
             patch("merkle.snapshot_manager.SnapshotManager") as MockSM:
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_gpath.return_value = mock_path
            # CodeGraph constructor itself raises
            MockCG.side_effect = RuntimeError("cannot open graph")

            result = json.loads(server.clear_index())

        assert result["success"] is False
        assert result["vector_cleared"] is True
        assert result["graph_cleared"] is False
        assert result["snapshot_cleared"] is True

    def test_clear_index_snapshot_failure_reports_partial(self):
        """When snapshot delete raises, success=False and snapshot_cleared=False."""
        server = CodeSearchServer()
        server._current_project = "/active/project"

        mock_index_manager = MagicMock()

        with patch.object(server, "get_index_manager", return_value=mock_index_manager), \
             patch.object(server, "_graph_db_path") as mock_gpath, \
             patch("mcp_server.code_search_server.CodeGraph") as MockCG, \
             patch("merkle.snapshot_manager.SnapshotManager") as MockSM:
            mock_gpath.return_value = MagicMock(exists=MagicMock(return_value=False))
            # Snapshot delete raises
            MockSM.return_value.delete_snapshot.side_effect = OSError("permission denied")

            result = json.loads(server.clear_index())

        assert result["success"] is False
        assert result["vector_cleared"] is True
        # No graph file means graph_cleared=True (nothing to clear)
        assert result["graph_cleared"] is True
        assert result["snapshot_cleared"] is False

    def test_clear_index_resets_cached_state(self):
        """After clear_index, _index_manager, _searcher, and _code_graph
        should all be None.
        """
        server = CodeSearchServer()
        server._current_project = "/active/project"
        server._index_manager = MagicMock()
        server._searcher = MagicMock()
        server._code_graph = MagicMock()
        server._code_graph_project = "/active/project"

        with patch.object(server, "get_index_manager", return_value=MagicMock()), \
             patch.object(server, "_graph_db_path") as mock_gpath, \
             patch("mcp_server.code_search_server.CodeGraph") as MockCG, \
             patch("merkle.snapshot_manager.SnapshotManager") as MockSM:
            mock_gpath.return_value = MagicMock(exists=MagicMock(return_value=False))
            server.clear_index()

        assert server._index_manager is None
        assert server._searcher is None
        # _close_cached_graph sets both to None
        assert server._code_graph is None
        assert server._code_graph_project is None

    def test_clear_index_closes_graph_handle_before_delete(self):
        """_close_cached_graph must be called BEFORE any delete operations
        so that Windows file handles are released.
        """
        server = CodeSearchServer()
        server._current_project = "/active/project"

        call_order = []

        original_close = server._close_cached_graph

        def track_close():
            call_order.append("close_graph")
            original_close()

        def track_get_index_manager(*args, **kwargs):
            call_order.append("get_index_manager")
            return MagicMock()

        with patch.object(server, "_close_cached_graph", side_effect=track_close), \
             patch.object(server, "get_index_manager", side_effect=track_get_index_manager), \
             patch.object(server, "_graph_db_path") as mock_gpath, \
             patch("mcp_server.code_search_server.CodeGraph") as MockCG, \
             patch("merkle.snapshot_manager.SnapshotManager") as MockSM:
            mock_gpath.return_value = MagicMock(exists=MagicMock(return_value=False))
            server.clear_index()

        # close_graph must appear before get_index_manager (first delete op)
        assert call_order.index("close_graph") < call_order.index("get_index_manager")


# ===========================================================================
# 3. TestCrossProjectGraphNonMutation (Phase 3)
# ===========================================================================

class TestCrossProjectGraphNonMutation:
    """Phase 3 — cross-project graph lookups must not create ghost state."""

    def test_get_graph_context_does_not_create_project_storage_when_absent(self, tmp_path):
        """Cross-project read must not create project dir/project_info when graph is absent."""
        server = CodeSearchServer()
        server._current_project = "/active/project"

        target = str(tmp_path / "other_project")
        storage_root = tmp_path / "storage"

        with patch("mcp_server.code_search_server.get_storage_dir", return_value=storage_root):
            result = json.loads(server.get_graph_context("c1", project_path=target))

        assert result["error"] == "Project graph not indexed"
        projects_dir = storage_root / "projects"
        # The read-only lookup path should not create any storage artifacts.
        assert not projects_dir.exists()

    def test_get_graph_context_returns_not_indexed_error_when_db_absent(self):
        """Cross-project lookup should return 'Project graph not indexed'
        when the graph DB file does not exist.
        """
        server = CodeSearchServer()
        server._current_project = "/active/project"

        with patch.object(server, "_open_transient_graph", return_value=None):
            result = json.loads(server.get_graph_context(
                "c1", project_path="/other/project"
            ))

        assert result["error"] == "Project graph not indexed"
        assert result["chunk_id"] == "c1"

    def test_active_project_graph_context_returns_not_indexed_when_db_absent(self):
        """Even for the active project, if the graph DB file does not exist,
        get_graph_context must return a 'not indexed' error rather than
        creating a new empty database.
        """
        server = CodeSearchServer()
        server._current_project = "/active/project"

        fake_graph_path = MagicMock()
        fake_graph_path.exists.return_value = False

        with patch.object(server, "_graph_db_path", return_value=fake_graph_path):
            result = json.loads(server.get_graph_context("c1"))

        assert result["error"] == "Project graph not indexed"
        assert result["chunk_id"] == "c1"


# ===========================================================================
# 4. TestMissingSeedSemantics (Phase 3)
# ===========================================================================

class TestMissingSeedSemantics:
    """Phase 3 — missing seed chunk returns found=False with miss_reason."""

    def test_unknown_chunk_returns_found_false(self):
        """Calling get_graph_context with a chunk_id that doesn't exist in
        the graph must return found=False and a miss_reason string.
        """
        server = CodeSearchServer()
        server._current_project = "/active/project"

        mock_graph = MagicMock()
        mock_graph.get_symbol.return_value = None  # chunk not found

        with patch.object(server, "get_code_graph", return_value=mock_graph), \
             patch.object(server, "_graph_db_path") as mock_gpath:
            mock_gpath.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = json.loads(server.get_graph_context("nonexistent_chunk"))

        assert result["found"] is False
        assert "miss_reason" in result
        assert result["chunk_id"] == "nonexistent_chunk"

    def test_known_chunk_returns_found_true(self):
        """Calling get_graph_context with a valid chunk_id must return
        found=True.
        """
        server = CodeSearchServer()
        server._current_project = "/active/project"

        mock_graph = MagicMock()
        mock_graph.get_symbol.return_value = {"chunk_id": "valid_chunk", "name": "Foo"}
        mock_graph.get_connected_subgraph.return_value = {
            "symbols": [{"chunk_id": "valid_chunk"}],
            "edges": [{"source_chunk_id": "valid_chunk", "target_chunk_id": "bar", "edge_type": "contains"}],
        }

        with patch.object(server, "get_code_graph", return_value=mock_graph), \
             patch.object(server, "_graph_db_path") as mock_gpath:
            mock_gpath.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = json.loads(server.get_graph_context("valid_chunk"))

        assert result["found"] is True
        assert result["symbol_count"] == 1
        assert result["edge_count"] == 1

    def test_known_chunk_with_no_edges_returns_found_true(self):
        """A chunk that exists in the graph but has no relationships
        must still return found=True with edge_count=0.
        """
        server = CodeSearchServer()
        server._current_project = "/active/project"

        mock_graph = MagicMock()
        mock_graph.get_symbol.return_value = {"chunk_id": "lonely_chunk", "name": "Bar"}
        mock_graph.get_connected_subgraph.return_value = {
            "symbols": [{"chunk_id": "lonely_chunk"}],
            "edges": [],
        }

        with patch.object(server, "get_code_graph", return_value=mock_graph), \
             patch.object(server, "_graph_db_path") as mock_gpath:
            mock_gpath.return_value = MagicMock(exists=MagicMock(return_value=True))
            result = json.loads(server.get_graph_context("lonely_chunk"))

        assert result["found"] is True
        assert result["edge_count"] == 0
        assert result["symbol_count"] == 1


# ===========================================================================
# 5. TestDefaultGraphEnrichment (Phase 2)
# ===========================================================================

class TestDefaultGraphEnrichment:
    """Phase 2 — search results enriched with graph relationships."""

    def _server_with_active_project(self):
        """Return a CodeSearchServer with an active project and mocked deps."""
        server = CodeSearchServer()
        server._current_project = "/some/project"
        return server

    def test_search_code_includes_graph_enriched_flag(self):
        """When the graph has relationships for search results, the response
        must include graph_enriched=True.
        """
        server = self._server_with_active_project()
        mock_searcher = _mock_searcher_with_results([_fake_search_result()])

        mock_graph = MagicMock()
        # get_relationships returns data for our chunk
        mock_graph.get_relationships.return_value = [
            {"edge_type": "contains", "source_chunk_id": "c0", "target_chunk_id": "c1"},
        ]
        server._code_graph = mock_graph

        with patch.object(server, "get_searcher", return_value=mock_searcher), \
             patch.object(server, "embedder", return_value=MagicMock()):
            result = json.loads(server.search_code("test query", auto_reindex=False))

        assert result.get("graph_enriched") is True
        assert "relationships" in result["results"][0]

    def test_search_code_no_graph_enriched_when_no_relationships(self):
        """When the graph has no relationships for search results,
        graph_enriched must NOT appear in the response.
        """
        server = self._server_with_active_project()
        mock_searcher = _mock_searcher_with_results([_fake_search_result()])

        mock_graph = MagicMock()
        # get_relationships returns empty list
        mock_graph.get_relationships.return_value = []
        server._code_graph = mock_graph

        with patch.object(server, "get_searcher", return_value=mock_searcher), \
             patch.object(server, "embedder", return_value=MagicMock()):
            result = json.loads(server.search_code("test query", auto_reindex=False))

        assert "graph_enriched" not in result

    def test_search_project_includes_graph_enrichment(self, tmp_path):
        """_search_project also enriches results when the graph exists
        for the target project.
        """
        server = self._server_with_active_project()

        target = str(tmp_path / "target_project")

        mock_searcher = MagicMock()
        mock_searcher.search.return_value = [_fake_search_result()]

        mock_index_manager = MagicMock()
        mock_index_manager.get_index_size.return_value = 100

        mock_graph = MagicMock()
        mock_graph.get_relationships.return_value = [
            {"edge_type": "inherits", "source_chunk_id": "c0", "target_chunk_id": "c2"},
        ]

        with patch.object(server, "_project_storage_dir") as mock_dir, \
             patch("mcp_server.code_search_server.CodeIndexManager", return_value=mock_index_manager), \
             patch("search.searcher.IntelligentSearcher", return_value=mock_searcher), \
             patch.object(server, "embedder", return_value=MagicMock()), \
             patch.object(server, "reranker", return_value=None), \
             patch("mcp_server.code_search_server.load_reranker_config", return_value={}), \
             patch.object(server, "_open_transient_graph", return_value=mock_graph):
            idx_dir = tmp_path / "idx" / "index"
            idx_dir.mkdir(parents=True)
            mock_dir.return_value = tmp_path / "idx"

            result = json.loads(server.search_code(
                "test query", project_path=target, auto_reindex=False,
            ))

        assert result.get("graph_enriched") is True

    def test_search_project_no_mutation_without_graph_db(self, tmp_path):
        """_search_project must NOT create a graph DB when it doesn't exist
        for the target project.
        """
        server = self._server_with_active_project()
        original_graph = server._code_graph

        target = str(tmp_path / "target_project")

        mock_searcher = MagicMock()
        mock_searcher.search.return_value = []

        mock_index_manager = MagicMock()
        mock_index_manager.get_index_size.return_value = 100

        with patch.object(server, "_project_storage_dir") as mock_dir, \
             patch("mcp_server.code_search_server.CodeIndexManager", return_value=mock_index_manager), \
             patch("search.searcher.IntelligentSearcher", return_value=mock_searcher), \
             patch.object(server, "embedder", return_value=MagicMock()), \
             patch.object(server, "reranker", return_value=None), \
             patch("mcp_server.code_search_server.load_reranker_config", return_value={}), \
             patch.object(server, "_open_transient_graph", return_value=None) as mock_open:
            idx_dir = tmp_path / "idx" / "index"
            idx_dir.mkdir(parents=True)
            mock_dir.return_value = tmp_path / "idx"

            result = json.loads(server.search_code(
                "test query", project_path=target, auto_reindex=False,
            ))

        # _open_transient_graph called with create_if_missing=False
        mock_open.assert_called_once_with(target, create_if_missing=False)
        # graph_enriched absent because no graph available
        assert "graph_enriched" not in result
        # Server state unchanged
        assert server._code_graph is original_graph


# ===========================================================================
# 6. TestSyncObservability (Phase 1)
# ===========================================================================

class TestSyncObservability:
    """Phase 1 — get_index_status includes sync observability fields."""

    def test_get_index_status_includes_sync_fields(self):
        """Response must include sync_status, vector_indexed, graph_indexed,
        and snapshot_exists keys.
        """
        server = CodeSearchServer()
        server._current_project = "/active/project"

        mock_index_manager = MagicMock()
        mock_index_manager.get_stats.return_value = {"total_chunks": 42}
        mock_embedder = MagicMock()
        mock_embedder.get_model_info.return_value = {"model": "test"}

        mock_graph = MagicMock()
        mock_graph.get_stats.return_value = {"total_symbols": 10, "total_edges": 5}
        server._code_graph = mock_graph
        server._code_graph_project = str(Path("/active/project").resolve())

        with patch.object(server, "get_index_manager", return_value=mock_index_manager), \
             patch.object(server, "embedder", return_value=mock_embedder), \
             patch.object(server, "reranker", return_value=None), \
             patch("mcp_server.code_search_server.load_reranker_config", return_value={}), \
             patch("merkle.snapshot_manager.SnapshotManager") as MockSM:
            MockSM.return_value.has_snapshot.return_value = True
            result = json.loads(server.get_index_status())

        assert "sync_status" in result
        assert "vector_indexed" in result
        assert "graph_indexed" in result
        assert "snapshot_exists" in result

        # With all stores present and populated, sync_status should be "synced"
        assert result["sync_status"] == "synced"
        assert result["vector_indexed"] is True
        assert result["graph_indexed"] is True
        assert result["snapshot_exists"] is True

    def test_get_index_status_degraded_when_no_graph(self):
        """When vector is indexed but graph is missing, sync_status must
        be 'degraded' with a relevant degraded_reason.
        """
        server = CodeSearchServer()
        server._current_project = "/active/project"

        mock_index_manager = MagicMock()
        mock_index_manager.get_stats.return_value = {"total_chunks": 42}
        mock_embedder = MagicMock()
        mock_embedder.get_model_info.return_value = {"model": "test"}

        # No cached graph and graph DB doesn't exist on disk
        server._code_graph = None
        server._code_graph_project = None
        fake_graph_path = MagicMock()
        fake_graph_path.exists.return_value = False

        with patch.object(server, "get_index_manager", return_value=mock_index_manager), \
             patch.object(server, "embedder", return_value=mock_embedder), \
             patch.object(server, "reranker", return_value=None), \
             patch("mcp_server.code_search_server.load_reranker_config", return_value={}), \
             patch.object(server, "_graph_db_path", return_value=fake_graph_path), \
             patch("merkle.snapshot_manager.SnapshotManager") as MockSM:
            MockSM.return_value.has_snapshot.return_value = True
            result = json.loads(server.get_index_status())

        assert result["sync_status"] == "degraded"
        assert result["vector_indexed"] is True
        assert result["graph_indexed"] is False
        assert "degraded_reason" in result
        assert "graph" in result["degraded_reason"]

    def test_get_index_status_includes_revision_observability(self):
        """Status response should expose vector/graph/snapshot revision details."""
        server = CodeSearchServer()
        server._current_project = "/active/project"

        mock_index_manager = MagicMock()
        mock_index_manager.get_stats.return_value = {"total_chunks": 5, "version_count": 2}
        mock_embedder = MagicMock()
        mock_embedder.get_model_info.return_value = {"model": "test"}

        mock_graph = MagicMock()
        mock_graph.get_stats.return_value = {"total_symbols": 2, "total_edges": 1}
        server._code_graph = mock_graph
        server._code_graph_project = str(Path("/active/project").resolve())

        fake_graph_path = MagicMock()
        fake_graph_path.exists.return_value = True
        fake_graph_path.stat.return_value.st_mtime = 1700000000
        fake_graph_path.__str__.return_value = "/tmp/code_graph.db"

        with patch.object(server, "get_index_manager", return_value=mock_index_manager), \
             patch.object(server, "embedder", return_value=mock_embedder), \
             patch.object(server, "reranker", return_value=None), \
             patch("mcp_server.code_search_server.load_reranker_config", return_value={}), \
             patch.object(server, "_graph_db_path", return_value=fake_graph_path), \
             patch("merkle.snapshot_manager.SnapshotManager") as MockSM:
            MockSM.return_value.has_snapshot.return_value = True
            MockSM.return_value.load_metadata.return_value = {
                "last_snapshot": "2026-01-01T00:00:00",
                "root_hash": "abc123",
                "file_count": 7,
            }
            result = json.loads(server.get_index_status())

        assert "revision_observability" in result
        ro = result["revision_observability"]
        assert ro["vector"]["version_count"] == 2
        assert ro["snapshot"]["root_hash"] == "abc123"
        assert "last_updated" in ro["graph"]


