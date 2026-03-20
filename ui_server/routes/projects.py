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

def _error_status(detail: str) -> int:
    lowered = detail.lower()
    if "not registered" in lowered or "does not exist" in lowered:
        return 404
    return 500


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


class ProjectActionRequest(BaseModel):
    project_path: str = Field(..., min_length=1, max_length=500)

    @field_validator("project_path")
    @classmethod
    def project_path_must_be_absolute(cls, v: str) -> str:
        """Require an absolute path to avoid ambiguous destructive actions."""
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


def _clear_project_index_impl(project_path: str, server) -> dict:
    raw = server.clear_project_index(project_path)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Malformed response from backend: %.200s", raw)
        raise HTTPException(status_code=502, detail="Backend returned invalid JSON")
    if "error" in data:
        raise HTTPException(status_code=_error_status(data["error"]), detail=data["error"])
    if data.get("success") is False:
        raise HTTPException(status_code=400, detail=data.get("message", "Failed to clear project index"))
    return data


@router.delete("/projects/index")
async def clear_project_index_delete(
    request: ProjectActionRequest,
    server=Depends(get_server),
) -> dict:
    """Clear index data for a single project without removing project metadata."""
    return _clear_project_index_impl(request.project_path, server)


@router.post("/projects/index")
async def clear_project_index_post(
    request: ProjectActionRequest,
    server=Depends(get_server),
) -> dict:
    """POST alias for clear-index action for broader client compatibility."""
    return _clear_project_index_impl(request.project_path, server)


def _remove_project_impl(project_path: str, server) -> dict:
    raw = server.remove_project(project_path)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Malformed response from backend: %.200s", raw)
        raise HTTPException(status_code=502, detail="Backend returned invalid JSON")
    if "error" in data:
        raise HTTPException(status_code=_error_status(data["error"]), detail=data["error"])
    if data.get("success") is False:
        raise HTTPException(status_code=400, detail=data.get("message", "Failed to remove project"))
    return data


@router.delete("/projects/remove")
async def remove_project_delete(
    request: ProjectActionRequest,
    server=Depends(get_server),
) -> dict:
    """Remove a project and all associated index artifacts."""
    return _remove_project_impl(request.project_path, server)


@router.post("/projects/remove")
async def remove_project_post(
    request: ProjectActionRequest,
    server=Depends(get_server),
) -> dict:
    """POST alias for remove-project action for broader client compatibility."""
    return _remove_project_impl(request.project_path, server)
