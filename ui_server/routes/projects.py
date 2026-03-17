"""Projects endpoints — GET/POST /api/v1/projects.

Wraps CodeSearchServer.list_projects() and switch_project().
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ui_server.dependencies import get_server

logger = logging.getLogger(__name__)

router = APIRouter()


class SwitchProjectRequest(BaseModel):
    project_path: str = Field(..., min_length=1, max_length=500)

    @field_validator("project_path")
    @classmethod
    def project_path_must_be_absolute(cls, v: str) -> str:
        """Require an absolute path to prevent unintended relative-path traversal."""
        p = Path(v)
        if not p.is_absolute():
            raise ValueError("project_path must be an absolute file-system path.")
        return str(p)


@router.get("/projects")
async def list_projects(server=Depends(get_server)) -> dict:
    """Return all indexed projects with their metadata."""
    raw = server.list_projects()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Malformed response from backend: %.200s", raw)
        raise HTTPException(status_code=502, detail="Backend returned invalid JSON")
    if "error" in data:
        raise HTTPException(status_code=500, detail=data["error"])
    return data


@router.post("/projects/switch")
async def switch_project(
    request: SwitchProjectRequest,
    server=Depends(get_server),
) -> dict:
    """Set the active project by path."""
    raw = server.switch_project(request.project_path)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Malformed response from backend: %.200s", raw)
        raise HTTPException(status_code=502, detail="Backend returned invalid JSON")
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    return data
