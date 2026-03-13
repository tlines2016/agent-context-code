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

import hashlib
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


def get_project_lock_path(project_path: str) -> Path:
    """Return the file-lock path for a given project.

    The lock file lives inside the per-project storage directory at
    ``<storage>/projects/{name}_{hash}/.indexing.lock``.

    The hash derivation mirrors ``CodeSearchServer._project_storage_key()``
    but is duplicated here to avoid a circular import (``common_utils`` is
    the lowest-level module).
    """
    resolved = Path(project_path).resolve()
    project_name = resolved.name
    project_hash = hashlib.md5(str(resolved).encode()).hexdigest()[:8]
    project_dir = get_storage_dir() / "projects" / f"{project_name}_{project_hash}"
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir / ".indexing.lock"


def get_embedding_lock_path() -> Path:
    """Return the system-wide embedding lock path.

    Only one full-index operation should run at a time to avoid doubling
    RAM/VRAM usage from concurrent model loads.  The lock file is at
    ``<storage>/.embedding.lock``.
    """
    return get_storage_dir() / ".embedding.lock"


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


def detect_gpu_index_url() -> tuple[str, str | None, str | None, str | None]:
    """Detect GPU hardware and return the matching PyTorch index URL.

    Returns ``(vendor, version, gpu_name, index_url)`` where *vendor* is one
    of ``"nvidia"``, ``"amd"``, ``"mps"``, or ``"cpu"``.  *index_url* is the
    ``https://download.pytorch.org/whl/...`` URL for the best matching GPU
    build, or ``None`` when no GPU-specific index is needed (MPS, CPU, or
    unsupported hardware).

    This function does NOT import ``torch`` — it shells out to ``nvidia-smi``
    / ``rocminfo`` so it works even when only CPU torch is installed.
    """
    import re
    import shutil
    import subprocess

    # Apple Silicon — MPS is included in the standard PyTorch macOS build
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return ("mps", None, "Apple Silicon", None)

    # NVIDIA
    if shutil.which("nvidia-smi"):
        gpu_name = "unknown"
        cuda_ver = None
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                gpu_name = result.stdout.strip().splitlines()[0]
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["nvidia-smi"], capture_output=True, text=True, timeout=5,
            )
            m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", result.stdout)
            if m:
                major, minor = int(m.group(1)), int(m.group(2))
                cuda_ver = f"{major}.{minor}"
                if major >= 13 or (major == 12 and minor >= 8):
                    url = "https://download.pytorch.org/whl/cu128"
                elif major == 12 and minor >= 6:
                    url = "https://download.pytorch.org/whl/cu126"
                elif major == 12 and minor >= 4:
                    url = "https://download.pytorch.org/whl/cu124"
                elif major == 12:
                    url = "https://download.pytorch.org/whl/cu121"
                elif major == 11 and minor >= 8:
                    url = "https://download.pytorch.org/whl/cu118"
                else:
                    url = None
                return ("nvidia", cuda_ver, gpu_name, url)
        except Exception:
            pass
        return ("nvidia", cuda_ver, gpu_name, None)

    # AMD ROCm
    if shutil.which("rocminfo") or shutil.which("rocm-smi"):
        gpu_name = "unknown"
        rocm_ver = None
        # Parse ROCm version
        if shutil.which("rocminfo"):
            try:
                result = subprocess.run(
                    ["rocminfo"], capture_output=True, text=True, timeout=5,
                )
                m = re.search(r"HSA Runtime Version:\s*(\d+\.\d+)", result.stdout)
                if m:
                    rocm_ver = m.group(1)
            except Exception:
                pass
        if rocm_ver is None and shutil.which("rocm-smi"):
            try:
                result = subprocess.run(
                    ["rocm-smi", "--showdriverversion"],
                    capture_output=True, text=True, timeout=5,
                )
                m = re.search(r"(\d+\.\d+)", result.stdout)
                if m:
                    rocm_ver = m.group(1)
            except Exception:
                pass
        # GPU name
        try:
            result = subprocess.run(
                ["rocm-smi", "--showproductname"],
                capture_output=True, text=True, timeout=5,
            )
            m = re.search(r"GPU\[\d+\]\s*:\s*(.*)", result.stdout)
            if m:
                gpu_name = m.group(1).strip()
        except Exception:
            pass
        # Map ROCm version to PyTorch index URL
        url: str | None = None
        if rocm_ver:
            parts = rocm_ver.split(".")
            rocm_major = int(parts[0])
            rocm_minor = int(parts[1]) if len(parts) > 1 else 0
            if rocm_major >= 7 and rocm_minor >= 1:
                url = "https://download.pytorch.org/whl/rocm7.1"
            elif rocm_major >= 7 or (rocm_major == 6 and rocm_minor >= 2):
                url = "https://download.pytorch.org/whl/rocm6.2.4"
            elif rocm_major == 6:
                url = "https://download.pytorch.org/whl/rocm6.1"
            # ROCm < 6.0 → no compatible PyTorch wheels, url stays None
        else:
            # ROCm tools found but version unknown — try latest stable
            url = "https://download.pytorch.org/whl/rocm7.1"
        return ("amd", rocm_ver, gpu_name, url)

    return ("cpu", None, None, None)


def detect_gpu() -> str:
    """Detect the best available compute device.

    Returns ``"cuda"`` (NVIDIA / AMD ROCm via HIP), ``"mps"`` (Apple
    Silicon), or ``"cpu"``.  Safe to call even when PyTorch is not
    installed — falls back to ``"cpu"`` on ImportError.
    """
    try:
        import torch
    except ImportError:
        return "cpu"

    if torch.cuda.is_available():
        return "cuda"
    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def has_explicit_model_choice(storage_dir: Optional[Path] = None) -> bool:
    """Check whether the user has explicitly configured an embedding model.

    Returns True when ``install_config.json`` contains an
    ``embedding_model`` key (string or dict with ``model_name``).
    """
    config = load_local_install_config(storage_dir)
    em = config.get("embedding_model")
    if em is None:
        return False
    if isinstance(em, str):
        return bool(em.strip())
    if isinstance(em, dict):
        return bool(em.get("model_name", "").strip())
    return False


def has_explicit_reranker_choice(storage_dir: Optional[Path] = None) -> bool:
    """Check whether the user has explicitly configured a reranker.

    Returns True when ``install_config.json`` contains a ``reranker``
    key with an ``enabled`` field that is not None.
    """
    config = load_local_install_config(storage_dir)
    rr = config.get("reranker")
    if not isinstance(rr, dict):
        return False
    return "enabled" in rr


def load_reranker_config(storage_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Load the reranker section from install_config.json.

    Returns an empty dict when no reranker config is present or the file
    cannot be read.  This mirrors the load_local_install_config pattern.
    """
    config = load_local_install_config(storage_dir)
    reranker_config = config.get("reranker", {})
    # Older or manually edited configs may contain a non-dict "reranker"
    # value; normalize to {} so downstream .get() callers remain safe.
    return reranker_config if isinstance(reranker_config, dict) else {}


def save_reranker_config(
    model_name: str,
    enabled: bool = False,
    recall_k: int = 50,
    storage_dir: Optional[Path] = None,
    min_reranker_score: float = 0.0,
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
        "min_reranker_score": min_reranker_score,
    }

    config_path = get_install_config_path(target_storage_dir)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config_path
