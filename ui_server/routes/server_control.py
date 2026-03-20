"""Server control endpoints — POST /api/v1/server/restart and /server/restart-mcp.

Allows the frontend to trigger a graceful dashboard server restart so that
model/config changes take effect without manual intervention, and to stop
the MCP server process so Claude Code respawns it.
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
from typing import Any, Dict

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level flag checked by the server main loop after uvicorn exits.
_restart_requested = False


def is_restart_requested() -> bool:
    return _restart_requested


def clear_restart_flag() -> None:
    global _restart_requested
    _restart_requested = False


@router.post("/server/restart")
async def restart_server() -> Dict[str, Any]:
    """Signal the server to restart.

    The response is sent before shutdown begins so the client can
    start polling ``/api/v1/health`` for the new instance.
    """
    global _restart_requested
    _restart_requested = True
    logger.info("Restart requested via API — scheduling graceful shutdown…")

    # Schedule the actual signal after a short delay so the HTTP response
    # has time to be sent back to the client.
    loop = asyncio.get_running_loop()
    loop.call_later(0.5, _signal_shutdown)

    return {"message": "Server restarting — poll /api/v1/health until ready."}


@router.post("/server/restart-mcp")
async def restart_mcp_server() -> Dict[str, Any]:
    """Stop the MCP server process so Claude Code automatically restarts it.

    Finds running Python processes whose command line contains
    ``mcp_server/server.py`` (or the Windows backslash equivalent) and
    terminates them.  Claude Code monitors the MCP process and will
    respawn it on the next tool invocation.

    This endpoint is a no-op if no matching process is found.
    """
    my_pid = os.getpid()
    killed = 0

    if sys.platform == "win32":
        pids = _find_mcp_pids_windows()
    else:
        pids = _find_mcp_pids_unix()

    for pid in pids:
        if pid == my_pid:
            continue
        try:
            if sys.platform == "win32":
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode != 0:
                    logger.warning(
                        "taskkill PID %d exited %d: %s",
                        pid, result.returncode, result.stderr.strip(),
                    )
                    continue
            else:
                os.kill(pid, signal.SIGTERM)
            killed += 1
            logger.info("Stopped MCP server process PID %d", pid)
        except Exception:
            logger.warning("Failed to stop MCP process PID %d", pid, exc_info=True)

    if killed > 0:
        return {
            "message": f"Stopped {killed} MCP server process(es). Claude Code will restart it on next use.",
            "stopped": killed,
        }
    return {
        "message": "No running MCP server processes found.",
        "stopped": 0,
    }


def _find_mcp_pids_windows() -> list[int]:
    """Find PIDs of MCP server processes on Windows via PowerShell."""
    try:
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                (
                    "Get-CimInstance Win32_Process "
                    r"| Where-Object { $_.CommandLine -match 'mcp_server[\\/]server\.py' } "
                    "| ForEach-Object { $_.ProcessId }"
                ),
            ],
            capture_output=True, text=True, timeout=10,
        )
        return [int(p.strip()) for p in result.stdout.strip().split("\n") if p.strip().isdigit()]
    except Exception:
        logger.warning("Failed to enumerate MCP processes", exc_info=True)
        return []


def _find_mcp_pids_unix() -> list[int]:
    """Find PIDs of MCP server processes on Unix via pgrep."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", r"mcp_server/server\.py"],
            capture_output=True, text=True, timeout=10,
        )
        return [int(p.strip()) for p in result.stdout.strip().split("\n") if p.strip().isdigit()]
    except Exception:
        logger.warning("Failed to enumerate MCP processes", exc_info=True)
        return []


def _signal_shutdown() -> None:
    """Raise SIGINT in the current process to trigger uvicorn's graceful shutdown.

    Uses ``signal.raise_signal`` (Python 3.8+) rather than
    ``os.kill(os.getpid(), SIGINT)`` because on Windows the latter calls
    ``GenerateConsoleCtrlEvent(CTRL_C_EVENT, 0)`` which broadcasts to the
    entire console process group — terminating any parent terminal session.
    ``signal.raise_signal`` delivers the signal only to the current process.
    """
    try:
        signal.raise_signal(signal.SIGINT)
    except Exception:
        logger.exception("Failed to send shutdown signal")
