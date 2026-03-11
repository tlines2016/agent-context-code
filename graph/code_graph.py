"""SQLite-backed relational graph for code structure.

This module provides a lightweight graph database that stores structural
relationships between code entities extracted during AST-based indexing.
It complements the LanceDB vector index:

- **LanceDB** answers "what code is semantically similar to my query?"
- **CodeGraph** answers "how does that code connect to the rest of the
  codebase?" (callers, callees, parent classes, importers, etc.)

Schema design principles
------------------------
1. **Flat relational model** — a ``symbols`` table for nodes and an ``edges``
   table for relationships.  This is simpler than a dedicated graph DB and
   sufficient for the relationship types we track.
2. **File-level granularity for updates** — when a file is re-indexed, all
   its symbols and edges are deleted and re-inserted.  This mirrors the
   Merkle DAG incremental strategy used by the vector index.
3. **Chunk-ID alignment** — every symbol row stores the ``chunk_id`` used by
   LanceDB so that graph results can be joined to vector results in O(1).
4. **No external dependencies** — Python's built-in ``sqlite3`` module is
   the only requirement.

Edge types
----------
``imports``
    File A imports symbol from file B.
``calls``
    Function/method A calls function/method B (intra-file only for now;
    cross-file call resolution requires type inference beyond tree-sitter).
``inherits``
    Class A extends or implements class B.
``contains``
    Class A contains method B (parent→child relationship).
"""

import logging
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Edge type constants ──────────────────────────────────────────────────
EDGE_IMPORTS = "imports"
EDGE_CALLS = "calls"
EDGE_INHERITS = "inherits"
EDGE_CONTAINS = "contains"

VALID_EDGE_TYPES = {EDGE_IMPORTS, EDGE_CALLS, EDGE_INHERITS, EDGE_CONTAINS}


class CodeGraph:
    """SQLite-backed relational graph for code structure.

    Parameters
    ----------
    db_path : str or Path
        Path to the SQLite database file.  Created if it does not exist.
        Typically lives alongside the LanceDB index under the project
        storage directory (e.g. ``~/.claude_code_search/projects/foo_abc123/
        index/code_graph.db``).
    """

    def __init__(self, db_path: str):
        self._db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    # ── Connection management ────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Return (and cache) a SQLite connection.

        WAL mode is enabled for better concurrent read performance — the
        MCP server may search while an incremental re-index is running.
        """
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't already exist."""
        conn = self._get_conn()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Write operations ─────────────────────────────────────────────────

    def upsert_symbol(
        self,
        chunk_id: str,
        name: str,
        symbol_type: str,
        file_path: str,
        start_line: int,
        end_line: int,
        parent_name: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> None:
        """Insert or replace a symbol (function, class, method, …).

        Uses ``INSERT OR REPLACE`` keyed on ``chunk_id`` so that re-indexing
        a file naturally overwrites stale data.
        """
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO symbols
                (chunk_id, name, symbol_type, file_path, start_line,
                 end_line, parent_name, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (chunk_id, name, symbol_type, file_path, start_line,
             end_line, parent_name, metadata_json),
        )

    def add_edge(
        self,
        source_chunk_id: str,
        target_chunk_id: str,
        edge_type: str,
        metadata_json: Optional[str] = None,
    ) -> None:
        """Record a directed relationship between two symbols.

        Duplicate edges (same source + target + type) are silently ignored
        via ``INSERT OR IGNORE``.
        """
        if edge_type not in VALID_EDGE_TYPES:
            logger.warning("Unknown edge type '%s'; skipping", edge_type)
            return

        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR IGNORE INTO edges
                (source_chunk_id, target_chunk_id, edge_type, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (source_chunk_id, target_chunk_id, edge_type, metadata_json),
        )

    def remove_file(self, file_path: str) -> int:
        """Remove all symbols and edges for a given file.

        Called during incremental re-indexing when a file is modified or
        deleted.  Returns the number of symbols removed.

        Any edge whose source **or** target belonged to *file_path* is
        explicitly deleted before removing the corresponding symbols.
        """
        conn = self._get_conn()
        # Gather chunk_ids for the file so we can delete edges referencing them
        cursor = conn.execute(
            "SELECT chunk_id FROM symbols WHERE file_path = ?",
            (file_path,),
        )
        chunk_ids = [row["chunk_id"] for row in cursor.fetchall()]

        if not chunk_ids:
            return 0

        placeholders = ",".join("?" * len(chunk_ids))

        # Delete edges where this file's symbols are source or target.
        conn.execute(
            f"DELETE FROM edges WHERE source_chunk_id IN ({placeholders})"
            f" OR target_chunk_id IN ({placeholders})",
            chunk_ids + chunk_ids,
        )

        # Delete the symbols themselves.
        conn.execute(
            f"DELETE FROM symbols WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        )

        conn.commit()
        return len(chunk_ids)

    def commit(self) -> None:
        """Explicitly commit pending changes."""
        if self._conn is not None:
            self._conn.commit()

    def clear(self) -> None:
        """Delete all data (full re-index)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM edges")
        conn.execute("DELETE FROM symbols")
        conn.commit()

    # ── Read / query operations ──────────────────────────────────────────

    def get_symbol(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single symbol by its chunk_id."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM symbols WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_file_symbols(self, file_path: str) -> List[Dict[str, Any]]:
        """Return all symbols defined in *file_path*."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM symbols WHERE file_path = ? ORDER BY start_line",
            (file_path,),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_symbol_by_name(
        self,
        name: str,
        symbol_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find symbols matching *name* (exact, case-sensitive).

        Optionally filter by ``symbol_type`` (e.g. ``'function'``, ``'class'``).
        """
        conn = self._get_conn()
        if symbol_type:
            rows = conn.execute(
                "SELECT * FROM symbols WHERE name = ? AND symbol_type = ?",
                (name, symbol_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM symbols WHERE name = ?", (name,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_relationships(
        self,
        chunk_id: str,
        direction: str = "both",
        edge_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return edges connected to *chunk_id*.

        Parameters
        ----------
        chunk_id : str
            The symbol to query.
        direction : str
            ``"outgoing"``, ``"incoming"``, or ``"both"`` (default).
        edge_type : str, optional
            Filter to a specific edge type (e.g. ``"calls"``).
        """
        conn = self._get_conn()
        results: List[Dict[str, Any]] = []

        if direction in ("outgoing", "both"):
            sql = "SELECT * FROM edges WHERE source_chunk_id = ?"
            params: list = [chunk_id]
            if edge_type:
                sql += " AND edge_type = ?"
                params.append(edge_type)
            rows = conn.execute(sql, params).fetchall()
            results.extend(dict(r) for r in rows)

        if direction in ("incoming", "both"):
            sql = "SELECT * FROM edges WHERE target_chunk_id = ?"
            params = [chunk_id]
            if edge_type:
                sql += " AND edge_type = ?"
                params.append(edge_type)
            rows = conn.execute(sql, params).fetchall()
            results.extend(dict(r) for r in rows)

        return results

    def get_callers(self, chunk_id: str) -> List[Dict[str, Any]]:
        """Return symbols that *call* the given chunk."""
        edges = self.get_relationships(chunk_id, direction="incoming", edge_type=EDGE_CALLS)
        return self._resolve_symbols([e["source_chunk_id"] for e in edges])

    def get_callees(self, chunk_id: str) -> List[Dict[str, Any]]:
        """Return symbols that the given chunk *calls*."""
        edges = self.get_relationships(chunk_id, direction="outgoing", edge_type=EDGE_CALLS)
        return self._resolve_symbols([e["target_chunk_id"] for e in edges])

    def get_parent_classes(self, chunk_id: str) -> List[Dict[str, Any]]:
        """Return classes that the given class inherits from."""
        edges = self.get_relationships(chunk_id, direction="outgoing", edge_type=EDGE_INHERITS)
        return self._resolve_symbols([e["target_chunk_id"] for e in edges])

    def get_children(self, chunk_id: str) -> List[Dict[str, Any]]:
        """Return methods/properties contained in a class."""
        edges = self.get_relationships(chunk_id, direction="outgoing", edge_type=EDGE_CONTAINS)
        return self._resolve_symbols([e["target_chunk_id"] for e in edges])

    def get_importers(self, chunk_id: str) -> List[Dict[str, Any]]:
        """Return symbols that import the given symbol."""
        edges = self.get_relationships(chunk_id, direction="incoming", edge_type=EDGE_IMPORTS)
        return self._resolve_symbols([e["source_chunk_id"] for e in edges])

    # ── Graph traversal helpers ──────────────────────────────────────────

    def get_connected_subgraph(
        self,
        chunk_id: str,
        max_depth: int = 2,
    ) -> Dict[str, Any]:
        """Return a small neighbourhood around *chunk_id*.

        Does a breadth-first traversal up to *max_depth* hops from the seed
        symbol, collecting all reachable symbols and their connecting edges.
        Useful for providing "context" around a search result.

        Returns
        -------
        dict
            ``{"symbols": [...], "edges": [...]}`` where each symbol /
            edge is a dict.
        """
        visited_ids: set = set()
        frontier = {chunk_id}
        all_edges: List[Dict[str, Any]] = []

        # depth 0 = seed only; depth 1 = seed + direct neighbours; etc.
        for _ in range(max_depth + 1):
            if not frontier:
                break
            next_frontier: set = set()
            for cid in frontier:
                if cid in visited_ids:
                    continue
                visited_ids.add(cid)
                rels = self.get_relationships(cid, direction="both")
                for edge in rels:
                    all_edges.append(edge)
                    neighbour = (
                        edge["target_chunk_id"]
                        if edge["source_chunk_id"] == cid
                        else edge["source_chunk_id"]
                    )
                    if neighbour not in visited_ids:
                        next_frontier.add(neighbour)
            frontier = next_frontier

        # Resolve all visited symbols in one pass.
        symbols = self._resolve_symbols(list(visited_ids))

        # Deduplicate edges (same triple may appear from both ends).
        seen_edges: set = set()
        unique_edges: List[Dict[str, Any]] = []
        for e in all_edges:
            key = (e["source_chunk_id"], e["target_chunk_id"], e["edge_type"])
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(e)

        return {"symbols": symbols, "edges": unique_edges}

    # ── Index helper ────────────────────────────────────────────────────

    def index_file_chunks(
        self,
        file_path: str,
        chunks: list,
    ) -> None:
        """Extract symbols and intra-file relationships from parsed chunks.

        This is the primary entry point called by the indexing pipeline
        after tree-sitter has chunked a file.  It:

        1. Removes any stale symbols for *file_path*.
        2. Inserts a symbol row for each chunk that has a ``name``.
        3. Infers ``contains`` edges (class → method/property).
        4. Commits the transaction.

        Cross-file relationships (imports, inheritance) require a second
        pass after all files are indexed — see ``resolve_cross_file_edges``.
        """
        # Remove stale data for this file.
        self.remove_file(file_path)

        # Build a lookup of name → chunk_id for intra-file edge resolution.
        name_to_id: Dict[str, str] = {}
        chunk_id_from_chunk = _get_chunk_id  # local alias for speed

        for chunk in chunks:
            cid = chunk_id_from_chunk(chunk)
            if not cid:
                continue

            name = getattr(chunk, "name", None) or ""
            if not name:
                continue

            self.upsert_symbol(
                chunk_id=cid,
                name=name,
                symbol_type=getattr(chunk, "chunk_type", "unknown"),
                file_path=file_path,
                start_line=getattr(chunk, "start_line", 0),
                end_line=getattr(chunk, "end_line", 0),
                parent_name=getattr(chunk, "parent_name", None),
            )
            name_to_id[name] = cid

        # Infer ``contains`` edges: if a chunk has a ``parent_name`` and
        # that parent is also indexed in this file, create an edge.
        for chunk in chunks:
            cid = chunk_id_from_chunk(chunk)
            parent = getattr(chunk, "parent_name", None)
            if cid and parent and parent in name_to_id:
                self.add_edge(
                    source_chunk_id=name_to_id[parent],
                    target_chunk_id=cid,
                    edge_type=EDGE_CONTAINS,
                )

        self.commit()

    def resolve_cross_file_edges(self) -> int:
        """Infer import and inheritance edges across all indexed files.

        This should be called **after** all files have been indexed.  It
        scans every symbol and attempts to match:

        - ``parent_name`` → ``inherits`` edge to a class with that name.
        - (Future) import statements → ``imports`` edges.

        Returns the number of new edges actually created (duplicates excluded).
        """
        conn = self._get_conn()

        # Snapshot the current edge count so we can compute the true delta
        # after INSERT OR IGNORE (which silently skips duplicates).
        before_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        # Inheritance: symbol with parent_name → class with that name
        # in a *different* file.
        rows = conn.execute(
            """
            SELECT s1.chunk_id AS child_id,
                   s2.chunk_id AS parent_id
            FROM symbols s1
            JOIN symbols s2
              ON s1.parent_name = s2.name
             AND s1.file_path != s2.file_path
             AND s2.symbol_type IN ('class', 'interface', 'trait')
            WHERE s1.parent_name IS NOT NULL
              AND s1.parent_name != ''
            """
        ).fetchall()

        for row in rows:
            self.add_edge(
                source_chunk_id=row["child_id"],
                target_chunk_id=row["parent_id"],
                edge_type=EDGE_INHERITS,
            )

        self.commit()

        after_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return after_count - before_count

    # ── Statistics ───────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return graph size statistics."""
        conn = self._get_conn()
        symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        edge_count = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        # Breakdown by type.
        type_rows = conn.execute(
            "SELECT symbol_type, COUNT(*) as cnt FROM symbols GROUP BY symbol_type"
        ).fetchall()
        symbol_types = {r["symbol_type"]: r["cnt"] for r in type_rows}

        edge_rows = conn.execute(
            "SELECT edge_type, COUNT(*) as cnt FROM edges GROUP BY edge_type"
        ).fetchall()
        edge_types = {r["edge_type"]: r["cnt"] for r in edge_rows}

        return {
            "total_symbols": symbol_count,
            "total_edges": edge_count,
            "symbol_types": symbol_types,
            "edge_types": edge_types,
        }

    # ── Internal helpers ─────────────────────────────────────────────────

    def _resolve_symbols(self, chunk_ids: List[str]) -> List[Dict[str, Any]]:
        """Batch-fetch symbol rows for a list of chunk_ids."""
        if not chunk_ids:
            return []
        conn = self._get_conn()
        placeholders = ",".join("?" * len(chunk_ids))
        rows = conn.execute(
            f"SELECT * FROM symbols WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        ).fetchall()
        return [dict(r) for r in rows]


def _get_chunk_id(chunk) -> Optional[str]:
    """Build a chunk_id from a CodeChunk that matches ``CodeEmbedder._make_chunk_id``.

    The embedder builds IDs as ``relative_path:start-end:chunk_type[:name]``.
    We replicate that scheme here so graph symbols use the same IDs that
    end up in LanceDB, enabling O(1) joins between vector results and
    the relational graph.
    """
    relative_path = getattr(chunk, "relative_path", "") or ""
    start_line = getattr(chunk, "start_line", 0)
    end_line = getattr(chunk, "end_line", 0)
    chunk_type = getattr(chunk, "chunk_type", "")
    name = getattr(chunk, "name", None) or ""

    if not relative_path:
        return None

    chunk_id = f"{relative_path}:{start_line}-{end_line}:{chunk_type}"
    if name:
        chunk_id += f":{name}"
    return chunk_id


# ── SQL Schema ───────────────────────────────────────────────────────────
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS symbols (
    chunk_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    symbol_type   TEXT NOT NULL,       -- function, class, method, etc.
    file_path     TEXT NOT NULL,
    start_line    INTEGER NOT NULL DEFAULT 0,
    end_line      INTEGER NOT NULL DEFAULT 0,
    parent_name   TEXT,                -- enclosing class/module
    metadata_json TEXT                 -- extensible JSON blob
);

CREATE TABLE IF NOT EXISTS edges (
    source_chunk_id TEXT NOT NULL,
    target_chunk_id TEXT NOT NULL,
    edge_type       TEXT NOT NULL,     -- imports, calls, inherits, contains
    metadata_json   TEXT,
    PRIMARY KEY (source_chunk_id, target_chunk_id, edge_type)
);

-- Indexes for common query patterns.
CREATE INDEX IF NOT EXISTS idx_symbols_file
    ON symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_name
    ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_type
    ON symbols(symbol_type);
CREATE INDEX IF NOT EXISTS idx_edges_source
    ON edges(source_chunk_id);
CREATE INDEX IF NOT EXISTS idx_edges_target
    ON edges(target_chunk_id);
CREATE INDEX IF NOT EXISTS idx_edges_type
    ON edges(edge_type);
"""
