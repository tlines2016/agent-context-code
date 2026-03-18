"""Server control endpoint — POST /api/v1/server/restart.

Allows the frontend to trigger a graceful server restart so that
model/config changes take effect without manual intervention.
"""

import asyncio
import logging
import os
import signal
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
