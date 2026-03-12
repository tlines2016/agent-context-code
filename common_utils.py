"""Common utilities shared across modules.

This is the lowest-level shared module in the project.  It provides:

- ``VERSION``: the single source of truth for the package version string.
- ``get_storage_dir()``: resolves and caches the storage root
  (``~/.agent_code_search`` or ``CODE_SEARCH_STORAGE``).
- ``load_local_install_config()`` / ``save_local_install_config()``:
  read/write the persisted model selection in ``install_config.json``.
- ``normalize_path()``: cross-platform path normalisation.

Every module that touches storage or config should go through these helpers
rather than computing paths ad-hoc, so that the ``CODE_SEARCH_STORAGE``
override and the ``{name}_{hash}`` project layout stay consistent.
"""

import json
import logging
import os
import platform
from pathlib import Path
from functools import lru_cache
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from importlib.metadata import version as _pkg_version, PackageNotFoundError
try:
    VERSION = _pkg_version("agent-context-local")
except PackageNotFoundError:
    VERSION = "0.0.0-dev"  # fallback for editable/source installs


def is_installed_package() -> bool:
    """True when running as a pip/uv-installed package, False for source checkout."""
    return VERSION != "0.0.0-dev"


def is_windows() -> bool:
    """Return True when running on native Windows (not WSL)."""
    return platform.system() == "Windows"


def normalize_path(path: str) -> str:
    """Normalize a file path for the current operating system.

    Converts forward/backward slashes to the OS-native separator and
    resolves ``~`` so that paths work on both Windows and Unix.
    """
    # Expand user home directory (works on all platforms)
    expanded = os.path.expanduser(path)
    # Normalize slashes and remove redundant separators
    return str(Path(expanded).resolve())


@lru_cache(maxsize=1)
def get_storage_dir() -> Path:
    """Get or create base storage directory. Cached for performance.

    The directory is chosen by the following priority:
    1. ``CODE_SEARCH_STORAGE`` environment variable (if set).
    2. ``~/.agent_code_search`` (works on all platforms – ``~`` expands
       to ``%USERPROFILE%`` on Windows and ``$HOME`` on Unix).
    """
    raw_path = os.getenv('CODE_SEARCH_STORAGE', '')
    if raw_path:
        storage_dir = Path(os.path.expanduser(raw_path)).resolve()
    else:
        legacy_path = Path.home() / '.claude_code_search'
        storage_dir = Path.home() / '.agent_code_search'
        # Preserve compatibility for existing installs that still have the
        # legacy folder name and no explicit CODE_SEARCH_STORAGE override.
        if legacy_path.exists() and not storage_dir.exists():
            try:
                legacy_path.rename(storage_dir)
                logger.info("Migrated storage from %s to %s", legacy_path, storage_dir)
            except OSError as exc:
                logger.warning(
                    "Could not migrate legacy storage from %s to %s: %s. "
                    "Continuing to use legacy path.",
                    legacy_path,
                    storage_dir,
                    exc,
                )
                storage_dir = legacy_path
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Cannot create storage directory '{storage_dir}': {exc}\n"
            "Set CODE_SEARCH_STORAGE to a writable path and try again."
        ) from exc

    # Restrict directory permissions to the owning user on Unix/macOS.
    # The index stores full source code in the 'content' column, so on
    # shared machines other users should not be able to read it.
    # Windows default ACLs already restrict to the creating user.
    if os.name != 'nt':
        try:
            os.chmod(storage_dir, 0o700)
        except OSError:
            pass  # Best-effort; don't fail if permissions can't be set.

    return storage_dir


def get_install_config_path(storage_dir: Optional[Path] = None) -> Path:
    """Get the persisted local installation config path."""
    return (storage_dir or get_storage_dir()) / "install_config.json"


def load_local_install_config(storage_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Load the local installation config if present.

    Returns an empty dict when the file does not exist or cannot be parsed,
    and logs a warning on parse errors so users have visibility.
    """
    config_path = get_install_config_path(storage_dir)
    if not config_path.exists():
        return {}

    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning(
            "Corrupt install config at %s: %s – using defaults", config_path, exc
        )
        return {}
    except OSError as exc:
        logger.warning(
            "Cannot read install config at %s: %s – using defaults", config_path, exc
        )
        return {}


def save_local_install_config(
    model_name: str,
    storage_dir: Optional[Path] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> Path:
    """Persist the selected embedding model for the local installation.

    Merges the new ``model_name`` into the existing config's
    ``embedding_model`` dict (preserving any extra keys like
    ``embedding_dimension``).  If *overrides* is provided, those key/value
    pairs are written into the same ``embedding_model`` block.

    Returns the path to the written config file.
    """
    target_storage_dir = storage_dir or get_storage_dir()
    target_storage_dir.mkdir(parents=True, exist_ok=True)

    config = load_local_install_config(target_storage_dir)
    existing_embedding_config = config.get("embedding_model")
    if isinstance(existing_embedding_config, dict):
        embedding_config: Dict[str, Any] = dict(existing_embedding_config)
    else:
        embedding_config = {}

    embedding_config["model_name"] = model_name
    if overrides:
        for key, value in overrides.items():
            if isinstance(value, str):
                if value:
                    embedding_config[key] = value
            elif value is not None:
                embedding_config[key] = value

    config["embedding_model"] = embedding_config

    config_path = get_install_config_path(target_storage_dir)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config_path


def load_reranker_config(storage_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Load the reranker section from install_config.json.

    Returns an empty dict when no reranker config is present or the file
    cannot be read.  This mirrors the load_local_install_config pattern.
    """
    config = load_local_install_config(storage_dir)
    return config.get("reranker", {})


def save_reranker_config(
    model_name: str,
    enabled: bool = False,
    recall_k: int = 50,
    storage_dir: Optional[Path] = None,
) -> Path:
    """Persist reranker configuration into install_config.json.

    Merges the reranker settings into the existing config file, preserving
    all other keys (e.g. ``embedding_model``).

    Returns the path to the written config file.
    """
    target_storage_dir = storage_dir or get_storage_dir()
    target_storage_dir.mkdir(parents=True, exist_ok=True)

    config = load_local_install_config(target_storage_dir)
    config["reranker"] = {
        "model_name": model_name,
        "enabled": enabled,
        "recall_k": recall_k,
    }

    config_path = get_install_config_path(target_storage_dir)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config_path
