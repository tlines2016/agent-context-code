"""Incremental indexing using Merkle tree change detection.

Integrates a SQLite relational graph (``CodeGraph``) alongside the LanceDB
vector index.  When a ``code_graph`` is provided, parsed chunks are fed
into the graph so that structural relationships (class hierarchies,
function containment, cross-file inheritance) are available for
graph-enriched search results.
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from merkle.change_detector import ChangeDetector, FileChanges
from merkle.ignore_rules import IgnoreRules
from merkle.merkle_dag import MerkleDAG
from merkle.snapshot_manager import SnapshotManager
from chunking.multi_language_chunker import MultiLanguageChunker
from embeddings.embedder import CodeEmbedder
from search.indexer import CodeIndexManager as Indexer

logger = logging.getLogger(__name__)


@dataclass
class IncrementalIndexResult:
    """Result of incremental indexing operation."""

    files_added: int
    files_removed: int
    files_modified: int
    chunks_added: int
    chunks_removed: int
    time_taken: float
    success: bool
    error: Optional[str] = None
    skipped_files: List[Dict] = field(default_factory=list)
    graph_stats: Dict = field(default_factory=dict)
    graph_sync_ok: bool = True
    graph_sync_error: Optional[str] = None
    ignore_stats: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        result = {
            'files_added': self.files_added,
            'files_removed': self.files_removed,
            'files_modified': self.files_modified,
            'chunks_added': self.chunks_added,
            'chunks_removed': self.chunks_removed,
            'time_taken': self.time_taken,
            'success': self.success,
            'error': self.error,
            'graph_sync_ok': self.graph_sync_ok,
        }
        if self.skipped_files:
            result['skipped_files'] = self.skipped_files
            result['skipped_file_count'] = len(self.skipped_files)
        if self.graph_sync_error:
            result['graph_sync_error'] = self.graph_sync_error
        if self.graph_stats:
            result['graph_stats'] = self.graph_stats
        if self.ignore_stats:
            result['ignore_stats'] = self.ignore_stats
        return result


@dataclass
class AddChunksResult:
    """Outcome details from chunk/embed/index add stage."""

    chunks_added: int
    chunking_errors: List[str] = field(default_factory=list)
    embedding_error: Optional[str] = None
    graph_index_errors: List[str] = field(default_factory=list)
    skipped_files: List[Dict] = field(default_factory=list)


class IncrementalIndexer:
    """Handles incremental indexing of code changes.
    
    When a ``code_graph`` is provided, parsed chunks are also fed into the
    SQLite relational graph for structural relationship tracking.  The
    graph is optional — when *None*, behaviour is identical to the original
    vector-only pipeline.
    """
    
    def __init__(
        self,
        indexer: Optional[Indexer] = None,
        embedder: Optional[CodeEmbedder] = None,
        chunker: Optional[MultiLanguageChunker] = None,
        snapshot_manager: Optional[SnapshotManager] = None,
        code_graph=None,
    ):
        """Initialize incremental indexer.
        
        Args:
            indexer: Indexer instance
            embedder: Embedder instance
            chunker: Code chunker instance
            snapshot_manager: Snapshot manager instance
            code_graph: Optional CodeGraph instance for structural
                        relationship tracking alongside vector embeddings.
        """
        self.indexer = indexer or Indexer()
        self.embedder = embedder or CodeEmbedder()
        self.chunker = chunker or MultiLanguageChunker()
        self.snapshot_manager = snapshot_manager or SnapshotManager()
        self.change_detector = ChangeDetector(self.snapshot_manager)
        self.code_graph = code_graph
    
    def detect_changes(self, project_path: str) -> Tuple[FileChanges, MerkleDAG]:
        """Detect changes in project since last snapshot.
        
        Args:
            project_path: Path to project
            
        Returns:
            Tuple of (FileChanges, current MerkleDAG)
        """
        return self.change_detector.detect_changes_from_snapshot(project_path)
    
    def incremental_index(
        self,
        project_path: str,
        project_name: Optional[str] = None,
        force_full: bool = False
    ) -> IncrementalIndexResult:
        """Perform incremental indexing of a project.
        
        Args:
            project_path: Path to project
            project_name: Optional project name
            force_full: Force full reindex even if snapshot exists
            
        Returns:
            IncrementalIndexResult with statistics
        """
        start_time = time.time()
        project_path = str(Path(project_path).resolve())
        
        if not project_name:
            project_name = Path(project_path).name

        indexing_config = self.chunker.get_indexing_config_signature()

        # Merge ignore-file signatures so .gitignore/.cursorignore changes
        # trigger a full reindex via the existing config comparison.
        ignore_sig = IgnoreRules.compute_signature(Path(project_path))
        indexing_config = {**(indexing_config or {}), "ignore_signature": ignore_sig}

        try:
            # Check if we should do full index
            if force_full or not self.snapshot_manager.has_snapshot(project_path):
                logger.info(f"Performing full index for {project_name}")
                return self._full_index(project_path, project_name, start_time, indexing_config)

            snapshot_metadata = self.snapshot_manager.load_metadata(project_path) or {}
            if snapshot_metadata.get('indexing_config') != indexing_config:
                logger.info(
                    "Indexing configuration changed for %s; performing a full reindex to remove stale chunks.",
                    project_name,
                )
                return self._full_index(project_path, project_name, start_time, indexing_config)
            
            # Detect changes
            logger.info(f"Detecting changes in {project_name}")
            changes, current_dag = self.detect_changes(project_path)
            ignore_stats = current_dag.get_ignore_stats()

            if not changes.has_changes():
                logger.info(f"No changes detected in {project_name}")
                return IncrementalIndexResult(
                    files_added=0,
                    files_removed=0,
                    files_modified=0,
                    chunks_added=0,
                    chunks_removed=0,
                    time_taken=time.time() - start_time,
                    success=True,
                    ignore_stats=ignore_stats,
                )
            
            # Log changes
            logger.info(
                f"Changes detected - Added: {len(changes.added)}, "
                f"Removed: {len(changes.removed)}, Modified: {len(changes.modified)}"
            )
            
            # Process changes
            chunks_removed = self._remove_old_chunks(changes, project_name, project_path)
            add_result = self._add_new_chunks(changes, project_path, project_name)
            # Keep compatibility with tests/mocks that still return an int.
            if isinstance(add_result, int):
                add_result = AddChunksResult(chunks_added=add_result)
            chunks_added = add_result.chunks_added

            graph_stats = {}
            graph_sync_ok = True
            graph_sync_error = None
            index_sync_ok = True
            index_sync_errors: List[str] = []

            if add_result.chunking_errors:
                index_sync_ok = False
                index_sync_errors.append(
                    f"Chunking failed for {len(add_result.chunking_errors)} file(s)"
                )
            if add_result.embedding_error:
                index_sync_ok = False
                index_sync_errors.append(f"Embedding failed: {add_result.embedding_error}")
            if add_result.graph_index_errors:
                graph_sync_ok = False
                graph_sync_error = f"Graph indexing failed for {len(add_result.graph_index_errors)} file(s)"

            if self.code_graph is not None:
                try:
                    # Incremental updates can invalidate cross-file links
                    # (e.g. inheritance), so reconcile after add/remove steps.
                    cross_edges = self.code_graph.resolve_cross_file_edges()
                    logger.info(
                        "Incremental graph reconciliation added %d cross-file edges",
                        cross_edges,
                    )
                    graph_stats = self.code_graph.get_stats()
                except Exception as exc:
                    graph_sync_ok = False
                    graph_sync_error = str(exc)
                    logger.warning("Incremental graph reconciliation failed: %s", exc)

            sync_ok = index_sync_ok and graph_sync_ok
            sync_errors = []
            if index_sync_errors:
                sync_errors.extend(index_sync_errors)
            if graph_sync_error:
                sync_errors.append(f"Graph sync failed: {graph_sync_error}")

            # Only advance the snapshot when all required stores succeeded.
            if sync_ok:
                self.snapshot_manager.save_snapshot(current_dag, {
                    'project_name': project_name,
                    'incremental_update': True,
                    'files_added': len(changes.added),
                    'files_removed': len(changes.removed),
                    'files_modified': len(changes.modified),
                    'indexing_config': indexing_config,
                })
            else:
                logger.warning(
                    "Snapshot not advanced for %s due to stage failures: %s",
                    project_name,
                    "; ".join(sync_errors) if sync_errors else "unknown",
                )

            # Update index
            self.indexer.set_indexing_config(indexing_config)
            self.indexer.save_index()

            # Compact fragments and clean up old versions created by
            # the add/delete operations above.
            self.indexer.optimize()

            return IncrementalIndexResult(
                files_added=len(changes.added),
                files_removed=len(changes.removed),
                files_modified=len(changes.modified),
                chunks_added=chunks_added,
                chunks_removed=chunks_removed,
                time_taken=time.time() - start_time,
                success=sync_ok,
                error="; ".join(sync_errors) if sync_errors else None,
                skipped_files=add_result.skipped_files,
                graph_stats=graph_stats,
                graph_sync_ok=graph_sync_ok,
                graph_sync_error=graph_sync_error,
                ignore_stats=ignore_stats,
            )
            
        except Exception as e:
            logger.error(f"Incremental indexing failed: {e}")
            return IncrementalIndexResult(
                files_added=0,
                files_removed=0,
                files_modified=0,
                chunks_added=0,
                chunks_removed=0,
                time_taken=time.time() - start_time,
                success=False,
                error=str(e)
            )
    
    def _full_index(
        self,
        project_path: str,
        project_name: str,
        start_time: float,
        indexing_config: Optional[Dict] = None,
    ) -> IncrementalIndexResult:
        """Perform full indexing of a project.
        
        Args:
            project_path: Path to project
            project_name: Project name
            start_time: Start time for timing
            
        Returns:
            IncrementalIndexResult
        """
        try:
            # Clear existing index
            self.indexer.clear_index()
            self.indexer.set_indexing_config(indexing_config)
            
            # Clear the graph if present (full re-index).
            if self.code_graph is not None:
                self.code_graph.clear()
            
            # Build DAG for all files
            dag = MerkleDAG(project_path)
            dag.build()
            ignore_stats = dag.get_ignore_stats()
            all_files = dag.get_all_files()
            
            # Filter supported files
            supported_files = [f for f in all_files if self.chunker.is_supported(f)]
            
            # Reset skipped files tracking before each session.
            self.chunker.reset_skipped_files()

            # Collect all chunks first, then embed in a single pass for efficiency
            all_chunks = []
            chunking_errors: List[str] = []
            graph_file_errors: List[str] = []
            for file_path in supported_files:
                full_path = str(Path(project_path) / file_path)
                try:
                    chunks = self.chunker.chunk_file(full_path)
                    if chunks:
                        all_chunks.extend(chunks)
                        # Populate the relational graph when available.
                        if self.code_graph is not None:
                            try:
                                self.code_graph.index_file_chunks(full_path, chunks)
                            except Exception as exc:
                                graph_file_errors.append(f"{file_path}: {exc}")
                                logger.warning("Graph indexing failed for %s: %s", file_path, exc)
                except Exception as e:
                    chunking_errors.append(f"{file_path}: {e}")
                    logger.warning(f"Failed to chunk {file_path}: {e}")

            # Embed all chunks in one batched call
            all_embedding_results = []
            embedding_error = None
            if all_chunks:
                try:
                    all_embedding_results = self.embedder.embed_chunks(all_chunks)
                    # Update metadata
                    for chunk, embedding_result in zip(all_chunks, all_embedding_results):
                        embedding_result.metadata['project_name'] = project_name
                        embedding_result.metadata['content'] = chunk.content
                except Exception as e:
                    embedding_error = str(e)
                    logger.warning(f"Embedding failed: {e}")
            
            # Add all embeddings to index at once
            if all_embedding_results:
                self.indexer.add_embeddings(all_embedding_results)
            
            chunks_added = len(all_embedding_results)

            # Resolve cross-file edges in the graph after all files are
            # indexed (inheritance across files, etc.).
            graph_sync_ok = True
            graph_sync_error = None
            index_sync_ok = True
            index_sync_errors: List[str] = []
            if chunking_errors:
                index_sync_ok = False
                index_sync_errors.append(f"Chunking failed for {len(chunking_errors)} file(s)")
            if embedding_error:
                index_sync_ok = False
                index_sync_errors.append(f"Embedding failed: {embedding_error}")
            if self.code_graph is not None:
                if graph_file_errors:
                    graph_sync_ok = False
                    graph_sync_error = f"Graph indexing failed for {len(graph_file_errors)} file(s)"
                try:
                    cross_edges = self.code_graph.resolve_cross_file_edges()
                    logger.info("Resolved %d cross-file graph edges", cross_edges)
                except Exception as e:
                    graph_sync_ok = False
                    graph_sync_error = str(e)
                    logger.warning("Cross-file graph resolution failed: %s", e)

            sync_ok = index_sync_ok and graph_sync_ok
            sync_errors = []
            if index_sync_errors:
                sync_errors.extend(index_sync_errors)
            if graph_sync_error:
                sync_errors.append(f"Graph sync failed: {graph_sync_error}")

            # Only advance the snapshot when all required stores succeeded.
            if sync_ok:
                self.snapshot_manager.save_snapshot(dag, {
                    'project_name': project_name,
                    'full_index': True,
                    'total_files': len(all_files),
                    'supported_files': len(supported_files),
                    'chunks_indexed': chunks_added,
                    'indexing_config': indexing_config or {},
                })
            else:
                logger.warning(
                    "Snapshot not advanced for %s due to stage failures: %s",
                    project_name,
                    "; ".join(sync_errors) if sync_errors else "unknown",
                )

            # Save index
            self.indexer.save_index()

            # Compact fragments and clean up old versions.
            self.indexer.optimize()

            graph_stats = (
                self.code_graph.get_stats()
                if self.code_graph is not None
                else {}
            )

            skipped = list(self.chunker.skipped_files)
            if skipped:
                total_skipped_bytes = sum(f.get("size_bytes", 0) for f in skipped)
                logger.warning(
                    "%d structured file(s) skipped (total %s bytes)",
                    len(skipped),
                    total_skipped_bytes,
                )

            return IncrementalIndexResult(
                files_added=len(supported_files),
                files_removed=0,
                files_modified=0,
                chunks_added=chunks_added,
                chunks_removed=0,
                time_taken=time.time() - start_time,
                success=sync_ok,
                error="; ".join(sync_errors) if sync_errors else None,
                skipped_files=skipped,
                graph_stats=graph_stats,
                graph_sync_ok=graph_sync_ok,
                graph_sync_error=graph_sync_error,
                ignore_stats=ignore_stats,
            )

        except Exception as e:
            logger.error(f"Full indexing failed: {e}")
            return IncrementalIndexResult(
                files_added=0,
                files_removed=0,
                files_modified=0,
                chunks_added=0,
                chunks_removed=0,
                time_taken=time.time() - start_time,
                success=False,
                error=str(e)
            )
    
    def _remove_old_chunks(
        self,
        changes: FileChanges,
        project_name: str,
        project_path: str,
    ) -> int:
        """Remove chunks for deleted and modified files.
        
        Also removes symbols/edges from the code graph when present.
        
        Args:
            changes: File changes
            project_name: Project name
            project_path: Project root path, used to reconstruct the absolute
                          path form that was stored during indexing.
            
        Returns:
            Number of chunks removed
        """
        files_to_remove = self.change_detector.get_files_to_remove(changes)
        chunks_removed = 0
        
        for file_path in files_to_remove:
            # Remove from vector index.
            removed = self.indexer.remove_file_chunks(file_path, project_name)
            chunks_removed += removed
            logger.debug(f"Removed {removed} chunks from {file_path}")

            # Remove from relational graph when available.
            # Construct the same absolute path form used during indexing:
            # index_file_chunks is called with str(Path(project_path) / file_path).
            if self.code_graph is not None:
                graph_file_path = str(Path(project_path) / file_path)
                try:
                    self.code_graph.remove_file(graph_file_path)
                except Exception as exc:
                    logger.warning("Graph removal failed for %s: %s", graph_file_path, exc)
        
        return chunks_removed
    
    def _add_new_chunks(
        self,
        changes: FileChanges,
        project_path: str,
        project_name: str
    ) -> AddChunksResult:
        """Add chunks for new and modified files.
        
        Also populates the relational graph when a ``code_graph`` is available.
        
        Args:
            changes: File changes
            project_path: Project root path
            project_name: Project name
            
        Returns:
            Number of chunks added
        """
        files_to_index = self.change_detector.get_files_to_reindex(changes)

        # Reset skipped files tracking before each session.
        self.chunker.reset_skipped_files()

        # Filter supported files
        supported_files = [f for f in files_to_index if self.chunker.is_supported(f)]

        # Collect all chunks first, then embed in a single pass
        chunks_to_embed = []
        chunking_errors: List[str] = []
        graph_index_errors: List[str] = []
        for file_path in supported_files:
            full_path = str(Path(project_path) / file_path)
            try:
                chunks = self.chunker.chunk_file(full_path)
                if chunks:
                    chunks_to_embed.extend(chunks)
                    # Populate the relational graph when available.
                    if self.code_graph is not None:
                        try:
                            self.code_graph.index_file_chunks(full_path, chunks)
                        except Exception as exc:
                            graph_index_errors.append(f"{file_path}: {exc}")
                            logger.warning("Graph indexing failed for %s: %s", file_path, exc)
            except Exception as e:
                chunking_errors.append(f"{file_path}: {e}")
                logger.warning(f"Failed to chunk {file_path}: {e}")

        all_embedding_results = []
        embedding_error = None
        if chunks_to_embed:
            try:
                all_embedding_results = self.embedder.embed_chunks(chunks_to_embed)
                # Update metadata
                for chunk, embedding_result in zip(chunks_to_embed, all_embedding_results):
                    embedding_result.metadata['project_name'] = project_name
                    embedding_result.metadata['content'] = chunk.content
            except Exception as e:
                embedding_error = str(e)
                logger.warning(f"Embedding failed: {e}")
        
        # Add all embeddings to index at once
        if all_embedding_results:
            self.indexer.add_embeddings(all_embedding_results)
        
        return AddChunksResult(
            chunks_added=len(all_embedding_results),
            chunking_errors=chunking_errors,
            embedding_error=embedding_error,
            graph_index_errors=graph_index_errors,
            skipped_files=list(self.chunker.skipped_files),
        )
    
    
    def get_indexing_stats(self, project_path: str) -> Optional[Dict]:
        """Get indexing statistics for a project.
        
        Args:
            project_path: Path to project
            
        Returns:
            Dictionary with statistics or None
        """
        metadata = self.snapshot_manager.load_metadata(project_path)
        if not metadata:
            return None
        
        # Add current index stats
        metadata['current_chunks'] = self.indexer.get_index_size()
        metadata['snapshot_age'] = self.snapshot_manager.get_snapshot_age(project_path)
        
        return metadata
    
    def needs_reindex(self, project_path: str, max_age_minutes: float = 5) -> bool:
        """Check if a project needs reindexing.
        
        Args:
            project_path: Path to project
            max_age_minutes: Maximum age of snapshot in minutes (default 5)
            
        Returns:
            True if reindex is needed
        """
        # No snapshot means needs index
        if not self.snapshot_manager.has_snapshot(project_path):
            return True
        
        # Check snapshot age (convert minutes to seconds)
        age = self.snapshot_manager.get_snapshot_age(project_path)
        if age and age > max_age_minutes * 60:
            return True
        
        # Quick check for changes
        return self.change_detector.quick_check(project_path)
    
    def auto_reindex_if_needed(self, project_path: str, project_name: Optional[str] = None, 
                              max_age_minutes: float = 5) -> IncrementalIndexResult:
        """Automatically reindex if the index is stale.
        
        Args:
            project_path: Path to project
            project_name: Optional project name
            max_age_minutes: Maximum age before auto-reindex (default 5 minutes)
            
        Returns:
            IncrementalIndexResult with statistics
        """
        import time
        start_time = time.time()
        
        if self.needs_reindex(project_path, max_age_minutes):
            logger.info(f"Auto-reindexing {project_path} (index older than {max_age_minutes} minutes)")
            return self.incremental_index(project_path, project_name)
        else:
            logger.debug(f"Index for {project_path} is fresh, skipping reindex")
            return IncrementalIndexResult(
                files_added=0,
                files_removed=0,
                files_modified=0,
                chunks_added=0,
                chunks_removed=0,
                time_taken=time.time() - start_time,
                success=True
            )
