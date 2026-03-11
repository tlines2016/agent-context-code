"""Unit tests for graph/code_graph.CodeGraph."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from graph.code_graph import (
    CodeGraph,
    EDGE_CALLS,
    EDGE_CONTAINS,
    EDGE_IMPORTS,
    EDGE_INHERITS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def graph(tmp_path) -> CodeGraph:
    """Return a fresh CodeGraph backed by a temp SQLite DB."""
    db_path = tmp_path / "code_graph.db"
    return CodeGraph(str(db_path))


@pytest.fixture()
def populated_graph(graph) -> CodeGraph:
    """Graph pre-populated with a small class hierarchy.

    Structure:
        MyClass (class)
        ├── __init__ (method, parent=MyClass)
        └── do_work (method, parent=MyClass)
        helper_func (function)
        helper_func → do_work (calls)
    """
    graph.upsert_symbol("cls_1", "MyClass", "class", "/proj/a.py", 1, 20)
    graph.upsert_symbol("init_1", "__init__", "method", "/proj/a.py", 2, 5, parent_name="MyClass")
    graph.upsert_symbol("work_1", "do_work", "method", "/proj/a.py", 6, 15, parent_name="MyClass")
    graph.upsert_symbol("helper_1", "helper_func", "function", "/proj/b.py", 1, 10)

    # Edges
    graph.add_edge("cls_1", "init_1", EDGE_CONTAINS)
    graph.add_edge("cls_1", "work_1", EDGE_CONTAINS)
    graph.add_edge("helper_1", "work_1", EDGE_CALLS)
    graph.commit()
    return graph


# ---------------------------------------------------------------------------
# Schema and lifecycle
# ---------------------------------------------------------------------------

class TestSchemaAndLifecycle:

    def test_new_graph_is_empty(self, graph):
        stats = graph.get_stats()
        assert stats["total_symbols"] == 0
        assert stats["total_edges"] == 0

    def test_close_is_idempotent(self, graph):
        graph.close()
        graph.close()  # should not raise


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------

class TestSymbols:

    def test_upsert_symbol(self, graph):
        graph.upsert_symbol("s1", "foo", "function", "/a.py", 1, 10)
        graph.commit()
        sym = graph.get_symbol("s1")
        assert sym is not None
        assert sym["name"] == "foo"
        assert sym["symbol_type"] == "function"
        assert sym["file_path"] == "/a.py"

    def test_upsert_replaces_existing(self, graph):
        graph.upsert_symbol("s1", "foo", "function", "/a.py", 1, 10)
        graph.upsert_symbol("s1", "bar", "class", "/b.py", 5, 20)
        graph.commit()
        sym = graph.get_symbol("s1")
        assert sym["name"] == "bar"

    def test_get_file_symbols(self, populated_graph):
        syms = populated_graph.get_file_symbols("/proj/a.py")
        names = [s["name"] for s in syms]
        assert "MyClass" in names
        assert "__init__" in names

    def test_find_symbol_by_name(self, populated_graph):
        results = populated_graph.find_symbol_by_name("do_work")
        assert len(results) == 1
        assert results[0]["chunk_id"] == "work_1"

    def test_find_symbol_by_name_and_type(self, populated_graph):
        results = populated_graph.find_symbol_by_name("MyClass", symbol_type="class")
        assert len(results) == 1
        results = populated_graph.find_symbol_by_name("MyClass", symbol_type="function")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

class TestEdges:

    def test_add_edge(self, graph):
        graph.upsert_symbol("a", "A", "class", "/a.py", 1, 5)
        graph.upsert_symbol("b", "B", "class", "/b.py", 1, 5)
        graph.add_edge("a", "b", EDGE_INHERITS)
        graph.commit()
        rels = graph.get_relationships("a", direction="outgoing")
        assert len(rels) == 1
        assert rels[0]["edge_type"] == EDGE_INHERITS

    def test_duplicate_edge_is_ignored(self, graph):
        graph.upsert_symbol("a", "A", "class", "/a.py", 1, 5)
        graph.upsert_symbol("b", "B", "class", "/b.py", 1, 5)
        graph.add_edge("a", "b", EDGE_INHERITS)
        graph.add_edge("a", "b", EDGE_INHERITS)  # duplicate
        graph.commit()
        stats = graph.get_stats()
        assert stats["total_edges"] == 1

    def test_invalid_edge_type_is_skipped(self, graph):
        graph.add_edge("a", "b", "not_real")
        graph.commit()
        assert graph.get_stats()["total_edges"] == 0

    def test_get_callers(self, populated_graph):
        callers = populated_graph.get_callers("work_1")
        assert len(callers) == 1
        assert callers[0]["name"] == "helper_func"

    def test_get_callees(self, populated_graph):
        callees = populated_graph.get_callees("helper_1")
        assert len(callees) == 1
        assert callees[0]["name"] == "do_work"

    def test_get_children(self, populated_graph):
        children = populated_graph.get_children("cls_1")
        names = {c["name"] for c in children}
        assert names == {"__init__", "do_work"}


# ---------------------------------------------------------------------------
# File removal
# ---------------------------------------------------------------------------

class TestFileRemoval:

    def test_remove_file_deletes_symbols_and_edges(self, populated_graph):
        removed = populated_graph.remove_file("/proj/a.py")
        assert removed == 3  # MyClass, __init__, do_work

        # Symbols gone.
        assert populated_graph.get_symbol("cls_1") is None
        # Edges referencing those symbols gone.
        assert populated_graph.get_stats()["total_edges"] == 0

    def test_remove_nonexistent_file_returns_zero(self, graph):
        assert graph.remove_file("/does/not/exist.py") == 0


# ---------------------------------------------------------------------------
# Graph traversal
# ---------------------------------------------------------------------------

class TestGraphTraversal:

    def test_connected_subgraph(self, populated_graph):
        sg = populated_graph.get_connected_subgraph("cls_1", max_depth=1)
        # cls_1 has edges to init_1 and work_1 (contains), and
        # work_1 has an incoming edge from helper_1 (calls).
        # Depth 1 should include cls_1 + its direct neighbours.
        assert len(sg["symbols"]) >= 3
        assert len(sg["edges"]) >= 2

    def test_connected_subgraph_depth_zero(self, populated_graph):
        sg = populated_graph.get_connected_subgraph("helper_1", max_depth=0)
        # Depth 0 — only the seed symbol, no traversal.
        assert len(sg["symbols"]) == 1
        assert sg["symbols"][0]["chunk_id"] == "helper_1"

    def test_connected_subgraph_deep(self, populated_graph):
        sg = populated_graph.get_connected_subgraph("helper_1", max_depth=3)
        # Should reach all 4 symbols via helper→do_work→cls_1→__init__
        assert len(sg["symbols"]) == 4


# ---------------------------------------------------------------------------
# index_file_chunks integration
# ---------------------------------------------------------------------------

class TestIndexFileChunks:

    def _make_chunk(self, name, chunk_type, file_path, start_line, parent_name=None):
        """Minimal mock chunk with the attributes CodeGraph expects.
        
        Includes ``relative_path`` so ``_get_chunk_id`` can generate IDs
        that match the ``CodeEmbedder._make_chunk_id`` scheme.
        """
        class MockChunk:
            pass
        c = MockChunk()
        c.name = name
        c.chunk_type = chunk_type
        c.file_path = file_path
        c.relative_path = file_path  # mirrors embedder behaviour
        c.start_line = start_line
        c.end_line = start_line + 10
        c.parent_name = parent_name
        return c

    def test_index_file_creates_symbols_and_edges(self, graph):
        chunks = [
            self._make_chunk("Calculator", "class", "/proj/calc.py", 1),
            self._make_chunk("add", "method", "/proj/calc.py", 3, parent_name="Calculator"),
            self._make_chunk("subtract", "method", "/proj/calc.py", 8, parent_name="Calculator"),
        ]
        graph.index_file_chunks("/proj/calc.py", chunks)
        stats = graph.get_stats()
        assert stats["total_symbols"] == 3
        # "Calculator contains add" + "Calculator contains subtract"
        assert stats["total_edges"] == 2

    def test_reindex_replaces_old_data(self, graph):
        chunks = [self._make_chunk("foo", "function", "/proj/a.py", 1)]
        graph.index_file_chunks("/proj/a.py", chunks)
        assert graph.get_stats()["total_symbols"] == 1

        # Re-index with different content.
        chunks2 = [self._make_chunk("bar", "function", "/proj/a.py", 5)]
        graph.index_file_chunks("/proj/a.py", chunks2)
        stats = graph.get_stats()
        assert stats["total_symbols"] == 1
        syms = graph.get_file_symbols("/proj/a.py")
        assert syms[0]["name"] == "bar"


# ---------------------------------------------------------------------------
# Cross-file edge resolution
# ---------------------------------------------------------------------------

class TestCrossFileEdges:

    def test_resolve_cross_file_inherits(self, graph):
        # File A: BaseWidget (class)
        graph.upsert_symbol("base_1", "BaseWidget", "class", "/a.py", 1, 10)
        # File B: MyWidget (class, parent_name=BaseWidget)
        graph.upsert_symbol("my_1", "MyWidget", "class", "/b.py", 1, 10, parent_name="BaseWidget")
        graph.commit()

        new_edges = graph.resolve_cross_file_edges()
        assert new_edges == 1
        parents = graph.get_parent_classes("my_1")
        assert len(parents) == 1
        assert parents[0]["name"] == "BaseWidget"


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

class TestStats:

    def test_stats_populated(self, populated_graph):
        stats = populated_graph.get_stats()
        assert stats["total_symbols"] == 4
        assert stats["total_edges"] == 3
        assert "class" in stats["symbol_types"]
        assert EDGE_CONTAINS in stats["edge_types"]

    def test_clear(self, populated_graph):
        populated_graph.clear()
        stats = populated_graph.get_stats()
        assert stats["total_symbols"] == 0
        assert stats["total_edges"] == 0
