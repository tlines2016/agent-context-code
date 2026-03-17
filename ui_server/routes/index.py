"""Index management endpoints.

GET    /api/v1/index/status   → get_index_status()
POST   /api/v1/index/run      → index_directory()
DELETE /api/v1/index/clear    → clear_index()
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ui_server.dependencies import get_server

logger = logging.getLogger(__name__)

router = APIRouter()

# Maximum number of file-pattern entries accepted in a single request.
_MAX_FILE_PATTERNS = 50


class IndexRequest(BaseModel):
    directory_path: str = Field(..., min_length=1, max_length=500)
    project_name: Optional[str] = Field(None, max_length=200)
    file_patterns: Optional[List[str]] = None
    incremental: bool = True

    @field_validator("directory_path")
    @classmethod
    def directory_path_must_be_absolute(cls, v: str) -> str:
        """Require an absolute path to prevent unintended relative-path traversal."""
        p = Path(v)
        if not p.is_absolute():
            raise ValueError(
                "directory_path must be an absolute file-system path."
            )
        return str(p)  # normalise (removes trailing slashes, etc.)

    @field_validator("file_patterns")
    @classmethod
    def file_patterns_bounded(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Limit the number of glob patterns and each pattern's length."""
        if v is None:
            return v
        if len(v) > _MAX_FILE_PATTERNS:
            raise ValueError(
                f"file_patterns must contain at most {_MAX_FILE_PATTERNS} entries."
            )
        for pattern in v:
            if len(pattern) > 200:
                raise ValueError("Each file pattern must be at most 200 characters.")
        return v


@router.get("/index/status")
async def index_status(server=Depends(get_server)) -> dict:
    """Return current index health and statistics."""
    raw = server.get_index_status()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Malformed response from backend: %.200s", raw)
        raise HTTPException(status_code=502, detail="Backend returned invalid JSON")
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
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Malformed response from backend: %.200s", raw)
        raise HTTPException(status_code=502, detail="Backend returned invalid JSON")
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    return data


@router.delete("/index/clear")
async def clear_index(server=Depends(get_server)) -> dict:
    """Clear the active project's index (vector store, graph, and snapshot)."""
    raw = server.clear_index()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Malformed response from backend: %.200s", raw)
        raise HTTPException(status_code=502, detail="Backend returned invalid JSON")
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    return data
