"""Phase 1 — LanceDB schema and storage tests.

Why LanceDB?
    LanceDB is an embedded, serverless vector database — think "SQLite for
    vectors."  It stores everything on local disk (no external server, no
    username/password, no Docker container).  The connection string is simply a
    filesystem path, which is managed internally by agent-context-code via
    ``common_utils.get_storage_dir()``.  This keeps the "easy to install, 100%
    local" promise intact while giving us native vector search, row-level
    deletes for incremental re-indexing, and Apache Arrow / Pandas
    interoperability that FAISS lacked.

Schema design rationale:
    The ``CodeChunkModel`` Pydantic schema mirrors the metadata that
    ``CodeIndexManager`` previously stored in SQLite + FAISS.  By collapsing
    the vector *and* the metadata into a single LanceDB table we eliminate the
    need for a separate ``metadata.db`` and ``chunk_ids.pkl``, simplifying
    both storage and the delete-by-file-path logic required by the Merkle
    DAG incremental indexer.

    The ``vector`` field is typed as a ``Vector(QWEN3_4B_EMBEDDING_DIM)``
    fixed-size list so that LanceDB can build an ANN index on it.  The
    dimension (2560) matches the hidden_size of the Unsloth/Qwen3-Embedding-4B
    model that is the new default for GPU-accelerated search.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest

import lancedb
from lancedb.pydantic import LanceModel, Vector

# ── Import the embedding dimension from our own catalog so the test stays
# in sync with the rest of the codebase rather than hard-coding a magic
# number.
from embeddings.model_catalog import QWEN3_4B_EMBEDDING_DIM


# ---------------------------------------------------------------------------
# Pydantic LanceModel schema
# ---------------------------------------------------------------------------
class CodeChunkModel(LanceModel):
    """Pydantic schema for a single indexed code chunk stored in LanceDB.

    Fields
    ------
    text : str
        The embedding content (created by ``CodeEmbedder.create_embedding_content``).
    vector : Vector
        The dense embedding vector.  Dimension matches the Unsloth Qwen3-4B
        model (2560-d).
    file_path : str
        Absolute or relative path of the source file that contains this chunk.
    chunk_index : int
        Positional index of this chunk within its source file (0-based).
        Useful for ordering search results by their position in a file.
    """

    # The actual embedding — LanceDB stores this as a FixedSizeList in the
    # underlying Arrow table, which allows efficient ANN indexing.
    text: str
    # type: ignore is needed because LanceDB's Vector() is a runtime descriptor
    # that mypy/pyright cannot verify statically — it generates a proper
    # pyarrow FixedSizeList type at schema-construction time.
    vector: Vector(QWEN3_4B_EMBEDDING_DIM)  # type: ignore[valid-type]
    file_path: str
    chunk_index: int


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def lance_tmp_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for a throwaway LanceDB database.

    LanceDB is embedded/serverless — the "connection" is just a directory on
    disk.  No username, password, or running server required.  This is why we
    can spin up and tear down databases freely inside tests.
    """
    db_dir = tmp_path / "test_lance_db"
    db_dir.mkdir()
    return db_dir


@pytest.fixture()
def mock_chunks() -> list[dict]:
    """Generate deterministic mock code-chunk records.

    We use a fixed NumPy seed so that the embedding vectors are reproducible
    across runs, making assertions on search results stable.
    """
    rng = np.random.RandomState(42)
    chunks = [
        {
            "text": "def authenticate(user, password): ...",
            "vector": rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist(),
            "file_path": "src/auth/authenticator.py",
            "chunk_index": 0,
        },
        {
            "text": "class DatabaseManager:\n    def connect(self): ...",
            "vector": rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist(),
            "file_path": "src/database/manager.py",
            "chunk_index": 0,
        },
        {
            "text": "def get_user_by_id(user_id: int): ...",
            "vector": rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist(),
            "file_path": "src/database/manager.py",
            "chunk_index": 1,
        },
        {
            "text": "@app.route('/api/health')\ndef health_check(): return 'ok'",
            "vector": rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist(),
            "file_path": "src/api/endpoints.py",
            "chunk_index": 0,
        },
    ]
    return chunks


@pytest.fixture()
def populated_table(lance_tmp_dir: Path, mock_chunks: list[dict]):
    """Create a LanceDB table pre-populated with mock chunks.

    This fixture demonstrates the full lifecycle that the refactored
    ``CodeIndexManager`` will use:
        1. Connect to a local directory (no server, no creds).
        2. Create (or open) a table with the ``CodeChunkModel`` schema.
        3. Insert data — LanceDB accepts plain dicts, Pydantic instances,
           or Arrow tables.
    """
    # LanceDB connection is just a path — fully managed by our codebase.
    db = lancedb.connect(str(lance_tmp_dir))

    # ``create_table`` — we pass the schema explicitly to guarantee the
    # Arrow types match our Pydantic definition even when the input is a
    # list of plain dicts (LanceDB can infer types from dicts, but
    # explicit is better than implicit for schema-sensitive code).
    table = db.create_table("code_chunks", data=mock_chunks, schema=CodeChunkModel.to_arrow_schema())

    return table


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.lancedb
class TestCodeChunkSchema:
    """Validate the Pydantic LanceModel schema for code chunks."""

    def test_schema_fields_exist(self):
        """Verify all required fields are present in the schema."""
        field_names = {f for f in CodeChunkModel.model_fields}
        assert "text" in field_names, "Schema must include 'text'"
        assert "vector" in field_names, "Schema must include 'vector'"
        assert "file_path" in field_names, "Schema must include 'file_path'"
        assert "chunk_index" in field_names, "Schema must include 'chunk_index'"

    def test_vector_dimension_matches_qwen3(self):
        """The vector column must match the Qwen3-4B embedding dimension.

        This guards against accidental dimension mismatches that would cause
        silent failures when inserting real embeddings.
        """
        arrow_schema = CodeChunkModel.to_arrow_schema()
        vec_field = arrow_schema.field("vector")

        # LanceDB stores vectors as fixed-size lists of float32.
        assert pa.types.is_fixed_size_list(vec_field.type), (
            "vector column must be a FixedSizeList for ANN indexing"
        )
        assert vec_field.type.list_size == QWEN3_4B_EMBEDDING_DIM, (
            f"Expected vector dimension {QWEN3_4B_EMBEDDING_DIM}, "
            f"got {vec_field.type.list_size}"
        )

    def test_arrow_schema_roundtrip(self):
        """Pydantic model can produce a valid Arrow schema and back."""
        schema = CodeChunkModel.to_arrow_schema()
        assert isinstance(schema, pa.Schema)
        # Must contain all four user-defined columns.
        assert len(schema) >= 4


@pytest.mark.lancedb
class TestLanceDBTableOperations:
    """End-to-end tests for LanceDB table insert and vector search.

    These tests prove that the LanceDB storage layer works correctly
    *before* we refactor the core ``CodeIndexManager``.
    """

    def test_table_creation_and_row_count(self, populated_table, mock_chunks):
        """Inserting N mock chunks should produce N rows."""
        assert populated_table.count_rows() == len(mock_chunks)

    def test_vector_search_returns_dataframe(self, populated_table):
        """A vector search must return a Pandas DataFrame so downstream
        code can filter, sort, and display results easily.
        """
        # Build a random query vector with the correct dimension.
        rng = np.random.RandomState(99)
        query_vec = rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist()

        results = populated_table.search(query_vec).limit(2).to_pandas()

        assert isinstance(results, pd.DataFrame), "Search must return a DataFrame"
        assert len(results) <= 2, "Limit should cap the number of results"
        # The DataFrame must contain all schema columns plus the distance col.
        for col in ("text", "file_path", "chunk_index"):
            assert col in results.columns, f"Missing column '{col}' in results"

    def test_vector_search_distance_ordering(self, populated_table):
        """Results should be ordered by distance (nearest first)."""
        rng = np.random.RandomState(99)
        query_vec = rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist()

        results = populated_table.search(query_vec).limit(4).to_pandas()

        # LanceDB returns a "_distance" column by default (L2).
        assert "_distance" in results.columns, "Expected '_distance' column"
        distances = results["_distance"].tolist()
        assert distances == sorted(distances), "Results should be sorted by distance"

    def test_search_with_file_path_filter(self, populated_table):
        """Filtering by file_path should narrow the result set.

        This mirrors the filter logic the refactored indexer will use when
        a user restricts a search to a specific directory or file.
        """
        rng = np.random.RandomState(99)
        query_vec = rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist()

        results = (
            populated_table
            .search(query_vec)
            .where("file_path = 'src/database/manager.py'")
            .limit(10)
            .to_pandas()
        )

        # Only chunks from manager.py should survive the filter.
        assert len(results) > 0, "Filter should return at least one result"
        assert all(
            r == "src/database/manager.py" for r in results["file_path"]
        ), "All results must match the file_path filter"

    def test_delete_by_file_path(self, lance_tmp_dir, mock_chunks):
        """Row-level deletion by file_path is critical for incremental
        re-indexing: the Merkle DAG change detector identifies modified
        files, and we delete their stale chunks before inserting the
        updated ones.  FAISS could not do this without a full rebuild.
        """
        db = lancedb.connect(str(lance_tmp_dir))
        table = db.create_table(
            "delete_test",
            data=mock_chunks,
            schema=CodeChunkModel.to_arrow_schema(),
        )
        initial_count = table.count_rows()

        # Delete all chunks belonging to a specific file.
        table.delete("file_path = 'src/auth/authenticator.py'")

        assert table.count_rows() == initial_count - 1, (
            "Exactly one chunk should have been removed"
        )

        # Verify the correct file was deleted.
        remaining = table.to_pandas()
        assert "src/auth/authenticator.py" not in remaining["file_path"].values

    def test_upsert_workflow(self, lance_tmp_dir, mock_chunks):
        """Simulate the delete-then-insert upsert pattern the incremental
        indexer will use when a file changes on disk.

        Steps:
            1. Insert initial chunks.
            2. Delete chunks for the changed file.
            3. Insert updated chunks for that file.
            4. Verify total count and updated content.
        """
        db = lancedb.connect(str(lance_tmp_dir))
        table = db.create_table(
            "upsert_test",
            data=mock_chunks,
            schema=CodeChunkModel.to_arrow_schema(),
        )

        target_file = "src/api/endpoints.py"
        original_count = table.count_rows()

        # Step 1: delete old chunks for the changed file.
        table.delete(f"file_path = '{target_file}'")
        assert table.count_rows() == original_count - 1

        # Step 2: insert replacement chunks (simulating a file edit that
        # produced two chunks instead of the original one).
        rng = np.random.RandomState(123)
        new_chunks = [
            {
                "text": "@app.route('/api/health')\ndef health_check_v2(): return 'ok v2'",
                "vector": rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist(),
                "file_path": target_file,
                "chunk_index": 0,
            },
            {
                "text": "@app.route('/api/status')\ndef status(): return {'status': 'up'}",
                "vector": rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist(),
                "file_path": target_file,
                "chunk_index": 1,
            },
        ]
        table.add(new_chunks)

        # Net result: original 4 − 1 deleted + 2 new = 5
        assert table.count_rows() == original_count + 1
        api_chunks = table.to_pandas().query(f"file_path == '{target_file}'")
        assert len(api_chunks) == 2, "Updated file should have two chunks"


@pytest.mark.lancedb
class TestLanceDBLocalStorage:
    """Verify that LanceDB is truly embedded and serverless.

    These tests exist to confirm the "no credentials, no server" guarantee
    that makes agent-context-code easy to install and use.

    Storage philosophy
    ------------------
    All index data (vectors, metadata) is stored in a **centralised**
    directory (``~/.claude_code_search/`` by default, configurable via
    ``CODE_SEARCH_STORAGE``).  The user's project workspace is NEVER
    polluted with database files.  This mirrors the existing architecture
    where ``common_utils.get_storage_dir()`` returns the base path and
    projects are stored under ``<base>/projects/{name}_{hash}/``.

    LanceDB fits this perfectly because its "connection" is just a
    filesystem path — no server process, no Docker, no credentials.
    """

    def test_connect_creates_directory(self, tmp_path):
        """Connecting to a non-existent path should create the DB directory.

        This is the same behaviour the refactored ``CodeIndexManager`` will
        rely on — ``get_storage_dir()`` provides the path, and LanceDB
        creates it if needed.
        """
        db_path = tmp_path / "auto_created_db"
        db = lancedb.connect(str(db_path))
        # Creating a table forces the directory to materialise.
        rng = np.random.RandomState(0)
        db.create_table(
            "probe",
            data=[{
                "text": "probe",
                "vector": rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist(),
                "file_path": "probe.py",
                "chunk_index": 0,
            }],
            schema=CodeChunkModel.to_arrow_schema(),
        )
        assert db_path.exists(), "LanceDB should create the storage directory"

    def test_no_credentials_required(self, tmp_path):
        """LanceDB must not require any authentication for local use.

        Unlike client-server databases, the embedded LanceDB engine reads
        and writes files directly — no username, password, or connection
        URI with credentials.  This test simply confirms that a connect +
        table-create + search cycle succeeds with only a path.
        """
        db = lancedb.connect(str(tmp_path / "no_creds_db"))
        rng = np.random.RandomState(7)
        data = [{
            "text": "hello world",
            "vector": rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist(),
            "file_path": "hello.py",
            "chunk_index": 0,
        }]
        table = db.create_table("t", data=data, schema=CodeChunkModel.to_arrow_schema())
        results = table.search(data[0]["vector"]).limit(1).to_pandas()
        assert len(results) == 1, "Search should work without any credentials"

    def test_centralised_storage_keeps_workspace_clean(self, tmp_path):
        """Verify the centralised storage pattern: all database files live
        under a dedicated storage directory, NOT inside the user's project.

        This simulates how ``CodeIndexManager`` works at runtime:
            1. ``get_storage_dir()`` returns ``~/.claude_code_search/``
            2. The project DB is at
               ``<storage>/projects/<name>_<hash>/index/lancedb/``
            3. The user's actual project directory has ZERO database files

        This is a key usability requirement — other tools (e.g. code-index-mcp)
        store databases in the workspace itself, cluttering ``git status`` and
        requiring ``.gitignore`` entries.  We explicitly avoid that.

        Note: This test simulates the pattern using a simplified path
        (``my_project_abc123/lancedb/``) to validate that LanceDB creates
        files only inside the given directory.  The full runtime path with
        the ``index/`` sub-layer is covered by integration tests.
        """
        # Simulate a user workspace (should remain untouched).
        workspace = tmp_path / "my_project"
        workspace.mkdir()
        (workspace / "main.py").write_text("print('hello')")

        # Simulate the centralised storage location (managed by us).
        storage = tmp_path / "claude_code_search" / "projects" / "my_project_abc123"
        lance_dir = storage / "lancedb"
        lance_dir.mkdir(parents=True)

        # Open LanceDB in the storage dir, NOT the workspace.
        db = lancedb.connect(str(lance_dir))
        rng = np.random.RandomState(0)
        db.create_table(
            "code_chunks",
            data=[{
                "text": "print('hello')",
                "vector": rng.randn(QWEN3_4B_EMBEDDING_DIM).astype(np.float32).tolist(),
                "file_path": "main.py",
                "chunk_index": 0,
            }],
            schema=CodeChunkModel.to_arrow_schema(),
        )

        # The workspace must contain ONLY the original source file.
        workspace_files = list(workspace.iterdir())
        assert len(workspace_files) == 1, (
            f"Workspace should only contain main.py, got: {[f.name for f in workspace_files]}"
        )
        assert workspace_files[0].name == "main.py"

        # The storage dir should contain the LanceDB data.
        assert lance_dir.exists()
        assert any(lance_dir.iterdir()), "Storage dir should contain LanceDB data files"
