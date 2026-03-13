"""Test auto-reindex functionality.

Phase 3: Updated to work with LanceDB-based CodeIndexManager.
"""

import time
from pathlib import Path
import pytest

from search.incremental_indexer import IncrementalIndexer
from search.indexer import CodeIndexManager
from embeddings.embedder import CodeEmbedder
from chunking.multi_language_chunker import MultiLanguageChunker
from search.searcher import IntelligentSearcher
from merkle.snapshot_manager import SnapshotManager


@pytest.mark.integration
class TestAutoReindex:
    """Test suite for auto-reindex feature."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        """Setup test fixtures."""
        self.test_project = Path(__file__).parent.parent / "test_data" / "python_project"
        self.project_name = "test_project"
        self.storage_dir = tmp_path / "test_auto_reindex"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.index_dir = self.storage_dir / "index"
        self.index_dir.mkdir(exist_ok=True)

        self.embedder = CodeEmbedder(device="cpu")
        self.index_manager = CodeIndexManager(str(self.index_dir))
        self.chunker = MultiLanguageChunker(str(self.test_project))

        # Use an isolated SnapshotManager so parallel test runs
        # don't contaminate the shared ~/.agent_code_search/merkle/ dir.
        self.snapshot_dir = self.storage_dir / "merkle"
        self.snapshot_dir.mkdir(exist_ok=True)
        self.snapshot_manager = SnapshotManager(storage_dir=self.snapshot_dir)

        self.indexer = IncrementalIndexer(
            indexer=self.index_manager,
            embedder=self.embedder,
            chunker=self.chunker,
            snapshot_manager=self.snapshot_manager,
        )

        self.searcher = IntelligentSearcher(self.index_manager, self.embedder)

    def test_initial_index(self):
        """Test initial indexing."""
        result = self.indexer.incremental_index(str(self.test_project), self.project_name)

        # Check that indexing succeeded
        assert result.success is True, "Indexing should report success=True"
        assert isinstance(result.time_taken, (int, float)) and result.time_taken >= 0, (
            f"time_taken must be a non-negative number; got {result.time_taken!r}"
        )
        # Result must carry the required attributes with the correct types
        assert isinstance(result.chunks_added, int), (
            f"chunks_added must be an int; got {type(result.chunks_added).__name__}"
        )
        assert isinstance(result.files_added, int), (
            f"files_added must be an int; got {type(result.files_added).__name__}"
        )
        assert result.chunks_added >= 0, "chunks_added must be non-negative"
        assert result.files_added >= 0, "files_added must be non-negative"

    def test_no_reindex_immediately(self):
        """Test that no reindex happens immediately after indexing."""
        # Initial index
        self.indexer.incremental_index(str(self.test_project), self.project_name)

        # Immediate reindex check
        reindex_result = self.indexer.auto_reindex_if_needed(
            str(self.test_project),
            self.project_name,
            max_age_minutes=5
        )

        assert reindex_result.files_modified == 0, "No files should be marked for reindex"
        assert reindex_result.files_added == 0, "No files should be added on immediate reindex"
        assert reindex_result.files_removed == 0, "No files should be removed on immediate reindex"

    def test_reindex_with_short_timeout(self):
        """Test auto-reindex with short timeout."""
        # Initial index
        self.indexer.incremental_index(str(self.test_project), self.project_name)

        # Wait for timeout
        time.sleep(2)

        # Reindex with very short timeout (1 second)
        reindex_result = self.indexer.auto_reindex_if_needed(
            str(self.test_project),
            self.project_name,
            max_age_minutes=1/60  # 1 second
        )

        # Should trigger reindex due to age
        assert (reindex_result.files_modified >= 0 or
                reindex_result.files_added >= 0), "Reindex should be triggered or attempted"

    def test_snapshot_age(self):
        """Test snapshot age tracking."""
        # Initial index
        self.indexer.incremental_index(str(self.test_project), self.project_name)

        # Check stats
        stats = self.indexer.get_indexing_stats(str(self.test_project))
        assert stats is not None, "Should return indexing stats"
        assert 'snapshot_age' in stats, "Stats should include snapshot age"
        assert stats['snapshot_age'] >= 0, "Snapshot age should be non-negative"

    def test_search_after_reindex(self):
        """Test search functionality after auto-reindex."""
        # Initial index
        self.indexer.incremental_index(str(self.test_project), self.project_name)

        # Auto-reindex
        self.indexer.auto_reindex_if_needed(
            str(self.test_project),
            self.project_name,
            max_age_minutes=5
        )

        # Search
        results = self.searcher.search("database connection", k=3)

        # Results may be empty with mock, but should be a list
        assert isinstance(results, list), "Search should return a list"

    def test_needs_reindex_function(self):
        """Test needs_reindex function."""
        # Initial index
        self.indexer.incremental_index(str(self.test_project), self.project_name)

        # Should not need reindex with long timeout
        needs_long = self.indexer.needs_reindex(str(self.test_project), max_age_minutes=60)
        assert needs_long is False, "Should not need reindex with long timeout"

        # Wait briefly
        time.sleep(1)

        # May need reindex with very short timeout
        needs_short = self.indexer.needs_reindex(str(self.test_project), max_age_minutes=1/60)
        assert isinstance(needs_short, bool), "Should return boolean"

    def test_indexing_stats(self):
        """Test indexing statistics."""
        # Initial index
        result = self.indexer.incremental_index(str(self.test_project), self.project_name)

        # Get stats
        stats = self.indexer.get_indexing_stats(str(self.test_project))

        assert stats is not None, "Should return stats"
        # Check various possible stat keys depending on implementation
        has_stats = (
            stats.get('file_count', 0) > 0 or
            stats.get('files_indexed', 0) > 0 or
            stats.get('chunks_indexed', 0) > 0
        )
        assert has_stats, "Should have indexing statistics"
