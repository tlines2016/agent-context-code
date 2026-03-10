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
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Add the parent directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common_utils import (
    VERSION,
    get_storage_dir,
    load_local_install_config,
    load_reranker_config,
    save_reranker_config,
)

INSTALL_SH_URL = "https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.sh"
INSTALL_PS1_URL = "https://raw.githubusercontent.com/tlines2016/agent-context-code/main/scripts/install.ps1"

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

    if torch.cuda.is_available():
        # Check if this is ROCm (AMD) or NVIDIA CUDA
        if hasattr(torch.version, "hip") and torch.version.hip:
            device_name = torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else "unknown"
            return f"AMD ROCm ({device_name})"
        else:
            device_name = torch.cuda.get_device_name(0) if torch.cuda.device_count() > 0 else "unknown"
            return f"NVIDIA CUDA ({device_name})"
    try:
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "Apple MPS"
    except Exception:
        pass
    return "CPU only"


# ── Sub-commands ──────────────────────────────────────────────────────

def cmd_help() -> None:
    """Print the main help message listing available commands and examples."""
    install_dir = get_default_install_dir()

    print(bold("AGENT Context Local (compat: Claude Context Local)") + f"  v{VERSION}")
    print("Local semantic code search for Claude Code via MCP.\n")

    print(bold("USAGE"))
    print(f"  python scripts/cli.py {cyan('<command>')}\n")

    print(bold("COMMANDS"))
    cmds = [
        ("help", "Show this help message"),
        ("doctor", "Check installation health and diagnose problems"),
        ("version", "Print version and platform info"),
        ("status", "Show index statistics and active project info"),
        ("paths", "Show all paths used by the tool"),
        ("setup-guide", "Print step-by-step setup instructions for your OS"),
        ("troubleshoot", "HuggingFace auth & model download help"),
        ("mcp-check", "Verify MCP server registration with Claude"),
        ("models list", "List available embedding and reranker models"),
        ("models active", "Show currently configured models"),
        ("models install", "Download a model by short name"),
        ("config reranker", "Toggle reranker on/off"),
    ]
    for name, desc in cmds:
        print(f"  {cyan(name):<20s} {desc}")

    print(f"\n{bold('EXAMPLES')}")
    print(f"  python scripts/cli.py doctor        # Verify installation")
    print(f"  python scripts/cli.py setup-guide    # Setup instructions")
    print(f"  python scripts/cli.py status         # Show project status\n")

    print(f"{bold('MCP SERVER')}")
    if is_windows():
        print(f"  uv run --directory \"{install_dir}\" python mcp_server/server.py")
    else:
        print(f"  uv run --directory {install_dir} python mcp_server/server.py")

    print(f"\nSee README.md for full documentation.")


def cmd_version() -> None:
    """Print version and platform information."""
    print(f"agent-context-code  {VERSION}")
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
        print(f"\n{bold('Claude config locations (checked in order):')}")
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

    print(f"\n{bold('Claude config locations (checked in order):')}")
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

    # 9. Claude CLI (WARNING)
    if shutil.which("claude"):
        print(f"  {green('✓')} Claude CLI found in PATH")
    else:
        msg = "Claude CLI not found in PATH – install from https://claude.ai/code"
        print(f"  {yellow('!')} {msg}")
        warnings.append(msg)

    # 10. GPU/device detection (informational)
    gpu_info = _detect_gpu_info()
    print(f"  {cyan('ℹ')} Compute device: {gpu_info}")

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

    Iterates ``~/.claude_code_search/projects/`` and prints each project's
    name, workspace path, chunk count, and file count from its ``stats.json``.
    """
    print(bold("Index Status\n"))
    storage = _get_storage_dir_or_report("status")
    if storage is None:
        return

    projects_dir = storage / "projects"

    if not projects_dir.is_dir():
        print("  No projects indexed yet.")
        print(f"  Use Claude Code to say: {cyan('index this codebase')}")
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
        print(f"   Default model: {cyan('Qwen/Qwen3-Embedding-0.6B')} {green('(open – no HF auth required)')}")

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
    print(bold("3. Register the MCP server"))
    print(f"   {yellow('Run this in your terminal, not inside a Claude Code session.')}\n")
    if is_windows():
        print(f"   {cyan(f'claude mcp add code-search --scope user -- uv run --directory \"{install_dir}\" python mcp_server/server.py')}\n")
    else:
        print(f"   {cyan(f'claude mcp add code-search --scope user -- uv run --directory {install_dir} python mcp_server/server.py')}\n")

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
    print(bold("4. Verify"))
    if is_windows():
        print(f"   {cyan(f'uv run --directory \"{install_dir}\" python scripts/cli.py doctor')}")
    else:
        print(f"   {cyan(f'uv run --directory {install_dir} python scripts/cli.py doctor')}")
    print(f"   {cyan('claude mcp list')}")
    print(f"   Look for: code-search … {green('✓ Connected')}\n")

    # Step 5 – Use
    print(bold("5. Index & search"))
    print(f"   Open Claude Code in your project directory and say:")
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
            print(f"    {cyan('$env:CODE_SEARCH_MODEL=\"Qwen/Qwen3-Embedding-0.6B\"')}")
        else:
            print(f"    {cyan('export CODE_SEARCH_MODEL=\"Qwen/Qwen3-Embedding-0.6B\"')}")
        print(f"    Then re-run the installer.\n")
    else:
        effective_model = current_model or "Qwen/Qwen3-Embedding-0.6B"
        print(f"  {green('✓')} Your model ({cyan(effective_model)}) does not require HuggingFace authentication.\n")

    # Troubleshooting
    print(bold("Troubleshooting"))
    if is_windows():
        print(f"  • Run {cyan(f'uv run --directory \"{install_dir}\" python scripts/cli.py doctor')} to diagnose issues")
    else:
        print(f"  • Run {cyan(f'uv run --directory {install_dir} python scripts/cli.py doctor')} to diagnose issues")
    print(f"  • Ensure Python >= 3.12 and uv are installed")
    print()


def cmd_troubleshoot() -> None:
    """Print troubleshooting guidance for model downloads and HuggingFace auth."""
    install_dir = get_default_install_dir()
    print(bold("Troubleshooting Guide\n"))

    # ── Model download issues ────────────────────────────────────────
    print(bold("1. Gated model access (google/embeddinggemma-300m)"))
    print()
    print(f"  The legacy default embedding model is {yellow('gated')} by Google on HuggingFace.")
    print(f"  The new default ({cyan('Qwen/Qwen3-Embedding-0.6B')}) is {green('not gated')}.")
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
    if is_windows():
        print(f"    {cyan(f'uv run --directory \"{install_dir}\" python scripts/cli.py doctor')}")
    else:
        print(f"    {cyan(f'uv run --directory {install_dir} python scripts/cli.py doctor')}")
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
    print(f"  The default model ({cyan('Qwen/Qwen3-Embedding-0.6B')}) does {green('not')} require")
    print(f"  HuggingFace gated access. If you switched to a gated model and")
    print(f"  are having auth issues, consider switching back:\n")
    if is_windows():
        print(f"    {cyan('$env:CODE_SEARCH_MODEL=\"Qwen/Qwen3-Embedding-0.6B\"')}")
    else:
        print(f"    {cyan('export CODE_SEARCH_MODEL=\"Qwen/Qwen3-Embedding-0.6B\"')}")
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
    """Check if the code-search MCP server is registered with Claude CLI."""
    install_dir = get_default_install_dir()

    print(bold("MCP Server Registration Check\n"))

    claude_path = shutil.which("claude")
    if not claude_path:
        print(f"  {red('✗')} Claude CLI not found in PATH")
        print(f"    Install from https://claude.ai/code\n")
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
            if is_windows():
                print(f"  {cyan(f'claude mcp add code-search --scope user -- uv run --directory \"{install_dir}\" python mcp_server/server.py')}")
            else:
                print(f"  {cyan(f'claude mcp add code-search --scope user -- uv run --directory {install_dir} python mcp_server/server.py')}")
    except FileNotFoundError:
        print(f"  {red('✗')} Could not run 'claude mcp list'")
    except subprocess.TimeoutExpired:
        print(f"  {yellow('!')} 'claude mcp list' timed out")
    except Exception as exc:
        print(f"  {yellow('!')} Could not check MCP status: {exc}")

    print()


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
        print(f"  Reranker:   {rr_name} [{status}] (recall_k={recall_k})")
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
        print(red("Usage: config reranker <on|off>"))
        sys.exit(1)

    sub = args[0].lower()
    if sub == "reranker":
        if len(args) < 2:
            print(red("Usage: config reranker <on|off>"))
            sys.exit(1)
        cmd_config_reranker(args[1])
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

    # Read existing reranker config to preserve model_name and recall_k
    existing = load_reranker_config(storage_dir=storage)
    model_name = existing.get("model_name", "Qwen/Qwen3-Reranker-4B")
    recall_k = existing.get("recall_k", 50)

    save_reranker_config(
        model_name=model_name,
        enabled=enabled,
        recall_k=recall_k,
        storage_dir=storage,
    )

    status = green("enabled") if enabled else yellow("disabled")
    print(f"Reranker {status} (model: {model_name}, recall_k={recall_k})")


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
    "troubleshoot": cmd_troubleshoot,
    "mcp-check": cmd_mcp_check,
    "models": cmd_models,
    "config": cmd_config,
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
        print(f"Run '{cyan('python scripts/cli.py help')}' to see available commands.\n")
        sys.exit(1)

    handler()


if __name__ == "__main__":
    main()
