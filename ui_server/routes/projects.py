"""Projects endpoints — GET/POST /api/v1/projects.

Wraps CodeSearchServer.list_projects() and switch_project().
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ui_server.dependencies import get_server

logger = logging.getLogger(__name__)

router = APIRouter()


class SwitchProjectRequest(BaseModel):
    project_path: str


@router.get("/projects")
async def list_projects(server=Depends(get_server)) -> dict:
    """Return all indexed projects with their metadata."""
    raw = server.list_projects()
    data = json.loads(raw)
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
    data = json.loads(raw)
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])
    return data
