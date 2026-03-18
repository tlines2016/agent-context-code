"""Models and Rerankers endpoints — GET /api/v1/models, GET /api/v1/rerankers.

Returns the full embedding model and reranker catalogs so the frontend can
populate dropdowns in the Settings form without hard-coding model names.
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter()


def _detect_gpu_available() -> bool:
    """Return True if a CUDA or MPS GPU is accessible at runtime."""
    try:
        import torch
        return torch.cuda.is_available() or (
            hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        )
    except ImportError:
        return False


@router.get("/models")
async def list_models() -> Dict[str, Any]:
    """Return available embedding models from the catalog."""
    try:
        from embeddings.model_catalog import MODEL_CATALOG
        gpu_available = _detect_gpu_available()
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
        return {"models": models, "count": len(models), "gpu_available": gpu_available}
    except Exception as exc:
        logger.error("Failed to load model catalog: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to load model catalog: {exc}")


@router.get("/rerankers")
async def list_rerankers() -> Dict[str, Any]:
    """Return available reranker models from the catalog."""
    try:
        from reranking.reranker_catalog import RERANKER_CATALOG
        rerankers: List[Dict[str, Any]] = []
        for model_name, config in RERANKER_CATALOG.items():
            rerankers.append({
                "model_name": model_name,
                "short_name": config.short_name,
                "description": config.description,
                "recommended_for": getattr(config, "recommended_for", ""),
                "gpu_default": config.gpu_default,
            })
        return {"rerankers": rerankers, "count": len(rerankers)}
    except Exception as exc:
        logger.error("Failed to load reranker catalog: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to load reranker catalog: {exc}")
