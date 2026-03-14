"""Models endpoint — GET /api/v1/models.

Returns the full embedding model catalog so the frontend can populate
the model-selection dropdown in the Settings form without hard-coding
model names.
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/models")
async def list_models() -> Dict[str, Any]:
    """Return available embedding models from the catalog."""
    try:
        from embeddings.model_catalog import MODEL_CATALOG
        models: List[Dict[str, Any]] = []
        for model_name, config in MODEL_CATALOG.items():
            models.append({
                "model_name": model_name,
                "short_name": config.short_name,
                "description": config.description,
                "recommended_for": config.recommended_for,
                "embedding_dimension": config.embedding_dimension,
                "gpu_default": config.gpu_default,
            })
        return {"models": models, "count": len(models)}
    except Exception as exc:
        logger.error("Failed to load model catalog: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to load model catalog: {exc}")
