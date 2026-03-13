"""Unit tests for search/indexer.CodeIndexManager."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from embeddings.embedder import EmbeddingResult
from search.indexer import CodeIndexManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_embedding_result(
    chunk_id: str,
    dim: int = 4,
    *,
    file_path: str = "/proj/foo.py",
    relative_path: str = "foo.py",
    chunk_type: str = "function",
    name: str = "my_func",
    content_preview: str = "def my_func(): pass",
) -> EmbeddingResult:
    rng = np.random.RandomState(abs(hash(chunk_id)) % (2**31))
    embedding = rng.randn(dim).astype(np.float32)
    # Normalise so cosine similarity is well-defined
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm
    return EmbeddingResult(
        chunk_id=chunk_id,
        embedding=embedding,
        metadata={
            "file_path": file_path,
            "relative_path": relative_path,
            "chunk_type": chunk_type,
            "name": name,
            "content_preview": content_preview,
            "start_line": 1,
            "end_line": 5,
            "tags": ["python"],
            "project_name": "test_proj",
        },
    )


@pytest.fixture()
def index_manager(tmp_path) -> CodeIndexManager:
    """Return a fresh CodeIndexManager backed by a temp LanceDB."""
    return CodeIndexManager(str(tmp_path / "index"))


@pytest.fixture()
def populated_index(index_manager) -> CodeIndexManager:
    """Index manager pre-populated with 5 chunks of dim=4."""
    results = [_make_embedding_result(f"chunk_{i}", dim=4) for i in range(5)]
    index_manager.add_embeddings(results)
    return index_manager


# ---------------------------------------------------------------------------
# Basic state
# ---------------------------------------------------------------------------

class TestInitialState:
    def test_new_index_is_empty(self, index_manager):
        assert index_manager.get_index_size() == 0

    def test_search_on_empty_index_returns_empty(self, index_manager):
        qv = np.zeros(4, dtype=np.float32)
        assert index_manager.search(qv, k=5) == []

    def test_get_chunk_by_id_on_empty_returns_none(self, index_manager):
        assert index_manager.get_chunk_by_id("nonexistent") is None

    def test_get_similar_chunks_on_empty_returns_empty(self, index_manager):
        assert index_manager.get_similar_chunks("nonexistent", k=3) == []


# ---------------------------------------------------------------------------
# add_embeddings / dimension validation
# ---------------------------------------------------------------------------

class TestAddEmbeddings:
    def test_add_increases_index_size(self, index_manager):
        results = [_make_embedding_result(f"c{i}", dim=4) for i in range(3)]
        index_manager.add_embeddings(results)
        assert index_manager.get_index_size() == 3

    def test_add_empty_list_is_noop(self, index_manager):
        index_manager.add_embeddings([])
        assert index_manager.get_index_size() == 0

    def test_dimension_mismatch_raises_value_error(self, index_manager):
        """Adding vectors with a different dim after the table is created must raise."""
        index_manager.add_embeddings([_make_embedding_result("first", dim=4)])
        with pytest.raises(ValueError, match="dimension mismatch"):
            index_manager.add_embeddings([_make_embedding_result("second", dim=8)])


# ---------------------------------------------------------------------------
# Search results format
# ---------------------------------------------------------------------------

class TestSearchResults:
    def test_search_returns_list_of_tuples(self, populated_index):
        qv = np.zeros(4, dtype=np.float32)
        results = populated_index.search(qv, k=3)
        assert isinstance(results, list)
        for item in results:
            assert len(item) == 3
            chunk_id, score, meta = item
            assert isinstance(chunk_id, str)
            assert isinstance(score, float)
            assert isinstance(meta, dict)

    def test_search_respects_k_limit(self, populated_index):
        qv = np.zeros(4, dtype=np.float32)
        results = populated_index.search(qv, k=2)
        assert len(results) <= 2

    def test_search_scores_are_in_0_1_range(self, populated_index):
        qv = np.zeros(4, dtype=np.float32)
        results = populated_index.search(qv, k=5)
        for _, score, _ in results:
            assert 0.0 <= score <= 1.0, f"Score out of range: {score}"

    def test_search_returns_chunk_ids(self, populated_index):
        qv = np.zeros(4, dtype=np.float32)
        results = populated_index.search(qv, k=5)
        chunk_ids = [cid for cid, _, _ in results]
        # No duplicate IDs
        assert len(set(chunk_ids)) == len(chunk_ids), "Duplicate chunk IDs in results"
        # All IDs should be non-empty strings matching the known fixture names
        expected_ids = {f"chunk_{i}" for i in range(5)}
        for cid in chunk_ids:
            assert isinstance(cid, str) and len(cid) > 0
            assert cid in expected_ids, f"Unexpected chunk_id '{cid}' not in fixture"


# ---------------------------------------------------------------------------
# Filter clause escaping and correctness
# ---------------------------------------------------------------------------

class TestFilterClauses:
    def test_chunk_type_filter_restricts_results(self, tmp_path):
        """Only chunks matching the chunk_type filter should be returned."""
        im = CodeIndexManager(str(tmp_path / "idx"))
        func_chunk = _make_embedding_result("func_1", chunk_type="function")
        cls_chunk = _make_embedding_result("cls_1", chunk_type="class")
        im.add_embeddings([func_chunk, cls_chunk])

        qv = np.ones(4, dtype=np.float32) / 2.0
        results = im.search(qv, k=10, filters={"chunk_type": "function"})
        for cid, _, _ in results:
            assert cid == "func_1"

    def test_empty_index_with_filters_returns_empty(self, index_manager):
        qv = np.zeros(4, dtype=np.float32)
        results = index_manager.search(qv, k=5, filters={"chunk_type": "class"})
        assert results == []

    def test_file_pattern_filter_underscore_is_literal(self, tmp_path):
        """Verify that '_' in file_pattern is treated as a literal character.

        The _build_where_clause escapes SQL wildcard chars ('%' and '_')
        via _escape_like_pattern() and emits an ESCAPE clause so that
        DuckDB treats them literally.  A pattern like 'foo_bar' should
        match only 'foo_bar.py', NOT 'fooXbar.py'.
        """
        im = CodeIndexManager(str(tmp_path / "idx"))
        # Add a chunk at 'foo_bar.py' and one at 'fooXbar.py'
        r1 = _make_embedding_result("c0", relative_path="foo_bar.py")
        r2 = _make_embedding_result("c1", relative_path="fooXbar.py")
        im.add_embeddings([r1, r2])

        qv = np.ones(4, dtype=np.float32) / 2.0
        results = im.search(qv, k=10, filters={"file_pattern": ["foo_bar"]})
        matched_paths = {meta.get("relative_path") for _, _, meta in results}
        # With ESCAPE clause active, '_' is literal — only exact match
        assert "foo_bar.py" in matched_paths
        assert "fooXbar.py" not in matched_paths


# ---------------------------------------------------------------------------
# get_chunk_by_id
# ---------------------------------------------------------------------------

class TestGetChunkById:
    def test_get_chunk_by_id_returns_metadata(self, populated_index):
        result = populated_index.get_chunk_by_id("chunk_0")
        assert result is not None
        assert isinstance(result, dict)

    def test_get_chunk_by_id_missing_returns_none(self, populated_index):
        assert populated_index.get_chunk_by_id("no_such_chunk") is None

    def test_get_chunk_by_id_metadata_has_expected_keys(self, populated_index):
        result = populated_index.get_chunk_by_id("chunk_0")
        assert result is not None
        # Basic metadata keys should be present
        assert "chunk_type" in result or "file_path" in result


# ---------------------------------------------------------------------------
# get_similar_chunks — exclude self, metadata contract
# ---------------------------------------------------------------------------

class TestGetSimilarChunks:
    def test_similar_chunks_excludes_self(self, populated_index):
        results = populated_index.get_similar_chunks("chunk_0", k=4)
        ids = [cid for cid, _, _ in results]
        assert "chunk_0" not in ids

    def test_similar_chunks_returns_at_most_k(self, populated_index):
        results = populated_index.get_similar_chunks("chunk_0", k=2)
        assert len(results) <= 2

    def test_similar_chunks_for_nonexistent_returns_empty(self, populated_index):
        results = populated_index.get_similar_chunks("nonexistent_id", k=3)
        assert results == []

    def test_similar_chunks_result_format(self, populated_index):
        results = populated_index.get_similar_chunks("chunk_0", k=3)
        for item in results:
            assert len(item) == 3
            cid, score, meta = item
            assert isinstance(cid, str)
            assert isinstance(score, float)
            assert isinstance(meta, dict)


# ---------------------------------------------------------------------------
# remove_file_chunks
# ---------------------------------------------------------------------------

class TestRemoveFileChunks:
    def test_remove_decreases_index_size(self, tmp_path):
        im = CodeIndexManager(str(tmp_path / "idx"))
        r1 = _make_embedding_result("c0", file_path="/proj/a.py", relative_path="a.py")
        r2 = _make_embedding_result("c1", file_path="/proj/b.py", relative_path="b.py")
        im.add_embeddings([r1, r2])
        assert im.get_index_size() == 2
        im.remove_file_chunks("/proj/a.py")
        assert im.get_index_size() == 1

    def test_remove_on_empty_index_is_safe(self, index_manager):
        count = index_manager.remove_file_chunks("/nonexistent/file.py")
        assert count == 0


# ---------------------------------------------------------------------------
# clear_index
# ---------------------------------------------------------------------------

class TestClearIndex:
    def test_clear_empties_index(self, populated_index):
        populated_index.clear_index()
        assert populated_index.get_index_size() == 0

    def test_clear_allows_re_add_with_different_dim(self, tmp_path):
        """After clearing, adding vectors with a different dimension should work."""
        im = CodeIndexManager(str(tmp_path / "idx"))
        im.add_embeddings([_make_embedding_result("c0", dim=4)])
        im.clear_index()
        im.add_embeddings([_make_embedding_result("c1", dim=8)])
        assert im.get_index_size() == 1


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:
    def test_get_stats_returns_dict(self, index_manager):
        stats = index_manager.get_stats()
        assert isinstance(stats, dict)

    def test_get_stats_total_chunks_zero_on_empty(self, index_manager):
        stats = index_manager.get_stats()
        assert stats.get("total_chunks", 0) == 0

    def test_get_stats_total_chunks_matches_size(self, populated_index):
        stats = populated_index.get_stats()
        assert stats.get("total_chunks", -1) == populated_index.get_index_size()


# ---------------------------------------------------------------------------
# prefilter flag on .where() calls
# ---------------------------------------------------------------------------

class TestPrefilterFlag:
    """Verify _vector_search and _hybrid_search pass prefilter=True."""

    def test_vector_search_passes_prefilter(self, populated_index):
        """_vector_search passes prefilter=True when a where_clause is set."""
        mock_builder = MagicMock()
        mock_builder.metric.return_value = mock_builder
        mock_builder.refine_factor.return_value = mock_builder
        mock_builder.where.return_value = mock_builder
        mock_builder.limit.return_value = mock_builder
        mock_builder.to_pandas.return_value = MagicMock(iterrows=lambda: iter([]))

        with patch.object(populated_index, "_table") as mock_table:
            mock_table.search.return_value = mock_builder
            populated_index._vector_search([0.1, 0.2, 0.3, 0.4], 10, "chunk_type = 'function'")

        mock_builder.where.assert_called_once_with("chunk_type = 'function'", prefilter=True)

    def test_hybrid_search_passes_prefilter(self, populated_index):
        """_hybrid_search passes prefilter=True when a where_clause is set."""
        mock_builder = MagicMock()
        mock_builder.vector.return_value = mock_builder
        mock_builder.text.return_value = mock_builder
        mock_builder.where.return_value = mock_builder
        mock_builder.limit.return_value = mock_builder
        mock_builder.to_pandas.return_value = MagicMock(iterrows=lambda: iter([]))

        with patch.object(populated_index, "_table") as mock_table:
            mock_table.search.return_value = mock_builder
            populated_index._hybrid_search([0.1, 0.2, 0.3, 0.4], "test query", 10, "chunk_type = 'function'")

        mock_builder.where.assert_called_once_with("chunk_type = 'function'", prefilter=True)

    def test_vector_search_no_where_without_clause(self, populated_index):
        """_vector_search does not call .where() when clause is None."""
        mock_builder = MagicMock()
        mock_builder.metric.return_value = mock_builder
        mock_builder.refine_factor.return_value = mock_builder
        mock_builder.limit.return_value = mock_builder
        mock_builder.to_pandas.return_value = MagicMock(iterrows=lambda: iter([]))

        with patch.object(populated_index, "_table") as mock_table:
            mock_table.search.return_value = mock_builder
            populated_index._vector_search([0.1, 0.2, 0.3, 0.4], 10, None)

        mock_builder.where.assert_not_called()

    def test_hybrid_search_no_where_without_clause(self, populated_index):
        """_hybrid_search does not call .where() when clause is None."""
        mock_builder = MagicMock()
        mock_builder.vector.return_value = mock_builder
        mock_builder.text.return_value = mock_builder
        mock_builder.limit.return_value = mock_builder
        mock_builder.to_pandas.return_value = MagicMock(iterrows=lambda: iter([]))

        with patch.object(populated_index, "_table") as mock_table:
            mock_table.search.return_value = mock_builder
            populated_index._hybrid_search([0.1, 0.2, 0.3, 0.4], "test query", 10, None)

        mock_builder.where.assert_not_called()
