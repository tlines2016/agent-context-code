#!/usr/bin/env python3
"""Command-line interface for AGENT Context Local.

Provides help, diagnostics, and management commands for the local
semantic code search system.

Entry point: ``python scripts/cli.py <command>``

Architecture note
-----------------
This module is intentionally self-contained. It imports only ``common_utils``
from the project (for VERSION, storage helpers) and stdlib modules. Heavy
dependencies like ``sentence_transformers`` or ``lancedb`` are checked via
``importlib.import_module`` inside ``cmd_doctor`` so the CLI itself can run
even when the venv is incomplete — which is exactly the scenario where
``doctor`` is most useful.

Key conventions:
- Colour output degrades gracefully when stdout is not a tty (or ``NO_COLOR``
  is set), so CI/piped output stays clean.
- All sub-commands are registered in the ``COMMANDS`` dict near the bottom of
  the file.  Adding a new command means writing a ``cmd_<name>`` function and
  adding one entry to that dict.
- Platform detection helpers (``is_windows``, ``is_wsl``, ``get_platform_label``)
  are shared by multiple commands and by the test suite.
"""

import json
import importlib
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

try:
    from common_utils import (
        VERSION,
        is_installed_package,
        get_storage_dir,
        load_local_install_config,
        save_local_install_config,
        load_reranker_config,
        save_reranker_config,
        save_idle_config,
        detect_gpu_index_url,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common_utils import (
        VERSION,
        is_installed_package,
        get_storage_dir,
        load_local_install_config,
        save_local_install_config,
        load_reranker_config,
        save_reranker_config,
        save_idle_config,
        detect_gpu_index_url,
    )

INSTALL_SH_URL = "https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh"
INSTALL_PS1_URL = "https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1"

# Lazy import — embeddings package may not be importable when venv is incomplete
# (e.g. first run of `doctor` before `uv sync`).  The fallback keeps setup-guide
# and troubleshoot functional even without a complete environment.
try:
    from embeddings.model_catalog import DEFAULT_EMBEDDING_MODEL as _DEFAULT_EMBEDDING_MODEL
except ImportError:
    _DEFAULT_EMBEDDING_MODEL = "mixedbread-ai/mxbai-embed-xsmall-v1"

# Models that require a HuggingFace account, license acceptance, and auth
# token to download. Referenced by setup-guide and models sub-commands.
GATED_MODELS: frozenset[str] = frozenset({"google/embeddinggemma-300m"})

# ── Ensure UTF-8 output on Windows ────────────────────────────────────
# Windows terminals default to cp1252 which can't render Unicode symbols
# (✓, ✗, ℹ, etc.).  Reconfigure stdout/stderr to UTF-8 with replacement
# fallback so we never crash on encoding errors.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── Colour helpers (degrade gracefully when stdout is not a terminal) ──

_NO_COLOR = os.environ.get("NO_COLOR") or not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty()


def _clr(code: str, text: str) -> str:
    """Apply ANSI colour code to *text*, returning plain text when colour is disabled."""
    return text if _NO_COLOR else f"\033[{code}m{text}\033[0m"


def bold(text: str) -> str:
    return _clr("1", text)


def green(text: str) -> str:
    return _clr("32", text)


def yellow(text: str) -> str:
    return _clr("33", text)


def red(text: str) -> str:
    return _clr("31", text)


def cyan(text: str) -> str:
    return _clr("36", text)


def _get_storage_dir_or_report(command_name: str) -> Optional[Path]:
    """Return the storage directory or print actionable guidance."""
    try:
        return get_storage_dir()
    except RuntimeError as exc:
        print(f"{red('✗')} {command_name} could not access the storage directory.")
        print(f"  {exc}")
        if "CODE_SEARCH_STORAGE" not in str(exc):
            print(f"  Set {cyan('CODE_SEARCH_STORAGE')} to a writable path and try again.")
        print()
        return None


# ── Platform helpers ──────────────────────────────────────────────────

def is_windows() -> bool:
    return platform.system() == "Windows"


def is_wsl() -> bool:
    """Detect if running inside WSL."""
    if platform.system() != "Linux":
        return False
    try:
        release = Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
        return "microsoft" in release or "wsl" in release
    except OSError:
        return False


def get_platform_label() -> str:
    system = platform.system()
    if is_wsl():
        return "WSL2 (Windows Subsystem for Linux)"
    return {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(system, system)


def _gpu_extra_flag() -> str:
    """Return ``--extra <name> `` if a GPU extra is configured, else ``""``."""
    try:
        config = load_local_install_config()
        extra = config.get("gpu", {}).get("extra", "")
        if extra:
            return f"--extra {extra} "
    except Exception:
        pass
    return ""


def _is_ui_entry_point_installed() -> bool:
    """True when ``agent-context-local-ui`` resolves to a binary *outside* this source checkout.

    Uses path-based detection rather than package metadata because
    ``is_installed_package()`` returns True even for an editable/source-checkout
    install where the version is set in ``pyproject.toml``.
    """
    bin_path = shutil.which("agent-context-local-ui")
    if not bin_path:
        return False
    repo_root = Path(__file__).resolve().parent.parent
    try:
        Path(bin_path).resolve().relative_to(repo_root)
        return False  # binary is inside the source-checkout venv
    except ValueError:
        return True   # binary lives outside → proper uv-tool / pip install


def _cmd_prefix() -> str:
    """CLI command prefix appropriate for install mode."""
    if is_installed_package() and shutil.which("agent-context-local"):
        return "agent-context-local"
    install_dir = get_default_install_dir()
    extra_flag = _gpu_extra_flag()
    if is_windows():
        return f'uv run {extra_flag}--directory "{install_dir}" python scripts/cli.py'
    return f"uv run {extra_flag}--directory {install_dir} python scripts/cli.py"


def _mcp_server_cmd() -> str:
    """MCP server command appropriate for install mode.

    Reads ``install_config.json`` to include ``--extra`` when a GPU
    extra is configured, so ``uv run`` resolves GPU PyTorch automatically.
    """
    if is_installed_package() and shutil.which("agent-context-local-mcp"):
        return "agent-context-local-mcp"
    install_dir = get_default_install_dir()
    extra_flag = _gpu_extra_flag()
    if is_windows():
        return f'uv run {extra_flag}--directory "{install_dir}" python mcp_server/server.py'
    return f"uv run {extra_flag}--directory {install_dir} python mcp_server/server.py"


def get_default_install_dir() -> Path:
    """Return the expected installation directory for this platform.

    - Windows: ``%LOCALAPPDATA%\\agent-context-code``
    - macOS/Linux: ``~/.local/share/agent-context-code``

    This must stay in sync with the ``PROJECT_DIR`` / ``$ProjectDir`` variables
    in ``scripts/install.sh`` and ``scripts/install.ps1``.
    """
    if is_windows():
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            return Path(local_app) / "agent-context-code"
        return Path.home() / "AppData" / "Local" / "agent-context-code"
    return Path.home() / ".local" / "share" / "agent-context-code"


def get_claude_config_paths() -> list:
    """Return likely Claude Desktop configuration file paths for this platform.

    Checks platform-appropriate locations for ``claude_desktop_config.json``
    and the legacy ``~/.claude.json``.  When running in WSL, also probes the
    Windows-side ``AppData`` path so ``doctor`` can report cross-environment
    config state.
    """
    paths = []
    home = Path.home()

    if is_windows():
        # Windows: AppData paths
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            paths.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        if localappdata:
            paths.append(Path(localappdata) / "Claude" / "claude_desktop_config.json")
        paths.append(home / ".claude.json")
    elif platform.system() == "Darwin":
        paths.append(home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
        paths.append(home / ".claude.json")
    else:
        # Linux/WSL
        xdg_config = os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))
        paths.append(Path(xdg_config) / "Claude" / "claude_desktop_config.json")
        paths.append(home / ".claude.json")

    if is_wsl():
        # Also check Windows-side paths from WSL
        for win_user_dir in _wsl_windows_user_dirs():
            paths.append(win_user_dir / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json")

    return paths


def _wsl_windows_user_dirs() -> list:
    """Attempt to find Windows user directories from within WSL."""
    dirs = []
    # /mnt/c/Users/<username> is the typical WSL mount
    users_dir = Path("/mnt/c/Users")
    if users_dir.is_dir():
        for entry in users_dir.iterdir():
            if entry.is_dir() and entry.name not in ("Public", "Default", "Default User", "All Users"):
                dirs.append(entry)
    return dirs


def _detect_gpu_info() -> str:
    """Detect GPU type and return a human-readable description."""
    try:
        import torch
    except ImportError:
        return "unknown (torch not importable)"

    build = torch.__version__  # e.g. "2.10.0+cu128" or "2.10.0+cpu"
    build_suffix = build.split("+")[-1] if "+" in build else "unknown"

    if torch.cuda.is_available():
        # Check if this is ROCm (AMD) or NVIDIA CUDA
        if hasattr(torch.version, "hip") and torch.version.hip:
            device_name = torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else "unknown"
            return f"AMD ROCm ({device_name}, torch+{build_suffix})"
        else:
            device_name = torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else "unknown"
            return f"NVIDIA CUDA ({device_name}, torch+{build_suffix})"
    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return f"Apple MPS (torch+{build_suffix})"
    except Exception:
        pass

    # CPU-only — check if a GPU exists but wrong PyTorch build is installed
    if build_suffix == "cpu":
        hw_hint = _detect_gpu_hardware_without_torch()
        if hw_hint:
            return f"CPU only (torch+cpu) — {hw_hint} detected but PyTorch lacks GPU support. Run: {_cmd_prefix()} gpu-setup"
    return f"CPU only (torch+{build_suffix})"


def _detect_gpu_hardware_without_torch() -> str:
    """Detect GPU hardware without relying on PyTorch — uses system tools."""
    # NVIDIA
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return f"NVIDIA {result.stdout.strip().splitlines()[0]}"
        except Exception:
            return "NVIDIA GPU"
    # AMD (Linux/Windows)
    if shutil.which("rocm-smi") or shutil.which("rocminfo"):
        return "AMD GPU (ROCm)"
    return ""


# ── Sub-commands ──────────────────────────────────────────────────────

def cmd_help() -> None:
    """Print the main help message listing available commands and examples."""
    prefix = _cmd_prefix()
    mcp_cmd = _mcp_server_cmd()

    print(bold("AGENT Context Local (compat: Claude Context Local)") + f"  v{VERSION}")
    print("Local semantic code search for AI coding assistants via MCP.\n")

    print(bold("USAGE"))
    print(f"  {prefix} {cyan('<command>')}\n")

    print(bold("COMMANDS"))
    cmds = [
        ("help", "Show this help message"),
        ("doctor", "Check installation health and diagnose problems"),
        ("version", "Print version and platform info"),
        ("status", "Show index statistics and active project info"),
        ("paths", "Show all paths used by the tool"),
        ("open-dashboard", "Launch the web dashboard and open in browser"),
        ("create-shortcut", "Create a desktop shortcut for the dashboard"),
        ("setup-guide", "Print step-by-step setup instructions for your OS"),
        ("setup-mcp", "MCP registration instructions for all supported clients"),
        ("gpu-setup", "Detect GPU and install matching PyTorch build"),
        ("troubleshoot", "HuggingFace auth & model download help"),
        ("mcp-check", "Verify MCP registration (Claude CLI check)"),
        ("models list", "List available embedding and reranker models"),
        ("models active", "Show currently configured models"),
        ("models install", "Download a model by short name"),
        ("config model", "Switch the active embedding model"),
        ("config reranker", "Toggle reranker, set model, or min-score"),
        ("config idle", "Set idle offload/unload thresholds (minutes)"),
    ]
    for name, desc in cmds:
        print(f"  {cyan(name):<20s} {desc}")

    print(f"\n{bold('EXAMPLES')}")
    print(f"  {prefix} doctor        # Verify installation")
    print(f"  {prefix} setup-guide    # Setup instructions")
    print(f"  {prefix} status         # Show project status\n")

    print(f"{bold('MCP SERVER')}")
    print(f"  {mcp_cmd}")

    print(f"\nSee README.md for full documentation.")


def cmd_version() -> None:
    """Print version and platform information."""
    print(f"agent-context-local  {VERSION}")
    print(f"Platform:  {get_platform_label()} ({platform.machine()})")
    print(f"Python:    {platform.python_version()}")


def cmd_paths() -> None:
    """Show all paths used by the tool."""
    install_dir = get_default_install_dir()
    print(bold("Paths used by AGENT Context Local\n"))
    storage = _get_storage_dir_or_report("paths")

    if storage is None:
        print(f"  {yellow('—')} Install directory:       {install_dir}")
        print(f"  {yellow('—')} Storage-dependent paths are unavailable until {cyan('CODE_SEARCH_STORAGE')} points to a writable location.")
        print(f"\n{bold('Claude Desktop config locations (optional, checked in order):')}")
        for p in get_claude_config_paths():
            marker = green("✓") if p.is_file() else yellow("—")
            print(f"  {marker} {p}")
        return

    rows = [
        ("Storage directory", str(storage), storage.is_dir()),
        ("Install directory", str(install_dir), install_dir.is_dir()),
        ("Models cache", str(storage / "models"), (storage / "models").is_dir()),
        ("Install config", str(storage / "install_config.json"), (storage / "install_config.json").is_file()),
        ("Projects data", str(storage / "projects"), (storage / "projects").is_dir()),
    ]

    for label, path, exists in rows:
        marker = green("✓") if exists else yellow("—")
        print(f"  {marker} {label + ':':<22s} {path}")

    print(f"\n{bold('Claude Desktop config locations (optional, checked in order):')}")
    for p in get_claude_config_paths():
        marker = green("✓") if p.is_file() else yellow("—")
        print(f"  {marker} {p}")


def cmd_doctor() -> None:
    """Run diagnostic checks and report actionable problems.

    Checks are separated into blockers (prevent usage) and warnings
    (non-critical issues). A summary shows counts of each.
    """
    print(bold("Running diagnostics…\n"))
    blockers = []
    warnings = []
    storage = _get_storage_dir_or_report("doctor")

    # 1. Python version (BLOCKER)
    py = sys.version_info
    if py >= (3, 12):
        print(f"  {green('✓')} Python {py.major}.{py.minor}.{py.micro}")
    else:
        msg = f"Python >= 3.12 required (found {py.major}.{py.minor}.{py.micro})"
        print(f"  {red('✗')} {msg}")
        blockers.append(msg)

    # 2. uv available (BLOCKER)
    if shutil.which("uv"):
        print(f"  {green('✓')} uv is installed")
    else:
        msg = "uv not found in PATH – install from https://astral.sh/uv/"
        print(f"  {red('✗')} {msg}")
        blockers.append(msg)

    # 3. git available (BLOCKER)
    if shutil.which("git"):
        print(f"  {green('✓')} git is installed")
    else:
        msg = "git not found in PATH"
        print(f"  {red('✗')} {msg}")
        blockers.append(msg)

    # 4. Storage directory (BLOCKER)
    if storage and storage.is_dir():
        print(f"  {green('✓')} Storage directory exists: {storage}")
    else:
        msg = "Storage directory unavailable – set CODE_SEARCH_STORAGE to a writable path"
        print(f"  {red('✗')} {msg}")
        blockers.append(msg)

    # 5. Install config (WARNING)
    if storage:
        config = load_local_install_config(storage_dir=storage)
        if config:
            model = config.get("embedding_model", {})
            model_name = model.get("model_name", "unknown") if isinstance(model, dict) else (model or "unknown")
            print(f"  {green('✓')} Install config found (model: {model_name})")
        else:
            msg = "No install_config.json found – run the installer first"
            print(f"  {yellow('!')} {msg}")
            warnings.append(msg)
    else:
        msg = "Install config unavailable because the storage directory is not writable"
        print(f"  {yellow('!')} {msg}")
        warnings.append(msg)

    # 6. Models directory (WARNING)
    if storage:
        models_dir = storage / "models"
        if models_dir.is_dir() and any(models_dir.iterdir()):
            print(f"  {green('✓')} Models cached in: {models_dir}")
        else:
            msg = "No models cached yet – the embedding model needs to be downloaded"
            print(f"  {yellow('!')} {msg}")
            warnings.append(msg)
    else:
        msg = "Model cache unavailable because the storage directory is not writable"
        print(f"  {yellow('!')} {msg}")
        warnings.append(msg)

    # 7. Key Python packages (BLOCKER)
    for pkg_name, import_names in [
        ("lancedb", ("lancedb",)),
        ("pyarrow", ("pyarrow",)),
        ("pandas", ("pandas",)),
        ("sentence-transformers", ("sentence_transformers",)),
        ("fastmcp", ("fastmcp",)),
        ("mcp", ("mcp", "mcp.server.fastmcp")),
        ("tree-sitter", ("tree_sitter",)),
    ]:
        try:
            for import_name in import_names:
                importlib.import_module(import_name)
            print(f"  {green('✓')} {pkg_name} importable ({', '.join(import_names)})")
        except Exception as exc:
            msg = (
                f"{pkg_name} not importable via {', '.join(import_names)} "
                f"({type(exc).__name__}) – run 'uv sync' to install dependencies"
            )
            print(f"  {red('✗')} {msg}")
            blockers.append(msg)

    # 8. Reranker status (informational)
    if storage:
        reranker_cfg = load_reranker_config(storage_dir=storage)
        if reranker_cfg:
            rr_enabled = reranker_cfg.get("enabled", False)
            rr_model = reranker_cfg.get("model_name", "unknown")
            if rr_enabled:
                print(f"  {green('✓')} Reranker enabled: {rr_model}")
            else:
                print(f"  {cyan('ℹ')} Reranker configured but disabled: {rr_model}")
        else:
            print(f"  {cyan('ℹ')} Reranker not configured (optional)")

    # 9. Claude CLI availability (optional, only needed for claude mcp commands)
    if shutil.which("claude"):
        print(f"  {green('✓')} Claude CLI found in PATH (optional)")
    else:
        msg = "Claude CLI not found in PATH (optional unless you use Claude as your MCP client)"
        print(f"  {yellow('!')} {msg}")
        warnings.append(msg)

    # 10. GPU/device detection (informational)
    gpu_info = _detect_gpu_info()
    print(f"  {cyan('ℹ')} Compute device: {gpu_info}")

    # 10b. GPU model auto-selection status
    try:
        from common_utils import detect_gpu, has_explicit_model_choice
        from embeddings.model_catalog import GPU_DEFAULT_EMBEDDING_MODEL
        device = detect_gpu()
        if device in ("cuda", "mps"):
            # Distinguish AMD ROCm from NVIDIA CUDA for the user
            device_label = device
            try:
                import torch
                if device == "cuda" and hasattr(torch.version, "hip") and torch.version.hip:
                    device_label = "rocm"
            except Exception:
                pass
            if has_explicit_model_choice():
                print(f"  {cyan('ℹ')} GPU model auto-upgrade: skipped (explicit model configured, device={device_label})")
            else:
                print(f"  {green('✓')} GPU model auto-upgrade: will use {GPU_DEFAULT_EMBEDDING_MODEL} at runtime (device={device_label})")
        else:
            # Check if GPU config exists but torch lacks GPU support
            if storage:
                gpu_cfg = load_local_install_config(storage_dir=storage).get("gpu", {})
                if gpu_cfg.get("vendor") and gpu_cfg["vendor"] != "cpu":
                    saved_url = gpu_cfg.get("torch_index_url", "")
                    print(f"  {yellow('!')} GPU was detected during install ({gpu_cfg['vendor']}) but PyTorch lacks GPU support")
                    print(f"    Fix: run '{_cmd_prefix()} gpu-setup' to install GPU PyTorch")
                    warnings.append("GPU config exists but PyTorch is CPU-only — GPU acceleration inactive")
                else:
                    print(f"  {cyan('ℹ')} GPU model auto-upgrade: not applicable (CPU-only)")
            else:
                print(f"  {cyan('ℹ')} GPU model auto-upgrade: not applicable (CPU-only)")
    except ImportError:
        pass

    # 11. WSL-specific checks
    if is_wsl():
        print(f"\n  {cyan('ℹ')} WSL2 detected – checking Windows interop…")
        win_dirs = _wsl_windows_user_dirs()
        if win_dirs:
            print(f"  {green('✓')} Windows user directories accessible: {', '.join(d.name for d in win_dirs)}")
        else:
            msg = "Cannot access Windows user directories from WSL (/mnt/c/Users/)"
            print(f"  {yellow('!')} {msg}")
            warnings.append(msg)

    # Summary
    print()
    if not blockers and not warnings:
        print(green(bold("All checks passed!")))
    else:
        if blockers:
            print(red(bold(f"{len(blockers)} blocker(s):")))
            for b in blockers:
                print(f"  {red('✗')} {b}")
        if warnings:
            print(yellow(bold(f"{len(warnings)} warning(s):")))
            for w in warnings:
                print(f"  {yellow('!')} {w}")

        total = len(blockers) + len(warnings)
        print(f"\n{total} issue(s): {len(blockers)} blocker(s), {len(warnings)} warning(s)")
        if blockers:
            print(f"Fix blockers first — they prevent indexing and search from working.")
        print(f"Run '{cyan('python scripts/cli.py setup-guide')}' for setup instructions.")


def cmd_status() -> None:
    """Show per-project index statistics from the storage directory.

    Iterates ``~/.agent_code_search/projects/`` and prints each project's
    name, workspace path, chunk count, and file count from its ``stats.json``.
    """
    print(bold("Index Status\n"))
    storage = _get_storage_dir_or_report("status")
    if storage is None:
        return

    projects_dir = storage / "projects"

    if not projects_dir.is_dir():
        print("  No projects indexed yet.")
        print(f"  Use your AI coding assistant to say: {cyan('index this codebase')}")
        return

    project_count = 0
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue

        info_file = project_dir / "project_info.json"
        stats_file = project_dir / "index" / "stats.json"

        if not info_file.is_file():
            continue

        project_count += 1
        try:
            info = json.loads(info_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            info = {}

        name = info.get("project_name", project_dir.name)
        path = info.get("project_path", "unknown")
        print(f"  {bold(name)}")
        print(f"    Path: {path}")

        if stats_file.is_file():
            try:
                stats = json.loads(stats_file.read_text(encoding="utf-8"))
                chunks = stats.get("total_chunks", 0)
                files = stats.get("files_indexed", 0)
                print(f"    Chunks: {chunks}  Files: {files}")
            except (json.JSONDecodeError, OSError):
                print("    (stats unavailable)")
        else:
            print("    (not yet indexed)")

        print()

    if project_count == 0:
        print("  No projects indexed yet.")


def cmd_setup_guide() -> None:
    """Print step-by-step setup instructions tailored to the current platform.

    Covers: install command, MCP registration, verification, first use, and
    common troubleshooting tips.  WSL-specific hints are included when running
    inside a WSL environment.

    HuggingFace auth section is only shown if the current model is gated.
    """
    plat = get_platform_label()
    install_dir = get_default_install_dir()

    # Determine if the current/default model is gated
    current_model = None
    try:
        storage = get_storage_dir()
        config = load_local_install_config(storage_dir=storage)
        if config:
            emb = config.get("embedding_model", {})
            current_model = emb.get("model_name") if isinstance(emb, dict) else emb
    except Exception:
        pass

    gated_models = GATED_MODELS
    model_is_gated = current_model in gated_models if current_model else False

    print(bold(f"Setup Guide for {plat}\n"))

    # Step 1 – Model selection
    print(bold("1. Pick a model (optional)"))
    if current_model:
        if model_is_gated:
            print(f"   Current model: {cyan(current_model)} {yellow('(gated – requires HF auth)')}")
        else:
            print(f"   Current model: {cyan(current_model)} {green('(open – no HF auth required)')}")
    else:
        print(f"   Default model: {cyan(_DEFAULT_EMBEDDING_MODEL)} {green('(open – no HF auth required)')}")

    print()
    if is_windows():
        print(f"   Example for a higher-end model:\n")
        print(f"   {cyan('$env:CODE_SEARCH_MODEL=\"unsloth/Qwen3-Embedding-4B\"')}\n")
    else:
        print(f"   Example for a higher-end model:\n")
        print(f"   {cyan('export CODE_SEARCH_MODEL=\"unsloth/Qwen3-Embedding-4B\"')}\n")

    # Step 2 – Install
    print(bold("2. Install"))
    if is_windows():
        print("   Open PowerShell and run:\n")
        print(f"   {cyan(f'irm {INSTALL_PS1_URL} | iex')}\n")
        print("   If execution policy blocks the script:\n")
        print(f"   {cyan(f'powershell -ExecutionPolicy Bypass -c \"irm {INSTALL_PS1_URL} | iex\"')}\n")
    elif is_wsl():
        print("   From your WSL terminal:\n")
        print(f"   {cyan(f'curl -fsSL {INSTALL_SH_URL} | bash')}\n")
        print(f"   {yellow('Note:')} If Claude Desktop is installed on the Windows side,")
        print(f"   you may need to register the MCP server using the Windows path.")
        print(f"   The installer puts the project at: {install_dir}\n")
    else:
        print("   In your terminal:\n")
        print(f"   {cyan(f'curl -fsSL {INSTALL_SH_URL} | bash')}\n")

    # Step 3 – Register MCP
    mcp_cmd = _mcp_server_cmd()
    print(bold("3. Register the MCP server"))
    print(f"   {yellow('Run this in your terminal, not inside your MCP client session.')}\n")
    print(f"   {cyan(f'claude mcp add code-search --scope user -- {mcp_cmd}')}\n")
    print(f"   For other MCP clients, run: {cyan(f'{_cmd_prefix()} setup-mcp')}\n")

    if is_wsl():
        print(f"   {yellow('WSL tip:')} If Claude Desktop runs on Windows, register the server")
        print(f"   from a Windows terminal using the Windows-style path.")
        print(f"   Alternatively, use {cyan('claude.exe')} from WSL to register directly —")
        print(f"   WSL2 can run Windows executables natively (add the {cyan('.exe')} suffix).\n")
        print(f"   {yellow('WSL2 + Windows interop:')} Your WSL2 instance has access to the Windows")
        print(f"   filesystem at {cyan('/mnt/c/')} and can call Windows binaries directly.")
        print(f"   For example, Docker Desktop installed via the Windows Store works from WSL:")
        print(f"     {cyan('[mcp_servers.MCP_DOCKER]')}")
        print(f"     {cyan('command = \"docker.exe\"')}")
        print(f"     {cyan('args = [\"mcp\", \"gateway\", \"run\"]')}\n")

    # Step 4 – Verify
    prefix = _cmd_prefix()
    print(bold("4. Verify"))
    print(f"   {cyan(f'{prefix} doctor')}")
    print(f"   If using Claude CLI, run: {cyan('claude mcp list')}")
    print(f"   Look for: code-search … {green('✓ Connected')}")
    print(f"   For other MCP clients, verify using your client's MCP server list/health view.\n")

    # Step 5 – Use
    print(bold("5. Index & search"))
    print(f"   Open your AI coding assistant in your project directory and say:")
    print(f"   {cyan('index this codebase')}\n")
    print(f"   Then search with:")
    print(f"   {cyan('search for authentication logic')}\n")

    # HuggingFace auth — only if the current model is gated
    if model_is_gated:
        print(bold("HuggingFace Authentication (required for your model)"))
        print()
        print(f"  Your current model ({cyan(current_model)}) is {yellow('gated')} on HuggingFace.")
        print(f"  You must authenticate before the model can be downloaded.\n")
        print(f"  1. Create a HuggingFace account at https://huggingface.co/join")
        print(f"  2. Visit https://huggingface.co/{current_model}")
        print(f"     and click {bold('\"Agree and access repository\"')} to accept the license.")
        print(f"  3. Create an access token at https://huggingface.co/settings/tokens\n")
        print(f"  {bold('Authenticate:')}")
        print(f"    {cyan('uv run huggingface-cli login')}")
        print(f"    Or set {cyan('HF_TOKEN')} in your shell.\n")
        print(f"  {bold('Alternative:')} Switch to a non-gated model:")
        if is_windows():
            print(f"    {cyan(f'$env:CODE_SEARCH_MODEL=\"{_DEFAULT_EMBEDDING_MODEL}\"')}")
        else:
            print(f"    {cyan(f'export CODE_SEARCH_MODEL=\"{_DEFAULT_EMBEDDING_MODEL}\"')}")
        print(f"    Then re-run the installer.\n")
    else:
        effective_model = current_model or _DEFAULT_EMBEDDING_MODEL
        print(f"  {green('✓')} Your model ({cyan(effective_model)}) does not require HuggingFace authentication.\n")

    # Troubleshooting
    print(bold("Troubleshooting"))
    print(f"  • Run {cyan(f'{_cmd_prefix()} doctor')} to diagnose issues")
    print(f"  • Ensure Python >= 3.12 and uv are installed")
    print()


def cmd_troubleshoot() -> None:
    """Print troubleshooting guidance for model downloads and HuggingFace auth."""
    print(bold("Troubleshooting Guide\n"))

    # ── Model download issues ────────────────────────────────────────
    print(bold("1. Gated model access (google/embeddinggemma-300m)"))
    print()
    print(f"  The legacy default embedding model is {yellow('gated')} by Google on HuggingFace.")
    print(f"  The new default ({cyan(_DEFAULT_EMBEDDING_MODEL)}) is {green('not gated')}.")
    print(f"  If you are using a gated model, you must accept the license:\n")
    print(f"  a) Go to https://huggingface.co/google/embeddinggemma-300m")
    print(f"  b) Sign in (or create an account at https://huggingface.co/join)")
    print(f"  c) Click {bold('\"Agree and access repository\"')}")
    print(f"     Access is granted immediately — no manual review wait.\n")

    print(bold("2. Authenticate with HuggingFace"))
    print()
    print(f"  Create a token at: https://huggingface.co/settings/tokens")
    print(f"  Then authenticate using one of these methods:\n")
    print(f"  {bold('Method A — huggingface-cli (bundled with this project):')}")
    print(f"    {cyan('uv run huggingface-cli login')}")
    print(f"    Paste your token when prompted.\n")
    print(f"  {bold('Method B — Environment variable:')}")
    if is_windows():
        print(f"    {cyan('$env:HF_TOKEN=\"hf_your_token_here\"')}")
    else:
        print(f"    {cyan('export HF_TOKEN=\"hf_your_token_here\"')}")
    print()
    print(f"  {bold('Method C — Standalone hf CLI:')}")
    if is_windows():
        print(f"    Install: {cyan('powershell -c \"irm https://hf.co/cli/install.ps1 | iex\"')}")
    else:
        print(f"    Install: {cyan('curl -LsSf https://hf.co/cli/install.sh | bash')}")
    print(f"    Login:   {cyan('hf auth login')}")
    print(f"    Verify:  {cyan('hf auth whoami')}\n")

    print(bold("3. Verify your setup"))
    print()
    print(f"    {cyan(f'{_cmd_prefix()} doctor')}")
    print()

    print(bold("4. Common errors and fixes"))
    print()
    errors = [
        ("401 / Access denied",
         "Accept the Gemma license at https://huggingface.co/google/embeddinggemma-300m"),
        ("Token not found",
         "Run 'uv run huggingface-cli login' or set HF_TOKEN env var"),
        ("Download incomplete / timeout",
         "Check disk space (~1-2 GB needed) and network connection"),
        ("Import errors after install",
         "Run 'uv sync' in the project directory"),
        ("Model works offline after first download",
         "Set HF_HUB_OFFLINE=1 to skip network checks"),
    ]
    for err, fix in errors:
        print(f"    {yellow(err)}")
        print(f"      Fix: {fix}\n")

    print(bold("5. Switch to a non-gated model"))
    print()
    print(f"  The default model ({cyan(_DEFAULT_EMBEDDING_MODEL)}) does {green('not')} require")
    print(f"  HuggingFace gated access. If you switched to a gated model and")
    print(f"  are having auth issues, consider switching back:\n")
    if is_windows():
        print(f"    {cyan(f'$env:CODE_SEARCH_MODEL=\"{_DEFAULT_EMBEDDING_MODEL}\"')}")
    else:
        print(f"    {cyan(f'export CODE_SEARCH_MODEL=\"{_DEFAULT_EMBEDDING_MODEL}\"')}")
    print()
    print(f"  Or install interactively:")
    print(f"    {cyan('python scripts/cli.py models list')}")
    print(f"    {cyan('python scripts/cli.py models install qwen-embed-0.6b')}")
    print()
    if is_wsl():
        print(bold("6. WSL-specific notes"))
        print()
        print(f"  • Windows-cached HuggingFace tokens are NOT visible in WSL.")
        print(f"    Set HF_TOKEN explicitly in your WSL shell.")
        print(f"  • If Claude Desktop runs on the Windows side, register MCP")
        print(f"    from a Windows terminal using the Windows-style path.")
        print()
        print(f"  {bold('Windows filesystem & exe interop from WSL2:')}")
        print()
        print(f"  WSL2 instances (including those installed via the Microsoft Store)")
        print(f"  have full access to the Windows filesystem and can run Windows")
        print(f"  executables directly. This is useful for tools installed on the")
        print(f"  Windows side (e.g. Docker Desktop, claude.exe).")
        print()
        print(f"  Examples:")
        print(f"    • Access Windows files:  {cyan('ls /mnt/c/Users/$USER/')}")
        print(f"    • Run Windows commands:  {cyan('cmd.exe /c dir')}")
        print(f"    • Run Docker Desktop:    {cyan('docker.exe ps')}")
        print()
        print(f"  This means CLI tools installed on either side can interop. For")
        print(f"  example, if Codex CLI is installed in WSL2 but Docker Desktop is")
        print(f"  a Windows Store app, you can still configure MCP servers that call")
        print(f"  Windows executables from WSL:")
        print()
        print(f"    {cyan('[mcp_servers.MCP_DOCKER]')}")
        print(f"    {cyan('command = \"docker.exe\"')}")
        print(f"    {cyan('args = [\"mcp\", \"gateway\", \"run\"]')}")
        print()
        print(f"  The {cyan('.exe')} suffix is required when calling Windows binaries from WSL.")
        print(f"  Similarly, {cyan('claude.exe')} can be used to register MCP servers from WSL")
        print(f"  if the Claude CLI was installed on the Windows side.")
        print()


def cmd_mcp_check() -> None:
    """Check MCP registration using Claude CLI (optional helper)."""
    print(bold("MCP Server Registration Check (Claude CLI)\n"))

    claude_path = shutil.which("claude")
    if not claude_path:
        print(f"  {red('✗')} Claude CLI not found in PATH")
        print(f"    This check is Claude-specific. If you use another MCP client, verify there instead.")
        print(f"    Install Claude CLI (optional): https://claude.ai/code\n")
        return

    print(f"  {green('✓')} Claude CLI found: {claude_path}")

    # Try to run `claude mcp list` and look for code-search
    try:
        result = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout + result.stderr
        if "code-search" in output.lower():
            print(f"  {green('✓')} code-search MCP server is registered")
            # Print the relevant line(s) for confirmation
            for line in output.splitlines():
                if "code-search" in line.lower():
                    print(f"    {line.strip()}")
        else:
            print(f"  {yellow('!')} code-search MCP server is NOT registered\n")
            print(f"  Register it with:\n")
            print(f"  {cyan(f'claude mcp add code-search --scope user -- {_mcp_server_cmd()}')}")
    except FileNotFoundError:
        print(f"  {red('✗')} Could not run 'claude mcp list'")
    except subprocess.TimeoutExpired:
        print(f"  {yellow('!')} 'claude mcp list' timed out")
    except Exception as exc:
        print(f"  {yellow('!')} Could not check MCP status: {exc}")

    print()


# ── MCP setup command ─────────────────────────────────────────────────

# Each entry: key → (display_name, has_cli, brief_description)
# Config file / setup details are in the cmd_setup_mcp_tool function.
MCP_TOOLS = {
    "claude-code": ("Claude Code", True, "CLI: claude mcp add"),
    "copilot-cli": ("GitHub Copilot CLI", True, "CLI: copilot mcp add"),
    "gemini-cli": ("Gemini CLI", False, "Config: ~/.gemini/settings.json"),
    "cursor": ("Cursor", False, "Config: ~/.cursor/mcp.json"),
    "codex-cli": ("OpenAI Codex CLI", True, "Config: ~/.codex/config.toml"),
    "opencode": ("OpenCode", True, "Config: ~/.config/opencode/opencode.json"),
    "cline": ("Cline (VS Code)", False, "VS Code globalStorage UI"),
    "roo-code": ("Roo Code (VS Code)", False, "VS Code globalStorage UI"),
}


def cmd_setup_mcp() -> None:
    """Print MCP registration instructions for supported AI coding clients."""
    args = sys.argv[2:]  # skip "cli.py setup-mcp"
    if not args or args[0] == "--list":
        _setup_mcp_list()
        return

    tool_key = args[0].lower()
    if tool_key not in MCP_TOOLS:
        print(red(f"Unknown tool: '{tool_key}'"))
        print(f"Run '{cyan(f'{_cmd_prefix()} setup-mcp')}' to see supported tools.")
        sys.exit(1)

    _setup_mcp_tool(tool_key)


def _setup_mcp_list() -> None:
    """List all supported MCP client tools."""
    print(bold("Supported MCP Client Tools\n"))
    print(f"Run '{cyan(f'{_cmd_prefix()} setup-mcp <tool>')}' for setup instructions.\n")
    for key, (name, _has_cli, brief) in MCP_TOOLS.items():
        print(f"  {cyan(key):<18s} {name:<28s} {brief}")
    print()


def _setup_mcp_tool(tool_key: str) -> None:
    """Print detailed setup instructions for a specific MCP client tool."""
    name, _has_cli, _brief = MCP_TOOLS[tool_key]
    mcp_cmd = _mcp_server_cmd()
    install_dir = get_default_install_dir()

    print(bold(f"MCP Setup: {name}\n"))

    # Prerequisites
    print(bold("Prerequisites"))
    print(f"  • Python 3.12+ and uv installed")
    print(f"  • AGENT Context Local installed (run the installer or pip install)")
    print(f"  • MCP server command: {cyan(mcp_cmd)}")
    print()

    # Per-tool instructions
    if tool_key == "claude-code":
        _mcp_claude_code(mcp_cmd)
    elif tool_key == "copilot-cli":
        _mcp_copilot_cli(mcp_cmd)
    elif tool_key == "gemini-cli":
        _mcp_gemini_cli(mcp_cmd, install_dir)
    elif tool_key == "cursor":
        _mcp_cursor(mcp_cmd, install_dir)
    elif tool_key == "codex-cli":
        _mcp_codex_cli(mcp_cmd, install_dir)
    elif tool_key == "opencode":
        _mcp_opencode(mcp_cmd, install_dir)
    elif tool_key == "cline":
        _mcp_cline(mcp_cmd, install_dir)
    elif tool_key == "roo-code":
        _mcp_roo_code(mcp_cmd, install_dir)

    # Verification
    print(bold("Verify"))
    print(f"  Run {cyan(f'{_cmd_prefix()} doctor')} to check installation health.")
    print()


def _mcp_claude_code(mcp_cmd: str) -> None:
    print(bold("Registration (run in your terminal, not inside Claude Code)"))
    print()
    print(f"  {cyan(f'claude mcp add code-search --scope user -- {mcp_cmd}')}")
    print()
    print(f"  Verify: {cyan('claude mcp list')}")
    print(f"  Look for: code-search … Connected")
    print()
    if is_windows():
        print(f"  {yellow('Windows cmd.exe:')} prefix with {cyan('cmd /c')} if needed.")
        print()


def _mcp_copilot_cli(mcp_cmd: str) -> None:
    print(bold("Registration"))
    print()
    print(f"  {cyan(f'copilot mcp add code-search -- {mcp_cmd}')}")
    print()
    print(f"  Or edit {cyan('~/.copilot/mcp-config.json')}:")
    print()
    _print_json_config(mcp_cmd)
    print()


def _mcp_gemini_cli(mcp_cmd: str, install_dir: Path) -> None:
    print(bold("Configuration"))
    print()
    print(f"  Edit {cyan('~/.gemini/settings.json')} and add under {cyan('\"mcpServers\"')}:")
    print()
    _print_json_config(mcp_cmd)
    print()


def _mcp_cursor(mcp_cmd: str, install_dir: Path) -> None:
    print(bold("Configuration"))
    print()
    print(f"  Edit {cyan('~/.cursor/mcp.json')} (global) or {cyan('.cursor/mcp.json')} (per-project):")
    print()
    _print_json_config(mcp_cmd)
    print()


def _mcp_codex_cli(mcp_cmd: str, install_dir: Path) -> None:
    print(bold("Configuration"))
    print()
    print(f"  Edit {cyan('~/.codex/config.toml')} and add:")
    print()
    # Split mcp_cmd into command + args for TOML format
    parts = mcp_cmd.split()
    cmd = parts[0]
    args_list = parts[1:] if len(parts) > 1 else []
    args_toml = ", ".join(f'"{a}"' for a in args_list)
    print(f'  {cyan("[mcp_servers.code-search]")}')
    print(f'  {cyan(f"command = " + chr(34) + cmd + chr(34))}')
    if args_list:
        print(f'  {cyan(f"args = [{args_toml}]")}')
    print()


def _mcp_opencode(mcp_cmd: str, install_dir: Path) -> None:
    print(bold("Configuration"))
    print()
    print(f"  Edit {cyan('~/.config/opencode/opencode.json')} and add under {cyan('\"mcpServers\"')}:")
    print()
    _print_json_config(mcp_cmd)
    print()


def _mcp_cline(mcp_cmd: str, install_dir: Path) -> None:
    print(bold("Configuration (via VS Code UI)"))
    print()
    print(f"  1. Open VS Code with Cline installed")
    print(f"  2. Open Cline settings (gear icon in the Cline panel)")
    print(f"  3. Navigate to MCP Servers")
    print(f"  4. Add a new server with these settings:")
    print()
    parts = mcp_cmd.split()
    print(f"     Name:    {cyan('code-search')}")
    print(f"     Command: {cyan(parts[0])}")
    if len(parts) > 1:
        print(f"     Args:    {cyan(' '.join(parts[1:]))}")
    print()
    print(f"  Or edit the Cline MCP settings JSON directly:")
    print()
    _print_json_config(mcp_cmd)
    print()


def _mcp_roo_code(mcp_cmd: str, install_dir: Path) -> None:
    print(bold("Configuration (via VS Code UI)"))
    print()
    print(f"  1. Open VS Code with Roo Code installed")
    print(f"  2. Open Roo Code settings")
    print(f"  3. Navigate to MCP Servers")
    print(f"  4. Add a new server with these settings:")
    print()
    parts = mcp_cmd.split()
    print(f"     Name:    {cyan('code-search')}")
    print(f"     Command: {cyan(parts[0])}")
    if len(parts) > 1:
        print(f"     Args:    {cyan(' '.join(parts[1:]))}")
    print()
    print(f"  Or edit the Roo Code MCP settings JSON directly:")
    print()
    _print_json_config(mcp_cmd)
    print()


def _print_json_config(mcp_cmd: str) -> None:
    """Print a JSON MCP server config snippet for the given server command."""
    parts = mcp_cmd.split()
    cmd = parts[0]
    args = parts[1:] if len(parts) > 1 else []
    args_json = ", ".join(f'"{a}"' for a in args)
    print(f'  {{')
    print(f'    "mcpServers": {{')
    print(f'      "code-search": {{')
    print(f'        "command": "{cmd}",')
    print(f'        "args": [{args_json}]')
    print(f'      }}')
    print(f'    }}')
    print(f'  }}')


# ── GPU setup command ─────────────────────────────────────────────────

def cmd_gpu_setup() -> None:
    """Detect GPU hardware and configure PyTorch for GPU acceleration.

    Uses pyproject.toml extras (``cu128``, ``cu126``, etc.) with
    ``[tool.uv.sources]`` to route torch through GPU-specific PyTorch
    indexes.  The MCP server command includes ``--extra <name>`` so
    ``uv run`` syncs GPU torch automatically.
    """
    print(bold("GPU Setup\n"))

    # Check for --cpu flag → show CPU commands
    if "--cpu" in sys.argv:
        project_dir = Path(__file__).resolve().parent.parent
        mcp_dir = str(project_dir)
        print(f"  {green('✓')} CPU mode selected.\n")
        print(f"  Syncing without GPU extra...")
        subprocess.run(["uv", "sync"], cwd=project_dir, timeout=600)
        print(f"\n  Register the MCP server (CPU):")
        if sys.platform == "win32":
            print(f'    claude mcp add code-search --scope user -- uv run --directory "{mcp_dir}" python mcp_server/server.py')
        else:
            print(f"    claude mcp add code-search --scope user -- uv run --directory {mcp_dir} python mcp_server/server.py")
        print()
        return

    # Step 1: Detect hardware
    vendor, cuda_ver, gpu_name, index_url = detect_gpu_index_url()

    if vendor == "mps":
        print(f"  {green('✓')} Apple Silicon detected ({gpu_name})")
        print(f"    MPS acceleration is included in the standard PyTorch macOS build.")
        print(f"    No additional installation needed.\n")
        _verify_torch_gpu()
        return

    if vendor == "nvidia":
        print(f"  {green('✓')} NVIDIA GPU detected: {gpu_name}")
        print(f"    Driver CUDA version: {cuda_ver}")
        print(f"    PyTorch index: {index_url}\n")
    elif vendor == "amd":
        print(f"  {green('✓')} AMD GPU detected: {gpu_name}")
        if cuda_ver:
            print(f"    ROCm version: {cuda_ver}")
        print(f"    PyTorch index: {index_url}\n")
    else:
        print(f"  {yellow('!')} No supported GPU detected.")
        print(f"    Embedding generation will use CPU.\n")
        print(f"  Supported GPUs:")
        print(f"    • NVIDIA: requires nvidia-smi in PATH (comes with NVIDIA drivers)")
        print(f"    • AMD:    requires ROCm/HIP SDK (rocminfo or rocm-smi in PATH)")
        print(f"    • Apple:  M1/M2/M3/M4 — automatic via MPS\n")
        return

    if not index_url:
        print(f"  {yellow('!')} Could not determine the right PyTorch build for your hardware.")
        print(f"    Run gpu-setup again after updating your GPU drivers.")
        return

    # Step 2: Map index URL to pyproject.toml extra name
    extra_name = _index_url_to_extra(index_url)
    if not extra_name:
        # Older CUDA/ROCm — no pre-defined extra.  Fall back to uv pip install.
        print(f"  {yellow('!')} No pre-built extra for {index_url} (torch 2.10.0 not available).")
        print(f"  Installing via uv pip install fallback...")
        project_dir = Path(__file__).resolve().parent.parent
        fallback = subprocess.run(
            ["uv", "pip", "install", "torch", "--index-url", index_url, "--reinstall"],
            cwd=project_dir, timeout=600,
        )
        if fallback.returncode == 0:
            print(f"\n  {green('✓')} GPU torch installed.")
            print(f"  {yellow('!')} Use --no-sync in MCP command to prevent uv from reverting:")
            mcp_dir = str(project_dir)
            if sys.platform == "win32":
                print(f'    claude mcp add code-search --scope user -- uv run --no-sync --directory "{mcp_dir}" python mcp_server/server.py')
            else:
                print(f"    claude mcp add code-search --scope user -- uv run --no-sync --directory '{mcp_dir}' python mcp_server/server.py")
        else:
            print(f"  {red('✗')} GPU torch installation failed.")
        _verify_torch_gpu()
        return

    # Step 3: Sync with GPU extra
    project_dir = Path(__file__).resolve().parent.parent
    print(f"  Installing GPU PyTorch (extra: {extra_name})...")
    sync_result = subprocess.run(
        ["uv", "sync", "--extra", extra_name],
        cwd=project_dir, timeout=600,
    )
    if sync_result.returncode != 0:
        print(f"\n  {yellow('!')} uv sync --extra {extra_name} failed — falling back to uv pip install...")
        fallback = subprocess.run(
            ["uv", "pip", "install", "torch", "--index-url", index_url, "--reinstall"],
            cwd=project_dir, timeout=600,
        )
        if fallback.returncode == 0:
            print(f"  {green('✓')} GPU torch installed via fallback (uv pip install).")
        else:
            print(f"  {red('✗')} GPU torch installation failed.")
        _verify_torch_gpu()
        return

    # Step 4: Save GPU info to install_config.json
    try:
        config = load_local_install_config()
        config["gpu"] = {
            "vendor": vendor,
            "torch_index_url": index_url,
            "extra": extra_name,
            "status": f"{vendor}-{index_url.split('/')[-1]}",
        }
        config_path = Path(get_storage_dir()) / "install_config.json"
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass  # Non-critical

    # Step 5: Auto-register MCP with --extra flag
    mcp_dir = str(project_dir)
    print(f"\n  {green('✓')} GPU-accelerated PyTorch installed successfully.")
    print(f"  Use --extra {extra_name} in uv run commands for GPU torch.\n")

    mcp_cmd_parts = ["uv", "run", "--extra", extra_name, "--directory", mcp_dir,
                     "python", "mcp_server/server.py"]
    if shutil.which("claude"):
        print(f"  Auto-registering MCP server with Claude Code...")
        subprocess.run(["claude", "mcp", "remove", "code-search", "--scope", "user"],
                       capture_output=True)
        reg = subprocess.run(
            ["claude", "mcp", "add", "code-search", "--scope", "user", "--"] + mcp_cmd_parts,
            capture_output=True,
        )
        if reg.returncode == 0:
            print(f"  {green('✓')} MCP server registered. Verify with: claude mcp list\n")
        else:
            mcp_cmd_str = " ".join(mcp_cmd_parts)
            print(f"  {yellow('!')} Auto-registration failed. Register manually:")
            print(f"    claude mcp add code-search --scope user -- {mcp_cmd_str}\n")
    else:
        mcp_cmd_str = " ".join(mcp_cmd_parts)
        print(f"  Register the MCP server:")
        print(f"    claude mcp remove code-search")
        print(f"    claude mcp add code-search --scope user -- {mcp_cmd_str}")
        print()

    _verify_torch_gpu()


# Map PyTorch index URLs to pyproject.toml extra names.
# Only cu126, cu128, and rocm7.1 have torch>=2.10.0 wheels.
# Older CUDA (cu118/cu121/cu124) and ROCm <7.1 fall through to the
# uv pip install fallback in gpu-setup.
_INDEX_URL_TO_EXTRA = {
    "https://download.pytorch.org/whl/cu126": "cu126",
    "https://download.pytorch.org/whl/cu128": "cu128",
    "https://download.pytorch.org/whl/rocm7.1": "rocm",
}


def _index_url_to_extra(index_url: str) -> Optional[str]:
    """Map a PyTorch index URL to the corresponding pyproject.toml extra name."""
    return _INDEX_URL_TO_EXTRA.get(index_url)


def _verify_torch_gpu() -> None:
    """Quick check: verify PyTorch can see the GPU."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", (
                "import torch; "
                "cuda = torch.cuda.is_available(); "
                "mps = hasattr(torch.backends, 'mps') and torch.backends.mps.is_available(); "
                "dev = 'CUDA' if cuda else ('MPS' if mps else 'CPU'); "
                "name = torch.cuda.get_device_name(0) if cuda else ''; "
                "print(f'{dev}|{name}|{torch.__version__}')"
            )],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split("|")
            dev, name, ver = parts[0], parts[1], parts[2]
            if dev in ("CUDA", "MPS"):
                label = f"{dev}: {name}" if name else dev
                print(f"  {green('✓')} PyTorch {ver} — accelerator: {label}")
            else:
                print(f"  {yellow('!')} PyTorch {ver} — running on CPU")
        else:
            print(f"  {yellow('!')} Could not verify PyTorch GPU status")
    except Exception as exc:
        print(f"  {yellow('!')} Verification failed: {exc}")


# ── Model & reranker management commands ─────────────────────────────

def cmd_models() -> None:
    """Dispatch ``models <subcommand>``."""
    args = sys.argv[2:]  # skip "cli.py models"
    if not args:
        cmd_models_list()
        return

    sub = args[0].lower()
    if sub == "list":
        cmd_models_list()
    elif sub == "active":
        cmd_models_active()
    elif sub == "install":
        if len(args) < 2:
            print(red("Usage: models install <short-name>"))
            sys.exit(1)
        cmd_models_install(args[1])
    else:
        print(red(f"Unknown models subcommand: '{sub}'"))
        print(f"Available: {cyan('list')}, {cyan('active')}, {cyan('install <short-name>')}")
        sys.exit(1)


def cmd_models_list() -> None:
    """Print all available embedding and reranker models with active/default markers."""
    from embeddings.model_catalog import MODEL_CATALOG, DEFAULT_EMBEDDING_MODEL
    from reranking.reranker_catalog import RERANKER_CATALOG

    # Load current config to determine active model
    active_model = None
    try:
        storage = get_storage_dir()
        config = load_local_install_config(storage_dir=storage)
        if config:
            emb = config.get("embedding_model", {})
            active_model = emb.get("model_name") if isinstance(emb, dict) else emb
    except Exception:
        pass

    gated_models = GATED_MODELS

    print(bold("Embedding Models\n"))
    for name, cfg in MODEL_CATALOG.items():
        dim = cfg.embedding_dimension or "?"
        markers = []
        if name == active_model:
            markers.append(green("[ACTIVE]"))
        if name == DEFAULT_EMBEDDING_MODEL:
            markers.append(cyan("[DEFAULT]"))
        gated_label = yellow("(gated)") if name in gated_models else green("(open)")
        marker_str = " ".join(markers)
        if marker_str:
            marker_str = " " + marker_str

        print(f"  {cyan(cfg.short_name or '(none)'):<22s} {name}{marker_str} {gated_label}")
        print(f"    {'dim=' + str(dim):<12s} {cfg.description}")
        print()

    print(bold("Reranker Models\n"))
    for name, cfg in RERANKER_CATALOG.items():
        print(f"  {cyan(cfg.short_name):<22s} {name}")
        print(f"    {'VRAM ~' + str(cfg.vram_requirement_gb) + 'GB':<12s} {cfg.description}")
        print()


def cmd_models_active() -> None:
    """Show the currently configured embedding model and reranker."""
    storage = _get_storage_dir_or_report("models active")
    if storage is None:
        return

    config = load_local_install_config(storage_dir=storage)
    emb = config.get("embedding_model", {})
    emb_name = emb.get("model_name", "unknown") if isinstance(emb, dict) else (emb or "unknown")

    print(bold("Active Models\n"))
    print(f"  Embedding:  {green(emb_name)}")

    reranker_cfg = load_reranker_config(storage_dir=storage)
    if reranker_cfg:
        enabled = reranker_cfg.get("enabled", False)
        rr_name = reranker_cfg.get("model_name", "unknown")
        status = green("enabled") if enabled else yellow("disabled")
        recall_k = reranker_cfg.get("recall_k", 50)
        min_reranker_score = reranker_cfg.get("min_reranker_score", 0.0)
        print(
            f"  Reranker:   {rr_name} [{status}] "
            f"(recall_k={recall_k}, min_score={min_reranker_score})"
        )
    else:
        print(f"  Reranker:   {yellow('not configured')}")


def cmd_models_install(short_name: str) -> None:
    """Download a model by its short name."""
    from embeddings.model_catalog import EMBEDDING_SHORT_NAMES
    from reranking.reranker_catalog import RERANKER_SHORT_NAMES

    storage = _get_storage_dir_or_report("models install")
    if storage is None:
        return

    # Check embedding models first
    if short_name in EMBEDDING_SHORT_NAMES:
        full_name = EMBEDDING_SHORT_NAMES[short_name]
        print(f"Installing embedding model: {full_name}")
        # Import and run the download script
        from scripts.download_model_standalone import download_model
        success = download_model(full_name, str(storage))
        sys.exit(0 if success else 1)

    # Check reranker models
    if short_name in RERANKER_SHORT_NAMES:
        full_name = RERANKER_SHORT_NAMES[short_name]
        print(f"Installing reranker model: {full_name}")
        from scripts.download_reranker_standalone import download_reranker
        success = download_reranker(full_name, str(storage))
        sys.exit(0 if success else 1)

    print(red(f"Unknown model short name: '{short_name}'"))
    print(f"Run '{cyan('python scripts/cli.py models list')}' to see available models.")
    sys.exit(1)


def cmd_config() -> None:
    """Dispatch ``config <subcommand>``."""
    args = sys.argv[2:]
    if not args:
        print(
            red(
                "Usage: config model <short-name>  |  "
                "config reranker <on|off>  |  "
                "config reranker model <short-name>  |  "
                "config reranker min-score <0.0-1.0>  |  "
                "config idle <offload|unload> <minutes>"
            )
        )
        sys.exit(1)

    sub = args[0].lower()
    if sub == "reranker":
        if len(args) < 2:
            print(
                red(
                    "Usage: config reranker <on|off>  OR  "
                    "config reranker model <short-name>  OR  "
                    "config reranker min-score <0.0-1.0>"
                )
            )
            sys.exit(1)
        if args[1].lower() == "model":
            if len(args) < 3:
                print(red("Usage: config reranker model <short-name>"))
                sys.exit(1)
            cmd_config_reranker_model(args[2])
        elif args[1].lower() in ("min-score", "min_score", "threshold"):
            if len(args) < 3:
                print(red("Usage: config reranker min-score <0.0-1.0>"))
                sys.exit(1)
            cmd_config_reranker_min_score(args[2])
        else:
            cmd_config_reranker(args[1])
    elif sub == "model":
        if len(args) < 2:
            print(red("Usage: config model <short-name>"))
            sys.exit(1)
        cmd_config_model(args[1])
    elif sub == "idle":
        if len(args) < 3:
            print(
                red(
                    "Usage: config idle offload <minutes>  |  "
                    "config idle unload <minutes>"
                )
            )
            sys.exit(1)
        cmd_config_idle(args[1], args[2])
    else:
        print(red(f"Unknown config subcommand: '{sub}'"))
        sys.exit(1)


def cmd_config_reranker(state: str) -> None:
    """Toggle reranker enabled/disabled in install_config.json."""
    storage = _get_storage_dir_or_report("config reranker")
    if storage is None:
        return

    if state.lower() in ("on", "enable", "true", "1"):
        enabled = True
    elif state.lower() in ("off", "disable", "false", "0"):
        enabled = False
    else:
        print(red(f"Invalid state: '{state}'. Use 'on' or 'off'."))
        sys.exit(1)

    # Read existing reranker config to preserve model_name, recall_k, and
    # min_reranker_score across enable/disable toggles.
    from reranking.reranker_catalog import DEFAULT_RERANKER_MODEL
    existing = load_reranker_config(storage_dir=storage)
    model_name = existing.get("model_name", DEFAULT_RERANKER_MODEL)
    recall_k = existing.get("recall_k", 50)
    min_reranker_score = existing.get("min_reranker_score", 0.0)

    save_reranker_config(
        model_name=model_name,
        enabled=enabled,
        recall_k=recall_k,
        min_reranker_score=min_reranker_score,
        storage_dir=storage,
    )

    status = green("enabled") if enabled else yellow("disabled")
    print(f"Reranker {status} (model: {model_name}, recall_k={recall_k})")


def cmd_config_model(short_name: str) -> None:
    """Switch the active embedding model in install_config.json."""
    from embeddings.model_catalog import MODEL_CATALOG, EMBEDDING_SHORT_NAMES

    storage = _get_storage_dir_or_report("config model")
    if storage is None:
        return

    # Resolve short name → full HuggingFace model name
    if short_name in EMBEDDING_SHORT_NAMES:
        full_name = EMBEDDING_SHORT_NAMES[short_name]
    elif short_name in MODEL_CATALOG:
        full_name = short_name
    else:
        print(red(f"Unknown model: '{short_name}'"))
        print(f"Run '{cyan(_cmd_prefix())} models list' to see available models.")
        sys.exit(1)

    # Warn if the model does not appear to be downloaded yet
    models_dir = storage / "models"
    # HuggingFace hub caches models as "models--<org>--<model>" directories
    sanitised = "models--" + full_name.replace("/", "--")
    try:
        downloaded = models_dir.is_dir() and any(
            p.name == sanitised or p.name.startswith(sanitised)
            for p in models_dir.iterdir()
            if p.is_dir()
        )
    except OSError:
        downloaded = False
    if not downloaded:
        print(yellow(f"Warning: '{full_name}' doesn't appear to be downloaded yet."))
        print(f"  Download it first: {cyan(f'{_cmd_prefix()} models install {short_name}')}")

    save_local_install_config(full_name, storage_dir=storage)
    print(f"Embedding model set to: {green(full_name)}")
    print(f"Restart the MCP server for the change to take effect.")


def cmd_config_reranker_model(short_name: str) -> None:
    """Switch the reranker model without changing enabled/disabled state."""
    from reranking.reranker_catalog import RERANKER_CATALOG, RERANKER_SHORT_NAMES

    storage = _get_storage_dir_or_report("config reranker model")
    if storage is None:
        return

    if short_name in RERANKER_SHORT_NAMES:
        full_name = RERANKER_SHORT_NAMES[short_name]
    elif short_name in RERANKER_CATALOG:
        full_name = short_name
    else:
        print(red(f"Unknown reranker model: '{short_name}'"))
        print(f"Run '{cyan(_cmd_prefix())} models list' to see available reranker models.")
        sys.exit(1)

    # Preserve enabled state, recall_k, and min_reranker_score.
    existing = load_reranker_config(storage_dir=storage)
    enabled = existing.get("enabled", False)
    recall_k = existing.get("recall_k", 50)
    min_reranker_score = existing.get("min_reranker_score", 0.0)

    save_reranker_config(
        model_name=full_name,
        enabled=enabled,
        recall_k=recall_k,
        min_reranker_score=min_reranker_score,
        storage_dir=storage,
    )
    status = green("enabled") if enabled else yellow("disabled")
    print(f"Reranker model set to: {green(full_name)} [{status}]")
    print(f"Restart the MCP server for the change to take effect.")


def cmd_config_reranker_min_score(raw_value: str) -> None:
    """Set reranker min score threshold in install_config.json."""
    from reranking.reranker_catalog import DEFAULT_RERANKER_MODEL

    storage = _get_storage_dir_or_report("config reranker min-score")
    if storage is None:
        return

    try:
        min_reranker_score = float(raw_value)
    except ValueError:
        print(red(f"Invalid min-score: '{raw_value}'. Expected a number between 0.0 and 1.0."))
        sys.exit(1)

    if not 0.0 <= min_reranker_score <= 1.0:
        print(red(f"Invalid min-score: {min_reranker_score}. Use a value between 0.0 and 1.0."))
        sys.exit(1)

    existing = load_reranker_config(storage_dir=storage)
    model_name = existing.get("model_name", DEFAULT_RERANKER_MODEL)
    enabled = existing.get("enabled", False)
    recall_k = existing.get("recall_k", 50)

    save_reranker_config(
        model_name=model_name,
        enabled=enabled,
        recall_k=recall_k,
        min_reranker_score=min_reranker_score,
        storage_dir=storage,
    )

    status = green("enabled") if enabled else yellow("disabled")
    print(
        f"Reranker min-score set to: {green(str(min_reranker_score))} "
        f"(model: {model_name}, {status}, recall_k={recall_k})"
    )
    print("Restart the MCP server for the change to take effect.")


def cmd_config_idle(kind: str, raw_minutes: str) -> None:
    """Set idle offload/unload thresholds in install_config.json."""
    storage = _get_storage_dir_or_report("config idle")
    if storage is None:
        return

    kind_lower = kind.lower()
    if kind_lower not in ("offload", "unload"):
        print(red(f"Unknown idle kind: '{kind}'. Use 'offload' or 'unload'."))
        sys.exit(1)

    try:
        minutes = int(raw_minutes)
    except ValueError:
        print(red(f"Invalid minutes: '{raw_minutes}'. Expected a non-negative integer."))
        sys.exit(1)

    if minutes < 0:
        print(red(f"Invalid minutes: {minutes}. Must be >= 0 (0 = disabled)."))
        sys.exit(1)

    if kind_lower == "offload":
        save_idle_config(idle_offload_minutes=minutes, storage_dir=storage)
        label = "warm CPU offload"
    else:
        save_idle_config(idle_unload_minutes=minutes, storage_dir=storage)
        label = "cold full unload"

    if minutes == 0:
        print(f"Idle {label}: {yellow('disabled')}")
    else:
        print(f"Idle {label}: {green(str(minutes))} minute(s)")
    print("Restart the MCP server for the change to take effect.")


# ── UI Dashboard commands ─────────────────────────────────────────────

# Default port matches ui_server/server.py and CODE_SEARCH_UI_PORT.
_DEFAULT_UI_PORT = 7432
_DASHBOARD_START_TIMEOUT_S = 60.0


def _ui_server_cmd_parts() -> list[str]:
    """Build the ``uv run`` command list for the UI server.

    Uses the installed ``agent-context-local-ui`` entry-point when available;
    falls back to ``uv run ... python ui_server/server.py`` for source checkouts.
    """
    if _is_ui_entry_point_installed():
        return ["agent-context-local-ui"]
    install_dir = get_default_install_dir()
    extra_flag = _gpu_extra_flag().strip()
    cmd: list[str] = ["uv", "run"]
    if extra_flag:
        cmd += extra_flag.split()
    cmd += ["--directory", str(install_dir), "python", "ui_server/server.py"]
    return cmd


def _ui_port() -> int:
    """Return the configured UI server port (``CODE_SEARCH_UI_PORT`` or 7432).

    Falls back to the default port and prints a warning if the env value is
    not a valid integer so ``open-dashboard`` never crashes on bad config.
    """
    raw = os.environ.get("CODE_SEARCH_UI_PORT", "")
    if raw:
        try:
            return int(raw)
        except ValueError:
            print(yellow(
                f"Warning: CODE_SEARCH_UI_PORT={raw!r} is not a valid integer — "
                f"using default port {_DEFAULT_UI_PORT}."
            ))
    return _DEFAULT_UI_PORT


def _is_dashboard_running(port: int) -> bool:
    """Return True if a server is already accepting connections on *port*."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _is_port_in_use(port: int) -> bool:
    """True if *port* is already bound by any process (even one not yet accepting connections)."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False  # bind succeeded → port is free
        except OSError:
            return True   # bind failed → port is occupied


def _build_launch_cmd_str() -> str:
    """Return the launch command as a single printable string."""
    return " ".join(_ui_server_cmd_parts())


def cmd_open_dashboard() -> None:
    """Launch the Agent Context web dashboard and open it in the default browser.

    If the server is already running on the configured port the browser is
    opened directly without starting a second instance.
    """
    port = _ui_port()
    url = f"http://127.0.0.1:{port}"

    if _is_dashboard_running(port):
        print(f"{green('✓')} Dashboard already running at {cyan(url)}")
        print("  Opening browser…")
        import webbrowser
        webbrowser.open(url)
        print(f"  If the browser does not open, navigate to: {cyan(url)}")
        return

    # Port is not accepting connections — check if it's bound by a starting/alien process.
    if _is_port_in_use(port):
        print(red(f"✗ Port {port} is already in use by another process (not the dashboard)."))
        print(f"  Kill the process holding port {port} or set {cyan('CODE_SEARCH_UI_PORT')} to a free port.")
        return

    # Start the server as an independent background process so the CLI
    # returns immediately without blocking the terminal.
    cmd = _ui_server_cmd_parts() + ["--no-browser"]
    print("  Starting dashboard server…")
    if is_windows():
        proc = subprocess.Popen(
            cmd,
            creationflags=0x08000000,  # CREATE_NO_WINDOW — avoids console popup
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # detach from terminal so it keeps running
        )
    print(f"  Server PID {proc.pid} — waiting for it to become ready…")
    print("  (first run may take up to 60 s while the embedding model loads)", flush=True)

    import time
    deadline = time.monotonic() + _DASHBOARD_START_TIMEOUT_S
    started = False
    while time.monotonic() < deadline:
        time.sleep(0.4)
        rc = proc.poll()
        if rc is not None:
            # Process exited before becoming ready
            print(red(f"✗ Server process exited unexpectedly (exit code {rc})."))
            print("  Check for port conflicts or a missing dependency.")
            return
        if _is_dashboard_running(port):
            started = True
            break

    if not started:
        install_dir = get_default_install_dir()
        extra = _gpu_extra_flag()
        print(red(f"✗ Dashboard did not start within {int(_DASHBOARD_START_TIMEOUT_S)} seconds."))
        print(f"  Start it manually: {cyan(f'uv run {extra}--directory {install_dir} python ui_server/server.py')}")
        return

    print(f"{green('✓')} Dashboard running at {cyan(url)}")
    print("  Opening browser…")
    import webbrowser
    webbrowser.open(url)
    print(f"  If the browser does not open, navigate to: {cyan(url)}")


def cmd_create_shortcut() -> None:
    """Create a desktop shortcut / application launcher for the Agent Context Dashboard.

    Creates a platform-appropriate shortcut so the dashboard can be launched
    without opening a terminal:

    - **Linux**   — XDG ``.desktop`` file in ``~/.local/share/applications/``
                    (appears in the application menu).  Also placed on
                    ``~/Desktop/`` when that directory exists.
    - **macOS**   — Minimal ``.app`` bundle in ``~/Applications/``.
    - **Windows** — ``.lnk`` shortcut on the Desktop (created via PowerShell).
    - **WSL**     — Linux ``.desktop`` file *and* an optional Windows
                    ``.lnk`` shortcut accessible from the Windows Desktop.
    """
    platform_label = get_platform_label()
    print(bold("Creating Agent Context Dashboard shortcut"))
    print(f"  Platform: {platform_label}")
    print()
    if is_wsl():
        _create_shortcut_wsl()
    elif is_windows():
        _create_shortcut_windows()
    elif platform.system() == "Darwin":
        _create_shortcut_macos()
    else:
        _create_shortcut_linux()


def _create_shortcut_linux(*, also_desktop: bool = True) -> None:
    """Create an XDG .desktop launcher (Linux)."""
    install_dir = get_default_install_dir()
    # _gpu_extra_flag() already returns "--extra <name> " (with the flag prefix).
    # Strip trailing whitespace only; do NOT add another "--extra".
    extra_flag = _gpu_extra_flag().strip()

    # Use the absolute uv path so graphical launchers that don't inherit $PATH
    # can still find the binary.
    uv_bin = shutil.which("uv") or "uv"
    if _is_ui_entry_point_installed():
        exec_cmd = shutil.which("agent-context-local-ui") or "agent-context-local-ui"
    else:
        extra_parts = f"{extra_flag} " if extra_flag else ""
        exec_cmd = f"{shlex.quote(uv_bin)} run {extra_parts}--directory {shlex.quote(str(install_dir))} python ui_server/server.py"

    # Escape single quotes for the outer bash -c '...' wrapper in the .desktop Exec line.
    exec_cmd_escaped = exec_cmd.replace("'", "'\\''")

    desktop_content = (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=Agent Context Dashboard\n"
        "GenericName=Code Search Dashboard\n"
        "Comment=Open the Agent Context local semantic code search dashboard\n"
        f"Exec=bash -c '{exec_cmd_escaped}'\n"
        "Icon=utilities-terminal\n"
        "Terminal=false\n"
        "Categories=Development;Utility;\n"
        "Keywords=code;search;ai;agent;semantic;\n"
        "StartupNotify=true\n"
    )

    # Install to the XDG applications directory so it appears in the app menu.
    apps_dir = Path.home() / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    app_file = apps_dir / "agent-context-dashboard.desktop"
    app_file.write_text(desktop_content, encoding="utf-8")
    app_file.chmod(0o755)
    print(f"{green('✓')} Application launcher: {app_file}")

    # Refresh the desktop database so the launcher appears without re-login.
    if shutil.which("update-desktop-database"):
        try:
            subprocess.run(
                ["update-desktop-database", str(apps_dir)],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError:
            pass  # Non-fatal; entry appears after next session login.

    # Also place a copy on ~/Desktop when that directory exists.
    if also_desktop:
        desktop_dir = Path.home() / "Desktop"
        if desktop_dir.is_dir():
            desktop_shortcut = desktop_dir / "agent-context-dashboard.desktop"
            desktop_shortcut.write_text(desktop_content, encoding="utf-8")
            desktop_shortcut.chmod(0o755)
            print(f"{green('✓')} Desktop shortcut:      {desktop_shortcut}")
        else:
            print("  (~/Desktop not found — only the application launcher was created)")

    print()
    print("  'Agent Context Dashboard' now appears in your application menu.")
    print(f"  Command line: {cyan(_build_launch_cmd_str())}")


def _create_shortcut_macos() -> None:
    """Create a minimal .app bundle in ~/Applications (macOS)."""
    install_dir = get_default_install_dir()
    # _gpu_extra_flag() already returns "--extra <name> " (with the flag prefix).
    # Strip trailing whitespace only; do NOT add another "--extra".
    extra_flag = _gpu_extra_flag().strip()

    uv_bin = shutil.which("uv") or "uv"
    if _is_ui_entry_point_installed():
        launch_cmd = shutil.which("agent-context-local-ui") or "agent-context-local-ui"
    else:
        extra_parts = f"{extra_flag} " if extra_flag else ""
        launch_cmd = f"{shlex.quote(uv_bin)} run {extra_parts}--directory {shlex.quote(str(install_dir))} python ui_server/server.py"

    app_dir = Path.home() / "Applications" / "Agent Context Dashboard.app"
    macos_dir = app_dir / "Contents" / "MacOS"
    macos_dir.mkdir(parents=True, exist_ok=True)

    # Minimal Info.plist so macOS recognises the bundle.
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"'
        ' "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        "    <key>CFBundleExecutable</key><string>AppRun</string>\n"
        "    <key>CFBundleIdentifier</key><string>local.agent-context.dashboard</string>\n"
        "    <key>CFBundleName</key><string>Agent Context Dashboard</string>\n"
        "    <key>CFBundleDisplayName</key><string>Agent Context Dashboard</string>\n"
        "    <key>CFBundleVersion</key><string>1.0</string>\n"
        "    <key>CFBundlePackageType</key><string>APPL</string>\n"
        "    <key>LSUIElement</key><false/>\n"
        "</dict></plist>\n"
    )
    (app_dir / "Contents" / "Info.plist").write_text(plist, encoding="utf-8")

    # The executable shell script that launches the server.
    app_run = macos_dir / "AppRun"
    app_run.write_text(
        "#!/usr/bin/env bash\n"
        f"exec {launch_cmd}\n",
        encoding="utf-8",
    )
    app_run.chmod(0o755)

    print(f"{green('✓')} Application bundle created: {app_dir}")
    print()
    print("  Open Finder → ~/Applications to find 'Agent Context Dashboard'.")
    print("  Drag it to the Dock for one-click access.")
    print(f"  Command line: {cyan(launch_cmd)}")


def _create_shortcut_windows() -> None:
    """Create a .lnk shortcut on the Windows Desktop via PowerShell."""
    install_dir = get_default_install_dir()
    # _gpu_extra_flag() already returns "--extra <name> " (with the flag prefix).
    # Strip trailing whitespace only; do NOT add another "--extra".
    extra_flag = _gpu_extra_flag().strip()

    uv_bin = shutil.which("uv") or "uv"
    if _is_ui_entry_point_installed():
        target = shutil.which("agent-context-local-ui") or "agent-context-local-ui"
        arguments = ""
    else:
        extra_parts = f"{extra_flag} " if extra_flag else ""
        target = "cmd.exe"
        # /c start "" keeps cmd.exe hidden after launching the background process.
        arguments = (
            f'/c start "" "{uv_bin}" run {extra_parts}'
            f'--directory "{install_dir}" python ui_server/server.py'
        )

    def _ps_str(s: str) -> str:
        # Escape single-quotes inside PowerShell string literals.
        return s.replace("'", "''")

    # Use the Shell API to resolve the actual Desktop path — handles OneDrive
    # folder redirection, enterprise policies, and non-standard setups.
    ps_script = (
        "$Desktop = [Environment]::GetFolderPath('Desktop')\n"
        "if (-not $Desktop -or -not (Test-Path $Desktop)) {\n"
        "  Write-Error 'Could not resolve Desktop folder path.'\n"
        "  exit 1\n"
        "}\n"
        "$ShortcutPath = Join-Path $Desktop 'Agent Context Dashboard.lnk'\n"
        "$WshShell = New-Object -ComObject WScript.Shell\n"
        "$Shortcut = $WshShell.CreateShortcut($ShortcutPath)\n"
        f"$Shortcut.TargetPath = '{_ps_str(target)}'\n"
        f"$Shortcut.Arguments = '{_ps_str(arguments)}'\n"
        "$Shortcut.Description = 'Open Agent Context Local Web Dashboard'\n"
        f"$Shortcut.WorkingDirectory = '{_ps_str(str(install_dir))}'\n"
        "$Shortcut.Save()\n"
        "Write-Output $ShortcutPath\n"
    )

    # Fallback display path — the actual path is determined by PowerShell above.
    shortcut_display = str(Path.home() / "Desktop" / "Agent Context Dashboard.lnk")

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            check=True, capture_output=True, text=True,
        )
        actual_path = (result.stdout or "").strip() or shortcut_display
        print(f"{green('✓')} Desktop shortcut created: {actual_path}")
    except subprocess.CalledProcessError as exc:
        err_detail = (exc.stderr or "").strip()
        print(red(f"✗ Could not create Windows shortcut (PowerShell exit {exc.returncode})."))
        if err_detail:
            print(f"  PowerShell error: {err_detail}")
        print("  Create it manually: right-click Desktop → New → Shortcut")
        return
    except FileNotFoundError:
        print(red("✗ powershell.exe not found in PATH — cannot create shortcut automatically."))
        print("  Create it manually: right-click Desktop → New → Shortcut")
        return

    print()
    print("  Double-click 'Agent Context Dashboard' on your Desktop to open it.")
    print(f"  Command line: {cyan(_build_launch_cmd_str())}")


def _create_shortcut_wsl() -> None:
    """Create a Linux .desktop file and optionally a Windows .lnk shortcut (WSL)."""
    print("WSL detected — creating Linux application launcher…")
    _create_shortcut_linux()

    # Also try to place a shortcut on the Windows Desktop so it's reachable from Windows.
    print()
    print("Attempting to create Windows Desktop shortcut via PowerShell…")
    windows_user_dirs = _wsl_windows_user_dirs()
    if not windows_user_dirs:
        print(yellow("  Could not locate Windows user directory — skipping Windows shortcut."))
        return

    install_dir = get_default_install_dir()
    # _gpu_extra_flag() already returns "--extra <name> " (with the flag prefix).
    # Strip trailing whitespace only; do NOT add another "--extra".
    extra_flag = _gpu_extra_flag().strip()
    uv_bin = shutil.which("uv") or "uv"
    extra_parts = f"{extra_flag} " if extra_flag else ""

    # The server runs inside WSL, so we target wsl.exe from the Windows side.
    wsl_launch = f"{shlex.quote(uv_bin)} run {extra_parts}--directory {shlex.quote(str(install_dir))} python ui_server/server.py"

    def _ps_str(s: str) -> str:
        return s.replace("'", "''")

    for win_user_dir in windows_user_dirs[:1]:  # Only use the first matched Windows user
        win_desktop = win_user_dir / "Desktop"
        if not win_desktop.is_dir():
            continue

        shortcut_path = win_desktop / "Agent Context Dashboard.lnk"
        ps_script = (
            "$WshShell = New-Object -ComObject WScript.Shell\n"
            f"$Shortcut = $WshShell.CreateShortcut('{_ps_str(str(shortcut_path))}')\n"
            "$Shortcut.TargetPath = 'wsl.exe'\n"
            f"$Shortcut.Arguments = '-- {_ps_str(wsl_launch)}'\n"
            "$Shortcut.Description = 'Open Agent Context Local Web Dashboard (WSL)'\n"
            "$Shortcut.Save()\n"
        )
        try:
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                check=True, capture_output=True, text=True,
            )
            print(f"{green('✓')} Windows Desktop shortcut: {shortcut_path}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(yellow("  Could not create Windows shortcut (PowerShell unavailable or permission denied)."))
        break


# ── Entry point ───────────────────────────────────────────────────────

COMMANDS = {
    "help": cmd_help,
    "--help": cmd_help,
    "-h": cmd_help,
    "doctor": cmd_doctor,
    "version": cmd_version,
    "--version": cmd_version,
    "status": cmd_status,
    "paths": cmd_paths,
    "setup-guide": cmd_setup_guide,
    "setup-mcp": cmd_setup_mcp,
    "gpu-setup": cmd_gpu_setup,
    "troubleshoot": cmd_troubleshoot,
    "mcp-check": cmd_mcp_check,
    "models": cmd_models,
    "config": cmd_config,
    "open-dashboard": cmd_open_dashboard,
    "create-shortcut": cmd_create_shortcut,
}


def _suggest_command(unknown: str) -> str:
    """Return a suggestion for a mistyped command, or empty string."""
    # Common near-miss mappings: space vs hyphen, partial matches
    aliases = {
        "setup": "setup-guide",
        "guide": "setup-guide",
        "setupguide": "setup-guide",
        "setup_guide": "setup-guide",
        "model": "models",
        "reranker": "config reranker <on|off>",
        "threshold": "config reranker min-score <0.0-1.0>",
        "install": "models install <short-name>",
        "list": "models list",
        "active": "models active",
        "fix": "troubleshoot",
        "debug": "doctor",
        "diag": "doctor",
        "diagnose": "doctor",
        "info": "version",
        "mcp": "mcp-check",
        "mcpcheck": "mcp-check",
        "mcp_check": "mcp-check",
        "setupmcp": "setup-mcp",
        "setup_mcp": "setup-mcp",
        "mcpsetup": "setup-mcp",
        "gpu": "gpu-setup",
        "gpusetup": "gpu-setup",
        "gpu_setup": "gpu-setup",
        "cuda": "gpu-setup",
        "open": "open-dashboard",
        "dashboard": "open-dashboard",
        "ui": "open-dashboard",
        "opendashboard": "open-dashboard",
        "open_dashboard": "open-dashboard",
        "shortcut": "create-shortcut",
        "icon": "create-shortcut",
        "desktop": "create-shortcut",
        "launcher": "create-shortcut",
        "createshortcut": "create-shortcut",
        "create_shortcut": "create-shortcut",
    }
    return aliases.get(unknown.lower().replace("-", "").replace("_", ""), "")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        cmd_help()
        return

    command = args[0].lower()
    handler = COMMANDS.get(command)
    if handler is None:
        print(red(f"Unknown command: '{command}'"))
        suggestion = _suggest_command(command)
        if suggestion:
            print(f"  Did you mean: {cyan(suggestion)}?")
        print(f"Run '{cyan(f'{_cmd_prefix()} help')}' to see available commands.\n")
        sys.exit(1)

    handler()


if __name__ == "__main__":
    main()
