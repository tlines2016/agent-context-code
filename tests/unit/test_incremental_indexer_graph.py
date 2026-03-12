"""Unit tests for IncrementalIndexer graph reconciliation behavior."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from merkle.change_detector import FileChanges
from search.incremental_indexer import IncrementalIndexer


def _make_indexer_with_mocks():
    indexer = MagicMock()
    embedder = MagicMock()
    chunker = MagicMock()
    chunker.get_indexing_config_signature.return_value = {"sig": "1"}
    snapshot_manager = MagicMock()
    snapshot_manager.has_snapshot.return_value = True
    snapshot_manager.load_metadata.return_value = {
        "indexing_config": {
            "sig": "1",
            "ignore_signature": {"gitignore_hash": None, "cursorignore_hash": None},
        }
    }
    code_graph = MagicMock()

    inc = IncrementalIndexer(
        indexer=indexer,
        embedder=embedder,
        chunker=chunker,
        snapshot_manager=snapshot_manager,
        code_graph=code_graph,
    )
    return inc, indexer, snapshot_manager, code_graph


class TestIncrementalGraphReconciliation:
    def test_reconciles_cross_file_edges_after_incremental_changes(self):
        inc, indexer, snapshot_manager, code_graph = _make_indexer_with_mocks()

        changes = FileChanges(
            added=["new.py"],
            removed=[],
            modified=["child.py"],
            unchanged=[],
        )

        with patch.object(inc, "detect_changes", return_value=(changes, MagicMock())), \
             patch.object(inc, "_remove_old_chunks", return_value=2), \
             patch.object(inc, "_add_new_chunks", return_value=5):
            result = inc.incremental_index("/project/path", project_name="proj")

        assert result.success is True
        code_graph.resolve_cross_file_edges.assert_called_once()
        code_graph.get_stats.assert_called_once()
        indexer.save_index.assert_called_once()
        indexer.optimize.assert_called_once()
        snapshot_manager.save_snapshot.assert_called_once()

    def test_skips_graph_reconciliation_when_no_changes(self):
        inc, _, snapshot_manager, code_graph = _make_indexer_with_mocks()
        changes = FileChanges(added=[], removed=[], modified=[], unchanged=["same.py"])

        with patch.object(inc, "detect_changes", return_value=(changes, MagicMock())):
            result = inc.incremental_index("/project/path", project_name="proj")

        assert result.success is True
        code_graph.resolve_cross_file_edges.assert_not_called()
        snapshot_manager.save_snapshot.assert_not_called()
