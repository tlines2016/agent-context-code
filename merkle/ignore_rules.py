"""Ignore-rule engine for MerkleDAG file discovery.

Layers hardcoded patterns, root .gitignore, nested per-directory .gitignore
files, and root .cursorignore through a single ``pathspec``-based matcher.
"""

import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

import pathspec

logger = logging.getLogger(__name__)

# Hardcoded fallback patterns expressed in gitignore syntax so they can be
# compiled by pathspec alongside user-authored ignore files.
HARDCODED_IGNORE_PATTERNS: List[str] = [
    # VCS
    ".git/",
    ".hg/",
    ".svn/",
    # Python virtualenvs
    ".venv/",
    "venv/",
    "env/",
    ".env/",
    ".direnv/",
    # JS / Node
    "node_modules/",
    ".pnpm-store/",
    ".yarn/",
    # Python caches
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".pytype/",
    ".ipynb_checkpoints/",
    # Build outputs
    "build/",
    "dist/",
    "out/",
    "public/",
    # JS framework caches
    ".next/",
    ".nuxt/",
    ".svelte-kit/",
    ".angular/",
    ".astro/",
    ".vite/",
    # Generic caches
    ".cache/",
    ".parcel-cache/",
    ".turbo/",
    # Coverage
    "coverage/",
    ".coverage/",
    ".nyc_output/",
    # IDE / tooling
    ".gradle/",
    ".idea/",
    ".vscode/",
    ".docusaurus/",
    ".vercel/",
    ".serverless/",
    ".terraform/",
    ".mvn/",
    ".tox/",
    # Compiled output dirs
    "target/",
    "bin/",
    "obj/",
    # File-level patterns
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "Thumbs.db",
]


def _hash_file_content(path: Path) -> Optional[str]:
    """Return SHA-256 hex digest of a file, or None if unreadable."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, IOError):
        return None


def _load_pathspec(path: Path) -> Optional[pathspec.PathSpec]:
    """Load a gitignore-style file into a PathSpec, or None if missing."""
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        return pathspec.PathSpec.from_lines("gitwildmatch", text.splitlines())
    except (OSError, IOError):
        return None


class IgnoreRules:
    """Layered ignore-rule engine.

    Precedence (checked in order, first match wins):
    1. Hardcoded fallback patterns (always active)
    2. Dynamic runtime patterns (snapshot dir exclusion added by ChangeDetector)
    3. Root ``.gitignore`` rules
    4. Nested per-directory ``.gitignore`` rules
    5. Root ``.cursorignore`` rules
    """

    def __init__(self, root_path: Path):
        self._root = root_path.resolve()

        # Compile hardcoded patterns
        self._hardcoded_spec = pathspec.PathSpec.from_lines(
            "gitwildmatch", HARDCODED_IGNORE_PATTERNS
        )

        # Root-level ignore files
        self._gitignore_spec = _load_pathspec(self._root / ".gitignore")
        self._cursorignore_spec = _load_pathspec(self._root / ".cursorignore")

        # Stack of (directory_relative_path, PathSpec) for nested .gitignore
        self._nested_stack: List[tuple] = []

        # Counters
        self._ignored_by_hardcoded = 0
        self._ignored_by_gitignore = 0
        self._ignored_by_cursorignore = 0

    # ------------------------------------------------------------------
    # Nested .gitignore scope management
    # ------------------------------------------------------------------

    def enter_directory(self, dir_path: Path) -> None:
        """Push a nested .gitignore scope if one exists in *dir_path*."""
        if dir_path == self._root:
            return  # root gitignore already loaded separately
        gitignore_path = dir_path / ".gitignore"
        spec = _load_pathspec(gitignore_path)
        if spec is not None:
            try:
                rel = dir_path.relative_to(self._root)
                rel_str = str(rel).replace("\\", "/")
            except ValueError:
                rel_str = ""
            self._nested_stack.append((rel_str, spec))

    def leave_directory(self, dir_path: Path) -> None:
        """Pop the nested .gitignore scope for *dir_path*, if one was pushed."""
        if dir_path == self._root:
            return
        if not self._nested_stack:
            return
        try:
            rel = dir_path.relative_to(self._root)
            rel_str = str(rel).replace("\\", "/")
        except ValueError:
            return
        if self._nested_stack[-1][0] == rel_str:
            self._nested_stack.pop()

    # ------------------------------------------------------------------
    # Core matching
    # ------------------------------------------------------------------

    def should_ignore(self, path: Path, relative_path: str) -> bool:
        """Return True if *path* should be excluded from the DAG.

        Parameters
        ----------
        path : Path
            Absolute path being tested.
        relative_path : str
            Forward-slash relative path from the project root, with a
            trailing ``/`` appended for directories.
        """
        # 1. Hardcoded patterns
        if self._hardcoded_spec.match_file(relative_path):
            self._ignored_by_hardcoded += 1
            return True

        # 2. Root .gitignore
        if self._gitignore_spec is not None and self._gitignore_spec.match_file(relative_path):
            self._ignored_by_gitignore += 1
            return True

        # 3. Nested .gitignore (walk the stack top-down)
        for scope_rel, spec in reversed(self._nested_stack):
            # Nested rules only apply to paths within their directory scope
            if scope_rel and relative_path.startswith(scope_rel + "/"):
                local_rel = relative_path[len(scope_rel) + 1:]
                if spec.match_file(local_rel):
                    self._ignored_by_gitignore += 1
                    return True

        # 4. Root .cursorignore
        if self._cursorignore_spec is not None and self._cursorignore_spec.match_file(relative_path):
            self._ignored_by_cursorignore += 1
            return True

        return False

    # ------------------------------------------------------------------
    # Signature & stats
    # ------------------------------------------------------------------

    def get_ignore_signature(self) -> Dict[str, Optional[str]]:
        """Return content hashes of ignore files for cache invalidation."""
        return {
            "gitignore_hash": _hash_file_content(self._root / ".gitignore"),
            "cursorignore_hash": _hash_file_content(self._root / ".cursorignore"),
        }

    @staticmethod
    def compute_signature(root_path: Path) -> Dict[str, Optional[str]]:
        """Cheap signature computation without building full PathSpec objects."""
        root = root_path.resolve()
        return {
            "gitignore_hash": _hash_file_content(root / ".gitignore"),
            "cursorignore_hash": _hash_file_content(root / ".cursorignore"),
        }

    def get_stats(self) -> Dict:
        """Return ignore counters for reporting."""
        return {
            "ignored_by_hardcoded": self._ignored_by_hardcoded,
            "ignored_by_gitignore": self._ignored_by_gitignore,
            "ignored_by_cursorignore": self._ignored_by_cursorignore,
            "total_ignored": (
                self._ignored_by_hardcoded
                + self._ignored_by_gitignore
                + self._ignored_by_cursorignore
            ),
        }
