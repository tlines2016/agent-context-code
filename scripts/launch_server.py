"""GPU-aware MCP server launcher utility.

Reads ``install_config.json`` to determine whether a GPU extra (e.g.
``cu128``) should be passed to ``uv run``, then execs the MCP server
with the correct flags.  Uses **only stdlib** — does not need the
project venv.

The install scripts auto-register with the correct ``--extra`` flag
directly.  This launcher is a convenience utility for manual use,
debugging, or third-party MCP clients that need a single stable command.

Usage::

    python scripts/launch_server.py [--verbose] [--transport sse]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _get_storage_dir() -> Path:
    """Mirror ``common_utils.get_storage_dir()`` using only stdlib."""
    raw = os.getenv("CODE_SEARCH_STORAGE", "")
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    home = Path.home()
    storage = home / ".agent_code_search"
    legacy = home / ".claude_code_search"
    if legacy.exists() and not storage.exists():
        return legacy
    return storage


def _load_gpu_extra(storage_dir: Path) -> str:
    """Return the GPU extra name (e.g. ``cu128``) or empty string."""
    config_path = storage_dir / "install_config.json"
    if not config_path.exists():
        return ""
    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        return config.get("gpu", {}).get("extra", "") or ""
    except (json.JSONDecodeError, OSError, KeyError):
        return ""


def main() -> None:
    project_dir = str(Path(__file__).resolve().parent.parent)
    storage_dir = _get_storage_dir()
    gpu_extra = _load_gpu_extra(storage_dir)

    # Build the uv run command
    cmd = ["uv", "run"]
    if gpu_extra:
        cmd += ["--extra", gpu_extra]
        print(f"[launch_server] GPU extra: --extra {gpu_extra}", file=sys.stderr)
    cmd += ["--directory", project_dir, "python", "mcp_server/server.py"]

    # Pass through any additional arguments (--verbose, --transport, etc.)
    cmd += sys.argv[1:]

    # Execute
    if os.name == "nt":
        # Windows: os.execvp doesn't work reliably, use subprocess
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    else:
        os.execvp("uv", cmd)


if __name__ == "__main__":
    main()
