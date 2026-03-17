"""Search endpoint — POST /api/v1/search.

Thin wrapper over CodeSearchServer.search_code().  Accepts JSON with the
same knobs exposed by the MCP tool and returns structured JSON results
that the React frontend can render directly.
"""

import json
import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ui_server.dependencies import get_server

logger = logging.getLogger(__name__)

router = APIRouter()

# Allowed characters for chunk_type filter — alphanumeric plus underscore only.
_CHUNK_TYPE_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


class SearchRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language or keyword search query",
    )
    k: int = Field(5, ge=1, le=50, description="Number of results to return")
    file_pattern: Optional[str] = Field(
        None,
        max_length=500,
        description="Glob pattern to filter files",
    )
    chunk_type: Optional[str] = Field(
        None,
        max_length=100,
        description="Filter by chunk type: function, class, method, etc.",
    )
    include_context: bool = Field(True, description="Include graph relationship hints in results")
    project_path: Optional[str] = Field(
        None,
        max_length=500,
        description="Target project path; uses active project if omitted",
    )
    max_results_per_file: Optional[int] = Field(None, ge=1, le=50, description="Cap results from any single file")

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, v: str) -> str:
        """Reject queries that are entirely whitespace."""
        if not v.strip():
            raise ValueError("Search query must not be blank.")
        return v.strip()

    @field_validator("chunk_type")
    @classmethod
    def chunk_type_safe_chars(cls, v: Optional[str]) -> Optional[str]:
        """Allow only identifier-safe characters for chunk_type to prevent injection."""
        if v is None:
            return v
        if not _CHUNK_TYPE_RE.match(v):
            raise ValueError(
                "chunk_type must contain only letters, digits, and underscores."
            )
        return v


class SearchResponse(BaseModel):
    query: str
    project: Optional[str]
    results: List[dict]
    graph_enriched: bool = False
    result_count: int


@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    server=Depends(get_server),
) -> SearchResponse:
    """Run a semantic/keyword search against the active project's index."""
    raw = server.search_code(
        query=request.query,
        k=request.k,
        file_pattern=request.file_pattern,
        chunk_type=request.chunk_type,
        include_context=request.include_context,
        project_path=request.project_path,
        max_results_per_file=request.max_results_per_file,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Malformed response from backend: %.200s", raw)
        raise HTTPException(status_code=502, detail="Backend returned invalid JSON")

    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])

    return SearchResponse(
        query=data.get("query", request.query),
        project=data.get("project"),
        results=data.get("results", []),
        graph_enriched=data.get("graph_enriched", False),
        result_count=len(data.get("results", [])),
    )
