"""Unit tests for workspace/mode_router.ModeRouter."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from workspace.workspace_config import WorkspaceConfig, MODE_CODING, MODE_WRITING
from workspace.mode_router import ModeRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_chunk(name: str = "func", file_path: str = "/proj/a.py"):
    """Return a lightweight mock CodeChunk."""
    chunk = MagicMock()
    chunk.name = name
    chunk.chunk_type = "function"
    chunk.file_path = file_path
    chunk.start_line = 1
    chunk.end_line = 10
    chunk.parent_name = None
    chunk.content = "def func(): pass"
    return chunk


def _make_mock_chunker(chunks=None):
    """Return a mock MultiLanguageChunker."""
    chunker = MagicMock()
    chunker.is_supported.return_value = True
    chunker.chunk_file.return_value = chunks or [_make_mock_chunk()]
    return chunker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def default_config():
    """WorkspaceConfig with built-in defaults."""
    return WorkspaceConfig()


@pytest.fixture()
def mock_chunker():
    return _make_mock_chunker()


@pytest.fixture()
def mock_graph():
    graph = MagicMock()
    graph.index_file_chunks = MagicMock()
    return graph


@pytest.fixture()
def router(mock_chunker, default_config, mock_graph):
    return ModeRouter(
        chunker=mock_chunker,
        workspace_config=default_config,
        code_graph=mock_graph,
    )


# ---------------------------------------------------------------------------
# Basic routing
# ---------------------------------------------------------------------------

class TestBasicRouting:

    def test_python_file_routes_to_coding(self, router, mock_chunker, mock_graph):
        chunks = router.route_file("/proj/main.py")
        assert len(chunks) == 1
        mock_chunker.chunk_file.assert_called_once()
        # Graph should have been populated for coding-mode files.
        mock_graph.index_file_chunks.assert_called_once()

    def test_markdown_file_routes_to_writing(self, router, mock_chunker, mock_graph):
        chunks = router.route_file("/proj/README.md")
        assert len(chunks) == 1
        mock_chunker.chunk_file.assert_called_once()
        # Graph should NOT be populated for writing-mode files.
        mock_graph.index_file_chunks.assert_not_called()

    def test_json_file_routes_to_writing(self, router, mock_chunker, mock_graph):
        router.route_file("/proj/config.json")
        mock_graph.index_file_chunks.assert_not_called()

    def test_unsupported_file_returns_empty(self, router, mock_chunker):
        mock_chunker.is_supported.return_value = False
        chunks = router.route_file("/proj/file.unknown")
        assert chunks == []


# ---------------------------------------------------------------------------
# Routing without a graph
# ---------------------------------------------------------------------------

class TestRoutingWithoutGraph:

    def test_coding_without_graph_still_chunks(self, mock_chunker, default_config):
        router = ModeRouter(chunker=mock_chunker, workspace_config=default_config, code_graph=None)
        chunks = router.route_file("/proj/main.py")
        assert len(chunks) == 1
        mock_chunker.chunk_file.assert_called_once()


# ---------------------------------------------------------------------------
# Batch routing
# ---------------------------------------------------------------------------

class TestBatchRouting:

    def test_route_files(self, router, mock_chunker):
        files = ["/proj/a.py", "/proj/README.md", "/proj/b.go"]
        chunks = router.route_files(files)
        assert len(chunks) == 3
        assert mock_chunker.chunk_file.call_count == 3

    def test_route_files_handles_errors(self, router, mock_chunker):
        mock_chunker.chunk_file.side_effect = [RuntimeError("boom"), [_make_mock_chunk()]]
        mock_chunker.is_supported.return_value = True
        chunks = router.route_files(["/proj/bad.py", "/proj/good.py"])
        # Only the successful file should contribute chunks.
        assert len(chunks) == 1


# ---------------------------------------------------------------------------
# Stats tracking
# ---------------------------------------------------------------------------

class TestStatsTracking:

    def test_stats_count_coding_and_writing(self, router):
        router.route_file("/proj/main.py")
        router.route_file("/proj/README.md")
        router.route_file("/proj/app.js")
        stats = router.get_routing_stats()
        assert stats["coding_files_processed"] == 2
        assert stats["writing_files_processed"] == 1

    def test_reset_stats(self, router):
        router.route_file("/proj/main.py")
        router.reset_stats()
        stats = router.get_routing_stats()
        assert stats["coding_files_processed"] == 0
        assert stats["writing_files_processed"] == 0


# ---------------------------------------------------------------------------
# Graph error resilience
# ---------------------------------------------------------------------------

class TestGraphResilience:

    def test_graph_failure_does_not_block_chunking(self, mock_chunker, default_config):
        broken_graph = MagicMock()
        broken_graph.index_file_chunks.side_effect = RuntimeError("DB locked")
        router = ModeRouter(
            chunker=mock_chunker,
            workspace_config=default_config,
            code_graph=broken_graph,
        )
        # Should still return chunks even though graph failed.
        chunks = router.route_file("/proj/main.py")
        assert len(chunks) == 1


# ---------------------------------------------------------------------------
# Custom workspace config overrides
# ---------------------------------------------------------------------------

class TestCustomConfig:

    def test_md_forced_to_coding(self, mock_chunker, mock_graph):
        config = WorkspaceConfig({
            "workspace_mode": {"extension_overrides": {".md": "coding"}}
        })
        router = ModeRouter(chunker=mock_chunker, workspace_config=config, code_graph=mock_graph)
        router.route_file("/proj/README.md")
        # Since .md was overridden to coding, graph should be populated.
        mock_graph.index_file_chunks.assert_called_once()

    def test_py_forced_to_writing(self, mock_chunker, mock_graph):
        config = WorkspaceConfig({
            "workspace_mode": {"extension_overrides": {".py": "writing"}}
        })
        router = ModeRouter(chunker=mock_chunker, workspace_config=config, code_graph=mock_graph)
        router.route_file("/proj/main.py")
        # Since .py was overridden to writing, graph should NOT be populated.
        mock_graph.index_file_chunks.assert_not_called()
