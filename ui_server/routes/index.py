"""Index management endpoints.

GET    /api/v1/index/status   → get_index_status()
POST   /api/v1/index/run      → index_directory()
DELETE /api/v1/index/clear    → clear_index()
"""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ui_server.dependencies import get_server

logger = logging.getLogger(__name__)

router = APIRouter()


class IndexRequest(BaseModel):
    directory_path: str
    project_name: Optional[str] = None
    file_patterns: Optional[List[str]] = None
    incremental: bool = True


@router.get("/index/status")
async def index_status(server=Depends(get_server)) -> dict:
    """Return current index health and statistics."""
    raw = server.get_index_status()
    data = json.loads(raw)
    if "error" in data:
        raise HTTPException(status_code=500, detail=data["error"])
    return data


@router.post("/index/run")
async def run_index(
    request: IndexRequest,
    server=Depends(get_server),
) -> dict:
    """Trigger indexing (incremental by default) for a directory."""
    raw = server.index_directory(
        directory_path=request.directory_path,
        project_name=request.project_name,
        file_patterns=request.file_patterns,
        incremental=request.incremental,
    )
    data = json.loads(raw)
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    return data


@router.delete("/index/clear")
async def clear_index(server=Depends(get_server)) -> dict:
    """Clear the active project's index (vector store, graph, and snapshot)."""
    raw = server.clear_index()
    data = json.loads(raw)
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    return data
