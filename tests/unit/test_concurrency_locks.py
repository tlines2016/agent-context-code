"""Unit tests for cross-process concurrency locking.

Validates the file-lock integration in incremental_indexer and
code_search_server to prevent concurrent index corruption.
"""

import hashlib
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common_utils import get_embedding_lock_path, get_project_lock_path, get_storage_dir
from search.incremental_indexer import IncrementalIndexer, IncrementalIndexResult


# ---------------------------------------------------------------------------
# Lock path derivation
# ---------------------------------------------------------------------------


class TestLockPathDerivation:
    """Verify lock path helpers produce correct, consistent paths."""

    def test_project_lock_path_uses_storage_dir(self, tmp_path):
        with patch("common_utils.get_storage_dir", return_value=tmp_path):
            lock_path = get_project_lock_path("/some/project")
        assert lock_path.parent.parent == tmp_path / "projects"

    def test_project_lock_path_filename(self, tmp_path):
        with patch("common_utils.get_storage_dir", return_value=tmp_path):
            lock_path = get_project_lock_path("/some/project")
        assert lock_path.name == ".indexing.lock"

    def test_project_lock_path_hash_matches_server(self, tmp_path):
        """Hash derivation must mirror CodeSearchServer._project_storage_key."""
        project = "/home/user/myproject"
        resolved = str(Path(project).resolve())
        expected_name = Path(resolved).name
        expected_hash = hashlib.md5(resolved.encode()).hexdigest()[:8]

        with patch("common_utils.get_storage_dir", return_value=tmp_path):
            lock_path = get_project_lock_path(project)
        assert f"{expected_name}_{expected_hash}" in str(lock_path.parent)

    def test_project_lock_path_creates_parent_dir(self, tmp_path):
        with patch("common_utils.get_storage_dir", return_value=tmp_path):
            lock_path = get_project_lock_path("/brand/new/project")
        assert lock_path.parent.exists()

    def test_embedding_lock_path(self, tmp_path):
        with patch("common_utils.get_storage_dir", return_value=tmp_path):
            lock_path = get_embedding_lock_path()
        assert lock_path == tmp_path / ".embedding.lock"

    def test_same_project_gives_same_lock(self, tmp_path):
        with patch("common_utils.get_storage_dir", return_value=tmp_path):
            a = get_project_lock_path("/some/project")
            b = get_project_lock_path("/some/project")
        assert a == b

    def test_different_projects_give_different_locks(self, tmp_path):
        with patch("common_utils.get_storage_dir", return_value=tmp_path):
            a = get_project_lock_path("/project/alpha")
            b = get_project_lock_path("/project/beta")
        assert a != b


# ---------------------------------------------------------------------------
# IncrementalIndexer lock behaviour
# ---------------------------------------------------------------------------


def _make_indexer(**overrides) -> IncrementalIndexer:
    """Build an IncrementalIndexer with fully-mocked dependencies."""
    defaults = {
        "indexer": MagicMock(),
        "embedder": MagicMock(),
        "chunker": MagicMock(),
        "snapshot_manager": MagicMock(),
    }
    defaults.update(overrides)
    # chunker.get_indexing_config_signature returns a dict
    defaults["chunker"].get_indexing_config_signature.return_value = {}
    return IncrementalIndexer(**defaults)


class TestProjectLockTimeout:
    """Lock timeout is chosen based on whether the op is full or incremental."""

    def test_full_index_uses_zero_timeout(self, tmp_path):
        indexer = _make_indexer()
        indexer.snapshot_manager.has_snapshot.return_value = False  # full index

        with patch("search.incremental_indexer.get_project_lock_path") as mock_path, \
             patch("search.incremental_indexer.FileLock") as MockLock:
            mock_path.return_value = tmp_path / ".indexing.lock"
            mock_lock_instance = MagicMock()
            MockLock.return_value = mock_lock_instance

            indexer.incremental_index(str(tmp_path))

            MockLock.assert_called_once_with(
                tmp_path / ".indexing.lock",
                timeout=IncrementalIndexer._FULL_INDEX_LOCK_TIMEOUT,
            )

    def test_incremental_index_uses_five_second_timeout(self, tmp_path):
        indexer = _make_indexer()
        indexer.snapshot_manager.has_snapshot.return_value = True  # incremental
        # Metadata config must match the computed config (which merges
        # ignore_signature from IgnoreRules.compute_signature).
        indexer.snapshot_manager.load_metadata.return_value = {
            "indexing_config": {"ignore_signature": None}
        }

        with patch("search.incremental_indexer.get_project_lock_path") as mock_path, \
             patch("search.incremental_indexer.FileLock") as MockLock, \
             patch("search.incremental_indexer.IgnoreRules") as MockIgnore:
            mock_path.return_value = tmp_path / ".indexing.lock"
            mock_lock_instance = MagicMock()
            MockLock.return_value = mock_lock_instance
            MockIgnore.compute_signature.return_value = None

            # Set up change detection to return no changes
            indexer.change_detector = MagicMock()
            mock_dag = MagicMock()
            mock_dag.get_ignore_stats.return_value = {}
            mock_changes = MagicMock()
            mock_changes.has_changes.return_value = False
            indexer.change_detector.detect_changes_from_snapshot.return_value = (mock_changes, mock_dag)

            indexer.incremental_index(str(tmp_path))

            MockLock.assert_called_once_with(
                tmp_path / ".indexing.lock",
                timeout=IncrementalIndexer._INCREMENTAL_LOCK_TIMEOUT,
            )

    def test_explicit_lock_timeout_overrides_default(self, tmp_path):
        indexer = _make_indexer()
        indexer.snapshot_manager.has_snapshot.return_value = False  # would default to 0

        with patch("search.incremental_indexer.get_project_lock_path") as mock_path, \
             patch("search.incremental_indexer.FileLock") as MockLock:
            mock_path.return_value = tmp_path / ".indexing.lock"
            mock_lock_instance = MagicMock()
            MockLock.return_value = mock_lock_instance

            indexer.incremental_index(str(tmp_path), lock_timeout=42)

            MockLock.assert_called_once_with(
                tmp_path / ".indexing.lock",
                timeout=42,
            )


class TestLockContention:
    """When the lock cannot be acquired, return success with lock_contention."""

    def test_contention_returns_success_and_flag(self, tmp_path):
        from filelock import Timeout

        indexer = _make_indexer()
        indexer.snapshot_manager.has_snapshot.return_value = False

        with patch("search.incremental_indexer.get_project_lock_path") as mock_path, \
             patch("search.incremental_indexer.FileLock") as MockLock:
            mock_path.return_value = tmp_path / ".indexing.lock"
            mock_lock_instance = MagicMock()
            mock_lock_instance.acquire.side_effect = Timeout(str(tmp_path / ".indexing.lock"))
            MockLock.return_value = mock_lock_instance

            result = indexer.incremental_index(str(tmp_path))

        assert result.success is True
        assert result.lock_contention is True
        assert result.files_added == 0

    def test_contention_appears_in_to_dict(self, tmp_path):
        result = IncrementalIndexResult(
            files_added=0,
            files_removed=0,
            files_modified=0,
            chunks_added=0,
            chunks_removed=0,
            time_taken=0.1,
            success=True,
            lock_contention=True,
        )
        d = result.to_dict()
        assert d["lock_contention"] is True

    def test_no_contention_omits_key(self):
        result = IncrementalIndexResult(
            files_added=0,
            files_removed=0,
            files_modified=0,
            chunks_added=0,
            chunks_removed=0,
            time_taken=0.1,
            success=True,
        )
        d = result.to_dict()
        assert "lock_contention" not in d


class TestLockRelease:
    """Lock is released on both success and exception paths."""

    def test_lock_released_on_success(self, tmp_path):
        indexer = _make_indexer()
        indexer.snapshot_manager.has_snapshot.return_value = True
        indexer.snapshot_manager.load_metadata.return_value = {"indexing_config": {}}

        with patch("search.incremental_indexer.get_project_lock_path") as mock_path, \
             patch("search.incremental_indexer.FileLock") as MockLock, \
             patch("search.incremental_indexer.IgnoreRules") as MockIgnore:
            mock_path.return_value = tmp_path / ".indexing.lock"
            mock_lock_instance = MagicMock()
            MockLock.return_value = mock_lock_instance
            MockIgnore.compute_signature.return_value = None

            indexer.change_detector = MagicMock()
            mock_dag = MagicMock()
            mock_dag.get_ignore_stats.return_value = {}
            mock_changes = MagicMock()
            mock_changes.has_changes.return_value = False
            indexer.change_detector.detect_changes_from_snapshot.return_value = (mock_changes, mock_dag)

            indexer.incremental_index(str(tmp_path))

            mock_lock_instance.release.assert_called_once()

    def test_lock_released_on_exception(self, tmp_path):
        indexer = _make_indexer()
        indexer.snapshot_manager.has_snapshot.return_value = True
        indexer.snapshot_manager.load_metadata.return_value = {
            "indexing_config": {"ignore_signature": None}
        }

        with patch("search.incremental_indexer.get_project_lock_path") as mock_path, \
             patch("search.incremental_indexer.FileLock") as MockLock, \
             patch("search.incremental_indexer.IgnoreRules") as MockIgnore:
            mock_path.return_value = tmp_path / ".indexing.lock"
            mock_lock_instance = MagicMock()
            MockLock.return_value = mock_lock_instance
            MockIgnore.compute_signature.return_value = None

            # Force an exception inside the lock
            indexer.change_detector = MagicMock()
            indexer.change_detector.detect_changes_from_snapshot.side_effect = RuntimeError("boom")

            result = indexer.incremental_index(str(tmp_path))

            mock_lock_instance.release.assert_called_once()
            assert result.success is False
            assert "boom" in result.error


# ---------------------------------------------------------------------------
# search_code auto-reindex uses lock_timeout=0
# ---------------------------------------------------------------------------


class TestSearchAutoReindexLockTimeout:
    """search_code passes lock_timeout=0 so searches are never blocked."""

    def test_auto_reindex_passes_lock_timeout_zero(self, tmp_path):
        indexer = _make_indexer()
        indexer.snapshot_manager.has_snapshot.return_value = True
        indexer.snapshot_manager.get_snapshot_age.return_value = 999  # stale
        # Ensure the indexing config matches so auto-reindex doesn't bail out
        indexer.snapshot_manager.load_metadata.return_value = {"indexing_config": {}}

        with patch.object(indexer, "incremental_index") as mock_index:
            mock_index.return_value = IncrementalIndexResult(
                files_added=0, files_removed=0, files_modified=0,
                chunks_added=0, chunks_removed=0, time_taken=0, success=True,
            )
            indexer.auto_reindex_if_needed(str(tmp_path), lock_timeout=0)

            mock_index.assert_called_once()
            _, kwargs = mock_index.call_args
            assert kwargs["lock_timeout"] == 0


# ---------------------------------------------------------------------------
# Global embedding lock in index_directory
# ---------------------------------------------------------------------------


class TestGlobalEmbeddingLock:
    """Global embedding lock guards full-index calls in index_directory."""

    def _make_server(self):
        from mcp_server.code_search_server import CodeSearchServer

        server = CodeSearchServer.__new__(CodeSearchServer)
        server._index_manager = None
        server._searcher = None
        server._current_project = None
        server._code_graph = None
        server._code_graph_project = None
        server._model_preload_started = True
        return server

    def _mock_incremental_indexer(self, *, has_snapshot=False):
        mock_inc_indexer = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.lock_contention = False
        mock_result.files_added = 1
        mock_result.files_removed = 0
        mock_result.files_modified = 0
        mock_result.chunks_added = 10
        mock_result.chunks_removed = 0
        mock_result.time_taken = 1.0
        mock_result.graph_stats = {}
        mock_result.ignore_stats = {}
        mock_result.skipped_files = []
        mock_result.error = None
        mock_inc_indexer.incremental_index.return_value = mock_result
        mock_inc_indexer.get_indexing_stats.return_value = {}
        mock_inc_indexer.snapshot_manager.has_snapshot.return_value = has_snapshot
        return mock_inc_indexer

    def test_global_lock_acquired_for_full_index(self, tmp_path):
        server = self._make_server()
        mock_inc_indexer = self._mock_incremental_indexer(has_snapshot=False)
        MockIncrementalIndexerClass = MagicMock(return_value=mock_inc_indexer)

        with patch("search.incremental_indexer.IncrementalIndexer", MockIncrementalIndexerClass), \
             patch.object(server, "get_index_manager"), \
             patch.object(server, "embedder"), \
             patch.object(server, "get_code_graph"), \
             patch("mcp_server.code_search_server.MultiLanguageChunker"), \
             patch("mcp_server.code_search_server.FileLock") as MockLock, \
             patch("mcp_server.code_search_server.get_embedding_lock_path", return_value=tmp_path / ".embedding.lock"):

            mock_lock_instance = MagicMock()
            MockLock.return_value = mock_lock_instance

            test_dir = tmp_path / "test_project"
            test_dir.mkdir()

            response = server.index_directory(str(test_dir))
            result = json.loads(response)

            # Global lock was acquired and released
            MockLock.assert_called_once_with(tmp_path / ".embedding.lock", timeout=0)
            mock_lock_instance.acquire.assert_called_once()
            mock_lock_instance.release.assert_called_once()

    def test_global_lock_contention_returns_message(self, tmp_path):
        server = self._make_server()
        mock_inc_indexer = self._mock_incremental_indexer(has_snapshot=False)
        MockIncrementalIndexerClass = MagicMock(return_value=mock_inc_indexer)

        with patch("search.incremental_indexer.IncrementalIndexer", MockIncrementalIndexerClass), \
             patch.object(server, "get_index_manager"), \
             patch.object(server, "embedder"), \
             patch.object(server, "get_code_graph"), \
             patch("mcp_server.code_search_server.MultiLanguageChunker"), \
             patch("mcp_server.code_search_server.FileLock") as MockLock, \
             patch("mcp_server.code_search_server.get_embedding_lock_path", return_value=tmp_path / ".embedding.lock"):

            mock_lock_instance = MagicMock()
            mock_lock_instance.acquire.side_effect = LockTimeout(str(tmp_path / ".embedding.lock"))
            MockLock.return_value = mock_lock_instance

            test_dir = tmp_path / "test_project"
            test_dir.mkdir()

            response = server.index_directory(str(test_dir))
            result = json.loads(response)

            assert result["success"] is True
            assert result["lock_contention"] is True
            assert "retry" in result["message"].lower() or "another" in result["message"].lower()

    def test_no_global_lock_for_incremental_index(self, tmp_path):
        """When an existing snapshot exists (incremental), no global lock is taken."""
        server = self._make_server()
        mock_inc_indexer = self._mock_incremental_indexer(has_snapshot=True)
        MockIncrementalIndexerClass = MagicMock(return_value=mock_inc_indexer)

        with patch("search.incremental_indexer.IncrementalIndexer", MockIncrementalIndexerClass), \
             patch.object(server, "get_index_manager"), \
             patch.object(server, "embedder"), \
             patch.object(server, "get_code_graph"), \
             patch("mcp_server.code_search_server.MultiLanguageChunker"), \
             patch("mcp_server.code_search_server.FileLock") as MockLock, \
             patch("mcp_server.code_search_server.get_embedding_lock_path"):

            test_dir = tmp_path / "test_project"
            test_dir.mkdir()

            response = server.index_directory(str(test_dir))

            # FileLock should NOT have been called for an incremental index
            MockLock.assert_not_called()


# Import LockTimeout for the test above
from filelock import Timeout as LockTimeout
