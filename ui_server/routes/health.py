"""Health check endpoint for the UI server REST API."""

from fastapi import APIRouter
from pydantic import BaseModel

try:
    from common_utils import VERSION
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from common_utils import VERSION

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return server health status and version."""
    return HealthResponse(status="ok", version=VERSION)
