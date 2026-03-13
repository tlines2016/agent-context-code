"""Vector index management with LanceDB — Phase 3 implementation.

This module replaces the legacy FAISS + SQLite + pickle storage with a
single embedded LanceDB table.  LanceDB is serverless (like SQLite for
vectors) — the "connection" is just a filesystem path, so there are no
credentials, no running server, and no workspace pollution.

Architecture changes vs. the FAISS backend
-------------------------------------------
* **Single table, all data** — vectors *and* metadata live in the same
  LanceDB table (``code_chunks``).  This eliminates the separate
  ``metadata.db`` (SQLiteDict) and ``chunk_ids.pkl`` files.
* **Native row-level deletes** — ``table.delete("file_path = '...'")``
  replaces the old "mark deleted in metadata but leave FAISS index stale"
  approach.  The Merkle-DAG incremental indexer can now delete outdated
  file chunks *and* insert replacements in a single pass.
* **Arrow/Pandas interop** — search results are returned as DataFrames
  internally, making filtering and post-processing much cleaner.
* **Automatic compaction** — ``optimize()`` runs after each indexing
  session to compact fragments and clean up old versions, preventing
  unbounded disk growth from accumulated Lance fragments and tombstones.
* **Scalar indexes** — BTREE indexes on ``relative_path`` and
  ``chunk_id``, plus a BITMAP index on ``chunk_type``, accelerate
  WHERE clause filtering on both standalone and vector+filter queries.

The public API of ``CodeIndexManager`` is preserved so that
``IncrementalIndexer``, ``IntelligentSearcher``, and ``CodeSearchServer``
continue to work with minimal (mostly zero) changes.
"""

import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import lancedb
from lancedb.pydantic import LanceModel, Vector

from embeddings.embedder import EmbeddingResult

logger = logging.getLogger(__name__)

# ── LanceDB table name ──────────────────────────────────────────────────
TABLE_NAME = "code_chunks"


def _make_schema_class(dim: int) -> type:
    """Create a LanceModel schema class with the specified vector dimension.

    We generate the class dynamically because LanceDB's ``Vector(N)`` must
    be a compile-time literal in the class body.  When the configured
    embedding model changes (e.g. 768-d Gemma vs 2560-d Qwen3) we need
    the schema to match.

    Parameters
    ----------
    dim : int
        The embedding vector dimension.
    """
    # Using type() + LanceModel as base to dynamically set Vector(dim).
    # LanceDB/Pydantic inspect __annotations__ at class-creation time.
    ns: dict = {
        "__annotations__": {
            "text": str,
            # type: ignore — Vector(dim) is a runtime descriptor that generates a
            # pyarrow FixedSizeList; mypy cannot verify it statically because
            # the dimension is a runtime variable, not a literal.
            "vector": Vector(dim),   # type: ignore[valid-type]
            "file_path": str,
            "relative_path": str,
            "chunk_type": str,
            "name": str,
            "parent_name": str,
            "start_line": int,
            "end_line": int,
            "docstring": str,
            "tags": str,            # JSON-encoded list
            "content_preview": str,
            "chunk_id": str,
            "project_name": str,
            "content": str,
            "folder_structure": str, # JSON-encoded list
            "decorators": str,       # JSON-encoded list
            "imports": str,          # JSON-encoded list
            "complexity_score": float,
        },
    }
    return type("CodeChunkRow", (LanceModel,), ns)


class CodeIndexManager:
    """Manages a LanceDB vector index and metadata for code chunks.

    This is the Phase 3 replacement for the FAISS + SQLiteDict backend.
    All data is stored in a single LanceDB table under the centralised
    storage directory (``~/.agent_code_search/``), never inside the
    user's project workspace.

    Public API
    ----------
    The methods below are intentionally kept compatible with the legacy
    FAISS ``CodeIndexManager`` so that ``IncrementalIndexer``,
    ``IntelligentSearcher``, and ``CodeSearchServer`` can switch backends
    with zero changes.
    """

    def __init__(self, storage_dir: str = ""):
        # Fallback for callers that omit storage_dir (e.g. legacy
        # IncrementalIndexer() instantiation without arguments).  We
        # default to a sub-directory under the centralised storage root
        # so that data never ends up in the user's project workspace.
        if not storage_dir:
            from common_utils import get_storage_dir
            storage_dir = str(get_storage_dir() / "default_index")

        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # LanceDB stores its data inside this sub-directory.
        self._lance_dir = self.storage_dir / "lancedb"
        self._lance_dir.mkdir(parents=True, exist_ok=True)

        self.stats_path = self.storage_dir / "stats.json"

        self._db = lancedb.connect(str(self._lance_dir))
        self._table = None
        self._embedding_dim: Optional[int] = None
        self._schema_class: Optional[type] = None
        self._logger = logging.getLogger(__name__)
        self._stats_cache: Optional[Dict[str, Any]] = None
        self._file_chunk_counts: Dict[str, int] = {}
        self._indexing_config: Dict[str, Any] = {}
        self._content_changed: bool = False

        # Attempt to open an existing table (created during a previous
        # indexing run).  If it does not exist yet we create it lazily
        # when the first batch of embeddings arrives.
        self._try_open_existing_table()

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _try_open_existing_table(self) -> None:
        """Open the ``code_chunks`` table if it already exists on disk.

        When re-opening a table created during a previous indexing run we
        also recover ``_embedding_dim`` and ``_schema_class`` from the
        Arrow schema so that ``get_stats()`` reports the correct dimension
        and ``add_embeddings()`` can detect model-change mismatches.
        """
        try:
            names = self._db.table_names()
            if TABLE_NAME in names:
                self._table = self._db.open_table(TABLE_NAME)

                # ── Recover embedding dimension from the Arrow schema ──
                # The ``vector`` column is stored as a FixedSizeList; its
                # list_size is the embedding dimension used when the table
                # was originally created.
                self._recover_embedding_dim()

                self._ensure_scalar_indexes()
                self._ensure_fts_index()

                self._logger.info(
                    "Opened existing LanceDB table '%s' with %d rows (dim=%s)",
                    TABLE_NAME,
                    self._table.count_rows(),
                    self._embedding_dim or "unknown",
                )
        except Exception as exc:
            self._logger.warning("Could not open existing LanceDB table: %s", exc)

    def _recover_embedding_dim(self) -> None:
        """Derive ``_embedding_dim`` and ``_schema_class`` from the opened table.

        This is needed because ``_try_open_existing_table`` skips
        ``_ensure_table`` (which normally sets these attributes).  Without
        this, stats would report ``embedding_dimension: 0`` and
        ``add_embeddings`` could not detect a model-change mismatch.
        """
        if self._table is None:
            return
        try:
            import pyarrow as pa
            schema = self._table.schema
            vec_field = schema.field("vector")
            # LanceDB stores vectors as FixedSizeList<float32, dim>.
            if pa.types.is_fixed_size_list(vec_field.type):
                dim = vec_field.type.list_size
                self._embedding_dim = dim
                self._schema_class = _make_schema_class(dim)
        except Exception as exc:
            # Log at warning — a missing/malformed vector column is
            # not expected and could cause silent dimension-mismatch
            # issues downstream.
            self._logger.warning("Could not recover embedding dim: %s", exc)

    def _ensure_table(self, embedding_dim: int) -> None:
        """Create the LanceDB table if it doesn't exist yet.

        The table is created with a schema that matches the embedding
        dimension of the first batch of vectors we receive.  This lets
        the same ``CodeIndexManager`` work with any model (768-d Gemma,
        2560-d Qwen3, etc.) without hard-coding a dimension.
        """
        if self._table is not None:
            return

        self._embedding_dim = embedding_dim
        self._schema_class = _make_schema_class(embedding_dim)

        self._table = self._db.create_table(
            TABLE_NAME,
            schema=self._schema_class.to_arrow_schema(),
        )
        self._logger.info(
            "Created LanceDB table '%s' (dim=%d)", TABLE_NAME, embedding_dim,
        )
        self._ensure_scalar_indexes()
        self._ensure_fts_index()

    def _ensure_scalar_indexes(self) -> None:
        """Create scalar indexes on filtered columns if they don't exist.

        - BTREE on ``relative_path`` (high cardinality — many unique file paths)
        - BITMAP on ``chunk_type`` (low cardinality — ~5 unique values)
        - BTREE on ``chunk_id`` (used in ``get_chunk_by_id()`` lookups)

        Scalar indexes accelerate WHERE clause filtering on both standalone
        queries and vector+filter searches.  They are updated during
        ``table.optimize()`` (see ``optimize()`` method).

        Uses ``replace=False`` so LanceDB skips creation when the index
        already exists, making this safe to call on every table open
        without rebuilding indexes or adding startup latency.
        """
        if self._table is None:
            return
        for col, idx_type in [
            ("relative_path", "BTREE"),
            ("chunk_type", "BITMAP"),
            ("chunk_id", "BTREE"),
        ]:
            try:
                self._table.create_scalar_index(col, index_type=idx_type, replace=False)
                self._logger.info("Created %s scalar index on '%s'", idx_type, col)
            except Exception:
                # Index already exists — skip silently.
                pass

    def _ensure_fts_index(self) -> None:
        """Create a full-text search (FTS) index on the ``text`` column.

        The FTS index uses Tantivy (via LanceDB) to enable BM25 keyword
        matching.  Combined with vector search in hybrid mode, this gives
        ~48% retrieval quality improvement over vector-only search
        (per recent RAG benchmarks).

        Safe to call repeatedly — LanceDB silently skips creation when the
        index already exists.

        BM25 parameter notes (k1=1.2, b=0.75 — Tantivy defaults)
        -----------------------------------------------------------
        Tantivy hardcodes k1=1.2 and b=0.75 in ``bm25.rs``; they are
        not configurable through Tantivy's API or LanceDB's
        ``create_fts_index()``.

        * **k1 (term frequency saturation):**  For AST-level code chunks
          (typically 50-500 lines), term frequency saturates naturally in
          short documents, so the exact k1 matters less.  Common code
          keywords (``def``, ``class``, ``return``) are high-frequency /
          low-signal, but RRF fusion with vector search already
          down-weights pure keyword noise.
        * **b (document length normalization):**  Code chunk length varies
          by complexity, not topical breadth.  Lower b (0.3-0.5) could
          reduce unfair length penalty on complex functions, but our
          AST-segmented chunks have bounded length variation (max 6000
          chars with head/tail truncation).
        * **Sourcegraph's approach:**  Their gains came from BM25F
          field-level boosting (5x for symbol names), not from tuning
          k1/b.  Our post-retrieval heuristics (1.4x name boost, path
          relevance boost) achieve a similar effect.

        Verdict: defaults are acceptable.  Our hybrid search architecture
        (RRF + heuristics + optional reranker) compensates for any BM25
        parameter suboptimality.
        """
        if self._table is None:
            return
        try:
            self._table.create_fts_index("text", replace=False)
            self._logger.info("FTS index on 'text' column ready")
        except Exception:
            # Index already exists or FTS not supported — skip silently.
            pass

    # ------------------------------------------------------------------
    # Public API — add / search / remove / clear
    # ------------------------------------------------------------------

    def add_embeddings(self, embedding_results: List[EmbeddingResult]) -> None:
        """Add embedding results to the LanceDB table.

        Each ``EmbeddingResult`` carries a numpy vector, a ``chunk_id``,
        and a metadata dict.  We flatten these into table rows.
        """
        if not embedding_results:
            return

        embedding_dim = embedding_results[0].embedding.shape[0]
        self._ensure_table(embedding_dim)

        # ── Validate dimension consistency ───────────────────────────
        # If the user changes the embedding model (e.g. 768-d Gemma →
        # 2560-d Qwen3) without clearing the index, the incoming vectors
        # would silently fail on insert.  Detect this early and give a
        # clear error message instead.
        if self._embedding_dim is not None and embedding_dim != self._embedding_dim:
            raise ValueError(
                f"Embedding dimension mismatch: incoming vectors have "
                f"dim={embedding_dim} but the existing LanceDB table was "
                f"created with dim={self._embedding_dim}.  Clear the index "
                f"(or delete the project storage) to switch models."
            )

        rows: list[dict] = []
        for result in embedding_results:
            meta = result.metadata
            rows.append({
                "text": meta.get("content_preview", ""),
                "vector": result.embedding.tolist(),
                "file_path": meta.get("file_path", ""),
                "relative_path": meta.get("relative_path", ""),
                "chunk_type": meta.get("chunk_type", ""),
                "name": meta.get("name", "") or "",
                "parent_name": meta.get("parent_name", "") or "",
                "start_line": meta.get("start_line", 0),
                "end_line": meta.get("end_line", 0),
                "docstring": meta.get("docstring", "") or "",
                "tags": json.dumps(meta.get("tags", [])),
                "content_preview": meta.get("content_preview", ""),
                "chunk_id": result.chunk_id,
                "project_name": meta.get("project_name", ""),
                "content": meta.get("content", ""),
                "folder_structure": json.dumps(meta.get("folder_structure", [])),
                "decorators": json.dumps(meta.get("decorators", [])),
                "imports": json.dumps(meta.get("imports", [])),
                "complexity_score": float(meta.get("complexity_score", 0)),
            })

        self._table.add(rows)
        self._content_changed = True
        self._logger.info("Added %d embeddings to LanceDB", len(rows))
        self._stats_cache = None  # Invalidate stats cache

    def search(
        self,
        query_embedding: np.ndarray,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        query_text: Optional[str] = None,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Search for similar code chunks via vector similarity.

        Returns a list of ``(chunk_id, similarity_score, metadata_dict)``
        tuples ordered by descending similarity.

        When ``query_text`` is provided *and* an FTS index exists, the search
        uses **hybrid mode** (BM25 keyword matching + vector similarity via
        Reciprocal Rank Fusion).  This combines the precision of exact keyword
        matches with the recall of semantic embeddings, yielding ~48% quality
        improvement over vector-only search per recent RAG benchmarks.

        When ``query_text`` is ``None`` or the FTS index is unavailable, the
        search falls back to pure vector similarity (cosine metric).

        **Metric choice — cosine similarity (vector-only mode)**
        Modern dense embedding models (Qwen3-Embedding, Gemma-Embedding,
        SFR-Embedding) L2-normalise their output vectors.  For normalised
        vectors, cosine similarity is the natural and most interpretable
        metric: 1.0 = identical direction, 0.0 = orthogonal, scores in
        a well-defined [0, 1] range.

        **refine_factor** — After ANN retrieval, LanceDB recomputes exact
        distances on ``refine_factor × k`` candidates, improving recall
        with negligible latency cost.

        .. note:: **Future improvement — parent-child retrieval**
           Currently each chunk is retrieved independently.  A higher-quality
           approach is to embed at the function/method level (small, precise
           chunks) but return the enclosing class or module as context to the
           LLM.  This would require storing a ``parent_chunk_id`` relationship
           and doing a follow-up fetch after retrieval.  The chunker already
           produces these granularities — the missing piece is the parent-child
           linkage at index time and context expansion at search time.
        """
        if self._table is None or self._table.count_rows() == 0:
            return []

        query_vec = query_embedding.reshape(-1).tolist()

        # Decide whether to use hybrid search (BM25 + vector) or vector-only.
        use_hybrid = query_text and self._has_fts_index()

        where_clause = self._build_where_clause(filters)

        # When filters are active, many ANN candidates may be discarded
        # by the WHERE clause.  Fetch 10× candidates to increase the
        # chance of returning the requested k results after filtering.
        fetch_k = k * 10 if filters else k

        try:
            if use_hybrid:
                df = self._hybrid_search(query_vec, query_text, fetch_k, where_clause)
            else:
                df = self._vector_search(query_vec, fetch_k, where_clause)
        except Exception as exc:
            self._logger.warning("LanceDB search failed: %s", exc)
            return []

        results: list[tuple[str, float, dict]] = []
        is_hybrid = "_relevance_score" in df.columns

        for _, row in df.iterrows():
            if is_hybrid:
                # Hybrid search returns _relevance_score (RRF-combined).
                # These are already in a [0, 1]-ish range, higher = better.
                similarity = max(0.0, float(row.get("_relevance_score", 0.0)))
            else:
                # Convert cosine distance → cosine similarity.
                # LanceDB cosine distance = 1 - cosine_similarity for normalised
                # vectors, so similarity = 1 - distance.  Result is in [0, 1].
                distance = row.get("_distance", 0.0)
                similarity = max(0.0, 1.0 - float(distance))

            metadata = self._row_to_metadata(row)
            chunk_id = row.get("chunk_id", "")
            results.append((chunk_id, similarity, metadata))

            if len(results) >= k:
                break

        return results

    def _vector_search(
        self,
        query_vec: list,
        fetch_k: int,
        where_clause: Optional[str],
    ):
        """Pure vector search with cosine metric and refine_factor."""
        query_builder = (
            self._table.search(query_vec)
            .metric("cosine")
            .refine_factor(5)
        )
        if where_clause:
            query_builder = query_builder.where(where_clause, prefilter=True)
        return query_builder.limit(fetch_k).to_pandas()

    def _hybrid_search(
        self,
        query_vec: list,
        query_text: str,
        fetch_k: int,
        where_clause: Optional[str],
    ):
        """Hybrid search combining BM25 (FTS) and vector similarity via RRF.

        Uses LanceDB's built-in hybrid query mode which:
        1. Runs a BM25 keyword search against the FTS index on ``text``
        2. Runs an ANN vector search against the vector column
        3. Combines results via Reciprocal Rank Fusion (RRF)
        """
        query_builder = (
            self._table.search(query_type="hybrid")
            .vector(query_vec)
            .text(query_text)
        )
        if where_clause:
            query_builder = query_builder.where(where_clause, prefilter=True)
        return query_builder.limit(fetch_k).to_pandas()

    def _has_fts_index(self) -> bool:
        """Check if the FTS index exists on this table."""
        if self._table is None:
            return False
        try:
            stats = self._table.index_stats()
            if stats:
                for idx_info in stats.values():
                    if hasattr(idx_info, 'index_type') and 'FTS' in str(getattr(idx_info, 'index_type', '')).upper():
                        return True
                    # Fallback: check if any index mentions the text column
                    if hasattr(idx_info, 'columns') and 'text' in str(getattr(idx_info, 'columns', '')):
                        return True
            # If we can't confirm via stats, try the FTS path optimistically.
            # The _get_fts_index_path method exists on LanceDB tables.
            if hasattr(self._table, '_get_fts_index_path'):
                fts_path = self._table._get_fts_index_path()
                if fts_path and fts_path.exists():
                    return True
            return False
        except Exception:
            return False

    def remove_file_chunks(
        self, file_path: str, project_name: Optional[str] = None,
    ) -> int:
        """Delete all chunks belonging to *file_path*.

        LanceDB supports native row-level deletes, which is the key
        advantage over FAISS (which required a full index rebuild).
        The Merkle-DAG incremental indexer calls this for every
        modified / deleted file before inserting updated chunks.
        """
        if self._table is None:
            return 0

        # Count before delete so we can report how many were removed.
        before = self._table.count_rows()

        # Escape single quotes in the file path for the SQL predicate.
        safe_path = file_path.replace("'", "''")

        # Build a WHERE that matches either file_path or relative_path,
        # since the incremental indexer may pass either form.
        where = (
            f"file_path = '{safe_path}' OR relative_path = '{safe_path}'"
        )
        if project_name:
            safe_project = project_name.replace("'", "''")
            where = f"({where}) AND project_name = '{safe_project}'"

        try:
            self._table.delete(where)
        except Exception as exc:
            self._logger.warning("Failed to delete chunks for %s: %s", file_path, exc)
            return 0

        removed = before - self._table.count_rows()
        if removed > 0:
            self._content_changed = True
        self._logger.info("Removed %d chunks for %s", removed, file_path)
        self._stats_cache = None
        return removed

    def clear_index(self) -> None:
        """Drop the entire table and reset in-memory state."""
        try:
            if TABLE_NAME in self._db.table_names():
                self._db.drop_table(TABLE_NAME)
        except Exception as exc:
            self._logger.warning("Failed to drop LanceDB table: %s", exc)

        self._table = None
        self._embedding_dim = None
        self._schema_class = None
        self._stats_cache = None
        self._file_chunk_counts = {}
        self._indexing_config = {}

        # Also remove legacy files if they exist (migration cleanup).
        for legacy in ("code.index", "metadata.db", "chunk_ids.pkl"):
            p = self.storage_dir / legacy
            if p.exists():
                p.unlink()

        # Remove stats.json so that get_stats() does not return stale
        # data after the index has been cleared.
        if self.stats_path.exists():
            self.stats_path.unlink()

        self._logger.info("Index cleared")

    def optimize(self) -> None:
        """Compact fragments, clean up old versions, and rebuild FTS index.

        Every ``table.add()`` and ``table.delete()`` creates new Lance
        fragments and versions.  Without periodic compaction, disk usage
        grows unboundedly and deletes remain as soft tombstones.  Call
        this once after a batch of add/delete operations (not per-row).

        Uses ``cleanup_older_than=timedelta(days=1)`` to keep one day of
        history — safe for the single-writer pattern and allows rollback
        if needed.

        After compaction, the FTS index is rebuilt (``replace=True``) so
        that keyword search reflects the latest adds/deletes.
        """
        if self._table is None:
            return
        try:
            self._table.optimize(cleanup_older_than=timedelta(days=1))
            self._logger.info("LanceDB table optimized (compaction + version cleanup)")
        except Exception as exc:
            self._logger.warning("LanceDB optimize failed: %s", exc)

        # Only rebuild the FTS index when content actually changed (adds/deletes
        # occurred since the last optimize).  Skipping the rebuild when nothing
        # changed avoids an expensive full-text re-index on no-op sessions.
        if self._content_changed:
            try:
                self._table.create_fts_index("text", replace=True)
                self._logger.info("FTS index rebuilt after optimization")
            except Exception as exc:
                self._logger.warning("FTS index rebuild failed: %s", exc)
            self._content_changed = False
        else:
            self._logger.debug("Skipping FTS rebuild — no content changes since last optimize")

    def save_index(self) -> None:
        """Persist stats to disk.

        LanceDB writes data to disk automatically on ``add()`` and
        ``delete()``, so there is no separate "save" step for the
        vectors.  We only need to write the stats JSON.
        """
        self._update_stats()

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def set_indexing_config(self, indexing_config: Optional[Dict[str, Any]]) -> None:
        """Store the indexing configuration for cache-invalidation checks."""
        self._indexing_config = dict(indexing_config or {})
        self._stats_cache = None

    def get_chunk_by_id(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve chunk metadata by its unique ID.

        A BTREE scalar index on ``chunk_id`` accelerates this lookup.
        """
        if self._table is None:
            return None
        try:
            # LanceDB's .where() takes a SQL string, not parameterized placeholders.
            # Escape single-quotes so IDs containing apostrophes don't break the filter.
            safe_id = chunk_id.replace("'", "''")
            df = (
                self._table.search()
                .where(f"chunk_id = '{safe_id}'")
                .limit(1)
                .to_pandas()
            )
            if df.empty:
                return None
            return self._row_to_metadata(df.iloc[0])
        except Exception:
            return None

    def get_similar_chunks(
        self, chunk_id: str, k: int = 5,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Find chunks similar to a given chunk (by its embedding).

        Uses a filtered WHERE query to fetch only the target row's vector
        rather than loading the entire table into a DataFrame.
        """
        if self._table is None:
            return []
        try:
            # Fetch only the target row's vector via a filtered query
            # instead of materializing the entire table (O(1) vs O(N)).
            # LanceDB's .where() takes a SQL string — escape single-quotes manually.
            safe_id = chunk_id.replace("'", "''")
            df = (
                self._table.search()
                .where(f"chunk_id = '{safe_id}'")
                .limit(1)
                .to_pandas()
            )
            if df.empty:
                return []
            vec = df.iloc[0]["vector"]
            if isinstance(vec, np.ndarray):
                vec_arr = vec.astype(np.float32)
            else:
                vec_arr = np.array(vec, dtype=np.float32)
            results = self.search(vec_arr, k + 1)
            return [(cid, sim, meta) for cid, sim, meta in results if cid != chunk_id][:k]
        except Exception:
            return []

    def get_file_chunk_count(self, relative_path: str) -> int:
        """Return the number of indexed chunks for a specific file."""
        if not relative_path:
            return 0
        if relative_path not in self._file_chunk_counts:
            self.get_stats()
        return self._file_chunk_counts.get(relative_path, 0)

    def get_index_size(self) -> int:
        """Return the total number of chunks in the index."""
        if self._table is None:
            return 0
        try:
            return self._table.count_rows()
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self, summary_only: bool = False) -> Dict[str, Any]:
        """Return index statistics (cached).

        Parameters
        ----------
        summary_only : bool
            When True, excludes the ``file_chunk_counts`` dict from the
            returned payload.  This keeps the response compact for MCP
            tool output on large projects (the full dict can be 100 KB+
            for 1000-file codebases).  The internal cache always stores
            the full data so ``get_file_chunk_count()`` continues to work.
        """
        if self._stats_cache is not None:
            return self._make_summary(self._stats_cache) if summary_only else self._stats_cache

        if self.stats_path.exists():
            try:
                with open(self.stats_path, "r") as f:
                    stats = json.load(f)
                self._stats_cache = stats
                self._file_chunk_counts = stats.get("file_chunk_counts", {})
                self._indexing_config = stats.get("indexing_config", {})
                return self._make_summary(stats) if summary_only else stats
            except Exception:
                pass

        full_stats = self._compute_stats()
        return self._make_summary(full_stats) if summary_only else full_stats

    @staticmethod
    def _make_summary(stats: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of *stats* without the large ``file_chunk_counts`` dict."""
        return {k: v for k, v in stats.items() if k != "file_chunk_counts"}

    def _update_stats(self) -> None:
        """Recompute and persist index statistics."""
        stats = self._compute_stats()
        try:
            with open(self.stats_path, "w") as f:
                json.dump(stats, f, indent=2)
        except Exception as exc:
            self._logger.warning("Failed to write stats: %s", exc)

    def _compute_stats(self) -> Dict[str, Any]:
        """Build statistics from the current table contents.

        Uses a two-tier scan strategy to avoid loading the large 'vector' column:

        1. **Preferred** — column projection via the Lance dataset (requires the
           ``lance`` package to be installed separately).  Skips the vector
           column entirely — for a 2560-d Qwen3 model with 10 000 chunks this
           saves ~100 MB of data transfer.

        2. **Fallback** — full ``to_pandas()`` scan.  Loads all columns including
           vectors, then immediately discards the vector data before Python-side
           aggregation.  Always available; just slightly less memory-efficient.
        """
        total = self.get_index_size()

        file_counts: Dict[str, int] = {}
        folder_counts: Dict[str, int] = {}
        chunk_type_counts: Dict[str, int] = {}
        tag_counts: Dict[str, int] = {}

        if self._table is not None and total > 0:
            df = None
            try:
                # Preferred path: column projection via the Lance dataset API.
                # to_lance() returns the underlying lance.LanceDataset; its
                # to_table(columns=[...]) performs a columnar scan without
                # touching the vector column.  Requires the 'lance' package.
                arrow_tbl = self._table.to_lance().to_table(
                    columns=["relative_path", "folder_structure", "chunk_type", "tags"]
                )
                df = arrow_tbl.to_pandas()
            except Exception:
                pass  # Fall through to the full-scan fallback below.

            if df is None:
                # Fallback: column-projected scanner that avoids loading
                # the vector column into memory.
                try:
                    needed = ["relative_path", "folder_structure", "chunk_type", "tags"]
                    scanner = self._table.scanner(columns=needed)
                    arrow_tbl = scanner.to_table()
                    df = arrow_tbl.to_pandas()
                except Exception:
                    # Last resort: full scan
                    try:
                        full_df = self._table.to_pandas()
                        df = full_df[[c for c in needed if c in full_df.columns]]
                    except Exception as exc:
                        self._logger.warning("Failed to compute stats: %s", exc)

            if df is not None:
                for _, row in df.iterrows():
                    rp = row.get("relative_path", "unknown")
                    file_counts[rp] = file_counts.get(rp, 0) + 1

                    for folder in json.loads(row.get("folder_structure", "[]") or "[]"):
                        folder_counts[folder] = folder_counts.get(folder, 0) + 1

                    ct = row.get("chunk_type", "unknown")
                    chunk_type_counts[ct] = chunk_type_counts.get(ct, 0) + 1

                    for tag in json.loads(row.get("tags", "[]") or "[]"):
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # ── Storage health metrics ──────────────────────────────────────
        version_count = None
        storage_size_mb = None
        try:
            if self._table is not None:
                versions = self._table.list_versions()
                version_count = len(versions)
        except Exception:
            pass
        try:
            lance_size = sum(
                f.stat().st_size for f in self._lance_dir.rglob("*") if f.is_file()
            )
            storage_size_mb = round(lance_size / (1024 * 1024), 2)
        except Exception:
            pass

        stats: Dict[str, Any] = {
            "total_chunks": total,
            "index_size": total,
            "embedding_dimension": self._embedding_dim or 0,
            "index_type": "LanceDB",
            "indexing_config": self._indexing_config,
            "files_indexed": len(file_counts),
            "file_chunk_counts": file_counts,
            "top_folders": dict(
                sorted(folder_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
            "chunk_types": chunk_type_counts,
            "top_tags": dict(
                sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:20]
            ),
            "version_count": version_count,
            "storage_size_mb": storage_size_mb,
        }
        self._file_chunk_counts = file_counts
        self._stats_cache = stats
        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _escape_like_pattern(value: str) -> str:
        """Escape a value for safe use inside a SQL LIKE pattern.

        Escapes single quotes (SQL string delimiter), ``%`` (matches any
        sequence), and ``_`` (matches any single character) so that
        user-provided filter values are treated as literal strings.
        """
        return (
            value
            .replace("'", "''")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )

    @staticmethod
    def _glob_to_like_pattern(glob_pattern: str) -> str:
        """Convert a glob pattern (or plain substring) to a SQL LIKE pattern.

        Handles three cases:

        1. **No glob chars** (``*``, ``?``): treated as a substring match
           for backward compatibility — ``auth`` becomes ``%auth%``.
        2. **Single star** (``*``) and **double star** (``**``): both
           translated to ``%`` (SQL LIKE has no single-segment wildcard).
           ``*.kt`` becomes ``%.kt``; ``src/**/*.ts`` becomes ``src/%.ts``.
        3. **Question mark** (``?``): single character — translated to ``_``.

        .. note::

           SQL LIKE ``%`` matches across path separators, so ``*`` and
           ``**`` are functionally equivalent.  This is more permissive
           than true filesystem glob but sufficient for file-pattern
           filtering in search results.

        Backslashes in the input are normalised to forward slashes so
        patterns work on both Windows and Unix.
        """
        pattern = glob_pattern.replace("\\", "/")

        has_glob = "*" in pattern or "?" in pattern
        if not has_glob:
            safe = CodeIndexManager._escape_like_pattern(pattern)
            return f"%{safe}%"

        # Process the glob pattern segment by segment.
        # 1) Replace ** with a placeholder (to avoid double-processing).
        # 2) Escape literal parts.
        # 3) Convert * -> %, ? -> _.
        result_parts: list[str] = []
        # Split on '**' first, then handle '*' inside each part.
        double_star_segments = pattern.split("**")
        for idx, segment in enumerate(double_star_segments):
            if idx > 0:
                # Each '**' boundary becomes '%' (match any depth).
                result_parts.append("%")
            # Within each segment, split on '*' to handle single-star globs.
            star_segments = segment.split("*")
            for j, literal in enumerate(star_segments):
                if j > 0:
                    result_parts.append("%")
                # Within each literal piece, convert '?' to '_' and escape
                # SQL-significant characters in the literal text.
                qmark_parts = literal.split("?")
                for q, lit in enumerate(qmark_parts):
                    if q > 0:
                        result_parts.append("_")
                    if lit:
                        result_parts.append(CodeIndexManager._escape_like_pattern(lit))

        # Collapse consecutive '%' markers (e.g. "%/%" from "**/" → "%").
        # SQL LIKE '%' already matches any sequence including path separators,
        # so adjacent '%' are redundant.
        merged: list[str] = []
        for part in result_parts:
            if part == "%" and merged and merged[-1] == "%":
                continue
            merged.append(part)
        # Also collapse cases like %/% where the / between wildcards is redundant
        result = "".join(merged)
        while "%/%" in result:
            result = result.replace("%/%", "%")
        return result

    @staticmethod
    def _build_where_clause(filters: Optional[Dict[str, Any]]) -> Optional[str]:
        """Convert the legacy filter dict into a LanceDB SQL WHERE clause."""
        if not filters:
            return None

        clauses: list[str] = []
        for key, value in filters.items():
            if key == "file_pattern":
                # file_pattern is a list of glob patterns (or substrings) to
                # match against relative_path.  Glob chars are converted to
                # SQL LIKE wildcards; plain strings fall back to substring match.
                pattern_clauses = []
                for pattern in value:
                    like_pattern = CodeIndexManager._glob_to_like_pattern(pattern)
                    pattern_clauses.append(
                        f"relative_path LIKE '{like_pattern}' ESCAPE '\\'"
                    )
                if pattern_clauses:
                    clauses.append("(" + " OR ".join(pattern_clauses) + ")")
            elif key == "chunk_type":
                safe = str(value).replace("'", "''")
                clauses.append(f"chunk_type = '{safe}'")
            elif key == "folder_structure":
                # folder_structure is stored as a JSON-encoded list string.
                # Use JSON-token matching ("%"folder"%" with surrounding quotes)
                # to prevent substring false-positives.  For example,
                # filtering for folder "src" must NOT match "srcgen".
                folders = value if isinstance(value, list) else [value]
                fc = []
                for folder in folders:
                    safe = CodeIndexManager._escape_like_pattern(folder).replace('"', '""')
                    fc.append(f'folder_structure LIKE \'%"{safe}"%\' ESCAPE \'\\\'')
                if fc:
                    clauses.append("(" + " OR ".join(fc) + ")")
            elif key == "tags":
                # Same JSON-token matching strategy as folder_structure.
                # Filtering for tag "auth" must NOT match "oauth" or
                # "authentication" — surrounding quotes ensure exact token
                # boundaries within the JSON-encoded list string.
                tags = value if isinstance(value, list) else [value]
                tc = []
                for tag in tags:
                    safe = CodeIndexManager._escape_like_pattern(tag).replace('"', '""')
                    tc.append(f'tags LIKE \'%"{safe}"%\' ESCAPE \'\\\'')
                if tc:
                    clauses.append("(" + " OR ".join(tc) + ")")

        return " AND ".join(clauses) if clauses else None

    @staticmethod
    def _row_to_metadata(row) -> Dict[str, Any]:
        """Convert a LanceDB/Pandas row to the legacy metadata dict format.

        The callers (``IntelligentSearcher``, ``CodeSearchServer``)
        expect a plain dict with the same keys that the old SQLiteDict
        metadata used.  We reconstruct that here.
        """
        def _safe_json_loads(val, default=None):
            """Parse a JSON string, returning *default* on failure."""
            if default is None:
                default = []
            if not val:
                return default
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return default

        return {
            "file_path": row.get("file_path", ""),
            "relative_path": row.get("relative_path", ""),
            "folder_structure": _safe_json_loads(row.get("folder_structure")),
            "chunk_type": row.get("chunk_type", ""),
            "start_line": int(row.get("start_line", 0)),
            "end_line": int(row.get("end_line", 0)),
            "name": row.get("name", ""),
            "parent_name": row.get("parent_name", ""),
            "docstring": row.get("docstring", ""),
            "decorators": _safe_json_loads(row.get("decorators")),
            "imports": _safe_json_loads(row.get("imports")),
            "complexity_score": float(row.get("complexity_score", 0)),
            "tags": _safe_json_loads(row.get("tags")),
            "content_preview": row.get("content_preview", ""),
            "project_name": row.get("project_name", ""),
            "content": row.get("content", ""),
        }

    def __del__(self):
        """No-op — LanceDB handles its own cleanup."""
        pass
