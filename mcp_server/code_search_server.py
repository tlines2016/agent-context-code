"""Code Search Server - manages code search state and business logic."""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from functools import lru_cache

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from common_utils import get_storage_dir, load_reranker_config
from chunking.multi_language_chunker import MultiLanguageChunker
from embeddings.embedder import CodeEmbedder
from search.indexer import CodeIndexManager
from search.searcher import IntelligentSearcher

# Configure logging
logger = logging.getLogger(__name__)


class CodeSearchServer:
    """Server that manages code search state and implements business logic."""

    def __init__(self):
        """Initialize the code search server."""
        # State management
        self._index_manager: Optional[CodeIndexManager] = None
        self._searcher: Optional[IntelligentSearcher] = None
        self._current_project: Optional[str] = None

    def get_project_storage_dir(self, project_path: str) -> Path:
        """Get or create project-specific storage directory."""
        base_dir = get_storage_dir()
        project_path_obj = Path(project_path).resolve()
        project_name = project_path_obj.name
        import hashlib
        project_hash = hashlib.md5(str(project_path_obj).encode()).hexdigest()[:8]

        # Use common utils for base directory
        project_dir = base_dir / "projects" / f"{project_name}_{project_hash}"
        project_dir.mkdir(parents=True, exist_ok=True)

        # Store project info
        project_info_file = project_dir / "project_info.json"
        if not project_info_file.exists():
            project_info = {
                "project_name": project_name,
                "project_path": str(project_path_obj),
                "project_hash": project_hash,
                "created_at": datetime.now().isoformat()
            }
            with open(project_info_file, 'w') as f:
                json.dump(project_info, f, indent=2)

        return project_dir

    def ensure_project_indexed(self, project_path: str) -> bool:
        """Check if project is indexed, auto-index if needed."""
        try:
            project_dir = self.get_project_storage_dir(project_path)
            index_dir = project_dir / "index"

            # Phase 3: check for LanceDB data directory (replaces the
            # old ``code.index`` FAISS file check).  Also accept the
            # legacy path for backward compatibility during migration.
            lance_dir = index_dir / "lancedb"
            if lance_dir.exists() and any(lance_dir.iterdir()):
                return True
            # Legacy FAISS check — kept for migration period.
            if index_dir.exists() and (index_dir / "code.index").exists():
                return True

            project_path_obj = Path(project_path)
            if project_path_obj == Path.cwd() and list(project_path_obj.glob("**/*.py")):
                logger.info(f"Auto-indexing current directory: {project_path}")
                result = self.index_directory(project_path)
                result_data = json.loads(result)
                return "error" not in result_data

            return False
        except Exception as e:
            logger.warning(f"Failed to check/auto-index project {project_path}: {e}")
            return False

    # @lru_cache on a bound method works here because CodeSearchServer is
    # effectively a singleton (one instance per MCP server process). The cache
    # is keyed on (self,) — since only one instance ever exists, maxsize=1 is
    # sufficient and there is no reference-cycle risk. This lazy-initialises
    # the embedder exactly once per process lifetime.
    @lru_cache(maxsize=1)
    def embedder(self) -> CodeEmbedder:
        """Lazy initialization of embedder."""
        cache_dir = get_storage_dir() / "models"
        cache_dir.mkdir(exist_ok=True)
        embedder = CodeEmbedder(cache_dir=str(cache_dir))
        logger.info("Embedder initialized")
        return embedder

    @lru_cache(maxsize=1)
    def reranker(self):
        """Lazy initialization of reranker.  Returns None when disabled."""
        config = load_reranker_config()
        if not config.get("enabled", False):
            logger.info("Reranker not enabled")
            return None

        model_name = config.get("model_name", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        try:
            from reranking.reranker import CodeReranker

            cache_dir = get_storage_dir() / "models"
            cache_dir.mkdir(exist_ok=True)
            reranker = CodeReranker(
                model_name=model_name,
                cache_dir=str(cache_dir),
            )
            logger.info("Reranker initialized: %s", model_name)
            return reranker
        except Exception as exc:
            logger.warning("Failed to initialize reranker: %s", exc)
            return None

    @lru_cache(maxsize=1)
    def _maybe_start_model_preload(self) -> None:
        """Preload the embedding model in the background."""
        async def _preload():
            try:
                logger.info("Starting background model preload")
                _ = self.embedder().model
                logger.info("Background model preload completed")
            except Exception as e:
                logger.warning(f"Background model preload failed: {e}")

        try:
            # Try to get the current event loop, handling the case where none exists
            try:
                loop = asyncio.get_running_loop()
                # If we're already in an event loop, create a task
                loop.create_task(_preload())
            except RuntimeError:
                # No running loop, so create one and run the coroutine
                asyncio.run(_preload())
        except Exception as e:
            logger.debug(f"Model preload scheduling skipped: {e}")
        return None

    def get_index_manager(self, project_path: str = None) -> CodeIndexManager:
        """Get index manager for specific or current project."""
        if project_path is None:
            if self._current_project is None:
                project_path = os.getcwd()
                logger.info(f"No active project. Using cwd: {project_path}")
                self.ensure_project_indexed(project_path)
            else:
                project_path = self._current_project

        if self._current_project != project_path:
            self._index_manager = None
            self._current_project = project_path

        if self._index_manager is None:
            project_dir = self.get_project_storage_dir(project_path)
            index_dir = project_dir / "index"
            index_dir.mkdir(exist_ok=True)
            self._index_manager = CodeIndexManager(str(index_dir))
            logger.info(f"Index manager initialized for: {Path(project_path).name}")

        return self._index_manager

    def get_searcher(self, project_path: str = None) -> IntelligentSearcher:
        """Get searcher for specific or current project."""
        if project_path is None and self._current_project is None:
            project_path = os.getcwd()
            logger.info(f"No active project. Using cwd: {project_path}")
            self.ensure_project_indexed(project_path)

        if self._current_project != project_path or self._searcher is None:
            reranker = self.reranker()
            reranker_config = load_reranker_config()
            recall_k = reranker_config.get("recall_k", 50)
            self._searcher = IntelligentSearcher(
                self.get_index_manager(project_path),
                self.embedder(),
                reranker=reranker,
                reranker_recall_k=recall_k,
            )
            logger.info(f"Searcher initialized for: {Path(self._current_project).name if self._current_project else 'unknown'}")

        return self._searcher

    def search_code(
        self,
        query: str,
        k: int = 5,
        search_mode: str = "auto",
        file_pattern: str = None,
        chunk_type: str = None,
        include_context: bool = True,
        auto_reindex: bool = True,
        max_age_minutes: float = 5,
        project_path: str = None,
    ) -> str:
        """Implementation of search_code tool."""
        try:
            if not query or not query.strip():
                return json.dumps({
                    "error": "Search query must not be empty.",
                    "suggestion": "Provide a natural language description of the code you are looking for, e.g. search_code('authentication logic')."
                })

            if k < 1 or k > 100:
                return json.dumps({
                    "error": f"k must be between 1 and 100 (got {k}).",
                    "suggestion": "Use a smaller value for k, e.g. search_code('query', k=10)."
                })

            logger.info(f"🔍 MCP REQUEST: search_code(query='{query}', k={k}, mode='{search_mode}', file_pattern={file_pattern}, chunk_type={chunk_type}, project_path={project_path})")

            # ── Cross-project search ─────────────────────────────────────────
            # When ``project_path`` is provided the search targets that project
            # without changing ``self._current_project``.  This lets an AI
            # agent query any indexed project while staying active in another.
            if project_path is not None:
                return self._search_project(
                    query=query,
                    project_path=str(Path(project_path).resolve()),
                    k=k,
                    search_mode=search_mode,
                    file_pattern=file_pattern,
                    chunk_type=chunk_type,
                    include_context=include_context,
                )

            if auto_reindex and self._current_project:
                from search.incremental_indexer import IncrementalIndexer

                logger.info(f"Checking if index needs refresh (max age: {max_age_minutes} minutes)")

                index_manager = self.get_index_manager(self._current_project)
                embedder = self.embedder()
                chunker = MultiLanguageChunker(self._current_project)

                incremental_indexer = IncrementalIndexer(
                    indexer=index_manager,
                    embedder=embedder,
                    chunker=chunker
                )

                reindex_result = incremental_indexer.auto_reindex_if_needed(
                    self._current_project,
                    max_age_minutes=max_age_minutes
                )

                if reindex_result.files_modified > 0 or reindex_result.files_added > 0:
                    logger.info(f"Auto-reindexed: {reindex_result.files_added} added, {reindex_result.files_modified} modified, took {reindex_result.time_taken:.2f}s")
                    self._searcher = None  # Reset to force reload

            searcher = self.get_searcher()
            logger.info(f"Current project: {self._current_project}")

            index_stats = searcher.index_manager.get_stats()
            logger.info(f"Index contains {index_stats.get('total_chunks', 0)} chunks")

            filters = {}
            if file_pattern:
                filters['file_pattern'] = [file_pattern]
            if chunk_type:
                filters['chunk_type'] = chunk_type

            logger.info(f"Search filters: {filters}")

            context_depth = 1 if include_context else 0
            logger.info(f"Calling searcher.search with query='{query}', k={k}, mode={search_mode}")
            results = searcher.search(
                query=query,
                k=k,
                search_mode=search_mode,
                context_depth=context_depth,
                filters=filters if filters else None
            )
            logger.info(f"Search returned {len(results)} results")

            formatted_results = [self._format_result(r) for r in results]

            response = {
                'query': query,
                'results': formatted_results
            }

            return json.dumps(response, separators=(",", ":"))
        except Exception as e:
            error_msg = f"Search failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            suggestion = "Ensure the project is indexed (use index_directory) and the embedding model is loaded."
            return json.dumps({"error": error_msg, "suggestion": suggestion})

    @staticmethod
    def _format_result(result) -> dict:
        """Build the wire-format dict for a single SearchResult.

        Centralises result serialisation so search_code() and _search_project()
        always produce an identical output shape.
        """
        item = {
            'file': result.relative_path,
            'lines': f"{result.start_line}-{result.end_line}",
            'kind': result.chunk_type,
            'score': round(result.similarity_score, 2),
            'chunk_id': result.chunk_id,
        }
        if result.name:
            item['name'] = result.name
        snippet = CodeSearchServer._make_snippet(result.content_preview)
        if snippet:
            item['snippet'] = snippet
        return item

    @staticmethod
    def _make_snippet(preview: Optional[str]) -> str:
        """Extract a one-line snippet from a content preview string."""
        if not preview:
            return ""
        for line in preview.split('\n'):
            s = line.strip()
            if s:
                snippet = ' '.join(s.split())
                return (snippet[:157] + '...') if len(snippet) > 160 else snippet
        return ""

    def _search_project(
        self,
        query: str,
        project_path: str,
        k: int = 5,
        search_mode: str = "auto",
        file_pattern: str = None,
        chunk_type: str = None,
        include_context: bool = True,
    ) -> str:
        """Run a search against any indexed project without changing active state.

        Used by ``search_code(project_path=...)`` to let an AI agent query a
        different workspace's index while remaining active in its own project.
        The caller's ``_current_project`` / ``_index_manager`` / ``_searcher``
        are never mutated.
        """
        # Build a transient index manager + searcher for the target project.
        # These local objects are garbage-collected when the method returns —
        # they are never assigned to self, so the caller's active project
        # state (_current_project / _index_manager / _searcher) is untouched.
        project_dir = self.get_project_storage_dir(project_path)
        index_dir = project_dir / "index"
        index_dir.mkdir(exist_ok=True)
        # CodeIndexManager is instantiated inline (not via get_index_manager)
        # intentionally: get_index_manager mutates self._current_project, which
        # would defeat the purpose of a context-free cross-project search.
        target_manager = CodeIndexManager(str(index_dir))

        if target_manager.get_index_size() == 0:
            return json.dumps({
                "error": f"Project not indexed: {project_path}",
                "suggestion": f"Run index_directory('{project_path}') first, then retry."
            })

        from search.searcher import IntelligentSearcher
        reranker = self.reranker()
        reranker_config = load_reranker_config()
        recall_k = reranker_config.get("recall_k", 50)
        target_searcher = IntelligentSearcher(
            target_manager,
            self.embedder(),
            reranker=reranker,
            reranker_recall_k=recall_k,
        )

        filters = {}
        if file_pattern:
            filters['file_pattern'] = [file_pattern]
        if chunk_type:
            filters['chunk_type'] = chunk_type

        context_depth = 1 if include_context else 0
        results = target_searcher.search(
            query=query,
            k=k,
            search_mode=search_mode,
            context_depth=context_depth,
            filters=filters if filters else None,
        )

        formatted_results = [self._format_result(r) for r in results]

        return json.dumps({
            'query': query,
            'project': project_path,
            'results': formatted_results,
        }, separators=(",", ":"))

    def index_directory(
        self,
        directory_path: str,
        project_name: str = None,
        file_patterns: List[str] = None,
        incremental: bool = True
    ) -> str:
        """Implementation of index_directory tool."""
        try:
            from search.incremental_indexer import IncrementalIndexer

            self._maybe_start_model_preload()

            directory_path = Path(directory_path).resolve()
            if not directory_path.exists():
                return json.dumps({
                    "error": f"Directory does not exist: {directory_path}",
                    "suggestion": "Check the path and ensure it is accessible. On Windows, use forward slashes or raw strings."
                })

            if not directory_path.is_dir():
                return json.dumps({
                    "error": f"Path is not a directory: {directory_path}",
                    "suggestion": "Provide a path to a directory, not a file."
                })

            project_name = project_name or directory_path.name
            logger.info(f"Indexing directory: {directory_path} (incremental={incremental})")

            index_manager = self.get_index_manager(str(directory_path))
            embedder = self.embedder()
            chunker = MultiLanguageChunker(str(directory_path))

            incremental_indexer = IncrementalIndexer(
                indexer=index_manager,
                embedder=embedder,
                chunker=chunker
            )

            result = incremental_indexer.incremental_index(
                str(directory_path),
                project_name,
                force_full=not incremental
            )

            stats = incremental_indexer.get_indexing_stats(str(directory_path))

            response = {
                "success": result.success,
                "directory": str(directory_path),
                "project_name": project_name,
                "incremental": incremental and result.files_modified > 0,
                "files_added": result.files_added,
                "files_removed": result.files_removed,
                "files_modified": result.files_modified,
                "chunks_added": result.chunks_added,
                "chunks_removed": result.chunks_removed,
                "time_taken": round(result.time_taken, 2),
                "index_stats": stats
            }

            if result.error:
                response["error"] = result.error

            logger.info(f"Indexing completed. Added: {result.files_added}, Modified: {result.files_modified}, Time: {result.time_taken:.2f}s")
            return json.dumps(response, indent=2)
        except Exception as e:
            error_msg = f"Indexing failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            suggestion = "Check that the directory is readable, dependencies are installed (uv sync), and the embedding model is available."
            return json.dumps({"error": error_msg, "suggestion": suggestion})

    def find_similar_code(self, chunk_id: str, k: int = 5) -> str:
        """Implementation of find_similar_code tool."""
        try:
            searcher = self.get_searcher()
            results = searcher.find_similar_to_chunk(chunk_id, k=k)

            formatted_results = []
            for result in results:
                formatted_results.append({
                    'file_path': result.relative_path,
                    'lines': f"{result.start_line}-{result.end_line}",
                    'chunk_type': result.chunk_type,
                    'name': result.name,
                    'similarity_score': round(result.similarity_score, 3),
                    'content_preview': result.content_preview,
                    'tags': result.tags
                })

            response = {
                'reference_chunk': chunk_id,
                'similar_chunks': formatted_results
            }

            return json.dumps(response, indent=2)
        except Exception as e:
            error_msg = f"Similar code search failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return json.dumps({"error": error_msg})

    def get_index_status(self) -> str:
        """Implementation of get_index_status tool.

        Returns index statistics including storage health metrics:
        version_count, storage_size_mb (from LanceDB table stats).
        """
        try:
            index_manager = self.get_index_manager()
            stats = index_manager.get_stats()

            model_info = self.embedder().get_model_info()

            response = {
                "index_statistics": stats,
                "model_information": model_info,
                "storage_directory": str(get_storage_dir()),
            }

            # Include reranker status
            reranker = self.reranker()
            if reranker is not None:
                response["reranker"] = reranker.get_model_info()
            else:
                reranker_cfg = load_reranker_config()
                response["reranker"] = {
                    "enabled": reranker_cfg.get("enabled", False),
                    "model_name": reranker_cfg.get("model_name"),
                    "loaded": False,
                }

            return json.dumps(response, indent=2)
        except Exception as e:
            error_msg = f"Status check failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return json.dumps({"error": error_msg})

    def list_projects(self) -> str:
        """Implementation of list_projects tool."""
        try:
            base_dir = get_storage_dir()
            projects_dir = base_dir / "projects"

            if not projects_dir.exists():
                return json.dumps({
                    "projects": [],
                    "count": 0,
                    "message": "No projects indexed yet"
                })

            projects = []
            for project_dir in projects_dir.iterdir():
                if project_dir.is_dir():
                    info_file = project_dir / "project_info.json"
                    if info_file.exists():
                        with open(info_file) as f:
                            project_info = json.load(f)

                        stats_file = project_dir / "index" / "stats.json"
                        if stats_file.exists():
                            with open(stats_file) as f:
                                stats = json.load(f)
                            project_info["index_stats"] = stats

                        projects.append(project_info)

            return json.dumps({
                "projects": projects,
                "count": len(projects),
                "current_project": self._current_project
            }, indent=2)
        except Exception as e:
            logger.error(f"Error listing projects: {e}")
            return json.dumps({"error": str(e)})

    def switch_project(self, project_path: str) -> str:
        """Implementation of switch_project tool."""
        try:
            project_path = Path(project_path).resolve()
            if not project_path.exists():
                return json.dumps({"error": f"Project path does not exist: {project_path}"})

            project_dir = self.get_project_storage_dir(str(project_path))
            index_dir = project_dir / "index"

            # Phase 3: check for LanceDB directory (replaces old FAISS
            # ``code.index`` check).  The project is considered indexed when
            # the LanceDB subdirectory exists and contains at least one file.
            lance_dir = index_dir / "lancedb"
            has_lancedb = lance_dir.exists() and any(lance_dir.iterdir())
            if not has_lancedb:
                return json.dumps({
                    "error": f"Project not indexed: {project_path}",
                    "suggestion": f"Run index_directory('{project_path}') first"
                })

            self._current_project = str(project_path)
            self._index_manager = None
            self._searcher = None

            info_file = project_dir / "project_info.json"
            project_info = {}
            if info_file.exists():
                with open(info_file) as f:
                    project_info = json.load(f)

            logger.info(f"Switched to project: {project_path.name}")

            return json.dumps({
                "success": True,
                "message": f"Switched to project: {project_path.name}",
                "project_info": project_info
            })
        except Exception as e:
            logger.error(f"Error switching project: {e}")
            return json.dumps({"error": str(e)})

    def index_test_project(self) -> str:
        """Implementation of index_test_project tool."""
        try:
            logger.info("Indexing built-in test project")

            server_dir = Path(__file__).parent
            test_project_path = server_dir.parent / "tests" / "test_data" / "python_project"

            if not test_project_path.exists():
                return json.dumps({
                    "success": False,
                    "error": "Test project not found. The sample project may not be available."
                })

            result = self.index_directory(str(test_project_path))
            result_data = json.loads(result)

            if "error" not in result_data:
                result_data["demo_info"] = {
                    "project_type": "Sample Python Project",
                    "includes": [
                        "Authentication module (user login, password hashing)",
                        "Database module (connections, queries, transactions)",
                        "API module (HTTP handlers, request validation)",
                        "Utilities (helpers, validation, configuration)"
                    ],
                    "sample_searches": [
                        "user authentication functions",
                        "database connection code",
                        "HTTP API handlers",
                        "input validation",
                        "error handling patterns"
                    ]
                }

            return json.dumps(result_data, indent=2)
        except Exception as e:
            logger.error(f"Error indexing test project: {e}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })

    def clear_index(self) -> str:
        """Implementation of clear_index tool."""
        try:
            if self._current_project is None:
                return json.dumps({"error": "No project is currently active. Use index_directory() to index a project first."})

            index_manager = self.get_index_manager()
            index_manager.clear_index()

            response = {
                "success": True,
                "message": "Search index cleared successfully"
            }

            logger.info("Search index cleared")
            return json.dumps(response, indent=2)
        except Exception as e:
            error_msg = f"Clear index failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return json.dumps({"error": error_msg})
