"""Search endpoint — POST /api/v1/search.

Thin wrapper over CodeSearchServer.search_code().  Accepts JSON with the
same knobs exposed by the MCP tool and returns structured JSON results
that the React frontend can render directly.
"""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ui_server.dependencies import get_server

logger = logging.getLogger(__name__)

router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(..., description="Natural language or keyword search query")
    k: int = Field(5, ge=1, le=50, description="Number of results to return")
    file_pattern: Optional[str] = Field(None, description="Glob pattern to filter files")
    chunk_type: Optional[str] = Field(None, description="Filter by chunk type: function, class, method, etc.")
    include_context: bool = Field(True, description="Include graph relationship hints in results")
    project_path: Optional[str] = Field(None, description="Target project path; uses active project if omitted")
    max_results_per_file: Optional[int] = Field(None, ge=1, description="Cap results from any single file")


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
    data = json.loads(raw)

    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"])

    return SearchResponse(
        query=data.get("query", request.query),
        project=data.get("project"),
        results=data.get("results", []),
        graph_enriched=data.get("graph_enriched", False),
        result_count=len(data.get("results", [])),
    )
